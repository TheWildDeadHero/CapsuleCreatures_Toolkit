#!/usr/bin/env python3
"""!Regression tests of the studio review's window findings (S14): bench scenarios in the window's unsaved marks,
Save all and the close prompt (F2), Save writing every file of a grouped edit (F3), text still being typed
committed before the close prompt (F4), no modal box headless (F7, F16), the pre-E6a migration offer and action
(F10), move cost boxes cut off from their signals when rebuilt (F14) and undo of a rename from either file in
lock step (F1). Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle, bench, document  # noqa: E402
from capsule_studio.core.structure import stages  # noqa: E402
from test_qt_battle import QtBattleTestCase, QtCore, QtWidgets  # noqa: E402

## The Starter's move logic.
MOVES = "effects/moves.ceffect"
## A line typed into the Effects page's text view.
TYPED = "# typed just now"
## A seed the bench scenario gets.
NEW_SEED = 777
## The signal a cost box's line edit commits with.
EDITING_FINISHED = "editingFinished()"


class ReviewWindowTests(QtBattleTestCase):
   """!F1, F2, F3, F4, F7, F10, F14 in the battle window."""

   def test_bench_scenarios_count_unsaved(self) -> None:
      """!An edited bench scenario marks the window unsaved, the close prompt is not skipped (headless: Cancel,
      nothing lost) and Save all writes it.
      @return None
      """
      w, panel = self.window("bench")
      panel.toolchain_check = lambda: []
      self.assertTrue(panel.new_scenario("duel"))
      doc = panel.scenario_doc()
      self.assertIs(doc, w.project.scenario(doc.path))
      self.assertTrue(w.run_edit("Seed", lambda: doc.data.__setitem__("seed", NEW_SEED), doc))
      self.settle()
      self.assertTrue(w.project.dirty)
      self.assertIn(" *", w.windowTitle())
      self.assertFalse(w._confirm_discard())   # headless: kept open, no box
      self.assertTrue(w.save_all())
      self.assertFalse(doc.dirty)
      self.assertEqual(json.loads(doc.path.read_text(encoding="utf-8"))["seed"], NEW_SEED)
      self.close(w)

   def test_save_writes_the_whole_edit(self) -> None:
      """!Save on the Moves page after a rename writes battle.json and structure.json (the fallback move), so the
      files on disk compile.
      @return None
      """
      w, panel = self.window("moves")
      self.assertTrue(panel.edit("Rename move", lambda: battle.rename_entry(w.project.battle, "moves", "Strike",
                                                                             "Bonk")))
      self.assertIs(w.document, w.project.battle)
      self.assertTrue(w.save_current())
      self.assertFalse(w.project.structure.dirty)
      fresh = battle.BattleProject.open(self.battle_json)
      self.assertEqual(fresh.structure.data["rules"]["fallback_move"], "Bonk")
      self.assertIsNone(fresh.validate())
      self.close(w)

   def test_typing_committed_before_prompt(self) -> None:
      """!Text typed in the Effects page's text view (its idle timer still pending) reaches the source before the
      close prompt checks for unsaved changes.
      @return None
      """
      w, panel = self.window("effects")
      panel.select_owner("move:Fireball")
      panel.set_view("text")
      self.settle()
      panel.code.setPlainText(panel.code.toPlainText() + "\n" + TYPED + "\n")
      self.assertFalse(w._confirm_discard())   # unsaved now: headless Cancel
      self.assertIn(TYPED, w.project.effect_source(MOVES).text)
      self.close(w)

   def test_no_modal_box_headless(self) -> None:
      """!Validate with an error, a failed save and a failed new scenario report to the status bar and return.
      @return None
      """
      w, panel = self.window("bench")
      with w.project.structure.edit("Break"):
         w.project.structure.data["rules"]["fallback_move"] = "Nope"
      with mock.patch.object(QtWidgets.QMessageBox, "warning") as box:
         w.validate()
         self.assertIn("Validate", w.statusBar().currentMessage())
         with mock.patch.object(document.Document, "save", side_effect=OSError("disk full")):
            self.assertFalse(w.save_all())
            w.show_panel("stats")   # a page of the unsaved structure.json
            self.assertFalse(w.save_current())
            w.show_panel("bench")
         self.assertIn("disk full", w.statusBar().currentMessage())
         self.assertTrue(panel.new_scenario("taken"))
         self.assertFalse(panel.new_scenario("taken"))
      box.assert_not_called()
      self.close(w)

   def test_migrate_offer_and_action(self) -> None:
      """!Pre-E6a stage data: opening it headless asks nothing (the status bar names the menu action); File >
      Migrate stages and chart migrates it as one undo step.
      @return None
      """
      data = json.loads(self.battle_json.read_text(encoding="utf-8"))
      data[stages.OLD_NAMES_KEY] = {"accuracy": "accuracy"}
      self.battle_json.write_text(json.dumps(data), encoding="utf-8")
      w, _panel = self.window("stages")
      self.assertTrue(stages.needs_any_migration(w.project.battle))
      self.assertTrue(w.migrate_action.isEnabled())
      self.assertTrue(w.migrate())
      self.assertFalse(stages.needs_any_migration(w.project.battle))
      self.assertTrue(w.project.battle.undo())
      self.assertTrue(stages.needs_any_migration(w.project.battle))
      self.close(w)

   def test_cost_boxes_rebuilt_without_signals(self) -> None:
      """!The move cost boxes a refresh replaces no longer reach the page (a focus change after the rebuild would
      read a deleted box); the new boxes do.
      @return None
      """
      w, panel = self.window("moves")
      self.select(panel, "Fireball")
      self.settle()
      old = list(panel.cost_boxes.values())
      self.assertTrue(old)
      panel.refresh()
      signal = QtCore.SIGNAL(EDITING_FINISHED)
      for box in old:
         self.assertEqual(box.lineEdit().receivers(signal), 0)
      for box in panel.cost_boxes.values():
         self.assertGreater(box.lineEdit().receivers(signal), 0)
      self.close(w)

   def test_undo_from_either_page(self) -> None:
      """!A rename made on the Moves page, then a structure edit: Undo on the Moves page undoes both, in order.
      @return None
      """
      w, panel = self.window("moves")
      p = w.project
      self.assertTrue(panel.edit("Rename move", lambda: battle.rename_entry(p.battle, "moves", "Strike", "Bonk")))
      cap = p.structure.data["rules"]["stat_cap"]
      self.assertTrue(w.run_edit("Stat cap", lambda: p.structure.data["rules"].__setitem__("stat_cap", cap - 1),
                                 p.structure))
      w.show_panel("moves")
      self.settle()
      w.undo()
      self.settle()
      self.assertEqual(p.structure.data["rules"]["fallback_move"], "Strike")
      self.assertIsNone(p.validate())
      self.close(w)

   def test_scenarios_follow_a_party_rename(self) -> None:
      """!Renaming a party on the Parties page rewrites the scenario the Bench page made (one undo step).
      @return None
      """
      w, panel = self.window("bench")
      panel.toolchain_check = lambda: []
      self.assertTrue(panel.new_scenario("duel"))
      doc = panel.scenario_doc()
      party = doc.data["parties"][0]["data"]
      p = w.project
      self.assertTrue(w.run_edit("Rename party", lambda: battle.rename_entry(p.battle, "parties", party, "Renamed"),
                                 p.battle))
      self.assertEqual(doc.data["parties"][0]["data"], "Renamed")
      self.assertEqual(bench.validate(doc.data, p), [])
      self.assertTrue(p.battle.undo())
      self.assertEqual(doc.data["parties"][0]["data"], party)
      self.close(w)


if __name__ == "__main__":
   unittest.main()
