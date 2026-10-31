#!/usr/bin/env python3
"""!Tests for capsule_studio.core.pipelines (D-20 D: the ruleset's pipelines
and points, their analysed ranges, damage_trace()), the named formulas of
core.battle, the neutral new ruleset, and the `battle FILE pipeline / point /
damage / formula / rule` commands. No Qt.

Uses a copy of the engine's Starter sample. ClassicGridTests check
damage_trace() against the WP-2 damage grid of the reference repo's classic
sample (classic/golden/damage_grid.txt, written by its C++ golden program
through battle::damage_preview()) on sampled lines of each section; they are
skipped without the reference repo.
"""
from __future__ import annotations

import copy
import io
import json
import re
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, engine, pipelines  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import chart, stages  # noqa: E402
from sample_data import CLASSIC, needs_classic, reference_root  # noqa: E402
from test_battle import BattleTestCase, ClassicTestCase  # noqa: E402

## Genes and training of every golden grid creature (the reference repo's classic/tests/battle_golden_tests.cpp).
GRID_GENES = 20
## Training values of every golden grid creature.
GRID_TRAINING = 100
## Training values of the Starter's test creatures (G4: its layout's stat_training is 6 bits; S11 refuses more).
STARTER_TRAINING = 30
## Genes of the Starter's test creatures (its layout's stat_genes is 4 bits: S11 refuses more).
STARTER_GENES = 12
## Q8 shift (x1 = 1 << 8).
Q8_SHIFT = 8
## Raw speed of the speed pipeline trace.
SPEED_RAW = 100
## Highest damage roll index of the classic ruleset (its span is 16; the Starter's comes from its ROLL_SPAN).
ROLL_HIGH = 15
## Every how many grid lines one is checked.
SAMPLE_EVERY = 97
## A key=value field of a golden label (values may hold spaces).
FIELD = re.compile(r"(\w+)=(.*?)(?= \w+=|$)")


def golden_lines() -> list[str]:
   """!The classic damage grid's value lines (section headers dropped; needs_classic tests only).
   @return lines
   """
   ref = reference_root()
   assert ref is not None, "decorate classic tests with needs_classic"
   path = ref / CLASSIC / "golden" / "damage_grid.txt"
   return [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("--")]


