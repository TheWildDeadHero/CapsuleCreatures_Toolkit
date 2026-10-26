"""!`capsule-studio battle FILE ...` actions for the condition records, move
flags, tags, categories, passives / items and manifest point handlers
(D-23 §3.4 `battle condition KIND ...`, `battle flag|tag ...`;
core.structure.conditions, core.structure.flags, core.structure.categories,
core.holders).

    battle FILE condition KIND list            KIND: status volatile weather side_condition field_condition
    battle FILE condition KIND show NAME       its fields, texts and what names it
    battle FILE condition KIND add NAME [--copy OTHER] [--at I]
    battle FILE condition KIND remove NAME     refused while effect logic names it
    battle FILE condition KIND rename OLD NEW  effect logic follows
    battle FILE condition KIND move NAME up|down
    battle FILE condition KIND set NAME KEY VALUE        VALUE JSON (bare words are text; null: the default)
    battle FILE condition KIND text NAME SLOT [TEXT] [--message KEY] [--clear]
    battle FILE condition budget               volatile bits / counters / words, status ids, side, field
    battle FILE flag|tag list                  names with their use counts and the budget
    battle FILE flag|tag add NAME [--at I] | remove NAME | rename OLD NEW | move NAME up|down
    battle FILE category list | add NAME [--offense S --defense S] [--at I] | damage NAME OFFENSE DEFENSE
                         (none none: non-damaging) | remove NAME | rename OLD NEW | move NAME up|down |
                         mode move|type [--default CATEGORY] | type TYPE CATEGORY   (category_by_type, E11) |
                         hit on|off [--default CATEGORY] | hit-type TYPE CATEGORY   (hit_category_by_type, C5)
    battle FILE holder passives|items list | announce NAME on|off
    battle FILE handler LIST NAME list | add POINT [CODE] [--at I] | set INDEX [--point P] [--code C] |
                                 remove INDEX | move INDEX up|down
                         LIST: a list of the engine's OWNER_SOURCES (passives items statuses weathers: manifest
                         handlers; E13b moves volatiles side_conditions: their .ceffect point members)

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core import engine, holders
from ..core.structure import categories, conditions, flags
from .battle_cmds import json_value, open_project, save_if_valid
from .main import CommandError

## `move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## `holder announce` values.
SWITCH = {"on": True, "off": False}
## The word of `category damage` that means "no stat" (both: non-damaging).
NO_STAT = "none"


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   _register_condition(s)
   for which, word in ((flags.FLAGS_KEY, "flag"), (flags.TAGS_KEY, "tag")):
      _register_names(s, which, word)
   _register_category(s)
   _register_holder(s)
   _register_handler(s)


def _add_move(a: argparse._SubParsersAction, run: object, what: str) -> None:
   """!Adds a `move NAME up|down` action.
   @param a     the action subparsers
   @param run   its command function
   @param what  what moves (help text)
   @return None
   """
   r = a.add_parser("move", help=f"move a {what} up or down (its engine index)")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=run)


def _register_condition(s: argparse._SubParsersAction) -> None:
   """!Adds `condition ...`.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("condition", help="condition records: KIND list | show | add | remove | rename | move | set | "
                                      "text, or budget")
   kinds = q.add_subparsers(dest="condition_kind", metavar="KIND")
   kinds.required = True
   b = kinds.add_parser("budget", help="the condition budgets (volatile bits, counters, words, status ids, ...)")
   b.set_defaults(run=cmd_condition_budget)
   try:
      engine_kinds = conditions.kinds()
   except engine.EngineNotFound:   # the parser builds without an engine; every battle action needs one
      engine_kinds = []
   for kind in engine_kinds:
      k = kinds.add_parser(kind, help=f"the {kind} records")
      k.set_defaults(kind=kind)
      a = k.add_subparsers(dest="condition_command", metavar="ACTION")
      a.required = True
      r = a.add_parser("list", help="the records with their fields")
      r.set_defaults(run=cmd_condition_list)
      r = a.add_parser("show", help="one record: fields, texts, what names it")
      r.add_argument("name")
      r.set_defaults(run=cmd_condition_show)
      r = a.add_parser("add", help="add a record (a copy with --copy)")
      r.add_argument("name")
      r.add_argument("--copy", help="the record to copy")
      r.add_argument("--at", type=int, help="position (default: the end)")
      r.set_defaults(run=cmd_condition_add)
      r = a.add_parser("remove", help="remove a record no effect logic names")
      r.add_argument("name")
      r.set_defaults(run=cmd_condition_remove)
      r = a.add_parser("rename", help="rename a record and the effect logic naming it")
      r.add_argument("old")
      r.add_argument("new")
      r.set_defaults(run=cmd_condition_rename)
      _add_move(a, cmd_condition_move, kind)
      r = a.add_parser("set", help=f"change a field: KEY one of {', '.join(conditions.FIELDS[kind])}; VALUE JSON "
                                   "(null: the default)")
      r.add_argument("name")
      r.add_argument("key", choices=list(conditions.FIELDS[kind]))
      r.add_argument("value")
      r.set_defaults(run=cmd_condition_set)
      r = a.add_parser("text", help="set one text (or --message KEY, or --clear)")
      r.add_argument("name")
      r.add_argument("slot")
      r.add_argument("text", nargs="?")
      r.add_argument("--message", help="an engine message (volatiles, side and field conditions)")
      r.add_argument("--clear", action="store_true", help="remove the text")
      r.set_defaults(run=cmd_condition_text)


