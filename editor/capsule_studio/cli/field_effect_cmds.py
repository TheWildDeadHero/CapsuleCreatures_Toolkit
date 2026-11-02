"""!`capsule-studio battle FILE field-effect ...` and `battle FILE encounter ...` (engine F1, field effect sections 1
and 2): the structure manifest's timed field effects (core.structure.field_effects) and encounter rules (the lead rule,
core.structure.encounter_rules).

    battle FILE field-effect list                     every effect (unit, stack rule, persists, expiry, users)
    battle FILE field-effect add NAME [--unit U] [--at I]
    battle FILE field-effect remove NAME              refused while effect logic names it
    battle FILE field-effect rename OLD NEW           effect logic and the game's scripts naming it follow
    battle FILE field-effect move NAME up|down
    battle FILE field-effect set NAME label|unit|stack|expiry|persists VALUE
                                                      (expiry "": none; persists on|off)
    battle FILE field-effect item ITEM EFFECT N       the item's use_field logic starts EFFECT for N steps / minutes
    battle FILE encounter show                        who leads, the encounter pipelines, the logic running the hooks
    battle FILE encounter lead EXPR                   the first member for which EXPR holds leads
    battle FILE encounter lead-clear                  the first member that can battle leads
    battle FILE encounter hook-lead EXPR              the field effects: the first member for which EXPR holds runs the
    hooks of its
                                                      passive and held item (the lead stays the global rules' holder)
    battle FILE encounter hook-lead-clear             the field effects: the lead runs them
    battle FILE encounter add-global NAME             a global rule with an empty `on encounter` handler

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core.document import DocumentError
from ..core.structure import encounter_rules, field_effects
from .battle_cmds import open_project, save_if_valid

## `move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## `persists` values.
SWITCH = {"on": True, "off": False}
## The record keys `set` writes.
SET_KEYS = ["label", "unit", "stack", "expiry", "persists"]


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the field-effect and encounter actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("field-effect", help="timed field effects: list | add | remove | rename | move | set | item")
   a = q.add_subparsers(dest="field_effect_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="every field effect").set_defaults(run=cmd_list)
   r = a.add_parser("add", help="add a field effect")
   r.add_argument("name")
   r.add_argument("--unit", choices=field_effects.units(), help="steps or minutes (default: the engine's first)")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_add)
   r = a.add_parser("remove", help="remove a field effect")
   r.add_argument("name")
   r.set_defaults(run=cmd_remove)
   r = a.add_parser("rename", help="rename a field effect; effect logic follows")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename)
   r = a.add_parser("move", help="move a field effect up or down")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_move)
   r = a.add_parser("set", help="one of a field effect's keys")
   r.add_argument("name")
   r.add_argument("key", choices=SET_KEYS)
   r.add_argument("value")
   r.set_defaults(run=cmd_set)
   r = a.add_parser("item", help="an item's use_field logic starts a field effect")
   r.add_argument("item")
   r.add_argument("effect")
   r.add_argument("amount", type=int)
   r.set_defaults(run=cmd_item)
   q = s.add_parser("encounter", help="encounter rules: show | lead | lead-clear | hook-lead | hook-lead-clear | "
                                      "add-global")
   a = q.add_subparsers(dest="encounter_command", metavar="ACTION")
   a.required = True
   a.add_parser("show", help="who leads, the pipelines, the logic running the hooks").set_defaults(run=cmd_show)
   r = a.add_parser("lead", help="the first member for which EXPR holds leads")
   r.add_argument("when", metavar="EXPR")
   r.set_defaults(run=cmd_lead)
   a.add_parser("lead-clear", help="the first member that can battle leads").set_defaults(run=cmd_lead_clear)
   r = a.add_parser("hook-lead", help="the first member for which EXPR holds runs the hooks of its passive and "
                                      "held item")
   r.add_argument("when", metavar="EXPR")
   r.set_defaults(run=cmd_hook_lead)
   a.add_parser("hook-lead-clear", help="the lead runs the hooks of its passive and held item").set_defaults(
      run=cmd_hook_lead_clear)
   r = a.add_parser("add-global", help="a global rule with an empty `on encounter` handler")
   r.add_argument("name")
   r.set_defaults(run=cmd_add_global)


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the field effects.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in field_effects.lines(p.structure) or ["no field effects"]:
      print(line)
   return 0


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds a field effect.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Add field effect"):
      field_effects.add_effect(p.structure, args.name, args.unit, args.at)
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes a field effect.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Remove field effect"):
      field_effects.remove_effect(p.structure, args.name)
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames a field effect.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Rename field effect"):
      places = field_effects.rename_effect(p.structure, args.old, args.new, follow=False)
   for place in places:
      print(place if place.startswith("scripts: ") else f"logic: {place}")
   # The game's scripts (saved at once) follow only once the renamed battle data compiled and was saved
   status = save_if_valid(p)
   if status == 0:
      for place in field_effects.follow_scripts(p.structure, args.old, args.new):
         print(place)
   return status


def cmd_move(args: argparse.Namespace) -> int:
   """!Moves a field effect.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Move field effect"):
      field_effects.move_effect(p.structure, args.name, MOVES[args.direction])
   return save_if_valid(p)


def cmd_set(args: argparse.Namespace) -> int:
   """!Sets one of a field effect's keys.
   @param args  parsed arguments
   @return 0 or 1
   @throws DocumentError for a persists value other than on / off
   """
   p = open_project(args)
   doc, name, value = p.structure, args.name, args.value
   setters = {"label": lambda: field_effects.set_label(doc, name, value),
              "unit": lambda: field_effects.set_unit(doc, name, value),
              "stack": lambda: field_effects.set_stack(doc, name, value),
              "expiry": lambda: field_effects.set_expiry(doc, name, value)}
   with doc.edit(f"Field effect {args.key}"):
      if args.key == "persists":
         if value not in SWITCH:
            raise DocumentError(f"persists: on or off (got {value!r})")
         field_effects.set_persists(doc, name, SWITCH[value])
      else:
         setters[args.key]()
   return save_if_valid(p)


def cmd_item(args: argparse.Namespace) -> int:
   """!Makes an item's use_field logic start a field effect.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Item field effect"):
      field_effects.set_item_field_effect(p, args.item, args.effect, args.amount)
   return save_if_valid(p)


def cmd_show(args: argparse.Namespace) -> int:
   """!Prints the encounter rules.
   @param args  parsed arguments
   @return 0
   """
   for line in encounter_rules.lines(open_project(args)):
      print(line)
   return 0


def cmd_lead(args: argparse.Namespace) -> int:
   """!States the lead rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Lead rule"):
      encounter_rules.set_lead(p.structure, args.when)
   return save_if_valid(p)


def cmd_lead_clear(args: argparse.Namespace) -> int:
   """!Drops the lead rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Clear lead rule"):
      encounter_rules.clear_lead(p.structure)
   return save_if_valid(p)


def cmd_hook_lead(args: argparse.Namespace) -> int:
   """!States the hooks' member's rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Hooks' member rule"):
      encounter_rules.set_hook_lead(p.structure, args.when)
   return save_if_valid(p)


def cmd_hook_lead_clear(args: argparse.Namespace) -> int:
   """!Drops the hooks' member's rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Clear hooks' member rule"):
      encounter_rules.clear_hook_lead(p.structure)
   return save_if_valid(p)


def cmd_add_global(args: argparse.Namespace) -> int:
   """!Adds a global rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add global rule"):
      rel = encounter_rules.add_global_rule(p, args.name)
   print(f"logic: {rel}")
   return save_if_valid(p)
