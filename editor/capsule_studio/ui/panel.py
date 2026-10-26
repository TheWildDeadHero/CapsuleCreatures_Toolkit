"""!The contract between editor panels and whatever hosts them.

Each editor is an EditorPanel: a self-contained widget that edits the host's
Document through capsule_studio.core. Each tool's window hosts its panels
in tabs (ui/*_shell.py); the Studio (ui/studio_shell.py) hosts those windows
as its pages, so the same panels run standalone and in the Studio. A panel
never opens files, owns menus or talks to another panel directly; it goes
through its PanelHost.

A host provides:
  - document:          the core Document being edited (may be replaced)
  - reports:           (problems, {key: AssetReport}) from the last validation
  - show_status(text): a short message for the status bar
  - run_edit(label, fn, document=None): calls fn() inside
                       (document or host.document).edit(label), turning
                       exceptions into a message instead of a crash; returns
                       True on success
  - selection_changed(): the panel's current_document() changed (another
                       map or tileset picked); the host updates Undo / Redo
A host of world panels (maps, tilesets) also provides:
  - project:           the core world Project (may be replaced)
  - changed():         the project was edited outside run_edit (a map or
                       tileset added); every panel is refreshed once, after
                       the current signal handler returns
  - shows_map():       whether a Map tab is hosted (extension panels offer to
                       follow its map only then); selected_map() and
                       select_map(name) read and set that tab's map
Undo and Redo act on the active panel's current_document().
[S2] A panel that edits files besides the host's Document (the text tables
and fonts an asset manifest names) lists them in extra_documents(); the
scene editor saves them with its manifest and counts them as unsaved changes.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from PySide6 import QtWidgets

if TYPE_CHECKING:
   from ..core.document import AssetReport, Document
   from ..core.world import Project

## Results of the last validation: (problems, {asset key: AssetReport}), or None before the first one.
Reports = tuple[list[str], dict[str | None, "AssetReport"]] | None


class PanelHost(Protocol):
   """!What every panel host provides (see the module docstring); for type annotations only."""

   ## The core Document being edited (may be replaced).
   document: Document
   ## Results of the last validation.
   reports: Reports

   def show_status(self, text: str) -> None:
      """!Shows a short message in the status bar.
      @param text  the message
      @return None
      """

   def run_edit(self, label: str, fn: Callable[[], object], document: Document | None = None) -> bool:
      """!Calls fn() inside (document or host.document).edit(label).
      @param label     undo label
      @param fn        the edit
      @param document  the Document to edit, or None for the host's
      @return True on success
      """

   def selection_changed(self) -> None:
      """!The panel's current_document() changed.
      @return None
      """


class EditorPanel(QtWidgets.QWidget):
   """!Base class of every editor panel."""

   ## Identifier used on the command line (--panel) and in settings.
   panel_id = "panel"
   ## Tab title.
   title = "Panel"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The PanelHost this panel belongs to.
      self.host = host

   def host_project(self) -> Project | None:
      """!The host's world Project, for world panels.
      @return Project, or None (hosts of asset panels have none)
      """
      return getattr(self.host, "project", None)

   @property
   def doc(self) -> Document:
      """!The host's current Document.
      @return Document
      """
      return self.host.document

   def current_document(self) -> Document | None:
      """!The document Undo / Redo should act on while this panel is active.
      @return a core Document, or None
      """
      return getattr(self.host, "document", None)

   def extra_documents(self) -> list[Document]:
      """![S2] Documents this panel edits besides the host's (saved and asked about with it).
      @return Documents (default none)
      """
      return []

   def document_replaced(self) -> None:
      """!Called when the host switches to another Document (new/open).
      Default: refresh().
      @return None
      """
      self.refresh()

   def refresh(self) -> None:
      """!Called after every change to the Document (edits, undo, redo).
      Panels re-read what they show; selection should survive.
      @return None
      """
      pass

   def reports_changed(self) -> None:
      """!Called when new validation results are in host.reports.
      @return None
      """
      pass

   def stop(self) -> None:
      """!Called before the panel is hidden or the host closes (stop timers).
      @return None
      """
      pass


def report_for(host: PanelHost, key: str | None) -> AssetReport | None:
   """!The validation report of one asset.
   @param host  PanelHost
   @param key   asset key
   @return AssetReport, or None before the first validation
   """
   reports = host.reports[1] if host.reports else {}
   return reports.get(key)
