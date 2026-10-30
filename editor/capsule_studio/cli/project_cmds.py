"""!`capsule-studio project ...`: a game's project manifest, its build
settings (A-2, A-5), the same operations as the project settings window, the
data files it names (what the Studio opens for the game), and adding a world
to it (core.game_world, as the Studio's Add world to game...)."""
from __future__ import annotations

import argparse

from ..core import game_world, project
from ..core.document import DocumentError
from .main import CommandError


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("project", help="a game's reference/project.json: build settings and data files")
   s = p.add_subparsers(dest="project_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("build", help="show or change the build settings")
   q.add_argument("manifest", help="reference/project.json")
   q.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="set a setting")
   q.add_argument("--default", action="append", default=[], metavar="KEY", help="use the engine's default")
   q.add_argument("--waitcnt", action="append", default=[], metavar="FIELD=CHOICE",
                  help="change one WAITCNT field, e.g. ws0_first=4 or prefetch=off")
   q.set_defaults(run=cmd_build)
   q = s.add_parser("files", help="list the data files the project names (what the Studio opens)")
   q.add_argument("manifest", help="reference/project.json")
   q.set_defaults(run=cmd_files)
   q = s.add_parser("add-world", help="name a world in the project (a world outside the game is imported first)")
   q.add_argument("manifest", help="reference/project.json")
   q.add_argument("world", nargs="?", help="the world's world.json (default with --sandbox: the engine's map sandbox)")
   q.add_argument("--sandbox", action="store_true", help="the engine's map sandbox world")
   q.add_argument("--import", dest="do_import", action="store_true",
                  help="import a world from outside the game into the game's own world first (without it, only "
                       "a world inside the game folder is accepted)")
   q.add_argument("--map", action="append", default=None, metavar="NAME",
                  help="a map to import (repeat it; default: every map of the world)")
   q.add_argument("--dry-run", action="store_true", help="say what would happen, change nothing")
   q.set_defaults(run=cmd_add_world)


def cmd_add_world(args: argparse.Namespace) -> int:
   """!project add-world: names a world in the project manifest, importing it first when it is outside the game.
   @param args  parsed arguments
   @return exit status
   """
   source = args.world
   if args.sandbox:
      if source is not None:
         raise CommandError("give a world file or --sandbox, not both")
      source = game_world.sandbox_world()
      if source is None:
         raise CommandError("the engine's map sandbox world was not found (see --engine)")
   if source is None:
      raise CommandError("give the world's world.json, or --sandbox")
   try:
      doc = project.open_project(args.manifest)
      add = game_world.plan(doc, source)
      if add.action == game_world.IMPORT and not args.do_import and not args.dry_run:
         raise CommandError(f"{add.source} is not in the game folder; --import copies its maps into "
                            f"{add.rel} first")
      if args.dry_run:
         print(_describe(add))
         return 0
      lines = game_world.run(doc, source, args.map)
   except DocumentError as e:
      raise CommandError(str(e)) from e
   for line in lines:
      print(line)
   return 0


def _describe(add: game_world.AddWorldPlan) -> str:
   """!What a plan would do, in one line.
   @param add  game_world.AddWorldPlan
   @return str
   """
   if add.action == game_world.LINKED:
      return f"the game names this world already ({add.rel})"
   was = f" (instead of {add.replaces})" if add.replaces else ""
   if add.action == game_world.LINK:
      return f"would name {add.rel}{was}"
   into = "a new world" if add.creates else "the world"
   return f"would import {add.source} into {into} {add.rel}, then name it{was}"


def cmd_files(args: argparse.Namespace) -> int:
   """!project files: each data file the project names, relative to the game folder.
   @param args  parsed arguments
   @return exit status (1 when a named file is missing)
   """
   try:
      doc = project.open_project(args.manifest)
      files = project.game_files(doc)
      base = project.game_folder(doc)
   except DocumentError as e:
      raise CommandError(str(e)) from e
   status = 0
   for key, what in project.GAME_FILES:
      if key not in files:
         print(f"{key}: (none)  {what}")
         continue
      path = files[key]
      try:
         shown = path.relative_to(base)
      except ValueError:
         shown = path
      missing = not path.is_file()
      status = 1 if missing else status
      print(f"{key}: {shown}{'  (missing)' if missing else ''}  {what}")
   return status


def _choice(text: str) -> int | str:
   """!A WAITCNT choice from the command line.
   @param text  e.g. '3' or 'on'
   @return int or str
   """
   return int(text) if text.isdigit() else text


def cmd_build(args: argparse.Namespace) -> int:
   """!project build.
   @param args  parsed arguments
   @return exit status
   """
   try:
      doc = project.open_project(args.manifest)
      for item in args.set:
         key, sep, value = item.partition("=")
         if not sep:
            raise CommandError(f"--set needs KEY=VALUE, got {item!r}")
         project.set_setting(doc, key, value)
      for key in args.default:
         project.clear_setting(doc, key)
      fields: dict[str, int | str] = {}
      for item in args.waitcnt:
         name, sep, value = item.partition("=")
         if not sep:
            raise CommandError(f"--waitcnt needs FIELD=CHOICE, got {item!r}")
         fields[name] = _choice(value)
      if fields:
         project.set_waitcnt_fields(doc, fields)
      if doc.dirty:
         doc.save()
      shown = project.rows(doc)
   except DocumentError as e:
      raise CommandError(str(e)) from e
   for r in shown:
      print(f"{r.key} = {r.shown}" + ("" if r.given else "  (engine default)"))
   status = 0
   for sev, msg in project.problems(doc):
      print(f"{sev}: {msg}")
      status = 1 if sev == "error" else status
   return status
