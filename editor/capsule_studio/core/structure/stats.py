"""!The stats of battle data (D-20 C): the battle manifest's "stats" list,
edited with everything that depends on them.

    "stats": [{"name": "hp", "label": "Health", "formula": "stat_hp", "pool": true,
               "editor": {"short": "HP"}}, ...,
              {"name": "spe", "label": "Speed", "formula": "stat_other", "order": true}]

A stat's position is its record and engine index, so adding, removing and
moving one also moves every species' base value; renaming one follows the
categories (offense / defense), the traits (up / down), the battler resources
whose maximum it is (resources[].stat; a stat a resource takes is not
removed) and the effect logic that reads the stat or its stage (core.logic, through the AST of the .ceffect
sources). Each helper is one change: call it inside one battle.edit() and
Undo takes the whole migration back (the source edits are linked to it).

Flags (the engine's battlec/stats.py): exactly one pool stat (hit points;
no trait by default) and exactly one order stat (turn order, escape).
Setting either flag on a stat takes it off the others. At most one stat is
the odds stat (E9: the ruleset's effect_odds pipeline reads it as user_stat
/ target_stat); setting it takes it off the others, and a game may have
none. trait defaults to
true, transfer (the stat's key in transfers) to the name; editor.short is a
studio-only abbreviation. "stage" is not a key of the stat (E6a): a stat has
a stage when the manifest's "stages" list one for it (core.structure.stages);
the stage flag here adds or removes that stage, and renaming or removing a
stat follows its stage.

Limits: the engine's per-platform limits (build_settings.PLATFORM_LIMITS:
10 stats on the GBA, 32 otherwise; at most 3 + stats - 1 stages) and the
game's declared targets (its reference/project.json "targets", default
["gba"]).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import battle, engine, logic
from ..document import Document, DocumentError
from . import stages as stage_model

## A parsed JSON object.
JsonDict = dict[str, Any]
## One stat as stat_list() gives it: every flag resolved (name, label, formula, pool, order, odds, stage (it has
## one), trait, transfer, short).
StatRow = dict[str, Any]
## One target's stat budget: (platform, stats used, most stats).
Budget = tuple[str, int, int]

## The battle manifest's stats list.
STATS_KEY = "stats"
## Flags a stat may set (see the module docstring; "stage" is the stat's entry in "stages").
FLAGS = ("pool", "order", "odds", "stage", "trait")
## Flags exactly one stat has.
ONE_OF_FLAGS = ("pool", "order")
## Flags at most one stat has (E9: the effect_odds pipeline's stat); false is the default and is not written.
AT_MOST_ONE_FLAGS = ("odds",)
## Every key set_stat() changes ("short" is the editor's abbreviation, kept under "editor").
STAT_KEYS = ("label", "formula", "pool", "order", "odds", "stage", "trait", "transfer", "short")
## Key of a stat's transfer key (default: its name).
TRANSFER_KEY = "transfer"
## Key of a manifest entry's studio-only data (the compiler strips it).
EDITOR_KEY = "editor"
## Key of a stat's abbreviation under "editor".
SHORT_KEY = "short"
## Targets a game without a "targets" list builds for.
DEFAULT_TARGETS = ["gba"]
## The project manifest's list of target platforms.
TARGETS_KEY = "targets"
## The effect compiler's structure lists a stat's name is in: the stat itself (`holder.stat(atk)`) and its
## stage (`holder.stage(atk)`, `stage target atk -1;`) when the stage is named after the stat.
STAT_LISTS = ("stats", "stages")
## The list of the stat alone (a stage named otherwise does not follow the stat).
STAT_ONLY = ("stats",)
## The stage flag.
STAGE_FLAG = "stage"
## The structure's training section (G4; its yields name stats: core.structure.transformation).
TRAINING_KEY = "training"
## The training's yields, {stat: species field}.
YIELDS_KEY = "yields"


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def stats(doc: Document) -> list[JsonDict]:
   """!The battle manifest's stats list.
   @param doc  battle Document
   @return the list (live; created when absent; change it only inside doc.edit())
   """
   given = battle.data_of(doc, STATS_KEY).get(STATS_KEY)
   if not isinstance(given, list):
      given = battle.data_of(doc, STATS_KEY)[STATS_KEY] = []
   return given


def _listed(doc: Document) -> list[Any]:
   """!The stats list for reading (nothing created).
   @param doc  battle Document
   @return the live list, or [] when the manifest has none
   """
   given = battle.data_of(doc, STATS_KEY).get(STATS_KEY)
   return given if isinstance(given, list) else []


def stat_names(doc: Document) -> list[str]:
   """!The stat names in record order (core.battle.stat_keys()).
   @param doc  battle Document
   @return names
   """
   return battle.stat_keys(doc)


def stat_entry(doc: Document, name: str) -> JsonDict:
   """!A stat by name.
   @param doc   battle Document
   @param name  stat name
   @return the dict (live)
   @throws DocumentError when there is none
   """
   for st in _listed(doc):
      if isinstance(st, dict) and st.get("name") == name:
         return st
   raise DocumentError(f"no stat {name!r} (stats: {', '.join(stat_names(doc)) or 'none'})")


def _short(st: JsonDict) -> str | None:
   """!A stat's editor abbreviation.
   @param st  stat dict
   @return editor.short, or None
   """
   ed = st.get(EDITOR_KEY)
   short = ed.get(SHORT_KEY) if isinstance(ed, dict) else None
   return short if isinstance(short, str) else None


def stat_list(doc: Document) -> list[StatRow]:
   """!Every stat with its flags resolved as the engine resolves them (pool, order and odds false, trait true but
   false for the pool stat, transfer the name), whether it has a stage (and its index) and its abbreviation.
   @param doc  battle Document
   @return copies, in record order (each with "index", "stage" and "stage_index": the stage's index, or None)
   """
   out = []
   staged = {r["stat"]: r["index"] for r in stage_model.stage_list(doc) if r["stat"] is not None}
   for i, st in enumerate(s for s in _listed(doc) if isinstance(s, dict)):
      pool = st.get("pool", False) is True
      row = {"index": i, "name": st.get("name"), "label": st.get("label", st.get("name")),
             "formula": st.get("formula"), "pool": pool, "order": st.get("order", False) is True,
             "odds": st.get("odds", False) is True, "stage": st.get("name") in staged,
             "trait": st.get("trait", not pool) is True,
             "transfer": st.get("transfer", st.get("name")), "short": _short(st),
             "stage_index": staged.get(st.get("name"))}
      out.append(row)
   return out


def _check_new_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A stat name the engine takes and no other stat has.
   @param doc      battle Document
   @param name     wanted name
   @param current  the stat being renamed (its own name is fine), or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   bc = _bc()
   if not isinstance(name, str) or not bc.STAT_NAME.fullmatch(name.strip()):
      raise DocumentError(f"a stat name is a lower-case identifier (got {name!r})")
   name = name.strip()
   if name != current and name in stat_names(doc):
      raise DocumentError(f"there is already a stat {name!r}")
   # A new stat uses its name as its transfer key, and the battle compiler refuses two stats with one key. (A
   # renamed stat keeps its old key: rename_stat() pins it.)
   holder = transfer_key_holder(doc, name, current) if current is None else None
   if holder is not None:
      raise DocumentError(f"{name!r} is the transfer key of the stat {holder!r} (transfers find that stat by it): "
                          f"pick another name, or change {holder!r}'s transfer key first")
   return name


def transfer_key_holder(doc: Document, key: str, current: str | None = None) -> str | None:
   """!The stat whose transfer key a key is (a stat without one uses its name).
   @param doc      battle Document
   @param key      a transfer key
   @param current  a stat to leave out (the one being renamed or changed), or None
   @return that stat's name, or None when no other stat has the key
   """
   return next((r["name"] for r in stat_list(doc) if r["name"] != current and r["transfer"] == key), None)


# -- limits -----------------------------------------------------------------------------------------------------------

def max_stats(platform: str | None = None) -> int:
   """!Most stats a creature has on a platform (the engine's build_settings.PLATFORM_LIMITS).
   @param platform  a build_settings.PLATFORMS name, or None for the engine's default (the GBA)
   @return count
   @throws DocumentError for an unknown platform
   """
   bs = engine.tool("build_settings")
   try:
      return bs.platform_limits(platform)["max_stats"]
   except bs.SettingsError as e:
      raise DocumentError(str(e)) from None


def platforms() -> list[str]:
   """!The platform names a project's targets may list (the engine's build_settings.PLATFORMS).
   @return names
   """
   return list(engine.tool("build_settings").PLATFORMS)


def project_targets(path: str | Path | None) -> list[str]:
   """!The platforms a game builds for: its reference/project.json "targets".
   @param path  any file of the game (its battle.json, say), or None
   @return the targets; DEFAULT_TARGETS when the file is in no game or the project declares none
   @throws DocumentError when the project lists a platform the engine does not know
   """
   from .. import codepage, manifest_io   # local: codepage imports core.battle

   found = codepage.find_project(path) if path is not None else None
   if found is None:
      return list(DEFAULT_TARGETS)
   try:
      data = manifest_io.load(found)
   except (OSError, ValueError) as e:
      raise DocumentError(f"cannot read {found}: {e}") from None
   given = data.get(TARGETS_KEY) if isinstance(data, dict) else None
   if given is None:
      return list(DEFAULT_TARGETS)
   known = platforms()
   if not isinstance(given, list) or not given or not all(isinstance(t, str) and t in known for t in given):
      raise DocumentError(f"{found}: {TARGETS_KEY} lists platforms ({', '.join(known)}), got {given!r}")
   return list(dict.fromkeys(given))


def stat_limit(targets: list[str] | None = None) -> int:
   """!Most stats every target takes.
   @param targets  platforms, or None for DEFAULT_TARGETS
   @return the smallest limit
   """
   return min(max_stats(t) for t in (targets or DEFAULT_TARGETS))


def stat_budget(doc: Document, targets: list[str] | None = None) -> list[Budget]:
   """!Stats used against each target's limit ("7/10 GBA").
   @param doc      battle Document
   @param targets  platforms, or None for DEFAULT_TARGETS
   @return [(platform, stats, most)] in target order
   """
   used = len(_listed(doc))
   return [(t, used, max_stats(t)) for t in (targets or DEFAULT_TARGETS)]


def limit_problems(doc: Document, targets: list[str] | None = None) -> list[str]:
   """!What the stats break on each target: too many stats, or too many stages.
   @param doc      battle Document
   @param targets  platforms, or None for DEFAULT_TARGETS
   @return messages ([] when every target takes them)
   """
   rows = stat_list(doc)
   count = len(stage_model.stage_list(doc))
   out = []
   for t in targets or DEFAULT_TARGETS:
      most = max_stats(t)
      if len(rows) > most:
         out.append(f"{t}: {len(rows)} stats, the engine takes at most {most}")
      most_stages = stage_model.max_stages([t])
      if count > most_stages:
         out.append(f"{t}: {count} stages, the engine takes at most {most_stages}")
   return out


# -- references -------------------------------------------------------------------------------------------------------

def stat_references(doc: Document, name: str, new: str | None = None) -> list[str]:
   """!Finds (and optionally renames) what names a stat: categories' offense / defense, traits' up / down, the
   battler resources it is the maximum of, the field rules' expressions (C8: core.structure.field_expressions) and
   the effect logic reading the stat or its stage (core.logic.references(); one "where" per owner).
   @param doc   battle Document
   @param name  stat name
   @param new   new name to write, or None to only look
   @return "where" strings
   @throws DocumentError when an effect source does not parse (a rename could not follow it)
   """
   found = []

   def fix(container: JsonDict, key: str, label: str) -> None:
      """!Records (and renames) a field holding the stat's name.
      @param container  dict holding the field
      @param key        field name
      @param label      "where" string
      """
      if isinstance(container, dict) and container.get(key) == name:
         found.append(label)
         if new is not None:
            container[key] = new

   for c in battle.data_of(doc, "categories").get("categories", []):
      for key in ("offense", "defense"):
         fix(c, key, f"category {c.get('name')}" if isinstance(c, dict) else "category")
   for t in battle.data_of(doc, "traits").get("traits", []):
      for key in ("up", "down"):
         fix(t, key, f"trait {t.get('name')}" if isinstance(t, dict) else "trait")
   # a battler resource's maximum (D-25): renamed with the stat, and a stat a resource takes is not removed
   for r in battle.data_of(doc, "resources").get("resources", []):
      fix(r, "stat", f"resource {r.get('name')}" if isinstance(r, dict) else "resource")
   # The stage follows the stat only when it is named after it (a stage named otherwise keeps its name).
   e = stage_model.stat_stage(doc, name)
   lists = STAT_LISTS if e is not None and stage_model.name_of(e) == name else STAT_ONLY
   # C8: the field rules' expressions (lead rules, field action requirements) read stat.NAME and ROLE.NAME
   from . import field_expressions   # local: core.structure imports this module
   found += field_expressions.follow_stat(battle.merged(doc), name, new)
   return found + logic.per_owner(logic.references(doc, lists, name, new))


# -- editing (inside battle.edit()) -----------------------------------------------------------------------------------

def _take_flag(doc: Document, flag: str, keep: JsonDict) -> None:
   """!Takes a one-of flag (pool, order) or an at-most-one flag (odds) off every stat but one.
   @param doc   battle Document
   @param flag  "pool", "order" or "odds"
   @param keep  the stat that keeps it
   @return None
   """
   for st in stats(doc):
      if isinstance(st, dict) and st is not keep:
         st.pop(flag, None)


def _species_rows(doc: Document) -> list[list[Any]]:
   """!Every species' base list (created as needed) and every form's that gives its own (G4: a form's base is one
   value per stat too).
   @param doc  battle Document
   @return the live lists
   """
   out = []
   for sp in battle.data_of(doc, "species").get("species", []):
      if isinstance(sp, dict):
         if not isinstance(sp.get("base"), list):
            sp["base"] = []
         out.append(sp["base"])
         forms = sp.get("forms")
         for f in forms if isinstance(forms, list) else []:
            if isinstance(f, dict) and isinstance(f.get("base"), list):
               out.append(f["base"])
   return out


def _training_yields(doc: Document) -> dict[str, Any] | None:
   """!The structure's training yields, {stat: species field} (G4), live.
   @param doc  battle Document
   @return the dict, or None
   """
   tr = battle.data_of(doc, TRAINING_KEY).get(TRAINING_KEY)
   given = tr.get(YIELDS_KEY) if isinstance(tr, dict) else None
   return given if isinstance(given, dict) else None


def check_formula(doc: Document, formula: str) -> None:
   """!Refuses a stat formula the ruleset does not have (F12 [S14]; the compiler would refuse the data only when it
   compiles: the panel must not take the edit).
   @param doc      any manifest Document of a BattleProject (a Document on its own has no ruleset: anything goes)
   @param formula  the formula's name
   @return None
   @throws DocumentError when the project's ruleset has stat formulas and this is none of them
   """
   project = logic.project_of(doc)
   known = battle.stat_formulas(project.ruleset) if project is not None else []
   if known and formula not in known:
      raise DocumentError(f"no stat formula {formula!r} in the ruleset (stat formulas: {', '.join(known)})")


def add_stat(doc: Document, name: str, label: str | None = None, formula: str | None = None,
             index: int | None = None, base: int = battle.NEW_BASE_STAT, targets: list[str] | None = None,
             **flags: bool) -> int:
   """!Adds a stat; every species gets a base value for it.
   @param doc      battle Document
   @param name     stat name (lower-case identifier)
   @param label    in-game text, or None for the name
   @param formula  ruleset stat formula, or None for the formula of the first stat that is not the pool stat
   @param index    position, or None for the end
   @param base     every species' base value of the new stat
   @param targets  platforms whose limit applies (project_targets()), or None for DEFAULT_TARGETS
   @param flags    pool, order, odds, stage, trait (pool / order / odds taken off the other stats; stage, default
                   true but for the pool stat, adds the stat's stage: core.structure.stages.add_stage())
   @return its index
   @throws DocumentError for a bad name, a full list or an unknown flag
   """
   name = _check_new_name(doc, name)
   unknown = set(flags) - set(FLAGS)
   if unknown:
      raise DocumentError(f"unknown stat flag(s) {', '.join(sorted(unknown))} (flags: {', '.join(FLAGS)})")
   most = stat_limit(targets)
   lst = stats(doc)
   if len(lst) >= most:
      raise DocumentError(f"at most {most} stats on {', '.join(targets or DEFAULT_TARGETS)}")
   if formula is not None:
      check_formula(doc, formula)
   else:
      rows = stat_list(doc)
      formula = next((r["formula"] for r in rows if not r["pool"]), rows[0]["formula"] if rows else None)
      if formula is None:
         raise DocumentError("name the stat's formula (a stat formula of the ruleset)")
   at = len(lst) if index is None else max(0, min(len(lst), int(index)))
   st: JsonDict = {"name": name, "label": label.strip() if isinstance(label, str) and label.strip() else name,
                   "formula": formula}
   for flag, value in flags.items():
      if not isinstance(value, bool):
         raise DocumentError(f"{flag}: true or false")
      if flag in AT_MOST_ONE_FLAGS and value is not True:
         continue   # false is the default: not written
      if flag != STAGE_FLAG:
         st[flag] = value
   staged = flags.get(STAGE_FLAG, flags.get("pool") is not True)
   if staged and flags.get("pool") is True:
      raise DocumentError("the pool stat has no stage")
   lst.insert(at, st)
   for flag in ONE_OF_FLAGS + AT_MOST_ONE_FLAGS:
      if st.get(flag) is True:
         _take_flag(doc, flag, st)
   for row in _species_rows(doc):
      row.insert(min(at, len(row)), int(base))
   if staged:
      stage_model.add_stage(doc, stage_model.STAT_KIND, stat=name, index=stage_model.stat_stage_index(doc),
                            targets=targets)
   return at


def _record() -> Any:
   """!The record module (imported here: it imports this one).
   @return core.structure.record
   """
   from . import record
   return record


def remove_stat(doc: Document, name: str) -> None:
   """!Removes a stat with its species base values; traits that raise or lower it no longer do. Refused for
   the pool and order stats (give the flag to another stat first) and while a category or effect logic names
   it.
   @param doc   battle Document
   @param name  stat name
   @return None
   """
   st = stat_entry(doc, name)
   for flag in ONE_OF_FLAGS:
      if st.get(flag) is True:
         raise DocumentError(f"{name} is the {flag} stat: make another stat the {flag} stat first")
   refs = [r for r in stat_references(doc, name) if not r.startswith("trait ")]
   if refs:
      shown = ", ".join(sorted(set(refs))[:battle.REFERENCES_SHOWN])
      raise DocumentError(f"stat {name!r} is still used by: {shown}")
   before = battle.ruleset_problem(doc)
   i = stats(doc).index(st)
   for t in battle.data_of(doc, "traits").get("traits", []):
      for key in ("up", "down"):
         if isinstance(t, dict) and t.get(key) == name:
            del t[key]
   for row in _species_rows(doc):
      if i < len(row):
         del row[i]
   yields = _training_yields(doc)
   if yields is not None:
      yields.pop(name, None)   # G4: the stat's yield goes with it
   stage_model.drop_stat(doc, name)
   _record().drop_transfer_stat(doc, name)
   stats(doc).remove(st)
   battle.check_ruleset_kept(doc, f"stat {name!r}", before)   # the ruleset's pipelines / points may need it


def move_stat(doc: Document, name: str, delta: int) -> bool:
   """!Moves a stat up or down the list (its record and engine index), with every species' base value.
   @param doc    battle Document
   @param name   stat name
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   lst = stats(doc)
   i = lst.index(stat_entry(doc, name))
   j = i + delta
   if not 0 <= j < len(lst):
      return False
   lst[i], lst[j] = lst[j], lst[i]
   for row in _species_rows(doc):
      if max(i, j) < len(row):
         row[i], row[j] = row[j], row[i]
   return True


def rename_stat(doc: Document, old: str, new: str) -> int:
   """!Renames a stat and what names it (categories, traits, effect logic). A stat without its own
   transfer key keeps its old name as the key (written as "transfer"), so creatures transferred to or from
   other games still find the stat; a key that becomes equal to the new name is dropped again (the default).
   @param doc  battle Document
   @param old  current name
   @param new  new name
   @return references updated
   """
   st = stat_entry(doc, old)
   new = _check_new_name(doc, new, old)
   if new == old:
      return 0
   n = len(stat_references(doc, old, new))
   st["name"] = new
   yields = _training_yields(doc)
   if yields is not None and old in yields:   # G4: the training's yield keys name stats (their order kept)
      renamed = [(new if k == old else k, v) for k, v in yields.items()]
      yields.clear()
      yields.update(renamed)
      n += 1
   stage_model.rename_stat(doc, old, new)
   _record().rename_transfer_stat(doc, old, new)   # the layout's transfer defaults name stats
   # The transfer key defaults to the name: pin the old one so the key does not change with the name.
   if TRANSFER_KEY not in st:
      st[TRANSFER_KEY] = old
   if st[TRANSFER_KEY] == new:
      del st[TRANSFER_KEY]
   return n


def set_stat(doc: Document, name: str, key: str, value: Any) -> None:
   """!Changes one property of a stat (None puts a default back). Setting pool, order or odds takes the flag
   off the other stats; pool and order can't be taken off the only stat that has them (odds can: a game may
   have no odds stat).
   @param doc    battle Document
   @param name   stat name
   @param key    one of STAT_KEYS (the name: rename_stat())
   @param value  str for label, formula, transfer and short; bool for the flags; None for the default
   @return None
   """
   st = stat_entry(doc, name)
   if key not in STAT_KEYS:
      raise DocumentError(f"unknown stat property {key!r} (properties: {', '.join(STAT_KEYS)}; the name: rename)")
   if key == STAGE_FLAG:
      _set_stage_flag(doc, st, value)
      return
   if key in FLAGS:
      if value is not None and not isinstance(value, bool):
         raise DocumentError(f"{key}: true or false")
      if key == "pool" and value is True and stage_model.stat_stage(doc, name) is not None:
         raise DocumentError(f"{name} has a stage, and the pool stat has none: take its stage off first")
      if key in ONE_OF_FLAGS and value is not True and st.get(key) is True:
         raise DocumentError(f"{name} is the {key} stat: set {key} on another stat instead")
      if value is None or (key in AT_MOST_ONE_FLAGS and value is not True):
         st.pop(key, None)   # odds false is the default: not written
      else:
         st[key] = value
      if value is True and key in ONE_OF_FLAGS + AT_MOST_ONE_FLAGS:
         _take_flag(doc, key, st)
      return
   if value is not None and (not isinstance(value, str) or not value.strip()):
      raise DocumentError(f"{key}: a non-empty text")
   value = value.strip() if value is not None else None
   if key == "formula" and value is None:
      raise DocumentError("a stat always names its formula")
   if key == "formula":
      check_formula(doc, value)
   if key == TRANSFER_KEY:
      # The key the stat ends up with (none given: its name) must be no other stat's.
      wanted = value if value is not None else name
      holder = transfer_key_holder(doc, wanted, name)
      if holder is not None:
         raise DocumentError(f"the transfer key {wanted!r} is the stat {holder!r}'s already (each stat needs its "
                             "own key)")
   if key == SHORT_KEY:
      ed = st.get(EDITOR_KEY) if isinstance(st.get(EDITOR_KEY), dict) else {}
      if value is None:
         ed.pop(SHORT_KEY, None)
      else:
         ed[SHORT_KEY] = value
      if ed:
         st[EDITOR_KEY] = ed
      else:
         st.pop(EDITOR_KEY, None)
   elif value is None:
      st.pop(key, None)
   else:
      st[key] = value


# -- stages -----------------------------------------------------------------------------------------------------------

def _set_stage_flag(doc: Document, st: JsonDict, value: Any) -> None:
   """!Gives a stat a stage or takes it off (core.structure.stages; None: the default, a stage for every stat
   but the pool stat). Taking it off is refused while effect logic names the stage.
   @param doc    battle Document
   @param st     stat entry
   @param value  True, False or None
   @return None
   """
   if value is not None and not isinstance(value, bool):
      raise DocumentError(f"{STAGE_FLAG}: true or false")
   name = st.get("name")
   wanted = value if value is not None else st.get("pool") is not True
   have = stage_model.stat_stage(doc, name)
   if wanted and have is None:
      if st.get("pool") is True:
         raise DocumentError(f"{name} is the pool stat, which has no stage")
      stage_model.add_stage(doc, stage_model.STAT_KIND, stat=name, index=stage_model.stat_stage_index(doc),
                            targets=project_targets(doc.path))
   elif not wanted and have is not None:
      stage_model.remove_stage(doc, stage_model.name_of(have))


def stats_report(doc: Document, targets: list[str] | None = None) -> list[str]:
   """!The stats as text lines (the CLI's `stat list`): one per stat, then each target's budget.
   @param doc      battle Document
   @param targets  platforms, or None for DEFAULT_TARGETS
   @return lines
   """
   lines = []
   for r in stat_list(doc):
      flags = [f for f in FLAGS if r[f]]
      extra = [f"transfer {r['transfer']}"] if r["transfer"] != r["name"] else []
      extra += [f"short {r['short']}"] if r["short"] else []
      lines.append(f"{r['index']} {r['name']}: {json.dumps(r['label'])} formula {r['formula']} "
                   f"[{', '.join(flags) or 'no flags'}]" + (f" ({', '.join(extra)})" if extra else ""))
   for t, used, most in stat_budget(doc, targets):
      lines.append(f"{used}/{most} {t}")
   return lines
