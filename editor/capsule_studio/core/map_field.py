"""!The world's and the maps' field action parts (engine F2, D-27 section 3): what field actions target and the
mechanisms their scripts use.

    world.json  "object_kinds": ["bush"], "map_tags": ["dark"],
                "flight_points": [{"name": "park", "label": "Showcase Park", "map": "showcase", "x": 5, "y": 8,
                                   "facing": "down"}]
    map.json    "darkness": 3, "tags": ["dark"], "escape_point": true
    objects     {"name": "bush", ..., "kind": "bush"}   (core.objects: the "kind" field)

Object kinds and map tags are the names a battle structure's field_actions target (core.structure.field_actions);
a map's darkness is how dark it is on entering (0 lit to the world's darkest level; scripts' `darkness N;` change it
until the next map, kept across a save), what each level looks like is the world's "darkness_levels" (C8: the lit
box's half size and the brightness outside it; the engine's defaults while it states none), its
tags make menu actions available on it, and escape_point marks it outdoors (a warp from it to a map without
records the escape point scripts' `escape;` returns to). Flight points are the places a flight menu lists once a
script recorded them. Every limit and check is the engine's map compiler (object_kinds(), map_tags(),
compile_flight_points(), map_field_rules(), MAX_DARKNESS, MAX_MAP_TAGS, MAX_OBJECT_KINDS, MAX_FLIGHT_POINTS,
DIRECTIONS).

Each helper is one change: call it inside one edit() of the world (or map) Document. A rename of a kind or tag
follows the maps of the world (their objects' kinds, their tags) and, when the world is saved, the game's battle
field actions targeting it (C8: follow_saved_renames()); a removal is refused while a map or a field action uses
it; an edit the engine refuses is refused with its message.
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from . import engine, manifest_io
from .document import Document, DocumentError

if TYPE_CHECKING:
   from .world import Project

## A parsed JSON object.
JsonDict = dict[str, Any]

## The world's object kinds.
KINDS_KEY = "object_kinds"
## The world's map tags.
TAGS_KEY = "map_tags"
## The world's flight points.
FLIGHTS_KEY = "flight_points"
## A map's darkness level.
DARKNESS_KEY = "darkness"
## C8: the world's darkness levels ([{"lit", "brightness"}]; map_compiler darkness_levels()).
LEVELS_KEY = "darkness_levels"
## A darkness level's fields, in manifest order.
LEVEL_FIELDS = ("lit", "brightness")
## A map's tags.
MAP_TAGS_KEY = "tags"
## A map's escape point flag.
ESCAPE_KEY = "escape_point"
## An object's kind.
OBJECT_KIND_KEY = "kind"
## The battle field actions' target kind of each world list (battlec/field.py TARGET_KINDS).
TARGET_KINDS = {KINDS_KEY: "object", TAGS_KEY: "tag"}
## A flight point's fields, in manifest order.
FLIGHT_FIELDS = ("name", "label", "map", "x", "y", "facing")
## The facing a flight point lands with when it states none (the engine's default).
DEFAULT_FACING = "down"
## Where the map compiler's messages point.
WHERE = "map"


def _mc() -> Any:
   """!The engine's map compiler.
   @return module
   """
   return engine.tool("map_compiler")


def max_darkness() -> int:
   """!The most darkness levels a world may define (the engine's MAX_DARKNESS).
   @return it
   """
   return int(_mc().MAX_DARKNESS)


def max_lit() -> int:
   """!The widest lit box half size of a darkness level (the engine's MAX_LIT_HALF, pixels).
   @return it
   """
   return int(_mc().MAX_LIT_HALF)


def max_brightness() -> int:
   """!The darkest brightness of a darkness level (the engine's MAX_DARK_BRIGHTNESS).
   @return it
   """
   return int(_mc().MAX_DARK_BRIGHTNESS)


def darkness_levels(world: Document | None) -> list[JsonDict]:
   """!The world's darkness levels (C8: the world's data; the engine's defaults when it states none).
   @param world  world Document, or None
   @return [{"lit", "brightness"}] in level order (level n is entry n - 1); [] when they do not compile
   """
   if world is None:
      return []
   try:
      return _mc().darkness_levels(world.data)
   except Exception:   # the map compiler's ManifestError
      return []


def levels_default(world: Document) -> bool:
   """!Whether the world states no darkness levels (the engine's defaults apply).
   @param world  world Document
   @return True when it states none
   """
   return LEVELS_KEY not in world.data


def darkest(world: Document | None) -> int:
   """!The world's darkest level (a map's darkness and scripts' `darkness N;` go up to it).
   @param world  world Document, or None
   @return it (0: every map lit)
   """
   return len(darkness_levels(world))


def max_tags() -> int:
   """!The most map tags of a world (the engine's MAX_MAP_TAGS).
   @return it
   """
   return int(_mc().MAX_MAP_TAGS)


def max_kinds() -> int:
   """!The most object kinds of a world (the engine's MAX_OBJECT_KINDS).
   @return it
   """
   return int(_mc().MAX_OBJECT_KINDS)


def max_flight_points() -> int:
   """!The most flight points of a world (the engine's MAX_FLIGHT_POINTS).
   @return it
   """
   return int(_mc().MAX_FLIGHT_POINTS)


def max_flight_label() -> int:
   """!The longest flight point label (the engine's MAX_FLIGHT_LABEL, letters).
   @return it
   """
   return int(_mc().MAX_FLIGHT_LABEL)


def coord_range() -> tuple[int, int]:
   """!The cells a flight point may land on (the engine's MIN_COORD and MAX_COORD).
   @return (lowest, highest)
   """
   return int(_mc().MIN_COORD), int(_mc().MAX_COORD)


def directions() -> list[str]:
   """!The facings a flight point may land with (the engine's DIRECTIONS).
   @return names
   """
   return list(_mc().DIRECTIONS)


def object_kinds(world: Document) -> list[str]:
   """!The world's object kinds.
   @param world  world Document
   @return names ([] when it states none or they do not compile)
   """
   try:
      return _mc().object_kinds(world.data)
   except Exception:   # the map compiler's ManifestError
      return []


def map_tags(world: Document) -> list[str]:
   """!The world's map tags.
   @param world  world Document
   @return names ([] when it states none or they do not compile)
   """
   try:
      return _mc().map_tags(world.data)
   except Exception:   # the map compiler's ManifestError
      return []


def check(world: Document) -> str | None:
   """!What the engine's map compiler says about the world's F2 lists.
   @param world  world Document
   @return the message, or None when they compile
   """
   mc = _mc()
   try:
      mc.object_kinds(copy.deepcopy(world.data))
      mc.map_tags(copy.deepcopy(world.data))
      mc.darkness_levels(copy.deepcopy(world.data))
      mc.compile_flight_points(copy.deepcopy(world.data), list((world.data.get("maps") or {}).keys()))
   except Exception as e:   # ManifestError, type errors in odd data
      return str(e)
   return None


def _guarded(world: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the lists compiled before and do not after.
   @param world   world Document
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   before = check(world)
   result = change()
   if before is None:
      error = check(world)
      if error is not None:
         raise DocumentError(error)
   return result


def _names_live(world: Document, key: str) -> list[str]:
   """!A name list of the world for editing (written when it states none).
   @param world  world Document
   @param key    KINDS_KEY or TAGS_KEY
   @return the live list
   """
   if not isinstance(world.data.get(key), list):
      world.data[key] = []
   return world.data[key]


def _maps(project: Project) -> list[tuple[str, Document]]:
   """!The world's maps as Documents.
   @param project  the world's Project
   @return (name, Document) pairs, world order (unreadable maps are left out)
   """
   out = []
   for name in (project.world.data.get("maps") or {}):
      try:
         out.append((name, project.map(name)))
      except (DocumentError, OSError, ValueError, KeyError):
         continue
   return out


def kind_users(project: Project, kind: str) -> list[str]:
   """!The maps' objects of a kind.
   @param project  the world's Project
   @param kind     the kind
   @return "MAP: OBJECT" strings
   """
   return [f"{n}: {o.get('name')}" for n, doc in _maps(project) for o in doc.data.get("objects") or []
           if isinstance(o, dict) and o.get(OBJECT_KIND_KEY) == kind]


def tag_users(project: Project, tag: str) -> list[str]:
   """!The maps carrying a tag.
   @param project  the world's Project
   @param tag      the tag
   @return map names
   """
   return [n for n, doc in _maps(project) if tag in (doc.data.get(MAP_TAGS_KEY) or [])]


def add_name(project: Project, key: str, name: str) -> None:
   """!Adds an object kind or a map tag.
   @param project  the world's Project
   @param key      KINDS_KEY or TAGS_KEY
   @param name     the new name
   @return None
   """
   name = name.strip() if isinstance(name, str) else ""
   if not name:
      raise DocumentError("a name is needed")
   live = _names_live(project.world, key)
   if name in live:
      raise DocumentError(f"there is already {name!r} in {key}")
   _guarded(project.world, lambda: live.append(name))


def remove_name(project: Project, key: str, name: str) -> None:
   """!Removes an object kind or a map tag (refused while a map or a battle field action uses it).
   @param project  the world's Project
   @param key      KINDS_KEY or TAGS_KEY
   @param name     the name
   @return None
   """
   live = _names_live(project.world, key)
   if name not in live:
      raise DocumentError(f"no {name!r} in {key}")
   users = kind_users(project, name) if key == KINDS_KEY else tag_users(project, name)
   # C8: the game's battle field actions targeting it count too
   from .structure import field_actions   # local: core.structure imports core modules
   users += field_actions.world_target_users(project.world.path, TARGET_KINDS[key], name)
   if users:
      raise DocumentError(f"{name!r} is used by {', '.join(users)}")
   _guarded(project.world, lambda: live.remove(name))


def rename_name(project: Project, key: str, old: str, new: str) -> list[str]:
   """!Renames an object kind or a map tag; the maps using it follow (one undo step with the world's). C8: the
   game's battle field actions targeting it follow when the world is saved (core.world.Project's saves:
   follow_saved_renames()), so the battle data on disk always names what the world on disk names.
   @param project  the world's Project
   @param key      KINDS_KEY or TAGS_KEY
   @param old      the name
   @param new      the new name
   @return the maps changed
   """
   new = new.strip() if isinstance(new, str) else ""
   live = _names_live(project.world, key)
   if old not in live:
      raise DocumentError(f"no {old!r} in {key}")
   if not new or (new != old and new in live):
      raise DocumentError(f"{new!r} is empty or taken")
   _guarded(project.world, lambda: live.__setitem__(live.index(old), new))
   changed = []
   for name, doc in _maps(project):
      if key == KINDS_KEY:
         hits = [o for o in doc.data.get("objects") or [] if isinstance(o, dict) and o.get(OBJECT_KIND_KEY) == old]
         if hits:
            with doc.edit("Rename object kind"):
               for o in hits:
                  o[OBJECT_KIND_KEY] = new
            changed.append(name)
      elif old in (doc.data.get(MAP_TAGS_KEY) or []):
         with doc.edit("Rename map tag"):
            tags = doc.data[MAP_TAGS_KEY]
            tags[tags.index(old)] = new
         changed.append(name)
   return changed


def saved_names(world: Document) -> dict[str, list[str]]:
   """!The object kinds and map tags of the world file on disk (before a save: what the battle data names).
   @param world  world Document
   @return {KINDS_KEY: names, TAGS_KEY: names} ({} lists when the file does not read)
   """
   try:
      data = manifest_io.load(world.path) if world.path is not None and world.path.is_file() else {}
   except (OSError, ValueError):
      data = {}
   out = {}
   for key in TARGET_KINDS:
      raw = data.get(key) if isinstance(data, dict) else None
      out[key] = [n for n in raw if isinstance(n, str)] if isinstance(raw, list) else []
   return out


def saved_renames(before: dict[str, list[str]], after: dict[str, list[str]]) -> list[tuple[str, str, str]]:
   """!The renames between two saves of the world's object kinds and map tags: a rename keeps its place in the list
   (rename_name()), so a name at a place whose old name is gone and whose new name is new is one (additions and
   removals move places and match nothing; a removal is refused while a field action targets it).
   @param before  saved_names() before the save
   @param after   saved_names() after it
   @return (KINDS_KEY or TAGS_KEY, old, new) per rename
   """
   out = []
   for key in TARGET_KINDS:
      old, new = before.get(key, []), after.get(key, [])
      if len(old) != len(new):
         continue
      out += [(key, a, b) for a, b in zip(old, new) if a != b and a not in new and b not in old]
   return out


def follow_saved_renames(project: Project, before: dict[str, list[str]]) -> list[str]:
   """!C8 (F2's open item): after the world file is saved, the game's battle field actions follow the object kinds
   and map tags it renamed (core.structure.field_actions.follow_world_rename(): the battle data saved).
   @param project  the world's Project
   @param before   saved_names() before the save
   @return "field action NAME: OLD -> NEW" per record rewritten
   """
   from .structure import field_actions   # local: core.structure imports core modules
   out = []
   for key, old, new in saved_renames(before, saved_names(project.world)):
      out += [f"{place}: {old} -> {new}"
              for place in field_actions.follow_world_rename(project.world.path, TARGET_KINDS[key], old, new)]
   return out


# -- a map's darkness, tags and escape point -------------------------------------------------------------------------

def map_rules(map_doc: Document, world: Document) -> tuple[int, list[str], bool]:
   """!A map's F2 properties as the page shows them.
   @param map_doc  map Document
   @param world    its world Document
   @return (darkness, tag names, escape point)
   """
   d = map_doc.data
   darkness = d.get(DARKNESS_KEY, 0)
   tags = d.get(MAP_TAGS_KEY)
   return (darkness if isinstance(darkness, int) else 0, [t for t in tags if isinstance(t, str)]
           if isinstance(tags, list) else [], d.get(ESCAPE_KEY) is True)


def _map_guarded(map_doc: Document, world: Document, change: Callable[[], None]) -> None:
   """!Runs a change to a map's F2 properties; refused with the engine's message (map_field_rules()).
   @param map_doc  map Document
   @param world    its world Document
   @param change   the change
   @return None
   """
   change()
   try:
      _mc().map_field_rules(map_doc.data, map_tags(world), WHERE, darkest(world))
   except Exception as e:   # ManifestError
      raise DocumentError(str(e)) from None


def set_darkness(map_doc: Document, world: Document, level: int) -> None:
   """!Sets how dark a map is on entering (0: lit, the key goes).
   @param map_doc  map Document
   @param world    its world Document
   @param level    0 to darkest(world)
   @return None
   """
   def change() -> None:
      """!Writes it."""
      if level == 0:
         map_doc.data.pop(DARKNESS_KEY, None)
      else:
         map_doc.data[DARKNESS_KEY] = level
   _map_guarded(map_doc, world, change)


# -- the world's darkness levels (C8) ----------------------------------------------------------------------------------

def _levels_live(world: Document) -> list[JsonDict]:
   """!The world's darkness levels for editing (the defaults written out when it states none).
   @param world  world Document
   @return the live list
   """
   if not isinstance(world.data.get(LEVELS_KEY), list):
      world.data[LEVELS_KEY] = copy.deepcopy(darkness_levels(world))
   return world.data[LEVELS_KEY]


def level_users(project: Project, level: int) -> list[str]:
   """!The maps at a darkness level or darker (a level the world drops would leave them too dark to compile).
   @param project  the world's Project
   @param level    1 up
   @return map names
   """
   return [n for n, doc in _maps(project) if map_rules(doc, project.world)[0] >= level]


def add_darkness_level(world: Document, lit: int, brightness: int) -> int:
   """!Adds a darkest level after the others.
   @param world       world Document
   @param lit         the lit box's half size, pixels
   @param brightness  how dark the rest goes (0-16)
   @return its level number
   """
   live = _levels_live(world)
   _guarded(world, lambda: live.append({"lit": lit, "brightness": brightness}))
   return len(live)


def set_darkness_level(world: Document, level: int, key: str, value: int) -> None:
   """!Changes one field of a darkness level.
   @param world  world Document
   @param level  1 up
   @param key    one of LEVEL_FIELDS
   @param value  the value (the engine checks its range)
   @return None
   """
   if key not in LEVEL_FIELDS:
      raise DocumentError(f"a darkness level has {', '.join(LEVEL_FIELDS)}")
   live = _levels_live(world)
   if not 1 <= level <= len(live):
      raise DocumentError(f"no darkness level {level} (1 to {len(live)})")
   _guarded(world, lambda: live[level - 1].__setitem__(key, value))


def remove_darkness_level(project: Project) -> None:
   """!Removes the darkest level (refused while a map is that dark).
   @param project  the world's Project
   @return None
   """
   live = _levels_live(project.world)
   if not live:
      raise DocumentError("the world has no darkness levels")
   users = level_users(project, len(live))
   if users:
      raise DocumentError(f"darkness level {len(live)} is used by {', '.join(users)}")
   _guarded(project.world, live.pop)


def set_tags(map_doc: Document, world: Document, tags: list[str]) -> None:
   """!Sets the tags a map carries (none: the key goes).
   @param map_doc  map Document
   @param world    its world Document
   @param tags     names of map_tags()
   @return None
   """
   def change() -> None:
      """!Writes them."""
      if tags:
         map_doc.data[MAP_TAGS_KEY] = list(tags)
      else:
         map_doc.data.pop(MAP_TAGS_KEY, None)
   _map_guarded(map_doc, world, change)


def set_escape_point(map_doc: Document, world: Document, on: bool) -> None:
   """!Sets whether a map is an escape point (outdoors).
   @param map_doc  map Document
   @param world    its world Document
   @param on       on or off (off: the key goes)
   @return None
   """
   def change() -> None:
      """!Writes it."""
      if on:
         map_doc.data[ESCAPE_KEY] = True
      else:
         map_doc.data.pop(ESCAPE_KEY, None)
   _map_guarded(map_doc, world, change)


# -- flight points ---------------------------------------------------------------------------------------------------

def flight_points(world: Document) -> list[JsonDict]:
   """!The world's flight points with the engine's defaults filled in.
   @param world  world Document
   @return records {"name", "label", "map", "x", "y", "facing"} ([] when they do not compile)
   """
   mc = _mc()
   try:
      rows = mc.compile_flight_points(copy.deepcopy(world.data), list((world.data.get("maps") or {}).keys()))
   except Exception:   # ManifestError
      return []
   dirs = directions()
   return [{**r, "facing": dirs[r["facing"]]} for r in rows]


def _flights_live(world: Document) -> list[JsonDict]:
   """!The flight point list for editing.
   @param world  world Document
   @return the live list
   """
   if not isinstance(world.data.get(FLIGHTS_KEY), list):
      world.data[FLIGHTS_KEY] = []
   return world.data[FLIGHTS_KEY]


def _flight(world: Document, name: str) -> JsonDict:
   """!One flight point (live).
   @param world  world Document
   @param name   its name
   @return the record
   @throws DocumentError when there is none
   """
   for f in _flights_live(world):
      if isinstance(f, dict) and f.get("name") == name:
         return f
   raise DocumentError(f"no flight point {name!r}")


def add_flight_point(world: Document, name: str, map_name: str, x: int, y: int, label: str | None = None,
                     facing: str = DEFAULT_FACING) -> None:
   """!Adds a flight point.
   @param world     world Document
   @param name      its name (an identifier; the script compiler gives it the flag flight_NAME)
   @param map_name  the map it lands on
   @param x         landing column
   @param y         landing row
   @param label     what the flight menu shows (None: the name)
   @param facing    one of directions()
   @return None
   """
   live = _flights_live(world)
   if any(isinstance(f, dict) and f.get("name") == name for f in live):
      raise DocumentError(f"there is already a flight point {name!r}")
   if len(live) >= max_flight_points():
      raise DocumentError(f"at most {max_flight_points()} flight points")
   rec: JsonDict = {"name": name}
   if label and label != name:
      rec["label"] = label
   rec.update({"map": map_name, "x": x, "y": y})
   if facing != DEFAULT_FACING:
      rec["facing"] = facing
   _guarded(world, lambda: live.append(rec))
   if check(world) is not None:
      error = check(world)
      live.remove(rec)
      raise DocumentError(error or "refused")


def set_flight_point(world: Document, name: str, key: str, value: Any) -> None:
   """!Changes one field of a flight point.
   @param world  world Document
   @param name   its name
   @param key    label, map, x, y or facing
   @param value  the value (label None / the name, facing the default: the key goes)
   @return None
   """
   if key not in FLIGHT_FIELDS or key == "name":
      raise DocumentError(f"a flight point's fields are {', '.join(FLIGHT_FIELDS[1:])}")
   f = _flight(world, name)
   before = copy.deepcopy(f)

   def change() -> None:
      """!Writes it."""
      if (key == "label" and value in (None, "", name)) or (key == "facing" and value == DEFAULT_FACING):
         f.pop(key, None)
      else:
         f[key] = value
   _guarded(world, change)
   error = check(world)
   if error is not None:
      f.clear()
      f.update(before)
      raise DocumentError(error)


def remove_flight_point(world: Document, name: str) -> None:
   """!Removes a flight point (the game's scripts naming it stop compiling: their compile names them).
   @param world  world Document
   @param name   its name
   @return None
   """
   f = _flight(world, name)
   _guarded(world, lambda: _flights_live(world).remove(f))


def lines(project: Project) -> list[str]:
   """!The world's F2 parts as text (the CLI's list).
   @param project  the world's Project
   @return lines
   """
   w = project.world
   out = [f"object kinds: {', '.join(object_kinds(w)) or 'none'}", f"map tags: {', '.join(map_tags(w)) or 'none'}"]
   levels = ", ".join(f"{k + 1}: lit {lv['lit']} brightness {lv['brightness']}"
                      for k, lv in enumerate(darkness_levels(w)))
   out.append(f"darkness levels{' (defaults)' if levels_default(w) else ''}: {levels or 'none'}")
   for f in flight_points(w):
      out.append(f"flight point {f['name']} ({f['label']}): {f['map']} {f['x']},{f['y']} facing {f['facing']}")
   for name, doc in _maps(project):
      darkness, tags, escape = map_rules(doc, w)
      if darkness or tags or escape:
         out.append(f"map {name}: darkness {darkness}, tags {', '.join(tags) or 'none'}"
                    f"{', escape point' if escape else ''}")
   return out
