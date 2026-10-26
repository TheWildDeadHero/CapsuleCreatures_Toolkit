#!/usr/bin/env python3
"""!Tests for capsule_studio.core.battle and the battle commands (no Qt needed).

Uses a copy of the engine's Starter sample (tests/sample_data.py); GenThreeTests use the reference repo's Gen-3
sample and are skipped without it.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, engine  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import chart as chart_model  # noqa: E402
from sample_data import copy_battle_data, gen3_data, make_game, needs_gen3, starter_data  # noqa: E402

## A trait percentage that changes nothing (the stat formulas' trait_pct of no trait).
NEUTRAL_PCT = 100
## Q8 factor of x1.
Q8_ONE = 256


class BattleTestCase(unittest.TestCase):
   """!Base: a copy of the Starter sample's battle data per test (sample() picks another sample).

   @var dir
   The copy's folder.
   @var project
   The opened BattleProject.
   """

   def sample(self) -> Path:
      """!The sample folder the test copies.
      @return the Starter's (a Gen-3 test class gives the reference repo's)
      """
      return starter_data()

   def setUp(self) -> None:
      """!Copies the data and opens it.
      @return None
      """
      self.dir = Path(tempfile.mkdtemp(prefix="capsule_battle_"))
      copy_battle_data(self.sample() / "battle.json", self.dir)
      self.project = BattleProject.open(self.dir / "battle.json")

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.dir, ignore_errors=True)


def formula_stats(project: BattleProject, species: str, level: int) -> list[int]:
   """!A species' stats at a level as its stats' ruleset formulas give them (no genes, training, awakening or
   trait): what the sample's numbers are, read from its data rather than written down.
   @param project  BattleProject
   @param species  species name
   @param level    level
   @return one value per stat
   """
   base = project.entry("species", species)["base"]
   return [project.formula(st["formula"], base=b, gene=0, training=0, awaken=0, level=level, trait_pct=NEUTRAL_PCT)
           for st, b in zip(project.structure.data["stats"], base)]


def tier_factor(project: BattleProject, tier: str) -> float:
   """!A scaling tier's multiplier (what set_chart() takes for it).
   @param project  BattleProject
   @param tier     tier name
   @return q8 / 256
   """
   return chart_model.tier_entry(project.structure, tier)["q8"] / Q8_ONE


class GenThreeTestCase(BattleTestCase):
   """!Base of the Gen-3 tests: a copy of the reference repo's Gen-3 sample (decorate the class with needs_gen3)."""

   def sample(self) -> Path:
      """!The reference repo's Gen-3 sample.
      @return folder
      """
      folder = gen3_data()
      assert folder is not None, "decorate Gen-3 test classes with needs_gen3"
      return folder


## A presenter's slide in (24 frames from the side's edge) and out (16 frames), as the Starter's Coach moves.
SLIDE_IN = {"style": "slide", "frames": 24, "from": "side"}
## A presenter's slide out.
SLIDE_OUT = {"style": "slide", "frames": 16, "from": "side"}


def add_cast(doc: battle.Document) -> None:
   """!Adds presenters to a Starter copy (one undo step): Ash and Bly stand beside the stand (20 pixels left and
   right) and present Duo Ash & Bly (Ash speaks); Wen fades in over 32 frames, 8 pixels up, stays, and presents
   Scholar Wen.
   @param doc  the battle Document
   @return None
   """
   with doc.edit("Cast"):
      for name, at, enter, leave in (("Ash", [-20, 0], SLIDE_IN, SLIDE_OUT), ("Bly", [20, 0], SLIDE_IN, SLIDE_OUT),
                                     ("Wen", [0, -8], {"style": "fade", "frames": 32}, {"style": "stay"})):
         battle.add_entry(doc, "presenters", name)
         e = battle.entry(doc, "presenters", name)
         e.update({"sprite": "sprite:PRESENTER", "at": at, "enter": dict(enter), "exit": dict(leave),
                   "intro": "{party} wants to battle!"})
      del battle.entry(doc, "presenters", "Bly")["intro"]
      battle.entry(doc, "parties", "Duo Ash & Bly")["presenters"] = ["Ash", "Bly"]
      battle.entry(doc, "parties", "Scholar Wen")["presenters"] = ["Wen"]


