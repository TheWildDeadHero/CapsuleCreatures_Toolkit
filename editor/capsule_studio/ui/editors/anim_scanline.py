"""![S8] Scanline-effect preview (M5, D-38): the line tables a scene writes for one register, frame by frame, and
the screen they make with simple shapes on two layers (core/anim_scanline.py).

Left: the register (a layer's x or y scroll, window 0's edges, the blend weights), the table's source (the engine's
wave, a weight ramp, a growing diamond) and its settings. Middle: the screen on the frame shown (layer A: stripes,
a ring and a bar; layer B: checks) with the frame bar. Right: the frame's table, one row per line (the value, and
what it means for the register), and a plot of it. A change shows at once; nothing is saved (a preview).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import anim_scanline as core
from ...core import engine
from ..panel import EditorPanel
from ..panes import NARROW, WIDE, mark_panel, pane, splitter
from ..widgets import PixelView, set_enabled
from .anim_common import PICTURE_ZOOM, FrameBar, rgb_qimage

if TYPE_CHECKING:
   from ..panel import PanelHost

## The settings' fields: attribute, title, smallest and largest value, the sources that use it.
SETTINGS = (
   ("start_line", "First line", 0, core.LINE_ENTRIES, ("wave",)),
   ("end_line", "Line after the last", 0, core.LINE_ENTRIES, ("wave",)),
   ("frequency", "Frequency", 1, core.BYTE_MASK, ("wave",)),
   ("amplitude", "Amplitude", 0, core.BYTE_MASK, ("wave",)),
   ("delay", "Delay", 0, core.BYTE_MASK, ("wave",)),
   ("base", "Base value", -core.LAYER_SIZE, core.LAYER_SIZE, ("wave",)),
   ("period", "Period", 1, core.LAYER_SIZE, ("ramp",)),
   ("speed", "Lines a frame", -core.LAYER_SIZE, core.LAYER_SIZE, ("ramp",)),
   ("radius", "First radius", 0, core.SCREEN_WIDTH, ("diamond",)),
   ("growth", "Radius a frame", -core.SCREEN_WIDTH, core.SCREEN_WIDTH, ("diamond",)),
)
## Largest frame count the preview offers.
MAX_FRAMES = 1000
## Table columns: line, value, meaning.
TABLE_COLUMNS = ("Line", "Value", "Meaning")
## Table column of the value.
VALUE_COLUMN = 1
## Table column of the meaning.
MEANING_COLUMN = 2
## Plot size, pixels (one column a line, LINE_ENTRIES wide; the values scaled to the height).
PLOT_HEIGHT = 96
## Plot colours.
PLOT_LINE = QtGui.QColor(32, 96, 200)
## The plot's zero line.
PLOT_AXIS = QtGui.QColor(160, 160, 160)
## Halves.
HALF = 2
## Starting widths of the left and right panes, pixels.
LEFT_WIDTH = 300
## Starting width of the right pane, pixels.
RIGHT_WIDTH = 260


class Plot(QtWidgets.QWidget):
   """!A plot of a table: one point per line, the line down the side (the screen's orientation), the value across.

   @var values
   The values plotted (signed for scrolls).
   """

   def __init__(self) -> None:
      """!An empty plot.
      """
      super().__init__()
      self.values: list[int] = []
      self.setMinimumSize(PLOT_HEIGHT, core.LINE_ENTRIES)
      mark_panel(self)

   def set_values(self, values: list[int]) -> None:
      """!Plots values.
      @param values  one per line
      @return None
      """
      self.values = values
      self.update()

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the axis and the values.
      @param event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.fillRect(self.rect(), self.palette().base())
      if self.values:
         low, high = min(self.values + [0]), max(self.values + [0])
         span = max(1, high - low)
         w = self.width() - 1
         x0 = (0 - low) * w // span
         p.setPen(PLOT_AXIS)
         p.drawLine(x0, 0, x0, self.height())
         p.setPen(PLOT_LINE)
         h = max(1, self.height() - 1)
         points = [QtCore.QPointF((v - low) * w / span, y * h / max(1, len(self.values) - 1))
                   for y, v in enumerate(self.values)]
         p.drawPolyline(points)
      p.end()


class ScanlinePanel(EditorPanel):
   """!The scanline-effect preview (see the module doc).

   @var effect
   The core.Effect shown.
   @var tables
   Its tables, one per frame.
   """

   ## See EditorPanel.panel_id.
   panel_id = "anim_scanline"
   ## See EditorPanel.title.
   title = "Scanline effects"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel (a wave on layer A's x scroll).
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      self.effect = core.Effect()
      self.tables: list[list[int]] = []
      ## True while the panel fills its own widgets.
      self._filling = False
      ## The screens drawn so far, by frame.
      self._images = dict[int, QtGui.QImage]()

      left = QtWidgets.QWidget()
      form = QtWidgets.QFormLayout(left)
      ## The register.
      self.register = QtWidgets.QComboBox()
      for key, text in core.REGISTERS.items():
         self.register.addItem(text, key)
      self.register.currentIndexChanged.connect(lambda _i: self._register_chosen())
      form.addRow("Register", self.register)
      ## The table's source.
      self.source = QtWidgets.QComboBox()
      for key, text in core.SOURCES.items():
         self.source.addItem(text, key)
      self.source.currentIndexChanged.connect(lambda _i: self._changed())
      form.addRow("Table", self.source)
      ## The settings' fields by attribute.
      self.fields: dict[str, QtWidgets.QSpinBox] = {}
      for attr, text, low, high, _sources in SETTINGS:
         s = QtWidgets.QSpinBox()
         s.setRange(low, high)
         s.setValue(getattr(self.effect, attr))
         s.valueChanged.connect(lambda _v: self._changed())
         self.fields[attr] = s
         form.addRow(text, s)
      ## Frames offered.
      self.frame_count = QtWidgets.QSpinBox()
      self.frame_count.setRange(1, MAX_FRAMES)
      self.frame_count.setValue(core.DEFAULT_FRAMES)
      self.frame_count.valueChanged.connect(lambda _v: self._changed())
      form.addRow("Frames", self.frame_count)
      ## The settings' problems.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)
      form.addRow(self.problems)

      middle = QtWidgets.QWidget()
      mv = QtWidgets.QVBoxLayout(middle)
      ## The screen.
      self.view = PixelView(PICTURE_ZOOM)
      mv.addWidget(self.view, 1)
      ## The frame chooser.
      self.frame_bar = FrameBar(lambda f: self.show_frame(f))
      mv.addWidget(self.frame_bar)

      ## The frame's table.
      self.table = QtWidgets.QTableWidget(core.LINE_ENTRIES, len(TABLE_COLUMNS))
      self.table.setHorizontalHeaderLabels(list(TABLE_COLUMNS))
      self.table.verticalHeader().setVisible(False)
      self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      for y in range(core.LINE_ENTRIES):
         self.table.setItem(y, 0, QtWidgets.QTableWidgetItem(str(y) if y < core.SCREEN_HEIGHT else f"{y} (not shown)"))
         for col in (VALUE_COLUMN, MEANING_COLUMN):
            self.table.setItem(y, col, QtWidgets.QTableWidgetItem(""))
      ## The plot.
      self.plot = Plot()
      right = splitter(QtCore.Qt.Orientation.Vertical, [self.table, pane(self.plot)], [WIDE, NARROW])

      lay = QtWidgets.QVBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(splitter(QtCore.Qt.Orientation.Horizontal, [pane(left), pane(middle), right],
                             [NARROW, WIDE, NARROW], [LEFT_WIDTH, None, RIGHT_WIDTH]))
      self._changed()

   def showEvent(self, event: QtGui.QShowEvent) -> None:
      """!Draws the frame chosen once the panel is in front.
      @param event  QShowEvent
      @return None
      """
      super().showEvent(event)
      self.show_frame(self.frame_bar.frame())

   def stop(self) -> None:
      """!Stops playback.
      @return None
      """
      self.frame_bar.stop()

   def set_effect(self, register: str, source: str | None = None, **settings: int) -> None:
      """!Shows an effect (the fields follow).
      @param register  core.REGISTERS id
      @param source    core.SOURCES id, or None for the register's default
      @param settings  Effect fields to set
      @return None
      """
      self._filling = True
      try:
         self.register.setCurrentIndex(self.register.findData(register))
         self.source.setCurrentIndex(self.source.findData(source or core.DEFAULT_SOURCE[register]))
         for attr, v in settings.items():
            self.fields[attr].setValue(v)
      finally:
         self._filling = False
      self._changed()

   def _register_chosen(self) -> None:
      """!Another register: its usual source.
      @return None
      """
      if self._filling:
         return
      self._filling = True
      try:
         self.source.setCurrentIndex(self.source.findData(core.DEFAULT_SOURCE[self.register.currentData()]))
      finally:
         self._filling = False
      self._changed()

   def _changed(self) -> None:
      """!The settings changed: the tables are made again.
      @return None
      """
      if self._filling:
         return
      e = core.Effect(self.register.currentData(), self.source.currentData())
      for attr, s in self.fields.items():
         setattr(e, attr, s.value())
      for attr, _text, _low, _high, sources in SETTINGS:
         set_enabled(self.fields[attr], e.source in sources)
      self.effect = e
      self._images.clear()
      found = e.problems()
      self.problems.setText("\n".join(found))
      try:
         self.tables = core.tables(e, self.frame_count.value()) if not found else []
      except (ValueError, engine.EngineNotFound) as err:
         self.tables = []
         self.problems.setText(str(err))
      self.frame_bar.set_range(0, max(0, len(self.tables) - 1))
      self.show_frame(self.frame_bar.frame())

   def image(self, frame: int) -> QtGui.QImage:
      """!The screen on a frame (kept once drawn).
      @param frame  the frame
      @return QImage
      """
      if frame not in self._images:
         rgb = core.render(self.effect.register, self.tables[frame])
         self._images[frame] = rgb_qimage(core.SCREEN_WIDTH, core.SCREEN_HEIGHT, rgb)
      return self._images[frame]

   def meaning(self, value: int) -> str:
      """!What an entry means for the register.
      @param value  the entry
      @return text
      """
      reg = self.effect.register
      if reg in ("bg_x", "bg_y"):
         return f"scroll {core.signed(value)}"
      if reg == "win0_h":
         left, right = value >> core.WINDOW_LINE_SHIFT, value & core.BYTE_MASK
         return f"x {left} to {right}" if right > left else "closed"
      return f"eva {value & core.BYTE_MASK}, evb {value >> core.WINDOW_LINE_SHIFT}"

   def show_frame(self, frame: int) -> None:
      """!Shows a frame's screen and table.
      @param frame  the frame
      @return None
      """
      if not 0 <= frame < len(self.tables):
         self.view.set_image(None)
         self.plot.set_values([])
         return
      table = self.tables[frame]
      if self.isVisible():   # drawn once the panel shows (showEvent())
         self.view.set_image(self.image(frame))
      for y, v in enumerate(table):
         self.table.item(y, VALUE_COLUMN).setText(f"{v:#06x}")
         self.table.item(y, MEANING_COLUMN).setText(self.meaning(v))
      scroll = self.effect.register in ("bg_x", "bg_y")
      self.plot.set_values([core.signed(v) if scroll else v & core.BYTE_MASK for v in table[:core.SCREEN_HEIGHT]])
