"""!The storage boxes (D-26 section 3, engine G3): the structure manifest's
"storage" section, and the boxes of a test save.

    "storage": {"box_count": 8, "box_size": 30, "names": "Box {n}"}

box_count boxes of box_size slots, each slot one creature record (the
record layout's bytes); "names" is one text with {n} (the box number, from
1) naming every box, or a list of box_count names. A recruit with a full
party goes to the storage (the current box first, Structure > Recruit); the
script statements deposit_box / withdraw_box / count_boxed / open_boxes move
records between the party and the boxes. The platform bounds the boxes,
their slots and their record bytes (build_settings PLATFORM_LIMITS
max_boxes / max_box_slots / max_storage_bytes), and the save image keeps
every slot (the Boxes section: tools/save_layout.py).

A test save (core.inventory, capsule.testsave/1) may hold boxed creatures:
{"boxes": [{"slot": N, "species": NAME, "level": L}], "current_box": B};
export() writes them as the engine records of the save image's Boxes
section.

The engine's tools/battlec/storage.py is the one authority (re-exported by
battle_compiler). Each editing helper is one change: call it inside one
edit() of either manifest and Undo takes the whole change back. An edit that
stops data that compiled from compiling is refused with the engine's
message. Saved games keep their boxes by slot: another box count, size or
record layout makes an older save image of another shape.
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, TypedDict

from .. import battle, engine, logic
from ..document import Document, DocumentError
from . import stats

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure manifest's storage section.
STORAGE_KEY = "storage"
## Boxes.
COUNT_KEY = "box_count"
## Slots per box.
SIZE_KEY = "box_size"
## The box names (a pattern or a list).
NAMES_KEY = "names"
## The numbers set_field() sets.
FIELDS = (COUNT_KEY, SIZE_KEY)
## Boxes of a new section.
NEW_COUNT = 8
## Slots per box of a new section.
NEW_SIZE = 30
## The platform limit of the boxes.
BOX_LIMIT_KEY = "max_boxes"
## The platform limit of the slots of every box together.
SLOT_LIMIT_KEY = "max_box_slots"
## The platform limit of the boxed record bytes.
BYTES_LIMIT_KEY = "max_storage_bytes"
## A test save's boxed creatures.
TESTSAVE_BOXES = "boxes"
## A test save's current box.
TESTSAVE_CURRENT = "current_box"
## A boxed creature's slot (0 = box 1's first).
BOXED_SLOT = "slot"
## A boxed creature's species.
BOXED_SPECIES = "species"
## A boxed creature's level.
BOXED_LEVEL = "level"
## The record role of a boxed creature's species.
SPECIES_ROLE = "species_key"
## The record role of a boxed creature's level.
LEVEL_ROLE = "level"
## Level of a boxed creature put without one.
NEW_LEVEL = 5
## Location the transfer compile names.
WHERE = "test save"


class BoxRow(TypedDict):
   """!One box as the page and the CLI show it."""
   ## Box index (0 = box 1).
   index: int
   ## Its display name.
   name: str
   ## Its first storage slot.
   first: int
   ## Its slots.
   size: int


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def number_placeholder() -> str:
   """!The placeholder of a box's number in a name pattern.
   @return the engine's BOX_NUMBER_PLACEHOLDER
   """
   return str(_bc().BOX_NUMBER_PLACEHOLDER)


def default_names() -> str:
   """!The names of a section that gives none.
   @return the engine's BOX_DEFAULT_NAMES
   """
   return str(_bc().BOX_DEFAULT_NAMES)


def max_name_chars() -> int:
   """!Longest box name.
   @return the engine's BOX_MAX_NAME_CHARS
   """
   return int(_bc().BOX_MAX_NAME_CHARS)


def limits(targets: list[str] | None = None) -> dict[str, int]:
   """!The smallest storage limits of the targets.
   @param targets  platforms, or None for the default targets
   @return {"max_boxes", "max_box_slots", "max_storage_bytes"}
   @throws DocumentError for an unknown platform
   """
   bs = engine.tool("build_settings")
   try:
      chosen = [bs.platform_limits(t) for t in (targets or stats.DEFAULT_TARGETS)]
   except bs.SettingsError as e:
      raise DocumentError(str(e)) from None
   return {k: min(c[k] for c in chosen) for k in (BOX_LIMIT_KEY, SLOT_LIMIT_KEY, BYTES_LIMIT_KEY)}


# -- reading ----------------------------------------------------------------------------------------------------------

def is_stated(doc: Document) -> bool:
   """!Whether the structure states storage boxes (else a recruit with a full party has no room).
   @param doc  any manifest Document of the battle
   @return True when "storage" is given
   """
   return isinstance(battle.data_of(doc, STORAGE_KEY).get(STORAGE_KEY), dict)


def section(doc: Document) -> JsonDict:
   """!The section with the defaults filled in.
   @param doc  any manifest Document of the battle
   @return {"box_count", "box_size", "names" (the pattern or the list as given)} (box_count 0 when not stated)
   """
   g = battle.data_of(doc, STORAGE_KEY).get(STORAGE_KEY)
   g = g if isinstance(g, dict) else {}
   return {COUNT_KEY: g.get(COUNT_KEY, 0), SIZE_KEY: g.get(SIZE_KEY, 0),
           NAMES_KEY: copy.deepcopy(g.get(NAMES_KEY, default_names()))}


def box_names(doc: Document) -> list[str]:
   """!Every box's name (a pattern expanded).
   @param doc  any manifest Document of the battle
   @return names (box_count of them when the section is valid)
   """
   s = section(doc)
   count = s[COUNT_KEY] if isinstance(s[COUNT_KEY], int) else 0
   names = s[NAMES_KEY]
   if isinstance(names, str):
      return [names.replace(number_placeholder(), str(k + 1)) for k in range(count)]
   return [str(n) for n in names] if isinstance(names, list) else []


def rows(doc: Document) -> list[BoxRow]:
   """!The boxes with their slots.
   @param doc  any manifest Document of the battle
   @return one row per box
   """
   s = section(doc)
   size = s[SIZE_KEY] if isinstance(s[SIZE_KEY], int) else 0
   return [BoxRow(index=k, name=n, first=k * size, size=size) for k, n in enumerate(box_names(doc))]


def slot_count(doc: Document) -> int:
   """!Every box's slots together.
   @param doc  any manifest Document of the battle
   @return slots
   """
   s = section(doc)
   return s[COUNT_KEY] * s[SIZE_KEY] if isinstance(s[COUNT_KEY], int) and isinstance(s[SIZE_KEY], int) else 0


# -- editing (inside one edit()) -------------------------------------------------------------------------------------

def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the battle data compiled before and does not after.
   @param doc     any manifest Document of the battle
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   project = logic.project_of(doc)
   before = project.error_now() if project is not None else None
   result = change()
   if before is None and project is not None:
      error = project.error_now()
      if error is not None:
         raise DocumentError(error)
   return result


def _live(doc: Document) -> JsonDict:
   """!The section for editing.
   @param doc  any manifest Document of the battle
   @return the live dict
   @throws DocumentError when the structure states none (enable() first)
   """
   given = battle.data_of(doc, STORAGE_KEY).get(STORAGE_KEY)
   if not isinstance(given, dict):
      raise DocumentError("the structure states no storage boxes: enable them first")
   return given


def _whole(value: Any, field: str) -> int:
   """!A whole number of 1 or more.
   @param value  the value (int or digits)
   @param field  field name (messages)
   @return it
   @throws DocumentError when it is not one
   """
   try:
      value = int(value)
   except (TypeError, ValueError):
      raise DocumentError(f"{field}: a whole number (got {value!r})") from None
   if value < 1:
      raise DocumentError(f"{field}: 1 or more (got {value})")
   return value


def enable(doc: Document, count: int = NEW_COUNT, size: int = NEW_SIZE) -> None:
   """!Gives the structure storage boxes (named by the engine's default pattern).
   @param doc    any manifest Document of the battle
   @param count  boxes
   @param size   slots per box
   @return None
   @throws DocumentError when it has them, or the engine refuses the size on this platform
   """
   if is_stated(doc):
      raise DocumentError("the structure states storage boxes already")
   entry = {COUNT_KEY: _whole(count, COUNT_KEY), SIZE_KEY: _whole(size, SIZE_KEY)}
   _guarded(doc, lambda: battle.data_of(doc, STORAGE_KEY).update({STORAGE_KEY: entry}))


def disable(doc: Document) -> None:
   """!Takes the storage boxes out.
   @param doc  any manifest Document of the battle
   @return None
   """
   _live(doc)
   _guarded(doc, lambda: battle.data_of(doc, STORAGE_KEY).pop(STORAGE_KEY))


def set_field(doc: Document, field: str, value: Any) -> None:
   """!Sets box_count or box_size (a name list follows a new count: names past it go, new boxes get the pattern's).
   @param doc    any manifest Document of the battle
   @param field  one of FIELDS
   @param value  1 or more
   @return None
   @throws DocumentError for an unknown field or a value the engine refuses
   """
   if field not in FIELDS:
      raise DocumentError(f"a storage field is one of {', '.join(FIELDS)} (got {field!r})")
   value = _whole(value, field)
   live = _live(doc)

   def change() -> None:
      """!Writes the number (and fits a name list to a new count).
      @return None
      """
      live[field] = value
      names = live.get(NAMES_KEY)
      if field == COUNT_KEY and isinstance(names, list):
         pattern = default_names()
         live[NAMES_KEY] = (names + [pattern.replace(number_placeholder(), str(k + 1))
                                     for k in range(len(names), value)])[:value]

   _guarded(doc, change)


def set_names(doc: Document, names: str | list[str]) -> None:
   """!Sets the box names: one pattern with {n} (the default pattern: the key goes) or a list of box_count names.
   @param doc    any manifest Document of the battle
   @param names  the pattern or the list
   @return None
   """
   live = _live(doc)
   if not isinstance(names, (str, list)):
      raise DocumentError(f"names: a text with {number_placeholder()} or a list of names")

   def change() -> None:
      """!Writes the names.
      @return None
      """
      if names == default_names():
         live.pop(NAMES_KEY, None)
      else:
         live[NAMES_KEY] = list(names) if isinstance(names, list) else names

   _guarded(doc, change)


def rename_box(doc: Document, index: int, name: str) -> None:
   """!Names one box (a pattern becomes the list of every box's name first).
   @param doc    any manifest Document of the battle
   @param index  box index (0 = box 1)
   @param name   its name
   @return None
   """
   names = box_names(doc)
   if not isinstance(index, int) or not 0 <= index < len(names):
      raise DocumentError(f"no box {index!r} ({len(names)} boxes)")
   names[index] = name.strip() if isinstance(name, str) else name
   set_names(doc, names)


def follow_count(doc: Document) -> None:
   """!Keeps a name list as long as the boxes (after a count change made elsewhere).
   @param doc  any manifest Document of the battle
   @return None
   """
   s = section(doc)
   if isinstance(s[NAMES_KEY], list) and len(s[NAMES_KEY]) != s[COUNT_KEY]:
      set_field(doc, COUNT_KEY, s[COUNT_KEY])


# -- report -----------------------------------------------------------------------------------------------------------

def budget(doc: Document, targets: list[str] | None = None) -> tuple[str, bool]:
   """!The boxes, slots and record bytes against the engine's limits.
   @param doc      any manifest Document of the battle
   @param targets  platforms, or None for the default targets
   @return (e.g. "8/16 boxes, 240/512 slots, 15360/32768 B (gba)", over a limit)
   """
   chosen = targets or stats.DEFAULT_TARGETS
   most = limits(chosen)
   s = section(doc)
   project = logic.project_of(doc)
   compiled = project.compile(chosen[0])[0] if project is not None else None
   record = compiled["layout"]["bytes"] if compiled is not None else 0
   slots = slot_count(doc)
   count = s[COUNT_KEY] if isinstance(s[COUNT_KEY], int) else 0
   text = (f"{count}/{most[BOX_LIMIT_KEY]} boxes, {slots}/{most[SLOT_LIMIT_KEY]} slots, "
           f"{slots * record}/{most[BYTES_LIMIT_KEY]} B of records ({', '.join(chosen)})")
   over = count > most[BOX_LIMIT_KEY] or slots > most[SLOT_LIMIT_KEY] or slots * record > most[BYTES_LIMIT_KEY]
   return text, over


def save_report(project: BattleProject, platform: str | None = None) -> tuple[str, bool]:
   """!The save image with its Boxes section against the platform's save medium (tools/save_layout.py: C6, the
   medium's erase unit, the game's script banks, two copies needed).
   @param project   BattleProject
   @param platform  save platform (None: the GBA's flash; "gba_sram": its SRAM)
   @return (e.g. "save image 16088 of 65536 B (boxes 15391 B; 2 copies, gba)", over the medium or under two copies)
   """
   sl = engine.tool("save_layout")
   bs = engine.tool("build_settings")
   name = platform or bs.DEFAULT_PLATFORM
   compile_for, room, unit = sl.medium(name)
   compiled, error = project.compile(compile_for)
   if compiled is None:
      return f"the battle data does not compile: {error}", True
   from .. import inventory   # local: core.inventory imports this module
   try:
      banks = inventory.script_banks(project)
   except DocumentError as e:
      return str(e), True
   sections = sl.sections_of(compiled, banks)
   size = sl.image_bytes(sections)
   copies = min(sl.MAX_COPIES, room // ((size + unit - 1) // unit * unit))
   text = (f"save image {size} of {room} B (boxes {sections.get('boxes', 0)} B, script {sections.get('script', 0)} "
           f"B; {copies} copies, {name})")
   return text, size > room or copies < sl.REQUIRED_COPIES


def lines(doc: Document, targets: list[str] | None = None) -> list[str]:
   """!The boxes as text (CLI `storage show`), then the budget.
   @param doc      any manifest Document of the battle
   @param targets  platforms, or None for the default targets
   @return lines
   """
   if not is_stated(doc):
      return ["(no storage boxes: the structure states no storage section)"]
   s = section(doc)
   out = [f"{s[COUNT_KEY]} boxes of {s[SIZE_KEY]} slots; names {s[NAMES_KEY]!r}"]
   out += [f"{r['index']} {r['name']}: slots {r['first']}-{r['first'] + r['size'] - 1}" for r in rows(doc)]
   return out + [budget(doc, targets)[0]]


# -- test saves' boxes ------------------------------------------------------------------------------------------------

def boxed_of(save: Document) -> list[JsonDict]:
   """!A test save's boxed creatures, by slot.
   @param save  test save Document
   @return [{"slot", "species", "level"}] (copies)
   """
   given = save.data.get(TESTSAVE_BOXES)
   out = [dict(b) for b in (given if isinstance(given, list) else []) if isinstance(b, dict)]
   return sorted(out, key=lambda b: b.get(BOXED_SLOT) if isinstance(b.get(BOXED_SLOT), int) else -1)


def current_box(save: Document) -> int:
   """!A test save's current box.
   @param save  test save Document
   @return the box (0 = box 1)
   """
   value = save.data.get(TESTSAVE_CURRENT, 0)
   return value if isinstance(value, int) else 0


def _species_names(doc: Document) -> list[str]:
   """!The battle's species.
   @param doc  any manifest Document of the battle
   @return names
   """
   return [str(e.get("name")) for e in battle.entries(battle.content_doc(doc), "species") if isinstance(e, dict)]


def first_free(save: Document, doc: Document, box: int | None = None) -> int | None:
   """!The first free slot (of a box, else of every box).
   @param save  test save Document
   @param doc   any manifest Document of the battle
   @param box   box index, or None
   @return the slot, or None when it is full
   """
   used = {b.get(BOXED_SLOT) for b in boxed_of(save)}
   size = section(doc)[SIZE_KEY]
   slots = range(box * size, (box + 1) * size) if box is not None else range(slot_count(doc))
   return next((k for k in slots if k not in used), None)


def max_level(doc: Document) -> int:
   """!The highest level a boxed creature's record holds (the layout's level role).
   @param doc  any manifest Document of the battle
   @return the value (NEW_LEVEL when the data does not compile)
   """
   project = logic.project_of(doc)
   compiled = project.compile()[0] if project is not None else None
   if compiled is None:
      return NEW_LEVEL
   return int(_bc().role_max_value(compiled["layout"], LEVEL_ROLE))


def put_creature(save: Document, doc: Document, species: str, level: int = NEW_LEVEL,
                 slot: int | None = None) -> int:
   """!Boxes a creature in a test save (inside save.edit()).
   @param save     test save Document
   @param doc      any manifest Document of the battle
   @param species  species name
   @param level    its level (1 or more; the record layout bounds it)
   @param slot     the slot, or None for the current box's first free slot (else any)
   @return the slot
   @throws DocumentError without boxes, for an unknown species, a taken or missing slot, or full boxes
   """
   slots = slot_count(doc)
   if slots == 0:
      raise DocumentError("the structure states no storage boxes")
   if species not in _species_names(doc):
      raise DocumentError(f"no species {species!r}")
   if not isinstance(level, int) or isinstance(level, bool) or level < 1:
      raise DocumentError(f"a level is 1 or more (got {level!r})")
   if slot is None:
      box = min(current_box(save), max(0, section(doc)[COUNT_KEY] - 1))
      slot = first_free(save, doc, box)
      slot = slot if slot is not None else first_free(save, doc)
      if slot is None:
         raise DocumentError(f"every box is full ({slots} slots)")
   if not isinstance(slot, int) or not 0 <= slot < slots:
      raise DocumentError(f"storage slot {slot!r}: the boxes have {slots} slots")
   if any(b.get(BOXED_SLOT) == slot for b in boxed_of(save)):
      raise DocumentError(f"storage slot {slot} holds a creature already")
   save.data.setdefault(TESTSAVE_BOXES, []).append({BOXED_SLOT: slot, BOXED_SPECIES: species, BOXED_LEVEL: level})
   return slot


def remove_creature(save: Document, slot: int) -> JsonDict:
   """!Takes a boxed creature out of a test save (inside save.edit()).
   @param save  test save Document
   @param slot  its slot
   @return the entry taken
   @throws DocumentError when the slot is empty
   """
   lst = save.data.get(TESTSAVE_BOXES)
   for b in list(lst) if isinstance(lst, list) else []:
      if isinstance(b, dict) and b.get(BOXED_SLOT) == slot:
         lst.remove(b)
         return b
   raise DocumentError(f"storage slot {slot!r} is empty")


def set_current_box(save: Document, doc: Document, box: int) -> None:
   """!Sets a test save's current box (inside save.edit()).
   @param save  test save Document
   @param doc   any manifest Document of the battle
   @param box   box index (0 = box 1)
   @return None
   """
   count = section(doc)[COUNT_KEY]
   if not isinstance(box, int) or not 0 <= box < max(1, count):
      raise DocumentError(f"no box {box!r} ({count} boxes)")
   if box == 0:
      save.data.pop(TESTSAVE_CURRENT, None)
   else:
      save.data[TESTSAVE_CURRENT] = box


def check_boxes(save: Document, doc: Document) -> list[str]:
   """!What the manifests refuse in a test save's boxes.
   @param save  test save Document
   @param doc   any manifest Document of the battle
   @return problems
   """
   out = []
   boxed = boxed_of(save)
   slots = slot_count(doc)
   if boxed and slots == 0:
      return [f"{len(boxed)} boxed creature(s), but the structure states no storage boxes"]
   species = _species_names(doc)
   seen: set[int] = set()
   for b in boxed:
      slot = b.get(BOXED_SLOT)
      if not isinstance(slot, int) or not 0 <= slot < slots:
         out.append(f"boxes: slot {slot!r} (the boxes have {slots} slots)")
      elif slot in seen:
         out.append(f"boxes: slot {slot} twice")
      seen.add(slot if isinstance(slot, int) else -1)
      if b.get(BOXED_SPECIES) not in species:
         out.append(f"boxes: slot {slot}: unknown species {b.get(BOXED_SPECIES)!r}")
      level = b.get(BOXED_LEVEL)
      if not isinstance(level, int) or isinstance(level, bool) or level < 1:
         out.append(f"boxes: slot {slot}: level {level!r}")
   count = section(doc)[COUNT_KEY]
   if current_box(save) != 0 and not 0 <= current_box(save) < count:
      out.append(f"current box {current_box(save)} ({count} boxes)")
   return out


def records_of(save: Document, compiled: Mapping[str, Any]) -> dict[int, bytes]:
   """!A test save's boxed creatures as engine records (tools/record_transfer.py pack(): the species and the
   level, every other role its new-record value; B2: a boxed egg's "hatch" sets its egg role and counter,
   core.structure.nursery.record_bytes()).
   @param save      test save Document
   @param compiled  compile_battle() result
   @return {slot: record bytes}
   @throws DocumentError for a creature the record layout cannot hold
   """
   from . import nursery   # local: it reads this module's test save keys
   out = {}
   for b in boxed_of(save):
      try:
         out[int(b[BOXED_SLOT])] = nursery.record_bytes(compiled, b[BOXED_SPECIES], int(b[BOXED_LEVEL]),
                                                        b.get(nursery.HATCH_KEY))
      except (KeyError, ValueError, DocumentError) as e:
         raise DocumentError(f"boxes: slot {b.get(BOXED_SLOT)}: {e}") from None
   return out


def boxed_lines(save: Document, doc: Document) -> list[str]:
   """!A test save's boxes as text (CLI `testsave show`).
   @param save  test save Document
   @param doc   any manifest Document of the battle
   @return lines ([] without boxed creatures)
   """
   boxed = boxed_of(save)
   if not boxed:
      return []
   names = box_names(doc)
   size = section(doc)[SIZE_KEY] or 1
   out = [f"current box: {names[current_box(save)] if current_box(save) < len(names) else current_box(save)}"]
   for b in boxed:
      slot = b.get(BOXED_SLOT)
      box = slot // size if isinstance(slot, int) else 0
      where = names[box] if box < len(names) else f"box {box + 1}"
      egg = f" (egg, {b['hatch']} steps)" if "hatch" in b else ""   # B2: core.structure.nursery.HATCH_KEY
      out.append(f"{where} slot {slot}: {b.get(BOXED_SPECIES)} level {b.get(BOXED_LEVEL)}{egg}")
   return out