class ProjectTests(BattleTestCase):
   """!Opening, compiling with unsaved edits, previews, saving."""

   def test_compiles_and_previews(self) -> None:
      """!The data compiles; stats come from the engine's formulas.
      @return None
      """
      self.assertIsNone(self.project.validate())
      self.assertEqual(self.project.stats("Emberkit", 5), formula_stats(self.project, "Emberkit", 5))
      c = self.project.ruleset.data["constants"]   # the Starter's damage_base on its own constants
      want = 20 * 40 * (10 + c["DAMAGE_LEVEL_BIAS"]) // ((15 + c["DEFENCE_PAD"]) * c["DAMAGE_DIV"]) + c["DAMAGE_FLAT"]
      self.assertEqual(self.project.formula("damage_base", level=10, power=40, attack=20, defense=15), want)
      with self.assertRaises(DocumentError):
         self.project.formula("damage_base", level=10)
      rows, error = self.project.ruleset_report()
      self.assertIsNone(error)
      # the engine's slots, the Starter's named formulas ep_regen (EP's regen, D-25) and train_gain (its training's
      # gain, G4) and its three stat formulas
      self.assertEqual({r[0] for r in rows}, {"exp_gain", "reward", "escape_odds", "damage_base", "ep_regen",
                                             "train_gain", "vital", "reserve", "core"})
      self.assertTrue(all(len(r) == len(("slot", "bounds", "range", "clamp", "expr")) for r in rows))   # no flag
      self.assertEqual([f.relative_to(self.dir).as_posix() for f in self.project.files()][:3],
                       ["battle.json", "structure.json", "ruleset.json"])

   def test_unsaved_edits_compile(self) -> None:
      """!An unsaved base-stat change shows in the preview; a broken formula is reported.
      @return None
      """
      doc = self.project.battle
      agility = battle.stat_keys(doc).index("agility")
      before = self.project.stats("Emberkit", 50)[agility]
      with doc.edit("Base"):
         battle.set_field(doc, "species", "Emberkit", "base", [45, 40, 50, 62, 58, 44, 42, 48, 99])
      self.assertGreater(self.project.stats("Emberkit", 50)[agility], before)
      with self.project.ruleset.edit("Formula"):
         battle.set_formula(self.project.ruleset, "damage_base", "level * power * attack * defense * 9999")
      self.assertIn("outside int32", self.project.validate())

   def test_new_project_compiles(self) -> None:
      """!New battle data is the Blank template's (S10): it compiles as it is and is neutral, with no PP built in.
      @return None
      """
      p = BattleProject.create(self.dir / "fresh" / "battle.json", "fresh")
      self.assertIsNone(p.validate())
      doc = p.battle
      bc = engine.tool("battle_compiler")
      self.assertEqual(set(doc.data["messages"]), set(bc.MESSAGES))
      # every file records the template it came from, as applying the template does
      blank = battle.blank_template()
      for d in (doc, p.structure, p.ruleset):
         self.assertEqual(d.data["editor"]["template"], {"id": blank.id, "version": blank.version})
      self.assertEqual(doc.data["id"], "fresh")
      self.assertEqual({k: v for k, v in p.structure.data.items() if k != "editor"},
                       {k: v for k, v in json.loads((blank.folder / battle.STRUCTURE_FILE).read_text(
                          encoding="utf-8")).items() if k != "editor"})
      # the structure keys are in structure.json, which battle.json names (E5s)
      self.assertEqual(doc.data[battle.STRUCTURE_KEY], battle.STRUCTURE_FILE)
      self.assertFalse(set(doc.data) & set(battle.structure_keys()))
      self.assertLessEqual(set(p.structure.data) - {"schema", "editor"}, set(battle.structure_keys()))
      text = json.dumps([doc.data, p.structure.data, p.ruleset.data]).lower()
      for word in ("trainer", "pokemon", "nature", "abilit", "prize", "wild", "special", "pp_"):
         self.assertNotIn(word, text)
      with doc.edit("Add"):
         battle.add_entry(doc, "moves", "Poke")
         battle.add_entry(doc, "species", "Blob")
         battle.learn(doc, "Blob", 1, "Poke")
         battle.add_entry(doc, "parties", "Kid")
         battle.party_add(doc, "Kid", "Blob", 3)
         battle.add_entry(doc, "presenters", "Host")
         battle.presenter_attach(doc, "Kid", "Host")
      self.assertEqual(battle.entry(doc, "moves", "Poke")["category"], "physical")
      self.assertEqual(len(battle.entry(doc, "species", "Blob")["base"]), len(battle.stat_keys()))
      # D-25 (E8): the hit points only; no move resource, so a new move states no base (no PP built in)
      self.assertEqual([(r["name"], r["scope"]) for r in p.structure.data["resources"]], [("hp", "battler")])
      self.assertEqual(list(p.structure.data).index("resources"), list(p.structure.data).index("stats") + 1)
      self.assertNotIn("pp", battle.entry(doc, "moves", "Poke"))
      self.assertNotIn("pp", p.structure.data["monster_layout"]["roles"])
      self.assertIn("no_usable_move", doc.data["messages"])
      self.assertIsNone(p.validate())
      # Neutral rules: stats are the base values, the exp text uses the game's term.
      self.assertEqual(p.stats("Blob", 3), [battle.NEW_BASE_STAT] * len(battle.stat_keys()))
      self.assertIn("{@exp}", doc.data["messages"]["exp_gained"])
      p.save_all()
      again = BattleProject.open(self.dir / "fresh" / "battle.json")
      self.assertIn("Blob", again.names("species"))
      with self.assertRaises(DocumentError):
         BattleProject.create(self.dir / "fresh" / "battle.json")


