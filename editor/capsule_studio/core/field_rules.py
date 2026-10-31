"""!The world's field rules (D-22 A1 / A2, engine E8): its 16 elevation levels
("elevations") and its movement modes ("vehicle_classes").

    "elevations": [{"name": "any", "meets": "all", "on_arrive": "take", "priority": 2}, ... 16 levels],
    "vehicle_classes": ["foot", {"name": "bike", "speeds": {"walk": 2, "run": 4}, "can_run": false,
                                 "first_animation": 12, "passable": ["normal", "grass"]}]

A level says which other levels a mover on it meets ("all", "same" or a
list of levels by number or name; a level always meets itself), whether
arriving on it makes the mover take its level ("take") or keep its own
("keep": bridges), and the sprite priority of a mover on it. Without
"elevations" the engine's default rule applies (map_compiler's
default_elevations(): 0 meets all, 15 meets all and keeps, 1-14 meet
themselves; the older "elevation_priority" list gives their priorities);
the first edit writes the 16 levels out. Class 0 of the movement modes is
on foot; each mode has walk / run speeds (pixels per frame), may forbid
running, names the sprite animation its set starts at and may list the
behaviors it can enter (default: every behavior that lets it).

The engine's map compiler is the authority: its compile_elevations() and
compile_vehicle_classes() check every edit (a refused one raises its
message inside the world's edit, which puts the manifest back), and every
choice list and limit is its own (ELEVATIONS, MEETS_WORDS, ON_ARRIVE,
MAX_PRIORITY, DEFAULT_SPRITE_PRIORITY, MAX_VEHICLE_CLASSES, VEHICLE_SPEEDS,
DEFAULT_WALK_SPEED, DEFAULT_RUN_SPEED, ANIMATION_SET,
MAX_FIRST_ANIMATION). A level rename follows the other levels' "meets"
lists; a mode rename follows the behaviors' "passable" lists and the
encounter methods' "vehicles"; the game's scripts naming a mode
(`vehicle NAME;`) are reported, not rewritten (mode_users()). Call each
editing helper inside one world.edit().
"""
from __future__ import annotations

import copy
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import engine, manifest_io
from .document import Document, DocumentError

## A parsed JSON object.
JsonDict = dict[str, Any]

## The world's elevation levels.
ELEVATIONS_KEY = "elevations"
## The older form: one sprite priority per level for the default rule.
PRIORITY_KEY = "elevation_priority"
## The world's movement modes.
CLASSES_KEY = "vehicle_classes"
## The world's behaviors.
BEHAVIORS_KEY = "behaviors"
## The world's encounter methods.
METHODS_KEY = "encounter_methods"
## An encounter method's movement modes.
VEHICLES_KEY = "vehicles"
## A behavior's / mode's list of what it lets in.
PASSABLE_KEY = "passable"
## The level / mode fields a set_* helper changes.
LEVEL_FIELDS = ("meets", "on_arrive", "priority")
## A mode's speeds object.
SPEEDS_KEY = "speeds"
## The mode fields set_mode() changes.
MODE_FIELDS = ("walk", "run", "can_run", "first_animation", PASSABLE_KEY, "dismount", "turn_frames", "bumps",
               "keeps_moving")
## I3: a mode's turn time, bump and keep-moving fields (map_compiler KEYS "vehicle_class").
TURN_FRAMES_KEY, BUMPS_KEY, KEEPS_MOVING_KEY = "turn_frames", "bumps", "keeps_moving"
## The project manifest's key of the scripts manifest (core.project.GAME_FILES).
SCRIPTS_FILE_KEY = "scripts"
## The script statement that names a movement mode.
VEHICLE_STATEMENT = re.compile(r"\bvehicle\s+([A-Za-z_][A-Za-z0-9_]*)\s*;")


def _mc() -> Any:
   """!The engine's map compiler.
   @return module
   """
   return engine.tool("map_compiler")


def level_count() -> int:
   """!Elevation levels of a cell (4 bits).
   @return ELEVATIONS
   """
   return int(_mc().ELEVATIONS)


def meets_words() -> list[str]:
   """!The words a level's "meets" may be instead of a list.
   @return MEETS_WORDS ("all", "same")
   """
   return list(_mc().MEETS_WORDS)


def arrive_words() -> list[str]:
   """!The words of a level's "on_arrive".
   @return ON_ARRIVE ("take", "keep")
   """
   return list(_mc().ON_ARRIVE)


def max_priority() -> int:
   """!Highest sprite priority (0 is the front).
   @return MAX_PRIORITY
   """
   return int(_mc().MAX_PRIORITY)


