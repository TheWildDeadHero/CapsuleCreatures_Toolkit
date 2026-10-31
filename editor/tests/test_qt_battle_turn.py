#!/usr/bin/env python3
"""!Smoke tests of the S5c battle pages: Structure > Formats, Turn and
Progression, the Record page's transfer defaults box and the Formulas
page's rows. Each opens a copy of the Starter sample laid
out as a game, edits through the widgets (one undo step per edit), undoes
and saves. Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle  # noqa: E402
from capsule_studio.core.structure import progression, turn  # noqa: E402
from test_qt_battle import QtBattleTestCase, QtWidgets  # noqa: E402


class FormatsPanelTests(QtBattleTestCase):
   """!The Formats page."""

   def test_edit_undo_save(self) -> None:
      """!Sides, a place, a stand, range: one undo step each; the preview follows; saves.
      @return None
      """
      w, panel = self.window("formats")
      doc = w.project.battle
      self.select(panel, "Single")
      self.assertEqual(panel.side_count.value(), 2)
      self.assertEqual(panel.places.rowCount(), 2)
      panel.side_spins[1].setValue(2)
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["formats"][0]["sides"], [[0], [1, 2]])
      self.assertEqual(w.undo_action.text(), "Undo Format sides")
      self.assertEqual(panel.places.rowCount(), 3)
      self.assertEqual(len(panel.preview.battlers), 3)
      panel.places.item(2, 2).setText("210")
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["formats"][0]["layout"][2][0], 210)
      panel.stands.item(0, 1).setText("70")
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["formats"][0]["stands"][0][0], 70)
      panel.range_box.setCurrentText("adjacent")
      panel.range_box.activated.emit(panel.range_box.currentIndex())   # refused: sides of 1 and 2
      self.settle()
      self.assertNotEqual(battle.structure_doc(doc).data["formats"][0].get("range"), "adjacent")
      self.assertIsNotNone(w.edit_error)
      w.undo()
      self.settle()
      self.assertNotIn("stands", battle.structure_doc(doc).data["formats"][0])
      self.assertTrue(w.save_all())
      self.assertEqual(self.saved()["formats"][0]["layout"][2][0], 210)
      self.close(w)


class TurnPanelTests(QtBattleTestCase):
   """!The Turn page."""

   def test_edit_undo_save(self) -> None:
      """!A bracket, the tie rule, the effect order, phases; the default marks; saves.
      @return None
      """
      w, panel = self.window("turn")
      doc = w.project.battle
      self.assertTrue(panel.move_priority.isChecked())
      self.assertEqual(panel.order.count(), len(turn.sources()))
      self.assertEqual(panel.phases.count(), 5)   # with the Starter's regen phase (D-25)
      panel.brackets["run"].setValue(7)
      panel.brackets["run"].editingFinished.emit()
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["turn"]["brackets"]["run"], 7)
      self.assertEqual(w.undo_action.text(), "Undo Turn bracket")
      combo = panel.choices["tie"][0]
      combo.setCurrentText("position")
      combo.activated.emit(combo.currentIndex())
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["turn"]["tie"], "position")
      panel.order.setCurrentRow(len(turn.sources()) - 1)
      self.assertTrue(panel.move_source(-1))
      self.settle()
      self.assertEqual(turn.effect_order(doc)[-2:], ["item", "passive"])
      panel.phases.setCurrentRow(1)
      self.settle()
      self.assertTrue(panel.sources.isVisibleTo(panel))
      self.assertTrue(panel.set_phase_sources(["status", "item"]))
      self.settle()
      self.assertEqual(turn.phase_rows(doc)[1]["runs"], ["status", "item"])
      panel.phases.setCurrentRow(0)
      self.assertFalse(panel.remove_phase())   # the weather phase is needed (refused)
      self.settle()
      self.assertEqual(panel.phases.count(), 5)
      self.assertTrue(panel.add_phase("battlers"))
      self.settle()
      self.assertEqual(panel.phases.count(), 6)
      self.assertTrue(panel.reset(turn.END_KEY))
      self.settle()
      self.assertIn("color: #808080", panel.phases.styleSheet())   # the engine's phases now
      w.undo()
      self.settle()
      self.assertEqual(panel.phases.count(), 6)
      self.assertTrue(w.save_all())
      self.assertEqual(self.saved()["turn"]["tie"], "position")
      self.close(w)


class ProgressionPanelTests(QtBattleTestCase):
   """!The Progression page."""

   def test_edit_preview_undo_save(self) -> None:
      """!A policy word, a new derived entry with its preview, a constant, removal; saves.
      @return None
      """
      w, panel = self.window("progression")
      doc = w.project.battle
      self.assertEqual(panel.table.rowCount(), 4)
      self.assertIn("draws 1-2", panel.table.item(0, 3).text())
      combo = panel.policy["learn.on_full"]
      combo.setCurrentText("request")
      combo.activated.emit(combo.currentIndex())
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["learn"]["on_full"], "request")
      panel.table.selectRow(3)
      self.assertTrue(panel.add_entry("owner_id"))
      self.settle()
      self.assertEqual(panel.selected_index(), 4)
      self.assertTrue(panel.set_way(progression.DERIVED_WAY))
      self.settle()
      self.assertTrue(panel.set_derived("seed_lo % 7 + element", [0, 9]))
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["generation"][4],
                       {"role": "owner_id", "derived": "seed_lo % 7 + element", "range": [0, 9]})
      self.assertEqual(panel.expr.text(), "seed_lo % 7 + element")
      self.assertTrue(panel.set_input("seed_lo", 20))
      panel.element.setValue(1)
      self.assertEqual(panel.run_preview(), 7)
      self.assertEqual(panel.result.text(), "= 7")
      self.assertFalse(panel.set_input("zzz", 1))   # no such input: refused, nothing raised
      self.assertIn("no input 'zzz'", panel.result.text())
      self.assertFalse(panel.set_derived("unknown_input + 1"))   # refused with the compiler's message
      self.settle()
      self.assertIn("unknown", w.edit_error[1])
      w.undo()
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["generation"][4], {"role": "owner_id", "derived": "0"})
      panel.table.selectRow(4)
      self.settle()
      self.assertTrue(panel.remove_entry())
      self.settle()
      self.assertEqual(panel.table.rowCount(), 4)
      self.assertTrue(w.save_all())
      self.assertEqual(self.saved()["learn"]["on_full"], "request")
      self.close(w)


class TransferAndFormulasTests(QtBattleTestCase):
   """!The Record page's transfer defaults box and the Formulas page's rows."""

   def test_transfer_defaults(self) -> None:
      """!Typing a value sets it (one undo step); emptying it drops it.
      @return None
      """
      w, panel = self.window("record")
      box = panel.transfer_box
      doc = w.project.battle
      self.assertEqual(box.table.rowCount(), len(battle.stat_keys(doc)))
      box.table.item(0, 1).setText("3")   # hp, every per-stat role
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["monster_layout"]["transfer_defaults"], {"hp": 3})
      self.assertEqual(w.undo_action.text(), "Undo Transfer default")
      box.table.item(0, 1).setText("")
      self.settle()
      self.assertNotIn("transfer_defaults", battle.structure_doc(doc).data["monster_layout"])
      self.close(w)

   def test_named_formula_rows(self) -> None:
      """!Every row is the ruleset's own formula (since E8 the engine fills no formula slot); typing an expression
      into a named formula a resource names (ep_regen) edits it.
      @return None
      """
      from capsule_studio.ui.editors.logic.formulas import EXPR_COLUMN, SLOT_COLUMN
      w, panel = self.window("rules")
      p = w.project
      slots = p.formula_slots()
      self.assertEqual([panel.table.item(r, SLOT_COLUMN).text() for r in range(panel.table.rowCount())], slots)
      row = slots.index("ep_regen")
      panel.table.item(row, EXPR_COLUMN).setText("max(1, pool_max / 20)")
      self.settle()
      self.assertEqual(p.ruleset.data["formulas"]["ep_regen"]["expr"], "max(1, pool_max / 20)")
      self.assertIsNone(p.validate())
      self.close(w)


if __name__ == "__main__":
   import unittest
   unittest.main()

_ = QtWidgets   # imported for the skip of the base class
