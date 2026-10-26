"""!Move flags and tags of battle data (D-23 §3.2 "Flags & Tags"): the
battle manifest's "move_flags" and "tags" name lists.

    "move_flags": ["contact", "sound", "protect", "thaws", "high_crit", "protection"],
    "tags": ["levitating"]

A move flag is bit n of MoveData::flags (n = its place in the list): moves'
"flags" tick them, effect code tests them (`move.has(contact)`), a status's
"thawed_by_move" and a volatile's chain "kept_by" name one. A tag is a bit of
an owner's tags: effect owner blocks (`tags [...]`) and condition records'
"tags" give them, effect code tests them. Each list holds at most the
engine's MAX_MOVE_FLAGS / MAX_TAGS names (battle_compiler re-exports both).

Each editing helper is one change: call it inside one battle.edit() and
Undo takes the whole change back. A rename rewrites every reference: the
manifest's fields and the effect logic (core.logic, through the AST of the
.ceffect sources; those edits join the battle edit's undo step). A name
something still uses cannot be removed.
"""
from __future__ import annotations

from typing import Any

from .. import battle, engine, logic
from ..document import Document, DocumentError
from . import conditions

## A parsed JSON object.
JsonDict = dict[str, Any]

## The manifest's move flag list (and core.logic's list key of it).
FLAGS_KEY = "move_flags"
## The manifest's tag list (and core.logic's list key of it).
TAGS_KEY = "tags"
## The lists this module edits.
LISTS = (FLAGS_KEY, TAGS_KEY)
## Structure key: the tag whose holders suppress the weather (engine C6; a weather-calming passive's tag).
WEATHER_SUPPRESS_KEY = "weather_suppress_tag"
## What one name of each list is called in messages.
SINGULAR = {FLAGS_KEY: "move flag", TAGS_KEY: "tag"}


def _bc() -> Any:
   """!The engine's battle compiler.
   @return module
   """
   return engine.tool("battle_compiler")


def _check_list(which: str) -> None:
   """!Refuses a list key this module does not edit.
   @param which  FLAGS_KEY or TAGS_KEY
   @return None
   """
   if which not in LISTS:
      raise DocumentError(f"unknown list {which!r} (lists: {', '.join(LISTS)})")


def max_names(which: str) -> int:
   """!Most names a list holds (capsule::battle::kMaxMoveFlags / the effect compiler's MAX_TAGS).
   @param which  FLAGS_KEY or TAGS_KEY
   @return count
   """
   _check_list(which)
   bc = _bc()
   return int(bc.MAX_MOVE_FLAGS if which == FLAGS_KEY else bc.MAX_TAGS)


def names(doc: Document, which: str) -> list[str]:
   """!A list's names in bit order.
   @param doc    battle Document
   @param which  FLAGS_KEY or TAGS_KEY
   @return names
   """
   _check_list(which)
   given = battle.data_of(doc, which).get(which)
   return [x for x in given if isinstance(x, str)] if isinstance(given, list) else []


def _live(doc: Document, which: str) -> list[Any]:
   """!A list for editing.
   @param doc    battle Document
   @param which  FLAGS_KEY or TAGS_KEY
   @return the live list (created when absent)
   """
   given = battle.data_of(doc, which).get(which)
   if not isinstance(given, list):
      given = battle.data_of(doc, which)[which] = []
   return given


def _check_name(doc: Document, which: str, name: Any, current: str | None = None) -> str:
   """!A name effect code can write bare (a lower-case identifier) that the list does not have yet.
   @param doc      battle Document
   @param which    FLAGS_KEY or TAGS_KEY
   @param name     the wanted name
   @param current  the name being renamed, or None
   @return the name (stripped)
   @throws DocumentError when it is not one
   """
   word = SINGULAR[which]
   if not isinstance(name, str) or not _bc().STAT_NAME.fullmatch(name.strip()):
      raise DocumentError(f"a {word} is a lower-case identifier (got {name!r})")
   name = name.strip()
   if name != current and name in names(doc, which):
      raise DocumentError(f"there is already a {word} {name!r}")
   return name


# -- references --------------------------------------------------------------------------------------------------------

def _manifest_refs(doc: Document, which: str, name: str, new: str | None) -> list[str]:
   """!Finds (and renames) a name in the manifest's fields: moves' flags, statuses' thawed_by_move and volatiles'
   chain kept_by (a move flag), condition records' tags (a tag).
   @param doc    battle Document
   @param which  FLAGS_KEY or TAGS_KEY
   @param name   the name
   @param new    new name, or None to only look
   @return "where" strings
   """
   d = battle.merged(doc)   # moves are content, the rest structure
   found = []

   def fix_list(lst: Any, where: str) -> None:
      """!A list naming it (renamed in place).
      @param lst    the list
      @param where  "where" string
      @return None
      """
      for i, v in enumerate(lst if isinstance(lst, list) else []):
         if v == name:
            found.append(where)
            if new is not None:
               lst[i] = new

   def fix_key(holder: Any, key: str, where: str) -> None:
      """!A field naming it (renamed in place).
      @param holder  the dict
      @param key     its key
      @param where   "where" string
      @return None
      """
      if isinstance(holder, dict) and holder.get(key) == name:
         found.append(where)
         if new is not None:
            holder[key] = new

   if which == FLAGS_KEY:
      for m in d.get("moves", []) if isinstance(d.get("moves"), list) else []:
         if isinstance(m, dict):
            fix_list(m.get("flags"), f"move {m.get('name')}")
      for st in conditions._listed(d, "status"):
         fix_key(st, "thawed_by_move", f"status {st.get('name') if isinstance(st, dict) else st}")
      for v in conditions._listed(d, "volatile"):
         if isinstance(v, dict):
            fix_key(v.get("chain"), "kept_by", f"volatile {v.get('name')} chain")
   else:
      for kind in conditions.kinds():
         for e in conditions._listed(d, kind):
            if isinstance(e, dict):
               fix_list(e.get("tags"), f"{kind} {e.get('name')}")
      # C6: the structure's weather-suppressing tag (the live structure data, not the merged view)
      fix_key(battle.data_of(doc, WEATHER_SUPPRESS_KEY), WEATHER_SUPPRESS_KEY, f"structure {WEATHER_SUPPRESS_KEY}")
   return found


