#!/usr/bin/env python3
"""!Tests for the studio side of the engine's E13b (package S17), no Qt:

- point handlers of moves, volatiles and side conditions (core.holders on
  their .ceffect point members; the owner lists from the engine's
  battlec.pipelines OWNER_SOURCES / OWNER_KINDS) and `battle FILE handler`;
- the damage trace's move_type point (the hit's type) and the point runner's
  volatiles, side conditions, side battlers and genes (core.pipelines,
  `battle FILE damage`);
- the logic palette, words and name lists (reset_stages, delay, reward,
  end_battle, the silent stage, species fields);
- the delayed end-of-turn phase (core.structure.turn, `turn show`);
- the bench's owner_texts switch and the data's member level (core.bench,
  `bench owner-texts`);
- the read commands keeping their project alive (the weak reference from a
  Document to its project, S16's generation fix).

The Starter (neutral) tests run everywhere; the Gen-3 ones (the reference
repo's templates/gen3 has E13b's moves, side conditions and points) are
skipped without the reference repo. Expected values come from the data or
the engine, not written down.
"""
from __future__ import annotations

import gc
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, bench, engine, holders, logic, pipelines  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import Document, DocumentError  # noqa: E402
from capsule_studio.core.structure import conditions, turn  # noqa: E402
from sample_data import copy_battle_data, gen3_data, make_game, needs_gen3  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## Gen-3 sample names E13b's rows use (reference README): a move with move_type handlers, a move with a power
## handler against a volatile, that volatile, the screens and the weather that turns Sky Ball's type.
SKY_BALL, WHIRL, AIRBORNE, HARD_WALL, GLOW_WALL, RAIN = ("Sky Ball", "Whirl", "airborne", "Hard Wall", "Glow Wall",
                                                         "Rain")


def run_cli(*argv: str) -> tuple[int, str]:
   """!Runs the CLI.
   @param argv  arguments
   @return (exit status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      try:
         status = cli(list(argv))
      except SystemExit as e:
         status = int(e.code or 0)
   return status, out.getvalue() + err.getvalue()


class OwnerListTests(unittest.TestCase):
   """!The point handler owner lists are the engine's."""

   def test_from_the_engine(self) -> None:
      """!handler_owners() / point_owner_lists() are the engine's OWNER_SOURCES / OWNER_KINDS (battle_compiler's
      re-exports); the manifest handler lists (MANIFEST_HANDLER_LISTS) and the logic-member lists split them; the
      condition kinds with handlers follow.
      @return None
      """
      bp = engine.tool("battle_compiler")
      self.assertEqual(pipelines.handler_owners(), bp.OWNER_SOURCES)
      self.assertEqual(logic.point_owner_lists(), bp.OWNER_KINDS)
      self.assertEqual(holders.handler_lists(), bp.OWNER_KINDS)
      manifest, members = holders.manifest_lists(), holders.logic_lists()
      self.assertEqual(sorted(manifest + members), sorted(bp.OWNER_SOURCES))
      self.assertFalse(set(manifest) & set(members))
      self.assertEqual(set(manifest), set(bp.MANIFEST_HANDLER_LISTS))
      keys = bp.KEYS
      for key in members:   # the engine reads no manifest "handlers" for these
         self.assertNotIn(holders.HANDLERS_KEY, keys.get(bp.OWNER_KINDS[key], set()), key)
      self.assertIn("moves", members)
      for kind in conditions.handler_kinds():
         self.assertIn(conditions.list_key(kind), bp.OWNER_KINDS)
      self.assertTrue(holders.takes_source(["target.side"], "side"))
      self.assertTrue(holders.takes_source(["move"], "move"))
      self.assertFalse(holders.takes_source(["user.passive"], "side"))

   def test_c5_engine_features(self) -> None:
      """!C5: try_switch takes per_foe in the handler picker (the engine's PER_FOE_HOOKS: a foe's trap); the bench's
      trapped records are a row type of their own (the engine's TRAPPED_RECORD), with their text.
      @return None
      """
      ec = engine.tool("effect_compiler")
      catalog = {h["name"]: h for h in logic.hook_catalog()}
      self.assertEqual({n for n, h in catalog.items() if h["per_foe"]}, set(ec.PER_FOE_HOOKS))
      self.assertTrue(catalog["try_switch"]["per_foe"])
      self.assertEqual(bench.TRAPPED_KIND, engine.tool("bench_scenario").TRAPPED_RECORD)
      self.assertIn(bench.TRAPPED_KIND, bench.RECORD_KINDS)
      text = bench.record_text({"t": bench.TRAPPED_KIND, "turn": 2, "battler": 0})
      self.assertTrue(text.startswith("trapped: battler 0 on turn 2"), text)


