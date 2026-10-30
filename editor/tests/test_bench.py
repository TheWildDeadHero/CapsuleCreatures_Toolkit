#!/usr/bin/env python3
"""!Tests for capsule_studio.core.bench (battle bench scenarios, the build, runs, results, expected transcripts)
and the `battle FILE bench` commands (no Qt needed).

Without a toolchain the tests use a stand-in bench (a script that prints recorded output) and a mocked PATH.
With CAPSULE_BENCH_BUILD=1 the slow tests build the real bench for a copy of the Starter sample (CMake and a C++
compiler needed; a first build takes a minute or two), run the engine's Starter golden scenario unowned_single with the
default generator, check its expected transcript and rebuild without configuring again. ClassicBuildTests (also
needing the reference repo) build the classic sample's bench with the reference repo's Method-1 generator and replay
its WP-2 golden wild_single.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli import bench_cmds  # noqa: E402
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import bench, engine  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from sample_data import (CLASSIC, make_classic_game, make_game, method1_source, needs_classic,  # noqa: E402
                         reference_root)

## The slow tests run only when this is "1".
BUILD_ENV = "CAPSULE_BENCH_BUILD"
## Recorded bench output: a header, two draws before the first line, a VM step with its source, a stop.
OUTPUT = "\n".join(json.dumps(r) for r in [
   {"t": "bench", "schema": "capsule.bench/1", "manifest": "battle.json", "rng": "default", "scenario": "s"},
   {"t": "line", "text": "-- s"},
   {"t": "rng", "n": 1, "value": 7, "state": "0x1", "turn": 1, "phase": "begin_turn"},
   {"t": "rng", "n": 2, "value": 9, "state": "0x2", "turn": 1, "phase": "act", "owner": "move Flare Claw",
    "hook": "on_hit", "program": 3, "pc": 4, "depth": 1, "file": "effects/moves.ceffect", "line": 12, "column": 5},
   {"t": "line", "text": "turn 1"},
   {"t": "vm", "op": "between", "value": 3, "owner": "move Flare Claw", "hook": "on_hit", "program": 3, "pc": 4,
    "depth": 1, "file": "effects/moves.ceffect", "line": 12, "column": 5},
   {"t": "event", "kind": "damage", "battler": 1, "target": 0, "extra": 0, "a": 5, "b": 0, "turn": 1},
   {"t": "line", "text": "> It hit 3 times!"},
   {"t": "stop", "reason": "end", "steps": 9, "turn": 1, "outcome": "Won", "draws": 2, "faults": 0,
    "events_lost": 0},
]) + "\n"


def fake_bench(folder: Path, text: str, wait: float = 0) -> Path:
   """!A stand-in bench: a script that reads its input, waits and prints recorded output.
   @param folder  where to write it
   @param text    what it prints
   @param wait    seconds it waits first
   @return the script
   """
   out = folder / "recorded.jsonl"
   out.write_text(text, encoding="utf-8")
   script = folder / "fake_bench"
   script.write_text(f"#!{sys.executable}\nimport sys, time\nsys.stdin.read()\ntime.sleep({wait})\n"
                     f"sys.stdout.write(open({str(out)!r}, encoding='utf-8').read())\n", encoding="utf-8")
   script.chmod(script.stat().st_mode | stat.S_IXUSR)
   return script


class BenchTestCase(unittest.TestCase):
   """!A game copy per test.

   @var root
   The game folder.
   @var battle_json
   Its battle.json.
   @var project
   The opened BattleProject.
   """

   def setUp(self) -> None:
      """!Copies the game.
      @return None
      """
      self.root = Path(tempfile.mkdtemp(prefix="capsule_bench_"))
      self.battle_json = make_game(self.root)
      self.project = BattleProject.open(self.battle_json)

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def cli(self, *args: str) -> tuple[int, str, str]:
      """!Runs `battle FILE bench ...`.
      @param args  the bench arguments
      @return (status, stdout, stderr)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         status = cli(["battle", str(self.battle_json), "bench", *args])
      return status, out.getvalue(), err.getvalue()