def _register_names(s: argparse._SubParsersAction, which: str, word: str) -> None:
   """!Adds `flag ...` or `tag ...`.
   @param s      the battle group's subparsers
   @param which  flags.FLAGS_KEY or flags.TAGS_KEY
   @param word   the command word
   @return None
   """
   q = s.add_parser(word, help=f"the {which}: list | add | remove | rename | move")
   q.set_defaults(which=which)
   a = q.add_subparsers(dest=f"{word}_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="the names with their use counts, and the budget")
   r.set_defaults(run=cmd_names_list)
   r = a.add_parser("add", help=f"add a {word}")
   r.add_argument("name")
   r.add_argument("--at", type=int, help="position (its bit; default: the end)")
   r.set_defaults(run=cmd_names_add)
   r = a.add_parser("remove", help=f"remove a {word} nothing uses")
   r.add_argument("name")
   r.set_defaults(run=cmd_names_remove)
   r = a.add_parser("rename", help=f"rename a {word}; every use follows (moves, records, effect logic)")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_names_rename)
   _add_move(a, cmd_names_move, word)
   if which == flags.TAGS_KEY:
      r = a.add_parser("weather-suppress", help="the tag whose holders keep the weather from acting (C6): [NAME|none]")
      r.add_argument("name", nargs="?")
      r.set_defaults(run=cmd_weather_suppress)