def speeds() -> list[int]:
   """!Speeds a movement mode may use, pixels per frame.
   @return VEHICLE_SPEEDS
   """
   return list(_mc().VEHICLE_SPEEDS)


def max_modes() -> int:
   """!Most movement modes.
   @return MAX_VEHICLE_CLASSES
   """
   return int(_mc().MAX_VEHICLE_CLASSES)


def animation_step() -> tuple[int, int]:
   """!A mode's first animation: a multiple of the set size, at most the highest.
   @return (ANIMATION_SET, MAX_FIRST_ANIMATION)
   """
   return int(_mc().ANIMATION_SET), int(_mc().MAX_FIRST_ANIMATION)


# -- checks ------------------------------------------------------------------------------------------------------------

def check(doc: Document) -> str | None:
   """!What the engine's map compiler says about the levels and the modes.
   @param doc  world Document
   @return the message, or None when both compile
   """
   mc = _mc()
   try:
      mc.compile_vehicle_classes(copy.deepcopy(doc.data))
      mc.compile_elevations(copy.deepcopy(doc.data))
   except Exception as e:   # ManifestError, type errors in odd data
      return str(e)
   return None


def compile_levels(data: JsonDict) -> list[tuple[int, int, int, str]]:
   """!A world manifest's 16 levels as the engine's runtime table.
   @param data  the world manifest (not changed)
   @return per level (meet mask, flags, sprite priority, name)
   @throws map_compiler.ManifestError when they do not compile
   """
   return _mc().compile_elevations(copy.deepcopy(data))


def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it when the levels and modes compiled before and do not after.
   @param doc     world Document
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   before = check(doc)
   result = change()
   if before is None:
      error = check(doc)
      if error is not None:
         raise DocumentError(error)
   return result


# -- elevation levels --------------------------------------------------------------------------------------------------

def levels_default(doc: Document) -> bool:
   """!Whether the world leaves its levels to the engine's default rule.
   @param doc  world Document
   @return True without "elevations"
   """
   return not isinstance(doc.data.get(ELEVATIONS_KEY), list)


def _default_levels(doc: Document) -> list[JsonDict]:
   """!The default rule's levels in manifest form, with the world's older priorities.
   @param doc  world Document
   @return 16 entries
   """
   prio = doc.data.get(PRIORITY_KEY)
   ok = isinstance(prio, list) and len(prio) == level_count() and all(isinstance(p, int) for p in prio)
   return _mc().default_elevations(prio if ok else None)


def level_rows(doc: Document) -> list[JsonDict]:
   """!The 16 levels.
   @param doc  world Document
   @return per level: index, name, meets (as written), on_arrive, priority, met (the level numbers it meets,
           as the compiler resolves them; [] when the levels do not compile), default (True: the engine's rule)
   """
   mc = _mc()
   given = doc.data.get(ELEVATIONS_KEY)
   raw = given if isinstance(given, list) else _default_levels(doc)
   try:
      compiled = mc.compile_elevations(copy.deepcopy(doc.data))
   except Exception:   # the panel shows check()'s message
      compiled = None
   out = []
   for i in range(level_count()):
      e = raw[i] if i < len(raw) and isinstance(raw[i], dict) else {}
      met = [k for k in range(level_count()) if compiled is not None and compiled[i][0] >> k & 1]
      out.append({"index": i, "name": e.get("name"), "meets": e.get("meets", mc.MEETS_WORDS[1]),
                  "on_arrive": e.get("on_arrive", mc.ON_ARRIVE[0]),
                  "priority": e.get("priority", mc.DEFAULT_SPRITE_PRIORITY), "met": met,
                  "default": not isinstance(given, list)})
   return out


def _levels(doc: Document) -> list[JsonDict]:
   """!The world's levels, written out from the default rule when it had none (the older priority list goes).
   @param doc  world Document
   @return the live list
   """
   if not isinstance(doc.data.get(ELEVATIONS_KEY), list):
      doc.data[ELEVATIONS_KEY] = _default_levels(doc)
      doc.data.pop(PRIORITY_KEY, None)
   return doc.data[ELEVATIONS_KEY]


def _level(doc: Document, index: int) -> JsonDict:
   """!One level, for editing.
   @param doc    world Document
   @param index  0..ELEVATIONS - 1
   @return the live dict
   """
   if not 0 <= index < level_count():
      raise DocumentError(f"levels are 0-{level_count() - 1}, got {index}")
   lst = _levels(doc)
   if not isinstance(lst[index], dict):
      raise DocumentError(f"level {index} is not an object")
   return lst[index]


