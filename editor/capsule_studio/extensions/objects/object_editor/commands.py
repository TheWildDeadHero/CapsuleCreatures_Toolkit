"""!`capsule-studio objects ...`: everything the Objects panel and the Objects
map tool do, from the command line (parity).

Objects are addressed as MAP OBJECT, OBJECT being a local ID (as `show`
lists them) or a name; pages by their index (as `show` lists them). Changes
are compiled with the engine before anything is saved. `--args` gives a
movement's settings as JSON (`--movement roam --args '{"choices": ["up",
"down"], "delays": "short"}'`), `view MAP L R U D` a map's object view and
`stacked MAP on|off` whether its objects may share a cell.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from capsule_studio.core import objects
from capsule_studio.core.document import DocumentError
from capsule_studio.core.world import Project

if TYPE_CHECKING:
   import argparse

   from capsule_studio.core.document import Document
   from capsule_studio.plugins.registry import ExtensionContext

## A JSON object (an object or a page).
JsonDict = dict[str, Any]
## A command's body: callable(parsed arguments) -> exit status, or None for 0.
CommandRun = Callable[["argparse.Namespace"], int | None]
## A command's argument setup: callable(parser), its result unused.
CommandSetup = Callable[["argparse.ArgumentParser"], object]
## How an option's text is read: int, str, or "range", "bool", "letters" or "json" (see _value()).
OptionType = type[int] | type[str] | str
## An option's value: a number, a text, on / off, a range [x, y], self switch letters or a JSON object.
OptionValue = int | str | bool | list[int] | list[str] | JsonDict
## An option table: (option, field, OptionType).
OptionTable = list[tuple[str, str, OptionType]]

## Object options: (option, field, type).
OPTIONS = [("--elevation", "elevation", int), ("--sprite", "sprite", str), ("--facing", "facing", str),
           ("--movement", "movement", str), ("--range", "range", "range"), ("--speed", "speed", int),
           ("--frequency", "frequency", int), ("--script", "script", str), ("--trigger", "trigger", str),
           ("--flag", "flag", str), ("--self-switches", "self_switches", "bool"), ("--sight", "sight", int),
           ("--until", "until", str), ("--kind", "kind", str), ("--args", "movement_args", "json")]
## Page field options: (option, field, type).
PAGE_OPTIONS = [("--sprite", "sprite", str), ("--facing", "facing", str), ("--movement", "movement", str),
                ("--range", "range", "range"), ("--speed", "speed", int), ("--frequency", "frequency", int),
                ("--script", "script", str), ("--trigger", "trigger", str), ("--hidden", "hidden", "bool"),
                ("--args", "movement_args", "json")]
## Page condition options: (option, "when" key, type).
WHEN_OPTIONS = [("--when-flag", "flag", str), ("--when-var", "var", str), ("--when-value", "value", int),
                ("--when-equal", "equal", "bool"), ("--when-self", "self", "letters")]
## Words for true and false.
BOOLS = {"on": True, "yes": True, "true": True, "1": True, "off": False, "no": False, "false": False, "0": False}
## Numbers in a range option (X,Y).
RANGE_PARTS = 2


class Usage(Exception):
   """!Bad arguments; the message says what to give."""
   pass


def _wrap(fn: CommandRun) -> Callable[[argparse.Namespace], int]:
   """!Turns Usage and DocumentError into messages and exit status 1.
   @param fn  callable(args)
   @return callable(args) -> status
   """
   def run(args: argparse.Namespace) -> int:
      try:
         return fn(args) or 0
      except (Usage, DocumentError) as e:
         print(f"capsule-studio objects: error: {e}")
         return 1
   return run


def _open(args: argparse.Namespace) -> Project:
   """!The world.
   @param args  parsed arguments (world)
   @return Project
   """
   return Project.open(args.world)


def _map(p: Project, name: str) -> Document:
   """!A map's Document.
   @param p     Project
   @param name  map name
   @return Document
   """
   if name not in p.map_names():
      raise Usage(f"no map {name!r} (maps: {', '.join(p.map_names())})")
   return p.map(name)


def _index(doc: Document, which: str) -> int:
   """!An object's local ID from a number or a name.
   @param doc    map Document
   @param which  local ID or name
   @return local ID
   """
   if which.isdigit():
      i = int(which)
      if i >= len(objects.objects(doc)):
         raise Usage(f"no object {i} (the map has {len(objects.objects(doc))})")
      return i
   return objects.index_of(doc, which)


def _save(p: Project) -> None:
   """!Compiles, then saves every changed document.
   @param p  Project
   @return None
   """
   error = p.validate()
   if error:
      raise DocumentError(error)
   p.save_all()


def _value(opt: str, typ: OptionType, raw: str) -> OptionValue:
   """!One option's value.
   @param opt  option name (for messages)
   @param typ  int, str, "range" (X,Y), "bool" (on / off), "letters" (A,B: self switches) or "json"
   @param raw  the text
   @return the value
   """
   if typ == "bool":
      if raw.lower() not in BOOLS:
         raise Usage(f"{opt} needs on or off, got {raw!r}")
      return BOOLS[raw.lower()]
   if typ == "letters":
      return [x.strip().upper() for x in raw.split(",") if x.strip()]
   if typ == "json":   # a movement's settings
      try:
         return json.loads(raw)
      except ValueError:
         raise Usage(f"{opt} needs a JSON object, e.g. '{{\"pace\": \"jog\"}}', got {raw!r}") from None
   try:
      if typ == "range":
         parts = raw.split(",")
         if len(parts) != RANGE_PARTS:
            raise ValueError
         return [int(parts[0]), int(parts[1])]
      return typ(raw)
   except ValueError:
      raise Usage(f"{opt} needs " + ("X,Y" if typ == "range" else "a number") + f", got {raw!r}") from None


def _fields(args: argparse.Namespace, options: OptionTable, prefix: str = "") -> dict[str, OptionValue | None]:
   """!Fields given on the command line ("-" clears one; a range is X,Y).
   @param args     parsed arguments
   @param options  OPTIONS, PAGE_OPTIONS or WHEN_OPTIONS
   @param prefix   prefix of the argparse destinations ("when_" for WHEN_OPTIONS)
   @return {field: value or None}
   """
   out: dict[str, OptionValue | None] = {}
   for opt, field, typ in options:
      raw = getattr(args, prefix + field, None)
      if raw is None:
         continue
      out[field] = None if raw == "-" else _value(opt, typ, raw)
   return out


def _page(args: argparse.Namespace) -> int | None:
   """!The --page argument.
   @param args  parsed arguments
   @return page index, or None for the object itself
   """
   return getattr(args, "page", None)


def _route_text(src: JsonDict) -> str | None:
   """!A route's steps on one line.
   @param src  object or page
   @return text, or None without a route
   """
   rt = src.get("route")
   if not isinstance(rt, dict):
      return None
   # the words for the route's non-default settings
   flags = [w for w, on in (("once", rt.get("repeat", True) is False), ("skip blocked", rt.get("skip"))) if on]
   return "; ".join(rt.get("steps") or []) + (f" ({', '.join(flags)})" if flags else "")


def cmd_show(args: argparse.Namespace) -> None:
   """!objects show. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   for n in [args.map] if args.map else p.map_names():
      doc = _map(p, n)
      items = objects.objects(doc)
      if not items and not args.map:
         continue
      print(n)
      for i, o in enumerate(items):
         at = o.get("at", ["?", "?"])
         print(f"  object {i} {o.get('name')} at {at[0]},{at[1]}: {objects.describe(o)}")
         route = _route_text(o)
         if route:
            print(f"    route: {route}")
         for j, pg in enumerate(o.get("pages") or []):
            print(f"    page {j}: {objects.describe_page(pg) if isinstance(pg, dict) else '?'}")
            route = _route_text(pg) if isinstance(pg, dict) else None
            if route:
               print(f"      route: {route}")


