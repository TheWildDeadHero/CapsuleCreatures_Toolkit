"""!`capsule-studio sprite ...`: frame animations from bitmaps."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core import imaging, sprites
from .common import RGB_BYTES_PER_PIXEL, open_doc, parse_rgb, parse_rows, parse_size, read_image, write_rgb_png
from .main import CommandError

if TYPE_CHECKING:
   from ..core.document import Document

## Left shift taking a 5-bit color channel to the top of 8 bits.
CHANNEL_5_TO_8_SHIFT = 3
## Right shift repeating a 5-bit channel's top bits in the low 3 bits of 8 (so 31 becomes 255).
CHANNEL_5_LOW_BITS_SHIFT = 2
## Side of a square of the transparency checkerboard, in output pixels.
CHECKER_SQUARE = 4
## Gray level of the checkerboard's light squares.
CHECKER_LIGHT = 160
## Gray level of the checkerboard's dark squares.
CHECKER_DARK = 110


## Imported sprite step mirroring words and their flips values (asset::kFlipH 1, kFlipV 2).
FLIP_WORDS = {"none": 0, "h": 1, "v": 2, "hv": 3}
## How `show` names a flips value.
FLIP_NAMES = ("none", "horizontally", "vertically", "both ways")

def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("sprite", help="sprite frames, durations and animations")
   s = p.add_subparsers(dest="sprite_command", metavar="ACTION")
   s.required = True

   q = s.add_parser("new", help="add an empty sprite")
   q.add_argument("manifest")
   q.add_argument("key", help='e.g. "sprite:HERO WALK"')
   q.add_argument("--size", default="32x32", help="OBJ size, e.g. 32x32 (default)")
   q.set_defaults(run=cmd_new)

   q = s.add_parser("import", help="add PNG frames, one step each")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("images", nargs="+", help="PNG files, in order")
   q.add_argument("--create", metavar="SIZE", help="create the sprite first; SIZE like 32x32, or 'auto' for "
                                                   "the smallest OBJ size the first image fits")
   q.add_argument("--duration", type=int, default=sprites.DEFAULT_DURATION, help="display frames per step")
   q.add_argument("--fit", choices=imaging.FIT_MODES, default="center", help="how other sizes are fitted")
   q.add_argument("--transparent", default="alpha", metavar="MODE",
                  help="'alpha' (default), 'corner' (top-left pixel's color) or a color like #ff00ff")
   q.add_argument("--anim", type=int, default=0, help="animation index")
   q.add_argument("--at", type=int, help="insert before this step (default: append)")
   q.set_defaults(run=cmd_import)

   q = s.add_parser("duration", help="set step durations")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("frames", type=int, help="display frames, 1-255")
   q.add_argument("--steps", default="all", help='steps like "0,2-4" (default: all)')
   q.add_argument("--anim", type=int, default=0)
   q.set_defaults(run=cmd_duration)

   q = s.add_parser("loop", help="make an animation loop or hold its last step")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("mode", choices=["on", "off"])
   q.add_argument("--anim", type=int, default=0)
   q.set_defaults(run=cmd_loop)

   q = s.add_parser("remove", help="remove steps (frames no longer shown are dropped)")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("steps", help='steps like "0,2-4"')
   q.add_argument("--anim", type=int, default=0)
   q.set_defaults(run=cmd_remove)

   q = s.add_parser("show", help="list frames and steps")
   q.add_argument("manifest")
   q.add_argument("key")
   q.set_defaults(run=cmd_show)

   q = s.add_parser("sheet", help="write the frames as the GBA will show them, side by side, to a PNG")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("output")
   q.add_argument("--scale", type=int, default=1)
   q.set_defaults(run=cmd_sheet)
   # Mirrored steps, streamed sprites, step tables, indexed sheet frames
   q = s.add_parser("flips", help="mirror steps: none, h, v or hv")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("value", choices=list(FLIP_WORDS))
   q.add_argument("--steps", default="all", help='steps like "0,2-4" (default: all)')
   q.add_argument("--anim", type=int, default=0)
   q.set_defaults(run=cmd_flips)
   q = s.add_parser("stream", help="keep only the shown frame in VRAM, on or off")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("mode", choices=["on", "off"])
   q.set_defaults(run=cmd_stream)
   q = s.add_parser("step-table", help="the walk animations' step table: FIRST_STAND SECOND_STAND "
                                       "AFTER_SECOND AFTER_FIRST, or - to remove it")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("entries", nargs="+")
   q.set_defaults(run=cmd_step_table)
   q = s.add_parser("sheet-frames", help="add every frame of an indexed sheet, its palette indices as they are")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("image", help="a palette PNG of frames of the sprite's size (copied next to the manifest)")
   q.add_argument("--anim", type=int, default=0)
   q.add_argument("--duration", type=int, default=sprites.DEFAULT_DURATION)
   q.set_defaults(run=cmd_sheet_frames)
   from . import grid_cmds   # doors and overrides direction grids: `sprite grid MANIFEST KEY ...`
   grid_cmds.register(s)


def _sprite(doc: Document, key: str) -> dict[str, Any]:
   """!A sprite asset, which must exist.
   @param doc  Document
   @param key  asset key
   @return the asset
   """
   a = doc.get(key)
   if a.get("kind") != "sprite":
      raise CommandError(f"{key!r} is a {a.get('kind')}, not a sprite")
   return a


def cmd_new(args: argparse.Namespace) -> None:
   """!sprite new. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   w, h = parse_size(args.size)
   with doc.edit("New sprite"):
      sprites.new_sprite(doc, args.key, w, h)
   doc.save()
   print(f"added {args.key} ({w}x{h})")


