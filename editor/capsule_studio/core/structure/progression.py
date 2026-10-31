"""!Progression rules of battle data (D-22 A8 / A12, D-23 §3.2 "Progression"):
the battle manifest's "learn", "exp_policy" and "generation".

    "learn": {"on_full": "request", "default_moves": "last_n_by_level"},
    "exp_policy": {"share": "faced", "receivers": "human_side", "outsider": "owner_id"},
    "generation": [{"role": "seed", "random_range": [0, "max"]},
                   {"role": "stat_genes", "random_range": [0, 31]},
                   {"role": "gender", "derived": "seed_lo % 2", "range": [0, 1]},
                   {"role": "friendship", "constant": 70}]

learn says what happens when a creature learns a move with no free slot
and which moves a new creature starts with; exp_policy who shares the
experience of a defeated foe (the amount is the ruleset's exp_gain()); the
generation list is how a new record is made, in random-draw order: each
entry fills one role with a random range (one draw per element, two for a
power-of-two range above 65536 values, the high half first or with
"order": "low_first" the low half first (E13a: GenKind wide_low_first);
"max" is the role's highest value, "last" the last trait or passive slot),
a constant, or a derived expression over the layout's other roles
(battle_compiler.derived_inputs()) and the species' fields (species.NAME,
species_inputs(), E13a), which the engine evaluates as rules::derive() and
the studio previews with run_derived(), the species' field values taken
from the compiled data (record_inputs()). An unstored custom role (computed
on read, E13a) has exactly one entry, derived or constant (the compiler's
check_unstored()). Missing keys take the engine's defaults (DEFAULT_LEARN,
DEFAULT_EXP_POLICY, DEFAULT_GENERATION: its former fixed rules); every
choice list comes from the engine's compiler (LEARN_ON_FULL,
DEFAULT_MOVE_RULES, EXP_SHARES / RECEIVERS / OUTSIDERS, GEN_KINDS,
GENERATED_BY_ENGINE, MAX_GENERATION, BOUND_MAX / BOUND_LAST, LAST_ROLES,
WIDE_ORDERS / DEFAULT_WIDE_ORDER, UNSTORED_KINDS, SPECIES_PREFIX),
and an edit its compile_learn() / compile_exp_policy() / compile_generation()
refuses is refused with its message.

A custom role's rename follows the generation list (entries filling it and
derived expressions reading it, NAME_hi / NAME_lo halves included:
rename_role()); removing a role drops the entries filling a custom role and
is refused while a derived expression reads it (drop_role()). The record
module (core.structure.record) calls both. A species field's rename and
removal follow the derived expressions the same way (rename_field(),
field_readers(); core.structure.species_fields calls them).

Each editing helper is one change: call it inside one battle.edit().
"""
from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from typing import Any

from .. import battle, engine, expressions, logic
from ..document import Document, DocumentError
from . import resources as resource_model

## A parsed JSON object.
JsonDict = dict[str, Any]
## One generation entry as generation_rows() gives it.
GenRow = dict[str, Any]

## The battle manifest's learn policy.
LEARN_KEY = "learn"
## The battle manifest's experience policy.
EXP_KEY = "exp_policy"
## The battle manifest's generation list.
GENERATION_KEY = "generation"
## A generation entry's role.
ROLE_KEY = "role"
## A generation entry way: a random range.
RANDOM_WAY = "random_range"
## A generation entry way: a constant.
CONSTANT_WAY = "constant"
## A generation entry way: a derived expression.
DERIVED_WAY = "derived"
## The ways a generation entry fills its role (the compiler's keys).
WAYS = (RANDOM_WAY, CONSTANT_WAY, DERIVED_WAY)
## A derived entry's declared range.
RANGE_KEY = "range"
## Location the compiler's messages name.
WHERE = "battle"
## Names of an expression (role inputs, constants, functions; a dotted species.NAME is one name, as the engine's
## ruleset tokenizer reads it since E13a).
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")
## A random entry's draw order key (E13a: a wide range's high or low half first).
ORDER_KEY = "order"
## The structure manifest's species fields (E13a; core.structure.species_fields edits them).
SPECIES_FIELDS_KEY = "species_fields"
## The compiled kind whose draw depends on the species (the engine's DRAWS_PER_KIND gives it one draw, taken only
## when the species fills a rolled passive slot past the first).
SPECIES_KIND = "passive_slot"
## The compiled kind that draws only for more than one value.
RANDOM_KIND = "random"


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


# -- the engine's choices ----------------------------------------------------------------------------------------------

def choices() -> dict[str, list[str]]:
   """!The words of learn and exp_policy, by dotted key.
   @return {"learn.on_full": LEARN_ON_FULL, "learn.default_moves": DEFAULT_MOVE_RULES, "exp_policy.share": ...}
   """
   bc = _bc()
   return {f"{LEARN_KEY}.on_full": list(bc.LEARN_ON_FULL), f"{LEARN_KEY}.default_moves": list(bc.DEFAULT_MOVE_RULES),
           f"{EXP_KEY}.share": list(bc.EXP_SHARES), f"{EXP_KEY}.receivers": list(bc.EXP_RECEIVERS),
           f"{EXP_KEY}.outsider": list(bc.EXP_OUTSIDERS)}


