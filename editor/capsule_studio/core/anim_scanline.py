"""![S8] Scanline-effect preview for the Studio (M5, D-38; the engine's include/capsule/screen/scanline.h).

A scanline effect gives one display register a value per line from a table (hal::video::set_line_effect(); line y
shows entry y). This module makes the tables a scene would write, frame by frame, and draws what the screen shows
with simple shapes on two layers (layer A: stripes with a ring and a bar, the front; layer B: checks):

  - registers (REGISTERS): a layer's x scroll, its y scroll, window 0's edges ((left << 8) | right, inside shows
    A over B, outside B only) and the colour effect's weights (eva | (evb << 8), A blended over B);
  - tables (Effect.source): "wave" is the engine's wave (scanline.h start_wave(): samples (sine[theta] x amplitude)
    / 256, theta stepping by the frequency, the engine's 8.8 sine (trig.h sin_q14 >> 6, as the engine's sandbox
    makes it), the start sample moving every delay + 1 frames, back to the first after 256 / frequency, plus the
    base, written to lines start to end - 1), "ramp" a weight cycle (a = (y + frame x speed) % period, the weights
    a and 16 - a; the sandbox's blend part) and "diamond" a window that grows (half width radius - |y - centre|,
    the radius start + frame x growth; the sandbox's window part).

Frame t shows the table written on frame t (the engine's double buffer: written while the other one shows, then
present() in the vertical blank). Numbers follow the engine's integer arithmetic. Nothing here needs Qt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import anim_affine, engine

## The engine header with the screen's size and the line table's entries.
VIDEO_HEADER = "capsule/hal/video.h"
## Fallbacks for video.h's constants (used only without an engine checkout; the values are the engine's).
FALLBACK_SCREEN_WIDTH = 240
## Fallback of video.h kScreenHeight.
FALLBACK_SCREEN_HEIGHT = 160
## Fallback of video.h kBlendMax.
FALLBACK_BLEND_MAX = 16
## Fallback of video.h kWindowLineShift.
FALLBACK_WINDOW_LINE_SHIFT = 8

## Samples of a wave (scanline.h kWaveSamples) and its sine table's entries.
WAVE_SAMPLES = 256
## A sample is sine x amplitude / this.
SINE_SCALE = 256
## The engine sandbox's 8.8 sine: sin_q14 of i << 8, >> this.
SINE_TO_Q8 = 6
## 1/256 turns to a 16-bit turn.
ANGLE_SHIFT = 8
## Values of a 16-bit entry.
WORD_VALUES = 0x10000
## Values of a byte.
BYTE_VALUES = 0x100
## Low byte of an entry.
BYTE_MASK = 0xFF
## Width and height of a background layer's picture (a 32 x 32 cell map of 8-pixel tiles): scrolls wrap there.
LAYER_SIZE = 256
## Halves.
HALF = 2

## The registers the preview shows: id -> title.
REGISTERS = {
   "bg_x": "Layer A x scroll (BGnHOFS)",
   "bg_y": "Layer A y scroll (BGnVOFS)",
   "win0_h": "Window 0 edges (WIN0H: left << 8 | right)",
   "blend": "Blend weights (BLDALPHA: eva | evb << 8)",
}
## The table sources: id -> title.
SOURCES = {
   "wave": "Wave (the engine's start_wave)",
   "ramp": "Weight ramp",
   "diamond": "Growing diamond",
}
## The source each register starts with in the editor.
DEFAULT_SOURCE = {"bg_x": "wave", "bg_y": "wave", "win0_h": "diamond", "blend": "ramp"}

## Defaults of an Effect's settings (the engine sandbox's wave: frequency 4, amplitude 6, delay 1; its ramp and its
## diamond).
DEFAULT_FREQUENCY = 4
## Default wave amplitude.
DEFAULT_AMPLITUDE = 6
## Default wave delay.
DEFAULT_DELAY = 1
## Default ramp period (weights 0 to 16).
DEFAULT_PERIOD = 17
## Default ramp speed, lines a frame.
DEFAULT_SPEED = 1
## Default diamond's first radius.
DEFAULT_RADIUS = 20
## Default diamond growth a frame.
DEFAULT_GROWTH = 1
## Frames the preview offers by default (one scene part of the sandbox).
DEFAULT_FRAMES = 60

## Shapes of the preview's layers: stripe width, ring radii (squared bounds), bar height, check side, pixels.
STRIPE_WIDTH = 8
## Layer A's ring: inside this radius.
RING_OUTER = 40
## Layer A's ring: outside this radius.
RING_INNER = 28
## Half height of layer A's bar.
BAR_HALF_HEIGHT = 6
## Side of layer B's checks.
CHECK_SIDE = 8
## Colours (8-bit RGB): the stripes (cycled), the ring and bar, the two checks.
STRIPES = ((24, 176, 72), (40, 160, 80), (56, 144, 88), (72, 128, 96))
## The ring's colour.
RING = (248, 216, 64)
## The bar's colour.
BAR = (240, 96, 64)
## Layer B's first check colour.
CHECK_A = (48, 48, 112)
## Layer B's second check colour.
CHECK_B = (80, 80, 160)
## Bytes per RGB pixel.
RGB_BYTES = 3


def _video_constant(name: str, fallback: int) -> int:
   """!A constant of the engine's video.h (decimal), or its fallback.
   @param name      its name
   @param fallback  value without an engine checkout
   @return the value
   """
   try:
      text = (engine.root() / "include" / VIDEO_HEADER).read_text(encoding="utf-8")
   except (OSError, engine.EngineNotFound):
      return fallback
   m = re.search(r"\b" + re.escape(name) + r"\s*=\s*(\d+)\s*;", text)
   return int(m.group(1)) if m else fallback


## Screen width, pixels (video.h kScreenWidth).
SCREEN_WIDTH = _video_constant("kScreenWidth", FALLBACK_SCREEN_WIDTH)
## Screen height, pixels (video.h kScreenHeight).
SCREEN_HEIGHT = _video_constant("kScreenHeight", FALLBACK_SCREEN_HEIGHT)
## Entries of a line table: one more than the lines (the last is read but not shown; video.h kLineEntries).
LINE_ENTRIES = SCREEN_HEIGHT + 1
## Largest blend weight (video.h kBlendMax).
BLEND_MAX = _video_constant("kBlendMax", FALLBACK_BLEND_MAX)
## Shift of a window entry's left edge (video.h kWindowLineShift).
WINDOW_LINE_SHIFT = _video_constant("kWindowLineShift", FALLBACK_WINDOW_LINE_SHIFT)


def c_div(a: int, b: int) -> int:
   """!C's integer division (toward zero).
   @param a  dividend
   @param b  divisor (not 0)
   @return the quotient
   """
   return anim_affine.c_div(a, b)


def engine_sine() -> list[int]:
   """!The engine sandbox's 256-entry 8.8 sine table: sin_q14(i << 8) >> 6 (scenes.cpp make_shapes()).
   @return 256 values
   """
   n = anim_affine.numbers()
   return [n.sin_q14(i << ANGLE_SHIFT) >> SINE_TO_Q8 for i in range(WAVE_SAMPLES)]


@dataclass
class Effect:
   """!One scanline effect's settings (see the module doc)."""

   ## The register (REGISTERS id).
   register: str = "bg_x"
   ## The source of the table (SOURCES id).
   source: str = "wave"
   ## First line written (wave).
   start_line: int = 0
   ## Line after the last (wave).
   end_line: int = SCREEN_HEIGHT
   ## Theta step per sample (wave; 1 or more).
   frequency: int = DEFAULT_FREQUENCY
   ## Sample scale (wave).
   amplitude: int = DEFAULT_AMPLITUDE
   ## Frames each start sample is kept less one (wave).
   delay: int = DEFAULT_DELAY
   ## Value added to every sample (wave: e.g. the layer's scroll).
   base: int = 0
   ## Weight cycle (ramp).
   period: int = DEFAULT_PERIOD
   ## Lines the cycle moves a frame (ramp).
   speed: int = DEFAULT_SPEED
   ## First radius (diamond).
   radius: int = DEFAULT_RADIUS
   ## Radius added a frame (diamond).
   growth: int = DEFAULT_GROWTH
   ## The wave's sine table (None: engine_sine()).
   sine: list[int] | None = field(default=None, repr=False)

   def problems(self) -> list[str]:
      """!Settings the engine would refuse (the asserts of scanline.cpp) or that make no table.
      @return problem texts
      """
      out = []
      source = self.source
      if self.register not in REGISTERS:
         out.append(f"unknown register {self.register!r}")
      if source not in SOURCES:
         out.append(f"unknown source {source!r}")
      if source == "wave":
         if self.frequency < 1:
            out.append("the wave's frequency is 1 or more")
         if not 0 <= self.start_line <= self.end_line <= LINE_ENTRIES:
            out.append(f"the wave's lines must keep 0 <= start <= end <= {LINE_ENTRIES}")
      if source == "ramp" and self.period < 1:
         out.append("the ramp's period is 1 or more")
      return out


