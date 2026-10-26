"""!The stages of battle data (D-22 A7, D-23 §3.2 "Stages"): the battle
manifest's "stages" list, edited stage by stage.

    "stages": [{"name": "accuracy", "kind": "accuracy", "label": "accuracy", "range": [-6, 6],
                "table": [[3, 9], ..., [9, 3]]},
               {"name": "evasion", "kind": "evasion", "label": "evasiveness", "range": [-6, 6]},
               {"name": "critical", "kind": "crit", "label": "focus", "range": [0, 4],
                "table": ["1/16", "1/8", "1/4", "1/3", "1/2"]},
               {"stat": "attack", "range": [-6, 6], "table": [[2, 8], ..., [8, 2]]}, ...]

A stage's place in the list is its index (Battler::stages). Its kind is
"stat" (the default when it names a stat: that stat's stage, any stat but
the pool stat, at most one each) or "accuracy", "evasion" or "crit" (at most
one each). Its name is what effect code writes (`stage target atk -1;`;
a stat's stage defaults to the stat's name), its label the in-game text (a
stat's stage defaults to the stat's label). range [lo, hi] (lo <= 0 <= hi,
within the engine's STAGE_LIMIT) is required. A stage scales by a table
(hi - lo + 1 entries from stage lo: [num, den] multipliers, or odds such as
"1/16" for the crit stage), by a named ruleset formula of two arguments
(the value and the stage value; not for the crit stage), or not at all (x1).
The engine's battle compiler (battlec/stats.py compile_stages()) is the
authority; the helpers here refuse what it refuses where they can say why
earlier.

Each editing helper is one change: call it inside one battle.edit() and
Undo takes the whole change back. A rename follows the effect logic that
names the stage (core.logic, through the AST of the .ceffect sources; the
source edits join the battle edit's undo step).

migrate() turns pre-E6a data (rules.stat_stages / accuracy_stages /
crit_odds, "stage_names", a stat's "stage" flag) into the stages list.
"""
from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING, Any

from .. import battle, engine, logic
from ..document import Document, DocumentError

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]
## One stage as stage_list() gives it (see stage_list()).
StageRow = dict[str, Any]
## One preview row: (stage value, the multiplier or odds as text, the scaled value or the odds in percent).
PreviewRow = tuple[int, str, str]

## The battle manifest's stages list.
STAGES_KEY = "stages"
## Keys of a stage entry (the engine's battlec stats register_keys "stage").
STAGE_KEYS = ("name", "kind", "stat", "label", "range", "table", "formula")
## Properties set_stage() changes (the name: rename_stage(); the kind is fixed: remove and add instead).
STAGE_PROPERTIES = ("label", "stat", "range", "table", "formula")
## A stage that scales by its table.
TABLE_MODE = "table"
## A stage that scales by a named formula.
FORMULA_MODE = "formula"
## A stage that does not scale (x1).
NO_MODE = "none"
## How a stage scales: by its table, by a named formula, or not at all.
MODES = (TABLE_MODE, FORMULA_MODE, NO_MODE)
## Kind of a stat's stage.
STAT_KIND = "stat"
## Kind of the critical-hit stage (its table holds odds).
CRIT_KIND = "crit"
## Numbers in a [num, den] multiplier and in a [lo, hi] range.
PAIR = 2
## Multiplier of a new table entry: x1.
IDENTITY = [1, 1]
## Odds of a new crit table entry: never.
NEVER = "0/1"
## A multiplier or odds typed as text: "3/2", "1/16".
FRACTION = re.compile(r"\s*(?P<num>\d+)\s*/\s*(?P<den>\d+)\s*")
## Value the preview scales.
PREVIEW_VALUE = 100
## Percent of a whole (crit odds in the preview).
PERCENT = 100
## Decimals of a multiplier or a percentage in the preview.
PREVIEW_DECIMALS = 2
## Old keys migrate() reads: rules.KEY -> stage kind whose table it was.
OLD_RULES = {"stat_stages": STAT_KIND, "accuracy_stages": "accuracy", "crit_odds": CRIT_KIND}
## Old fixed stages in their pre-E6a order (stage_names keys) with their kinds.
OLD_FIXED = (("accuracy", "accuracy"), ("evasion", "evasion"), ("critical", CRIT_KIND))
## The pre-E6a "stage_names" object.
OLD_NAMES_KEY = "stage_names"
## A pre-E6a stat's stage flag.
OLD_STAT_FLAG = "stage"


