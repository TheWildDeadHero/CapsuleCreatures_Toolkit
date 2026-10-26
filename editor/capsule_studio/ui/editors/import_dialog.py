"""!Options for importing bitmaps as sprite frames."""
from __future__ import annotations

from typing import Any

from PySide6 import QtGui, QtWidgets

from ...core import imaging, sprites

## Labels for imaging.FIT_MODES.
FIT_LABELS = {
   "center": "Keep pixels 1:1 (centre, crop or pad)",
   "nearest": "Scale to fit, sharp (pixel art)",
   "smooth": "Scale to fit, smooth (reduce artwork)",
}
## Labels for imaging.TRANSPARENCY_MODES.
TRANSPARENCY_LABELS = {
   "alpha": "Use the file's transparency",
   "corner": "Top-left pixel's color is transparent",
   "color": "This color is transparent:",
}
## Transparent color offered at first, (r, g, b): magenta, the usual key color.
DEFAULT_KEY_COLOR = (255, 0, 255)


class ImportDialog(QtWidgets.QDialog):
   """!Asks how images become frames: sprite key and size (for a new
   sprite), fitting, transparency, step duration.

   @var color
   (r, g, b) chosen for "color" transparency.
   """

   def __init__(self, first_size: tuple[int, int], count: int, new_sprite: bool, key_hint: str = "",
                parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the dialog.
      @param first_size  (w, h) of the first image, for the default sprite size
      @param count       images being imported
      @param new_sprite  True to also ask for a key and size
      @param key_hint    initial key for a new sprite
      @param parent      parent widget
      """
      super().__init__(parent)
      self.setWindowTitle(f"Import {count} image{'s' if count != 1 else ''}")
      self.color = DEFAULT_KEY_COLOR
      form = QtWidgets.QFormLayout(self)
      ## Key field (new sprite only).
      self.key = QtWidgets.QLineEdit(key_hint)
      ## Size choice (new sprite only).
      self.size_box = QtWidgets.QComboBox()
      if new_sprite:
         for w, h in sprites.SPRITE_SIZES:
            self.size_box.addItem(f"{w} x {h}")
         self.size_box.setCurrentIndex(sprites.SPRITE_SIZES.index(sprites.smallest_size(*first_size)))
         form.addRow("Sprite key", self.key)
         form.addRow("Size", self.size_box)
      ## Fit choice.
      self.fit = QtWidgets.QComboBox()
      for mode in imaging.FIT_MODES:
         self.fit.addItem(FIT_LABELS[mode])
      form.addRow("Other sizes", self.fit)
      ## Transparency choice.
      self.transparency = QtWidgets.QComboBox()
      for mode in imaging.TRANSPARENCY_MODES:
         self.transparency.addItem(TRANSPARENCY_LABELS[mode])
      ## Button showing / picking the key color.
      self.color_button = QtWidgets.QPushButton()
      self.color_button.clicked.connect(lambda *a: self._pick_color(*a))
      self._show_color()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.transparency, 1)
      row.addWidget(self.color_button)
      form.addRow("Transparency", row)
      self.transparency.currentIndexChanged.connect(lambda *_args: self._sync())   # the new value is read in _sync()
      ## Duration of the new steps.
      self.duration = QtWidgets.QSpinBox()
      self.duration.setRange(1, sprites.MAX_DURATION)
      self.duration.setValue(sprites.DEFAULT_DURATION)
      self.duration.setSuffix(" frames")
      ## Duration in milliseconds, for reference.
      self.ms = QtWidgets.QLabel()
      self.duration.valueChanged.connect(lambda *_args: self._sync())   # the new value is read in _sync()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.duration)
      row.addWidget(self.ms, 1)
      form.addRow("Each frame shows for", row)
      buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                           QtWidgets.QDialogButtonBox.StandardButton.Cancel)
      buttons.accepted.connect(lambda *a: self.accept(*a))
      buttons.rejected.connect(lambda *a: self.reject(*a))
      form.addRow(buttons)
      self._sync()

   def _transparency(self) -> str:
      """!The chosen transparency mode.
      @return one of imaging.TRANSPARENCY_MODES
      """
      return imaging.TRANSPARENCY_MODES[max(0, self.transparency.currentIndex())]

   def _sync(self) -> None:
      """!Updates dependent controls.
      @return None
      """
      self.color_button.setEnabled(self._transparency() == "color")
      self.ms.setText(f"= {sprites.frames_to_ms(self.duration.value())} ms")

   def _show_color(self) -> None:
      """!Paints the color button.
      @return None
      """
      self.color_button.setText("#{:02x}{:02x}{:02x}".format(*self.color))
      self.color_button.setStyleSheet("background-color: rgb({}, {}, {});".format(*self.color))

   def _pick_color(self) -> None:
      """!Opens a color chooser for the transparent color.
      @return None
      """
      c = QtWidgets.QColorDialog.getColor(QtGui.QColor(*self.color), self, "Transparent color")
      if c.isValid():
         self.color = (c.red(), c.green(), c.blue())
         self._show_color()

   def options(self) -> dict[str, Any]:
      """!The choices.
      @return dict: key, size (w, h), fit, transparency, color, duration
      """
      return {"key": self.key.text().strip(), "size": sprites.SPRITE_SIZES[max(0, self.size_box.currentIndex())],
              "fit": imaging.FIT_MODES[max(0, self.fit.currentIndex())],
              "transparency": self._transparency(), "color": self.color,
              "duration": self.duration.value()}
