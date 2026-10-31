"""!`capsule-studio locations ...`: everything the Locations panel does, from
the command line (D-10 parity): the world's default warp transition, banner
styles, locations with their banners and previews, and each map's location.
Changes are compiled with the engine before anything is saved.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from capsule_studio.core import locations
from capsule_studio.core.document import DocumentError
from capsule_studio.core.world import Project

if TYPE_CHECKING:
   import argparse

   from capsule_studio.plugins.registry import ExtensionContext

## A command's body: callable(parsed arguments) -> exit status, or None for 0.
CommandRun = Callable[["argparse.Namespace"], int | None]
## A command's argument setup: callable(parser), its result unused.
CommandSetup = Callable[["argparse.ArgumentParser"], object]
## A banner style field's value from the command line (None removes it).
StyleValue = int | str | None

## Banner style options: (option, field, type).
STYLE_OPTIONS = [("--frame", "frame", str), ("--ink", "ink", str), ("--shadow", "shadow", str),
                 ("--fill", "fill", str), ("--border", "border", str), ("--frames", "frames", int),
                 ("--slide", "slide", int)]


class Usage(Exception):
   """!Bad arguments; the message says what to give."""
   pass


def _wrap(fn: CommandRun) -> Callable[[argparse.Namespace], int]:
   """!Turns Usage and DocumentError into messages and exit status 1.
   @param fn  callable(args)
   @return callable(args) -> status
   """
   def run(args: argparse.Namespace) -> int:
      try:
         return fn(args) or 0
      except (Usage, DocumentError) as e:
         print(f"capsule-studio locations: error: {e}")
         return 1
   return run


def _save(p: Project) -> None:
   """!Compiles, then saves every changed document.
   @param p  Project
   @return None
   """
   error = p.validate()
   if error:
      raise DocumentError(error)
   p.save_all()


def _style_fields(args: argparse.Namespace) -> dict[str, StyleValue]:
   """!Style fields given on the command line ("-" removes one).
   @param args  parsed arguments
   @return {field: value or None}
   """
   out: dict[str, StyleValue] = {}
   for opt, field, typ in STYLE_OPTIONS:
      raw = getattr(args, field, None)
      if raw is None:
         continue
      if raw == "-":
         out[field] = None
         continue
      try:
         out[field] = typ(raw)
      except ValueError:
         raise Usage(f"{opt} needs a number, got {raw!r}") from None
   return out


def _when(raw: str | None) -> list[str] | None | Literal[False]:
   """!A --when value.
   @param raw  "c1,c2", "-" or None
   @return list, None (none) or False (not given)
   """
   if raw is None:
      return False
   if raw == "-":
      return None
   return [c.strip() for c in raw.split(",") if c.strip()]


def cmd_show(args: argparse.Namespace) -> None:
   """!locations show. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   print(f"transition: {locations.transition(p)}")
   for name, st in locations.styles(p).items():
      print(f"banner style {name}: {locations.describe_style(st)}")
   for key, loc in locations.locations(p).items():
      maps = locations.maps_of(p, key)
      print(f"location {key}: {locations.describe(loc)}; maps: {', '.join(maps) or 'none'}")
      for j, e in enumerate(locations.sequences(p, key)):
         print(f"  preview {j}: {locations.describe_entry(e)}")
   outside = [n for n in p.map_names() if locations.map_location(p.map(n)) is None]
   if outside:
      print(f"maps in no location: {', '.join(outside)}")


def cmd_check(args: argparse.Namespace) -> int:
   """!locations check. @param args  parsed arguments
   @return status"""
   p = Project.open(args.world)
   found = locations.diagnostics(p)
   for d in found:
      print(f"{d.level}: {d.message}")
   if any(d.level == "error" for d in found):
      return 1
   print("locations compile")
   return 0