## The pre-E6a engine's fixed stat, accuracy and evasion stage range (migrate()).
OLD_STAGE_RANGE = (-6, 6)
## The pre-E6a engine's fixed crit stage range (migrate()).
OLD_CRIT_RANGE = (0, 4)

def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def _rc() -> Any:
   """!The engine's ruleset compiler.
   @return module
   """
   return engine.tool("ruleset_compiler")


def kinds() -> list[str]:
   """!The stage kinds the engine has (battlec STAGE_KINDS).
   @return names
   """
   return list(_bc().STAGE_KINDS)


def single_kinds() -> list[str]:
   """!The kinds a battle has at most one stage of.
   @return names
   """
   return list(_bc().SINGLE_STAGE_KINDS)


def stage_limit() -> int:
   """!A stage's range lies within [-limit, limit] (capsule::battle::kStageLimit).
   @return the limit
   """
   return int(_bc().STAGE_LIMIT)


def default_range(kind: str) -> tuple[int, int]:
   """!The range a new stage of a kind starts with: the studio's starting range (core.battle's
   NEUTRAL_STAGE_RANGE, NEUTRAL_CRIT_RANGE: the new-battle template's), within the engine's stage limit. Since E7
   the ruleset compiler's own neutral ranges (DEFAULT_STAGE_RANGE / DEFAULT_CRIT_RANGE) span the whole limit,
   which makes a long table to fill; a game widens a stage's range when it wants more.
   @param kind  stage kind
   @return (lo, hi)
   """
   lo, hi = battle.NEUTRAL_CRIT_RANGE if kind == CRIT_KIND else battle.NEUTRAL_STAGE_RANGE
   limit = stage_limit()
   return max(lo, -limit), min(hi, limit)


def old_range(kind: str) -> tuple[int, int]:
   """!The fixed range the pre-E6a engine gave a stage of a kind (its tables ran from -6 to +6, its crit odds from
   0 to 4): what migrate() writes.
   @param kind  stage kind
   @return (lo, hi)
   """
   return OLD_CRIT_RANGE if kind == CRIT_KIND else OLD_STAGE_RANGE


def max_stages(targets: list[str] | None = None) -> int:
   """!Most stages every target takes (capsule::battle::kMaxStages: the single kinds plus one per stat but the
   pool stat).
   @param targets  platforms, or None for the default targets
   @return count
   """
   from . import stats as stat_model   # local: core.structure.stats imports this module
   return len(single_kinds()) + stat_model.stat_limit(targets) - 1


# -- reading -----------------------------------------------------------------------------------------------------------

def _listed(data: JsonDict) -> list[Any]:
   """!The stages list for reading (nothing created).
   @param data  battle manifest data
   @return the live list, or [] when the manifest has none
   """
   given = data.get(STAGES_KEY)
   return given if isinstance(given, list) else []


def stages(doc: Document) -> list[JsonDict]:
   """!The battle manifest's stages list.
   @param doc  battle Document
   @return the list (live; created when absent; change it only inside doc.edit())
   """
   given = battle.data_of(doc, STAGES_KEY).get(STAGES_KEY)
   if not isinstance(given, list):
      given = battle.data_of(doc, STAGES_KEY)[STAGES_KEY] = []
   return given


def kind_of(entry: Any) -> str | None:
   """!A stage entry's kind as the engine reads it ("stat" when it names a stat and gives no kind).
   @param entry  stage entry
   @return the kind, or None when it has none
   """
   if not isinstance(entry, dict):
      return None
   return entry.get("kind", STAT_KIND if "stat" in entry else None)


def name_of(entry: Any) -> str | None:
   """!A stage entry's name as the engine reads it (a stat's stage defaults to the stat's name).
   @param entry  stage entry
   @return the name, or None when it has none
   """
   if not isinstance(entry, dict):
      return None
   name = entry.get("name", entry.get("stat") if kind_of(entry) == STAT_KIND else None)
   return name if isinstance(name, str) else None


def names_of(data: JsonDict) -> list[str]:
   """!The stage names in index order (the names effect code uses; core.logic's "stages" list).
   @param data  battle manifest data
   @return names (entries without one left out)
   """
   return [n for n in (name_of(e) for e in _listed(data)) if n is not None]


