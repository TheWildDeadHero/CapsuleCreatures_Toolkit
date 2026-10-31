"""!`capsule-studio battle FILE delayed-hit ...` (engine G1, D-26 section 1): the structure manifest's delayed hits
(core.structure.delayed_hits).

    battle FILE delayed-hit list                  every record (what it takes on use, flags, accuracy, users)
    battle FILE delayed-hit add NAME [--at I]
    battle FILE delayed-hit remove NAME           refused while effect logic names it
    battle FILE delayed-hit rename OLD NEW        `delay_hit ... NAME` in the effect logic follows
    battle FILE delayed-hit move NAME up|down
    battle FILE delayed-hit at-use NAME [VALUE ...]
                                                  what the landing takes from the time of use (none given: nothing)
    battle FILE delayed-hit flag NAME FLAG on|off typed, crit (the engine's flags)
    battle FILE delayed-hit accuracy NAME N       the landing's accuracy percent (0: no check)
    battle FILE delayed-hit miss NAME MESSAGE     the engine message a miss says

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core.structure import delayed_hits
from .battle_cmds import open_project, save_if_valid

## `move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## `flag` values.
SWITCH = {"on": True, "off": False}


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the delayed-hit action to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("delayed-hit", help="delayed hits (delay_hit): list | add | remove | rename | move | at-use | "
                                        "flag | accuracy | miss")
   a = q.add_subparsers(dest="delayed_hit_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="every delayed hit").set_defaults(run=cmd_list)
   r = a.add_parser("add", help="add a delayed hit")
   r.add_argument("name")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_add)
   r = a.add_parser("remove", help="remove a delayed hit")
   r.add_argument("name")
   r.set_defaults(run=cmd_remove)
   r = a.add_parser("rename", help="rename a delayed hit; effect logic follows")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename)
   r = a.add_parser("move", help="move a delayed hit up or down")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_move)
   r = a.add_parser("at-use", help="what the landing takes from the time of use")
   r.add_argument("name")
   r.add_argument("values", nargs="*", metavar="VALUE", help="the engine's names (stats, stages, ...)")
   r.set_defaults(run=cmd_at_use)
   r = a.add_parser("flag", help="a delayed hit's flag")
   r.add_argument("name")
   r.add_argument("flag", help="the engine's flag names (typed, crit)")
   r.add_argument("value", choices=list(SWITCH))
   r.set_defaults(run=cmd_flag)
   r = a.add_parser("accuracy", help="the landing's accuracy percent (0: no check)")
   r.add_argument("name")
   r.add_argument("accuracy", type=int)
   r.set_defaults(run=cmd_accuracy)
   r = a.add_parser("miss", help="the engine message a missed landing says")
   r.add_argument("name")
   r.add_argument("message")
   r.set_defaults(run=cmd_miss)


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the delayed hits.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in delayed_hits.lines(p.structure) or ["no delayed hits"]:
      print(line)
   return 0


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds a delayed hit.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Add delayed hit"):
      delayed_hits.add_hit(p.structure, args.name, args.at)
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes a delayed hit.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Remove delayed hit"):
      delayed_hits.remove_hit(p.structure, args.name)
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames a delayed hit.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Rename delayed hit"):
      places = delayed_hits.rename_hit(p.structure, args.old, args.new)
   for place in places:
      print(f"logic: {place}")
   return save_if_valid(p)


def cmd_move(args: argparse.Namespace) -> int:
   """!Moves a delayed hit.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Move delayed hit"):
      delayed_hits.move_hit(p.structure, args.name, MOVES[args.direction])
   return save_if_valid(p)


def cmd_at_use(args: argparse.Namespace) -> int:
   """!Sets what a delayed hit takes from the time of use.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Delayed hit at use"):
      delayed_hits.set_at_use(p.structure, args.name, args.values)
   return save_if_valid(p)


def cmd_flag(args: argparse.Namespace) -> int:
   """!Sets a delayed hit's flag.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Delayed hit flag"):
      delayed_hits.set_flag(p.structure, args.name, args.flag, SWITCH[args.value])
   return save_if_valid(p)


def cmd_accuracy(args: argparse.Namespace) -> int:
   """!Sets a delayed hit's landing accuracy.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Delayed hit accuracy"):
      delayed_hits.set_accuracy(p.structure, args.name, args.accuracy)
   return save_if_valid(p)


def cmd_miss(args: argparse.Namespace) -> int:
   """!Sets a delayed hit's miss message.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Delayed hit miss message"):
      delayed_hits.set_miss_message(p.structure, args.name, args.message)
   return save_if_valid(p)
