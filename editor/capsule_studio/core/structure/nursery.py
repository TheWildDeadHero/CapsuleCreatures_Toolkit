"""!Eggs and the nursery of battle data (engine B2, D-28 sections 2 and 3): the structure manifest's "eggs" and
"nursery", and the refusal flags of the systems that use records.

    structure.json  "eggs": {"role": "egg", "counter": "hatch_counter", "cycles_field": "hatch_cycles",
                             "step_effect": "egg_cycle", "hatch_script": "hatch_egg", "name": "Egg",
                             "sprite": "sprite:Egg", "sprite_field": "egg_look"},
                    "nursery": {"slots": 2, "method": "grove", "check": "grove_check", "odds_scale": 100,
                                "gain": true, "fee": true}

The engine has no idea of breeding (tools/battlec/nursery.py): an egg is an ordinary record whose egg role is set,
with a hatch counter role holding the steps left (a method delivering eggs seeds it with the species' cycles field
times the method's cycle steps); the egg step effect's runs take steps off it and an egg at 0 hatches (the hatch
script runs with the implicit variable egg_member). The nursery holds a few records a combination method of kind
"nursery" checks on the runs of its check step effect; gain gives the held records experience per step (the
ruleset pipeline nursery_gain), fee makes taking one back cost (nursery_fee). The systems that would use a record
refuse eggs unless their own allow_eggs flag says otherwise: battle setup (rules), recruitment (recruit), each field
action, each item and each combination method; refusal_rows() lists them all, set_refusal() writes one.

Each editing helper is one change: call it inside one edit() of either manifest. The renames of what the sections
name follow into them (follow_role(), follow_species_field(), follow_step_effect(), follow_method(); the hatch
script follows through core.structure.field_expressions.follow_script()) and removals are refused while they name
it (uses()). An edit that stops data that compiled from compiling is refused with the engine's message.

Test saves (capsule.testsave/1) hold the nursery's records ("nursery": [{"slot", "species", "level", "gained"}]),
its waiting result ("nursery_result": {"species", "level", "hatch"}) and eggs in the boxes (a boxed creature's
"hatch": its counter); image_parts() turns them into what the engine's save_layout.image() writes.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .. import battle, engine, logic
from ..document import Document, DocumentError

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure's egg section.
EGGS_KEY = "eggs"
## The structure's nursery section.
NURSERY_KEY = "nursery"
## The refusal flag every system states.
ALLOW_KEY = "allow_eggs"
## The egg section's keys naming other parts of the battle data, by what they name.
EGG_ROLE_KEYS = ("role", "counter")
## The egg section's species field keys.
EGG_FIELD_KEYS = ("cycles_field", "sprite_field")
## The egg section's step effect key.
EGG_STEP_KEY = "step_effect"
## The egg section's script key.
SCRIPT_KEY = "hatch_script"
## The egg section's name and sprite keys.
NAME_KEY, SPRITE_KEY = "name", "sprite"
## Every key of the egg section, in the order the page shows them.
EGG_KEYS = ("role", "counter", "cycles_field", "step_effect", "hatch_script", "name", "sprite", "sprite_field")
## The egg keys a section must state.
EGG_REQUIRED = ("role", "counter", "cycles_field", "step_effect")
## The nursery's keys.
SLOTS_KEY, METHOD_KEY, CHECK_KEY, SCALE_KEY, GAIN_KEY, FEE_KEY = "slots", "method", "check", "odds_scale", "gain", \
   "fee"
## Every key of the nursery, in the order the page shows them.
NURSERY_KEYS = (SLOTS_KEY, METHOD_KEY, CHECK_KEY, SCALE_KEY, GAIN_KEY, FEE_KEY)
## The nursery's flag keys.
NURSERY_FLAGS = (GAIN_KEY, FEE_KEY)
## The systems with one refusal flag for the whole section (structure key: what the page calls it; C9: the
## encounter lead rules and transformations).
SECTION_SYSTEMS = {"rules": "battle setup", "recruit": "recruitment", "lead": "encounter lead",
                   "transformation": "transformation"}
## The sections a flag may create when they are absent (the others need their section).
CREATED_SECTIONS = ("rules", "lead")
## The systems with a refusal flag per entry (list key, the manifest holding it; C9: the step effects' handlers).
LIST_SYSTEMS = {"field_actions": "field action", "items": "item", "combine_methods": "combination method",
                "step_effects": "step effect"}
## C9: the structure key of what a build without an egg role does with a transferred egg.
TRANSFER_EGGS_KEY = "transfer_eggs"
## A method's keys the eggs read.
DELIVERY_KEY, CYCLE_KEY, KIND_KEY = "delivery", "cycle_steps", "kind"
## A species field's value key in a species.
SPECIES_FIELDS_KEY = "fields"
## Location the compiler's messages name.
WHERE = "structure"

# -- test saves --------------------------------------------------------------------------------------------------------

## A test save's nursery slots: [{"slot", "species", "level", "gained"}].
TESTSAVE_NURSERY = "nursery"
## A test save's waiting result: {"species", "level", "hatch"} ("hatch": an egg with that counter).
TESTSAVE_RESULT = "nursery_result"
## A slot's or result's keys.
SLOT_KEY, SPECIES_KEY, LEVEL_KEY, GAINED_KEY, HATCH_KEY = "slot", "species", "level", "gained", "hatch"
## The record roles a test record states (tools/record_transfer.py names).
SPECIES_ROLE, LEVEL_ROLE = "species_key", "level"
## Level of a new test record.
NEW_LEVEL = 5
## Largest experience a slot's gain holds (the save's u32).
MAX_GAINED = 0xFFFFFFFF
## Largest level a nursery slot's "level when left" holds (the save's byte).
MAX_SLOT_LEVEL = 0xFF


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def default_name() -> str:
   """!What an egg is called without a name of its own (the engine's DEFAULT_EGG_NAME).
   @return the name
   """
   return str(_bc().DEFAULT_EGG_NAME)


def max_name_chars() -> int:
   """!The longest egg name (the engine's MAX_EGG_NAME_CHARS).
   @return letters
   """
   return int(_bc().MAX_EGG_NAME_CHARS)


def default_odds_scale() -> int:
   """!The nursery's odds scale when it states none (the engine's NURSERY_DEFAULT_ODDS).
   @return it
   """
   return int(_bc().NURSERY_DEFAULT_ODDS)


def default_cycle_steps() -> int:
   """!The steps of an egg cycle of a method stating none (the engine's DEFAULT_CYCLE_STEPS).
   @return steps
   """
   return int(_bc().DEFAULT_CYCLE_STEPS)


def max_slots(targets: list[str] | None = None) -> int:
   """!The most nursery slots on every target (build_settings max_nursery_slots).
   @param targets  platform names (None: every platform)
   @return slots
   """
   bs = engine.tool("build_settings")
   names = targets or list(bs.PLATFORMS)
   return min(int(bs.platform_limits(p)["max_nursery_slots"]) for p in names)


def member_var() -> str:
   """!The implicit variable the hatch script reads (the engine's EGG_MEMBER_VAR).
   @return its name
   """
   return str(_bc().EGG_MEMBER_VAR)


# -- reading -----------------------------------------------------------------------------------------------------------

def _section(doc: Document | None, key: str) -> JsonDict | None:
   """!One of the two sections (live), or None when the structure states none.
   @param doc  any manifest Document of the battle, or None
   @param key  EGGS_KEY or NURSERY_KEY
   @return the dict or None
   """
   if doc is None:
      return None
   given = battle.data_of(doc, key).get(key)
   return given if isinstance(given, dict) else None


def eggs(doc: Document | None) -> JsonDict | None:
   """!The egg section (live).
   @param doc  any manifest Document of the battle, or None
   @return the dict, or None without eggs
   """
   return _section(doc, EGGS_KEY)


def nursery(doc: Document | None) -> JsonDict | None:
   """!The nursery (live).
   @param doc  any manifest Document of the battle, or None
   @return the dict, or None without a nursery
   """
   return _section(doc, NURSERY_KEY)


def _methods(doc: Document) -> list[JsonDict]:
   """!The combination methods.
   @param doc  any manifest Document of the battle
   @return method dicts
   """
   from . import combination   # local: combination imports core.structure
   return combination.methods(doc)


def role_choices(doc: Document) -> list[str]:
   """!The roles the egg role and the counter may name: the stored custom roles of one element.
   @param doc  any manifest Document of the battle
   @return names
   """
   from . import record   # local: record imports this module
   return [r["name"] for r in record.role_rows(doc)
           if r["kind"] == record.KIND_CUSTOM and r["count"] == 1 and r["stored"]]


def field_choices(doc: Document) -> list[str]:
   """!The species fields the cycles and the egg look may name.
   @param doc  any manifest Document of the battle
   @return names
   """
   from . import species_fields   # local: species_fields imports this module
   return species_fields.field_names(doc)


def step_choices(doc: Document) -> list[str]:
   """!The step effects the egg cycle and the nursery check may name.
   @param doc  any manifest Document of the battle
   @return names
   """
   from . import step_effects   # local: step_effects imports this module
   return step_effects.effect_names(doc)


def script_choices(doc: Document) -> list[str]:
   """!The game's scripts the hatch script may name.
   @param doc  any manifest Document of the battle
   @return names
   """
   from . import step_effects   # local: the same lookup
   return step_effects.script_choices(doc)


def method_choices(doc: Document) -> list[str]:
   """!The combination methods of kind nursery (the nursery's method).
   @param doc  any manifest Document of the battle
   @return names
   """
   kind = str(_bc().NURSERY_KIND)
   return [str(m.get("name")) for m in _methods(doc) if m.get(KIND_KEY) == kind]


def egg_methods(doc: Document) -> list[tuple[str, int]]:
   """!The methods delivering eggs with their cycle steps.
   @param doc  any manifest Document of the battle
   @return [(name, steps of one cycle)]
   """
   out = []
   for m in _methods(doc):
      if m.get(DELIVERY_KEY) == _bc().EGG_DELIVERY:
         steps = m.get(CYCLE_KEY, default_cycle_steps())
         out.append((str(m.get("name")), steps if isinstance(steps, int) else default_cycle_steps()))
   return out


def egg_row(doc: Document) -> JsonDict | None:
   """!The egg section with its defaults filled in.
   @param doc  any manifest Document of the battle
   @return {key: value ("" when left out; name: the default)}, or None without eggs
   """
   e = eggs(doc)
   if e is None:
      return None
   out: JsonDict = {k: e.get(k) if isinstance(e.get(k), str) else "" for k in EGG_KEYS}
   out[NAME_KEY] = out[NAME_KEY] or default_name()
   return out


def nursery_row(doc: Document) -> JsonDict | None:
   """!The nursery with its defaults filled in.
   @param doc  any manifest Document of the battle
   @return {key: value}, or None without a nursery
   """
   n = nursery(doc)
   if n is None:
      return None
   from . import combination   # local: combination imports core.structure
   method = next((m for m in _methods(doc) if m.get("name") == n.get(METHOD_KEY)), None)
   most = combination.count_of(method)[1] if method is not None else 0
   return {SLOTS_KEY: n.get(SLOTS_KEY, most), METHOD_KEY: str(n.get(METHOD_KEY, "")),
           CHECK_KEY: str(n.get(CHECK_KEY, "")), SCALE_KEY: n.get(SCALE_KEY, default_odds_scale()),
           GAIN_KEY: n.get(GAIN_KEY) is True, FEE_KEY: n.get(FEE_KEY) is True}


def species_eggs(doc: Document, species: str) -> JsonDict | None:
   """!A species' egg values as the Species page shows them: its hatch cycles, the steps an egg of it counts from
   for each egg method, and its egg look.
   @param doc      any manifest Document of the battle
   @param species  species name
   @return {"cycles_field", "cycles", "max", "steps": [(method, steps)], "look_field" ("" without), "look",
           "look_max", "sprite"}, or None without eggs (or a cycles field the structure lacks)
   """
   from . import species_fields   # local: species_fields imports this module
   row = egg_row(doc)
   if row is None:
      return None
   values = {v["name"]: v for v in species_fields.values_of(doc, species)}
   cycles = values.get(row["cycles_field"])
   if cycles is None:
      return None
   look = values.get(row["sprite_field"])
   n = cycles["value"] if isinstance(cycles["value"], int) else 0
   return {"cycles_field": row["cycles_field"], "cycles": n, "max": cycles["max"],
           "steps": [(m, n * steps) for m, steps in egg_methods(doc)],
           "look_field": row["sprite_field"] if look is not None else "",
           "look": look["value"] if look is not None else 0, "look_max": look["max"] if look is not None else 0,
           "sprite": row[SPRITE_KEY]}


def compile_check(doc: Document) -> tuple[JsonDict | None, str | None]:
   """!The whole battle data's compile (the egg and nursery tables need the layout, the species and the methods).
   @param doc  any manifest Document of the battle
   @return ({"eggs", "nursery"} compiled, or None; the compiler's message or None)
   """
   project = logic.project_of(doc)
   if project is None:
      return None, "the battle data is in no project"
   compiled, error = project.compile()
   if compiled is None:
      return None, error
   return {EGGS_KEY: compiled["combine"].get(EGGS_KEY), NURSERY_KEY: compiled["combine"].get(NURSERY_KEY)}, None


def fee_table(doc: Document, levels: int, level: int, count: int) -> int | None:
   """!What taking a record back costs (the engine's nursery_fee mirror).
   @param doc     any manifest Document of the battle
   @param levels  the levels it gained there
   @param level   its level now
   @param count   the records held
   @return the fee, or None when the data does not compile
   """
   project = logic.project_of(doc)
   compiled = project.compile()[0] if project is not None else None
   if compiled is None:
      return None
   return int(_bc().nursery_fee_of(compiled, levels, level, count))


def gain_of(doc: Document, level: int, slot: int) -> int | None:
   """!The experience a held record gains per step (the engine's nursery_gain mirror).
   @param doc    any manifest Document of the battle
   @param level  its level when left
   @param slot   its slot
   @return experience per step, or None when the data does not compile
   """
   project = logic.project_of(doc)
   compiled = project.compile()[0] if project is not None else None
   if compiled is None:
      return None
   return int(_bc().nursery_gain_of(compiled, level, slot))


# -- the refusal flags -------------------------------------------------------------------------------------------------

def refusal_rows(doc: Document) -> list[tuple[str, str, bool]]:
   """!Every system that refuses eggs unless its flag allows them.
   @param doc  any manifest Document of the battle
   @return [(system, entry name ("" for a whole section), allowed)]
   """
   out = []
   for key, what in SECTION_SYSTEMS.items():
      given = battle.data_of(doc, key).get(key)
      if isinstance(given, dict) or key in CREATED_SECTIONS:
         out.append((what, "", isinstance(given, dict) and given.get(ALLOW_KEY) is True))
   for key, what in LIST_SYSTEMS.items():
      given = battle.data_of(doc, key).get(key)
      for e in given if isinstance(given, list) else []:
         if isinstance(e, dict) and isinstance(e.get("name"), str):
            out.append((what, e["name"], e.get(ALLOW_KEY) is True))
   return out


def allowed(doc: Document, system: str, name: str = "") -> bool:
   """!One system's flag.
   @param doc     any manifest Document of the battle
   @param system  a structure key of SECTION_SYSTEMS or LIST_SYSTEMS
   @param name    the entry (list systems)
   @return True when it takes eggs
   """
   return _flag_holder(doc, system, name, False).get(ALLOW_KEY) is True


def _flag_holder(doc: Document, system: str, name: str, create: bool) -> JsonDict:
   """!The dict a system's flag is in.
   @param doc     any manifest Document of the battle
   @param system  a structure key of SECTION_SYSTEMS or LIST_SYSTEMS
   @param name    the entry (list systems)
   @param create  write an absent section (SECTION_SYSTEMS)
   @return the live dict ({} when it is absent and not created)
   @throws DocumentError for an unknown system or entry
   """
   data = battle.data_of(doc, system)
   if system in SECTION_SYSTEMS:
      given = data.get(system)
      if not isinstance(given, dict):
         if not create:
            return {}
         if system not in CREATED_SECTIONS:
            raise DocumentError(f"the structure states no {system} section ({SECTION_SYSTEMS[system]})")
         data[system] = given = {}
      return given
   if system not in LIST_SYSTEMS:
      raise DocumentError(f"no egg refusal on {system!r} (systems: "
                          f"{', '.join([*SECTION_SYSTEMS, *LIST_SYSTEMS])})")
   given = data.get(system)
   for e in given if isinstance(given, list) else []:
      if isinstance(e, dict) and e.get("name") == name:
         return e
   raise DocumentError(f"no {LIST_SYSTEMS[system]} {name!r}")


def set_refusal(doc: Document, system: str, name: str, on: bool) -> None:
   """!Sets whether a system takes eggs (False: the key goes; refused is the engine's default).
   @param doc     any manifest Document of the battle
   @param system  a structure key of SECTION_SYSTEMS or LIST_SYSTEMS
   @param name    the entry (list systems; "" for a section)
   @param on      True: it takes eggs
   @return None
   """
   holder = _flag_holder(doc, system, name, on)

   def change() -> None:
      """!Writes it."""
      if on:
         holder[ALLOW_KEY] = True
      else:
         holder.pop(ALLOW_KEY, None)
   _guarded(doc, change)


def transfer_choices() -> list[str]:
   """!What a build without an egg role may do with a transferred egg (C9; the engine's TRANSFER_EGGS, refuse first).
   @return the choices
   """
   return list(_bc().TRANSFER_EGGS)


def transfer_eggs(doc: Document) -> str:
   """!The structure's transfer rule for eggs (C9).
   @param doc  any manifest Document of the battle
   @return "refuse" (default) or "hatch"
   """
   rule = battle.data_of(doc, TRANSFER_EGGS_KEY).get(TRANSFER_EGGS_KEY)
   return rule if rule in transfer_choices() else transfer_choices()[0]


def set_transfer_eggs(doc: Document, rule: str) -> None:
   """!Sets what the build does with a transferred egg its layout has no egg role for (C9: refuse, the default, or
   hatch: it arrives hatched).
   @param doc   any manifest Document of the battle
   @param rule  one of transfer_choices()
   @return None
   """
   if rule not in transfer_choices():
      raise DocumentError(f"transfer_eggs: one of {', '.join(transfer_choices())}")
   data = battle.structure_doc(doc).data

   def change() -> None:
      """!Writes it (the default goes)."""
      if rule == transfer_choices()[0]:
         data.pop(TRANSFER_EGGS_KEY, None)
      else:
         data[TRANSFER_EGGS_KEY] = rule
   _guarded(doc, change)


# -- editing -----------------------------------------------------------------------------------------------------------

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


def _pick(names: list[str], hints: tuple[str, ...], taken: tuple[str, ...], what: str) -> str:
   """!The first name holding one of some words, else the first one not taken.
   @param names  the choices
   @param hints  words to look for, in order
   @param taken  names another key took
   @param what   what it is (messages)
   @return the name
   @throws DocumentError without a choice
   """
   free = [n for n in names if n not in taken]
   for hint in hints:
      found = next((n for n in free if hint in n), None)
      if found is not None:
         return found
   if not free:
      raise DocumentError(f"eggs and the nursery need {what}")
   return free[0]


def egg_defaults(doc: Document) -> tuple[str, str, str, str]:
   """!What a new egg section names (the Nursery page's "The game has eggs"): roles, field and step effect whose
   names suggest them, else the first ones.
   @param doc  any manifest Document of the battle
   @return (role, counter, cycles field, step effect)
   @throws DocumentError when the structure lacks two one-element custom roles, a species field or a step effect
   """
   roles = role_choices(doc)
   role = _pick(roles, ("egg",), (), "a custom role of one element for the egg role (Structure > Record)")
   counter = _pick(roles, ("hatch", "counter"), (role,), "a second custom role for the hatch counter")
   cycles = _pick(field_choices(doc), ("hatch", "cycle"), (), "a species field for the hatch cycles")
   step = _pick(step_choices(doc), ("egg", "hatch"), (), "a step effect for the egg cycles (Structure > Step effects)")
   return role, counter, cycles, step


def nursery_defaults(doc: Document) -> tuple[str, str]:
   """!What a new nursery names (the Nursery page's "The game has a nursery").
   @param doc  any manifest Document of the battle
   @return (method, check step effect)
   @throws DocumentError without a method of kind nursery or a step effect
   """
   method = _pick(method_choices(doc), (), (), "a combination method of kind nursery (Structure > Combination)")
   check = _pick(step_choices(doc), ("check", "nursery"), (), "a step effect for the nursery's checks")
   return method, check


def enable_eggs(doc: Document, role: str, counter: str, cycles_field: str, step_effect: str) -> None:
   """!Writes the egg section.
   @param doc           any manifest Document of the battle
   @param role          the egg role (role_choices())
   @param counter       the hatch counter role (role_choices())
   @param cycles_field  the species field of the hatch cycles
   @param step_effect   the step effect of the egg cycles
   @return None
   """
   if eggs(doc) is not None:
      raise DocumentError("the structure states eggs already")
   values = {"role": role, "counter": counter, "cycles_field": cycles_field, EGG_STEP_KEY: step_effect}
   for key, value in values.items():
      _check_choice(doc, key, value)
   _guarded(doc, lambda: battle.data_of(doc, EGGS_KEY).__setitem__(EGGS_KEY, dict(values)))


def disable_eggs(doc: Document) -> None:
   """!Removes the egg section (refused while a method delivers eggs: the engine's message).
   @param doc  any manifest Document of the battle
   @return None
   """
   if eggs(doc) is None:
      return
   egg = egg_methods(doc)
   if egg:
      raise DocumentError(f"combination method {egg[0][0]!r} delivers eggs: change its delivery first")
   _guarded(doc, lambda: battle.data_of(doc, EGGS_KEY).pop(EGGS_KEY, None))


def _check_choice(doc: Document, key: str, value: Any) -> Any:
   """!An egg key's value, checked against its choices (the engine checks the rest).
   @param doc    any manifest Document of the battle
   @param key    one of EGG_KEYS
   @param value  the value
   @return it
   @throws DocumentError for a value that is not a choice
   """
   choices = {"role": role_choices, "counter": role_choices, "cycles_field": field_choices,
              "sprite_field": field_choices, EGG_STEP_KEY: step_choices, SCRIPT_KEY: script_choices}
   if key in choices and value is not None:
      names = choices[key](doc)
      if value not in names:
         raise DocumentError(f"eggs {key}: one of {', '.join(names) or 'none'} (got {value!r})")
   return value


def set_egg(doc: Document, key: str, value: str | None) -> None:
   """!Sets one key of the egg section (None or empty: the key goes, for the optional ones).
   @param doc    any manifest Document of the battle
   @param key    one of EGG_KEYS
   @param value  the value
   @return None
   """
   e = eggs(doc)
   if e is None:
      raise DocumentError("the structure states no eggs")
   if key not in EGG_KEYS:
      raise DocumentError(f"eggs: one of {', '.join(EGG_KEYS)} (got {key!r})")
   value = value.strip() if isinstance(value, str) else value
   value = value or None
   if value is None and key in EGG_REQUIRED:
      raise DocumentError(f"eggs {key}: the engine needs it")
   if key == NAME_KEY and value is not None and len(value) > max_name_chars():
      raise DocumentError(f"an egg's name is at most {max_name_chars()} letters")
   _check_choice(doc, key, value)

   def change() -> None:
      """!Writes it (the default name goes)."""
      if value is None or (key == NAME_KEY and value == default_name()):
         e.pop(key, None)
      else:
         e[key] = value
   _guarded(doc, change)


def enable_nursery(doc: Document, method: str, check: str) -> None:
   """!Writes the nursery (its slots: the method's inputs).
   @param doc     any manifest Document of the battle
   @param method  a method of kind nursery (method_choices())
   @param check   the step effect of the checks
   @return None
   """
   if nursery(doc) is not None:
      raise DocumentError("the structure states a nursery already")
   if method not in method_choices(doc):
      raise DocumentError(f"nursery method: one of {', '.join(method_choices(doc)) or 'none of kind nursery'}")
   if check not in step_choices(doc):
      raise DocumentError(f"nursery check: one of {', '.join(step_choices(doc)) or 'no step effects'}")
   _guarded(doc, lambda: battle.data_of(doc, NURSERY_KEY).__setitem__(NURSERY_KEY,
                                                                       {METHOD_KEY: method, CHECK_KEY: check}))


def disable_nursery(doc: Document) -> None:
   """!Removes the nursery (refused while a method of kind nursery needs it: the engine's message).
   @param doc  any manifest Document of the battle
   @return None
   """
   if nursery(doc) is None:
      return
   _guarded(doc, lambda: battle.data_of(doc, NURSERY_KEY).pop(NURSERY_KEY, None))


def set_nursery(doc: Document, key: str, value: Any) -> None:
   """!Sets one key of the nursery (its default: the key goes).
   @param doc    any manifest Document of the battle
   @param key    one of NURSERY_KEYS
   @param value  slots / odds_scale: a number; method / check: a name; gain / fee: a flag
   @return None
   """
   n = nursery(doc)
   if n is None:
      raise DocumentError("the structure states no nursery")
   if key not in NURSERY_KEYS:
      raise DocumentError(f"nursery: one of {', '.join(NURSERY_KEYS)} (got {key!r})")
   if key in NURSERY_FLAGS and not isinstance(value, bool):
      raise DocumentError(f"nursery {key}: true or false (got {value!r})")
   if key in (SLOTS_KEY, SCALE_KEY) and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
      raise DocumentError(f"nursery {key}: a whole number 1 or more (got {value!r})")
   if key == METHOD_KEY and value not in method_choices(doc):
      raise DocumentError(f"nursery method: one of {', '.join(method_choices(doc)) or 'none of kind nursery'}")
   if key == CHECK_KEY and value not in step_choices(doc):
      raise DocumentError(f"nursery check: one of {', '.join(step_choices(doc)) or 'no step effects'}")
   defaults = {GAIN_KEY: False, FEE_KEY: False, SCALE_KEY: default_odds_scale()}

   def change() -> None:
      """!Writes it."""
      if key in defaults and value == defaults[key]:
         n.pop(key, None)
      else:
         n[key] = value
   _guarded(doc, change)


# -- what the sections name --------------------------------------------------------------------------------------------

def _follow(d: JsonDict, section: str, keys: tuple[str, ...], old: str, new: str | None) -> list[str]:
   """!Finds (and renames) a name some keys of one section state.
   @param d        the battle data (battle.merged(): its sections live)
   @param section  EGGS_KEY or NURSERY_KEY
   @param keys     the keys naming it
   @param old      the name
   @param new      its new name, or None to only look
   @return "where" strings
   """
   given = d.get(section)
   found = []
   for key in keys if isinstance(given, dict) else ():
      if given.get(key) == old:
         found.append(f"{section}.{key}")
         if new is not None:
            given[key] = new
   return found


def follow_role(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A custom role's rename (or its users): the egg role and the hatch counter.
   @param d    the battle data
   @param old  the role
   @param new  its new name, or None to only look
   @return "where" strings
   """
   return _follow(d, EGGS_KEY, EGG_ROLE_KEYS, old, new)


def follow_species_field(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A species field's rename (or its users): the hatch cycles and the egg look.
   @param d    the battle data
   @param old  the field
   @param new  its new name, or None to only look
   @return "where" strings
   """
   return _follow(d, EGGS_KEY, EGG_FIELD_KEYS, old, new)


def follow_step_effect(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A step effect's rename (or its users): the egg cycle and the nursery check.
   @param d    the battle data
   @param old  the effect
   @param new  its new name, or None to only look
   @return "where" strings
   """
   return _follow(d, EGGS_KEY, (EGG_STEP_KEY,), old, new) + _follow(d, NURSERY_KEY, (CHECK_KEY,), old, new)


def follow_method(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A combination method's rename (or its users): the nursery's method.
   @param d    the battle data
   @param old  the method
   @param new  its new name, or None to only look
   @return "where" strings
   """
   return _follow(d, NURSERY_KEY, (METHOD_KEY,), old, new)


def follow_script(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A game script's rename (or its users): the hatch script.
   @param d    the battle data
   @param old  the script
   @param new  its new name, or None to only look
   @return "where" strings
   """
   return _follow(d, EGGS_KEY, (SCRIPT_KEY,), old, new)


def uses(doc: Document, kind: str, name: str) -> list[str]:
   """!What the two sections name (removals are refused while it is used).
   @param doc   any manifest Document of the battle
   @param kind  "role", "species_field", "step_effect", "method" or "script"
   @param name  the name
   @return "where" strings
   """
   look = {"role": follow_role, "species_field": follow_species_field, "step_effect": follow_step_effect,
           "method": follow_method, "script": follow_script}
   return look[kind](battle.merged(doc), name, None)


def lines(doc: Document) -> list[str]:
   """!The two sections and the refusal flags as text (the CLI's `nursery show`).
   @param doc  any manifest Document of the battle
   @return lines
   """
   out = []
   e = egg_row(doc)
   if e is None:
      out.append("eggs: none")
   else:
      out.append("eggs: " + ", ".join(f"{k} {e[k] or '-'}" for k in EGG_KEYS))
      out.append("egg methods: " + (", ".join(f"{m} ({s} steps a cycle)" for m, s in egg_methods(doc)) or "none"))
   n = nursery_row(doc)
   if n is None:
      out.append("nursery: none")
   else:
      out.append("nursery: " + ", ".join(f"{k} {str(n[k]).lower() if isinstance(n[k], bool) else n[k]}"
                                         for k in NURSERY_KEYS))
   refused = [f"{what} {name}".strip() + (" takes eggs" if on else " refuses eggs")
              for what, name, on in refusal_rows(doc)]
   return out + ["refusals: " + ("; ".join(refused) or "none"), f"transferred eggs: {transfer_eggs(doc)}"]


# -- test saves --------------------------------------------------------------------------------------------------------

def _whole(value: Any, lo: int, hi: int, what: str) -> int:
   """!A whole number in a range.
   @param value  the value
   @param lo     lowest
   @param hi     highest
   @param what   what it is (messages)
   @return it
   @throws DocumentError out of range
   """
   if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
      raise DocumentError(f"{what}: {lo} to {hi} (got {value!r})")
   return value


def _species_names(doc: Document) -> list[str]:
   """!The battle's species.
   @param doc  any manifest Document of the battle
   @return names
   """
   return [str(e.get("name")) for e in battle.entries(battle.content_doc(doc), "species") if isinstance(e, dict)]


def counter_max(doc: Document) -> int:
   """!The largest hatch counter the egg counter role holds.
   @param doc  any manifest Document of the battle
   @return it (0 without eggs)
   """
   from . import record   # local: record imports this module
   e = eggs(doc)
   if e is None or e.get("counter") not in role_choices(doc):
      return 0
   return int(record.role_max(battle.structure_doc(doc), e["counter"]))


def held_of(save: Document) -> list[JsonDict]:
   """!A test save's nursery slots, by slot.
   @param save  test save Document
   @return [{"slot", "species", "level", "gained"}] (copies)
   """
   given = save.data.get(TESTSAVE_NURSERY)
   out = [dict(b) for b in (given if isinstance(given, list) else []) if isinstance(b, dict)]
   return sorted(out, key=lambda b: b.get(SLOT_KEY) if isinstance(b.get(SLOT_KEY), int) else -1)


def result_of(save: Document) -> JsonDict | None:
   """!A test save's waiting result.
   @param save  test save Document
   @return {"species", "level", "hatch"} (a copy), or None
   """
   given = save.data.get(TESTSAVE_RESULT)
   return dict(given) if isinstance(given, dict) else None


def slot_count(doc: Document) -> int:
   """!The nursery's slots.
   @param doc  any manifest Document of the battle
   @return slots (0 without a nursery)
   """
   n = nursery_row(doc)
   return int(n[SLOTS_KEY]) if n is not None and isinstance(n[SLOTS_KEY], int) else 0


def put_held(save: Document, doc: Document, slot: int, species: str, level: int = NEW_LEVEL,
             gained: int = 0) -> None:
   """!Leaves a record in a nursery slot of a test save (inside save.edit(); a held slot is replaced).
   @param save     test save Document
   @param doc      any manifest Document of the battle
   @param slot     the slot
   @param species  species name
   @param level    its level when left
   @param gained   the experience it gained there
   @return None
   """
   slots = slot_count(doc)
   if slots == 0:
      raise DocumentError("the structure states no nursery")
   _whole(slot, 0, slots - 1, "nursery slot")
   if species not in _species_names(doc):
      raise DocumentError(f"no species {species!r}")
   _whole(level, 1, MAX_SLOT_LEVEL, "level")
   _whole(gained, 0, MAX_GAINED, "experience gained")
   take_held(save, slot, missing_ok=True)
   entry: JsonDict = {SLOT_KEY: slot, SPECIES_KEY: species, LEVEL_KEY: level}
   if gained:
      entry[GAINED_KEY] = gained
   save.data.setdefault(TESTSAVE_NURSERY, []).append(entry)


def take_held(save: Document, slot: int, missing_ok: bool = False) -> JsonDict | None:
   """!Empties a nursery slot of a test save (inside save.edit()).
   @param save        test save Document
   @param slot        the slot
   @param missing_ok  an empty slot is no error
   @return the entry taken, or None
   @throws DocumentError when the slot is empty (and not missing_ok)
   """
   lst = save.data.get(TESTSAVE_NURSERY)
   for b in list(lst) if isinstance(lst, list) else []:
      if isinstance(b, dict) and b.get(SLOT_KEY) == slot:
         lst.remove(b)
         if not lst:
            save.data.pop(TESTSAVE_NURSERY, None)
         return b
   if missing_ok:
      return None
   raise DocumentError(f"nursery slot {slot!r} is empty")


def set_result(save: Document, doc: Document, species: str | None, hatch: int | None = None,
               level: int = 1) -> None:
   """!Sets a test save's waiting result (inside save.edit()).
   @param save     test save Document
   @param doc      any manifest Document of the battle
   @param species  species name, or None: no result waits
   @param hatch    an egg's hatch counter, or None: not an egg
   @param level    its level
   @return None
   """
   if species is None:
      save.data.pop(TESTSAVE_RESULT, None)
      return
   if nursery(doc) is None:
      raise DocumentError("the structure states no nursery")
   if species not in _species_names(doc):
      raise DocumentError(f"no species {species!r}")
   _whole(level, 1, MAX_SLOT_LEVEL, "level")
   entry: JsonDict = {SPECIES_KEY: species, LEVEL_KEY: level}
   if hatch is not None:
      if eggs(doc) is None:
         raise DocumentError("the structure states no eggs")
      entry[HATCH_KEY] = _whole(hatch, 0, counter_max(doc), "hatch counter")
   save.data[TESTSAVE_RESULT] = entry


def set_boxed_hatch(save: Document, doc: Document, slot: int, hatch: int | None) -> None:
   """!Makes a boxed creature of a test save an egg (or a creature again; inside save.edit()).
   @param save   test save Document
   @param doc    any manifest Document of the battle
   @param slot   its storage slot
   @param hatch  its hatch counter, or None: not an egg
   @return None
   """
   from . import storage   # local: storage reads this module's egg keys
   lst = save.data.get(storage.TESTSAVE_BOXES)
   for b in lst if isinstance(lst, list) else []:
      if isinstance(b, dict) and b.get(storage.BOXED_SLOT) == slot:
         if hatch is None:
            b.pop(HATCH_KEY, None)
            return
         if eggs(doc) is None:
            raise DocumentError("the structure states no eggs")
         b[HATCH_KEY] = _whole(hatch, 0, counter_max(doc), "hatch counter")
         return
   raise DocumentError(f"storage slot {slot!r} is empty")


def _check_entry(doc: Document, b: Mapping[str, Any], where: str, species: list[str]) -> list[str]:
   """!What the manifests refuse in one test record (species, level, an egg's counter).
   @param doc      any manifest Document of the battle
   @param b        the entry
   @param where    what it is (messages)
   @param species  the battle's species
   @return problems
   """
   out = []
   if b.get(SPECIES_KEY) not in species:
      out.append(f"{where}: unknown species {b.get(SPECIES_KEY)!r}")
   level = b.get(LEVEL_KEY)
   if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= MAX_SLOT_LEVEL:
      out.append(f"{where}: level {level!r}")
   if HATCH_KEY in b:
      top = counter_max(doc)
      hatch = b.get(HATCH_KEY)
      if eggs(doc) is None:
         out.append(f"{where}: an egg, but the structure states no eggs")
      elif not isinstance(hatch, int) or isinstance(hatch, bool) or not 0 <= hatch <= top:
         out.append(f"{where}: hatch counter {hatch!r} (0-{top})")
   return out


def check_test(save: Document, doc: Document) -> list[str]:
   """!What the manifests refuse in a test save's nursery, result and boxed eggs.
   @param save  test save Document
   @param doc   any manifest Document of the battle
   @return problems
   """
   from . import storage   # local: storage reads this module's egg keys
   out = []
   species = _species_names(doc)
   held = held_of(save)
   slots = slot_count(doc)
   if (held or result_of(save) is not None) and nursery(doc) is None:
      out.append("nursery records, but the structure states no nursery")
   seen: set[int] = set()
   for b in held:
      slot = b.get(SLOT_KEY)
      if not isinstance(slot, int) or not 0 <= slot < max(slots, 1) or slots == 0:
         out.append(f"nursery: slot {slot!r} (the nursery has {slots} slots)")
      elif slot in seen:
         out.append(f"nursery: slot {slot} twice")
      seen.add(slot if isinstance(slot, int) else -1)
      out += _check_entry(doc, b, f"nursery slot {slot}", species)
      gained = b.get(GAINED_KEY, 0)
      if not isinstance(gained, int) or isinstance(gained, bool) or not 0 <= gained <= MAX_GAINED:
         out.append(f"nursery slot {slot}: experience gained {gained!r}")
   result = result_of(save)
   if result is not None:
      out += _check_entry(doc, result, "nursery result", species)
   for b in storage.boxed_of(save):
      if HATCH_KEY in b:
         out += _check_entry(doc, {**b, LEVEL_KEY: b.get(storage.BOXED_LEVEL)},
                             f"boxes: slot {b.get(storage.BOXED_SLOT)}", species)
   return out


def record_bytes(compiled: Mapping[str, Any], species: str, level: int, hatch: int | None) -> bytes:
   """!One test record as engine bytes (tools/record_transfer.py pack(): the species and the level, an egg's role
   and counter through the engine's egg_record(); every other role its new-record value).
   @param compiled  compile_battle() result
   @param species   species name
   @param level     its level
   @param hatch     an egg's hatch counter, or None
   @return the bytes
   @throws DocumentError for a record the layout cannot hold
   """
   bc = _bc()
   table = bc.compile_transfer(compiled["layout"], compiled["stats"], WHERE)
   keys = {s["name"]: int(s["key"]) for s in compiled["species"]}
   try:
      values: JsonDict = {SPECIES_ROLE: keys[species], LEVEL_ROLE: int(level)}
      if hatch is not None:
         values = bc.egg_record(compiled, values, hatch)
      return bytes(engine.tool("record_transfer").pack(table, values))
   except (KeyError, ValueError, bc.ManifestError) as e:
      raise DocumentError(f"{species}: {e}") from None


def image_parts(save: Document, compiled: Mapping[str, Any]) -> tuple[dict[int, tuple[int, int, bytes]],
                                                                       bytes | None]:
   """!A test save's nursery as the engine's save_layout.image() takes it.
   @param save      test save Document
   @param compiled  compile_battle() result
   @return ({slot: (level when left, experience gained, record bytes)}, the waiting result's bytes or None)
   """
   slots = {int(b[SLOT_KEY]): (int(b[LEVEL_KEY]), int(b.get(GAINED_KEY, 0)),
                               record_bytes(compiled, b[SPECIES_KEY], b[LEVEL_KEY], b.get(HATCH_KEY)))
            for b in held_of(save)}
   r = result_of(save)
   result = record_bytes(compiled, r[SPECIES_KEY], r.get(LEVEL_KEY, 1), r.get(HATCH_KEY)) if r is not None else None
   return slots, result


def test_lines(save: Document) -> list[str]:
   """!A test save's nursery as text (CLI `testsave show`; none without one).
   @param save  test save Document
   @return lines
   """
   out = [f"nursery slot {b.get(SLOT_KEY)}: {b.get(SPECIES_KEY)} level {b.get(LEVEL_KEY)}, gained "
          f"{b.get(GAINED_KEY, 0)}" for b in held_of(save)]
   r = result_of(save)
   if r is not None:
      egg = f" (egg, {r[HATCH_KEY]} steps)" if HATCH_KEY in r else ""
      out.append(f"nursery result: {r.get(SPECIES_KEY)} level {r.get(LEVEL_KEY, 1)}{egg}")
   return out

