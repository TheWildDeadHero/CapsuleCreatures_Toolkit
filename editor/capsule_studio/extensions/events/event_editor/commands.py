"""!`capsule-studio events ...`: everything the Events panel and the Events
map tool do, from the command line (D-10 parity).

Events are addressed as MAP KIND INDEX (KIND: warp, trigger or sign; INDEX
as `show` lists them). Changes are compiled with the engine before anything
is saved. I3: `--trigger` takes step, press, arrow, door or none, `--to
dynamic` leaves the destination to the game, and `unpainted MAP on|off`
lets a map's events stand on unpainted cells. S3: `--door door:KEY` binds a
door animation to a warp's cell (D-30). S4 (engine C10): `--run step|immediate`
sets how a trigger runs (immediate: to its end at once; its script may not wait).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from capsule_studio.core import events
from capsule_studio.core.document import DocumentError
from capsule_studio.core.world import Project

if TYPE_CHECKING:
   import argparse

   from capsule_studio.core.document import Document
   from capsule_studio.plugins.registry import ExtensionContext

## A command's body: callable(parsed arguments) -> exit status, or None for 0.
CommandRun = Callable[["argparse.Namespace"], int | None]
## A command's argument setup: callable(parser), its result unused.
CommandSetup = Callable[["argparse.ArgumentParser"], object]
## An event field's value from the command line (None clears it).
FieldValue = int | str | None

## Event options: (option, field, type).
OPTIONS = [("--elevation", "elevation", int), ("--to", "to", str), ("--warp", "warp", int),
           ("--trigger", "trigger", str), ("--direction", "direction", str), ("--transition", "transition", str),
           ("--script", "script", str),
           ("--var", "var", str), ("--value", "value", int), ("--facing", "facing", str), ("--flag", "flag", str),
           ("--door", "door", str),   # S3 (D-30): a warp's door animation, door:KEY
           ("--run", "run", str)]     # S4 (C10): a trigger's run, step or immediate
## S4: option destinations that differ from their field (argparse's "run" is the command's callback).
DESTS = {"run": "run_mode"}


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
         print(f"capsule-studio events: error: {e}")
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


def _save(p: Project) -> None:
   """!Compiles, then saves every changed document.
   @param p  Project
   @return None
   """
   error = p.validate()
   if error:
      raise DocumentError(error)
   p.save_all()


def _fields(args: argparse.Namespace, kind: str) -> dict[str, FieldValue]:
   """!Event fields given on the command line ("-" clears one).
   @param args  parsed arguments
   @param kind  event kind
   @return {field: value or None}
   """
   out: dict[str, FieldValue] = {}
   allowed = events.FIELDS[events._kind(kind)]   # "warp" or "warps": the plural key FIELDS uses
   for opt, field, typ in OPTIONS:
      raw = getattr(args, DESTS.get(field, field), None)
      if raw is None:
         continue
      if field not in allowed:
         raise Usage(f"a {kind} has no {opt}")
      if raw == "-":
         out[field] = None
         continue
      try:
         out[field] = typ(raw)
      except ValueError:
         raise Usage(f"{opt} needs a number, got {raw!r}") from None
   return out


def cmd_show(args: argparse.Namespace) -> None:
   """!events show. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   print(f"scripts: {p.world.data.get('scripts', '(none)')}")
   for h in events.step_hooks(p):
      phase = f", phase {h['phase']}" if "phase" in h else ""
      print(f"step hook {h.get('name')}: every {h.get('period')} steps{phase}")
   for n in [args.map] if args.map else p.map_names():
      doc = _map(p, n)
      root = events.area(doc, n)
      print(f"{n}" + ("" if root == n else f" (area {root})"))
      for kind, i, e in events.all_events(doc):
         at = e.get("at", ["?", "?"])
         print(f"  {events.KINDS[kind]} {i} at {at[0]},{at[1]}: {events.describe(kind, e)}")


def cmd_check(args: argparse.Namespace) -> int:
   """!events check. @param args  parsed arguments
   @return status"""
   p = _open(args)
   status = 0
   for d in events.diagnostics(p, args.map):
      print(f"{d.level}: {d.message}")
      status = 1 if d.level == "error" else status
   if status == 0:
      print("events compile")
   return status


def cmd_add(args: argparse.Namespace) -> None:
   """!events add. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   with doc.edit("Add event"):
      i = events.add_event(doc, args.kind, args.x, args.y, **_fields(args, args.kind))
   _save(p)
   print(f"{args.map}: {args.kind} {i} at {args.x},{args.y}")


def cmd_set(args: argparse.Namespace) -> None:
   """!events set. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   with doc.edit("Change event"):
      events.set_event(doc, args.kind, args.index, **_fields(args, args.kind))
   _save(p)
   e = events.events(doc, args.kind)[args.index]
   print(f"{args.map}: {args.kind} {args.index}: {events.describe(args.kind, e)}")


