"""!`capsule-studio battle FILE ...` actions for the formats, the turn
structure, the progression rules and the record's transfer defaults
(D-23 §3.4 `battle turn|learn|exp|generation show|set`;
core.structure.turn, core.structure.progression, core.structure.record).

    battle FILE format list
    battle FILE format add NAME [--copy OTHER] [--at I] | remove NAME | rename OLD NEW | move NAME up|down
    battle FILE format sides NAME COUNT COUNT...      positions per side (numbered side by side)
    battle FILE format place NAME POSITION X Y | stand NAME SIDE X Y | stands NAME --clear
    battle FILE format set NAME range|party_max|on_target_fainted VALUE       (null: the default)
    battle FILE turn show
    battle FILE turn bracket NAME VALUE              run / switch / item / move: a number, "priority" (move), null
    battle FILE turn set tie|switching.send_out|switching.switch_in WORD       (null: the default)
    battle FILE turn order SOURCE up|down | order --set S S ... | order --default
    battle FILE turn phase add RUN [--at I] | remove I | move I up|down | sources I [S ...] | each I WORD|null
                                                     (RUN: the engine's END_PHASES: weather, battlers, sides,
                                                     field, regen, delayed (E13b: lands `delay`), ...)
    battle FILE turn reset brackets|tie|end_of_turn|effect_order|switching|turn
    battle FILE learning|exp show | set KEY WORD|null   (`learn` adds a learnset entry: battle_cmds)
    battle FILE generation show | add ROLE [--way W] [--at I] | remove I | move I up|down | role I ROLE |
                           way I W | random I LO HI | order I high_first|low_first|null |
                           constant I V | derived I EXPR [--range LO HI] |
                           preview I [NAME=V ...] [--element E] [--species S] | reset
                           (order, E13a: which half a wide range draws first; --species: the species
                           whose fields species.NAME reads, else the fields' defaults)
    battle FILE transfer list | set STAT VALUE [--role R] | clear STAT [--role R]

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core import engine
from ..core.structure import progression, record, turn
from .battle_cmds import json_value, open_project, save_if_valid
from .main import CommandError

## `move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## Names of a derived range's two numbers.
RANGE_METAVAR = ("LO", "HI")
## The word that gives a value back to the engine's default.
NULL_WORD = "null"


def _phase_help() -> str:
   """!The help of a phase argument: the engine's END_PHASES (E13b: delayed), when the engine is found.
   @return help text
   """
   try:
      names = ", ".join(turn.end_phases())
   except engine.EngineNotFound:
      names = "the engine's END_PHASES"
   return f"{names} (`turn show` says what each runs)"


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   _register_format(s)
   _register_turn(s)
   for part, word in ((progression.LEARN_KEY, "learning"), (progression.EXP_KEY, "exp")):
      _register_policy(s, part, word)
   _register_generation(s)
   _register_transfer(s)


def _action(a: argparse._SubParsersAction, name: str, run: object, text: str,
            arguments: tuple[str, ...] = ()) -> argparse.ArgumentParser:
   """!Adds one action with positional arguments.
   @param a          the action subparsers
   @param name       its word
   @param run        its command function
   @param text       help text
   @param arguments  positional argument names
   @return its parser
   """
   r = a.add_parser(name, help=text)
   for arg in arguments:
      r.add_argument(arg)
   r.set_defaults(run=run)
   return r


def _register_format(s: argparse._SubParsersAction) -> None:
   """!Adds `format ...`.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("format", help="battle formats: list | add | remove | rename | move | sides | place | stand | "
                                   "stands | set")
   a = q.add_subparsers(dest="format_command", metavar="ACTION")
   a.required = True
   _action(a, "list", cmd_format_list, "the formats with their geometry")
   r = _action(a, "add", cmd_format_add, "add a format (two sides of one position, or --copy)", ("name",))
   r.add_argument("--copy", help="the format to copy")
   r.add_argument("--at", type=int, help="position (default: the end)")
   _action(a, "remove", cmd_format_remove, "remove a format nothing names", ("name",))
   _action(a, "rename", cmd_format_rename, "rename a format; references follow", ("old", "new"))
   r = _action(a, "move", cmd_format_move, "move a format up or down", ("name",))
   r.add_argument("direction", choices=list(MOVES))
   r = _action(a, "sides", cmd_format_sides, "positions per side, numbered side by side", ("name",))
   r.add_argument("counts", type=int, nargs="+")
   r = _action(a, "place", cmd_format_place, "a position's screen place", ("name",))
   for arg in ("index", "x", "y"):
      r.add_argument(arg, type=int)
   r.set_defaults(what=turn.LAYOUT_KEY)
   r = _action(a, "stand", cmd_format_place, "where a side's presenters stand", ("name",))
   for arg in ("index", "x", "y"):
      r.add_argument(arg, type=int)
   r.set_defaults(what=turn.STANDS_KEY)
   r = _action(a, "stands", cmd_format_stands, "drop the format's own stands (--clear)", ("name",))
   r.add_argument("--clear", action="store_true", required=True)
   r = _action(a, "set", cmd_format_set, "range, party_max or on_target_fainted (null: the default)", ("name",))
   r.add_argument("key", choices=[turn.RANGE_KEY, turn.PARTY_MAX_KEY, turn.FAINTED_KEY])
   r.add_argument("value")


