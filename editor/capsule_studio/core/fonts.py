"""!Proportional fonts (engine I4, D-29: capsule.font/2, `*.font.json`) for the font editor [S2].

A font is a Document (schema capsule.font/2, opened keeping its file's json layout): a cell (width a multiple of
font_compiler.CELL_WIDTH_STEP, each side at most MAX_CELL), a line height and letter spacing, S6b (engine C13a) an
optional glyph_height (the rows of a glyph a window draws, 0 or left out: the whole cell; the handheld games' glyph
height, so a cell's rows below it never show), and glyphs keyed by
their character (or `#name`, a named glyph of the code page), each with its advance width and cell rows of pixel
digits (font_compiler.PIXEL_DIGITS: 0 transparent, 1 ink, 2 shadow, 3 fill). The engine's
tools/font_compiler.py compile_proportional() is the one authority: compile_font() runs it on the Document's data
(unsaved edits included, through a MemoryFile), and its message is the font's problem. The edit helpers keep a font
well formed by the compiler's own limits; call them inside Document.edit().

Qt-free; the font panel (ui/editors/fonts.py) and `capsule-studio font ...` use it.
"""
from __future__ import annotations

import json
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import engine
from .document import Document, DocumentError

## Schema of a proportional font (the engine's font_compiler.PROPORTIONAL_SCHEMA; a test keeps them equal).
SCHEMA = "capsule.font/2"
## A parsed JSON object.
JsonDict = dict[str, Any]
## Index of the width in a cell (width, height).
CELL_WIDTH = 0
## Index of the height in a cell.
CELL_HEIGHT = 1
## S6b (C13a): the font key of the rows a window draws (font_compiler PROPORTIONAL_KEYS; 0: the whole cell).
GLYPH_HEIGHT = "glyph_height"
## The metrics set_metric() sets.
METRICS = ("line_height", "letter_spacing", GLYPH_HEIGHT)


def compiler() -> types.ModuleType:
   """!The engine's font compiler.
   @return module
   """
   return engine.tool("font_compiler")


class MemoryFile:
   """!A file the engine's readers take in place of a Path (they read name, parent and read_text()): a Document's
   data as it is now, unsaved edits included."""

   def __init__(self, data: JsonDict, path: Path | None, name: str = "untitled.json") -> None:
      """!Wraps data.
      @param data  the JSON object
      @param path  the file it stands for (its folder is the readers' base for relative paths), or None
      @param name  the name used when there is no path
      """
      ## The file's name (the readers' messages start with it).
      self.name = path.name if path is not None else name
      ## Its folder.
      self.parent = path.parent if path is not None else Path(".")
      ## The text the readers parse.
      self.text = json.dumps(data, ensure_ascii=False)

   def read_text(self, encoding: str = "utf-8") -> str:
      """!The file's text.
      @param encoding  ignored (the text is in memory)
      @return text
      """
      return self.text

   def resolve(self) -> Path:
      """!The file's absolute path (readers resolve relative paths against it).
      @return Path
      """
      return (self.parent / self.name).resolve()


def open_font(path: str | Path) -> Document:
   """!Opens a font file.
   @param path  the .font.json
   @return Document (its json layout kept on save)
   @throws DocumentError when it is not a capsule.font/2 file
   """
   try:
      return Document.open(path, SCHEMA, keep_layout=True)
   except (OSError, ValueError) as e:
      raise DocumentError(f"cannot read {path}: {e}") from e


def compile_font(doc: Document, page: Any) -> JsonDict:
   """!The font compiled by the engine for a code page.
   @param doc   font Document
   @param page  text_encoder.CodePage
   @return compile_proportional()'s result
   @throws DocumentError with the compiler's message
   """
   te = engine.tool("text_encoder")
   try:
      return compiler().compile_proportional(MemoryFile(doc.data, doc.path), page)
   except te.TextError as e:
      raise DocumentError(str(e)) from None


def problem(doc: Document, page: Any) -> str | None:
   """!What the build would refuse in the font.
   @param doc   font Document
   @param page  code page
   @return the compiler's message, or None when it compiles
   """
   try:
      compile_font(doc, page)
   except DocumentError as e:
      return str(e)
   return None


