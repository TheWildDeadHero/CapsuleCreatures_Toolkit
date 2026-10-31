"""!Map editing: tile layers, the attribute layer, flood fill, the metatile
and behavior dictionaries, the map's tilesets and the border.

A map manifest (capsule.map/2, C-01b) has up to four tile layers, each on
its own GBA background (BG0-BG3) with its own draw priority, and stores
sparse 8x8-metatile chunks. Each chunk holds:
  - "cells": the attribute layer, one cell per metatile: None (unpainted:
    the border shows and it is impassable) or behavior | env << 8 |
    collision << 16 | elevation << 18 | encounter << 22 | slot << 23,
    where behavior indexes the map's behavior dictionary ("behaviors",
    world behavior names) and slot (0-15) picks which of the map's
    encounter tables the cell uses (see core.encounters);
  - "layers": per tile layer, 8 rows of 8 metatile dictionary indices, or
    None where that layer shows nothing.

Metatiles are graphics only (one layer of 2x2 tiles); collision, elevation,
behavior, encounter, encounter slot and env are painted on the attribute
layer. Painting a
tile on an unpainted cell makes the cell painted with default attributes
(behavior 0, everything else 0). Painting outside every chunk creates the
chunk.

A map lists the tilesets it draws from ("tilesets"); editors offer every
metatile of those. The metatile dictionary ("metatiles") is bookkeeping: a
metatile joins it when first painted (dictionary_index()) and leaves it
when nothing uses it any more (compact_dictionary()). I2: a dictionary may
instead be "all" (ALL_METATILES): every metatile of the map's tilesets, in
their order, tileset by tileset (imported maps index their tilesets' metatile
ids directly). Its entries are positions, so the functions that resolve a
dictionary take the map's tilesets' metatile names (dictionary()); changing
the tilesets or their metatile order renumbers its cells (set_tilesets(),
follow_metatile_order()). The border has one
w x h pattern per tile layer; a border entry may be None (that layer shows
nothing there).

Tile layers are addressed by their position in "layers" (the layer index),
which is also the position of their grid in each chunk's "layers".

Functions that change a Document must be called inside doc.edit().
"""
from __future__ import annotations

import functools
from collections.abc import Callable, Collection, Iterable, Sequence
from types import ModuleType
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
   from .document import Document
   from .manifest_io import JsonDict

## A metatile cell of the map: (column, row).
Cell = tuple[int, int]
## A chunk's grid for one tile layer: CHUNK rows of CHUNK dictionary indices (None: nothing there).
Grid = list[list[int | None]]
## An unpacked attribute cell: field name -> value (see cell_fields(); "encounter" is a bool).
CellFields = dict[str, int | bool]
## A tileset's metatile names in order, by tileset name (resolves an "all" dictionary).
MetatilesOf = Callable[[str], Sequence[str]]
## The entry type of a stamp pattern (dictionary indices on the map, metatile names on the border).
EntryT = TypeVar("EntryT")

## Metatiles per chunk side.
CHUNK = 8
## Shift from a metatile coordinate to its chunk's (CHUNK is 1 << CHUNK_SHIFT).
CHUNK_SHIFT = 3
## Mask of a metatile coordinate's position inside its chunk.
CHUNK_MASK = CHUNK - 1
## Entries of a border's "size": [w, h].
SIZE_ENTRIES = 2
## Layer purposes the compiler accepts (C-01b; for tools, not drawn differently).
PURPOSES = ("terrain", "geometry", "canopy", "infrastructure", "backdrop", "environment_effect", "unused")
## Tile layers of a new map: (bg, priority, purpose), back to front. BG0 stays free for text windows.
DEFAULT_LAYERS = ((3, 3, "terrain"), (2, 2, "terrain"), (1, 1, "canopy"))
## Most cells one flood fill changes.
FILL_LIMIT = 65536
## I2: the "metatiles" value of a map whose dictionary is every metatile of its tilesets (map_compiler: names ==
## "all"; a manifest word, as the key names are).
ALL_METATILES = "all"


# -- the engine's limits (map_compiler; S17 / X1: no copies here) ----------------------------------------------------

def _mc() -> ModuleType:
   """!The engine's map compiler (imported on first use: importing this module needs no engine).
   @return map_compiler
   """
   from . import engine   # local: importing this module needs no engine
   return engine.tool("map_compiler")


def max_priority() -> int:
   """!The largest (backmost) draw priority of a tile layer; 0 is the front (the engine's map_compiler.MAX_PRIORITY,
   the GBA's BG priorities 0-3; S17: no copy here).
   @return the priority
   """
   return int(_mc().MAX_PRIORITY)


def max_layers() -> int:
   """!Tile layers a map may have, one per GBA background (the engine's map_compiler.MAX_LAYERS).
   @return the count
   """
   return int(_mc().MAX_LAYERS)


def max_metatiles() -> int:
   """!Entries a map's metatile dictionary may hold (the engine's map_compiler.MAX_METATILES).
   @return the count
   """
   return int(_mc().MAX_METATILES)


def max_tiles() -> int:
   """!4bpp tiles a map's VRAM holds (the engine's map_compiler.MAX_TILES).
   @return the count
   """
   return int(_mc().MAX_TILES)


def max_palettes() -> int:
   """!Background palette banks a map may use (the engine's map_compiler.MAX_PALETTES).
   @return the count
   """
   return int(_mc().MAX_PALETTES)


def max_animations() -> int:
   """!Tile animations a map may run (the engine's map_compiler.MAX_ANIMATIONS; I2: 32).
   @return the count
   """
   return int(_mc().MAX_ANIMATIONS)


def max_behaviors() -> int:
   """!Entries a map's behavior dictionary may hold (the engine's map_compiler.MAX_BEHAVIORS).
   @return the count
   """
   return int(_mc().MAX_BEHAVIORS)


