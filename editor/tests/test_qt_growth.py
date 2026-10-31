#!/usr/bin/env python3
"""!Smoke tests of the G4 pages: Content > Species (its Transformations, Forms and Yields tabs) and Structure >
Growth & training. Each opens a copy of the Starter sample laid out as a game and edits through the widgets (one
undo step per edit); the previews ask the engine's evaluator. Skipped when PySide6 is missing; uses Qt's offscreen
platform. CAPSULE_SHOTS=FOLDER saves a picture of each page there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import species_growth  # noqa: E402
from capsule_studio.core.structure import transformation  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## Environment variable naming a folder for the pages' pictures.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a picture, pixels.
SHOT_SIZE = (1250, 900)
## The Starter species with an item rule and a level rule.
BRANCHING = "Sproutle"
## The Starter species with a form chosen by the time of day.
SHIFTING = "Glimmet"


class GrowthPagesTests(QtBattleTestCase):
   """!The Species page's growth tabs and the Growth & training page."""

   def window(self, panel_id: str) -> tuple[object, object]:
      """!A battle editor on the copy hosting the growth pages (and Logic > Rules, which "Formula..." opens).
      @param panel_id  the page's panel id
      @return (BattleWindow, the panel)
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.editors.content.species import SpeciesPanel
      from capsule_studio.ui.editors.logic.formulas import RulesPanel
      from capsule_studio.ui.editors.structure.transformation import TransformationPanel
      w = BattleWindow([SpeciesPanel, TransformationPanel, RulesPanel], self.battle_json)
      panel = w.show_panel(panel_id)
      self.settle()
      return w, panel

   def shot(self, w: object, panel: object, name: str) -> None:
      """!Saves a picture of a page when CAPSULE_SHOTS names a folder.
      @param w      the window
      @param panel  the page
      @param name   file stem
      @return None
      """
      shots = os.environ.get(SHOTS_ENV)
      if not shots:
         return
      Path(shots).mkdir(parents=True, exist_ok=True)
      w.resize(*SHOT_SIZE)
      w.show()
      self.settle()
      panel.grab().save(str(Path(shots) / f"{name}.png"))

   def select(self, panel: object, name: str) -> None:
      """!Picks a species on the Species page.
      @param panel  the page
      @param name   species name
      @return None
      """
      panel.entry_list.setCurrentRow(panel.names().index(name))
      self.settle()

   def test_transformations_tab(self) -> None:
      """!The rules table, the preview (which rule fires on level_up / item_use), add and remove through the row.
      @return None
      """
      w, panel = self.window("species")
      p = w.project
      self.select(panel, BRANCHING)
      tabs = panel.growth_tabs
      rules = species_growth.transforms(p.battle, BRANCHING)
      self.assertEqual(tabs.rules.rowCount(), len(rules))
      tabs.level.setValue(20)
      tabs.trigger.setCurrentText("level_up")
      self.settle()
      self.assertIn("becomes Sprouthorn", tabs.result.text())
      tabs.trigger.setCurrentText("item_use")
      tabs.item.setCurrentText("Bloom Charm")
      self.settle()
      self.assertIn("becomes Sprigshield", tabs.result.text())
      self.shot(w, panel, "species_transformations")
      tabs.into.setCurrentText("Clodbun")
      tabs.when.setText("level >= 40")
      tabs.on["level_up"].setChecked(True)
      self.assertTrue(tabs.add_rule())
      self.settle()
      self.assertEqual(species_growth.transforms(p.battle, BRANCHING)[-1]["into"], "Clodbun")
      self.assertEqual(w.undo_action.text(), "Undo Add transformation")
      tabs.rules.selectRow(len(rules))
      self.assertTrue(tabs.remove_rule())
      self.settle()
      self.assertEqual(len(species_growth.transforms(p.battle, BRANCHING)), len(rules))

   def test_forms_and_yields_tabs(self) -> None:
      """!The forms table, the time of day preview, a refused form, the yields spins.
      @return None
      """
      w, panel = self.window("species")
      p = w.project
      self.select(panel, SHIFTING)
      tabs = panel.growth_tabs
      self.assertEqual(tabs.forms.rowCount(), len(species_growth.forms(p.battle, SHIFTING)))
      tabs.trigger.setCurrentText("after_battle")
      tabs.context["time_of_day"].setCurrentText("night")
      self.settle()
      self.assertIn("takes the form Radiant", tabs.result.text())
      tabs.forms.selectRow(0)
      self.settle()
      self.assertEqual(tabs.form_name.text(), "Radiant")
      tabs.setCurrentIndex(1)
      self.shot(w, panel, "species_forms")
      tabs.form_name.setText("Dim")
      tabs.form_types.setText("")
      tabs.form_base.setText("")
      tabs.form_when.setText("")
      self.assertTrue(tabs.add_form())
      self.settle()
      self.assertIn("Dim", [f["name"] for f in species_growth.forms(p.battle, SHIFTING)])
      tabs.form_name.setText("Dim")
      self.assertFalse(tabs.add_form())   # a taken name: refused
      tabs.setCurrentIndex(2)
      stat = species_growth.yields(p.battle, SHIFTING)[0]["stat"]
      tabs.yield_spins[stat].setValue(2)
      tabs.yield_spins[stat].editingFinished.emit()
      self.settle()
      self.assertEqual(species_growth.yields(p.battle, SHIFTING)[0]["value"], 2)
      self.assertIn("+", tabs.train_result.text())
      self.shot(w, panel, "species_yields")

   def test_growth_training_page(self) -> None:
      """!Cancel boxes, a context value added by the widgets, the training caps, the rule list, the formula link.
      @return None
      """
      w, panel = self.window("growth_training")
      p = w.project
      self.assertIs(w.document, p.structure)
      self.assertEqual(list(panel.cancel), transformation.cancellable())
      self.assertGreater(panel.rules.rowCount(), 0)
      self.assertTrue(panel.training_on.isChecked())
      self.shot(w, panel, "growth_training")
      panel.cancel["trade"].setChecked(True)
      self.settle()
      self.assertIn("trade", transformation.transformation(p.structure)["cancel"])
      self.assertEqual(w.undo_action.text(), "Undo Set transformation")
      self.assertTrue(panel.add_context("mood", "calm,wild"))
      self.settle()
      self.assertIn("mood", transformation.context_names(p.structure))
      panel.stat_cap.setValue(panel.stat_cap.value() - 1)
      panel.stat_cap.editingFinished.emit()
      self.settle()
      self.assertEqual(transformation.training(p.structure)["stat_cap"], panel.stat_cap.value())
      self.assertTrue(panel.open_formula())
      self.assertEqual(w.active_panel().panel_id, "rules")
