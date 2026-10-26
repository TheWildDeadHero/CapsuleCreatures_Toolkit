"""!The species fields of battle data (engine E13a, D-23 section 2): the
structure manifest's "species_fields" list and each species' "fields".

    structure.json  "species_fields": [{"name": "gender_ratio", "width": 8, "default": 255},
                                       {"name": "letter_forms", "width": 1}]
    battle.json     "species": [{"name": "Mothlet", ..., "fields": {"gender_ratio": 127}}]

A species field is a numeric data column every species has (its "fields"
value, else the field's default, 0 when none is given), up to
MAX_SPECIES_FIELD_BITS bits wide and at most MAX_SPECIES_FIELDS of them.
The generation list's derived expressions read it as species.NAME (the
engine's species_inputs(); a Gen-3 gender from gender_ratio and the seed).
The engine's battlec/content.py is the one authority: compile_species_fields()
checks the list, compile_species() each species' values against it.

Each editing helper is one change: call it inside one edit() of either
manifest (the partner opens the other's step, so Undo takes the whole change
back). A rename follows the species' "fields" keys, the derived
expressions (core.structure.progression.rename_field()) and the effect logic
reading it as `species_field(NAME)` (C5: core.logic.references(), the
sources and the manifests' point handler code); a removal drops the species'
values and is refused while a derived expression or effect logic reads it;
a narrower width or a new default is refused (with the engine's message)
when a species' value no longer fits. An edit that stops data that compiled
from compiling is refused with the engine's message.

A species value equal to its field's default is not written: the species
then follows the field's default (set_value()).

B1 (D-28): a field may name its values ("values": ["sprite", "beast", ...],
value k the k-th name: a group field such as a race or a family); a species
then gives the name (or the number), combination tables and expressions
read the names (FIELD.VALUE). set_values() writes the names, rename_value()
renames one (the species, the default and the combination methods follow:
core.structure.combination.follow_field_value()).
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict

from .. import battle, engine, logic
from ..document import Document, DocumentError
from . import progression

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## B1: a field's value names.
VALUES_KEY = "values"
## The structure manifest's list of species fields.
FIELDS_KEY = progression.SPECIES_FIELDS_KEY
## A field's name.
NAME_KEY = "name"
## A field's width in bits.
WIDTH_KEY = "width"
## A field's value for a species that gives none.
DEFAULT_KEY = "default"
## The properties set_field() changes.
FIELD_PROPERTIES = (WIDTH_KEY, DEFAULT_KEY)
## A species' values, {field name: value}.
SPECIES_KEY = "fields"
## A field's default when it states none (battlec/content.py compile_species_fields()).
UNSTATED_DEFAULT = 0
## Location the compiler's messages name.
WHERE = "structure"
## The effect compiler's list effect logic names a species field from (`holder.species_field(NAME)`).
LOGIC_LISTS = ("species_fields",)
## Undo label of the effect logic's part of a rename.
RENAME_LABEL = "Rename species field"


class FieldRow(TypedDict):
   """!One species field as the page and the CLI show it."""
   ## Position in the list.
   index: int
   ## Field name (species.NAME in derived expressions).
   name: str
   ## Bits.
   width: int
   ## Highest value (2^width - 1).
   max: int
   ## Value of a species that gives none.
   default: int
   ## True when the field states its default.
   default_stated: bool
   ## Species giving a value of their own.
   species: int
   ## Derived entries reading it ("generation[k] (ROLE)"), then effect logic owners ("effects/moves.ceffect: move X").
   readers: list[str]
   ## B1: its value names (value k is the k-th), or [].
   values: list[str]


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def max_fields() -> int:
   """!Most species fields (the engine's MAX_SPECIES_FIELDS).
   @return count
   """
   return int(_bc().MAX_SPECIES_FIELDS)


def max_width() -> int:
   """!Widest species field (the engine's MAX_SPECIES_FIELD_BITS: derived expressions analyse int32 values).
   @return bits
   """
   return int(_bc().MAX_SPECIES_FIELD_BITS)


def prefix() -> str:
   """!The prefix a derived expression reads a field with (the engine's SPECIES_PREFIX).
   @return "species."
   """
   return str(_bc().SPECIES_PREFIX)


def _is_int(value: Any) -> bool:
   """!Whether a value is a whole number (not a bool).
   @param value  the value
   @return True for an int
   """
   return isinstance(value, int) and not isinstance(value, bool)


def top_of(width: Any) -> int:
   """!The highest value a field of a width holds.
   @param width  bits (an odd value: the widest field's)
   @return 2^width - 1
   """
   return (1 << (width if _is_int(width) and 0 < width <= max_width() else max_width())) - 1


def is_stated(doc: Document) -> bool:
   """!Whether the structure states species fields.
   @param doc  any manifest Document of the battle
   @return True when "species_fields" is given
   """
   return FIELDS_KEY in battle.data_of(doc, FIELDS_KEY)


def fields(doc: Document | None) -> list[JsonDict]:
   """!The species fields in order, default filled in.
   @param doc  any manifest Document of the battle, or None (none)
   @return [{"name", "width", "max", "default", "default_stated", "values"}] (entries that are not objects with a
           name are left out)
   """
   if doc is None:
      return []
   given = battle.data_of(doc, FIELDS_KEY).get(FIELDS_KEY)
   out = []
   for e in given if isinstance(given, list) else []:
      if isinstance(e, dict) and isinstance(e.get(NAME_KEY), str):
         width = e.get(WIDTH_KEY)
         names = e.get(VALUES_KEY)
         out.append({NAME_KEY: e[NAME_KEY], WIDTH_KEY: width, "max": top_of(width),
                     DEFAULT_KEY: e.get(DEFAULT_KEY, UNSTATED_DEFAULT), "default_stated": DEFAULT_KEY in e,
                     VALUES_KEY: [v for v in names if isinstance(v, str)] if isinstance(names, list) else []})
   return out


def field_names(doc: Document | None) -> list[str]:
   """!The field names in order.
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   return [f[NAME_KEY] for f in fields(doc)]


def _index(doc: Document, name: str) -> int:
   """!A field's index.
   @param doc   any manifest Document of the battle
   @param name  field name
   @return the index
   @throws DocumentError when there is no such field
   """
   names = field_names(doc)
   if name not in names:
      raise DocumentError(f"no species field {name!r} (fields: {', '.join(names) or 'none'})")
   return names.index(name)


def _species(doc: Document) -> list[JsonDict]:
   """!The species dicts of the battle data.
   @param doc  any manifest Document of the battle
   @return species dicts
   """
   return list(battle.entries(doc, "species"))


def _species_entry(doc: Document, species: str) -> JsonDict:
   """!One species.
   @param doc      any manifest Document of the battle
   @param species  species name
   @return the live dict
   @throws DocumentError when there is no such species
   """
   for s in _species(doc):
      if s.get(NAME_KEY) == species:
         return s
   raise DocumentError(f"no species {species!r}")


def users(doc: Document, name: str) -> list[str]:
   """!The species giving a field a value of their own.
   @param doc   any manifest Document of the battle
   @param name  field name
   @return "species X" strings
   """
   return [f"species {s.get(NAME_KEY)}" for s in _species(doc)
           if isinstance(s.get(SPECIES_KEY), dict) and name in s[SPECIES_KEY]]


def readers(doc: Document, name: str) -> list[str]:
   """!What reads a field: the derived expressions (species.NAME), then the effect logic's owners
   (`species_field(NAME)`: the sources and the manifests' point handler code, one per owner; C5).
   @param doc   any manifest Document of the battle
   @param name  field name
   @return "generation[k] (ROLE)" strings, then "FILE: KIND NAME" strings
   """
   from . import combination   # local: it imports core.structure
   return progression.field_readers(doc, name) + logic.per_owner(logic.references(doc, LOGIC_LISTS, name)) + \
      combination.follow_species_field(battle.merged(doc), name, None)


def field_rows(doc: Document) -> list[FieldRow]:
   """!The fields with what uses them.
   @param doc  any manifest Document of the battle
   @return one row per field
   """
   return [FieldRow(index=i, name=f[NAME_KEY], width=f[WIDTH_KEY], max=f["max"], default=f[DEFAULT_KEY],
                    default_stated=f["default_stated"], species=len(users(doc, f[NAME_KEY])),
                    readers=readers(doc, f[NAME_KEY]), values=list(f[VALUES_KEY]))
           for i, f in enumerate(fields(doc))]


def values_of(doc: Document, species: str) -> list[JsonDict]:
   """!A species' value of every field, as the Species page shows it.
   @param doc      any manifest Document of the battle
   @param species  species name
   @return [{"name", "value" (the species' own, else the field's default; a value name of a field with names),
           "own" (True when the species gives it), "max", "default", "values"}] in field order
   """
   s = _species_entry(doc, species)
   given = s.get(SPECIES_KEY) if isinstance(s.get(SPECIES_KEY), dict) else {}
   return [{NAME_KEY: f[NAME_KEY], "value": given.get(f[NAME_KEY], f[DEFAULT_KEY]), "own": f[NAME_KEY] in given,
            "max": f["max"], DEFAULT_KEY: f[DEFAULT_KEY], VALUES_KEY: list(f[VALUES_KEY])} for f in fields(doc)]


# -- the engine's compile ---------------------------------------------------------------------------------------------

def compile_check(doc: Document) -> tuple[list[JsonDict] | None, str | None]:
   """!Compiles the fields with the engine's compile_species_fields().
   @param doc  any manifest Document of the battle
   @return (compiled fields or None, the compiler's message or None)
   """
   bc = _bc()
   try:
      given = bc.strip(copy.deepcopy(battle.data_of(doc, FIELDS_KEY).get(FIELDS_KEY)))
      return bc.compile_species_fields(given, WHERE), None
   except Exception as e:   # ManifestError, type errors in odd data
      return None, str(e)


def _project_error(project: BattleProject | None) -> str | None:
   """!The battle data's compile error as the Documents hold it now.
   @param project  BattleProject, or None
   @return the message, or None (it compiles, or no project)
   """
   return project.error_now() if project is not None else None


def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the fields (or the whole battle data) compiled
   before and do not after (raised inside the edit, which puts the manifests back).
   @param doc     any manifest Document of the battle
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   project = logic.project_of(doc)
   _fields, before = compile_check(doc)
   whole_before = _project_error(project)
   result = change()
   _fields, error = compile_check(doc)
   if before is None and error is not None:
      raise DocumentError(error)
   if whole_before is None:
      error = _project_error(project)
      if error is not None:
         raise DocumentError(error)
   return result


def _live(doc: Document) -> list[JsonDict]:
   """!The field list for editing (written when the structure states none).
   @param doc  any manifest Document of the battle
   @return the live list
   """
   data = battle.data_of(doc, FIELDS_KEY)
   if not isinstance(data.get(FIELDS_KEY), list):
      data[FIELDS_KEY] = []
   return data[FIELDS_KEY]


def _check_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A field name: a lower-case identifier (the engine's SPECIES_FIELD_NAME) no other field has.
   @param doc      any manifest Document of the battle
   @param name     the wanted name
   @param current  the name being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   pattern = _bc().SPECIES_FIELD_NAME
   name = name.strip() if isinstance(name, str) else name
   if not isinstance(name, str) or not pattern.match(name):
      raise DocumentError(f"a species field's name is a lower-case identifier (got {name!r})")
   if name != current and name in field_names(doc):
      raise DocumentError(f"there is already a species field {name!r}")
   return name


def _width(value: Any) -> int:
   """!A field width the engine takes.
   @param value  wanted bits
   @return the width
   @throws DocumentError when it is not 1 to max_width()
   """
   if not _is_int(value) or not 1 <= value <= max_width():
      raise DocumentError(f"a species field is 1 to {max_width()} bits wide, got {value!r}")
   return value


def _value(value: Any, width: Any, what: str) -> Any:
   """!A value a field of a width holds.
   @param value  the value
   @param width  the field's bits
   @param what   what the value is, for the message
   @return the value (a value name as it is)
   @throws DocumentError when it does not fit
   """
   top = top_of(width)
   if isinstance(value, str):
      return value   # B1: a value name (the engine checks it against the field's names)
   if not _is_int(value) or not 0 <= value <= top:
      raise DocumentError(f"{what}: 0 to {top} ({width} bits), got {value!r}")
   return value


# -- editing (inside one edit()) -------------------------------------------------------------------------------------

def add_field(doc: Document, name: str, width: int, default: int | None = None, index: int | None = None) -> int:
   """!Adds a species field (every species then has its default).
   @param doc      any manifest Document of the battle
   @param name     a lower-case identifier
   @param width    bits (1 to max_width())
   @param default  the value of a species that gives none, or None for 0 (nothing written)
   @param index    position, or None for the end
   @return its index
   @throws DocumentError for a taken or invalid name, a full list or values that do not fit
   """
   name = _check_name(doc, name)
   width = _width(width)
   if len(field_names(doc)) >= max_fields():
      raise DocumentError(f"at most {max_fields()} species fields (the engine's limit)")
   entry: JsonDict = {NAME_KEY: name, WIDTH_KEY: width}
   if default is not None:
      entry[DEFAULT_KEY] = _value(default, width, f"{name} default")
   count = len(field_names(doc))
   at = count if index is None else max(0, min(count, int(index)))

   def change() -> int:
      """!Inserts the field.
      @return its index
      """
      _live(doc).insert(at, entry)
      return at

   return _guarded(doc, change)


def remove_field(doc: Document, name: str) -> list[str]:
   """!Removes a species field and every species' value of it (refused while a derived expression, effect logic or
   a field rule's expression reads it).
   @param doc   any manifest Document of the battle
   @param name  field name
   @return the species that lost their value ("species X")
   @throws DocumentError while something reads it
   """
   i = _index(doc, name)
   derived = progression.field_readers(doc, name)
   if derived:
      raise DocumentError(f"species field {name!r} is read by the derived expression of {', '.join(derived)}")
   owners = logic.per_owner(logic.references(doc, LOGIC_LISTS, name))
   if owners:
      raise DocumentError(f"species field {name!r} is read by effect logic: {', '.join(owners)}")
   from . import combination, field_expressions   # local: core.structure imports this module
   rules = field_expressions.follow_species_field(battle.merged(doc), name, None)
   if rules:
      raise DocumentError(f"species field {name!r} is read by the field rules: {', '.join(rules)}")
   # B1: the combination methods' expressions, tables, recipes and picks read species fields
   rules = combination.follow_species_field(battle.merged(doc), name, None)
   if rules:
      raise DocumentError(f"species field {name!r} is read by the combination methods: {', '.join(rules)}")
   from . import nursery   # local: it imports this module
   rules = nursery.follow_species_field(battle.merged(doc), name, None)   # B2: hatch cycles, egg look
   if rules:
      raise DocumentError(f"species field {name!r} is named by {', '.join(rules)}")
   lost = users(doc, name)

   def change() -> None:
      """!Drops the field and the species' values of it (an empty "fields" goes too).
      @return None
      """
      for s in _species(doc):
         given = s.get(SPECIES_KEY)
         if isinstance(given, dict) and name in given:
            del given[name]
            if not given:
               del s[SPECIES_KEY]
      del _live(doc)[i]

   _guarded(doc, change)
   return lost


def rename_field(doc: Document, old: str, new: str) -> int:
   """!Renames a species field; the species' values, the derived expressions and the effect logic reading it follow
   (C5: the logic's owners rewritten in the same undo step).
   @param doc  any manifest Document of the battle
   @param old  current name
   @param new  new name
   @return species, generation entries and effect logic uses updated
   """
   i = _index(doc, old)
   new = _check_name(doc, new, old)
   if new == old:
      return 0

   def change() -> int:
      """!Renames the field, the species' keys and the expressions.
      @return items updated
      """
      n = 0
      for s in _species(doc):
         given = s.get(SPECIES_KEY)
         if isinstance(given, dict) and old in given:
            # keep the keys' order: rebuild the object with the new key in the old one's place
            s[SPECIES_KEY] = {(new if k == old else k): v for k, v in given.items()}
            n += 1
      _live(doc)[i][NAME_KEY] = new
      followed = logic.references(doc, LOGIC_LISTS, old, new, RENAME_LABEL)
      # G3: the recruit section's rate reads a species field
      from . import combination, field_expressions, recruit, transformation   # local: they import this module
      # C8: the field rules' expressions (lead rules, field action requirements) read species.NAME
      rules = field_expressions.follow_species_field(battle.merged(doc), old, new)
      # B1: the combination methods (expressions, tables, recipes, picks)
      rules += combination.follow_species_field(battle.merged(doc), old, new)
      from . import nursery   # local: it imports this module
      rules += nursery.follow_species_field(battle.merged(doc), old, new)   # B2: hatch cycles, egg look
      # C6: the training yields name species fields too
      return (n + progression.rename_field(doc, old, new) + len(followed) + recruit.follow_field_rename(doc, old, new)
              + transformation.follow_field_rename(doc, old, new) + len(rules))

   return _guarded(doc, change)


def move_field(doc: Document, name: str, delta: int) -> bool:
   """!Moves a field up or down the list (its column in the generated kSpeciesFields; values stay by name).
   @param doc    any manifest Document of the battle
   @param name   field name
   @param delta  -1 earlier, +1 later
   @return True when it moved
   """
   i = _index(doc, name)
   j = i + delta
   if not 0 <= j < len(field_names(doc)):
      return False

   def change() -> None:
      """!Takes the field out and puts it back.
      @return None
      """
      lst = _live(doc)
      lst.insert(j, lst.pop(i))

   _guarded(doc, change)
   return True


def set_field(doc: Document, name: str, key: str, value: int | None) -> bool:
   """!Changes a field's width or default (None: the default goes back to 0; the width is required). A width every
   species' value and the default no longer fit in is refused.
   @param doc    any manifest Document of the battle
   @param name   field name
   @param key    one of FIELD_PROPERTIES
   @param value  the value, or None
   @return True when it changed
   """
   if key not in FIELD_PROPERTIES:
      raise DocumentError(f"unknown species field property {key!r} (properties: {', '.join(FIELD_PROPERTIES)}; "
                          "the name: rename)")
   i = _index(doc, name)
   entry = _live(doc)[i]
   if key == WIDTH_KEY:
      if value is None:
         raise DocumentError(f"a species field needs a width (1-{max_width()} bits)")
      value = _width(value)
      _value(entry.get(DEFAULT_KEY, UNSTATED_DEFAULT), value, f"{name} default")
      for s in _species(doc):
         given = s.get(SPECIES_KEY)
         if isinstance(given, dict) and name in given:
            _value(given[name], value, f"species {s.get(NAME_KEY)} {name}")
   elif isinstance(value, str):
      names = entry.get(VALUES_KEY) if isinstance(entry.get(VALUES_KEY), list) else []
      if value not in names:
         raise DocumentError(f"{value!r} is not a value of {name!r} ({', '.join(names) or 'none named'})")
   elif value is not None:
      value = _value(value, entry.get(WIDTH_KEY), f"{name} default")
   before = copy.deepcopy(entry)

   def change() -> None:
      """!Writes the property.
      @return None
      """
      live = _live(doc)[i]
      if value is None or (key == DEFAULT_KEY and value == UNSTATED_DEFAULT):
         live.pop(key, None)
      else:
         live[key] = value

   _guarded(doc, change)
   return _live(doc)[i] != before


def set_value(doc: Document, species: str, name: str, value: int | str | None) -> bool:
   """!Sets a species' value of a field (battle.json species[].fields). None, or the field's default, drops the
   species' own value: it then follows the field's default.
   @param doc      any manifest Document of the battle
   @param species  species name
   @param name     field name
   @param value    the value (0 to the field's highest, or one of its value names), or None
   @return True when it changed
   """
   i = _index(doc, name)
   f = fields(doc)[i]
   if isinstance(value, str):
      if value not in f[VALUES_KEY]:
         raise DocumentError(f"{value!r} is not a value of {name!r} ({', '.join(f[VALUES_KEY]) or 'none named'})")
   elif value is not None:
      value = _value(value, f[WIDTH_KEY], f"species {species} {name}")
   s = _species_entry(doc, species)
   before = copy.deepcopy(s.get(SPECIES_KEY))

   def change() -> None:
      """!Writes or drops the value (an empty "fields" goes).
      @return None
      """
      given = s.get(SPECIES_KEY)
      if not isinstance(given, dict):
         given = {}
      if value is None or value == f[DEFAULT_KEY]:
         given.pop(name, None)
      else:
         given[name] = value
      if given:
         s[SPECIES_KEY] = given
      else:
         s.pop(SPECIES_KEY, None)

   _guarded(doc, change)
   return s.get(SPECIES_KEY) != before


def set_values(doc: Document, name: str, values: list[str] | str | None) -> bool:
   """!Sets a field's value names (B1: value k is the k-th name; a list or comma text; None or empty: none). The
   engine refuses names that do not fit the width, and species or a default giving a name the list loses.
   @param doc     any manifest Document of the battle
   @param name    field name
   @param values  the names
   @return True when they changed
   """
   if isinstance(values, str):
      values = [v.strip() for v in values.split(",") if v.strip()]
   values = list(values or [])
   i = _index(doc, name)
   before = copy.deepcopy(_live(doc)[i])

   def change() -> None:
      """!Writes the names.
      @return None
      """
      live = _live(doc)[i]
      if values:
         live[VALUES_KEY] = values
      else:
         live.pop(VALUES_KEY, None)

   _guarded(doc, change)
   return _live(doc)[i] != before


def rename_value(doc: Document, name: str, old: str, new: str) -> int:
   """!Renames one of a field's value names; the species giving it, the field's default and the combination methods
   (tables, recipes, FIELD.VALUE words) follow.
   @param doc   any manifest Document of the battle
   @param name  field name
   @param old   the value name
   @param new   its new name
   @return the places updated
   """
   i = _index(doc, name)
   names = fields(doc)[i][VALUES_KEY]
   new = new.strip() if isinstance(new, str) else new
   if old not in names:
      raise DocumentError(f"{old!r} is not a value of {name!r} ({', '.join(names) or 'none named'})")
   if not isinstance(new, str) or not new or (new != old and new in names):
      raise DocumentError(f"a value name of its own, got {new!r}")

   def change() -> int:
      """!Renames it everywhere.
      @return items updated
      """
      live = _live(doc)[i]
      live[VALUES_KEY] = [new if v == old else v for v in live[VALUES_KEY]]
      n = 0
      if live.get(DEFAULT_KEY) == old:
         live[DEFAULT_KEY] = new
         n += 1
      for s in _species(doc):
         given = s.get(SPECIES_KEY)
         if isinstance(given, dict) and given.get(name) == old:
            given[name] = new
            n += 1
      from . import combination   # local: it imports core.structure
      return n + len(combination.follow_field_value(battle.merged(doc), name, old, new))

   return _guarded(doc, change)


# -- report ------------------------------------------------------------------------------------------------------------

def row_text(row: FieldRow) -> str:
   """!A field as the CLI's `species-field list` prints it.
   @param row  field_rows() row
   @return text
   """
   default = f"default {row['default']}" + ("" if row["default_stated"] else " (unstated)")
   named = row.get(VALUES_KEY) or []
   text = f"{row['index']} {row['name']}: {row['width']} bit(s) (0-{row['max']}), {default}; " \
          f"{row['species']} species give their own" + (f"; values {', '.join(named)}" if named else "")
   if row["readers"]:
      text += f"; read by {', '.join(row['readers'])}"
   return text


def lines(doc: Document) -> list[str]:
   """!The fields as text lines, then the count against the limit and the compiler's message.
   @param doc  any manifest Document of the battle
   @return lines
   """
   out = [row_text(r) for r in field_rows(doc)]
   out.append(f"{len(out)}/{max_fields()} species fields (read as {prefix()}NAME in derived expressions)")
   _compiled, error = compile_check(doc)
   if error:
      out.append(f"error: {error}")
   return out