def max_border() -> int:
   """!Largest border side, in metatiles (the engine's map_compiler.MAX_BORDER_SIZE).
   @return the side
   """
   return int(_mc().MAX_BORDER_SIZE)


@functools.cache
def _cell_fields() -> tuple[tuple[str, int, int], ...]:
   """!The engine's attribute cell fields, read once (make_cell() and unpack() run per cell).
   @return (name, mask after shifting, shift) per field, in the engine's order
   """
   return tuple((name, int(mask), int(shift)) for name, (mask, shift) in _mc().CELL_FIELDS.items())


def cell_fields() -> dict[str, tuple[int, int]]:
   """!Attribute cell fields: name -> (mask after shifting, shift) (the engine's map_compiler.CELL_FIELDS).
   @return a copy, in the engine's order
   """
   return {name: (mask, shift) for name, mask, shift in _cell_fields()}


def behavior_mask() -> int:
   """!Mask of an attribute cell's behavior (dictionary index); it is in the lowest bits (the engine's
   map_compiler.BEHAVIOR_MASK).
   @return the mask
   """
   return int(_mc().BEHAVIOR_MASK)


# -- attribute cells --------------------------------------------------------------------


def make_cell(behavior: int = 0, env: int = 0, collision: int = 0, elevation: int = 0, encounter: bool = False,
              slot: int = 0) -> int:
   """!Packs an attribute cell.
   @param behavior   index into the map's behavior dictionary, 0-255
   @param env        environment tag, 0-255
   @param collision  0-3 (0 passable)
   @param elevation  0-15
   @param encounter  wild-encounter cell
   @param slot       encounter slot, 0-15 (which of the map's encounter tables the cell uses)
   @return the cell value
   """
   values = {"behavior": behavior, "env": env, "collision": collision, "elevation": elevation,
             "encounter": int(bool(encounter)), "slot": slot}
   cell = 0
   for name, mask, shift in _cell_fields():
      v = values[name]
      # A whole number that fits the field; bools only for the encounter flag.
      if not isinstance(v, int) or (isinstance(v, bool) and name != "encounter") or not 0 <= v <= mask:
         raise ValueError(f"{name} is 0-{mask}")
      cell |= v << shift
   return cell


def unpack(cell: int | None) -> CellFields | None:
   """!Splits an attribute cell.
   @param cell  cell value or None
   @return {"behavior", "env", "collision", "elevation", "encounter" (bool), "slot"}, or None when unpainted
   """
   if cell is None:
      return None
   out = {name: (cell >> shift) & mask for name, mask, shift in _cell_fields()}
   out["encounter"] = bool(out["encounter"])
   return out


def with_fields(cell: int, **fields: int | bool | None) -> int:
   """!An attribute cell with some fields changed.
   @param cell    cell value (not None)
   @param fields  behavior, env, collision, elevation, encounter, slot; None keeps a field
   @return the new cell value
   """
   a = unpack(cell)
   for k, v in fields.items():
      if k not in cell_fields():
         raise ValueError(f"no attribute {k!r}")
      if v is not None:
         a[k] = v
   return make_cell(**a)


# -- layers -------------------------------------------------------------------------------

def layers_of(data: JsonDict) -> list[JsonDict]:
   """!A map's tile layers.
   @param data  map manifest
   @return list of {"bg", "priority", "content", "purpose"} (the manifest's own objects)
   """
   out = data.get("layers")
   return out if isinstance(out, list) else []


def layer_priority(layer: JsonDict) -> int:
   """!A layer's draw priority (0 = front), with the compiler's default.
   @param layer  layer object
   @return 0-3
   """
   return layer.get("priority", layer.get("bg", 0))


def draw_order(data: JsonDict) -> list[int]:
   """!Layer indices back to front, the way the GBA stacks them: higher
   priority numbers behind, and on equal priority the higher BG behind.
   @param data  map manifest
   @return list of layer indices
   """
   ls = layers_of(data)
   return sorted(range(len(ls)), key=lambda i: (-layer_priority(ls[i]), -ls[i].get("bg", 0)))


def free_bgs(data: JsonDict) -> list[int]:
   """!Backgrounds no tile layer uses yet.
   @param data  map manifest
   @return list of BG numbers
   """
   used = {ly.get("bg") for ly in layers_of(data)}
   return [bg for bg in range(max_layers()) if bg not in used]


def add_layer(doc: Document, bg: int, priority: int | None = None, purpose: str = "terrain") -> int:
   """!Adds an empty tile layer.
   @param doc       map Document
   @param bg        background 0-3 (unused by the map's other layers)
   @param priority  draw priority 0-3 (0 = front), default the BG number
   @param purpose   one of PURPOSES
   @return the new layer's index
   """
   if bg not in free_bgs(doc.data):
      raise ValueError(f"BG{bg} already holds a layer" if 0 <= bg < max_layers() else "backgrounds are BG0-BG3")
   priority = bg if priority is None else priority
   if not 0 <= priority <= max_priority():
      raise ValueError(f"priority is 0-{max_priority()}")
   if purpose not in PURPOSES:
      raise ValueError(f"purpose is one of {', '.join(PURPOSES)}")
   w, h, pats = border_of(doc.data)
   ls = doc.data.setdefault("layers", [])
   ls.append({"bg": bg, "priority": priority, "content": "tilemap", "purpose": purpose})
   for c in doc.data.get("chunks", []):
      _grid(c, len(ls) - 1, len(ls))
   pats.append([None] * (w * h))
   _store_border(doc.data, w, h, pats)
   return len(ls) - 1


def remove_layer(doc: Document, layer: int) -> None:
   """!Removes a tile layer and everything painted on it.
   @param doc    map Document
   @param layer  layer index
   @return None
   """
   ls = layers_of(doc.data)
   if not 0 <= layer < len(ls):
      raise ValueError(f"no layer {layer}")
   w, h, pats = border_of(doc.data)
   del ls[layer]
   for c in doc.data.get("chunks", []):
      grids = c.get("layers", [])
      if layer < len(grids):
         del grids[layer]
   del pats[layer]
   _store_border(doc.data, w, h, pats)
   compact_dictionary(doc)