class ScenarioTests(BenchTestCase):
   """!Scenarios: places, new, create, list, resolve, validate, expected transcripts."""

   def test_places(self) -> None:
      """!Scenarios live in the game folder's bench/; the build in build/bench/RNG; names are relative.
      @return None
      """
      self.assertEqual(bench.game_folder(self.project), self.root.resolve())
      self.assertEqual(bench.scenario_folder(self.project), self.root.resolve() / "bench")
      self.assertEqual(bench.cache_folder(self.project, "mine"), self.root.resolve() / "build" / "bench" / "mine")
      self.assertEqual(bench.relative_name(self.project, self.root / "bench" / "a.json"), "bench/a.json")
      self.assertEqual(bench.scenario_paths(self.project), [])
      # Battle data in no game: its own folder.
      loose = Path(tempfile.mkdtemp(prefix="capsule_bench_loose_"))
      self.addCleanup(shutil.rmtree, loose, True)
      for f in self.project.files():
         out = loose / f.relative_to(self.battle_json.parent)
         out.parent.mkdir(parents=True, exist_ok=True)
         shutil.copy(f, out)
      self.assertEqual(bench.game_folder(BattleProject.open(loose / "battle.json")), loose.resolve())

   def test_new_scenario(self) -> None:
      """!A new scenario: the data's first two parties, a chosen format and parties, a wild foe; bad names refused.
      @return None
      """
      s = bench.new_scenario(self.project, "a")
      self.assertEqual(s["schema"], bench.SCHEMA)
      self.assertEqual(s["seed"], bench.DEFAULT_SEED)
      self.assertEqual(s["parties"], [{"side": 0, "controller": "human", "data": "Novice Kit"},
                                      {"side": 1, "controller": "ai", "data": "Scholar Wen"}])
      self.assertNotIn("format", s)
      s = bench.new_scenario(self.project, "b", "Double", ["Duo Ash & Bly"], seed=9)
      self.assertEqual((s["format"], s["seed"]), ("Double", 9))
      # the wild creature's level is the data's (S17): the first party's first member
      first = self.project.entry("parties", self.project.names("parties")[0])["members"][0]["level"]
      self.assertEqual(s["parties"][1], {"side": 1, "controller": "ai", "flags": ["unowned"],
                                         "members": [{"species": "Emberkit", "level": first}]})
      self.assertEqual(bench.validate(s), [])
      with self.assertRaisesRegex(bench.BenchError, "no format"):
         bench.new_scenario(self.project, "c", "Quintuple")
      with self.assertRaisesRegex(bench.BenchError, "no party"):
         bench.new_scenario(self.project, "c", parties=["Nobody"])
      with self.assertRaisesRegex(bench.BenchError, "at most two"):
         bench.new_scenario(self.project, "c", parties=["Novice Kit"] * 3)

   def test_create_list_resolve(self) -> None:
      """!create() writes bench/NAME.json once; the list skips other JSON; resolve() takes names and paths.
      @return None
      """
      doc = bench.create(self.project, "wild")
      self.assertEqual(doc.path, self.root.resolve() / "bench" / "wild.json")
      self.assertEqual(json.loads(doc.path.read_text(encoding="utf-8"))["name"], "wild")
      with self.assertRaisesRegex(bench.BenchError, "already exists"):
         bench.create(self.project, "wild.json")
      for bad in ("", "a/b", ".hidden"):
         with self.assertRaisesRegex(bench.BenchError, "plain file name"):
            bench.create(self.project, bad)
      (self.root / "bench" / "notes.json").write_text('{"schema": "capsule.other/1"}', encoding="utf-8")
      (self.root / "bench" / "broken.json").write_text("{", encoding="utf-8")
      self.assertEqual([p.name for p in bench.scenario_paths(self.project)], ["broken.json", "wild.json"])
      for name in ("wild", "wild.json", "bench/wild.json", str(doc.path)):
         self.assertEqual(bench.resolve(self.project, name), doc.path, name)
      with self.assertRaisesRegex(bench.BenchError, "scenarios: bench/broken.json, bench/wild.json"):
         bench.resolve(self.project, "tame")
      with self.assertRaises(bench.BenchError):
         bench.open_scenario(self.root / "bench" / "broken.json")
      with self.assertRaises(bench.BenchError):
         bench.open_scenario(self.root / "bench" / "notes.json")

   def test_validate_is_the_engines(self) -> None:
      """!Validation is the engine tool's (the studio adds no rules of its own).
      @return None
      """
      s = bench.new_scenario(self.project, "a")
      self.assertEqual(bench.validate(s), bench.tool().validate(s))
      s["colour"] = "red"
      s["seed"] = -1
      problems = bench.validate(s)
      self.assertIn("colour: unknown member", problems)
      self.assertTrue(any(p.startswith("seed:") for p in problems))
      self.assertEqual(problems, bench.tool().validate(s))

   def test_validate_poke_names(self) -> None:
      """!With the project, the pokes' names are checked against the data (the engine's check_names()):
      counters only of volatiles that have one, stage names and each stage's own range.
      @return None
      """
      s = bench.new_scenario(self.project, "a")
      s["pokes"] = [{"party": 0, "member": 0, "counters": {"dazed": 2}, "stages": {"attack": 2, "critical": 1}}]
      self.assertEqual(bench.validate(s, self.project), [])
      s["pokes"] = [{"party": 0, "member": 0, "counters": {"flinch": 1, "nothing": 1},
                     "stages": {"critical": 6, "luck": 1}}]
      problems = bench.validate(s, self.project)
      self.assertIn("pokes[0].counters.flinch: the volatile flinch has no counter", problems)
      self.assertIn("pokes[0].counters.nothing: unknown volatile 'nothing'", problems)
      self.assertIn("pokes[0].stages.critical: 0 to 3 (the stage's range)", problems)
      self.assertTrue(any(p.startswith("pokes[0].stages.luck: unknown stage") for p in problems))
      self.assertEqual(bench.validate(s), [])   # the shape alone is fine

   def test_set_scenario_and_expected(self) -> None:
      """!set_scenario() keeps the schema and reports changes; save_expected() writes NAME.expected.txt beside the
      scenario, sets "expect" (one undo step) and saves; expected_problems() names the first differing line.
      @return None
      """
      doc = bench.create(self.project, "wild")
      data = dict(doc.data, seed=5)
      del data["schema"]
      with doc.edit("Seed"):
         self.assertTrue(bench.set_scenario(doc, data))
      self.assertEqual((doc.data["schema"], doc.data["seed"]), (bench.SCHEMA, 5))
      with doc.edit("Nothing"):
         self.assertFalse(bench.set_scenario(doc, doc.data))
      self.assertIsNone(bench.expected_path(doc))
      out = bench.save_expected(doc, "-- wild\nturn 1\n")
      self.assertEqual(out, self.root.resolve() / "bench" / "wild.expected.txt")
      self.assertEqual(doc.data["expect"], "wild.expected.txt")
      self.assertFalse(doc.dirty)
      self.assertEqual(json.loads(doc.path.read_text(encoding="utf-8"))["expect"], "wild.expected.txt")
      self.assertEqual(bench.expected_text(doc), "-- wild\nturn 1\n")
      self.assertEqual(doc.undo_label(), "Save as expected")
      self.assertEqual(bench.expected_problems("a\nb\n", "a\nb\n"), [])
      self.assertEqual(bench.expected_problems("a\nb\n", "a\nc\n", "x.txt"),
                       ["x.txt:2\n  expected: b\n  bench:    c"])
      self.assertEqual(bench.expected_problems("a\n", "a\nb\n", "x.txt"),
                       ["x.txt:2\n  expected: <end>\n  bench:    b"])
      self.assertEqual(bench.expected_problems("a\r\n", "a\n", "x.txt"), ["x.txt: differs only in line endings"])


