"""!`capsule-studio battle FILE combine ...` (engine B1, D-28 section 1): the structure manifest's combination methods
(core.structure.combination).

    battle FILE combine list                          every method (kind, inputs, rules, tables, users)
    battle FILE combine show NAME                     one method in full
    battle FILE combine add NAME [--count N] [--at I] an immediate method (its rule: the first input's species)
    battle FILE combine remove NAME                   refused while effect logic or the game's scripts name it
    battle FILE combine rename OLD NEW                effect logic and the game's scripts follow
    battle FILE combine move NAME up|down
    battle FILE combine set NAME KEY VALUE            label | kind | delivery | afterwards | allow_eggs | level | odds |
                                                      fee (odds / fee "": none)
    battle FILE combine count NAME MIN [MAX]          the inputs (slots added or dropped at the end)
    battle FILE combine slot NAME K [--role R] [--requires EXPR | --no-requires]
                                                      a slot's role (the method's expressions and input.ROLE follow)
                                                      and requirement
    battle FILE combine table NAME add T KEY | remove T | rename T NEW | key T KEY | symmetric T on|off |
                                   cell T A B [VALUE] (no VALUE: the cell goes)
    battle FILE combine rule NAME add recipe A,B,... RESULT | add table T | add expression EXPR
                                  [--when E] [--where E] [--order F] [--choose C] [--else E]
    battle FILE combine rule NAME remove K | move K up|down | when K EXPR | pick K [--where ...]
    battle FILE combine moves NAME [--limit N] [--chooser C] [--fill on|off] [--push on|off]
                                                      C9: --push: the chosen moves after the result's own ones
    battle FILE combine source NAME KIND on|off|remove [--limit N] [--all] [--from ROLE]
                                                      C9: --from: the one slot role it reads (its moves in slot
                                                      order); without it every input
    battle FILE combine message NAME MOMENT [KEY]     the battle message at a moment (no KEY: none)
    battle FILE combine preview NAME SPECIES[:LEVEL] ... [--context N=V] [--save SAVE --slots S,S]
                                                      "A + B -> C" without the random parts (a test save's boxed
                                                      creatures by slot)

A recipe's matchers are species names, FIELD=VALUE (a species field value) or type=TYPE. Editing actions save only
when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse
from typing import Any

from ..core import inventory
from ..core.structure import combination, storage
from .battle_cmds import json_value, open_project, save_if_valid
from .main import CommandError

## `move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## The method keys `set` writes.
SET_KEYS = ["label", "kind", "delivery", "afterwards", "allow_eggs", "level", "odds", "fee"]
## The words of on / off arguments.
ON_OFF = {"on": True, "off": False}
## A matcher's separator (FIELD=VALUE).
MATCH_SEP = "="
## A preview record's separator (SPECIES:LEVEL).
LEVEL_SEP = ":"
## Argument counts after the table: a cell's pair, and with its value.
CELL_PAIR_ARGS, CELL_VALUE_ARGS = 2, 3
## Argument counts of `rule add`: KIND plus one (table T, expression EXPR), a recipe's KIND A,B,... RESULT.
RULE_ONE_ARGS, RECIPE_ARGS = 2, 3
## Argument count of the rule actions naming a rule and one more (move K up|down, when K EXPR).
RULE_INDEX_ARGS = 2
## A preview record's level without one.
DEFAULT_LEVEL = 1


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the combine actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("combine", help="combination methods: list | show | add | remove | rename | move | set | count | "
                                    "slot | table | rule | moves | source | message | preview")
   a = q.add_subparsers(dest="combine_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="every method").set_defaults(run=cmd_list)
   r = a.add_parser("show", help="one method in full")
   r.add_argument("name")
   r.set_defaults(run=cmd_show)
   r = a.add_parser("add", help="add an immediate method")
   r.add_argument("name")
   r.add_argument("--count", type=int, default=combination.DEFAULT_COUNT, help="its inputs")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_add)
   r = a.add_parser("remove", help="remove a method")
   r.add_argument("name")
   r.set_defaults(run=cmd_remove)
   r = a.add_parser("rename", help="rename a method; effect logic and scripts follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename)
   r = a.add_parser("move", help="move a method up or down")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_move)
   r = a.add_parser("set", help="one of a method's keys")
   r.add_argument("name")
   r.add_argument("key", choices=SET_KEYS)
   r.add_argument("value")
   r.set_defaults(run=cmd_set)
   r = a.add_parser("count", help="the input count")
   r.add_argument("name")
   r.add_argument("lo", type=int)
   r.add_argument("hi", type=int, nargs="?")
   r.set_defaults(run=cmd_count)
   r = a.add_parser("slot", help="a slot's role and requirement")
   r.add_argument("name")
   r.add_argument("slot", type=int)
   r.add_argument("--role")
   r.add_argument("--requires")
   r.add_argument("--no-requires", action="store_true")
   r.set_defaults(run=cmd_slot)
   r = a.add_parser("table", help="a method's tables")
   r.add_argument("name")
   r.add_argument("action", choices=["add", "remove", "rename", "key", "symmetric", "cell"])
   r.add_argument("table")
   r.add_argument("args", nargs="*")
   r.set_defaults(run=cmd_table)
   r = a.add_parser("rule", help="a method's result rules")
   r.add_argument("name")
   r.add_argument("action", choices=["add", "remove", "move", "when", "pick"])
   r.add_argument("args", nargs="*")
   r.add_argument("--when")
   r.add_argument("--where")
   r.add_argument("--order")
   r.add_argument("--choose", choices=combination.pick_choices())
   r.add_argument("--else", dest="otherwise", choices=combination.pick_fallbacks())
   r.set_defaults(run=cmd_rule)
   r = a.add_parser("moves", help="the move chooser")
   r.add_argument("name")
   r.add_argument("--limit", type=int)
   r.add_argument("--chooser", choices=combination.choosers())
   r.add_argument("--fill", choices=list(ON_OFF))
   r.add_argument("--push", choices=list(ON_OFF))
   r.set_defaults(run=cmd_moves)
   r = a.add_parser("source", help="a move source")
   r.add_argument("name")
   r.add_argument("kind", choices=combination.move_sources())
   r.add_argument("state", choices=[*ON_OFF, "remove"])
   r.add_argument("--limit", type=int, default=0)
   r.add_argument("--all", action="store_true")
   r.add_argument("--from", dest="role", help="the one slot role the source reads (C9)")
   r.set_defaults(run=cmd_source)
   r = a.add_parser("message", help="the battle message at a moment")
   r.add_argument("name")
   r.add_argument("moment", choices=combination.moments())
   r.add_argument("key", nargs="?")
   r.set_defaults(run=cmd_message)
   r = a.add_parser("preview", help="what a combination gives (no random parts)")
   r.add_argument("name")
   r.add_argument("records", nargs="*", help="SPECIES[:LEVEL]")
   r.add_argument("--context", action="append", default=[], help="NAME=VALUE")
   r.add_argument("--save", help="a test save whose boxed creatures are the inputs")
   r.add_argument("--slots", help="their storage slots, comma separated")
   r.set_defaults(run=cmd_preview)


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the methods.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in combination.lines(p.structure) or ["no combination methods"]:
      print(line)
   return 0


def cmd_show(args: argparse.Namespace) -> int:
   """!Prints one method.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in combination.show_lines(p.structure, args.name):
      print(line)
   return 0


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds a method.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Add combination method"):
      combination.add_method(p.structure, args.name, args.count, args.at)
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes a method.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Remove combination method"):
      combination.remove_method(p.structure, args.name)
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames a method; the scripts follow once the renamed data compiled and was saved.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Rename combination method"):
      places = combination.rename_method(p.structure, args.old, args.new, follow=False)
   for place in places:
      print(place if place.startswith("structure: ") else f"logic: {place}")   # B2: the nursery's method
   status = save_if_valid(p)
   if status == 0:
      for place in combination.follow_scripts(p.structure, args.old, args.new):
         print(place)
   return status


