#!/usr/bin/env python3
"""!Builds and smoke-tests the prebuilt studio bundle for this machine's platform (RI).

    python3 build_bundle.py build [--version V] [--work DIR] [--require-licence]
    python3 build_bundle.py smoke ARCHIVE [--work DIR]

`build` stages the studio's sources, the engine files the studio reads and the notices; draws the icons; runs
PyInstaller on capsule_studio.spec (one-folder, Qt as separate shared libraries); adds the README, licence and
launchers; and writes the download:
   linux-x86_64       capsule-studio-<version>-linux-x86_64.tar.gz
   windows-x64        capsule-studio-<version>-windows-x64.zip
   macos-universal2   capsule-studio-<version>-macos-universal2.zip (CapsuleStudio.app, unsigned)
It prints the archive's path last. It runs in the Python that will be bundled, with PySide6 (toolkit/requirements/
ui.txt) and the pinned PyInstaller (requirements-bundle.txt) installed. Nothing outside --work is written, and
--work must be new or empty (nothing is ever deleted).

`smoke` unpacks a download into a new folder (what a user gets), checks the Qt libraries are plain, replaceable
files with no unused Qt module among them, and runs both executables with --bundle-smoke (bundle_smoke.py) on Qt's
offscreen platform.

See packaging/README.md for the layout and the choices behind it.
"""
from __future__ import annotations

import argparse
import compileall
import json
import os
import platform
import py_compile
import runpy
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

## This folder (toolkit/packaging).
HERE = Path(__file__).resolve().parent
## The toolkit checkout.
TOOLKIT = HERE.parent
## The engine checkout beside it (the umbrella's engine/ submodule; CAPSULE_ENGINE overrides).
ENGINE_DEFAULT = TOOLKIT.parent / "engine"
## Name of every download and of the folder inside it.
PRODUCT = "capsule-studio"
## Platforms: name -> (sys.platform, archive suffix).
PLATFORMS = {"linux-x86_64": ("linux", "tar.gz"), "windows-x64": ("win32", "zip"),
             "macos-universal2": ("darwin", "zip")}
## The macOS target architecture (both Apple silicon and Intel).
MAC_ARCH = "universal2"
## The macOS app's name (capsule_studio.spec BUNDLE).
MAC_APP = "CapsuleStudio.app"
## PyInstaller's output folder name (capsule_studio.spec COLLECT).
COLLECT_NAME = "capsule-studio"
## The two executables (capsule_studio.spec EXE names).
GUI_EXE = "studio"
CLI_EXE = "capsule-studio"
## The toolkit's sources the studio runs (below the toolkit checkout).
EDITOR_SOURCES = "editor/capsule_studio"
## Engine folders (top level) a bundle leaves out: tests, CI and editor settings, the libgba submodule (GBA builds
## use devkitPro's own copy). Everything else the studio may read (tools, include, assets, samples, CMake files)
## is copied.
ENGINE_SKIPPED = {"tests", ".github", ".vscode", "submodules"}
## Licence and notice files copied from the toolkit's root (glob patterns; RD/RT name them).
LICENCE_PATTERNS = ("LICENSE*", "LICENCE*", "COPYING*")
NOTICE_PATTERNS = ("THIRD_PARTY*", "NOTICE*")
## The bundle's README (packaging/notices/BUNDLE_README.md, shipped as README.md).
README_SOURCE = "BUNDLE_README.md"
README_NAME = "README.md"
## Places of the Python licence text, relative to sys.base_prefix (python.org, setup-python, Debian).
PYTHON_LICENCE_PLACES = ("LICENSE.txt", f"lib/python{sys.version_info[0]}.{sys.version_info[1]}/LICENSE.txt",
                         "share/doc/python3/copyright", "Resources/English.lproj/License.txt")
