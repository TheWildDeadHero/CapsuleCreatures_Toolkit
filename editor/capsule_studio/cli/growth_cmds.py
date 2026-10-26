"""!`capsule-studio battle FILE transform|form|yield|transformation|training ...` (D-26 section 4, engine G4): each
species' transformation rules, forms and training yields (core.species_growth), and the structure's transformation
and training sections (core.structure.transformation).

    battle FILE transform list SPECIES            its rules (the triggers each is looked at for), forms and yields
    battle FILE transform add SPECIES INTO WHEN [--on T,T] [--takes-item] [--also SPECIES] [--at I]
    battle FILE transform remove SPECIES I
    battle FILE transform move SPECIES I up|down  the first rule that holds wins
    battle FILE transform set SPECIES I into|when|on|takes_item|also VALUE   (null: left out)
    battle FILE transform preview SPECIES TRIGGER [--item ITEM] [--context NAME=V ...] [ROLE=V ...]
                                                  which rule fires (the engine's evaluator); ROLE.STAT=V for a
                                                  per-stat role (stat_training.hp=4)
    battle FILE form add SPECIES NAME [--when EXPR] [--on T,T]   (NAME base: the rule back to its own form)
    battle FILE form remove SPECIES NAME [--force]  (--force: even though saved records keep form numbers)
    battle FILE form rename SPECIES OLD NEW       effect logic `form WHO OLD` follows (unless another species
                                                  has a form OLD)
    battle FILE form set SPECIES NAME types|base|passives|front|back|when|on VALUE   (null: the species' own)
    battle FILE yield SPECIES [STAT VALUE]        its training yields (the training's yield fields)
    battle FILE transformation show               context values, cancel, blocked, learn, form role
    battle FILE transformation set cancel|blocked|learn|form_role VALUE        (null: left out)
    battle FILE transformation context add NAME [--values a,b] [--range LO,HI] [--default V]
    battle FILE transformation context remove NAME             (refused while a rule reads it)
    battle FILE transformation context set NAME values|range|default VALUE
    battle FILE training show
    battle FILE training on GAIN | off            GAIN: a ruleset formula taking (yield, value, total, level)
    battle FILE training set gain|stat_cap|total_cap|point VALUE   (point: a ruleset point every gain goes through)
    battle FILE training yield STAT FIELD|none    the species field holding the stat's yield
    battle FILE training preview FOE --level L [--values V,V,...]
                                                  what defeating FOE gives each stat (the engine's caps)

Choice lists are the engine's (battle_compiler TRIGGERS, UNCANCELLABLE, TRAIN_GAIN_ARGS). Manifest actions save
only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse
from typing import Any

from ..core import species_growth
from ..core.structure import transformation
from .battle_cmds import json_value, open_project, save_if_valid
from .main import CommandError

## `transform move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## The word for "no yield field" in `training yield STAT none`.
NO_FIELD = "none"
## Separator of a NAME=VALUE argument.
ASSIGN = "="
## Separator of a per-stat role's stat (ROLE.STAT=V).
STAT_SEPARATOR = "."


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the transform, form, yield, transformation and training actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("transform", help="a species' transformation rules: list | add | remove | move | set | preview")
   a = q.add_subparsers(dest="transform_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="a species' rules, forms and yields")
   r.add_argument("species")
   r.set_defaults(run=cmd_transform_list)
   r = a.add_parser("add", help="add a rule")
   r.add_argument("species")
   r.add_argument("into")
   r.add_argument("when")
   r.add_argument("--on", help=f"triggers, comma separated ({', '.join(species_growth.triggers())}); default: "
                               "every trigger the expression can hold for")
   r.add_argument("--takes-item", action="store_true", help="the held item is used up")
   r.add_argument("--also", help="a second creature made beside it")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_transform_add)
   r = a.add_parser("remove", help="remove a rule")
   r.add_argument("species")
   r.add_argument("index", type=int)
   r.set_defaults(run=cmd_transform_remove)
   r = a.add_parser("move", help="move a rule up or down")
   r.add_argument("species")
   r.add_argument("index", type=int)
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_transform_move)
   r = a.add_parser("set", help="set a rule's field (null: left out)")
   r.add_argument("species")
   r.add_argument("index", type=int)
   r.add_argument("field", choices=species_growth.TRANSFORM_FIELDS)
   r.add_argument("value")
   r.set_defaults(run=cmd_transform_set)
   r = a.add_parser("preview", help="which rule fires for a record in a trigger context")
   r.add_argument("species")
   r.add_argument("trigger", choices=species_growth.triggers())
   r.add_argument("--item", help="the context's item (item_use: used; trade: held)")
   r.add_argument("--context", action="append", default=[], help="NAME=VALUE (a number or a value name)")
   r.add_argument("roles", nargs="*", help="ROLE=VALUE or ROLE.STAT=VALUE")
   r.set_defaults(run=cmd_transform_preview)

   q = s.add_parser("form", help="a species' forms: add | remove | rename | set")
   a = q.add_subparsers(dest="form_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("add", help=f"add a form ({species_growth.base_form()}: the rule back to its own form)")
   r.add_argument("species")
   r.add_argument("name")
   r.add_argument("--when", help="the expression choosing it (none: effect logic only)")
   r.add_argument("--on", help="its triggers, comma separated")
   r.set_defaults(run=cmd_form_add)
   r = a.add_parser("remove", help="remove a form")
   r.add_argument("species")
   r.add_argument("name")
   r.add_argument("--force", action="store_true", help="even though saved records keep their form numbers")
   r.set_defaults(run=cmd_form_remove)
   r = a.add_parser("rename", help="rename a form (its effect logic follows)")
   r.add_argument("species")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_form_rename)
   r = a.add_parser("set", help="set a form's override or rule (null: the species' own)")
   r.add_argument("species")
   r.add_argument("name")
   r.add_argument("field", choices=species_growth.FORM_FIELDS)
   r.add_argument("value")
   r.set_defaults(run=cmd_form_set)

   r = s.add_parser("yield", help="a species' training yields, or set one")
   r.add_argument("species")
   r.add_argument("stat", nargs="?")
   r.add_argument("value", nargs="?")
   r.set_defaults(run=cmd_yield)

   q = s.add_parser("transformation", help="the structure's transformation section: show | set | context")
   a = q.add_subparsers(dest="transformation_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("show", help="the section and the context values")
   r.set_defaults(run=cmd_transformation_show)
   r = a.add_parser("set", help="set cancel (triggers), blocked (an expression), learn (true / false) or form_role")
   r.add_argument("field", choices=transformation.TRANSFORMATION_FIELDS)
   r.add_argument("value")
   r.set_defaults(run=cmd_transformation_set)
   r = a.add_parser("context", help="context values: add | remove | set")
   c = r.add_subparsers(dest="context_command", metavar="ACTION")
   c.required = True
   r = c.add_parser("add", help="add a context value")
   r.add_argument("name")
   r.add_argument("--values", help="value names, comma separated (value 0 first)")
   r.add_argument("--range", help="LO,HI")
   r.add_argument("--default", help="a number or a value name")
   r.set_defaults(run=cmd_context_add)
   r = c.add_parser("remove", help="remove a context value no rule reads")
   r.add_argument("name")
   r.set_defaults(run=cmd_context_remove)
   r = c.add_parser("set", help="set a context value's values, range or default (null: left out)")
   r.add_argument("name")
   r.add_argument("field", choices=transformation.CONTEXT_FIELDS)
   r.add_argument("value")
   r.set_defaults(run=cmd_context_set)

   q = s.add_parser("training", help="the structure's training values: show | on | off | set | yield | preview")
   a = q.add_subparsers(dest="training_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("show", help="the gain, the caps and the yield fields")
   r.set_defaults(run=cmd_transformation_show)
   r = a.add_parser("on", help="give the structure training values")
   r.add_argument("gain", help=f"a ruleset formula taking ({', '.join(transformation.gain_args())})")
   r.set_defaults(run=cmd_training_on)
   r = a.add_parser("off", help="remove the training section")
   r.set_defaults(run=cmd_training_off)
   r = a.add_parser("set", help="set the gain, a cap or the training point (null: the engine's default / none)")
   r.add_argument("field", choices=transformation.TRAINING_FIELDS)
   r.add_argument("value")
   r.set_defaults(run=cmd_training_set)
   r = a.add_parser("yield", help="the species field holding a stat's yield")
   r.add_argument("stat")
   r.add_argument("field", help=f"a species field, or {NO_FIELD}")
   r.set_defaults(run=cmd_training_yield)
   r = a.add_parser("preview", help="what defeating a foe gives each stat")
   r.add_argument("foe")
   r.add_argument("--level", type=int, required=True)
   r.add_argument("--values", help="the receiver's training values, comma separated (default 0)")
   r.set_defaults(run=cmd_training_preview)


def _assignments(texts: list[str], what: str) -> dict[str, Any]:
   """!NAME=VALUE arguments (ROLE.STAT=V: a per-stat role's stat).
   @param texts  the arguments
   @param what   their kind, for the message
   @return {name: value or {stat: value}}
   """
   out: dict[str, Any] = {}
   for text in texts:
      name, sep, value = text.partition(ASSIGN)
      if not sep or not name:
         raise CommandError(f"{what}: NAME=VALUE (got {text!r})")
      role, dot, stat = name.partition(STAT_SEPARATOR)
      if dot:
         out.setdefault(role, {})[stat] = json_value(value)
      else:
         out[name] = json_value(value)
   return out


def cmd_transform_list(args: argparse.Namespace) -> int:
   """!Prints a species' rules, forms and yields.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in species_growth.lines(p.battle, args.species):
      print(line)
   return 0


def cmd_transform_add(args: argparse.Namespace) -> int:
   """!Adds a rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add transformation"):
      i = species_growth.add_transform(p.battle, args.species, args.into, args.when, args.on, args.takes_item,
                                       args.also, args.at)
   print(f"added rule {i}: {args.species} -> {args.into}")
   return save_if_valid(p)


def cmd_transform_remove(args: argparse.Namespace) -> int:
   """!Removes a rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove transformation"):
      species_growth.remove_transform(p.battle, args.species, args.index)
   return save_if_valid(p)


def cmd_transform_move(args: argparse.Namespace) -> int:
   """!Moves a rule.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Move transformation"):
      moved = species_growth.move_transform(p.battle, args.species, args.index, MOVES[args.direction])
   if not moved:
      raise CommandError(f"rule {args.index} is already at the {'top' if args.direction == 'up' else 'bottom'}")
   return save_if_valid(p)


def cmd_transform_set(args: argparse.Namespace) -> int:
   """!Sets a rule's field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value = args.value if args.field == species_growth.WHEN_KEY else json_value(args.value)
   with p.battle.edit("Set transformation"):
      species_growth.set_transform(p.battle, args.species, args.index, args.field, value)
   return save_if_valid(p)


def cmd_transform_preview(args: argparse.Namespace) -> int:
   """!Prints which rule fires, then every rule of the species with whether it listens and holds.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   result = species_growth.preview(p.battle, args.species, _assignments(args.roles, "role"), args.trigger, args.item,
                                   _assignments(args.context, "context"))
   print(f"{args.species} on {args.trigger}: {result['text']}")
   for r in result["rules"]:
      state = "holds" if r["holds"] else "does not hold"
      listens = "" if r["listens"] else f" (not looked at on {args.trigger})"
      print(f"  {r['owner']}: {r['when']} {state}{listens}")
   return 0


def cmd_form_add(args: argparse.Namespace) -> int:
   """!Adds a form.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add form"):
      species_growth.add_form(p.battle, args.species, args.name, args.when, args.on)
   return save_if_valid(p)


def cmd_form_remove(args: argparse.Namespace) -> int:
   """!Removes a form.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   # C6 (review4 finding 13): saved records keep their form numbers, as with passive slots
   warning = species_growth.form_removal_warning(p.battle, args.species, args.name)
   if warning is not None and not args.force:
      raise CommandError(f"{warning} (not changed; --force to remove it anyway)")
   if warning is not None:
      print(f"warning: {warning}")
   with p.battle.edit("Remove form"):
      species_growth.remove_form(p.battle, args.species, args.name)
   return save_if_valid(p)


def cmd_form_rename(args: argparse.Namespace) -> int:
   """!Renames a form.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Rename form"):
      n = species_growth.rename_form(p.battle, args.species, args.old, args.new)
   print(f"renamed; {n} effect logic reference(s) updated")
   return save_if_valid(p)


def cmd_form_set(args: argparse.Namespace) -> int:
   """!Sets a form's field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value = args.value if args.field == species_growth.WHEN_KEY else json_value(args.value)
   with p.battle.edit("Set form"):
      species_growth.set_form(p.battle, args.species, args.name, args.field, value)
   return save_if_valid(p)


def cmd_yield(args: argparse.Namespace) -> int:
   """!Prints a species' yields, or sets one.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.stat is None or args.value is None:
      if args.stat is not None:
         raise CommandError("give the value too (null: the field's default)")
      for y in species_growth.yields(p.battle, args.species):
         print(f"{y['stat']} {y['value']} ({y['field']}" + ("" if y["own"] else ", default") + ")")
      return 0
   with p.battle.edit("Set yield"):
      species_growth.set_yield(p.battle, args.species, args.stat, json_value(args.value))
   return save_if_valid(p)


def cmd_transformation_show(args: argparse.Namespace) -> int:
   """!Prints the transformation and training sections.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in transformation.lines(p.structure):
      print(line)
   return 0


def cmd_transformation_set(args: argparse.Namespace) -> int:
   """!Sets a transformation field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value = args.value if args.field == transformation.BLOCKED_KEY else json_value(args.value)
   with p.structure.edit("Set transformation"):
      transformation.set_transformation(p.structure, args.field, value)
   return save_if_valid(p)


def cmd_context_add(args: argparse.Namespace) -> int:
   """!Adds a context value.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   values = [v.strip() for v in args.values.split(",") if v.strip()] if args.values else None
   rng = None
   if args.range:
      try:
         lo, hi = (int(v) for v in args.range.split(","))
      except ValueError:
         raise CommandError(f"--range: LO,HI (got {args.range!r})") from None
      rng = (lo, hi)
   default = json_value(args.default) if args.default is not None else None
   with p.structure.edit("Add context value"):
      transformation.add_context(p.structure, args.name, values, rng, default)
   return save_if_valid(p)


def cmd_context_remove(args: argparse.Namespace) -> int:
   """!Removes a context value.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Remove context value"):
      transformation.remove_context(p.structure, args.name)
   return save_if_valid(p)


def cmd_context_set(args: argparse.Namespace) -> int:
   """!Sets a context value's field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value = json_value(args.value)
   if args.field == transformation.VALUES_KEY:
      warning = transformation.context_order_warning(p.structure, args.name, value)   # C6 (review4 finding 24)
      if warning is not None:
         print(f"warning: {warning}")
   with p.structure.edit("Set context value"):
      transformation.set_context(p.structure, args.name, args.field, value)
   return save_if_valid(p)


def cmd_training_on(args: argparse.Namespace) -> int:
   """!Gives the structure training.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Training on"):
      transformation.enable_training(p.structure, args.gain)
   return save_if_valid(p)


def cmd_training_off(args: argparse.Namespace) -> int:
   """!Removes the training section.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Training off"):
      transformation.disable_training(p.structure)
   return save_if_valid(p)


def cmd_training_set(args: argparse.Namespace) -> int:
   """!Sets the gain or a cap.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Set training"):
      transformation.set_training(p.structure, args.field, json_value(args.value))
   return save_if_valid(p)


def cmd_training_yield(args: argparse.Namespace) -> int:
   """!Names a stat's yield field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Training yield"):
      transformation.set_yield_field(p.structure, args.stat, None if args.field == NO_FIELD else args.field)
   return save_if_valid(p)


def cmd_training_preview(args: argparse.Namespace) -> int:
   """!Prints what defeating a foe gives each stat.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   values = None
   if args.values:
      try:
         values = [int(v) for v in args.values.split(",")]
      except ValueError:
         raise CommandError(f"--values: whole numbers, comma separated (got {args.values!r})") from None
   result = species_growth.training_preview(p.battle, args.foe, args.level, values)
   for name, before, gain, after in zip(result["stats"], result["before"], result["gain"], result["after"]):
      if gain:
         print(f"{name}: {before} + {gain} = {after}")
   if not any(result["gain"]):
      print(f"defeating {args.foe} gives nothing (its yields, or the caps)")
   return 0
