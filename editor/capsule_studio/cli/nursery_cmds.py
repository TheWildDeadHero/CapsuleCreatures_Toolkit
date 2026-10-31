"""!`capsule-studio battle FILE nursery ...` and `battle FILE testsave nursery|egg ...` (engine B2, D-28 sections 2
and 3): the structure manifest's eggs and nursery (core.structure.nursery), the egg refusal flags of the systems
that use records, and a test save's nursery slots, waiting result and boxed eggs.

    battle FILE nursery show                          the eggs, the nursery and every refusal flag
    battle FILE nursery eggs on ROLE COUNTER CYCLES STEP
                                                      write the egg section (egg role, hatch counter role, the species
                                                      field of the hatch cycles, the egg cycle's step effect)
    battle FILE nursery eggs off                      refused while a method delivers eggs
    battle FILE nursery eggs set KEY VALUE            role | counter | cycles_field | step_effect | hatch_script | name
                                                      | sprite | sprite_field ("" leaves an optional one out)
    battle FILE nursery on METHOD CHECK               write the nursery (a method of kind nursery, its check effect)
    battle FILE nursery off                           refused while a method of kind nursery needs it
    battle FILE nursery set KEY VALUE                 slots | method | check | odds_scale | gain | fee
    battle FILE nursery fee LEVELS LEVEL COUNT        what taking a record back costs (the ruleset's nursery_fee)
    battle FILE nursery allow SYSTEM [NAME] on|off    whether a system takes eggs: rules, recruit, lead,
                                                      transformation, field_actions NAME, items NAME,
                                                      combine_methods NAME, step_effects NAME (C9: lead,
                                                      transformation, step_effects)
    battle FILE nursery transfer refuse|hatch         C9: what a build without an egg role does with a transferred
                                                      egg (the structure's transfer_eggs)
    battle FILE testsave nursery SAVE SLOT SPECIES [--level N] [--gained N] | SAVE SLOT --clear
    battle FILE testsave nursery-result SAVE SPECIES [--level N] [--hatch N] | SAVE --clear
    battle FILE testsave egg SAVE BOX_SLOT STEPS | SAVE BOX_SLOT --clear
                                                      a boxed creature as an egg with STEPS left

Editing actions save only when the result compiles (battle_cmds.save_if_valid); test save changes save at once.
"""
from __future__ import annotations

import argparse

from ..core import inventory
from ..core.structure import nursery
from .battle_cmds import open_project, save_if_valid
from .main import CommandError

## `on` / `off` words.
ON_OFF = {"on": True, "off": False}
## The nursery keys holding numbers.
NUMBER_KEYS = (nursery.SLOTS_KEY, nursery.SCALE_KEY)
## The systems `allow` names.
SYSTEMS = [*nursery.SECTION_SYSTEMS, *nursery.LIST_SYSTEMS]


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the nursery actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("nursery", help="eggs and the nursery: show | eggs | on | off | set | fee | allow | transfer")
   a = q.add_subparsers(dest="nursery_command", metavar="ACTION")
   a.required = True
   a.add_parser("show", help="the eggs, the nursery and the refusal flags").set_defaults(run=cmd_show)
   r = a.add_parser("eggs", help="the egg section: on ROLE COUNTER CYCLES STEP | off | set KEY VALUE")
   r.add_argument("action", choices=["on", "off", "set"])
   r.add_argument("values", nargs="*")
   r.set_defaults(run=cmd_eggs)
   r = a.add_parser("on", help="write the nursery")
   r.add_argument("method")
   r.add_argument("check")
   r.set_defaults(run=cmd_on)
   a.add_parser("off", help="remove the nursery").set_defaults(run=cmd_off)
   r = a.add_parser("set", help="one of the nursery's keys")
   r.add_argument("key", choices=list(nursery.NURSERY_KEYS))
   r.add_argument("value")
   r.set_defaults(run=cmd_set)
   r = a.add_parser("fee", help="what taking a record back costs")
   for name in ("levels", "level", "count"):
      r.add_argument(name, type=int)
   r.set_defaults(run=cmd_fee)
   r = a.add_parser("allow", help="whether a system takes eggs")
   r.add_argument("system", choices=SYSTEMS)
   r.add_argument("words", nargs="+", help="[NAME] on|off")
   r.set_defaults(run=cmd_allow)
   r = a.add_parser("transfer", help="what a build without an egg role does with a transferred egg")
   r.add_argument("rule", choices=nursery.transfer_choices())
   r.set_defaults(run=cmd_transfer)


def register_testsave(a: argparse._SubParsersAction) -> None:
   """!Adds `testsave nursery`, `nursery-result` and `egg` to the testsave group (cli/inventory_cmds.py).
   @param a  the testsave group's subparsers
   @return None
   """
   r = a.add_parser("nursery", help="a test save's nursery slot")
   r.add_argument("name", help="the test save")
   r.add_argument("slot", type=int)
   r.add_argument("species", nargs="?")
   r.add_argument("--level", type=int, default=nursery.NEW_LEVEL)
   r.add_argument("--gained", type=int, default=0, help="experience gained there")
   r.add_argument("--clear", action="store_true", help="empty the slot")
   r.set_defaults(run=cmd_save_nursery)
   r = a.add_parser("nursery-result", help="a test save's waiting nursery result")
   r.add_argument("name", help="the test save")
   r.add_argument("species", nargs="?")
   r.add_argument("--level", type=int, default=1)
   r.add_argument("--hatch", type=int, help="an egg with this hatch counter")
   r.add_argument("--clear", action="store_true", help="no result waits")
   r.set_defaults(run=cmd_save_result)
   r = a.add_parser("egg", help="a boxed creature of a test save as an egg")
   r.add_argument("name", help="the test save")
   r.add_argument("slot", type=int, help="its storage slot")
   r.add_argument("steps", type=int, nargs="?", help="its hatch counter")
   r.add_argument("--clear", action="store_true", help="a creature again")
   r.set_defaults(run=cmd_save_egg)