def cmd_check(args: argparse.Namespace) -> int:
   """!objects check. @param args  parsed arguments
   @return status"""
   p = _open(args)
   status = 0
   error = objects.check(p)
   if error:
      print(f"error: {error}")
      status = 1
   for d in objects.diagnostics(p, args.map):
      if d.level != "error":
         print(f"{d.level}: {d.message}")
   if status == 0:
      print("objects compile")
   return status


def cmd_add(args: argparse.Namespace) -> None:
   """!objects add. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   with doc.edit("Add object"):
      i = objects.add_object(doc, args.x, args.y, args.name, **_fields(args, OPTIONS))
   _save(p)
   print(f"{args.map}: object {i} {objects.objects(doc)[i]['name']} at {args.x},{args.y}")


def cmd_set(args: argparse.Namespace) -> None:
   """!objects set. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   with doc.edit("Change object"):
      objects.set_object(doc, i, **_fields(args, OPTIONS))
   _save(p)
   print(f"{args.map}: object {i}: {objects.describe(objects.objects(doc)[i])}")


def cmd_move(args: argparse.Namespace) -> None:
   """!objects move. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   with doc.edit("Move object"):
      objects.move_object(doc, i, args.x, args.y)
   _save(p)
   print(f"{args.map}: object {i} now at {args.x},{args.y}")


def cmd_rename(args: argparse.Namespace) -> None:
   """!objects rename. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   with doc.edit("Rename object"):
      objects.rename_object(doc, i, args.name)
   _save(p)
   print(f"{args.map}: object {i} is now {args.name}")