def _register_category(s: argparse._SubParsersAction) -> None:
   """!Adds `category ...`.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("category", help="move categories: list | add | damage | remove | rename | move | mode | type")
   a = q.add_subparsers(dest="category_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="the categories, their damage stats and moves")
   r.set_defaults(run=cmd_category_list)
   r = a.add_parser("add", help="add a category (non-damaging without --offense / --defense)")
   r.add_argument("name")
   r.add_argument("--offense", help="the stat its damage attacks with")
   r.add_argument("--defense", help="the stat its damage meets")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_category_add)
   r = a.add_parser("damage", help=f"the stats its damage uses ({NO_STAT} {NO_STAT}: non-damaging)")
   r.add_argument("name")
   r.add_argument("offense")
   r.add_argument("defense")
   r.set_defaults(run=cmd_category_damage)
   r = a.add_parser("remove", help="remove a category nothing names")
   r.add_argument("name")
   r.set_defaults(run=cmd_category_remove)
   r = a.add_parser("rename", help="rename a category; moves, rules.self_hit, category_by_type and effect logic "
                                   "follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_category_rename)
   _add_move(a, cmd_category_move, "category")
   r = a.add_parser("mode", help="where a damaging move's category comes from: the move, or its type "
                                 "(category_by_type: each type takes its moves' most common damaging category)")
   r.add_argument("mode", choices=(categories.BY_MOVE, categories.BY_TYPE))
   r.add_argument("--default", help="type mode: the category of a type without damaging moves (default: the first "
                                    "damaging one)")
   r.set_defaults(run=cmd_category_mode)
   r = a.add_parser("type", help="type mode: the damaging category a type gives its damaging moves")
   r.add_argument("type")
   r.add_argument("category")
   r.set_defaults(run=cmd_category_type)
   r = a.add_parser("hit", help="move mode (C5): the category a damaging move hits with when the move_type point "
                                "changed its type follows the hit type (on: each type its moves' most common one)")
   r.add_argument("value", choices=list(SWITCH))
   r.add_argument("--default", help="on: the category of a type without damaging moves (default: the first "
                                    "damaging one)")
   r.set_defaults(run=cmd_category_hit)
   r = a.add_parser("hit-type", help="the damaging category a hit of this type takes (hit types' categories on)")
   r.add_argument("type")
   r.add_argument("category")
   r.set_defaults(run=cmd_category_hit_type)


def _register_holder(s: argparse._SubParsersAction) -> None:
   """!Adds `holder ...`.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("holder", help="passives / items: list | announce")
   q.add_argument("list", choices=list(holders.HOLDER_LISTS))
   a = q.add_subparsers(dest="holder_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="names, announce flag, point handlers, uses")
   r.set_defaults(run=cmd_holder_list)
   r = a.add_parser("announce", help="whether the battle shows it when its logic announces it")
   r.add_argument("name")
   r.add_argument("value", choices=list(SWITCH))
   r.set_defaults(run=cmd_holder_announce)


def _register_handler(s: argparse._SubParsersAction) -> None:
   """!Adds `handler ...`.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("handler", help="an entry's point handlers: list | add | set | remove | move (moves, "
                                    "volatiles, side conditions: their .ceffect point members, E13b)")
   # no fixed choices: the lists are the engine's (holders.handler_lists(), checked when the command runs)
   q.add_argument("list", metavar="LIST", help="a list whose entries hold point handlers (the engine's "
                                               "battle_compiler OWNER_SOURCES keys)")
   q.add_argument("name")
   a = q.add_subparsers(dest="handler_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="the handlers, numbered")
   r.set_defaults(run=cmd_handler_list)
   r = a.add_parser("add", help="add a handler (default code: x1)")
   r.add_argument("point")
   r.add_argument("code", nargs="?", default=holders.NEW_CODE)
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_handler_add)
   r = a.add_parser("set", help="change a handler's point and / or code")
   r.add_argument("index", type=int)
   r.add_argument("--point")
   r.add_argument("--code")
   r.set_defaults(run=cmd_handler_set)
   r = a.add_parser("remove", help="remove a handler")
   r.add_argument("index", type=int)
   r.set_defaults(run=cmd_handler_remove)
   r = a.add_parser("move", help="move a handler up or down")
   r.add_argument("index", type=int)
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_handler_move)


def _moved(moved: bool, name: object, direction: str) -> None:
   """!Refuses a move that did nothing.
   @param moved      what the move returned
   @param name       what was moved
   @param direction  "up" or "down"
   @return None
   """
   if not moved:
      raise CommandError(f"{name} is already at the {'top' if direction == 'up' else 'bottom'}")


# -- conditions --------------------------------------------------------------------------------------------------------

def cmd_condition_budget(args: argparse.Namespace) -> int:
   """!Prints the condition budgets.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for row in conditions.budget(p.battle):
      print(conditions.budget_line(row))
   return 0


def cmd_condition_list(args: argparse.Namespace) -> int:
   """!Prints a kind's records.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in conditions.report(p.battle, args.kind)[1:]:
      print(line.strip())
   return 0


def cmd_condition_show(args: argparse.Namespace) -> int:
   """!Prints one record.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   doc = p.battle
   e = conditions.record(doc, args.kind, args.name)
   i = conditions.names(doc, args.kind).index(args.name)
   print(conditions.record_line(doc, args.kind, i, e))
   for slot, value in conditions.texts_of(doc, args.kind, args.name):
      print(f"  text {slot}: {value if value is not None else '(none)'}")
   for k, h in enumerate(e.get("handlers", []) if isinstance(e.get("handlers"), list) else []):
      print(f"  handler {k}: point {h.get('point')} {h.get('code')}")
   for where in conditions.uses(doc, args.kind, args.name):
      print(f"  named by {where}")
   for where in conditions.bench_uses(p, args.kind, args.name):
      print(f"  bench {where}")
   return 0


def cmd_condition_add(args: argparse.Namespace) -> int:
   """!Adds a record.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"Add {args.kind}"):
      i = conditions.add_record(p.battle, args.kind, args.name, args.copy, args.at)
   print(f"added {args.kind} {args.name.strip()!r} at {i}")
   return save_if_valid(p)


def cmd_condition_remove(args: argparse.Namespace) -> int:
   """!Removes a record.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"Remove {args.kind}"):
      conditions.remove_record(p.battle, args.kind, args.name)
   return save_if_valid(p)


