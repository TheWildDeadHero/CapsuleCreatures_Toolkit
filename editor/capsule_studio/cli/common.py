"""!Argument parsing and output helpers shared by the command groups."""
from __future__ import annotations

from pathlib import Path

from ..core import engine
from ..core.document import Document

## Length of a "#rrggbb" color: the hash sign and six hex digits.
RGB_TEXT_LENGTH = 7
## Hex digits per color channel in "#rrggbb".
HEX_DIGITS_PER_CHANNEL = 2
## Number base of the color digits.
HEX_BASE = 16
## Where the red, green and blue digits start in "#rrggbb".
RGB_CHANNEL_OFFSETS = (1, 3, 5)
## Bytes per pixel in an RGB image.
RGB_BYTES_PER_PIXEL = 3


def parse_size(text: str) -> tuple[int, int]:
   """!"32x16" to (32, 16).
   @param text  WIDTHxHEIGHT
   @return (w, h)
   """
   try:
      w, h = text.lower().split("x")
      return int(w), int(h)
   except ValueError:
      raise ValueError(f"size must look like 32x32, got {text!r}") from None


def parse_rows(text: str, count: int) -> list[int]:
   """!Step selections like "0,2-4" or "all".
   @param text   comma-separated indices and ranges, or "all"
   @param count  number of steps (for "all" and range checks)
   @return sorted list of indices
   """
   if text == "all":
      return list(range(count))
   rows: set[int] = set()
   for part in text.split(","):
      part = part.strip()
      if "-" in part:
         a, b = part.split("-", 1)
         rows.update(range(int(a), int(b) + 1))
      elif part:
         rows.add(int(part))
   bad = [r for r in rows if not 0 <= r < count]
   if bad:
      raise ValueError(f"step {bad[0]} does not exist (there are {count})")
   return sorted(rows)


def parse_rgb(text: str) -> tuple[int, ...]:
   """!"#ff00ff" to (255, 0, 255).
   @param text  a hash sign and six hex digits
   @return (r, g, b)
   """
   if len(text) != RGB_TEXT_LENGTH or text[0] != "#":
      raise ValueError(f"colors look like #ff00ff, got {text!r}")
   return tuple(int(text[i:i + HEX_DIGITS_PER_CHANNEL], HEX_BASE) for i in RGB_CHANNEL_OFFSETS)


def open_doc(path: str | Path) -> Document:
   """!Opens a manifest, or starts one when the file does not exist yet.
   @param path  manifest path
   @return Document
   """
   p = Path(path)
   if p.exists():
      return Document.open(p)
   d = Document(path=p)
   d.data["id"] = p.stem
   return d


def read_image(path: str | Path) -> tuple[int, int, bytearray]:
   """!Reads an image for import. The command line reads PNG files with the
   engine's own reader, so it needs no imaging library.
   @param path  PNG file
   @return (w, h, RGBA)
   """
   return engine.bitmap().read_png(path)


def write_rgb_png(path: str | Path, w: int, h: int, rgb: bytes | bytearray) -> None:
   """!Writes an RGB image (3 bytes per pixel) as a PNG.
   @param path  output file
   @param w     width
   @param h     height
   @param rgb   pixels
   @return None
   """
   # Each pixel gets an opaque alpha byte after its three color bytes.
   rgba = bytearray()
   for o in range(0, len(rgb), RGB_BYTES_PER_PIXEL):
      rgba += rgb[o:o + RGB_BYTES_PER_PIXEL] + b"\xff"
   engine.bitmap().write_png(path, w, h, rgba)
