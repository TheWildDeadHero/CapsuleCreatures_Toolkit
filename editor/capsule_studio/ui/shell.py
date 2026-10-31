"""!The scene editor window: a PanelHost showing editor panels in tabs.

The window owns the Document, the File and Edit menus, validation and the
status bar; the panels own everything else. The monolithic Studio
application will be another host of the same panels.

[S2] Undo / Redo act on the active panel's current_document() (a text
table or font the text panels edit, else the manifest); Save also saves the
panels' extra_documents() that changed, and the unsaved-changes question
counts them.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import engine
from ..core.document import SCHEMA, Document, DocumentError
from . import json_view
from .editors import PANELS
from .widgets import STATUS_MS, file_toolbar, report_failure

if TYPE_CHECKING:
   from .panel import EditorPanel

## File dialog filter for manifests.
MANIFEST_FILTER = "Asset manifests (*.json);;All files (*)"
## Pause after the last edit before the document is validated again, milliseconds.
VALIDATE_DELAY_MS = 250
## Width of the window when it opens, pixels.
WINDOW_WIDTH = 1280
## Height of the window when it opens, pixels.
WINDOW_HEIGHT = 760


class EditorWindow(QtWidgets.QMainWindow):
   """!Main window hosting panels (implements PanelHost, see panel.py).

   @var document
   The Document being edited.
   @var reports
   (problems, {key: AssetReport}) from the last validation, or None.
   @var panels
   The hosted EditorPanel instances.
   """

   def __init__(self, panel_classes: Sequence[type[EditorPanel]] | None = None, path: str | Path | None = None) -> None:
      """!Creates the window.
      @param panel_classes  panels to host (default: all, in PANELS order)
      @param path           manifest to open, or None for a new one
      """
      super().__init__()
      self.document = Document()
      self.reports = None
      self.panels = []
      ## Runs validation once edits pause.
      self._validate_timer = QtCore.QTimer(self)
      self._validate_timer.setSingleShot(True)
      self._validate_timer.setInterval(VALIDATE_DELAY_MS)
      self._validate_timer.timeout.connect(lambda *a: self.validate(*a))
      ## Last revision a refresh was sent for.
      self._seen_revision = -1
      ## Callback given to Document.subscribe().
      self._on_change = lambda: self._changed()

      tabs = QtWidgets.QTabWidget()
      for cls in panel_classes or PANELS:
         self.panels.append(cls(self))
      if len(self.panels) > 1:
         for panel in self.panels:
            tabs.addTab(panel, panel.title)
      ## The tab widget (empty when the window hosts one panel: that panel is the central widget, S5).
      self.tabs = tabs
      self.setCentralWidget(tabs if len(self.panels) > 1 else self.panels[0])
      ## Status line: engine in use and validation summary.
      self.summary = QtWidgets.QLabel()
      self.statusBar().addPermanentWidget(self.summary)
      self._build_menus()
      # S5: connected once the actions exist (_tab_changed() updates them); a single panel never sits in the tab
      # widget, which used to report the panel's move out of it as a tab change before the menus were built
      tabs.currentChanged.connect(lambda *a: self._tab_changed(*a))
      self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
      self._attach(Document())
      if path:
         self.open_file(path)

   # -- PanelHost ---------------------------------------------------------------

   def show_status(self, text: str) -> None:
      """!Shows a message in the status bar.
      @param text  message
      @return None
      """
      self.statusBar().showMessage(text, STATUS_MS)

   def run_edit(self, label: str, fn: Callable[[], object], document: Document | None = None) -> bool:
      """!Runs fn() inside document.edit(label); errors become a message.
      @param label     undo label
      @param fn        callable
      @param document  Document to edit, default the window's
      @return True when the edit went through
      """
      try:
         with (document or self.document).edit(label):
            fn()
         return True
      except (DocumentError, ValueError, KeyError, IndexError, OSError, engine.EngineNotFound) as e:
         report_failure(self, label, str(e))   # [S2] a box on a screen; headless only the status bar
         return False

   def selection_changed(self) -> None:
      """!A panel's current document changed (PanelHost), or one of its own Documents was edited.
      @return None
      """
      self._update_title()

   def active_document(self) -> Document:
      """![S2] The Document Undo / Redo act on: the active panel's current_document(), else the manifest.
      @return Document
      """
      i = self.tabs.currentIndex() if len(self.panels) > 1 else 0
      panel = self.panels[i] if 0 <= i < len(self.panels) else None
      doc = panel.current_document() if panel is not None else None
      return doc if doc is not None else self.document

   def extra_documents(self) -> list[Document]:
      """![S2] The panels' own Documents (text tables, fonts), each once.
      @return Documents
      """
      out: list[Document] = []
      for p in self.panels:
         for d in p.extra_documents():
            if d is not self.document and all(d is not o for o in out):
               out.append(d)
      return out

   def unsaved(self) -> bool:
      """![S2] Whether the manifest or a panel's own Document has unsaved changes.
      @return True when something is unsaved
      """
      return self.document.dirty or any(d.dirty for d in self.extra_documents())

   # -- document --------------------------------------------------------------------

   def _attach(self, doc: Document) -> None:
      """!Switches to a document.
      @param doc  Document
      @return None
      """
      self.document.unsubscribe(self._on_change)
      self.document = doc
      self._seen_revision = doc.revision   # a new document restarts its revision count
      self.reports = None
      doc.subscribe(self._on_change)
      for p in self.panels:
         p.document_replaced()
      self._update_title()
      self.validate()

   def _changed(self) -> None:
      """!The document changed: refresh panels, revalidate soon.
      @return None
      """
      if self.document.revision == self._seen_revision:
         return
      self._seen_revision = self.document.revision
      for p in self.panels:
         p.refresh()
      self._update_title()
      self._validate_timer.start()

   def validate(self) -> None:
      """!Compiles the document with the engine's compiler and tells the panels.
      @return None
      """
      try:
         self.reports = self.document.validate()
      except engine.EngineNotFound as e:
         self.reports = None
         self.summary.setText("engine not found")
         self.show_status(str(e))
         return
      problems, reports = self.reports
      bad = len(problems) + sum(1 for r in reports.values() if not r.ok)   # manifest problems and failing assets
      self.summary.setText(f"{len(reports)} assets · " + (f"{bad} with problems" if bad else "all compile"))
      for p in self.panels:
         p.reports_changed()

   def _update_title(self) -> None:
      """!Window title: file name and unsaved mark.
      @return None
      """
      name = self.document.path.name if self.document.path else "untitled"
      dirty = self.unsaved()
      self.setWindowTitle(f"{name}{' *' if dirty else ''} - CapsuleCreatures Scene Editor")
      self.save_action.setEnabled(dirty or self.document.path is None)
      active = self.active_document()
      self.undo_action.setEnabled(active.undo_label() is not None)
      self.redo_action.setEnabled(active.redo_label() is not None)
      self.undo_action.setText(f"Undo {active.undo_label() or ''}".strip())
      self.redo_action.setText(f"Redo {active.redo_label() or ''}".strip())

   # -- menus -------------------------------------------------------------------------

   def _action(self, menu: QtWidgets.QMenu, text: str, slot: Callable[[], object],
               shortcut: QtGui.QKeySequence.StandardKey | None = None) -> QtGui.QAction:
      """!Adds a menu action.
      @param menu      QMenu
      @param text      label
      @param slot      callable
      @param shortcut  QKeySequence.StandardKey, or None
      @return QAction
      """
      a = QtGui.QAction(text, self)
      if shortcut is not None:
         a.setShortcuts(shortcut)   # every platform binding (e.g. Ctrl+Y and Ctrl+Shift+Z)
      a.triggered.connect(lambda _checked=False: slot())
      menu.addAction(a)
      return a

   def _build_menus(self) -> None:
      """!File and Edit menus.
      @return None
      """
      keys = QtGui.QKeySequence.StandardKey
      m = self.menuBar().addMenu("&File")
      self._action(m, "&New", lambda: self.new_file(), keys.New)
      ## Opens a manifest.
      self.open_action = self._action(m, "&Open...", lambda: self.open_file(), keys.Open)
      ## Saves the manifest.
      self.save_action = self._action(m, "&Save", lambda: self.save_file(), keys.Save)
      self._action(m, "Save &As...", lambda: self.save_as(), keys.SaveAs)
      m.addSeparator()
      self._action(m, "&Quit", lambda: self.close(), keys.Quit)
      m = self.menuBar().addMenu("&Edit")
      ## Undo action (label shows what it undoes).
      self.undo_action = self._action(m, "Undo", lambda: self.undo(), keys.Undo)
      ## Redo action.
      self.redo_action = self._action(m, "Redo", lambda: self.redo(), keys.Redo)
      ## Save / Undo / Redo buttons (the same actions as the menus; the scene editor edits one file).
      self.file_bar = file_toolbar(self, [
         ("open", self.open_action, "Open an asset manifest", "Open"),
         None,
         ("save", self.save_action, "Save the manifest (its new images go next to it)"),
         None,
         ("undo", self.undo_action, "Undo the last change"),
         ("redo", self.redo_action, "Redo the change you undid")])

   def _flush_panels(self) -> None:
      """!Lets panels write pending typing before a document-wide action.
      @return None
      """
      for p in self.panels:
         p.stop()

   def undo(self) -> None:
      """!Undoes the last edit.
      @return None
      """
      self._flush_panels()
      doc = self.active_document()
      doc.undo()
      if doc is not self.document:
         self._refresh_panels()

   def redo(self) -> None:
      """!Redoes the last undone edit.
      @return None
      """
      self._flush_panels()
      doc = self.active_document()
      doc.redo()
      if doc is not self.document:
         self._refresh_panels()

   def _refresh_panels(self) -> None:
      """![S2] Refreshes every panel after an undo / redo of a panel's own Document.
      @return None
      """
      for p in self.panels:
         p.refresh()
      self._update_title()

   def _confirm_discard(self) -> bool:
      """!Asks about unsaved changes.
      @return True to go ahead (saved or discarded), False to cancel
      """
      self._flush_panels()
      if not self.unsaved():
         return True
      b = QtWidgets.QMessageBox.StandardButton
      answer = QtWidgets.QMessageBox.question(self, "Unsaved changes", "Save changes first?",
                                              b.Save | b.Discard | b.Cancel, b.Save)
      if answer == b.Save:
         return self.save_file()
      return answer == b.Discard

   def new_file(self) -> None:
      """!Starts an empty manifest.
      @return None
      """
      if self._confirm_discard():
         self._attach(Document())

   def open_file(self, path: str | Path | None = None) -> None:
      """!Opens a manifest.
      @param path  file, or None to ask
      @return None
      """
      if not self._confirm_discard():
         return
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open manifest", "", MANIFEST_FILTER)
         if not path:
            return
      try:
         self._attach(Document.open(path))
      except (OSError, ValueError, DocumentError, engine.EngineNotFound) as e:
         if json_view.other_schema(path, SCHEMA):
            # [S5] another kind of JSON (e.g. an imported game's importer data): shown read-only, not refused
            json_view.show_read_only(path)
            self.show_status(f"{Path(path).name} is no asset manifest: shown read-only in the data view")
            return
         QtWidgets.QMessageBox.warning(self, "Open", f"{path}: {e}")

   def save_file(self) -> bool:
      """!Saves to the current file (asks for one if new).
      @return True when saved
      """
      if self.document.path is None:
         return self.save_as()
      self._flush_panels()
      try:
         if self.document.dirty or self.document.path is not None and not self.document.path.exists():
            self.document.save()
         for d in self.extra_documents():
            if d.dirty:
               d.save()   # [S2] a table or font keeps its file's layout
      except (OSError, DocumentError) as e:
         QtWidgets.QMessageBox.warning(self, "Save", str(e))
         return False
      self.show_status(f"Saved {self.document.path}")
      self._update_title()
      return True

   def save_as(self) -> bool:
      """!Saves under a new name. Image frames go next to the manifest.
      @return True when saved
      """
      path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save manifest", "assets.json", MANIFEST_FILTER)
      if not path:
         return False
      self._flush_panels()
      old = self.document.base_dir
      if old is not None and Path(path).resolve().parent != old:
         # Images saved earlier are relative to the old folder; carry them over as unsaved.
         for rel in self.document.image_paths():
            img = self.document.image(rel)
            if img is not None and rel not in self.document.pending:
               self.document.add_image(rel, img)
      try:
         self.document.save(path)
      except (OSError, DocumentError) as e:
         QtWidgets.QMessageBox.warning(self, "Save", str(e))
         return False
      self.show_status(f"Saved {self.document.path}")
      self._update_title()
      return True

   def _tab_changed(self, index: int) -> None:
      """!Stops panels that are no longer visible (playback, pending text).
      @param index  new tab
      @return None
      """
      for i, p in enumerate(self.panels):
         if i != index:
            p.stop()
      self._update_title()   # [S2] Undo / Redo follow the active panel's Document

   def closeEvent(self, event: QtGui.QCloseEvent) -> None:
      """!Asks about unsaved changes before closing.
      @param event  QCloseEvent
      @return None
      """
      if self._confirm_discard():
         event.accept()
      else:
         event.ignore()