class EditTests(BattleTestCase):
   """!Renames follow references; removals check them; the chart."""

   def test_rename_follows_references(self) -> None:
      """!Renaming a type, move, status and species updates every reference.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Rename"):
         battle.rename_entry(doc, "types", "Fire", "Blaze")
         battle.rename_entry(doc, "moves", "Flare Claw", "Fire Claw")
         battle.rename_entry(doc, "statuses", "Scorch", "Sear")
         battle.rename_entry(doc, "species", "Clodbun", "Clodling")
         battle.rename_entry(doc, "passives", "Thick Hide", "Tough Hide")
         battle.rename_entry(doc, "categories", "physical", "bodily")
         battle.rename_entry(doc, "traits", "Fierce", "Daring")
         battle.rename_entry(doc, "presenters", "Coach", "Coach Senior")
         battle.rename_entry(doc, "items", "Mana Drop", "Mana Bead")
      text = json.dumps(doc.data)
      for old in ('"Fire"', '"Flare Claw"', '"Scorch"', '"Clodbun"', '"Thick Hide"', ': "physical"', '"Fierce"',
                  '"Coach"', '"Mana Drop"'):
         self.assertNotIn(old, text)
      # The effect logic follows: owner blocks and the names inside them (.ceffect sources, through the AST).
      logic_text = "".join(s.text for s in self.project.effects.values())
      for old in ("== Fire ", 'status "Scorch"', 'passive "Thick Hide"', "== physical", "Scorch", "Flare Claw"):
         self.assertNotIn(old, logic_text)
      for new in ("== Blaze", 'status "Sear"', 'passive "Tough Hide"', "== bodily", 'move "Fire Claw"'):
         self.assertIn(new, logic_text)
      self.assertIsNone(self.project.validate())
      with self.assertRaises(DocumentError):
         with doc.edit("Clash"):
            battle.rename_entry(doc, "types", "Blaze", "Water")

   def test_remove_checks_references(self) -> None:
      """!An entry in use can't be removed; an unused one can.
      @return None
      """
      doc = self.project.battle
      with self.assertRaisesRegex(DocumentError, "still used"):
         with doc.edit("Remove"):
            battle.remove_entry(doc, "moves", "Fireball")
      with doc.edit("Add + remove"):
         name = battle.add_entry(doc, "moves", "Spare")
         battle.remove_entry(doc, "moves", name)
      self.assertNotIn("Spare", self.project.names("moves"))

   def test_review_fixes(self) -> None:
      """!Names with spaces in conditions follow renames; removing a type
      takes its chart cells along; a missing ruleset is written on save.
      @return None
      """
      doc = self.project.battle
      conditions = self.project.effect_source("effects/conditions.ceffect")
      with doc.edit("Rename"):
         battle.rename_entry(doc, "weathers", "Storm", "Heavy Storm")
      self.assertIn('weather "Heavy Storm" {', conditions.text)
      self.assertIsNone(self.project.validate())
      with doc.edit("Rename back"):
         battle.rename_entry(doc, "weathers", "Heavy Storm", "Storm")
      self.assertIn('weather "Storm" {', conditions.text)
      with doc.edit("Type"):
         name = battle.add_entry(doc, "types", "Spare")
         battle.set_chart(doc, name, "Bio", tier_factor(self.project, "strong"))
         battle.set_chart(doc, "Bio", name, 0)
         battle.remove_entry(doc, "types", name)
      self.assertNotIn("Spare", json.dumps(self.project.structure.data["chart"]))
      self.assertIsNone(self.project.validate())
      (self.dir / "ruleset.json").unlink()
      fresh = BattleProject.open(self.dir / "battle.json")
      self.assertTrue(fresh.dirty)
      fresh.save_all()
      self.assertTrue((self.dir / "ruleset.json").exists())

   def test_chart(self) -> None:
      """!Chart cells name tiers (a multiplier means the tier of that factor); the default tier is not stored.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Chart"):
         battle.set_chart(doc, "Fire", "Light", tier_factor(self.project, "strong"))
      self.assertEqual(battle.chart_value(doc, "Fire", "Light"), "strong")
      self.assertEqual(self.project.structure.data["chart"]["matchups"]["Fire"]["Light"], "strong")
      with doc.edit("Chart"):
         battle.set_chart(doc, "Fire", "Light", "normal")
      self.assertNotIn("Light", self.project.structure.data["chart"]["matchups"].get("Fire", {}))
      self.assertEqual(battle.chart_value(doc, "Fire", "Light"), "normal")
      for bad in (3, "triple"):
         with self.assertRaises(DocumentError):
            battle.set_chart(doc, "Fire", "Light", bad)

   def test_learnset_and_party(self) -> None:
      """!Learnsets stay sorted; parties are capped at the record's party size.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Learn"):
         battle.learn(doc, "Voltmink", 2, "Strike")
      ls = battle.entry(doc, "species", "Voltmink")["learnset"]
      self.assertEqual(ls, sorted(ls, key=lambda x: x[0]))
      with doc.edit("Forget"):
         self.assertEqual(battle.forget(doc, "Voltmink", "Strike"), 1)
      with doc.edit("Party"):
         while len(battle.entry(doc, "parties", "Novice Kit")["members"]) < battle.party_max():
            battle.party_add(doc, "Novice Kit", "Voltmink", 5)
      with self.assertRaises(DocumentError):
         battle.party_add(doc, "Novice Kit", "Voltmink", 5)
      self.assertIsNone(self.project.validate())


class TermsAndPresenterTests(BattleTestCase):
   """!Terms over the engine's defaults; presenters attached to parties; intros."""

   def test_terms(self) -> None:
      """!The sample's game words over the neutral defaults; setting and resetting one.
      @return None
      """
      doc = self.project.battle
      t = battle.terms(doc)
      self.assertEqual(t["party"], {"one": "Rival", "many": "Rivals"})
      self.assertEqual(t["creature"], {"one": "Creature", "many": "Creatures"})
      self.assertEqual(t["species"]["many"], "Species")
      self.assertEqual(set(t), set(engine.tool("battle_compiler").TERMS))
      self.assertEqual(battle.kind_label(doc, "passives", many=True), "Talents")   # the sample gives it (E7)
      with doc.edit("Plain"):
         battle.set_term(doc, "passive", "Knack")
      # a word without a plural takes the compiler's plural_of() by the section's rule (E7)
      self.assertEqual(battle.kind_label(doc, "passives", many=True), "Knacks")
      self.assertEqual(battle.plural_rules(), list(engine.tool("battle_compiler").PLURAL_RULES))
      with doc.edit("Same"):
         battle.set_plural_rule(doc, "same")
      self.assertEqual(battle.kind_label(doc, "passives", many=True), "Knack")
      self.assertIsNone(self.project.validate())
      with doc.edit("Rule back"):
         battle.set_plural_rule(doc, None)
      with self.assertRaises(DocumentError):
         battle.set_plural_rule(doc, "klingon")
      # a trait that raises or lowers a stat states its percentages (E7): the studio writes the unchanged ones
      with doc.edit("Trait"):
         battle.set_field(doc, "traits", doc.data["traits"][0]["name"], "up", "attack")
      unchanged = engine.tool("battle_compiler").PERCENT
      self.assertEqual(doc.data["traits"][0]["pct"], [unchanged, unchanged])
      self.assertIsNone(self.project.validate())
      self.assertEqual(self.project.scripts_option(engine.tool("battle_compiler")), {})   # in no game
      with doc.edit("Term"):
         battle.set_term(doc, "passive", "Knack", "Knacks")
         battle.set_term(doc, "move", "Skill")
         battle.set_term(doc, "party", None)
      self.assertEqual(battle.kind_label(doc, "passives", many=True), "Knacks")
      self.assertEqual(battle.term(doc, "move", many=True), "Skills")
      self.assertEqual(battle.term(doc, "party"), "Party")
      self.assertNotIn("party", self.project.structure.data["terms"])
      self.assertIsNone(self.project.validate())
      with self.assertRaises(DocumentError):
         battle.set_term(doc, "gizmo", "Thing")
      with self.assertRaises(DocumentError):
         battle.kind_label(doc, "gizmos")

   def test_presenters(self) -> None:
      """!Attach and detach follow the engine's limit; renames and removals follow parties.
      @return None
      """
      doc = self.project.battle
      add_cast(doc)
      with self.assertRaisesRegex(DocumentError, "at most"):
         with doc.edit("Attach"):
            battle.presenter_attach(doc, "Duo Ash & Bly", "Wen")
      with self.assertRaisesRegex(DocumentError, "already"):
         battle.presenter_attach(doc, "Novice Kit", "Coach")
      with self.assertRaisesRegex(DocumentError, "still used"):
         battle.remove_entry(doc, "presenters", "Wen")
      with doc.edit("Detach"):
         battle.presenter_detach(doc, "Scholar Wen", "Wen")
         battle.remove_entry(doc, "presenters", "Wen")
         battle.presenter_attach(doc, "Scholar Wen", "Coach")
      self.assertEqual(battle.entry(doc, "parties", "Scholar Wen")["presenters"], ["Coach"])
      self.assertIsNone(self.project.validate())
      with self.assertRaises(DocumentError):
         battle.presenter_detach(doc, "Novice Kit", "Ash")

   def test_intro(self) -> None:
      """!Intros as the engine runs them: enter, speak, leave.
      @return None
      """
      doc = self.project.battle
      add_cast(doc)
      lines = battle.intro(doc, "Duo Ash & Bly")
      self.assertEqual(lines[0], "Duo Ash & Bly (side 1, presenters stand at 176, 52)")
      self.assertIn("  Ash enters (slide from side, 24 frames) at 156, 52 [sprite:PRESENTER]", lines)
      self.assertEqual([ln for ln in lines if ": " in ln], ["  Ash: Duo Ash & Bly wants to battle!"])
      self.assertTrue(lines[-1].startswith("  Bly leaves before the first send-out (slide to side"))
      self.assertIn("  Wen stays", battle.intro(doc, "Scholar Wen", "Double"))
      self.assertEqual(battle.stand(doc, "Double"), (196, 56))
      # Without a presenter that speaks, the party_challenge message (with the game's terms).
      with doc.edit("Challenge"):
         battle.presenter_detach(doc, "Novice Kit", "Coach")
         doc.data["messages"]["party_challenge"] = "{@party} {party} is here!"
      self.assertEqual(battle.intro(doc, "Novice Kit")[1:], ["  Rival Novice Kit is here!"])
      with self.assertRaises(DocumentError):
         battle.stand(doc, "Single", 2)