def _register_turn(s: argparse._SubParsersAction) -> None:
   """!Adds `turn ...`.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("turn", help="the turn structure: show | bracket | set | order | phase | reset")
   a = q.add_subparsers(dest="turn_command", metavar="ACTION")
   a.required = True
   _action(a, "show", cmd_turn_show, "the turn structure ((default): the engine's)")
   _action(a, "bracket", cmd_turn_bracket, "an action bracket: a number, 'priority' (move) or null",
           ("name", "value"))
   r = _action(a, "set", cmd_turn_set, "the tie rule or a switching order (null: the default)")
   r.add_argument("key", choices=[turn.TIE_KEY, f"{turn.SWITCHING_KEY}.send_out", f"{turn.SWITCHING_KEY}.switch_in"])
   r.add_argument("value")
   r = _action(a, "order", cmd_turn_order, "the hook dispatch order: SOURCE up|down, --set S..., --default")
   r.add_argument("source", nargs="?")
   r.add_argument("direction", nargs="?", choices=list(MOVES))
   r.add_argument("--set", nargs="+", dest="order", help="every source once, in order")
   r.add_argument("--default", action="store_true", help="the engine's order")
   p = a.add_parser("phase", help="end-of-turn phases: add | remove | move | sources | each")
   pa = p.add_subparsers(dest="phase_command", metavar="ACTION")
   pa.required = True
   r = _action(pa, "add", cmd_phase_add, "add a phase")
   r.add_argument("phase", metavar="RUN", help=_phase_help())
   r.add_argument("--at", type=int, help="position (default: the end)")
   r = _action(pa, "remove", cmd_phase_remove, "remove a phase the engine does not need")
   r.add_argument("index", type=int)
   r = _action(pa, "move", cmd_phase_move, "move a phase earlier or later")
   r.add_argument("index", type=int)
   r.add_argument("direction", choices=list(MOVES))
   r = _action(pa, "sources", cmd_phase_sources, "a battlers phase's sources (none given: the effect order)")
   r.add_argument("index", type=int)
   r.add_argument("names", nargs="*")
   r = _action(pa, "each", cmd_phase_each, "for whom a sides / field phase runs (null: the default)")
   r.add_argument("index", type=int)
   r.add_argument("value")
   r = _action(a, "reset", cmd_turn_reset, "give a part back to the engine's default")
   r.add_argument("part", choices=[turn.BRACKETS_KEY, turn.TIE_KEY, turn.END_KEY, turn.ORDER_KEY, turn.SWITCHING_KEY,
                                   turn.TURN_KEY])


def _register_policy(s: argparse._SubParsersAction, part: str, word: str) -> None:
   """!Adds `learn ...` or `exp ...`.
   @param s     the battle group's subparsers
   @param part  progression.LEARN_KEY or EXP_KEY
   @param word  the command word
   @return None
   """
   q = s.add_parser(word, help=f"the {part}: show | set KEY WORD")
   q.set_defaults(part=part)
   a = q.add_subparsers(dest=f"{word}_command", metavar="ACTION")
   a.required = True
   _action(a, "show", cmd_policy_show, f"the {part} ((default): the engine's)")
   r = _action(a, "set", cmd_policy_set, "one setting (null: the default)", ("key", "value"))
   r.set_defaults(part=part)


def _register_generation(s: argparse._SubParsersAction) -> None:
   """!Adds `generation ...`.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("generation", help="how a new record is made, in draw order")
   a = q.add_subparsers(dest="generation_command", metavar="ACTION")
   a.required = True
   _action(a, "show", cmd_gen_show, "the entries, numbered in draw order, and the derived inputs")
   r = _action(a, "add", cmd_gen_add, "add an entry", ("role",))
   r.add_argument("--way", choices=list(progression.WAYS), default=progression.RANDOM_WAY)
   r.add_argument("--at", type=int, help="position in draw order (default: the end)")
   r = _action(a, "remove", cmd_gen_remove, "remove an entry")
   r.add_argument("index", type=int)
   r = _action(a, "move", cmd_gen_move, "move an entry in draw order")
   r.add_argument("index", type=int)
   r.add_argument("direction", choices=list(MOVES))
   r = _action(a, "role", cmd_gen_role, "the role an entry fills")
   r.add_argument("index", type=int)
   r.add_argument("role")
   r = _action(a, "way", cmd_gen_way, "how an entry fills it")
   r.add_argument("index", type=int)
   r.add_argument("way", choices=list(progression.WAYS))
   r = _action(a, "random", cmd_gen_random, "a random entry's range (hi may be max / last)", ("index", "lo", "hi"))
   r = _action(a, "order", cmd_gen_order, "a wide random range's draw order (null: the engine's default)")
   r.add_argument("index", type=int)
   # the orders are the engine's (WIDE_ORDERS: checked when the command runs, the engine is found after parsing)
   r.add_argument("order", help=f"high_first, low_first or {NULL_WORD}")
   r = _action(a, "constant", cmd_gen_constant, "a constant entry's value")
   r.add_argument("index", type=int)
   r.add_argument("value", type=int)
   r = _action(a, "derived", cmd_gen_derived, "a derived entry's expression")
   r.add_argument("index", type=int)
   r.add_argument("expr")
   r.add_argument("--range", type=int, nargs=len(RANGE_METAVAR), metavar=RANGE_METAVAR,
                  help="its range (default: the role's)")
   r = _action(a, "preview", cmd_gen_preview, "run a derived entry (inputs NAME=V, the rest 0)")
   r.add_argument("index", type=int)
   r.add_argument("values", nargs="*")
   r.add_argument("--element", type=int, default=0)
   r.add_argument("--species", help="the species whose fields the expression reads (default: the fields' "
                                    "defaults)")
   _action(a, "reset", cmd_gen_reset, "give the list back to the engine's default")


