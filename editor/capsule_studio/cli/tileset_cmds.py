"""!`capsule-studio tileset WORLD TILESET ...` for the imported maps / imported sprite tileset format (registered by
world_cmds): a fixed tileset's placement, palette banks, raw metatile entries and indexed sheets, and the tile
animations of any tileset (phase, from_sheet, on_shift; targets at frame offsets). Every change runs through
core.world.Project.edit_tileset(), so maps with an "all" dictionary follow a change of the metatile order, and is
compiled with the engine before anything is saved."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core import tilesets
from ..core.document import DocumentError
from ..core.world import Project
from .main import CommandError

if TYPE_CHECKING:
   from ..core.document import Document

## The word that removes an optional animation field (phase: back to the compiler's spread).
REMOVE = "-"
## Words for true and false.
BOOLS = {"on": True, "yes": True, "true": True, "off": False, "no": False, "false": False}


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the tileset actions of this module to `tileset`'s subparsers.
   @param s  the tileset group's subparsers
   @return None
   """
   q = s.add_parser("place", help="show or set a fixed tileset's placement (a tileset without one becomes fixed)")
   for opt in tilesets.PLACE_KEYS:
      q.add_argument(f"--{opt}", type=str if opt == "sheet" else int)
   q.set_defaults(run=cmd_place)
   q = s.add_parser("indexed-sheet", help="add an indexed sheet: a palette PNG used as its indices")
   q.add_argument("image")
   q.add_argument("--name", help="sheet name (default: the file name)")
   q.set_defaults(run=cmd_indexed_sheet)
   q = s.add_parser("bank", help="set one color of a fixed tileset's palette bank (banks up to it are added)")
   q.add_argument("bank", type=int, help="the tileset's bank, 0 up (VRAM bank: the placement's palette + it)")
   q.add_argument("entry", type=int, help="0-15")
   q.add_argument("color", help='like "#208020"')
   q.set_defaults(run=cmd_bank)
   q = s.add_parser("bank-remove", help="remove a fixed tileset's last palette bank")
   q.set_defaults(run=cmd_bank_remove)
   q = s.add_parser("metatile-add", help="add a fixed tileset's metatile of four raw tilemap entries")
   q.add_argument("name")
   q.add_argument("--entries", nargs=tilesets.TILES_PER_METATILE, type=lambda t: int(t, 0), metavar="ENTRY",
                  help="top-left top-right bottom-left bottom-right (numbers; 0x... too)")
   q.set_defaults(run=cmd_metatile_add)
   q = s.add_parser("entry", help="set one raw entry of a fixed tileset's metatile")
   q.add_argument("metatile")
   q.add_argument("slot", type=int, help="0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right")
   q.add_argument("tile", type=int, help="VRAM tile")
   q.add_argument("--bank", type=int, default=0)
   q.add_argument("--hflip", action="store_true")
   q.add_argument("--vflip", action="store_true")
   q.set_defaults(run=cmd_entry)
   q = s.add_parser("metatile-remove", help="remove a metatile (maps with an \"all\" dictionary are renumbered)")
   q.add_argument("metatile")
   q.set_defaults(run=cmd_metatile_remove)
   q = s.add_parser("animations", help="list the tileset's tile animations")
   q.set_defaults(run=cmd_animations)
   for name, helptext in (("animation-add", "add a tile animation"),
                          ("animation-set", "change a tile animation (- removes a field: its default)")):
      q = s.add_parser(name, help=helptext)
      if name == "animation-add":
         q.add_argument("name")
         q.add_argument("frames", help="the frame sheet")
      else:
         q.add_argument("index", type=int)
         q.add_argument("--name")
         q.add_argument("--frames")
      q.add_argument("--tiles", help='first tile, "sheet:index" (a tileset that is not fixed)')
      q.add_argument("--at", help="first tile counted from the placement's (a fixed tileset)")
      q.add_argument("--count", help="tiles replaced")
      q.add_argument("--period", help="display frames per frame")
      q.add_argument("--phase", help="frames into the period at map entry (- lets the compiler spread it)")
      q.add_argument("--from-sheet", dest="from_sheet", help="on: no frame at entry")
      q.add_argument("--on-shift", dest="on_shift", help="keep, reload or restart")
      q.set_defaults(run=cmd_animation_add if name == "animation-add" else cmd_animation_set)
   q = s.add_parser("animation-remove", help="remove a tile animation")
   q.add_argument("index", type=int)
   q.set_defaults(run=cmd_animation_remove)
   # One animation's frames on several targets at frame offsets
   q = s.add_parser("targets", help="list an animation's targets (tile, offset, phase) and the ROM they save")
   q.add_argument("index", type=int)
   q.add_argument("--at-frame", dest="at_frame", type=int, help="also say which frame each target shows on this "
                                                                 "display frame")
   q.set_defaults(run=cmd_targets)
   q = s.add_parser("target-add", help="add a target: the same frames on other tiles, from a frame offset")
   q.add_argument("index", type=int)
   q.add_argument("first", help='its first tile: "sheet:index", or a fixed tileset\'s tile of the placement')
   q.add_argument("--offset", type=int, default=0, help="the frame it shows while target 0 shows frame 0")
   q.add_argument("--phase", type=int, help="frames into the period at map entry (default: the animation's)")
   q.set_defaults(run=cmd_target_add)
   q = s.add_parser("target-set", help="change a target's tile, offset or phase (- removes the phase)")
   q.add_argument("index", type=int)
   q.add_argument("target", type=int)
   q.add_argument("--first", help="its first tile")
   q.add_argument("--offset", type=int)
   q.add_argument("--phase")
   q.set_defaults(run=cmd_target_set)
   q = s.add_parser("target-remove", help="remove a target (the last one at offset 0: the one-target form)")
   q.add_argument("index", type=int)
   q.add_argument("target", type=int)
   q.set_defaults(run=cmd_target_remove)


