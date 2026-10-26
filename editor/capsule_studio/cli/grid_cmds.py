"""![S3] `capsule-studio sprite grid MANIFEST KEY ...`: direction-grid sprite sheets (D-30 section 3; registered by
sprite_cmds): columns down / up / left (/ right), right mirroring left, named rows, animations by rows, the walk of
each direction and the ROM the grid saves. Each change is compiled with the engine before the manifest is saved."""
from __future__ import annotations

import argparse
from typing import Any

from ..core import engine, sprite_grid
from .common import open_doc, parse_size
from .main import CommandError

## Words for on and off.
SWITCH = {"on": True, "off": False}
## Separator of a list of names or numbers on the command line.
LIST_SEPARATOR = ","
## The word that removes an optional animation field.
REMOVE = "-"


def register(s: argparse._SubParsersAction) -> None:
   """!Adds `sprite grid` to the sprite group's subparsers.
   @param s  the sprite group's subparsers
   @return None
   """
   p = s.add_parser("grid", help="direction-grid sprites (D-30): columns down/up/left(/right), named rows (S3)")
   p.add_argument("manifest")
   p.add_argument("key")
   g = p.add_subparsers(dest="grid_command", metavar="ACTION")
   g.required = True
   q = g.add_parser("show", help="columns, rows, animations, frames stored and the ROM saved")
   q.set_defaults(run=cmd_show)
   q = g.add_parser("new", help="add a grid sprite of empty shape frames")
   q.add_argument("--size", default="16x32", help="frame size (an OBJ size, default 16x32)")
   q.add_argument("--rows", default=LIST_SEPARATOR.join(sprite_grid.NEW_ROWS), help="row names, comma separated")
   q.add_argument("--four", action="store_true", help="store a right column (default: right mirrors left)")
   q.set_defaults(run=cmd_new)
   q = g.add_parser("mirror", help="on: three columns, right is left mirrored; off: four (a sheet is rewritten)")
   q.add_argument("value", choices=tuple(SWITCH))
   q.set_defaults(run=cmd_mirror)
   q = g.add_parser("row", help="add / rename / remove / move a row (a sheet is rewritten)")
   q.add_argument("action", choices=("add", "rename", "remove", "up", "down"))
   q.add_argument("name")
   q.add_argument("other", nargs="?", help="rename: the new name; add: the row copied (default the last)")
   q.set_defaults(run=cmd_row)
   q = g.add_parser("anim-add", help="add an animation by rows")
   q.add_argument("rows", help="row names in order, comma separated")
   _timing(q)
   q.set_defaults(run=cmd_anim_add)
   q = g.add_parser("anim-set", help="change an animation (- removes direction / loop)")
   q.add_argument("index", type=int)
   q.add_argument("--rows", help="row names in order, comma separated")
   _timing(q)
   q.set_defaults(run=cmd_anim_set)
   q = g.add_parser("anim-remove", help="remove an animation")
   q.add_argument("index", type=int)
   q.set_defaults(run=cmd_anim_remove)
   q = g.add_parser("walk", help="what each direction shows, display frame by display frame")
   q.add_argument("index", type=int, help="grid animation")
   q.add_argument("--frames", type=int, default=0, help="display frames listed (default one pass)")
   q.set_defaults(run=cmd_walk)
   q = g.add_parser("sheet", help="write the grid as the GBA shows it (right column mirrored when not stored)")
   q.add_argument("out")
   q.set_defaults(run=cmd_sheet)


def _timing(q: argparse.ArgumentParser) -> None:
   """!The timing options of an animation.
   @param q  the parser
   @return None
   """
   q.add_argument("--period", type=int, help="display frames per row step")
   q.add_argument("--durations", help="display frames per row step, comma separated")
   q.add_argument("--loop", choices=("on", "off", REMOVE))
   q.add_argument("--direction", help="one direction only (- : all four)")


def _names(text: str) -> list[str]:
   """!Comma separated names.
   @param text  the text
   @return names
   """
   return [n.strip() for n in text.split(LIST_SEPARATOR) if n.strip()]


def _grid(doc: Any, key: str) -> dict[str, Any]:
   """!A grid sprite, which must exist.
   @param doc  Document
   @param key  its key
   @return the asset
   """
   a = doc.get(key)
   if not sprite_grid.is_grid(a):
      raise CommandError(f"{key!r} is not a direction-grid sprite")
   return a


def _done(doc: Any, key: str) -> None:
   """!Saves the manifest and prints the grid.
   @param doc  Document
   @param key  sprite key
   @return None
   """
   doc.save()
   print("\n".join(sprite_grid.lines(doc, key)))


def cmd_show(args: argparse.Namespace) -> None:
   """!sprite grid show. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _grid(doc, args.key)
   print("\n".join(sprite_grid.lines(doc, args.key)))


def cmd_new(args: argparse.Namespace) -> None:
   """!sprite grid new. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   w, h = parse_size(args.size)
   with doc.edit("New grid sprite"):
      sprite_grid.new_grid(doc, args.key, w, h, _names(args.rows), not args.four)
   _done(doc, args.key)


