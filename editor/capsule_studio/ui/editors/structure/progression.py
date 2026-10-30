"""!The Progression page of the battle navigator (D-23 §3.2 "Progression";
core.structure.progression): the party size and move slots (the record's;
also on the Record page), what happens when a creature learns a move with
no free slot and which moves a new creature starts with, who shares the
experience of a defeated foe, and the generation list of a new record,
numbered in random-draw order.

The generation table shows each entry's role, how it fills it (a random
range, a constant or a derived expression), the compiled kind (the
engine's GEN_KINDS word: wide_low_first for a wide range drawn low half
first, E13a) and the random draws it takes (their numbers: the draw order
is the list order; DRAWS_PER_KIND). The form below edits the selected
entry: a wide range's draw order (the engine's WIDE_ORDERS; the default
draws the high half first), and a derived expression in a coloured,
completing field (expression_edit.FormulaEdit: the stored roles, the
species' fields species.NAME, the constants, the functions, the bit
operators). For a derived entry the preview runs its expression as the
generated rules::derive() would (the engine's run_derived()) with input
values typed in; picking a species fills its species.NAME inputs from the
compiled data (record_inputs()). Grey values are the engine's defaults; "Engine
default" gives a part back. Every choice comes from the engine's compiler;
an edit it refuses is refused with its message. Every change is one undo
step on the battle manifest.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ....core.document import DocumentError
from ....core.structure import progression as model
from ....core.structure import record
from ...widgets import button, set_enabled
from ..battle_common import NONE_TEXT, STRUCTURE, BattlePanel, set_combo, set_spin
from ..logic.expression_edit import FormulaEdit
from .turn import mark_default

if TYPE_CHECKING:
   from ...panel import PanelHost

## Generation table columns: (key, header).
GEN_COLUMNS = [("index", "#"), ("role", "Role"), ("how", "Fills it with"), ("draws", "Random draws"),
               ("kind", "Kind"), ("error", "Problem")]
## The generation table column that takes the room left.
STRETCH_COLUMN = "how"
## The order combo's entry for "the engine's default order" (no "order" written).
DEFAULT_ORDER_TEXT = "(engine default)"
## Lowest and highest value a preview input spin takes (int32).
INPUT_RANGE = (-(1 << 31), (1 << 31) - 1)
## Most elements a preview's element spin offers (a role holds at most 255 elements: an 8-bit operand).
MAX_ELEMENT = 255
## Stretch of the generation table.
TABLE_STRETCH = 2


class ProgressionPanel(BattlePanel):
   """!Learning, experience, record size and the generation list.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "progression"
   ## See EditorPanel.title.
   title = "Progression"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the page.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Policy combos by dotted key ("learn.on_full", ...).
      self.policy = {}
      top = QtWidgets.QHBoxLayout()
      labels = {"learn.on_full": "No free move slot", "learn.default_moves": "Starting moves",
                "exp_policy.share": "Shared by", "exp_policy.receivers": "Received by",
                "exp_policy.outsider": "Outsider bonus"}
      for part, title in ((model.LEARN_KEY, "Learning moves"), (model.EXP_KEY, "Experience")):
         group = QtWidgets.QGroupBox(title)
         form = QtWidgets.QFormLayout(group)
         for key, label in labels.items():
            if key.startswith(part + "."):
               c = QtWidgets.QComboBox()
               c.activated.connect(lambda _i, k=key, w=c: self.set_policy(k, w.currentText()))
               self.policy[key] = c
               form.addRow(label, c)
         top.addWidget(group)
      group = QtWidgets.QGroupBox("Record (also on the Record page)")
      form = QtWidgets.QFormLayout(group)
      ## Party size.
      self.party_size = QtWidgets.QSpinBox()
      self.party_size.editingFinished.connect(lambda: self.set_record("party_size", self.party_size.value()))
      ## Move slots.
      self.move_slots = QtWidgets.QSpinBox()
      self.move_slots.editingFinished.connect(lambda: self.set_record("move_slots", self.move_slots.value()))
      form.addRow(self.term_label("party", False, "Creatures per {}"), self.party_size)
      form.addRow("Move slots", self.move_slots)
      top.addWidget(group)
      top.addStretch(1)
      ## The generation entries.
      self.table = QtWidgets.QTableWidget(0, len(GEN_COLUMNS))
      self.table.setHorizontalHeaderLabels([h for _k, h in GEN_COLUMNS])
      self.table.verticalHeader().setVisible(False)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.table.itemSelectionChanged.connect(lambda: self._fill_form())
      ## Generation list state ("engine default" or the count against the limit).
      self.gen_state = QtWidgets.QLabel()
      buttons = QtWidgets.QHBoxLayout()
      ## Role of a new entry.
      self.new_role = QtWidgets.QComboBox()
      buttons.addWidget(self.new_role)
      buttons.addWidget(button("Add", lambda: self.add_entry(self.new_role.currentText()),
                               "Add a random entry for the role after the selected one"))
      buttons.addWidget(button("Remove", lambda: self.remove_entry(), "Remove the selected entry"))
      buttons.addWidget(button("Up", lambda: self.move_entry(-1), "Draw earlier"))
      buttons.addWidget(button("Down", lambda: self.move_entry(1), "Draw later"))
      buttons.addWidget(button("Engine default", lambda: self.reset_generation(), "The engine's generation list"))
      buttons.addStretch(1)
      form_box = QtWidgets.QGroupBox("Selected entry")
      form = QtWidgets.QFormLayout(form_box)
      ## The entry's role.
      self.role = QtWidgets.QComboBox()
      self.role.activated.connect(lambda _i: self.set_role(self.role.currentText()))
      form.addRow("Role", self.role)
      ## How the entry fills it.
      self.way = QtWidgets.QComboBox()
      self.way.addItems(list(model.WAYS))
      self.way.activated.connect(lambda _i: self.set_way(self.way.currentText()))
      form.addRow("Fills it with", self.way)
      ## Random range low bound (a number).
      self.lo = QtWidgets.QLineEdit()
      ## Random range high bound (a number, "max", "last").
      self.hi = QtWidgets.QLineEdit()
      for w in (self.lo, self.hi):
         w.editingFinished.connect(lambda: self.set_random(self.lo.text().strip(), self.hi.text().strip()))
      rng = QtWidgets.QHBoxLayout()
      rng.addWidget(self.lo)
      rng.addWidget(QtWidgets.QLabel("to"))
      rng.addWidget(self.hi)
      form.addRow("Random range", rng)
      ## A wide range's draw order (E13a: the engine's WIDE_ORDERS; enabled for a range of two draws).
      self.order = QtWidgets.QComboBox()
      self.order.activated.connect(lambda _i: self._order_chosen())
      self.order.setToolTip("Which half of a wide range (two draws) is drawn first")
      form.addRow("Draw order", self.order)
      ## Constant value.
      self.constant = QtWidgets.QLineEdit()
      self.constant.editingFinished.connect(lambda: self._constant_typed())
      form.addRow("Constant", self.constant)
      ## Derived expression.
      self.expr = FormulaEdit()
      self.expr.editingFinished.connect(lambda: self._derived_typed())
      form.addRow("Derived", self.expr)
      ## Derived range ("lo hi", empty: the role's values).
      self.expr_range = QtWidgets.QLineEdit()
      self.expr_range.setPlaceholderText("the role's values")
      self.expr_range.editingFinished.connect(lambda: self._derived_typed())
      form.addRow("Derived range", self.expr_range)
      ## The names an expression may read.
      self.inputs_note = QtWidgets.QLabel()
      self.inputs_note.setWordWrap(True)
      form.addRow(self.inputs_note)
      preview_box = QtWidgets.QGroupBox("Preview (derived entries: rules::derive())")
      pv = QtWidgets.QVBoxLayout(preview_box)
      ## Input values of the preview.
      self.inputs = QtWidgets.QTableWidget(0, len(("name", "value")))
      self.inputs.setHorizontalHeaderLabels(["Input", "Value"])
      self.inputs.verticalHeader().setVisible(False)
      pv.addWidget(self.inputs)
      species_row = QtWidgets.QHBoxLayout()
      ## The species whose fields (species.NAME) the preview reads.
      self.species = QtWidgets.QComboBox()
      self.species.activated.connect(lambda _i: self._species_chosen())
      species_row.addWidget(QtWidgets.QLabel("Species"))
      species_row.addWidget(self.species, 1)
      pv.addLayout(species_row)
      row = QtWidgets.QHBoxLayout()
      ## The element asked for.
      self.element = QtWidgets.QSpinBox()
      self.element.setRange(0, MAX_ELEMENT)
      row.addWidget(QtWidgets.QLabel("Element"))
      row.addWidget(self.element)
      row.addWidget(button("Run", lambda: self.run_preview(), "Evaluate the expression as the engine would"))
      ## Preview result.
      self.result = QtWidgets.QLabel()
      row.addWidget(self.result, 1)
      pv.addLayout(row)
      lower = QtWidgets.QHBoxLayout()
      lower.addWidget(form_box, 1)
      lower.addWidget(preview_box, 1)
      outer = QtWidgets.QVBoxLayout(self)
      outer.addLayout(top)
      outer.addWidget(QtWidgets.QLabel("Generation of a new record, in random-draw order:"))
      outer.addWidget(self.gen_state)
      outer.addWidget(self.table, TABLE_STRETCH)
      outer.addLayout(buttons)
      outer.addLayout(lower, 1)
      outer.addWidget(self.errors)
      ## Input names the preview table shows.
      self._input_names = []
      ## Row the next refresh selects (an entry just added or moved), or None.
      self._want_row = None

   # -- reading ------------------------------------------------------------------------

   def rows(self) -> list[model.GenRow]:
      """!The generation entries.
      @return generation_rows() ([] with nothing open)
      """
      doc = self.battle_doc()
      return model.generation_rows(doc) if doc is not None else []

   def selected_index(self) -> int:
      """!The selected entry.
      @return its index, or -1
      """
      rows = self.table.selectionModel().selectedRows()
      return rows[0].row() if rows else -1

   def refresh(self) -> None:
      """!Re-reads everything.
      @return None
      """
      self.update_terms()
      doc = self.battle_doc()
      self._filling = True
      try:
         if doc is not None:
            words = model.choices()
            for key, c in self.policy.items():
               part, sub = key.split(".", 1)
               value, left = model.policy(doc, part)
               set_combo(c, words[key], value.get(sub))
               mark_default(c, sub in left)
            self.party_size.setRange(1, record.max_party_size(record.project_targets(doc.path)))
            self.move_slots.setRange(1, record.max_move_slots())
            set_spin(self.party_size, record.party_size(doc))
            set_spin(self.move_slots, record.move_slots(doc))
            self._fill_table(doc)
            self.new_role.clear()
            self.new_role.addItems(model.role_choices(doc))
      except DocumentError as e:   # a project.json naming an unknown platform
         self.host.show_status(str(e))
      finally:
         self._filling = False
      self._fill_form()
      set_enabled(self, doc is not None)
      self.show_errors()

   def _fill_table(self, doc: Any) -> None:
      """!The generation table.
      @param doc  battle Document
      @return None
      """
      current = self.selected_index() if self._want_row is None else self._want_row
      self._want_row = None
      rows = model.generation_rows(doc)
      default = model.is_default(doc)
      self.gen_state.setText(("engine default (the manifest has no generation list)" if default else
                              f"{len(rows)}/{model.max_generation()} entries"))
      mark_default(self.gen_state, default)
      self.table.setRowCount(len(rows))
      for r, row in enumerate(rows):
         text = model.row_text(row)
         how = text.split(": ", 1)[1].split(";")[0] if ": " in text else ""
         draws = text.split("; ")[1] if "; " in text else ""
         cells = {"index": str(row["index"]), "role": str(row["role"]), "how": how, "kind": row["kind"] or "",
                  "draws": draws, "error": row["error"] or ""}
         for c, (key, _h) in enumerate(GEN_COLUMNS):
            item = QtWidgets.QTableWidgetItem(cells[key])
            if key == STRETCH_COLUMN:
               item.setToolTip(cells[key])
            if default:
               item.setForeground(QtCore.Qt.GlobalColor.gray)
            self.table.setItem(r, c, item)
      # the expression column takes the room left (long expressions are elided; the form shows them whole)
      header = self.table.horizontalHeader()
      for c, (key, _h) in enumerate(GEN_COLUMNS):
         mode = QtWidgets.QHeaderView.ResizeMode
         header.setSectionResizeMode(c, mode.Stretch if key == STRETCH_COLUMN else mode.ResizeToContents)
      if rows:
         self.table.selectRow(min(max(current, 0), len(rows) - 1))

   def _fill_form(self) -> None:
      """!Shows the selected entry.
      @return None
      """
      doc = self.battle_doc()
      rows = self.rows()
      i = self.selected_index()
      row = rows[i] if 0 <= i < len(rows) else None
      way = row["way"] if row is not None else None
      for w in (self.role, self.way):
         w.setEnabled(row is not None)
      for w in (self.lo, self.hi):
         w.setEnabled(way == model.RANDOM_WAY)
      self.order.setEnabled(row is not None and bool(row["wide"]))
      self.constant.setEnabled(way == model.CONSTANT_WAY)
      for w in (self.expr, self.expr_range, self.inputs, self.element, self.species):
         set_enabled(w, way == model.DERIVED_WAY)   # the inputs table goes read-only and keeps its scroll bar
      blocked = [self.role, self.way, self.lo, self.hi, self.order, self.constant, self.expr, self.expr_range]
      for w in blocked:
         w.blockSignals(True)
      try:
         if row is None or doc is None:
            for w in (self.lo, self.hi, self.constant, self.expr, self.expr_range):
               w.setText("")
            return
         set_combo(self.role, model.role_choices(doc), row["role"])
         set_combo(self.way, list(model.WAYS), way)
         self.lo.setText("" if row["lo"] is None else str(row["lo"]))
         self.hi.setText("" if row["hi"] is None else str(row["hi"]))
         set_combo(self.order, [DEFAULT_ORDER_TEXT] + model.wide_orders(), row["order"] or DEFAULT_ORDER_TEXT)
         self.order.setToolTip(f"Which half of a wide range is drawn first (default {model.default_wide_order()})")
         self.constant.setText("" if row["value"] is None else str(row["value"]))
         self.expr.setText(row["expr"] or "")
         self.expr_range.setText(" ".join(str(v) for v in row["range"]) if row["range"] else "")
      finally:
         for w in blocked:
            w.blockSignals(False)
      if way == model.DERIVED_WAY:
         self._fill_inputs(doc)

   def _fill_inputs(self, doc: Any) -> None:
      """!The preview's input table (the layout's inputs; values typed in are kept).
      @param doc  battle Document
      @return None
      """
      names = [n for n in model.derived_inputs(doc) if n != model.element_input()]
      constants = model.derived_constants(doc)
      self.inputs_note.setText("Reads: " + ", ".join(model.derived_inputs(doc)) + ". Constants: " +
                               ", ".join(constants))
      self.expr.set_names(model.derived_names(doc))
      keep = self.species.currentText()
      species = [NONE_TEXT] + model.species_names(doc)
      set_combo(self.species, species, keep if keep in species else NONE_TEXT)
      if names == self._input_names:
         return
      self._input_names = names
      self.inputs.setRowCount(len(names))
      for r, n in enumerate(names):
         item = QtWidgets.QTableWidgetItem(n)
         item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
         self.inputs.setItem(r, 0, item)
         s = QtWidgets.QSpinBox()
         s.setRange(*INPUT_RANGE)
         self.inputs.setCellWidget(r, 1, s)
      self.inputs.resizeColumnsToContents()
      self._species_chosen()   # the species.NAME inputs start at the picked species' values (or the defaults)

   def species_name(self) -> str | None:
      """!The species the preview reads the fields of.
      @return its name, or None (the fields' defaults)
      """
      text = self.species.currentText()
      return None if not text or text == NONE_TEXT else text

   def _species_chosen(self) -> None:
      """!A species was picked: its field values fill the species.NAME inputs (the engine's record_inputs()).
      @return None
      """
      doc = self.battle_doc()
      if doc is None:
         return
      for name, value in model.species_values(doc, self.species_name()).items():
         if name in self._input_names:
            self.inputs.cellWidget(self._input_names.index(name), 1).setValue(value)

   def set_species(self, name: str | None) -> bool:
      """!Picks the preview's species (headless tests).
      @param name  species name, or None for the fields' defaults
      @return True when it is one of the choices
      """
      text = NONE_TEXT if name is None else name
      i = self.species.findText(text)
      if i < 0:
         return False
      self.species.setCurrentIndex(i)
      self._species_chosen()
      return True

   def input_values(self) -> dict[str, int]:
      """!The preview inputs typed in.
      @return name -> value
      """
      return {n: self.inputs.cellWidget(r, 1).value() for r, n in enumerate(self._input_names)}

   def set_input(self, name: str, value: int) -> bool:
      """!Types a preview input value (an input the selected entry does not read is refused: the result line says
      which it reads).
      @param name   input name
      @param value  its value
      @return True when the input exists
      """
      names = self._input_names   # a local name: Doxygen 1.12 misreads membership tests on self.x
      if name not in names:
         self.result.setText(f"no input {name!r} (inputs: {', '.join(names) or 'none'})")
         return False
      self.inputs.cellWidget(names.index(name), 1).setValue(value)
      return True

   def run_preview(self) -> int | None:
      """!Runs the selected derived entry with the typed inputs.
      @return the value, or None when it cannot run
      """
      doc, i = self.battle_doc(), self.selected_index()
      if doc is None or i < 0:
         return None
      try:
         v = model.preview(doc, i, self.input_values(), self.element.value(), self.species_name())
      except DocumentError as e:
         self.result.setText(str(e))
         return None
      self.result.setText(f"= {v}")
      return v

   # -- editing ------------------------------------------------------------------------

   def _run(self, label: str, fn: Any) -> bool:
      """!One edit; a refused one refreshes the page back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      if self._filling:
         return False
      ok = self.edit(label, fn)
      if not ok:
         self.host.changed()
      return ok

   def set_policy(self, key: str, value: str | None) -> bool:
      """!Sets a learn / experience word.
      @param key    dotted key
      @param value  its word, or None
      @return True when it went through
      """
      doc = self.battle_doc()
      return self._run("Progression", lambda: model.set_policy(doc, key, value))

   def set_record(self, key: str, value: int) -> bool:
      """!Sets the party size or the move slots.
      @param key    "party_size" or "move_slots"
      @param value  the value
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if key == "party_size":
         if value == record.party_size(doc):
            return False
         targets = record.project_targets(doc.path)
         return self._run("Party size", lambda: record.set_party_size(doc, value, targets))
      if value == record.move_slots(doc):
         return False
      return self._run("Move slots", lambda: record.set_move_slots(doc, value))

   def add_entry(self, role: str, way: str = model.RANDOM_WAY) -> bool:
      """!Adds an entry after the selected one.
      @param role  the role
      @param way   one of model.WAYS
      @return True when it went through
      """
      doc, i = self.battle_doc(), self.selected_index()
      at = i + 1 if i >= 0 else None
      ok = self._run("Add generation entry", lambda: model.add_entry(doc, role, way, at))
      if ok:
         self._want_row = at if at is not None else len(self.rows()) - 1
      return ok

   def remove_entry(self) -> bool:
      """!Removes the selected entry.
      @return True when it went through
      """
      doc, i = self.battle_doc(), self.selected_index()
      return i >= 0 and self._run("Remove generation entry", lambda: model.remove_entry(doc, i))

   def move_entry(self, delta: int) -> bool:
      """!Moves the selected entry in draw order.
      @param delta  -1 earlier, +1 later
      @return True when it went through
      """
      doc, i = self.battle_doc(), self.selected_index()
      ok = i >= 0 and self._run("Move generation entry", lambda: model.move_entry(doc, i, delta))
      if ok:
         self._want_row = i + delta
      return ok

   def reset_generation(self) -> bool:
      """!Gives the list back to the engine.
      @return True when it went through
      """
      doc = self.battle_doc()
      return self._run("Engine generation", lambda: model.reset_generation(doc))

   def _entry_edit(self, label: str, fn: Any) -> bool:
      """!An edit of the selected entry.
      @param label  undo label
      @param fn     callable(doc, index)
      @return True when it went through
      """
      doc, i = self.battle_doc(), self.selected_index()
      return i >= 0 and self._run(label, lambda: fn(doc, i))

   def set_role(self, role: str) -> bool:
      """!The selected entry's role.
      @param role  the role
      @return True when it went through
      """
      return self._entry_edit("Generation role", lambda doc, i: model.set_role(doc, i, role))

   def set_way(self, way: str) -> bool:
      """!How the selected entry fills its role.
      @param way  one of model.WAYS
      @return True when it went through
      """
      return self._entry_edit("Generation way", lambda doc, i: model.set_way(doc, i, way))

   def set_random(self, lo: str, hi: str) -> bool:
      """!The selected random entry's range.
      @param lo  lowest (a number)
      @param hi  highest (a number, "max" or "last")
      @return True when it went through
      """
      return self._entry_edit("Generation range", lambda doc, i: model.set_random(doc, i, lo, hi))

   def _order_chosen(self) -> None:
      """!A draw order was picked.
      @return None
      """
      text = self.order.currentText()
      self.set_order(None if text == DEFAULT_ORDER_TEXT else text)

   def set_order(self, order: str | None) -> bool:
      """!The selected wide range's draw order.
      @param order  one of the engine's WIDE_ORDERS, or None for its default
      @return True when it went through
      """
      return self._entry_edit("Generation draw order", lambda doc, i: model.set_order(doc, i, order))

   def _constant_typed(self) -> None:
      """!A constant was typed.
      @return None
      """
      text = self.constant.text().strip()
      if not text.isdigit():
         self.host.show_status("A constant is a whole number.")
         self.host.changed()
         return
      self.set_constant(int(text))

   def set_constant(self, value: int) -> bool:
      """!The selected constant entry's value.
      @param value  the value
      @return True when it went through
      """
      return self._entry_edit("Generation constant", lambda doc, i: model.set_constant(doc, i, value))

   def _derived_typed(self) -> None:
      """!The expression or its range was typed.
      @return None
      """
      parts = self.expr_range.text().split()
      if parts and (len(parts) != len(("lo", "hi")) or not all(p.lstrip("-").isdigit() for p in parts)):
         self.host.show_status("The range is two whole numbers (or empty: the role's values).")
         self.host.changed()
         return
      self.set_derived(self.expr.text(), [int(p) for p in parts] if parts else None)

   def set_derived(self, expr: str, rng: list[int] | None = None) -> bool:
      """!The selected derived entry's expression and range.
      @param expr  the expression
      @param rng   [lo, hi], or None for the role's values
      @return True when it went through
      """
      return self._entry_edit("Generation expression", lambda doc, i: model.set_derived(doc, i, expr, rng))