def _change(args: argparse.Namespace, label: str, fn: Any) -> Project:
   """!Runs a change of the tileset (one step; "all" maps follow), compiles the world and saves.
   @param args   parsed arguments (world, tileset)
   @param label  undo label
   @param fn     callable(tileset Document)
   @return the Project
   """
   p = Project.open(args.world)
   if args.tileset not in p.tileset_names():
      raise CommandError(f"the world has no tileset {args.tileset!r}")
   try:
      p.edit_tileset(args.tileset, label, fn)
   except (ValueError, DocumentError, OSError) as e:
      raise CommandError(str(e))
   error = p.validate()
   if error:
      raise CommandError(error)
   p.save_all()
   return p


def _number(opt: str, raw: str | None) -> int | None:
   """!A whole number option (None when not given).
   @param opt  option name
   @param raw  the text
   @return the number, or None
   """
   if raw is None:
      return None
   try:
      return int(raw, 0)
   except ValueError:
      raise CommandError(f"{opt} needs a number, got {raw!r}") from None


def cmd_place(args: argparse.Namespace) -> None:
   """!tileset place. @param args  parsed arguments
   @return None
   """
   fields = {k: getattr(args, k) for k in tilesets.PLACE_KEYS if getattr(args, k) is not None}
   if fields:
      p = _change(args, "Placement", lambda doc: tilesets.set_place(doc, **fields))
   else:
      p = Project.open(args.world)
   pl = tilesets.place_of(p.tileset(args.tileset))
   print("not fixed" if pl is None else ", ".join(f"{k} {pl.get(k)}" for k in tilesets.PLACE_KEYS))


def cmd_indexed_sheet(args: argparse.Namespace) -> None:
   """!tileset indexed-sheet. @param args  parsed arguments
   @return None
   """
   out = []
   _change(args, "Import indexed sheet", lambda doc: out.append(tilesets.add_indexed_sheet(
      doc, args.name or Path(args.image).stem, args.image)))
   print(f"sheet {out[0]}")


