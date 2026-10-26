"""!`capsule-studio levels|modes WORLD ...`: the world's elevation levels and
movement modes (engine E8; core.field_rules), everything the World page's
Levels and Movement modes panels do.

    levels WORLD list
    levels WORLD set LEVEL meets|on_arrive|priority VALUE     VALUE JSON (all / same / [1, "bridge"], take, 2)
    levels WORLD rename LEVEL NAME                           other levels' meets lists follow
    levels WORLD reset                                       the engine's default rule
    modes WORLD list
    modes WORLD add NAME | remove NAME | rename OLD NEW [--force] | move NAME up|down
    modes WORLD set NAME walk|run|can_run|first_animation|passable VALUE      (null: the default)

A rename or removal the game's scripts would notice (`vehicle NAME;`) needs
--force. Changes are compiled with the engine before the world is saved.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from ..core import field_rules
from ..core.document import Document, DocumentError
from ..core.world import Project
from .main import CommandError

## `move` directions and their deltas.
MOVES = {"up": -1, "down": 1}


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the `levels` and `modes` groups.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("levels", help="a world's 16 elevation levels")
   p.add_argument("world")
   a = p.add_subparsers(dest="levels_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="the levels and whom they meet").set_defaults(run=cmd_levels_list)
   q = a.add_parser("set", help="meets / on_arrive / priority of a level (VALUE JSON)")
   q.add_argument("level", type=int)
   q.add_argument("key", choices=list(field_rules.LEVEL_FIELDS))
   q.add_argument("value")
   q.set_defaults(run=cmd_levels_set)
   q = a.add_parser("rename", help="rename a level (meets lists follow)")
   q.add_argument("level", type=int)
   q.add_argument("name")
   q.set_defaults(run=cmd_levels_rename)
   a.add_parser("reset", help="the engine's default rule").set_defaults(run=cmd_levels_reset)

   p = sub.add_parser("modes", help="a world's movement modes (vehicle classes; class 0 is on foot)")
   p.add_argument("world")
   a = p.add_subparsers(dest="modes_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="the modes with what they enter").set_defaults(run=cmd_modes_list)
   q = a.add_parser("add", help="add a mode (on-foot defaults)")
   q.add_argument("name")
   q.set_defaults(run=cmd_modes_add)
   q = a.add_parser("remove", help="remove a mode (behaviors and encounter methods drop it)")
   q.add_argument("name")
   q.add_argument("--force", action="store_true", help="even when scripts name it")
   q.set_defaults(run=cmd_modes_remove)
   q = a.add_parser("rename", help="rename a mode (behaviors and encounter methods follow)")
   q.add_argument("old")
   q.add_argument("new")
   q.add_argument("--force", action="store_true", help="even when scripts name it")
   q.set_defaults(run=cmd_modes_rename)
   q = a.add_parser("move", help="move a mode (its class number; class 0 stays)")
   q.add_argument("name")
   q.add_argument("direction", choices=list(MOVES))
   q.set_defaults(run=cmd_modes_move)
   q = a.add_parser("set", help="one field of a mode (VALUE JSON; null: the default)")
   q.add_argument("name")
   q.add_argument("key", choices=list(field_rules.MODE_FIELDS))
   q.add_argument("value")
   q.set_defaults(run=cmd_modes_set)


def _value(text: str) -> Any:
   """!A command-line value as JSON (bare words are strings).
   @param text  argument
   @return value
   """
   try:
      return json.loads(text)
   except json.JSONDecodeError:
      return text


def _edit(args: argparse.Namespace, label: str, fn: Callable[[Document], object]) -> int:
   """!Runs a change on the world file and saves it when the world compiles.
   @param args   parsed arguments
   @param label  undo label
   @param fn     callable(world Document)
   @return 0, or 1 when the world does not compile
   """
   p = Project.open(args.world)
   try:
      with p.world.edit(label):
         result = fn(p.world)
   except DocumentError as e:
      raise CommandError(str(e))
   if isinstance(result, list) and result:
      print("followed: " + ", ".join(str(r) for r in result))
   error = p.validate()
   if error:
      print(f"not saved: {error}")
      return 1
   p.save_all()
   return 0


def _check_users(args: argparse.Namespace, name: str) -> None:
   """!Refuses a rename / removal the game's scripts would notice, unless --force.
   @param args  parsed arguments (world, force)
   @param name  the mode
   @return None
   """
   users = field_rules.mode_users(Project.open(args.world).world, name)
   if users and not args.force:
      raise CommandError(f"the game's scripts name {name!r} ({'; '.join(users)}); give --force to go ahead")


def cmd_levels_list(args: argparse.Namespace) -> int:
   """!Prints the levels and modes.
   @param args  parsed arguments
   @return 0
   """
   for line in field_rules.lines(Project.open(args.world).world):
      print(line)
   return 0


def cmd_levels_set(args: argparse.Namespace) -> int:
   """!Sets a level field.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Level", lambda w: field_rules.set_level(w, args.level, args.key, _value(args.value)))


def cmd_levels_rename(args: argparse.Namespace) -> int:
   """!Renames a level.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Rename level", lambda w: field_rules.rename_level(w, args.level, args.name))


def cmd_levels_reset(args: argparse.Namespace) -> int:
   """!Gives the levels back to the engine.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Default levels", field_rules.reset_levels)


def cmd_modes_list(args: argparse.Namespace) -> int:
   """!Prints the levels and modes (one report).
   @param args  parsed arguments
   @return 0
   """
   return cmd_levels_list(args)


def cmd_modes_add(args: argparse.Namespace) -> int:
   """!Adds a mode.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Add mode", lambda w: print(f"class {field_rules.add_mode(w, args.name)}"))


def cmd_modes_remove(args: argparse.Namespace) -> int:
   """!Removes a mode.
   @param args  parsed arguments
   @return 0 or 1
   """
   _check_users(args, args.name)
   return _edit(args, "Remove mode", lambda w: field_rules.remove_mode(w, args.name))


def cmd_modes_rename(args: argparse.Namespace) -> int:
   """!Renames a mode.
   @param args  parsed arguments
   @return 0 or 1
   """
   _check_users(args, args.old)
   return _edit(args, "Rename mode", lambda w: field_rules.rename_mode(w, args.old, args.new))


def cmd_modes_move(args: argparse.Namespace) -> int:
   """!Moves a mode.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Move mode", lambda w: field_rules.move_mode(w, args.name, MOVES[args.direction]))


def cmd_modes_set(args: argparse.Namespace) -> int:
   """!Sets a mode field.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Mode", lambda w: field_rules.set_mode(w, args.name, args.key, _value(args.value)))
