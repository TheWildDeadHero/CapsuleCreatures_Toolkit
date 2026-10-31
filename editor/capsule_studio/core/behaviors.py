"""!The world's behaviors (terrain classes; world.json "behaviors", index 0 "normal"): whether a cell of it is
solid, which movement modes may enter it, what it does to the walker (slide, ledge, push; I3: counter) and, I2, its
walls (the sides a step may not cross: one-way fences).

The engine's map_compiler is the authority: the kinds, directions and limits come from it (KINDS, DIRECTIONS,
MAX_BEHAVIORS, KEYS "behavior"), edits are refused with the rules it applies (one movement kind at most, a ledge or
push needs a direction, walls list directions once each), and compile() checks the world as the build does. Maps
name behaviors by name in their behavior dictionaries, so adding one changes no map. Qt-free.

Functions that change the world Document must be called inside doc.edit().
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import engine
from .document import DocumentError

if TYPE_CHECKING:
   from .document import Document

## A parsed JSON object.
JsonDict = dict[str, Any]

## The world's behavior list.
BEHAVIORS_KEY = "behaviors"
## A behavior's movement modes (vehicle classes) that may enter it.
PASSABLE_KEY = "passable"
## A behavior's wall sides (I2).
WALLS_KEY = "walls"
## The kind of a behavior that does nothing to the walker (map_compiler KINDS[0]).
NO_KIND = "none"
## Kinds that take no direction (a slide keeps the walker's; a counter is faced from any side).
UNDIRECTED = ("slide", "counter")


def _mc() -> Any:
   """!The engine's map compiler.
   @return map_compiler
   """
   return engine.tool("map_compiler")


def kinds() -> list[str]:
   """!What a behavior may do to the walker (the engine's map_compiler.KINDS: none, slide, ledge, push, counter).
   @return kind words
   """
   return list(_mc().KINDS)


def directions() -> list[str]:
   """!Directions (the engine's map_compiler.DIRECTIONS, field::Direction order).
   @return down, up, left, right
   """
   return list(_mc().DIRECTIONS)


def _behaviors(doc: Document) -> list[JsonDict]:
   """!The world's behavior objects.
   @param doc  world Document
   @return the manifest's own list (a world without one gets the engine's default list on the first edit)
   """
   raw = doc.data.get(BEHAVIORS_KEY)
   return raw if isinstance(raw, list) else []


def rows(doc: Document) -> list[JsonDict]:
   """!The world's behaviors.
   @param doc  world Document
   @return per behavior: index, name, solid, passable (mode names, or None: every mode), kind (a kinds() word),
           direction (for ledge / push, or None), walls (directions)
   """
   out = []
   for i, b in enumerate(_behaviors(doc)):
      b = b if isinstance(b, dict) else {}
      kind = next((k for k in kinds()[1:] if b.get(k)), NO_KIND)
      direction = b.get(kind) if kind not in UNDIRECTED and kind != NO_KIND else None
      out.append({"index": i, "name": b.get("name"), "solid": b.get("solid", False) is True,
                  "passable": b.get(PASSABLE_KEY), "kind": kind, "direction": direction,
                  "walls": list(b.get(WALLS_KEY, [])) if isinstance(b.get(WALLS_KEY), list) else []})
   return out


def _behavior(doc: Document, name: str) -> JsonDict:
   """!A behavior object by name.
   @param doc   world Document
   @param name  behavior name
   @return the dict
   """
   for b in _behaviors(doc):
      if isinstance(b, dict) and b.get("name") == name:
         return b
   raise DocumentError(f"the world has no behavior {name!r}")


def add_behavior(doc: Document, name: str) -> int:
   """!Adds a behavior (nothing special: entered by every mode).
   @param doc   world Document
   @param name  a new name
   @return its index
   """
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("a behavior needs a name")
   if any(isinstance(b, dict) and b.get("name") == name for b in _behaviors(doc)):
      raise DocumentError(f"the world already has a behavior {name!r}")
   if len(_behaviors(doc)) >= _mc().MAX_BEHAVIORS:
      raise DocumentError(f"a world has at most {_mc().MAX_BEHAVIORS} behaviors")
   if not isinstance(doc.data.get(BEHAVIORS_KEY), list):
      doc.data[BEHAVIORS_KEY] = [{"name": "normal"}]   # the engine's default list, made explicit
   doc.data[BEHAVIORS_KEY].append({"name": name})
   return len(doc.data[BEHAVIORS_KEY]) - 1


def set_kind(doc: Document, name: str, kind: str, direction: str | None = None) -> None:
   """!What a behavior does to the walker: none, slide, ledge (jumped over moving its direction), push (a forced
   step) or counter (I3: A facing it talks to the object beyond); the kinds exclude each other.
   @param doc        world Document
   @param name       behavior name
   @param kind       one of kinds()
   @param direction  for ledge and push: one of directions()
   @return None
   """
   if kind not in kinds():
      raise DocumentError(f"a behavior's kind is one of {', '.join(kinds())}")
   b = _behavior(doc, name)
   for k in kinds()[1:]:
      b.pop(k, None)
   if kind == NO_KIND:
      return
   if kind in UNDIRECTED:
      b[kind] = True
      return
   if direction not in directions():
      raise DocumentError(f"a {kind} needs a direction ({', '.join(directions())})")
   b[kind] = direction


def set_walls(doc: Document, name: str, sides: list[str]) -> None:
   """!A behavior's walls (I2): the sides of its cells a step may not cross, leaving or entering (one-way fences).
   @param doc    world Document
   @param name   behavior name
   @param sides  directions, each once ([]: no walls)
   @return None
   """
   if any(s not in directions() for s in sides) or len(set(sides)) != len(sides):
      raise DocumentError(f"walls list directions ({', '.join(directions())}), each once")
   b = _behavior(doc, name)
   if sides:
      # in the engine's direction order, as the compiler numbers the bits
      b[WALLS_KEY] = [d for d in directions() if d in sides]
   else:
      b.pop(WALLS_KEY, None)


def set_solid(doc: Document, name: str, solid: bool) -> None:
   """!Whether nothing may enter a behavior's cells.
   @param doc    world Document
   @param name   behavior name
   @param solid  True or False
   @return None
   """
   b = _behavior(doc, name)
   if solid:
      b["solid"] = True
   else:
      b.pop("solid", None)


def set_passable(doc: Document, name: str, modes: list[str] | None) -> None:
   """!The movement modes that may enter a behavior's cells (with the mode's own passable list).
   @param doc    world Document
   @param name   behavior name
   @param modes  mode names, or None for every mode
   @return None
   """
   known = [str(n) for n in _mc().vehicle_class_names(doc.data)]
   if modes is not None and any(m not in known for m in modes):
      raise DocumentError(f"passable lists movement modes ({', '.join(known)})")
   b = _behavior(doc, name)
   if modes is None:
      b.pop(PASSABLE_KEY, None)
   else:
      b[PASSABLE_KEY] = [m for m in known if m in modes]


def lines(doc: Document) -> list[str]:
   """!The behaviors as text lines.
   @param doc  world Document
   @return lines
   """
   out = []
   for r in rows(doc):
      parts = ["solid"] if r["solid"] else []
      if r["passable"] is not None:
         parts.append("passable " + (", ".join(str(m) for m in r["passable"]) or "by nothing"))
      if r["kind"] != NO_KIND:
         parts.append(r["kind"] + (f" {r['direction']}" if r["direction"] else ""))
      if r["walls"]:
         parts.append("walls " + ", ".join(r["walls"]))
      out.append(f"{r['index']} {r['name']}" + (": " + "; ".join(parts) if parts else ""))
   return out
