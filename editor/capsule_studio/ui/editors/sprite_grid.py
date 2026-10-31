"""![S3] The sprite editor's direction-grid view (D-30 section 3, engine DS1): shown by the Animation panel in place
of its step table when the chosen sprite's frames are a direction grid ("layout": "direction_grid").

The grid: one row per row name, columns labelled down / up / left / right in the field's order; with "Right mirrors
left" (three columns) the right column is the left one mirrored and stores no pixels. Rows are renamed, added (a
copy), removed and moved here (a sheet grid's palette PNG is rewritten). Animations are lists of rows with a period
or per-row durations, looping or not, for all four directions or one. The preview walks each direction with the
chosen animation at the GBA's frame rate (the compiled sprite: identical frames merged, the right frames mirrored),
and the readout says what the grid saves in ROM. Every change goes through the panel's host (one undo step) and is
compiled by the engine's asset compiler first (core.sprite_grid).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import engine, sprite_grid, sprites
from ..qtimage import to_qimage
from ..panes import split_box
from ..widgets import PixelView, button

if TYPE_CHECKING:
   from .animation import AnimationPanel

## A parsed JSON object (an asset, an animation).
JsonDict = dict[str, Any]

## Errors meaning the engine is missing or too old.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError, KeyError)
## Side of a grid cell's thumbnail, pixels, and the zoom frames are drawn at in it.
THUMBNAIL, THUMBNAIL_ZOOM = 64, 2
## Height of a grid row, pixels.
ROW_HEIGHT = 72
## Zoom of the walk previews.
WALK_ZOOM = 3
## Playback timer interval, milliseconds.
TICK_MS = 16
## The direction chooser's entry for every direction.
ALL_DIRECTIONS = "all four directions"
## Keys of a grid animation (asset_compiler GRID_ANIM_KEYS).
ROWS, PERIOD, DURATIONS, DIRECTION = "rows", "period", "durations", "direction"
## Separator of row names and durations in the animation form.
LIST_SEPARATOR = ","
## Row of the walk previews' grid holding the Play button (under the labels and the views).
PLAY_ROW = 2
## Text of the right column when it mirrors the left.
MIRRORED_HEADER = "right = left mirrored"


class GridBox(QtWidgets.QWidget):
   """!A direction grid: the cells, the rows, the animations by rows and a walk preview per direction."""

   def __init__(self, panel: AnimationPanel) -> None:
      """!Builds the view.
      @param panel  the owning AnimationPanel (its host runs the edits)
      """
      super().__init__()
      ## The owning panel.
      self.panel = panel
      ## True while the view fills its widgets.
      self._filling = False
      ## The compiled sprite (identical frames merged), or None.
      self.compiled = None
      ## Each direction's display frames of the chosen animation: [(frame, flips)].
      self.walks = {}

      ## Three columns, the right one mirrored.
      self.mirror = QtWidgets.QCheckBox("Right mirrors left (3 columns, no right pixels stored)")
      self.mirror.clicked.connect(lambda on: self._mirror_toggled(on))
      ## What the grid saves.
      self.saved = QtWidgets.QLabel()
      head = QtWidgets.QHBoxLayout()
      head.addWidget(self.mirror)
      head.addStretch(1)
      head.addWidget(self.saved)

      ## The grid.
      self.grid = QtWidgets.QTableWidget(0, len(self._directions()))
      self.grid.setIconSize(QtCore.QSize(THUMBNAIL, THUMBNAIL))
      self.grid.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
      self.grid.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.grid.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.grid.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.grid.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
      rows = QtWidgets.QHBoxLayout()
      rows.addWidget(button("Add row...", lambda: self.add_row(), "A copy of the chosen row at the bottom"))
      rows.addWidget(button("Rename row...", lambda: self.rename_row(), "Animations naming it follow"))
      rows.addWidget(button("Remove row", lambda: self.remove_row()))
      rows.addWidget(button("Up", lambda: self.move_row(-1)))
      rows.addWidget(button("Down", lambda: self.move_row(1)))
      rows.addStretch(1)

      # -- animations
      ## The animations.
      self.anims = QtWidgets.QListWidget()
      self.anims.currentRowChanged.connect(lambda _r: self._anim_picked())
      ## The chosen animation's rows.
      self.anim_rows = QtWidgets.QLineEdit()
      self.anim_rows.setToolTip("Row names in order, comma separated (e.g. step_a, stand, step_b, stand)")
      self.anim_rows.editingFinished.connect(lambda: self._anim_edited())
      ## Per-row durations (else the period).
      self.per_row = QtWidgets.QCheckBox("a duration per row")
      self.per_row.clicked.connect(lambda _on: self._anim_edited())
      ## Display frames per row step.
      self.period = QtWidgets.QSpinBox()
      self.period.setRange(1, sprites.MAX_DURATION)
      self.period.setKeyboardTracking(False)
      self.period.valueChanged.connect(lambda _v: self._anim_edited())
      ## Durations per row step.
      self.durations = QtWidgets.QLineEdit()
      self.durations.setToolTip("Display frames per row step, comma separated")
      self.durations.editingFinished.connect(lambda: self._anim_edited())
      ## Loops.
      self.loop = QtWidgets.QCheckBox("loop")
      self.loop.clicked.connect(lambda _on: self._anim_edited())
      ## One direction, or all four.
      self.direction = QtWidgets.QComboBox()
      self.direction.addItems([ALL_DIRECTIONS] + self._directions())
      self.direction.activated.connect(lambda _i: self._anim_edited())
      form = QtWidgets.QFormLayout()
      form.addRow("Rows", self.anim_rows)
      timing = QtWidgets.QHBoxLayout()
      timing.addWidget(self.period)
      timing.addWidget(self.per_row)
      timing.addWidget(self.durations, 1)
      form.addRow("Period", timing)
      form.addRow("", self.loop)
      form.addRow("Plays", self.direction)
      anim_buttons = QtWidgets.QHBoxLayout()
      anim_buttons.addWidget(button("Add", lambda: self.add_animation(), "A copy of the chosen animation"))
      anim_buttons.addWidget(button("Remove", lambda: self.remove_animation()))
      anim_col = QtWidgets.QVBoxLayout()
      anim_col.addWidget(QtWidgets.QLabel("Animations (by rows; each plays in the four directions)"))
      anim_col.addWidget(self.anims, 1)
      anim_col.addLayout(anim_buttons)
      anim_col.addLayout(form)

      # -- walk previews
      ## One view per direction.
      self.views = {d: PixelView(WALK_ZOOM) for d in self._directions()}
      walk = QtWidgets.QGridLayout()
      for k, (d, v) in enumerate(self.views.items()):
         walk.addWidget(QtWidgets.QLabel(d), 0, k)
         walk.addWidget(v, 1, k)
      ## Play / pause.
      self.play = QtWidgets.QPushButton("Play")
      self.play.setCheckable(True)
      self.play.toggled.connect(lambda on: self._play_toggled(on))
      walk.addWidget(self.play, PLAY_ROW, 0)
      ## Timer driving the walk previews.
      self.timer = QtCore.QTimer(self)
      self.timer.setInterval(TICK_MS)
      self.timer.timeout.connect(lambda: self._tick())
      ## Time since playback started.
      self.clock = QtCore.QElapsedTimer()

      lay = QtWidgets.QVBoxLayout(self)
      lay.addLayout(head)
      body = QtWidgets.QHBoxLayout()
      left = QtWidgets.QVBoxLayout()
      left.addWidget(self.grid, 1)
      left.addLayout(rows)
      body.addLayout(left, 1)
      body.addLayout(anim_col, 1)
      lay.addLayout(body, 1)
      lay.addLayout(walk)
      split_box(body)   # [RZ] grid | animations
      split_box(lay)   # [RZ] grid and animations over the walk previews

   # -- helpers -------------------------------------------------------------------------------

   @staticmethod
   def _directions() -> list[str]:
      """!The grid's directions (the engine's order), or none without an engine.
      @return down, up, left, right
      """
      try:
         return sprite_grid.directions()
      except ENGINE_ERRORS:
         return []

   def asset(self) -> JsonDict | None:
      """!The grid sprite shown.
      @return the asset, or None
      """
      a = self.panel.sprite()
      return a if sprite_grid.is_grid(a) else None

   def _edit(self, label: str, fn: Callable[[], object]) -> bool:
      """!One change of the sprite through the panel's host.
      @param label  undo label
      @param fn     the change
      @return True when it went through
      """
      if self._filling or self.asset() is None:
         return False
      ok = self.panel.host.run_edit(label, fn)
      self.panel.refresh()
      return ok

   # -- fill ----------------------------------------------------------------------------------

   def fill(self, a: JsonDict) -> None:
      """!Shows a grid sprite.
      @param a  the sprite asset
      @return None
      """
      self._filling = True
      try:
         doc, key = self.panel.doc, self.panel.key
         dirs = self._directions()
         cols = sprite_grid.columns(a)
         mirrored = sprite_grid.right_mirrors_left(a)
         self.mirror.setChecked(mirrored)
         self.grid.setHorizontalHeaderLabels(dirs[:cols] + ([MIRRORED_HEADER] if mirrored else []))
         names = sprite_grid.rows(a)
         self.grid.setRowCount(len(names))
         self.grid.setVerticalHeaderLabels(names)
         cells, error = sprite_grid.cell_frames(doc, key)
         for r in range(len(names)):
            for c in range(len(dirs)):
               flip = c >= cols   # the right column of a three-column grid: the left one mirrored
               item = QtWidgets.QTableWidgetItem("mirrored" if flip else "")
               if cells is not None:
                  src = r * cols + (sprite_grid.mirrored_from() if flip else c)
                  img = to_qimage(*sprite_grid.frame_image(cells, src, flip))
                  big = img.scaled(img.width() * THUMBNAIL_ZOOM, img.height() * THUMBNAIL_ZOOM)   # no smoothing
                  item.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(big)))
               if flip:
                  item.setForeground(QtGui.QBrush(QtGui.QColor(QtCore.Qt.GlobalColor.gray)))
                  item.setToolTip("Not stored: the left frame mirrored horizontally")
               self.grid.setItem(r, c, item)
         report = doc.compile_asset(a)
         self.compiled = report.compiled if report.ok else None
         saved = sprite_grid.saved(report)
         stored = self.compiled["frames"] if self.compiled else 0
         self.saved.setText(f"ROM saved: {saved} bytes ({stored} frames stored)" if saved is not None
                            else f"error: {report.error or error}")
         row = self.anims.currentRow()
         self.anims.clear()
         for i, an in enumerate(sprite_grid.animations(a)):
            timing = f"durations {an.get(DURATIONS)}" if DURATIONS in an else f"period {an.get(PERIOD, 1)}"
            shown, where = " ".join(an.get(ROWS, [])), an.get(DIRECTION, "all")
            self.anims.addItem(f"{i}: {shown} ({timing}, {where})")
         if self.anims.count():
            self.anims.setCurrentRow(min(max(row, 0), self.anims.count() - 1))
         self._fill_anim()
      finally:
         self._filling = False
      self._build_walks()

   def _fill_anim(self) -> None:
      """!The chosen animation's form.
      @return None
      """
      a = self.asset()
      i = self.anims.currentRow()
      items = sprite_grid.animations(a) if a is not None else []
      an = items[i] if 0 <= i < len(items) else None
      for w in (self.anim_rows, self.per_row, self.period, self.durations, self.loop, self.direction):
         w.setEnabled(an is not None)
      if an is None:
         return
      self.anim_rows.setText(", ".join(an.get("rows", [])))
      per_row = "durations" in an
      self.per_row.setChecked(per_row)
      self.period.setValue(an.get("period", 1) if not per_row else an["durations"][0])
      self.period.setEnabled(not per_row)
      self.durations.setText(", ".join(str(d) for d in an.get("durations", [])))
      self.durations.setEnabled(per_row)
      self.loop.setChecked(an.get("loop", True) is not False)
      self.direction.setCurrentText(an.get("direction", ALL_DIRECTIONS))

   def _build_walks(self) -> None:
      """!Each direction's frames of the chosen animation, and the first one shown.
      @return None
      """
      a = self.asset()
      self.walks = {}
      i = max(0, self.anims.currentRow())
      if a is not None and self.compiled is not None:
         for d in self._directions():
            k = sprite_grid.compiled_index(a, i, d)
            if k is not None:
               self.walks[d] = sprite_grid.timeline(self.compiled, k)
      self._show(0)

   def _show(self, n: int) -> None:
      """!Shows display frame n of every direction's walk.
      @param n  display frames since playback started
      @return None
      """
      for d, v in self.views.items():
         tl = self.walks.get(d)
         if not tl or self.compiled is None:
            v.set_image(None)
            continue
         frame, flips = tl[n % len(tl)]
         v.set_image(to_qimage(*sprite_grid.frame_image(self.compiled, frame, bool(flips & sprite_grid.FLIP_H))))

   # -- edits ---------------------------------------------------------------------------------

   def _chosen_row(self) -> str | None:
      """!The chosen grid row's name.
      @return the name, or None
      """
      a = self.asset()
      names = sprite_grid.rows(a) if a is not None else []
      r = self.grid.currentRow()
      return names[r] if 0 <= r < len(names) else (names[-1] if names else None)

   def _mirror_toggled(self, on: bool) -> None:
      """!Right mirrors left on or off.
      @param on  three columns
      @return None
      """
      doc, key = self.panel.doc, self.panel.key
      lost: dict[str, int] = {}

      def run() -> None:
         lost["n"] = sprite_grid.set_right_mirrors_left(doc, key, on)
      if self._edit("Right mirrors left", run) and lost.get("n"):
         n = lost["n"]
         self.panel.host.show_status(f"{n} right frame(s) differed from the left ones mirrored; undo to keep them")

   def add_row(self, name: str | None = None) -> bool:
      """!Adds a copy of the chosen row (asks its name when none is given).
      @param name  the new row's name, or None to ask
      @return True when added
      """
      src = self._chosen_row()
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add row", "Row name:")
         if not ok or not name.strip():
            return False
      new = name.strip()
      return self._edit("Grid row", lambda: sprite_grid.add_row(self.panel.doc, self.panel.key, new, src))

   def rename_row(self, new: str | None = None) -> bool:
      """!Renames the chosen row (asks when no name is given).
      @param new  the new name, or None to ask
      @return True when renamed
      """
      old = self._chosen_row()
      if old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename row", "Row name:", text=old)
         if not ok or not new.strip():
            return False
      name = new.strip()
      return self._edit("Grid row", lambda: sprite_grid.rename_row(self.panel.doc, self.panel.key, old, name))

   def remove_row(self) -> bool:
      """!Removes the chosen row.
      @return True when removed
      """
      name = self._chosen_row()
      return name is not None and self._edit("Grid row", lambda: sprite_grid.remove_row(
         self.panel.doc, self.panel.key, name))

   def move_row(self, delta: int) -> bool:
      """!Moves the chosen row.
      @param delta  -1 up, +1 down
      @return True when moved
      """
      name = self._chosen_row()
      r = self.grid.currentRow()
      ok = name is not None and self._edit("Grid row", lambda: sprite_grid.move_row(
         self.panel.doc, self.panel.key, name, delta))
      if ok:
         self.grid.selectRow(max(0, min(self.grid.rowCount() - 1, r + delta)))
      return ok

   def _anim_picked(self) -> None:
      """!Another animation: its form and walk.
      @return None
      """
      if self._filling is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      self._filling = True
      try:
         self._fill_anim()
      finally:
         self._filling = False
      self._build_walks()

   def _anim_edited(self) -> None:
      """!The animation form changed: the chosen animation takes it (one undo step).
      @return None
      """
      a = self.asset()
      i = self.anims.currentRow()
      if self._filling or a is None or not 0 <= i < len(sprite_grid.animations(a)):
         return
      an = sprite_grid.animations(a)[i]
      names = [n.strip() for n in self.anim_rows.text().split(LIST_SEPARATOR) if n.strip()]
      fields: dict[str, Any] = {"rows": names, "loop": None if self.loop.isChecked() and "loop" not in an
                                else self.loop.isChecked(),
                                "direction": None if self.direction.currentText() == ALL_DIRECTIONS
                                else self.direction.currentText()}
      if self.per_row.isChecked():
         try:
            durations = [int(v) for v in self.durations.text().split(LIST_SEPARATOR) if v.strip()]
         except ValueError:
            self.panel.host.show_status("Durations are numbers, comma separated")
            return
         # a duration per row: one for each, the period's when not typed
         fields["durations"] = (durations + [an.get("period", self.period.value())] * len(names))[:len(names)]
      else:
         fields["period"] = self.period.value()
      same = all(an.get(k) == v for k, v in fields.items() if v is not None) and \
         all(k not in an for k, v in fields.items() if v is None)
      if same:
         return
      key = self.panel.key
      self._edit("Grid animation", lambda: sprite_grid.set_animation(self.panel.doc, key, i, **fields))

   def add_animation(self) -> bool:
      """!Adds a copy of the chosen animation (or one of the first row).
      @return True when added
      """
      a = self.asset()
      if a is None:
         return False
      items = sprite_grid.animations(a)
      i = self.anims.currentRow()
      src = items[i] if 0 <= i < len(items) else {"rows": sprite_grid.rows(a)[:1]}
      ok = self._edit("Grid animation", lambda: sprite_grid.add_animation(
         self.panel.doc, self.panel.key, src.get("rows", []), src.get("period", sprite_grid.NEW_PERIOD)
         if "durations" not in src else None, src.get("durations"), src.get("loop"), src.get("direction")))
      if ok:
         self.anims.setCurrentRow(self.anims.count() - 1)
      return ok

   def remove_animation(self) -> bool:
      """!Removes the chosen animation (a sprite keeps one).
      @return True when removed
      """
      i = self.anims.currentRow()
      return i >= 0 and self._edit("Remove grid animation", lambda: sprite_grid.remove_animation(
         self.panel.doc, self.panel.key, i))

   # -- playback --------------------------------------------------------------------------------

   def _play_toggled(self, on: bool) -> None:
      """!Starts or stops the walk previews.
      @param on  playing
      @return None
      """
      self.play.setText("Pause" if on else "Play")
      if on:
         self.clock.start()
         self.timer.start()
      else:
         self.timer.stop()

   def _tick(self) -> None:
      """!Shows the display frame for the elapsed time.
      @return None
      """
      # elapsed milliseconds -> GBA display frames (cycles elapsed / cycles per frame), in whole numbers
      self._show(self.clock.elapsed() * sprites.GBA_CLOCK // (sprites.GBA_FRAME_CYCLES * sprites.MS_PER_SECOND))

   def stop(self) -> None:
      """!Stops playback.
      @return None
      """
      self.play.setChecked(False)