def set_level(doc: Document, index: int, key: str, value: Any) -> None:
   """!Changes one field of a level.
   @param doc    world Document
   @param index  the level
   @param key    "meets" ("all", "same" or a list of level numbers / names), "on_arrive" or "priority"
   @param value  the value
   @return None
   """
   if key not in LEVEL_FIELDS:
      raise DocumentError(f"a level's fields are {', '.join(LEVEL_FIELDS)} (its name: rename_level())")

   def change() -> None:
      """!Writes the field.
      @return None
      """
      _level(doc, index)[key] = copy.deepcopy(value)

   _guarded(doc, change)


def rename_level(doc: Document, index: int, new: str) -> int:
   """!Renames a level; the other levels' "meets" lists naming it follow.
   @param doc    world Document
   @param index  the level
   @param new    its new name (unique, not a meets word)
   @return lists updated
   """
   if not isinstance(new, str) or not new.strip():
      raise DocumentError("level names can't be empty")
   new = new.strip()
   old = _level(doc, index).get("name")
   if new == old:
      return 0
   changed = 0

   def change() -> None:
      """!Writes the name and the lists naming it.
      @return None
      """
      nonlocal changed
      for e in _levels(doc):
         meets = e.get("meets") if isinstance(e, dict) else None
         if isinstance(meets, list) and old in meets:
            e["meets"] = [new if m == old else m for m in meets]
            changed += 1
      _level(doc, index)["name"] = new

   _guarded(doc, change)
   return changed


def reset_levels(doc: Document) -> bool:
   """!Gives the levels back to the engine's default rule.
   @param doc  world Document
   @return True when the world had its own
   """
   return doc.data.pop(ELEVATIONS_KEY, None) is not None


# -- movement modes ----------------------------------------------------------------------------------------------------

def mode_names(doc: Document) -> list[str]:
   """!The movement modes' names, class 0 (on foot) first.
   @param doc  world Document
   @return names
   """
   return [str(n) for n in _mc().vehicle_class_names(doc.data)]


def mode_rows(doc: Document) -> list[JsonDict]:
   """!The movement modes.
   @param doc  world Document
   @return per mode: index, name, walk, run, can_run, first_animation, passable (behavior names, or None: every
           behavior that lets it), dismount (F2: it steps onto land on foot), enters (the behaviors it may enter,
           as the compiler resolves both lists; None when the world does not compile)
   """
   mc = _mc()
   raw = doc.data.get(CLASSES_KEY, [mc.vehicle_class_names({})[0]])
   behaviors = [b for b in doc.data.get(BEHAVIORS_KEY, []) if isinstance(b, dict)]
   names = mode_names(doc)
   out = []
   for i, c in enumerate(raw if isinstance(raw, list) else []):
      c = {"name": c} if isinstance(c, str) else (c if isinstance(c, dict) else {})
      sp = c.get(SPEEDS_KEY) if isinstance(c.get(SPEEDS_KEY), dict) else {}
      passable = c.get(PASSABLE_KEY)
      enters = []
      for b in behaviors:
         lets = not b.get("solid") and names[i] in b.get(PASSABLE_KEY, names)
         if lets and (passable is None or b.get("name") in passable):
            enters.append(b.get("name"))
      out.append({"index": i, "name": c.get("name"), "walk": sp.get("walk", mc.DEFAULT_WALK_SPEED),
                  "run": sp.get("run", mc.DEFAULT_RUN_SPEED), "can_run": c.get("can_run", True),
                  "first_animation": c.get("first_animation", 0), "passable": passable, "enters": enters,
                  "dismount": c.get("dismount", False) is True, TURN_FRAMES_KEY: c.get(TURN_FRAMES_KEY, 0),
                  BUMPS_KEY: c.get(BUMPS_KEY, False) is True, KEEPS_MOVING_KEY: c.get(KEEPS_MOVING_KEY, False) is True})
   return out


def _modes(doc: Document) -> list[Any]:
   """!The world's modes for editing (written out when the world gives none).
   @param doc  world Document
   @return the live list
   """
   if not isinstance(doc.data.get(CLASSES_KEY), list):
      doc.data[CLASSES_KEY] = list(_mc().vehicle_class_names({}))
   return doc.data[CLASSES_KEY]


def _mode(doc: Document, name: str) -> JsonDict:
   """!A mode as an object (a bare name is written out as {"name"}).
   @param doc   world Document
   @param name  its name
   @return the live dict
   """
   lst = _modes(doc)
   names = mode_names(doc)
   if name not in names:
      raise DocumentError(f"no movement mode {name!r} ({', '.join(names)})")
   i = names.index(name)
   if not isinstance(lst[i], dict):
      lst[i] = {"name": lst[i]}
   return lst[i]


