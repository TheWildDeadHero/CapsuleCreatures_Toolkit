"""!`capsule-studio text ...` and `capsule-studio credits ...`.

Texts are checked and previewed with the code page of the game the manifest
belongs to (core.codepage: the first reference/project.json in its folder
or above; the engine's ASCII page outside a game). `text codepage ...` shows
and edits that page and finds the characters the game's texts use that it
lacks.
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core import codepage, preview, texts
from .common import RGB_BYTES_PER_PIXEL, open_doc, write_rgb_png
from .main import CommandError

## Default enlargement of preview PNGs.
DEFAULT_PREVIEW_SCALE = 2
## Places `text codepage check` lists per missing character.
WHERE_SHOWN = 3


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command groups.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("text", help="text assets")
   s = p.add_subparsers(dest="text_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("set", help="set a text (creates it if needed)")
   q.add_argument("manifest")
   q.add_argument("key", help='e.g. "text:INTRO LINE 1"')
   src = q.add_mutually_exclusive_group(required=True)
   src.add_argument("--text", help=r"the string (use \n for line breaks)")
   src.add_argument("--file", help="read the string from a UTF-8 file ('-' for stdin)")
   q.set_defaults(run=cmd_text_set)
   q = s.add_parser("check", help="report characters and line lengths that won't fit")
   q.add_argument("manifest")
   q.add_argument("--columns", type=int, default=texts.SCREEN_COLUMNS)
   q.set_defaults(run=cmd_text_check)
   q = s.add_parser("preview", help="draw a text on a 240x160 screen to a PNG")
   q.add_argument("manifest")
   q.add_argument("key")
   q.add_argument("output")
   q.add_argument("--box", action="store_true", help="show it in the text box (cutscene layout)")
   q.add_argument("--scale", type=int, default=DEFAULT_PREVIEW_SCALE)
   q.set_defaults(run=cmd_text_preview)
   _register_codepage(s)

   p = sub.add_parser("credits", help="credits pages (heading + names text pairs)")
   p.add_argument("--prefix", default=texts.CREDITS_PREFIX, help="key prefix (default CREDITS)")
   s = p.add_subparsers(dest="credits_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("import", help="replace the credits from a text file (pages separated by blank lines, "
                                   "first line the heading)")
   q.add_argument("manifest")
   q.add_argument("file", help="UTF-8 text file, '-' for stdin")
   q.set_defaults(run=cmd_credits_import)
   q = s.add_parser("export", help="write the credits as a text file")
   q.add_argument("manifest")
   q.add_argument("-o", "--output", help="file (default: stdout)")
   q.set_defaults(run=cmd_credits_export)
   q = s.add_parser("preview", help="draw one credits page to a PNG")
   q.add_argument("manifest")
   q.add_argument("page", type=int, help="page number, from 1")
   q.add_argument("output")
   q.add_argument("--scale", type=int, default=DEFAULT_PREVIEW_SCALE)
   q.set_defaults(run=cmd_credits_preview)


def _register_codepage(s: argparse._SubParsersAction) -> None:
   """!Adds `text codepage ACTION PROJECT ...`.
   @param s  the text group's subparsers
   @return None
   """
   p = s.add_parser("codepage", help="the game's code page: which code each character gets")
   c = p.add_subparsers(dest="codepage_command", metavar="ACTION")
   c.required = True
   game = "the game: its reference/project.json, its folder or a file in it"
   q = c.add_parser("show", help="the page as a 16x16 grid, with its aliases")
   q.add_argument("project", help=game)
   q.set_defaults(run=cmd_codepage_show)
   q = c.add_parser("set", help="give a code (0x00-0xF9) a character")
   q.add_argument("project", help=game)
   q.add_argument("code", help="e.g. 0x80 or 128")
   q.add_argument("char", help="the character (one, with any combining marks)")
   q.set_defaults(run=cmd_codepage_set)
   q = c.add_parser("unset", help="leave a code without a character")
   q.add_argument("project", help=game)
   q.add_argument("code")
   q.set_defaults(run=cmd_codepage_unset)
   q = c.add_parser("alias", help="fold a character the page lacks onto mapped text (no TARGET: remove it)")
   q.add_argument("project", help=game)
   q.add_argument("text", help="e.g. a curly quote")
   q.add_argument("target", nargs="?", help="mapped text it encodes as")
   q.set_defaults(run=cmd_codepage_alias)
   q = c.add_parser("check", help="characters the game's texts use that the page lacks, and font glyphs it "
                                  "lacks; status 1 when there are any")
   q.add_argument("project", help=game)
   q.set_defaults(run=cmd_codepage_check)
   q = c.add_parser("import", help="give the game its own code page: copy a page (default: the engine's) into "
                                   f"{codepage.PAGE_FOLDER}/ and name it in project.json")
   q.add_argument("project", help=game)
   q.add_argument("file", nargs="?", help="a capsule.codepage/1 file")
   q.add_argument("--language", help="language id (default: the page's id)")
   q.add_argument("--replace", action="store_true", help="replace the page the game has for that language")
   q.set_defaults(run=cmd_codepage_import)


def _page_of(manifest: str) -> Any:
   """!The code page of the game a manifest belongs to.
   @param manifest  manifest path
   @return text_encoder.CodePage
   """
   return codepage.for_file(Path(manifest).resolve().parent)


def _read(path: str) -> str:
   """!Reads UTF-8 text from a file or stdin.
   @param path  file, or '-'
   @return the text
   """
   return sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")


def _write_screen(screen: preview.Screen, path: str | Path, scale: int) -> None:
   """!Saves a preview Screen, scaled up.
   @param screen  preview.Screen
   @param path    PNG path
   @param scale   integer factor
   @return None
   """
   k = max(1, scale)
   w, h = preview.WIDTH * k, preview.HEIGHT * k
   rgb = bytearray(w * h * RGB_BYTES_PER_PIXEL)
   for y in range(h):
      for x in range(w):
         # Each output pixel copies the screen pixel it scales up from.
         o = ((y // k) * preview.WIDTH + x // k) * RGB_BYTES_PER_PIXEL
         out = (y * w + x) * RGB_BYTES_PER_PIXEL
         rgb[out:out + RGB_BYTES_PER_PIXEL] = screen.rgb[o:o + RGB_BYTES_PER_PIXEL]
   write_rgb_png(path, w, h, rgb)


def _report(label: str, msgs: list[str]) -> bool:
   """!Prints check_text() messages.
   @param label  what was checked
   @param msgs   messages
   @return True when one of them is an error
   """
   for m in msgs:
      print(f"{label}: {m}" if m.startswith("error:") else f"{label}: warning: {m}")
   return any(m.startswith("error:") for m in msgs)


def cmd_text_set(args: argparse.Namespace) -> None:
   """!text set. @param args  parsed arguments
   @return None
   """
   value = args.text.replace("\\n", "\n") if args.text is not None else _read(args.file).rstrip("\n")
   doc = open_doc(args.manifest)
   if _report(args.key, texts.check_text(value, page=_page_of(args.manifest))):
      raise CommandError("text not saved")
   with doc.edit("Set text"):
      texts.set_text(doc, args.key, value)
   doc.save()


def cmd_text_check(args: argparse.Namespace) -> int:
   """!text check.
   @param args  parsed arguments
   @return 1 when a text has an error, otherwise 0
   """
   doc = open_doc(args.manifest)
   page = _page_of(args.manifest)
   bad = False
   for a in doc.assets("text"):
      bad |= _report(a.get("key"), texts.check_text(a.get("text", ""), args.columns, page=page))
   return 1 if bad else 0


def cmd_text_preview(args: argparse.Namespace) -> None:
   """!text preview. @param args  parsed arguments
   @return None
   """
   a = open_doc(args.manifest).get(args.key)
   if a.get("kind") != "text":
      raise CommandError(f"{args.key!r} is not a text")
   page, glyphs = _font_of(args.manifest)
   if args.box:
      screen = preview.text_box(a["text"], page=page, glyphs=glyphs)
   else:
      screen = preview.text_layer(a["text"], page=page, glyphs=glyphs)
   _write_screen(screen, args.output, args.scale)


def _font_of(manifest: str) -> tuple[Any, dict[int, list[list[int]]]]:
   """!The code page and font of the game a manifest belongs to.
   @param manifest  manifest path
   @return (text_encoder.CodePage, glyphs by code)
   """
   found = codepage.find_project(Path(manifest).resolve().parent)
   project = codepage.open_project(found) if found is not None else None
   page = codepage.load(project)
   return page, codepage.glyphs(project, page)


def cmd_credits_import(args: argparse.Namespace) -> None:
   """!credits import. @param args  parsed arguments
   @return None
   """
   pages = texts.parse_credits_text(_read(args.file))
   page = _page_of(args.manifest)
   bad = False
   for n, (h, names) in enumerate(pages, 1):
      bad |= _report(f"page {n} heading", texts.check_text(h, page=page))
      bad |= _report(f"page {n} names", texts.check_text(names, rows=texts.CREDITS_NAMES_ROWS, page=page))
   if bad:
      raise CommandError("credits not saved")
   doc = open_doc(args.manifest)
   with doc.edit("Credits"):
      texts.set_credits_pages(doc, pages, args.prefix)
   doc.save()
   print(f"{len(pages)} credits pages")


def cmd_credits_export(args: argparse.Namespace) -> None:
   """!credits export. @param args  parsed arguments
   @return None
   """
   out = texts.format_credits_text(texts.credits_pages(open_doc(args.manifest), args.prefix))
   if args.output:
      Path(args.output).write_text(out, encoding="utf-8")
   else:
      sys.stdout.write(out)


def cmd_credits_preview(args: argparse.Namespace) -> None:
   """!credits preview. @param args  parsed arguments
   @return None
   """
   pages = texts.credits_pages(open_doc(args.manifest), args.prefix)
   if not 1 <= args.page <= len(pages):
      raise CommandError(f"there are {len(pages)} pages")
   page, glyphs = _font_of(args.manifest)
   _write_screen(preview.credits_page(*pages[args.page - 1], page=page, glyphs=glyphs), args.output, args.scale)


# -- text codepage -------------------------------------------------------------------------------

def _char_label(ch: str) -> str:
   """!A character with its code points, e.g. 'é' (U+00E9).
   @param ch  the character
   @return text
   """
   points = "+".join(f"U+{ord(c):04X}" for c in ch)
   name = unicodedata.name(ch, "") if len(ch) == 1 else ""
   return f"{ch!r} ({points}{', ' + name if name else ''})"


def cmd_codepage_show(args: argparse.Namespace) -> int:
   """!text codepage show.
   @param args  parsed arguments
   @return 0
   """
   project = codepage.open_project(args.project)
   page = codepage.load(project)
   where = codepage.page_path(project) or "the engine's default page"
   print(f"{page.id}: {page.name} ({len(page.chars)} characters; {where})")
   for line in codepage.grid(page):
      print(line)
   aliases = {t: c for t, c in page.table.items() if t not in page.chars.values()}
   for t, codes in aliases.items():
      print(f"alias {t!r} -> {page.decode(codes)!r}")
   return 0


def _edit_page(args: argparse.Namespace, label: str, change: Callable[[Any], None]) -> int:
   """!Changes the game's own code page and saves it (nothing is saved when the page would be invalid).
   @param args    parsed arguments (project)
   @param label   undo label
   @param change  callable(page Document)
   @return 0
   """
   project = codepage.open_project(args.project)
   doc = codepage.open_page(project)
   with doc.edit(label):
      change(doc)
   doc.save()
   for m in codepage.font_problems(project):
      print(f"warning: {m}")
   return 0


def cmd_codepage_set(args: argparse.Namespace) -> int:
   """!text codepage set.
   @param args  parsed arguments
   @return 0
   """
   return _edit_page(args, "Set code", lambda d: codepage.set_code(d, codepage.parse_code(args.code), args.char))


def cmd_codepage_unset(args: argparse.Namespace) -> int:
   """!text codepage unset.
   @param args  parsed arguments
   @return 0
   """
   return _edit_page(args, "Unset code", lambda d: codepage.unset_code(d, codepage.parse_code(args.code)))


def cmd_codepage_alias(args: argparse.Namespace) -> int:
   """!text codepage alias.
   @param args  parsed arguments
   @return 0
   """
   return _edit_page(args, "Alias", lambda d: codepage.set_alias(d, args.text, args.target))


def cmd_codepage_check(args: argparse.Namespace) -> int:
   """!text codepage check.
   @param args  parsed arguments
   @return 1 when a character or glyph is missing, otherwise 0
   """
   project = codepage.open_project(args.project)
   page = codepage.load(project)
   missing = codepage.missing(project, page)
   for ch, where in missing.items():
      more = f" and {len(where) - WHERE_SHOWN} more" if len(where) > WHERE_SHOWN else ""
      print(f"missing {_char_label(ch)}: {'; '.join(where[:WHERE_SHOWN])}{more}")
   problems = codepage.font_problems(project, page)
   for m in problems:
      print(f"font: {m}")
   if not missing and not problems:
      print(f"every text fits the code page {page.id!r}")
   return 1 if missing or problems else 0


def cmd_codepage_import(args: argparse.Namespace) -> int:
   """!text codepage import.
   @param args  parsed arguments
   @return 0
   """
   project = codepage.open_project(args.project)
   with project.edit("Code page"):
      out = codepage.import_page(project, args.file, args.language, args.replace)
   project.save()
   print(f"code page {out} (language {codepage.language(project)})")
   return 0
