"""!Wild encounter editing (C-03d, C-03e, D-12): the world's encounter
settings, each map's encounter file and the shared tables, with previews
computed exactly as the engine rolls.

Files (see the engine's tools/encounter_compiler.py for the rules):
  - world.json: "battle" (the battle manifest species come from),
    "encounter_methods", "encounter_conditions", "encounter_tables" (the
    shared tables file);
  - a map's "encounters": its capsule.encounters/1 file, tables
    {"slot", "method", "rate", "entries"} or {"slot", "method", "table":
    shared name};
  - the shared file: tables {"name", "rate", "entries"}.

Encounter cells pick their table with the slot field of the attribute
cell (core.maps, "slot"). New encounter files go to encounters/NAME.json
and encounters/shared.json beside the world file.

Functions that change one Document must be called inside doc.edit();
functions taking the Project (creating files, renames that follow
references into other files) make their own undo steps, one per changed
document. Nothing here depends on a user interface.
"""
from __future__ import annotations

import copy
import types
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from . import engine, maps, paths
from .document import Document, DocumentError

if TYPE_CHECKING:
   from ..plugins.registry import Diagnostic
   from .world import Project

## Encounter file schema.
SCHEMA = "capsule.encounters/1"
## Encounter slots per map.
MAX_SLOTS = 16
## Entries per table.
MAX_ENTRIES = 64
## Modifiers per entry.
MAX_MODIFIERS = 8
## Methods per world.
MAX_METHODS = 16
## Condition names per world.
MAX_CONDITIONS = 32
## Triggers of a method.
TRIGGERS = ("step", "script")
## What a world without "encounter_methods" has.
DEFAULT_METHODS = [{"name": "step", "trigger": "step"}]
## Folder (beside the world file) new encounter files go to.
FOLDER = "encounters"
## Shared tables file created by default (relative to the world file).
SHARED_FILE = "encounters/shared.json"
## Rate of a new table.
DEFAULT_RATE = "1/10"
## Highest level an entry may give.
MAX_LEVEL = 255
## Highest weight of an entry.
MAX_WEIGHT = 65535
## Length of a level range: [lowest, highest].
LEVEL_RANGE_LENGTH = 2
## Highest level species() reports when the world names no battle data (a new battle manifest's level_max).
LEVEL_MAX_WITHOUT_BATTLE = 100
## Fraction bits of the Q8 fixed-point multipliers modifiers use.
Q8_FRACTION_BITS = 8
## Percent in a whole, for rate displays.
PERCENT = 100.0
## Species names describe_slot() lists before "...".
SPECIES_SHOWN = 4
## The attribute cell field of the encounter flag (core.maps.cell_fields(): the engine's).
ENCOUNTER_FIELD = "encounter"
## The attribute cell field of the encounter slot.
SLOT_FIELD = "slot"

## A parsed JSON object (a method, a table, an entry, a modifier, a manifest).
JsonDict = dict[str, Any]
## A rate as stored: "1/10", "12.5%", [n, m] or a number (the engine's encounter compiler reads it).
Rate = str | int | float | list[int]


def _ec() -> types.ModuleType:
   """!The engine's encounter compiler (rate and multiplier rules, species order).
   @return module
   """
   return engine.tool("encounter_compiler")


# -- the world's settings -----------------------------------------------------------------

def methods(project: Project) -> list[JsonDict]:
   """!The world's encounter methods (the default when it names none).
   @param project  Project
   @return list of {"name", "trigger", "vehicles"?} (live objects when the world names them)
   """
   raw = project.world.data.get("encounter_methods")
   return raw if isinstance(raw, list) else copy.deepcopy(DEFAULT_METHODS)


def method_names(project: Project) -> list[str]:
   """!Names of the world's encounter methods, in index order.
   @param project  Project
   @return list of names
   """
   return [m.get("name") for m in methods(project)]


def step_methods(project: Project) -> list[str]:
   """!Names of the methods steps roll.
   @param project  Project
   @return list of names
   """
   return [m.get("name") for m in methods(project) if m.get("trigger", "step") == "step"]


def conditions(project: Project) -> list[str]:
   """!The world's condition names, in bit order.
   @param project  Project
   @return list of names
   """
   raw = project.world.data.get("encounter_conditions")
   return list(raw) if isinstance(raw, list) else []


def _world_methods(world: Document) -> list[JsonDict]:
   """!The world's method list, written into the world when it was the default.
   @param world  world Document
   @return the live list
   """
   if not isinstance(world.data.get("encounter_methods"), list):
      world.data["encounter_methods"] = copy.deepcopy(DEFAULT_METHODS)
   return world.data["encounter_methods"]