class TextFormTests(unittest.TestCase):
   """!The text forms of choices, answers, stages, names and table cells."""

   def test_choices(self) -> None:
      """!Choices round trip; several on a line are one per field position; bad ones name their line.
      @return None
      """
      choices = ["first", "run", {"move": 2}, {"move": "Flare Claw", "target": 1}, {"switch": 1},
                 [{"move": 0}, "first"]]
      text = bench.choices_text(choices)
      self.assertEqual(text, "first\nrun\nmove 2\nmove Flare Claw @1\nswitch 1\nmove 0 | first")
      self.assertEqual(bench.parse_choices(text + "\n\n"), choices)
      for bad in ("fly", "move", "switch x", "move Strike @x"):
         with self.assertRaisesRegex(bench.BenchError, "choices line 2"):
            bench.parse_choices("first\n" + bad)
      self.assertEqual(bench.tool().validate({"schema": bench.SCHEMA, "seed": 1, "choices": choices,
                                              "parties": [{"side": 0, "data": "x"}]}), [])

   def test_answers_stages_names(self) -> None:
      """!Answers, stages and name lists round trip.
      @return None
      """
      answers = [{"learn_move": 0}, {"switch_target": 1}, {"choice": 2}]
      self.assertEqual(bench.parse_answers(bench.answers_text(answers)), answers)
      with self.assertRaisesRegex(bench.BenchError, "answers line 1"):
         bench.parse_answers("forget 1")
      stages = {"attack": 2, "defence": -1, "evasion": 0}
      self.assertEqual(bench.stages_text(stages), "attack +2, defence -1, evasion +0")
      self.assertEqual(bench.parse_stages(bench.stages_text(stages)), stages)
      with self.assertRaisesRegex(bench.BenchError, "NAME VALUE"):
         bench.parse_stages("attack")
      self.assertEqual(bench.parse_names(bench.names_text(["Strike", None, "Flare Claw"])), ["Strike", None,
                                                                                           "Flare Claw"])
      self.assertEqual(bench.parse_traces("rng, vm"), ["rng", "vm"])
      with self.assertRaisesRegex(bench.BenchError, "unknown trace"):
         bench.parse_traces("rng,colour")
      self.assertEqual(bench.trace_options({"trace": {"vm": True, "rng": False}}), ["vm"])

   def test_cells(self) -> None:
      """!Table rows: empty cells leave keys out, "-" is null, hidden keys are kept, bad numbers name the column.
      @return None
      """
      member = {"species": "Voltmink", "level": 10, "moves": ["Shock Fang", None], "status": None, "seed": 7,
                "resources": {"uses": [5, 3], "ep": 4}, "passive_slot": 1}
      texts = bench.cells(member, bench.MEMBER_COLUMNS)
      self.assertEqual(texts, ["Voltmink", "10", "", "", "Shock Fang, -", "", "-", "uses 5/3, ep 4"])
      self.assertEqual(bench.from_cells(texts, bench.MEMBER_COLUMNS, member), member)
      self.assertEqual(bench.from_cells(["Voltmink", "12", "", "", "", "", "", ""], bench.MEMBER_COLUMNS, member),
                       {"species": "Voltmink", "level": 12, "seed": 7, "passive_slot": 1})
      # a value with "/" is a move resource's list (one per slot)
      self.assertEqual(bench.parse_pools("uses 7/6, mp 2"), {"uses": [7, 6], "mp": 2})
      with self.assertRaisesRegex(bench.BenchError, "NAME VALUE"):
         bench.parse_pools("uses seven")
      with self.assertRaisesRegex(bench.BenchError, "level: 'x' is not a number"):
         bench.from_cells(["Voltmink", "x"], bench.MEMBER_COLUMNS)
      poke = {"party": 1, "member": 0, "hp": 30, "status": "Scorch", "counters": {"dazed": 2},
              "volatiles": ["dazed"], "stages": {"defence": -2}, "resources": {"mp": 0}}
      texts = bench.cells(poke, bench.POKE_COLUMNS)
      self.assertEqual(texts[[k for k, _kind in bench.POKE_COLUMNS].index("counters")], "dazed 2")
      self.assertEqual(bench.from_cells(texts, bench.POKE_COLUMNS), poke)
      party = {"side": 1, "flags": ["unowned"], "members": [member]}
      self.assertEqual(bench.from_cells(bench.cells(party, bench.PARTY_COLUMNS), bench.PARTY_COLUMNS, party), party)


