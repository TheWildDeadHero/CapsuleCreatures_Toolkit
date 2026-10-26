"""!The structure's growth sections (D-26 section 4, engine G4): "transformation"
(the context values rules read, which triggers a player may stop, the blocked
expression, learning, the form role) and "training" (the gain formula, the
caps, each stat's yield field).

    "transformation": {"context_values": [{"name": "time_of_day", "values": ["morning", "day", "evening", "night"]}],
                       "cancel": ["level_up"], "blocked": "held_item == still_stone && trigger != item_use",
                       "learn": true, "form_role": "form"},
    "training": {"gain": "train_gain", "stat_cap": 32, "total_cap": 96,
                 "yields": {"hp": "yield_hp", "attack": "yield_attack"}}

A context value is a game's number a `when` expression reads by name: named
values (value 0 first; the words name them) or a range, with a default (what
the default port answers). The context value named time_of_day comes from the
game's clock port. The gain names a ruleset formula taking (yield, value,
total, level); the stat cap is at most what the stat_training role holds.

The engine's tools/battlec/growth.py is the one authority (re-exported by
battle_compiler): compile_transformation(), compile_contexts(),
compile_training(), TRIGGERS, UNCANCELLABLE, TIME_OF_DAY, CONTEXT_SOURCES,
MAX_CONTEXT_VALUES, TRAIN_GAIN_ARGS and MAX_TRAINING.

Each editing helper is one change: call it inside one edit() of either
manifest and Undo takes the whole change back. An edit that stops data that
compiled from compiling is refused with the engine's message; a context value
a rule reads cannot go.
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict

from .. import battle, engine, logic
from ..document import Document, DocumentError
from . import record, species_fields

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure's transformation section.
TRANSFORMATION_KEY = "transformation"
## Its context values.
CONTEXTS_KEY = "context_values"
## Its triggers a player may stop.
CANCEL_KEY = "cancel"
## Its blocked expression.
BLOCKED_KEY = "blocked"
## Its "a transformed creature learns its new species' moves of its level".
LEARN_KEY = "learn"
## Its record role holding the form.
FORM_ROLE_KEY = "form_role"
## The fields set_transformation() sets.
TRANSFORMATION_FIELDS = (CANCEL_KEY, BLOCKED_KEY, LEARN_KEY, FORM_ROLE_KEY)
## A context value's name.
NAME_KEY = "name"
## A context value's named values.
VALUES_KEY = "values"
## A context value's range.
RANGE_KEY = "range"
## A context value's default.
DEFAULT_KEY = "default"
## The fields set_context() sets.
CONTEXT_FIELDS = (VALUES_KEY, RANGE_KEY, DEFAULT_KEY)
## Numbers of a range (lo, hi).
RANGE_LENGTH = 2
## The structure's training section.
TRAINING_KEY = "training"
## The training's gain formula.
GAIN_KEY = "gain"
## The training's most of one stat.
STAT_CAP_KEY = "stat_cap"
## The training's most of every stat together.
TOTAL_CAP_KEY = "total_cap"
## The training's yield fields, {stat: species field}.
YIELDS_KEY = "yields"
## Training key: the ruleset point each gain goes through in battle (engine C6; held items / passives change it).
POINT_KEY = "point"
## The fields set_training() sets.
TRAINING_FIELDS = (GAIN_KEY, STAT_CAP_KEY, TOTAL_CAP_KEY, POINT_KEY)
## The record role the training values live in (the engine's per-stat role).
TRAINING_ROLE = "stat_training"
## Location the compiler's messages name.
WHERE = "structure"


class ContextRow(TypedDict):
   """!One context value as the page and the CLI show it."""
   ## Position (battle_ids.h CONTEXT_<NAME> order).
   index: int
   ## Name.
   name: str
   ## Value names (value 0 first), or [].
   values: list[str]
   ## (lo, hi).
   range: tuple[int, int]
   ## Default value (number).
   default: int
   ## Where it comes from (a CONTEXT_SOURCES name).
   source: str
   ## The rules reading it.
   readers: list[str]


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


# -- the engine's lists ------------------------------------------------------------------------------------------------

def triggers() -> list[str]:
   """!The triggers (the engine's TRIGGERS).
   @return names
   """
   return list(_bc().TRIGGERS)


def cancellable() -> list[str]:
   """!The triggers whose transformation a player may stop (every trigger but the engine's UNCANCELLABLE).
   @return names
   """
   return [t for t in triggers() if t not in _bc().UNCANCELLABLE]


def clock_value() -> str:
   """!The context value the game's clock port answers.
   @return the engine's TIME_OF_DAY
   """
   return str(_bc().TIME_OF_DAY)


def sources() -> list[str]:
   """!Where context values come from.
   @return the engine's CONTEXT_SOURCES
   """
   return list(_bc().CONTEXT_SOURCES)


def max_contexts() -> int:
   """!Most context values.
   @return the engine's MAX_CONTEXT_VALUES
   """
   return int(_bc().MAX_CONTEXT_VALUES)


def gain_args() -> list[str]:
   """!What the training gain formula takes, in order.
   @return the engine's TRAIN_GAIN_ARGS
   """
   return list(_bc().TRAIN_GAIN_ARGS)


def max_training() -> int:
   """!Highest training value of one stat on any engine.
   @return the engine's MAX_TRAINING
   """
   return int(_bc().MAX_TRAINING)


# -- reading -----------------------------------------------------------------------------------------------------------

def _section(doc: Document, key: str) -> JsonDict | None:
   """!A section as stated.
   @param doc  any manifest Document of the battle
   @param key  TRANSFORMATION_KEY or TRAINING_KEY
   @return the dict, or None
   """
   value = battle.data_of(doc, key).get(key)
   return value if isinstance(value, dict) else None


def transformation(doc: Document) -> JsonDict:
   """!The transformation section with defaults filled in (a copy).
   @param doc  any manifest Document of the battle
   @return {"context_values", "cancel", "blocked", "learn", "form_role"}
   """
   given = _section(doc, TRANSFORMATION_KEY) or {}
   learn = given.get(LEARN_KEY, _bc().GROWTH_DEFAULT_LEARN)
   return {CONTEXTS_KEY: copy.deepcopy(given.get(CONTEXTS_KEY, [])), CANCEL_KEY: list(given.get(CANCEL_KEY, [])),
           BLOCKED_KEY: given.get(BLOCKED_KEY), LEARN_KEY: learn, FORM_ROLE_KEY: given.get(FORM_ROLE_KEY)}


def compiled(doc: Document) -> tuple[JsonDict | None, str | None]:
   """!The battle data compiled (the project's cached compile).
   @param doc  any manifest Document of the battle
   @return (compiled or None, error or None)
   """
   project: BattleProject | None = logic.project_of(doc)
   if project is None:
      return None, "the document is not part of a battle project"
   return project.compile()


def compile_check(doc: Document) -> tuple[JsonDict | None, str | None]:
   """!Compiles the transformation section alone with the engine's compile_transformation() (the layout from the
   record page's compile).
   @param doc  any manifest Document of the battle
   @return (compiled section or None, the compiler's message or None)
   """
   bc = _bc()
   layout, error = record.compile_record(doc)
   if layout is None:
      return None, error
   try:
      given = bc.strip(copy.deepcopy(_section(doc, TRANSFORMATION_KEY)))
      return bc.compile_transformation(given, layout, WHERE), None
   except Exception as e:   # ManifestError, type errors in odd data
      return None, str(e)


def context_rows(doc: Document) -> list[ContextRow]:
   """!The context values (their readers from the compiled rules).
   @param doc  any manifest Document of the battle
   @return one row per value
   """
   c, _error = compiled(doc)
   rules = c["transform"]["rules"] if c is not None else []
   # B1: the combination methods' expressions read context values too (their owners: "METHOD ...")
   rules = rules + [{"owner": f"combine_methods: {e['owner']}", "used": e["used"]}
                    for e in (c.get("combine") or {}).get("exprs", [])] if c is not None else rules
   clock = clock_value()
   out: list[ContextRow] = []
   for i, e in enumerate(transformation(doc)[CONTEXTS_KEY]):
      if not isinstance(e, dict) or not isinstance(e.get(NAME_KEY), str):
         continue
      name = e[NAME_KEY]
      values = [v for v in e.get(VALUES_KEY, []) if isinstance(v, str)]
      rng = e.get(RANGE_KEY)
      lo, hi = (rng[0], rng[1]) if isinstance(rng, list) and len(rng) == RANGE_LENGTH else (0, max(0, len(values) - 1))
      default = e.get(DEFAULT_KEY, lo)
      if isinstance(default, str):
         default = values.index(default) if default in values else lo
      src = sources()[1] if name == clock else sources()[0]
      out.append(ContextRow(index=i, name=name, values=values, range=(lo, hi), default=int(default), source=src,
                            readers=[r["owner"] for r in rules if name in r["used"]]))
   return out


def context_names(doc: Document | None) -> list[str]:
   """!The context value names.
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   return [r["name"] for r in context_rows(doc)] if doc is not None else []


def form_role_choices(doc: Document) -> list[str]:
   """!The record roles that may hold the form (custom roles of one element).
   @param doc  any manifest Document of the battle
   @return role names
   """
   return [r["name"] for r in record.role_rows(doc) if r["kind"] == record.KIND_CUSTOM and r["count"] == 1
           and isinstance(r["name"], str)]


def training(doc: Document) -> JsonDict | None:
   """!The training section with defaults filled in (a copy), or None (no training).
   @param doc  any manifest Document of the battle
   @return {"gain", "stat_cap", "total_cap", "yields", "point" (C6: a ruleset point, or None)} (the caps as the
           engine compiled them when it compiles)
   """
   given = _section(doc, TRAINING_KEY)
   if given is None:
      return None
   out = {GAIN_KEY: given.get(GAIN_KEY), STAT_CAP_KEY: given.get(STAT_CAP_KEY),
          TOTAL_CAP_KEY: given.get(TOTAL_CAP_KEY), YIELDS_KEY: dict(given.get(YIELDS_KEY) or {}),
          POINT_KEY: given.get(POINT_KEY)}
   c, _error = compiled(doc)
   tr = c["transform"]["training"] if c is not None else None
   if tr is not None:
      out[STAT_CAP_KEY], out[TOTAL_CAP_KEY] = tr[STAT_CAP_KEY], tr[TOTAL_CAP_KEY]
   return out


def stat_cap_max(doc: Document) -> int:
   """!The highest stat cap: what the record's training role holds, at most the engine's MAX_TRAINING.
   @param doc  any manifest Document of the battle
   @return the value (0 without the role)
   """
   row = next((r for r in record.role_rows(doc) if r["name"] == TRAINING_ROLE), None)
   if row is None or not isinstance(row["width"], int):
      return 0
   return min((1 << row["width"]) - 1, max_training())


def gain_formulas(doc: Document) -> list[str]:
   """!The ruleset's named formulas that take as many arguments as the training gain (TRAIN_GAIN_ARGS).
   @param doc  any manifest Document of the battle
   @return names
   """
   project: BattleProject | None = logic.project_of(doc)
   if project is None:
      return []
   want = len(gain_args())
   formulas = project.ruleset.data.get("formulas")
   out = []
   for name in battle.named_formulas(project.ruleset):
      f = formulas.get(name) if isinstance(formulas, dict) else None
      args = f.get("args") if isinstance(f, dict) else None
      if isinstance(args, (list, dict)) and len(args) == want:
         out.append(name)
   return out


# -- editing (inside one edit()) --------------------------------------------------------------------------------------

def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the section (or the whole battle data) compiled
   before and does not after (raised inside the edit, which puts the manifests back).
   @param doc     any manifest Document of the battle
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   project: BattleProject | None = logic.project_of(doc)
   _section_before, before = compile_check(doc)
   whole_before = project.error_now() if project is not None else None
   result = change()
   _section_after, error = compile_check(doc)
   if before is None and error is not None:
      raise DocumentError(error)
   if whole_before is None and project is not None:
      error = project.error_now()
      if error is not None:
         raise DocumentError(error)
   return result


def _live(doc: Document, key: str) -> JsonDict:
   """!A section for editing (created when the structure states none).
   @param doc  any manifest Document of the battle
   @param key  TRANSFORMATION_KEY or TRAINING_KEY
   @return the live dict
   """
   data = battle.data_of(doc, key)
   if not isinstance(data.get(key), dict):
      data[key] = {}
   return data[key]


def _tidy(doc: Document) -> None:
   """!Drops an empty transformation section (no rules need one).
   @param doc  any manifest Document of the battle
   @return None
   """
   data = battle.data_of(doc, TRANSFORMATION_KEY)
   if data.get(TRANSFORMATION_KEY) == {}:
      data.pop(TRANSFORMATION_KEY)


def set_transformation(doc: Document, field: str, value: Any) -> None:
   """!Sets one field of the transformation section (None: left out, the engine's default).
   @param doc    any manifest Document of the battle
   @param field  one of TRANSFORMATION_FIELDS
   @param value  cancel: trigger names (list or comma text); blocked: an expression; learn: true / false;
                 form_role: a role name
   @return None
   @throws DocumentError for an unknown field or a value the engine refuses
   """
   if field not in TRANSFORMATION_FIELDS:
      raise DocumentError(f"a transformation field is one of {', '.join(TRANSFORMATION_FIELDS)} (got {field!r})")
   if field == CANCEL_KEY:
      if isinstance(value, str):
         value = [t.strip() for t in value.split(",") if t.strip()]
      value = value or None
      for t in value or []:
         if t not in cancellable():
            raise DocumentError(f"cancel: triggers among {', '.join(cancellable())} (got {t!r}; an item's own "
                                f"logic transforms or fails)")
   elif field == BLOCKED_KEY and isinstance(value, str):
      value = value.strip() or None
   elif field == FORM_ROLE_KEY and value is not None and value not in form_role_choices(doc):
      raise DocumentError(f"form_role: a custom role of one element ({', '.join(form_role_choices(doc)) or 'none'})")
   elif field == LEARN_KEY and value is not None and not isinstance(value, bool):
      raise DocumentError("learn: true or false")

   def change() -> None:
      """!Writes the field.
      @return None
      """
      section = _live(doc, TRANSFORMATION_KEY)
      if value is None:
         section.pop(field, None)
      else:
         section[field] = value
      _tidy(doc)

   _guarded(doc, change)


def _context_index(doc: Document, name: str) -> int:
   """!A context value's index.
   @param doc   any manifest Document of the battle
   @param name  its name
   @return the index
   @throws DocumentError when there is none
   """
   names = [e.get(NAME_KEY) if isinstance(e, dict) else None for e in transformation(doc)[CONTEXTS_KEY]]
   if name not in names:
      raise DocumentError(f"no context value {name!r} (context values: "
                          f"{', '.join(n for n in names if isinstance(n, str)) or 'none'})")
   return names.index(name)


def add_context(doc: Document, name: str, values: list[str] | None = None, rng: tuple[int, int] | None = None,
                default: Any = None) -> int:
   """!Adds a context value (named values or a range; neither: the clock's time_of_day takes the clock's names).
   @param doc      any manifest Document of the battle
   @param name     a lower-case identifier
   @param values   value names (value 0 first), or None
   @param rng      (lo, hi), or None
   @param default  its default (a number or a value name), or None
   @return its index
   @throws DocumentError for a full list or data the engine refuses
   """
   if len(transformation(doc)[CONTEXTS_KEY]) >= max_contexts():
      raise DocumentError(f"at most {max_contexts()} context values (the engine's limit)")
   entry: JsonDict = {NAME_KEY: name.strip() if isinstance(name, str) else name}
   if values:
      entry[VALUES_KEY] = list(values)
   if rng is not None:
      entry[RANGE_KEY] = [int(rng[0]), int(rng[1])]
   if default is not None:
      entry[DEFAULT_KEY] = default

   def change() -> int:
      """!Appends the value.
      @return its index
      """
      section = _live(doc, TRANSFORMATION_KEY)
      lst = section.setdefault(CONTEXTS_KEY, [])
      lst.append(entry)
      return len(lst) - 1

   return _guarded(doc, change)


def remove_context(doc: Document, name: str) -> None:
   """!Removes a context value no rule reads.
   @param doc   any manifest Document of the battle
   @param name  its name
   @return None
   @throws DocumentError while a rule reads it
   """
   i = _context_index(doc, name)
   readers = next(r["readers"] for r in context_rows(doc) if r["name"] == name)
   if readers:
      raise DocumentError(f"{name!r} is read by {', '.join(readers)}: change those rules first")

   def change() -> None:
      """!Drops the value (and an empty list or section).
      @return None
      """
      section = _live(doc, TRANSFORMATION_KEY)
      section[CONTEXTS_KEY].pop(i)
      if not section[CONTEXTS_KEY]:
         section.pop(CONTEXTS_KEY)
      _tidy(doc)

   _guarded(doc, change)


def set_context(doc: Document, name: str, field: str, value: Any) -> None:
   """!Sets a context value's named values, range or default (None: left out).
   @param doc    any manifest Document of the battle
   @param name   its name
   @param field  one of CONTEXT_FIELDS
   @param value  values: names (list or comma text); range: (lo, hi) or "lo,hi"; default: a number or a name
   @return None
   @throws DocumentError for an unknown field or a value the engine refuses
   """
   i = _context_index(doc, name)
   if field not in CONTEXT_FIELDS:
      raise DocumentError(f"a context value's field is one of {', '.join(CONTEXT_FIELDS)} (got {field!r})")
   if isinstance(value, str) and field in (VALUES_KEY, RANGE_KEY):
      value = [v.strip() for v in value.split(",") if v.strip()] or None
   if field == RANGE_KEY and value is not None:
      try:
         value = [int(v) for v in value]
      except (TypeError, ValueError):
         raise DocumentError(f"range: two whole numbers lo,hi (got {value!r})") from None

   def change() -> None:
      """!Writes the field.
      @return None
      """
      entry = _live(doc, TRANSFORMATION_KEY)[CONTEXTS_KEY][i]
      if value is None or value == []:
         entry.pop(field, None)
      else:
         entry[field] = value

   _guarded(doc, change)


def enable_training(doc: Document, gain: str) -> None:
   """!Gives the structure training values (gain: a ruleset formula taking TRAIN_GAIN_ARGS).
   @param doc   any manifest Document of the battle
   @param gain  formula name
   @return None
   """
   if _section(doc, TRAINING_KEY) is not None:
      raise DocumentError("the structure already has training (set its gain instead)")
   _guarded(doc, lambda: _live(doc, TRAINING_KEY).update({GAIN_KEY: gain}))


def disable_training(doc: Document) -> None:
   """!Removes the training section (nothing is gained; the yield fields stay).
   @param doc  any manifest Document of the battle
   @return None
   """
   _guarded(doc, lambda: battle.data_of(doc, TRAINING_KEY).pop(TRAINING_KEY, None))


def set_training(doc: Document, field: str, value: Any) -> None:
   """!Sets the gain formula or a cap (a cap of None: the engine's default).
   @param doc    any manifest Document of the battle
   @param field  one of TRAINING_FIELDS
   @param value  the formula name or the cap
   @return None
   @throws DocumentError without training, for an unknown field or a value the engine refuses
   """
   if _section(doc, TRAINING_KEY) is None:
      raise DocumentError("the structure has no training (enable it first)")
   if field not in TRAINING_FIELDS:
      raise DocumentError(f"a training field is one of {', '.join(TRAINING_FIELDS)} (got {field!r})")
   if field not in (GAIN_KEY, POINT_KEY) and value is not None:
      try:
         value = int(value)
      except (TypeError, ValueError):
         raise DocumentError(f"{field}: a whole number (got {value!r})") from None

   def change() -> None:
      """!Writes the field.
      @return None
      """
      section = _live(doc, TRAINING_KEY)
      if value is None:
         section.pop(field, None)
      else:
         section[field] = value

   _guarded(doc, change)


def training_points(doc: Document) -> list[str]:
   """!The ruleset's points a training section may name (its "point": each gain goes through it in battle).
   @param doc  any manifest Document of the battle
   @return point names (from the compiled ruleset), [] when it does not compile
   """
   c, _error = compiled(doc)
   return list(((c or {}).get("pipelines") or {}).get("points") or {})


def follow_field_rename(doc: Document, old: str, new: str | None = None) -> int:
   """!A species field rename follows into the training yields (core.structure.species_fields.rename_field(); C6).
   @param doc  any manifest Document of the battle
   @param old  the field
   @param new  its new name, or None to only look
   @return the yields naming it
   """
   tr = _section(doc, TRAINING_KEY)
   given = tr.get(YIELDS_KEY) if tr is not None else None
   if not isinstance(given, dict):
      return 0
   stats = [st for st, field in given.items() if field == old]
   if new is not None:
      for st in stats:
         given[st] = new
   return len(stats)


def follow_role_rename(doc: Document, old: str, new: str | None = None) -> int:
   """!A custom role rename follows into the transformation's form_role (core.structure.record.rename_role(); C6).
   @param doc  any manifest Document of the battle
   @param old  the role
   @param new  its new name, or None to only look
   @return 1 when the section names it, else 0
   """
   section = _section(doc, TRANSFORMATION_KEY)
   if section is None or section.get(FORM_ROLE_KEY) != old:
      return 0
   if new is not None:
      section[FORM_ROLE_KEY] = new
   return 1


def context_order_warning(doc: Document, name: str, values: Any) -> str | None:
   """!What new value names do to a context value's numbers (C6, review4 finding 24): a value is its index, and the
   game's port function (and a saved script variable holding one) returns numbers, so a value that changes its
   index means another value to them. The editors ask, the CLI prints it.
   @param doc     any manifest Document of the battle
   @param name    the context value
   @param values  its new value names (list or comma text), or None
   @return the warning, or None (no value moves)
   """
   rows = [r for r in context_rows(doc) if r["name"] == name]
   if not rows or values is None:
      return None
   if isinstance(values, str):
      values = [v.strip() for v in values.split(",") if v.strip()]
   old = rows[0]["values"]
   moved = [f"{v!r} {k} -> {list(values).index(v)}" for k, v in enumerate(old)
            if v in values and list(values).index(v) != k]
   gone = [repr(v) for v in old if v not in values]
   if not moved and not gone:
      return None
   parts = (["moved: " + ", ".join(moved)] if moved else []) + (["gone: " + ", ".join(gone)] if gone else [])
   return (f"{name}'s values are numbered by position, and the game's port answers with numbers: "
           f"{'; '.join(parts)} (the game's code and saved variables keep the old numbers)")


def set_yield_field(doc: Document, stat: str, field: str | None) -> None:
   """!Names the species field holding a stat's yield (None: the stat gains nothing).
   @param doc    any manifest Document of the battle
   @param stat   stat name
   @param field  a species field, or None
   @return None
   @throws DocumentError without training, for an unknown stat or field
   """
   if _section(doc, TRAINING_KEY) is None:
      raise DocumentError("the structure has no training (enable it first)")
   stats = battle.stat_keys(doc)
   if stat not in stats:
      raise DocumentError(f"no stat {stat!r} ({', '.join(stats)})")
   if field is not None and field not in species_fields.field_names(doc):
      raise DocumentError(f"no species field {field!r} (Structure > Species fields)")

   def change() -> None:
      """!Writes (or drops) the stat's yield field, in the stats' order.
      @return None
      """
      section = _live(doc, TRAINING_KEY)
      given = dict(section.get(YIELDS_KEY) or {})
      if field is None:
         given.pop(stat, None)
      else:
         given[stat] = field
      ordered = {s: given[s] for s in stats if s in given}
      if ordered:
         section[YIELDS_KEY] = ordered
      else:
         section.pop(YIELDS_KEY, None)

   _guarded(doc, change)


# -- report ------------------------------------------------------------------------------------------------------------

def rule_rows(doc: Document) -> list[JsonDict]:
   """!Every compiled growth rule (the species' rules and forms, the blocked expression).
   @param doc  any manifest Document of the battle
   @return [{"id", "owner", "when", "on", "reads"}] ([] while the data does not compile)
   """
   c, _error = compiled(doc)
   if c is None:
      return []
   return [{"id": i, "owner": r["owner"], "when": str(r["expr"]), "on": list(r["on"]), "reads": list(r["used"])}
           for i, r in enumerate(c["transform"]["rules"])]


def lines(doc: Document) -> list[str]:
   """!Both sections as text (CLI `transformation show` / `training show`).
   @param doc  any manifest Document of the battle
   @return lines
   """
   t = transformation(doc)
   out = [f"cancel: {', '.join(t[CANCEL_KEY]) or 'none'} (stoppable: {', '.join(cancellable())})",
          f"blocked: {t[BLOCKED_KEY] or 'none'}", f"learn: {'yes' if t[LEARN_KEY] else 'no'}",
          f"form role: {t[FORM_ROLE_KEY] or 'none'}"]
   for r in context_rows(doc):
      named = f"values {', '.join(r['values'])}" if r["values"] else f"range {r['range'][0]}..{r['range'][1]}"
      out.append(f"context {r['index']} {r['name']} ({r['source']}): {named}, default {r['default']}; read by "
                 f"{', '.join(r['readers']) or 'no rule'}")
   tr = training(doc)
   if tr is None:
      out.append("training: none")
   else:
      out.append(f"training: gain {tr[GAIN_KEY]}({', '.join(gain_args())}), stat cap {tr[STAT_CAP_KEY]}, total cap "
                 f"{tr[TOTAL_CAP_KEY]}")
      out += [f"yield {stat}: species field {field}" for stat, field in tr[YIELDS_KEY].items()]
   return out
