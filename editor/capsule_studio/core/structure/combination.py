"""!The combination methods of battle data (engine B1, D-28 section 1): the structure manifest's "combine_methods".

    structure.json  "combine_methods": [{"name": "merge_altar", "label": "Merge Altar", "kind": "immediate",
                     "inputs": {"count": 2, "slots": [{"role": "first", "requires": "level >= 5"}, {"role": "second"}]},
                     "tables": {"elements": {"key": "type", "cells": [["Fire", "Water", "Wind"]]}},
                     "results": [{"table": "elements", "pick": {"where": "cand.base == cand.species"}}],
                     "level": "level_avg", "moves": {"sources": [{"kind": "known", "limit": 2}]},
                     "afterwards": "consumed", "messages": {"combined": "merge_done"}}]

The engine has no idea of breeding, fusion or synthesis: N records go in, the method's result rules (recipes, tables
with a pick, expressions; the first that matches wins) choose a species, the `on combine` effect logic builds the
result (the inheritance primitives) and the engine delivers it (tools/battlec/combine.py is the authority: every
choice list, limit and check here is its). The expressions are the ruleset language over the inputs by slot role
(ROLE.level, ROLE.species, ROLE.base, ROLE.type, ROLE.FIELD, ROLE.R), the aggregates (count, level_avg, ...), the
context values, the words sp.NAME / type.NAME / FIELD.VALUE, a pick's cand.* and the level's / fee's result.*.

Each editing helper is one change: call it inside one edit() of either manifest. An edit that stops data that
compiled from compiling is refused with the engine's message. A method's rename follows the effect logic
(`field.combine_method == NAME`) and the game's scripts (`combine KIND NAME`); a slot role's rename follows the
method's expressions and the logic's `input.ROLE`; renames elsewhere (species, types, moves, species fields and
their values, record roles, context values, messages) follow into every method through follow_entry() and the
other follow_* helpers (core.battle.references(), core.structure.species_fields, record, transformation,
core.messages), and their removals are refused while a method reads them (readers()). preview() runs the engine's
Python mirror on records (species and levels, or a test save's boxed creatures).

C9: every combination expression is also one of core.structure.field_expressions.holders(), so the renames that
follow there (an item's `item.NAME` in a rule's when, ...) follow here and a removal is refused while read. Slot
roles shared by two methods (Starter's grove and merge_altar both have `first`): a role's rename rewrites only its
method's expressions and move sources (`from`), the logic's method-qualified reads `input.METHOD.ROLE` (the
engine's effect compiler takes them: unambiguous), and a bare `input.ROLE` only while no other method gives that
name (else the bare read is the other method's too and stays). A method's rename follows its qualified reads; its
removal is refused while any are read. Move sources take `from` (one slot role; set_source(role=)) and the moves
section `push` (set_moves(push=)).
"""
from __future__ import annotations

import copy

import itertools
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypedDict

from .. import battle, engine, logic
from ..document import Document, DocumentError

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure manifest's list of methods.
METHODS_KEY = "combine_methods"
## A method's name.
NAME_KEY = "name"
## What menus show.
LABEL_KEY = "label"
## Where it runs.
KIND_KEY = "kind"
## Its inputs ({"count", "slots"}).
INPUTS_KEY = "inputs"
## The input count (N or [min, max]).
COUNT_KEY = "count"
## The input slots.
SLOTS_KEY = "slots"
## A slot's role.
ROLE_KEY = "role"
## A slot's requirement.
REQUIRES_KEY = "requires"
## The odds / fee sections ({"value": EXPR}).
ODDS_KEY, FEE_KEY, VALUE_KEY = "odds", "fee", "value"
## The tables.
TABLES_KEY = "tables"
## A table's key, inputs, symmetry and cells.
TABLE_KEY_KEY, TABLE_INPUTS_KEY, SYMMETRIC_KEY, CELLS_KEY = "key", "inputs", "symmetric", "cells"
## The result rules.
RESULTS_KEY = "results"
## A rule's parts.
RECIPE_KEY, RESULT_KEY, TABLE_KEY, PICK_KEY, EXPRESSION_KEY, WHEN_KEY = ("recipe", "result", "table", "pick",
                                                                         "expression", "when")
## A pick's parts.
WHERE_KEY, ORDER_KEY, CHOOSE_KEY, ELSE_KEY = "where", "order", "choose", "else"
## The result's level expression.
LEVEL_KEY = "level"
## The move sources section and its parts.
MOVES_KEY, SOURCES_KEY, LIMIT_KEY, CHOOSER_KEY, FILL_KEY = "moves", "sources", "limit", "chooser", "fill"
## A move source's parts (C9: from, the one slot role it reads).
SOURCE_KIND_KEY, SOURCE_ON_KEY, SOURCE_ALL_KEY, SOURCE_FROM_KEY = "kind", "on", "all", "from"
## C9: the moves section's push flag (the chosen moves learned after the result's own ones).
PUSH_KEY = "push"
## What happens to the inputs, the delivery, the eggs seam, the messages.
AFTERWARDS_KEY, DELIVERY_KEY, EGGS_KEY, MESSAGES_KEY = "afterwards", "delivery", "allow_eggs", "messages"
## The effect compiler's list effect logic names a method from.
LOGIC_LISTS = (METHODS_KEY,)
## Undo label of the logic's part of a rename.
RENAME_LABEL = "Rename combination method"
## The script statement's word (`combine KIND NAME`).
SCRIPT_WORD = "combine"
## The hook the methods run (`on combine`).
HOOK = "combine"
## The subject word of the inputs in effect logic (`input.ROLE`).
INPUT_SUBJECT = "input"
## A word of an expression: a name with at most one dotted part, not inside a longer name.
WORD = re.compile(r"(?<![A-Za-z0-9_.])[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?(?![A-Za-z0-9_.])")
## Default slot roles of a new method's inputs (more inputs: in2, in3, ...).
DEFAULT_ROLES = ("first", "second")
## Prefix of a default role past DEFAULT_ROLES.
ROLE_PREFIX = "in"
## A new method's inputs.
DEFAULT_COUNT = 2
## A table cell's length: [first key value, second key value, group].
CELL_LENGTH = 3
## Suffixes of a wide role's two inputs (battlec/growth.py WhenScope: NAME_hi / NAME_lo).
HALF_SUFFIXES = ("_hi", "_lo")
## The record fields a preview record takes.
SPECIES_FIELD, LEVEL_FIELD = "species", "level"


class MethodRow(TypedDict):
   """!One method as the page and the CLI show it."""
   ## Position (its COMBINE_METHOD_<NAME> id).
   index: int
   ## Its name.
   name: str
   ## What menus show.
   label: str
   ## nursery or immediate.
   kind: str
   ## Fewest inputs.
   min: int
   ## Most inputs.
   max: int
   ## The slot roles.
   roles: list[str]
   ## Where the result goes.
   delivery: str
   ## kept or consumed.
   afterwards: str
   ## Result rules.
   rules: int
   ## Table names.
   tables: list[str]
   ## The effect logic naming it.
   users: list[str]


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


# -- the engine's lists ------------------------------------------------------------------------------------------------

def kinds() -> list[str]:
   """!Where a method runs (the engine's COMBINE_KINDS).
   @return names
   """
   return list(_bc().COMBINE_KINDS)


def deliveries() -> list[str]:
   """!How a result arrives (COMBINE_DELIVERIES).
   @return names
   """
   return list(_bc().COMBINE_DELIVERIES)


def afterwards_choices() -> list[str]:
   """!What happens to the inputs (COMBINE_AFTERWARDS).
   @return names
   """
   return list(_bc().COMBINE_AFTERWARDS)


def choosers() -> list[str]:
   """!Who picks the moves (COMBINE_CHOOSERS).
   @return names
   """
   return list(_bc().COMBINE_CHOOSERS)


def move_sources() -> list[str]:
   """!Where candidate moves come from (COMBINE_MOVE_SOURCES).
   @return names
   """
   return list(_bc().COMBINE_MOVE_SOURCES)


def rule_kinds() -> list[str]:
   """!The result rule kinds (COMBINE_RULE_KINDS).
   @return names
   """
   return list(_bc().COMBINE_RULE_KINDS)