class ResultTests(unittest.TestCase):
   """!Results: the event list with draw markers, trace positions, record texts."""

   def test_events_and_traces(self) -> None:
      """!Lines carry the draws made before them; VM and RNG rows point at owner, hook, pc and source.
      @return None
      """
      run = bench.BenchRun.from_output(OUTPUT, rng="default")
      self.assertTrue(run.ok())
      self.assertEqual(run.transcript(), "-- s\nturn 1\n> It hit 3 times!\n")
      lines = run.events(["line"])
      self.assertEqual([(r.text, r.draws) for r in lines], [("-- s", 0), ("turn 1", 2), ("> It hit 3 times!", 0)])
      rows = run.events()
      self.assertEqual([r.kind for r in rows], ["line", "rng", "rng", "line", "vm", "event", "line", "stop"])
      self.assertEqual([r.turn for r in rows], [0, 1, 1, 1, 1, 1, 1, 1])
      pos = run.trace_positions()[0]
      self.assertEqual(pos, bench.TracePosition("move:Flare Claw", "on_hit", 4, "effects/moves.ceffect", 12, 5))
      self.assertEqual(bench.trace_position(run.of("rng")[1]), pos)
      self.assertIsNone(bench.trace_position(run.of("rng")[0]))
      self.assertIn("between = 3: move Flare Claw on_hit pc 4 (effects/moves.ceffect:12:5)", rows[4].text)
      self.assertIn("draw #2: 9 [act] by move Flare Claw", rows[2].text)
      self.assertIn("stop: end after 9 steps", rows[-1].text)
      self.assertEqual(len(run.events(None)), len(run.records) - 1)   # the header is left out
      bad = bench.BenchRun.from_output(json.dumps({"t": "error", "where": "format", "message": "unknown"}), 1)
      self.assertFalse(bad.ok())
      self.assertEqual(bad.errors(), ["format: unknown"])
      self.assertEqual(bench.BenchRun.from_output("", 1, "crashed").errors(), ["crashed"])
      with self.assertRaises(bench.BenchError):
         bench.BenchRun.from_output("not json")

   def test_template_and_rng(self) -> None:
      """!A VM record of template code names its template (E7 "template"); a scenario names its generator.
      @return None
      """
      record = {"t": "vm", "owner": "status Scorch", "hook": "on_residual", "pc": 2, "template": "status Scorch"}
      pos = bench.trace_position(record)
      self.assertEqual((pos.owner, pos.file, pos.template), ("status:Scorch", "", "status Scorch"))
      # any generator name (E11: a game's or the reference repo's; build() says when nobody provides it)
      self.assertEqual(bench.scenario_rng({"rng": "method1"}), "method1")
      self.assertEqual(bench.scenario_rng({"rng": "mine"}), "mine")
      for bad in ("Not A Name", 3):
         self.assertEqual(bench.scenario_rng({"rng": bad}), bench.DEFAULT_RNG)
      self.assertEqual(bench.scenario_rng({}), bench.DEFAULT_RNG)
      self.assertEqual(bench.expected_problems("a\nb\n", "a\nc\n", "x.txt"), ["x.txt:2\n  expected: b\n  bench:    c"])