def stage_names(doc: Document) -> list[str]:
   """!The stage names in index order.
   @param doc  battle Document
   @return names
   """
   return names_of(battle.merged(doc))


def stage_entry(doc: Document, name: str) -> JsonDict:
   """!A stage by name.
   @param doc   battle Document
   @param name  stage name
   @return the dict (live)
   @throws DocumentError when there is none
   """
   for e in _listed(battle.data_of(doc, STAGES_KEY)):
      if name_of(e) == name:
         return e
   raise DocumentError(f"no stage {name!r} (stages: {', '.join(stage_names(doc)) or 'none'})")


def stat_stage(doc: Document, stat: str) -> JsonDict | None:
   """!A stat's stage.
   @param doc   battle Document
   @param stat  stat name
   @return the entry (live), or None when the stat has none
   """
   listed = _listed(battle.data_of(doc, STAGES_KEY))
   return next((e for e in listed if kind_of(e) == STAT_KIND and e.get("stat") == stat), None)


def crit_max(doc: Document) -> int:
   """!The highest crit stage a move may add (a move's crit_stage): the crit stage's highest stage.
   @param doc  battle Document
   @return its range's hi; 0 without a crit stage (or without a range)
   """
   e = next((e for e in _listed(battle.data_of(doc, STAGES_KEY)) if kind_of(e) == CRIT_KIND), None)
   rng = e.get("range") if e is not None else None
   return int(rng[1]) if isinstance(rng, list) and len(rng) == PAIR and isinstance(rng[1], int) else 0


def mode_of(entry: JsonDict) -> str:
   """!How a stage scales.
   @param entry  stage entry
   @return one of MODES
   """
   if "table" in entry:
      return TABLE_MODE
   if entry.get("formula") is not None:
      return FORMULA_MODE
   return NO_MODE


def _stat_label(doc: Document, stat: Any) -> str | None:
   """!A stat's in-game label (its name when it has none).
   @param doc   battle Document
   @param stat  stat name
   @return the label, or None for an unknown stat
   """
   given = battle.data_of(doc, "stats").get("stats")
   for st in given if isinstance(given, list) else []:
      if isinstance(st, dict) and st.get("name") == stat:
         label = st.get("label", stat)
         return label if isinstance(label, str) else stat
   return None


def stage_list(doc: Document) -> list[StageRow]:
   """!Every stage with its defaults resolved as the engine resolves them.
   @param doc  battle Document
   @return copies in index order: index, name, named (the manifest gives the name), kind, stat (None but for a
           stat's stage), label, labelled (the manifest gives the label), range (lo, hi) or None, mode (MODES),
           table (a copy) or None, formula or None
   """
   out = []
   for i, e in enumerate(e for e in _listed(battle.data_of(doc, STAGES_KEY)) if isinstance(e, dict)):
      kind = kind_of(e)
      name = name_of(e)
      rng = e.get("range")
      label = e.get("label")
      if label is None:
         label = _stat_label(doc, e.get("stat")) if kind == STAT_KIND else None
         label = label if label is not None else name
      out.append({"index": i, "name": name, "named": "name" in e, "kind": kind,
                  "stat": e.get("stat") if kind == STAT_KIND else None, "label": label, "labelled": "label" in e,
                  "range": tuple(rng) if isinstance(rng, list) and len(rng) == PAIR else None, "mode": mode_of(e),
                  "table": copy.deepcopy(e["table"]) if "table" in e else None, "formula": e.get("formula")})
   return out


def formula_choices(project: BattleProject) -> list[str]:
   """!The ruleset formulas a stage may scale by: named formulas of two arguments (the value, the stage value).
   @param project  BattleProject
   @return names, in ruleset order
   """
   formulas = project.ruleset.data.get("formulas")
   formulas = formulas if isinstance(formulas, dict) else {}
   return [n for n in battle.named_formulas(project.ruleset)
           if isinstance(formulas[n].get("args"), list) and len(formulas[n]["args"]) == PAIR]


# -- values ------------------------------------------------------------------------------------------------------------