def add_method(world: Document, name: str, trigger: str = "step", vehicles: Sequence[str] | None = None) -> None:
   """!Adds a method (call inside world.edit()).
   @param world     world Document
   @param name      new name
   @param trigger   "step" or "script"
   @param vehicles  step methods: vehicle classes (None: every class)
   @return None
   """
   ms = _world_methods(world)
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("a method needs a name")
   if any(m.get("name") == name for m in ms):
      raise DocumentError(f"there is a method {name!r} already")
   if len(ms) >= MAX_METHODS:
      raise DocumentError(f"a world has up to {MAX_METHODS} methods")
   m = {"name": name, "trigger": trigger}
   ms.append(m)
   _set_method_fields(world, m, trigger, vehicles)


def _set_method_fields(world: Document, m: JsonDict, trigger: str, vehicles: Sequence[str] | None) -> None:
   """!Checks and sets a method's trigger and vehicles.
   @param world     world Document
   @param m         the method object
   @param trigger   "step" or "script"
   @param vehicles  list of vehicle classes, or None for every class
   @return None
   """
   if trigger not in TRIGGERS:
      raise DocumentError(f"a method's trigger is {' or '.join(TRIGGERS)}")
   m["trigger"] = trigger
   m.pop("vehicles", None)
   if vehicles is not None:
      if trigger != "step":
         raise DocumentError("vehicles apply to step methods only")
      classes = engine.tool("map_compiler").vehicle_class_names(world.data)   # names or {"name", ...} entries
      bad = [v for v in vehicles if v not in classes]
      if bad:
         raise DocumentError(f"no vehicle class {bad[0]!r} (the world's: {', '.join(classes)})")
      m["vehicles"] = list(vehicles)


def set_method(world: Document, name: str, trigger: str | None = None,
               vehicles: Sequence[str] | Literal[False] | None = False) -> None:
   """!Changes a method's trigger or vehicle classes (call inside world.edit()).
   @param world     world Document
   @param name      method name
   @param trigger   "step" or "script", or None to keep it
   @param vehicles  list, None (every class), or False to keep them
   @return None
   """
   ms = _world_methods(world)
   m = next((x for x in ms if x.get("name") == name), None)
   if m is None:
      raise DocumentError(f"no method {name!r}")
   trigger = trigger or m.get("trigger", "step")
   if vehicles is False:
      vehicles = m.get("vehicles") if trigger == "step" else None
   _set_method_fields(world, m, trigger, vehicles)


def add_condition(world: Document, name: str) -> None:
   """!Adds a condition name (call inside world.edit()).
   @param world  world Document
   @param name   new name
   @return None
   """
   cs = world.data.setdefault("encounter_conditions", [])
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("a condition needs a name")
   if name in cs:
      raise DocumentError(f"there is a condition {name!r} already")
   if len(cs) >= MAX_CONDITIONS:
      raise DocumentError(f"a world has up to {MAX_CONDITIONS} conditions (one bit each)")
   cs.append(name)


def set_battle(world: Document, rel: str | Path | None) -> None:
   """!Names the battle manifest species come from (call inside world.edit()).
   @param world  world Document
   @param rel    path relative to the world file, or None to remove it
   @return None
   """
   if rel is None:
      world.data.pop("battle", None)
   else:
      world.data["battle"] = Path(rel).as_posix()


def battle_path(project: Project) -> Path | None:
   """!The battle manifest the world names.
   @param project  Project
   @return resolved Path, or None
   """
   rel = project.world.data.get("battle")
   return (project.base / rel).resolve() if isinstance(rel, str) else None


def species(project: Project) -> tuple[list[str], int]:
   """!The species encounters may name, in the battle data's index order.
   @param project  Project
   @return (names, level_max); ([], 100) when the world names no battle data
   @throws DocumentError when the battle manifest cannot be read
   """
   path = battle_path(project)
   if path is None:
      return [], LEVEL_MAX_WITHOUT_BATTLE
   ec = _ec()
   try:
      # The compiler reads unsaved documents from the project's sources.
      sp = ec.load_species(path, None, project._sources()[0])
   except ec.ManifestError as e:
      raise DocumentError(str(e)) from None
   return sp.names, sp.level_max


# -- files -------------------------------------------------------------------------------

def _rel(from_dir: str | Path, path: str | Path) -> str:
   """!A path relative to a folder, '/'-separated (both resolved first).
   @param from_dir  folder
   @param path      target
   @return text
   @throws DocumentError when the target is on another drive (Windows)
   """
   return paths.relative(path, from_dir)