class GeneratorTests(BenchTestCase):
   """!The generators a bench can link (E11, C1): the engine's and the ones the reference repo declares in its
   compat/generators.json (capsule.generators/1, read by the engine's bench_scenario.load_generators())."""

   def fake_reference(self, generators: list[dict] | None = None) -> Path:
      """!A reference checkout with a generators manifest and one generator source.
      @param generators  the manifest's entries, or None for one generator "alt"
      @return the folder
      """
      ref = self.root / "rules"
      (ref / "templates").mkdir(parents=True)
      src = ref / "compat" / "alt" / "src"
      src.mkdir(parents=True)
      (src / "random_alt.cpp").write_text("// a generator\n", encoding="utf-8")
      (src / "random_unlisted.cpp").write_text("// not declared: not a generator\n", encoding="utf-8")
      entries = generators if generators is not None else [{"name": "alt", "source": "alt/src/random_alt.cpp",
                                                            "description": "a test generator"}]
      manifest = {"schema": bench.tool().GENERATORS_SCHEMA, "generators": entries}
      (ref / "compat" / bench.tool().GENERATORS_FILE).write_text(json.dumps(manifest), encoding="utf-8")
      return ref

   def test_sources(self) -> None:
      """!default has no source; the reference repo's manifest names the others (file names alone do not); build()
      refuses a name nobody provides, and the CLI lists them; a malformed manifest says why.
      @return None
      """
      ref = self.fake_reference()
      with mock.patch.dict(os.environ, {"CAPSULE_REFERENCE": str(ref)}):
         self.assertEqual(bench.reference_generators(), {"alt": (ref / "compat" / "alt" / "src" /
                                                                 "random_alt.cpp").resolve()})
         self.assertEqual(list(bench.generators(self.project)), [bench.DEFAULT_RNG, "alt"])
         self.assertIsNone(bench.generator_source(self.project, bench.DEFAULT_RNG))
         with self.assertRaisesRegex(bench.BenchError, "unknown generator 'gone'"):
            bench.build(self.project, "gone")
         status, out, _err = self.cli("generators")
         self.assertEqual(status, 0)
         self.assertEqual(out.splitlines()[0], f"{bench.DEFAULT_RNG}  {bench_cmds.ENGINE_GENERATOR}")
         self.assertIn("alt  ", out)
         self.assertNotIn("unlisted", out)
      with mock.patch.dict(os.environ, {"CAPSULE_REFERENCE": str(self.root / "nowhere")}):
         self.assertEqual(bench.generators(None)[bench.DEFAULT_RNG], None)   # (a sibling checkout may add its own)

   def test_malformed_manifest(self) -> None:
      """!A manifest naming a missing source is refused with the engine's message.
      @return None
      """
      ref = self.fake_reference([{"name": "gone", "source": "gone/src/random_gone.cpp"}])
      with mock.patch.dict(os.environ, {"CAPSULE_REFERENCE": str(ref)}):
         with self.assertRaisesRegex(bench.BenchError, "does not exist"):
            bench.generators(self.project)

   @needs_classic
   def test_reference_method1(self) -> None:
      """!With the real reference repo, method1 is its compat/classic generator (skipped without the repo).
      @return None
      """
      self.assertEqual(bench.generator_source(self.project, "method1"), method1_source().resolve())
      self.assertEqual(bench.reference_generators()["method1"].parent.parent.parent.parent, reference_root())


