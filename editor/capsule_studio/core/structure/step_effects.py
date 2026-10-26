"""!The step effects of battle data (engine F3, D-27 section 4): the structure manifest's "step_effects".

    structure.json  "step_effects": [{"name": "blight", "label": "Blight", "every": 4, "damage": "survive",
                                      "messages": {"survived": "blight_survived"}},
                                     {"name": "bond", "label": "Bond", "every": 64}]

Every `every` steps of the walker the engine runs the effect-logic hook `steps` (written `on steps`) on each party
member: the game's global rules, then the member's status, its passive, its held item (`field.step_effect == NAME`
tells the effects apart). The logic is the rule (a poison-like status taking hit points through the member's hit
point resource, a friendship-like role growing, an egg-like counter running down, a field effect started); the
record says what the engine does around it: the damage rule for a member the run took to 0 hit points (faint, or
survive at 1), the battle messages queued for the moments hurt / survived / fainted ({user} = the member), and a
game script run after a run with an outcome (with the implicit variables step_effect_member / step_effect_outcome).
The script compiler counts each effect's steps in an implicit permanent u16 script variable (`step_effect_<name>`,
0 to every - 1: the save image's script section). The names, choices and checks are the engine's (battle_compiler
re-exports battlec/field.py: STEP_EFFECT_DAMAGE_RULES, STEP_EFFECT_DEFAULT_DAMAGE, STEP_EFFECT_MOMENTS,
STEP_EFFECT_OUTCOMES, MAX_STEP_EFFECTS, STEP_EFFECT_MAX_EVERY, compile_step_effects(), step_effect_var()).

Each editing helper is one change: call it inside one edit() of either manifest. A rename follows the effect logic
naming the effect (core.logic.references(): `field.step_effect == NAME`) and the game's `.cscript` sources reading its
implicit counter (core.scripts.follow_rename(), saved at once and undone with the edit); a removal is refused while
logic names it (B2: or the eggs' cycle or the nursery's check does; a rename follows into them). An edit that
stops data that compiled from compiling is refused with the engine's message.
step_handlers() lists the logic running the hook in the engine's order (the Step effects page, the CLI).
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict

from .. import battle, engine, logic
from ..document import Document, DocumentError

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure manifest's list of step effects.
EFFECTS_KEY = "step_effects"
## An effect's name.
NAME_KEY = "name"
## What menus and HUDs show.
LABEL_KEY = "label"
## Steps between two runs.
EVERY_KEY = "every"
## The damage rule.
DAMAGE_KEY = "damage"
## The messages by moment.
MESSAGES_KEY = "messages"
## The game script run after a run with an outcome.
SCRIPT_KEY = "script"
## The steps a new effect counts (what the page offers first).
DEFAULT_EVERY = 4
## The effect compiler's list effect logic names a step effect from.
LOGIC_LISTS = (EFFECTS_KEY,)
## Location the compiler's messages name.
WHERE = "structure"
## Undo label of the effect logic's part of a rename.
RENAME_LABEL = "Rename step effect"
## The hook the effects run (effect_compiler HOOKS; `on steps`).
HOOK = "steps"
## The order the engine runs a member's owners in (capsule/battle/step_effects.h), after the global rules.
MEMBER_ORDER = ("status", "passive", "item")
## The statement word scripts would name a step effect with (none: the scripts only read the implicit counter).
SCRIPT_WORD = ""


class EffectRow(TypedDict):
   """!One step effect as the page and the CLI show it."""
   ## Position in the list (its STEP_EFFECT_<NAME> id).
   index: int
   ## Its name.
   name: str
   ## What menus show (the name when it states none).
   label: str
   ## Steps between two runs.
   every: int
   ## faint or survive.
   damage: str
   ## {moment: message key} (moments without one left out).
   messages: dict[str, str]
   ## The game script run after a run with an outcome, or "".
   script: str
   ## Its implicit counter variable.
   var: str
   ## The effect logic naming it ("effects/conditions.ceffect: status Blight").
   users: list[str]


class HandlerUse(NamedTuple):
   """!One owner's `on steps` handler."""
   ## Owner kind (global, status, passive, item).
   kind: str
   ## Owner name.
   name: str
   ## The source it is in.
   file: str


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def damage_rules() -> list[str]:
   """!The damage rules (the engine's STEP_EFFECT_DAMAGE_RULES, in capsule::script::StepDamage order).
   @return names
   """
   return list(_bc().STEP_EFFECT_DAMAGE_RULES)


