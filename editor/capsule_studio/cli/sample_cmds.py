"""!`capsule-studio sample ...`: the engine's sample projects (D-40 RP, core.samples).

    sample list                          every sample of the engine in use: id, name and one line on it
    sample copy NAME DEST [--name N]     copy a sample into DEST (new or empty) as a game of its own: its files,
                                         the engine data it shares (data/starter), paths pointed at the copies, a
                                         build-safe name and ROM header; build it with ./build PRESET --game DEST
    sample check GAME                    what ties a game folder to files outside it (paths that lead out,
                                         libraries the engine does not link for any game); exit 1 when any
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ..core import samples
from .main import CommandError

## Exit status of `sample check` when the game leads out of its folder.
PROBLEMS_STATUS = 1


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("sample", help="the engine's sample projects: list | copy | check")
   s = p.add_subparsers(dest="sample_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("list", help="every sample project, with one line on what it shows")
   q.set_defaults(run=cmd_list)
   q = s.add_parser("copy", help="copy a sample into a new folder as a game of your own")
   q.add_argument("name", help="sample id or name (sample list), e.g. starter_battle or sandbox_map")
   q.add_argument("dest", help="the new game's folder (new, or empty; not inside the engine or the Studio)")
   q.add_argument("--name", dest="game_name", metavar="N", help="the game's name (default: the folder's name)")
   q.set_defaults(run=cmd_copy)
   q = s.add_parser("check", help="whether a game folder stands alone (exit 1 when a path leads out of it)")
   q.add_argument("game", help="a game folder (with reference/project.json)")
   q.set_defaults(run=cmd_check)


def cmd_list(args: argparse.Namespace) -> int:
   """!Lists the samples.
   @param args  parsed arguments
   @return 0
   """
   found, problems = samples.discover()
   for s in found:
      print(f"{s.id}: {s.name} - {s.description}")
   for problem in problems:
      print(f"problem: {problem}")
   return 0


def cmd_copy(args: argparse.Namespace) -> int:
   """!Copies a sample into a new game folder.
   @param args  parsed arguments
   @return 0
   """
   sample = samples.find(args.name)
   project = samples.copy(sample, Path(args.dest), args.game_name)
   game = project.parent.parent
   print(f"copied {sample.label()} into {game}")
   print(f"  open {project} in the Studio; build it with ./build gba-release --game {game}")
   return 0


def cmd_check(args: argparse.Namespace) -> int:
   """!Checks that a game folder stands alone.
   @param args  parsed arguments
   @return 0, or PROBLEMS_STATUS when something leads out of it
   """
   game = Path(args.game)
   if not (game / samples.REFERENCE_DIR / samples.PROJECT_FILE).is_file():
      raise CommandError(f"{game} has no {samples.REFERENCE_DIR}/{samples.PROJECT_FILE}")
   problems = samples.outside_paths(game)
   for problem in problems:
      print(f"problem: {problem}")
   if problems:
      return PROBLEMS_STATUS
   print(f"ok: {game} stands alone (no path leads out of it)")
   return 0
