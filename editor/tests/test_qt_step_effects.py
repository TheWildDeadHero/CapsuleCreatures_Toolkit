#!/usr/bin/env python3
"""!Smoke tests of the F3 pages: Structure > Step effects (the list, the form with the engine's choices, the messages
and the game's scripts as choices, the logic running `on steps`, add / rename / remove through the widgets) and the
Test save page's Step counters box. Each opens a copy of the map sandbox laid out as one game
(sample_data.make_field_game: the Starter's blight and bond effects, the sandbox's scripts) and edits through the
widgets. Skipped when PySide6 is missing; uses Qt's offscreen platform. CAPSULE_SHOTS=FOLDER saves a picture of each
page there.
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

from capsule_studio.core import inventory, logic  # noqa: E402
from capsule_studio.core.structure import step_effects  # noqa: E402
from sample_data import make_field_game  # noqa: E402
from test_step_effects import NAMES  # noqa: E402

## Environment variable naming a folder for the pages' pictures.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a picture, pixels.
SHOT_SIZE = (1200, 760)
## The Test save page's size for its picture (its boxes stack).
SAVE_SHOT_SIZE = (1200, 980)


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class StepEffectPagesTests(unittest.TestCase):
   """!The Step effects page and the Test save page's step counters."""

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
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_f3_"))
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
      for _ in range(3):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def shot(self, w: object, panel: object, name: str, size: tuple[int, int] = SHOT_SIZE) -> None:
      """!Saves a picture of a page when CAPSULE_SHOTS names a folder.
      @param w     the window
      @param panel the page
      @param name  file stem
      @param size  the window's size
      @return None
      """
      shots = os.environ.get(SHOTS_ENV)
      if not shots:
         return
      Path(shots).mkdir(parents=True, exist_ok=True)
      w.resize(*size)
      w.show()
      self.settle()
      panel.grab().save(str(Path(shots) / f"{name}.png"))

   def battle_window(self, panel_id: str) -> tuple[object, object]:
      """!A battle editor on the copy with the F3 pages (and Logic > Effects for the Logic... button).
      @param panel_id  the page's panel id
      @return (BattleWindow, the panel)
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.editors.content.test_save import TestSavePanel
      from capsule_studio.ui.editors.logic.effects_panel import EffectsPanel
      from capsule_studio.ui.editors.structure.step_effects import StepEffectsPanel
      w = BattleWindow([StepEffectsPanel, TestSavePanel, EffectsPanel], self.battle_json)
      panel = w.show_panel(panel_id)
      self.settle()
      return w, panel

   def test_step_effects_page(self) -> None:
      """!The Starter's effects with the engine's choices; the damage rule and a message through the widgets; the
      handler table; add, rename (the logic follows), a refused removal, Logic....
      @return None
      """
      w, panel = self.battle_window("step_effects")
      p = w.project
      self.assertIs(w.document, p.structure)
      self.assertEqual(panel.names(), NAMES)
      self.assertEqual(panel.selected, "blight")
      self.assertEqual(panel.every.value(), 4)
      self.assertEqual(panel.damage.currentText(), "survive")
      self.assertEqual(panel.messages["survived"].currentText(), "blight_survived")
      self.assertIn("field_wade", [panel.script.itemText(i) for i in range(panel.script.count())])
      self.assertIn("step_effect_blight", panel.implicit.text())
      self.assertIn("Blight", panel.used_by.text())
      self.assertEqual(panel.handlers.item(0, 0).text(), f"{logic.global_kind()} bond_rule")
      self.assertEqual(panel.handlers.item(1, 0).text(), "status Blight")
      self.shot(w, panel, "studio_step_effects")
      panel.damage.setCurrentText("faint")
      panel.damage.activated.emit(panel.damage.currentIndex())
      self.settle()
      self.assertNotIn("damage", step_effects.effects(p.structure)[0])   # faint is the default: the key goes
      self.assertEqual(w.undo_action.text(), "Undo Set step effect")
      combo = panel.messages["hurt"]
      combo.setCurrentText("blight_survived")
      combo.activated.emit(combo.currentIndex())
      self.settle()
      self.assertEqual(step_effects.effects(p.structure)[0]["messages"]["hurt"], "blight_survived")
      self.assertTrue(panel.add_effect("hatch"))
      self.settle()
      self.assertEqual(step_effects.effect_names(p.structure), ["blight", "hatch", "bond", "grove_check",
                                                                     "egg_cycle"])
      self.assertTrue(panel.rename_effect("egg"))
      self.settle()
      self.assertTrue(panel.remove_effect())
      self.settle()
      panel.selected = "blight"
      panel.refresh()
      self.assertTrue(panel.rename_effect("sting"))
      self.settle()
      self.assertIn("field.step_effect == sting", p.effect_source("effects/conditions.ceffect").text)
      self.assertFalse(panel.remove_effect())   # the logic names it
      panel.handlers.selectRow(1)
      self.assertTrue(panel.show_logic())
      self.settle()
      self.shot(w, w.show_panel("effects"), "studio_logic_on_steps")   # Logic > Effects on status Blight
      self.assertIsNone(p.error_now())

   def test_test_save_counters(self) -> None:
      """!The Step counters box lists the effects; Set changes the selected counter (saved at once); a count past
      every is refused.
      @return None
      """
      w, panel = self.battle_window("test_save")
      p = w.project
      self.assertTrue(panel.new_save("walk"))
      self.settle()
      self.assertEqual(panel.steps.rowCount(), len(NAMES))
      self.assertEqual(panel.steps.item(0, 0).text(), "blight")
      panel.steps.selectRow(0)
      self.assertTrue(panel.set_step_selected(3))
      self.settle()
      self.assertEqual(panel.steps.item(0, 1).text(), "3")
      self.assertEqual(panel.steps.item(0, 3).text(), "1")
      save = inventory.open_testsave(p, "walk")
      self.assertEqual(step_effects.counters_of(save), {"blight": 3})
      panel.steps.selectRow(1)
      self.assertTrue(panel.set_step_selected(40))
      self.settle()
      self.shot(w, panel, "studio_test_save_step_counters", SAVE_SHOT_SIZE)
      panel.steps.selectRow(0)
      import capsule_studio.ui.editors.content.test_save as page
      failures = []
      original = page.report_failure
      page.report_failure = lambda _w, title, text: failures.append((title, text))
      try:
         self.assertFalse(panel.set_step_selected(4))
      finally:
         page.report_failure = original
      self.assertTrue(failures)
      self.assertEqual(step_effects.counters_of(inventory.open_testsave(p, "walk")), {"blight": 3, "bond": 40})


if __name__ == "__main__":
   unittest.main()
