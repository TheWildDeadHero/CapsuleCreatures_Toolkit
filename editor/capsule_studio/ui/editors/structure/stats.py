"""!The Stats panel (D-20 F StatsPanel, D-23 §3.2 "Stats & Stages"): the
battle manifest's stats with their flags and a stat budget per target
platform.

The stats table edits name (a rename follows every reference, the stat's
stage included, and keeps the transfer key), label, abbreviation, formula
(one of the ruleset's stat formulas), the pool / order / odds / stage / trait flags
and the transfer key. The stage flag gives the stat a stage in the
manifest's "stages" list or takes it off (core.structure.stages); the
stages themselves (ranges, tables, formulas, labels) are edited on the
Stages page (ui/editors/structure/stages.py). Add, remove, move and rename
are one undo step each, with every species' base values
(core.structure.stats). The budget line shows "6/10 GBA" for each of the
game's targets (its project.json "targets"), red when over. Everything
edits the battle manifest, so Undo / Redo on this page act on it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import battle
from ....core.document import DocumentError
from ....core.structure import stats as stat_model
from ...widgets import button, set_enabled
from ..battle_common import STRUCTURE, TERM_SLOT, BattlePanel

if TYPE_CHECKING:
   from ...panel import PanelHost

## Stats table columns, in order: (stat_list() key, header).
STAT_COLUMNS = [("name", "Name"), ("label", "Label"), ("short", "Short"), ("formula", "Formula"),
                ("pool", "Pool"), ("order", "Order"), ("odds", "Odds"), ("stage", "Stage"), ("trait", "Trait"),
                ("transfer", "Transfer key"), ("stage_index", "Stage #")]
## Stats table column of each stat_list() key.
STAT_COLUMN = {key: c for c, (key, _header) in enumerate(STAT_COLUMNS)}
## Columns typed as text (the name renames; an empty short or transfer key puts the default back).
TEXT_KEYS = ("name", "label", "short", "transfer")
## Columns that are check boxes (the stat's flags).
FLAG_KEYS = stat_model.FLAGS
## Read-only columns.
READ_ONLY_KEYS = ("stage_index",)
## Text colour of a budget over its limit (and of limit problems).
OVER_COLOR = "#c03030"
## Text colour of a budget within its limit.
WITHIN_COLOR = "#2a7a2a"
## Text colour of defaults shown in place of a missing value (a transfer key equal to the name).
DEFAULT_COLOR = "#909090"
## Stretch of the stats table in the panel's layout.
TABLE_STRETCH = 1
## Pattern of the budget heading ("Stats per target:").
TERM_SLOT_BUDGET = TERM_SLOT + " per target:"


def platform_text(platform: str) -> str:
   """!A target platform as the budget shows it.
   @param platform  build_settings platform name
   @return e.g. "GBA"
   """
   return platform.upper()


class StatsPanel(BattlePanel):
   """!The stats table with its budget per target.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "stats"
   ## See EditorPanel.title.
   title = "Stats"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the tables and buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Name of the selected stat, or None.
      self.selected = None
      ## Budget labels, one per target ("6/10 GBA").
      self.budget_labels = []
      ## Row holding the budget labels.
      self.budget_row = QtWidgets.QHBoxLayout()
      ## What the stats break on a target (too many stats or staged stats), or empty.
      self.limit_problems = QtWidgets.QLabel()
      self.limit_problems.setWordWrap(True)
      self.limit_problems.setStyleSheet(f"color: {OVER_COLOR};")
      ## The stats, one row each.
      self.table = QtWidgets.QTableWidget(0, len(STAT_COLUMNS))
      self.table.setHorizontalHeaderLabels([h for _key, h in STAT_COLUMNS])
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.verticalHeader().setVisible(False)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      ## Formula combos of the stats table, by row.
      self.formula_combos = []
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("A stat's position is its record and engine index. Exactly one stat is the pool "
                              "(hit points) and one the order stat (turn order, escape); at most one is the odds "
                              "stat (the effect_odds pipeline's user_stat / target_stat). A renamed stat keeps its "
                              "old name as its transfer key, so creatures moved between games still match. Stage "
                              "gives the stat a stage (its range and table: Structure > Stages).")
      note.setWordWrap(True)
      lay.addWidget(note)
      budget = QtWidgets.QHBoxLayout()
      budget.addWidget(self.term_label("stat", True, TERM_SLOT_BUDGET))
      budget.addLayout(self.budget_row)
      budget.addStretch(1)
      lay.addLayout(budget)
      lay.addWidget(self.limit_problems)
      lay.addWidget(self.table, TABLE_STRETCH)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_stat(), "Add a stat after the selected one (every species "
                                                              "gets a base value for it)"))
      row.addWidget(button("Remove", lambda: self.remove_stat(), "Remove the selected stat and its base values"))
      row.addWidget(button("Rename...", lambda: self.rename_stat(), "Rename the selected stat and what names it"))
      row.addWidget(button("Up", lambda: self.move_stat(-1), "Earlier in the record (lower engine index)"))
      row.addWidget(button("Down", lambda: self.move_stat(1), "Later in the record (higher engine index)"))
      row.addStretch(1)
      lay.addLayout(row)
      lay.addWidget(self.errors)

   # -- reading ------------------------------------------------------------------------

   def targets(self) -> tuple[list[str], str | None]:
      """!The game's target platforms.
      @return (targets, error reading the project or None); the default targets on an error
      """
      doc = self.battle_doc()
      try:
         return stat_model.project_targets(doc.path if doc is not None else None), None
      except DocumentError as e:
         return list(stat_model.DEFAULT_TARGETS), str(e)

   def rows(self) -> list[stat_model.StatRow]:
      """!The stats as the table shows them.
      @return stat_list() rows ([] with nothing open)
      """
      doc = self.battle_doc()
      return stat_model.stat_list(doc) if doc is not None else []

   def refresh(self) -> None:
      """!Re-reads the stats and the budgets.
      @return None
      """
      self.update_terms()
      doc = self.battle_doc()
      rows = self.rows()
      names = [r["name"] for r in rows]
      if self.selected not in names:
         self.selected = names[0] if names else None
      self._filling = True
      try:
         self._fill_budget(doc)
         self._fill_stats(rows)
      finally:
         self._filling = False
      set_enabled(self.table, doc is not None)   # read-only, still scrolling
      self.show_errors()

   def _fill_budget(self, doc: Any) -> None:
      """!The budget labels and the limit problems.
      @param doc  battle Document, or None
      @return None
      """
      while self.budget_row.count():
         w = self.budget_row.takeAt(0).widget()
         if w is not None:
            w.deleteLater()
      self.budget_labels = []
      if doc is None:
         self.limit_problems.setText("")
         return
      targets, error = self.targets()
      for platform, used, most in stat_model.stat_budget(doc, targets):
         label = QtWidgets.QLabel(f"{used}/{most} {platform_text(platform)}")
         label.setStyleSheet(f"color: {OVER_COLOR if used > most else WITHIN_COLOR}; font-weight: bold;")
         label.setToolTip(f"{used} stats; the engine takes at most {most} on {platform}")
         self.budget_row.addWidget(label)
         self.budget_labels.append(label)
      problems = stat_model.limit_problems(doc, targets) + ([error] if error else [])
      self.limit_problems.setText("\n".join(problems))
      self.limit_problems.setVisible(bool(problems))

   def _fill_stats(self, rows: list[stat_model.StatRow]) -> None:
      """!The stats table.
      @param rows  stat_list() rows
      @return None
      """
      p = self.project()
      formulas = battle.stat_formulas(p.ruleset) if p is not None else []
      self.table.setRowCount(len(rows))
      self.formula_combos = []
      editable = QtCore.Qt.ItemFlag.ItemIsEditable
      checkable = QtCore.Qt.ItemFlag.ItemIsUserCheckable
      for r, row in enumerate(rows):
         for key, c in STAT_COLUMN.items():
            if key == "formula":
               self.table.setItem(r, c, QtWidgets.QTableWidgetItem(""))
               box = QtWidgets.QComboBox()
               box.addItems(formulas)
               if row["formula"] not in formulas:
                  box.addItem(str(row["formula"]))   # odd data still shows (the compiler reports it)
               box.setCurrentText(str(row["formula"]))
               box.activated.connect(lambda _i, name=row["name"], b=box: self.set_stat(name, "formula",
                                                                                       b.currentText()))
               self.table.setCellWidget(r, c, box)
               self.formula_combos.append(box)
               continue
            value = row[key]
            if key in FLAG_KEYS:
               item = QtWidgets.QTableWidgetItem("")
               item.setFlags((item.flags() | checkable) & ~editable)
               item.setCheckState(QtCore.Qt.CheckState.Checked if value else QtCore.Qt.CheckState.Unchecked)
            else:
               item = QtWidgets.QTableWidgetItem("" if value is None else str(value))
               if key in READ_ONLY_KEYS:
                  item.setFlags(item.flags() & ~editable)
               if key == "transfer" and value == row["name"]:
                  item.setForeground(QtGui.QBrush(QtGui.QColor(DEFAULT_COLOR)))
                  item.setToolTip("The default: the stat's name")
            self.table.setItem(r, c, item)
      self.table.resizeColumnsToContents()
      if self.selected is not None:
         self.table.selectRow([row["name"] for row in rows].index(self.selected))

   # -- editing ------------------------------------------------------------------------

   def _selection_changed(self) -> None:
      """!Another stat row was picked.
      @return None
      """
      if self._filling:
         return
      rows = self.table.selectionModel().selectedRows()
      names = [r["name"] for r in self.rows()]
      if rows and rows[0].row() < len(names):
         self.selected = names[rows[0].row()]

   def _row_name(self, row: int) -> str | None:
      """!The stat shown in a table row.
      @param row  table row
      @return its name, or None
      """
      names = [r["name"] for r in self.rows()]
      return names[row] if 0 <= row < len(names) else None

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A cell was typed in or a flag ticked.
      @param item  QTableWidgetItem
      @return None
      """
      if self._filling:
         return
      name = self._row_name(item.row())
      key = STAT_COLUMNS[item.column()][0]
      if name is None or key in READ_ONLY_KEYS or key == "formula":
         return
      if key in FLAG_KEYS:
         self.set_stat(name, key, item.checkState() == QtCore.Qt.CheckState.Checked)
         return
      text = item.text().strip()
      if key == "name":
         if text != name:
            self.rename_stat(text, name)
         return
      if key == "label" and not text:
         self.host.show_status("A label can't be empty.")
         self.host.changed()   # the cell shows the stored value again
         return
      self.set_stat(name, key, text or None)

   def set_stat(self, name: str, key: str, value: Any) -> bool:
      """!Changes one property of a stat (one undo step).
      @param name   stat name
      @param key    one of core.structure.stats.STAT_KEYS
      @param value  the value (None: the default)
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      row = next((r for r in self.rows() if r["name"] == name), None)
      if row is not None:
         current = row[key]
         if key == "transfer":
            # Compare with what the manifest says: the table shows the name for the default key.
            current = stat_model.stat_entry(doc, name).get(key)
         if current == value:
            return False   # nothing changes
      ok = self.edit(f"Stat {key}", lambda: stat_model.set_stat(doc, name, key, value))
      if not ok:
         self.host.changed()   # a refused change: the table shows the stored values again
      return ok

   def add_stat(self, name: str | None = None) -> bool:
      """!Adds a stat after the selected one (every species gets a base value for it).
      @param name  its name, or None to ask
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add " + self.word("stat"), "Name (lower-case):")
         if not ok or not name.strip():
            return False
      names = [r["name"] for r in self.rows()]
      at = names.index(self.selected) + 1 if self.selected in names else None
      targets = self.targets()[0]
      if self.edit("Add " + self.word("stat"),
                   lambda: stat_model.add_stat(doc, name, None, None, at, targets=targets)):
         self.selected = name.strip()
         return True
      return False

   def remove_stat(self) -> bool:
      """!Removes the selected stat (refused for the pool and order stats and while something names it).
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self.edit("Remove " + self.word("stat"), lambda: stat_model.remove_stat(doc, name)):
         self.selected = None
         return True
      return False

   def rename_stat(self, new: str | None = None, old: str | None = None) -> bool:
      """!Renames a stat and what names it.
      @param new  the new name, or None to ask
      @param old  the stat, or None for the selected one
      @return True when renamed
      """
      doc = self.battle_doc()
      old = old or self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename " + self.word("stat"), "New name:", text=old)
         if not ok:
            return False
      new = new.strip()
      if not new or new == old:
         self.host.changed()
         return False
      if self.edit("Rename " + self.word("stat"), lambda: stat_model.rename_stat(doc, old, new)):
         self.selected = new
         return True
      self.host.changed()
      return False

   def move_stat(self, delta: int) -> bool:
      """!Moves the selected stat up or down, with every species' base value.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      moved = []
      ok = self.edit("Move " + self.word("stat"), lambda: moved.append(stat_model.move_stat(doc, name, delta)))
      return ok and moved == [True]