def _open(project: Project, path: Path) -> Document:
   """!Opens (once) an encounter Document; a new one starts as {"schema", "id", "tables"}.
   @param project  Project
   @param path     resolved Path
   @return Document
   """
   doc = project._doc(path, SCHEMA)
   # Project._doc() starts a missing file as the schema's empty content plus an "id": put the keys in file order.
   if not path.exists() and list(doc.data) == ["schema", "tables", "id"] and not doc.data["tables"]:
      doc.data = {"schema": SCHEMA, "id": doc.data["id"], "tables": []}
   return doc


def map_file(project: Project, name: str) -> Path | None:
   """!A map's encounter file.
   @param project  Project
   @param name     map name
   @return resolved Path, or None when the map has none
   """
   # I2: map_head() reads an unopened map without opening its document (a large world lists every map's file)
   rel = project.map_head(name)["encounters"]
   return (project.map_path(name).parent / rel).resolve() if isinstance(rel, str) else None


def map_doc(project: Project, name: str, create: bool = False) -> Document | None:
   """!A map's encounter Document.
   @param project  Project
   @param name     map name
   @param create   give the map a new file (encounters/NAME.json) when it has none; this is an undo
                   step of the map
   @return Document, or None (no file and not create)
   """
   path = map_file(project, name)
   if path is None:
      if not create:
         return None
      mdoc = project.map(name)
      path = (project.base / FOLDER / f"{name}.json").resolve()
      # Taken (on disk, or by an unsaved document): try NAME_1.json, NAME_2.json, ...
      n = 1
      while path.exists() or path in {d.path for d in project.documents()}:
         path = (project.base / FOLDER / f"{name}_{n}.json").resolve()
         n += 1
      with mdoc.edit("Add encounters"):
         mdoc.data["encounters"] = _rel(mdoc.path.parent, path)
   return _open(project, path)


def shared_file(project: Project) -> Path | None:
   """!The shared tables file.
   @param project  Project
   @return resolved Path, or None
   """
   rel = project.world.data.get("encounter_tables")
   return (project.base / rel).resolve() if isinstance(rel, str) else None


def shared_doc(project: Project, create: bool = False) -> Document | None:
   """!The shared tables Document.
   @param project  Project
   @param create   name a new file (encounters/shared.json) in the world when it has none (a world undo step)
   @return Document, or None
   """
   path = shared_file(project)
   if path is None:
      if not create:
         return None
      with project.world.edit("Add shared encounter tables"):
         project.world.data["encounter_tables"] = SHARED_FILE
      path = shared_file(project)
   return _open(project, path)


def encounter_docs(project: Project) -> list[tuple[str | None, Document]]:
   """!Every map's encounter Document (opening them), plus the shared one.
   @param project  Project
   @return list of (map name or None for shared, Document)
   """
   out = []
   for n in project.map_names():
      d = map_doc(project, n)
      if d is not None:
         out.append((n, d))
   s = shared_doc(project)
   if s is not None:
      out.append((None, s))
   return out


# -- tables --------------------------------------------------------------------------------

def tables(doc: Document) -> list[JsonDict]:
   """!A file's tables.
   @param doc  encounter Document
   @return the live list
   """
   return doc.data.setdefault("tables", [])


def table(doc: Document, index: int) -> JsonDict:
   """!One table.
   @param doc    encounter Document
   @param index  table index
   @return the table object
   """
   ts = tables(doc)
   if not 0 <= index < len(ts):
      raise DocumentError(f"no table {index}")
   return ts[index]


def check_rate(value: Rate) -> Rate:
   """!Checks a rate the way the engine does.
   @param value  "1/10", "12.5%", [n, m], a number
   @return the value as given (stored unchanged)
   """
   ec = _ec()
   try:
      ec.rate(value, "rate")
   except ec.ManifestError as e:
      # The compiler's message starts with the location given above ("rate: "), which says nothing here.
      raise DocumentError(str(e).replace("rate: ", "")) from None
   return value


def rate_odds(value: Rate) -> tuple[int, int]:
   """!A rate as integer odds.
   @param value  rate as stored
   @return (n, m)
   """
   ec = _ec()
   try:
      return ec.rate(value, "rate")
   except ec.ManifestError as e:
      raise DocumentError(str(e)) from None


def format_rate(value: Rate | None) -> str:
   """!A rate for display: "1/10 (10%)".
   @param value  rate as stored, or None
   @return text
   """
   if value is None:
      return "-"
   try:
      n, m = rate_odds(value)
   except DocumentError:
      return f"{value!r} (invalid)"
   except (engine.EngineNotFound, ImportError):   # no engine to read it with: show it as written
      return str(value)
   pct = PERCENT * n / m
   return f"{n}/{m} ({pct:.3g}%)"