def _check_name(doc: Document, name: Any) -> str:
   """!A new mode name the world does not have.
   @param doc   world Document
   @param name  wanted name
   @return the name, stripped
   """
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("movement mode names can't be empty")
   name = name.strip()
   if name in mode_names(doc):
      raise DocumentError(f"there is already a movement mode {name!r}")
   return name


def add_mode(doc: Document, name: str) -> int:
   """!Adds a movement mode (on-foot defaults).
   @param doc   world Document
   @param name  its name
   @return its class number
   """
   name = _check_name(doc, name)
   if len(mode_names(doc)) >= max_modes():
      raise DocumentError(f"at most {max_modes()} movement modes (the engine's limit)")

   def change() -> int:
      """!Appends the mode.
      @return its index
      """
      _modes(doc).append(name)
      return len(_modes(doc)) - 1

   return _guarded(doc, change)


def _renamed(values: Any, old: str, new: str | None) -> tuple[Any, bool]:
   """!A name list with one name renamed (or dropped when new is None).
   @param values  the list (anything else is kept)
   @param old     the name
   @param new     its new name, or None to drop it
   @return (the list, True when it named old)
   """
   if not isinstance(values, list) or old not in values:
      return values, False
   return [new if v == old else v for v in values if not (new is None and v == old)], True


def _follow(doc: Document, old: str, new: str | None) -> list[str]:
   """!Renames (or drops) a mode in the behaviors' passable lists and the encounter methods' vehicles.
   @param doc  world Document
   @param old  the mode
   @param new  its new name, or None to drop it
   @return what changed ("behavior X", "encounter method Y")
   """
   out = []
   for key, label, field in ((BEHAVIORS_KEY, "behavior", PASSABLE_KEY), (METHODS_KEY, "encounter method",
                                                                         VEHICLES_KEY)):
      for e in doc.data.get(key, []) if isinstance(doc.data.get(key), list) else []:
         if not isinstance(e, dict):
            continue
         fixed, hit = _renamed(e.get(field), old, new)
         if hit:
            e[field] = fixed
            out.append(f"{label} {e.get('name')}")
   return out


def _scripts(doc: Document) -> tuple[Path, JsonDict] | None:
   """!The game's scripts manifest (its project's "scripts").
   @param doc  world Document
   @return (scripts.json, its data), or None
   """
   from . import codepage, project as projects   # local: these import heavier modules

   found = codepage.find_project(doc.path) if doc.path is not None else None
   if found is None:
      return None
   try:
      path = projects.game_files(codepage.open_project(found)).get(SCRIPTS_FILE_KEY)
      data = manifest_io.load(path) if path is not None and path.is_file() else None
   except (DocumentError, OSError, ValueError):
      return None
   return (path, data) if isinstance(data, dict) else None


def mode_users(doc: Document, name: str) -> list[str]:
   """!Where the game's field scripts name a movement mode (`vehicle NAME;`): a rename or removal breaks them.
   @param doc   world Document
   @param name  the mode
   @return "scripts: FILE line N" per use
   """
   found = _scripts(doc)
   if found is None:
      return []
   path, data = found
   out = []
   sources = data.get("sources")
   for rel in sources if isinstance(sources, list) else []:
      try:
         text = (path.parent / str(rel)).read_text(encoding="utf-8")
      except (OSError, UnicodeDecodeError):
         continue
      for m in VEHICLE_STATEMENT.finditer(text):
         if m.group(1) == name:
            line = text.count("\n", 0, m.start()) + 1   # 1-based line of the match
            out.append(f"scripts: {rel} line {line}")
   return out


def rename_mode(doc: Document, old: str, new: str) -> list[str]:
   """!Renames a movement mode; the behaviors' passable lists and the encounter methods follow (scripts naming it
   do not: see mode_users()).
   @param doc  world Document
   @param old  current name
   @param new  new name
   @return what followed
   """
   new = _check_name(doc, new)

   def change() -> list[str]:
      """!Writes the name and its uses.
      @return what followed
      """
      lst = _modes(doc)
      i = mode_names(doc).index(old) if old in mode_names(doc) else -1
      if i < 0:
         raise DocumentError(f"no movement mode {old!r}")
      if isinstance(lst[i], dict):
         lst[i]["name"] = new
      else:
         lst[i] = new
      return _follow(doc, old, new)

   return _guarded(doc, change)


