#!/usr/bin/env python3
"""!Tests for species growth in the studio (D-26 section 4, engine G4): core.species_growth (each species'
transformation rules, forms and training yields, the previews by the engine's evaluator), core.structure.
transformation (the structure's transformation and training sections), what follows a rename (species, items,
stats, forms, types), the logic catalog's form names and Growth palette, and the `battle FILE transform|form|yield|
transformation|training ...` commands. No Qt.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase): Sproutle's two rules (an item and a level),
Glimmet's Radiant form by the time of day, its training values (stat cap 32, total cap 96) are read from the sample.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, engine, logic, species_growth  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import stats, transformation  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## The Starter species with an item rule before a level rule.
BRANCHING = "Sproutle"
## The Starter species with a form chosen by the time of day.
SHIFTING = "Glimmet"
## The Starter's item Sproutle's item rule names.
CHARM = "Bloom Charm"
## Level of the Starter's level rules.
RULE_LEVEL = 20


def run_cli(*argv: object) -> tuple[int, str]:
   """!Runs a command.
   @param argv  arguments
   @return (status, output)
   """
   out = io.StringIO()
   with redirect_stdout(out):
      status = cli([str(a) for a in argv])
   return status, out.getvalue()


class EngineListTests(BattleTestCase):
   """!The choice lists are the engine's."""

   def test_lists(self) -> None:
      """!Triggers, the cancellable ones, the gain's arguments, the form names, the limits.
      @return None
      """
      bc = engine.tool("battle_compiler")
      self.assertEqual(species_growth.triggers(), list(bc.TRIGGERS))
      self.assertEqual(transformation.cancellable(), [t for t in bc.TRIGGERS if t not in bc.UNCANCELLABLE])
      self.assertEqual(transformation.gain_args(), list(bc.TRAIN_GAIN_ARGS))
      self.assertEqual((species_growth.max_forms(), species_growth.max_transforms()), (bc.MAX_FORMS,
                                                                                      bc.MAX_TRANSFORMS))
      doc = self.project.battle
      self.assertEqual(species_growth.form_names(doc)[0], bc.BASE_FORM)
      self.assertIn("Radiant", species_growth.form_names(doc))
      # the logic catalog knows the form names (effect `form WHO NAME`) and the palette has the growth primitives
      self.assertEqual(logic.name_lists(self.project)["forms"], species_growth.form_names(doc))
      templates = [t for _g, label, t in logic.statement_templates(self.project) if label in ("form", "train")]
      self.assertEqual(len(templates), 2)
      self.assertTrue(all(t is not None and "{" not in t for t in templates))


