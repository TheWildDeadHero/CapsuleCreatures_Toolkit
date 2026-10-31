"""!The window of a world: a PanelHost for world panels (maps, tilesets,
and the panels extensions add, such as Encounters). It is the map editor,
each standalone world tool and the Studio's World page.

The window owns the Project (world file plus the tileset and map documents
it lists), the File and Edit menus and the status bar. Each document keeps
its own undo history; Undo / Redo act on the active panel's current
document. Panels never open files or talk to each other.

While no world is open the window shows an empty state (NoWorldPage) instead
of its panels: why there is nothing to edit, and buttons that make or open a
world (the Studio's World page offers "Create a new world" and "Add an existing
world" for a game without one: set_empty_state()). A panel action that still
runs without a world says why in the status bar (EditorPanel.explain()).

Extensions (D-10, capsule_studio.plugins): the window holds a plugin
registry (`extensions`) with the studio's own extensions; opening a world
also loads the plugins its project (reference/project.json) lists. Panels
extensions register for this host's id (or ids) are added as tabs; the map
panel adds their tools and overlays. Host ids (plugins.registry): the map
editor ("map-editor", Map, Tileset, Levels and Movement modes; of the built-in extensions only the
override sets (S3) add a panel there), a world tool's own id with only extension panels (the encounter,
event, object and location editor apps), or STUDIO_HOSTS (the Studio's
World page: Map, Tileset and every world tool's panel).
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import engine
from ..core.document import DocumentError
from ..core.world import Project
from ..plugins import loader
from .editors.behaviors import BehaviorsPanel
from .editors.field_rules import LevelsPanel, ModesPanel
from .editors.map_field import MapFieldPanel
from .editors.mapedit import MapPanel
from .editors.tileset import TilesetPanel
from .editors.world_doors import WorldDoorsPanel
from .editors.world_interactions import InteractionsPanel
from . import background, profiler
from .panel import EditorPanel
from .panes import fit_panel
from .widgets import START_TITLE_EXTRA_POINTS, STATUS_MS, StartPage, button, file_toolbar, remember_file, \
   report_failure

if TYPE_CHECKING:
   from ..core.document import Document

## World panels, in tab order (the field rules after the map and tileset: S5c; the F2 Field panel; I2 / I3: the
## world's behaviors; S3 (D-30): door bindings and the draw order rule; S6b (C13b): the cell interaction rules last).
WORLD_PANELS = [MapPanel, TilesetPanel, LevelsPanel, ModesPanel, MapFieldPanel, BehaviorsPanel, WorldDoorsPanel,
                InteractionsPanel]
## File dialog filter for worlds.
WORLD_FILTER = "Worlds (world.json *.json);;All files (*)"
## Width of the window when it opens, pixels.
WINDOW_WIDTH = 1360
## Height of the window when it opens, pixels.
WINDOW_HEIGHT = 820
## Percent per whole (zoom factor to percent).
PERCENT = 100

## Heading of a world window's empty state while no world is open.
NO_WORLD_HEADING = "No world is open"
## What the empty state says.
NO_WORLD_TEXT = ("Open a world (its world.json) or make a new one; its maps, tilesets and the world's other panels "
                 "show here then.")
## Why a world panel's action did nothing while no world is open (status bar).
NO_WORLD_REASON = "no world is open (File > Open world... or New world...)"
## Smallest height of the empty state's buttons, pixels.
EMPTY_BUTTON_HEIGHT = 36
## Widest the empty state's text grows, pixels.
EMPTY_TEXT_WIDTH = 520
## Space between the empty state's heading, text and buttons, pixels.
EMPTY_SPACING = 12

## A button of the empty state: (label, callable).
EmptyAction = tuple[str, Callable[[], object]]

## Worlds of up to this many maps are compiled at once when they open (a few seconds at most). Larger ones (I2: the
## imported world's 500-odd maps take about 15 s and 1 GB) are not compiled on open: the pure-Python compile
## holds the interpreter lock, so on a thread it slows the editor tenfold. World > Validate compiles them on a
## background thread (ui/background.py), and every map shown compiles on its own against its tilesets.
SYNC_VALIDATE_MAPS = 64

class NoWorldPage(QtWidgets.QWidget):
   """!What a world window shows instead of its panels while no world is open: a heading, a sentence on what to
   do, and buttons that make or open a world. Nothing on it is disabled; every button does something."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the page (set_message() fills it).
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The heading.
      self.heading = QtWidgets.QLabel()
      font = self.heading.font()
      font.setPointSize(font.pointSize() + START_TITLE_EXTRA_POINTS)
      font.setBold(True)
      self.heading.setFont(font)
      self.heading.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
      ## The sentence under it.
      self.text = QtWidgets.QLabel()
      self.text.setWordWrap(True)
      self.text.setMaximumWidth(EMPTY_TEXT_WIDTH)
      self.text.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
      ## The buttons, by label.
      self.buttons = {}
      ## Row of the buttons.
      self._row = QtWidgets.QHBoxLayout()
      box = QtWidgets.QVBoxLayout(self)
      box.addStretch(1)
      box.addWidget(self.heading, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
      box.addSpacing(EMPTY_SPACING)
      box.addWidget(self.text, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
      box.addSpacing(EMPTY_SPACING)
      box.addLayout(self._row)
      box.addStretch(1)

   def set_message(self, heading: str, text: str, actions: Sequence[EmptyAction]) -> None:
      """!Shows a heading, a sentence and buttons (the old buttons go).
      @param heading  the heading
      @param text     what to do
      @param actions  [(button label, callable), ...]
      @return None
      """
      self.heading.setText(heading)
      self.text.setText(text)
      for b in self.buttons.values():
         self._row.removeWidget(b)
         b.deleteLater()
      self.buttons = {}
      while self._row.count():   # the stretches around the old buttons
         self._row.takeAt(0)
      self._row.addStretch(1)
      for label, slot in actions:
         b = button(label, slot)
         b.setMinimumHeight(EMPTY_BUTTON_HEIGHT)
         b.setDefault(not self.buttons)   # the first one is what Enter does
         self.buttons[label] = b
         self._row.addWidget(b)
      self._row.addStretch(1)


class WorldWindow(QtWidgets.QMainWindow):
   """!Main window hosting world panels (implements PanelHost, see panel.py)."""

   def __init__(self, panel_classes: Sequence[type[EditorPanel]] | None = None, path: str | Path | None = None,
                host_id: str | Iterable[str] = "map-editor", title: str = "CapsuleCreatures Map Editor",
                panel_ids: Collection[str] | None = None) -> None:
      """!Creates the window.
      @param panel_classes  built-in panels to host (default: WORLD_PANELS; [] for none)
      @param path           world.json to open, or None
      @param host_id        which extension panels it shows (plugins.registry.PanelSpec.hosts): an id or several
      @param title          application title
      @param panel_ids      only these panels (built-in or extension ids), or None for all
      """
      super().__init__()
      ## Host id for extension panels.
      self.host_id = host_id
      ## Name of this tool's recent-worlds list and performance reports (the map editor's on the Studio's page).
      self.tool_name = host_id if isinstance(host_id, str) else "map-editor"
      ## Application title.
      self.app_title = title
      ## Plugin registry: the studio's own extensions plus the open project's plugins.
      self.extensions = loader.builtin_registry().copy()
      ## Plugin ids the open project loaded (dropped when another world opens).
      self._project_plugins = []
      ## Panel ids shown, or None for all.
      self._panel_ids = panel_ids
      ## Extension panels shown: panel id -> EditorPanel.
      self._ext_panels = {}
      ## The open Project, or None.
      self.project = None
      ## A refresh is scheduled (see changed()).
      self._refresh_pending = False
      ## Unused by world panels; present for the PanelHost contract.
      self.reports = None
      ## The hosted EditorPanel instances.
      self.panels = []
      ## Why a panel's action did nothing while no world is open (EditorPanel.explain(); the Studio sets its own).
      self.no_world_reason = NO_WORLD_REASON
      ## The tab widget.
      self.tabs = QtWidgets.QTabWidget()
      self._build_menus()   # before the tabs: their signals update the menus
      for cls in WORLD_PANELS if panel_classes is None else panel_classes:
         if panel_ids is None or cls.panel_id in panel_ids:
            panel = cls(self)
            fit_panel(panel)   # [RZ] scroll bars instead of a window larger than the screen
            self.panels.append(panel)
            self.tabs.addTab(panel, panel.title)
      self._sync_extension_panels()
      if not self.panels:
         raise DocumentError("no panel to show (check --panel and the extensions that loaded)")
      ## Start page, shown until a world is open.
      self.start = StartPage(
         title,
         "Open a world (its world.json) or create a new one to start editing.",
         [("Open world...", lambda: self.open_world()), ("New world...", lambda: self.new_world())],
         self.tool_name, lambda path: self.open_world(path),
         skip=("Continue without a world", lambda: self.show_editor()), recent_title="Recent worlds")
      ## The empty state, shown instead of the panels while no world is open.
      self.empty = NoWorldPage()
      self.empty.set_message(NO_WORLD_HEADING, NO_WORLD_TEXT,
                             [("New world...", lambda: self.new_world()), ("Open world...", lambda: self.open_world())])
      ## The empty state or the tabs (the tab bar shows only with several panels).
      self.body = QtWidgets.QStackedWidget()
      self.body.addWidget(self.empty)
      self.body.addWidget(self.tabs)
      self.setCentralWidget(self.body)
      self._show_body()
      self.tabs.currentChanged.connect(lambda *a: self._tab_changed(*a))
      self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
      self._update_title()
      if path:
         self.open_world(path)

   def _sync_extension_panels(self) -> None:
      """!Adds tabs for extension panels registered for this host (and removes those of unloaded plugins).
      @return None
      """
      specs = {s.panel_id: s for s in self.extensions.panels(self.host_id)
               if self._panel_ids is None or s.panel_id in self._panel_ids}
      for pid in [k for k in self._ext_panels if k not in specs]:
         panel = self._ext_panels.pop(pid)
         panel.stop()
         self.panels.remove(panel)   # first: removeTab may signal currentChanged
         self.tabs.removeTab(self.tabs.indexOf(panel))
         panel.deleteLater()
      for pid, spec in specs.items():
         if pid in self._ext_panels:
            continue
         try:
            panel = spec.factory(self)
         except Exception as e:   # a broken extension panel must not stop the editor
            self.extensions.errors.append((spec.plugin, f"panel {pid}: {e}"))
            continue
         fit_panel(panel)
         self._ext_panels[pid] = panel
         self.panels.append(panel)
         self.tabs.addTab(panel, spec.title)
      self.tabs.tabBar().setVisible(len(self.panels) > 1)

   def set_empty_state(self, heading: str, text: str, actions: Sequence[EmptyAction], reason: str) -> None:
      """!What the window shows and says while no world is open (the Studio's World page: a game without a world).
      @param heading  the empty state's heading
      @param text     what to do
      @param actions  its buttons: [(label, callable), ...]
      @param reason   why a panel's action does nothing meanwhile (status bar)
      @return None
      """
      self.empty.set_message(heading, text, actions)
      self.no_world_reason = reason

   def _show_body(self) -> None:
      """!Shows the panels while a world is open, else the empty state.
      @return None
      """
      self.body.setCurrentWidget(self.tabs if self.project is not None else self.empty)

   def selected_map(self) -> str | None:
      """!The map the map panel shows (extension panels follow it).
      @return map name, or None
      """
      for p in self.panels:
         if isinstance(p, MapPanel):
            return p.map_name
      return None

   def shows_map(self) -> bool:
      """!Whether the window has a Map tab for extension panels to follow
      (the map editor and the Studio's World page; the standalone world tools have none).
      @return True when a map panel is hosted
      """
      return any(isinstance(p, MapPanel) for p in self.panels)

   def select_map(self, name: str) -> bool:
      """!Shows a map in the map panel (an extension panel asked to).
      @param name  map name
      @return True when a map panel showed it
      """
      for p in self.panels:
         if isinstance(p, MapPanel):
            p.select_map(name)
            self.tabs.setCurrentWidget(p)
            return True
      return False

   def dialog_parent(self) -> QtWidgets.QWidget:
      """!Window dialogs belong to: the start window while it is the one shown.
      @return QWidget
      """
      return self.start if self.start.isVisible() else self

   def show_editor(self) -> None:
      """!Shows the editor window (with or without a world open) instead of the start window.
      @return None
      """
      self.start.hide()
      self.show()
      if self.project is None:
         self.show_status(f"Nothing to edit: {self.no_world_reason}")

   def launch(self) -> None:
      """!Shows the editor when something is open, else the start window
      (closing that one ends the program).
      @return None
      """
      if self.project is not None:
         self.show()
      else:
         self.start.refresh()
         self.start.show()

   # -- PanelHost -------------------------------------------------------------------

   @property
   def document(self) -> Document | None:
      """!The active panel's current document (for Undo / Redo).
      @return Document, or None
      """
      panel = self.active_panel()
      if panel is None or self.project is None:
         return None
      # A panel that does not override current_document() has no document of its own here.
      if type(panel).current_document is EditorPanel.current_document:
         return None   # the default would ask the host again (asset panels have no world document)
      return panel.current_document()

   def active_panel(self) -> EditorPanel | None:
      """!The panel in front.
      @return EditorPanel, or None
      """
      w = self.tabs.currentWidget()
      return w if w in self.panels else None

   def show_status(self, text: str) -> None:
      """!Shows a message in the status bar.
      @param text  message
      @return None
      """
      self.statusBar().showMessage(text, STATUS_MS)

   def run_edit(self, label: str, fn: Callable[[], object], document: Document | None = None) -> bool:
      """!Runs fn() inside document.edit(label); errors become a message (widgets.report_failure()).
      @param label     undo label
      @param fn        callable
      @param document  Document to edit (default: the active panel's)
      @return True when the edit went through
      """
      doc = document or self.document
      if doc is None:
         self.show_status(f"{label}: {self.no_world_reason if self.project is None else 'nothing is chosen'}")
         return False
      revision = doc.revision
      try:
         with doc.edit(label):
            fn()
      except (DocumentError, ValueError, KeyError, IndexError, OSError, engine.EngineNotFound) as e:
         report_failure(self, label, str(e))   # headless: the status bar only (nothing waits for a click)
         return False
      if doc.revision == revision:   # it went through and changed nothing (no undo step): say so
         self.show_status(f"{label}: nothing to change")
      self.changed()
      return True

   def selection_changed(self) -> None:
      """!The active panel picked another document: update Undo / Redo.
      @return None
      """
      self._update_title()

   def changed(self) -> None:
      """!Something in the project changed: refresh every panel once, after
      the current signal handler returns (panels may be inside a signal of a
      widget the refresh rebuilds).
      @return None
      """
      if not self._refresh_pending:
         self._refresh_pending = True
         QtCore.QTimer.singleShot(0, lambda: self._refresh_now())

   def _refresh_now(self) -> None:
      """!Runs the refresh changed() scheduled.
      @return None
      """
      self._refresh_pending = False
      for p in self.panels:
         p.refresh()
      self._update_title()

   # -- project -----------------------------------------------------------------------

   def _attach(self, project: Project) -> None:
      """!Switches to a project.
      @param project  Project
      @return None
      """
      ids, _proj = loader.load_project_plugins(self.extensions, project.world.path, self._project_plugins)
      self._project_plugins = ids
      self._sync_extension_panels()
      old, self.project = self.project, project
      try:
         for p in self.panels:
            p.document_replaced()
      except Exception as e:   # a malformed tileset or map: go back to the previous project
         self.project = old
         for p in self.panels:
            p.document_replaced()
         self._update_title()
         self._show_body()
         raise DocumentError(f"cannot show this world: {e}") from e
      self._show_body()
      self.start.hide()
      if not self.isVisible():
         self.show()
      remember_file(self.tool_name, project.world.path)
      self._update_title()
      failed = [msg for _where, msg in self.extensions.errors]
      self.extensions.errors.clear()
      if failed:
         QtWidgets.QMessageBox.warning(self, "Plugins", "Some plugins were not loaded:\n\n" + "\n".join(failed))
      loaded = f"; plugins: {', '.join(ids)}" if ids else ""
      if len(project.map_names()) <= SYNC_VALIDATE_MAPS:
         error = project.validate()
         self.show_status((f"compile error: {error}" if error else "world compiles") + loaded)
         return
      # I2: a large world is not compiled whole on open (see SYNC_VALIDATE_MAPS); each map compiles when shown
      self.show_status(f"{len(project.map_names())} maps, {len(project.tileset_names())} tilesets: World > "
                       f"Validate compiles the whole world in the background{loaded}")

   def _checked(self, project: Project, result: tuple[object, str | None], note: str, ask: bool) -> None:
      """!A background whole-world compile is done (I2): reports it, unless another world was opened meanwhile.
      @param project  the Project it compiled
      @param result   (compile_world() result or None, error or None)
      @param note     text added to the status line
      @param ask      show an error in a message box (Validate) rather than the status bar only
      @return None
      """
      if project is not self.project:
         return
      error = result[1]
      if error and ask:
         QtWidgets.QMessageBox.warning(self, "Validate", error)
      self.show_status((f"compile error: {error}" if error else "world compiles") + note)

   def profile_notes(self) -> list[str]:
      """!What the performance report should know about the open world.
      @return list of lines
      """
      if self.project is None:
         return ["no world open"]
      mp = self.panels[0]
      canvas = getattr(mp, "canvas", None)
      notes = [f"world {self.project.world.path}: {len(self.project.map_names())} maps, "
               f"{len(self.project.tileset_names())} tilesets"]
      if canvas is not None:
         notes.append(f"map {getattr(mp, 'map_name', None)}: canvas {canvas.width()}x{canvas.height()} px, "
                      f"zoom {round(canvas.zoom * PERCENT)}%, {len(getattr(mp, 'images', {}))} metatile pictures")
      return notes

   def _update_title(self) -> None:
      """!Window title and Undo / Redo labels.
      @return None
      """
      if self.project is None:
         self.setWindowTitle(self.app_title)
      else:
         mark = " *" if self.project.dirty else ""
         self.setWindowTitle(f"{self.project.world.path.parent.name}{mark} - {self.app_title}")
      for a in self.project_actions:
         a.setEnabled(self.project is not None)
      doc = self.document
      undo = doc.undo_label() if doc is not None else None
      redo = doc.redo_label() if doc is not None else None
      self.save_action.setEnabled(doc is not None and (doc.dirty or bool(doc.pending) or self.project.world.dirty))
      self.save_all_action.setEnabled(self.project is not None and self.project.dirty)
      self.undo_action.setEnabled(undo is not None)
      self.redo_action.setEnabled(redo is not None)
      self.undo_action.setText(f"Undo {undo or ''}".strip())
      self.redo_action.setText(f"Redo {redo or ''}".strip())

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
      """!File and Edit menus.
      @return None
      """
      keys = QtGui.QKeySequence.StandardKey
      m = self.menuBar().addMenu("&File")
      self._action(m, "&New world...", lambda: self.new_world(), keys.New)
      ## Opens a world.
      self.open_action = self._action(m, "&Open world...", lambda: self.open_world(), keys.Open)
      ## Imports maps and tilesets from another world.
      self.import_action = self._action(m, "&Import from another world...", lambda: self.import_world())
      ## Saves the document being edited (and the world file, when it changed).
      self.save_action = self._action(m, "&Save", lambda: self.save_current(), keys.Save)
      ## Saves every changed document.
      self.save_all_action = self._action(m, "Save a&ll", lambda: self.save_all(), keys.SaveAs)
      ## Actions that need an open world.
      self.project_actions = [self.save_all_action, self.import_action,
                              self._action(m, "&Validate", lambda: self.validate())]
      m.addSeparator()
      self._action(m, "&Quit", lambda: self.close(), keys.Quit)
      m = self.menuBar().addMenu("&Edit")
      ## Undo action.
      self.undo_action = self._action(m, "Undo", lambda: self.undo(), keys.Undo)
      ## Redo action.
      self.redo_action = self._action(m, "Redo", lambda: self.redo(), keys.Redo)
      ## Help > Record performance.
      self.recorder = profiler.add_menu(self, self.tool_name)
      ## Save / Save all / Undo / Redo buttons (the same actions as the menus).
      self.file_bar = file_toolbar(self, [
         ("open", self.open_action, "Open a world (its world.json)", "Open"),
         ("import", self.import_action, "Import maps and tilesets from another world, with the tilesets, sheet "
                                        "images and behaviors they need", "Import"),
         None,
         ("save", self.save_action, "Save the map or tileset you are editing"),
         ("save_all", self.save_all_action, "Save every changed map, tileset and the world"),
         None,
         ("undo", self.undo_action, "Undo the last change to the map or tileset you are editing"),
         ("redo", self.redo_action, "Redo the change you undid")])

   def undo(self) -> None:
      """!Undoes the active document's last edit.
      @return None
      """
      doc = self.document
      if doc is not None and doc.undo():
         self.changed()

   def redo(self) -> None:
      """!Redoes the active document's last undone edit.
      @return None
      """
      doc = self.document
      if doc is not None and doc.redo():
         self.changed()

   def _confirm_discard(self) -> bool:
      """!Asks about unsaved changes.
      @return True to go ahead
      """
      if self.project is None or not self.project.dirty:
         return True
      b = QtWidgets.QMessageBox.StandardButton
      answer = QtWidgets.QMessageBox.question(self, "Unsaved changes", "Save all changes first?",
                                              b.Save | b.Discard | b.Cancel, b.Save)
      if answer == b.Save:
         return self.save_all()
      return answer == b.Discard

   def new_world(self) -> None:
      """!Creates an empty world in a chosen folder.
      @return None
      """
      if not self._confirm_discard():
         return
      folder = QtWidgets.QFileDialog.getExistingDirectory(self.dialog_parent(), "Folder for the new world")
      if not folder:
         return
      try:
         self._attach(Project.create(Path(folder) / "world.json", Path(folder).name))
      except (DocumentError, OSError) as e:
         QtWidgets.QMessageBox.warning(self.dialog_parent(), "New world", str(e))

   def open_world(self, path: str | Path | None = None) -> None:
      """!Opens a world.
      @param path  world.json, or None to ask
      @return None
      """
      if not self._confirm_discard():
         return
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self.dialog_parent(), "Open world", "", WORLD_FILTER)
         if not path:
            return
      try:
         self._attach(Project.open(path))
      except (DocumentError, OSError, ValueError) as e:
         QtWidgets.QMessageBox.warning(self.dialog_parent(), "Open world", f"{path}: {e}")

   def import_world(self) -> None:
      """!Imports maps and tilesets from another world (asks which).
      @return None
      """
      if self.project is None:
         self.show_status(f"Import: {self.no_world_reason}; imports go into the open world")
         return
      path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import from world", "", WORLD_FILTER)
      if not path:
         return
      from .world_import import ImportWorldDialog
      try:
         source = Project.open(path)
      except (DocumentError, OSError, ValueError) as e:
         QtWidgets.QMessageBox.warning(self, "Import", f"{path}: {e}")
         return
      dlg = ImportWorldDialog(self.project, source, self)
      accepted = dlg.exec()
      chosen = dlg.choice()
      dlg.deleteLater()
      if not accepted:
         return
      try:
         report = self.project.import_from(path, *chosen)
      except (DocumentError, OSError, ValueError, KeyError) as e:
         QtWidgets.QMessageBox.warning(self, "Import", str(e))
         return
      if chosen[0]:
         first = self.project.map_names()[-len(chosen[0])]   # imported maps are listed last
         for panel in self.panels:
            if hasattr(panel, "map_name"):
               panel.map_name = first
      self.changed()
      self.show_status(report[0] + " (unsaved: Save all writes it)")
      if len(report) > 1:
         QtWidgets.QMessageBox.information(self, "Import", "\n".join(report))

   def save_current(self) -> bool:
      """!Saves the document the active tab is editing (and the world file, when it changed).
      @return True when saved
      """
      doc = self.document
      if self.project is None or doc is None:
         return True
      for p in self.panels:
         p.stop()
      try:
         self.project.save_document(doc)
      except (DocumentError, OSError) as e:
         QtWidgets.QMessageBox.warning(self, "Save", str(e))
         return False
      self.show_status(f"Saved {doc.path.name}")
      self._update_title()
      return True

   def save_all(self) -> bool:
      """!Saves every changed document.
      @return True when saved
      """
      if self.project is None:
         return True
      for p in self.panels:
         p.stop()
      try:
         self.project.save_all()
      except (DocumentError, OSError) as e:
         QtWidgets.QMessageBox.warning(self, "Save", str(e))
         return False
      self.show_status("Saved")
      self._update_title()
      return True

   def validate(self) -> None:
      """!Compiles the world and reports in the status bar.
      @return None
      """
      if self.project is None:
         self.show_status(f"Validate: {self.no_world_reason}")
         return
      if len(self.project.map_names()) > SYNC_VALIDATE_MAPS:   # I2: a large world compiles in the background
         self.show_status("Compiling the whole world in the background...")
         background.start(self, "validate", self.project.snapshot(),
                          lambda result, project=self.project: self._checked(project, result, "", True))
         return
      error = self.project.validate()   # engine problems come back as messages
      if error:
         QtWidgets.QMessageBox.warning(self, "Validate", error)
      else:
         self.show_status("The world compiles.")

   def _tab_changed(self, index: int) -> None:
      """!Refreshes Undo / Redo labels for the new active panel.
      @param index  tab index
      @return None
      """
      for i, p in enumerate(self.panels):
         if i != index:
            p.stop()
      self._update_title()

   def closeEvent(self, event: QtGui.QCloseEvent) -> None:
      """!Asks about unsaved changes before closing.
      @param event  QCloseEvent
      @return None
      """
      if self._confirm_discard():
         event.accept()
      else:
         event.ignore()
