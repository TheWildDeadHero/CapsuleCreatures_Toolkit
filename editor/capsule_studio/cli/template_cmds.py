"""!`capsule-studio new ...` and `capsule-studio template ...`: battle data
templates (D-23 section 3.5, core.templates).

    new GAME --template NAME [--name N]     a new game folder: the template's files in GAME/data/, a world
                                            (GAME/data/world.json: one simple-shape tileset, the map start) and
                                            GAME/reference/project.json naming its world, battle and asset
                                            manifests
    template list                           every template found (built in, engine samples, reference repo,
                                            plugins): id, name, where, version, parts
    template show NAME                      one template's description and files by part
    template apply NAME FOLDER [--part P]   copy the template's files (or some parts) into FOLDER with their
                                            relative paths; the JSON manifests record editor.template
    template recorded FILE                  the template a manifest was copied from

`battle FILE new --template NAME` (battle_cmds) applies a template into
FILE's folder. Plugin templates count when --project names a game whose
plugins register some.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ..core import manifest_io, starter_world, templates
from .main import CommandError


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command groups.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("new", help="a new game folder from a battle data template (data/ with a starter world "
                           "+ reference/project.json)")
   p.add_argument("game", help="the new game's folder (new, or empty)")
   p.add_argument("--template", required=True, metavar="NAME", help="template id or name (template list), e.g. "
                                                                   "starter or blank")
   p.add_argument("--name", help="the game's name (default: the folder's name)")
   p.set_defaults(run=cmd_new_game)

   p = sub.add_parser("template", help="battle data templates: list | show | apply | recorded")
   s = p.add_subparsers(dest="template_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("list", help="every template found, in discovery order")
   q.set_defaults(run=cmd_list)
   q = s.add_parser("show", help="one template's description and files")
   q.add_argument("name")
   q.set_defaults(run=cmd_show)
   q = s.add_parser("apply", help="copy a template's files into a folder (nothing is overwritten)")
   q.add_argument("name")
   q.add_argument("folder")
   q.add_argument("--part", action="append", choices=list(templates.PARTS),
                  help="copy only this part (repeat for several; default: every part)")
   q.set_defaults(run=cmd_apply)
   q = s.add_parser("recorded", help="the template (id, version) a manifest was copied from")
   q.add_argument("file")
   q.set_defaults(run=cmd_recorded)


def registry_of(args: argparse.Namespace) -> object:
   """!The plugin registry main() loaded (plugin templates), or None.
   @param args  parsed arguments
   @return plugins.Registry or None
   """
   return getattr(args, "registry", None)


def cmd_new_game(args: argparse.Namespace) -> int:
   """!Makes a new game folder from a template.
   @param args  parsed arguments
   @return 0
   """
   t = templates.find(args.template, registry_of(args))
   project = templates.new_game(Path(args.game), t, args.name)
   world = manifest_io.load(project).get("maps")
   print(f"created {project} from {t.label()}, with a world ({world}: map {starter_world.START_MAP})")
   return 0


def cmd_list(args: argparse.Namespace) -> int:
   """!Lists the templates.
   @param args  parsed arguments
   @return 0
   """
   found, problems = templates.discover(registry_of(args))
   for t in found:
      parts = ", ".join(f"{part} {len(files)}" for part, files in t.parts.items())
      print(f"{t.id}: {t.label()}; files: {parts}")
   for problem in problems:
      print(f"problem: {problem}")
   return 0


def cmd_show(args: argparse.Namespace) -> int:
   """!Shows one template.
   @param args  parsed arguments
   @return 0
   """
   t = templates.find(args.name, registry_of(args))
   print(f"{t.id}: {t.label()}")
   print(f"  folder: {t.folder}")
   if t.description:
      print(f"  {t.description}")
   for part, files in t.parts.items():
      print(f"  {part}: {', '.join(files)}")
   return 0


def cmd_apply(args: argparse.Namespace) -> int:
   """!Copies a template into a folder.
   @param args  parsed arguments
   @return 0
   """
   t = templates.find(args.name, registry_of(args))
   written = templates.apply(t, Path(args.folder), args.part)
   print(f"copied {len(written)} file(s) of {t.label()} into {args.folder}")
   for path in written:
      print(f"  {path}")
   return 0


def cmd_recorded(args: argparse.Namespace) -> int:
   """!Prints the template a manifest records.
   @param args  parsed arguments
   @return 0, or 1 when it records none
   """
   rec = templates.recorded(Path(args.file))
   if rec is None:
      raise CommandError(f"{args.file} records no template")
   print(f"{rec.get('id')} version {rec.get('version')}")
   return 0