class SpeciesGrowthTests(BattleTestCase):
   """!A species' rules, forms and yields with the previews."""

   def test_rows_and_preview(self) -> None:
      """!The rules in order with their engine triggers; which rule fires on each trigger; forms by the context.
      @return None
      """
      doc = self.project.battle
      rules = species_growth.transforms(doc, BRANCHING)
      self.assertEqual([r["into"] for r in rules], ["Sprigshield", "Sprouthorn"])
      self.assertEqual(rules[0]["triggers"], ["item_use"])
      r = species_growth.preview(doc, BRANCHING, {"level": RULE_LEVEL}, "level_up")
      self.assertEqual((r["found"]["into"], r["text"]), ("Sprouthorn", "becomes Sprouthorn"))
      self.assertEqual([x["holds"] for x in r["rules"]], [False, True])
      self.assertIsNone(species_growth.preview(doc, BRANCHING, {"level": RULE_LEVEL - 1}, "level_up")["found"])
      self.assertEqual(species_growth.preview(doc, BRANCHING, {}, "item_use", CHARM)["found"]["into"], "Sprigshield")
      night = species_growth.preview(doc, SHIFTING, {}, "after_battle", context={"time_of_day": "night"})
      self.assertEqual((night["found"]["kind"], night["found"]["name"]), ("form", "Radiant"))
      self.assertIsNone(species_growth.preview(doc, SHIFTING, {}, "after_battle",
                                               context={"time_of_day": "day"})["found"])
      with self.assertRaisesRegex(DocumentError, "no context value"):
         species_growth.preview(doc, SHIFTING, {}, "after_battle", context={"weather": 1})
      with self.assertRaisesRegex(DocumentError, "trigger"):
         species_growth.preview(doc, SHIFTING, {}, "sunrise")

   def test_rule_edits(self) -> None:
      """!Add (the engine works out the triggers), set, move, remove; refused data keeps the manifest; one undo each.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Add transformation"):
         i = species_growth.add_transform(doc, "Breezle", "Clodbun", "level >= 30")
      row = species_growth.transforms(doc, "Breezle")[i]
      self.assertIsNone(row["on"])
      self.assertIn("level_up", row["triggers"])
      with doc.edit("Set"):
         species_growth.set_transform(doc, "Breezle", i, "on", "level_up")
      self.assertEqual(species_growth.transforms(doc, "Breezle")[i]["triggers"], ["level_up"])
      with doc.edit("Move"):
         self.assertTrue(species_growth.move_transform(doc, "Breezle", i, -1))
      self.assertEqual(species_growth.transforms(doc, "Breezle")[0]["into"], "Clodbun")
      with self.assertRaisesRegex(DocumentError, "never hold"):
         with doc.edit("Never"):
            species_growth.set_transform(doc, "Breezle", 0, "when", "item == bloom_charm")   # level_up has none
      with self.assertRaisesRegex(DocumentError, "a species of the battle"):
         with doc.edit("Into"):
            species_growth.set_transform(doc, "Breezle", 0, "into", "Nobody")
      with doc.edit("Remove"):
         species_growth.remove_transform(doc, "Breezle", 0)
      doc.undo()
      self.assertEqual(species_growth.transforms(doc, "Breezle")[0]["into"], "Clodbun")

   def test_forms_and_yields(self) -> None:
      """!Forms: add (effect logic only), a base rule needs `when`, rename (logic follows), set an override; yields.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Add form"):
         species_growth.add_form(doc, SHIFTING, "Dim", overrides={"base": [1] * len(battle.stat_keys(doc))})
      self.assertEqual(species_growth.forms(doc, SHIFTING)[-1]["overrides"], ["base"])
      with self.assertRaises(DocumentError):
         with doc.edit("Base without rule"):
            species_growth.add_form(doc, SHIFTING, "base")
      with doc.edit("Base rule"):
         species_growth.add_form(doc, SHIFTING, "base", "time_of_day == day")
      back = species_growth.preview(doc, SHIFTING, {"form": 1}, "after_battle", context={"time_of_day": "day"})
      self.assertEqual((back["found"]["kind"], back["found"]["form"]), ("form", 0))
      users = species_growth.form_users(doc, "Radiant")
      self.assertTrue(users)
      with doc.edit("Rename form"):
         self.assertEqual(species_growth.rename_form(doc, SHIFTING, "Radiant", "Shining"), len(users))
      self.assertIsNone(self.project.error_now())
      self.assertEqual(len(species_growth.form_users(doc, "Shining")), len(users))
      with doc.edit("Clear override"):
         species_growth.set_form(doc, SHIFTING, "Dim", "base", None)
      self.assertEqual(species_growth.forms(doc, SHIFTING)[1]["overrides"], [])
      ylds = species_growth.yields(doc, SHIFTING)
      self.assertEqual([y["stat"] for y in ylds], list(transformation.training(doc)["yields"]))
      with doc.edit("Yield"):
         species_growth.set_yield(doc, SHIFTING, ylds[0]["stat"], 2)
      self.assertEqual(species_growth.yields(doc, SHIFTING)[0]["value"], 2)
      gain = species_growth.training_preview(doc, SHIFTING, 1)
      self.assertEqual(gain["after"], engine.tool("battle_compiler").training_gain(
         self.project.compile()[0], [0] * len(gain["stats"]), SHIFTING, 1))

   def test_renames_follow(self) -> None:
      """!A species rename follows the rules; an item rename their expressions; a stat rename the yields and a stat
      added gives every form's own base a value; a type rename a form's types.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Rename species"):
         battle.rename_entry(doc, "species", "Sprouthorn", "Thornling")
      self.assertEqual(species_growth.transforms(doc, BRANCHING)[1]["into"], "Thornling")
      with doc.edit("Rename item"):
         battle.rename_entry(doc, "items", CHARM, "Bud Charm")
      self.assertEqual(species_growth.transforms(doc, BRANCHING)[0]["when"], "item == bud_charm")
      self.assertIsNone(self.project.error_now())
      with doc.edit("Rename stat"):
         stats.rename_stat(doc, "attack", "power")
      self.assertIn("power", transformation.training(doc)["yields"])
      with doc.edit("Add stat"):
         stats.add_stat(doc, "luck", stage=False, targets=["desktop"])
      radiant = species_growth.form(doc, SHIFTING, "Radiant")
      self.assertEqual(len(radiant["base"]), len(battle.stat_keys(doc)))
      ty = radiant["types"][-1]
      with doc.edit("Rename type"):
         battle.rename_entry(doc, "types", ty, "Astral")
      self.assertEqual(species_growth.form(doc, SHIFTING, "Radiant")["types"][-1], "Astral")
      self.assertIsNone(self.project.validate("desktop"))


class StructureTests(BattleTestCase):
   """!The structure's transformation and training sections."""

   def test_sections(self) -> None:
      """!Cancel (item_use refused), blocked, the form role, context values (a read one cannot go), training on /
      off, caps, yield fields, the rule list.
      @return None
      """
      doc = self.project.structure
      with self.assertRaisesRegex(DocumentError, "item"):
         with doc.edit("Cancel"):
            transformation.set_transformation(doc, "cancel", ["item_use"])
      with doc.edit("Blocked"):
         transformation.set_transformation(doc, "blocked", "level > 90")
      self.assertEqual(transformation.transformation(doc)["blocked"], "level > 90")
      self.assertEqual(species_growth.preview(self.project.battle, BRANCHING, {"level": 95}, "level_up")["text"][:7],
                       "blocked")
      self.assertIn("form", transformation.form_role_choices(doc))
      with self.assertRaisesRegex(DocumentError, "read by"):
         with doc.edit("Remove context"):
            transformation.remove_context(doc, transformation.clock_value())
      with doc.edit("Add context"):
         transformation.add_context(doc, "region", rng=(0, 3), default=1)
      row = next(r for r in transformation.context_rows(doc) if r["name"] == "region")
      self.assertEqual((row["range"], row["default"], row["source"]), ((0, 3), 1, transformation.sources()[0]))
      with doc.edit("Range"):
         transformation.set_context(doc, "region", "range", "0,7")
      with doc.edit("Remove"):
         transformation.remove_context(doc, "region")
      self.assertEqual(transformation.gain_formulas(doc)[-1], transformation.training(doc)["gain"])
      top = transformation.stat_cap_max(doc)
      with self.assertRaises(DocumentError):
         with doc.edit("Cap"):
            transformation.set_training(doc, "stat_cap", top + 1)
      lower = transformation.training(doc)["stat_cap"] - 1   # within the gain formula's declared input range
      with doc.edit("Cap"):
         transformation.set_training(doc, "stat_cap", lower)
      self.assertEqual(transformation.training(doc)["stat_cap"], lower)
      with doc.edit("Yield"):
         transformation.set_yield_field(doc, "hp", None)
      self.assertNotIn("hp", transformation.training(doc)["yields"])
      self.assertTrue(any(r["owner"] == "blocked" for r in transformation.rule_rows(doc)))
      with doc.edit("Off"):
         transformation.disable_training(doc)
      self.assertIsNone(transformation.training(doc))
      with self.assertRaisesRegex(DocumentError, "no training"):
         species_growth.training_preview(self.project.battle, SHIFTING, 1)