def wave_samples(e: Effect) -> list[int]:
   """!The wave's samples (scanline.cpp start_wave()): 16-bit values.
   @param e  the effect
   @return WAVE_SAMPLES values
   """
   sine = e.sine if e.sine is not None else engine_sine()
   out, theta = [], 0
   for _ in range(WAVE_SAMPLES):
      out.append(c_div(sine[theta] * e.amplitude, SINE_SCALE) % WORD_VALUES)
      theta = (theta + e.frequency) % BYTE_VALUES
   return out


def wave_offsets(e: Effect, frames: int) -> list[int]:
   """!The start sample the wave's task writes on each frame (scanline.cpp wave_task()).
   @param e       the effect
   @param frames  frames
   @return one offset per frame (frame 0 first)
   """
   length = WAVE_SAMPLES // e.frequency
   offset, wait, out = 0, e.delay, []
   for _ in range(frames):
      out.append(offset)
      if wait != 0:
         wait -= 1
         continue
      wait = e.delay
      offset += 1
      if offset == length:
         offset = 0
   return out


def tables(e: Effect, frames: int) -> list[list[int]]:
   """!The line table shown on each frame.
   @param e       the effect (problems() empty)
   @param frames  frames
   @return one table (LINE_ENTRIES 16-bit entries) per frame
   """
   out: list[list[int]] = []
   if e.source == "wave":
      samples = wave_samples(e)
      for offset in wave_offsets(e, frames):
         t = [0] * LINE_ENTRIES
         for i, line in enumerate(range(e.start_line, e.end_line)):
            k = offset + i
            t[line] = ((samples[k] if k < WAVE_SAMPLES else 0) + e.base) % WORD_VALUES   # a read past gives 0
         out.append(t)
   elif e.source == "ramp":
      cycle = max(1, e.period)
      for f in range(frames):
         t = []
         for y in range(LINE_ENTRIES):
            a = min((y + f * e.speed) % cycle, BLEND_MAX)
            t.append(a | ((BLEND_MAX - a) << WINDOW_LINE_SHIFT))
         out.append(t)
   else:   # diamond
      cx, cy = SCREEN_WIDTH // HALF, SCREEN_HEIGHT // HALF
      for f in range(frames):
         r = e.radius + f * e.growth
         t = []
         for y in range(LINE_ENTRIES):
            hw = max(0, r - abs(y - cy))
            t.append(0 if hw == 0 else ((cx - hw) << WINDOW_LINE_SHIFT) | (cx + hw))
         out.append(t)
   return out


