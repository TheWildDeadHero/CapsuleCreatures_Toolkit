"""!The Moves panel: type, category, power, accuracy, priority, target,
flags (one box per flag the manifest declares in "move_flags"), critical
stage, the base of each move resource (one spin per resource, D-25: e.g. PP)
and the cost (one row per resource: a number or a named ruleset formula; a
move without its own cost pays the engine's default, shown greyed). What a
move does is its effect logic (its block in the battle's .ceffect sources,
core.logic), edited in the Logic group's Effects panel; the form says so.

Every widget follows the compiled structure (S11, D-22 A15): types,
categories, targets and flags are the data's and the engine's lists, the
accuracy, power, priority and base ranges the compiler's, the crit stage up to
the crit stage's highest, one base spin and cost row per resource.

It edits the host's BattleProject (core.battle) through host.run_edit(); the
engine's battle compiler checks the values and its message shows under the
form.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core import engine, holders
from ....core.document import DocumentError
from ....core.structure import categories as cat_model
from ....core.structure import resources, stages
from ...widgets import button
from ..record_widgets import PointHandlersBox
from ..battle_common import EntryPanel, combo, set_check, set_combo, set_spin, set_spin_max, spin

if TYPE_CHECKING:
   from ..battle_common import JsonDict

## The target a move without one has (the engine's first: battlec content.TARGETS[0]).
DEFAULT_TARGET_INDEX = 0
## Cost table columns: resource, amount (number or formula), where the amount comes from.
COST_HEADINGS = ("Resource", "Cost", "From")
## Cost table column of the amount.
COST_COLUMN = 1
## Cost table column saying where the amount comes from.
FROM_COLUMN = 2
## "From" text of an amount the move states.
FROM_MOVE = "this move"
## "From" text of the engine's default amount (the move states no cost).
FROM_DEFAULT = "default"
## "From" text of a default amount of nothing (a battler resource the move states no cost of: S17, the Gen-3 hp row
## read "0 / default").
FROM_FREE = "default: pays nothing"
## Colour of a default amount.
DEFAULT_COLOR = "#808080"
## Height of one cost table row, pixels (the table is as tall as its rows).
COST_ROW_HEIGHT = 30
## Cost table note of the fallback move (rules.fallback_move pays nothing: D-25 decision 4).
FALLBACK_NOTE = "the fallback move (rules.fallback_move) pays nothing"
## Where a move's logic is edited (the effect list of old battle data is gone: E4c, D-23 §1.6).
LOGIC_POINTER = ("What the move does is its effect logic: its block in the battle's .ceffect sources. Edit it in "
                 "Logic > Effects (or with: battle FILE effect show|set \"move:NAME\").")


def targets() -> list[str]:
   """!The move targets, in capsule::battle::Target order (the engine's battle_compiler.TARGETS).
   @return names
   """
   return list(engine.tool("battle_compiler").TARGETS)


def max_power() -> int:
   """!Highest move power (MoveData::power is 16 bits: the compiler's U16_MAX).
   @return the value
   """
   return int(engine.tool("battle_compiler").U16_MAX)


def max_accuracy() -> int:
   """!Highest accuracy, percent (the compiler's PERCENT; also the accuracy of a move that states none).
   @return the value
   """
   return int(engine.tool("battle_compiler").PERCENT)


def max_priority() -> int:
   """!Highest priority bracket (the compiler's MAX_PRIORITY; the lowest is its negative).
   @return the value
   """
   return int(engine.tool("battle_compiler").MAX_PRIORITY)


def max_base() -> int:
   """!Highest base of a move resource (a move field is a byte: the engine's STORAGE_MAX of the move scope).
   @return the value
   """
   return resources.storage_max(resources.MOVE)


class MovesPanel(EntryPanel):
   """!Moves: numbers, targeting and flags (the logic: Logic > Effects)."""

   ## See EditorPanel.panel_id.
   panel_id = "moves"
   ## See EditorPanel.title.
   title = "Moves"
   ## See EntryPanel.kind.
   kind = "moves"
   ## See BattlePanel.title_kind.
   title_kind = "moves"

   def build_form(self, layout: QtWidgets.QVBoxLayout) -> None:
      """!Move fields and the pointer to the move's logic.
      @param layout  QVBoxLayout
      @return None
      """
      ## Type.
      self.type_box = combo(lambda t: self.set_field("type", t))
      ## Category.
      self.category = combo(lambda t: self.set_field("category", t))
      ## Power.
      self.power = spin(0, max_power(), lambda v: self.set_field("power", v))
      ## Accuracy percent.
      self.accuracy = spin(1, max_accuracy(), lambda v: self.set_field("accuracy", v))
      ## Never misses.
      self.never = QtWidgets.QCheckBox("never misses")
      self.never.toggled.connect(lambda on: self.set_field("accuracy", None if on else self.accuracy.value(),
                                                           "Accuracy", True))
      ## Base spin per move resource ({resource: QSpinBox}), rebuilt when the resources change.
      self.bases = {}
      ## The row holding the base spins.
      self.base_row = QtWidgets.QHBoxLayout()
      ## The cost of each resource: name, an editable amount (number or formula) and where it comes from.
      self.cost_table = QtWidgets.QTableWidget(0, len(COST_HEADINGS))
      self.cost_table.setHorizontalHeaderLabels(list(COST_HEADINGS))
      self.cost_table.verticalHeader().setVisible(False)
      self.cost_table.horizontalHeader().setStretchLastSection(True)
      ## Amount combos by resource (editable; their items are the ruleset's two-argument formulas).
      self.cost_boxes = {}
      ## Drops the move's own cost.
      self.cost_reset = button("Default cost", lambda: self.reset_cost(),
                               f"The move pays the engine's default: {resources.default_cost()} of every move "
                               "resource")
      ## Priority bracket.
      self.priority = spin(-max_priority(), max_priority(), lambda v: self.set_field("priority", v))
      ## Targeting.
      self.target = combo(lambda t: self.set_field("target", t))
      ## Crit stage (up to the crit stage's highest once data is open: stages.crit_max(); none without data).
      self.crit = spin(0, 0, lambda v: self.set_field("crit_stage", v))
      ## Flag check boxes, one per flag the manifest declares (its "move_flags"), rebuilt when they change.
      self.flags = {}
      ## The row holding the flag boxes.
      self.flag_row = QtWidgets.QHBoxLayout()
      flag_row = self.flag_row
      acc_row = QtWidgets.QHBoxLayout()
      acc_row.addWidget(self.accuracy)
      acc_row.addWidget(self.never)
      form = QtWidgets.QFormLayout()
      form.addRow(self.term_label("type"), self.type_box)
      form.addRow(self.term_label("category"), self.category)
      form.addRow("Power", self.power)
      form.addRow("Accuracy %", acc_row)
      form.addRow("Bases", self.base_row)
      form.addRow("Priority", self.priority)
      form.addRow("Target", self.target)
      form.addRow("Crit stage", self.crit)
      form.addRow("Flags", flag_row)
      cost_box = QtWidgets.QVBoxLayout()
      cost_box.addWidget(self.cost_table)
      cost_box.addWidget(self.cost_reset, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
      form.addRow("Cost", cost_box)
      layout.addLayout(form)
      ## Where the move's logic is edited.
      self.logic_note = QtWidgets.QLabel(LOGIC_POINTER)
      self.logic_note.setWordWrap(True)
      layout.addWidget(self.logic_note)
      ## The move's point handlers (E13b: `point NAME` members of its logic, e.g. a power or move_type handler).
      self.handlers = PointHandlersBox(lambda label, fn: self.edit(label, fn), lambda: self.battle_doc(),
                                       in_logic=True)
      layout.addWidget(self.handlers)
      layout.addStretch(1)

   def _flags_changed(self) -> None:
      """!A flag box was toggled: the checked flags in the manifest's order, then the flags the move has that the
      manifest does not declare (kept as they are; the compiler names them).
      @return None
      """
      e = self.current() or {}
      undeclared = [f for f in (e.get("flags") or []) if f not in self.flags]
      self.set_field("flags", [f for f, b in self.flags.items() if b.isChecked()] + undeclared, "Set flags")

   def _show_flags(self, names: list[str]) -> None:
      """!Makes one check box per declared move flag (keeps the boxes while the names stay the same).
      @param names  the manifest's move flags, in order
      @return None
      """
      if list(self.flags) == names:
         return
      for box in self.flags.values():
         self.flag_row.removeWidget(box)
         box.hide()   # out of sight at once (the deletion waits for the event loop)
         box.deleteLater()
      self.flags = {}
      for f in names:
         box = QtWidgets.QCheckBox(f)
         box.toggled.connect(lambda _on: self._flags_changed())
         self.flags[f] = box
         self.flag_row.addWidget(box)

   def fill_form(self, entry: JsonDict | None) -> None:
      """!Shows a move.
      @param entry  move dict or None
      @return None
      """
      p = self.project()
      on = entry is not None
      for w in (self.type_box, self.category, self.power, self.accuracy, self.never, self.priority, self.target,
                self.crit, self.cost_table, self.cost_reset):
         w.setEnabled(on)
      e = entry or {}
      set_combo(self.type_box, p.names("types") if p else [], e.get("type"))
      categories = p.names("categories") if p else []
      # the category it compiles to: its own, its type's (category_by_type, E11) or the first
      set_combo(self.category, categories, cat_model.category_of(p.battle, e) if p and on else None)
      set_spin(self.power, e.get("power", 0))
      acc = e.get("accuracy", max_accuracy())   # None (JSON null): never misses
      set_check(self.never, acc is None)
      set_spin(self.accuracy, acc if acc is not None else max_accuracy())
      self.accuracy.setEnabled(on and acc is not None)
      set_spin(self.priority, e.get("priority", 0))
      names = targets()
      set_combo(self.target, names, e.get("target", names[DEFAULT_TARGET_INDEX]))
      set_spin_max(self.crit, stages.crit_max(p.battle) if p else 0)
      set_spin(self.crit, e.get("crit_stage", 0))
      declared = p.structure.data.get("move_flags") if p else None
      self._show_flags([f for f in declared if isinstance(f, str)] if isinstance(declared, list) else [])
      for f, box in self.flags.items():
         set_check(box, f in (e.get("flags") or []))
         box.setEnabled(on)
      self._fill_resources(e if on else None)
      self._fill_handlers(e.get("name") if on else None)

   def _fill_handlers(self, name: str | None) -> None:
      """!Shows the move's point handlers (none while a source does not parse: the Effects page shows why).
      @param name  move name, or None
      @return None
      """
      doc, p = self.battle_doc(), self.project()
      key = type(self).kind   # the moves list (a local name: Doxygen 1.9.8 misreads a "self.kind" argument)
      if doc is None or p is None or not isinstance(name, str):
         self.handlers.show_handlers(None, [], [])
         return
      try:
         rows = holders.handlers(doc, key, name)
      except DocumentError:
         self.handlers.show_handlers(None, [], [])
         return
      self.handlers.show_handlers((key, name), rows, holders.point_choices(p, key))

   # -- resources (D-25) ---------------------------------------------------------------

   def _show_bases(self, rows: list[dict]) -> None:
      """!Makes one spin per move resource (keeps them while the resources stay the same).
      @param rows  core.structure.resources.base_rows() of the move (or of no move: [])
      @return None
      """
      names = [r["resource"] for r in rows]
      if list(self.bases) == names:
         return
      while self.base_row.count():
         item = self.base_row.takeAt(0)
         if item.widget() is not None:
            item.widget().hide()   # out of sight at once (the deletion waits for the event loop)
            item.widget().deleteLater()
      self.bases = {}
      for r in rows:
         self.base_row.addWidget(QtWidgets.QLabel(r["resource"]))
         box = spin(0, max_base(), lambda v, n=r["resource"]: self.set_base(n, v))
         box.setToolTip(f"the move's {r['field']!r} field: the base of the move resource {r['resource']!r}")
         self.bases[r["resource"]] = box
         self.base_row.addWidget(box)
      self.base_row.addStretch(1)

   def _fill_resources(self, entry: JsonDict | None) -> None:
      """!Shows the move's bases and cost.
      @param entry  move dict or None
      @return None
      """
      doc = self.battle_doc()
      name = entry.get("name") if entry is not None else None
      have = doc is not None and isinstance(name, str)
      move_rows = resources.resource_rows(doc) if doc is not None else []
      blank = [{"resource": r["name"], "field": r["base"], "value": None} for r in move_rows
               if r["scope"] == resources.MOVE]
      base_rows = resources.base_rows(doc, name) if have else blank
      self._show_bases(base_rows)
      for r in base_rows:
         box = self.bases[r["resource"]]
         set_spin(box, r["value"] if r["value"] is not None else 0)
         box.setEnabled(have)
      costs = resources.cost_rows(doc, name) if have else []
      formulas = resources.formula_choices(doc) if doc is not None else []
      # rules.fallback_move pays nothing (D-25): its cost cannot be edited
      fallback = any(row["fallback"] for row in costs)
      # The boxes of the last fill are replaced (and deleted) below: their signals must not reach a deleted box
      # (a focus change after the rebuild would end its editing): cut them off first.
      for old in self.cost_boxes.values():
         old.activated.disconnect()
         old.lineEdit().editingFinished.disconnect()
      self.cost_table.setRowCount(len(costs))
      self.cost_boxes = {}
      for i, row in enumerate(costs):
         label = QtWidgets.QTableWidgetItem(f"{row['resource']} ({row['scope']})")
         label.setFlags(label.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
         self.cost_table.setItem(i, 0, label)
         box = QtWidgets.QComboBox()
         box.setEditable(True)
         box.addItems(formulas)
         # a default amount shows as the box's placeholder (what the move pays when it states nothing)
         box.setCurrentText("" if row["default"] and not fallback else str(row["amount"]))
         box.lineEdit().setPlaceholderText(str(row["amount"]))
         box.setToolTip(FALLBACK_NOTE if fallback else
                        "a whole number (0: free) or a named formula of (value, max); empty: the default")
         box.setEnabled(not fallback)
         if row["default"] or fallback:
            box.setStyleSheet(f"color: {DEFAULT_COLOR};")
         # The page (a stable owner) looks the box up when the signal comes: no reference to a box held here.
         box.activated.connect(lambda _i, n=row["resource"]: self.commit_cost(n))
         box.lineEdit().editingFinished.connect(lambda n=row["resource"]: self.commit_cost(n))
         self.cost_table.setCellWidget(i, COST_COLUMN, box)
         self.cost_boxes[row["resource"]] = box
         free = row["default"] and row["amount"] == 0
         source = QtWidgets.QTableWidgetItem(FALLBACK_NOTE if fallback else FROM_FREE if free else
                                             (FROM_DEFAULT if row["default"] else FROM_MOVE))
         source.setFlags(source.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
         self.cost_table.setItem(i, FROM_COLUMN, source)
      self.cost_table.resizeColumnsToContents()
      self.cost_table.setFixedHeight(COST_ROW_HEIGHT * (len(costs) + 1))
      # (a fallback move stating a cost, which the engine refuses, can still drop it)
      self.cost_reset.setEnabled(have and not all(r["default"] for r in costs))

   def set_base(self, resource: str, value: int) -> None:
      """!Sets the selected move's base of a move resource.
      @param resource  move resource name
      @param value     the base
      @return None
      """
      doc = self.battle_doc()
      if self._filling or doc is None or self.selected is None:
         return
      field = next((r["field"] for r in resources.base_rows(doc, self.selected) if r["resource"] == resource), None)
      if field is not None:
         self.set_field(field, value, f"Set {resource} base")

   def commit_cost(self, resource: str) -> bool:
      """!A cost box finished editing: sets the cost it shows (the current box of that resource; none: nothing).
      @param resource  resource name
      @return True when the edit went through
      """
      box = self.cost_boxes.get(resource)
      return self.set_cost(resource, box.currentText()) if box is not None else False

   def set_cost(self, resource: str, text: str) -> bool:
      """!Sets what the selected move pays of a resource.
      @param resource  resource name
      @param text      a number, a named formula, or "" for the default
      @return True when the edit went through
      """
      doc, move = self.battle_doc(), self.selected
      if self._filling or doc is None or move is None:
         return False
      text = text.strip()
      row = next((r for r in resources.cost_rows(doc, move) if r["resource"] == resource), None)
      if row is not None and (str(row["amount"]) == text or (row["default"] and not text)):
         return False   # unchanged (also: a default amount re-committed, or its empty box)
      amount = text if text else None
      ok = self.edit(f"Set {resource} cost", lambda: resources.set_cost(doc, move, resource, amount))
      if not ok:
         self.host.changed()
      return ok

   def reset_cost(self) -> bool:
      """!The selected move pays the default cost again.
      @return True when it had its own cost
      """
      doc, move = self.battle_doc(), self.selected
      if doc is None or move is None:
         return False
      done = []
      return self.edit("Default cost", lambda: done.append(resources.reset_cost(doc, move))) and done == [True]