class CliTests(BattleTestCase):
   """!The commands."""

   def test_commands(self) -> None:
      """!transform list / add / preview, form add / rename, yield, transformation / training show / set / preview.
      @return None
      """
      b = self.dir / "battle.json"
      status, out = run_cli("battle", b, "transform", "list", BRANCHING)
      self.assertEqual(status, 0)
      self.assertIn("-> Sprouthorn when level >= 20 on level_up", out)
      status, out = run_cli("battle", b, "transform", "preview", BRANCHING, "level_up", f"level={RULE_LEVEL}")
      self.assertIn("becomes Sprouthorn", out)
      status, out = run_cli("battle", b, "transform", "preview", SHIFTING, "after_battle", "--context",
                            "time_of_day=night")
      self.assertIn("takes the form Radiant", out)
      self.assertEqual(run_cli("battle", b, "transform", "add", "Breezle", "Clodbun", "level >= 30", "--on",
                               "level_up")[0], 0)
      saved = json.loads(b.read_text(encoding="utf-8"))
      breezle = next(s for s in saved["species"] if s["name"] == "Breezle")
      self.assertEqual(breezle["transforms"][-1], {"into": "Clodbun", "when": "level >= 30", "on": ["level_up"]})
      self.assertEqual(run_cli("battle", b, "form", "add", "Breezle", "Gale")[0], 0)
      self.assertEqual(run_cli("battle", b, "form", "rename", SHIFTING, "Radiant", "Shining")[0], 0)
      status, out = run_cli("battle", b, "yield", SHIFTING)
      self.assertIn("magic 1", out)
      self.assertEqual(run_cli("battle", b, "transformation", "set", "cancel", "level_up,trade")[0], 0)
      self.assertNotEqual(run_cli("battle", b, "transformation", "set", "cancel", "item_use")[0], 0)
      self.assertEqual(run_cli("battle", b, "transformation", "context", "add", "mood", "--values", "calm,wild")[0],
                       0)
      status, out = run_cli("battle", b, "training", "show")
      self.assertIn("context 1 mood (game): values calm, wild", out)
      self.assertIn("cancel: level_up, trade", out)
      status, out = run_cli("battle", b, "training", "preview", SHIFTING, "--level", 1)
      self.assertIn("magic: 0 + 2 = 2", out)
      self.assertEqual(run_cli("battle", b, "training", "set", "total_cap", 40)[0], 0)
      self.assertEqual(json.loads((self.dir / "structure.json").read_text(encoding="utf-8"))["training"]["total_cap"],
                       40)


if __name__ == "__main__":
   unittest.main()