class PresenterTrackTests(BattleTestCase):
   """!presenter_track(): a presenter's motion as the engine's presenter_view plays it."""

   ## The sample presenter sprite's OBJ size.
   SIZE = (32, 64)

   def track(self, name: str, cue: str = "enter", side: int = 1, fmt: str | None = None) -> list[tuple]:
      """!The track of a sample presenter with the sample sprite size.
      @param name  presenter
      @param cue   cue
      @param side  side
      @param fmt   format or None
      @return the track
      """
      compiled, error = self.project.compile()
      self.assertIsNone(error)
      return battle.presenter_track(compiled, name, fmt, side, cue, self.SIZE)

   def test_slide(self) -> None:
      """!A slide from the side's edge to the stand, linear with C++ rounding; the exit ends hidden.
      @return None
      """
      t = self.track("Coach")
      # Single, side 1 stands at (176, 52): the 32x64 sprite's corner is at (160, 20); the right half slides
      # in from the right edge.
      self.assertEqual(len(t), 25)
      self.assertEqual(t[0], (0, 240, 20, 16))
      self.assertEqual(t[1], (1, 237, 20, 16))   # 240 - 80 / 24 rounds toward zero (Python's // gives 236)
      self.assertEqual(t[-1], (24, 160, 20, 16))
      self.assertEqual([f for f, *_ in t], list(range(25)))
      out = self.track("Coach", "exit")
      self.assertEqual((len(out), out[0], out[-1]), (17, (0, 160, 20, 16), (16, 160, 20, 0)))
      left = self.track("Coach", side=0)   # side 0 stands at (64, 92): in from the left edge
      self.assertEqual((left[0], left[-1]), ((0, -32, 60, 16), (24, 48, 60, 16)))
      add_cast(self.project.battle)
      self.assertEqual(self.track("Ash", fmt="Double")[-1][1:3], (196 - 20 - 16, 56 - 32))

   def test_fade_stay(self) -> None:
      """!A fade blends in; "stay" and a missing sprite take no time.
      @return None
      """
      add_cast(self.project.battle)
      fade = self.track("Wen")
      self.assertEqual(len(fade), 33)
      self.assertEqual([a for *_, a in fade][:3], [0, 0, 1])
      self.assertEqual(fade[16], (16, 160, 12, 8))
      self.assertEqual(fade[-1], (32, 160, 12, 16))
      self.assertEqual(self.track("Wen", "exit"), [(0, 160, 12, 16)])   # stays
      doc = self.project.battle
      with doc.edit("No sprite"):
         battle.set_field(doc, "presenters", "Coach", "sprite", None)
      self.assertEqual(self.track("Coach"), [(0, 176, 52, 0)])   # text only: never drawn

   def test_errors_and_sizes(self) -> None:
      """!Unknown names, sides and cues are refused; sprite sizes come from the game's asset manifest.
      @return None
      """
      compiled, _ = self.project.compile()
      for args in (("Nobody",), ("Coach", "Quintuple"), ("Coach", None, 2), ("Coach", None, 1, "dance")):
         with self.assertRaises(DocumentError):
            battle.presenter_track(compiled, *args)
      self.assertEqual(battle.sprite_sizes(self.dir / "battle.json"), {})   # the copy is in no game
      game = make_game(self.dir / "game")
      self.assertEqual(battle.sprite_sizes(game)["sprite:PRESENTER"], self.SIZE)