def defaults() -> dict[str, Any]:
   """!The engine's progression without manifest keys.
   @return {"learn": DEFAULT_LEARN, "exp_policy": DEFAULT_EXP_POLICY, "generation": DEFAULT_GENERATION} (copies)
   """
   bc = _bc()
   return {LEARN_KEY: copy.deepcopy(bc.DEFAULT_LEARN), EXP_KEY: copy.deepcopy(bc.DEFAULT_EXP_POLICY),
           GENERATION_KEY: copy.deepcopy(bc.DEFAULT_GENERATION)}


def required(part: str) -> list[str]:
   """!The keys of learn or exp_policy a manifest must state (the engine's REQUIRED_LEARN / REQUIRED_EXP_POLICY).
   @param part  LEARN_KEY or EXP_KEY
   @return key names
   """
   bc = _bc()
   return list(bc.REQUIRED_LEARN if part == LEARN_KEY else bc.REQUIRED_EXP_POLICY)


def bounds() -> tuple[str, str, tuple[str, ...]]:
   """!The range bound words.
   @return (BOUND_MAX, BOUND_LAST, LAST_ROLES)
   """
   bc = _bc()
   return str(bc.BOUND_MAX), str(bc.BOUND_LAST), tuple(bc.LAST_ROLES)


def max_generation() -> int:
   """!Most generation entries.
   @return MAX_GENERATION
   """
   return int(_bc().MAX_GENERATION)


def gen_kinds() -> list[str]:
   """!The compiled entry kinds (GenKind order).
   @return GEN_KINDS
   """
   return list(_bc().GEN_KINDS)


def wide_orders() -> list[str]:
   """!The draw orders of a wide random range (E13a: the engine's WIDE_ORDERS keys).
   @return words ("high_first", "low_first")
   """
   return list(_bc().WIDE_ORDERS)


def default_wide_order() -> str:
   """!A wide range's draw order without "order" (the engine's DEFAULT_WIDE_ORDER).
   @return the word
   """
   return str(_bc().DEFAULT_WIDE_ORDER)


def wide_kinds() -> list[str]:
   """!The compiled kinds of a wide random range (two draws), one per draw order (the engine's WIDE_ORDERS values).
   @return kind words
   """
   return list(_bc().WIDE_ORDERS.values())


def unstored_kinds() -> list[str]:
   """!The ways an unstored custom role may be filled (the engine's UNSTORED_KINDS: it is computed on read).
   @return kind words ("derived", "constant")
   """
   return list(_bc().UNSTORED_KINDS)


def element_input() -> str:
   """!The derived expressions' input naming the element asked for.
   @return the compiler's DERIVED_ELEMENT
   """
   return str(_bc().DERIVED_ELEMENT)


# -- compiling ---------------------------------------------------------------------------------------------------------

def _layout(doc: Document) -> JsonDict | None:
   """!The record layout as the engine compiles it.
   @param doc  battle Document
   @return compile_layout() result, or None when it does not compile
   """
   from . import record   # local: record imports this module
   return record.compile_record(doc)[0]


def _ruleset(doc: Document) -> JsonDict:
   """!The compiled ruleset of the battle data's project (its constants), or no constants.
   @param doc  battle Document
   @return ruleset_compiler.load() result, or {"constants": {}}
   """
   project = logic.project_of(doc)
   if project is not None:
      try:
         rc = engine.tool("ruleset_compiler")
         return rc.load(_bc().strip(copy.deepcopy(project.ruleset.data)), project.ruleset.path.name)
      except Exception:   # a ruleset that does not compile: the battle's own compile reports it
         pass
   return {"constants": {}}


def _rules(doc: Document) -> JsonDict:
   """!The battle constants a derived expression may read.
   @param doc  battle Document
   @return {"stat_cap", "level_max"} (the manifest's rules over the engine's defaults)
   """
   bc = _bc()
   r = battle.data_of(doc, "rules").get("rules") if isinstance(battle.data_of(doc, "rules").get("rules"), dict) else {}
   return {"stat_cap": r.get("stat_cap", bc.DEFAULT_STAT_CAP), "level_max": r.get("level_max", bc.DEFAULT_LEVEL_MAX)}


def species_fields_of(doc: Document) -> tuple[list[JsonDict], str | None]:
   """!The structure's species fields as the engine compiles them (E13a compile_species_fields()).
   @param doc  battle Document
   @return (compiled fields, [] when they do not compile; the compiler's message or None)
   """
   bc = _bc()
   given = battle.data_of(doc, SPECIES_FIELDS_KEY).get(SPECIES_FIELDS_KEY)
   try:
      return list(bc.compile_species_fields(copy.deepcopy(given), WHERE)), None
   except Exception as e:   # ManifestError, type errors in odd data
      return [], str(e)


def _traits(doc: Document) -> int:
   """!Traits in the data.
   @param doc  battle Document
   @return count
   """
   t = battle.data_of(doc, "traits").get("traits")
   return len(t) if isinstance(t, list) else 0