def cmd_condition_rename(args: argparse.Namespace) -> int:
   """!Renames a record.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   bench = conditions.bench_uses(p, args.kind, args.old)
   with p.battle.edit(f"Rename {args.kind}"):
      n = conditions.rename_record(p.battle, args.kind, args.old, args.new)
   print(f"renamed; {n} reference(s) updated")
   for where in bench:
      print(f"bench scenario follows: {where}")
   return save_if_valid(p)


def cmd_condition_move(args: argparse.Namespace) -> int:
   """!Moves a record.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"Move {args.kind}"):
      moved = conditions.move_record(p.battle, args.kind, args.name, MOVES[args.direction])
   _moved(moved, args.name, args.direction)
   return save_if_valid(p)


def cmd_condition_set(args: argparse.Namespace) -> int:
   """!Changes one field of a record.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"Set {args.kind} {args.key}"):
      conditions.set_field(p.battle, args.kind, args.name, args.key, json_value(args.value))
   return save_if_valid(p)


def cmd_condition_text(args: argparse.Namespace) -> int:
   """!Sets or clears one text of a record.
   @param args  parsed arguments
   @return 0 or 1
   """
   if sum(x is not None and x is not False for x in (args.text, args.message, args.clear or None)) != 1:
      raise CommandError("give the text, --message KEY or --clear")
   value = None if args.clear else {conditions.MESSAGE_KEY: args.message} if args.message else args.text
   p = open_project(args)
   with p.battle.edit(f"{args.kind} text"):
      conditions.set_text(p.battle, args.kind, args.name, args.slot, value)
   return save_if_valid(p)


# -- move flags and tags -----------------------------------------------------------------------------------------------

def cmd_names_list(args: argparse.Namespace) -> int:
   """!Prints the move flags or tags.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in flags.report(p.battle, args.which):
      print(line)
   return 0


def cmd_weather_suppress(args: argparse.Namespace) -> int:
   """!Shows or names the weather-suppressing tag (C6).
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.name is None:
      print(flags.weather_suppress_tag(p.battle) or "none")
      return 0
   with p.battle.edit("Weather suppress tag"):
      flags.set_weather_suppress_tag(p.battle, None if args.name == "none" else args.name)
   return save_if_valid(p)


def cmd_names_add(args: argparse.Namespace) -> int:
   """!Adds a move flag or tag.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"Add {flags.SINGULAR[args.which]}"):
      i = flags.add_name(p.battle, args.which, args.name, args.at)
   print(f"added {flags.SINGULAR[args.which]} {args.name.strip()!r} at {i}")
   return save_if_valid(p)


def cmd_names_remove(args: argparse.Namespace) -> int:
   """!Removes a move flag or tag.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"Remove {flags.SINGULAR[args.which]}"):
      flags.remove_name(p.battle, args.which, args.name)
   return save_if_valid(p)


def cmd_names_rename(args: argparse.Namespace) -> int:
   """!Renames a move flag or tag.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"Rename {flags.SINGULAR[args.which]}"):
      n = flags.rename_name(p.battle, args.which, args.old, args.new)
   print(f"renamed; {n} use(s) updated")
   return save_if_valid(p)


def cmd_names_move(args: argparse.Namespace) -> int:
   """!Moves a move flag or tag.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"Move {flags.SINGULAR[args.which]}"):
      moved = flags.move_name(p.battle, args.which, args.name, MOVES[args.direction])
   _moved(moved, args.name, args.direction)
   return save_if_valid(p)


# -- categories --------------------------------------------------------------------------------------------------------

def _stat(text: str | None) -> str | None:
   """!A stat argument (NO_STAT: none).
   @param text  the argument
   @return the stat, or None
   """
   return None if text is None or text == NO_STAT else text


def cmd_category_list(args: argparse.Namespace) -> int:
   """!Prints the categories.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in categories.report(p.battle):
      print(line)
   return 0


def cmd_category_add(args: argparse.Namespace) -> int:
   """!Adds a category.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add category"):
      i = categories.add_category(p.battle, args.name, _stat(args.offense), _stat(args.defense), args.at)
   print(f"added category {args.name.strip()!r} at {i}")
   return save_if_valid(p)


def cmd_category_damage(args: argparse.Namespace) -> int:
   """!Sets a category's damage stats.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Category damage"):
      categories.set_damage(p.battle, args.name, _stat(args.offense), _stat(args.defense))
   return save_if_valid(p)


