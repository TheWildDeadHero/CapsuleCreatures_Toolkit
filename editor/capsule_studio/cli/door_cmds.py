"""![S3] `capsule-studio door MANIFEST ...` (door animation assets, D-30 section 1), `door-binding WORLD ...` (the
world's door bindings by metatile; a warp's own binding is `events set MAP warp N --door door:KEY`) and
`draw-order WORLD ...` (the world's object draw order rule, D-30 section 4). Changes are compiled with the engine
before anything is saved."""
from __future__ import annotations

import argparse
from typing import Any

from ..core import doors, draw_order
from ..core.world import Project
from .common import open_doc
from .main import CommandError

## The word that removes an optional field.
REMOVE = "-"
## Separator of a step's frame and ticks on the command line ("closed:4", "0:4").
STEP_SEPARATOR = ":"
## Separator of a size ("1x2") and of a cell ("27,20").
SIZE_SEPARATOR, CELL_SEPARATOR = "x", ","


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command groups.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("door", help="door animation assets (D-30): frames, cells, timing, sounds, exit (S3)")
   p.add_argument("manifest", help="asset manifest (capsule.assets/1)")
   s = p.add_subparsers(dest="door_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("list", help="the manifest's doors")
   q.set_defaults(run=cmd_list)
   q = s.add_parser("show", help="one door: timing, sounds, sheet and every cell's entries")
   q.add_argument("key")
   q.set_defaults(run=cmd_show)
   q = s.add_parser("new", help="add a door that compiles (tiles: an empty shapes sheet of frames)")
   q.add_argument("key", help="door:NAME")
   q.add_argument("--cells", default="1x1", help="WIDTHxHEIGHT metatiles (default 1x1)")
   q.add_argument("--show", choices=("tiles", "override"), default="tiles")
   q.set_defaults(run=cmd_new)
   q = s.add_parser("remove", help="remove a door")
   q.add_argument("key")
   q.set_defaults(run=cmd_remove)
   q = s.add_parser("cells", help="a door's size (cells keep their place from the bottom-left anchor)")
   q.add_argument("key")
   q.add_argument("size", help="WIDTHxHEIGHT")
   q.set_defaults(run=cmd_cells)
   q = s.add_parser("layers", help="how many map layers a door draws (1-4)")
   q.add_argument("key")
   q.add_argument("count", type=int)
   q.set_defaults(run=cmd_layers)
   q = s.add_parser("show-as", help="frames as tiles loaded into the map's tile area, or as cell overrides")
   q.add_argument("key")
   q.add_argument("show", choices=("tiles", "override"))
   q.set_defaults(run=cmd_show_as)
   q = s.add_parser("set", help="exit, load_at, frame_tiles and sounds (- removes one)")
   q.add_argument("key")
   q.add_argument("--exit", help="the direction a walker arriving on it walks out")
   q.add_argument("--load-at", dest="load_at", help="end, or the map tile a tiles door's frames load at")
   q.add_argument("--frame-tiles", dest="frame_tiles", type=int, help="tiles of one frame of the sheet")
   q.add_argument("--open-sound", dest="open_sound", help="sound key played when it opens")
   q.add_argument("--close-sound", dest="close_sound", help="sound key played when it closes")
   q.set_defaults(run=cmd_set)
   q = s.add_parser("entry", help="one entry of a cell: tK [pB] [h|v|hv] (a frame tile) or a raw map entry")
   q.add_argument("key")
   q.add_argument("cell", type=int, help="cell index, top row first")
   q.add_argument("layer", type=int)
   q.add_argument("slot", type=int, help="0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right")
   q.add_argument("value", help='e.g. "t3 p1 h" or 0x1004')
   q.add_argument("--frame", type=int, default=0, help="an override door's frame")
   q.set_defaults(run=cmd_entry)
   q = s.add_parser("steps", help="opening or closing steps FRAME:TICKS ... (FRAME a number or closed); "
                                  "close reverse: the open steps backwards")
   q.add_argument("key")
   q.add_argument("which", choices=("open", "close"))
   q.add_argument("steps", nargs="+")
   q.set_defaults(run=cmd_steps)
   q = s.add_parser("sheet", help="a tiles door's sheet from an indexed palette PNG (copied beside the manifest)")
   q.add_argument("key")
   q.add_argument("image")
   q.set_defaults(run=cmd_sheet)
   q = s.add_parser("render", help="write a frame to a PNG, alone (gray) or on a map cell (the map's palettes)")
   q.add_argument("key")
   q.add_argument("out")
   q.add_argument("--frame", default="0", help="frame index or closed (default 0)")
   q.add_argument("--world", help="world.json to draw it on")
   q.add_argument("--map", help="the map")
   q.add_argument("--at", help="X,Y anchor cell (default: the map's first cell bound to the door)")
   q.set_defaults(run=cmd_render)

   p = sub.add_parser("door-binding", help="the world's door bindings by metatile (D-30) (S3)")
   p.add_argument("world")
   s = p.add_subparsers(dest="binding_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("list", help="the bindings, and the door keys the game's asset manifests offer")
   q.set_defaults(run=cmd_binding_list)
   q = s.add_parser("add", help="bind a door to every cell showing a metatile")
   q.add_argument("tileset", help='the metatile\'s tileset, or "*" for any')
   q.add_argument("metatile")
   q.add_argument("door", help="door:NAME")
   q.set_defaults(run=cmd_binding_add)
   q = s.add_parser("set", help="change a binding")
   q.add_argument("index", type=int)
   q.add_argument("--tileset")
   q.add_argument("--metatile")
   q.add_argument("--door")
   q.set_defaults(run=cmd_binding_set)
   q = s.add_parser("remove", help="remove a binding")
   q.add_argument("index", type=int)
   q.set_defaults(run=cmd_binding_remove)
   q = s.add_parser("cells", help="a map's door anchors (warps first, then bound metatiles)")
   q.add_argument("map")
   q.add_argument("--door", help="only this door")
   q.set_defaults(run=cmd_binding_cells)

   p = sub.add_parser("draw-order", help="the world's object draw order rule (D-30) (S3)")
   p.add_argument("world")
   s = p.add_subparsers(dest="draw_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("show", help="the rule (the default when the world states none)")
   q.set_defaults(run=cmd_draw_show)
   q = s.add_parser("set", help="one field: bias, row_pixels, rows, row_step, add or wrap")
   q.add_argument("field")
   q.add_argument("value", type=int)
   q.set_defaults(run=cmd_draw_set)
   q = s.add_parser("base", help="one elevation's base")
   q.add_argument("elevation", type=int)
   q.add_argument("value", type=int)
   q.set_defaults(run=cmd_draw_base)
   q = s.add_parser("reset", help="remove the rule (the default applies)")
   q.set_defaults(run=cmd_draw_reset)
   q = s.add_parser("preview", help="sprites BOTTOM:ELEVATION ... front to back with their sort keys")
   q.add_argument("sprites", nargs="+", help="e.g. 96:3 112:4 (bottom edge on screen, pixels : elevation)")
   q.set_defaults(run=cmd_draw_preview)


def _pair(text: str, sep: str, what: str) -> tuple[int, int]:
   """!Two numbers from "AxB" or "A,B".
   @param text  the text
   @param sep   the separator
   @param what  what it is, for messages
   @return the numbers
   """
   parts = text.split(sep)
   try:
      a, b = (int(v) for v in parts)
   except ValueError:
      raise CommandError(f"{what} looks like 1{sep}2, got {text!r}") from None
   return a, b


def _int(text: str, what: str) -> int:
   """!A whole number (0x... too).
   @param text  the text
   @param what  what it is, for messages
   @return the number
   """
   try:
      return int(text, 0)
   except ValueError:
      raise CommandError(f"{what} needs a number, got {text!r}") from None


def _door(doc: Any, key: str) -> dict[str, Any]:
   """!A door asset, which must exist.
   @param doc  Document
   @param key  its key
   @return the asset
   """
   a = doc.get(key)
   if a.get("kind") != doors.KIND:
      raise CommandError(f"{key!r} is a {a.get('kind')}, not a door")
   return a


def _save(doc: Any, key: str | None = None) -> None:
   """!Saves the manifest (its doors compiled by each edit already); prints the door.
   @param doc  Document
   @param key  a door to print, or None
   @return None
   """
   doc.save()
   if key is not None:
      print("\n".join(doors.lines(doc, key)))


def cmd_list(args: argparse.Namespace) -> None:
   """!door list. @param args  parsed arguments
   @return None
   """
   out = doors.lines(open_doc(args.manifest))
   print("\n".join(out) if out else "no doors")


def cmd_show(args: argparse.Namespace) -> None:
   """!door show. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _door(doc, args.key)
   print("\n".join(doors.lines(doc, args.key)))


def cmd_new(args: argparse.Namespace) -> None:
   """!door new. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   w, h = _pair(args.cells, SIZE_SEPARATOR, "--cells")
   with doc.edit("New door"):
      doors.new_door(doc, args.key, w, h, args.show)
   _save(doc, args.key)


def cmd_remove(args: argparse.Namespace) -> None:
   """!door remove. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _door(doc, args.key)
   with doc.edit("Remove door"):
      doc.remove_asset(args.key)
   _save(doc)
   print(f"removed {args.key}")


def cmd_cells(args: argparse.Namespace) -> None:
   """!door cells. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _door(doc, args.key)
   w, h = _pair(args.size, SIZE_SEPARATOR, "the size")
   with doc.edit("Door cells"):
      doors.set_cells(doc, args.key, w, h)
   _save(doc, args.key)


def cmd_layers(args: argparse.Namespace) -> None:
   """!door layers. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _door(doc, args.key)
   with doc.edit("Door layers"):
      doors.set_layers(doc, args.key, args.count)
   _save(doc, args.key)


def cmd_show_as(args: argparse.Namespace) -> None:
   """!door show-as. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _door(doc, args.key)
   with doc.edit("Door frames"):
      doors.set_show(doc, args.key, args.show)
   _save(doc, args.key)


def cmd_set(args: argparse.Namespace) -> None:
   """!door set. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   a = _door(doc, args.key)
   fields: dict[str, Any] = {}
   if args.exit is not None:
      fields["exit"] = None if args.exit == REMOVE else args.exit
   if args.load_at is not None:
      fields["load_at"] = None if args.load_at == REMOVE else \
         args.load_at if args.load_at == doors.load_end_word() else _int(args.load_at, "--load-at")
   if args.frame_tiles is not None:
      fields["frame_tiles"] = args.frame_tiles
   if args.open_sound is not None or args.close_sound is not None:
      sounds = dict(a.get("sounds", {}))
      for which, v in (("open", args.open_sound), ("close", args.close_sound)):
         if v is not None:
            sounds[which] = None if v == REMOVE else v
      fields["sounds"] = sounds
   if not fields:
      raise CommandError("give --exit, --load-at, --frame-tiles, --open-sound or --close-sound")
   with doc.edit("Door"):
      doors.set_fields(doc, args.key, **fields)
   _save(doc, args.key)


def cmd_entry(args: argparse.Namespace) -> None:
   """!door entry. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _door(doc, args.key)
   with doc.edit("Door entry"):
      doors.set_entry(doc, args.key, args.cell, args.layer, args.slot, doors.parse_entry(args.value), args.frame)
   _save(doc, args.key)


def parse_steps(words: list[str]) -> list[list[Any]] | str:
   """!Steps from the command line: FRAME:TICKS words (FRAME a number or "closed"), or "reverse".
   @param words  the words
   @return [[frame, ticks]], or "reverse"
   """
   if words == [doors.reverse_word()]:
      return doors.reverse_word()
   out: list[list[Any]] = []
   for w in words:
      frame, _sep, ticks = w.partition(STEP_SEPARATOR)
      if not ticks.isdigit():
         raise CommandError(f"a step is FRAME:TICKS (FRAME a number or {doors.closed_word()}), got {w!r}")
      out.append([frame if frame == doors.closed_word() else _int(frame, "a step's frame"), int(ticks)])
   return out


def cmd_steps(args: argparse.Namespace) -> None:
   """!door steps. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _door(doc, args.key)
   with doc.edit("Door steps"):
      doors.set_steps(doc, args.key, args.which, parse_steps(args.steps))
   _save(doc, args.key)


def cmd_sheet(args: argparse.Namespace) -> None:
   """!door sheet. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _door(doc, args.key)
   with doc.edit("Door sheet"):
      rel = doors.set_sheet_image(doc, args.key, args.image)
   _save(doc, args.key)
   print(f"copied to {rel}")


def cmd_render(args: argparse.Namespace) -> None:
   """!door render. @param args  parsed arguments
   @return None
   """
   from ..core import engine
   doc = open_doc(args.manifest)
   _door(doc, args.key)
   r = doors.compiled(doc, args.key)
   if not r.ok:
      raise CommandError(r.error)
   frame: Any = args.frame if args.frame == doors.closed_word() else _int(args.frame, "--frame")
   if args.world:
      p = Project.open(args.world)
      if args.map not in p.map_names():
         raise CommandError(f"--map: the world has no map {args.map!r}")
      if args.at:
         x, y = _pair(args.at, CELL_SEPARATOR, "--at")
      else:
         bound = doors.bound_cells(p, args.map, args.key)
         if not bound:
            raise CommandError(f"no cell of {args.map} is bound to {args.key}; give --at X,Y")
         x, y = bound[0][0], bound[0][1]
      img = doors.render_on_map(p, args.map, x, y, r.compiled, frame)
      if img is None:
         raise CommandError(p.compiled_map(args.map)[1])
   else:
      img = doors.render_alone(r.compiled, frame)
   engine.bitmap().write_png(args.out, *img)
   print(f"wrote {args.out} ({img[0]}x{img[1]})")


def _world_change(args: argparse.Namespace, label: str, fn: Any) -> Project:
   """!Runs a change of the world file, compiles and saves.
   @param args   parsed arguments (world)
   @param label  undo label
   @param fn     callable(world Document)
   @return the Project
   """
   p = Project.open(args.world)
   with p.world.edit(label):
      fn(p.world)
   error = p.validate()
   if error:
      raise CommandError(error)
   p.save_all()
   return p


def cmd_binding_list(args: argparse.Namespace) -> None:
   """!door-binding list. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   items = doors.bindings(p.world)
   for i, b in enumerate(items):
      print(f"{i}: {b.get('tileset')}/{b.get('metatile')} -> {b.get('door')}")
   if not items:
      print("no door bindings by metatile")
   keys = doors.door_keys(p)
   print(f"door keys: {', '.join(keys) if keys else 'none found'}")


def cmd_binding_add(args: argparse.Namespace) -> None:
   """!door-binding add. @param args  parsed arguments
   @return None
   """
   out = {"i": 0}

   def run(world: Any) -> None:
      out["i"] = doors.add_binding(world, args.tileset, args.metatile, args.door)
   _world_change(args, "Add door binding", run)
   print(f"door binding {out['i']}: {args.tileset}/{args.metatile} -> {args.door}")


def cmd_binding_set(args: argparse.Namespace) -> None:
   """!door-binding set. @param args  parsed arguments
   @return None
   """
   fields = {k: getattr(args, k) for k in ("tileset", "metatile", "door") if getattr(args, k) is not None}
   if not fields:
      raise CommandError("give --tileset, --metatile or --door")
   _world_change(args, "Door binding", lambda world: doors.set_binding(world, args.index, **fields))
   print(f"door binding {args.index} changed")


def cmd_binding_remove(args: argparse.Namespace) -> None:
   """!door-binding remove. @param args  parsed arguments
   @return None
   """
   _world_change(args, "Remove door binding", lambda world: doors.remove_binding(world, args.index))
   print(f"door binding {args.index} removed")


def cmd_binding_cells(args: argparse.Namespace) -> None:
   """!door-binding cells. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   if args.map not in p.map_names():
      raise CommandError(f"the world has no map {args.map!r}")
   cells = doors.bound_cells(p, args.map, args.door)
   for x, y, key, how in cells:
      print(f"{x},{y}: {key} ({how})")
   if not cells:
      print("no door anchors")


def cmd_draw_show(args: argparse.Namespace) -> None:
   """!draw-order show. @param args  parsed arguments
   @return None
   """
   print("\n".join(draw_order.lines(Project.open(args.world).world)))


def cmd_draw_set(args: argparse.Namespace) -> None:
   """!draw-order set. @param args  parsed arguments
   @return None
   """
   if args.field == draw_order.BASE_KEY:
      raise CommandError("set one elevation's base with `draw-order WORLD base ELEVATION VALUE`")
   p = _world_change(args, "Draw order", lambda world: draw_order.set_field(world, args.field, args.value))
   print("\n".join(draw_order.lines(p.world)))


def cmd_draw_base(args: argparse.Namespace) -> None:
   """!draw-order base. @param args  parsed arguments
   @return None
   """
   p = _world_change(args, "Draw order", lambda world: draw_order.set_base(world, args.elevation, args.value))
   print("\n".join(draw_order.lines(p.world)))


def cmd_draw_reset(args: argparse.Namespace) -> None:
   """!draw-order reset. @param args  parsed arguments
   @return None
   """
   p = _world_change(args, "Draw order", draw_order.reset)
   print("\n".join(draw_order.lines(p.world)))


def cmd_draw_preview(args: argparse.Namespace) -> None:
   """!draw-order preview. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   r = draw_order.rule(p.world)
   sprites = []
   for i, text in enumerate(args.sprites):
      bottom, elevation = _pair(text, STEP_SEPARATOR, "a sprite")
      sprites.append(draw_order.Sprite(f"sprite {i}", bottom, elevation,
                                       draw_order.level_priority(p.world, elevation)))
   for k, s in enumerate(draw_order.order(r, sprites)):
      place = "front" if k == 0 else "behind"
      print(f"{place}: {s.name} (bottom {s.bottom}, elevation {s.elevation}): priority {s.priority}, "
            f"sub-priority {s.sub}, key {s.key()}")