class Compiler:
   """!The inputs compile_generation() needs, gathered once for several checks."""

   def __init__(self, doc: Document) -> None:
      """!Compiles the layout and the ruleset.
      @param doc  battle Document
      """
      ## The battle Document.
      self.doc = doc
      ## Compiled layout, or None.
      self.layout = _layout(doc)
      ## Compiled ruleset (its constants).
      self.ruleset = _ruleset(doc)
      ## Battle constants.
      self.rules = _rules(doc)
      ## Traits in the data.
      self.traits = _traits(doc)
      ## The resources' persist roles (D-25: the engine fills them with full pools; no entry may set them).
      self.filled = resource_model.persist_roles(doc)
      ## The compiled species fields (species.NAME inputs, E13a; [] when they do not compile).
      self.species_fields = species_fields_of(doc)[0]

   def generation(self, src: Any, layout: JsonDict | None = None) -> tuple[list[JsonDict] | None, str | None]:
      """!Compiles a generation list.
      @param src     the list (None: the default)
      @param layout  the compiled layout to use (default: the battle's)
      @return (compile_generation() result or None, message or None)
      """
      layout = self.layout if layout is None else layout
      if layout is None:
         return None, "the record layout does not compile (see the Record page)"
      try:
         return _bc().compile_generation(copy.deepcopy(src), layout, self.ruleset, self.rules, self.traits,
                                         WHERE, self.filled, self.species_fields), None
      except Exception as e:   # ManifestError, type errors in odd data
         return None, str(e)

   def entry(self, e: Any) -> tuple[JsonDict | None, str | None]:
      """!Compiles one generation entry on its own (the layout's other unstored roles, which need entries of their
      own, are left out of the check: the whole list's compile reports them).
      @param e  the entry
      @return (compiled entry or None when it draws nothing at all (no traits), message or None)
      """
      layout = self.layout
      if layout is not None and layout.get("unstored"):
         role = e.get(ROLE_KEY) if isinstance(e, dict) else None
         layout = {**layout, "unstored": [u for u in layout["unstored"] if u["name"] == role]}
      out, error = self.generation([e], layout)
      if error is not None:
         return None, error.replace(f"{GENERATION_KEY}[0]", GENERATION_KEY)
      return (out[0] if out else None), None


def compile_progress(doc: Document) -> dict[str, str | None]:
   """!What the engine's compiler says about each part.
   @param doc  battle Document
   @return {"learn": message or None, "exp_policy": ..., "generation": ...}
   """
   bc = _bc()
   out: dict[str, str | None] = {}
   try:
      bc.compile_learn(copy.deepcopy(battle.data_of(doc, LEARN_KEY).get(LEARN_KEY)), WHERE)
      out[LEARN_KEY] = None
   except Exception as e:   # ManifestError, odd data
      out[LEARN_KEY] = str(e)
   c = Compiler(doc)
   if c.layout is None:
      out[EXP_KEY] = out[GENERATION_KEY] = "the record layout does not compile (see the Record page)"
      return out
   try:
      bc.compile_exp_policy(copy.deepcopy(battle.data_of(doc, EXP_KEY).get(EXP_KEY)), c.layout, WHERE)
      out[EXP_KEY] = None
   except Exception as e:   # ManifestError, odd data
      out[EXP_KEY] = str(e)
   out[GENERATION_KEY] = c.generation(battle.data_of(doc, GENERATION_KEY).get(GENERATION_KEY))[1]
   return out