def set_layer(doc: Document, layer: int, bg: int | None = None, priority: int | None = None,
              purpose: str | None = None) -> None:
   """!Changes a tile layer's background, priority or purpose (None keeps one).
   @param doc       map Document
   @param layer     layer index
   @param bg        new background 0-3 (unused by the other layers)
   @param priority  0-3
   @param purpose   one of PURPOSES
   @return None
   """
   ls = layers_of(doc.data)
   if not 0 <= layer < len(ls):
      raise ValueError(f"no layer {layer}")
   ly = ls[layer]
   if bg is not None and bg != ly.get("bg"):
      if bg not in free_bgs(doc.data):
         raise ValueError(f"BG{bg} already holds a layer" if 0 <= bg < max_layers() else "backgrounds are BG0-BG3")
      ly["bg"] = bg
   if priority is not None:
      if not 0 <= priority <= max_priority():
         raise ValueError(f"priority is 0-{max_priority()}")
      ly["priority"] = priority
   if purpose is not None:
      if purpose not in PURPOSES:
         raise ValueError(f"purpose is one of {', '.join(PURPOSES)}")
      ly["purpose"] = purpose


def layer_label(data: JsonDict, layer: int) -> str:
   """!A short name for a layer, like "BG2 terrain (priority 2)".
   @param data   map manifest
   @param layer  layer index
   @return text
   """
   ly = layers_of(data)[layer]
   return f"BG{ly.get('bg', 0)} {ly.get('purpose', 'terrain')} (priority {layer_priority(ly)})"


# -- chunks and cells -------------------------------------------------------------------------

def _chunks(data: JsonDict) -> dict[tuple[int, ...], JsonDict]:
   """!Chunks by position.
   @param data  map manifest
   @return {(cx, cy): chunk object}
   """
   return {tuple(c["at"]): c for c in data.get("chunks", [])}


def _new_chunk(data: JsonDict, key: Cell) -> JsonDict:
   """!Adds an empty chunk (kept sorted by row, then column).
   @param data  map manifest
   @param key   (cx, cy)
   @return the chunk object
   """
   c = {"at": [key[0], key[1]], "cells": [[None] * CHUNK for _ in range(CHUNK)],
        "layers": [[[None] * CHUNK for _ in range(CHUNK)] for _ in layers_of(data)]}
   data.setdefault("chunks", []).append(c)
   data["chunks"].sort(key=lambda k: (k["at"][1], k["at"][0]))
   return c


def _grid(chunk: JsonDict, layer: int, count: int) -> Grid:
   """!A chunk's grid for a tile layer, created when missing.
   @param chunk  chunk object
   @param layer  layer index
   @param count  the map's layer count
   @return 8 rows of 8 entries
   """
   grids = chunk.setdefault("layers", [])
   while len(grids) < count:
      grids.append([[None] * CHUNK for _ in range(CHUNK)])
   return grids[layer]


def get(data: JsonDict, x: int, y: int) -> int | None:
   """!An attribute cell.
   @param data  map manifest
   @param x     metatile column
   @param y     metatile row
   @return the cell value, or None (unpainted or no chunk)
   """
   # The high bits of a coordinate pick the chunk, the low bits the cell inside it.
   c = _chunks(data).get((x >> CHUNK_SHIFT, y >> CHUNK_SHIFT))
   return None if c is None else c["cells"][y & CHUNK_MASK][x & CHUNK_MASK]


def get_tile(data: JsonDict, layer: int, x: int, y: int) -> int | None:
   """!The dictionary index painted on a tile layer.
   @param data   map manifest
   @param layer  layer index
   @param x      metatile column
   @param y      metatile row
   @return dictionary index, or None (nothing there, or no chunk)
   """
   c = _chunks(data).get((x >> CHUNK_SHIFT, y >> CHUNK_SHIFT))
   if c is None:
      return None
   grids = c.get("layers") or []
   return grids[layer][y & CHUNK_MASK][x & CHUNK_MASK] if layer < len(grids) else None


def has_chunk(data: JsonDict, x: int, y: int) -> bool:
   """!Whether a chunk covers a cell.
   @param data  map manifest
   @param x     metatile column
   @param y     metatile row
   @return True or False
   """
   return (x >> CHUNK_SHIFT, y >> CHUNK_SHIFT) in _chunks(data)


def put(data: JsonDict, x: int, y: int, value: int | None) -> None:
   """!Sets an attribute cell, creating its chunk when needed (value None in
   a missing chunk does nothing). Setting None also clears the cell's tiles
   on every layer: an unpainted cell shows the border.
   @param data   map manifest
   @param x      metatile column
   @param y      metatile row
   @param value  cell value or None
   @return None
   """
   key = (x >> CHUNK_SHIFT, y >> CHUNK_SHIFT)
   c = _chunks(data).get(key)
   if c is None:
      if value is None:
         return
      c = _new_chunk(data, key)
   c["cells"][y & CHUNK_MASK][x & CHUNK_MASK] = value
   if value is None:
      for g in c.get("layers") or []:
         g[y & CHUNK_MASK][x & CHUNK_MASK] = None


def put_tile(data: JsonDict, layer: int, x: int, y: int, index: int | None) -> None:
   """!Sets a tile layer entry, creating the chunk when needed. A tile on an
   unpainted cell paints the cell with default attributes.
   @param data   map manifest
   @param layer  layer index
   @param x      metatile column
   @param y      metatile row
   @param index  dictionary index, or None for nothing on this layer
   @return None
   """
   count = len(layers_of(data))
   if not 0 <= layer < count:
      raise ValueError(f"the map has no layer {layer}")
   key = (x >> CHUNK_SHIFT, y >> CHUNK_SHIFT)
   c = _chunks(data).get(key)
   if c is None:
      if index is None:
         return
      c = _new_chunk(data, key)
   if index is not None and c["cells"][y & CHUNK_MASK][x & CHUNK_MASK] is None:
      c["cells"][y & CHUNK_MASK][x & CHUNK_MASK] = make_cell()
   _grid(c, layer, count)[y & CHUNK_MASK][x & CHUNK_MASK] = index


