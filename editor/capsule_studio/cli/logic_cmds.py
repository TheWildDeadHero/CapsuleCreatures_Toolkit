"""!`capsule-studio battle FILE ...` Logic actions (D-23 §3.4): the effect
logic (the battle's .ceffect sources, core.logic), the hook catalog, the
ruleset's formulas, pipelines and points, and the damage calculator.

    battle FILE effect list [--kind K]             every owner with logic: kind, name, file:line, handlers
    battle FILE effect show OWNER                  an owner's block as written, and its handlers
    battle FILE effect set OWNER (--file F | --text T)   replace an owner's block (same kind and name)
    battle FILE effect check                       diagnostics with file:line:col (exit 1 on errors)
    battle FILE effect format [--write]            the canonical text (--write: rewrite the sources)
    battle FILE effect ast OWNER                   an owner's JSON AST (capsule.effect-ast/1)
    battle FILE effect add KIND NAME [--file F]    an empty logic block for an entry
    battle FILE effect remove OWNER                remove an owner's logic block
    battle FILE effect rename OWNER NEW            give an owner's logic to another entry of its kind
    battle FILE hooks [--kind K]                   the hooks and points a handler can use, with their bindings

OWNER is "kind:name" (move:Strike) or a name only one owner has.

    battle FILE formula [NAME [input=value ...]]   list every formula, or evaluate one (slot, named, stat)
    battle FILE pipeline show [NAME]               the pipelines, or one's steps with their analysed ranges
                                                   (an optional pipeline the ruleset leaves out: "engine default")
    battle FILE pipeline reset NAME                leave an optional pipeline (effect_odds) to the engine
    battle FILE pipeline step add NAME (--let VAR --expr E [--range LO HI] | --point P --on VAR |
                                        --roll VAR --span E) [--at I]
    battle FILE pipeline step remove NAME INDEX
    battle FILE pipeline step move NAME INDEX up|down
    battle FILE pipeline step set NAME INDEX KEY VALUE   (KEY: let expr range | point on | roll span;
                                                          range VALUE "[lo, hi]" or null)
    battle FILE point list                          (then the reserved point names, e.g. move_type, E13b)
    battle FILE point add NAME [--holder H] [--sources S,S] [--range LO HI]
    battle FILE point remove NAME
    battle FILE point set NAME KEY VALUE           KEY: holder, sources (S,S or a JSON list), range ("[lo, hi]")
    battle FILE damage ATTACKER DEFENDER MOVE [--level N] [--roll N] [--crit] [--weather W] [--status S]
                                               [--spread] [--trace] [...]
                                               [--volatile V] [--defender-volatile V] [--side C]
                                               [--defender-side C] [--active N] [--defender-active N]
                                               (E13b: their point handlers run; the move_type point sets the
                                               hit's type)

Range bounds may name constants (STAT_CAP, a ruleset constant). Editing
actions save only when the result compiles (battle_cmds.save_if_valid).
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..core import battle, engine, holders, logic, pipelines
from .battle_cmds import json_value, open_project, save_if_valid
from .main import CommandError

## Move directions and their deltas.
MOVES = {"up": -1, "down": 1}
## Values a --range takes: the low and the high bound.
RANGE_VALUES = 2


def bound(text: str) -> int | str:
   """!A range bound from the command line: an integer or a constant name.
   @param text  argument
   @return int or str
   """
   try:
      return int(text)
   except ValueError:
      return text


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   register_effect_actions(s)
   q = s.add_parser("formula", help="list the ruleset's formulas, or evaluate one: NAME input=value ... (an engine "
                                    "slot, a named formula or a stat formula)")
   q.add_argument("slot", nargs="?")
   q.add_argument("values", nargs="*")
   q.set_defaults(run=cmd_formula)

   q = s.add_parser("pipeline", help="the ruleset's pipelines: show | reset | step add|remove|move|set")
   a = q.add_subparsers(dest="pipeline_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("show", help="every pipeline, or one pipeline's steps with their analysed ranges")
   r.add_argument("name", nargs="?")
   r.set_defaults(run=cmd_pipeline_show)
   r = a.add_parser("reset", help="leave an optional pipeline out of the ruleset (the engine's default steps)")
   r.add_argument("name")
   r.set_defaults(run=cmd_pipeline_reset)
   r = a.add_parser("step", help="change a pipeline's steps: add | remove | move | set")
   b = r.add_subparsers(dest="step_command", metavar="ACTION")
   b.required = True
   t = b.add_parser("add", help="insert a let, point or roll step")
   t.add_argument("name", help="pipeline")
   kind = t.add_mutually_exclusive_group(required=True)
   kind.add_argument("--let", metavar="VAR", help="a let step setting VAR (needs --expr)")
   kind.add_argument("--point", metavar="POINT", help="a point step running POINT (needs --on)")
   kind.add_argument("--roll", metavar="VAR", help="a roll step drawing VAR (needs --span)")
   t.add_argument("--expr", help="the let's expression")
   t.add_argument("--on", metavar="VAR", help="the variable the point runs on")
   t.add_argument("--span", help="the roll's span expression (draws 0 to span - 1)")
   t.add_argument("--range", nargs=RANGE_VALUES, type=bound, metavar=("LO", "HI"), help="the let's clamp")
   t.add_argument("--at", type=int, help="position (default: the end)")
   t.set_defaults(run=cmd_step_add)
   t = b.add_parser("remove", help="remove a step")
   t.add_argument("name", help="pipeline")
   t.add_argument("index", type=int)
   t.set_defaults(run=cmd_step_remove)
   t = b.add_parser("move", help="move a step up or down")
   t.add_argument("name", help="pipeline")
   t.add_argument("index", type=int)
   t.add_argument("direction", choices=list(MOVES))
   t.set_defaults(run=cmd_step_move)
   t = b.add_parser("set", help="change one key of a step")
   t.add_argument("name", help="pipeline")
   t.add_argument("index", type=int)
   t.add_argument("key")
   t.add_argument("value")
   t.set_defaults(run=cmd_step_set)

   q = s.add_parser("point", help="the ruleset's points: list | add | remove | set")
   a = q.add_subparsers(dest="point_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="every point: id, holder, sources, range, and what uses it")
   r.set_defaults(run=cmd_point_list)
   r = a.add_parser("add", help="add a point")
   r.add_argument("name")
   r.add_argument("--holder", default=pipelines.DEFAULT_HOLDER, help="user, target or self")
   r.add_argument("--sources", default="", help="comma-separated, in the order they run")
   r.add_argument("--range", nargs=RANGE_VALUES, type=bound, metavar=("LO", "HI"))
   r.set_defaults(run=cmd_point_add)
   r = a.add_parser("remove", help="remove a point nothing uses")
   r.add_argument("name")
   r.set_defaults(run=cmd_point_remove)
   r = a.add_parser("set", help="change a point's holder, sources or range")
   r.add_argument("name")
   r.add_argument("key", choices=pipelines.POINT_KEYS)
   r.add_argument("value")
   r.set_defaults(run=cmd_point_set)

   q = s.add_parser("damage", help="one hit's damage as the engine computes it (the damage pipeline)")
   q.add_argument("attacker", help="attacking species")
   q.add_argument("defender", help="defending species")
   q.add_argument("move")
   q.add_argument("--level", type=int, help=f"both creatures' level (default {pipelines.DEFAULT_LEVEL}, at most "
                                         "the rules' level_max)")
   q.add_argument("--defender-level", type=int, help="the defender's level (default: --level)")
   q.add_argument("--roll", type=int, default=0, help="damage roll index (0 lowest; larger is clamped to the "
                                                    "highest)")
   q.add_argument("--crit", action="store_true", help="a critical hit")
   q.add_argument("--weather")
   q.add_argument("--status", help="the attacker's status")
   q.add_argument("--spread", action="store_true", help="a spread hit")
   q.add_argument("--trace", action="store_true", help="print every step")
   q.add_argument("--passive", help="the attacker's passive (default: its species' first)")
   q.add_argument("--item", help="the attacker's held item")
   q.add_argument("--trait", help="the attacker's trait")
   q.add_argument("--defender-trait")
   q.add_argument("--genes", type=int, default=0, help="every stat's gene value of both")
   q.add_argument("--training", type=int, default=0, help="every stat's training value of both")
   q.add_argument("--hp", type=int, default=pipelines.PERCENT, help="the attacker's HP in percent")
   q.add_argument("--offense-stage", type=int, default=0)
   q.add_argument("--defense-stage", type=int, default=0)
   # E13b: the point handlers of volatiles and side conditions run too
   q.add_argument("--volatile", action="append", default=[], help="a volatile on the attacker (repeatable)")
   q.add_argument("--defender-volatile", action="append", default=[], help="a volatile on the defender")
   q.add_argument("--side", action="append", default=[], help="a side condition on the attacker's side")
   q.add_argument("--defender-side", action="append", default=[], help="a side condition on the defender's side")
   q.add_argument("--active", type=int, help="battlers active on the attacker's side (default 1)")
   q.add_argument("--defender-active", type=int, help="battlers active on the defender's side (default 1)")
   q.set_defaults(run=cmd_damage)


def register_effect_actions(s: argparse._SubParsersAction) -> None:
   """!Adds the effect and hooks actions to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("effect", help="the effect logic (.ceffect sources): list | show | set | check | format | ast | "
                                   "add | remove | rename")
   a = q.add_subparsers(dest="effect_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("list", help="every owner with logic")
   r.add_argument("--kind", help="only this owner kind (move, passive, item, status, weather)")
   r.set_defaults(run=cmd_effect_list)
   r = a.add_parser("show", help="an owner's block as written, and its handlers")
   r.add_argument("owner", help="kind:name, or a name only one owner has")
   r.set_defaults(run=cmd_effect_show)
   r = a.add_parser("set", help="replace an owner's block (one block of the same kind and name)")
   r.add_argument("owner")
   given = r.add_mutually_exclusive_group(required=True)
   given.add_argument("--file", dest="block_file", help="a file holding the block")
   given.add_argument("--text", help="the block")
   r.set_defaults(run=cmd_effect_set)
   r = a.add_parser("check", help="the logic's diagnostics (file:line:col), then whether the battle data compiles")
   r.set_defaults(run=cmd_effect_check)
   r = a.add_parser("format", help="print the canonical text of every source, or rewrite them (--write)")
   r.add_argument("--write", action="store_true", help="rewrite the sources whose text is not canonical")
   r.set_defaults(run=cmd_effect_format)
   r = a.add_parser("ast", help="an owner's JSON AST")
   r.add_argument("owner")
   r.set_defaults(run=cmd_effect_ast)
   r = a.add_parser("add", help="an empty logic block for an entry")
   r.add_argument("kind", help="move, passive, item, status or weather")
   r.add_argument("name", help="the entry")
   r.add_argument("--file", dest="source", help="the source (as the battle manifest lists it; default: the one "
                                               "holding the kind)")
   r.set_defaults(run=cmd_effect_add)
   r = a.add_parser("remove", help="remove an owner's logic block (the entry stays)")
   r.add_argument("owner")
   r.set_defaults(run=cmd_effect_remove)
   r = a.add_parser("rename", help="give an owner's logic to another entry of its kind (renaming the entry itself: "
                                   "battle FILE rename KIND OLD NEW)")
   r.add_argument("owner")
   r.add_argument("new")
   r.set_defaults(run=cmd_effect_rename)

   q = s.add_parser("hooks", help="the hooks and move phases a handler can use (bindings, value, verdicts, draws, "
                                  "yields) and the ruleset's points")
   q.add_argument("--kind", help="only what this owner kind can hold")
   q.set_defaults(run=cmd_hooks)


# -- effect logic -----------------------------------------------------------------------------------------------------

def cmd_effect_list(args: argparse.Namespace) -> int:
   """!Prints the owners.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for row in logic.owners(p, args.kind):
      print(f"{row.kind}:{row.name}  {row.file}:{row.line}  {row.handlers} handler(s)")
   return 0


def cmd_effect_show(args: argparse.Namespace) -> int:
   """!Prints an owner's block and its handlers.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   print(f"# {logic.owner_file(p, args.owner)}")
   print(logic.owner_text(p, args.owner))
   for h in logic.handlers(p, args.owner):
      head = f"{h.member} {h.name}" if h.member != "phase" else h.name
      extra = (" per_foe" if h.per_foe else "") + (f" when {h.when}" if h.when else "")
      print(f"# [{h.index}] {head}{extra}: {h.statements} statement(s)")
   return 0


def cmd_effect_set(args: argparse.Namespace) -> int:
   """!Replaces an owner's block.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   text = Path(args.block_file).read_text(encoding="utf-8") if args.block_file is not None else args.text
   logic.set_owner_text(p, args.owner, text)
   return save_if_valid(p)


def cmd_effect_check(args: argparse.Namespace) -> int:
   """!Prints the diagnostics; then whether the battle data compiles.
   @param args  parsed arguments
   @return 0, or 1 when there is an error
   """
   p = open_project(args)
   found = logic.diagnostics(p)
   for d in found:
      print(d.text())
   if any(d.severity == "error" for d in found):
      return 1
   errors = p.target_errors()
   for error in errors:
      print(f"battle data: {error}")
   if not errors:
      print(f"logic checks: {len(found)} warning(s); battle data compiles")
   return 1 if errors else 0


def cmd_effect_format(args: argparse.Namespace) -> int:
   """!Prints the canonical text, or rewrites the sources.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if not args.write:
      many = len(logic.source_paths(p)) > 1
      for rel in logic.source_paths(p):
         print((f"# file: {rel}\n" if many else "") + logic.canonical_text(p, rel), end="")
      return 0
   changed = logic.format_sources(p, write=True)
   for rel in changed:
      print(f"formatted {rel}")
   if not changed:
      print("every source is canonical")
      return 0
   return save_if_valid(p)


def cmd_effect_ast(args: argparse.Namespace) -> int:
   """!Prints an owner's JSON AST.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   print(engine.tool("effect_compiler").to_json(logic.owner_ast(p, args.owner)), end="")
   return 0


def cmd_effect_add(args: argparse.Namespace) -> int:
   """!Adds an empty logic block.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   rel = logic.add_owner(p, args.kind, args.name, args.source)
   print(f"added {args.kind}:{args.name} to {rel}")
   return save_if_valid(p)


def cmd_effect_remove(args: argparse.Namespace) -> int:
   """!Removes an owner's logic block.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   logic.remove_owner(p, args.owner)
   return save_if_valid(p)


def cmd_effect_rename(args: argparse.Namespace) -> int:
   """!Gives an owner's logic to another entry.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   logic.rename_owner(p, args.owner, args.new)
   return save_if_valid(p)


def range_text(value: Any) -> str:
   """!A catalog value range as text.
   @param value  [lo, hi], or None
   @return "[lo, hi]" or "none"
   """
   return f"[{value[0]}, {value[1]}]" if value else "none"


def cmd_hooks(args: argparse.Namespace) -> int:
   """!Prints the hook catalog and the ruleset's points.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for h in logic.hook_catalog(args.kind):
      notes = []
      if h["phase"]:
         notes.append("move phase")
      if h["per_foe"]:
         notes.append("per_foe")
      if h["yields"]:
         notes.append("may yield / ask")
      if h["results"]:
         notes.append("verdicts " + ", ".join(h["results"]))
      if h["draws"]:
         notes.append("draws: " + h["draws"])
      print(f"{h['name']}: {h['binds']}; value {range_text(h['value'])}; owners {', '.join(h['owners'])}"
            + "".join(f"; {n}" for n in notes))
   owners = logic.point_owner_lists()
   if args.kind is None or args.kind in owners.values():
      # with a kind: only the points whose sources take it (E13b: a move's own, a side condition's "side")
      key = next((k for k, kind in owners.items() if kind == args.kind), None)
      source = pipelines.handler_owners()[key] if key is not None else None
      for pt in logic.point_catalog(p):
         if source is not None and not holders.takes_source(pt["sources"], source):
            continue
         print(f"point {pt['name']}: id {pt['id']}, holder {pt['holder']}, sources {', '.join(pt['sources'])}, "
               f"value {range_text(pt['range'])}; pure (no draws, no yields)")
   return 0


# -- formulas ---------------------------------------------------------------------------------------------------------

def cmd_formula(args: argparse.Namespace) -> int:
   """!Lists the formulas or evaluates one.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   if args.slot is None:
      rc = engine.tool("ruleset_compiler")
      named = battle.named_formulas(p.ruleset)
      for name in p.formula_slots():
         what = "slot" if name in rc.FORMULA_SLOTS else "named" if name in named else "stat"
         f = battle.formula_entry(p.ruleset, name)
         rng = f.get("range", ["?", "?"])
         inputs = ", ".join(n for n, _r in p.formula_inputs(name))
         print(f"{name} ({what}; {inputs}) = {f.get('expr', '')}  [{rng[0]}, {rng[1]}]")
      return 0
   values: dict[str, int] = {}
   for v in args.values:
      if "=" not in v:
         raise CommandError(f"values look like name=12, got {v!r}")
      k, x = v.split("=", 1)
      values[k] = int(x)
   print(p.formula(args.slot, **values))
   return 0


# -- pipelines --------------------------------------------------------------------------------------------------------

def cmd_pipeline_show(args: argparse.Namespace) -> int:
   """!Prints the pipelines, or one's steps.
   @param args  parsed arguments
   @return 0, or 1 when the ruleset does not compile
   """
   p = open_project(args)
   if args.name is None:
      for name in pipelines.pipeline_names():
         steps = pipelines.shown_steps(p.ruleset, name)
         default = f" ({pipelines.default_note(name)})" if pipelines.is_engine_default(p.ruleset, name) else ""
         print(f"{name}: {len(steps)} steps{default}; inputs {', '.join(pipelines.pipeline_inputs(name))}; outputs "
               f"{', '.join(pipelines.pipeline_outputs(name))}")
      return 0
   rows, error, own = pipelines.pipeline_report(p, args.name)
   if error and not rows:
      print(f"error: {error}")
      return 1
   print(f"{args.name}: inputs {', '.join(pipelines.pipeline_inputs(args.name))}"
         + ("" if own else " (analysed against neutral battle values: the battle data does not compile)")
         + (f" ({pipelines.default_note(args.name)})" if pipelines.is_engine_default(p.ruleset, args.name) else ""))
   for r in rows:
      extra = ""
      if r["range"] is not None:
         clamp = "can engage" if r["clamp_active"] else "never engages"
         extra = f" (analysed [{r['analysed'][0]}, {r['analysed'][1]}], clamp {clamp})"
      print(f"  [{r['index']}] {r['text']}  -> {r['var']} [{r['bounds'][0]}, {r['bounds'][1]}]{extra}")
   if error:
      print(f"error: {error}")
   return 0


def cmd_step_add(args: argparse.Namespace) -> int:
   """!Adds a step.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   if args.let is not None:
      step = pipelines.make_step("let", args.let, args.expr, args.range)
   elif args.point is not None:
      step = pipelines.make_step("point", args.on, args.point)
   else:
      step = pipelines.make_step("roll", args.roll, args.span)
   with p.ruleset.edit("Add step"):
      i = pipelines.add_step(p.ruleset, args.name, step, args.at)
   print(f"added step {i}: {pipelines.step_text(step)}")
   return save_if_valid(p)


def cmd_pipeline_reset(args: argparse.Namespace) -> int:
   """!Gives an optional pipeline back to the engine.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.ruleset.edit("Engine default pipeline"):
      listed = pipelines.reset_pipeline(p.ruleset, args.name)
   print(f"{args.name}: {pipelines.default_note(args.name)}" + ("" if listed else " (already)"))
   return save_if_valid(p)


def cmd_step_remove(args: argparse.Namespace) -> int:
   """!Removes a step.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.ruleset.edit("Remove step"):
      pipelines.remove_step(p.ruleset, args.name, args.index)
   return save_if_valid(p)


def cmd_step_move(args: argparse.Namespace) -> int:
   """!Moves a step.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.ruleset.edit("Move step"):
      moved = pipelines.move_step(p.ruleset, args.name, args.index, MOVES[args.direction])
   if not moved:
      raise CommandError(f"step {args.index} is already at the {'top' if args.direction == 'up' else 'bottom'}")
   return save_if_valid(p)


def cmd_step_set(args: argparse.Namespace) -> int:
   """!Changes one key of a step.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value: Any = json_value(args.value) if args.key == "range" else args.value
   with p.ruleset.edit("Set step"):
      pipelines.set_step(p.ruleset, args.name, args.index, args.key, value)
   return save_if_valid(p)


# -- points -----------------------------------------------------------------------------------------------------------

def cmd_point_list(args: argparse.Namespace) -> int:
   """!Prints the points.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   for i, name in enumerate(pipelines.point_names(p.ruleset)):
      pt = pipelines.point_entry(p.ruleset, name)
      rng = pt.get("range", ["?", "?"])
      users = pipelines.point_users(p.ruleset, name, p.battle)
      print(f"{i} {name}: holder {pt.get('holder', pipelines.DEFAULT_HOLDER)}, sources "
            f"{', '.join(pt.get('sources') or []) or 'none'}, range [{rng[0]}, {rng[1]}]; used by "
            f"{', '.join(users) or 'nothing'}")
   for name, note in pipelines.reserved_points().items():
      print(f"{name}: {note}" + ("" if name in pipelines.point_names(p.ruleset) else " (not declared)"))
   return 0


def sources(text: str) -> list[str]:
   """!A source list from the command line: a JSON list or comma-separated names.
   @param text  argument
   @return names
   """
   v = json_value(text)
   if isinstance(v, list):
      return v
   return [x.strip() for x in text.split(",") if x.strip()]


def cmd_point_add(args: argparse.Namespace) -> int:
   """!Adds a point.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.ruleset.edit("Add point"):
      pipelines.add_point(p.ruleset, args.name, args.holder, sources(args.sources), args.range)
   return save_if_valid(p)


def cmd_point_remove(args: argparse.Namespace) -> int:
   """!Removes a point.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   with p.ruleset.edit("Remove point"):
      pipelines.remove_point(p.ruleset, args.name, p.battle)
   return save_if_valid(p)


def cmd_point_set(args: argparse.Namespace) -> int:
   """!Changes a point.
   @param args  parsed arguments
   @return 0 or 1
   """
   p = open_project(args)
   value: Any = args.value
   if args.key == "sources":
      value = sources(args.value)
   elif args.key == "range":
      value = json_value(args.value)
   with p.ruleset.edit("Set point"):
      pipelines.set_point(p.ruleset, args.name, args.key, value)
   return save_if_valid(p)


# -- damage -----------------------------------------------------------------------------------------------------------

def cmd_damage(args: argparse.Namespace) -> int:
   """!Prints one hit's damage (and with --trace every step).
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   level = args.level if args.level is not None else min(pipelines.DEFAULT_LEVEL, battle.level_max(p.structure))
   t = pipelines.damage_trace(p, args.attacker, args.defender, args.move, level, args.roll, args.crit,
                              args.weather, args.status, args.spread, attacker_trait=args.trait,
                              defender_trait=args.defender_trait, passive=args.passive, item=args.item,
                              genes=args.genes, training=args.training, hp_pct=args.hp,
                              offense_stage=args.offense_stage, defense_stage=args.defense_stage,
                              defender_level=args.defender_level, attacker_volatiles=args.volatile,
                              defender_volatiles=args.defender_volatile, attacker_side=args.side,
                              defender_side=args.defender_side, attacker_active=args.active,
                              defender_active=args.defender_active)
   if args.trace:
      for line in t.lines():
         print(line)
   else:
      print(t.damage)
   return 0