def _register_transfer(s: argparse._SubParsersAction) -> None:
   """!Adds `transfer ...`.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("transfer", help="what a record transfer gives a stat the sending game lacks")
   a = q.add_subparsers(dest="transfer_command", metavar="ACTION")
   a.required = True
   _action(a, "list", cmd_transfer_list, "the defaults per stat and per-stat role")
   r = _action(a, "set", cmd_transfer_set, "a stat's default (every per-stat role, or --role)", ("stat",))
   r.add_argument("value", type=int)
   r.add_argument("--role", help="one per-stat role")
   r = _action(a, "clear", cmd_transfer_set, "drop a stat's default (back to 0)", ("stat",))
   r.add_argument("--role", help="one per-stat role")
   r.set_defaults(value=None)


def _null(text: str) -> str | None:
   """!A word argument (NULL_WORD: None).
   @param text  argument
   @return the word, or None
   """
   return None if text == NULL_WORD else text


# -- formats -----------------------------------------------------------------------------------------------------------

def cmd_format_list(args: argparse.Namespace) -> int:
   """!Prints the formats.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)   # kept alive: helpers reach the project through the Document (a weak reference, S17)
   for line in turn.format_lines(p.battle):
      print(line)
   return 0


def cmd_format_add(args: argparse.Namespace) -> int:
   """!Adds a format.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add format"):
      name = turn.add_format(p.battle, args.name, args.copy, args.at)
   print(f"added format {name!r}")
   return save_if_valid(p)


def cmd_format_remove(args: argparse.Namespace) -> int:
   """!Removes a format.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove format"):
      turn.remove_format(p.battle, args.name)
   return save_if_valid(p)


def cmd_format_rename(args: argparse.Namespace) -> int:
   """!Renames a format.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Rename format"):
      n = turn.rename_format(p.battle, args.old, args.new)
   print(f"renamed; {n} reference(s) updated")
   return save_if_valid(p)


def cmd_format_move(args: argparse.Namespace) -> int:
   """!Moves a format.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move format"):
      turn.move_format(p.battle, args.name, MOVES[args.direction])
   return save_if_valid(p)


