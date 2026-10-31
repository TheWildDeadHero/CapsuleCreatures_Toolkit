#!/usr/bin/env python3
"""!Smoke tests of the S15 pages: Structure > Passive slots (D-25 decision 6,
engine C1), the Species page's one passive combo per slot, the Parties page's
member slot combo, the Moves page's fallback cost and the C1 widths. Each
opens a copy of the Starter sample laid out as a game and edits through the
widgets (one undo step per edit). Skipped when PySide6 is missing; uses Qt's
offscreen platform. CAPSULE_SHOTS=FOLDER saves a picture of the Passive
slots page there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import ai as ai_model, battle, engine  # noqa: E402
from capsule_studio.core.structure import passive_slots, resources  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## Environment variable naming a folder for the page's picture.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of the picture, pixels.
SHOT_SIZE = (900, 520)


class PassiveSlotsPanelTests(QtBattleTestCase):
   """!The Passive slots page and the pages that follow it."""

   def yes(self) -> Any:
      """!Answers the page's questions Yes (widgets.ask() says No without a screen).
      @return a context manager
      """
      from PySide6 import QtWidgets
      return mock.patch("capsule_studio.ui.editors.structure.passive_slots.ask",
                        return_value=QtWidgets.QMessageBox.StandardButton.Yes)

   def test_table_and_edits(self) -> None:
      """!The sample's slots with the budget; add (unrolled), rename by typing, rolled box, move and remove; each
      one undo step; the Species page shows one combo per slot.
      @return None
      """
      from capsule_studio.ui.editors.structure.passive_slots import NAME_COLUMN, ROLLED_COLUMN
      w, panel = self.window("passive_slots")
      p = w.project
      self.assertIs(w.document, p.structure)
      names = passive_slots.slot_names(p.structure)
      self.assertEqual(panel.table.rowCount(), len(names))
      self.assertEqual(panel.table.item(0, NAME_COLUMN).text(), names[0])
      self.assertIn(f"{len(names)}/", panel.budget.text())
      self.assertIn(passive_slots.SELECTOR_ROLE, panel.budget.text())
      panel.selected = names[-1]
      self.assertTrue(panel.add_slot("veiled", rolled=False))
      self.settle()
      self.assertEqual(passive_slots.slot_names(p.structure), names + ["veiled"])
      self.assertEqual(w.undo_action.text(), "Undo Add passive slot")
      row = len(names)
      self.assertEqual(panel.table.item(row, ROLLED_COLUMN).checkState().name, "Unchecked")
      shots = os.environ.get(SHOTS_ENV)
      if shots:
         Path(shots).mkdir(parents=True, exist_ok=True)
         w.resize(*SHOT_SIZE)
         w.show()
         self.settle()
         panel.grab().save(str(Path(shots) / "passive_slots.png"))
      panel.table.item(row, NAME_COLUMN).setText("secret")
      self.settle()
      self.assertEqual(passive_slots.slot_names(p.structure)[-1], "secret")
      self.assertEqual(w.undo_action.text(), "Undo Rename passive slot")
      panel.table.item(row, ROLLED_COLUMN).setCheckState(panel.table.item(0, ROLLED_COLUMN).checkState())
      self.settle()
      self.assertEqual(p.structure.data["passive_slots"][-1], {"name": "secret"})
      panel.selected = "secret"
      # saved records keep their slot numbers (C4): headless, the question's answer is No
      self.assertFalse(panel.move_slot(-1))
      self.settle()
      self.assertEqual(passive_slots.slot_names(p.structure)[-1], "secret")
      with self.yes():
         self.assertTrue(panel.move_slot(-1))
      self.settle()
      self.assertEqual(passive_slots.slot_names(p.structure)[-2], "secret")
      self.assertFalse(panel.rename_slot("Bad Name", "secret"))
      self.settle()
      self.assertIsNotNone(w.edit_error)
      # the Species page follows the slot count
      species = w.show_panel("species")
      self.settle()
      self.assertEqual(len(species.passives), len(names) + 1)
      w.show_panel("passive_slots")
      self.settle()
      panel.selected = "secret"
      self.assertFalse(panel.remove_slot())
      with self.yes():
         self.assertTrue(panel.remove_slot())
      self.settle()
      self.assertEqual(passive_slots.slot_names(p.structure), names)
      w.undo()
      self.settle()
      self.assertIn("secret", passive_slots.slot_names(p.structure))
      self.assertIsNone(p.validate())
      self.assertTrue(w.save_all())
      self.assertIn("secret", [e["name"] for e in self.saved()["passive_slots"]])
      self.close(w)

   def test_member_slot_combo(self) -> None:
      """!The Parties page's member slot lists the structure's slots and writes the slot's name.
      @return None
      """
      w, panel = self.window("parties")
      p = w.project
      party = p.names("parties")[0]
      self.select(panel, party)
      panel.members.setCurrentRow(0)
      self.settle()
      names = passive_slots.slot_names(p.structure)
      self.assertEqual([panel.m_passive.itemText(i) for i in range(panel.m_passive.count())], names)
      self.assertEqual(panel.m_passive.currentText(), names[0])
      panel._passive_picked(names[1])
      self.settle()
      self.assertEqual(battle.entry(p.battle, "parties", party)["members"][0]["passive"], names[1])
      profiles = [panel.ai.itemText(i) for i in range(1, panel.ai.count())]   # G1: the default, then the profiles
      self.assertEqual(profiles, ai_model.profile_names(p.battle))
      self.close(w)

   def test_moves_fallback_and_widths(self) -> None:
      """!The fallback move's cost cannot be edited; power and base stat spins go as far as the engine's widths.
      @return None
      """
      w, panel = self.window("moves")
      p = w.project
      fallback = resources.fallback_move(p.battle)
      self.assertIsNotNone(fallback)
      self.select(panel, fallback)
      self.assertTrue(panel.cost_boxes)
      self.assertFalse(any(box.isEnabled() for box in panel.cost_boxes.values()))
      top = engine.tool("battle_compiler").U16_MAX
      self.assertEqual(panel.power.maximum(), top)
      species = w.show_panel("species")
      self.settle()
      self.assertEqual(species.base[0].maximum(), top)
      self.close(w)


if __name__ == "__main__":
   import unittest
   unittest.main()
