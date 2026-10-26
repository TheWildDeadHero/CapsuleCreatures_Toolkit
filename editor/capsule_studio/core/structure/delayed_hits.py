"""!The delayed hits of battle data (engine G1, D-26 section 1): the structure manifest's "delayed_hits".

    structure.json  "delayed_hits": [{"name": "foresight", "at_use": ["stats", "stages", "level", "target_defense"],
                                      "typed": false, "crit": false, "accuracy": 90, "miss_message": "failed"}]

Effect logic `delay_hit WHO TURNS NAME;` keeps a snapshot of the move's user at the target's position; when it
lands (the end-of-turn phase `delayed`), the move's land phase `damage` works the hit out through the normal
damage pipeline. A record says which values the landing takes from the time of use (at_use: the engine's
DELAYED_AT_USE), whether the hit has the move's type (typed) and may be critical (crit), its landing accuracy
(0: no check) and the engine message a miss says. The names, defaults and checks are the engine's (battle_compiler
re-exports battlec/delayed.py: DELAYED_AT_USE, DELAYED_HIT_FLAGS, DELAYED_DEFAULT_FLAGS, DEFAULT_MISS_MESSAGE,
DELAYED_MAX_ACCURACY, compile_delayed_hits()).

Each editing helper is one change: call it inside one edit() of either manifest. A rename follows the effect logic
naming the record (`delay_hit ... NAME`, core.logic.references()); a removal is refused while logic names it. An
edit that stops data that compiled from compiling is refused with the engine's message.
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from typing import Any, TypedDict

from .. import battle, engine, logic
from ..document import Document, DocumentError

## A parsed JSON object.
JsonDict = dict[str, Any]

## The structure manifest's list of delayed hits.
HITS_KEY = "delayed_hits"
## A record's name.
NAME_KEY = "name"
## What a record takes from the time of use.
AT_USE_KEY = "at_use"
## A record's landing accuracy.
ACCURACY_KEY = "accuracy"
## A record's miss message.
MISS_KEY = "miss_message"
## The effect compiler's list effect logic names a delayed hit from.
LOGIC_LISTS = (HITS_KEY,)
## Location the compiler's messages name.
WHERE = "structure"
## Undo label of the effect logic's part of a rename.
RENAME_LABEL = "Rename delayed hit"


class HitRow(TypedDict):
   """!One delayed hit as the page and the CLI show it."""
   ## Position in the list.
   index: int
   ## Its name.
   name: str
   ## What it takes from the time of use (the engine's names; all of them when the record states none).
   at_use: list[str]
   ## Its flags with their values (typed, crit), defaults filled in.
   flags: dict[str, bool]
   ## Landing accuracy (0: none).
   accuracy: int
   ## The message a miss says.
   miss_message: str
   ## The effect logic naming it ("effects/moves.ceffect: move X").
   users: list[str]


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def at_use_names() -> list[str]:
   """!What a landing may take from the time of use (the engine's DELAYED_AT_USE, in its bit order).
   @return names
   """
   return list(_bc().DELAYED_AT_USE)


def flag_names() -> list[str]:
   """!A record's flags (the engine's DELAYED_HIT_FLAGS).
   @return names
   """
   return list(_bc().DELAYED_HIT_FLAGS)


def flag_default(flag: str) -> bool:
   """!A flag's value when a record states none (the engine's DELAYED_DEFAULT_FLAGS).
   @param flag  flag name
   @return its default
   """
   return bool(_bc().DELAYED_DEFAULT_FLAGS[flag])


def max_accuracy() -> int:
   """!The highest landing accuracy (the engine's DELAYED_MAX_ACCURACY: a percent).
   @return it
   """
   return int(_bc().DELAYED_MAX_ACCURACY)


def default_miss_message() -> str:
   """!The message a miss says when a record names none (the engine's DEFAULT_MISS_MESSAGE).
   @return the key
   """
   return str(_bc().DEFAULT_MISS_MESSAGE)


def message_choices(doc: Document) -> list[str]:
   """!The engine messages the battle data gives (a miss message is one of them).
   @param doc  any manifest Document of the battle
   @return keys
   """
   project = logic.project_of(doc)
   return logic.name_lists(project)["messages"] if project is not None else []


def hits(doc: Document | None) -> list[JsonDict]:
   """!The records in order (live).
   @param doc  any manifest Document of the battle, or None
   @return record dicts (entries that are not objects with a name are left out)
   """
   if doc is None:
      return []
   given = battle.data_of(doc, HITS_KEY).get(HITS_KEY)
   return [h for h in given if isinstance(h, dict) and isinstance(h.get(NAME_KEY), str)] \
      if isinstance(given, list) else []


def hit_names(doc: Document | None) -> list[str]:
   """!The record names in order.
   @param doc  any manifest Document of the battle, or None
   @return names
   """
   return [h[NAME_KEY] for h in hits(doc)]


def users(doc: Document, name: str) -> list[str]:
   """!The effect logic owners naming a record.
   @param doc   any manifest Document of the battle
   @param name  record name
   @return "FILE: KIND NAME" strings
   """
   return logic.per_owner(logic.references(doc, LOGIC_LISTS, name))


def hit_rows(doc: Document) -> list[HitRow]:
   """!The records with their defaults filled in and their users.
   @param doc  any manifest Document of the battle
   @return one row per record
   """
   out = []
   for i, h in enumerate(hits(doc)):
      at_use = h.get(AT_USE_KEY, at_use_names())
      out.append(HitRow(index=i, name=h[NAME_KEY], at_use=list(at_use) if isinstance(at_use, list) else [],
                        flags={f: bool(h.get(f, flag_default(f))) for f in flag_names()},
                        accuracy=h.get(ACCURACY_KEY, 0) if isinstance(h.get(ACCURACY_KEY, 0), int) else 0,
                        miss_message=str(h.get(MISS_KEY, default_miss_message())), users=users(doc, h[NAME_KEY])))
   return out


def compile_check(doc: Document) -> tuple[list[JsonDict] | None, str | None]:
   """!Compiles the records with the engine's compile_delayed_hits().
   @param doc  any manifest Document of the battle
   @return (compiled records or None, the compiler's message or None)
   """
   bc = _bc()
   try:
      given = bc.strip(copy.deepcopy(battle.data_of(doc, HITS_KEY).get(HITS_KEY)))
      merged = battle.merged(doc)
      return bc.compile_delayed_hits(given, WHERE, bc.declared_messages(merged.get("messages", {}))), None
   except Exception as e:   # ManifestError, type errors in odd data
      return None, str(e)


def _guarded(doc: Document, change: Callable[[], Any]) -> Any:
   """!Runs a change; refuses it with the engine's message when the records (or the whole battle data) compiled
   before and do not after.
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


def _live(doc: Document) -> list[JsonDict]:
   """!The record list for editing (written when the structure states none).
   @param doc  any manifest Document of the battle
   @return the live list
   """
   data = battle.data_of(doc, HITS_KEY)
   if not isinstance(data.get(HITS_KEY), list):
      data[HITS_KEY] = []
   return data[HITS_KEY]


def _hit(doc: Document, name: str) -> JsonDict:
   """!One record (live).
   @param doc   any manifest Document of the battle
   @param name  record name
   @return the dict
   @throws DocumentError when there is no such record
   """
   for h in hits(doc):
      if h[NAME_KEY] == name:
         return h
   raise DocumentError(f"no delayed hit {name!r} (delayed hits: {', '.join(hit_names(doc)) or 'none'})")


def _check_name(doc: Document, name: Any, current: str | None = None) -> str:
   """!A record name: not empty, no other record's.
   @param doc      any manifest Document of the battle
   @param name     the wanted name
   @param current  the name being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   name = name.strip() if isinstance(name, str) else name
   if not isinstance(name, str) or not name:
      raise DocumentError("a delayed hit needs a name")
   if name != current and name in hit_names(doc):
      raise DocumentError(f"there is already a delayed hit {name!r}")
   return name


def add_hit(doc: Document, name: str, at: int | None = None) -> None:
   """!Adds a record (the engine's defaults: everything from the time of use, typed, may be critical, no landing
   accuracy check).
   @param doc   any manifest Document of the battle
   @param name  its name
   @param at    its position (None: last)
   @return None
   """
   name = _check_name(doc, name)

   def change() -> None:
      """!Inserts it."""
      live = _live(doc)
      live.insert(len(live) if at is None else max(0, min(at, len(live))), {NAME_KEY: name})
   _guarded(doc, change)


def remove_hit(doc: Document, name: str) -> None:
   """!Removes a record (refused while effect logic names it).
   @param doc   any manifest Document of the battle
   @param name  record name
   @return None
   """
   _hit(doc, name)
   named = users(doc, name)
   if named:
      raise DocumentError(f"delayed hit {name!r} is used by {', '.join(named)}")
   _guarded(doc, lambda: _live(doc).remove(_hit(doc, name)))


def rename_hit(doc: Document, old: str, new: str) -> list[str]:
   """!Renames a record; the effect logic naming it follows.
   @param doc  any manifest Document of the battle
   @param old  its name
   @param new  the new name
   @return the logic places rewritten
   """
   new = _check_name(doc, new, old)
   h = _hit(doc, old)

   def change() -> list[str]:
      """!Renames it and its users."""
      h[NAME_KEY] = new
      return logic.references(doc, LOGIC_LISTS, old, new, RENAME_LABEL)
   return _guarded(doc, change)


def move_hit(doc: Document, name: str, delta: int) -> None:
   """!Moves a record up or down (the ids effect logic compiles to follow the order).
   @param doc    any manifest Document of the battle
   @param name   record name
   @param delta  -1 up, +1 down
   @return None
   """
   names = hit_names(doc)
   if name not in names:
      raise DocumentError(f"no delayed hit {name!r}")
   i = names.index(name)
   j = i + delta
   if not 0 <= j < len(names):
      return

   def change() -> None:
      """!Swaps it with its neighbour."""
      live = _live(doc)
      live[i], live[j] = live[j], live[i]
   _guarded(doc, change)


def set_at_use(doc: Document, name: str, values: Sequence[str]) -> None:
   """!Sets what a record takes from the time of use (in the engine's order; all of them: the key goes).
   @param doc     any manifest Document of the battle
   @param name    record name
   @param values  names from at_use_names()
   @return None
   """
   known = at_use_names()
   unknown = [v for v in values if v not in known]
   if unknown:
      raise DocumentError(f"at_use: {', '.join(known)} (not {', '.join(unknown)})")
   ordered = [v for v in known if v in values]
   h = _hit(doc, name)

   def change() -> None:
      """!Writes it."""
      if ordered == known:
         h.pop(AT_USE_KEY, None)
      else:
         h[AT_USE_KEY] = ordered
   _guarded(doc, change)


def set_flag(doc: Document, name: str, flag: str, value: bool) -> None:
   """!Sets one of a record's flags (its default value: the key goes).
   @param doc    any manifest Document of the battle
   @param name   record name
   @param flag   a flag_names() name
   @param value  on or off
   @return None
   """
   if flag not in flag_names():
      raise DocumentError(f"a delayed hit's flags are {', '.join(flag_names())} (not {flag!r})")
   h = _hit(doc, name)

   def change() -> None:
      """!Writes it."""
      if bool(value) == flag_default(flag):
         h.pop(flag, None)
      else:
         h[flag] = bool(value)
   _guarded(doc, change)


def set_accuracy(doc: Document, name: str, accuracy: int) -> None:
   """!Sets a record's landing accuracy (0: no check; the key goes).
   @param doc       any manifest Document of the battle
   @param name      record name
   @param accuracy  0 to max_accuracy()
   @return None
   """
   if not isinstance(accuracy, int) or isinstance(accuracy, bool) or not 0 <= accuracy <= max_accuracy():
      raise DocumentError(f"a landing accuracy is 0 to {max_accuracy()} (got {accuracy!r})")
   h = _hit(doc, name)

   def change() -> None:
      """!Writes it."""
      if accuracy == 0:
         h.pop(ACCURACY_KEY, None)
      else:
         h[ACCURACY_KEY] = accuracy
   _guarded(doc, change)


def set_miss_message(doc: Document, name: str, message: str) -> None:
   """!Sets the message a missed landing says (the engine's default: the key goes).
   @param doc      any manifest Document of the battle
   @param name     record name
   @param message  an engine message the battle gives
   @return None
   """
   choices = message_choices(doc)
   if choices and message not in choices:
      raise DocumentError(f"miss_message: one of the battle's messages (not {message!r})")
   h = _hit(doc, name)

   def change() -> None:
      """!Writes it."""
      if message == default_miss_message():
         h.pop(MISS_KEY, None)
      else:
         h[MISS_KEY] = message
   _guarded(doc, change)


def lines(doc: Document) -> list[str]:
   """!The records as text (the CLI's `delayed-hit list`).
   @param doc  any manifest Document of the battle
   @return one line per record
   """
   out = []
   for r in hit_rows(doc):
      flags = ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in r["flags"].items())
      out.append(f"{r['name']}: at use {', '.join(r['at_use']) or 'nothing'}; {flags}; accuracy "
                 f"{r['accuracy'] or 'no check'}; miss says {r['miss_message']}; used by "
                 f"{', '.join(r['users']) or 'nobody'}")
   return out