## The bundled copy of it.
PYTHON_LICENCE_NAME = "PYTHON-LICENSE.txt"
## Linux icon size copied beside the executables, and the menu-entry helper.
LINUX_ICON_SIZE = 256
LINUX_MENU_SCRIPT = "add-to-menu.sh"
## Editors that get a launcher of their own beside the executables (Linux shell scripts, Windows .cmd files).
NO_LAUNCHER = {"studio", "capsule-studio"}
## File mode of the Linux launchers (rwxr-xr-x).
EXEC_MODE = 0o755
## Qt library modules a bundle must not carry (the studio imports only QtCore, QtGui and QtWidgets).
UNUSED_QT = ("Qml", "Quick", "Network", "Multimedia", "WebEngine", "Pdf", "Sql", "Svg", "Test", "Designer",
             "Charts", "3D")
## Qt Core's library name per platform (the one file every bundle must hold as a plain, replaceable file).
QT_CORE = {"linux": "libQt6Core.so.6", "win32": "Qt6Core.dll", "darwin": "QtCore"}
## Seconds each smoke run may take.
SMOKE_TIMEOUT = 600
## Version used when none is given (the toolkit's own calendar version).
VERSION_FALLBACK = "0000.00.00.0000"


def say(text: str) -> None:
   """!Prints a progress line.
   @param text  message
   @return None
   """
   print(f"build_bundle: {text}", flush=True)


def fail(text: str) -> None:
   """!Stops with an error.
   @param text  message
   @return never (exits)
   """
   sys.exit(f"build_bundle: error: {text}")


def this_platform() -> str:
   """!This machine's platform name (PLATFORMS).
   @return name
   """
   for name, (plat, _suffix) in PLATFORMS.items():
      if sys.platform == plat:
         return name
   fail(f"no bundle for {sys.platform}")
   return ""


def default_version() -> str:
   """!The toolkit's own calendar version (capsule_studio.__calver__), read without importing the package.
   @return version text
   """
   init = TOOLKIT / EDITOR_SOURCES / "__init__.py"
   for line in init.read_text(encoding="utf-8").splitlines():
      if line.startswith("__calver__"):
         return line.split("=", 1)[1].strip().strip("\"'")
   return VERSION_FALLBACK


def new_folder(path: Path) -> Path:
   """!Creates a folder that must be new or empty (the build never deletes anything).
   @param path  the folder
   @return the resolved path
   """
   path = path.resolve()
   if path.exists() and any(path.iterdir()):
      fail(f"{path} is not empty; pass a new --work folder")
   path.mkdir(parents=True, exist_ok=True)
   return path


def tracked_files(repo: Path, below: str = "") -> list[str]:
   """!The files git tracks in a checkout (as they are in the working tree), '/'-separated.
   @param repo   the checkout
   @param below  limit to this folder, or "" for all
   @return relative paths
   """
   cmd = ["git", "-C", str(repo), "ls-files", "-z"] + ([below] if below else [])
   out = subprocess.run(cmd, capture_output=True, check=True).stdout.decode("utf-8")
   return [p for p in out.split("\0") if p and (repo / p).is_file()]


def copy_files(repo: Path, files: list[str], dest: Path) -> int:
   """!Copies files keeping their relative paths.
   @param repo   where they are
   @param files  relative paths
   @param dest   target folder
   @return number copied
   """
   for rel in files:
      target = dest / rel
      target.parent.mkdir(parents=True, exist_ok=True)
      shutil.copy2(repo / rel, target)
   return len(files)


def root_files(folder: Path, patterns: tuple[str, ...]) -> list[Path]:
   """!Files at a folder's top matching any pattern.
   @param folder    the folder
   @param patterns  glob patterns
   @return sorted Paths
   """
   return sorted({f for p in patterns for f in folder.glob(p) if f.is_file()})


def python_licence() -> Path:
   """!The licence text of the Python that is bundled.
   @return Path
   """
   bases = [Path(sys.base_prefix), Path(sys.base_prefix).parent]
   for base in bases:
      for place in PYTHON_LICENCE_PLACES:
         if (base / place).is_file():
            return base / place
   fail(f"no Python licence text found under {sys.base_prefix}")
   return Path()


def tool_table() -> dict[str, str]:
   """!toolkit/env.py's TOOLS as name -> module.
   @return dict
   """
   env = runpy.run_path(str(TOOLKIT / "toolkit" / "env.py"))
   return {name: module for name, (module, _groups) in env["TOOLS"].items()}