def label(t: JsonDict) -> str:
   """!A table's editor label.
   @param t  table object
   @return text, or ""
   """
   return (t.get("editor") or {}).get("label", "")


def add_table(doc: Document, slot: int, method: str, rate: Rate | None = DEFAULT_RATE, label_text: str | None = None,
              shared: str | None = None) -> int:
   """!Adds a map table (call inside doc.edit()).
   @param doc         a map's encounter Document
   @param slot        0-15
   @param method      method name
   @param rate        trigger odds (None with @p shared: the shared table's)
   @param label_text  editor label, or None
   @param shared      shared table name to use instead of own entries, or None
   @return the new table's index
   """
   if not isinstance(slot, int) or not 0 <= slot < MAX_SLOTS:
      raise DocumentError(f"slots are 0-{MAX_SLOTS - 1}")
   if any(t.get("slot") == slot and t.get("method") == method for t in tables(doc)):
      raise DocumentError(f"slot {slot} has a {method!r} table already")
   t = {"slot": slot, "method": method}
   if label_text:
      t["editor"] = {"label": label_text}
   if shared is not None:
      t["table"] = shared
      if rate is not None:
         t["rate"] = check_rate(rate)
   else:
      t["rate"] = check_rate(rate)
      t["entries"] = []
   tables(doc).append(t)
   return len(tables(doc)) - 1


def add_shared(doc: Document, name: str, rate: Rate = DEFAULT_RATE) -> int:
   """!Adds a shared table (call inside doc.edit()).
   @param doc   the shared Document
   @param name  unique name
   @param rate  trigger odds
   @return its index
   """
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("a shared table needs a name")
   if any(t.get("name") == name for t in tables(doc)):
      raise DocumentError(f"there is a shared table {name!r} already")
   tables(doc).append({"name": name, "rate": check_rate(rate), "entries": []})
   return len(tables(doc)) - 1


def remove_table(doc: Document, index: int) -> None:
   """!Removes a map table (call inside doc.edit()).
   @param doc    encounter Document
   @param index  table index
   @return None
   """
   table(doc, index)   # refuses a bad index
   del tables(doc)[index]


def set_table(doc: Document, index: int, slot: int | None = None, method: str | None = None,
              rate: Rate | Literal[False] | None = False, label_text: str | None = None) -> None:
   """!Changes a map table (call inside doc.edit()).
   @param doc         encounter Document
   @param index       table index
   @param slot        new slot, or None
   @param method      new method name, or None
   @param rate        new rate, None to drop an override (shared references), False to keep it
   @param label_text  new label ("" removes it), or None
   @return None
   """
   t = table(doc, index)
   ns = t.get("slot") if slot is None else slot
   nm = t.get("method") if method is None else method
   if not isinstance(ns, int) or not 0 <= ns < MAX_SLOTS:
      raise DocumentError(f"slots are 0-{MAX_SLOTS - 1}")
   if any(o is not t and o.get("slot") == ns and o.get("method") == nm for o in tables(doc)):
      raise DocumentError(f"slot {ns} has a {nm!r} table already")
   # A field the table leaves out is only written when it is being changed.
   if "slot" in t or slot is not None:
      t["slot"] = ns
   if "method" in t or method is not None:
      t["method"] = nm
   if rate is None:
      if "table" not in t:
         raise DocumentError("a table with its own entries needs a rate")
      t.pop("rate", None)
   elif rate is not False:
      t["rate"] = check_rate(rate)
   if label_text is not None:
      if label_text:
         t.setdefault("editor", {})["label"] = label_text
      else:
         (t.get("editor") or {}).pop("label", None)
         if t.get("editor") == {}:
            del t["editor"]


def link_shared(doc: Document, index: int, name: str) -> None:
   """!Makes a map table use a shared table (its own entries and rate go; call inside doc.edit()).
   @param doc    a map's encounter Document
   @param index  table index
   @param name   shared table name
   @return None
   """
   t = table(doc, index)
   t.pop("entries", None)
   t.pop("rate", None)
   t["table"] = name


def unlink_shared(project: Project, doc: Document, index: int) -> None:
   """!Copies the shared table a map table uses into it, so it can be edited on its own (call inside doc.edit()).
   @param project  Project
   @param doc      a map's encounter Document
   @param index    table index
   @return None
   """
   t = table(doc, index)
   name = t.get("table")
   src = find_shared(project, name)
   if src is None:
      raise DocumentError(f"no shared table {name!r}")
   t.pop("table")
   t.setdefault("rate", copy.deepcopy(src.get("rate", DEFAULT_RATE)))
   t["entries"] = copy.deepcopy(src.get("entries", []))


