#!/usr/bin/env python3
"""!Smoke test of the script editor's Qt layer: the window on the script test
app's data, live checks, problems, outline jumps, Declare / Rename and saving.
Skipped when PySide6 is missing (the other tests need no Qt); run it in the
toolkit environment. Uses Qt's offscreen platform, so it needs no display.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core import engine  # noqa: E402

if TYPE_CHECKING:
   from capsule_studio.ui.script_shell import ScriptWindow


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtScriptTests(unittest.TestCase):
   """!Builds the window on a copy of the test app's scripts."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies apps/test_script/data and isolates the recent-files settings.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_scripts_"))
      shutil.copytree(engine.root() / "apps" / "test_script" / "data", self.root / "data")
      ## The copy's scripts.json.
      self.manifest = self.root / "data" / "scripts.json"
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events.
      @return None
      """
      for _ in range(3):
         self.app.processEvents()

   def window(self) -> ScriptWindow:
      """!The editor on the copy.
      @return ScriptWindow
      """
      from capsule_studio.ui.script_shell import ScriptWindow
      w = ScriptWindow(str(self.manifest))
      w.launch()
      self.settle()
      return w

   def test_open_check_and_outline(self) -> None:
      """!Opens with one tab, compiles, fills the outline and jumps to a declaration.
      @return None
      """
      w = self.window()
      self.assertEqual(w.tabs.count(), 1)
      self.assertTrue(w.result.ok, w.summary.text())
      self.assertEqual(w.problems.topLevelItemCount(), 0)
      groups = {w.outline.topLevelItem(i).text(0): w.outline.topLevelItem(i)
                for i in range(w.outline.topLevelItemCount())}
      flags = groups["Flags"]
      names = [flags.child(i).text(0) for i in range(flags.childCount())]
      self.assertIn("met_guide", names)
      item = flags.child(names.index("met_guide"))
      w._jump_to_item(item)
      ed = w.editors["demo.cscript"]
      self.assertIn("met_guide", ed.textCursor().block().text())
      self.assertFalse(w.save_action.isEnabled())
      w.project.manifest_dirty = False
      w.close()

   def test_error_marks_and_save(self) -> None:
      """!Typing an error shows it in the problems list and the editor; fixing and saving clears it.
      @return None
      """
      w = self.window()
      ed = w.editors["demo.cscript"]
      cur = ed.textCursor()
      cur.movePosition(QtGui.QTextCursor.MoveOperation.End)
      cur.insertText("\nscript bad {\n    set flag(nope);\n}\n")
      self.assertTrue(w.project.dirty)
      self.assertTrue(w.tabs.tabText(0).endswith("*"))
      w.recheck.flush()
      self.assertFalse(w.result.ok)
      self.assertGreater(w.problems.topLevelItemCount(), 0)
      self.assertTrue(ed.marks)
      self.assertTrue(ed.extraSelections())
      w._jump_to_problem(w.problems.topLevelItem(0))
      self.assertIn("nope", ed.textCursor().block().text())
      ed.undo()
      w.recheck.flush()
      self.assertTrue(w.result.ok)
      self.assertEqual(w.problems.topLevelItemCount(), 0)
      cur = ed.textCursor()
      cur.movePosition(QtGui.QTextCursor.MoveOperation.End)
      cur.insertText("// edited\n")
      self.assertTrue(w.save_action.isEnabled())
      self.assertTrue(w.save_current())
      self.assertIn("// edited", (self.root / "data" / "demo.cscript").read_text())
      self.assertFalse(w.project.dirty)
      w.close()

   def test_declare_rename_settings(self) -> None:
      """!Declare and rename go into the editor as undoable steps; a setting change rechecks.
      @return None
      """
      w = self.window()
      ed = w.editors["demo.cscript"]
      line = w.project.declare("demo.cscript", "var", "strides", "daily", "u16", 0, 9)
      w._sync_editors("demo.cscript")
      self.assertIn(line, ed.toPlainText())
      n = w.project.rename("strides", "paces")
      w._sync_editors()
      self.assertEqual(n, 1)
      self.assertIn("var paces", ed.toPlainText())
      ed.undo()
      self.assertIn("var strides", ed.toPlainText())
      w.depth.setValue(1)
      self.assertEqual(w.project.setting("stack_depth"), 1)
      self.assertTrue(w.project.manifest_dirty)
      w.depth.setValue(8)
      w.recheck.flush()
      self.assertTrue(w.result.ok, w.summary.text())
      w.project.manifest_dirty = False
      w.project.saved = dict(w.project.texts)
      w.close()

   def test_start_page_without_file(self) -> None:
      """!Without a file the start page shows; continuing opens the empty editor.
      @return None
      """
      from capsule_studio.ui.script_shell import ScriptWindow
      w = ScriptWindow()
      w.launch()
      self.settle()
      self.assertTrue(w.start.isVisible())
      w.show_editor()
      self.assertFalse(w.check_action.isEnabled())
      self.assertIsNone(w.check())
      w.close()

   def test_highlighter_block_comments(self) -> None:
      """!Block comments spanning lines keep their state.
      @return None
      """
      from capsule_studio.ui.editors.script import CodeEditor
      ed = CodeEditor()
      ed.setPlainText("flag a; /* one\ntwo\nthree */ flag b;\n/* x */ flag c; /* y\n*/")
      doc = ed.document()
      self.settle()
      states = [doc.findBlockByNumber(i).userState() for i in range(doc.blockCount())]
      self.assertEqual(states, [1, 1, 0, 1, 0])


if __name__ == "__main__":
   unittest.main()
