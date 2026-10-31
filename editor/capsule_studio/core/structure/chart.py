"""!The type chart of battle data (D-22 A6, D-23 §3.2 "Type chart"): the
battle manifest's "chart", edited tier by tier and cell by cell.

    "chart": {"tiers": [{"name": "none", "decisive": "zero", "message": "no_effect"},
                        {"name": "half", "q8": 128}, {"name": "normal", "q8": 256},
                        {"name": "twice", "q8": 512}, {"name": "ko", "decisive": "ko"}],
              "combine": "exponent" | "multiply" | "sequential",
              "messages": {"above": "super_effective", "below": "not_very_effective"},
              "types_per_species": 2, "added_types": 1, "default": "normal",
              "matchups": {"Flame": {"Leaf": "twice", ...}, ...}}

A tier scales (q8: its Q8 factor, 256 = x1) or is decisive ("zero": no
effect; "ko": knocks out at once) and then may name an engine message said
when it applies. combine says how the tiers of a defender's types combine
("exponent" needs every scaling tier to be a power of two). A matchup names
a tier (the engine also takes a multiplier equal to one tier's factor; the
helpers here write names); matchups not given take "default" (default: the
tier whose factor is x1). types_per_species (1 or more) plus added_types
(types effects may add) is at most the engine's MAX_TYPES_PER. The engine's
battle compiler (battlec/chart.py compile_chart()) is the authority.

Each editing helper is one change: call it inside one battle.edit() and
Undo takes the whole change back (a tier rename rewrites every matchup and
the default in the same step).

migrate() turns a pre-E6a chart ({attacker: {defender: multiplier}}) into
this shape with the old engine's seven tiers.
"""
from __future__ import annotations

import re
from typing import Any

from .. import battle, engine
from ..document import Document, DocumentError

## A parsed JSON object.
JsonDict = dict[str, Any]
## One tier as tier_list() gives it (see tier_list()).
TierRow = dict[str, Any]