def cmd_format_sides(args: argparse.Namespace) -> int:
   """!Sets a format's sides.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Format sides"):
      turn.set_sides(p.battle, args.name, args.counts)
   return save_if_valid(p)


def cmd_format_place(args: argparse.Namespace) -> int:
   """!Moves a position's place or a side's stand.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Format place"):
      turn.set_place(p.battle, args.name, args.what, args.index, args.x, args.y)
   return save_if_valid(p)


def cmd_format_stands(args: argparse.Namespace) -> int:
   """!Drops a format's own stands.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Format stands"):
      turn.clear_stands(p.battle, args.name)
   return save_if_valid(p)


def cmd_format_set(args: argparse.Namespace) -> int:
   """!Sets a format field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"Format {args.key}"):
      turn.set_format_field(p.battle, args.name, args.key, json_value(args.value))
   return save_if_valid(p)


# -- turn --------------------------------------------------------------------------------------------------------------

def cmd_turn_show(args: argparse.Namespace) -> int:
   """!Prints the turn structure.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)   # kept alive (a weak reference from the Document, S17)
   for line in turn.turn_lines(p.battle):
      print(line)
   return 0


def cmd_turn_bracket(args: argparse.Namespace) -> int:
   """!Sets a bracket.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Turn bracket"):
      turn.set_bracket(p.battle, args.name, json_value(args.value))
   return save_if_valid(p)


def cmd_turn_set(args: argparse.Namespace) -> int:
   """!Sets the tie rule or a switching order.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"Turn {args.key}"):
      turn.set_choice(p.battle, args.key, _null(args.value))
   return save_if_valid(p)


def cmd_turn_order(args: argparse.Namespace) -> int:
   """!Changes the dispatch order.
   @param args  parsed arguments
   @return 0 or 1
   """
   given = sum(x for x in (args.source is not None, args.order is not None, args.default))
   if given != 1 or (args.source is not None and args.direction is None):
      raise CommandError("give SOURCE up|down, --set S ... or --default")
   p = open_project(args)
   with p.battle.edit("Effect order"):
      if args.default:
         turn.set_effect_order(p.battle, None)
      elif args.order is not None:
         turn.set_effect_order(p.battle, args.order)
      else:
         turn.move_source(p.battle, args.source, MOVES[args.direction])
   print(", ".join(turn.effect_order(p.battle)))
   return save_if_valid(p)


def cmd_phase_add(args: argparse.Namespace) -> int:
   """!Adds an end-of-turn phase.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add phase"):
      i = turn.add_phase(p.battle, args.phase, args.at)
   print(f"added phase {args.phase} at {i}")
   return save_if_valid(p)


def cmd_phase_remove(args: argparse.Namespace) -> int:
   """!Removes an end-of-turn phase.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove phase"):
      turn.remove_phase(p.battle, args.index)
   return save_if_valid(p)


def cmd_phase_move(args: argparse.Namespace) -> int:
   """!Moves an end-of-turn phase.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move phase"):
      turn.move_phase(p.battle, args.index, MOVES[args.direction])
   return save_if_valid(p)


def cmd_phase_sources(args: argparse.Namespace) -> int:
   """!Sets a battlers phase's sources.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Phase sources"):
      turn.set_phase_sources(p.battle, args.index, args.names or None)
   return save_if_valid(p)


def cmd_phase_each(args: argparse.Namespace) -> int:
   """!Sets for whom a sides / field phase runs.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Phase each"):
      turn.set_phase_each(p.battle, args.index, _null(args.value))
   return save_if_valid(p)


def cmd_turn_reset(args: argparse.Namespace) -> int:
   """!Gives a part of the turn back to the engine.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Reset turn"):
      changed = turn.reset(p.battle, args.part)
   print("reset" if changed else "already the engine's default")
   return save_if_valid(p)


# -- learn / exp_policy ------------------------------------------------------------------------------------------------

def cmd_policy_show(args: argparse.Namespace) -> int:
   """!Prints a policy with its choices.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)   # kept alive: the generation compile reads the ruleset's constants through it (S17)
   doc = p.battle
   value, left = progression.policy(doc, args.part)
   words = progression.choices()
   for k, v in value.items():
      print(f"{k}: {v}" + (" (default)" if k in left else "") + f"   [{' | '.join(words[f'{args.part}.{k}'])}]")
   error = progression.compile_progress(doc)[args.part]
   if error:
      print(f"error: {error}")
   return 0