@needs_gen3
class GenThreeTests(GenThreeTestCase):
   """!The Gen-3 sample of the reference repo (skipped without it): its stats and presenters, including the one
   whose entrance is a sequence file."""

   ## The sample presenter sprite's OBJ size.
   SIZE = (32, 64)

   def test_sample(self) -> None:
      """!The sample compiles; its stats; Bo's entrance is its sequence and hides the sprite.
      @return None
      """
      self.assertIsNone(self.project.validate())
      self.assertEqual(self.project.stats("Cindercub", 5), [20, 10, 9, 11, 10, 11])
      self.assertIn("sequences", [f.parent.name for f in self.project.files()])
      doc = self.project.battle
      self.assertIn("sequence sequences/presenter_bo_enter.json", battle.intro(doc, "Ranger Bo")[1])
      compiled, error = self.project.compile()
      self.assertIsNone(error)
      bo = battle.presenter_track(compiled, "Bo", None, 1, "enter", self.SIZE)
      self.assertEqual(bo, [(0, 160, 20, 0), (1, 160, 20, 16)])
      self.assertEqual(battle.presenter_track(compiled, "Bo", None, 1, "return", self.SIZE), bo)
      out = battle.presenter_track(compiled, "Bo", None, 1, "exit", self.SIZE)
      self.assertEqual((out[0][3], out[-1][3]), (16, 0))
      self.assertEqual(battle.terms(doc)["party"], {"one": "Trainer", "many": "Trainers"})


