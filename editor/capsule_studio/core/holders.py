"""!Passives and items of battle data, and the manifest point handlers of
every owner that has them (D-23 §3.1 Content "Passives/Items"; the battle
manifest's "passives" and "items", the "handlers" of statuses and
weathers).

    "passives": [{"name": "Blaze Heart", "announce": false,
                  "handlers": [{"point": "power", "code": "when move.type == Fire { modify by 1.5; }"}]}, ...]

A passive or item is a name, whether the battle shows it when its logic
says `announce;` ("announce", default true) and its manifest point
handlers: {"point": NAME, "code": TEXT}, the text after `point NAME` of a
`.ceffect` point member (tools/battlec/pipelines.py). A handler's point must
take the owner's kind as a source (the ruleset's points: "sources", the kind
alone or as user.KIND / target.KIND). The logic of a holder (its lifecycle
hooks and `.ceffect` point members) is edited on the Effects page; the
engine's battle compiler checks the code.

E13b: moves, volatiles and side conditions hold point handlers too, but only
as `point NAME` members of their `.ceffect` logic (the engine reads no
manifest "handlers" for them: their records have no such key). The same
helpers edit those: for a list of logic_lists() a handler is the owner's
point member (handlers() gives each as {"point", "code"}, add_handler()
writes a new logic block for an entry that has none), so one editor box
serves every owner. Those helpers need the BattleProject the Document
belongs to (core.logic.project_of()).

Each editing helper is one change: call it inside one battle.edit(). A
holder's rename, removal and order are core.battle's (rename_entry() follows
species, party members and the effect logic).
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from . import battle, engine, logic
from .document import Document, DocumentError

if TYPE_CHECKING:
   from .battle import BattleProject

## A parsed JSON object.
JsonDict = dict[str, Any]
## One holder as holder_rows() gives it.
HolderRow = dict[str, Any]

## The lists of holders (core.battle kinds).
HOLDER_LISTS = ("passives", "items")
## The dot between a battler and a source kind in a point's sources ("target.side").
SOURCE_DOT = "."
## A holder's announce flag (default true).
ANNOUNCE_KEY = "announce"
## A record's point handler list.
HANDLERS_KEY = "handlers"
## Code of a new handler: x1 (a bare integer N modifies by xN).
NEW_CODE = "{ modify by 1; }"


def _ec() -> Any:
   """!The engine's effect compiler.
   @return module
   """
   return engine.tool("effect_compiler")


def handler_lists() -> dict[str, str]:
   """!The manifest lists whose entries have point handlers, with their owner kinds (core.logic.point_owner_lists():
   the engine's battlec.pipelines OWNER_KINDS).
   @return {manifest list: owner kind}
   """
   return logic.point_owner_lists()


def manifest_lists() -> list[str]:
   """!The lists whose records take manifest "handlers" (the engine's MANIFEST_HANDLER_LISTS, battle_compiler's
   re-export: passives, items, statuses, weathers); the others' handlers are `.ceffect` point members
   (logic_lists()).
   @return list keys, in handler_lists() order
   """
   manifest = engine.tool("battle_compiler").MANIFEST_HANDLER_LISTS
   return [key for key in handler_lists() if key in manifest]


def logic_lists() -> list[str]:
   """!The lists whose point handlers are only `.ceffect` point members (E13b: moves, volatiles, side conditions).
   @return list keys
   """
   manifest = manifest_lists()
   return [key for key in handler_lists() if key not in manifest]


def source_kind(key: str) -> str:
   """!The point source kind of a list (core.pipelines.handler_owners(): "side" for the side conditions).
   @param key  one of handler_lists()
   @return source kind
   """
   from . import pipelines   # local: core.pipelines imports the modules this one does
   _check_list(key)
   return pipelines.handler_owners()[key]


def _check_list(key: str) -> str:
   """!The owner kind of a list with point handlers.
   @param key  one of handler_lists()
   @return owner kind
   @throws DocumentError for another list
   """
   lists = handler_lists()
   if key not in lists:
      raise DocumentError(f"unknown list {key!r} (lists with point handlers: {', '.join(lists)})")
   return lists[key]


def takes_source(sources: Any, kind: str) -> bool:
   """!Whether a point's sources include a source kind (alone, or as user.KIND / target.KIND: the battle
   compiler's check in battlec/pipelines.py PointHandlers.add_node()).
   @param sources  the point's "sources"
   @param kind     source kind
   @return True when a handler of that kind runs on the point
   """
   given = sources if isinstance(sources, list) else []
   return any(isinstance(s, str) and (s == kind or s.endswith(SOURCE_DOT + kind)) for s in given)


def holder_rows(doc: Document, key: str) -> list[HolderRow]:
   """!The passives or items with their flags and what names them.
   @param doc  battle Document
   @param key  "passives" or "items"
   @return copies in index order: index, name, announce, handlers (count), uses ("where" strings of the manifest
           and the effect logic, its own logic block included)
   """
   if key not in HOLDER_LISTS:
      raise DocumentError(f"unknown holder list {key!r} (lists: {', '.join(HOLDER_LISTS)})")
   out = []
   for i, e in enumerate(battle.entries(doc, key)):
      if not isinstance(e, dict):
         continue
      try:
         used = battle.references(doc, key, e.get("name"))
      except DocumentError:
         used = []   # a source that does not parse: the Effects page shows it
      handlers = e.get(HANDLERS_KEY)
      out.append({"index": i, "name": e.get("name"), "announce": e.get(ANNOUNCE_KEY, True) is not False,
                  "handlers": len(handlers) if isinstance(handlers, list) else 0, "uses": used})
   return out


def set_announce(doc: Document, key: str, name: str, on: bool) -> None:
   """!Whether a holder is shown when its logic announces it (true is the default and left out).
   @param doc   battle Document
   @param key   "passives" or "items"
   @param name  its name
   @param on    shown
   @return None
   """
   e = battle.entry(doc, key, name)
   if on:
      e.pop(ANNOUNCE_KEY, None)
   else:
      e[ANNOUNCE_KEY] = False


# -- point handlers ----------------------------------------------------------------------------------------------------

def point_choices(project: BattleProject, key: str) -> list[str]:
   """!The ruleset points an owner of a list may handle: those whose sources include its kind.
   @param project  BattleProject
   @param key      one of handler_lists()
   @return point names, in declaration order
   """
   kind = source_kind(key)
   points = project.ruleset.data.get("points")
   points = points if isinstance(points, dict) else {}
   return [n for n, p in points.items() if isinstance(p, dict) and takes_source(p.get("sources"), kind)]


def handlers(doc: Document, key: str, name: str) -> list[JsonDict]:
   """!An entry's manifest point handlers.
   @param doc   battle Document
   @param key   one of handler_lists()
   @param name  the entry
   @return copies, in order
   """
   _check_list(key)
   if key in logic_lists():
      _check_entry(doc, key, name)
      found = _logic_owner(doc, key, name)
      if found is None:
         return []
      members = found[1]["handlers"]
      return [{"point": members[i]["point"], "code": logic._code_of(members[i])} for i in _point_members(found[1])]
   given = battle.entry(doc, key, name).get(HANDLERS_KEY)
   return [copy.deepcopy(h) for h in given if isinstance(h, dict)] if isinstance(given, list) else []


# -- point members of the logic (moves, volatiles, side conditions; E13b) ----------------------------------------------

def _project(doc: Document) -> BattleProject:
   """!The project a manifest Document belongs to (the logic of a logic_lists() entry is in its sources).
   @param doc  battle or structure Document
   @return the project
   @throws DocumentError for a Document opened on its own
   """
   project = logic.project_of(doc)
   if project is None:
      raise DocumentError("the point handlers of this list are in the effect logic: open the battle data as a "
                          "project")
   return project


def _check_entry(doc: Document, key: str, name: str) -> None:
   """!Refuses a name the list does not have (the condition records are structure lists, not core.battle kinds).
   @param doc   battle or structure Document
   @param key   one of logic_lists()
   @param name  the entry
   @return None
   """
   given = logic.manifest_view(doc).get(key)
   names = [e.get("name") for e in given if isinstance(e, dict)] if isinstance(given, list) else []
   if name not in names:
      raise DocumentError(f"no {_check_list(key)} {name!r} in {key}")


def _ref(key: str, name: str) -> str:
   """!The owner reference of an entry ("kind:name").
   @param key   one of logic_lists()
   @param name  the entry
   @return reference
   """
   return f"{_check_list(key)}{logic.OWNER_SEPARATOR}{name}"


def _logic_owner(doc: Document, key: str, name: str) -> tuple[BattleProject, JsonDict] | None:
   """!An entry's logic block, if it has one.
   @param doc   battle or structure Document
   @param key   one of logic_lists()
   @param name  the entry
   @return (project, owner AST copy), or None without a block
   """
   project = _project(doc)
   kind = _check_list(key)
   if not any(r.kind == kind and r.name == name for r in logic.owners(project, kind)):
      return None
   return project, logic.owner_ast(project, _ref(key, name))


def _point_members(ast: JsonDict) -> list[int]:
   """!The indices of an owner's point members among its members (the handlers, in order).
   @param ast  owner AST
   @return indices into ast["handlers"]
   """
   return [i for i, h in enumerate(ast.get("handlers", [])) if isinstance(h, dict) and "point" in h]


def _member(key: str, name: str, point: str, code: str) -> JsonDict:
   """!A handler as a `.ceffect` point member node.
   @param key    one of logic_lists()
   @param name   the entry
   @param point  the point
   @param code   the code after `point NAME`
   @return the member node
   """
   ec = _ec()
   kind = _check_list(key)
   try:
      return ec.parse(logic._code_owner(kind, name, {"point": point, "code": code.strip()}))["owners"][0]["handlers"][0]
   except ec.EffectError as e:
      raise DocumentError(str(e)) from None


def _edit_members(doc: Document, key: str, name: str, change: Callable[[list[Any], list[int]], Any],
                  create: bool = False) -> Any:
   """!Changes an entry's point members: its logic block rewritten in canonical form (one block of its source).
   @param doc     battle or structure Document
   @param key     one of logic_lists()
   @param name    the entry
   @param change  callable(the owner's member list, the point members' indices) -> result
   @param create  write an empty logic block first when the entry has none
   @return change()'s result
   @throws DocumentError for an entry without logic (create False)
   """
   _check_entry(doc, key, name)
   found = _logic_owner(doc, key, name)
   if found is None:
      if not create:
         raise DocumentError(f"{name} has no point handlers (no logic block)")
      project = _project(doc)
      logic.add_owner(project, _check_list(key), name, label="Point handler")
      found = _logic_owner(doc, key, name)
   project, ast = found
   members = ast.setdefault("handlers", [])
   out = change(members, _point_members(ast))
   logic.set_owner_ast(project, _ref(key, name), ast, "Point handler")
   return out


def code_problem(key: str, name: str, point: str, code: str) -> str | None:
   """!What the effect compiler's parser says about a handler's code (the compile checks names and ranges).
   @param key    one of handler_lists()
   @param name   the entry
   @param point  the point
   @param code   the code after `point NAME`
   @return the problem, or None when it parses
   """
   ec = _ec()
   kind = _check_list(key)
   try:
      # core.logic builds the same owner around manifest code when it walks it.
      ec.parse(logic._code_owner(kind, name, {"point": point, "code": code}))
   except ec.EffectError as e:
      return str(e)
   return None


def _live(doc: Document, key: str, name: str) -> list[Any]:
   """!An entry's handler list for editing.
   @param doc   battle Document
   @param key   one of handler_lists()
   @param name  the entry
   @return the live list (created when absent)
   """
   _check_list(key)
   e = battle.entry(doc, key, name)
   if not isinstance(e.get(HANDLERS_KEY), list):
      e[HANDLERS_KEY] = []
   return e[HANDLERS_KEY]


def _drop_empty(doc: Document, key: str, name: str) -> None:
   """!Leaves out an empty handler list.
   @param doc   battle Document
   @param key   one of handler_lists()
   @param name  the entry
   @return None
   """
   e = battle.entry(doc, key, name)
   if e.get(HANDLERS_KEY) == []:
      e.pop(HANDLERS_KEY)


def _check(key: str, name: str, point: Any, code: Any, choices: list[str] | None) -> None:
   """!Refuses a handler the parser refuses or whose point is not among the choices.
   @param key      one of handler_lists()
   @param name     the entry
   @param point    the point
   @param code     the code
   @param choices  point_choices(), or None to leave the point to the compiler
   @return None
   """
   if not isinstance(point, str) or not point:
      raise DocumentError("a point handler names a point")
   if choices is not None and point not in choices:
      raise DocumentError(f"{point!r} is not a point a {_check_list(key)} handles (points: "
                          f"{', '.join(choices) or 'none'})")
   if not isinstance(code, str) or not code.strip():
      raise DocumentError("a point handler has code ({ ... } after the point)")
   problem = code_problem(key, name, point, code)
   if problem is not None:
      raise DocumentError(problem)


def add_handler(doc: Document, key: str, name: str, point: str, code: str = NEW_CODE,
                choices: list[str] | None = None, index: int | None = None) -> int:
   """!Adds a point handler.
   @param doc      battle Document
   @param key      one of handler_lists()
   @param name     the entry
   @param point    the point it modifies
   @param code     its code (default x1)
   @param choices  point_choices(), or None
   @param index    position, or None for the end
   @return its index
   """
   _check(key, name, point, code, choices)
   if key in logic_lists():
      def change(members: list[Any], points: list[int]) -> int:
         """!Inserts the member before the index-th point member (or after the others)."""
         at = len(points) if index is None else max(0, min(len(points), int(index)))
         members.insert(points[at] if at < len(points) else len(members), _member(key, name, point, code))
         return at
      return _edit_members(doc, key, name, change, create=True)
   lst = _live(doc, key, name)
   at = len(lst) if index is None else max(0, min(len(lst), int(index)))
   lst.insert(at, {"point": point, "code": code.strip()})
   return at


def set_handler(doc: Document, key: str, name: str, index: int, point: str | None = None, code: str | None = None,
                choices: list[str] | None = None) -> None:
   """!Changes a point handler's point and / or code.
   @param doc      battle Document
   @param key      one of handler_lists()
   @param name     the entry
   @param index    the handler
   @param point    new point, or None to keep it
   @param code     new code, or None to keep it
   @param choices  point_choices(), or None
   @return None
   """
   if key in logic_lists():
      current = handlers(doc, key, name)
      if not 0 <= index < len(current):
         raise DocumentError(f"{name} has no point handler {index}")
      new_point = point if point is not None else current[index]["point"]
      new_code = code if code is not None else current[index]["code"]
      _check(key, name, new_point, new_code, choices if point is not None else None)

      def change(members: list[Any], points: list[int]) -> None:
         """!Replaces the index-th point member."""
         members[points[index]] = _member(key, name, new_point, new_code)
      _edit_members(doc, key, name, change)
      return
   lst = _live(doc, key, name)
   if not 0 <= index < len(lst) or not isinstance(lst[index], dict):
      _drop_empty(doc, key, name)
      raise DocumentError(f"{name} has no point handler {index}")
   h = lst[index]
   new_point = point if point is not None else h.get("point")
   new_code = code if code is not None else h.get("code")
   _check(key, name, new_point, new_code, choices if point is not None else None)
   h["point"] = new_point
   h["code"] = new_code.strip()


def remove_handler(doc: Document, key: str, name: str, index: int) -> None:
   """!Removes a point handler.
   @param doc    battle Document
   @param key    one of handler_lists()
   @param name   the entry
   @param index  the handler
   @return None
   """
   if key in logic_lists():
      if not 0 <= index < len(handlers(doc, key, name)):
         raise DocumentError(f"{name} has no point handler {index}")

      def change(members: list[Any], points: list[int]) -> None:
         """!Drops the index-th point member (the logic block stays, with its other members)."""
         del members[points[index]]
      _edit_members(doc, key, name, change)
      return
   lst = _live(doc, key, name)
   if not 0 <= index < len(lst):
      _drop_empty(doc, key, name)
      raise DocumentError(f"{name} has no point handler {index}")
   del lst[index]
   _drop_empty(doc, key, name)


def move_handler(doc: Document, key: str, name: str, index: int, delta: int) -> bool:
   """!Moves a point handler up or down (handlers of one point run in order).
   @param doc    battle Document
   @param key    one of handler_lists()
   @param name   the entry
   @param index  the handler
   @param delta  -1 up, +1 down
   @return True if it moved
   """
   j = index + delta
   if key in logic_lists():
      count = len(handlers(doc, key, name))
      if not (0 <= index < count and 0 <= j < count):
         return False

      def change(members: list[Any], points: list[int]) -> None:
         """!Swaps two point members (the members between them keep their places)."""
         a, b = points[index], points[j]
         members[a], members[b] = members[b], members[a]
      _edit_members(doc, key, name, change)
      return True
   lst = _live(doc, key, name)
   if not (0 <= index < len(lst) and 0 <= j < len(lst)):
      _drop_empty(doc, key, name)
      return False
   lst[index], lst[j] = lst[j], lst[index]
   return True


def holder_line(row: HolderRow) -> str:
   """!A holder as one line of text.
   @param row  a holder_rows() row
   @return the line
   """
   shown = "announced" if row["announce"] else "not announced"
   return f"{row['index']} {row['name']}: {shown}; {row['handlers']} point handler(s); {len(row['uses'])} use(s)"


def report(doc: Document, key: str) -> list[str]:
   """!The passives or items as text lines.
   @param doc  battle Document
   @param key  "passives" or "items"
   @return lines
   """
   return [holder_line(r) for r in holder_rows(doc, key)]