class PipelineModelTests(BattleTestCase):
   """!Steps and points of the ruleset Document."""

   def test_steps(self) -> None:
      """!Add, move, set and remove steps; each edit is one undo step; bad steps are refused.
      @return None
      """
      doc = self.project.ruleset
      before = copy.deepcopy(doc.data)
      self.assertEqual(pipelines.pipeline_names(), ["damage", "self_hit", "speed", "accuracy", "crit",
                                                       "effect_odds", "ai_score", "recruit_odds", "encounter_rate",
                                                     "encounter_level", "combine_odds", "combine_fee",
                                                     "nursery_gain", "nursery_fee"])
      self.assertEqual(pipelines.pipeline_inputs("speed"), ["speed_raw", "speed_stage", "speed_stage_id"])
      self.assertEqual(pipelines.pipeline_outputs("crit"), ["crit", "chance", "out_of"])
      with doc.edit("Step"):
         i = pipelines.add_step(doc, "speed", pipelines.make_step("let", "speed", "speed * 2", [1, "STAT_CAP"]), 2)
      self.assertEqual(i, 2)
      self.assertEqual(pipelines.step_text(pipelines.steps(doc, "speed")[2]), "let speed = speed * 2 [1, STAT_CAP]")
      self.assertIsNone(self.project.validate())
      self.assertTrue(doc.undo())
      self.assertEqual(doc.data, before)
      second = dict(pipelines.steps(doc, "damage")[1])   # the sample's own second step
      with doc.edit("Move"):
         self.assertTrue(pipelines.move_step(doc, "damage", 0, 1))
         self.assertFalse(pipelines.move_step(doc, "damage", 0, -1))
      self.assertEqual(pipelines.steps(doc, "damage")[0], second)
      with doc.edit("Set"):
         pipelines.set_step(doc, "speed", 2, "range", None)
         pipelines.set_step(doc, "speed", 0, "expr", "speed_raw")
      self.assertNotIn("range", pipelines.steps(doc, "speed")[2])
      with doc.edit("Remove"):
         removed = pipelines.remove_step(doc, "speed", 1)
      self.assertEqual(removed, {"point": "speed", "on": "speed"})
      self.assertEqual(pipelines.step_text(removed), "point speed on speed")
      self.assertEqual(pipelines.step_text({"roll": "r", "span": "16"}), "roll r in [0, 16)")
      for bad in (lambda: pipelines.make_step("jump", "x", "1"), lambda: pipelines.make_step("let", "x", ""),
                  lambda: pipelines.make_step("let", "x", "1", [1]),
                  lambda: pipelines.add_step(doc, "speed", {"let": "x", "roll": "y"}),
                  lambda: pipelines.set_step(doc, "speed", 0, "span", "2"),
                  lambda: pipelines.remove_step(doc, "speed", 9), lambda: pipelines.steps(doc, "dodge")):
         with self.assertRaises(DocumentError):
            bad()
      with doc.edit("Break"):
         pipelines.set_step(doc, "speed", 0, "expr", "nothing + 1")
      self.assertIn("unknown name", self.project.validate())

   def test_report(self) -> None:
      """!Analysed ranges per step: against this battle when it compiles, else against neutral values.
      @return None
      """
      rows, error, own = pipelines.pipeline_report(self.project, "speed")
      self.assertIsNone(error)
      self.assertTrue(own)
      self.assertEqual([r["kind"] for r in rows], ["let", "point", "let"])
      # the sample's staged stats run to STAGED_CAP (the stat cap x the top stage's x2, engine C4), not STAT_CAP
      staged_cap = self.project.ruleset.data["constants"]["STAGED_CAP"]
      self.assertEqual(rows[0]["range"], (1, staged_cap))
      # the order stat's reach on this battle's stage table: within STAGED_CAP, so the clamp never engages
      self.assertEqual(rows[0]["bounds"][0], 1)
      self.assertLessEqual(rows[0]["bounds"][1], staged_cap)
      self.assertFalse(rows[0]["clamp_active"])
      self.assertTrue(rows[2]["clamp_active"])        # after the speed point
      self.assertEqual(rows[1]["text"], "point speed on speed")
      self.assertIsNone(rows[1]["analysed"])
      roll = next(r for r in pipelines.pipeline_report(self.project, "damage")[0] if r["kind"] == "roll")
      span = self.project.ruleset.data["constants"]["ROLL_SPAN"]   # the sample's damage roll span
      self.assertEqual(roll["bounds"], (0, span - 1))
      with self.project.battle.edit("Break the battle"):
         battle.set_field(self.project.battle, "moves", "Strike", "power", 0)
      rows, error, own = pipelines.pipeline_report(self.project, "speed")
      self.assertFalse(own)
      self.assertIsNotNone(error)
      self.assertEqual(len(rows), 3)
      with self.project.ruleset.edit("Break the ruleset"):
         pipelines.set_step(self.project.ruleset, "speed", 0, "expr", "(")
      self.assertEqual(pipelines.pipeline_report(self.project, "speed")[0], [])

   def test_points(self) -> None:
      """!Points: add, set (holder, sources, range), source order, users, removal checks.
      @return None
      """
      doc = self.project.ruleset
      self.assertEqual(pipelines.point_names(doc), ["offense", "power", "weather", "damage", "guard", "speed", "odds",
                                                    "resist"])
      self.assertIn("user.passive", pipelines.point_sources())
      self.assertIn("passive", pipelines.point_sources())
      with doc.edit("Point"):
         pipelines.add_point(doc, "shield", "target", ["passive"], [1, "STAT_CAP"])
         pipelines.add_source(doc, "shield", "item", 0)
         self.assertTrue(pipelines.move_source(doc, "shield", "passive", -1))
         pipelines.set_point(doc, "shield", "range", [1, 500])
      self.assertEqual(pipelines.point_entry(doc, "shield"), {"holder": "target", "sources": ["passive", "item"],
                                                             "range": [1, 500]})
      self.assertIsNone(self.project.validate())
      with doc.edit("Point use"):
         pipelines.add_step(doc, "damage", pipelines.make_step("point", "defense", "shield"), 4)
      self.assertEqual(pipelines.point_users(doc, "shield"), ["pipeline damage step 4"])
      self.assertIsNone(self.project.validate())
      with self.assertRaisesRegex(DocumentError, "still used"):
         pipelines.remove_point(doc, "shield")
      weather_step = next(i for i, st in enumerate(pipelines.steps(doc, "damage")) if st.get("point") == "weather")
      self.assertEqual(pipelines.point_users(doc, "weather", self.project.battle),
                       [f"pipeline damage step {weather_step}", "weather Storm"])   # after shield's step
      self.assertIn("passive Blaze Heart", pipelines.point_users(doc, "power", self.project.battle))
      self.assertIn("status Shock", pipelines.point_users(doc, "speed", self.project.battle))
      with doc.edit("Unused"):
         pipelines.remove_step(doc, "damage", 4)
         pipelines.remove_source(doc, "shield", "item")
         pipelines.set_point(doc, "shield", "holder", "user")
         pipelines.set_point(doc, "shield", "sources", ["user.status", "weather"])
         pipelines.remove_point(doc, "shield", self.project.battle)
      self.assertNotIn("shield", pipelines.point_names(doc))
      for bad in (lambda: pipelines.add_point(doc, "Power"), lambda: pipelines.add_point(doc, "power"),
                  lambda: pipelines.add_point(doc, "x", "everyone"), lambda: pipelines.add_point(doc, "x", "user",
                                                                                                 ["moon"]),
                  lambda: pipelines.set_point(doc, "power", "sources", ["item", "item"]),
                  lambda: pipelines.set_point(doc, "power", "combine", "max"),
                  lambda: pipelines.remove_source(doc, "power", "weather"), lambda: pipelines.point_entry(doc, "x")):
         with self.assertRaises(DocumentError):
            bad()


