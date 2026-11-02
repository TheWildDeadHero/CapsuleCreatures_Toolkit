"""![S8] Parts the battle animation panels share (M5): a frame bar (a slider, a frame field, play / pause and a step
button, driven by a timer) and RGB pictures as QImages. The panels are anim_script.py (the animation-script viewer
and stepper), anim_affine.py (the affine animation editor), anim_scanline.py (the scanline-effect preview) and
anim_scene.py (the engine sandbox's scene viewer)."""
from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from ..widgets import button

## Playback timer interval, ms (about one 60 Hz frame).
TICK_MS = 16
## Bytes of an RGB pixel.
RGB_BYTES = 3
## Zoom the panels' pictures start at.
PICTURE_ZOOM = 2


def rgb_qimage(w: int, h: int, rgb: bytes) -> QtGui.QImage:
   """!(w, h, RGB) as a QImage (an independent copy).
   @param w    width
   @param h    height
   @param rgb  3 bytes a pixel
   @return QImage
   """
   return QtGui.QImage(bytes(rgb), w, h, w * RGB_BYTES, QtGui.QImage.Format.Format_RGB888).copy()


class FrameBar(QtWidgets.QWidget):
   """!A frame chooser: |< and > buttons, play / pause, a slider and a frame field; changed(frame) on every change.

   @var slider
   The QSlider.
   @var field
   The QSpinBox.
   @var play_button
   The play / pause button.
   @var timer
   The playback QTimer.
   """

   def __init__(self, changed: Callable[[int], None], first: int = 0, last: int = 0,
                parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the bar.
      @param changed  called with the new frame
      @param first    first frame
      @param last     last frame
      @param parent   parent widget
      """
      super().__init__(parent)
      ## Called with the new frame.
      self._changed = changed
      ## True while the bar sets its own widgets.
      self._setting = False
      lay = QtWidgets.QHBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      self.play_button = button("Play", self.toggle, "Play the frames in turn (again to pause)")
      lay.addWidget(button("|<", lambda: self.set_frame(self.slider.minimum()), "First frame"))
      lay.addWidget(button("<", lambda: self.set_frame(self.frame() - 1), "Previous frame"))
      lay.addWidget(button(">", lambda: self.set_frame(self.frame() + 1), "Next frame"))
      lay.addWidget(self.play_button)
      self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
      self.slider.valueChanged.connect(lambda v: self._moved(v))
      lay.addWidget(self.slider, 1)
      self.field = QtWidgets.QSpinBox()
      self.field.setPrefix("frame ")
      self.field.valueChanged.connect(lambda v: self._moved(v))
      lay.addWidget(self.field)
      self.timer = QtCore.QTimer(self)
      self.timer.setInterval(TICK_MS)
      self.timer.timeout.connect(lambda: self._tick())
      self.set_range(first, last)

   def frame(self) -> int:
      """!The frame shown.
      @return frame
      """
      return self.slider.value()

   def set_range(self, first: int, last: int) -> None:
      """!The frames offered (the frame shown is kept inside them).
      @param first  first frame
      @param last   last frame
      @return None
      """
      self._setting = True
      try:
         for w in (self.slider, self.field):
            w.setRange(first, max(first, last))
      finally:
         self._setting = False

   def set_frame(self, frame: int) -> None:
      """!Shows a frame (clamped to the range; changed() is called when it moves).
      @param frame  the frame
      @return None
      """
      self.slider.setValue(max(self.slider.minimum(), min(self.slider.maximum(), frame)))

   def _moved(self, v: int) -> None:
      """!The slider or the field moved: both follow, changed() runs.
      @param v  the frame
      @return None
      """
      if self._setting:
         return
      self._setting = True
      try:
         self.slider.setValue(v)
         self.field.setValue(v)
      finally:
         self._setting = False
      self._changed(v)

   def toggle(self) -> None:
      """!Plays or pauses.
      @return None
      """
      if self.timer.isActive():
         self.stop()
      else:
         if self.frame() >= self.slider.maximum():
            self.set_frame(self.slider.minimum())
         self.timer.start()
         self.play_button.setText("Pause")

   def stop(self) -> None:
      """!Pauses.
      @return None
      """
      self.timer.stop()
      self.play_button.setText("Play")

   def _tick(self) -> None:
      """!The next frame; at the last one playback stops.
      @return None
      """
      if self.frame() >= self.slider.maximum():
         self.stop()
         return
      self.set_frame(self.frame() + 1)
