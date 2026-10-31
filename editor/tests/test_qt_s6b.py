#!/usr/bin/env python3
"""!S6b (engine C13a / C13b / C13c) Qt panels: the font panel's glyph height (kept, edited, the rows below it shown
as not drawn), the text box panel's window storage line, the screen plan panel's exit choosers, Exit timing tab and
window buffer line, and the World page's Interactions tab (a rule added from the form after the chosen one, moved,
changed, removed, undone; the compiler's verdict under the form). Skipped when PySide6 is missing; uses Qt's
offscreen platform.
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

import text_fixture as fx  # noqa: E402
from capsule_studio.core import engine, fonts, interactions, screen_plans as sp  # noqa: E402
from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402

## The engine fixtures the Interactions tab opens (C13b names D-30's tileset).
INTERACTION_FIXTURES = ("c13b", "d30")
## The fixture's rules.
FIXTURE_RULES = 7
## The glyph height the font test sets.
GLYPH_HEIGHT = 3


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtS6bTests(unittest.TestCase):
   """!Drives the S6b panel parts."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!A temporary folder.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_s6b_"))

   def tearDown(self) -> None:
      """!Removes the folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events.
      @return None
      """
      for _ in range(3):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def close(self, w: QtWidgets.QWidget, docs: list) -> None:
      """!Closes a window without asking.
      @param w     the window
      @param docs  its Documents
      @return None
      """
      for d in docs:
         d.dirty = False
      w.close()

   def test_font_and_box_panels(self) -> None:
      """!The glyph height spin edits the font; the editor and grid know the drawn rows; the box shows its storage.
      @return None
      """
      from capsule_studio.ui.editors.fonts import FontPanel
      from capsule_studio.ui.editors.text_boxes import TextBoxPanel
      from capsule_studio.ui.shell import EditorWindow
      game = fx.make_game(self.root)
      w = EditorWindow([FontPanel, TextBoxPanel], game.assets)
      w.show()
      self.settle()
      fp, bp = w.panels
      self.assertEqual((fp.glyph_height.value(), fp.glyph_height.specialValueText()), (0, "whole cell"))
      fp.glyph_height.setValue(GLYPH_HEIGHT)
      fp._metric_changed(fonts.GLYPH_HEIGHT, fp.glyph_height)
      doc = fp.font_doc()
      self.assertEqual(doc.data[fonts.GLYPH_HEIGHT], GLYPH_HEIGHT)
      self.assertEqual(doc.undo_label(), "Glyph height")
      self.assertTrue(fp.select_glyph("W"))
      self.assertEqual(fp.canvas.drawn_rows, GLYPH_HEIGHT)
      self.assertIsNotNone(fp.view.image)
      fp.glyph_height.setValue(0)
      fp._metric_changed(fonts.GLYPH_HEIGHT, fp.glyph_height)
      self.assertNotIn(fonts.GLYPH_HEIGHT, doc.data)
      w.tabs.setCurrentWidget(bp)
      bp.add_style("text_box:MAIN")
      self.settle()
      self.assertIsNotNone(bp.style())
      self.assertIn("Window storage: ", bp.checks.text())
      self.assertIn("tiles", bp.checks.text())
      self.close(w, [w.document] + w.extra_documents())

   def test_plan_panel(self) -> None:
      """!The exit choosers, the Exit timing tab and the window buffer line.
      @return None
      """
      from capsule_studio.ui.shell import EditorWindow
      apps = copy_engine_apps(self.root, ["sandbox_screen"], ("data", "reference"))
      data = apps / "sandbox_screen" / "data"
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))
      w = EditorWindow(None, str(data / "assets.json"))
      w.show()
      self.settle()
      p = next(x for x in w.panels if x.panel_id == "screen_plans")
      w.tabs.setCurrentWidget(p)
      self.assertTrue(p.new_plan("menu"))
      self.assertTrue(p.add_item("layers"))
      self.assertTrue(p.add_item("windows", name="title", w=20, h=2))
      self.assertIn("Window buffers: 1 window(s), 40 tiles, 1280 bytes", p.storage.text())
      self.assertIn("40 tiles 1280 B", p.tree.topLevelItem(sp.SECTIONS.index("windows")).child(0).text(0))
      self.assertIn("frame 23: the screen leaves", p.exit_frames.toPlainText())
      self.assertFalse(p.exit_next.isEnabled())
      p.exit_call.setCurrentIndex(p.exit_call.findData("close_now"))
      p._exit_edited()
      self.assertEqual(p.plan.data["exit"], {"call": "close_now"})
      self.assertTrue(p.exit_frames.toPlainText().startswith("frame 0: close_now()"))
      texts = [p.problems.item(i).text() for i in range(p.problems.count())]
      self.assertTrue(any("never plays the out fade" in t for t in texts), texts)
      self.assertTrue(p.set_exit("replace", "menu_two"))
      self.assertTrue(p.exit_next.isEnabled())
      self.assertEqual(p.exit_next.currentText(), "menu_two")
      w.undo()
      self.assertEqual(sp.exit_of(p.plan.data)["call"], "close_now")
      self.assertFalse(p.set_exit("leave"))   # refused: no such call
      self.close(w, [w.document] + w.extra_documents())

   def test_interactions_panel(self) -> None:
      """!A rule from the form added after the chosen one, moved, changed, removed, undone; the verdict.
      @return None
      """
      from capsule_studio.ui.editors.world_interactions import ANY, InteractionsPanel
      from capsule_studio.ui.world_shell import WorldWindow
      for name in INTERACTION_FIXTURES:
         shutil.copytree(engine.root() / "tests" / "data" / name, self.root / name)
      w = WorldWindow([InteractionsPanel], str(self.root / INTERACTION_FIXTURES[0] / "world.json"), STUDIO_HOSTS,
                      "World")
      w.show()
      self.settle()
      p = w.panels[0]
      world = p.world()
      self.assertEqual(p.table.rowCount(), FIXTURE_RULES)
      self.assertIn("the map compiler takes them", p.problems.text())
      self.assertIn("pc", [p.behavior.itemText(i) for i in range(p.behavior.count())])
      self.assertIn("use_pc", [p.script.itemText(i) for i in range(p.script.count())])
      p.table.selectRow(1)
      self.assertEqual((p.behavior.currentText(), p.facing.currentText()), ("screen", "up"))
      p.behavior.setCurrentText("shelf")
      p.script.setCurrentText("read")
      p.facing.setCurrentText("left")
      p.same_level.setChecked(True)
      self.assertTrue(p.add_rule())
      self.assertEqual(interactions.rules(world)[2], {"behavior": "shelf", "script": "read", "facing": "left",
                                                      "same_level": True})
      self.assertEqual(p.table.currentRow(), 2)
      self.assertTrue(p.move_rule(-1))
      self.assertEqual(interactions.rules(world)[1]["facing"], "left")
      p.facing.setCurrentText(ANY)
      self.assertTrue(p.apply_rule())
      self.assertNotIn("facing", interactions.rules(world)[1])
      p.script.setCurrentText("no_such_script")
      self.assertTrue(p.apply_rule())
      self.assertIn("unknown script 'no_such_script'", p.problems.text())
      w.undo()
      self.assertEqual(interactions.rules(world)[1]["script"], "read")
      self.assertTrue(p.remove_rule())
      self.assertEqual(len(interactions.rules(world)), FIXTURE_RULES)
      p.behavior.setCurrentText("nothing")
      self.assertNotEqual(p.behavior.currentText(), "nothing")   # a picker: only the world's behaviors
      p.script.setCurrentText("")
      self.assertFalse(p.add_rule())   # refused: a rule names its script
      self.close(w, [world])


if __name__ == "__main__":
   unittest.main()