def cmd_category_remove(args: argparse.Namespace) -> int:
   """!Removes a category.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove category"):
      categories.remove_category(p.battle, args.name)
   return save_if_valid(p)


def cmd_category_rename(args: argparse.Namespace) -> int:
   """!Renames a category.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Rename category"):
      n = categories.rename_category(p.battle, args.old, args.new)
   print(f"renamed; {n} reference(s) updated")
   return save_if_valid(p)


def cmd_category_move(args: argparse.Namespace) -> int:
   """!Moves a category.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move category"):
      moved = categories.move_category(p.battle, args.name, MOVES[args.direction])
   _moved(moved, args.name, args.direction)
   return save_if_valid(p)


def cmd_category_mode(args: argparse.Namespace) -> int:
   """!Switches where damaging moves take their category from.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Category mode"):
      changed = categories.set_mode(p.battle, args.mode, args.default)
   print(f"categories come from the {args.mode}" + (f"; {changed} move(s) take their type's" if changed else ""))
   return save_if_valid(p)


def cmd_category_type(args: argparse.Namespace) -> int:
   """!Sets one type's damaging category (category_by_type).
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Type category"):
      changed = categories.set_type_category(p.battle, args.type, args.category)
   print(f"{args.type}: {args.category}" + (f"; {changed} move(s) follow" if changed else ""))
   return save_if_valid(p)


def cmd_category_hit(args: argparse.Namespace) -> int:
   """!Turns the hit types' categories on or off (structure hit_category_by_type, engine C5).
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Hit categories"):
      changed = categories.set_hit(p.battle, SWITCH[args.value], args.default)
   if not changed:
      print(f"the hit types' categories are already {args.value}")
   return save_if_valid(p)


def cmd_category_hit_type(args: argparse.Namespace) -> int:
   """!Sets the category a hit of one type takes (hit_category_by_type).
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Hit type category"):
      categories.set_hit_category(p.battle, args.type, args.category)
   print(f"a {args.type} hit: {args.category}")
   return save_if_valid(p)


# -- passives / items and point handlers -------------------------------------------------------------------------------

def cmd_holder_list(args: argparse.Namespace) -> int:
   """!Prints the passives or items.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in holders.report(p.battle, args.list):
      print(line)
   return 0


def cmd_holder_announce(args: argparse.Namespace) -> int:
   """!Sets a holder's announce flag.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Announce"):
      holders.set_announce(p.battle, args.list, args.name, SWITCH[args.value])
   return save_if_valid(p)


def cmd_handler_list(args: argparse.Namespace) -> int:
   """!Prints an entry's point handlers.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for i, h in enumerate(holders.handlers(p.battle, args.list, args.name)):
      print(f"{i} point {h.get('point')} {h.get('code')}")
   print(f"points it may handle: {', '.join(holders.point_choices(p, args.list)) or 'none'}")
   return 0


def cmd_handler_add(args: argparse.Namespace) -> int:
   """!Adds a point handler.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add point handler"):
      i = holders.add_handler(p.battle, args.list, args.name, args.point, args.code,
                              holders.point_choices(p, args.list), args.at)
   print(f"added handler {i}")
   return save_if_valid(p)


def cmd_handler_set(args: argparse.Namespace) -> int:
   """!Changes a point handler.
   @param args  parsed arguments
   @return 0 or 1
   """
   if args.point is None and args.code is None:
      raise CommandError("give --point and / or --code")
   p = open_project(args)
   with p.battle.edit("Point handler"):
      holders.set_handler(p.battle, args.list, args.name, args.index, args.point, args.code,
                          holders.point_choices(p, args.list))
   return save_if_valid(p)


def cmd_handler_remove(args: argparse.Namespace) -> int:
   """!Removes a point handler.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove point handler"):
      holders.remove_handler(p.battle, args.list, args.name, args.index)
   return save_if_valid(p)


def cmd_handler_move(args: argparse.Namespace) -> int:
   """!Moves a point handler.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move point handler"):
      moved = holders.move_handler(p.battle, args.list, args.name, args.index, MOVES[args.direction])
   _moved(moved, f"handler {args.index}", args.direction)
   return save_if_valid(p)