## The battle manifest's type chart.
CHART_KEY = "chart"
## The chart's tier list.
TIERS_KEY = "tiers"
## The chart's attacker -> defender -> tier table.
MATCHUPS_KEY = "matchups"
## The chart's messages object (above / below x1).
MESSAGES_KEY = "messages"
## The tier of matchups not given.
DEFAULT_KEY = "default"
## How the tiers combine.
COMBINE_KEY = "combine"
## Settings set_option() changes: combine, default, types_per_species, added_types, and the messages above /
## below x1.
OPTIONS = ("combine", "default", "types_per_species", "added_types", "above", "below")
## Options that are counts.
COUNT_OPTIONS = ("types_per_species", "added_types")
## Options that are message keys (under "messages").
MESSAGE_OPTIONS = ("above", "below")
## Properties set_tier() changes (the name: rename_tier(); shade is the studio's cell colour, under "editor").
TIER_PROPERTIES = ("q8", "decisive", "message", "shade")
## Key of a manifest entry's studio-only data (the compiler strips it).
EDITOR_KEY = "editor"
## Key of a tier's cell colour under "editor".
SHADE_KEY = "shade"
## A shade: "#rrggbb".
SHADE = re.compile(r"#[0-9a-fA-F]{6}")
## Kind of a scaling tier (tier_list() "kind").
SCALE = "scale"
## Q8 factor of x1.
Q8_ONE = 256
## Largest Q8 factor (the manifest's u16).
Q8_MAX = 0xFFFF
## Tiers of a pre-E6a chart (the old engine's Tier codes): multiplier -> (name, q8 or decisive kind).
OLD_TIERS = ((0, "none", "zero"), (0.25, "quarter", Q8_ONE // 4), (0.5, "half", Q8_ONE // 2), (1, "normal", Q8_ONE),
             (2, "twice", Q8_ONE * 2), (4, "quad", Q8_ONE * 4), ("ko", "ko", "ko"))
## Messages of the pre-E6a engine's chart (the zero tier said no_effect; above / below x1 as before).
OLD_MESSAGES = {"zero": "no_effect", "above": "super_effective", "below": "not_very_effective"}
## Types per species of the pre-E6a engine.
OLD_TYPES_PER_SPECIES = 2


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def _ct() -> Any:
   """!The engine's battle compiler chart module (its defaults).
   @return module
   """
   return engine.tool("battlec.chart")


def combine_modes() -> list[str]:
   """!The combine modes (capsule::battle::Combine order).
   @return names
   """
   return list(_bc().COMBINE_MODES)


def decisive_kinds() -> list[str]:
   """!The decisive tier kinds ("zero", "ko").
   @return names
   """
   return list(_bc().TIER_KINDS[1:])


def max_tiers() -> int:
   """!Most tiers a chart has (capsule::battle::kMaxTiers).
   @return count
   """
   return int(_bc().MAX_TIERS)


def max_types_per() -> int:
   """!Most types a battler has, the species' and the added ones together (capsule::battle::kMaxTypesPer).
   @return count
   """
   return int(_bc().MAX_TYPES_PER)


def message_keys(doc: Document | None = None) -> list[str]:
   """!The engine's message keys a tier or the above / below messages may name: the ones the battle data gives
   (the engine's declared_messages(): an optional message the manifest leaves out cannot be named; C1).
   @param doc  any manifest Document of the battle, or None (the required messages only)
   @return keys, in Msg order
   """
   given = battle.data_of(doc, "messages").get("messages") if doc is not None else None
   return [m for m in _bc().declared_messages(given if isinstance(given, dict) else {}) if m is not None]


# -- reading -----------------------------------------------------------------------------------------------------------

def _read(doc: Document) -> JsonDict:
   """!The chart for reading (nothing created).
   @param doc  battle Document
   @return the live dict, or {} when the manifest has none
   """
   given = battle.data_of(doc, CHART_KEY).get(CHART_KEY)
   return given if isinstance(given, dict) else {}


def chart(doc: Document) -> JsonDict:
   """!The battle manifest's chart.
   @param doc  battle Document
   @return the dict (live; created when absent; change it only inside doc.edit())
   """
   given = battle.data_of(doc, CHART_KEY).get(CHART_KEY)
   if not isinstance(given, dict):
      given = battle.data_of(doc, CHART_KEY)[CHART_KEY] = {}
   return given


def tiers(doc: Document) -> list[JsonDict]:
   """!The chart's tier list.
   @param doc  battle Document
   @return the list (live; created when absent)
   """
   c = chart(doc)
   if not isinstance(c.get(TIERS_KEY), list):
      c[TIERS_KEY] = []
   return c[TIERS_KEY]


def matchups(doc: Document) -> JsonDict:
   """!The chart's matchups.
   @param doc  battle Document
   @return {attacker: {defender: tier}} (live; created when absent)
   """
   c = chart(doc)
   if not isinstance(c.get(MATCHUPS_KEY), dict):
      c[MATCHUPS_KEY] = {}
   return c[MATCHUPS_KEY]


def _listed_tiers(doc: Document) -> list[JsonDict]:
   """!The tiers for reading.
   @param doc  battle Document
   @return the live entries that are objects
   """
   given = _read(doc).get(TIERS_KEY)
   return [t for t in given if isinstance(t, dict)] if isinstance(given, list) else []


def tier_names(doc: Document) -> list[str]:
   """!The tier names in order.
   @param doc  battle Document
   @return names
   """
   return [t["name"] for t in _listed_tiers(doc) if isinstance(t.get("name"), str)]


def tier_entry(doc: Document, name: str) -> JsonDict:
   """!A tier by name.
   @param doc   battle Document
   @param name  tier name
   @return the dict (live)
   @throws DocumentError when there is none
   """
   for t in _listed_tiers(doc):
      if t.get("name") == name:
         return t
   raise DocumentError(f"no tier {name!r} (tiers: {', '.join(tier_names(doc)) or 'none'})")


def kind_of(tier: JsonDict) -> str:
   """!A tier's kind.
   @param tier  tier entry
   @return "scale", "zero" or "ko"
   """
   decisive = tier.get("decisive")
   return decisive if isinstance(decisive, str) else SCALE


def exponent(q8: Any) -> int | None:
   """!The exponent of a power-of-two Q8 factor (the exponent combine mode adds them; the engine's
   battlec.chart.exponent_of()).
   @param q8  factor
   @return e with q8 == 256 * 2^e, or None (also for a value that is no whole number)
   """
   if not isinstance(q8, int) or isinstance(q8, bool):
      return None
   return _ct().exponent_of(q8)


def _shade(tier: JsonDict) -> str | None:
   """!A tier's studio cell colour.
   @param tier  tier entry
   @return editor.shade, or None
   """
   ed = tier.get(EDITOR_KEY)
   shade = ed.get(SHADE_KEY) if isinstance(ed, dict) else None
   return shade if isinstance(shade, str) else None


def default_tier(doc: Document) -> str | None:
   """!The tier of matchups not given: the chart's "default", else the first tier with factor x1.
   @param doc  battle Document
   @return its name, or None when there is none
   """
   given = _read(doc).get(DEFAULT_KEY)
   if isinstance(given, str):
      return given
   return next((t.get("name") for t in _listed_tiers(doc) if kind_of(t) == SCALE and t.get("q8") == Q8_ONE), None)


def options(doc: Document) -> JsonDict:
   """!The chart settings as the engine resolves them.
   @param doc  battle Document
   @return {combine, default (resolved), default_given (the manifest names one), types_per_species, added_types,
           above, below}
   """
   ct = _ct()
   c = _read(doc)
   msgs = c.get(MESSAGES_KEY) if isinstance(c.get(MESSAGES_KEY), dict) else {}
   return {"combine": c.get(COMBINE_KEY, ct.DEFAULT_COMBINE), "default": default_tier(doc),
           "default_given": DEFAULT_KEY in c,
           "types_per_species": c.get("types_per_species", ct.DEFAULT_TYPES_PER_SPECIES),
           "added_types": c.get("added_types", ct.DEFAULT_ADDED_TYPES),
           "above": msgs.get("above"), "below": msgs.get("below")}


def types_per_species(doc: Document | None) -> int:
   """!Most types a species has (chart.types_per_species).
   @param doc  battle Document, or None (the engine's default)
   @return count
   """
   if doc is None:
      return int(_ct().DEFAULT_TYPES_PER_SPECIES)
   value = options(doc)["types_per_species"]
   return value if isinstance(value, int) and not isinstance(value, bool) else int(_ct().DEFAULT_TYPES_PER_SPECIES)


def tier_of(doc: Document, value: Any) -> str | None:
   """!The tier a matchup value means: a tier name, or a multiplier equal to one scaling tier's factor (0: the
   zero tier), as the engine reads it.
   @param doc    battle Document
   @param value  a matchup value
   @return the tier's name, or None when it means none (or several)
   """
   rows = _listed_tiers(doc)
   if isinstance(value, str):
      return value if value in tier_names(doc) else None
   if isinstance(value, (int, float)) and not isinstance(value, bool):
      if value == 0:
         found = [t["name"] for t in rows if kind_of(t) == "zero"]
      else:
         found = [t["name"] for t in rows if kind_of(t) == SCALE and t.get("q8") == value * Q8_ONE]
      return found[0] if len(found) == 1 else None
   return None


def matchup(doc: Document, attacker: str, defender: str) -> Any:
   """!A chart cell.
   @param doc       battle Document
   @param attacker  type name
   @param defender  type name
   @return the tier's name (the default tier when the cell is not given), or the raw value when it names no tier
   """
   rows = _read(doc).get(MATCHUPS_KEY)
   row = rows.get(attacker) if isinstance(rows, dict) else None
   if not isinstance(row, dict) or defender not in row:
      return default_tier(doc)
   found = tier_of(doc, row[defender])
   return found if found is not None else row[defender]


def tier_uses(doc: Document, name: str) -> int:
   """!How many cells name a tier (written; the default tier's unwritten cells not counted).
   @param doc   battle Document
   @param name  tier name
   @return count
   """
   rows = _read(doc).get(MATCHUPS_KEY)
   rows = rows if isinstance(rows, dict) else {}
   return sum(1 for row in rows.values() if isinstance(row, dict) for v in row.values() if tier_of(doc, v) == name)


def tier_list(doc: Document) -> list[TierRow]:
   """!Every tier with what the panel shows.
   @param doc  battle Document
   @return copies in order: index, name, kind ("scale", "zero", "ko"), q8 (None for a decisive tier), factor
           (q8 / 256, or None), exponent (or None), message, uses (cells naming it), default (it is the default),
           shade (editor.shade, or None)
   """
   default = default_tier(doc)
   out = []
   for i, t in enumerate(_listed_tiers(doc)):
      kind = kind_of(t)
      q8 = t.get("q8") if kind == SCALE else None
      good = isinstance(q8, int) and not isinstance(q8, bool)
      out.append({"index": i, "name": t.get("name"), "kind": kind, "q8": q8,
                  "factor": q8 / Q8_ONE if good else None, "exponent": exponent(q8) if good else None,
                  "message": t.get("message"), "uses": tier_uses(doc, t.get("name")),
                  "default": t.get("name") == default, "shade": _shade(t)})
   return out


def type_names(doc: Document) -> list[str]:
   """!The battle's type names in order.
   @param doc  battle Document
   @return names
   """
   return [t.get("name") for t in battle.entries(doc, "types") if isinstance(t, dict)]


def grid(doc: Document) -> list[list[Any]]:
   """!The whole chart: one row per attacking type, one cell per defending type (matchup()).
   @param doc  battle Document
   @return rows in type order
   """
   names = type_names(doc)
   return [[matchup(doc, a, d) for d in names] for a in names]


# -- editing (inside battle.edit()) ------------------------------------------------------------------------------------

def _check_tier_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A tier name no other tier has.
   @param doc      battle Document
   @param name     wanted name
   @param current  the tier being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   if not isinstance(name, str) or not name.strip():
      raise DocumentError("a tier name can't be empty")
   name = name.strip()
   if name != current and name in tier_names(doc):
      raise DocumentError(f"there is already a tier {name!r}")
   return name


def _check_q8(value: Any) -> int:
   """!A scaling tier's Q8 factor.
   @param value  the factor
   @return it
   @throws DocumentError when it is not one
   """
   if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= Q8_MAX:
      raise DocumentError(f"a tier's q8 is its Q8 factor from 0 to {Q8_MAX} ({Q8_ONE} = x1; got {value!r})")
   return value


def _check_message(doc: Document, value: Any) -> str | None:
   """!An engine message key the battle data gives, or None.
   @param doc    any manifest Document of the battle
   @param value  the key
   @return it
   @throws DocumentError when the data gives no such message
   """
   if value is not None and value not in message_keys(doc):
      raise DocumentError(f"no engine message {value!r} (an optional message needs its text in the battle's "
                          f"messages first)")
   return value


def add_tier(doc: Document, name: str, q8: int | None = None, decisive: str | None = None,
             message: str | None = None, index: int | None = None) -> int:
   """!Adds a tier: a scaling one (q8) or a decisive one (decisive, with an optional message).
   @param doc       battle Document
   @param name      its name
   @param q8        Q8 factor (a scaling tier); None with no decisive: x1
   @param decisive  "zero" or "ko" (a decisive tier), or None
   @param message   a decisive tier's engine message key, or None
   @param index     position, or None for the end
   @return its index
   @throws DocumentError for what the engine refuses
   """
   name = _check_tier_name(doc, name)
   lst = tiers(doc)
   if len(lst) >= max_tiers():
      raise DocumentError(f"at most {max_tiers()} tiers")
   entry: JsonDict = {"name": name}
   if decisive is not None:
      if decisive not in decisive_kinds() or q8 is not None:
         raise DocumentError(f"a decisive tier is {' or '.join(decisive_kinds())}, without q8")
      entry["decisive"] = decisive
      if _check_message(doc, message) is not None:
         entry["message"] = message
   else:
      if message is not None:
         raise DocumentError("only a decisive tier has a message (a scaling result says the above / below "
                             "messages)")
      entry["q8"] = _check_q8(Q8_ONE if q8 is None else q8)
   at = len(lst) if index is None else max(0, min(len(lst), int(index)))
   lst.insert(at, entry)
   return at


def _rename_cells(doc: Document, old: str, new: str | None) -> int:
   """!Rewrites every cell naming a tier (by name or by its multiplier).
   @param doc  battle Document
   @param old  the tier
   @param new  the tier the cells name instead, or None to only count
   @return cells changed
   """
   n = 0
   rows = _read(doc).get(MATCHUPS_KEY)
   for row in rows.values() if isinstance(rows, dict) else []:
      if not isinstance(row, dict):
         continue
      for d, v in list(row.items()):
         if tier_of(doc, v) == old:
            n += 1
            if new is not None:
               row[d] = new
   return n


def _drop_default_cells(doc: Document) -> None:
   """!Leaves out the cells that name the default tier (they are the default), and rows left empty.
   @param doc  battle Document
   @return None
   """
   default = default_tier(doc)
   rows = _read(doc).get(MATCHUPS_KEY)
   if not isinstance(rows, dict):
      return
   for a in list(rows):
      row = rows[a]
      if isinstance(row, dict):
         for d in [d for d, v in row.items() if v == default]:
            del row[d]
         if not row:
            del rows[a]


def remove_tier(doc: Document, name: str, replace: str | None = None) -> int:
   """!Removes a tier. Cells naming it (and the default, when it is the default) take another tier, or the
   removal is refused while there are any.
   @param doc      battle Document
   @param name     tier name
   @param replace  the tier those cells take, or None
   @return cells changed
   """
   e = tier_entry(doc, name)
   uses = _rename_cells(doc, name, None)
   is_default = _read(doc).get(DEFAULT_KEY) == name
   if replace is None and (uses or is_default):
      what = f"{uses} cell(s)" + (" and the default" if is_default else "")
      raise DocumentError(f"tier {name!r} is used by {what}: give the tier they take instead")
   if replace is not None:
      if replace == name:
         raise DocumentError("a tier can't replace itself")
      tier_entry(doc, replace)
      _rename_cells(doc, name, replace)
      if is_default:
         chart(doc)[DEFAULT_KEY] = replace
   before = battle.ruleset_problem(doc)
   tiers(doc).remove(e)
   _drop_default_cells(doc)
   battle.check_ruleset_kept(doc, f"tier {name!r}", before)   # the ruleset's pipelines / points may need it
   return uses


def rename_tier(doc: Document, old: str, new: str) -> int:
   """!Renames a tier and every cell and the default naming it.
   @param doc  battle Document
   @param old  current name
   @param new  new name
   @return cells changed
   """
   e = tier_entry(doc, old)
   new = _check_tier_name(doc, new, old)
   if new == old:
      return 0
   n = _rename_cells(doc, old, new)
   c = chart(doc)
   if c.get(DEFAULT_KEY) == old:
      c[DEFAULT_KEY] = new
   e["name"] = new
   return n


def move_tier(doc: Document, name: str, delta: int) -> bool:
   """!Moves a tier up or down the list (cells name tiers, so nothing else changes; the first x1 tier is the
   default when the chart names none).
   @param doc    battle Document
   @param name   tier name
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   lst = tiers(doc)
   i = lst.index(tier_entry(doc, name))
   j = i + delta
   if not 0 <= j < len(lst):
      return False
   lst[i], lst[j] = lst[j], lst[i]
   return True


def set_tier(doc: Document, name: str, key: str, value: Any) -> None:
   """!Changes one property of a tier.
   @param doc    battle Document
   @param name   tier name
   @param key    q8 (a scaling tier's factor), decisive ("zero" / "ko" makes it decisive, None makes it a scaling
                 tier at x1), message (a decisive tier's engine message key, None: none), shade ("#rrggbb", the
                 studio's cell colour; None: the editor's default)
   @param value  the value
   @return None
   @throws DocumentError for what the engine refuses
   """
   e = tier_entry(doc, name)
   if key not in TIER_PROPERTIES:
      raise DocumentError(f"unknown tier property {key!r} (properties: {', '.join(TIER_PROPERTIES)}; the name: "
                          "rename)")
   if key == SHADE_KEY:
      if value is not None and (not isinstance(value, str) or not SHADE.fullmatch(value)):
         raise DocumentError(f"a shade is #rrggbb (got {value!r})")
      ed = e.get(EDITOR_KEY) if isinstance(e.get(EDITOR_KEY), dict) else {}
      if value is None:
         ed.pop(SHADE_KEY, None)
      else:
         ed[SHADE_KEY] = value
      if ed:
         e[EDITOR_KEY] = ed
      else:
         e.pop(EDITOR_KEY, None)
      return
   # Cells written as a multiplier would mean another tier once the factor changes: name the tier instead.
   _rename_cells(doc, name, name)
   if key == "q8":
      if kind_of(e) != SCALE:
         raise DocumentError(f"{name} is decisive: make it a scaling tier first (decisive null)")
      e["q8"] = _check_q8(value)
   elif key == "decisive":
      if value is None:
         e.pop("decisive", None)
         e.pop("message", None)
         e.setdefault("q8", Q8_ONE)
      elif value not in decisive_kinds():
         raise DocumentError(f"decisive is {' or '.join(decisive_kinds())}, or null for a scaling tier")
      else:
         e.pop("q8", None)
         e["decisive"] = value
   else:
      if kind_of(e) == SCALE and value is not None:
         raise DocumentError("only a decisive tier has a message (a scaling result says the above / below "
                             "messages)")
      if _check_message(doc, value) is None:
         e.pop("message", None)
      else:
         e["message"] = value


def set_option(doc: Document, key: str, value: Any) -> None:
   """!Changes one chart setting (None puts the engine's default back).
   @param doc    battle Document
   @param key    one of OPTIONS
   @param value  combine: a mode; default: a tier name; types_per_species / added_types: counts; above / below:
                 engine message keys
   @return None
   @throws DocumentError for what the engine refuses
   """
   c = chart(doc)
   if key not in OPTIONS:
      raise DocumentError(f"unknown chart setting {key!r} (settings: {', '.join(OPTIONS)})")
   if key in MESSAGE_OPTIONS:
      msgs = c.get(MESSAGES_KEY) if isinstance(c.get(MESSAGES_KEY), dict) else {}
      if _check_message(doc, value) is None:
         msgs.pop(key, None)
      else:
         msgs[key] = value
      if msgs:
         c[MESSAGES_KEY] = msgs
      else:
         c.pop(MESSAGES_KEY, None)
      return
   if value is None:
      c.pop(key, None)
   elif key == COMBINE_KEY:
      if value not in combine_modes():
         raise DocumentError(f"combine is one of {', '.join(combine_modes())}")
      c[key] = value
   elif key == DEFAULT_KEY:
      tier_entry(doc, value)
      c[key] = value
   else:
      if not isinstance(value, int) or isinstance(value, bool):
         raise DocumentError(f"{key}: a whole number")
      c[key] = value
   if key in COUNT_OPTIONS:
      _check_counts(doc)
   if key == DEFAULT_KEY:
      _drop_default_cells(doc)


def _check_counts(doc: Document) -> None:
   """!Refuses type counts the engine refuses, and fewer types per species than a species has.
   @param doc  battle Document
   @return None
   """
   o = options(doc)
   per, added, most = o["types_per_species"], o["added_types"], max_types_per()
   if not isinstance(per, int) or not 1 <= per <= most:
      raise DocumentError(f"types_per_species is 1 to {most}")
   if not isinstance(added, int) or not 0 <= added <= most - per:
      raise DocumentError(f"added_types is 0 to {most - per} (types_per_species + added_types <= {most})")
   over = [s.get("name") for s in battle.entries(doc, "species")
           if isinstance(s, dict) and isinstance(s.get("types"), list) and len(s["types"]) > per]
   if over:
      shown = ", ".join(map(str, over[:battle.REFERENCES_SHOWN]))
      raise DocumentError(f"these species have more than {per} types: {shown}")


def set_matchup(doc: Document, attacker: str, defender: str, tier: Any) -> None:
   """!Sets a chart cell (the default tier leaves the cell out).
   @param doc       battle Document
   @param attacker  type name
   @param defender  type name
   @param tier      a tier name, or a multiplier equal to one tier's factor (0: the zero tier)
   @return None
   """
   names = type_names(doc)
   for t in (attacker, defender):
      if t not in names:
         raise DocumentError(f"no type {t!r}")
   found = tier_of(doc, tier)
   if found is None:
      raise DocumentError(f"a tier ({', '.join(tier_names(doc))}) or the multiplier of exactly one tier, got "
                          f"{tier!r}")
   rows = matchups(doc)
   row = rows.setdefault(attacker, {})
   if found == default_tier(doc):
      row.pop(defender, None)
      if not row:
         del rows[attacker]
   else:
      row[defender] = found


def step_tier(doc: Document, attacker: str, defender: str, delta: int) -> str:
   """!The tier a cell steps to (the next or previous tier in list order, wrapping).
   @param doc       battle Document
   @param attacker  type name
   @param defender  type name
   @param delta     +1 next, -1 previous
   @return the tier name
   @throws DocumentError when the chart has no tiers
   """
   names = tier_names(doc)
   if not names:
      raise DocumentError("the chart has no tiers")
   cur = matchup(doc, attacker, defender)
   return names[(names.index(cur) + delta) % len(names)] if cur in names else names[0]


def rename_type(data: JsonDict, old: str, new: str | None) -> bool:
   """!Follows (or only finds) a type in the matchups (core.battle.references()).
   @param data  battle manifest data
   @param old   type name
   @param new   new name, or None to only look
   @return True when the matchups name the type
   """
   rows = (data.get(CHART_KEY) or {}).get(MATCHUPS_KEY) if isinstance(data.get(CHART_KEY), dict) else None
   if not isinstance(rows, dict):
      return False
   found = old in rows
   if found and new is not None:
      rows[new] = rows.pop(old)
   for row in rows.values():
      if isinstance(row, dict) and old in row:
         found = True
         if new is not None:
            row[new] = row.pop(old)
   return found


def drop_type(data: JsonDict, name: str) -> None:
   """!A type was removed: its row and column go (rows left empty too).
   @param data  battle manifest data
   @param name  type name
   @return None
   """
   rows = (data.get(CHART_KEY) or {}).get(MATCHUPS_KEY) if isinstance(data.get(CHART_KEY), dict) else None
   if not isinstance(rows, dict):
      return
   rows.pop(name, None)
   for row in rows.values():
      if isinstance(row, dict):
         row.pop(name, None)
   for k in [k for k, row in rows.items() if isinstance(row, dict) and not row]:
      del rows[k]


# -- text --------------------------------------------------------------------------------------------------------------

def tier_line(row: TierRow) -> str:
   """!A tier as one line of text (the CLI's `tier list`).
   @param row  a tier_list() row
   @return the line
   """
   if row["kind"] == SCALE:
      what = f"q8 {row['q8']}" + (f" (x{row['factor']:g})" if row["factor"] is not None else "")
      what += f", exponent {row['exponent']}" if row["exponent"] is not None else ""
   else:
      what = f"decisive {row['kind']}" + (f", message {row['message']}" if row["message"] else "")
   tail = " [default]" if row["default"] else ""
   return f"{row['index']} {row['name']}: {what}; {row['uses']} cell(s){tail}"


def report(doc: Document) -> list[str]:
   """!The tiers, the settings and the grid as text lines.
   @param doc  battle Document
   @return lines
   """
   o = options(doc)
   lines = [tier_line(r) for r in tier_list(doc)]
   lines.append(f"combine {o['combine']}, default {o['default']}, types per species {o['types_per_species']}, "
                f"added types {o['added_types']}, above {o['above']}, below {o['below']}")
   names = type_names(doc)
   for a, row in zip(names, grid(doc)):
      lines.append(f"{a}: " + ", ".join(f"{d} {v}" for d, v in zip(names, row) if v != o["default"]))
   return lines


# -- pre-E6a data ------------------------------------------------------------------------------------------------------

def needs_migration(data: JsonDict) -> bool:
   """!Whether battle data still has a pre-E6a chart (the engine refuses it).
   @param data  battle manifest data
   @return True when migrate() has something to do
   """
   c = data.get(CHART_KEY)
   return isinstance(c, dict) and TIERS_KEY not in c


def migrate(doc: Document) -> bool:
   """!Turns a pre-E6a chart ({attacker: {defender: multiplier}}) into tiers and matchups: the old engine's
   seven tiers (none, quarter, half, normal, twice, quad, ko), combine exponent, the old messages, two types per
   species.
   @param doc  battle Document
   @return True when something changed
   """
   d = battle.merged(doc)
   if not needs_migration(d):
      return False
   old = d[CHART_KEY]
   names = {m: name for m, name, _v in OLD_TIERS}
   tier_rows = []
   for _m, name, v in OLD_TIERS:
      if isinstance(v, str):
         row: JsonDict = {"name": name, "decisive": v}
         if v in OLD_MESSAGES:
            row["message"] = OLD_MESSAGES[v]
         tier_rows.append(row)
      else:
         tier_rows.append({"name": name, "q8": v})
   rows: JsonDict = {}
   for a, row in old.items():
      if isinstance(row, dict):
         rows[a] = {dname: names.get(v, v) for dname, v in row.items() if v != 1}
   battle.data_of(doc, CHART_KEY)[CHART_KEY] = {TIERS_KEY: tier_rows, COMBINE_KEY: "exponent",
                   MESSAGES_KEY: {k: OLD_MESSAGES[k] for k in MESSAGE_OPTIONS},
                   "types_per_species": OLD_TYPES_PER_SPECIES, MATCHUPS_KEY: {a: r for a, r in rows.items() if r}}
   return True

