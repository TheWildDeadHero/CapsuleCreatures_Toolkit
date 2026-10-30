"""!Encoded text drawn in a proportional font the way the engine's text windows draw it [S2] (engine I4,
capsule/text/window.h): a font compiled by the engine's tools/font_compiler.py compile_proportional(), each glyph's
pixels in the window's palette entries (1 ink, 2 shadow, 0 and 3 the background; an entry 0 is never written), the
pen advancing by the glyph's width and the font's letter spacing.

S6b (engine C13a, as the handheld games copy a glyph): a glyph draws only its advance width's columns (at most its
cell) and the font's glyph_height rows (the whole cell when 0, glyph_rows()), so the pixels a cell keeps past them
never show.

screens() splits a text into what the window shows between waits, as window.cpp types it: a newline goes to the
next line (past the last one the window scrolls up a line), a page break (FB) clears it, the scroll control waits
and scrolls a line, a prompt (FA) waits; color controls change the entries; field placeholders show their term's
text, or a stand-in (the placeholder's name in capitals) where the game fills them in. S6b (C13a): Fill (0F) clears
the window and starts again at the text's start, ShiftRight / SkipTo put the pen at a pixel from the text's start,
ShiftDown puts the line at a pixel below the text's start, Clear / ClearTo clear a span at the pen (a glyph's
height of the background), MinSpacing makes every later glyph take at least that many pixels; colours and the least
spacing carry over a Fill, a page break and a scroll as the window keeps them. Fit checks use the engine's own rule
(asset_compiler.measure_lines()); this module only draws. core.text_window is the frame-exact port of the window;
tests hold this one to it. Qt-free: the font viewer, the text table editor's preview and the text box style preview
use it.
"""
from __future__ import annotations

import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import engine
from .imaging import RGBA_BYTES

## An 8-bit RGB colour.
Rgb8 = tuple[int, int, int]
## Base of hexadecimal colour digits.
HEX_BASE = 16
## A compiled proportional font (font_compiler.compile_proportional()'s dict).
CompiledFont = Mapping[str, Any]
## A line of a screen: its items (("g", code) a glyph, ("ink" | "shadow" | "bg", entry) a colour change, ("x", px)
## the pen to a pixel of the line; S6b (C13a): ("y", px) the line's top at a pixel below the text's start, ("clear",
## px) a span cleared at the pen, ("clear_to", px) cleared up to a pixel of the line, ("min", px) the least glyph
## advance, 0 off).
Line = list[tuple[str, int]]
## S6b: the items that set a state the window keeps across lines, Fills, page breaks and scrolls (colours, spacing).
STATE_ITEMS = ("ink", "shadow", "bg", "min")
## Alpha of an opaque pixel.
OPAQUE = 255
## Pixel value of ink in a proportional glyph (font_compiler PIXEL_DIGITS "1").
PIXEL_INK = 1
## Pixel value of shadow.
PIXEL_SHADOW = 2
## Mask of a pixel value in a packed 2bpp byte.
PIXEL_MASK = 0b11
## Bit position of red in a hex colour value (rrggbb).
RED_SHIFT = 16
## Bit position of green in a hex colour value.
GREEN_SHIFT = 8
## Mask of one 8-bit channel.
CHANNEL_MASK = 0xFF
## A neutral preview palette's first entries (0 the backdrop, 1 white, 2 dark grey, 3 light grey, 4 / 5 a frame's
## lines); the rest of the bank is black.
FIRST_COLORS = [(40, 48, 64), (248, 248, 248), (96, 96, 96), (208, 208, 200), (48, 64, 96), (144, 176, 216)]
## The backdrop colour of a picture made without one (the neutral palette's entry 0).
BACKDROP = FIRST_COLORS[0]


def bank_colors() -> int:
   """!Colours of a palette bank (the engine's map_compiler.BANK_COLORS).
   @return entries
   """
   return int(engine.tool("map_compiler").BANK_COLORS)


def default_colors() -> list[Rgb8]:
   """!The neutral preview palette, a whole bank (FIRST_COLORS, then black).
   @return colours, entry 0 first
   """
   return FIRST_COLORS + [(0, 0, 0)] * (bank_colors() - len(FIRST_COLORS))


def font_compiler() -> types.ModuleType:
   """!The engine's font compiler.
   @return module
   """
   return engine.tool("font_compiler")


def encoder() -> types.ModuleType:
   """!The engine's text encoder.
   @return module
   """
   return engine.tool("text_encoder")