def cmd_policy_set(args: argparse.Namespace) -> int:
   """!Sets one policy word.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(f"{args.part} {args.key}"):
      progression.set_policy(p.battle, f"{args.part}.{args.key}", _null(args.value))
   return save_if_valid(p)


# -- generation --------------------------------------------------------------------------------------------------------

def cmd_gen_show(args: argparse.Namespace) -> int:
   """!Prints the generation list and the derived inputs.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)   # kept: the helpers find the ruleset's constants through the project (a weak reference)
   doc = p.battle
   print("generation" + (" (default)" if progression.is_default(doc) else "") + ":")
   for row in progression.generation_rows(doc):
      print("  " + progression.row_text(row))
   print("derived inputs: " + ", ".join(progression.derived_inputs(doc)))
   print("constants: " + ", ".join(f"{k} {v}" for k, v in progression.derived_constants(doc).items()))
   return 0


def _gen_edit(args: argparse.Namespace, label: str, change: object) -> int:
   """!One generation edit, then save when it compiles.
   @param args    parsed arguments
   @param label   undo label
   @param change  callable(doc)
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit(label):
      change(p.battle)
   return save_if_valid(p)


def cmd_gen_add(args: argparse.Namespace) -> int:
   """!Adds a generation entry.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _gen_edit(args, "Add generation entry",
                    lambda doc: print(f"added at {progression.add_entry(doc, args.role, args.way, args.at)}"))


def cmd_gen_remove(args: argparse.Namespace) -> int:
   """!Removes a generation entry.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _gen_edit(args, "Remove generation entry", lambda doc: progression.remove_entry(doc, args.index))


def cmd_gen_move(args: argparse.Namespace) -> int:
   """!Moves a generation entry.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _gen_edit(args, "Move generation entry",
                    lambda doc: progression.move_entry(doc, args.index, MOVES[args.direction]))


def cmd_gen_role(args: argparse.Namespace) -> int:
   """!Changes the role an entry fills.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _gen_edit(args, "Generation role", lambda doc: progression.set_role(doc, args.index, args.role))


def cmd_gen_way(args: argparse.Namespace) -> int:
   """!Changes how an entry fills its role.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _gen_edit(args, "Generation way", lambda doc: progression.set_way(doc, args.index, args.way))


def cmd_gen_random(args: argparse.Namespace) -> int:
   """!Sets a random range.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _gen_edit(args, "Generation range",
                    lambda doc: progression.set_random(doc, int(args.index), args.lo, args.hi))


def cmd_gen_order(args: argparse.Namespace) -> int:
   """!Sets a wide random range's draw order.
   @param args  parsed arguments
   @return 0 or 1
   """
   order = None if args.order == NULL_WORD else args.order
   return _gen_edit(args, "Generation draw order", lambda doc: progression.set_order(doc, args.index, order))


def cmd_gen_constant(args: argparse.Namespace) -> int:
   """!Sets a constant.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _gen_edit(args, "Generation constant", lambda doc: progression.set_constant(doc, args.index, args.value))


def cmd_gen_derived(args: argparse.Namespace) -> int:
   """!Sets a derived expression.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _gen_edit(args, "Generation expression",
                    lambda doc: progression.set_derived(doc, args.index, args.expr, args.range))


def cmd_gen_preview(args: argparse.Namespace) -> int:
   """!Runs a derived entry.
   @param args  parsed arguments
   @return 0
   """
   values: dict[str, int] = {}
   for v in args.values:
      if "=" not in v:
         raise CommandError(f"inputs look like seed_lo=12, got {v!r}")
      k, x = v.split("=", 1)
      values[k] = int(x)
   p = open_project(args)   # kept alive: the preview reads the ruleset and the compiled data through it
   print(progression.preview(p.battle, args.index, values, args.element, args.species))
   return 0


def cmd_gen_reset(args: argparse.Namespace) -> int:
   """!Gives the generation list back to the engine.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _gen_edit(args, "Reset generation", progression.reset_generation)


# -- transfer defaults -------------------------------------------------------------------------------------------------

def cmd_transfer_list(args: argparse.Namespace) -> int:
   """!Prints the transfer defaults.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)   # kept alive (a weak reference from the Document, S17)
   for line in record.transfer_lines(p.battle):
      print(line)
   return 0


def cmd_transfer_set(args: argparse.Namespace) -> int:
   """!Sets or clears a transfer default.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Transfer default"):
      record.set_transfer_default(p.battle, args.stat, args.value, args.role)
   return save_if_valid(p)
