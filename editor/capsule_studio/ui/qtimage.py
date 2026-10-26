"""!Conversions between Qt images and the core's (w, h, RGBA) images."""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6 import QtGui

from ..core import preview
from ..core.imaging import RGBA_BYTES

if TYPE_CHECKING:
   from pathlib import Path

   from ..core.imaging import RgbaImage

## Alpha of an opaque pixel.
OPAQUE = 255


def load_rgba(path: str | Path) -> RgbaImage:
   """!Reads any image format Qt supports (PNG, BMP, GIF, JPEG, ...).
   @param path  file path
   @return (w, h, RGBA bytearray)
   @throws ValueError when the file can't be read
   """
   img = QtGui.QImage(str(path))
   if img.isNull():
      raise ValueError(f"{path}: not an image Qt can read")
   return from_qimage(img)


def from_qimage(img: QtGui.QImage) -> RgbaImage:
   """!A QImage as (w, h, RGBA).
   @param img  QImage
   @return (w, h, RGBA bytearray)
   """
   img = img.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
   w, h, stride = img.width(), img.height(), img.bytesPerLine()
   try:
      raw = bytes(img.constBits())[:stride * h]
   except (TypeError, ValueError):   # bindings without buffer access: go pixel by pixel
      out = bytearray()
      for y in range(h):
         for x in range(w):
            c = img.pixelColor(x, y)
            out += bytes((c.red(), c.green(), c.blue(), c.alpha()))
      return w, h, out

   # Qt pads each row to its stride: keep only the w pixels of every row.
   out = bytearray()
   for y in range(h):
      out += raw[y * stride:y * stride + w * RGBA_BYTES]
   return w, h, out


def to_qimage(w: int, h: int, rgba: bytes | bytearray) -> QtGui.QImage:
   """!(w, h, RGBA) as a QImage (an independent copy).
   @param w     width
   @param h     height
   @param rgba  pixels
   @return QImage
   """
   return QtGui.QImage(bytes(rgba), w, h, w * RGBA_BYTES, QtGui.QImage.Format.Format_RGBA8888).copy()


def indexed_qimage(w: int, h: int, indices: bytes | bytearray | Sequence[int],
                   palette: Sequence[Sequence[int]]) -> QtGui.QImage:
   """!Palette indices in GBA colors (index 0 transparent) as a QImage.
   @param w        width
   @param h        height
   @param indices  bytes of entry numbers
   @param palette  list of 5-bit colors (entries 1..n)
   @return QImage
   """
   out = bytearray(w * h * RGBA_BYTES)
   for i, v in enumerate(indices):
      if v and v <= len(palette):   # entry v is palette[v - 1]; entry 0 and unknown entries stay transparent
         out[i * RGBA_BYTES:i * RGBA_BYTES + RGBA_BYTES] = bytes(preview.expand(palette[v - 1]) + (OPAQUE,))
   return to_qimage(w, h, out)


def screen_qimage(screen: preview.Screen) -> QtGui.QImage:
   """!A preview Screen as a QImage.
   @param screen  preview.Screen
   @return QImage
   """
   return QtGui.QImage(bytes(screen.rgb), preview.WIDTH, preview.HEIGHT, preview.WIDTH * preview.PIXEL_BYTES,
                       QtGui.QImage.Format.Format_RGB888).copy()
