#!/usr/bin/env python3
"""!The menu and text box styles Qt: the Menu styles panel on a copy of the menus fixture (tests/data/ui: a style's
menu given, edited through its widgets, the preview run over keys with the repeat, a list with its arrows), the
Text boxes panel's art (the stored palette, the frame's own colours, the arrow image's strip and settings), the
scene editor with a single panel (a tab change no longer reaches the actions before they exist: the field options'
save_action AttributeError), a JSON file of another schema opened read-only in the data view, the script editor's route
step help under the mouse, and the Test save page's Game box on a copy of the Starter sample. Skipped when PySide6 is
missing; uses Qt's offscreen platform. With CAPSULE_SHOTS=FOLDER it saves pictures of the panels.
"""
from __future__ import annotations

import json
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

from capsule_studio.core import engine, game_block, inventory, menu_styles, text_boxes  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## Folder of the pictures, or None.
SHOTS = Path(os.environ["CAPSULE_SHOTS"]) if os.environ.get("CAPSULE_SHOTS") else None
## Size of the windows in the pictures.
SHOT_SIZE = (1500, 900)
## The fixture's styles.
COLUMN, LIST, MESSAGE = "text_box:UI_COLUMN", "text_box:UI_LIST", "text_box:UI_MESSAGE"
## The repeat the preview runs with: frames before the first repeat, between repeats.
REPEAT = (40, 5)
## A test save's game block: version and size.
GAME_VERSION, GAME_SIZE = 2, 24


def settle(app: QtWidgets.QApplication) -> None:
   """!Runs pending events.
   @param app  the application
   @return None
   """
   for _ in range(3):
      app.processEvents()
      QtCore.QCoreApplication.sendPostedEvents()


