#!/usr/bin/env python3
"""![S8] The battle animation panels (M5, D-38) in the asset editor, offscreen: the animation-script viewer and
stepper on the engine sandbox's sample (frames, the timeline, lifetimes), the affine animation editor (edits with
undo, a refused value, Save as, the C++ export, the preview), the scanline-effect preview (registers, sources,
problems) and the scene viewer (a stand-in for the engine's capsule_anim_view). Skipped when PySide6 is missing."""
from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core import engine  # noqa: E402
from test_anim_formats import FAKE_VIEWER  # noqa: E402

try:
   engine.root()
   HAVE_ENGINE = True
except engine.EngineNotFound:
   HAVE_ENGINE = False

## Times the event loop runs to settle.
SETTLE_ROUNDS = 4


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
@unittest.skipUnless(HAVE_ENGINE, "no engine checkout (set CAPSULE_ENGINE)")
class AnimPanelTests(unittest.TestCase):
   """!The four panels in one asset editor window."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication; settings in a temporary folder.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
      ## Temporary root.
      cls.root = Path(tempfile.mkdtemp(prefix="capsule_anim_"))
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(cls.root / "settings"))

   @classmethod
   def tearDownClass(cls) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(cls.root, ignore_errors=True)

   def setUp(self) -> None:
      """!A window with the four panels.
      @return None
      """
      from capsule_studio.ui.editors.anim_affine import AffineAnimPanel
      from capsule_studio.ui.editors.anim_scanline import ScanlinePanel
      from capsule_studio.ui.editors.anim_scene import SceneViewerPanel
      from capsule_studio.ui.editors.anim_script import AnimScriptPanel
      from capsule_studio.ui.shell import EditorWindow
      self.w = EditorWindow([AnimScriptPanel, AffineAnimPanel, ScanlinePanel, SceneViewerPanel])
      self.w.show()
      self.settle()

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

   def panel(self, panel_id: str) -> QtWidgets.QWidget:
      """!Brings a panel to the front.
      @param panel_id  its id
      @return the panel
      """
      p = next(x for x in self.w.panels if x.panel_id == panel_id)
      self.w.tabs.setCurrentWidget(p)
      self.settle()
      return p

   def test_registered(self) -> None:
      """!The four panels are in the asset editor's panels, after the sprite animations.
      @return None
      """
      from capsule_studio.ui.editors import PANELS, by_id
      ids = [p.panel_id for p in PANELS]
      self.assertEqual(ids[ids.index("animation") + 1:ids.index("animation") + 5],
                       ["anim_script", "anim_affine", "anim_scanline", "anim_scene"])
      self.assertIsNotNone(by_id("anim_scene"))

   def test_script_stepper(self) -> None:
      """!The sample runs to its end; a frame shows the commands run and the player's state; the timeline's click
      picks a frame; a lifetime edit runs the script again; a bad bank is refused.
      @return None
      """
      from capsule_studio.ui.editors import anim_script as ui
      p = self.panel("anim_script")
      self.assertEqual(p.scripts.count(), 1)
      self.assertEqual(p.stepper.states[-1].frame, 104)
      p.frame_bar.set_frame(4)
      self.settle()
      self.assertEqual(p.state_labels["counts"].text(), "3 / 0")
      ran = [r for r in range(p.listing.rowCount())
             if p.listing.item(r, ui.COMMAND_COLUMN).background().color() == ui.RAN_COLOR]
      self.assertEqual([p.listing.item(r, ui.COMMAND_COLUMN).text() for r in ran],
                       ["create_sprite", "create_sprite", "create_task", "set_blend", "delay"])
      self.assertIn("wait mode", p.state_labels["mode"].text())
      # a click on the timeline at frame 30
      x = ui.LABEL_WIDTH + 30 * ui.FRAME_WIDTH + 1
      press = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, QtCore.QPointF(x, ui.RULER_HEIGHT),
                                QtCore.QPointF(x, ui.RULER_HEIGHT), QtCore.Qt.MouseButton.LeftButton,
                                QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
      QtWidgets.QApplication.sendEvent(p.timeline, press)
      self.settle()
      self.assertEqual(p.frame_bar.frame(), 30)
      self.assertTrue(p.listing.item(p._rows[0x3B], ui.LABEL_COLUMN).text().startswith(ui.NEXT_MARK))
      p.set_lifetime("ball", 10)
      self.assertEqual(next(v for v in p.stepper.visuals if v.name == "ball").finished, 14)
      p.life_table.item(0, ui.ARG_COLUMN).setText("9")   # refused: the slots are 0 to 7
      self.settle()
      self.assertEqual(p.lifetimes["ball"].from_arg, None)
      self.assertFalse(p.open_bank(str(self.root / "missing.canim")))
      self.assertEqual(p.bank_path.name, "shapes.canim")

   def test_affine_editor(self) -> None:
      """!The sample's animations; adding a command is one undo step; a value its field cannot hold is refused;
      Save as names the file (saved with the manifest from then on); the export writes the C++.
      @return None
      """
      p = self.panel("anim_affine")
      self.assertEqual([p.anims.item(i).text() for i in range(p.anims.count())], ["spin", "pulse", "squash"])
      self.assertEqual(p.extra_documents(), [])   # not named yet
      p.anims.setCurrentRow(0)
      self.settle()
      self.assertEqual(p.cmds.rowCount(), 2)
      self.assertEqual(p.steps[2].rotation, 0xC00)   # spin: 4 steps a frame
      p.cmds.setCurrentCell(0, 1)
      self.assertTrue(p.add_cmd("frame"))
      self.assertEqual(p.cmds.rowCount(), 3)
      self.assertEqual(self.w.active_document(), p.affine)
      self.w.undo()
      self.settle()
      self.assertEqual(p.cmds.rowCount(), 2)
      self.assertFalse(p.set_field(0, "rotation", 300))   # a signed byte
      self.assertEqual(p.affine.data["anims"][0]["cmds"][0]["rotation"], 4)
      p.cmds.item(0, 3).setText("-2")                     # the rotation cell
      self.settle()
      self.assertEqual(p.affine.data["anims"][0]["cmds"][0]["rotation"], -2)
      self.assertTrue(p.add_anim())
      self.assertEqual(p.anim()["name"], "anim")
      self.assertTrue(p.rename("wobble"))
      self.assertIn("wobble", [p.anims.item(i).text() for i in range(p.anims.count())])
      path = self.root / "shapes.affine.json"
      self.assertTrue(p.save_as(str(path)))
      self.assertEqual(p.extra_documents(), [p.affine])
      header = self.root / "out" / "affine.h"
      self.assertTrue(p.export(str(header)))
      text = header.read_text(encoding="utf-8")
      self.assertIn("from ../shapes.affine.json", text)   # relative, posix
      self.assertIn("kWobbleAffine", text)
      self.assertTrue(p.open_file(str(path)))
      self.assertEqual(p.affine.path, path.resolve())
      p.step_bar.set_frame(3)
      self.settle()
      self.assertIsNotNone(p.view.image)

   def test_scanline_preview(self) -> None:
      """!Each register with its usual table; a frame's table and meaning; settings that make no table.
      @return None
      """
      from capsule_studio.core import anim_scanline as core
      from capsule_studio.ui.editors import anim_scanline as ui
      p = self.panel("anim_scanline")
      self.assertIsNotNone(p.view.image)
      p.set_effect("win0_h")
      self.assertEqual(p.effect.source, "diamond")
      p.frame_bar.set_frame(5)
      self.settle()
      cy = core.SCREEN_HEIGHT // core.HALF
      self.assertTrue(p.table.item(cy, ui.MEANING_COLUMN).text().startswith("x "))
      p.set_effect("blend")
      self.assertEqual(p.effect.source, "ramp")
      self.assertIn("eva", p.table.item(0, ui.MEANING_COLUMN).text())
      p.set_effect("bg_x", "wave", start_line=100, end_line=50)   # the engine asserts start <= end
      self.assertEqual(p.tables, [])
      self.assertIn("start <= end", p.problems.text())
      self.assertIsNone(p.view.image)

   @unittest.skipIf(os.name == "nt", "the stand-in viewer is a script with a #! line")
   def test_scene_viewer(self) -> None:
      """!A viewer program: frames shown in front only, the scene list jumps, the check, a bad path refused.
      @return None
      """
      from capsule_studio.core import anim_scene as core
      prog = self.root / core.VIEWER_NAME
      prog.write_text(FAKE_VIEWER.format(python=sys.executable), encoding="utf-8")
      prog.chmod(prog.stat().st_mode | stat.S_IXUSR)
      p = next(x for x in self.w.panels if x.panel_id == "anim_scene")
      self.assertTrue(p.set_viewer(str(prog)))
      self.assertEqual(p.viewer.frames, {})   # not in front: nothing read
      self.panel("anim_scene")
      self.assertIsNotNone(p.view.image)
      p.scenes.setCurrentRow(2)
      self.settle()
      self.assertEqual(p.frame_bar.frame(), core.scenes()[2].first)
      self.assertIn("blend", p.where.text())
      self.assertTrue(p.check())
      self.assertTrue(p.check_label.text().startswith("Passed"))
      self.assertFalse(p.set_viewer(str(self.root / "missing")))
      self.assertEqual(QtCore.QSettings().value("anim_scene/viewer"), str(prog))


if __name__ == "__main__":
   unittest.main()