def cmd_transition(args: argparse.Namespace) -> None:
   """!locations transition. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   if args.name is not None:
      with p.world.edit("Set transition"):
         locations.set_transition(p, None if args.name == "-" else args.name)
      _save(p)
   print(f"transition: {locations.transition(p)}")


def cmd_style_add(args: argparse.Namespace) -> None:
   """!locations style-add. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   with p.world.edit("Add banner style"):
      locations.add_style(p, args.name, **{k: v for k, v in _style_fields(args).items() if v is not None})
   _save(p)
   print(f"banner style {args.name}: {locations.describe_style(locations.styles(p)[args.name])}")


def cmd_style_set(args: argparse.Namespace) -> None:
   """!locations style-set. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   with p.world.edit("Change banner style"):
      locations.set_style(p, args.name, **_style_fields(args))
      if args.rename:
         locations.rename_style(p, args.name, args.rename)
   _save(p)
   name = args.rename or args.name
   print(f"banner style {name}: {locations.describe_style(locations.styles(p)[name])}")


def cmd_style_remove(args: argparse.Namespace) -> None:
   """!locations style-remove. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   with p.world.edit("Remove banner style"):
      locations.remove_style(p, args.name)
   _save(p)
   print(f"removed banner style {args.name}")


def cmd_add(args: argparse.Namespace) -> None:
   """!locations add. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   with p.world.edit("Add location"):
      locations.add_location(p, args.key, args.name, args.banner)
   _save(p)
   print(f"location {args.key}: {locations.describe(locations.location(p, args.key))}")


def cmd_set(args: argparse.Namespace) -> None:
   """!locations set. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   # False keeps the banner, None removes it
   banner = False if args.banner is None else (None if args.banner == "-" else args.banner)
   with p.world.edit("Change location"):
      locations.set_location(p, args.key, args.name, banner)
   _save(p)
   print(f"location {args.key}: {locations.describe(locations.location(p, args.key))}")


def cmd_rename(args: argparse.Namespace) -> None:
   """!locations rename. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   maps = locations.maps_of(p, args.key)
   locations.rename_location(p, args.key, args.new)
   _save(p)
   print(f"location {args.key} is now {args.new}" + (f" (maps {', '.join(maps)} follow)" if maps else ""))


def cmd_remove(args: argparse.Namespace) -> None:
   """!locations remove. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   maps = locations.remove_location(p, args.key)
   _save(p)
   print(f"removed location {args.key}" + (f"; maps {', '.join(maps)} are in none now" if maps else ""))


def cmd_preview(args: argparse.Namespace) -> None:
   """!locations preview. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   if args.show is not None:
      with p.world.edit("Change preview"):
         locations.set_preview(p, args.key, None if args.show == "-" else args.show)
      _save(p)
   loc = locations.location(p, args.key)
   print(f"location {args.key}: {locations.describe(loc)}")


def cmd_preview_add(args: argparse.Namespace) -> None:
   """!locations preview-add. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   when = _when(args.when)
   with p.world.edit("Add preview sequence"):
      j = locations.add_sequence(p, args.key, args.sequence, when or None)
      if args.show:
         locations.set_preview(p, args.key, args.show)
   _save(p)
   print(f"location {args.key} preview {j}: {locations.describe_entry(locations.sequences(p, args.key)[j])}")


def cmd_preview_set(args: argparse.Namespace) -> None:
   """!locations preview-set. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   with p.world.edit("Change preview sequence"):
      locations.set_sequence(p, args.key, args.index, args.sequence, _when(args.when))
   _save(p)
   print(f"location {args.key} preview {args.index}: "
         f"{locations.describe_entry(locations.sequences(p, args.key)[args.index])}")


def cmd_preview_remove(args: argparse.Namespace) -> None:
   """!locations preview-remove. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   with p.world.edit("Remove preview sequence"):
      locations.remove_sequence(p, args.key, args.index)
   _save(p)
   print(f"location {args.key}: removed preview {args.index}")