def cmd_bank(args: argparse.Namespace) -> None:
   """!tileset bank. @param args  parsed arguments
   @return None
   """
   _change(args, "Bank color", lambda doc: tilesets.set_bank_color(doc, args.bank, args.entry, args.color))
   print(f"bank {args.bank} entry {args.entry}: {args.color.lower()}")


def cmd_bank_remove(args: argparse.Namespace) -> None:
   """!tileset bank-remove. @param args  parsed arguments
   @return None
   """
   p = _change(args, "Remove bank", lambda doc: tilesets.remove_last_bank(doc))
   print(f"{len(tilesets.bank_colors(p.tileset(args.tileset)))} bank(s) listed")


def cmd_metatile_add(args: argparse.Namespace) -> None:
   """!tileset metatile-add. @param args  parsed arguments
   @return None
   """
   out = []
   _change(args, "New metatile", lambda doc: out.append(tilesets.add_fixed_metatile(doc, args.name, args.entries)))
   print(f"metatile {out[0]}")


def cmd_entry(args: argparse.Namespace) -> None:
   """!tileset entry. @param args  parsed arguments
   @return None
   """
   entry = tilesets.make_entry(args.tile, args.hflip, args.vflip, args.bank)
   _change(args, "Set entry", lambda doc: tilesets.set_entry(doc, args.metatile, args.slot, entry))
   print(f"{args.metatile} slot {args.slot}: entry 0x{entry:04X}")


def cmd_metatile_remove(args: argparse.Namespace) -> None:
   """!tileset metatile-remove. @param args  parsed arguments
   @return None
   """
   _change(args, "Delete metatile", lambda doc: tilesets.remove_metatile(doc, args.metatile))
   print(f"removed {args.metatile}")


def _describe(doc: Document, i: int, an: dict[str, Any]) -> str:
   """!One animation as text.
   @param doc  tileset Document
   @param i    its index
   @param an   the animation
   @return text
   """
   first = f"at {an.get('at', 0)}" if tilesets.is_fixed(doc) else f"tiles {an.get('tiles')}"
   phase = an.get("phase", "auto")
   extra = (", from sheet" if an.get("from_sheet") else "") + \
      (f", on shift {an['on_shift']}" if an.get("on_shift") else "")
   if tilesets.targets(an):   # the tiles are its targets
      first = f"{len(tilesets.targets(an))} targets"
   return (f"{i} {an.get('name', '?')}: {first}, {an.get('count', 1)} tile(s), frames {an.get('frames')}, "
           f"period {an.get('period', tilesets._mc().DEFAULT_ANIMATION_PERIOD)}, phase {phase}{extra}")


def cmd_animations(args: argparse.Namespace) -> None:
   """!tileset animations. @param args  parsed arguments
   @return None
   """
   doc = Project.open(args.world).tileset(args.tileset)
   items = tilesets.animations(doc)
   if not items:
      print("no animations")
   for i, an in enumerate(items):
      print(_describe(doc, i, an))


def _fields(args: argparse.Namespace) -> dict[str, Any]:
   """!The animation fields given ("-" removes one: None).
   @param args  parsed arguments
   @return {key: value or None}
   """
   out: dict[str, Any] = {}
   for key in ("name", "frames", "tiles"):
      v = getattr(args, key, None)
      if v is not None:
         out[key] = None if v == REMOVE else v
   for key in ("at", "count", "period", "phase"):
      v = getattr(args, key)
      if v is not None:
         out[key] = None if v == REMOVE else _number(f"--{key}", v)
   if args.from_sheet is not None:
      if args.from_sheet not in BOOLS:
         raise CommandError(f"--from-sheet needs on or off, got {args.from_sheet!r}")
      out["from_sheet"] = BOOLS[args.from_sheet]
   if args.on_shift is not None:
      out["on_shift"] = None if args.on_shift == REMOVE else args.on_shift
   return out