def parse_entry(value: Any, kind: str) -> Any:
   """!A table entry as the manifest stores it.
   @param value  [num, den] or "num/den" (a multiplier); odds "n/m" or [n, m] for the crit stage
   @param kind   the stage's kind
   @return [num, den], or the odds text "n/m" for the crit stage
   @throws DocumentError when it is not one
   """
   pair = None
   if isinstance(value, str):
      m = FRACTION.fullmatch(value)
      pair = (int(m.group("num")), int(m.group("den"))) if m else None
   elif isinstance(value, (list, tuple)) and len(value) == PAIR and \
         all(isinstance(v, int) and not isinstance(v, bool) for v in value):
      pair = (int(value[0]), int(value[1]))
   if kind == CRIT_KIND:
      if pair is None or pair[1] < 1 or pair[0] > pair[1]:
         raise DocumentError(f"crit odds are n/m with 0 <= n <= m and m >= 1 (got {value!r})")
      return f"{pair[0]}/{pair[1]}"
   if pair is None or pair[0] < 1 or pair[1] < 1:
      raise DocumentError(f"a stage multiplier is num/den with both at least 1 (got {value!r})")
   return [pair[0], pair[1]]


def entry_text(value: Any) -> str:
   """!A table entry as text.
   @param value  [num, den] or odds text
   @return "num/den" (odds as they are)
   """
   if isinstance(value, list) and len(value) == PAIR:
      return f"{value[0]}/{value[1]}"
   return str(value)


def _blank(kind: str) -> Any:
   """!A new table entry of a kind: x1, or never for the crit stage.
   @param kind  stage kind
   @return the entry
   """
   return NEVER if kind == CRIT_KIND else list(IDENTITY)


def _check_range(value: Any) -> tuple[int, int]:
   """!A stage range the engine takes.
   @param value  [lo, hi]
   @return (lo, hi)
   @throws DocumentError when it is not one
   """
   limit = stage_limit()
   if not isinstance(value, (list, tuple)) or len(value) != PAIR or \
         not all(isinstance(v, int) and not isinstance(v, bool) for v in value) or \
         not -limit <= value[0] <= 0 <= value[1] <= limit:
      raise DocumentError(f"a stage range is [lo, hi] with -{limit} <= lo <= 0 <= hi <= {limit} (got {value!r})")
   return int(value[0]), int(value[1])


def _check_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A stage name the engine takes and no other stage has.
   @param doc      battle Document
   @param name     wanted name
   @param current  the stage being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   if not isinstance(name, str) or not _bc().STAT_NAME.fullmatch(name.strip()):
      raise DocumentError(f"a stage name is a lower-case identifier (got {name!r})")
   name = name.strip()
   if name != current and name in stage_names(doc):
      raise DocumentError(f"there is already a stage {name!r}")
   return name


def _check_stat(doc: Document, stat: Any, current: JsonDict | None = None) -> str:
   """!A stat that may get a stage: a stat of the battle, not the pool stat, without a stage yet.
   @param doc      battle Document
   @param stat     stat name
   @param current  the stage being changed (its own stat is fine), or None
   @return the stat name
   @throws DocumentError when it is not one
   """
   rows = [st for st in battle.data_of(doc, "stats").get("stats", []) if isinstance(st, dict)] \
      if isinstance(battle.data_of(doc, "stats").get("stats"), list) else []
   allowed = [st.get("name") for st in rows if st.get("pool") is not True]
   if stat not in allowed:
      raise DocumentError(f"a stat's stage names a stat other than the pool stat ({', '.join(map(str, allowed))}; "
                          f"got {stat!r})")
   held = stat_stage(doc, stat)
   if held is not None and held is not current:
      raise DocumentError(f"{stat} already has a stage ({name_of(held)})")
   return stat


# -- editing (inside battle.edit()) ------------------------------------------------------------------------------------