def stage(stage_dir: Path, engine: Path, require_licence: bool) -> list[Path]:
   """!Copies what the bundle carries as plain files into the stage folder.
   @param stage_dir        the (new) stage folder
   @param engine           the engine checkout
   @param require_licence  stop when the toolkit has no licence file
   @return the toolkit's licence and notice files (for the download's top level)
   """
   n = copy_files(TOOLKIT, tracked_files(TOOLKIT, EDITOR_SOURCES), stage_dir / "toolkit")
   say(f"staged {n} studio files")
   files = [f for f in tracked_files(engine) if f.split("/")[0] not in ENGINE_SKIPPED]
   n = copy_files(engine, files, stage_dir / "engine")
   say(f"staged {n} engine files from {engine}")
   licences = root_files(TOOLKIT, LICENCE_PATTERNS)
   if not licences:
      if require_licence:
         fail(f"the toolkit has no licence file ({', '.join(LICENCE_PATTERNS)}) at {TOOLKIT}")
      say("warning: the toolkit has no licence file yet; this bundle must not be published")
   tops = licences + root_files(TOOLKIT, NOTICE_PATTERNS)
   notices = stage_dir / "notices"
   # The bundle's README goes to the download's top level (assemble()), not among the notices.
   shutil.copytree(HERE / "notices", notices, ignore=shutil.ignore_patterns(README_SOURCE))
   for f in tops:
      shutil.copy2(f, notices / f.name)
   shutil.copy2(python_licence(), notices / PYTHON_LICENCE_NAME)
   (stage_dir / "bundle_tools.json").write_text(json.dumps(tool_table(), indent=1), encoding="utf-8")
   # Compiled once here, for the bundled Python; unchecked-hash .pyc files are used whatever the files' times.
   ok = compileall.compile_dir(str(stage_dir), quiet=1,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
   if not ok:
      fail("a staged Python file does not compile")
   return tops


def run_pyinstaller(work: Path, stage_dir: Path, icons: Path, version: str) -> Path:
   """!Runs PyInstaller on capsule_studio.spec.
   @param work       the work folder
   @param stage_dir  the stage folder
   @param icons      the icons folder
   @param version    the release version
   @return PyInstaller's dist folder
   """
   env = dict(os.environ, CAPSULE_BUNDLE_STAGE=str(stage_dir), CAPSULE_BUNDLE_ICONS=str(icons),
              CAPSULE_BUNDLE_VERSION=version)
   if sys.platform == "darwin":
      env["CAPSULE_BUNDLE_ARCH"] = MAC_ARCH
   dist = work / "pyinstaller-dist"
   cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--log-level", "WARN", "--distpath", str(dist),
          "--workpath", str(work / "pyinstaller-work"), str(HERE / "capsule_studio.spec")]
   say("running " + " ".join(cmd))
   if subprocess.call(cmd, env=env) != 0:
      fail("PyInstaller failed")
   return dist


def write_launchers(folder: Path, tools: dict[str, str]) -> None:
   """!One launcher per editor beside the executables (Linux: shell scripts; Windows: .cmd files).
   @param folder  the download's folder
   @param tools   tool table
   @return None
   """
   for name in sorted(t for t in tools if t not in NO_LAUNCHER):
      if sys.platform == "win32":
         # start: a windowed program; the empty "" is start's window title.
         text = f'@start "" "%~dp0{GUI_EXE}.exe" {name} %*\r\n'
         (folder / f"{name}.cmd").write_text(text, encoding="utf-8", newline="")
      else:
         f = folder / name
         f.write_text(f'#!/bin/sh\n# Starts the {name} of this bundle.\nexec "$(dirname "$0")/{GUI_EXE}" {name} "$@"\n',
                      encoding="utf-8")
         f.chmod(EXEC_MODE)