def code_of(key: str, page: Any) -> int | None:
   """!The code a glyph key has in a code page (the compiler's rule: a character with one code, or `#name` of a
   named glyph with one code).
   @param key   the glyph's key
   @param page  code page
   @return the code, or None when the page has no single code for it
   """
   prefix = engine.tool("text_encoder").GLYPH_PREFIX
   if key.startswith(prefix) and key[len(prefix):] in page.names:
      codes = page.names[key[len(prefix):]]
   else:
      codes = page.table.get(key)
   return codes[0] if codes and len(codes) == 1 else None


@dataclass
class GlyphRow:
   """!One glyph of a font."""

   ## Its key (character or `#name`).
   key: str
   ## Its code in the page, or None.
   code: int | None
   ## Its advance width, pixels.
   width: int
   ## Its rows of pixel digits.
   rows: list[str]


def cell(doc: Document) -> tuple[int, int]:
   """!The font's cell.
   @param doc  font Document
   @return (width, height)
   """
   c = doc.data.get("cell") or [0, 0]
   return int(c[CELL_WIDTH]), int(c[CELL_HEIGHT])


def glyph_rows(doc: Document, page: Any) -> list[GlyphRow]:
   """!The font's glyphs by code (glyphs without a code last, in file order).
   @param doc   font Document
   @param page  code page
   @return rows
   """
   cw, _ch = cell(doc)
   out = []
   for key, g in (doc.data.get("glyphs") or {}).items():
      g = g if isinstance(g, dict) else {}
      out.append(GlyphRow(key, code_of(key, page), int(g.get("width", cw)), list(g.get("rows", []))))
   order = {id(r): i for i, r in enumerate(out)}
   return sorted(out, key=lambda r: (r.code is None, r.code if r.code is not None else 0, order[id(r)]))


def missing_characters(doc: Document, page: Any) -> list[str]:
   """!The page's characters the font has no glyph for (a text using one is refused by the table compiler).
   @param doc   font Document
   @param page  code page
   @return characters, in code order
   """
   have = set((doc.data.get("glyphs") or {}).keys())
   chars = page.chars   # code -> character
   return [chars[c] for c in sorted(chars) if chars[c] not in have]


def _glyph(doc: Document, key: str) -> JsonDict:
   """!A glyph's object.
   @param doc  font Document
   @param key  its key
   @return the object (live)
   @throws DocumentError when there is none
   """
   g = (doc.data.get("glyphs") or {}).get(key)
   if not isinstance(g, dict):
      raise DocumentError(f"the font has no glyph {key!r}")
   return g


def _check_metric(value: int, what: str) -> None:
   """!A width, line height or letter spacing within the compiler's range.
   @param value  the value
   @param what   its name for the message
   @return None
   @throws DocumentError when it is out of range
   """
   top = compiler().MAX_METRIC
   if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= top:
      raise DocumentError(f"{what} is 0-{top}")


def set_width(doc: Document, key: str, width: int) -> None:
   """!Sets a glyph's advance width (call inside Document.edit()).
   @param doc    font Document
   @param key    the glyph
   @param width  pixels, 0-MAX_METRIC
   @return None
   """
   _check_metric(width, "a width")
   _glyph(doc, key)["width"] = width


def set_pixel(doc: Document, key: str, x: int, y: int, value: int) -> None:
   """!Sets one pixel of a glyph (call inside Document.edit()).
   @param doc    font Document
   @param key    the glyph
   @param x      column
   @param y      row
   @param value  a pixel value (0 transparent, 1 ink, 2 shadow, 3 fill)
   @return None
   @throws DocumentError for a pixel off the cell or a value the compiler does not know
   """
   digits = compiler().PIXEL_DIGITS
   cw, ch = cell(doc)
   if not 0 <= x < cw or not 0 <= y < ch:
      raise DocumentError(f"({x}, {y}) is off the {cw}x{ch} cell")
   if not 0 <= value < len(digits):
      raise DocumentError(f"a pixel is one of {', '.join(digits)}")
   g = _glyph(doc, key)
   rows = list(g.get("rows", []))
   row = rows[y]
   rows[y] = row[:x] + digits[value] + row[x + 1:]
   g["rows"] = rows