def add_stage(doc: Document, kind: str, name: str | None = None, stat: str | None = None,
              rng: tuple[int, int] | list[int] | None = None, index: int | None = None, label: str | None = None,
              targets: list[str] | None = None) -> int:
   """!Adds a stage. A new stage scales by nothing (x1); a new crit stage gets a table of "never" odds (the
   pipelines' crit_chance() needs odds). A stat's new stage copies the table, formula and range every other stat
   stage shares, when they share one.
   @param doc      battle Document
   @param kind     one of kinds()
   @param name     its name, or None (a stat's stage: the stat's name; other kinds: the kind)
   @param stat     the stat (kind "stat" only)
   @param rng      [lo, hi], or None for default_range() (or the shared stat stage range)
   @param index    position, or None for the end
   @param label    in-game text, or None for the default (the stat's label, else the name)
   @param targets  platforms whose stage limit applies, or None for the default targets
   @return its index
   @throws DocumentError for what the engine refuses
   """
   if kind not in kinds():
      raise DocumentError(f"a stage kind is one of {', '.join(kinds())} (got {kind!r})")
   rows = stage_list(doc)
   most = max_stages(targets)
   if len(rows) >= most:
      raise DocumentError(f"at most {most} stages on {', '.join(targets or ['the default targets'])}")
   entry: JsonDict = {}
   template = None
   if kind == STAT_KIND:
      stat = _check_stat(doc, stat)
      entry["stat"] = stat
      shared = [r for r in rows if r["kind"] == STAT_KIND]
      if shared and all((r["range"], r["table"], r["formula"]) ==
                        (shared[0]["range"], shared[0]["table"], shared[0]["formula"]) for r in shared):
         template = shared[0]
      wanted = name if name is not None else stat
   else:
      if stat is not None:
         raise DocumentError("only a stage of kind stat names a stat")
      if kind in (r["kind"] for r in rows):
         raise DocumentError(f"there is already a stage of kind {kind} (at most one)")
      entry["kind"] = kind
      wanted = name if name is not None else kind
   wanted = _check_name(doc, wanted)
   if kind != STAT_KIND or wanted != stat:
      entry = {"name": wanted, **entry}
   if label is not None:
      if not isinstance(label, str) or not label.strip():
         raise DocumentError("a stage label can't be empty")
      entry["label"] = label.strip()
   if rng is not None:
      lo, hi = _check_range(rng)
   elif template is not None and template["range"] is not None:
      lo, hi = template["range"]
   else:
      lo, hi = default_range(kind)
   entry["range"] = [lo, hi]
   if template is not None and template["table"] is not None and rng is None:
      entry["table"] = copy.deepcopy(template["table"])
   elif template is not None and template["formula"] is not None:
      entry["formula"] = template["formula"]
   elif kind == CRIT_KIND:
      entry["table"] = [_blank(kind) for _v in range(lo, hi + 1)]
   lst = stages(doc)
   at = len(lst) if index is None else max(0, min(len(lst), int(index)))
   lst.insert(at, entry)
   return at


def _logic_users(doc: Document, name: str) -> list[str]:
   """!The effect logic naming a stage (one "where" per owner).
   @param doc   battle Document
   @param name  stage name
   @return owners
   """
   return logic.per_owner(logic.references(doc, (STAGES_KEY,), name))


def remove_stage(doc: Document, name: str) -> None:
   """!Removes a stage; refused while effect logic names it or the ruleset's pipelines / points need it (a crit
   pipeline step needs a crit stage: core.battle.check_ruleset_kept()).
   @param doc   battle Document
   @param name  stage name
   @return None
   """
   e = stage_entry(doc, name)
   users = _logic_users(doc, name)
   if users:
      shown = ", ".join(sorted(set(users))[:battle.REFERENCES_SHOWN])
      raise DocumentError(f"stage {name!r} is still used by: {shown}")
   before = battle.ruleset_problem(doc)
   stages(doc).remove(e)
   battle.check_ruleset_kept(doc, f"stage {name!r}", before)


