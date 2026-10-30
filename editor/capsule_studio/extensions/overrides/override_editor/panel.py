"""!The Override sets panel (S3, D-30 section 2): a map's named cell override sets.

A tab of the map editor and the Studio's World page; it follows the map chosen in the Map tab. The list shows the
map's sets; Add / Rename / Remove change them (a rename follows into the scripts' `override apply|clear NAME`,
saved at once; a removal is refused while scripts name the set). The chosen set's persistence comes from the
world's scripts manifest (a flag, or a variable and a non-zero value; or none: until the map is left). The layer and
metatile chosen here are what the Override sets map tool paints (maptools.SELECTION); the cell table lists the
set's cells. The preview draws the set's cells and their surroundings applied or cleared, as the engine shows them.
Every change goes through the host's run_edit() on the map's Document; everything here is also a
`capsule-studio overrides` command (commands.py).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6 import QtWidgets

from capsule_studio.core import engine, events, maps, override_sets
from capsule_studio.ui.panel import EditorPanel
from capsule_studio.ui.qtimage import to_qimage
from capsule_studio.ui.widgets import PixelView, button, set_enabled

from . import maptools

if TYPE_CHECKING:
   from PySide6 import QtGui

   from capsule_studio.core.document import Document
   from capsule_studio.core.world import Project
   from capsule_studio.ui.world_shell import WorldWindow

## Errors meaning the engine (its compilers) is missing or too old, or the scripts do not compile.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError, IndexError, KeyError)
## Persistence choices, in core.override_sets.persist_kinds() order.
PERSIST_LABELS = ("until the map is left", "through a flag", "through a variable")
## The metatile chooser's entry for "nothing" (the layer shows no metatile).
NOTHING = "(nothing)"
## A cell record's raw entries key.
ENTRIES = "entries"
## Cell table columns.
CELL_COLUMNS = ("Cell", "Layer", "Shows")
## Preview zoom and cells drawn around the set.
PREVIEW_ZOOM, PREVIEW_MARGIN = 3, 1
## Layout stretch of the set column and of the form column.
LIST_STRETCH, FORM_STRETCH = 1, 2


class OverrideSetsPanel(EditorPanel):
   """!Edits a map's override sets (core.override_sets)."""

   ## See EditorPanel.panel_id.
   panel_id = "overrides"
   ## See EditorPanel.title.
   title = "Override sets"

   def __init__(self, host: WorldWindow, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The map shown, or None.
      self.map_name = None
      ## The chosen set's name, or None.
      self.chosen = None
      ## True while widgets are being filled.
      self._filling = False

      ## The map shown.
      self.map_box = QtWidgets.QComboBox()
      self.map_box.currentTextChanged.connect(lambda t: self._map_chosen(t))
      ## Follow the map chosen in the Map tab.
      self.follow = QtWidgets.QCheckBox("Follow the Map tab")
      self.follow.setChecked(True)
      self.follow.toggled.connect(lambda on: on and self._follow())
      self.follow.setVisible(getattr(host, "shows_map", lambda: True)())
      top = QtWidgets.QHBoxLayout()
      top.addWidget(QtWidgets.QLabel("Map"))
      top.addWidget(self.map_box, 1)
      top.addWidget(self.follow)

      ## The map's sets.
      self.list = QtWidgets.QListWidget()
      self.list.currentRowChanged.connect(lambda _r: self._set_picked())
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Sets (scripts: override apply NAME; / override clear NAME;)"))
      left.addWidget(self.list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_set(), "A new set, with the map's first painted cell (paint "
                                                             "its cells with the Override sets map tool)"))
      row.addWidget(button("Rename...", lambda: self.rename_set(), "Scripts naming it follow (saved at once)"))
      row.addWidget(button("Remove", lambda: self.remove_set(), "Refused while scripts name it"))
      left.addLayout(row)

      # -- persistence
      ## How the set lasts.
      self.persist = QtWidgets.QComboBox()
      self.persist.addItems(list(PERSIST_LABELS))
      self.persist.activated.connect(lambda _i: self._persist_changed())
      ## The flag or variable (of the scripts manifest).
      self.which = QtWidgets.QComboBox()
      self.which.setEditable(True)
      self.which.activated.connect(lambda _i: self._persist_changed())
      self.which.lineEdit().editingFinished.connect(lambda: self._persist_changed())
      ## The variable's value.
      self.value = QtWidgets.QSpinBox()
      self.value.setKeyboardTracking(False)
      self.value.valueChanged.connect(lambda _v: self._persist_changed())
      form = QtWidgets.QFormLayout()
      form.addRow("Lasts", self.persist)
      form.addRow("Flag / variable", self.which)
      form.addRow("Value", self.value)

      # -- painting
      ## The layer the map tool paints.
      self.layer = QtWidgets.QSpinBox()
      self.layer.valueChanged.connect(lambda _v: self._paint_choice())
      ## The metatile it paints.
      self.metatile = QtWidgets.QComboBox()
      self.metatile.activated.connect(lambda _i: self._paint_choice())
      form.addRow("Paint on layer", self.layer)
      form.addRow("Paint metatile", self.metatile)
      ## The set's cells.
      self.cells = QtWidgets.QTableWidget(0, len(CELL_COLUMNS))
      self.cells.setHorizontalHeaderLabels(list(CELL_COLUMNS))
      self.cells.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.cells.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.cells.horizontalHeader().setStretchLastSection(True)
      cell_row = QtWidgets.QHBoxLayout()
      cell_row.addWidget(button("Take out", lambda: self.erase_selected(), "Take the chosen cells out of the set"))
      cell_row.addWidget(button("Repaint", lambda: self.repaint_selected(),
                                "The chosen cells show the paint metatile on the paint layer"))
      cell_row.addStretch(1)

      # -- preview
      ## Applied (else cleared).
      self.applied = QtWidgets.QCheckBox("Applied (as after `override apply`)")
      self.applied.setChecked(True)
      self.applied.toggled.connect(lambda _on: self.update_preview())
      ## The picture.
      self.preview = PixelView(PREVIEW_ZOOM)
      ## Problems.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)

      mid = QtWidgets.QVBoxLayout()
      mid.addLayout(form)
      mid.addWidget(self.cells, 1)
      mid.addLayout(cell_row)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(self.applied)
      right.addWidget(self.preview, 1)
      right.addWidget(self.problems)
      body = QtWidgets.QHBoxLayout()
      body.addLayout(left, LIST_STRETCH)
      body.addLayout(mid, FORM_STRETCH)
      body.addLayout(right, FORM_STRETCH)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addLayout(top)
      lay.addLayout(body, 1)
      lo, hi = self._value_range()
      self.value.setRange(lo, hi)
      self.refresh()

   # -- host ---------------------------------------------------------------------------------

   def project(self) -> Project | None:
      """!The host's world Project.
      @return Project, or None
      """
      return self.host_project()

   def map_doc(self) -> Document | None:
      """!The shown map's Document.
      @return Document, or None
      """
      p = self.project()
      if p is None or self.map_name not in p.map_names():
         return None
      return p.map(self.map_name)

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the shown map.
      @return Document, or None
      """
      return self.map_doc()

   @staticmethod
   def _value_range() -> tuple[int, int]:
      """!A variable-persisted set's values (the engine's).
      @return (lo, hi)
      """
      try:
         return override_sets.value_range()
      except ENGINE_ERRORS:
         return 0, 0

   def _edit(self, label: str, fn: Callable[[], object]) -> bool:
      """!Runs an edit of the shown map through the host.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      doc = self.map_doc()
      if self._filling or doc is None:
         return False
      ok = self.host.run_edit(label, fn, doc)
      if not ok:
         self.refresh()
      return ok

   def _follow(self) -> None:
      """!Switches to the map the host's map panel shows (when following).
      @return None
      """
      sel = getattr(self.host, "selected_map", None)
      name = sel() if callable(sel) and self.follow.isChecked() else None
      if name is not None and self.map_name != name:
         self.map_name = name
         self.chosen = None
         self.refresh()

   def document_replaced(self) -> None:
      """!Another world was opened.
      @return None
      """
      self.map_name = None
      self.chosen = None
      maptools.SELECTION.clear()
      self.refresh()

   def showEvent(self, event: QtGui.QShowEvent) -> None:
      """!Follows the Map tab's map when shown.
      @param event  QShowEvent
      @return None
      """
      super().showEvent(event)
      self._follow()
      self.refresh()

   # -- refresh -------------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the map's sets and the chosen one.
      @return None
      """
      p = self.project()
      set_enabled(self, p is not None)
      if p is None:
         return
      self._filling = True
      try:
         if self.map_name not in p.map_names():
            self.map_name = p.map_names()[0] if p.map_names() else None
         self.map_box.clear()
         self.map_box.addItems(p.map_names())
         if self.map_name is not None:
            self.map_box.setCurrentText(self.map_name)
         doc = self.map_doc()
         names = override_sets.set_names(doc) if doc is not None else []
         if self.chosen not in names:
            self.chosen = names[0] if names else None
         self.list.clear()
         for s in override_sets.sets(doc) if doc is not None else []:
            kind, which, value = override_sets.persistence(s)
            held = "" if value is None else f"={value}"
            lasts = "" if kind == override_sets.PERSIST_NONE else f" ({which}{held})"
            name, count = s.get("name"), len(s.get("cells", []))
            self.list.addItem(f"{name}: {count} cell(s){lasts}")
         if self.chosen in names:
            self.list.setCurrentRow(names.index(self.chosen))
         self._fill_form(p, doc)
      finally:
         self._filling = False
      self._paint_choice()
      self.update_preview()

   def _fill_form(self, p: Project, doc: Document | None) -> None:
      """!The chosen set's persistence, the paint choices and its cells.
      @param p    Project
      @param doc  the map's Document, or None
      @return None
      """
      layers = len(doc.data.get("layers", [])) if doc is not None else 0
      self.layer.setRange(0, max(0, layers - 1))
      chosen_mt = self.metatile.currentText()
      self.metatile.clear()
      self.metatile.addItem(NOTHING)
      if doc is not None:
         try:
            self.metatile.addItems(p.dictionary(self.map_name))
         except ENGINE_ERRORS:
            pass
      if chosen_mt:
         self.metatile.setCurrentText(chosen_mt)
      s = None
      if doc is not None and self.chosen is not None:
         s = override_sets.find(doc, self.chosen)
      for w in (self.persist, self.which, self.value, self.cells):
         set_enabled(w, s is not None)   # the cell table goes read-only and keeps its scroll bars
      self.cells.setRowCount(0)
      if s is None:
         return
      kind, which, value = override_sets.persistence(s)
      self.persist.setCurrentIndex(override_sets.persist_kinds().index(kind))
      try:
         names = events.names(p)
      except ENGINE_ERRORS as e:
         names = {"flags": [], "vars": {}, "error": str(e)}
      self.which.clear()
      self.which.addItems(names["flags"] if kind == override_sets.PERSIST_FLAG else list(names["vars"]))
      self.which.setCurrentText(which or "")
      self.which.setEnabled(kind != override_sets.PERSIST_NONE)
      self.value.setEnabled(kind == override_sets.PERSIST_VAR)
      self.value.setValue(value if isinstance(value, int) else override_sets.DEFAULT_VAR_VALUE)
      cells = s.get("cells", [])
      self.cells.setRowCount(len(cells))
      for i, c in enumerate(cells):
         at = c.get("cell", ["?", "?"])
         shows = f"entries {c.get(ENTRIES)}" if ENTRIES in c else (c.get("metatile") or NOTHING)
         for col, text in enumerate((f"{at[0]},{at[1]}", str(c.get("layer", 0)), shows)):
            self.cells.setItem(i, col, QtWidgets.QTableWidgetItem(text))

   def _map_chosen(self, name: str) -> None:
      """!Another map in the chooser.
      @param name  map name
      @return None
      """
      if self._filling or not name or self.map_name == name:
         return
      self.follow.setChecked(False)
      self.map_name = name
      self.chosen = None
      self.refresh()

   def _set_picked(self) -> None:
      """!Another set in the list.
      @return None
      """
      if self._filling is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      doc = self.map_doc()
      names = override_sets.set_names(doc) if doc is not None else []
      row = self.list.currentRow()
      self.chosen = names[row] if 0 <= row < len(names) else None
      self.refresh()

   def _paint_choice(self) -> None:
      """!Tells the map tool what it paints.
      @return None
      """
      mt = self.metatile.currentText()
      maptools.choose(self.map_name, self.chosen, self.layer.value(), None if mt in ("", NOTHING) else mt)

   def update_preview(self) -> None:
      """!Draws the chosen set's cells applied or cleared, and the map's problems with its sets.
      @return None
      """
      p = self.project()
      img = None
      problems = []
      if p is not None and self.chosen is not None and self.map_doc() is not None:
         try:
            img = override_sets.render(p, self.map_name, self.chosen, self.applied.isChecked(), PREVIEW_MARGIN)
            problems = [d.message for d in override_sets.diagnostics(p, self.map_name)]
         except ENGINE_ERRORS as e:
            problems = [str(e)]
      self.preview.set_image(to_qimage(*img) if img is not None else None)
      self.problems.setText("\n".join(problems))

   # -- edits ----------------------------------------------------------------------------------

   def _first_cell(self) -> tuple[list[int], str | None]:
      """!Where a new set starts: the map's first painted cell, showing the paint metatile (or its own).
      @return ([x, y], metatile or None)
      """
      doc = self.map_doc()
      chunks = doc.data.get("chunks", []) if doc is not None else []
      # a chunk's "at" is in chunks; its first cell is CHUNK metatiles per chunk from the map's origin
      at = [chunks[0]["at"][0] * maps.CHUNK, chunks[0]["at"][1] * maps.CHUNK] if chunks else [0, 0]
      mt = self.metatile.currentText()
      return at, None if mt in ("", NOTHING) else mt

   def add_set(self, name: str | None = None) -> bool:
      """!Adds a set (asks its name when none is given).
      @param name  the name, or None to ask
      @return True when added
      """
      p = self.project()
      if p is None or self.map_doc() is None:
         return self.explain("Add override set", "map")
      if name is None:
         text, ok = QtWidgets.QInputDialog.getText(self, "Add override set", "Name (unique in the world):")
         if not ok or not text.strip():
            return False
         name = text.strip()
      at, mt = self._first_cell()
      if self._edit("Add override set", lambda: override_sets.add_set(p, self.map_name, name, at,
                                                                     self.layer.value(), mt)):
         self.chosen = name
         self.refresh()
         return True
      return False

   def rename_set(self, new: str | None = None) -> bool:
      """!Renames the chosen set (the scripts naming it follow, saved at once).
      @param new  the new name, or None to ask
      @return True when renamed
      """
      p = self.project()
      if p is None or self.chosen is None:
         return self.explain("Rename override set", "override set")
      if new is None:
         text, ok = QtWidgets.QInputDialog.getText(self, "Rename override set", "New name:", text=self.chosen)
         if not ok or not text.strip():
            return False
         new = text.strip()
      old = self.chosen
      out: dict[str, list[str]] = {}

      def run() -> None:
         out["files"] = override_sets.rename_set(p, self.map_name, old, new)
      if self._edit("Rename override set", run):
         self.chosen = new
         files = out.get("files", [])
         self.host.show_status(f"Override set {old} is {new}" + (f"; {len(files)} script file(s) rewritten"
                                                                 if files else ""))
         self.refresh()
         return True
      return False

   def remove_set(self) -> bool:
      """!Removes the chosen set (refused while scripts name it).
      @return True when removed
      """
      p = self.project()
      name = self.chosen
      if p is None or name is None:
         return self.explain("Remove override set", "override set")
      if self._edit("Remove override set", lambda: override_sets.remove_set(p, self.map_name, name)):
         self.chosen = None
         self.refresh()
         return True
      return False

   def _persist_changed(self) -> None:
      """!The persistence form changed.
      @return None
      """
      doc = self.map_doc()
      if self._filling or doc is None or self.chosen is None:
         return
      kind = override_sets.persist_kinds()[self.persist.currentIndex()]
      which = self.which.currentText().strip() or None
      value = self.value.value() if kind == override_sets.PERSIST_VAR else None
      s = override_sets.find(doc, self.chosen)
      if override_sets.persistence(s) == (kind, which if kind != override_sets.PERSIST_NONE else None, value):
         return
      if kind != override_sets.PERSIST_NONE and which is None:
         self.refresh()   # shows the names to choose from
         return
      name = self.chosen
      self._edit("Override set persistence", lambda: override_sets.set_persist(doc, name, kind, which, value))
      self.refresh()

   def _selected_cells(self) -> list[tuple[list[int], int]]:
      """!The chosen rows of the cell table.
      @return [([x, y], layer)]
      """
      doc = self.map_doc()
      cells = override_sets.cells(doc, self.chosen) if doc is not None and self.chosen else []
      rows = sorted({i.row() for i in self.cells.selectedIndexes()})
      return [(cells[r]["cell"], cells[r].get("layer", 0)) for r in rows if r < len(cells)]

   def erase_selected(self) -> bool:
      """!Takes the chosen cells out of the set.
      @return True when changed
      """
      doc, name, picked = self.map_doc(), self.chosen, self._selected_cells()
      if doc is None or not picked:
         return self.explain("Take out", "cell")

      def run() -> None:
         for at, layer in picked:
            override_sets.erase(doc, name, [at], layer)
      ok = self._edit("Erase override cells", run)
      self.refresh()
      return ok

   def repaint_selected(self) -> bool:
      """!The chosen cells show the paint metatile on the paint layer.
      @return True when changed
      """
      doc, name, picked = self.map_doc(), self.chosen, self._selected_cells()
      if doc is None or not picked:
         return self.explain("Repaint", "cell")
      mt = self.metatile.currentText()
      layer = self.layer.value()

      def run() -> None:
         for at, old_layer in picked:
            if old_layer != layer:
               override_sets.paint(doc, name, [at], layer, None if mt == NOTHING else mt)
               override_sets.erase(doc, name, [at], old_layer)
            else:
               override_sets.paint(doc, name, [at], layer, None if mt == NOTHING else mt)
      ok = self._edit("Paint override cells", run)
      self.refresh()
      return ok
