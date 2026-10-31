"""!`capsule-studio battle FILE ...` actions for the stages and the type chart
(D-23 §3.4 `battle stage|tier ...`; core.structure.stages, core.structure.chart).

    battle FILE stage list                    the stages in index order and the stage budget
    battle FILE stage add KIND [--name N] [--stat S] [--range LO HI] [--label L] [--at I]
                                              KIND: stat accuracy evasion crit
    battle FILE stage remove NAME             refused while effect logic names it
    battle FILE stage move NAME up|down
    battle FILE stage rename OLD NEW          effect logic follows
    battle FILE stage set NAME KEY VALUE      KEY: label stat range table formula (VALUE JSON; null: default)
    battle FILE stage mode NAME table|formula|none [FORMULA]
    battle FILE stage entry NAME STAGE VALUE  one table entry: num/den (odds n/m for the crit stage)
    battle FILE stage preview NAME [--value V]
    battle FILE tier list                     the tiers, the chart settings and the cells
    battle FILE tier add NAME [--q8 N | --decisive zero|ko] [--message KEY] [--at I]
    battle FILE tier remove NAME [--to TIER]  --to: the tier the cells (and the default) naming it take
    battle FILE tier move NAME up|down
    battle FILE tier rename OLD NEW           cells and the default follow
    battle FILE tier set NAME KEY VALUE       KEY: q8 decisive message shade (null: none / default)
    battle FILE tier option KEY VALUE         KEY: combine default types_per_species added_types above below
    battle FILE migrate                       pre-E6a stages and chart (rules tables, stage_names, a stat's
                                              stage flag, {attacker: {defender: multiplier}}) to the new keys

(`battle FILE chart ATTACKER DEFENDER TIER` sets a cell: cli/battle_cmds.py.)
Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core.structure import chart, stages, stats
from .battle_cmds import json_value, open_project, save_if_valid
from .main import CommandError

## `stage move` and `tier move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## Numbers of `stage add --range`.
RANGE_VALUES = 2


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   _register_stage(s)
   _register_tier(s)
   q = s.add_parser("migrate", help="turn pre-E6a stage and type chart data into the stages list and the chart "
                                    "tiers (saved when it compiles)")
   q.set_defaults(run=cmd_migrate)


def _register_stage(s: argparse._SubParsersAction) -> None:
   """!Adds `stage ...`.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("stage", help="the stages: list | add | remove | move | rename | set | mode | entry | preview")
   a = q.add_subparsers(dest="stage_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="the stages in index order, and the stage budget")
   r.set_defaults(run=cmd_stage_list)
   r = a.add_parser("add", help="add a stage (x1; a crit stage gets never-odds)")
   r.add_argument("kind", help="stat, accuracy, evasion or crit")
   r.add_argument("--name", help="its name (default: the stat's name, else the kind)")
   r.add_argument("--stat", help="the stat (kind stat)")
   r.add_argument("--range", nargs=RANGE_VALUES, type=int, metavar=("LO", "HI"))
   r.add_argument("--label", help="in-game text (default: the stat's label, else the name)")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_stage_add)
   r = a.add_parser("remove", help="remove a stage no effect logic names")
   r.add_argument("name")
   r.set_defaults(run=cmd_stage_remove)
   r = a.add_parser("move", help="move a stage up or down (its index)")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_stage_move)
   r = a.add_parser("rename", help="rename a stage and the effect logic naming it")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_stage_rename)
   r = a.add_parser("set", help=f"change a stage: KEY one of {', '.join(stages.STAGE_PROPERTIES)}; VALUE JSON "
                                "(null: the default)")
   r.add_argument("name")
   r.add_argument("key", choices=stages.STAGE_PROPERTIES)
   r.add_argument("value")
   r.set_defaults(run=cmd_stage_set)
   r = a.add_parser("mode", help="how a stage scales: by a table, a named formula, or not at all")
   r.add_argument("name")
   r.add_argument("mode", choices=stages.MODES)
   r.add_argument("formula", nargs="?", help="the named formula (mode formula)")
   r.set_defaults(run=cmd_stage_mode)
   r = a.add_parser("entry", help="set one table entry: STAGE (a value of the range) VALUE (num/den; n/m odds)")
   r.add_argument("name")
   r.add_argument("stage", type=int)
   r.add_argument("value")
   r.set_defaults(run=cmd_stage_entry)
   r = a.add_parser("preview", help="what the stage does at each value (the engine's evaluator)")
   r.add_argument("name")
   r.add_argument("--value", type=int, default=stages.PREVIEW_VALUE, help="the value scaled")
   r.set_defaults(run=cmd_stage_preview)


