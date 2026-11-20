"""!`capsule-studio exclude ...`: a game's build usage and its exclusion manifest (D-36 package 3 step 3C;
core.exclusion; the engine's docs/USAGE.md "Exclusion manifest").

    exclude PROJECT [--build DIR] [--write]

PROJECT is the game's reference/project.json. DIR is the build folder that built it (default: the first configured
build folder by the game, GBA ones first, as the project settings window finds them). Prints which excludable engine
modules the game uses, excludes or could exclude (with the bytes each links on the GBA when the folder has the
program's symbol listing), the script ops, and the last build's check. --write saves the build's suggestion as the
game's manifest: the file the project names, or reference/exclude.json, which the project then names.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..core import exclusion, gba_memory, project
from ..core.document import DocumentError
from .main import CommandError


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("exclude", help="a game's build usage and its exclusion manifest")
   p.add_argument("manifest", metavar="PROJECT", help="the game's reference/project.json")
   p.add_argument("--build", metavar="DIR", help="the build folder (default: the first one found by the game)")
   p.add_argument("--write", action="store_true", help="save the build's suggestion as the game's manifest")
   p.set_defaults(run=cmd_exclude)


def build_folder(doc: project.Document, given: str | None) -> Path:
   """!The build folder to read.
   @param doc    the project Document
   @param given  --build, or None
   @return the folder
   @throws CommandError when none is found
   """
   if given:
      return Path(given)
   found = gba_memory.build_folders(project.game_folder(doc))
   if not found:
      raise CommandError(f"no configured build folder by {project.game_folder(doc)}: pass --build")
   return found[0]


def cmd_exclude(args: argparse.Namespace) -> int:
   """!Prints the build usage; with --write saves the suggestion.
   @param args  parsed arguments
   @return 0
   @throws CommandError when the project, the build folder or the manifest does not read
   """
   try:
      doc = project.open_project(args.manifest)
      usage = exclusion.read_build(build_folder(doc, args.build), exclusion.game_name(doc))
      manifest = exclusion.read_manifest(doc)
      if args.write:
         if usage.suggestion is None:
            raise CommandError("the build wrote no suggestion (usage/GAME.exclude.json): build the game with an "
                               "engine that has the exclusion manifest")
         manifest = exclusion.build_manifest(usage, exclusion.names(usage.suggestion, exclusion.MODULES),
                                             exclusion.names(usage.suggestion, exclusion.SCRIPT_OPS), manifest)
         path, added = exclusion.save(doc, manifest)
         if added:
            doc.save()
         print(f"wrote {path}" + (f" (the project now names it: {exclusion.DEFAULT_MANIFEST})" if added else ""))
      sys.stdout.write(exclusion.summary(usage, manifest))
   except (exclusion.ExclusionError, DocumentError, OSError) as e:
      raise CommandError(str(e)) from None
   return 0
