#!/usr/bin/env python3
"""!The Extensions view (ui/editors/vm_ext.py) in the asset editor, offscreen: the engine sandbox's sample
(progress, the op list and its filters, an op's details, the checks, the report on the clipboard), and a refused
manifest (the status bar says why). A shot of the panel goes to $VM_EXT_SHOTS when it is set. Skipped when PySide6 is
missing or no engine checkout is found."""
from __future__ import annotations

import json
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

try:
   engine.root()
   HAVE_ENGINE = True
except engine.EngineNotFound:
   HAVE_ENGINE = False

## Times the event loop runs to settle.
SETTLE_ROUNDS = 4
## The shot's size.
SHOT_SIZE = (1280, 720)


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
@unittest.skipUnless(HAVE_ENGINE, "no engine checkout (set CAPSULE_ENGINE)")
class VmExtPanelTests(unittest.TestCase):
   """!The panel in one asset editor window."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication; settings in a temporary folder.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
      ## Temporary root.
      cls.root = Path(tempfile.mkdtemp(prefix="capsule_vm_ext_"))
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(cls.root / "settings"))

   @classmethod
   def tearDownClass(cls) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(cls.root, ignore_errors=True)

   def setUp(self) -> None:
      """!A window with the panel.
      @return None
      """
      from capsule_studio.ui.editors.vm_ext import VmExtPanel
      from capsule_studio.ui.shell import EditorWindow
      self.w = EditorWindow([VmExtPanel])
      self.w.resize(*SHOT_SIZE)
      self.w.show()
      self.settle()
      self.p = next(x for x in self.w.panels if x.panel_id == "vm_ext")

   def tearDown(self) -> None:
      """!Closes the window without questions.
      @return None
      """
      self.w.hide()
      self.w.deleteLater()
      self.settle()

   def settle(self) -> None:
      """!Runs pending events.
      @return None
      """
      for _ in range(SETTLE_ROUNDS):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def test_registered(self) -> None:
      """!The panel is in the asset editor's panels, after the battle animation tools.
      @return None
      """
      from capsule_studio.ui.editors import PANELS, by_id
      ids = [p.panel_id for p in PANELS]
      self.assertEqual(ids[ids.index("anim_scene") + 1], "vm_ext")
      self.assertIsNotNone(by_id("vm_ext"))

   def test_sample(self) -> None:
      """!The sample: progress, the list, the filters, an op, the checks, the report.
      @return None
      """
      self.p.open_sample()
      self.settle()
      self.assertEqual(self.p.progress.topLevelItemCount(), 1)
      self.assertEqual(self.p.progress.topLevelItem(0).text(2), "6 (75%)")
      self.assertEqual(self.p.ops.topLevelItemCount(), 8)
      self.assertIn("no errors", self.p.checks.toPlainText())
      self.p.kind_box.setCurrentText("Natives")
      self.p.fill()
      self.assertEqual(self.p.ops.topLevelItemCount(), 2)
      self.assertIn("Reason:", self.p.detail.toPlainText())
      self.p.kind_box.setCurrentText("All ops")
      self.p.search.setText("jumpif")
      self.settle()
      self.assertEqual(self.p.ops.topLevelItemCount(), 1)
      self.assertIn("jump_if width 1", self.p.detail.toPlainText())
      self.p.search.setText("")
      self.p.copy_report()
      self.assertIn("2 natives", QtWidgets.QApplication.clipboard().text())
      shots = os.environ.get("VM_EXT_SHOTS")
      if shots:
         self.w.grab().save(str(Path(shots) / "toolkit_extensions_sample.png"))

   def test_refused(self) -> None:
      """!A manifest the engine refuses leaves the view as it was and says why.
      @return None
      """
      bad = self.root / "bad.json"
      bad.write_text(json.dumps({"schema": "capsule.vm-ext/1", "vm": "battle", "ops": [
         {"id": 0, "name": "x", "kind": "native", "symbol": "cmd_x", "reason": ""}]}), encoding="utf-8")
      self.assertFalse(self.p.load([bad], [], None))
      self.assertIsNone(self.p.ext)


if __name__ == "__main__":
   unittest.main()
