"""!Preparing imported bitmaps for a sprite: size and transparency.

Images are (width, height, RGBA bytearray) as in the engine's bitmap module.
Decoding files of any format is left to the caller (Qt in the editor, the
engine's PNG reader on the command line); everything here is plain Python.
"""
from __future__ import annotations

from collections.abc import Sequence

## An image: (width, height, RGBA bytes, 4 per pixel, rows top to bottom).
RgbaImage = tuple[int, int, bytearray]
## An 8-bit color without alpha: (r, g, b), 0-255.
Rgb = tuple[int, int, int]

## Leading fields of an image tuple that give its size: image[:IMAGE_SIZE_FIELDS] is (width, height).
IMAGE_SIZE_FIELDS = 2
## Bytes per RGBA pixel.
RGBA_BYTES = 4
## Bytes of color (r, g, b) at the start of an RGBA pixel.
RGB_BYTES = 3
## Offset of the alpha byte in an RGBA pixel.
ALPHA = 3
## Offset of the green byte in an RGBA pixel.
GREEN = 1
## Offset of the blue byte in an RGBA pixel.
BLUE = 2
## Divisor that halves: centring offsets, and half the divisor added before a division to round it.
HALF = 2

## How an image of another size is made to fit.
FIT_MODES = ("center", "nearest", "smooth")
## How transparency is decided.
TRANSPARENCY_MODES = ("alpha", "corner", "color")


def blank(w: int, h: int) -> RgbaImage:
   """!A fully transparent image.
   @param w  width
   @param h  height
   @return (w, h, RGBA)
   """
   return w, h, bytearray(w * h * RGBA_BYTES)


def mirror(image: RgbaImage) -> RgbaImage:
   """![S3] An image mirrored horizontally (a direction grid's right frame from its left one).
   @param image  (w, h, RGBA)
   @return (w, h, RGBA)
   """
   w, h, px = image
   out = bytearray()
   for y in range(h):
      row = px[y * w * RGBA_BYTES:(y + 1) * w * RGBA_BYTES]
      for x in reversed(range(w)):
         out += row[x * RGBA_BYTES:(x + 1) * RGBA_BYTES]
   return w, h, out


def center(image: RgbaImage, w: int, h: int) -> RgbaImage:
   """!Places an image at the middle of a w x h canvas, cropping or padding
   with transparency, pixels unchanged.
   @param image  (w, h, RGBA)
   @param w      target width
   @param h      target height
   @return (w, h, RGBA)
   """
   sw, sh, src = image
   out = bytearray(w * h * RGBA_BYTES)
   # Offset of the source's top-left on the canvas (negative when the source is larger: cropped).
   ox, oy = (w - sw) // HALF, (h - sh) // HALF
   for y in range(h):
      sy = y - oy
      if not 0 <= sy < sh:
         continue
      for x in range(w):
         sx = x - ox
         if 0 <= sx < sw:
            s, d = (sy * sw + sx) * RGBA_BYTES, (y * w + x) * RGBA_BYTES
            out[d:d + RGBA_BYTES] = src[s:s + RGBA_BYTES]
   return w, h, out


