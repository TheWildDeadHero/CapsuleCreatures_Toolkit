"""!`capsule-studio text-table ...`, `font ...`, `text-box ...` and `manifest ...` (text, [the older studio]).

- text-table: a text table (capsule.texts/1, core.text_tables): its texts, wrap modes, fonts and box; `fit` checks
  every authored text against the box with the engine's rule; `controls` lists the control codes.
- font: a proportional font (capsule.font/2, core.fonts): its metrics and glyphs, a preview PNG.
- text-box: an asset manifest's text box styles (assets of kind text_box, the field options; core.text_boxes):
  settings, Font control fonts, checks, a preview PNG at a wait or a frame of the typing, the typing's timeline,
  The older studio's editor-data styles migrated into assets, a style's box applied to a table. `set` takes the
  art (palette, frame.image, frame.palette, window.arrow_image as JSON); `menu` shows / sets / clears a style's
  menu (core.menu_styles), `menu-run` runs it over a key script and says what happened, `menu-preview` draws a
  frame of the run to a PNG.
- manifest: an asset manifest's includes and text tables (core.asset_tables), the field options: its languages (the
build language
  and fallback, the engine's verdict, missing translations) and the engine's check of the whole manifest with its
  fit report (--language).

The game's code page and field placeholders are found from the file (core.text_tables.TextContext.for_manifest());
--code-page and --scripts name them instead. Edits are saved at once (a table or font keeps its file's layout).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..core import asset_tables, fonts, menu_styles, text_boxes, text_render, text_tables
from ..core.document import Document, DocumentError
from ..core.imaging import scale_nearest
from .main import CommandError

## Default enlargement of preview PNGs.
DEFAULT_SCALE = 2
## Characters of a text shown in `text-table list` before it is cut.
LIST_TEXT_CHARS = 60
## Fit lines `text-table fit` prints (the rest are counted).
FIT_LINES_SHOWN = 40
## Separator of a `text-box set` setting's group and key (window.x).
SETTING_SEPARATOR = "."
## Missing keys `manifest translations` names per language.
MISSING_SHOWN = 5
## Values of an option naming a table's text (the table, the key).
TABLE_TEXT_ARGS = 2
## Mark of a line wider than its box.
OVER_MARK = "OVER"
## The value that leaves a setting out (its default; a language key removed).
LEAVE_OUT = "-"


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command groups.
   @param sub  argparse subparsers
   @return None
   """
   _register_tables(sub)
   _register_fonts(sub)
   _register_boxes(sub)
   _register_manifest(sub)


def _context_args(q: argparse.ArgumentParser) -> None:
   """!The options naming the game's code page and scripts manifest.
   @param q  a parser
   @return None
   """
   q.add_argument("--code-page", help="the game's code page (default: the project's, or the *.codepage.json beside)")
   q.add_argument("--scripts", help="the scripts manifest whose field placeholders encode the texts (default: the "
                                    "project's, or the scripts.json naming the asset manifest)")


