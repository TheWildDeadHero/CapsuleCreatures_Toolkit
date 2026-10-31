"""!`capsule-studio battle FILE testsave game ...` [S5] (engine N3: the save image's Game section, core.game_block):

    battle FILE testsave game NAME show
    battle FILE testsave game NAME set VERSION SIZE [--hex HEX]    the game's version and block size, its first bytes
    battle FILE testsave game NAME poke OFFSET HEX                   bytes at an offset of the block
    battle FILE testsave game NAME from-image SAVE_FILE              the Game section of a save the game wrote
    battle FILE testsave game NAME clear

Each change is saved at once (a test save is its own file); `testsave export` writes the section into the image.
"""
from __future__ import annotations

import argparse

from ..core import game_block, inventory
from ..core.document import DocumentError
from .battle_cmds import open_project
from .main import CommandError


def register_testsave(a: argparse._SubParsersAction) -> None:
   """!Adds `testsave game` to the testsave group (cli/inventory_cmds.py).
   @param a  the testsave group's subparsers
   @return None
   """
   r = a.add_parser("game", help="a test save's game block (the image's Game section): show | set | poke | "
                                 "from-image | clear")
   r.add_argument("name", help="the test save")
   g = r.add_subparsers(dest="game_command", metavar="GAME_ACTION")
   g.required = True
   t = g.add_parser("show", help="the block's version, size and bytes")
   t.set_defaults(run=cmd_show)
   t = g.add_parser("set", help="the game's version of its block and the block's size")
   t.add_argument("version", type=int)
   t.add_argument("size", type=int)
   t.add_argument("--hex", default="", help="the block's first bytes (the rest zeros)")
   t.set_defaults(run=cmd_set)
   t = g.add_parser("poke", help="bytes at an offset of the block")
   t.add_argument("offset", type=int)
   t.add_argument("hex")
   t.set_defaults(run=cmd_poke)
   t = g.add_parser("from-image", help="the Game section of a save file the game wrote")
   t.add_argument("save_file", metavar="SAVE_FILE")   # not "file": `battle FILE` names the battle data so
   t.set_defaults(run=cmd_from_image)
   t = g.add_parser("clear", help="no Game section")
   t.set_defaults(run=cmd_clear)


def _change(args: argparse.Namespace, label: str, fn: object) -> int:
   """!One change of the test save, saved at once, then the save shown.
   @param args   parsed arguments
   @param label  undo label
   @param fn     callable(save)
   @return 0
   """
   p = open_project(args)
   save = inventory.open_testsave(p, args.name)
   try:
      with save.edit(label):
         fn(save)
   except DocumentError as e:
      raise CommandError(str(e)) from None
   save.save()
   for line in inventory.lines(save, p.battle):
      print(line)
   return 0


def _bytes(text: str) -> bytes:
   """!Hex from the command line.
   @param text  hex digits
   @return bytes
   """
   try:
      return bytes.fromhex(text)
   except ValueError:
      raise CommandError(f"{text!r}: bytes are hex digits, two per byte") from None


def cmd_show(args: argparse.Namespace) -> int:
   """!Prints the block.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   save = inventory.open_testsave(p, args.name)
   if game_block.game_of(save) is None:
      print("(no game block)")
      return 0
   for line in game_block.lines(save):
      print(line)
   for offset, row in game_block.hex_rows(save):
      print(f"  {offset:06x}  {row}")
   return 0


def cmd_set(args: argparse.Namespace) -> int:
   """!Sets the block's version, size and first bytes.
   @param args  parsed arguments
   @return 0
   """
   data = _bytes(args.hex)
   return _change(args, "Game block", lambda save: game_block.set_game(save, args.version, args.size, data))


def cmd_poke(args: argparse.Namespace) -> int:
   """!Writes bytes into the block.
   @param args  parsed arguments
   @return 0
   """
   data = _bytes(args.hex)
   return _change(args, "Game block bytes", lambda save: game_block.set_bytes(save, args.offset, data))


def cmd_from_image(args: argparse.Namespace) -> int:
   """!Takes the Game section of a save file.
   @param args  parsed arguments
   @return 0
   """
   return _change(args, "Game block from a save", lambda save: game_block.from_image(save, args.save_file))


def cmd_clear(args: argparse.Namespace) -> int:
   """!Takes the Game section out.
   @param args  parsed arguments
   @return 0
   """
   return _change(args, "No game block", game_block.clear_game)