def uses(doc: Document, which: str, name: str, new: str | None = None) -> list[str]:
   """!Finds (and optionally renames) every use of a move flag or tag: the manifest's fields and the effect logic.
   @param doc    battle Document
   @param which  FLAGS_KEY or TAGS_KEY
   @param name   the name
   @param new    new name, or None to only look
   @return "where" strings, one per use
   @throws DocumentError when an effect source does not parse
   """
   _check_list(which)
   return _manifest_refs(doc, which, name, new) + logic.references(doc, (which,), name, new,
                                                                   f"Rename {SINGULAR[which]}")


def use_counts(doc: Document, which: str) -> dict[str, int]:
   """!How many places use each name of a list (one walk of the logic).
   @param doc    battle Document
   @param which  FLAGS_KEY or TAGS_KEY
   @return {name: uses} for every name of the list
   """
   out = {n: len(_manifest_refs(doc, which, n, None)) for n in names(doc, which)}
   project = logic.project_of(doc)
   if project is not None:
      used = logic.name_uses(project).get(which, {})
      for n in out:
         out[n] += len(used.get(n, []))
   return out


# -- editing (inside battle.edit()) ------------------------------------------------------------------------------------

def add_name(doc: Document, which: str, name: str, index: int | None = None) -> int:
   """!Adds a move flag or tag.
   @param doc    battle Document
   @param which  FLAGS_KEY or TAGS_KEY
   @param name   the name
   @param index  position (its bit), or None for the end
   @return its index
   @throws DocumentError for a taken or invalid name, or a full list
   """
   name = _check_name(doc, which, name)
   most = max_names(which)
   if len(names(doc, which)) >= most:
      raise DocumentError(f"at most {most} {which} (the engine's limit)")
   lst = _live(doc, which)
   at = len(lst) if index is None else max(0, min(len(lst), int(index)))
   lst.insert(at, name)
   return at


def remove_name(doc: Document, which: str, name: str) -> None:
   """!Removes a move flag or tag nothing uses.
   @param doc    battle Document
   @param which  FLAGS_KEY or TAGS_KEY
   @param name   the name
   @return None
   """
   if name not in names(doc, which):
      raise DocumentError(f"no {SINGULAR[which]} {name!r}")
   users = logic.per_owner(uses(doc, which, name))
   if users:
      shown = ", ".join(sorted(set(users))[:battle.REFERENCES_SHOWN])
      raise DocumentError(f"{SINGULAR[which]} {name!r} is still used by: {shown}")
   _live(doc, which).remove(name)


def rename_name(doc: Document, which: str, old: str, new: str) -> int:
   """!Renames a move flag or tag and every use.
   @param doc    battle Document
   @param which  FLAGS_KEY or TAGS_KEY
   @param old    current name
   @param new    new name
   @return uses updated
   """
   if old not in names(doc, which):
      raise DocumentError(f"no {SINGULAR[which]} {old!r}")
   new = _check_name(doc, which, new, old)
   if new == old:
      return 0
   n = len(uses(doc, which, old, new))
   lst = _live(doc, which)
   lst[lst.index(old)] = new
   return n


def move_name(doc: Document, which: str, name: str, delta: int) -> bool:
   """!Moves a name up or down its list (its bit; everything names it, so nothing else changes).
   @param doc    battle Document
   @param which  FLAGS_KEY or TAGS_KEY
   @param name   the name
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   lst = _live(doc, which)
   if name not in lst:
      raise DocumentError(f"no {SINGULAR[which]} {name!r}")
   i = lst.index(name)
   j = i + delta
   if not 0 <= j < len(lst):
      return False
   lst[i], lst[j] = lst[j], lst[i]
   return True


def weather_suppress_tag(doc: Document) -> str | None:
   """!The tag whose holders keep the weather from acting while they are on the field (C6).
   @param doc  battle Document
   @return the tag, or None
   """
   v = battle.data_of(doc, WEATHER_SUPPRESS_KEY).get(WEATHER_SUPPRESS_KEY)
   return v if isinstance(v, str) else None


def set_weather_suppress_tag(doc: Document, name: str | None) -> None:
   """!Names the weather-suppressing tag (None: nothing suppresses the weather).
   @param doc   battle Document
   @param name  one of the tags, or None
   @return None
   @throws DocumentError for a name that is not a tag
   """
   if name is not None and name not in names(doc, TAGS_KEY):
      raise DocumentError(f"no tag {name!r} (tags: {', '.join(names(doc, TAGS_KEY)) or 'none'})")
   data = battle.data_of(doc, WEATHER_SUPPRESS_KEY)
   if name is None:
      data.pop(WEATHER_SUPPRESS_KEY, None)
   else:
      data[WEATHER_SUPPRESS_KEY] = name


def report(doc: Document, which: str) -> list[str]:
   """!A list with its use counts, then its budget.
   @param doc    battle Document
   @param which  FLAGS_KEY or TAGS_KEY
   @return lines
   """
   counts = use_counts(doc, which)
   rows = [f"{i} {n}: {counts.get(n, 0)} use(s)" for i, n in enumerate(names(doc, which))]
   return rows + [f"{len(rows)}/{max_names(which)} {which}"]