class OptionalPipelineTests(BattleTestCase):
   """!effect_odds (E9): optional; without it the engine runs the plain odds (OPTIONAL_PIPELINES)."""

   def test_engine_default(self) -> None:
      """!Left out: shown as the engine's steps ("engine default (plain odds)"); the first edit starts from them;
      reset gives it back; a required pipeline has no default; the CLI shows and resets it.
      @return None
      """
      doc = self.project.ruleset
      rc = engine.tool("ruleset_compiler")
      self.assertFalse(pipelines.is_engine_default(doc, "effect_odds"))   # the Starter's: Intelligence decides
      with doc.edit("Plain odds"):
         self.assertTrue(pipelines.reset_pipeline(doc, "effect_odds"))
      self.assertTrue(pipelines.is_engine_default(doc, "effect_odds"))
      self.assertIsNone(self.project.validate())
      self.assertFalse(pipelines.is_engine_default(doc, "damage"))
      self.assertEqual(pipelines.default_note("effect_odds"), "engine default (plain odds)")
      self.assertEqual(pipelines.shown_steps(doc, "effect_odds"), rc.OPTIONAL_PIPELINES["effect_odds"])
      self.assertNotIn("effect_odds", doc.data["pipelines"])   # looking writes nothing
      rows, error, _own = pipelines.pipeline_report(self.project, "effect_odds")
      self.assertIsNone(error)
      self.assertEqual(len(rows), len(rc.OPTIONAL_PIPELINES["effect_odds"]))
      with doc.edit("Step"):
         pipelines.set_step(doc, "effect_odds", 0, "expr", "effect_chance / 2")
      self.assertFalse(pipelines.is_engine_default(doc, "effect_odds"))
      self.assertEqual(len(pipelines.steps(doc, "effect_odds")), len(rc.OPTIONAL_PIPELINES["effect_odds"]))
      self.assertIsNone(self.project.validate())
      with doc.edit("Reset"):
         self.assertTrue(pipelines.reset_pipeline(doc, "effect_odds"))
      self.assertTrue(pipelines.is_engine_default(doc, "effect_odds"))
      with self.assertRaises(DocumentError):
         pipelines.reset_pipeline(doc, "speed")
      doc.undo()
      self.assertFalse(pipelines.is_engine_default(doc, "effect_odds"))
      b = self.dir / "battle.json"
      out = io.StringIO()
      with redirect_stdout(out):
         self.assertEqual(cli(["battle", str(b), "pipeline", "reset", "effect_odds"]), 0)
         self.assertEqual(cli(["battle", str(b), "pipeline", "show"]), 0)
      self.assertIn("effect_odds: 4 steps (engine default (plain odds))", out.getvalue())
      with redirect_stdout(out):
         self.assertEqual(cli(["battle", str(b), "pipeline", "step", "set", "effect_odds", "0", "expr",
                               "effect_chance"]), 0)
         self.assertEqual(cli(["battle", str(b), "pipeline", "reset", "effect_odds"]), 0)
      self.assertNotIn("effect_odds", BattleProject.open(b).ruleset.data["pipelines"])


