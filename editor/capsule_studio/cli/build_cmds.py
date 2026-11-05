"""!`capsule-studio build ...`: builds a game and starts it, as the Studio's Build and Build and Debug buttons do
(core.game_build; the same build as ./build PRESET --game FOLDER).

    build GAME                           build GAME (its reference/project.json or its folder) for this computer
    build GAME --target ID               ... for one target (desktop, gba, dreamcast; --list says which build here)
    build GAME --target all              ... for every target this computer builds
    build GAME --debug                   with the debug preset (release otherwise)
    build GAME --run                     Build and Debug: the debug preset, then start the result (the executable,
                                         the ROM in mGBA or No$GBA, the disc image in Flycast); --emulator CMD
                                         names the emulator's command instead of looking for one
    build GAME --list                    the targets this computer builds, their presets and what is missing
    build GAME --dry-run                 print the commands without running them
"""
from __future__ import annotations

import argparse
import shlex

from ..core import game_build
from .main import CommandError

## --target's value for every target this computer builds.
ALL_TARGETS = "all"
## Exit status of --dry-run when something the build (or the run) needs is missing.
MISSING_STATUS = 1


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("build", help="build a game (and start it with --run), as the Studio's Build buttons")
   p.add_argument("game", help="the game's reference/project.json, or its folder")
   p.add_argument("--target", default=None, metavar="ID",
                  help="what to build: " + ", ".join(t.target_id for t in game_build.targets())
                  + f" or {ALL_TARGETS} (default: this computer, {game_build.host_target().target_id})")
   p.add_argument("--debug", action="store_true", help="use the debug preset (release otherwise)")
   p.add_argument("--run", dest="start", action="store_true",
                  help="Build and Debug: the debug preset, then start the result")
   p.add_argument("--emulator", default=None, metavar="CMD", help="the emulator's command for --run")
   p.add_argument("--list", action="store_true", help="list the targets this computer builds and stop")
   p.add_argument("--dry-run", action="store_true", help="print the commands without running them")
   p.set_defaults(run=cmd_build)


def cmd_build(args: argparse.Namespace) -> int:
   """!Builds (and starts) the game.
   @param args  parsed arguments
   @return 0, a failing step's exit status, or MISSING_STATUS (--dry-run with something missing)
   """
   if args.list:
      for t in game_build.targets():
         missing = game_build.build_problems(t)
         state = "ready" if not missing else "missing " + "; ".join(missing)
         print(f"{t.target_id}: {t.title} ({t.debug_preset} / {t.release_preset}) - {state}")
      return 0
   if args.start and args.target == ALL_TARGETS:
      raise CommandError("--run starts one game: pick one --target")
   ids = None if args.target == ALL_TARGETS else [args.target or game_build.host_target().target_id]
   command = shlex.split(args.emulator) if args.emulator else None
   try:
      builds = game_build.plans(args.game, ids, debug=args.debug or args.start, run=args.start, command=command)
   except KeyError as e:
      raise CommandError(e.args[0]) from None
   status = 0
   for build in builds:
      if args.dry_run:
         for p in build.problems:
            print(f"missing: {p}")
         for step in build.steps + ([build.run] if build.run is not None else []):
            print(f"(cd {shlex.quote(str(step.cwd))} && {step.shown()})")
         if build.run_problem:
            print(f"missing: {build.run_problem}")
         if build.problems or build.run_problem:
            status = MISSING_STATUS
         continue
      status = game_build.run_plan(build, print) or status
   return status