def cmd_move(args: argparse.Namespace) -> int:
   """!Moves a method.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Move combination method"):
      combination.move_method(p.structure, args.name, MOVES[args.direction])
   return save_if_valid(p)


def cmd_set(args: argparse.Namespace) -> int:
   """!Sets one of a method's keys.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   doc, name, key, value = p.structure, args.name, args.key, args.value
   setters = {"label": combination.set_label, "kind": combination.set_kind,
              "delivery": combination.set_delivery, "afterwards": combination.set_afterwards,
              "level": combination.set_level}
   with doc.edit(f"Combination {key}"):
      if key in setters:
         setters[key](doc, name, value)
      elif key == "allow_eggs":
         if value not in ON_OFF:
            raise CommandError("allow_eggs: on or off")
         combination.set_allow_eggs(doc, name, ON_OFF[value])
      else:
         combination.set_value(doc, name, key, value or None)
   return save_if_valid(p)


def cmd_count(args: argparse.Namespace) -> int:
   """!Sets the input count.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Combination inputs"):
      combination.set_count(p.structure, args.name, args.lo, args.hi if args.hi is not None else args.lo)
   return save_if_valid(p)


def cmd_slot(args: argparse.Namespace) -> int:
   """!Sets a slot's role or requirement.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Combination slot"):
      places = combination.set_slot(p.structure, args.name, args.slot, args.role, args.requires, args.no_requires)
   for place in places:
      print(f"followed: {place}")
   return save_if_valid(p)