def pick_choices() -> list[str]:
   """!A pick's choices (COMBINE_PICK_CHOICES).
   @return names
   """
   return list(_bc().COMBINE_PICK_CHOICES)


def pick_fallbacks() -> list[str]:
   """!A pick's fallbacks (COMBINE_PICK_ELSE).
   @return names
   """
   return list(_bc().COMBINE_PICK_ELSE)


def order_index() -> str:
   """!A pick's order by the species index (COMBINE_ORDER_INDEX).
   @return the word
   """
   return str(_bc().COMBINE_ORDER_INDEX)


def type_key() -> str:
   """!A table key (and matcher) of the species' first type (COMBINE_TYPE_KEY).
   @return the word
   """
   return str(_bc().COMBINE_TYPE_KEY)


def moments() -> list[str]:
   """!The moments a method's messages name (COMBINE_MOMENTS).
   @return names
   """
   return list(_bc().COMBINE_MOMENTS)


def limits(platform: str | None = None) -> dict[str, int]:
   """!The engine's limits (COMBINE_MAX_*; the inputs per platform: build_settings max_combine_inputs).
   @param platform  a platform name, or None (the strictest, the GBA's)
   @return {"methods", "rules", "tables", "cells", "sources", "candidates", "label", "inputs", "min_inputs",
           "combine_moves"}
   """
   bc = _bc()
   inputs = engine.tool("build_settings").platform_limits(platform)["max_combine_inputs"]
   return {"methods": int(bc.COMBINE_MAX_METHODS), "rules": int(bc.COMBINE_MAX_RULES),
           "tables": int(bc.COMBINE_MAX_TABLES), "cells": int(bc.COMBINE_MAX_CELLS),
           "sources": int(bc.COMBINE_MAX_SOURCES), "candidates": int(bc.COMBINE_MAX_CANDIDATES),
           "label": int(bc.COMBINE_MAX_LABEL), "inputs": int(inputs), "min_inputs": int(bc.COMBINE_MIN_INPUTS),
           "combine_moves": int(bc.MAX_COMBINE_MOVES)}


def expression_words() -> dict[str, list[str]]:
   """!The fixed words of the expressions (the editor's completion): aggregates, the input parts, the prefixes.
   @return {"aggregates", "parts", "prefixes"}
   """
   bc = _bc()
   return {"aggregates": [bc.COMBINE_COUNT_INPUT, *bc.COMBINE_AGGREGATES], "parts": list(bc.COMBINE_INPUT_PARTS),
           "prefixes": [bc.COMBINE_CANDIDATE, bc.COMBINE_RESULT, bc.COMBINE_SPECIES_WORD.rstrip("."),
                        bc.COMBINE_TYPE_WORD.rstrip(".")]}


# -- reading -----------------------------------------------------------------------------------------------------------

def methods(doc: Document | None) -> list[JsonDict]:
   """!The methods in order (live).
   @param doc  any manifest Document of the battle, or None
   @return method dicts (entries that are not objects with a name left out)
   """
   if doc is None:
      return []
   given = battle.data_of(doc, METHODS_KEY).get(METHODS_KEY)
   return [m for m in given if isinstance(m, dict) and isinstance(m.get(NAME_KEY), str)] \
      if isinstance(given, list) else []


