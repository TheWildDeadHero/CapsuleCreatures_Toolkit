"""!`capsule-studio battle FILE ...` Structure actions (D-23 §3.4): checking
the data against the game's target platforms, editing its stats and its
creature record (roles, party size, move slots).

    battle FILE validate [--platform P]     compile; without --platform for every target of the game
    battle FILE stat list                    the stats, their flags, and each target's "7/10 gba" budget
    battle FILE stat add NAME [--label L] [--formula F] [--at I] [--base N] [--pool] [--order]
                                             [--odds] [--no-stage] [--no-trait]
    battle FILE stat remove NAME
    battle FILE stat move NAME up|down
    battle FILE stat rename OLD NEW
    battle FILE stat set NAME KEY VALUE      KEY: label formula pool order odds stage trait transfer
                                             short
                                             (null puts the default back)
    battle FILE stat stages [STAGE TEXT]     the stages (as `stage list`); or set a stage's in-game label
    battle FILE role list                    the record's roles: ID, width x count, bits, default, transfer keys
    battle FILE role add NAME [--custom] [--width W] [--count N] [--default V] [--at I]
                                             an engine role, or (--custom) a custom role (--width required)
    battle FILE role remove NAME [--force]   --force: even though field scripts use it (role_get / role_set,
                                             record placeholders)
    battle FILE role move NAME up|down|INDEX
    battle FILE role rename OLD NEW [--force]
                                             custom roles only; --force as for remove
    battle FILE role set NAME KEY VALUE      KEY: width count default (null puts the default back)
    battle FILE role stored NAME on|off [--force]
                                             E13a: off = computed on read from its one derived or constant
                                             generation entry (no record bits, not hashed or transferred);
                                             --force as for remove (field scripts read an unstored role as 0)
    battle FILE role preview [--species S] [ROLE=V ...]
                                             every derived role of such a record (record_value() /
                                             rederive(), the engine's Python mirrors)
    battle FILE role import [--from BATTLE] [--species S] [ROLE=V ...]
                                             the record sent by BATTLE (default this data) and imported here
                                             with the derived roles it lacked re-derived (import_rederived())
    battle FILE layout [--party-size N] [--move-slots N]
                                             record bytes, hash and the budget of each target; or set them

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from ..core import battle
from ..core.structure import record, record_preview, stages, stats
from .battle_cmds import json_value, open_project, save_if_valid
from .main import CommandError

if TYPE_CHECKING:
   from ..core.document import Document

## `stat move` and `role move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## `role stored` values.
SWITCH = {"on": True, "off": False}


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("validate", help="compile with the engine's battle compiler, for every target platform of the "
                                     "game (its project.json \"targets\", default gba) or one")
   # Platform names are the engine's (checked when the command runs: the engine is found after parsing).
   q.add_argument("--platform", help="check against this platform's limits only (gba, desktop, headless, ...)")
   q.set_defaults(run=cmd_validate)
   q = s.add_parser("stat", help="the stats: list | add | remove | move | rename | set | stages")
   a = q.add_subparsers(dest="stat_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="every stat with its flags, and the stat budget of each target")
   r.set_defaults(run=cmd_stat_list)
   r = a.add_parser("add", help="add a stat (every species gets a base value for it)")
   r.add_argument("name")
   r.add_argument("--label", help="in-game text (default: the name)")
   r.add_argument("--formula", help="ruleset stat formula (default: the first non-pool stat's)")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.add_argument("--base", type=int, default=battle.NEW_BASE_STAT, help="every species' base value")
   r.add_argument("--pool", action="store_true", help="make it the pool stat (hit points)")
   r.add_argument("--order", action="store_true", help="make it the order stat (turn order, escape)")
   r.add_argument("--odds", action="store_true", help="make it the odds stat (the effect_odds pipeline's "
                                                       "user_stat / target_stat)")
   r.add_argument("--no-stage", action="store_true", help="the stat has no stage")
   r.add_argument("--no-trait", action="store_true", help="traits leave the stat alone")
   r.set_defaults(run=cmd_stat_add)
   r = a.add_parser("remove", help="remove a stat no category or stage effect names")
   r.add_argument("name")
   r.set_defaults(run=cmd_stat_remove)
   r = a.add_parser("move", help="move a stat up or down (its index), with every species' base value")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_stat_move)
   r = a.add_parser("rename", help="rename a stat and what names it (categories, traits, stage effects)")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_stat_rename)
   r = a.add_parser("set", help=f"change a stat: KEY one of {', '.join(stats.STAT_KEYS)}; VALUE JSON (null: "
                                "the default)")
   r.add_argument("name")
   r.add_argument("key", choices=stats.STAT_KEYS)
   r.add_argument("value")
   r.set_defaults(run=cmd_stat_set)
   r = a.add_parser("stages", help="the stages in index order (as `stage list`); STAGE TEXT sets a stage's in-game "
                                   "label")
   r.add_argument("stage", nargs="?", help="a stage name")
   r.add_argument("text", nargs="?")
   r.set_defaults(run=cmd_stat_stages)
   _register_record(s)


def _register_record(s: argparse._SubParsersAction) -> None:
   """!Adds the record actions (role, layout).
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("role", help="the creature record's roles: list | add | remove | move | rename | set")
   a = q.add_subparsers(dest="role_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="every role: ID, width x count, bits, default, transfer keys")
   r.set_defaults(run=cmd_role_list)
   r = a.add_parser("add", help="add an engine role, or a custom role with --custom")
   r.add_argument("name")
   r.add_argument("--custom", action="store_true", help="a custom role (a field scripts read and write)")
   r.add_argument("--width", type=int, help="bits per element (required for a custom role)")
   r.add_argument("--count", type=int, help="elements (custom roles; engine roles whose count is chosen)")
   r.add_argument("--default", type=int, help="a custom role's initial value (default 0)")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_role_add)
   r = a.add_parser("remove", help="remove a role battles do not need (refused while field scripts use it)")
   r.add_argument("name")
   r.add_argument("--force", action="store_true", help="remove it even though field scripts use it")
   r.set_defaults(run=cmd_role_remove)
   r = a.add_parser("move", help="move a role up, down or to a position (its bit offset; a custom role's ID)")
   r.add_argument("name")
   r.add_argument("where", help="up, down or a position")
   r.set_defaults(run=cmd_role_move)
   r = a.add_parser("rename", help="rename a custom role (refused while field scripts use it)")
   r.add_argument("old")
   r.add_argument("new")
   r.add_argument("--force", action="store_true", help="rename it even though field scripts use it")
   r.set_defaults(run=cmd_role_rename)
   r = a.add_parser("set", help=f"change a role: KEY one of {', '.join(record.ROLE_PROPERTIES)}; VALUE a number "
                                "or null (the default)")
   r.add_argument("name")
   r.add_argument("key", choices=record.ROLE_PROPERTIES)
   r.add_argument("value")
   r.set_defaults(run=cmd_role_set)
   r = a.add_parser("stored", help="whether the record holds a custom role (off: computed on read, E13a)")
   r.add_argument("name")
   r.add_argument("value", choices=list(SWITCH))
   r.add_argument("--force", action="store_true", help="even though field scripts use it (they read it as 0)")
   r.set_defaults(run=cmd_role_stored)
   r = a.add_parser("preview", help="every derived role of a record of these values (ROLE=V, the rest 0)")
   r.add_argument("values", nargs="*")
   r.add_argument("--species", help="its species (whose fields species.NAME reads)")
   r.set_defaults(run=cmd_role_preview)
   r = a.add_parser("import", help="a record transferred from a battle data and imported here")
   r.add_argument("values", nargs="*")
   r.add_argument("--species", help="its species")
   r.add_argument("--from", dest="sender", help="the sending battle.json (default: this battle data)")
   r.set_defaults(run=cmd_role_import)
   q = s.add_parser("layout", help="the record's bytes, hash and budget per target; --party-size / --move-slots "
                                   "set them (the layout becomes the object form)")
   q.add_argument("--party-size", type=int, help="creatures a party holds")
   q.add_argument("--move-slots", type=int, help="moves a creature knows")
   q.set_defaults(run=cmd_layout)


