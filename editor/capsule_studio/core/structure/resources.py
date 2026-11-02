"""!The resources of battle data: the structure manifest's
"resources" list, every pool a battler spends or loses, in the order costs
are paid.

    "resources": [{"name": "hp", "label": "HP", "scope": "battler", "stat": "hp", "empty": "faint",
                   "persist": "current_hp"},
                  {"name": "pp", "label": "PP", "scope": "move", "base": "pp", "max": "pp_max",
                   "raises": "pp_ups", "persist": "pp"},
                  {"name": "ep", "label": "EP", "scope": "battler", "stat": "ep", "regen": 2}]

The engine's battlec/resources.py is the one authority (battle_compiler
re-exports SCOPES, EMPTY_RULES, STORAGE_MAX, ENGINE_STORAGE_ROLES,
FORMULA_ARGS, DEFAULT_COST, compile_resources(), pool_cap(),
resource_names()). In short:

- scope `battler`: one pool per battler; its maximum is a stat ("stat").
  Exactly one battler resource has "empty": "faint" (the pool stat's: the
  hit points).
- scope `move`: one pool per move slot; "base" names the move field every
  move states (no default), "max" a named ruleset formula of (base, raises)
  and "raises" the record role holding each slot's raises (needs "max").
- "persist": the record role the pool is kept in between battles (refilled
  at the start of every battle without one); "regen": an end-of-turn amount
  (a number or a named formula of (value, max)), run by the turn's "regen"
  end-of-turn phase (set_resource() adds that phase when the turn has none).
- a move's "cost" is {resource: amount} (a number or a named formula of
  (value, max)); a move without "cost" pays DEFAULT_COST of every move
  resource (cost_rows() shows that default). rules.fallback_move pays
  nothing and states no cost (set_cost() refuses it); a hit point cost must
  stay below the most hit points (paying never faints: the engine's
  check_costs()).

The caps are the engine's per platform (build_settings.PLATFORM_LIMITS
max_battler_resources / max_move_resources: hit points included) for every
target of the game. What follows a change: renaming a resource renames the
moves' cost keys, the move field it reads when that field is named after it,
and the effect logic naming it (`holder.resource(NAME)`, restore, raise);
the bench scenarios naming it follow too (core.bench.follow_rename() [the studio review];
bench_users() lists them).
Removing one is refused while a move's cost or effect logic names it (the
moves' base field of a move resource goes with it). Changing a move
resource's "base" renames that field in every move.

Each editing helper is one change: call it inside one battle.edit() (the
moves are in battle.json, the resources in structure.json: one undo step
takes both back). An edit that makes compiling resources stop compiling, or
battle data that compiled stop compiling (the engine's check_persist_roles():
a persist role narrower than its pool; check_costs(): a cost no pool can pay,
a cost on the fallback move; MAX_FORMULAS distinct resource formulas), is
refused with the engine's message.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import battle, engine, logic
from ..document import Document, DocumentError
from . import stats

## A parsed JSON object.
JsonDict = dict[str, Any]
## One resource as resource_rows() gives it.
ResourceRow = dict[str, Any]
## One target's resource budget: (platform, battler resources, most, move resources, most).
Budget = tuple[str, int, int, int, int]

## The structure manifest's resources list.
RESOURCES_KEY = "resources"
## Scope of a resource with one pool per battler.
BATTLER = "battler"
## Scope of a resource with one pool per move slot.
MOVE = "move"
## A move's cost.
COST_KEY = "cost"
## The empty rule that faints the battler (the hit points).
FAINT = "faint"
## The empty rule of every other resource (the engine's default).
NO_EMPTY = "none"
## Every key set_resource() changes (the name: rename_resource(); the scope: set_scope()).
RESOURCE_KEYS = ("label", "stat", "base", "max", "raises", "persist", "empty", "regen")
## Keys only a battler resource has.
BATTLER_ONLY = ("stat",)
## Keys only a move resource has.
MOVE_ONLY = ("base", "max", "raises")
## Key order of a resource as the studio writes it.
KEY_ORDER = ("name", "label", "scope", "stat", "base", "max", "raises", "persist", "empty", "regen")
## The effect compiler's structure list of the resources (`holder.resource(NAME)`, restore, raise).
RESOURCE_LISTS = ("resources",)
## The end-of-turn phase that applies the regen amounts (battlec END_PHASES).
REGEN_RUN = "regen"
## Location the compiler's messages name.
WHERE = "structure"
## A bench scenario's keys that hold resource values: members (record values) and pokes.
BENCH_KEYS = ("members", "pokes")
## The platform limit of each scope (build_settings.PLATFORM_LIMITS).
LIMIT_KEYS = {BATTLER: "max_battler_resources", MOVE: "max_move_resources"}
## The structure's transformation section and its record role holding the form (no resource's to take).
FORM_SECTION = "transformation"
## See FORM_SECTION.
FORM_ROLE = "form_role"


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def _res() -> Any:
   """!The engine's resources module (its name pattern, move fields and storage widths, which battle_compiler does
   not re-export).
   @return battlec.resources
   """
   return engine.tool("battlec.resources")


def scopes() -> list[str]:
   """!The resource scopes (the engine's SCOPES).
   @return names
   """
   return list(_bc().SCOPES)


def empty_rules() -> list[str]:
   """!What an empty pool may mean (the engine's EMPTY_RULES).
   @return names
   """
   return list(_bc().EMPTY_RULES)


def default_cost() -> int:
   """!What a move without "cost" pays of every move resource (the engine's DEFAULT_COST).
   @return amount
   """
   return int(_bc().DEFAULT_COST)


def regen_range() -> tuple[int, int]:
   """!The numbers a regen amount may be (the engine's REGEN_RANGE: ResourceData::regen is int16_t).
   @return (lowest, highest)
   """
   lo, hi = _bc().REGEN_RANGE
   return int(lo), int(hi)


def max_formulas() -> int:
   """!Most distinct resource formulas (max, regen and cost formulas together; the engine's MAX_FORMULAS).
   @return count
   """
   return int(_bc().MAX_FORMULAS)


def storage_max(scope: str) -> int:
   """!The highest value a pool of a scope holds (the engine's STORAGE_MAX).
   @param scope  BATTLER or MOVE
   @return the value
   """
   return int(_bc().STORAGE_MAX[scope])


def formula_args(use: str) -> list[str]:
   """!The arguments the engine passes a resource formula (the engine's FORMULA_ARGS).
   @param use  "max", "regen" or "cost"
   @return argument names, in order
   """
   return list(_bc().FORMULA_ARGS[use])


# -- reading ----------------------------------------------------------------------------------------------------------

def _listed(doc: Document) -> list[JsonDict]:
   """!The resources for reading (nothing created; entries that are not objects left out).
   @param doc  any manifest Document of the battle
   @return the live dicts
   """
   given = battle.data_of(doc, RESOURCES_KEY).get(RESOURCES_KEY)
   return [r for r in given if isinstance(r, dict)] if isinstance(given, list) else []


def _resources(doc: Document) -> list[Any]:
   """!The resources list for editing.
   @param doc  any manifest Document of the battle
   @return the live list (created when absent)
   """
   data = battle.data_of(doc, RESOURCES_KEY)
   if not isinstance(data.get(RESOURCES_KEY), list):
      data[RESOURCES_KEY] = []
   return data[RESOURCES_KEY]


def resource_names(doc: Document, scope: str | None = None) -> list[str]:
   """!The resources' names in order.
   @param doc    any manifest Document of the battle
   @param scope  BATTLER or MOVE to list only that scope, or None for every resource
   @return names
   """
   return [r["name"] for r in _listed(doc)
           if isinstance(r.get("name"), str) and (scope is None or r.get("scope") == scope)]


def resource_entry(doc: Document, name: str) -> JsonDict:
   """!A resource by name.
   @param doc   any manifest Document of the battle
   @param name  resource name
   @return the dict (live)
   @throws DocumentError when there is none
   """
   for r in _listed(doc):
      if r.get("name") == name:
         return r
   raise DocumentError(f"no resource {name!r} (resources: {', '.join(resource_names(doc)) or 'none'})")


def persist_roles(doc: Document) -> list[str]:
   """!The record roles the resources are persisted in (the engine fills them with full pools when it makes a
   record: no generation entry may set them).
   @param doc  any manifest Document of the battle
   @return role names, in resource order
   """
   return [r["persist"] for r in _listed(doc) if isinstance(r.get("persist"), str)]


def role_resources(doc: Document, role: str) -> list[str]:
   """!What of the resources names a record role.
   @param doc   any manifest Document of the battle
   @param role  role name
   @return "resource NAME persist" / "resource NAME raises" strings
   """
   return [f"resource {r.get('name')} {key}" for r in _listed(doc) for key in ("persist", "raises")
           if r.get(key) == role]


def rename_role(doc: Document, old: str, new: str) -> int:
   """!Follows a record role's rename (core.structure.record.rename_role()): the resources persisted in it or
   reading their raises from it name the new name.
   @param doc  any manifest Document of the battle
   @param old  the role's old name
   @param new  its new name
   @return keys changed
   """
   n = 0
   for r in _listed(doc):
      for key in ("persist", "raises"):
         if r.get(key) == old:
            r[key] = new
            n += 1
   return n


def _moves(doc: Document) -> list[JsonDict]:
   """!The moves (battle.json).
   @param doc  any manifest Document of the battle
   @return the live dicts
   """
   return battle.entries(doc, "moves")


def _stated_cost(move: JsonDict) -> JsonDict | None:
   """!A move's own "cost" object.
   @param move  move dict
   @return the live dict, or None when the move states none (it pays the default)
   """
   cost = move.get(COST_KEY)
   return cost if isinstance(cost, dict) else None


def cost_users(doc: Document, name: str) -> list[str]:
   """!The moves whose own "cost" names a resource (a move without "cost" pays the default and names none).
   @param doc   any manifest Document of the battle
   @param name  resource name
   @return "move NAME" strings
   """
   return [f"move {m.get('name')}" for m in _moves(doc) if name in (_stated_cost(m) or {})]


def payers(doc: Document, name: str) -> int:
   """!How many moves pay a resource (by their own cost or by the default).
   @param doc   any manifest Document of the battle
   @param name  resource name
   @return count
   """
   return sum(1 for m in _moves(doc) if cost_of(doc, m.get("name")).get(name))


def resource_rows(doc: Document) -> list[ResourceRow]:
   """!Every resource with its keys resolved as the engine resolves them.
   @param doc  any manifest Document of the battle
   @return copies in order: index, name, label (the name without one), scope, stat, base, max, raises, persist,
           empty (NO_EMPTY without one), regen (a number, a formula name or None), payers (moves paying it)
   """
   out = []
   for i, r in enumerate(_listed(doc)):
      name = r.get("name")
      out.append({"index": i, "name": name, "label": r.get("label", name), "scope": r.get("scope"),
                  "stat": r.get("stat"), "base": r.get("base"), "max": r.get("max"), "raises": r.get("raises"),
                  "persist": r.get("persist"), "empty": r.get("empty", NO_EMPTY), "regen": r.get("regen"),
                  "payers": payers(doc, name) if isinstance(name, str) else 0})
   return out


# -- limits -----------------------------------------------------------------------------------------------------------

def max_resources(scope: str, targets: list[str] | None = None) -> int:
   """!Most resources of a scope every target's engine holds (hit points included among the battler ones).
   @param scope    BATTLER or MOVE
   @param targets  platforms, or None for the default targets
   @return the smallest limit
   @throws DocumentError for an unknown platform
   """
   bs = engine.tool("build_settings")
   try:
      return min(bs.platform_limits(t)[LIMIT_KEYS[scope]] for t in (targets or stats.DEFAULT_TARGETS))
   except bs.SettingsError as e:
      raise DocumentError(str(e)) from None


def budget(doc: Document, targets: list[str] | None = None) -> list[Budget]:
   """!Resources used against each target's caps ("2/4 battler, 1/2 move gba").
   @param doc      any manifest Document of the battle
   @param targets  platforms, or None for the default targets
   @return [(platform, battler used, most, move used, most)] in target order
   """
   battler, move = len(resource_names(doc, BATTLER)), len(resource_names(doc, MOVE))
   return [(t, battler, max_resources(BATTLER, [t]), move, max_resources(MOVE, [t]))
           for t in (targets or stats.DEFAULT_TARGETS)]


# -- the engine's compile ---------------------------------------------------------------------------------------------

def _limits(targets: list[str] | None) -> dict[str, int]:
   """!The platform limits compile_resources() checks: the smallest of every target.
   @param targets  platforms, or None for the default targets
   @return {"max_battler_resources", "max_move_resources"}
   """
   return {LIMIT_KEYS[s]: max_resources(s, targets) for s in LIMIT_KEYS}


def compile_check(doc: Document, targets: list[str] | None = None) -> tuple[list[JsonDict] | None, str | None]:
   """!Compiles the resources with the engine's compile_resources() (with the stats, the record layout, the
   ruleset and the turn compiled as the battle compiler does).
   @param doc      any manifest Document of the battle
   @param targets  platforms whose caps apply, or None for the default targets
   @return (compiled resources or None, the compiler's message or None)
   """
   from . import progression, record, turn   # local: progression and record import this module
   bc = _bc()
   try:
      d = bc.strip(copy.deepcopy(battle.merged(doc)))   # without the editors' "editor" keys, as the compiler reads
      ruleset = progression._ruleset(doc)
      project = logic.project_of(doc)
      rs_name = project.ruleset.path.name if project is not None else battle.RULESET_FILE
      enc = bc.Texts(turn._page(doc))
      # the stats as any platform takes them (each target's stat limit is the Stats page's budget)
      most_stats = max(lim["max_stats"] for lim in engine.tool("build_settings").PLATFORM_LIMITS.values())
      compiled_stats = bc.compile_stats(copy.deepcopy(d.get("stats")), ruleset, rs_name, most_stats, WHERE, enc)
      layout, error = record.compile_record(doc)
      if layout is None:
         return None, f"the record layout does not compile: {error}"
      turn_rules = bc.compile_turn(copy.deepcopy(d.get("turn")), WHERE)
      return bc.compile_resources(copy.deepcopy(d.get(RESOURCES_KEY)), compiled_stats, layout, ruleset, rs_name,
                                  turn_rules, _limits(targets), WHERE, enc), None
   except Exception as e:   # ManifestError, DocumentError, type errors in odd data
      return None, str(e)


def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; when the resources (or the whole battle data: the persist roles' widths, the costs, the
   number of resource formulas are checked there) compiled before and do not after, refuses it with the
   compiler's message (raised inside battle.edit(), which puts the manifests back).
   @param doc     any manifest Document of the battle
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   targets = stats.project_targets(doc.path)
   project = logic.project_of(doc)
   _before, error_before = compile_check(doc, targets)
   whole_before = project.error_now() if project is not None else None
   result = change()
   if error_before is None:
      _after, error = compile_check(doc, targets)
      if error is not None:
         raise DocumentError(error)
   if project is not None and whole_before is None:
      error = project.error_now()
      if error is not None:
         raise DocumentError(error)
   return result


def pool_caps(doc: Document) -> dict[str, int]:
   """!The highest value each resource's pool holds (the engine's pool_cap(): storage, persist role, its stat's
   highest value when the battle data compiles, else the stat cap).
   @param doc  any manifest Document of the battle
   @return {name: cap} ({} when the resources do not compile)
   """
   from . import progression, record   # local: they import this module (see compile_check())
   project = logic.project_of(doc)
   whole = project.compile()[0] if project is not None else None
   if whole is not None:   # the stats' analysed bounds (a battler pool reaches its stat's highest value)
      return {r["name"]: int(_bc().pool_cap(r, whole["layout"], whole["rules"]["stat_cap"], whole["stats"]))
              for r in whole["resources"]}
   compiled, _error = compile_check(doc)
   layout = record.compile_record(doc)[0]
   if compiled is None or layout is None:
      return {}
   stat_cap = progression._rules(doc)["stat_cap"]
   return {r["name"]: int(_bc().pool_cap(r, layout, stat_cap)) for r in compiled}


# -- choices ----------------------------------------------------------------------------------------------------------

def formula_choices(doc: Document) -> list[str]:
   """!The ruleset's named formulas of two arguments (what "max", "regen" and a cost may name).
   @param doc  any manifest Document of the battle
   @return names
   """
   project = logic.project_of(doc)
   if project is None:
      return []
   formulas = project.ruleset.data.get("formulas")
   pair = len(formula_args("cost"))
   return [n for n, f in (formulas.items() if isinstance(formulas, dict) else [])
           if isinstance(f, dict) and isinstance(f.get("args"), list) and len(f["args"]) == pair]


def stat_choices(doc: Document) -> list[str]:
   """!The stats a battler resource may take as its maximum.
   @param doc  any manifest Document of the battle
   @return names, in record order
   """
   return battle.stat_keys(doc)


def pool_stat(doc: Document) -> str | None:
   """!The pool stat (the faint resource's stat: hit points).
   @param doc  any manifest Document of the battle
   @return its name, or None when no stat is the pool stat
   """
   given = battle.data_of(doc, "stats").get("stats")
   return next((st.get("name") for st in given if isinstance(st, dict) and st.get("pool") is True), None) \
      if isinstance(given, list) else None


def role_choices(doc: Document, scope: str, current: str | None = None) -> list[str]:
   """!The record roles a resource of a scope may be persisted in or read its raises from: the engine's storage
   roles of that scope (ENGINE_STORAGE_ROLES) and the custom roles, held by the layout with one element (a battler
   resource) or one per move slot (a move resource) and narrow enough for the pool, and no other resource's.
   @param doc      any manifest Document of the battle
   @param scope    BATTLER or MOVE
   @param current  the resource asking (its own roles are offered), or None
   @return role names, in record order
   """
   from . import record   # local: record imports this module
   want = record.move_slots(doc) if scope == MOVE else 1
   bits = _res().STORAGE_ROLE_BITS[scope]
   taken = {role for r in _listed(doc) if r.get("name") != current for role in (r.get("persist"), r.get("raises"))}
   # The role holding the form is the transformation's (Structure > Growth & training)
   growth = battle.data_of(doc, FORM_SECTION).get(FORM_SECTION)
   if isinstance(growth, dict):
      taken.add(growth.get(FORM_ROLE))
   storage = _bc().ENGINE_STORAGE_ROLES
   out = []
   for row in record.role_rows(doc):
      engine_role = row["kind"] == record.KIND_ENGINE and storage.get(row["name"]) == scope
      fits = row["count"] == want and isinstance(row["width"], int) and row["width"] <= bits
      if (engine_role or row["kind"] == record.KIND_CUSTOM) and fits and row["name"] not in taken:
         out.append(row["name"])
   return out


# -- checks -----------------------------------------------------------------------------------------------------------

def _check_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A resource name the engine takes and no other resource has.
   @param doc      any manifest Document of the battle
   @param name     wanted name
   @param current  the resource being renamed (its own name is fine), or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   name = name.strip() if isinstance(name, str) else name
   if not isinstance(name, str) or not _res().RESOURCE_NAME.match(name):
      raise DocumentError(f"a resource name is a lower-case identifier (got {name!r})")
   if name != current and name in resource_names(doc):
      raise DocumentError(f"there is already a resource {name!r}")
   return name


def _check_base(doc: Document, field: Any, current: str | None = None) -> str:
   """!A move field a move resource may read its base from.
   @param doc      any manifest Document of the battle
   @param field    wanted field name
   @param current  the resource asking, or None
   @return the field (stripped)
   @throws DocumentError when it is not one
   """
   res = _res()
   field = field.strip() if isinstance(field, str) else field
   if not isinstance(field, str) or not res.RESOURCE_NAME.match(field) or field in res.MOVE_FIELDS:
      raise DocumentError(f"a base is a move field: a lower-case identifier that is none of the move's own fields "
                          f"({', '.join(sorted(res.MOVE_FIELDS - {'editor'}))}); got {field!r}")
   other = next((r.get("name") for r in _listed(doc) if r.get("base") == field and r.get("name") != current), None)
   if other is not None:
      raise DocumentError(f"the resource {other!r} reads the move field {field!r} already")
   return field


def _check_formula(doc: Document, name: Any, use: str) -> str:
   """!A named ruleset formula of the arguments a use passes.
   @param doc   any manifest Document of the battle
   @param name  formula name
   @param use   "max", "regen" or "cost"
   @return the name
   @throws DocumentError when the ruleset has no such formula
   """
   choices = formula_choices(doc)
   if not isinstance(name, str) or name not in choices:
      raise DocumentError(f"a {use} formula is a named formula of the ruleset with \"args\" "
                          f"({', '.join(formula_args(use))}); named formulas of two args: "
                          f"{', '.join(choices) or 'none'}")
   return name


def _check_amount(doc: Document, value: Any, use: str, lo: int, hi: int) -> int | str:
   """!A regen or cost amount: a whole number in range or a named formula.
   @param doc    any manifest Document of the battle
   @param value  the amount (an int, a formula name, or a numeric text)
   @param use    "regen" or "cost"
   @param lo     lowest number
   @param hi     highest number
   @return the number or the formula name
   @throws DocumentError when it is neither
   """
   if isinstance(value, str):
      text = value.strip()
      try:
         value = int(text)
      except ValueError:
         return _check_formula(doc, text, use)
   if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
      raise DocumentError(f"a {use} amount is a whole number from {lo} to {hi} or a named formula (got {value!r})")
   return value


def _ordered(r: JsonDict) -> JsonDict:
   """!A resource's keys in KEY_ORDER (unknown keys after them, as they were).
   @param r  resource dict
   @return a new dict
   """
   return {**{k: r[k] for k in KEY_ORDER if k in r}, **{k: v for k, v in r.items() if k not in KEY_ORDER}}


def _replace(doc: Document, r: JsonDict) -> None:
   """!Writes a resource's keys back in KEY_ORDER (the same dict object stays in the list).
   @param doc  any manifest Document of the battle
   @param r    the live resource dict
   @return None
   """
   ordered = _ordered(r)
   r.clear()
   r.update(ordered)


# -- editing (inside battle.edit()) -----------------------------------------------------------------------------------

def _free_stat(doc: Document) -> str | None:
   """!A stat no battler resource names (the first such stat that is not the pool stat).
   @param doc  any manifest Document of the battle
   @return its name, or None
   """
   used = {r.get("stat") for r in _listed(doc)}
   pool = pool_stat(doc)
   return next((s for s in stat_choices(doc) if s not in used and s != pool), None)


def _set_bases(doc: Document, field: str, value: int | None = None, old: str | None = None) -> None:
   """!Gives every move a base field (keeping a value it has), or renames / drops one.
   @param doc    any manifest Document of the battle
   @param field  the field to write, or "" with @p old to drop @p old
   @param value  the value moves without the field get, or None to only rename / drop
   @param old    a field to rename to @p field (or drop), or None
   @return None
   """
   for m in _moves(doc):
      if old is not None and old in m:
         # renamed in place (the field keeps its position), or dropped
         items = [(field, v) if k == old else (k, v) for k, v in m.items() if k != old or field]
         m.clear()
         m.update(items)
      elif field and value is not None and field not in m:
         m[field] = value


def add_resource(doc: Document, name: str, scope: str, label: str | None = None, stat: str | None = None,
                 base: str | None = None, index: int | None = None, targets: list[str] | None = None) -> int:
   """!Adds a resource (refilled every battle, nothing empty-specific, no regen). A move resource's base field is
   written into every move (battle.NEW_RESOURCE_BASE); moves without their own cost pay DEFAULT_COST of it.
   @param doc      any manifest Document of the battle
   @param name     resource name (lower-case identifier)
   @param scope    BATTLER or MOVE
   @param label    in-game text, or None for the name
   @param stat     a battler resource's maximum stat, or None for the first stat no resource names (not the pool
                   stat)
   @param base     a move resource's base field, or None for its name
   @param index    position (the payment order), or None for the end
   @param targets  platforms whose caps apply, or None for the game's targets
   @return its index
   @throws DocumentError for a bad name, scope, stat or base, or a full scope
   """
   name = _check_name(doc, name)
   if scope not in scopes():
      raise DocumentError(f"a resource's scope is one of {', '.join(scopes())} (got {scope!r})")
   targets = targets or stats.project_targets(doc.path)
   most = max_resources(scope, targets)
   if len(resource_names(doc, scope)) >= most:
      raise DocumentError(f"at most {most} {scope} resources on {', '.join(targets)}")
   r: JsonDict = {"name": name, "label": label.strip() if isinstance(label, str) and label.strip() else name,
                  "scope": scope}
   if scope == BATTLER:
      stat = stat if stat is not None else _free_stat(doc)
      if stat not in stat_choices(doc):
         raise DocumentError(f"a battler resource's maximum is a stat ({', '.join(stat_choices(doc))}); "
                             f"got {stat!r} (add the stat on the Stats page first)")
      r["stat"] = stat
   else:
      r["base"] = _check_base(doc, base if base is not None else name)

   def change() -> int:
      """!Inserts the resource and the moves' base field.
      @return its index
      """
      lst = _resources(doc)
      at = len(lst) if index is None else max(0, min(len(lst), int(index)))
      lst.insert(at, r)
      if scope == MOVE:
         _set_bases(doc, r["base"], battle.NEW_RESOURCE_BASE)
      return at

   return _guarded(doc, change)


def remove_resource(doc: Document, name: str) -> None:
   """!Removes a resource (a move resource's base field goes from every move). Refused for the faint resource and
   while a move's own cost or effect logic names it.
   @param doc   any manifest Document of the battle
   @param name  resource name
   @return None
   """
   r = resource_entry(doc, name)
   if r.get("empty") == FAINT:
      raise DocumentError(f"{name} is the faint resource (hit points): every battle needs it")
   users = cost_users(doc, name) + logic.per_owner(logic.references(doc, RESOURCE_LISTS, name))
   if users:
      raise DocumentError(f"resource {name!r} is still used by: {', '.join(users[:battle.REFERENCES_SHOWN])}")

   def change() -> None:
      """!Drops the resource and its moves' base field.
      @return None
      """
      if r.get("scope") == MOVE and isinstance(r.get("base"), str):
         _set_bases(doc, "", old=r["base"])
      _resources(doc).remove(r)

   before = battle.ruleset_problem(doc)
   _guarded(doc, change)
   battle.check_ruleset_kept(doc, f"resource {name!r}", before)   # the ruleset's pipelines / points may need it


def move_resource(doc: Document, name: str, delta: int) -> bool:
   """!Moves a resource up or down the list (the order costs are paid in; its pool's index in its scope).
   @param doc    any manifest Document of the battle
   @param name   resource name
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   lst = _resources(doc)
   i = lst.index(resource_entry(doc, name))
   j = i + delta
   if not 0 <= j < len(lst):
      return False

   def change() -> None:
      """!Swaps the two entries.
      @return None
      """
      lst[i], lst[j] = lst[j], lst[i]

   _guarded(doc, change)
   return True


def _rename_cost_key(cost: JsonDict, old: str, new: str) -> None:
   """!Renames a key of a cost object in place, keeping its position.
   @param cost  the live cost dict
   @param old   current key
   @param new   new key
   @return None
   """
   items = [(new if k == old else k, v) for k, v in cost.items()]
   cost.clear()
   cost.update(items)


def rename_resource(doc: Document, old: str, new: str) -> int:
   """!Renames a resource; the moves' costs, the move field a move resource reads when it is named after the
   resource, the effect logic naming it and the bench scenarios follow (core.bench.follow_rename(); bench_users()
   lists the scenarios naming it).
   @param doc  any manifest Document of the battle
   @param old  current name
   @param new  new name
   @return references updated (costs, base fields renamed in moves, logic owners)
   """
   r = resource_entry(doc, old)
   new = _check_name(doc, new, old)
   if new == old:
      return 0
   follow_base = r.get("scope") == MOVE and r.get("base") == old
   if follow_base:
      _check_base(doc, new, old)
   costs = [_stated_cost(m) for m in _moves(doc) if old in (_stated_cost(m) or {})]

   refs: list[str] = []

   def change() -> None:
      """!Writes the new name where it is named (the effect logic too, so the guard compiles the renamed data).
      @return None
      """
      r["name"] = new
      for cost in costs:
         _rename_cost_key(cost, old, new)
      if follow_base:
         r["base"] = new
         _set_bases(doc, new, old=old)
      refs.extend(logic.per_owner(logic.references(doc, RESOURCE_LISTS, old, new, "Rename resource")))

   _guarded(doc, change)
   bases = sum(1 for m in _moves(doc) if new in m) if follow_base else 0
   return len(costs) + bases + len(refs)


def _faint_resource(doc: Document) -> JsonDict | None:
   """!The resource with "empty": "faint".
   @param doc  any manifest Document of the battle
   @return the live dict, or None
   """
   return next((r for r in _listed(doc) if r.get("empty") == FAINT), None)


def set_scope(doc: Document, name: str, scope: str) -> bool:
   """!Changes a resource's scope: the keys of the other scope go (its persist role too: its element count no
   longer fits), the new scope's are filled in (a stat no resource names; the name as the base field, written
   into every move). Refused for the faint resource.
   @param doc    any manifest Document of the battle
   @param name   resource name
   @param scope  BATTLER or MOVE
   @return True when it changed
   """
   r = resource_entry(doc, name)
   if scope not in scopes():
      raise DocumentError(f"a resource's scope is one of {', '.join(scopes())} (got {scope!r})")
   if r.get("scope") == scope:
      return False
   if r.get("empty") == FAINT:
      raise DocumentError(f"{name} is the faint resource: it is a battler resource")
   most = max_resources(scope)
   if len(resource_names(doc, scope)) >= most:
      raise DocumentError(f"at most {most} {scope} resources")
   stat = _free_stat(doc) if scope == BATTLER else None
   if scope == BATTLER and stat is None:
      raise DocumentError("every stat is another resource's maximum (or the pool stat): add a stat first")
   base = _check_base(doc, name, name) if scope == MOVE else None

   def change() -> None:
      """!Swaps the scope's keys.
      @return None
      """
      old_base = r.get("base")
      for key in BATTLER_ONLY + MOVE_ONLY + ("persist",):
         r.pop(key, None)
      r["scope"] = scope
      if scope == BATTLER:
         r["stat"] = stat
         if isinstance(old_base, str):
            _set_bases(doc, "", old=old_base)
      else:
         r["base"] = base
         _set_bases(doc, base, battle.NEW_RESOURCE_BASE)
      _replace(doc, r)

   _guarded(doc, change)
   return True


def _ensure_regen_phase(doc: Document) -> None:
   """!Adds the turn's regen end-of-turn phase when it has none (a regen amount needs it).
   @param doc  any manifest Document of the battle
   @return None
   """
   from . import turn   # local: turn imports the record module, which imports this one
   if not any(row["run"] == REGEN_RUN for row in turn.phase_rows(doc)):
      turn.add_phase(battle.structure_doc(doc), REGEN_RUN)


def set_resource(doc: Document, name: str, key: str, value: Any) -> None:
   """!Changes one key of a resource (None puts the default back: the name as the label, no max / raises /
   persist / regen, NO_EMPTY).
   @param doc    any manifest Document of the battle
   @param name   resource name
   @param key    one of RESOURCE_KEYS
   @param value  label: text; stat: a stat; base: a move field (renamed in every move); max: a named formula;
                 raises / persist: a record role (role_choices()); empty: one of empty_rules() (faint takes it off
                 the other resource); regen: a number or a named formula (the turn gets a regen phase)
   @return None
   """
   r = resource_entry(doc, name)
   if key not in RESOURCE_KEYS:
      raise DocumentError(f"unknown resource key {key!r} (keys: {', '.join(RESOURCE_KEYS)}; the name: rename, the "
                          "scope: scope)")
   scope = r.get("scope")
   if value is not None and ((key in BATTLER_ONLY and scope != BATTLER) or (key in MOVE_ONLY and scope != MOVE)):
      raise DocumentError(f"only a {BATTLER if key in BATTLER_ONLY else MOVE} resource has a {key}")
   after: Callable[[], None] | None = None
   if key == "label":
      if value is not None and (not isinstance(value, str) or not value.strip()):
         raise DocumentError("label: a non-empty text")
      value = value.strip() if value is not None else name
   elif key == "stat":
      if value not in stat_choices(doc):
         raise DocumentError(f"stat: one of {', '.join(stat_choices(doc))}")
      if r.get("empty") == FAINT and value != pool_stat(doc):
         raise DocumentError(f"{name} is the faint resource: its maximum is the pool stat ({pool_stat(doc)})")
   elif key == "base":
      if value is None:
         raise DocumentError("a move resource always reads a base field")
      value = _check_base(doc, value, name)
      old = r.get("base")
      after = (lambda: _set_bases(doc, value, battle.NEW_RESOURCE_BASE, old if isinstance(old, str) else None))
   elif key == "max":
      if value is None and r.get("raises") is not None:
         raise DocumentError(f"{name}'s raises change its max formula: take the raises off first")
      value = _check_formula(doc, value, "max") if value is not None else None
   elif key in ("raises", "persist"):
      value = _check_role(doc, r, key, value)
   elif key == "empty":
      value = _check_empty(doc, r, value)
      if value == FAINT:
         other = _faint_resource(doc)
         after = (lambda: other.pop("empty", None)) if other is not None and other is not r else None
   elif key == "regen" and value is not None:
      lo, hi = regen_range()
      value = _check_amount(doc, value, "regen", lo, hi)
      after = (lambda: _ensure_regen_phase(doc))

   def change() -> None:
      """!Writes the key (or drops it for the default).
      @return None
      """
      if value is None or (key == "empty" and value == NO_EMPTY) or (key == "label" and value == name):
         r.pop(key, None)
      else:
         r[key] = value
      _replace(doc, r)
      if after is not None:
         after()

   _guarded(doc, change)


def _check_role(doc: Document, r: JsonDict, key: str, value: Any) -> str | None:
   """!A raises or persist role.
   @param doc    any manifest Document of the battle
   @param r      the resource
   @param key    "raises" or "persist"
   @param value  role name or None
   @return the role, or None
   @throws DocumentError when the resource may not name it
   """
   from . import progression   # local: progression imports this module
   if value is None:
      return None
   if key == "raises" and r.get("max") is None:
      raise DocumentError(f"raises only change a max formula of ({', '.join(formula_args('max'))}): give "
                          f"{r.get('name')} a max formula first")
   choices = role_choices(doc, r.get("scope"), r.get("name"))
   if value not in choices:
      raise DocumentError(f"{key}: a record role of the layout fitting a {r.get('scope')} pool and no other "
                          f"resource's ({', '.join(choices) or 'none: add one on the Record page'})")
   if key == "persist" and progression.fillers(doc, value):
      raise DocumentError(f"the generation list sets {value!r}; a persisted pool's role is filled by the engine "
                          f"(remove those entries on the Progression page first)")
   return value


def _check_empty(doc: Document, r: JsonDict, value: Any) -> str:
   """!An empty rule.
   @param doc    any manifest Document of the battle
   @param r      the resource
   @param value  one of empty_rules(), or None (NO_EMPTY)
   @return the rule
   @throws DocumentError when the resource may not take it
   """
   value = NO_EMPTY if value is None else value
   if value not in empty_rules():
      raise DocumentError(f"empty: one of {', '.join(empty_rules())}")
   if value == FAINT and (r.get("scope") != BATTLER or r.get("stat") != pool_stat(doc)):
      raise DocumentError(f"only a battler resource on the pool stat ({pool_stat(doc)}) faints its battler")
   if value != FAINT and r.get("empty") == FAINT:
      raise DocumentError(f"{r.get('name')} is the faint resource: make another resource the faint one instead")
   return value


# -- move costs and bases (battle.json) -------------------------------------------------------------------------------

def default_cost_of(doc: Document) -> JsonDict:
   """!What a move without "cost" pays: DEFAULT_COST of every move resource.
   @param doc  any manifest Document of the battle
   @return {resource: amount}
   """
   return {name: default_cost() for name in resource_names(doc, MOVE)}


def cost_of(doc: Document, move: Any) -> JsonDict:
   """!What a move pays, resolved (its own cost, or the default).
   @param doc   any manifest Document of the battle
   @param move  move name
   @return {resource: amount or formula name}, in resource order, zero amounts left out
   """
   m = next((e for e in _moves(doc) if e.get("name") == move), None)
   stated = _stated_cost(m) if m is not None else None
   given = stated if stated is not None else default_cost_of(doc)
   return {n: given[n] for n in resource_names(doc) if given.get(n) not in (None, 0)}


def fallback_move(doc: Document) -> str | None:
   """!The move that runs when no move can be paid (rules.fallback_move: it pays nothing).
   @param doc  any manifest Document of the battle
   @return its name, or None
   """
   rules = battle.data_of(doc, "rules").get("rules")
   name = rules.get("fallback_move") if isinstance(rules, dict) else None
   return name if isinstance(name, str) else None


def cost_rows(doc: Document, move: str) -> list[JsonDict]:
   """!A move's cost of each resource, as the Moves page shows it.
   @param doc   any manifest Document of the battle
   @param move  move name
   @return [{"resource", "scope", "amount" (a number or a formula name), "default" (True when the move states no
           cost: the amount is the engine's default), "fallback" (True for rules.fallback_move: it pays nothing,
           amount 0)}] in resource order
   """
   m = battle.entry(doc, "moves", move)
   stated = _stated_cost(m)
   given = stated if stated is not None else default_cost_of(doc)
   fallback = move == fallback_move(doc)
   return [{"resource": r["name"], "scope": r["scope"], "amount": 0 if fallback else given.get(r["name"], 0),
            "default": stated is None, "fallback": fallback} for r in resource_rows(doc)]


def set_cost(doc: Document, move: str, resource: str, amount: Any) -> None:
   """!Sets what a move pays of a resource (the move states its whole cost from then on; a cost equal to the
   default is dropped again, so the move pays the default).
   @param doc       any manifest Document of the battle
   @param move      move name
   @param resource  resource name
   @param amount    a whole number (0: free), a named formula of (value, max), or None for the default (DEFAULT_COST
                    of a move resource, nothing of a battler resource)
   @return None
   """
   m = battle.entry(doc, "moves", move)
   r = resource_entry(doc, resource)
   if move == fallback_move(doc):
      raise DocumentError(f"{move} is rules.fallback_move: it pays nothing, so it states no cost")
   if amount is None:
      amount = default_cost() if r.get("scope") == MOVE else 0
   else:
      amount = _check_amount(doc, amount, "cost", 0, storage_max(r.get("scope")))
   if r.get("empty") == FAINT and isinstance(amount, int):
      top = pool_caps(doc).get(resource)
      if top is not None and amount >= top:
         raise DocumentError(f"a {resource} cost must stay below the most {resource} ({top}): paying never faints "
                             f"the user")
   cost = dict(_stated_cost(m) if _stated_cost(m) is not None else default_cost_of(doc))
   cost[resource] = amount

   def change() -> None:
      """!Writes the cost (in resource order, free resources left out; an empty object: the move pays nothing).
      @return None
      """
      written = {n: cost[n] for n in resource_names(doc) if cost.get(n) not in (None, 0)}
      written.update({k: v for k, v in cost.items() if k not in resource_names(doc)})   # kept: the compiler names them
      if written == default_cost_of(doc):
         m.pop(COST_KEY, None)
      else:
         m[COST_KEY] = written

   _guarded(doc, change)


def reset_cost(doc: Document, move: str) -> bool:
   """!Drops a move's own cost (it pays the default).
   @param doc   any manifest Document of the battle
   @param move  move name
   @return True when it had one
   """
   return battle.entry(doc, "moves", move).pop(COST_KEY, None) is not None


def base_rows(doc: Document, move: str) -> list[JsonDict]:
   """!A move's base of each move resource.
   @param doc   any manifest Document of the battle
   @param move  move name
   @return [{"resource", "field", "value" (None when the move does not state it)}] in resource order
   """
   m = battle.entry(doc, "moves", move)
   return [{"resource": r["name"], "field": r["base"], "value": m.get(r["base"])}
           for r in resource_rows(doc) if r["scope"] == MOVE and isinstance(r["base"], str)]


# -- bench scenarios --------------------------------------------------------------------------------------------------

def bench_users(doc: Document, name: str) -> list[str]:
   """!The bench scenarios whose members or pokes set a resource (a rename leaves them as they are; the bench's
   check names them).
   @param doc   any manifest Document of the battle
   @param name  resource name
   @return "bench FILE party P member M" / "bench FILE poke K" strings
   """
   from .. import bench   # local: core.bench imports the battle modules
   project = logic.project_of(doc)
   if project is None:
      return []
   out = []
   for path in bench.scenario_paths(project):
      try:
         data = json.loads(Path(path).read_text(encoding="utf-8"))
      except (OSError, ValueError):
         continue
      rel = bench.relative_name(project, path)
      parties = data.get("parties") if isinstance(data, dict) else None
      for p, party in enumerate(parties if isinstance(parties, list) else []):
         members = party.get("members") if isinstance(party, dict) else None
         for k, member in enumerate(members if isinstance(members, list) else []):
            if isinstance(member, dict) and name in (member.get(RESOURCES_KEY) or {}):
               out.append(f"bench {rel} party {p} member {k}")
      pokes = data.get("pokes") if isinstance(data, dict) else None
      for k, poke in enumerate(pokes if isinstance(pokes, list) else []):
         if isinstance(poke, dict) and name in (poke.get(RESOURCES_KEY) or {}):
            out.append(f"bench {rel} poke {k}")
   return out


# -- text -------------------------------------------------------------------------------------------------------------

def row_text(row: ResourceRow) -> str:
   """!One resource as a line (the CLI's `resource list`).
   @param row  resource_rows() row
   @return text
   """
   parts = [f"{row['scope']}"]
   if row["scope"] == BATTLER:
      parts.append(f"stat {row['stat']}")
   else:
      parts.append(f"base {row['base']}")
      if row["max"] is not None:
         parts.append(f"max {row['max']}")
      if row["raises"] is not None:
         parts.append(f"raises {row['raises']}")
   parts.append(f"persist {row['persist']}" if row["persist"] is not None else "refilled each battle")
   if row["empty"] != NO_EMPTY:
      parts.append(f"empty {row['empty']}")
   if row["regen"] is not None:
      parts.append(f"regen {row['regen']}")
   parts.append(f"{row['payers']} move(s) pay it")
   return f"{row['index']} {row['name']}: {json.dumps(row['label'])} " + ", ".join(parts)


def formula_count(doc: Document) -> int:
   """!How many distinct resource formulas the data names (the resources' max / regen formulas and the moves' cost
   formulas: the engine numbers them, at most max_formulas()).
   @param doc  any manifest Document of the battle
   @return count
   """
   names = {r.get(k) for r in _listed(doc) for k in ("max", "regen") if isinstance(r.get(k), str)}
   for m in _moves(doc):
      cost = _stated_cost(m)
      names |= {v for v in (cost or {}).values() if isinstance(v, str)}
   return len(names)


def lines(doc: Document, targets: list[str] | None = None) -> list[str]:
   """!The resources as text lines: one per resource, then each target's budget.
   @param doc      any manifest Document of the battle
   @param targets  platforms, or None for the default targets
   @return lines
   """
   out = [row_text(r) for r in resource_rows(doc)]
   for t, battler, most_b, move, most_m in budget(doc, targets):
      out.append(f"{battler}/{most_b} battler, {move}/{most_m} move {t}")
   out.append(f"{formula_count(doc)}/{max_formulas()} resource formulas")
   return out