class PointMemberCommentTests(unittest.TestCase):
   """!review3 probe p_points as a regression (C5): a point member added to a Gen-3 move keeps its source's
   comments."""

   @needs_gen3
   def test_point_member_keeps_comments(self) -> None:
      """!Cold Haze's comment inside its hit phase ("a step per battler") stays when a point member is added.
      @return None
      """
      with tempfile.TemporaryDirectory() as tmp:
         folder = Path(tmp)
         copy_battle_data(gen3_data() / "battle.json", folder)
         p = BattleProject.open(folder / "battle.json")
         doc = p.battle
         choices = holders.point_choices(p, "moves")
         self.assertIn("move_type", choices)
         with doc.edit("Add point"):
            holders.add_handler(doc, "moves", "Cold Haze", choices[0])
         text = p.effects["effects/moves.ceffect"].text
         self.assertIn("a step per battler", text)
         self.assertIsNone(p.error_now())


class StarterTests(BattleTestCase):
   """!The neutral Starter: no point takes a move; the palette, the delayed phase, the bench."""

   def test_moves_without_points(self) -> None:
      """!A Starter move has no point it may handle (no point names the move source), so adding one is refused.
      @return None
      """
      p = self.project
      move = p.names("moves")[0]
      self.assertEqual(holders.point_choices(p, "moves"), [])
      self.assertEqual(holders.handlers(p.battle, "moves", move), [])
      point = pipelines.point_names(p.ruleset)[0]
      with self.assertRaisesRegex(DocumentError, "is not a point a move handles"):
         with p.battle.edit("x"):
            holders.add_handler(p.battle, "moves", move, point, holders.NEW_CODE, holders.point_choices(p, "moves"))
      with self.assertRaises(DocumentError):
         holders.handlers(p.battle, "moves", "No Such Move")

   def test_palette_words_names(self) -> None:
      """!The palette has E13b's statements (and one per primitive of the effect compiler), each parses; the
      silent flag is a mode word; the new hooks and refs come from the engine's tables.
      @return None
      """
      ec = engine.tool("effect_compiler")
      templates = logic.statement_templates(self.project)
      words = {t.split()[0].rstrip(";") for _g, _l, t in templates if t is not None}
      for _group, _label, text in templates:
         if text is not None:
            logic.parse_statement(text)
      generated = {label for g, label, _t in templates if g == logic.PALETTE_MORE}
      written = {t.split()[0].rstrip(";") for entries in logic.PALETTE.values() for _l, t in entries}
      for name in ec.PRIMITIVES:   # every primitive: a written template or a generated one
         self.assertTrue(name in written or name.replace("_", " ") in generated, name)
      labels = {label: text for _g, label, text in templates}
      for name in ("reset_stages", "delay", "reward", "end_battle"):
         self.assertIn(name, words)
      self.assertTrue(labels["stage (silent)"].endswith(" silent;"))
      self.assertIn("silent", logic.words()["modes"])
      hooks = logic.words()["hooks"]
      for hook in ("try_switch", "redirect", "land"):
         self.assertIn(hook, hooks)
      refs = {name for name, _arg, _kind in logic.ref_catalog()["battler"]}
      for ref in ("gene", "human", "unowned", "delayed_turns", "species_field", "targeted_by"):
         self.assertIn(ref, refs)
      self.assertIn("active_count", {name for name, _a, _k in logic.ref_catalog()["side"]})
      self.assertEqual(logic.name_lists(self.project)["species_fields"],
                       [f["name"] for f in self.project.structure.data.get("species_fields", [])])
      self.assertIn("land", {h["name"] for h in logic.hook_catalog("move") if h["phase"]})

   def test_delayed_phase(self) -> None:
      """!The delayed phase is one of the engine's, with a note; at most once; `turn show` and the help name it.
      @return None
      """
      rules = engine.tool("battle_compiler")
      self.assertIn("delayed", turn.end_phases())
      self.assertIn("delay", turn.phase_note("delayed"))
      self.assertIn("at most once", turn.phase_note("delayed"))
      self.assertIn("exactly once", turn.phase_note(rules.ONCE_PHASES[0]))
      doc = self.project.battle
      with doc.edit("Add phase"):
         turn.add_phase(doc, "delayed")
      self.assertIsNone(turn.compile_turn(doc)[1])
      with self.assertRaises(DocumentError):
         with doc.edit("Again"):
            turn.add_phase(doc, "delayed")
      self.assertTrue(any(line.startswith("phases: ") and "delayed:" in line for line in turn.turn_lines(doc)))

   def test_reserved_points(self) -> None:
      """!move_type is the engine's reserved point (ruleset_compiler.MOVE_TYPE_POINT), with a note.
      @return None
      """
      rc = engine.tool("ruleset_compiler")
      self.assertIn(rc.MOVE_TYPE_POINT, pipelines.reserved_points())

   def test_bench_owner_texts_and_level(self) -> None:
      """!The owner_texts switch (the engine's scenario key) and a new member's level from the data.
      @return None
      """
      self.assertIn(bench.owner_texts_key(), engine.tool("bench_scenario").SCENARIO_KEYS)
      p = self.project
      doc = Document(bench.new_scenario(p, "t"), schema=bench.SCHEMA)
      self.assertFalse(bench.owner_texts(doc.data))
      with doc.edit("on"):
         self.assertTrue(bench.set_owner_texts(doc, True))
      self.assertIs(doc.data[bench.owner_texts_key()], True)
      self.assertEqual(bench.validate(doc.data), [])
      with doc.edit("off"):
         self.assertTrue(bench.set_owner_texts(doc, False))
      self.assertNotIn(bench.owner_texts_key(), doc.data)
      first = p.entry("parties", p.names("parties")[0])["members"][0]["level"]
      self.assertEqual(bench.new_member_level(p), first)
      scenario = {"parties": [{"members": [{"species": "x", "level": 1}, {"species": "y", "level": 3}]}]}
      self.assertEqual(bench.new_member_level(p, scenario, 0), 3)   # the party's last member
      with mock.patch.object(BattleProject, "names", lambda _s, _k: []):   # no party: the highest level
         self.assertEqual(bench.new_member_level(p), battle.level_max(p.structure))