def set_rows(doc: Document, key: str, rows: list[str]) -> None:
   """!Replaces a glyph's rows (call inside Document.edit()).
   @param doc   font Document
   @param key   the glyph
   @param rows  cell-height strings of cell-width pixel digits
   @return None
   @throws DocumentError when they do not fit the cell
   """
   digits = set(compiler().PIXEL_DIGITS)
   cw, ch = cell(doc)
   if len(rows) != ch or any(len(r) != cw or set(r) - digits for r in rows):
      raise DocumentError(f"a glyph is {ch} rows of {cw} pixel digits")
   _glyph(doc, key)["rows"] = list(rows)


def add_glyph(doc: Document, key: str, width: int | None = None) -> None:
   """!Adds a blank glyph (call inside Document.edit()).
   @param doc    font Document
   @param key    its character (or `#name`)
   @param width  its advance (default the cell width)
   @return None
   @throws DocumentError when it exists or the width is out of range
   """
   glyphs = doc.data.setdefault("glyphs", {})
   if not key:
      raise DocumentError("a glyph is keyed by its character or #name")
   if key in glyphs:
      raise DocumentError(f"the font has a glyph {key!r} already")
   cw, ch = cell(doc)
   width = cw if width is None else width
   _check_metric(width, "a width")
   glyphs[key] = {"width": width, "rows": [compiler().PIXEL_DIGITS[0] * cw] * ch}


def remove_glyph(doc: Document, key: str) -> None:
   """!Removes a glyph (call inside Document.edit()).
   @param doc  font Document
   @param key  the glyph
   @return None
   """
   _glyph(doc, key)
   del doc.data["glyphs"][key]


def glyph_height(doc: Document) -> int:
   """!S6b (C13a): the rows of a glyph a window draws as the font states it.
   @param doc  font Document
   @return glyph_height (0: the whole cell)
   """
   v = doc.data.get(GLYPH_HEIGHT, 0)
   return v if isinstance(v, int) and not isinstance(v, bool) else 0


def drawn_rows(doc: Document) -> int:
   """!S6b (C13a): the rows a window draws of each glyph (window.cpp glyph_rows(): glyph_height, the cell's height
   when it is 0).
   @param doc  font Document
   @return rows
   """
   ch = cell(doc)[CELL_HEIGHT]
   h = glyph_height(doc)
   return h if 0 < h < ch else ch


def set_metric(doc: Document, name: str, value: int) -> None:
   """!Sets the line height, the letter spacing or (S6b) the glyph height (call inside Document.edit()).
   @param doc    font Document
   @param name   one of METRICS
   @param value  pixels (glyph_height: 0-the cell's height, 0 the whole cell, which leaves the key out)
   @return None
   """
   if name not in METRICS:
      raise DocumentError(f"{name!r} is not a font metric ({', '.join(METRICS)})")
   if name == GLYPH_HEIGHT:
      ch = cell(doc)[CELL_HEIGHT]
      if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= ch:
         raise DocumentError(f"glyph_height is 0-{ch} (0: the whole cell)")
      if value == 0:
         doc.data.pop(GLYPH_HEIGHT, None)   # the compiler's default
      else:
         doc.data[GLYPH_HEIGHT] = value
      return
   _check_metric(value, name)
   doc.data[name] = value


def set_cell(doc: Document, width: int, height: int) -> None:
   """!Changes the cell (call inside Document.edit()): every glyph's rows are cut or padded with transparent
   pixels at the right and the bottom (S6b: a glyph_height past the new height is cut to it).
   @param doc     font Document
   @param width   pixels, a multiple of CELL_WIDTH_STEP, 1-MAX_CELL
   @param height  pixels, 1-MAX_CELL
   @return None
   @throws DocumentError when the cell is one the compiler refuses
   """
   fc = compiler()
   if not (0 < width <= fc.MAX_CELL and 0 < height <= fc.MAX_CELL and width % fc.CELL_WIDTH_STEP == 0):
      raise DocumentError(f"a cell is 1-{fc.MAX_CELL} pixels each way, its width a multiple of {fc.CELL_WIDTH_STEP}")
   blank = fc.PIXEL_DIGITS[0]
   for g in (doc.data.get("glyphs") or {}).values():
      rows = [(r + blank * width)[:width] for r in g.get("rows", [])][:height]
      g["rows"] = rows + [blank * width] * (height - len(rows))
   doc.data["cell"] = [width, height]
   if glyph_height(doc) > height:
      doc.data[GLYPH_HEIGHT] = height   # the compiler takes 0-the cell's height
