"""!Species growth (D-26 section 4, engine G4): each species' transformation
rules, its forms and its training yields, with previews from the engine's own
evaluator.

    battle.json  "species": [{"name": "Sproutle", ...,
                              "transforms": [{"into": "Sprouthorn", "when": "level >= 20", "on": ["level_up"]},
                                             {"into": "Sprigshield", "when": "item == bloom_charm"}],
                              "forms": [{"name": "Radiant", "types": ["Light"], "when": "time_of_day == night"},
                                        {"name": "base", "when": "time_of_day == day"}],
                              "fields": {"yield_hp": 1}}]

A rule's `when` is an expression over the record's roles, its stats
(stat.NAME), its species' fields (species.NAME), the trigger, the item and the
structure's context values (Structure > Growth); `on` lists the triggers it is
looked at for (left out: every trigger its expression can hold for, the
engine's analysis). The first rule that holds wins. A form overrides some of
the species' types, base stats, passives and sprites; a form with `when`
is chosen by rules (written to the record's form role), one without only by
the effect primitive `form WHO NAME`; a "base" entry is the rule back to the
species' own form. A species' yields are the species fields the structure's
training names for each stat (Structure > Growth).

The engine's tools/battlec/growth.py is the one authority (re-exported by
battle_compiler): TRIGGERS, ITEM_TRIGGERS, MAX_TRANSFORMS, MAX_FORMS,
BASE_FORM, form_names_of(), find_change(), when_values(), growth_holds(),
training_gain() and form_view(); the studio copies none of them.

Each editing helper is one change: call it inside one edit() of either
manifest and Undo takes the whole change back. An edit that stops data that
compiled from compiling is refused with the engine's message. A form rename
follows the effect logic naming it (`form holder NAME`) when no other species
has a form of that name; a species rename follows the rules naming it
(core.battle.references()).
"""
from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict

from . import battle, engine, logic
from .document import Document, DocumentError
from .structure import species_fields

if TYPE_CHECKING:
   from .battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## A species' transformation rules.
TRANSFORMS_KEY = "transforms"
## A species' forms.
FORMS_KEY = "forms"
## A rule's species.
INTO_KEY = "into"
## A rule's (or a form's) expression.
WHEN_KEY = "when"
## A rule's (or a form's) triggers.
ON_KEY = "on"
## A rule's "the held item is used up".
TAKES_ITEM_KEY = "takes_item"
## A rule's second creature.
ALSO_KEY = "also"
## The fields set_transform() sets.
TRANSFORM_FIELDS = (INTO_KEY, WHEN_KEY, ON_KEY, TAKES_ITEM_KEY, ALSO_KEY)
## A form's name.
NAME_KEY = "name"
## The overrides a form may give (each left out: the species' own).
FORM_OVERRIDES = ("types", "base", "passives", "front", "back")
## The fields set_form() sets.
FORM_FIELDS = FORM_OVERRIDES + (WHEN_KEY, ON_KEY)
## The effect compiler's list a form name is from (`form WHO NAME`).
LOGIC_LIST = "forms"
## Undo label of the effect logic's part of a form rename.
RENAME_LABEL = "Rename form"
## The structure's training section (its yields: {stat: species field}).
TRAINING_KEY = "training"
## The training section's yields.
YIELDS_KEY = "yields"
## The structure's transformation section (its blocked expression may name items).
TRANSFORMATION_KEY = "transformation"
## The transformation section's blocked expression.
BLOCKED_KEY = "blocked"


class TransformRow(TypedDict):
   """!One transformation rule as the page and the CLI show it."""
   ## Position (the first that holds wins).
   index: int
   ## The species it becomes.
   into: str
   ## Its expression.
   when: str
   ## Its triggers as given, or None (the engine works them out).
   on: list[str] | None
   ## The triggers it is looked at for (the compiled `on`; [] while the data does not compile).
   triggers: list[str]
   ## The held item is used up.
   takes_item: bool
   ## A second creature made beside it, or None.
   also: str | None


class FormRow(TypedDict):
   """!One form as the page and the CLI show it."""
   ## Its form number (the form role's value), or 0 for the "base" rule.
   form: int
   ## Its name.
   name: str
   ## True for the "base" entry (the rule back to the species' own form).
   is_base: bool
   ## The overrides it gives (FORM_OVERRIDES keys).
   overrides: list[str]
   ## Its expression, or None (effect logic only).
   when: str | None
   ## Its triggers as given, or None.
   on: list[str] | None


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


