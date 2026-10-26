#!/usr/bin/env python3
"""!The toolkit's Python environment: one virtual environment for every
capsule-studio tool, created and kept up to date automatically.

    python3 toolkit/env.py setup [--core-only] [--wheels DIR] [--offline] [--reset]
    python3 toolkit/env.py status [--check [--core-only]]
    python3 toolkit/env.py run TOOL [ARGS...]
    python3 toolkit/env.py fetch-wheels [--dest DIR] [--platform TAG ...] [--python-version X.Y]

The launchers in the repository root (scene-editor, capsule-studio and their
.cmd twins for Windows) call `run`, so a fresh checkout works without any
manual step: the first run creates .venv/ in the repository root and installs
the pinned packages from toolkit/requirements/ into it. Nothing is installed
system-wide and no administrator rights are needed. When a requirements file
changes (e.g. a version bump is pulled), the next run installs the
difference.

Secure or offline machines: put the wheel files in wheels/ (or pass --wheels
DIR, or set CAPSULE_STUDIO_WHEELS) and installs use only those files, never
the network. `fetch-wheels` downloads them on a connected machine, for this
platform or for others (--platform, e.g. win_amd64, manylinux_2_28_x86_64,
macosx_13_0_universal2). Only binary wheels are ever installed, so no package
code runs at install time.

The editors that play audio (audio-editor, studio) also install the optional
"audio" group (Qt Multimedia from PySide6-Addons, toolkit/requirements/
audio.txt), and so does `setup`. When it cannot be installed (no wheel for the
platform, an offline wheel folder without it) the tools start anyway and Play
uses the system's player; a launch does not try again, `setup` does.

Uses only the standard library and starts on Python 3.7 or later; if the interpreter
that started it is older than MIN_PYTHON, it looks for a newer one and hands
over to it.
"""
# Keeps annotations unevaluated, so this file still starts (and hands over) on Python 3.7-3.9.
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
   from typing import Any, NoReturn

## Oldest Python the tools run on (PySide6 6.11 needs 3.10).
MIN_PYTHON = (3, 10)
## Newest minor version looked for when searching for an interpreter.
MAX_MINOR = 15
## This directory (toolkit/).
TOOLKIT = Path(__file__).resolve().parent
## Repository root.
ROOT = TOOLKIT.parent
## Pinned requirement files, one per dependency group.
REQUIREMENTS = TOOLKIT / "requirements"
## Dependency groups and their files. "core" is what headless tools need; "audio" (C14b) is Qt Multimedia for
## playing audio inside the editors.
GROUPS = {"core": REQUIREMENTS / "core.txt", "ui": REQUIREMENTS / "ui.txt", "audio": REQUIREMENTS / "audio.txt"}
## Optional groups and what works without them: a failed install warns and the tools start anyway (a launch does
## not retry it; `setup` does).
OPTIONAL = {"audio": "audio plays in the system's player instead of inside the editor"}
## The state file's mark of an optional group whose install failed (followed by the digest it was tried with).
FAILED_MARK = "failed:"
## Tools: name -> (module run with -m, dependency groups it needs).
TOOLS = {
   "capsule-studio": ("capsule_studio.cli", ["core"]),
   "scene-editor": ("capsule_studio.ui", ["core", "ui"]),
   "map-editor": ("capsule_studio.ui.world_app", ["core", "ui"]),
   "battle-editor": ("capsule_studio.ui.battle_app", ["core", "ui"]),
   "battle-structure": ("capsule_studio.ui.battle_structure_app", ["core", "ui"]),
   "battle-logic": ("capsule_studio.ui.battle_logic_app", ["core", "ui"]),
   "encounter-editor": ("capsule_studio.ui.encounter_app", ["core", "ui"]),
   "script-editor": ("capsule_studio.ui.script_app", ["core", "ui"]),
   "project-settings": ("capsule_studio.ui.project_app", ["core", "ui"]),
   "event-editor": ("capsule_studio.ui.event_app", ["core", "ui"]),
   "object-editor": ("capsule_studio.ui.object_app", ["core", "ui"]),
   "location-editor": ("capsule_studio.ui.location_app", ["core", "ui"]),
   "audio-editor": ("capsule_studio.ui.audio_app", ["core", "ui", "audio"]),
   "studio": ("capsule_studio.ui.studio_app", ["core", "ui", "audio"]),
}
## Source folders made importable inside the environment (through a .pth file).
SOURCE_DIRS = [ROOT / "editor"]
## Name of the .pth file written into the environment.
PTH_NAME = "capsule_studio_toolkit.pth"
## File in the environment recording what was installed.
STATE_NAME = "capsule-studio-state.json"
## Seconds to wait for an interpreter to report its version.
VERSION_CHECK_TIMEOUT = 30
## Leading fields of sys.version_info that make (major, minor).
MAJOR_MINOR = 2
## Indentation of the state file's JSON.
STATE_JSON_INDENT = 2


