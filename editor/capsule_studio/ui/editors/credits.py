"""!Credits panel: pages of a heading and names, previewed as the credits
sequence shows them, importable from and exportable to plain text."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtWidgets

from ...core import engine, preview, texts
from ..panel import EditorPanel
from ..qtimage import screen_qimage
from ..widgets import DEBOUNCE_MS, Debounce, PixelView, button, set_enabled

if TYPE_CHECKING:
   from ..panel import PanelHost

## Screen pixels per preview pixel.
PREVIEW_ZOOM = 2
## Layout stretch of the page list column.
LIST_STRETCH = 3
## Layout stretch of the page fields column.
FIELDS_STRETCH = 4
## Layout stretch of the preview.
PREVIEW_STRETCH = 4


class CreditsPanel(EditorPanel):
   """!Edits the credits text pairs (text:PREFIX HEAD nn / NAMES nn).

   @var pages
   Working copy of the pages: list of [heading, names].
   """

   ## See EditorPanel.panel_id.
   panel_id = "credits"
   ## See EditorPanel.title.
   title = "Credits"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      self.pages = []
      ## Prefix the working pages were loaded under (commits use it, not the field being typed in).
      self._loaded_prefix = texts.CREDITS_PREFIX
      ## True while the panel fills its own widgets.
      self._filling = False
      ## Key prefix.
      self.prefix = QtWidgets.QLineEdit(texts.CREDITS_PREFIX)
      self.prefix.editingFinished.connect(lambda *a: self.refresh(*a))
      ## Pages.
      self.list = QtWidgets.QListWidget()
      self.list.currentRowChanged.connect(lambda *a: self._chosen(*a))
      left = QtWidgets.QVBoxLayout()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Key prefix"))
      row.addWidget(self.prefix, 1)
      left.addLayout(row)
      left.addWidget(self.list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add page", lambda: self.add_page()))
      row.addWidget(button("Remove", lambda: self.remove_page()))
      row.addWidget(button("Up", lambda: self.move_page(-1)))
      row.addWidget(button("Down", lambda: self.move_page(1)))
      left.addLayout(row)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Import .txt...", lambda: self.import_text(),
                           "Pages separated by blank lines; first line of each is the heading"))
      row.addWidget(button("Export .txt...", lambda: self.export_text()))
      left.addLayout(row)
      ## Heading of the current page.
      self.heading = QtWidgets.QLineEdit()
      self.heading.textEdited.connect(lambda *a: self._typed(*a))
      ## Names of the current page.
      self.names = QtWidgets.QPlainTextEdit()
      self.names.textChanged.connect(lambda *a: self._typed(*a))
      ## Problems found.
      self.checks = QtWidgets.QLabel()
      self.checks.setWordWrap(True)
      form = QtWidgets.QFormLayout()
      form.addRow("Heading", self.heading)
      form.addRow("Names", self.names)
      middle = QtWidgets.QVBoxLayout()
      middle.addLayout(form, 1)
      middle.addWidget(self.checks)
      note = QtWidgets.QLabel("Page n is the text pair numbered n; the credits sequence decides how many "
                              "pages it shows.")
      note.setWordWrap(True)
      middle.addWidget(note)
      ## Preview of the page.
      self.view = PixelView(PREVIEW_ZOOM)
      layout = QtWidgets.QHBoxLayout(self)
      for part, stretch in ((left, LIST_STRETCH), (middle, FIELDS_STRETCH)):
         box = QtWidgets.QWidget()
         box.setLayout(part)
         layout.addWidget(box, stretch)
      layout.addWidget(self.view, PREVIEW_STRETCH)
      ## Writes typing as one undo step after a pause.
      self.commit = Debounce(self._commit, DEBOUNCE_MS, self)

   def prefix_text(self) -> str:
      """!The key prefix in use.
      @return prefix, CREDITS when the field is empty
      """
      return self.prefix.text().strip().upper() or texts.CREDITS_PREFIX

   def current(self) -> int:
      """!The current page.
      @return its index, or -1 without one
      """
      return self.list.currentRow()

   def refresh(self) -> None:
      """!Re-reads the pages from the document, keeping the current page.
      @return None
      """
      self.commit.flush()
      row = max(0, self.current())
      self._loaded_prefix = self.prefix_text()
      self.pages = [list(p) for p in texts.credits_pages(self.doc, self._loaded_prefix)]
      self._fill_list(min(row, len(self.pages) - 1))

   def _fill_list(self, row: int) -> None:
      """!Rebuilds the page list.
      @param row  page to select, -1 for none
      @return None
      """
      self._filling = True
      try:
         self.list.clear()
         for n, (h, _) in enumerate(self.pages, 1):
            self.list.addItem(f"{n:02d}  {h or '(no heading)'}")
         if 0 <= row < len(self.pages):
            self.list.setCurrentRow(row)
         self._fill_page()
      finally:
         self._filling = False

   def _fill_page(self) -> None:
      """!Shows the current page in the fields and the preview.
      @return None
      """
      i = self.current()
      has = 0 <= i < len(self.pages)
      self.heading.setEnabled(has)
      set_enabled(self.names, has)   # read-only, still scrolls
      h, n = self.pages[i] if has else ("", "")
      was = self._filling
      self._filling = True
      if self.heading.text() != h:
         self.heading.setText(h)
      if self.names.toPlainText() != n:
         self.names.setPlainText(n)
      self._filling = was
      self._update_preview()

   def _chosen(self, _row: int) -> None:
      """!Another page was picked.
      @return None
      """
      if not self._filling:   # typing is already in self.pages; the debounce commits it
         self._filling = True
         self._fill_page()
         self._filling = False

   def _typed(self, *_: object) -> None:
      """!The heading or names changed.
      @return None
      """
      if self._filling:
         return
      i = self.current()
      if 0 <= i < len(self.pages):
         self.pages[i] = [self.heading.text(), self.names.toPlainText()]
         item = self.list.item(i)
         if item is not None:
            item.setText(f"{i + 1:02d}  {self.pages[i][0] or '(no heading)'}")
      self._update_preview()
      self.commit.poke()

   def _update_preview(self) -> None:
      """!Redraws the preview and checks the current page.
      @return None
      """
      i = self.current()
      if not 0 <= i < len(self.pages):
         self.view.set_image(None)
         self.checks.setText("No pages. Add one or import a text file.")
         return
      h, n = self.pages[i]
      msgs = [f"heading: {m}" for m in texts.check_text(h, rows=1)]
      msgs += [f"names: {m}" for m in texts.check_text(n, rows=texts.CREDITS_NAMES_ROWS)]
      self.checks.setText("\n".join(msgs) if msgs else "Fits.")
      self.checks.setStyleSheet("color: #c03030;" if any("error:" in m for m in msgs) else "")
      try:
         self.view.set_image(screen_qimage(preview.credits_page(h, n)))
      except engine.EngineNotFound:   # the preview needs the engine's font
         self.view.set_image(None)
         self.checks.setText(self.checks.text() + "\nNo preview: engine not found.")

   def _commit(self, label: str = "Edit credits") -> None:
      """!Writes the working pages to the document.
      @param label  undo label
      @return None
      """
      doc = self.doc
      pages = [tuple(p) for p in self.pages]
      prefix = self._loaded_prefix
      if pages != texts.credits_pages(self.doc, prefix):
         self.host.run_edit(label, lambda: texts.set_credits_pages(doc, pages, prefix))

   def _structural(self, label: str, row: int) -> None:
      """!Commits a page list change at once and selects a page.
      @param label  undo label
      @param row    page to select
      @return None
      """
      self.commit.flush()
      self._commit(label)
      self.pages = [list(p) for p in texts.credits_pages(self.doc, self._loaded_prefix)]
      self._fill_list(row)

   def add_page(self) -> None:
      """!Adds a page after the current one.
      @return None
      """
      self.commit.flush()
      at = self.current() + 1 if self.current() >= 0 else len(self.pages)
      self.pages.insert(at, ["HEADING", "Name"])
      self._structural("Add credits page", at)

   def remove_page(self) -> None:
      """!Removes the current page.
      @return None
      """
      self.commit.flush()
      i = self.current()
      if 0 <= i < len(self.pages):
         del self.pages[i]
         self._structural("Remove credits page", min(i, len(self.pages) - 1))

   def move_page(self, delta: int) -> None:
      """!Moves the current page.
      @param delta  -1 up, 1 down
      @return None
      """
      self.commit.flush()
      i = self.current()
      j = i + delta
      if 0 <= i < len(self.pages) and 0 <= j < len(self.pages):
         self.pages[i], self.pages[j] = self.pages[j], self.pages[i]
         self._structural("Move credits page", j)

   def import_text(self) -> None:
      """!Replaces the pages from a text file.
      @return None
      """
      self.commit.flush()
      path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import credits", "", "Text (*.txt);;All files (*)")
      if not path:
         return
      try:
         with open(path, encoding="utf-8") as f:
            pages = texts.parse_credits_text(f.read())
      except (OSError, UnicodeDecodeError) as e:
         QtWidgets.QMessageBox.warning(self, "Import credits", str(e))
         return
      self.pages = [list(p) for p in pages]
      self._structural("Import credits", 0)
      self.host.show_status(f"{len(pages)} pages imported")

   def export_text(self) -> None:
      """!Writes the pages to a text file.
      @return None
      """
      self.commit.flush()
      path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export credits", "credits.txt", "Text (*.txt)")
      if path:
         try:
            with open(path, "w", encoding="utf-8") as f:
               f.write(texts.format_credits_text([tuple(p) for p in self.pages]))
         except OSError as e:
            QtWidgets.QMessageBox.warning(self, "Export credits", str(e))
            return
         self.host.show_status(f"Wrote {path}")

   def stop(self) -> None:
      """!Writes pending typing.
      @return None
      """
      self.commit.flush()
