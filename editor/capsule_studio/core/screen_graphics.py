"""![S6] Screen graphics (engine UC, D-33): the asset kinds "tiles", "tilemap" and "palette" of an asset manifest
(capsule.assets/1), which a full-screen scene (capsule/screen/screen.h) loads where its own plan says.

- tiles: raw tile bytes ("data": a .4bpp / .8bpp file beside the manifest) or "shapes" drawn with palette indices on
  a "width" x "height" canvas, cut into tiles row by row or by "block" [columns, rows] (sprite frames); "bpp" 4 or 8;
  "columns" records the source image's tiles per row (the previews' sheet width).
- tilemap: raw 16-bit map entries ("data": a .bin file) or "cells" (entries: tile | h-flip 0x400 | v-flip 0x800 |
  bank << 12), "affine" for one tile byte a cell, "columns" entries per stored row (32: screen-block order).
- palette: "colors" bank by bank (16 a bank), each "#rrggbb" or a raw BGR555 number; entry 0 of a bank is kept.

The engine's tools/screen_assets.py (through asset_compiler) decides what is valid; every change here compiles the
changed asset first. Previews decode the compiled words as video memory holds them. import_png() turns an indexed
PNG into a tiles file (identical tiles shared, flipped ones too when asked), a tilemap and a palette, as the
reference games' graphics converters lay them out; export_png() writes a tiles asset back as an indexed PNG for a
paint program.

Functions that change a Document must run inside its edit(). Nothing here imports Qt.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import engine, indexed_png
from .imaging import RGBA_BYTES
from .mapview import (BANK_SIZE, ENTRY_BANK_SHIFT, ENTRY_HFLIP, ENTRY_TILE_MASK, ENTRY_VFLIP, GRAY_STEP,
                      MISSING_COLOR, OPAQUE, TILE, bgr_to_rgb, blank)
from .preview import BLUE_SHIFT, CHANNEL_MASK, EXPAND_SHIFT, GREEN_SHIFT

if TYPE_CHECKING:
   from .document import AssetReport, Document
   from .imaging import RgbaImage

## A parsed JSON object (an asset).
JsonDict = dict[str, Any]

## The three kinds, in the order the panel lists them.
KINDS = ("tiles", "tilemap", "palette")
## Key namespace of each kind ("tiles:NAME").
PREFIXES = {"tiles": "tiles:", "tilemap": "tilemap:", "palette": "palette:"}
## Folder beside the manifest that imported data files go to.
DATA_FOLDER = "screen"
## Suffix of a 4bpp tiles file and of an 8bpp one.
SUFFIX_4BPP, SUFFIX_8BPP = ".4bpp", ".8bpp"

## Bits per pixel of 4bpp and 8bpp tiles.
BPP4, BPP8 = 4, 8
## Bytes of one 4bpp tile and of one 8bpp tile.
TILE_BYTES_4BPP, TILE_BYTES_8BPP = 32, 64
## Bytes of a 32-bit word.
WORD_BYTES = 4
## Bits of a nibble (a 4bpp pixel) and its mask.
NIBBLE_BITS, NIBBLE_MASK = 4, 0xF
## Pixels of a 4bpp byte.
PIXELS_PER_BYTE_4BPP = 2
## Highest palette index of an 8bpp pixel.
MAX_INDEX_8BPP = 255
## Palette banks of one palette memory (BG or OBJ).
BANKS = 16
## Colours of one palette memory.
PALETTE_ENTRIES = BANKS * BANK_SIZE
## Highest bank number.
MAX_BANK = BANKS - 1
## Highest raw BGR555 colour.
MAX_BGR555 = 0x7FFF
## Bits an 8-bit channel drops for 5 bits.
CHANNEL_DROP = EXPAND_SHIFT
## Bits of a byte, and its mask.
BITS_PER_BYTE, BYTE_MASK = 8, 0xFF
## Shifts of the red and green bytes of a 24-bit "rrggbb" number (blue is the low byte).
RED_SHIFT_24, GREEN_SHIFT_24 = 16, 8
## Screen blocks side by side in the widest layer map (64 cells).
WIDE_BLOCKS = 2
## Bytes of one text-mode map entry.
ENTRY_BYTES = 2
## Highest map entry tile number.
MAX_TILE = ENTRY_TILE_MASK
## Cells across one screen block (the default stored row).
ROW_CELLS = 32
## Rows of cells a new tilemap gets (the screen's 20 visible rows, rounded up to the block's).
NEW_MAP_ROWS = 32
## A new tiles canvas: 4 tiles across, 1 down.
NEW_TILES_SIZE = (32, 8)
## Tiles per row of a sheet preview when the asset does not record its columns.
DEFAULT_SHEET_COLUMNS = 16
## Pixels per side of a palette swatch.
SWATCH = 12
## Bank layout of a palette preview: swatches across.
SWATCHES_ACROSS = BANK_SIZE
## Hex digits of a "#rrggbb" colour, and the base.
HEX_DIGITS, HEX_BASE = 6, 16
## A "#rrggbb" colour.
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
## An entry as text: "t12 p3 h" (tile, palette bank, flips) or a raw number.
ENTRY_WORD = re.compile(r"(?P<field>[tp])(?P<number>\d+)|(?P<flips>h|v|hv|vh)")


class ScreenGraphicsError(ValueError):
   """!A change the compiler or the format refuses."""


def _ac() -> Any:
   """!The engine's asset compiler.
   @return module
   """
   return engine.asset_compiler()


def available() -> bool:
   """!Whether the engine in use has the screen graphics kinds (UC).
   @return True when asset_compiler knows tiles / tilemap / palette
   """
   try:
      return all(k in _ac().KIND_KEYS for k in KINDS)
   except (engine.EngineNotFound, ImportError, AttributeError):
      return False


def max_colors() -> int:
   """!Most colours a palette asset holds (the engine's screen_assets.MAX_COLORS: BG and OBJ memory).
   @return the count
   """
   return int(engine.tool("screen_assets").MAX_COLORS)


def graphics(doc: Document, kind: str | None = None) -> list[JsonDict]:
   """!The manifest's screen graphics assets in manifest order.
   @param doc   asset manifest Document
   @param kind  one of KINDS, or None for all three
   @return assets (live)
   """
   return [a for a in doc.assets() if a.get("kind") in KINDS and (kind is None or a.get("kind") == kind)]


def keys(doc: Document, kind: str) -> list[str]:
   """!Keys of one kind.
   @param doc   asset manifest Document
   @param kind  one of KINDS
   @return keys in manifest order
   """
   return [str(a.get("key")) for a in graphics(doc, kind)]


def full_key(kind: str, name: str) -> str:
   """!A key with its kind's namespace ("tiles:NAME" from "NAME" or the full key).
   @param kind  one of KINDS
   @param name  NAME or the full key
   @return the key
   """
   prefix = PREFIXES[kind]
   return name if name.startswith(prefix) else prefix + name


def compiled(doc: Document, key: str) -> AssetReport:
   """!One asset compiled (the report keeps the error).
   @param doc  asset manifest Document
   @param key  its key
   @return AssetReport (compiled: screen_assets' record: words / cells / colors and their counts)
   """
   return doc.compile_asset(doc.get(key))


def check(doc: Document, asset: JsonDict) -> JsonDict:
   """!Compiles an asset with the engine's compiler.
   @param doc    asset manifest Document (data files are relative to it)
   @param asset  the asset
   @return the compiled record
   @throws ScreenGraphicsError with the compiler's message
   """
   report = doc.compile_asset(asset)
   if not report.ok or report.compiled is None:
      raise ScreenGraphicsError(report.error or "not a screen graphics asset")
   return report.compiled


def _edit(doc: Document, key: str, change: Any) -> None:
   """!Changes a copy of an asset, compiles it and stores it.
   @param doc     asset manifest Document
   @param key     its key
   @param change  callable(asset copy) -> None
   @return None
   """
   a = doc.get(key)
   if a.get("kind") not in KINDS:
      raise ScreenGraphicsError(f"{key!r} is a {a.get('kind')}, not tiles, a tilemap or a palette")
   b = copy.deepcopy(a)
   change(b)
   check(doc, b)
   a.clear()
   a.update(b)


def _add(doc: Document, asset: JsonDict) -> JsonDict:
   """!Adds an asset that compiles.
   @param doc    asset manifest Document
   @param asset  the asset
   @return it
   """
   check(doc, asset)
   return doc.add_asset(asset)


# -- new assets ----------------------------------------------------------------------------------------------------


def gray_ramp(banks: int = 1) -> list[str]:
   """!A gray ramp bank by bank (entry 0 black, then lighter), as a new palette's colours.
   @param banks  banks
   @return "#rrggbb" colours
   """
   out = []
   for _ in range(banks):
      for i in range(BANK_SIZE):
         v = min(CHANNEL_MASK, i * GRAY_STEP) << CHANNEL_DROP
         out.append(f"#{v:02x}{v:02x}{v:02x}")
   return out


def new_tiles(doc: Document, name: str, width: int = NEW_TILES_SIZE[0], height: int = NEW_TILES_SIZE[1],
              bpp: int = BPP4) -> JsonDict:
   """!Adds a tiles asset drawn with shapes (an empty canvas of index 0 to draw on).
   @param doc     asset manifest Document
   @param name    NAME or tiles:NAME
   @param width   canvas pixels across (a multiple of 8)
   @param height  canvas pixels down (a multiple of 8)
   @param bpp     4 or 8
   @return the asset
   """
   return _add(doc, {"key": full_key("tiles", name), "kind": "tiles", "bpp": bpp, "width": width, "height": height,
                     "fill": 0, "shapes": []})


def new_tilemap(doc: Document, name: str, rows: int = NEW_MAP_ROWS, columns: int = ROW_CELLS,
                affine: bool = False) -> JsonDict:
   """!Adds a tilemap of cells, every one tile 0 in bank 0.
   @param doc      asset manifest Document
   @param name     NAME or tilemap:NAME
   @param rows     stored rows
   @param columns  entries a stored row
   @param affine   one tile byte a cell (an affine layer's map)
   @return the asset
   """
   a = {"key": full_key("tilemap", name), "kind": "tilemap", "cells": [0] * (rows * columns)}
   if columns != ROW_CELLS:
      a["columns"] = columns
   if affine:
      a["affine"] = True
   return _add(doc, a)


def new_palette(doc: Document, name: str, banks: int = 1) -> JsonDict:
   """!Adds a palette of gray ramps.
   @param doc    asset manifest Document
   @param name   NAME or palette:NAME
   @param banks  banks of 16 colours
   @return the asset
   """
   return _add(doc, {"key": full_key("palette", name), "kind": "palette", "colors": gray_ramp(banks)})


# -- fields ----------------------------------------------------------------------------------------------------------


def set_fields(doc: Document, key: str, **fields: Any) -> None:
   """!Sets fields of an asset (None removes one), compiled before it is kept.
   @param doc     asset manifest Document
   @param key     its key
   @param fields  e.g. bpp=8, columns=None, block=[2, 2]
   @return None
   """
   def change(a: JsonDict) -> None:
      for k, v in fields.items():
         if v is None:
            a.pop(k, None)
         else:
            a[k] = v
   _edit(doc, key, change)


def set_shapes(doc: Document, key: str, shapes: list[Any]) -> None:
   """!A shapes tiles asset's shapes (asset_compiler's shape objects, painter's order).
   @param doc     asset manifest Document
   @param key     tiles key
   @param shapes  the shapes
   @return None
   """
   if not isinstance(shapes, list):
      raise ScreenGraphicsError("shapes is a list of shape objects")
   if "data" in doc.get(key):
      raise ScreenGraphicsError(f"{key} is a data file; its tiles have no shapes")
   set_fields(doc, key, shapes=shapes)


# -- colours ---------------------------------------------------------------------------------------------------------


def to_bgr555(value: Any) -> int:
   """!A palette entry as BGR555 (as the compiler reads it: "#rrggbb" drops the low three bits).
   @param value  "#rrggbb" or a raw BGR555 number
   @return the colour
   """
   if isinstance(value, int) and not isinstance(value, bool):
      if not 0 <= value <= MAX_BGR555:
         raise ScreenGraphicsError(f"{value} is not a BGR555 colour (0-{MAX_BGR555})")
      return value
   if not isinstance(value, str) or not HEX_COLOR.fullmatch(value):
      raise ScreenGraphicsError(f"colours are '#rrggbb' or a BGR555 number, got {value!r}")
   v = int(value[1:], HEX_BASE)
   r, g, b = (v >> RED_SHIFT_24) & BYTE_MASK, (v >> GREEN_SHIFT_24) & BYTE_MASK, v & BYTE_MASK
   return (r >> CHANNEL_DROP) | (g >> CHANNEL_DROP) << GREEN_SHIFT | (b >> CHANNEL_DROP) << BLUE_SHIFT



def hex_of(color: int) -> str:
   """!A BGR555 colour as "#rrggbb" (the channels' low bits zero, so it reads back as the same colour).
   @param color  BGR555
   @return the text
   """
   r, g, b = (color & CHANNEL_MASK, color >> GREEN_SHIFT & CHANNEL_MASK, color >> BLUE_SHIFT & CHANNEL_MASK)
   return f"#{r << CHANNEL_DROP:02x}{g << CHANNEL_DROP:02x}{b << CHANNEL_DROP:02x}"


def set_color(doc: Document, key: str, index: int, value: Any) -> None:
   """!One colour of a palette (an index one past the end adds it).
   @param doc    asset manifest Document
   @param key    palette key
   @param index  entry (bank * 16 + colour)
   @param value  "#rrggbb" or a raw BGR555 number
   @return None
   """
   to_bgr555(value)

   def change(a: JsonDict) -> None:
      colors = a.setdefault("colors", [])
      if not 0 <= index <= len(colors):
         raise ScreenGraphicsError(f"entry {index}: the palette has {len(colors)} colours")
      if index == len(colors):
         colors.append(value)
      else:
         colors[index] = value
   _edit(doc, key, change)


def set_banks(doc: Document, key: str, banks: int) -> None:
   """!A palette's bank count: new banks are gray ramps, removed ones go from the end.
   @param doc    asset manifest Document
   @param key    palette key
   @param banks  1-32
   @return None
   """
   if not 1 <= banks * BANK_SIZE <= max_colors():
      raise ScreenGraphicsError(f"a palette has 1-{max_colors() // BANK_SIZE} banks")

   def change(a: JsonDict) -> None:
      colors = a.get("colors", [])
      want = banks * BANK_SIZE
      a["colors"] = colors[:want] + gray_ramp(banks)[len(colors):want]
   _edit(doc, key, change)


# -- tilemap entries -------------------------------------------------------------------------------------------------


def make_entry(tile: int, bank: int = 0, hflip: bool = False, vflip: bool = False) -> int:
   """!A text-mode map entry.
   @param tile   tile 0-1023
   @param bank   palette bank 0-15
   @param hflip  mirrored horizontally
   @param vflip  mirrored vertically
   @return the entry
   """
   if not 0 <= tile <= MAX_TILE or not 0 <= bank <= MAX_BANK:
      raise ScreenGraphicsError(f"tile 0-{MAX_TILE}, bank 0-{MAX_BANK}")
   return tile | (ENTRY_HFLIP if hflip else 0) | (ENTRY_VFLIP if vflip else 0) | bank << ENTRY_BANK_SHIFT


def entry_parts(entry: int) -> tuple[int, int, bool, bool]:
   """!A map entry's fields.
   @param entry  the entry
   @return (tile, bank, hflip, vflip)
   """
   return (entry & ENTRY_TILE_MASK, entry >> ENTRY_BANK_SHIFT, bool(entry & ENTRY_HFLIP), bool(entry & ENTRY_VFLIP))


def entry_text(entry: int, affine: bool = False) -> str:
   """!A map entry as the panel and the command line show it.
   @param entry   the entry
   @param affine  an affine map's tile byte
   @return "t12 p3 h" (an affine one: "t12")
   """
   if affine:
      return f"t{entry}"
   tile, bank, h, v = entry_parts(entry)
   flips = ("h" if h else "") + ("v" if v else "")
   return f"t{tile} p{bank}" + (f" {flips}" if flips else "")


def parse_entry(text: str, affine: bool = False) -> int:
   """!A map entry from text: "t12 p3 h" (tile, bank, flips; each optional) or a raw number (0x... too).
   @param text    the text
   @param affine  an affine map's tile byte
   @return the entry
   """
   s = text.strip().lower()
   try:
      return int(s, 0)
   except ValueError:
      pass
   tile, bank, h, v = 0, 0, False, False
   for word in s.split():
      m = ENTRY_WORD.fullmatch(word)
      if m is None:
         raise ScreenGraphicsError(f"{text!r}: an entry is 't12 p3 h' (tile, bank, h / v / hv) or a number")
      if m.group("field") == "t":
         tile = int(m.group("number"))
      elif m.group("field") == "p":
         bank = int(m.group("number"))
      else:
         h, v = "h" in m.group("flips"), "v" in m.group("flips")
   if affine:
      if bank or h or v or not 0 <= tile <= MAX_INDEX_8BPP:
         raise ScreenGraphicsError(f"an affine map's entry is a tile 0-{MAX_INDEX_8BPP}")
      return tile
   return make_entry(tile, bank, h, v)


def map_columns(asset: JsonDict) -> int:
   """!A tilemap's entries a stored row.
   @param asset  tilemap asset
   @return its columns
   """
   return int(asset.get("columns", ROW_CELLS))


def to_cells(doc: Document, key: str) -> None:
   """!A tilemap read from a data file becomes "cells" in the manifest (so the panel can paint it; the file stays).
   @param doc  asset manifest Document
   @param key  tilemap key
   @return None
   """
   cells = list(check(doc, doc.get(key))["cells"])

   def change(a: JsonDict) -> None:
      a.pop("data", None)
      a["cells"] = cells
   _edit(doc, key, change)


def paint(doc: Document, key: str, x: int, y: int, entry: int, w: int = 1, h: int = 1, step: int = 0) -> None:
   """!Writes entries into a cells tilemap's rectangle (stored rows of its columns); with @p step each next cell's
   tile is that much higher (a run of tiles, row by row, as the engine's layers::fill()).
   @param doc    asset manifest Document
   @param key    tilemap key
   @param x      left column
   @param y      top row
   @param entry  the first cell's entry
   @param w      columns
   @param h      rows
   @param step   tile step per cell (0: one entry everywhere)
   @return None
   """
   a = doc.get(key)
   if "cells" not in a:
      raise ScreenGraphicsError(f"{key} reads a data file; turn it into cells first")
   columns = map_columns(a)
   affine = bool(a.get("affine"))

   def change(b: JsonDict) -> None:
      cells = b["cells"]
      n = 0
      for row in range(y, y + h):
         for col in range(x, x + w):
            i = row * columns + col
            if not 0 <= col < columns or not 0 <= i < len(cells):
               raise ScreenGraphicsError(f"cell {col},{row} is outside the map ({columns} x "
                                         f"{len(cells) // columns})")
            if affine:
               cells[i] = (entry + n * step) & MAX_INDEX_8BPP
            else:
               tile = ((entry & ENTRY_TILE_MASK) + n * step) & ENTRY_TILE_MASK
               cells[i] = (entry & ~ENTRY_TILE_MASK) | tile
            n += 1
   _edit(doc, key, change)


def set_rows(doc: Document, key: str, rows: int) -> None:
   """!A cells tilemap's stored rows (new rows are tile 0; removed ones go from the end).
   @param doc   asset manifest Document
   @param key   tilemap key
   @param rows  rows
   @return None
   """
   a = doc.get(key)
   if "cells" not in a:
      raise ScreenGraphicsError(f"{key} reads a data file; turn it into cells first")
   columns = map_columns(a)

   def change(b: JsonDict) -> None:
      cells = b["cells"]
      want = rows * columns
      b["cells"] = cells[:want] + [0] * (want - len(cells))
   _edit(doc, key, change)


# -- decoding and previews -------------------------------------------------------------------------------------------


## One tile: 8 rows of 8 palette indices.
Tile = list[list[int]]


def decode_tiles(record: JsonDict) -> list[Tile]:
   """!A compiled tiles record's tiles, as video memory holds them.
   @param record  screen_assets.compile_tiles()'s result
   @return tiles in order
   """
   blob = b"".join(w.to_bytes(WORD_BYTES, "little") for w in record["words"])
   return tiles_from_bytes(blob, record["bpp"])


def tiles_from_bytes(blob: bytes, bpp: int) -> list[Tile]:
   """!Tiles from raw tile bytes.
   @param blob  whole tiles' bytes
   @param bpp   4 or 8
   @return tiles
   """
   size = TILE_BYTES_8BPP if bpp == BPP8 else TILE_BYTES_4BPP
   out = []
   for t in range(0, len(blob) - size + 1, size):
      part = blob[t:t + size]
      if bpp == BPP8:
         out.append([list(part[y * TILE:(y + 1) * TILE]) for y in range(TILE)])
      else:
         row_bytes = TILE // PIXELS_PER_BYTE_4BPP
         out.append([[v for b in part[y * row_bytes:(y + 1) * row_bytes] for v in (b & NIBBLE_MASK, b >> NIBBLE_BITS)]
                     for y in range(TILE)])
   return out


def tile_bytes(tile: Tile, bpp: int) -> bytes:
   """!One tile's bytes as video memory holds them.
   @param tile  8 rows of 8 indices
   @param bpp   4 or 8
   @return 32 or 64 bytes
   """
   if bpp == BPP8:
      return bytes(v for row in tile for v in row)
   return bytes(row[i] | row[i + 1] << NIBBLE_BITS for row in tile for i in range(0, TILE, PIXELS_PER_BYTE_4BPP))


def palette_colors(doc: Document, key: str | None) -> list[int]:
   """!A palette asset's colours (BGR555), or a gray ramp when there is none or it does not compile.
   @param doc  asset manifest Document
   @param key  palette key, or None
   @return the colours
   """
   if key:
      a = doc.find(key)
      if a is not None and a.get("kind") == "palette":
         r = doc.compile_asset(a)
         if r.ok and r.compiled is not None:
            return list(r.compiled["colors"])
   return [to_bgr555(c) for c in gray_ramp()]


def _rgba(color: int) -> bytes:
   """!A BGR555 colour as opaque RGBA bytes.
   @param color  BGR555
   @return 4 bytes
   """
   return bytes(bgr_to_rgb(color) + (OPAQUE,))


def color_at(colors: Sequence[int], index: int) -> int:
   """!A palette entry, magenta past the colours given.
   @param colors  the colours
   @param index   entry
   @return BGR555
   """
   return colors[index] if 0 <= index < len(colors) else MISSING_COLOR


def draw_tile(img: RgbaImage, ox: int, oy: int, tile: Tile, colors: Sequence[int], bank: int, bpp: int,
              hflip: bool = False, vflip: bool = False, zero: bytes | None = None) -> None:
   """!Draws one tile (index 0 transparent, or @p zero).
   @param img     (w, h, RGBA) target
   @param ox      left
   @param oy      top
   @param tile    8 rows of 8 indices
   @param colors  the palette memory's colours (256)
   @param bank    a 4bpp tile's bank
   @param bpp     4 or 8
   @param hflip   mirrored horizontally
   @param vflip   mirrored vertically
   @param zero    RGBA drawn for index 0, or None (left as it is)
   @return None
   """
   w, h, px = img
   base = 0 if bpp == BPP8 else bank * BANK_SIZE
   for y in range(TILE):
      ty = oy + y
      if not 0 <= ty < h:
         continue
      row = tile[TILE - 1 - y if vflip else y]
      for x in range(TILE):
         tx = ox + x
         if not 0 <= tx < w:
            continue
         v = row[TILE - 1 - x if hflip else x]
         o = (ty * w + tx) * RGBA_BYTES
         if v:
            px[o:o + RGBA_BYTES] = _rgba(color_at(colors, base + v))
         elif zero is not None:
            px[o:o + RGBA_BYTES] = zero


def render_tiles(tiles: Sequence[Tile], colors: Sequence[int], bank: int = 0, bpp: int = BPP4,
                 columns: int = DEFAULT_SHEET_COLUMNS, positions: Sequence[tuple[int, int]] | None = None) -> RgbaImage:
   """!A sheet of tiles, in reading order or where @p positions puts them.
   @param tiles      the tiles
   @param colors     palette colours (a 4bpp sheet uses @p bank of them)
   @param bank       a 4bpp sheet's bank
   @param bpp        4 or 8
   @param columns    tiles per row
   @param positions  (column, row) of each tile (sheet_positions()), or None for reading order
   @return (w, h, RGBA); index 0 transparent
   """
   columns = max(1, columns)
   places = list(positions) if positions is not None else [(i % columns, i // columns) for i in range(len(tiles))]
   rows = max([r for _c, r in places] + [0]) + 1
   img = blank(columns * TILE, rows * TILE)
   for t, (c, r) in zip(tiles, places):
      draw_tile(img, c * TILE, r * TILE, t, colors, bank, bpp)
   return img


def sheet_positions(asset: JsonDict, count: int) -> tuple[int, list[tuple[int, int]]] | None:
   """!Where a shapes tiles asset cut by blocks had each tile on its canvas (so the sheet shows as drawn).
   @param asset  tiles asset
   @param count  its tiles
   @return (columns, (column, row) per tile), or None when it is not cut by blocks
   """
   block, width = asset.get("block"), asset.get("width")
   if not isinstance(block, list) or len(block) != len(NEW_TILES_SIZE) or not isinstance(width, int):
      return None
   bw, bh = block
   across = width // TILE
   per_row = max(1, across // bw)
   out = []
   for i in range(count):
      b, t = divmod(i, bw * bh)
      out.append(((b % per_row) * bw + t % bw, (b // per_row) * bh + t // bw))
   return across, out


def render_tilemap(cells: Sequence[int], columns: int, tiles: Sequence[Tile], colors: Sequence[int], bpp: int = BPP4,
                   affine: bool = False, first_tile: int = 0) -> RgbaImage:
   """!A tilemap as stored (rows of @p columns entries), its tiles from @p tiles counted from @p first_tile.
   @param cells       the entries
   @param columns     entries a row
   @param tiles       the tiles the entries name (tile first_tile is tiles[0])
   @param colors      palette colours
   @param bpp         the tiles' 4 or 8
   @param affine      entries are tile bytes (8bpp, no flips or banks)
   @param first_tile  the tile number of tiles[0]
   @return (w, h, RGBA); index 0 transparent
   """
   rows = max(1, -(-len(cells) // columns))
   img = blank(columns * TILE, rows * TILE)
   for i, e in enumerate(cells):
      tile, bank, h, v = (e, 0, False, False) if affine else entry_parts(e)
      t = tile - first_tile
      if 0 <= t < len(tiles):
         draw_tile(img, (i % columns) * TILE, (i // columns) * TILE, tiles[t], colors, bank,
                   BPP8 if affine else bpp, h, v)
   return img


def render_palette(colors: Sequence[int], swatch: int = SWATCH) -> RgbaImage:
   """!A palette's colours, a bank a row.
   @param colors  BGR555 colours
   @param swatch  pixels per side of a colour
   @return (w, h, RGBA)
   """
   rows = max(1, -(-len(colors) // SWATCHES_ACROSS))
   w, h = SWATCHES_ACROSS * swatch, rows * swatch
   img = blank(w, h)
   _w, _h, px = img
   for i, c in enumerate(colors):
      rgba = _rgba(c)
      x0, y0 = (i % SWATCHES_ACROSS) * swatch, (i // SWATCHES_ACROSS) * swatch
      for y in range(y0, y0 + swatch):
         o = (y * w + x0) * RGBA_BYTES
         px[o:o + swatch * RGBA_BYTES] = rgba * swatch
   return img


def sheet_columns(asset: JsonDict, record: JsonDict | None = None) -> int:
   """!Tiles per row a tiles asset's sheet shows: its "columns", its canvas width, or DEFAULT_SHEET_COLUMNS.
   @param asset   tiles asset
   @param record  its compiled record, or None
   @return the columns
   """
   if record is not None and record.get("columns"):
      return int(record["columns"])
   if asset.get("columns"):
      return int(asset["columns"])
   if isinstance(asset.get("width"), int) and "block" not in asset:
      return max(1, asset["width"] // TILE)
   return DEFAULT_SHEET_COLUMNS


def preview(doc: Document, key: str, palette_key: str | None = None, bank: int = 0,
            tiles_key: str | None = None, first_tile: int = 0) -> RgbaImage:
   """!A picture of one asset: a tiles sheet (in a palette's bank), a tilemap (drawn with a tiles asset) or a
   palette's swatches.
   @param doc          asset manifest Document
   @param key          the asset
   @param palette_key  palette to draw tiles in (None: a gray ramp)
   @param bank         bank of a 4bpp sheet
   @param tiles_key    tiles a tilemap is drawn with (None: blank tiles)
   @param first_tile   tile number of the tiles asset's first tile (a layer's load position)
   @return (w, h, RGBA)
   @throws ScreenGraphicsError when it does not compile
   """
   a = doc.get(key)
   rec = check(doc, a)
   colors = palette_colors(doc, palette_key)
   if a["kind"] == "palette":
      return render_palette(rec["colors"])
   if a["kind"] == "tiles":
      sheet = decode_tiles(rec)
      placed = sheet_positions(a, len(sheet))
      if placed is not None:
         return render_tiles(sheet, colors, bank, rec["bpp"], placed[0], placed[1])
      return render_tiles(sheet, colors, bank, rec["bpp"], sheet_columns(a, rec))
   tiles: list[Tile] = []
   bpp = BPP4
   if tiles_key:
      t = doc.find(tiles_key)
      if t is not None and t.get("kind") == "tiles":
         trec = check(doc, t)
         tiles, bpp = decode_tiles(trec), trec["bpp"]
   return render_tilemap(rec["cells"], rec["columns"], tiles, colors, bpp, rec["affine"], first_tile)


# -- import / export -----------------------------------------------------------------------------------------------


def _flipped(tile: Tile, h: bool, v: bool) -> tuple[tuple[int, ...], ...]:
   """!A tile flipped, as a hashable value.
   @param tile  the tile
   @param h     mirrored horizontally
   @param v     mirrored vertically
   @return rows
   """
   rows = list(reversed(tile)) if v else list(tile)
   return tuple(tuple(reversed(r)) if h else tuple(r) for r in rows)


## Flip combinations a shared tile is looked for under: (hflip, vflip).
FLIPS = ((False, False), (True, False), (False, True), (True, True))


def cut_image(w: int, h: int, indices: Sequence[int], bpp: int = BPP4, dedupe: bool = True,
              flips: bool = True) -> tuple[list[Tile], list[int]]:
   """!An indexed image cut into tiles and map entries. 4bpp: each tile's indices must lie in one bank of 16
   (an index's bank is the entry's palette bank, its low four bits the pixel); 8bpp: indices as they are.
   @param w        pixels across (a multiple of 8)
   @param h        pixels down (a multiple of 8)
   @param indices  one palette index per pixel
   @param bpp      4 or 8
   @param dedupe   identical tiles shared
   @param flips    flipped copies shared too (4bpp / 8bpp text maps)
   @return (tiles, one entry per tile of the image in reading order)
   """
   if w % TILE or h % TILE or not w or not h:
      raise ScreenGraphicsError(f"{w} x {h}: an image of tiles is a multiple of 8 pixels each way")
   tiles: list[Tile] = []
   seen: dict[tuple[tuple[int, ...], ...], int] = {}
   entries: list[int] = []
   for ty in range(h // TILE):
      for tx in range(w // TILE):
         rows = [[indices[(ty * TILE + y) * w + tx * TILE + x] for x in range(TILE)] for y in range(TILE)]
         bank = 0
         if bpp == BPP4:
            banks = {v >> NIBBLE_BITS for r in rows for v in r if v & NIBBLE_MASK}
            if len(banks) > 1:
               raise ScreenGraphicsError(f"tile {tx},{ty} mixes palette banks {sorted(banks)}; a 4bpp tile "
                                         "uses one bank of 16")
            bank = banks.pop() if banks else 0
            rows = [[v & NIBBLE_MASK for v in r] for r in rows]
         found = None
         if dedupe:
            for hf, vf in (FLIPS if flips else FLIPS[:1]):
               k = _flipped(rows, hf, vf)
               if k in seen:
                  found = (seen[k], hf, vf)
                  break
         if found is None:
            if len(tiles) > MAX_TILE:
               raise ScreenGraphicsError(f"more than {MAX_TILE + 1} tiles")
            found = (len(tiles), False, False)
            seen.setdefault(_flipped(rows, False, False), len(tiles))
            tiles.append(rows)
         t, hf, vf = found
         entries.append(make_entry(t, bank if bpp == BPP4 else 0, hf, vf))
   return tiles, entries


def block_order(entries: Sequence[int], cols: int, rows: int) -> list[int]:
   """!Map entries of an image (cols x rows tiles, reading order) laid out as a layer's map memory holds them: rows
   of 32 cells; an image wider than 32 cells takes two screen blocks side by side (64 cells: the left block's
   32 x 32, then the right block's), its rows padded to 32.
   @param entries  the image's entries
   @param cols     tiles across (at most 64)
   @param rows     tiles down
   @return the stored entries
   """
   if cols > WIDE_BLOCKS * ROW_CELLS:
      raise ScreenGraphicsError(f"{cols} tiles across: a layer's map is at most {WIDE_BLOCKS * ROW_CELLS} cells "
                                "wide")
   if cols <= ROW_CELLS:
      out = []
      for r in range(rows):
         out += list(entries[r * cols:(r + 1) * cols]) + [0] * (ROW_CELLS - cols)
      return out
   tall = -(-rows // ROW_CELLS) * ROW_CELLS
   out = []
   for top in range(0, tall, ROW_CELLS):
      for left in (0, ROW_CELLS):
         for r in range(top, top + ROW_CELLS):
            for c in range(left, left + ROW_CELLS):
               out.append(entries[r * cols + c] if r < rows and c < cols else 0)
   return out


def import_png(doc: Document, name: str, path: str | Path, bpp: int = BPP4, make_map: bool = True,
               make_palette: bool = True, dedupe: bool = True, flips: bool = True) -> list[str]:
   """!An indexed PNG becomes screen graphics: tiles:NAME (a data file screen/NAME.4bpp beside the manifest, written
   at once), with tilemap:NAME (the image's cells in a layer's map order) and palette:NAME (its PLTE colours, whole
   banks) when asked. Without a tilemap every tile is kept in reading order (a sprite sheet's frames).
   @param doc           asset manifest Document (saved: its folder is needed)
   @param name          NAME
   @param path          the palette PNG
   @param bpp           4 or 8
   @param make_map      add the tilemap (shared tiles: dedupe applies)
   @param make_palette  add the palette
   @param dedupe        identical tiles shared (only with a tilemap)
   @param flips         flipped copies shared too
   @return the keys added
   """
   if doc.base_dir is None:
      raise ScreenGraphicsError("save the manifest first: the tiles file is written next to it")
   w, h, indices = indexed_png.read(path)
   tiles, entries = cut_image(w, h, indices, bpp, dedupe and make_map, flips)
   slug = re.sub(r"[^a-z0-9_]+", "_", name.split(":", 1)[-1].lower()).strip("_") or "graphics"
   rel = f"{DATA_FOLDER}/{slug}{SUFFIX_8BPP if bpp == BPP8 else SUFFIX_4BPP}"
   for kind in ("tiles",) + (("tilemap",) if make_map else ()) + (("palette",) if make_palette else ()):
      doc.check_new_key(full_key(kind, name.split(":", 1)[-1]))
   out = doc.base_dir / rel
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_bytes(b"".join(tile_bytes(t, bpp) for t in tiles))
   stem = name.split(":", 1)[-1]
   added = []
   tiles_asset: JsonDict = {"key": full_key("tiles", stem), "kind": "tiles", "data": rel, "bpp": bpp}
   if not make_map:
      tiles_asset["columns"] = w // TILE
   added.append(_add(doc, tiles_asset)["key"])
   if make_map:
      cells = block_order(entries, w // TILE, h // TILE)
      added.append(_add(doc, {"key": full_key("tilemap", stem), "kind": "tilemap", "cells": cells})["key"])
   if make_palette:
      plte, _trns = indexed_png.palette_chunks(path)
      rgb = [plte[i:i + indexed_png.PLTE_ENTRY] for i in range(0, len(plte), indexed_png.PLTE_ENTRY)]
      used = max(indices) + 1 if indices else 1
      want = min(max_colors(), -(-max(used, 1) // BANK_SIZE) * BANK_SIZE)
      padded = rgb[:want] + [bytes(indexed_png.PLTE_ENTRY)] * (want - len(rgb[:want]))
      colors = ["#" + bytes(c).hex() for c in padded]
      added.append(_add(doc, {"key": full_key("palette", stem), "kind": "palette", "colors": colors})["key"])
   return added


def export_png(doc: Document, key: str, out: str | Path, palette_key: str | None = None, bank: int = 0) -> None:
   """!Writes a tiles asset's sheet as an indexed PNG (its pixels the palette indices; 4bpp: in @p bank, so the
   PNG's palette is the whole palette and import_png() reads it back).
   @param doc          asset manifest Document
   @param key          tiles key
   @param out          the PNG
   @param palette_key  palette whose colours the PNG gets (None: a gray ramp)
   @param bank         a 4bpp sheet's bank
   @return None
   """
   a = doc.get(key)
   if a.get("kind") != "tiles":
      raise ScreenGraphicsError(f"{key} is not tiles")
   rec = check(doc, a)
   tiles = decode_tiles(rec)
   columns = sheet_columns(a, rec)
   rows = max(1, -(-len(tiles) // columns))
   w, h = columns * TILE, rows * TILE
   base = 0 if rec["bpp"] == BPP8 else bank * BANK_SIZE
   indices = bytearray(w * h)
   for i, t in enumerate(tiles):
      ox, oy = (i % columns) * TILE, (i // columns) * TILE
      for y in range(TILE):
         for x in range(TILE):
            indices[(oy + y) * w + ox + x] = base + t[y][x]   # index 0 stays the bank's entry 0
   colors = palette_colors(doc, palette_key)
   entries = max(len(colors), max(indices) + 1 if indices else 1)
   plte = b"".join(bytes(bgr_to_rgb(color_at(colors, i))) for i in range(entries))
   Path(out).write_bytes(indexed_png.encode(w, h, indices, plte))


# -- text ----------------------------------------------------------------------------------------------------------


def describe(doc: Document, a: JsonDict) -> str:
   """!One line about an asset.
   @param doc  asset manifest Document
   @param a    the asset
   @return the line
   """
   r = doc.compile_asset(a)
   if not r.ok or r.compiled is None:
      return f"{a.get('key')}: {r.error}"
   c = r.compiled
   if a["kind"] == "tiles":
      src = f"data {a['data']}" if "data" in a else f"shapes {a.get('width')} x {a.get('height')}"
      block = f", blocks {a['block'][0]} x {a['block'][1]}" if isinstance(a.get("block"), list) else ""
      return f"{a['key']}: {c['count']} tiles {c['bpp']}bpp ({src}{block})"
   if a["kind"] == "tilemap":
      src = f"data {a['data']}" if "data" in a else "cells"
      kind = "affine bytes" if c["affine"] else "entries"
      return f"{a['key']}: {c['count']} {kind}, {c['columns']} a row ({src})"
   n = len(c["colors"])
   return f"{a['key']}: {n} colours ({-(-n // BANK_SIZE)} bank{'s' if n > BANK_SIZE else ''})"


def lines(doc: Document, key: str | None = None) -> list[str]:
   """!The manifest's screen graphics, or one asset in full (a tilemap's rows, a palette's banks).
   @param doc  asset manifest Document
   @param key  one asset, or None for the list
   @return lines
   """
   if key is None:
      return [describe(doc, a) for a in graphics(doc)]
   a = doc.get(key)
   out = [describe(doc, a)]
   rec = doc.compile_asset(a).compiled
   if rec is None:
      return out
   if a["kind"] == "palette":
      colors = rec["colors"]
      for b in range(0, len(colors), BANK_SIZE):
         out.append(f"  bank {b // BANK_SIZE}: " + " ".join(hex_of(c) for c in colors[b:b + BANK_SIZE]))
   elif a["kind"] == "tilemap":
      cols = rec["columns"]
      for r in range(0, len(rec["cells"]), cols):
         out.append(f"  row {r // cols}: " + " ".join(f"{e:04x}" for e in rec["cells"][r:r + cols]))
   return out