def cmd_import(args: argparse.Namespace) -> int | None:
   """!sprite import.
   @param args  parsed arguments
   @return 1 when the sprite no longer compiles, otherwise None
   """
   doc = open_doc(args.manifest)
   raw = [read_image(p) for p in args.images]
   if args.transparent in ("alpha", "corner"):
      mode, color = args.transparent, None
   else:
      mode, color = "color", parse_rgb(args.transparent)
   with doc.edit("Import frames"):
      if args.create:
         first_w, first_h, _rgba = raw[0]
         w, h = sprites.smallest_size(first_w, first_h) if args.create == "auto" else parse_size(args.create)
         sprites.new_sprite(doc, args.key, w, h)
      a = _sprite(doc, args.key)
      imgs = [imaging.prepare(img, a["width"], a["height"], args.fit, mode, color) for img in raw]
      rows = sprites.add_images(doc, args.key, imgs, args.anim, args.at, args.duration,
                                names=[Path(p).stem for p in args.images])
   report = doc.compile_asset(doc.get(args.key))
   doc.save()
   print(f"{args.key}: added steps {rows[0]}-{rows[-1]}" if rows else f"{args.key}: nothing added")
   if not report.ok:
      print(f"warning: {report.error}")
      return 1
   used, limit = sprites.tile_budget(doc.get(args.key))
   print(f"{used}/{limit} tiles")


def cmd_duration(args: argparse.Namespace) -> None:
   """!sprite duration. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   a = _sprite(doc, args.key)
   rows = parse_rows(args.steps, len(sprites.steps(a, args.anim)))
   with doc.edit("Set duration"):
      sprites.set_durations(doc, args.key, rows, args.frames, args.anim)
   doc.save()
   print(f"{len(rows)} steps: {args.frames} frames ({sprites.frames_to_ms(args.frames)} ms)")


def cmd_loop(args: argparse.Namespace) -> None:
   """!sprite loop. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _sprite(doc, args.key)
   with doc.edit("Loop"):
      sprites.set_loop(doc, args.key, args.mode == "on", args.anim)
   doc.save()


