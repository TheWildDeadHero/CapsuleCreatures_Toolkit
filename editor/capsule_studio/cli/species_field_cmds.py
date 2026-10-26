"""!`capsule-studio battle FILE species-field ...` (engine E13a): the structure
manifest's species fields and each species' values of them
(core.structure.species_fields).

    battle FILE species-field list                every field (width, values, default, species giving their own,
                                                  derived entries reading it), then the count against the limit
    battle FILE species-field add NAME --width W [--default V] [--at I]
                                                  a field every species has (derived expressions: species.NAME)
    battle FILE species-field remove NAME         the species' values go too (refused while a derived
                                                  expression reads it)
    battle FILE species-field rename OLD NEW      the species' values and the derived expressions follow
    battle FILE species-field move NAME up|down
    battle FILE species-field set NAME width|default VALUE
                                                  (default null: 0, nothing written)
    battle FILE species-field value SPECIES [FIELD [VALUE]]
                                                  a species' values; set one (null or the field's default: the
                                                  species follows the default; a value name of a named field)
    battle FILE species-field values NAME [A,B,C] B1: a field's value names (value k the k-th; "" none)
    battle FILE species-field rename-value NAME OLD NEW
                                                  B1: one value name; species, the default and the combination
                                                  methods follow

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core.structure import species_fields
from .battle_cmds import json_value, open_project, save_if_valid
from .main import CommandError

## `species-field move` directions and their deltas.
MOVES = {"up": -1, "down": 1}


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the species-field action to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("species-field", help="numeric data columns of every species, read by derived expressions as "
                                          "species.NAME: list | add | remove | rename | move | set | value")
   a = q.add_subparsers(dest="species_field_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="every species field")
   r.set_defaults(run=cmd_list)
   r = a.add_parser("add", help="add a species field")
   r.add_argument("name")
   r.add_argument("--width", type=int, required=True, help="bits (1 to the engine's MAX_SPECIES_FIELD_BITS)")
   r.add_argument("--default", type=int, help="the value of a species that gives none (default 0)")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_add)
   r = a.add_parser("remove", help="remove a species field and the species' values of it")
   r.add_argument("name")
   r.set_defaults(run=cmd_remove)
   r = a.add_parser("rename", help="rename a species field; species and derived expressions follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename)
   r = a.add_parser("move", help="move a species field up or down")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_move)
   r = a.add_parser("set", help=f"change a field: KEY one of {', '.join(species_fields.FIELD_PROPERTIES)}; VALUE a "
                                "number or null")
   r.add_argument("name")
   r.add_argument("key", choices=species_fields.FIELD_PROPERTIES)
   r.add_argument("value")
   r.set_defaults(run=cmd_set)
   r = a.add_parser("value", help="a species' field values, or set one (null: the field's default)")
   r.add_argument("species")
   r.add_argument("field", nargs="?")
   r.add_argument("value", nargs="?")
   r.set_defaults(run=cmd_value)
   r = a.add_parser("values", help="a field's value names (B1: group fields such as a race), or set them")
   r.add_argument("name")
   r.add_argument("names", nargs="?", help="comma separated (\"\": none)")
   r.set_defaults(run=cmd_values)
   r = a.add_parser("rename-value", help="rename one value name; species and combination methods follow")
   r.add_argument("name")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename_value)


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the species fields.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in species_fields.lines(p.structure):
      print(line)
   return 0


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds a species field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Add species field"):
      i = species_fields.add_field(p.structure, args.name, args.width, args.default, args.at)
   print(f"added species field {args.name!r} at {i}")
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes a species field and lists the species that lost their value.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Remove species field"):
      lost = species_fields.remove_field(p.structure, args.name)
   for line in lost:
      print(f"lost its value: {line}")
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames a species field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Rename species field"):
      n = species_fields.rename_field(p.structure, args.old, args.new)
   print(f"renamed; {n} species / derived entries updated")
   return save_if_valid(p)


def cmd_move(args: argparse.Namespace) -> int:
   """!Moves a species field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Move species field"):
      moved = species_fields.move_field(p.structure, args.name, MOVES[args.direction])
   if not moved:
      raise CommandError(f"{args.name} is already at the {'top' if args.direction == 'up' else 'bottom'}")
   return save_if_valid(p)


def cmd_set(args: argparse.Namespace) -> int:
   """!Changes a field's width or default.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Set species field"):
      species_fields.set_field(p.structure, args.name, args.key, json_value(args.value))
   return save_if_valid(p)


def cmd_value(args: argparse.Namespace) -> int:
   """!Prints a species' field values, or sets one.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.field is None or args.value is None:
      if args.field is not None:
         raise CommandError("give the value too (null: the field's default)")
      for v in species_fields.values_of(p.battle, args.species):
         print(f"{v['name']} {v['value']}" + ("" if v["own"] else " (default)"))
      return 0
   with p.battle.edit("Species field value"):
      species_fields.set_value(p.battle, args.species, args.field, json_value(args.value))
   return save_if_valid(p)


def cmd_values(args: argparse.Namespace) -> int:
   """!Prints a field's value names, or sets them.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.names is None:
      f = next((x for x in species_fields.fields(p.structure) if x["name"] == args.name), None)
      if f is None:
         raise CommandError(f"no species field {args.name!r}")
      print(", ".join(f["values"]) or "no value names")
      return 0
   with p.structure.edit("Species field values"):
      species_fields.set_values(p.structure, args.name, args.names)
   return save_if_valid(p)


def cmd_rename_value(args: argparse.Namespace) -> int:
   """!Renames one of a field's value names.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Rename species field value"):
      n = species_fields.rename_value(p.structure, args.name, args.old, args.new)
   print(f"renamed; {n} places updated")
   return save_if_valid(p)