def _register_tier(s: argparse._SubParsersAction) -> None:
   """!Adds `tier ...`.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("tier", help="the type chart's tiers and settings: list | add | remove | move | rename | set | "
                                 "option")
   a = q.add_subparsers(dest="tier_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="the tiers, the chart settings and the cells that are not the default")
   r.set_defaults(run=cmd_tier_list)
   r = a.add_parser("add", help="add a tier: scaling (--q8, default 256 = x1) or decisive (--decisive)")
   r.add_argument("name")
   r.add_argument("--q8", type=int, help="the Q8 factor (256 = x1)")
   r.add_argument("--decisive", help="zero (no effect) or ko")
   r.add_argument("--message", help="a decisive tier's engine message key")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_tier_add)
   r = a.add_parser("remove", help="remove a tier (cells naming it need --to)")
   r.add_argument("name")
   r.add_argument("--to", help="the tier the cells (and the default) naming it take")
   r.set_defaults(run=cmd_tier_remove)
   r = a.add_parser("move", help="move a tier up or down the list")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_tier_move)
   r = a.add_parser("rename", help="rename a tier; the cells and the default follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_tier_rename)
   r = a.add_parser("set", help=f"change a tier: KEY one of {', '.join(chart.TIER_PROPERTIES)}; VALUE JSON "
                                "(null: none)")
   r.add_argument("name")
   r.add_argument("key", choices=chart.TIER_PROPERTIES)
   r.add_argument("value")
   r.set_defaults(run=cmd_tier_set)
   r = a.add_parser("option", help=f"change a chart setting: KEY one of {', '.join(chart.OPTIONS)}; VALUE JSON "
                                   "(null: the engine's default)")
   r.add_argument("key", choices=chart.OPTIONS)
   r.add_argument("value")
   r.set_defaults(run=cmd_tier_option)


# -- stages ------------------------------------------------------------------------------------------------------------

def cmd_stage_list(args: argparse.Namespace) -> int:
   """!Prints the stages.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in stages.report(p.battle, stats.project_targets(p.battle.path)):
      print(line)
   return 0


def cmd_stage_add(args: argparse.Namespace) -> int:
   """!Adds a stage.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add stage"):
      i = stages.add_stage(p.battle, args.kind, args.name, args.stat, args.range, args.at, args.label,
                           stats.project_targets(p.battle.path))
   print(f"added stage {stages.stage_list(p.battle)[i]['name']!r} at {i}")
   return save_if_valid(p)


def cmd_stage_remove(args: argparse.Namespace) -> int:
   """!Removes a stage.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove stage"):
      stages.remove_stage(p.battle, args.name)
   return save_if_valid(p)


def cmd_stage_move(args: argparse.Namespace) -> int:
   """!Moves a stage.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move stage"):
      moved = stages.move_stage(p.battle, args.name, MOVES[args.direction])
   if not moved:
      raise CommandError(f"{args.name} is already at the {'top' if args.direction == 'up' else 'bottom'}")
   return save_if_valid(p)


def cmd_stage_rename(args: argparse.Namespace) -> int:
   """!Renames a stage.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Rename stage"):
      n = stages.rename_stage(p.battle, args.old, args.new)
   print(f"renamed; {n} reference(s) updated")
   return save_if_valid(p)


def cmd_stage_set(args: argparse.Namespace) -> int:
   """!Changes one property of a stage.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value = json_value(args.value)
   if args.key in ("label", "stat", "formula") and value is not None:
      value = args.value   # texts stay texts
   with p.battle.edit("Set stage"):
      stages.set_stage(p.battle, args.name, args.key, value)
   return save_if_valid(p)


def cmd_stage_mode(args: argparse.Namespace) -> int:
   """!Chooses how a stage scales.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Stage mode"):
      stages.set_mode(p.battle, args.name, args.mode, args.formula, stages.formula_choices(p))
   return save_if_valid(p)


def cmd_stage_entry(args: argparse.Namespace) -> int:
   """!Sets one table entry.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Stage table"):
      stages.set_entry(p.battle, args.name, args.stage, json_value(args.value))
   return save_if_valid(p)


def cmd_stage_preview(args: argparse.Namespace) -> int:
   """!Prints what a stage does at each value.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for v, how, result in stages.preview(p, args.name, args.value):
      print(f"{v:+d} {how}: {result}" if v else f"0 {how}: {result}")
   return 0


# -- tiers -------------------------------------------------------------------------------------------------------------

def cmd_tier_list(args: argparse.Namespace) -> int:
   """!Prints the tiers, the settings and the cells.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in chart.report(p.battle):
      print(line)
   return 0


def cmd_tier_add(args: argparse.Namespace) -> int:
   """!Adds a tier.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add tier"):
      i = chart.add_tier(p.battle, args.name, args.q8, args.decisive, args.message, args.at)
   print(f"added tier {args.name!r} at {i}")
   return save_if_valid(p)


def cmd_tier_remove(args: argparse.Namespace) -> int:
   """!Removes a tier.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove tier"):
      n = chart.remove_tier(p.battle, args.name, args.to)
   if n:
      print(f"{n} cell(s) now name {args.to}")
   return save_if_valid(p)


def cmd_tier_move(args: argparse.Namespace) -> int:
   """!Moves a tier.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move tier"):
      moved = chart.move_tier(p.battle, args.name, MOVES[args.direction])
   if not moved:
      raise CommandError(f"{args.name} is already at the {'top' if args.direction == 'up' else 'bottom'}")
   return save_if_valid(p)


def cmd_tier_rename(args: argparse.Namespace) -> int:
   """!Renames a tier.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Rename tier"):
      n = chart.rename_tier(p.battle, args.old, args.new)
   print(f"renamed; {n} cell(s) updated")
   return save_if_valid(p)


def cmd_tier_set(args: argparse.Namespace) -> int:
   """!Changes one property of a tier.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Set tier"):
      chart.set_tier(p.battle, args.name, args.key, json_value(args.value))
   return save_if_valid(p)


def cmd_tier_option(args: argparse.Namespace) -> int:
   """!Changes one chart setting.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Chart setting"):
      chart.set_option(p.battle, args.key, json_value(args.value))
   return save_if_valid(p)


def cmd_migrate(args: argparse.Namespace) -> int:
   """!Migrates pre-E6a stage and chart data.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Migrate stages and chart"):
      done = stages.migrate_all(p.battle)
   print(f"migrated: {', '.join(done)}" if done else "nothing to migrate")
   return save_if_valid(p) if done else 0
