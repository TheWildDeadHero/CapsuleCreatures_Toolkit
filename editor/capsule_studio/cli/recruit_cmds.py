"""!`capsule-studio battle FILE recruit|storage|testsave box ...` (D-26 section 3, engine G3): the structure's recruit
rules and the ruleset's recruit_odds (core.structure.recruit), the storage boxes (core.structure.storage) and the
boxed creatures of a test save.

    battle FILE recruit show                     the rules (defaults filled in) and the items that recruit
    battle FILE recruit enable [--checks N]      a recruit section (needs the ruleset's recruit_odds)
    battle FILE recruit disable
    battle FILE recruit pipeline                 write the neutral recruit_odds into the ruleset
    battle FILE recruit set checks|rate|owned|item_role VALUE
                                                 rate / item_role: a name, or none
    battle FILE recruit status-bonus STATUS N|default
                                                 STATUS: a status or none
    battle FILE recruit keep [hp] [status] [resources]
    battle FILE recruit refusal-consumes [refused] [blocked] [no_room]   (C6: refusals that use the item up)
    battle FILE recruit message MOMENT KEY|none
    battle FILE recruit break-free [KEY ...]
    battle FILE recruit odds [INPUT=V ...] [--species S]
                                                 recruit_odds for these inputs (a species gives its rate)
    battle FILE recruit item ITEM BONUS          the item recruits: `recruit holder BONUS;` in its use_battle
    battle FILE storage show [--platform P]      the boxes, the budget and the save image
    battle FILE storage enable [--boxes N] [--size N]
    battle FILE storage disable
    battle FILE storage set box_count|box_size N
    battle FILE storage names PATTERN | --list NAME ...
    battle FILE storage rename BOX NAME          BOX from 0
    battle FILE testsave box NAME put SPECIES [LEVEL] [--slot K]
    battle FILE testsave box NAME remove SLOT
    battle FILE testsave box NAME current BOX

Choice lists are the engine's (battle_compiler RECRUIT_MESSAGE_MOMENTS, RECRUIT_KEEPS, RECRUIT_OWNED). Manifest
actions save only when the result compiles (battle_cmds.save_if_valid); a test save is its own file.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable

from ..core import inventory
from ..core.document import Document
from ..core.structure import recruit, stats, storage
from .battle_cmds import open_project, save_if_valid
from .main import CommandError

## The word for "nothing" (a rate, an item role, a moment's message).
NONE_WORD = "none"
## The word `status-bonus` takes to put a bonus back to its default.
DEFAULT_WORD = "default"
## The separator of an INPUT=V pair.
PAIR_SEPARATOR = "="


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the recruit and storage actions to the battle group, and `box` to the testsave action.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("recruit", help="recruitment: show | enable | disable | pipeline | set | status-bonus | keep | "
                                    "message | break-free | odds | item")
   a = q.add_subparsers(dest="recruit_command", metavar="ACTION")
   a.required = True
   a.add_parser("show", help="the recruit rules").set_defaults(run=cmd_show)
   r = a.add_parser("enable", help="give the structure a recruit section")
   r.add_argument("--checks", type=int, default=recruit.NEW_CHECKS)
   r.set_defaults(run=cmd_enable)
   a.add_parser("disable", help="take the recruit section out").set_defaults(run=cmd_disable)
   a.add_parser("pipeline", help="write the neutral recruit_odds into the ruleset").set_defaults(run=cmd_pipeline)
   r = a.add_parser("set", help="checks, rate, owned or item_role")
   r.add_argument("field", choices=list(recruit.FIELDS))
   r.add_argument("value")
   r.set_defaults(run=cmd_set)
   r = a.add_parser("status-bonus", help="a status's bonus (none: the bonus without a status)")
   r.add_argument("status")
   r.add_argument("value")
   r.set_defaults(run=cmd_status_bonus)
   r = a.add_parser("keep", help="the battle changes a recruited record keeps")
   r.add_argument("kept", nargs="*")
   r.set_defaults(run=cmd_keep)
   r = a.add_parser("refusal-consumes", help="the refusals that still use the item up (none: every one keeps it)")
   r.add_argument("refused", nargs="*")
   r.set_defaults(run=cmd_refusal_consumes)
   r = a.add_parser("message", help="the message a moment says")
   r.add_argument("moment")
   r.add_argument("key")
   r.set_defaults(run=cmd_message)
   r = a.add_parser("break-free", help="the messages of a failed recruit by the checks it passed")
   r.add_argument("keys", nargs="*")
   r.set_defaults(run=cmd_break_free)
   r = a.add_parser("odds", help="recruit_odds for some inputs")
   r.add_argument("inputs", nargs="*", metavar="INPUT=V")
   r.add_argument("--species", help="read the species' recruit rate")
   r.set_defaults(run=cmd_odds)
   r = a.add_parser("item", help="make an item recruit (`recruit holder BONUS;`)")
   r.add_argument("item")
   r.add_argument("bonus", type=int)
   r.set_defaults(run=cmd_item)

   q = s.add_parser("storage", help="the storage boxes: show | enable | disable | set | names | rename")
   a = q.add_subparsers(dest="storage_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("show", help="the boxes, the budget and the save image")
   r.add_argument("--platform")
   r.set_defaults(run=cmd_storage_show)
   r = a.add_parser("enable", help="give the structure storage boxes")
   r.add_argument("--boxes", type=int, default=storage.NEW_COUNT)
   r.add_argument("--size", type=int, default=storage.NEW_SIZE)
   r.set_defaults(run=cmd_storage_enable)
   a.add_parser("disable", help="take the storage boxes out").set_defaults(run=cmd_storage_disable)
   r = a.add_parser("set", help="box_count or box_size")
   r.add_argument("field", choices=list(storage.FIELDS))
   r.add_argument("value", type=int)
   r.set_defaults(run=cmd_storage_set)
   r = a.add_parser("names", help="the box names: a pattern with {n}, or --list of every box's")
   r.add_argument("pattern", nargs="?")
   r.add_argument("--list", nargs="+", metavar="NAME")
   r.set_defaults(run=cmd_storage_names)
   r = a.add_parser("rename", help="name one box")
   r.add_argument("box", type=int)
   r.add_argument("name")
   r.set_defaults(run=cmd_storage_rename)


def register_testsave(a: argparse._SubParsersAction) -> None:
   """!Adds `box` to the testsave action (inventory_cmds calls it with the testsave subparsers).
   @param a  the testsave action's subparsers
   @return None
   """
   r = a.add_parser("box", help="a test save's boxed creatures: put | remove | current")
   r.add_argument("name")
   b = r.add_subparsers(dest="box_command", metavar="BOX_ACTION")
   b.required = True
   t = b.add_parser("put", help="box a creature")
   t.add_argument("species")
   t.add_argument("level", nargs="?", type=int, default=storage.NEW_LEVEL)
   t.add_argument("--slot", type=int)
   t.set_defaults(run=cmd_box_put)
   t = b.add_parser("remove", help="take a boxed creature out")
   t.add_argument("slot", type=int)
   t.set_defaults(run=cmd_box_remove)
   t = b.add_parser("current", help="the current box")
   t.add_argument("box", type=int)
   t.set_defaults(run=cmd_box_current)


def _none(value: str) -> str | None:
   """!A name, or None for the word none.
   @param value  the command line's value
   @return it
   """
   return None if value == NONE_WORD else value


# -- recruit ----------------------------------------------------------------------------------------------------------

def cmd_show(args: argparse.Namespace) -> int:
   """!Prints the recruit rules and the items that recruit.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in recruit.lines(p.structure):
      print(line)
   print(f"{recruit.pipeline_name()}: " + ("the ruleset's" if recruit.has_pipeline(p) else "not in the ruleset"))
   items = recruit.recruit_items(p)
   print("items that recruit: " + (", ".join(f"{i} (bonus {recruit.recruit_bonus(p, i)})" for i in items) or
                                   "none"))
   return 0


