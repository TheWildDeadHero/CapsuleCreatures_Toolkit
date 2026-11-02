"""!`capsule-studio battle FILE resource ...`: the structure
manifest's resources (core.structure.resources) and the moves' costs and
bases.

    battle FILE resource list                 every resource, then each target's "2/4 battler, 1/2 move gba" budget
    battle FILE resource add NAME battler|move [--label L] [--stat S] [--base F] [--at I]
    battle FILE resource remove NAME          refused while a move's cost or effect logic names it
    battle FILE resource rename OLD NEW       costs, the base field named after it and effect logic follow;
                                              bench scenarios naming it are listed
    battle FILE resource move NAME up|down    the payment order
    battle FILE resource scope NAME battler|move
    battle FILE resource set NAME KEY VALUE   KEY: label stat base max raises persist empty regen (null: the
                                              default; regen: a number or a named formula)
    battle FILE resource cost MOVE [RESOURCE AMOUNT]
                                              a move's cost of each resource; or set one (a number, a named
                                              formula, null: the default); --reset: the move pays the default
    battle FILE resource base MOVE RESOURCE N a move's base of a move resource

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core import battle
from ..core.structure import resources, stats
from .battle_cmds import json_value, open_project, save_if_valid
from .main import CommandError

## `resource move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## Shown for an amount that is the engine's default.
DEFAULT_MARK = " (default)"


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the resource action to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("resource", help="the resources: list | add | remove | rename | move | scope | set | "
                                     "cost | base")
   a = q.add_subparsers(dest="resource_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="every resource and each target's resource budget")
   r.set_defaults(run=cmd_list)
   r = a.add_parser("add", help="add a resource (refilled every battle until it names a persist role)")
   r.add_argument("name")
   r.add_argument("scope", help="battler (one pool per battler) or move (one pool per move slot)")
   r.add_argument("--label", help="in-game text (default: the name)")
   r.add_argument("--stat", help="a battler resource's maximum (default: the first stat no resource takes)")
   r.add_argument("--base", help="a move resource's move field (default: its name; every move gets it)")
   r.add_argument("--at", type=int, help="position in the payment order (default: the end)")
   r.set_defaults(run=cmd_add)
   r = a.add_parser("remove", help="remove a resource no move cost or effect logic names")
   r.add_argument("name")
   r.set_defaults(run=cmd_remove)
   r = a.add_parser("rename", help="rename a resource; costs, its base field and effect logic follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename)
   r = a.add_parser("move", help="move a resource up or down the payment order")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_move)
   r = a.add_parser("scope", help="change a resource's scope (the other scope's keys go)")
   r.add_argument("name")
   r.add_argument("scope")
   r.set_defaults(run=cmd_scope)
   r = a.add_parser("set", help=f"change a resource: KEY one of {', '.join(resources.RESOURCE_KEYS)}; VALUE "
                                "(null: the default)")
   r.add_argument("name")
   r.add_argument("key", choices=resources.RESOURCE_KEYS)
   r.add_argument("value")
   r.set_defaults(run=cmd_set)
   r = a.add_parser("cost", help="a move's cost of each resource; RESOURCE AMOUNT sets one (number, named "
                                 "formula, null: the default)")
   r.add_argument("move")
   r.add_argument("resource", nargs="?")
   r.add_argument("amount", nargs="?")
   r.add_argument("--reset", action="store_true", help="drop the move's own cost: it pays the default")
   r.set_defaults(run=cmd_cost)
   r = a.add_parser("base", help="set a move's base of a move resource")
   r.add_argument("move")
   r.add_argument("resource")
   r.add_argument("value", type=int)
   r.set_defaults(run=cmd_base)


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the resources.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in resources.lines(p.battle, stats.project_targets(p.battle.path)):
      print(line)
   return 0


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds a resource.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Add resource"):
      i = resources.add_resource(p.structure, args.name, args.scope, args.label, args.stat, args.base, args.at)
   print(f"added resource {args.name!r} at {i}")
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes a resource.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Remove resource"):
      resources.remove_resource(p.structure, args.name)
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames a resource and lists the bench scenarios the rename rewrote (core.bench.follow_rename()).
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   bench = resources.bench_users(p.structure, args.old)
   with p.structure.edit("Rename resource"):
      n = resources.rename_resource(p.structure, args.old, args.new)
   print(f"renamed; {n} reference(s) updated")
   for line in bench:
      print(f"bench scenario follows: {line}")
   return save_if_valid(p)


def cmd_move(args: argparse.Namespace) -> int:
   """!Moves a resource.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Move resource"):
      moved = resources.move_resource(p.structure, args.name, MOVES[args.direction])
   if not moved:
      raise CommandError(f"{args.name} is already at the {'top' if args.direction == 'up' else 'bottom'}")
   return save_if_valid(p)


def cmd_scope(args: argparse.Namespace) -> int:
   """!Changes a resource's scope.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Resource scope"):
      changed = resources.set_scope(p.structure, args.name, args.scope)
   if not changed:
      print(f"{args.name} is a {args.scope} resource already")
   return save_if_valid(p)


def cmd_set(args: argparse.Namespace) -> int:
   """!Changes one key of a resource.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value = json_value(args.value)
   if args.key != "regen" and value is not None:
      value = args.value   # texts stay texts (a label "1" is a label)
   with p.structure.edit("Set resource"):
      resources.set_resource(p.structure, args.name, args.key, value)
   return save_if_valid(p)


def cmd_cost(args: argparse.Namespace) -> int:
   """!Prints a move's cost, or sets / resets it.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.reset:
      with p.battle.edit("Reset cost"):
         resources.reset_cost(p.battle, args.move)
      return save_if_valid(p)
   if args.resource is None:
      for row in resources.cost_rows(p.battle, args.move):
         print(f"{row['resource']} ({row['scope']}): {row['amount']}" + (DEFAULT_MARK if row["default"] else ""))
      return 0
   if args.amount is None:
      raise CommandError("resource cost MOVE RESOURCE AMOUNT (a number, a named formula or null)")
   with p.battle.edit("Move cost"):
      resources.set_cost(p.battle, args.move, args.resource, json_value(args.amount))
   return save_if_valid(p)


def cmd_base(args: argparse.Namespace) -> int:
   """!Sets a move's base of a move resource.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   row = next((r for r in resources.base_rows(p.battle, args.move) if r["resource"] == args.resource), None)
   if row is None:
      names = resources.resource_names(p.battle, resources.MOVE)
      raise CommandError(f"{args.resource!r} is not a move resource ({', '.join(names) or 'none'})")
   with p.battle.edit("Move base"):
      battle.set_field(p.battle, "moves", args.move, row["field"], args.value)
   return save_if_valid(p)
