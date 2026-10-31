"""!The Code page panel (C-2, D-20 F): which 8-bit code each character of the
game's language gets.

A 16 x 16 grid shows every code with its character and the glyph the game's
font draws for it (codes after the glyphs are the text controls). Picking a
code shows it below, where it gets a character or loses its one. The list of
unmapped characters names each character the game's texts use that the page
lacks, and where (core.codepage.missing()); one can get the selected code, or
an alias that folds it onto mapped text. The aliases table lists those folds.

The page is a Document of its own (its file is the one reference/project.json
names under "text"), so it has its own undo history: Undo / Redo on this tab
act on it, and saving the project saves it too. A game that uses the
engine's default page gets a copy of its own first.
"""
from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import codepage, engine
from ...core.document import DocumentError
from ..panel import EditorPanel
from ..panes import split_box
from ..widgets import button

if TYPE_CHECKING:
   from ...core.document import Document
   from ..panel import PanelHost

## Codes per grid row and column (the page is 16 x 16).
GRID_SIDE = codepage.ROW_CODES
## Screen pixels per glyph pixel in the grid.
GLYPH_ZOOM = 2
## Pixels of a glyph cell (the font's cells are 8 x 8).
GLYPH_CELL = 8
## Glyph pixel colours (r, g, b, a) by font value: 0 empty, 1 ink, 2 shadow.
GLYPH_COLORS = {0: (0, 0, 0, 0), 1: (24, 24, 32, 255), 2: (150, 150, 165, 255)}
## Background of a grid cell for a code with no character.
FREE_COLOR = "#f4f4f4"
## Background of a grid cell for a control code (not a glyph).
CONTROL_COLOR = "#d0d0d8"
## Width of a grid column, pixels.
COLUMN_WIDTH = 46
## Starting height of the unmapped characters list, pixels (the user drags its boundary).
MISSING_LIST_HEIGHT = 140
## Places a list entry shows of where an unmapped character is used.
USES_SHOWN = 3
## Alias table columns: the folded text, what it encodes as.
ALIAS_COLUMNS = 2
## Longest text the character field takes (a character with its combining marks).
MAX_CHAR_LENGTH = 8
## Layout stretch of the grid column.
GRID_STRETCH = 3
## Layout stretch of the lists column.
LISTS_STRETCH = 2
## Hex digits of a Unicode code point in "U+00E9".
CODE_POINT_DIGITS = 4


def glyph_icon(cell: list[list[int]] | None) -> QtGui.QIcon:
   """!An icon of one font glyph.
   @param cell  8 rows of 8 values (0 empty, 1 ink, 2 shadow), or None
   @return QIcon (empty for None)
   """
   if cell is None:
      return QtGui.QIcon()
   img = QtGui.QImage(GLYPH_CELL, GLYPH_CELL, QtGui.QImage.Format.Format_ARGB32)
   img.fill(QtCore.Qt.GlobalColor.transparent)
   for y, row in enumerate(cell[:GLYPH_CELL]):
      for x, v in enumerate(row[:GLYPH_CELL]):
         r, g, b, a = GLYPH_COLORS.get(v, GLYPH_COLORS[1])
         img.setPixelColor(x, y, QtGui.QColor(r, g, b, a))
   size = GLYPH_CELL * GLYPH_ZOOM
   return QtGui.QIcon(QtGui.QPixmap.fromImage(img.scaled(size, size)))


def char_name(ch: str) -> str:
   """!How a character shows in lists: itself, its code points and its Unicode name.
   @param ch  the character (with any combining marks)
   @return e.g. "é  U+00E9 LATIN SMALL LETTER E WITH ACUTE"
   """
   points = " ".join(f"U+{ord(c):0{CODE_POINT_DIGITS}X}" for c in ch)
   return f"{ch}  {points} {unicodedata.name(ch[0], '')}".rstrip()


