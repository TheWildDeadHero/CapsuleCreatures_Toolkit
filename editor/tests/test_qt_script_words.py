#!/usr/bin/env python3
"""!The script editor with the script port statements [the older studio] (Qt, offscreen; skipped without PySide6): the
outline's movements, marts and route steps, the map triggers with conditions, the completion list by context, Insert
statement, the script port settings, and the colours of the engine's words. Uses test_script_words.py's neutral source.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))   # the sibling test helpers (V2 finding)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from test_script_words import SOURCE  # noqa: E402


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class ScriptWordsQtTests(unittest.TestCase):
   """!The window on the neutral script port source."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Writes the scripts and opens the window (recent files kept out of the user's settings).
      @return None
      """
      from capsule_studio.ui.script_shell import ScriptWindow
      ## Temporary folder.
      self.tmp = Path(tempfile.mkdtemp(prefix="capsule_qt_port_scripts_"))
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.tmp / "settings"))
      (self.tmp / "main.cscript").write_text(SOURCE, encoding="utf-8")
      ## The manifest.
      self.manifest = self.tmp / "scripts.json"
      self.manifest.write_text(json.dumps({"schema": "capsule.scripts/1", "sources": ["main.cscript"],
                                           "stack_depth": 4, "glitches": {"g.one": True}}), encoding="utf-8")
      ## The window.
      self.w = ScriptWindow(self.manifest)
      self.app.processEvents()

   def tearDown(self) -> None:
      """!Closes the window and removes the folder.
      @return None
      """
      if self.w.project is not None:
         self.w.project.texts = dict(self.w.project.saved)
         self.w.project.manifest_dirty = False
      self.w.close()
      shutil.rmtree(self.tmp, ignore_errors=True)

   def editor_at_end(self, extra: str) -> object:
      """!The source's editor with text typed at its end.
      @param extra  the text
      @return CodeEditor
      """
      ed = self.w.editors["main.cscript"]
      self.w.tabs.setCurrentWidget(ed)
      cur = ed.textCursor()
      cur.movePosition(QtGui.QTextCursor.MoveOperation.End)
      ed.setTextCursor(cur)
      ed.insertPlainText(extra)
      return ed

   def test_outline(self) -> None:
      """!Movements, marts, route steps; the map's triggers with their condition.
      @return None
      """
      groups = {self.w.outline.topLevelItem(i).text(0): self.w.outline.topLevelItem(i)
                for i in range(self.w.outline.topLevelItemCount())}
      for heading in ("Movements", "Marts", "Route steps"):
         self.assertEqual(groups[heading].childCount(), 1, heading)
      self.assertIn("on_warp_into var(mode) == 0 -> arrive", groups["Maps"].child(0).text(1))

   def test_completion(self) -> None:
      """!The list opens with the words that fit; choosing one replaces the typed part.
      @return None
      """
      ed = self.editor_at_end("\nscript extra {\n    door ")
      self.assertTrue(ed.show_completions(forced=True))
      model = ed.completer.model()
      words = [model.index(i, 0).data() for i in range(model.rowCount())]
      self.assertEqual(words[:2], ["open", "close"])
      ed.insertPlainText("se")
      ed.insert_completion("set_open")
      self.assertTrue(ed.toPlainText().endswith("door set_open"))
      ed.completer.popup().hide()
      ed = self.editor_at_end(" 1 2;\n    route 1 { fa")
      self.assertIn("face", ed.completions())

   def test_insert_statement_and_settings(self) -> None:
      """!Insert statement writes a template that compiles; the script port settings write the manifest.
      @return None
      """
      ed = self.editor_at_end("\nscript inserted {\n    ")
      self.w.insert_statement("set_metatile")
      ed.insertPlainText("\n}\n")
      r = self.w.check()
      self.assertTrue(r.ok, [d.message for d in r.errors])
      self.assertIn("set_metatile 1 2 5 1;", ed.toPlainText())
      self.assertEqual(self.w.glitches.count(), 1)
      self.w.glitches.item(0).setCheckState(QtCore.Qt.CheckState.Unchecked)
      self.w.warn_unused.setChecked(False)
      self.assertEqual(self.w.project.setting("glitches"), {"g.one": False})
      self.assertIs(self.w.project.setting("warn_unused"), False)
      self.w.save_all()
      data = json.loads(self.manifest.read_text(encoding="utf-8"))
      self.assertEqual((data["glitches"], data["warn_unused"]), ({"g.one": False}, False))
      self.assertNotIn("object_base", data)

   def test_colours(self) -> None:
      """!An script port statement word and a trigger kind are coloured as keywords.
      @return None
      """
      from capsule_studio.ui.editors.script import engine_keywords
      words = engine_keywords()
      for w in ("set_metatile", "on_warp_into", "to_black", "in_place", "loose"):
         self.assertIn(w, words)


if __name__ == "__main__":
   unittest.main()