def remove_mode(doc: Document, name: str) -> list[str]:
   """!Removes a movement mode (not class 0, on foot); the behaviors' passable lists and the encounter methods
   drop it (an encounter method left with none is refused: the compiler's message).
   @param doc   world Document
   @param name  the mode
   @return what followed
   """
   names = mode_names(doc)
   if name not in names:
      raise DocumentError(f"no movement mode {name!r}")
   if names.index(name) == 0:
      raise DocumentError("class 0 is on foot: rename it instead")

   def change() -> list[str]:
      """!Drops the mode and its uses.
      @return what followed
      """
      _modes(doc).pop(names.index(name))
      return _follow(doc, name, None)

   return _guarded(doc, change)


def move_mode(doc: Document, name: str, delta: int) -> bool:
   """!Moves a mode up or down (its class number; class 0 stays on foot).
   @param doc    world Document
   @param name   the mode
   @param delta  -1 up, +1 down
   @return True when it moved
   """
   names = mode_names(doc)
   if name not in names:
      raise DocumentError(f"no movement mode {name!r}")
   i = names.index(name)
   j = i + delta
   if i == 0 or j <= 0 or j >= len(names):
      return False
   lst = _modes(doc)
   lst.insert(j, lst.pop(i))
   return True


def set_mode(doc: Document, name: str, key: str, value: Any) -> None:
   """!Changes one field of a mode.
   @param doc    world Document
   @param name   the mode
   @param key    "walk" / "run" (a speed of speeds()), "can_run" (bool), "first_animation" (a multiple of the set
                 size), "passable" (behavior names, or None: every behavior that lets it), "dismount" (F2: bool; the
                 map compiler refuses it on class 0), "turn_frames" (I3: frames a turn in place takes, 0 the field's
                 default, up to max_turn_frames()), "bumps" / "keeps_moving" (I3: bool)
   @param value  the value (None removes the field: the default)
   @return None
   """
   if key not in MODE_FIELDS:
      raise DocumentError(f"a movement mode's fields are {', '.join(MODE_FIELDS)}")
   if key == PASSABLE_KEY and value is not None:
      known = [b.get("name") for b in doc.data.get(BEHAVIORS_KEY, []) if isinstance(b, dict)]
      unknown = [b for b in value if b not in known] if isinstance(value, list) else [value]
      if unknown:
         raise DocumentError(f"passable lists behaviors ({', '.join(str(k) for k in known)}), got {unknown}")

   def change() -> None:
      """!Writes the field (an empty speeds object goes).
      @return None
      """
      m = _mode(doc, name)
      holder = m.setdefault(SPEEDS_KEY, {}) if key in ("walk", "run") else m
      if value is None:
         holder.pop(key, None)
      else:
         holder[key] = copy.deepcopy(value)
      if isinstance(m.get(SPEEDS_KEY), dict) and not m[SPEEDS_KEY]:
         del m[SPEEDS_KEY]

   _guarded(doc, change)


def max_turn_frames() -> int:
   """!The longest turn in place a mode may set (I3: the engine's map_compiler.MAX_TURN_FRAMES).
   @return frames
   """
   return int(_mc().MAX_TURN_FRAMES)


def lines(doc: Document) -> list[str]:
   """!Levels and modes as text lines.
   @param doc  world Document
   @return lines
   """
   out = ["levels" + (" (the engine's default rule)" if levels_default(doc) else "") + ":"]
   for r in level_rows(doc):
      out.append(f"  {r['index']} {r['name']}: meets {r['meets']} ({', '.join(str(k) for k in r['met'])}); "
                 f"on arrive {r['on_arrive']}; priority {r['priority']}")
   out.append("movement modes:")
   for r in mode_rows(doc):
      passable = "every behavior" if r["passable"] is None else ", ".join(r["passable"]) or "nothing"
      out.append(f"  {r['index']} {r['name']}: walk {r['walk']}, run {r['run']}"
                 f"{'' if r['can_run'] else ' (no running)'}, first animation {r['first_animation']}, "
                 f"passable {passable}; enters {', '.join(str(b) for b in r['enters']) or 'nothing'}"
                 f"{'; dismounts' if r['dismount'] else ''}"
                 f"{f'; turns in {r[TURN_FRAMES_KEY]} frames' if r[TURN_FRAMES_KEY] else ''}"
                 f"{'; bumps' if r[BUMPS_KEY] else ''}{'; keeps moving' if r[KEEPS_MOVING_KEY] else ''}")
   error = check(doc)
   if error:
      out.append(f"error: {error}")
   return out