class ContainerTests(BattleTestCase):
   """!The structure manifest and effect sources a battle manifest names (D-23 §2, §3.1): one Document each,
   with its own undo history, loaded and saved with the project (most of these tests do not compile the data:
   core.logic's tests do)."""

   def name_files(self, structure: str | None, effects: list[str]) -> None:
      """!Makes the copy's battle.json name a structure manifest and effect sources.
      @param structure  structure path, or None for none
      @param effects    effect source paths
      @return None
      """
      path = self.dir / "battle.json"
      data = json.loads(path.read_text(encoding="utf-8"))
      data.pop(battle.STRUCTURE_KEY, None)
      if structure is not None:
         data[battle.STRUCTURE_KEY] = structure
      data[battle.EFFECTS_KEY] = effects
      path.write_text(json.dumps(data), encoding="utf-8")

   def test_single_file_split(self) -> None:
      """!Single-file battle data (the form before E5s) does not open (NeedsSplit); split() migrates it with the
      engine's tool, after which it opens and compiles as before. Battle data naming no structure manifest
      without inline structure is refused too.
      @return None
      """
      path = self.dir / "battle.json"
      merged = engine.tool("battle_compiler").view_of(path)
      merged.pop(battle.STRUCTURE_KEY)
      (self.dir / battle.STRUCTURE_FILE).unlink()
      path.write_text(json.dumps(merged), encoding="utf-8")
      with self.assertRaises(battle.NeedsSplit) as refused:
         BattleProject.open(path)
      self.assertIn("stats", refused.exception.keys)
      self.assertIn("split", str(refused.exception))
      self.assertEqual(battle.split_target(path), (self.dir / battle.STRUCTURE_FILE).resolve())
      st_path, keys = battle.split(path, check=True)
      self.assertFalse(st_path.exists())   # --check writes nothing
      # the same keys (split moves them in the file's order; the refusal names them in the engine's order)
      self.assertEqual(sorted(keys), sorted(refused.exception.keys))
      st_path, keys = battle.split(path)
      self.assertTrue(st_path.exists())
      p = BattleProject.open(path)
      self.assertEqual(p.structure.path, st_path)
      self.assertEqual(list(p.structure.data)[1:], keys)
      self.assertIsNone(p.validate())
      with self.assertRaises(DocumentError):   # already split
         battle.split(path)
      data = json.loads(path.read_text(encoding="utf-8"))
      data.pop(battle.STRUCTURE_KEY)
      path.write_text(json.dumps(data), encoding="utf-8")
      with self.assertRaises(DocumentError) as no_name:
         BattleProject.open(path)
      self.assertNotIsInstance(no_name.exception, battle.NeedsSplit)
      # The sandbox's own data lists its five sources (F1: field.ceffect, the Ward charm and its rule).
      self.assertEqual(list(self.project.effects), ["effects/moves.ceffect", "effects/passives.ceffect",
                                                    "effects/items.ceffect", "effects/conditions.ceffect",
                                                    "effects/field.ceffect"])
      self.assertEqual(self.project.documents()[:3], [self.project.battle, self.project.ruleset,
                                                      self.project.structure])

   def test_grouped_edits(self) -> None:
      """!The two manifests are partners: an edit of either may change both, as one undo step (undone and redone
      from either one); only the file that changed is marked unsaved, and saving writes both.
      @return None
      """
      p = self.project
      self.assertIs(battle.part_of(p.battle, "stats"), p.structure)
      self.assertIs(battle.part_of(p.structure, "moves"), p.battle)
      self.assertIs(battle.data_of(p.battle, "chart"), p.structure.data)
      with p.battle.edit("Category"):
         battle.rename_entry(p.battle, "categories", "physical", "body")
      self.assertTrue(p.battle.dirty and p.structure.dirty)
      self.assertIn("body", battle.merged(p.battle)["rules"]["self_hit"]["category"])
      self.assertEqual(p.structure.undo_label(), "Category")
      self.assertTrue(p.structure.undo())   # undoes the battle manifest's part too
      self.assertEqual(p.names("categories")[0], "physical")
      self.assertNotIn("body", json.dumps(p.battle.data))
      self.assertTrue(p.battle.redo())
      self.assertEqual(p.names("categories")[0], "body")
      p.save_all()
      self.assertFalse(p.dirty)
      self.assertIsNone(BattleProject.open(self.dir / "battle.json").validate())
      # An edit of one manifest marks only that file.
      with p.structure.edit("Term"):
         battle.set_term(p.structure, "move", "Skill")
      self.assertTrue(p.structure.dirty)
      self.assertFalse(p.battle.dirty)
      self.assertEqual(p.battle.undo_label(), "Category")   # no step in the file that did not change
      # A nested edit of the same Document is part of the outer step.
      with p.battle.edit("Outer"):
         battle.add_entry(p.battle, "types", "One")
         with p.battle.edit("Inner"):
            battle.add_entry(p.battle, "types", "Two")
      self.assertEqual(p.battle.undo_label(), "Outer")
      self.assertTrue(p.battle.undo())
      self.assertNotIn("One", p.names("types"))
      self.assertEqual(p.battle.undo_label(), "Category")

   def test_existing_files(self) -> None:
      """!Named files are read; each has its own undo; saving writes only the changed ones.
      @return None
      """
      (self.dir / "structure.json").write_text(json.dumps({"schema": battle.STRUCTURE_SCHEMA, "stats": []}),
                                               encoding="utf-8")
      (self.dir / "effects").mkdir(exist_ok=True)   # the copy has the sandbox's sources
      (self.dir / "effects" / "moves.ceffect").write_text("move \"Jolt\" {\n}\n", encoding="utf-8")
      (self.dir / "effects" / "items.ceffect").write_text("", encoding="utf-8")
      self.name_files("structure.json", ["effects/moves.ceffect", "effects/items.ceffect"])
      p = BattleProject.open(self.dir / "battle.json")
      self.assertEqual(p.structure.data["stats"], [])
      self.assertEqual(list(p.effects), ["effects/moves.ceffect", "effects/items.ceffect"])
      moves = p.effect_source("effects/moves.ceffect")
      self.assertEqual(moves.text, "move \"Jolt\" {\n}\n")
      self.assertEqual(len(p.documents()), 5)
      self.assertFalse(p.dirty)
      with self.assertRaises(DocumentError):
         p.effect_source("effects/none.ceffect")

      # Edits: one undo history per file.
      with p.structure.edit("Stats"):
         p.structure.data["stats"] = [{"name": "hp"}]
      with moves.edit("Text"):
         moves.data["text"] = "move \"Jolt\" {\n   on hit { }\n}\n"
      self.assertTrue(p.dirty)
      self.assertEqual(moves.undo_label(), "Text")
      self.assertEqual(p.structure.undo_label(), "Stats")
      self.assertIsNone(p.battle.undo_label())
      self.assertTrue(moves.undo())
      self.assertEqual(moves.text, "move \"Jolt\" {\n}\n")
      self.assertEqual(p.structure.data["stats"], [{"name": "hp"}])   # untouched by the other file's undo
      self.assertTrue(moves.redo())

      # Unsaved structure edits reach the compiler (its sources), and a revision change drops the cache.
      self.assertIs(p.sources()[p.structure.path], p.structure.data)
      self.assertEqual(p.sources()[moves.path], moves.text)   # an effect source's unsaved text
      before = p._revisions()
      with p.structure.edit("Again"):
         p.structure.data["stats"] = []
      self.assertNotEqual(p._revisions(), before)

      items = self.dir / "effects" / "items.ceffect"
      stamp = items.stat().st_mtime_ns
      p.save_all()
      self.assertFalse(p.dirty)
      self.assertEqual(json.loads((self.dir / "structure.json").read_text(encoding="utf-8"))["stats"], [])
      self.assertEqual((self.dir / "effects" / "moves.ceffect").read_text(encoding="utf-8"),
                       "move \"Jolt\" {\n   on hit { }\n}\n")
      self.assertEqual(items.stat().st_mtime_ns, stamp)   # unchanged: not written
      again = BattleProject.open(self.dir / "battle.json")
      self.assertEqual(again.effect_source("effects/moves.ceffect").text, moves.text)

   def test_absent_files(self) -> None:
      """!Named files that do not exist yet start empty and dirty; the next save writes them.
      @return None
      """
      self.name_files("parts/structure.json", ["effects/new.ceffect"])
      p = BattleProject.open(self.dir / "battle.json")
      self.assertEqual(p.structure.data, {"schema": battle.STRUCTURE_SCHEMA})
      self.assertEqual(p.effect_source("effects/new.ceffect").text, "")
      self.assertTrue(p.dirty)
      self.assertFalse(p.battle.dirty)
      p.save_all()
      self.assertEqual(json.loads((self.dir / "parts" / "structure.json").read_text(encoding="utf-8")),
                       {"schema": battle.STRUCTURE_SCHEMA})
      self.assertEqual((self.dir / "effects" / "new.ceffect").read_text(encoding="utf-8"), "")
      self.assertFalse(BattleProject.open(self.dir / "battle.json").dirty)

   def test_refused(self) -> None:
      """!Bad names are refused when the data opens: absolute paths, other endings, duplicates, a non-list,
      a wrong schema, text that is not UTF-8.
      @return None
      """
      bad = [(None, "effects/a.ceffect"), (None, ["effects/a.txt"]), (None, ["a.ceffect", "a.ceffect"]),
             (str(self.dir / "structure.json"), []), (None, [str(self.dir / "a.ceffect")]), (None, [3])]
      for structure, effects in bad:
         self.name_files(structure, effects)
         with self.assertRaises(DocumentError, msg=(structure, effects)):
            BattleProject.open(self.dir / "battle.json")
      (self.dir / "structure.json").write_text(json.dumps({"schema": battle.BATTLE_SCHEMA}), encoding="utf-8")
      self.name_files("structure.json", [])
      with self.assertRaises(DocumentError):
         BattleProject.open(self.dir / "battle.json")
      (self.dir / "structure.json").write_text(json.dumps({"schema": battle.STRUCTURE_SCHEMA}), encoding="utf-8")
      (self.dir / "latin.ceffect").write_bytes(b"\xe9t\xe9")
      self.name_files("structure.json", ["latin.ceffect"])
      with self.assertRaises(DocumentError):
         BattleProject.open(self.dir / "battle.json")

   def test_new_data_formulas(self) -> None:
      """!New battle data (the Blank template) writes the engine's manifest shape: stats and chart tiers (E6a), no
      stages (the Blank has none), stat formulas apart.
      @return None
      """
      p = BattleProject.create(self.dir / "fresh" / "battle.json", "fresh")
      for gone in ("stat_names", "stage_names"):
         self.assertNotIn(gone, p.battle.data)
         self.assertNotIn(gone, p.structure.data)
      st = p.structure.data
      self.assertNotIn("stat_stages", st["rules"])
      self.assertNotIn("stages", st)
      self.assertEqual([t["name"] for t in st["chart"]["tiers"]], ["normal"])
      self.assertEqual([e["name"] for e in st["stats"]], battle.stat_keys())
      self.assertEqual(battle.stat_formulas(p.ruleset), ["stat_pool", "stat_other"])
      self.assertNotIn("stat_pool", p.ruleset.data["formulas"])
      self.assertIn("stat_other", p.formula_slots())
      self.assertEqual([n for n, _r in p.formula_inputs("stat_other")], list(engine.tool("ruleset_compiler")
                                                                              .STAT_INPUTS))
      self.assertEqual(p.formula("stat_other", base=40, gene=0, training=0, awaken=0, level=9, trait_pct=100),
                       40)
      with p.ruleset.edit("Formula"):
         battle.set_formula(p.ruleset, "stat_other", expr="base + level")
      self.assertEqual(battle.formula_entry(p.ruleset, "stat_other")["expr"], "base + level")
      self.assertNotIn("stat_other", p.ruleset.data["formulas"])
      self.assertIsNone(p.validate())


