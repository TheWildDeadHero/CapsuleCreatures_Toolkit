"""!`capsule-studio battle FILE bench ...`: the battle test bench (D-23 §3.3,
core.bench): scenarios in the game's bench/ folder, run through the
engine's compiled bench.

    battle FILE bench new NAME [--format F] [--party P]... [--seed N]
                                                  a scenario from the battle data: bench/NAME.json
    battle FILE bench list                        the game's scenarios: name, title, expected transcript
    battle FILE bench validate [SCENARIO...]      shape and poke-name checks (the engine's bench_scenario); default: all
    battle FILE bench run SCENARIO [--trace rng,vm,events] [--rng NAME] [--json] [--save-expected]
                                                  build (incrementally) and run; prints the transcript
                                                  and the trace lines (owner, hook, pc, file:line:col)
    battle FILE bench check SCENARIO [--rng R]    run and compare with the scenario's "expect" transcript
    battle FILE bench build [--rng R]             configure (once) and build the bench; prints its path
    battle FILE bench generators                  the generators a bench can link (default, the reference
                                                  repo's compat/generators.json) and their source files
    battle FILE bench owner-texts SCENARIO [on|off]   the transcript's owner texts (E13b "owner_texts")
    battle FILE bench migrate                     rename the retired poke keys (status_turns -> status_counter,
                                                  escalation -> status_aux) in every scenario and save them

SCENARIO is a name in bench/ ("wild" or "wild.json"), a path relative to
the game folder ("bench/wild.json"), or a file. The bench builds from the
battle data as saved, into the game's build/bench/GENERATOR folder
(--cache DIR for another); building needs CMake and a C++ compiler.
Progress goes to stderr. Exit status 1 when a scenario has problems, the
bench reports errors or a check fails.
"""
from __future__ import annotations

import argparse
import json
import sys

from ..core import bench
from .battle_cmds import open_project
from .main import CommandError

## Exit status of a failed check, a bad scenario or a bench error.
FAILED_STATUS = 1
## The on / off words of `bench owner-texts`.
SWITCH = {"on": True, "off": False}
## How `bench generators` shows the engine's generator (it has no source file of the game's).
ENGINE_GENERATOR = "(the engine's)"


def register_actions(s: argparse._SubParsersAction) -> None:
   """!Adds `bench` to the battle group.
   @param s  the battle group's subparsers
   @return None
   """
   q = s.add_parser("bench", help="the battle test bench: new | list | validate | run | check | build | generators | "
                                  "migrate | owner-texts")
   a = q.add_subparsers(dest="bench_command", metavar="ACTION")
   a.required = True
   r = a.add_parser("new", help="a scenario from the battle data (bench/NAME.json in the game folder)")
   r.add_argument("name")
   r.add_argument("--format", help="a format of the battle data (default: the first)")
   r.add_argument("--party", action="append", help="a party of the battle data: the player's, then the foe's "
                                                   "(default: the first two; a wild creature when there is one)")
   r.add_argument("--seed", type=int, default=bench.DEFAULT_SEED, help="the battle seed")
   r.set_defaults(run=cmd_new)
   r = a.add_parser("list", help="the game's scenarios")
   r.set_defaults(run=cmd_list)
   r = a.add_parser("validate", help="check scenarios' shape (default: every scenario of the game)")
   r.add_argument("scenarios", nargs="*")
   r.set_defaults(run=cmd_validate)
   for name, fn, text in (("run", cmd_run, "build the bench (incrementally) and run a scenario"),
                          ("check", cmd_check, "run a scenario and compare its transcript with \"expect\""),
                          ("build", cmd_build, "configure (once) and build the bench")):
      r = a.add_parser(name, help=text)
      if name != "build":
         r.add_argument("scenario")
      r.add_argument("--rng", default=None if name != "build" else bench.DEFAULT_RNG,
                     help="the generator: default (the engine's) or the reference repo's "
                          "(bench generators lists them; run / check default to the scenario's \"rng\")")
      r.add_argument("--cache", metavar="DIR", help="the build folder (default: the game's build/bench/RNG)")
      r.add_argument("--jobs", type=int, help="parallel compile jobs (default: every core)")
      if name == "run":
         r.add_argument("--trace", default="", help="extra traces, comma-separated: rng, vm, events")
         r.add_argument("--json", action="store_true", help="print the bench's records as JSON lines")
         r.add_argument("--save-expected", action="store_true",
                        help="save the transcript as the scenario's expected one (NAME.expected.txt)")
      r.set_defaults(run=fn)
   r = a.add_parser("generators", help="the generators a bench can link and their source files")
   r.set_defaults(run=cmd_generators)
   r = a.add_parser("migrate", help="rename the retired poke keys in every scenario and save them")
   r.set_defaults(run=cmd_migrate)
   r = a.add_parser("owner-texts", help="whether a scenario's transcript prints the effect logic's texts "
                                        "(scenario \"owner_texts\", E13b); with on / off: set it and save")
   r.add_argument("scenario")
   r.add_argument("value", nargs="?", choices=list(SWITCH))
   r.set_defaults(run=cmd_owner_texts)


def progress(phase: str, text: str) -> None:
   """!Prints build and run progress to stderr.
   @param phase  one of core.bench.PHASES
   @param text   what happens
   @return None
   """
   print(f"bench: {text}", file=sys.stderr)


