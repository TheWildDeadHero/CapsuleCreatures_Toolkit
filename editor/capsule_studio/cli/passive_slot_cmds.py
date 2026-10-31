"""!`capsule-studio battle FILE passive-slot ...` (D-25 decision 6, engine C1):
the structure manifest's passive slots (core.structure.passive_slots).

    battle FILE passive-slot list                 every slot (rolled, species and members using it), then the
                                                  budget (the engine's most slots, the passive_selector role)
    battle FILE passive-slot add NAME [--fixed] [--at I]
                                                  a slot (--fixed: the generation list never rolls it)
    battle FILE passive-slot remove NAME [--force]
                                                  its place goes from every species' passives; members having it
                                                  fall back to the first slot
    battle FILE passive-slot rename OLD NEW       members naming it follow
    battle FILE passive-slot move NAME up|down [--force]
                                                  species' passives and members' slot numbers follow
                                                  (remove / move: saved creature records keep their slot numbers,
                                                  so --force is needed when the record holds a passive_selector)
    battle FILE passive-slot rolled NAME on|off   whether the generation list may roll it

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core.document import Document
from ..core.structure import passive_slots, stats
from .battle_cmds import open_project, save_if_valid
from .main import CommandError

## `passive-slot move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## `passive-slot rolled` values.
SWITCH = {"on": True, "off": False}


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the passive-slot action to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("passive-slot", help="the passive slots per species: list | add | remove | rename | move | "
                                         "rolled")
   a = q.add_subparsers(dest="passive_slot_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="every passive slot and the budget")
   r.set_defaults(run=cmd_list)
   r = a.add_parser("add", help="add a passive slot")
   r.add_argument("name")
   r.add_argument("--fixed", action="store_true", help="the generation list never rolls it (data or logic gives "
                                                       "it, like a hidden passive)")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_add)
   r = a.add_parser("remove", help="remove a passive slot (species' passives in it go; members fall back)")
   r.add_argument("name")
   r.add_argument("--force", action="store_true", help="even though saved records keep their slot numbers")
   r.set_defaults(run=cmd_remove)
   r = a.add_parser("rename", help="rename a passive slot; members naming it follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename)
   r = a.add_parser("move", help="move a passive slot up or down")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.add_argument("--force", action="store_true", help="even though saved records keep their slot numbers")
   r.set_defaults(run=cmd_move)
   r = a.add_parser("rolled", help="whether the generation list may roll a slot")
   r.add_argument("name")
   r.add_argument("value", choices=list(SWITCH))
   r.set_defaults(run=cmd_rolled)


def _check_saved_records(doc: Document, name: str, delta: int | None, force: bool) -> None:
   """!Refuses to remove or move a slot whose number saved creature records keep (core.structure.passive_slots
   saved_records_warning()) unless --force; with --force, prints the warning.
   @param doc    the structure Document
   @param name   slot name
   @param delta  the move's delta, or None for a removal
   @param force  --force was given
   @return None
   @throws CommandError without --force when saved records would change
   """
   warning = passive_slots.saved_records_warning(doc, name, delta)
   if warning is None:
      return
   if not force:
      raise CommandError(f"{warning} (not changed; --force to change it anyway)")
   print(f"warning: {warning}")


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the passive slots.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in passive_slots.lines(p.structure, stats.project_targets(p.structure.path)):
      print(line)
   return 0


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds a passive slot.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Add passive slot"):
      i = passive_slots.add_slot(p.structure, args.name, not args.fixed, args.at)
   print(f"added passive slot {args.name!r} at {i}")
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes a passive slot and lists what lost it.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   _check_saved_records(p.structure, args.name, None, args.force)
   with p.structure.edit("Remove passive slot"):
      lost = passive_slots.remove_slot(p.structure, args.name)
   for line in lost:
      print(f"lost the slot: {line}")
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames a passive slot.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Rename passive slot"):
      n = passive_slots.rename_slot(p.structure, args.old, args.new)
   print(f"renamed; {n} member(s) updated")
   return save_if_valid(p)


def cmd_move(args: argparse.Namespace) -> int:
   """!Moves a passive slot.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   _check_saved_records(p.structure, args.name, MOVES[args.direction], args.force)
   with p.structure.edit("Move passive slot"):
      moved = passive_slots.move_slot(p.structure, args.name, MOVES[args.direction])
   if not moved:
      raise CommandError(f"{args.name} is already at the {'top' if args.direction == 'up' else 'bottom'}")
   return save_if_valid(p)


def cmd_rolled(args: argparse.Namespace) -> int:
   """!Sets whether a slot is rolled.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Passive slot rolled"):
      passive_slots.set_rolled(p.structure, args.name, SWITCH[args.value])
   return save_if_valid(p)