def cmd_animation_add(args: argparse.Namespace) -> None:
   """!tileset animation-add. @param args  parsed arguments
   @return None
   """
   fields = {k: v for k, v in _fields(args).items() if v is not None}
   out = []
   p = _change(args, "Add animation", lambda doc: out.append(tilesets.add_animation(doc, args.name, args.frames,
                                                                                     **fields)))
   doc = p.tileset(args.tileset)
   print(_describe(doc, out[0], tilesets.animations(doc)[out[0]]))


def cmd_animation_set(args: argparse.Namespace) -> None:
   """!tileset animation-set. @param args  parsed arguments
   @return None
   """
   fields = _fields(args)
   if not fields:
      raise CommandError("give the fields to change (--phase, --on-shift, ...)")
   p = _change(args, "Animation", lambda doc: tilesets.set_animation(doc, args.index, **fields))
   doc = p.tileset(args.tileset)
   print(_describe(doc, args.index, tilesets.animations(doc)[args.index]))


def cmd_animation_remove(args: argparse.Namespace) -> None:
   """!tileset animation-remove. @param args  parsed arguments
   @return None
   """
   _change(args, "Remove animation", lambda doc: tilesets.remove_animation(doc, args.index))
   print(f"removed animation {args.index}")


def _first(doc: Document, raw: str) -> Any:
   """!A target's first tile from the command line: a number in a fixed tileset, else "sheet:index".
   @param doc  tileset Document
   @param raw  the text
   @return the value
   """
   return _number("first", raw) if tilesets.is_fixed(doc) else raw


def cmd_targets(args: argparse.Namespace) -> None:
   """!tileset targets. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   doc = p.tileset(args.tileset)
   items = tilesets.animations(doc)
   if not 0 <= args.index < len(items):
      raise CommandError(f"no animation {args.index}")
   an = items[args.index]
   ref = tilesets.target_ref_key(doc)
   rows = tilesets.targets(an) or [{ref: an.get(ref), "phase": an.get("phase")}]
   ts, error = p.compiled_tilesets([args.tileset])
   compiled = ts.get(args.tileset)
   frames = tilesets.target_frames(compiled, args.index, args.at_frame) if compiled and args.at_frame is not None \
      else []
   for k, tg in enumerate(rows):
      phase = tg.get("phase", an.get("phase"))
      shows = f", shows frame {frames[k]}" if k < len(frames) else ""
      print(f"target {k}: {ref} {tg.get(ref)}, offset {tg.get('offset', 0)}, phase "
            f"{'auto' if phase is None else phase}{shows}")
   if compiled is not None:
      print(f"frames stored once: the tileset's targets save {tilesets.target_saved(compiled)} bytes")
   elif error:
      print(f"error: {error}")


def cmd_target_add(args: argparse.Namespace) -> None:
   """!tileset target-add. @param args  parsed arguments
   @return None
   """
   def run(doc: Document) -> None:
      tilesets.add_target(doc, args.index, _first(doc, args.first), args.offset, args.phase)
   _change(args, "Add target", run)
   print(f"animation {args.index}: target added")


def cmd_target_set(args: argparse.Namespace) -> None:
   """!tileset target-set. @param args  parsed arguments
   @return None
   """
   def run(doc: Document) -> None:
      fields: dict[str, Any] = {}
      if args.first is not None:
         fields[tilesets.target_ref_key(doc)] = _first(doc, args.first)
      if args.offset is not None:
         fields["offset"] = args.offset
      if args.phase is not None:
         fields["phase"] = None if args.phase == REMOVE else _number("--phase", args.phase)
      if not fields:
         raise CommandError("give --first, --offset or --phase")
      tilesets.set_target(doc, args.index, args.target, **fields)
   _change(args, "Change target", run)
   print(f"animation {args.index}: target {args.target} changed")


def cmd_target_remove(args: argparse.Namespace) -> None:
   """!tileset target-remove. @param args  parsed arguments
   @return None
   """
   _change(args, "Remove target", lambda doc: tilesets.remove_target(doc, args.index, args.target))
   print(f"animation {args.index}: target {args.target} removed")