class Canvas:
   """!An RGBA picture to draw text into."""

   def __init__(self, width: int, height: int, color: Rgb8 = BACKDROP) -> None:
      """!Creates a picture filled with a colour.
      @param width   pixels
      @param height  pixels
      @param color   8-bit RGB
      """
      ## Width in pixels.
      self.width = width
      ## Height in pixels.
      self.height = height
      ## The pixels, RGBA rows top to bottom.
      self.rgba = bytearray(bytes(color) + bytes((OPAQUE,))) * (width * height)

   def put(self, x: int, y: int, color: Rgb8) -> None:
      """!Sets one pixel (off the picture: nothing).
      @param x      column
      @param y      row
      @param color  8-bit RGB
      @return None
      """
      if 0 <= x < self.width and 0 <= y < self.height:
         o = (y * self.width + x) * RGBA_BYTES
         self.rgba[o:o + RGBA_BYTES] = bytes(color) + bytes((OPAQUE,))

   def fill(self, x: int, y: int, w: int, h: int, color: Rgb8) -> None:
      """!Fills a rectangle (clipped).
      @param x      left
      @param y      top
      @param w      width
      @param h      height
      @param color  8-bit RGB
      @return None
      """
      for yy in range(max(0, y), min(self.height, y + h)):
         for xx in range(max(0, x), min(self.width, x + w)):
            o = (yy * self.width + xx) * RGBA_BYTES
            self.rgba[o:o + RGBA_BYTES] = bytes(color) + bytes((OPAQUE,))

   def pixel(self, x: int, y: int) -> Rgb8:
      """!One pixel's colour.
      @param x  column
      @param y  row
      @return 8-bit RGB
      """
      o = (y * self.width + x) * RGBA_BYTES
      return tuple(self.rgba[o:o + RGBA_BYTES - 1])

   def image(self) -> tuple[int, int, bytearray]:
      """!The picture as (w, h, RGBA).
      @return the image
      """
      return self.width, self.height, self.rgba


@dataclass
class Pens:
   """!The palette entries a window draws in (capsule::text::window::Config ink, shadow, background)."""

   ## Ink entry.
   ink: int = PIXEL_INK
   ## Shadow entry.
   shadow: int = PIXEL_SHADOW
   ## Background entry (empty and fill pixels).
   background: int = 0
   ## The bank's colours, entry 0 first.
   colors: list[Rgb8] = field(default_factory=default_colors)

   def color(self, entry: int) -> Rgb8:
      """!An entry's colour.
      @param entry  palette entry
      @return 8-bit RGB (black past the bank)
      """
      return self.colors[entry] if 0 <= entry < len(self.colors) else (0, 0, 0)


## Entries of the neutral palette a preview without a style draws in: dark grey ink, light grey shadow on white.
PREVIEW_INK, PREVIEW_SHADOW, PREVIEW_BACKGROUND = 2, 3, 1


def preview_pens() -> Pens:
   """!The pens of a preview without a style (the neutral palette: dark ink, light shadow on white).
   @return Pens
   """
   return Pens(PREVIEW_INK, PREVIEW_SHADOW, PREVIEW_BACKGROUND)


def advance(font: CompiledFont, code: int) -> int:
   """!How far the pen moves after a glyph (its width and the letter spacing; 0 for a code the font lacks).
   @param font  compiled font
   @param code  the code
   @return pixels
   """
   first, widths = font["first"], font["widths"]
   if not first <= code < first + len(widths):
      return 0
   return widths[code - first] + font["letter_spacing"]


def glyph_width(font: CompiledFont, code: int) -> int:
   """!S6b (C13a): a glyph's width without the letter spacing (window.cpp glyph_width()).
   @param font  compiled font
   @param code  the code
   @return pixels (0 for a code the font leaves out)
   """
   first, widths = font["first"], font["widths"]
   return widths[code - first] if first <= code < first + len(widths) else 0


def glyph_rows(font: CompiledFont) -> int:
   """!S6b (C13a): the rows of a glyph a window draws (window.cpp glyph_rows(): the font's glyph_height, the cell's
   height when it is 0 or larger).
   @param font  compiled font
   @return rows
   """
   ch = font["cell"][1]
   h = int(font.get("glyph_height", 0) or 0)
   return h if 0 < h < ch else ch


def pen_after(font: CompiledFont, code: int, min_spacing: int) -> int:
   """!S6b (C13a): pixels the pen moves after a glyph (window.cpp pen_after_glyph(): its advance, or with MinSpacing
   its width and then at least min_spacing in all, the letter spacing left out).
   @param font         compiled font
   @param code         the code
   @param min_spacing  the least advance, 0 when off
   @return pixels
   """
   if min_spacing == 0:
      return advance(font, code)
   return max(glyph_width(font, code), min_spacing)