# -- the engine's lists ------------------------------------------------------------------------------------------------

def triggers() -> list[str]:
   """!The triggers a rule may name (the engine's TRIGGERS, capsule::growth::Trigger order).
   @return names
   """
   return list(_bc().TRIGGERS)


def item_triggers() -> list[str]:
   """!The triggers that carry an item (item_use: the item used; trade: the held item).
   @return names
   """
   return list(_bc().ITEM_TRIGGERS)


def base_form() -> str:
   """!The name of a species' own form (form 0; the rule entry back to it).
   @return the engine's BASE_FORM
   """
   return str(_bc().BASE_FORM)


def max_transforms() -> int:
   """!Most transformation rules of one species.
   @return the engine's MAX_TRANSFORMS
   """
   return int(_bc().MAX_TRANSFORMS)


def max_forms() -> int:
   """!Most forms of one species besides the species itself.
   @return the engine's MAX_FORMS
   """
   return int(_bc().MAX_FORMS)


def form_names(doc: Document | None) -> list[str]:
   """!Every form name of the battle, "base" first (the ids effect logic's `form` names; engine form_names_of()).
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   if doc is None:
      return [base_form()]
   return list(_bc().form_names_of([s for s in battle.entries(doc, "species") if isinstance(s, dict)]))


# -- reading -----------------------------------------------------------------------------------------------------------

def _species(doc: Document, name: str) -> JsonDict:
   """!A species entry (live).
   @param doc   any manifest Document of the battle
   @param name  species name
   @return the dict
   """
   return battle.entry(doc, "species", name)


def _list_of(entry: JsonDict, key: str) -> list[JsonDict]:
   """!A species' rules or forms (entries that are not objects are left out).
   @param entry  species dict
   @param key    TRANSFORMS_KEY or FORMS_KEY
   @return the dicts
   """
   given = entry.get(key)
   return [e for e in given if isinstance(e, dict)] if isinstance(given, list) else []


def compiled(doc: Document) -> tuple[JsonDict | None, str | None]:
   """!The battle data compiled (the project's cached compile).
   @param doc  any manifest Document of the battle
   @return (compiled or None, error or None)
   """
   project: BattleProject | None = logic.project_of(doc)
   if project is None:
      return None, "the document is not part of a battle project"
   return project.compile()


def _compiled_species(c: JsonDict, name: str) -> JsonDict | None:
   """!A species' compiled growth entry.
   @param c     compiled battle data
   @param name  species name
   @return {"name", "transforms", "forms", "base_rule", "base_triggers"}, or None
   """
   return next((sg for sg in c["transform"]["species"] if sg["name"] == name), None)


def _trigger_names(mask: int) -> list[str]:
   """!The trigger names of a mask.
   @param mask  bit per trigger
   @return names
   """
   return [t for i, t in enumerate(triggers()) if mask >> i & 1]


def transforms(doc: Document, species: str) -> list[TransformRow]:
   """!A species' transformation rules.
   @param doc      any manifest Document of the battle
   @param species  species name
   @return rows, in order
   """
   given = _list_of(_species(doc, species), TRANSFORMS_KEY)
   c, _error = compiled(doc)
   sg = _compiled_species(c, species) if c is not None else None
   out: list[TransformRow] = []
   for i, t in enumerate(given):
      masks = sg["transforms"][i]["triggers"] if sg is not None and i < len(sg["transforms"]) else 0
      on = t.get(ON_KEY)
      out.append(TransformRow(index=i, into=str(t.get(INTO_KEY, "")), when=str(t.get(WHEN_KEY, "")),
                              on=list(on) if isinstance(on, list) else None, triggers=_trigger_names(masks),
                              takes_item=bool(t.get(TAKES_ITEM_KEY, False)), also=t.get(ALSO_KEY)))
   return out


def forms(doc: Document, species: str) -> list[FormRow]:
   """!A species' forms (the "base" rule entry with form 0).
   @param doc      any manifest Document of the battle
   @param species  species name
   @return rows, in order
   """
   out: list[FormRow] = []
   number = 0
   for f in _list_of(_species(doc, species), FORMS_KEY):
      name = str(f.get(NAME_KEY, ""))
      is_base = name.lower() == base_form()
      if not is_base:
         number += 1
      on = f.get(ON_KEY)
      out.append(FormRow(form=0 if is_base else number, name=name, is_base=is_base,
                         overrides=[k for k in FORM_OVERRIDES if k in f], when=f.get(WHEN_KEY),
                         on=list(on) if isinstance(on, list) else None))
   return out


def form(doc: Document, species: str, name: str) -> JsonDict:
   """!A copy of one form entry.
   @param doc      any manifest Document of the battle
   @param species  species name
   @param name     form name
   @return the dict
   """
   return copy.deepcopy(_list_of(_species(doc, species), FORMS_KEY)[_form_index(doc, species, name)])


def _training(doc: Document) -> JsonDict | None:
   """!The structure's training section.
   @param doc  any manifest Document of the battle
   @return the dict, or None (no training)
   """
   tr = battle.data_of(doc, TRAINING_KEY).get(TRAINING_KEY)
   return tr if isinstance(tr, dict) else None


def yields(doc: Document, species: str) -> list[JsonDict]:
   """!A species' training yields: for each stat the structure's training names a yield field for, its value.
   @param doc      any manifest Document of the battle
   @param species  species name
   @return [{"stat", "field", "value", "max", "own"}] in the training's order ([] without training)
   """
   tr = _training(doc)
   given = tr.get(YIELDS_KEY) if tr is not None else None
   values = {v["name"]: v for v in species_fields.values_of(doc, species)}
   out = []
   for stat, field in (given.items() if isinstance(given, dict) else []):
      v = values.get(field)
      if v is not None:
         out.append({"stat": stat, "field": field, "value": v["value"], "max": v["max"], "own": v["own"]})
   return out


def when_words(doc: Document) -> JsonDict:
   """!What a `when` expression may read and name (the compiled scope; the Transformations box's help and
   completion).
   @param doc  any manifest Document of the battle
   @return {"inputs": {name: (lo, hi)}, "triggers": names, "items": item words, "contexts": {name: value names}}
           (empty lists while the data does not compile)
   """
   c, _error = compiled(doc)
   if c is None:
      return {"inputs": {}, "triggers": triggers(), "items": [], "contexts": {}}
   scope = c["transform"]["scope"]
   prefix = _bc().ITEM_PREFIX
   items = sorted(w for w in scope.constants if w.startswith(prefix))
   contexts = {cv["name"]: list(cv["values"]) for cv in c["transform"]["transformation"]["contexts"]}
   return {"inputs": dict(scope.ranges), "triggers": triggers(), "items": items, "contexts": contexts}


# -- previews (the engine's evaluator) --------------------------------------------------------------------------------

def preview(doc: Document, species: str, roles: JsonDict, trigger: str, item: str | None = None,
            context: JsonDict | None = None) -> JsonDict:
   """!Which rule fires for a record of a species in a trigger context (the engine's find_change(), the same order
   as growth::find()), and every rule of the species with whether it holds.
   @param doc      any manifest Document of the battle
   @param species  species name
   @param roles    record roles ({"level": 20, "stat_training": {"hp": 4}, "form": 1, ...}; left out: their derived
                   value or 0)
   @param trigger  a trigger name
   @param item     the context's item name (item_use / trade), or None
   @param context  context values by name (a number or one of its value names); left out: their defaults
   @return {"found": find_change() result or None, "text": what happens, "rules": [{"owner", "when", "on",
           "listens", "holds"}]}
   @throws DocumentError when the data does not compile or an input is unknown
   """
   bc = _bc()
   c, error = compiled(doc)
   if c is None:
      raise DocumentError(error or "the battle data does not compile")
   if trigger not in triggers():
      raise DocumentError(f"trigger: one of {', '.join(triggers())} (got {trigger!r})")
   if item is not None and item not in c["names"]["items"]:
      raise DocumentError(f"no item {item!r}")
   sg = _compiled_species(c, species)
   if sg is None:
      raise DocumentError(f"no species {species!r}")
   contexts = {cv["name"]: cv for cv in c["transform"]["transformation"]["contexts"]}
   for name, value in (context or {}).items():
      if name not in contexts:
         raise DocumentError(f"no context value {name!r} (Structure > Growth: {', '.join(contexts) or 'none'})")
      if isinstance(value, str) and value not in contexts[name]["values"]:
         raise DocumentError(f"{name}: one of {', '.join(contexts[name]['values'])} (got {value!r})")
   record = {"species": species, "level": 1, **roles}
   try:
      found = bc.find_change(c, record, trigger, item, context)
      values = bc.when_values(c, record, trigger, item, context)
   except (KeyError, ValueError, TypeError) as e:
      raise DocumentError(f"the record does not fit the layout: {e}") from None
   bit = 1 << triggers().index(trigger)
   rules = []
   owned = [(t["rule"], t["triggers"]) for t in sg["transforms"]] + \
      [(f["rule"], f["triggers"]) for f in sg["forms"] if f["rule"] is not None]
   if sg["base_rule"] is not None:
      owned.append((sg["base_rule"], sg["base_triggers"]))
   if c["transform"]["blocked"] is not None:
      owned.insert(0, (c["transform"]["blocked"], c["transform"]["rules"][c["transform"]["blocked"]]["triggers"]))
   for rid, mask in owned:
      r = c["transform"]["rules"][rid]
      rules.append({"owner": r["owner"], "when": str(r["expr"]), "on": list(r["on"]),
                    "listens": bool(mask & bit), "holds": bool(bc.growth_holds(c, rid, values))})
   return {"found": found, "text": change_text(found), "rules": rules}


def change_text(found: JsonDict | None) -> str:
   """!A find_change() result in words.
   @param found  the result, or None
   @return e.g. "becomes Sprouthorn", "takes the form Radiant", "blocked", "nothing happens"
   """
   if found is None:
      return "nothing happens"
   if found["kind"] == "blocked":
      return "blocked (the structure's blocked expression holds)"
   if found["kind"] == "form":
      return f"takes the form {found['name']} (form {found['form']})"
   text = f"becomes {found['into']}"
   if found.get("also"):
      text += f" (and {found['also']} joins the party)"
   if found.get("takes_item"):
      text += ", using up the held item"
   return text


def training_preview(doc: Document, foe: str, level: int, training: list[int] | None = None) -> JsonDict:
   """!What defeating one foe gives each stat (the engine's training_gain(): its gain formula, the total cap first,
   then the stat cap).
   @param doc       any manifest Document of the battle
   @param foe       the defeated species
   @param level     the receiver's level
   @param training  the receiver's training values (one per stat; default 0)
   @return {"before", "after", "gain" (per stat), "stats" (names)}
   @throws DocumentError when the data does not compile, the battle has no training or the foe is unknown
   """
   c, error = compiled(doc)
   if c is None:
      raise DocumentError(error or "the battle data does not compile")
   if c["transform"]["training"] is None:
      raise DocumentError("the structure has no training (Structure > Growth)")
   if foe not in [s["name"] for s in c["species"]]:
      raise DocumentError(f"no species {foe!r}")
   names = [st["name"] for st in c["stats"]]
   before = list(training) if training is not None else [0] * len(names)
   if len(before) != len(names):
      raise DocumentError(f"one training value per stat ({' '.join(names)})")
   battle.check_level(battle.structure_doc(doc), level)
   after = _bc().training_gain(c, before, foe, level)
   return {"before": before, "after": after, "gain": [a - b for a, b in zip(after, before)], "stats": names}


# -- editing (inside one edit()) --------------------------------------------------------------------------------------

def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the battle data compiled before and does not after
   (raised inside the edit, which puts the manifests back).
   @param doc     any manifest Document of the battle
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   project: BattleProject | None = logic.project_of(doc)
   before = project.error_now() if project is not None else None
   result = change()
   if before is None and project is not None:
      error = project.error_now()
      if error is not None:
         raise DocumentError(error)
   return result


def _live(entry: JsonDict, key: str) -> list[Any]:
   """!A species' rule or form list for editing (created when absent).
   @param entry  species dict
   @param key    TRANSFORMS_KEY or FORMS_KEY
   @return the live list
   """
   if not isinstance(entry.get(key), list):
      entry[key] = []
   return entry[key]


def _tidy(entry: JsonDict, key: str) -> None:
   """!Drops an empty rule or form list.
   @param entry  species dict
   @param key    TRANSFORMS_KEY or FORMS_KEY
   @return None
   """
   if entry.get(key) == []:
      entry.pop(key)


def _check_triggers(on: Any) -> list[str] | None:
   """!A rule's `on` (None: the engine works it out).
   @param on  a list of trigger names, a comma separated text, or None
   @return the list, or None
   @throws DocumentError for an unknown trigger
   """
   if on is None or on == "" or on == []:
      return None
   if isinstance(on, str):
      on = [t.strip() for t in on.split(",") if t.strip()]
   if not isinstance(on, list) or not all(t in triggers() for t in on):
      raise DocumentError(f"on: triggers among {', '.join(triggers())} (got {on!r})")
   return list(dict.fromkeys(on))


def _check_species(doc: Document, name: Any, what: str) -> str:
   """!A species name of the battle.
   @param doc   any manifest Document of the battle
   @param name  the name
   @param what  the field, for the message
   @return the name
   @throws DocumentError when there is no such species
   """
   names = [s.get("name") for s in battle.entries(doc, "species") if isinstance(s, dict)]
   if name not in names:
      raise DocumentError(f"{what}: a species of the battle (got {name!r})")
   return str(name)


def add_transform(doc: Document, species: str, into: str, when: str, on: Any = None, takes_item: bool = False,
                  also: str | None = None, index: int | None = None) -> int:
   """!Adds a transformation rule.
   @param doc         any manifest Document of the battle
   @param species     species name
   @param into        the species it becomes
   @param when        its expression
   @param on          its triggers (None: every trigger its expression can hold for)
   @param takes_item  the held item is used up
   @param also        a second creature made beside it, or None
   @param index       position, or None for the end
   @return its index
   @throws DocumentError for a full list, an unknown species or trigger, or data the engine then refuses
   """
   entry = _species(doc, species)
   _check_species(doc, into, INTO_KEY)
   if also is not None:
      _check_species(doc, also, ALSO_KEY)
   if not isinstance(when, str) or not when.strip():
      raise DocumentError("when: the rule's expression (e.g. level >= 16)")
   count = len(_list_of(entry, TRANSFORMS_KEY))
   if count >= max_transforms():
      raise DocumentError(f"at most {max_transforms()} rules per species (the engine's limit)")
   rule: JsonDict = {INTO_KEY: into, WHEN_KEY: when.strip()}
   checked = _check_triggers(on)
   if checked is not None:
      rule[ON_KEY] = checked
   if takes_item:
      rule[TAKES_ITEM_KEY] = True
   if also is not None:
      rule[ALSO_KEY] = also
   at = count if index is None else max(0, min(count, int(index)))

   def change() -> int:
      """!Inserts the rule.
      @return its index
      """
      _live(entry, TRANSFORMS_KEY).insert(at, rule)
      return at

   return _guarded(doc, change)


def _transform_index(doc: Document, species: str, index: Any) -> int:
   """!A rule's index, checked.
   @param doc      any manifest Document of the battle
   @param species  species name
   @param index    the index
   @return it
   @throws DocumentError when there is no such rule
   """
   count = len(_list_of(_species(doc, species), TRANSFORMS_KEY))
   try:
      i = int(index)
   except (TypeError, ValueError):
      raise DocumentError(f"a rule number (got {index!r})") from None
   if not 0 <= i < count:
      raise DocumentError(f"{species} has {count} rule(s): no rule {i}")
   return i


def remove_transform(doc: Document, species: str, index: int) -> None:
   """!Removes a transformation rule.
   @param doc      any manifest Document of the battle
   @param species  species name
   @param index    rule index
   @return None
   """
   i = _transform_index(doc, species, index)
   entry = _species(doc, species)

   def change() -> None:
      """!Drops the rule (and an empty list).
      @return None
      """
      _live(entry, TRANSFORMS_KEY).pop(i)
      _tidy(entry, TRANSFORMS_KEY)

   _guarded(doc, change)


def move_transform(doc: Document, species: str, index: int, delta: int) -> bool:
   """!Moves a rule up or down (the first that holds wins).
   @param doc      any manifest Document of the battle
   @param species  species name
   @param index    rule index
   @param delta    -1 up, +1 down
   @return True if it moved
   """
   i = _transform_index(doc, species, index)
   entry = _species(doc, species)
   j = i + delta
   if not 0 <= j < len(_list_of(entry, TRANSFORMS_KEY)):
      return False

   def change() -> None:
      """!Swaps the two rules.
      @return None
      """
      lst = _live(entry, TRANSFORMS_KEY)
      lst[i], lst[j] = lst[j], lst[i]

   _guarded(doc, change)
   return True


def set_transform(doc: Document, species: str, index: int, field: str, value: Any) -> None:
   """!Sets one field of a rule (None, an empty `on` or a false takes_item leaves the field out).
   @param doc      any manifest Document of the battle
   @param species  species name
   @param index    rule index
   @param field    one of TRANSFORM_FIELDS
   @param value    the value
   @return None
   @throws DocumentError for an unknown field or a value the engine refuses
   """
   i = _transform_index(doc, species, index)
   if field not in TRANSFORM_FIELDS:
      raise DocumentError(f"a rule's field is one of {', '.join(TRANSFORM_FIELDS)} (got {field!r})")
   if field == INTO_KEY:
      value = _check_species(doc, value, INTO_KEY)
   elif field == ALSO_KEY and value not in (None, ""):
      value = _check_species(doc, value, ALSO_KEY)
   elif field == ON_KEY:
      value = _check_triggers(value)
   elif field == TAKES_ITEM_KEY:
      value = bool(value) or None
   elif field == WHEN_KEY:
      if not isinstance(value, str) or not value.strip():
         raise DocumentError("when: the rule's expression")
      value = value.strip()
   rule = _live(_species(doc, species), TRANSFORMS_KEY)[i]

   def change() -> None:
      """!Writes the field.
      @return None
      """
      if value in (None, ""):
         rule.pop(field, None)
      else:
         rule[field] = value

   _guarded(doc, change)


def _form_index(doc: Document, species: str, name: str) -> int:
   """!A form entry's index in the species' list.
   @param doc      any manifest Document of the battle
   @param species  species name
   @param name     form name ("base" for the rule entry)
   @return the index
   @throws DocumentError when there is no such form
   """
   names = [str(f.get(NAME_KEY, "")).lower() for f in _list_of(_species(doc, species), FORMS_KEY)]
   if str(name).lower() not in names:
      raise DocumentError(f"{species} has no form {name!r} (forms: {', '.join(names) or 'none'})")
   return names.index(str(name).lower())


def add_form(doc: Document, species: str, name: str, when: str | None = None, on: Any = None,
             overrides: JsonDict | None = None) -> int:
   """!Adds a form (or, named "base", the rule back to the species' own form: it needs `when`).
   @param doc        any manifest Document of the battle
   @param species    species name
   @param name       form name (a new word; "base": the rule entry)
   @param when       its expression, or None (effect logic only)
   @param on         its triggers, or None
   @param overrides  FORM_OVERRIDES values, or None (the species' own)
   @return its index in the list
   @throws DocumentError for a taken name, a full list, or data the engine then refuses
   """
   entry = _species(doc, species)
   given = _list_of(entry, FORMS_KEY)
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("a form's name is a word")
   name = name.strip()
   if name.lower() in [str(f.get(NAME_KEY, "")).lower() for f in given]:
      raise DocumentError(f"{species} already has a form {name!r}")
   if sum(1 for f in given if str(f.get(NAME_KEY, "")).lower() != base_form()) >= max_forms() and \
         name.lower() != base_form():
      raise DocumentError(f"at most {max_forms()} forms per species (the engine's limit)")
   new: JsonDict = {NAME_KEY: name}
   for key, value in (overrides or {}).items():
      if key not in FORM_OVERRIDES:
         raise DocumentError(f"a form overrides {', '.join(FORM_OVERRIDES)} (got {key!r})")
      new[key] = copy.deepcopy(value)
   if when is not None and str(when).strip():
      new[WHEN_KEY] = str(when).strip()
   checked = _check_triggers(on)
   if checked is not None:
      new[ON_KEY] = checked

   def change() -> int:
      """!Appends the form.
      @return its index
      """
      lst = _live(entry, FORMS_KEY)
      lst.append(new)
      return len(lst) - 1

   return _guarded(doc, change)


def remove_form(doc: Document, species: str, name: str) -> None:
   """!Removes a form (records holding a later form's number then hold another one: the forms are numbered by
   position).
   @param doc      any manifest Document of the battle
   @param species  species name
   @param name     form name
   @return None
   """
   i = _form_index(doc, species, name)
   entry = _species(doc, species)

   def change() -> None:
      """!Drops the form (and an empty list).
      @return None
      """
      _live(entry, FORMS_KEY).pop(i)
      _tidy(entry, FORMS_KEY)

   _guarded(doc, change)


def form_removal_warning(doc: Document, species: str, name: str) -> str | None:
   """!What removing a form does to creature records already saved (C6, review4 finding 13): a stored form role
   keeps the form's number (its place among the species' forms), so the numbers after it name the next form
   afterwards and the last one names none (as removing a passive slot does). The editors ask before the change;
   the CLI wants --force.
   @param doc      any manifest Document of the battle
   @param species  species name
   @param name     form name
   @return the warning, or None (the "base" rule entry: no number moves; the layout stores no form role)
   """
   if str(name).lower() == base_form():
      return None
   from .structure import transformation   # local: it imports core.structure modules that import this one
   role = transformation.transformation(doc).get(transformation.FORM_ROLE_KEY)
   if not role:
      return None
   numbered = [str(f.get(NAME_KEY)) for f in _list_of(_species(doc, species), FORMS_KEY)
               if str(f.get(NAME_KEY, "")).lower() != base_form()]
   if name not in numbered:
      return None
   k = numbered.index(name) + 1   # form 0 is the species itself
   after = [f"{numbered[j]!r} ({j + 1} -> {j})" for j in range(k, len(numbered))]
   moved = f"; the forms after it move down: {', '.join(after)}" if after else ""
   return (f"Saved {species} records keep their form number in the {role!r} role: number {k} ({name!r}) then "
           f"names {repr(numbered[k]) if k < len(numbered) else 'no form'}{moved}")


def form_users(doc: Document, name: str) -> list[str]:
   """!The effect logic naming a form (`form WHO NAME`).
   @param doc   any manifest Document of the battle
   @param name  form name
   @return "where" strings
   """
   return logic.references(doc, (LOGIC_LIST,), name)


def rename_form(doc: Document, species: str, old: str, new: str) -> int:
   """!Renames a form; the effect logic naming it follows when no other species has a form of that name.
   @param doc      any manifest Document of the battle
   @param species  species name
   @param old      current name
   @param new      new name
   @return logic references updated
   """
   i = _form_index(doc, species, old)
   if str(old).lower() == base_form() or not isinstance(new, str) or new.strip().lower() == base_form():
      raise DocumentError(f"{base_form()!r} is the species' own form: it is not renamed")
   new = new.strip()
   entry = _species(doc, species)
   if new.lower() in [str(f.get(NAME_KEY, "")).lower() for f in _list_of(entry, FORMS_KEY)]:
      raise DocumentError(f"{species} already has a form {new!r}")
   shared = [str(s.get(NAME_KEY)) for s in battle.entries(doc, "species")
             if isinstance(s, dict) and s is not entry and
             any(str(f.get(NAME_KEY)) == old for f in _list_of(s, FORMS_KEY))]
   if shared and form_users(doc, old):
      # C6 (review4 finding 14): `form WHO NAME` names no species, so its logic cannot follow one species alone
      raise DocumentError(f"other species ({', '.join(shared)}) have a form {old!r} too and the effect logic names "
                          f"it ({', '.join(form_users(doc, old))}): rename it in each species and the logic "
                          f"together, or give this species' form a name of its own in the logic first")

   def change() -> int:
      """!Renames the form (and its logic).
      @return logic references updated
      """
      n = 0 if shared else len(logic.references(doc, (LOGIC_LIST,), old, new, RENAME_LABEL))
      _live(entry, FORMS_KEY)[i][NAME_KEY] = new
      return n

   return _guarded(doc, change)


def set_form(doc: Document, species: str, name: str, field: str, value: Any) -> None:
   """!Sets (or with None clears) one field of a form: an override (the species' own again) or its rule.
   @param doc      any manifest Document of the battle
   @param species  species name
   @param name     form name
   @param field    one of FORM_FIELDS
   @param value    the value, or None
   @return None
   @throws DocumentError for an unknown field or a value the engine refuses
   """
   i = _form_index(doc, species, name)
   if field not in FORM_FIELDS:
      raise DocumentError(f"a form's field is one of {', '.join(FORM_FIELDS)} (got {field!r})")
   if field == ON_KEY:
      value = _check_triggers(value)
   elif field == WHEN_KEY and isinstance(value, str):
      value = value.strip() or None
   entry = _live(_species(doc, species), FORMS_KEY)[i]

   def change() -> None:
      """!Writes the field.
      @return None
      """
      if value is None:
         entry.pop(field, None)
         if field == WHEN_KEY:
            entry.pop(ON_KEY, None)   # a form without a rule has no triggers
      else:
         entry[field] = copy.deepcopy(value)

   _guarded(doc, change)


def set_yield(doc: Document, species: str, stat: str, value: int | None) -> bool:
   """!Sets a species' training yield of a stat (its yield field's value; None or the field's default: the
   species follows the default).
   @param doc      any manifest Document of the battle
   @param species  species name
   @param stat     stat name the training gives a yield field
   @param value    the yield
   @return True when it changed
   @throws DocumentError when the training names no yield for the stat
   """
   row = next((y for y in yields(doc, species) if y["stat"] == stat), None)
   if row is None:
      raise DocumentError(f"the training names no yield for {stat!r} (Structure > Growth: training yields)")
   return species_fields.set_value(doc, species, row["field"], value)


def follow_species_rename(d: JsonDict, name: str, new: str | None, found: list[str]) -> None:
   """!The rules naming a species (into / also): recorded and, with @p new, renamed (core.battle.references()).
   @param d      the merged manifests (battle.merged())
   @param name   species name
   @param new    the new name, or None to only look
   @param found  "where" strings, appended to
   @return None
   """
   for s in d.get("species", []):
      if not isinstance(s, dict):
         continue
      for k, t in enumerate(_list_of(s, TRANSFORMS_KEY)):
         for key in (INTO_KEY, ALSO_KEY):
            if t.get(key) == name:
               found.append(f"species {s.get('name')} transforms[{k}].{key}")
               if new is not None:
                  t[key] = new


def item_word(name: str) -> str:
   """!The word a `when` expression names an item by (bare, or after item.): the engine's ident(), lower case.
   @param name  item name
   @return e.g. "bloom_charm"
   """
   return str(_bc().ident(name)).lower()


def follow_item_rename(d: JsonDict, name: str, new: str | None, found: list[str]) -> None:
   """!The `when` expressions naming an item (its word, bare or after item.; the blocked expression too): recorded
   and, with @p new, rewritten (core.battle.references()).
   @param d      the merged manifests (battle.merged())
   @param name   item name
   @param new    the new name, or None to only look
   @param found  "where" strings, appended to
   @return None
   """
   prefix = re.escape(_bc().ITEM_PREFIX)
   pattern = re.compile(rf"(?<![A-Za-z0-9_.])((?:{prefix})?){re.escape(item_word(name))}(?![A-Za-z0-9_])")

   def fix(holder: JsonDict, key: str, label: str) -> None:
      """!Rewrites one expression.
      @param holder  dict holding it
      @param key     its key ("when", or the transformation section's "blocked")
      @param label   "where" string
      @return None
      """
      text = holder.get(key)
      if isinstance(text, str) and pattern.search(text):
         found.append(label)
         if new is not None:
            holder[key] = pattern.sub(lambda m: m.group(1) + item_word(new), text)

   for s in d.get("species", []) if isinstance(d.get("species"), list) else []:
      if isinstance(s, dict):
         for k, rule in enumerate(_list_of(s, TRANSFORMS_KEY)):
            fix(rule, WHEN_KEY, f"species {s.get('name')} transforms[{k}].when")
         for f in _list_of(s, FORMS_KEY):
            fix(f, WHEN_KEY, f"species {s.get('name')} form {f.get(NAME_KEY)} when")
   section = d.get(TRANSFORMATION_KEY)
   if isinstance(section, dict):
      fix(section, BLOCKED_KEY, "transformation.blocked")


# -- report ------------------------------------------------------------------------------------------------------------

def lines(doc: Document, species: str) -> list[str]:
   """!A species' rules, forms and yields as text (CLI `transform SPECIES list`).
   @param doc      any manifest Document of the battle
   @param species  species name
   @return lines
   """
   out = []
   for r in transforms(doc, species):
      on = ",".join(r["on"]) if r["on"] is not None else f"(auto: {','.join(r['triggers']) or '?'})"
      extra = (" takes item" if r["takes_item"] else "") + (f" also {r['also']}" if r["also"] else "")
      out.append(f"{r['index']} -> {r['into']} when {r['when']} on {on}{extra}")
   for f in forms(doc, species):
      head = f"form {f['form']} {f['name']}" if not f["is_base"] else f"form 0 {f['name']} (back to its own)"
      rule = f" when {f['when']}" + (f" on {','.join(f['on'])}" if f["on"] else "") if f["when"] else \
         " (effect logic only)"
      out.append(head + (f" overrides {','.join(f['overrides'])}" if f["overrides"] else "") + rule)
   for y in yields(doc, species):
      out.append(f"yield {y['stat']} {y['value']} ({y['field']}" + ("" if y["own"] else ", default") + ")")
   return out or [f"{species}: no rules, forms or yields"]
