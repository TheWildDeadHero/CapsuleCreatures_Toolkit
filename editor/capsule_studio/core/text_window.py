"""!A text window typed frame by frame as the engine's capsule/text/window.cpp types it [S4] (engine C10): the
preview of a text box style follows the style's typing ("interval": a glyph every frames_per_char frames, Accept /
Back held types the rest up to the next pause; "counter": a frame-counted printer, every code read restarts a
counter of char_delay frames, lead_frames before the first code, a Pause n waits n frames and one more, a scroll ends
one frame after its last row) and speed-up ("rest", "per_frame": a press while the counter runs ends it and from then
on held keeps it at 0, "none").

Window is a port of window.cpp's state machine (open(), print(), update(), busy(), waiting(): the same fields, the
same order of reads in a frame) over a pixel buffer of palette entries; the constants come from window.h (the typing
and speed-up values) and window.cpp (the arrow's blink, the reads per frame), read from the engine. run() types a
text to its end with a key policy (KEY_POLICIES: no keys, a press at each wait, Accept held), keeping every frame's
pixels and the frames where waits begin: the style panel's frame slider and `text-box timeline` read it.

S6b (engine C13a, as the handheld games' printer): a glyph draws its width's columns and the font's glyph_height
rows (0 and 3 pixels in the background entry, entries 0 never written); Fill (0F) fills the window and starts again
at the text's start; Clear n / ClearTo n clear a glyph's height at the pen (a positive one types as a glyph does:
it ends a typed frame); SkipTo n, ShiftRight n and ShiftDown n count from the text's start (print(): Config left /
top; print_at(): its x / y); MinSpacing n makes every later glyph advance at least n pixels. line_width() is
window::line_width() (GetStringWidth's rule for those controls), the width menus fit columns with.

S6b (engine C13c): a window holds no pixels of its own; its owner attaches width x height tiles (TileBuffer<W, H>, a
TilePool piece or a screen arena block). storage() says how many tiles and bytes one window needs.

S5 (engine N3): the arrow image (Config arrow_kind kArrowImage: an 8-pixel-wide image stepping its rows at the pen
while a wait shows it, step_image_arrow() / erase_image_arrow()) and the menu printing calls print_at() (a text at a
pixel, nothing typed, waits skipped), fill() and set_colors() that core.menu_styles draws menus with.

Qt-free; core.text_boxes.preview() draws a Window's pixels inside the box.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import engine, text_render

## A compiled proportional font (font_compiler.compile_proportional()'s dict).
CompiledFont = Mapping[str, Any]
## A window's settings: text::window::Config members by name (typing and speedup as their numbers; S5: the arrow
## image's arrow_rows / arrow_offsets as lists of numbers).
Settings = Mapping[str, Any]
## The engine source of the window printer (its private constants).
WINDOW_SOURCE = "src/text/window.cpp"
## A constant in window.cpp: `constexpr TYPE name = value;`.
CONSTANT = re.compile(r"\bconstexpr\s+[\w:]+\s+(?P<name>k\w+)\s*=\s*(?P<value>\d+)\s*;")
## window.cpp's constants when the source cannot be read: frames the arrow shows and hides, its phases, the most
## codes a frame reads.
DEFAULT_SOURCE_CONSTANTS = {"kArrowBlinkFrames": 16, "kBlinkPhases": 2, "kMaxCodesPerFrame": 4096, "kNibbleBits": 4,
                            "kNibbleMask": 15}
## window.h's typing and speed-up values when the header cannot be read.
DEFAULT_HEADER_CONSTANTS = {"kTypingInterval": 0, "kTypingCounter": 1, "kSpeedupRest": 0, "kSpeedupPerFrame": 1,
                            "kSpeedupNone": 2, "kArrowGlyph": 0, "kArrowImage": 1, "kArrowImageWidth": 8}
## Pixels per tile side (window.cpp kTileSide).
TILE_SIDE = 8
## Codes of an escape before its arguments (encode.h kEscapeHead).
ESCAPE_HEAD = 2
## Control::Colors: where its background and shadow entries are (window.cpp kColorsBackgroundAt, kColorsShadowAt).
COLORS_BACKGROUND_AT, COLORS_SHADOW_AT = ESCAPE_HEAD + 1, ESCAPE_HEAD + 2
## The pauses a window waits in (window::Pause).
PAUSE_NONE, PAUSE_PROMPT, PAUSE_PAGE, PAUSE_SCROLL, PAUSE_SCROLLING, PAUSE_BUTTON, PAUSE_FRAMES = range(7)
## The pauses that wait for a button (window::waiting()).
BUTTON_PAUSES = (PAUSE_PROMPT, PAUSE_PAGE, PAUSE_SCROLL, PAUSE_BUTTON)
## The pauses that blink the arrow (wait_with_arrow()).
ARROW_PAUSES = (PAUSE_PROMPT, PAUSE_PAGE, PAUSE_SCROLL)
## Key policies of run(): no keys; a press at each wait (PRESS_AFTER frames after it begins); Accept held all along
## (a press while the text types, and at each wait).
KEY_POLICIES = ("none", "advance", "hold")
## Frames a run() waits at a wait before its press.
PRESS_AFTER = 30
## Most frames run() types (a minute at 60 frames a second).
MAX_FRAMES = 3600
## Frames held before a hold policy presses again at a wait (the key is let go one frame first).
RELEASE_FRAMES = 1
## S5: the members print_at() keeps and puts back (the text being typed: its codes, the next one, an expansion's
## way back, the pause).
TEXT_STATE = ("src", "i", "resume", "pause")
## S6b: window.h's tile storage constants when the header cannot be read (kMaxTiles, kWordsPerTile).
DEFAULT_STORAGE_CONSTANTS = {"kMaxTiles": 256, "kWordsPerTile": 8}
## S6b: bytes of one 32-bit word of a tile (window.h kBytesPerTile = kWordsPerTile * sizeof(uint32_t)).
WORD_BYTES = 4


def _engine_constants(path: str, defaults: Mapping[str, int]) -> dict[str, int]:
   """!Integer constants of an engine file, the defaults for those it lacks.
   @param path      path below the engine's root
   @param defaults  name -> value
   @return name -> value
   """
   out = dict(defaults)
   try:
      text = (engine.root() / path).read_text(encoding="utf-8")
   except (OSError, engine.EngineNotFound):
      return out
   for m in CONSTANT.finditer(text):
      if m.group("name") in defaults:
         out[m.group("name")] = int(m.group("value"))
   return out


def source_constants() -> dict[str, int]:
   """!window.cpp's arrow blink and read limit (S5: and the 4bpp pixel's bits and mask of the arrow image's rows).
   @return kArrowBlinkFrames, kBlinkPhases, kMaxCodesPerFrame, kNibbleBits, kNibbleMask
   """
   return _engine_constants(WINDOW_SOURCE, DEFAULT_SOURCE_CONSTANTS)


def header_constants() -> dict[str, int]:
   """!window.h's typing and speed-up values (S5: and the arrow kinds, the arrow image's width).
   @return kTypingInterval, kTypingCounter, kSpeedupRest, kSpeedupPerFrame, kSpeedupNone, kArrowGlyph, kArrowImage,
           kArrowImageWidth
   """
   return _engine_constants("include/capsule/text/window.h", DEFAULT_HEADER_CONSTANTS)


def storage_constants() -> dict[str, int]:
   """!S6b (C13c): window.h's tile storage constants.
   @return kMaxTiles, kWordsPerTile
   """
   return _engine_constants("include/capsule/text/window.h", DEFAULT_STORAGE_CONSTANTS)


@dataclass(frozen=True)
class Storage:
   """!S6b (C13c): the tile storage a window of width x height cells needs from its owner (window::attach())."""

   ## Cells across.
   width: int
   ## Cells down.
   height: int
   ## Tiles (one a cell).
   tiles: int
   ## Bytes (window::tile_words() words of 4 bytes).
   size_bytes: int
   ## The most tiles one window covers (window::kMaxTiles).
   max_tiles: int

   def fits(self) -> bool:
      """!Whether one window may cover it (TileBuffer's static_assert: 1 to kMaxTiles cells).
      @return True when it may
      """
      return 0 < self.tiles <= self.max_tiles

   def cpp_type(self) -> str:
      """!The engine's static buffer type of this size.
      @return `capsule::text::window::TileBuffer<W, H>`
      """
      return f"capsule::text::window::TileBuffer<{self.width}, {self.height}>"

   def text(self) -> str:
      """!One line for panels and the command line.
      @return e.g. "40 tiles, 1280 bytes (TileBuffer<20, 2>)"
      """
      return f"{self.tiles} tiles, {self.size_bytes} bytes (TileBuffer<{self.width}, {self.height}>)"


def storage(width: int, height: int) -> Storage:
   """!S6b (C13c): the storage a window of width x height cells needs (window::tile_words(), kBytesPerTile a tile).
   @param width   cells across
   @param height  cells down
   @return Storage
   """
   k = storage_constants()
   tiles = max(width, 0) * max(height, 0)
   return Storage(width, height, tiles, tiles * k["kWordsPerTile"] * WORD_BYTES, k["kMaxTiles"])


def _controls() -> dict[str, tuple[int, int]]:
   """!The generic controls: name -> (code, argument bytes) (text_encoder.CONTROL_CODES, encode.h Control).
   @return controls
   """
   te = text_render.encoder()
   return {name: (code, sum(widths)) for name, (code, widths) in te.CONTROL_CODES.items()}


def line_width(font: CompiledFont, codes: Sequence[int],
               placeholders: Mapping[int, Sequence[int]] | None = None) -> int:
   """!S6b (C13a): a text's first line in pixels as window::line_width() counts it (pret's GetStringWidth): field
   placeholders expanded; Clear n adds n, SkipTo n sets the width to n, ClearTo n raises it to n, MinSpacing n makes
   every later glyph count at least n (without the letter spacing); other controls take none.
   @param font          compiled font
   @param codes         the codes (an end code, newline or page break ends the line)
   @param placeholders  a field placeholder's argument byte -> the codes it shows, or None (nothing)
   @return pixels
   """
   te = text_render.encoder()
   names = {code: name for name, (code, _n) in _controls().items()}
   return _width_of(font, list(codes) + [te.CODE_END], dict(placeholders or {}), names, [0])


def _width_of(font: CompiledFont, codes: list[int], placeholders: Mapping[int, Sequence[int]],
              names: Mapping[int, str], min_spacing: list[int]) -> int:
   """!line_width()'s walk (window.cpp width_of()).
   @param font          compiled font
   @param codes         the codes, ending with the end code
   @param placeholders  field placeholder texts
   @param names         control code -> its name
   @param min_spacing   [the least glyph advance so far] (MinSpacing in the text changes it)
   @return pixels
   """
   te = text_render.encoder()
   first, count = font["first"], len(font["widths"])
   w, i = 0, 0
   while i < len(codes) and codes[i] not in (te.CODE_END, te.CODE_NEWLINE, te.CODE_PAGE_BREAK):
      c = codes[i]
      nxt = codes[i + 1] if i + 1 < len(codes) else te.CODE_END
      if c == te.CODE_PLACEHOLDER and nxt != te.CODE_END and te.FIRST_FIELD_ARG <= nxt <= te.LAST_FIELD_ARG:
         w += _width_of(font, list(placeholders.get(nxt, [])) + [te.CODE_END], placeholders, names, min_spacing)
      if c == te.CODE_CONTROL and nxt != te.CODE_END:
         a = codes[i + ESCAPE_HEAD] if i + ESCAPE_HEAD < len(codes) else te.CODE_END
         name = names.get(nxt)
         if name == "clear":
            w += a
         elif name == "skip_to":
            w = a
         elif name == "clear_to":
            w = max(a, w)
         elif name == "min_spacing":
            min_spacing[0] = a
      if c in (te.CODE_CONTROL, te.CODE_PLACEHOLDER):
         i += _escape_length_at(codes, i)
         continue
      if first <= c < first + count:
         glyph = font["widths"][c - first]
         ms = min_spacing[0]
         # MinSpacing: a glyph takes at least that many pixels (and no letter spacing), as the printer draws it
         w += max(glyph, ms) if ms > 0 else glyph + font["letter_spacing"]
      i += 1
   return w


def _escape_length_at(codes: Sequence[int], i: int) -> int:
   """!Codes the escape at codes[i] takes (encode.h escape_length()).
   @param codes  the codes
   @param i      the escape's index
   @return at least 1
   """
   te = text_render.encoder()
   nxt = codes[i + 1] if i + 1 < len(codes) else te.CODE_END
   if nxt == te.CODE_END:
      return 1
   args = {code: n for code, n in _controls().values()}
   if codes[i] != te.CODE_CONTROL or nxt not in args:
      return ESCAPE_HEAD
   n = ESCAPE_HEAD + args[nxt]
   for k in range(ESCAPE_HEAD, n):
      if i + k >= len(codes) or codes[i + k] == te.CODE_END:
         return k   # cut short: stop at the end code
   return n


def advance_in(font: CompiledFont, code: int) -> int:
   """!A glyph's advance in a font (window.cpp advance_in()).
   @param font  compiled font
   @param code  the code
   @return pixels (0 for a code the font leaves out)
   """
   return text_render.advance(font, code)


class Window:
   """!One text window (window::Window): its pixels and its typing state, advanced one frame per update()."""

   def __init__(self, settings: Settings, font: CompiledFont, fonts: Mapping[int, CompiledFont] | None = None,
                placeholders: Mapping[int, Sequence[int]] | None = None) -> None:
      """!Opens a window (window::open()): its pixels cleared to the background entry.
      @param settings      the window's settings (Config members; typing / speedup as numbers)
      @param font          the window's font
      @param fonts         the fonts Control::Font n selects, or None
      @param placeholders  a field placeholder's argument byte -> the codes it shows, or None (nothing)
      """
      te = text_render.encoder()
      hc = header_constants()
      sc = source_constants()
      ## The settings.
      self.c = dict(settings)
      ## The window's font.
      self.font = font
      ## The fonts of the Font control.
      self.fonts = dict(fonts or {})
      ## What field placeholders show.
      self.placeholders = dict(placeholders or {})
      ## The engine's codes (text_encoder).
      self.te = te
      ## Control codes by name.
      self.control_codes = {name: code for name, (code, _n) in _controls().items()}
      ## Argument bytes per control code.
      self.control_args = {code: n for code, n in _controls().values()}
      ## window.h's typing / speed-up values.
      self.k = hc
      ## Frames the arrow shows (and hides).
      self.blink_frames = sc["kArrowBlinkFrames"]
      ## Arrow phases (shown, hidden).
      self.blink_phases = sc["kBlinkPhases"]
      ## Most codes one frame reads.
      self.max_reads = sc["kMaxCodesPerFrame"]
      ## Bits of one pixel in an arrow image's row word.
      self.nibble_bits = sc["kNibbleBits"]
      ## One pixel's mask in it.
      self.nibble_mask = sc["kNibbleMask"]
      cells_w, cells_h = max(0, self.c.get("width", 0)), max(0, self.c.get("height", 0))
      max_tiles = storage_constants()["kMaxTiles"]
      if cells_w * cells_h > max_tiles:
         cells_h = max_tiles // max(cells_w, 1)   # window::open(): the rows that fit kMaxTiles
      ## S6b (C13c): the tile storage its owner gives it (width x height cells).
      self.store = storage(cells_w, cells_h)
      ## Pixel width.
      self.width = cells_w * TILE_SIDE
      ## Pixel height.
      self.height = cells_h * TILE_SIDE
      ## The pixels' palette entries, rows top to bottom.
      self.pixels = bytearray(self.width * self.height)
      ## Open (a font and a size).
      self.open = font is not None and self.width > 0 and self.height > 0
      ## The codes typed (the text, or a placeholder's expansion), or None when done.
      self.src = None
      ## Index of the next code in src.
      self.i = 0
      ## Where the text goes on after a placeholder's expansion: (codes, index), or None.
      self.resume = None
      ## Pen, pixels from the left edge.
      self.pen_x = 0
      ## Top of the current line.
      self.line_y = 0
      ## Line index.
      self.line = 0
      ## Current ink entry.
      self.ink = self.c.get("ink", text_render.PIXEL_INK)
      ## Current shadow entry.
      self.shadow = self.c.get("shadow", text_render.PIXEL_SHADOW)
      ## Current background entry.
      self.background = self.c.get("background", 0)
      ## What it waits for.
      self.pause = PAUSE_NONE
      ## Pause frames left.
      self.frames = 0
      ## Frames to the next glyph (counter typing: the counter).
      self.timer = 0
      ## Lead frames left.
      self.lead = 0
      ## A press sped this text up (per_frame).
      self.sped_up = False
      ## The font glyphs come from.
      self.glyphs = font
      ## Pixels a scroll moved so far.
      self.scrolled = 0
      ## Arrow blink counter.
      self.blink = 0
      ## The arrow is drawn.
      self.arrow_shown = False
      ## S5 (N3): the arrow image's next step.
      self.arrow_step = 0
      ## S5 (N3): frames left before its next step.
      self.arrow_wait = 0
      ## Printed at once.
      self.instant = False
      ## S6b (C13a): the text's start (print(): Config left; print_at(): its x).
      self.start_x = self.c.get("left", 0)
      ## S6b (C13a): its top (print(): Config top; print_at(): its y).
      self.start_y = self.c.get("top", 0)
      ## S6b (C13a): Control::MinSpacing's least advance, 0 when off (each text starts off).
      self.min_spacing = 0
      if self.open:
         self._clear_all()

   # -- pixels (window.cpp put_pixel(), fill_row(), copy_row(), fill_rect()) ----------------------------------------

   def _put(self, x: int, y: int, entry: int) -> None:
      """!One pixel, clipped to the window.
      @param x      column
      @param y      row
      @param entry  palette entry
      @return None
      """
      if 0 <= x < self.width and 0 <= y < self.height:
         self.pixels[y * self.width + x] = entry & text_render.CHANNEL_MASK

   def _fill_row(self, y: int, entry: int) -> None:
      """!One pixel row of one entry.
      @param y      row
      @param entry  palette entry
      @return None
      """
      self.pixels[y * self.width:(y + 1) * self.width] = bytes((entry,)) * self.width

   def _copy_row(self, dst: int, src: int) -> None:
      """!One pixel row over another.
      @param dst  row written
      @param src  row read
      @return None
      """
      self.pixels[dst * self.width:(dst + 1) * self.width] = self.pixels[src * self.width:(src + 1) * self.width]

   def _fill_rect(self, x: int, y: int, w: int, h: int, entry: int) -> None:
      """!A rectangle of one entry (clipped).
      @param x      left
      @param y      top
      @param w      width
      @param h      height
      @param entry  palette entry
      @return None
      """
      for yy in range(y, y + h):
         for xx in range(x, x + w):
            self._put(xx, yy, entry)

   def _draw_glyph(self, code: int, x: int, y: int) -> None:
      """!A glyph of the current font in the current entries (S6b, C13a, window.cpp glyph_canvas(): its width's
      columns and glyph_rows() rows, clipped to the window; 0 and 3 pixels the background; entries 0 not written).
      @param code  the code
      @param x     left
      @param y     top
      @return None
      """
      for r, row in enumerate(text_render.drawn_pixels(self.glyphs, code)):
         for col, v in enumerate(row):
            entry = text_render.glyph_entry(v, self.ink, self.shadow, self.background)
            if entry != 0:
               self._put(x + col, y + r, entry)

   def _clear_span(self, width: int) -> None:
      """!S6b (C13a, window.cpp clear_span(): ClearTextSpan): a glyph's height of pixels at the pen in the background
      entry (nothing when it is 0).
      @param width  pixels
      @return None
      """
      if self.background != 0:
         self._fill_rect(self.pen_x, self.line_y, width, text_render.glyph_rows(self.glyphs), self.background)

   def _pen_after_glyph(self, code: int) -> None:
      """!S6b (C13a, window.cpp pen_after_glyph()): the pen after a glyph: its advance, or with MinSpacing its width
      and at least min_spacing in all (the rest cleared).
      @param code  the glyph's code
      @return None
      """
      if self.min_spacing == 0:
         self.pen_x += advance_in(self.glyphs, code)
         return
      width = text_render.glyph_width(self.glyphs, code)
      self.pen_x += width
      gap = self.min_spacing - width
      if gap > 0:
         self._clear_span(gap)
         self.pen_x += gap

   def _clear_all(self) -> None:
      """!Every pixel the background; the first line.
      @return None
      """
      self.pixels[:] = bytes((self.background & text_render.CHANNEL_MASK,)) * len(self.pixels)
      self.pen_x = self.start_x   # C13a: the text's start (a page break: currentX = x, currentY = y)
      self.line_y = self.start_y
      self.line = 0
      self.arrow_shown = False

   def _show_arrow(self, on: bool) -> None:
      """!Draws or erases the arrow at the last line's right end (the window font's glyph).
      @param on  drawn
      @return None
      """
      arrow = self.c.get("arrow")
      if arrow is None or arrow == self.te.CODE_END or on == self.arrow_shown:
         return
      adv = advance_in(self.font, arrow)
      x = self.width - adv - self.c.get("left", 0)
      self._fill_rect(x, self.line_y, adv, self.font["cell"][1], self.background)
      if on:
         glyphs, self.glyphs = self.glyphs, self.font   # the arrow is the window font's
         self._draw_glyph(arrow, x, self.line_y)
         self.glyphs = glyphs
      self.arrow_shown = on

   # -- typing ------------------------------------------------------------------------------------------------------

   def print(self, codes: Sequence[int], instant: bool = False) -> None:
      """!Clears the window and types a text (window::print()).
      @param codes    the codes (ending with the end code)
      @param instant  print it at once (prompts still wait)
      @return None
      """
      if not self.open:
         return
      self.ink = self.c.get("ink", text_render.PIXEL_INK)
      self.shadow = self.c.get("shadow", text_render.PIXEL_SHADOW)
      self.background = self.c.get("background", 0)
      self.start_x, self.start_y = self.c.get("left", 0), self.c.get("top", 0)   # C13a: the printer's x and y
      self.min_spacing = 0
      self._clear_all()
      self.src, self.i = list(codes) + [self.te.CODE_END], 0
      self.resume = None
      self.pause = PAUSE_NONE
      self.timer = 0
      self.lead = self.c.get("lead_frames", 0)
      self.sped_up = False
      self.glyphs = self.font
      self.arrow_step = 0   # N3: the arrow image starts its steps again
      self.arrow_wait = 0
      self.instant = instant or (self.typing_mode() == self.k["kTypingInterval"] and
                                 self.c.get("frames_per_char", 1) == 0)
      if self.instant:
         self._type(True)

   def typing_mode(self) -> int:
      """!The typing value.
      @return kTypingInterval or kTypingCounter
      """
      return self.c.get("typing", self.k["kTypingInterval"])

   def _speedup(self) -> int:
      """!The speed-up value.
      @return kSpeedupRest, kSpeedupPerFrame or kSpeedupNone
      """
      return self.c.get("speedup", self.k["kSpeedupRest"])

   def _code(self, ahead: int = 0) -> int:
      """!A code of the text being read.
      @param ahead  codes after the next one
      @return the code (the end code past the end)
      """
      j = self.i + ahead
      return self.src[j] if self.src is not None and j < len(self.src) else self.te.CODE_END

   def _escape_length(self) -> int:
      """!Codes the escape at the next code takes (encode.h escape_length()).
      @return at least 1
      """
      if self._code(1) == self.te.CODE_END:
         return 1
      if self._code() != self.te.CODE_CONTROL or self._code(1) not in self.control_args:
         return ESCAPE_HEAD
      n = ESCAPE_HEAD + self.control_args[self._code(1)]
      for k in range(ESCAPE_HEAD, n):
         if self._code(k) == self.te.CODE_END:
            return k   # cut short: stop at the end code
      return n

   def _is_field(self) -> bool:
      """!The next code is a field placeholder (FD 80-FE) outside an expansion.
      @return True when it is
      """
      te = self.te
      arg = self._code(1)
      return self._code() == te.CODE_PLACEHOLDER and arg != te.CODE_END and \
         te.FIRST_FIELD_ARG <= arg <= te.LAST_FIELD_ARG and self.resume is None

   def _expand(self) -> None:
      """!Types a field placeholder's codes next, then the text after it.
      @return None
      """
      codes = list(self.placeholders.get(self._code(1), [])) + [self.te.CODE_END]
      self.resume = (self.src, self.i + ESCAPE_HEAD)
      self.src, self.i = codes, 0

   def _control(self) -> bool:
      """!Acts on the control escape at the next code (window.cpp control()).
      @return S6b (C13a): True when it drew as a glyph does (Clear / ClearTo of a positive width: RENDER_PRINT)
      """
      k = self._code(1)
      a = self._code(ESCAPE_HEAD)
      c = self.control_codes
      if k == c["color"]:
         self.ink = a
      elif k == c["highlight"]:
         self.background = a
      elif k == c["shadow"]:
         self.shadow = a
      elif k == c["colors"]:
         self.ink, self.background, self.shadow = a, self._code(COLORS_BACKGROUND_AT), self._code(COLORS_SHADOW_AT)
      elif k == c["pause"]:
         if not self.instant:
            self.frames = a
            self.pause = PAUSE_FRAMES
            self.timer = 0   # counter typing: the pause takes over the counter
      elif k == c["wait_button"]:
         self.pause = PAUSE_BUTTON
      elif k == c["scroll"]:
         self.pause = PAUSE_SCROLL
      elif k == c["shift_right"]:
         self.pen_x = self.start_x + a
      elif k == c["shift_down"]:
         self.line_y = self.start_y + a   # C13a: currentY = y + n (from the text's start)
      elif k == c["fill"]:
         # C13a: FillWindowPixelBuffer(PIXEL_FILL(bgColor)), the pen back to the text's start
         self._fill_rect(0, 0, self.width, self.height, self.background)
         self.pen_x, self.line_y, self.line = self.start_x, self.start_y, 0
      elif k == c["clear"]:
         if a > 0:
            self._clear_span(a)
            self.pen_x += a
            return True
      elif k == c["skip_to"]:
         self.pen_x = self.start_x + a
      elif k == c["clear_to"]:
         width = self.start_x + a - self.pen_x
         if width > 0:
            self._clear_span(width)
            self.pen_x += width
            return True
      elif k == c["min_spacing"]:
         self.min_spacing = a
      elif k == c["font"]:
         if a in self.fonts and self.fonts[a] is not None:   # an unknown n keeps the current font
            self.glyphs = self.fonts[a]
      elif k == c["reset_font"]:
         self.glyphs = self.font
      return False

   def _new_line(self) -> None:
      """!The next line; past the last one the window scrolls up a line first.
      @return None
      """
      self.pen_x = self.start_x   # C13a: CHAR_NEWLINE: currentX = the printer's x
      if self.line + 1 < self.c.get("lines", 1):
         self.line += 1
         self.line_y += self.font["line_height"]
         return
      self.pause = PAUSE_SCROLLING
      self.scrolled = 0

   def _scroll_pixels(self) -> bool:
      """!One frame's part of a scroll.
      @return True when the line has scrolled all the way (nothing moved then)
      """
      line = self.font["line_height"]
      if self.scrolled >= line:
         return True
      speed = self.c.get("scroll_speed", 1)
      step = line - self.scrolled if speed == 0 or speed > line - self.scrolled else speed
      for y in range(0, self.height - step):
         self._copy_row(y, y + step)
      for y in range(max(0, self.height - step), self.height):
         self._fill_row(y, self.background)
      self.scrolled += step
      return False

   def _scroll_step(self) -> None:
      """!One frame of a scroll (interval typing: the text goes on in the frame its last row moves).
      @return None
      """
      self._scroll_pixels()
      if self.scrolled >= self.font["line_height"]:
         self.pause = PAUSE_NONE
         self.pen_x = self.start_x

   def _end_or_resume(self) -> bool:
      """!At the end code: back to the text after an expansion, or done.
      @return True when reading goes on
      """
      if self.resume is not None:
         self.src, self.i = self.resume
         self.resume = None
         return True
      self.src = None
      return False

   def _type(self, all_codes: bool) -> None:
      """!Types codes until a glyph is drawn (or up to a pause when all_codes; window.cpp type()).
      @param all_codes  do not stop after a glyph
      @return None
      """
      te = self.te
      while self.reading():
         c = self._code()
         if c == te.CODE_END:
            if self._end_or_resume():
               continue
            return
         if self._is_field():
            self._expand()
            continue
         if c in (te.CODE_CONTROL, te.CODE_PLACEHOLDER):
            drew = c == te.CODE_CONTROL and self._code(1) != te.CODE_END and self._control()
            self.i += self._escape_length()
            if drew and not all_codes:
               return   # C13a: a Clear types as a glyph
            continue
         self.i += 1
         if c == te.CODE_NEWLINE:
            self._new_line()
            continue
         if c == te.CODE_PROMPT:
            self.pause = PAUSE_PROMPT
            return
         if c == te.CODE_PAGE_BREAK:
            self.pause = PAUSE_PAGE
            return
         self._draw_glyph(c, self.pen_x, self.line_y)
         self._pen_after_glyph(c)
         if not all_codes:
            return

   def _go_on(self) -> None:
      """!A pause ends: reading goes on.
      @return None
      """
      self.pause = PAUSE_NONE

   def reading(self) -> bool:
      """!Whether codes are read now: a text left and no pause.
      @return True when they are
      """
      return self.src is not None and self.pause == PAUSE_NONE

   def image_arrow(self) -> bool:
      """!S5 (N3): whether waits show the arrow image (arrow_kind kArrowImage) instead of the glyph.
      @return True for the image
      """
      return self.c.get("arrow_kind", self.k["kArrowGlyph"]) == self.k["kArrowImage"]

   def _step_image_arrow(self) -> None:
      """!S5 (N3, window.cpp step_image_arrow()): one frame of the arrow image while a wait shows it: after
      arrow_delay frames (none for the first step) the image's next window of rows is drawn at the pen over the
      background (its 0 pixels show the background), and the step moves on.
      @return None
      """
      rows = list(self.c.get("arrow_rows") or [])
      offsets = list(self.c.get("arrow_offsets") or [])
      if not rows or not offsets:
         return
      if self.arrow_wait > 0:
         self.arrow_wait -= 1
         return
      width, height = self.k["kArrowImageWidth"], self.c.get("arrow_height", 0)
      self._fill_rect(self.pen_x, self.line_y, width, height, self.background)
      first = offsets[self.arrow_step % len(offsets)]
      for r in range(height):
         if first + r >= len(rows):
            break
         row = rows[first + r]
         for x in range(width):
            v = (row >> (x * self.nibble_bits)) & self.nibble_mask
            if v != 0:
               self._put(self.pen_x + x, self.line_y + r, v)
      self.arrow_shown = True
      self.arrow_wait = self.c.get("arrow_delay", 0)
      self.arrow_step = (self.arrow_step + 1) % len(offsets)

   def _erase_image_arrow(self) -> None:
      """!S5 (N3, window.cpp erase_image_arrow()): the arrow image's rectangle at the pen back to the background.
      @return None
      """
      shown = self.arrow_shown   # a local alias (Doxygen 1.12 reads `if self.x:` as a new member)
      if shown:
         self._fill_rect(self.pen_x, self.line_y, self.k["kArrowImageWidth"], self.c.get("arrow_height", 0),
                         self.background)
      self.arrow_shown = False

   def _wait_with_arrow(self, pressed: bool) -> None:
      """!One frame of a prompt, page break or scroll wait: the arrow blinks (S5, N3: or the arrow image steps); a
      press goes on.
      @param pressed  Accept or Back went down this frame
      @return None
      """
      image = self.image_arrow()
      if image:
         self._step_image_arrow()
      else:
         self.blink = (self.blink + 1) & text_render.CHANNEL_MASK
         self._show_arrow((self.blink // self.blink_frames) % self.blink_phases == 0)
      if not pressed:
         return
      if image:
         self._erase_image_arrow()
         self.arrow_step = 0   # the next wait starts its steps again, its first at once
         self.arrow_wait = 0
      else:
         self._show_arrow(False)
      if self.pause == PAUSE_PAGE:
         self._clear_all()
         self.pause = PAUSE_NONE
      elif self.pause == PAUSE_SCROLL:
         self.pause = PAUSE_SCROLLING
         self.scrolled = 0
         self.pen_x = self.start_x
      else:
         self.pause = PAUSE_NONE
      self.blink = 0

   def _counter_frame(self, pressed: bool, held: bool) -> None:
      """!Counter typing's reads in one frame (window.cpp counter_frame()): the waits first, then codes until one
      ends the frame.
      @param pressed  Accept or Back went down this frame
      @param held     Accept or Back is held
      @return None
      """
      te, k = self.te, self.k
      if self.lead > 0:
         self.lead -= 1   # the box's own first frames: nothing is read yet
         return
      speedup = self._speedup()
      rush = speedup == k["kSpeedupRest"] and held
      for _guard in range(self.max_reads):
         pause = self.pause   # a local alias (Doxygen 1.12 reads some of these lines as new members)
         if pause == PAUSE_FRAMES:
            if self.frames != 0:
               self.frames -= 1
            else:
               self._go_on()
            return
         if pause == PAUSE_BUTTON:
            if pressed:
               self._go_on()
            return
         if pause in ARROW_PAUSES:
            self._wait_with_arrow(pressed)
            return
         if pause == PAUSE_SCROLLING:
            if self._scroll_pixels():
               self._go_on()
            return
         if self.src is None:
            return
         if speedup == k["kSpeedupPerFrame"] and held and self.sped_up:
            self.timer = 0   # sped up: held keeps the counter at 0
         if self.timer != 0 and self.c.get("char_delay", 0) != 0 and not rush:
            self.timer -= 1
            if speedup == k["kSpeedupPerFrame"] and pressed:
               self.sped_up = True   # a press while the counter runs ends it
               self.timer = 0
            return
         c = self._code()
         # an expansion's end, or the expansion itself, costs nothing: read on at once
         if c == te.CODE_END and self.resume is not None:
            self._end_or_resume()
            continue
         if self._is_field():
            self._expand()
            continue
         self.timer = self.c.get("char_delay", 0)   # every code read restarts the counter
         if c == te.CODE_END:
            self._end_or_resume()   # no expansion here: the text is done
            return
         if c in (te.CODE_CONTROL, te.CODE_PLACEHOLDER):
            drew = c == te.CODE_CONTROL and self._code(1) != te.CODE_END and self._control()
            self.i += self._escape_length()
            if self.pause in (PAUSE_BUTTON, PAUSE_SCROLL):
               self.blink = 0
               return   # a wait ends the frame
            if drew and not rush:
               return   # C13a: a Clear of a positive width types as a glyph (RENDER_PRINT)
            continue
         self.i += 1
         if c == te.CODE_NEWLINE:
            self._new_line()
            continue
         if c in (te.CODE_PROMPT, te.CODE_PAGE_BREAK):
            self.pause = PAUSE_PROMPT if c == te.CODE_PROMPT else PAUSE_PAGE
            self.blink = 0
            return
         self._draw_glyph(c, self.pen_x, self.line_y)
         self._pen_after_glyph(c)
         if not rush:
            return

   def update(self, pressed: bool = False, held: bool = False) -> None:
      """!Advances the window one frame (window::update()).
      @param pressed  Accept or Back went down this frame
      @param held     Accept or Back is held
      @return None
      """
      if not self.open:
         return
      if self.typing_mode() == self.k["kTypingCounter"]:
         self._counter_frame(pressed, held)
         return
      pause = self.pause   # a local alias (see _counter_frame())
      if pause in ARROW_PAUSES:
         self._wait_with_arrow(pressed)
      elif pause == PAUSE_BUTTON:
         if pressed:
            self._go_on()
      elif pause == PAUSE_SCROLLING:
         self._scroll_step()
      elif pause == PAUSE_FRAMES:
         if self.frames > 0:
            self.frames -= 1
         if self.frames == 0:
            self._go_on()
      if self.reading():
         if self.instant or held:
            self._type(True)   # the rest up to the next pause at once
         elif self.timer > 0:
            self.timer -= 1
         else:
            self._type(False)
            self.timer = max(self.c.get("frames_per_char", 1) - 1, 0)

   def busy(self) -> bool:
      """!The text still types, scrolls or waits.
      @return True until it is printed to its end
      """
      return self.open and (self.src is not None or self.pause != PAUSE_NONE)

   def waiting(self) -> bool:
      """!The text waits for a button.
      @return True while it does
      """
      return self.open and self.pause in BUTTON_PAUSES

   # -- S5 (N3) what menus draw with --------------------------------------------------------------------------------

   def print_at(self, x: int, y: int, codes: Sequence[int]) -> int:
      """!Draws a text at a pixel of the window at once, over what is there (window::print_at()): glyphs, colours,
      fonts, shifts and placeholders as print() takes them; a newline goes back to x one line lower; waits are
      skipped. The window must not be typing a text at the time. S6b (C13a): the text's start is (x, y): ShiftRight,
      ShiftDown, SkipTo and ClearTo count from it, and it stays the window's start afterwards as in the engine.
      @param x      pixels from the window's left edge
      @param y      pixels from its top edge (the top of the glyphs)
      @param codes  the codes (an end code ends them)
      @return the pen's column after the text
      """
      shown = self.open   # a local alias (Doxygen 1.12 reads `if not self.x:` as a new member)
      if not shown:
         return x
      te = self.te
      self._pen_at(x, y)
      self.start_x, self.start_y, self.min_spacing = x, y, 0   # C13a: the printer's x and y
      kept = self._kept_state()
      self._text_state((list(codes) + [te.CODE_END], 0, None, PAUSE_NONE))
      while self.src is not None:
         c = self._code()
         if c == te.CODE_END:
            if not self._end_or_resume():
               break   # the end of a placeholder's text went back to the text after it, or the text is done
            continue
         if self._is_field():
            self._expand()
            continue
         if c in (te.CODE_CONTROL, te.CODE_PLACEHOLDER):
            if c == te.CODE_CONTROL and self._code(1) != te.CODE_END:
               self._control()
               self._go_on()   # waits are skipped: nothing types here
            self.i += self._escape_length()
            continue
         self.i += 1
         if c == te.CODE_NEWLINE:
            self.pen_x = x
            self.line_y += self.font["line_height"]
            continue
         if c in (te.CODE_PROMPT, te.CODE_PAGE_BREAK):
            continue
         self._draw_glyph(c, self.pen_x, self.line_y)
         self._pen_after_glyph(c)
      self.glyphs = self.font
      self._text_state(kept)   # the window's own text as it was
      return self.pen_x

   def _pen_at(self, x: int, y: int) -> None:
      """!Puts the pen at a pixel with the window's font (print_at()).
      @param x  column
      @param y  the glyphs' top row
      @return None
      """
      self.pen_x, self.line_y, self.glyphs = x, y, self.font

   def _kept_state(self) -> tuple[Any, ...]:
      """!What the window reads now (TEXT_STATE), for print_at() to put back.
      @return the values in TEXT_STATE's order
      """
      return tuple(getattr(self, name) for name in TEXT_STATE)

   def _text_state(self, state: Sequence[Any]) -> None:
      """!Sets what the window reads (TEXT_STATE: the codes, the next one, an expansion's way back, the pause).
      @param state  the values in TEXT_STATE's order
      @return None
      """
      for name, v in zip(TEXT_STATE, state):
         setattr(self, name, v)

   def fill(self, x: int, y: int, width: int, height: int, entry: int) -> None:
      """!Fills a rectangle of the window's pixels with one palette entry, clipped (window::fill()).
      @param x       left, pixels
      @param y       top
      @param width   pixels across
      @param height  pixels down
      @param entry   palette entry
      @return None
      """
      shown = self.open   # a local alias (see _erase_image_arrow())
      if shown:
         self._fill_rect(x, y, width, height, entry)

   def set_colors(self, ink: int, background: int, shadow: int) -> None:
      """!The colours print_at() draws with until the next print() (window::set_colors()).
      @param ink         ink entry
      @param background  background entry
      @param shadow      shadow entry
      @return None
      """
      self.ink, self.background, self.shadow = ink, background, shadow


@dataclass
class Run:
   """!A text typed to its end (run()): every frame's pixels and what happened when."""

   ## The window's pixel size (width, height).
   size: tuple[int, int]
   ## Pixels after each frame (frame 0: after print(), before the first update()).
   frames: list[bytes] = field(default_factory=list)
   ## Frames where a wait for a button began.
   waits: list[int] = field(default_factory=list)
   ## Frames where the policy pressed.
   presses: list[int] = field(default_factory=list)
   ## The frame the text was done, or None (cut at MAX_FRAMES, or a wait without keys).
   done: int | None = None
   ## Frames that drew at least one new glyph pixel.
   typed: int = 0

   def frame_at(self, n: int) -> bytes:
      """!The pixels after a frame (clamped to the run).
      @param n  frame
      @return pixels
      """
      frames = self.frames   # a local alias (Doxygen 1.12 reads a dataclass field used in a method as a new member)
      return frames[min(max(n, 0), len(frames) - 1)]


## A key policy: (window, frame, frames waited so far) -> (pressed, held).
KeyPolicy = Callable[[Window, int, int], tuple[bool, bool]]


def key_policy(name: str, press_after: int = PRESS_AFTER) -> KeyPolicy:
   """!The keys a run() presses (KEY_POLICIES).
   @param name         "none", "advance" or "hold"
   @param press_after  frames at a wait before the press
   @return the policy
   @throws ValueError for an unknown name
   """
   if name not in KEY_POLICIES:
      raise ValueError(f"keys are one of {', '.join(KEY_POLICIES)}")
   state = {"sped": False}

   def policy(w: Window, _frame: int, waited: int) -> tuple[bool, bool]:
      """!This frame's keys."""
      if name == "none":
         return False, False
      at_wait = w.waiting() and waited >= press_after
      if name == "advance":
         return at_wait, at_wait   # a key that goes down is held that frame
      if w.waiting():
         # held through the text; let go a frame before pressing again at a wait
         return at_wait, waited < press_after - RELEASE_FRAMES or at_wait
      # one press while the text types (a counter running), then held
      press = not state["sped"] and w.src is not None and w.pause == PAUSE_NONE and w.lead == 0 and \
         (w.timer != 0 or w.typing_mode() != w.k["kTypingCounter"])
      state["sped"] = state["sped"] or press
      return press, True

   return policy


def run(settings: Settings, font: CompiledFont, codes: Sequence[int], keys: str | KeyPolicy = "advance",
        fonts: Mapping[int, CompiledFont] | None = None, placeholders: Mapping[int, Sequence[int]] | None = None,
        limit: int = MAX_FRAMES) -> Run:
   """!Types a text to its end, a frame at a time, keeping every frame's pixels.
   @param settings      the window's settings
   @param font          its font
   @param codes         the text
   @param keys          a KEY_POLICIES name or a policy
   @param fonts         the Font control's fonts, or None
   @param placeholders  what field placeholders show, or None
   @param limit         most frames
   @return Run
   """
   w = Window(settings, font, fonts, placeholders)
   policy = key_policy(keys) if isinstance(keys, str) else keys
   out = Run((w.width, w.height))
   if not w.open:
      out.frames.append(bytes(w.pixels))
      out.done = 0
      return out
   w.print(codes)
   out.frames.append(bytes(w.pixels))
   waited = 0
   frame = 0
   while w.busy() and frame < limit:
      if w.waiting():
         waited += 1
      else:
         waited = 0
      pressed, held = policy(w, frame, waited)
      if pressed:
         out.presses.append(frame + 1)
      was_waiting = w.waiting()
      w.update(pressed, held)
      frame += 1
      if w.waiting() and not was_waiting:
         out.waits.append(frame)
      if out.frames[-1] != w.pixels:
         out.typed += 1
      out.frames.append(bytes(w.pixels))
      if keys == KEY_POLICIES[0] and w.waiting():
         break   # nothing ever presses: the text stays at its first wait
   if not w.busy():
      out.done = frame
   return out
