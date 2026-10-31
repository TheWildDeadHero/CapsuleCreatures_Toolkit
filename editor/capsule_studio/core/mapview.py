"""!Pictures of maps, metatiles and tile sheets, drawn from compiled data
the way the engine draws them (pure Python; the UI and the command line
turn the RGBA bytes into images).

Images are (w, h, RGBA bytearray). Colors are the GBA's (5 bits per channel,
expanded); palette entry 0 is transparent.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from . import engine
from .imaging import BLUE, GREEN, RGBA_BYTES
from .maps import CHUNK, cell_fields
from .preview import BLUE_SHIFT, CHANNEL_MASK, EXPAND_SHIFT, GREEN_SHIFT, REPLICATE_SHIFT

if TYPE_CHECKING:
   from .imaging import Rgb, RgbaImage

## A compile_map() or compile_world() result (lists and dicts as the engine's map_compiler builds them).
CompiledData = dict[str, Any]
## An 8-bit color with alpha: (r, g, b, a), 0-255.
Rgba = tuple[int, int, int, int]
## [S3] A cell's tile layer: (x, y, layer).
CellLayer = tuple[int, int, int]
## [S3] What a cell's layer shows: a metatile id, or four map entries (top-left, top-right, bottom-left, bottom-right).
CellShow = int | tuple[int, ...]

## Collision-view colors (RGBA): blocked, not passable on foot, moves the walker, encounter.
OVERLAY = [(248, 32, 32, 150), (48, 80, 248, 150), (248, 224, 0, 150), (32, 224, 64, 120)]
## OVERLAY index of a blocked cell.
OVERLAY_BLOCKED = 0
## OVERLAY index of a cell that is not passable on foot.
OVERLAY_NOT_WALKABLE = 1
## OVERLAY index of a cell whose behavior moves the walker (slide, ledge, push).
OVERLAY_MOVES = 2
## OVERLAY index of an encounter cell.
OVERLAY_ENCOUNTER = 3

## Pixels per side of a tile.
TILE = 8
## Pixels per side of a metatile (2x2 tiles).
METATILE = 16
## Tiles in a metatile.
METATILE_TILES = 4
## Alpha of an opaque pixel, the largest alpha.
OPAQUE = 255
## Map entry bits of the tile number.
ENTRY_TILE_MASK = 0x3FF
## Map entry bit: flip the tile horizontally.
ENTRY_HFLIP = 0x400
## Map entry bit: flip the tile vertically.
ENTRY_VFLIP = 0x800
## Map entry bits of both flips.
ENTRY_FLIPS = ENTRY_HFLIP | ENTRY_VFLIP
## Bit position of the palette bank in a map entry.
ENTRY_BANK_SHIFT = 12
## Colors of a palette bank besides the transparent entry 0.
PALETTE_COLORS = 15
## Color (BGR555 magenta) drawn for a palette bank the map does not have.
MISSING_COLOR = 0x7C1F
## Entries of a palette bank, entry 0 (transparent) included.
BANK_SIZE = PALETTE_COLORS + 1
## Gray ramp step per palette index (5-bit channels: index 15 is 30 of 31), for a fixed sheet's bank without colors.
GRAY_STEP = 2


def bgr_to_rgb(c: int) -> Rgb:
   """!A BGR555 color as 8-bit RGB.
   @param c  BGR555
   @return (r, g, b)
   """
   # Each 5-bit channel is shifted up with its top bits repeated below (as preview.expand()).
   channels = (c & CHANNEL_MASK, c >> GREEN_SHIFT & CHANNEL_MASK, c >> BLUE_SHIFT & CHANNEL_MASK)
   return tuple(((v << EXPAND_SHIFT) | (v >> REPLICATE_SHIFT)) for v in channels)


def blank(w: int, h: int, rgba: Sequence[int] = (0, 0, 0, 0)) -> RgbaImage:
   """!A filled image.
   @param w     width
   @param h     height
   @param rgba  fill color
   @return (w, h, RGBA)
   """
   return w, h, bytearray(bytes(rgba) * (w * h))


def draw_tile(img: RgbaImage, ox: int, oy: int, tile: Sequence[Sequence[int]], palette: Sequence[int],
              entry_flags: int) -> None:
   """!Draws one 8x8 tile into an image (transparent pixels skipped).
   @param img          (w, h, RGBA) target
   @param ox           left
   @param oy           top
   @param tile         8 rows of 8 indices
   @param palette      15 BGR555 colors (entries 1-15)
   @param entry_flags  map entry bits: 0x400 hflip, 0x800 vflip
   @return None
   """
   w, h, px = img
   hf, vf = entry_flags & ENTRY_HFLIP, entry_flags & ENTRY_VFLIP
   for y in range(TILE):
      sy = TILE - 1 - y if vf else y
      row = tile[sy]
      ty = oy + y
      if not 0 <= ty < h:
         continue
      for x in range(TILE):
         v = row[TILE - 1 - x if hf else x]
         tx = ox + x
         if v and 0 <= tx < w:
            r, g, b = bgr_to_rgb(palette[v - 1])   # the palette starts at entry 1
            o = (ty * w + tx) * RGBA_BYTES
            px[o:o + RGBA_BYTES] = bytes((r, g, b, OPAQUE))


def draw_entry(img: RgbaImage, ox: int, oy: int, mp: CompiledData, entry: int) -> None:
   """!Draws one background map entry of a compiled map.
   @param img    target image
   @param ox     left
   @param oy     top
   @param mp     compiled map (map_compiler.compile_map())
   @param entry  map entry (tile | flips | bank << 12)
   @return None
   """
   t = entry & ENTRY_TILE_MASK
   if t >= len(mp["tiles"]):   # I2: a raw entry may name a tile no tileset of the map places (blank VRAM)
      return
   bank = entry >> ENTRY_BANK_SHIFT
   pal = mp["palettes"][bank] if bank < len(mp["palettes"]) else [MISSING_COLOR] * PALETTE_COLORS
   draw_tile(img, ox, oy, mp["tiles"][t], pal, entry & ENTRY_FLIPS)


class TileCache:
   """!Rows of RGBA bytes per (tile, palette bank, flips) of one compiled map, so many metatile pictures drawing
   the same tiles convert each once (I2: an imported map's "all" dictionary holds 1,000 and more metatiles).
   Palette index 0 is transparent, or the backdrop color when one is given."""

   def __init__(self, mp: CompiledData, backdrop: Rgba | None = None) -> None:
      """!Starts an empty cache.
      @param mp        compiled map
      @param backdrop  RGBA drawn for palette index 0, or None for transparent
      """
      ## The compiled map.
      self.mp = mp
      ## Palette index 0's bytes.
      self.zero = bytes(backdrop) if backdrop is not None else bytes(RGBA_BYTES)
      ## Converted banks: bank -> 16 entries of RGBA bytes.
      self._banks: dict[int, list[bytes]] = {}
      ## Converted tiles: (tile, bank, flips) -> 8 rows of TILE * RGBA_BYTES bytes.
      self._tiles: dict[tuple[int, int, int], list[bytes]] = {}

   def bank(self, bank: int) -> list[bytes]:
      """!A palette bank as RGBA bytes (entry 0 the cache's zero; a bank the map lacks is magenta).
      @param bank  palette bank
      @return 16 entries
      """
      if bank not in self._banks:
         pals = self.mp["palettes"]
         colors = pals[bank] if bank < len(pals) and pals[bank] is not None else [MISSING_COLOR] * PALETTE_COLORS
         self._banks[bank] = [self.zero] + [bytes(bgr_to_rgb(c) + (OPAQUE,)) for c in colors]
      return self._banks[bank]

   def entry_rows(self, entry: int) -> list[bytes]:
      """!One map entry as 8 rows of RGBA bytes, flips applied.
      @param entry  map entry (tile | flips | bank << 12)
      @return rows (index 0 pixels: the cache's zero)
      """
      t, bank, flips = entry & ENTRY_TILE_MASK, entry >> ENTRY_BANK_SHIFT, entry & ENTRY_FLIPS
      key = (t, bank, flips)
      rows = self._tiles.get(key)
      if rows is None:
         if t >= len(self.mp["tiles"]):
            rows = [self.zero * TILE] * TILE
         else:
            pal = self.bank(bank)
            tile = self.mp["tiles"][t]
            src = [tile[TILE - 1 - y] for y in range(TILE)] if flips & ENTRY_VFLIP else list(tile)
            rows = [b"".join(pal[v] for v in (reversed(r) if flips & ENTRY_HFLIP else r)) for r in src]
         self._tiles[key] = rows
      return rows

   def metatile(self, index: int) -> RgbaImage:
      """!One metatile as a 16x16 image.
      @param index  metatile id (an id past the map's metatiles draws nothing)
      @return (16, 16, RGBA)
      """
      if not 0 <= index < len(self.mp["metatiles"]):
         return METATILE, METATILE, bytearray(self.zero * (METATILE * METATILE))
      return self.entries(self.mp["metatiles"][index])

   def entries(self, e: Sequence[int]) -> RgbaImage:
      """![S3] Four map entries (one metatile layer: a cell override's or a door frame's) as a 16x16 image.
      @param e  the entries: top-left, top-right, bottom-left, bottom-right
      @return (16, 16, RGBA)
      """
      # tiles in reading order: top-left, top-right, bottom-left, bottom-right; a metatile row joins two tile rows
      tl, tr, bl, br = (self.entry_rows(e[i]) for i in range(METATILE_TILES))
      out = bytearray()
      for left, right in ((tl, tr), (bl, br)):
         for y in range(TILE):
            out += left[y]
            out += right[y]
      return METATILE, METATILE, out


def draw_metatile(img: RgbaImage, ox: int, oy: int, mp: CompiledData, index: int) -> None:
   """!Draws a metatile (its four tiles; transparent pixels skipped).
   @param img    target image
   @param ox     left
   @param oy     top
   @param mp     compiled map
   @param index  metatile id (NO_METATILE and out-of-range ids draw nothing)
   @return None
   """
   if not 0 <= index < len(mp["metatiles"]):
      return
   e = mp["metatiles"][index]
   for i in range(METATILE_TILES):
      # Tiles in reading order: bit 0 of i is the column, bit 1 the row.
      draw_entry(img, ox + (i & 1) * TILE, oy + (i >> 1) * TILE, mp, e[i])


def metatile_image(mp: CompiledData, index: int, backdrop: bool = True) -> RgbaImage:
   """!One metatile as a 16x16 image.
   @param mp        compiled map
   @param index     metatile id
   @param backdrop  fill with the map's backdrop first
   @return (16, 16, RGBA)
   """
   return TileCache(mp, bgr_to_rgb(mp["backdrop"]) + (OPAQUE,) if backdrop else None).metatile(index)


def metatile_images(mp: CompiledData, backdrop: bool = True) -> list[RgbaImage]:
   """!Every metatile of a compiled map as 16x16 images, the tiles they share converted once (I2).
   @param mp        compiled map
   @param backdrop  fill with the map's backdrop first
   @return one (16, 16, RGBA) per metatile id
   """
   cache = TileCache(mp, bgr_to_rgb(mp["backdrop"]) + (OPAQUE,) if backdrop else None)
   return [cache.metatile(i) for i in range(len(mp["metatiles"]))]


def draw_order(mp: CompiledData) -> list[int]:
   """!A compiled map's tile layer indices back to front, the way the GBA
   stacks them (higher priority numbers behind; on a tie the higher BG).
   @param mp  compiled map
   @return list of layer indices
   """
   # Each compiled layer is (bg, priority).
   ls = mp["layers"]
   return sorted(range(len(ls)), key=lambda i: (-ls[i][1], -ls[i][0]))


def overlay_category(world: CompiledData | None, cell: int) -> int | None:
   """!Collision-view category of a compiled attribute cell (for walking on foot).
   @param world  compile_world() result (for behaviors), or None
   @param cell   32-bit attribute cell (world behavior index)
   @return index into OVERLAY, or None
   """
   # Compiled cells pack their fields like the manifest's (maps.cell_fields()).
   fields = cell_fields()
   collision_mask, collision_shift = fields["collision"]
   behavior_mask, behavior_shift = fields["behavior"]
   encounter_mask, encounter_shift = fields["encounter"]
   if cell >> collision_shift & collision_mask:
      return OVERLAY_BLOCKED
   beh = cell >> behavior_shift & behavior_mask
   behaviors = world["behaviors"] if world else []
   if beh < len(behaviors):
      mask, kind, _, _ = behaviors[beh]
      if not mask & 1:   # bit 0 of the passability mask: vehicle class 0, on foot
         return OVERLAY_NOT_WALKABLE
      if kind:
         return OVERLAY_MOVES
   if cell >> encounter_shift & encounter_mask:
      return OVERLAY_ENCOUNTER
   return None


def blend(img: RgbaImage, ox: int, oy: int, w: int, h: int, rgba: Rgba) -> None:
   """!Tints a rectangle.
   @param img   target image
   @param ox    left
   @param oy    top
   @param w     width
   @param h     height
   @param rgba  color with alpha
   @return None
   """
   iw, ih, px = img
   r, g, b, a = rgba
   for y in range(max(0, oy), min(ih, oy + h)):
      for x in range(max(0, ox), min(iw, ox + w)):
         # Mixes the tint in by its alpha: a / OPAQUE of the tint, the rest of the pixel.
         o = (y * iw + x) * RGBA_BYTES
         px[o] = (px[o] * (OPAQUE - a) + r * a) // OPAQUE
         px[o + GREEN] = (px[o + GREEN] * (OPAQUE - a) + g * a) // OPAQUE
         px[o + BLUE] = (px[o + BLUE] * (OPAQUE - a) + b * a) // OPAQUE


def render_map(mp: CompiledData, x0: int, y0: int, w: int, h: int, world: CompiledData | None = None,
               collision: bool = False, layers: Collection[int] | None = None,
               overrides: Mapping[CellLayer, CellShow] | None = None) -> RgbaImage:
   """!Draws a rectangle of a compiled map as the engine shows it (border included).
   @param mp         compiled map
   @param x0         left, metatiles
   @param y0         top, metatiles
   @param w          width, metatiles
   @param h          height, metatiles
   @param world      compile_world() result (needed for collision view behaviors)
   @param collision  tint cells by the collision-view categories
   @param layers     tile layer indices to draw (None: all)
   @param overrides  [S3] what some cells' layers show instead (cell overrides, door frames): (x, y, layer) -> a
                     metatile id (NO_METATILE: nothing) or a tuple of four map entries; None: none
   @return (w*16, h*16, RGBA)
   """
   mc = engine.tool("map_compiler")
   img = blank(w * METATILE, h * METATILE, bgr_to_rgb(mp["backdrop"]) + (OPAQUE,))
   order = [k for k in draw_order(mp) if layers is None or k in layers]
   cache = TileCache(mp)
   # metatile id, or a tuple of four entries -> its RGBA bytes (I2: drawn once per id, not per cell)
   pictures: dict[CellShow, bytes] = {}
   iw, _ih, px = img
   row_bytes = METATILE * RGBA_BYTES
   for y in range(h):
      for x in range(w):
         for k in order:
            shown = overrides.get((x0 + x, y0 + y, k)) if overrides else None
            index = mc.metatile_at(mp, k, x0 + x, y0 + y) if shown is None else shown
            if isinstance(index, int) and not 0 <= index < len(mp["metatiles"]):
               continue
            if index not in pictures:
               _w, _h, rgba = cache.metatile(index) if isinstance(index, int) else cache.entries(index)
               pictures[index] = bytes(rgba)
            src = pictures[index]
            for row in range(METATILE):
               o = ((y * METATILE + row) * iw + x * METATILE) * RGBA_BYTES
               line = src[row * row_bytes:(row + 1) * row_bytes]
               for i in range(METATILE):
                  # copy opaque pixels only (alpha is the last byte of each pixel)
                  if line[i * RGBA_BYTES + RGBA_BYTES - 1]:
                     px[o + i * RGBA_BYTES:o + (i + 1) * RGBA_BYTES] = line[i * RGBA_BYTES:(i + 1) * RGBA_BYTES]
         if collision:
            cat = overlay_category(world, mc.cell_at(mp, x0 + x, y0 + y))
            if cat is not None:
               blend(img, x * METATILE, y * METATILE, METATILE, METATILE, OVERLAY[cat])
   return img


def map_bounds(mp: CompiledData) -> tuple[int, int, int, int]:
   """!Metatile rectangle covering a compiled map's chunks.
   @param mp  compiled map
   @return (x0, y0, w, h) in metatiles
   """
   # The compiled chunk grid is in chunks.
   return mp["grid_x0"] * CHUNK, mp["grid_y0"] * CHUNK, mp["grid_w"] * CHUNK, mp["grid_h"] * CHUNK


def sheet_bank_colors(ts: Any, sheet: str, bank: int | None = None) -> list[int]:
   """!The 15 colors (entries 1-15, BGR555) a sheet is shown in: its palette group's, or for a fixed tileset's
   indexed sheet (I2) one of the tileset's banks.
   @param ts     compiled Tileset
   @param sheet  sheet name
   @param bank   a fixed tileset's palette bank (VRAM bank number), or None for its first
   @return 15 colors (a bank the tileset does not list: a gray ramp)
   """
   s = ts.sheets[sheet]
   if s.group in ts.palettes:
      return ts.palettes[s.group][0]
   place = getattr(ts, "place", None) or {}
   k = (bank if bank is not None else place.get("palette", 0)) - place.get("palette", 0)
   colors = getattr(ts, "bank_colors", [])
   if 0 <= k < len(colors):
      return colors[k][1:]
   # no colors for that bank: palette index i as gray, so the indices still show
   return [GRAY_STEP * i | GRAY_STEP * i << GREEN_SHIFT | GRAY_STEP * i << BLUE_SHIFT for i in range(1, BANK_SIZE)]


def sheet_image(ts: Any, sheet: str, bank: int | None = None) -> RgbaImage:
   """!A tileset sheet in its own colors (I2: a fixed tileset's indexed sheet in one of its banks).
   @param ts     compiled Tileset (map_compiler.compile_tileset())
   @param sheet  sheet name
   @param bank   a fixed tileset's palette bank, or None (see sheet_bank_colors())
   @return (w, h, RGBA)
   """
   s = ts.sheets[sheet]
   colors = sheet_bank_colors(ts, sheet, bank)
   w, h = s.w * TILE, s.h * TILE   # the sheet's size is in tiles
   pal = [bytes(RGBA_BYTES)] + [bytes(bgr_to_rgb(c) + (OPAQUE,)) for c in colors]
   out = bytearray(w * h * RGBA_BYTES)
   for i in range(s.w * s.h):
      tile = s.tile(i, sheet)
      tx, ty = (i % s.w) * TILE, (i // s.w) * TILE
      for y in range(TILE):
         o = ((ty + y) * w + tx) * RGBA_BYTES
         out[o:o + TILE * RGBA_BYTES] = b"".join(pal[v] for v in tile[y])
   return w, h, out
