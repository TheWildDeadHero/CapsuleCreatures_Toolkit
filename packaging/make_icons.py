#!/usr/bin/env python3
"""!Draws the studio bundle's icons from simple shapes (standard library only): a rounded teal square holding a
two-colour pill, written as PNG files, a Windows .ico and a macOS .icns.

    python3 make_icons.py OUT_DIR

Nothing is copied from elsewhere: every pixel comes from the shapes below, so the icons carry the project's own
licence (D-40, tier 0). The bundle build (build_bundle.py) runs this into its work folder; no image is committed.
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
import zlib
from collections.abc import Callable
from pathlib import Path

## An RGBA colour, 0-255 per channel.
Colour = tuple[int, int, int, int]
## A shape's coverage test: (x, y) in unit coordinates (0..1, y down) -> inside?
Shape = Callable[[float, float], bool]

## Icon sizes drawn (pixels, square).
SIZES = (16, 32, 48, 64, 128, 256)
## Sizes the Windows .ico holds.
ICO_SIZES = (16, 32, 48, 256)
## macOS .icns chunk type per size (PNG-coded types; see Apple's IconFamily layout).
ICNS_TYPES = {16: b"icp4", 32: b"icp5", 64: b"icp6", 128: b"ic07", 256: b"ic08"}
## Samples per pixel along each axis (anti-aliasing by supersampling).
SUPERSAMPLE = 3
## Largest 8-bit channel value.
CHANNEL_MAX = 255
## Bytes per RGBA pixel.
RGBA_BYTES = 4
## Index of the alpha channel in a Colour; the colour channels come before it.
ALPHA = 3

## Background: the rounded square's colour.
TEAL: Colour = (31, 122, 140, CHANNEL_MAX)
## The pill's left half.
AMBER: Colour = (242, 165, 65, CHANNEL_MAX)
## The pill's right half.
CREAM: Colour = (247, 243, 227, CHANNEL_MAX)
## The pill's outline.
INK: Colour = (22, 48, 59, CHANNEL_MAX)
## Fully transparent.
CLEAR: Colour = (0, 0, 0, 0)

## The rounded square's margin from the icon's edge (unit coordinates).
SQUARE_MARGIN = 0.06
## The rounded square's corner radius.
SQUARE_RADIUS = 0.2
## Middle of the icon.
CENTRE = 0.5
## The pill's half length along its axis, before the outline.
PILL_HALF_LENGTH = 0.25
## The pill's radius.
PILL_RADIUS = 0.15
## The outline's width around the pill.
OUTLINE = 0.035
## The pill's tilt from horizontal (degrees; the right end lower).
PILL_TILT_DEGREES = -35.0

## PNG file signature.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
## PNG bit depth (8 bits per channel).
PNG_BIT_DEPTH = 8
## PNG colour type 6: RGBA.
PNG_COLOUR_RGBA = 6
## PNG scanline filter "none".
PNG_FILTER_NONE = 0
## zlib level for PNG data.
ZLIB_LEVEL = 9
## ICO file type (1 = icon).
ICO_TYPE = 1
## ICO entry's size field for 256 px (stored as 0).
ICO_BIG = 256
## ICO header bytes, and bytes per directory entry.
ICO_HEADER_BYTES = 6
ICO_ENTRY_BYTES = 16
## ICO colour planes and bits per pixel.
ICO_PLANES = 1
ICO_BPP = 32
## ICNS: bytes of a chunk header (type + length).
ICNS_HEADER_BYTES = 8


def rounded_square(x: float, y: float) -> bool:
   """!Inside the background square with rounded corners?
   @param x  unit x
   @param y  unit y
   @return bool
   """
   half = CENTRE - SQUARE_MARGIN - SQUARE_RADIUS
   # Distance from the square's core (shrunk by the radius); inside within the radius.
   dx = max(abs(x - CENTRE) - half, 0.0)
   dy = max(abs(y - CENTRE) - half, 0.0)
   return dx * dx + dy * dy <= SQUARE_RADIUS * SQUARE_RADIUS


def pill_axis(x: float, y: float) -> tuple[float, float]:
   """!A point in the pill's own frame: u along its axis, v across it.
   @param x  unit x
   @param y  unit y
   @return (u, v)
   """
   angle = math.radians(PILL_TILT_DEGREES)
   dx, dy = x - CENTRE, y - CENTRE
   return dx * math.cos(angle) - dy * math.sin(angle), dx * math.sin(angle) + dy * math.cos(angle)


def in_pill(x: float, y: float, grow: float) -> bool:
   """!Inside the pill (a capsule: a segment with a radius), grown by `grow`?
   @param x     unit x
   @param y     unit y
   @param grow  extra radius (the outline)
   @return bool
   """
   u, v = pill_axis(x, y)
   # Nearest point on the axis segment, then the distance to it.
   cu = min(max(u, -PILL_HALF_LENGTH), PILL_HALF_LENGTH)
   du = u - cu
   radius = PILL_RADIUS + grow
   return du * du + v * v <= radius * radius


def colour_at(x: float, y: float) -> Colour:
   """!The icon's colour at one sample point (shapes painted back to front).
   @param x  unit x
   @param y  unit y
   @return Colour
   """
   if in_pill(x, y, 0.0):
      return AMBER if pill_axis(x, y)[0] < 0.0 else CREAM
   if in_pill(x, y, OUTLINE):
      return INK
   if rounded_square(x, y):
      return TEAL
   return CLEAR


def render(size: int) -> bytes:
   """!Draws the icon at one size.
   @param size  pixels per side
   @return RGBA rows, top to bottom
   """
   out = bytearray()
   samples = SUPERSAMPLE * SUPERSAMPLE
   for py in range(size):
      for px in range(size):
         acc = [0, 0, 0, 0]
         for sy in range(SUPERSAMPLE):
            for sx in range(SUPERSAMPLE):
               # Sample centres spread evenly inside the pixel.
               c = colour_at((px + (sx + CENTRE) / SUPERSAMPLE) / size, (py + (sy + CENTRE) / SUPERSAMPLE) / size)
               alpha = c[ALPHA]
               for i in range(ALPHA):
                  acc[i] += c[i] * alpha   # premultiplied, so clear samples do not darken the edge
               acc[ALPHA] += alpha
         a = acc[ALPHA]
         if a == 0:
            out += bytes(CLEAR)
         else:
            out += bytes([round(acc[i] / a) for i in range(ALPHA)] + [round(a / samples)])
   return bytes(out)


def png_chunk(kind: bytes, data: bytes) -> bytes:
   """!One PNG chunk (length, type, data, CRC).
   @param kind  4-byte chunk type
   @param data  payload
   @return bytes
   """
   return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(size: int, rgba: bytes) -> bytes:
   """!An RGBA PNG file.
   @param size  pixels per side
   @param rgba  pixels from render()
   @return the file's bytes
   """
   stride = size * RGBA_BYTES
   raw = b"".join(bytes([PNG_FILTER_NONE]) + rgba[row * stride:(row + 1) * stride] for row in range(size))
   header = struct.pack(">IIBBBBB", size, size, PNG_BIT_DEPTH, PNG_COLOUR_RGBA, 0, 0, 0)
   return (PNG_SIGNATURE + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(raw, ZLIB_LEVEL))
           + png_chunk(b"IEND", b""))


def ico(images: dict[int, bytes]) -> bytes:
   """!A Windows icon holding PNG images (supported since Windows Vista).
   @param images  size -> PNG bytes
   @return the file's bytes
   """
   sizes = [s for s in ICO_SIZES if s in images]
   head = struct.pack("<HHH", 0, ICO_TYPE, len(sizes))
   offset = ICO_HEADER_BYTES + ICO_ENTRY_BYTES * len(sizes)
   entries, blobs = b"", b""
   for s in sizes:
      side = 0 if s == ICO_BIG else s   # the byte field stores 256 as 0
      entries += struct.pack("<BBBBHHII", side, side, 0, 0, ICO_PLANES, ICO_BPP, len(images[s]), offset)
      blobs += images[s]
      offset += len(images[s])
   return head + entries + blobs


def icns(images: dict[int, bytes]) -> bytes:
   """!A macOS icon family holding PNG images.
   @param images  size -> PNG bytes
   @return the file's bytes
   """
   body = b"".join(kind + struct.pack(">I", ICNS_HEADER_BYTES + len(images[s])) + images[s]
                   for s, kind in ICNS_TYPES.items() if s in images)
   return b"icns" + struct.pack(">I", ICNS_HEADER_BYTES + len(body)) + body


def main(argv: list[str] | None = None) -> int:
   """!Writes capsule-studio-<size>.png, capsule-studio.ico and capsule-studio.icns.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   p = argparse.ArgumentParser(description="Draws the studio bundle's icons.")
   p.add_argument("out", help="folder to write the icons into")
   args = p.parse_args(argv)
   out = Path(args.out)
   out.mkdir(parents=True, exist_ok=True)
   images = {s: png(s, render(s)) for s in SIZES}
   for s, data in images.items():
      (out / f"capsule-studio-{s}.png").write_bytes(data)
   (out / "capsule-studio.ico").write_bytes(ico(images))
   (out / "capsule-studio.icns").write_bytes(icns(images))
   print(f"icons in {out}")
   return 0


if __name__ == "__main__":
   sys.exit(main())