def default_damage() -> str:
   """!The damage rule of an effect that states none (the engine's STEP_EFFECT_DEFAULT_DAMAGE).
   @return the name
   """
   return str(_bc().STEP_EFFECT_DEFAULT_DAMAGE)


def moments() -> list[str]:
   """!The moments an effect's messages name (the engine's STEP_EFFECT_MOMENTS).
   @return names
   """
   return list(_bc().STEP_EFFECT_MOMENTS)


def outcomes() -> list[str]:
   """!A member's outcomes of a run (the engine's STEP_EFFECT_OUTCOMES: the outcome variable's values).
   @return names
   """
   return list(_bc().STEP_EFFECT_OUTCOMES)


def max_effects() -> int:
   """!The most step effects (the engine's MAX_STEP_EFFECTS).
   @return it
   """
   return int(_bc().MAX_STEP_EFFECTS)


def max_every() -> int:
   """!The most steps between two runs (the engine's STEP_EFFECT_MAX_EVERY: the counter's u16 variable).
   @return it
   """
   return int(_bc().STEP_EFFECT_MAX_EVERY)


def max_label() -> int:
   """!The longest label (the engine's FIELD_EFFECT_MAX_LABEL: the field rules share it).
   @return letters
   """
   return int(_bc().FIELD_EFFECT_MAX_LABEL)


def implicit_vars() -> tuple[str, str]:
   """!The implicit variables an effect's script reads (the engine's STEP_EFFECT_MEMBER_VAR / _OUTCOME_VAR).
   @return (member variable, outcome variable)
   """
   bc = _bc()
   return str(bc.STEP_EFFECT_MEMBER_VAR), str(bc.STEP_EFFECT_OUTCOME_VAR)


def effects(doc: Document | None) -> list[JsonDict]:
   """!The records in order (live).
   @param doc  any manifest Document of the battle, or None
   @return record dicts (entries that are not objects with a name are left out)
   """
   if doc is None:
      return []
   given = battle.data_of(doc, EFFECTS_KEY).get(EFFECTS_KEY)
   return [e for e in given if isinstance(e, dict) and isinstance(e.get(NAME_KEY), str)] \
      if isinstance(given, list) else []


