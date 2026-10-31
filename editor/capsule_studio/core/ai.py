"""!AI profiles of battle data (engine G1, D-26 section 1): the content manifest's "ai_profiles" and each party's
"ai".

    battle.json  "ai_profiles": [{"name": "Basic", "default": true, "rules": [{"rule": "noise", "max": 16},
                                                                               {"rule": "status_move", "score": 8}]},
                                 {"name": "Careful", "rules": [{"rule": "noise"}, {"rule": "damage"},
                                                               {"rule": "hook"}],
                                  "switching": [{"rule": "below", "score": 0}]}]
                 "parties": [{"name": "Rival", "ai": "Careful", ...}]

A profile is an ordered list of scoring rules (the engine runs each for every usable move and target: built-in
terms with their numbers, the ruleset pipeline ai_score, the effect hook ai_score) and an ordered list of
switching rules (after scoring; the first that says so switches out). A party names its profile; a party that
names none, a party of records and an unowned one use the default profile (the one marked default, else the
first). The rule names, their numbers with their ranges and defaults, and every check are the engine's
(battle_compiler re-exports battlec/ai.py: AI_RULES, AI_SWITCH_RULES, AI_RULE_ARGS, AI_SWITCH_ARGS,
compile_ai_profiles()). G3: a third list, "items", holds item-use rules (AI_ITEM_RULES: below_hp uses the item on
the AI's own battler below a share of its HP, hook when the item's own ai_score beats the best move by a margin);
each names its item ("item": one the battle uses in battle), tried after the switching rules.

Each editing helper is one change: call it inside one battle.edit() and Undo takes the whole change back. A
profile rename follows the parties naming it and the game's bench scenarios (core.bench.follow_rename(), same undo
step); a removal is refused while a party names it. An edit that stops data that compiled from compiling is
refused with the engine's message. migrate_flags() turns the former party AI flags into profiles (the engine's
tools/battle_ai.py).
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, TypedDict

from . import battle, bench, engine, logic
from .document import Document, DocumentError

if TYPE_CHECKING:
   from .battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## The content manifest's list of AI profiles.
PROFILES_KEY = "ai_profiles"
## A party's profile.
PARTY_KEY = "ai"
## A profile's name.
NAME_KEY = "name"
## A profile's default mark.
DEFAULT_KEY = "default"
## A profile's scoring rules.
RULES_KEY = "rules"
## A profile's switching rules.
SWITCHING_KEY = "switching"
## A rule's kind.
RULE_KEY = "rule"
## A profile's item-use rules (G3).
ITEMS_KEY = "items"
## The rule lists a profile has, in the order the page shows them.
RULE_LISTS = (RULES_KEY, SWITCHING_KEY, ITEMS_KEY)
## An item-use rule's item (the engine's AI_ITEM_KEY).
ITEM_KEY = "item"
## The uses of an item an item-use rule may name (it is used in battle).
BATTLE_USES = ("battle", "both")
## The list key of profile names in bench scenarios (core.bench.SCENARIO_LISTS) and core.logic.name_lists().
NAMES_LIST = PROFILES_KEY
## Location the compiler's messages name.
WHERE = "battle"
## Undo label of a rename's bench part.
RENAME_LABEL = "Rename AI profile"
## The effect hook a profile's hook rule runs.
HOOK = "ai_score"
## The word the editors show for a party naming no profile (it gets the default one).
DEFAULT_CHOICE = "default"


class RuleRow(TypedDict):
   """!One rule of a profile as the page and the CLI show it."""
   ## Position in its list.
   index: int
   ## Its kind (an engine rule name).
   rule: str
   ## Its numbers: name -> value (the stated one, else the engine's default; None: none stated and no default).
   args: dict[str, int | None]
   ## The numbers it states.
   stated: list[str]
   ## The item an item-use rule names (None for the other lists).
   item: str | None


class ProfileRow(TypedDict):
   """!One profile as the page and the CLI show it."""
   ## Position in the list.
   index: int
   ## Its name.
   name: str
   ## True for the default profile (marked, or the first when none is).
   default: bool
   ## Scoring rules.
   rules: int
   ## Switching rules.
   switching: int
   ## Item-use rules (G3).
   items: int
   ## The parties naming it ("party X"); the default profile's also count parties naming none.
   parties: list[str]


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def rule_kinds(which: str = RULES_KEY) -> list[str]:
   """!The rule names of a list (the engine's AI_RULES / AI_SWITCH_RULES).
   @param which  RULES_KEY, SWITCHING_KEY or ITEMS_KEY
   @return names
   """
   bc = _bc()
   if which == ITEMS_KEY:
      return list(bc.AI_ITEM_RULES)
   return list(bc.AI_SWITCH_RULES if which == SWITCHING_KEY else bc.AI_RULES)


def rule_args(which: str, rule: str) -> dict[str, tuple[int, int, int | None]]:
   """!A rule's numbers with their ranges and defaults (the engine's AI_RULE_ARGS / AI_SWITCH_ARGS).
   @param which  RULES_KEY, SWITCHING_KEY or ITEMS_KEY
   @param rule   rule name
   @return {number: (lowest, highest, default or None)}
   @throws DocumentError for an unknown rule
   """
   bc = _bc()
   table = {SWITCHING_KEY: bc.AI_SWITCH_ARGS, ITEMS_KEY: bc.AI_ITEM_ARGS}.get(which, bc.AI_RULE_ARGS)
   if rule not in table:
      raise DocumentError(f"no {_list_word(which)} rule {rule!r} (rules: {', '.join(rule_kinds(which))})")
   return {name: (lo, hi, default) for name, (_field, lo, hi, default) in table[rule].items()}


def max_profiles() -> int:
   """!Most profiles (the engine's MAX_AI_PROFILES).
   @return count
   """
   return int(_bc().MAX_AI_PROFILES)


def max_rules() -> int:
   """!Most rules of each list per profile (the engine's MAX_AI_RULES).
   @return count
   """
   return int(_bc().MAX_AI_RULES)


def implicit_profile() -> JsonDict:
   """!The profile a battle without "ai_profiles" gets (the engine's AI_DEFAULT_PROFILE).
   @return a copy
   """
   return copy.deepcopy(_bc().AI_DEFAULT_PROFILE)


def hook_entry() -> JsonDict:
   """!The effect hook ai_score as the engine's hook catalog has it (owners, bindings, verdicts, pure).
   @return {"name", "owners", "binds", "value", "results", "draws", "pure"}
   """
   ec = engine.tool("effect_compiler")
   return dict(ec.HOOKS[ec.HOOK[HOOK]])


def _list_word(which: str) -> str:
   """!The word of a rule list ("scoring" / "switching" / "item-use").
   @param which  RULES_KEY, SWITCHING_KEY or ITEMS_KEY
   @return the word
   """
   return {SWITCHING_KEY: "switching", ITEMS_KEY: "item-use"}.get(which, "scoring")


def is_stated(doc: Document) -> bool:
   """!Whether the battle states its AI profiles.
   @param doc  any manifest Document of the battle
   @return True when "ai_profiles" is given
   """
   return PROFILES_KEY in battle.data_of(doc, PROFILES_KEY)


def profiles(doc: Document | None) -> list[JsonDict]:
   """!The profiles in order (the implicit one for a battle without "ai_profiles").
   @param doc  any manifest Document of the battle, or None
   @return the profile dicts (live when stated)
   """
   if doc is None:
      return []
   given = battle.data_of(doc, PROFILES_KEY).get(PROFILES_KEY)
   if not isinstance(given, list):
      return [implicit_profile()]
   return [p for p in given if isinstance(p, dict) and isinstance(p.get(NAME_KEY), str)]


def profile_names(doc: Document | None) -> list[str]:
   """!The profile names in order.
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   return [p[NAME_KEY] for p in profiles(doc)]


def default_name(doc: Document | None) -> str | None:
   """!The default profile's name (the marked one, else the first).
   @param doc  any manifest Document of the battle, or None
   @return its name, or None without profiles
   """
   ps = profiles(doc)
   marked = [p[NAME_KEY] for p in ps if p.get(DEFAULT_KEY) is True]
   return marked[0] if marked else (ps[0][NAME_KEY] if ps else None)


def _parties(doc: Document) -> list[JsonDict]:
   """!The parties of the battle data.
   @param doc  any manifest Document of the battle
   @return party dicts
   """
   return list(battle.entries(doc, "parties"))


def flag_parties(doc: Document) -> list[str]:
   """!The parties still giving the former AI flag lists (migrate_flags() turns them into profiles).
   @param doc  any manifest Document of the battle
   @return their names
   """
   return [str(p.get(NAME_KEY)) for p in _parties(doc) if isinstance(p.get(PARTY_KEY), list)]


def party_profile(doc: Document, party: str) -> str | None:
   """!The profile a party names.
   @param doc    any manifest Document of the battle
   @param party  party name
   @return the profile name, or None (the default one)
   @throws DocumentError when there is no such party
   """
   value = _party(doc, party).get(PARTY_KEY)
   return value if isinstance(value, str) else None


def users(doc: Document, name: str) -> list[str]:
   """!The parties naming a profile (the default one: those naming none too).
   @param doc   any manifest Document of the battle
   @param name  profile name
   @return "party X" strings
   """
   default = default_name(doc) == name
   return [f"party {p.get(NAME_KEY)}" for p in _parties(doc)
           if p.get(PARTY_KEY) == name or (default and PARTY_KEY not in p)]


def profile_rows(doc: Document) -> list[ProfileRow]:
   """!The profiles with what uses them.
   @param doc  any manifest Document of the battle
   @return one row per profile
   """
   default = default_name(doc)
   return [ProfileRow(index=i, name=p[NAME_KEY], default=p[NAME_KEY] == default,
                      rules=len(p.get(RULES_KEY, [])) if isinstance(p.get(RULES_KEY), list) else 0,
                      switching=len(p.get(SWITCHING_KEY, [])) if isinstance(p.get(SWITCHING_KEY), list) else 0,
                      items=len(p.get(ITEMS_KEY, [])) if isinstance(p.get(ITEMS_KEY), list) else 0,
                      parties=users(doc, p[NAME_KEY]))
           for i, p in enumerate(profiles(doc))]


def rule_rows(doc: Document, name: str, which: str = RULES_KEY) -> list[RuleRow]:
   """!A profile's rules of one list, each number filled in with the engine's default.
   @param doc    any manifest Document of the battle
   @param name   profile name
   @param which  RULES_KEY, SWITCHING_KEY or ITEMS_KEY
   @return one row per rule (an unknown rule shows no numbers)
   """
   _check_list(which)
   out = []
   for i, r in enumerate(_profile(doc, name).get(which, []) or []):
      rule = r.get(RULE_KEY) if isinstance(r, dict) else None
      try:
         spec = rule_args(which, rule) if isinstance(rule, str) else {}
      except DocumentError:
         spec = {}
      args = {k: (r[k] if k in r else default) for k, (_lo, _hi, default) in spec.items()}
      item = r.get(ITEM_KEY) if which == ITEMS_KEY and isinstance(r, dict) else None
      out.append(RuleRow(index=i, rule=str(rule), args=args, stated=[k for k in spec if k in r],
                         item=str(item) if item is not None else None))
   return out


# -- the engine's compile ---------------------------------------------------------------------------------------------

def _pipelines(doc: Document) -> list[str]:
   """!The pipelines the battle's ruleset declares (a pipeline rule needs the engine's ai_score among them).
   @param doc  any manifest Document of the battle
   @return pipeline names
   """
   project = logic.project_of(doc)
   data = project.ruleset.data if project is not None else {}
   return list((data.get("pipelines") or {}).keys())


def _item_names(doc: Document) -> list[str]:
   """!The battle's items (an item-use rule names one).
   @param doc  any manifest Document of the battle
   @return names
   """
   return [str(e.get(NAME_KEY)) for e in battle.entries(battle.content_doc(doc), "items") if isinstance(e, dict)]


def item_choices(doc: Document | None) -> list[str]:
   """!The items an item-use rule may name: those used in battle (Content > Items: use battle or both).
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   if doc is None:
      return []
   return [str(e.get(NAME_KEY)) for e in battle.entries(battle.content_doc(doc), "items")
           if isinstance(e, dict) and e.get("use") in BATTLE_USES]


def compile_check(doc: Document) -> tuple[JsonDict | None, str | None]:
   """!Compiles the profiles and the parties' choices with the engine's compile_ai_profiles() / party_profile().
   @param doc  any manifest Document of the battle
   @return (compiled profiles or None, the compiler's message or None)
   """
   bc = _bc()
   try:
      given = bc.strip(copy.deepcopy(battle.data_of(doc, PROFILES_KEY).get(PROFILES_KEY)))
      compiled = bc.compile_ai_profiles(given, WHERE, _pipelines(doc), _item_names(doc))
      for p in _parties(doc):
         bc.party_profile(p.get(PARTY_KEY), compiled, f"{WHERE}: party {p.get(NAME_KEY)!r}")
      return compiled, None
   except Exception as e:   # ManifestError, type errors in odd data
      return None, str(e)


def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the profiles (or the whole battle data) compiled
   before and do not after (raised inside the edit, which puts the manifests back).
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


# -- editing ----------------------------------------------------------------------------------------------------------

def _live(doc: Document) -> list[JsonDict]:
   """!The profile list for editing (the implicit profile is written first when the battle states none).
   @param doc  any manifest Document of the battle
   @return the live list
   """
   data = battle.data_of(doc, PROFILES_KEY)
   if not isinstance(data.get(PROFILES_KEY), list):
      data[PROFILES_KEY] = [implicit_profile()]
   return data[PROFILES_KEY]


def _profile(doc: Document, name: str) -> JsonDict:
   """!One profile (live when stated).
   @param doc   any manifest Document of the battle
   @param name  profile name
   @return the dict
   @throws DocumentError when there is no such profile
   """
   for p in profiles(doc):
      if p[NAME_KEY] == name:
         return p
   raise DocumentError(f"no AI profile {name!r} (profiles: {', '.join(profile_names(doc)) or 'none'})")


def _live_profile(doc: Document, name: str) -> JsonDict:
   """!One profile for editing.
   @param doc   any manifest Document of the battle
   @param name  profile name
   @return the live dict
   """
   for p in _live(doc):
      if isinstance(p, dict) and p.get(NAME_KEY) == name:
         return p
   raise DocumentError(f"no AI profile {name!r} (profiles: {', '.join(profile_names(doc)) or 'none'})")


def _party(doc: Document, party: str) -> JsonDict:
   """!One party.
   @param doc    any manifest Document of the battle
   @param party  party name
   @return the live dict
   @throws DocumentError when there is no such party
   """
   for p in _parties(doc):
      if p.get(NAME_KEY) == party:
         return p
   raise DocumentError(f"no party {party!r}")


def _check_list(which: str) -> None:
   """!Refuses a rule list name that is not one.
   @param which  the list
   @return None
   @throws DocumentError when it is not one of RULE_LISTS
   """
   if which not in RULE_LISTS:
      raise DocumentError(f"a profile's rule lists are {' and '.join(RULE_LISTS)} (got {which!r})")


def _check_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A profile name: not empty, no other profile's.
   @param doc      any manifest Document of the battle
   @param name     the wanted name
   @param current  the name being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   name = name.strip() if isinstance(name, str) else name
   if not isinstance(name, str) or not name:
      raise DocumentError("an AI profile needs a name")
   if name != current and name in profile_names(doc):
      raise DocumentError(f"there is already an AI profile {name!r}")
   return name


def add_profile(doc: Document, name: str, like: str | None = None, at: int | None = None) -> None:
   """!Adds a profile: a copy of another's rules, else the implicit profile's.
   @param doc   any manifest Document of the battle
   @param name  its name
   @param like  the profile whose rules it copies, or None
   @param at    its position (None: last)
   @return None
   """
   name = _check_name(doc, name)
   if len(profile_names(doc)) >= max_profiles():
      raise DocumentError(f"at most {max_profiles()} AI profiles")
   source = copy.deepcopy(_profile(doc, like)) if like is not None else implicit_profile()
   source.pop(DEFAULT_KEY, None)
   new = {NAME_KEY: name, **{k: v for k, v in source.items() if k != NAME_KEY}}

   def change() -> None:
      """!Inserts it."""
      live = _live(doc)
      live.insert(len(live) if at is None else max(0, min(at, len(live))), new)
   _guarded(doc, change)


def remove_profile(doc: Document, name: str) -> None:
   """!Removes a profile (refused while a party names it, and for the last one).
   @param doc   any manifest Document of the battle
   @param name  profile name
   @return None
   """
   named = [f"party {p.get(NAME_KEY)}" for p in _parties(doc) if p.get(PARTY_KEY) == name]
   if named:
      raise DocumentError(f"AI profile {name!r} is used by {', '.join(named)}")
   if len(profile_names(doc)) <= 1:
      raise DocumentError("a battle keeps at least one AI profile")
   _profile(doc, name)

   def change() -> None:
      """!Drops it."""
      live = _live(doc)
      live[:] = [p for p in live if not (isinstance(p, dict) and p.get(NAME_KEY) == name)]
   _guarded(doc, change)


def rename_profile(doc: Document, old: str, new: str) -> list[str]:
   """!Renames a profile; the parties naming it and the game's bench scenarios follow.
   @param doc  any manifest Document of the battle
   @param old  its name
   @param new  the new name
   @return the bench places rewritten ("bench/x.json: parties[1].ai")
   """
   new = _check_name(doc, new, old)
   _profile(doc, old)

   def change() -> None:
      """!Renames it and its users."""
      _live_profile(doc, old)[NAME_KEY] = new
      for p in _parties(doc):
         if p.get(PARTY_KEY) == old:
            p[PARTY_KEY] = new
   _guarded(doc, change)
   return bench.follow_rename(logic.project_of(doc), NAMES_LIST, old, new, RENAME_LABEL)


def move_profile(doc: Document, name: str, delta: int) -> None:
   """!Moves a profile up or down the list (the profile ids follow the order; the default one does not change by it
   unless none is marked).
   @param doc    any manifest Document of the battle
   @param name   profile name
   @param delta  -1 up, +1 down
   @return None
   """
   names = profile_names(doc)
   if name not in names:
      raise DocumentError(f"no AI profile {name!r}")
   i = names.index(name)
   j = i + delta
   if not 0 <= j < len(names):
      return

   def change() -> None:
      """!Swaps it with its neighbour."""
      live = _live(doc)
      live[i], live[j] = live[j], live[i]
   _guarded(doc, change)


def set_default(doc: Document, name: str) -> None:
   """!Marks a profile the default (the others lose the mark).
   @param doc   any manifest Document of the battle
   @param name  profile name
   @return None
   """
   _profile(doc, name)

   def change() -> None:
      """!Moves the mark."""
      for p in _live(doc):
         if isinstance(p, dict):
            if p.get(NAME_KEY) == name:
               p[DEFAULT_KEY] = True
            else:
               p.pop(DEFAULT_KEY, None)
   _guarded(doc, change)


def set_party_profile(doc: Document, party: str, name: str | None) -> None:
   """!Sets the profile a party names (None: the default one; the key goes).
   @param doc    any manifest Document of the battle
   @param party  party name
   @param name   profile name, or None
   @return None
   """
   if name is not None:
      _profile(doc, name)
   p = _party(doc, party)

   def change() -> None:
      """!Writes it."""
      if name is None:
         p.pop(PARTY_KEY, None)
      else:
         p[PARTY_KEY] = name
   _guarded(doc, change)


def _rules(doc: Document, name: str, which: str) -> list[JsonDict]:
   """!A profile's rule list for editing.
   @param doc    any manifest Document of the battle
   @param name   profile name
   @param which  RULES_KEY, SWITCHING_KEY or ITEMS_KEY
   @return the live list
   """
   _check_list(which)
   p = _live_profile(doc, name)
   if not isinstance(p.get(which), list):
      p[which] = []
   return p[which]


def _number(which: str, rule: str, arg: str, value: Any) -> int:
   """!A rule's number the engine takes.
   @param which  the list
   @param rule   rule name
   @param arg    number name
   @param value  the value
   @return it
   @throws DocumentError when the rule has no such number or the value is out of its range
   """
   spec = rule_args(which, rule)
   if arg not in spec:
      raise DocumentError(f"a {rule} rule takes {', '.join(spec) or 'no numbers'} (not {arg!r})")
   lo, hi, _default = spec[arg]
   if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
      raise DocumentError(f"{rule}.{arg}: {lo} to {hi} (got {value!r})")
   return value


def add_rule(doc: Document, name: str, rule: str, which: str = RULES_KEY, at: int | None = None,
             args: Mapping[str, int] | None = None, item: str | None = None) -> None:
   """!Adds a rule to a profile's list (its numbers the engine's defaults unless given).
   @param doc    any manifest Document of the battle
   @param name   profile name
   @param rule   rule name
   @param which  RULES_KEY, SWITCHING_KEY or ITEMS_KEY
   @param at     its position (None: last)
   @param args   numbers it states
   @param item   an item-use rule's item (None: the first of item_choices())
   @return None
   """
   _check_list(which)
   rule_args(which, rule)
   new: JsonDict = {RULE_KEY: rule}
   if which == ITEMS_KEY:
      choices = item_choices(doc)
      item = item if item is not None else (choices[0] if choices else None)
      if item not in choices:
         raise DocumentError(f"an item-use rule names an item used in battle ({', '.join(choices) or 'none'}), "
                             f"got {item!r}")
      new[ITEM_KEY] = item
   elif item is not None:
      raise DocumentError(f"only an item-use rule names an {ITEM_KEY!r}")
   for k, v in (args or {}).items():
      new[k] = _number(which, rule, k, v)
   if len(_profile(doc, name).get(which, []) or []) >= max_rules():
      raise DocumentError(f"at most {max_rules()} {_list_word(which)} rules per profile")

   def change() -> None:
      """!Inserts it."""
      rules = _rules(doc, name, which)
      rules.insert(len(rules) if at is None else max(0, min(at, len(rules))), new)
   _guarded(doc, change)


def remove_rule(doc: Document, name: str, index: int, which: str = RULES_KEY) -> None:
   """!Removes a rule.
   @param doc    any manifest Document of the battle
   @param name   profile name
   @param index  its position
   @param which  RULES_KEY, SWITCHING_KEY or ITEMS_KEY
   @return None
   """
   _rule_at(doc, name, index, which)
   _guarded(doc, lambda: _rules(doc, name, which).pop(index))


def move_rule(doc: Document, name: str, index: int, delta: int, which: str = RULES_KEY) -> None:
   """!Moves a rule up or down its list (the order the engine runs them in: a draw's place changes the draws).
   @param doc    any manifest Document of the battle
   @param name   profile name
   @param index  its position
   @param delta  -1 up, +1 down
   @param which  RULES_KEY, SWITCHING_KEY or ITEMS_KEY
   @return None
   """
   _rule_at(doc, name, index, which)
   j = index + delta
   if not 0 <= j < len(rule_rows(doc, name, which)):
      return

   def change() -> None:
      """!Swaps it with its neighbour."""
      rules = _rules(doc, name, which)
      rules[index], rules[j] = rules[j], rules[index]
   _guarded(doc, change)


def set_rule_arg(doc: Document, name: str, index: int, arg: str, value: int | None,
                 which: str = RULES_KEY) -> None:
   """!Sets one number of a rule (None: back to the engine's default, the key goes).
   @param doc    any manifest Document of the battle
   @param name   profile name
   @param index  the rule's position
   @param arg    the number
   @param value  its value, or None
   @param which  RULES_KEY, SWITCHING_KEY or ITEMS_KEY
   @return None
   """
   rule = _rule_at(doc, name, index, which)
   kind = rule.get(RULE_KEY)
   if value is not None:
      value = _number(which, kind, arg, value)
   elif arg not in rule_args(which, kind):
      raise DocumentError(f"a {kind} rule takes {', '.join(rule_args(which, kind)) or 'no numbers'} (not {arg!r})")

   def change() -> None:
      """!Writes it."""
      live = _rules(doc, name, which)[index]
      if value is None:
         live.pop(arg, None)
      else:
         live[arg] = value
   _guarded(doc, change)


def set_rule_item(doc: Document, name: str, index: int, item: str) -> None:
   """!Sets the item an item-use rule names.
   @param doc    any manifest Document of the battle
   @param name   profile name
   @param index  the rule's position in the item-use list
   @param item   one of item_choices()
   @return None
   """
   _rule_at(doc, name, index, ITEMS_KEY)
   if item not in item_choices(doc):
      raise DocumentError(f"an item-use rule names an item used in battle ({', '.join(item_choices(doc)) or 'none'})"
                          f", got {item!r}")
   _guarded(doc, lambda: _rules(doc, name, ITEMS_KEY)[index].update({ITEM_KEY: item}))


def follow_item_rename(doc: Document, old: str, new: str | None, found: list[str]) -> None:
   """!An item rename follows into the item-use rules (core.battle.references()).
   @param doc    any manifest Document of the battle
   @param old    the item
   @param new    its new name, or None to only look
   @param found  "where" strings, appended to
   @return None
   """
   given = battle.data_of(doc, PROFILES_KEY).get(PROFILES_KEY)
   for p in given if isinstance(given, list) else []:
      for k, r in enumerate(p.get(ITEMS_KEY) or [] if isinstance(p, dict) else []):
         if isinstance(r, dict) and r.get(ITEM_KEY) == old:
            found.append(f"AI profile {p.get(NAME_KEY)} item rule {k}")
            if new is not None:
               r[ITEM_KEY] = new


def _rule_at(doc: Document, name: str, index: int, which: str) -> JsonDict:
   """!One rule.
   @param doc    any manifest Document of the battle
   @param name   profile name
   @param index  its position
   @param which  the list
   @return the rule dict
   @throws DocumentError when there is none there
   """
   _check_list(which)
   rules = _profile(doc, name).get(which, []) or []
   if not isinstance(index, int) or not 0 <= index < len(rules) or not isinstance(rules[index], dict):
      raise DocumentError(f"AI profile {name!r} has no {_list_word(which)} rule {index!r} ({len(rules)} rules)")
   return rules[index]


def migrate_flags(doc: Document) -> list[str]:
   """!Turns the parties' former AI flag lists into profiles, as the engine's tools/battle_ai.py does (each flag
   set a profile of its rules, no flags the default one); nothing when the battle states profiles.
   @param doc  any manifest Document of the battle
   @return what changed (the tool's notes)
   """
   tool = engine.tool("battle_ai")
   content = battle.data_of(doc, "parties")
   migrated, notes = tool.migrate_battle(copy.deepcopy(content))
   if not notes:
      return []

   def change() -> None:
      """!Writes the profiles and the parties' names."""
      content[PROFILES_KEY] = migrated[PROFILES_KEY]
      content["parties"] = migrated["parties"]
   _guarded(doc, change)
   return list(notes)


def lines(doc: Document) -> list[str]:
   """!The profiles as text (the CLI's `ai list`).
   @param doc  any manifest Document of the battle
   @return one line per profile
   """
   out = []
   for row in profile_rows(doc):
      mark = " (default)" if row["default"] else ""
      out.append(f"{row['name']}{mark}: {row['rules']} rules, {row['switching']} switching, {row['items']} item-use; "
                 f"used by {', '.join(row['parties']) or 'nobody'}")
   return out


def rule_lines(doc: Document, name: str) -> list[str]:
   """!A profile's rules as text (the CLI's `ai show`).
   @param doc   any manifest Document of the battle
   @param name  profile name
   @return lines
   """
   out = [f"{name}{' (default)' if default_name(doc) == name else ''}"]
   for which in RULE_LISTS:
      out.append(f"{_list_word(which)}:")
      for row in rule_rows(doc, name, which):
         numbers = ", ".join(f"{k} {v}{'' if k in row['stated'] else ' (default)'}" for k, v in row["args"].items()
                             if v is not None)
         item = f" {row['item']}" if row["item"] is not None else ""
         out.append(f"  {row['index']}: {row['rule']}{item}" + (f" ({numbers})" if numbers else ""))
   return out