class MigrationTests(BenchTestCase):
   """!Scenarios writing the poke keys C1 retired (status_turns, escalation): reported, migrated as one undo step,
   saved by `bench migrate`."""

   def old_scenario(self) -> Path:
      """!A saved scenario with the retired poke keys.
      @return its file
      """
      d = bench.new_scenario(self.project, "old")
      d["pokes"] = [{"party": 1, "member": 0, "status_turns": 2, "hp": 5, "escalation": 1}]
      path = bench.scenario_folder(self.project) / "old.json"
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text(json.dumps(d), encoding="utf-8")
      return path

   def test_report_and_migrate(self) -> None:
      """!validate() names the retired keys; migrate keeps each key's place; undo takes every scenario back.
      @return None
      """
      path = self.old_scenario()
      data = json.loads(path.read_text(encoding="utf-8"))
      problems = bench.validate(data, self.project)
      self.assertTrue(any("status_turns" in p and "status_counter" in p for p in problems), problems)
      self.assertEqual(bench.retired_keys_in(data), ["pokes[0].status_turns", "pokes[0].escalation"])
      self.assertEqual(bench.scenarios_to_migrate(self.project), ["bench/old.json"])
      done = bench.migrate_scenarios(self.project)
      self.assertEqual(len(done), len(bench.retired_poke_keys()))
      doc = self.project.scenario(path)
      self.assertEqual(list(doc.data["pokes"][0]), ["party", "member", "status_counter", "hp", "status_aux"])
      self.assertEqual(bench.validate(doc.data, self.project), [])
      self.assertTrue(doc.dirty)
      doc.undo()
      self.assertIn("status_turns", doc.data["pokes"][0])
      # both names: the new one wins
      poke = {"status_turns": 1, "status_counter": 3}
      bench.migrate_scenario({"pokes": [poke]})
      self.assertEqual(poke, {"status_counter": 3})

   def test_cli(self) -> None:
      """!`bench migrate` writes the migrated scenarios; a second run has nothing to do.
      @return None
      """
      path = self.old_scenario()
      status, out, _err = self.cli("migrate")
      self.assertEqual(status, 0)
      self.assertIn("status_turns -> status_counter", out)
      self.assertIn("status_counter", json.loads(path.read_text(encoding="utf-8"))["pokes"][0])
      self.assertEqual(self.cli("migrate")[1].strip(), "nothing to migrate")


@unittest.skipIf(os.name == "nt", "the stand-in bench is a POSIX script")
class RunnerTests(BenchTestCase):
   """!The Runner over a stand-in bench, the toolchain check, cancelling."""

   def test_run_and_cancel(self) -> None:
      """!run() validates, pipes the scenario and parses the output; cancel() kills a running bench.
      @return None
      """
      scenario = bench.new_scenario(self.project, "s")
      phases = []
      run = bench.Runner().run(fake_bench(self.root, OUTPUT), scenario, ["vm"], "mine",
                               lambda phase, text: phases.append(phase))
      self.assertEqual(phases, [bench.PHASE_RUN, bench.PHASE_DONE])
      self.assertEqual((run.rng, len(run.of("line"))), ("mine", 3))
      with self.assertRaisesRegex(bench.BenchError, "unknown trace"):
         bench.Runner().run(fake_bench(self.root, OUTPUT), scenario, ["colour"])
      with self.assertRaisesRegex(bench.BenchError, "seed"):
         bench.Runner().run(fake_bench(self.root, OUTPUT), dict(scenario, seed="x"))
      slow = fake_bench(self.root, OUTPUT, wait=60)
      runner = bench.Runner()
      threading.Timer(0.5, runner.cancel).start()
      started = time.monotonic()
      with self.assertRaises(bench.Cancelled):
         runner.run(slow, scenario)
      self.assertLess(time.monotonic() - started, 30)
      self.assertTrue(runner.cancelled)
      runner.reset()
      self.assertEqual(len(runner.run(fake_bench(self.root, OUTPUT), scenario).records), len(run.records))

   def test_toolchain_missing(self) -> None:
      """!Without CMake or a compiler the build says what is needed; nothing else needs them.
      @return None
      """
      with mock.patch.object(bench.shutil, "which", return_value=None), mock.patch.dict(os.environ, {"CXX": ""}):
         missing = bench.toolchain()
         self.assertEqual(len(missing), 2)
         self.assertIn("CMake 3.24", missing[0])
         self.assertIn("C++20 compiler", missing[1])
         with self.assertRaises(bench.ToolchainMissing) as caught:
            bench.build(self.project)
         self.assertEqual(caught.exception.missing, missing)
         self.assertIn("building it needs CMake", str(caught.exception))
         status, _out, err = self.cli("run", "x")
         self.assertEqual(status, 1)
         self.assertIn("no scenario 'x'", err)
         self.cli("new", "wild")
         status, _out, err = self.cli("run", "wild")
         self.assertEqual(status, 1)
         self.assertIn("needs CMake", err)
         status, _out, err = self.cli("build", "--rng", "default")
         self.assertIn("needs CMake", err)
         status, _out, err = self.cli("build", "--rng", "nobodys")   # checked before the toolchain
         self.assertIn("unknown generator 'nobodys'", err)
      with mock.patch.object(bench.subprocess, "run") as version:
         version.return_value.stdout = "cmake version 3.20.1\n"
         self.assertTrue(any("found 3.20" in m for m in bench.toolchain()) or shutil.which("cmake") is None)


