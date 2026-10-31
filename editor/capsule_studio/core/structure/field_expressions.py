"""!The names the field rules of battle data read (engine F1 to F3, D-27; package C8): what a rename elsewhere has to
follow into the structure manifest, and what a removal elsewhere has to be refused for.

    structure.json  "lead": {"when": "level >= 3", "hook_when": "1"},
                    "field_actions": [{"name": "wade", "requires": "knows.tide_slam && flag.badge_1",
                                       "script": "field_wade"}],
                    "step_effects": [{"name": "blight", "script": "field_blight"}]

The expressions are the lead rules (`lead.when`, `lead.hook_when`), the field actions' requirements
(`field_actions[].requires`) and (B1) the combination methods' slot requirements (`combine_methods[].inputs.slots[]
.requires`): the growth `when` language over a member (a custom role `bond` or its halves
`bond_hi` / `bond_lo`, `stat.NAME` and the per-stat roles `stat_genes.NAME`, `species.NAME`, `item.NAME`) and, in a
requirement, `knows.MOVE`, `passive.NAME`, `flag.NAME` and `var.NAME` (battlec/field.py). The scripts are the field
actions' and the step effects' `script`. Each helper takes the battle data as one dict (core.battle.merged(): its
sections are the manifests' live objects, so a rewrite inside an edit() is part of that edit) and returns one
"where" string per expression or record it found; with a new name it rewrites them too.

follow_game_rename() is the scripts' side: a script, flag or variable renamed in the game's `.cscript` sources is
followed into the battle data the scripts manifest names ("battle"), saved at once (core.scripts.ScriptProject).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .. import engine

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure manifest's lead section.
LEAD_KEY = "lead"
## The lead rule (the member whose level the encounter pipelines and the global rules see).
WHEN_KEY = "when"
## The optional hooks' lead rule (the member whose passive and held item run the encounter hooks).
HOOK_WHEN_KEY = "hook_when"
## The lead section's expressions, in the order the page shows them.
LEAD_EXPRESSIONS = (WHEN_KEY, HOOK_WHEN_KEY)
## The structure manifest's field actions.
ACTIONS_KEY = "field_actions"
## A field action's requirement.
REQUIRES_KEY = "requires"
## The structure manifest's step effects.
STEPS_KEY = "step_effects"
## A field action's / step effect's game script.
SCRIPT_KEY = "script"
## A record's name.
NAME_KEY = "name"
## B1: the structure manifest's combination methods (their slots' requirements are growth expressions too).
COMBINE_KEY = "combine_methods"
## The lists whose records run a game script.
SCRIPT_LISTS = (ACTIONS_KEY, STEPS_KEY)
## A word of an expression: a name with at most one dotted part (stat.attack, knows.tide_slam, flag.badge_1), not
## inside a longer name.
WORD = re.compile(r"(?<![A-Za-z0-9_.])[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?(?![A-Za-z0-9_.])")
## Suffixes of a wide custom role's two inputs (battlec/growth.py WhenScope: NAME_hi / NAME_lo).
HALF_SUFFIXES = ("_hi", "_lo")
## The scripts manifest's key naming the battle data.
BATTLE_FILE_KEY = "battle"
## Declaration kinds of the scripts (core.scripts Outline) whose renames the battle data follows.
GAME_KINDS = ("script", "flag", "var")


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def _list_of(d: JsonDict, key: str) -> list[JsonDict]:
   """!The records of a list section (records that are not objects left out).
   @param d    the battle data
   @param key  the section
   @return the live records
   """
   lst = d.get(key)
   return [r for r in lst if isinstance(r, dict)] if isinstance(lst, list) else []


def holders(d: JsonDict) -> list[tuple[JsonDict, str, str]]:
   """!Every expression of the D-27 / D-28 structure sections: the lead rules, the field actions' requirements, the
   combination slots' requirements and (C9) every combination expression (odds, fee, level, each rule's when and
   expression, each pick's where: core.structure.combination's). One path for all of them, so a rename of anything an
   expression names (an item's `item.NAME`, a role, a species field, a stat, a script flag or variable) follows into
   each, and a removal is refused while any reads it. The eggs and nursery sections name entries, never expressions
   (core.structure.nursery follows those).
   @param d  the battle data (core.battle.merged())
   @return (dict holding it, its key, "where" string) per expression
   """
   out: list[tuple[JsonDict, str, str]] = []
   lead = d.get(LEAD_KEY)
   if isinstance(lead, dict):
      for key in LEAD_EXPRESSIONS:
         if isinstance(lead.get(key), str):
            out.append((lead, key, f"{LEAD_KEY}.{key}"))
   for k, a in enumerate(_list_of(d, ACTIONS_KEY)):
      if isinstance(a.get(REQUIRES_KEY), str):
         out.append((a, REQUIRES_KEY, f"{ACTIONS_KEY}[{k}] {a.get(NAME_KEY)}: {REQUIRES_KEY}"))
   # B1: the combination methods' slot requirements (the growth language over one input's record)
   for m in _list_of(d, COMBINE_KEY):
      inputs = m.get("inputs") if isinstance(m.get("inputs"), dict) else {}
      slots = inputs.get("slots") if isinstance(inputs.get("slots"), list) else []
      for k, sl in enumerate(slots):
         if isinstance(sl, dict) and isinstance(sl.get(REQUIRES_KEY), str):
            out.append((sl, REQUIRES_KEY, f"{COMBINE_KEY} {m.get(NAME_KEY)}: slot {k} {REQUIRES_KEY}"))
      # C9: the method's own expressions (the combination language: its words follow here too)
      from . import combination   # local: it imports this module's package
      out += list(combination.method_expressions(m))
   return out


def follow(d: JsonDict, mapping: Mapping[str, str], write: bool = True) -> list[str]:
   """!Finds (and rewrites) the expressions reading any word of @p mapping.
   @param d        the battle data (core.battle.merged(); change it only inside an edit())
   @param mapping  old word -> new word
   @param write    False to only look
   @return "where" per expression found
   """
   found = []
   if not mapping:
      return found
   for holder, key, label in holders(d):
      text = holder[key]
      fixed = WORD.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)
      if any(w in mapping for w in WORD.findall(text)):
         found.append(label)
         if write and fixed != text:
            holder[key] = fixed
   return found


def readers(d: JsonDict, words: list[str]) -> list[str]:
   """!The expressions reading any of @p words (a removal is refused while there are any).
   @param d      the battle data
   @param words  the words
   @return "where" per expression
   """
   return follow(d, {w: w for w in words}, False)


def _renamed(old_words: list[str], new_words: list[str] | None) -> dict[str, str]:
   """!The mapping of a rename (or, without new words, a look-only mapping).
   @param old_words  the words before
   @param new_words  the words after (same order), or None
   @return old -> new
   """
   return dict(zip(old_words, new_words if new_words is not None else old_words))


def follow_move(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A move's rename (or, with None, its readers): `knows.MOVE` in the requirements.
   @param d    the battle data
   @param old  the move's name
   @param new  its new name, or None to only look
   @return "where" per expression
   """
   bc = _bc()
   mapping = _renamed([bc.field_action_move_word(old)], [bc.field_action_move_word(new)] if new else None)
   return follow(d, mapping, new is not None)


def follow_passive(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A passive's rename (or its readers): `passive.NAME` in the requirements.
   @param d    the battle data
   @param old  the passive's name
   @param new  its new name, or None to only look
   @return "where" per expression
   """
   bc = _bc()
   mapping = _renamed([bc.field_action_passive_word(old)], [bc.field_action_passive_word(new)] if new else None)
   return follow(d, mapping, new is not None)


def item_words(name: str) -> list[str]:
   """!An item's words in an expression (bare, and after the prefix item.NAME; battlec/growth.py WhenScope).
   @param name  the item's name
   @return the words
   """
   word = str(_bc().ident(name)).lower()
   return [word, str(_bc().ITEM_PREFIX) + word]


def follow_item(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!An item's rename (or its readers).
   @param d    the battle data
   @param old  the item's name
   @param new  its new name, or None to only look
   @return "where" per expression
   """
   return follow(d, _renamed(item_words(old), item_words(new) if new else None), new is not None)


def role_words(name: str) -> list[str]:
   """!A custom role's inputs (the whole value, and the halves of a wide one).
   @param name  the role
   @return the words
   """
   return [name] + [name + s for s in HALF_SUFFIXES]


def follow_role(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A custom role's rename (or its readers).
   @param d    the battle data
   @param old  the role
   @param new  its new name, or None to only look
   @return "where" per expression
   """
   return follow(d, _renamed(role_words(old), role_words(new) if new else None), new is not None)


def species_field_word(name: str) -> str:
   """!A species field's input.
   @param name  the field
   @return species.NAME
   """
   return str(_bc().SPECIES_PREFIX) + name


def follow_species_field(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A species field's rename (or its readers).
   @param d    the battle data
   @param old  the field
   @param new  its new name, or None to only look
   @return "where" per expression
   """
   mapping = _renamed([species_field_word(old)], [species_field_word(new)] if new else None)
   return follow(d, mapping, new is not None)


def stat_words(name: str) -> list[str]:
   """!A stat's inputs: stat.NAME and each per-stat role's ROLE.NAME (battlec/layout.py PER_STAT_ROLES).
   @param name  the stat
   @return the words
   """
   per_stat = engine.tool("battlec.layout").PER_STAT_ROLES
   return [str(_bc().STAT_PREFIX) + name] + [f"{role}.{name}" for role in per_stat]


def follow_stat(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A stat's rename (or its readers).
   @param d    the battle data
   @param old  the stat
   @param new  its new name, or None to only look
   @return "where" per expression
   """
   return follow(d, _renamed(stat_words(old), stat_words(new) if new else None), new is not None)


def follow_game_ref(d: JsonDict, kind: str, old: str, new: str | None) -> list[str]:
   """!A script flag's or variable's rename (or its readers): `flag.NAME` / `var.NAME` in the requirements.
   @param d     the battle data
   @param kind  "flag" or "var" (battlec/field.py GAME_REF_KINDS)
   @param old   the name
   @param new   its new name, or None to only look
   @return "where" per expression
   """
   return follow(d, _renamed([f"{kind}.{old}"], [f"{kind}.{new}"] if new else None), new is not None)


def follow_script(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A game script's rename (or its users): the field actions' and step effects' `script`, the eggs' hatch_script.
   @param d    the battle data
   @param old  the script
   @param new  its new name, or None to only look
   @return "where" per record
   """
   found = []
   for key in SCRIPT_LISTS:
      for k, r in enumerate(_list_of(d, key)):
         if r.get(SCRIPT_KEY) == old:
            found.append(f"{key}[{k}] {r.get(NAME_KEY)}: {SCRIPT_KEY}")
            if new is not None:
               r[SCRIPT_KEY] = new
   from . import nursery   # local: it imports core.structure
   return found + nursery.follow_script(d, old, new)   # B2: the eggs' hatch script


def battle_file(scripts_manifest: Path, manifest: JsonDict) -> Path | None:
   """!The battle data a scripts manifest names.
   @param scripts_manifest  scripts.json
   @param manifest          its data
   @return battle.json, or None when it names none (or it does not exist)
   """
   rel = manifest.get(BATTLE_FILE_KEY)
   if not isinstance(rel, str):
      return None
   path = scripts_manifest.parent / rel
   return path if path.is_file() else None


def follow_game_rename(battle_json: Path | None, kind: str, old: str, new: str) -> list[str]:
   """!Follows a script, flag or variable rename of the game's scripts into its battle data, saving the manifests it
   changed (the scripts' rename is saved by its own editor; the two never disagree on disk after both are saved).
   @param battle_json  the battle data (battle_file()), or None
   @param kind         the declaration's kind (GAME_KINDS; others follow nothing)
   @param old          the name
   @param new          its new name
   @return "where" per expression or record rewritten
   """
   if battle_json is None or kind not in GAME_KINDS or old == new:
      return []
   from ..battle import BattleProject, merged   # local: core.battle imports this package
   from ..document import DocumentError

   try:
      project = BattleProject.open(battle_json)
   except (DocumentError, OSError, ValueError):
      return []
   d = merged(project.structure)
   wanted = follow_script(d, old, None) if kind == "script" else follow_game_ref(d, kind, old, None)
   if not wanted:
      return []
   with project.structure.edit(f"Follow the scripts' rename of {old}"):
      d = merged(project.structure)
      found = follow_script(d, old, new) if kind == "script" else follow_game_ref(d, kind, old, new)
   project.save_all()
   return found