def find_shared(project: Project, name: str) -> JsonDict | None:
   """!A shared table by name.
   @param project  Project
   @param name     its name
   @return the table object, or None
   """
   s = shared_doc(project)
   if s is None:
      return None
   return next((t for t in tables(s) if t.get("name") == name), None)


def resolved(project: Project, t: JsonDict) -> tuple[Rate | None, list[JsonDict]]:
   """!The rate and entries a table rolls with (a shared table's, for references).
   @param project  Project
   @param t        table object
   @return (rate as stored, entries list); entries is [] when a referenced table is missing
   """
   if "table" in t:
      src = find_shared(project, t["table"]) or {}
      # A reference's own rate, when it has one, overrides the shared table's.
      return t.get("rate", src.get("rate")), src.get("entries", [])
   return t.get("rate"), t.get("entries", [])


# -- entries ---------------------------------------------------------------------------------

def entries(doc: Document, index: int) -> list[JsonDict]:
   """!A table's own entries.
   @param doc    encounter Document
   @param index  table index
   @return the live list
   @throws DocumentError for a shared reference (edit the shared table, or unlink it)
   """
   t = table(doc, index)
   if "table" in t:
      raise DocumentError(f"this table uses the shared table {t['table']!r}: edit that one, or copy it here first")
   return t.setdefault("entries", [])


def _levels(levels: int | Sequence[int]) -> int | list[int]:
   """!Normalises levels.
   @param levels  int or [lo, hi]
   @return int or [lo, hi]
   """
   # bool is an int subclass, but True is no level.
   if isinstance(levels, int) and not isinstance(levels, bool):
      lo = hi = levels
   elif isinstance(levels, (list, tuple)) and len(levels) == LEVEL_RANGE_LENGTH:
      lo, hi = levels
   else:
      raise DocumentError("levels are a level or [lowest, highest]")
   if not all(isinstance(v, int) and not isinstance(v, bool) for v in (lo, hi)) or not 1 <= lo <= hi <= MAX_LEVEL:
      raise DocumentError(f"levels are 1-{MAX_LEVEL}, lowest first")
   return lo if lo == hi else [lo, hi]


def add_entry(doc: Document, index: int, species_name: str, levels: int | Sequence[int], weight: int = 1,
              requires: Iterable[str] | None = None, excludes: Iterable[str] | None = None,
              modifiers: list[JsonDict] | None = None) -> int:
   """!Adds an entry (call inside doc.edit()).
   @param doc           encounter Document
   @param index         table index
   @param species_name  species
   @param levels        level or [lowest, highest]
   @param weight        1-65535
   @param requires      condition names, or None
   @param excludes      condition names, or None
   @param modifiers     [{"when", "multiply"}], or None
   @return the new entry's index
   """
   es = entries(doc, index)
   if len(es) >= MAX_ENTRIES:
      raise DocumentError(f"a table has up to {MAX_ENTRIES} entries")
   # Appended with a valid weight first; set_entry() checks and sets the rest (and removes nothing on refusal).
   e = {"species": species_name, "levels": _levels(levels), "weight": 1}
   es.append(e)
   set_entry(doc, index, len(es) - 1, weight=weight, requires=requires, excludes=excludes, modifiers=modifiers)
   return len(es) - 1


def set_entry(doc: Document, index: int, entry: int, species_name: str | None = None,
              levels: int | Sequence[int] | None = None, weight: int | None = None,
              requires: Iterable[str] | None = None, excludes: Iterable[str] | None = None,
              modifiers: list[JsonDict] | None = None) -> None:
   """!Changes an entry; None keeps a field, [] clears a list (call inside doc.edit()).
   @param doc           encounter Document
   @param index         table index
   @param entry         entry index
   @param species_name  species
   @param levels        level or [lowest, highest]
   @param weight        1-65535
   @param requires      condition names
   @param excludes      condition names
   @param modifiers     [{"when", "multiply"}]
   @return None
   """
   es = entries(doc, index)
   if not 0 <= entry < len(es):
      raise DocumentError(f"no entry {entry}")
   e = es[entry]
   # Check everything first, so a refused change leaves the entry as it was.
   if species_name is not None and (not isinstance(species_name, str) or not species_name.strip()):
      raise DocumentError("an entry needs a species")
   lv = None if levels is None else _levels(levels)
   if weight is not None and (not isinstance(weight, int) or isinstance(weight, bool)
                              or not 1 <= weight <= MAX_WEIGHT):
      raise DocumentError(f"weights are 1-{MAX_WEIGHT}")
   if modifiers is not None:
      if len(modifiers) > MAX_MODIFIERS:
         raise DocumentError(f"an entry has up to {MAX_MODIFIERS} modifiers")
      ec = _ec()
      for m in modifiers:
         if set(m) != {"when", "multiply"}:
            raise DocumentError("a modifier is {\"when\": condition, \"multiply\": number}")
         try:
            # Only checks the multiplier (as Q8 fixed point); the value is stored as given.
            ec.q8(m["multiply"], f"multiplier for {m['when']}")
         except ec.ManifestError as err:
            raise DocumentError(str(err)) from None
   req = e.get("requires", []) if requires is None else list(requires)
   exc = e.get("excludes", []) if excludes is None else list(excludes)
   if set(req) & set(exc):
      raise DocumentError("a condition cannot be both required and excluded")
   if species_name is not None:
      e["species"] = species_name
   if lv is not None:
      e["levels"] = lv
   if weight is not None:
      e["weight"] = weight
   for key, value in (("requires", requires), ("excludes", excludes)):
      if value is not None:
         if value:
            e[key] = list(value)
         else:
            e.pop(key, None)
   if modifiers is not None:
      if modifiers:
         e["modifiers"] = [dict(m) for m in modifiers]
      else:
         e.pop("modifiers", None)


