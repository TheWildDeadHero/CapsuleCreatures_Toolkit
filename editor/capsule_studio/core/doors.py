"""![S3] Door animations (D-30 section 1, engine DS1): the asset kind "door" of an asset manifest
(capsule.assets/1) and the world's door bindings.

A door covers "cells" [width, height] metatiles; the cell a map binds it to (its anchor) is the bottom-left one.
Its frames show either as tiles loaded into the map's tile area ("show": "tiles": a "sheet" of frames,
"frame_tiles" per frame, loaded at "load_at" ("end": the area's last tiles), and "entries": per cell, top row first,
per layer four map entries, a frame tile {"tile": k, "palette": bank, "flip"} or a raw entry) or as cell overrides
("show": "override": "frames", per frame the cells' raw entries). "layers" is how many of the map's tile layers it
draws (the others keep the cell's own metatiles). "open" lists its opening steps [frame or "closed", ticks]
(a step's frame shows from its first display frame for its ticks), "close" the same or "reverse" (the open steps
backwards, the default). "sounds" {"open", "close"} name sound keys; "exit" is the direction a walker arriving on it
walks out. The engine's asset_compiler.compile_door() decides what is valid; previews draw a frame as
capsule/field/doors.cpp draw() does.

A sheet of indexed pixels holds palette indices into the map's banks (the entries name the bank), so a door is shown
in a map's palettes when previewed on that map, and in a gray ramp alone.

Bindings: a warp's "door": "door:KEY" binds its own cell (core.events FIELDS); the world's "doors" list
[{"tileset": T or "*", "metatile": NAME, "door": KEY}] binds every cell showing that metatile on any layer
(map_compiler.compile_door_bindings(); a warp binding wins).

S4: the engine does not check that a door's sounds name sounds the game has (it hashes the key into the door's
record and game::door_sound() plays it); sound_problems() does: a sound is "sound:NAME" where NAME is a sound asset
of the manifest (a key "sound:NAME") or a constant of the game's scripts manifest (the sound ids its `sound se NAME`
statements play, the importer's SE_* constants), found through project.json or the world near the manifest
(sound_keys()).

Functions that change a Document must run inside its edit(). Nothing here imports Qt.
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import engine
from .imaging import RGBA_BYTES
from .mapview import (BANK_SIZE, ENTRY_BANK_SHIFT, ENTRY_HFLIP, ENTRY_TILE_MASK, ENTRY_VFLIP, GRAY_STEP, METATILE,
                      TILE, TileCache, blank, render_map)
from .preview import BLUE_SHIFT, GREEN_SHIFT

if TYPE_CHECKING:
   from .document import AssetReport, Document
   from .imaging import RgbaImage
   from .world import Project

## A parsed JSON object (an asset, a binding).
JsonDict = dict[str, Any]
## One step of an opening or closing: [frame or "closed", ticks].
Step = list[Any]

## The asset kind.
KIND = "door"
## A door key's namespace ("door:NAME").
KEY_PREFIX = "door:"
## The world's door bindings by metatile.
BINDINGS_KEY = "doors"
## A warp's door binding (event_compiler KEYS "warp").
WARP_KEY = "door"
## Frames a new door has.
NEW_FRAMES = 3
## Ticks of a new door's steps (display frames).
NEW_TICKS = 4
## 4bpp tile data: 32-bit words per tile (one per row) and bits per pixel.
WORDS_PER_TILE = 8
## Bits of one 4bpp pixel.
BITS_PER_PIXEL = 4
## Mask of one 4bpp pixel.
PIXEL_MASK = 0xF
## Map entry flip words of a frame tile ({"flip": "h" | "v" | "hv"}).
FLIP_WORDS = ("", "h", "v", "hv")
## Numbers in a door's "cells": [width, height].
CELL_AXES = 2
## Display order of a cell's four entries.
SLOTS = ("top-left", "top-right", "bottom-left", "bottom-right")
## Sides a preview margin is drawn on, across or down.
SIDES = 2
## A transparent RGBA pixel.
TRANSPARENT = (0, 0, 0, 0)
## Cells drawn around a door previewed on a map.
PREVIEW_MARGIN = 1
## Folder below the manifest a door's copied sheet goes to.
SHEET_FOLDER = "doors"
## Folders searched for a game's world and asset manifests (beside the manifest, in its parent and their children).
WORLD_FILE = "world.json"
## A game's asset manifest file name, when no project.json names it.
ASSETS_FILE = "assets.json"
## S4: the key namespace of a sound ("sound:NAME").
SOUND_PREFIX = "sound:"
## S4: a constant declaration of a .cscript source (`const NAME = value;`).
CONST_DECLARATION = re.compile(r"^[ \t]*const[ \t]+(?P<name>[A-Za-z_]\w*)[ \t]*=", re.MULTILINE)
## S4: the constants of a source by (path, its time): the scan is done again only when the file changes.
_CONSTANTS_CACHE: dict[tuple[str, int], list[str]] = {}


def _ac() -> Any:
   """!The engine's asset compiler.
   @return module
   """
   return engine.asset_compiler()


def shows() -> list[str]:
   """!How a door's frames show (asset_compiler DOOR_SHOWS, asset::DoorShow order).
   @return "tiles", "override"
   """
   return list(_ac().DOOR_SHOWS)


def directions() -> list[str]:
   """!A door's exit directions (asset_compiler DIRECTIONS).
   @return down, up, left, right
   """
   return list(_ac().DIRECTIONS)


def closed_word() -> str:
   """!The step frame of the closed door (asset_compiler DOOR_CLOSED_WORD).
   @return "closed"
   """
   return str(_ac().DOOR_CLOSED_WORD)


def reverse_word() -> str:
   """!A close given as the open steps backwards (asset_compiler DOOR_REVERSE).
   @return "reverse"
   """
   return str(_ac().DOOR_REVERSE)


def load_end_word() -> str:
   """!The default first map tile of a tiles door (asset_compiler DOOR_LOAD_END: the area's last tiles).
   @return "end"
   """
   return str(_ac().DOOR_LOAD_END)


def limits() -> dict[str, int]:
   """!The engine's door limits.
   @return {"cells": most cells across or down, "layers", "ticks": most display frames a step shows, "steps",
           "map_tiles": tiles of the map's tile area, "palette": highest bank}
   """
   ac = _ac()
   return {"cells": ac.MAX_DOOR_CELLS, "layers": ac.MAX_MAP_LAYERS, "ticks": ac.MAX_FRAME_DURATION,
           "steps": ac.MAX_ANIM_FRAMES, "map_tiles": ac.MAP_TILES, "palette": ac.MAX_ENTRY_PALETTE}


def doors(doc: Document) -> list[JsonDict]:
   """!The door assets of a manifest, in order.
   @param doc  asset manifest Document
   @return assets (live)
   """
   return doc.assets(KIND)


def cells_of(asset: JsonDict) -> tuple[int, int]:
   """!A door's size in metatiles.
   @param asset  door asset
   @return (width, height)
   """
   c = asset.get("cells", [1, 1])
   return (c[0], c[1]) if isinstance(c, list) and len(c) == CELL_AXES else (1, 1)


def layers_of(asset: JsonDict) -> int:
   """!The map layers a door draws.
   @param asset  door asset
   @return 1-4
   """
   n = asset.get("layers", 1)
   return n if isinstance(n, int) else 1


def show_of(asset: JsonDict) -> str:
   """!How a door's frames show.
   @param asset  door asset
   @return "tiles" or "override"
   """
   return asset.get("show", shows()[0])


def _tile_cell(c: int, layers: int, frame_tiles: int) -> list[list[Any]]:
   """!A new tiles door's cell: layer 0 draws the frame's tiles 4c .. 4c + 3 (raw 0 past the frame), the others 0.
   @param c            cell index (top row first)
   @param layers       layers per cell
   @param frame_tiles  tiles per frame
   @return [layers: [4 entries]]
   """
   first = c * len(SLOTS)
   own = [{"tile": first + j} if first + j < frame_tiles else 0 for j in range(len(SLOTS))]
   return [own] + [[0] * len(SLOTS) for _ in range(layers - 1)]


def _raw_cell(layers: int) -> list[list[int]]:
   """!A cell of raw entries 0.
   @param layers  layers per cell
   @return [layers: [4 zeros]]
   """
   return [[0] * len(SLOTS) for _ in range(layers)]


def new_door(doc: Document, key: str, width: int = 1, height: int = 1, show: str | None = None,
             index: int | None = None) -> JsonDict:
   """!Adds a door that compiles: a tiles door gets an empty shapes sheet of NEW_FRAMES frames and entries drawing
   each frame's tiles in reading order, an override door NEW_FRAMES frames of raw entries 0; it opens through
   its frames (NEW_TICKS each) from closed and closes in reverse.
   @param doc     asset manifest Document
   @param key     "door:NAME"
   @param width   cells across
   @param height  cells down
   @param show    "tiles" (default) or "override"
   @param index   position in the manifest, or None for the end
   @return the asset
   """
   if not isinstance(key, str) or not key.startswith(KEY_PREFIX):
      raise ValueError(f"a door's key is {KEY_PREFIX}NAME")
   show = show or shows()[0]
   if show not in shows():
      raise ValueError(f"a door shows as {' or '.join(shows())}")
   cells = width * height
   a: JsonDict = {"key": key, "kind": KIND, "cells": [width, height]}
   if show == shows()[0]:
      frame_tiles = cells * len(SLOTS)
      a["sheet"] = {"size": [width * METATILE, height * METATILE * NEW_FRAMES], "shapes": []}
      a["frame_tiles"] = frame_tiles
      a["entries"] = [_tile_cell(c, 1, frame_tiles) for c in range(cells)]
   else:
      a["show"] = show
      a["frames"] = [[_raw_cell(1) for _ in range(cells)] for _ in range(NEW_FRAMES)]
   a["open"] = [[closed_word(), NEW_TICKS]] + [[f, NEW_TICKS] for f in range(NEW_FRAMES)]
   check(doc, a)
   return doc.add_asset(a, index)


def check(doc: Document, asset: JsonDict) -> JsonDict:
   """!Compiles a door with the engine's compiler.
   @param doc    asset manifest Document (images are relative to it)
   @param asset  the door asset
   @return compile_door()'s result
   @throws ValueError with the compiler's message
   """
   report = doc.compile_asset(asset)
   if not report.ok:
      raise ValueError(report.error)
   return report.compiled


def compiled(doc: Document, key: str) -> AssetReport:
   """!A door compiled (the report keeps the error).
   @param doc  asset manifest Document
   @param key  door key
   @return AssetReport (compiled: compile_door()'s result)
   """
   return doc.compile_asset(doc.get(key))


def _edit(doc: Document, key: str, change: Any) -> None:
   """!Changes a copy of a door, checks it with the compiler and stores it.
   @param doc     asset manifest Document
   @param key     door key
   @param change  callable(asset copy) -> None
   @return None
   """
   a = doc.get(key)
   b = copy.deepcopy(a)
   change(b)
   check(doc, b)
   a.clear()
   a.update(b)


def _resize_cells(raw: list[Any], old: tuple[int, int], new: tuple[int, int], make: Any) -> list[Any]:
   """!A cell list (top row first) for a new size, each kept cell at the same place counted from the bottom-left
   anchor; new cells from make(index).
   @param raw   the cells
   @param old   (width, height) before
   @param new   (width, height) after
   @param make  callable(new cell index) -> a new cell
   @return the cells
   """
   (ow, oh), (nw, nh) = old, new
   out = []
   for cy in range(nh):
      for cx in range(nw):
         up = nh - 1 - cy   # rows above the anchor's
         oy = oh - 1 - up
         out.append(copy.deepcopy(raw[oy * ow + cx]) if 0 <= oy < oh and cx < ow and oy * ow + cx < len(raw)
                    else make(cy * nw + cx))
   return out


def set_cells(doc: Document, key: str, width: int, height: int) -> None:
   """!A door's size (its cells keep their place from the bottom-left anchor; new cells draw nothing new: raw 0,
   or in a tiles door the frame's tiles they would take in reading order).
   @param doc     asset manifest Document
   @param key     door key
   @param width   cells across
   @param height  cells down
   @return None
   """
   def change(a: JsonDict) -> None:
      old, layers = cells_of(a), layers_of(a)
      a["cells"] = [width, height]
      if show_of(a) == shows()[0]:
         ft = a.get("frame_tiles", 0)
         a["entries"] = _resize_cells(a.get("entries", []), old, (width, height),
                                      lambda c: _tile_cell(c, layers, ft)[:layers])
      else:
         a["frames"] = [_resize_cells(f, old, (width, height), lambda c: _raw_cell(layers))
                        for f in a.get("frames", [])]
   _edit(doc, key, change)


def set_layers(doc: Document, key: str, layers: int) -> None:
   """!How many map layers a door draws (new layers raw 0; the map's other layers keep the cell's own metatiles).
   @param doc     asset manifest Document
   @param key     door key
   @param layers  1-4
   @return None
   """
   def fit(cell: list[Any]) -> list[Any]:
      return [copy.deepcopy(cell[k]) if k < len(cell) else [0] * len(SLOTS) for k in range(layers)]

   def change(a: JsonDict) -> None:
      if layers == 1:
         a.pop("layers", None)
      else:
         a["layers"] = layers
      if show_of(a) == shows()[0]:
         a["entries"] = [fit(c) for c in a.get("entries", [])]
      else:
         a["frames"] = [[fit(c) for c in f] for f in a.get("frames", [])]
   _edit(doc, key, change)


def set_show(doc: Document, key: str, show: str) -> None:
   """!How a door's frames show; the other form's data is replaced by a new door's (its size, layers, timing,
   sounds and exit are kept; steps naming frames it no longer has are dropped).
   @param doc   asset manifest Document
   @param key   door key
   @param show  "tiles" or "override"
   @return None
   """
   def change(a: JsonDict) -> None:
      if show_of(a) == show:
         return
      w, h = cells_of(a)
      layers = layers_of(a)
      for k in ("sheet", "frame_tiles", "load_at", "entries", "frames", "show"):
         a.pop(k, None)
      if show == shows()[0]:
         ft = w * h * len(SLOTS)
         a["sheet"] = {"size": [w * METATILE, h * METATILE * NEW_FRAMES], "shapes": []}
         a["frame_tiles"] = ft
         a["entries"] = [_tile_cell(c, layers, ft) for c in range(w * h)]
      else:
         a["show"] = show
         a["frames"] = [[_raw_cell(layers) for _ in range(w * h)] for _ in range(NEW_FRAMES)]
      for which in ("open", "close"):
         if isinstance(a.get(which), list):
            a[which] = [s for s in a[which] if s[0] == closed_word() or s[0] < NEW_FRAMES] or \
               [[closed_word(), NEW_TICKS]]
   _edit(doc, key, change)


def set_fields(doc: Document, key: str, **fields: Any) -> None:
   """!Sets plain fields of a door: "exit", "load_at" ("end" or a map tile), "frame_tiles", "sounds" ({"open",
   "close"}: None leaves one out); None removes a field (its default applies).
   @param doc     asset manifest Document
   @param key     door key
   @param fields  the fields
   @return None
   """
   allowed = {"exit", "load_at", "frame_tiles", "sounds"}
   bad = sorted(set(fields) - allowed)
   if bad:
      raise ValueError(f"set_fields() sets {', '.join(sorted(allowed))}, not {', '.join(bad)}")

   def change(a: JsonDict) -> None:
      for k, v in fields.items():
         if k == "sounds" and isinstance(v, dict):
            v = {s: n for s, n in v.items() if n}
         if v is None or v == {} or (k == "exit" and v == directions()[0]) or \
               (k == "load_at" and v == load_end_word()):
            a.pop(k, None)
         else:
            a[k] = v
   _edit(doc, key, change)


def entry(asset: JsonDict, cell: int, layer: int, slot: int, frame: int = 0) -> Any:
   """!One entry of a door's cell.
   @param asset  door asset
   @param cell   cell index (top row first)
   @param layer  layer
   @param slot   0-3 (SLOTS)
   @param frame  an override door's frame (a tiles door has one entry set)
   @return a raw map entry (int) or a frame tile {"tile", "palette", "flip"}
   """
   cells = asset["entries"] if show_of(asset) == shows()[0] else asset["frames"][frame]
   return cells[cell][layer][slot]


def set_entry(doc: Document, key: str, cell: int, layer: int, slot: int, value: Any, frame: int = 0) -> None:
   """!Sets one entry of a door's cell: a raw map entry, or (a tiles door) a frame tile {"tile": k, "palette":
   bank, "flip": "h" | "v" | "hv"} (palette 0 and no flip are left out).
   @param doc    asset manifest Document
   @param key    door key
   @param cell   cell index (top row first)
   @param layer  layer
   @param slot   0-3
   @param value  the entry
   @param frame  an override door's frame
   @return None
   """
   if isinstance(value, dict):
      value = {k: v for k, v in value.items() if not (k == "palette" and v == 0) and not (k == "flip" and not v)}

   def change(a: JsonDict) -> None:
      cells = a["entries"] if show_of(a) == shows()[0] else a["frames"][frame]
      cells[cell][layer][slot] = value
   _edit(doc, key, change)


def entry_text(value: Any) -> str:
   """!An entry as short text: "t3" (frame tile 3), "t3 p1 hv" (bank 1, flipped), or a raw entry "0x1004".
   @param value  the entry
   @return text
   """
   if isinstance(value, dict):
      parts = [f"t{value.get('tile', 0)}"]
      if value.get("palette"):
         parts.append(f"p{value['palette']}")
      if value.get("flip"):
         parts.append(str(value["flip"]))
      return " ".join(parts)
   return f"0x{int(value):04x}"


def parse_entry(text: str) -> Any:
   """!The entry entry_text() writes: "t3 p1 hv" (a frame tile) or a raw entry (decimal or 0x hex).
   @param text  the text
   @return an int or {"tile", "palette", "flip"}
   """
   words = text.strip().lower().split()
   if not words:
      raise ValueError("an entry is tK [pB] [h|v|hv], or a map entry")
   if words[0].startswith("t") and words[0][1:].isdigit():
      out: JsonDict = {"tile": int(words[0][1:])}
      for w in words[1:]:
         if w.startswith("p") and w[1:].isdigit():
            out["palette"] = int(w[1:])
         elif w in FLIP_WORDS[1:]:
            out["flip"] = w
         else:
            raise ValueError(f"{w!r}: an entry's words are tK, pB and h, v or hv")
      return out
   try:
      return int(words[0], 0)
   except ValueError:
      raise ValueError(f"{text!r} is not an entry (tK [pB] [h|v|hv], or a map entry)") from None


def is_reverse(asset: JsonDict) -> bool:
   """!Whether a door closes with its open steps backwards.
   @param asset  door asset
   @return True when "close" is "reverse" or left out
   """
   return asset.get("close", reverse_word()) == reverse_word()


def steps(asset: JsonDict, which: str) -> list[Step]:
   """!A door's opening or closing steps ("reverse" resolved).
   @param asset  door asset
   @param which  "open" or "close"
   @return [[frame or "closed", ticks]]
   """
   if which == "close" and is_reverse(asset):
      return [list(s) for s in reversed(asset.get("open", []))]
   return [list(s) for s in asset.get(which, [])]


def set_steps(doc: Document, key: str, which: str, value: Sequence[Step] | str) -> None:
   """!A door's opening or closing steps; "reverse" makes the close the open steps backwards.
   @param doc    asset manifest Document
   @param key    door key
   @param which  "open" or "close"
   @param value  [[frame or "closed", ticks]], or "reverse" (close only)
   @return None
   """
   if which not in ("open", "close"):
      raise ValueError("a door's steps are its open or its close")

   def change(a: JsonDict) -> None:
      if value == reverse_word():
         if which == "open":
            raise ValueError("only the close may be the open reversed")
         a.pop("close", None)
      else:
         a[which] = [list(s) for s in value]
   _edit(doc, key, change)


def timeline(asset: JsonDict, which: str) -> list[Any]:
   """!Which frame shows on each display frame of an opening or closing, as doors::update() plays it (a step's
   frame from its first display frame for its ticks; the last stays).
   @param asset  door asset
   @param which  "open" or "close"
   @return frame indices or "closed", one per display frame
   """
   out = []
   for frame, ticks in steps(asset, which):
      out += [frame] * ticks
   return out


def set_sheet_image(doc: Document, key: str, source: str | Path) -> str:
   """!A tiles door's sheet becomes an indexed PNG (a palette PNG: its indices are the data, entries into the bank
   each frame tile names), copied next to the manifest at once (doors/NAME.png).
   @param doc     asset manifest Document (saved: its folder is needed)
   @param key     door key
   @param source  the palette PNG
   @return its manifest path
   """
   if doc.base_dir is None:
      raise ValueError("save the manifest first: a door's sheet is copied next to it")
   slug = key.split(":", 1)[-1].strip().lower().replace(" ", "_") or "door"
   rel = doc.unique_image_path(SHEET_FOLDER, slug)
   out = doc.base_dir / rel
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_bytes(Path(source).read_bytes())   # as it is: the indices are the data

   def change(a: JsonDict) -> None:
      a["sheet"] = {"image": rel, "indexed": True}
   _edit(doc, key, change)
   return rel


def sheet_tiles(doc: Document, asset: JsonDict) -> tuple[int, list[Any]]:
   """!A tiles door's sheet as the compiler reads it (asset_compiler.door_sheet_tiles()).
   @param doc    asset manifest Document
   @param asset  door asset
   @return (sheet width in tiles, tiles in reading order: 8 rows of 8 palette indices)
   """
   ac = _ac()
   sheet = asset.get("sheet")
   tiles = ac.door_sheet_tiles(sheet, doc.base_dir, None, str(asset.get("key")))
   if isinstance(sheet, dict) and "image" in sheet:
      w, _h, _px = engine.bitmap().read_png_indices(doc.base_dir / sheet["image"])
   else:
      w = sheet["size"][0]
   return w // TILE, tiles


def frame_tiles_of(compiled_door: JsonDict, frame: int) -> list[list[list[int]]]:
   """!A compiled tiles door's frame as tiles (decoded from its 4bpp words, as the engine loads them).
   @param compiled_door  compile_door()'s result
   @param frame          the frame
   @return frame_tiles tiles, each 8 rows of 8 palette indices
   """
   words = compiled_door["tiles"]
   n = compiled_door["frame_tiles"]
   out = []
   for t in range(frame * n, (frame + 1) * n):
      rows = words[t * WORDS_PER_TILE:(t + 1) * WORDS_PER_TILE]
      # 4bpp: the leftmost pixel is in the word's lowest bits
      out.append([[(w >> (BITS_PER_PIXEL * x)) & PIXEL_MASK for x in range(TILE)] for w in rows])
   return out


def gray_palettes() -> list[list[int]]:
   """!Palette banks for a door shown without a map: every bank a gray ramp (index i as gray), so the indices show.
   @return 16 banks of 15 BGR555 colors
   """
   ramp = [GRAY_STEP * i | GRAY_STEP * i << GREEN_SHIFT | GRAY_STEP * i << BLUE_SHIFT for i in range(1, BANK_SIZE)]
   return [list(ramp) for _ in range(BANK_SIZE)]


def frame_cells(compiled_door: JsonDict, frame: Any) -> list[list[tuple[int, ...]]] | None:
   """!The entries a frame draws, per cell (top row first) per door layer, as doors.cpp draw() takes them.
   @param compiled_door  compile_door()'s result
   @param frame          frame index, or "closed"
   @return [cells: [layers: (4 entries)]], or None for the closed door (the cells show their own metatiles)
   """
   frames = compiled_door["frames"]
   if frame == closed_word() or not isinstance(frame, int) or not 0 <= frame < frames:
      return None
   layers = compiled_door["layers"]
   cells = compiled_door["width"] * compiled_door["height"]
   per_cell = layers * len(SLOTS)
   # an override door has one entry set per frame, a tiles door one for all its frames
   base = frame * cells * per_cell if compiled_door["entry_frames"] > 1 else 0
   e = compiled_door["entries"]
   return [[tuple(e[base + c * per_cell + k * len(SLOTS):base + c * per_cell + (k + 1) * len(SLOTS)])
            for k in range(layers)] for c in range(cells)]


def _with_frame(mp: JsonDict, compiled_door: JsonDict, frame: Any) -> JsonDict:
   """!A compiled map (or a stand-in) with a tiles door's frame loaded into its tile area (map::load_tiles()).
   @param mp             compile_map()'s result
   @param compiled_door  compile_door()'s result
   @param frame          frame index, or "closed"
   @return a shallow copy with its own tile list (the map itself unchanged)
   """
   if compiled_door["show"] != 0 or frame_cells(compiled_door, frame) is None:
      return mp
   out = dict(mp)
   tiles = list(mp["tiles"])
   start = compiled_door["load_at"]
   loaded = frame_tiles_of(compiled_door, frame)
   empty = [[0] * TILE for _ in range(TILE)]
   tiles += [empty] * max(0, start + len(loaded) - len(tiles))
   tiles[start:start + len(loaded)] = loaded
   out["tiles"] = tiles
   return out


def render_alone(compiled_door: JsonDict, frame: Any, palettes: Sequence[Sequence[int]] | None = None,
                 backdrop: tuple[int, int, int, int] | None = None) -> RgbaImage:
   """!A door's frame by itself: its cells drawn from its layers (layer 0 first), in some palette banks.
   @param compiled_door  compile_door()'s result
   @param frame          frame index, or "closed" (drawn empty)
   @param palettes       the banks (BGR555, 15 colors each; a map's), or None for gray_palettes()
   @param backdrop       RGBA behind it, or None for transparent
   @return (width * 16, height * 16, RGBA)
   """
   w, h = compiled_door["width"], compiled_door["height"]
   stand_in = {"tiles": [], "palettes": [list(p) for p in (palettes or gray_palettes())], "metatiles": []}
   mp = _with_frame(stand_in, compiled_door, frame)
   img = blank(w * METATILE, h * METATILE, backdrop or TRANSPARENT)
   cells = frame_cells(compiled_door, frame)
   if cells is None:
      return img
   cache = TileCache(mp)
   iw, _ih, px = img
   for c, layers in enumerate(cells):
      ox, oy = (c % w) * METATILE, (c // w) * METATILE
      for e in layers:
         _w, _h, rgba = cache.entries(e)
         for y in range(METATILE):
            for x in range(METATILE):
               s = (y * METATILE + x) * RGBA_BYTES
               if rgba[s + RGBA_BYTES - 1]:   # opaque pixels only (alpha is the last byte)
                  o = ((oy + y) * iw + ox + x) * RGBA_BYTES
                  px[o:o + RGBA_BYTES] = rgba[s:s + RGBA_BYTES]
   return img


def overrides_for(compiled_door: JsonDict, frame: Any, x: int, y: int, layer_count: int) -> dict[Any, Any]:
   """!What a frame draws over a map, as mapview.render_map() overrides: the door's layers of each cell (the map's
   other layers keep the cell's own metatiles, as doors.cpp draw() does).
   @param compiled_door  compile_door()'s result
   @param frame          frame index, or "closed" (no overrides)
   @param x              anchor column (the bottom-left cell)
   @param y              anchor row
   @param layer_count    the map's tile layers
   @return {(x, y, layer): (4 entries)}
   """
   cells = frame_cells(compiled_door, frame)
   if cells is None:
      return {}
   w, h = compiled_door["width"], compiled_door["height"]
   top = y - (h - 1)   # the anchor is the bottom-left cell
   out = {}
   for c, layers in enumerate(cells):
      for k, e in enumerate(layers[:layer_count]):
         out[(x + c % w, top + c // w, k)] = e
   return out


def render_on_map(project: Project, map_name: str, x: int, y: int, compiled_door: JsonDict, frame: Any,
                  margin: int = PREVIEW_MARGIN) -> RgbaImage | None:
   """!A door's frame drawn on a map cell with the cells around it, in the map's palettes (a tiles door's frame
   loaded at its load_at first).
   @param project        Project
   @param map_name       the map
   @param x              anchor column (the bottom-left cell)
   @param y              anchor row
   @param compiled_door  compile_door()'s result
   @param frame          frame index, or "closed"
   @param margin         cells drawn around the door
   @return (w, h, RGBA), or None when the map does not compile
   """
   mp, _error = project.compiled_map(map_name)
   if mp is None:
      return None
   w, h = compiled_door["width"], compiled_door["height"]
   shown = _with_frame(mp, compiled_door, frame)
   around = SIDES * margin   # the margin on both sides
   return render_map(shown, x - margin, y - (h - 1) - margin, w + around, h + around,
                     overrides=overrides_for(compiled_door, frame, x, y, len(mp["layers"])))


def entry_fields(entry: int) -> str:
   """!A raw entry's fields as text (for tooltips).
   @param entry  map entry
   @return "tile T bank B [h] [v]"
   """
   flips = ("h " if entry & ENTRY_HFLIP else "") + ("v" if entry & ENTRY_VFLIP else "")
   return f"tile {entry & ENTRY_TILE_MASK} bank {entry >> ENTRY_BANK_SHIFT} {flips}".strip()


# -- bindings --------------------------------------------------------------------------------------------------------

def bindings(world: Document) -> list[JsonDict]:
   """!The world's door bindings by metatile.
   @param world  world Document
   @return the manifest's own list
   """
   b = world.data.get(BINDINGS_KEY)
   return b if isinstance(b, list) else []


def _check_bindings(raw: list[JsonDict]) -> None:
   """!The engine's checks of binding rules (map_compiler.compile_door_bindings() without maps).
   @param raw  the bindings
   @return None
   """
   mc = engine.tool("map_compiler")
   try:
      mc.compile_door_bindings({BINDINGS_KEY: raw}, [], {})
   except mc.ManifestError as e:
      raise ValueError(str(e)) from None


def add_binding(world: Document, tileset: str, metatile: str, key: str) -> int:
   """!Binds a door to every cell showing a metatile (call inside world.edit()).
   @param world     world Document
   @param tileset   the metatile's tileset, or "*" for any of a map's tilesets
   @param metatile  the metatile's name
   @param key       "door:NAME"
   @return the binding's index
   """
   raw = bindings(world) + [{"tileset": tileset, "metatile": metatile, "door": key}]
   _check_bindings(raw)
   world.data[BINDINGS_KEY] = raw
   return len(raw) - 1


def set_binding(world: Document, index: int, **fields: str) -> None:
   """!Changes a binding's tileset, metatile or door (call inside world.edit()).
   @param world   world Document
   @param index   the binding
   @param fields  tileset, metatile, door
   @return None
   """
   raw = copy.deepcopy(bindings(world))
   if not 0 <= index < len(raw):
      raise ValueError(f"no door binding {index}")
   raw[index].update(fields)
   _check_bindings(raw)
   world.data[BINDINGS_KEY] = raw


def remove_binding(world: Document, index: int) -> None:
   """!Removes a binding (call inside world.edit()).
   @param world  world Document
   @param index  the binding
   @return None
   """
   raw = bindings(world)
   if not 0 <= index < len(raw):
      raise ValueError(f"no door binding {index}")
   del raw[index]
   if not raw:
      world.data.pop(BINDINGS_KEY, None)


def warp_doors(doc: Document) -> list[tuple[int, list[int], str]]:
   """!A map's warps that bind a door.
   @param doc  map Document
   @return [(warp index, its cell [x, y], door key)]
   """
   from . import events
   return [(i, w.get("at"), w[WARP_KEY]) for i, w in enumerate(events.events(doc, "warps")) if WARP_KEY in w]


def bound_cells(project: Project, map_name: str, key: str | None = None) -> list[tuple[int, int, str, str]]:
   """!The anchors of a map's doors: its warps' doors, then every cell showing a bound metatile on any layer (as
   map_compiler.compile_door_bindings() binds them; a warp's binding wins on its cell).
   @param project   Project
   @param map_name  the map
   @param key       only this door, or None
   @return [(x, y, door key, "warp N" or "metatile TILESET/NAME")]
   """
   from . import mapview
   mc = engine.tool("map_compiler")
   out, seen = [], set()
   for i, at, k in warp_doors(project.map(map_name)):
      if (key is None or k == key) and isinstance(at, list):
         out.append((at[0], at[1], k, f"warp {i}"))
         seen.add((at[0], at[1]))
   mp, _error = project.compiled_map(map_name)
   rules = [b for b in bindings(project.world) if key is None or b.get("door") == key]
   if mp is None or not rules:
      return out
   ids: dict[int, tuple[str, str]] = {}
   for idx, name in enumerate(mp["dictionary"]):
      ts, mt = name.split("/", 1)
      for b in rules:
         if b.get("metatile") == mt and b.get("tileset") in (mc.ANY_TILESET, ts):
            ids.setdefault(idx, (b["door"], name))
   if not ids:
      return out
   x0, y0, w, h = mapview.map_bounds(mp)
   for y in range(y0, y0 + h):
      for x in range(x0, x0 + w):
         if (x, y) in seen or mc.cell_at(mp, x, y) == mc.CELL_UNDEFINED:
            continue
         for k in range(len(mp["layers"])):
            hit = ids.get(mc.metatile_at(mp, k, x, y))
            if hit is not None:
               out.append((x, y, hit[0], f"metatile {hit[1]}"))
               seen.add((x, y))
               break
   return out


def find_anchor(project: Project, key: str, prefer: str | None = None) -> tuple[str, int, int, str] | None:
   """!A map cell a door is bound to, for previews: the preferred map first, then the maps drawing from a tileset a
   binding of the door names (map heads: maps are compiled only until one has a bound cell).
   @param project  Project
   @param key      the door
   @param prefer   a map to look at first, or None
   @return (map, x, y, how), or None
   """
   tilesets = {b.get("tileset") for b in bindings(project.world) if b.get("door") == key}
   any_tileset = engine.tool("map_compiler").ANY_TILESET in tilesets
   names = ([prefer] if prefer in project.map_names() else []) + [
      m for m in project.map_names() if m != prefer and
      (any_tileset or tilesets & set(project.map_head(m).get("tilesets") or []))]
   for m in names:
      cells = bound_cells(project, m, key)
      if cells:
         x, y, _k, how = cells[0]
         return m, x, y, how
   return None


# -- where a game's files are -----------------------------------------------------------------------------------------

def _game_file(start: Path, key: str) -> Path | None:
   """!A file the game's reference/project.json names, found from a file of the game.
   @param start  a file of the game (the world or an asset manifest)
   @param key    project.json key ("maps", "assets")
   @return the path, or None
   """
   folder = start.resolve().parent
   for _ in range(len(start.resolve().parts)):
      candidate = folder / "reference" / "project.json"
      if candidate.is_file():
         try:
            rel = json.loads(candidate.read_text(encoding="utf-8")).get(key)
         except (OSError, ValueError, AttributeError):
            rel = None
         return (folder / rel).resolve() if isinstance(rel, str) and rel else None
      if folder.parent == folder:
         break
      folder = folder.parent
   return None


def _nearby(start: Path, name: str) -> list[Path]:
   """!Files of a name beside a file, in its folder's parent and in their child folders (an imported game's
   overworld/assets.json beside world/world.json; a sandbox's data/assets.json beside data/world.json).
   @param start  the file
   @param name   file name
   @return paths, nearest first
   """
   here = start.resolve().parent
   out = []
   for folder in (here, here.parent):
      for p in [folder / name] + sorted(q / name for q in folder.iterdir() if q.is_dir()) if folder.is_dir() else []:
         if p.is_file() and p not in out:
            out.append(p)
   return out


def asset_manifests(project: Project) -> list[Path]:
   """!The game's asset manifests a world's doors come from: the one its project.json names, else assets.json files
   near the world (see _nearby()).
   @param project  Project
   @return paths
   """
   named = _game_file(project.world.path, "assets")
   return [named] if named is not None and named.is_file() else _nearby(project.world.path, ASSETS_FILE)


def worlds_near(doc: Document) -> list[Path]:
   """!Worlds an asset manifest's doors may be previewed on: the one the game's project.json names, else world.json
   files near the manifest.
   @param doc  asset manifest Document
   @return paths
   """
   if doc.path is None:
      return []
   named = _game_file(doc.path, "maps")
   return [named] if named is not None and named.is_file() else _nearby(doc.path, WORLD_FILE)


def door_keys(project: Project) -> list[str]:
   """!Door keys a world may bind: the door assets of its game's asset manifests and the keys its bindings name.
   @param project  Project
   @return keys, sorted
   """
   from .manifest_io import load
   keys = {b.get("door") for b in bindings(project.world) if isinstance(b.get("door"), str)}
   for path in asset_manifests(project):
      try:
         m = load(path)
      except (OSError, ValueError):
         continue
      keys |= {a.get("key") for a in m.get("assets", []) if isinstance(a, dict) and a.get("kind") == KIND}
   return sorted(k for k in keys if isinstance(k, str))


def lines(doc: Document, key: str | None = None) -> list[str]:
   """!Doors as text (`door list` / `door show`).
   @param doc  asset manifest Document
   @param key  one door, or None for all (one line each)
   @return lines
   """
   out = []
   known = sound_keys(doc) if any(a.get("sounds") for a in doors(doc)) else None   # S4: read once for all doors
   for a in doors(doc):
      if key is not None and a.get("key") != key:
         continue
      w, h = cells_of(a)
      r = doc.compile_asset(a)
      state = f"{r.compiled['frames']} frames" if r.ok else f"error: {r.error}"
      out.append(f"{a.get('key')}: {w}x{h} cells, {show_of(a)}, {layers_of(a)} layer(s), {state}")
      out += [f"  {p}" for p in sound_problems(doc, a, known)]   # S4
      if key is None:
         continue
      for which in ("open", "close"):
         how = " (open reversed)" if which == "close" and is_reverse(a) else ""
         out.append(f"  {which}{how}: " + ", ".join(f"{f} x{t}" for f, t in steps(a, which)))
      sounds = a.get("sounds", {})
      out.append(f"  sounds: open {sounds.get('open', '-')}, close {sounds.get('close', '-')}; exit "
                 f"{a.get('exit', directions()[0])}")
      if show_of(a) == shows()[0]:
         out.append(f"  sheet {a.get('sheet', {}).get('image', 'shapes')}, {a.get('frame_tiles')} tiles a frame, "
                    f"loaded at {a.get('load_at', load_end_word())}")
         frames = [None]
      else:
         frames = list(range(len(a.get("frames", []))))
      for f in frames:
         for c in range(w * h):
            for k in range(layers_of(a)):
               label = f"frame {f} " if f is not None else ""
               out.append(f"  {label}cell {c} layer {k}: " +
                          " ".join(entry_text(entry(a, c, k, s, f or 0)) for s in range(len(SLOTS))))
   return out


# -- S4: door sounds --------------------------------------------------------------------------------------------------

def scripts_manifest_near(doc: Document) -> Path | None:
   """!S4: the game's scripts manifest for an asset manifest: the one its project.json names, else the "scripts" of
   the first world near the manifest (worlds_near()).
   @param doc  asset manifest Document
   @return the path, or None
   """
   if doc.path is None:
      return None
   named = _game_file(doc.path, "scripts")
   if named is not None and named.is_file():
      return named
   for world in worlds_near(doc):
      try:
         rel = json.loads(world.read_text(encoding="utf-8")).get("scripts")
      except (OSError, ValueError, AttributeError):
         continue
      if isinstance(rel, str) and (world.parent / rel).is_file():
         return (world.parent / rel).resolve()
   return None


def _source_constants(path: Path) -> list[str]:
   """!The constants a .cscript source declares (scanned once per file version).
   @param path  the source
   @return names
   """
   try:
      key = (str(path), path.stat().st_mtime_ns)
   except OSError:
      return []
   if key not in _CONSTANTS_CACHE:
      try:
         text = path.read_text(encoding="utf-8")
      except (OSError, UnicodeDecodeError):
         text = ""
      _CONSTANTS_CACHE[key] = [m.group("name") for m in CONST_DECLARATION.finditer(text)]
   return _CONSTANTS_CACHE[key]


def sound_keys(doc: Document) -> tuple[set[str], list[str]]:
   """!S4: the sound keys a game has: its sound assets (keys "sound:NAME" of the manifest) and the
   constants of its scripts manifest's sources as "sound:NAME".
   @param doc  asset manifest Document
   @return (keys, where they were looked for: the files read)
   """
   keys = {str(a.get("key")) for a in doc.assets() if str(a.get("key", "")).startswith(SOUND_PREFIX)}
   where = [str(doc.path)] if doc.path is not None else []
   manifest = scripts_manifest_near(doc)
   if manifest is not None:
      where.append(str(manifest))
      try:
         sources = json.loads(manifest.read_text(encoding="utf-8")).get("sources", [])
      except (OSError, ValueError, AttributeError):
         sources = []
      for rel in sources if isinstance(sources, list) else []:
         keys |= {SOUND_PREFIX + n for n in _source_constants(manifest.parent / str(rel))}
   return keys, where


def sound_problems(doc: Document, asset: JsonDict, known: tuple[set[str], list[str]] | None = None) -> list[str]:
   """!S4: a door's sounds that name no sound of the game (the engine does not check them).
   @param doc    asset manifest Document
   @param asset  the door asset
   @param known  sound_keys()'s result (a caller checking many doors), or None
   @return problems ("warning: ..."), [] when every sound is known
   """
   sounds = asset.get("sounds")
   if not isinstance(sounds, dict) or not sounds:
      return []
   keys, where = known if known is not None else sound_keys(doc)
   out = []
   for which in sorted(sounds):
      name = sounds[which]
      if not isinstance(name, str) or not name.startswith(SOUND_PREFIX):
         out.append(f"warning: {asset.get('key')} {which} sound {name!r} is no sound key ({SOUND_PREFIX}NAME)")
      elif name not in keys:
         looked = "a sound asset or a scripts constant" if len(where) > 1 else \
            "a sound asset (no scripts manifest found near the manifest)"
         out.append(f"warning: {asset.get('key')} {which} sound {name}: the game has no such sound ({looked})")
   return out