def cmd_enable(args: argparse.Namespace) -> int:
   """!Gives the structure a recruit section.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Enable recruitment"):
      recruit.enable(p.structure, args.checks)
   return save_if_valid(p)


def cmd_disable(args: argparse.Namespace) -> int:
   """!Takes the recruit section out.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Disable recruitment"):
      recruit.disable(p.structure)
   return save_if_valid(p)


def cmd_pipeline(args: argparse.Namespace) -> int:
   """!Writes the neutral recruit_odds into the ruleset.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.ruleset.edit("Add recruit_odds"):
      recruit.add_pipeline(p.ruleset)
   return save_if_valid(p)


def cmd_set(args: argparse.Namespace) -> int:
   """!Sets a recruit field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value = _none(args.value) if args.field in (recruit.RATE_KEY, recruit.ITEM_ROLE_KEY) else args.value
   with p.structure.edit("Recruit " + args.field):
      recruit.set_field(p.structure, args.field, value)
   return save_if_valid(p)


def cmd_status_bonus(args: argparse.Namespace) -> int:
   """!Sets a status bonus.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.value == DEFAULT_WORD:
      value = None
   else:
      try:
         value = int(args.value)
      except ValueError:
         raise CommandError(f"a status bonus is a whole number or {DEFAULT_WORD} (got {args.value!r})") from None
   with p.structure.edit("Recruit status bonus"):
      recruit.set_status_bonus(p.structure, args.status, value)
   return save_if_valid(p)


def cmd_keep(args: argparse.Namespace) -> int:
   """!Sets what a recruited record keeps.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Recruit keep"):
      recruit.set_keep(p.structure, args.kept)
   return save_if_valid(p)