def _cell_value(text: str) -> Any:
   """!A table key value: a number or a name.
   @param text  the argument
   @return the value
   """
   v = json_value(text)
   return v if isinstance(v, int) and not isinstance(v, bool) else text


def cmd_table(args: argparse.Namespace) -> int:
   """!Edits a table.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   doc, name, t, rest = p.structure, args.name, args.table, args.args
   want = {"add": 1, "remove": 0, "rename": 1, "key": 1, "symmetric": 1}
   if args.action in want and len(rest) != want[args.action]:
      raise CommandError(f"table {args.action} takes {want[args.action]} argument(s) after the table")
   with doc.edit(f"Combination table {args.action}"):
      if args.action == "add":
         combination.add_table(doc, name, t, rest[0])
      elif args.action == "remove":
         combination.remove_table(doc, name, t)
      elif args.action == "rename":
         combination.rename_table(doc, name, t, rest[0])
      elif args.action == "key":
         combination.set_table(doc, name, t, key=rest[0])
      elif args.action == "symmetric":
         if rest[0] not in ON_OFF:
            raise CommandError("symmetric: on or off")
         combination.set_table(doc, name, t, symmetric=ON_OFF[rest[0]])
      else:
         if len(rest) not in (CELL_PAIR_ARGS, CELL_VALUE_ARGS):
            raise CommandError("table cell T A B [VALUE]")
         value = _cell_value(rest[-1]) if len(rest) == CELL_VALUE_ARGS else None
         combination.set_cell(doc, name, t, _cell_value(rest[0]), _cell_value(rest[1]), value)
   return save_if_valid(p)


def matcher_of(text: str) -> Any:
   """!A recipe matcher from the command line.
   @param text  SPECIES, FIELD=VALUE or type=TYPE
   @return the manifest's matcher
   """
   if MATCH_SEP in text:
      key, value = text.split(MATCH_SEP, 1)
      return {key: _cell_value(value)}
   return text


def _pick(args: argparse.Namespace) -> dict[str, Any] | None:
   """!A pick from the options.
   @param args  parsed arguments
   @return the pick, or None when none is given
   """
   pick = {k: v for k, v in (("where", args.where), ("order", args.order), ("choose", args.choose),
                             ("else", args.otherwise)) if v is not None}
   return pick or None


def cmd_rule(args: argparse.Namespace) -> int:
   """!Edits the result rules.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   doc, name, rest = p.structure, args.name, args.args
   with doc.edit(f"Combination rule {args.action}"):
      if args.action == "add":
         if not rest or rest[0] not in combination.rule_kinds():
            raise CommandError(f"rule add KIND ... (KIND one of {', '.join(combination.rule_kinds())})")
         kind = rest[0]
         rule: dict[str, Any] = {}
         if kind == "recipe":
            if len(rest) != RECIPE_ARGS:
               raise CommandError("rule add recipe A,B,... RESULT")
            _kind, inputs, result = rest
            rule = {"recipe": [matcher_of(x) for x in inputs.split(",") if x], "result": result}
         elif kind == "table":
            if len(rest) != RULE_ONE_ARGS:
               raise CommandError("rule add table T")
            rule = {"table": rest[1]}
            if _pick(args) is not None:
               rule["pick"] = _pick(args)
         else:
            if len(rest) != RULE_ONE_ARGS:
               raise CommandError("rule add expression EXPR")
            rule = {"expression": rest[1]}
         if args.when:
            rule["when"] = args.when
         combination.add_rule(doc, name, rule)
      elif args.action == "remove":
         combination.remove_rule(doc, name, int(rest[0]) if rest else -1)
      elif args.action == "move":
         if len(rest) != RULE_INDEX_ARGS or rest[1] not in MOVES:
            raise CommandError("rule move K up|down")
         combination.move_rule(doc, name, int(rest[0]), MOVES[rest[1]])
      elif args.action == "when":
         if len(rest) != RULE_INDEX_ARGS:
            raise CommandError('rule when K EXPR ("" none)')
         combination.set_rule(doc, name, int(rest[0]), when=rest[1] or None)
      else:
         if len(rest) != 1:
            raise CommandError("rule pick K [--where E] [--order F] [--choose C] [--else E]")
         combination.set_rule(doc, name, int(rest[0]), pick=_pick(args))
   return save_if_valid(p)


