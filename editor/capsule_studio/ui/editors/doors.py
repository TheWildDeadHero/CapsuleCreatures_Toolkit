"""![S3] The scene editor's Doors panel (D-30 section 1, engine DS1): door animation assets of the asset manifest.

Left: the doors. Middle: the chosen door's size (cells, the anchor its bottom-left cell), map layers it draws, how
its frames show (tiles loaded into the map's tile area, with a sheet, tiles per frame and a load position; or cell
overrides, one entry set per frame), the entries of each cell and layer (a frame tile tK [pB] [h|v|hv], or a raw map
entry), the open and close timing tables (frame or closed, ticks; close may be the open reversed), sounds and the
exit direction. Right: the preview, a frame alone (indexed sheets in a gray ramp: their pixels are indices into the
map's banks) or on a map cell (the map's palettes and tiles, as capsule/field/doors.cpp draws it), and playback of
the opening or closing at the GBA frame rate. Every change goes through the host's run_edit() and is compiled by the
engine's asset compiler before it is kept (core.doors); everything here is also a `capsule-studio door` command.
S4: the sounds are checked against the game's sounds (core.doors.sound_problems(); the engine does not check them).
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ...core import doors, engine, sprites
from ...core.world import Project
from ..panel import EditorPanel, PanelHost
from ..qtimage import to_qimage
from ..widgets import PixelView, button

if TYPE_CHECKING:
   from ...core.document import Document

## A parsed JSON object (an asset).
JsonDict = dict[str, Any]

## Errors meaning the engine is missing or too old, or a file cannot be read.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError, KeyError, OSError)
## Steps table columns.
STEP_COLUMNS = ("Frame", "Ticks")
## Preview zoom.
PREVIEW_ZOOM = 4
## Playback timer interval, milliseconds.
TICK_MS = 16
## The world chooser's entry for "no map" (the frame alone).
ALONE = "(the door alone)"
## Image file filter of a door's indexed sheet.
SHEET_FILTER = "Palette PNG (*.png);;All files (*)"
## World file filter.
WORLD_FILTER = "Worlds (world.json *.json);;All files (*)"
## Most cells a preview cell spin reaches either way.
MAX_CELL = 16383
## S4: colour of the sound check's warnings.
SOUND_WARNING_COLOR = "#b08010"
## Layout stretch of the list, the form and the preview.
LIST_STRETCH, FORM_STRETCH, PREVIEW_STRETCH = 1, 3, 2


class DoorPanel(EditorPanel):
   """!Edits door assets (core.doors)."""

   ## See EditorPanel.panel_id.
   panel_id = "doors"
   ## See EditorPanel.title.
   title = "Doors"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The chosen door's key, or None.
      self.key = None
      ## True while widgets are being filled.
      self._filling = False
      ## The world a door is previewed on, or None (opened read-only: nothing here edits it).
      self.world = None
      ## Frames the playback shows, one per display frame (frame index or "closed").
      self.timeline = []
      ## (door, world) the preview was last placed for (locate()).
      self._located_for = None

      # -- list
      ## The doors.
      self.list = QtWidgets.QListWidget()
      self.list.currentRowChanged.connect(lambda _r: self._picked())
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Doors"))
      left.addWidget(self.list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("New...", lambda: self.new_door(), "A door that compiles: an empty sheet of frames"))
      row.addWidget(button("Rename...", lambda: self.rename_door()))
      row.addWidget(button("Delete", lambda: self.delete_door()))
      left.addLayout(row)

      # -- form
      lim = self._limits()
      ## Cells across and down.
      self.cells_w = QtWidgets.QSpinBox()
      ## Cells down.
      self.cells_h = QtWidgets.QSpinBox()
      for w in (self.cells_w, self.cells_h):
         w.setRange(1, lim.get("cells", 1))
         w.setKeyboardTracking(False)
         w.valueChanged.connect(lambda _v: self._cells_changed())
      ## Map layers it draws.
      self.layers = QtWidgets.QSpinBox()
      self.layers.setRange(1, lim.get("layers", 1))
      self.layers.setKeyboardTracking(False)
      self.layers.valueChanged.connect(lambda v: self._layers_changed(v))
      ## How frames show.
      self.show_as = QtWidgets.QComboBox()
      self.show_as.addItems(self._words(doors.shows))
      self.show_as.setToolTip("tiles: the frames' tiles load into the map's tile area and the entries draw them; "
                              "override: each frame is the cells' own map entries")
      self.show_as.activated.connect(lambda _i: self._show_chosen())
      ## Exit direction.
      self.exit = QtWidgets.QComboBox()
      self.exit.addItems(self._words(doors.directions))
      self.exit.setToolTip("The direction a walker arriving on the door walks out")
      self.exit.activated.connect(lambda _i: self._set(exit=self.exit.currentText()))
      ## Sounds.
      self.open_sound = QtWidgets.QLineEdit()
      self.open_sound.setPlaceholderText("sound key (none)")
      ## Close sound.
      self.close_sound = QtWidgets.QLineEdit()
      self.close_sound.setPlaceholderText("sound key (none)")
      for w in (self.open_sound, self.close_sound):
         w.editingFinished.connect(lambda: self._sounds_changed())
         w.setToolTip("sound:NAME: a sound asset of the manifest or a constant of the game's scripts (the sound "
                      "ids `sound se NAME` plays); the studio checks it, the engine does not yet")
      ## S4: the sound keys the game has (doors.sound_keys(): read on refresh), or None.
      self.known_sounds = None
      ## A tiles door's sheet (shown), and its tiles per frame and load position.
      self.sheet = QtWidgets.QLabel()
      self.sheet.setWordWrap(True)
      ## Tiles per frame.
      self.frame_tiles = QtWidgets.QSpinBox()
      self.frame_tiles.setRange(1, lim.get("map_tiles", 1))
      self.frame_tiles.setKeyboardTracking(False)
      self.frame_tiles.valueChanged.connect(lambda v: self._set(frame_tiles=v))
      ## Load position: the end of the map's tile area, or a tile.
      self.load_end = QtWidgets.QCheckBox("at the end of the map's tile area")
      self.load_end.clicked.connect(lambda on: self._load_changed())
      ## The first map tile.
      self.load_at = QtWidgets.QSpinBox()
      self.load_at.setRange(0, lim.get("map_tiles", 1) - 1)
      self.load_at.setKeyboardTracking(False)
      self.load_at.valueChanged.connect(lambda _v: self._load_changed())
      size = QtWidgets.QHBoxLayout()
      size.addWidget(self.cells_w)
      size.addWidget(QtWidgets.QLabel("x"))
      size.addWidget(self.cells_h)
      size.addWidget(QtWidgets.QLabel("cells (the anchor is the bottom-left one)"))
      load = QtWidgets.QHBoxLayout()
      load.addWidget(self.load_end)
      load.addWidget(self.load_at)
      sheet_row = QtWidgets.QHBoxLayout()
      sheet_row.addWidget(self.sheet, 1)
      sheet_row.addWidget(button("Indexed sheet...", lambda: self.choose_sheet(),
                                 "A palette PNG of the frames, one after another in reading order; its pixels are "
                                 "indices into the map bank each entry names"))
      ## The form.
      self.form = QtWidgets.QFormLayout()
      self.form.addRow("Cells", size)
      self.form.addRow("Map layers", self.layers)
      self.form.addRow("Frames show as", self.show_as)
      self.form.addRow("Sheet", sheet_row)
      self.form.addRow("Tiles per frame", self.frame_tiles)
      self.form.addRow("Loaded", load)
      self.form.addRow("Exit", self.exit)
      self.form.addRow("Open sound", self.open_sound)
      self.form.addRow("Close sound", self.close_sound)

      # -- entries
      ## An override door's frame whose entries show.
      self.entry_frame = QtWidgets.QSpinBox()
      self.entry_frame.valueChanged.connect(lambda _v: self._fill_entries())
      ## Per cell and layer, the four entries.
      self.entries = QtWidgets.QTableWidget(0, len(doors.SLOTS))
      self.entries.setHorizontalHeaderLabels(list(doors.SLOTS))
      self.entries.setToolTip("tK: frame tile K; pB: palette bank B; h / v / hv: flipped; or a raw map entry "
                              "(0x...)")
      self.entries.itemChanged.connect(lambda item: self._entry_edited(item))
      entry_head = QtWidgets.QHBoxLayout()
      entry_head.addWidget(QtWidgets.QLabel("Entries per cell (top row first) and layer"))
      entry_head.addStretch(1)
      ## The frame spin's label.
      self.entry_frame_label = QtWidgets.QLabel("Frame")
      entry_head.addWidget(self.entry_frame_label)
      entry_head.addWidget(self.entry_frame)

      # -- timing
      ## Opening and closing steps.
      self.steps = {w: QtWidgets.QTableWidget(0, len(STEP_COLUMNS)) for w in ("open", "close")}
      timing = QtWidgets.QHBoxLayout()
      ## Close: the open steps backwards.
      self.reverse = QtWidgets.QCheckBox("Close: the open steps reversed")
      self.reverse.clicked.connect(lambda on: self._reverse_toggled(on))
      for which, table in self.steps.items():
         table.setHorizontalHeaderLabels(list(STEP_COLUMNS))
         most = lim.get("ticks", 1)
         table.setToolTip(f"Frame: a frame number or \"closed\"; ticks: display frames it shows (1-{most}); the "
                          "frame of a step is drawn on its first display frame")
         table.itemChanged.connect(lambda _item, w=which: self._steps_edited(w))
         box = QtWidgets.QVBoxLayout()
         box.addWidget(QtWidgets.QLabel("Open" if which == "open" else "Close"))
         box.addWidget(table, 1)
         r = QtWidgets.QHBoxLayout()
         r.addWidget(button("Add step", lambda w=which: self.add_step(w)))
         r.addWidget(button("Remove step", lambda w=which: self.remove_step(w)))
         r.addWidget(button("Play", lambda w=which: self.play(w), "Play it at the GBA's frame rate"))
         box.addLayout(r)
         if which == "close":
            box.addWidget(self.reverse)
         timing.addLayout(box)
      ## Compiler message.
      self.error = QtWidgets.QLabel()
      self.error.setWordWrap(True)
      self.error.setStyleSheet("color: #c03030;")
      ## S4: sounds that name no sound of the game (doors.sound_problems()).
      self.sound_check = QtWidgets.QLabel()
      self.sound_check.setWordWrap(True)
      self.sound_check.setStyleSheet(f"color: {SOUND_WARNING_COLOR};")
      mid = QtWidgets.QVBoxLayout()
      mid.addLayout(self.form)
      mid.addWidget(self.error)
      mid.addWidget(self.sound_check)
      mid.addLayout(entry_head)
      mid.addWidget(self.entries, 1)
      mid.addLayout(timing, 1)

      # -- preview
      ## The world a door is previewed on.
      self.world_box = QtWidgets.QComboBox()
      self.world_box.activated.connect(lambda _i: self._world_chosen())
      ## Its map.
      self.map_box = QtWidgets.QComboBox()
      self.map_box.activated.connect(lambda _i: self._map_chosen())
      ## The anchor cell.
      self.cell_x = QtWidgets.QSpinBox()
      ## The anchor row.
      self.cell_y = QtWidgets.QSpinBox()
      for w in (self.cell_x, self.cell_y):
         w.setRange(-MAX_CELL, MAX_CELL)
         w.setKeyboardTracking(False)
         w.valueChanged.connect(lambda _v: self.update_preview())
      ## The frame previewed (0..frames - 1, or closed).
      self.frame = QtWidgets.QComboBox()
      self.frame.activated.connect(lambda _i: self.update_preview())
      ## The picture.
      self.view = PixelView(PREVIEW_ZOOM)
      ## What the picture shows.
      self.where = QtWidgets.QLabel()
      self.where.setWordWrap(True)
      wl = QtWidgets.QFormLayout()
      world_row = QtWidgets.QHBoxLayout()
      world_row.addWidget(self.world_box, 1)
      world_row.addWidget(button("...", lambda: self.browse_world(), "Preview on another world's map"))
      wl.addRow("World", world_row)
      wl.addRow("Map", self.map_box)
      cell = QtWidgets.QHBoxLayout()
      cell.addWidget(self.cell_x)
      cell.addWidget(self.cell_y)
      cell.addWidget(button("Bound cell", lambda: self.find_cell(), "The map's first cell bound to this door "
                                                                    "(a warp's door, or a bound metatile)"))
      wl.addRow("Anchor cell", cell)
      wl.addRow("Frame", self.frame)
      right = QtWidgets.QVBoxLayout()
      right.addLayout(wl)
      right.addWidget(self.view, 1)
      right.addWidget(self.where)
      ## Playback timer (drawn from elapsed time, so no drift).
      self.timer = QtCore.QTimer(self)
      self.timer.setInterval(TICK_MS)
      self.timer.timeout.connect(lambda: self._tick())
      ## Time since playback started.
      self.clock = QtCore.QElapsedTimer()

      lay = QtWidgets.QHBoxLayout(self)
      for part, stretch in ((left, LIST_STRETCH), (mid, FORM_STRETCH), (right, PREVIEW_STRETCH)):
         w = QtWidgets.QWidget()
         w.setLayout(part)
         lay.addWidget(w, stretch)

   # -- helpers ---------------------------------------------------------------------------------

   @staticmethod
   def _limits() -> dict[str, int]:
      """!The engine's door limits, or none without an engine.
      @return core.doors.limits()
      """
      try:
         return doors.limits()
      except ENGINE_ERRORS:
         return {}

   @staticmethod
   def _words(fn: Callable[[], list[str]]) -> list[str]:
      """!An engine word list, or none without an engine.
      @param fn  core.doors.shows / directions
      @return the words
      """
      try:
         return fn()
      except ENGINE_ERRORS:
         return []

   def asset(self) -> JsonDict | None:
      """!The chosen door asset.
      @return the asset, or None
      """
      a = self.doc.find(self.key) if self.key else None
      return a if a is not None and a.get("kind") == doors.KIND else None

   def compiled(self) -> JsonDict | None:
      """!The chosen door compiled.
      @return compile_door()'s result, or None (the error shows)
      """
      a = self.asset()
      if a is None:
         return None
      r = self.doc.compile_asset(a)
      self.error.setText("" if r.ok else str(r.error))
      return r.compiled if r.ok else None

   def _edit(self, label: str, fn: Callable[[Document, str], object]) -> bool:
      """!Runs an edit of the chosen door through the host (refreshed either way: a refused edit puts the widgets
      back).
      @param label  undo label
      @param fn     callable(asset manifest Document, door key): the change
      @return True when it went through
      """
      if self._filling or self.asset() is None:
         return False
      doc, key = self.doc, self.key
      ok = self.host.run_edit(label, lambda: fn(doc, key))
      self.refresh()
      return ok

   def _set(self, **fields: Any) -> bool:
      """!Sets plain fields of the door.
      @param fields  core.doors.set_fields() fields
      @return True when it went through
      """
      a = self.asset()
      if a is None or all(a.get(k) == v for k, v in fields.items()):
         return False
      def run(doc: Document, key: str) -> None:
         """!The change."""
         doors.set_fields(doc, key, **fields)
      return self._edit("Door", run)

   # -- refresh ------------------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the manifest's doors and the chosen one.
      @return None
      """
      self._filling = True
      try:
         assets = doors.doors(self.doc)
         keys = [a.get("key") for a in assets]
         self.known_sounds = doors.sound_keys(self.doc) if any(a.get("sounds") for a in assets) else None
         if self.key not in keys:
            self.key = keys[0] if keys else None
         self.list.clear()
         self.list.addItems(keys)
         if self.key in keys:
            self.list.setCurrentRow(keys.index(self.key))
         self._fill_form()
         self._fill_worlds()
      finally:
         self._filling = False
      self._fill_entries()
      self._fill_steps()
      world_path = None
      if self.world is not None:
         world_path = str(self.world.world.path)
      located = (self.key, world_path)
      if self._located_for != located:   # a new door or world: show it where it is bound
         self._located_for = located
         self.locate()
      self.update_preview()

   def locate(self) -> bool:
      """!Moves the preview to a map cell the door is bound to (the shown map first).
      @return True when one was found
      """
      if self.world is None or self.key is None:
         return False
      try:
         hit = doors.find_anchor(self.world, self.key, self.map_box.currentText() or None)
      except ENGINE_ERRORS as e:
         self.where.setText(str(e))
         return False
      if hit is None:
         self.where.setText(f"No map of this world binds {self.key} (World > Doors and draw order, or the door "
                            "of a warp): pick a map and a cell")
         return False
      name, x, y, how = hit
      self._filling = True
      try:
         self.map_box.setCurrentText(name)
         self.cell_x.setValue(x)
         self.cell_y.setValue(y)
      finally:
         self._filling = False
      self.where.setText(f"{name} {x},{y}: {how}")
      return True

   def _fill_form(self) -> None:
      """!The chosen door's fields.
      @return None
      """
      a = self.asset()
      for i in range(self.form.rowCount()):
         item = self.form.itemAt(i, QtWidgets.QFormLayout.ItemRole.FieldRole)
         if item is not None and item.widget() is not None:
            item.widget().setEnabled(a is not None)
      if a is None:
         self.error.setText("")
         self.sound_check.setText("")
         return
      w, h = doors.cells_of(a)
      self.cells_w.setValue(w)
      self.cells_h.setValue(h)
      self.layers.setValue(doors.layers_of(a))
      self.show_as.setCurrentText(doors.show_of(a))
      self.exit.setCurrentText(a.get("exit", doors.directions()[0]))
      sounds = a.get("sounds", {})
      self.open_sound.setText(sounds.get("open", ""))
      self.close_sound.setText(sounds.get("close", ""))
      doc = self.doc   # a local alias (Doxygen reads `self.doc` passed on here as a new member)
      if sounds and self.known_sounds is None:
         self.known_sounds = doors.sound_keys(doc)
      self.sound_check.setText("\n".join(doors.sound_problems(doc, a, self.known_sounds)))
      tiles = doors.show_of(a) == doors.shows()[0]
      sheet = a.get("sheet", {}) if tiles else {}
      image = sheet.get("image")
      size = sheet.get("size") or ["?", "?"]
      self.sheet.setText(f"{image} (indexed: pixels are map bank indices)" if image else
                         f"shapes, {size[0]}x{size[1]}" if tiles else "(an override door has no sheet)")
      self.frame_tiles.setValue(a.get("frame_tiles", 1) if tiles else 1)
      load = a.get("load_at", doors.load_end_word())
      self.load_end.setChecked(load == doors.load_end_word())
      self.load_at.setEnabled(tiles and load != doors.load_end_word())
      c = self.compiled()
      self.load_at.setValue(c["load_at"] if c else 0)
      for wdg in (self.frame_tiles, self.load_end):
         wdg.setEnabled(tiles)
      frames = c["frames"] if c else 1
      self.entry_frame.setRange(0, max(0, frames - 1))
      self.entry_frame.setVisible(not tiles)
      self.entry_frame_label.setVisible(not tiles)
      shown = self.frame.currentText()
      self.frame.clear()
      self.frame.addItems([doors.closed_word()] + [str(f) for f in range(frames)])
      self.frame.setCurrentText(shown if shown else str(frames - 1))
      self.reverse.setChecked(doors.is_reverse(a))

   def _fill_entries(self) -> None:
      """!The entry table: one row per cell and layer.
      @return None
      """
      a = self.asset()
      self._filling = True
      try:
         self.entries.setRowCount(0)
         if a is None:
            return
         w, h = doors.cells_of(a)
         layers = doors.layers_of(a)
         frame = self.entry_frame.value()
         self.entries.setRowCount(w * h * layers)
         labels = []
         for c in range(w * h):
            for k in range(layers):
               r = c * layers + k
               labels.append(f"cell {c} ({c % w},{c // w}) layer {k}")
               for s in range(len(doors.SLOTS)):
                  try:
                     text = doors.entry_text(doors.entry(a, c, k, s, frame))
                  except (IndexError, KeyError, TypeError, ValueError):
                     text = "?"
                  self.entries.setItem(r, s, QtWidgets.QTableWidgetItem(text))
         self.entries.setVerticalHeaderLabels(labels)
      finally:
         self._filling = False

   def _fill_steps(self) -> None:
      """!The open and close tables.
      @return None
      """
      a = self.asset()
      self._filling = True
      try:
         for which, table in self.steps.items():
            st = doors.steps(a, which) if a is not None else []
            table.setRowCount(len(st))
            for i, (frame, ticks) in enumerate(st):
               table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(frame)))
               table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(ticks)))
            table.setEnabled(a is not None and not (which == "close" and doors.is_reverse(a)))
      finally:
         self._filling = False

   def _fill_worlds(self) -> None:
      """!The worlds near the manifest (its game's), and the preview world's maps.
      @return None
      """
      chosen = self.world_box.currentData()
      self.world_box.clear()
      self.world_box.addItem(ALONE, None)
      known = []
      try:
         known = [str(p) for p in doors.worlds_near(self.doc)]
      except ENGINE_ERRORS:
         pass
      if self.world is not None and str(self.world.world.path) not in known:
         known.append(str(self.world.world.path))
      for p in known:
         self.world_box.addItem(Path(p).parent.name + "/" + Path(p).name, p)
      if chosen is None and self.world is None and known:
         chosen = known[0]   # the game's world: doors show on its maps
      at = self.world_box.findData(chosen)
      self.world_box.setCurrentIndex(max(0, at))
      self._open_world(self.world_box.currentData())

   def _open_world(self, path: str | None) -> None:
      """!Opens the preview world (read-only) and lists its maps.
      @param path  world.json, or None
      @return None
      """
      if path is None:
         self.world = None
      elif self.world is None or str(self.world.world.path) != path:
         try:
            self.world = Project.open(path)
         except (ValueError, *ENGINE_ERRORS) as e:
            self.world = None
            self.where.setText(f"cannot open {path}: {e}")
      m = self.map_box.currentText()
      self.map_box.clear()
      if self.world is not None:
         self.map_box.addItems(self.world.map_names())
         if m in self.world.map_names():
            self.map_box.setCurrentText(m)

   # -- edits -----------------------------------------------------------------------------------------

   def _picked(self) -> None:
      """!Another door in the list.
      @return None
      """
      if self._filling is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      item = self.list.currentItem()
      self.key = item.text() if item else None
      self.frame.clear()
      self.refresh()

   def _cells_changed(self) -> None:
      """!The size spins changed.
      @return None
      """
      a = self.asset()
      w, h = self.cells_w.value(), self.cells_h.value()
      if a is not None and doors.cells_of(a) != (w, h):
         self._edit("Door cells", lambda doc, key: doors.set_cells(doc, key, w, h))

   def _show_chosen(self) -> None:
      """!How frames show changed.
      @return None
      """
      show = self.show_as.currentText()
      self._edit("Door frames", lambda doc, key: doors.set_show(doc, key, show))

   def _layers_changed(self, layers: int) -> None:
      """!The map layers spin changed.
      @param layers  1-4
      @return None
      """
      a = self.asset()
      if a is not None and doors.layers_of(a) != layers:
         self._edit("Door layers", lambda doc, key: doors.set_layers(doc, key, layers))

   def _sounds_changed(self) -> None:
      """!A sound key changed.
      @return None
      """
      a = self.asset()
      if self._filling or a is None:
         return
      sounds = {"open": self.open_sound.text().strip() or None, "close": self.close_sound.text().strip() or None}
      old = a.get("sounds", {})
      if {k: v for k, v in sounds.items() if v} != old:
         self._set(sounds=sounds)

   def _load_changed(self) -> None:
      """!The load position changed.
      @return None
      """
      if self._filling is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      self._set(load_at=doors.load_end_word() if self.load_end.isChecked() else self.load_at.value())

   def _entry_edited(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!An entry was typed.
      @param item  the table cell
      @return None
      """
      a = self.asset()
      if self._filling or a is None:
         return
      layers = doors.layers_of(a)
      cell, layer = divmod(item.row(), layers)
      slot, frame = item.column(), self.entry_frame.value()
      try:
         value = doors.parse_entry(item.text())
      except ValueError as e:
         self.host.show_status(str(e))
         self._fill_entries()
         return
      self._edit("Door entry", lambda doc, key: doors.set_entry(doc, key, cell, layer, slot, value, frame))

   def _table_steps(self, which: str) -> list[list[Any]] | None:
      """!A timing table's steps as typed.
      @param which  "open" or "close"
      @return [[frame or "closed", ticks]], or None when a cell is not a number / "closed"
      """
      table = self.steps[which]
      out: list[list[Any]] = []
      for r in range(table.rowCount()):
         f = table.item(r, 0).text().strip() if table.item(r, 0) else ""
         t = table.item(r, 1).text().strip() if table.item(r, 1) else ""
         if not t.isdigit() or not (f == doors.closed_word() or f.isdigit()):
            return None
         out.append([f if f == doors.closed_word() else int(f), int(t)])
      return out

   def _steps_edited(self, which: str) -> None:
      """!A timing table was typed in.
      @param which  "open" or "close"
      @return None
      """
      if self._filling or self.asset() is None:
         return
      st = self._table_steps(which)
      if st is None:
         closed = doors.closed_word()
         self.host.show_status(f"The frame of a step is a number or {closed}; its ticks a number")
         self._fill_steps()
         return
      self._edit("Door steps", lambda doc, key: doors.set_steps(doc, key, which, st))

   def add_step(self, which: str) -> bool:
      """!Adds a step after the last (the last frame again, or closed).
      @param which  "open" or "close"
      @return True when added
      """
      a = self.asset()
      if a is None:
         return False
      st = doors.steps(a, which)
      st.append(list(st[-1]) if st else [doors.closed_word(), doors.NEW_TICKS])
      return self._edit("Door steps", lambda doc, key: doors.set_steps(doc, key, which, st))

   def remove_step(self, which: str) -> bool:
      """!Removes the chosen step (a door keeps one).
      @param which  "open" or "close"
      @return True when removed
      """
      a = self.asset()
      r = self.steps[which].currentRow()
      if a is None or r < 0:
         return False
      st = doors.steps(a, which)
      del st[r]
      return self._edit("Door steps", lambda doc, key: doors.set_steps(doc, key, which, st))

   def _reverse_toggled(self, on: bool) -> None:
      """!Close reversed on or off (off: the reversed steps become the close's own).
      @param on  reversed
      @return None
      """
      a = self.asset()
      if a is None:
         return
      value: Any = doors.reverse_word() if on else doors.steps(a, "close")
      self._edit("Door close", lambda doc, key: doors.set_steps(doc, key, "close", value))

   def choose_sheet(self, path: str | None = None) -> bool:
      """!A tiles door's sheet from an indexed PNG (asks for it when none is given).
      @param path  the palette PNG, or None to ask
      @return True when set
      """
      if self.asset() is None:
         return False
      if path is None:
         path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Indexed door sheet", "", SHEET_FILTER)
         if not path:
            return False
      return self._edit("Door sheet", lambda doc, key: doors.set_sheet_image(doc, key, path))

   def new_door(self, key: str | None = None) -> bool:
      """!Adds a door (asks its key when none is given).
      @param key  "door:NAME", or None to ask
      @return True when added
      """
      if key is None:
         key, ok = QtWidgets.QInputDialog.getText(self, "New door", "Key:", text="door:NEW DOOR")
         if not ok or not key.strip():
            return False
      key = key.strip()
      doc = self.doc
      if self.host.run_edit("New door", lambda: doors.new_door(doc, key)):
         self.key = key
         self.refresh()
         return True
      return False

   def rename_door(self, new: str | None = None) -> bool:
      """!Changes the door's key (asks when none is given).
      @param new  the new key, or None to ask
      @return True when renamed
      """
      if self.key is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename door", "Key:", text=self.key)
         if not ok or not new.strip():
            return False
      old, new = self.key, new.strip()
      doc = self.doc
      if self.host.run_edit("Rename door", lambda: doc.rename_asset(old, new)):
         self.key = new
         self.refresh()
         return True
      return False

   def delete_door(self) -> bool:
      """!Removes the door (undo brings it back).
      @return True when removed
      """
      key = self.key
      if key is None:
         return False
      doc = self.doc
      if self.host.run_edit("Delete door", lambda: doc.remove_asset(key)):
         self.key = None
         self.refresh()
         return True
      return False

   # -- preview -----------------------------------------------------------------------------------------

   def browse_world(self, path: str | None = None) -> None:
      """!Previews on another world (asks for its file when none is given).
      @param path  world.json, or None to ask
      @return None
      """
      if path is None:
         path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Preview on a world", "", WORLD_FILTER)
         if not path:
            return
      self._open_world(path)
      self.refresh()

   def _world_chosen(self) -> None:
      """!Another preview world.
      @return None
      """
      self._open_world(self.world_box.currentData())
      self.refresh()

   def _map_chosen(self) -> None:
      """!Another preview map.
      @return None
      """
      self.find_cell(quiet=True)

   def find_cell(self, quiet: bool = False) -> bool:
      """!Moves the preview to the map's first cell bound to this door.
      @param quiet  say nothing when there is none
      @return True when one was found
      """
      if self.world is None or self.key is None or not self.map_box.currentText():
         self.update_preview()
         return False
      try:
         bound = doors.bound_cells(self.world, self.map_box.currentText(), self.key)
      except ENGINE_ERRORS as e:
         bound = []
         self.where.setText(str(e))
      if bound:
         self._filling = True
         try:
            self.cell_x.setValue(bound[0][0])
            self.cell_y.setValue(bound[0][1])
         finally:
            self._filling = False
         x, y, _key, how = bound[0]
         self.where.setText(f"{self.map_box.currentText()} {x},{y}: {how}")
      elif not quiet:
         self.host.show_status(f"No cell of {self.map_box.currentText()} is bound to {self.key}")
      self.update_preview()
      return bool(bound)

   def _frame_value(self) -> Any:
      """!The frame chosen for the preview.
      @return a frame index, or "closed"
      """
      t = self.frame.currentText()
      return int(t) if t.isdigit() else doors.closed_word()

   def update_preview(self, frame: Any = None) -> None:
      """!Draws a frame: on the preview map's cell (its palettes and tiles) or alone (gray banks).
      @param frame  the frame (None: the chooser's)
      @return None
      """
      if self._filling is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      c = self.compiled()
      if c is None:
         self.view.set_image(None)
         return
      frame = self._frame_value() if frame is None else frame
      img = None
      if self.world is not None and self.map_box.currentText():
         try:
            img = doors.render_on_map(self.world, self.map_box.currentText(), self.cell_x.value(),
                                      self.cell_y.value(), c, frame)
         except ENGINE_ERRORS as e:
            self.where.setText(str(e))
      if img is None:
         img = doors.render_alone(c, frame)
      self.view.set_image(to_qimage(*img))

   def play(self, which: str) -> None:
      """!Plays the opening or closing at the GBA's frame rate.
      @param which  "open" or "close"
      @return None
      """
      a = self.asset()
      if a is None:
         return
      self.timeline = doors.timeline(a, which)
      self.clock.start()
      self.timer.start()

   def _tick(self) -> None:
      """!Shows the display frame for the elapsed time; stops on the last.
      @return None
      """
      # elapsed milliseconds -> GBA display frames (cycles elapsed / cycles per frame), in whole numbers
      n = self.clock.elapsed() * sprites.GBA_CLOCK // (sprites.GBA_FRAME_CYCLES * sprites.MS_PER_SECOND)
      if not self.timeline or n >= len(self.timeline):
         self.timer.stop()
         n = len(self.timeline) - 1
      if len(self.timeline) > 0:
         self.update_preview(self.timeline[n])

   def stop(self) -> None:
      """!Stops playback.
      @return None
      """
      self.timer.stop()