def cmd_mirror(args: argparse.Namespace) -> None:
   """!sprite grid mirror. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _grid(doc, args.key)
   with doc.edit("Right mirrors left"):
      lost = sprite_grid.set_right_mirrors_left(doc, args.key, SWITCH[args.value])
   if lost:
      print(f"note: {lost} right frame(s) differed from the left ones mirrored; they are gone")
   _done(doc, args.key)


def cmd_row(args: argparse.Namespace) -> None:
   """!sprite grid row. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _grid(doc, args.key)
   with doc.edit("Grid row"):
      if args.action == "add":
         sprite_grid.add_row(doc, args.key, args.name, args.other)
      elif args.action == "rename":
         if not args.other:
            raise CommandError("rename needs the new name")
         sprite_grid.rename_row(doc, args.key, args.name, args.other)
      elif args.action == "remove":
         sprite_grid.remove_row(doc, args.key, args.name)
      else:
         sprite_grid.move_row(doc, args.key, args.name, -1 if args.action == "up" else 1)
   _done(doc, args.key)


def _anim_fields(args: argparse.Namespace) -> dict[str, Any]:
   """!Animation fields given on the command line.
   @param args  parsed arguments
   @return {field: value or None (removed)}
   """
   out: dict[str, Any] = {}
   if getattr(args, "rows", None):
      out["rows"] = _names(args.rows)
   if args.period is not None:
      out["period"] = args.period
   if args.durations is not None:
      try:
         out["durations"] = [int(v) for v in _names(args.durations)]
      except ValueError:
         raise CommandError(f"--durations are numbers, got {args.durations!r}") from None
   if args.loop is not None:
      out["loop"] = None if args.loop == REMOVE else SWITCH[args.loop]
   if args.direction is not None:
      out["direction"] = None if args.direction == REMOVE else args.direction
   return out


def cmd_anim_add(args: argparse.Namespace) -> None:
   """!sprite grid anim-add. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _grid(doc, args.key)
   f = _anim_fields(args)
   with doc.edit("Grid animation"):
      sprite_grid.add_animation(doc, args.key, _names(args.rows), f.get("period", sprite_grid.NEW_PERIOD),
                                f.get("durations"), f.get("loop"), f.get("direction"))
   _done(doc, args.key)


def cmd_anim_set(args: argparse.Namespace) -> None:
   """!sprite grid anim-set. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _grid(doc, args.key)
   fields = _anim_fields(args)
   if not fields:
      raise CommandError("give --rows, --period, --durations, --loop or --direction")
   with doc.edit("Grid animation"):
      sprite_grid.set_animation(doc, args.key, args.index, **fields)
   _done(doc, args.key)


def cmd_anim_remove(args: argparse.Namespace) -> None:
   """!sprite grid anim-remove. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _grid(doc, args.key)
   with doc.edit("Remove grid animation"):
      sprite_grid.remove_animation(doc, args.key, args.index)
   _done(doc, args.key)


def cmd_walk(args: argparse.Namespace) -> None:
   """!sprite grid walk. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   a = _grid(doc, args.key)
   r = doc.compile_asset(a)
   if not r.ok:
      raise CommandError(r.error)
   for d in sprite_grid.directions():
      k = sprite_grid.compiled_index(a, args.index, d)
      if k is None:
         continue
      tl = sprite_grid.timeline(r.compiled, k)
      shown = tl if not args.frames else (tl * (args.frames // max(1, len(tl)) + 1))[:args.frames]
      steps = " ".join(f"{f}{'m' if flip else ''}" for f, flip in shown)
      print(f"{d}: {steps}   (frame numbers of the stored frames; m: mirrored)")


def cmd_sheet(args: argparse.Namespace) -> None:
   """!sprite grid sheet. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   a = _grid(doc, args.key)
   frames, error = sprite_grid.cell_frames(doc, args.key)
   if frames is None:
      raise CommandError(error)
   cols = sprite_grid.columns(a)
   names = sprite_grid.rows(a)
   fw, fh = a["width"], a["height"]
   across = len(sprite_grid.directions())
   from ..core.imaging import RGBA_BYTES
   out = bytearray(fw * across * fh * len(names) * RGBA_BYTES)
   for r in range(len(names)):
      for c in range(across):
         mirrored = c >= cols   # the right column of a three-column grid: the left one mirrored
         src = r * cols + (sprite_grid.mirrored_from() if mirrored else c)
         _w, _h, px = sprite_grid.frame_image(frames, src, mirrored)
         for y in range(fh):
            o = ((r * fh + y) * fw * across + c * fw) * RGBA_BYTES
            out[o:o + fw * RGBA_BYTES] = px[y * fw * RGBA_BYTES:(y + 1) * fw * RGBA_BYTES]
   engine.bitmap().write_png(args.out, fw * across, fh * len(names), out)
   print(f"wrote {args.out}: {len(names)} rows x {across} columns (down, up, left, right)")