def signed(v: int) -> int:
   """!A 16-bit entry as a signed value (a scroll).
   @param v  0 to 65535
   @return -32768 to 32767
   """
   return anim_affine.s16(v)


# -- the preview's picture --------------------------------------------------------------------------------------

def layer_a(x: int, y: int) -> tuple[int, int, int] | None:
   """!Layer A's pixel (its 256 x 256 picture, wrapping): stripes, a ring and a bar across it.
   @param x  column
   @param y  row
   @return RGB, or None where it is transparent
   """
   x %= LAYER_SIZE
   y %= LAYER_SIZE
   cx, cy = SCREEN_WIDTH // HALF, SCREEN_HEIGHT // HALF
   d2 = (x - cx) * (x - cx) + (y - cy) * (y - cy)
   if RING_INNER * RING_INNER <= d2 < RING_OUTER * RING_OUTER:
      return RING
   if abs(y - cy) < BAR_HALF_HEIGHT:
      return BAR
   band = x // STRIPE_WIDTH
   return STRIPES[band % len(STRIPES)] if band % HALF == 0 else None


def layer_b(x: int, y: int) -> tuple[int, int, int]:
   """!Layer B's pixel: checks.
   @param x  column
   @param y  row
   @return RGB
   """
   return CHECK_A if (x // CHECK_SIDE + y // CHECK_SIDE) % HALF == 0 else CHECK_B


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], eva: int, evb: int) -> tuple[int, int, int]:
   """!The colour effect's alpha blend (each channel a x eva / 16 + b x evb / 16, at most full).
   @param a    first target
   @param b    second target
   @param eva  its weight
   @param evb  the second's
   @return RGB
   """
   full = BYTE_MASK
   return tuple(min(full, (ca * min(eva, BLEND_MAX) + cb * min(evb, BLEND_MAX)) // BLEND_MAX)
                for ca, cb in zip(a, b))


def render(register: str, table: list[int]) -> bytes:
   """!The screen with a line table applied to a register (see the module doc).
   @param register  REGISTERS id
   @param table     LINE_ENTRIES entries (line y uses entry y)
   @return SCREEN_WIDTH x SCREEN_HEIGHT RGB pixels
   """
   out = bytearray(SCREEN_WIDTH * SCREEN_HEIGHT * RGB_BYTES)
   at = 0
   for y in range(SCREEN_HEIGHT):
      v = table[y]
      left, right = v >> WINDOW_LINE_SHIFT, v & BYTE_MASK
      eva, evb = v & BYTE_MASK, v >> WINDOW_LINE_SHIFT
      for x in range(SCREEN_WIDTH):
         back = layer_b(x, y)
         if register == "bg_x":
            front = layer_a(x + signed(v), y)
            px = front or back
         elif register == "bg_y":
            front = layer_a(x, y + signed(v))
            px = front or back
         elif register == "win0_h":
            front = layer_a(x, y)
            px = (front or back) if left <= x < right else back
         else:   # blend
            front = layer_a(x, y)
            px = _blend(front, back, eva, evb) if front is not None else back
         out[at:at + RGB_BYTES] = bytes(px)
         at += RGB_BYTES
   return bytes(out)
