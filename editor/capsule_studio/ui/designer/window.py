"""!The manifest designer's window (D-43 §5): the palette on the left, the canvas in the middle, the inspector on the
right and the problems below, with File, Edit, Arrange and View menus and a toolbar. It opens any manifest a
designer system edits (the system comes from the manifest's schema) and starts new ones of any system.

The window title starts with the file name and " *" while there are unsaved changes, as every studio window's does.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.designer import ops, registry
from ...core.designer.model import ModelError
from ...core.designer.session import DesignSession
from ...core.document import DocumentError
from ..widgets import STATUS_MS, StartPage, file_toolbar, remember_file, report_failure
from .canvas import PERCENT, ZOOM_STEP, DesignerScene, DesignerView
from .inspector import Inspector
from .palette import Palette, QuickAdd

## Tool name (recent files, settings).
TOOL = "manifest-designer"
## Shown in titles.
APP_TITLE = "Manifest Designer"
## File dialog filter.
MANIFEST_FILTER = "Manifests (*.json);;All files (*)"
## Mime type of copied elements on the clipboard (Diagram.to_json() of them, UTF-8 JSON).
CLIP_MIME = "application/x-capsule-designer-clip"
## How far pasted and duplicated copies sit from the originals, canvas units.
COPY_OFFSET = 40
## Window size when it opens, pixels.
WINDOW_SIZE = (1400, 860)
## Width of the side docks when they open, pixels.
DOCK_WIDTH = 260
## Height of the problems dock when it opens, pixels.
PROBLEMS_HEIGHT = 120
## Role of a problem item's element and link ids.
IDS_ROLE = QtCore.Qt.ItemDataRole.UserRole


class DesignerWindow(QtWidgets.QMainWindow):
   """!One manifest in the designer."""

   def __init__(self, path: str | Path | None = None, system_id: str | None = None) -> None:
      """!Creates the window, and opens a manifest (or starts a new one of a system).
      @param path       a manifest to open, or None
      @param system_id  with no path: the system of a new manifest; with a path: the system to open it with
      """
      super().__init__()
      ## The open manifest, or None.
      self.session = None
      ## The canvas's scene, or None.
      self.scene = None
      ## The canvas, or None.
      self.view = None
      ## The palette, or None.
      self.palette = None
      ## The inspector, or None.
      self.inspector = None
      ## The open add-by-typing popup, or None.
      self.quick_add = None
      ## Whether a refresh is scheduled.
      self._refresh_pending = False
      ## What the Document calls after each change (kept to unsubscribe it again).
      self._on_change = lambda: self._schedule_refresh()
      self.resize(*WINDOW_SIZE)
      self._build_docks()
      self._build_menus()
      ## The start page, shown until something is open.
      self.start = StartPage(APP_TITLE, "Open a manifest to see it as a diagram, or start a new one. Each kind of "
                             "data has its own designer; the right one opens with the file.",
                             [("Open...", lambda: self.open_file()), ("New...", lambda: self.new_file())], TOOL,
                             lambda p: self.open_file(p))
      if path is not None:
         self.open_file(path, system_id)
      elif system_id is not None:
         self._attach(DesignSession.new(system_id))
      self._update_title()

   def launch(self) -> None:
      """!Shows the designer when something is open, else the start page.
      @return None
      """
      if self.session is not None:
         self.show()
      else:
         self.start.refresh()
         self.start.show()

   # -- building ----------------------------------------------------------------------------------------------------

   def _build_docks(self) -> None:
      """!The palette, inspector and problems docks (filled when a manifest opens).
      @return None
      """
      area = QtCore.Qt.DockWidgetArea
      ## The palette's dock.
      self.palette_dock = QtWidgets.QDockWidget("Palette", self)
      self.palette_dock.setObjectName("palette")
      self.addDockWidget(area.LeftDockWidgetArea, self.palette_dock)
      ## The inspector's dock.
      self.inspector_dock = QtWidgets.QDockWidget("Inspector", self)
      self.inspector_dock.setObjectName("inspector")
      self.addDockWidget(area.RightDockWidgetArea, self.inspector_dock)
      ## The problems list.
      self.problems = QtWidgets.QListWidget()
      self.problems.itemActivated.connect(lambda item: self._locate(item))
      self.problems.itemClicked.connect(lambda item: self._locate(item))
      ## The problems' dock.
      self.problems_dock = QtWidgets.QDockWidget("Problems", self)
      self.problems_dock.setObjectName("problems")
      self.problems_dock.setWidget(self.problems)
      self.addDockWidget(area.BottomDockWidgetArea, self.problems_dock)
      self.resizeDocks([self.palette_dock, self.inspector_dock], [DOCK_WIDTH, DOCK_WIDTH],
                       QtCore.Qt.Orientation.Horizontal)
      self.resizeDocks([self.problems_dock], [PROBLEMS_HEIGHT], QtCore.Qt.Orientation.Vertical)
      ## The zoom in the status bar.
      self.zoom_label = QtWidgets.QLabel("")
      self.statusBar().addPermanentWidget(self.zoom_label)

   def _action(self, menu: QtWidgets.QMenu, text: str, slot: Callable[[], object], keys: str | None = None,
               tip: str = "") -> QtGui.QAction:
      """!A menu action.
      @param menu  the menu
      @param text  its text
      @param slot  what it does
      @param keys  its shortcut, or None
      @param tip   its status tip
      @return the action
      """
      action = menu.addAction(text)
      action.triggered.connect(lambda _c=False: slot())
      if keys:
         action.setShortcut(QtGui.QKeySequence(keys))
      if tip:
         action.setStatusTip(tip)
      return action

   def _build_menus(self) -> None:
      """!File, Edit, Arrange and View, and the toolbar.
      @return None
      """
      bar = self.menuBar()
      f = bar.addMenu("&File")
      self._action(f, "&New...", lambda: self.new_file(), "Ctrl+N", "Start a new manifest of a designer system")
      self._action(f, "&Open...", lambda: self.open_file(), "Ctrl+O")
      ## Save.
      self.save_action = self._action(f, "&Save", lambda: self.save_file(), "Ctrl+S")
      self._action(f, "Save &as...", lambda: self.save_as(), "Ctrl+Shift+S")
      f.addSeparator()
      self._action(f, "&Close", lambda: self.close(), "Ctrl+W")
      e = bar.addMenu("&Edit")
      ## Undo.
      self.undo_action = self._action(e, "&Undo", lambda: self.undo(), "Ctrl+Z")
      ## Redo.
      self.redo_action = self._action(e, "&Redo", lambda: self.redo(), "Ctrl+Shift+Z")
      e.addSeparator()
      self._action(e, "Cu&t", lambda: self.cut(), "Ctrl+X")
      self._action(e, "&Copy", lambda: self.copy(), "Ctrl+C")
      self._action(e, "&Paste", lambda: self.paste(), "Ctrl+V")
      self._action(e, "&Duplicate", lambda: self.duplicate(), "Ctrl+D", "Copy the selection with the wires between it")
      self._action(e, "De&lete", lambda: self.scene and self.scene.delete_selection())
      self._action(e, "Select &all", lambda: self.select_all(), "Ctrl+A")
      self._action(e, "Add by &typing...", lambda: self.ask_add(None, None, ""), "Ctrl+Space",
                   "Type the name of what to add")
      a = bar.addMenu("&Arrange")
      for edge, text in ((ops.ALIGN_LEFT, "Align &left"), (ops.ALIGN_CENTRE, "Align &centre"),
                         (ops.ALIGN_RIGHT, "Align &right"), (ops.ALIGN_TOP, "Align &top"),
                         (ops.ALIGN_MIDDLE, "Align &middle"), (ops.ALIGN_BOTTOM, "Align &bottom")):
         self._action(a, text, lambda edge=edge: self._arrange(lambda ids: self.session.align(ids, edge)),
                      tip="Line the selection up on the first element picked")
      a.addSeparator()
      self._action(a, "Distribute &horizontally", lambda: self._arrange(
         lambda ids: self.session.distribute(ids, ops.HORIZONTAL)))
      self._action(a, "Distribute &vertically", lambda: self._arrange(
         lambda ids: self.session.distribute(ids, ops.VERTICAL)))
      a.addSeparator()
      for which, text in ((ops.SAME_WIDTH, "Same &width"), (ops.SAME_HEIGHT, "Same h&eight"),
                          (ops.SAME_BOTH, "Same &size")):
         self._action(a, text, lambda which=which: self._arrange(lambda ids: self.session.same_size(ids, which)))
      a.addSeparator()
      self._action(a, "Bring to &front", lambda: self._arrange(self.session.to_front, 1), "Ctrl+Shift+]")
      self._action(a, "Send to bac&k", lambda: self._arrange(self.session.to_back, 1), "Ctrl+Shift+[")
      a.addSeparator()
      self._action(a, "Tid&y up", lambda: self.tidy_up(), "Ctrl+L", "Lay the nodes out in ranks along the flow")
      v = bar.addMenu("&View")
      self._action(v, "Zoom &in", lambda: self.view and self.view.zoom_by(ZOOM_STEP), "Ctrl+=")
      self._action(v, "Zoom &out", lambda: self.view and self.view.zoom_by(1 / ZOOM_STEP), "Ctrl+-")
      self._action(v, "&Actual size", lambda: self.view and self.view.set_zoom(PERCENT), "Ctrl+0")
      self._action(v, "Zoom to &fit", lambda: self.view and self.view.fit(), "Ctrl+9")
      self._action(v, "Zoom to &selection", lambda: self.view and self.scene and self.view.fit(
         self.scene.selected_elements()), "Ctrl+8")
      v.addSeparator()
      ## Snap to grid.
      self.snap_action = self._action(v, "S&nap to grid", lambda: self._set_scene_flag("snap_to_grid",
                                                                                        self.snap_action))
      self.snap_action.setCheckable(True)
      self.snap_action.setChecked(True)
      ## Show grid.
      self.grid_action = self._action(v, "Show &grid", lambda: self._set_scene_flag("show_grid", self.grid_action))
      self.grid_action.setCheckable(True)
      self.grid_action.setChecked(True)
      v.addSeparator()
      for dock in (self.palette_dock, self.inspector_dock, self.problems_dock):
         v.addAction(dock.toggleViewAction())
      ## The toolbar.
      self.toolbar = file_toolbar(self, [("open", self._find_action(f, "&Open..."), "Open a manifest"),
                                         ("save", self.save_action, "Save the manifest"), None,
                                         ("undo", self.undo_action, "Undo"), ("redo", self.redo_action, "Redo")])
      self.toolbar.addSeparator()
      for text, slot, tip in (("Tidy up", lambda: self.tidy_up(), "Lay the nodes out in ranks along the flow"),
                              ("Zoom to fit", lambda: self.view and self.view.fit(), "Show the whole diagram")):
         act = self.toolbar.addAction(text)
         act.setToolTip(tip)
         act.triggered.connect(lambda _c=False, slot=slot: slot())
      self.addToolBar(self.toolbar)

   def _find_action(self, menu: QtWidgets.QMenu, text: str) -> QtGui.QAction:
      """!A menu's action by text.
      @param menu  the menu
      @param text  its text
      @return the action
      """
      return next(a for a in menu.actions() if a.text() == text)

   def _set_scene_flag(self, name: str, action: QtGui.QAction) -> None:
      """!Sets a scene option from a checkable action.
      @param name    the scene attribute
      @param action  the action
      @return None
      """
      if self.scene is not None:
         setattr(self.scene, name, action.isChecked())
         self.scene.update()

   # -- the manifest ------------------------------------------------------------------------------------------------

   def _attach(self, session: DesignSession) -> None:
      """!Shows a session: a new canvas, palette and inspector for its system.
      @param session  the session
      @return None
      """
      if self.session is not None:
         self.session.doc.unsubscribe(self._on_change)
      if self.scene is not None:
         # The old manifest's canvas and panels go (setCentralWidget() deletes the old view itself).
         self.scene.close()
         self.scene.deleteLater()
         for old in (self.palette, self.inspector):
            if old is not None:
               old.deleteLater()
      self.session = session
      self.scene = DesignerScene(session, self)
      self.scene.snap_to_grid = self.snap_action.isChecked()
      self.scene.show_grid = self.grid_action.isChecked()
      self.view = DesignerView(self.scene)
      self.setCentralWidget(self.view)
      self.palette = Palette(session.system)
      self.palette.chosen.connect(lambda kind_id: self.add_in_view(kind_id))
      self.palette_dock.setWidget(self.palette)
      self.inspector = Inspector(session)
      self.inspector.refused.connect(lambda text: self.show_status(text))
      self.inspector_dock.setWidget(self.inspector)
      self.scene.refused.connect(lambda text: self.show_status(text))
      self.scene.picked.connect(lambda ids: self.inspector.show_ids(ids))
      self.scene.edit_requested.connect(lambda i: self._edit(i))
      self.scene.add_requested.connect(lambda screen, pos, wire_from: self.ask_add(screen, pos, wire_from))
      self.view.zoomed.connect(lambda percent: self.zoom_label.setText(f"{percent}%"))
      session.doc.subscribe(self._on_change)
      self.view.apply_view(session.diagram().view if self._readable() else {})
      self.start.hide()
      self.show()
      self._refresh()

   def _readable(self) -> bool:
      """!Whether the manifest can be shown.
      @return True when its diagram reads
      """
      try:
         self.session.diagram()
      except ModelError:
         return False
      return True

   def _confirm_discard(self) -> bool:
      """!Asks about unsaved changes.
      @return True to go on (saved or discarded), False to stay
      """
      if self.session is None or not self.session.doc.dirty:
         return True
      b = QtWidgets.QMessageBox.StandardButton
      answer = QtWidgets.QMessageBox.question(self, "Unsaved changes", "Save changes first?",
                                              b.Save | b.Discard | b.Cancel, b.Save)
      if answer == b.Save:
         return self.save_file()
      return answer == b.Discard

   def new_file(self, system_id: str | None = None) -> bool:
      """!Starts a new manifest of a system (asked for when not given).
      @param system_id  the system, or None to ask
      @return True when started
      """
      if not self._confirm_discard():
         return False
      if system_id is None:
         systems = registry.systems()
         names = [f"{s.title}" + (" (for developing the designer)" if s.dev_only else "") for s in systems]
         name, ok = QtWidgets.QInputDialog.getItem(self, "New", "What kind of data?", names, 0, False)
         if not ok:
            return False
         system_id = systems[names.index(name)].system_id
      self._attach(DesignSession.new(system_id))
      return True

   def open_file(self, path: str | Path | None = None, system_id: str | None = None) -> bool:
      """!Opens a manifest.
      @param path       the file, or None to ask
      @param system_id  the system to open it with, or None to find it from the schema
      @return True when opened
      """
      if not self._confirm_discard():
         return False
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open manifest", "", MANIFEST_FILTER)
         if not path:
            return False
      try:
         session = DesignSession.open(path, system_id)
      except (OSError, ValueError, DocumentError) as e:
         report_failure(self.start if self.session is None else self, "Open", f"{path}: {e}")
         return False
      remember_file(TOOL, path)
      self._attach(session)
      return True

   def save_file(self) -> bool:
      """!Saves (asks for a name when new); the view is kept with it.
      @return True when saved
      """
      if self.session is None:
         return False
      if self.session.doc.path is None:
         return self.save_as()
      try:
         self.session.save(view=self.view.view_state() if self.view is not None else None)
      except (OSError, DocumentError) as e:
         report_failure(self, "Save", str(e))
         return False
      remember_file(TOOL, self.session.doc.path)
      self.show_status(f"Saved {self.session.doc.path}")
      self._update_title()
      return True

   def save_as(self) -> bool:
      """!Saves under a new name.
      @return True when saved
      """
      if self.session is None:
         return False
      path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save manifest", f"{self.session.system.system_id}.json",
                                                      MANIFEST_FILTER)
      if not path:
         return False
      try:
         self.session.save(path, view=self.view.view_state() if self.view is not None else None)
      except (OSError, DocumentError) as e:
         report_failure(self, "Save", str(e))
         return False
      remember_file(TOOL, path)
      self._update_title()
      return True

   def closeEvent(self, event: QtGui.QCloseEvent) -> None:
      """!Asks about unsaved changes first.
      @param event  the event
      @return None
      """
      if self._confirm_discard():
         if self.scene is not None:
            self.scene.close()
         event.accept()
      else:
         event.ignore()

   # -- refreshing ----------------------------------------------------------------------------------------------------

   def _schedule_refresh(self) -> None:
      """!Refreshes the side panels once the current event is done (an edit may come from one of their own fields,
      which must not be rebuilt inside its own signal).
      @return None
      """
      if not self._refresh_pending:
         self._refresh_pending = True
         QtCore.QTimer.singleShot(0, self, lambda: self._refresh())

   def _refresh(self) -> None:
      """!The title, Undo / Redo, the inspector and the problems.
      @return None
      """
      self._refresh_pending = False
      if self.session is None:
         return
      if self.inspector is not None:
         self.inspector.refresh()
      self.problems.clear()
      for p in self.session.diagnostics():
         item = QtWidgets.QListWidgetItem(f"{p.severity}: {p.message}")
         item.setData(IDS_ROLE, list(p.elements) + list(p.links))
         self.problems.addItem(item)
      if not self.problems.count():
         done = QtWidgets.QListWidgetItem("No problems")
         done.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
         self.problems.addItem(done)
      doc = self.session.doc
      self.undo_action.setEnabled(doc.undo_label() is not None)
      self.undo_action.setText(f"&Undo {doc.undo_label()}" if doc.undo_label() else "&Undo")
      self.redo_action.setEnabled(doc.redo_label() is not None)
      self.redo_action.setText(f"&Redo {doc.redo_label()}" if doc.redo_label() else "&Redo")
      self._update_title()

   def _update_title(self) -> None:
      """!"name * - Manifest Designer (system)".
      @return None
      """
      if self.session is None:
         self.setWindowTitle(APP_TITLE)
         return
      doc = self.session.doc
      name = doc.path.name if doc.path is not None else "untitled"
      self.setWindowTitle(f"{name}{' *' if doc.dirty else ''} - {APP_TITLE} ({self.session.system.title})")

   def show_status(self, text: str) -> None:
      """!A message in the status bar.
      @param text  the message
      @return None
      """
      self.statusBar().showMessage(text, STATUS_MS)

   def _locate(self, item: QtWidgets.QListWidgetItem) -> None:
      """!Selects and shows what a problem names.
      @param item  the problem
      @return None
      """
      ids = item.data(IDS_ROLE) or []
      if self.scene is not None and ids:
         self.scene.select_ids(list(ids))
         self.view.fit([i for i in ids if i in self.scene.element_items])

   def _edit(self, element_id: str) -> None:
      """!Shows an element's fields and focuses the first.
      @param element_id  the element (or link)
      @return None
      """
      self.inspector_dock.show()
      if self.scene is not None:
         self.scene.select_ids([element_id])
      if self.inspector is not None and self.inspector.editors:
         next(iter(self.inspector.editors.values())).setFocus()

   # -- editing -------------------------------------------------------------------------------------------------------

   def _run(self, change: Callable[[], object]) -> object:
      """!Runs a session change; a refusal shows in the status bar.
      @param change  the change
      @return its result, or None
      """
      if self.session is None:
         return None
      try:
         return change()
      except ModelError as e:
         self.show_status(str(e))
         return None

   def undo(self) -> None:
      """!Undo.
      @return None
      """
      if self.session is not None and self.session.doc.undo():
         self.show_status("Undone")

   def redo(self) -> None:
      """!Redo.
      @return None
      """
      if self.session is not None and self.session.doc.redo():
         self.show_status("Redone")

   def _arrange(self, change: Callable[[list[str]], object], fewest: int = ops.ARRANGE_MIN) -> None:
      """!Runs an Arrange command on the selection.
      @param change  takes the selected element ids
      @param fewest  how many must be selected
      @return None
      """
      if self.scene is None:
         return
      ids = self.scene.selected_elements()
      if len(ids) < fewest:
         self.show_status(f"select at least {fewest} elements")
         return
      self._run(lambda: change(ids))

   def tidy_up(self) -> None:
      """!Auto-layout of the system's nodes.
      @return None
      """
      self._run(lambda: self.session.auto_layout())

   def select_all(self) -> None:
      """!Selects every element.
      @return None
      """
      if self.scene is not None:
         self.scene.select_ids(list(self.scene.element_items))

   def copy(self) -> bool:
      """!Copies the selection (with the wires between it) to the clipboard.
      @return True when something was copied
      """
      if self.scene is None or not self.scene.selected_elements():
         return False
      clip = self.session.copy(self.scene.selected_elements())
      data = QtCore.QMimeData()
      data.setData(CLIP_MIME, QtCore.QByteArray(json.dumps(clip).encode("utf-8")))
      data.setText(json.dumps(clip, indent=1))
      QtWidgets.QApplication.clipboard().setMimeData(data)
      return True

   def cut(self) -> None:
      """!Copies the selection and removes it.
      @return None
      """
      if self.copy():
         self.scene.delete_selection()

   def paste(self) -> None:
      """!Pastes copied elements a little below and right of the view's centre.
      @return None
      """
      if self.scene is None:
         return
      data = QtWidgets.QApplication.clipboard().mimeData()
      if data is None or not data.hasFormat(CLIP_MIME):
         self.show_status("nothing to paste")
         return
      clip = json.loads(bytes(data.data(CLIP_MIME).data()).decode("utf-8"))
      centre = self.view.mapToScene(self.view.viewport().rect().center())
      at = (self.scene.snap_length(centre.x() + COPY_OFFSET), self.scene.snap_length(centre.y() + COPY_OFFSET))
      made = self._run(lambda: self.session.paste(clip, at))
      if made:
         self.scene.select_ids(list(made.values()))

   def duplicate(self) -> None:
      """!Copies the selection next to itself.
      @return None
      """
      if self.scene is None or not self.scene.selected_elements():
         return
      made = self._run(lambda: self.session.duplicate(self.scene.selected_elements(), (COPY_OFFSET, COPY_OFFSET)))
      if made:
         self.scene.select_ids(list(made.values()))

   def add_in_view(self, kind_id: str) -> str | None:
      """!Adds a kind in the middle of the view (a double-click in the palette).
      @param kind_id  the kind
      @return the new element's id, or None
      """
      if self.scene is None:
         return None
      centre = self.view.mapToScene(self.view.viewport().rect().center())
      return self.scene.add_at(kind_id, centre)

   def ask_add(self, screen: QtCore.QPoint | None, pos: QtCore.QPointF | None, wire_from: str) -> None:
      """!Opens the add-by-typing popup (only the kinds a wire can end on, when one was dragged).
      @param screen     where to open it (None: the view's centre)
      @param pos        where the element goes on the canvas (None: the view's centre)
      @param wire_from  "element.port" a wire was dragged from, or ""
      @return None
      """
      if self.scene is None:
         return
      from ...core.designer.model import Endpoint
      kinds = self.session.system.kinds()
      if wire_from:
         fitting = set(self.session.fitting_kinds(Endpoint.parse(wire_from)))
         kinds = tuple(k for k in kinds if k.kind_id in fitting)
         if not kinds:
            self.show_status(f"nothing can be wired to {wire_from}")
            return
      if pos is None:
         pos = self.view.mapToScene(self.view.viewport().rect().center())
      if screen is None:
         screen = self.view.mapToGlobal(self.view.viewport().rect().center())
      at = QtCore.QPointF(pos)
      self.quick_add = QuickAdd(kinds, lambda kind_id: self.scene.add_at(kind_id, at, wire_from), self)
      self.quick_add.popup(screen)
