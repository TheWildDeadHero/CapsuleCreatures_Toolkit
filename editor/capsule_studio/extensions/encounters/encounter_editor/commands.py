"""!`capsule-studio encounters ...`: everything the Encounters panel and
the Encounter area brush do, from the command line (D-10 parity).

Tables are addressed with --map NAME (a map's file; TABLE is its index)
or --shared (the shared file; TABLE is the shared table's name). Changes
are compiled with the engine before anything is saved.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from capsule_studio.core import encounters as enc
from capsule_studio.core import maps
from capsule_studio.core.document import DocumentError
from capsule_studio.core.world import Project

if TYPE_CHECKING:
   import argparse

   from capsule_studio.core.document import Document
   from capsule_studio.plugins.registry import ExtensionContext

## A JSON object (a table or an entry).
JsonDict = dict[str, Any]
## A command's body: callable(parsed arguments) -> exit status, or None for 0.
CommandRun = Callable[["argparse.Namespace"], int | None]
## A command's argument setup: callable(parser), its result unused.
CommandSetup = Callable[["argparse.ArgumentParser"], object]

## Shares are printed as percentages.
PERCENT = 100


class Usage(Exception):
   """!Bad arguments; the message says what to give."""
   pass


def _csv(text: str | None) -> list[str] | None:
   """!"a,b" to ["a", "b"] ("" or "-" to []).
   @param text  text, or None
   @return list, or None
   """
   if text is None:
      return None
   if text in ("", "-"):
      return []
   return [t.strip() for t in text.split(",") if t.strip()]


def _levels(text: str) -> int | list[int]:
   """!"3" or "3-5" to a level or [3, 5].
   @param text  text
   @return int or list
   """
   try:
      if "-" in text:
         a, b = text.split("-", 1)
         return [int(a), int(b)]
      return int(text)
   except ValueError:
      raise Usage(f"levels look like 5 or 3-5, got {text!r}") from None


def _rate(text: str | None) -> int | str | None:
   """!A rate from the command line ("1/10", "12.5%", "1").
   @param text  text, or None
   @return value as stored, or None
   """
   if text is None:
      return None
   try:
      return int(text)
   except ValueError:
      return text


def _save(p: Project) -> None:
   """!Compiles, then saves every changed document.
   @param p  Project
   @return None
   """
   error = p.validate()
   if error:
      raise DocumentError(error)
   p.save_all()


def _target(p: Project, args: argparse.Namespace, create: bool = False) -> tuple[Document, int | None]:
   """!The Document and table index a command addresses.
   @param p       Project
   @param args    parsed arguments (map / shared / table)
   @param create  create the map's encounter file when it has none
   @return (Document, table index or None)
   """
   # exactly one of --map and --shared
   if args.shared == (args.map is not None):
      raise Usage("give --map NAME or --shared")
   if args.shared:
      doc = enc.shared_doc(p, create=create)
      if doc is None:
         raise Usage("the world has no shared tables file (shared-add creates it)")
      if getattr(args, "table", None) is None:
         return doc, None
      names = [t.get("name") for t in enc.tables(doc)]
      if args.table not in names:
         raise Usage(f"no shared table {args.table!r} (there are: {', '.join(names) or 'none'})")
      return doc, names.index(args.table)
   if args.map not in p.map_names():
      raise Usage(f"the world has no map {args.map!r}")
   doc = enc.map_doc(p, args.map, create=create)
   if doc is None:
      raise Usage(f"map {args.map} has no encounter file yet (table-add creates it)")
   if getattr(args, "table", None) is None:
      return doc, None
   try:
      i = int(args.table)
   except ValueError:
      raise Usage(f"tables of a map are given by index, got {args.table!r}") from None
   return doc, i


def _where(q: argparse.ArgumentParser, table: bool = True) -> None:
   """!Adds --map / --shared (and TABLE).
   @param q      parser
   @param table  also the TABLE argument
   @return None
   """
   q.add_argument("--map", help="map name")
   q.add_argument("--shared", action="store_true", help="the shared tables file")
   if table:
      q.add_argument("table", help="table index (--map) or shared table name (--shared)")


def _wrap(fn: CommandRun) -> Callable[[argparse.Namespace], int]:
   """!Turns Usage and DocumentError into messages and exit status 1.
   @param fn  callable(args)
   @return callable(args) -> status
   """
   def run(args: argparse.Namespace) -> int:
      try:
         return fn(args) or 0
      except (Usage, DocumentError) as e:
         print(f"capsule-studio encounters: error: {e}")
         return 1
   return run


# -- reading --------------------------------------------------------------------------------

def cmd_show(args: argparse.Namespace) -> None:
   """!encounters show. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   names, level_max = enc.species(p)
   print(f"battle: {p.world.data.get('battle') or '(none)'} ({len(names)} species, levels up to {level_max})")
   for m in enc.methods(p):
      vs = m.get("vehicles")
      print(f"method {m.get('name')}: {m.get('trigger', 'step')}" + (f", vehicles {', '.join(vs)}" if vs else ""))
   print("conditions: " + (", ".join(enc.conditions(p)) or "(none)"))
   shown = [args.map] if args.map else p.map_names()
   for n in shown:
      doc = enc.map_doc(p, n)
      cells = enc.slot_cells(p.map(n).data)
      print(f"map {n}: " + (f"{doc.path.name}" if doc else "no encounter file") +
            (", encounter cells per slot: " + ", ".join(f"{s}: {len(c)}" for s, c in sorted(cells.items()))
             if cells else ""))
      for i, t in enumerate(enc.tables(doc) if doc else []):
         rate, es = enc.resolved(p, t)
         src = f" -> shared {t['table']}" if "table" in t else ""
         print(f"  [{i}] slot {t.get('slot')} {t.get('method')} {enc.label(t)!r} rate {enc.format_rate(rate)}"
               f"{src}, {len(es)} entries")
         _print_entries(p, t, args.when)
   s = enc.shared_doc(p)
   if s is not None and not args.map:
      print(f"shared tables ({s.path.name}):")
      for t in enc.tables(s):
         print(f"  {t.get('name')}: rate {enc.format_rate(t.get('rate'))}, {len(t.get('entries', []))} entries")
         _print_entries(p, t, args.when)