def _fit_size(sw: int, sh: int, w: int, h: int) -> tuple[int, int]:
   """!Largest size with the source's aspect ratio inside w x h.
   @param sw  source width
   @param sh  source height
   @param w   box width
   @param h   box height
   @return (width, height), each at least 1
   """
   # Compares the aspect ratios sw / sh and w / h without division; the other side is rounded.
   if sw * h > sh * w:
      return w, max(1, (sh * w + sw // HALF) // sw)
   return max(1, (sw * h + sh // HALF) // sh), h


def scale_nearest(image: RgbaImage, nw: int, nh: int) -> RgbaImage:
   """!Resizes by repeating or dropping pixels (keeps pixel art crisp).
   @param image  (w, h, RGBA)
   @param nw     new width
   @param nh     new height
   @return (nw, nh, RGBA)
   """
   sw, sh, src = image
   out = bytearray(nw * nh * RGBA_BYTES)
   for y in range(nh):
      sy = y * sh // nh
      for x in range(nw):
         s, d = (sy * sw + x * sw // nw) * RGBA_BYTES, (y * nw + x) * RGBA_BYTES
         out[d:d + RGBA_BYTES] = src[s:s + RGBA_BYTES]
   return nw, nh, out


def scale_smooth(image: RgbaImage, nw: int, nh: int) -> RgbaImage:
   """!Resizes by averaging the source area under each pixel (for
   reductions) with alpha-weighted color, so edges don't darken.
   Enlarging falls back to nearest, which suits GBA-sized output.
   @param image  (w, h, RGBA)
   @param nw     new width
   @param nh     new height
   @return (nw, nh, RGBA)
   """
   sw, sh, src = image
   if nw >= sw and nh >= sh:
      return scale_nearest(image, nw, nh)
   out = bytearray(nw * nh * RGBA_BYTES)
   for y in range(nh):
      # Source rows [y0, y1) under this pixel, at least one.
      y0, y1 = y * sh // nh, max(y * sh // nh + 1, (y + 1) * sh // nh)
      for x in range(nw):
         x0, x1 = x * sw // nw, max(x * sw // nw + 1, (x + 1) * sw // nw)
         # Sums of alpha-weighted color, of alpha, and the pixel count.
         r = g = b = a = n = 0
         for sy in range(y0, y1):
            for sx in range(x0, x1):
               o = (sy * sw + sx) * RGBA_BYTES
               pa = src[o + ALPHA]
               r += src[o] * pa
               g += src[o + GREEN] * pa
               b += src[o + BLUE] * pa
               a += pa
               n += 1
         d = (y * nw + x) * RGBA_BYTES
         if a:
            # Rounded averages: color weighted by alpha, alpha over all pixels (fully transparent stays 0).
            out[d:d + RGBA_BYTES] = bytes(((r + a // HALF) // a, (g + a // HALF) // a, (b + a // HALF) // a,
                                           (a + n // HALF) // n))
   return nw, nh, out


def fit(image: RgbaImage, w: int, h: int, mode: str = "center") -> RgbaImage:
   """!Makes an image exactly w x h.
   @param image  (w, h, RGBA)
   @param w      target width
   @param h      target height
   @param mode   one of FIT_MODES: "center" crops or pads at 1:1; "nearest"
                 and "smooth" scale to fit, keeping the aspect ratio, then pad
   @return (w, h, RGBA)
   """
   if mode not in FIT_MODES:
      raise ValueError(f"fit mode must be one of {FIT_MODES}")
   if image[:IMAGE_SIZE_FIELDS] == (w, h):
      return image
   if mode == "center":
      return center(image, w, h)
   nw, nh = _fit_size(image[0], image[1], w, h)
   scaled = (scale_nearest if mode == "nearest" else scale_smooth)(image, nw, nh)
   return center(scaled, w, h)


def key_color(image: RgbaImage, rgb: Sequence[int]) -> RgbaImage:
   """!Makes every pixel of one color transparent (for formats without alpha).
   @param image  (w, h, RGBA)
   @param rgb    (r, g, b), 0-255
   @return (w, h, RGBA), a copy
   """
   w, h, src = image
   out = bytearray(src)
   for o in range(0, len(out), RGBA_BYTES):
      if (out[o], out[o + GREEN], out[o + BLUE]) == tuple(rgb):
         out[o + ALPHA] = 0
   return w, h, out


def corner_color(image: RgbaImage) -> Rgb | None:
   """!Color of the top-left pixel (a common transparency convention).
   @param image  (w, h, RGBA)
   @return (r, g, b), or None for an empty image
   """
   w, h, src = image
   return tuple(src[0:RGB_BYTES]) if w and h else None


def prepare(image: RgbaImage, w: int, h: int, fit_mode: str = "center", transparency: str = "alpha",
            color: Sequence[int] | None = None) -> RgbaImage:
   """!The whole import step: transparency first (at the source's own
   pixels), then fitting to the sprite size.
   @param image         (w, h, RGBA) as decoded
   @param w             sprite width
   @param h             sprite height
   @param fit_mode      one of FIT_MODES
   @param transparency  one of TRANSPARENCY_MODES: "alpha" keeps the file's
                        alpha; "corner" keys out the top-left pixel's color;
                        "color" keys out @p color
   @param color         (r, g, b) for "color"
   @return (w, h, RGBA)
   """
   if transparency not in TRANSPARENCY_MODES:
      raise ValueError(f"transparency must be one of {TRANSPARENCY_MODES}")
   if transparency == "corner":
      c = corner_color(image)
      if c is not None:
         image = key_color(image, c)
   elif transparency == "color":
      if color is None:
         raise ValueError("transparency 'color' needs a color")
      image = key_color(image, color)
   return fit(image, w, h, fit_mode)
