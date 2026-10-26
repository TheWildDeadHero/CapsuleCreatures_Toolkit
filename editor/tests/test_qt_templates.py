#!/usr/bin/env python3
"""!Smoke tests of S10 in the Qt layer: the New game / New battle data
dialog over the templates (Blank, Starter), the Studio's New game and the
battle editor's New battle data, the Starter sample on every battle page
(Resources, Moves cost, Stats Odds column, Effects with the function
picker's odds() of 2 to 4 arguments), and Blank's effect_odds pipeline shown
as the engine default. Skipped when PySide6 is missing; uses Qt's offscreen
platform.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtCore = QtWidgets = None

from capsule_studio.core import manifest_io, templates  # noqa: E402


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtTemplateTests(unittest.TestCase):
   """!A temporary folder per test and isolated recent-files settings.

   @var root
   The folder.
   """

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Makes the folder.
      @return None
      """
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_templates_"))
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes it.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(3):
         self.app.processEvents()

   def battle_window(self, template: str) -> object:
      """!The battle editor on a new game made from a template.
      @param template  template id
      @return BattleWindow
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      templates.new_game(self.root / template, templates.find(template))
      w = BattleWindow(None, self.root / template / "data" / "battle.json")
      self.settle()
      self.assertIsNone(w.open_error)
      return w

   def test_dialog(self) -> None:
      """!Both modes list Blank and Starter (Starter first chosen); a game gets every part; battle data takes the
      ticked parts; a refusal shows in the dialog.
      @return None
      """
      from capsule_studio.ui.new_dialog import BATTLE, GAME, NewDialog
      d = NewDialog(GAME, self.root / "g")
      ids = [t.id for t in d.templates]
      self.assertEqual(ids[:2], ["blank", "starter"])
      self.assertEqual(d.template().id, "starter")
      self.assertFalse(d.part_boxes["logic"].isEnabled())   # a game takes every part
      self.assertIn("Starter", d.description.text())
      self.assertIn("effects/moves.ceffect", d.description.text())
      d.name.setText("Quest")
      created = d.create()
      self.assertEqual(created, self.root / "g" / "reference" / "project.json")
      self.assertEqual(manifest_io.load(created)["name"], "Quest")
      self.assertIsNone(d.create())   # the folder is not empty now
      self.assertIn("not an empty folder", d.message.text())
      b = NewDialog(BATTLE, self.root / "b")
      self.assertTrue(b.select("blank"))
      self.assertTrue(b.part_boxes["logic"].isEnabled())
      b.part_boxes["logic"].setChecked(False)
      self.assertEqual(b.parts(), ["structure", "content"])
      self.assertEqual(b.create(), self.root / "b" / "battle.json")
      self.assertFalse((self.root / "b" / "ruleset.json").exists())
      b.part_boxes["logic"].setChecked(True)
      b.part_boxes["structure"].setChecked(False)
      b.part_boxes["content"].setChecked(False)
      self.assertEqual(b.create(), self.root / "b" / "battle.json")   # the folder's battle manifest
      self.assertTrue((self.root / "b" / "ruleset.json").is_file())
      self.assertFalse(b.select("nothing"))
      b.folder.setText("")
      self.assertIsNone(b.create())
      self.assertIn("name the folder", b.message.text())

   def test_studio_new_game_and_battle_new(self) -> None:
      """!Studio > New game opens the new game's pages; the battle editor's New battle data opens the copy.
      @return None
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.studio_shell import StudioWindow
      w = StudioWindow(None)
      self.assertTrue(w.new_game("starter", self.root / "quest"))
      self.settle()
      self.assertEqual(w.project_path, (self.root / "quest" / "reference" / "project.json").resolve())
      self.assertIn("battle", w.windows)
      self.assertEqual(w.windows["battle"].project.battle.path, (self.root / "quest" / "data" / "battle.json"))
      self.assertFalse(w.new_game("starter", self.root / "quest"))   # not empty: refused, nothing waits
      w.close()
      b = BattleWindow(None)
      b.new_battle("blank", self.root / "fresh")
      self.settle()
      self.assertIsNotNone(b.project)
      self.assertEqual(b.project.battle.path, self.root / "fresh" / "battle.json")
      b.new_battle("blank", self.root / "fresh")   # its files exist: refused
      self.assertIn("overwrite", b.open_error)
      b.close()

   def test_starter_pages(self) -> None:
      """!The Starter sample on every page without a refusal; Resources lists HP, MP and EP with their persist
      roles and EP's regen; the Moves cost table shows Strike free; Stats has the Odds column; the Effects block
      view's function picker inserts odds() with 2 to 4 arguments.
      @return None
      """
      from capsule_studio.ui.battle_shell import BATTLE_PANELS
      from capsule_studio.ui.editors.structure.resources import RESOURCE_COLUMN
      from capsule_studio.ui.editors.structure.stats import STAT_COLUMN
      w = self.battle_window("starter")
      for cls in BATTLE_PANELS:
         w.show_panel(cls.panel_id)
         self.settle()
         self.assertIsNone(w.edit_error, cls.panel_id)
      panel = w.show_panel("resources")
      self.settle()
      self.assertEqual(panel.table.rowCount(), 3)
      self.assertEqual([panel.table.item(r, RESOURCE_COLUMN["name"]).text() for r in range(3)], ["hp", "mp", "ep"])
      self.assertEqual([panel.row_widgets[r]["persist"].currentText() for r in range(3)],
                       ["current_hp", "current_mp", "current_ep"])
      self.assertEqual(panel.row_widgets[2]["regen"].currentText(), "ep_regen")
      moves = w.show_panel("moves")
      moves.entry_list.setCurrentRow(moves.names().index("Strike"))
      self.settle()
      self.assertEqual(moves.cost_table.rowCount(), 3)
      stats = w.show_panel("stats")
      self.settle()
      odds = [stats.table.item(r, STAT_COLUMN["odds"]).checkState() == QtCore.Qt.CheckState.Checked
              for r in range(stats.table.rowCount())]
      self.assertEqual(odds.count(True), 1)
      stats.table.item(odds.index(True) - 1, STAT_COLUMN["odds"]).setCheckState(QtCore.Qt.CheckState.Checked)
      self.settle()
      self.assertEqual(w.undo_action.text(), "Undo Stat odds")
      w.undo()
      self.settle()
      effects = w.show_panel("effects")
      self.assertTrue(effects.select_owner("move:Flare Claw"))
      effects.set_view("blocks")
      self.settle()
      picker = effects.blocks.function_picker
      self.assertTrue(picker.select("odds"))
      self.assertEqual((picker.count.minimum(), picker.count.maximum()), (2, 4))
      self.assertTrue(picker.count.isEnabled())
      for n, text in ((2, "odds(1, 2)"), (3, "odds(1, 2, user)"), (4, "odds(1, 2, user, target)")):
         picker.count.setValue(n)
         self.assertEqual(picker.text(), text)
      self.assertIn("effect_odds", picker.help.text())
      picker.select("abs")
      self.assertFalse(picker.count.isEnabled())
      w._confirm_discard = lambda: True
      w.close()

   def test_blank_effect_odds_default(self) -> None:
      """!Blank leaves effect_odds out: the Pipelines page shows the engine's steps greyed with "engine default
      (plain odds)"; an edit starts from them, Engine default gives the pipeline back.
      @return None
      """
      w = self.battle_window("blank")
      panel = w.show_panel("pipelines")
      panel.pipeline.setCurrentText("effect_odds")
      self.settle()
      self.assertIn("engine default (plain odds)", panel.default_state.text())
      self.assertFalse(panel.reset_button.isEnabled())
      self.assertEqual(panel.step_list.count(), 4)
      panel.step_list.setCurrentRow(0)
      self.settle()
      self.assertTrue(panel.move_step(1))
      self.settle()
      self.assertIn("effect_odds", w.project.ruleset.data["pipelines"])
      self.assertFalse(panel.default_state.isVisibleTo(panel))
      self.assertTrue(panel.reset_button.isEnabled())
      self.assertTrue(panel.reset_pipeline())
      self.settle()
      self.assertNotIn("effect_odds", w.project.ruleset.data["pipelines"])
      w._confirm_discard = lambda: True
      w.close()


if __name__ == "__main__":
   unittest.main()
