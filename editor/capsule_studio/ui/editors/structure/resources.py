"""!The Resources panel (D-25, Structure > Resources): every pool a battler
spends or loses, the structure manifest's "resources" list in payment order
(core.structure.resources; the engine's battlec/resources.py decides).

The table edits a resource's name (a rename follows the moves' costs, the
move field named after it and the effect logic; bench scenarios naming it
are listed in the status bar), its in-game label, its scope (battler: one
pool per battler, its maximum a stat; move: one pool per move slot, its base
a move field, its maximum a named ruleset formula of (base, raises)), the
raises and persist record roles (a pool without a persist role is refilled
at the start of every battle), what an empty pool means (faint: the hit
points) and an end-of-turn regen amount (a number or a named formula; the
turn gets a regen phase). The budget line shows the resources against each
target's caps. Every change is one undo step (a rename spans battle.json and
structure.json: still one step); the compile result shows at the bottom.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core.structure import resources as res_model
from ....core.structure import stats as stat_model
from ...widgets import button
from ..battle_common import STRUCTURE, BattlePanel

if TYPE_CHECKING:
   from ...panel import PanelHost

## Table columns: (resource_rows() key, header).
RESOURCE_COLUMNS = [("index", "#"), ("name", "Name"), ("label", "Label"), ("scope", "Scope"), ("stat", "Stat (max)"),
                    ("base", "Base field"), ("max", "Max formula"), ("raises", "Raises"), ("persist", "Persist"),
                    ("empty", "Empty"), ("regen", "Regen"), ("payers", "Paid by")]
## Table column of each key.
RESOURCE_COLUMN = {key: c for c, (key, _h) in enumerate(RESOURCE_COLUMNS)}
## Columns typed into (the rest are widgets or read-only).
TEXT_KEYS = ("name", "label", "base")
## Columns shown as combo boxes.
COMBO_KEYS = ("scope", "stat", "max", "raises", "persist", "empty", "regen")
## Combo text of "none" (no max formula, no raises role, no regen).
NONE_TEXT = "-"
## Combo text of a pool refilled at the start of every battle (no persist role).
REFILL_TEXT = "(refill each battle)"
## Text colour of a budget over its limit.
OVER_COLOR = "#c03030"
## Text colour of a budget within its limit.
WITHIN_COLOR = "#2a7a2a"
## Undo label of each set_resource() key.
SET_LABELS = {"label": "Resource label", "stat": "Resource stat", "base": "Resource base", "max": "Resource max",
              "raises": "Resource raises", "persist": "Resource persist", "empty": "Resource empty",
              "regen": "Resource regen"}
## The page's explanation.
NOTE = ("Resources are the pools a battler spends or loses, paid in this order. A battler resource has one pool per "
        "battler (its maximum is a stat); a move resource one per move slot (each move states its base field; the "
        "maximum is a named formula of (base, raises), or the base). A persist role keeps the pool in the record "
        "between battles; without one it is refilled at the start of every battle. Exactly one resource faints its "
        "battler when empty: the hit points. Moves pay their cost (Content > Moves; default 1 of every move "
        "resource).")


class ResourcesPanel(BattlePanel):
   """!The resources table.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "resources"
   ## See EditorPanel.title.
   title = "Resources"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the table and the buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Name of the selected resource, or None.
      self.selected = None
      ## Resources used against each target's caps.
      self.budget = QtWidgets.QLabel()
      ## The resources.
      self.table = QtWidgets.QTableWidget(0, len(RESOURCE_COLUMNS))
      self.table.setHorizontalHeaderLabels([h for _k, h in RESOURCE_COLUMNS])
      self.table.verticalHeader().setVisible(False)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      ## Cell widgets by row: {key: QComboBox}.
      self.row_widgets = []
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      lay.addWidget(note)
      lay.addWidget(self.budget)
      lay.addWidget(self.table, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add battler...", lambda: self.add_resource(res_model.BATTLER),
                           "Add a battler resource (one pool per battler; its maximum is a stat)"))
      row.addWidget(button("Add move...", lambda: self.add_resource(res_model.MOVE),
                           "Add a move resource (one pool per move slot; every move gets its base field)"))
      row.addWidget(button("Remove", lambda: self.remove_resource(),
                           "Remove the selected one (no move cost or effect logic may name it)"))
      row.addWidget(button("Rename...", lambda: self.rename_resource(), "Rename it; costs and logic follow"))
      row.addWidget(button("Up", lambda: self.move_resource(-1), "Earlier in the payment order"))
      row.addWidget(button("Down", lambda: self.move_resource(1), "Later in the payment order"))
      row.addStretch(1)
      lay.addLayout(row)
      lay.addWidget(self.errors)

   def rows(self) -> list[res_model.ResourceRow]:
      """!The resources as the table shows them.
      @return resource_rows() ([] with nothing open)
      """
      doc = self.battle_doc()
      return res_model.resource_rows(doc) if doc is not None else []

   def _budget_text(self) -> tuple[str, bool]:
      """!The budget line: battler and move resources against each target's caps.
      @return (text, over a cap)
      """
      doc = self.battle_doc()
      if doc is None:
         return "", False
      parts, over = [], False
      for t, battler, most_b, move, most_m in res_model.budget(doc, stat_model.project_targets(doc.path)):
         parts.append(f"{battler}/{most_b} battler, {move}/{most_m} move ({t})")
         over = over or battler > most_b or move > most_m
      formulas, most_f = res_model.formula_count(doc), res_model.max_formulas()
      parts.append(f"{formulas}/{most_f} formulas")
      return "; ".join(parts), over or formulas > most_f

   def _combo(self, items: Sequence[str], current: str, enabled: bool, slot: Callable[[str], object],
              editable: bool = False) -> QtWidgets.QComboBox:
      """!A cell's combo box.
      @param items     choices
      @param current   the text shown (added when missing)
      @param enabled   whether it can be changed
      @param slot      callable(text) on a choice
      @param editable  typing allowed (regen numbers)
      @return QComboBox
      """
      box = QtWidgets.QComboBox()
      box.setEditable(editable)
      box.addItems(list(items) + ([current] if current not in items else []))
      box.setCurrentText(current)
      box.setEnabled(enabled)
      box.activated.connect(lambda _i: slot(box.currentText()))
      if editable:
         box.lineEdit().editingFinished.connect(lambda: slot(box.currentText()))
      return box

   def _row_widgets(self, r: int, row: res_model.ResourceRow) -> dict[str, QtWidgets.QComboBox]:
      """!The combo boxes of one row.
      @param r    table row
      @param row  the resource
      @return {key: QComboBox}
      """
      doc = self.battle_doc()
      name = row["name"]
      battler = row["scope"] == res_model.BATTLER
      formulas = res_model.formula_choices(doc)
      roles = res_model.role_choices(doc, row["scope"], name)

      def setter(key: str) -> Callable[[str], object]:
         """!The slot of a key's combo.
         @param key  resource key
         @return callable(text)
         """
         return lambda text: self.set_resource(name, key, text)

      widgets = {
         "scope": self._combo(res_model.scopes(), str(row["scope"]), True, lambda t: self.set_scope(name, t)),
         "stat": self._combo(res_model.stat_choices(doc) if battler else [NONE_TEXT],
                             str(row["stat"]) if battler else NONE_TEXT, battler, setter("stat")),
         "max": self._combo([NONE_TEXT] + formulas, row["max"] or NONE_TEXT, not battler, setter("max")),
         "raises": self._combo([NONE_TEXT] + roles, row["raises"] or NONE_TEXT, not battler, setter("raises")),
         "persist": self._combo([REFILL_TEXT] + roles, row["persist"] or REFILL_TEXT, True, setter("persist")),
         "empty": self._combo(res_model.empty_rules(), str(row["empty"]), battler, setter("empty")),
         "regen": self._combo([NONE_TEXT] + formulas, NONE_TEXT if row["regen"] is None else str(row["regen"]), True,
                              setter("regen"), editable=True),
      }
      lo, hi = res_model.regen_range()
      widgets["regen"].setToolTip(f"a whole number from {lo} to {hi} (the engine's REGEN_RANGE) or a named formula "
                                  "of (value, max); none: no regen")
      for key, box in widgets.items():
         self.table.setCellWidget(r, RESOURCE_COLUMN[key], box)
      return widgets

   def refresh(self) -> None:
      """!Re-reads the resources.
      @return None
      """
      doc = self.battle_doc()
      rows = self.rows()
      names = [r["name"] for r in rows]
      if self.selected not in names:
         self.selected = names[0] if names else None
      text, over = self._budget_text()
      self._filling = True
      try:
         self.budget.setText(text)
         self.budget.setStyleSheet(f"color: {OVER_COLOR if over else WITHIN_COLOR}; font-weight: bold;")
         self.table.setRowCount(len(rows))
         self.row_widgets = []
         editable = QtCore.Qt.ItemFlag.ItemIsEditable
         for r, row in enumerate(rows):
            texts = {"index": str(row["index"]), "name": str(row["name"]), "label": str(row["label"]),
                     "base": str(row["base"]) if row["base"] is not None else "",
                     "payers": f"{row['payers']} move(s)"}
            for key, value in texts.items():
               item = QtWidgets.QTableWidgetItem(value)
               if key not in TEXT_KEYS or (key == "base" and row["scope"] != res_model.MOVE):
                  item.setFlags(item.flags() & ~editable)
               self.table.setItem(r, RESOURCE_COLUMN[key], item)
            self.row_widgets.append(self._row_widgets(r, row))
         self.table.resizeColumnsToContents()
         if self.selected in names:
            self.table.selectRow(names.index(self.selected))
      finally:
         self._filling = False
      self.table.setEnabled(doc is not None)
      self.show_errors()

   # -- editing ------------------------------------------------------------------------

   def _edit(self, label: str, fn: Callable[[], object]) -> bool:
      """!One edit; a refused one refreshes the table back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      ok = self.edit(label, fn)
      if not ok:
         self.host.changed()
      return ok

   def _selection_changed(self) -> None:
      """!Another row was picked.
      @return None
      """
      if self._filling:
         return
      rows = self.table.selectionModel().selectedRows()
      all_rows = self.rows()
      if rows and rows[0].row() < len(all_rows):
         self.selected = all_rows[rows[0].row()]["name"]

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A name, label or base field was typed.
      @param item  the cell
      @return None
      """
      rows = self.rows()
      if self._filling or not 0 <= item.row() < len(rows):
         return
      row, text = rows[item.row()], item.text().strip()
      if item.column() == RESOURCE_COLUMN["name"] and text != row["name"]:
         self.rename_resource(text, row["name"])
      elif item.column() == RESOURCE_COLUMN["label"] and text != row["label"]:
         self.set_resource(row["name"], "label", text)
      elif item.column() == RESOURCE_COLUMN["base"] and text != (row["base"] or ""):
         self.set_resource(row["name"], "base", text)

   def set_resource(self, name: str, key: str, text: str) -> bool:
      """!Changes one key of a resource from a cell's text (NONE_TEXT / REFILL_TEXT / "": the default).
      @param name  resource name
      @param key   one of core.structure.resources.RESOURCE_KEYS
      @param text  the new value as shown
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if self._filling or doc is None:
         return False
      text = text.strip()
      value = None if text in (NONE_TEXT, REFILL_TEXT, "") else text
      row = next((r for r in self.rows() if r["name"] == name), None)
      if row is not None and (row[key] if row[key] is None else str(row[key])) == value:
         return False   # unchanged
      return self._edit(SET_LABELS[key], lambda: res_model.set_resource(doc, name, key, value))

   def set_scope(self, name: str, scope: str) -> bool:
      """!Changes a resource's scope.
      @param name   resource name
      @param scope  battler or move
      @return True when it changed
      """
      doc = self.battle_doc()
      if self._filling or doc is None:
         return False
      changed = []
      ok = self._edit("Resource scope", lambda: changed.append(res_model.set_scope(doc, name, scope)))
      return ok and changed == [True]

   def add_resource(self, scope: str, name: str | None = None) -> bool:
      """!Adds a resource after the selected one.
      @param scope  battler or move
      @param name   its name, or None to ask
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, f"Add {scope} resource", "Name (lower case):")
         if not ok:
            return False
      names = [r["name"] for r in self.rows()]
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit("Add resource", lambda: res_model.add_resource(doc, name, scope, index=at)):
         self.selected = name.strip()
         return True
      return False

   def remove_resource(self) -> bool:
      """!Removes the selected resource (refused while a move's cost or effect logic names it).
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self._edit("Remove resource", lambda: res_model.remove_resource(doc, name)):
         self.selected = None
         return True
      return False

   def rename_resource(self, new: str | None = None, old: str | None = None) -> bool:
      """!Renames a resource; the moves' costs, its base field, the effect logic and the bench scenarios follow
      (the scenarios rewritten are listed in the status bar).
      @param new  the new name, or None to ask
      @param old  the resource, or None for the selected one
      @return True when renamed
      """
      doc = self.battle_doc()
      old = old or self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename resource", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         self.host.changed()
         return False
      bench = res_model.bench_users(doc, old)
      if self._edit("Rename resource", lambda: res_model.rename_resource(doc, old, new)):
         self.selected = new.strip()
         if bench:
            self.host.show_status(f"bench scenarios follow the rename: {', '.join(bench)}")
         return True
      return False

   def move_resource(self, delta: int) -> bool:
      """!Moves the selected resource up or down the payment order.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      moved = []
      ok = self._edit("Move resource", lambda: moved.append(res_model.move_resource(doc, name, delta)))
      return ok and moved == [True]