def cmd_remove(args: argparse.Namespace) -> None:
   """!objects remove. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   with doc.edit("Remove object"):
      shifted = objects.remove_object(doc, i)
   _save(p)
   print(f"{args.map}: removed object {i}")
   if shifted:
      print(f"  local IDs {i + 1}-{i + len(shifted)} moved down by one ({', '.join(shifted)}); "
            "scripts naming them by number must follow")


def _describe_page(doc: Document, i: int, j: int) -> str:
   """!A page's line for messages.
   @param doc  map Document
   @param i    local ID
   @param j    page index
   @return text
   """
   return f"object {i} page {j}: {objects.describe_page(objects.pages(doc, i)[j])}"


def cmd_page_add(args: argparse.Namespace) -> None:
   """!objects page-add. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   when = {k: v for k, v in _fields(args, WHEN_OPTIONS, "when_").items() if v is not None}
   with doc.edit("Add page"):
      j = objects.add_page(doc, i, when, **_fields(args, PAGE_OPTIONS))
   _save(p)
   print(f"{args.map}: {_describe_page(doc, i, j)}")


def cmd_page_set(args: argparse.Namespace) -> None:
   """!objects page-set. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   when = _fields(args, WHEN_OPTIONS, "when_")
   with doc.edit("Change page"):
      objects.set_page(doc, i, args.index, when or None, **_fields(args, PAGE_OPTIONS))
   _save(p)
   print(f"{args.map}: {_describe_page(doc, i, args.index)}")


def cmd_page_move(args: argparse.Namespace) -> None:
   """!objects page-move. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   with doc.edit("Move page"):
      objects.move_page(doc, i, args.index, args.to)
   _save(p)
   print(f"{args.map}: {_describe_page(doc, i, args.to)}")


def cmd_page_remove(args: argparse.Namespace) -> None:
   """!objects page-remove. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   with doc.edit("Remove page"):
      objects.remove_page(doc, i, args.index)
   _save(p)
   print(f"{args.map}: object {i}: removed page {args.index}")


def cmd_route_set(args: argparse.Namespace) -> None:
   """!objects route-set. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   steps = list(args.steps)
   if args.file:
      try:
         with open(args.file, encoding="utf-8") as f:
            steps += objects.route_steps(f.read())
      except OSError as e:
         raise Usage(f"cannot read {args.file}: {e}") from None
   if not steps:
      raise Usage("give the route's steps (one argument each, e.g. 'left 2' 'wait 30'), or --file")
   with doc.edit("Set route"):
      objects.set_route(doc, i, steps, repeat=args.repeat, skip=args.skip, page=_page(args))
   _save(p)
   src = objects.objects(doc)[i] if _page(args) is None else objects.pages(doc, i)[_page(args)]
   where = f"object {i}" + ("" if _page(args) is None else f" page {_page(args)}")
   print(f"{args.map}: {where} route: {_route_text(src)}")


def cmd_route_clear(args: argparse.Namespace) -> None:
   """!objects route-clear. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   with doc.edit("Remove route"):
      objects.set_route(doc, i, None, page=_page(args))
   _save(p)
   print(f"{args.map}: object {i}" + ("" if _page(args) is None else f" page {_page(args)}") + ": no route")


def cmd_option(args: argparse.Namespace) -> None:
   """!objects option. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   i = _index(doc, args.object)
   value = None if args.value == "-" else _value("value", "bool", args.value)
   with doc.edit("Change option"):
      objects.set_option(doc, i, args.option, value, page=_page(args))
   _save(p)
   src = objects.objects(doc)[i] if _page(args) is None else objects.pages(doc, i)[_page(args)]
   opts = src.get("options") or {}
   shown = ", ".join(f"{k} {'on' if v else 'off'}" for k, v in opts.items()) or "defaults"
   print(f"{args.map}: object {i}" + ("" if _page(args) is None else f" page {_page(args)}") + f" options: {shown}")


def cmd_view(args: argparse.Namespace) -> None:
   """!objects view. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   if args.sides:
      view = None if args.sides == ["-"] else [_value("view", int, v) for v in args.sides]
      with doc.edit("Object view"):
         objects.set_object_view(doc, view)
      _save(p)
   v = objects.object_view(doc)
   print(f"{args.map}: " + ("every object spawns at entry" if v is None else
                            "objects spawn within " + ", ".join(f"{n} {s}" for s, n in zip(objects.VIEW_SIDES, v))) +
         f" (at most {objects.max_objects(doc)} objects)")


def cmd_stacked(args: argparse.Namespace) -> None:
   """!objects stacked. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   if args.value is not None:
      with doc.edit("Stacked objects"):
         objects.set_stacked(doc, _value("stacked", "bool", args.value))
      _save(p)
   print(f"{args.map}: objects {'may' if doc.data.get('stacked_objects') else 'may not'} share a cell")


