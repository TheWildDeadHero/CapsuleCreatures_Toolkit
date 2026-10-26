"""!The Formulas panel: the ruleset's formula slots and stat formulas with
their analysed ranges, editable in place, and an evaluator that runs a
formula as the generated C++ does.

Expressions are coloured and completed (expression_edit.FormulaEdit /
FormulaDelegate, engine E13a: the bit operators & | ^ ~ << >> bind tighter
than the comparisons; the tool tip gives every level): the formula's
inputs, the ruleset's constants and the language's functions; a name the
formula does not take shows red. When the ruleset does not compile, the
row the engine's message names (an unknown name, a shift amount outside
0-SHIFT_MAX, an overflow) is marked and its Analysed cell gives the message.

It edits the ruleset Document of the host's BattleProject (core.battle), so
Undo / Redo on this page act on the ruleset.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import battle, expressions
from ...widgets import button
from ..battle_common import BattlePanel
from .expression_edit import FormulaDelegate

if TYPE_CHECKING:
   from ....core.document import Document
   from ...panel import PanelHost

## Columns of the formula table: slot, expression, lowest, highest, analysed range.
FORMULA_COLUMNS = 5
## Formula table column of the slot name (read only).
SLOT_COLUMN = 0
## Formula table column of the expression.
EXPR_COLUMN = 1
## Formula table column of the declared lowest value.
LO_COLUMN = 2
## Formula table column of the declared highest value.
HI_COLUMN = 3
## Formula table column of the analysed range (read only).
ANALYSED_COLUMN = 4
## Item data role holding a row's formula name.
SLOT_ROLE = QtCore.Qt.ItemDataRole.UserRole
## Index of "the clamp is active" in a ruleset_report() row.
REPORT_CLAMPS = 3
## Range of an evaluator input whose formula declares none.
DEFAULT_INPUT_RANGE = (0, 9999)
## Value an evaluator input starts at (clamped to its range).
DEFAULT_INPUT_VALUE = 50
## Background of the row the ruleset's compile error names.
ERROR_BACKGROUND = "#f6d5d5"
## Analysed cell of the row the compile error names.
ERROR_TEXT = "error (see tool tip)"


def error_slot(error: str | None, slots: list[str]) -> str | None:
   """!The formula a ruleset compile error names (the engine's messages say "...: SLOT: ..." or
   "stat_formulas.NAME").
   @param error  the message, or None
   @param slots  the formula names
   @return the slot, or None
   """
   if not error:
      return None
   for slot in sorted(slots, key=len, reverse=True):
      if f": {slot}:" in error or f"stat_formulas.{slot}" in error or f"formulas.{slot}" in error:
         return slot
   return None


class RulesPanel(BattlePanel):
   """!Ruleset formulas (the formula slots and the stat formulas) with their analysed ranges, and an
   evaluator.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "rules"
   ## See EditorPanel.title.
   title = "Formulas"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the formula table and the evaluator.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Formula rows: slot, expression, lo, hi, analysed.
      self.table = QtWidgets.QTableWidget(0, FORMULA_COLUMNS)
      self.table.setHorizontalHeaderLabels(["Formula", "Expression", "Lowest", "Highest", "Analysed range"])
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      ## Coloured, completed expression cells.
      self.delegate = FormulaDelegate(lambda index: self.names_of(index.row()), self.table)
      self.table.setItemDelegateForColumn(EXPR_COLUMN, self.delegate)
      ## The formula the ruleset's compile error names, or None.
      self.error_slot = None
      ## Evaluator slot.
      self.slot = QtWidgets.QComboBox()
      self.slot.currentIndexChanged.connect(lambda *a: self._build_inputs())
      ## Evaluator inputs.
      self.inputs_box = QtWidgets.QHBoxLayout()
      ## Input spins by name.
      self.input_spins = {}
      ## (slot, input ranges) the spins were built for.
      self._inputs_for = None
      ## Evaluation result.
      self.result = QtWidgets.QLabel()
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(QtWidgets.QLabel("Formulas are integer expressions (see the engine's ruleset_compiler.py). "
                                     "The engine refuses any formula that could overflow or divide by zero."))
      lay.addWidget(self.table, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Try"))
      row.addWidget(self.slot)
      row.addLayout(self.inputs_box, 1)
      row.addWidget(button("Evaluate", lambda: self.evaluate()))
      row.addWidget(self.result)
      lay.addLayout(row)
      lay.addWidget(self.errors)

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the ruleset.
      @return Document, or None
      """
      p = self.project()
      return p.ruleset if p is not None else None

   def names_of(self, row: int) -> expressions.Names | None:
      """!What a row's formula may name.
      @param row  table row
      @return core.expressions.Names, or None
      """
      p = self.project()
      item = self.table.item(row, SLOT_COLUMN)
      if p is None or item is None:
         return None
      return expressions.formula_names(p, str(item.data(SLOT_ROLE)))

   def refresh(self) -> None:
      """!Re-reads the formulas and their analysis.
      @return None
      """
      p = self.project()
      self._filling = True
      try:
         rows, error = p.ruleset_report() if p is not None else ([], None)
         analysed = {r[0]: r for r in rows}
         slots = p.formula_slots() if p is not None else []
         self.error_slot = error_slot(error, slots)
         self.table.setRowCount(len(slots))
         for r, slot in enumerate(slots):
            f = battle.formula_entry(p.ruleset, slot)
            rng = f.get("range", [0, 0])
            cells = [slot, f.get("expr", ""), str(rng[0]), str(rng[1])]
            a = analysed.get(slot)
            cells.append(f"[{a[1][0]}, {a[1][1]}]" + (" clamps" if a[REPORT_CLAMPS] else "") if a else "")
            if slot == self.error_slot:
               cells[ANALYSED_COLUMN] = ERROR_TEXT
            for c, text in enumerate(cells):
               item = QtWidgets.QTableWidgetItem(text)
               item.setData(SLOT_ROLE, slot)
               if c in (SLOT_COLUMN, ANALYSED_COLUMN):
                  item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
               if slot == self.error_slot:
                  item.setBackground(QtGui.QColor(ERROR_BACKGROUND))
                  item.setToolTip(error)
               self.table.setItem(r, c, item)
         self.table.resizeColumnsToContents()
         if self.slot.count() != len(slots):
            self.slot.clear()
            self.slot.addItems(slots)
      finally:
         self._filling = False
      self._build_inputs()
      self.result.setText("")   # formulas may have changed
      p_err = error if p is not None else None
      if p_err:
         self.errors.setText(f"Ruleset: {p_err}")
         self.errors.setStyleSheet("color: #c03030;")
      else:
         self.show_errors()

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!An expression or range cell was edited.
      @param item  QTableWidgetItem
      @return None
      """
      if self._filling:
         return
      p = self.project()
      if p is None:
         return
      slot = self.table.item(item.row(), SLOT_COLUMN).data(SLOT_ROLE)
      text = item.text().strip()
      col = item.column()
      doc = p.ruleset
      try:
         if col == EXPR_COLUMN:
            fn = lambda: battle.set_formula(doc, slot, expr=text)   # noqa: E731
         elif col == LO_COLUMN:
            v = int(text)
            fn = lambda: battle.set_formula(doc, slot, lo=v)   # noqa: E731
         elif col == HI_COLUMN:
            v = int(text)
            fn = lambda: battle.set_formula(doc, slot, hi=v)   # noqa: E731
         else:
            return
      except ValueError:
         self.host.show_status("Ranges are whole numbers.")
         self.host.changed()   # refreshes the table: the cell shows the stored value again
         return
      self.host.run_edit("Formula", fn, doc)

   def _build_inputs(self) -> None:
      """!Input spins for the chosen slot.
      @return None
      """
      p = self.project()
      inputs = p.formula_inputs(self.slot.currentText()) if p is not None and self.slot.currentText() else []
      key = (self.slot.currentText(), tuple(inputs))
      if key == self._inputs_for:
         return   # keep the values typed in
      self._inputs_for = key
      self.result.setText("")
      while self.inputs_box.count():
         w = self.inputs_box.takeAt(0).widget()
         if w is not None:
            w.deleteLater()
      self.input_spins = {}
      for name, rng in inputs:
         label = QtWidgets.QLabel(name)
         s = QtWidgets.QSpinBox()
         lo, hi = rng if rng else DEFAULT_INPUT_RANGE
         s.setRange(lo, hi)
         s.setValue(max(lo, min(hi, DEFAULT_INPUT_VALUE)))
         self.inputs_box.addWidget(label)
         self.inputs_box.addWidget(s)
         self.input_spins[name] = s

   def evaluate(self) -> None:
      """!Evaluates the chosen formula.
      @return None
      """
      p = self.project()
      if p is None:
         return
      try:
         v = p.formula(self.slot.currentText(), **{k: s.value() for k, s in self.input_spins.items()})
         self.result.setText(f"= {v}")
      except Exception as e:   # DocumentError
         self.result.setText(str(e))