class DamageTraceTests(BattleTestCase):
   """!damage_trace(): its steps, decisive tiers and errors."""

   def test_trace(self) -> None:
      """!Every step with its value; point steps show the value before the handlers; unsaved edits count.
      @return None
      """
      t = pipelines.damage_trace(self.project, "Emberkit", "Sproutle", "Fireball", 5, weather="Storm",
                                 attacker_trait="Fierce", defender_trait="Sturdy", passive="Blaze Heart",
                                 genes=STARTER_GENES, training=STARTER_TRAINING)
      self.assertIsNone(t.decisive)
      self.assertEqual(len(t.trace), len(pipelines.steps(self.project.ruleset, "damage")))
      weather = next(s for s in t.trace if s[1] == "point" and "weather" in s[5])
      self.assertGreater(weather[3], weather[4])            # the storm weakens a Fire move
      self.assertEqual(t.trace[-1][2:], ("damage", None, t.damage, "let damage = max(d, 1)"))
      self.assertEqual(t.inputs["same_type"], 1)
      self.assertEqual(t.inputs["type_exp"], 0)              # the Starter's chart multiplies tiers (no exponent)
      scaled = next(s for s in t.trace if s[5] == "let d = type_scale(d)")
      strong = chart.tier_entry(self.project.structure, "strong")["q8"]   # Fire on Bio: the sample's strong tier
      before = next(s for s in reversed(t.trace[:scaled[0]]) if s[2] == "d")[4]
      self.assertEqual(scaled[4], before * strong >> Q8_SHIFT)
      self.assertEqual(t.lines()[-1], f"damage {t.damage}")
      weather_step = next(i for i, st in enumerate(pipelines.steps(self.project.ruleset, "damage"))
                          if st.get("point") == "weather")
      self.assertIn(f"  [{weather_step}] point weather on d: d = ", "\n".join(t.lines()))
      with self.project.ruleset.edit("Double"):
         pipelines.add_step(self.project.ruleset, "damage", pipelines.make_step("let", "damage", "damage * 2",
                                                                                [1, 65535]))
      self.assertEqual(pipelines.damage_trace(self.project, "Emberkit", "Sproutle", "Fireball", 5,
                                              weather="Storm", attacker_trait="Fierce", defender_trait="Sturdy",
                                              passive="Blaze Heart", genes=STARTER_GENES,
                                              training=STARTER_TRAINING).damage,
                       t.damage * 2)

   def test_decisive_and_errors(self) -> None:
      """!A zero tier deals nothing and a KO tier the defender's HP, without running the pipeline; unknown
      names and non-damaging moves are refused.
      @return None
      """
      t = pipelines.damage_trace(self.project, "Voltmink", "Clodbun", "Arc Bolt", 20)   # Lightning on Earth
      self.assertEqual((t.damage, t.decisive, t.trace), (0, "zero", []))
      with self.project.battle.edit("KO"):
         chart.add_tier(self.project.structure, "ko", decisive="ko")
         battle.set_chart(self.project.battle, "Fire", "Bio", "ko")
      t = pipelines.damage_trace(self.project, "Emberkit", "Sproutle", "Flare Claw", 20)
      self.assertEqual((t.damage, t.decisive), (t.defender["max_hp"], "ko"))
      self.assertIn("decisive type tier ko: no pipeline runs", t.lines())
      for kw in ({"move": "Smolder"}, {"move": "Nothing"}, {"attacker": "Nobody"}, {"weather": "Hail"},
                 {"status": "Gloom"}, {"item": "Rock"}, {"attacker_trait": "Shy"}, {"passive": "Wings"}):
         args = {"attacker": "Emberkit", "defender": "Sproutle", "move": "Flare Claw", **kw}
         with self.assertRaises(DocumentError, msg=kw):
            pipelines.damage_trace(self.project, **args)
      with self.project.battle.edit("Break"):
         battle.set_field(self.project.battle, "moves", "Strike", "power", 0)
      with self.assertRaises(DocumentError):
         pipelines.damage_trace(self.project, "Emberkit", "Sproutle", "Flare Claw")

   def test_pipeline_trace(self) -> None:
      """!Any pipeline on given inputs (no point handlers).
      @return None
      """
      out, trace = pipelines.pipeline_trace(self.project, "crit", {"crit_stage": 0, "move_crit_stage": 0},
                                            roll=0)
      first = stages.stage_entry(self.project.battle, "critical")["table"][0]   # the sample's stage-0 odds
      chance, out_of = (int(x) for x in first.split("/"))
      self.assertEqual((out["chance"], out["out_of"], out["crit"]), (chance, out_of, 1))   # roll 0
      self.assertEqual([s[2] for s in trace], ["stage", "chance", "out_of", "r", "crit"])
      self.assertEqual(trace[3][5], "roll r in [0, if(chance > 0 && chance < out_of, out_of, 0))")
      out, _ = pipelines.pipeline_trace(self.project, "speed", {"speed_raw": 100, "speed_stage": 1})
      agility = stages.stat_stage(self.project.battle, "agility")   # the order stat's own stage table
      num, den = agility["table"][1 - agility["range"][0]]
      self.assertEqual(out["speed"], SPEED_RAW * num // den)
      with self.assertRaises(DocumentError):
         pipelines.pipeline_trace(self.project, "speed", {"speed_raw": 100})


@needs_classic
class ClassicGridTests(ClassicTestCase):
   """!damage_trace() equals the WP-2 damage grid of the reference repo's classic sample (skipped without it)."""

   def line(self, **kw: object) -> str:
      """!One grid line's values, as damage_line() of the reference repo's golden program writes them.
      @param kw  damage_trace() arguments (no roll, spread or crit)
      @return "hit=a..b crit=... spread=... spread_crit=..."
      """
      out = []
      for name, spread, crit in (("hit", False, False), ("crit", False, True), ("spread", True, False),
                                 ("spread_crit", True, True)):
         lo = pipelines.damage_trace(self.project, roll=0, spread=spread, crit=crit, **kw).damage
         hi = pipelines.damage_trace(self.project, roll=ROLL_HIGH, spread=spread, crit=crit, **kw).damage
         out.append(f"{name}={lo}..{hi}")
      return " ".join(out)

   def test_golden_grid(self) -> None:
      """!Sampled lines of each section of damage_grid.txt (matchups, passives / items / HP, stages).
      @return None
      """
      lines = golden_lines()
      sample = lines[::SAMPLE_EVERY] + [next(ln for ln in lines if "low_hp" in ln),
                                        next(ln for ln in lines if "item=" in ln and "item=none" not in ln),
                                        next(ln for ln in lines if "offense_stage=6" in ln)]
      kinds = set()
      for line in sample:
         label, want = line.split(" : ")
         f = dict(FIELD.findall(label))
         none = lambda v: None if v == "none" else v   # noqa: E731
         common = {"move": f["move"], "genes": GRID_GENES, "training": GRID_TRAINING}
         if "atk" in f:
            kw = {"attacker": f["atk"], "defender": f["def"], "level": int(f["lv"]), "attacker_trait": "Brave",
                  "defender_trait": "Bold", "passive": f["passive"], "status": none(f["status"]),
                  "weather": none(f["weather"])}
            kinds.add("matchup")
         elif "variant" in f:
            kw = {"attacker": "Cindercub", "defender": "Rippleray", "level": int(f["lv"]), "attacker_trait": "Even",
                  "defender_trait": "Even", "passive": f["passive"], "status": none(f["status"]),
                  "item": none(f["item"]), "weather": none(f["weather"]),
                  "hp_pct": pipelines.PERCENT // 4 if "low_hp" in f["variant"] else pipelines.PERCENT}
            kinds.add("variant")
         else:
            kw = {"attacker": "Cindercub", "defender": "Rippleray", "level": 50, "attacker_trait": "Even",
                  "defender_trait": "Even", "offense_stage": int(f["offense_stage"]),
                  "defense_stage": int(f["defense_stage"])}
            kinds.add("stages")
         self.assertEqual(self.line(**common, **kw), want, line)
      self.assertEqual(kinds, {"matchup", "variant", "stages"})
      self.assertGreater(len(sample), 40)

   def test_damage_command(self) -> None:
      """!`battle FILE damage` gives a golden line's highest roll.
      @return None
      """
      b = self.dir / "battle.json"
      want = next(ln for ln in golden_lines() if ln.startswith("move=Bump atk=Cindercub def=Fernling lv=5 "
                                                                "weather=none status=none"))
      high = want.split("hit=")[1].split("..")[1].split()[0]
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in ("battle", b, "damage", "Cindercub", "Fernling", "Bump", "--level", 5,
                                        "--trait", "Brave", "--defender-trait", "Bold", "--genes", GRID_GENES,
                                        "--training", GRID_TRAINING, "--roll", ROLL_HIGH)])
      self.assertEqual((status, out.getvalue()), (0, f"{high}\n"))


