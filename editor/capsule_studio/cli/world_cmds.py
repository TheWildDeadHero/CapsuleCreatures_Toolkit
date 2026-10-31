"""!`capsule-studio world|map|tileset ...`: worlds, maps and tilesets. I2 / I3: `map dictionary all|list` (a map's
dictionary as every metatile of its tilesets, or the ones painted) and the fixed-placement and animation actions of
`tileset` (cli/tileset_cmds.py)."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core import engine, mapgroups, maps, mapview, tilesets
from ..core.document import DocumentError
from ..core.world import Project
from . import tileset_cmds
from .common import RGB_BYTES_PER_PIXEL, write_rgb_png
from .main import CommandError

if TYPE_CHECKING:
   from ..core.document import Document

## GBA backgrounds a tile layer can be on (BG0-BG3).
BG_COUNT = 4
## Draw priorities of a background (0 = front, 3 = back).
PRIORITY_COUNT = 4
## Default border metatiles `world render` draws around the chunks.
DEFAULT_RENDER_MARGIN = 2
## A render margin is added on both sides of each axis.
MARGIN_SIDES = 2
## Default metatiles per row of `tileset render`.
DEFAULT_TILESET_COLUMNS = 8
## Bytes per pixel of an RGBA image.
RGBA_BYTES_PER_PIXEL = 4
## Position of the optional purpose in a --layers entry "BG:PRIORITY[:PURPOSE]".
LAYER_PURPOSE_PART = 2
## Pixels per tile side.
TILE_PIXELS = 8
## Pixels per metatile side.
METATILE_PIXELS = 16
## Gap drawn between (and around) metatiles in `tileset render`, pixels.
METATILE_GAP = 1
## Background color of `tileset render` (RGBA): it shows through the gaps.
TILESET_BACKGROUND = (40, 40, 48, 255)
## Enlargement of `tileset render` PNGs.
TILESET_RENDER_SCALE = 2


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command groups.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("world", help="worlds (capsule.world/1) with their tilesets and maps")
   s = p.add_subparsers(dest="world_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("validate", help="compile the world with the engine's map compiler")
   q.add_argument("world")
   q.set_defaults(run=cmd_validate)
   q = s.add_parser("info", help="list maps and tilesets with their sizes")
   q.add_argument("world")
   q.set_defaults(run=cmd_info)
   q = s.add_parser("new", help="create an empty world file")
   q.add_argument("world")
   q.set_defaults(run=cmd_new)
   q = s.add_parser("import", help="import maps and tilesets from another world (with the tilesets, images and "
                                   "behaviors they need)")
   q.add_argument("world")
   q.add_argument("source", help="the other world's world.json")
   q.add_argument("--maps", nargs="+", default=[], metavar="MAP")
   q.add_argument("--tilesets", nargs="+", default=[], metavar="TILESET")
   q.add_argument("--dry-run", action="store_true", help="only report what would be imported")
   q.set_defaults(run=cmd_import)
   q = s.add_parser("groups", help="show the map group tree")
   q.add_argument("world")
   q.set_defaults(run=cmd_groups)
   q = s.add_parser("group-add", help="add a map group (a path like Outside/Towns)")
   q.add_argument("world")
   q.add_argument("group", help='group path, "/"-separated')
   q.set_defaults(run=cmd_group_add)
   q = s.add_parser("group-rename", help="rename a map group")
   q.add_argument("world")
   q.add_argument("group")
   q.add_argument("name")
   q.set_defaults(run=cmd_group_rename)
   q = s.add_parser("group-remove", help="remove a map group (its maps and subgroups move up)")
   q.add_argument("world")
   q.add_argument("group")
   q.set_defaults(run=cmd_group_remove)
   q = s.add_parser("group-move", help="put a map into a group (- for ungrouped)")
   q.add_argument("world")
   q.add_argument("map")
   q.add_argument("group", help='group path, or "-"')
   q.set_defaults(run=cmd_group_move)
   q = s.add_parser("render", help="draw a map (its chunks plus a border margin) to a PNG")
   q.add_argument("world")
   q.add_argument("map")
   q.add_argument("output")
   q.add_argument("--collision", action="store_true", help="tint cells like the sandbox's collision view")
   q.add_argument("--margin", type=int, default=DEFAULT_RENDER_MARGIN, help="border metatiles around the chunks")
   q.set_defaults(run=cmd_render)

   p = sub.add_parser("map", help="paint maps (tile layers and the attribute layer)")
   p.add_argument("world")
   p.add_argument("map")
   s = p.add_subparsers(dest="map_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("new", help="add a blank map (or one chunk and border of one metatile on its back layer)")
   q.add_argument("metatile", nargs="?", help='"tileset/metatile" to fill with; leave out for a blank map')
   q.add_argument("--tilesets", nargs="+", default=[], metavar="TILESET", help="tilesets the map draws from")
   q.add_argument("--group", metavar="PATH", help='map group to put it in, like "Outside/Towns"')
   q.add_argument("--layers", nargs="+", metavar="BG:PRIORITY[:PURPOSE]",
                  help="tile layers (default 3:3:terrain 2:2:terrain 1:1:canopy)")
   q.set_defaults(run=cmd_map_new)
   q = s.add_parser("tilesets", help="set the tilesets the map draws from")
   q.add_argument("tilesets", nargs="*", metavar="TILESET")
   q.set_defaults(run=cmd_map_tilesets)
   q = s.add_parser("dictionary", help="show the metatile dictionary, or make it every metatile of the map's "
                                       "tilesets (all, I2) or the metatiles painted (list); the cells are renumbered")
   q.add_argument("form", nargs="?", choices=("all", "list"))
   q.set_defaults(run=cmd_map_dictionary)
   q = s.add_parser("layers", help="list the tile layers, back to front")
   q.set_defaults(run=cmd_layers)
   q = s.add_parser("layer-add", help="add an empty tile layer on a free BG")
   q.add_argument("bg", type=int, choices=range(BG_COUNT))
   q.add_argument("--priority", type=int, choices=range(PRIORITY_COUNT),
                  help="draw priority, 0 = front (default: the BG number)")
   q.add_argument("--purpose", choices=maps.PURPOSES, default="terrain")
   q.set_defaults(run=cmd_layer_add)
   q = s.add_parser("layer-remove", help="remove a tile layer and everything painted on it")
   q.add_argument("bg", type=int, choices=range(BG_COUNT))
   q.set_defaults(run=cmd_layer_remove)
   q = s.add_parser("layer-set", help="change a tile layer's BG, priority or purpose")
   q.add_argument("bg", type=int, choices=range(BG_COUNT))
   q.add_argument("--to-bg", type=int, choices=range(BG_COUNT), help="move the layer to another free BG")
   q.add_argument("--priority", type=int, choices=range(PRIORITY_COUNT))
   q.add_argument("--purpose", choices=maps.PURPOSES)
   q.set_defaults(run=cmd_layer_set)
   for name, helptext in (("paint", "paint a rectangle on a tile layer"), ("fill", "flood-fill a tile layer"),
                          ("clear", "clear a rectangle of a tile layer (the cells stay painted)")):
      q = s.add_parser(name, help=helptext)
      if name != "clear":
         q.add_argument("metatile", help='"tileset/metatile"')
      q.add_argument("x", type=int)
      q.add_argument("y", type=int)
      if name != "fill":
         q.add_argument("x2", type=int, nargs="?")
         q.add_argument("y2", type=int, nargs="?")
      q.add_argument("--bg", type=int, choices=range(BG_COUNT), help="the layer's BG (default: the back layer)")
      q.set_defaults(run={"paint": cmd_paint, "fill": cmd_fill, "clear": cmd_clear}[name])
   q = s.add_parser("cells", help="set attributes of a rectangle of painted cells")
   q.add_argument("x", type=int)
   q.add_argument("y", type=int)
   q.add_argument("x2", type=int)
   q.add_argument("y2", type=int)
   # the fields' ranges are the engine's (core.maps.cell_fields(), checked when the command runs: the parser is
   # built before --engine names the engine)
   q.add_argument("--collision", type=int)
   q.add_argument("--elevation", type=int)
   q.add_argument("--behavior", metavar="NAME", help="world behavior name")
   q.add_argument("--encounter", choices=("yes", "no"))
   q.add_argument("--slot", type=int, metavar="0-15",
                  help="encounter slot: which of the map's encounter tables the cells use")
   q.add_argument("--env", type=int, metavar="0-255")
   q.set_defaults(run=cmd_cells)
   q = s.add_parser("erase", help="unpaint a rectangle: attributes and every layer (the border shows there)")
   q.add_argument("x", type=int)
   q.add_argument("y", type=int)
   q.add_argument("x2", type=int)
   q.add_argument("y2", type=int)
   q.set_defaults(run=cmd_erase)
   q = s.add_parser("border", help="set the border size and one tile layer's pattern")
   q.add_argument("width", type=int)
   q.add_argument("height", type=int)
   q.add_argument("metatiles", nargs="+", help='"tileset/metatile" (or blank) per border cell, rows first')
   q.add_argument("--bg", type=int, choices=range(BG_COUNT), help="the layer's BG (default: the back layer)")
   q.set_defaults(run=cmd_border)

   p = sub.add_parser("tileset", help="tilesets")
   p.add_argument("world")
   p.add_argument("tileset")
   s = p.add_subparsers(dest="tileset_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("new", help="add an empty tileset to the world")
   q.set_defaults(run=cmd_tileset_new)
   q = s.add_parser("import-sheet", help="add a PNG tile sheet (palette chosen from its colors)")
   q.add_argument("image")
   q.add_argument("--name", help="sheet name (default: the file name)")
   q.add_argument("--metatiles", action="store_true", help="also add one metatile per non-empty 16x16 block")
   q.add_argument("--transparent", metavar="COLOR", help='color that becomes transparent, like "#ff00ff"')
   q.set_defaults(run=cmd_import_sheet)
   q = s.add_parser("transparent", help="set (or clear) an image sheet's transparent color")
   q.add_argument("sheet")
   q.add_argument("color", help='like "#ff00ff", or none')
   q.set_defaults(run=cmd_sheet_transparent)
   q = s.add_parser("render", help="draw every metatile of the tileset to a PNG")
   q.add_argument("output")
   q.add_argument("--columns", type=int, default=DEFAULT_TILESET_COLUMNS)
   q.set_defaults(run=cmd_tileset_render)
   tileset_cmds.register_actions(s)   # I2 / I3: placement, banks, raw entries, indexed sheets, animations


def _project(path: str | Path) -> Project:
   """!Opens a world.
   @param path  world.json
   @return Project
   """
   return Project.open(path)


def _check(project: Project) -> None:
   """!Compiles and raises on errors.
   @param project  Project
   @return None
   """
   error = project.validate()
   if error:
      raise CommandError(error)


def _png(path: str | Path, img: tuple[int, int, bytes | bytearray], scale: int = 1) -> None:
   """!Writes an RGBA image (alpha dropped) as a PNG.
   @param path   file
   @param img    (w, h, RGBA)
   @param scale  integer factor
   @return None
   """
   w, h, px = img
   k = max(1, scale)
   rgb = bytearray()
   for y in range(h * k):
      for x in range(w * k):
         # The source pixel this scaled-up pixel comes from; its alpha byte is left out.
         o = ((y // k) * w + x // k) * RGBA_BYTES_PER_PIXEL
         rgb += px[o:o + RGB_BYTES_PER_PIXEL]
   write_rgb_png(path, w * k, h * k, rgb)


def cmd_validate(args: argparse.Namespace) -> int:
   """!world validate.
   @param args  parsed arguments
   @return 1 on a compile error or an extension error, otherwise 0
   """
   p = _project(args.world)
   result, error = p.compile()
   if error:
      print(f"error: {error}")
      return 1
   for mp in result["maps"]:
      print(f"ok: map {mp['name']}: {len(mp['chunks'])} chunks, {len(mp['metatiles'])} metatiles, "
            f"{len(mp['tiles'])}/{engine.tool('map_compiler').MAX_TILES} tiles, {len(mp['palettes'])} palettes")
   reg = getattr(args, "registry", None)   # extensions' validators (D-10)
   found = reg.validate(p) if reg is not None else []
   for d in found:
      print(f"{d.level}: {d.message}" + (f" at {d.at[0]},{d.at[1]}" if d.at else "") + f" [{d.plugin}]")
   return 1 if any(d.level == "error" for d in found) else 0


def cmd_info(args: argparse.Namespace) -> None:
   """!world info. @param args  parsed arguments
   @return None
   """
   p = _project(args.world)
   print(f"world {p.world.data.get('id', '?')} in {p.base}")
   print("behaviors: " + ", ".join(p.behavior_names()))
   for t in p.tileset_names():
      d = p.tileset(t).data
      fixed = f", fixed at tile {d['place'].get('tile')} bank {d['place'].get('palette')}" \
         if tilesets.is_fixed(p.tileset(t)) else ""
      print(f"tileset {t}: {len(d.get('sheets', []))} sheets, {len(d.get('metatiles', []))} metatiles, "
            f"{len(d.get('animations', []))} animations{fixed}")
   for m in p.map_names():
      d = p.map(m).data
      b = maps.bounds(d)
      span = "empty"
      if b:
         bx0, by0, bx1, by1 = b   # inclusive
         span = f"{bx1 - bx0 + 1}x{by1 - by0 + 1} metatiles"
      layers = ", ".join(f"BG{maps.layers_of(d)[i].get('bg')}" for i in maps.draw_order(d)) or "no layers"
      every = ", dictionary: every metatile of its tilesets" if maps.uses_all(d) else ""
      print(f"map {m}: {len(d.get('chunks', []))} chunks, {span}, tile layers {layers} (back to front){every}")


def cmd_new(args: argparse.Namespace) -> None:
   """!world new. @param args  parsed arguments
   @return None
   """
   Project.create(args.world, Path(args.world).resolve().parent.name)
   print(f"created {args.world}")


def cmd_import(args: argparse.Namespace) -> None:
   """!world import. @param args  parsed arguments
   @return None
   """
   from ..core import importer
   if not args.maps and not args.tilesets:
      raise CommandError("give --maps and/or --tilesets")
   p = _project(args.world)
   try:
      if args.dry_run:
         plan = importer.plan(p, Project.open(args.source), args.maps, args.tilesets)
         for t, (new, reused) in plan["tilesets"].items():
            print(f"tileset {t}: " + ("reused" if reused else f"imported as {new}"))
         for m, new in plan["maps"].items():
            print(f"map {m}: imported as {new}")
         for b in plan["behaviors"]:
            print(f"behavior {b}: added")
         for c in plan["classes"]:
            print(f"vehicle class {c}: added")
         for key, names in plan["names"].items():   # F2: map tags, object kinds
            for n in names:
               print(f"{key.replace('_', ' ')} {n}: added")
         for line in plan["notes"]:
            print(line)
         print("(dry run: nothing written)")
         return
      report = p.import_from(args.source, args.maps, args.tilesets)
   except DocumentError as e:
      raise CommandError(str(e))
   _check(p)
   p.save_all()
   for line in report:
      print(line)


def _group_path(text: str) -> tuple[str, ...]:
   """!A group path from its "/"-separated text.
   @param text  like "Outside/Towns"
   @return tuple of names
   """
   return tuple(part for part in text.split("/") if part)


def _edit_world(args: argparse.Namespace, label: str, fn: Callable[[Project, Document], object]) -> None:
   """!Runs a change on the world file and saves it.
   @param args   parsed arguments
   @param label  undo label
   @param fn     callable(project, world Document)
   @return None
   """
   p = _project(args.world)
   try:
      with p.world.edit(label):
         fn(p, p.world)
   except ValueError as e:
      raise CommandError(str(e))
   _check(p)
   p.save_all()


def cmd_groups(args: argparse.Namespace) -> None:
   """!world groups. @param args  parsed arguments
   @return None
   """
   p = _project(args.world)

   def show(nodes: list[tuple[Any, ...]], depth: int) -> None:
      # Nodes are ("group", name, path, children) or ("map", name).
      for n in nodes:
         if n[0] == "group":
            _kind, name, _path, children = n
            print("  " * depth + name + "/")
            show(children, depth + 1)
         else:
            print("  " * depth + n[1])
   show(mapgroups.tree(p.world.data, p.map_names()), 0)


def cmd_group_add(args: argparse.Namespace) -> None:
   """!world group-add. @param args  parsed arguments
   @return None
   """
   path = _group_path(args.group)
   if not path:
      raise CommandError("give a group path")
   _edit_world(args, "Add group", lambda p, w: mapgroups.add_group(w, path[:-1], path[-1]))


def cmd_group_rename(args: argparse.Namespace) -> None:
   """!world group-rename. @param args  parsed arguments
   @return None
   """
   _edit_world(args, "Rename group", lambda p, w: mapgroups.rename_group(w, _group_path(args.group), args.name))


def cmd_group_remove(args: argparse.Namespace) -> None:
   """!world group-remove. @param args  parsed arguments
   @return None
   """
   _edit_world(args, "Remove group", lambda p, w: mapgroups.remove_group(w, _group_path(args.group)))


def cmd_group_move(args: argparse.Namespace) -> None:
   """!world group-move. @param args  parsed arguments
   @return None
   """
   path = None if args.group == "-" else _group_path(args.group)
   _edit_world(args, "Move map", lambda p, w: mapgroups.move_map(w, args.map, path))


def cmd_render(args: argparse.Namespace) -> None:
   """!world render. @param args  parsed arguments
   @return None
   """
   p = _project(args.world)
   # I2: the map alone against its tilesets; the collision view needs the world's behaviors (a whole compile)
   world, error = p.compile([args.map]) if args.collision else (None, None)
   if error:
      raise CommandError(error)
   mp, error = p.compiled_map(args.map)
   if mp is None:
      raise CommandError(error)
   x0, y0, w, h = mapview.map_bounds(mp)
   m = max(0, args.margin)
   img = mapview.render_map(mp, x0 - m, y0 - m, w + MARGIN_SIDES * m, h + MARGIN_SIDES * m, world, args.collision)
   _png(args.output, img)
   print(f"wrote {args.output} ({img[0]}x{img[1]})")


def _edit_map(args: argparse.Namespace, label: str, fn: Callable[[Project, Document], object]) -> None:
   """!Runs a change on a map and saves the world.
   @param args   parsed arguments
   @param label  undo label
   @param fn     callable(project, map Document) doing the change
   @return None
   """
   p = _project(args.world)
   doc = p.map(args.map)
   with doc.edit(label):
      fn(p, doc)
   _check(p)
   p.save_all()


def _layer_spec(text: str) -> tuple[int, int, str]:
   """!Parses a --layers entry.
   @param text  "BG:PRIORITY[:PURPOSE]"
   @return (bg, priority, purpose)
   """
   parts = text.split(":")
   try:
      bg, prio = int(parts[0]), int(parts[1])
   except (IndexError, ValueError):
      raise CommandError(f"a layer looks like 2:2 or 1:1:canopy, not {text!r}") from None
   purpose = parts[LAYER_PURPOSE_PART] if len(parts) > LAYER_PURPOSE_PART else "terrain"
   if not (0 <= bg < BG_COUNT and 0 <= prio < PRIORITY_COUNT) or purpose not in maps.PURPOSES:
      raise CommandError(f"{text!r}: BG and priority are 0-3; purposes are {', '.join(maps.PURPOSES)}")
   return bg, prio, purpose


def _layer(doc: Document, bg: int | None) -> int:
   """!A layer index by BG number.
   @param doc  map Document
   @param bg   BG number, or None for the back layer
   @return layer index
   """
   ls = maps.layers_of(doc.data)
   if not ls:
      raise CommandError("the map has no tile layers (add one with layer-add)")
   if bg is None:
      return maps.draw_order(doc.data)[0]
   for i, ly in enumerate(ls):
      if ly.get("bg") == bg:
         return i
   raise CommandError(f"the map has no layer on BG{bg} (it has {', '.join('BG%d' % ly.get('bg') for ly in ls)})")


def cmd_map_new(args: argparse.Namespace) -> None:
   """!map new. @param args  parsed arguments
   @return None
   """
   p = _project(args.world)
   layers = [_layer_spec(t) for t in args.layers] if args.layers else None
   try:
      p.add_map(args.map, fill=args.metatile, tilesets=args.tilesets, layers=layers,
                group=_group_path(args.group) if args.group else None)
   except DocumentError as e:
      raise CommandError(str(e))
   _check(p)
   p.save_all()


def cmd_map_tilesets(args: argparse.Namespace) -> None:
   """!map tilesets. @param args  parsed arguments
   @return None
   """
   def run(p: Project, doc: Document) -> None:
      maps.set_tilesets(doc, args.tilesets, p.tileset_names(), p.metatile_names)
      print("tilesets: " + (", ".join(doc.data["tilesets"]) or "none"))
   _edit_map(args, "Map tilesets", run)


def cmd_map_dictionary(args: argparse.Namespace) -> None:
   """!map dictionary (I2). @param args  parsed arguments
   @return None
   """
   def show(p: Project, doc: Document) -> None:
      names = maps.dictionary(doc.data, p.metatile_names)
      form = "every metatile of its tilesets (all)" if maps.uses_all(doc.data) else "the metatiles painted (list)"
      print(f"dictionary: {form}, {len(names)} of {maps.max_metatiles()} entries")
   if args.form is None:
      p = _project(args.world)
      show(p, p.map(args.map))
      return

   def run(p: Project, doc: Document) -> None:
      try:
         (maps.set_all if args.form == "all" else maps.set_listed)(doc, p.metatile_names)
      except ValueError as e:
         raise CommandError(str(e))
      show(p, doc)
   _edit_map(args, "Dictionary", run)


def cmd_layers(args: argparse.Namespace) -> None:
   """!map layers. @param args  parsed arguments
   @return None
   """
   doc = _project(args.world).map(args.map)
   order = maps.draw_order(doc.data)
   if not order:
      print("no tile layers")
   for i in order:
      print(maps.layer_label(doc.data, i))


def cmd_layer_add(args: argparse.Namespace) -> None:
   """!map layer-add. @param args  parsed arguments
   @return None
   """
   _edit_map(args, "Add layer", lambda p, doc: maps.add_layer(doc, args.bg, args.priority, args.purpose))


def cmd_layer_remove(args: argparse.Namespace) -> None:
   """!map layer-remove. @param args  parsed arguments
   @return None
   """
   _edit_map(args, "Remove layer", lambda p, doc: maps.remove_layer(doc, _layer(doc, args.bg)))


def cmd_layer_set(args: argparse.Namespace) -> None:
   """!map layer-set. @param args  parsed arguments
   @return None
   """
   def run(p: Project, doc: Document) -> None:
      maps.set_layer(doc, _layer(doc, args.bg), args.to_bg, args.priority, args.purpose)
   _edit_map(args, "Layer", run)


def cmd_paint(args: argparse.Namespace) -> None:
   """!map paint. @param args  parsed arguments
   @return None
   """
   x2 = args.x if args.x2 is None else args.x2
   y2 = args.y if args.y2 is None else args.y2

   def run(p: Project, doc: Document) -> None:
      n = maps.rect(doc, _layer(doc, args.bg), args.x, args.y, x2, y2,
                    maps.dictionary_index(doc, args.metatile, p.metatile_names))
      print(f"{n} cells")
   _edit_map(args, "Paint", run)


def cmd_fill(args: argparse.Namespace) -> None:
   """!map fill. @param args  parsed arguments
   @return None
   """
   def run(p: Project, doc: Document) -> None:
      n = maps.fill(doc, _layer(doc, args.bg), args.x, args.y,
                    maps.dictionary_index(doc, args.metatile, p.metatile_names))
      maps.compact_dictionary(doc)
      print(f"{n} cells")
   _edit_map(args, "Fill", run)


def cmd_clear(args: argparse.Namespace) -> None:
   """!map clear. @param args  parsed arguments
   @return None
   """
   x2 = args.x if args.x2 is None else args.x2
   y2 = args.y if args.y2 is None else args.y2

   def run(p: Project, doc: Document) -> None:
      n = maps.rect(doc, _layer(doc, args.bg), args.x, args.y, x2, y2, None)
      maps.compact_dictionary(doc)
      print(f"{n} cells")
   _edit_map(args, "Clear", run)


def cmd_cells(args: argparse.Namespace) -> None:
   """!map cells. @param args  parsed arguments
   @return None
   """
   if all(v is None for v in (args.collision, args.elevation, args.behavior, args.encounter, args.slot, args.env)):
      raise CommandError("give --collision, --elevation, --behavior, --encounter, --slot and/or --env")

   def run(p: Project, doc: Document) -> None:
      beh = None if args.behavior is None else maps.behavior_index(doc, args.behavior, p.behavior_names())
      enc = None if args.encounter is None else args.encounter == "yes"
      # the values fit their fields (ValueError "NAME is 0-MAX" otherwise), painted cells in the rectangle or not
      maps.with_fields(maps.make_cell(), collision=args.collision, elevation=args.elevation, slot=args.slot,
                       env=args.env)
      n = maps.rect_attributes(doc, args.x, args.y, args.x2, args.y2, collision=args.collision,
                               elevation=args.elevation, behavior=beh, encounter=enc, slot=args.slot,
                               env=args.env)
      maps.compact_behaviors(doc)
      print(f"{n} cells")
   _edit_map(args, "Cells", run)


def cmd_erase(args: argparse.Namespace) -> None:
   """!map erase. @param args  parsed arguments
   @return None
   """
   def run(p: Project, doc: Document) -> None:
      for x, y in maps.rect_cells(args.x, args.y, args.x2, args.y2):
         maps.erase(doc, x, y)
      maps.trim(doc)
      maps.compact_dictionary(doc)
      maps.compact_behaviors(doc)
   _edit_map(args, "Erase", run)


def cmd_border(args: argparse.Namespace) -> None:
   """!map border. @param args  parsed arguments
   @return None
   """
   if len(args.metatiles) != args.width * args.height:
      raise CommandError(f"a {args.width}x{args.height} border takes {args.width * args.height} metatiles")

   def run(p: Project, doc: Document) -> None:
      layer = _layer(doc, args.bg)
      maps.resize_border(doc, args.width, args.height, p.metatile_names)
      for i, m in enumerate(args.metatiles):
         maps.paint_border(doc, layer, [(i % args.width, i // args.width)], None if m == "blank" else m,
                           p.metatile_names)
   _edit_map(args, "Border", run)


def cmd_tileset_new(args: argparse.Namespace) -> None:
   """!tileset new. @param args  parsed arguments
   @return None
   """
   p = _project(args.world)
   p.add_tileset(args.tileset)
   p.save_all()


def cmd_import_sheet(args: argparse.Namespace) -> None:
   """!tileset import-sheet. @param args  parsed arguments
   @return None
   """
   p = _project(args.world)
   doc = p.tileset(args.tileset)
   img = engine.bitmap().read_png(args.image)
   img_w, img_h, _rgba = img
   with doc.edit("Import sheet"):
      name = tilesets.add_image_sheet(doc, args.name or Path(args.image).stem, img)
      if args.transparent:
         tilesets.set_transparent(doc, name, args.transparent)
   added = []
   if args.metatiles:
      sheet = tilesets.compile_sheet(p, args.tileset, name)
      with doc.edit("Metatiles from sheet"):
         added = tilesets.metatiles_from_sheet(doc, name, sheet)
   ts, _, error = p.compiled_tileset(args.tileset)
   if ts is None:
      raise CommandError(error)
   p.save_all()
   print(f"sheet {name}: {img_w // TILE_PIXELS}x{img_h // TILE_PIXELS} tiles, {len(added)} metatiles added")


def cmd_sheet_transparent(args: argparse.Namespace) -> None:
   """!tileset transparent. @param args  parsed arguments
   @return None
   """
   p = _project(args.world)
   doc = p.tileset(args.tileset)
   with doc.edit("Transparent color"):
      tilesets.set_transparent(doc, args.sheet, None if args.color.lower() == "none" else args.color)
   ts, _, error = p.compiled_tileset(args.tileset)
   if ts is None:
      raise CommandError(error)
   p.save_all()
   print(f"sheet {args.sheet}: transparent {args.color.lower()}")


def cmd_tileset_render(args: argparse.Namespace) -> None:
   """!tileset render. @param args  parsed arguments
   @return None
   """
   p = _project(args.world)
   ts, preview, error = p.compiled_tileset(args.tileset)
   if ts is None:
      raise CommandError(error)
   if preview is None:
      raise CommandError("the tileset has no metatiles")
   n, cols = len(preview["metatiles"]), max(1, args.columns)
   rows = (n + cols - 1) // cols   # rounded up
   # Metatiles sit on a grid with a gap line between them and around the edge.
   step = METATILE_PIXELS + METATILE_GAP
   img = mapview.blank(cols * step + METATILE_GAP, rows * step + METATILE_GAP, TILESET_BACKGROUND)
   for i in range(n):
      mapview.draw_metatile(img, METATILE_GAP + (i % cols) * step, METATILE_GAP + (i // cols) * step, preview, i)
   if tilesets.is_fixed(p.tileset(args.tileset)):   # I2: its entries are drawn with the tilesets maps load with it
      print("drawn with " + ", ".join(p.companions(args.tileset)))
   _png(args.output, img, TILESET_RENDER_SCALE)
   print(f"wrote {args.output} ({n} metatiles)")