def move_stage(doc: Document, name: str, delta: int) -> bool:
   """!Moves a stage up or down the list (its index; effect logic names stages, so nothing else changes).
   @param doc    battle Document
   @param name   stage name
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   lst = stages(doc)
   i = lst.index(stage_entry(doc, name))
   j = i + delta
   if not 0 <= j < len(lst):
      return False
   lst[i], lst[j] = lst[j], lst[i]
   return True


def rename_stage(doc: Document, old: str, new: str) -> int:
   """!Renames a stage and the effect logic naming it. A stat's stage renamed to its stat's name goes back to the
   default (no "name").
   @param doc  battle Document
   @param old  current name
   @param new  new name
   @return references updated
   """
   e = stage_entry(doc, old)
   new = _check_name(doc, new, old)
   if new == old:
      return 0
   n = len(logic.per_owner(logic.references(doc, (STAGES_KEY,), old, new)))
   _put_name(e, new)
   return n


def _put_name(entry: JsonDict, name: str) -> None:
   """!Writes a stage's name, leaving it out when it is the default (a stat's stage named as its stat).
   @param entry  stage entry
   @param name   the name
   @return None
   """
   if kind_of(entry) == STAT_KIND and entry.get("stat") == name:
      entry.pop("name", None)
   else:
      # The name first, as the manifest writes it.
      rest = {k: v for k, v in entry.items() if k != "name"}
      entry.clear()
      entry.update({"name": name, **rest})


def _resize(entry: JsonDict, lo: int, hi: int) -> None:
   """!Fits a stage's table to a new range: entries of stage values in both ranges stay, new ones are x1 (never
   for the crit stage).
   @param entry  stage entry with a table and a range
   @param lo     new lowest stage
   @param hi     new highest stage
   @return None
   """
   old = entry.get("table")
   old_lo = entry["range"][0] if isinstance(entry.get("range"), list) else lo
   kind = kind_of(entry) or STAT_KIND
   table = []
   for v in range(lo, hi + 1):
      at = v - old_lo
      table.append(copy.deepcopy(old[at]) if isinstance(old, list) and 0 <= at < len(old) else _blank(kind))
   entry["table"] = table


def set_stage(doc: Document, name: str, key: str, value: Any) -> None:
   """!Changes one property of a stage (None puts the default back where there is one).
   @param doc    battle Document
   @param name   stage name
   @param key    one of STAGE_PROPERTIES: label (text; None: the default), stat (a stat's stage only), range
                 ([lo, hi]: a table is fitted, see _resize()), table (a full list of entries: replaces the formula;
                 None: no table), formula (a named formula of two arguments: replaces the table; None: none)
   @param value  the value
   @return None
   @throws DocumentError for what the engine refuses
   """
   e = stage_entry(doc, name)
   kind = kind_of(e)
   if key not in STAGE_PROPERTIES:
      raise DocumentError(f"unknown stage property {key!r} (properties: {', '.join(STAGE_PROPERTIES)}; the name: "
                          "rename; the kind: remove the stage and add one)")
   if key == "label":
      if value is None:
         e.pop("label", None)
      elif not isinstance(value, str) or not value.strip():
         raise DocumentError("a stage label can't be empty (None puts the default back)")
      else:
         e["label"] = value.strip()
   elif key == "stat":
      if kind != STAT_KIND:
         raise DocumentError("only a stage of kind stat names a stat")
      implicit = "name" not in e
      e["stat"] = _check_stat(doc, value, e)
      if implicit:
         _put_name(e, name)   # the stage keeps its name (effect logic names it)
   elif key == "range":
      lo, hi = _check_range(value)
      if "table" in e:
         _resize(e, lo, hi)
      e["range"] = [lo, hi]
   elif key == "table":
      if value is None:
         e.pop("table", None)
         return
      lo, hi = _check_range(e.get("range"))
      if not isinstance(value, list) or len(value) != hi - lo + 1:
         raise DocumentError(f"{name}'s table has {hi - lo + 1} entries, one per stage from {lo} to {hi}")
      e["table"] = [parse_entry(v, kind) for v in value]
      e.pop("formula", None)
   else:
      set_mode(doc, name, FORMULA_MODE if value is not None else NO_MODE, value)


def set_mode(doc: Document, name: str, mode: str, formula: str | None = None,
             choices: list[str] | None = None) -> None:
   """!Chooses how a stage scales: by a table (a new one is all x1, or never for the crit stage), by a named
   formula, or not at all.
   @param doc      battle Document
   @param name     stage name
   @param mode     one of MODES
   @param formula  the formula (mode "formula")
   @param choices  the formulas allowed (formula_choices()), or None to leave the check to the compiler
   @return None
   @throws DocumentError for the crit stage with a formula, an unknown mode or formula
   """
   e = stage_entry(doc, name)
   kind = kind_of(e)
   if mode not in MODES:
      raise DocumentError(f"a stage scales by one of {', '.join(MODES)} (got {mode!r})")
   if mode == TABLE_MODE:
      if "table" not in e:
         lo, hi = _check_range(e.get("range"))
         e["table"] = [_blank(kind) for _v in range(lo, hi + 1)]
      e.pop("formula", None)
   elif mode == FORMULA_MODE:
      if kind == CRIT_KIND:
         raise DocumentError("the crit stage takes odds (a table), not a formula")
      if not isinstance(formula, str) or not formula.strip():
         raise DocumentError("name the formula (a named ruleset formula of two arguments)")
      if choices is not None and formula.strip() not in choices:
         raise DocumentError(f"{formula!r} is not a named formula of two arguments ({', '.join(choices) or 'none'})")
      e.pop("table", None)
      e["formula"] = formula.strip()
   else:
      e.pop("table", None)
      e.pop("formula", None)


def set_entry(doc: Document, name: str, stage: int, value: Any) -> None:
   """!Sets one table entry (a stage without a table gets one first: see set_mode()).
   @param doc    battle Document
   @param name   stage name
   @param stage  the stage value (within the range)
   @param value  "num/den" or [num, den]; odds for the crit stage
   @return None
   """
   e = stage_entry(doc, name)
   lo, hi = _check_range(e.get("range"))
   if not lo <= stage <= hi:
      raise DocumentError(f"{name}'s stages run from {lo} to {hi} (got {stage})")
   entry = parse_entry(value, kind_of(e))
   set_mode(doc, name, TABLE_MODE)
   e["table"][stage - lo] = entry


# -- the stat side (core.structure.stats) ------------------------------------------------------------------------------

def rename_stat(doc: Document, old: str, new: str) -> bool:
   """!A stat was renamed: its stage names the new stat; a stage named after the stat by default keeps that.
   @param doc  battle Document
   @param old  the stat's old name
   @param new  its new name
   @return True when the stage's name follows the stat (effect logic naming the stage must be renamed too)
   """
   e = stat_stage(doc, old)
   if e is None:
      return False
   follows = name_of(e) == old
   e["stat"] = new
   if follows:
      e.pop("name", None)
   return follows


def drop_stat(doc: Document, stat: str) -> None:
   """!A stat was removed: its stage goes too.
   @param doc   battle Document
   @param stat  stat name
   @return None
   """
   e = stat_stage(doc, stat)
   if e is not None:
      stages(doc).remove(e)


def stat_stage_users(doc: Document, stat: str) -> list[str]:
   """!The effect logic naming a stat's stage.
   @param doc   battle Document
   @param stat  stat name
   @return owners ([] when the stat has no stage)
   """
   e = stat_stage(doc, stat)
   return _logic_users(doc, name_of(e)) if e is not None else []


def stat_stage_index(doc: Document) -> int:
   """!Where a stat's new stage goes: after the last stat stage, else at the end.
   @param doc  battle Document
   @return index
   """
   rows = stage_list(doc)
   at = [r["index"] for r in rows if r["kind"] == STAT_KIND]
   return at[-1] + 1 if at else len(rows)


# -- preview and text --------------------------------------------------------------------------------------------------

def preview(project: BattleProject, name: str, value: int = PREVIEW_VALUE) -> list[PreviewRow]:
   """!What a stage does at each of its values, computed by the engine's own evaluator on the compiled data
   (ruleset_compiler.stage_value(): table, formula or x1; the crit stage's odds).
   @param project  BattleProject (its data must compile)
   @param name     stage name
   @param value    the value scaled
   @return one row per stage value, lowest first
   @throws DocumentError when the data does not compile or there is no such stage
   """
   compiled, error = project.compile()
   if compiled is None:
      raise DocumentError(error)
   index = next((i for i, st in enumerate(compiled["stages"]) if st["name"] == name), None)
   if index is None:
      raise DocumentError(f"no stage {name!r}")
   st = compiled["stages"][index]
   rc = _rc()
   env = compiled["pipelines"]["env"]
   lo, hi = st["range"]
   rows = []
   for v in range(lo, hi + 1):
      if st["odds"] is not None:
         n, m = st["odds"][v - lo]
         rows.append((v, f"{n}/{m}", f"{n * PERCENT / m:.{PREVIEW_DECIMALS}f} %"))
      elif st["table"] is not None:
         num, den = st["table"][v - lo]
         rows.append((v, f"x{num / den:.{PREVIEW_DECIMALS}f} ({num}/{den})", str(rc.stage_value(env, index, value, v))))
      else:
         scaled = rc.stage_value(env, index, value, v)
         how = f"formula {st['formula']}" if st["formula"] is not None else "x1"
         rows.append((v, how, str(scaled)))
   return rows


def stage_line(row: StageRow) -> str:
   """!A stage as one line of text (the CLI's `stage list`).
   @param row  a stage_list() row
   @return the line
   """
   rng = f"[{row['range'][0]}, {row['range'][1]}]" if row["range"] is not None else "no range"
   what = row["kind"] + (f" of {row['stat']}" if row["stat"] is not None else "")
   if row["mode"] == TABLE_MODE:
      how = "table " + " ".join(entry_text(v) for v in row["table"] or [])
   elif row["mode"] == FORMULA_MODE:
      how = f"formula {row['formula']}"
   else:
      how = "x1"
   return f"{row['index']} {row['name']}: {what}, label {row['label']!r}, range {rng}, {how}"


def report(doc: Document, targets: list[str] | None = None) -> list[str]:
   """!The stages as text lines, then the stage budget.
   @param doc      battle Document
   @param targets  platforms, or None for the default targets
   @return lines
   """
   rows = stage_list(doc)
   return [stage_line(r) for r in rows] + [f"{len(rows)}/{max_stages(targets)} stages"]


# -- pre-E6a data ------------------------------------------------------------------------------------------------------

def needs_migration(data: JsonDict) -> bool:
   """!Whether battle data still has the pre-E6a stage keys (the engine refuses them).
   @param data  battle manifest data
   @return True when migrate() has something to do
   """
   rules = data.get("rules") if isinstance(data.get("rules"), dict) else {}
   stats = data.get("stats") if isinstance(data.get("stats"), list) else []
   return OLD_NAMES_KEY in data or any(k in rules for k in OLD_RULES) or \
      any(isinstance(st, dict) and OLD_STAT_FLAG in st for st in stats)


def migrate(doc: Document) -> bool:
   """!Turns pre-E6a stage data into the stages list (the old engine's order: accuracy, evasion, critical, then
   each staged stat; the old tables ran from -6 to +6, the crit odds from 0 to 4). Keeps stages already listed.
   @param doc  battle Document
   @return True when something changed
   """
   d = battle.merged(doc)
   if not needs_migration(d):
      return False
   rules = d.get("rules") if isinstance(d.get("rules"), dict) else {}
   names = battle.data_of(doc, OLD_NAMES_KEY).pop(OLD_NAMES_KEY, None)
   names = names if isinstance(names, dict) else {}
   tables = {kind: rules.pop(key, None) for key, kind in OLD_RULES.items()}
   out = list(_listed(d))
   have = {kind_of(e) for e in out}
   for old, kind in OLD_FIXED:
      if kind in have:
         continue
      entry: JsonDict = {"name": old, "kind": kind}
      if isinstance(names.get(old), str):
         entry["label"] = names[old]
      entry["range"] = list(old_range(kind))
      table = tables.get(kind) if kind != "evasion" else None
      if isinstance(table, list):
         entry["table"] = table
      out.append(entry)
   for st in d.get("stats", []) if isinstance(d.get("stats"), list) else []:
      if not isinstance(st, dict):
         continue
      staged = st.pop(OLD_STAT_FLAG, st.get("pool") is not True)
      if staged is True and not any(e.get("stat") == st.get("name") for e in out if isinstance(e, dict)):
         entry = {"stat": st.get("name"), "range": list(old_range(STAT_KIND))}
         if isinstance(tables.get(STAT_KIND), list):
            entry["table"] = copy.deepcopy(tables[STAT_KIND])
         out.append(entry)
   battle.data_of(doc, STAGES_KEY)[STAGES_KEY] = out
   return True


def needs_any_migration(doc: Document) -> bool:
   """!Whether battle data still has pre-E6a stage or chart data (`battle FILE migrate`, the window's offer).
   @param doc  any manifest Document of the battle
   @return True when migrate_all() has something to do
   """
   from . import chart   # local: only the migration needs the chart module here
   d = battle.merged(doc)
   return needs_migration(d) or chart.needs_migration(d)


def migrate_all(doc: Document) -> list[str]:
   """!Migrates pre-E6a stage data (migrate()) and the pre-E6a chart (core.structure.chart.migrate()): what the
   CLI's `migrate` and the battle window's File > Migrate do (call it inside one edit).
   @param doc  any manifest Document of the battle
   @return what changed: "stages", "chart" (empty: nothing to migrate)
   """
   from . import chart   # local: see needs_any_migration()
   return [what for what, changed in (("stages", migrate(doc)), ("chart", chart.migrate(doc))) if changed]
