"""!Text panel: text assets, checked against the game's code page and the
screen width, with a preview in the game's font.

Any Unicode text can be typed; characters the game's code page (the page of
the game the asset manifest belongs to, else the engine's ASCII page) neither
maps nor aliases are underlined, and the checks name them.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import codepage, engine, preview, texts
from ...core.document import DocumentError
from ..panel import EditorPanel
from ..qtimage import screen_qimage
from ..panes import split_box
from ..widgets import DEBOUNCE_MS, Debounce, PixelView, button, set_enabled

if TYPE_CHECKING:
   from ..panel import PanelHost

## Columns of text that fit inside the cutscene text box.
TEXT_BOX_COLUMNS = 27
## Anchor column of the centred layer layout (the middle of the screen).
CENTRED_COLUMN = 15
## First row of the centred layer layout.
CENTRED_ROW = 8
## Preview layouts: label -> (columns that fit, function(text, code page, glyphs) drawing the text).
LAYOUTS = {
   "Text box (cutscene)": (TEXT_BOX_COLUMNS, lambda t, page, g: preview.text_box(t, page=page, glyphs=g)),
   "Layer, left": (texts.SCREEN_COLUMNS - 1, lambda t, page, g: preview.text_layer(t, 1, 1, page=page, glyphs=g)),
   "Layer, centred": (texts.SCREEN_COLUMNS, lambda t, page, g: preview.text_layer(t, CENTRED_COLUMN, CENTRED_ROW,
                                                                                "center", page=page, glyphs=g)),
}
## Underline colour of characters the code page lacks.
UNMAPPED_COLOR = "#d02020"


def text_setup(path: Path | None) -> tuple[Any, Any]:
   """!The code page and font of the game a file belongs to.
   @param path  the asset manifest, or None
   @return (text_encoder.CodePage, glyphs by code); the engine's page and font outside a game or when the
           game's page cannot be read (the build reports that)
   """
   found = codepage.find_project(path) if path is not None else None
   try:
      project = codepage.open_project(found) if found is not None else None
      page = codepage.load(project)
      return page, codepage.glyphs(project, page)
   except (DocumentError, OSError, SystemExit):
      page = codepage.default_page()
      return page, codepage.glyphs(None, page)


def page_stamp(path: Path | None) -> tuple[object, ...]:
   """!What text_setup() depends on, to know when to read it again: the
   file, and the game's code page file with its modification time.
   @param path  the asset manifest, or None
   @return a comparable tuple
   """
   found = codepage.find_project(path) if path is not None else None
   if found is None:
      return (path,)
   try:
      page = codepage.page_path(codepage.open_project(found))
      return (path, found.stat().st_mtime_ns, page, page.stat().st_mtime_ns if page is not None else None)
   except (DocumentError, OSError):
      return (path, found)


class UnmappedHighlighter(QtGui.QSyntaxHighlighter):
   """!Underlines the characters of a text the code page cannot encode."""

   def __init__(self, document: QtGui.QTextDocument) -> None:
      """!Creates the highlighter (the engine's page until set_page()).
      @param document  QTextDocument to highlight
      """
      super().__init__(document)
      ## The code page, or None (nothing is underlined).
      self.page = None
      ## Format of an unmapped character.
      self.mark = QtGui.QTextCharFormat()
      self.mark.setUnderlineStyle(QtGui.QTextCharFormat.UnderlineStyle.WaveUnderline)
      self.mark.setUnderlineColor(QtGui.QColor(UNMAPPED_COLOR))
      self.mark.setToolTip("not in the game's code page")

   def set_page(self, page: Any) -> None:
      """!Checks against another code page.
      @param page  text_encoder.CodePage
      @return None
      """
      if page is not self.page:
         self.page = page
         self.rehighlight()

   def highlightBlock(self, text: str) -> None:
      """!Underlines one line's unmapped characters.
      @param text  the line
      @return None
      """
      if self.page is None or not text:
         return
      nf = codepage.encoder().NORMAL_FORM
      if unicodedata.normalize(nf, text) == text:
         # The pieces line up with the typed text: underline exactly the pieces the page lacks.
         at = 0
         for piece, codes in codepage.pieces(self.page, text):
            if codes is None:
               self.setFormat(at, len(piece), self.mark)
            at += len(piece)
         return
      # Not in normal form (typed combining marks): underline each character that does not encode.
      bad = set("".join(codepage.unmapped(self.page, text)))
      for i, ch in enumerate(text):
         if ch in bad:
            self.setFormat(i, 1, self.mark)
## Screen pixels per preview pixel.
PREVIEW_ZOOM = 2
## Layout stretch of the text list column.
LIST_STRETCH = 2
## Layout stretch of the editor column.
EDITOR_STRETCH = 4
## Layout stretch of the preview column.
PREVIEW_STRETCH = 4


class TextPanel(EditorPanel):
   """!Edits text assets other than credits pages (those have their own panel)."""

   ## See EditorPanel.panel_id.
   panel_id = "text"
   ## See EditorPanel.title.
   title = "Text"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Text being edited, or None.
      self.key = None
      ## True while the panel fills its own widgets.
      self._filling = False
      ## Text asset keys.
      self.list = QtWidgets.QListWidget()
      self.list.currentRowChanged.connect(lambda *a: self._chosen(*a))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Texts"))
      left.addWidget(self.list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("New...", lambda: self.new_text()))
      row.addWidget(button("Rename...", lambda: self.rename_text()))
      row.addWidget(button("Delete", lambda: self.delete_text()))
      left.addLayout(row)
      ## The text.
      self.edit = QtWidgets.QPlainTextEdit()
      self.edit.setFont(QtWidgets.QApplication.font())
      self.edit.textChanged.connect(lambda *a: self._typed(*a))
      ## Underlines what the game's code page lacks.
      self.highlighter = UnmappedHighlighter(self.edit.document())
      ## The game's code page and font: (page_stamp(), page, glyphs), see text_setup().
      self._setup = None
      ## Problems found.
      self.checks = QtWidgets.QLabel()
      self.checks.setWordWrap(True)
      ## Layout used for the preview and line-length check.
      self.layout_box = QtWidgets.QComboBox()
      self.layout_box.addItems(list(LAYOUTS))
      self.layout_box.currentIndexChanged.connect(lambda _i: self._update_preview())
      ## Preview.
      self.view = PixelView(PREVIEW_ZOOM)
      middle = QtWidgets.QVBoxLayout()
      middle.addWidget(self.edit, 1)
      middle.addWidget(self.checks)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(self.layout_box)
      right.addWidget(self.view, 1)
      layout = QtWidgets.QHBoxLayout(self)
      for part, stretch in ((left, LIST_STRETCH), (middle, EDITOR_STRETCH), (right, PREVIEW_STRETCH)):
         box = QtWidgets.QWidget()
         box.setLayout(part)
         layout.addWidget(box, stretch)
      split_box(layout)   # [RZ] texts | editor | preview: the user drags the boundaries
      ## Applies typing as one undo step after a pause.
      self.commit = Debounce(self._commit, DEBOUNCE_MS, self)

   def setup(self) -> tuple[Any, Any]:
      """!The code page and font texts are checked and previewed with (read again when the page file changes).
      @return (text_encoder.CodePage, glyphs)
      """
      doc = getattr(self.host, "document", None)
      path = doc.path if doc is not None else None
      stamp = page_stamp(path)
      if self._setup is None or self._setup[0] != stamp:
         self._setup = (stamp,) + text_setup(path)
      _stamp, page, glyphs = self._setup
      return page, glyphs

   def keys(self) -> list[str]:
      """!Text assets shown here (credits pages excluded).
      @return list of keys
      """
      return [a.get("key") for a in self.doc.assets("text") if not texts.is_credits_key(a.get("key"))]

   def refresh(self) -> None:
      """!Re-reads the document, keeping the chosen text and cursor.
      @return None
      """
      self._filling = True
      try:
         keys = self.keys()
         if self.key not in keys:
            self.key = keys[0] if keys else None
         self.list.clear()
         self.list.addItems(keys)
         if self.key:
            self.list.setCurrentRow(keys.index(self.key))
         a = self.doc.find(self.key) if self.key else None
         set_enabled(self.edit, a is not None)   # read-only, still scrolling
         value = a.get("text", "") if a else ""
         if self.edit.toPlainText() != value:
            self.edit.setPlainText(value)
      finally:
         self._filling = False
      self._update_preview()

   def _chosen(self, row: int) -> None:
      """!The list selection changed.
      @param row  list row
      @return None
      """
      if self._filling:
         return
      item = self.list.item(row)
      key = item.text() if item else None
      # Switch after this signal returns: committing pending typing rebuilds the list.
      QtCore.QTimer.singleShot(0, lambda: self._switch_to(key))

   def _switch_to(self, key: str | None) -> None:
      """!Writes pending typing, then shows another text.
      @param key  text key, or None
      @return None
      """
      self.commit.flush()
      self.key = key
      self.refresh()

   def _typed(self) -> None:
      """!Text changed in the editor.
      @return None
      """
      if self._filling:
         return
      self._update_preview()
      self.commit.poke()

   def _commit(self) -> None:
      """!Writes the edited text to the document.
      @return None
      """
      doc = self.doc
      if self.key is None:
         return
      value, key = self.edit.toPlainText(), self.key
      a = self.doc.find(key)
      if a is not None and a.get("text") != value:
         self.host.run_edit("Edit text", lambda: texts.set_text(doc, key, value))

   def _update_preview(self) -> None:
      """!Redraws the preview and the checks.
      @return None
      """
      value = self.edit.toPlainText()
      names = list(LAYOUTS)
      # The chosen layout (the index clamped: -1 while the combo is empty).
      columns, draw = LAYOUTS[names[min(max(0, self.layout_box.currentIndex()), len(names) - 1)]]
      try:
         page, glyphs = self.setup()
         self.highlighter.set_page(page)
         msgs = texts.check_text(value, columns, page=page)
         self.checks.setText("\n".join(msgs) if msgs else "Fits.")
         self.checks.setStyleSheet("color: #c03030;" if any(m.startswith("error:") for m in msgs) else "")
         self.view.set_image(screen_qimage(draw(value, page, glyphs)) if self.key else None)
      except engine.EngineNotFound:   # the checks and the preview need the engine's encoder and font
         self.view.set_image(None)
         self.checks.setText(self.checks.text() + "\nNo preview: engine not found.")

   def new_text(self) -> None:
      """!Adds a text asset.
      @return None
      """
      doc = self.doc
      self.commit.flush()
      key, ok = QtWidgets.QInputDialog.getText(self, "New text", "Key:", text="text:NEW TEXT")
      if ok and key.strip():
         done = self.host.run_edit("New text", lambda: doc.add_asset(
               {"key": key.strip(), "kind": "text", "text": ""}))
         if done:
            self.key = key.strip()
            self.refresh()

   def rename_text(self) -> None:
      """!Changes the text's key.
      @return None
      """
      doc = self.doc
      self.commit.flush()
      if self.key is None:
         return
      new, ok = QtWidgets.QInputDialog.getText(self, "Rename text", "Key:", text=self.key)
      if ok and new.strip() and new.strip() != self.key:
         old = self.key
         done = self.host.run_edit("Rename text", lambda: doc.rename_asset(old, new.strip()))
         if done:
            self.key = new.strip()
            self.refresh()

   def delete_text(self) -> None:
      """!Removes the text.
      @return None
      """
      doc = self.doc
      self.commit.flush()
      if self.key is not None:
         key = self.key
         done = self.host.run_edit("Delete text", lambda: doc.remove_asset(key))
         if done:
            self.key = None
            self.refresh()

   def stop(self) -> None:
      """!Writes pending typing.
      @return None
      """
      self.commit.flush()