class FormulaTests(BattleTestCase):
   """!Named formulas (formulas with "args", called by pipelines) and the neutral new ruleset."""

   def test_named_formulas(self) -> None:
      """!Listed, evaluated and edited like the slots; added with arguments; removed when nothing calls them.
      @return None
      """
      p = self.project
      # the Starter's ep_regen is the regen formula its resource "ep" names (D-25); train_gain its training's (G4)
      self.assertEqual(battle.named_formulas(p.ruleset), ["damage_base", "ep_regen", "train_gain"])
      self.assertEqual(p.formula_slots()[:5], ["exp_gain", "reward", "escape_odds", "damage_base", "ep_regen"])
      self.assertEqual(battle.formula_users(p.ruleset, "ep_regen"), ["resource ep regen"])
      self.assertEqual(battle.formula_users(p.ruleset, "train_gain"), ["training gain"])
      with self.assertRaisesRegex(DocumentError, "resource ep regen"):
         with p.ruleset.edit("Remove"):
            battle.remove_formula(p.ruleset, "ep_regen")
      self.assertEqual([n for n, _r in p.formula_inputs("damage_base")], ["level", "power", "attack", "defense"])
      with p.ruleset.edit("Named"):
         battle.set_formula(p.ruleset, "halve", "attack / 2", 1, 999, args=["attack"])
      self.assertEqual(battle.formula_entry(p.ruleset, "halve"), {"expr": "attack / 2", "range": [1, 999],
                                                                  "args": ["attack"]})
      self.assertEqual(p.formula("halve", attack=81), 40)
      self.assertIsNone(p.validate())
      with p.ruleset.edit("Use"):
         pipelines.add_step(p.ruleset, "damage", pipelines.make_step("let", "attack", "halve(attack)"), 4)
      self.assertIsNone(p.validate())
      self.assertEqual(battle.formula_users(p.ruleset, "halve"), ["pipeline damage step 4"])
      with self.assertRaisesRegex(DocumentError, "still called"):
         battle.remove_formula(p.ruleset, "halve")
      with p.ruleset.edit("Unuse"):
         pipelines.remove_step(p.ruleset, "damage", 4)
         battle.remove_formula(p.ruleset, "halve")
      self.assertNotIn("halve", p.formula_slots())
      for bad in (lambda: battle.set_formula(p.ruleset, "reward", args=["level"]),
                  lambda: battle.set_formula(p.ruleset, "Bad Name", "1"),
                  lambda: battle.remove_formula(p.ruleset, "exp_gain")):
         with self.assertRaises(DocumentError):
            bad()

   def test_new_ruleset(self) -> None:
      """!New data's ruleset (the Blank template's) is capsule.ruleset/2 and neutral: damage is power x offense /
      defense (no spread, critical, same-type or random factor), critical hits never happen, moves hit by their
      accuracy.
      @return None
      """
      p = BattleProject.create(self.dir / "fresh" / "battle.json", "fresh")
      self.assertEqual(p.ruleset.data["schema"], engine.tool("ruleset_compiler").SCHEMA)
      for key in ("crit", "stab", "spread", "random_min_pct", "damage_steps", "crit_ignores_stages"):
         self.assertNotIn(key, p.structure.data["rules"])
      doc = p.battle
      with doc.edit("Content"):
         battle.add_entry(doc, "moves", "Poke")
         battle.add_entry(doc, "species", "Blob")
         battle.set_field(doc, "species", "Blob", "base", [50, 60, 30, 50])   # hp, power, guard, speed
         battle.learn(doc, "Blob", 1, "Poke")
      self.assertIsNone(p.validate())
      for crit in (False, True):
         for spread in (False, True):
            t = pipelines.damage_trace(p, "Blob", "Blob", "Poke", 10, roll=ROLL_HIGH, crit=crit, spread=spread)
            self.assertEqual(t.damage, 50 * 60 // 30)
      out, _ = pipelines.pipeline_trace(p, "crit", {"crit_stage": 4, "move_crit_stage": 4})
      self.assertEqual(out["crit"], 0)
      out, _ = pipelines.pipeline_trace(p, "accuracy", {"move_accuracy": 70, "accuracy_stage": 6,
                                                        "evasion_stage": 0}, roll=69)
      self.assertEqual((out["hit"], out["chance"], out["out_of"]), (1, 70, 100))
      out, _ = pipelines.pipeline_trace(p, "accuracy", {"move_accuracy": 70, "accuracy_stage": 0,
                                                        "evasion_stage": 0}, roll=70)
      self.assertEqual(out["hit"], 0)


class LogicCliTests(BattleTestCase):
   """!`battle FILE formula | pipeline | point | damage | rule`."""

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command.
      @param argv  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()

   def test_pipeline_and_point_commands(self) -> None:
      """!show, step add / move / set / remove, point list / add / set / remove; refused edits are not saved.
      @return None
      """
      b = self.dir / "battle.json"
      status, out = self.run_cli("battle", b, "pipeline", "show")
      self.assertEqual(status, 0)
      self.assertIn("speed: 3 steps; inputs speed_raw, speed_stage, speed_stage_id; outputs speed", out)
      status, out = self.run_cli("battle", b, "pipeline", "show", "speed")
      # the Starter scales by the order stat's own stage (agility's)
      lo, hi = pipelines.pipeline_report(self.project, "speed")[0][0]["bounds"]
      self.assertIn(f"  [0] let speed = stage_scale(speed_stage_id, speed_raw, speed_stage)  -> speed [{lo}, {hi}] "
                    f"(analysed [{lo}, {hi}], clamp never engages)", out)
      self.assertEqual(self.run_cli("battle", b, "pipeline", "step", "add", "speed", "--let", "speed", "--expr",
                                    "speed + 1", "--range", 1, "STAT_CAP", "--at", 1)[0], 0)
      self.assertEqual(BattleProject.open(b).ruleset.data["pipelines"]["speed"][1],
                       {"let": "speed", "expr": "speed + 1", "range": [1, "STAT_CAP"]})
      self.assertEqual(self.run_cli("battle", b, "pipeline", "step", "move", "speed", 1, "down")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "pipeline", "step", "set", "speed", 2, "range", "null")[0], 0)
      self.assertNotIn("range", BattleProject.open(b).ruleset.data["pipelines"]["speed"][2])
      self.assertEqual(self.run_cli("battle", b, "pipeline", "step", "set", "speed", 2, "expr", "oops")[0], 1)
      self.assertEqual(BattleProject.open(b).ruleset.data["pipelines"]["speed"][2]["expr"], "speed + 1")
      self.assertEqual(self.run_cli("battle", b, "pipeline", "step", "remove", "speed", 2)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "pipeline", "step", "add", "speed", "--roll", "r", "--span",
                                    "2")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "pipeline", "step", "add", "speed", "--point", "speed", "--on",
                                    "speed")[0], 1)    # after the last clamp: the output could reach 0
      self.assertEqual(self.run_cli("battle", b, "pipeline", "step", "add", "speed", "--point", "speed", "--on",
                                    "speed", "--at", 1)[0], 0)
      self.assertEqual(len(BattleProject.open(b).ruleset.data["pipelines"]["speed"]), 5)
      status, out = self.run_cli("battle", b, "point", "list")
      weather_step = next(i for i, st in enumerate(self.project.ruleset.data["pipelines"]["damage"])
                          if st.get("point") == "weather")
      self.assertIn(f"2 weather: holder user, sources weather, range [0, 65535]; used by pipeline damage step "
                    f"{weather_step}, weather Storm", out)
      self.assertEqual(self.run_cli("battle", b, "point", "add", "shield", "--holder", "target", "--sources",
                                    "passive,item", "--range", 0, 999)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "point", "set", "shield", "sources", '["item"]')[0], 0)
      self.assertEqual(self.run_cli("battle", b, "point", "set", "shield", "range", "[1, 50]")[0], 0)
      self.assertEqual(BattleProject.open(b).ruleset.data["points"]["shield"],
                       {"holder": "target", "sources": ["item"], "range": [1, 50]})
      self.assertEqual(self.run_cli("battle", b, "point", "remove", "shield")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "point", "remove", "power")[0], 1)
      self.assertIn("power", BattleProject.open(b).ruleset.data["points"])

   def test_damage_and_formula_commands(self) -> None:
      """!damage (with --trace), formula listing and named formulas, rule --args / --remove.
      @return None
      """
      b = self.dir / "battle.json"
      high = pipelines.damage_trace(self.project, "Emberkit", "Sproutle", "Fireball", 5, roll=ROLL_HIGH,
                                    attacker_trait="Fierce", defender_trait="Sturdy", genes=STARTER_GENES,
                                    training=STARTER_TRAINING).damage
      status, out = self.run_cli("battle", b, "damage", "Emberkit", "Sproutle", "Fireball", "--level", 5, "--trait",
                                 "Fierce", "--defender-trait", "Sturdy", "--genes", STARTER_GENES, "--training",
                                 STARTER_TRAINING, "--roll", ROLL_HIGH)
      self.assertEqual((status, out), (0, f"{high}\n"))
      status, out = self.run_cli("battle", b, "damage", "Emberkit", "Sproutle", "Fireball", "--crit", "--spread",
                                 "--weather", "Storm", "--status", "Scorch", "--trace")
      self.assertEqual(status, 0)
      self.assertTrue(out.startswith("inputs: level 50, move_power 70"))
      self.assertIn("crit 1, spread 1", out)
      self.assertIn("] roll r in [0, ROLL_SPAN): r = 0", out)
      self.assertEqual(self.run_cli("battle", b, "damage", "Emberkit", "Sproutle", "Smolder")[0], 1)
      status, out = self.run_cli("battle", b, "formula")
      self.assertIn("damage_base (named; level, power, attack, defense) = ", out)
      self.assertIn("vital (stat; base, gene, training, awaken, level, trait_pct) = ", out)
      self.assertEqual(self.run_cli("battle", b, "rule", "halve", "--expr", "attack / 2", "--range", 1, 999,
                                    "--args", "attack")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "formula", "halve", "attack=9")[1], "4\n")
      want = self.project.formula("damage_base", level=10, power=40, attack=20, defense=15)
      self.assertEqual(self.run_cli("battle", b, "formula", "damage_base", "level=10", "power=40", "attack=20",
                                    "defense=15")[1], f"{want}\n")
      self.assertEqual(self.run_cli("battle", b, "rule", "halve", "--remove")[0], 0)
      self.assertNotIn("halve", json.dumps(BattleProject.open(b).ruleset.data))
      self.assertEqual(self.run_cli("battle", b, "rule", "damage_base", "--remove")[0], 1)   # pipelines call it


if __name__ == "__main__":
   unittest.main()