def shot(app: QtWidgets.QApplication, w: QtWidgets.QWidget, name: str) -> None:
   """!Saves a picture of a window when CAPSULE_SHOTS names a folder.
   @param app   the application
   @param w     the window
   @param name  file stem
   @return None
   """
   if SHOTS is None:
      return
   SHOTS.mkdir(parents=True, exist_ok=True)
   w.resize(*SHOT_SIZE)
   w.show()
   settle(app)
   w.grab().save(str(SHOTS / f"{name}.png"))


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtMenuTextBoxStylesTests(unittest.TestCase):
   """!Drives the menu and text box styles scene editor panels, the shell and the data view."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies tests/data/ui.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_s5_"))
      shutil.copytree(engine.root() / "tests" / "data" / "ui", self.root / "ui")
      ## The fixture's manifest.
      self.assets = self.root / "ui" / "assets.json"
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def window(self, *panels: type) -> QtWidgets.QMainWindow:
      """!A scene editor on the copy with some panels.
      @param panels  panel classes
      @return EditorWindow
      """
      from capsule_studio.ui.shell import EditorWindow
      w = EditorWindow(list(panels), str(self.assets))
      settle(self.app)
      return w

   def test_menu_styles_panel(self) -> None:
      """!A style without a menu gets one; a setting edited through its combo; the list preview runs Down held past
      the repeat with its arrows; a setting refused leaves the style as it was.
      @return None
      """
      from capsule_studio.ui.editors.menu_styles import MenuStylePanel
      w = self.window(MenuStylePanel)
      panel = w.panels[0]
      self.assertEqual(panel.key, COLUMN)   # the first style with a menu
      self.assertIn("chose option", panel.summary.text())
      panel.key = MESSAGE
      panel._fill_style()
      self.assertIn("no menu", panel.checks.text())
      self.assertTrue(panel.set_menu(True))
      self.assertTrue(menu_styles.has_menu(text_boxes.find(w.document, MESSAGE)))
      combo = panel.editors["wrap"]
      combo.setCurrentText("always")
      combo.activated.emit(combo.currentIndex())
      self.assertEqual(text_boxes.find(w.document, MESSAGE)["menu"]["wrap"], "always")
      panel.cancel_boxes["START"].click()
      self.assertEqual(text_boxes.find(w.document, MESSAGE)["menu"]["cancel_keys"], ["B", "START"])
      self.assertFalse(panel.set_value("option_x", menu_styles.field_of("option_x").high + 1))
      panel.key = LIST
      panel._fill_style()
      for name, v in (("kind", "list"), ("shown", 3), ("repeat", list(REPEAT)),
                      ("script", f"down*{REPEAT[0] + REPEAT[1] + 1}")):
         self.assertTrue(panel._preview_set(name, v), name)
      settle(self.app)
      run = panel._run[1]
      self.assertEqual([f for f, t in run.events if "(move)" in t], [1, REPEAT[0] + 1, REPEAT[0] + REPEAT[1] + 1])
      self.assertTrue(run.arrows[-1].up and run.arrows[-1].down)
      self.assertIsNotNone(panel.view.image)
      self.assertTrue(panel.add_key("a"))
      settle(self.app)
      self.assertIn("chose option 3", panel.summary.text())
      shot(self.app, w, "menu_styles_list")

   def test_text_box_art(self) -> None:
      """!The stored palette's switch writes the style's palette, a bank colour lands in it; the frame gets its own
      colours; the arrow image's strip shows its steps and a setting edits it.
      @return None
      """
      from capsule_studio.ui.editors.text_boxes import TextBoxPanel
      w = self.window(TextBoxPanel)
      panel = w.panels[0]
      panel.key = MESSAGE
      panel._fill_style()
      self.assertTrue(panel.stored.isChecked())
      self.assertIsNotNone(panel.arrow_view.image)
      self.assertEqual(panel.arrow_path.text(), "arrow.png")
      self.assertTrue(panel.set_color(1, (16, 32, 48)))
      self.assertEqual(text_boxes.find(w.document, MESSAGE)["palette"][0], "#102030")
      self.assertTrue(panel.set_frame_palette(True))
      self.assertTrue(panel.set_frame_color(2, (255, 0, 0)))
      self.assertEqual(text_boxes.frame_palette(text_boxes.find(w.document, MESSAGE))[1], "#ff0000")
      panel.arrow_delay.setValue(3)
      panel.arrow_delay.editingFinished.emit()
      self.assertEqual(text_boxes.arrow_image(text_boxes.find(w.document, MESSAGE))["delay"], 3)
      self.assertTrue(panel.set_stored_palette(False))
      self.assertNotIn("palette", text_boxes.find(w.document, MESSAGE))
      self.assertIn("draws this box", panel.checks.text())
      shot(self.app, w, "text_box_arrow_image")

   def test_single_panel_window_and_data_view(self) -> None:
      """!A scene editor of one panel builds and changes tabs without an error; a JSON of another schema opens in
      the read-only data view instead of being refused.
      @return None
      """
      from capsule_studio.ui import json_view
      from capsule_studio.ui.editors.menu_styles import MenuStylePanel
      w = self.window(MenuStylePanel)
      w.tabs.currentChanged.emit(0)   # the field options' report: save_action was not there yet
      w._tab_changed(-1)
      self.assertTrue(w.save_action is not None)
      other = self.root / "menus.json"
      other.write_text(json.dumps({"schema": "capsule_import.menus/1", "multichoice": [{"id": 0}]}), encoding="utf-8")
      before = len(json_view._OPEN)
      w.open_file(other)
      settle(self.app)
      self.assertEqual(len(json_view._OPEN), before + 1)
      view = json_view._OPEN[-1]
      self.assertIn("read-only", view.view.banner.text())
      self.assertEqual(view.view.rows(), 2)
      item = view.view.tree.topLevelItem(1)
      view.view.tree.expandItem(item)
      self.assertEqual(item.child(0).text(0), "[0]")
      self.assertEqual(w.document.path, self.assets.resolve())   # the manifest stays open
      view.close()

   def test_script_hover_help(self) -> None:
      """!The script editor's word help names a route step's run-time behaviour inside a movement only.
      @return None
      """
      from capsule_studio.core import script_words
      from capsule_studio.ui.editors.script import CodeEditor
      ed = CodeEditor()
      ed.word_help = script_words.word_help
      ed.setPlainText("movement walk { in_place up; speed 3; }\n")
      text = ed.toPlainText()
      self.assertIn("walk animation", ed.word_help(text[:text.index("in_place")], "in_place"))
      self.assertIsNone(ed.word_help("", "speed"))


class QtGameBoxTests(QtBattleTestCase):
   """!The Test save page's Game box."""

   def test_game_box(self) -> None:
      """!Apply writes the version, size and bytes; the export carries the Game section; Remove takes it out.
      @return None
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.editors.content.test_save import TestSavePanel
      w = BattleWindow([TestSavePanel], self.battle_json)
      panel = w.show_panel("test_save")
      self.settle()
      self.assertTrue(panel.new_save("game"))
      self.assertTrue(panel.game_box.isVisibleTo(panel))
      panel.game_version.setValue(GAME_VERSION)
      panel.game_size.setValue(GAME_SIZE)
      panel.game_hex.setPlainText("de ad be ef")
      self.assertTrue(panel.set_game_from_form())
      g = game_block.game_of(panel.save)
      self.assertEqual((g["version"], g["size"], g["bytes"]), (GAME_VERSION, GAME_SIZE, "deadbeef"))
      self.assertIn(f"version {GAME_VERSION}, {GAME_SIZE} bytes", panel.game_info.text())
      out = self.root / "game.sav"
      self.assertTrue(panel.export_save(out))
      self.assertIn("game", game_block.sections(out.read_bytes())[1])
      panel.game_hex.setPlainText("xyz")
      self.assertFalse(panel.set_game_from_form())
      other = inventory.new_testsave(w.project, "copy")
      self.assertTrue(panel.open_save("copy"))
      self.assertTrue(panel.game_from_file(out))
      self.assertEqual(game_block.game_of(panel.save)["bytes"], "deadbeef")
      self.assertIsNotNone(other)
      shot(self.app, w, "test_save_game_block")
      self.assertTrue(panel._change("No game block", lambda save, _d: game_block.clear_game(save)))
      self.assertIsNone(game_block.game_of(panel.save))


if __name__ == "__main__":
   unittest.main()