def cmd_refusal_consumes(args: argparse.Namespace) -> int:
   """!Sets the refusals that use the item up (C6).
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Recruit refusal consumes"):
      recruit.set_refusal_consumes(p.structure, args.refused)
   return save_if_valid(p)


def cmd_message(args: argparse.Namespace) -> int:
   """!Sets a moment's message.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Recruit message"):
      recruit.set_message(p.structure, args.moment, _none(args.key))
   return save_if_valid(p)


def cmd_break_free(args: argparse.Namespace) -> int:
   """!Sets the "broke free" messages.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Recruit break free"):
      recruit.set_break_free(p.structure, args.keys)
   return save_if_valid(p)


def cmd_odds(args: argparse.Namespace) -> int:
   """!Prints recruit_odds for some inputs.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   inputs = {}
   for pair in args.inputs:
      key, sep, value = pair.partition(PAIR_SEPARATOR)
      if not sep or not key:
         raise CommandError(f"an input is INPUT=V (got {pair!r})")
      try:
         inputs[key] = int(value, 0)
      except ValueError:
         raise CommandError(f"{key}: a whole number (got {value!r})") from None
   if args.species is not None:
      inputs.setdefault("recruit_rate", recruit.species_rate(p, args.species))
   print(recruit.odds_text(recruit.odds(p, inputs)))
   return 0


def cmd_item(args: argparse.Namespace) -> int:
   """!Makes an item recruit.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Recruit logic"):
      recruit.set_recruit_logic(p, args.item, args.bonus)
   return save_if_valid(p)


# -- storage ----------------------------------------------------------------------------------------------------------

def cmd_storage_show(args: argparse.Namespace) -> int:
   """!Prints the boxes, the budget and the save image.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   targets = [args.platform] if args.platform else stats.project_targets(p.structure.path)
   for line in storage.lines(p.structure, targets):
      print(line)
   print(storage.save_report(p, args.platform)[0])
   return 0


def cmd_storage_enable(args: argparse.Namespace) -> int:
   """!Gives the structure storage boxes.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Enable storage"):
      storage.enable(p.structure, args.boxes, args.size)
   return save_if_valid(p)


def cmd_storage_disable(args: argparse.Namespace) -> int:
   """!Takes the storage boxes out.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Disable storage"):
      storage.disable(p.structure)
   return save_if_valid(p)


def cmd_storage_set(args: argparse.Namespace) -> int:
   """!Sets box_count or box_size.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Storage " + args.field):
      storage.set_field(p.structure, args.field, args.value)
   return save_if_valid(p)


def cmd_storage_names(args: argparse.Namespace) -> int:
   """!Sets the box names.
   @param args  parsed arguments
   @return 0 or 1
   """
   if (args.pattern is None) == (args.list is None):
      raise CommandError("storage names takes a PATTERN or --list NAME ...")
   p = open_project(args)
   with p.structure.edit("Storage names"):
      storage.set_names(p.structure, args.list if args.list is not None else args.pattern)
   return save_if_valid(p)


def cmd_storage_rename(args: argparse.Namespace) -> int:
   """!Names one box.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Rename box"):
      storage.rename_box(p.structure, args.box, args.name)
   return save_if_valid(p)


# -- test saves' boxes ------------------------------------------------------------------------------------------------

def _box_change(args: argparse.Namespace, label: str, fn: Callable[[Document, Document], str | None]) -> int:
   """!One change of a test save's boxes, saved at once.
   @param args   parsed arguments
   @param label  undo label
   @param fn     callable(save, battle doc) -> a line to print
   @return 0
   """
   p = open_project(args)
   save = inventory.open_testsave(p, args.name)
   with save.edit(label):
      line = fn(save, p.battle)
   save.save()
   print(line)
   return 0


def cmd_box_put(args: argparse.Namespace) -> int:
   """!Boxes a creature in a test save.
   @param args  parsed arguments
   @return 0
   """
   def put(save: Document, doc: Document) -> str:
      """!Boxes it.
      @param save  test save Document
      @param doc   battle Document
      @return the line to print
      """
      return f"slot {storage.put_creature(save, doc, args.species, args.level, args.slot)}"

   return _box_change(args, "Box creature", put)


def cmd_box_remove(args: argparse.Namespace) -> int:
   """!Takes a boxed creature out of a test save.
   @param args  parsed arguments
   @return 0
   """
   return _box_change(args, "Unbox creature",
                      lambda save, _doc: f"took {storage.remove_creature(save, args.slot)[storage.BOXED_SPECIES]}")


def cmd_box_current(args: argparse.Namespace) -> int:
   """!Sets a test save's current box.
   @param args  parsed arguments
   @return 0
   """
   return _box_change(args, "Current box",
                      lambda save, doc: storage.set_current_box(save, doc, args.box) or f"current box {args.box}")
