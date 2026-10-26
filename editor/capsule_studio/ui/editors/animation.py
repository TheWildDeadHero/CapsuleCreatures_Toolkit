"""!Animation panel: sprite frames, frame durations, bitmap import, preview. [S3] A direction-grid sprite (D-30) shows
the grid view (ui/editors/sprite_grid.py) in place of the steps and playback."""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import engine, imaging, sprite_grid, sprites
from ..panel import EditorPanel, report_for
from ..qtimage import indexed_qimage, load_rgba, to_qimage
from ..widgets import PaletteStrip, PixelView, button
from .import_dialog import ImportDialog
from .sprite_grid import GridBox

if TYPE_CHECKING:
   from ...core.imaging import RgbaImage
   from ..panel import PanelHost

## A sprite asset, or the compiler's output for one (parsed JSON).
JsonDict = dict[str, Any]

## File dialog filter for importable images.
IMAGE_FILTER = "Images (*.png *.bmp *.gif *.jpg *.jpeg *.ppm);;All files (*)"
## Size offered for a new sprite, (w, h) pixels.
DEFAULT_SPRITE_SIZE = (32, 32)
## Color of a sprite that does not compile in the sprite list.
ERROR_COLOR = QtGui.QColor(192, 48, 48)

## Property grid column of the "Size" label.
SIZE_LABEL_COLUMN = 0
## Property grid column of the size chooser.
SIZE_COLUMN = 1
## Property grid column of the "Animation" label.
ANIM_LABEL_COLUMN = 2
## Property grid column of the animation chooser.
ANIM_COLUMN = 3
## Property grid column of the add animation button.
ADD_ANIM_COLUMN = 4
## Property grid column of the remove animation button.
REMOVE_ANIM_COLUMN = 5
## Property grid column of the loop check box.
LOOP_COLUMN = 6
## Property grid columns the tile budget spans (under the size).
BUDGET_SPAN = 2
## Property grid columns the palette strip spans (from the animation label to the loop box).
PALETTE_SPAN = 5

## Columns of the steps table: frame, duration, milliseconds, mirroring (I3).
STEP_COLUMNS = 4
## Steps table column of the frame (with its thumbnail).
FRAME_COLUMN = 0
## Steps table column of the duration (the editable one).
DURATION_COLUMN = 1
## Steps table column of the duration in milliseconds.
MS_COLUMN = 2
## Steps table column of the step's mirroring (I3 "flips").
FLIP_COLUMN = 3
## The mirroring choices, by flips value (asset::kFlipH 1, kFlipV 2).
FLIP_NAMES = ("none", "horizontal", "vertical", "both")
## Flips bit of a horizontal mirror.
FLIP_H = 1
## Flips bit of a vertical mirror.
FLIP_V = 2
## Property grid row of the I3 sprite settings (stream, step table).
I3_ROW = 2
## Half speed shows each entry twice as long.
HALF_SPEED_DIVISOR = 2
## Size of a frame thumbnail in the steps table, pixels.
THUMBNAIL_SIZE = 48
## Height of a steps table row, pixels (a thumbnail and a margin).
STEP_ROW_HEIGHT = 52

## Zoom the playback view starts at.
PLAYBACK_ZOOM = 4
## Highest playback zoom.
MAX_PLAYBACK_ZOOM = 12
## Playback timer interval, ms (about one 60 Hz display frame; frames come from the elapsed time).
TICK_MS = 16

## Layout stretch of the sprite list column.
LIST_STRETCH = 2
## Layout stretch of the steps column.
STEPS_STRETCH = 5
## Layout stretch of the playback column.
PLAYBACK_STRETCH = 3


def mirror(img: QtGui.QImage, horizontal: bool, vertical: bool) -> QtGui.QImage:
   """!A mirrored copy of an image (Qt 6.9 renamed QImage.mirrored() to flipped()).
   @param img         the image
   @param horizontal  mirror left to right
   @param vertical    mirror top to bottom
   @return the copy
   """
   if hasattr(img, "flipped"):
      orient = QtCore.Qt.Orientation(0)
      if horizontal:
         orient |= QtCore.Qt.Orientation.Horizontal
      if vertical:
         orient |= QtCore.Qt.Orientation.Vertical
      return img.flipped(orient)
   return img.mirrored(horizontal, vertical)


def natural_key(path: str | Path) -> list[int | str]:
   """!Sort key that orders "frame2" before "frame10".
   @param path  file path
   @return tuple for sorting
   """
   return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", Path(path).name)]


