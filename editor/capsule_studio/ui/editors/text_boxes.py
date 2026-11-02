"""!Text box styles panel [the older studio, the field options] (asset kind "text_box", capsule/text/window.h): a game's
message box styles, the window and the frame the engine draws, with a preview that types as the engine types.

Left: the manifest's text_box assets (core.text_boxes) with Add / Copy / Rename / Remove, and, while the manifest
still holds the older studio's editor-data styles, a button that turns them into assets (core.text_boxes.migrate()).
Middle: the style's font (a font asset of the manifest) and the fonts its Font control n selects; one field per setting
the engine's text_box takes, in window.h's order with its comments as tips (a number in the compiler's range; typing and
speed-up as their words; char_block and arrow may be left out: the layer's block, no arrow); the frame's first tile,
palette bank and padding per side; the preview's colours (the bank's 16 entries), the frame art's two entries or a
24x24 frame picture. Below, what the engine refuses or draws wrongly (core.text_boxes.check()), and "Apply to table"
(a table's box gets the style's width and lines, core.text_boxes.fit_box()). Right: the box on a 240x160 screen
with a text of the manifest's tables, typed frame by frame as window.cpp types it (core.text_window: interval or
counter typing, the lead frames, pauses, scrolls, the speed-up): the keys pressed (none, a press at each wait,
Accept held), the wait shown, a frame slider and Play.

The bank's colours are stored in the style ("palette": the engine loads them) once "Stored in the
style" is on (else they are the preview's); the frame's image (a 24x24 palette PNG of the nine parts) and its own
bank's colours (frame "palette"); the window's arrow image (an 8-pixel-wide palette PNG, the rows shown at once, the
steps' first rows, the frames between steps) with a strip of its steps, typed in the preview as window.cpp steps it.
A style's menu is the Menu styles panel's (ui/editors/menu_styles.py).

Every change is one undo step of the manifest (host.run_edit()).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import engine, text_boxes, text_render, text_tables, text_window
from ...core.document import Document, DocumentError
from ..panel import EditorPanel
from ..qtimage import to_qimage
from ..panes import split_box
from ..widgets import PixelView, button
from .text_common import session_of

if TYPE_CHECKING:
   from ..panel import PanelHost
   from .text_common import TextSession

## Screen pixels per preview pixel.
PREVIEW_ZOOM = 2
## Colour buttons per row of the preview palette.
SWATCHES_PER_ROW = 8
## Side of a colour button, pixels.
SWATCH_SIDE = 20
## The text the preview shows without a table.
SAMPLE_TEXT = "The quick brown fox\njumps over the lazy dog."
## Channel sum above which a colour is bright (a swatch's number is drawn dark on it).
BRIGHT_SUM = 384
## Group box titles.
GROUP_TITLES = {"window": "Window (window::Config)", "frame": "Frame (window::Frame)"}
## Stretch of the list, the form and the preview.
LIST_STRETCH, FORM_STRETCH, PREVIEW_STRETCH = 1, 3, 3
## Columns of the form's grid per field (label, editor).
FORM_COLUMNS = 2
## Fields per row of the form's grid.
FIELDS_PER_ROW = 2
## What an optional setting left out shows (its spin's lowest value).
LEFT_OUT_TEXT = {"char_block": "(the layer's)", "arrow": "(none)"}
## Milliseconds between preview frames while playing (the GBA's 60 frames a second, rounded).
FRAME_MS = 16
## Columns of the Font control table.
FONT_COLUMNS = ["Control", "Font"]
## Rows the Font control table shows before it scrolls.
FONT_ROWS = 4
## Colour of the engine's refusals.
ERROR_COLOR = "#c03030"
## Screen pixels per arrow image pixel in its strip.
STRIP_ZOOM = 4
## Highest arrow image height / delay the spins offer (the compiler's MAX_ARROW_ROWS when it has one).
DEFAULT_ARROW_MAX = 255


class TextBoxPanel(EditorPanel):
   """!Edits the text box styles (text_box assets) of the host's asset manifest."""

   ## See EditorPanel.panel_id.
   panel_id = "text_boxes"
   ## See EditorPanel.title.
   title = "Text boxes"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The style shown (its key), or None.
      self.key = None
      ## True while the panel fills its widgets.
      self._filling = False
      ## The preview's typing (core.text_window.Run) and what it was typed from.
      self._run = None
      ## Whether the preview has a text to type (a font and a text).
      self._has_text = False
      ## The manifest's font asset keys (read on refresh).
      self._font_keys = []
      ## The fonts the manifest reaches: label -> path (read on refresh: the manifest is expanded for them).
      self._font_paths = {}
      ## The styles.
      self.list = QtWidgets.QListWidget()
      self.list.currentItemChanged.connect(lambda item, _old: self._chosen(item))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Styles (text_box assets)"))
      left.addWidget(self.list, 1)
      left.addWidget(button("Add...", lambda: self.add_style()))
      left.addWidget(button("Copy...", lambda: self.copy_style()))
      left.addWidget(button("Rename...", lambda: self.rename_style()))
      left.addWidget(button("Remove", lambda: self.remove_style()))
      ## Turns the older studio's editor-data styles into assets (shown while the manifest has some).
      self.migrate_button = button("Make editor-data styles assets", lambda: self.migrate(),
                                   "Older studios kept styles as the manifest's editor data; the engine now reads "
                                   "text_box assets")
      left.addWidget(self.migrate_button)
      ## The style's font (a font asset's key).
      self.font_box = QtWidgets.QComboBox()
      self.font_box.activated.connect(lambda _i: self._font_chosen())
      ## The Font control's fonts: number -> font asset.
      self.control_fonts = QtWidgets.QTableWidget(0, len(FONT_COLUMNS))
      self.control_fonts.setHorizontalHeaderLabels(FONT_COLUMNS)
      self.control_fonts.verticalHeader().setVisible(False)
      self.control_fonts.horizontalHeader().setStretchLastSection(True)
      self.control_fonts.setMaximumHeight(self.control_fonts.horizontalHeader().height() +
                                          self.fontMetrics().height() * FONT_ROWS * FORM_COLUMNS)
      ## The number a new Font control row takes.
      self.control_number = QtWidgets.QSpinBox()
      ## The font a new Font control row takes.
      self.control_font = QtWidgets.QComboBox()
      ## Editors by (group, member): spin boxes, or combo boxes for word settings.
      self.editors = {}
      form = QtWidgets.QVBoxLayout()
      frow = QtWidgets.QHBoxLayout()
      frow.addWidget(QtWidgets.QLabel("Font"))
      frow.addWidget(self.font_box, 1)
      form.addLayout(frow)
      fonts_box = QtWidgets.QGroupBox("Font control fonts (the text's {font:n} draws in font n)")
      fv = QtWidgets.QVBoxLayout(fonts_box)
      fv.addWidget(self.control_fonts)
      crow = QtWidgets.QHBoxLayout()
      crow.addWidget(self.control_number)
      crow.addWidget(self.control_font, 1)
      crow.addWidget(button("Set", lambda: self.set_control_font()))
      crow.addWidget(button("Remove", lambda: self.remove_control_font()))
      fv.addLayout(crow)
      form.addWidget(fonts_box)
      lim = None
      try:
         fields = text_boxes.config_fields()
         lim = text_boxes.limits()
         self.control_number.setRange(0, int(getattr(engine.asset_compiler(), "MAX_TEXT_BOX_FONTS", 1)) - 1)
      except (DocumentError, engine.EngineNotFound) as e:
         fields = []
         form.addWidget(QtWidgets.QLabel(str(e)))
      ## The engine's limits (None without them).
      self.limits = lim
      for group in ("window", "frame"):
         box = QtWidgets.QGroupBox(GROUP_TITLES[group])
         grid = QtWidgets.QGridLayout(box)
         members = [f for f in fields if f.group == group]
         for i, f in enumerate(members):
            editor = self._editor(f)
            self.editors[(group, f.name)] = editor
            row, col = divmod(i, FIELDS_PER_ROW)
            grid.addWidget(QtWidgets.QLabel(f.name), row, col * FORM_COLUMNS)
            grid.addWidget(editor, row, col * FORM_COLUMNS + 1)
         form.addWidget(box)
      ## The bank's colours (the style's palette, else the preview's).
      self.swatches = []
      colors = QtWidgets.QGroupBox("Bank colours (palette bank entries; entry 0 is the backdrop)")
      cgrid = QtWidgets.QGridLayout(colors)
      for i in range(text_render.bank_colors()):
         b = QtWidgets.QPushButton(str(i))
         b.setFixedSize(SWATCH_SIDE + SWATCH_SIDE, SWATCH_SIDE)
         b.clicked.connect(lambda _c=False, n=i: self._pick_color(n))
         self.swatches.append(b)
         cgrid.addWidget(b, i // SWATCHES_PER_ROW, i % SWATCHES_PER_ROW)
      ## The colours are the style's own palette (entries 1-15; the engine loads them into the bank).
      self.stored = QtWidgets.QCheckBox("Stored in the style (palette: the game loads these colours)")
      self.stored.clicked.connect(lambda on: self.set_stored_palette(on))
      cgrid.addWidget(self.stored, text_render.bank_colors() // SWATCHES_PER_ROW, 0, 1, SWATCHES_PER_ROW)
      ## The frame bank's own colours.
      self.frame_swatches = []
      fcolors = QtWidgets.QGroupBox("Frame bank colours (frame palette; off: the window's)")
      fgrid = QtWidgets.QGridLayout(fcolors)
      for i in range(text_render.bank_colors()):
         b = QtWidgets.QPushButton(str(i))
         b.setFixedSize(SWATCH_SIDE + SWATCH_SIDE, SWATCH_SIDE)
         b.clicked.connect(lambda _c=False, n=i: self._pick_frame_color(n))
         self.frame_swatches.append(b)
         fgrid.addWidget(b, i // SWATCHES_PER_ROW, i % SWATCHES_PER_ROW)
      ## The frame has a palette of its own.
      self.frame_own = QtWidgets.QCheckBox("Own colours (frame palette)")
      self.frame_own.clicked.connect(lambda on: self.set_frame_palette(on))
      fgrid.addWidget(self.frame_own, text_render.bank_colors() // SWATCHES_PER_ROW, 0, 1, SWATCHES_PER_ROW)
      ## The generated frame art's outer and inner entries.
      self.frame_entries = [QtWidgets.QSpinBox(), QtWidgets.QSpinBox()]
      erow = QtWidgets.QHBoxLayout()
      erow.addWidget(QtWidgets.QLabel("Frame art lines (outer, inner)"))
      for s in self.frame_entries:
         s.setRange(0, text_render.bank_colors() - 1)
         s.editingFinished.connect(lambda: self._frame_entries_changed())
         erow.addWidget(s)
      ## The frame's image (frame "image": a 24x24 palette PNG of the nine parts; menus data).
      self.frame_image = QtWidgets.QLineEdit()
      self.frame_image.setPlaceholderText("generated from the two entries")
      self.frame_image.setToolTip("frame.image: a 24x24 palette PNG of the nine frame parts in reading order, relative "
                                  "to the manifest (the game loads it into the frame's tiles)")
      self.frame_image.editingFinished.connect(lambda: self._frame_image_changed())
      erow.addWidget(QtWidgets.QLabel("Frame image"))
      erow.addWidget(self.frame_image, 1)
      form.addWidget(colors)
      form.addLayout(erow)
      form.addWidget(fcolors)
      form.addWidget(self._build_arrow())
      ## What the engine would refuse.
      self.checks = QtWidgets.QLabel()
      self.checks.setWordWrap(True)
      form.addWidget(self.checks)
      ## The table "Apply to table" sets.
      self.table_box = QtWidgets.QComboBox()
      self.table_box.currentIndexChanged.connect(lambda _i: self._table_chosen())
      arow = QtWidgets.QHBoxLayout()
      arow.addWidget(QtWidgets.QLabel("Table"))
      arow.addWidget(self.table_box, 1)
      arow.addWidget(button("Apply to table", lambda: self.apply_to_table(),
                            "The table's box gets this style's width (less the left margin) and lines"))
      form.addLayout(arow)
      form.addStretch(1)
      ## The preview's text: a table's key, or the sample.
      self.text_key = QtWidgets.QComboBox()
      self.text_key.setEditable(True)
      self.text_key.activated.connect(lambda _i: self._update_preview(True))
      ## The keys the preview's typing presses (core.text_window.KEY_POLICIES).
      self.keys = QtWidgets.QComboBox()
      self.keys.addItems(text_window.KEY_POLICIES)
      self.keys.setCurrentText(text_window.KEY_POLICIES[1])
      self.keys.setToolTip("none: no key (the text stops at its first wait); advance: a press at each wait; hold: "
                           "Accept held (a press while it types, then held: the speed-up)")
      self.keys.activated.connect(lambda _i: self._update_preview(True))
      ## Which wait of the text.
      self.screen = QtWidgets.QSpinBox()
      self.screen.valueChanged.connect(lambda _v: self._wait_chosen())
      ## The frame of the typing shown.
      self.frame = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
      self.frame.valueChanged.connect(lambda _v: self._frame_chosen())
      ## The frame's number.
      self.frame_label = QtWidgets.QLabel()
      ## Plays the typing.
      self.timer = QtCore.QTimer(self)
      self.timer.setInterval(FRAME_MS)
      self.timer.timeout.connect(lambda: self._tick())
      ## The typing's summary (when it waits, when it ends).
      self.summary = QtWidgets.QLabel()
      self.summary.setWordWrap(True)
      ## The preview.
      self.view = PixelView(PREVIEW_ZOOM)
      right = QtWidgets.QVBoxLayout()
      prow = QtWidgets.QHBoxLayout()
      prow.addWidget(QtWidgets.QLabel("Text"))
      prow.addWidget(self.text_key, 1)
      prow.addWidget(QtWidgets.QLabel("Keys"))
      prow.addWidget(self.keys)
      prow.addWidget(QtWidgets.QLabel("Wait"))
      prow.addWidget(self.screen)
      right.addLayout(prow)
      trow = QtWidgets.QHBoxLayout()
      trow.addWidget(QtWidgets.QLabel("Frame"))
      trow.addWidget(self.frame, 1)
      trow.addWidget(self.frame_label)
      trow.addWidget(button("Play", lambda: self.play(), "Type the text at the GBA's frame rate"))
      trow.addWidget(button("Stop", lambda: self.stop()))
      right.addLayout(trow)
      right.addWidget(self.summary)
      right.addWidget(self.view, 1)
      layout = QtWidgets.QHBoxLayout(self)
      form_holder = QtWidgets.QWidget()
      form_holder.setLayout(form)
      scroll = QtWidgets.QScrollArea()
      scroll.setWidget(form_holder)
      scroll.setWidgetResizable(True)
      for part, stretch in ((left, LIST_STRETCH), (scroll, FORM_STRETCH), (right, PREVIEW_STRETCH)):
         if isinstance(part, QtWidgets.QLayout):
            holder = QtWidgets.QWidget()
            holder.setLayout(part)
            part = holder
         layout.addWidget(part, stretch)
      split_box(layout)   # [RZ] list | form | preview: the user drags the boundaries

   def _build_arrow(self) -> QtWidgets.QGroupBox:
      """!The arrow image box (window "arrow_image"): the image, its height, steps and delay, and a
      strip of the steps.
      @return the box
      """
      most = int(getattr(engine.asset_compiler(), "MAX_ARROW_ROWS", DEFAULT_ARROW_MAX))
      box = QtWidgets.QGroupBox("Arrow image (window arrow_image: the prompt arrow steps through an image's rows)")
      grid = QtWidgets.QGridLayout(box)
      ## The image (an 8-pixel-wide palette PNG).
      self.arrow_path = QtWidgets.QLineEdit()
      self.arrow_path.setPlaceholderText("(none: the arrow glyph blinks)")
      self.arrow_path.setToolTip("An 8-pixel-wide palette PNG relative to the manifest; its indices are the bank's "
                                 "entries, 0 shows the window's background")
      self.arrow_path.editingFinished.connect(lambda: self._arrow_changed())
      ## Rows shown at once.
      self.arrow_height = QtWidgets.QSpinBox()
      self.arrow_height.setRange(0, most)
      self.arrow_height.setSpecialValueText("(the image's)")
      self.arrow_height.editingFinished.connect(lambda: self._arrow_changed())
      ## The steps' first rows.
      self.arrow_steps = QtWidgets.QLineEdit()
      self.arrow_steps.setPlaceholderText("0")
      self.arrow_steps.setToolTip("The image row each step shows first, comma-separated (e.g. 0, 1, 2, 1)")
      self.arrow_steps.editingFinished.connect(lambda: self._arrow_changed())
      ## Frames between two steps.
      self.arrow_delay = QtWidgets.QSpinBox()
      self.arrow_delay.setRange(0, most)
      self.arrow_delay.setToolTip("Frames between two steps (the first step shows at once)")
      self.arrow_delay.editingFinished.connect(lambda: self._arrow_changed())
      ## The steps side by side.
      self.arrow_view = PixelView(STRIP_ZOOM)
      self.arrow_view.setMinimumHeight(SWATCH_SIDE + SWATCH_SIDE)
      grid.addWidget(QtWidgets.QLabel("Image"), 0, 0)
      grid.addWidget(self.arrow_path, 0, 1, 1, FORM_COLUMNS + 1)
      grid.addWidget(button("None", lambda: self.set_arrow_image(None), "No arrow image (the glyph blinks)"), 0,
                     FORM_COLUMNS + FORM_COLUMNS)
      grid.addWidget(QtWidgets.QLabel("Height"), 1, 0)
      grid.addWidget(self.arrow_height, 1, 1)
      grid.addWidget(QtWidgets.QLabel("Delay"), 1, FORM_COLUMNS)
      grid.addWidget(self.arrow_delay, 1, FORM_COLUMNS + 1)
      grid.addWidget(QtWidgets.QLabel("Steps"), FORM_COLUMNS, 0)
      grid.addWidget(self.arrow_steps, FORM_COLUMNS, 1, 1, FORM_COLUMNS + FORM_COLUMNS - 1)
      grid.addWidget(self.arrow_view, FORM_COLUMNS + 1, 0, 1, FORM_COLUMNS + FORM_COLUMNS + 1)
      return box

   def _editor(self, f: text_boxes.Field) -> QtWidgets.QWidget:
      """!The editor of one setting: a combo for a word setting, else a spin in the engine's range (an optional
      setting's lowest value shows LEFT_OUT_TEXT and means left out).
      @param f  the field
      @return the widget
      """
      tip = f"{f.group}.{f.name}: {f.doc}" if f.doc else f"{f.group}.{f.name}"
      if f.words:
         combo = QtWidgets.QComboBox()
         combo.addItems(f.words)
         combo.setToolTip(tip)
         combo.activated.connect(lambda _i, g=f.group, n=f.name: self._changed(g, n))
         return combo
      spin = QtWidgets.QSpinBox()
      low = f.low - 1 if f.optional else f.low
      spin.setRange(low, self._high(f))
      if f.optional:
         spin.setSpecialValueText(LEFT_OUT_TEXT.get(f.name, "(left out)"))
      spin.setToolTip(f"{tip} ({f.low}-{f.high})")
      spin.editingFinished.connect(lambda g=f.group, n=f.name: self._changed(g, n))
      return spin

   def _high(self, f: text_boxes.Field) -> int:
      """!The highest value a field's spin offers (the compiler's, the engine's limits where they are tighter).
      @param f  the field
      @return value
      """
      lim = self.limits
      if lim is None:
         return f.high
      tighter = {"bg": lim.layers - 1, "palette_bank": lim.banks - 1, "first_tile": lim.max_tile,
                 "x": lim.map_cells - 1, "y": lim.map_cells - 1, "width": lim.map_cells, "height": lim.map_cells}
      return min(f.high, tighter.get(f.name, f.high))

   # -- filling ---------------------------------------------------------------------------------------------------

   def session(self) -> TextSession | None:
      """!The host's text session.
      @return TextSession, or None
      """
      host = self.host   # a local alias (Doxygen reads `self.x` returned here as a new member)
      return session_of(host)

   def style(self) -> dict[str, Any] | None:
      """!The style shown.
      @return it, or None
      """
      doc, key = self.doc, self.key   # local aliases (see session())
      if key is None:
         return None
      try:
         return text_boxes.find(doc, key)
      except DocumentError:
         return None

   def document_replaced(self) -> None:
      """!Another manifest.
      @return None
      """
      self.key = None
      self.refresh()

   def refresh(self) -> None:
      """!Re-reads the styles and the style shown.
      @return None
      """
      keys = text_boxes.keys(self.doc)
      self._filling = True
      try:
         if self.key not in keys:
            self.key = keys[0] if keys else None
         self.list.clear()
         self.list.addItems(keys)
         if self.key is not None:
            self.list.setCurrentRow(keys.index(self.key))
         legacy = text_boxes.legacy_styles(self.doc)
         self.migrate_button.setVisible(bool(legacy))
         self.migrate_button.setText(f"Make {len(legacy)} editor-data styles assets")
         s = self.session()
         self._font_paths = dict(s.font_refs()) if s is not None else {}
         font_keys = text_boxes.font_keys(self.doc) if s is not None else [str(a.get("key"))
                                                                           for a in self.doc.assets("font")]
         self._font_keys = font_keys
         for combo in (self.font_box, self.control_font):
            combo.clear()
            combo.addItems(([""] if combo is self.font_box else []) + font_keys)
         chosen = self.table_box.currentData()
         self.table_box.clear()
         refs = s.table_refs() if s is not None else []
         for r in refs:
            self.table_box.addItem(f"{r.label} [{r.language}]" if r.language else r.label, str(r.path))
         paths = [str(r.path) for r in refs]
         if chosen in paths:
            self.table_box.setCurrentIndex(paths.index(chosen))
      finally:
         self._filling = False
      self._fill_keys()
      self._fill_style()

   def _fill_keys(self) -> None:
      """!The preview's texts: the sample, then the keys of the table chosen.
      @return None
      """
      s = self.session()
      current = self.text_key.currentText()
      keys = [SAMPLE_TEXT.replace("\n", "\\n")]
      data = self.table_box.currentData()
      if s is not None and data:
         try:
            keys += [r.key for r in text_tables.rows(s.table(Path(data)))]
         except DocumentError:
            pass
      self._filling = True
      self.text_key.clear()
      self.text_key.addItems(keys)
      if current in keys:
         self.text_key.setCurrentText(current)
      self._filling = False

   def _table_chosen(self) -> None:
      """!Another table: its texts for the preview.
      @return None
      """
      if not self._filling:
         self._fill_keys()
         self._update_preview(True)

   def _fill_style(self) -> None:
      """!Shows the style's settings, its fonts, its checks and the preview.
      @return None
      """
      self._filling = True
      style = self.style()
      try:
         for (group, name), w in self.editors.items():
            w.setEnabled(style is not None)
            if style is None:
               continue
            v = text_boxes.value(style, group, name)
            if isinstance(w, QtWidgets.QComboBox):
               w.setCurrentText(str(v))
            else:
               w.setValue(w.minimum() if v is None else int(v))
         self.font_box.setCurrentText(str(style.get("font") or "") if style is not None else "")
         self._fill_control_fonts(style)
         preview = text_boxes.preview_data(style) if style is not None else {}
         pens = text_boxes.pens(style) if style is not None else text_render.Pens()
         _paint(self.swatches, pens)
         fpens = text_boxes.frame_pens(style) if style is not None else text_render.Pens()
         _paint(self.frame_swatches, fpens)
         own = style is not None and text_boxes.frame_palette(style) is not None
         for b in self.frame_swatches:
            b.setEnabled(own)
         self.stored.setChecked(style is not None and text_boxes.stored_palette(style) is not None)
         self.frame_own.setChecked(own)
         entries = preview.get("frame_entries") or text_boxes.NEW_PREVIEW["frame_entries"]
         for spin, v in zip(self.frame_entries, entries):
            spin.setValue(int(v))
         image = text_boxes.frame_image(style) if style is not None else None
         self.frame_image.setText(image or "")
         legacy = preview.get("frame_image")
         self.frame_image.setPlaceholderText(f"(preview picture {legacy})" if legacy else "generated from the two "
                                                                                          "entries")
         self._fill_arrow(style)
      finally:
         self._filling = False
      self._update_preview(True)

   def _fill_arrow(self, style: dict[str, Any] | None) -> None:
      """!The arrow image box.
      @param style  the style, or None
      @return None
      """
      arrow = text_boxes.arrow_image(style) if style is not None else None
      self.arrow_path.setText(str(arrow.get("image", "")) if arrow else "")
      self.arrow_height.setValue(int(arrow.get("height", 0)) if arrow else 0)
      self.arrow_delay.setValue(int(arrow.get("delay", 0)) if arrow else 0)
      self.arrow_steps.setText(", ".join(str(v) for v in arrow.get("steps", [])) if arrow else "")
      for w in (self.arrow_height, self.arrow_delay, self.arrow_steps):
         w.setEnabled(arrow is not None)
      strip = text_boxes.arrow_strip(style, self.doc.base_dir) if style is not None else None
      self.arrow_view.set_image(to_qimage(*strip.image()) if strip is not None else None)

   def _fill_control_fonts(self, style: dict[str, Any] | None) -> None:
      """!The Font control table.
      @param style  the style, or None
      @return None
      """
      table = text_boxes.control_fonts(style) if style is not None else {}
      self.control_fonts.setRowCount(len(table))
      for r, (n, key) in enumerate(sorted(table.items())):
         for c, text in enumerate((str(n), key)):
            item = QtWidgets.QTableWidgetItem(text)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.control_fonts.setItem(r, c, item)

   def _compiled_font(self, key: str | None) -> dict | None:
      """!A font asset compiled (the session's context: the game's code page).
      @param key  its asset key, or None
      @return compile_proportional()'s result, or None
      """
      s = self.session()
      if s is None or not key:
         return None
      path = self._font_paths.get(key)
      if path is None:
         return None
      try:
         return s.context.font(path)
      except DocumentError as e:
         self.host.show_status(str(e))
         return None

   def _codes(self) -> list[int] | None:
      """!The preview text's codes: a table text's (its key chosen) or the typed sample.
      @return codes, or None
      """
      s = self.session()
      if s is None:
         return None
      chosen = self.text_key.currentText()
      data = self.table_box.currentData()
      refs = s.table_refs()
      # the chosen table first (another language's table may hold the same key)
      refs = sorted(refs, key=lambda r: str(r.path) != data)
      for ref in refs:
         try:
            table = s.table(ref.path)
         except DocumentError:
            continue
         if chosen in (table.data.get("texts") or {}):
            text = text_tables.entry(table, chosen).text
            break
      else:
         text = chosen.replace("\\n", "\n")
      try:
         return s.context.encode(text, "preview")
      except DocumentError as e:
         self.host.show_status(str(e))
         return None

   def _typing(self, style: dict[str, Any], font: dict, codes: list[int]) -> text_window.Run:
      """!The preview text typed in the style (again only when the style, the text or the keys changed).
      @param style  the style
      @param font   its compiled font
      @param codes  the text
      @return core.text_window.Run
      """
      s = self.session()
      stamp = (json.dumps(style, sort_keys=True), tuple(codes), self.keys.currentText())
      if self._run is None or self._run[0] != stamp:
         control = {n: self._compiled_font(k) for n, k in text_boxes.control_fonts(style).items()}
         run = text_boxes.typing(style, font, codes, self.keys.currentText(),
                                 {n: f for n, f in control.items() if f is not None},
                                 s.context.placeholder_codes() if s is not None else None, self.doc.base_dir)
         self._run = (stamp, run)
      return self._run[1]

   def _update_preview(self, retype: bool = False) -> None:
      """!Checks the style, types the text and draws the frame chosen.
      @param retype  the text or the style changed: start at the first wait
      @return None
      """
      style = self.style()
      if style is None or self.limits is None:
         self.view.set_image(None)
         self.checks.setText("No style: Add one." if self.limits is not None else "")
         self.summary.setText("")
         return
      font = self._compiled_font(style.get("font"))
      problems = text_boxes.check(style, font, self._font_keys, self.doc.base_dir)
      # The tiles the game gives the window (window::attach()), with what the engine says
      self.checks.setText("\n".join(problems or ["The engine draws this box as shown."]) +
                          f"\nWindow storage: {text_boxes.storage(style).text()}")
      self.checks.setStyleSheet(f"color: {ERROR_COLOR};" if any(p.startswith("error") for p in problems) else "")
      codes = self._codes() if font is not None else None
      run = self._typing(style, font, codes) if font is not None and codes else None
      self._has_text = run is not None
      waits = text_boxes.wait_frames(run) if run is not None else [0]
      self._filling = True
      try:
         self.screen.setRange(0, max(0, len(waits) - 1))
         self.screen.setSuffix(f" of {len(waits)}")
         self.frame.setRange(0, max(0, len(run.frames) - 1) if run is not None else 0)
         if retype:
            self.frame.setValue(waits[min(self.screen.value(), len(waits) - 1)])
      finally:
         self._filling = False
      self.summary.setText(text_boxes.describe_run(run) if run is not None else "No text to type (a font and a text "
                                                                                "are needed).")
      self._draw()

   def _draw(self) -> None:
      """!Draws the frame the slider shows.
      @return None
      """
      style = self.style()
      if style is None or self.limits is None:
         return
      run = self._run[1] if self._run is not None and self._has_text else None
      self.frame_label.setText(f"{self.frame.value()} / {self.frame.maximum()}")
      canvas = text_boxes.preview(style, None, None, 0, self.doc.base_dir, None, self.frame.value(), run)
      self.view.set_image(to_qimage(*canvas.image()))

   def _wait_chosen(self) -> None:
      """!Another wait: the slider goes to its frame.
      @return None
      """
      if self._filling or self._run is None:
         return
      waits = text_boxes.wait_frames(self._run[1])
      self.frame.setValue(waits[min(self.screen.value(), len(waits) - 1)])

   def _frame_chosen(self) -> None:
      """!The slider moved.
      @return None
      """
      if not self._filling:
         self._draw()

   def play(self) -> None:
      """!Types the text from its first frame at the GBA's frame rate.
      @return None
      """
      self.frame.setValue(0)
      self.timer.start()

   def stop(self) -> None:
      """!Stops playing.
      @return None
      """
      self.timer.stop()

   def _tick(self) -> None:
      """!One frame of playing.
      @return None
      """
      if self.frame.value() >= self.frame.maximum():
         self.timer.stop()
         return
      self.frame.setValue(self.frame.value() + 1)

   # -- edits ------------------------------------------------------------------------------------------------------

   def _set(self, group: str, name: str, value: Any, label: str = "Text box") -> bool:
      """!Changes one setting of the style shown.
      @param group  "window", "frame", "preview" or ""
      @param name   the setting
      @param value  its value
      @param label  undo label
      @return True when it went through
      """
      doc, key = self.doc, self.key
      if key is None:
         return False
      return self.host.run_edit(label, lambda: text_boxes.set_value(doc, key, group, name, value))

   def _chosen(self, item: QtWidgets.QListWidgetItem | None) -> None:
      """!Another style.
      @param item  its list item
      @return None
      """
      if self._filling or item is None:
         return
      self.key = item.text()
      self._fill_style()

   def _changed(self, group: str, name: str) -> None:
      """!A setting's editor changed.
      @param group  "window" or "frame"
      @param name   the member
      @return None
      """
      style = self.style()
      if self._filling or style is None:
         return
      w = self.editors[(group, name)]
      if isinstance(w, QtWidgets.QComboBox):
         v: Any = w.currentText()
      else:
         f = text_boxes.field_of(group, name)
         v = None if f is not None and f.optional and w.value() == w.minimum() else w.value()
      if text_boxes.value(style, group, name) != v:
         self._set(group, name, v, f"{group} {name}")

   def _font_chosen(self) -> None:
      """!The font combo changed.
      @return None
      """
      style = self.style()
      if not self._filling and style is not None and (style.get("font") or "") != self.font_box.currentText():
         self._set("", "font", self.font_box.currentText() or None, "Font")

   def set_control_font(self, number: int | None = None, font: str | None = None) -> bool:
      """!Gives a Font control number a font.
      @param number  the number, or None for the spin's
      @param font    a font asset's key, or None for the combo's
      @return True when it went through
      """
      doc, key = self.doc, self.key
      n = self.control_number.value() if number is None else number
      f = font if font is not None else self.control_font.currentText()
      if key is None or not f:
         return False
      return self.host.run_edit("Font control", lambda: text_boxes.set_control_font(doc, key, n, f))

   def remove_control_font(self, number: int | None = None) -> bool:
      """!Takes a Font control number out (the selected row's, or a number's).
      @param number  the number, or None for the selected row's
      @return True when it went through
      """
      doc, key = self.doc, self.key
      row = self.control_fonts.currentRow()
      if number is None and row >= 0:
         number = int(self.control_fonts.item(row, 0).text())
      if key is None or number is None:
         return False
      return self.host.run_edit("Font control", lambda: text_boxes.set_control_font(doc, key, number, None))

   def _pick_color(self, entry: int) -> None:
      """!Asks for a preview colour.
      @param entry  the palette entry
      @return None
      """
      style = self.style()
      if style is None:
         return
      pens = text_boxes.pens(style)
      c = QtWidgets.QColorDialog.getColor(QtGui.QColor(*pens.color(entry)), self, f"Entry {entry}")
      if c.isValid():
         self.set_color(entry, (c.red(), c.green(), c.blue()))

   def set_color(self, entry: int, color: tuple[int, int, int]) -> bool:
      """!Changes one bank colour: the style's palette when it stores one (entries 1-15), else the preview's.
      @param entry  the palette entry
      @param color  8-bit RGB
      @return True when it went through
      """
      style = self.style()
      if style is None:
         return False
      colors = [text_render.color_text(c) for c in text_boxes.pens(style).colors]
      colors[entry] = text_render.color_text(color)
      if entry and text_boxes.stored_palette(style) is not None:
         return self._set("", text_boxes.PALETTE_KEY, colors[1:], "Bank colour")
      return self._set("preview", "colors", colors, "Preview colour")

   def set_stored_palette(self, on: bool) -> bool:
      """!stores the bank's colours in the style (its palette: entries 1-15 as shown) or leaves them out.
      @param on  store them
      @return True when it went through
      """
      style, filling = self.style(), self._filling   # local aliases (Doxygen 1.12 reads `or self.x:` as a member)
      if style is None or filling:
         return False
      colors = [text_render.color_text(c) for c in text_boxes.pens(style).colors]
      return self._set("", text_boxes.PALETTE_KEY, colors[1:] if on else None, "Palette")

   def set_frame_palette(self, on: bool) -> bool:
      """!gives the frame its own bank colours (a copy of the window's) or takes them away.
      @param on  own colours
      @return True when it went through
      """
      style, filling = self.style(), self._filling   # local aliases (see set_stored_palette())
      if style is None or filling:
         return False
      colors = [text_render.color_text(c) for c in text_boxes.pens(style).colors]
      return self._set("frame", text_boxes.FRAME_PALETTE_KEY, colors[1:] if on else None, "Frame palette")

   def _pick_frame_color(self, entry: int) -> None:
      """!asks for a frame bank colour.
      @param entry  the palette entry (1-15)
      @return None
      """
      style = self.style()
      if style is None or not entry:
         return
      pens = text_boxes.frame_pens(style)
      c = QtWidgets.QColorDialog.getColor(QtGui.QColor(*pens.color(entry)), self, f"Frame entry {entry}")
      if c.isValid():
         self.set_frame_color(entry, (c.red(), c.green(), c.blue()))

   def set_frame_color(self, entry: int, color: tuple[int, int, int]) -> bool:
      """!changes one frame bank colour (the frame gets its own palette).
      @param entry  the palette entry (1-15)
      @param color  8-bit RGB
      @return True when it went through
      """
      style = self.style()
      if style is None or not entry:
         return False
      colors = [text_render.color_text(c) for c in text_boxes.frame_pens(style).colors]
      colors[entry] = text_render.color_text(color)
      return self._set("frame", text_boxes.FRAME_PALETTE_KEY, colors[1:], "Frame colour")

   def _arrow_changed(self) -> None:
      """!an arrow image setting's editor changed.
      @return None
      """
      style = self.style()
      if self._filling or style is None:
         return
      path = self.arrow_path.text().strip()
      if not path:
         if text_boxes.arrow_image(style) is not None:
            self.set_arrow_image(None)
         return
      arrow: dict[str, Any] = {"image": path}
      try:
         steps = [int(v) for v in self.arrow_steps.text().replace(",", " ").split()]
      except ValueError:
         self.host.show_status("arrow steps are numbers (image rows), e.g. 0, 1, 2, 1")
         return
      arrow["steps"] = steps or list(text_boxes.NEW_ARROW["steps"])
      arrow["delay"] = self.arrow_delay.value()
      if self.arrow_height.value():
         arrow["height"] = self.arrow_height.value()
      if arrow != text_boxes.arrow_image(style):
         self.set_arrow_image(arrow)

   def set_arrow_image(self, arrow: dict[str, Any] | None) -> bool:
      """!gives the window an arrow image ({image, height, steps, delay}) or takes it away.
      @param arrow  the settings, or None
      @return True when it went through
      """
      return self._set("window", text_boxes.ARROW_IMAGE_KEY, arrow, "Arrow image")

   def _frame_entries_changed(self) -> None:
      """!The frame art entries changed.
      @return None
      """
      style = self.style()
      if self._filling or style is None:
         return
      values = [s.value() for s in self.frame_entries]
      if (text_boxes.preview_data(style).get("frame_entries") or []) != values:
         self._set("preview", "frame_entries", values, "Frame art")

   def _frame_image_changed(self) -> None:
      """!The frame image changed (the frame's own "image", menus data).
      @return None
      """
      style = self.style()
      if self._filling or style is None:
         return
      text = self.frame_image.text().strip() or None
      if text_boxes.frame_image(style) != text:
         self._set("frame", text_boxes.FRAME_IMAGE_KEY, text, "Frame image")

   def add_style(self, key: str | None = None, like: str | None = None) -> None:
      """!Adds a style.
      @param key   its key (text_box:NAME or NAME), or None to ask
      @param like  a style to copy, or None
      @return None
      """
      if key is None:
         key, ok = QtWidgets.QInputDialog.getText(self, "New text box style", "Key:", text="text_box:MESSAGE")
         if not ok:
            return
      doc = self.doc
      font = self.font_box.itemText(1) if self.font_box.count() > 1 and like is None else None
      try:
         full = text_boxes.full_key(key)
      except DocumentError as e:
         self.host.show_status(str(e))
         return
      if self.host.run_edit("Add text box", lambda: text_boxes.add_style(doc, full, font, like)):
         self.key = full
         self.refresh()

   def copy_style(self) -> None:
      """!Copies the style shown under a new key.
      @return None
      """
      if self.key is not None:
         key, ok = QtWidgets.QInputDialog.getText(self, "Copy text box style", "Key:", text=f"{self.key}_COPY")
         if ok:
            self.add_style(key, self.key)

   def rename_style(self, new: str | None = None) -> bool:
      """!Gives the style shown another key.
      @param new  the key, or None to ask
      @return True when it went through
      """
      if self.key is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename text box style", "Key:", text=self.key)
         if not ok:
            return False
      try:
         full = text_boxes.full_key(new)
      except DocumentError as e:
         self.host.show_status(str(e))
         return False
      if self._set("", "key", full, "Rename text box"):
         self.key = full
         self.refresh()
         return True
      return False

   def remove_style(self) -> None:
      """!Removes the style shown.
      @return None
      """
      doc, key = self.doc, self.key
      if key is not None and self.host.run_edit("Remove text box", lambda: text_boxes.remove_style(doc, key)):
         self.key = None
         self.refresh()

   def migrate(self) -> bool:
      """!turns the older studio's editor-data styles into text_box assets (one undo step).
      @return True when it went through
      """
      doc = self.doc
      done: list[Any] = []
      if not text_boxes.legacy_styles(doc):
         return False
      if self.host.run_edit("Text box assets", lambda: done.extend(text_boxes.migrate(doc))):
         dropped = [f"{name}: {', '.join(d)}" for name, _key, d in done if d]
         self.host.show_status(f"{len(done)} styles are text_box assets" +
                               (f" (left out: {'; '.join(dropped)})" if dropped else ""))
         self.key = done[0][1] if done else self.key
         self.refresh()
         return True
      return False

   def apply_to_table(self, path: Path | None = None, font_name: str | None = None) -> bool:
      """!Gives a table's box this style's width and lines (one undo step of the table).
      @param path       the table, or None for the chosen one
      @param font_name  the table's name of the style's font, or None for the table box's
      @return True when it went through
      """
      s, style = self.session(), self.style()
      data = self.table_box.currentData()
      path = path if path is not None else (Path(data) if data else None)
      if s is None or style is None or path is None:
         return False
      table = s.table(path)
      name = font_name if font_name is not None else text_tables.box(table).get("font")
      b = text_boxes.fit_box(style, name)
      done = self.host.run_edit("Box from style", lambda: text_tables.set_box(table, b.get("font"), b["width"],
                                                                             b["lines"]), document=table)
      self.host.selection_changed()
      return done

   def extra_documents(self) -> list[Document]:
      """!The tables and fonts the text panels opened.
      @return Documents
      """
      s = self.session()
      return s.documents() if s is not None else []


def _paint(swatches: list[QtWidgets.QPushButton], pens: text_render.Pens) -> None:
   """!Colours a row of swatches with a bank's colours.
   @param swatches  the buttons, by entry
   @param pens      the colours
   @return None
   """
   for i, b in enumerate(swatches):
      c = pens.color(i)
      b.setStyleSheet(f"background: {text_render.color_text(c)}; color: "
                      f"{'#000000' if sum(c) > BRIGHT_SUM else '#ffffff'};")
