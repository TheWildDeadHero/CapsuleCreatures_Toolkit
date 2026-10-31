"""!`capsule-studio battle FILE field-action ...` (engine F2, D-27 section 3): the structure manifest's field actions
(core.structure.field_actions).

    battle FILE field-action list                     every action (requirement, target, prompt, script)
    battle FILE field-action add NAME SCRIPT [--target KIND [--name N]] [--at I]
    battle FILE field-action remove NAME
    battle FILE field-action rename OLD NEW           the game's scripts naming it follow
    battle FILE field-action move NAME up|down
    battle FILE field-action set NAME label|requires|ask|prompt|script VALUE      (ask on|off; "" : the default)
    battle FILE field-action target NAME KIND [TARGET]   behavior / object / tag with a name, or none
    battle FILE field-action check NAME EXPR          the engine's checks of a requirement (nothing is changed)
    battle FILE field-action choices                  the target names, scripts and requirement words to pick from
    battle FILE field-action preview PARTY [--set flag.NAME=1 ...]   who uses each action

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core.document import DocumentError
from ..core.structure import field_actions
from .battle_cmds import open_project, save_if_valid

## `move` directions and their deltas.
MOVES = {"up": -1, "down": 1}
## `ask` values.
SWITCH = {"on": True, "off": False}
## The record keys `set` writes.
SET_KEYS = ["label", "requires", "ask", "prompt", "script"]


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the field-action actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("field-action", help="field actions: list | add | remove | rename | move | set | target | "
                                         "check | choices | preview")
   a = q.add_subparsers(dest="field_action_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="every field action").set_defaults(run=cmd_list)
   r = a.add_parser("add", help="add a field action")
   r.add_argument("name")
   r.add_argument("script")
   r.add_argument("--target", choices=field_actions.target_kinds(), default=field_actions.MENU_TARGET)
   r.add_argument("--name", dest="target_name", help="the behavior, object kind or map tag")
   r.add_argument("--at", type=int, help="position (default: the end)")
   r.set_defaults(run=cmd_add)
   r = a.add_parser("remove", help="remove a field action")
   r.add_argument("name")
   r.set_defaults(run=cmd_remove)
   r = a.add_parser("rename", help="rename a field action; the game's scripts follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename)
   r = a.add_parser("move", help="move a field action up or down")
   r.add_argument("name")
   r.add_argument("direction", choices=list(MOVES))
   r.set_defaults(run=cmd_move)
   r = a.add_parser("set", help="one of a field action's keys")
   r.add_argument("name")
   r.add_argument("key", choices=SET_KEYS)
   r.add_argument("value")
   r.set_defaults(run=cmd_set)
   r = a.add_parser("target", help="what a field action is used on")
   r.add_argument("name")
   r.add_argument("kind", choices=field_actions.target_kinds())
   r.add_argument("target", nargs="?")
   r.set_defaults(run=cmd_target)
   r = a.add_parser("check", help="the engine's checks of a requirement")
   r.add_argument("name")
   r.add_argument("expr")
   r.set_defaults(run=cmd_check)
   a.add_parser("choices", help="what targets, scripts and requirements may name").set_defaults(run=cmd_choices)
   r = a.add_parser("preview", help="who uses each action, for one of the battle's parties")
   r.add_argument("party")
   r.add_argument("--set", action="append", default=[], metavar="flag.NAME=V", help="game state (default 0)")
   r.set_defaults(run=cmd_preview)


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the field actions.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for line in field_actions.lines(p.structure) or ["no field actions"]:
      print(line)
   return 0


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds a field action.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Add field action"):
      field_actions.add_action(p.structure, args.name, args.script, args.target, args.target_name, args.at)
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes a field action.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Remove field action"):
      field_actions.remove_action(p.structure, args.name)
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames a field action.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Rename field action"):
      field_actions.rename_action(p.structure, args.old, args.new, follow=False)
   # C8: the game's scripts (saved at once) follow only once the renamed battle data compiled and was saved
   status = save_if_valid(p)
   if status == 0:
      for place in field_actions.follow_scripts(p.structure, args.old, args.new):
         print(f"scripts: {place}")
   return status


def cmd_move(args: argparse.Namespace) -> int:
   """!Moves a field action.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Move field action"):
      field_actions.move_action(p.structure, args.name, MOVES[args.direction])
   return save_if_valid(p)


def cmd_set(args: argparse.Namespace) -> int:
   """!Sets one of a field action's keys.
   @param args  parsed arguments
   @return 0 or 1
   @throws DocumentError for an ask value other than on / off
   """
   p = open_project(args)
   doc, name, value = p.structure, args.name, args.value
   setters = {"label": lambda: field_actions.set_label(doc, name, value),
              "requires": lambda: field_actions.set_requires(doc, name, value),
              "prompt": lambda: field_actions.set_prompt(doc, name, value),
              "script": lambda: field_actions.set_script(doc, name, value)}
   with doc.edit(f"Field action {args.key}"):
      if args.key == "ask":
         if value not in SWITCH:
            raise DocumentError(f"ask: on or off (got {value!r})")
         field_actions.set_ask(doc, name, SWITCH[value])
      else:
         setters[args.key]()
   return save_if_valid(p)


def cmd_target(args: argparse.Namespace) -> int:
   """!Sets what a field action is used on.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.structure.edit("Field action target"):
      field_actions.set_target(p.structure, args.name, args.kind, args.target)
   return save_if_valid(p)


def cmd_check(args: argparse.Namespace) -> int:
   """!Prints the engine's verdict on a requirement.
   @param args  parsed arguments
   @return 0 when it compiles, else 1
   """
   p = open_project(args)
   error = field_actions.check_requirement(p.structure, args.name, args.expr)
   print(error or "ok")
   return 0 if error is None else 1


def cmd_choices(args: argparse.Namespace) -> int:
   """!Prints what targets, scripts and requirements may name.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for kind in field_actions.target_kinds():
      if kind != field_actions.MENU_TARGET:
         print(f"{kind}: {', '.join(field_actions.target_choices(p.structure, kind)) or '(none)'}")
   print(f"scripts: {', '.join(field_actions.script_names(p.structure)['script']) or '(no scripts manifest)'}")
   print(f"requirement words: {', '.join(field_actions.requirement_words(p.structure))}")
   return 0


def cmd_preview(args: argparse.Namespace) -> int:
   """!Prints who uses each action.
   @param args  parsed arguments
   @return 0
   @throws DocumentError for a --set that is not NAME=VALUE
   """
   p = open_project(args)
   game = {}
   for item in args.set:
      key, sep, value = item.partition("=")
      if not sep or not value.lstrip("-").isdigit():
         raise DocumentError(f"--set NAME=NUMBER (got {item!r})")
      game[key] = int(value)
   party = field_actions.party_records(p, args.party)
   for name, slot in field_actions.preview(p, party, game).items():
      who = f"member {slot} ({party[slot]['species']})" if slot is not None else "nobody"
      print(f"{name}: {who}")
   return 0