def _print_entries(p: Project, t: JsonDict, when: str | None) -> None:
   """!Prints a table's entries with their shares.
   @param p     Project
   @param t     table object
   @param when  active conditions (comma-separated) or None
   @return None
   """
   active = _csv(when) or []
   for j, (e, w, share) in enumerate(enc.shares(p, t, active)):
      lv = e.get("levels")
      lv = f"{lv[0]}-{lv[1]}" if isinstance(lv, list) else lv
      extra = []
      if e.get("requires"):
         extra.append("needs " + ",".join(e["requires"]))
      if e.get("excludes"):
         extra.append("not " + ",".join(e["excludes"]))
      if e.get("modifiers"):
         extra.append(enc.format_modifiers(e["modifiers"]))
      print(f"      {j}: {e.get('species')} L{lv} weight {e.get('weight')} -> {share * PERCENT:.1f}%"
            + (f" ({'; '.join(extra)})" if extra else ""))


def cmd_check(args: argparse.Namespace) -> int:
   """!encounters check. @param args  parsed arguments
   @return status"""
   p = Project.open(args.world)
   found = enc.diagnostics(p, args.map)
   for d in found:
      print(f"{d.level}: {d.message}" + (f" at {d.at[0]},{d.at[1]}" if d.at else ""))
   if not found:
      print("ok: no encounter problems")
   return 1 if any(d.level == "error" for d in found) else 0


# -- world settings -------------------------------------------------------------------------

def cmd_battle(args: argparse.Namespace) -> None:
   """!encounters battle. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   with p.world.edit("Battle data"):
      enc.set_battle(p.world, None if args.path == "-" else args.path)
   _save(p)


def cmd_method_add(args: argparse.Namespace) -> None:
   """!encounters method-add. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   with p.world.edit("Add method"):
      enc.add_method(p.world, args.name, args.trigger, _csv(args.vehicles))
   _save(p)


def cmd_method_set(args: argparse.Namespace) -> None:
   """!encounters method-set. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   with p.world.edit("Method"):
      # False keeps the vehicle classes, None means every class
      vehicles = False if args.vehicles is None else (None if args.vehicles == "all" else _csv(args.vehicles))
      enc.set_method(p.world, args.name, args.trigger, vehicles)
   _save(p)


def _renamer(kind: str) -> CommandRun:
   """!A rename command.
   @param kind  "method", "condition" or "shared"
   @return callable(args)
   """
   def run(args: argparse.Namespace) -> None:
      p = Project.open(args.world)
      n = enc.rename(p, kind, args.old, args.new)
      _save(p)
      print(f"{n} file(s) changed")
   return run


def _remover(kind: str) -> CommandRun:
   """!A remove command.
   @param kind  "method", "condition" or "shared"
   @return callable(args)
   """
   def run(args: argparse.Namespace) -> None:
      p = Project.open(args.world)
      enc.remove(p, kind, args.name)
      _save(p)
   return run


def cmd_condition_add(args: argparse.Namespace) -> None:
   """!encounters condition-add. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   with p.world.edit("Add condition"):
      enc.add_condition(p.world, args.name)
   _save(p)


# -- tables ------------------------------------------------------------------------------------

