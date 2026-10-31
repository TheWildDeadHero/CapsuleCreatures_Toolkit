"""!`capsule-studio battle FILE ai ...` (engine G1, D-26 section 1): the battle's AI profiles (core.ai).

    battle FILE ai list                           every profile (default, rules, the parties using it)
    battle FILE ai show NAME                      its scoring, switching and item-use rules with their numbers
    battle FILE ai rules [--switching|--items]    the rule names and their numbers (ranges, defaults: the engine's)
    battle FILE ai hook                           the ai_score effect hook a hook rule runs (the engine's catalog)
    battle FILE ai add NAME [--like OTHER] [--at I]
    battle FILE ai remove NAME                    refused while a party names it
    battle FILE ai rename OLD NEW                 the parties and the bench scenarios naming it follow
    battle FILE ai move NAME up|down
    battle FILE ai default NAME                   the profile of a party naming none (records, unowned parties)
    battle FILE ai party PARTY [NAME | --default] the profile a party names (--default: none, the default one)
    battle FILE ai rule NAME add RULE [--switching] [--at I] [ARG=V ...]
    battle FILE ai rule NAME remove I [--switching]
    battle FILE ai rule NAME move I up|down [--switching]
    battle FILE ai rule NAME set I ARG V|default [--switching]
    battle FILE ai rule NAME add RULE --items [--item ITEM] [ARG=V ...]
                                                  G3: an item-use rule (below_hp, hook) naming an item used in
                                                  battle; remove / move / set take --items too
    battle FILE ai rule NAME item I ITEM          the item an item-use rule names
    battle FILE ai migrate                        the former party AI flags as profiles (tools/battle_ai.py)

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core import ai
from .battle_cmds import open_project, save_if_valid
from .main import CommandError

## `move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## The word `rule set` takes to put a number back to its default.
DEFAULT_WORD = "default"
## The separator of an ARG=V pair.
PAIR_SEPARATOR = "="


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the ai action to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("ai", help="AI profiles: list | show | rules | hook | add | remove | rename | move | default | "
                               "party | rule | migrate")
   a = q.add_subparsers(dest="ai_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="every AI profile").set_defaults(run=cmd_list)
   r = a.add_parser("show", help="a profile's rules")
   r.add_argument("name")
   r.set_defaults(run=cmd_show)
   r = a.add_parser("rules", help="the rule names and their numbers (the engine's)")
   r.add_argument("--switching", action="store_true", help="the switching rules")
   r.add_argument("--items", action="store_true", help="the item-use rules (G3)")
   r.set_defaults(run=cmd_rules)
   a.add_parser("hook", help="the ai_score effect hook").set_defaults(run=cmd_hook)
   r = a.add_parser("add", help="add a profile")
   r.add_argument("name")
   r.add_argument("--like", help="copy this profile's rules")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_add)
   r = a.add_parser("remove", help="remove a profile")
   r.add_argument("name")
   r.set_defaults(run=cmd_remove)
   r = a.add_parser("rename", help="rename a profile; parties and bench scenarios follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename)
   r = a.add_parser("move", help="move a profile up or down")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_move)
   r = a.add_parser("default", help="make a profile the default one")
   r.add_argument("name")
   r.set_defaults(run=cmd_default)
   r = a.add_parser("party", help="the profile a party names")
   r.add_argument("party")
   r.add_argument("name", nargs="?")
   r.add_argument("--default", action="store_true", help="name none: the default profile")
   r.set_defaults(run=cmd_party)
   r = a.add_parser("rule", help="a profile's rules: add | remove | move | set")
   r.add_argument("name")
   b = r.add_subparsers(dest="ai_rule_command", metavar="RULE_ACTION")
   b.required = True
   t = b.add_parser("add", help="add a rule")
   t.add_argument("rule")
   t.add_argument("numbers", nargs="*", metavar="ARG=V")
   t.add_argument("--at", type=int, help="position (default: the end)")
   t.add_argument("--switching", action="store_true", help="a switching rule")
   t.add_argument("--items", action="store_true", help="an item-use rule (G3)")
   t.add_argument("--item", help="an item-use rule's item (default: the first used in battle)")
   t.set_defaults(run=cmd_rule_add)
   t = b.add_parser("item", help="the item an item-use rule names")
   t.add_argument("index", type=int)
   t.add_argument("item")
   t.set_defaults(run=cmd_rule_item)
   t = b.add_parser("remove", help="remove a rule")
   t.add_argument("index", type=int)
   t.add_argument("--switching", action="store_true", help="a switching rule")
   t.add_argument("--items", action="store_true", help="an item-use rule (G3)")
   t.set_defaults(run=cmd_rule_remove)
   t = b.add_parser("move", help="move a rule up or down")
   t.add_argument("index", type=int)
   t.add_argument("direction", choices=list(MOVES))
   t.add_argument("--switching", action="store_true", help="a switching rule")
   t.add_argument("--items", action="store_true", help="an item-use rule (G3)")
   t.set_defaults(run=cmd_rule_move)
   t = b.add_parser("set", help="set a rule's number (default: back to the engine's)")
   t.add_argument("index", type=int)
   t.add_argument("arg")
   t.add_argument("value")
   t.add_argument("--switching", action="store_true", help="a switching rule")
   t.add_argument("--items", action="store_true", help="an item-use rule (G3)")
   t.set_defaults(run=cmd_rule_set)
   a.add_parser("migrate", help="turn the parties' former AI flags into profiles").set_defaults(run=cmd_migrate)


def _which(args: argparse.Namespace) -> str:
   """!The rule list an action edits.
   @param args  parsed arguments
   @return ai.RULES_KEY, ai.SWITCHING_KEY or ai.ITEMS_KEY
   """
   if getattr(args, "items", False):
      return ai.ITEMS_KEY
   return ai.SWITCHING_KEY if getattr(args, "switching", False) else ai.RULES_KEY


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the profiles.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in ai.lines(p.battle):
      print(line)
   left = ai.flag_parties(p.battle)
   if left:
      print(f"parties with former AI flags (ai migrate): {', '.join(left)}")
   return 0


def cmd_show(args: argparse.Namespace) -> int:
   """!Prints a profile's rules.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in ai.rule_lines(p.battle, args.name):
      print(line)
   return 0


