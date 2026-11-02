"""!`capsule-studio battle FILE ...`: battle data (capsule.battle/1), the
structure manifest it names (capsule.structure/1) and its ruleset.

Editing commands change the files, compile the result with the engine's
battle compiler and save only when it compiles; otherwise they print the
compiler's message and leave the files as they were. A change saves the
files it changed (battle.json, structure.json or both). `split` migrates
single-file battle data (the form from an older version), which no other action opens.

The Structure and Logic commands (validate, stat, pipeline, point, damage,
formula) are actions of this group too; their modules are listed in
main.BATTLE_ACTION_MODULES and register them here.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Any

from ..core import battle
from ..core.battle import BattleProject
from .main import BATTLE_ACTION_MODULES, CommandError

## Values --range takes: the low and the high bound.
RANGE_VALUES = 2
## Arguments of `party PARTY add`: species and level.
PARTY_ADD_ARGS = 2
## Values --size takes: width and height.
SIZE_VALUES = 2


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the command group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("battle", help="battle data (capsule.battle/1) and its ruleset")
   p.add_argument("file", help="battle.json")
   s = p.add_subparsers(dest="battle_command", metavar="ACTION")
   s.required = True
   q = s.add_parser("new", help="create battle.json, structure.json and ruleset.json from the built-in Blank "
                                "template, or (--template) copy a template's files into FILE's folder")
   q.add_argument("--template", metavar="NAME", help="a battle data template (capsule-studio template list), e.g. "
                                                     "blank or starter; FILE must be its battle manifest's name")
   q.set_defaults(run=cmd_new)
   q = s.add_parser("split", help="split older single-file battle data into FILE + its structure "
                                  "manifest (the engine's battle_split tool; values unchanged)")
   q.add_argument("--check", action="store_true", help="only report what would move")
   q.set_defaults(run=cmd_split)
   q = s.add_parser("info", help="counts, record size and formula ranges")
   q.set_defaults(run=cmd_info)
   q = s.add_parser("list", help="names of one kind")
   q.add_argument("kind", choices=battle.KINDS)
   q.set_defaults(run=cmd_list)
   q = s.add_parser("show", help="one entry as JSON")
   q.add_argument("kind", choices=battle.KINDS)
   q.add_argument("name")
   q.set_defaults(run=cmd_show)
   q = s.add_parser("stats", help="a creature's stats at a level, as the engine computes them")
   q.add_argument("species")
   q.add_argument("level", type=int)
   q.add_argument("--genes", type=int, default=0, help="gene value for every stat")
   q.add_argument("--training", type=int, default=0, help="training value for every stat")
   q.add_argument("--awaken", type=int, default=0, help="awakening value for every stat")
   q.add_argument("--trait", help="trait name")
   q.set_defaults(run=cmd_stats)
   q = s.add_parser("set", help="set one field of an entry to a JSON value (null removes it)")
   q.add_argument("kind", choices=battle.KINDS)
   q.add_argument("name")
   q.add_argument("key")
   q.add_argument("value", help='JSON, e.g. 40, "Flame", ["contact"]; bare words are strings')
   q.set_defaults(run=cmd_set)
   q = s.add_parser("add", help="add an entry")
   q.add_argument("kind", choices=battle.KINDS)
   q.add_argument("name")
   q.add_argument("--from", dest="copy_of", help="copy this entry")
   q.set_defaults(run=cmd_add)
   q = s.add_parser("rename", help="rename an entry and every reference to it")
   q.add_argument("kind", choices=battle.KINDS)
   q.add_argument("old")
   q.add_argument("new")
   q.set_defaults(run=cmd_rename)
   q = s.add_parser("remove", help="remove an entry nothing refers to")
   q.add_argument("kind", choices=battle.KINDS)
   q.add_argument("name")
   q.set_defaults(run=cmd_remove)
   q = s.add_parser("learn", help="add a learnset entry")
   q.add_argument("species")
   q.add_argument("level", type=int)
   q.add_argument("move")
   q.set_defaults(run=cmd_learn)
   q = s.add_parser("teachable", help="the moves `teach` may give a species: SPECIES [add|remove MOVE]")
   q.add_argument("species")
   q.add_argument("action", nargs="?", choices=("add", "remove"))
   q.add_argument("move", nargs="?")
   q.set_defaults(run=cmd_teachable)
   q = s.add_parser("forget", help="remove a move from a learnset")
   q.add_argument("species")
   q.add_argument("move")
   q.add_argument("--level", type=int)
   q.set_defaults(run=cmd_forget)
   q = s.add_parser("party", help="party members: PARTY add SPECIES LEVEL | PARTY remove INDEX")
   q.add_argument("party")
   q.add_argument("action", choices=["add", "remove"])
   q.add_argument("args", nargs="+")
   q.add_argument("--moves", help="comma-separated move names")
   q.add_argument("--item")
   q.add_argument("--passive", help="passive slot of the species: its name or index (Structure > Passive slots)")
   q.add_argument("--genes", type=int, help="gene value of every stat (up to the record layout's stat_genes width)")
   q.add_argument("--trait")
   q.set_defaults(run=cmd_party)
   q = s.add_parser("presenter", help="the presenters a party shows: PARTY attach|detach NAME")
   q.add_argument("party")
   q.add_argument("action", choices=["attach", "detach"])
   q.add_argument("name", help="presenter name")
   q.set_defaults(run=cmd_presenter)
   q = s.add_parser("terms", help="the game's words: list them, show one (CONCEPT), or set one (CONCEPT ONE "
                                  f"[MANY]; ONE {battle.TERM_RESET} puts the default back)")
   q.add_argument("concept", nargs="?")
   q.add_argument("one", nargs="?", help="the word")
   q.add_argument("many", nargs="?", help="its plural (default: derived by the plural rule)")
   q.add_argument("--plural", help="set the plural rule of words given without a plural (the engine's "
                                   f"PLURAL_RULES; {battle.TERM_RESET}: the default)")
   q.set_defaults(run=cmd_terms)
   q = s.add_parser("intro", help="what a party's intro shows: presenters entering, speaking and leaving")
   q.add_argument("party")
   q.add_argument("--format", help="format (where presenters stand; default the first)")
   q.set_defaults(run=cmd_intro)
   q = s.add_parser("presenter-track", help="how a presenter's sprite moves for a cue, one line per frame: "
                                            "FRAME X Y ALPHA (top-left corner; alpha 0 hidden)")
   q.add_argument("name", help="presenter name")
   q.add_argument("--format", help="format (where presenters stand; default the first)")
   q.add_argument("--side", type=int, default=battle.FOE_SIDE, help="side of the presenter's party")
   q.add_argument("--cue", choices=battle.TRACK_CUES, default=battle.TRACK_CUES[0])
   q.add_argument("--size", nargs=SIZE_VALUES, type=int, metavar=("W", "H"),
                  help="sprite size (default: the sprite's size in the game's asset manifest)")
   q.set_defaults(run=cmd_presenter_track)
   q = s.add_parser("chart", help="set a type chart cell: ATTACKER DEFENDER TIER (a tier name, or a multiplier "
                                  "equal to one tier's factor; `tier list` shows them)")
   q.add_argument("attacker")
   q.add_argument("defender")
   q.add_argument("value")
   q.set_defaults(run=cmd_chart)
   q = s.add_parser("rule", help="change or add a formula: NAME [--expr TEXT] [--range LO HI] [--args A,B,...] "
                                 "(a name that is not an engine slot or stat formula is a named formula)")
   q.add_argument("slot")
   q.add_argument("--expr")
   q.add_argument("--range", nargs=RANGE_VALUES, type=int, metavar=("LO", "HI"))
   q.add_argument("--args", help="a named formula's arguments, comma-separated (input names)")
   q.add_argument("--remove", action="store_true", help="remove the named formula (nothing may call it)")
   q.set_defaults(run=cmd_rule)
   for name in BATTLE_ACTION_MODULES:
      importlib.import_module(f"{__package__}.{name}").register_actions(s)


def open_project(args: argparse.Namespace) -> BattleProject:
   """!Opens the battle data named on the command line.
   @param args  parsed arguments
   @return BattleProject
   """
   p = Path(args.file)
   if not p.exists():
      raise CommandError(f"{p} does not exist (create it with: battle {p} new)")
   return BattleProject.open(p)


def save_if_valid(project: BattleProject) -> int:
   """!Compiles for every platform the game builds for (its project.json "targets"); saves when it compiles
   for all of them.
   @param project  BattleProject
   @return exit status
   """
   errors = project.target_errors()
   if errors:
      for error in errors:   # each names its platform
         print(f"not saved: {error}")
      return 1
   project.save_all()
   return 0


def json_value(text: str) -> Any:
   """!A command-line value as JSON (bare words are strings).
   @param text  argument
   @return value
   """
   try:
      return json.loads(text)
   except json.JSONDecodeError:
      return text


def cmd_new(args: argparse.Namespace) -> int:
   """!Creates new battle data (or copies a template's).
   @param args  parsed arguments
   @return 0
   """
   if args.template is not None:
      from ..core import templates   # local: only this action needs it

      t = templates.find(args.template, getattr(args, "registry", None))
      target = Path(args.file)
      if target.name not in t.files():
         raise CommandError(f"template {t.id} has no {target.name} (its files: {', '.join(t.files())})")
      written = templates.apply(t, target.parent)
      print(f"copied {len(written)} file(s) of {t.label()} into {target.parent}")
      return 0
   p = BattleProject.create(Path(args.file), Path(args.file).parent.name or "battle")
   print(f"created {p.battle.path}, {p.structure.path} and {p.ruleset.path}")
   return 0


def cmd_split(args: argparse.Namespace) -> int:
   """!Splits single-file battle data into the battle manifest and its structure manifest.
   @param args  parsed arguments
   @return 0
   """
   st_path, keys = battle.split(Path(args.file), args.check)
   verb = "would move" if args.check else "moved"
   print(f"{args.file}: {verb} {len(keys)} structure key(s) to {st_path.name} ({', '.join(keys) or 'none'})")
   return 0


def cmd_info(args: argparse.Namespace) -> int:
   """!Prints counts and formula ranges.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   c, error = p.compile()
   if c is None:
      print(error)
      return 1
   # Items and statuses start with "none" (index 0).
   print(f"{len(c['types'])} types, {len(c['categories'])} categories, {len(c['moves'])} moves, "
         f"{len(c['species'])} species, {len(c['parties'])} parties, {len(c['presenters'])} presenters, "
         f"{len(c['formats'])} formats, {len(c['passives'])} passives, {len(c['items']) - 1} items, "
         f"{len(c['statuses']) - 1} statuses, {len(c['weathers'])} weathers, {len(c['traits'])} traits")
   print(f"record {c['layout']['bytes']} bytes ({c['layout']['bits']} bits), layout hash "
         f"0x{c['layout']['hash']:08X}")
   rows, _ = p.ruleset_report()
   for slot, bounds, rng, clamp, _expr in rows:
      print(f"  {slot}: [{bounds[0]}, {bounds[1]}] -> [{rng[0]}, {rng[1]}]" + (" (clamp can engage)" if clamp else ""))
   return 0


def cmd_list(args: argparse.Namespace) -> int:
   """!Prints the names of one kind.
   @param args  parsed arguments
   @return 0
   """
   for n in open_project(args).names(args.kind):
      print(n)
   return 0


def cmd_show(args: argparse.Namespace) -> int:
   """!Prints one entry.
   @param args  parsed arguments
   @return 0
   """
   print(json.dumps(open_project(args).entry(args.kind, args.name), indent=1))
   return 0


def cmd_stats(args: argparse.Namespace) -> int:
   """!Prints a creature's stats.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   keys = battle.stat_keys(p.battle)
   count = len(keys)
   # out of range values are refused (the level to rules.level_max, the rest to the record layout's widths)
   st = p.stats(args.species, args.level, [args.genes] * count, [args.training] * count, args.trait,
                [args.awaken] * count)
   print(" ".join(f"{k} {v}" for k, v in zip(keys, st)))
   return 0


def cmd_set(args: argparse.Namespace) -> int:
   """!Sets one field.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Set"):
      battle.set_field(p.battle, args.kind, args.name, args.key, json_value(args.value))
   return save_if_valid(p)


def cmd_add(args: argparse.Namespace) -> int:
   """!Adds an entry.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Add"):
      name = battle.add_entry(p.battle, args.kind, args.name, args.copy_of)
   print(f"added {battle.SINGULAR[args.kind]} {name!r}")
   return save_if_valid(p)


def cmd_rename(args: argparse.Namespace) -> int:
   """!Renames an entry.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Rename"):
      n = battle.rename_entry(p.battle, args.kind, args.old, args.new)
   print(f"renamed; {n} reference(s) updated")
   return save_if_valid(p)


def cmd_remove(args: argparse.Namespace) -> int:
   """!Removes an entry.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Remove"):
      battle.remove_entry(p.battle, args.kind, args.name)
   return save_if_valid(p)


def cmd_learn(args: argparse.Namespace) -> int:
   """!Adds a learnset entry.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Learn"):
      battle.learn(p.battle, args.species, args.level, args.move)
   return save_if_valid(p)


def cmd_teachable(args: argparse.Namespace) -> int:
   """!Shows or changes a species' teachable moves.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.action is None:
      moves = battle.teachable(p.battle, args.species)
      print(", ".join(moves) if moves is not None else "(no list: any move while no species lists teachable moves)")
      return 0
   if args.move is None:
      raise CommandError("teachable SPECIES add|remove MOVE")
   with p.battle.edit("Teachable"):
      changed = battle.set_teachable(p.battle, args.species, args.move, args.action == "add")
   if not changed:
      print(f"{args.species}: unchanged")
   return save_if_valid(p)


def cmd_forget(args: argparse.Namespace) -> int:
   """!Removes learnset entries.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Forget"):
      n = battle.forget(p.battle, args.species, args.move, args.level)
   if n == 0:
      raise CommandError(f"{args.species} does not learn {args.move}")
   return save_if_valid(p)


def cmd_party(args: argparse.Namespace) -> int:
   """!Adds or removes a party member.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Party"):
      if args.action == "add":
         if len(args.args) != PARTY_ADD_ARGS:
            raise CommandError("party PARTY add SPECIES LEVEL")
         moves = [m.strip() for m in args.moves.split(",")] if args.moves else None
         # a slot's index or name (the engine takes either: battlec content.passive_slot_of())
         slot = int(args.passive) if args.passive is not None and args.passive.isdigit() else args.passive
         battle.party_add(p.battle, args.party, args.args[0], int(args.args[1]), moves=moves, item=args.item,
                          passive=slot, genes=args.genes, trait=args.trait)
      else:
         if len(args.args) != 1:
            raise CommandError("party PARTY remove INDEX")
         battle.party_remove(p.battle, args.party, int(args.args[0]))
   return save_if_valid(p)


def cmd_presenter(args: argparse.Namespace) -> int:
   """!Attaches a presenter to a party or detaches it.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.battle.edit("Presenter"):
      if args.action == "attach":
         battle.presenter_attach(p.battle, args.party, args.name)
      else:
         battle.presenter_detach(p.battle, args.party, args.name)
   return save_if_valid(p)


def cmd_terms(args: argparse.Namespace) -> int:
   """!Lists, shows or sets the game's words.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.plural is not None:
      with p.battle.edit("Plural rule"):
         battle.set_plural_rule(p.battle, None if args.plural == battle.TERM_RESET else args.plural)
      if args.one is None:
         return save_if_valid(p)
   if args.one is None:
      defaults = battle.default_terms()
      if args.concept is None:
         print(f"plural rule: {battle.plural_rule(p.battle) or 'default'} ({', '.join(battle.plural_rules())})")
      shown = battle.terms(p.battle)
      for concept, t in shown.items():
         if args.concept is not None and concept != args.concept:
            continue
         mark = "" if t == defaults[concept] else "  (game word)"
         print(f"{concept}: {t['one']} / {t['many']}{mark}")
      if args.concept is not None and args.concept not in shown:
         raise CommandError(f"unknown concept {args.concept!r} (concepts: {', '.join(shown)})")
      return 0
   with p.battle.edit("Term"):
      if args.one == battle.TERM_RESET:
         battle.set_term(p.battle, args.concept, None)
      else:
         battle.set_term(p.battle, args.concept, args.one, args.many)
   return save_if_valid(p)


def cmd_intro(args: argparse.Namespace) -> int:
   """!Prints a party's intro.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)   # kept alive (a weak reference from the Document)
   for line in battle.intro(p.battle, args.party, args.format):
      print(line)
   return 0


def cmd_presenter_track(args: argparse.Namespace) -> int:
   """!Prints a presenter's motion for one cue.
   @param args  parsed arguments
   @return 0, or 1 when the data does not compile
   """
   p = open_project(args)
   compiled, error = p.compile()
   if compiled is None:
      print(f"error: {error}")
      return 1
   size = tuple(args.size) if args.size else None
   if size is None:   # the sprite's own size, when the game's asset manifest has it
      sprite = battle.entry(p.battle, "presenters", args.name).get("sprite")
      size = battle.sprite_sizes(p.battle.path).get(sprite, (0, 0))
   for frame, x, y, alpha in battle.presenter_track(compiled, args.name, args.format, args.side, args.cue, size):
      print(f"{frame} {x} {y} {alpha}")
   return 0


def cmd_chart(args: argparse.Namespace) -> int:
   """!Sets a chart cell.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   # A tier name, or a number meaning the tier of that factor.
   v = json_value(args.value)
   with p.battle.edit("Chart"):
      battle.set_chart(p.battle, args.attacker, args.defender, v if isinstance(v, (int, float)) else args.value)
   return save_if_valid(p)


def cmd_rule(args: argparse.Namespace) -> int:
   """!Changes a formula.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.remove:
      with p.ruleset.edit("Remove formula"):
         battle.remove_formula(p.ruleset, args.slot)
      return save_if_valid(p)
   names = [a.strip() for a in args.args.split(",") if a.strip()] if args.args is not None else None
   # No --range leaves both bounds as they are.
   with p.ruleset.edit("Formula"):
      battle.set_formula(p.ruleset, args.slot, args.expr, *(args.range or (None, None)), args=names)
   return save_if_valid(p)
