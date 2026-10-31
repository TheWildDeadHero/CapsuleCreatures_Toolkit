"""!Recruitment (D-26 section 3, engine G3): the structure manifest's
"recruit" section, the ruleset pipeline recruit_odds and the items whose
use_battle logic recruits.

    "recruit": {"checks": 3, "rate": "recruit_rate", "status_bonus": {"none": 0, "Doze": 25},
                "owned": "refuse", "keep": ["hp", "status"], "item_role": "ball",
                "messages": {"check": "orb_wobble", "recruited": "orb_caught"}, "break_free": ["orb_free"]}

An item's use_battle logic calls `recruit WHO BONUS;`; the engine makes
"checks" draws, each against recruit_odds (inputs: the target's HP, the
species field "rate" as recruit_rate, the logic's bonus, the status bonus
of the target's primary status, the levels, the turn; outputs: sure, or
chance in out_of), with an event (and the message of "messages") per check
that passes; every check passed recruits (the record joins the party, else
the storage boxes, Structure > Storage). An owned battler is refused unless
"owned" is "allow"; "keep" names the battle changes the record keeps;
"item_role" a record role that stores the item used; "break_free" the
messages of a failed recruit by the checks it passed.

The engine's tools/battlec/recruit.py is the one authority (re-exported by
battle_compiler): the moments, keeps and owned choices, the caps, every
check (compile_recruit(), through the whole battle compile). A section
needs the ruleset's own recruit_odds pipeline (add_pipeline() writes a
neutral one).

Each editing helper is one change: call it inside one edit() of either
manifest and Undo takes the whole change back. An edit that stops data that
compiled from compiling is refused with the engine's message. Renames of a
status, a species field or a message follow into the section
(follow_status_rename(), follow_field_rename(), message_uses()).
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypedDict

from .. import battle, engine, logic
from ..document import Document, DocumentError

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure manifest's recruit section.
RECRUIT_KEY = "recruit"
## Checks a recruit makes.
CHECKS_KEY = "checks"
## The species field read as recruit_rate.
RATE_KEY = "rate"
## The status bonuses ({"none": n, STATUS: n}).
STATUS_BONUS_KEY = "status_bonus"
## Whether an owned battler may be recruited.
OWNED_KEY = "owned"
## The battle changes the record keeps.
KEEP_KEY = "keep"
## Section key: the refusals that still use the item up (engine C6, RECRUIT_REFUSALS).
REFUSAL_CONSUMES_KEY = "refusal_consumes"
## The record role storing the item used.
ITEM_ROLE_KEY = "item_role"
## A message per moment.
MESSAGES_KEY = "messages"
## The "broke free" messages by checks passed.
BREAK_FREE_KEY = "break_free"
## The fields set_field() sets.
FIELDS = (CHECKS_KEY, RATE_KEY, OWNED_KEY, ITEM_ROLE_KEY)
## The structure's status records.
STATUSES_KEY = "statuses"
## The ruleset's pipelines.
PIPELINES_KEY = "pipelines"
## Checks of a new section.
NEW_CHECKS = 3
## The odds of the neutral pipeline add_pipeline() writes are percent.
NEUTRAL_OUT_OF = 100
## The neutral recruit_odds: rate + item bonus + status bonus percent per check (clamped), sure from a bonus of 100.
NEUTRAL_PIPELINE = [
   {"let": "chance", "expr": f"clamp(recruit_rate + bonus + status_bonus, 0, {NEUTRAL_OUT_OF})"},
   {"let": "out_of", "expr": str(NEUTRAL_OUT_OF)},
   {"let": "sure", "expr": f"bonus >= {NEUTRAL_OUT_OF}"},
]
## The battler a recruit item's logic recruits (the item's holder: the battler it is used on).
RECRUIT_WHO = "holder"
## The effect primitive.
PRIMITIVE = "recruit"
## The words of a call: the primitive, its battler, its bonus.
CALL_WORDS = 3
## The key of a parsed statement's kind (core.logic.parse_statement()).
STATEMENT_KEY = "stmt"
## The use hook a recruit runs in.
USE_HOOK = "use_battle"
## The use an item that recruits needs (at least battle use; "both" keeps its field use).
BATTLE_USE = "battle"
## The target an item that recruits needs.
BATTLER_TARGET = "battler"
## Undo label of a rename's follow-ups.
RENAME_LABEL = "Rename"
## A percentage.
PERCENT = 100
## The recruit_odds input of the status bonus (a preview without one takes the "none" bonus).
STATUS_INPUT = "status_bonus"
## Inputs of an odds preview when the caller gives none (a healthy level 10 target, turn 1).
PREVIEW_DEFAULTS = {"target_hp": 1, "target_max_hp": 1, "recruit_rate": 0, "bonus": 0, "status_bonus": 0,
                    "target_level": 10, "user_level": 10, "turn": 1}


class OddsRow(TypedDict):
   """!The odds of a recruit as the page and the CLI show them."""
   ## Every check passes without a draw.
   sure: bool
   ## The odds of one check: chance in out_of.
   chance: int
   ## The draw's span.
   out_of: int
   ## Checks the section makes.
   checks: int
   ## One check passing, percent.
   per_check: float
   ## Every check passing, percent.
   all_checks: float


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


# -- the engine's lists -----------------------------------------------------------------------------------------------

def moments() -> list[str]:
   """!The moments "messages" names a message for (the engine's RECRUIT_MESSAGE_MOMENTS).
   @return names
   """
   return list(_bc().RECRUIT_MESSAGE_MOMENTS)


def keeps() -> list[str]:
   """!The battle changes a record may keep (the engine's RECRUIT_KEEPS).
   @return names, in capsule::battle::RecruitKeep order
   """
   return list(_bc().RECRUIT_KEEPS)


def refusals() -> list[str]:
   """!The refusals "refusal_consumes" may name (the engine's RECRUIT_REFUSALS; C6).
   @return names
   """
   return list(_bc().RECRUIT_REFUSALS)


def owned_choices() -> list[str]:
   """!The choices of "owned" (the engine's RECRUIT_OWNED).
   @return names
   """
   return list(_bc().RECRUIT_OWNED)


def default_owned() -> str:
   """!"owned" when the section states none.
   @return the engine's RECRUIT_DEFAULT_OWNED
   """
   return str(_bc().RECRUIT_DEFAULT_OWNED)


def no_status() -> str:
   """!The status_bonus key of a battler without a primary status.
   @return the engine's RECRUIT_NO_STATUS
   """
   return str(_bc().RECRUIT_NO_STATUS)


def max_checks() -> int:
   """!Most checks (capsule::battle::kMaxRecruitChecks).
   @return the engine's RECRUIT_MAX_CHECKS
   """
   return int(_bc().RECRUIT_MAX_CHECKS)


def max_break_free() -> int:
   """!Most "broke free" messages.
   @return the engine's RECRUIT_MAX_BREAK_FREE
   """
   return int(_bc().RECRUIT_MAX_BREAK_FREE)


def max_status_bonus() -> int:
   """!Highest status bonus.
   @return the engine's RECRUIT_MAX_STATUS_BONUS
   """
   return int(_bc().RECRUIT_MAX_STATUS_BONUS)


def max_bonus() -> int:
   """!Highest item bonus a `recruit` passes the pipeline.
   @return the engine's RECRUIT_MAX_BONUS
   """
   return int(_bc().RECRUIT_MAX_BONUS)


def pipeline_name() -> str:
   """!The pipeline the checks draw against.
   @return the engine's RECRUIT_PIPELINE
   """
   return str(_bc().RECRUIT_PIPELINE)


def pipeline_inputs() -> list[str]:
   """!The recruit_odds inputs (ruleset_compiler PIPELINES).
   @return names
   """
   return list(engine.tool("ruleset_compiler").PIPELINES[pipeline_name()]["inputs"])


# -- reading ----------------------------------------------------------------------------------------------------------

def is_stated(doc: Document) -> bool:
   """!Whether the structure states recruitment (else no item can recruit: the primitive fails).
   @param doc  any manifest Document of the battle
   @return True when "recruit" is given
   """
   return isinstance(battle.data_of(doc, RECRUIT_KEY).get(RECRUIT_KEY), dict)


def given(doc: Document) -> JsonDict:
   """!The section as given.
   @param doc  any manifest Document of the battle
   @return the dict ({} when not stated)
   """
   given = battle.data_of(doc, RECRUIT_KEY).get(RECRUIT_KEY)
   return given if isinstance(given, dict) else {}


def status_names(doc: Document) -> list[str]:
   """!The primary statuses (the structure's status records), the choices of a status bonus besides "none".
   @param doc  any manifest Document of the battle
   @return names
   """
   given = battle.data_of(doc, STATUSES_KEY).get(STATUSES_KEY)
   return [str(s["name"]) for s in (given if isinstance(given, list) else [])
           if isinstance(s, dict) and isinstance(s.get("name"), str)]


def rate_choices(doc: Document) -> list[str]:
   """!The species fields a recruit rate may be (Structure > Species fields).
   @param doc  any manifest Document of the battle
   @return names
   """
   from . import species_fields   # local: core.structure.species_fields imports this module
   return species_fields.field_names(doc)


def role_choices(doc: Document) -> list[str]:
   """!The record roles the layout holds (an item role must hold every item id: the compile checks).
   @param doc  any manifest Document of the battle
   @return names
   """
   from . import record   # local: as rate_choices()
   return record.role_names(doc)


def message_choices(doc: Document) -> list[str]:
   """!The battle's messages a moment may say (Content > Messages: the engine's the data gives and its own).
   @param doc  any manifest Document of the battle
   @return keys
   """
   from .. import messages   # local: core.messages imports this module
   return list(messages.given(doc))


def section(doc: Document) -> JsonDict:
   """!The section with the engine's defaults filled in.
   @param doc  any manifest Document of the battle
   @return {"checks", "rate", "status_bonus" (every status: its bonus), "owned", "keep", "item_role",
           "messages" (every moment: a key or None), "refusal_consumes", "break_free"} (copies; checks 0 when not
           stated)
   """
   g = given(doc)
   bonus_src = g.get(STATUS_BONUS_KEY) if isinstance(g.get(STATUS_BONUS_KEY), dict) else {}
   none = bonus_src.get(no_status(), _bc().RECRUIT_DEFAULT_STATUS_BONUS)
   bonus = {no_status(): none}
   bonus.update({n: bonus_src.get(n, none) for n in status_names(doc)})
   msgs = g.get(MESSAGES_KEY) if isinstance(g.get(MESSAGES_KEY), dict) else {}
   free = g.get(BREAK_FREE_KEY, [])
   return {CHECKS_KEY: g.get(CHECKS_KEY, 0), RATE_KEY: g.get(RATE_KEY), STATUS_BONUS_KEY: bonus,
           OWNED_KEY: g.get(OWNED_KEY, default_owned()), KEEP_KEY: list(g.get(KEEP_KEY, keeps())),
           ITEM_ROLE_KEY: g.get(ITEM_ROLE_KEY), MESSAGES_KEY: {m: msgs.get(m) for m in moments()},
           REFUSAL_CONSUMES_KEY: list(g.get(REFUSAL_CONSUMES_KEY, [])),
           BREAK_FREE_KEY: [free] if isinstance(free, str) else list(free)}


def has_pipeline(project: BattleProject) -> bool:
   """!Whether the ruleset lists its own recruit_odds (a recruit section needs it).
   @param project  BattleProject
   @return True when listed
   """
   given = project.ruleset.data.get(PIPELINES_KEY)
   return isinstance(given, dict) and pipeline_name() in given


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
   given = battle.data_of(doc, RECRUIT_KEY).get(RECRUIT_KEY)
   if not isinstance(given, dict):
      raise DocumentError("the structure states no recruitment: enable it first")
   return given


def enable(doc: Document, checks: int = NEW_CHECKS) -> None:
   """!Gives the structure a recruit section (checks only: every other rule the engine's default).
   @param doc     any manifest Document of the battle
   @param checks  its checks
   @return None
   @throws DocumentError when it has one, or the ruleset lists no recruit_odds (add_pipeline() first)
   """
   if is_stated(doc):
      raise DocumentError("the structure states recruitment already")
   project = logic.project_of(doc)
   if project is not None and not has_pipeline(project):
      raise DocumentError(f"the checks draw against the ruleset's {pipeline_name()} pipeline: add it first "
                          "(Logic > Pipelines, or the page's Add pipeline)")
   _guarded(doc, lambda: battle.data_of(doc, RECRUIT_KEY).update({RECRUIT_KEY: {CHECKS_KEY: checks}}))


def disable(doc: Document) -> None:
   """!Takes the section out (items' `recruit` logic then fails: the engine's default has no checks).
   @param doc  any manifest Document of the battle
   @return None
   """
   _live(doc)
   _guarded(doc, lambda: battle.data_of(doc, RECRUIT_KEY).pop(RECRUIT_KEY))


def _name_or_none(value: Any, choices: Sequence[str], field: str) -> str | None:
   """!A choice, or None.
   @param value    the value
   @param choices  what it may be
   @param field    field name (messages)
   @return it
   @throws DocumentError when it is neither
   """
   if value is None or value == "":
      return None
   if value not in choices:
      raise DocumentError(f"{field}: one of {', '.join(choices) or 'none'}, or none (got {value!r})")
   return str(value)


def set_field(doc: Document, field: str, value: Any) -> None:
   """!Sets checks, rate, owned or item_role (None takes rate / item_role out; a default owned is left out).
   @param doc    any manifest Document of the battle
   @param field  one of FIELDS
   @param value  the value
   @return None
   @throws DocumentError for an unknown field or a value the engine refuses
   """
   if field not in FIELDS:
      raise DocumentError(f"a recruit field is one of {', '.join(FIELDS)} (got {field!r})")
   if field == CHECKS_KEY:
      try:
         value = int(value)
      except (TypeError, ValueError):
         raise DocumentError(f"checks: a whole number 1-{max_checks()} (got {value!r})") from None
      if not 1 <= value <= max_checks():
         raise DocumentError(f"checks: 1-{max_checks()} (got {value})")
   elif field == RATE_KEY:
      value = _name_or_none(value, rate_choices(doc), field)
   elif field == ITEM_ROLE_KEY:
      value = _name_or_none(value, role_choices(doc), field)
   elif value not in owned_choices():
      raise DocumentError(f"owned: one of {', '.join(owned_choices())} (got {value!r})")
   live = _live(doc)

   def change() -> None:
      """!Writes the field.
      @return None
      """
      if value is None or (field == OWNED_KEY and value == default_owned()):
         live.pop(field, None)
      else:
         live[field] = value

   _guarded(doc, change)


def set_status_bonus(doc: Document, status: str, value: int | None) -> None:
   """!Sets a status's bonus (None: a status takes the "none" value; "none" itself the engine's default).
   @param doc     any manifest Document of the battle
   @param status  a status name or no_status()
   @param value   0 to max_status_bonus(), or None
   @return None
   """
   if status != no_status() and status not in status_names(doc):
      raise DocumentError(f"no status {status!r} (statuses: {', '.join(status_names(doc)) or 'none'})")
   if value is not None and (not isinstance(value, int) or isinstance(value, bool) or
                             not 0 <= value <= max_status_bonus()):
      raise DocumentError(f"a status bonus is 0-{max_status_bonus()} (got {value!r})")
   live = _live(doc)

   def change() -> None:
      """!Writes the bonus (an empty object goes).
      @return None
      """
      bonus = live.get(STATUS_BONUS_KEY) if isinstance(live.get(STATUS_BONUS_KEY), dict) else {}
      if value is None:
         bonus.pop(status, None)
      else:
         bonus[status] = value
      if bonus:
         live[STATUS_BONUS_KEY] = bonus
      else:
         live.pop(STATUS_BONUS_KEY, None)

   _guarded(doc, change)


def set_keep(doc: Document, kept: Sequence[str]) -> None:
   """!Sets the battle changes the record keeps (every one: the key goes, the engine's default).
   @param doc   any manifest Document of the battle
   @param kept  names of keeps(), each once
   @return None
   """
   kept = list(kept)
   if any(k not in keeps() for k in kept) or len(set(kept)) != len(kept):
      raise DocumentError(f"keep: a list of {', '.join(keeps())} (each once; got {kept!r})")
   ordered = [k for k in keeps() if k in kept]
   live = _live(doc)

   def change() -> None:
      """!Writes the list.
      @return None
      """
      if ordered == keeps():
         live.pop(KEEP_KEY, None)
      else:
         live[KEEP_KEY] = ordered

   _guarded(doc, change)


def set_refusal_consumes(doc: Document, refused: Sequence[str]) -> None:
   """!Sets the refusals that still use the item up (C6, review4 finding 11; none: the key goes).
   @param doc      any manifest Document of the battle
   @param refused  names of refusals(), each once
   @return None
   """
   refused = list(refused)
   if any(k not in refusals() for k in refused) or len(set(refused)) != len(refused):
      raise DocumentError(f"refusal_consumes: a list of {', '.join(refusals())} (each once; got {refused!r})")
   ordered = [k for k in refusals() if k in refused]
   live = _live(doc)

   def change() -> None:
      """!Writes the list.
      @return None
      """
      if ordered:
         live[REFUSAL_CONSUMES_KEY] = ordered
      else:
         live.pop(REFUSAL_CONSUMES_KEY, None)

   _guarded(doc, change)


def set_message(doc: Document, moment: str, key: str | None) -> None:
   """!Sets the message a moment says (None: no text at that moment).
   @param doc     any manifest Document of the battle
   @param moment  one of moments()
   @param key     a message of the battle, or None
   @return None
   """
   if moment not in moments():
      raise DocumentError(f"a recruit moment is one of {', '.join(moments())} (got {moment!r})")
   key = _name_or_none(key, message_choices(doc), f"messages.{moment}")
   live = _live(doc)

   def change() -> None:
      """!Writes the message (an empty object goes).
      @return None
      """
      msgs = live.get(MESSAGES_KEY) if isinstance(live.get(MESSAGES_KEY), dict) else {}
      if key is None:
         msgs.pop(moment, None)
      else:
         msgs[moment] = key
      if msgs:
         live[MESSAGES_KEY] = msgs
      else:
         live.pop(MESSAGES_KEY, None)

   _guarded(doc, change)


def set_break_free(doc: Document, keys: Sequence[str]) -> None:
   """!Sets the "broke free" messages (index = the checks passed; the last one for more; [] for none).
   @param doc   any manifest Document of the battle
   @param keys  messages of the battle
   @return None
   """
   keys = list(keys)
   if len(keys) > max_break_free():
      raise DocumentError(f"at most {max_break_free()} \"broke free\" messages")
   for k in keys:
      _name_or_none(k, message_choices(doc), BREAK_FREE_KEY)
   live = _live(doc)

   def change() -> None:
      """!Writes the list.
      @return None
      """
      if keys:
         live[BREAK_FREE_KEY] = keys
      else:
         live.pop(BREAK_FREE_KEY, None)

   _guarded(doc, change)


def add_pipeline(ruleset: Document) -> None:
   """!Writes the neutral recruit_odds into the ruleset (inside an edit() of the ruleset Document): rate + item
   bonus + status bonus percent per check, sure from a bonus of 100.
   @param ruleset  the ruleset Document
   @return None
   @throws DocumentError when it lists one already
   """
   given = ruleset.data.setdefault(PIPELINES_KEY, {})
   if pipeline_name() in given:
      raise DocumentError(f"the ruleset lists {pipeline_name()} already")
   given[pipeline_name()] = copy.deepcopy(NEUTRAL_PIPELINE)


# -- renames that follow ----------------------------------------------------------------------------------------------

def message_uses(doc: Document, key: str, new: str | None = None) -> list[str]:
   """!Finds (and renames) a message in the section (core.messages: its uses and renames).
   @param doc  any manifest Document of the battle
   @param key  the message
   @param new  new key, or None to only look
   @return "where" strings
   """
   g = battle.data_of(doc, RECRUIT_KEY).get(RECRUIT_KEY)
   if not isinstance(g, dict):
      return []
   found = []
   msgs = g.get(MESSAGES_KEY)
   for moment, value in list(msgs.items()) if isinstance(msgs, dict) else []:
      if value == key:
         found.append(f"recruit: messages.{moment}")
         if new is not None:
            msgs[moment] = new
   free = g.get(BREAK_FREE_KEY)
   if free == key:
      found.append(f"recruit: {BREAK_FREE_KEY}")
      if new is not None:
         g[BREAK_FREE_KEY] = new
   for i, value in enumerate(free if isinstance(free, list) else []):
      if value == key:
         found.append(f"recruit: {BREAK_FREE_KEY}[{i}]")
         if new is not None:
            free[i] = new
   return found


def _rename_key(table: Any, old: str, new: str | None) -> bool:
   """!Renames an object's key in its place.
   @param table  the object (anything else: nothing)
   @param old    the key
   @param new    new key, or None to only look
   @return True when it held the key
   """
   if not isinstance(table, dict) or old not in table:
      return False
   if new is not None:
      renamed = [(new if k == old else k, v) for k, v in table.items()]
      table.clear()
      table.update(renamed)
   return True


def follow_status_rename(doc: Document, old: str, new: str | None = None) -> int:
   """!A status rename follows into the status bonuses (core.structure.conditions.rename_record()).
   @param doc  any manifest Document of the battle
   @param old  the status
   @param new  its new name, or None to only look
   @return 1 when the section names it, else 0
   """
   g = battle.data_of(doc, RECRUIT_KEY).get(RECRUIT_KEY)
   return int(isinstance(g, dict) and _rename_key(g.get(STATUS_BONUS_KEY), old, new))


def follow_field_rename(doc: Document, old: str, new: str | None = None) -> int:
   """!A species field rename follows into the recruit rate (core.structure.species_fields.rename_field()).
   @param doc  any manifest Document of the battle
   @param old  the field
   @param new  its new name, or None to only look
   @return 1 when the section reads it, else 0
   """
   g = battle.data_of(doc, RECRUIT_KEY).get(RECRUIT_KEY)
   if not isinstance(g, dict) or g.get(RATE_KEY) != old:
      return 0
   if new is not None:
      g[RATE_KEY] = new
   return 1


def follow_role_rename(doc: Document, old: str, new: str | None = None) -> int:
   """!A custom role rename follows into the recruit item_role (core.structure.record.rename_role(); C6).
   @param doc  any manifest Document of the battle
   @param old  the role
   @param new  its new name, or None to only look
   @return 1 when the section names it, else 0
   """
   g = battle.data_of(doc, RECRUIT_KEY).get(RECRUIT_KEY)
   if not isinstance(g, dict) or g.get(ITEM_ROLE_KEY) != old:
      return 0
   if new is not None:
      g[ITEM_ROLE_KEY] = new
   return 1


# -- odds -------------------------------------------------------------------------------------------------------------

def odds(project: BattleProject, inputs: Mapping[str, int] | None = None) -> OddsRow:
   """!The odds of a recruit: recruit_odds run as the engine runs it (the compiled ruleset), for the given inputs.
   @param project  BattleProject
   @param inputs   pipeline inputs (pipeline_inputs(); the others PREVIEW_DEFAULTS, the status bonus the section's
                   "none" one)
   @return OddsRow
   @throws DocumentError when the battle data does not compile or has no recruit section
   """
   compiled, error = project.compile()
   if compiled is None:
      raise DocumentError(f"the battle data does not compile: {error}")
   rec = compiled.get(RECRUIT_KEY)
   if rec is None:
      raise DocumentError("the structure states no recruitment")
   given = dict(PREVIEW_DEFAULTS)
   given[STATUS_INPUT] = int(rec["status_bonus"][0])   # no primary status: the section's "none" bonus
   given.update(inputs or {})
   unknown = sorted(set(given) - set(pipeline_inputs()))
   if unknown:
      raise DocumentError(f"no {pipeline_name()} input {', '.join(unknown)} (inputs: {', '.join(pipeline_inputs())})")
   try:
      out = engine.tool("ruleset_compiler").run_pipeline(compiled["pipelines"], pipeline_name(), given)["outputs"]
   except Exception as e:   # the evaluator's errors (an input out of its range)
      raise DocumentError(str(e)) from None
   sure = bool(out["sure"])
   chance, out_of = int(out["chance"]), max(1, int(out["out_of"]))
   one = 1.0 if sure else max(0, min(chance, out_of)) / out_of
   checks = int(rec["checks"])
   return OddsRow(sure=sure, chance=chance, out_of=out_of, checks=checks, per_check=one * PERCENT,
                  all_checks=one ** checks * PERCENT)


def species_rate(project: BattleProject, species: str) -> int:
   """!A species' recruit rate (its rate field, or 0 when the section reads none).
   @param project  BattleProject
   @param species  species name
   @return the value
   @throws DocumentError when the data does not compile or has no such species
   """
   compiled, error = project.compile()
   if compiled is None:
      raise DocumentError(f"the battle data does not compile: {error}")
   rec = compiled.get(RECRUIT_KEY)
   sp = next((s for s in compiled["species"] if s["name"] == species), None)
   if sp is None:
      raise DocumentError(f"no species {species!r}")
   if rec is None or rec["rate_name"] is None:
      return 0
   return int(sp["fields"][rec["rate_name"]])


def odds_text(row: OddsRow) -> str:
   """!An odds row as text.
   @param row  odds() result
   @return e.g. "sure" or "41/100 a check (41.0 %), 3 checks: 6.9 %"
   """
   if row["sure"]:
      return f"sure ({row['checks']} checks pass without a draw)"
   return (f"{row['chance']}/{row['out_of']} a check ({row['per_check']:.1f} %), {row['checks']} checks: "
           f"{row['all_checks']:.1f} %")


# -- items that recruit -----------------------------------------------------------------------------------------------

def recruit_bonus(project: BattleProject, item: str) -> str | None:
   """!The bonus an item's use_battle logic passes `recruit` (its expression's text), if it recruits.
   @param project  BattleProject
   @param item     item name
   @return the bonus text, or None when its use_battle logic does not recruit
   """
   from .. import inventory   # local: core.inventory imports core.structure
   text = inventory.use_logic(project, item).get(USE_HOOK)
   for line in (text or "").splitlines():
      # `recruit WHO BONUS;`: the primitive, its battler, then the bonus expression (spaces and all)
      words = line.strip().rstrip(";").split(None, CALL_WORDS - 1)
      if len(words) == CALL_WORDS and words[0] == PRIMITIVE:
         return words[-1]
   return None


def recruit_items(project: BattleProject) -> list[str]:
   """!The items whose use_battle logic recruits.
   @param project  BattleProject
   @return names
   """
   names = [str(e.get("name")) for e in battle.entries(project.battle, "items") if isinstance(e, dict)]
   return [n for n in names if recruit_bonus(project, n) is not None]


def set_recruit_logic(project: BattleProject, item: str, bonus: int, label: str = "Recruit logic") -> None:
   """!Makes an item recruit: its use_battle handler becomes `recruit holder BONUS;` (a handler that recruits
   already gets the new bonus; other code in it stays, the recruit last), its use grows to battle use and its
   target becomes a battler (inside an edit() of the battle manifest).
   @param project  BattleProject
   @param item     item name
   @param bonus    the bonus passed to recruit_odds (0 to max_bonus())
   @param label    undo label of the logic edit
   @return None
   @throws DocumentError for a bonus out of range, or data the engine then refuses
   """
   from .. import inventory   # local: as recruit_bonus()
   if not isinstance(bonus, int) or isinstance(bonus, bool) or not 0 <= bonus <= max_bonus():
      raise DocumentError(f"a recruit bonus is 0-{max_bonus()} (got {bonus!r})")
   doc = project.battle

   def change() -> None:
      """!Writes the use, the target and the handler.
      @return None
      """
      e = battle.entry(doc, "items", item)
      use = inventory.fields_of(doc, item)[inventory.USE_KEY]
      if USE_HOOK not in inventory.hooks_needed(use):
         grown = set(inventory.hooks_needed(use)) | {USE_HOOK}
         e[inventory.USE_KEY] = next(u for u in inventory.uses() if set(inventory.hooks_needed(u)) == grown)
      e[inventory.TARGET_KEY] = BATTLER_TARGET
      ref = f"item{logic.OWNER_SEPARATOR}{item}"
      if not any(r.kind == "item" and r.name == item for r in logic.owners(project, "item")):
         logic.add_owner(project, "item", item, label=label)
      ast = logic.owner_ast(project, ref)
      statement = logic.parse_statement(f"{PRIMITIVE} {RECRUIT_WHO} {bonus};")
      handlers = ast.setdefault("handlers", [])
      h = next((h for h in handlers if h.get("on") == USE_HOOK), None)
      if h is None:
         handlers.append({"on": USE_HOOK, "body": [statement]})
      else:
         stub = [logic.parse_statement(inventory.NEW_USE_BODY)]
         body = [s for s in h.get("body", []) if s not in stub and not _is_recruit(s)]
         h["body"] = body + [statement]
      logic.set_owner_ast(project, ref, ast, label)

   _guarded(doc, change)


def _is_recruit(statement: Any) -> bool:
   """!Whether a parsed statement is a `recruit` call.
   @param statement  a statement of the effect AST
   @return True for one
   """
   return isinstance(statement, dict) and statement.get(STATEMENT_KEY) == PRIMITIVE


# -- report -----------------------------------------------------------------------------------------------------------

def lines(doc: Document) -> list[str]:
   """!The section as text (CLI `recruit show`).
   @param doc  any manifest Document of the battle
   @return lines
   """
   if not is_stated(doc):
      return ["(no recruitment: the structure states no recruit section)"]
   s = section(doc)
   bonus = ", ".join(f"{k} {v}" for k, v in s[STATUS_BONUS_KEY].items())
   msgs = ", ".join(f"{m} {k}" for m, k in s[MESSAGES_KEY].items() if k is not None) or "none"
   return [f"checks: {s[CHECKS_KEY]}", f"rate: {s[RATE_KEY] or 'none (0)'}", f"status bonus: {bonus}",
           f"owned: {s[OWNED_KEY]}", f"keep: {', '.join(s[KEEP_KEY]) or 'nothing'}",
           f"refusals using the item up: {', '.join(s[REFUSAL_CONSUMES_KEY]) or 'none'}",
           f"item role: {s[ITEM_ROLE_KEY] or 'none'}", f"messages: {msgs}",
           f"break free: {', '.join(s[BREAK_FREE_KEY]) or 'none'}"]