def _guarded(doc: Document, part: str, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it (inside battle.edit()) when the part compiled before and does not after.
   @param doc     battle Document
   @param part    LEARN_KEY, EXP_KEY or GENERATION_KEY
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   before = compile_progress(doc)[part]
   result = change()
   if before is None:
      after = compile_progress(doc)[part]
      if after is not None:
         raise DocumentError(after)
   return result


# -- learn and exp_policy ----------------------------------------------------------------------------------------------

def policy(doc: Document, part: str) -> tuple[JsonDict, set[str]]:
   """!The learn or experience policy the compiler uses.
   @param doc   battle Document
   @param part  LEARN_KEY or EXP_KEY
   @return (every key of the part: the manifest's word, else the engine's default, else None for a required key
           the manifest leaves out; the keys left to the engine's default)
   """
   given = battle.data_of(doc, part).get(part)
   given = given if isinstance(given, dict) else {}
   default = defaults()[part]
   keys = [k.split(".", 1)[1] for k in choices() if k.startswith(part + ".")]
   out = {k: given.get(k, default.get(k)) for k in keys}
   left = {k for k in keys if k not in given and k in default}
   return out, left


def new_policy(part: str) -> JsonDict:
   """!The policy new battle data writes: the engine's defaults, and for each key the engine requires the first
   word of its list (the studio's neutral pick, D-22 decision 8: the game states it, and may change it).
   @param part  LEARN_KEY or EXP_KEY
   @return the object
   """
   out = defaults()[part]
   words = choices()
   for k in required(part):
      out.setdefault(k, words[f"{part}.{k}"][0])
   return out


def set_policy(doc: Document, key: str, value: str | None) -> None:
   """!Sets one learn or experience policy word.
   @param doc    battle Document
   @param key    a key of choices() ("learn.on_full", "exp_policy.share", ...)
   @param value  one of its words, or None for the engine's default
   @return None
   """
   words = choices()
   if key not in words:
      raise DocumentError(f"no progression setting {key!r} ({', '.join(words)})")
   if value is not None and value not in words[key]:
      raise DocumentError(f"{key}: one of {', '.join(words[key])}, got {value!r}")
   part, k = key.split(".", 1)
   if value is None and k in required(part):
      raise DocumentError(f"{key} has no engine default: the game states it ({', '.join(words[key])})")

   def change() -> None:
      """!Writes the word (an empty policy object is dropped).
      @return None
      """
      obj = battle.data_of(doc, part).get(part)
      if not isinstance(obj, dict):
         obj = battle.data_of(doc, part)[part] = {}
      if value is None:
         obj.pop(k, None)
         if not obj:
            battle.data_of(doc, part).pop(part)
      else:
         obj[k] = value

   _guarded(doc, part, change)


# -- the generation list -----------------------------------------------------------------------------------------------

def is_default(doc: Document) -> bool:
   """!Whether the manifest leaves the generation list to the engine.
   @param doc  battle Document
   @return True without a "generation" key
   """
   return not isinstance(battle.data_of(doc, GENERATION_KEY).get(GENERATION_KEY), list)


def entries_of(doc: Document) -> list[Any]:
   """!The generation list the compiler uses.
   @param doc  battle Document
   @return the manifest's list, or a copy of DEFAULT_GENERATION
   """
   given = battle.data_of(doc, GENERATION_KEY).get(GENERATION_KEY)
   return given if isinstance(given, list) else defaults()[GENERATION_KEY]


def _entries(doc: Document) -> list[Any]:
   """!The manifest's generation list, written out from the default when it had none.
   @param doc  battle Document
   @return the live list
   """
   if not isinstance(battle.data_of(doc, GENERATION_KEY).get(GENERATION_KEY), list):
      battle.data_of(doc, GENERATION_KEY)[GENERATION_KEY] = defaults()[GENERATION_KEY]
   return battle.data_of(doc, GENERATION_KEY)[GENERATION_KEY]


def _entry(doc: Document, index: int) -> JsonDict:
   """!One entry of the manifest's list.
   @param doc    battle Document
   @param index  its index
   @return the live dict
   """
   lst = _entries(doc)
   if not 0 <= index < len(lst) or not isinstance(lst[index], dict):
      raise DocumentError(f"no generation entry {index} (0-{len(lst) - 1})")
   return lst[index]


def way_of(e: Any) -> str | None:
   """!How an entry fills its role.
   @param e  the entry
   @return one of WAYS, or None for an odd entry
   """
   if not isinstance(e, dict):
      return None
   ways = [w for w in WAYS if w in e]
   return ways[0] if len(ways) == 1 else None


def role_choices(doc: Document) -> list[str]:
   """!The roles a generation entry may fill: the engine roles (held by the layout or not: an unheld one still
   draws) but those the engine fills itself (GENERATED_BY_ENGINE, the resources' persist roles) and the retired
   ones, then the layout's custom roles (stored ones, then unstored ones: E13a "unstored_ids", which a layout
   compiled by an engine before E13a does not have).
   @param doc  battle Document
   @return names
   """
   bc = _bc()
   lay = _layout(doc)
   custom = (list(lay["custom_ids"]) + list(lay.get("unstored_ids", {}))) if lay is not None else []
   filled = set(bc.GENERATED_BY_ENGINE) | set(resource_model.persist_roles(doc))
   return [n for n in bc.ROLE_NAMES if n not in filled and n not in bc.RETIRED_ROLES] + \
      [n for n in custom if n not in filled]


def species_inputs(doc: Document) -> dict[str, tuple[int, int]]:
   """!The species fields a derived expression reads (species.NAME, E13a: the engine's species_inputs()).
   @param doc  battle Document
   @return name -> (lo, hi) ({} when the fields do not compile)
   """
   return dict(_bc().species_inputs(species_fields_of(doc)[0]))


def derived_inputs(doc: Document) -> list[str]:
   """!The names a derived expression reads: the layout's stored single-element roles (32-bit ones as NAME_hi /
   NAME_lo), the species' fields (species.NAME) and the element.
   @param doc  battle Document
   @return names (empty when the layout does not compile)
   """
   lay = _layout(doc)
   if lay is None:
      return []
   return list(_bc().derived_inputs(lay)) + list(species_inputs(doc)) + [element_input()]


def derived_names(doc: Document) -> expressions.Names:
   """!What a derived expression may name, for the editors' completion and colours: the inputs (derived_inputs()),
   the constants (derived_constants()) and the ruleset language's functions.
   @param doc  battle Document
   @return core.expressions.Names
   """
   return expressions.Names(derived_inputs(doc), list(derived_constants(doc)), expressions.functions())


def derived_constants(doc: Document) -> dict[str, int]:
   """!The constants a derived expression may use (the ruleset's, STAT_CAP, LEVEL_MAX, TRAIT_COUNT).
   @param doc  battle Document
   @return name -> value ({} when nothing compiles)
   """
   c = Compiler(doc)
   roles = role_choices(doc)
   if not roles:
      return {}
   compiled, _error = c.entry({ROLE_KEY: roles[0], DERIVED_WAY: "0"})
   return dict(compiled["formula"]["constants"]) if compiled is not None else {}


def _draws(compiled: JsonDict | None) -> tuple[int, bool]:
   """!The random draws a compiled entry takes.
   @param compiled  compiled entry, or None (draws nothing)
   @return (draws, True when they depend on the species)
   """
   if compiled is None:
      return 0, False
   kind = gen_kinds()[compiled["kind"]]
   per = int(_bc().DRAWS_PER_KIND.get(kind, 0))
   if kind == RANDOM_KIND and compiled["span"] <= 1:
      per = 0   # one value needs no draw
   return per * max(int(compiled["count"]), 1), kind == SPECIES_KIND


def generation_rows(doc: Document) -> list[GenRow]:
   """!The generation list with what each entry draws, numbered in draw order.
   @param doc  battle Document
   @return per entry: index, role, way (one of WAYS or None), lo / hi (random range bounds as given), order (a
           random range's "order" as given, or None), wide (True when the range takes two draws: it has a draw
           order), value (constant), expr / range (derived; range None: the role's values), kind (the compiled
           kind word or None), elements, draws, species (True when the draw depends on the species), first (the
           first draw's number, from 1; None when it draws nothing), error (the compiler's message or None),
           default (True when the manifest leaves the list to the engine)
   """
   c = Compiler(doc)
   default = is_default(doc)
   n = 1
   out = []
   for i, e in enumerate(entries_of(doc)):
      way = way_of(e)
      compiled, error = c.entry(e)
      draws, species = _draws(compiled)
      rng = e.get(RANDOM_WAY) if isinstance(e, dict) else None
      lo, hi = (rng[0], rng[1]) if isinstance(rng, list) and len(rng) == len(("lo", "hi")) else (None, None)
      declared = e.get(RANGE_KEY) if isinstance(e, dict) else None
      kind = gen_kinds()[compiled["kind"]] if compiled is not None else None
      out.append({"index": i, "role": e.get(ROLE_KEY) if isinstance(e, dict) else None, "way": way, "lo": lo,
                  "hi": hi, "order": e.get(ORDER_KEY) if isinstance(e, dict) else None,
                  "wide": kind in wide_kinds(), "value": e.get(CONSTANT_WAY) if isinstance(e, dict) else None,
                  "expr": e.get(DERIVED_WAY) if isinstance(e, dict) else None,
                  "range": list(declared) if isinstance(declared, list) else None,
                  "kind": kind,
                  "elements": int(compiled["count"]) if compiled is not None else 0, "draws": draws,
                  "species": species, "first": n if draws else None, "error": error, "default": default})
      n += draws
   return out


def _new_entry(role: str, way: str) -> JsonDict:
   """!A new entry filling a role.
   @param role  the role
   @param way   one of WAYS
   @return {"role", way: its neutral value}
   """
   top, last, last_roles = bounds()
   if way == RANDOM_WAY:
      return {ROLE_KEY: role, RANDOM_WAY: [0, last if role in last_roles else top]}
   if way == CONSTANT_WAY:
      return {ROLE_KEY: role, CONSTANT_WAY: 0}
   return {ROLE_KEY: role, DERIVED_WAY: "0"}


def _check_way(way: str) -> None:
   """!Refuses an unknown way.
   @param way  wanted way
   @return None
   """
   if way not in WAYS:
      raise DocumentError(f"an entry fills its role by {', '.join(WAYS)}, got {way!r}")


def add_entry(doc: Document, role: str, way: str = RANDOM_WAY, index: int | None = None) -> int:
   """!Adds a generation entry (writes the list out when it was the default).
   @param doc    battle Document
   @param role   one of role_choices()
   @param way    one of WAYS (random range [0, "max"] / [0, "last"], constant 0, derived "0")
   @param index  position (its place in draw order), or None for the end
   @return its index
   """
   _check_way(way)
   if role not in role_choices(doc):
      raise DocumentError(f"no role {role!r} a generation entry may fill ({', '.join(role_choices(doc))})")
   most = max_generation()
   if len(entries_of(doc)) >= most:
      raise DocumentError(f"at most {most} generation entries (the engine's limit)")

   def change() -> int:
      """!Inserts the entry.
      @return its index
      """
      lst = _entries(doc)
      at = len(lst) if index is None else max(0, min(len(lst), int(index)))
      lst.insert(at, _new_entry(role, way))
      return at

   return _guarded(doc, GENERATION_KEY, change)


def remove_entry(doc: Document, index: int) -> None:
   """!Removes a generation entry (the role then keeps its initial value; later draws move up).
   @param doc    battle Document
   @param index  its index
   @return None
   """
   _entry(doc, index)
   _guarded(doc, GENERATION_KEY, lambda: _entries(doc).pop(index))


def move_entry_to(doc: Document, index: int, to: int) -> bool:
   """!Moves an entry in draw order.
   @param doc    battle Document
   @param index  its index
   @param to     new index
   @return True when it moved
   """
   _entry(doc, index)
   lst = _entries(doc)
   if not 0 <= to < len(lst) or to == index:
      return False

   def change() -> None:
      """!Takes the entry out and puts it back.
      @return None
      """
      lst.insert(to, lst.pop(index))

   _guarded(doc, GENERATION_KEY, change)
   return True


def move_entry(doc: Document, index: int, delta: int) -> bool:
   """!Moves an entry up or down the draw order.
   @param doc    battle Document
   @param index  its index
   @param delta  -1 earlier, +1 later
   @return True when it moved
   """
   return move_entry_to(doc, index, index + delta)


def _write(doc: Document, index: int, fill: Callable[[JsonDict], None]) -> None:
   """!Changes one entry, guarded by the compiler.
   @param doc    battle Document
   @param index  the entry
   @param fill   callable(entry) that changes it
   @return None
   """
   _entry(doc, index)
   _guarded(doc, GENERATION_KEY, lambda: fill(_entry(doc, index)))


def set_role(doc: Document, index: int, role: str) -> None:
   """!Changes the role an entry fills.
   @param doc    battle Document
   @param index  the entry
   @param role   one of role_choices()
   @return None
   """
   if role not in role_choices(doc):
      raise DocumentError(f"no role {role!r} a generation entry may fill ({', '.join(role_choices(doc))})")

   def fill(e: JsonDict) -> None:
      """!Writes the role.
      @param e  the entry
      @return None
      """
      e[ROLE_KEY] = role

   _write(doc, index, fill)


def set_way(doc: Document, index: int, way: str) -> None:
   """!Changes how an entry fills its role (its value starts neutral: see add_entry()).
   @param doc    battle Document
   @param index  the entry
   @param way    one of WAYS
   @return None
   """
   _check_way(way)

   def fill(e: JsonDict) -> None:
      """!Replaces the way.
      @param e  the entry
      @return None
      """
      if way_of(e) == way:
         return
      new = _new_entry(str(e.get(ROLE_KEY)), way)
      e.clear()
      e.update(new)

   _write(doc, index, fill)


def _bound(value: Any) -> int | str:
   """!A random range bound as given (an integer, BOUND_MAX or BOUND_LAST; digits become an integer).
   @param value  given bound
   @return the bound
   """
   if isinstance(value, str) and value.strip().lstrip("-").isdigit():
      return int(value)
   top, last, _roles = bounds()
   if isinstance(value, bool) or not (isinstance(value, int) or value in (top, last)):
      raise DocumentError(f"a bound is a number, {top!r} or {last!r}, got {value!r}")
   return value


def set_random(doc: Document, index: int, lo: Any, hi: Any) -> None:
   """!Sets a random entry's range.
   @param doc    battle Document
   @param index  the entry
   @param lo     lowest value (an integer)
   @param hi     highest value (an integer, BOUND_MAX or BOUND_LAST)
   @return None
   """
   lo, hi = _bound(lo), _bound(hi)

   def fill(e: JsonDict) -> None:
      """!Writes the range.
      @param e  the entry
      @return None
      """
      if way_of(e) != RANDOM_WAY:
         raise DocumentError(f"entry {index} is not a random range")
      e[RANDOM_WAY] = [lo, hi]

   _write(doc, index, fill)


def set_order(doc: Document, index: int, order: str | None) -> None:
   """!Sets a wide random range's draw order (E13a "order": the high or the low half first; the engine refuses it
   on a range of one draw).
   @param doc    battle Document
   @param index  the entry
   @param order  one of wide_orders(), or None for the engine's default (DEFAULT_WIDE_ORDER, nothing written)
   @return None
   """
   if order is not None and order not in wide_orders():
      raise DocumentError(f"a draw order is one of {', '.join(wide_orders())}, got {order!r}")

   def fill(e: JsonDict) -> None:
      """!Writes the order.
      @param e  the entry
      @return None
      """
      if way_of(e) != RANDOM_WAY:
         raise DocumentError(f"entry {index} is not a random range")
      if order is None:
         e.pop(ORDER_KEY, None)
      else:
         e[ORDER_KEY] = order

   _write(doc, index, fill)
   compiled, error = Compiler(doc).entry(_entry(doc, index))
   if error is not None:
      raise DocumentError(error)
   if order is not None and (compiled is None or gen_kinds()[compiled["kind"]] not in wide_kinds()):
      raise DocumentError(f"entry {index}: only a wide random range (two draws) has a draw order")


def set_constant(doc: Document, index: int, value: int) -> None:
   """!Sets a constant entry's value.
   @param doc    battle Document
   @param index  the entry
   @param value  the value (within the role's)
   @return None
   """
   if isinstance(value, bool) or not isinstance(value, int):
      raise DocumentError(f"a constant is a whole number, got {value!r}")

   def fill(e: JsonDict) -> None:
      """!Writes the value.
      @param e  the entry
      @return None
      """
      if way_of(e) != CONSTANT_WAY:
         raise DocumentError(f"entry {index} is not a constant")
      e[CONSTANT_WAY] = value

   _write(doc, index, fill)


def set_derived(doc: Document, index: int, expr: str, rng: list[int] | None = None) -> None:
   """!Sets a derived entry's expression and range.
   @param doc    battle Document
   @param index  the entry
   @param expr   the expression (derived_inputs(), derived_constants(), the ruleset's functions)
   @param rng    [lo, hi] within the role's values, or None for the role's values
   @return None
   """
   if not isinstance(expr, str) or not expr.strip():
      raise DocumentError("a derived entry needs an expression")

   def fill(e: JsonDict) -> None:
      """!Writes the expression and the range.
      @param e  the entry
      @return None
      """
      if way_of(e) != DERIVED_WAY:
         raise DocumentError(f"entry {index} is not derived")
      e[DERIVED_WAY] = expr.strip()
      if rng is None:
         e.pop(RANGE_KEY, None)
      else:
         e[RANGE_KEY] = list(rng)

   _write(doc, index, fill)
   # the expression must compile on its own too (a list that did not compile before is not checked as a whole)
   _compiled, error = Compiler(doc).entry(_entry(doc, index))
   if error is not None:
      raise DocumentError(error)


def reset_generation(doc: Document) -> bool:
   """!Gives the generation list back to the engine (DEFAULT_GENERATION).
   @param doc  battle Document
   @return True when the manifest had one
   """
   return battle.data_of(doc, GENERATION_KEY).pop(GENERATION_KEY, None) is not None


def species_names(doc: Document) -> list[str]:
   """!The species a preview may take its fields from.
   @param doc  battle Document
   @return names, in manifest order
   """
   return [str(s.get("name")) for s in battle.entries(doc, "species") if isinstance(s.get("name"), str)]


def species_values(doc: Document, species: str | None) -> dict[str, int]:
   """!A species' field values as a derived expression reads them (species.NAME -> value): the engine's
   record_inputs() on the compiled battle data when it compiles (the species' "fields" over the fields'
   defaults), else from the manifests; every field's default without a species.
   @param doc      battle Document
   @param species  species name, or None
   @return name (with the species prefix) -> value
   """
   bc = _bc()
   prefix = str(bc.SPECIES_PREFIX)
   fields, _error = species_fields_of(doc)
   project = logic.project_of(doc)
   compiled = project.compile()[0] if project is not None else None
   if compiled is not None and species is not None:
      sp = next((s for s in compiled["species"] if s["name"] == species), None)
      if sp is not None:
         # the engine's mirror of what battle::record_value() hands the derived expressions
         values = bc.record_inputs(compiled, {"species_key": sp["key"]})
         return {k: int(v) for k, v in values.items() if k.startswith(prefix)}
   given: dict[str, Any] = {}
   for s in battle.entries(doc, "species"):
      if s.get("name") == species and isinstance(s.get("fields"), dict):
         given = s["fields"]
   out = {}
   for f in fields:
      v = given.get(f["name"], f["default"])
      out[prefix + f["name"]] = v if isinstance(v, int) and not isinstance(v, bool) else f["default"]
   return out


def preview(doc: Document, index: int, values: Mapping[str, int] | None = None, element: int = 0,
            species: str | None = None) -> int:
   """!Runs a derived entry as the generated rules::derive() would (the engine's run_derived()).
   @param doc      battle Document
   @param index    a derived entry
   @param values   input name -> value (inputs left out are 0; species fields left out take the species')
   @param element  the element asked for
   @param species  the species whose fields the expression reads (species_values()), or None for the fields'
                   defaults
   @return the value, clamped to the entry's range
   @throws DocumentError when the entry is not derived or does not compile
   """
   lst = entries_of(doc)
   if not 0 <= index < len(lst) or way_of(lst[index]) != DERIVED_WAY:
      raise DocumentError(f"entry {index} is not a derived entry")
   compiled, error = Compiler(doc).entry(lst[index])
   if error is not None or compiled is None:
      raise DocumentError(error or "the entry draws nothing")
   given = {n: 0 for n in derived_inputs(doc) if n != element_input()}
   given.update(species_values(doc, species))
   given.update(values or {})
   try:
      return int(_bc().run_derived(compiled, given, element))
   except Exception as e:   # the evaluator's RulesetError (division by zero, an unknown input)
      raise DocumentError(str(e)) from None


# -- role renames and removals (core.structure.record) ----------------------------------------------------------------

def _input_names(layout: JsonDict | None, role: str) -> list[str]:
   """!The derived-expression inputs that read a role (NAME, or NAME_hi / NAME_lo for a 32-bit one).
   @param layout  compiled layout, or None
   @param role    role name
   @return names
   """
   if layout is None:
      return []
   info = _bc().role_info(layout, role)
   if info is None:
      return []
   rid = info[0]
   return [n for n, (r, _shift, _top, _half) in _bc().derived_inputs(layout).items() if r == rid]


def readers(doc: Document, role: str, layout: JsonDict | None = None) -> list[str]:
   """!The generation entries whose derived expression reads a role.
   @param doc     battle Document
   @param role    role name
   @param layout  the compiled layout (default: the current one)
   @return "generation[k] (ROLE)" per entry
   """
   names = set(_input_names(layout if layout is not None else _layout(doc), role))
   out = []
   for k, e in enumerate(entries_of(doc)):
      if way_of(e) == DERIVED_WAY and isinstance(e[DERIVED_WAY], str) and \
            names & set(IDENTIFIER.findall(e[DERIVED_WAY])):
         out.append(f"{GENERATION_KEY}[{k}] ({e.get(ROLE_KEY)})")
   return out


def fillers(doc: Document, role: str) -> list[int]:
   """!The generation entries filling a role.
   @param doc   battle Document
   @param role  role name
   @return indices
   """
   return [k for k, e in enumerate(entries_of(doc)) if isinstance(e, dict) and e.get(ROLE_KEY) == role]


def rename_role(doc: Document, old: str, new: str, layout: JsonDict | None) -> int:
   """!Follows a role rename in the generation list: entries filling it and derived expressions reading it
   (the record module calls it inside the rename's edit). A list the manifest leaves to the engine names
   only engine roles, which are never renamed.
   @param doc     battle Document
   @param old     old name
   @param new     new name
   @param layout  the layout compiled before the rename (its input names)
   @return entries changed
   """
   if is_default(doc):
      return 0
   mapping = {n: new + n[len(old):] for n in _input_names(layout, old)}
   changed = 0
   for e in battle.data_of(doc, GENERATION_KEY)[GENERATION_KEY]:
      if not isinstance(e, dict):
         continue
      touched = False
      if e.get(ROLE_KEY) == old:
         e[ROLE_KEY] = new
         touched = True
      expr = e.get(DERIVED_WAY)
      if isinstance(expr, str) and mapping:
         fixed = IDENTIFIER.sub(lambda m: mapping.get(m.group(0), m.group(0)), expr)
         if fixed != expr:
            e[DERIVED_WAY] = fixed
            touched = True
      changed += touched
   return changed


def drop_role(doc: Document, role: str, custom: bool) -> list[int]:
   """!Follows a role removal in the generation list (the record module calls it inside the removal's edit):
   refused while a derived expression reads the role; a custom role's entries are dropped (it no longer
   exists), an engine role's kept (an engine role the layout leaves out still draws, so the draw order
   stays).
   @param doc     battle Document
   @param role    role name
   @param custom  True for a custom role
   @return the indices dropped
   @throws DocumentError while an expression reads it
   """
   users = readers(doc, role)
   if users:
      raise DocumentError(f"role {role!r} is read by the derived expression of {', '.join(users)}")
   if not custom or is_default(doc):
      return []
   gone = fillers(doc, role)
   lst = battle.data_of(doc, GENERATION_KEY)[GENERATION_KEY]
   for k in reversed(gone):
      lst.pop(k)
   return gone


# -- species field renames and removals (core.structure.species_fields) -----------------------------------------------

def field_readers(doc: Document, name: str) -> list[str]:
   """!The generation entries whose derived expression reads a species field (species.NAME).
   @param doc   battle Document
   @param name  field name (without the prefix)
   @return "generation[k] (ROLE)" per entry
   """
   wanted = str(_bc().SPECIES_PREFIX) + name
   out = []
   for k, e in enumerate(entries_of(doc)):
      if way_of(e) == DERIVED_WAY and isinstance(e[DERIVED_WAY], str) and \
            wanted in IDENTIFIER.findall(e[DERIVED_WAY]):
         out.append(f"{GENERATION_KEY}[{k}] ({e.get(ROLE_KEY)})")
   return out


def rename_field(doc: Document, old: str, new: str) -> int:
   """!Follows a species field's rename in the derived expressions (species.OLD -> species.NEW; called inside the
   rename's edit).
   @param doc  battle Document
   @param old  old field name
   @param new  new field name
   @return entries changed
   """
   if is_default(doc):
      return 0
   prefix = str(_bc().SPECIES_PREFIX)
   mapping = {prefix + old: prefix + new}
   changed = 0
   for e in battle.data_of(doc, GENERATION_KEY)[GENERATION_KEY]:
      expr = e.get(DERIVED_WAY) if isinstance(e, dict) else None
      if isinstance(expr, str):
         fixed = IDENTIFIER.sub(lambda m: mapping.get(m.group(0), m.group(0)), expr)
         if fixed != expr:
            e[DERIVED_WAY] = fixed
            changed += 1
   return changed


# -- report ------------------------------------------------------------------------------------------------------------

def row_text(row: GenRow) -> str:
   """!A generation entry as text.
   @param row  a generation_rows() row
   @return the text
   """
   if row["way"] == RANDOM_WAY:
      how = f"random [{row['lo']}, {row['hi']}]" + (f" {row['order']}" if row.get("order") else "")
   elif row["way"] == CONSTANT_WAY:
      how = f"constant {row['value']}"
   elif row["way"] == DERIVED_WAY:
      how = f"derived {row['expr']}" + (f" in {row['range']}" if row["range"] is not None else "")
   else:
      how = "?"
   if row["draws"]:
      last = row["first"] + row["draws"] - 1
      draws = f"draw {row['first']}" if last == row["first"] else f"draws {row['first']}-{last}"
      if row["species"]:
         draws += " (when the species has two passives)"
   else:
      draws = "no draw"
   return f"{row['index']} {row['role']}: {how}; {draws}" + (f"; error: {row['error']}" if row["error"] else "")


def lines(doc: Document) -> list[str]:
   """!The progression rules as text lines ("(default)" marks what the engine gives).
   @param doc  battle Document
   @return lines
   """
   out = []
   for part in (LEARN_KEY, EXP_KEY):
      value, left = policy(doc, part)
      out.append(f"{part}: " + ", ".join(f"{k} {v if v is not None else '(required)'}" +
                                         (" (default)" if k in left else "") for k, v in value.items()))
   out.append(f"{GENERATION_KEY}" + (" (default)" if is_default(doc) else "") + ":")
   out += ["  " + row_text(r) for r in generation_rows(doc)]
   for part, error in compile_progress(doc).items():
      if error:
         out.append(f"{part} error: {error}")
   return out