def is_painted(data: JsonDict, x: int, y: int) -> bool:
   """!Whether a cell is painted (has attributes; the border shows otherwise).
   @param data  map manifest
   @param x     metatile column
   @param y     metatile row
   @return True or False
   """
   return get(data, x, y) is not None


# -- dictionaries -----------------------------------------------------------------------------

def tilesets_of(data: JsonDict, world_tilesets: Sequence[str] | None = None) -> list[str]:
   """!The tilesets a map draws from: its "tilesets" list, or (maps without
   one) the tilesets its dictionary uses.
   @param data            map manifest
   @param world_tilesets  the world's tileset names in order (orders the fallback), or None
   @return list of names
   """
   listed = data.get("tilesets")
   if isinstance(listed, list):
      return [t for t in listed if isinstance(t, str)]
   used = []
   for n in _listed_names(data):
      t = n.split("/", 1)[0] if isinstance(n, str) else None
      if t and t not in used:
         used.append(t)
   if world_tilesets:
      # In the world's order; tilesets the world does not have go last.
      used.sort(key=lambda t: world_tilesets.index(t) if t in world_tilesets else len(world_tilesets))
   return used


def set_tilesets(doc: Document, names: Iterable[str], world_tilesets: Collection[str],
                 metatiles_of: MetatilesOf | None = None) -> None:
   """!Sets the tilesets a map draws from. Refused while metatiles of a
   tileset left out are still painted (or in the border). I2: an "all"
   dictionary is every metatile of the new tilesets, so the cells are
   renumbered to keep showing the same metatiles.
   @param doc             map Document
   @param names           tileset names
   @param world_tilesets  the world's tileset names
   @param metatiles_of    a tileset's metatile names (needed for an "all" dictionary), or None
   @return None
   """
   names = list(dict.fromkeys(names))
   unknown = [t for t in names if t not in world_tilesets]
   if unknown:
      raise ValueError(f"the world has no tileset {unknown[0]!r}")
   if uses_all(doc.data):
      if metatiles_of is None:
         raise ValueError("an \"all\" dictionary needs the tilesets' metatiles to renumber its cells")
      old = dictionary(doc.data, metatiles_of)
      new = [f"{t}/{m}" for t in names for m in metatiles_of(t)]
      _renumber(doc, old, new)
      doc.data["tilesets"] = names
      return
   compact_dictionary(doc)
   in_use = sorted({n.split("/", 1)[0] for n in _listed_names(doc.data)} - set(names))
   if in_use:
      raise ValueError(f"metatiles of {', '.join(in_use)} are still painted on this map; erase them first")
   doc.data["tilesets"] = names


def uses_all(data: JsonDict) -> bool:
   """!Whether a map's dictionary is "all" (I2: every metatile of its tilesets).
   @param data  map manifest
   @return True or False
   """
   return data.get("metatiles") == ALL_METATILES


def _listed_names(data: JsonDict) -> list[str]:
   """!The names a map's dictionary lists itself ([] for an "all" dictionary, which lists none).
   @param data  map manifest
   @return list of "tileset/metatile"
   """
   names = data.get("metatiles", [])
   return [n for n in names if isinstance(n, str)] if isinstance(names, list) else []


def dictionary(data: JsonDict, metatiles_of: MetatilesOf | None = None) -> list[str]:
   """!A map's dictionary, resolved: its list, or for "all" every metatile of its tilesets in order (as the
   engine's map_compiler.compile_map() resolves it).
   @param data          map manifest
   @param metatiles_of  a tileset's metatile names in order (needed for "all"; unknown tilesets give none), or None
   @return list of "tileset/metatile" (an "all" dictionary without metatiles_of resolves to [])
   """
   if not uses_all(data):
      return _listed_names(data)
   if metatiles_of is None:
      return []
   return [f"{t}/{m}" for t in tilesets_of(data) for m in metatiles_of(t)]


def _renumber(doc: Document, old: Sequence[str], new: Sequence[str]) -> None:
   """!Renumbers a map's layer cells and border from one dictionary to another, by name (an "all" dictionary
   whose tilesets or their metatiles changed). Refused when a painted metatile is not in the new one.
   @param doc  map Document
   @param old  the dictionary the cells index now
   @param new  the dictionary they index after
   @return None
   """
   if len(new) > max_metatiles():
      raise ValueError(f"the map's tilesets offer {len(new)} metatiles; a dictionary holds {max_metatiles()}")
   at = {n: i for i, n in enumerate(new)}

   def remap(v: int | None) -> int | None:
      """!One cell's new index (None stays None)."""
      if v is None:
         return None
      name = old[v] if 0 <= v < len(old) else None
      if name not in at:
         raise ValueError(f"metatile {name or v!r} is painted on this map but leaves its dictionary; erase it first")
      return at[name]
   if list(old) == list(new):
      return
   for c in doc.data.get("chunks", []):
      c["layers"] = [[[remap(v) for v in r] for r in g] if g is not None else None for g in c.get("layers") or []]
   b = doc.data.get("border")
   if b and "layers" in b:
      b["layers"] = [[remap(v) for v in pat] for pat in b["layers"]]