def cmd_rules(args: argparse.Namespace) -> int:
   """!Prints the engine's rule names and numbers.
   @param args  parsed arguments
   @return 0
   """
   which = _which(args)
   for rule in ai.rule_kinds(which):
      numbers = ", ".join(f"{k} {lo}..{hi}" + (f" (default {d})" if d is not None else "")
                          for k, (lo, hi, d) in ai.rule_args(which, rule).items())
      print(f"{rule}" + (f": {numbers}" if numbers else ""))
   return 0


def cmd_hook(args: argparse.Namespace) -> int:
   """!Prints the ai_score hook's catalog entry.
   @param args  parsed arguments
   @return 0
   """
   h = ai.hook_entry()
   print(f"{h['name']}: {h['binds']}")
   print(f"owners: {', '.join(sorted(h['owners']))}; verdicts: {', '.join(sorted(h['results'])) or 'none'}; "
         f"pure: {'yes' if h.get('pure') else 'no'}")
   return 0


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds a profile.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add AI profile"):
      ai.add_profile(p.battle, args.name, args.like, args.at)
   print(f"added AI profile {args.name!r}")
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes a profile.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove AI profile"):
      ai.remove_profile(p.battle, args.name)
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames a profile.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Rename AI profile"):
      places = ai.rename_profile(p.battle, args.old, args.new)
   for place in places:
      print(f"bench: {place}")
   return save_if_valid(p)


def cmd_move(args: argparse.Namespace) -> int:
   """!Moves a profile.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move AI profile"):
      ai.move_profile(p.battle, args.name, MOVES[args.direction])
   return save_if_valid(p)


def cmd_default(args: argparse.Namespace) -> int:
   """!Marks the default profile.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Default AI profile"):
      ai.set_default(p.battle, args.name)
   return save_if_valid(p)


def cmd_party(args: argparse.Namespace) -> int:
   """!Prints or sets a party's profile.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.name is None and not args.default:
      name = ai.party_profile(p.battle, args.party)
      print(name if name is not None else f"{ai.default_name(p.battle)} (the default)")
      return 0
   if args.name is not None and args.default:
      raise CommandError("give a profile or --default, not both")
   with p.battle.edit("Party AI profile"):
      ai.set_party_profile(p.battle, args.party, None if args.default else args.name)
   return save_if_valid(p)


def _numbers(pairs: list[str]) -> dict[str, int]:
   """!ARG=V pairs as numbers.
   @param pairs  the command line's pairs
   @return {arg: value}
   @throws CommandError on a malformed pair
   """
   out = {}
   for pair in pairs:
      key, sep, value = pair.partition(PAIR_SEPARATOR)
      if not sep or not key:
         raise CommandError(f"a rule's number is ARG=V (got {pair!r})")
      try:
         out[key] = int(value, 0)
      except ValueError:
         raise CommandError(f"{key}: a whole number (got {value!r})") from None
   return out


def cmd_rule_add(args: argparse.Namespace) -> int:
   """!Adds a rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add AI rule"):
      ai.add_rule(p.battle, args.name, args.rule, _which(args), args.at, _numbers(args.numbers), args.item)
   return save_if_valid(p)


def cmd_rule_item(args: argparse.Namespace) -> int:
   """!Sets the item an item-use rule names.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Set AI rule item"):
      ai.set_rule_item(p.battle, args.name, args.index, args.item)
   return save_if_valid(p)


def cmd_rule_remove(args: argparse.Namespace) -> int:
   """!Removes a rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove AI rule"):
      ai.remove_rule(p.battle, args.name, args.index, _which(args))
   return save_if_valid(p)


def cmd_rule_move(args: argparse.Namespace) -> int:
   """!Moves a rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move AI rule"):
      ai.move_rule(p.battle, args.name, args.index, MOVES[args.direction], _which(args))
   return save_if_valid(p)


def cmd_rule_set(args: argparse.Namespace) -> int:
   """!Sets a rule's number.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value = None if args.value == DEFAULT_WORD else _numbers([f"{args.arg}{PAIR_SEPARATOR}{args.value}"])[args.arg]
   with p.battle.edit("Set AI rule"):
      ai.set_rule_arg(p.battle, args.name, args.index, args.arg, value, _which(args))
   return save_if_valid(p)


def cmd_migrate(args: argparse.Namespace) -> int:
   """!Turns the former party AI flags into profiles.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Migrate AI flags"):
      notes = ai.migrate_flags(p.battle)
   for note in notes or ["nothing to migrate"]:
      print(note)
   return save_if_valid(p) if notes else 0