def remove_entry(doc: Document, index: int, entry: int) -> None:
   """!Removes an entry (call inside doc.edit()).
   @param doc    encounter Document
   @param index  table index
   @param entry  entry index
   @return None
   """
   es = entries(doc, index)
   if not 0 <= entry < len(es):
      raise DocumentError(f"no entry {entry}")
   del es[entry]


def move_entry(doc: Document, index: int, entry: int, delta: int) -> int:
   """!Moves an entry up or down (call inside doc.edit()).
   @param doc    encounter Document
   @param index  table index
   @param entry  entry index
   @param delta  -1 or 1
   @return its new index
   """
   es = entries(doc, index)
   to = entry + delta
   if not (0 <= entry < len(es) and 0 <= to < len(es)):
      return entry
   es[entry], es[to] = es[to], es[entry]
   return to


def parse_modifiers(text: str) -> list[JsonDict]:
   """!"rain x0, night x2.5" to modifier objects.
   @param text  comma-separated "condition xN" (N a number, "1/2" or "50%")
   @return list of {"when", "multiply"}
   """
   out = []
   for part in text.split(","):
      part = part.strip()
      if not part:
         continue
      if " x" not in part and "*" not in part:
         raise DocumentError(f"modifiers look like 'rain x0, night x2', got {part!r}")
      # "rain*2" reads as "rain x2"; the last " x" splits, so condition names may contain " x".
      when, _, mult = part.replace("*", " x").rpartition(" x")
      mult = mult.strip()
      # A number when it reads as one; anything else ("1/2", "50%") goes to the compiler as text.
      try:
         value = int(mult)
      except ValueError:
         try:
            value = float(mult)
         except ValueError:
            value = mult
      out.append({"when": when.strip(), "multiply": value})
   return out


def format_modifiers(mods: list[JsonDict] | None) -> str:
   """!Modifier objects as text ("rain x0, night x2").
   @param mods  list or None
   @return text
   """
   return ", ".join(f"{m.get('when')} x{m.get('multiply')}" for m in mods or [])


# -- renames that follow references ------------------------------------------------------------

def _refs(project: Project, kind: str, name: str) -> list[tuple[str | None, Document]]:
   """!Where a method, condition or shared table is used.
   @param project  Project
   @param kind     "method", "condition" or "shared"
   @param name     its name
   @return list of (map name or None, Document)
   """
   used = []
   for owner, doc in encounter_docs(project):
      hit = False
      for t in tables(doc):
         if kind == "method" and t.get("method") == name:
            hit = True
         if kind == "shared" and t.get("table") == name:
            hit = True
         if kind == "condition":
            for e in t.get("entries", []):
               if name in e.get("requires", []) or name in e.get("excludes", []) or \
                       any(m.get("when") == name for m in e.get("modifiers", [])):
                  hit = True
      if hit:
         used.append((owner, doc))
   return used


def _where(found: list[tuple[str | None, Document]]) -> str:
   """!Names of the files that use something.
   @param found  _refs() result
   @return text
   """
   return ", ".join("shared tables" if n is None else f"map {n}" for n, _ in found)


