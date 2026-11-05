#!/usr/bin/env python3
"""!Smoke test of the Studio's Build and Build and Debug buttons (ui/build_bar.py): their drop-downs, the choices
remembered per game, saving every page first, and a build whose steps run through QProcess into the Build log.
The steps are small Python programs (no CMake). Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core import game_build  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402

## How long a test build may take, milliseconds.
BUILD_WAIT_MS = 20000


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtBuildTests(unittest.TestCase):
   """!The Studio on a copy of the map sandbox game."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies the game; settings go to the temporary folder.
      @return None
      """
      ## Temporary apps folder.
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_qt_build_")), ["sandbox_map"],
                                   ("data", "reference"))
      ## The game's project manifest.
      self.manifest = self.root / "sandbox_map" / "reference" / "project.json"
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root.parent, ignore_errors=True)

   def fake_plans(self, fail: bool = False) -> object:
      """!A stand-in for game_build.plans: one plan whose steps print and whose run step prints.
      @param fail  True to make the build step fail
      @return the function
      """
      out = self.root / "out"
      out.mkdir(exist_ok=True)

      def plans(path: Path, ids: list[str] | None, debug: bool = False, run: bool = False,
                command: list[str] | None = None) -> list[game_build.BuildPlan]:
         """!The fake plans.
         @return plans
         """
         t = game_build.target(ids[0] if ids else "desktop")
         (out / ("capsule_demo" + t.output_suffix)).write_text("", encoding="utf-8")
         code = "raise SystemExit(2)" if fail else "print('compiled ok')"
         steps = [game_build.Step("Configuring", [sys.executable, "-c", "print('configured', end='')"], out),
                  game_build.Step("Building", [sys.executable, "-c", code], out)]
         plan = game_build.BuildPlan(t, t.preset(debug), Path(path), "demo", out, steps, [])
         if run:
            plan.run = game_build.Step("Starting", [sys.executable, "-c", "print('game running')", "x"], out)
         return [plan]
      return plans

   def wait(self, bar: object) -> bool:
      """!Waits for the build to finish.
      @param bar  the BuildBar
      @return whether it succeeded
      """
      result: list[bool] = []
      loop = QtCore.QEventLoop()
      bar.finished.connect(lambda ok: (result.append(ok), loop.quit()))
      QtCore.QTimer.singleShot(BUILD_WAIT_MS, loop.quit)
      if bar.busy():
         loop.exec()
      return bool(result and result[0])

   def test_buttons_choices_and_build(self) -> None:
      """!Drop-downs list this computer's targets; choices are remembered per game; a build saves, logs and runs.
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      w = StudioWindow()
      bar = w.build_bar
      self.assertFalse(bar.build_action.isEnabled())   # no game yet
      self.assertTrue(w.open_game(self.manifest))
      w.show()
      self.assertTrue(bar.build_action.isEnabled())
      titles = [a.text() for a in bar.build_menu.actions() if a.isCheckable()]
      self.assertEqual(titles[0], game_build.host_target().title)
      self.assertIn("All targets", titles)
      self.assertNotIn("All targets", [a.text() for a in bar.debug_menu.actions()])
      self.assertEqual(bar.build_button.popupMode(), QtWidgets.QToolButton.ToolButtonPopupMode.MenuButtonPopup)
      self.assertIn("&Build", [a.text() for a in w.menuBar().actions()])
      self.assertEqual(w.menuBar().actions()[-1], w.help_action)
      # Choices are the game's.
      bar.build_choices["gba"].trigger()
      bar.debug_choices["gba"].trigger()
      bar.debug_preset_action.setChecked(True)
      bar.choose(game_build.host_target().target_id, True)
      bar.choose("gba", True)
      bar.build_choice = bar.debug_choice = "desktop"
      bar.game_changed()
      self.assertEqual((bar.build_choice, bar.debug_choice, bar.build_debug), ("gba", "gba", True))
      # Every page with changes is saved first; a page that cannot be saved stops the build.
      with mock.patch.object(w, "save_all_pages", return_value=False) as save:
         self.assertFalse(bar.build())
         save.assert_called_once()
      # Build: the steps' output in the log.
      with mock.patch.object(game_build, "plans", self.fake_plans()):
         self.assertTrue(bar.build())
         self.assertFalse(bar.build_action.isEnabled())   # while it builds
         self.assertTrue(self.wait(bar))
      lines = bar.log.lines()
      self.assertIn("configured", lines)
      self.assertIn("compiled ok", lines)
      self.assertEqual(lines[-1], "==== Done")
      self.assertTrue(bar.build_action.isEnabled())
      # Build and Debug: the game runs after the build.
      with mock.patch.object(game_build, "plans", self.fake_plans()):
         self.assertTrue(bar.build_and_debug())
         self.assertTrue(self.wait(bar))
      self.assertIn("game running", bar.log.lines())
      # A failing step stops the build.
      with mock.patch.object(game_build, "plans", self.fake_plans(fail=True)):
         self.assertTrue(bar.build())
         self.assertFalse(self.wait(bar))
      self.assertTrue(bar.log.lines()[-1].startswith("==== Failed"))
      # Emulators chosen in the drop-down are remembered; a Windows program runs in Wine off Windows.
      bar.set_emulator(game_build.RUN_GBA, "/x/NO$GBA.EXE")
      expected = ["/x/NO$GBA.EXE"] if sys.platform == "win32" else ["wine", "/x/NO$GBA.EXE"]
      self.assertEqual(bar.emulator(game_build.RUN_GBA), expected)
      bar.set_emulator(game_build.RUN_GBA, None)
      self.assertIsNone(bar.emulator(game_build.RUN_GBA))
      w.close()

   def test_missing_toolchain_builds_nothing(self) -> None:
      """!With the toolchain missing, nothing runs and the log says what is missing.
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      w = StudioWindow(str(self.manifest))
      bar = w.build_bar
      with mock.patch.object(game_build, "build_problems", return_value=["devkitARM"]):
         bar.choose("gba", True)
         self.assertFalse(bar.build())
      self.assertFalse(bar.busy())
      self.assertTrue(any("missing devkitARM" in line for line in bar.log.lines()))
      w.close()


if __name__ == "__main__":
   unittest.main()