def set_all(doc: Document, metatiles_of: MetatilesOf) -> None:
   """!Makes a map's dictionary "all" (I2), renumbering its cells. The map needs a "tilesets" list holding every
   tileset it paints from.
   @param doc           map Document
   @param metatiles_of  a tileset's metatile names in order
   @return None
   """
   if uses_all(doc.data):
      return
   if not isinstance(doc.data.get("tilesets"), list):
      raise ValueError("an \"all\" dictionary needs the map's tilesets (choose them first)")
   old = _listed_names(doc.data)
   new = [f"{t}/{m}" for t in tilesets_of(doc.data) for m in metatiles_of(t)]
   _renumber(doc, old, new)
   doc.data["metatiles"] = ALL_METATILES


def set_listed(doc: Document, metatiles_of: MetatilesOf) -> None:
   """!Makes an "all" dictionary a list of the metatiles the map paints (I2: the studio's usual dictionary),
   renumbering its cells.
   @param doc           map Document
   @param metatiles_of  a tileset's metatile names in order
   @return None
   """
   if not uses_all(doc.data):
      return
   doc.data["metatiles"] = dictionary(doc.data, metatiles_of)
   compact_dictionary(doc)


def follow_metatile_order(doc: Document, tileset: str, before: Sequence[str], after: Sequence[str],
                          metatiles_of: MetatilesOf) -> bool:
   """!Keeps an "all" map showing the same metatiles after a tileset's metatiles were added, removed or reordered
   (its cells are positions in its tilesets' metatiles). Refused when a removed metatile is painted.
   @param doc           map Document
   @param tileset       the tileset that changed
   @param before        its metatile names before
   @param after         its metatile names now
   @param metatiles_of  a tileset's metatile names in order (now)
   @return True when the map's cells were renumbered
   """
   if not uses_all(doc.data) or tileset not in tilesets_of(doc.data) or list(before) == list(after):
      return False
   uses = tilesets_of(doc.data)
   old = [f"{t}/{m}" for t in uses for m in (before if t == tileset else metatiles_of(t))]
   new = [f"{t}/{m}" for t in uses for m in metatiles_of(t)]
   _renumber(doc, old, new)
   return True


def dictionary_index(doc: Document, name: str, metatiles_of: MetatilesOf | None = None) -> int:
   """!The dictionary index of a metatile, added when missing. A map with a
   "tilesets" list takes only metatiles of those tilesets. I2: an "all"
   dictionary already holds every metatile of the map's tilesets.
   @param doc           map Document
   @param name          "tileset/metatile"
   @param metatiles_of  a tileset's metatile names (needed for an "all" dictionary), or None
   @return index
   """
   listed = doc.data.get("tilesets")
   if isinstance(listed, list) and name.split("/", 1)[0] not in listed:
      raise ValueError(f"{name!r} is not from one of this map's tilesets ({', '.join(listed) or 'none'})")
   if uses_all(doc.data):
      names = dictionary(doc.data, metatiles_of)
      if name not in names:
         raise ValueError(f"{name!r} is not a metatile of this map's tilesets")
      return names.index(name)
   names = doc.data.setdefault("metatiles", [])
   if name not in names:
      if len(names) >= max_metatiles():
         raise ValueError(f"the map's metatile dictionary is full ({max_metatiles()} entries)")
      names.append(name)
   return names.index(name)


def behaviors_of(data: JsonDict, world_behaviors: Sequence[str] | None = None) -> list[str]:
   """!The map's behavior dictionary (attribute cells index it).
   @param data             map manifest
   @param world_behaviors  the world's behavior names (the default dictionary is its first), or None
   @return list of world behavior names
   """
   b = data.get("behaviors")
   if isinstance(b, list) and b:
      return list(b)
   return [(world_behaviors or ["normal"])[0]]


def behavior_index(doc: Document, name: str, world_behaviors: Sequence[str] | None = None) -> int:
   """!The behavior dictionary index of a world behavior, added when missing.
   @param doc              map Document
   @param name             world behavior name
   @param world_behaviors  the world's behavior names (checked when given), or None
   @return index
   """
   if world_behaviors is not None and name not in world_behaviors:
      raise ValueError(f"the world has no behavior {name!r}")
   names = behaviors_of(doc.data, world_behaviors)
   if name not in names:
      if len(names) >= max_behaviors():
         raise ValueError(f"the map's behavior dictionary is full ({max_behaviors()} entries)")
      names.append(name)
   doc.data["behaviors"] = names
   return names.index(name)


def behavior_name(data: JsonDict, cell: int, world_behaviors: Sequence[str] | None = None) -> str:
   """!The world behavior name of a painted cell.
   @param data             map manifest
   @param cell             attribute cell (not None)
   @param world_behaviors  the world's behavior names, or None
   @return name, or "?" past the dictionary
   """
   names = behaviors_of(data, world_behaviors)
   i = cell & behavior_mask()
   return names[i] if i < len(names) else "?"


def compact_dictionary(doc: Document) -> int:
   """!Drops metatile dictionary entries no layer or border uses, renumbering.
   @param doc  map Document
   @return entries dropped (0 for an "all" dictionary, which always holds its tilesets' metatiles)
   """
   if uses_all(doc.data):
      return 0
   names = doc.data.get("metatiles", [])
   used = set()
   for pat in (doc.data.get("border") or {}).get("layers", []):
      used.update(v for v in pat or [] if v is not None)
   for c in doc.data.get("chunks", []):
      for g in c.get("layers") or []:
         used.update(v for r in g or [] for v in r if v is not None)
   keep = [i for i in range(len(names)) if i in used]
   if len(keep) == len(names):
      return 0
   remap = {old: new for new, old in enumerate(keep)}
   doc.data["metatiles"] = [names[i] for i in keep]
   for c in doc.data.get("chunks", []):
      c["layers"] = [None if g is None else [[None if v is None else remap[v] for v in r] for r in g]
                     for g in c.get("layers") or []]
   b = doc.data.get("border")
   if b and "layers" in b:
      b["layers"] = [[None if v is None else remap[v] for v in pat] for pat in b["layers"]]
   return len(names) - len(keep)


