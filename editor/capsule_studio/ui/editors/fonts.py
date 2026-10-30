"""!Font panel [S2] (engine I4: capsule.font/2 proportional fonts): the fonts an asset manifest reaches (its font
assets and its tables' fonts), viewed and edited.

Left: the font and its glyph grid (each glyph as the engine draws it, with its character and code). Middle: the
chosen glyph's pixels at a large zoom (click or drag paints the chosen pixel value: transparent, ink, shadow or
fill; the advance width is the line across the cell), its width, Add / Remove glyph. Right: the font's metrics
(cell, line height, letter spacing; S6b, engine C13a: the glyph height, the rows a window draws of each glyph, 0 the
whole cell), the compiler's verdict (core.fonts.problem(): compile_proportional() for the
game's code page), the page's characters the font lacks, and a preview of a text in the font
(core.text_render.render_text()).

S6b (C13a, as the handheld games copy a glyph): a window draws only a glyph's advance width's columns and the glyph
height's rows, so the editor and the grid show the pixels past them darker (kept in the font, never drawn), the
editor marks the glyph height with a line across, and the preview draws as the engine does.

A stroke (press, drag, release) is one undo step of the font's Document; the font is saved with the manifest
(extra_documents()) and the text tables are fitted with its edited data at once (the shared TextSession).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import engine, fonts, text_render
from ...core.document import Document, DocumentError
from ..panel import EditorPanel
from ..qtimage import to_qimage
from ..widgets import PixelView, button
from .text_common import session_of

if TYPE_CHECKING:
   from ..panel import PanelHost
   from .text_common import TextSession

## Names of the pixel values (font_compiler.PIXEL_DIGITS order).
PIXEL_NAMES = ["transparent", "ink", "shadow", "fill"]
## Colours of the pixel values in the glyph editor (transparent as a light check colour).
PIXEL_COLORS = [(232, 232, 236), (40, 40, 48), (150, 150, 160), (255, 255, 255)]
## Screen pixels per glyph pixel in the editor.
EDIT_ZOOM = 16
## Screen pixels per glyph pixel in the grid's icons.
ICON_ZOOM = 2
## Screen pixels per preview pixel.
PREVIEW_ZOOM = 3
## How much darker (percent, Qt's darker()) a pixel past the advance width is shown.
PAST_WIDTH_DARKER = 115
## Colour of the advance width line.
WIDTH_LINE_COLOR = "#d04040"
## S6b: colour of the glyph height line (the last row a window draws).
HEIGHT_LINE_COLOR = "#3070d0"
## Colour of the grid lines between pixels.
GRID_LINE_COLOR = "#b0b0b8"
## The preview's sample text.
SAMPLE_TEXT = "The quick brown fox jumps over the lazy dog."
## Pixels around the preview's text.
PREVIEW_MARGIN = 2
## Stretch of the grid column, the editor column and the settings column.
GRID_STRETCH, EDITOR_STRETCH, SETTINGS_STRETCH = 3, 3, 2
## Pixels of the grid icons' padding around a glyph.
ICON_PAD = 2
## Characters of the missing list shown.
MISSING_SHOWN = 80


def glyph_image(rows: list[str], width: int, zoom: int, drawn_rows: int | None = None) -> QtGui.QImage:
   """!A glyph's rows as an image (PIXEL_COLORS), the pixels a window does not draw (past its advance width, S6b: below
   the font's glyph height) darker.
   @param rows        pixel digit strings
   @param width       advance width
   @param zoom        pixels per glyph pixel
   @param drawn_rows  rows a window draws (fonts.drawn_rows()), or None for every row
   @return QImage
   """
   h = len(rows)
   w = len(rows[0]) if rows else 0
   img = QtGui.QImage(max(w, 1) * zoom, max(h, 1) * zoom, QtGui.QImage.Format.Format_RGB32)
   img.fill(QtGui.QColor(*PIXEL_COLORS[0]))
   painter = QtGui.QPainter(img)
   for y, row in enumerate(rows):
      for x, digit in enumerate(row):
         v = int(digit) if digit.isdigit() and int(digit) < len(PIXEL_COLORS) else 0
         color = QtGui.QColor(*PIXEL_COLORS[v])
         if x >= width or (drawn_rows is not None and y >= drawn_rows):
            color = color.darker(PAST_WIDTH_DARKER)   # past the advance or the glyph height: kept, never drawn
         painter.fillRect(x * zoom, y * zoom, zoom, zoom, color)
   painter.end()
   return img


class GlyphCanvas(QtWidgets.QWidget):
   """!A glyph's pixels at a large zoom; a stroke paints the panel's pixel value."""

   def __init__(self, panel: FontPanel) -> None:
      """!Creates the canvas.
      @param panel  the font panel (its glyph, value and edits)
      """
      super().__init__(panel)
      ## The panel.
      self.panel = panel
      ## The rows shown (the stroke's changes included).
      self.rows = []
      ## The advance width.
      self.width_px = 0
      ## S6b: the rows a window draws (the font's glyph height), or None for every row.
      self.drawn_rows = None
      ## Whether a stroke is going on.
      self.stroking = False
      self.setMouseTracking(False)

   def set_glyph(self, rows: list[str], width: int, drawn_rows: int | None = None) -> None:
      """!Shows a glyph.
      @param rows        its rows
      @param width       its advance
      @param drawn_rows  S6b: the rows a window draws, or None for every row
      @return None
      """
      self.rows = list(rows)
      self.width_px = width
      self.drawn_rows = drawn_rows
      self.resize(self.sizeHint())   # the scroll area does not resize it
      self.update()

   def sizeHint(self) -> QtCore.QSize:
      """!The glyph at the editor's zoom.
      @return QSize
      """
      w = len(self.rows[0]) if self.rows else 1
      return QtCore.QSize(w * EDIT_ZOOM + 1, max(len(self.rows), 1) * EDIT_ZOOM + 1)

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the pixels, the grid and the width line.
      @param event  QPaintEvent
      @return None
      """
      painter = QtGui.QPainter(self)
      painter.drawImage(0, 0, glyph_image(self.rows, self.width_px, EDIT_ZOOM, self.drawn_rows))
      painter.setPen(QtGui.QColor(GRID_LINE_COLOR))
      h = len(self.rows)
      w = len(self.rows[0]) if self.rows else 0
      for x in range(w + 1):
         painter.drawLine(x * EDIT_ZOOM, 0, x * EDIT_ZOOM, h * EDIT_ZOOM)
      for y in range(h + 1):
         painter.drawLine(0, y * EDIT_ZOOM, w * EDIT_ZOOM, y * EDIT_ZOOM)
      pen = QtGui.QPen(QtGui.QColor(WIDTH_LINE_COLOR))
      pen.setWidth(ICON_ZOOM)
      painter.setPen(pen)
      painter.drawLine(self.width_px * EDIT_ZOOM, 0, self.width_px * EDIT_ZOOM, h * EDIT_ZOOM)
      limit = self.drawn_rows   # a local alias (Doxygen 1.12 reads `if self.x ...:` as a new member)
      if limit is not None and limit < h:
         pen.setColor(QtGui.QColor(HEIGHT_LINE_COLOR))
         painter.setPen(pen)
         painter.drawLine(0, limit * EDIT_ZOOM, w * EDIT_ZOOM, limit * EDIT_ZOOM)
      painter.end()

   def _paint_at(self, pos: QtCore.QPoint) -> None:
      """!Paints the pixel under a point (in the stroke's rows).
      @param pos  widget position
      @return None
      """
      x, y = pos.x() // EDIT_ZOOM, pos.y() // EDIT_ZOOM
      if 0 <= y < len(self.rows) and 0 <= x < len(self.rows[y]):
         digit = str(self.panel.value)
         row = self.rows[y]
         if row[x] != digit:
            self.rows[y] = row[:x] + digit + row[x + 1:]
            self.update()

   def mousePressEvent(self, e: QtGui.QMouseEvent) -> None:
      """!Starts a stroke.
      @param e  QMouseEvent
      @return None
      """
      self.stroking = True
      self._paint_at(e.position().toPoint())

   def mouseMoveEvent(self, e: QtGui.QMouseEvent) -> None:
      """!Continues a stroke.
      @param e  QMouseEvent
      @return None
      """
      if self.stroking:
         self._paint_at(e.position().toPoint())

   def mouseReleaseEvent(self, e: QtGui.QMouseEvent) -> None:
      """!Ends a stroke: one edit of the font.
      @param e  QMouseEvent
      @return None
      """
      if self.stroking:
         self.stroking = False
         self.panel.stroke_done(list(self.rows))