def _register_tables(sub: argparse._SubParsersAction) -> None:
   """!Adds `text-table ACTION TABLE ...`.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("text-table", help="text tables (capsule.texts/1)")
   s = p.add_subparsers(dest="table_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("list", help="the table's texts (key, wrap, font, start)")
   q.add_argument("table")
   q.add_argument("--json", action="store_true")
   q.set_defaults(run=cmd_table_list)
   q = s.add_parser("show", help="one text with its lines measured against the box")
   q.add_argument("table")
   q.add_argument("key")
   _context_args(q)
   q.set_defaults(run=cmd_table_show)
   q = s.add_parser("set", help="change a text")
   q.add_argument("table")
   q.add_argument("key")
   src = q.add_mutually_exclusive_group(required=True)
   src.add_argument("--text", help=r"the text (\n for a newline)")
   src.add_argument("--file", help="read it from a UTF-8 file ('-' for stdin)")
   q.set_defaults(run=cmd_table_set)
   q = s.add_parser("wrap", help="a text's wrap mode: original (authored breaks, checked) or auto (broken to the box)")
   q.add_argument("table")
   q.add_argument("key")
   q.add_argument("mode")
   q.set_defaults(run=cmd_table_wrap)
   q = s.add_parser("font", help="the font a text is fitted in (- for the box's)")
   q.add_argument("table")
   q.add_argument("key")
   q.add_argument("font")
   q.set_defaults(run=cmd_table_font)
   q = s.add_parser("add", help="add a text")
   q.add_argument("table")
   q.add_argument("key")
   q.add_argument("text", nargs="?", default="")
   q.add_argument("--wrap")
   q.set_defaults(run=cmd_table_add)
   q = s.add_parser("remove", help="remove a text")
   q.add_argument("table")
   q.add_argument("key")
   q.set_defaults(run=cmd_table_remove)
   q = s.add_parser("rename", help="rename a text's key")
   q.add_argument("table")
   q.add_argument("old")
   q.add_argument("new")
   q.set_defaults(run=cmd_table_rename)
   q = s.add_parser("box", help="show or set the table's box")
   q.add_argument("table")
   q.add_argument("--font")
   q.add_argument("--width", type=int)
   q.add_argument("--lines", type=int)
   q.set_defaults(run=cmd_table_box)
   q = s.add_parser("fit", help="check every authored text against the box (exit 1 when a line is wider)")
   q.add_argument("table")
   q.add_argument("--json", action="store_true")
   _context_args(q)
   q.set_defaults(run=cmd_table_fit)
   q = s.add_parser("language", help="set the table's language (- leaves it out: the table is in every "
                                     "language)")
   q.add_argument("table")
   q.add_argument("language")
   q.set_defaults(run=cmd_table_language)
   q = s.add_parser("controls", help="the control codes a text may use, with their arguments")
   q.set_defaults(run=cmd_controls)


def _register_fonts(sub: argparse._SubParsersAction) -> None:
   """!Adds `font ACTION FILE ...`.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("font", help="proportional fonts (capsule.font/2)")
   s = p.add_subparsers(dest="font_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("info", help="metrics, glyphs, the compiler's verdict, the page's characters it lacks")
   q.add_argument("font")
   _context_args(q)
   q.set_defaults(run=cmd_font_info)
   q = s.add_parser("glyph", help="a glyph's width and rows")
   q.add_argument("font")
   q.add_argument("glyph", help="its character (or #name)")
   q.set_defaults(run=cmd_font_glyph)
   q = s.add_parser("width", help="set a glyph's advance width")
   q.add_argument("font")
   q.add_argument("glyph")
   q.add_argument("width", type=int)
   q.set_defaults(run=cmd_font_width)
   q = s.add_parser("pixel", help="set a glyph pixel (0 transparent, 1 ink, 2 shadow, 3 fill)")
   q.add_argument("font")
   q.add_argument("glyph")
   q.add_argument("x", type=int)
   q.add_argument("y", type=int)
   q.add_argument("value", type=int)
   q.set_defaults(run=cmd_font_pixel)
   q = s.add_parser("metric", help="set line_height, letter_spacing or glyph_height (the rows a window draws of a "
                                   "glyph, 0: the whole cell)")
   q.add_argument("font")
   q.add_argument("name", choices=list(fonts.METRICS))
   q.add_argument("value", type=int)
   q.set_defaults(run=cmd_font_metric)
   q = s.add_parser("add", help="add a blank glyph")
   q.add_argument("font")
   q.add_argument("glyph")
   q.add_argument("--width", type=int)
   q.set_defaults(run=cmd_font_add)
   q = s.add_parser("remove", help="remove a glyph")
   q.add_argument("font")
   q.add_argument("glyph")
   q.set_defaults(run=cmd_font_remove)
   q = s.add_parser("preview", help="draw a text in the font to a PNG")
   q.add_argument("font")
   q.add_argument("text")
   q.add_argument("output")
   q.add_argument("--scale", type=int, default=DEFAULT_SCALE)
   _context_args(q)
   q.set_defaults(run=cmd_font_preview)


def _register_boxes(sub: argparse._SubParsersAction) -> None:
   """!Adds `text-box ACTION MANIFEST ...`.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("text-box", help="text box styles (asset kind text_box: window, frame, fonts)")
   s = p.add_subparsers(dest="box_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("list", help="the styles")
   q.add_argument("manifest")
   q.set_defaults(run=cmd_box_list)
   q = s.add_parser("show", help="a style's settings and checks")
   q.add_argument("manifest")
   q.add_argument("key")
   q.set_defaults(run=cmd_box_show)
   q = s.add_parser("fields", help="the settings the engine's text_box takes, with their ranges or words")
   q.set_defaults(run=cmd_box_fields)
   q = s.add_parser("add", help="add a style (text_box:NAME)")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("--font", help="its font's asset key")
   q.add_argument("--like", help="copy another style")
   q.set_defaults(run=cmd_box_add)
   q = s.add_parser("remove", help="remove a style")
   q.add_argument("manifest")
   q.add_argument("key")
   q.set_defaults(run=cmd_box_remove)
   q = s.add_parser("set", help="set window.KEY, frame.KEY (a number, a word, or - to leave it out), "
                                "preview.colors|frame_entries|frame_image, font or key")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("setting")
   q.add_argument("value", help="a number, a word, text, a comma-separated list, or -")
   q.set_defaults(run=cmd_box_set)
   q = s.add_parser("font", help="the font a style's Font control N selects (- takes it out)")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("number", type=int)
   q.add_argument("font")
   q.set_defaults(run=cmd_box_font)
   for word, run, what in (("preview", cmd_box_preview, "draw the box with a text on a 240x160 screen to a PNG"),
                           ("timeline", cmd_box_timeline, "type a text in the style frame by frame and say when it "
                                                          "waits and ends")):
      q = s.add_parser(word, help=what)
      q.add_argument("manifest")
      q.add_argument("key")
      if word == "preview":
         q.add_argument("output")
      src = q.add_mutually_exclusive_group()
      src.add_argument("--text", help="a text (markup)")
      src.add_argument("--table", nargs=TABLE_TEXT_ARGS, metavar=("TABLE", "KEY"), help="a table's text")
      q.add_argument("--keys", default="advance", choices=text_boxes.text_window.KEY_POLICIES,
                     help="none, advance (a press at each wait) or hold (Accept held)")
      if word == "preview":
         q.add_argument("--screen", type=int, default=0, help="which wait of the text (0: the first)")
         q.add_argument("--frame", type=int, help="a frame of the typing instead of a wait")
         q.add_argument("--scale", type=int, default=DEFAULT_SCALE)
      _context_args(q)
      q.set_defaults(run=run)
   q = s.add_parser("menu", help="a style's menu (ui::MenuStyle): show, set NAME VALUE (- leaves it out), on, off")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("action", nargs="?", default="show", choices=("show", "set", "on", "off", "fields"))
   q.add_argument("name", nargs="?")
   q.add_argument("value", nargs="?", help="a number, a word, comma-separated keys (cancel_keys), sprite:NAME, or -")
   q.set_defaults(run=cmd_box_menu)
   for word, run, what in (("menu-run", cmd_box_menu_run, "run a style's menu over a key script frame by frame"),
                           ("menu-preview", cmd_box_menu_preview, "draw a frame of a menu run to a PNG")):
      q = s.add_parser(word, help=what)
      q.add_argument("manifest")
      q.add_argument("key")
      if word == "menu-preview":
         q.add_argument("output")
         q.add_argument("--frame", type=int, help="the frame (default: the last)")
         q.add_argument("--scale", type=int, default=DEFAULT_SCALE)
      q.add_argument("--items", help="the options, | between them (text:KEY: a table's text); default the preview's")
      q.add_argument("--keys", help="a key script (down, down*40, wait 10, a); default the preview's")
      q.add_argument("--kind", choices=menu_styles.KINDS, help="the kind of menu (default the preview's)")
      q.add_argument("--shown", type=int, help="a list's rows shown")
      q.add_argument("--columns", type=int, help="a grid's columns")
      _context_args(q)
      q.set_defaults(run=run)
   q = s.add_parser("migrate", help="turn older studios' editor-data styles (editor.text_boxes) into text_box "
                                    "assets")
   q.add_argument("manifest")
   q.set_defaults(run=cmd_box_migrate)
   q = s.add_parser("apply", help="set a table's box to a style's width and lines")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("table")
   q.add_argument("--font-name", help="the table's name of the style's font (default: the table box's)")
   q.set_defaults(run=cmd_box_apply)


def _register_manifest(sub: argparse._SubParsersAction) -> None:
   """!Adds `manifest ACTION MANIFEST ...`.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("manifest", help="an asset manifest's includes and text tables")
   s = p.add_subparsers(dest="manifest_command", metavar="ACTION")
   s.required = True
   for word, key in (("includes", "includes"), ("tables", "text_tables")):
      q = s.add_parser(word, help=f"list, add or remove the manifest's {key}")
      q.add_argument("manifest")
      q.add_argument("action", nargs="?", choices=["add", "remove", "up", "down"])
      q.add_argument("path", nargs="?")
      q.set_defaults(run=cmd_manifest_list, key=key)
   q = s.add_parser("check", help="the engine's check of the whole manifest (includes, tables, fonts) and its fit")
   q.add_argument("manifest")
   q.add_argument("--fit-report", help="write the fit report (JSON) here")
   _context_args(q)
   q.set_defaults(run=cmd_manifest_check)
   q.add_argument("--language", help="the build's language (the asset compiler's --language)")
   q = s.add_parser("translations", help="the keys a language's tables lack that another language has (other "
                                         "languages: the manifest's own, and tables of the same name in sibling "
                                         "folders)")
   q.add_argument("manifest")
   q.set_defaults(run=cmd_manifest_translations)
   q = s.add_parser("languages", help="the languages of the manifest's tables, the build language and fallback, the "
                                      "engine's verdict and each language's missing keys")
   q.add_argument("manifest")
   q.add_argument("--language", help="check a build in this language (the asset compiler's --language)")
   q.set_defaults(run=cmd_manifest_languages)
   for word, key in (("language", "language"), ("fallback", "fallback_language")):
      q = s.add_parser(word, help=f"set the manifest's {key} (- leaves it out)")
      q.add_argument("manifest")
      q.add_argument("value")
      q.set_defaults(run=cmd_manifest_language, key=key)


# -- helpers ----------------------------------------------------------------------------------------------------------

def _context(path: str | Path, args: argparse.Namespace) -> text_tables.TextContext:
   """!The game's text settings for a file.
   @param path  a table, font or manifest
   @param args  parsed arguments (--code-page, --scripts)
   @return TextContext
   """
   page = getattr(args, "code_page", None)
   scripts = getattr(args, "scripts", None)
   return text_tables.TextContext.for_manifest(Path(path).resolve(), Path(scripts).resolve() if scripts else None,
                                               Path(page).resolve() if page else None)


def _edit(doc: Document, label: str, fn: Any) -> None:
   """!Runs an edit and saves the file.
   @param doc    Document
   @param label  what it is
   @param fn     the edit
   @return None
   """
   with doc.edit(label):
      fn()
   doc.save()


def _write_png(image: tuple[int, int, bytearray], path: str, scale: int) -> None:
   """!Writes an RGBA image scaled up.
   @param image  (w, h, RGBA)
   @param path   PNG path
   @param scale  factor
   @return None
   """
   from ..core import engine
   k = max(1, scale)
   w, h, _px = image
   ow, oh, px = scale_nearest(image, w * k, h * k)
   engine.bitmap().write_png(path, ow, oh, px)


def _shown(text: str) -> str:
   """!A text on one line.
   @param text  the text
   @return newlines written \\n, cut to LIST_TEXT_CHARS
   """
   flat = text.replace("\n", "\\n")
   return flat if len(flat) <= LIST_TEXT_CHARS else flat[:LIST_TEXT_CHARS] + "..."


# -- text-table -------------------------------------------------------------------------------------------------------

def cmd_table_list(args: argparse.Namespace) -> None:
   """!text-table list. @param args  parsed arguments
   @return None
   """
   doc = text_tables.open_table(args.table)
   rows = text_tables.rows(doc)
   if args.json:
      print(json.dumps([{"key": r.key, "text": r.text, "wrap": r.wrap, "font": r.font} for r in rows], indent=1,
                       ensure_ascii=False))
      return
   print(f"{doc.path.name}: language {doc.data.get('language')!r}, {len(rows)} texts, box {text_tables.box(doc)}")
   for r in rows:
      print(f"  {r.key}  [{r.wrap}{', ' + r.font if r.font else ''}]  {_shown(r.text)}")


def cmd_table_show(args: argparse.Namespace) -> None:
   """!text-table show. @param args  parsed arguments
   @return None
   """
   doc = text_tables.open_table(args.table)
   r = text_tables.entry(doc, args.key)
   print(f"{r.key} [{r.wrap}{', font ' + r.font if r.font else ''}]")
   print(r.text)
   fit = text_tables.check_text(_context(args.table, args), doc, args.key)
   if fit.error:
      print(f"error: {fit.error}")
   for line in fit.lines:
      mark = f" {OVER_MARK}" if line.over else ""
      extra = " (placeholders measured without their text)" if line.unmeasured else ""
      print(f"  line {line.number}: {line.width}/{line.box} px{mark}{extra}  {line.text}")


def cmd_table_set(args: argparse.Namespace) -> None:
   """!text-table set. @param args  parsed arguments
   @return None
   """
   if args.file is not None:
      text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
   else:
      text = args.text.replace("\\n", "\n")
   doc = text_tables.open_table(args.table)
   _edit(doc, "Edit text", lambda: text_tables.set_text(doc, args.key, text))


def cmd_table_wrap(args: argparse.Namespace) -> None:
   """!text-table wrap. @param args  parsed arguments
   @return None
   """
   doc = text_tables.open_table(args.table)
   _edit(doc, "Wrap", lambda: text_tables.set_wrap(doc, args.key, args.mode))


def cmd_table_font(args: argparse.Namespace) -> None:
   """!text-table font. @param args  parsed arguments
   @return None
   """
   doc = text_tables.open_table(args.table)
   font = None if args.font == "-" else args.font
   _edit(doc, "Font", lambda: text_tables.set_text_font(doc, args.key, font))


def cmd_table_add(args: argparse.Namespace) -> None:
   """!text-table add. @param args  parsed arguments
   @return None
   """
   doc = text_tables.open_table(args.table)
   _edit(doc, "Add text", lambda: text_tables.add_text(doc, args.key, args.text.replace("\\n", "\n"), args.wrap))


def cmd_table_remove(args: argparse.Namespace) -> None:
   """!text-table remove. @param args  parsed arguments
   @return None
   """
   doc = text_tables.open_table(args.table)
   _edit(doc, "Remove text", lambda: text_tables.remove_text(doc, args.key))


def cmd_table_rename(args: argparse.Namespace) -> None:
   """!text-table rename. @param args  parsed arguments
   @return None
   """
   doc = text_tables.open_table(args.table)
   _edit(doc, "Rename text", lambda: text_tables.rename_text(doc, args.old, args.new))


def cmd_table_box(args: argparse.Namespace) -> None:
   """!text-table box. @param args  parsed arguments
   @return None
   """
   doc = text_tables.open_table(args.table)
   if args.font is None and args.width is None and args.lines is None:
      print(json.dumps(text_tables.box(doc)))
      return
   b = text_tables.box(doc)
   font = args.font if args.font is not None else b.get("font")
   width = args.width if args.width is not None else b.get("width")
   lines = args.lines if args.lines is not None else b.get("lines")
   _edit(doc, "Box", lambda: text_tables.set_box(doc, font, width, lines))


def cmd_table_fit(args: argparse.Namespace) -> int:
   """!text-table fit. @param args  parsed arguments
   @return 1 when a line is wider than the box or a text does not compile
   """
   doc = text_tables.open_table(args.table)
   fit = text_tables.check_table(_context(args.table, args), doc)
   if args.json:
      print(json.dumps({"checked": fit.checked, "over": fit.over, "with_placeholders": fit.with_placeholders,
                        "problems": [{"key": p.key, "error": p.error,
                                      "lines": [{"line": n.number, "width": n.width, "box": n.box,
                                                 "with_placeholders": n.unmeasured} for n in p.over]}
                                     for p in fit.problems]}, indent=1))
   else:
      print(f"{doc.path.name}: {fit.checked} authored texts checked: {fit.over} lines wider than the box "
            f"({fit.with_placeholders} lines with placeholders measured without them)")
      shown = 0
      for p in fit.problems:
         if p.error:
            print(f"  error: {p.error}")
         for n in p.over:
            if shown < FIT_LINES_SHOWN:
               print(f"  {p.key} line {n.number}: {n.width}/{n.box} px  {n.text}")
            shown += 1
      if shown > FIT_LINES_SHOWN:
         print(f"  ... and {shown - FIT_LINES_SHOWN} more")
   return 1 if fit.problems else 0


def cmd_controls(args: argparse.Namespace) -> None:
   """!text-table controls. @param args  parsed arguments
   @return None
   """
   for c in text_tables.controls():
      widths = ", ".join(f"{w} byte(s)" for w in c.widths) or "no arguments"
      print(f"  {c.markup():24} 0x{c.code:02X}  {widths:28} {c.description}")


# -- font -------------------------------------------------------------------------------------------------------------

def cmd_font_info(args: argparse.Namespace) -> int:
   """!font info. @param args  parsed arguments
   @return 1 when the font does not compile for the page
   """
   doc = fonts.open_font(args.font)
   ctx = _context(args.font, args)
   cw, ch = fonts.cell(doc)
   rows = fonts.glyph_rows(doc, ctx.page)
   print(f"{doc.path.name}: {doc.data.get('name')!r}, cell {cw}x{ch}, line height {doc.data.get('line_height', ch)}, "
         f"letter spacing {doc.data.get('letter_spacing', 0)}, {len(rows)} glyphs")
   # The rows a window draws of each glyph
   gh = fonts.glyph_height(doc)
   print(f"  glyph height: {gh} (a window draws {fonts.drawn_rows(doc)} rows of each glyph)" if gh else
         f"  glyph height: the whole cell ({ch} rows)")
   problem = fonts.problem(doc, ctx.page)
   print(f"  compiles: {'no: ' + problem if problem else 'yes'}")
   missing = fonts.missing_characters(doc, ctx.page)
   print(f"  page characters without a glyph: {''.join(missing) if missing else 'none'}")
   return 1 if problem else 0


def cmd_font_glyph(args: argparse.Namespace) -> None:
   """!font glyph. @param args  parsed arguments
   @return None
   """
   doc = fonts.open_font(args.font)
   g = (doc.data.get("glyphs") or {}).get(args.glyph)
   if not isinstance(g, dict):
      raise CommandError(f"the font has no glyph {args.glyph!r}")
   print(f"{args.glyph!r}: width {g.get('width', fonts.cell(doc)[0])}")
   for r in g.get("rows", []):
      print("  " + r)


def cmd_font_width(args: argparse.Namespace) -> None:
   """!font width. @param args  parsed arguments
   @return None
   """
   doc = fonts.open_font(args.font)
   _edit(doc, "Width", lambda: fonts.set_width(doc, args.glyph, args.width))


def cmd_font_pixel(args: argparse.Namespace) -> None:
   """!font pixel. @param args  parsed arguments
   @return None
   """
   doc = fonts.open_font(args.font)
   _edit(doc, "Pixel", lambda: fonts.set_pixel(doc, args.glyph, args.x, args.y, args.value))


def cmd_font_metric(args: argparse.Namespace) -> None:
   """!font metric. @param args  parsed arguments
   @return None
   """
   doc = fonts.open_font(args.font)
   _edit(doc, "Metric", lambda: fonts.set_metric(doc, args.name, args.value))


def cmd_font_add(args: argparse.Namespace) -> None:
   """!font add. @param args  parsed arguments
   @return None
   """
   doc = fonts.open_font(args.font)
   _edit(doc, "Add glyph", lambda: fonts.add_glyph(doc, args.glyph, args.width))


def cmd_font_remove(args: argparse.Namespace) -> None:
   """!font remove. @param args  parsed arguments
   @return None
   """
   doc = fonts.open_font(args.font)
   _edit(doc, "Remove glyph", lambda: fonts.remove_glyph(doc, args.glyph))


def cmd_font_preview(args: argparse.Namespace) -> None:
   """!font preview. @param args  parsed arguments
   @return None
   """
   doc = fonts.open_font(args.font)
   ctx = _context(args.font, args)
   font = fonts.compile_font(doc, ctx.page)
   te = text_render.encoder()
   try:
      codes = te.encode(args.text.replace("\\n", "\n"), "preview", codepage=ctx.page, controls=True)
   except te.TextError as e:
      raise CommandError(str(e)) from None
   _write_png(text_render.render_text(font, codes, text_render.preview_pens(), margin=1), args.output, args.scale)


# -- text-box ---------------------------------------------------------------------------------------------------------

def _manifest(path: str) -> Document:
   """!An asset manifest.
   @param path  the file
   @return Document
   """
   try:
      return Document.open(path)
   except (OSError, ValueError) as e:
      raise CommandError(f"cannot read {path}: {e}") from None


def _style(doc: Document, key: str) -> dict[str, Any]:
   """!A style of the manifest by key (text_box:NAME or NAME).
   @param doc  asset manifest Document
   @param key  its key
   @return the style
   """
   try:
      return text_boxes.find(doc, text_boxes.full_key(key))
   except DocumentError as e:
      raise CommandError(str(e)) from None


def cmd_box_list(args: argparse.Namespace) -> None:
   """!text-box list. @param args  parsed arguments
   @return None
   """
   doc = _manifest(args.manifest)
   for s in text_boxes.styles(doc):
      w = {k: text_boxes.value(s, "window", k) for k in ("x", "y", "width", "height", "typing", "speedup")}
      print(f"  {s.get('key')}: {w['width']}x{w['height']} cells at ({w['x']}, {w['y']}), font {s.get('font')}, "
            f"typing {w['typing']}, speed-up {w['speedup']}")
   legacy = text_boxes.legacy_styles(doc)
   if legacy:
      print(f"  {len(legacy)} editor-data styles of older studios (`text-box migrate` makes them text_box assets)")


def cmd_box_show(args: argparse.Namespace) -> int:
   """!text-box show. @param args  parsed arguments
   @return 1 when the engine would refuse the style
   """
   doc = _manifest(args.manifest)
   s = _style(doc, args.key)
   print(json.dumps(s, indent=1))
   print(f"window storage: {text_boxes.storage(s).text()}")   # what window::attach() needs
   problems = text_boxes.check(s, None, text_boxes.font_keys(doc), doc.base_dir)
   for p in problems:
      print(p)
   return 1 if any(p.startswith("error") for p in problems) else 0


def cmd_box_fields(args: argparse.Namespace) -> None:
   """!text-box fields. @param args  parsed arguments
   @return None
   """
   for f in text_boxes.config_fields():
      allowed = "|".join(f.words) if f.words else f"{f.low}-{f.high}"
      default = "left out: " + ("the layer's" if f.name == "char_block" else "none") if f.optional else f.default
      print(f"  {f.group}.{f.name:16} {allowed:22} default {default!s:<16} {f.doc}")


def cmd_box_add(args: argparse.Namespace) -> None:
   """!text-box add. @param args  parsed arguments
   @return None
   """
   doc = _manifest(args.manifest)
   like = text_boxes.full_key(args.like) if args.like else None
   _edit(doc, "Add text box", lambda: text_boxes.add_style(doc, args.key, args.font, like))


def cmd_box_remove(args: argparse.Namespace) -> None:
   """!text-box remove. @param args  parsed arguments
   @return None
   """
   doc = _manifest(args.manifest)
   key = str(_style(doc, args.key)["key"])
   _edit(doc, "Remove text box", lambda: text_boxes.remove_style(doc, key))


def cmd_box_set(args: argparse.Namespace) -> None:
   """!text-box set. @param args  parsed arguments
   @return None
   """
   doc = _manifest(args.manifest)
   key = str(_style(doc, args.key)["key"])
   group, _sep, name = args.setting.rpartition(SETTING_SEPARATOR)
   raw: Any = args.value
   if (group, name) in ART_SETTINGS:   # the style's art
      raw = None if raw == LEAVE_OUT else (_json_value(raw) if name == text_boxes.ARROW_IMAGE_KEY else
                                           [p.strip() for p in raw.split(",") if p.strip()]
                                           if name == text_boxes.PALETTE_KEY else raw)
   elif group in ("window", "frame"):
      f = text_boxes.field_of(group, name)
      if raw == LEAVE_OUT:
         raw = None
      elif f is not None and not f.words:
         try:
            raw = int(args.value, 0)
         except ValueError:
            raise CommandError(f"{args.setting} is a number (or - to leave it out)") from None
   elif group == "preview" and name in ("colors", "frame_entries"):
      parts = [p.strip() for p in args.value.split(",") if p.strip()]
      raw = parts if name == "colors" else [int(p, 0) for p in parts]
   elif raw == LEAVE_OUT:
      raw = None
   _edit(doc, "Text box", lambda: text_boxes.set_value(doc, key, group, name, raw))


## The style's art settings `text-box set` takes as (group, name).
ART_SETTINGS = (("", text_boxes.PALETTE_KEY), ("frame", text_boxes.FRAME_PALETTE_KEY),
                ("frame", text_boxes.FRAME_IMAGE_KEY), ("window", text_boxes.ARROW_IMAGE_KEY))


def _json_value(text: str) -> Any:
   """!A JSON value from the command line.
   @param text  JSON
   @return the value
   """
   try:
      return json.loads(text)
   except ValueError as e:
      raise CommandError(f"{text!r} is no JSON: {e}") from None


def cmd_box_menu(args: argparse.Namespace) -> int:
   """!text-box menu. @param args  parsed arguments
   @return 0
   """
   if args.action == "fields":
      for f in menu_styles.menu_fields():
         allowed = "|".join(f.words) if f.words else (f"{f.low}-{f.high}" if f.kind == "number" else f.kind)
         print(f"  {f.name:16} {allowed:28} default {f.default!s:<10} {f.doc}")
      return 0
   doc = _manifest(args.manifest)
   key = str(_style(doc, args.key)["key"])
   if args.action in ("on", "off"):
      _edit(doc, "Menu", lambda: menu_styles.set_menu(doc, key, args.action == "on"))
   elif args.action == "set":
      if not args.name or args.value is None:
         raise CommandError("text-box menu MANIFEST KEY set NAME VALUE")
      f = menu_styles.field_of(args.name)
      if f is None:
         raise CommandError(f"no menu setting {args.name!r} (`text-box menu - - fields` lists them)")
      raw: Any = args.value
      if raw == LEAVE_OUT:
         raw = None
      elif f.kind == "number":
         try:
            raw = int(raw, 0)
         except ValueError:
            raise CommandError(f"menu {args.name} is a number") from None
      elif f.kind == "keys":
         raw = [k.strip() for k in raw.split(",") if k.strip()]
      _edit(doc, "Menu", lambda: menu_styles.set_value(doc, key, args.name, raw))
   for line in menu_styles.lines(text_boxes.find(doc, key)):
      print(line)
   return 0


def _menu_run(args: argparse.Namespace) -> tuple[Document, dict[str, Any], menu_styles.MenuRun]:
   """!A style's menu run for menu-run / menu-preview.
   @param args  parsed arguments
   @return (manifest, the style with the command line's preview settings, the run)
   """
   doc = _manifest(args.manifest)
   style = json.loads(json.dumps(_style(doc, args.key)))   # a copy: the command line's settings are not saved
   if not menu_styles.has_menu(style):
      raise CommandError(f"{style['key']} has no menu (`text-box menu ... on`)")
   preview = style.setdefault("editor", {}).setdefault(menu_styles.PREVIEW_KEY, {})
   for name in ("kind", "shown", "columns"):
      if getattr(args, name) is not None:
         preview[name] = getattr(args, name)
   if args.keys is not None:
      preview["script"] = args.keys
   if args.items is not None:
      preview["items"] = [t.strip() for t in args.items.split("|") if t.strip()]
   ctx = _context(args.manifest, args)
   font, _control = _box_fonts(doc, style, ctx)
   if font is None:
      raise CommandError(f"{style['key']}'s font is no font of the manifest")
   p = menu_styles.preview_data(style)
   lines = list(p.get("items") or []) or (list(menu_styles.YES_NO_ITEMS) if p.get("kind") == "yes_no" else [])
   texts = {}
   stems = {t[len("text:"):].split(".")[0] for t in lines if t.startswith("text:")}
   # the tables named after a key's first part first (text:menus.X is in menus.json by the importer's naming)
   for ref in sorted(asset_tables.tables(doc), key=lambda r: Path(r.path).stem not in stems):
      wanted = [t for t in lines if t.startswith("text:") and t not in texts]
      if not wanted:
         break
      table = text_tables.open_table(ref.path)
      for t in wanted:
         if t in (table.data.get("texts") or {}):
            texts[t] = text_tables.entry(table, t).text
   try:
      items = [ctx.encode(texts.get(t, t), "menu option") for t in lines]
      return doc, style, menu_styles.run(style, font, items, base=doc.base_dir,
                                         placeholders=ctx.placeholder_codes())
   except DocumentError as e:
      raise CommandError(str(e)) from None


def cmd_box_menu_run(args: argparse.Namespace) -> int:
   """!text-box menu-run. @param args  parsed arguments
   @return 0
   """
   _doc, style, run = _menu_run(args)
   print(f"{style['key']}: {menu_styles.describe(run)}")
   print(f"  cursor by frame: {' '.join(str(c) for c in run.cursors)}")
   if any(run.scrolls):
      print(f"  scroll by frame: {' '.join(str(c) for c in run.scrolls)}")
   return 0


def cmd_box_menu_preview(args: argparse.Namespace) -> None:
   """!text-box menu-preview. @param args  parsed arguments
   @return None
   """
   doc, _style_copy, run = _menu_run(args)
   frame = args.frame if args.frame is not None else len(run.frames) - 1
   _write_png(menu_styles.preview(run, frame, doc.base_dir).image(), args.output, args.scale)


def cmd_box_font(args: argparse.Namespace) -> None:
   """!text-box font. @param args  parsed arguments
   @return None
   """
   doc = _manifest(args.manifest)
   key = str(_style(doc, args.key)["key"])
   font = None if args.font == LEAVE_OUT else args.font
   _edit(doc, "Font control", lambda: text_boxes.set_control_font(doc, key, args.number, font))
   print(json.dumps(text_boxes.find(doc, key).get("fonts", {})))


def _box_fonts(doc: Document, style: dict[str, Any], ctx: text_tables.TextContext) -> tuple[Any, dict[int, Any]]:
   """!A style's compiled font and its Font control's fonts.
   @param doc    asset manifest Document
   @param style  the style
   @param ctx    the game's text settings
   @return (font or None, number -> font)
   """
   paths = dict(asset_tables.fonts(doc))
   font = ctx.font(paths[style["font"]]) if style.get("font") in paths else None
   control = {n: ctx.font(paths[k]) for n, k in text_boxes.control_fonts(style).items() if k in paths}
   return font, control


def _box_codes(args: argparse.Namespace, ctx: text_tables.TextContext) -> list[int] | None:
   """!The text of a preview or timeline (--table or --text).
   @param args  parsed arguments
   @param ctx   the game's text settings
   @return codes, or None
   """
   if args.table:
      table = text_tables.open_table(args.table[0])
      return ctx.encode(text_tables.entry(table, args.table[1]).text, args.table[1])
   if args.text:
      return ctx.encode(args.text.replace("\\n", "\n"), "preview")
   return None


def cmd_box_preview(args: argparse.Namespace) -> None:
   """!text-box preview. @param args  parsed arguments
   @return None
   """
   doc = _manifest(args.manifest)
   style = _style(doc, args.key)
   ctx = _context(args.manifest, args)
   font, control = _box_fonts(doc, style, ctx)
   codes = _box_codes(args, ctx)
   canvas = text_boxes.preview(style, font, codes, args.screen, doc.base_dir, ctx.placeholder_codes(), args.frame,
                               keys=args.keys, fonts=control)
   _write_png(canvas.image(), args.output, args.scale)


def cmd_box_timeline(args: argparse.Namespace) -> int:
   """!text-box timeline. @param args  parsed arguments
   @return 1 when the style has no font or no text was given
   """
   doc = _manifest(args.manifest)
   style = _style(doc, args.key)
   ctx = _context(args.manifest, args)
   font, control = _box_fonts(doc, style, ctx)
   codes = _box_codes(args, ctx)
   if font is None or not codes:
      print("error: the style needs a font of the manifest and a text (--text or --table)")
      return 1
   run = text_boxes.typing(style, font, codes, args.keys, control, ctx.placeholder_codes(), doc.base_dir)
   w = {k: text_boxes.value(style, "window", k) for k in ("typing", "speedup", "frames_per_char", "char_delay",
                                                           "lead_frames")}
   print(f"{style['key']}: typing {w['typing']} (frames_per_char {w['frames_per_char']}, char_delay "
         f"{w['char_delay']}, lead {w['lead_frames']}), speed-up {w['speedup']}, keys {args.keys}")
   print(f"  {text_boxes.describe_run(run)}")
   if run.presses:
      print(f"  presses at {', '.join(str(f) for f in run.presses)}")
   return 0


def cmd_box_migrate(args: argparse.Namespace) -> None:
   """!text-box migrate. @param args  parsed arguments
   @return None
   """
   doc = _manifest(args.manifest)
   if not text_boxes.legacy_styles(doc):
      print("no editor-data styles")
      return
   done: list[Any] = []
   _edit(doc, "Text box assets", lambda: done.extend(text_boxes.migrate(doc)))
   for name, key, dropped in done:
      print(f"  {name} -> {key}" + (f" (left out: {', '.join(dropped)})" if dropped else ""))


def cmd_box_apply(args: argparse.Namespace) -> None:
   """!text-box apply. @param args  parsed arguments
   @return None
   """
   style = _style(_manifest(args.manifest), args.key)
   table = text_tables.open_table(args.table)
   name = args.font_name if args.font_name is not None else text_tables.box(table).get("font")
   b = text_boxes.fit_box(style, name)
   _edit(table, "Box", lambda: text_tables.set_box(table, b.get("font"), b["width"], b["lines"]))
   print(json.dumps(text_tables.box(table)))


# -- manifest ---------------------------------------------------------------------------------------------------------

def cmd_manifest_list(args: argparse.Namespace) -> None:
   """!manifest includes | tables. @param args  parsed arguments
   @return None
   """
   doc = _manifest(args.manifest)
   if args.action is not None:
      if not args.path:
         raise CommandError(f"{args.action} needs a path")
      steps = {"up": -1, "down": 1}
      if args.action == "add":
         _edit(doc, "Add", lambda: asset_tables.add_entry(doc, args.key, args.path))
      elif args.action == "remove":
         _edit(doc, "Remove", lambda: asset_tables.remove_entry(doc, args.key, args.path))
      else:
         _edit(doc, "Move", lambda: asset_tables.move_entry(doc, args.key, args.path, steps[args.action]))
   for rel in asset_tables.entries(doc, args.key):
      print(f"  {rel}")


def cmd_manifest_check(args: argparse.Namespace) -> int:
   """!manifest check. @param args  parsed arguments
   @return 1 when the manifest does not compile or a line is wider than its box
   """
   doc = _manifest(args.manifest)
   ctx = _context(args.manifest, args)
   try:
      fit = asset_tables.fit_report(doc, ctx.page, ctx.field, getattr(args, "language", None))
   except DocumentError as e:
      print(f"error: {e}")
      return 1
   print(f"{doc.path.name}: {fit['assets']} assets; {fit.get('checked', 0)} authored texts checked against their "
         f"box: {fit.get('over', 0)} lines wider ({fit.get('with_placeholders', 0)} lines with placeholders "
         f"measured without them)")
   if args.fit_report:
      Path(args.fit_report).write_text(json.dumps({k: v for k, v in fit.items() if k != "assets"}, indent=1) + "\n",
                                       encoding="utf-8")
   return 1 if fit.get("over") else 0


def cmd_manifest_translations(args: argparse.Namespace) -> int:
   """!manifest translations. @param args  parsed arguments
   @return 1 when a language lacks a key
   """
   doc = _manifest(args.manifest)
   docs = {t.path: text_tables.open_table(t.path) for t in asset_tables.table_set(doc)}
   missing = asset_tables.missing_translations(docs)
   langs = sorted({str(d.data.get("language", "")) for d in docs.values()})
   print(f"{len(docs)} tables, languages: {', '.join(lang or '(every)' for lang in langs) or 'none'}")
   for lang, keys in missing.items():
      print(f"  {lang}: {len(keys)} keys missing, e.g. {', '.join(keys[:MISSING_SHOWN])}")
   return 1 if missing else 0


def cmd_manifest_languages(args: argparse.Namespace) -> int:
   """!manifest languages. @param args  parsed arguments
   @return 1 when the engine refuses the manifest's languages
   """
   doc = _manifest(args.manifest)
   docs = {t.path: text_tables.open_table(t.path) for t in asset_tables.tables(doc)}
   langs = asset_tables.languages(doc, docs)
   build = asset_tables.build_language(doc, args.language, docs)
   fallback = asset_tables.language_setting(doc, "fallback_language")
   print(f"{len(docs)} tables listed, languages: {', '.join(langs) or 'none'}")
   print(f"  manifest language {asset_tables.language_setting(doc, 'language') or LEAVE_OUT}, fallback "
         f"{fallback or LEAVE_OUT}; a build takes {build or 'no language'}")
   problem = asset_tables.language_problem(doc, args.language, docs)
   if problem:
      print(f"  error: {problem}")
   for lang, keys in asset_tables.missing_translations(docs).items():
      filled = asset_tables.fallback_keys(docs, lang, fallback)
      note = f", {len(filled)} from the fallback {fallback}" if filled else ""
      print(f"  {lang}: {len(keys)} keys missing{note}, e.g. {', '.join(keys[:MISSING_SHOWN])}")
   return 1 if problem else 0


def cmd_manifest_language(args: argparse.Namespace) -> None:
   """!manifest language | fallback. @param args  parsed arguments
   @return None
   """
   doc = _manifest(args.manifest)
   value = None if args.value == LEAVE_OUT else args.value
   _edit(doc, "Language", lambda: asset_tables.set_language(doc, args.key, value))
   print(f"{args.key}: {asset_tables.language_setting(doc, args.key) or LEAVE_OUT}")


def cmd_table_language(args: argparse.Namespace) -> None:
   """!text-table language. @param args  parsed arguments
   @return None
   """
   table = text_tables.open_table(args.table)
   value = None if args.language == LEAVE_OUT else args.language
   _edit(table, "Language", lambda: text_tables.set_language(table, value))
   print(f"{table.path.name}: language {table.data.get('language', LEAVE_OUT)}")