def compact_behaviors(doc: Document) -> int:
   """!Drops behavior dictionary entries no cell uses (entry 0, the default
   for new cells, always stays), renumbering cells.
   @param doc  map Document
   @return entries dropped
   """
   names = doc.data.get("behaviors")
   if not isinstance(names, list) or len(names) <= 1:
      return 0
   used = {0}
   mask = behavior_mask()
   for c in doc.data.get("chunks", []):
      used.update(v & mask for r in c["cells"] for v in r if v is not None)
   keep = [i for i in range(len(names)) if i in used]
   if len(keep) == len(names):
      return 0
   remap = {old: new for new, old in enumerate(keep)}
   doc.data["behaviors"] = [names[i] for i in keep]
   for c in doc.data.get("chunks", []):
      # Swaps each painted cell's behavior index for its new one, keeping the other fields.
      c["cells"] = [[None if v is None else (v & ~mask) | remap[v & mask] for v in r]
                    for r in c["cells"]]
   return len(names) - len(keep)


def rename_metatile_refs(doc: Document, old: str, new: str) -> bool:
   """!Renames a metatile in a map's dictionary (after a tileset rename).
   @param doc  map Document
   @param old  "tileset/old"
   @param new  "tileset/new"
   @return True if the map used it (an "all" dictionary names no metatile: its cells are positions)
   """
   names = _listed_names(doc.data)
   if uses_all(doc.data) or old not in names:
      return False
   listed = doc.data["metatiles"]
   listed[listed.index(old)] = new
   return True


# -- painting -----------------------------------------------------------------------------------

def paint(doc: Document, layer: int, x: int, y: int, index: int | None) -> None:
   """!Paints a metatile on a tile layer (the cell's attributes stay; an
   unpainted cell gets the default ones).
   @param doc    map Document
   @param layer  layer index
   @param x      metatile column
   @param y      metatile row
   @param index  dictionary index, or None to clear this layer there
   @return None
   """
   put_tile(doc.data, layer, x, y, index)


def set_attributes(doc: Document, x: int, y: int, **fields: int | bool | None) -> bool:
   """!Changes attributes of a painted cell (unpainted cells are always blocked).
   @param doc     map Document
   @param x       metatile column
   @param y       metatile row
   @param fields  behavior (dictionary index), env, collision, elevation, encounter, slot; None keeps one
   @return True if the cell was painted
   """
   old = get(doc.data, x, y)
   if old is None:
      return False
   put(doc.data, x, y, with_fields(old, **fields))
   return True


def erase(doc: Document, x: int, y: int) -> None:
   """!Unpaints a cell: its attributes and every layer's tile go (the border shows there).
   @param doc  map Document
   @param x    metatile column
   @param y    metatile row
   @return None
   """
   put(doc.data, x, y, None)


def rect_cells(x0: int, y0: int, x1: int, y1: int) -> list[Cell]:
   """!The cells of a rectangle (corners included, any order), rows first.
   @param x0  corner column
   @param y0  corner row
   @param x1  other corner column
   @param y1  other corner row
   @return list of (x, y)
   """
   return [(x, y) for y in range(min(y0, y1), max(y0, y1) + 1) for x in range(min(x0, x1), max(x0, x1) + 1)]


def rect(doc: Document, layer: int, x0: int, y0: int, x1: int, y1: int, index: int | None) -> int:
   """!Paints a rectangle on a tile layer.
   @param doc    map Document
   @param layer  layer index
   @param x0     corner column
   @param y0     corner row
   @param x1     other corner column
   @param y1     other corner row
   @param index  dictionary index, or None to clear
   @return cells painted
   """
   cells = rect_cells(x0, y0, x1, y1)
   for x, y in cells:
      paint(doc, layer, x, y, index)
   return len(cells)


def rect_attributes(doc: Document, x0: int, y0: int, x1: int, y1: int, **fields: int | bool | None) -> int:
   """!Changes attributes of the painted cells of a rectangle.
   @param doc     map Document
   @param x0      corner column
   @param y0      corner row
   @param x1      other corner column
   @param y1      other corner row
   @param fields  see set_attributes()
   @return cells changed
   """
   return sum(set_attributes(doc, x, y, **fields) for x, y in rect_cells(x0, y0, x1, y1))


def _flood(doc: Document, x: int, y: int, key: Callable[[JsonDict, int, int], object],
           change: Callable[[JsonDict, int, int], None]) -> int:
   """!Flood fill core: visits the 4-connected cells inside chunks whose key
   equals the start's.
   @param doc     map Document
   @param x       start column
   @param y       start row
   @param key     callable(chunk, x, y) -> comparable value
   @param change  callable(chunk, x, y) changing one cell
   @return cells changed
   """
   chunks = _chunks(doc.data)
   start = chunks.get((x >> CHUNK_SHIFT, y >> CHUNK_SHIFT))
   if start is None:
      return 0
   target = key(start, x, y)
   seen, todo, n = {(x, y)}, [(x, y)], 0
   while todo:
      cx, cy = todo.pop()
      c = chunks.get((cx >> CHUNK_SHIFT, cy >> CHUNK_SHIFT))
      if c is None or key(c, cx, cy) != target:
         continue
      change(c, cx, cy)
      n += 1
      if n >= FILL_LIMIT:
         break
      for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
         if (nx, ny) not in seen:
            seen.add((nx, ny))
            todo.append((nx, ny))
   return n


def pattern_at(pattern: Sequence[Sequence[EntryT]], ax: int, ay: int, x: int, y: int) -> EntryT:
   """!The entry of a stamp pattern that lands on a cell when the pattern is
   repeated from an anchor (so overlapping and repeated stamps line up).
   @param pattern  rows of entries (all rows the same length)
   @param ax       anchor column (where the pattern's top-left goes)
   @param ay       anchor row
   @param x        cell column
   @param y        cell row
   @return the entry
   """
   row = pattern[(y - ay) % len(pattern)]
   return row[(x - ax) % len(row)]


