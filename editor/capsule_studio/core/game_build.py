"""!Building and running a game from the Studio and `capsule-studio build` (no Qt).

The same build as the umbrella's `./build PRESET --game FOLDER`: CMake is configured from the engine's folder with
one of its presets (engine/CMakePresets.json) into FOLDER/build/PRESET, with the game in CAPSULE_GAMES and the
engine's own tests off, then built. "Build and Debug" builds the target's debug preset and starts the result: the
executable on this computer, the ROM in a GBA emulator, the disc image in a Dreamcast emulator.

Which targets this computer can build is decided here, in TARGETS, and nowhere in the editors: the computer the
Studio runs on is always one target (its own preset family), the GBA builds everywhere and the Dreamcast
everywhere but Windows (the presets' own host conditions). Target modules (ProjectPeridot) are meant to replace
this table later; the editors only see BuildTarget.

Nothing here runs anything when imported: plan() describes the steps, run_plan() runs them for the command line,
and the Studio's build bar runs the same steps through QProcess.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import bench, engine, manifest_io

## A game folder's manifest, relative to the folder (what ./build --game checks).
PROJECT_MANIFEST = Path("reference") / "project.json"
## Where a game's builds go, inside its folder: one folder per preset (FOLDER/build/PRESET, as ./build --game).
BUILD_FOLDER = "build"
## Each game target's name: this prefix and the project's "name" (the engine's capsule_game()).
TARGET_PREFIX = "capsule_"
## Environment variable naming a GBA emulator command (the ROM's path is added at the end).
GBA_EMULATOR_ENV = "CAPSULE_GBA_EMULATOR"
## Environment variable naming a Dreamcast emulator command (the disc image's path is added at the end).
DC_EMULATOR_ENV = "CAPSULE_DC_EMULATOR"
## Environment variable naming No$GBA's NO$GBA.EXE (the backup GBA emulator, run in Wine off Windows).
NOCASH_ENV = "CAPSULE_NOCASH_GBA"
## Environment variable naming the MSYS2 install whose UCRT64 tools build on Windows (default MSYS2_DEFAULT).
MSYS2_ENV = "MSYS2_ROOT"
## Where MSYS2 installs by default.
MSYS2_DEFAULT = "C:/msys64"
## MSYS2 folders put in front of PATH for a Windows build when gcc is not on PATH already.
MSYS2_BIN_FOLDERS = ("ucrt64/bin", "usr/bin")
## devkitPro's folder when DEVKITPRO is not set (the engine's GBA toolchain file's default).
DEVKITPRO_DEFAULT = "/opt/devkitpro"
## devkitPro's Windows installer's folder (its own MSYS2 maps /opt/devkitpro there).
DEVKITPRO_WINDOWS = "C:/devkitPro"
## KallistiOS's environment script when KOS_ENVIRON is not set (the engine's Dreamcast toolchain file's default).
KOS_ENVIRON_DEFAULT = "/opt/toolchains/dc/kos/environ.sh"
## What the missing-toolchain messages point to.
SETUP_HINT = "run the umbrella's ./setup (setup.cmd on Windows) to install it"

## Kinds of run (BuildTarget.run_kind).
RUN_NATIVE = "native"
RUN_GBA = "gba"
RUN_DREAMCAST = "dreamcast"

## Flatpak application folders (system-wide and per user), for emulators installed through Flatpak.
FLATPAK_APP_FOLDERS = (Path("/var/lib/flatpak/app"), Path.home() / ".local/share/flatpak/app")
## mGBA: program names on PATH, its Flatpak id, and install locations off PATH.
MGBA_PROGRAMS = ("mgba-qt", "mgba", "mGBA")
MGBA_FLATPAK = "io.mgba.mGBA"
MGBA_KNOWN = ("/Applications/mGBA.app/Contents/MacOS/mGBA", "C:/Program Files/mGBA/mGBA.exe",
              "C:/Program Files (x86)/mGBA/mGBA.exe")
## mGBA built from a clone in the workspace (the folder beside the umbrella), relative to that clone.
MGBA_CLONE = "mgba"
MGBA_CLONE_BUILDS = ("build/qt/mgba-qt", "build/mgba-qt", "build/qt/mGBA.exe", "build/mGBA.exe")
## No$GBA's program file and where it is looked for (beside the umbrella, in Wine's C: drive).
NOCASH_EXE = "NO$GBA.EXE"
NOCASH_FOLDERS = ("no$gba", "nocash", "NO$GBA")
## Dreamcast emulators on PATH, in order of preference, and Flycast's Flatpak id.
DC_PROGRAMS = ("flycast", "redream", "lxdream")
DC_FLATPAK = "org.flycast.Flycast"


@dataclass(frozen=True)
class BuildTarget:
   """!One thing the Studio can build: a family of engine presets and what its build produces."""
   ## Id (the engine's platform name: desktop, gba, dreamcast).
   target_id: str
   ## Name shown in menus.
   title: str
   ## The engine preset of a debug build.
   debug_preset: str
   ## The engine preset of a release build.
   release_preset: str
   ## What starts it (RUN_NATIVE, RUN_GBA, RUN_DREAMCAST).
   run_kind: str
   ## The runnable file's suffix after capsule_<name> ("" or ".exe" for an executable, ".gba", ".cdi").
   output_suffix: str
   ## A second runnable file when the first is not made ("": none); a Dreamcast build without mkdcdisc makes the
   ## .elf only, which the emulators also start.
   fallback_suffix: str = ""

   def preset(self, debug: bool) -> str:
      """!The engine preset of a debug or release build.
      @param debug  True for the debug preset
      @return preset name
      """
      return self.debug_preset if debug else self.release_preset


@dataclass
class Step:
   """!One program the build runs."""
   ## What the log says it does.
   title: str
   ## The program and its arguments.
   argv: list[str]
   ## Folder it runs in.
   cwd: Path
   ## Environment variables set for it on top of the Studio's own.
   env: dict[str, str] = field(default_factory=dict)

   def program(self) -> str:
      """!The program to start: argv[0] found on the PATH the step runs with (on Windows that PATH may add MSYS2's
      tools, which a lookup on the Studio's own PATH would miss).
      @return its path, or argv[0] when it is not found there
      """
      return shutil.which(self.argv[0], path=self.env.get("PATH") or os.environ.get("PATH")) or self.argv[0]

   def shown(self) -> str:
      """!The command as a line for the log.
      @return the command line
      """
      return shlex.join(self.argv)


@dataclass
class BuildPlan:
   """!Everything one build of one target does."""
   ## The target.
   target: BuildTarget
   ## The engine preset.
   preset: str
   ## The game's folder (with reference/project.json).
   game: Path
   ## The project's name (its target is capsule_<name>).
   name: str
   ## The build folder (FOLDER/build/PRESET).
   out: Path
   ## Configure and build, in order.
   steps: list[Step]
   ## What is missing to build at all (empty: the steps can run).
   problems: list[str]
   ## Starts the result after the build, or None (a plain Build, or nothing to start it with).
   run: Step | None = None
   ## Why there is no run step although one was asked for (empty otherwise).
   run_problem: str = ""

   def output(self) -> Path | None:
      """!The runnable file the build made (the executable, ROM or disc image).
      @return its path, or None before it exists
      """
      return find_output(self.out, self.name, self.target)


def host_target() -> BuildTarget:
   """!This computer's own target (its preset family follows the host the Studio runs on).
   @return the target
   """
   if sys.platform == "win32":
      return BuildTarget("desktop", "This PC (Windows)", "windows-debug", "windows-release", RUN_NATIVE, ".exe")
   title = "This PC (macOS)" if sys.platform == "darwin" else "This PC (Linux)"
   return BuildTarget("desktop", title, "desktop-debug", "desktop-release", RUN_NATIVE, "")


## The GBA: every host builds it (the gba presets have no host condition).
GBA_TARGET = BuildTarget("gba", "Game Boy Advance", "gba-debug", "gba-release", RUN_GBA, ".gba")
## The Dreamcast: every host but Windows (the dc presets' condition).
DREAMCAST_TARGET = BuildTarget("dreamcast", "Dreamcast", "dc-debug", "dc-release", RUN_DREAMCAST, ".cdi", ".elf")


def targets() -> list[BuildTarget]:
   """!The targets this computer can build, this computer's own first.
   @return targets
   """
   out = [host_target(), GBA_TARGET]
   if sys.platform != "win32":
      out.append(DREAMCAST_TARGET)
   return out


def target(target_id: str) -> BuildTarget:
   """!One of targets() by id.
   @param target_id  its id (desktop, gba, dreamcast)
   @return the target
   @throws KeyError when this computer cannot build it
   """
   for t in targets():
      if t.target_id == target_id:
         return t
   raise KeyError(f"this computer cannot build {target_id!r} (it builds " + ", ".join(t.target_id for t in targets())
                  + ")")


# ---- the game --------------------------------------------------------------------------------------------------

def game_folder(path: str | Path) -> Path:
   """!The game folder of a reference/project.json, or a game folder itself.
   @param path  the manifest or the folder
   @return the folder, absolute
   @throws ValueError when it is not a game
   """
   p = Path(path).expanduser().resolve()
   folder = p.parent.parent if p.is_file() else p
   if not (folder / PROJECT_MANIFEST).is_file():
      raise ValueError(f"{path} is not a game folder (it has no {PROJECT_MANIFEST.as_posix()})")
   return folder


def project_name(folder: Path) -> str:
   """!The project's "name" (its build target is capsule_<name>).
   @param folder  the game folder
   @return the name
   @throws ValueError when the manifest cannot be read or has no name
   """
   try:
      data = manifest_io.load(folder / PROJECT_MANIFEST)
   except (OSError, ValueError) as e:
      raise ValueError(f"cannot read {folder / PROJECT_MANIFEST}: {e}") from None
   name = data.get("name") if isinstance(data, dict) else None
   if not isinstance(name, str) or not name:
      raise ValueError(f"{folder / PROJECT_MANIFEST} has no name")
   return name


def find_output(out: Path, name: str, build_target: BuildTarget) -> Path | None:
   """!The runnable file a build made: capsule_<name><suffix> in the build folder (or below it).
   @param out  the build folder
   @param name  the project's name
   @param build_target  the target
   @return its path, or None when it does not exist (yet)
   """
   suffixes = [build_target.output_suffix] + ([build_target.fallback_suffix] if build_target.fallback_suffix else [])
   for suffix in suffixes:
      file_name = TARGET_PREFIX + name + suffix
      direct = out / file_name
      if direct.is_file():
         return direct
      if out.is_dir():
         found = next((f for f in sorted(out.rglob(file_name)) if f.is_file()), None)
         if found is not None:
            return found
   return None


# ---- toolchains ------------------------------------------------------------------------------------------------

def _msys2_path() -> str | None:
   """!PATH with MSYS2's UCRT64 tools in front, when gcc is not on PATH but MSYS2 is installed (Windows).
   @return the new PATH, or None when nothing needs adding
   """
   if shutil.which("gcc") is not None:
      return None
   root = Path(os.environ.get(MSYS2_ENV) or MSYS2_DEFAULT)
   folders = [str(root / f) for f in MSYS2_BIN_FOLDERS if (root / f).is_dir()]
   if not folders:
      return None
   return os.pathsep.join(folders + [os.environ.get("PATH", "")])


def _devkitpro() -> Path:
   """!devkitPro's folder: DEVKITPRO, else the toolchain file's default, else its Windows installer's.
   @return the folder (it may not exist)
   """
   given = os.environ.get("DEVKITPRO")
   if given and Path(given).is_dir():
      return Path(given)
   default = Path(DEVKITPRO_DEFAULT)
   if sys.platform == "win32" and not default.is_dir() and Path(DEVKITPRO_WINDOWS).is_dir():
      return Path(DEVKITPRO_WINDOWS)
   return Path(given) if given else default


def _which(name: str, env: Mapping[str, str]) -> str | None:
   """!A program on the PATH a step will run with.
   @param name  program
   @param env  the step's environment additions
   @return its path, or None
   """
   return shutil.which(name, path=env.get("PATH") or os.environ.get("PATH"))


def build_env(build_target: BuildTarget) -> dict[str, str]:
   """!Environment variables a target's build steps need on top of the Studio's own.
   @param build_target  the target
   @return variables (empty when none)
   """
   env: dict[str, str] = {}
   if bench.JOBS_ENV not in os.environ:
      env[bench.JOBS_ENV] = str(os.cpu_count() or 1)
   if build_target.run_kind == RUN_NATIVE and sys.platform == "win32":
      path = _msys2_path()
      if path is not None:
         env["PATH"] = path
   return env


def build_problems(build_target: BuildTarget) -> list[str]:
   """!What this computer lacks to build a target.
   @param build_target  the target
   @return missing items, each a sentence (empty: it can build)
   """
   missing = [m for m in (bench.cmake_missing(),) if m is not None]
   env = build_env(build_target)
   if build_target.run_kind == RUN_NATIVE:
      if sys.platform == "win32":
         for program, what in (("ninja", "Ninja"), ("gcc", "MSYS2's UCRT64 gcc"), ("g++", "MSYS2's UCRT64 g++")):
            if _which(program, env) is None:
               missing.append(f"{what} ({program} on PATH or in {MSYS2_DEFAULT}/ucrt64/bin)")
      else:
         m = bench.compiler_missing()
         if m is not None:
            missing.append(m)
   elif build_target.run_kind == RUN_GBA:
      kit = _devkitpro()
      arm = Path(os.environ.get("DEVKITARM") or kit / "devkitARM")
      libgba = Path(os.environ.get("LIBGBA") or kit / "libgba")
      if not any((arm / "bin" / ("arm-none-eabi-g++" + s)).is_file() for s in ("", ".exe")):
         missing.append(f"devkitARM (looked in {arm}; set DEVKITPRO)")
      if not (libgba / "lib" / "libgba.a").is_file():
         missing.append(f"libgba (looked in {libgba}; set LIBGBA)")
      if not any((kit / "tools" / "bin" / ("gbafix" + s)).is_file() for s in ("", ".exe")):
         missing.append(f"gbafix (looked in {kit / 'tools' / 'bin'})")
   elif build_target.run_kind == RUN_DREAMCAST:
      environ = Path(os.environ.get("KOS_ENVIRON") or KOS_ENVIRON_DEFAULT)
      if not environ.is_file():
         missing.append(f"KallistiOS (no {environ}; set KOS_ENVIRON)")
   return missing


# ---- running the result ----------------------------------------------------------------------------------------

def _flatpak(app_id: str) -> list[str] | None:
   """!A Flatpak application's command, when it is installed.
   @param app_id  its id
   @return ["flatpak", "run", id], or None
   """
   if shutil.which("flatpak") is None:
      return None
   if any((folder / app_id).is_dir() for folder in FLATPAK_APP_FOLDERS):
      return ["flatpak", "run", app_id]
   return None


def _workspace() -> Path | None:
   """!The workspace: the folder holding the umbrella (whose engine/ is the engine in use).
   @return the folder, or None when the engine is not found
   """
   try:
      return engine.root().parent.parent
   except engine.EngineNotFound:
      return None


def _nocash() -> list[str] | None:
   """!No$GBA's command (in Wine off Windows), when it is found.
   @return the command, or None
   """
   places = [os.environ.get(NOCASH_ENV, "")]
   workspace = _workspace()
   if workspace is not None:
      places += [str(workspace / f / NOCASH_EXE) for f in NOCASH_FOLDERS]
   places += [str(Path.home() / ".wine" / "drive_c" / f / NOCASH_EXE) for f in NOCASH_FOLDERS]
   on_path = shutil.which(NOCASH_EXE)
   if on_path is not None:
      places.insert(1, on_path)
   exe = next((p for p in places if p and Path(p).is_file()), None)
   if exe is None:
      return None
   if sys.platform == "win32":
      return [exe]
   wine = shutil.which("wine")
   return [wine, exe] if wine is not None else None


def gba_emulator() -> list[str] | None:
   """!The GBA emulator's command: CAPSULE_GBA_EMULATOR, else mGBA (on PATH, Flatpak, installed, or built in the
   workspace's mgba clone), else No$GBA as the backup.
   @return the command (the ROM goes at the end), or None when none is found
   """
   given = os.environ.get(GBA_EMULATOR_ENV)
   if given:
      return shlex.split(given)
   for program in MGBA_PROGRAMS:
      found = shutil.which(program)
      if found is not None:
         return [found]
   flatpak = _flatpak(MGBA_FLATPAK)
   if flatpak is not None:
      return flatpak
   places = list(MGBA_KNOWN)
   workspace = _workspace()
   if workspace is not None:
      places += [str(workspace / MGBA_CLONE / b) for b in MGBA_CLONE_BUILDS]
   known = next((p for p in places if Path(p).is_file()), None)
   if known is not None:
      return [known]
   return _nocash()


def dreamcast_emulator() -> list[str] | None:
   """!The Dreamcast emulator's command: CAPSULE_DC_EMULATOR, else Flycast, Redream or lxdream.
   @return the command (the disc image goes at the end), or None when none is found
   """
   given = os.environ.get(DC_EMULATOR_ENV)
   if given:
      return shlex.split(given)
   for program in DC_PROGRAMS:
      found = shutil.which(program)
      if found is not None:
         return [found]
   return _flatpak(DC_FLATPAK)


def emulator(build_target: BuildTarget) -> list[str] | None:
   """!What starts a target's result, apart from the file itself.
   @param build_target  the target
   @return the command ([] for an executable, which starts itself), or None when nothing is found
   """
   if build_target.run_kind == RUN_GBA:
      return gba_emulator()
   if build_target.run_kind == RUN_DREAMCAST:
      return dreamcast_emulator()
   return []


def emulator_wanted(build_target: BuildTarget) -> str:
   """!What to install when emulator() finds nothing.
   @param build_target  the target
   @return a sentence
   """
   if build_target.run_kind == RUN_GBA:
      return (f"no GBA emulator found: install mGBA (or No$GBA), or set {GBA_EMULATOR_ENV} to the emulator's "
              "command")
   return f"no Dreamcast emulator found: install Flycast, or set {DC_EMULATOR_ENV} to the emulator's command"


def run_step(build_target: BuildTarget, out: Path, name: str, command: Sequence[str] | None = None) -> Step | None:
   """!The step that starts a build's result.
   @param build_target  the target
   @param out  the build folder
   @param name  the project's name
   @param command  the emulator's command, or None to look for one (emulator())
   @return the step, or None when there is nothing to start it with
   """
   cmd = list(command) if command is not None else emulator(build_target)
   if cmd is None:
      return None
   # The file is named by the path the build will make; find_output() may find it below the build folder instead.
   result = find_output(out, name, build_target) or out / (TARGET_PREFIX + name + build_target.output_suffix)
   title = "Starting the game" if not cmd else f"Starting {result.name} in {Path(cmd[-1]).name}"
   return Step(title, cmd + [str(result)], result.parent)


def plan(path: str | Path, target_id: str, debug: bool = False, run: bool = False,
         command: Sequence[str] | None = None) -> BuildPlan:
   """!The build of one target, as ./build PRESET --game FOLDER does it.
   @param path  the game's reference/project.json, or its folder
   @param target_id  one of targets()
   @param debug  True for the debug preset ("Build and Debug" always is)
   @param run  True to start the result afterwards
   @param command  the emulator's command to start it with, or None to look for one
   @return the plan
   @throws ValueError when the path is not a game, KeyError when this computer cannot build the target
   """
   build_target = target(target_id)
   folder = game_folder(path)
   name = project_name(folder)
   preset = build_target.preset(debug)
   out = folder / BUILD_FOLDER / preset
   problems = build_problems(build_target)
   env = build_env(build_target)
   steps: list[Step] = []
   try:
      engine_root = engine.root()
   except engine.EngineNotFound as e:
      return BuildPlan(build_target, preset, folder, name, out, steps, problems + [str(e)])
   configure = ["cmake", "--preset", preset, "-B", str(out), f"-DCAPSULE_GAMES={folder}",
                "-DCAPSULE_ENGINE_TESTS=OFF"]
   # A desktop build reuses the SDL2 source the engine's own build of the preset downloaded (as ./build does).
   sdl2 = engine_root / BUILD_FOLDER / preset / "_deps" / "sdl2-src"
   if (sdl2 / "CMakeLists.txt").is_file():
      configure.append(f"-DFETCHCONTENT_SOURCE_DIR_SDL2={sdl2}")
   if build_target.run_kind == RUN_GBA and _devkitpro() != Path(DEVKITPRO_DEFAULT) and "DEVKITPRO" not in os.environ:
      configure.append(f"-DDEVKITPRO={_devkitpro().as_posix()}")
   steps.append(Step(f"Configuring {name} ({preset})", configure, engine_root, env))
   steps.append(Step(f"Building {name} ({preset})", ["cmake", "--build", str(out)], engine_root, env))
   result = BuildPlan(build_target, preset, folder, name, out, steps, [p + "; " + SETUP_HINT for p in problems])
   if run:
      result.run = run_step(build_target, out, name, command)
      if result.run is None:
         result.run_problem = emulator_wanted(build_target)
   return result


def plans(path: str | Path, target_ids: Sequence[str] | None, debug: bool = False, run: bool = False,
          command: Sequence[str] | None = None) -> list[BuildPlan]:
   """!Builds of several targets (None: every target this computer builds).
   @param path  the game's reference/project.json, or its folder
   @param target_ids  ids, or None for all of targets()
   @param debug  True for debug presets
   @param run  True to start each result afterwards
   @param command  the emulator's command, or None to look for one
   @return plans, in the order given
   """
   ids = list(target_ids) if target_ids is not None else [t.target_id for t in targets()]
   return [plan(path, i, debug, run, command) for i in ids]


# ---- running a plan without Qt (the command line) --------------------------------------------------------------

def run_steps(steps: Sequence[Step], echo: Callable[[str], None]) -> int:
   """!Runs steps one after another, their output line by line, stopping at the first that fails.
   @param steps  the steps
   @param echo  takes each line of the log
   @return 0, or the exit status of the step that failed
   """
   for step in steps:
      echo(f"== {step.title}")
      echo(f"$ {step.shown()}")
      env = dict(os.environ)
      env.update(step.env)
      try:
         proc = subprocess.Popen([step.program()] + step.argv[1:], cwd=step.cwd, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, errors="replace")
      except OSError as e:
         echo(f"error: cannot start {step.argv[0]}: {e}")
         return 1
      with proc:
         assert proc.stdout is not None
         for line in proc.stdout:
            echo(line.rstrip("\n"))
      status = proc.returncode
      if status != 0:
         echo(f"error: {step.title.lower()} failed (exit status {status})")
         return status
   return 0


def run_plan(build: BuildPlan, echo: Callable[[str], None]) -> int:
   """!Runs a plan: its build steps, then its run step when it has one.
   @param build  the plan
   @param echo  takes each line of the log
   @return 0, or a failing step's exit status (1 when something is missing)
   """
   if build.problems:
      for p in build.problems:
         echo(f"error: {build.target.title}: missing {p}")
      return 1
   status = run_steps(build.steps, echo)
   if status != 0:
      return status
   output = build.output()
   echo(f"built {build.name} for {build.target.title}: {output if output is not None else build.out}")
   if build.run_problem:
      echo(f"error: {build.run_problem}")
      return 1
   if build.run is not None:
      if output is None:
         echo(f"error: the build made no {TARGET_PREFIX}{build.name}{build.target.output_suffix} to start")
         return 1
      run = run_step(build.target, build.out, build.name, build.run.argv[:-1])
      return run_steps([run] if run is not None else [], echo)
   return 0
