"""!`capsule-studio overrides ...`: everything the Override sets panel and map tool do, from the command line (D-10
parity; S3, D-30 section 2). Changes are compiled with the engine before anything is saved.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from capsule_studio.core import engine, override_sets
from capsule_studio.core.document import DocumentError
from capsule_studio.core.world import Project

if TYPE_CHECKING:
   import argparse

   from capsule_studio.plugins.registry import ExtensionContext

## A command's body: callable(parsed arguments) -> exit status, or None for 0.
CommandRun = Callable[["argparse.Namespace"], int | None]
## A command's argument setup: callable(parser), its result unused.
CommandSetup = Callable[["argparse.ArgumentParser"], object]
## The word for "nothing" (a cell's layer shows no metatile).
NOTHING = "-"
## Separator of a cell's coordinates ("28,23").
CELL_SEPARATOR = ","


class Usage(Exception):
   """!Bad arguments; the message says what to give."""
   pass


def _wrap(fn: CommandRun) -> Callable[[argparse.Namespace], int]:
   """!Turns Usage, DocumentError and ValueError into messages and exit status 1.
   @param fn  callable(args)
   @return callable(args) -> status
   """
   def run(args: argparse.Namespace) -> int:
      try:
         return fn(args) or 0
      except (Usage, DocumentError, ValueError) as e:
         print(f"capsule-studio overrides: error: {e}")
         return 1
   return run


def _open(args: argparse.Namespace) -> Project:
   """!The world, with the map checked.
   @param args  parsed arguments (world, map)
   @return Project
   """
   p = Project.open(args.world)
   name = getattr(args, "map", None)
   if name is not None and name not in p.map_names():
      raise Usage(f"no map {name!r}")
   return p


def _save(p: Project, map_name: str) -> None:
   """!Checks the map (and its sets' names with the scripts), then saves every changed document.
   @param p         Project
   @param map_name  the map changed
   @return None
   """
   error = override_sets.check(p, map_name)
   if error:
      raise DocumentError(error)
   problems = override_sets.persist_problems(p, map_name)
   if problems:
      raise DocumentError(problems[0])
   p.save_all()


def _cells(texts: list[str]) -> list[list[int]]:
   """!Cells from X,Y words.
   @param texts  the words
   @return [[x, y]]
   """
   out = []
   for t in texts:
      try:
         x, y = (int(v) for v in t.split(CELL_SEPARATOR))
      except ValueError:
         raise Usage(f"a cell is X,Y, got {t!r}") from None
      out.append([x, y])
   return out


def cmd_list(args: argparse.Namespace) -> None:
   """!overrides list. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   names = [args.map] if args.map else [m for m in p.map_names() if p.map_head(m).get(override_sets.SETS_KEY)]
   lines = [line for m in names for line in override_sets.lines(p, m)]
   print("\n".join(lines) if lines else "no override sets")


def cmd_add(args: argparse.Namespace) -> None:
   """!overrides add. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   cell = _cells([args.cell])[0]
   doc = p.map(args.map)
   with doc.edit("Add override set"):
      override_sets.add_set(p, args.map, args.name, cell, args.layer, None if args.metatile == NOTHING else
                            args.metatile)
   _save(p, args.map)
   print("\n".join(override_sets.lines(p, args.map)))


def cmd_rename(args: argparse.Namespace) -> None:
   """!overrides rename. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   changed = override_sets.rename_set(p, args.map, args.old, args.new, follow=not args.keep_scripts)
   _save(p, args.map)
   print(f"override set {args.old} is {args.new}" + (f"; rewrote {', '.join(changed)}" if changed else ""))


def cmd_remove(args: argparse.Namespace) -> None:
   """!overrides remove. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   with p.map(args.map).edit("Remove override set"):
      override_sets.remove_set(p, args.map, args.name, args.force)
   _save(p, args.map)
   print(f"removed override set {args.name}")


def cmd_persist(args: argparse.Namespace) -> None:
   """!overrides persist. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = p.map(args.map)
   with doc.edit("Override set persistence"):
      override_sets.set_persist(doc, args.name, args.kind, args.which, args.value)
   _save(p, args.map)
   print("\n".join(override_sets.lines(p, args.map)))


def cmd_paint(args: argparse.Namespace) -> None:
   """!overrides paint. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = p.map(args.map)
   cells = _cells(args.cells)
   entries = None
   if args.entries:
      try:
         entries = [int(v, 0) for v in args.entries.split(CELL_SEPARATOR)]
      except ValueError:
         raise Usage(f"--entries are four map entries E0,E1,E2,E3, got {args.entries!r}") from None
   with doc.edit("Paint override cells"):
      n = override_sets.paint(doc, args.name, cells, args.layer, None if args.metatile == NOTHING else args.metatile,
                              entries)
   _save(p, args.map)
   print(f"override set {args.name}: {n} cell(s) painted on layer {args.layer}")


def cmd_erase(args: argparse.Namespace) -> None:
   """!overrides erase. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   doc = p.map(args.map)
   with doc.edit("Erase override cells"):
      n = override_sets.erase(doc, args.name, _cells(args.cells), args.layer)
   _save(p, args.map)
   print(f"override set {args.name}: {n} cell(s) taken out")


def cmd_render(args: argparse.Namespace) -> None:
   """!overrides render. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   img = override_sets.render(p, args.map, args.name, not args.cleared, args.margin)
   if img is None:
      raise Usage(p.compiled_map(args.map)[1] or f"override set {args.name} has no cells")
   engine.bitmap().write_png(args.out, *img)
   print(f"wrote {args.out} ({img[0]}x{img[1]}, {'cleared' if args.cleared else 'applied'})")


def cmd_uses(args: argparse.Namespace) -> None:
   """!overrides uses. @param args  parsed arguments
   @return None
   """
   p = _open(args)
   uses = override_sets.script_uses(p, args.name)
   for f, line in uses:
      print(f"{f}:{line}")
   if not uses:
      print(f"no script names override set {args.name}")


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

   def one(q: argparse.ArgumentParser) -> None:
      q.add_argument("map")
      q.add_argument("name", help="the override set")

   def painted(q: argparse.ArgumentParser) -> None:
      one(q)
      q.add_argument("layer", type=int)
      q.add_argument("cells", nargs="+", help="X,Y ...")

   add("list", "every map's override sets (or one map's) with their cells",
       lambda q: q.add_argument("--map", help="only this map"), cmd_list)
   add("add", "add a set with its first cell",
       lambda q: (one(q), q.add_argument("cell", help="X,Y"), q.add_argument("--layer", type=int, default=0),
                  q.add_argument("--metatile", default=NOTHING, help="tileset/name it shows (- nothing)")), cmd_add)
   add("rename", "rename a set; `override apply|clear OLD` in the scripts follows (saved at once)",
       lambda q: (q.add_argument("map"), q.add_argument("old"), q.add_argument("new"),
                  q.add_argument("--keep-scripts", action="store_true", help="leave the scripts as they are")),
       cmd_rename)
   add("remove", "remove a set (refused while scripts name it, unless --force)",
       lambda q: (one(q), q.add_argument("--force", action="store_true")), cmd_remove)
   add("persist", "how a set lasts: map (until the map is left), flag NAME, or var NAME --value N",
       lambda q: (one(q), q.add_argument("kind", choices=("map", "flag", "var")),
                  q.add_argument("which", nargs="?", help="the flag or variable"),
                  q.add_argument("--value", type=int, help="the variable's value (not 0)")), cmd_persist)
   add("paint", "cells of a set on a layer show a metatile (- nothing) or four raw entries",
       lambda q: (painted(q), q.add_argument("--metatile", default=NOTHING, help="tileset/name (- nothing)"),
                  q.add_argument("--entries", help="E0,E1,E2,E3 raw map entries instead")), cmd_paint)
   add("erase", "take cells out of a set on a layer", painted, cmd_erase)
   add("render", "write the set's cells and their surroundings, applied (or --cleared), to a PNG",
       lambda q: (one(q), q.add_argument("out"), q.add_argument("--cleared", action="store_true"),
                  q.add_argument("--margin", type=int, default=1, help="cells around the set")), cmd_render)
   add("uses", "the script lines naming a set", one, cmd_uses)