class CommandTests(BenchTestCase):
   """!`battle FILE bench new|list|validate|check` without building."""

   def test_new_list_validate(self) -> None:
      """!new writes bench/NAME.json; list shows names, titles and expected files; validate checks every one.
      @return None
      """
      status, out, _err = self.cli("new", "wild")
      self.assertEqual((status, out.strip()), (0, "bench/wild.json"))
      status, out, _err = self.cli("new", "duo", "--format", "Double", "--party", "Novice Kit", "--party",
                                   "Scholar Wen", "--seed", "4")
      self.assertEqual(status, 0)
      duo = json.loads((self.root / "bench" / "duo.json").read_text(encoding="utf-8"))
      self.assertEqual((duo["format"], duo["seed"]), ("Double", 4))
      status, out, _err = self.cli("list")
      self.assertEqual(out.splitlines(), ["bench/duo.json  duo", "bench/wild.json  wild"])
      status, out, _err = self.cli("validate")
      self.assertEqual((status, out.splitlines()), (0, ["bench/duo.json: ok", "bench/wild.json: ok"]))
      duo["colour"] = "red"
      (self.root / "bench" / "duo.json").write_text(json.dumps(duo), encoding="utf-8")
      status, out, _err = self.cli("validate", "duo")
      self.assertEqual((status, out.strip()), (1, "bench/duo.json: colour: unknown member"))
      status, _out, err = self.cli("check", "wild")
      self.assertEqual(status, 1)
      self.assertIn("names no expected transcript", err)
      status, _out, err = self.cli("new", "wild")
      self.assertIn("already exists", err)


