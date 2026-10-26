"""!`capsule-studio battle FILE pocket|item-field|item-logic|shop|testsave ...` (D-26 section 2, engine G2): the bag's
pockets (core.structure.pockets), the items' bag and use fields and use logic, the shop lists and test saves
(core.inventory).

    battle FILE pocket list                      every pocket (slots, quantity, sort, items) and the budget
    battle FILE pocket add NAME [--label L] [--capacity N] [--at I]
    battle FILE pocket remove NAME [--move-to POCKET | --unpocket]
                                                 a pocket no item names (or move its items first)
    battle FILE pocket rename OLD NEW            the items naming it follow
    battle FILE pocket move NAME up|down
    battle FILE pocket set NAME label|capacity|quantity_max|sort VALUE
    battle FILE item-field ITEM                  the item's bag and use fields (defaults filled in)
    battle FILE item-field ITEM FIELD VALUE      pocket (a name or none), price, use, target, key / consumed /
                                                 holdable / allow_eggs (true | false)
    battle FILE item-logic ITEM [--add use_field|use_battle]
                                                 the item's use handlers (--add: a stub `fail;` handler)
    battle FILE shop list
    battle FILE shop add|remove NAME
    battle FILE shop rename OLD NEW
    battle FILE shop item SHOP add|remove ITEM [--at I]
    battle FILE testsave list|new NAME|show NAME [--json]|check NAME
    battle FILE testsave put NAME ITEM [COUNT] | take NAME ITEM [COUNT]
    battle FILE testsave export NAME OUT [--platform P]
                                                 the engine save image of the test save's bag (and boxes, G3)
    battle FILE testsave box NAME put|remove|current ...
                                                 G3: its boxed creatures (cli/recruit_cmds.py)
    battle FILE testsave nursery|nursery-result|egg NAME ...
    battle FILE testsave game NAME show|set|poke|from-image|clear ...   (S5: cli/game_block_cmds.py)
                                                 B2: its nursery slots, waiting result and boxed eggs
                                                 (cli/nursery_cmds.py)

Choice lists are the engine's (battle_compiler SORT_RULES, ITEM_USES, ITEM_TARGETS). Manifest actions save only
when the result compiles (battle_cmds.save_if_valid); a test save is its own file.
"""
from __future__ import annotations

import argparse

from ..core import inventory
from ..core.structure import pockets, stats
from .battle_cmds import json_value, open_project, save_if_valid
from .main import CommandError

