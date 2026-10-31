"""![S6] `capsule-studio screen-gfx MANIFEST ...` (the tiles / tilemap / palette asset kinds, engine UC), `screen-plan
...` (screen plans: layers, windows, sprites and transitions as data, previewed and exported as C++) and
`gba-memory BUILD ...` (a build folder's GBA memory settings and its programs' memory report, engine UM). Changes are
compiled or checked before anything is saved."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..core import engine, gba_memory, paths, screen_graphics as sg, screen_plans as sp
from ..core.document import Document
from .common import open_doc, parse_size
from .main import CommandError

## The word that removes an optional field (set) or clears a cache override (gba-memory set arena).
REMOVE = "-"
## Separator of FIELD=VALUE on the command line.
ASSIGN = "="
## Directions of `screen-plan move`.
MOVES = {"up": -1, "down": 1}


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command groups.
   @param sub  argparse subparsers
   @return None
   """
   _register_graphics(sub)
   _register_plans(sub)
   _register_memory(sub)


def _register_graphics(sub: argparse._SubParsersAction) -> None:
   """!`screen-gfx`.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("screen-gfx", help="screen graphics assets: tiles, tilemaps, palettes (UC) (S6)")
   p.add_argument("manifest", help="asset manifest (capsule.assets/1)")
   s = p.add_subparsers(dest="gfx_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("list", help="the manifest's tiles, tilemaps and palettes")
   q.set_defaults(run=cmd_gfx_list)
   q = s.add_parser("show", help="one asset (a palette's banks, a tilemap's rows)")
   q.add_argument("key")
   q.set_defaults(run=cmd_gfx_show)
   q = s.add_parser("new", help="a new asset: tiles (an empty shapes canvas), tilemap (tile 0 cells) or palette "
                                "(gray ramps)")
   q.add_argument("kind", choices=sg.KINDS)
   q.add_argument("name", help="NAME or KIND:NAME")
   q.add_argument("--size", default=None, help="tiles: WIDTHxHEIGHT pixels (default 32x8); tilemap: COLUMNSxROWS "
                                               "(default 32x32)")
   q.add_argument("--bpp", type=int, choices=(sg.BPP4, sg.BPP8), default=sg.BPP4)
   q.add_argument("--banks", type=int, default=1, help="palette banks")
   q.add_argument("--affine", action="store_true", help="tilemap: one tile byte a cell")
   q.set_defaults(run=cmd_gfx_new)
   q = s.add_parser("set", help="fields FIELD=VALUE (JSON values; - removes a field), e.g. bpp=8 block=[2,2]")
   q.add_argument("key")
   q.add_argument("fields", nargs="+")
   q.set_defaults(run=cmd_gfx_set)
   q = s.add_parser("color", help="one palette entry: INDEX #rrggbb or a BGR555 number")
   q.add_argument("key")
   q.add_argument("index", type=int)
   q.add_argument("value")
   q.set_defaults(run=cmd_gfx_color)
   q = s.add_parser("banks", help="a palette's bank count (new banks are gray ramps)")
   q.add_argument("key")
   q.add_argument("count", type=int)
   q.set_defaults(run=cmd_gfx_banks)
   q = s.add_parser("paint", help="write an entry into a cells tilemap: X Y ENTRY ('t3 p1 h' or a number)")
   q.add_argument("key")
   q.add_argument("x", type=int)
   q.add_argument("y", type=int)
   q.add_argument("entry")
   q.add_argument("--size", default="1x1", help="WIDTHxHEIGHT cells (default 1x1)")
   q.add_argument("--step", type=int, default=0, help="tile step per cell (a run of tiles)")
   q.set_defaults(run=cmd_gfx_paint)
   q = s.add_parser("rows", help="a cells tilemap's stored rows")
   q.add_argument("key")
   q.add_argument("count", type=int)
   q.set_defaults(run=cmd_gfx_rows)
   q = s.add_parser("to-cells", help="a tilemap read from a data file becomes cells in the manifest")
   q.add_argument("key")
   q.set_defaults(run=cmd_gfx_to_cells)
   q = s.add_parser("import", help="an indexed PNG to tiles (a data file beside the manifest), a tilemap and a "
                                   "palette")
   q.add_argument("name")
   q.add_argument("image")
   q.add_argument("--bpp", type=int, choices=(sg.BPP4, sg.BPP8), default=sg.BPP4)
   q.add_argument("--no-map", dest="make_map", action="store_false", help="tiles only, in reading order")
   q.add_argument("--no-palette", dest="make_palette", action="store_false")
   q.add_argument("--no-dedupe", dest="dedupe", action="store_false", help="keep identical tiles")
   q.add_argument("--no-flips", dest="flips", action="store_false", help="share only unflipped copies")
   q.set_defaults(run=cmd_gfx_import)
   q = s.add_parser("export", help="a tiles asset as an indexed PNG")
   q.add_argument("key")
   q.add_argument("out")
   q.add_argument("--palette", help="palette key (default: a gray ramp)")
   q.add_argument("--bank", type=int, default=0)
   q.set_defaults(run=cmd_gfx_export)
   q = s.add_parser("render", help="a picture of an asset (tiles in a palette's bank, a tilemap with its tiles, "
                                   "a palette's swatches)")
   q.add_argument("key")
   q.add_argument("out")
   q.add_argument("--palette", help="palette key")
   q.add_argument("--bank", type=int, default=0)
   q.add_argument("--tiles", help="tilemap: the tiles key it is drawn with")
   q.add_argument("--first-tile", dest="first_tile", type=int, default=0, help="tilemap: the tiles' first number")
   q.set_defaults(run=cmd_gfx_render)


def _register_plans(sub: argparse._SubParsersAction) -> None:
   """!`screen-plan`.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("screen-plan", help="screen plans: layers, windows, sprites, transitions (UC) (S6)")
   s = p.add_subparsers(dest="plan_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("list", help="the plans of an asset manifest")
   q.add_argument("manifest")
   q.set_defaults(run=cmd_plan_list)
   q = s.add_parser("new", help="a new plan in the manifest's screens/ folder")
   q.add_argument("manifest")
   q.add_argument("name", help="snake_case (the export's namespace)")
   q.set_defaults(run=cmd_plan_new)
   q = s.add_parser("fields", help="the fields of a section's items")
   q.add_argument("section", choices=sp.SECTIONS)
   q.set_defaults(run=cmd_plan_fields)
   for name, help_text, run in (("show", "the plan", cmd_plan_show), ("check", "what would go wrong on the GBA",
                                                                      cmd_plan_check),
                                ("vram", "background and sprite memory as the plan uses it", cmd_plan_vram)):
      q = s.add_parser(name, help=help_text)
      q.add_argument("plan")
      q.add_argument("--later", action="store_true", help="with the templates applied later (layers::init())")
      q.set_defaults(run=run)
   q = s.add_parser("add", help="an item: SECTION FIELD=VALUE ...")
   q.add_argument("plan")
   q.add_argument("section", choices=sp.SECTIONS)
   q.add_argument("fields", nargs="*")
   q.set_defaults(run=cmd_plan_add)
   q = s.add_parser("set", help="an item's fields: SECTION INDEX FIELD=VALUE ...")
   q.add_argument("plan")
   q.add_argument("section", choices=sp.SECTIONS)
   q.add_argument("index", type=int)
   q.add_argument("fields", nargs="+")
   q.set_defaults(run=cmd_plan_set)
   q = s.add_parser("remove", help="an item")
   q.add_argument("plan")
   q.add_argument("section", choices=sp.SECTIONS)
   q.add_argument("index", type=int)
   q.set_defaults(run=cmd_plan_remove)
   q = s.add_parser("move", help="an item up or down its list (load and creation order)")
   q.add_argument("plan")
   q.add_argument("section", choices=sp.SECTIONS)
   q.add_argument("index", type=int)
   q.add_argument("direction", choices=tuple(MOVES))
   q.set_defaults(run=cmd_plan_move)
   q = s.add_parser("mode", help="the display mode 0-2")
   q.add_argument("plan")
   q.add_argument("mode", type=int)
   q.set_defaults(run=cmd_plan_mode)
   q = s.add_parser("steps", help="the frame order (screen::Step words: tasks, build_oam ...)")
   q.add_argument("plan")
   q.add_argument("steps", nargs="*")
   q.set_defaults(run=cmd_plan_steps)
   q = s.add_parser("transition", help="open / in / out: a preset (" + ", ".join(sp.PRESETS) + ") or a fade "
                                       "object as JSON")
   q.add_argument("plan")
   q.add_argument("which", choices=sp.TRANSITIONS)
   q.add_argument("value")
   q.set_defaults(run=cmd_plan_transition)
   q = s.add_parser("fade-style", help="the fade style as JSON (step, finish_calls, alternate, rounding), or - for "
                                       "the engine's kHandheldFade")
   q.add_argument("plan")
   q.add_argument("value")
   q.set_defaults(run=cmd_plan_fade_style)
   q = s.add_parser("exit", help="how the screen leaves: close, close_now, replace NEXT or replace_now NEXT (engine "
                                 "C13a), and its frames; no CALL: show them")
   q.add_argument("plan")
   q.add_argument("call", nargs="?", choices=sp.EXIT_CALLS)
   q.add_argument("next", nargs="?", default="", help="replace / replace_now: the next screen's plan name")
   q.set_defaults(run=cmd_plan_exit)
   q = s.add_parser("frames", help="a transition call by call: the BG and OBJ blend amounts")
   q.add_argument("plan")
   q.add_argument("which", choices=sp.TRANSITIONS)
   q.set_defaults(run=cmd_plan_frames)
   q = s.add_parser("render", help="the screen as the GBA shows it, to a PNG")
   q.add_argument("plan")
   q.add_argument("out")
   q.add_argument("--later", action="store_true")
   q.add_argument("--guides", action="store_true", help="window outlines and sprite boxes")
   q.add_argument("--transition", choices=sp.TRANSITIONS, help="at a call of this transition")
   q.add_argument("--call", type=int, default=0, help="the transition's call (0 = its first)")
   q.set_defaults(run=cmd_plan_render)
   q = s.add_parser("export", help="the plan's C++ tables as a header")
   q.add_argument("plan")
   q.add_argument("out", help="NAME.h")
   q.set_defaults(run=cmd_plan_export)


def _register_memory(sub: argparse._SubParsersAction) -> None:
   """!`gba-memory`.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("gba-memory", help="a build folder's GBA memory checks, stack reserve and memory report (UM) "
                                         "(S6)")
   p.add_argument("build", help="a configured build folder (its CMakeCache.txt)")
   s = p.add_subparsers(dest="memory_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("show", help="the settings")
   q.set_defaults(run=cmd_mem_show)
   q = s.add_parser("set", help="checks on|off, reserve BYTES, arena BYTES|- (CMake reads them at the next build)")
   q.add_argument("setting", choices=("checks", "reserve", "arena"))
   q.add_argument("value")
   q.set_defaults(run=cmd_mem_set)
   q = s.add_parser("report", help="each GBA program's memory use (read with nm), or a build log's report lines")
   q.add_argument("--log", help="a build's output to read instead")
   q.add_argument("--arena", type=int, help="the screen arena's bytes, to say its share")
   q.set_defaults(run=cmd_mem_report)


def _value(text: str) -> Any:
   """!A command-line value: JSON when it parses, else the text.
   @param text  the text
   @return the value
   """
   try:
      return json.loads(text)
   except ValueError:
      return text


def _assignments(items: list[str]) -> dict[str, str]:
   """!FIELD=VALUE words.
   @param items  the words
   @return {field: value text}
   """
   out = {}
   for it in items:
      k, sep, v = it.partition(ASSIGN)
      if not sep or not k:
         raise CommandError(f"fields look like FIELD{ASSIGN}VALUE, got {it!r}")
      out[k] = v
   return out


def _graphic(doc: Document, key: str) -> None:
   """!Refuses a key that is not a screen graphics asset.
   @param doc  Document
   @param key  its key
   @return None
   """
   a = doc.get(key)
   if a.get("kind") not in sg.KINDS:
      raise CommandError(f"{key!r} is a {a.get('kind')}, not tiles, a tilemap or a palette")


def _save_gfx(doc: Document, key: str | None) -> None:
   """!Saves the manifest; prints the asset.
   @param doc  Document
   @param key  asset key, or None
   @return None
   """
   doc.save()
   if key is not None:
      print("\n".join(sg.lines(doc, key)))


def cmd_gfx_list(args: argparse.Namespace) -> None:
   """!screen-gfx list. @param args  parsed arguments
   @return None
   """
   out = sg.lines(open_doc(args.manifest))
   print("\n".join(out) if out else "no tiles, tilemaps or palettes")


def cmd_gfx_show(args: argparse.Namespace) -> None:
   """!screen-gfx show. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _graphic(doc, args.key)
   print("\n".join(sg.lines(doc, args.key)))


def cmd_gfx_new(args: argparse.Namespace) -> None:
   """!screen-gfx new. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   name = args.name.split(":", 1)[-1]
   with doc.edit(f"New {args.kind}"):
      if args.kind == "tiles":
         w, h = parse_size(args.size) if args.size else sg.NEW_TILES_SIZE
         a = sg.new_tiles(doc, name, w, h, args.bpp)
      elif args.kind == "tilemap":
         cols, rows = parse_size(args.size) if args.size else (sg.ROW_CELLS, sg.NEW_MAP_ROWS)
         a = sg.new_tilemap(doc, name, rows, cols, args.affine)
      else:
         a = sg.new_palette(doc, name, args.banks)
   _save_gfx(doc, a["key"])


def cmd_gfx_set(args: argparse.Namespace) -> None:
   """!screen-gfx set. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _graphic(doc, args.key)
   fields = {k: (None if v == REMOVE else _value(v)) for k, v in _assignments(args.fields).items()}
   with doc.edit("Set fields"):
      sg.set_fields(doc, args.key, **fields)
   _save_gfx(doc, args.key)


def cmd_gfx_color(args: argparse.Namespace) -> None:
   """!screen-gfx color. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _graphic(doc, args.key)
   value = args.value if args.value.startswith("#") else int(args.value, 0)
   with doc.edit("Set colour"):
      sg.set_color(doc, args.key, args.index, value)
   _save_gfx(doc, args.key)


def cmd_gfx_banks(args: argparse.Namespace) -> None:
   """!screen-gfx banks. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _graphic(doc, args.key)
   with doc.edit("Palette banks"):
      sg.set_banks(doc, args.key, args.count)
   _save_gfx(doc, args.key)


def cmd_gfx_paint(args: argparse.Namespace) -> None:
   """!screen-gfx paint. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _graphic(doc, args.key)
   w, h = parse_size(args.size)
   entry = sg.parse_entry(args.entry, bool(doc.get(args.key).get("affine")))
   with doc.edit("Paint tilemap"):
      sg.paint(doc, args.key, args.x, args.y, entry, w, h, args.step)
   doc.save()
   print(f"{args.key}: {w * h} cell(s) from {args.x},{args.y} = {sg.entry_text(entry)}")


def cmd_gfx_rows(args: argparse.Namespace) -> None:
   """!screen-gfx rows. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _graphic(doc, args.key)
   with doc.edit("Tilemap rows"):
      sg.set_rows(doc, args.key, args.count)
   doc.save()
   print(sg.lines(doc)[[a["key"] for a in sg.graphics(doc)].index(args.key)])


def cmd_gfx_to_cells(args: argparse.Namespace) -> None:
   """!screen-gfx to-cells. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _graphic(doc, args.key)
   with doc.edit("Tilemap to cells"):
      sg.to_cells(doc, args.key)
   doc.save()
   print(sg.describe(doc, doc.get(args.key)))


def cmd_gfx_import(args: argparse.Namespace) -> None:
   """!screen-gfx import. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   with doc.edit("Import screen graphics"):
      added = sg.import_png(doc, args.name, args.image, args.bpp, args.make_map, args.make_palette, args.dedupe,
                            args.flips)
   doc.save()
   for key in added:
      print(sg.describe(doc, doc.get(key)))


def cmd_gfx_export(args: argparse.Namespace) -> None:
   """!screen-gfx export. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _graphic(doc, args.key)
   sg.export_png(doc, args.key, args.out, args.palette, args.bank)
   print(f"wrote {args.out}")


def cmd_gfx_render(args: argparse.Namespace) -> None:
   """!screen-gfx render. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   _graphic(doc, args.key)
   img = sg.preview(doc, args.key, args.palette, args.bank, args.tiles, args.first_tile)
   engine.bitmap().write_png(args.out, *img)
   print(f"wrote {args.out} ({img[0]}x{img[1]})")


# -- screen-plan -----------------------------------------------------------------------------------------------------


def _plan(path: str) -> tuple[Document, Document]:
   """!A plan and its manifest.
   @param path  the plan file
   @return (plan Document, manifest Document)
   """
   plan = sp.open_plan(path)
   manifest = sp.manifest_path(plan)
   if not manifest.is_file():
      raise CommandError(f"{Path(path).name} names {plan.data.get('assets')!r}, which is not there")
   return plan, Document.open(manifest)


def _save_plan(plan: Document, manifest: Document) -> None:
   """!Saves a plan; prints its problems.
   @param plan      plan Document
   @param manifest  its manifest
   @return None
   """
   plan.save()
   problems = sp.check(plan.data, manifest)
   print("\n".join(str(p) for p in problems) if problems else "no problems")


def cmd_plan_list(args: argparse.Namespace) -> None:
   """!screen-plan list. @param args  parsed arguments
   @return None
   """
   doc = open_doc(args.manifest)
   files = sp.plan_files(doc)
   print("\n".join(paths.shown(p, doc.base_dir) for p in files) if files else "no screen plans")


def cmd_plan_new(args: argparse.Namespace) -> None:
   """!screen-plan new. @param args  parsed arguments
   @return None
   """
   plan = sp.create(open_doc(args.manifest), args.name)
   print(f"wrote {plan.path}")


def cmd_plan_fields(args: argparse.Namespace) -> None:
   """!screen-plan fields. @param args  parsed arguments
   @return None
   """
   for f in sp.FIELDS[args.section]:
      what = f"{f.lo}-{f.hi}" if f.kind == sp.INT else ("|".join(sp.choices_of(f)) if f.kind == sp.CHOICE else
                                                        (f"{f.choices[0]} key" if f.kind == sp.ASSET else f.kind))
      print(f"{f.key:16s} {what:24s} default {f.default!r}: {f.help}")


def cmd_plan_show(args: argparse.Namespace) -> None:
   """!screen-plan show. @param args  parsed arguments
   @return None
   """
   plan, _m = _plan(args.plan)
   print("\n".join(sp.describe(plan.data)))


def cmd_plan_check(args: argparse.Namespace) -> int:
   """!screen-plan check. @param args  parsed arguments
   @return 1 when there are errors
   """
   plan, manifest = _plan(args.plan)
   problems = sp.check(plan.data, manifest, args.later)
   print("\n".join(str(p) for p in problems) if problems else "no problems")
   return 1 if any(p.severity == "error" for p in problems) else 0


def cmd_plan_vram(args: argparse.Namespace) -> None:
   """!screen-plan vram. @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   print("\n".join(sp.vram_lines(plan.data, manifest, args.later)))


def cmd_plan_add(args: argparse.Namespace) -> None:
   """!screen-plan add. @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   with plan.edit(f"Add {args.section}"):
      i = sp.add_item(plan, args.section, **_assignments(args.fields))
   print(f"{args.section} {i}")
   _save_plan(plan, manifest)


def cmd_plan_set(args: argparse.Namespace) -> None:
   """!screen-plan set. @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   with plan.edit(f"Set {args.section}"):
      sp.set_item(plan, args.section, args.index, **_assignments(args.fields))
   _save_plan(plan, manifest)


def cmd_plan_remove(args: argparse.Namespace) -> None:
   """!screen-plan remove. @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   with plan.edit(f"Remove {args.section}"):
      sp.remove_item(plan, args.section, args.index)
   _save_plan(plan, manifest)


def cmd_plan_move(args: argparse.Namespace) -> None:
   """!screen-plan move. @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   with plan.edit(f"Move {args.section}"):
      i = sp.move_item(plan, args.section, args.index, MOVES[args.direction])
   print(f"{args.section} {i}")
   _save_plan(plan, manifest)


def cmd_plan_mode(args: argparse.Namespace) -> None:
   """!screen-plan mode. @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   with plan.edit("Display mode"):
      sp.set_mode(plan, args.mode)
   _save_plan(plan, manifest)


def cmd_plan_steps(args: argparse.Namespace) -> None:
   """!screen-plan steps. @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   with plan.edit("Frame steps"):
      sp.set_steps(plan, args.steps)
   _save_plan(plan, manifest)


def cmd_plan_transition(args: argparse.Namespace) -> None:
   """!screen-plan transition. @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   with plan.edit(f"Transition {args.which}"):
      sp.set_transition(plan, args.which, _value(args.value))
   _save_plan(plan, manifest)


def cmd_plan_fade_style(args: argparse.Namespace) -> None:
   """!screen-plan fade-style. @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   style = None if args.value == REMOVE else _value(args.value)
   if style is not None and not isinstance(style, dict):
      raise CommandError("the fade style is a JSON object, or -")
   with plan.edit("Fade style"):
      sp.set_fade_style(plan, style)
   _save_plan(plan, manifest)


def cmd_plan_exit(args: argparse.Namespace) -> None:
   """!screen-plan exit (S6b, engine C13a). @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   if args.call is not None:
      with plan.edit("Exit"):
         sp.set_exit(plan, args.call, args.next)
      _save_plan(plan, manifest)
   ex = sp.exit_of(plan.data)
   print(f"exit: {ex['call']}" + (f" -> {ex['next'] or '(no next screen)'}" if ex["call"] in sp.REPLACING else ""))
   for frame, what in sp.exit_frames(plan.data):
      print(f"  frame {frame}: {what}")


def cmd_plan_frames(args: argparse.Namespace) -> None:
   """!screen-plan frames. @param args  parsed arguments
   @return None
   """
   plan, _m = _plan(args.plan)
   frames = sp.fade_frames(sp.fade_of(sp.transition(plan.data, args.which)), sp.fade_style(plan.data))
   if not frames:
      print(f"{args.which}: no fade")
      return
   for i, (bg, obj) in enumerate(frames):
      print(f"call {i}: BG {bg}, OBJ {obj}")
   print(f"{len(frames)} calls")


def cmd_plan_render(args: argparse.Namespace) -> None:
   """!screen-plan render. @param args  parsed arguments
   @return None
   """
   plan, manifest = _plan(args.plan)
   fade = sp.fade_at(plan.data, args.transition, args.call) if args.transition else None
   img = sp.render(plan.data, manifest, args.later, fade, args.guides)
   engine.bitmap().write_png(args.out, *img)
   print(f"wrote {args.out} ({img[0]}x{img[1]})")


def cmd_plan_export(args: argparse.Namespace) -> None:
   """!screen-plan export. @param args  parsed arguments
   @return None
   """
   plan, _m = _plan(args.plan)
   Path(args.out).write_text(sp.export_cpp(plan.data, Path(args.plan).name), encoding="utf-8")
   print(f"wrote {args.out}")


# -- gba-memory ------------------------------------------------------------------------------------------------------


def cmd_mem_show(args: argparse.Namespace) -> None:
   """!gba-memory show. @param args  parsed arguments
   @return None
   """
   s = gba_memory.settings(args.build)
   print(f"{gba_memory.CHECKS}: {'ON' if s.checks else 'OFF'}")
   print(f"{gba_memory.RESERVE}: {s.reserve} B")
   print(f"{gba_memory.ARENA}: " + (f"{s.arena} B (overrides every game's screen_arena_bytes)" if s.arena else
                                     "(each game's screen_arena_bytes)"))
   if not s.gba:
      print("note: this build folder does not configure a GBA build (the settings apply to GBA links only)")


def cmd_mem_set(args: argparse.Namespace) -> None:
   """!gba-memory set. @param args  parsed arguments
   @return None
   """
   name = {"checks": gba_memory.CHECKS, "reserve": gba_memory.RESERVE, "arena": gba_memory.ARENA}[args.setting]
   value = args.value.upper() if args.setting == "checks" else ("" if args.value == REMOVE else args.value)
   gba_memory.set_cache(args.build, name, value)
   print(f"{name} = {value or '(default)'} (read at the next build)")


def cmd_mem_report(args: argparse.Namespace) -> int:
   """!gba-memory report. @param args  parsed arguments
   @return 1 when a program does not fit
   """
   if args.log:
      reports, failures = gba_memory.parse_log(Path(args.log).read_text(encoding="utf-8", errors="replace"))
      errors: list[str] = []
   else:
      reports, errors = gba_memory.folder_reports(args.build)
      failures = []
   for r in reports:
      print(r.line())
      for p in r.problems():
         print(f"  {p}")
      if args.arena:
         print(f"  {gba_memory.arena_share(r, args.arena)}")
   for f in failures:
      print(f"link failed: {f}")
   for e in errors:
      print(f"not read: {e}")
   if not reports and not failures:
      print("no GBA memory report (no linked GBA program, or no report lines in the log)")
   return 1 if failures or any(not r.fits for r in reports) else 0
