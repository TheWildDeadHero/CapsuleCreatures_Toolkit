"""![S3] The world's object draw order rule (D-30 section 4, engine DS1: world "draw_order").

Sprites sort among themselves by priority << 8 | sub-priority, ascending (lower draws in front; on a tie the one
whose lower edge is lower on screen goes first). The sub-priority comes from the sprite's bottom edge on screen and
its elevation: base[elevation] + (rows - ((bottom + bias) & (wrap - 1)) / row_pixels) * row_step + add, kept to 8
bits (capsule::map::draw_order_of()). The rule's fields and defaults are map_compiler's (KEYS "draw_order",
DEFAULT_DRAW_ORDER); compile_draw_order() decides what is valid. A world without "draw_order" uses the default
(lower on screen in front).

Functions that change the world must run inside world.edit(). Nothing here imports Qt.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import engine

if TYPE_CHECKING:
   from .document import Document

## A parsed JSON object (the rule).
JsonDict = dict[str, Any]

## The world key.
KEY = "draw_order"
## The rule's per-elevation list.
BASE_KEY = "elevation_base"
## Bits a sub-priority keeps (a u8).
SUB_MASK = 0xFF
## Bits a priority is shifted by in the sort key (priority << 8 | sub).
PRIORITY_SHIFT = 8
## Pixels per side of a metatile (a cell's bottom edge is 16 pixels below its top).
CELL_PIXELS = 16


def _mc() -> Any:
   """!The engine's map compiler.
   @return module
   """
   return engine.tool("map_compiler")


def fields() -> list[str]:
   """!The rule's fields, in the manifest's documented order (map_compiler KEYS "draw_order").
   @return names (elevation_base first)
   """
   order = list(_mc().DEFAULT_DRAW_ORDER)
   return order + sorted(set(_mc().KEYS[KEY]) - set(order))


def defaults() -> JsonDict:
   """!The default rule (map_compiler DEFAULT_DRAW_ORDER).
   @return a copy
   """
   return copy.deepcopy(_mc().DEFAULT_DRAW_ORDER)


def elevations() -> int:
   """!Elevation levels the rule has a base for (map_compiler ELEVATIONS).
   @return 16
   """
   return int(_mc().ELEVATIONS)


def ranges() -> dict[str, tuple[int, int]]:
   """!Each field's values as compile_draw_order() takes them (row_pixels and wrap powers of two).
   @return {field: (lowest, highest)}; elevation_base gives one base's range
   """
   mc = _mc()
   byte = (0, mc.MAX_U8)
   return {BASE_KEY: byte, "bias": (mc.MIN_I8, mc.MAX_I8), "row_pixels": (1, mc.MAX_DRAW_WRAP), "rows": byte,
           "row_step": byte, "add": byte, "wrap": (1, mc.MAX_DRAW_WRAP)}


def is_set(world: Document) -> bool:
   """!Whether the world states a rule (else the default applies).
   @param world  world Document
   @return True when "draw_order" is given
   """
   return isinstance(world.data.get(KEY), dict)


def rule(world: Document) -> JsonDict:
   """!The world's rule with the defaults filled in.
   @param world  world Document
   @return every field
   """
   d = world.data.get(KEY)
   return dict(defaults(), **(copy.deepcopy(d) if isinstance(d, dict) else {}))


def check(raw: JsonDict) -> JsonDict:
   """!Checks a rule with the engine (map_compiler.compile_draw_order()).
   @param raw  the "draw_order" value
   @return the compiled rule ({"base", "bias", "mask", "row_shift", "rows", "row_step", "add"})
   @throws ValueError with the compiler's message
   """
   mc = _mc()
   try:
      return mc.compile_draw_order({KEY: raw})
   except mc.ManifestError as e:
      raise ValueError(str(e)) from None


def set_field(world: Document, name: str, value: Any) -> None:
   """!Sets one field of the rule (a field equal to its default is left out; an empty rule is removed).
   @param world  world Document
   @param name   a field (elevation_base takes the 16 values)
   @param value  its value
   @return None
   """
   if name not in fields():
      raise ValueError(f"the draw order rule has {', '.join(fields())}, not {name!r}")
   raw = copy.deepcopy(world.data.get(KEY)) if is_set(world) else {}
   raw[name] = list(value) if name == BASE_KEY else value
   check(raw)
   _store(world, raw)


def set_base(world: Document, elevation: int, value: int) -> None:
   """!Sets one elevation's base.
   @param world      world Document
   @param elevation  0-15
   @param value      0-255
   @return None
   """
   base = list(rule(world)[BASE_KEY])
   if not 0 <= elevation < len(base):
      raise ValueError(f"elevation is 0-{len(base) - 1}")
   base[elevation] = value
   set_field(world, BASE_KEY, base)


def _store(world: Document, raw: JsonDict) -> None:
   """!Writes a rule, leaving out fields equal to their defaults.
   @param world  world Document
   @param raw    the rule
   @return None
   """
   kept = {k: v for k, v in raw.items() if defaults().get(k) != v}
   if kept:
      world.data[KEY] = kept
   else:
      world.data.pop(KEY, None)


def reset(world: Document) -> None:
   """!Removes the rule (the default applies).
   @param world  world Document
   @return None
   """
   world.data.pop(KEY, None)


def sub_priority(r: JsonDict, bottom: int, elevation: int) -> int:
   """!A sprite's sub-priority by a rule, as capsule::map::draw_order_of() computes it.
   @param r          the rule (rule()'s form)
   @param bottom     the sprite's bottom edge on screen, pixels
   @param elevation  its elevation level
   @return 0 (front) to 255
   """
   c = check(r)
   edge = (bottom + c["bias"]) & c["mask"]
   row = edge >> c["row_shift"]
   return (c["base"][elevation % len(c["base"])] + (c["rows"] - row) * c["row_step"] + c["add"]) & SUB_MASK


@dataclass
class Sprite:
   """!A sprite of the draw-order preview: where it stands and its result."""

   ## A name for the readout.
   name: str
   ## Its bottom edge on screen, pixels.
   bottom: int
   ## Its elevation level.
   elevation: int
   ## Its priority against the background layers (the elevation's level priority).
   priority: int
   ## Its sub-priority (computed).
   sub: int = 0

   def key(self) -> int:
      """!The sort key OAM entries are ordered by.
      @return priority << 8 | sub
      """
      return self.priority << PRIORITY_SHIFT | self.sub


def order(r: JsonDict, sprites: list[Sprite]) -> list[Sprite]:
   """!Sprites front to back, as gfx::sprites sorts them (key ascending; on a tie the lower bottom edge first).
   @param r        the rule
   @param sprites  the sprites (their sub is set)
   @return the sprites, the front one first
   """
   for s in sprites:
      s.sub = sub_priority(r, s.bottom, s.elevation)
   return sorted(sprites, key=lambda s: (s.key(), -s.bottom))


def level_priority(world: Document, elevation: int) -> int:
   """!The sprite priority of an elevation level (the world's levels, core.field_rules; level priority).
   @param world      world Document
   @param elevation  0-15
   @return 0-3
   """
   from . import field_rules
   rows = field_rules.level_rows(world)
   return int(rows[elevation]["priority"]) if 0 <= elevation < len(rows) else 0


def lines(world: Document) -> list[str]:
   """!The rule as text (`draw-order show`).
   @param world  world Document
   @return lines
   """
   r = rule(world)
   head = "draw order (the world's)" if is_set(world) else "draw order (the default: the world states none)"
   return [head] + [f"  {k}: {r[k]}" for k in fields()]