def cmd_remove(args: argparse.Namespace) -> None:
   """!sprite remove. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   a = _sprite(doc, args.key)
   rows = parse_rows(args.steps, len(sprites.steps(a, args.anim)))
   with doc.edit("Remove steps"):
      sprites.remove_steps(doc, args.key, rows, args.anim)
   doc.save()


def cmd_show(args: argparse.Namespace) -> int | None:
   """!sprite show.
   @param args  parsed arguments
   @return 1 when the sprite does not compile, otherwise None
   """
   doc = open_doc(args.manifest)
   a = _sprite(doc, args.key)
   used, limit = sprites.tile_budget(a)
   print(f"{args.key}: {a.get('width')}x{a.get('height')}, {len(a.get('frames', []))} frames, "
         f"{used}/{limit} tiles")
   for i, f in enumerate(a.get("frames", [])):
      print(f"  frame {i}: {f.get('image', 'shapes')}")
   for n, an in enumerate(a.get("animations", [])):
      st = sprites.steps(a, n)
      loop = "loops" if an.get("loop", True) else "holds"
      print(f"  animation {n} ({loop}, {sprites.total_duration(a, n)} frames, "
            f"{sprites.frames_to_ms(sprites.total_duration(a, n))} ms):")
      mirrored = sprites.flips(a, n)
      for i, (f, d) in enumerate(st):
         flip = f", mirrored {FLIP_NAMES[mirrored[i]]}" if i < len(mirrored) and mirrored[i] else ""
         print(f"    step {i}: frame {f}, {d} frames ({sprites.frames_to_ms(d)} ms){flip}")
   if a.get("stream") is True:
      print("  streamed: only the shown frame is in VRAM")
   if sprites.step_table(a) is not None:
      print(f"  step table: {', '.join(str(v) for v in sprites.step_table(a))}")
   r = doc.compile_asset(a)
   if not r.ok:
      print(f"  error: {r.error}")
      return 1


def _saved(doc: Document, key: str) -> int | None:
   """!Saves the manifest and reports whether the sprite compiles.
   @param doc  Document
   @param key  sprite key
   @return 1 when it does not compile, otherwise None
   """
   report = doc.compile_asset(doc.get(key))
   doc.save()
   if not report.ok:
      print(f"warning: {report.error}")
      return 1
   return None


def cmd_flips(args: argparse.Namespace) -> int | None:
   """!sprite flips. @param args  parsed arguments
   @return 1 when the sprite no longer compiles, otherwise None
   """
   doc = open_doc(args.manifest)
   a = _sprite(doc, args.key)
   rows = parse_rows(args.steps, len(sprites.steps(a, args.anim)))
   with doc.edit("Mirror steps"):
      sprites.set_flips(doc, args.key, rows, FLIP_WORDS[args.value], args.anim)
   print(f"{len(rows)} steps mirrored {FLIP_NAMES[FLIP_WORDS[args.value]]}")
   return _saved(doc, args.key)


def cmd_stream(args: argparse.Namespace) -> int | None:
   """!sprite stream. @param args  parsed arguments
   @return 1 when the sprite no longer compiles, otherwise None
   """
   doc = open_doc(args.manifest)
   _sprite(doc, args.key)
   with doc.edit("Stream"):
      sprites.set_stream(doc, args.key, args.mode == "on")
   used, limit = sprites.tile_budget(doc.get(args.key))
   print(f"{args.key}: {'streamed' if args.mode == 'on' else 'all frames in VRAM'}, {used}/{limit} tiles")
   return _saved(doc, args.key)


def cmd_step_table(args: argparse.Namespace) -> int | None:
   """!sprite step-table. @param args  parsed arguments
   @return 1 when the sprite no longer compiles, otherwise None
   """
   doc = open_doc(args.manifest)
   _sprite(doc, args.key)
   if args.entries == ["-"]:
      table = None
   else:
      try:
         table = [int(v) for v in args.entries]
      except ValueError:
         raise CommandError(f"a step table is four numbers, got {' '.join(args.entries)}") from None
   with doc.edit("Step table"):
      try:
         sprites.set_step_table(doc, args.key, table)
      except ValueError as e:
         raise CommandError(str(e))
   print(f"{args.key}: step table {', '.join(str(v) for v in table) if table else 'none'}")
   return _saved(doc, args.key)


def cmd_sheet_frames(args: argparse.Namespace) -> int | None:
   """!sprite sheet-frames. @param args  parsed arguments
   @return 1 when the sprite no longer compiles, otherwise None
   """
   doc = open_doc(args.manifest)
   _sprite(doc, args.key)
   with doc.edit("Indexed sheet"):
      try:
         rows = sprites.add_sheet_frames(doc, args.key, args.image, args.anim, args.duration)
      except ValueError as e:
         raise CommandError(str(e))
   print(f"{args.key}: added steps {rows[0]}-{rows[-1]}" if rows else f"{args.key}: nothing added")
   return _saved(doc, args.key)


def cmd_sheet(args: argparse.Namespace) -> None:
   """!sprite sheet. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   a = _sprite(doc, args.key)
   r = doc.compile_asset(a)
   if not r.ok:
      raise CommandError(r.error)
   pal = sprites.palette_rgb(r.compiled)
   w, h, n, k = a["width"], a["height"], len(a["frames"]), max(1, args.scale)
   sw, sh = w * n * k, h * k
   rgb = bytearray(sw * sh * RGB_BYTES_PER_PIXEL)
   for f in range(n):
      _, _, idx = sprites.frame_pixels(r.compiled, f)
      for y in range(sh):
         for x in range(w * k):
            v = idx[(y // k) * w + x // k]
            # Frame f is drawn f frame widths to the right.
            o = (y * sw + f * w * k + x) * RGB_BYTES_PER_PIXEL
            if v:
               # Palette entry v is pal[v - 1] (entry 0 is transparent); 5-bit channels widen to 8 bits.
               rgb[o:o + RGB_BYTES_PER_PIXEL] = bytes(((c << CHANNEL_5_TO_8_SHIFT) | (c >> CHANNEL_5_LOW_BITS_SHIFT))
                                                      for c in pal[v - 1])
            else:   # transparent: checkerboard
               g = CHECKER_LIGHT if ((x // CHECKER_SQUARE + y // CHECKER_SQUARE) & 1) else CHECKER_DARK
               rgb[o:o + RGB_BYTES_PER_PIXEL] = bytes((g, g, g))
   write_rgb_png(args.output, sw, sh, rgb)
   print(f"wrote {args.output} ({n} frames)")