def register(ctx: ExtensionContext) -> None:
   """!Adds the commands.
   @param ctx  ExtensionContext
   @return None
   """
   def add(name: str, help: str, setup: CommandSetup, fn: CommandRun) -> None:
      def full(q: argparse.ArgumentParser) -> None:
         q.add_argument("world", help="world.json")
         setup(q)
      ctx.add_command(name, help, full, _wrap(fn))

   def target(q: argparse.ArgumentParser) -> None:
      q.add_argument("map")
      q.add_argument("object", help="local ID or name")

   def options(q: argparse.ArgumentParser, which: OptionTable) -> None:
      for opt, field, typ in which:
         extra = {"range": "; X,Y", "bool": "; on or off"}.get(typ, "")
         q.add_argument(opt, dest=field, help=f"{field} ('-' removes it{extra})")

   def when_options(q: argparse.ArgumentParser) -> None:
      for opt, field, typ in WHEN_OPTIONS:
         extra = {"bool": "; on or off", "letters": "; e.g. A or A,B"}.get(typ, "")
         q.add_argument(opt, dest="when_" + field, help=f"condition {field} ('-' removes it{extra})")

   def page(q: argparse.ArgumentParser) -> None:
      q.add_argument("--page", type=int, help="a page of the object instead of the object itself")

   add("view", "show or set a map's object view: LEFT RIGHT UP DOWN cells around the player (- removes it)",
       lambda q: (q.add_argument("map"), q.add_argument("sides", nargs="*")), cmd_view)
   add("stacked", "show or set whether a map's objects may share a cell",
       lambda q: (q.add_argument("map"), q.add_argument("value", nargs="?", help="on or off")), cmd_stacked)
   add("show", "list every map's objects, their routes and pages",
       lambda q: q.add_argument("--map", help="only this map"), cmd_show)
   add("check", "report object problems; status 1 on errors",
       lambda q: q.add_argument("--map", help="only this map"), cmd_check)
   add("add", "add an object on a cell",
       lambda q: (q.add_argument("map"), q.add_argument("x", type=int), q.add_argument("y", type=int),
                  q.add_argument("--name"), options(q, OPTIONS)), cmd_add)
   add("set", "change an object's fields (--sight 0 or - makes it no spotter; --until FLAG ends its watch)",
       lambda q: (target(q), options(q, OPTIONS)), cmd_set)
   add("move", "move an object to another cell",
       lambda q: (target(q), q.add_argument("x", type=int), q.add_argument("y", type=int)), cmd_move)
   add("rename", "rename an object (its world_ids.h name follows)",
       lambda q: (target(q), q.add_argument("name")), cmd_rename)
   add("remove", "remove an object (the local IDs after it move down)", target, cmd_remove)
   add("page-add", "add an event page (conditions --when-*; the last page that holds applies)",
       lambda q: (target(q), when_options(q), options(q, PAGE_OPTIONS)), cmd_page_add)
   add("page-set", "change a page's conditions and fields ('-' removes one: the object's value applies)",
       lambda q: (target(q), q.add_argument("index", type=int), when_options(q), options(q, PAGE_OPTIONS)),
       cmd_page_set)
   add("page-move", "move a page to another place (later pages win)",
       lambda q: (target(q), q.add_argument("index", type=int), q.add_argument("to", type=int)), cmd_page_move)
   add("page-remove", "remove a page",
       lambda q: (target(q), q.add_argument("index", type=int)), cmd_page_remove)
   add("route-set", "give an object (or --page) a move route; its movement becomes custom",
       lambda q: (target(q), q.add_argument("steps", nargs="*", help="steps, one argument each ('left 2')"),
                  q.add_argument("--file", help="a text file of steps, one per line"), page(q),
                  q.add_argument("--once", dest="repeat", action="store_false", default=None,
                                 help="do not start over at the end"),
                  q.add_argument("--repeat", dest="repeat", action="store_true", help="start over at the end"),
                  q.add_argument("--skip", dest="skip", action="store_true", default=None,
                                 help="skip blocked steps"),
                  q.add_argument("--wait", dest="skip", action="store_false", help="wait at blocked steps")),
       cmd_route_set)
   add("route-clear", "remove a move route (a custom movement becomes static)",
       lambda q: (target(q), page(q)), cmd_route_clear)
   add("option", "set a movement option on or off ('-': the default)",
       lambda q: (target(q), q.add_argument("option", choices=list(objects.OPTIONS)),
                  q.add_argument("value", help="on, off or -"), page(q)), cmd_option)
