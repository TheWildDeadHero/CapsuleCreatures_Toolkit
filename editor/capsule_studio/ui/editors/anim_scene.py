"""![S8] The engine sandbox's scene viewer (M5, D-38): the scene kit's scenes (affine animation, scanline effects,
palette blends, the animation-script player) as the engine draws them, frame by frame (core/anim_scene.py).

The pictures come from the engine's own viewer, capsule_anim_view (built with the engine's tests): Find looks in
the engine checkout's build folders and CAPSULE_ANIM_VIEW, Browse... picks it; the choice is remembered. Left: the
viewer, its check (two rounds of every scene, the sandbox's report) and the scenes (pick one to go to its first
frame). Middle: the frame and the frame bar (frame k is the picture after the k-th vertical blank, as on the GBA).
Frames are read from the viewer as they are shown, a run at a time, and kept.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import anim_scene as core
from ..panel import EditorPanel
from ..panes import NARROW, WIDE, pane, splitter
from ..widgets import PixelView, button
from .anim_common import PICTURE_ZOOM, FrameBar, rgb_qimage

if TYPE_CHECKING:
   from ..panel import PanelHost

## Settings key of the viewer's path.
VIEWER_KEY = "anim_scene/viewer"
## File dialog filter for the viewer.
VIEWER_FILTER = "Programs (capsule_anim_view*);;All files (*)"
## What the viewer may raise.
VIEWER_ERRORS = (core.ViewerError, OSError)
## Starting width of the left pane, pixels.
LEFT_WIDTH = 260


class SceneViewerPanel(EditorPanel):
   """!The scene viewer (see the module doc).

   @var viewer
   The core.Viewer, or None while no program is chosen.
   """

   ## See EditorPanel.panel_id.
   panel_id = "anim_scene"
   ## See EditorPanel.title.
   title = "Anim scenes"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel; the viewer remembered (or found) is used.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      self.viewer: core.Viewer | None = None
      ## True while the panel fills its own widgets.
      self._filling = False

      left = QtWidgets.QWidget()
      lv = QtWidgets.QVBoxLayout(left)
      lv.addWidget(QtWidgets.QLabel("The engine's viewer (capsule_anim_view):"))
      ## The viewer's path.
      self.path_edit = QtWidgets.QLineEdit()
      self.path_edit.setPlaceholderText("not found: Find or Browse...")
      self.path_edit.editingFinished.connect(lambda: self.set_viewer(self.path_edit.text()))
      lv.addWidget(self.path_edit)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Find", lambda: self.find(), "Looks in the engine's build folders and CAPSULE_ANIM_VIEW"))
      row.addWidget(button("Browse...", lambda: self.browse()))
      row.addWidget(button("Check", lambda: self.check(), "Two rounds of every scene; the sandbox's report"))
      lv.addLayout(row)
      ## The check's result.
      self.check_label = QtWidgets.QLabel()
      self.check_label.setWordWrap(True)
      lv.addWidget(self.check_label)
      ## The scenes.
      self.scenes = QtWidgets.QListWidget()
      self.scenes.currentRowChanged.connect(lambda r: self._scene_chosen(r))
      lv.addWidget(self.scenes, 1)

      middle = QtWidgets.QWidget()
      mv = QtWidgets.QVBoxLayout(middle)
      ## The frame.
      self.view = PixelView(PICTURE_ZOOM)
      mv.addWidget(self.view, 1)
      ## The scene and frame shown.
      self.where = QtWidgets.QLabel()
      mv.addWidget(self.where)
      ## The frame chooser (1 to one round and one more frame).
      self.frame_bar = FrameBar(lambda f: self.show_frame(f), 1, core.total_frames())
      mv.addWidget(self.frame_bar)

      lay = QtWidgets.QVBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(splitter(QtCore.Qt.Orientation.Horizontal, [pane(left), pane(middle)], [NARROW, WIDE],
                             [LEFT_WIDTH, None]))
      self._fill_scenes()
      saved = QtCore.QSettings().value(VIEWER_KEY, "")
      found = saved if saved and QtCore.QFileInfo(str(saved)).isFile() else core.find_viewer()
      if found:
         self.set_viewer(str(found), remember=False)
      else:
         self.where.setText("No viewer yet: build the engine's tests (capsule_anim_view), then Find.")

   def stop(self) -> None:
      """!Stops playback.
      @return None
      """
      self.frame_bar.stop()

   def showEvent(self, event: QtGui.QShowEvent) -> None:
      """!Shows the frame chosen once the panel is in front (frames are read only then).
      @param event  QShowEvent
      @return None
      """
      super().showEvent(event)
      self.show_frame(self.frame_bar.frame())

   def _fill_scenes(self) -> None:
      """!The sandbox's scenes (scenes.h).
      @return None
      """
      self._filling = True
      try:
         self.scenes.clear()
         for s in core.scenes():
            self.scenes.addItem(f"{s.index} {s.name}: frames {s.first} to {s.first + s.frames - 1}")
      finally:
         self._filling = False

   def find(self) -> bool:
      """!Looks for the viewer (core.find_viewer()).
      @return True when one was found
      """
      found = core.find_viewer()
      if found is None:
         self.host.show_status("No capsule_anim_view found: build the engine's tests, or Browse... for it")
         return False
      return self.set_viewer(str(found))

   def browse(self) -> bool:
      """!Asks for the viewer.
      @return True when one was chosen
      """
      path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "The engine's capsule_anim_view", "", VIEWER_FILTER)
      return self.set_viewer(path) if path else False

   def set_viewer(self, path: str, remember: bool = True) -> bool:
      """!Uses a viewer program and shows the frame chosen.
      @param path      the program
      @param remember  keep the choice in the settings
      @return True when it is a program
      """
      if not path.strip():
         return False
      try:
         self.viewer = core.Viewer(path.strip())
      except VIEWER_ERRORS as e:
         self.viewer = None
         self.host.show_status(f"Viewer: {e}")
         return False
      self.path_edit.setText(str(self.viewer.program))
      if remember:
         QtCore.QSettings().setValue(VIEWER_KEY, str(self.viewer.program))
      self.show_frame(self.frame_bar.frame())
      return True

   def check(self) -> bool:
      """!Runs the viewer's check and shows its result.
      @return True when it passed
      """
      if self.viewer is None:
         return self.explain("Check", "viewer")
      try:
         ok, text = self.viewer.check()
      except VIEWER_ERRORS as e:
         self.check_label.setText(str(e))
         return False
      self.check_label.setText(("Passed: " if ok else "Failed: ") + text)
      return ok

   def _scene_chosen(self, row: int) -> None:
      """!A scene was picked: its first frame.
      @param row  its index
      @return None
      """
      if self._filling or row < 0:
         return
      self.frame_bar.set_frame(core.scenes()[row].first)

   def show_frame(self, frame: int) -> None:
      """!Shows a frame (read from the viewer when it is not kept yet).
      @param frame  1-based frame
      @return None
      """
      scene = core.scene_of(frame)
      self.where.setText(f"Frame {frame}" + (f": scene {scene.index} {scene.name}, its frame {frame - scene.first}"
                                             if scene else ""))
      if self.viewer is None:
         self.view.set_image(None)
         return
      if not self.isVisible():
         return   # read when the panel shows (showEvent()): opening the editor runs no program
      QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
      try:
         rgb = self.viewer.frame(frame)
      except VIEWER_ERRORS as e:
         self.frame_bar.stop()
         self.host.show_status(f"Viewer: {e}")
         self.view.set_image(None)
         return
      finally:
         QtWidgets.QApplication.restoreOverrideCursor()
      self.view.set_image(rgb_qimage(core.FRAME_WIDTH, core.FRAME_HEIGHT, rgb))
