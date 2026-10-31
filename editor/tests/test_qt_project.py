#!/usr/bin/env python3
"""!Smoke test of the project settings window and its build settings panel.
Skipped when PySide6 is missing; uses Qt's offscreen platform.
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
   QtWidgets = None

from capsule_studio.core import engine  # noqa: E402


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtProjectTests(unittest.TestCase):
   """!Builds the window on a copy of test_vram's project.json."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies the manifest and isolates the recent-files settings.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_project_"))
      (self.root / "reference").mkdir()
      ## The copy's project.json.
      self.manifest = self.root / "reference" / "project.json"
      shutil.copy(engine.root() / "apps" / "test_vram" / "reference" / "project.json", self.manifest)
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_panel_edits(self) -> None:
      """!Checkboxes, values and WAITCNT fields edit the manifest with undo; save writes it.
      @return None
      """
      from capsule_studio.ui.project_shell import ProjectWindow
      w = ProjectWindow(str(self.manifest))
      w.launch()
      self.app.processEvents()
      panel = w.panels[0]
      use, value = panel.rows["vram_streaming_slots"]
      self.assertTrue(use.isChecked())
      value.stepBy(1)                       # doubles, and commits at once
      self.assertEqual(value.value(), 128)
      self.assertEqual(w.document.data["build"]["vram_streaming_slots"], 128)
      self.assertTrue(w.save_action.isEnabled())
      use.setChecked(False)                 # back to the default
      self.assertNotIn("vram_streaming_slots", w.document.data["build"])
      use.setChecked(True)                  # ticking again restores the value it had
      self.assertEqual(w.document.data["build"]["vram_streaming_slots"], 128)
      use.setChecked(False)
      combo = panel.fields["ws0_first"]
      combo.setCurrentIndex(combo.findData(4))
      self.assertEqual(w.document.data["build"]["gba_waitcnt"], "0x4010")
      self.assertIn("4/1", panel.problems.text())
      w._undo_redo(True)
      self.assertEqual(w.document.data["build"]["gba_waitcnt"], "0x4014")
      self.assertEqual(panel.fields["ws0_first"].currentData(), 3)
      _, hexbox = panel.rows["gba_waitcnt"]
      hexbox.setText("0x8000")              # rejected: a message, widgets put back
      QtCore.QTimer.singleShot(0, lambda: [b.close() for b in QtWidgets.QApplication.topLevelWidgets()
                                            if isinstance(b, QtWidgets.QMessageBox)])
      hexbox.editingFinished.emit()
      self.assertEqual(hexbox.text(), "0x4014")
      self.assertTrue(w.save())
      self.assertNotIn("vram_streaming_slots", self.manifest.read_text())
      w.close()

   def test_invalid_manifest_value(self) -> None:
      """!A value the build rejects is marked; the other rows keep their values.
      @return None
      """
      import json
      from capsule_studio.ui.project_shell import ProjectWindow
      data = json.loads(self.manifest.read_text())
      data["build"]["vram_must_land_slots"] = 48
      self.manifest.write_text(json.dumps(data))
      w = ProjectWindow(str(self.manifest))
      w.launch()
      self.app.processEvents()
      panel = w.panels[0]
      use, value = panel.rows["vram_budget_cycles"]
      self.assertTrue(use.isChecked())
      self.assertEqual(value.value(), 67392)
      self.assertIn("power of two", panel.rows["vram_must_land_slots"][0].toolTip())
      self.assertFalse(w.document.dirty)
      panel.rows["vram_must_land_slots"][1].setValue(64)
      self.assertEqual(w.document.data["build"]["vram_must_land_slots"], 64)
      w.document.dirty = False
      w.close()

   def test_start_page(self) -> None:
      """!Without a file the start page shows.
      @return None
      """
      from capsule_studio.ui.project_shell import ProjectWindow
      w = ProjectWindow()
      w.launch()
      self.app.processEvents()
      self.assertTrue(w.start.isVisible())
      w.show_editor()
      from capsule_studio.ui.widgets import is_enabled
      # [RZ] greyed through its contents (set_enabled()): the panel holds a fit area, whose scroll bars stay on
      self.assertFalse(is_enabled(w.panels[0]))
      w.close()


if __name__ == "__main__":
   unittest.main()