def cmd_new(args: argparse.Namespace) -> int:
   """!`bench new`.
   @param args  parsed arguments
   @return exit status
   """
   p = open_project(args)
   doc = bench.create(p, args.name, format_name=args.format, parties=args.party, seed=args.seed)
   print(bench.relative_name(p, doc.path))
   return 0


def cmd_list(args: argparse.Namespace) -> int:
   """!`bench list`.
   @param args  parsed arguments
   @return exit status
   """
   p = open_project(args)
   paths = bench.scenario_paths(p)
   if not paths:
      print(f"no scenarios in {bench.relative_name(p, bench.scenario_folder(p))} (make one: bench new NAME)")
   for path in paths:
      try:
         doc = bench.open_scenario(path)
      except bench.BenchError as e:
         print(f"{bench.relative_name(p, path)}  (cannot read: {e})")
         continue
      expect = bench.expected_path(doc)
      mark = "" if expect is None else f"  expect {expect.name}" + ("" if expect.is_file() else " (missing)")
      print(f"{bench.relative_name(p, path)}  {doc.data.get('name', '')!s}{mark}")
   return 0


def cmd_validate(args: argparse.Namespace) -> int:
   """!`bench validate`.
   @param args  parsed arguments
   @return exit status
   """
   p = open_project(args)
   paths = [bench.resolve(p, s) for s in args.scenarios] if args.scenarios else bench.scenario_paths(p)
   bad = 0
   for path in paths:
      name = bench.relative_name(p, path)
      try:
         problems = bench.validate(bench.open_scenario(path).data, p)
      except bench.BenchError as e:
         problems = [str(e)]
      if problems:
         bad += 1
         for pr in problems:
            print(f"{name}: {pr}")
      else:
         print(f"{name}: ok")
   return FAILED_STATUS if bad else 0


def cmd_run(args: argparse.Namespace) -> int:
   """!`bench run`.
   @param args  parsed arguments
   @return exit status
   """
   p = open_project(args)
   path = bench.resolve(p, args.scenario)
   doc = bench.open_scenario(path)
   result = bench.run(p, doc, args.rng, bench.parse_traces(args.trace), progress, args.cache, args.jobs)
   for row in result.events() if not args.json else []:
      print(row.text if row.kind == "line" else f"  [{row.kind}] {row.text}")
   for r in result.records if args.json else []:
      print(json.dumps(r))
   if result.errors():
      for e in result.errors():
         print(f"bench error: {e}", file=sys.stderr)
      return FAILED_STATUS
   if args.save_expected:
      out = bench.save_expected(doc, result.transcript())
      print(f"saved the transcript as {bench.relative_name(p, out)}", file=sys.stderr)
   return 0


def cmd_check(args: argparse.Namespace) -> int:
   """!`bench check`.
   @param args  parsed arguments
   @return exit status
   """
   p = open_project(args)
   path = bench.resolve(p, args.scenario)
   if bench.expected_path(bench.open_scenario(path)) is None:
      raise CommandError(f"{bench.relative_name(p, path)} names no expected transcript (run it with "
                         "--save-expected, or set \"expect\")")
   problems = bench.check(p, path, args.rng, args.cache, progress, args.jobs)
   for pr in problems:
      print(f"FAIL {pr}")
   if not problems:
      print(f"{bench.relative_name(p, path)}: transcript matches")
   return FAILED_STATUS if problems else 0


def cmd_build(args: argparse.Namespace) -> int:
   """!`bench build`.
   @param args  parsed arguments
   @return exit status
   """
   p = open_project(args)
   print(bench.build(p, args.rng, args.cache, progress, args.jobs))
   return 0


def cmd_generators(args: argparse.Namespace) -> int:
   """!`bench generators` (a malformed reference manifest: the engine's generator, the error and exit 1).
   @param args  parsed arguments
   @return 0, or 1 with a malformed reference manifest
   """
   p = open_project(args)
   found, problem = bench.generators_or_default(p)
   for name, source in found.items():
      print(f"{name}  {source if source is not None else ENGINE_GENERATOR}")
   if problem is not None:   # a malformed reference manifest: the engine's generator still works (C4)
      print(f"capsule-studio: error: {problem}", file=sys.stderr)
      return 1
   return 0


def cmd_owner_texts(args: argparse.Namespace) -> int:
   """!`bench owner-texts`: prints a scenario's owner texts switch, or sets it and saves the scenario.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   doc = bench.open_scenario(bench.resolve(p, args.scenario))
   if args.value is not None:
      with doc.edit("Owner texts"):
         changed = bench.set_owner_texts(doc, SWITCH[args.value])
      if changed:
         doc.save()
   print(f"owner_texts: {'on' if bench.owner_texts(doc.data) else 'off'}")
   return 0


def cmd_migrate(args: argparse.Namespace) -> int:
   """!`bench migrate`: renames the retired poke keys of every scenario and saves the scenarios it changed.
   @param args  parsed arguments
   @return 0
   """
   p = open_project(args)
   done = bench.migrate_scenarios(p)
   for doc in p.edited_documents():
      if doc.schema == bench.SCHEMA and doc.dirty:
         doc.save()
   for line in done:
      print(line)
   print(f"migrated {len(done)} poke key(s)" if done else "nothing to migrate")
   return 0