def cmd_validate(args: argparse.Namespace) -> int:
   """!Compiles for each target and reports.
   @param args  parsed arguments
   @return 0, or 1 when the data does not compile for a target
   """
   p = open_project(args)
   if args.platform is not None and args.platform not in stats.platforms():
      raise CommandError(f"--platform: one of {', '.join(stats.platforms())}")
   targets = [args.platform] if args.platform else stats.project_targets(p.battle.path)
   status = 0
   for t in targets:
      error = p.validate(t)
      if error:
         print(f"{t}: {error}")
         status = 1
      else:
         print(f"battle data compiles ({t})")
   return status


def cmd_stat_list(args: argparse.Namespace) -> int:
   """!Prints the stats.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in stats.stats_report(p.battle, stats.project_targets(p.battle.path)):
      print(line)
   return 0


def cmd_stat_add(args: argparse.Namespace) -> int:
   """!Adds a stat.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   flags = {}
   for flag, on in (("pool", args.pool), ("order", args.order), ("odds", args.odds)):
      if on:
         flags[flag] = True
   for flag, off in (("stage", args.no_stage), ("trait", args.no_trait)):
      if off:
         flags[flag] = False
   with p.battle.edit("Add stat"):
      i = stats.add_stat(p.battle, args.name, args.label, args.formula, args.at, args.base,
                         stats.project_targets(p.battle.path), **flags)
   print(f"added stat {args.name!r} at {i}")
   return save_if_valid(p)


