"""!Screen previews drawn the way the engine draws them, without any UI.

A Screen is a 240x160 RGB image. Text is encoded with a code page and drawn
with that page's font (default: the engine's ASCII page and font; pass the
game's from core.codepage.load() / glyphs()) in the text layer's style
colors; credits pages follow the layout of the credits macro used by the
sequences (heading centred on row 14 in style 1, names from row 16 in
style 0). The result is a guide to layout and fit; it is not
an emulator.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from . import codepage
from .imaging import HALF

if TYPE_CHECKING:
   from .imaging import Rgb

## A GBA color, 5 bits per channel: (r5, g5, b5), 0-31.
Color5 = tuple[int, int, int]
## A font: code -> 8x8 cell (0 empty, 1 ink, 2 shadow), see engine.font_glyphs().
Glyphs = dict[int, list[list[int]]]
## A cell rectangle: (x, y, w, h).
CellRect = tuple[int, int, int, int]

## Screen width, pixels.
WIDTH = 240
## Screen height, pixels.
HEIGHT = 160
## Bytes per Screen pixel (r, g, b).
PIXEL_BYTES = 3
## Pixels per side of a text cell (8x8 glyphs).
CELL = 8
## Columns of a text layer's tile map (32; 30 of them are on screen).
LAYER_COLUMNS = 32
## Mask of one 5-bit channel of a BGR555 color.
CHANNEL_MASK = 0x1F
## Bit position of green in a BGR555 color (red is at 0).
GREEN_SHIFT = 5
## Bit position of blue in a BGR555 color.
BLUE_SHIFT = 10
## Bits a 5-bit channel moves up to become 8 bits.
EXPAND_SHIFT = 3
## Bits a 5-bit channel moves down so its top bits fill the 3 low bits left empty (5 - 3).
REPLICATE_SHIFT = 2
## Font cell value of an ink pixel (font_compiler FG).
GLYPH_INK = 1
## Font cell value of a shadow pixel (font_compiler SHADOW).
GLYPH_SHADOW = 2

## Ink color per text style (text_layer.cpp kStyleInk), 5-bit RGB.
STYLE_INK = [(31, 31, 31), (31, 28, 8), (12, 28, 31), (31, 16, 24)]
## Glyph shadow (text_layer.cpp), 5-bit RGB.
SHADOW = (2, 3, 8)
## Text box fill, 5-bit RGB.
BOX_FILL = (3, 5, 12)
## Text box frame, 5-bit RGB.
BOX_FRAME = (26, 28, 31)
## Backdrop used behind previews, 5-bit RGB.
BACKDROP = (0, 0, 0)
## Row of a credits heading.
CREDITS_HEAD_ROW = 14
## First row of credits names.
CREDITS_NAMES_ROW = 16
## Column the credits text is centred on.
CREDITS_CENTER = 15
## Text box of a cutscene, in cells: (x, y, w, h), the bottom six rows.
DEFAULT_BOX = (0, 14, 30, 6)
## Column of a box's text from the box's left edge (frame column, then one column of padding).
BOX_TEXT_COLUMN = 2


def expand(c5: Sequence[int]) -> Rgb:
   """!A 5-bit color as 8-bit RGB.
   @param c5  (r5, g5, b5)
   @return (r, g, b)
   """
   # Shifts each channel up and repeats its top bits below, so 0 stays 0 and 31 becomes 255.
   return tuple((v << EXPAND_SHIFT) | (v >> REPLICATE_SHIFT) for v in c5)


class Screen:
   """!A 240x160 RGB image to draw previews into.

   @var rgb
   Pixels, 3 bytes each, rows top to bottom.
   """

   def __init__(self, backdrop: Color5 = BACKDROP) -> None:
      """!Creates a screen filled with a color.
      @param backdrop  5-bit RGB
      """
      self.rgb = bytearray(bytes(expand(backdrop)) * (WIDTH * HEIGHT))

   def put(self, x: int, y: int, c5: Color5) -> None:
      """!Sets one pixel, ignoring pixels off the screen.
      @param x   column
      @param y   row
      @param c5  5-bit RGB
      @return None
      """
      if 0 <= x < WIDTH and 0 <= y < HEIGHT:
         o = (y * WIDTH + x) * PIXEL_BYTES
         self.rgb[o:o + PIXEL_BYTES] = bytes(expand(c5))

   def fill(self, x: int, y: int, w: int, h: int, c5: Color5) -> None:
      """!Fills a rectangle.
      @param x   left
      @param y   top
      @param w   width
      @param h   height
      @param c5  5-bit RGB
      @return None
      """
      for yy in range(y, y + h):
         for xx in range(x, x + w):
            self.put(xx, yy, c5)

   def pixel(self, x: int, y: int) -> Rgb:
      """!One pixel.
      @param x  column
      @param y  row
      @return (r, g, b)
      """
      o = (y * WIDTH + x) * PIXEL_BYTES
      return tuple(self.rgb[o:o + PIXEL_BYTES])


## The engine's default font for its default page, loaded on first use.
_font: Glyphs | None = None
## Shown for a character the page lacks (when the page maps it).
FALLBACK_CHAR = "?"


def font() -> Glyphs:
   """!The engine's default font, laid out for its default code page.
   @return dict code -> 8x8 cell (0 empty, 1 ink, 2 shadow)
   """
   global _font
   if _font is None:
      _font = codepage.glyphs(None)
   return _font


def text_codes(text: str, page: Any = None) -> list[int | None]:
   """!The codes a line prints, one per cell; a character the page lacks
   becomes the page's "?" (or an empty cell when it has none).
   @param text  one line (no newline)
   @param page  text_encoder.CodePage, or None for the engine's default page
   @return codes (None: an empty cell)
   """
   page = page if page is not None else codepage.default_page()
   fallback = (page.table.get(FALLBACK_CHAR) or [None])[0]
   return [c if c is not None else fallback for c in codepage.cells(page, text)]


def draw_code(screen: Screen, col: int, row: int, code: int | None, style: int = 0, opaque: bool = False,
              glyphs: Glyphs | None = None) -> None:
   """!Draws one cell by code.
   @param screen  Screen
   @param col     text column (8 pixels)
   @param row     text row
   @param code    glyph code, or None for an empty cell
   @param style   text style 0-3
   @param opaque  fill empty pixels with the box color (text inside a box)
   @param glyphs  the font (default: the engine's)
   @return None
   """
   cell = (glyphs if glyphs is not None else font()).get(code) if code is not None else None
   if cell is None:
      return
   ink = STYLE_INK[style if 0 <= style < len(STYLE_INK) else 0]
   for y in range(CELL):
      for x in range(CELL):
         v = cell[y][x]
         if v or opaque:
            color = ink if v == GLYPH_INK else (SHADOW if v == GLYPH_SHADOW else BOX_FILL)
            screen.put(col * CELL + x, row * CELL + y, color)


def draw_char(screen: Screen, col: int, row: int, ch: str, style: int = 0, opaque: bool = False,
              page: Any = None, glyphs: Glyphs | None = None) -> None:
   """!Draws one character cell.
   @param screen  Screen
   @param col     text column (8 pixels)
   @param row     text row
   @param ch      character
   @param style   text style 0-3
   @param opaque  fill empty pixels with the box color (text inside a box)
   @param page    text_encoder.CodePage, or None for the engine's default page
   @param glyphs  the page's font (default: the engine's)
   @return None
   """
   codes = text_codes(ch, page)
   draw_code(screen, col, row, codes[0] if codes else None, style, opaque, glyphs)


def line_start(anchor: int, align: str, width: int) -> int:
   """!First column of a line (text_layer.cpp line_start()).
   @param anchor  anchor column
   @param align   "left", "center" or "right"
   @param width   characters in the line
   @return the column (never below 0)
   """
   col = anchor
   if align == "center":
      col = anchor - width // HALF   # centred: half the line left of the anchor
   elif align == "right":
      col = anchor - width + 1
   return max(0, col)


def draw_text(screen: Screen, col: int, row: int, text: str, align: str = "left", style: int = 0,
              opaque: bool = False, max_col: int = LAYER_COLUMNS, page: Any = None,
              glyphs: Glyphs | None = None) -> None:
   """!Draws text as text::layer::print() lays it out: each line encoded with
   the code page, aligned on the anchor column by its cells, newlines moving
   down one row.
   @param screen   Screen
   @param col      anchor column
   @param row      first row
   @param text     string
   @param align    "left", "center" or "right"
   @param style    text style 0-3
   @param opaque   box-style background
   @param max_col  columns past this are clipped (a layer is 32 wide)
   @param page     text_encoder.CodePage, or None for the engine's default page
   @param glyphs   the page's font (default: the engine's)
   @return None
   """
   for i, line in enumerate(text.split("\n")):
      codes = text_codes(line, page)
      start = line_start(col, align, len(codes))
      for j, code in enumerate(codes):
         if start + j < max_col:
            draw_code(screen, start + j, row + i, code, style, opaque, glyphs)


def draw_box(screen: Screen, x: int, y: int, w: int, h: int) -> None:
   """!Draws an empty text box (text::layer::open_box()).
   @param screen  Screen
   @param x       left column
   @param y       top row
   @param w       width in cells, at least 3
   @param h       height in cells, at least 3
   @return None
   """
   screen.fill(x * CELL, y * CELL, w * CELL, h * CELL, BOX_FILL)

   # A one-pixel frame along the box's outer edge.
   px, py, pw, ph = x * CELL, y * CELL, w * CELL, h * CELL
   for xx in range(px, px + pw):
      screen.put(xx, py, BOX_FRAME)
      screen.put(xx, py + ph - 1, BOX_FRAME)
   for yy in range(py, py + ph):
      screen.put(px, yy, BOX_FRAME)
      screen.put(px + pw - 1, yy, BOX_FRAME)


def credits_page(heading: str, names: str, backdrop: Color5 = BACKDROP, page: Any = None,
                 glyphs: Glyphs | None = None) -> Screen:
   """!A credits page as the credits macro shows it.
   @param heading   heading text
   @param names     names text (lines)
   @param backdrop  5-bit RGB
   @param page      text_encoder.CodePage, or None for the engine's default page
   @param glyphs    the page's font (default: the engine's)
   @return Screen
   """
   s = Screen(backdrop)
   draw_text(s, CREDITS_CENTER, CREDITS_HEAD_ROW, heading, "center", style=1, page=page, glyphs=glyphs)
   draw_text(s, CREDITS_CENTER, CREDITS_NAMES_ROW, names, "center", style=0, page=page, glyphs=glyphs)
   return s


def text_box(text: str, box: CellRect = DEFAULT_BOX, backdrop: Color5 = BACKDROP, page: Any = None,
             glyphs: Glyphs | None = None) -> Screen:
   """!A text shown in a text box (the cutscene layout: text at column 1, row 0 inside).
   @param text      string
   @param box       (x, y, w, h) in cells
   @param backdrop  5-bit RGB
   @param page      text_encoder.CodePage, or None for the engine's default page
   @param glyphs    the page's font (default: the engine's)
   @return Screen
   """
   s = Screen(backdrop)
   x, y, w, h = box
   draw_box(s, x, y, w, h)
   # Clipped at the frame.
   draw_text(s, x + BOX_TEXT_COLUMN, y + 1, text, "left", 0, opaque=True, max_col=x + w - 1, page=page,
             glyphs=glyphs)
   return s


def text_layer(text: str, col: int = 1, row: int = 1, align: str = "left", style: int = 0,
               backdrop: Color5 = BACKDROP, page: Any = None, glyphs: Glyphs | None = None) -> Screen:
   """!A text printed straight onto a layer.
   @param text      string
   @param col       anchor column
   @param row       first row
   @param align     "left", "center" or "right"
   @param style     text style 0-3
   @param backdrop  5-bit RGB
   @param page      text_encoder.CodePage, or None for the engine's default page
   @param glyphs    the page's font (default: the engine's)
   @return Screen
   """
   s = Screen(backdrop)
   draw_text(s, col, row, text, align, style, page=page, glyphs=glyphs)
   return s