def cmd_table_add(args: argparse.Namespace) -> None:
   """!encounters table-add. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   if args.map not in p.map_names():
      raise Usage(f"the world has no map {args.map!r}")
   if args.method not in enc.method_names(p):
      raise Usage(f"no method {args.method!r} (the world's: {', '.join(enc.method_names(p))})")
   doc = enc.map_doc(p, args.map, create=True)
   with doc.edit("Add table"):
      # a table using a shared table takes the shared table's rate unless one is given
      rate = _rate(args.rate) if args.rate is not None else (None if args.shared_table else enc.DEFAULT_RATE)
      i = enc.add_table(doc, args.slot, args.method, rate, args.label, args.shared_table)
   _save(p)
   print(f"table {i}")


def cmd_table_set(args: argparse.Namespace) -> None:
   """!encounters table-set. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   args.shared = False
   doc, i = _target(p, args)
   # False keeps the rate, None drops the table's own rate
   rate = False if args.rate is None else (None if args.rate == "-" else _rate(args.rate))
   with doc.edit("Table"):
      enc.set_table(doc, i, args.slot, args.method, rate, args.label)
   _save(p)


def cmd_table_remove(args: argparse.Namespace) -> None:
   """!encounters table-remove. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   args.shared = False
   doc, i = _target(p, args)
   with doc.edit("Remove table"):
      enc.remove_table(doc, i)
   _save(p)


def cmd_link(args: argparse.Namespace) -> None:
   """!encounters link. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   args.shared = False
   doc, i = _target(p, args)
   if enc.find_shared(p, args.name) is None:
      raise Usage(f"no shared table {args.name!r}")
   with doc.edit("Use shared table"):
      enc.link_shared(doc, i, args.name)
   _save(p)


def cmd_unlink(args: argparse.Namespace) -> None:
   """!encounters unlink. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   args.shared = False
   doc, i = _target(p, args)
   with doc.edit("Copy shared table"):
      enc.unlink_shared(p, doc, i)
   _save(p)


def cmd_shared_add(args: argparse.Namespace) -> None:
   """!encounters shared-add. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   doc = enc.shared_doc(p, create=True)
   with doc.edit("Add shared table"):
      enc.add_shared(doc, args.name, _rate(args.rate) or enc.DEFAULT_RATE)
   _save(p)


def cmd_shared_set(args: argparse.Namespace) -> None:
   """!encounters shared-set. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   args.shared, args.map = True, None
   doc, i = _target(p, args)
   with doc.edit("Shared table"):
      enc.table(doc, i)["rate"] = enc.check_rate(_rate(args.rate))
   _save(p)


# -- entries ------------------------------------------------------------------------------------

def cmd_entry_add(args: argparse.Namespace) -> None:
   """!encounters entry-add. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   doc, i = _target(p, args)
   with doc.edit("Add entry"):
      mods = enc.parse_modifiers(args.modifiers) if args.modifiers else None
      j = enc.add_entry(doc, i, args.species, _levels(args.levels), args.weight, _csv(args.requires),
                        _csv(args.excludes), mods)
   _save(p)
   print(f"entry {j}")


def cmd_entry_set(args: argparse.Namespace) -> None:
   """!encounters entry-set. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   doc, i = _target(p, args)
   with doc.edit("Entry"):
      mods = None if args.modifiers is None else enc.parse_modifiers(args.modifiers)
      enc.set_entry(doc, i, args.entry, args.species, None if args.levels is None else _levels(args.levels),
                    args.weight, _csv(args.requires), _csv(args.excludes), mods)
   _save(p)


def cmd_entry_remove(args: argparse.Namespace) -> None:
   """!encounters entry-remove. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   doc, i = _target(p, args)
   with doc.edit("Remove entry"):
      enc.remove_entry(doc, i, args.entry)
   _save(p)


def cmd_entry_move(args: argparse.Namespace) -> None:
   """!encounters entry-move. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   doc, i = _target(p, args)
   with doc.edit("Move entry"):
      print(f"entry {enc.move_entry(doc, i, args.entry, -1 if args.direction == 'up' else 1)}")
   _save(p)


# -- painting -----------------------------------------------------------------------------------

def cmd_area(args: argparse.Namespace) -> None:
   """!encounters area (the Encounter area brush on a rectangle). @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   if args.map not in p.map_names():
      raise Usage(f"the world has no map {args.map!r}")
   doc = p.map(args.map)
   off = args.slot == "off"
   slot = 0 if off else int(args.slot)
   if not 0 <= slot < enc.MAX_SLOTS:
      raise Usage("slots are 0-15 (or off)")
   with doc.edit("Encounters"):
      n = maps.rect_attributes(doc, args.x, args.y, args.x2, args.y2, encounter=not off, slot=slot)
   _save(p)
   print(f"{n} cells")