def cmd_stat_remove(args: argparse.Namespace) -> int:
   """!Removes a stat.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove stat"):
      stats.remove_stat(p.battle, args.name)
   return save_if_valid(p)


def cmd_stat_move(args: argparse.Namespace) -> int:
   """!Moves a stat.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move stat"):
      moved = stats.move_stat(p.battle, args.name, MOVES[args.direction])
   if not moved:
      raise CommandError(f"{args.name} is already at the {'top' if args.direction == 'up' else 'bottom'}")
   return save_if_valid(p)


def cmd_stat_rename(args: argparse.Namespace) -> int:
   """!Renames a stat.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Rename stat"):
      n = stats.rename_stat(p.battle, args.old, args.new)
   print(f"renamed; {n} reference(s) updated")
   return save_if_valid(p)


def cmd_stat_set(args: argparse.Namespace) -> int:
   """!Changes one property of a stat.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value = json_value(args.value)
   if args.key not in stats.FLAGS and value is not None:
      value = args.value   # texts stay texts ("1" is a label, not a number)
   with p.battle.edit("Set stat"):
      stats.set_stat(p.battle, args.name, args.key, value)
   return save_if_valid(p)


def cmd_stat_stages(args: argparse.Namespace) -> int:
   """!Prints the stages, or sets a stage's in-game label.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.stage is None:
      for row in stages.stage_list(p.battle):
         print(f"{row['index']} {row['name']}: {row['label']}")
      return 0
   if args.text is None:
      raise CommandError("stat stages STAGE TEXT")
   with p.battle.edit("Stage label"):
      stages.set_stage(p.battle, args.stage, "label", args.text)
   return save_if_valid(p)


# -- record ------------------------------------------------------------------------------------------------------------

def cmd_role_list(args: argparse.Namespace) -> int:
   """!Prints the roles.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for row in record.role_rows(p.battle):
      print(record.role_line(row))
   return 0