def glyph_pixels(font: CompiledFont, code: int) -> list[list[int]]:
   """!A glyph's pixel values (unpacked from the 2bpp rows: pixel 0 in bits 1:0), the whole cell.
   @param font  compiled font
   @param code  the code
   @return rows of cell-width values ([] for a code the font lacks)
   """
   fc = font_compiler()
   first, glyphs = font["first"], font["glyphs"]
   if not first <= code < first + len(glyphs):
      return []
   cw, ch = font["cell"]
   row_bytes = cw // fc.PIXELS_PER_BYTE
   packed = glyphs[code - first]
   out = []
   for r in range(ch):
      row = []
      for x in range(cw):
         byte = packed[r * row_bytes + x // fc.PIXELS_PER_BYTE]
         row.append(byte >> ((x % fc.PIXELS_PER_BYTE) * fc.BITS_PER_PIXEL) & PIXEL_MASK)
      out.append(row)
   return out


def drawn_pixels(font: CompiledFont, code: int) -> list[list[int]]:
   """!S6b (C13a): the part of a glyph a window draws: its width's columns (at most the cell's) of its glyph_rows()
   rows (the handheld games' glyph clip).
   @param font  compiled font
   @param code  the code
   @return rows of values ([] for a code the font lacks)
   """
   cols = min(glyph_width(font, code), font["cell"][0])
   return [row[:cols] for row in glyph_pixels(font, code)[:glyph_rows(font)]]


def glyph_entry(v: int, ink: int, shadow: int, background: int) -> int:
   """!S6b (C13a): the entry a glyph pixel takes (window.cpp glyph_entry(): 1 ink, 2 shadow, 0 and 3 the background).
   @param v           the 2bpp value
   @param ink         ink entry
   @param shadow      shadow entry
   @param background  background entry
   @return the entry (0: not written)
   """
   return ink if v == PIXEL_INK else (shadow if v == PIXEL_SHADOW else background)


def draw_glyph(canvas: Canvas, font: CompiledFont, code: int, x: int, y: int, pens: Pens) -> None:
   """!Draws one glyph (window.cpp draw_glyph(); S6b, C13a: its width's columns and glyph_rows() rows, 0 and 3 pixels
   in the background entry, entries 0 not written).
   @param canvas  the picture
   @param font    compiled font
   @param code    the code
   @param x       left
   @param y       top
   @param pens    the entries and colours
   @return None
   """
   for r, row in enumerate(drawn_pixels(font, code)):
      for c, v in enumerate(row):
         entry = glyph_entry(v, pens.ink, pens.shadow, pens.background)
         if entry != 0:
            canvas.put(x + c, y + r, pens.color(entry))


def stand_in(name: str, page: Any) -> list[int]:
   """!The codes a preview shows for a placeholder the game fills in: its name in capitals (the part before a ':'),
   the characters the page lacks left out.
   @param name  the placeholder's name
   @param page  the code page
   @return glyph codes
   """
   out = []
   for ch in name.split(":")[0].upper():
      codes = page.table.get(ch)
      if codes:
         out += codes
   return out


def carried(shown: Sequence[Line]) -> Line:
   """!S6b: the state items of lines (STATE_ITEMS, in order): what the window still draws with after they are gone
   (a Fill, a page break or a scroll clears their pixels, not the colours or the least spacing).
   @param shown  the lines
   @return the items
   """
   return [item for line in shown for item in line if item[0] in STATE_ITEMS]


def screens(codes: Sequence[int], lines: int, placeholders: Mapping[int, list[int]] | None = None) -> list[list[Line]]:
   """!What a window shows of a text each time it waits (and at the end), as window.cpp types it.
   @param codes         the codes (ending with CODE_END)
   @param lines         lines the window shows
   @param placeholders  a placeholder's argument byte -> the codes shown for it, or None (nothing)
   @return the screens, each `lines` lines at most
   """
   te = encoder()
   lines = max(1, lines)
   control = {code: name for name, (code, _w) in te.CONTROL_CODES.items()}
   out: list[list[Line]] = []
   shown: list[Line] = [[]]

   def snapshot() -> None:
      """!Keeps what the window shows now."""
      out.append([list(line) for line in shown])

   def next_line() -> None:
      """!The next line; a full window scrolls up one first."""
      if len(shown) == lines:
         snapshot()   # the scroll shows what was there first
         kept = carried(shown[:1])
         del shown[0]
         shown[0][:0] = kept   # the scrolled-off line's colours still hold
      shown.append([])

   def restart() -> None:
      """!S6b: the window cleared, the text's start again (a page break, Fill); its colours and spacing kept."""
      shown[:] = [carried(shown)]

   i = 0
   while i < len(codes) and codes[i] != te.CODE_END:
      c = codes[i]
      if c == te.CODE_NEWLINE:
         next_line()
         i += 1
         continue
      if c == te.CODE_PAGE_BREAK:
         snapshot()
         restart()
         i += 1
         continue
      if c == te.CODE_PROMPT:
         snapshot()
         i += 1
         continue
      if c == te.CODE_PLACEHOLDER and i + 1 < len(codes):
         shown[-1] += [("g", g) for g in (placeholders or {}).get(codes[i + 1], [])]
         i += te.PLACEHOLDER_CODES
         continue
      if c == te.CODE_CONTROL:
         n = te.control_length(list(codes), i)
         name = control.get(codes[i + 1]) if i + 1 < len(codes) else None
         args = list(codes[i + te.CONTROL_HEAD:i + n])
         if name == "fill":
            restart()   # S6b (C13a): FillWindowPixelBuffer, the pen back to the text's start
         else:
            _control(name, args, shown, snapshot, next_line)
         i += n
         continue
      shown[-1].append(("g", c))
      i += 1
   snapshot()
   return out


## S6b (C13a): the controls that put one item on the line, by name: the item's kind (its argument is the item's value).
LINE_CONTROLS = {"shift_right": "x", "skip_to": "x", "shift_down": "y", "clear": "clear", "clear_to": "clear_to",
                 "min_spacing": "min"}


def _control(name: str | None, args: list[int], shown: list[Line], snapshot: Any, next_line: Any) -> None:
   """!A control's effect on the screens (the ones window.cpp acts on; every other is skipped).
   @param name       the control (text_encoder.CONTROL_CODES), or None
   @param args       its argument bytes
   @param shown      the lines shown now
   @param snapshot   keeps a screen
   @param next_line  goes to the next line
   @return None
   """
   if name in ("color", "highlight", "shadow") and args:
      shown[-1].append(({"color": "ink", "highlight": "bg", "shadow": "shadow"}[name], args[0]))
   elif name == "colors" and len(args) == len(("ink", "bg", "shadow")):
      shown[-1] += [("ink", args[0]), ("bg", args[1]), ("shadow", args[-1])]
   elif name in LINE_CONTROLS and args:
      shown[-1].append((LINE_CONTROLS[name], args[0]))
   elif name == "scroll":
      snapshot()
      next_line()
   elif name == "wait_button":
      snapshot()


@dataclass
class _Pen:
   """!S6b: where draw_lines() is in a screen (window.cpp's pen_x, line_y and min_spacing)."""

   ## Pen, pixels from the text's start.
   x: int = 0
   ## The line's top, pixels from the text's start.
   y: int = 0
   ## The least glyph advance (0: off).
   min_spacing: int = 0


def _walk(font: CompiledFont, screen: Sequence[Line], glyph: Any, clear: Any, pens: Pens | None = None) -> None:
   """!S6b: a screen's lines walked as window.cpp types them: glyphs at the pen, the pen and line moved by the
   controls (relative to the text's start), spans cleared.
   @param font    compiled font
   @param screen  the lines
   @param glyph   callable(code, x, y, pens) for each glyph
   @param clear   callable(x, y, width, pens) for each span cleared (a glyph's height)
   @param pens    the entries the colour items change, or None
   @return None
   """
   pen = _Pen()
   for n, line in enumerate(screen):
      if n:
         pen.x, pen.y = 0, pen.y + font["line_height"]
      for kind, v in line:
         if kind == "g":
            glyph(v, pen.x, pen.y, pens)
            pen.x += pen_after(font, v, pen.min_spacing)
            gap = pen.min_spacing - glyph_width(font, v)
            if pen.min_spacing and gap > 0:
               clear(pen.x - gap, pen.y, gap, pens)   # MinSpacing: the rest of the least advance is cleared
         elif kind == "x":
            pen.x = v
         elif kind == "y":
            pen.y = v
         elif kind == "clear":
            if v > 0:
               clear(pen.x, pen.y, v, pens)
               pen.x += v
         elif kind == "clear_to":
            if v > pen.x:
               clear(pen.x, pen.y, v - pen.x, pens)
               pen.x = v
         elif kind == "min":
            pen.min_spacing = v
         elif pens is not None:
            setattr(pens, {"ink": "ink", "shadow": "shadow", "bg": "background"}[kind], v)


def draw_lines(canvas: Canvas, font: CompiledFont, screen: Sequence[Line], x: int, y: int, pens: Pens,
               left: int = 0, top: int = 0) -> None:
   """!Draws a screen's lines (the window's rectangle already filled).
   @param canvas  the picture
   @param font    compiled font
   @param screen  the lines (screens()' items)
   @param x       the window's left, pixels
   @param y       its top
   @param pens    the starting entries and colours (changed by colour items)
   @param left    pixels from its left edge to the text's start
   @param top     pixels from its top to the first line's top
   @return None
   """
   def glyph(code: int, gx: int, gy: int, p: Pens) -> None:
      """!One glyph at the pen.
      @param code  the code
      @param gx    pen, from the text's start
      @param gy    line top, from the text's start
      @param p     the entries
      """
      draw_glyph(canvas, font, code, x + left + gx, y + top + gy, p)

   def clear(cx: int, cy: int, width: int, p: Pens) -> None:
      """!A span in the background entry (ClearTextSpan: nothing when the entry is 0).
      @param cx     left, from the text's start
      @param cy     line top, from the text's start
      @param width  pixels
      @param p      the entries
      """
      if p.background != 0:
         canvas.fill(x + left + cx, y + top + cy, width, glyph_rows(font), p.color(p.background))

   _walk(font, screen, glyph, clear, Pens(pens.ink, pens.shadow, pens.background, pens.colors))


def line_pixels(font: CompiledFont, line: Line) -> int:
   """!How wide a screen line is drawn (for sizing a preview; fit checks use the engine's measure_lines()).
   @param font  compiled font
   @param line  its items
   @return pixels
   """
   widest = [0]

   def glyph(code: int, gx: int, _gy: int, _p: Pens | None) -> None:
      """!A glyph's right edge.
      @param code  the code
      @param gx    pen
      """
      widest[0] = max(widest[0], gx + advance(font, code))

   def clear(cx: int, _cy: int, width: int, _p: Pens | None) -> None:
      """!A span's right edge.
      @param cx     left
      @param width  pixels
      """
      widest[0] = max(widest[0], cx + width)

   _walk(font, [line], glyph, clear)
   return widest[0]


def screen_height(font: CompiledFont, screen: Sequence[Line]) -> int:
   """!S6b: how far down a screen's lines reach (for sizing a preview; ShiftDown may move a line).
   @param font    compiled font
   @param screen  the lines
   @return pixels
   """
   lowest = [len(screen) * font["line_height"]]

   def glyph(_code: int, _gx: int, gy: int, _p: Pens | None) -> None:
      """!A glyph's line bottom.
      @param gy  line top
      """
      lowest[0] = max(lowest[0], gy + font["line_height"])

   _walk(font, screen, glyph, lambda *_a: None)
   return lowest[0]


def render_text(font: CompiledFont, codes: Sequence[int], pens: Pens, margin: int = 0,
                placeholders: Mapping[int, list[int]] | None = None) -> tuple[int, int, bytearray]:
   """!A text drawn on one picture, every line of it (newlines and page breaks start lines; for a font preview).
   @param font          compiled font
   @param codes         the codes
   @param pens          entries and colours (the picture is the background colour)
   @param margin        pixels around the text
   @param placeholders  a placeholder's argument byte -> its codes, or None
   @return (w, h, RGBA)
   """
   te = encoder()
   flat = [te.CODE_NEWLINE if c in (te.CODE_PAGE_BREAK, te.CODE_PROMPT) else c for c in codes]
   lines = screens(flat, len(flat) + 1, placeholders)[-1] if flat else [[]]
   width = max([line_pixels(font, line) for line in lines] + [1]) + margin + margin
   height = screen_height(font, lines) + margin + margin
   canvas = Canvas(width, height, pens.color(pens.background))
   draw_lines(canvas, font, lines, margin, margin, pens)
   return canvas.image()


def parse_color(text: str) -> Rgb8:
   """!A colour written as a hex colour ("#" and rrggbb).
   @param text  the colour
   @return 8-bit RGB
   @throws ValueError when it is not one
   """
   hex_digits = text.strip().lstrip("#")
   if len(hex_digits) != len("rrggbb"):
      raise ValueError(f"{text!r} is not a colour (#rrggbb)")
   value = int(hex_digits, HEX_BASE)
   return value >> RED_SHIFT & CHANNEL_MASK, value >> GREEN_SHIFT & CHANNEL_MASK, value & CHANNEL_MASK


def color_text(color: Sequence[int]) -> str:
   """!A colour as a hex colour ("#" and rrggbb).
   @param color  8-bit RGB
   @return text
   """
   return "#" + "".join(f"{v:02x}" for v in color[:len("rgb")])
