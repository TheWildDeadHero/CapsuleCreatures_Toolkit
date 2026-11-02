"""!`capsule-studio map-field WORLD ...`: the world's object kinds, map tags and flight
points and the maps' darkness, tags and escape points (core.map_field), everything the World page's Field panel
does.

    map-field WORLD list
    map-field WORLD kind add|remove NAME | kind rename OLD NEW      (the maps' objects follow; and the battle's
                                                                    field actions; a removal is refused while used)
    map-field WORLD tag add|remove NAME | tag rename OLD NEW        (the maps' tags follow, and the field actions)
    map-field WORLD darkness list | add LIT BRIGHTNESS | remove | set LEVEL lit|brightness VALUE
                                                                    (the world's darkness levels)
    map-field WORLD flight add NAME MAP X Y [--label L] [--facing F]
    map-field WORLD flight set NAME label|map|x|y|facing VALUE
    map-field WORLD flight remove NAME
    map-field WORLD map MAP darkness N | tags [A,B] | escape on|off

Changes are compiled with the engine before the world is saved.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable

from ..core import map_field
from ..core.document import DocumentError
from ..core.world import Project
from .main import CommandError

## `escape` values.
SWITCH = {"on": True, "off": False}
## The flight point fields `flight set` writes, and how their values read.
FLIGHT_VALUES = {"label": str, "map": str, "x": int, "y": int, "facing": str}


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the `map-field` group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("map-field", help="a world's object kinds, map tags, flight points; maps' darkness / tags / "
                                        "escape points")
   p.add_argument("world", help="world.json")
   a = p.add_subparsers(dest="map_field_command", metavar="ACTION")
   a.required = True
   a.add_parser("list", help="everything").set_defaults(run=cmd_list)
   for word, key in (("kind", map_field.KINDS_KEY), ("tag", map_field.TAGS_KEY)):
      q = a.add_parser(word, help=f"the world's {key}")
      q.add_argument("op", choices=["add", "remove", "rename"])
      q.add_argument("name")
      q.add_argument("new", nargs="?")
      q.set_defaults(run=cmd_names, key=key)
   q = a.add_parser("flight", help="the world's flight points")
   f = q.add_subparsers(dest="flight_command", metavar="OP")
   f.required = True
   r = f.add_parser("add")
   r.add_argument("name")
   r.add_argument("map")
   r.add_argument("x", type=int)
   r.add_argument("y", type=int)
   r.add_argument("--label")
   r.add_argument("--facing", choices=map_field.directions(), default=map_field.DEFAULT_FACING)
   r.set_defaults(run=cmd_flight_add)
   r = f.add_parser("set")
   r.add_argument("name")
   r.add_argument("key", choices=list(FLIGHT_VALUES))
   r.add_argument("value")
   r.set_defaults(run=cmd_flight_set)
   r = f.add_parser("remove")
   r.add_argument("name")
   r.set_defaults(run=cmd_flight_remove)
   q = a.add_parser("darkness", help="the world's darkness levels")
   d = q.add_subparsers(dest="darkness_command", metavar="OP")
   d.required = True
   d.add_parser("list").set_defaults(run=cmd_darkness_list)
   r = d.add_parser("add", help="a darkest level after the others")
   r.add_argument("lit", type=int, help="the lit box's half size, pixels")
   r.add_argument("brightness", type=int, help="how dark the rest goes (0-16)")
   r.set_defaults(run=cmd_darkness_add)
   d.add_parser("remove", help="the darkest level (refused while a map is that dark)").set_defaults(
      run=cmd_darkness_remove)
   r = d.add_parser("set")
   r.add_argument("level", type=int)
   r.add_argument("key", choices=list(map_field.LEVEL_FIELDS))
   r.add_argument("value", type=int)
   r.set_defaults(run=cmd_darkness_set)
   q = a.add_parser("map", help="a map's darkness, tags or escape point")
   q.add_argument("map")
   q.add_argument("key", choices=["darkness", "tags", "escape"])
   q.add_argument("value", nargs="?", default="")
   q.set_defaults(run=cmd_map)


def _save(p: Project) -> int:
   """!Saves the world when it compiles.
   @param p  the world's Project
   @return 0, or 1 when it does not compile
   """
   error = p.validate()
   if error:
      print(f"not saved: {error}")
      return 1
   p.save_all()
   if p.followed_battle:   # the battle field actions the saved world's renames made follow
      print("battle: " + ", ".join(p.followed_battle))
   return 0


def _edit(args: argparse.Namespace, label: str, fn: Callable[[Project], object]) -> int:
   """!Runs a change on the world (or its maps) and saves it when the world compiles.
   @param args   parsed arguments
   @param label  undo label
   @param fn     callable(Project)
   @return 0, or 1 when the world does not compile
   """
   p = Project.open(args.world)
   try:
      with p.world.edit(label):
         result = fn(p)
   except DocumentError as e:
      raise CommandError(str(e))
   if isinstance(result, list) and result:
      print("followed: " + ", ".join(str(r) for r in result))
   return _save(p)


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the world's field actions parts.
   @param args  parsed arguments
   @return 0
   """
   for line in map_field.lines(Project.open(args.world)):
      print(line)
   return 0