def cmd_map(args: argparse.Namespace) -> None:
   """!locations map. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   if args.map not in p.map_names():
      raise Usage(f"no map {args.map!r} (maps: {', '.join(p.map_names())})")
   doc = p.map(args.map)
   if args.key is not None:
      with doc.edit("Set location"):
         locations.set_map_location(p, doc, None if args.key == "-" else args.key)
      _save(p)
   print(f"{args.map}: location {locations.map_location(doc) or '(none)'}")


def register(ctx: ExtensionContext) -> None:
   """!Adds the commands.
   @param ctx  ExtensionContext
   @return None
   """
   def add(name: str, help: str, setup: CommandSetup, fn: CommandRun) -> None:
      def full(q: argparse.ArgumentParser) -> None:
         q.add_argument("world", help="world.json")
         setup(q)
      ctx.add_command(name, help, full, _wrap(fn))

   def style_options(q: argparse.ArgumentParser) -> None:
      for opt, field, _typ in STYLE_OPTIONS:
         extra = {"frame": "; a 24x24 PNG, relative to the world file", "frames": "; how long it stays",
                  "slide": "; frames to slide in"}.get(field, "; #rrggbb")
         q.add_argument(opt, dest=field, help=f"{field} ('-' removes it{extra})")

   add("show", "list the world's transition, banner styles and locations with their maps and previews",
       lambda q: None, cmd_show)
   add("check", "report location problems; status 1 on errors", lambda q: None, cmd_check)
   add("transition", "show or set the world's default warp transition ('-': fade)",
       lambda q: q.add_argument("name", nargs="?", help=", ".join(locations.TRANSITIONS)), cmd_transition)
   add("style-add", "add a banner style",
       lambda q: (q.add_argument("name"), style_options(q)), cmd_style_add)
   add("style-set", "change a banner style",
       lambda q: (q.add_argument("name"), q.add_argument("--rename", help="new name (locations follow)"),
                  style_options(q)), cmd_style_set)
   add("style-remove", "remove a banner style no location uses", lambda q: q.add_argument("name"),
       cmd_style_remove)
   add("add", "add a location",
       lambda q: (q.add_argument("key"), q.add_argument("--name", required=True, help="the banner's text"),
                  q.add_argument("--banner", help="banner style")), cmd_add)
   add("set", "change a location's banner text or style",
       lambda q: (q.add_argument("key"), q.add_argument("--name", help="the banner's text"),
                  q.add_argument("--banner", help="banner style ('-': no banner)")), cmd_set)
   add("rename", "rename a location (its maps follow)",
       lambda q: (q.add_argument("key"), q.add_argument("new")), cmd_rename)
   add("remove", "remove a location (its maps are in none)", lambda q: q.add_argument("key"), cmd_remove)
   add("preview", "show or set when a location's preview shows ('-' removes the preview)",
       lambda q: (q.add_argument("key"), q.add_argument("show", nargs="?", help="always, first or -")),
       cmd_preview)
   add("preview-add", "add a preview sequence (the last whose conditions hold plays)",
       lambda q: (q.add_argument("key"), q.add_argument("sequence", help="capsule.sequence/1 file"),
                  q.add_argument("--when", help="encounter conditions, c1,c2"),
                  q.add_argument("--show", choices=list(locations.SHOWS))), cmd_preview_add)
   add("preview-set", "change a preview sequence",
       lambda q: (q.add_argument("key"), q.add_argument("index", type=int), q.add_argument("--sequence"),
                  q.add_argument("--when", help="encounter conditions, c1,c2 ('-': none)")), cmd_preview_set)
   add("preview-remove", "remove a preview sequence",
       lambda q: (q.add_argument("key"), q.add_argument("index", type=int)), cmd_preview_remove)
   add("map", "show or set a map's location ('-': none)",
       lambda q: (q.add_argument("map"), q.add_argument("key", nargs="?")), cmd_map)