@unittest.skipUnless(os.environ.get(BUILD_ENV) == "1", f"set {BUILD_ENV}=1 to build and run the real bench")
class BuildTests(unittest.TestCase):
   """!The real bench, built once for a copy of the Starter (slow)."""

   ## The generator the bench links.
   rng = bench.DEFAULT_RNG

   @classmethod
   def make(cls, root: Path) -> Path:
      """!The game copy.
      @param root  the game folder
      @return its battle.json
      """
      return make_game(root)

   def golden_scenario(self) -> Path:
      """!The scenario the transcript test replays (with its "expect" beside it, relative).
      @return the engine's Starter golden scenario unowned_single
      """
      return engine.root() / "tests" / "bench" / "starter" / "unowned_single.json"

   @classmethod
   def setUpClass(cls) -> None:
      """!Copies the game and builds its bench with the engine's generator.
      @return None
      """
      cls.root = Path(tempfile.mkdtemp(prefix="capsule_bench_build_"))
      cls.battle_json = cls.make(cls.root)
      cls.project = BattleProject.open(cls.battle_json)
      cls.phases: list[str] = []
      cls.exe = bench.build(cls.project, cls.rng, progress=lambda phase, text: cls.phases.append(phase))

   @classmethod
   def tearDownClass(cls) -> None:
      """!Removes the copy and its build.
      @return None
      """
      shutil.rmtree(cls.root, ignore_errors=True)

   def golden(self) -> tuple[Path, str]:
      """!The golden scenario (golden_scenario()) as a game scenario, and its transcript.
      @return (scenario file, expected text)
      """
      src = self.golden_scenario()
      data = json.loads(src.read_text(encoding="utf-8"))
      expected = (src.parent / data.pop("expect")).read_text(encoding="utf-8")
      out = self.root / "bench" / "golden.json"
      out.parent.mkdir(exist_ok=True)
      out.write_text(json.dumps(data), encoding="utf-8")
      return out, expected

   def test_build_run_check_rebuild(self) -> None:
      """!The first build configures; a run reproduces the golden transcript with traces; a saved expected
      transcript checks; the CLI runs and checks it; a second build only rebuilds.
      @return None
      """
      # the tool's output lines come as PHASE_LOG (E7's build(progress=)); the phases are configure only
      self.assertEqual([ph for ph in self.phases if ph != bench.PHASE_LOG], [bench.PHASE_CONFIGURE])
      self.assertTrue(self.exe.is_file())
      self.assertTrue(str(self.exe).startswith(str(bench.cache_folder(self.project, self.rng))))
      path, expected = self.golden()
      doc = bench.open_scenario(path)
      run = bench.run(self.project, doc, self.rng, ["rng", "vm"])
      self.assertTrue(run.ok(), run.errors())
      self.assertEqual(run.transcript(), expected)
      self.assertEqual(len(run.of("rng")), run.of("stop")[0]["draws"])
      self.assertGreater(sum(r.draws for r in run.events(["line"])), 0)
      bench.save_expected(doc, run.transcript())
      self.assertEqual(bench.check(self.project, path, self.rng), [])
      status = cli(["battle", str(self.battle_json), "bench", "check", "golden", "--rng", self.rng])
      self.assertEqual(status, 0)
      out = io.StringIO()
      with redirect_stdout(out), redirect_stderr(io.StringIO()):
         status = cli(["battle", str(self.battle_json), "bench", "run", "golden", "--rng", self.rng, "--trace",
                       "rng,vm"])
      self.assertEqual(status, 0)
      self.assertIn("  [rng] draw #1:", out.getvalue())
      title = json.loads(self.golden_scenario().read_text(encoding="utf-8"))["name"]
      self.assertTrue(out.getvalue().startswith(f"-- {title}\n"))
      cache = (bench.cache_folder(self.project, self.rng) / bench.CMAKE_CACHE).stat().st_mtime
      phases = []
      self.assertEqual(bench.build(self.project, self.rng, progress=lambda phase, text: phases.append(phase)),
                       self.exe)
      self.assertEqual([ph for ph in phases if ph != bench.PHASE_LOG], [bench.PHASE_BUILD])
      self.assertEqual((bench.cache_folder(self.project, self.rng) / bench.CMAKE_CACHE).stat().st_mtime, cache)
      # A wrong expected transcript fails with its first differing line.
      (path.parent / "golden.expected.txt").write_text(expected.replace("turn 1", "turn one"), encoding="utf-8")
      problems = bench.check(self.project, path, self.rng)
      self.assertEqual(len(problems), 1)
      self.assertIn("expected: turn one", problems[0])

   def trace_scenario(self) -> Path:
      """!The scenario of the VM trace test.
      @return the engine's pokes_trace case (on the Starter)
      """
      return engine.root() / "tests" / "bench" / "cases" / "pokes_trace.json"

   def test_vm_trace_positions(self) -> None:
      """!A VM trace names owners of the sources with lines inside them (the pokes_trace case of the engine).
      @return None
      """
      src = self.trace_scenario()
      run = bench.Runner().run(self.exe, json.loads(src.read_text(encoding="utf-8")), ("vm",), self.rng)
      self.assertTrue(run.ok(), run.errors())
      # Code from a source file names it as the manifest lists it; template code names its template.
      sourced = [p for p in run.trace_positions() if p.file in self.project.effects]
      self.assertGreater(len(sourced), 0)
      for pos in sourced:
         self.assertGreater(pos.line, 0)
         self.assertIn(":", pos.owner)
         lines = self.project.effects[pos.file].text.splitlines()
         self.assertLessEqual(pos.line, len(lines))

   def test_build_failure_shows_the_output(self) -> None:
      """!Battle data that does not compile fails the (incremental) build with the compiler's message; fixed, it
      builds again.
      @return None
      """
      good = self.battle_json.read_text(encoding="utf-8")
      data = json.loads(good)
      data["species"][0]["types"] = ["Nonexistent"]
      self.battle_json.write_text(json.dumps(data), encoding="utf-8")
      try:
         with self.assertRaisesRegex(bench.BenchError, "building the bench failed:(.|\n)*Nonexistent"):
            bench.build(self.project, self.rng)
      finally:
         self.battle_json.write_text(good, encoding="utf-8")
      self.assertEqual(bench.build(self.project, self.rng), self.exe)


@needs_classic
@unittest.skipUnless(os.environ.get(BUILD_ENV) == "1", f"set {BUILD_ENV}=1 to build and run the real bench")
class ClassicBuildTests(BuildTests):
   """!The real bench of the reference repo's classic sample with its Method-1 generator (compat/classic, found by
   core.bench.generators()): the WP-2 golden wild_single replays (slow; skipped without the reference repo)."""

   ## The reference repo's generator.
   rng = "method1"

   @classmethod
   def make(cls, root: Path) -> Path:
      """!The classic sandbox as a game.
      @param root  the game folder
      @return its battle.json
      """
      return make_classic_game(root)

   def golden_scenario(self) -> Path:
      """!The WP-2 golden scenario.
      @return the reference repo's classic/bench/wild_single.json
      """
      return reference_root() / CLASSIC / "bench" / "wild_single.json"

   def trace_scenario(self) -> Path:
      """!A scenario of the classic sample for the VM trace test (run with the vm trace).
      @return the reference repo's classic/bench/rival_ana.json
      """
      return reference_root() / CLASSIC / "bench" / "rival_ana.json"


if __name__ == "__main__":
   unittest.main()
