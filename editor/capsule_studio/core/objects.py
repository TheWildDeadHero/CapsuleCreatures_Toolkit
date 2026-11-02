"""!Map objects (B-21): editing a map's characters, spotters and pickups,
their event pages, triggers, movement options and move routes.

The engine's tools/object_compiler.py (through map_compiler.py) is the one
authority on what is valid: check() and diagnostics() run it on the open,
unsaved documents. This module adds what editors need: objects by local ID
(their index in the map's "objects" list) and cell, changes as one undo step
each, unique names, pages by index, move routes checked with the engine's
tools/route_compiler.py as they are typed, and the names the scripts
manifest offers (core.events.names()). Qt-free; the objects panel, its map tool and
`capsule-studio objects` use it.

Every function that changes a Document must be called inside doc.edit()
(the host's run_edit()).

Object records are the manifest's own objects: {"name", "at": [x, y],
"sprite": "sprite:NAME", ...}; see the engine's object_compiler.py for every
key. Scripts address objects by local ID (world_ids.h OBJ_<MAP>_<NAME>), so
removing an object shifts the local IDs of the ones after it; remove_object()
says which.

Pages (RPG Maker XP's event pages) are {"when": {flag, var, value,
equal, self}, ...fields it replaces} or {"when": ..., "hidden": true}; the
last page whose conditions all hold is the active one, and with none the
object's own fields are. Worlds written from an older version had "overrides" (the
first whose flag was set applied); pages_from_overrides() turns them into
pages (the importer does so).

The reference games' movement types (turn, roam, rotate, patrol, circuit,
mirror, in_place, invisible) and their settings ("movement_args": the
engine's object_compiler.MOVEMENT_ARGS, DELAYS, PACES), ranges up to the
engine's MAX_RANGE, and a map's "object_view" (up to MAX_VIEW_OBJECTS
objects, spawned near the player) and "stacked_objects". The lists and
limits are read from the engine (movements(), movement_args_of(), ...).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import engine, events
from .document import DocumentError

if TYPE_CHECKING:
   from ..plugins.registry import Diagnostic
   from .document import Document
   from .manifest_io import JsonDict, JsonValue
   from .world import Project

## The movement the compiler refuses until the world clock exists (C-05).
SCHEDULE = "schedule"
## Movement types that use a range box (roam, patrol, circuit and mirror stay inside theirs; 0 on an axis
## leaves it unbounded).
RANGED = {"wander", "pace_vertical", "pace_horizontal", "roam", "patrol", "circuit", "mirror"}
## Triggers (capsule::map::Trigger order): what starts an object's script.
TRIGGERS = ["action", "player_touch", "event_touch", "autorun", "parallel"]
## Triggers that need a script (the compiler refuses them without one).
SCRIPTED = {"autorun", "parallel"}
## Movement options and their defaults (walking animation on, the rest off).
OPTIONS = {"walk_anim": True, "step_anim": False, "direction_fix": False, "through": False, "on_top": False}
## Speed range and default (2 = walking).
SPEEDS, DEFAULT_SPEED = (1, 4), 2
## Frequency range and default.
FREQUENCIES, DEFAULT_FREQUENCY = (1, 5), 3
## Self switch letters.
SELF_SWITCHES = ("A", "B", "C", "D")
## Directions (field::Direction order).
DIRECTIONS = events.DIRECTIONS
## Keys an object may hold (besides "name", "at" and "pages"); "sight" and "until" are its spotter's.
FIELDS = ("elevation", "sprite", "facing", "movement", "range", "route", "speed", "frequency", "options", "script",
          "trigger", "flag", "self_switches", "sight", "until", "kind", "movement_args")
## Fields of an object's spotter ({"sight": cells, "until": flag}): it watches the cells in front of it.
SPOTTER_FIELDS = ("sight", "until")
## Keys a page may hold besides "when": the fields it replaces, or "hidden".
PAGE_FIELDS = ("sprite", "facing", "movement", "range", "route", "speed", "frequency", "options", "script",
               "trigger", "hidden", "movement_args")
## Keys of a page's conditions ("when").
WHEN_FIELDS = ("flag", "var", "value", "equal", "self")
## Keys of a move route.
ROUTE_FIELDS = ("steps", "repeat", "skip")
## Pages per object.
MAX_PAGES = 255
## Longest spotter sight.
MAX_SIGHT = 8
## A movement setting's choices or legs: entries of an "at"-style list ("choices" 2 or 4, "legs" 4).
TWO, FOUR = 2, 4
## Sides of a map's object view: left, right, up, down.
VIEW_SIDES = ("left", "right", "up", "down")
## Sprite new objects get.
DEFAULT_SPRITE = "sprite:NPC"
## Route a custom movement starts with when it has none.
DEFAULT_ROUTE = {"steps": ["turn random", "wait 60"]}
## Highest elevation of an object (0: any level; the levels of an attribute cell's elevation).
MAX_ELEVATION = 15
## Entries of an [x, y] pair: a cell ("at") or a range.
XY_ENTRIES = 2
## Smallest value a page condition compares a variable with (signed 32-bit).
VALUE_MIN = -2**31
## Largest value a page condition compares a variable with (signed 32-bit).
VALUE_MAX = 2**31 - 1
## Words of a route step that names a flag: "set FLAG" or "clear FLAG".
FLAG_STEP_WORDS = 2


def _obc() -> Any:
   """!The engine's object compiler.
   @return object_compiler
   """
   return engine.tool("object_compiler")


def movements() -> list[str]:
   """!The movement types (the engine's object_compiler.MOVEMENTS, capsule::map::Movement order, without schedule,
   which the compiler refuses until the world clock exists; the imported events and sprites adds the reference games'
   types).
   @return movement names
   """
   return [m for m in _obc().MOVEMENTS if m != SCHEDULE]


def movement_args_of(movement: str) -> list[str]:
   """!The settings a movement takes in "movement_args" (the engine's object_compiler.MOVEMENT_ARGS).
   @param movement  movement name
   @return setting names ([] for a movement without settings)
   """
   return sorted(_obc().MOVEMENT_ARGS.get(movement, ()))


def delay_words() -> list[str]:
   """!A turn / roam's delay tables (the engine's object_compiler.DELAYS).
   @return medium, short
   """
   return list(_obc().DELAYS)


def pace_words() -> list[str]:
   """!An in_place's paces (the engine's object_compiler.PACES).
   @return slow, walk, jog, run
   """
   return list(_obc().PACES)


def max_range() -> int:
   """!The largest range each way (the engine's object_compiler.MAX_RANGE; 15).
   @return cells
   """
   return int(_obc().MAX_RANGE)


def max_objects(doc: Document) -> int:
   """!Objects a map may list: the engine's object_compiler.MAX_OBJECTS (sprite slots 1-15), or with an object
   view MAX_VIEW_OBJECTS (they spawn near the player).
   @param doc  map Document
   @return the count
   """
   return int(_obc().MAX_VIEW_OBJECTS if doc.data.get("object_view") is not None else _obc().MAX_OBJECTS)


def object_view(doc: Document) -> list[int] | None:
   """!A map's object view: [left, right, up, down] cells around the player its objects spawn in.
   @param doc  map Document
   @return the four counts, or None (every object spawns at entry)
   """
   v = doc.data.get("object_view")
   return list(v) if isinstance(v, list) else None


def set_object_view(doc: Document, view: list[int] | None) -> None:
   """!Sets a map's object view (call inside doc.edit()): None removes it (then at most MAX_OBJECTS objects).
   @param doc   map Document
   @param view  [left, right, up, down] (0 to the engine's map_compiler.MAX_VIEW_CELLS, one at least above 0), or
                None
   @return None
   """
   if view is None:
      if len(objects(doc)) > _obc().MAX_OBJECTS:
         raise DocumentError(f"the map lists {len(objects(doc))} objects; without an object view at most "
                             f"{_obc().MAX_OBJECTS} (remove some first)")
      doc.data.pop("object_view", None)
      return
   most = engine.tool("map_compiler").MAX_VIEW_CELLS
   if not (isinstance(view, (list, tuple)) and len(view) == len(VIEW_SIDES) and
           all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= most for v in view)) or not any(view):
      raise DocumentError(f"an object view is [left, right, up, down], each 0-{most}, one at least above 0")
   doc.data["object_view"] = list(view)


def set_stacked(doc: Document, on: bool) -> None:
   """!Whether a map's objects may share a cell (the imported events and sprites "stacked_objects": data whose flags
   keep one there at a time).
   @param doc  map Document
   @param on   True or False
   @return None
   """
   if on:
      doc.data["stacked_objects"] = True
   else:
      doc.data.pop("stacked_objects", None)


def objects(doc: Document) -> list[JsonDict]:
   """!A map's objects, in local-ID order.
   @param doc  map Document
   @return list of object dicts (the document's own; do not change them outside edit())
   """
   items = doc.data.get("objects")
   return items if isinstance(items, list) else []


def objects_at(doc: Document, x: int, y: int) -> list[tuple[int, JsonDict]]:
   """!The objects on a cell.
   @param doc  map Document
   @param x    column
   @param y    row
   @return list of (local ID, object)
   """
   return [(i, o) for i, o in enumerate(objects(doc)) if isinstance(o, dict) and o.get("at") == [x, y]]


def object_at(doc: Document, x: int, y: int) -> tuple[int, JsonDict] | None:
   """!The first object on a cell.
   @param doc  map Document
   @param x    column
   @param y    row
   @return (local ID, object), or None
   """
   here = objects_at(doc, x, y)
   return here[0] if here else None


def index_of(doc: Document, name: str) -> int:
   """!An object's local ID by name.
   @param doc   map Document
   @param name  object name
   @return its local ID
   """
   for i, o in enumerate(objects(doc)):
      if isinstance(o, dict) and o.get("name") == name:
         return i
   raise DocumentError(f"no object {name!r} (objects: {', '.join(str(o.get('name')) for o in objects(doc))})")


def _get(doc: Document, index: int) -> JsonDict:
   """!An object by local ID.
   @param doc    map Document
   @param index  local ID
   @return the object
   """
   items = objects(doc)
   if not 0 <= index < len(items) or not isinstance(items[index], dict):
      raise DocumentError(f"no object {index}")
   return items[index]


def _range_text(r: JsonValue) -> str:
   """!A range as text.
   @param r  [x, y]
   @return e.g. 2x1
   """
   return f"{r[0]}x{r[1]}" if isinstance(r, list) and len(r) == XY_ENTRIES else "?"


def _motion_text(src: JsonDict, defaults: bool) -> list[str]:
   """!The movement parts of an object or page description.
   @param src       object or page
   @param defaults  True for an object (default values are not shown)
   @return list of texts
   """
   parts = []
   if "speed" in src and (not defaults or src["speed"] != DEFAULT_SPEED):
      parts.append(f"speed {src['speed']}")
   if "frequency" in src and (not defaults or src["frequency"] != DEFAULT_FREQUENCY):
      parts.append(f"frequency {src['frequency']}")
   opts = src.get("options")
   if isinstance(opts, dict) and (opts or not defaults):
      on = [k for k, v in opts.items() if v is True]
      off = [k for k, v in opts.items() if v is False]
      parts.append("options " + (", ".join(on + [f"no {k}" for k in off]) or "default"))
   rt = src.get("route")
   if isinstance(rt, dict):
      steps = rt.get("steps") if isinstance(rt.get("steps"), list) else []
      how = "" if rt.get("repeat", True) else ", once"
      parts.append(f"route of {len(steps)} step(s){how}")
   if "trigger" in src and (not defaults or src["trigger"] != "action"):
      parts.append(f"trigger {src['trigger']}")
   return parts


def describe_args(args: JsonValue) -> str:
   """!A movement's settings as text.
   @param args  the "movement_args" object
   @return e.g. "choices down, up; delays short", or "" for none
   """
   if not isinstance(args, dict) or not args:
      return ""
   parts = []
   for k, v in args.items():
      if v is True:
         parts.append(k.replace("_", " "))
      elif isinstance(v, list):
         parts.append(f"{k} {', '.join(str(x) for x in v)}")
      else:
         parts.append(f"{k} {v}")
   return "; ".join(parts)


def describe(o: JsonDict) -> str:
   """!One line about an object.
   @param o  the object
   @return text
   """
   move = o.get("movement", "static")
   if move in RANGED:
      r = o.get("range", [1, 1])
      move += f" {r[0]}x{r[1]}" if isinstance(r, list) and len(r) == XY_ENTRIES else ""
   if describe_args(o.get("movement_args")):
      move += f" ({describe_args(o.get('movement_args'))})"
   parts = [f"{o.get('sprite', '?')}, {move}, facing {o.get('facing', 'down')}"]
   parts += _motion_text(o, True)
   spotter = o.get("spotter")
   if isinstance(spotter, dict):
      until = f" until {spotter['until']}" if "until" in spotter else ""
      parts.append(f"spotter, sight {spotter.get('sight')}{until}")
   if "script" in o:
      parts.append(f"talk: {o['script']}")
   if "flag" in o:
      parts.append(f"hidden while {o['flag']}")
   if o.get("self_switches"):
      parts.append("self switches")
   pgs = o.get("pages")
   if isinstance(pgs, list) and pgs:
      parts.append(f"{len(pgs)} page(s)")
   if o.get("elevation"):
      parts.append(f"level {o['elevation']}")
   return "; ".join(parts)


def describe_when(when: JsonValue) -> str:
   """!A page's conditions as text.
   @param when  the "when" object
   @return e.g. "badge_1, coins >= 5, self A"
   """
   if not isinstance(when, dict):
      return "?"
   parts = []
   if "flag" in when:
      parts.append(str(when["flag"]))
   if "var" in when:
      parts.append(f"{when['var']} {'==' if when.get('equal') else '>='} {when.get('value', '?')}")
   letters = when.get("self")
   if letters:
      parts.append("self " + ("+".join(letters) if isinstance(letters, list) else str(letters)))
   return ", ".join(parts) or "nothing"


def describe_page(pg: JsonDict) -> str:
   """!One line about a page.
   @param pg  the page
   @return text
   """
   head = f"when {describe_when(pg.get('when'))}: "
   if pg.get("hidden"):
      return head + "hidden"
   what = [f"{k} {pg[k]}" for k in ("sprite", "movement", "facing", "script") if k in pg]
   if "range" in pg:
      what.append(f"range {_range_text(pg['range'])}")
   what += _motion_text(pg, False)
   return head + (", ".join(what) or "nothing")


def _check_name(name: JsonValue) -> None:
   """!Checks an object name.
   @param name  candidate
   @return None
   """
   if not isinstance(name, str) or not name.isidentifier() or not name.isascii():
      raise DocumentError(f"{name!r} is not an identifier (letters, digits and _, not starting with a digit)")


def free_name(doc: Document, base: str = "npc") -> str:
   """!A name no object of the map has.
   @param doc   map Document
   @param base  stem
   @return e.g. npc_2
   """
   taken = {o.get("name") for o in objects(doc) if isinstance(o, dict)}
   n = 1
   while f"{base}_{n}" in taken:
      n += 1
   return f"{base}_{n}"


def _range(value: JsonValue) -> list[int]:
   """!Checks a range.
   @param value  [x, y]
   @return the list
   """
   if not (isinstance(value, (list, tuple)) and len(value) == XY_ENTRIES and
           all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= max_range() for v in value)):
      raise DocumentError(f"range is [x, y], each 0-{max_range()}")
   return [value[0], value[1]]


def _int(value: JsonValue, lo: int, hi: int, what: str) -> int:
   """!Checks a whole number.
   @param value  candidate
   @param lo     minimum
   @param hi     maximum
   @param what   name for messages
   @return the value
   """
   if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
      raise DocumentError(f"{what} is {lo}-{hi}")
   return value


def _options(value: JsonValue) -> dict[str, bool]:
   """!Checks movement options.
   @param value  {option: bool}
   @return a copy
   """
   if not isinstance(value, dict):
      raise DocumentError(f"options is an object of {', '.join(OPTIONS)}: true / false")
   for k, v in value.items():
      if k not in OPTIONS:
         raise DocumentError(f"no option {k!r} (options: {', '.join(OPTIONS)})")
      if not isinstance(v, bool):
         raise DocumentError(f"option {k} is true or false")
   return dict(value)


def route_steps(text: str | Sequence[str]) -> list[str]:
   """!Route steps from text, one per line (blank lines and lines starting with # are skipped).
   @param text  the text, or a list of steps
   @return list of step strings
   """
   lines = text if isinstance(text, (list, tuple)) else str(text).splitlines()
   out = []
   for line in lines:
      if not isinstance(line, str):
         raise DocumentError(f"a route step is text, got {line!r}")
      line = " ".join(line.split())
      if line and not line.startswith("#"):
         out.append(line)
   return out


def route_error(steps: list[str], repeat: bool = True, skip: bool = False,
                flags: Iterable[str] | None = None) -> str | None:
   """!Checks route steps with the engine's route_compiler (when it can be imported).
   @param steps   list of step strings
   @param repeat  the route starts over at the end
   @param skip    blocked steps are skipped
   @param flags   flag names the steps may name, or None not to check them
   @return error message, or None when the steps compile (or the engine is missing)
   """
   if not isinstance(steps, list) or not steps:
      return "a route needs at least one step"
   try:
      rc = engine.tool("route_compiler")
   except (engine.EngineNotFound, ImportError):
      return None
   known = None if flags is None else set(flags)

   def flag_id(name: str) -> int:
      """!A flag's ID (0: only checked to exist)."""
      if known is not None and name not in known:
         raise rc.RouteError(f"unknown flag {name!r}")
      return 0
   try:
      rc.compile_route([rc.parse_text(t) for t in steps], repeat, skip, flag_id, lambda _ref: 0)
   except rc.RouteError as e:
      return str(e)
   return None


def _route(value: JsonValue) -> JsonDict:
   """!Checks a move route.
   @param value  {"steps": [...], "repeat": bool, "skip": bool}
   @return the route to store (defaults left out)
   """
   if not isinstance(value, dict):
      raise DocumentError("a route is {\"steps\": [...], \"repeat\": true / false, \"skip\": true / false}")
   bad = sorted(set(value) - set(ROUTE_FIELDS))
   if bad:
      raise DocumentError(f"a route has no field(s) {', '.join(bad)} (known: {', '.join(ROUTE_FIELDS)})")
   steps = route_steps(value.get("steps") or [])
   repeat, skip = value.get("repeat", True), value.get("skip", False)
   if not isinstance(repeat, bool) or not isinstance(skip, bool):
      raise DocumentError("a route's repeat and skip are true or false")
   error = route_error(steps, repeat, skip)
   if error:
      raise DocumentError(f"route: {error}")
   out = {"steps": steps}
   if not repeat:
      out["repeat"] = False
   if skip:
      out["skip"] = True
   return out


def _check(field: str, value: JsonValue) -> JsonValue:
   """!Checks one object or page field.
   @param field  key
   @param value  value (not None)
   @return the value to store
   """
   if field == "elevation":
      _int(value, 0, MAX_ELEVATION, "elevation (0: any level)")
   elif field == "sprite":
      if not isinstance(value, str) or not value.startswith("sprite:") or len(value) <= len("sprite:"):
         raise DocumentError("sprite is a sprite asset reference, 'sprite:NAME'")
   elif field == "facing":
      if value not in DIRECTIONS:
         raise DocumentError(f"facing is one of {', '.join(DIRECTIONS)}")
   elif field == "movement":
      if value not in movements():
         raise DocumentError(f"movement is one of {', '.join(movements())}"
                             + (" (schedule needs the world clock, C-05)" if value == SCHEDULE else ""))
   elif field == "movement_args":
      value = _check_args(value)
   elif field == "range":
      value = _range(value)
   elif field == "route":
      value = _route(value)
   elif field == "speed":
      _int(value, SPEEDS[0], SPEEDS[1], "speed")
   elif field == "frequency":
      _int(value, FREQUENCIES[0], FREQUENCIES[1], "frequency")
   elif field == "options":
      value = _options(value)
   elif field == "trigger":
      if value not in TRIGGERS:
         raise DocumentError(f"trigger is one of {', '.join(TRIGGERS)}")
   elif field in ("self_switches", "hidden"):
      if not isinstance(value, bool):
         raise DocumentError(f"{field} is true or false")
   elif field == "sight":
      _int(value, 0, MAX_SIGHT, "sight (0: not a spotter)")
   elif field in ("script", "flag", "until"):
      if not isinstance(value, str) or not value:
         raise DocumentError(f"{field} is a name from the scripts manifest")
   elif field == "kind":
      # One of the world's object_kinds (the map compiler checks the name)
      if not isinstance(value, str) or not value:
         raise DocumentError("kind is one of the world's object kinds (core.map_field)")
   return value


def _check_args(value: JsonValue) -> JsonDict:
   """!Checks a movement's settings ("movement_args") with the engine's values (the movement itself decides
   which settings it takes: _tidy_args()); keep_to's vehicle class is checked by the world's compile.
   @param value  {setting: value}
   @return a copy
   """
   if not isinstance(value, dict):
      raise DocumentError("movement_args is an object of a movement's settings")
   known = sorted({k for ks in _obc().MOVEMENT_ARGS.values() for k in ks})
   for k, v in value.items():
      if k not in known:
         raise DocumentError(f"no movement setting {k!r} (settings: {', '.join(known)})")
      if k in ("watch_runner", "clockwise", "keep_facing") and not isinstance(v, bool):
         raise DocumentError(f"{k} is true or false")
      if k == "choices" and not (isinstance(v, list) and len(v) in (TWO, FOUR) and all(d in DIRECTIONS for d in v)):
         raise DocumentError(f"choices lists 2 or 4 directions ({', '.join(DIRECTIONS)})")
      if k == "legs" and not (isinstance(v, list) and len(v) == FOUR and all(d in DIRECTIONS for d in v)):
         raise DocumentError("legs lists four directions")
      if k == "facing" and v not in DIRECTIONS:
         raise DocumentError(f"facing is one of {', '.join(DIRECTIONS)}")
      if k == "delays" and v not in delay_words():
         raise DocumentError(f"delays is one of {', '.join(delay_words())}")
      if k == "pace" and v not in pace_words():
         raise DocumentError(f"pace is one of {', '.join(pace_words())}")
      if k == "keep_to" and (not isinstance(v, str) or not v):
         raise DocumentError("keep_to names a vehicle class of the world")
   return dict(value)


def _tidy_args(o: JsonDict, movement: str | None) -> None:
   """!Keeps only the settings a movement takes (settings of another movement go when it changes), and drops
   an empty "movement_args".
   @param o         object or page (changed in place)
   @param movement  its movement (None: a page that keeps its object's)
   @return None
   """
   args = o.get("movement_args")
   if not isinstance(args, dict):
      return
   if movement is not None:
      allowed = set(movement_args_of(movement))
      for k in [k for k in args if k not in allowed]:
         del args[k]
   if not args:
      del o["movement_args"]


def _tidy(o: JsonDict) -> None:
   """!Drops fields that mean nothing with the others: a range for movement
   without one, a route for movement other than custom, an until flag
   without a spotter, a spotter without sight, and values that are the defaults.
   @param o  the object (changed in place)
   @return None
   """
   if o.get("movement", "static") not in RANGED:
      o.pop("range", None)
   if o.get("movement") != "custom":
      o.pop("route", None)
   _tidy_args(o, o.get("movement", "static"))
   defaults = {"movement": "static", "facing": "down", "elevation": 0, "speed": DEFAULT_SPEED,
               "frequency": DEFAULT_FREQUENCY, "trigger": "action", "self_switches": False}
   for k, v in defaults.items():
      # Python has False == 0, so a value only counts as the default when both are bools or neither is.
      if k in o and o[k] == v and not (isinstance(o[k], bool) != isinstance(v, bool)):
         del o[k]
   opts = o.get("options")
   if isinstance(opts, dict):
      for k in [k for k, v in opts.items() if OPTIONS.get(k) is v]:
         del opts[k]
      if not opts:
         del o["options"]
   t = o.get("spotter")
   if isinstance(t, dict) and not t.get("sight"):
      del o["spotter"]


def add_object(doc: Document, x: int, y: int, name: str | None = None, **fields: JsonValue) -> int:
   """!Adds an object (call inside doc.edit()).
   @param doc     map Document
   @param x       column
   @param y       row
   @param name    its name, or None for a free one
   @param fields  its fields (see FIELDS)
   @return its local ID
   """
   items = doc.data.get("objects")
   if items is not None and not isinstance(items, list):
      raise DocumentError('"objects" must be a list; fix the map file by hand')
   if len(objects(doc)) >= max_objects(doc):
      view = "" if doc.data.get("object_view") is not None else "; an object view allows more"
      raise DocumentError(f"this map has at most {max_objects(doc)} objects (sprite slots 1-15; the walker has slot "
                          f"0){view}")
   name = free_name(doc) if name is None else name
   _check_name(name)
   if any(isinstance(o, dict) and o.get("name") == name for o in objects(doc)):
      raise DocumentError(f"another object is named {name!r}")
   o = {"name": name, "at": [int(x), int(y)], "sprite": DEFAULT_SPRITE}
   doc.data.setdefault("objects", []).append(o)
   if fields:
      set_object(doc, len(doc.data["objects"]) - 1, **fields)
   return len(doc.data["objects"]) - 1


def set_object(doc: Document, index: int, **fields: JsonValue) -> None:
   """!Changes an object's fields; None removes one (call inside doc.edit()).
   "sight" and "until" are the spotter's; sight 0 (or None) makes it no
   spotter. Movement "custom" without a route gets DEFAULT_ROUTE; a route
   given without a movement makes the movement custom.
   @param doc     map Document
   @param index   local ID
   @param fields  fields to change
   @return None
   """
   o = _get(doc, index)
   bad = sorted(set(fields) - set(FIELDS))
   if bad:
      raise DocumentError(f"an object has no field(s) {', '.join(bad)} (known: {', '.join(FIELDS)})")
   for k, v in fields.items():
      if k == "sprite" and v is None:
         raise DocumentError("an object needs a sprite")
      if v is not None:
         v = _check(k, v)
      if k in SPOTTER_FIELDS:
         t = o.get("spotter") if isinstance(o.get("spotter"), dict) else {}
         if v is None:
            t.pop(k, None)
         else:
            t[k] = v
         if t.get("sight"):
            o["spotter"] = t
         else:
            o.pop("spotter", None)   # no sight: no spotter (and no until flag)
         continue
      if v is None:
         o.pop(k, None)
      else:
         o[k] = v
   if "route" in fields and "movement" not in fields:
      if fields["route"] is not None:
         o["movement"] = "custom"
      elif o.get("movement") == "custom":
         del o["movement"]   # no route: no custom movement
   if o.get("movement") == "custom" and "route" not in o:
      o["route"] = dict(DEFAULT_ROUTE)
   _tidy(o)


def _target(doc: Document, index: int, page: int | None) -> JsonDict:
   """!An object, or one of its pages.
   @param doc    map Document
   @param index  local ID
   @param page   page index, or None for the object itself
   @return the dict
   """
   if page is None:
      return _get(doc, index)
   pgs = pages(doc, index)
   if not 0 <= page < len(pgs) or not isinstance(pgs[page], dict):
      raise DocumentError(f"object {index} has no page {page}")
   return pgs[page]


def set_route(doc: Document, index: int, steps: str | Sequence[str] | None, repeat: bool | None = None,
              skip: bool | None = None, page: int | None = None) -> None:
   """!Sets or removes the move route of an object or one of its pages (call inside doc.edit()).
   Steps are checked with the engine's route_compiler (flags by the build).
   A route makes the movement custom; removing it makes a custom movement
   static (or, on a page, no longer replaced).
   @param doc     map Document
   @param index   local ID
   @param steps   list of steps, or text with one step per line; None removes the route
   @param repeat  start over at the end (None: keep, default true)
   @param skip    skip blocked steps (None: keep, default false)
   @param page    page index, or None for the object itself
   @return None
   """
   t = _target(doc, index, page)
   if steps is None:
      t.pop("route", None)
      if t.get("movement") == "custom":
         del t["movement"]
      if page is None:
         _tidy(t)
      return
   old = t.get("route") if isinstance(t.get("route"), dict) else {}
   rt = {"steps": route_steps(steps),
         "repeat": old.get("repeat", True) if repeat is None else repeat,
         "skip": old.get("skip", False) if skip is None else skip}
   t["route"] = _check("route", rt)
   t["movement"] = "custom"
   if page is None:
      _tidy(t)
   else:
      _tidy_page(t)


def set_option(doc: Document, index: int, option: str, value: bool | None, page: int | None = None) -> None:
   """!Sets one movement option of an object or page (call inside doc.edit()).
   @param doc     map Document
   @param index   local ID
   @param option  a key of OPTIONS
   @param value   True / False, or None for the default (on a page: the page's options start from the defaults)
   @param page    page index, or None for the object itself
   @return None
   """
   if option not in OPTIONS:
      raise DocumentError(f"no option {option!r} (options: {', '.join(OPTIONS)})")
   if value is not None and not isinstance(value, bool):
      raise DocumentError(f"option {option} is true or false")
   t = _target(doc, index, page)
   opts = t.get("options") if isinstance(t.get("options"), dict) else {}
   if value is None:
      opts.pop(option, None)
   else:
      opts[option] = value
   t["options"] = opts
   if page is None:
      _tidy(t)


def rename_object(doc: Document, index: int, name: str) -> None:
   """!Renames an object (call inside doc.edit()). world_ids.h names follow; scripts use local IDs.
   @param doc    map Document
   @param index  local ID
   @param name   new name
   @return None
   """
   o = _get(doc, index)
   _check_name(name)
   if any(isinstance(other, dict) and other.get("name") == name for i, other in enumerate(objects(doc))
          if i != index):
      raise DocumentError(f"another object is named {name!r}")
   o["name"] = name


def move_object(doc: Document, index: int, x: int, y: int) -> None:
   """!Moves an object to another cell (call inside doc.edit()).
   @param doc    map Document
   @param index  local ID
   @param x      column
   @param y      row
   @return None
   """
   _get(doc, index)["at"] = [int(x), int(y)]


def remove_object(doc: Document, index: int) -> list[str | None]:
   """!Removes an object (call inside doc.edit()).
   @param doc    map Document
   @param index  local ID
   @return the names of the objects whose local IDs went down by one (scripts naming them by number must follow)
   """
   _get(doc, index)
   items = doc.data["objects"]
   shifted = [o.get("name") for o in items[index + 1:] if isinstance(o, dict)]
   del items[index]
   if not items:
      del doc.data["objects"]
   return shifted


# -- pages ----------------------------------------------------------------------------------------

def pages(doc: Document, index: int) -> list[JsonDict]:
   """!An object's event pages (the last whose conditions all hold is active).
   @param doc    map Document
   @param index  local ID
   @return list of page dicts
   """
   pgs = _get(doc, index).get("pages")
   return pgs if isinstance(pgs, list) else []


def _set_when(pg: JsonDict, conds: Mapping[str, JsonValue]) -> None:
   """!Applies condition changes to a page (None removes one).
   @param pg     the page (changed in place)
   @param conds  {key of WHEN_FIELDS: value or None}
   @return None
   """
   bad = sorted(set(conds) - set(WHEN_FIELDS))
   if bad:
      raise DocumentError(f"page conditions have no {', '.join(bad)} (known: {', '.join(WHEN_FIELDS)})")
   when = dict(pg.get("when") or {}) if isinstance(pg.get("when"), dict) else {}
   for k, v in conds.items():
      if v is None or (k == "equal" and v is False) or (k == "self" and v in ([], "")):
         when.pop(k, None)
         continue
      if k in ("flag", "var"):
         if not isinstance(v, str) or not v:
            raise DocumentError(f"a page's {k} is a name from the scripts manifest")
      elif k == "value":
         _int(v, VALUE_MIN, VALUE_MAX, "a page's value")
      elif k == "equal":
         if v is not True:
            raise DocumentError("a page's equal is true or false")
      elif k == "self":
         letters = [v] if isinstance(v, str) else v
         if not isinstance(letters, (list, tuple)) or any(s not in SELF_SWITCHES for s in letters):
            raise DocumentError("a page's self switches are A, B, C or D (or a list of them)")
         letters = [s for s in SELF_SWITCHES if s in letters]
         v = letters[0] if len(letters) == 1 else letters
      when[k] = v
   if "var" not in when:
      when.pop("value", None)
      when.pop("equal", None)
   elif "value" not in when:
      when["value"] = 1   # a variable without a value is compared with 1
   if not any(k in when for k in ("flag", "var", "self")):
      raise DocumentError("a page needs a condition: a flag, a variable or self switches")
   pg["when"] = when


def _tidy_page(pg: JsonDict) -> None:
   """!A hidden page holds nothing else; a range or route the page's movement does not use goes.
   @param pg  the page (changed in place)
   @return None
   """
   if pg.get("hidden"):
      for k in list(pg):
         if k not in ("when", "hidden"):
            del pg[k]
      return
   pg.pop("hidden", None)
   if "movement" in pg and pg["movement"] not in RANGED:
      pg.pop("range", None)
   if "movement" in pg and pg["movement"] != "custom":
      pg.pop("route", None)
   _tidy_args(pg, pg.get("movement"))
   if pg.get("movement") == "custom" and "route" not in pg:
      pg["route"] = dict(DEFAULT_ROUTE)


def _set_page_fields(pg: JsonDict, fields: Mapping[str, JsonValue]) -> None:
   """!Applies page fields (None removes one: the object's value applies).
   @param pg      the page (changed in place)
   @param fields  {key of PAGE_FIELDS: value or None}
   @return None
   """
   bad = sorted(set(fields) - set(PAGE_FIELDS))
   if bad:
      raise DocumentError(f"a page has no field(s) {', '.join(bad)} (known: {', '.join(PAGE_FIELDS)})")
   if fields.get("hidden") is False:
      fields = dict(fields, hidden=None)
   for k, v in fields.items():
      if v is None:
         pg.pop(k, None)
         continue
      pg[k] = _check(k, v)
      if k != "hidden":
         pg.pop("hidden", None)   # a page that replaces a field shows the object
   if "route" in fields and "movement" not in fields:
      if fields["route"] is not None:
         pg["movement"] = "custom"
      elif pg.get("movement") == "custom":
         del pg["movement"]
   _tidy_page(pg)


def add_page(doc: Document, index: int, when: Mapping[str, JsonValue], **fields: JsonValue) -> int:
   """!Adds a page after the object's others (call inside doc.edit()).
   @param doc     map Document
   @param index   local ID
   @param when    its conditions {flag, var, value, equal, self} (at least a flag, a variable or self switches)
   @param fields  what it replaces (see PAGE_FIELDS), or hidden=True
   @return its index
   """
   o = _get(doc, index)
   if len(pages(doc, index)) >= MAX_PAGES:
      raise DocumentError(f"an object has at most {MAX_PAGES} pages")
   if not isinstance(when, dict):
      raise DocumentError("a page's conditions are an object: {flag, var, value, equal, self}")
   pg = {}
   _set_when(pg, when)
   _set_page_fields(pg, fields)
   if not isinstance(o.get("pages"), list):
      o["pages"] = []
   o["pages"].append(pg)
   return len(o["pages"]) - 1


def set_page(doc: Document, index: int, which: int, when: Mapping[str, JsonValue] | None = None,
             **fields: JsonValue) -> None:
   """!Changes a page; None removes a field or condition (call inside doc.edit()).
   @param doc     map Document
   @param index   local ID
   @param which   page index
   @param when    condition changes {key: value or None}, or None to keep them
   @param fields  fields to change (see PAGE_FIELDS)
   @return None
   """
   pg = _target(doc, index, which)
   if when is not None:
      _set_when(pg, when)
   _set_page_fields(pg, fields)


def move_page(doc: Document, index: int, which: int, to: int) -> None:
   """!Moves a page to another place in the list (call inside doc.edit()). Later pages win.
   @param doc    map Document
   @param index  local ID
   @param which  page index
   @param to     its new index
   @return None
   """
   pgs = pages(doc, index)
   if not 0 <= which < len(pgs):
      raise DocumentError(f"object {index} has no page {which}")
   if not 0 <= to < len(pgs):
      raise DocumentError(f"a page index is 0-{len(pgs) - 1}")
   pgs.insert(to, pgs.pop(which))


def remove_page(doc: Document, index: int, which: int) -> None:
   """!Removes a page (call inside doc.edit()).
   @param doc    map Document
   @param index  local ID
   @param which  page index
   @return None
   """
   pgs = pages(doc, index)
   if not 0 <= which < len(pgs):
      raise DocumentError(f"object {index} has no page {which}")
   del pgs[which]
   if not pgs:
      del _get(doc, index)["pages"]


def pages_from_overrides(o: JsonDict) -> int:
   """!Turns an object's old "overrides" (the first whose flag is set
   applies) into pages (the last whose conditions hold applies): each
   {flag, ...} becomes {"when": {"flag"}, ...}, in reverse order, after the
   object's pages.
   @param o  the object (changed in place)
   @return how many overrides were turned into pages
   """
   ovs = o.pop("overrides", None)
   if not isinstance(ovs, list):
      return 0
   new = []
   for ov in reversed(ovs):
      if not isinstance(ov, dict) or "flag" not in ov:
         continue
      pg = {"when": {"flag": ov["flag"]}}
      pg.update({k: v for k, v in ov.items() if k != "flag"})
      new.append(pg)
   if new:
      o["pages"] = (o.get("pages") if isinstance(o.get("pages"), list) else []) + new
   return len(new)


def sight_cells(o: JsonDict) -> list[tuple[int, int]]:
   """!The cells a spotter looks at (its facing, up to its sight).
   @param o  the object
   @return list of (x, y); [] for objects that are no spotter
   """
   t = o.get("spotter")
   at = o.get("at")
   if not (isinstance(t, dict) and isinstance(t.get("sight"), int) and isinstance(at, list) and len(at) == XY_ENTRIES):
      return []
   d = o.get("facing", "down")
   dx, dy = {"down": (0, 1), "up": (0, -1), "left": (-1, 0), "right": (1, 0)}.get(d, (0, 1))
   return [(at[0] + dx * k, at[1] + dy * k) for k in range(1, t["sight"] + 1)]


def game_sprites(project: Project) -> set[str] | None:
   """!The sprite references of the game's assets manifest (project.json "assets").
   @param project  Project
   @return set of 'sprite:NAME' (canonical upper case), or None when no game manifest is known
   """
   import json
   from ..plugins.project import find_project
   manifest, folder = find_project(project.world.path)
   if manifest is None:
      return None
   try:
      rel = json.loads(Path(manifest).read_text(encoding="utf-8")).get("assets")
      if not isinstance(rel, str) or not rel:
         return None
      data = json.loads((Path(folder) / rel).read_text(encoding="utf-8"))
   except (OSError, ValueError):
      return None
   out = set()
   for a in data.get("assets", []) if isinstance(data, dict) else []:
      key = a.get("key") if isinstance(a, dict) else None
      if isinstance(key, str) and key.lower().startswith("sprite:"):
         out.add(_canon(key))
   return out


def _canon(ref: str) -> str:
   """!An asset reference in its canonical form (namespace kept, name upper case, spaces folded).
   @param ref  'sprite:Name'
   @return 'sprite:NAME'
   """
   ns, _sep, name = ref.partition(":")
   return f"{ns}:{' '.join(name.upper().split())}"


def check(project: Project) -> str | None:
   """!Compiles the world's events and objects with the engine's rules, on the open documents.
   @param project  Project
   @return error message, or None when they compile
   """
   return events.check(project)


def diagnostics(project: Project, name: str | None = None) -> list[Diagnostic]:
   """!Object problems: what the build would reject, objects on cells with
   collision, sprites the game's assets manifest lacks (invisible in game),
   and objects standing on warps.
   @param project  Project
   @param name     only this map, or None for all
   @return list of plugins.Diagnostic
   """
   from ..plugins.registry import Diagnostic
   from . import maps
   out = []
   error = check(project)
   # Only errors about objects are reported here; events report the rest.
   if error and re.search(r"object ['\d]|objects;|object pages|move routes|self switches|OBJ_", error):
      out.append(Diagnostic("error", error, name))
   sprites = game_sprites(project)
   for n in [name] if name else project.map_names():
      doc = project.map(n)
      warps = {tuple(w.get("at")) for w in events.events(doc, "warps")
               if isinstance(w.get("at"), list) and len(w.get("at")) == XY_ENTRIES}
      seen: dict[tuple[int, int], str] = {}
      for i, o in enumerate(objects(doc)):
         if not isinstance(o, dict):
            continue
         at = o.get("at")
         if not (isinstance(at, list) and len(at) == XY_ENTRIES):
            continue
         label = f"map {n}: object {i} ({o.get('name')})"
         if tuple(at) in seen and doc.data.get("stacked_objects") is True:   # allowed, worth knowing
            out.append(Diagnostic("info", f"{label} shares its cell with {seen[tuple(at)]} (stacked objects: the "
                                          "game's flags keep one there at a time)", n, tuple(at)))
         seen.setdefault(tuple(at), str(o.get("name")))
         cell = maps.get(doc.data, at[0], at[1])
         if cell is not None and maps.unpack(cell)["collision"]:
            out.append(Diagnostic("warning", f"{label} stands on a cell with collision", n, tuple(at)))
         opts = o.get("options")
         # A "through" object does not block the walker, so it neither stays solid when invisible nor hides a warp.
         through = isinstance(opts, dict) and opts.get("through") is True
         spr = o.get("sprite")
         if sprites is not None and isinstance(spr, str) and _canon(spr) not in sprites:
            solid = "the walker passes through it" if through else "but still solid"
            out.append(Diagnostic("warning", f"{label}: the game's assets have no {spr}; it would be invisible "
                                             f"({solid})", n, tuple(at)))
         if tuple(at) in warps and not through:
            out.append(Diagnostic("info", f"{label} stands on a warp, which the walker cannot reach while "
                                          "it is there", n, tuple(at)))
   return out


def _route_flags(src: JsonDict) -> list[str]:
   """!The flags a route's set / clear steps name.
   @param src  object or page
   @return list of names
   """
   rt = src.get("route")
   steps = rt.get("steps") if isinstance(rt, dict) else None
   out = []
   for step in steps if isinstance(steps, list) else []:
      words = step.split() if isinstance(step, str) else []
      if len(words) == FLAG_STEP_WORDS and words[0] in ("set", "clear"):
         out.append(words[1])
   return out


def import_objects(data: JsonDict, known: Mapping[str, Any] | None) -> int:
   """!Keeps a map's objects whose scripts, flags and variables the target
   world has (the importer calls this). Old "overrides" become pages first
   (pages_from_overrides()).
   @param data   map manifest (changed in place)
   @param known  events.names() of the target world, or None when it has no scripts manifest
   @return how many objects were left out
   """
   items = data.get("objects")
   if items is None:
      return 0
   if not isinstance(items, list):
      del data["objects"]
      return 1
   kept, dropped = [], 0
   for o in items:
      if not isinstance(o, dict):
         dropped += 1
         continue
      pages_from_overrides(o)
      names = [("scripts", o.get("script")), ("flags", o.get("flag"))]
      names += [("flags", f) for f in _route_flags(o)]
      t = o.get("spotter")
      if isinstance(t, dict):
         names.append(("flags", t.get("until")))
      for pg in o.get("pages") or []:
         if isinstance(pg, dict):
            when = pg.get("when") if isinstance(pg.get("when"), dict) else {}
            names += [("flags", when.get("flag")), ("vars", when.get("var")), ("scripts", pg.get("script"))]
            names += [("flags", f) for f in _route_flags(pg)]
      needs = [(k, v) for k, v in names if v is not None]
      if needs and (known is None or not all(isinstance(v, str) and v in known[k] for k, v in needs)):
         dropped += 1
         continue
      kept.append(o)
   if kept:
      data["objects"] = kept
   else:
      del data["objects"]
   return dropped
