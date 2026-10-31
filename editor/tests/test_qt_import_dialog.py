#!/usr/bin/env python3
"""!Smoke test of the image Import dialog (ui/editors/import_dialog.py): changing the transparency mode and
the frame duration updates the dialog, and the color button opens the chooser.
Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtGui, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core import imaging, sprites  # noqa: E402


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtImportDialogTests(unittest.TestCase):
   """!The dialog's controls follow each other."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def test_changes_update_the_dialog(self) -> None:
      """!A new transparency mode or duration is shown at once (no TypeError from the signal).
      @return None
      """
      from capsule_studio.ui.editors.import_dialog import ImportDialog
      dlg = ImportDialog((16, 16), 2, True, "sprite:X")
      errors: list[BaseException] = []
      old_hook = sys.excepthook
      sys.excepthook = lambda kind, value, tb: errors.append(value)   # exceptions raised in slots land here
      try:
         dlg.duration.setValue(30)
         self.app.processEvents()
         self.assertEqual(dlg.ms.text(), f"= {sprites.frames_to_ms(30)} ms")
         dlg.transparency.setCurrentIndex(imaging.TRANSPARENCY_MODES.index("color"))
         self.app.processEvents()
         self.assertTrue(dlg.color_button.isEnabled())
      finally:
         sys.excepthook = old_hook
      self.assertEqual(errors, [])
      dlg.deleteLater()

   def test_color_button_picks_a_color(self) -> None:
      """!Clicking the color button asks for a color and keeps the answer (clicked() passes 'checked').
      @return None
      """
      from unittest import mock
      from capsule_studio.ui.editors.import_dialog import ImportDialog
      dlg = ImportDialog((16, 16), 2, True, "sprite:X")
      dlg.transparency.setCurrentIndex(imaging.TRANSPARENCY_MODES.index("color"))
      errors: list[BaseException] = []
      old_hook = sys.excepthook
      sys.excepthook = lambda kind, value, tb: errors.append(value)
      try:
         with mock.patch.object(QtWidgets.QColorDialog, "getColor", return_value=QtGui.QColor(10, 20, 30)):
            dlg.color_button.click()
            self.app.processEvents()
      finally:
         sys.excepthook = old_hook
      self.assertEqual(errors, [])
      self.assertEqual(dlg.color, (10, 20, 30))
      dlg.deleteLater()


if __name__ == "__main__":
   unittest.main()
