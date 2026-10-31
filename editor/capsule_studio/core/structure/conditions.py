"""!The condition records of battle data (D-22 A3-A5, D-23 §3.2
"Conditions"): the battle manifest's statuses, volatiles, weathers,
side_conditions and field_conditions, edited record by record.

    "statuses": [{"name": "Sleep", "turns": [1, 3], "color": 0, "texts": {"inflicted": "...", "skip": "...",
                  "cured": "...", "already": "..."}}, ...],
    "volatiles": [{"name": "confusion", "duration": [1, 4], "passes": true,
                   "texts": {"start": {"message": "became_confused"}, ...}}, ...],
    "weathers": [{"name": "Rain", "turns": 5, "texts": {"started": "...", ...}}, ...],
    "side_conditions": [{"name": "spikes", "layers": 3, "turns": 0, "texts": {...}}],
    "field_conditions": [{"name": "gravity", "turns": 5}]

A record keeps what the engine needs; its declarative fields (residual,
skip, cure, turns, duration, chain, immune_types...) are templates the
engine's battle compiler expands into effect code (battlec/conditions.py,
the authority: it decides what is valid, and its message shows in the
editors). FIELDS lists every field of each kind with how it is edited; the
keys are the compiler's own (battle_compiler.KEYS), and the choice lists
(durations, where a duration counts down, what clears a volatile, the text
slots of statuses and weathers, the engine messages) are the compiler's.
A record's manifest point handlers ("handlers", statuses and weathers) are
edited through core.holders; its `.ceffect` logic on the Effects page.

Each editing helper is one change: call it inside one battle.edit() and
Undo takes the whole change back. A rename follows the effect logic that
names the record (its own owner block too, through the AST of the .ceffect
sources; the source edits join the battle edit's undo step), and so do the
game's bench scenarios (core.bench.follow_rename(), same undo step [S14]);
bench_uses() lists the saved scenarios naming a record.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from .. import battle, codepage, engine, logic, manifest_io
from ..document import Document, DocumentError

if TYPE_CHECKING:
   from ..battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]


## Field kind: true or left out.
BOOL = "bool"
## Field kind: a number 0..255.
BYTE = "byte"
## Field kind: a side condition's layer cap, 1..255.
LAYERS = "layers"
## Field kind: a share of the holder's max HP ("1/8", Q8 up to 255).
SHARE = "share"
## Field kind: odds "n/m" (m up to 255).
ODDS = "odds"
## Field kind: a volatile's lost turn (true: always, or odds).
SKIP = "skip"
## Field kind: [min, max] turns (both 0: none).
PAIR = "pair"
## Field kind: type names.
TYPES = "types"
## Field kind: one type name.
TYPE = "type"
## Field kind: one move flag of the manifest.
FLAG = "flag"
## Field kind: tag names of the manifest.
TAGS = "tags"
## Field kind: an escalating residual (true, or {"cap": n}).
ESCALATING = "escalating"
## Field kind: a volatile's duration ("turn", "until_switch" or [min, max]).
DURATION = "duration"
## Field kind: where a [min, max] duration counts down.
COUNTS = "counts"
## Field kind: the events that clear a volatile.
CLEARS = "clears"
## Field kind: a volatile's chain {den, cap, kept_by}.
CHAIN = "chain"
## Field kind: whom a volatile is bound to (engine G1: bound_to; it ends when that battler leaves), or left out.
BOUND = "bound"

## The fields of each kind in the order editors show them, with their field kind ("name", "texts" and "handlers"
## are edited apart: rename_record(), set_text(), core.holders).
FIELDS = {
   "status": {"residual": SHARE, "escalating": ESCALATING, "skip": ODDS, "cure": ODDS, "turns": PAIR,
              "immune_types": TYPES, "thawed_by_move": FLAG, "thawed_by_hit": TYPE, "cured_on_switch": BOOL,
              "color": BYTE, "tags": TAGS},
   "volatile": {"duration": DURATION, "counts": COUNTS, "counter": BOOL, "word": BOOL, "clears_on": CLEARS,
                "passes": BOOL, "skip": SKIP, "chain": CHAIN, "hud": BOOL, "tags": TAGS, "bound_to": BOUND},
   "weather": {"residual": SHARE, "immune_types": TYPES, "turns": BYTE, "tags": TAGS},
   "side_condition": {"turns": BYTE, "layers": LAYERS, "tags": TAGS},
   "field_condition": {"turns": BYTE, "tags": TAGS},
}
## Keys of a record that FIELDS does not list.
APART_KEYS = ("name", "texts", "handlers")
## The kinds whose texts are fixed slots of engine events (StatusText / WeatherText); the others' are owner
## texts or engine messages under any slot name.
FIXED_TEXT_KINDS = ("status", "weather")
## The battle compiler's re-export of the text slots the condition templates show, by kind with owner texts
## (template_slots(); E9: VOLATILE_TEXT_SLOTS start, already, end, skip; CONDITION_TEXT_SLOTS start, already,
## end). Other slots are texts the record's own logic shows (`text SLOT;`).
TEMPLATE_SLOT_NAMES = {"volatile": "VOLATILE_TEXT_SLOTS", "side_condition": "CONDITION_TEXT_SLOTS",
                       "field_condition": "CONDITION_TEXT_SLOTS"}
## Key of an own text that names an engine message.
MESSAGE_KEY = "message"
## The kind of the primary statuses (the recruit section's status bonuses name them, G3).
STATUS_KIND = "status"
## A volatile's duration given as [min, max].
RANGE_DURATION = "range"
## A volatile's default duration (battlec conditions.compile_volatiles()).
DEFAULT_DURATION = "until_switch"
## Where a [min, max] duration counts down by default.
DEFAULT_COUNTS = "before_move"
## Numbers in a [min, max] pair.
PAIR_LEN = 2
## The key of an escalating residual's cap.
CAP_KEY = "cap"
## Keys of a chain.
CHAIN_KEYS = ("den", "cap", "kept_by")
## An own text slot name: a lower-case identifier.
SLOT_NAME = re.compile(r"[a-z_][a-z0-9_]*")
## Most bench scenario uses one "where" list shows per scenario file.
BENCH_SHOWN = 8


class BudgetRow(NamedTuple):
   """!One budget of the condition records (the engine's fixed storage)."""

   ## What is counted ("volatile bits").
   label: str
   ## How many the data uses.
   used: int
   ## The engine's most.
   most: int
   ## A note ("6 id bits"), or "".
   note: str


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def kinds() -> list[str]:
   """!The condition kinds this module edits: the effect owner kinds (the engine's LOGIC_KINDS, in its order) that
   are condition records (effect_compiler.CONDITION_KINDS: statuses, weathers, volatiles, side / field conditions).
   @return kinds
   """
   conditions = engine.tool("effect_compiler").CONDITION_KINDS
   return [k for k in _bc().LOGIC_KINDS if k in conditions]


def _lc() -> Any:
   """!The engine's battle compiler layout module (status id bits).
   @return module
   """
   return engine.tool("battlec.layout")


# -- the engine's tables -----------------------------------------------------------------------------------------------

def handler_kinds() -> list[str]:
   """!The condition kinds whose records hold point handlers (core.logic.point_owner_lists(), the engine's
   OWNER_KINDS: statuses and weathers in the manifest's "handlers"; E13b: volatiles and side conditions as `.ceffect`
   point members, core.holders.logic_lists()).
   @return kinds, in kinds() order
   """
   owners = logic.point_owner_lists()
   return [k for k in kinds() if list_key(k) in owners]


def list_key(kind: str) -> str:
   """!The battle manifest list of a kind (the engine's battlec LOGIC_KINDS).
   @param kind  one of kinds()
   @return e.g. "side_conditions"
   @throws DocumentError for an unknown kind
   """
   if kind not in kinds():
      raise DocumentError(f"unknown condition kind {kind!r} (kinds: {', '.join(kinds())})")
   return _bc().LOGIC_KINDS[kind]


def engine_keys(kind: str) -> set[str]:
   """!The keys the engine's compiler takes in a record of a kind.
   @param kind  one of kinds()
   @return keys
   """
   list_key(kind)
   return set(_bc().KEYS[kind])


def fields(kind: str) -> dict[str, str]:
   """!The fields of a kind the engine takes, in editor order, with their field kinds.
   @param kind  one of kinds()
   @return {key: field kind}
   """
   keys = engine_keys(kind)
   return {k: v for k, v in FIELDS[kind].items() if k in keys}


def durations() -> list[str]:
   """!A volatile's duration words, then RANGE_DURATION for [min, max] (the compiler's DURATIONS).
   @return choices
   """
   return list(_bc().DURATIONS) + [RANGE_DURATION]


def count_modes() -> list[str]:
   """!Where a [min, max] duration counts down (the compiler's COUNTS).
   @return choices
   """
   return list(_bc().COUNTS)


def clear_events() -> list[str]:
   """!The events a volatile's clears_on may name (the compiler's CLEARS_ON).
   @return names
   """
   return list(_bc().CLEARS_ON)


def bound_choices() -> list[str]:
   """!Whom a volatile may be bound to (the compiler's BOUND_TO; engine G1: it ends when that battler leaves the
   field or faints).
   @return names
   """
   return list(_bc().BOUND_TO)


def template_slots(kind: str) -> list[str]:
   """!The text slots a kind's condition template shows (the compiler's VOLATILE_TEXT_SLOTS /
   CONDITION_TEXT_SLOTS).
   @param kind  one of kinds()
   @return slots in template order ([] for the kinds with fixed slots: fixed_slots())
   """
   name = TEMPLATE_SLOT_NAMES.get(kind)
   return list(getattr(_bc(), name)) if name is not None else []


def fixed_slots(kind: str) -> list[str]:
   """!The text slots of a status or weather (StatusText / WeatherText order).
   @param kind  "status" or "weather"
   @return slots ([] for the other kinds: any slot name)
   """
   bc = _bc()
   return list(bc.STATUS_TEXTS if kind == "status" else bc.WEATHER_TEXTS if kind == "weather" else [])


def text_args(kind: str) -> list[str]:
   """!The placeholders a kind's texts may use.
   @param kind  one of kinds()
   @return names
   """
   bc = _bc()
   if kind == "status":
      return sorted(bc.STATUS_TEXT_ARGS)
   if kind == "weather":
      return sorted(bc.WEATHER_TEXT_ARGS)
   return sorted(_bc().CONDITION_TEXT_ARGS)


def messages(doc: Document | None = None) -> list[str]:
   """!The engine messages an own text may name ({"message": NAME}): the ones the battle data gives (the engine's
   declared_messages(): every required message and the optional ones the manifest states; C1).
   @param doc  any manifest Document of the battle, or None (the required messages only)
   @return keys, in Msg order
   """
   given = battle.data_of(doc, "messages").get("messages") if doc is not None else None
   return [m for m in _bc().declared_messages(given if isinstance(given, dict) else {}) if m is not None]


def max_records(kind: str) -> int:
   """!Most records of a kind (the engine's caps).
   @param kind  one of kinds()
   @return count
   """
   bc = _bc()
   return {"status": bc.MAX_STATUSES, "volatile": bc.MAX_VOLATILES, "weather": bc.LIMITS["weathers"],
           "side_condition": bc.MAX_SIDE_CONDS, "field_condition": bc.MAX_FIELD_CONDS}[kind]


def byte_max() -> int:
   """!Largest value of a byte field.
   @return 255
   """
   return int(_bc().U8_MAX)


def turns_max() -> int:
   """!Longest status length in turns.
   @return turns
   """
   return int(_bc().MAX_TURNS)


def chain_limits() -> tuple[int, int, int]:
   """!A chain's limits: smallest odds denominator, most steps, largest den^cap.
   @return (min den, max cap, max odds)
   """
   bc = _bc()
   return int(bc.MIN_CHAIN_DEN), int(bc.MAX_CHAIN_CAP), int(bc.MAX_CHAIN_ODDS)


def default_escalation_cap() -> int:
   """!An escalating residual's cap when it gives none.
   @return cap
   """
   return int(_bc().DEFAULT_ESCALATION_CAP)


# -- reading -----------------------------------------------------------------------------------------------------------

def _listed(data: JsonDict, kind: str) -> list[Any]:
   """!A kind's list for reading (nothing created).
   @param data  battle manifest data
   @param kind  one of kinds()
   @return the live list, or []
   """
   given = data.get(list_key(kind))
   return given if isinstance(given, list) else []


def records(doc: Document, kind: str) -> list[JsonDict]:
   """!A kind's records.
   @param doc   battle Document
   @param kind  one of kinds()
   @return the live list (created when absent; change it only inside doc.edit())
   """
   key = list_key(kind)
   given = battle.data_of(doc, key).get(key)
   if not isinstance(given, list):
      given = battle.data_of(doc, key)[key] = []
   return given


def names(doc: Document, kind: str) -> list[str]:
   """!A kind's record names in index order.
   @param doc   battle Document
   @param kind  one of kinds()
   @return names
   """
   listed = _listed(battle.data_of(doc, list_key(kind)), kind)
   return [e["name"] for e in listed if isinstance(e, dict) and isinstance(e.get("name"), str)]


def record(doc: Document, kind: str, name: str) -> JsonDict:
   """!A record by name.
   @param doc   battle Document
   @param kind  one of kinds()
   @param name  its name
   @return the dict (live)
   @throws DocumentError when there is none
   """
   for e in _listed(battle.data_of(doc, list_key(kind)), kind):
      if isinstance(e, dict) and e.get("name") == name:
         return e
   raise DocumentError(f"no {kind} {name!r} ({list_key(kind)}: {', '.join(names(doc, kind)) or 'none'})")


def duration_of(entry: JsonDict) -> tuple[str, tuple[int, int] | None]:
   """!A volatile's duration as the editors show it.
   @param entry  volatile record
   @return (one of durations(), (min, max) for RANGE_DURATION else None)
   """
   d = entry.get("duration", DEFAULT_DURATION)
   if isinstance(d, list):
      lo = d[0] if d and isinstance(d[0], int) else 0
      hi = d[1] if len(d) > 1 and isinstance(d[1], int) else lo
      return RANGE_DURATION, (lo, hi)
   return (d if isinstance(d, str) else DEFAULT_DURATION), None


def has_counter(entry: JsonDict) -> bool:
   """!Whether a volatile gets a counter slot (battlec conditions.compile_volatiles(): "counter", a [min, max]
   duration or a chain).
   @param entry  volatile record
   @return True when it has one
   """
   return bool(entry.get("counter")) or isinstance(entry.get("duration"), list) or entry.get("chain") is not None


def has_word(entry: JsonDict) -> bool:
   """!Whether a volatile gets a word slot.
   @param entry  volatile record
   @return True when it has one
   """
   return bool(entry.get("word"))


def status_bits(doc: Document) -> tuple[Any, int | None]:
   """!The primary_status role's id bits: the layout's choice and the bits the engine gives the statuses.
   @param doc  battle Document
   @return (choice: "auto" or a number, bits or None when the statuses do not fit)
   """
   ml = battle.data_of(doc, "monster_layout").get("monster_layout")
   choice = ml.get("status_bits", "auto") if isinstance(ml, dict) else "auto"
   count = len(names(doc, "status"))
   try:
      return choice, int(_lc().status_id_bits(choice, count, "status_bits"))
   except _bc().ManifestError:
      return choice, None


def budget(doc: Document) -> list[BudgetRow]:
   """!The condition budgets: volatile bits, counters, words, status ids, side and field conditions, weathers.
   @param doc  battle Document
   @return rows
   """
   bc = _bc()
   vols = [v for v in _listed(battle.data_of(doc, list_key("volatile")), "volatile") if isinstance(v, dict)]
   choice, bits = status_bits(doc)
   lc = _lc()
   if bits is None:
      status_most, note = bc.MAX_STATUSES, "too many for the status id bits"
   elif choice == "auto":
      status_most, note = bc.MAX_STATUSES, f"{bits} id bits (auto: up to {lc.MAX_STATUS_BITS})"
   else:
      status_most, note = min(bc.MAX_STATUSES, (1 << bits) - 1), f"{bits} id bits (status_bits {choice})"
   return [
      BudgetRow("volatile bits", len(vols), bc.MAX_VOLATILES, ""),
      BudgetRow("volatile counters", sum(1 for v in vols if has_counter(v)), bc.MAX_COUNTERS, ""),
      BudgetRow("volatile words", sum(1 for v in vols if has_word(v)), bc.MAX_WORDS, ""),
      # G1: a bound volatile takes a source slot
      BudgetRow("bound volatiles", sum(1 for v in vols if v.get("bound_to") is not None), bc.MAX_BOUND, ""),
      BudgetRow("status ids", len(names(doc, "status")), status_most, note),
      BudgetRow("weathers", len(names(doc, "weather")), max_records("weather"), ""),
      BudgetRow("side conditions", len(names(doc, "side_condition")), bc.MAX_SIDE_CONDS, ""),
      BudgetRow("field conditions", len(names(doc, "field_condition")), bc.MAX_FIELD_CONDS, ""),
   ]


def budget_line(row: BudgetRow) -> str:
   """!A budget as text.
   @param row  a budget() row
   @return "volatile bits 4/32", with its note
   """
   over = " OVER" if row.used > row.most else ""
   return f"{row.label} {row.used}/{row.most}{over}" + (f" ({row.note})" if row.note else "")


# -- checks ------------------------------------------------------------------------------------------------------------

def _page(doc: Document) -> Any:
   """!The game's code page (the engine's default outside a game or when it cannot be read).
   @param doc  battle Document
   @return text_encoder.CodePage
   """
   if doc.path is None:
      return codepage.default_page()
   try:
      return codepage.for_file(doc.path)
   except DocumentError:
      return codepage.default_page()


def _terms(doc: Document) -> Any:
   """!The manifest's terms as the compiler expands them in texts (the game's words for its concepts).
   @param doc  battle Document
   @return compile_terms() result (the engine's defaults when the manifest's terms are not valid)
   """
   bc = _bc()
   try:
      return bc.compile_terms(battle.data_of(doc, "terms").get("terms", {}), "terms")
   except bc.ManifestError:
      return bc.compile_terms({}, "terms")


def text_problem(doc: Document, kind: str, text: Any) -> str | None:
   """!What the engine's text encoder says about a condition text (placeholders, terms, the code page).
   @param doc   battle Document
   @param kind  one of kinds()
   @param text  the text
   @return the problem, or None when the engine takes it
   """
   bc = _bc()
   if not isinstance(text, str):
      return "a text is a string"
   try:
      bc.encode(text, "text", set(text_args(kind)), _page(doc), _terms(doc))
   except bc.ManifestError as e:
      return str(e)
   return None


def name_problem(doc: Document, kind: str, name: Any, current: str | None = None) -> str | None:
   """!Whether a record name is taken or cannot be written in the game's code page.
   @param doc      battle Document
   @param kind     one of kinds()
   @param name     the wanted name
   @param current  the record being renamed, or None
   @return the problem, or None
   """
   bc = _bc()
   if not isinstance(name, str) or not name.strip():
      return "names can't be empty"
   name = name.strip()
   if name != current and name in names(doc, kind):
      return f"there is already a {kind} {name!r}"
   try:
      bc.encode(name, "name", (), _page(doc))
   except bc.ManifestError as e:
      return str(e)
   return None


def _check_name(doc: Document, kind: str, name: Any, current: str | None = None) -> str:
   """!A record name the engine takes and no other record of the kind has.
   @param doc      battle Document
   @param kind     one of kinds()
   @param name     the wanted name
   @param current  the record being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   problem = name_problem(doc, kind, name, current)
   if problem is not None:
      raise DocumentError(problem)
   return name.strip()


def _engine(fn: Any, *args: Any) -> Any:
   """!Runs one of the compiler's value parsers; its ManifestError becomes a DocumentError.
   @param fn    the parser (battle_compiler.q8, odds, ...)
   @param args  its arguments
   @return its result
   """
   bc = _bc()
   try:
      return fn(*args)
   except bc.ManifestError as e:
      raise DocumentError(str(e)) from e


def _int(value: Any, lo: int, hi: int, what: str) -> int:
   """!An integer within a range.
   @param value  the value
   @param lo     lowest
   @param hi     highest
   @param what   field name (messages)
   @return the value
   @throws DocumentError when it is not one
   """
   if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
      raise DocumentError(f"{what} is a whole number from {lo} to {hi} (got {value!r})")
   return value


def _distinct_names(value: Any, allowed: Sequence[str], what: str, kinds_of: str) -> list[str]:
   """!A list of distinct names from a list.
   @param value     the value
   @param allowed   names it may hold
   @param what      field name (messages)
   @param kinds_of  what the names are ("types")
   @return the list
   @throws DocumentError when it is not one
   """
   if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value) or \
         len(set(value)) != len(value):
      raise DocumentError(f"{what} is a list of distinct names")
   unknown = [v for v in value if v not in allowed]
   if unknown:
      raise DocumentError(f"{what}: {', '.join(unknown)} not among the {kinds_of} ({', '.join(allowed) or 'none'})")
   return list(value)


def _type_names(doc: Document) -> list[str]:
   """!The battle's type names.
   @param doc  battle Document
   @return names
   """
   given = battle.data_of(doc, "types").get("types")
   return [t["name"] for t in given if isinstance(t, dict) and isinstance(t.get("name"), str)] \
      if isinstance(given, list) else []


def _plain_names(doc: Document, key: str) -> list[str]:
   """!A top-level list of plain names (move_flags, tags).
   @param doc  battle Document
   @param key  list key
   @return names
   """
   given = battle.data_of(doc, key).get(key)
   return [x for x in given if isinstance(x, str)] if isinstance(given, list) else []


# -- editing (inside battle.edit()) ------------------------------------------------------------------------------------

def new_record(kind: str) -> JsonDict:
   """!The fields of a new record (the name added by add_record()): a status and a weather get the texts the
   engine needs (core.battle.NEW_ENTRY); the others none.
   @param kind  one of kinds()
   @return the record
   """
   key = list_key(kind)
   return copy.deepcopy(battle.NEW_ENTRY.get(key, {}))


def add_record(doc: Document, kind: str, name: str, copy_of: str | None = None, index: int | None = None) -> int:
   """!Adds a record (a copy of another, or new_record()).
   @param doc      battle Document
   @param kind     one of kinds()
   @param name     its name
   @param copy_of  the record to copy, or None
   @param index    position, or None for the end
   @return its index
   @throws DocumentError for a taken or unwritable name, or a full list
   """
   name = _check_name(doc, kind, name)
   most = max_records(kind)
   if len(names(doc, kind)) >= most:
      raise DocumentError(f"at most {most} {list_key(kind)} (the engine's limit)")
   e = copy.deepcopy(record(doc, kind, copy_of)) if copy_of is not None else new_record(kind)
   e.pop("name", None)
   e = {"name": name, **e}
   lst = records(doc, kind)
   at = len(lst) if index is None else max(0, min(len(lst), int(index)))
   lst.insert(at, e)
   return at


def uses(doc: Document, kind: str, name: str) -> list[str]:
   """!The effect logic naming a record (its own logic block counts), one "where" per use.
   @param doc   battle Document
   @param kind  one of kinds()
   @param name  record name
   @return "where" strings
   @throws DocumentError when a source does not parse
   """
   return logic.references(doc, (list_key(kind),), name)


def remove_record(doc: Document, kind: str, name: str) -> None:
   """!Removes a record; refused while effect logic names it (its own logic block too: remove that first).
   @param doc   battle Document
   @param kind  one of kinds()
   @param name  record name
   @return None
   """
   e = record(doc, kind, name)
   users = logic.per_owner(uses(doc, kind, name))
   if users:
      shown = ", ".join(sorted(set(users))[:battle.REFERENCES_SHOWN])
      raise DocumentError(f"{kind} {name!r} is still named by: {shown}")
   before = battle.ruleset_problem(doc)
   records(doc, kind).remove(e)
   battle.check_ruleset_kept(doc, f"{kind} {name!r}", before)   # the ruleset's pipelines / points may need it


def rename_record(doc: Document, kind: str, old: str, new: str) -> int:
   """!Renames a record and the effect logic naming it (its own owner block, `vol_on X`, `has(X)`, ...).
   @param doc  battle Document
   @param kind  one of kinds()
   @param old  current name
   @param new  new name
   @return references updated
   """
   e = record(doc, kind, old)
   new = _check_name(doc, kind, new, old)
   if new == old:
      return 0
   n = len(logic.references(doc, (list_key(kind),), old, new, "Rename " + kind))
   if kind == STATUS_KIND:
      # G3: the recruit section's status bonuses name statuses
      from . import recruit   # local: core.structure.recruit reads the status records
      n += recruit.follow_status_rename(doc, old, new)
   e["name"] = new
   return n


def move_record(doc: Document, kind: str, name: str, delta: int) -> bool:
   """!Moves a record up or down its list (its engine index; effect logic names records, so nothing else changes).
   @param doc    battle Document
   @param kind   one of kinds()
   @param name   record name
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   lst = records(doc, kind)
   i = lst.index(record(doc, kind, name))
   j = i + delta
   if not 0 <= j < len(lst):
      return False
   lst[i], lst[j] = lst[j], lst[i]
   return True


def set_field(doc: Document, kind: str, name: str, key: str, value: Any) -> None:
   """!Changes one field of a record (None removes it: the engine's default). Values are checked the way the
   compiler checks them where a field alone can say; the compile decides the rest.
   @param doc    battle Document
   @param kind   one of kinds()
   @param name   record name
   @param key    a key of fields(kind)
   @param value  the value (see FIELDS: bools, numbers, "n/m" texts, [min, max], name lists, {...})
   @return None
   @throws DocumentError for a value the engine refuses
   """
   e = record(doc, kind, name)
   known = fields(kind)
   if key not in known:
      raise DocumentError(f"unknown {kind} field {key!r} (fields: {', '.join(known)}; the name: rename; texts: "
                          "text)")
   value = _normalized(doc, kind, e, key, known[key], value)
   if value is None:
      e.pop(key, None)
   else:
      e[key] = value
   if kind == "volatile" and key == "duration" and not isinstance(value, list):
      e.pop("counts", None)   # where a duration counts down only goes with [min, max]


def _normalized(doc: Document, kind: str, e: JsonDict, key: str, field: str, value: Any) -> Any:
   """!A field value as the manifest stores it (None: leave the field out).
   @param doc    battle Document
   @param kind   one of kinds()
   @param e      the record
   @param key    field key
   @param field  its field kind
   @param value  the value given
   @return the value to store, or None
   @throws DocumentError for a value the engine refuses
   """
   bc = _bc()
   what = f"{kind}.{key}"
   if value is None:
      return None
   if field == BOOL:
      if not isinstance(value, bool):
         raise DocumentError(f"{what} is true or false")
      return True if value else None
   if field == BYTE:
      return _int(value, 0, byte_max(), what)
   if field == LAYERS:
      return _int(value, 1, byte_max(), what)
   if field == SHARE:
      if isinstance(value, str) and not value.strip():
         return None
      value = value.strip() if isinstance(value, str) else value
      return None if _engine(bc.q8, value, what, 0, byte_max()) == 0 else value
   if field in (ODDS, SKIP):
      if field == SKIP and value is True:
         return True
      if value is False or (isinstance(value, str) and not value.strip()):
         return None
      value = value.strip() if isinstance(value, str) else value
      n, _m = _engine(bc.odds, value, what, byte_max())
      return None if n == 0 else value
   if field == PAIR:
      if not isinstance(value, (list, tuple)) or len(value) != PAIR_LEN:
         raise DocumentError(f"{what} is [min, max]")
      lo, hi = _int(value[0], 0, turns_max(), what), _int(value[1], 0, turns_max(), what)
      if lo > hi:
         raise DocumentError(f"{what}: min {lo} is above max {hi}")
      return None if hi == 0 else [lo, hi]
   if field == TYPES:
      out = _distinct_names(value, _type_names(doc), what, "types")
      return out or None
   if field == TYPE:
      return _distinct_names([value], _type_names(doc), what, "types")[0]
   if field == FLAG:
      return _distinct_names([value], _plain_names(doc, "move_flags"), what, "move flags")[0]
   if field == TAGS:
      out = _distinct_names(value, _plain_names(doc, "tags"), what, "tags")
      return out or None
   if field == ESCALATING:
      return _escalating(value, what)
   if field == DURATION:
      return _duration(value, what)
   if field == COUNTS:
      if value not in count_modes():
         raise DocumentError(f"{what} is one of {', '.join(count_modes())}")
      if not isinstance(e.get("duration"), list):
         raise DocumentError(f"{what} goes with a [min, max] duration")
      return None if value == DEFAULT_COUNTS else value
   if field == CLEARS:
      out = _distinct_names(value, clear_events(), what, "events")
      return None if set(out) == set(clear_events()) else out
   if field == BOUND:
      if isinstance(value, str) and not value.strip():
         return None
      if value not in bound_choices():
         raise DocumentError(f"{what} is one of {', '.join(bound_choices())} (or left out)")
      return value
   return _chain(doc, value, what)


def _escalating(value: Any, what: str) -> Any:
   """!An escalating residual: true (the default cap), {"cap": n}, or left out.
   @param value  bool, a cap number, or {"cap": n}
   @param what   field name (messages)
   @return the value to store, or None
   """
   if value is False:
      return None
   if value is True:
      return True
   cap = value.get(CAP_KEY) if isinstance(value, dict) else value
   cap = _int(cap, 1, byte_max(), what + ".cap")
   return True if cap == default_escalation_cap() else {CAP_KEY: cap}


def _duration(value: Any, what: str) -> Any:
   """!A volatile's duration: a duration word or [min, max] (the default word is left out).
   @param value  the value
   @param what   field name (messages)
   @return the value to store, or None
   """
   if isinstance(value, (list, tuple)):
      if len(value) != PAIR_LEN:
         raise DocumentError(f"{what} is [min, max]")
      lo, hi = _int(value[0], 0, byte_max(), what), _int(value[1], 0, byte_max(), what)
      if lo > hi:
         raise DocumentError(f"{what}: min {lo} is above max {hi}")
      return [lo, hi]
   words = list(_bc().DURATIONS)
   if value not in words:
      raise DocumentError(f"{what} is one of {', '.join(words)} or [min, max]")
   return None if value == DEFAULT_DURATION else value


def _chain(doc: Document, value: Any, what: str) -> Any:
   """!A volatile's chain {den, cap, kept_by (a move flag, optional)}.
   @param doc    battle Document
   @param value  the dict
   @param what   field name (messages)
   @return the value to store
   """
   if not isinstance(value, dict) or set(value) - set(CHAIN_KEYS):
      raise DocumentError(f"{what} is {{den, cap, kept_by}}")
   min_den, max_cap, max_odds = chain_limits()
   den = _int(value.get("den"), min_den, byte_max(), what + ".den")
   cap = _int(value.get("cap"), 1, max_cap, what + ".cap")
   if den ** cap > max_odds:
      raise DocumentError(f"{what}: den^cap must stay below 2^31")
   out: JsonDict = {"den": den, "cap": cap}
   if value.get("kept_by") is not None:
      out["kept_by"] = _distinct_names([value["kept_by"]], _plain_names(doc, "move_flags"), what + ".kept_by",
                                       "move flags")[0]
   return out


def set_text(doc: Document, kind: str, name: str, slot: str, value: Any) -> None:
   """!Sets or removes one text of a record.
   @param doc    battle Document
   @param kind   one of kinds()
   @param name   record name
   @param slot   the slot (a status's or weather's fixed slots; any lower-case name for the other kinds)
   @param value  a text, {"message": KEY} (not for statuses and weathers), or None to remove it
   @return None
   @throws DocumentError for an unknown slot, message or a text the engine's encoder refuses
   """
   e = record(doc, kind, name)
   fixed = fixed_slots(kind)
   if fixed and slot not in fixed:
      raise DocumentError(f"a {kind}'s text slots are {', '.join(fixed)} (got {slot!r})")
   if not fixed and (not isinstance(slot, str) or not SLOT_NAME.fullmatch(slot)):
      raise DocumentError(f"a text slot is a lower-case name (got {slot!r})")
   texts = e.get("texts") if isinstance(e.get("texts"), dict) else None
   if value is None:
      if texts is not None:
         texts.pop(slot, None)
         if not texts:
            e.pop("texts", None)
      return
   if isinstance(value, dict):
      if kind in FIXED_TEXT_KINDS:
         raise DocumentError(f"a {kind}'s texts are texts (engine messages: volatiles, side and field conditions)")
      if set(value) != {MESSAGE_KEY} or value[MESSAGE_KEY] not in messages(doc):
         raise DocumentError("{\"message\": KEY} names an engine message the battle data gives (an optional one "
                             "needs its text in the messages first)")
      value = {MESSAGE_KEY: value[MESSAGE_KEY]}
   else:
      problem = text_problem(doc, kind, value)
      if problem is not None:
         raise DocumentError(problem)
   if texts is None:
      texts = e["texts"] = {}
   texts[slot] = value


def texts_of(doc: Document, kind: str, name: str) -> list[tuple[str, Any]]:
   """!A record's texts in slot order: the fixed slots (missing ones as None), else the template slots and then
   the others.
   @param doc   battle Document
   @param kind  one of kinds()
   @param name  record name
   @return [(slot, text, {"message": KEY} or None)]
   """
   given = record(doc, kind, name).get("texts")
   given = given if isinstance(given, dict) else {}
   order = fixed_slots(kind) or [s for s in template_slots(kind) if s in given]
   return [(slot, copy.deepcopy(given.get(slot))) for slot in order] + \
      [(slot, copy.deepcopy(v)) for slot, v in given.items() if slot not in order]


# -- other references --------------------------------------------------------------------------------------------------

def bench_uses(project: BattleProject, kind: str, name: str) -> list[str]:
   """!The bench scenarios (bench/*.json, as saved) whose pokes or field name a record: a volatile (pokes'
   volatiles and counters), a status (pokes' status) or a weather (field.weather).
   @param project  BattleProject
   @param kind     one of kinds()
   @param name     record name
   @return "where" strings ("bench/x.json: pokes[0].volatiles")
   """
   from .. import bench   # local: core.bench imports core.battle
   out = []
   for path in bench.scenario_paths(project):
      try:
         data = manifest_io.load(Path(path))
      except (OSError, ValueError):
         continue
      rel = bench.relative_name(project, path)
      found = []
      pokes = data.get("pokes") if isinstance(data, dict) and isinstance(data.get("pokes"), list) else []
      for i, k in enumerate(p for p in pokes if isinstance(p, dict)):
         if kind == "volatile":
            if name in (k.get("volatiles") or []) or name in (k.get("counters") or {}):
               found.append(f"pokes[{i}]")
         elif kind == "status" and k.get("status") == name:
            found.append(f"pokes[{i}].status")
      fld = data.get("field") if isinstance(data, dict) else None
      if kind == "weather" and isinstance(fld, dict) and fld.get("weather") == name:
         found.append("field.weather")
      out += [f"{rel}: {f}" for f in found[:BENCH_SHOWN]]
   return out


# -- text --------------------------------------------------------------------------------------------------------------

def _value_text(value: Any) -> str:
   """!A field value as text.
   @param value  JSON value
   @return text
   """
   return manifest_io.dumps(value).strip() if not isinstance(value, str) else value


def record_line(doc: Document, kind: str, index: int, entry: JsonDict) -> str:
   """!A record as one line of text (the CLI's `condition KIND list`).
   @param doc    battle Document
   @param kind   one of kinds()
   @param index  its index
   @param entry  the record
   @return the line
   """
   parts = [f"{k} {_value_text(entry[k])}" for k in fields(kind) if k in entry]
   if kind == "volatile":
      slots = [s for s, flag in (("counter", has_counter(entry)), ("word", has_word(entry))) if flag]
      parts.append("slots: " + (", ".join(slots) or "none"))
   texts = entry.get("texts")
   if isinstance(texts, dict) and texts:
      parts.append("texts " + ", ".join(texts))
   handlers = entry.get("handlers")
   if isinstance(handlers, list) and handlers:
      parts.append(f"{len(handlers)} point handler(s)")
   return f"{index} {entry.get('name')}: " + ("; ".join(parts) or "no fields")


def report(doc: Document, kind: str | None = None) -> list[str]:
   """!The records of one kind (or of all) as text lines, then the budgets.
   @param doc   battle Document
   @param kind  one of kinds(), or None for every kind
   @return lines
   """
   lines = []
   for k in [kind] if kind is not None else kinds():
      lines.append(f"{list_key(k)}:")
      for i, e in enumerate(e for e in _listed(battle.data_of(doc, list_key(k)), k) if isinstance(e, dict)):
         lines.append("  " + record_line(doc, k, i, e))
   return lines + [budget_line(r) for r in budget(doc)]