def venv_dir() -> Path:
   """!Where the environment lives (CAPSULE_STUDIO_VENV overrides .venv/).
   @return Path
   """
   return Path(os.environ.get("CAPSULE_STUDIO_VENV") or ROOT / ".venv")


def wheels_dir(override: str | Path | None = None) -> Path | None:
   """!The local wheel folder to install from, if any.
   @param override  --wheels value, or None
   @return Path, or None to use the package index
   """
   d = override or os.environ.get("CAPSULE_STUDIO_WHEELS")
   if d:
      return Path(d).expanduser().resolve()
   local = ROOT / "wheels"
   return local if local.is_dir() and any(local.glob("*.whl")) else None


def say(text: str) -> None:
   """!Prints a progress line.
   @param text  message
   @return None
   """
   print(f"capsule-studio: {text}", flush=True)


def fail(text: str) -> NoReturn:
   """!Stops with an error.
   @param text  message
   @return never (exits)
   """
   sys.exit(f"capsule-studio: error: {text}")


# -- finding an interpreter ----------------------------------------------------------

def version_of(python: list[str]) -> tuple[int, int] | None:
   """!Version of an interpreter.
   @param python  command (list of strings)
   @return (major, minor), or None when it doesn't run
   """
   try:
      out = subprocess.run(python + ["-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                           capture_output=True, text=True, timeout=VERSION_CHECK_TIMEOUT)
   except (OSError, subprocess.SubprocessError):
      return None
   if out.returncode != 0:
      return None
   major, minor = out.stdout.split()
   return int(major), int(minor)


def find_python() -> list[str] | None:
   """!A Python of at least MIN_PYTHON, newest first.
   @return command (list of strings), or None
   """
   found: list[list[str]] = []
   for minor in range(MAX_MINOR, MIN_PYTHON[1] - 1, -1):
      if os.name == "nt":
         if shutil.which("py"):
            found.append(["py", f"-3.{minor}"])
      else:
         exe = shutil.which(f"python3.{minor}")
         if exe:
            found.append([exe])
   found += [[c] for c in ("python3", "python") if shutil.which(c)]
   for cmd in found:
      v = version_of(cmd)
      if v is not None and v >= MIN_PYTHON:
         return cmd
   return None


def install_hint() -> str:
   """!How to get a suitable Python on this system.
   @return text
   """
   if os.name == "nt":
      return "install it with 'winget install Python.Python.3.12' (or run install\\install.ps1)"
   if sys.platform == "darwin":
      return "install it with 'brew install python' (or run install/install.sh)"
   return "install your distribution's python3 package (or run install/install.sh)"


def handoff_if_too_old() -> None:
   """!Re-runs this script under a new enough Python when the current one is older.
   @return None
   """
   if sys.version_info[:MAJOR_MINOR] >= MIN_PYTHON:
      return
   cmd = find_python()
   if cmd is None:
      fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or later is needed "
           f"(this is {sys.version.split()[0]}); {install_hint()}")
   sys.exit(subprocess.call(cmd + [str(Path(__file__).resolve())] + sys.argv[1:]))


# -- the environment ---------------------------------------------------------------------

def venv_python() -> Path:
   """!The environment's interpreter.
   @return Path
   """
   return venv_dir() / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def load_state() -> dict[str, Any]:
   """!What was installed last time.
   @return dict
   """
   try:
      return json.loads((venv_dir() / STATE_NAME).read_text(encoding="utf-8"))
   except (OSError, ValueError):
      return {}


def save_state(state: dict[str, Any]) -> None:
   """!Records what is installed.
   @param state  dict
   @return None
   """
   (venv_dir() / STATE_NAME).write_text(json.dumps(state, indent=STATE_JSON_INDENT) + "\n", encoding="utf-8")


def requirement_lines(group: str) -> list[str]:
   """!The package lines of a group's requirements file.
   @param group  group name
   @return list of requirement strings (comments and blanks dropped)
   """
   lines: list[str] = []
   for line in GROUPS[group].read_text(encoding="utf-8").splitlines():
      line = line.split("#", 1)[0].strip()
      if line:
         lines.append(line)
   return lines


def digest(group: str) -> str:
   """!Fingerprint of a group's requirements, to notice when they change.
   @param group  group name
   @return hex string
   """
   return hashlib.sha256("\n".join(requirement_lines(group)).encode("utf-8")).hexdigest()


def healthy() -> bool:
   """!Whether the environment exists and its interpreter runs.
   @return True or False
   """
   return venv_python().exists() and version_of([str(venv_python())]) is not None


def create(reset: bool = False) -> None:
   """!Creates the environment (again, with @p reset or when broken).
   @param reset  delete and recreate it
   @return None
   """
   d = venv_dir()
   if d.exists() and (reset or not healthy()):
      if not (d / "pyvenv.cfg").exists():
         fail(f"{d} exists but is not a virtual environment; move it away first")
      say(f"recreating {d}" if reset else f"{d} is broken (its Python moved?), recreating it")
      shutil.rmtree(d)
   if d.exists():
      return
   say(f"creating the toolkit environment in {d}")
   try:
      venv.EnvBuilder(with_pip=True).create(d)
   except (OSError, subprocess.CalledProcessError) as e:
      shutil.rmtree(d, ignore_errors=True)
      hint = " (on Debian/Ubuntu: sudo apt install python3-venv)" if sys.platform.startswith("linux") else ""
      fail(f"could not create the environment: {e}{hint}")
   save_state({"python": "{}.{}".format(*sys.version_info[:MAJOR_MINOR]), "groups": {}})


def link_sources() -> None:
   """!Makes the toolkit's source folders importable inside the environment.
   @return None
   """
   out = subprocess.run([str(venv_python()), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                        capture_output=True, text=True, check=True)
   # A .pth file in site-packages adds each line (a folder) to sys.path.
   site = Path(out.stdout.strip())
   text = "".join(f"{p}\n" for p in SOURCE_DIRS)
   pth = site / PTH_NAME
   if not pth.exists() or pth.read_text(encoding="utf-8") != text:
      pth.write_text(text, encoding="utf-8")


def pip_install(group: str, wheels: Path | None = None, offline: bool = False) -> bool:
   """!Installs one group's pinned packages into the environment.
   @param group    group name
   @param wheels   local wheel folder, or None
   @param offline  never use the network (needs @p wheels)
   @return True when installed; False when an OPTIONAL group could not be (a required group stops instead)
   """
   packages = requirement_lines(group)
   if not packages:
      return True
   cmd = [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
          "--only-binary=:all:", "-r", str(GROUPS[group])]
   if wheels is not None:
      cmd += ["--no-index", "--find-links", str(wheels)]
      say(f"installing {group} packages from {wheels}: {', '.join(packages)}")
   elif offline:
      if group in OPTIONAL:
         say(f"skipping the optional {group} packages (offline without a wheel folder): {OPTIONAL[group]}")
         return False
      fail("offline install needs a wheel folder (wheels/, --wheels or CAPSULE_STUDIO_WHEELS)")
   else:
      say(f"installing {group} packages (first run, or the pins changed): {', '.join(packages)}")
   if subprocess.call(cmd) != 0:
      where = f"the wheels in {wheels}" if wheels else "the package index (network?)"
      if group in OPTIONAL:
         say(f"warning: the optional {group} packages could not be installed from {where}: {OPTIONAL[group]}. "
             "Run 'toolkit/env.py setup' to try again (offline: add their wheels to wheels/, see 'fetch-wheels').")
         return False
      fail(f"pip could not install the {group} packages from {where}; nothing else was changed. "
           "On machines without network access, copy the wheels into wheels/ (see 'fetch-wheels').")
   return True


def ensure(groups: list[str], wheels: Path | None = None, offline: bool = False, reset: bool = False,
           retry: bool = False) -> None:
   """!Makes sure the environment exists with these groups installed and
   current; does nothing when it already is. An optional group whose install
   failed for the current pins is not tried again unless @p retry.
   @param groups   group names
   @param wheels   local wheel folder, or None for wheels_dir()
   @param offline  never use the network
   @param reset    recreate the environment first
   @param retry    try optional groups that failed before again (setup)
   @return None
   """
   create(reset)
   state = load_state()
   done = state.setdefault("groups", {})
   wheels = wheels or wheels_dir()
   for g in groups:
      if done.get(g) == digest(g) or (done.get(g) == FAILED_MARK + digest(g) and not retry):
         continue
      done[g] = digest(g) if pip_install(g, wheels, offline) else FAILED_MARK + digest(g)
      save_state(state)
   link_sources()


# -- commands --------------------------------------------------------------------------------

def cmd_setup(args: argparse.Namespace) -> int:
   """!setup: create or update the environment.
   @param args  parsed arguments
   @return exit status
   """
   groups = ["core"] if args.core_only else list(GROUPS)
   ensure(groups, Path(args.wheels).resolve() if args.wheels else None, args.offline, args.reset, retry=True)
   done = load_state().get("groups", {})
   ready = [g for g in groups if done.get(g) == digest(g)]
   say(f"ready: {venv_dir()} ({', '.join(ready)})")
   for g in groups:
      if g not in ready:
         say(f"without the optional {g} packages: {OPTIONAL[g]}")
   return 0


def cmd_status(args: argparse.Namespace) -> int:
   """!status: what is installed.
   @param args  parsed arguments
   @return 0, or 1 with --check when something is missing or out of date
   """
   ok = healthy()
   print(f"environment: {venv_dir()} ({'ok' if ok else 'missing'})")
   state = load_state() if ok else {}
   if ok:
      print(f"python:      {state.get('python', '?')}")
   complete = ok
   needed = ["core"] if args.core_only else list(GROUPS)
   for g in GROUPS:
      installed = state.get("groups", {}).get(g)
      if installed == digest(g):
         mark = "current"
      elif installed == FAILED_MARK + digest(g):
         mark = "install failed"
      else:
         mark = "outdated" if installed else "not installed"
      if g in OPTIONAL and mark != "current":
         mark += f" (optional: {OPTIONAL[g]})"
      complete = complete and (mark == "current" or g not in needed or g in OPTIONAL)
      print(f"{g + ':':12} {mark}  ({', '.join(requirement_lines(g)) or 'no packages'})")
   w = wheels_dir()
   print(f"wheels:      {w if w else 'none (installs use the package index)'}")
   return 0 if complete or not args.check else 1


def cmd_run(args: argparse.Namespace) -> int:
   """!run: start a tool inside the environment, setting it up first if needed.
   @param args  parsed arguments
   @return the tool's exit status
   """
   if args.tool not in TOOLS:
      fail(f"unknown tool {args.tool!r} (tools: {', '.join(TOOLS)})")
   module, groups = TOOLS[args.tool]
   ensure(groups)
   cmd = [str(venv_python()), "-m", module] + args.args
   if os.name != "nt":
      os.execv(cmd[0], cmd)   # the tool replaces this process (signals, exit status)
   return subprocess.call(cmd)


def cmd_fetch_wheels(args: argparse.Namespace) -> int:
   """!fetch-wheels: download every pinned package as wheels, for offline installs.
   @param args  parsed arguments
   @return exit status
   """
   ensure(["core"])
   dest = Path(args.dest).resolve()
   dest.mkdir(parents=True, exist_ok=True)
   for g in GROUPS:
      if not requirement_lines(g):
         continue
      cmd = [str(venv_python()), "-m", "pip", "download", "--disable-pip-version-check", "--no-input",
             "--only-binary=:all:", "-r", str(GROUPS[g]), "--dest", str(dest)]
      for p in args.platform or []:
         cmd += ["--platform", p]
      if args.platform:
         cmd += ["--implementation", "cp", "--python-version", args.python_version]
      if subprocess.call(cmd) != 0:
         if g in OPTIONAL:
            say(f"warning: could not download the optional {g} wheels ({OPTIONAL[g]} on the target machine)")
            continue
         fail(f"could not download the {g} wheels")
   say(f"wheels in {dest}; copy them to wheels/ on the target machine")
   return 0


def main(argv: list[str] | None = None) -> int:
   """!Command-line entry point; see the module docstring.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   handoff_if_too_old()
   p = argparse.ArgumentParser(prog="toolkit/env.py", description="The capsule-studio toolkit environment.")
   sub = p.add_subparsers(dest="command", metavar="COMMAND")
   sub.required = True
   q = sub.add_parser("setup", help="create or update the environment")
   q.add_argument("--core-only", action="store_true", help="headless tools only (no PySide6), e.g. CI")
   # the optional groups (audio) are tried on every setup; a failure warns and leaves the rest installed
   q.add_argument("--wheels", metavar="DIR", help="install only from the wheel files in DIR")
   q.add_argument("--offline", action="store_true", help="never use the network")
   q.add_argument("--reset", action="store_true", help="delete and recreate the environment")
   q.set_defaults(run=cmd_setup)
   q = sub.add_parser("status", help="show what is installed")
   q.add_argument("--check", action="store_true", help="exit with status 1 unless everything is current")
   q.add_argument("--core-only", action="store_true", help="with --check: only the headless tools' packages")
   q.set_defaults(run=cmd_status)
   q = sub.add_parser("run", help="run a tool in the environment")
   q.add_argument("tool", help=", ".join(TOOLS))
   q.add_argument("args", nargs=argparse.REMAINDER, help="arguments for the tool")
   q.set_defaults(run=cmd_run)
   q = sub.add_parser("fetch-wheels", help="download the pinned packages as wheels for offline installs")
   q.add_argument("--dest", default=str(ROOT / "wheels"), help="folder (default: wheels/)")
   q.add_argument("--platform", action="append", metavar="TAG",
                  help="target platform tag (repeatable), e.g. win_amd64; default: this machine")
   q.add_argument("--python-version", default="3.12", help="target Python with --platform (default 3.12)")
   q.set_defaults(run=cmd_fetch_wheels)
   args = p.parse_args(argv)
   return args.run(args)


if __name__ == "__main__":
   sys.exit(main())
