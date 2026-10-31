#!/usr/bin/env python3
"""!Smoke tests of the pages S3 keeps working with the manifest's stats and
capsule.ruleset/2: the Species page's base row follows the battle's stats
(one spin per stat, labelled by its abbreviation or label), and the
Formulas page lists and evaluates named formulas. Skipped when PySide6 is
missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.structure import stats  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402


class SpeciesStatsTests(QtBattleTestCase):
   """!The Species page and the battle's stats."""

   def test_base_row_follows_stats(self) -> None:
      """!Nine stats give nine spins; adding a stat gives ten, and a base edit writes ten values.
      @return None
      """
      w, panel = self.window("species")
      self.select(panel, "Emberkit")
      self.assertEqual(len(panel.base), 9)
      self.assertEqual(panel._base_labels, ["HP", "MP", "EP", "Attack", "Magic", "Defence", "Protection",
                                            "Intelligence", "Agility"])
      doc = w.project.battle
      self.assertTrue(w.run_edit("Add stat", lambda: stats.add_stat(doc, "luck", "Luck", base=12), doc))
      self.settle()
      self.assertEqual(len(panel.base), 10)
      self.assertEqual(panel._base_labels[-1], "Luck")
      self.assertEqual(panel.base[-1].value(), 12)
      panel.base[-1].setValue(30)
      panel.base[-1].editingFinished.emit()   # the spin reports finished edits
      self.settle()
      self.assertEqual(battle.entry(doc, "species", "Emberkit")["base"][-1], 30)
      self.assertEqual(len(panel.preview.text().split("  ")), 10)
      self.assertIsNone(w.project.validate())
      w.project.save_all()
      self.assertEqual(len(BattleProject.open(self.battle_json).battle.data["species"][0]["base"]), 10)
      self.close(w)


class FormulasPageTests(QtBattleTestCase):
   """!The Formulas page and named formulas."""

   def test_named_formula(self) -> None:
      """!A named formula shows with its arguments as the evaluator's inputs and evaluates.
      @return None
      """
      from capsule_studio.ui.editors.logic.formulas import EXPR_COLUMN, SLOT_COLUMN
      w, panel = self.window("rules")
      doc = w.project.ruleset
      self.assertTrue(w.run_edit("Named", lambda: battle.set_formula(doc, "halve", "attack / 2", 1, 999,
                                                                     args=["attack"]), doc))
      self.settle()
      slots = [panel.table.item(r, SLOT_COLUMN).text() for r in range(panel.table.rowCount())]
      self.assertIn("halve", slots)
      self.assertEqual(panel.table.item(slots.index("halve"), EXPR_COLUMN).text(), "attack / 2")
      panel.slot.setCurrentText("halve")
      self.settle()
      self.assertEqual(list(panel.input_spins), ["attack"])
      panel.input_spins["attack"].setValue(81)
      panel.evaluate()
      self.assertEqual(panel.result.text(), "= 40")
      self.close(w)
