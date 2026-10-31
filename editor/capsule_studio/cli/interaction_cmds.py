"""![S6b] `capsule-studio interactions WORLD ...` (engine C13b): the world's cell interaction rules (core.interactions),
everything the World page's Interactions panel does: list them, add, change, remove and reorder a rule, and check
them as the build's map compiler does. Changes are compiled with the engine before anything is saved."""
from __future__ import annotations

import argparse
from typing import Any

from ..core import interactions
from ..core.world import Project
from .main import CommandError

## The word that removes an optional condition.
REMOVE = "-"
## The moves of a rule in the order (`move INDEX up|down`).
MOVES = {"up": -1, "down": 1}
## Switch words.
SWITCH = {"on": True, "off": False}


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("interactions", help="the world's cell interaction rules: facing a cell of a behavior runs a "
                                           "script (engine C13b) (S6b)")
   p.add_argument("world")
   s = p.add_subparsers(dest="interaction_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("list", help="the rules in the order they are tried, and the behaviors they pick from")
   q.set_defaults(run=cmd_list)
   q = s.add_parser("check", help="what the build's map compiler refuses, and rules that never run")
   q.set_defaults(run=cmd_check)
   for word, run, what in (("add", cmd_add, "add a rule (last, or --at INDEX)"),
                           ("set", cmd_set, "change a rule's behavior, script or conditions (- removes one)")):
      q = s.add_parser(word, help=what)
      if word == "add":
         q.add_argument("behavior", help="the faced cell's behavior")
         q.add_argument("script", help="the script it starts")
         q.add_argument("--at", type=int, help="its place in the order")
      else:
         q.add_argument("index", type=int)
         q.add_argument("--behavior")
         q.add_argument("--script")
      q.add_argument("--facing", help="the direction the player faces (- any)")
      q.add_argument("--vehicle", help="the movement mode (- any)")
      q.add_argument("--flag", help="a flag that must be set (- none)")
      q.add_argument("--same-level", dest="same_level", choices=SWITCH, help="the faced level must be the cell's")
      q.add_argument("--after-actions", dest="after_actions", choices=SWITCH,
                     help="tried only after the field actions had nothing")
      q.set_defaults(run=run)
   q = s.add_parser("remove", help="remove a rule")
   q.add_argument("index", type=int)
   q.set_defaults(run=cmd_remove)
   q = s.add_parser("move", help="move a rule up (tried earlier) or down")
   q.add_argument("index", type=int)
   q.add_argument("direction", choices=MOVES)
   q.set_defaults(run=cmd_move)


def _conditions(args: argparse.Namespace) -> dict[str, Any]:
   """!The conditions given on the command line (- removes a named one).
   @param args  parsed arguments
   @return {key: value} (None: removed)
   """
   out: dict[str, Any] = {}
   for k in interactions.NAMED_CONDITIONS:
      v = getattr(args, k, None)
      if v is not None:
         out[k] = None if v == REMOVE else v
   for k in interactions.SWITCHES:
      v = getattr(args, k, None)
      if v is not None:
         out[k] = SWITCH[v]
   return out


def _change(args: argparse.Namespace, label: str, fn: Any) -> Project:
   """!Runs a change of the world's rules and saves (the compiler checks the change itself).
   @param args   parsed arguments (world)
   @param label  undo label
   @param fn     callable(world Document)
   @return the Project
   """
   p = Project.open(args.world)
   try:
      with p.world.edit(label):
         fn(p.world)
   except ValueError as e:
      raise CommandError(str(e)) from None
   p.save_all()
   for problem in interactions.problems(p):
      print(problem)
   return p


def cmd_list(args: argparse.Namespace) -> None:
   """!interactions list. @param args  parsed arguments
   @return None
   """
   p = Project.open(args.world)
   for line in interactions.lines(p.world) or ["no rules"]:
      print(line)
   print("behaviors: " + ", ".join(interactions.behavior_names(p.world)))


def cmd_check(args: argparse.Namespace) -> int:
   """!interactions check. @param args  parsed arguments
   @return 1 when the compiler refuses the rules
   """
   p = Project.open(args.world)
   found = interactions.problems(p)
   for line in found or ["the rules compile"]:
      print(line)
   return 1 if any(f.startswith("error") for f in found) else 0


def cmd_add(args: argparse.Namespace) -> None:
   """!interactions add. @param args  parsed arguments
   @return None
   """
   out = {"i": 0}
   conds = {k: v for k, v in _conditions(args).items() if v is not None}

   def run(world: Any) -> None:
      out["i"] = interactions.add_rule(world, args.behavior, args.script, args.at, **conds)
   p = _change(args, "Add interaction", run)
   print(f"{out['i']}: {interactions.describe(interactions.rules(p.world)[out['i']])}")


def cmd_set(args: argparse.Namespace) -> None:
   """!interactions set. @param args  parsed arguments
   @return None
   """
   fields = _conditions(args)
   for k in interactions.REQUIRED:
      if getattr(args, k) is not None:
         fields[k] = getattr(args, k)
   if not fields:
      raise CommandError("give the fields to change (--behavior, --script, --facing ...)")
   p = _change(args, "Interaction", lambda world: interactions.set_rule(world, args.index, **fields))
   print(f"{args.index}: {interactions.describe(interactions.rules(p.world)[args.index])}")


def cmd_remove(args: argparse.Namespace) -> None:
   """!interactions remove. @param args  parsed arguments
   @return None
   """
   _change(args, "Remove interaction", lambda world: interactions.remove_rule(world, args.index))
   print(f"rule {args.index} removed")


def cmd_move(args: argparse.Namespace) -> None:
   """!interactions move. @param args  parsed arguments
   @return None
   """
   out = {"i": 0}

   def run(world: Any) -> None:
      out["i"] = interactions.move_rule(world, args.index, MOVES[args.direction])
   _change(args, "Move interaction", run)
   print(f"rule {args.index} is now {out['i']}")