def rename(project: Project, kind: str, old: str, new: str) -> int:
   """!Renames a method, condition or shared table everywhere (one undo step per changed document).
   @param project  Project
   @param kind     "method", "condition" or "shared"
   @param old      current name
   @param new      new name
   @return number of documents changed
   """
   if not isinstance(new, str) or not new.strip():
      raise DocumentError("names cannot be empty")
   if old == new:
      return 0
   if kind == "method":
      names = method_names(project)
   elif kind == "condition":
      names = conditions(project)
   else:
      s = shared_doc(project)
      names = [t.get("name") for t in tables(s)] if s else []
   if old not in names:
      raise DocumentError(f"no {kind} {old!r}")
   if new in names:
      raise DocumentError(f"there is a {kind} {new!r} already")
   found = _refs(project, kind, old)
   changed = 0
   if kind in ("method", "condition"):
      with project.world.edit(f"Rename {kind}"):
         if kind == "method":
            next(m for m in _world_methods(project.world) if m.get("name") == old)["name"] = new
         else:
            cs = project.world.data["encounter_conditions"]
            cs[cs.index(old)] = new
      changed += 1
   else:
      s = shared_doc(project)
      with s.edit("Rename shared table"):
         next(t for t in tables(s) if t.get("name") == old)["name"] = new
      changed += 1
   for _owner, doc in found:
      with doc.edit(f"Rename {kind}"):
         for t in tables(doc):
            if kind == "method" and t.get("method") == old:
               t["method"] = new
            if kind == "shared" and t.get("table") == old:
               t["table"] = new
            if kind == "condition":
               for e in t.get("entries", []):
                  for key in ("requires", "excludes"):
                     if old in e.get(key, []):
                        e[key] = [new if c == old else c for c in e[key]]
                  for m in e.get("modifiers", []):
                     if m.get("when") == old:
                        m["when"] = new
      changed += 1 if doc is not project.world else 0
   return changed


def remove(project: Project, kind: str, name: str) -> None:
   """!Removes a method, condition or shared table, refused while something uses it (one undo step).
   @param project  Project
   @param kind     "method", "condition" or "shared"
   @param name     its name
   @return None
   """
   found = _refs(project, kind, name)
   if found:
      raise DocumentError(f"the {kind} {name!r} is used by {_where(found)}")
   if kind == "method":
      ms = methods(project)
      if not any(m.get("name") == name for m in ms):
         raise DocumentError(f"no method {name!r}")
      if len(ms) == 1:
         raise DocumentError("a world keeps at least one method")
      with project.world.edit("Remove method"):
         ms = _world_methods(project.world)
         ms[:] = [m for m in ms if m.get("name") != name]
   elif kind == "condition":
      if name not in conditions(project):
         raise DocumentError(f"no condition {name!r}")
      with project.world.edit("Remove condition"):
         project.world.data["encounter_conditions"].remove(name)
   else:
      s = shared_doc(project)
      if s is None or find_shared(project, name) is None:
         raise DocumentError(f"no shared table {name!r}")
      with s.edit("Remove shared table"):
         tables(s)[:] = [t for t in tables(s) if t.get("name") != name]


# -- previews and checks -----------------------------------------------------------------------

def weight_under(entry: JsonDict, active: set[str], condition_names: list[str]) -> int:
   """!An entry's weight under some active conditions, as the engine computes it
   (filtered out = 0; each active modifier multiplies in Q8, truncating).
   @param entry            entry object
   @param active           set of active condition names
   @param condition_names  the world's conditions
   @return weight (0 when filtered out or invalid)
   """
   if any(c not in active for c in entry.get("requires", [])) or any(c in active for c in entry.get("excludes", [])):
      return 0
   w = entry.get("weight", 0)
   if not isinstance(w, int) or isinstance(w, bool):
      return 0
   ec = _ec()
   for m in entry.get("modifiers", []):
      if m.get("when") in active:
         try:
            # Q8 multiply: the product has Q8_FRACTION_BITS fraction bits, dropped (truncating) by the shift.
            w = (w * ec.q8(m.get("multiply"), "multiply")) >> Q8_FRACTION_BITS
         except ec.ManifestError:
            return 0
   return w


def shares(project: Project, t: JsonDict, active: Iterable[str] = ()) -> list[tuple[JsonDict, int, float]]:
   """!How often each entry of a table comes up under some conditions.
   @param project  Project
   @param t        table object (map or shared)
   @param active   active condition names
   @return list of (entry object, weight, fraction 0-1), in entry order
   """
   _rate, es = resolved(project, t)
   names = conditions(project)
   ws = [weight_under(e, set(active), names) for e in es]
   total = sum(ws)
   return [(e, w, (w / total) if total else 0.0) for e, w in zip(es, ws)]


