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
## Step D: the engine's script natives sample.
SCRIPT_SAMPLE = Path("tests") / "data" / "vm_ext" / "script_natives_vm_ext.json"
## Whether the engine has it (an older pinned engine does not).
HAVE_SCRIPT_SAMPLE = HAVE_ENGINE and (engine.root() / SCRIPT_SAMPLE).is_file()

## Times the event loop runs to settle.
SETTLE_ROUNDS = 4
## The shot's size.
SHOT_SIZE = (1280, 720)
## The progress tree's aliases column (step D put the generic ops' column before it).
ALIASES_COLUMN = 3
## Step D: the script sample's natives, and the op list's implemented and milestone columns.
SCRIPT_SAMPLE_NATIVES = 3
## The columns.
IMPLEMENTED_COLUMN, MILESTONE_COLUMN = 9, 10


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
      self.assertEqual(self.p.progress.topLevelItem(0).text(ALIASES_COLUMN), "6 (75%)")
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

   @unittest.skipUnless(HAVE_SCRIPT_SAMPLE, "the engine has no script natives sample (D-36 step D)")
   def test_script_sample(self) -> None:
      """!Step D: the script VM's generic ops and the natives sample, their classes and columns; a game's folders.
      @return None
      """
      self.p.open_script_sample()
      self.settle()
      self.assertEqual(self.p.progress.topLevelItemCount(), 2)
      self.assertEqual(self.p.classes.topLevelItemCount(), SCRIPT_SAMPLE_NATIVES)
      self.assertIn("no errors", self.p.checks.toPlainText())
      self.p.kind_box.setCurrentText("Natives")
      self.p.fill()
      self.assertEqual(self.p.ops.topLevelItemCount(), SCRIPT_SAMPLE_NATIVES)
      first = self.p.ops.topLevelItem(0)
      self.assertEqual((first.text(IMPLEMENTED_COLUMN), first.text(MILESTONE_COLUMN)), ("yes", "M2"))
      self.assertIn("Implemented by the game: yes", self.p.detail.toPlainText())
      self.p.kind_box.setCurrentText("Generic ops")
      self.p.fill()
      self.assertGreater(self.p.ops.topLevelItemCount(), SCRIPT_SAMPLE_NATIVES)
      self.assertFalse(self.p.open_game_folders([self.root]))   # no natives manifest there
      shots = os.environ.get("VM_EXT_SHOTS")
      if shots:
         self.w.grab().save(str(Path(shots) / "toolkit_extensions_script.png"))

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
