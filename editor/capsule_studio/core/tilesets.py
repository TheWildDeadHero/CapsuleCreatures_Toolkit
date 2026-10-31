"""!Tileset editing: sheets and metatiles.

A tileset (capsule.tileset/2, C-01b) has sheets of 8x8 tiles (shape-drawn
or PNG, one palette each), metatiles of 2x2 tiles (graphics only: one
layer, painted on any of a map's tile layers; behavior, collision and the
rest are painted on the map's attribute layer), and tile animations. Tile
references are "sheet:index" with an optional "h", "v" or "hv" flip suffix;
None is transparent.

I2: a fixed-placement tileset ("place") holds imported indexed graphics as
they are: indexed sheets (palette PNGs used as their indices), its own palette
banks ("palettes"), metatiles of raw tilemap entries ("entries") and
animations at a tile of its placement ("at"); see the engine's
map_compiler.py. Animations take "phase" (I2), "from_sheet" and "on_shift"
(I3).

Functions that change a Document must be called inside doc.edit().
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import engine
from .document import Document

if TYPE_CHECKING:
   from .world import Project

## Tile side, in pixels.
TILE_PIXELS = 8
## Metatile side, in tiles.
METATILE_TILES = 2
## Tiles in a metatile (its slots: top-left, top-right, bottom-left, bottom-right).
TILES_PER_METATILE = METATILE_TILES * METATILE_TILES
## Last metatile slot.
MAX_SLOT = TILES_PER_METATILE - 1
## Bytes per pixel of an RGBA image.
RGBA_BYTES = 4
## Color bytes (red, green, blue) at the start of each RGBA pixel.
RGB_BYTES = 3
## Number unique_name() appends first ("base_2"; the unnumbered name counts as the first).
FIRST_COPY_NUMBER = 2

## A tile reference: "sheet:index" with an optional flip suffix, or None (transparent).
TileRef = str | None
## A parsed tile reference: (sheet, index, hflip, vflip).
ParsedRef = tuple[str, int, bool, bool]
## An image as the engine's bitmap module holds it: (width, height, RGBA bytes).
Image = tuple[int, int, bytearray]
## A sheet compiled by the engine's map compiler (its tools/map_compiler.Sheet, imported at run time).
CompiledSheet = Any


def ref(sheet: str, index: int, hflip: bool = False, vflip: bool = False) -> str:
   """!Builds a tile reference.
   @param sheet  sheet name
   @param index  tile number (row by row)
   @param hflip  mirror horizontally
   @param vflip  mirror vertically
   @return "sheet:index[h][v]"
   """
   return f"{sheet}:{index}{'h' if hflip else ''}{'v' if vflip else ''}"


def parse(r: TileRef) -> ParsedRef | None:
   """!Splits a tile reference.
   @param r  reference or None
   @return (sheet, index, hflip, vflip), or None
   """
   if r is None:
      return None
   sheet, rest = r.split(":", 1)
   # Flip letters trail the index, in either order.
   h = v = False
   while rest and rest[-1] in "hv":
      if rest[-1] == "h":
         h = True
      else:
         v = True
      rest = rest[:-1]
   return sheet, int(rest), h, v


def block_refs(sheet: str, width_tiles: int, bx: int, by: int) -> list[str]:
   """!The four tile references of a 16x16 block of a sheet.
   @param sheet        sheet name
   @param width_tiles  sheet width in tiles
   @param bx           block column (16-pixel units)
   @param by           block row
   @return [top-left, top-right, bottom-left, bottom-right]
   """
   # Tile number of the block's top-left tile: tiles are numbered row by row.
   t = by * METATILE_TILES * width_tiles + bx * METATILE_TILES
   return [ref(sheet, t), ref(sheet, t + 1), ref(sheet, t + width_tiles), ref(sheet, t + width_tiles + 1)]


def sheet(doc: Document, name: str) -> dict[str, Any]:
   """!A sheet object.
   @param doc   tileset Document
   @param name  sheet name
   @return the sheet dict
   """
   for s in doc.data.get("sheets", []):
      if s.get("name") == name:
         return s
   raise ValueError(f"no sheet {name!r}")


def metatile(doc: Document, name: str) -> dict[str, Any]:
   """!A metatile object.
   @param doc   tileset Document
   @param name  metatile name
   @return the metatile dict
   """
   for m in doc.data.get("metatiles", []):
      if m.get("name") == name:
         return m
   raise ValueError(f"no metatile {name!r}")


def unique_name(existing: Sequence[str | None], base: str) -> str:
   """!A name not in @p existing.
   @param existing  names in use
   @param base      wanted name
   @return base, or base_2, base_3, ...
   """
   if base not in existing:
      return base
   n = FIRST_COPY_NUMBER
   while f"{base}_{n}" in existing:
      n += 1
   return f"{base}_{n}"


def add_image_sheet(doc: Document, name: str, image: Image, palette: str | list[str] = "auto") -> str:
   """!Adds a PNG sheet; the image is held until the tileset is saved, as
   sheets/NAME.png next to it.
   @param doc      tileset Document
   @param name     sheet name
   @param image    (w, h, RGBA), sizes multiples of 8
   @param palette  "auto", a list of colors, or "@other" to share a sheet's
   @return the sheet name used
   """
   w, h, _ = image
   if w % TILE_PIXELS or h % TILE_PIXELS or not w or not h:
      raise ValueError(f"sheet images are multiples of 8 pixels, this one is {w}x{h}")
   name = unique_name([s.get("name") for s in doc.data.get("sheets", [])], name)
   rel = doc.unique_image_path("sheets", name)
   doc.add_image(rel, image)
   doc.data.setdefault("sheets", []).append({"name": name, "palette": palette, "image": rel})
   return name


def set_transparent(doc: Document, sheet_name: str, color: str | None) -> None:
   """!Sets an image sheet's transparent color: its pixels of exactly that
   color become transparent (and take no palette entry).
   @param doc         tileset Document
   @param sheet_name  sheet name
   @param color       "#rrggbb", or None for no transparent color
   @return None
   """
   s = sheet(doc, sheet_name)
   if "image" not in s:
      raise ValueError("only image sheets take a transparent color (shape sheets use palette entry 0)")
   if color is None:
      s.pop("transparent", None)
      return
   c = color.lower() if isinstance(color, str) else color
   if engine.bitmap().parse_rgb(c) is None:
      raise ValueError(f"a transparent color looks like #ff00ff, not {color!r}")
   s["transparent"] = c


def source_color(doc: Document, sheet_name: str, x: int, y: int) -> str | None:
   """!A pixel's color in an image sheet's source image (for picking the
   transparent color).
   @param doc         tileset Document
   @param sheet_name  sheet name
   @param x           pixel column
   @param y           pixel row
   @return "#rrggbb", or None (no image, or outside it)
   """
   s = sheet(doc, sheet_name)
   img = doc.image(s["image"]) if "image" in s else None
   if img is None:
      return None
   w, h, px = img
   if not (0 <= x < w and 0 <= y < h):
      return None
   i = (y * w + x) * RGBA_BYTES
   red, green, blue = px[i:i + RGB_BYTES]
   return "#{:02x}{:02x}{:02x}".format(red, green, blue)


def add_metatile(doc: Document, name: str, tiles: Sequence[TileRef]) -> str:
   """!Adds a metatile.
   @param doc    tileset Document
   @param name   wanted name (made unique)
   @param tiles  4 tile references (top-left, top-right, bottom-left, bottom-right; None transparent)
   @return the name used
   """
   if len(tiles) != TILES_PER_METATILE:
      raise ValueError(f"a metatile has {TILES_PER_METATILE} tile references")
   name = unique_name([m.get("name") for m in doc.data.get("metatiles", [])], name)
   doc.data.setdefault("metatiles", []).append({"name": name, "tiles": list(tiles)})
   return name


def set_tile(doc: Document, name: str, slot: int, tile_ref: TileRef) -> None:
   """!Sets one of a metatile's four tiles.
   @param doc       tileset Document
   @param name      metatile name
   @param slot      0-3 (top-left, top-right, bottom-left, bottom-right)
   @param tile_ref  reference or None
   @return None
   """
   if not 0 <= slot <= MAX_SLOT:
      raise ValueError(f"slots are 0-{MAX_SLOT}")
   m = metatile(doc, name)
   refs = m.setdefault("tiles", [None] * TILES_PER_METATILE)
   refs[slot] = tile_ref


def block(sheet_name: str, width_tiles: int, index: int, w: int = 1, h: int = 1, hflip: bool = False,
          vflip: bool = False) -> list[list[str]]:
   """!Tile references of a w x h block of a sheet, as they land in a
   metatile: a flipped block also swaps its columns (H) or rows (V), so it
   reads as the mirror image of the whole block.
   @param sheet_name   sheet name
   @param width_tiles  sheet width in tiles
   @param index        top-left tile number
   @param w            block width in tiles, 1-2
   @param h            block height in tiles, 1-2
   @param hflip        mirror horizontally
   @param vflip        mirror vertically
   @return rows of references (h rows of w)
   """
   if not (1 <= w <= METATILE_TILES and 1 <= h <= METATILE_TILES):
      raise ValueError(f"a block is 1-{METATILE_TILES} tiles wide and high")
   rows = [[ref(sheet_name, index + dy * width_tiles + dx, hflip, vflip) for dx in range(w)] for dy in range(h)]
   if hflip:
      rows = [list(reversed(r)) for r in rows]
   if vflip:
      rows = list(reversed(rows))
   return rows


def place(doc: Document, name: str, slot: int, rows: Sequence[Sequence[TileRef]]) -> list[int]:
   """!Puts a block of tile references into a metatile with its top-left
   tile on @p slot; parts falling outside the 2x2 metatile are dropped.
   @param doc   tileset Document
   @param name  metatile name
   @param slot  0-3 (top-left, top-right, bottom-left, bottom-right)
   @param rows  rows of references (None clears), e.g. from block()
   @return slots changed
   """
   if not 0 <= slot <= MAX_SLOT:
      raise ValueError(f"slots are 0-{MAX_SLOT}")
   m = metatile(doc, name)
   refs = m.setdefault("tiles", [None] * TILES_PER_METATILE)
   # Slots are numbered row by row in the 2x2 metatile: bit 0 is the column, bit 1 the row.
   sx, sy = slot & 1, slot >> 1
   changed = []
   for dy, row in enumerate(rows):
      for dx, r in enumerate(row):
         x, y = sx + dx, sy + dy
         at = y * METATILE_TILES + x
         if x < METATILE_TILES and y < METATILE_TILES and refs[at] != r:
            refs[at] = r
            changed.append(at)
   return changed


def toggle_flip(doc: Document, name: str, slot: int, axis: str) -> bool:
   """!Mirrors one tile of a metatile in place.
   @param doc   tileset Document
   @param name  metatile name
   @param slot  0-3
   @param axis  "h" or "v"
   @return True if the slot holds a tile
   """
   m = metatile(doc, name)
   refs = m.setdefault("tiles", [None] * TILES_PER_METATILE)
   p = parse(refs[slot])
   if p is None:
      return False
   sheet_name, index, h, v = p
   # != toggles the flag of the chosen axis only.
   refs[slot] = ref(sheet_name, index, h != (axis == "h"), v != (axis == "v"))
   return True


def rename_metatile(doc: Document, old: str, new: str) -> None:
   """!Renames a metatile (maps refer to it by name: see Project-level rename).
   @param doc  tileset Document
   @param old  current name
   @param new  new name
   @return None
   """
   if not new or "/" in new:
      raise ValueError("metatile names have no '/'")
   if any(m.get("name") == new for m in doc.data.get("metatiles", [])):
      raise ValueError(f"metatile {new!r} exists")
   metatile(doc, old)["name"] = new


def remove_metatile(doc: Document, name: str) -> None:
   """!Removes a metatile.
   @param doc   tileset Document
   @param name  metatile name
   @return None
   """
   doc.data["metatiles"].remove(metatile(doc, name))


def metatiles_from_sheet(doc: Document, sheet_name: str, compiled_sheet: CompiledSheet, prefix: str | None = None,
                         skip_empty: bool = True) -> list[str]:
   """!Adds one metatile per 16x16 block of a sheet (a quick start for
   imported art); blocks that are fully transparent are skipped.
   @param doc             tileset Document
   @param sheet_name      sheet name
   @param compiled_sheet  the compiled Sheet (map_compiler) for pixel checks
   @param prefix          name prefix, default the sheet name
   @param skip_empty      skip fully transparent blocks
   @return names added
   """
   s = compiled_sheet
   added = []
   # The sheet's size is in tiles; a last odd row or column makes no block.
   for by in range(s.h // METATILE_TILES):
      for bx in range(s.w // METATILE_TILES):
         refs = block_refs(sheet_name, s.w, bx, by)
         if skip_empty:
            # Each tile's 8x8 palette indices; 0 is transparent.
            tiles = [s.tile(parse(r)[1], sheet_name) for r in refs]
            if all(v == 0 for t in tiles for row in t for v in row):
               continue
         added.append(add_metatile(doc, f"{prefix or sheet_name}_{bx}_{by}", refs))
   return added


def compile_sheet(project: Project, tileset_name: str, sheet_name: str) -> CompiledSheet:
   """!A sheet as the compiler sees it.
   @param project       world Project
   @param tileset_name  tileset name
   @param sheet_name    sheet name
   @return map_compiler Sheet
   """
   ts, _, error = project.compiled_tileset(tileset_name)
   if ts is None:
      raise ValueError(error)
   return ts.sheets[sheet_name]



# -- I2: fixed-placement tilesets (map_compiler compile_fixed_tileset(): "place", indexed sheets, "palettes", raw
# metatile "entries", animations "at") --------------------------------------------------------------------------

## Keys of a fixed tileset's "place".
PLACE_KEYS = ("sheet", "tile", "tiles", "palette", "palettes")
## Black, a new bank's colors.
BLACK = "#000000"


def _mc() -> Any:
   """!The engine's map compiler.
   @return map_compiler
   """
   return engine.tool("map_compiler")


def is_fixed(doc: Document) -> bool:
   """!Whether a tileset is a fixed-placement one (I2: it has "place").
   @param doc  tileset Document
   @return True or False
   """
   return isinstance(doc.data.get("place"), dict)


def place_of(doc: Document) -> dict[str, Any] | None:
   """!A fixed tileset's placement.
   @param doc  tileset Document
   @return {"sheet", "tile", "tiles", "palette", "palettes"} (the manifest's own dict), or None
   """
   p = doc.data.get("place")
   return p if isinstance(p, dict) else None


def _whole(value: Any, lo: int, hi: int, what: str) -> int:
   """!Checks a whole number.
   @param value  candidate
   @param lo     smallest
   @param hi     largest
   @param what   name for the message
   @return the value
   """
   if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
      raise ValueError(f"{what} is {lo}-{hi}")
   return value


def set_place(doc: Document, **fields: Any) -> None:
   """!Sets a fixed tileset's placement (I2): "sheet" (its indexed sheet loaded at "tile"), "tile" (first VRAM
   tile), "tiles" (VRAM tiles it owns), "palette" (first bank), "palettes" (banks it owns). A tileset without one
   becomes fixed (only an empty or indexed-only tileset may: its sheets are then indexed images, its metatiles raw
   entries). Ranges are the engine's (map_compiler MAX_TILES, MAX_PALETTES).
   @param doc     tileset Document
   @param fields  some of PLACE_KEYS
   @return None
   """
   bad = sorted(set(fields) - set(PLACE_KEYS))
   if bad:
      raise ValueError(f"a placement has no {', '.join(bad)} (keys: {', '.join(PLACE_KEYS)})")
   mc = _mc()
   if not is_fixed(doc):
      plain = [s.get("name") for s in doc.data.get("sheets", []) if not s.get("indexed")]
      tiled = [m.get("name") for m in doc.data.get("metatiles", []) if "tiles" in m]
      if plain or tiled:
         raise ValueError("only an empty tileset (or one of indexed sheets) becomes a fixed one: its sheets are "
                          "indexed images and its metatiles raw tilemap entries")
      doc.data["place"] = {"sheet": None, "tile": 0, "tiles": 1, "palette": 0, "palettes": 1}
   pl = doc.data["place"]
   new = dict(pl, **fields)
   if new.get("sheet") is not None and new["sheet"] not in [s.get("name") for s in doc.data.get("sheets", [])]:
      raise ValueError(f"the tileset has no sheet {new['sheet']!r}")
   tile = _whole(new["tile"], 0, mc.MAX_TILES - 1, "tile (the first VRAM tile)")
   _whole(new["tiles"], 1, mc.MAX_TILES - tile, "tiles (VRAM tiles it owns)")
   bank = _whole(new["palette"], 0, mc.MAX_PALETTES - 1, "palette (the first palette bank)")
   _whole(new["palettes"], 0, mc.MAX_PALETTES - bank, "palettes (banks it owns)")
   pl.update(fields)
   if len(doc.data.get("palettes", [])) > pl["palettes"]:
      raise ValueError(f"the tileset lists {len(doc.data['palettes'])} banks; remove some before owning fewer")


def add_indexed_sheet(doc: Document, name: str, source: str | Path) -> str:
   """!Adds an indexed sheet (I2): a palette PNG whose pixels are palette indices 0-15, used as it is. The file
   is copied next to the tileset at once (sheets/NAME.png; the compiler reads indexed sheets from files).
   @param doc     tileset Document (saved: its folder is needed)
   @param name    wanted sheet name (made unique)
   @param source  the PNG
   @return the sheet name used
   """
   if doc.base_dir is None:
      raise ValueError("save the tileset first: an indexed sheet is copied next to it")
   bm = engine.bitmap()
   blob = Path(source).read_bytes()
   try:
      w, h, idx = bm.decode_png_indices(blob, str(source))
   except bm.BitmapError as e:
      raise ValueError(str(e)) from None
   if w % TILE_PIXELS or h % TILE_PIXELS or not w or not h:
      raise ValueError(f"sheet images are multiples of 8 pixels, this one is {w}x{h}")
   if idx and max(idx) > _mc().MAX_PIXEL_4BPP:
      raise ValueError(f"the image uses palette index {max(idx)}; 4bpp tiles use 0-{_mc().MAX_PIXEL_4BPP}")
   name = unique_name([s.get("name") for s in doc.data.get("sheets", [])], name)
   rel = doc.unique_image_path("sheets", name)
   out = doc.base_dir / rel
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_bytes(blob)   # as it is: the indices are the data
   doc.data.setdefault("sheets", []).append({"name": name, "image": rel, "indexed": True})
   return name


def bank_colors(doc: Document) -> list[list[str]]:
   """!A fixed tileset's palette banks (16 "#rrggbb" each, entry 0 included).
   @param doc  tileset Document
   @return the manifest's own lists
   """
   p = doc.data.get("palettes")
   return p if isinstance(p, list) else []


def set_bank_color(doc: Document, bank: int, entry: int, color: str) -> None:
   """!Sets one color of a fixed tileset's bank; banks up to it are added (black) when missing.
   @param doc    tileset Document
   @param bank   bank of the tileset, 0 to its place's palettes - 1 (VRAM bank = place palette + bank)
   @param entry  0-15 (entry 0 is kept for the map's backdrop in bank 0; the runtime loads 1-15)
   @param color  "#rrggbb"
   @return None
   """
   pl = place_of(doc)
   if pl is None:
      raise ValueError("only a fixed tileset (one with a placement) lists palette banks")
   colors = _mc().BANK_COLORS
   _whole(bank, 0, max(0, pl.get("palettes", 0) - 1), "bank (the placement's banks)")
   _whole(entry, 0, colors - 1, "entry")
   if engine.bitmap().parse_rgb(color) is None:
      raise ValueError(f"a color looks like #208020, not {color!r}")
   banks = doc.data.setdefault("palettes", [])
   while len(banks) <= bank:
      banks.append([BLACK] * colors)
   banks[bank][entry] = color.lower()


def remove_last_bank(doc: Document) -> None:
   """!Removes a fixed tileset's last listed bank.
   @param doc  tileset Document
   @return None
   """
   banks = bank_colors(doc)
   if not banks:
      raise ValueError("the tileset lists no banks")
   banks.pop()
   if not banks:
      doc.data.pop("palettes", None)


def split_entry(entry: int) -> tuple[int, bool, bool, int]:
   """!A raw tilemap entry's parts (I2: a fixed tileset's metatile entries; the GBA's text BG map entry).
   @param entry  0-0xFFFF
   @return (VRAM tile, h flip, v flip, palette bank)
   """
   from .mapview import ENTRY_BANK_SHIFT, ENTRY_HFLIP, ENTRY_TILE_MASK, ENTRY_VFLIP
   return entry & ENTRY_TILE_MASK, bool(entry & ENTRY_HFLIP), bool(entry & ENTRY_VFLIP), entry >> ENTRY_BANK_SHIFT


def make_entry(tile: int, hflip: bool = False, vflip: bool = False, bank: int = 0) -> int:
   """!A raw tilemap entry (see split_entry()).
   @param tile   VRAM tile 0-1023
   @param hflip  mirrored horizontally
   @param vflip  mirrored vertically
   @param bank   palette bank 0-15
   @return the entry
   """
   from .mapview import ENTRY_BANK_SHIFT, ENTRY_HFLIP, ENTRY_TILE_MASK, ENTRY_VFLIP
   _whole(tile, 0, ENTRY_TILE_MASK, "tile")
   _whole(bank, 0, _mc().MAX_ENTRY >> ENTRY_BANK_SHIFT, "bank")
   return tile | (ENTRY_HFLIP if hflip else 0) | (ENTRY_VFLIP if vflip else 0) | bank << ENTRY_BANK_SHIFT


def add_fixed_metatile(doc: Document, name: str, entries: Sequence[int] | None = None) -> str:
   """!Adds a fixed tileset's metatile: four raw tilemap entries (any tile any fixed tileset the map loads places).
   @param doc      tileset Document
   @param name     wanted name (made unique)
   @param entries  top-left, top-right, bottom-left, bottom-right (default: the placement's first tile, 4 times)
   @return the name used
   """
   pl = place_of(doc)
   if pl is None:
      raise ValueError("raw entries belong to a fixed tileset (one with a placement)")
   if entries is None:
      entries = [make_entry(pl.get("tile", 0), bank=pl.get("palette", 0))] * TILES_PER_METATILE
   entries = [_whole(e, 0, _mc().MAX_ENTRY, "a tilemap entry") for e in entries]
   if len(entries) != TILES_PER_METATILE:
      raise ValueError(f"a metatile has {TILES_PER_METATILE} entries")
   name = unique_name([m.get("name") for m in doc.data.get("metatiles", [])], name)
   doc.data.setdefault("metatiles", []).append({"name": name, "entries": list(entries)})
   return name


def set_entry(doc: Document, name: str, slot: int, entry: int) -> None:
   """!Sets one raw entry of a fixed tileset's metatile.
   @param doc    tileset Document
   @param name   metatile name
   @param slot   0-3 (top-left, top-right, bottom-left, bottom-right)
   @param entry  0-0xFFFF
   @return None
   """
   _whole(slot, 0, MAX_SLOT, "slot")
   m = metatile(doc, name)
   if "entries" not in m:
      raise ValueError(f"metatile {name!r} has tile references, not raw entries")
   m["entries"][slot] = _whole(entry, 0, _mc().MAX_ENTRY, "a tilemap entry")


# -- tile animations (C-01b; I2 phase, I3 from_sheet / on_shift) ---------------------------------------------------

def animations(doc: Document) -> list[dict[str, Any]]:
   """!A tileset's tile animations.
   @param doc  tileset Document
   @return the manifest's own list
   """
   a = doc.data.get("animations")
   return a if isinstance(a, list) else []


def on_shift_words() -> list[str]:
   """!An animation's "on_shift" values (the engine's map_compiler.ON_SHIFT; I3).
   @return keep, reload, restart
   """
   return list(_mc().ON_SHIFT)


def animation_keys(doc: Document) -> list[str]:
   """!The keys an animation of this tileset takes (map_compiler KEYS "animation", or "fixed_animation" for a fixed
   tileset: "at" instead of "tiles").
   @param doc  tileset Document
   @return key names
   """
   return sorted(_mc().KEYS["fixed_animation" if is_fixed(doc) else "animation"])


def _check_animation(doc: Document, an: dict[str, Any]) -> None:
   """!Checks an animation's fields within the engine's ranges (the compiler checks the sheets and frame counts).
   @param doc  tileset Document
   @param an   the animation dict
   @return None
   """
   mc = _mc()
   bad = sorted(set(an) - set(animation_keys(doc)))
   if bad:
      raise ValueError(f"an animation of this tileset has no {', '.join(bad)} (keys: "
                       f"{', '.join(animation_keys(doc))})")
   period = _whole(an.get("period", mc.DEFAULT_ANIMATION_PERIOD), 1, mc.MAX_ANIMATION_PERIOD, "period")
   _whole(an.get("count", 1), 1, mc.MAX_ANIMATION_TILES, "count")
   if an.get("phase") is not None:
      _whole(an["phase"], 0, period - 1, "phase (frames into the period)")
   if "at" in an:
      _whole(an["at"], 0, mc.MAX_TILES - 1, "at (first tile, counted from the placement's)")
   if not isinstance(an.get("from_sheet", False), bool):
      raise ValueError("from_sheet is true or false")
   if an.get("on_shift", "keep") not in mc.ON_SHIFT:
      raise ValueError(f"on_shift is one of {', '.join(mc.ON_SHIFT)}")
   if an.get("frames") is not None and an["frames"] not in [s.get("name") for s in doc.data.get("sheets", [])]:
      raise ValueError(f"frames names a sheet of this tileset, not {an['frames']!r}")


def add_animation(doc: Document, name: str, frames: str, **fields: Any) -> int:
   """!Adds a tile animation: "count" tiles from "tiles" (a "sheet:index"; a fixed tileset: "at", its first tile
   counted from the placement's) replaced by frames of the sheet "frames", each for "period" display frames;
   "phase", "from_sheet" and "on_shift" as the engine's map_compiler describes.
   @param doc     tileset Document
   @param name    its name
   @param frames  the frame sheet
   @param fields  its other fields
   @return its index
   """
   an = dict({"name": name, "frames": frames}, **{k: v for k, v in fields.items() if v is not None})
   if is_fixed(doc):
      an.setdefault("at", 0)
   elif "tiles" not in an:
      raise ValueError("an animation names its first tile (\"tiles\": \"sheet:index\")")
   _check_animation(doc, an)
   doc.data.setdefault("animations", []).append(an)
   return len(doc.data["animations"]) - 1


def set_animation(doc: Document, index: int, **fields: Any) -> None:
   """!Changes an animation's fields; None removes one (its default applies: phase spread by the compiler,
   from_sheet false, on_shift keep).
   @param doc     tileset Document
   @param index   its index
   @param fields  fields to change
   @return None
   """
   items = animations(doc)
   if not 0 <= index < len(items):
      raise ValueError(f"no animation {index}")
   an = dict(items[index])
   for k, v in fields.items():
      if v is None:
         an.pop(k, None)
      else:
         an[k] = v
   # defaults are left out, as the compiler reads them
   if an.get("from_sheet") is False:
      del an["from_sheet"]
   if an.get("on_shift") == "keep":
      del an["on_shift"]
   _check_animation(doc, an)
   items[index].clear()
   items[index].update(an)


def remove_animation(doc: Document, index: int) -> None:
   """!Removes an animation.
   @param doc    tileset Document
   @param index  its index
   @return None
   """
   items = animations(doc)
   if not 0 <= index < len(items):
      raise ValueError(f"no animation {index}")
   del items[index]
   if not items:
      doc.data.pop("animations", None)


# -- S3 (D-30 section 5, engine DS1): one animation's frames on several targets --------------------------------------

## A target's tile key in a regular tileset ("sheet:index") and in a fixed one (a tile of the placement).
TARGET_REF_KEYS = ("tiles", "at")


def target_ref_key(doc: Document) -> str:
   """!The key naming a target's first tile: "tiles" (a "sheet:index"), or "at" in a fixed tileset.
   @param doc  tileset Document
   @return the key
   """
   return TARGET_REF_KEYS[1] if is_fixed(doc) else TARGET_REF_KEYS[0]


def targets(an: dict[str, Any]) -> list[dict[str, Any]]:
   """!An animation's targets ("targets": [{"tiles" | "at", "offset", "phase"}]); without them its one target is
   its own "tiles" / "at".
   @param an  the animation
   @return the manifest's own list, or [] for the one-target form
   """
   t = an.get("targets")
   return t if isinstance(t, list) else []


def target_keys(doc: Document) -> list[str]:
   """!The keys a target takes (map_compiler KEYS "anim_target" / "fixed_anim_target").
   @param doc  tileset Document
   @return key names
   """
   return sorted(_mc().KEYS["fixed_anim_target" if is_fixed(doc) else "anim_target"])


def _check_targets(doc: Document, an: dict[str, Any], items: Sequence[dict[str, Any]]) -> None:
   """!Checks targets' keys and ranges (the compiler checks offsets against the frame count, overlaps and fits).
   @param doc    tileset Document
   @param an     their animation
   @param items  the targets
   @return None
   """
   mc = _mc()
   if not 1 <= len(items) <= mc.MAX_ANIM_TARGETS + 1:
      raise ValueError(f"an animation has 1-{mc.MAX_ANIM_TARGETS + 1} targets")
   period = an.get("period", mc.DEFAULT_ANIMATION_PERIOD)
   for k, tg in enumerate(items):
      bad = sorted(set(tg) - set(target_keys(doc)))
      if bad:
         raise ValueError(f"target {k} has no {', '.join(bad)} (keys: {', '.join(target_keys(doc))})")
      if target_ref_key(doc) not in tg:
         raise ValueError(f"target {k} names its first tile ({target_ref_key(doc)!r})")
      _whole(tg.get("offset", 0), 0, mc.MAX_ANIMATION_FRAMES - 1, f"target {k} offset (a frame index)")
      if tg.get("phase") is not None:
         _whole(tg["phase"], 0, period - 1, f"target {k} phase (frames into the period)")


def set_targets(doc: Document, index: int, items: Sequence[dict[str, Any]] | None) -> None:
   """!An animation's targets: a list makes it the targets form ("tiles" / "at" and "phase" move into the targets);
   None returns to the one-target form (the first target's tile and phase; refused when its offset is not 0: the
   frames would start elsewhere).
   @param doc    tileset Document
   @param index  the animation
   @param items  [{"tiles" | "at", "offset", "phase"}], or None
   @return None
   """
   anims = animations(doc)
   if not 0 <= index < len(anims):
      raise ValueError(f"no animation {index}")
   an = dict(anims[index])
   ref = target_ref_key(doc)
   if items is None:
      t = targets(an)
      if not t:
         return
      if t[0].get("offset", 0):
         raise ValueError("the first target shows the frames from another offset; keep the targets form")
      an.pop("targets")
      an[ref] = t[0][ref]
      if t[0].get("phase") is not None:
         an["phase"] = t[0]["phase"]
   else:
      clean = [{k: v for k, v in tg.items() if v is not None and not (k == "offset" and v == 0)} for tg in items]
      _check_targets(doc, an, clean)
      an.pop(ref, None)
      an.pop("phase", None)
      an["targets"] = clean
   _check_animation(doc, an)
   anims[index].clear()
   anims[index].update(an)


def use_targets(doc: Document, index: int) -> None:
   """!Turns a one-target animation into the targets form (its tile and phase become target 0, offset 0).
   @param doc    tileset Document
   @param index  the animation
   @return None
   """
   an = animations(doc)[index]
   if targets(an):
      return
   ref = target_ref_key(doc)
   first = {ref: an.get(ref, 0 if ref == TARGET_REF_KEYS[1] else None)}
   if an.get("phase") is not None:
      first["phase"] = an["phase"]
   set_targets(doc, index, [first])


def add_target(doc: Document, index: int, first: Any, offset: int = 0, phase: int | None = None) -> int:
   """!Adds a target (the animation takes the targets form first).
   @param doc     tileset Document
   @param index   the animation
   @param first   its first tile ("sheet:index", or a tile of the placement in a fixed tileset)
   @param offset  the frame it shows when target 0 shows frame 0 (0 to frames - 1)
   @param phase   frames into the period at map entry, or None (the animation's)
   @return the target's index
   """
   use_targets(doc, index)
   items = [dict(t) for t in targets(animations(doc)[index])]
   items.append({target_ref_key(doc): first, "offset": offset, "phase": phase})
   set_targets(doc, index, items)
   return len(items) - 1


def set_target(doc: Document, index: int, k: int, **fields: Any) -> None:
   """!Changes a target's tile, offset or phase (None: phase left to the animation's, offset 0).
   @param doc     tileset Document
   @param index   the animation
   @param k       the target
   @param fields  "tiles" | "at", offset, phase
   @return None
   """
   items = [dict(t) for t in targets(animations(doc)[index])]
   if not 0 <= k < len(items):
      raise ValueError(f"no target {k}")
   items[k].update(fields)
   set_targets(doc, index, items)


def remove_target(doc: Document, index: int, k: int) -> None:
   """!Removes a target; the last one left at offset 0 returns to the one-target form.
   @param doc    tileset Document
   @param index  the animation
   @param k      the target
   @return None
   """
   items = [dict(t) for t in targets(animations(doc)[index])]
   if not 0 <= k < len(items) or len(items) == 1:
      raise ValueError("an animation keeps one target" if len(items) == 1 else f"no target {k}")
   del items[k]
   set_targets(doc, index, items)
   if len(items) == 1 and not items[0].get("offset", 0):
      set_targets(doc, index, None)


def target_frame(t: int, period: int, frames: int, offset: int = 0, phase: int = 0) -> int:
   """!The frame a target shows on a display frame: (t + phase) / period + offset, modulo the frames.
   @param t       display frames since the map was entered
   @param period  the animation's period
   @param frames  its frames
   @param offset  the target's offset
   @param phase   the target's phase
   @return the frame index
   """
   return ((t + phase) // period + offset) % frames


def compiled_animation(ts: Any, index: int) -> dict[str, Any] | None:
   """!A compiled tileset's animation record (map_compiler: frames rotated so target 0 has offset 0, more targets
   as (first, offset, phase)).
   @param ts     compiled Tileset
   @param index  the animation
   @return the record, or None
   """
   anims = getattr(ts, "animations", [])
   return anims[index] if 0 <= index < len(anims) else None


def target_frames(ts: Any, index: int, t: int) -> list[int]:
   """!The frame of the compiled record each target shows on a display frame (target 0 first).
   @param ts     compiled Tileset
   @param index  the animation
   @param t      display frames since the map was entered
   @return frame indices into the record's frames
   """
   rec = compiled_animation(ts, index)
   if rec is None:
      return []
   n = len(rec["frames"])
   phase0 = rec["phase"] or 0
   out = [target_frame(t, rec["period"], n, 0, phase0)]
   out += [target_frame(t, rec["period"], n, off, phase0 if ph is None else ph) for _f, off, ph in rec["targets"]]
   return out


def target_picture(ts: Any, index: int, frame: int, colors: Sequence[int]) -> Image:
   """!One frame's tiles as a picture: 2x2 when it has four tiles (a metatile's), else a row.
   @param ts      compiled Tileset
   @param index   the animation
   @param frame   index into the record's frames
   @param colors  15 BGR555 colors (entries 1-15)
   @return (w, h, RGBA)
   """
   from .mapview import blank, draw_tile
   rec = compiled_animation(ts, index)
   tiles = rec["frames"][frame]
   across = METATILE_TILES if len(tiles) == TILES_PER_METATILE else len(tiles)
   down = (len(tiles) + across - 1) // across
   img = blank(across * TILE_PIXELS, down * TILE_PIXELS)
   for i, tile in enumerate(tiles):
      draw_tile(img, (i % across) * TILE_PIXELS, (i // across) * TILE_PIXELS, tile, colors, 0)
   return img


def target_saved(ts: Any) -> int:
   """!ROM a tileset's animation targets save against one animation (with its own frames) per target.
   @param ts  compiled Tileset
   @return bytes (map_compiler Tileset.target_saved)
   """
   return int(getattr(ts, "target_saved", 0))


def bank_of_tile(doc: Document, at: int) -> int | None:
   """!S3: the palette bank a fixed tileset's metatiles draw one of its tiles in (the first entry naming it), so an
   animation's frames are previewed in the colours the map shows them in.
   @param doc  fixed tileset Document
   @param at   the tile, counted from the placement's first tile
   @return the VRAM bank, or None when no metatile entry names the tile
   """
   place = place_of(doc)
   if place is None:
      return None
   tile = place.get("tile", 0) + at
   for mt in doc.data.get("metatiles", []):
      for e in mt.get("entries", []) if isinstance(mt, dict) else []:
         if isinstance(e, int):
            t, _h, _v, bank = split_entry(e)
            if t == tile:
               return bank
   return None