def method_names(doc: Document | None) -> list[str]:
   """!The method names in order.
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   return [m[NAME_KEY] for m in methods(doc)]


def method(doc: Document, name: str) -> JsonDict:
   """!One method (live).
   @param doc   any manifest Document of the battle
   @param name  its name
   @return the dict
   @throws DocumentError when there is none
   """
   for m in methods(doc):
      if m[NAME_KEY] == name:
         return m
   raise DocumentError(f"no combination method {name!r} (methods: {', '.join(method_names(doc)) or 'none'})")


def count_of(m: Mapping[str, Any]) -> tuple[int, int]:
   """!A method's input count.
   @param m  the method
   @return (min, max) (2, 2 when it states none or an odd one)
   """
   inputs = m.get(INPUTS_KEY) if isinstance(m.get(INPUTS_KEY), dict) else {}
   c = inputs.get(COUNT_KEY, DEFAULT_COUNT)
   if isinstance(c, int) and not isinstance(c, bool):
      return c, c
   if isinstance(c, list) and len(c) == len(DEFAULT_ROLES) and all(isinstance(x, int) for x in c):
      return int(c[0]), int(c[1])
   return DEFAULT_COUNT, DEFAULT_COUNT


def slots_of(m: Mapping[str, Any]) -> list[JsonDict]:
   """!A method's slots (live).
   @param m  the method
   @return the slot dicts
   """
   inputs = m.get(INPUTS_KEY) if isinstance(m.get(INPUTS_KEY), dict) else {}
   slots = inputs.get(SLOTS_KEY)
   return [s for s in slots if isinstance(s, dict)] if isinstance(slots, list) else []


def roles_of(m: Mapping[str, Any]) -> list[str]:
   """!A method's slot roles.
   @param m  the method
   @return roles in slot order
   """
   return [str(s.get(ROLE_KEY, "")) for s in slots_of(m)]


def tables_of(m: Mapping[str, Any]) -> dict[str, JsonDict]:
   """!A method's tables (live).
   @param m  the method
   @return name -> table
   """
   t = m.get(TABLES_KEY)
   return {k: v for k, v in t.items() if isinstance(v, dict)} if isinstance(t, dict) else {}


def rules_of(m: Mapping[str, Any]) -> list[JsonDict]:
   """!A method's result rules (live).
   @param m  the method
   @return rule dicts
   """
   r = m.get(RESULTS_KEY)
   return [x for x in r if isinstance(x, dict)] if isinstance(r, list) else []


def rule_kind(rule: Mapping[str, Any]) -> str:
   """!A rule's kind.
   @param rule  the rule
   @return recipe / table / expression, or "" for a broken one
   """
   return next((k for k in rule_kinds() if k in rule), "")


def users(doc: Document, name: str) -> list[str]:
   """!The effect logic owners naming a method.
   @param doc   any manifest Document of the battle
   @param name  method name
   @return "FILE: KIND NAME" strings
   """
   return logic.per_owner(logic.references(doc, LOGIC_LISTS, name))


def method_rows(doc: Document) -> list[MethodRow]:
   """!The methods with their defaults filled in and their users.
   @param doc  any manifest Document of the battle
   @return one row per method
   """
   bc = _bc()
   out = []
   for i, m in enumerate(methods(doc)):
      lo, hi = count_of(m)
      out.append(MethodRow(index=i, name=m[NAME_KEY], label=str(m.get(LABEL_KEY, m[NAME_KEY])),
                           kind=str(m.get(KIND_KEY, bc.COMBINE_IMMEDIATE)), min=lo, max=hi, roles=roles_of(m),
                           delivery=str(m.get(DELIVERY_KEY, deliveries()[0])),
                           afterwards=str(m.get(AFTERWARDS_KEY, afterwards_choices()[0])), rules=len(rules_of(m)),
                           tables=list(tables_of(m)), users=users(doc, m[NAME_KEY])))
   return out


def rule_text(rule: Mapping[str, Any]) -> str:
   """!One result rule as a line (the page's rule list, the CLI).
   @param rule  the rule
   @return e.g. "recipe Pixlet + Pupkin -> Owlseer", "table races pick ..."
   """
   kind = rule_kind(rule)
   when = f" when {rule[WHEN_KEY]}" if isinstance(rule.get(WHEN_KEY), str) else ""
   if kind == RECIPE_KEY:
      parts = [m if isinstance(m, str) else ", ".join(f"{k} {v}" for k, v in m.items())
               if isinstance(m, dict) else str(m) for m in rule[RECIPE_KEY] or []]
      return f"recipe {' + '.join(parts)} -> {rule.get(RESULT_KEY)}{when}"
   if kind == TABLE_KEY:
      p = rule.get(PICK_KEY)
      p = {WHERE_KEY: p} if isinstance(p, str) else p if isinstance(p, dict) else {}
      bits = [f"where {p[WHERE_KEY]}"] if WHERE_KEY in p else []
      bits += [f"{k} {p[k]}" for k in (ORDER_KEY, CHOOSE_KEY, ELSE_KEY) if k in p]
      return f"table {rule[TABLE_KEY]}" + (f" pick {', '.join(bits)}" if bits else "") + when
   if kind == EXPRESSION_KEY:
      return f"expression {rule[EXPRESSION_KEY]}{when}"
   return f"(broken rule){when}"


def lines(doc: Document) -> list[str]:
   """!The methods as text (the CLI's `combine list`).
   @param doc  any manifest Document of the battle
   @return one line per method
   """
   out = []
   for r in method_rows(doc):
      count = r["min"] if r["min"] == r["max"] else f"{r['min']}-{r['max']}"
      out.append(f"{r['name']} ({r['label']}): {r['kind']}, {count} inputs ({', '.join(r['roles'])}), "
                 f"{r['rules']} rules, tables {', '.join(r['tables']) or 'none'}, {r['afterwards']}, delivery "
                 f"{r['delivery']}; used by {', '.join(r['users']) or 'nobody'}")
   return out


def show_lines(doc: Document, name: str) -> list[str]:
   """!One method in full (the CLI's `combine show`).
   @param doc   any manifest Document of the battle
   @param name  method name
   @return lines
   """
   m = method(doc, name)
   lo, hi = count_of(m)
   out = [f"{name} ({m.get(LABEL_KEY, name)}): {m.get(KIND_KEY, _bc().COMBINE_IMMEDIATE)}, inputs {lo}-{hi}"]
   for k, s in enumerate(slots_of(m)):
      out.append(f"  slot {k} {s.get(ROLE_KEY)}" + (f" requires {s[REQUIRES_KEY]}" if REQUIRES_KEY in s else ""))
   for key in (ODDS_KEY, FEE_KEY):
      if isinstance(m.get(key), dict):
         out.append(f"  {key} {m[key].get(VALUE_KEY)}")
   for tname, t in tables_of(m).items():
      out.append(f"  table {tname}: key {t.get(TABLE_KEY_KEY)}, {len(t.get(CELLS_KEY) or [])} cells")
      for cell in t.get(CELLS_KEY) or []:
         if isinstance(cell, list) and len(cell) == CELL_LENGTH:
            a, b, group = cell
            out.append(f"    {a} x {b} -> {group}")
         else:
            out.append(f"    {cell}")
   for k, r in enumerate(rules_of(m)):
      out.append(f"  rule {k}: {rule_text(r)}")
   out.append(f"  level {m.get(LEVEL_KEY, _bc().COMBINE_DEFAULT_LEVEL)}")
   mv = m.get(MOVES_KEY) if isinstance(m.get(MOVES_KEY), dict) else {}
   srcs = [f"{s.get(SOURCE_KIND_KEY)}" + (f" (limit {s[LIMIT_KEY]})" if s.get(LIMIT_KEY) else "") +
           ("" if s.get(SOURCE_ON_KEY, True) else " off") + (" all" if s.get(SOURCE_ALL_KEY) else "") +
           (f" from {s[SOURCE_FROM_KEY]}" if s.get(SOURCE_FROM_KEY) else "")
           for s in mv.get(SOURCES_KEY) or [] if isinstance(s, dict)]
   out.append(f"  moves: {', '.join(srcs) or 'the result keeps its own'}; chooser {mv.get(CHOOSER_KEY, choosers()[0])}"
              f", limit {mv.get(LIMIT_KEY, 'move slots')}, fill {mv.get(FILL_KEY, True)}"
              + (", pushed after its own" if mv.get(PUSH_KEY) else ""))
   out.append(f"  afterwards {m.get(AFTERWARDS_KEY, afterwards_choices()[0])}, delivery "
              f"{m.get(DELIVERY_KEY, deliveries()[0])}, eggs {'allowed' if m.get(EGGS_KEY) else 'refused'}")
   msgs = m.get(MESSAGES_KEY) if isinstance(m.get(MESSAGES_KEY), dict) else {}
   out.append(f"  messages: {', '.join(f'{k} {v}' for k, v in msgs.items()) or 'none'}")
   return out


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


def _live(doc: Document) -> list[JsonDict]:
   """!The method list for editing (written when the structure states none).
   @param doc  any manifest Document of the battle
   @return the live list
   """
   data = battle.data_of(doc, METHODS_KEY)
   if not isinstance(data.get(METHODS_KEY), list):
      data[METHODS_KEY] = []
   return data[METHODS_KEY]


def _check_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A method name: not empty, no other method's (the engine checks its form).
   @param doc      any manifest Document of the battle
   @param name     the wanted name
   @param current  the name being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   name = name.strip() if isinstance(name, str) else name
   if not isinstance(name, str) or not name:
      raise DocumentError("a combination method needs a name")
   if name != current and name in method_names(doc):
      raise DocumentError(f"there is already a combination method {name!r}")
   return name


def default_roles(count: int) -> list[str]:
   """!The slot roles a new method's inputs get.
   @param count  how many
   @return roles
   """
   return [DEFAULT_ROLES[k] if k < len(DEFAULT_ROLES) else f"{ROLE_PREFIX}{k}" for k in range(count)]


def add_method(doc: Document, name: str, count: int = DEFAULT_COUNT, at: int | None = None) -> None:
   """!Adds an immediate method of @p count inputs whose one rule gives the first input's species (a start the
   page edits from; the engine's defaults for the rest).
   @param doc    any manifest Document of the battle
   @param name   its name
   @param count  its inputs (2 to the platform's most)
   @param at     its position (None: last)
   @return None
   """
   name = _check_name(doc, name)
   lim = limits()
   if len(methods(doc)) >= lim["methods"]:
      raise DocumentError(f"at most {lim['methods']} combination methods")
   if not isinstance(count, int) or not lim["min_inputs"] <= count <= lim["inputs"]:
      raise DocumentError(f"inputs: {lim['min_inputs']} to {lim['inputs']} (got {count!r})")
   roles = default_roles(count)
   entry = {NAME_KEY: name, KIND_KEY: _bc().COMBINE_IMMEDIATE,
            INPUTS_KEY: {COUNT_KEY: count, SLOTS_KEY: [{ROLE_KEY: r} for r in roles]},
            RESULTS_KEY: [{EXPRESSION_KEY: f"{roles[0]}.species"}]}

   def change() -> None:
      """!Inserts it."""
      live = _live(doc)
      live.insert(len(live) if at is None else max(0, min(at, len(live))), entry)
   _guarded(doc, change)


def script_users(doc: Document, name: str) -> list[str]:
   """!The game's scripts naming a method (`combine KIND NAME`).
   @param doc   any manifest Document of the battle
   @param name  method name
   @return "FILE: line N" strings
   """
   project = logic.project_of(doc)
   manifest = project.scripts_manifest() if project is not None else None
   if manifest is None:
      return []
   kinds_ = "|".join(engine.tool("script_compiler").COMBINE_KINDS)
   pattern = re.compile(rf"\b{SCRIPT_WORD}\s+({kinds_})\s+{re.escape(name)}\b")
   out = []
   for path in sorted(manifest.parent.rglob("*.cscript")):
      try:
         text = path.read_text(encoding="utf-8")
      except OSError:
         continue
      for k, line in enumerate(text.splitlines(), 1):
         if pattern.search(line):
            out.append(f"{path.relative_to(manifest.parent)}: line {k}")
   return out


def remove_method(doc: Document, name: str) -> None:
   """!Removes a method (refused while effect logic or the game's scripts name it).
   @param doc   any manifest Document of the battle
   @param name  method name
   @return None
   """
   m = method(doc, name)
   from . import nursery   # local: it imports this module
   named = users(doc, name) + script_users(doc, name) + nursery.uses(doc, "method", name)   # B2: the nursery's
   named += [u for u in input_users(doc, name) if u not in named]   # C9: `input.METHOD.ROLE` reads
   if named:
      raise DocumentError(f"combination method {name!r} is used by {', '.join(named)}")
   _guarded(doc, lambda: _live(doc).remove(m))


def rename_method(doc: Document, old: str, new: str, follow: bool = True) -> list[str]:
   """!Renames a method; the effect logic naming it follows, and the game's scripts (`combine KIND NAME`).
   @param doc     any manifest Document of the battle
   @param old     its name
   @param new     the new name
   @param follow  False to leave the scripts to follow_scripts() (the CLI follows them after a save)
   @return the places rewritten (logic, then "scripts: ..." ones)
   """
   new = _check_name(doc, new, old)
   m = method(doc, old)

   def change() -> list[str]:
      """!Renames it and its users."""
      m[NAME_KEY] = new
      from . import nursery   # local: it imports this module
      followed = nursery.follow_method(battle.merged(doc), old, new)   # B2: the nursery's method
      qualified: list[str] = []
      for role in roles_of(m):
         # C9: `input.OLD.ROLE` reads follow the method's new name
         qualified += rename_input_subject(doc, f"{old}.{role}", f"{new}.{role}")
      return (logic.references(doc, LOGIC_LISTS, old, new, RENAME_LABEL) + sorted(set(qualified)) +
              [f"structure: {f}" for f in followed])
   places = _guarded(doc, change)
   return places + (follow_scripts(doc, old, new) if follow else [])


def follow_scripts(doc: Document, old: str, new: str) -> list[str]:
   """!The game's scripts follow a method's rename (saved at once, undone with the edit group).
   @param doc  any manifest Document of the battle
   @param old  the old name
   @param new  the new name
   @return "scripts: ..." places
   """
   from .. import scripts
   project = logic.project_of(doc)
   manifest = project.scripts_manifest() if project is not None else None
   kinds_ = list(engine.tool("script_compiler").COMBINE_KINDS)
   return [f"scripts: {p}" for p in scripts.follow_rename(manifest, SCRIPT_WORD, kinds_, old, new, [])]


def move_method(doc: Document, name: str, delta: int) -> None:
   """!Moves a method up or down (the COMBINE_METHOD_<NAME> ids follow the order).
   @param doc    any manifest Document of the battle
   @param name   method name
   @param delta  -1 up, +1 down
   @return None
   """
   names = method_names(doc)
   if name not in names:
      raise DocumentError(f"no combination method {name!r}")
   i = names.index(name)
   j = i + delta
   if not 0 <= j < len(names):
      return

   def change() -> None:
      """!Swaps it with its neighbour."""
      live = _live(doc)
      live[i], live[j] = live[j], live[i]
   _guarded(doc, change)


def _set(doc: Document, name: str, key: str, value: Any, default: Any = None) -> None:
   """!Writes one key of a method (its default: the key goes).
   @param doc      any manifest Document of the battle
   @param name     method name
   @param key      the key
   @param value    the value
   @param default  the value the engine takes when the key is left out
   @return None
   """
   m = method(doc, name)

   def change() -> None:
      """!Writes it."""
      if value == default or value is None:
         m.pop(key, None)
      else:
         m[key] = value
   _guarded(doc, change)


def _choice(value: Any, choices: Sequence[str], what: str) -> str:
   """!Checks a choice.
   @param value    the value
   @param choices  the allowed ones
   @param what     what it is (the message)
   @return it
   @throws DocumentError when it is not one
   """
   if value not in choices:
      raise DocumentError(f"{what}: one of {', '.join(choices)} (got {value!r})")
   return str(value)


def set_label(doc: Document, name: str, label: str) -> None:
   """!Sets what menus show (the name, or empty: the key goes).
   @param doc    any manifest Document of the battle
   @param name   method name
   @param label  up to the engine's longest label
   @return None
   """
   label = label.strip() if isinstance(label, str) else label
   if not isinstance(label, str) or len(label) > limits()["label"]:
      raise DocumentError(f"a label is at most {limits()['label']} letters")
   _set(doc, name, LABEL_KEY, label or name, name)


def set_kind(doc: Document, name: str, kind: str) -> None:
   """!Sets where a method runs (nursery: package B2's; the engine refuses one in B1's immediate path).
   @param doc   any manifest Document of the battle
   @param name  method name
   @param kind  one of kinds()
   @return None
   """
   _set(doc, name, KIND_KEY, _choice(kind, kinds(), "kind"))


def set_delivery(doc: Document, name: str, delivery: str) -> None:
   """!Sets how the result arrives.
   @param doc       any manifest Document of the battle
   @param name      method name
   @param delivery  one of deliveries()
   @return None
   """
   _set(doc, name, DELIVERY_KEY, _choice(delivery, deliveries(), "delivery"), deliveries()[0])


def set_afterwards(doc: Document, name: str, after: str) -> None:
   """!Sets what happens to the inputs.
   @param doc    any manifest Document of the battle
   @param name   method name
   @param after  one of afterwards_choices()
   @return None
   """
   _set(doc, name, AFTERWARDS_KEY, _choice(after, afterwards_choices(), "afterwards"), afterwards_choices()[0])


def set_allow_eggs(doc: Document, name: str, on: bool) -> None:
   """!Sets whether eggs may be inputs (package B2's egg role).
   @param doc   any manifest Document of the battle
   @param name  method name
   @param on    allowed
   @return None
   """
   _set(doc, name, EGGS_KEY, bool(on), False)


def set_level(doc: Document, name: str, expr: str) -> None:
   """!Sets the result's level expression (empty: the engine's default, 1).
   @param doc   any manifest Document of the battle
   @param name  method name
   @param expr  the expression
   @return None
   """
   expr = expr.strip() if isinstance(expr, str) else ""
   _set(doc, name, LEVEL_KEY, expr or None, _bc().COMBINE_DEFAULT_LEVEL)


def set_value(doc: Document, name: str, key: str, expr: str | None) -> None:
   """!Sets the odds or fee expression (None or empty: the section goes).
   @param doc   any manifest Document of the battle
   @param name  method name
   @param key   ODDS_KEY or FEE_KEY
   @param expr  the expression, or None
   @return None
   """
   if key not in (ODDS_KEY, FEE_KEY):
      raise DocumentError(f"{key!r}: odds or fee")
   expr = expr.strip() if isinstance(expr, str) else ""
   _set(doc, name, key, {VALUE_KEY: expr} if expr else None)


def set_count(doc: Document, name: str, lo: int, hi: int) -> None:
   """!Sets the input count: slots are added (default roles) or dropped from the end (a dropped slot's role read by
   an expression stops the data from compiling: refused).
   @param doc   any manifest Document of the battle
   @param name  method name
   @param lo    fewest inputs
   @param hi    most inputs
   @return None
   """
   lim = limits()
   if not (isinstance(lo, int) and isinstance(hi, int)) or not lim["min_inputs"] <= lo <= hi <= lim["inputs"]:
      raise DocumentError(f"inputs: {lim['min_inputs']} <= min <= max <= {lim['inputs']} (got {lo!r}, {hi!r})")
   m = method(doc, name)

   def change() -> None:
      """!Writes the count and the slots."""
      inputs = m.setdefault(INPUTS_KEY, {})
      slots = inputs.setdefault(SLOTS_KEY, [])
      roles = roles_of(m)
      for k in range(len(slots), hi):
         # the default roles first, then in1, in2, ... (an endless supply: the first one not taken)
         role = next(r for r in itertools.chain(default_roles(hi), (f"{ROLE_PREFIX}{x}" for x in itertools.count(1)))
                     if r not in roles)
         roles.append(role)
         slots.append({ROLE_KEY: role})
      del slots[hi:]
      inputs[COUNT_KEY] = lo if lo == hi else [lo, hi]
   _guarded(doc, change)


def rename_slot_words(m: JsonDict, old: str, new: str) -> list[str]:
   """!Rewrites a slot role's words (old.X -> new.X) in a method's expressions.
   @param m    the method (live)
   @param old  the role
   @param new  its new name
   @return "where" per expression rewritten
   """
   return _rewrite_method(m, lambda w: f"{new}.{w.split('.', 1)[1]}" if w.split(".")[0] == old and "." in w
                          else None, m.get(NAME_KEY, ""))


def set_slot(doc: Document, name: str, slot: int, role: str | None = None, requires: str | None = None,
             clear_requires: bool = False) -> list[str]:
   """!Sets a slot's role (its rename follows the method's expressions and the effect logic's `input.ROLE`) and its
   requirement (a growth `when` expression over the input's record).
   @param doc             any manifest Document of the battle
   @param name            method name
   @param slot            slot index
   @param role            its new role, or None
   @param requires        its requirement, or None
   @param clear_requires  True: no requirement
   @return the places a role rename rewrote
   """
   m = method(doc, name)
   slots = slots_of(m)
   if not isinstance(slot, int) or not 0 <= slot < len(slots):
      raise DocumentError(f"slot {slot!r}: {name} has slots 0 to {len(slots) - 1}")
   s = slots[slot]
   old = str(s.get(ROLE_KEY, ""))
   if role is not None:
      role = role.strip()
      if role != old and role in roles_of(m):
         raise DocumentError(f"slot role {role!r} is taken")

   def change() -> list[str]:
      """!Writes the slot and follows the role."""
      places: list[str] = []
      if role is not None and role and role != old:
         s[ROLE_KEY] = role
         places += rename_slot_words(m, old, role)
         places += rename_source_roles(m, old, role)
         # C9: the logic's reads of this method's role: `input.METHOD.ROLE` always; a bare `input.ROLE` only when no
         # other method gives the name (else it reads theirs and stays)
         places += rename_input_subject(doc, f"{name}.{old}", f"{name}.{role}")
         if not any(old in roles_of(o) for o in methods(doc) if o is not m):
            places += rename_input_subject(doc, old, role)
      if clear_requires:
         s.pop(REQUIRES_KEY, None)
      elif requires is not None:
         if requires.strip():
            s[REQUIRES_KEY] = requires.strip()
         else:
            s.pop(REQUIRES_KEY, None)
      return places
   return _guarded(doc, change)


def rename_source_roles(m: JsonDict, old: str, new: str | None) -> list[str]:
   """!A method's move sources naming a slot role (`from`) follow its rename (C9), or are listed.
   @param m    the method (live)
   @param old  the role
   @param new  its new name, or None to only look
   @return "where" per source
   """
   found = []
   for s in sources_of(m):
      if s.get(SOURCE_FROM_KEY) == old:
         found.append(f"{METHODS_KEY} {m.get(NAME_KEY)}: move source {s.get(SOURCE_KIND_KEY)} from")
         if new is not None:
            s[SOURCE_FROM_KEY] = new
   return found


def input_users(doc: Document, name: str) -> list[str]:
   """!The effect logic owners reading a method's slot roles by its name (C9: `input.METHOD.ROLE`).
   @param doc   any manifest Document of the battle
   @param name  method name
   @return "FILE: KIND NAME" strings
   """
   m = method(doc, name)
   found: list[str] = []
   for role in roles_of(m):
      found += rename_input_subject(doc, f"{name}.{role}", None)
   return sorted(set(found))


def rename_input_subject(doc: Document, old: str, new: str | None) -> list[str]:
   """!The effect logic's `input.OLD` subjects and reads follow a slot role's rename (owner blocks rewritten in
   canonical form, part of the edit running). C9: OLD may be method-qualified (METHOD.ROLE: `input.METHOD.ROLE`).
   @param doc  any manifest Document of the battle
   @param old  the role (or METHOD.ROLE)
   @param new  its new name (or METHOD.NEW), or None to only look
   @return "where" per owner rewritten (or reading it)
   """
   project = logic.project_of(doc)
   if project is None:
      return []
   before, after = f"{INPUT_SUBJECT}.{old}", f"{INPUT_SUBJECT}.{new}"

   def walk(node: Any) -> bool:
      """!Rewrites a subtree; true when something changed."""
      changed = False
      if isinstance(node, dict):
         for k, v in list(node.items()):
            if isinstance(v, str) and (v == before or v.startswith(before + ".")):
               if new is not None:
                  node[k] = after + v[len(before):]
               changed = True
            else:
               changed = walk(v) or changed
      elif isinstance(node, list):
         for v in node:
            changed = walk(v) or changed
      return changed
   found = []
   for p in logic.parsed_sources(project):
      changes = {}
      for i, (node, span) in enumerate(p.owners):
         if walk(node):   # with new None it only looks
            changes[i] = logic._format_owner(node)
            found.append(f"{p.rel}: {span.kind} {span.name}")
      if changes and new is not None:
         text = logic._splice(p.text, [s for _n, s in p.owners], changes)
         logic._write_source(p.doc, text, RENAME_LABEL + logic.FOLLOW_LABEL)
   return found


# -- tables ------------------------------------------------------------------------------------------------------------

def _table(m: JsonDict, table: str) -> JsonDict:
   """!One table of a method (live).
   @param m      the method
   @param table  its name
   @return the dict
   @throws DocumentError when there is none
   """
   t = tables_of(m).get(table)
   if t is None:
      raise DocumentError(f"no table {table!r} in {m.get(NAME_KEY)} (tables: {', '.join(tables_of(m)) or 'none'})")
   return t


def add_table(doc: Document, name: str, table: str, key: str) -> None:
   """!Adds an empty table keyed by a species field (or the type).
   @param doc    any manifest Document of the battle
   @param name   method name
   @param table  its name
   @param key    a species field or type_key()
   @return None
   """
   m = method(doc, name)
   table = table.strip() if isinstance(table, str) else table
   if not isinstance(table, str) or not table or table in tables_of(m):
      raise DocumentError(f"a table needs a name of its own (got {table!r})")

   def change() -> None:
      """!Adds it."""
      m.setdefault(TABLES_KEY, {})[table] = {TABLE_KEY_KEY: key, CELLS_KEY: []}
   _guarded(doc, change)


def remove_table(doc: Document, name: str, table: str) -> None:
   """!Removes a table (refused while a rule uses it).
   @param doc    any manifest Document of the battle
   @param name   method name
   @param table  its name
   @return None
   """
   m = method(doc, name)
   _table(m, table)
   used = [k for k, r in enumerate(rules_of(m)) if r.get(TABLE_KEY) == table]
   if used:
      raise DocumentError(f"table {table!r} is used by rule(s) {', '.join(str(k) for k in used)}")

   def change() -> None:
      """!Removes it."""
      m[TABLES_KEY].pop(table)
      if not m[TABLES_KEY]:
         m.pop(TABLES_KEY)
   _guarded(doc, change)


def rename_table(doc: Document, name: str, old: str, new: str) -> None:
   """!Renames a table; its rules follow.
   @param doc   any manifest Document of the battle
   @param name  method name
   @param old   its name
   @param new   the new name
   @return None
   """
   m = method(doc, name)
   t = _table(m, old)
   new = new.strip() if isinstance(new, str) else new
   if not isinstance(new, str) or not new or (new != old and new in tables_of(m)):
      raise DocumentError(f"a table needs a name of its own (got {new!r})")

   def change() -> None:
      """!Renames it in place (order kept) and its rules."""
      m[TABLES_KEY] = {new if k == old else k: (t if k == old else v) for k, v in m[TABLES_KEY].items()}
      for r in rules_of(m):
         if r.get(TABLE_KEY) == old:
            r[TABLE_KEY] = new
   _guarded(doc, change)


def set_table(doc: Document, name: str, table: str, key: str | None = None, symmetric: bool | None = None,
              inputs: Sequence[int] | None = None) -> None:
   """!Sets a table's key, symmetry or keyed inputs.
   @param doc        any manifest Document of the battle
   @param name       method name
   @param table      its name
   @param key        a species field or type_key(), or None
   @param symmetric  (a, b) matches (b, a), or None
   @param inputs     the two keyed input slots, or None
   @return None
   """
   m = method(doc, name)
   t = _table(m, table)

   def change() -> None:
      """!Writes them."""
      if key is not None:
         t[TABLE_KEY_KEY] = key
      if symmetric is not None:
         if symmetric:
            t.pop(SYMMETRIC_KEY, None)
         else:
            t[SYMMETRIC_KEY] = False
      if inputs is not None:
         if list(inputs) == [0, 1]:
            t.pop(TABLE_INPUTS_KEY, None)
         else:
            t[TABLE_INPUTS_KEY] = list(inputs)
   _guarded(doc, change)


def cells(doc: Document, name: str, table: str) -> dict[tuple[Any, Any], Any]:
   """!A table's cells.
   @param doc    any manifest Document of the battle
   @param name   method name
   @param table  its name
   @return (a, b) -> value
   """
   t = _table(method(doc, name), table)
   given = [c for c in t.get(CELLS_KEY) or [] if isinstance(c, list) and len(c) == CELL_LENGTH]
   return {(a, b): group for a, b, group in given}


def key_values(doc: Document, key: str) -> list[str]:
   """!The values a table key takes: a field's value names (or nothing for a numeric field: numbers), the types.
   @param doc  any manifest Document of the battle
   @param key  a species field or type_key()
   @return the names (a numeric field: [])
   """
   if key == type_key():
      return [str(t.get("name")) for t in battle.entries(battle.content_doc(doc), "types") if isinstance(t, dict)]
   fields = battle.merged(doc).get("species_fields")
   f = next((x for x in fields if isinstance(x, dict) and x.get("name") == key), None) \
      if isinstance(fields, list) else None
   return list(f.get("values") or []) if isinstance(f, dict) else []


def set_cell(doc: Document, name: str, table: str, a: Any, b: Any, value: Any | None) -> None:
   """!Sets one cell (None: the cell goes). A symmetric table keeps one cell per pair.
   @param doc    any manifest Document of the battle
   @param name   method name
   @param table  its name
   @param a      the first input's key value
   @param b      the second's
   @param value  the group, or None
   @return None
   """
   m = method(doc, name)
   t = _table(m, table)
   lim = limits()["cells"]
   sym = t.get(SYMMETRIC_KEY, True) is not False

   def change() -> None:
      """!Writes it."""
      lst = t.setdefault(CELLS_KEY, [])
      for c in list(lst):
         pair = tuple(c[:CELL_LENGTH - 1]) if isinstance(c, list) and len(c) == CELL_LENGTH else None
         if pair is not None and (pair == (a, b) or (sym and pair == (b, a))):
            lst.remove(c)
      if value is not None:
         if len(lst) >= lim:
            raise DocumentError(f"a table holds at most {lim} cells")
         lst.append([a, b, value])
   _guarded(doc, change)


# -- result rules ------------------------------------------------------------------------------------------------------

def _rule(m: JsonDict, k: int) -> JsonDict:
   """!One rule (live).
   @param m  the method
   @param k  its index
   @return the dict
   @throws DocumentError out of range
   """
   rules = rules_of(m)
   if not isinstance(k, int) or not 0 <= k < len(rules):
      raise DocumentError(f"rule {k!r}: {m.get(NAME_KEY)} has rules 0 to {len(rules) - 1}")
   return rules[k]


def add_rule(doc: Document, name: str, rule: JsonDict, at: int | None = None) -> None:
   """!Adds a result rule (one of rule_kinds(): {"recipe": [...], "result": S}, {"table": T, "pick": ...},
   {"expression": E}; "when" optional).
   @param doc   any manifest Document of the battle
   @param name  method name
   @param rule  the rule
   @param at    its position (None: last)
   @return None
   """
   m = method(doc, name)
   if len(rules_of(m)) >= limits()["rules"]:
      raise DocumentError(f"at most {limits()['rules']} rules")
   if rule_kind(rule) == "":
      raise DocumentError(f"a rule is one of {', '.join(rule_kinds())}")
   entry = copy.deepcopy(dict(rule))

   def change() -> None:
      """!Inserts it."""
      lst = m.setdefault(RESULTS_KEY, [])
      lst.insert(len(lst) if at is None else max(0, min(at, len(lst))), entry)
   _guarded(doc, change)


def remove_rule(doc: Document, name: str, k: int) -> None:
   """!Removes a result rule (refused for the last one: a method needs one).
   @param doc   any manifest Document of the battle
   @param name  method name
   @param k     its index
   @return None
   """
   m = method(doc, name)
   r = _rule(m, k)
   if len(rules_of(m)) == 1:
      raise DocumentError("a method needs a result rule")
   _guarded(doc, lambda: m[RESULTS_KEY].remove(r))


def move_rule(doc: Document, name: str, k: int, delta: int) -> None:
   """!Moves a rule up or down (the first that matches wins).
   @param doc    any manifest Document of the battle
   @param name   method name
   @param k      its index
   @param delta  -1 up, +1 down
   @return None
   """
   m = method(doc, name)
   _rule(m, k)
   j = k + delta
   if not 0 <= j < len(rules_of(m)):
      return

   def change() -> None:
      """!Swaps it."""
      lst = m[RESULTS_KEY]
      lst[k], lst[j] = lst[j], lst[k]
   _guarded(doc, change)


def set_rule(doc: Document, name: str, k: int, **parts: Any) -> None:
   """!Changes parts of a rule: when (None or "": none), recipe (matchers), result, table, pick (an expression or
   {where, order, choose, else}; None: none), expression.
   @param doc    any manifest Document of the battle
   @param name   method name
   @param k      its index
   @param parts  the parts to write
   @return None
   """
   m = method(doc, name)
   r = _rule(m, k)
   known = {WHEN_KEY, RECIPE_KEY, RESULT_KEY, TABLE_KEY, PICK_KEY, EXPRESSION_KEY}
   unknown = set(parts) - known
   if unknown:
      raise DocumentError(f"unknown rule part(s) {', '.join(sorted(unknown))}")

   def change() -> None:
      """!Writes them."""
      for key, value in parts.items():
         if value is None or value == "":
            r.pop(key, None)
         else:
            r[key] = copy.deepcopy(value)
   _guarded(doc, change)


# -- moves and messages ------------------------------------------------------------------------------------------------

def set_moves(doc: Document, name: str, limit: int | None = None, chooser: str | None = None,
              fill: bool | None = None, push: bool | None = None) -> None:
   """!Sets the move chooser's limit (0: the layout's move slots), the chooser, whether the result's own moves
   fill the slots left and (C9) whether the chosen moves are pushed after the result's own ones (each pushing the
   first out when the slots are full).
   @param doc      any manifest Document of the battle
   @param name     method name
   @param limit    the limit, or None
   @param chooser  one of choosers(), or None
   @param fill     fill, or None
   @param push     push, or None
   @return None
   """
   m = method(doc, name)
   if chooser is not None:
      _choice(chooser, choosers(), "chooser")

   def change() -> None:
      """!Writes them."""
      mv = m.setdefault(MOVES_KEY, {})
      if limit is not None:
         if limit:
            mv[LIMIT_KEY] = limit
         else:
            mv.pop(LIMIT_KEY, None)
      if chooser is not None:
         if chooser == choosers()[0]:
            mv.pop(CHOOSER_KEY, None)
         else:
            mv[CHOOSER_KEY] = chooser
      if fill is not None:
         if fill:
            mv.pop(FILL_KEY, None)
         else:
            mv[FILL_KEY] = False
      if push is not None:
         if push:
            mv[PUSH_KEY] = True
         else:
            mv.pop(PUSH_KEY, None)
      if not mv:
         m.pop(MOVES_KEY)
   _guarded(doc, change)


def sources_of(m: Mapping[str, Any]) -> list[JsonDict]:
   """!A method's move sources (live).
   @param m  the method
   @return source dicts
   """
   mv = m.get(MOVES_KEY) if isinstance(m.get(MOVES_KEY), dict) else {}
   s = mv.get(SOURCES_KEY)
   return [x for x in s if isinstance(x, dict)] if isinstance(s, list) else []


def set_source(doc: Document, name: str, kind: str, on: bool = True, limit: int = 0, every: bool = False,
               role: str | None = None) -> None:
   """!Adds or changes a move source.
   @param doc    any manifest Document of the battle
   @param name   method name
   @param kind   one of move_sources()
   @param on     on
   @param limit  most moves it gives (0: no limit)
   @param every  combine_moves: the whole list
   @param role   C9: the one slot role it reads (`from`: that input's moves, in slot order), or None: every input
   @return None
   """
   _choice(kind, move_sources(), "move source")
   m = method(doc, name)
   if role is not None and role not in roles_of(m):
      raise DocumentError(f"from {role!r}: one of {name}'s slot roles ({', '.join(roles_of(m))})")
   if role is not None and every:
      raise DocumentError("a source reading one input does not take the whole list")

   def change() -> None:
      """!Writes it."""
      lst = m.setdefault(MOVES_KEY, {}).setdefault(SOURCES_KEY, [])
      s = next((x for x in lst if isinstance(x, dict) and x.get(SOURCE_KIND_KEY) == kind), None)
      if s is None:
         if len(lst) >= limits()["sources"]:
            raise DocumentError(f"at most {limits()['sources']} move sources")
         s = {SOURCE_KIND_KEY: kind}
         lst.append(s)
      for key, value, default in ((SOURCE_ON_KEY, on, True), (LIMIT_KEY, limit, 0), (SOURCE_ALL_KEY, every, False),
                                  (SOURCE_FROM_KEY, role, None)):
         if value == default:
            s.pop(key, None)
         else:
            s[key] = value
   _guarded(doc, change)


def remove_source(doc: Document, name: str, kind: str) -> None:
   """!Removes a move source.
   @param doc   any manifest Document of the battle
   @param name  method name
   @param kind  its kind
   @return None
   """
   m = method(doc, name)
   s = next((x for x in sources_of(m) if x.get(SOURCE_KIND_KEY) == kind), None)
   if s is None:
      raise DocumentError(f"{name} has no move source {kind!r}")

   def change() -> None:
      """!Removes it (and an empty moves section)."""
      mv = m[MOVES_KEY]
      mv[SOURCES_KEY].remove(s)
      if not mv[SOURCES_KEY]:
         mv.pop(SOURCES_KEY)
      if not mv:
         m.pop(MOVES_KEY)
   _guarded(doc, change)


def message_choices(doc: Document) -> list[str]:
   """!The battle's messages a moment may name.
   @param doc  any manifest Document of the battle
   @return message keys
   """
   from . import step_effects   # local: the same declared-messages lookup
   return step_effects.message_choices(doc)


def set_message(doc: Document, name: str, moment: str, key: str | None) -> None:
   """!Sets a moment's battle message (None or empty: none).
   @param doc     any manifest Document of the battle
   @param name    method name
   @param moment  one of moments()
   @param key     one of message_choices(), or None
   @return None
   """
   _choice(moment, moments(), "moment")
   key = key or None
   if key is not None and key not in message_choices(doc):
      raise DocumentError(f"{key!r} is not one of the battle's messages")
   m = method(doc, name)

   def change() -> None:
      """!Writes it (the engine's moment order)."""
      msgs = m.get(MESSAGES_KEY) if isinstance(m.get(MESSAGES_KEY), dict) else {}
      if key is None:
         msgs.pop(moment, None)
      else:
         msgs[moment] = key
      if msgs:
         m[MESSAGES_KEY] = {x: msgs[x] for x in moments() if x in msgs}
      else:
         m.pop(MESSAGES_KEY, None)
   _guarded(doc, change)


# -- what renames elsewhere follow -------------------------------------------------------------------------------------

def method_expressions(m: JsonDict) -> Iterator[tuple[JsonDict, str, str]]:
   """!A method's combination expressions (C9: also core.structure.field_expressions.holders(), the one path every
   rename and removal check of an expression's words takes; the slots' requirements are listed there).
   @param m  the method
   @return (dict holding it, its key, "where" string) per expression
   """
   return _expressions(m)


def _expressions(m: JsonDict) -> Iterator[tuple[JsonDict, str, str]]:
   """!A method's combination expressions (not the slots' requirements: core.structure.field_expressions holds those).
   @param m  the method
   @return (dict holding it, its key, "where" string) per expression
   """
   name = m.get(NAME_KEY)
   for key in (ODDS_KEY, FEE_KEY):
      if isinstance(m.get(key), dict) and isinstance(m[key].get(VALUE_KEY), str):
         yield m[key], VALUE_KEY, f"{METHODS_KEY} {name}: {key}"
   if isinstance(m.get(LEVEL_KEY), str):
      yield m, LEVEL_KEY, f"{METHODS_KEY} {name}: {LEVEL_KEY}"
   for k, r in enumerate(rules_of(m)):
      for key in (WHEN_KEY, EXPRESSION_KEY):
         if isinstance(r.get(key), str):
            yield r, key, f"{METHODS_KEY} {name}: rule {k} {key}"
      p = r.get(PICK_KEY)
      if isinstance(p, str):
         yield r, PICK_KEY, f"{METHODS_KEY} {name}: rule {k} pick"
      elif isinstance(p, dict) and isinstance(p.get(WHERE_KEY), str):
         yield p, WHERE_KEY, f"{METHODS_KEY} {name}: rule {k} pick"


def _rewrite_method(m: JsonDict, fn: Callable[[str], str | None], _name: str, write: bool = True) -> list[str]:
   """!Rewrites the words of a method's expressions.
   @param m      the method
   @param fn     word -> new word, or None to keep it
   @param _name  the method's name (unused: the where strings carry it)
   @param write  False to only look
   @return "where" per expression with a word fn maps
   """
   found = []
   for holder, key, where in _expressions(m):
      text = holder[key]
      hit = [w for w in WORD.findall(text) if fn(w) is not None]
      if hit:
         found.append(where)
         if write:
            holder[key] = WORD.sub(lambda x: fn(x.group(0)) or x.group(0), text)
   return found


def _methods_of(d: JsonDict) -> list[JsonDict]:
   """!The methods of the battle data as one dict.
   @param d  core.battle.merged()
   @return live method dicts
   """
   lst = d.get(METHODS_KEY)
   return [m for m in lst if isinstance(m, dict)] if isinstance(lst, list) else []


def _words(d: JsonDict, mapping: Mapping[str, str], write: bool) -> list[str]:
   """!Rewrites (or finds) exact words in every method's expressions.
   @param d        the battle data
   @param mapping  old word -> new word
   @param write    False to only look
   @return "where" strings
   """
   out = []
   for m in _methods_of(d):
      out += _rewrite_method(m, lambda w: mapping.get(w), m.get(NAME_KEY, ""), write)
   return out


def _suffix_words(d: JsonDict, old: str, new: str | None, prefixes_of: Callable[[JsonDict], list[str]]) -> list[str]:
   """!Rewrites (or finds) PREFIX.OLD words (a part after a slot role, cand or result) in every method.
   @param d            the battle data
   @param old          the part
   @param new          its new name, or None to only look
   @param prefixes_of  method -> the prefixes
   @return "where" strings
   """
   out = []
   for m in _methods_of(d):
      pre = set(prefixes_of(m))

      def fn(w: str, pre: set[str] = pre) -> str | None:
         """!One word."""
         head, _dot, tail = w.partition(".")
         return f"{head}.{new or tail}" if head in pre and tail == old else None
      out += _rewrite_method(m, fn, m.get(NAME_KEY, ""), new is not None)
   return out


def word_of(prefix_word: str, name: str) -> str:
   """!A species' or type's word (sp.NAME / type.NAME: the lower-case identifier).
   @param prefix_word  the engine's COMBINE_SPECIES_WORD or COMBINE_TYPE_WORD
   @param name         the name
   @return the word
   """
   return prefix_word + str(_bc().ident(name)).lower()


def follow_entry(d: JsonDict, kind: str, old: str, new: str | None) -> list[str]:
   """!A species' or type's rename (or, with None, its readers): recipes, results, table cells keyed by the type,
   type matchers and the words sp.NAME / type.NAME. A move's rename is core.battle's (the species' combine_moves).
   @param d     the battle data (core.battle.merged(); change it only inside an edit())
   @param kind  "species" or "types"
   @param old   the name
   @param new   its new name, or None to only look
   @return "where" strings
   """
   bc = _bc()
   found: list[str] = []
   if kind not in ("species", "types"):
      return found
   for m in _methods_of(d):
      mname = m.get(NAME_KEY)
      for k, r in enumerate(rules_of(m)):
         lst = r.get(RECIPE_KEY)
         for q, x in enumerate(lst if isinstance(lst, list) else []):
            if kind == "species" and x == old:
               found.append(f"{METHODS_KEY} {mname}: rule {k} recipe")
               if new is not None:
                  lst[q] = new
            if kind == "types" and isinstance(x, dict) and x.get(type_key()) == old:
               found.append(f"{METHODS_KEY} {mname}: rule {k} recipe")
               if new is not None:
                  x[type_key()] = new
         if kind == "species" and r.get(RESULT_KEY) == old:
            found.append(f"{METHODS_KEY} {mname}: rule {k} result")
            if new is not None:
               r[RESULT_KEY] = new
      if kind == "types":
         for tname, t in tables_of(m).items():
            if t.get(TABLE_KEY_KEY) != type_key():
               continue
            for c in t.get(CELLS_KEY) or []:
               if isinstance(c, list) and old in c:
                  found.append(f"{METHODS_KEY} {mname}: table {tname}")
                  if new is not None:
                     c[:] = [new if v == old else v for v in c]
   prefix = bc.COMBINE_SPECIES_WORD if kind == "species" else bc.COMBINE_TYPE_WORD
   found += _words(d, {word_of(prefix, old): word_of(prefix, new or old)}, new is not None)
   return found


def _part_prefixes(m: JsonDict) -> list[str]:
   """!The prefixes a species field or part follows: the slot roles, cand and result.
   @param m  the method
   @return prefixes
   """
   bc = _bc()
   return [*roles_of(m), bc.COMBINE_CANDIDATE, bc.COMBINE_RESULT]


def follow_species_field(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A species field's rename (or its readers): ROLE.FIELD / cand.FIELD / result.FIELD and FIELD.VALUE words, table
   keys, field matchers, pick orders.
   @param d    the battle data
   @param old  the field
   @param new  its new name, or None to only look
   @return "where" strings
   """
   found = _suffix_words(d, old, new, _part_prefixes)
   for m in _methods_of(d):
      mname = m.get(NAME_KEY)

      def value_word(w: str) -> str | None:
         """!FIELD.VALUE."""
         head, dot, tail = w.partition(".")
         return f"{new or old}.{tail}" if head == old and dot and head not in _part_prefixes(m) else None
      found += _rewrite_method(m, value_word, mname, new is not None)
      for tname, t in tables_of(m).items():
         if t.get(TABLE_KEY_KEY) == old:
            found.append(f"{METHODS_KEY} {mname}: table {tname} key")
            if new is not None:
               t[TABLE_KEY_KEY] = new
      for k, r in enumerate(rules_of(m)):
         for x in r.get(RECIPE_KEY) if isinstance(r.get(RECIPE_KEY), list) else []:
            if isinstance(x, dict) and old in x:
               found.append(f"{METHODS_KEY} {mname}: rule {k} recipe")
               if new is not None:
                  x[new] = x.pop(old)
         p = r.get(PICK_KEY)
         if isinstance(p, dict) and p.get(ORDER_KEY) == old:
            found.append(f"{METHODS_KEY} {mname}: rule {k} pick order")
            if new is not None:
               p[ORDER_KEY] = new
   return found


def follow_field_value(d: JsonDict, field: str, old: str, new: str | None) -> list[str]:
   """!A species field value name's rename (or its readers): FIELD.VALUE words, the cells of tables keyed by the
   field, field matchers.
   @param d      the battle data
   @param field  the field
   @param old    the value name
   @param new    its new name, or None to only look
   @return "where" strings
   """
   found = _words(d, {f"{field}.{old}": f"{field}.{new or old}"}, new is not None)
   for m in _methods_of(d):
      mname = m.get(NAME_KEY)
      for tname, t in tables_of(m).items():
         if t.get(TABLE_KEY_KEY) != field:
            continue
         for c in t.get(CELLS_KEY) or []:
            if isinstance(c, list) and old in c:
               found.append(f"{METHODS_KEY} {mname}: table {tname}")
               if new is not None:
                  c[:] = [new if v == old else v for v in c]
      for k, r in enumerate(rules_of(m)):
         for x in r.get(RECIPE_KEY) if isinstance(r.get(RECIPE_KEY), list) else []:
            if isinstance(x, dict) and x.get(field) == old:
               found.append(f"{METHODS_KEY} {mname}: rule {k} recipe")
               if new is not None:
                  x[field] = new
   return found


def follow_role(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A record role's rename (or its readers): ROLE.R (and its halves) after every slot role.
   @param d    the battle data
   @param old  the role
   @param new  its new name, or None to only look
   @return "where" strings
   """
   found = []
   for old_w, new_w in zip([old] + [old + s for s in HALF_SUFFIXES],
                           [new or old] + [(new or old) + s for s in HALF_SUFFIXES]):
      found += _suffix_words(d, old_w, new_w if new is not None else None, roles_of)
   return found


def follow_context(d: JsonDict, old: str, new: str | None) -> list[str]:
   """!A context value's (or one of its value names') rename (or its readers): the bare word.
   @param d    the battle data
   @param old  the name
   @param new  its new name, or None to only look
   @return "where" strings
   """
   return _words(d, {old: new or old}, new is not None)


def message_uses(doc: Document, key: str, new: str | None = None) -> list[str]:
   """!Finds (and renames) a battle message the methods show (core.messages: its uses, renames and refused removal).
   @param doc  any manifest Document of the battle (changes happen in the edit running on it)
   @param key  the message
   @param new  new key, or None to only look
   @return "where" strings ("combine_methods NAME: messages.MOMENT")
   """
   found = []
   for m in methods(doc):
      msgs = m.get(MESSAGES_KEY)
      for moment, value in list(msgs.items()) if isinstance(msgs, dict) else []:
         if value == key:
            found.append(f"{METHODS_KEY} {m.get(NAME_KEY)}: {MESSAGES_KEY}.{moment}")
            if new is not None:
               msgs[moment] = new
   return found


# -- previews ----------------------------------------------------------------------------------------------------------

def preview(project: BattleProject, name: str, records: Sequence[Mapping[str, Any]],
            context: Mapping[str, Any] | None = None) -> JsonDict:
   """!What a combination would give (the engine's Python mirror of combine::preview(): no random parts; a random
   pick gives its group), with the moves its sources would gather for the result.
   @param project  BattleProject
   @param name     method name
   @param records  the inputs: {"species", "level", roles, "moves"} (a test save's boxed creature works)
   @param context  context value name -> value or value name
   @return the engine's preview dict plus "moves" (the candidates) and "group_name" (a random pick's group)
   @throws DocumentError when the data does not compile or the method is unknown
   """
   compiled, error = project.compile()
   if compiled is None:
      raise DocumentError(f"the battle data does not compile: {error}")
   bc = _bc()
   recs = [{k: v for k, v in r.items() if k != "slot"} for r in records]
   try:
      out = dict(bc.combine_preview(compiled, name, recs, context))
      out["moves"] = bc.combine_move_candidates(compiled, name, out["species"], recs) if out["species"] else []
   except (bc.ManifestError, KeyError, ValueError) as e:
      raise DocumentError(str(e)) from None
   out["group_name"] = None
   if out.get("group") is not None and out.get("rule") is not None:
      _i, m = bc.combine_method_of(compiled, name)
      table = list(m["tables"].values())[m["rules"][out["rule"]]["table"]]
      names = key_values(project.structure, table["key"])
      out["group_name"] = names[out["group"]] if out["group"] < len(names) else str(out["group"])
   return out


def preview_text(p: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> str:
   """!A preview as a line ("A + B -> C (level 6)").
   @param p        preview()
   @param records  the inputs
   @return the text
   """
   head = " + ".join(f"{r.get(SPECIES_FIELD)} Lv {r.get(LEVEL_FIELD, 1)}" for r in records)
   if p["status"] != "ok":
      slot = f" (slot {p['slot']})" if p.get("slot") is not None else ""
      return f"{head} -> refused: {p['status']}{slot}"
   result = p["species"] if p["species"] is not None else f"a random member of {p.get('group_name')}"
   extra = f", fee {p['fee']}" if p.get("fee") else ""
   moves = f"; moves {', '.join(p['moves'])}" if p.get("moves") else ""
   return f"{head} -> {result} (level {p['level']}, rule {p['rule']}, odds {p['odds']}{extra}){moves}"


def species_names(doc: Document) -> list[str]:
   """!The battle's species (the preview's choices).
   @param doc  any manifest Document of the battle
   @return names
   """
   return [str(e.get("name")) for e in battle.entries(battle.content_doc(doc), "species") if isinstance(e, dict)]
