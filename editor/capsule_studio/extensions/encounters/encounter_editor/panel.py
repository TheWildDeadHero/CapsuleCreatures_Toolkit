"""!The Encounters panel: the world's encounter settings, each map's tables
and the shared tables, with each entry's share under chosen conditions.

Shown on its own as the encounter editor app, and as a tab of the Studio's
World page (it follows the map chosen in the Map tab there). Every change goes through
the host's run_edit() on the Document it changes, so Undo / Redo, the
unsaved mark and Save work as in the other panels. Everything here is also
a `capsule-studio encounters` command (commands.py).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from capsule_studio.core import encounters as enc
from capsule_studio.core import engine, paths
from capsule_studio.core.document import DocumentError
from capsule_studio.ui.panel import EditorPanel
from capsule_studio.ui.widgets import button

if TYPE_CHECKING:
   from PySide6 import QtGui

   from capsule_studio.core.document import Document
   from capsule_studio.core.world import Project
   from capsule_studio.ui.world_shell import WorldWindow

## A JSON object (a method, a table or an entry).
JsonDict = dict[str, Any]
## A rate as stored: "1/10", "12.5%", [n, m] or a number (as core.encounters keeps it).
Rate = str | int | float | list[int]
## Levels as stored: a level, or [lo, hi].
Levels = int | list[int]
## The chosen table: (Document, index, table object), or (None, None, None).
ChosenTable = tuple["Document", int, JsonDict] | tuple[None, None, None]
## The chosen entry: (Document, table index, entry index), or (None, None, None).
ChosenEntry = tuple["Document", int, int] | tuple[None, None, None]

## File list key of the shared tables.
SHARED = "\0shared"
## Entry table columns.
ENTRY_COLUMNS = ["Species", "Levels", "Weight", "Requires", "Excludes", "Modifiers", "Share"]
## Table list columns.
TABLE_COLUMNS = ["Slot", "Method", "Label", "Rate", "Entries", "Cells"]

## Entry table column of the species.
SPECIES_COLUMN = ENTRY_COLUMNS.index("Species")
## Entry table column of the levels.
LEVELS_COLUMN = ENTRY_COLUMNS.index("Levels")
## Entry table column of the weight.
WEIGHT_COLUMN = ENTRY_COLUMNS.index("Weight")
## Entry table column of the required conditions.
REQUIRES_COLUMN = ENTRY_COLUMNS.index("Requires")
## Entry table column of the excluded conditions.
EXCLUDES_COLUMN = ENTRY_COLUMNS.index("Excludes")
## Entry table column of the modifiers.
MODIFIERS_COLUMN = ENTRY_COLUMNS.index("Modifiers")
## Entry table column of the share (computed, never edited).
SHARE_COLUMN = ENTRY_COLUMNS.index("Share")
## Table list column of the slot (hidden for the shared file).
SLOT_COLUMN = TABLE_COLUMNS.index("Slot")
## Table list column of the method (hidden for the shared file).
METHOD_COLUMN = TABLE_COLUMNS.index("Method")
## Table list column of the encounter cell count (hidden for the shared file).
CELLS_COLUMN = TABLE_COLUMNS.index("Cells")

## Numbers in a level range [lo, hi].
LEVEL_BOUNDS = 2
## Numbers in an odds rate [n, m].
RATE_PARTS = 2
## Shares are shown as percentages.
PERCENT = 100
## Most problems listed under the entries.
MAX_PROBLEMS_SHOWN = 8
## Level of a new entry.
NEW_ENTRY_LEVEL = 5
## Weight of a new entry.
NEW_ENTRY_WEIGHT = 10
## Tallest the method list grows (pixels).
METHOD_LIST_HEIGHT = 120
## Tallest the condition list grows (pixels).
CONDITION_LIST_HEIGHT = 100
## Stretch of the table list in the middle column.
TABLE_LIST_STRETCH = 2
## Stretch of the left column (files and world settings).
LEFT_STRETCH = 2
## Stretch of the middle column (tables).
MIDDLE_STRETCH = 4
## Stretch of the right column (entries).
RIGHT_STRETCH = 5


def _levels_text(levels: Levels | None) -> str:
   """!Levels for display.
   @param levels  int or [lo, hi]
   @return "5" or "3-5"
   """
   if isinstance(levels, list) and len(levels) == LEVEL_BOUNDS:
      return f"{levels[0]}-{levels[1]}"
   return str(levels)


def _rate_text(rate: Rate | None) -> str:
   """!A stored rate as the Rate field shows it.
   @param rate  rate as stored, or None
   @return "1/10", "12.5%", "1", or ""
   """
   if rate is None:
      return ""
   if isinstance(rate, list) and len(rate) == RATE_PARTS:
      return f"{rate[0]}/{rate[1]}"
   return str(rate)


## Errors meaning the engine (its encounter compiler) is missing or too old.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError)


def _parse_levels(text: str) -> Levels:
   """!"3-5" or "5" to levels.
   @param text  text
   @return int or [lo, hi]
   """
   t = text.replace(" ", "")
   try:
      if "-" in t:
         a, b = t.split("-", 1)
         return [int(a), int(b)]
      return int(t)
   except ValueError:
      raise DocumentError(f"levels look like 5 or 3-5, got {text!r}") from None


def _names(text: str) -> list[str]:
   """!"a, b" to ["a", "b"].
   @param text  text
   @return list
   """
   return [t.strip() for t in text.split(",") if t.strip()]


class EncounterPanel(EditorPanel):
   """!Edits encounter tables (core.encounters).

   @var _filling
   True while widgets are being filled.
   """

   ## See EditorPanel.panel_id.
   panel_id = "encounters"
   ## See EditorPanel.title.
   title = "Encounters"

   def __init__(self, host: WorldWindow, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The file shown: a map name, SHARED, or None.
      self.key = None
      ## The Document the last edit changed (Undo goes there first).
      self._last_doc = None
      ## True while widgets are being filled.
      self._filling = False
      ## True while a table property edit runs (its warning box takes focus, which would edit again).
      self._editing = False

      # -- left: files and world settings
      ## Maps and the shared tables.
      self.files = QtWidgets.QListWidget()
      self.files.currentItemChanged.connect(lambda item, _old: self._file_chosen(item))
      ## Follow the map chosen in the Map tab.
      self.follow = QtWidgets.QCheckBox("Follow the Map tab")
      self.follow.setChecked(True)
      self.follow.setToolTip("Show the encounters of the map the Map tab is editing")
      self.follow.toggled.connect(lambda on: on and self._follow())
      self.follow.setVisible(getattr(host, "shows_map", lambda: True)())   # no Map tab: nothing to follow
      ## Battle data line.
      self.battle = QtWidgets.QLabel()
      self.battle.setWordWrap(True)
      ## Methods.
      self.method_list = QtWidgets.QListWidget()
      self.method_list.setMaximumHeight(METHOD_LIST_HEIGHT)
      ## Conditions.
      self.condition_list = QtWidgets.QListWidget()
      self.condition_list.setMaximumHeight(CONDITION_LIST_HEIGHT)
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Encounter files"))
      left.addWidget(self.files, 1)
      left.addWidget(self.follow)
      world = QtWidgets.QGroupBox("World")
      wl = QtWidgets.QVBoxLayout(world)
      wl.addWidget(self.battle)
      wl.addWidget(button("Battle data...", lambda: self.choose_battle(),
                          "The battle manifest (capsule.battle/1) whose species encounters name"))
      wl.addWidget(QtWidgets.QLabel("Methods (how creatures are met)"))
      wl.addWidget(self.method_list)
      row = QtWidgets.QHBoxLayout()
      for text, fn, tip in (("Add", lambda: self.add_method(), "A new method: steps on encounter cells, or game "
                                                               "code (a lure, a search, ...)"),
                            ("Edit", lambda: self.edit_method(), "Trigger and vehicle classes"),
                            ("Rename", lambda: self.rename("method", self.method_list), "Renames it everywhere"),
                            ("Remove", lambda: self.remove("method", self.method_list), "Only when no table uses it")):
         row.addWidget(button(text, fn, tip))
      wl.addLayout(row)
      wl.addWidget(QtWidgets.QLabel("Conditions (bits game code sets)"))
      wl.addWidget(self.condition_list)
      row = QtWidgets.QHBoxLayout()
      for text, fn in (("Add", lambda: self.add_condition()),
                       ("Rename", lambda: self.rename("condition", self.condition_list)),
                       ("Remove", lambda: self.remove("condition", self.condition_list))):
         row.addWidget(button(text, fn))
      wl.addLayout(row)
      left.addWidget(world)

      # -- middle: tables
      ## The file's tables.
      self.table_list = QtWidgets.QTableWidget(0, len(TABLE_COLUMNS))
      self.table_list.setHorizontalHeaderLabels(TABLE_COLUMNS)
      self.table_list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table_list.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.table_list.verticalHeader().setVisible(False)
      self.table_list.horizontalHeader().setStretchLastSection(True)
      self.table_list.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
      self.table_list.itemSelectionChanged.connect(lambda: self._table_chosen())
      ## Table properties.
      self.slot = QtWidgets.QSpinBox()
      self.slot.setRange(0, enc.MAX_SLOTS - 1)
      self.slot.setToolTip("Encounter cells of this slot use this table (paint them with the Encounters brush)")
      self.slot.editingFinished.connect(lambda: self._table_edited())
      ## The table's method.
      self.method = QtWidgets.QComboBox()
      self.method.activated.connect(lambda *a: self._table_edited())
      ## The table's label (editor only).
      self.label_edit = QtWidgets.QLineEdit()
      self.label_edit.setPlaceholderText("label (editor only)")
      self.label_edit.editingFinished.connect(lambda: self._table_edited())
      ## The table's rate as typed.
      self.rate = QtWidgets.QLineEdit()
      self.rate.setToolTip('Odds that a step (or a script roll) starts an encounter: "1/10", "12.5%", 1 = always. '
                           "Empty on a shared reference: the shared table's")
      self.rate.editingFinished.connect(lambda: self._table_edited())
      ## The rate as odds and percent.
      self.rate_info = QtWidgets.QLabel()
      ## Shared table name (for the shared file) / the shared table a map table uses.
      self.source = QtWidgets.QLabel()
      form = QtWidgets.QFormLayout()
      form.addRow("Slot", self.slot)
      form.addRow("Method", self.method)
      form.addRow("Label", self.label_edit)
      rate_row = QtWidgets.QHBoxLayout()
      rate_row.addWidget(self.rate, 1)
      rate_row.addWidget(self.rate_info)
      form.addRow("Rate", rate_row)
      form.addRow("Entries from", self.source)
      ## Table actions (map files).
      self.map_buttons = QtWidgets.QWidget()
      mb = QtWidgets.QHBoxLayout(self.map_buttons)
      mb.setContentsMargins(0, 0, 0, 0)
      mb.addWidget(button("Add table", lambda: self.add_table(), "A table for a slot and method"))
      mb.addWidget(button("Remove", lambda: self.remove_table()))
      mb.addWidget(button("Use shared...", lambda: self.link_shared(), "Roll a shared table's entries instead"))
      mb.addWidget(button("Copy shared here", lambda: self.unlink_shared(),
                          "Copy the shared table's entries into this table to edit them here"))
      show = button("Show on map", lambda: self.show_on_map(), "Open this map in the Map tab")
      show.setVisible(getattr(host, "shows_map", lambda: True)())   # no Map tab in the encounter editor
      mb.addWidget(show)
      ## Table actions (the shared file).
      self.shared_buttons = QtWidgets.QWidget()
      sb = QtWidgets.QHBoxLayout(self.shared_buttons)
      sb.setContentsMargins(0, 0, 0, 0)
      sb.addWidget(button("Add shared table", lambda: self.add_shared()))
      sb.addWidget(button("Rename", lambda: self.rename_shared(), "Renames it in every map using it"))
      sb.addWidget(button("Remove", lambda: self.remove_shared(), "Only when no map uses it"))
      middle = QtWidgets.QVBoxLayout()
      ## Title over the tables.
      self.heading = QtWidgets.QLabel()
      middle.addWidget(self.heading)
      middle.addWidget(self.table_list, TABLE_LIST_STRETCH)
      middle.addWidget(self.map_buttons)
      middle.addWidget(self.shared_buttons)
      middle.addLayout(form)

      # -- entries and preview
      ## The table's entries.
      self.entry_list = QtWidgets.QTableWidget(0, len(ENTRY_COLUMNS))
      self.entry_list.setHorizontalHeaderLabels(ENTRY_COLUMNS)
      self.entry_list.verticalHeader().setVisible(False)
      self.entry_list.horizontalHeader().setStretchLastSection(True)
      self.entry_list.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
      self.entry_list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.entry_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.entry_list.itemChanged.connect(lambda item: self._entry_edited(item))
      self.entry_list.setToolTip("Levels: 5 or 3-5. Requires / Excludes: condition names (a, b). Modifiers: "
                                 "'rain x0, night x2'. Share: how often the entry comes up under the preview "
                                 "conditions below")
      entry_buttons = QtWidgets.QHBoxLayout()
      entry_buttons.addWidget(button("Add entry", lambda: self.add_entry()))
      entry_buttons.addWidget(button("Remove", lambda: self.remove_entry()))
      entry_buttons.addWidget(button("Up", lambda: self.move_entry(-1)))
      entry_buttons.addWidget(button("Down", lambda: self.move_entry(1)))
      entry_buttons.addStretch(1)
      ## Preview conditions.
      self.preview_box = QtWidgets.QHBoxLayout()
      ## Preview checkboxes by condition name.
      self.preview = {}
      ## Problems (encounters.diagnostics()).
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(QtWidgets.QLabel("Entries"))
      right.addWidget(self.entry_list, 1)
      right.addLayout(entry_buttons)
      prow = QtWidgets.QHBoxLayout()
      prow.addWidget(QtWidgets.QLabel("Preview with:"))
      prow.addLayout(self.preview_box)
      prow.addStretch(1)
      right.addLayout(prow)
      right.addWidget(self.problems)

      layout = QtWidgets.QHBoxLayout(self)
      for part, stretch in ((left, LEFT_STRETCH), (middle, MIDDLE_STRETCH), (right, RIGHT_STRETCH)):
         box = QtWidgets.QWidget()
         box.setLayout(part)
         layout.addWidget(box, stretch)

   # -- documents ---------------------------------------------------------------------------

   def project(self) -> Project | None:
      """!The host's project.
      @return Project, or None
      """
      return self.host_project()

   def file_doc(self, create: bool = False) -> Document | None:
      """!The encounter Document shown.
      @param create  create the file (a map's, or the shared one) when it has none
      @return Document, or None
      """
      p = self.project()
      if p is None or self.key is None:
         return None
      if self.key == SHARED:
         return enc.shared_doc(p, create)
      if self.key not in p.map_names():
         return None
      return enc.map_doc(p, self.key, create)

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the document of the last edit from this tab, else the file shown.
      @return Document, or None
      """
      p = self.project()
      if p is None:
         return None
      last = self._last_doc
      if last is not None and last in p.documents() and (last.undo_label() or last.redo_label()):
         return last
      return self.file_doc()

   def _edit(self, label: str, fn: Callable[[], object], doc: Document) -> bool:
      """!Runs an edit through the host.
      @param label  undo label
      @param fn     callable
      @param doc    the Document it changes
      @return True when it went through
      """
      self._last_doc = doc
      return self.host.run_edit(label, fn, doc)

   def _project_step(self, fn: Callable[[Project], object]) -> bool:
      """!Runs a change that makes its own undo steps (renames, new files), reporting errors.
      @param fn  callable(project)
      @return True when it went through
      """
      p = self.project()
      try:
         fn(p)
      except DocumentError as e:
         QtWidgets.QMessageBox.warning(self, "Encounters", str(e))
         return False
      self.host.changed()
      return True

   def document_replaced(self) -> None:
      """!Another world was opened.
      @return None
      """
      self.key = None
      self._last_doc = None
      self.refresh()

   def showEvent(self, event: QtGui.QShowEvent) -> None:
      """!Follows the Map tab's map when shown.
      @param event  QShowEvent
      @return None
      """
      super().showEvent(event)
      self._follow()

   def _follow(self) -> None:
      """!Switches to the map the host's map panel shows (when following).
      @return None
      """
      sel = getattr(self.host, "selected_map", None)
      name = sel() if callable(sel) and self.follow.isChecked() else None
      if name is not None and name != self.key:
         self.key = name
         self.refresh()

   # -- refresh -------------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the world, the files and the shown table.
      @return None
      """
      p = self.project()
      self._filling = True
      try:
         self._fill_world(p)
         self._fill_files(p)
         self._fill_tables(p)
      finally:
         self._filling = False
      self._fill_entries()
      self._fill_problems()

   def _fill_world(self, p: Project | None) -> None:
      """!World settings.
      @param p  Project or None
      @return None
      """
      self.method_list.clear()
      self.condition_list.clear()
      if p is None:
         self.battle.setText("No world open")
         return
      try:
         names, level_max = enc.species(p)
         rel = p.world.data.get("battle")
         self.battle.setText(f"Battle data: {rel} ({len(names)} species, levels up to {level_max})" if rel else
                             "Battle data: none yet (species can't be checked)")
      except DocumentError as e:
         self.battle.setText(f"Battle data: {e}")
      except ENGINE_ERRORS as e:
         self.battle.setText(f"Battle data: cannot be checked without the engine's encounter compiler ({e})")
      for m in enc.methods(p):
         vs = m.get("vehicles")
         item = QtWidgets.QListWidgetItem(f"{m.get('name')}  ({m.get('trigger', 'step')}"
                                          + (f": {', '.join(vs)})" if vs else ")"))
         item.setData(QtCore.Qt.ItemDataRole.UserRole, m.get("name"))
         self.method_list.addItem(item)
      for c in enc.conditions(p):
         item = QtWidgets.QListWidgetItem(c)
         item.setData(QtCore.Qt.ItemDataRole.UserRole, c)
         self.condition_list.addItem(item)
      # rebuild the preview check boxes for the world's conditions, keeping the checked ones
      keep = {n for n, cb in self.preview.items() if cb.isChecked()}
      for cb in self.preview.values():
         self.preview_box.removeWidget(cb)
         cb.deleteLater()
      self.preview = {}
      for c in enc.conditions(p):
         cb = QtWidgets.QCheckBox(c)
         cb.setChecked(c in keep)
         cb.toggled.connect(lambda *a: self._fill_entries())
         self.preview_box.addWidget(cb)
         self.preview[c] = cb
      names = enc.method_names(p)
      if [self.method.itemText(i) for i in range(self.method.count())] != names:
         self.method.clear()
         self.method.addItems(names)

   def _fill_files(self, p: Project | None) -> None:
      """!The file list.
      @param p  Project or None
      @return None
      """
      self.files.clear()
      if p is None:
         return
      keys = [SHARED] + p.map_names()
      if self.key not in keys:
         self.key = p.map_names()[0] if p.map_names() else SHARED
      for k in keys:
         if k == SHARED:
            s = enc.shared_doc(p)
            text = f"Shared tables ({len(enc.tables(s))})" if s else "Shared tables (none yet)"
         else:
            d = enc.map_doc(p, k)
            text = f"{k}  ({len(enc.tables(d))} tables)" if d else f"{k}  (no encounters)"
         item = QtWidgets.QListWidgetItem(text)
         item.setData(QtCore.Qt.ItemDataRole.UserRole, k)
         self.files.addItem(item)
         if k == self.key:
            self.files.setCurrentItem(item)

   def _fill_tables(self, p: Project | None) -> None:
      """!The table list and properties.
      @param p  Project or None
      @return None
      """
      doc = self.file_doc()
      shared = self.key == SHARED
      self.map_buttons.setVisible(not shared)
      self.shared_buttons.setVisible(shared)
      self.slot.setEnabled(not shared)
      self.method.setEnabled(not shared)
      self.label_edit.setEnabled(not shared)
      if p is None:
         self.heading.setText("")
      elif shared:
         self.heading.setText(f"Shared tables: {doc.path.name}" if doc else
                              "Shared tables: none yet (Add shared table creates encounters/shared.json)")
      else:
         self.heading.setText(f"Map {self.key}: {doc.path.name}" if doc else
                              f"Map {self.key}: no encounter file yet (Add table creates one)")
      row = self.table_list.currentRow()
      ts = enc.tables(doc) if doc is not None else []
      cells = enc.slot_cells(p.map(self.key).data) if p is not None and not shared and self.key else {}
      self.table_list.setRowCount(len(ts))
      for i, t in enumerate(ts):
         rate, es = enc.resolved(p, t)
         if shared:
            vals = ["", "", t.get("name", ""), enc.format_rate(rate), str(len(es)), ""]
         else:
            src = f" (shared {t['table']})" if "table" in t else ""
            vals = [str(t.get("slot")), str(t.get("method")), enc.label(t), enc.format_rate(rate),
                    f"{len(es)}{src}", str(len(cells.get(t.get("slot"), [])))]
         for c, v in enumerate(vals):
            self.table_list.setItem(i, c, QtWidgets.QTableWidgetItem(v))
      self.table_list.setColumnHidden(SLOT_COLUMN, shared)
      self.table_list.setColumnHidden(METHOD_COLUMN, shared)
      self.table_list.setColumnHidden(CELLS_COLUMN, shared)
      if ts:
         self.table_list.selectRow(min(max(row, 0), len(ts) - 1))   # the same row, clamped to the tables
      self._fill_properties()

   def current_table(self) -> ChosenTable:
      """!The chosen table.
      @return (Document, index, table object), or (None, None, None)
      """
      doc = self.file_doc()
      i = self.table_list.currentRow()
      if doc is None or not 0 <= i < len(enc.tables(doc)):
         return None, None, None
      return doc, i, enc.tables(doc)[i]

   def _fill_properties(self) -> None:
      """!The chosen table's properties.
      @return None
      """
      doc, i, t = self.current_table()
      was = self._filling
      self._filling = True
      try:
         if t is None:
            for w in (self.label_edit, self.rate):
               w.setText("")
            self.rate_info.setText("")
            self.source.setText("")
            return
         self.slot.setValue(t.get("slot", 0) or 0)
         if t.get("method") is not None and self.method.findText(t["method"]) >= 0:
            self.method.setCurrentIndex(self.method.findText(t["method"]))
         self.label_edit.setText(enc.label(t))
         self.rate.setText(_rate_text(t.get("rate")))
         rate, _es = enc.resolved(self.project(), t)
         self.rate_info.setText(enc.format_rate(rate))
         self.source.setText(f"shared table {t['table']}" if "table" in t else
                             (t.get("name", "") + " (shared)" if "name" in t else "this table"))
      finally:
         self._filling = was

   def _fill_entries(self) -> None:
      """!The chosen table's entries with their shares.
      @return None
      """
      p = self.project()
      doc, i, t = self.current_table()
      self._filling = True
      try:
         self.entry_list.setRowCount(0)
         if t is None:
            return
         active = [n for n, cb in self.preview.items() if cb.isChecked()]
         rows = enc.shares(p, t, active)
         linked = "table" in t
         try:
            species, _lm = enc.species(p)
         except (DocumentError,) + ENGINE_ERRORS:
            species = []
         self.entry_list.setRowCount(len(rows))
         for r, (e, _w, share) in enumerate(rows):
            vals = [e.get("species", ""), _levels_text(e.get("levels")), str(e.get("weight", "")),
                    ", ".join(e.get("requires", [])), ", ".join(e.get("excludes", [])),
                    enc.format_modifiers(e.get("modifiers")), f"{share * PERCENT:.1f}%"]
            for c, v in enumerate(vals):
               item = QtWidgets.QTableWidgetItem(v)
               if linked or c == SHARE_COLUMN:
                  item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
               self.entry_list.setItem(r, c, item)
            if species and not linked:
               box = QtWidgets.QComboBox()
               box.addItems(species)
               if e.get("species") not in species:
                  box.addItem(str(e.get("species")))
               box.setCurrentText(str(e.get("species")))
               # defaults bind this row and box (a plain closure would see the last ones)
               box.activated.connect(lambda _i, row=r, b=box: self._species_chosen(row, b.currentText()))
               self.entry_list.setCellWidget(r, SPECIES_COLUMN, box)
      finally:
         self._filling = False

   def _fill_problems(self) -> None:
      """!Diagnostics for the shown map (or the world, for the shared file).
      @return None
      """
      p = self.project()
      if p is None:
         self.problems.setText("")
         return
      try:
         found = enc.diagnostics(p, None if self.key == SHARED else self.key)
      except ENGINE_ERRORS as e:
         self.problems.setText(f"Encounters cannot be checked without the engine: {e}")
         self.problems.setStyleSheet("color: #c03030;")
         return
      key = self.key   # a local alias (Doxygen 1.12 reads `if self.x ...:` as a declaration)
      if key == SHARED:
         found = [d for d in found if d.map is None]
      text = "\n".join(f"{d.level.capitalize()}: {d.message}" + (f" ({d.at[0]}, {d.at[1]})" if d.at else "")
                       for d in found[:MAX_PROBLEMS_SHOWN])
      self.problems.setText(text or "No problems.")
      bad = any(d.level == "error" for d in found)
      self.problems.setStyleSheet("color: #c03030;" if bad else "color: #b07000;" if found else "")

   # -- choosing ---------------------------------------------------------------------------

   def _file_chosen(self, item: QtWidgets.QListWidgetItem | None) -> None:
      """!Another file was picked.
      @param item  QListWidgetItem or None
      @return None
      """
      if self._filling or item is None:
         return
      self.key = item.data(QtCore.Qt.ItemDataRole.UserRole)
      if self.key != SHARED:
         self.follow.blockSignals(True)
         self.follow.setChecked(self.key == getattr(self.host, "selected_map", lambda: None)())
         self.follow.blockSignals(False)
      QtCore.QTimer.singleShot(0, lambda: self.refresh())   # not from inside the list's own signal

   def _table_chosen(self) -> None:
      """!Another table was picked.
      @return None
      """
      if self._filling:
         return
      self._fill_properties()
      self._fill_entries()

   # -- world settings ----------------------------------------------------------------------

   def choose_battle(self) -> None:
      """!Picks the battle manifest (stored relative to the world).
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("Battle data")
         return
      path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Battle data", str(p.base),
                                                      "Battle data (*.json);;All files (*)")
      if not path:
         return
      # Resolved on both sides; another drive (Windows) is refused with a message by run_edit.
      self._edit("Battle data", lambda: enc.set_battle(p.world, paths.relative(path, p.base)), p.world)

   def _ask(self, title: str, text: str, value: str = "") -> str | None:
      """!Asks for a name.
      @param title  dialog title
      @param text   prompt
      @param value  start value
      @return text, or None when cancelled / empty
      """
      t, ok = QtWidgets.QInputDialog.getText(self, title, text, text=value)
      return t.strip() if ok and t.strip() else None

   def add_method(self) -> None:
      """!Adds a method (asks name and trigger).
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("Add method")
         return
      name = self._ask("Add method", "Method name (e.g. walk, swim, lure):")
      if name is None:
         return
      trigger, ok = QtWidgets.QInputDialog.getItem(self, "Add method", "Rolled by:", [
         "step (arriving on an encounter cell)", "script (game code: a lure, a search, ...)"], 0, False)
      if not ok:
         return
      # the trigger is the chooser text's first word
      self._edit("Add method", lambda: enc.add_method(p.world, name, trigger.split(" ")[0]), p.world)

   def edit_method(self) -> None:
      """!Changes the chosen method's trigger and vehicle classes.
      @return None
      """
      p, item = self.project(), self.method_list.currentItem()
      if p is None or item is None:
         self.host.show_status("Pick a method first")
         return
      name = item.data(QtCore.Qt.ItemDataRole.UserRole)
      m = next(x for x in enc.methods(p) if x.get("name") == name)
      dlg = QtWidgets.QDialog(self)
      dlg.setWindowTitle(f"Method {name}")
      form = QtWidgets.QFormLayout(dlg)
      trig = QtWidgets.QComboBox()
      trig.addItems(list(enc.TRIGGERS))
      trig.setCurrentText(m.get("trigger", "step"))
      form.addRow("Rolled by", trig)
      classes = p.world.data.get("vehicle_classes", ["foot"])
      boxes = []
      for c in classes:
         cb = QtWidgets.QCheckBox(c)
         cb.setChecked(c in (m.get("vehicles") or classes))
         boxes.append(cb)
         form.addRow("" if boxes[:-1] else "Vehicle classes", cb)   # the label on the first row only
      bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                      QtWidgets.QDialogButtonBox.StandardButton.Cancel)
      bb.accepted.connect(dlg.accept)
      bb.rejected.connect(dlg.reject)
      form.addRow(bb)
      if not dlg.exec():
         return
      t = trig.currentText()
      chosen = [cb.text() for cb in boxes if cb.isChecked()]
      vehicles = None if t != "step" or len(chosen) == len(classes) else chosen   # None: every class
      self._edit("Method", lambda: enc.set_method(p.world, name, t, vehicles), p.world)

   def add_condition(self) -> None:
      """!Adds a condition name.
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("Add condition")
         return
      name = self._ask("Add condition", "Condition name (e.g. night, rain, swarm):")
      if name is not None:
         self._edit("Add condition", lambda: enc.add_condition(p.world, name), p.world)

   def rename(self, kind: str, lst: QtWidgets.QListWidget) -> None:
      """!Renames the chosen method or condition everywhere.
      @param kind  "method" or "condition"
      @param lst   its QListWidget
      @return None
      """
      item = lst.currentItem()
      if item is None or self.project() is None:
         self.host.show_status(f"Pick a {kind} first")
         return
      old = item.data(QtCore.Qt.ItemDataRole.UserRole)
      new = self._ask(f"Rename {kind}", f"New name for {old}:", old)
      if new is not None and new != old:
         self._project_step(lambda p: enc.rename(p, kind, old, new))

   def remove(self, kind: str, lst: QtWidgets.QListWidget) -> None:
      """!Removes the chosen method or condition (refused while used).
      @param kind  "method" or "condition"
      @param lst   its QListWidget
      @return None
      """
      item = lst.currentItem()
      if item is None or self.project() is None:
         self.host.show_status(f"Pick a {kind} first")
         return
      name = item.data(QtCore.Qt.ItemDataRole.UserRole)
      self._project_step(lambda p: enc.remove(p, kind, name))

   # -- tables ----------------------------------------------------------------------------------

   def _table_edited(self) -> None:
      """!Slot, method, label or rate of the chosen table changed (a refused change puts the fields back).
      @return None
      """
      if self._filling is True or self._editing is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      doc, i, t = self.current_table()
      if t is None:
         return
      text = self.rate.text().strip()
      self._editing = True
      try:
         if "name" in t:   # a shared table: only its rate
            ok = True
            if text and text != _rate_text(t.get("rate")):
               ok = self._edit("Rate", lambda: enc.table(doc, i).__setitem__("rate", enc.check_rate(text)), doc)
         else:
            rate = False   # False keeps the rate, None drops the table's own
            if text != _rate_text(t.get("rate")):
               rate = None if not text else text
            slot, method, label = self.slot.value(), self.method.currentText(), self.label_edit.text().strip()
            ok = True
            if (slot, method, label, rate) != (t.get("slot"), t.get("method"), enc.label(t), False):
               ok = self._edit("Table", lambda: enc.set_table(doc, i, slot, method, rate, label), doc)
      finally:
         self._editing = False
      if not ok:
         QtCore.QTimer.singleShot(0, lambda: self._fill_properties())

   def add_table(self) -> None:
      """!Adds a table to the shown map (creating its file), on the first free slot for the chosen method.
      @return None
      """
      p = self.project()
      if p is None or self.key in (None, SHARED):
         self.explain("Add table", "map")   # a map's tables (shared tables: Add shared table)
         return
      method = self.method.currentText() or enc.method_names(p)[0]
      doc0 = enc.map_doc(p, self.key)
      used = {t.get("slot") for t in enc.tables(doc0) if t.get("method") == method} if doc0 else set()
      cells = enc.slot_cells(p.map(self.key).data)
      # slots with encounter cells first, then every slot without a table for the method
      free = [s for s in sorted(cells) if s not in used] + [s for s in range(enc.MAX_SLOTS) if s not in used]
      if not free:
         self.host.show_status(f"Every slot has a {method} table")
         return
      doc = enc.map_doc(p, self.key, create=True)
      self._edit("Add table", lambda: enc.add_table(doc, free[0], method), doc)
      self.host.changed()
      QtCore.QTimer.singleShot(0, lambda: self.table_list.selectRow(self.table_list.rowCount() - 1))

   def remove_table(self) -> None:
      """!Removes the chosen table.
      @return None
      """
      doc, i, t = self.current_table()
      if t is None:
         self.explain("Remove table", "table")
      else:
         self._edit("Remove table", lambda: enc.remove_table(doc, i), doc)

   def link_shared(self) -> None:
      """!Makes the chosen table roll a shared table (asks which).
      @return None
      """
      p = self.project()
      doc, i, t = self.current_table()
      s = enc.shared_doc(p) if p else None
      names = [x.get("name") for x in enc.tables(s)] if s else []
      if t is None or not names:
         self.host.show_status("Pick a table, and add shared tables first (Shared tables in the list)")
         return
      name, ok = QtWidgets.QInputDialog.getItem(self, "Use shared table", "Shared table:", names, 0, False)
      if ok:
         if t.get("entries"):
            b = QtWidgets.QMessageBox.question(self, "Use shared table",
                                               "This table's own entries are replaced (Undo brings them back).")
            if b != QtWidgets.QMessageBox.StandardButton.Yes:
               return
         self._edit("Use shared table", lambda: enc.link_shared(doc, i, name), doc)

   def unlink_shared(self) -> None:
      """!Copies the shared table the chosen table uses into it.
      @return None
      """
      p = self.project()
      doc, i, t = self.current_table()
      if t is None or "table" not in t:
         self.host.show_status("Pick a table that uses a shared table")
         return
      self._edit("Copy shared table", lambda: enc.unlink_shared(p, doc, i), doc)

   def add_shared(self) -> None:
      """!Adds a shared table (creating the shared file).
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("Add shared table")
         return
      name = self._ask("Add shared table", "Name (maps refer to it by name):")
      if name is None:
         return
      doc = enc.shared_doc(p, create=True)
      self._edit("Add shared table", lambda: enc.add_shared(doc, name), doc)
      self.host.changed()

   def rename_shared(self) -> None:
      """!Renames the chosen shared table in every map.
      @return None
      """
      _doc, _i, t = self.current_table()
      if t is None or "name" not in t:
         self.explain("Rename shared table", "shared table")
         return
      new = self._ask("Rename shared table", f"New name for {t['name']}:", t["name"])
      if new is not None and new != t["name"]:
         old = t["name"]
         self._project_step(lambda p: enc.rename(p, "shared", old, new))

   def remove_shared(self) -> None:
      """!Removes the chosen shared table (refused while used).
      @return None
      """
      _doc, _i, t = self.current_table()
      if t is None or "name" not in t:
         self.explain("Remove shared table", "shared table")
      else:
         name = t["name"]
         self._project_step(lambda p: enc.remove(p, "shared", name))

   def show_on_map(self) -> None:
      """!Opens the shown map in the Map tab.
      @return None
      """
      sel = getattr(self.host, "select_map", None)
      if self.key in (None, SHARED):
         self.explain("Show on map", "map")
         return
      if not (callable(sel) and sel(self.key)):
         self.host.show_status("The map editor shows maps (this app edits encounters only)")

   # -- entries ---------------------------------------------------------------------------------

   def _entry_row(self) -> ChosenEntry:
      """!The chosen entry.
      @return (Document, table index, entry index), or (None, None, None)
      """
      doc, i, t = self.current_table()
      r = self.entry_list.currentRow()
      if t is None or "table" in t or not 0 <= r < len(t.get("entries", [])):
         return None, None, None
      return doc, i, r

   def add_entry(self) -> None:
      """!Adds an entry (the first species, level 5).
      @return None
      """
      p = self.project()
      doc, i, t = self.current_table()
      if t is None:
         self.host.show_status("Pick or add a table first")
         return
      if "table" in t:
         self.host.show_status(f"This table rolls the shared table {t['table']}: edit that one (Shared tables), "
                               "or Copy shared here")
         return
      try:
         names, _lm = enc.species(p)
      except DocumentError as e:
         self.host.show_status(str(e))
         names = []
      if not names:
         self.host.show_status("Name the world's battle data first (Battle data...): entries name its species")
         return
      self._edit("Add entry", lambda: enc.add_entry(doc, i, names[0], NEW_ENTRY_LEVEL, NEW_ENTRY_WEIGHT), doc)

   def remove_entry(self) -> None:
      """!Removes the chosen entry.
      @return None
      """
      doc, i, r = self._entry_row()
      if doc is None:
         self.explain("Remove entry", "entry")
      else:
         self._edit("Remove entry", lambda: enc.remove_entry(doc, i, r), doc)

   def move_entry(self, delta: int) -> None:
      """!Moves the chosen entry.
      @param delta  -1 up, 1 down
      @return None
      """
      doc, i, r = self._entry_row()
      if doc is None:
         self.explain("Move entry", "entry")
         return
      if self._edit("Move entry", lambda: enc.move_entry(doc, i, r, delta), doc):
         QtCore.QTimer.singleShot(0, lambda: self.entry_list.selectRow(r + delta))

   def _species_chosen(self, row: int, name: str) -> None:
      """!A species was picked in an entry's chooser.
      @param row   entry index
      @param name  species
      @return None
      """
      doc, i, t = self.current_table()
      if t is not None and row < len(t.get("entries", [])) and t["entries"][row].get("species") != name:
         self._edit("Species", lambda: enc.set_entry(doc, i, row, species_name=name), doc)

   def _entry_edited(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!An entry cell was typed into.
      @param item  QTableWidgetItem
      @return None
      """
      if self._filling is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      doc, i, t = self.current_table()
      r, c = item.row(), item.column()
      if t is None or "table" in t or r >= len(t.get("entries", [])):
         return
      text = item.text().strip()
      fields: dict[str, Any] = {}
      try:
         if c == SPECIES_COLUMN:
            fields["species_name"] = text
         elif c == LEVELS_COLUMN:
            fields["levels"] = _parse_levels(text)
         elif c == WEIGHT_COLUMN:
            fields["weight"] = int(text)
         elif c == REQUIRES_COLUMN:
            fields["requires"] = _names(text)
         elif c == EXCLUDES_COLUMN:
            fields["excludes"] = _names(text)
         elif c == MODIFIERS_COLUMN:
            fields["modifiers"] = enc.parse_modifiers(text)
         else:
            return
      except (DocumentError, ValueError) as e:
         self.host.show_status(str(e))
         QtCore.QTimer.singleShot(0, lambda: self.refresh())
         return
      if not self._edit(ENTRY_COLUMNS[c], lambda: enc.set_entry(doc, i, r, **fields), doc):
         QtCore.QTimer.singleShot(0, lambda: self.refresh())

   def stop(self) -> None:
      """!Nothing runs in the background.
      @return None
      """
      pass
