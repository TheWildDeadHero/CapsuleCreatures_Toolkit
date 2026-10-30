"""!The Growth & training page (D-26 section 4, engine G4): the structure
manifest's "transformation" and "training" sections.

Transformation: the triggers whose transformation the player may stop (one
box per trigger the engine lets a player stop), the blocked expression (while
it holds nothing changes), whether a transformed creature learns its new
species' moves of its level, and the record role holding the form. Context
values: the game's numbers the rules read by name (time_of_day from the clock
port), named values or a range and a default; a value a rule reads cannot go.
Training: on / off, the gain formula (a ruleset formula taking the engine's
TRAIN_GAIN_ARGS; "Formula..." opens it on Logic > Rules), the most of one
stat and of every stat together, and each stat's yield field (a species
field, Structure > Species fields). The table at the bottom lists every rule
the data has, with the triggers it is looked at for and what it reads.
Every edit is one undo step (core.structure.transformation).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ....core import battle
from ....core.structure import species_fields
from ....core.structure import transformation as model
from ...widgets import ask, button, set_enabled
from ..battle_common import NONE_TEXT, STRUCTURE, BattlePanel, combo, set_check, set_combo, set_spin, spin

if TYPE_CHECKING:
   from ...panel import PanelHost

## Context value table columns.
CONTEXT_COLUMNS = ["#", "Name", "Values (or range lo,hi)", "Default", "From", "Read by"]
## Column of the name.
NAME_COLUMN = 1
## Column of the values / range (typing sets them).
VALUES_COLUMN = 2
## Column of the default (typing sets it).
DEFAULT_COLUMN = 3
## Column of the source.
SOURCE_COLUMN = 4
## Column of the readers.
READERS_COLUMN = 5
## Yield table columns.
YIELD_COLUMNS = ["Stat", "Yield field"]
## Rule table columns.
RULE_COLUMNS = ["#", "Rule", "When", "Looked at on", "Reads"]
## What the page says at the top.
NOTE = ("A species' rules (Content > Species: Transformations, Forms) are expressions over the record, its stats "
        "(stat.NAME), its species' fields (species.NAME), the trigger, the item and the context values below. "
        "Training values are gained for each defeated foe by everyone sharing its experience.")
## Separator of a range typed as "lo,hi".
RANGE_SEPARATOR = ","


class TransformationPanel(BattlePanel):
   """!The transformation and training sections.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "growth_training"
   ## See EditorPanel.title.
   title = "Growth & training"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the transformation box, the context value table, the training box and the rule table.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      ## One box per trigger the player may stop ({trigger: QCheckBox}).
      self.cancel = {}
      cancel_row = QtWidgets.QHBoxLayout()
      for t in model.cancellable():
         box = QtWidgets.QCheckBox(t)
         box.toggled.connect(lambda _on: self._cancel_changed())
         self.cancel[t] = box
         cancel_row.addWidget(box)
      cancel_row.addStretch(1)
      ## The blocked expression.
      self.blocked = QtWidgets.QLineEdit()
      self.blocked.setPlaceholderText("none (e.g. held_item == still_stone && trigger != item_use)")
      self.blocked.editingFinished.connect(lambda: self.set_transformation(model.BLOCKED_KEY,
                                                                           self.blocked.text().strip() or None))
      ## Learn the new species' moves of its level.
      self.learn = QtWidgets.QCheckBox("A transformed creature learns its new species' moves of its level")
      self.learn.toggled.connect(lambda on: self.set_transformation(model.LEARN_KEY, bool(on)))
      ## The record role holding the form.
      self.form_role = combo(lambda text: self.set_transformation(model.FORM_ROLE_KEY,
                                                                  None if text == NONE_TEXT else text))
      form = QtWidgets.QFormLayout()
      form.addRow("Player may stop", cancel_row)
      form.addRow("Blocked while", self.blocked)
      form.addRow("", self.learn)
      form.addRow("Form role", self.form_role)
      top = QtWidgets.QGroupBox("Transformation")
      top.setLayout(form)
      ## The context values.
      self.contexts = QtWidgets.QTableWidget(0, len(CONTEXT_COLUMNS))
      self.contexts.setHorizontalHeaderLabels(CONTEXT_COLUMNS)
      self.contexts.verticalHeader().setVisible(False)
      self.contexts.horizontalHeader().setStretchLastSection(True)
      self.contexts.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.contexts.itemChanged.connect(lambda item: self._context_cell(item))
      ctx_buttons = QtWidgets.QHBoxLayout()
      ctx_buttons.addWidget(button("Add...", lambda: self.add_context(), "Add a context value"))
      ctx_buttons.addWidget(button("Remove", lambda: self.remove_context(), "Remove the selected value (no rule "
                                                                             "reads it)"))
      ctx_buttons.addStretch(1)
      ctx_lay = QtWidgets.QVBoxLayout()
      ctx_lay.addWidget(self.contexts)
      ctx_lay.addLayout(ctx_buttons)
      ctx_box = QtWidgets.QGroupBox("Context values")
      ctx_box.setLayout(ctx_lay)
      ## Training on / off.
      self.training_on = QtWidgets.QCheckBox("Training values")
      self.training_on.toggled.connect(lambda on: self.set_training_on(bool(on)))
      ## The gain formula.
      self.gain = combo(lambda text: self.set_training(model.GAIN_KEY, text))
      ## The stat cap.
      self.stat_cap = spin(0, 0, lambda v: self.set_training(model.STAT_CAP_KEY, v))
      ## The total cap.
      self.total_cap = spin(0, 0, lambda v: self.set_training(model.TOTAL_CAP_KEY, v))
      ## The ruleset point each gain goes through in battle (C6: held items / passives change it), or none.
      self.point = combo(lambda text: self.set_training(model.POINT_KEY, None if text == NONE_TEXT else text))
      gain_row = QtWidgets.QHBoxLayout()
      gain_row.addWidget(self.gain, 1)
      gain_row.addWidget(QtWidgets.QLabel("(" + ", ".join(model.gain_args()) + ")"))
      gain_row.addWidget(button("Formula...", lambda: self.open_formula(), "Show the formula on Logic > Rules"))
      ## Each stat's yield field.
      self.yields = QtWidgets.QTableWidget(0, len(YIELD_COLUMNS))
      self.yields.setHorizontalHeaderLabels(YIELD_COLUMNS)
      self.yields.verticalHeader().setVisible(False)
      self.yields.horizontalHeader().setStretchLastSection(True)
      train_form = QtWidgets.QFormLayout()
      train_form.addRow(self.training_on)
      train_form.addRow("Gain per foe", gain_row)
      train_form.addRow("Most of one stat", self.stat_cap)
      train_form.addRow("Most in all", self.total_cap)
      train_form.addRow("Gain point", self.point)
      train_form.addRow("Yields", self.yields)
      train_box = QtWidgets.QGroupBox("Training")
      train_box.setLayout(train_form)
      ## Every rule of the data.
      self.rules = QtWidgets.QTableWidget(0, len(RULE_COLUMNS))
      self.rules.setHorizontalHeaderLabels(RULE_COLUMNS)
      self.rules.verticalHeader().setVisible(False)
      self.rules.horizontalHeader().setStretchLastSection(True)
      self.rules.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      middle = QtWidgets.QHBoxLayout()
      middle.addWidget(ctx_box, 1)
      middle.addWidget(train_box, 1)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addWidget(top)
      lay.addLayout(middle, 1)
      lay.addWidget(QtWidgets.QLabel("Rules"))
      lay.addWidget(self.rules, 1)
      lay.addWidget(self.errors)

   # -- reading -------------------------------------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads both sections and the rules.
      @return None
      """
      doc = self.battle_doc()
      self._filling = True
      try:
         if doc is not None:
            self._fill_transformation(doc)
            self._fill_contexts(doc)
            self._fill_training(doc)
            self._fill_rules(doc)
      finally:
         self._filling = False
      set_enabled(self, doc is not None)
      self.show_errors()

   def _fill_transformation(self, doc: Any) -> None:
      """!Shows the transformation section.
      @param doc  battle Document
      @return None
      """
      t = model.transformation(doc)
      for name, box in self.cancel.items():
         set_check(box, name in t[model.CANCEL_KEY])
      if not self.blocked.hasFocus():
         self.blocked.setText(t[model.BLOCKED_KEY] or "")
      set_check(self.learn, t[model.LEARN_KEY])
      set_combo(self.form_role, [NONE_TEXT] + model.form_role_choices(doc), t[model.FORM_ROLE_KEY] or NONE_TEXT)

   def _fill_contexts(self, doc: Any) -> None:
      """!Shows the context values.
      @param doc  battle Document
      @return None
      """
      rows = model.context_rows(doc)
      self.contexts.setRowCount(len(rows))
      editable = QtCore.Qt.ItemFlag.ItemIsEditable
      for r, row in enumerate(rows):
         named = ", ".join(row["values"]) if row["values"] else f"{row['range'][0]}{RANGE_SEPARATOR}{row['range'][1]}"
         default = row["values"][row["default"]] if row["values"] and row["default"] < len(row["values"]) else \
            str(row["default"])
         texts = [str(row["index"]), row["name"], named, default, row["source"], ", ".join(row["readers"]) or "-"]
         for c, value in enumerate(texts):
            item = QtWidgets.QTableWidgetItem(value)
            if c not in (VALUES_COLUMN, DEFAULT_COLUMN):
               item.setFlags(item.flags() & ~editable)
            self.contexts.setItem(r, c, item)
      self.contexts.resizeColumnsToContents()

   def _fill_training(self, doc: Any) -> None:
      """!Shows the training section and the yield table (one combo per stat: none or a species field).
      @param doc  battle Document
      @return None
      """
      tr = model.training(doc)
      on = tr is not None
      set_check(self.training_on, on)
      p = self.project()
      formulas = model.gain_formulas(doc)
      set_combo(self.gain, formulas if not on or tr[model.GAIN_KEY] in formulas else
                formulas + [str(tr[model.GAIN_KEY])], tr[model.GAIN_KEY] if on else None)
      most = model.stat_cap_max(doc)
      self.stat_cap.setRange(0, most)
      stats = battle.stat_keys(doc)
      self.total_cap.setRange(0, most * len(stats))
      if on:
         set_spin(self.stat_cap, tr[model.STAT_CAP_KEY] or 0)
         set_spin(self.total_cap, tr[model.TOTAL_CAP_KEY] or 0)
      points = model.training_points(doc)
      point = tr.get(model.POINT_KEY) if on else None
      set_combo(self.point, [NONE_TEXT] + points + ([point] if point and point not in points else []),
                point or NONE_TEXT)
      fields = species_fields.field_names(doc)
      given = tr[model.YIELDS_KEY] if on else {}
      self.yields.setRowCount(len(stats))
      for r, stat in enumerate(stats):
         label = QtWidgets.QTableWidgetItem(stat)
         label.setFlags(label.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
         self.yields.setItem(r, 0, label)
         box = self.yields.cellWidget(r, 1)
         if not isinstance(box, QtWidgets.QComboBox):
            box = combo(lambda text, s=stat: self.set_yield_field(s, None if text == NONE_TEXT else text))
            self.yields.setCellWidget(r, 1, box)
         set_combo(box, [NONE_TEXT] + fields, given.get(stat, NONE_TEXT))
         box.setEnabled(on)
      for w in (self.gain, self.stat_cap, self.total_cap):
         w.setEnabled(on and p is not None)

   def _fill_rules(self, doc: Any) -> None:
      """!Lists every compiled rule.
      @param doc  battle Document
      @return None
      """
      rows = model.rule_rows(doc)
      self.rules.setRowCount(len(rows))
      for r, row in enumerate(rows):
         texts = [str(row["id"]), row["owner"], row["when"], ", ".join(row["on"]), ", ".join(row["reads"])]
         for c, value in enumerate(texts):
            self.rules.setItem(r, c, QtWidgets.QTableWidgetItem(value))
      self.rules.resizeColumnsToContents()

   def selected_context(self) -> str | None:
      """!The selected context value's name.
      @return the name, or None
      """
      rows = self.contexts.selectionModel().selectedRows()
      if not rows:
         return None
      item = self.contexts.item(rows[0].row(), NAME_COLUMN)
      return item.text() if item is not None else None

   # -- editing -------------------------------------------------------------------------------------------------------

   def _edit(self, label: str, fn: Any) -> bool:
      """!One edit; a refused one refreshes the page back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      ok = self.edit(label, fn)
      if not ok:
         self.host.changed()
      return ok

   def _cancel_changed(self) -> None:
      """!A "player may stop" box was toggled.
      @return None
      """
      chosen = [t for t, box in self.cancel.items() if box.isChecked()]
      self.set_transformation(model.CANCEL_KEY, chosen or None)

   def set_transformation(self, field: str, value: Any) -> bool:
      """!Sets a transformation field.
      @param field  cancel, blocked, learn or form_role
      @param value  the value (None: left out)
      @return True when it went through
      """
      doc = self.battle_doc()
      if self._filling or doc is None:
         return False
      if model.transformation(doc).get(field) == value:
         return False
      return self._edit("Set transformation", lambda: model.set_transformation(doc, field, value))

   def add_context(self, name: str | None = None, values: str | None = None) -> bool:
      """!Adds a context value.
      @param name    its name, or None to ask
      @param values  value names, comma separated (empty: a range 0..255), or None to ask
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add context value", "Name (a lower-case identifier):")
         if not ok:
            return False
      if values is None:
         values, ok = QtWidgets.QInputDialog.getText(self, "Add context value",
                                                     "Value names, comma separated (empty: a number):")
         if not ok:
            return False
      names = [v.strip() for v in values.split(RANGE_SEPARATOR) if v.strip()] or None
      return self._edit("Add context value", lambda: model.add_context(doc, name, names))

   def remove_context(self) -> bool:
      """!Removes the selected context value.
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected_context()
      if doc is None or name is None:
         return False
      return self._edit("Remove context value", lambda: model.remove_context(doc, name))

   def _context_cell(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A context value's values / range or default was typed.
      @param item  the cell
      @return None
      """
      doc = self.battle_doc()
      if self._filling or doc is None:
         return
      name_item = self.contexts.item(item.row(), NAME_COLUMN)
      if name_item is None:
         return
      name, text = name_item.text(), item.text().strip()
      row = next((r for r in model.context_rows(doc) if r["name"] == name), None)
      if row is None:
         return
      if item.column() == VALUES_COLUMN:
         parts = [v.strip() for v in text.split(RANGE_SEPARATOR) if v.strip()]
         if parts and all(p.lstrip("-").isdigit() for p in parts):
            self._edit("Set context value", lambda: model.set_context(doc, name, model.RANGE_KEY, parts))
         else:
            # C6 (review4 finding 24): the values are numbered by position; ask before one moves or goes
            warning = model.context_order_warning(doc, name, parts)
            b = QtWidgets.QMessageBox.StandardButton
            if warning is not None and ask(self, "Context values", f"{warning}\n\nChange them anyway?", b.Yes | b.No,
                                           b.No, b.No) != b.Yes:
               self.refresh()   # the cell shows the values again
               return
            self._edit("Set context value", lambda: model.set_context(doc, name, model.VALUES_KEY, parts or None))
      elif item.column() == DEFAULT_COLUMN:
         value: Any = int(text) if text.lstrip("-").isdigit() else (text or None)
         self._edit("Set context value", lambda: model.set_context(doc, name, model.DEFAULT_KEY, value))

   def set_training_on(self, on: bool) -> bool:
      """!Turns training on (the first gain formula) or off.
      @param on  True for on
      @return True when it changed
      """
      doc = self.battle_doc()
      if self._filling or doc is None or (model.training(doc) is not None) == on:
         return False
      if not on:
         return self._edit("Training off", lambda: model.disable_training(doc))
      formulas = model.gain_formulas(doc)
      if not formulas:
         self.host.show_status("training: the ruleset has no formula taking (" + ", ".join(model.gain_args()) +
                               ") (Logic > Rules)")
         self.host.changed()
         return False
      return self._edit("Training on", lambda: model.enable_training(doc, formulas[0]))

   def set_training(self, field: str, value: Any) -> bool:
      """!Sets the gain, a cap or the gain point.
      @param field  gain, stat_cap, total_cap or point
      @param value  the value
      @return True when it went through
      """
      doc = self.battle_doc()
      if self._filling or doc is None:
         return False
      tr = model.training(doc)
      if tr is None or tr.get(field) == value:
         return False
      return self._edit("Set training", lambda: model.set_training(doc, field, value))

   def set_yield_field(self, stat: str, field: str | None) -> bool:
      """!Names a stat's yield field.
      @param stat   stat name
      @param field  species field, or None
      @return True when it went through
      """
      doc = self.battle_doc()
      if self._filling or doc is None:
         return False
      return self._edit("Training yield", lambda: model.set_yield_field(doc, stat, field))

   def open_formula(self) -> bool:
      """!Shows the gain formula on Logic > Rules.
      @return True when the page shows it
      """
      show = getattr(self.host, "show_panel", None)
      try:
         rules = show("rules") if show is not None else None
      except KeyError:
         rules = None
      if rules is None:
         self.host.show_status("no Rules page here (open the battle editor's Logic group)")
         return False
      at = rules.slot.findText(self.gain.currentText())
      if at >= 0:
         rules.slot.setCurrentIndex(at)
      return at >= 0