def cmd_move(args: argparse.Namespace) -> None:
   """!events move. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   with doc.edit("Move event"):
      events.move_event(doc, args.kind, args.index, args.x, args.y)
   _save(p)
   print(f"{args.map}: {args.kind} {args.index} now at {args.x},{args.y}")


def cmd_remove(args: argparse.Namespace) -> None:
   """!events remove. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   _map(p, args.map)
   events.remove_event(p, args.map, args.kind, args.index)
   _save(p)
   print(f"{args.map}: removed {args.kind} {args.index}")


def cmd_area(args: argparse.Namespace) -> None:
   """!events area. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   if args.root is not None:
      root = None if args.root == "-" else args.root
      with doc.edit("Set area"):
         events.set_area(doc, args.map, root)
      _save(p)
   print(f"{args.map}: area {events.area(doc, args.map)}")


def cmd_scripts(args: argparse.Namespace) -> None:
   """!events scripts. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   if args.path is not None:
      with p.world.edit("Set scripts manifest"):
         events.set_scripts(p, None if args.path == "-" else args.path)
      _save(p)
   print(f"scripts: {p.world.data.get('scripts', '(none)')}")
   n = events.names(p)
   if n["error"]:
      print(f"  {n['error']}")
   else:
      print(f"  scripts: {', '.join(n['scripts']) or '-'}")
      print(f"  flags: {', '.join(n['flags']) or '-'}")
      print(f"  variables: {', '.join(f'{v} {lo}..{hi}' for v, (lo, hi) in n['vars'].items()) or '-'}")


def cmd_unpainted(args: argparse.Namespace) -> None:
   """!events unpainted (I3). @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = _map(p, args.map)
   if args.value is not None:
      if args.value not in ("on", "off"):
         raise Usage(f"unpainted needs on or off, got {args.value!r}")
      with doc.edit("Unpainted events"):
         events.set_unpainted_events(doc, args.value == "on")
      _save(p)
   print(f"{args.map}: events and objects {'may' if doc.data.get('unpainted_events') else 'may not'} stand on "
         "unpainted cells")


def cmd_hook_add(args: argparse.Namespace) -> None:
   """!events hook-add. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   with p.world.edit("Add step hook"):
      events.add_hook(p, args.name, args.period, args.phase)
   _save(p)
   print(f"step hook {args.name}: every {args.period} steps")


def cmd_hook_remove(args: argparse.Namespace) -> None:
   """!events hook-remove. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   with p.world.edit("Remove step hook"):
      events.remove_hook(p, args.name)
   _save(p)
   print(f"removed step hook {args.name}")


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

   def kind(q: argparse.ArgumentParser) -> None:
      q.add_argument("map")
      q.add_argument("kind", choices=["warp", "trigger", "sign"])

   def options(q: argparse.ArgumentParser) -> None:
      for opt, field, _typ in OPTIONS:
         q.add_argument(opt, dest=DESTS.get(field, field), help=f"{field} ('-' removes it)")

   add("show", "list the world's scripts manifest, step hooks and every map's events",
       lambda q: q.add_argument("--map", help="only this map"), cmd_show)
   add("check", "report event problems; status 1 on errors",
       lambda q: q.add_argument("--map", help="only this map"), cmd_check)
   add("add", "add a warp, trigger or sign on a cell",
       lambda q: (kind(q), q.add_argument("x", type=int), q.add_argument("y", type=int), options(q)), cmd_add)
   add("set", "change an event's fields",
       lambda q: (kind(q), q.add_argument("index", type=int), options(q)), cmd_set)
   add("move", "move an event to another cell",
       lambda q: (kind(q), q.add_argument("index", type=int), q.add_argument("x", type=int),
                  q.add_argument("y", type=int)), cmd_move)
   add("remove", "remove an event (warps after it are renumbered everywhere)",
       lambda q: (kind(q), q.add_argument("index", type=int)), cmd_remove)
   add("area", "show or set a map's area root (B-2; '-' for its own area)",
       lambda q: (q.add_argument("map"), q.add_argument("root", nargs="?")), cmd_area)
   add("scripts", "show or set the world's scripts manifest ('-' removes it), with its names",
       lambda q: q.add_argument("path", nargs="?", help="relative to the world file"), cmd_scripts)
   add("hook-add", "add a step hook",
       lambda q: (q.add_argument("name"), q.add_argument("period", type=int),
                  q.add_argument("--phase", type=int)), cmd_hook_add)
   add("hook-remove", "remove a step hook", lambda q: q.add_argument("name"), cmd_hook_remove)
   add("unpainted", "show or set whether a map's events and objects may stand on unpainted cells (I3)",
       lambda q: (q.add_argument("map"), q.add_argument("value", nargs="?", help="on or off")), cmd_unpainted)