def register(ctx: ExtensionContext) -> None:
   """!Adds the commands.
   @param ctx  ExtensionContext
   @return None
   """
   def world(q: argparse.ArgumentParser) -> None:
      q.add_argument("world", help="world.json")

   def add(name: str, help: str, setup: CommandSetup, fn: CommandRun) -> None:
      def full(q: argparse.ArgumentParser) -> None:
         world(q)
         setup(q)
      ctx.add_command(name, help, full, _wrap(fn))

   add("show", "list the world's encounter settings and every map's tables with their shares",
       lambda q: (q.add_argument("--map", help="only this map"),
                  q.add_argument("--when", metavar="CONDITIONS", help="active conditions for the shares (a,b)")),
       cmd_show)
   add("check", "report encounter problems (and the compile error); status 1 on errors",
       lambda q: q.add_argument("--map", help="only this map"), cmd_check)
   add("battle", "name the battle manifest species come from (- removes it)",
       lambda q: q.add_argument("path", help="relative to the world file"), cmd_battle)
   add("method-add", "add an encounter method",
       lambda q: (q.add_argument("name"), q.add_argument("--trigger", choices=enc.TRIGGERS, default="step"),
                  q.add_argument("--vehicles", help="step methods: vehicle classes (a,b; default every class)")),
       cmd_method_add)
   add("method-set", "change a method's trigger or vehicle classes",
       lambda q: (q.add_argument("name"), q.add_argument("--trigger", choices=enc.TRIGGERS),
                  q.add_argument("--vehicles", help="vehicle classes (a,b), or all")), cmd_method_set)
   for kind, label in (("method", "method"), ("condition", "condition"), ("shared", "shared table")):
      add(f"{kind}-rename", f"rename a {label} everywhere it is used",
          lambda q: (q.add_argument("old"), q.add_argument("new")), _renamer(kind))
      add(f"{kind}-remove", f"remove a {label} (refused while it is used)",
          lambda q: q.add_argument("name"), _remover(kind))
   add("condition-add", "add a condition name (one bit)", lambda q: q.add_argument("name"), cmd_condition_add)
   add("table-add", "add a table to a map (creates its encounter file)",
       lambda q: (q.add_argument("map"), q.add_argument("slot", type=int), q.add_argument("method"),
                  q.add_argument("--rate", help='trigger odds, e.g. "1/10" or "12.5%%"'),
                  q.add_argument("--label"), q.add_argument("--shared-table", metavar="NAME",
                                                            help="use this shared table")),
       cmd_table_add)
   add("table-set", "change a map table's slot, method, rate (- drops an override) or label",
       lambda q: (q.add_argument("--map", required=True), q.add_argument("table"),
                  q.add_argument("--slot", type=int), q.add_argument("--method"), q.add_argument("--rate"),
                  q.add_argument("--label")), cmd_table_set)
   add("table-remove", "remove a map table",
       lambda q: (q.add_argument("--map", required=True), q.add_argument("table")), cmd_table_remove)
   add("link", "make a map table use a shared table",
       lambda q: (q.add_argument("--map", required=True), q.add_argument("table"), q.add_argument("name")),
       cmd_link)
   add("unlink", "copy the shared table a map table uses into it",
       lambda q: (q.add_argument("--map", required=True), q.add_argument("table")), cmd_unlink)
   add("shared-add", "add a shared table (creates the shared file)",
       lambda q: (q.add_argument("name"), q.add_argument("--rate")), cmd_shared_add)
   add("shared-set", "change a shared table's rate",
       lambda q: (q.add_argument("table"), q.add_argument("rate")), cmd_shared_set)
   add("entry-add", "add an entry",
       lambda q: (_where(q), q.add_argument("species"), q.add_argument("levels", help="5 or 3-5"),
                  q.add_argument("--weight", type=int, default=1), q.add_argument("--requires"),
                  q.add_argument("--excludes"), q.add_argument("--modifiers", help='e.g. "rain x0, night x2"')),
       cmd_entry_add)
   add("entry-set", "change an entry (lists: - clears)",
       lambda q: (_where(q), q.add_argument("entry", type=int), q.add_argument("--species"),
                  q.add_argument("--levels"), q.add_argument("--weight", type=int), q.add_argument("--requires"),
                  q.add_argument("--excludes"), q.add_argument("--modifiers")), cmd_entry_set)
   add("entry-remove", "remove an entry",
       lambda q: (_where(q), q.add_argument("entry", type=int)), cmd_entry_remove)
   add("entry-move", "move an entry up or down",
       lambda q: (_where(q), q.add_argument("entry", type=int), q.add_argument("direction", choices=("up", "down"))),
       cmd_entry_move)
   add("area", "make a rectangle of painted cells encounter cells in a slot (off: no encounters)",
       lambda q: (q.add_argument("map"), q.add_argument("slot", help="0-15 or off"),
                  *(q.add_argument(a, type=int) for a in ("x", "y", "x2", "y2"))), cmd_area)
