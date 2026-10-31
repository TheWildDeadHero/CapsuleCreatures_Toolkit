"""![S6] The scene editor's Screen graphics panel (engine UC, D-33): the tiles, tilemap and palette assets a
full-screen scene loads (core.screen_graphics).

Left: the assets, with New (an empty shapes canvas, a tilemap of tile 0, a gray-ramp palette), Import PNG (an indexed
PNG becomes a tiles file beside the manifest, a tilemap and a palette, shared and flipped tiles found as the
reference games' converters do), Rename and Delete. Middle: the chosen asset's form: tiles (colour depth, sheet
columns, the canvas, its blocks and fill, the shapes as JSON, Export PNG for a paint program), a tilemap (columns,
rows, affine; a data file turned into cells; the entry to paint: tile, bank, flips, a tile step for runs) or a
palette (banks, every colour: click a swatch, type a hex colour ("#" and rrggbb) or pick one). Right: the preview,
as video memory holds the asset: tiles in a palette's bank; a tilemap drawn with a tiles asset from a first tile
(click a cell to paint it; click the tiles strip below to pick a tile); a palette's swatches. Every change goes
through the host's run_edit() and is compiled by the engine before it is kept; everything here is also a
`capsule-studio screen-gfx` command.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import engine, screen_graphics as sg
from ..panel import EditorPanel, PanelHost
from ..qtimage import to_qimage
from ..widgets import HALF, PixelView, button, set_enabled
from .content.json_edit import JsonEdit

if TYPE_CHECKING:
   from ...core.document import Document

## A parsed JSON object (an asset).
JsonDict = dict[str, Any]

## Errors meaning the engine is missing or too old, or a file cannot be read.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError, KeyError, OSError, ValueError)
## Preview zoom.
PREVIEW_ZOOM = 3
## Zoom of the tile picker strip.
PICKER_ZOOM = 2
## The palette chooser's entry for a gray ramp.
GRAY = "(gray ramp)"
## The tiles chooser's entry for none.
NO_TILES = "(none)"
## Image file filter of an indexed PNG.
PNG_FILTER = "Palette PNG (*.png);;All files (*)"
## Highest canvas side offered, pixels (a 64 x 64 cell map's image).
MAX_CANVAS = 512
## Highest stored rows of a tilemap offered.
MAX_ROWS = 256
## Pages of the form stack, by kind.
PAGES = {"tiles": 0, "tilemap": 1, "palette": 2}
## Layout stretch of the list, the form and the preview.
LIST_STRETCH, FORM_STRETCH, PREVIEW_STRETCH = 1, 2, 3
## Narrowest a swatch column gets, pixels (16 fit across the form).
SWATCH_COLUMN = 16
## Colour of the compiler's message.
ERROR_STYLE = "color: #c03030;"


class ClickView(PixelView):
   """!A PixelView that reports clicks in image pixels."""

   ## Emitted with (x, y) of the image pixel clicked.
   clicked = QtCore.Signal(int, int)

   def image_pos(self, pos: QtCore.QPoint | QtCore.QPointF) -> tuple[int, int] | None:
      """!The image pixel under a widget position.
      @param pos  widget position
      @return (x, y), or None outside the image
      """
      if self.image is None:
         return None
      zoom = self.zoom   # a local alias (Doxygen reads the base class's member read here as a new one)
      w, h = self.image.width() * zoom, self.image.height() * zoom
      left, top = (self.width() - w) // HALF, (self.height() - h) // HALF
      x, y = int(pos.x()) - left, int(pos.y()) - top
      if not 0 <= x < w or not 0 <= y < h:
         return None
      return x // zoom, y // zoom

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Reports the pixel clicked.
      @param event  the mouse event
      @return None
      """
      at = self.image_pos(event.position())
      if at is not None:
         self.clicked.emit(*at)


