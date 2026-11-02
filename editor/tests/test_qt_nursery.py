#!/usr/bin/env python3
"""!Smoke tests of the nursery pages: Structure > Nursery (the Starter's eggs and Grove in the boxes, edits through the
widgets, the refusal table), the egg flags on the Turn, Recruit, Field actions and Items pages, the Species page's
Eggs row and the Test save page's boxed eggs and Nursery box. Each opens a copy of the map sandbox laid out as one
game (sample_data.make_field_game) and edits through the widgets. Skipped when PySide6 is missing; uses Qt's
offscreen platform. CAPSULE_SHOTS=FOLDER saves a picture of each page there.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core import battle, inventory  # noqa: E402
from capsule_studio.core.structure import nursery, species_fields  # noqa: E402
from sample_data import make_field_game  # noqa: E402
from test_nursery import BREEZLE, CHECK, GROVE, SAVE, SPROUTLE, SPROUTLE_CYCLES, STEPS  # noqa: E402

## Environment variable naming a folder for the pages' pictures.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a picture, pixels.
SHOT_SIZE = (1280, 860)
## Settle passes (scheduled refreshes).
SETTLE_PASSES = 3
## Hatch cycles the Species page's Eggs row sets.
NEW_CYCLES = 6


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class NurseryPageTests(unittest.TestCase):
   """!The Nursery page and the nursery parts of the other pages."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies the game.
      @return None
      """
      ## The game folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_b2_"))
      ## Its battle.json.
      self.battle_json = make_field_game(self.root)
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(SETTLE_PASSES):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def shot(self, w: object, name: str) -> None:
      """!Saves a picture of a window when CAPSULE_SHOTS names a folder.
      @param w     the window
      @param name  file stem
      @return None
      """
      shots = os.environ.get(SHOTS_ENV)
      if not shots:
         return
      Path(shots).mkdir(parents=True, exist_ok=True)
      w.resize(*SHOT_SIZE)
      w.show()
      self.settle()
      w.grab().save(str(Path(shots) / f"{name}.png"))

   def window(self, classes: list[type], panel_id: str) -> tuple[object, object]:
      """!A battle editor on the copy with some pages.
      @param classes   the panel classes
      @param panel_id  the page shown
      @return (BattleWindow, the panel)
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      w = BattleWindow(classes, self.battle_json)
      panel = w.show_panel(panel_id)
      self.settle()
      return w, panel

   def test_nursery_page(self) -> None:
      """!The Starter's eggs and Grove in the boxes; an egg name, gain and fee through the widgets; a refusal flag
      through the table; eggs off refused while the Grove delivers them.
      @return None
      """
      from capsule_studio.ui.battle_shell import BATTLE_PANELS
      from capsule_studio.ui.editors.structure.nursery import CHECK_COLUMN, NurseryPanel
      self.assertIn(NurseryPanel, BATTLE_PANELS)
      from capsule_studio.ui.editors.content.species import SpeciesPanel
      w, panel = self.window([NurseryPanel, SpeciesPanel], "nursery")
      p = w.project
      self.assertIs(w.document, p.structure)
      self.assertTrue(panel.has_eggs.isChecked())
      self.assertEqual(panel.egg_combos["role"].currentText(), "egg")
      self.assertEqual(panel.egg_combos["hatch_script"].currentText(), "hatch_egg")
      self.assertTrue(panel.has_nursery.isChecked())
      self.assertEqual((panel.method.currentText(), panel.check.currentText()), (GROVE, CHECK))
      self.assertIn(GROVE, panel.egg_info.text())
      self.assertTrue(panel.set_egg("name", "Seed"))
      self.assertTrue(panel.set_nursery("gain", True))
      self.assertTrue(panel.set_nursery("fee", True))
      self.settle()
      self.assertTrue(panel.fee.isChecked())
      self.assertIn("Fee:", panel.fee_info.text())
      self.assertEqual(nursery.eggs(p.structure)["name"], "Seed")
      row = next(r for r in range(panel.refusals.rowCount()) if panel.refusals.item(r, 1).text() == "Orb")
      panel.refusals.item(row, CHECK_COLUMN).setCheckState(QtCore.Qt.CheckState.Checked)
      self.settle()
      self.assertTrue(battle.entry(p.battle, "items", "Orb").get("allow_eggs"))
      self.shot(w, "studio_nursery")
      self.assertFalse(panel.set_eggs_on(False))   # the Grove delivers eggs
      self.settle()
      self.assertTrue(panel.has_eggs.isChecked())
      w.undo_action.trigger()
      self.settle()
      self.assertNotIn("allow_eggs", battle.entry(p.battle, "items", "Orb"))
      w.close()

   def test_flags_on_their_pages(self) -> None:
      """!Turn (battle setup), Recruit, Field actions and Items each set their own egg flag.
      @return None
      """
      from capsule_studio.ui.editors.content.holders import PassivesItemsPanel
      from capsule_studio.ui.editors.structure.field_actions import FieldActionsPanel
      from capsule_studio.ui.editors.structure.recruit import RecruitPanel
      from capsule_studio.ui.editors.structure.turn import TurnPanel
      w, turn = self.window([TurnPanel, RecruitPanel, FieldActionsPanel, PassivesItemsPanel], "turn")
      p = w.project
      self.assertFalse(turn.allow_eggs.isChecked())
      self.assertTrue(turn.set_allow_eggs(True))
      self.settle()
      self.assertTrue(nursery.allowed(p.structure, "rules"))
      self.assertTrue(turn.allow_eggs.isChecked())
      recruit = w.show_panel("recruit")
      self.settle()
      self.assertTrue(recruit.set_allow_eggs(True))
      self.assertTrue(nursery.allowed(p.structure, "recruit"))
      actions = w.show_panel("field_actions")
      self.settle()
      actions.allow_eggs.click()
      self.settle()
      self.assertTrue(nursery.allowed(p.structure, "field_actions", actions.selected))
      self.shot(w, "studio_field_action_eggs")
      w.close()

   def test_species_and_test_save(self) -> None:
      """!The Species page's Eggs row edits the hatch cycles; the Test save page boxes an egg, fills the nursery and
      the waiting egg, and exports them.
      @return None
      """
      from capsule_studio.ui.editors.content.species import SpeciesPanel
      from capsule_studio.ui.editors.content.test_save import EGG_COLUMN, EMPTY_SLOT, TestSavePanel
      w, species = self.window([SpeciesPanel, TestSavePanel], "species")
      p = w.project
      species.entry_list.setCurrentRow(species.names().index(SPROUTLE))
      self.settle()
      self.assertEqual(species.hatch_cycles.value(), SPROUTLE_CYCLES)
      self.assertIn(f"{GROVE}: {SPROUTLE_CYCLES * 256} steps", species.egg_info.text())
      species.hatch_cycles.setValue(NEW_CYCLES)
      species.hatch_cycles.editingFinished.emit()
      self.settle()
      own = next(v for v in species_fields.values_of(p.battle, SPROUTLE) if v["name"] == "hatch_cycles")
      self.assertEqual(own["value"], NEW_CYCLES)
      self.shot(w, "studio_species_eggs")
      panel = w.show_panel("test_save")
      self.settle()
      self.assertTrue(panel.new_save(SAVE))
      self.assertEqual(panel.held.rowCount(), 2)
      self.assertEqual(panel.held.item(0, 1).text(), EMPTY_SLOT)
      self.assertTrue(panel.box_creature(SPROUTLE, 5))
      panel.boxed.selectRow(0)
      panel.box_hatch.setValue(STEPS)
      self.assertTrue(panel.set_boxed_egg(panel.box_hatch.value()))
      self.assertEqual(panel.boxed.item(0, EGG_COLUMN).text(), str(STEPS))
      panel.held.selectRow(0)
      panel.held_species.setCurrentText(BREEZLE)
      panel.held_gained.setValue(120)
      self.assertTrue(panel.leave_selected())
      self.assertEqual(panel.held.item(0, 1).text(), BREEZLE)
      panel.result_species.setCurrentText(SPROUTLE)
      panel.result_egg.setChecked(True)
      panel.result_hatch.setValue(STEPS)
      self.assertTrue(panel.set_result_from_form())
      save = inventory.open_testsave(p, SAVE)
      self.assertEqual(nursery.result_of(save), {"species": SPROUTLE, "level": 1, "hatch": STEPS})
      self.assertEqual(inventory.check(save, p.battle), [])
      self.shot(w, "studio_test_save_nursery")
      out = self.root / "grove.sav"
      self.assertTrue(panel.export_save(out))
      self.assertTrue(out.is_file())
      panel.held.selectRow(0)
      self.assertTrue(panel.take_back_selected())
      self.assertEqual(panel.held.item(0, 1).text(), EMPTY_SLOT)
      w.close()


if __name__ == "__main__":
   unittest.main()