def cmd_names(args: argparse.Namespace) -> int:
   """!Adds, removes or renames an object kind or a map tag.
   @param args  parsed arguments
   @return 0 or 1
   """
   if args.op == "rename" and not args.new:
      raise CommandError("rename OLD NEW")
   ops = {"add": lambda p: map_field.add_name(p, args.key, args.name),
          "remove": lambda p: map_field.remove_name(p, args.key, args.name),
          "rename": lambda p: map_field.rename_name(p, args.key, args.name, args.new)}
   return _edit(args, f"{args.op} {args.key}", ops[args.op])


def cmd_flight_add(args: argparse.Namespace) -> int:
   """!Adds a flight point.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Add flight point", lambda p: map_field.add_flight_point(
      p.world, args.name, args.map, args.x, args.y, args.label, args.facing))


def cmd_flight_set(args: argparse.Namespace) -> int:
   """!Changes a flight point.
   @param args  parsed arguments
   @return 0 or 1
   """
   try:
      value = FLIGHT_VALUES[args.key](args.value)
   except ValueError:
      raise CommandError(f"{args.key}: a number (got {args.value!r})") from None
   return _edit(args, "Flight point", lambda p: map_field.set_flight_point(p.world, args.name, args.key, value))


def cmd_flight_remove(args: argparse.Namespace) -> int:
   """!Removes a flight point.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Remove flight point", lambda p: map_field.remove_flight_point(p.world, args.name))


def cmd_darkness_list(args: argparse.Namespace) -> int:
   """!Prints the world's darkness levels.
   @param args  parsed arguments
   @return 0
   """
   w = Project.open(args.world).world
   for k, lv in enumerate(map_field.darkness_levels(w)):
      print(f"{k + 1}: lit {lv['lit']} brightness {lv['brightness']}")
   if map_field.levels_default(w):
      print("(the engine's defaults: the world states none)")
   return 0


def cmd_darkness_add(args: argparse.Namespace) -> int:
   """!Adds a darkest level.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Add darkness level",
                lambda p: map_field.add_darkness_level(p.world, args.lit, args.brightness) and None)


def cmd_darkness_remove(args: argparse.Namespace) -> int:
   """!Removes the darkest level.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Remove darkness level", map_field.remove_darkness_level)


def cmd_darkness_set(args: argparse.Namespace) -> int:
   """!Changes a darkness level.
   @param args  parsed arguments
   @return 0 or 1
   """
   return _edit(args, "Darkness level",
                lambda p: map_field.set_darkness_level(p.world, args.level, args.key, args.value))


def cmd_map(args: argparse.Namespace) -> int:
   """!Sets a map's darkness, tags or escape point.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = Project.open(args.world)
   if args.map not in p.map_names():
      raise CommandError(f"no map {args.map!r}")
   doc = p.map(args.map)
   try:
      with doc.edit(f"Map {args.key}"):
         if args.key == "darkness":
            if not args.value.isdigit():
               raise DocumentError(f"darkness: 0 to {map_field.darkest(p.world)} (got {args.value!r})")
            map_field.set_darkness(doc, p.world, int(args.value))
         elif args.key == "tags":
            map_field.set_tags(doc, p.world, [t for t in args.value.split(",") if t])
         else:
            if args.value not in SWITCH:
               raise DocumentError(f"escape: on or off (got {args.value!r})")
            map_field.set_escape_point(doc, p.world, SWITCH[args.value])
   except DocumentError as e:
      raise CommandError(str(e))
   return _save(p)