class ScreenGraphicsPanel(EditorPanel):
   """!Edits tiles, tilemap and palette assets (core.screen_graphics)."""

   ## See EditorPanel.panel_id.
   panel_id = "screen_graphics"
   ## See EditorPanel.title.
   title = "Screen graphics"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The chosen asset's key, or None.
      self.key = None
      ## True while widgets are being filled.
      self._filling = False

      # -- list
      ## The assets.
      self.list = QtWidgets.QListWidget()
      self.list.currentRowChanged.connect(lambda _r: self._picked())
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Tiles, tilemaps and palettes"))
      left.addWidget(self.list, 1)
      for row in ((("New tiles...", lambda: self.new_asset("tiles"), "An empty canvas of index 0 to draw shapes on"),
                   ("New tilemap...", lambda: self.new_asset("tilemap"), "32 x 32 cells of tile 0"),
                   ("New palette...", lambda: self.new_asset("palette"), "A bank of gray ramp colours")),
                  (("Import PNG...", lambda: self.import_png(),
                    "An indexed PNG becomes tiles (a file beside the manifest), a tilemap and a palette"),
                   ("Rename...", lambda: self.rename_asset(), None), ("Delete", lambda: self.delete_asset(), None))):
         line = QtWidgets.QHBoxLayout()
         for text, slot, tip in row:
            line.addWidget(button(text, slot, tip))
         left.addLayout(line)

      # -- forms
      ## The form of each kind.
      self.forms = QtWidgets.QStackedWidget()
      self.forms.addWidget(self._tiles_form())
      self.forms.addWidget(self._tilemap_form())
      self.forms.addWidget(self._palette_form())
      ## Compiler message.
      self.error = QtWidgets.QLabel()
      self.error.setWordWrap(True)
      self.error.setStyleSheet(ERROR_STYLE)
      mid = QtWidgets.QVBoxLayout()
      mid.addWidget(self.forms, 1)
      mid.addWidget(self.error)

      # -- preview
      ## The palette tiles are drawn in.
      self.palette_box = QtWidgets.QComboBox()
      self.palette_box.activated.connect(lambda _i: self.update_preview())
      ## A 4bpp sheet's bank.
      self.bank = QtWidgets.QSpinBox()
      self.bank.setRange(0, sg.MAX_BANK)
      self.bank.valueChanged.connect(lambda _v: self.update_preview())
      ## The tiles a tilemap is drawn with.
      self.tiles_box = QtWidgets.QComboBox()
      self.tiles_box.activated.connect(lambda _i: self.update_preview())
      ## The tile number of those tiles' first (a layer's load position).
      self.first_tile = QtWidgets.QSpinBox()
      self.first_tile.setRange(0, sg.MAX_TILE)
      self.first_tile.setToolTip("The tile number the tiles' first tile has (where a layer loads them)")
      self.first_tile.valueChanged.connect(lambda _v: self.update_preview())
      ## Zoom.
      self.zoom = QtWidgets.QSpinBox()
      self.zoom.setRange(1, PREVIEW_ZOOM * PREVIEW_ZOOM)
      self.zoom.setValue(PREVIEW_ZOOM)
      self.zoom.valueChanged.connect(lambda v: self.view.set_zoom(v))
      ## The picture.
      self.view = ClickView(PREVIEW_ZOOM)
      self.view.clicked.connect(lambda x, y: self._view_clicked(x, y))
      ## The tile picker (a tilemap's tiles, click one to paint with it).
      self.picker = ClickView(PICKER_ZOOM)
      self.picker.clicked.connect(lambda x, y: self._picker_clicked(x, y))
      self.picker.setToolTip("Click a tile to paint with it")
      opts = QtWidgets.QFormLayout()
      opts.addRow("Palette", self.palette_box)
      opts.addRow("Bank", self.bank)
      opts.addRow("Tiles", self.tiles_box)
      opts.addRow("First tile", self.first_tile)
      opts.addRow("Zoom", self.zoom)
      area = QtWidgets.QScrollArea()
      area.setWidgetResizable(True)
      area.setWidget(self.view)
      right = QtWidgets.QVBoxLayout()
      right.addLayout(opts)
      right.addWidget(area, 1)
      right.addWidget(self.picker)

      lay = QtWidgets.QHBoxLayout(self)
      lay.addLayout(left, LIST_STRETCH)
      lay.addLayout(mid, FORM_STRETCH)
      lay.addLayout(right, PREVIEW_STRETCH)
      self.refresh()

   # -- forms ---------------------------------------------------------------------------------------------------

   def _spin(self, lo: int, hi: int, slot: Callable[[int], object]) -> QtWidgets.QSpinBox:
      """!A spin box that commits on Enter, the arrows or leaving it.
      @param lo    lowest value
      @param hi    highest value
      @param slot  called with the value
      @return the box
      """
      s = QtWidgets.QSpinBox()
      s.setRange(lo, hi)
      s.setKeyboardTracking(False)
      s.valueChanged.connect(lambda v: None if self._filling else slot(v))
      return s

   def _tiles_form(self) -> QtWidgets.QWidget:
      """!The tiles form.
      @return its widget
      """
      w = QtWidgets.QWidget()
      ## Where the tiles come from.
      self.tiles_source = QtWidgets.QLabel()
      self.tiles_source.setWordWrap(True)
      ## Colour depth.
      self.bpp = QtWidgets.QComboBox()
      self.bpp.addItem("4bpp (16 colours, a bank)", sg.BPP4)
      self.bpp.addItem("8bpp (256 colours)", sg.BPP8)
      self.bpp.activated.connect(lambda _i: self._set(bpp=self.bpp.currentData()))
      ## Tiles per row of the sheet (0: not an image's rows).
      self.columns = self._spin(0, sg.BYTE_MASK, lambda v: self._set(columns=v or None))
      self.columns.setSpecialValueText("(not recorded)")
      ## Canvas width and height.
      self.canvas_w = self._spin(sg.TILE, MAX_CANVAS, lambda v: self._set(width=v))
      ## Canvas height.
      self.canvas_h = self._spin(sg.TILE, MAX_CANVAS, lambda v: self._set(height=v))
      for s in (self.canvas_w, self.canvas_h):
         s.setSingleStep(sg.TILE)
      ## The canvas's fill index.
      self.fill = self._spin(0, sg.MAX_INDEX_8BPP, lambda v: self._set(fill=v))
      ## Cut by blocks.
      self.use_block = QtWidgets.QCheckBox("cut by blocks (sprite frames)")
      self.use_block.clicked.connect(lambda on: self._block_changed())
      ## Block columns and rows.
      self.block_w = self._spin(1, MAX_CANVAS // sg.TILE, lambda _v: self._block_changed())
      ## Block rows.
      self.block_h = self._spin(1, MAX_CANVAS // sg.TILE, lambda _v: self._block_changed())
      ## The shapes.
      self.shapes = JsonEdit(lambda v: self._edit("Tile shapes", lambda doc, key: sg.set_shapes(doc, key, v)))
      self.shapes.setToolTip("asset_compiler's shapes (rect, frame, circle, ring, ellipse, gradients, stripes, "
                             "checker, dots ...) drawn in order with palette indices")
      size = QtWidgets.QHBoxLayout()
      size.addWidget(self.canvas_w)
      size.addWidget(QtWidgets.QLabel("x"))
      size.addWidget(self.canvas_h)
      size.addWidget(QtWidgets.QLabel("pixels"))
      block = QtWidgets.QHBoxLayout()
      block.addWidget(self.use_block)
      block.addWidget(self.block_w)
      block.addWidget(QtWidgets.QLabel("x"))
      block.addWidget(self.block_h)
      block.addWidget(QtWidgets.QLabel("tiles"))
      f = QtWidgets.QFormLayout(w)
      f.addRow("Source", self.tiles_source)
      f.addRow("Colours", self.bpp)
      f.addRow("Sheet columns", self.columns)
      f.addRow("Canvas", size)
      f.addRow("Fill index", self.fill)
      f.addRow("Blocks", block)
      f.addRow("Shapes", self.shapes)
      f.addRow("", button("Export PNG...", lambda: self.export_png(),
                          "The sheet as an indexed PNG in the preview's palette (import it back after painting)"))
      return w

   def _tilemap_form(self) -> QtWidgets.QWidget:
      """!The tilemap form.
      @return its widget
      """
      w = QtWidgets.QWidget()
      ## Where the entries come from, and the data file's button.
      self.map_source = QtWidgets.QLabel()
      self.map_source.setWordWrap(True)
      ## Turns a data file into cells.
      self.to_cells = button("Turn into cells", lambda: self.make_cells(),
                             "Copy the file's entries into the manifest, so they can be painted (the file stays)")
      ## Entries a stored row.
      self.map_columns = self._spin(1, sg.BYTE_MASK, lambda v: self._set(columns=None if v == sg.ROW_CELLS else v))
      ## Stored rows.
      self.map_rows = self._spin(1, MAX_ROWS, lambda v: self._edit("Tilemap rows",
                                                                   lambda doc, key: sg.set_rows(doc, key, v)))
      ## One tile byte a cell.
      self.affine = QtWidgets.QCheckBox("affine (one tile byte a cell, 8bpp tiles)")
      self.affine.clicked.connect(lambda on: self._set(affine=True if on else None))
      ## The entry painted: tile, bank, flips, step.
      self.paint_tile = QtWidgets.QSpinBox()
      self.paint_tile.setRange(0, sg.MAX_TILE)
      ## Bank painted.
      self.paint_bank = QtWidgets.QSpinBox()
      self.paint_bank.setRange(0, sg.MAX_BANK)
      ## Flips painted.
      self.paint_h = QtWidgets.QCheckBox("h-flip")
      ## Vertical flip.
      self.paint_v = QtWidgets.QCheckBox("v-flip")
      ## Painted rectangle.
      self.paint_w = QtWidgets.QSpinBox()
      ## Its rows.
      self.paint_hgt = QtWidgets.QSpinBox()
      for s in (self.paint_w, self.paint_hgt):
         s.setRange(1, sg.ROW_CELLS * HALF)
      ## Tile step per painted cell.
      self.paint_step = QtWidgets.QSpinBox()
      self.paint_step.setRange(0, sg.MAX_TILE)
      self.paint_step.setToolTip("0: the same tile everywhere; 1: a run of tiles, cell by cell, row by row")
      ## The entry as text.
      self.paint_text = QtWidgets.QLabel()
      for s in (self.paint_tile, self.paint_bank, self.paint_w, self.paint_hgt, self.paint_step):
         s.valueChanged.connect(lambda _v: self._paint_changed())
      for c in (self.paint_h, self.paint_v):
         c.toggled.connect(lambda _on: self._paint_changed())
      src = QtWidgets.QHBoxLayout()
      src.addWidget(self.map_source, 1)
      src.addWidget(self.to_cells)
      entry = QtWidgets.QHBoxLayout()
      for label, wid in (("tile", self.paint_tile), ("bank", self.paint_bank)):
         entry.addWidget(QtWidgets.QLabel(label))
         entry.addWidget(wid)
      entry.addWidget(self.paint_h)
      entry.addWidget(self.paint_v)
      rect = QtWidgets.QHBoxLayout()
      rect.addWidget(self.paint_w)
      rect.addWidget(QtWidgets.QLabel("x"))
      rect.addWidget(self.paint_hgt)
      rect.addWidget(QtWidgets.QLabel("cells, tile step"))
      rect.addWidget(self.paint_step)
      f = QtWidgets.QFormLayout(w)
      f.addRow("Source", src)
      f.addRow("Columns", self.map_columns)
      f.addRow("Rows", self.map_rows)
      f.addRow("", self.affine)
      f.addRow("Paint", entry)
      f.addRow("Rectangle", rect)
      f.addRow("Entry", self.paint_text)
      hint = QtWidgets.QLabel("Click a cell of the preview to paint the entry there; click the tiles strip to pick "
                              "a tile.")
      hint.setWordWrap(True)
      f.addRow(hint)
      return w

   def _palette_form(self) -> QtWidgets.QWidget:
      """!The palette form.
      @return its widget
      """
      w = QtWidgets.QWidget()
      try:
         most_banks = sg.max_colors() // sg.BANK_SIZE
      except ENGINE_ERRORS:
         most_banks = sg.BANKS
      ## Banks.
      self.banks = self._spin(1, most_banks, lambda v: self._edit(
         "Palette banks", lambda doc, key: sg.set_banks(doc, key, v)))
      ## The colours: a row per bank.
      self.swatches = QtWidgets.QTableWidget(0, sg.BANK_SIZE)
      self.swatches.setHorizontalHeaderLabels([str(i) for i in range(sg.BANK_SIZE)])
      self.swatches.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.swatches.horizontalHeader().setMinimumSectionSize(SWATCH_COLUMN)
      self.swatches.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
      self.swatches.currentCellChanged.connect(lambda *_a: self._swatch_picked())
      self.swatches.cellDoubleClicked.connect(lambda _r, _c: self.pick_color())
      ## The chosen colour as a hex colour ("#" and rrggbb).
      self.color_text = QtWidgets.QLineEdit()
      self.color_text.setPlaceholderText("#rrggbb")
      self.color_text.editingFinished.connect(lambda: self._color_typed())
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.color_text)
      row.addWidget(button("Pick...", lambda: self.pick_color(), "Choose the colour (5 bits a channel are kept)"))
      f = QtWidgets.QFormLayout(w)
      f.addRow("Banks", self.banks)
      f.addRow(self.swatches)
      f.addRow("Colour", row)
      note = QtWidgets.QLabel("Entry 0 of a bank is transparent for tiles and sprites; a BG bank 0's entry 0 is the "
                              "backdrop.")
      note.setWordWrap(True)
      f.addRow(note)
      return w

   # -- filling -------------------------------------------------------------------------------------------------

   def asset(self) -> JsonDict | None:
      """!The chosen asset.
      @return it, or None
      """
      doc = self.doc
      if doc is None or self.key is None:
         return None
      a = doc.find(self.key)
      return a if a is not None and a.get("kind") in sg.KINDS else None

   def refresh(self) -> None:
      """!Re-reads the assets and the chosen one.
      @return None
      """
      doc = self.doc
      self._filling = True
      try:
         self.list.clear()
         items = sg.graphics(doc) if doc is not None else []
         for a in items:
            self.list.addItem(str(a.get("key")))
         keys = [str(a.get("key")) for a in items]
         if self.key not in keys:
            self.key = keys[0] if keys else None
         if self.key is not None:
            self.list.setCurrentRow(keys.index(self.key))
         self._fill_choosers(doc)
      finally:
         self._filling = False
      self._fill_form()

   def _fill_choosers(self, doc: Document | None) -> None:
      """!The palette and tiles choosers, keeping their choice.
      @param doc  the manifest, or None
      @return None
      """
      for box, kind, none in ((self.palette_box, "palette", GRAY), (self.tiles_box, "tiles", NO_TILES)):
         keep = box.currentData()
         box.clear()
         box.addItem(none, None)
         for k in (sg.keys(doc, kind) if doc is not None else []):
            box.addItem(k, k)
         i = box.findData(keep)
         if i < 0 and box.count() > 1:
            i = 1   # the first asset, until one is picked
         box.setCurrentIndex(max(0, i))

   def _fill_form(self) -> None:
      """!The chosen asset's form.
      @return None
      """
      a = self.asset()
      set_enabled(self.forms, a is not None)   # greyed, read-only; its tables and text still scroll
      if a is None:
         self.error.setText("")
         self.view.set_image(None)
         self.picker.set_image(None)
         return
      self._filling = True
      try:
         kind = a["kind"]
         self.forms.setCurrentIndex(PAGES[kind])
         r = self.doc.compile_asset(a)
         self.error.setText("" if r.ok else str(r.error))
         if kind == "tiles":
            self._fill_tiles(a)
         elif kind == "tilemap":
            self._fill_tilemap(a, r.compiled)
         else:
            self._fill_palette(r.compiled)
         self.bank.setEnabled(kind == "tiles")
         self.tiles_box.setEnabled(kind == "tilemap")
         self.first_tile.setEnabled(kind == "tilemap")
      finally:
         self._filling = False
      self._paint_changed()
      self.update_preview()

   def _fill_tiles(self, a: JsonDict) -> None:
      """!The tiles form.
      @param a  tiles asset
      @return None
      """
      data = "data" in a
      self.tiles_source.setText(f"data file {a['data']}" if data else "shapes drawn on a canvas")
      self.bpp.setCurrentIndex(self.bpp.findData(a.get("bpp", sg.BPP4)))
      self.columns.setValue(int(a.get("columns", 0)))
      for wid in (self.canvas_w, self.canvas_h, self.fill, self.use_block, self.block_w, self.block_h):
         wid.setEnabled(not data)
      self.shapes.set_editable(not data)   # greyed out, but its text still scrolls
      self.canvas_w.setValue(int(a.get("width", sg.TILE)))
      self.canvas_h.setValue(int(a.get("height", sg.TILE)))
      self.fill.setValue(int(a.get("fill", 0)))
      block = a.get("block")
      self.use_block.setChecked(isinstance(block, list))
      if isinstance(block, list):
         self.block_w.setValue(int(block[0]))
         self.block_h.setValue(int(block[1]))
      self.shapes.set_read_only("a data file's tiles have no shapes" if data else None)
      self.shapes.set_value(a.get("shapes", []))

   def _fill_tilemap(self, a: JsonDict, rec: JsonDict | None) -> None:
      """!The tilemap form.
      @param a    tilemap asset
      @param rec  its compiled record, or None
      @return None
      """
      data = "data" in a
      self.map_source.setText(f"data file {a['data']}" if data else "cells in the manifest")
      self.to_cells.setEnabled(data and rec is not None)
      self.map_columns.setValue(sg.map_columns(a))
      count = len(a.get("cells", [])) if not data else (rec["count"] if rec else 0)
      self.map_rows.setValue(max(1, -(-count // sg.map_columns(a))))
      self.map_rows.setEnabled(not data)
      self.affine.setChecked(bool(a.get("affine")))

   def _fill_palette(self, rec: JsonDict | None) -> None:
      """!The palette form.
      @param rec  the compiled palette, or None
      @return None
      """
      colors = rec["colors"] if rec else []
      banks = max(1, -(-len(colors) // sg.BANK_SIZE))
      self.banks.setValue(banks)
      row, col = self.swatches.currentRow(), self.swatches.currentColumn()
      self.swatches.setRowCount(banks)
      self.swatches.setVerticalHeaderLabels([f"bank {b}" for b in range(banks)])
      for i in range(banks * sg.BANK_SIZE):
         item = QtWidgets.QTableWidgetItem()
         if i < len(colors):
            item.setBackground(QtGui.QColor(*sg.bgr_to_rgb(colors[i])))
            item.setToolTip(f"entry {i}: {sg.hex_of(colors[i])}")
         else:
            item.setToolTip(f"entry {i}: not given")
         self.swatches.setItem(i // sg.BANK_SIZE, i % sg.BANK_SIZE, item)
      self.swatches.setCurrentCell(max(0, row), max(0, col))
      self._swatch_picked()

   # -- edits ---------------------------------------------------------------------------------------------------

   def _edit(self, label: str, fn: Callable[[Document, str], object]) -> bool:
      """!One undo step on the chosen asset.
      @param label  undo label
      @param fn     callable(doc, key)
      @return True when it went through
      """
      doc, key = self.doc, self.key
      if doc is None or key is None or self._filling:
         return False
      ok = self.host.run_edit(label, lambda: fn(doc, key))
      if not ok:
         self._fill_form()
      return ok

   def _set(self, **fields: Any) -> bool:
      """!Sets fields of the chosen asset.
      @param fields  the fields (None removes one)
      @return True when kept
      """
      return self._edit("Set " + ", ".join(fields), lambda doc, key: sg.set_fields(doc, key, **fields))

   def _block_changed(self) -> bool:
      """!The block check box or size.
      @return True when kept
      """
      if self.use_block.isChecked():
         return self._set(block=[self.block_w.value(), self.block_h.value()])
      return self._set(block=None)

   def make_cells(self) -> bool:
      """!The chosen tilemap's data file becomes cells.
      @return True when done
      """
      return self._edit("Tilemap to cells", lambda doc, key: sg.to_cells(doc, key))

   def entry(self) -> int:
      """!The entry the paint controls make.
      @return the map entry (an affine map's tile byte)
      """
      a = self.asset()
      if a is not None and a.get("affine"):
         return self.paint_tile.value() & sg.BYTE_MASK
      return sg.make_entry(self.paint_tile.value(), self.paint_bank.value(), self.paint_h.isChecked(),
                           self.paint_v.isChecked())

   def _paint_changed(self) -> None:
      """!The paint controls changed: the entry's text.
      @return None
      """
      a = self.asset()
      affine = bool(a and a.get("affine"))
      self.paint_text.setText(f"{sg.entry_text(self.entry(), affine)} (0x{self.entry():04X})")

   def paint_at(self, x: int, y: int) -> bool:
      """!Paints the entry at a cell of the chosen tilemap (its rectangle from there).
      @param x  column
      @param y  row
      @return True when painted
      """
      a = self.asset()
      if a is None or a.get("kind") != "tilemap" or "cells" not in a:
         if a is not None and a.get("kind") == "tilemap":
            self.host.show_status("This tilemap reads a data file: Turn into cells first to paint it")
         return False
      entry, w, h, step = self.entry(), self.paint_w.value(), self.paint_hgt.value(), self.paint_step.value()
      columns = sg.map_columns(a)
      rows = -(-len(a["cells"]) // columns)
      w, h = min(w, columns - x), min(h, rows - y)
      return self._edit("Paint tilemap", lambda doc, key: sg.paint(doc, key, x, y, entry, w, h, step))

   def _view_clicked(self, x: int, y: int) -> None:
      """!A click on the preview: a tilemap's cell is painted; a palette's swatch is picked.
      @param x  image x
      @param y  image y
      @return None
      """
      a = self.asset()
      if a is None:
         return
      if a["kind"] == "tilemap":
         self.paint_at(x // sg.TILE, y // sg.TILE)
      elif a["kind"] == "palette":
         self.swatches.setCurrentCell(y // sg.SWATCH, x // sg.SWATCH)

   def _picker_clicked(self, x: int, y: int) -> None:
      """!A click on the tiles strip picks the tile to paint.
      @param x  image x
      @param y  image y
      @return None
      """
      img = self.picker.image
      if img is None:
         return
      columns = max(1, img.width() // sg.TILE)
      self.paint_tile.setValue(self.first_tile.value() + (y // sg.TILE) * columns + x // sg.TILE)

   def _swatch_picked(self) -> None:
      """!Another swatch: its colour in the text box.
      @return None
      """
      rec = self.doc.compile_asset(self.asset()).compiled if self.asset() is not None else None
      i = self.swatches.currentRow() * sg.BANK_SIZE + self.swatches.currentColumn()
      colors = rec["colors"] if rec and rec.get("colors") is not None else []
      self.color_text.setText(sg.hex_of(colors[i]) if 0 <= i < len(colors) else "")

   def set_color(self, text: str) -> bool:
      """!The chosen swatch's colour.
      @param text  a hex colour ("#" and rrggbb) or a BGR555 number
      @return True when kept
      """
      i = self.swatches.currentRow() * sg.BANK_SIZE + self.swatches.currentColumn()
      if i < 0:
         return False
      value: Any = text.strip()
      if not value.startswith("#"):
         try:
            value = int(value, 0)
         except ValueError:
            self.host.show_status(f"{text!r}: a colour is #rrggbb or a BGR555 number")
            return False
      return self._edit("Set colour", lambda doc, key: sg.set_color(doc, key, i, value))

   def _color_typed(self) -> None:
      """!The colour text was edited.
      @return None
      """
      if self.color_text.isModified():
         self.color_text.setModified(False)
         self.set_color(self.color_text.text())

   def pick_color(self) -> bool:
      """!Picks the chosen swatch's colour in a dialog.
      @return True when changed
      """
      current = QtGui.QColor(self.color_text.text() or "#000000")
      c = QtWidgets.QColorDialog.getColor(current, self, "Palette colour")
      if not c.isValid():
         return False
      return self.set_color(f"#{c.red():02x}{c.green():02x}{c.blue():02x}")

   # -- the list ------------------------------------------------------------------------------------------------

   def _picked(self) -> None:
      """!Another asset.
      @return None
      """
      if self._filling:
         return
      item = self.list.currentItem()
      self.key = item.text() if item is not None else None
      self._fill_form()

   def new_asset(self, kind: str, name: str | None = None) -> bool:
      """!Adds an asset of a kind (asks its name when none is given).
      @param kind  tiles, tilemap or palette
      @param name  NAME, or None to ask
      @return True when added
      """
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, f"New {kind}", "Name:", text="NEW")
         if not ok or not name.strip():
            return False
      key = sg.full_key(kind, name.strip())
      doc = self.doc
      makers = {"tiles": sg.new_tiles, "tilemap": sg.new_tilemap, "palette": sg.new_palette}
      if self.host.run_edit(f"New {kind}", lambda: makers[kind](doc, key)):
         self.key = key
         self.refresh()
         return True
      return False

   def import_png(self, path: str | None = None, name: str | None = None, make_map: bool = True) -> bool:
      """!Imports an indexed PNG as tiles, a tilemap and a palette (asks for the file and name when not given).
      @param path      the palette PNG, or None to ask
      @param name      NAME, or None to ask
      @param make_map  add a tilemap (else the tiles stay in reading order: a sprite sheet)
      @return True when imported
      """
      if path is None:
         path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Import indexed PNG", "", PNG_FILTER)
         if not path:
            return False
         choice, ok = QtWidgets.QInputDialog.getItem(
            self, "Import indexed PNG", "Import as:", ["a screen background (tiles, tilemap, palette)",
                                                      "sprite frames (tiles in reading order, palette)"], 0, False)
         if not ok:
            return False
         make_map = choice.startswith("a screen")
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Import indexed PNG", "Name:",
                                                   text=Path(path).stem.upper())
         if not ok or not name.strip():
            return False
      doc, added = self.doc, []
      if self.host.run_edit("Import screen graphics",
                            lambda: added.extend(sg.import_png(doc, name.strip(), path, make_map=make_map))):
         self.key = added[0] if added else self.key
         self.refresh()
         self.host.show_status("Imported " + ", ".join(added))
         return True
      return False

   def export_png(self, path: str | None = None) -> bool:
      """!Writes the chosen tiles as an indexed PNG in the preview's palette and bank.
      @param path  the PNG, or None to ask
      @return True when written
      """
      a = self.asset()
      if a is None or a.get("kind") != "tiles":
         return False
      if path is None:
         path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Export tiles", a["key"].split(":", 1)[-1].lower()
                                                          + ".png", PNG_FILTER)
         if not path:
            return False
      try:
         doc = self.doc   # a local alias (see image_pos())
         sg.export_png(doc, a["key"], path, self.palette_box.currentData(), self.bank.value())
      except ENGINE_ERRORS as e:
         self.host.show_status(str(e))
         return False
      self.host.show_status(f"Wrote {path}")
      return True

   def rename_asset(self, new: str | None = None) -> bool:
      """!Changes the asset's key (asks when none is given).
      @param new  the new key, or None to ask
      @return True when renamed
      """
      if self.key is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Key:", text=self.key)
         if not ok or not new.strip():
            return False
      old, new = self.key, new.strip()
      doc = self.doc
      if self.host.run_edit("Rename asset", lambda: doc.rename_asset(old, new)):
         self.key = new
         self.refresh()
         return True
      return False

   def delete_asset(self) -> bool:
      """!Removes the asset (undo brings it back; a data file stays on disk).
      @return True when removed
      """
      key = self.key
      if key is None:
         return False
      doc = self.doc
      if self.host.run_edit("Delete asset", lambda: doc.remove_asset(key)):
         self.key = None
         self.refresh()
         return True
      return False

   # -- preview -------------------------------------------------------------------------------------------------

   def update_preview(self) -> None:
      """!Draws the chosen asset (and a tilemap's tile strip).
      @return None
      """
      a = self.asset()
      if a is None:
         return
      tiles_key = self.tiles_box.currentData()
      try:
         img = sg.preview(self.doc, a["key"], self.palette_box.currentData(), self.bank.value(), tiles_key,
                          self.first_tile.value())
      except ENGINE_ERRORS as e:
         self.view.set_image(None)
         self.error.setText(str(e))
         return
      self.view.set_image(to_qimage(*img))
      strip = None
      t = self.doc.find(tiles_key) if a["kind"] == "tilemap" and tiles_key else None
      if t is not None and t.get("kind") == "tiles":
         try:   # the tiles in number order (the picker counts them so), in the painted bank
            rec = sg.check(self.doc, t)
            strip = sg.render_tiles(sg.decode_tiles(rec), sg.palette_colors(self.doc, self.palette_box.currentData()),
                                    self.paint_bank.value(), rec["bpp"], sg.DEFAULT_SHEET_COLUMNS)
         except ENGINE_ERRORS:
            strip = None
      self.picker.setVisible(strip is not None)
      self.picker.set_image(to_qimage(*strip) if strip is not None else None)