def cmd_moves(args: argparse.Namespace) -> int:
   """!Sets the move chooser.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Combination moves"):
      combination.set_moves(p.structure, args.name, args.limit, args.chooser,
                            ON_OFF[args.fill] if args.fill is not None else None,
                            ON_OFF[args.push] if args.push is not None else None)
   return save_if_valid(p)


def cmd_source(args: argparse.Namespace) -> int:
   """!Adds, changes or removes a move source.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Combination move source"):
      if args.state == "remove":
         combination.remove_source(p.structure, args.name, args.kind)
      else:
         combination.set_source(p.structure, args.name, args.kind, ON_OFF[args.state], args.limit, args.all,
                                args.role)
   return save_if_valid(p)


def cmd_message(args: argparse.Namespace) -> int:
   """!Sets a moment's message.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Combination message"):
      combination.set_message(p.structure, args.name, args.moment, args.key)
   return save_if_valid(p)


def cmd_preview(args: argparse.Namespace) -> int:
   """!Prints what a combination gives.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   records: list[dict[str, Any]] = []
   for text in args.records:
      species, _sep, level = text.partition(LEVEL_SEP)
      records.append({"species": species, "level": int(level) if level else DEFAULT_LEVEL})
   if args.save is not None:
      save = inventory.open_testsave(p, args.save)
      boxed = {b.get("slot"): b for b in storage.boxed_of(save)}
      for slot in (args.slots or "").split(","):
         if slot.strip():
            if int(slot) not in boxed:
               raise CommandError(f"storage slot {slot} of {args.save} is empty")
            records.append(boxed[int(slot)])
   context: dict[str, Any] = {}
   for item in args.context:
      key, _sep, value = item.partition(MATCH_SEP)
      context[key] = _cell_value(value)
   out = combination.preview(p, args.name, records, context)
   print(combination.preview_text(out, records))
   return 0
