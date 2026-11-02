"""!Battle formats and the turn structure of battle data (A11, §3.2
"Formats & Turn"): the battle manifest's "formats" list and its "turn"
object.

    "formats": [{"name": "Single", "sides": [[0], [1]], "range": "all", "layout": [[64, 92], [176, 52]],
                 "stands": [[64, 92], [176, 52]], "party_max": 6, "on_target_fainted": "redirect"}]
    "turn": {"brackets": {"run": 30, "switch": 20, "item": 25, "move": "priority"}, "tie": "random_byte",
             "end_of_turn": [{"run": "weather"}, {"run": "battlers", "sources": [...]},
                             {"run": "sides", "each": "battler"}, {"run": "field"}],
             "effect_order": ["status", "volatile", "side", "field", "weather", "passive", "item"],
             "switching": {"send_out": "foes_first", "switch_in": "speed"}}

A format's sides list the field positions on each side; "layout" gives one
[x, y] screen place per position and "stands" (optional) one per side, where
that side's presenters stand. Every key of "turn" is optional: a missing
one takes the engine's default (battle_compiler.DEFAULT_TURN, the engine's
former fixed order), and turn_value() shows the merged structure with which
parts are defaults. Every choice list, limit and default comes from the
engine's compiler (battle_compiler re-exports battlec.turn's SOURCES,
END_PHASES, PHASE_EACH, TIE_RULES, SEND_ORDERS, SWITCH_IN_ORDERS,
BRACKET_MIN / BRACKET_MAX, MAX_END_PHASES, DEFAULT_TURN, MAX_POSITIONS,
MIN_SIDES, MAX_SIDES); a turn edit the engine's compile_turn() refuses is
refused with its message, a format edit compile_formats() refuses likewise.

Each editing helper is one change: call it inside one battle.edit() and Undo
takes it back. A format rename or removal goes through core.battle (every
reference follows; a removal is refused while something names it).
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from typing import Any

from .. import battle, codepage, engine
from ..document import Document, DocumentError

## A parsed JSON object.
JsonDict = dict[str, Any]
## One end-of-turn phase as phase_rows() gives it.
PhaseRow = dict[str, Any]
## One format as format_rows() gives it.
FormatRow = dict[str, Any]

## The battle manifest's turn object.
TURN_KEY = "turn"
## The battle manifest's format list (core.battle kind).
FORMATS_KEY = "formats"
## The turn's action brackets.
BRACKETS_KEY = "brackets"
## The turn's speed tie rule.
TIE_KEY = "tie"
## The turn's end-of-turn phases.
END_KEY = "end_of_turn"
## The turn's hook dispatch order.
ORDER_KEY = "effect_order"
## The turn's battle-start send-out settings.
SWITCHING_KEY = "switching"
## A phase's kind.
RUN_KEY = "run"
## A battlers phase's dispatch sources.
SOURCES_KEY = "sources"
## A sides / field phase's "for whom".
EACH_KEY = "each"
## The end-of-turn phase that lists dispatch sources.
BATTLERS_PHASE = "battlers"
## What each end-of-turn phase of the engine runs (the Turn page and `turn show`; a phase the engine adds later and
## this list lacks shows PHASE_NOTE_UNKNOWN). Delayed lands the pending effects of `delay`.
PHASE_NOTES = {"weather": "the weather's residual and countdown",
               "battlers": "each active battler's residual hooks, by source (its statuses, volatiles, ...)",
               "sides": "each side condition's residual and countdown",
               "field": "each field condition's residual and countdown",
               "regen": "the resources' end-of-turn amounts",
               "delayed": "the pending effects of `delay` count down; one that is due lands (its move's land phase "
                          "runs); needed when the logic uses delay"}
## Note of a phase PHASE_NOTES does not describe.
PHASE_NOTE_UNKNOWN = "an end-of-turn phase of the engine"
## The bracket whose value may be the move-priority word.
MOVE_BRACKET = "move"
## A format's side lists.
SIDES_KEY = "sides"
## A format's screen place per position.
LAYOUT_KEY = "layout"
## A format's presenter stand per side.
STANDS_KEY = "stands"
## A format's party size limit.
PARTY_MAX_KEY = "party_max"
## A format's reach.
RANGE_KEY = "range"
## A format's rule when the chosen target fainted.
FAINTED_KEY = "on_target_fainted"
## Location the compiler's messages name.
WHERE = "battle"
## Index of an [x, y] pair's x.
X = 0
## Index of an [x, y] pair's y.
Y = 1


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


# -- the engine's choices ----------------------------------------------------------------------------------------------

def sources() -> list[str]:
   """!The hook dispatch sources, in the engine's EffectSource order.
   @return names
   """
   return list(_bc().SOURCES)


def end_phases() -> list[str]:
   """!The end-of-turn phase kinds.
   @return names
   """
   return list(_bc().END_PHASES)


def phase_note(run: str) -> str:
   """!What an end-of-turn phase runs and how often a turn may list it (the engine's ONCE_PHASES: exactly once,
   AT_MOST_ONCE_PHASES: at most once, battle_compiler's re-exports; a battlers phase at least once).
   @param run  an end_phases() name
   @return note
   """
   rules = _bc()
   note = PHASE_NOTES.get(run, PHASE_NOTE_UNKNOWN)
   if run in rules.ONCE_PHASES:
      note += " (exactly once)"
   elif run in rules.AT_MOST_ONCE_PHASES:
      note += " (at most once)"
   elif run == BATTLERS_PHASE:
      note += " (at least once)"
   return note


def each_phases() -> list[str]:
   """!The end-of-turn phases that say for whom their residual runs (the engine's EACH_PHASES: sides, field).
   @return phase names
   """
   return list(_bc().EACH_PHASES)


def phase_each() -> list[str]:
   """!For whom a sides / field phase runs its residual.
   @return words (the first is the compiler's default)
   """
   return list(_bc().PHASE_EACH)


def tie_rules() -> list[str]:
   """!The speed tie rules.
   @return words
   """
   return list(_bc().TIE_RULES)


def send_orders() -> list[str]:
   """!The battle start's send-out orders.
   @return words
   """
   return list(_bc().SEND_ORDERS)


def switch_in_orders() -> list[str]:
   """!The battle start's switch-in hook orders.
   @return words
   """
   return list(_bc().SWITCH_IN_ORDERS)


def bracket_range() -> tuple[int, int]:
   """!The lowest and highest action bracket.
   @return (BRACKET_MIN, BRACKET_MAX)
   """
   return int(_bc().BRACKET_MIN), int(_bc().BRACKET_MAX)


def max_end_phases() -> int:
   """!Most end-of-turn phases.
   @return MAX_END_PHASES
   """
   return int(_bc().MAX_END_PHASES)


def default_turn() -> JsonDict:
   """!The engine's turn structure without a manifest "turn".
   @return a copy of DEFAULT_TURN
   """
   return copy.deepcopy(_bc().DEFAULT_TURN)


def bracket_names() -> list[str]:
   """!The action brackets the turn has.
   @return keys of DEFAULT_TURN's brackets (run, switch, item, move)
   """
   return list(_bc().DEFAULT_TURN[BRACKETS_KEY])


def move_priority() -> str:
   """!The "move" bracket word meaning each move's own priority (DEFAULT_TURN's move bracket).
   @return the word
   """
   return str(_bc().DEFAULT_TURN[BRACKETS_KEY][MOVE_BRACKET])


def format_ranges() -> list[str]:
   """!The format reach words (the compiler's FORMAT_RANGES).
   @return words (the first is the default)
   """
   return list(_bc().FORMAT_RANGES)


def fainted_rules() -> list[str]:
   """!The format "target fainted" words (the compiler's ON_TARGET_FAINTED).
   @return words (the first is the default)
   """
   return list(_bc().ON_TARGET_FAINTED)


def position_limits() -> tuple[int, int, int]:
   """!Format limits.
   @return (MAX_POSITIONS, MIN_SIDES, MAX_SIDES)
   """
   bc = _bc()
   return int(bc.MAX_POSITIONS), int(bc.MIN_SIDES), int(bc.MAX_SIDES)


def screen_max() -> int:
   """!Highest screen coordinate of a position or stand.
   @return U8_MAX
   """
   return int(_bc().U8_MAX)


# -- the turn ----------------------------------------------------------------------------------------------------------

def _given(doc: Document) -> JsonDict:
   """!The manifest's turn for reading.
   @param doc  battle Document
   @return the dict ({} without one)
   """
   t = battle.data_of(doc, TURN_KEY).get(TURN_KEY)
   return t if isinstance(t, dict) else {}


def turn_value(doc: Document) -> tuple[JsonDict, set[str]]:
   """!The turn structure the compiler uses: the manifest's keys over DEFAULT_TURN.
   @param doc  battle Document
   @return (merged copy, the keys the manifest leaves to the engine: "brackets.run", "tie", "end_of_turn", ...)
   """
   given = _given(doc)
   out = default_turn()
   defaulted = set()
   for key in list(out):
      if key not in given:
         defaulted |= {f"{key}.{k}" for k in out[key]} if isinstance(out[key], dict) else {key}
         continue
      if isinstance(out[key], dict) and isinstance(given[key], dict):
         for k in out[key]:
            if k in given[key]:
               out[key][k] = copy.deepcopy(given[key][k])
            else:
               defaulted.add(f"{key}.{k}")
      else:
         out[key] = copy.deepcopy(given[key])
   return out, defaulted


def compile_turn(doc: Document) -> tuple[JsonDict | None, str | None]:
   """!The turn as the engine compiles it.
   @param doc  battle Document
   @return (compile_turn() result or None, the compiler's message or None)
   """
   try:
      return _bc().compile_turn(copy.deepcopy(battle.data_of(doc, TURN_KEY).get(TURN_KEY)), WHERE), None
   except Exception as e:   # the compiler's ManifestError, type errors in odd data
      return None, str(e)


def _turn(doc: Document) -> JsonDict:
   """!The manifest's turn object, created when missing.
   @param doc  battle Document
   @return the live dict
   """
   t = battle.data_of(doc, TURN_KEY).get(TURN_KEY)
   if not isinstance(t, dict):
      t = battle.data_of(doc, TURN_KEY)[TURN_KEY] = {}
   return t


def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a turn change; refuses it (inside battle.edit(), which puts the manifest back) when the turn
   compiled before and the engine's compile_turn() refuses it after.
   @param doc     battle Document
   @param change  the change
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   _before, error_before = compile_turn(doc)
   result = change()
   if error_before is None:
      _after, error = compile_turn(doc)
      if error is not None:
         raise DocumentError(error)
   return result


def _part(doc: Document, key: str) -> JsonDict:
   """!A sub-object of the turn (brackets, switching), created when missing.
   @param doc  battle Document
   @param key  BRACKETS_KEY or SWITCHING_KEY
   @return the live dict
   """
   t = _turn(doc)
   if not isinstance(t.get(key), dict):
      t[key] = {}
   return t[key]


def set_bracket(doc: Document, name: str, value: int | str | None) -> None:
   """!Sets an action bracket (bigger acts first).
   @param doc    battle Document
   @param name   one of bracket_names()
   @param value  BRACKET_MIN..BRACKET_MAX, move_priority() for the move bracket, or None for the default
   @return None
   """
   if name not in bracket_names():
      raise DocumentError(f"no bracket {name!r} (brackets: {', '.join(bracket_names())})")
   lo, hi = bracket_range()
   if value is not None and not (name == MOVE_BRACKET and value == move_priority()):
      if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
         word = f" or {move_priority()!r}" if name == MOVE_BRACKET else ""
         raise DocumentError(f"bracket {name}: {lo} to {hi}{word}, got {value!r}")

   def change() -> None:
      """!Writes the bracket.
      @return None
      """
      part = _part(doc, BRACKETS_KEY)
      if value is None:
         part.pop(name, None)
      else:
         part[name] = value

   _guarded(doc, change)


def set_choice(doc: Document, key: str, value: str | None) -> None:
   """!Sets the tie rule or a switching setting.
   @param doc    battle Document
   @param key    TIE_KEY, "switching.send_out" or "switching.switch_in"
   @param value  one of its words, or None for the default
   @return None
   """
   choices = {TIE_KEY: tie_rules(), f"{SWITCHING_KEY}.send_out": send_orders(),
              f"{SWITCHING_KEY}.switch_in": switch_in_orders()}
   if key not in choices:
      raise DocumentError(f"no turn setting {key!r} ({', '.join(choices)})")
   if value is not None and value not in choices[key]:
      raise DocumentError(f"{key}: one of {', '.join(choices[key])}, got {value!r}")

   def change() -> None:
      """!Writes the setting.
      @return None
      """
      if key == TIE_KEY:
         holder, k = _turn(doc), TIE_KEY
      else:
         holder, k = _part(doc, SWITCHING_KEY), key.split(".", 1)[1]
      if value is None:
         holder.pop(k, None)
      else:
         holder[k] = value

   _guarded(doc, change)


def effect_order(doc: Document) -> list[str]:
   """!The hook dispatch order the compiler uses.
   @param doc  battle Document
   @return source names
   """
   return list(turn_value(doc)[0][ORDER_KEY])


def set_effect_order(doc: Document, order: Sequence[str] | None) -> None:
   """!Sets the hook dispatch order: every source once (a permutation of sources()), or None for the default.
   @param doc    battle Document
   @param order  source names
   @return None
   """
   if order is not None:
      order = list(order)
      if sorted(order) != sorted(sources()):
         raise DocumentError(f"effect_order lists every source once ({', '.join(sources())})")

   def change() -> None:
      """!Writes the order.
      @return None
      """
      if order is None:
         _turn(doc).pop(ORDER_KEY, None)
      else:
         _turn(doc)[ORDER_KEY] = order

   _guarded(doc, change)


def move_source(doc: Document, name: str, delta: int) -> bool:
   """!Moves a source up or down the dispatch order (writes the order when it was the default).
   @param doc    battle Document
   @param name   a source
   @param delta  -1 earlier, +1 later
   @return True when it moved
   """
   order = effect_order(doc)
   if name not in order:
      raise DocumentError(f"no source {name!r} ({', '.join(order)})")
   i = order.index(name)
   j = i + delta
   if not 0 <= j < len(order):
      return False
   order.insert(j, order.pop(i))
   set_effect_order(doc, order)
   return True


# -- end-of-turn phases ------------------------------------------------------------------------------------------------

def phase_rows(doc: Document) -> list[PhaseRow]:
   """!The end-of-turn phases the compiler uses.
   @param doc  battle Document
   @return per phase: index, run, sources (a battlers phase's own list, or None: the effect order), runs
           (the sources it runs, in order: [] for other phases), each (sides / field: the word; else None),
           default (True when the manifest leaves the whole list to the engine)
   """
   value, defaulted = turn_value(doc)
   order = list(value[ORDER_KEY])
   out = []
   for i, ph in enumerate(value[END_KEY] if isinstance(value[END_KEY], list) else []):
      ph = ph if isinstance(ph, dict) else {}
      run = ph.get(RUN_KEY)
      own = ph.get(SOURCES_KEY)
      runs = (list(own) if isinstance(own, list) else order) if run == BATTLERS_PHASE else []
      each = ph.get(EACH_KEY, phase_each()[0]) if run in each_phases() else None
      out.append({"index": i, "run": run, "sources": list(own) if isinstance(own, list) else None, "runs": runs,
                  "each": each, "default": END_KEY in defaulted})
   return out


def _phases(doc: Document) -> list[JsonDict]:
   """!The manifest's end-of-turn list, written out from the default when it had none.
   @param doc  battle Document
   @return the live list
   """
   t = _turn(doc)
   if not isinstance(t.get(END_KEY), list):
      t[END_KEY] = copy.deepcopy(turn_value(doc)[0][END_KEY])
   return t[END_KEY]


def _phase(doc: Document, index: int) -> JsonDict:
   """!One phase of the manifest's list.
   @param doc    battle Document
   @param index  its index
   @return the live dict
   """
   lst = _phases(doc)
   if not 0 <= index < len(lst) or not isinstance(lst[index], dict):
      raise DocumentError(f"no end-of-turn phase {index} (0-{len(lst) - 1})")
   return lst[index]


def add_phase(doc: Document, run: str, index: int | None = None) -> int:
   """!Adds an end-of-turn phase (the compiler wants weather, sides and field once each, battlers at least once:
   only a battlers phase can be added to a complete list).
   @param doc    battle Document
   @param run    one of end_phases()
   @param index  position, or None for the end
   @return its index
   """
   if run not in end_phases():
      raise DocumentError(f"no phase {run!r} ({', '.join(end_phases())})")
   most = max_end_phases()
   if len(phase_rows(doc)) >= most:
      raise DocumentError(f"at most {most} end-of-turn phases (the engine's limit)")

   def change() -> int:
      """!Inserts the phase.
      @return its index
      """
      lst = _phases(doc)
      at = len(lst) if index is None else max(0, min(len(lst), int(index)))
      lst.insert(at, {RUN_KEY: run})
      return at

   return _guarded(doc, change)


def remove_phase(doc: Document, index: int) -> None:
   """!Removes an end-of-turn phase (refused when the compiler needs it).
   @param doc    battle Document
   @param index  its index
   @return None
   """
   _phase(doc, index)
   _guarded(doc, lambda: _phases(doc).pop(index))


def move_phase(doc: Document, index: int, delta: int) -> bool:
   """!Moves a phase up or down (the order the end of turn runs them in).
   @param doc    battle Document
   @param index  its index
   @param delta  -1 earlier, +1 later
   @return True when it moved
   """
   return move_phase_to(doc, index, index + delta)


def move_phase_to(doc: Document, index: int, to: int) -> bool:
   """!Moves a phase to a position (a drag in the panel).
   @param doc    battle Document
   @param index  its index
   @param to     new index
   @return True when it moved
   """
   _phase(doc, index)
   lst = _phases(doc)
   if not 0 <= to < len(lst) or to == index:
      return False

   def change() -> None:
      """!Takes the phase out and puts it back.
      @return None
      """
      lst.insert(to, lst.pop(index))

   _guarded(doc, change)
   return True


def set_phase_sources(doc: Document, index: int, names: Sequence[str] | None) -> None:
   """!Sets the dispatch sources a battlers phase runs, in order (None: the effect order).
   @param doc    battle Document
   @param index  the phase
   @param names  a non-empty list of distinct sources, or None
   @return None
   """
   ph = _phase(doc, index)
   if ph.get(RUN_KEY) != BATTLERS_PHASE:
      raise DocumentError(f"only a {BATTLERS_PHASE} phase lists sources")
   if names is not None:
      names = list(names)
      if not names or len(set(names)) != len(names) or any(n not in sources() for n in names):
         raise DocumentError(f"sources: a non-empty list of distinct sources ({', '.join(sources())})")

   def change() -> None:
      """!Writes the sources.
      @return None
      """
      if names is None:
         ph.pop(SOURCES_KEY, None)
      else:
         ph[SOURCES_KEY] = names

   _guarded(doc, change)


def set_phase_each(doc: Document, index: int, each: str | None) -> None:
   """!Sets for whom a sides / field phase runs its residual (None: the compiler's default).
   @param doc    battle Document
   @param index  the phase
   @param each   one of phase_each(), or None
   @return None
   """
   ph = _phase(doc, index)
   if ph.get(RUN_KEY) not in each_phases():
      raise DocumentError(f"only a {' or '.join(each_phases())} phase says for whom its residual runs")
   if each is not None and each not in phase_each():
      raise DocumentError(f"each: one of {', '.join(phase_each())}, got {each!r}")

   def change() -> None:
      """!Writes the word.
      @return None
      """
      if each is None:
         ph.pop(EACH_KEY, None)
      else:
         ph[EACH_KEY] = each

   _guarded(doc, change)


def reset(doc: Document, key: str) -> bool:
   """!Gives a part of the turn back to the engine's default (removes it from the manifest).
   @param doc  battle Document
   @param key  BRACKETS_KEY, TIE_KEY, END_KEY, ORDER_KEY, SWITCHING_KEY, or TURN_KEY for all of it
   @return True when something was removed
   """
   if key == TURN_KEY:
      return battle.data_of(doc, TURN_KEY).pop(TURN_KEY, None) is not None
   if key not in default_turn():
      raise DocumentError(f"no turn part {key!r} ({', '.join(default_turn())})")
   t = battle.data_of(doc, TURN_KEY).get(TURN_KEY)
   if not isinstance(t, dict) or key not in t:
      return False
   _guarded(doc, lambda: t.pop(key))
   return True


def turn_lines(doc: Document) -> list[str]:
   """!The turn structure as text lines ("(default)" marks what the engine gives).
   @param doc  battle Document
   @return lines
   """
   value, defaulted = turn_value(doc)

   def mark(key: str) -> str:
      """!The default mark of a key.
      @param key  dotted key
      @return " (default)" or ""
      """
      return " (default)" if key in defaulted else ""

   br = value[BRACKETS_KEY]
   out = ["brackets: " + ", ".join(f"{k} {br[k]}{mark(f'{BRACKETS_KEY}.{k}')}" for k in br),
          f"tie: {value[TIE_KEY]}{mark(TIE_KEY)}",
          f"effect_order: {', '.join(value[ORDER_KEY])}{mark(ORDER_KEY)}",
          "switching: " + ", ".join(f"{k} {v}{mark(f'{SWITCHING_KEY}.{k}')}"
                                    for k, v in value[SWITCHING_KEY].items()),
          f"end_of_turn{mark(END_KEY)}:"]
   for row in phase_rows(doc):
      extra = ""
      if row["run"] == BATTLERS_PHASE:
         extra = f": {', '.join(row['runs'])}" + ("" if row["sources"] is not None else " (the effect order)")
      elif row["each"] is not None:
         extra = f": each {row['each']}"
      out.append(f"  {row['index']} {row['run']}{extra}")
   out.append("phases: " + "; ".join(f"{run}: {phase_note(run)}" for run in end_phases()))
   _compiled, error = compile_turn(doc)
   if error:
      out.append(f"error: {error}")
   return out


# -- formats -----------------------------------------------------------------------------------------------------------

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


def party_size(doc: Document) -> int:
   """!The layout's party size (the most a format's party_max may be).
   @param doc  battle Document
   @return size
   """
   from . import record   # local: imported when needed (record pulls in the stats and logic modules)
   return record.party_size(doc)


def check_format(doc: Document, fd: JsonDict) -> str | None:
   """!What the engine's compile_formats() says about one format.
   @param doc  battle Document
   @param fd   the format entry
   @return the compiler's message, or None when it compiles
   """
   bc = _bc()
   try:
      bc.compile_formats([copy.deepcopy(fd)], WHERE, bc.Texts(_page(doc)), party_size(doc))
   except Exception as e:   # ManifestError, type errors in odd data
      return str(e)
   return None


def format_names(doc: Document) -> list[str]:
   """!The formats' names.
   @param doc  battle Document
   @return names in order
   """
   return [str(f.get("name")) for f in battle.entries(doc, FORMATS_KEY) if isinstance(f, dict)]


def _pairs(value: Any) -> list[list[int]]:
   """!A list of [x, y] pairs for reading (odd entries become [0, 0]).
   @param value  the manifest's list
   @return pairs
   """
   out = []
   for v in value if isinstance(value, list) else []:
      ok = isinstance(v, list) and len(v) == len((X, Y)) and all(isinstance(c, int) for c in v)
      out.append([v[X], v[Y]] if ok else [0, 0])
   return out


def format_rows(doc: Document) -> list[FormatRow]:
   """!Every format with its geometry.
   @param doc  battle Document
   @return per format: index, name, sides (position lists), positions, range, layout ([x, y] per position),
           stands ([x, y] per side, the side's first position's place when the format gives none),
           own_stands (True when it gives them), party_max (None: the party size), on_target_fainted, error
           (the compiler's message or None)
   """
   rng, fainted = format_ranges(), fainted_rules()
   out = []
   for i, f in enumerate(e for e in battle.entries(doc, FORMATS_KEY) if isinstance(e, dict)):
      sides = [list(s) for s in f.get(SIDES_KEY, []) if isinstance(s, list)] if isinstance(f.get(SIDES_KEY),
                                                                                           list) else []
      layout = _pairs(f.get(LAYOUT_KEY))
      own = isinstance(f.get(STANDS_KEY), list)
      if own:
         stands = _pairs(f[STANDS_KEY])
      else:
         stands = [list(layout[s[0]]) if s and isinstance(s[0], int) and 0 <= s[0] < len(layout) else [0, 0]
                   for s in sides]
      out.append({"index": i, "name": f.get("name"), "sides": sides, "positions": sum(len(s) for s in sides),
                  "range": f.get(RANGE_KEY, rng[0]), "layout": layout, "stands": stands, "own_stands": own,
                  "party_max": f.get(PARTY_MAX_KEY), "on_target_fainted": f.get(FAINTED_KEY, fainted[0]),
                  "error": check_format(doc, f)})
   return out


def _format(doc: Document, name: str) -> JsonDict:
   """!A format entry.
   @param doc   battle Document
   @param name  its name
   @return the live dict
   """
   return battle.entry(doc, FORMATS_KEY, name)


def _format_guarded(doc: Document, name: str, change: Callable[[JsonDict], Any]) -> Any:
   """!Runs a format change; refused when the format compiled before and does not after.
   @param doc     battle Document
   @param name    the format
   @param change  callable(entry)
   @return what change() returned
   @throws DocumentError with the engine's message
   """
   fd = _format(doc, name)
   before = check_format(doc, fd)
   result = change(fd)
   if before is None:
      error = check_format(doc, fd)
      if error is not None:
         raise DocumentError(error)
   return result


def add_format(doc: Document, name: str, copy_of: str | None = None, index: int | None = None) -> str:
   """!Adds a format (a copy of another, or two sides of one position each).
   @param doc      battle Document
   @param name     wanted name (made unique)
   @param copy_of  a format to copy, or None
   @param index    position, or None for the end
   @return the name used
   """
   used = battle.add_entry(doc, FORMATS_KEY, name, copy_of)
   if index is not None:
      lst = battle.entries(doc, FORMATS_KEY)
      lst.insert(max(0, min(len(lst) - 1, int(index))), lst.pop())
   return used


def rename_format(doc: Document, old: str, new: str) -> int:
   """!Renames a format; references follow (core.battle).
   @param doc  battle Document
   @param old  current name
   @param new  new name
   @return references updated
   """
   return battle.rename_entry(doc, FORMATS_KEY, old, new)


def remove_format(doc: Document, name: str) -> None:
   """!Removes a format nothing names (battles need one).
   @param doc   battle Document
   @param name  its name
   @return None
   """
   if len(format_names(doc)) <= 1:
      raise DocumentError("battles need a format")
   battle.remove_entry(doc, FORMATS_KEY, name)


def move_format(doc: Document, name: str, delta: int) -> bool:
   """!Moves a format up or down (its index).
   @param doc    battle Document
   @param name   its name
   @param delta  -1 up, +1 down
   @return True when it moved
   """
   return battle.move_entry(doc, FORMATS_KEY, name, delta)


def set_sides(doc: Document, name: str, counts: Sequence[int]) -> None:
   """!Gives a format sides of these many positions, numbered side by side (positions keep their screen
   place by number; new ones take the last place); the stands follow the sides (a new side stands where its
   first position is).
   @param doc     battle Document
   @param name    the format
   @param counts  positions per side (MIN_SIDES..MAX_SIDES sides, MAX_POSITIONS in all)
   @return None
   """
   most, fewest, most_sides = position_limits()
   counts = [int(c) for c in counts]
   if not fewest <= len(counts) <= most_sides or any(c < 1 for c in counts) or sum(counts) > most:
      raise DocumentError(f"{fewest}-{most_sides} sides of one position or more, at most {most} positions in all")

   def change(fd: JsonDict) -> None:
      """!Writes sides, layout and stands.
      @param fd  the format
      @return None
      """
      layout = _pairs(fd.get(LAYOUT_KEY)) or [[0, 0]]
      sides, p = [], 0
      for c in counts:
         sides.append(list(range(p, p + c)))
         p += c
      fd[SIDES_KEY] = sides
      fd[LAYOUT_KEY] = [layout[min(q, len(layout) - 1)] for q in range(p)]
      if isinstance(fd.get(STANDS_KEY), list):
         stands = _pairs(fd[STANDS_KEY])
         fd[STANDS_KEY] = [stands[s] if s < len(stands) else list(fd[LAYOUT_KEY][side[0]])
                           for s, side in enumerate(sides)]

   _format_guarded(doc, name, change)


def set_place(doc: Document, name: str, what: str, index: int, x: int, y: int) -> None:
   """!Moves a position's screen place or a side's stand.
   @param doc    battle Document
   @param name   the format
   @param what   LAYOUT_KEY (a position) or STANDS_KEY (a side; the format then gives every side's stand)
   @param index  position or side
   @param x      screen x (0..screen_max())
   @param y      screen y
   @return None
   """
   if what not in (LAYOUT_KEY, STANDS_KEY):
      raise DocumentError(f"{LAYOUT_KEY} or {STANDS_KEY}, got {what!r}")
   top = screen_max()
   for c in (x, y):
      if isinstance(c, bool) or not isinstance(c, int) or not 0 <= c <= top:
         raise DocumentError(f"screen coordinates are 0-{top}, got {c!r}")
   row = next((r for r in format_rows(doc) if r["name"] == name), None)
   if row is None:
      raise DocumentError(f"no format {name!r}")
   places = row["layout"] if what == LAYOUT_KEY else row["stands"]
   if not 0 <= index < len(places):
      raise DocumentError(f"no {'position' if what == LAYOUT_KEY else 'side'} {index} (0-{len(places) - 1})")

   def change(fd: JsonDict) -> None:
      """!Writes the place (all stands, when the format had none of its own).
      @param fd  the format
      @return None
      """
      new = [list(p) for p in places]
      new[index] = [x, y]
      fd[what] = new

   _format_guarded(doc, name, change)


def clear_stands(doc: Document, name: str) -> bool:
   """!Drops a format's own stands (each side's presenters stand at its first position again).
   @param doc   battle Document
   @param name  the format
   @return True when it had some
   """
   fd = _format(doc, name)
   return fd.pop(STANDS_KEY, None) is not None


def set_format_field(doc: Document, name: str, key: str, value: Any) -> None:
   """!Sets a format's range, party_max or on_target_fainted (None removes it: the compiler's default).
   @param doc    battle Document
   @param name   the format
   @param key    RANGE_KEY, PARTY_MAX_KEY or FAINTED_KEY
   @param value  a word of format_ranges() / fainted_rules(), 1..the party size, or None
   @return None
   """
   choices = {RANGE_KEY: format_ranges(), FAINTED_KEY: fainted_rules()}
   if key not in (RANGE_KEY, PARTY_MAX_KEY, FAINTED_KEY):
      raise DocumentError(f"format field: {RANGE_KEY}, {PARTY_MAX_KEY} or {FAINTED_KEY}, got {key!r}")
   if value is not None and key in choices and value not in choices[key]:
      raise DocumentError(f"{key}: one of {', '.join(choices[key])}, got {value!r}")
   if value is not None and key == PARTY_MAX_KEY:
      size = party_size(doc)
      if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= size:
         raise DocumentError(f"{PARTY_MAX_KEY}: 1 to the party size {size}, got {value!r}")

   def change(fd: JsonDict) -> None:
      """!Writes the field.
      @param fd  the format
      @return None
      """
      if value is None:
         fd.pop(key, None)
      else:
         fd[key] = value

   _format_guarded(doc, name, change)


def format_lines(doc: Document) -> list[str]:
   """!The formats as text lines.
   @param doc  battle Document
   @return lines
   """
   out = []
   for r in format_rows(doc):
      sides = " | ".join(",".join(str(p) for p in s) for s in r["sides"])
      places = " ".join(f"{q}@{x},{y}" for q, (x, y) in enumerate(r["layout"]))
      stands = " ".join(f"{s}@{x},{y}" for s, (x, y) in enumerate(r["stands"]))
      party = r["party_max"] if r["party_max"] is not None else f"{party_size(doc)} (party size)"
      out.append(f"{r['index']} {r['name']}: sides {sides}; range {r['range']}; places {places}; stands "
                 f"{stands}{'' if r['own_stands'] else ' (first positions)'}; party_max {party}; target fainted "
                 f"{r['on_target_fainted']}" + (f"; error: {r['error']}" if r["error"] else ""))
   return out
