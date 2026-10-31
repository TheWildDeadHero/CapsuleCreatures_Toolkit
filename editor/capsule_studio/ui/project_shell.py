"""!The project settings window: a PanelHost for a game's project manifest
(reference/project.json, capsule.project/1).

It hosts the build settings panel (A-2, A-5) and the code page panel (C-2,
D-20 F), and owns the File and Edit menus and the status bar. Each document
keeps its own undo history: a panel editing a file of its own (the code page)
names it with current_document() and own_documents(); Undo / Redo act on the
tab in front's document, Save saves every document with changes. More project
panels (ROM header, sources, plugins) can join as tabs.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtGui, QtWidgets

from ..core import engine, project
from ..core.document import DocumentError
from . import profiler
from .editors.build_settings import BuildSettingsPanel
from .editors.codepage_panel import CodePagePanel
from .editors.gba_memory import GbaMemoryPanel
from .panes import fit_panel
from .widgets import STATUS_MS, StartPage, file_toolbar, remember_file

if TYPE_CHECKING:
   from ..core.document import Document
   from .panel import EditorPanel

## Project panels, in tab order ([S6] engine UM: the GBA memory settings and report after the build settings).
PROJECT_PANELS = [BuildSettingsPanel, GbaMemoryPanel, CodePagePanel]
## File dialog filter.
PROJECT_FILTER = "Project manifest (project.json *.json);;All files (*)"
## Width of the window when it opens, pixels.
WINDOW_WIDTH = 900
## Height of the window when it opens, pixels.
WINDOW_HEIGHT = 640


class ProjectWindow(QtWidgets.QMainWindow):
   """!Main window hosting project panels (implements PanelHost, see panel.py)."""

   def __init__(self, path: str | Path | None = None) -> None:
      """!Creates the window.
      @param path  reference/project.json to open, or None
      """
      super().__init__()
      ## The open project Document, or None.
      self.document = None
      ## Unused by project panels; present for the PanelHost contract.
      self.reports = None
      ## The hosted EditorPanel instances.
      self.panels = []
      self._build_menus()
      ## The tab widget.
      self.tabs = QtWidgets.QTabWidget()
      for cls in PROJECT_PANELS:
         panel = cls(self)
         fit_panel(panel)   # [RZ] scroll bars instead of a window larger than the screen
         self.panels.append(panel)
         self.tabs.addTab(panel, panel.title)
      self.tabs.currentChanged.connect(lambda _i: self._tab_changed())
      self.setCentralWidget(self.tabs)
      ## Start page, shown until a manifest is open.
      self.start = StartPage(
         "CapsuleCreatures Project Settings",
         "Open a game's project manifest (its reference/project.json) to edit its build settings and "
         "code page.",
         [("Open project...", lambda: self.open_project())],
         "project-settings", lambda p: self.open_project(p),
         skip=("Continue without a project", lambda: self.show_editor()), recent_title="Recent projects")
      self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
      self._update_title()
      if path:
         self.open_project(path)

   # -- PanelHost -------------------------------------------------------------------

   def show_status(self, text: str) -> None:
      """!Shows a message in the status bar.
      @param text  message
      @return None
      """
      self.statusBar().showMessage(text, STATUS_MS)

   def apply(self, label: str, fn: Callable[[], object]) -> bool:
      """!Runs a core edit (which makes its own undo step); errors become a message.
      @param label  what the change is called
      @param fn     callable without arguments
      @return True when it went through
      """
      if self.document is None:
         return False
      try:
         fn()
      except (DocumentError, OSError, engine.EngineNotFound) as e:
         QtWidgets.QMessageBox.warning(self, label, str(e))
         self.refresh()   # put the widgets back
         return False
      self.refresh()
      return True

   def run_edit(self, label: str, fn: Callable[[], object], document: Document | None = None) -> bool:
      """!Runs fn() inside document.edit(label) (PanelHost contract).
      @param label     undo label
      @param fn        callable
      @param document  Document to edit (default: the project)
      @return True when the edit went through
      """
      doc = document or self.document
      if doc is None:
         return False

      def edit() -> None:
         """!The edit block."""
         with doc.edit(label):
            fn()
      return self.apply(label, edit)

   def selection_changed(self) -> None:
      """!Nothing to choose between: update the title and menus.
      @return None
      """
      self._update_title()

   def active_document(self) -> Document | None:
      """!The document the tab in front edits (Undo / Redo): its panel's own, or the project manifest.
      @return Document, or None
      """
      panel = self.tabs.currentWidget()
      own = getattr(panel, "own_documents", None)
      if self.document is not None and callable(own) and own():
         return panel.current_document()
      return self.document

   def documents(self) -> list[Document]:
      """!Every open document: the project manifest and the panels' own.
      @return list
      """
      out = [self.document] if self.document is not None else []
      for p in self.panels:
         own = getattr(p, "own_documents", None)
         out += [d for d in (own() if callable(own) else []) if d not in out]
      return out

   def show_panel(self, panel_id: str) -> EditorPanel:
      """!Brings a panel's tab to the front (the battle editor's Text page opens the code page so).
      @param panel_id  e.g. "codepage"
      @return the panel
      @throws KeyError when the window hosts no such panel
      """
      found = [p for p in self.panels if p.panel_id == panel_id]
      if not found:
         raise KeyError(panel_id)
      self.tabs.setCurrentWidget(found[0])
      return found[0]

   def _tab_changed(self) -> None:
      """!Another tab is in front: the others stop, Undo / Redo follow its document.
      @return None
      """
      for p in self.panels:
         if p is not self.tabs.currentWidget():
            p.stop()
      self._update_title()

   def refresh(self) -> None:
      """!Refreshes every panel, the title and the menus.
      @return None
      """
      for p in self.panels:
         p.refresh()
      self._update_title()

   # -- window --------------------------------------------------------------------

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
         a.setShortcuts(shortcut)
      a.triggered.connect(lambda _checked=False: slot())
      menu.addAction(a)
      return a

   def _build_menus(self) -> None:
      """!File and Edit menus and the toolbar.
      @return None
      """
      keys = QtGui.QKeySequence.StandardKey
      m = self.menuBar().addMenu("&File")
      ## Open a project manifest.
      self.open_action = self._action(m, "&Open project...", lambda: self.open_project(), keys.Open)
      ## Save the manifest.
      self.save_action = self._action(m, "&Save", lambda: self.save(), keys.Save)
      m.addSeparator()
      self._action(m, "&Quit", lambda: self.close(), keys.Quit)
      m = self.menuBar().addMenu("&Edit")
      ## Undo.
      self.undo_action = self._action(m, "Undo", lambda: self._undo_redo(True), keys.Undo)
      ## Redo.
      self.redo_action = self._action(m, "Redo", lambda: self._undo_redo(False), keys.Redo)
      ## Help > Record performance.
      self.recorder = profiler.add_menu(self, "project-settings")
      ## Toolbar.
      self.file_bar = file_toolbar(self, [
         ("open", self.open_action, "Open a game's reference/project.json", "Open"),
         ("save", self.save_action, "Save the project manifest and its code page"),
         None,
         ("undo", self.undo_action, "Undo"),
         ("redo", self.redo_action, "Redo")])

   def _undo_redo(self, undo: bool) -> None:
      """!Undo or Redo of the tab in front's document.
      @param undo  True for undo
      @return None
      """
      doc = self.active_document()
      if doc is None:
         return
      if doc.undo() if undo else doc.redo():   # True when there was a step to undo / redo
         self.refresh()

   def _update_title(self) -> None:
      """!Title and enabled actions.
      @return None
      """
      doc = self.document
      if doc is None or doc.path is None:
         self.setWindowTitle("CapsuleCreatures Project Settings")
      else:
         mark = " *" if any(d.dirty for d in self.documents()) else ""
         game = doc.data.get("name") or doc.path.parent.parent.name
         self.setWindowTitle(f"{game} ({doc.path.parent.name}/{doc.path.name}){mark} - "
                             "CapsuleCreatures Project Settings")
      self.save_action.setEnabled(any(d.dirty for d in self.documents()))
      doc = self.active_document()
      undo = doc.undo_label() if doc is not None else None
      redo = doc.redo_label() if doc is not None else None
      self.undo_action.setEnabled(undo is not None)
      self.undo_action.setText(f"Undo {undo}" if undo else "Undo")
      self.redo_action.setEnabled(redo is not None)
      self.redo_action.setText(f"Redo {redo}" if redo else "Redo")

   def dialog_parent(self) -> QtWidgets.QWidget:
      """!Window dialogs belong to.
      @return QWidget
      """
      return self.start if self.start.isVisible() else self

   def show_editor(self) -> None:
      """!Shows the editor instead of the start window.
      @return None
      """
      self.start.hide()
      self.show()
      if self.document is None:
         self.show_status("No project open: File > Open project...")

   def launch(self) -> None:
      """!Shows the editor when something is open, else the start window.
      @return None
      """
      if self.document is not None:
         self.show()
      else:
         self.start.refresh()
         self.start.show()

   # -- files ---------------------------------------------------------------------

   def _confirm_discard(self) -> bool:
      """!Asks about unsaved changes.
      @return True to go ahead
      """
      for p in self.panels:
         p.commit()
      if not any(d.dirty for d in self.documents()):
         return True
      b = QtWidgets.QMessageBox.StandardButton
      answer = QtWidgets.QMessageBox.question(self.dialog_parent(), "Unsaved changes", "Save changes first?",
                                              b.Save | b.Discard | b.Cancel, b.Save)
      if answer == b.Save:
         return self.save()
      return answer == b.Discard

   def open_project(self, path: str | Path | None = None) -> None:
      """!Opens a project manifest.
      @param path  reference/project.json, or None to ask
      @return None
      """
      if not self._confirm_discard():
         return
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self.dialog_parent(), "Open project", "", PROJECT_FILTER)
         if not path:
            return
      try:
         doc = project.open_project(path)
      except DocumentError as e:
         QtWidgets.QMessageBox.warning(self.dialog_parent(), "Open project", str(e))
         return
      self.document = doc
      for p in self.panels:
         p.document_replaced()
      remember_file("project-settings", Path(path))
      self.start.hide()
      self.show()
      self._update_title()

   def save(self) -> bool:
      """!Saves the manifest.
      @return True when saved (or nothing to save)
      """
      for p in self.panels:
         p.commit()
      dirty = [d for d in self.documents() if d.dirty]
      if not dirty:
         return True
      try:
         for doc in dirty:
            doc.save()
      except (OSError, DocumentError) as e:
         QtWidgets.QMessageBox.warning(self, "Save", str(e))
         return False
      self.show_status("Saved " + ", ".join(d.path.name for d in dirty))
      self.refresh()
      return True

   def closeEvent(self, event: QtGui.QCloseEvent) -> None:
      """!Asks about unsaved changes before closing.
      @param event  QCloseEvent
      @return None
      """
      if self._confirm_discard():
         event.accept()
      else:
         event.ignore()