def stamp(doc: Document, layer: int, cells: Iterable[Cell], pattern: Sequence[Sequence[int | None]], ax: int,
          ay: int) -> int:
   """!Paints cells of a tile layer from a stamp pattern repeated from an
   anchor; None entries of the pattern leave their cell alone.
   @param doc      map Document
   @param layer    layer index
   @param cells    (x, y) cells to paint
   @param pattern  rows of dictionary indices (or None)
   @param ax       anchor column
   @param ay       anchor row
   @return cells painted
   """
   n = 0
   for x, y in cells:
      i = pattern_at(pattern, ax, ay, x, y)
      if i is not None:
         paint(doc, layer, x, y, i)
         n += 1
   return n


def stamp_cells(pattern: Sequence[Sequence[object]], x: int, y: int) -> list[Cell]:
   """!The cells one stamp covers with its top-left on (x, y) (None entries left out).
   @param pattern  rows of entries
   @param x        column of the top-left entry
   @param y        row of the top-left entry
   @return list of (x, y)
   """
   return [(x + dx, y + dy) for dy, row in enumerate(pattern) for dx, v in enumerate(row) if v is not None]


def fill(doc: Document, layer: int, x: int, y: int, index: int | None,
         pattern: Sequence[Sequence[int | None]] | None = None) -> int:
   """!Flood-fills a tile layer: the area of cells showing the same thing on
   that layer as (x, y) (4-connected, painted and unpainted cells kept
   apart), only inside existing chunks.
   @param doc      map Document
   @param layer    layer index
   @param x        start column
   @param y        start row
   @param index    dictionary index to paint, or None to clear (ignored with a pattern)
   @param pattern  rows of dictionary indices repeated from (x, y) instead of one index (None entries
                   leave their cell alone), or None
   @return cells in the area
   """
   count = len(layers_of(doc.data))
   if not 0 <= layer < count:
      raise ValueError(f"the map has no layer {layer}")
   if pattern is not None and len(pattern) == 1 and len(pattern[0]) == 1:
      index, pattern = pattern[0][0], None
      if index is None:
         return 0

   # Cells belong to one area when both are unpainted or both painted, with the same entry on the layer.
   def key(c: JsonDict, cx: int, cy: int) -> tuple[bool, int | None]:
      row, col = cy & CHUNK_MASK, cx & CHUNK_MASK
      return c["cells"][row][col] is None, _grid(c, layer, count)[row][col]

   start = _chunks(doc.data).get((x >> CHUNK_SHIFT, y >> CHUNK_SHIFT))
   if start is None:
      return 0
   # Nothing changes when the start already shows the index, or is unpainted and the fill clears.
   if pattern is None and (key(start, x, y) == (False, index) or key(start, x, y) == (True, None) and index is None):
      return 0

   def change(c: JsonDict, cx: int, cy: int) -> None:
      i = index if pattern is None else pattern_at(pattern, x, y, cx, cy)
      if pattern is not None and i is None:
         return
      if i is not None and c["cells"][cy & CHUNK_MASK][cx & CHUNK_MASK] is None:
         c["cells"][cy & CHUNK_MASK][cx & CHUNK_MASK] = make_cell()
      _grid(c, layer, count)[cy & CHUNK_MASK][cx & CHUNK_MASK] = i
   return _flood(doc, x, y, key, change)


def fill_attributes(doc: Document, x: int, y: int, field: str, value: int | bool) -> int:
   """!Flood-fills one attribute over the painted cells around (x, y) that
   have the same value of it (4-connected).
   @param doc    map Document
   @param x      start column
   @param y      start row
   @param field  one of cell_fields()
   @param value  new value
   @return cells changed
   """
   mask, shift = cell_fields()[field]
   if get(doc.data, x, y) is None:
      return 0
   with_fields(make_cell(), **{field: value})   # validates the value

   def key(c: JsonDict, cx: int, cy: int) -> int | None:
      v = c["cells"][cy & CHUNK_MASK][cx & CHUNK_MASK]
      return None if v is None else (v >> shift) & mask

   if key(_chunks(doc.data)[(x >> CHUNK_SHIFT, y >> CHUNK_SHIFT)], x, y) == int(value):
      return 0

   def change(c: JsonDict, cx: int, cy: int) -> None:
      row, col = cy & CHUNK_MASK, cx & CHUNK_MASK
      c["cells"][row][col] = with_fields(c["cells"][row][col], **{field: value})
   return _flood(doc, x, y, key, change)


def bounds(data: JsonDict) -> tuple[int, int, int, int] | None:
   """!Metatile rectangle covering every chunk.
   @param data  map manifest
   @return (x0, y0, x1, y1) inclusive, or None without chunks
   """
   at = [c["at"] for c in data.get("chunks", [])]
   if not at:
      return None
   # Chunk positions to metatiles: the first chunk's first cell to the last chunk's last cell.
   return (min(a[0] for a in at) * CHUNK, min(a[1] for a in at) * CHUNK,
           max(a[0] for a in at) * CHUNK + CHUNK - 1, max(a[1] for a in at) * CHUNK + CHUNK - 1)


def trim(doc: Document) -> int:
   """!Removes chunks that have no painted cell.
   @param doc  map Document
   @return chunks removed
   """
   keep = [c for c in doc.data.get("chunks", []) if any(v is not None for r in c["cells"] for v in r)]
   n = len(doc.data.get("chunks", [])) - len(keep)
   doc.data["chunks"] = keep
   return n


# -- border ---------------------------------------------------------------------------------------

def border_of(data: JsonDict) -> tuple[int, int, list[list[int | None]]]:
   """!The border patterns.
   @param data  map manifest
   @return (w, h, patterns): one list of w*h dictionary indices (None: nothing) per tile layer, rows first
   """
   b = data.get("border") or {}
   w, h = (b.get("size") or [1, 1])[:SIZE_ENTRIES]
   raw = b.get("layers") or []
   pats = []
   for k in range(len(layers_of(data))):
      cells = list(raw[k]) if k < len(raw) else []
      pats.append((cells + [None] * (w * h))[:w * h])
   return w, h, pats