class FontPanel(EditorPanel):
   """!Views and edits the proportional fonts of the host's asset manifest."""

   ## See EditorPanel.panel_id.
   panel_id = "fonts"
   ## See EditorPanel.title.
   title = "Fonts"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The font shown, or None.
      self.font_path = None
      ## The glyph shown, or None.
      self.key = None
      ## The pixel value strokes paint.
      self.value = 1
      ## True while the panel fills its widgets.
      self._filling = False
      ## The fonts the manifest reaches.
      self.font_combo = QtWidgets.QComboBox()
      self.font_combo.currentIndexChanged.connect(lambda _i: self._font_chosen())
      ## The glyphs.
      self.grid = QtWidgets.QListWidget()
      self.grid.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
      self.grid.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
      self.grid.setMovement(QtWidgets.QListView.Movement.Static)
      self.grid.setUniformItemSizes(True)
      self.grid.currentItemChanged.connect(lambda item, _old: self._glyph_chosen(item))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Font"))
      left.addWidget(self.font_combo)
      left.addWidget(self.grid, 1)
      ## The glyph editor.
      self.canvas = GlyphCanvas(self)
      scroll = QtWidgets.QScrollArea()
      scroll.setWidget(self.canvas)
      scroll.setWidgetResizable(False)
      ## The glyph's label.
      self.glyph_label = QtWidgets.QLabel()
      ## The pixel value buttons.
      self.values = QtWidgets.QButtonGroup(self)
      vrow = QtWidgets.QHBoxLayout()
      for i, name in enumerate(PIXEL_NAMES):
         b = QtWidgets.QRadioButton(f"{i} {name}")
         self.values.addButton(b, i)
         vrow.addWidget(b)
      self.values.button(self.value).setChecked(True)
      self.values.idClicked.connect(lambda i: setattr(self, "value", i))
      ## The glyph's advance width.
      self.width_spin = QtWidgets.QSpinBox()
      self.width_spin.editingFinished.connect(lambda: self._width_changed())
      wrow = QtWidgets.QHBoxLayout()
      wrow.addWidget(QtWidgets.QLabel("Width"))
      wrow.addWidget(self.width_spin)
      wrow.addStretch(1)
      wrow.addWidget(button("Add glyph...", lambda: self.add_glyph()))
      wrow.addWidget(button("Remove glyph", lambda: self.remove_glyph()))
      middle = QtWidgets.QVBoxLayout()
      middle.addWidget(self.glyph_label)
      middle.addLayout(vrow)
      middle.addWidget(scroll, 1)
      middle.addLayout(wrow)
      # the font's metrics
      ## Cell width.
      self.cell_w = QtWidgets.QSpinBox()
      ## Cell height.
      self.cell_h = QtWidgets.QSpinBox()
      ## Line height.
      self.line_height = QtWidgets.QSpinBox()
      ## Letter spacing.
      self.spacing = QtWidgets.QSpinBox()
      ## S6b (C13a): glyph height, the rows a window draws of each glyph (0: the whole cell).
      self.glyph_height = QtWidgets.QSpinBox()
      self.glyph_height.setSpecialValueText("whole cell")
      self.glyph_height.setToolTip("The rows of each glyph a text window draws (the handheld games' glyph height); "
                                   "rows below it stay in the font but never show")
      for w in (self.cell_w, self.cell_h):
         w.editingFinished.connect(lambda: self._cell_changed())
      self.line_height.editingFinished.connect(lambda: self._metric_changed("line_height", self.line_height))
      self.spacing.editingFinished.connect(lambda: self._metric_changed("letter_spacing", self.spacing))
      self.glyph_height.editingFinished.connect(lambda: self._metric_changed(fonts.GLYPH_HEIGHT, self.glyph_height))
      form = QtWidgets.QFormLayout()
      form.addRow("Cell width", self.cell_w)
      form.addRow("Cell height", self.cell_h)
      form.addRow("Line height", self.line_height)
      form.addRow("Letter spacing", self.spacing)
      form.addRow("Glyph height", self.glyph_height)
      ## The compiler's verdict.
      self.verdict = QtWidgets.QLabel()
      self.verdict.setWordWrap(True)
      ## The page's characters without a glyph.
      self.missing = QtWidgets.QLabel()
      self.missing.setWordWrap(True)
      ## The preview's text.
      self.sample = QtWidgets.QLineEdit(SAMPLE_TEXT)
      self.sample.textChanged.connect(lambda _t: self._update_preview())
      ## The preview.
      self.view = PixelView(PREVIEW_ZOOM)
      right = QtWidgets.QVBoxLayout()
      right.addLayout(form)
      right.addWidget(self.verdict)
      right.addWidget(self.missing)
      right.addWidget(QtWidgets.QLabel("Preview"))
      right.addWidget(self.sample)
      right.addWidget(self.view, 1)
      layout = QtWidgets.QHBoxLayout(self)
      for part, stretch in ((left, GRID_STRETCH), (middle, EDITOR_STRETCH), (right, SETTINGS_STRETCH)):
         holder = QtWidgets.QWidget()
         holder.setLayout(part)
         layout.addWidget(holder, stretch)

   # -- documents --------------------------------------------------------------------------------------------------

   def session(self) -> TextSession | None:
      """!The host's text session.
      @return TextSession, or None
      """
      host = self.host   # a local alias (Doxygen reads `self.x` returned here as a new member)
      return session_of(host)

   def font_doc(self) -> Document | None:
      """!The font shown.
      @return its Document, or None
      """
      s = self.session()
      if s is None or self.font_path is None:
         return None
      try:
         return s.font(self.font_path)
      except DocumentError as e:
         self.host.show_status(str(e))
         return None

   def current_document(self) -> Document | None:
      """!Undo / Redo act on the font shown.
      @return its Document, or the manifest
      """
      host = self.host   # a local alias (see session())
      return self.font_doc() or getattr(host, "document", None)

   def extra_documents(self) -> list[Document]:
      """!The tables and fonts the text panels opened.
      @return Documents
      """
      s = self.session()
      return s.documents() if s is not None else []

   def _edit(self, label: str, fn: object) -> bool:
      """!One undo step of the font.
      @param label  undo label
      @param fn     the edit
      @return True when it went through
      """
      doc = self.font_doc()
      if doc is None:
         return False
      done = self.host.run_edit(label, fn, document=doc)
      self.host.selection_changed()
      self.refresh()
      return done

   # -- filling ---------------------------------------------------------------------------------------------------

   def document_replaced(self) -> None:
      """!Another manifest: its first font.
      @return None
      """
      self.font_path = None
      self.key = None
      self.refresh()

   def refresh(self) -> None:
      """!Re-reads the fonts, the glyphs and the metrics.
      @return None
      """
      s = self.session()
      refs = s.font_refs() if s is not None else []
      paths = [p for _label, p in refs]
      self._filling = True
      try:
         if self.font_path not in paths:
            self.font_path = paths[0] if paths else None
         self.font_combo.clear()
         for label, p in refs:
            self.font_combo.addItem(f"{label} ({p.name})", str(p))
         if self.font_path is not None:
            self.font_combo.setCurrentIndex(paths.index(self.font_path))
      finally:
         self._filling = False
      self._fill_font()

   def _fill_font(self) -> None:
      """!Shows the font: glyph grid, metrics, verdict, preview.
      @return None
      """
      s, doc = self.session(), self.font_doc()
      self._filling = True
      try:
         self.grid.clear()
         if s is None or doc is None:
            self.verdict.setText("This manifest names no proportional font (a font asset or a table's font).")
            self.missing.setText("")
            self.view.set_image(None)
            self.canvas.set_glyph([], 0)
            return
         fc = fonts.compiler()
         rows = fonts.glyph_rows(doc, s.context.page)
         cw, ch = fonts.cell(doc)
         icon_size = QtCore.QSize(cw * ICON_ZOOM + ICON_PAD, ch * ICON_ZOOM + ICON_PAD)
         self.grid.setIconSize(icon_size)
         keys = [r.key for r in rows]
         for r in rows:
            code = f"{r.code:02X}" if r.code is not None else "--"
            icon = glyph_image(r.rows, r.width, ICON_ZOOM, fonts.drawn_rows(doc))
            item = QtWidgets.QListWidgetItem(QtGui.QIcon(QtGui.QPixmap.fromImage(icon)),
                                             f"{r.key} {code}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, r.key)
            item.setToolTip(f"{r.key!r}: code {code}, width {r.width}")
            self.grid.addItem(item)
         if self.key not in keys:
            self.key = keys[0] if keys else None
         if self.key is not None:
            self.grid.setCurrentRow(keys.index(self.key))
         self.cell_w.setRange(fc.CELL_WIDTH_STEP, fc.MAX_CELL)
         self.cell_w.setSingleStep(fc.CELL_WIDTH_STEP)
         self.cell_h.setRange(1, fc.MAX_CELL)
         for w in (self.line_height, self.spacing, self.width_spin):
            w.setRange(0, fc.MAX_METRIC)
         self.cell_w.setValue(cw)
         self.cell_h.setValue(ch)
         self.line_height.setValue(int(doc.data.get("line_height", ch)))
         self.spacing.setValue(int(doc.data.get("letter_spacing", 0)))
         self.glyph_height.setRange(0, ch)
         self.glyph_height.setValue(fonts.glyph_height(doc))
         problem = fonts.problem(doc, s.context.page)
         self.verdict.setText(f"Does not compile: {problem}" if problem else
                              f"Compiles for the code page {s.context.page.id!r}: {len(rows)} glyphs.")
         self.verdict.setStyleSheet("color: #d03030;" if problem else "")
         missing = fonts.missing_characters(doc, s.context.page)
         self.missing.setText("Page characters without a glyph: " +
                              ("".join(missing)[:MISSING_SHOWN] if missing else "none"))
      except engine.EngineNotFound as e:
         self.verdict.setText(str(e))
      finally:
         self._filling = False
      self._fill_glyph()
      self._update_preview()

   def _fill_glyph(self) -> None:
      """!Shows the chosen glyph in the editor.
      @return None
      """
      doc = self.font_doc()
      g = (doc.data.get("glyphs") or {}).get(self.key) if doc is not None and self.key is not None else None
      if not isinstance(g, dict):
         self.canvas.set_glyph([], 0)
         self.glyph_label.setText("")
         return
      cw, _ch = fonts.cell(doc)
      width = int(g.get("width", cw))
      self.canvas.set_glyph(list(g.get("rows", [])), width, fonts.drawn_rows(doc))
      s = self.session()
      code = fonts.code_of(self.key, s.context.page) if s is not None else None
      self.glyph_label.setText(f"Glyph {self.key!r}" + (f", code 0x{code:02X}" if code is not None else
                                                       ", no code in the page"))
      self._filling = True
      self.width_spin.setValue(width)
      self._filling = False

   def _update_preview(self) -> None:
      """!Draws the sample text in the font (as edited).
      @return None
      """
      s, doc = self.session(), self.font_doc()
      if s is None or doc is None:
         self.view.set_image(None)
         return
      te = text_render.encoder()
      try:
         font = fonts.compile_font(doc, s.context.page)
         codes = te.encode(self.sample.text(), "preview", codepage=s.context.page, markup=False)
      except (DocumentError, te.TextError) as e:
         self.view.set_image(None)
         self.host.show_status(str(e))
         return
      pens = text_render.preview_pens()
      self.view.set_image(to_qimage(*text_render.render_text(font, codes, pens, PREVIEW_MARGIN)))

   # -- edits ------------------------------------------------------------------------------------------------------

   def _font_chosen(self) -> None:
      """!Another font.
      @return None
      """
      if self._filling:
         return
      data = self.font_combo.currentData()
      self.font_path = Path(data) if data else None
      self.key = None
      self._fill_font()
      self.host.selection_changed()

   def _glyph_chosen(self, item: QtWidgets.QListWidgetItem | None) -> None:
      """!Another glyph.
      @param item  its grid item
      @return None
      """
      if self._filling or item is None:
         return
      self.key = item.data(QtCore.Qt.ItemDataRole.UserRole)
      self._fill_glyph()

   def select_glyph(self, key: str) -> bool:
      """!Shows a glyph (its grid cell selected).
      @param key  its key
      @return True when the font has it
      """
      for i in range(self.grid.count()):
         if self.grid.item(i).data(QtCore.Qt.ItemDataRole.UserRole) == key:
            self.grid.setCurrentRow(i)
            self.key = key
            self._fill_glyph()
            return True
      return False

   def stroke_done(self, rows: list[str]) -> None:
      """!A stroke ended: its rows as one edit.
      @param rows  the glyph's rows after it
      @return None
      """
      doc, key = self.font_doc(), self.key
      if doc is None or key is None:
         return
      g = (doc.data.get("glyphs") or {}).get(key) or {}
      if list(g.get("rows", [])) != rows:
         self._edit("Paint glyph", lambda: fonts.set_rows(doc, key, rows))

   def _width_changed(self) -> None:
      """!The width spin changed.
      @return None
      """
      doc, key = self.font_doc(), self.key
      if self._filling or doc is None or key is None:
         return
      width = self.width_spin.value()
      g = (doc.data.get("glyphs") or {}).get(key) or {}
      if g.get("width") != width:
         self._edit("Glyph width", lambda: fonts.set_width(doc, key, width))

   def _cell_changed(self) -> None:
      """!The cell spins changed.
      @return None
      """
      doc = self.font_doc()
      if self._filling or doc is None:
         return
      w, h = self.cell_w.value(), self.cell_h.value()
      if (w, h) != fonts.cell(doc):
         self._edit("Cell", lambda: fonts.set_cell(doc, w, h))

   def _metric_changed(self, name: str, spin: QtWidgets.QSpinBox) -> None:
      """!A metric spin changed.
      @param name  line_height, letter_spacing or glyph_height
      @param spin  its spin box
      @return None
      """
      doc = self.font_doc()
      if self._filling or doc is None:
         return
      v = spin.value()
      if doc.data.get(name, 0 if name == fonts.GLYPH_HEIGHT else None) != v:
         self._edit(name.replace("_", " ").capitalize(), lambda: fonts.set_metric(doc, name, v))

   def add_glyph(self, key: str | None = None) -> None:
      """!Adds a blank glyph.
      @param key  its character (or a named glyph's key), or None to ask
      @return None
      """
      doc = self.font_doc()
      if doc is None:
         return
      if key is None:
         key, ok = QtWidgets.QInputDialog.getText(self, "New glyph", "Character (or a named glyph's key):")
         if not ok:
            return
      if key and self._edit("Add glyph", lambda: fonts.add_glyph(doc, key)):
         self.key = key
         self._fill_font()

   def remove_glyph(self) -> None:
      """!Removes the glyph shown.
      @return None
      """
      doc, key = self.font_doc(), self.key
      if doc is not None and key is not None and self._edit("Remove glyph", lambda: fonts.remove_glyph(doc, key)):
         self.key = None
         self._fill_font()