def cmd_show(args: argparse.Namespace) -> int:
   """!Prints the eggs, the nursery and the refusal flags.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)   # held: the Documents name their project weakly
   for line in nursery.lines(p.structure):
      print(line)
   return 0


def cmd_eggs(args: argparse.Namespace) -> int:
   """!Writes, removes or sets the egg section.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   doc, values = p.structure, args.values
   with doc.edit("Eggs"):
      if args.action == "on":
         if len(values) != len(nursery.EGG_REQUIRED):
            raise CommandError("eggs on ROLE COUNTER CYCLES_FIELD STEP_EFFECT")
         nursery.enable_eggs(doc, *values)
      elif args.action == "off":
         nursery.disable_eggs(doc)
      else:
         if len(values) != len(("key", "value")):
            raise CommandError(f"eggs set KEY VALUE (keys: {', '.join(nursery.EGG_KEYS)})")
         nursery.set_egg(doc, values[0], values[1])
   return save_if_valid(p)


def cmd_on(args: argparse.Namespace) -> int:
   """!Writes the nursery.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Nursery"):
      nursery.enable_nursery(p.structure, args.method, args.check)
   return save_if_valid(p)


def cmd_off(args: argparse.Namespace) -> int:
   """!Removes the nursery.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("No nursery"):
      nursery.disable_nursery(p.structure)
   return save_if_valid(p)


def cmd_set(args: argparse.Namespace) -> int:
   """!Sets one of the nursery's keys.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value: object = args.value
   if args.key in NUMBER_KEYS:
      try:
         value = int(args.value)
      except ValueError:
         raise CommandError(f"{args.key}: a whole number (got {args.value!r})") from None
   elif args.key in nursery.NURSERY_FLAGS:
      if args.value not in ON_OFF:
         raise CommandError(f"{args.key}: on or off")
      value = ON_OFF[args.value]
   with p.structure.edit(f"Nursery {args.key}"):
      nursery.set_nursery(p.structure, args.key, value)
   return save_if_valid(p)


def cmd_fee(args: argparse.Namespace) -> int:
   """!Prints what taking a record back costs.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)   # held: the Documents name their project weakly
   fee = nursery.fee_table(p.structure, args.levels, args.level, args.count)
   if fee is None:
      raise CommandError("the battle data does not compile")
   print(f"fee {fee} ({args.levels} levels gained, level {args.level}, {args.count} held)")
   return 0


def cmd_allow(args: argparse.Namespace) -> int:
   """!Sets whether a system takes eggs.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   words = args.words
   if words[-1] not in ON_OFF:
      raise CommandError("allow SYSTEM [NAME] on|off")
   name = " ".join(words[:-1])
   if args.system in nursery.LIST_SYSTEMS and not name:
      raise CommandError(f"allow {args.system} NAME on|off")
   with p.structure.edit("Egg refusal"):
      nursery.set_refusal(p.structure, args.system, name, ON_OFF[words[-1]])
   return save_if_valid(p)


def cmd_transfer(args: argparse.Namespace) -> int:
   """!Sets the structure's transfer rule for eggs (C9).
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Egg transfer rule"):
      nursery.set_transfer_eggs(p.structure, args.rule)
   return save_if_valid(p)


def _print_save(p: object, save: object) -> None:
   """!Prints a test save's nursery and its problems.
   @param p     BattleProject
   @param save  test save Document
   @return None
   """
   for line in nursery.test_lines(save) or ["an empty nursery"]:
      print(line)
   for problem in nursery.check_test(save, p.battle):
      print(f"problem: {problem}")


def cmd_save_nursery(args: argparse.Namespace) -> int:
   """!Sets or empties a test save's nursery slot (saved at once).
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   save = inventory.open_testsave(p, args.name)
   with save.edit("Nursery slot"):
      if args.clear:
         nursery.take_held(save, args.slot)
      elif args.species is None:
         raise CommandError("testsave nursery SAVE SLOT SPECIES (or --clear)")
      else:
         nursery.put_held(save, p.battle, args.slot, args.species, args.level, args.gained)
   save.save()
   _print_save(p, save)
   return 0


def cmd_save_result(args: argparse.Namespace) -> int:
   """!Sets or clears a test save's waiting result (saved at once).
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   save = inventory.open_testsave(p, args.name)
   if not args.clear and args.species is None:
      raise CommandError("testsave nursery-result SAVE SPECIES (or --clear)")
   with save.edit("Nursery result"):
      nursery.set_result(save, p.battle, None if args.clear else args.species, args.hatch, args.level)
   save.save()
   _print_save(p, save)
   return 0


def cmd_save_egg(args: argparse.Namespace) -> int:
   """!Makes a boxed creature an egg, or a creature again (saved at once).
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   save = inventory.open_testsave(p, args.name)
   if not args.clear and args.steps is None:
      raise CommandError("testsave egg SAVE BOX_SLOT STEPS (or --clear)")
   with save.edit("Boxed egg"):
      nursery.set_boxed_hatch(save, p.battle, args.slot, None if args.clear else args.steps)
   save.save()
   for line in inventory.lines(save, p.battle):
      print(line)
   return 0