def _store_border(data: JsonDict, w: int, h: int, patterns: Iterable[Iterable[int | None]]) -> None:
   """!Writes the border object, keeping its phase.
   @param data      map manifest
   @param w         width
   @param h         height
   @param patterns  per-layer patterns
   @return None
   """
   phase = (data.get("border") or {}).get("phase", [0, 0])
   border = {"size": [w, h], "layers": [list(p) for p in patterns]}
   if tuple(phase) != (0, 0):
      border["phase"] = [phase[0] % w, phase[1] % h]
   data["border"] = border


def set_border(doc: Document, w: int, h: int, patterns: Sequence[Sequence[int | None]],
               phase: Sequence[int] = (0, 0), metatiles_of: MetatilesOf | None = None) -> None:
   """!Sets the border patterns.
   @param doc           map Document
   @param w             width, 1-8 metatiles
   @param h             height, 1-8
   @param patterns      per tile layer, w*h dictionary indices (None: nothing), rows first
   @param phase         (x, y) pattern offset
   @param metatiles_of  a tileset's metatile names (an "all" dictionary's size), or None
   @return None
   """
   if not (1 <= w <= max_border() and 1 <= h <= max_border()):
      raise ValueError("the border is 1-8 x 1-8 metatiles")
   if len(patterns) != len(layers_of(doc.data)) or any(len(p) != w * h for p in patterns):
      raise ValueError("the border has one pattern of w*h dictionary indices per tile layer")
   names = dictionary(doc.data, metatiles_of)
   # an "all" dictionary resolved without its tilesets' names has no size to check against here (the compiler checks)
   if (names or not uses_all(doc.data)) and any(c is not None and not 0 <= c < len(names) for p in patterns
                                                for c in p):
      raise ValueError("border cells index the map's metatile dictionary")
   doc.data["border"] = {"size": [w, h], "phase": [phase[0] % w, phase[1] % h]}
   _store_border(doc.data, w, h, patterns)


def resize_border(doc: Document, w: int, h: int, metatiles_of: MetatilesOf | None = None) -> None:
   """!Changes the border's size, keeping the cells that still fit (new
   cells are empty). The phase is kept, wrapped to the new size.
   @param doc           map Document
   @param w             width, 1-8 metatiles
   @param h             height, 1-8
   @param metatiles_of  a tileset's metatile names (an "all" dictionary), or None
   @return None
   """
   ow, oh, old = border_of(doc.data)
   pats = [[p[y * ow + x] if x < ow and y < oh else None for y in range(h) for x in range(w)] for p in old]
   phase = (doc.data.get("border") or {}).get("phase", [0, 0])
   set_border(doc, w, h, pats, (phase[0], phase[1]), metatiles_of)
   compact_dictionary(doc)


def paint_border(doc: Document, layer: int, cells: Iterable[Cell], name: str | None,
                 metatiles_of: MetatilesOf | None = None) -> int:
   """!Paints border cells of one tile layer with a metatile, or clears them.
   @param doc           map Document
   @param layer         layer index
   @param cells         (x, y) border cells
   @param name          "tileset/metatile", or None to clear
   @param metatiles_of  a tileset's metatile names (an "all" dictionary), or None
   @return cells changed
   """
   w, h, pats = border_of(doc.data)
   if not 0 <= layer < len(pats):
      raise ValueError(f"the map has no layer {layer}")
   index = None if name is None else dictionary_index(doc, name, metatiles_of)
   n = 0
   for x, y in cells:
      if 0 <= x < w and 0 <= y < h and pats[layer][y * w + x] != index:
         pats[layer][y * w + x] = index
         n += 1
   _store_border(doc.data, w, h, pats)
   compact_dictionary(doc)
   return n


def stamp_border(doc: Document, layer: int, cells: Iterable[Cell], pattern: Sequence[Sequence[str | None]],
                 ax: int, ay: int, metatiles_of: MetatilesOf | None = None) -> int:
   """!Paints border cells of one tile layer from a stamp pattern of
   metatile names repeated from an anchor (None entries leave a cell alone).
   @param doc      map Document
   @param layer    layer index
   @param cells    (x, y) border cells
   @param pattern  rows of "tileset/metatile" names (or None)
   @param ax       anchor column
   @param ay       anchor row
   @param metatiles_of  a tileset's metatile names (an "all" dictionary), or None
   @return cells changed
   """
   w, h, pats = border_of(doc.data)
   if not 0 <= layer < len(pats):
      raise ValueError(f"the map has no layer {layer}")
   n = 0
   for x, y in cells:
      name = pattern_at(pattern, ax, ay, x, y)
      if name is None or not (0 <= x < w and 0 <= y < h):
         continue
      index = dictionary_index(doc, name, metatiles_of)
      if pats[layer][y * w + x] != index:
         pats[layer][y * w + x] = index
         n += 1
   _store_border(doc.data, w, h, pats)
   compact_dictionary(doc)
   return n


def new_map_data(name: str, tilesets: Iterable[str] = (),
                 layers: Sequence[tuple[int, int, str]] = DEFAULT_LAYERS) -> JsonDict:
   """!The manifest of a new, blank map.
   @param name      map id
   @param tilesets  tilesets it draws from
   @param layers    (bg, priority, purpose) per tile layer
   @return capsule.map/2 JSON
   """
   return {"schema": "capsule.map/2", "id": name, "tilesets": list(tilesets),
           "layers": [{"bg": bg, "priority": p, "content": "tilemap", "purpose": purpose} for bg, p, purpose in layers],
           "metatiles": [], "chunks": [], "border": {"size": [1, 1], "layers": [[None] for _ in layers]}}