def slot_cells(map_data: JsonDict) -> dict[int, list[tuple[int, int]]]:
   """!Encounter cells per slot.
   @param map_data  map manifest
   @return {slot: [(x, y), ...]} in map order
   """
   out = {}
   fields = maps.cell_fields()
   enc_mask, enc_shift = fields[ENCOUNTER_FIELD]
   slot_mask, slot_shift = fields[SLOT_FIELD]
   for c in map_data.get("chunks", []):
      cx, cy = c["at"]
      for y, row in enumerate(c.get("cells", [])):
         for x, v in enumerate(row):
            # Attribute cells pack their fields (core.maps.cell_fields()): an encounter cell has its flag set.
            if v is not None and (v >> enc_shift) & enc_mask:
               # Chunk position (in chunks) and cell (in metatiles) to map metatiles.
               out.setdefault((v >> slot_shift) & slot_mask, []).append((cx * maps.CHUNK + x, cy * maps.CHUNK + y))
   return out


def slot_tables(project: Project, name: str) -> dict[int | None, list[tuple[str | None, JsonDict]]]:
   """!A map's tables by slot.
   @param project  Project
   @param name     map name
   @return {slot: [(method name, table object), ...]}
   """
   doc = map_doc(project, name)
   out = {}
   for t in tables(doc) if doc is not None else []:
      out.setdefault(t.get("slot"), []).append((t.get("method"), t))
   return out


def describe_slot(project: Project, name: str, slot: int) -> str:
   """!One line about a slot, for hover text: its tables, rates and species.
   @param project  Project
   @param name     map name
   @param slot     slot
   @return text
   """
   ts = slot_tables(project, name).get(slot, [])
   if not ts:
      return f"slot {slot}: no encounter table"
   parts = []
   for method, t in ts:
      rate, es = resolved(project, t)
      species_names = []
      for e in es:
         if e.get("species") not in species_names:
            species_names.append(e.get("species"))
      shown = ", ".join(species_names[:SPECIES_SHOWN]) + (", ..." if len(species_names) > SPECIES_SHOWN else "")
      title = label(t) or (f"shared {t['table']}" if "table" in t else "")
      # The rate as odds only ("1/10"), without the percentage format_rate() adds.
      parts.append(f"{method}{' ' + repr(title) if title else ''} {format_rate(rate).split(' ')[0]}: "
                   f"{shown or 'no entries'}")
   return f"slot {slot}: " + "; ".join(parts)


def diagnostics(project: Project, name: str | None = None) -> list[Diagnostic]:
   """!Encounter problems the compiler does not treat as errors, plus the
   compile error when it is about encounters.
   @param project  Project
   @param name     only this map, or None for all
   @return list of plugins.Diagnostic
   """
   from ..plugins.registry import Diagnostic
   out = []
   steps = set(step_methods(project))
   names = [name] if name else project.map_names()
   used_shared = set()
   for n in project.map_names() if name is None else []:   # I2: a map's check opens no other map
      d = map_doc(project, n)
      if d is not None:
         used_shared.update(t.get("table") for t in tables(d) if "table" in t)
   for n in names:
      cells = slot_cells(project.map(n).data)
      by_slot = slot_tables(project, n)
      for slot, at in sorted(cells.items()):
         if not any(m in steps for m, _t in by_slot.get(slot, [])):
            out.append(Diagnostic("warning", f"map {n}: {len(at)} encounter cell(s) in slot {slot}, which has "
                                             "no step table (nothing rolls there)", n, at[0]))
      # Tables without a slot sort last.
      for slot, ts in sorted(by_slot.items(), key=lambda kv: (kv[0] is None, kv[0])):
         for method, t in ts:
            if method in steps and slot not in cells:
               out.append(Diagnostic("info", f"map {n}: the {method} table of slot {slot} has no encounter "
                                             "cells", n))
            _rate, es = resolved(project, t)
            if "table" in t and find_shared(project, t["table"]) is None:
               out.append(Diagnostic("error", f"map {n}: slot {slot} uses shared table {t['table']!r}, "
                                              "which does not exist", n))
            elif not es:
               out.append(Diagnostic("warning", f"map {n}: the {method} table of slot {slot} has no entries "
                                                "(it never starts an encounter)", n))
            elif all(e.get("requires") for e in es):
               out.append(Diagnostic("info", f"map {n}: every entry of the {method} table of slot {slot} "
                                             "needs a condition (no encounter without one)", n))
   if name is None:
      s = shared_doc(project)
      for t in tables(s) if s is not None else []:
         if t.get("name") not in used_shared:
            out.append(Diagnostic("info", f"shared table {t.get('name')!r} is used by no map"))
   # I2: the engine's encounter compiler alone (compile_world() runs the same), not the whole world
   error = project.check_encounters([name] if name else None)
   if error and ("encounter" in error or "species" in error or "battle" in error):
      out.insert(0, Diagnostic("error", error, name))
   return out