class AnimationPanel(EditorPanel):
   """!Edits sprite assets as frame animations.

   Left: the sprites. Middle: the steps of the chosen animation (frame and
   duration), with import and editing buttons. Right: playback in GBA colors
   at the GBA frame rate.

   @var anim
   Animation index being edited.
   @var _filling
   True while the panel itself fills widgets (their signals are ignored).
   @var frames_timeline
   Frame index per display frame of the animation (sprites.timeline()).
   """

   ## See EditorPanel.panel_id.
   panel_id = "animation"
   ## See EditorPanel.title.
   title = "Animation"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Sprite being edited, or None.
      self.key = None
      self.anim = 0
      self._filling = False

      # -- sprites list
      ## Sprite keys.
      self.sprite_list = QtWidgets.QListWidget()
      self.sprite_list.currentRowChanged.connect(lambda *a: self._sprite_chosen(*a))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Sprites"))
      left.addWidget(self.sprite_list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("New...", lambda: self.new_sprite(), "Add an empty sprite"))
      row.addWidget(button("From images...", lambda: self.new_from_images(), "Create a sprite from bitmap files"))
      left.addLayout(row)
      left.addWidget(button("New direction grid...", lambda: self.new_grid(),
                            "[S3] A sprite whose frames are a grid: columns down, up, left (right mirrors left), "
                            "one row per named frame"))
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Rename...", lambda: self.rename_sprite()))
      row.addWidget(button("Delete", lambda: self.delete_sprite()))
      left.addLayout(row)

      # -- sprite properties
      ## OBJ size of the sprite.
      self.size_box = QtWidgets.QComboBox()
      for w, h in sprites.SPRITE_SIZES:
         self.size_box.addItem(f"{w} x {h}")
      self.size_box.activated.connect(lambda *a: self._size_chosen(*a))
      ## Animation chooser.
      self.anim_box = QtWidgets.QComboBox()
      self.anim_box.currentIndexChanged.connect(lambda *a: self._anim_chosen(*a))
      ## Loop checkbox.
      self.loop = QtWidgets.QCheckBox("Loop")
      self.loop.toggled.connect(lambda *a: self._loop_toggled(*a))
      ## Tile use against the slot budget.
      self.budget = QtWidgets.QLabel()
      ## The compiled palette.
      self.palette_strip = PaletteStrip()
      ## Compiler message for the sprite.
      self.error = QtWidgets.QLabel()
      self.error.setWordWrap(True)
      self.error.setStyleSheet("color: #c03030;")
      props = QtWidgets.QGridLayout()
      props.addWidget(QtWidgets.QLabel("Size"), 0, SIZE_LABEL_COLUMN)
      props.addWidget(self.size_box, 0, SIZE_COLUMN)
      props.addWidget(QtWidgets.QLabel("Animation"), 0, ANIM_LABEL_COLUMN)
      props.addWidget(self.anim_box, 0, ANIM_COLUMN)
      props.addWidget(button("+", lambda: self.add_animation(), "Add an animation (copy of this one)"), 0,
                      ADD_ANIM_COLUMN)
      props.addWidget(button("-", lambda: self.remove_animation(), "Remove this animation"), 0, REMOVE_ANIM_COLUMN)
      props.addWidget(self.loop, 0, LOOP_COLUMN)
      props.addWidget(self.budget, 1, SIZE_LABEL_COLUMN, 1, BUDGET_SPAN)
      props.addWidget(self.palette_strip, 1, ANIM_LABEL_COLUMN, 1, PALETTE_SPAN)
      ## I3: only the shown frame is in VRAM.
      self.stream = QtWidgets.QCheckBox("Streamed")
      self.stream.setToolTip("Only the frame shown is in the sprite slot's tiles (uploaded when it changes), so the "
                             "frames together may use more tiles than a slot holds; one frame must fit")
      self.stream.clicked.connect(lambda on: self._sprite_edit("Stream", lambda: sprites.set_stream(
         self.doc, self.key, on)))
      ## I3: the walk animations' step table is set.
      self.has_steps = QtWidgets.QCheckBox("Step table")
      self.has_steps.setToolTip("The walk animations pause on one of two standing entries between steps and a new "
                                "step starts after the other one, so the feet alternate: first stand, second stand, "
                                "after the second, after the first")
      self.has_steps.clicked.connect(lambda on: self._steps_edited())
      ## Its four entries.
      self.step_table = [QtWidgets.QSpinBox() for _ in range(engine.asset_compiler().STEP_ENTRIES)]
      step_row = QtWidgets.QHBoxLayout()
      step_row.addWidget(self.stream)
      step_row.addWidget(self.has_steps)
      for w in self.step_table:
         w.setRange(0, engine.asset_compiler().MAX_ANIM_FRAMES)
         w.setKeyboardTracking(False)
         w.valueChanged.connect(lambda _v: self._steps_edited())
         step_row.addWidget(w)
      step_row.addStretch(1)
      props.addLayout(step_row, I3_ROW, SIZE_LABEL_COLUMN, 1, LOOP_COLUMN + 1)

      # -- steps
      ## Steps of the animation: frame, duration, milliseconds.
      self.table = QtWidgets.QTableWidget(0, STEP_COLUMNS)
      self.table.setHorizontalHeaderLabels(["Frame", "Duration (frames)", "ms", "Mirrored"])
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
      self.table.setIconSize(QtCore.QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
      self.table.verticalHeader().setDefaultSectionSize(STEP_ROW_HEIGHT)
      self.table.horizontalHeader().setSectionResizeMode(FRAME_COLUMN, QtWidgets.QHeaderView.ResizeMode.Stretch)
      self.table.itemChanged.connect(lambda *a: self._cell_edited(*a))
      self.table.itemSelectionChanged.connect(lambda *a: self._selection_changed(*a))
      ## Duration applied to selected steps.
      self.duration = QtWidgets.QSpinBox()
      self.duration.setRange(1, sprites.MAX_DURATION)
      self.duration.setValue(sprites.DEFAULT_DURATION)
      self.duration.setSuffix(" frames")
      edit_row = QtWidgets.QHBoxLayout()
      edit_row.addWidget(button("Import images...", lambda: self.import_images(), "Add bitmap files as new frames"))
      edit_row.addWidget(button("Replace image...", lambda: self.replace_image(),
                                "New bitmap for the selected step's frame"))
      edit_row.addWidget(button("Indexed sheet...", lambda: self.import_indexed_sheet(),
                                "Add every frame of a palette PNG of frames of the sprite's size, its palette indices "
                                "used as they are (imported sprites; the sprite needs a palette of its own)"))
      edit_row.addWidget(button("Duplicate", lambda: self.duplicate(), "Repeat the selected steps (no new tiles)"))
      edit_row.addWidget(button("Remove", lambda: self.remove()))
      edit_row.addWidget(button("Up", lambda: self.move_steps(-1)))
      edit_row.addWidget(button("Down", lambda: self.move_steps(1)))
      dur_row = QtWidgets.QHBoxLayout()
      dur_row.addWidget(QtWidgets.QLabel("Selected steps show for"))
      dur_row.addWidget(self.duration)
      dur_row.addWidget(button("Apply", lambda: self.apply_duration()))
      dur_row.addStretch(1)
      middle = QtWidgets.QVBoxLayout()
      middle.addLayout(props)
      middle.addWidget(self.error)
      middle.addWidget(self.table, 1)
      middle.addLayout(edit_row)
      middle.addLayout(dur_row)

      # -- preview
      ## Playback view.
      self.view = PixelView(PLAYBACK_ZOOM)
      ## Play / pause.
      self.play = QtWidgets.QPushButton("Play")
      self.play.setCheckable(True)
      self.play.toggled.connect(lambda *a: self._play_toggled(*a))
      ## Zoom factor.
      self.zoom = QtWidgets.QSpinBox()
      self.zoom.setRange(1, MAX_PLAYBACK_ZOOM)
      self.zoom.setValue(PLAYBACK_ZOOM)
      self.zoom.setPrefix("x")
      self.zoom.valueChanged.connect(lambda *a: self.view.set_zoom(*a))
      ## I3: plays each entry for twice its duration, as gfx::sprites::set_half_speed() does (slow walks in place).
      self.half_speed = QtWidgets.QCheckBox("Half speed")
      self.half_speed.setToolTip("Preview the animation at half speed, as the engine plays a slow walk in place "
                                 "(gfx::sprites::set_half_speed())")
      ## Playback position.
      self.position = QtWidgets.QLabel()
      right = QtWidgets.QVBoxLayout()
      right.addWidget(self.view, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.play)
      row.addWidget(self.zoom)
      row.addWidget(self.half_speed)
      right.addLayout(row)
      right.addWidget(self.position)
      ## Timer driving playback (drawn from elapsed time, so no drift).
      self.timer = QtCore.QTimer(self)
      self.timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
      self.timer.setInterval(TICK_MS)
      self.timer.timeout.connect(lambda *a: self._tick(*a))
      ## Time since playback started.
      self.clock = QtCore.QElapsedTimer()
      ## Frame images in GBA colors, per frame index (rebuilt on change).
      self.frame_images = []
      self.frames_timeline = []
      ## I3: each display frame's mirroring, as frames_timeline.
      self.flips_timeline = []

      layout = QtWidgets.QHBoxLayout(self)
      box = QtWidgets.QWidget()
      box.setLayout(left)
      layout.addWidget(box, LIST_STRETCH)
      # [S3] the frame steps and playback, or (a direction-grid sprite, D-30) the grid view in their place
      ## The steps and playback page.
      self.frames_page = QtWidgets.QWidget()
      frames_lay = QtWidgets.QHBoxLayout(self.frames_page)
      frames_lay.setContentsMargins(0, 0, 0, 0)
      for part, stretch in ((middle, STEPS_STRETCH), (right, PLAYBACK_STRETCH)):
         box = QtWidgets.QWidget()
         box.setLayout(part)
         frames_lay.addWidget(box, stretch)
      ## [S3] The direction-grid view.
      self.grid_box = GridBox(self)
      ## The page shown: steps or grid.
      self.pages = QtWidgets.QStackedWidget()
      self.pages.addWidget(self.frames_page)
      self.pages.addWidget(self.grid_box)
      layout.addWidget(self.pages, STEPS_STRETCH + PLAYBACK_STRETCH)

   # -- refresh -------------------------------------------------------------

   def sprite(self) -> JsonDict | None:
      """!The sprite asset being edited.
      @return asset object, or None
      """
      a = self.doc.find(self.key) if self.key else None
      return a if a is not None and a.get("kind") == "sprite" else None

   def refresh(self) -> None:
      """!Re-reads the document, keeping the chosen sprite, animation and steps.
      @return None
      """
      self._filling = True
      keys = [a.get("key") for a in self.doc.assets("sprite")]
      if self.key not in keys:
         self.key = keys[0] if keys else None
      self.sprite_list.clear()
      for k in keys:
         item = QtWidgets.QListWidgetItem(k)
         r = report_for(self.host, k)
         if r is not None and not r.ok:
            item.setForeground(QtGui.QBrush(ERROR_COLOR))
            item.setToolTip(r.error)
         self.sprite_list.addItem(item)
      if self.key:
         self.sprite_list.setCurrentRow(keys.index(self.key))
      self._filling = False
      self._fill_sprite()

   def reports_changed(self) -> None:
      """!New validation results: refresh colors, palette, previews (not
      while a duration is being typed into the table; the edit refreshes after).
      @return None
      """
      if self.table.state() == QtWidgets.QAbstractItemView.State.EditingState:
         return
      self.refresh()

   def _fill_sprite(self, keep_rows: list[int] | None = None) -> None:
      """!Fills properties, steps and preview for the current sprite.
      @param keep_rows  step rows to select afterwards, or None to keep the current ones
      @return None
      """
      a = self.sprite()
      # [S3] a direction-grid sprite shows the grid view (its animations are by rows, not steps)
      grid = sprite_grid.is_grid(a)
      self.pages.setCurrentWidget(self.grid_box if grid else self.frames_page)
      if grid:
         self.frames_timeline = []
         self.view.set_image(None)
         self.grid_box.fill(a)
         return
      self.grid_box.stop()
      rows = keep_rows if keep_rows is not None else self.selected_rows()
      scroll = self.table.verticalScrollBar().value()
      self._filling = True
      try:
         enabled = a is not None
         for w in [self.size_box, self.anim_box, self.loop, self.table, self.duration, self.stream,
                   self.has_steps] + self.step_table:
            w.setEnabled(enabled)
         self.table.setRowCount(0)
         self.anim_box.clear()
         if a is None:
            self.budget.setText("")
            self.error.setText("No sprite. Use New... or From images...")
            self.palette_strip.set_colors([])
            self.frame_images = []
            self.frames_timeline = []
            self.view.set_image(None)
            return
         size = (a.get("width"), a.get("height"))
         if size in sprites.SPRITE_SIZES:
            self.size_box.setCurrentIndex(sprites.SPRITE_SIZES.index(size))
         anims = a.get("animations") or [{}]
         for i in range(len(anims)):
            self.anim_box.addItem(f"{i}")
         self.anim = min(self.anim, len(anims) - 1)
         self.anim_box.setCurrentIndex(self.anim)
         self.loop.setChecked(anims[self.anim].get("loop", True))
         self.stream.setChecked(a.get("stream") is True)
         table = sprites.step_table(a)
         self.has_steps.setChecked(table is not None)
         for k, w in enumerate(self.step_table):
            w.setValue(table[k] if table is not None and k < len(table) else 0)
            w.setEnabled(table is not None)
         used, limit = sprites.tile_budget(a)
         self.budget.setText(f"{len(a.get('frames', []))} frames, {used}/{limit} tiles"
                             + (" (streamed: one frame)" if a.get("stream") is True else ""))
         r = report_for(self.host, self.key)
         compiled = None
         self.error.setText("" if r is None or r.ok else r.error)
         # Compiled pixels only while they match the frames (validation runs just after edits).
         if r is not None and r.compiled is not None and r.compiled["frames"] == len(a.get("frames", [])):
            compiled = r.compiled
         self._build_frame_images(a, compiled)
         st = sprites.steps(a, self.anim) if a.get("frames") else []
         mirrored = sprites.flips(a, self.anim) if a.get("frames") else []
         self.table.setRowCount(len(st))
         for i, (f, d) in enumerate(st):
            item = QtWidgets.QTableWidgetItem(f"frame {f}")
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            if f < len(self.frame_images) and self.frame_images[f] is not None:
               item.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(self.frame_images[f])))
            src = a["frames"][f].get("image", "shapes") if f < len(a["frames"]) else "?"
            item.setToolTip(src)
            self.table.setItem(i, FRAME_COLUMN, item)
            self.table.setItem(i, DURATION_COLUMN, QtWidgets.QTableWidgetItem(str(d)))
            ms = QtWidgets.QTableWidgetItem(str(sprites.frames_to_ms(d)))
            ms.setFlags(ms.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, MS_COLUMN, ms)
            flip = QtWidgets.QComboBox()
            flip.addItems(list(FLIP_NAMES))
            flip.setCurrentIndex(mirrored[i] if i < len(mirrored) else 0)
            # row=i binds this row (a plain closure would see the last one)
            flip.activated.connect(lambda value, row=i: self._flip_chosen(row, value))
            self.table.setCellWidget(i, FLIP_COLUMN, flip)
         self.frames_timeline = sprites.timeline(a, self.anim, 1)   # one entry per display frame
         self.flips_timeline = [fl for (_f, d), fl in zip(st, mirrored) for _ in range(d)]
         self._select_rows([r for r in rows if r < len(st)])
         self.table.verticalScrollBar().setValue(scroll)
      finally:
         self._filling = False
      if self.selected_rows():
         self._selection_changed()   # keep showing the selected step
      else:
         self._show_position(0)

   def _build_frame_images(self, a: JsonDict, compiled: JsonDict | None) -> None:
      """!Frame images for thumbnails and playback: the compiled pixels in
      GBA colors when the sprite compiles, else the imported images as they are.
      @param a         sprite asset
      @param compiled  compiler output, or None
      @return None
      """
      self.frame_images = []
      if compiled is not None:
         pal = sprites.palette_rgb(compiled)
         self.palette_strip.set_colors(pal)
         for f in range(compiled["frames"]):
            w, h, idx = sprites.frame_pixels(compiled, f)
            self.frame_images.append(indexed_qimage(w, h, idx, pal))
         return
      self.palette_strip.set_colors([])
      for frame in a.get("frames", []):
         img = self.doc.image(frame["image"]) if "image" in frame else None
         self.frame_images.append(to_qimage(*img) if img else None)

   # -- selection ---------------------------------------------------------------

   def selected_rows(self) -> list[int]:
      """!Selected step rows.
      @return sorted list of indices
      """
      return sorted({i.row() for i in self.table.selectionModel().selectedRows()})

   def _select_rows(self, rows: list[int]) -> None:
      """!Selects step rows.
      @param rows  indices
      @return None
      """
      self.table.clearSelection()
      sel = self.table.selectionModel()
      for r in rows:
         sel.select(self.table.model().index(r, 0),
                    QtCore.QItemSelectionModel.SelectionFlag.Select |
                    QtCore.QItemSelectionModel.SelectionFlag.Rows)
      if rows:   # keyboard anchor for arrows and Shift+click
         sel.setCurrentIndex(self.table.model().index(rows[0], 0),
                             QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)

   def _selection_changed(self) -> None:
      """!Shows the selected step in the preview and its duration in the box.
      @return None
      """
      if self._filling:
         return
      rows = self.selected_rows()
      a = self.sprite()
      if rows and a is not None:
         st = sprites.steps(a, self.anim)
         if rows[0] < len(st):
            self.duration.setValue(st[rows[0]][1])
            if not self.play.isChecked():   # the display frame where the selected step starts
               self._show_position(sum(d for _, d in st[:rows[0]]))

   def _sprite_chosen(self, row: int) -> None:
      """!The sprite list selection changed.
      @param row  list row
      @return None
      """
      if self._filling:
         return
      item = self.sprite_list.item(row)
      self.key = item.text() if item else None
      self.anim = 0
      self._fill_sprite(keep_rows=[])

   def _anim_chosen(self, index: int) -> None:
      """!The animation chooser changed.
      @param index  animation
      @return None
      """
      if self._filling or index < 0:
         return
      self.anim = index
      self._fill_sprite(keep_rows=[])

   # -- edits ---------------------------------------------------------------------

   def _edit(self, label: str, fn: Callable[[], object], rows: list[int] | None = None) -> None:
      """!Runs an edit through the host, then reselects.
      @param label  undo label
      @param fn     callable doing the change; may return new rows to select
      @param rows   rows to select if fn returns nothing
      @return None
      """
      result = []

      def run() -> None:
         """!Runs the change, keeping what it returns."""
         result.append(fn())
      if self.host.run_edit(label, run):
         picked = result[0] if result and isinstance(result[0], list) else rows
         self._fill_sprite(keep_rows=picked)
      else:   # put widgets (size, loop) back to what the document says
         self._fill_sprite()

   def new_sprite(self) -> None:
      """!Asks for a key and size and adds an empty sprite.
      @return None
      """
      doc = self.doc
      key, ok = QtWidgets.QInputDialog.getText(self, "New sprite", "Key:", text="sprite:NEW SPRITE")
      if not ok or not key.strip():
         return
      labels = [f"{w} x {h}" for w, h in sprites.SPRITE_SIZES]
      size, ok = QtWidgets.QInputDialog.getItem(self, "New sprite", "Size:", labels,
                                                sprites.SPRITE_SIZES.index(DEFAULT_SPRITE_SIZE), False)
      if not ok:
         return
      w, h = sprites.SPRITE_SIZES[labels.index(size)]
      done = self.host.run_edit("New sprite", lambda: sprites.new_sprite(doc, key.strip(), w, h))
      if done:
         self.key = key.strip()
         self.refresh()

   def _ask_images(self, title: str) -> tuple[list[str], list[RgbaImage]] | tuple[None, None]:
      """!File chooser for images, naturally sorted, loaded with Qt.
      @param title  dialog title
      @return (paths, images) or (None, None) when cancelled or unreadable
      """
      paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, title, "", IMAGE_FILTER)
      if not paths:
         return None, None
      paths.sort(key=natural_key)
      try:
         return paths, [load_rgba(p) for p in paths]
      except ValueError as e:
         QtWidgets.QMessageBox.warning(self, title, str(e))
         return None, None

   def new_from_images(self) -> None:
      """!Creates a sprite from bitmap files.
      @return None
      """
      paths, raw = self._ask_images("Images for a new sprite")
      if not paths:
         return
      # The key hint: the first file's name without its frame number ("walk_01" -> "sprite:WALK").
      stem = re.sub(r"[_\-\s]*\d+$", "", Path(paths[0]).stem) or "NEW SPRITE"
      dlg = ImportDialog(raw[0][:imaging.IMAGE_SIZE_FIELDS], len(raw), True, "sprite:" + stem.replace("_", " ").upper(),
                         self)
      accepted = dlg.exec()
      o = dlg.options()
      dlg.deleteLater()
      if not accepted:
         return
      w, h = o["size"]
      doc = self.doc

      def run() -> None:
         """!Adds the sprite, then the prepared images as its frames."""
         sprites.new_sprite(doc, o["key"], w, h)
         imgs = [imaging.prepare(img, w, h, o["fit"], o["transparency"], o["color"]) for img in raw]
         sprites.add_images(doc, o["key"], imgs, 0, None, o["duration"], names=[Path(p).stem for p in paths])
      if self.host.run_edit("New sprite from images", run):
         self.key = o["key"]
         self.anim = 0
         self.refresh()

   def import_images(self) -> None:
      """!Adds bitmap files as frames after the selected step.
      @return None
      """
      a = self.sprite()
      if a is None:
         self.new_from_images()
         return
      paths, raw = self._ask_images("Import frames")
      if not paths:
         return
      dlg = ImportDialog(raw[0][:imaging.IMAGE_SIZE_FIELDS], len(raw), False, parent=self)
      accepted = dlg.exec()
      o = dlg.options()
      dlg.deleteLater()
      if not accepted:
         return
      rows = self.selected_rows()
      at = rows[-1] + 1 if rows else None   # after the last selected step, or at the end
      w, h = a["width"], a["height"]
      doc, key, anim = self.doc, self.key, self.anim

      def run() -> list[int]:
         """!Adds the prepared images as frames.
         @return the new steps' rows (selected afterwards)
         """
         imgs = [imaging.prepare(img, w, h, o["fit"], o["transparency"], o["color"]) for img in raw]
         return sprites.add_images(doc, key, imgs, anim, at, o["duration"], names=[Path(p).stem for p in paths])
      self._edit("Import frames", run)

   def replace_image(self) -> None:
      """!Gives the selected step's frame a new bitmap.
      @return None
      """
      doc = self.doc
      a, rows = self.sprite(), self.selected_rows()
      if a is None or not rows:
         return
      paths, raw = self._ask_images("Replace frame image")
      if not paths:
         return
      dlg = ImportDialog(raw[0][:imaging.IMAGE_SIZE_FIELDS], 1, False, parent=self)
      dlg.duration.setEnabled(False)
      accepted = dlg.exec()
      o = dlg.options()
      dlg.deleteLater()
      if not accepted:
         return
      frame = sprites.steps(a, self.anim)[rows[0]][0]
      img = imaging.prepare(raw[0], a["width"], a["height"], o["fit"], o["transparency"], o["color"])
      self._edit("Replace image", lambda: sprites.replace_image(doc, self.key, frame, img,
                                                                Path(paths[0]).stem), rows)

   def duplicate(self) -> None:
      """!Repeats the selected steps.
      @return None
      """
      doc = self.doc
      rows = self.selected_rows()
      if rows:
         self._edit("Duplicate steps", lambda: sprites.duplicate_steps(doc, self.key, rows, self.anim))

   def remove(self) -> None:
      """!Removes the selected steps.
      @return None
      """
      doc = self.doc
      rows = self.selected_rows()
      if rows:
         self._edit("Remove steps", lambda: sprites.remove_steps(doc, self.key, rows, self.anim),
                    [max(0, rows[0] - 1)])

   def move_steps(self, delta: int) -> None:
      """!Moves the selected steps.
      @param delta  -1 up, 1 down
      @return None
      """
      doc = self.doc
      rows = self.selected_rows()
      if rows:
         self._edit("Move steps", lambda: sprites.move_steps(doc, self.key, rows, delta, self.anim))

   def apply_duration(self) -> None:
      """!Sets the duration box's value on the selected steps.
      @return None
      """
      doc = self.doc
      rows = self.selected_rows()
      if rows:
         d = self.duration.value()
         self._edit("Set duration", lambda: sprites.set_durations(doc, self.key, rows, d, self.anim), rows)

   def _cell_edited(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A duration typed into the table.
      @param item  the edited cell
      @return None
      """
      doc = self.doc
      if self._filling or item.column() != DURATION_COLUMN:
         return
      row = item.row()
      try:
         d = int(item.text())
      except ValueError:
         d = 0
      # Rebuild the table after this signal returns, not from inside it.
      if not 1 <= d <= sprites.MAX_DURATION:
         self.host.show_status(f"Durations are 1-{sprites.MAX_DURATION} display frames")
         QtCore.QTimer.singleShot(0, lambda: self._fill_sprite())
         return
      QtCore.QTimer.singleShot(0, lambda: self._edit(
         "Set duration", lambda: sprites.set_durations(doc, self.key, [row], d, self.anim), [row]))

   def _flip_chosen(self, row: int, value: int) -> None:
      """!A step's mirroring was picked (I3); the selected steps take it when the row is one of them.
      @param row    the row of the combo
      @param value  0 none, 1 horizontal, 2 vertical, 3 both
      @return None
      """
      doc = self.doc
      rows = self.selected_rows() if row in self.selected_rows() else [row]
      QtCore.QTimer.singleShot(0, lambda: self._edit(
         "Mirror steps", lambda: sprites.set_flips(doc, self.key, rows, value, self.anim), rows))

   def _sprite_edit(self, label: str, fn: Callable[[], object]) -> None:
      """!A sprite setting changed (I3: stream, step table).
      @param label  undo label
      @param fn     the change
      @return None
      """
      if not self._filling and self.sprite() is not None:
         self._edit(label, fn)

   def _steps_edited(self) -> None:
      """!The step table box or an entry changed (I3).
      @return None
      """
      table = [w.value() for w in self.step_table] if self.has_steps.isChecked() else None
      a = self.sprite()
      if a is not None and table != sprites.step_table(a):
         doc = self.doc
         self._sprite_edit("Step table", lambda: sprites.set_step_table(doc, self.key, table))

   def import_indexed_sheet(self, path: str | None = None) -> None:
      """!Adds every frame of an indexed sheet to the sprite (I3; asks for the file when none is given).
      @param path  the palette PNG, or None to ask
      @return None
      """
      doc = self.doc
      if self.sprite() is None:
         return
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Indexed sheet", "", "Palette PNGs (*.png)")
         if not path:
            return
      self._edit("Indexed sheet", lambda: sprites.add_sheet_frames(doc, self.key, path, self.anim))

   def _loop_toggled(self, on: bool) -> None:
      """!The loop checkbox changed.
      @param on  checked
      @return None
      """
      doc = self.doc
      if not self._filling and self.sprite() is not None:
         self._edit("Loop", lambda: sprites.set_loop(doc, self.key, on, self.anim))

   def _size_chosen(self, index: int) -> None:
      """!A new size was picked.
      @param index  combo index
      @return None
      """
      doc = self.doc
      a = self.sprite()
      if not 0 <= index < len(sprites.SPRITE_SIZES):
         return
      w, h = sprites.SPRITE_SIZES[index]
      if a is not None and (w, h) != (a.get("width"), a.get("height")):
         self._edit("Resize sprite", lambda: sprites.resize(doc, self.key, w, h))

   def add_animation(self) -> None:
      """!Adds an animation, copying the current one.
      @return None
      """
      doc = self.doc
      if self.sprite() is None:
         return
      result = []
      done = self.host.run_edit("Add animation",
                            lambda: result.append(sprites.add_animation(doc, self.key, self.anim)))
      if done:
         self.anim = result[0]
         self._fill_sprite(keep_rows=[])

   def remove_animation(self) -> None:
      """!Removes the current animation.
      @return None
      """
      doc = self.doc
      if self.sprite() is None:
         return
      done = self.host.run_edit("Remove animation",
                                lambda: sprites.remove_animation(doc, self.key, self.anim))
      if done:
         self.anim = max(0, self.anim - 1)
         self._fill_sprite(keep_rows=[])

   def new_grid(self, key: str | None = None, size: tuple[int, int] = sprite_grid.NEW_GRID_SIZE) -> bool:
      """![S3] Adds a direction-grid sprite of empty shape frames (asks its key when none is given).
      @param key   "sprite:NAME", or None to ask
      @param size  frame size
      @return True when added
      """
      if key is None:
         key, ok = QtWidgets.QInputDialog.getText(self, "New direction grid", "Key:", text="sprite:NEW NPC")
         if not ok or not key.strip():
            return False
      key = key.strip()
      if self.host.run_edit("New grid sprite", lambda: sprite_grid.new_grid(self.doc, key, *size)):
         self.key = key
         self.refresh()
         return True
      return False

   def rename_sprite(self) -> None:
      """!Changes the sprite's key.
      @return None
      """
      doc = self.doc
      if self.key is None:
         return
      new, ok = QtWidgets.QInputDialog.getText(self, "Rename sprite", "Key:", text=self.key)
      if ok and new.strip() and new.strip() != self.key:
         old = self.key
         done = self.host.run_edit("Rename sprite", lambda: doc.rename_asset(old, new.strip()))
         if done:
            self.key = new.strip()
            self.refresh()

   def delete_sprite(self) -> None:
      """!Removes the sprite (undo brings it back).
      @return None
      """
      doc = self.doc
      if self.key is not None:
         key = self.key
         done = self.host.run_edit("Delete sprite", lambda: doc.remove_asset(key))
         if done:
            self.key = None
            self.refresh()

   # -- playback --------------------------------------------------------------------

   def _play_toggled(self, on: bool) -> None:
      """!Starts or stops playback.
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
      # Elapsed milliseconds -> GBA display frames (cycles elapsed / cycles per frame), in whole numbers.
      frame = self.clock.elapsed() * sprites.GBA_CLOCK // (sprites.GBA_FRAME_CYCLES * sprites.MS_PER_SECOND)
      self._show_position(frame // HALF_SPEED_DIVISOR if self.half_speed.isChecked() else frame)

   def _show_position(self, frame: int) -> None:
      """!Shows the animation at a display frame.
      @param frame  display frames from the start
      @return None
      """
      tl = self.frames_timeline
      if not tl:
         self.view.set_image(None)
         self.position.setText("")
         return
      a = self.sprite()
      anims = (a.get("animations") or [{}]) if a is not None else [{}]
      looping = anims[min(self.anim, len(anims) - 1)].get("loop", True)
      pos = frame % len(tl) if looping else min(frame, len(tl) - 1)   # a single run stops on its last frame
      f = tl[pos]
      if f < len(self.frame_images):
         img = self.frame_images[f]
         fl = self.flips_timeline[pos] if pos < len(self.flips_timeline) else 0
         if img is not None and fl:   # I3: the step is drawn mirrored
            img = mirror(img, bool(fl & FLIP_H), bool(fl & FLIP_V))
         self.view.set_image(img)
      self.position.setText(f"frame {f}  ·  {pos + 1}/{len(tl)}  ({sprites.frames_to_ms(pos)} ms)")

   def stop(self) -> None:
      """!Stops playback.
      @return None
      """
      self.play.setChecked(False)
      self.grid_box.stop()
