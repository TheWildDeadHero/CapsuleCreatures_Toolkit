#!/usr/bin/env python3
"""!Smoke tests of the combination pages: Structure > Combination (the method list, the tabs editing the Starter's Merge
Altar and a new method, the preview on typed species and on a test save's boxed creatures, a rename following the logic
and the scripts, a refused removal) and the Species page's named field values and Combine moves tab. Each opens a copy
of the map sandbox laid out as one game (sample_data.make_field_game) and edits through the widgets. Skipped when
PySide6 is missing; uses Qt's offscreen platform. CAPSULE_SHOTS=FOLDER saves a picture of each page there.
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
from capsule_studio.core.structure import combination, species_fields, storage  # noqa: E402
from sample_data import DATA, make_field_game  # noqa: E402
from test_combination import (ALTAR, BREEZLE, ELEMENTS, FIT_LEVEL, GLIMMET, GROUP_FIELD, GROUP_VALUES,  # noqa: E402
                              GROVE, ROLES, SANDBOX_SCRIPTS, SAVE, SPROUTLE, TIDEPUP, UNFIT_LEVEL)

## Environment variable naming a folder for the pages' pictures.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a picture, pixels.
SHOT_SIZE = (1200, 820)
## Settle passes (scheduled refreshes).
SETTLE_PASSES = 3
## The page's tabs, in order.
TABS = ["Method", "Slots", "Tables", "Rules", "Moves", "Messages"]


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class CombinationPageTests(unittest.TestCase):
   """!The Combination page and the Species page's combination parts."""

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
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_b1_"))
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
      w.grab().save(str(Path(shots) / f"{name}.png"))

   def window(self, panel_id: str) -> tuple[object, object]:
      """!A battle editor on the copy with the Combination and Species pages.
      @param panel_id  the page shown
      @return (BattleWindow, the panel)
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.editors.content.species import SpeciesPanel
      from capsule_studio.ui.editors.structure.combination import CombinationPanel
      w = BattleWindow([CombinationPanel, SpeciesPanel], self.battle_json)
      panel = w.show_panel(panel_id)
      self.settle()
      return w, panel

   def test_combination_page(self) -> None:
      """!The altar in the tabs; the preview on typed inputs and a test save; a new method edited through the
      widgets; a refused removal; a rename following the scripts (one undo step).
      @return None
      """
      from capsule_studio.ui.battle_shell import BATTLE_PANELS
      from capsule_studio.ui.editors.structure.combination import TYPED_INPUTS, CombinationPanel
      self.assertIn(CombinationPanel, BATTLE_PANELS)
      w, panel = self.window("combination")
      p = w.project
      self.assertIs(w.document, p.structure)
      self.assertEqual(panel.names(), [ALTAR, GROVE])
      self.assertEqual([panel.tabs.tabText(i) for i in range(panel.tabs.count())], TABS)
      self.assertEqual(panel.selected, ALTAR)
      self.assertEqual(panel.label.text(), "Merge Altar")
      self.assertEqual(panel.afterwards.currentText(), "consumed")
      self.assertEqual(panel.slots.rowCount(), len(ROLES))
      self.assertEqual(panel.slots.item(0, 0).text(), ROLES[0])
      self.assertEqual(panel.table.currentText(), ELEMENTS)
      self.assertGreater(panel.grid.rowCount(), 0)
      self.assertEqual(panel.rules.count(), 1)
      self.assertIn("merge_rule", panel.users_text.text())
      # the preview: typed species, then a refusal
      (a, la), (b, lb) = panel.inputs[:2]
      a.setCurrentText(BREEZLE)
      b.setCurrentText(TIDEPUP)
      la.setValue(FIT_LEVEL)
      lb.setValue(FIT_LEVEL)
      self.assertIn(f"-> {GLIMMET}", panel.run_preview())
      self.shot(w, panel, "studio_combination")
      la.setValue(UNFIT_LEVEL)
      a.setCurrentText(SPROUTLE)
      self.assertIn("refused: unfit", panel.run_preview())
      # a test save's boxed creatures
      save = inventory.new_testsave(p, SAVE)
      with save.edit("Box"):
         storage.put_creature(save, p.structure, BREEZLE, FIT_LEVEL)
         storage.put_creature(save, p.structure, TIDEPUP, FIT_LEVEL)
      save.save()
      panel.refresh()
      panel.save.setCurrentText(SAVE)
      panel._fill_preview_inputs()
      self.assertIn(GLIMMET, panel.preview_text.text())
      panel.save.setCurrentText(TYPED_INPUTS)
      panel._fill_preview_inputs()
      # the grid: the Light x Darkness cell gives Cosmic
      panel.tabs.setCurrentIndex(TABS.index("Tables"))
      self.shot(w, panel, "studio_combination_tables")
      # a refused removal (merge_rule and the sandbox script name it)
      self.assertFalse(panel.remove_method())
      self.assertEqual(panel.names(), [ALTAR, GROVE])
      # a new method through the widgets
      self.assertTrue(panel.add_method("fuse"))
      self.settle()
      self.assertEqual(panel.selected, "fuse")
      self.assertEqual(panel.names(), [ALTAR, "fuse", GROVE])
      panel.count_hi.setValue(3)
      self.assertTrue(panel.apply_count())
      self.settle()
      self.assertEqual(panel.slots.rowCount(), 3)
      self.assertTrue(panel.set_slot(0, role="left"))
      self.assertIn("left.", combination.rules_of(combination.method(p.structure, "fuse"))[0]["expression"])
      self.assertTrue(panel.add_recipe([BREEZLE, TIDEPUP], GLIMMET))
      self.assertTrue(panel.add_table("kins"))
      self.settle()
      self.assertTrue(panel.set_cell("Wind", "Water", "Light"))
      self.assertEqual(combination.cells(p.structure, "fuse", "kins"), {("Wind", "Water"): "Light"})
      self.assertTrue(panel.apply_message("combined", "merge_done"))
      self.assertTrue(panel.set_source("known", True, 2))
      self.settle()
      panel.tabs.setCurrentIndex(TABS.index("Rules"))
      self.shot(w, panel, "studio_combination_new")
      self.assertIsNone(p.error_now())
      # a rename of the altar follows the logic and the scripts; one undo step brings it back
      panel.list.setCurrentRow(0)
      self.settle()
      self.assertEqual(panel.selected, ALTAR)
      self.assertTrue(panel.rename_method("altar"))
      self.settle()
      scripts = self.root.joinpath(DATA, *SANDBOX_SCRIPTS)
      self.assertIn("combine open altar", scripts.read_text(encoding="utf-8"))
      self.assertIn("combine_method == altar", p.effect_source("effects/field.ceffect").text)
      w.undo()
      self.settle()
      self.assertIn(ALTAR, panel.names())

   def test_move_source_from(self) -> None:
      """!The Moves tab's From column (one slot role per source, every input by default) and the push check.
      @return None
      """
      from capsule_studio.ui.editors.structure.combination import (ANY_INPUT_TEXT, SOURCE_FROM_COLUMN,
                                                                    SOURCE_ON_COLUMN)
      w, panel = self.window("combination")
      p = w.project
      panel.list.setCurrentRow(panel.names().index(GROVE))
      self.settle()
      self.assertEqual(panel.selected, GROVE)
      panel.tabs.setCurrentIndex(TABS.index("Moves"))
      kinds = combination.move_sources()
      row = kinds.index("combine_moves")
      combo = panel.sources.cellWidget(row, SOURCE_FROM_COLUMN)
      self.assertEqual(combo.currentText(), ANY_INPUT_TEXT)
      self.assertEqual([combo.itemText(i) for i in range(combo.count())], [ANY_INPUT_TEXT, *ROLES])
      self.assertTrue(panel.set_source("combine_moves", True, 0, False, ROLES[1]))
      self.settle()
      self.assertEqual(combination.sources_of(combination.method(p.structure, GROVE))[0]["from"], ROLES[1])
      self.assertEqual(panel.sources.cellWidget(row, SOURCE_FROM_COLUMN).currentText(), ROLES[1])
      panel.push.click()
      self.settle()
      self.assertTrue(combination.method(p.structure, GROVE)["moves"]["push"])
      self.assertTrue(panel.push.isChecked())
      # the combo itself: back to every input
      combo = panel.sources.cellWidget(row, SOURCE_FROM_COLUMN)
      combo.setCurrentIndex(0)
      panel._source_edited(panel.sources.item(row, SOURCE_ON_COLUMN))
      self.settle()
      self.assertNotIn("from", combination.sources_of(combination.method(p.structure, GROVE))[0])
      self.assertTrue(panel.set_source("combine_moves", True, 0, False, ROLES[0]))
      self.settle()
      self.assertIsNone(p.error_now())
      self.shot(w, panel, "studio_move_sources")

   def test_species_parts(self) -> None:
      """!A named-values field shows as a combo of its names; the Combine moves tab adds, moves and removes.
      @return None
      """
      w, panel = self.window("species")
      p = w.project
      with p.structure.edit("Field"):
         species_fields.add_field(p.structure, GROUP_FIELD, 2)
         species_fields.set_values(p.structure, GROUP_FIELD, GROUP_VALUES)
      w.changed()
      self.settle()
      panel.entry_list.setCurrentRow(panel.names().index(BREEZLE))
      self.settle()
      self.assertEqual(panel.selected, BREEZLE)
      box = panel.field_spins[GROUP_FIELD]
      self.assertIsInstance(box, QtWidgets.QComboBox)
      self.assertEqual([box.itemText(i) for i in range(box.count())], GROUP_VALUES)
      box.setCurrentIndex(2)
      box.activated.emit(2)
      self.settle()
      own = next(v for v in species_fields.values_of(p.battle, BREEZLE) if v["name"] == GROUP_FIELD)
      self.assertEqual(own["value"], GROUP_VALUES[2])
      tabs = panel.growth_tabs
      tabs.setCurrentIndex(tabs.count() - 1)
      self.assertEqual(tabs.tabText(tabs.count() - 1), "Combine moves")
      before = tabs.combine_move_names()
      self.assertTrue(before)
      added = next(m for m in p.names("moves") if m not in before)
      tabs.add_combine_move(added)
      self.settle()
      self.assertEqual(tabs.combine_move_names(), before + [added])
      tabs.combine_moves.setCurrentRow(len(before))
      tabs.move_combine_move(-1)
      self.settle()
      self.assertEqual(tabs.combine_move_names()[len(before) - 1], added)
      tabs.combine_moves.setCurrentRow(len(before) - 1)
      tabs.remove_combine_move()
      self.settle()
      self.assertEqual(tabs.combine_move_names(), before)
      entry = battle.entry(p.battle, "species", BREEZLE)
      self.assertEqual(entry[battle.COMBINE_MOVES_KEY], before)
      self.shot(w, panel, "studio_species_combine")


if __name__ == "__main__":
   unittest.main()