## `pocket move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## The word for "no pocket" in `item-field ITEM pocket none`.
NO_POCKET_WORD = "none"


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the pocket, item-field, item-logic, shop and testsave actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("pocket", help="the bag's pockets: list | add | remove | rename | move | set")
   a = q.add_subparsers(dest="pocket_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="every pocket and the budget").set_defaults(run=cmd_pocket_list)
   r = a.add_parser("add", help="add a pocket")
   r.add_argument("name")
   r.add_argument("--label")
   r.add_argument("--capacity", type=int, default=pockets.NEW_CAPACITY)
   r.add_argument("--at", type=int)
   r.set_defaults(run=cmd_pocket_add)
   r = a.add_parser("remove", help="remove a pocket no item names")
   r.add_argument("name")
   g = r.add_mutually_exclusive_group()
   g.add_argument("--move-to", metavar="POCKET", help="move its items to this pocket first")
   g.add_argument("--unpocket", action="store_true", help="take its items out of the bag first")
   r.set_defaults(run=cmd_pocket_remove)
   r = a.add_parser("rename", help="rename a pocket; its items follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_pocket_rename)
   r = a.add_parser("move", help="move a pocket up or down")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_pocket_move)
   r = a.add_parser("set", help="a pocket's label, capacity, quantity_max or sort")
   r.add_argument("name")
   r.add_argument("field", choices=list(pockets.FIELDS))
   r.add_argument("value")
   r.set_defaults(run=cmd_pocket_set)

   r = s.add_parser("item-field", help="an item's bag and use fields (show, or set FIELD VALUE)")
   r.add_argument("item")
   r.add_argument("field", nargs="?")
   r.add_argument("value", nargs="?")
   r.set_defaults(run=cmd_item_field)
   r = s.add_parser("item-logic", help="an item's use handlers (use_field / use_battle)")
   r.add_argument("item")
   r.add_argument("--add", metavar="HOOK", help="add a stub handler for this use hook")
   r.set_defaults(run=cmd_item_logic)

   q = s.add_parser("shop", help="the shop lists: list | add | remove | rename | item")
   a = q.add_subparsers(dest="shop_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="every shop and what it sells").set_defaults(run=cmd_shop_list)
   for word, fn in (("add", cmd_shop_add), ("remove", cmd_shop_remove)):
      r = a.add_parser(word, help=f"{word} a shop")
      r.add_argument("name")
      r.set_defaults(run=fn)
   r = a.add_parser("rename", help="rename a shop")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_shop_rename)
   r = a.add_parser("item", help="put an item on a shop's list or take it off")
   r.add_argument("shop")
   r.add_argument("action", choices=["add", "remove"])
   r.add_argument("item")
   r.add_argument("--at", type=int)
   r.set_defaults(run=cmd_shop_item)

   q = s.add_parser("testsave", help="test saves (a bag by pocket): list | new | show | check | put | take | export")
   a = q.add_subparsers(dest="testsave_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="the game's test saves").set_defaults(run=cmd_save_list)
   for word, fn in (("new", cmd_save_new), ("check", cmd_save_check)):
      r = a.add_parser(word, help=f"{word} a test save")
      r.add_argument("name")
      r.set_defaults(run=fn)
   r = a.add_parser("show", help="a test save's bag")
   r.add_argument("name")
   r.add_argument("--json", action="store_true")
   r.set_defaults(run=cmd_save_show)
   for word, fn in (("put", cmd_save_put), ("take", cmd_save_take)):
      r = a.add_parser(word, help=f"{word} items")
      r.add_argument("name")
      r.add_argument("item")
      r.add_argument("count", nargs="?", type=int)
      r.set_defaults(run=fn)
   r = a.add_parser("export", help="write the engine save image of the bag")
   r.add_argument("name")
   r.add_argument("out")
   r.add_argument("--platform")
   r.set_defaults(run=cmd_save_export)
   # G3: the test save's boxed creatures (cli/recruit_cmds.py)
   from . import recruit_cmds   # local: the box commands live with the recruit ones
   recruit_cmds.register_testsave(a)
   # F3: the test save's step counters (cli/step_effect_cmds.py)
   from . import step_effect_cmds   # local: the step commands live with the step effect ones
   step_effect_cmds.register_testsave(a)
   # B2: the test save's nursery slots, waiting result and boxed eggs (cli/nursery_cmds.py)
   from . import nursery_cmds   # local: the test save egg commands live with the nursery ones
   nursery_cmds.register_testsave(a)
   # S5 (N3): the test save's game block (cli/game_block_cmds.py)
   from . import game_block_cmds   # local: like the others
   game_block_cmds.register_testsave(a)


# -- pockets ----------------------------------------------------------------------------------------------------------

def cmd_pocket_list(args: argparse.Namespace) -> int:
   """!Prints the pockets.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in pockets.lines(p.structure, stats.project_targets(p.structure.path)):
      print(line)
   return 0


def cmd_pocket_add(args: argparse.Namespace) -> int:
   """!Adds a pocket.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Add pocket"):
      i = pockets.add_pocket(p.structure, args.name, args.label, args.capacity, args.at)
   print(f"added pocket {args.name!r} at {i}")
   return save_if_valid(p)


def cmd_pocket_remove(args: argparse.Namespace) -> int:
   """!Removes a pocket (moving its items first when asked).
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Remove pocket"):
      if args.move_to or args.unpocket:
         n = pockets.move_items(p.structure, args.name, args.move_to)
         print(f"moved {n} item(s) {'to ' + args.move_to if args.move_to else 'out of the bag'}")
      pockets.remove_pocket(p.structure, args.name)
   return save_if_valid(p)


def cmd_pocket_rename(args: argparse.Namespace) -> int:
   """!Renames a pocket.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Rename pocket"):
      n = pockets.rename_pocket(p.structure, args.old, args.new)
   print(f"renamed; {n} item(s) updated")
   return save_if_valid(p)


def cmd_pocket_move(args: argparse.Namespace) -> int:
   """!Moves a pocket.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Move pocket"):
      moved = pockets.move_pocket(p.structure, args.name, MOVES[args.direction])
   if not moved:
      raise CommandError(f"{args.name} is already at the {'top' if args.direction == 'up' else 'bottom'}")
   return save_if_valid(p)


def cmd_pocket_set(args: argparse.Namespace) -> int:
   """!Sets a pocket's field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Pocket " + args.field):
      pockets.set_field(p.structure, args.name, args.field, args.value)
   return save_if_valid(p)


# -- items ------------------------------------------------------------------------------------------------------------

def cmd_item_field(args: argparse.Namespace) -> int:
   """!Shows an item's bag and use fields, or sets one.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.field is None:
      for k, v in inventory.fields_of(p.battle, args.item).items():
         print(f"{k}: {NO_POCKET_WORD if v is None else v}")
      needed = inventory.hooks_needed(inventory.fields_of(p.battle, args.item)[inventory.USE_KEY])
      print("needs: " + (", ".join(f"on {h}" for h in needed) if needed else "no use logic"))
      return 0
   if args.value is None:
      raise CommandError(f"item-field {args.item} {args.field} needs a value")
   value = None if args.field == inventory.POCKET_KEY and args.value == NO_POCKET_WORD else json_value(args.value)
   if args.field == inventory.POCKET_KEY and value is not None:
      value = str(value)
   with p.battle.edit(f"Item {args.field}"):
      inventory.set_item_field(p.battle, args.item, args.field, value)
   return save_if_valid(p)


def cmd_item_logic(args: argparse.Namespace) -> int:
   """!Shows an item's use handlers, or adds a stub one.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.add:
      with p.battle.edit("Add use logic"):
         inventory.add_use_handler(p, args.item, args.add)
      return save_if_valid(p)
   for hook, text in inventory.use_logic(p, args.item).items():
      print(f"{hook}: " + ("(none)" if text is None else ""))
      if text is not None:
         print(text)
   return 0


# -- shops ------------------------------------------------------------------------------------------------------------

def cmd_shop_list(args: argparse.Namespace) -> int:
   """!Prints the shops.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   rows = inventory.shops(p.battle)
   for i, s in enumerate(rows):
      print(f"{i} {s['name']}: " + (", ".join(s[inventory.SHOP_ITEMS_KEY]) or "nothing"))
   if not rows:
      print("(no shops)")
   return 0


def cmd_shop_add(args: argparse.Namespace) -> int:
   """!Adds a shop.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add shop"):
      inventory.add_shop(p.battle, args.name)
   return save_if_valid(p)


def cmd_shop_remove(args: argparse.Namespace) -> int:
   """!Removes a shop.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove shop"):
      inventory.remove_shop(p.battle, args.name)
   return save_if_valid(p)


def cmd_shop_rename(args: argparse.Namespace) -> int:
   """!Renames a shop.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Rename shop"):
      inventory.rename_shop(p.battle, args.old, args.new)
   return save_if_valid(p)


def cmd_shop_item(args: argparse.Namespace) -> int:
   """!Puts an item on a shop's list or takes it off.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Shop item"):
      if args.action == "add":
         inventory.add_shop_item(p.battle, args.shop, args.item, args.at)
      else:
         inventory.remove_shop_item(p.battle, args.shop, args.item)
   return save_if_valid(p)


# -- test saves -------------------------------------------------------------------------------------------------------

def cmd_save_list(args: argparse.Namespace) -> int:
   """!Lists the test saves.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   paths = inventory.testsave_paths(p)
   for path in paths:
      print(path.stem)
   if not paths:
      print(f"(no test saves in {inventory.testsave_folder(p)})")
   return 0


def cmd_save_new(args: argparse.Namespace) -> int:
   """!Writes an empty test save.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   doc = inventory.new_testsave(p, args.name)
   print(f"wrote {doc.path}")
   return 0


def cmd_save_show(args: argparse.Namespace) -> int:
   """!Prints a test save.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   save = inventory.open_testsave(p, args.name)
   if args.json:
      print(inventory.dumps(save))
      return 0
   for line in inventory.lines(save, p.battle):
      print(line)
   return 0


def cmd_save_check(args: argparse.Namespace) -> int:
   """!Checks a test save against the manifests.
   @param args  parsed arguments
   @return 0, or 1 with problems
   """
   p = open_project(args)
   problems = inventory.check(inventory.open_testsave(p, args.name), p.battle)
   for line in problems:
      print(f"problem: {line}")
   if not problems:
      print("ok")
   return 1 if problems else 0


def cmd_save_put(args: argparse.Namespace) -> int:
   """!Adds items to a test save and saves it.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   save = inventory.open_testsave(p, args.name)
   with save.edit("Put items"):
      n = inventory.put(save, p.battle, args.item, 1 if args.count is None else args.count)
   save.save()
   print(f"{args.item} x{n}")
   return 0


def cmd_save_take(args: argparse.Namespace) -> int:
   """!Takes items out of a test save and saves it.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   save = inventory.open_testsave(p, args.name)
   with save.edit("Take items"):
      left = inventory.take(save, p.battle, args.item, args.count)
   save.save()
   print(f"{args.item} x{left}")
   return 0


def cmd_save_export(args: argparse.Namespace) -> int:
   """!Writes a test save's engine image.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   n = inventory.export(inventory.open_testsave(p, args.name), p, args.out, args.platform)
   print(f"wrote {args.out} ({n} B)")
   return 0