def assemble(dist: Path, out: Path, stage_dir: Path, icons: Path, tops: list[Path], version: str) -> None:
   """!Lays out the download's folder: the program, README, licence and notices.
   @param dist       PyInstaller's dist folder
   @param out        the download's (new) folder
   @param stage_dir  the stage folder (notices)
   @param icons      the icons folder
   @param tops       licence and notice files for the top level
   @param version    the release version
   @return None
   """
   if sys.platform == "darwin":
      shutil.copytree(dist / MAC_APP, out / MAC_APP, symlinks=True)
   else:
      for f in sorted((dist / COLLECT_NAME).iterdir()):
         if f.is_dir():
            shutil.copytree(f, out / f.name, symlinks=True)
         else:
            shutil.copy2(f, out / f.name)
      write_launchers(out, tool_table())
   if sys.platform == "linux":
      shutil.copy2(icons / f"{PRODUCT}-{LINUX_ICON_SIZE}.png", out / f"{PRODUCT}.png")
      shutil.copy2(HERE / "linux" / LINUX_MENU_SCRIPT, out / LINUX_MENU_SCRIPT)
      (out / LINUX_MENU_SCRIPT).chmod(EXEC_MODE)
   shutil.copy2(HERE / "notices" / README_SOURCE, out / README_NAME)
   for f in tops:
      shutil.copy2(f, out / f.name)
   shutil.copytree(stage_dir / "notices", out / "notices")
   (out / "VERSION.txt").write_text(f"{PRODUCT} {version}\n" + describe_sources(), encoding="utf-8")


def describe_sources() -> str:
   """!Which commits the bundle was built from (for VERSION.txt).
   @return lines
   """
   lines = []
   for name, repo in (("toolkit", TOOLKIT), ("engine", engine_dir())):
      done = subprocess.run(["git", "-C", str(repo), "describe", "--always", "--dirty", "--tags"],
                            capture_output=True, text=True, check=False)
      lines.append(f"{name} {done.stdout.strip() or 'unknown'}\n")
   lines.append(f"python {platform.python_version()}\n")
   return "".join(lines)


def engine_dir() -> Path:
   """!The engine checkout to copy from.
   @return Path
   """
   return Path(os.environ.get("CAPSULE_ENGINE") or ENGINE_DEFAULT).resolve()


def archive(folder: Path, suffix: str) -> Path:
   """!Packs the download's folder.
   @param folder  the folder (its name is the archive's top folder)
   @param suffix  "tar.gz" or "zip"
   @return the archive
   """
   target = folder.parent / f"{folder.name}.{suffix}"
   if sys.platform == "darwin":
      # The system's zip keeps the app's symbolic links (-y) and permissions, so its code signatures stay valid
      # (zipfile would turn the links into copies).
      cmd = ["zip", "-q", "-r", "-y", str(target), folder.name]
      if subprocess.call(cmd, cwd=folder.parent) != 0:
         fail("zip failed")
   elif suffix == "tar.gz":
      with tarfile.open(target, "w:gz") as tar:
         tar.add(folder, arcname=folder.name)
   else:
      with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
         for f in sorted(folder.rglob("*")):
            z.write(f, Path(folder.name) / f.relative_to(folder))
   return target


def cmd_build(args: argparse.Namespace) -> int:
   """!build: see the module docstring.
   @param args  parsed arguments
   @return exit status
   """
   name = this_platform()
   version = args.version or default_version()
   work = new_folder(Path(args.work))
   engine = engine_dir()
   if not (engine / "tools" / "asset_compiler.py").is_file():
      fail(f"no engine checkout at {engine} (set CAPSULE_ENGINE)")
   stage_dir = work / "stage"
   tops = stage(stage_dir, engine, args.require_licence)
   icons = work / "icons"
   runpy.run_path(str(HERE / "make_icons.py"), run_name="make_icons")["main"]([str(icons)])
   dist = run_pyinstaller(work, stage_dir, icons, version)
   out = work / "out" / f"{PRODUCT}-{version}-{name}"
   out.mkdir(parents=True)
   assemble(dist, out, stage_dir, icons, tops, version)
   target = archive(out, PLATFORMS[name][1])
   say(f"wrote {target}")
   print(target)
   return 0


