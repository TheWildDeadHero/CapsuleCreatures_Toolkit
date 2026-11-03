"""!`capsule-studio usage ...`: a game's usage report (D-36; the engine's docs/USAGE.md), read with the engine's own
tools/usage.py (core.engine.tool()).

    usage GAME [--build DIR] [--link FILE] [--json]

GAME is a report file (usage/GAME.json in a build folder) or a game's name, looked up as
DIR/usage/GAME.json (DIR: --build, default the current folder). Prints which engine modules the game's data uses
and what each compiler recorded; --link compares the report with the GBA build's linker map or symbol listing
(capsule_GAME.map / capsule_GAME.nm) and lists the modules linked while nothing in the report uses them; --json
prints the report (or the comparison) as JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core import engine
from .main import CommandError

## The folder of the reports in a build folder.
USAGE_FOLDER = "usage"
## A report's suffix.
REPORT_SUFFIX = ".json"
## The indent of --json.
JSON_INDENT = 1


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("usage", help="a game's usage report: the engine modules and items its data uses")
   p.add_argument("game", help="a report file, or a game's name (DIR/usage/GAME.json)")
   p.add_argument("--build", metavar="DIR", default=".", help="the build folder (default: the current folder)")
   p.add_argument("--link", metavar="FILE", help="compare with a linker map or nm listing (capsule_GAME.map / .nm)")
   p.add_argument("--json", action="store_true", help="print JSON")
   p.set_defaults(run=cmd_usage)


def report_path(game: str, build: str) -> Path:
   """!The report a GAME argument names.
   @param game   a report file or a game's name
   @param build  the build folder
   @return the report's path
   @throws CommandError when it does not exist
   """
   given = Path(game)
   path = given if given.suffix == REPORT_SUFFIX or given.is_file() else Path(build) / USAGE_FOLDER / (
      game + REPORT_SUFFIX)
   if not path.is_file():
      raise CommandError(f"no usage report at {path} (build the game first: its target capsule_<game>_usage)")
   return path


def cmd_usage(args: argparse.Namespace) -> int:
   """!Prints a report, or its comparison with a link.
   @param args  parsed arguments
   @return 0
   @throws CommandError when the report or the link file does not read
   """
   try:
      tool = engine.tool("usage")
   except engine.EngineNotFound as e:
      raise CommandError(str(e)) from None
   except ImportError:
      raise CommandError(f"the engine at {engine.root()} has no usage reports (tools/usage.py): update it") from None
   path = report_path(args.game, args.build)
   try:
      report = tool.read_report(path)
      shown = report
      if args.link:
         shown = tool.compare(report, tool.read_linked(Path(args.link).read_text(encoding="utf-8", errors="replace")))
   except (tool.UsageError, OSError) as e:
      raise CommandError(str(e)) from None
   if args.json:
      sys.stdout.write(json.dumps(shown, indent=JSON_INDENT) + "\n")
   else:
      sys.stdout.write(tool.linkmap_text(shown) if args.link else tool.summary(shown))
   return 0
