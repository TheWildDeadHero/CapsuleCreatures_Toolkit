#!/usr/bin/env python3
"""!Writes the sample world's tile sheet, sheets/shapes_8x8.png: simple shapes only (project rule: test art is
simple shapes, no third-party material), standard library only.

    python3 test/tilesets/make_shapes_sheet.py [--out PATH]

The sheet is 128 x 16384 pixels, 8 x 8 tiles in rows of 16 (tile N is at column N % 16, row N // 16), the layout
tilesets/t1.json's "Shapes:N" references use. Every tile is a background colour, one of four shapes in an ink
colour, and the low bits of its index as dots along its top row, so the tiles t1.json uses differ from each other
(also when mirrored).
Tiles whose index is a multiple of TRANSPARENT_EVERY have the sheet's transparent colour (#fff200) as background.
The output is the same on every run.
"""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

## Pixels per tile side.
TILE = 8
## Tiles per sheet row.
TILES_PER_ROW = 16
## Sheet size in pixels (the size of the sheet this one replaced, so t1.json's tile numbers keep their places).
WIDTH = TILE * TILES_PER_ROW
HEIGHT = 16384
## An RGB colour.
Rgb = tuple[int, int, int]
## The transparent colour t1.json names.
TRANSPARENT: Rgb = (0xFF, 0xF2, 0x00)
## Every this many tiles has a transparent background.
TRANSPARENT_EVERY = 7
## Background colours (cycled by tile index).
BACKGROUNDS: tuple[Rgb, ...] = ((0x58, 0x98, 0x48), (0x38, 0x68, 0xB0), (0xB0, 0x90, 0x60), (0x80, 0x80, 0x88))
## Ink colours of the shapes (cycled by tile row).
INKS: tuple[Rgb, ...] = ((0x18, 0x18, 0x20), (0xF0, 0xF0, 0xE8))
## Colour of the index dots.
DOT: Rgb = (0xD0, 0x30, 0x30)
## The shapes, chosen by tile index.
SHAPES = ("square", "disc", "diagonal", "cross")
## Bits of the tile index shown as dots on the top row (one per pixel).
INDEX_BITS = TILE
## Inner box of a shape (first and last pixel, inside the dot row).
INNER_FIRST = 2
INNER_LAST = TILE - 1
## Squared radius of the disc around the inner box's centre, in pixels.
DISC_RADIUS_SQUARED = 10
## The disc is measured in doubled coordinates, so its centre between pixels is a whole number.
DOUBLE = 2
## PNG signature, colour type (RGB), bit depth and the per-row filter byte (none).
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_RGB = 2
PNG_BIT_DEPTH = 8
PNG_FILTER_NONE = 0
## zlib level of the image data.
ZLIB_LEVEL = 9
## The default output, beside this script.
DEFAULT_OUT = Path(__file__).resolve().parent / "sheets" / "shapes_8x8.png"


def shape_pixel(shape: str, x: int, y: int) -> bool:
   """!Whether a pixel of a tile belongs to its shape.
   @param shape  one of SHAPES
   @param x      column in the tile
   @param y      row in the tile
   @return True when the pixel is ink
   """
   if not (INNER_FIRST <= x <= INNER_LAST and INNER_FIRST <= y <= INNER_LAST):
      return False
   if shape == "square":
      return x in (INNER_FIRST, INNER_LAST) or y in (INNER_FIRST, INNER_LAST)
   if shape == "disc":
      centre = INNER_FIRST + INNER_LAST   # doubled
      dx = DOUBLE * x - centre
      dy = DOUBLE * y - centre
      return dx * dx + dy * dy <= DOUBLE * DOUBLE * DISC_RADIUS_SQUARED
   if shape == "diagonal":
      return x == y
   return x == (INNER_FIRST + INNER_LAST) // DOUBLE or y == INNER_LAST - 1


def tile_pixel(index: int, x: int, y: int) -> Rgb:
   """!One pixel of a tile.
   @param index  tile number
   @param x      column in the tile
   @param y      row in the tile
   @return its colour
   """
   if y == 0:
      # The top row shows the index's low bits, most significant bit on the left.
      if (index >> (INDEX_BITS - 1 - x)) & 1:
         return DOT
   elif shape_pixel(SHAPES[index % len(SHAPES)], x, y):
      return INKS[(index // TILES_PER_ROW) % len(INKS)]
   if index % TRANSPARENT_EVERY == 0:
      return TRANSPARENT
   return BACKGROUNDS[(index // len(SHAPES)) % len(BACKGROUNDS)]


def sheet_rows() -> list[bytes]:
   """!The sheet's pixel rows as RGB bytes, each with its filter byte.
   @return rows, top first
   """
   rows = []
   for py in range(HEIGHT):
      row = bytearray([PNG_FILTER_NONE])
      for px in range(WIDTH):
         index = (py // TILE) * TILES_PER_ROW + px // TILE
         row += bytes(tile_pixel(index, px % TILE, py % TILE))
      rows.append(bytes(row))
   return rows


def chunk(kind: bytes, data: bytes) -> bytes:
   """!One PNG chunk.
   @param kind  its four-letter type
   @param data  its contents
   @return the chunk with length and CRC
   """
   return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def write_png(path: Path) -> None:
   """!Writes the sheet.
   @param path  the PNG file
   @return None
   """
   header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, PNG_BIT_DEPTH, PNG_RGB, 0, 0, 0)
   data = zlib.compress(b"".join(sheet_rows()), ZLIB_LEVEL)
   path.parent.mkdir(parents=True, exist_ok=True)
   path.write_bytes(PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", data) + chunk(b"IEND", b""))


def main() -> None:
   """!Command line.
   @return None
   """
   p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
   p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the PNG to write (default: sheets/shapes_8x8.png)")
   write_png(p.parse_args().out)


if __name__ == "__main__":
   main()