class CodePagePanel(EditorPanel):
   """!The game's code page: grid, code editor, unmapped characters, aliases."""

   ## See EditorPanel.panel_id.
   panel_id = "codepage"
   ## See EditorPanel.title.
   title = "Code page"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project Document
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The code page Document, or None (no project, or the game uses the engine's page).
      self.page_doc = None
      ## Project Document the page was opened for.
      self._page_for = None
      ## Code selected in the grid.
      self.code = 0
      ## True while the panel fills its own widgets.
      self._filling = False
      ## What the page is (file, language) or why there is none.
      self.header = QtWidgets.QLabel()
      self.header.setWordWrap(True)
      ## Gives the game its own copy of the engine's page.
      self.own_button = button("Give the game its own code page", lambda: self.own_page(),
                               "Copies the engine's default page into data/text/ and names it in the project")
      ## The 16 x 16 grid.
      self.grid = QtWidgets.QTableWidget(GRID_SIDE, GRID_SIDE)
      self.grid.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.grid.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.grid.setHorizontalHeaderLabels([f"{c:X}" for c in range(GRID_SIDE)])
      self.grid.setVerticalHeaderLabels([f"{r * GRID_SIDE:02X}" for r in range(GRID_SIDE)])
      self.grid.setIconSize(QtCore.QSize(GLYPH_CELL * GLYPH_ZOOM, GLYPH_CELL * GLYPH_ZOOM))
      for c in range(GRID_SIDE):
         self.grid.setColumnWidth(c, COLUMN_WIDTH)
      self.grid.currentCellChanged.connect(lambda r, c, *_: self._cell_chosen(r, c))
      ## Selected code and its character.
      self.code_label = QtWidgets.QLabel()
      ## The selected code's character.
      self.char_edit = QtWidgets.QLineEdit()
      self.char_edit.setMaxLength(MAX_CHAR_LENGTH)
      self.char_edit.returnPressed.connect(lambda: self.set_char())
      ## Code editor buttons.
      self.code_buttons = [button("Set", lambda: self.set_char(), "Give the code this character"),
                           button("Unset", lambda: self.unset_char(), "Leave the code without a character")]
      ## Characters the game's texts use that the page lacks.
      self.missing_list = QtWidgets.QListWidget()
      ## Unmapped-character buttons.
      self.missing_buttons = [
         button("Give it the selected code", lambda: self.map_missing(),
                "The selected grid code gets the character picked in this list"),
         button("Alias...", lambda: self.alias_missing(),
                "Fold the character onto text the page maps (e.g. a curly quote onto ')")]
      ## Aliases: folded text -> what it encodes as.
      self.aliases = QtWidgets.QTableWidget(0, ALIAS_COLUMNS)
      self.aliases.setHorizontalHeaderLabels(["Text", "Encodes as"])
      self.aliases.horizontalHeader().setStretchLastSection(True)
      self.aliases.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.aliases.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      ## Alias buttons.
      self.alias_buttons = [button("Add...", lambda: self.add_alias()),
                            button("Remove", lambda: self.remove_alias())]
      ## Font problems (characters without a glyph).
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)
      self.problems.setStyleSheet("color: #c03030;")

      left = QtWidgets.QVBoxLayout()
      top = QtWidgets.QHBoxLayout()
      top.addWidget(self.header, 1)
      top.addWidget(self.own_button)
      left.addLayout(top)
      left.addWidget(self.grid, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.code_label)
      row.addWidget(self.char_edit)
      for b in self.code_buttons:
         row.addWidget(b)
      row.addStretch(1)
      left.addLayout(row)
      left.addWidget(self.problems)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(QtWidgets.QLabel("Characters the game's texts use that the page lacks"))
      right.addWidget(self.missing_list)
      row = QtWidgets.QHBoxLayout()
      for b in self.missing_buttons:
         row.addWidget(b)
      right.addLayout(row)
      right.addWidget(QtWidgets.QLabel("Aliases"))
      right.addWidget(self.aliases, 1)
      row = QtWidgets.QHBoxLayout()
      for b in self.alias_buttons:
         row.addWidget(b)
      row.addStretch(1)
      right.addLayout(row)
      lay = QtWidgets.QHBoxLayout(self)
      lay.addLayout(left, GRID_STRETCH)
      lay.addLayout(right, LISTS_STRETCH)
      split_box(right, [MISSING_LIST_HEIGHT, None])   # [RZ] missing characters over aliases: drag the boundary
      split_box(lay)   # [RZ] code page | lists: the user drags the boundary

   # -- documents -------------------------------------------------------------------------

   def project_doc(self) -> Document | None:
      """!The host's project Document.
      @return Document, or None
      """
      host = self.host   # a local name: Doxygen 1.12 misreads getattr(self.x, ...)
      return getattr(host, "document", None)

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the code page.
      @return Document, or None
      """
      return self.page_doc

   def own_documents(self) -> list[Document]:
      """!Documents this panel edits besides the host's (saved with it).
      @return [the page Document] or []
      """
      return [self.page_doc] if self.page_doc is not None else []

   def document_replaced(self) -> None:
      """!Another project: its page is opened.
      @return None
      """
      self.page_doc, self._page_for = None, None
      self.refresh()

   def _open_page(self) -> str | None:
      """!Opens the project's page file when it is not open yet.
      @return why there is no page Document, or None
      """
      project = self.project_doc()
      if project is None:
         self.page_doc, self._page_for = None, None
         return "No project open."
      if self._page_for is project and self.page_doc is not None:
         return None
      try:
         self.page_doc = codepage.open_page(project)
      except (DocumentError, engine.EngineNotFound) as e:
         self.page_doc = None
         return str(e)
      self._page_for = project
      return None

   def page(self) -> Any:
      """!The page as being edited (unsaved edits included), or the engine's default.
      @return text_encoder.CodePage
      """
      if self.page_doc is None:
         return codepage.default_page()
      return codepage.check(self.page_doc.data)

   # -- showing ---------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the page, the font and the project's texts.
      @return None
      """
      why = self._open_page()
      project = self.project_doc()
      on = self.page_doc is not None
      self.own_button.setVisible(project is not None and not on)
      try:
         page = self.page()
      except DocumentError as e:   # an invalid page file: shown as the engine's until it is fixed
         page, why = codepage.default_page(), str(e)
      if on:
         self.header.setText(f"Language {page.id!r}: {self.page_doc.path.name}" + (" *" if self.page_doc.dirty
                                                                                  else ""))
      else:
         self.header.setText(f"{why}\nShown: the engine's default page (printable ASCII).")
      self._fill_grid(project, page)
      self._fill_missing(project, page)
      self._fill_aliases(page)
      problems = codepage.font_problems(project, page) if project is not None else []
      self.problems.setText("\n".join(problems))
      for w in self.code_buttons + self.missing_buttons + self.alias_buttons + [self.char_edit]:
         w.setEnabled(on)
      self._fill_code(page)

   def _fill_grid(self, project: Document | None, page: Any) -> None:
      """!Fills the grid: each code's character and glyph.
      @param project  project Document, or None
      @param page     text_encoder.CodePage
      @return None
      """
      te = codepage.encoder()
      try:
         glyphs = codepage.glyphs(project, page)
      except (DocumentError, OSError, SystemExit):   # unreadable fonts: font_problems() says so
         glyphs = {}
      self._filling = True
      try:
         for code in range(GRID_SIDE * GRID_SIDE):
            item = QtWidgets.QTableWidgetItem()
            ch = page.chars.get(code)
            if code > te.MAX_GLYPH_CODE:   # control codes: not characters
               item.setText("ctl")
               item.setBackground(QtGui.QColor(CONTROL_COLOR))
               item.setToolTip(f"{codepage.code_key(code)}: a text control code")
            elif ch is None:
               item.setBackground(QtGui.QColor(FREE_COLOR))
               item.setToolTip(f"{codepage.code_key(code)}: no character")
            else:
               item.setText(ch)
               item.setIcon(glyph_icon(glyphs.get(code)))
               item.setToolTip(f"{codepage.code_key(code)}: {char_name(ch)}"
                               + ("" if code in glyphs else " (the font has no glyph for it)"))
            self.grid.setItem(code // GRID_SIDE, code % GRID_SIDE, item)
         self.grid.setCurrentCell(self.code // GRID_SIDE, self.code % GRID_SIDE)
      finally:
         self._filling = False

   def _fill_missing(self, project: Document | None, page: Any) -> None:
      """!Lists the characters the project's texts use that the page lacks.
      @param project  project Document, or None
      @param page     text_encoder.CodePage
      @return None
      """
      keep = self.selected_missing()
      self.missing_list.clear()
      try:
         missing = codepage.missing(project, page) if project is not None else {}
      except (DocumentError, engine.EngineNotFound) as e:
         self.missing_list.addItem(f"({e})")
         return
      for ch, uses in missing.items():
         more = f" and {len(uses) - USES_SHOWN} more" if len(uses) > USES_SHOWN else ""
         item = QtWidgets.QListWidgetItem(f"{char_name(ch)}  ({'; '.join(uses[:USES_SHOWN])}{more})")
         item.setData(QtCore.Qt.ItemDataRole.UserRole, ch)
         item.setToolTip("\n".join(uses))
         self.missing_list.addItem(item)
         if ch == keep:
            self.missing_list.setCurrentItem(item)
      if not missing:
         self.missing_list.addItem("(none: the page has every character the texts use)")

   def _fill_aliases(self, page: Any) -> None:
      """!Fills the alias table.
      @param page  text_encoder.CodePage
      @return None
      """
      aliases = self.page_doc.data.get("aliases") if self.page_doc is not None else None
      rows = list(aliases.items()) if isinstance(aliases, dict) else []
      self.aliases.setRowCount(len(rows))
      for r, (text, target) in enumerate(rows):
         self.aliases.setItem(r, 0, QtWidgets.QTableWidgetItem(text))
         self.aliases.setItem(r, 1, QtWidgets.QTableWidgetItem(str(target)))

   def _cell_chosen(self, row: int, col: int) -> None:
      """!Another grid cell was picked.
      @param row  grid row
      @param col  grid column
      @return None
      """
      if self._filling or row < 0 or col < 0:
         return
      self.code = row * GRID_SIDE + col
      try:
         self._fill_code(self.page())
      except DocumentError:
         self._fill_code(codepage.default_page())

   def _fill_code(self, page: Any) -> None:
      """!Shows the selected code and its character.
      @param page  text_encoder.CodePage
      @return None
      """
      te = codepage.encoder()
      ch = page.chars.get(self.code)
      control = self.code > te.MAX_GLYPH_CODE
      self.code_label.setText(f"Code {codepage.code_key(self.code)}" + (" (control)" if control else ""))
      self.char_edit.setText(ch or "")
      editable = self.page_doc is not None and not control
      self.char_edit.setEnabled(editable)
      for b in self.code_buttons:
         b.setEnabled(editable)

   def selected_missing(self) -> str | None:
      """!The unmapped character picked in the list.
      @return the character, or None
      """
      item = self.missing_list.currentItem()
      return item.data(QtCore.Qt.ItemDataRole.UserRole) if item is not None else None

   # -- edits -----------------------------------------------------------------------------

   def _edit(self, label: str, fn: Any) -> bool:
      """!Runs an edit of the page Document through the host.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      doc = self.page_doc
      return doc is not None and self.host.run_edit(label, fn, doc)

   def set_char(self) -> None:
      """!Gives the selected code the typed character.
      @return None
      """
      ch, code, doc = self.char_edit.text(), self.code, self.page_doc
      if not ch:
         self.unset_char()
         return
      same = self.page().chars.get(code) == unicodedata.normalize(codepage.encoder().NORMAL_FORM, ch)
      if doc is not None and not same:
         self._edit(f"Set {codepage.code_key(code)}", lambda: codepage.set_code(doc, code, ch))

   def unset_char(self) -> None:
      """!Leaves the selected code without a character.
      @return None
      """
      code, doc = self.code, self.page_doc
      if doc is not None and code in self.page().chars:
         self._edit(f"Unset {codepage.code_key(code)}", lambda: codepage.unset_code(doc, code))

   def map_missing(self) -> None:
      """!Gives the selected code the unmapped character picked in the list.
      @return None
      """
      ch, code, doc = self.selected_missing(), self.code, self.page_doc
      if ch is None or doc is None:
         return
      self._edit(f"Set {codepage.code_key(code)}", lambda: codepage.set_code(doc, code, ch))

   def alias_missing(self) -> None:
      """!Folds the unmapped character picked in the list onto mapped text.
      @return None
      """
      ch, doc = self.selected_missing(), self.page_doc
      if ch is None or doc is None:
         return
      target, ok = QtWidgets.QInputDialog.getText(self, "Alias", f"{ch!r} encodes as (mapped characters):")
      if ok and target:
         self._edit("Alias", lambda: codepage.set_alias(doc, ch, target))

   def add_alias(self) -> None:
      """!Adds an alias (asks for the text and its target).
      @return None
      """
      doc = self.page_doc
      if doc is None:
         return
      text, ok = QtWidgets.QInputDialog.getText(self, "Alias", "Text to fold (e.g. a curly quote):")
      if not ok or not text:
         return
      target, ok = QtWidgets.QInputDialog.getText(self, "Alias", f"{text!r} encodes as (mapped characters):")
      if ok and target:
         self._edit("Alias", lambda: codepage.set_alias(doc, text, target))

   def remove_alias(self) -> None:
      """!Removes the selected aliases.
      @return None
      """
      doc = self.page_doc
      rows = sorted({i.row() for i in self.aliases.selectedItems()})
      texts = [self.aliases.item(r, 0).text() for r in rows]
      if doc is None or not texts:
         return

      def fn() -> None:
         """!Removes each alias."""
         for t in texts:
            codepage.set_alias(doc, t, None)
      self._edit("Remove alias", fn)

   def own_page(self) -> None:
      """!Gives the game its own copy of the engine's default page (edits the project manifest).
      @return None
      """
      project = self.project_doc()
      if project is None:
         return
      if self.host.run_edit("Own code page", lambda: codepage.import_page(project), project):
         self.page_doc, self._page_for = None, None
         self.refresh()

   def commit(self) -> None:
      """!Nothing is typed into the document directly (ProjectWindow contract).
      @return None
      """
      pass
