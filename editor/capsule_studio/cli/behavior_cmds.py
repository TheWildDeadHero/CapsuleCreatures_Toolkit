"""!`capsule-studio behaviors WORLD ...`: the world's behaviors (core.behaviors): list them, add one, and set what a
behavior is (solid, the movement modes that enter it, slide / ledge / push / counter, its walls). Changes
are compiled with the engine before the world is saved."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..core import behaviors
from ..core.document import DocumentError
from ..core.world import Project
from .main import CommandError

if TYPE_CHECKING:
   from ..core.document import Document

## The word for "no walls" / "every mode" in a list option.
NONE_WORD = "none"
## Words for true and false.
BOOLS = {"on": True, "yes": True, "true": True, "off": False, "no": False, "false": False}


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("behaviors", help="a world's behaviors (terrain classes): solid, passable, kind, walls")
   p.add_argument("world")
   a = p.add_subparsers(dest="behaviors_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="the behaviors").set_defaults(run=cmd_list)
   q = a.add_parser("add", help="add a behavior")
   q.add_argument("name")
   q.set_defaults(run=cmd_add)
   q = a.add_parser("set", help="change a behavior")
   q.add_argument("name")
   q.add_argument("--kind", help="none, slide, ledge, push or counter")
   q.add_argument("--direction", help="a ledge's or push's direction")
   q.add_argument("--walls", help="sides that are walls, comma-separated, or none")
   q.add_argument("--solid", help="on or off")
   q.add_argument("--passable", help="movement modes that enter it, comma-separated, or every")
   q.set_defaults(run=cmd_set)


def _edit(args: argparse.Namespace, label: str, fn: Callable[[Document], object]) -> None:
   """!Runs a change of the world file, compiles and saves.
   @param args   parsed arguments (world)
   @param label  undo label
   @param fn     callable(world Document)
   @return None
   """
   p = Project.open(args.world)
   try:
      with p.world.edit(label):
         fn(p.world)
   except DocumentError as e:
      raise CommandError(str(e))
   error = p.validate()
   if error:
      raise CommandError(error)
   p.save_all()
   name = getattr(args, "name", None)
   for r, line in zip(behaviors.rows(p.world), behaviors.lines(p.world)):
      if r["name"] == name:
         print(line)


def cmd_list(args: argparse.Namespace) -> None:
   """!behaviors list. @param args  parsed arguments
   @return None
   """
   for line in behaviors.lines(Project.open(args.world).world):
      print(line)


def cmd_add(args: argparse.Namespace) -> None:
   """!behaviors add. @param args  parsed arguments
   @return None
   """
   _edit(args, "Add behavior", lambda w: behaviors.add_behavior(w, args.name))


def cmd_set(args: argparse.Namespace) -> None:
   """!behaviors set. @param args  parsed arguments
   @return None
   """
   if all(v is None for v in (args.kind, args.walls, args.solid, args.passable)):
      raise CommandError("give --kind, --walls, --solid and/or --passable")
   if args.solid is not None and args.solid not in BOOLS:
      raise CommandError(f"--solid needs on or off, got {args.solid!r}")

   def run(w: Document) -> None:
      if args.kind is not None:
         behaviors.set_kind(w, args.name, args.kind, args.direction)
      if args.walls is not None:
         sides = [] if args.walls == NONE_WORD else [s.strip() for s in args.walls.split(",") if s.strip()]
         behaviors.set_walls(w, args.name, sides)
      if args.solid is not None:
         behaviors.set_solid(w, args.name, BOOLS[args.solid])
      if args.passable is not None:
         modes = None if args.passable == "every" else [m.strip() for m in args.passable.split(",") if m.strip()]
         behaviors.set_passable(w, args.name, modes)
   _edit(args, "Behavior", run)