def cmd_role_add(args: argparse.Namespace) -> int:
   """!Adds a role.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.custom:
      if args.width is None:
         raise CommandError("a custom role needs --width")
      with p.battle.edit("Add custom role"):
         i = record.add_custom_role(p.battle, args.name, args.width, args.count, args.default, args.at)
   else:
      if args.default is not None:
         raise CommandError("--default is for custom roles (--custom)")
      with p.battle.edit("Add role"):
         i = record.add_engine_role(p.battle, args.name, args.at, args.width, args.count)
   print(f"added role {args.name!r} at {i}")
   return save_if_valid(p)


def _check_role_users(doc: Document, name: str, removing: bool, force: bool, storing: bool = False) -> None:
   """!Refuses to remove or rename a role the game's field scripts use (role_get / role_set, record
   placeholders) unless --force; with --force, says what will break.
   @param doc       battle Document
   @param name      role name
   @param removing  True for a removal (see record.role_users())
   @param force     --force was given
   @param storing   the role is stored again (record.role_users(storing=): the IDs move from its stored position)
   @return None
   @throws CommandError when the scripts use it and --force is not given
   """
   users = record.role_users(doc, name, removing, storing)
   if not users:
      return
   shown = "\n".join(users)
   if not force:
      raise CommandError(f"field scripts use the role {name!r} (not changed; --force to change it anyway):\n{shown}")
   print(f"warning: field scripts use the role {name!r}:\n{shown}")


def cmd_role_remove(args: argparse.Namespace) -> int:
   """!Removes a role.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   _check_role_users(p.battle, args.name, True, args.force)
   with p.battle.edit("Remove role"):
      record.remove_role(p.battle, args.name)
   return save_if_valid(p)


def cmd_role_move(args: argparse.Namespace) -> int:
   """!Moves a role.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move role"):
      if args.where in MOVES:
         moved = record.move_role(p.battle, args.name, MOVES[args.where])
      else:
         try:
            index = int(args.where)
         except ValueError:
            raise CommandError(f"move a role up, down or to a position (got {args.where!r})") from None
         moved = record.move_role_to(p.battle, args.name, index)
   if not moved:
      raise CommandError(f"{args.name} is already there")
   return save_if_valid(p)


def cmd_role_rename(args: argparse.Namespace) -> int:
   """!Renames a custom role.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.new != args.old:
      _check_role_users(p.battle, args.old, False, args.force)
   with p.battle.edit("Rename role"):
      record.rename_role(p.battle, args.old, args.new)
   return save_if_valid(p)


def cmd_role_set(args: argparse.Namespace) -> int:
   """!Changes one property of a role.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value = json_value(args.value)
   with p.battle.edit("Set role"):
      record.set_role(p.battle, args.name, args.key, value)
   return save_if_valid(p)


def cmd_role_stored(args: argparse.Namespace) -> int:
   """!Sets whether the record holds a custom role.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   _check_role_users(p.battle, args.name, True, args.force, SWITCH[args.value])
   with p.battle.edit("Role stored"):
      changed = record.set_stored(p.battle, args.name, SWITCH[args.value])
   if not changed:
      print(f"{args.name} is already {'stored' if SWITCH[args.value] else 'unstored'}")
   return save_if_valid(p)


def _role_values(values: list[str]) -> dict[str, int]:
   """!ROLE=V arguments.
   @param values  the arguments
   @return role -> value
   @throws CommandError for one that is not ROLE=number
   """
   out = {}
   for v in values:
      name, _sep, number = v.partition("=")
      try:
         out[name] = int(number, 0)
      except ValueError:
         raise CommandError(f"role values look like seed=12345, got {v!r}") from None
   return out


def cmd_role_preview(args: argparse.Namespace) -> int:
   """!Prints every derived role of a record.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   rows = record_preview.derived_rows(p, args.species, _role_values(args.values))
   for line in record_preview.derived_lines(rows):
      print(line)
   return 0


def cmd_role_import(args: argparse.Namespace) -> int:
   """!Prints a record transferred from a battle data and imported here.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   result = record_preview.transfer_preview(p, args.species, _role_values(args.values), args.sender)
   for line in record_preview.transfer_lines(result):
      print(line)
   return 0


def cmd_layout(args: argparse.Namespace) -> int:
   """!Prints the record's size, hash and budgets, after setting party size / move slots when given.
   @param args  parsed arguments
   @return 0, or 1 when a change does not compile
   """
   p = open_project(args)
   targets = stats.project_targets(p.battle.path)
   status = 0
   if args.party_size is not None or args.move_slots is not None:
      with p.battle.edit("Record layout"):
         if args.party_size is not None:
            record.set_party_size(p.battle, args.party_size, targets)
         if args.move_slots is not None:
            record.set_move_slots(p.battle, args.move_slots)
      status = save_if_valid(p)
   for line in record.layout_lines(p.battle, targets):
      print(line)
   return status
