"""![S3] Palette PNGs (color type 3) written with their indices as they are: a direction grid's sheet rearranged
(core.sprite_grid: a right column added or dropped, rows added or removed) keeps every pixel's palette index, which
the engine reads unchanged (bitmap.read_png_indices()). The engine's bitmap module reads them; it writes only RGBA
PNGs, so the few lines of writing live here. No Qt.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

from . import engine

## The PNG file signature.
SIGNATURE = b"\x89PNG\r\n\x1a\n"
## Bytes of a chunk's length and type.
CHUNK_HEADER = 8
## Bytes of a chunk's length, type and CRC.
CHUNK_OVERHEAD = 12
## IHDR bit depth written: one byte per pixel.
BYTE_DEPTH = 8
## IHDR color type of a palette PNG.
COLOR_PALETTE = 3
## PNG row filter "none" (each row starts with its filter byte).
FILTER_NONE = 0
## Bytes per palette entry in PLTE (r, g, b).
PLTE_ENTRY = 3


def palette_chunks(path: str | Path) -> tuple[bytes, bytes | None]:
   """!A palette PNG's PLTE and tRNS chunk bodies.
   @param path  the file
   @return (PLTE body, tRNS body or None)
   @throws ValueError when the file is not a palette PNG
   """
   blob = Path(path).read_bytes()
   if blob[:len(SIGNATURE)] != SIGNATURE:
      raise ValueError(f"{Path(path).name}: not a PNG file")
   pos, plte, trns = len(SIGNATURE), None, None
   while pos + CHUNK_HEADER <= len(blob):
      length, ctype = struct.unpack(">I4s", blob[pos:pos + CHUNK_HEADER])
      body = blob[pos + CHUNK_HEADER:pos + CHUNK_HEADER + length]
      pos += CHUNK_OVERHEAD + length
      if ctype == b"PLTE":
         plte = body
      elif ctype == b"tRNS":
         trns = body
      elif ctype == b"IEND":
         break
   if plte is None:
      raise ValueError(f"{Path(path).name}: not a palette PNG (no PLTE)")
   return plte, trns


def _chunk(ctype: bytes, body: bytes) -> bytes:
   """!One PNG chunk: length, type, body and CRC.
   @param ctype  four-byte type
   @param body   the body
   @return the chunk
   """
   return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body))


def encode(width: int, height: int, indices: bytes | bytearray, plte: bytes, trns: bytes | None = None) -> bytes:
   """!A palette PNG of indices (8 bits per pixel, no interlace).
   @param width    pixels across
   @param height   pixels down
   @param indices  one palette index per pixel, rows top to bottom
   @param plte     PLTE body (r, g, b per entry)
   @param trns     tRNS body, or None
   @return the file's bytes
   """
   if len(indices) != width * height:
      raise ValueError(f"{len(indices)} indices for a {width}x{height} image")
   if indices and max(indices) >= len(plte) // PLTE_ENTRY:
      raise ValueError("an index past the palette")
   raw = b"".join(bytes([FILTER_NONE]) + bytes(indices[y * width:(y + 1) * width]) for y in range(height))
   ihdr = struct.pack(">IIBBBBB", width, height, BYTE_DEPTH, COLOR_PALETTE, 0, 0, 0)
   out = SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"PLTE", plte)
   if trns is not None:
      out += _chunk(b"tRNS", trns)
   return out + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")


def read(path: str | Path) -> tuple[int, int, bytearray]:
   """!A palette PNG's indices (the engine's bitmap.read_png_indices()).
   @param path  the file
   @return (width, height, indices)
   """
   bm = engine.bitmap()
   try:
      return bm.read_png_indices(path)
   except bm.BitmapError as e:
      raise ValueError(str(e)) from None
