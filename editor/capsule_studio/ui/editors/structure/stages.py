"""!The Stages panel (D-22 A7, D-23 §3.2 "Stats & Stages"): the battle
manifest's "stages" list in index order and the table of the selected stage
with a preview of what it does.

The stages table edits a stage's name (a rename follows the effect logic),
its in-game label (empty: the default, the stat's label or the name), the
stat of a stat stage, its range (lo..hi; a table is fitted, new entries x1)
and how it scales: by a table, by a named ruleset formula of two arguments
(the value and the stage value) or not at all. The kind is fixed (remove the
stage and add another). The entry table below lists the selected stage's
values with its table entry ([num, den] multipliers, odds n/m for the crit
stage; typing one gives the stage a table) and the engine's result for a
value of 100 (or the odds in percent). Every change is one undo step of the
battle manifest (core.structure.stages); the engine's compiler checks the
result and its message shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ....core.document import DocumentError
from ....core.structure import stages as stage_model
from ....core.structure import stats as stat_model
from ...widgets import button
from ..battle_common import NONE_TEXT, STRUCTURE, BattlePanel

if TYPE_CHECKING:
   from ...panel import PanelHost

## Stages table columns, in order: (stage_list() key, header).
STAGE_COLUMNS = [("index", "#"), ("name", "Name"), ("label", "Label"), ("kind", "Kind"), ("stat", "Stat"),
                 ("lo", "Lowest"), ("hi", "Highest"), ("mode", "Scales by"), ("formula", "Formula")]
## Stages table column of each key.
STAGE_COLUMN = {key: c for c, (key, _header) in enumerate(STAGE_COLUMNS)}
## Columns typed as text (the name renames; an empty label puts the default back).
STAGE_TEXT_KEYS = ("name", "label")
## Read-only text columns.
STAGE_READ_ONLY = ("index", "kind")
## Entry table columns: the stage value, its table entry, what it means, the engine's result.
ENTRY_COLUMNS = ["Stage", "Entry", "Means", "Result"]
## Entry table column of the stage value.
ENTRY_STAGE_COLUMN = 0
## Entry table column of the table entry (editable).
ENTRY_VALUE_COLUMN = 1
## Entry table column of the meaning.
ENTRY_MEANS_COLUMN = 2
## Entry table column of the engine's result.
ENTRY_RESULT_COLUMN = 3
## Text of an entry cell of a stage without a table.
NO_TABLE_TEXT = "x1"
## Text colour of a budget over its limit.
OVER_COLOR = "#c03030"
## Text colour of a budget within its limit.
WITHIN_COLOR = "#2a7a2a"
## Text colour of defaults shown in place of a missing value (a label taken from the stat).
DEFAULT_COLOR = "#909090"
## Stretch of the stages table in the panel's layout.
STAGES_STRETCH = 1
## Stretch of the entry table.
ENTRIES_STRETCH = 1


class StagesPanel(BattlePanel):
   """!The stages table, the stage budget and the selected stage's entries.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "stages"
   ## See EditorPanel.title.
   title = "Stages"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the tables and the buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Name of the selected stage, or None.
      self.selected = None
      ## Stages used against the limit of each target ("8/12 stages (GBA)").
      self.budget = QtWidgets.QLabel()
      ## The stages, one row each.
      self.table = QtWidgets.QTableWidget(0, len(STAGE_COLUMNS))
      self.table.setHorizontalHeaderLabels([h for _k, h in STAGE_COLUMNS])
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.verticalHeader().setVisible(False)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      ## Cell widgets of the stages table by row: {"stat", "lo", "hi", "mode", "formula": widget or None}.
      self.row_widgets = []
      ## What the selected stage's heading says.
      self.entries_label = QtWidgets.QLabel()
      ## The selected stage's values with their entries and results.
      self.entries = QtWidgets.QTableWidget(0, len(ENTRY_COLUMNS))
      self.entries.setHorizontalHeaderLabels(ENTRY_COLUMNS)
      self.entries.verticalHeader().setVisible(False)
      self.entries.horizontalHeader().setStretchLastSection(True)
      self.entries.itemChanged.connect(lambda item: self._entry_changed(item))
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("A stage's place is its index. Effect code names it (stage target atk -1); its label "
                              "is the in-game text. A table holds one entry per stage value from the lowest "
                              "(multipliers num/den, odds n/m for the crit stage); a formula is a named ruleset "
                              "formula of (value, stage); neither scales by x1.")
      note.setWordWrap(True)
      lay.addWidget(note)
      lay.addWidget(self.budget)
      lay.addWidget(self.table, STAGES_STRETCH)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_stage(), "Add a stage (x1; a crit stage never hits)"))
      row.addWidget(button("Remove", lambda: self.remove_stage(), "Remove the selected stage (no logic may name it)"))
      row.addWidget(button("Rename...", lambda: self.rename_stage(), "Rename the selected stage; logic follows"))
      row.addWidget(button("Up", lambda: self.move_stage(-1), "Lower index"))
      row.addWidget(button("Down", lambda: self.move_stage(1), "Higher index"))
      row.addStretch(1)
      lay.addLayout(row)
      lay.addWidget(self.entries_label)
      lay.addWidget(self.entries, ENTRIES_STRETCH)
      lay.addWidget(self.errors)

   # -- reading ------------------------------------------------------------------------

   def rows(self) -> list[stage_model.StageRow]:
      """!The stages as the table shows them.
      @return stage_list() rows ([] with nothing open)
      """
      doc = self.battle_doc()
      return stage_model.stage_list(doc) if doc is not None else []

   def targets(self) -> list[str]:
      """!The game's target platforms (the default ones when the project can't be read).
      @return platforms
      """
      doc = self.battle_doc()
      try:
         return stat_model.project_targets(doc.path if doc is not None else None)
      except DocumentError:
         return list(stat_model.DEFAULT_TARGETS)

   def refresh(self) -> None:
      """!Re-reads the stages, the budget and the selected stage's entries.
      @return None
      """
      doc = self.battle_doc()
      rows = self.rows()
      names = [r["name"] for r in rows]
      if self.selected not in names:
         self.selected = names[0] if names else None
      self._filling = True
      try:
         self._fill_budget(rows)
         self._fill_table(rows)
         self._fill_entries(next((r for r in rows if r["name"] == self.selected), None))
      finally:
         self._filling = False
      self.table.setEnabled(doc is not None)
      self.entries.setEnabled(doc is not None)
      self.show_errors()

   def _fill_budget(self, rows: list[stage_model.StageRow]) -> None:
      """!The budget line.
      @param rows  stage_list() rows
      @return None
      """
      if self.battle_doc() is None:
         self.budget.setText("")
         return
      parts, over = [], False
      for t in self.targets():
         most = stage_model.max_stages([t])
         over = over or len(rows) > most
         parts.append(f"{len(rows)}/{most} {t.upper()}")
      self.budget.setText("Stages per target: " + ", ".join(parts))
      self.budget.setStyleSheet(f"color: {OVER_COLOR if over else WITHIN_COLOR}; font-weight: bold;")

   def _fill_table(self, rows: list[stage_model.StageRow]) -> None:
      """!The stages table.
      @param rows  stage_list() rows
      @return None
      """
      p = self.project()
      formulas = stage_model.formula_choices(p) if p is not None else []
      doc = self.battle_doc()
      stat_names = [r["name"] for r in stat_model.stat_list(doc) if not r["pool"]] if doc is not None else []
      limit = stage_model.stage_limit()
      self.table.setRowCount(len(rows))
      self.row_widgets = []
      editable = QtCore.Qt.ItemFlag.ItemIsEditable
      for r, row in enumerate(rows):
         widgets: dict[str, Any] = {}
         for key in ("index", "name", "label", "kind"):
            item = QtWidgets.QTableWidgetItem("" if row[key] is None else str(row[key]))
            if key in STAGE_READ_ONLY:
               item.setFlags(item.flags() & ~editable)
            if key == "label" and not row["labelled"]:
               item.setForeground(QtGui.QBrush(QtGui.QColor(DEFAULT_COLOR)))
               item.setToolTip("The default: the stat's label, else the name (type one to set it)")
            self.table.setItem(r, STAGE_COLUMN[key], item)
         for key in ("stat", "lo", "hi", "mode", "formula"):
            self.table.setItem(r, STAGE_COLUMN[key], QtWidgets.QTableWidgetItem(""))
         name = row["name"]
         if row["kind"] == stage_model.STAT_KIND:
            box = QtWidgets.QComboBox()
            box.addItems(stat_names + ([] if row["stat"] in stat_names else [str(row["stat"])]))
            box.setCurrentText(str(row["stat"]))
            box.activated.connect(lambda _i, n=name, b=box: self.set_stage(n, "stat", b.currentText()))
            self.table.setCellWidget(r, STAGE_COLUMN["stat"], box)
            widgets["stat"] = box
         lo, hi = row["range"] if row["range"] is not None else (0, 0)
         for key, value, lowest, highest in (("lo", lo, -limit, 0), ("hi", hi, 0, limit)):
            sb = QtWidgets.QSpinBox()
            sb.setRange(lowest, highest)
            sb.setValue(value)
            sb.valueChanged.connect(lambda _v, n=name: self._range_changed(n))
            self.table.setCellWidget(r, STAGE_COLUMN[key], sb)
            widgets[key] = sb
         mode = QtWidgets.QComboBox()
         # The crit stage takes odds, never a formula.
         crit = row["kind"] == stage_model.CRIT_KIND
         modes = [m for m in stage_model.MODES if not (crit and m == stage_model.FORMULA_MODE)]
         mode.addItems(modes)
         mode.setCurrentText(row["mode"])
         mode.activated.connect(lambda _i, n=name, b=mode: self._mode_picked(n, b.currentText()))
         self.table.setCellWidget(r, STAGE_COLUMN["mode"], mode)
         widgets["mode"] = mode
         formula = QtWidgets.QComboBox()
         formula.addItems([NONE_TEXT] + formulas + ([row["formula"]] if row["formula"] and
                                                     row["formula"] not in formulas else []))
         formula.setCurrentText(row["formula"] or NONE_TEXT)
         formula.setEnabled(row["kind"] != stage_model.CRIT_KIND)
         formula.activated.connect(lambda _i, n=name, b=formula: self._formula_picked(n, b.currentText()))
         self.table.setCellWidget(r, STAGE_COLUMN["formula"], formula)
         widgets["formula"] = formula
         self.row_widgets.append(widgets)
      self.table.resizeColumnsToContents()
      names = [row["name"] for row in rows]
      if self.selected in names:
         self.table.selectRow(names.index(self.selected))

   def _fill_entries(self, row: stage_model.StageRow | None) -> None:
      """!The selected stage's entries and the engine's results.
      @param row  its stage_list() row, or None
      @return None
      """
      if row is None or row["range"] is None:
         self.entries_label.setText("No stage selected." if row is None else f"{row['name']} has no range.")
         self.entries.setRowCount(0)
         return
      p = self.project()
      try:
         preview = stage_model.preview(p, row["name"]) if p is not None else []
         note = ""
      except DocumentError as e:
         preview, note = [], f" (no results while the data does not compile: {e})"
      what = "odds" if row["kind"] == stage_model.CRIT_KIND else f"a value of {stage_model.PREVIEW_VALUE}"
      self.entries_label.setText(f"{row['name']}: entries per stage value, and what the engine makes of {what}"
                                 + note)
      lo, hi = row["range"]
      by_value = {v: (how, result) for v, how, result in preview}
      editable = QtCore.Qt.ItemFlag.ItemIsEditable
      self.entries.setRowCount(hi - lo + 1)
      table = row["table"]
      for r, v in enumerate(range(lo, hi + 1)):
         entry = stage_model.entry_text(table[r]) if isinstance(table, list) and r < len(table) else NO_TABLE_TEXT
         how, result = by_value.get(v, ("", ""))
         for c, text in enumerate((f"{v:+d}" if v else "0", entry, how, result)):
            item = QtWidgets.QTableWidgetItem(text)
            if c != ENTRY_VALUE_COLUMN or row["mode"] == stage_model.FORMULA_MODE:
               item.setFlags(item.flags() & ~editable)
            if c == ENTRY_VALUE_COLUMN and row["mode"] != stage_model.TABLE_MODE:
               item.setToolTip("Typing an entry gives the stage a table (x1 elsewhere)")
            self.entries.setItem(r, c, item)
      self.entries.resizeColumnsToContents()

   # -- editing ------------------------------------------------------------------------

   def _selection_changed(self) -> None:
      """!Another stage row was picked: its entries show.
      @return None
      """
      if self._filling:
         return
      rows = self.table.selectionModel().selectedRows()
      all_rows = self.rows()
      if rows and rows[0].row() < len(all_rows):
         self.selected = all_rows[rows[0].row()]["name"]
         self._filling = True
         try:
            self._fill_entries(all_rows[rows[0].row()])
         finally:
            self._filling = False

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A name or label was typed.
      @param item  QTableWidgetItem
      @return None
      """
      if self._filling:
         return
      rows = self.rows()
      key = STAGE_COLUMNS[item.column()][0]
      if not 0 <= item.row() < len(rows) or key not in STAGE_TEXT_KEYS:
         return
      name, text = rows[item.row()]["name"], item.text().strip()
      if key == "name":
         if text != name:
            self.rename_stage(text, name)
         return
      self.set_stage(name, "label", text or None)

   def _range_changed(self, name: str) -> None:
      """!A range spin changed.
      @param name  the stage
      @return None
      """
      if self._filling:
         return
      i = [r["name"] for r in self.rows()].index(name)
      w = self.row_widgets[i]
      self.set_stage(name, "range", [w["lo"].value(), w["hi"].value()])

   def _mode_picked(self, name: str, mode: str) -> None:
      """!A "scales by" combo changed.
      @param name  the stage
      @param mode  one of core.structure.stages.MODES
      @return None
      """
      formula = None
      if mode == stage_model.FORMULA_MODE:
         p = self.project()
         choices = stage_model.formula_choices(p) if p is not None else []
         if not choices:
            self.host.show_status("The ruleset has no named formula of two arguments (value, stage).")
            self.host.changed()
            return
         formula = choices[0]
      self.set_mode(name, mode, formula)

   def _formula_picked(self, name: str, text: str) -> None:
      """!A formula combo changed.
      @param name  the stage
      @param text  the formula, or NONE_TEXT
      @return None
      """
      if text == NONE_TEXT:
         self.set_mode(name, stage_model.NO_MODE)
      else:
         self.set_mode(name, stage_model.FORMULA_MODE, text)

   def set_stage(self, name: str, key: str, value: Any) -> bool:
      """!Changes one property of a stage (one undo step).
      @param name   stage name
      @param key    one of core.structure.stages.STAGE_PROPERTIES
      @param value  the value (None: the default)
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      row = next((r for r in self.rows() if r["name"] == name), None)
      if row is not None:
         current = {"label": row["label"] if row["labelled"] else None, "stat": row["stat"],
                    "range": list(row["range"]) if row["range"] is not None else None,
                    "table": row["table"], "formula": row["formula"]}.get(key)
         if current == value:
            return False
      ok = self.edit(f"Stage {key}", lambda: stage_model.set_stage(doc, name, key, value))
      if not ok:
         self.host.changed()
      return ok

   def set_mode(self, name: str, mode: str, formula: str | None = None) -> bool:
      """!Chooses how a stage scales (one undo step).
      @param name     stage name
      @param mode     one of core.structure.stages.MODES
      @param formula  the formula (mode "formula")
      @return True when the edit went through
      """
      doc, p = self.battle_doc(), self.project()
      if doc is None or p is None:
         return False
      row = next((r for r in self.rows() if r["name"] == name), None)
      if row is not None and row["mode"] == mode and (mode != stage_model.FORMULA_MODE or row["formula"] == formula):
         return False
      choices = stage_model.formula_choices(p)
      ok = self.edit("Stage scaling", lambda: stage_model.set_mode(doc, name, mode, formula, choices))
      if not ok:
         self.host.changed()
      return ok

   def _entry_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A table entry was typed.
      @param item  QTableWidgetItem
      @return None
      """
      if self._filling or item.column() != ENTRY_VALUE_COLUMN or self.selected is None:
         return
      row = next((r for r in self.rows() if r["name"] == self.selected), None)
      if row is None or row["range"] is None:
         return
      self.set_entry(row["range"][0] + item.row(), item.text())

   def set_entry(self, stage: int, text: str) -> bool:
      """!Sets one table entry of the selected stage (one undo step).
      @param stage  the stage value
      @param text   "num/den" (odds "n/m" for the crit stage)
      @return True when the edit went through
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      ok = self.edit("Stage table", lambda: stage_model.set_entry(doc, name, stage, text.strip()))
      if not ok:
         self.host.changed()
      return ok

   def add_stage(self, kind: str | None = None, stat: str | None = None, name: str | None = None) -> bool:
      """!Adds a stage after the selected one.
      @param kind  its kind, or None to ask
      @param stat  the stat (kind stat), or None to ask
      @param name  its name, or None for the default (the stat's name, else the kind)
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if kind is None:
         kind, ok = QtWidgets.QInputDialog.getItem(self, "Add stage", "Kind:", stage_model.kinds(), 0, False)
         if not ok:
            return False
      if kind == stage_model.STAT_KIND and stat is None:
         free = [r["name"] for r in stat_model.stat_list(doc) if not r["pool"] and not r["stage"]]
         if not free:
            self.host.show_status("Every stat but the pool stat has a stage already.")
            return False
         stat, ok = QtWidgets.QInputDialog.getItem(self, "Add stage", "Stat:", free, 0, False)
         if not ok:
            return False
      names = [r["name"] for r in self.rows()]
      at = names.index(self.selected) + 1 if self.selected in names else None
      added = []
      targets = self.targets()
      if self.edit("Add stage", lambda: added.append(stage_model.add_stage(doc, kind, name, stat, None, at,
                                                                             None, targets))):
         self.selected = self.rows()[added[0]]["name"]
         return True
      return False

   def remove_stage(self) -> bool:
      """!Removes the selected stage (refused while effect logic names it).
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self.edit("Remove stage", lambda: stage_model.remove_stage(doc, name)):
         self.selected = None
         return True
      return False

   def rename_stage(self, new: str | None = None, old: str | None = None) -> bool:
      """!Renames a stage; the effect logic naming it follows (one undo step).
      @param new  the new name, or None to ask
      @param old  the stage, or None for the selected one
      @return True when renamed
      """
      doc = self.battle_doc()
      old = old or self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename stage", "New name:", text=old)
         if not ok:
            return False
      new = new.strip()
      if not new or new == old:
         self.host.changed()
         return False
      if self.edit("Rename stage", lambda: stage_model.rename_stage(doc, old, new)):
         self.selected = new
         return True
      self.host.changed()
      return False

   def move_stage(self, delta: int) -> bool:
      """!Moves the selected stage up or down.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      moved = []
      ok = self.edit("Move stage", lambda: moved.append(stage_model.move_stage(doc, name, delta)))
      return ok and moved == [True]