def effect_names(doc: Document | None) -> list[str]:
   """!The record names in order.
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   return [e[NAME_KEY] for e in effects(doc)]


def users(doc: Document, name: str) -> list[str]:
   """!The effect logic owners naming a record.
   @param doc   any manifest Document of the battle
   @param name  record name
   @return "FILE: KIND NAME" strings
   """
   return logic.per_owner(logic.references(doc, LOGIC_LISTS, name))


def message_uses(doc: Document, key: str, new: str | None = None) -> list[str]:
   """!Finds (and renames) a battle message the step effects show (C8; core.messages: its uses, renames and the
   refused removal).
   @param doc  any manifest Document of the battle (changes happen in the edit running on it)
   @param key  the message
   @param new  new key, or None to only look
   @return "where" strings ("step_effects NAME: messages.MOMENT")
   """
   found = []
   for e in effects(doc):
      msgs = e.get(MESSAGES_KEY)
      for moment, value in list(msgs.items()) if isinstance(msgs, dict) else []:
         if value == key:
            found.append(f"{EFFECTS_KEY} {e.get(NAME_KEY)}: {MESSAGES_KEY}.{moment}")
            if new is not None:
               msgs[moment] = new
   return found


def message_choices(doc: Document) -> list[str]:
   """!The battle's messages a moment may name (the engine's declared_messages(): its engine messages and its own).
   @param doc  any manifest Document of the battle
   @return message keys
   """
   bc = _bc()
   view = battle.data_of(doc, "messages")
   messages = view.get("messages")
   return [m for m in bc.declared_messages(messages if isinstance(messages, dict) else {}) if m is not None]


def script_choices(doc: Document) -> list[str]:
   """!The game's scripts an effect may run (its scripts manifest; none outside a game).
   @param doc  any manifest Document of the battle
   @return script names
   """
   from . import field_actions   # local: field_actions holds the game's file lookups
   return field_actions.script_names(doc)["script"]


def effect_rows(doc: Document) -> list[EffectRow]:
   """!The records with their defaults filled in, their implicit counters and their users.
   @param doc  any manifest Document of the battle
   @return one row per record
   """
   bc = _bc()
   out = []
   for i, e in enumerate(effects(doc)):
      name = e[NAME_KEY]
      msgs = e.get(MESSAGES_KEY)
      every = e.get(EVERY_KEY)
      script = e.get(SCRIPT_KEY)
      out.append(EffectRow(index=i, name=name, label=str(e.get(LABEL_KEY, name)),
                           every=every if isinstance(every, int) and not isinstance(every, bool) else 0,
                           damage=str(e.get(DAMAGE_KEY, default_damage())),
                           messages={k: v for k, v in msgs.items() if isinstance(v, str)}
                           if isinstance(msgs, dict) else {},
                           script=script if isinstance(script, str) else "", var=bc.step_effect_var(name),
                           users=users(doc, name)))
   return out


def compile_check(doc: Document) -> tuple[list[JsonDict] | None, str | None]:
   """!Compiles the records with the engine's compile_step_effects() (against the battle's messages).
   @param doc  any manifest Document of the battle
   @return (compiled records or None, the compiler's message or None)
   """
   bc = _bc()
   try:
      given = bc.strip(copy.deepcopy(battle.data_of(doc, EFFECTS_KEY).get(EFFECTS_KEY)))
      messages = battle.data_of(doc, "messages").get("messages")
      declared = bc.declared_messages(messages if isinstance(messages, dict) else {})
      return bc.compile_step_effects(given, declared, WHERE), None
   except Exception as e:   # ManifestError, type errors in odd data
      return None, str(e)


def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the records (or the whole battle data) compiled
   before and do not after.
   @param doc     any manifest Document of the battle
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   project = logic.project_of(doc)
   _compiled, before = compile_check(doc)
   whole_before = project.error_now() if project is not None else None
   result = change()
   _compiled, error = compile_check(doc)
   if before is None and error is not None:
      raise DocumentError(error)
   if whole_before is None and project is not None:
      error = project.error_now()
      if error is not None:
         raise DocumentError(error)
   return result


def _live(doc: Document) -> list[JsonDict]:
   """!The record list for editing (written when the structure states none).
   @param doc  any manifest Document of the battle
   @return the live list
   """
   data = battle.data_of(doc, EFFECTS_KEY)
   if not isinstance(data.get(EFFECTS_KEY), list):
      data[EFFECTS_KEY] = []
   return data[EFFECTS_KEY]


def _effect(doc: Document, name: str) -> JsonDict:
   """!One record (live).
   @param doc   any manifest Document of the battle
   @param name  record name
   @return the dict
   @throws DocumentError when there is no such record
   """
   for e in effects(doc):
      if e[NAME_KEY] == name:
         return e
   raise DocumentError(f"no step effect {name!r} (step effects: {', '.join(effect_names(doc)) or 'none'})")


def _check_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A record name: not empty, no other record's (the engine checks its form: a lower-case identifier).
   @param doc      any manifest Document of the battle
   @param name     the wanted name
   @param current  the name being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   name = name.strip() if isinstance(name, str) else name
   if not isinstance(name, str) or not name:
      raise DocumentError("a step effect needs a name")
   if name != current and name in effect_names(doc):
      raise DocumentError(f"there is already a step effect {name!r}")
   return name


def _check_every(every: Any) -> int:
   """!Steps between two runs.
   @param every  the wanted value
   @return it
   @throws DocumentError out of 1 to max_every()
   """
   if not isinstance(every, int) or isinstance(every, bool) or not 1 <= every <= max_every():
      raise DocumentError(f"every: 1 to {max_every()} steps (got {every!r})")
   return every


def add_effect(doc: Document, name: str, every: int = DEFAULT_EVERY, at: int | None = None) -> None:
   """!Adds a record (the engine's defaults: the faint rule, no messages, no script).
   @param doc    any manifest Document of the battle
   @param name   its name
   @param every  steps between two runs
   @param at     its position (None: last)
   @return None
   """
   name = _check_name(doc, name)
   every = _check_every(every)
   if len(effects(doc)) >= max_effects():
      raise DocumentError(f"at most {max_effects()} step effects")

   def change() -> None:
      """!Inserts it."""
      live = _live(doc)
      live.insert(len(live) if at is None else max(0, min(at, len(live))), {NAME_KEY: name, EVERY_KEY: every})
   _guarded(doc, change)


def remove_effect(doc: Document, name: str) -> None:
   """!Removes a record (refused while effect logic names it).
   @param doc   any manifest Document of the battle
   @param name  record name
   @return None
   """
   _effect(doc, name)
   from . import nursery   # local: it imports this module
   named = users(doc, name) + nursery.uses(doc, "step_effect", name)   # B2: the egg cycle, the nursery check
   if named:
      raise DocumentError(f"step effect {name!r} is used by {', '.join(named)}")
   _guarded(doc, lambda: _live(doc).remove(_effect(doc, name)))


def rename_effect(doc: Document, old: str, new: str, follow: bool = True) -> list[str]:
   """!Renames a record; the effect logic naming it follows, and the game's scripts reading its implicit counter.
   @param doc     any manifest Document of the battle
   @param old     its name
   @param new     the new name
   @param follow  False to leave the game's scripts to follow_scripts() (C8: the CLI follows them only once the
                  renamed battle data compiled and was saved)
   @return the places rewritten (logic, then "scripts: ..." ones)
   """
   new = _check_name(doc, new, old)
   e = _effect(doc, old)

   def change() -> list[str]:
      """!Renames it and its users."""
      e[NAME_KEY] = new
      from . import nursery   # local: it imports this module
      followed = nursery.follow_step_effect(battle.merged(doc), old, new)   # B2: the egg cycle, the nursery check
      return logic.references(doc, LOGIC_LISTS, old, new, RENAME_LABEL) + [f"structure: {f}" for f in followed]
   places = _guarded(doc, change)
   return places + (follow_scripts(doc, old, new) if follow else [])


def follow_scripts(doc: Document, old: str, new: str) -> list[str]:
   """!The game's scripts follow a rename (its implicit counter; saved at once, undone with the edit group).
   @param doc  any manifest Document of the battle
   @param old  the old name
   @param new  the new name
   @return "scripts: ..." places
   """
   from .. import scripts
   bc = _bc()
   project = logic.project_of(doc)
   manifest = project.scripts_manifest() if project is not None else None
   follow = scripts.follow_rename(manifest, SCRIPT_WORD, [], old, new,
                                  [(bc.step_effect_var(old), bc.step_effect_var(new))])
   return [f"scripts: {place}" for place in follow]


def move_effect(doc: Document, name: str, delta: int) -> None:
   """!Moves a record up or down (the STEP_EFFECT_<NAME> ids follow the order).
   @param doc    any manifest Document of the battle
   @param name   record name
   @param delta  -1 up, +1 down
   @return None
   """
   names = effect_names(doc)
   if name not in names:
      raise DocumentError(f"no step effect {name!r}")
   i = names.index(name)
   j = i + delta
   if not 0 <= j < len(names):
      return

   def change() -> None:
      """!Swaps it with its neighbour."""
      live = _live(doc)
      live[i], live[j] = live[j], live[i]
   _guarded(doc, change)


def _set_key(doc: Document, name: str, key: str, value: Any, default: Any) -> None:
   """!Writes one key of a record (its default value: the key goes).
   @param doc      any manifest Document of the battle
   @param name     record name
   @param key      the key
   @param value    the value
   @param default  the value the engine takes when the key is left out
   @return None
   """
   e = _effect(doc, name)

   def change() -> None:
      """!Writes it."""
      if value == default:
         e.pop(key, None)
      else:
         e[key] = value
   _guarded(doc, change)


def set_label(doc: Document, name: str, label: str) -> None:
   """!Sets what menus show (the name, or empty: the key goes).
   @param doc    any manifest Document of the battle
   @param name   record name
   @param label  1 to max_label() letters
   @return None
   """
   label = label.strip() if isinstance(label, str) else label
   if not isinstance(label, str) or len(label) > max_label():
      raise DocumentError(f"a label is at most {max_label()} letters")
   _set_key(doc, name, LABEL_KEY, label or name, name)


def set_every(doc: Document, name: str, every: int) -> None:
   """!Sets the steps between two runs (a new range of the implicit counter: record the save shapes).
   @param doc    any manifest Document of the battle
   @param name   record name
   @param every  1 to max_every()
   @return None
   """
   # every has no default: it is always written
   _set_key(doc, name, EVERY_KEY, _check_every(every), None)


def set_damage(doc: Document, name: str, damage: str) -> None:
   """!Sets what a member the run took to 0 hit points does.
   @param doc     any manifest Document of the battle
   @param name    record name
   @param damage  one of damage_rules()
   @return None
   """
   if damage not in damage_rules():
      raise DocumentError(f"damage: one of {', '.join(damage_rules())} (got {damage!r})")
   _set_key(doc, name, DAMAGE_KEY, damage, default_damage())


def set_message(doc: Document, name: str, moment: str, message: str | None) -> None:
   """!Sets the battle message queued at one moment (None or empty: none; the messages key goes when none is left).
   @param doc      any manifest Document of the battle
   @param name     record name
   @param moment   one of moments()
   @param message  one of message_choices(), or None
   @return None
   """
   if moment not in moments():
      raise DocumentError(f"moment: one of {', '.join(moments())} (got {moment!r})")
   message = message or None
   if message is not None and message not in message_choices(doc):
      raise DocumentError(f"{message!r} is not one of the battle's messages")
   e = _effect(doc, name)

   def change() -> None:
      """!Writes it."""
      msgs = e.get(MESSAGES_KEY) if isinstance(e.get(MESSAGES_KEY), dict) else {}
      if message is None:
         msgs.pop(moment, None)
      else:
         msgs[moment] = message
      if msgs:
         # the engine's moment order, whatever order they were set in
         e[MESSAGES_KEY] = {m: msgs[m] for m in moments() if m in msgs}
      else:
         e.pop(MESSAGES_KEY, None)
   _guarded(doc, change)


def set_script(doc: Document, name: str, script: str | None) -> None:
   """!Sets the game script run after a run with an outcome (None or empty: none). The script compiler checks that
   the game declares it.
   @param doc     any manifest Document of the battle
   @param name    record name
   @param script  a script name, or None
   @return None
   """
   script = script.strip() if isinstance(script, str) else script
   _set_key(doc, name, SCRIPT_KEY, script or None, None)


def step_handlers(project: BattleProject) -> list[HandlerUse]:
   """!The logic running the steps hook, in the engine's order for a member: the global rules, then statuses,
   passives and held items (capsule/battle/step_effects.h).
   @param project  BattleProject
   @return rows, file order within a kind
   """
   out = []
   for row in logic.owners(project):
      ref = f"{row.kind}{logic.OWNER_SEPARATOR}{row.name}"
      if any(h.member == "on" and h.name == HOOK for h in logic.handlers(project, ref)):
         out.append(HandlerUse(row.kind, row.name, row.file))
   order = (logic.global_kind(), *MEMBER_ORDER)
   return sorted(out, key=lambda u: order.index(u.kind) if u.kind in order else len(order))


def lines(doc: Document) -> list[str]:
   """!The records as text (the CLI's `step-effect list`).
   @param doc  any manifest Document of the battle
   @return one line per record
   """
   out = []
   for r in effect_rows(doc):
      msgs = ", ".join(f"{m} {k}" for m, k in r["messages"].items()) or "no messages"
      out.append(f"{r['name']} ({r['label']}): every {r['every']} steps, {r['damage']}; {msgs}; script "
                 f"{r['script'] or 'none'}; counter {r['var']}; used by {', '.join(r['users']) or 'nobody'}")
   return out


# -- test saves: the counters ------------------------------------------------------------------------------------------

## A test save's key of the step effects' counters ({name: steps counted}).
TESTSAVE_COUNTERS = "step_counters"


def counters_of(save: Document) -> dict[str, int]:
   """!A test save's step effect counters.
   @param save  test save Document
   @return {effect name: steps counted} (copies; entries that are not counts left out)
   """
   given = save.data.get(TESTSAVE_COUNTERS)
   return {str(k): v for k, v in (given.items() if isinstance(given, dict) else [])
           if isinstance(v, int) and not isinstance(v, bool)}


def counter_rows(save: Document, doc: Document) -> list[tuple[str, int, int]]:
   """!Every step effect with the test save's counter (0 when it states none).
   @param save  test save Document
   @param doc   any manifest Document of the battle
   @return [(name, steps counted, every)]
   """
   given = counters_of(save)
   return [(r["name"], given.get(r["name"], 0), r["every"]) for r in effect_rows(doc)]


def set_counter(save: Document, doc: Document, name: str, steps: int) -> None:
   """!Sets a test save's counter of a step effect (inside save.edit(); 0: the entry goes).
   @param save   test save Document
   @param doc    any manifest Document of the battle
   @param name   one of effect_names()
   @param steps  0 to every - 1
   @return None
   @throws DocumentError for an unknown effect or a count out of range
   """
   row = next((r for r in effect_rows(doc) if r["name"] == name), None)
   if row is None:
      raise DocumentError(f"no step effect {name!r} (step effects: {', '.join(effect_names(doc)) or 'none'})")
   if not isinstance(steps, int) or isinstance(steps, bool) or not 0 <= steps < max(row["every"], 1):
      raise DocumentError(f"{name} counts 0 to {max(row['every'], 1) - 1} steps (got {steps!r})")
   counters = save.data.get(TESTSAVE_COUNTERS) if isinstance(save.data.get(TESTSAVE_COUNTERS), dict) else {}
   if steps == 0:
      counters.pop(name, None)
   else:
      counters[name] = steps
   if counters:
      save.data[TESTSAVE_COUNTERS] = counters
   else:
      save.data.pop(TESTSAVE_COUNTERS, None)


def check_counters(save: Document, doc: Document) -> list[str]:
   """!What the battle data refuses in a test save's counters.
   @param save  test save Document
   @param doc   any manifest Document of the battle
   @return problems
   """
   rows = {r["name"]: r for r in effect_rows(doc)}
   out = []
   for name, steps in counters_of(save).items():
      if name not in rows:
         out.append(f"step counter of an unknown step effect {name!r}")
      elif not 0 <= steps < max(rows[name]["every"], 1):
         out.append(f"step counter {name}: {steps} (0-{max(rows[name]['every'], 1) - 1})")
   return out


def counter_values(save: Document) -> dict[str, int]:
   """!A test save's counters as the script variables the image writes (the engine's save_layout.image() values).
   @param save  test save Document
   @return {implicit variable: steps counted}
   """
   bc = _bc()
   return {bc.step_effect_var(name): steps for name, steps in counters_of(save).items()}


def counter_lines(save: Document, doc: Document) -> list[str]:
   """!A test save's counters as text (CLI `testsave show`; none without step effects).
   @param save  test save Document
   @param doc   any manifest Document of the battle
   @return lines
   """
   return [f"step {name}: {steps} of {every} steps" for name, steps, every in counter_rows(save, doc)]
