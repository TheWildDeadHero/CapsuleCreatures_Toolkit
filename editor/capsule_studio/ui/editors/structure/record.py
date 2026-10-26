"""!The Record panel (D-23 §3.2): the creature record's roles, the party size
and move slots, a bit budget per target platform and the live layout hash.

The role table lists the record in order: engine roles are greyed with
their fixed IDs (their width is editable where the engine lets a layout
choose it, up to its maximum; per-stat and move roles take their count from
the stats and the move slots), custom roles show their name, width, count
and default (each editable in place) and their ID 0x80 + their place among
the custom roles. Drag a row (or use Up / Down) to reorder; every change is
one undo step (core.structure.record) and is refused when the engine's
compiler would refuse it.

A custom role's Stored box (engine E13a) unticked makes it computed on
read: its one derived or constant generation entry gives its value
whenever it is read, so it takes no record bits, leaves the hash and the
transfer, and its ID follows every stored custom role's. The box is refused
(with the reason) until the role has exactly one such entry (Progression
page); field scripts read an unstored role as 0, so the page asks first
when they use it.

The budget bars show the record's bytes against each of the game's targets
(its project.json "targets"; "61/100 B GBA"), red when over. The layout
hash and the record size come from the engine's own compile_layout(); a
hash other than the saved file's means saves made with the old layout no
longer load, and the panel says so. The transfer defaults box (transfer.py)
sets what a record transfer gives a stat the sending game lacks; the
preview tabs (record_preview.py) show a record's derived roles and a
record transferred in (the engine's derived_values() / rederive() /
import_rederived()). Everything edits the battle manifest, so Undo / Redo
on this page act on it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import battle
from ....core.document import Document, DocumentError
from ....core.structure import record as model
from ....core.structure import stats as stat_model
from ...widgets import ask, button
from ..battle_common import STRUCTURE, BattlePanel
from .record_preview import DerivedPreviewBox, TransferPreviewBox
from .transfer import TransferDefaultsBox

if TYPE_CHECKING:
   from ...panel import PanelHost

## Role table columns, in order: (role_rows() key or a panel key, header).
ROLE_COLUMNS = [("id", "ID"), ("name", "Role"), ("kind", "Kind"), ("width", "Width"), ("count", "Count"),
                ("count_rule", "Count from"), ("default", "Default"), ("stored", "Stored"), ("bits", "Bits"),
                ("offset", "Bit offset"), ("transfer", "Transfer keys")]
## Role table column of each key.
ROLE_COLUMN = {key: c for c, (key, _header) in enumerate(ROLE_COLUMNS)}
## Columns typed in: the property set_role() changes (the name renames a custom role).
EDIT_KEYS = ("name", "width", "count", "default")
## What a count rule means, as the "Count from" column says it.
COUNT_FROM = {"one": "1", "stat": "stats", "move": "move slots", "chosen": "chosen", "custom": "chosen",
              "retired": "chosen"}
## Text colour of the greyed engine-role cells (fixed ID and name).
ENGINE_COLOR = "#808080"
## Background of an engine role's row.
ENGINE_BACKGROUND = "#f0f0f0"
## Text colour of a budget over its limit (and of the warnings).
OVER_COLOR = "#c03030"
## Colour of a budget bar within its limit.
WITHIN_COLOR = "#7cc47c"
## Colour of a budget bar over its limit.
OVER_BAR_COLOR = "#e06060"
## Width of a budget bar, pixels.
BUDGET_WIDTH = 180
## Stretch of the role table in the panel's layout.
TABLE_STRETCH = 1
## Base of a custom role's default typed in the form (decimal; "0x..." is read as hexadecimal).
DECIMAL = 10
## Prefix of a hexadecimal number typed in the form.
HEX_PREFIX = "0x"
## Base of a hexadecimal number.
HEXADECIMAL = 16
## Width of a new custom role in the form, bits.
NEW_CUSTOM_WIDTH = 8
## What the Bits / Bit offset cells of an unstored role say (E13a: no record bits).
UNSTORED_TEXT = "computed on read"
## Text colour of an unstored role's row.
UNSTORED_COLOR = "#5f6fa0"
## The bottom tabs: (key, title).
BOTTOM_TABS = [("custom", "Custom role"), ("transfer_defaults", "Transfer defaults"),
               ("derived", "Derived preview"), ("transfer", "Transfer preview")]


def platform_text(platform: str) -> str:
   """!A target platform as the budget shows it.
   @param platform  build_settings platform name
   @return e.g. "GBA"
   """
   return platform.upper()


def parse_number(text: str) -> int | None:
   """!A whole number typed in a cell or the form (decimal or 0x hexadecimal).
   @param text  the text
   @return the number, or None for an empty text
   @throws ValueError when it is not a number
   """
   text = text.strip()
   if not text:
      return None
   if text.lower().startswith(HEX_PREFIX):
      return int(text[len(HEX_PREFIX):], HEXADECIMAL)
   return int(text, DECIMAL)


class RoleTable(QtWidgets.QTableWidget):
   """!The role table: rows reorder by dragging (the panel moves the role; the table never moves items itself)."""

   def __init__(self, rows: int, columns: int) -> None:
      """!Creates the table.
      @param rows     initial rows
      @param columns  columns
      """
      super().__init__(rows, columns)
      ## Called with (row dragged, row dropped on) after a drop.
      self.dropped = self._ignore_drop
      self.setDragEnabled(True)
      self.setAcceptDrops(True)
      self.setDropIndicatorShown(True)
      self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
      self.setDragDropOverwriteMode(False)

   def _ignore_drop(self, _source: int, _target: int) -> None:
      """!What a drop does until the panel sets dropped.
      @param _source  row dragged
      @param _target  row dropped on
      @return None
      """

   def drop_row(self, y: int) -> int:
      """!The row a drop at a height lands on.
      @param y  viewport y
      @return the row (the last row below the rows)
      """
      row = self.rowAt(y)
      return self.rowCount() - 1 if row < 0 else row

   def dropEvent(self, event: QtGui.QDropEvent) -> None:
      """!Moves the dragged role to the row it was dropped on (Qt override).
      @param event  QDropEvent
      @return None
      """
      source = self.currentRow()
      target = self.drop_row(int(event.position().y()))
      event.setDropAction(QtCore.Qt.DropAction.IgnoreAction)   # the refresh after the edit rebuilds the rows
      event.accept()
      if source >= 0 and target != source:
         self.dropped(source, target)


class RecordPanel(BattlePanel):
   """!The role table, the custom role form, party size and move slots, the budget bars and the hash.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "record"
   ## See EditorPanel.title.
   title = "Record"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the widgets.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Name of the selected role, or None.
      self.selected = None
      ## The rows shown (role_rows()).
      self._rows = []
      ## Creatures a party holds.
      self.party_size = QtWidgets.QSpinBox()
      self.party_size.valueChanged.connect(lambda v: self.set_party_size(v))
      ## Moves a creature knows.
      self.move_slots = QtWidgets.QSpinBox()
      self.move_slots.valueChanged.connect(lambda v: self.set_move_slots(v))
      ## Budget bars, one per target ("61/100 B GBA").
      self.budget_bars = []
      ## Row holding the budget bars.
      self.budget_row = QtWidgets.QHBoxLayout()
      ## The layout hash and the record size.
      self.hash_label = QtWidgets.QLabel()
      self.hash_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## The warning shown when the hash differs from the saved file's.
      self.hash_warning = QtWidgets.QLabel()
      self.hash_warning.setWordWrap(True)
      self.hash_warning.setStyleSheet(f"color: {OVER_COLOR}; font-weight: bold;")
      ## What the record breaks on a target (bytes, party size), or why the layout does not compile.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)
      self.problems.setStyleSheet(f"color: {OVER_COLOR};")
      ## The roles, one row each.
      self.table = RoleTable(0, len(ROLE_COLUMNS))
      self.table.setHorizontalHeaderLabels([h for _key, h in ROLE_COLUMNS])
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.verticalHeader().setVisible(False)
      self.table.horizontalHeader().setStretchLastSection(True)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      self.table.dropped = lambda src, dst: self._dropped(src, dst)
      ## Engine roles the record does not hold yet.
      self.engine_choice = QtWidgets.QComboBox()
      ## Custom role form: name.
      self.c_name = QtWidgets.QLineEdit()
      self.c_name.setPlaceholderText("lower-case name, e.g. met_level")
      ## Custom role form: bits per element.
      self.c_width = QtWidgets.QSpinBox()
      self.c_width.setValue(NEW_CUSTOM_WIDTH)
      ## Custom role form: elements.
      self.c_count = QtWidgets.QSpinBox()
      ## Custom role form: initial value (decimal or 0x hexadecimal; a 32-bit role's exceeds a spin box).
      self.c_default = QtWidgets.QLineEdit("0")
      ## Custom role form: adds a custom role.
      self.c_add = button("Add custom role", lambda: self.add_custom_from_form(),
                          "Add a custom role with these values after the selected role")
      ## Custom role form: writes the form to the selected custom role.
      self.c_apply = button("Apply to selected", lambda: self.apply_form(),
                            "Rename the selected custom role and set its width, count and default (one undo step)")
      ## Transfer defaults of the stats (monster_layout.transfer_defaults).
      self.transfer_box = TransferDefaultsBox(self)
      ## A record's derived roles (derived_values() / rederive()).
      self.derived_box = DerivedPreviewBox(self)
      ## A record transferred in (import_rederived()).
      self.import_box = TransferPreviewBox(self)
      ## The bottom tabs (BOTTOM_TABS).
      self.tabs = QtWidgets.QTabWidget()
      self._build_layout()

   def _build_layout(self) -> None:
      """!Places the widgets.
      @return None
      """
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("The creature record in order. Engine roles (grey) have fixed IDs; some let the "
                              "layout choose their width. Custom roles are fields the engine stores and scripts "
                              "read and write; their ID is 0x80 + their place among the custom roles. Untick "
                              "Stored to compute a custom role on read from its derived or constant generation "
                              "entry (no record bits; its ID after the stored ones). Drag rows to reorder.")
      note.setWordWrap(True)
      lay.addWidget(note)
      top = QtWidgets.QHBoxLayout()
      form = QtWidgets.QFormLayout()
      form.addRow(self.term_label("party", False, "Creatures per {}"), self.party_size)
      form.addRow("Move slots", self.move_slots)
      top.addLayout(form)
      budget = QtWidgets.QVBoxLayout()
      budget.addWidget(QtWidgets.QLabel("Record bytes per target:"))
      budget.addLayout(self.budget_row)
      budget.addWidget(self.hash_label)
      top.addLayout(budget)
      top.addStretch(1)
      lay.addLayout(top)
      lay.addWidget(self.hash_warning)
      lay.addWidget(self.problems)
      lay.addWidget(self.table, TABLE_STRETCH)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Engine role:"))
      row.addWidget(self.engine_choice)
      row.addWidget(button("Add", lambda: self.add_engine_role(), "Add the engine role after the selected role"))
      row.addWidget(button("Remove", lambda: self.remove_role(), "Remove the selected role from the record"))
      row.addWidget(button("Up", lambda: self.move_role(-1), "Earlier in the record"))
      row.addWidget(button("Down", lambda: self.move_role(1), "Later in the record"))
      row.addStretch(1)
      lay.addLayout(row)
      group = QtWidgets.QGroupBox("Custom role")
      cform = QtWidgets.QFormLayout(group)
      cform.addRow("Name", self.c_name)
      sizes = QtWidgets.QHBoxLayout()
      sizes.addWidget(QtWidgets.QLabel("Width (bits)"))
      sizes.addWidget(self.c_width)
      sizes.addWidget(QtWidgets.QLabel("Count"))
      sizes.addWidget(self.c_count)
      sizes.addWidget(QtWidgets.QLabel("Default"))
      sizes.addWidget(self.c_default)
      sizes.addStretch(1)
      cform.addRow(sizes)
      buttons = QtWidgets.QHBoxLayout()
      buttons.addWidget(self.c_add)
      buttons.addWidget(self.c_apply)
      buttons.addStretch(1)
      cform.addRow(buttons)
      pages = {"custom": group, "transfer_defaults": self.transfer_box, "derived": self.derived_box,
               "transfer": self.import_box}
      for key, title in BOTTOM_TABS:
         self.tabs.addTab(pages[key], title)
      lay.addWidget(self.tabs)
      lay.addWidget(self.errors)

   # -- reading ------------------------------------------------------------------------

   def targets(self) -> tuple[list[str], str | None]:
      """!The game's target platforms.
      @return (targets, error reading the project or None); the default targets on an error
      """
      doc = self.battle_doc()
      try:
         return model.project_targets(doc.path if doc is not None else None), None
      except DocumentError as e:
         return list(stat_model.DEFAULT_TARGETS), str(e)

   def refresh(self) -> None:
      """!Re-reads the roles, the settings, the budgets and the hash.
      @return None
      """
      self.update_terms()
      doc = self.battle_doc()
      self._rows = model.role_rows(doc) if doc is not None else []
      names = [r["name"] for r in self._rows]
      if self.selected not in names:
         self.selected = names[0] if names else None
      targets, target_error = self.targets()
      report = model.layout_report(doc, targets) if doc is not None else None
      self._filling = True
      try:
         self._fill_settings(doc, targets)
         self._fill_budget(report, target_error)
         self._fill_table(report)
         self._fill_form()
         self.transfer_box.refresh()
         self.derived_box.refresh()
         self.import_box.refresh()
         free = model.free_engine_roles(doc) if doc is not None else []
         self.engine_choice.clear()
         self.engine_choice.addItems(free)
      finally:
         self._filling = False
      for w in (self.table, self.party_size, self.move_slots, self.engine_choice, self.c_name, self.c_width,
                self.c_count, self.c_default, self.c_add):
         w.setEnabled(doc is not None)
      self.show_errors()

   def _fill_settings(self, doc: Any, targets: list[str]) -> None:
      """!The party size and move slots spins, with the targets' limits.
      @param doc      battle Document, or None
      @param targets  platforms
      @return None
      """
      self.party_size.setRange(1, model.max_party_size(targets))
      self.move_slots.setRange(1, model.max_move_slots())
      if doc is None:
         return
      self.party_size.setToolTip(f"At most {model.max_party_size(targets)} on {', '.join(targets)}")
      self.move_slots.setToolTip(f"At most {model.max_move_slots()} (the engine's)")
      # A party size above the targets' limit still shows (the spin would clamp it): widen the range.
      self.party_size.setMaximum(max(self.party_size.maximum(), model.party_size(doc)))
      self.party_size.setValue(model.party_size(doc))
      self.move_slots.setValue(model.move_slots(doc))

   def _fill_budget(self, report: model.LayoutReport | None, target_error: str | None) -> None:
      """!The budget bars, the hash, the hash warning and the problems.
      @param report        layout_report(), or None with nothing open
      @param target_error  error reading the game's targets, or None
      @return None
      """
      while self.budget_row.count():
         w = self.budget_row.takeAt(0).widget()
         if w is not None:
            w.deleteLater()
      self.budget_bars = []
      if report is None:
         for label in (self.hash_label, self.hash_warning, self.problems):
            label.setText("")
         return
      for platform, used, most in report["budgets"]:
         bar = QtWidgets.QProgressBar()
         bar.setFixedWidth(BUDGET_WIDTH)
         bar.setRange(0, most)
         bar.setValue(min(used, most))
         bar.setTextVisible(True)
         bar.setFormat(model.budget_text(platform_text(platform), used, most))
         over = used > most
         bar.setStyleSheet("QProgressBar { color: black; text-align: center; font-weight: bold; }"
                           f"QProgressBar::chunk {{ background: {OVER_BAR_COLOR if over else WITHIN_COLOR}; }}")
         bar.setProperty("over", over)
         bar.setToolTip(f"{used} record bytes; the engine stores at most {most} on {platform}")
         self.budget_row.addWidget(bar)
         self.budget_bars.append(bar)
      if report["hash"] is not None:
         self.hash_label.setText(f"Layout hash {model.hash_text(report['hash'])} · {report['bytes']} bytes "
                                 f"({report['bits']} bits used)")
      else:
         self.hash_label.setText("Layout hash: ? (the layout does not compile)")
      warning = ""
      if report["hash_changed"]:
         warning = (f"The layout hash differs from the saved file's ({model.hash_text(report['saved_hash'])}): "
                    "old saves won't load with this layout.")
      self.hash_warning.setText(warning)
      self.hash_warning.setVisible(bool(warning))
      problems = report["problems"] + ([report["error"]] if report["error"] else []) + \
         ([target_error] if target_error else [])
      self.problems.setText("\n".join(problems))
      self.problems.setVisible(bool(problems))

   def _offsets(self, report: model.LayoutReport | None) -> list[int | None]:
      """!Each row's bit offset in the compiled record.
      @param report  layout_report(), or None
      @return one offset per row (None when the layout does not compile)
      """
      doc = self.battle_doc()
      compiled = model.compile_record(doc)[0] if doc is not None and report is not None else None
      if compiled is None:
         return [None] * len(self._rows)
      out = []
      for row in self._rows:
         if not row["stored"]:
            out.append(None)   # computed on read: no bits
         elif row["kind"] == model.KIND_CUSTOM:
            out.append(next((c["offset"] for c in compiled["custom"] if c["name"] == row["name"]), None))
         elif row["kind"] == model.KIND_ENGINE:
            out.append(compiled["offsets"][row["id"]])
         else:
            out.append(None)
      return out

   def _cell_text(self, row: model.RoleRow, key: str, offset: int | None) -> str:
      """!What a cell shows.
      @param row     role_rows() row
      @param key     column key
      @param offset  the role's bit offset, or None
      @return text
      """
      if key == "id":
         return "?" if row["id"] is None else f"0x{row['id']:02X}"
      if key == "stored":
         return "" if row["kind"] == model.KIND_CUSTOM else "yes"
      if key in ("bits", "offset") and not row["stored"]:
         return UNSTORED_TEXT
      if key == "offset":
         return "" if offset is None else str(offset)
      if key == "count_rule":
         return COUNT_FROM.get(row["count_rule"], "?")
      if key == "transfer":
         return model.transfer_text(row)
      value = row.get(key)
      return "" if value is None else str(value)

   def _editable(self, row: model.RoleRow, key: str) -> bool:
      """!Whether a cell is typed in.
      @param row  role_rows() row
      @param key  column key
      @return True when editable
      """
      custom = row["kind"] == model.KIND_CUSTOM
      return {"name": custom, "width": row["width_editable"], "count": row["count_editable"],
              "default": custom}.get(key, False)

   def _fill_table(self, report: model.LayoutReport | None) -> None:
      """!The role table.
      @param report  layout_report(), or None
      @return None
      """
      offsets = self._offsets(report)
      self.table.setRowCount(len(self._rows))
      editable = QtCore.Qt.ItemFlag.ItemIsEditable
      grey = QtGui.QBrush(QtGui.QColor(ENGINE_COLOR))
      engine_bg = QtGui.QBrush(QtGui.QColor(ENGINE_BACKGROUND))
      checkable = QtCore.Qt.ItemFlag.ItemIsUserCheckable
      unstored = QtGui.QBrush(QtGui.QColor(UNSTORED_COLOR))
      for r, row in enumerate(self._rows):
         engine_row = row["kind"] == model.KIND_ENGINE
         for key, c in ROLE_COLUMN.items():
            item = QtWidgets.QTableWidgetItem(self._cell_text(row, key, offsets[r]))
            if not self._editable(row, key):
               item.setFlags(item.flags() & ~editable)
            if key == "stored" and row["kind"] == model.KIND_CUSTOM:
               item.setFlags(item.flags() | checkable)
               item.setCheckState(QtCore.Qt.CheckState.Checked if row["stored"] else
                                  QtCore.Qt.CheckState.Unchecked)
               item.setToolTip("Stored in the record; untick to compute it on read from its derived or constant "
                               "generation entry (no record bits, not in the hash or the transfer)")
            if not row["stored"]:
               item.setForeground(unstored)
               if key in ("bits", "offset", "name"):
                  item.setToolTip("Computed on read from its generation entry: no record bits (E13a)")
            if engine_row:
               item.setBackground(engine_bg)
               if key in ("id", "name", "kind"):
                  item.setForeground(grey)
            if key == "width" and row["width_editable"]:
               item.setToolTip(f"1-{row['width_max']} bits")
            elif key == "width" and engine_row:
               item.setToolTip("Fixed by the engine")
            if key == "count" and row["count_editable"]:
               item.setToolTip(f"1-{row['count_max']} elements")
            if key == "transfer" and row["transfer_values"]:
               item.setToolTip("Transfer keys: " + ", ".join(model.hash_text(v) for v in row["transfer_values"]))
            if key == "name" and row["required"]:
               item.setToolTip("Every battle needs this role")
            self.table.setItem(r, c, item)
      self.table.resizeColumnsToContents()
      header = self.table.horizontalHeader()
      header.setStretchLastSection(False)   # resizing to contents fixed the last section's width: stretch again
      header.setStretchLastSection(True)
      names = [row["name"] for row in self._rows]
      if self.selected in names:
         self.table.selectRow(names.index(self.selected))

   def selected_row(self) -> model.RoleRow | None:
      """!The selected role.
      @return its role_rows() row, or None
      """
      return next((r for r in self._rows if r["name"] == self.selected), None)

   def _fill_form(self) -> None:
      """!The custom role form: the selected custom role's values (a new role's otherwise).
      @return None
      """
      self.c_width.setRange(1, model.max_role_bits())
      self.c_count.setRange(1, model.max_custom_count())
      row = self.selected_row()
      custom = row is not None and row["kind"] == model.KIND_CUSTOM
      self.c_apply.setEnabled(custom)
      if not custom:
         return
      self.c_name.setText(str(row["name"]))
      if isinstance(row["width"], int):
         self.c_width.setValue(row["width"])
      if isinstance(row["count"], int):
         self.c_count.setValue(row["count"])
      self.c_default.setText(str(row["default"]))

   # -- editing ------------------------------------------------------------------------

   def _selection_changed(self) -> None:
      """!Another role row was picked.
      @return None
      """
      if self._filling:
         return
      rows = self.table.selectionModel().selectedRows()
      if rows and rows[0].row() < len(self._rows):
         self.selected = self._rows[rows[0].row()]["name"]
         self._filling = True
         try:
            self._fill_form()
         finally:
            self._filling = False

   def _refused(self, ok: bool) -> bool:
      """!After an edit: a refused one shows the stored values again.
      @param ok  whether the edit went through
      @return ok
      """
      if not ok:
         self.host.changed()
      return ok

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A cell was typed in.
      @param item  QTableWidgetItem
      @return None
      """
      if self._filling or not 0 <= item.row() < len(self._rows):
         return
      row = self._rows[item.row()]
      key = ROLE_COLUMNS[item.column()][0]
      if key == "stored" and row["kind"] == model.KIND_CUSTOM:
         checked = item.checkState() == QtCore.Qt.CheckState.Checked
         if checked != row["stored"]:
            self.set_stored(row["name"], checked)
         return
      if key not in EDIT_KEYS:
         return
      text = item.text().strip()
      if key == "name":
         if text != row["name"]:
            self.rename_role(row["name"], text)
         return
      try:
         value = parse_number(text)
      except ValueError:
         self.host.show_status(f"{key}: a whole number")
         self.host.changed()
         return
      self.set_role(row["name"], key, value)

   def set_role(self, name: str, key: str, value: int | None) -> bool:
      """!Changes one property of a role (one undo step).
      @param name   role name
      @param key    width, count or default
      @param value  the value, or None for the default
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      row = next((r for r in self._rows if r["name"] == name), None)
      if row is not None and row.get(key) == value:
         return False
      return self._refused(self.edit(f"Role {key}", lambda: model.set_role(doc, name, key, value)))

   def set_stored(self, name: str, stored: bool) -> bool:
      """!Whether the record holds a custom role (one undo step; E13a: unstored = computed on read). Asks first when
      field scripts use the role (they read an unstored role as 0; the custom IDs after it move).
      @param name    role name
      @param stored  True: stored; False: computed on read
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if not self.confirm_scripts_use(doc, name, True, "Unstore" if not stored else "Store", storing=stored):
         self.host.changed()   # puts the box back
         return False
      self.selected = name
      return self._refused(self.edit("Role stored", lambda: model.set_stored(doc, name, stored)))

   def rename_role(self, old: str, new: str) -> bool:
      """!Renames a custom role (one undo step).
      @param old  current name
      @param new  new name
      @return True when renamed
      """
      doc = self.battle_doc()
      if doc is None or not new or new == old:
         self.host.changed()
         return False
      if not self.confirm_scripts_use(doc, old, False):
         self.host.changed()   # puts the old name back in the table
         return False
      if self._refused(self.edit("Rename role", lambda: model.rename_role(doc, old, new))):
         self.selected = new
         return True
      return False

   def confirm_scripts_use(self, doc: Document, name: str, removing: bool, what: str | None = None,
                           storing: bool = False) -> bool:
      """!Asks before removing or renaming a role the game's field scripts use (core.structure.record.role_users():
      role_get / role_set statements, record placeholders).
      @param doc       battle Document
      @param name      role name
      @param removing  True for a removal (or a change that moves the custom IDs after it), False for a rename
      @param what      the verb the question uses, or None for Remove / Rename
      @param storing   the role is stored again (C5: the IDs move from its stored-position ID on)
      @return True to go ahead (nothing uses it, or the user says so; headless No: widgets.ask(), as the CLI
              refuses without --force)
      """
      users = model.role_users(doc, name, removing, storing)
      if not users:
         return True
      shown = "\n".join(users[:battle.REFERENCES_SHOWN]) + ("\n..." if len(users) > battle.REFERENCES_SHOWN else "")
      what = what or ("Remove" if removing else "Rename")
      b = QtWidgets.QMessageBox.StandardButton
      answer = ask(self, f"{what} role", f"Field scripts use the role {name!r}; they will no longer compile:\n\n"
                   f"{shown}\n\n{what} it anyway?", b.Yes | b.No, b.No, b.No)
      return answer == b.Yes

   def _after_selected(self) -> int | None:
      """!The position after the selected role.
      @return the index, or None for the end
      """
      row = self.selected_row()
      return row["index"] + 1 if row is not None else None

   def add_engine_role(self, name: str | None = None) -> bool:
      """!Adds an engine role after the selected role.
      @param name  the role, or None for the one chosen in the combo
      @return True when added
      """
      doc = self.battle_doc()
      name = name or self.engine_choice.currentText()
      if doc is None or not name:
         return False
      at = self._after_selected()
      if self._refused(self.edit("Add role", lambda: model.add_engine_role(doc, name, at))):
         self.selected = name
         return True
      return False

   def _form_default(self) -> int | None:
      """!The form's default value.
      @return the number (None: the default, 0)
      @throws ValueError when it is not a number
      """
      return parse_number(self.c_default.text())

   def add_custom_from_form(self) -> bool:
      """!Adds a custom role with the form's values after the selected role.
      @return True when added
      """
      doc = self.battle_doc()
      name = self.c_name.text().strip()
      if doc is None:
         return False
      try:
         default = self._form_default()
      except ValueError:
         self.host.show_status("Default: a whole number")
         return False
      width, count, at = self.c_width.value(), self.c_count.value(), self._after_selected()
      ok = self.edit("Add custom role",
                     lambda: model.add_custom_role(doc, name, width, count if count != 1 else None,
                                                   default or None, at))
      if ok:
         self.selected = name
      return self._refused(ok)

   def apply_form(self) -> bool:
      """!Writes the form's name, width, count and default to the selected custom role (one undo step).
      @return True when something changed
      """
      doc, row = self.battle_doc(), self.selected_row()
      if doc is None or row is None or row["kind"] != model.KIND_CUSTOM:
         return False
      try:
         default = self._form_default()
      except ValueError:
         self.host.show_status("Default: a whole number")
         return False
      name, new = row["name"], self.c_name.text().strip()
      width, count = self.c_width.value(), self.c_count.value()
      if new != name and not self.confirm_scripts_use(doc, name, False):
         return False

      def apply() -> None:
         """!Renames, then sets each property (the default last: it must fit the new width).
         @return None
         """
         current = name
         if new != name:
            model.rename_role(doc, name, new)
            current = new
         model.set_role(doc, current, model.WIDTH_KEY, width)
         model.set_role(doc, current, model.COUNT_KEY, count if count != 1 else None)
         model.set_role(doc, current, model.DEFAULT_KEY, default or None)

      ok = self.edit("Edit custom role", apply)
      if ok:
         self.selected = new
      return self._refused(ok)

   def remove_role(self) -> bool:
      """!Removes the selected role (refused for the roles battles need).
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if not self.confirm_scripts_use(doc, name, True):
         return False
      if self._refused(self.edit("Remove role", lambda: model.remove_role(doc, name))):
         self.selected = None
         return True
      return False

   def move_role(self, delta: int) -> bool:
      """!Moves the selected role up or down.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      moved = []
      ok = self.edit("Move role", lambda: moved.append(model.move_role(doc, name, delta)))
      return self._refused(ok) and moved == [True]

   def move_role_to(self, name: str, index: int) -> bool:
      """!Moves a role to a position (a drag; one undo step).
      @param name   role name
      @param index  new position
      @return True when it moved
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      moved = []
      ok = self.edit("Move role", lambda: moved.append(model.move_role_to(doc, name, index)))
      if ok and moved == [True]:
         self.selected = name
         return True
      self._refused(ok)
      return False

   def _dropped(self, source: int, target: int) -> None:
      """!A row was dragged onto another.
      @param source  row dragged
      @param target  row dropped on
      @return None
      """
      if 0 <= source < len(self._rows):
         self.move_role_to(self._rows[source]["name"], target)

   def set_party_size(self, value: int) -> bool:
      """!Sets the party size (one undo step; the layout becomes the object form).
      @param value  creatures per party
      @return True when it changed
      """
      doc = self.battle_doc()
      if self._filling or doc is None or value == model.party_size(doc):
         return False
      targets = self.targets()[0]
      return self._refused(self.edit("Party size", lambda: model.set_party_size(doc, value, targets)))

   def set_move_slots(self, value: int) -> bool:
      """!Sets the move slots (one undo step; the layout becomes the object form).
      @param value  moves per creature
      @return True when it changed
      """
      doc = self.battle_doc()
      if self._filling or doc is None or value == model.move_slots(doc):
         return False
      return self._refused(self.edit("Move slots", lambda: model.set_move_slots(doc, value)))
