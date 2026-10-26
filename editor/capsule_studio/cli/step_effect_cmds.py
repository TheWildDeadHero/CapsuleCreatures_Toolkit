"""!`capsule-studio battle FILE step-effect ...` and `battle FILE testsave step ...` (engine F3, D-27 section 4): the
structure manifest's step effects (core.structure.step_effects) and a test save's step counters.

    battle FILE step-effect list                      every effect (every, damage rule, messages, script, users)
    battle FILE step-effect add NAME [--every N] [--at I]
    battle FILE step-effect remove NAME               refused while effect logic names it
    battle FILE step-effect rename OLD NEW            effect logic and the game's scripts reading its counter follow
    battle FILE step-effect move NAME up|down
    battle FILE step-effect set NAME label|every|damage|script VALUE
                                                      (script "": none)
    battle FILE step-effect message NAME MOMENT [KEY] the battle message at hurt / survived / fainted (no KEY: none)
    battle FILE step-effect handlers                  the logic running `on steps`, in the engine's order
    battle FILE testsave step SAVE NAME N             a test save's counter of a step effect (0 to every - 1)

Editing actions save only when the result compiles (battle_cmds.save_if_valid); test save changes save at once.
"""
from __future__ import annotations

import argparse

from ..core import inventory
from ..core.structure import step_effects
from .battle_cmds import open_project, save_if_valid

## `move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## The record keys `set` writes.
SET_KEYS = ["label", "every", "damage", "script"]


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the step-effect actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("step-effect", help="step effects: list | add | remove | rename | move | set | message | handlers")
   a = q.add_subparsers(dest="step_effect_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="every step effect").set_defaults(run=cmd_list)
   r = a.add_parser("add", help="add a step effect")
   r.add_argument("name")
   r.add_argument("--every", type=int, default=step_effects.DEFAULT_EVERY, help="steps between two runs")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_add)
   r = a.add_parser("remove", help="remove a step effect")
   r.add_argument("name")
   r.set_defaults(run=cmd_remove)
   r = a.add_parser("rename", help="rename a step effect; effect logic and scripts follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename)
   r = a.add_parser("move", help="move a step effect up or down")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_move)
   r = a.add_parser("set", help="one of a step effect's keys")
   r.add_argument("name")
   r.add_argument("key", choices=SET_KEYS)
   r.add_argument("value")
   r.set_defaults(run=cmd_set)
   r = a.add_parser("message", help="the battle message queued at a moment")
   r.add_argument("name")
   r.add_argument("moment", choices=step_effects.moments())
   r.add_argument("key", nargs="?", help="a battle message (left out: none)")
   r.set_defaults(run=cmd_message)
   a.add_parser("handlers", help="the logic running on steps").set_defaults(run=cmd_handlers)


def register_testsave(a: argparse._SubParsersAction) -> None:
   """!Adds `testsave step` to the testsave group (cli/inventory_cmds.py).
   @param a  the testsave group's subparsers
   @return None
   """
   r = a.add_parser("step", help="a test save's counter of a step effect")
   r.add_argument("name", help="the test save")
   r.add_argument("effect")
   r.add_argument("steps", type=int)
   r.set_defaults(run=cmd_save_step)


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the step effects.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in step_effects.lines(p.structure) or ["no step effects"]:
      print(line)
   return 0


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds a step effect.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Add step effect"):
      step_effects.add_effect(p.structure, args.name, args.every, args.at)
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes a step effect.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Remove step effect"):
      step_effects.remove_effect(p.structure, args.name)
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames a step effect.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Rename step effect"):
      places = step_effects.rename_effect(p.structure, args.old, args.new, follow=False)
   for place in places:
      print(place if place.startswith(("scripts: ", "structure: ")) else f"logic: {place}")
   # C8: the game's scripts (saved at once) follow only once the renamed battle data compiled and was saved
   status = save_if_valid(p)
   if status == 0:
      for place in step_effects.follow_scripts(p.structure, args.old, args.new):
         print(place)
   return status


def cmd_move(args: argparse.Namespace) -> int:
   """!Moves a step effect.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Move step effect"):
      step_effects.move_effect(p.structure, args.name, MOVES[args.direction])
   return save_if_valid(p)


def cmd_set(args: argparse.Namespace) -> int:
   """!Sets one of a step effect's keys.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   doc, name, value = p.structure, args.name, args.value
   with doc.edit(f"Step effect {args.key}"):
      if args.key == "every":
         step_effects.set_every(doc, name, int(value))
      elif args.key == "label":
         step_effects.set_label(doc, name, value)
      elif args.key == "damage":
         step_effects.set_damage(doc, name, value)
      else:
         step_effects.set_script(doc, name, value)
   return save_if_valid(p)


def cmd_message(args: argparse.Namespace) -> int:
   """!Sets the battle message of a moment.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Step effect message"):
      step_effects.set_message(p.structure, args.name, args.moment, args.key)
   return save_if_valid(p)


def cmd_handlers(args: argparse.Namespace) -> int:
   """!Prints the logic running `on steps`.
   @param args  parsed arguments
   @return 0
   """
   rows = step_effects.step_handlers(open_project(args))
   for u in rows:
      print(f"on {step_effects.HOOK}: {u.kind} {u.name} ({u.file})")
   if not rows:
      print("no logic runs on steps")
   return 0


def cmd_save_step(args: argparse.Namespace) -> int:
   """!Sets a test save's step counter (saved at once).
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   save = inventory.open_testsave(p, args.name)
   with save.edit("Step counter"):
      step_effects.set_counter(save, p.battle, args.effect, args.steps)
   save.save()
   for line in step_effects.counter_lines(save, p.battle):
      print(line)
   return 0