class ReadCommandProjectTests(unittest.TestCase):
   """!The read commands keep their project alive while helpers reach it through a Document (S17 check of S16's
   generation fix: format list, turn show, transfer list, learning / exp show, intro)."""

   def test_project_alive(self) -> None:
      """!Every core.logic.project_of() call made by these commands finds the project, even after a collection.
      @return None
      """
      real = logic.project_of
      lost: list[str] = []

      def spy(doc: object) -> object:
         """!project_of() after a collection: records a lost project."""
         gc.collect()
         found = real(doc)
         if doc is not None and found is None:
            lost.append(str(getattr(doc, "path", doc)))
         return found

      with tempfile.TemporaryDirectory() as tmp:
         b = str(make_game(Path(tmp)))
         party = BattleProject.open(b).names("parties")[0]
         with mock.patch.object(logic, "project_of", spy):
            for argv in (("format", "list"), ("turn", "show"), ("transfer", "list"), ("learning", "show"),
                         ("exp", "show"), ("intro", party), ("generation", "show")):
               status, out = run_cli("battle", b, *argv)
               self.assertEqual(status, 0, (argv, out))
      self.assertEqual(lost, [])


@needs_gen3
class Gen3Tests(BattleTestCase):
   """!E13b's owners on the reference repo's Gen-3 template."""

   def sample(self) -> Path:
      """!The Gen-3 template.
      @return folder
      """
      return gen3_data()

   def test_move_point_members(self) -> None:
      """!A move's point handlers are its logic's point members: listed, added (a new logic block for a move
      without one), changed, moved, removed; the data still compiles; point users name the move.
      @return None
      """
      p = self.project
      choices = holders.point_choices(p, "moves")
      rc = engine.tool("ruleset_compiler")
      self.assertIn(rc.MOVE_TYPE_POINT, choices)
      sky = holders.handlers(p.battle, "moves", SKY_BALL)
      self.assertIn(rc.MOVE_TYPE_POINT, [h["point"] for h in sky])
      self.assertIn(f"move {SKY_BALL}", pipelines.point_users(p.ruleset, rc.MOVE_TYPE_POINT, p.battle))
      before = holders.handlers(p.battle, "moves", WHIRL)
      with p.battle.edit("Add"):
         self.assertEqual(holders.add_handler(p.battle, "moves", WHIRL, "power", "{ modify by 3; }", choices, 0), 0)
      rows = holders.handlers(p.battle, "moves", WHIRL)
      self.assertEqual(rows[1:], before)
      self.assertIn("modify by 3", rows[0]["code"])
      self.assertIn("modify by 3", logic.owner_text(p, f"move:{WHIRL}"))
      with p.battle.edit("Move"):
         self.assertTrue(holders.move_handler(p.battle, "moves", WHIRL, 0, 1))
      self.assertEqual(holders.handlers(p.battle, "moves", WHIRL)[0], before[0])
      with p.battle.edit("Set"):
         holders.set_handler(p.battle, "moves", WHIRL, 1, code="{ modify by 4; }")
      self.assertIn("modify by 4", holders.handlers(p.battle, "moves", WHIRL)[1]["code"])
      with p.battle.edit("Remove"):
         holders.remove_handler(p.battle, "moves", WHIRL, 1)
      self.assertEqual(holders.handlers(p.battle, "moves", WHIRL), before)
      self.assertIsNone(p.compile()[1])
      # a move without logic gets a block
      plain = next(m for m in p.names("moves") if not any(r.name == m for r in logic.owners(p, "move")))
      with p.battle.edit("Add to a plain move"):
         holders.add_handler(p.battle, "moves", plain, "power", "{ modify by 2; }", choices)
      self.assertEqual([h["point"] for h in holders.handlers(p.battle, "moves", plain)], ["power"])
      self.assertIsNone(p.compile()[1])
      with self.assertRaises(DocumentError):   # a bad code is refused by the parser
         with p.battle.edit("Bad"):
            holders.add_handler(p.battle, "moves", plain, "power", "{ modify by ; }", choices)

   def test_condition_point_members(self) -> None:
      """!A side condition's point handlers (the screen point takes target.side) and a volatile's.
      @return None
      """
      p = self.project
      self.assertIn("side_condition", conditions.handler_kinds())
      self.assertIn("volatile", conditions.handler_kinds())
      screen = holders.point_choices(p, "side_conditions")
      self.assertTrue(screen)
      rows = holders.handlers(p.structure, "side_conditions", HARD_WALL)
      self.assertEqual([h["point"] for h in rows], screen[:1])
      with p.structure.edit("Add"):
         holders.add_handler(p.structure, "side_conditions", HARD_WALL, screen[0], "{ modify by 1; }", screen)
      self.assertEqual(len(holders.handlers(p.structure, "side_conditions", HARD_WALL)), len(rows) + 1)
      self.assertIsNone(p.compile()[1])

   def test_handler_cli(self) -> None:
      """!`battle FILE handler moves NAME list|add` edits the move's logic and saves the source.
      @return None
      """
      b = str(self.dir / "battle.json")
      status, out = run_cli("battle", b, "handler", "moves", WHIRL, "list")
      self.assertEqual(status, 0, out)
      self.assertIn("point power", out)
      status, out = run_cli("battle", b, "handler", "moves", WHIRL, "add", "power", "{ modify by 3; }")
      self.assertEqual(status, 0, out)
      self.assertIn("modify by 3", logic.owner_text(BattleProject.open(b), f"move:{WHIRL}"))
      status, out = run_cli("battle", b, "handler", "nothing", WHIRL, "list")
      self.assertNotEqual(status, 0)
      status, out = run_cli("battle", b, "hooks", "--kind", "side_condition")
      self.assertIn("point screen", out)
      self.assertNotIn("point power:", out)
      status, out = run_cli("battle", b, "point", "list")
      self.assertIn(engine.tool("ruleset_compiler").MOVE_TYPE_POINT + ": reserved", out)

   def test_damage_trace(self) -> None:
      """!The move_type point gives the hit's type (the chart and same-type read it); a side condition's and a
      volatile's handlers run; the side's battlers and the genes reach the handlers.
      @return None
      """
      p = self.project
      sp = p.names("species")
      plain = pipelines.damage_trace(p, sp[0], sp[1], SKY_BALL)
      rain = pipelines.damage_trace(p, sp[0], sp[1], SKY_BALL, weather=RAIN)
      self.assertEqual(plain.hit_type, plain.own_type)
      self.assertNotEqual(rain.hit_type, rain.own_type)
      self.assertIn("hit type", rain.lines()[0])
      compiled = p.compile()[0]
      typed = compiled["names"]["types"].index(rain.hit_type)
      fx = pipelines.type_effect(compiled, typed, rain.defender)
      self.assertEqual(rain.inputs["type_exp"], fx["exp"])
      self.assertEqual(rain.inputs["same_type"], int(typed in rain.attacker["types"]))
      # Whirl's power doubles against an airborne target (its own point handler reads the volatile)
      base = pipelines.damage_trace(p, sp[0], sp[1], WHIRL).damage
      self.assertGreater(pipelines.damage_trace(p, sp[0], sp[1], WHIRL, defender_volatiles=[AIRBORNE]).damage, base)
      # a screen of its category lowers the damage; crits pass it
      category = compiled["names"]["categories"][compiled["moves"][compiled["names"]["moves"].index(WHIRL)]
                                                 ["category"]]
      wall = GLOW_WALL if category == "special" else HARD_WALL
      screened = pipelines.damage_trace(p, sp[0], sp[1], WHIRL, defender_side=[wall]).damage
      self.assertLess(screened, base)
      crit = pipelines.damage_trace(p, sp[0], sp[1], WHIRL, crit=True)
      self.assertEqual(pipelines.damage_trace(p, sp[0], sp[1], WHIRL, crit=True, defender_side=[wall]).damage,
                       crit.damage)
      two = pipelines.damage_trace(p, sp[0], sp[1], WHIRL, defender_side=[wall], defender_active=2).damage
      self.assertNotEqual(two, screened)   # a third in a double battle, a half alone
      self.assertEqual(len(rain.attacker["genes"]), len(compiled["stats"]))
      with self.assertRaises(DocumentError):
         pipelines.damage_trace(p, sp[0], sp[1], WHIRL, defender_side=["No Such Wall"])
      with self.assertRaises(DocumentError):
         pipelines.damage_trace(p, sp[0], sp[1], WHIRL, defender_active=0)
      b = str(self.dir / "battle.json")
      status, out = run_cli("battle", b, "damage", sp[0], sp[1], WHIRL, "--defender-side", wall)
      self.assertEqual((status, out.strip()), (0, str(screened)))
      status, out = run_cli("battle", b, "damage", sp[0], sp[1], SKY_BALL, "--weather", RAIN, "--trace")
      self.assertIn("hit type", out)

   def test_species_fields_names(self) -> None:
      """!The ref picker's species field names are the structure's.
      @return None
      """
      names = logic.name_lists(self.project)["species_fields"]
      self.assertTrue(names)
      self.assertEqual(names, [f["name"] for f in self.project.structure.data["species_fields"]])


class BenchCliTests(unittest.TestCase):
   """!`bench owner-texts`."""

   def test_owner_texts(self) -> None:
      """!Prints the switch; on / off set it and save the scenario.
      @return None
      """
      with tempfile.TemporaryDirectory() as tmp:
         b = str(make_game(Path(tmp)))
         self.assertEqual(run_cli("battle", b, "bench", "new", "t")[0], 0)
         status, out = run_cli("battle", b, "bench", "owner-texts", "t")
         self.assertEqual((status, out.strip()), (0, "owner_texts: off"))
         status, out = run_cli("battle", b, "bench", "owner-texts", "t", "on")
         self.assertEqual((status, out.strip()), (0, "owner_texts: on"))
         saved = json.loads((Path(tmp) / bench.SCENARIO_FOLDER / "t.json").read_text(encoding="utf-8"))
         self.assertIs(saved[bench.owner_texts_key()], True)
         status, out = run_cli("battle", b, "bench", "owner-texts", "t", "off")
         self.assertEqual(out.strip(), "owner_texts: off")


if __name__ == "__main__":
   unittest.main()
