"""!The encounter rules of battle data (engine F1, D-27 section 1): the structure manifest's "lead" and what runs
when the walker meets a creature.

    structure.json  "lead": {"when": "level >= 5", "hook_when": "1"}

The lead (capsule::battle::lead_of()) is the party member whose passive and held item run the encounter hooks
(`on encounter`: before the pick, the rate, the level range, a bias by type or species field, a skip below a level;
`on encounter_made`: after the pick, before the battle, a re-roll or a block) and whose level the ruleset's
encounter_rate / encounter_level pipelines see. Without a `lead` section it is the first member that can battle;
`when` makes it the first member for which the expression holds (a growth-style expression over the member's
record: the engine compiles it as one more growth rule, battlec/field.py compile_lead()). C8: `hook_when` picks
another member for the hooks of a passive and a held item (e.g. the first party slot even when it fainted:
"1"); the lead stays the holder of the global rules and the level the pipelines see (a repel-style check). Global
rules (`global "NAME" { on encounter {...} }`, the engine's GLOBAL_KIND) run the same hooks before the lead's.

set_lead() / clear_lead() are one change each (call them inside one edit() of either manifest); a rule the engine
refuses is refused with its message. encounter_handlers() lists the logic that runs the hooks;
encounter_pipelines() whether the ruleset states the two pipelines or the engine runs its defaults.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from .. import battle, engine, logic, pipelines
from ..document import Document, DocumentError

if TYPE_CHECKING:
   from ..battle import BattleProject

## The structure manifest's lead section.
LEAD_KEY = "lead"
## Its expression.
WHEN_KEY = "when"
## C8: the expression choosing the member whose passive and held item run the encounter hooks (default: the lead).
HOOK_WHEN_KEY = "hook_when"
## What the page and the CLI say for the hooks' member when no rule is stated.
DEFAULT_HOOK_TEXT = "the lead"
## The ruleset pipelines of an encounter roll.
PIPELINES = ("encounter_rate", "encounter_level")
## What the page and the CLI say for the engine's lead when no rule is stated.
DEFAULT_LEAD_TEXT = "the first party member that can battle (hit points above 0)"


class HandlerUse(NamedTuple):
   """!One owner running an encounter hook."""

   ## Owner kind (global, passive, item).
   kind: str
   ## Its name.
   name: str
   ## The source it is in.
   file: str
   ## The hook.
   hook: str


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def hooks() -> list[str]:
   """!The encounter hooks (the engine's GLOBAL_HOOKS that are encounter hooks: F3 adds the step effects' steps
   hook to the global ones, the Step effects page's).
   @return names
   """
   encounter = engine.tool("effect_compiler").ENCOUNTER_HOOKS
   return [h for h in _bc().GLOBAL_HOOKS if h in encounter]


def lead_when(doc: Document | None) -> str | None:
   """!The lead rule's expression.
   @param doc  any manifest Document of the battle, or None
   @return its text, or None when the structure states no lead rule
   """
   if doc is None:
      return None
   lead = battle.data_of(doc, LEAD_KEY).get(LEAD_KEY)
   when = lead.get(WHEN_KEY) if isinstance(lead, dict) else None
   return when if isinstance(when, str) else None


def hook_lead_when(doc: Document | None) -> str | None:
   """!C8: the hooks' member's rule (its passive and held item run `on encounter` / `on encounter_made`).
   @param doc  any manifest Document of the battle, or None
   @return its text, or None when the lead runs them
   """
   if doc is None:
      return None
   lead = battle.data_of(doc, LEAD_KEY).get(LEAD_KEY)
   when = lead.get(HOOK_WHEN_KEY) if isinstance(lead, dict) else None
   return when if isinstance(when, str) else None


def describe(doc: Document | None) -> str:
   """!Who leads, in words.
   @param doc  any manifest Document of the battle, or None
   @return text
   """
   when = lead_when(doc)
   return DEFAULT_LEAD_TEXT if when is None else f"the first party member for which `{when}` holds"


def describe_hooks(doc: Document | None) -> str:
   """!C8: whose passive and held item run the encounter hooks, in words.
   @param doc  any manifest Document of the battle, or None
   @return text
   """
   when = hook_lead_when(doc)
   return DEFAULT_HOOK_TEXT if when is None else f"the first party member for which `{when}` holds"


def _guarded(doc: Document, change: Any) -> None:
   """!Runs a change; refuses it with the engine's message when the battle data compiled before and does not
   after, or when the error after it is the lead rule's.
   @param doc     any manifest Document of the battle
   @param change  callable
   @return None
   @throws DocumentError with the engine's message
   """
   project = logic.project_of(doc)
   before = project.error_now() if project is not None else None
   change()
   after = project.error_now() if project is not None else None
   if after is not None and (before is None or f": {LEAD_KEY}" in after):
      raise DocumentError(after)


def _set_rule(doc: Document, key: str, when: str) -> None:
   """!States one of the lead section's rules.
   @param doc   any manifest Document of the battle
   @param key   WHEN_KEY or HOOK_WHEN_KEY
   @param when  an expression over a member's record (empty: the rule is dropped)
   @return None
   @throws DocumentError when the engine refuses it
   """
   when = when.strip() if isinstance(when, str) else when
   if not isinstance(when, str):
      raise DocumentError("a lead rule is an expression over a party member")
   if not when:
      _clear_rule(doc, key)
      return
   data = battle.data_of(doc, LEAD_KEY)

   def change() -> None:
      """!Writes it."""
      lead = data.get(LEAD_KEY)
      if not isinstance(lead, dict):
         lead = data[LEAD_KEY] = {}
      lead[key] = when
   _guarded(doc, change)


def _clear_rule(doc: Document, key: str) -> None:
   """!Drops one of the lead section's rules (the section goes with its last one).
   @param doc  any manifest Document of the battle
   @param key  WHEN_KEY or HOOK_WHEN_KEY
   @return None
   """
   data = battle.data_of(doc, LEAD_KEY)

   def change() -> None:
      """!Drops it."""
      lead = data.get(LEAD_KEY)
      if isinstance(lead, dict):
         lead.pop(key, None)
         if not lead:
            data.pop(LEAD_KEY, None)
      else:
         data.pop(LEAD_KEY, None)
   _guarded(doc, change)


def set_lead(doc: Document, when: str) -> None:
   """!States the lead rule: the first member for which @p when holds leads.
   @param doc   any manifest Document of the battle
   @param when  an expression over a member's record (empty: clear_lead())
   @return None
   @throws DocumentError when the engine refuses it
   """
   _set_rule(doc, WHEN_KEY, when)


def clear_lead(doc: Document) -> None:
   """!Drops the lead rule (the first member that can battle leads; a hooks' rule stays).
   @param doc  any manifest Document of the battle
   @return None
   """
   _clear_rule(doc, WHEN_KEY)


def set_hook_lead(doc: Document, when: str) -> None:
   """!C8: states the hooks' member's rule: the first member for which @p when holds runs the encounter hooks of its
   passive and held item (the lead stays the global rules' holder and the level the pipelines see).
   @param doc   any manifest Document of the battle
   @param when  an expression over a member's record (empty: clear_hook_lead())
   @return None
   @throws DocumentError when the engine refuses it
   """
   _set_rule(doc, HOOK_WHEN_KEY, when)


def clear_hook_lead(doc: Document) -> None:
   """!C8: drops the hooks' member's rule (the lead runs them).
   @param doc  any manifest Document of the battle
   @return None
   """
   _clear_rule(doc, HOOK_WHEN_KEY)


def encounter_handlers(project: BattleProject) -> list[HandlerUse]:
   """!The logic running the encounter hooks: global rules first (the engine runs them first), then passives and
   items (a lead's own run).
   @param project  BattleProject
   @return rows in run order, file order within a kind
   """
   wanted = set(hooks())
   out = []
   for row in logic.owners(project):
      ref = f"{row.kind}{logic.OWNER_SEPARATOR}{row.name}"
      for h in logic.handlers(project, ref):
         if h.member == "on" and h.name in wanted:
            out.append(HandlerUse(row.kind, row.name, row.file, h.name))
   first = logic.global_kind()
   return [u for u in out if u.kind == first] + [u for u in out if u.kind != first]


def encounter_pipelines(project: BattleProject) -> dict[str, bool]:
   """!Whether the ruleset states each encounter pipeline.
   @param project  BattleProject
   @return {pipeline: True when stated, False when the engine runs its default steps}
   """
   known = pipelines.pipeline_names()
   return {name: not pipelines.is_engine_default(project.ruleset, name) for name in PIPELINES if name in known}


def add_global_rule(project: BattleProject, name: str, label: str = "Add global rule") -> str:
   """!Adds a global rule with an empty `on encounter` handler (effects/field.ceffect when no source holds one).
   @param project  BattleProject
   @param name     its name
   @param label    undo label
   @return the source it went to
   """
   kind = logic.global_kind()
   name = name.strip() if isinstance(name, str) else name
   if not isinstance(name, str) or not name:
      raise DocumentError("a global rule needs a name")
   if any(r.kind == kind and r.name == name for r in logic.owners(project, kind)):
      raise DocumentError(f"there is already a global rule {name!r}")
   rel = logic.add_owner(project, kind, name, label=label)
   ref = f"{kind}{logic.OWNER_SEPARATOR}{name}"
   ast = logic.owner_ast(project, ref)
   ast.setdefault("handlers", []).append({"on": hooks()[0], "body": []})
   logic.set_owner_ast(project, ref, ast, label)
   return rel


def lines(project: BattleProject) -> list[str]:
   """!The encounter rules as text (the CLI's `lead show`).
   @param project  BattleProject
   @return lines
   """
   out = [f"lead: {describe(project.structure)}", f"hooks' member: {describe_hooks(project.structure)}"]
   for name, stated in encounter_pipelines(project).items():
      out.append(f"pipeline {name}: {'the ruleset' if stated else 'the engine default'}")
   for u in encounter_handlers(project):
      out.append(f"on {u.hook}: {u.kind} {u.name} ({u.file})")
   return out


def party_names(project: BattleProject) -> list[str]:
   """!The battle's parties (the lead preview's choices).
   @param project  BattleProject
   @return names
   """
   return [p["name"] for p in battle.entries(project.battle, "parties") if isinstance(p.get("name"), str)]


def lead_preview(project: BattleProject, party_name: str, hooks: bool = False) -> int | None:
   """!Which member of one of the battle's parties would lead (F2, the F1 page's preview): the engine's lead rule
   through its Python mirror (bc.growth_holds() on bc.when_values() with the script trigger), or the first member
   when the structure states none (the party's members battle at full hit points).
   @param project     BattleProject
   @param party_name  one of party_names()
   @param hooks       C8: the hooks' member (lead.hook_when; the lead when it states none) instead of the lead
   @return the member's party slot, or None when none leads
   @throws DocumentError when the battle data does not compile or there is no such party
   """
   from . import field_actions   # local: field_actions reads this package's battle helpers
   compiled, error = project.compile()
   if compiled is None:
      raise DocumentError(error or "the battle data does not compile")
   party = field_actions.party_records(project, party_name)
   bc = _bc()
   rule = compiled["field"]["lead_rule"]
   if hooks and compiled["field"].get("hook_lead_rule", bc.NO_LEAD_RULE) != bc.NO_LEAD_RULE:
      rule = compiled["field"]["hook_lead_rule"]
   if rule == bc.NO_LEAD_RULE:
      return 0 if party else None
   for k, rec in enumerate(party):
      if bc.growth_holds(compiled, rule, bc.when_values(compiled, rec, bc.FIELD_LEAD_TRIGGER)):
         return k
   return None