class BattleCliTests(BattleTestCase):
   """!The battle commands."""

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command.
      @param argv  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()

   def test_commands(self) -> None:
      """!validate, info, stats, formula, set, add, rename, learn, party, chart, presenter, terms, intro.
      @return None
      """
      b = self.dir / "battle.json"
      self.assertEqual(self.run_cli("battle", b, "validate")[0], 0)
      status, out = self.run_cli("battle", b, "info")
      self.assertEqual(status, 0)
      self.assertIn("9 species, 3 parties, 1 presenters", out)
      status, out = self.run_cli("battle", b, "stats", "Emberkit", 5)
      self.assertEqual(status, 0)
      self.assertIn(f"hp {formula_stats(self.project, 'Emberkit', 5)[0]} ", out)
      status, out = self.run_cli("battle", b, "formula", "damage_base", "level=10", "power=40", "attack=20",
                                 "defense=15")
      self.assertEqual(out.strip(), str(self.project.formula("damage_base", level=10, power=40, attack=20,
                                                             defense=15)))
      self.assertEqual(self.run_cli("battle", b, "set", "moves", "Strike", "power", "45")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "add", "moves", "Poke", "--from", "Strike")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "rename", "moves", "Poke", "Prod")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "learn", "Voltmink", 3, "Prod")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "party", "Novice Kit", "add", "Voltmink", 4)[0], 0)
      strong = tier_factor(self.project, "strong")   # a multiplier names its tier
      self.assertEqual(self.run_cli("battle", b, "chart", "Fire", "Light", str(strong))[0], 0)
      status, out = self.run_cli("battle", b, "list", "moves")
      self.assertIn("Prod", out)
      p = BattleProject.open(b)
      self.assertEqual(battle.entry(p.battle, "moves", "Strike")["power"], 45)
      self.assertEqual(battle.chart_value(p.battle, "Fire", "Light"), "strong")
      self.assertEqual(self.run_cli("battle", b, "chart", "Fire", "Light", "weak")[0], 0)
      self.assertEqual(battle.chart_value(BattleProject.open(b).battle, "Fire", "Light"), "weak")
      p = BattleProject.open(b)
      self.assertIsNone(p.validate())
      too_strong = str(engine.tool("battle_compiler").U16_MAX + 1)   # a move's power is 16 bits since C1
      self.assertEqual(self.run_cli("battle", b, "set", "moves", "Strike", "power", too_strong)[0], 1)   # refused
      self.assertEqual(BattleProject.open(b).battle.data == p.battle.data, True)                   # not saved
      status, out = self.run_cli("battle", b, "stats", "Emberkit", 50, "--trait", "Fierce")
      self.assertEqual(status, 0)
      self.assertTrue(out.startswith("hp "))
      self.assertEqual(self.run_cli("battle", b, "party", "Novice Kit", "add", "Voltmink", 4, "--trait", "Swift",
                                    "--passive", 0)[0], 0)
      self.assertEqual(battle.entry(BattleProject.open(b).battle, "parties", "Novice Kit")["members"][-1],
                       {"species": "Voltmink", "level": 4, "passive": 0, "trait": "Swift"})
      self.assertEqual(self.run_cli("battle", b, "party", "Novice Kit", "remove", 3)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "add", "presenters", "Mentor")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "presenter", "Scholar Wen", "attach", "Mentor")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "presenter", "Scholar Wen", "detach", "Coach")[0], 0)
      self.assertEqual(battle.entry(BattleProject.open(b).battle, "parties", "Scholar Wen")["presenters"],
                       ["Mentor"])
      self.assertEqual(self.run_cli("battle", b, "presenter", "Scholar Wen", "detach", "Coach")[0], 1)
      status, out = self.run_cli("battle", b, "terms")
      self.assertIn("party: Rival / Rivals  (game word)", out)
      self.assertIn("move: Move / Moves\n", out)
      self.assertEqual(self.run_cli("battle", b, "terms", "move", "Skill", "Skillz")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "terms", "move")[1], "move: Skill / Skillz  (game word)\n")
      self.assertEqual(self.run_cli("battle", b, "terms", "move", "-")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "terms", "move")[1], "move: Move / Moves\n")
      self.assertEqual(self.run_cli("battle", b, "terms", "move", "x" * 30)[0], 1)   # refused by the compiler
      self.assertEqual(self.run_cli("battle", b, "terms", "gizmo")[0], 1)
      status, out = self.run_cli("battle", b, "intro", "Novice Kit", "--format", "Double")
      self.assertEqual(status, 0)
      self.assertIn("Coach: Novice Kit wants to battle!", out)
      self.assertIn("at 196, 56", out)
      status, out = self.run_cli("battle", b, "presenter-track", "Coach", "--cue", "exit", "--size", 32, 64)
      self.assertEqual(status, 0)
      self.assertEqual(out.splitlines()[0], "0 160 20 16")
      self.assertEqual(out.splitlines()[-1], "16 160 20 0")
      self.assertEqual(self.run_cli("battle", b, "presenter-track", "Nobody")[0], 1)
      # `battle FILE new` starts from the Blank template (no PP built in)
      status, _ = self.run_cli("battle", self.dir / "new" / "battle.json", "new")
      self.assertEqual(status, 0)
      self.assertEqual(self.run_cli("battle", self.dir / "new" / "battle.json", "validate")[0], 0)
      fresh = BattleProject.open(self.dir / "new" / "battle.json")
      self.assertEqual(fresh.structure.data["editor"]["template"]["id"], battle.BLANK_TEMPLATE)
      self.assertEqual([r["name"] for r in fresh.structure.data["resources"]], ["hp"])


if __name__ == "__main__":
   unittest.main()
