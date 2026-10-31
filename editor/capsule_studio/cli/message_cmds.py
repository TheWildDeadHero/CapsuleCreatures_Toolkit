"""!`capsule-studio battle FILE message ...` (engine C4): the battle's
messages, the engine's and the ones the battle declares itself
(core.messages).

    battle FILE message list                every message in message id order: id, kind (required / optional /
                                            game), key, the placeholders it takes and its text ("-": an optional
                                            message the data leaves out); then the battle's own against the most
    battle FILE message show KEY            its text and what names it (effect logic, chart, condition texts)
    battle FILE message set KEY TEXT        its text (an optional engine message is added)
    battle FILE message add KEY [TEXT]      an optional engine message, or a message of the battle's own (a
                                            lower-case identifier; the next message id)
    battle FILE message remove KEY          not a required one, nor one something still names
    battle FILE message rename OLD NEW      a message of the battle's own; its uses follow

Editing actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse

from ..core import messages
from .battle_cmds import open_project, save_if_valid
from .main import CommandError

## What `message list` shows for an optional message the data leaves out (no id, no text).
ABSENT = "-"


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the message action to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("message", help="the battle's messages (the engine's and its own): list | show | set | add | "
                                    "remove | rename")
   a = q.add_subparsers(dest="message_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="every message in message id order")
   r.set_defaults(run=cmd_list)
   r = a.add_parser("show", help="one message's text and what names it")
   r.add_argument("key")
   r.set_defaults(run=cmd_show)
   r = a.add_parser("set", help="set a message's text")
   r.add_argument("key")
   r.add_argument("text")
   r.set_defaults(run=cmd_set)
   r = a.add_parser("add", help="add an optional engine message or one of the battle's own")
   r.add_argument("key")
   r.add_argument("text", nargs="?", help="its text (default: the template's, or empty)")
   r.set_defaults(run=cmd_add)
   r = a.add_parser("remove", help="remove a message nothing names (not a required one)")
   r.add_argument("key")
   r.set_defaults(run=cmd_remove)
   r = a.add_parser("rename", help="rename a message of the battle's own; its uses follow")
   r.add_argument("old")
   r.add_argument("new")
   r.set_defaults(run=cmd_rename)


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints every message and the budget of the battle's own.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for row in messages.rows(p.battle):
      ident = ABSENT if row["id"] is None else str(row["id"])
      text = ABSENT if row["text"] is None else repr(row["text"])
      takes = " ".join("{" + a + "}" for a in row["args"])
      print(f"{ident:>3} {row['kind']:<8} {row['key']}  [{takes}]  {text}")
   print(f"{len(messages.game_keys(p.battle))} of at most {messages.max_game_messages()} messages of the "
         f"battle's own")
   return 0


def cmd_show(args: argparse.Namespace) -> int:
   """!Prints one message and its uses.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   row = next((r for r in messages.rows(p.battle) if r["key"] == args.key), None)
   if row is None:
      raise CommandError(f"no message {args.key!r}")
   print(f"{row['key']} ({row['kind']}): {ABSENT if row['text'] is None else repr(row['text'])}")
   for where in messages.uses(p.battle, args.key):
      print(f"   used by {where}")
   return 0


def cmd_set(args: argparse.Namespace) -> int:
   """!Sets a message's text.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Set message"):
      messages.set_text(p.battle, args.key, args.text)
   return save_if_valid(p)


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds a message.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add message"):
      messages.add(p.battle, args.key, args.text)
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes a message.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove message"):
      messages.remove(p.battle, args.key)
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames a message of the battle's own.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Rename message"):
      followed = messages.rename(p.battle, args.old, args.new)
   for where in followed:
      print(f"followed: {where}")
   return save_if_valid(p)
