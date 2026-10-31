"""!Text tables panel [S2] (engine I4: capsule.texts/1): the texts of the tables an asset manifest reaches, edited
with the engine's fit check as you type.

Left: the table (and its language), a filter, the texts with a mark for those that do not fit or compile, and
Add / Rename / Remove. Middle: the text with its markup coloured (MarkupHighlighter) and an Insert menu (the
control codes with their arguments, the placeholders, terms and named glyphs), its wrap mode ("original": the
authored breaks kept and every line checked against the box; "auto": broken to the box at spaces) and font, the
lines measured against the box by the engine's rule (core.text_tables.check_text(): a line wider than the box in
red, a line with a placeholder measured without its text marked), the same key in the other languages' tables,
and the table's box (font, width, lines) with its fit summary. S4 (engine C10): Languages shows the table's keys
with their text in every language of the manifest side by side (one manifest lists every language's tables, or
their translations sit in sibling folders), a key a language lacks marked missing or taken from the manifest's
fallback language, the missing keys per language, and the table's own language (none: every language). The build
language and fallback are the Manifest panel's. Right: the box as the game shows it, one wait at a time (a text box
style of the manifest when it has one, typed as the engine types it: core.text_boxes.preview(); else the bare
box).

Every edit is one undo step of the table's Document (host.run_edit(document=...)); typing commits after a pause.
The tables are saved with the manifest (extra_documents()).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import asset_tables, engine, text_boxes, text_render, text_tables
from ...core.document import Document, DocumentError
from ..panel import EditorPanel
from ..qtimage import to_qimage
from ..panes import split_box
from ..widgets import DEBOUNCE_MS, Debounce, PixelView, button, set_enabled
from .text_common import MarkupHighlighter, control_menu, session_of

if TYPE_CHECKING:
   from ..panel import PanelHost
   from .text_common import TextSession

## Mark of a text that does not fit or does not compile.
PROBLEM_MARK = "!"
## Colour of a line wider than the box.
OVER_COLOR = "#d03030"
## Colour of a line measured without its placeholders' text.
UNMEASURED_COLOR = "#b08010"
## Screen pixels per preview pixel.
PREVIEW_ZOOM = 2
## Columns of the fit list: line, width / box, text.
FIT_COLUMNS = ["Line", "Width", "Text"]
## Width of the fit list's Line and Width columns, pixels.
FIT_NUMBER_WIDTH = 70
## Stretch of the list column, the editor column and the preview column.
LIST_STRETCH, EDITOR_STRETCH, PREVIEW_STRETCH = 2, 4, 3
## Stretch of the text against the fit list under it (1).
TEXT_STRETCH = 2
## Box widths and line counts the box spins allow (the compiler takes any non-negative number).
BOX_MAX = 4095
## The "font of the box" entry of a text's font combo.
BOX_FONT = "(the box's font)"
## Pixels around the bare box preview.
BARE_MARGIN = 4
## S4: the languages grid's first column.
KEY_COLUMN = "Key"
## S4: what a language the key lacks shows.
MISSING_TEXT = "(missing)"
## S4: colour of a text the fallback language gives.
FALLBACK_COLOR = "#7070a0"
## S4: missing keys the Languages box names per language.
MISSING_SHOWN = 8
## S4: the table language combo's entry of a table without one.
EVERY_LANGUAGE_TEXT = "(every language)"
## S4: rows of the languages grid before it scrolls.
GRID_ROWS = 6


class TextTablesPanel(EditorPanel):
   """!Edits the text tables of the host's asset manifest."""

   ## See EditorPanel.panel_id.
   panel_id = "text_tables"
   ## See EditorPanel.title.
   title = "Text tables"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The table shown, or None.
      self.table_path = None
      ## The text shown, or None.
      self.key = None
      ## True while the panel fills its widgets.
      self._filling = False
      ## The last fit of the text shown.
      self.fit = None
      ## The table's fit (counted on refresh).
      self.table_fit = None
      ## The tables the manifest reaches (and their translations).
      self.table = QtWidgets.QComboBox()
      self.table.currentIndexChanged.connect(lambda _i: self._table_chosen())
      ## Filters the keys (part of a key or of a text).
      self.filter = QtWidgets.QLineEdit()
      self.filter.setPlaceholderText("Filter keys and texts")
      self.filter.textChanged.connect(lambda _t: self._fill_list())
      ## The table's texts.
      self.list = QtWidgets.QListWidget()
      self.list.currentItemChanged.connect(lambda item, _old: self._chosen(item))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Table"))
      left.addWidget(self.table)
      left.addWidget(self.filter)
      left.addWidget(self.list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_text()))
      row.addWidget(button("Rename...", lambda: self.rename_text()))
      row.addWidget(button("Remove", lambda: self.remove_text()))
      left.addLayout(row)
      ## The text's markup.
      self.edit = QtWidgets.QPlainTextEdit()
      self.edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)   # the authored breaks only
      self.edit.textChanged.connect(lambda: self._typed())
      ## Colours its markup.
      self.highlighter = MarkupHighlighter(self.edit.document())
      ## Wrap mode.
      self.wrap = QtWidgets.QComboBox()
      self.wrap.setToolTip("original: the authored breaks stay and each line must fit the box; auto: broken to the "
                           "box at spaces, a new page after the box's lines")
      self.wrap.currentTextChanged.connect(lambda _t: self._wrap_chosen())
      ## The text's font.
      self.font_box = QtWidgets.QComboBox()
      self.font_box.currentTextChanged.connect(lambda _t: self._font_chosen())
      ## Inserts markup.
      self.insert = QtWidgets.QPushButton("Insert")
      self.insert.setToolTip("Insert a control code, a placeholder, a term or a named glyph at the cursor")
      self.insert.clicked.connect(lambda _c=False: self._insert_menu())
      bar = QtWidgets.QHBoxLayout()
      bar.addWidget(QtWidgets.QLabel("Wrap"))
      bar.addWidget(self.wrap)
      bar.addWidget(QtWidgets.QLabel("Font"))
      bar.addWidget(self.font_box, 1)
      bar.addWidget(self.insert)
      ## The lines against the box.
      self.lines = QtWidgets.QTreeWidget()
      self.lines.setHeaderLabels(FIT_COLUMNS)
      self.lines.setRootIsDecorated(False)
      for i in range(len(FIT_COLUMNS) - 1):
         self.lines.setColumnWidth(i, FIT_NUMBER_WIDTH)
      ## The fit verdict.
      self.verdict = QtWidgets.QLabel()
      self.verdict.setWordWrap(True)
      ## The key in the other languages.
      self.others = QtWidgets.QLabel()
      self.others.setWordWrap(True)
      # the table's box
      ## Box font.
      self.box_font = QtWidgets.QComboBox()
      ## Box width, pixels.
      self.box_width = QtWidgets.QSpinBox()
      self.box_width.setRange(0, BOX_MAX)
      self.box_width.setSuffix(" px")
      ## Lines per page.
      self.box_lines = QtWidgets.QSpinBox()
      self.box_lines.setRange(0, BOX_MAX)
      for w in (self.box_width, self.box_lines):
         w.editingFinished.connect(lambda: self._box_changed())
      self.box_font.activated.connect(lambda _i: self._box_changed())
      box_row = QtWidgets.QHBoxLayout()
      for label, w in (("Box font", self.box_font), ("Width", self.box_width), ("Lines", self.box_lines)):
         box_row.addWidget(QtWidgets.QLabel(label))
         box_row.addWidget(w)
      ## The table's fit summary.
      self.summary = QtWidgets.QLabel()
      self.summary.setWordWrap(True)
      # S4 (C10): the languages side by side
      languages = QtWidgets.QGroupBox("Languages")
      lv = QtWidgets.QVBoxLayout(languages)
      lrow = QtWidgets.QHBoxLayout()
      ## The table's own language (none: every language).
      self.table_language = QtWidgets.QComboBox()
      self.table_language.setEditable(True)
      self.table_language.setToolTip("The table's \"language\" (a table without one is in every language of the "
                                     "manifest); the build language and its fallback are set in the Manifest panel")
      self.table_language.activated.connect(lambda _i: self._table_language_chosen())
      self.table_language.lineEdit().editingFinished.connect(lambda: self._table_language_chosen())
      lrow.addWidget(QtWidgets.QLabel("This table's language"))
      lrow.addWidget(self.table_language, 1)
      ## Only the keys some language lacks.
      self.missing_only = QtWidgets.QCheckBox("Missing only")
      self.missing_only.toggled.connect(lambda _on: self._fill_languages())
      lrow.addWidget(self.missing_only)
      lv.addLayout(lrow)
      ## The table's keys with their text in each language.
      self.grid = QtWidgets.QTableWidget()
      self.grid.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.grid.setWordWrap(False)   # one line a text (its newlines shown as \\n), cut at the column's end
      self.grid.verticalHeader().setVisible(False)
      self.grid.horizontalHeader().setStretchLastSection(True)
      self.grid.setMinimumHeight(self.fontMetrics().height() * GRID_ROWS)
      self.grid.cellClicked.connect(lambda row, _col: self._grid_chosen(row))
      lv.addWidget(self.grid, 1)
      ## The manifest's languages, its build language and the missing keys per language.
      self.missing = QtWidgets.QLabel()
      self.missing.setWordWrap(True)
      lv.addWidget(self.missing)
      middle = QtWidgets.QVBoxLayout()
      middle.addLayout(bar)
      middle.addWidget(self.edit, TEXT_STRETCH)
      middle.addWidget(self.verdict)
      middle.addWidget(self.lines, 1)
      middle.addWidget(self.others)
      middle.addLayout(box_row)
      middle.addWidget(self.summary)
      middle.addWidget(languages, TEXT_STRETCH)
      split_box(middle)   # [RZ] text / lines / languages, stacked
      ## The text box style the preview uses.
      self.style_box = QtWidgets.QComboBox()
      self.style_box.currentIndexChanged.connect(lambda _i: self._update_preview())
      ## Which wait of the text the preview shows.
      self.screen = QtWidgets.QSpinBox()
      self.screen.valueChanged.connect(lambda _v: self._update_preview())
      ## The preview.
      self.view = PixelView(PREVIEW_ZOOM)
      right = QtWidgets.QVBoxLayout()
      prow = QtWidgets.QHBoxLayout()
      prow.addWidget(QtWidgets.QLabel("Style"))
      prow.addWidget(self.style_box, 1)
      prow.addWidget(QtWidgets.QLabel("Wait"))
      prow.addWidget(self.screen)
      right.addLayout(prow)
      right.addWidget(self.view, 1)
      layout = QtWidgets.QHBoxLayout(self)
      for part, stretch in ((left, LIST_STRETCH), (middle, EDITOR_STRETCH), (right, PREVIEW_STRETCH)):
         holder = QtWidgets.QWidget()
         holder.setLayout(part)
         layout.addWidget(holder, stretch)
      split_box(layout)   # [RZ] tables | editor | preview: the user drags the boundaries
      ## Commits typing as one undo step after a pause.
      self.commit = Debounce(lambda: self._commit(), DEBOUNCE_MS, self)
      ## Re-checks the table after edits.
      self.recount = Debounce(lambda: self._count_table(), DEBOUNCE_MS, self)

   # -- documents ------------------------------------------------------------------------------------------------

   def session(self) -> TextSession | None:
      """!The host's text session.
      @return TextSession, or None (an unsaved manifest)
      """
      host = self.host   # a local alias (Doxygen reads `self.x` returned here as a new member)
      return session_of(host)

   def table_doc(self) -> Document | None:
      """!The table shown.
      @return its Document, or None
      """
      s = self.session()
      if s is None or self.table_path is None:
         return None
      try:
         return s.table(self.table_path)
      except DocumentError as e:
         self.host.show_status(str(e))
         return None

   def current_document(self) -> Document | None:
      """!Undo / Redo act on the table shown.
      @return its Document, or the manifest
      """
      host = self.host   # a local alias (see session())
      return self.table_doc() or getattr(host, "document", None)

   def extra_documents(self) -> list[Document]:
      """!The tables and fonts the text panels opened (saved with the manifest).
      @return Documents
      """
      s = self.session()
      return s.documents() if s is not None else []

   # -- filling ---------------------------------------------------------------------------------------------------

   def document_replaced(self) -> None:
      """!Another manifest: its first table.
      @return None
      """
      self.table_path = None
      self.key = None
      self.refresh()

   def refresh(self) -> None:
      """!Re-reads the tables, the text and the box.
      @return None
      """
      self._filling = True
      try:
         s = self.session()
         refs = s.table_refs() if s is not None else []
         paths = [r.path for r in refs]
         if self.table_path not in paths:
            self.table_path = paths[0] if paths else None
         self.table.clear()
         for r in refs:
            self.table.addItem(f"{r.label} [{r.language}]", str(r.path))
         if self.table_path is not None:
            self.table.setCurrentIndex(paths.index(self.table_path))
         if s is not None:
            self.highlighter.set_names(s.context)
         self._fill_styles()
      finally:
         self._filling = False
      self._fill_table()

   def _fill_styles(self) -> None:
      """!The text box styles the preview may use.
      @return None
      """
      doc = getattr(self.host, "document", None)
      names = text_boxes.keys(doc) if doc is not None else []   # S4: text_box assets
      current = self.style_box.currentText()
      self.style_box.clear()
      self.style_box.addItems(["(the bare box)"] + names)
      if current in names:
         self.style_box.setCurrentText(current)
      elif names:
         self.style_box.setCurrentIndex(1)

   def _fill_table(self) -> None:
      """!Shows the table: its box, its texts and the text chosen.
      @return None
      """
      doc = self.table_doc()
      self._filling = True
      try:
         box = text_tables.box(doc) if doc is not None else {}
         fonts = list((doc.data.get("fonts") or {})) if doc is not None else []
         self.box_font.clear()
         self.box_font.addItems([""] + fonts)
         self.box_font.setCurrentText(str(box.get("font") or ""))
         self.box_width.setValue(int(box.get("width", 0) or 0))
         self.box_lines.setValue(int(box.get("lines", 0) or 0))
         self.font_box.clear()
         self.font_box.addItems([BOX_FONT] + fonts)
         self.wrap.clear()
         self.wrap.addItems(text_tables.wrap_modes())
         s = self.session()
         langs = asset_tables.languages(s.manifest, s.tables) if s is not None else []
         self.table_language.clear()
         self.table_language.addItems([EVERY_LANGUAGE_TEXT] + langs)
         lang = doc.data.get("language") if doc is not None else None
         self.table_language.setCurrentText(str(lang) if lang else EVERY_LANGUAGE_TEXT)
         self.table_language.setEnabled(doc is not None)
      finally:
         self._filling = False
      self._count_table()
      self._fill_list()
      self._fill_languages()

   def _count_table(self) -> None:
      """!Fits the whole table (the summary and the list's marks).
      @return None
      """
      s, doc = self.session(), self.table_doc()
      if s is None or doc is None:
         self.table_fit = None
         self.summary.setText("Save the manifest and list text tables in it (Manifest panel) to edit them here.")
         return
      try:
         self.table_fit = text_tables.check_table(s.context, doc)
      except (DocumentError, engine.EngineNotFound) as e:
         self.summary.setText(str(e))
         return
      f = self.table_fit
      self.summary.setText(f"{f.checked} authored texts checked against the box: {f.over} lines wider "
                           f"({f.with_placeholders} lines with placeholders measured without them), "
                           f"{len(f.problems)} texts with problems" + (f"; {s.problem}" if s.problem else ""))
      self._mark_list()

   def _fill_list(self) -> None:
      """!The texts matching the filter.
      @return None
      """
      doc = self.table_doc()
      rows = text_tables.rows(doc) if doc is not None else []
      needle = self.filter.text().strip().lower()
      shown = [r.key for r in rows if not needle or needle in r.key.lower() or needle in r.text.lower()]
      self._filling = True
      try:
         self.list.clear()
         for key in shown:
            self.list.addItem(key)
         if self.key not in shown:
            self.key = shown[0] if shown else None
         if self.key is not None:
            self.list.setCurrentRow(shown.index(self.key))
      finally:
         self._filling = False
      self._mark_list()
      self._fill_text()

   def _mark_list(self) -> None:
      """!Marks the texts that do not fit or compile.
      @return None
      """
      bad = {p.key for p in self.table_fit.problems} if self.table_fit is not None else set()
      for i in range(self.list.count()):
         item = self.list.item(i)
         key = item.data(QtCore.Qt.ItemDataRole.UserRole) or item.text()
         item.setData(QtCore.Qt.ItemDataRole.UserRole, key)
         item.setText(f"{PROBLEM_MARK} {key}" if key in bad else key)
         item.setForeground(QtGui.QColor(OVER_COLOR) if key in bad else self.palette().text().color())

   def _fill_text(self) -> None:
      """!Shows the chosen text.
      @return None
      """
      doc = self.table_doc()
      row = None
      if doc is not None and self.key is not None:
         try:
            row = text_tables.entry(doc, self.key)
         except DocumentError:
            row = None
      self._filling = True
      try:
         for w in (self.edit, self.wrap, self.font_box, self.insert):
            set_enabled(w, row is not None)   # the text goes read-only and keeps its scroll bar
         value = row.text if row is not None else ""
         if self.edit.toPlainText() != value:
            self.edit.setPlainText(value)
         if row is not None:
            self.wrap.setCurrentText(row.wrap)
            self.font_box.setCurrentText(row.font if row.font else BOX_FONT)
      finally:
         self._filling = False
      self._fill_others()
      self._update_fit()

   def _fill_others(self) -> None:
      """!The chosen key's text in the other languages' tables.
      @return None
      """
      s = self.session()
      if s is None or self.key is None:
         self.others.setText("")
         return
      out = []
      doc = self.table_doc()
      language = str(doc.data.get("language", "")) if doc is not None else ""
      for ref in s.table_refs():
         if ref.path == self.table_path or ref.language == language:
            continue   # only the other languages' tables are opened
         try:
            other = s.table(ref.path)
         except DocumentError:
            continue
         texts = other.data.get("texts") or {}
         if self.key in texts:
            entry = texts[self.key]
            out.append(f"[{ref.language}] {entry if isinstance(entry, str) else entry.get('text', '')}")
      self.others.setText("\n".join(out))

   # -- fit and preview ------------------------------------------------------------------------------------------

   def _update_fit(self) -> None:
      """!Fits the text as typed (the engine's rule) and redraws the preview.
      @return None
      """
      s, doc = self.session(), self.table_doc()
      self.lines.clear()
      self.fit = None
      if s is None or doc is None or self.key is None:
         self.verdict.setText("")
         self.view.set_image(None)
         return
      typed = self.edit.toPlainText()
      try:
         # the typed text is fitted before it is committed: a scratch copy of the table holds it
         scratch = Document(dict(doc.data, texts=dict(doc.data.get("texts") or {})), doc.path, text_tables.SCHEMA)
         entry = scratch.data["texts"].get(self.key)
         scratch.data["texts"][self.key] = dict(entry, text=typed) if isinstance(entry, dict) else typed
         self.fit = text_tables.check_text(s.context, scratch, self.key)
      except (DocumentError, engine.EngineNotFound) as e:
         self.verdict.setText(str(e))
         return
      f = self.fit
      for line in f.lines:
         item = QtWidgets.QTreeWidgetItem([str(line.number), f"{line.width}/{line.box}", line.text])
         if line.over:
            for c in range(len(FIT_COLUMNS)):
               item.setForeground(c, QtGui.QColor(OVER_COLOR))
            item.setToolTip(1, f"{line.width - line.box} pixels wider than the box")
         elif line.unmeasured:
            item.setForeground(1, QtGui.QColor(UNMEASURED_COLOR))
            item.setToolTip(1, "a placeholder counts nothing here: the game's text may be longer")
         self.lines.addTopLevelItem(item)
      if f.error:
         self.verdict.setText(f"Does not compile: {f.error}")
         self.verdict.setStyleSheet(f"color: {OVER_COLOR};")
      elif f.over:
         worst = max(f.over, key=lambda n: n.width)
         self.verdict.setText(f"{len(f.over)} line(s) wider than the box ({f.box_width} px): line {worst.number} is "
                              f"{worst.width} px")
         self.verdict.setStyleSheet(f"color: {OVER_COLOR};")
      else:
         self.verdict.setText("Fits the box." if f.lines else
                              ("Broken to the box at spaces (auto)." if f.box_width else "No box to fit."))
         self.verdict.setStyleSheet("")
      self._update_preview()

   def _update_preview(self) -> None:
      """!Draws the text in its box, the chosen wait.
      @return None
      """
      s, doc, f = self.session(), self.table_doc(), self.fit
      if s is None or doc is None or f is None or f.error or f.font is None or self._filling:
         if f is None or f.error:
            self.view.set_image(None)
         return
      try:
         font = s.context.font(f.font)
         style = self._style()
         if style is not None:
            # S4: typed as the engine types it in the style (the table's font), a press at each wait
            run = text_boxes.typing(style, font, f.codes, placeholders=s.context.placeholder_codes())
            self._set_screens(len(text_boxes.wait_frames(run)))
            canvas = text_boxes.preview(style, font, f.codes, self.screen.value(), self.host.document.base_dir,
                                        s.context.placeholder_codes(), run=run)
         else:
            lines = int(text_tables.box(doc).get("lines", 1) or 1)
            shown = text_render.screens(f.codes, lines, s.context.placeholder_codes())
            self._set_screens(len(shown))
            canvas = self._bare_box(font, shown[min(self.screen.value(), len(shown) - 1)], lines, f.box_width)
      except (DocumentError, engine.EngineNotFound) as e:
         self.host.show_status(str(e))
         return
      self.view.set_image(to_qimage(*canvas.image()))

   def _style(self) -> dict | None:
      """!The text box style chosen for the preview.
      @return the style, or None (the bare box)
      """
      doc = getattr(self.host, "document", None)
      name = self.style_box.currentText()
      if doc is None or self.style_box.currentIndex() <= 0:
         return None
      try:
         return text_boxes.find(doc, name)
      except DocumentError:
         return None

   def _set_screens(self, count: int) -> None:
      """!The wait spin's range.
      @param count  screens of the text
      @return None
      """
      self.screen.blockSignals(True)
      self.screen.setRange(0, max(0, count - 1))
      self.screen.setSuffix(f" of {count}")
      self.screen.blockSignals(False)

   def _bare_box(self, font: dict, lines: list, count: int, width: int) -> text_render.Canvas:
      """!A box of the table's width and lines with one screen of text.
      @param font   compiled font
      @param lines  the screen's lines
      @param count  lines the box shows
      @param width  box width, pixels
      @return Canvas
      """
      pens = text_render.preview_pens()
      w = max(width, 1) + BARE_MARGIN + BARE_MARGIN
      h = count * font["line_height"] + BARE_MARGIN + BARE_MARGIN
      canvas = text_render.Canvas(w, h, pens.color(pens.background))
      text_render.draw_lines(canvas, font, lines, BARE_MARGIN, BARE_MARGIN, pens)
      return canvas

   # -- edits ------------------------------------------------------------------------------------------------------

   def _edit(self, label: str, fn: object) -> bool:
      """!One undo step of the table.
      @param label  undo label
      @param fn     the edit
      @return True when it went through
      """
      doc = self.table_doc()
      if doc is None:
         return False
      done = self.host.run_edit(label, fn, document=doc)
      self.host.selection_changed()
      self.recount.poke()
      return done

   def _table_chosen(self) -> None:
      """!Another table.
      @return None
      """
      if self._filling:
         return
      self.commit.flush()
      data = self.table.currentData()
      self.table_path = Path(data) if data else None
      self.key = None
      self._fill_table()
      self.host.selection_changed()

   def _chosen(self, item: QtWidgets.QListWidgetItem | None) -> None:
      """!Another text.
      @param item  its list item
      @return None
      """
      if self._filling or item is None:
         return
      key = item.data(QtCore.Qt.ItemDataRole.UserRole) or item.text()
      QtCore.QTimer.singleShot(0, lambda: self._switch_to(key))

   def _switch_to(self, key: str) -> None:
      """!Writes pending typing, then shows another text.
      @param key  its key
      @return None
      """
      self.commit.flush()
      self.key = key
      self._fill_text()

   def _typed(self) -> None:
      """!The text changed in the editor.
      @return None
      """
      if self._filling:
         return
      self._update_fit()
      self.commit.poke()

   def _commit(self) -> None:
      """!Writes the typed text.
      @return None
      """
      doc, key = self.table_doc(), self.key
      if doc is None or key is None:
         return
      value = self.edit.toPlainText()
      try:
         same = text_tables.entry(doc, key).text == value
      except DocumentError:
         return
      if not same:
         self._edit("Edit text", lambda: text_tables.set_text(doc, key, value))
         self._mark_list()
         self._fill_languages()   # S4: the key's text in the languages grid

   def _wrap_chosen(self) -> None:
      """!The wrap combo changed.
      @return None
      """
      doc, key = self.table_doc(), self.key
      if self._filling or doc is None or key is None:
         return
      mode = self.wrap.currentText()
      self.commit.flush()
      self._edit("Wrap", lambda: text_tables.set_wrap(doc, key, mode))
      self._update_fit()

   def _font_chosen(self) -> None:
      """!The font combo changed.
      @return None
      """
      doc, key = self.table_doc(), self.key
      if self._filling or doc is None or key is None:
         return
      font = self.font_box.currentText()
      self.commit.flush()
      self._edit("Font", lambda: text_tables.set_text_font(doc, key, None if font == BOX_FONT else font))
      self._update_fit()

   def _box_changed(self) -> None:
      """!The box fields changed.
      @return None
      """
      doc = self.table_doc()
      if self._filling or doc is None:
         return
      font = self.box_font.currentText() or None
      width, lines = self.box_width.value(), self.box_lines.value()
      b = text_tables.box(doc)
      if (b.get("font"), b.get("width", 0), b.get("lines", 0)) == (font, width, lines):
         return
      self._edit("Box", lambda: text_tables.set_box(doc, font, width or None, lines or None))
      self._update_fit()

   def _insert_menu(self) -> None:
      """!Opens the Insert menu under its button.
      @return None
      """
      s = self.session()
      if s is None:
         return
      menu = control_menu(self, s.context, lambda m: self.insert_markup(m))
      menu.exec(self.insert.mapToGlobal(self.insert.rect().bottomLeft()))

   def insert_markup(self, markup: str) -> None:
      """!Inserts markup at the cursor.
      @param markup  e.g. "{pause:15}"
      @return None
      """
      self.edit.textCursor().insertText(markup)
      self.edit.setFocus()

   def _other_keys(self) -> list[str]:
      """!The keys of the manifest's other tables a build takes with this one (a key names one asset of a build:
      S4, C10: the tables of the same language, or of every language; another language's table holds the same keys).
      @return keys
      """
      s = self.session()
      out: list[str] = []
      if s is None:
         return out
      doc = self.table_doc()
      mine = str(doc.data.get("language", "")) if doc is not None else ""
      for ref in s.table_refs():
         same_build = ref.listed and (not mine or not ref.language or ref.language == mine)
         if ref.path != self.table_path and same_build:
            try:
               out += list(s.table(ref.path).data.get("texts") or {})
            except DocumentError:
               continue
      return out

   def add_text(self, key: str | None = None) -> None:
      """!Adds a text to the table.
      @param key  its key, or None to ask
      @return None
      """
      doc = self.table_doc()
      if doc is None:
         return
      self.commit.flush()
      if key is None:
         key, ok = QtWidgets.QInputDialog.getText(self, "New text", "Key:", text="text:NEW")
         if not ok:
            return
      key = key.strip()
      others = self._other_keys()
      if key and self._edit("New text", lambda: text_tables.add_text(doc, key, "", None, others)):
         self.key = key
         self._fill_list()

   def rename_text(self, new: str | None = None) -> None:
      """!Renames the text shown.
      @param new  its new key, or None to ask
      @return None
      """
      doc, old = self.table_doc(), self.key
      if doc is None or old is None:
         return
      self.commit.flush()
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename text", "Key:", text=old)
         if not ok:
            return
      new = new.strip()
      others = self._other_keys()
      if new and new != old and self._edit("Rename text", lambda: text_tables.rename_text(doc, old, new, others)):
         self.key = new
         self._fill_list()

   def remove_text(self) -> None:
      """!Removes the text shown.
      @return None
      """
      doc, key = self.table_doc(), self.key
      if doc is None or key is None:
         return
      self.commit.flush()
      if self._edit("Remove text", lambda: text_tables.remove_text(doc, key)):
         self.key = None
         self._fill_list()

   def stop(self) -> None:
      """!Writes pending typing.
      @return None
      """
      self.commit.flush()

   # -- S4: languages ----------------------------------------------------------------------------------------------

   def _language_docs(self) -> dict[Path, Document]:
      """!Every table the manifest reaches and their translations, opened (a manifest of one language: none).
      @return Documents by path
      """
      s = self.session()
      if s is None:
         return {}
      refs = s.table_refs()
      if len({r.language for r in refs if r.language}) < len(("one", "other")):
         return {}
      out = {}
      for r in refs:
         try:
            out[r.path] = s.table(r.path)
         except DocumentError:
            continue
      return out

   def _fill_languages(self) -> None:
      """!The table's keys with their text per language, the manifest's languages and the missing keys.
      @return None
      """
      s, doc = self.session(), self.table_doc()
      self.grid.clear()
      self.grid.setRowCount(0)
      if s is None or doc is None:
         self.missing.setText("")
         return
      docs = self._language_docs() or {self.table_path: doc}
      matrix = asset_tables.key_matrix(docs)
      langs = sorted({str(d.data.get("language", "")) for d in docs.values()} - {asset_tables.EVERY_LANGUAGE})
      langs = langs or [str(doc.data.get("language", ""))]
      build = asset_tables.build_language(s.manifest, None, s.tables)
      fallback = asset_tables.language_setting(s.manifest, "fallback_language")
      keys = [r.key for r in text_tables.rows(doc)]
      if self.missing_only.isChecked():
         keys = [k for k in keys if any(lang not in matrix.get(k, {}) for lang in langs) and
                 asset_tables.EVERY_LANGUAGE not in matrix.get(k, {})]
      self.grid.setColumnCount(1 + len(langs))
      self.grid.setHorizontalHeaderLabels([KEY_COLUMN] + [f"{lang} (build)" if lang == build else lang
                                                          for lang in langs])
      self.grid.setRowCount(len(keys))
      for r, key in enumerate(keys):
         self.grid.setItem(r, 0, QtWidgets.QTableWidgetItem(key))
         by = matrix.get(key, {})
         for c, lang in enumerate(langs, start=1):
            path = by.get(lang) or by.get(asset_tables.EVERY_LANGUAGE)
            item = QtWidgets.QTableWidgetItem(self._text_of(docs, path, key) if path else MISSING_TEXT)
            if path is None:
               filled = fallback and fallback != lang and fallback in by
               item.setText(f"({fallback}) {self._text_of(docs, by[fallback], key)}" if filled else MISSING_TEXT)
               item.setForeground(QtGui.QColor(FALLBACK_COLOR if filled else OVER_COLOR))
            self.grid.setItem(r, c, item)
      header = self.grid.horizontalHeader()
      header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
      for c in range(1, self.grid.columnCount()):   # the languages share the rest side by side
         header.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeMode.Stretch)
      text = f"Languages: {', '.join(langs) or 'none'}; a build takes {build or 'no language'}" + \
         (f", fallback {fallback}" if fallback else "")
      problem = asset_tables.language_problem(s.manifest, None, s.tables)
      if problem:
         text += f"\nerror: {problem}"
      for lang, missing in asset_tables.missing_translations(docs).items():
         filled = asset_tables.fallback_keys(docs, lang, fallback)
         note = f" ({len(filled)} from {fallback})" if filled else ""
         text += f"\n{lang} lacks {len(missing)} keys{note}: {', '.join(missing[:MISSING_SHOWN])}" + \
            ("..." if len(missing) > MISSING_SHOWN else "")
      self.missing.setText(text)

   @staticmethod
   def _text_of(docs: dict[Path, Document], path: Path, key: str) -> str:
      """!A key's text in a table, on one line.
      @param docs  the tables by path
      @param path  the table
      @param key   the key
      @return the text
      """
      entry = (docs[path].data.get("texts") or {}).get(key) if path in docs else None
      text = entry if isinstance(entry, str) else (entry or {}).get("text", "")
      return str(text).replace("\n", "\\n")

   def _grid_chosen(self, row: int) -> None:
      """!A row of the languages grid: its key in the editor.
      @param row  the row
      @return None
      """
      item = self.grid.item(row, 0)
      if item is not None and item.text() != self.key:
         self._switch_to(item.text())
         self._fill_list()

   def _table_language_chosen(self) -> None:
      """!The table's language changed (one undo step of the table).
      @return None
      """
      doc = self.table_doc()
      if self._filling or doc is None:
         return
      text = self.table_language.currentText().strip()
      value = None if text in ("", EVERY_LANGUAGE_TEXT) else text
      if doc.data.get("language") != value:
         if self._edit("Table language", lambda: text_tables.set_language(doc, value)):
            self.refresh()
