#!/usr/bin/env python3
"""!D-36 package 3 step 3C: the project settings window's Build usage panel (ui/editors/build_usage.py), offscreen,
on the sample build folder and project of test_exclusion.py: the folder found beside the game, the tables (bytes,
the boxes offered where the build suggests), the last check's findings, "Exclude all suggested" and Save (the manifest
written and named in the project). A shot of the window goes to $CAPSULE_SHOTS when it is set. Skipped when PySide6
is missing or the engine has no exclusion manifest."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # test_exclusion, a sibling
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core import exclusion, gba_memory  # noqa: E402
import test_exclusion as sample_build  # noqa: E402   (a module, so its tests are not collected here again)

## Where the screenshots go when CAPSULE_SHOTS names a folder.
SHOTS_ENV = "CAPSULE_SHOTS"
## Times the event loop runs to settle.
SETTLE_ROUNDS = 3
## The window's size.
WINDOW_SIZE = (1100, 720)


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
@unittest.skipIf(sample_build.have_tools() is not None, f"{sample_build.have_tools()}")
class BuildUsagePanelTests(unittest.TestCase):
   """!The panel in one project settings window."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!test_exclusion's build folder and project; a CMake cache so the folder is found; settings in the copy.
      @return None
      """
      ## The sample (its setUp makes the folders).
      self.sample = sample_build.ExclusionTests()
      self.sample.setUp()
      self.build = self.sample.build
      (self.build / gba_memory.CACHE_FILE).write_text("CMAKE_BUILD_TYPE:STRING=Release\n", encoding="utf-8")
      # the game's folder holds the build folder, as a game built beside its sources does
      self.game = self.sample.project_file.parent.parent
      moved = self.game / self.build.name
      shutil.move(str(self.build), str(moved))
      self.build = moved
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(Path(tempfile.mkdtemp(prefix="capsule_qt_usage_settings_"))))

   def tearDown(self) -> None:
      """!Removes the sample.
      @return None
      """
      self.sample.tearDown()

   def settle(self) -> None:
      """!Runs pending events.
      @return None
      """
      for _ in range(SETTLE_ROUNDS):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def test_panel(self) -> None:
      """!The tables and findings; Exclude all suggested, then Save.
      @return None
      """
      from capsule_studio.ui.project_shell import ProjectWindow
      w = ProjectWindow(str(self.sample.project_file))
      w.resize(*WINDOW_SIZE)
      w.show()
      self.settle()
      panel = {p.panel_id: p for p in w.panels}["build_usage"]
      self.assertEqual(panel.build_folder(), self.build)   # found beside the game
      self.assertIsNotNone(panel.usage)
      self.assertIn("The last build's check", panel.notes.text())
      names = [panel.modules.item(r, 0).text() for r in range(panel.modules.rowCount())]
      seq = names.index("seq")
      self.assertEqual(panel.modules.item(seq, 3).text(), str(sample_build.SEQ_BYTES))
      box = panel.modules.item(seq, 4)
      self.assertTrue(box.flags() & QtCore.Qt.ItemFlag.ItemIsEnabled)
      self.assertEqual(box.checkState(), QtCore.Qt.CheckState.Unchecked)
      self.assertTrue(panel.take_suggestion())
      modules, ops = panel.chosen()
      self.assertIn("seq", modules)
      self.assertNotIn("Message", ops)   # emitted by the scripts: its box cannot be ticked
      self.assertIn("Shop", ops)
      self.assertTrue(panel.save())
      self.assertEqual(w.document.data[exclusion.EXCLUDE_KEY], exclusion.DEFAULT_MANIFEST)
      saved = exclusion.read_manifest(w.document)
      self.assertEqual(exclusion.names(saved, exclusion.MODULES), modules)
      self.assertEqual(panel.modules.item(seq, 4).checkState(), QtCore.Qt.CheckState.Checked)
      panel.clear_choices()
      self.assertEqual(panel.chosen(), ([], []))
      w.tabs.setCurrentWidget(panel)
      folder = os.environ.get(SHOTS_ENV)
      if folder:
         w.grab().save(str(Path(folder) / f"build_usage_{sample_build.GAME}.png"))
      w.document.save()   # the project now names the manifest; saved, so closing asks nothing
      w.close()


if __name__ == "__main__":
   unittest.main()
