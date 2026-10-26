#!/usr/bin/env python3
"""!Smoke tests of the S12 pages (D-25): Structure > Resources and the
Moves page's bases and cost editor. Each opens a copy of the Starter sample
laid out as a game, edits through the widgets (one undo step per edit; a
rename spanning battle.json and structure.json is one step), undoes and
saves. Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle  # noqa: E402
from capsule_studio.core.structure import resources  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402


class ResourcesPanelTests(QtBattleTestCase):
   """!The Resources page."""

   def test_table_and_edits(self) -> None:
      """!The Starter's three resources with the budget; label and regen edits, an added move resource and a rename
      (one undo step across both files); saved.
      @return None
      """
      from capsule_studio.ui.editors.structure.resources import RESOURCE_COLUMN
      w, panel = self.window("resources")
      p = w.project
      self.assertIs(w.document, p.structure)   # a structure page edits structure.json
      self.assertEqual(panel.table.rowCount(), 3)
      self.assertEqual(panel.table.item(2, RESOURCE_COLUMN["name"]).text(), "ep")
      self.assertEqual(panel.row_widgets[2]["regen"].currentText(), "ep_regen")
      self.assertFalse(panel.row_widgets[0]["max"].isEnabled())   # a battler resource has no max formula
      self.assertIn("3/4 battler, 0/2 move (gba)", panel.budget.text())
      panel.table.item(2, RESOURCE_COLUMN["label"]).setText("Energy")
      self.settle()
      self.assertEqual(resources.resource_entry(p.structure, "ep")["label"], "Energy")
      self.assertEqual(w.undo_action.text(), "Undo Resource label")
      self.assertTrue(panel.set_resource("mp", "regen", "1"))
      self.settle()
      self.assertEqual(resources.resource_entry(p.structure, "mp")["regen"], 1)
      self.assertIn("regen", [e.get("run") for e in p.structure.data["turn"]["end_of_turn"]])
      panel.selected = "hp"
      self.assertTrue(panel.add_resource(resources.MOVE, "charge"))
      self.settle()
      self.assertEqual(panel.table.rowCount(), 4)
      self.assertEqual(battle.entry(p.battle, "moves", "Strike")["charge"], battle.NEW_RESOURCE_BASE)
      self.assertTrue(panel.add_resource(resources.MOVE, "spare"))
      self.settle()
      self.assertFalse(panel.add_resource(resources.MOVE, "third"))   # the GBA holds two move resources
      self.settle()
      self.assertIn("at most 2", w.edit_error[1])
      w.undo()   # the spare one
      self.settle()
      # added after the selected resource (hp): the payment order is hp, charge, mp, ep
      self.assertEqual(resources.resource_names(p.structure), ["hp", "charge", "mp", "ep"])
      panel.table.item(1, RESOURCE_COLUMN["name"]).setText("spark")
      self.settle()
      self.assertEqual(battle.entry(p.battle, "moves", "Strike")["spark"], battle.NEW_RESOURCE_BASE)
      self.assertEqual(w.undo_action.text(), "Undo Rename resource")
      w.undo()
      self.settle()
      self.assertEqual(resources.resource_names(p.structure), ["hp", "charge", "mp", "ep"])
      self.assertIn("charge", battle.entry(p.battle, "moves", "Strike"))
      self.assertNotIn("spark", battle.entry(p.battle, "moves", "Strike"))
      self.assertIsNone(p.validate())
      self.assertTrue(w.save_all())
      self.assertEqual([r["name"] for r in self.saved()["resources"]], ["hp", "charge", "mp", "ep"])
      self.close(w)

   def test_refusals(self) -> None:
      """!A refused edit leaves the data and shows the reason (the faint resource is neither removed nor moved to
      another scope).
      @return None
      """
      w, panel = self.window("resources")
      before = dict(w.project.structure.data)
      panel.selected = "hp"
      self.assertFalse(panel.remove_resource())
      self.settle()
      self.assertIn("faint resource", w.edit_error[1])
      self.assertFalse(panel.set_scope("hp", resources.MOVE))
      self.settle()
      self.assertEqual(dict(w.project.structure.data), before)
      self.close(w)


class MovesCostTests(QtBattleTestCase):
   """!The Moves page's bases and cost editor."""

   def test_bases_and_cost(self) -> None:
      """!One base spin per move resource, one cost row per resource (the default greyed); setting and resetting
      a cost is one undo step each.
      @return None
      """
      from capsule_studio.ui.editors.content.moves import FROM_COLUMN, FROM_FREE, FROM_MOVE
      w, panel = self.window("moves")
      move = "Flare Claw"
      entry = lambda: battle.entry(w.project.battle, "moves", move)   # noqa: E731
      self.select(panel, move)
      self.assertEqual(list(panel.bases), [])   # the Starter has battler resources only
      self.assertEqual(panel.cost_table.rowCount(), 3)
      self.assertEqual(panel.cost_boxes["ep"].currentText(), "5")
      self.assertEqual(panel.cost_table.item(2, FROM_COLUMN).text(), FROM_MOVE)
      self.assertTrue(panel.cost_reset.isEnabled())
      self.assertTrue(panel.set_cost("mp", "2"))
      self.settle()
      self.assertEqual(entry()["cost"], {"mp": 2, "ep": 5})
      self.assertFalse(panel.set_cost("mp", "-3"))   # refused: not a cost
      self.settle()
      self.assertTrue(panel.reset_cost())
      self.settle()
      self.assertNotIn("cost", entry())
      # a battler resource's default is nothing (S17: no "0 / default"): the box is empty with the amount as its
      # placeholder, and the From cell says it pays nothing
      self.assertEqual(panel.cost_table.item(2, FROM_COLUMN).text(), FROM_FREE)
      self.assertEqual(panel.cost_boxes["ep"].currentText(), "")
      self.assertEqual(panel.cost_boxes["ep"].lineEdit().placeholderText(), "0")
      self.assertFalse(panel.set_cost("ep", ""))   # the empty box of a default is no edit
      self.assertFalse(panel.cost_reset.isEnabled())
      w.undo()
      self.settle()
      self.assertEqual(entry()["cost"], {"mp": 2, "ep": 5})
      # a move resource adds a base spin per move
      st = w.project.structure
      self.assertTrue(w.run_edit("Move resource", lambda: resources.add_resource(st, "charge", resources.MOVE), st))
      w.show_panel("moves")
      self.settle()
      self.select(panel, move)
      self.assertEqual(list(panel.bases), ["charge"])
      self.assertEqual(panel.bases["charge"].value(), entry()["charge"])
      panel.bases["charge"].setValue(12)
      panel.bases["charge"].editingFinished.emit()
      self.settle()
      self.assertEqual(entry()["charge"], 12)
      self.assertIsNone(w.project.validate())
      self.close(w)


if __name__ == "__main__":
   import unittest
   unittest.main()