def unpack(target: Path, dest: Path) -> Path:
   """!Unpacks a download the way a user would.
   @param target  the archive
   @param dest    a new folder
   @return the folder inside the archive
   """
   if sys.platform == "darwin":
      if subprocess.call(["unzip", "-q", str(target), "-d", str(dest)]) != 0:
         fail("unzip could not unpack the archive")
   elif target.name.endswith(".tar.gz"):
      with tarfile.open(target) as tar:
         tar.extractall(dest, filter="data")
   else:
      with zipfile.ZipFile(target) as z:
         z.extractall(dest)
   inner = [p for p in dest.iterdir() if p.is_dir()]
   if len(inner) != 1:
      fail(f"{target.name} should hold one folder, not {len(inner)}")
   return inner[0]


def executables(folder: Path) -> list[Path]:
   """!The bundle's two executables.
   @param folder  the unpacked download
   @return [studio, capsule-studio]
   """
   if sys.platform == "darwin":
      base = folder / MAC_APP / "Contents" / "MacOS"
   else:
      base = folder
   suffix = ".exe" if sys.platform == "win32" else ""
   return [base / f"{GUI_EXE}{suffix}", base / f"{CLI_EXE}{suffix}"]


def check_qt(folder: Path) -> list[str]:
   """!Problems with the bundle's Qt libraries: Qt Core must be a plain file (replaceable, LGPL-3), and no unused Qt
   module may be there.
   @param folder  the unpacked download
   @return problem texts (empty when fine)
   """
   problems = []
   core = [f for f in folder.rglob(QT_CORE[sys.platform]) if f.is_file()]
   if not core:
      problems.append(f"no {QT_CORE[sys.platform]} file in the bundle")
   for f in folder.rglob("*"):
      name = f.name
      for unused in UNUSED_QT:
         if name.startswith((f"libQt6{unused}", f"Qt6{unused}", f"Qt{unused}.framework", f"Qt{unused}.abi3")):
            problems.append(f"unused Qt module in the bundle: {f.relative_to(folder)}")
   return problems


def cmd_smoke(args: argparse.Namespace) -> int:
   """!smoke: see the module docstring.
   @param args  parsed arguments
   @return exit status
   """
   target = Path(args.archive).resolve()
   work = new_folder(Path(args.work))
   folder = unpack(target, work / "unpacked")
   say(f"unpacked {target.name} into {folder}")
   problems = check_qt(folder)
   for p in problems:
      say(f"problem: {p}")
   env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
   env.pop("PYTHONPATH", None)   # the bundle must not need anything from outside
   env.pop("CAPSULE_ENGINE", None)
   for exe in executables(folder):
      run_dir = work / f"run-{exe.stem}"
      say(f"smoke: {exe}")
      try:
         status = subprocess.call([str(exe), "--bundle-smoke", str(run_dir)], env=env, timeout=SMOKE_TIMEOUT)
      except subprocess.TimeoutExpired:
         status = None
      report = run_dir / "smoke.json"
      if report.is_file():
         print(report.read_text(encoding="utf-8"))   # the windowed program prints nothing itself
      if status != 0:
         problems.append(f"{exe.name} --bundle-smoke ended with {status}")
   if problems:
      fail("; ".join(problems))
   say("smoke test passed")
   return 0


def main(argv: list[str] | None = None) -> int:
   """!Command-line entry point.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   p = argparse.ArgumentParser(prog="build_bundle.py", description="Builds and tests the prebuilt studio bundle.")
   sub = p.add_subparsers(dest="command", metavar="COMMAND")
   sub.required = True
   q = sub.add_parser("build", help="build this platform's bundle")
   q.add_argument("--version", help="release version (YYYY.MM.DD.MMMM; default: the toolkit's __calver__)")
   q.add_argument("--work", default=str(TOOLKIT / "build" / "bundle"), help="new or empty work folder")
   q.add_argument("--require-licence", action="store_true", help="stop when the toolkit has no licence file")
   q.set_defaults(run=cmd_build)
   q = sub.add_parser("smoke", help="unpack a bundle and run its smoke test")
   q.add_argument("archive", help="the download built by `build`")
   q.add_argument("--work", default=str(TOOLKIT / "build" / "bundle-smoke"), help="new or empty work folder")
   q.set_defaults(run=cmd_smoke)
   args = p.parse_args(argv)
   return args.run(args)


if __name__ == "__main__":
   sys.exit(main())
