"""!The Combination page (engine B1, D-28 section 1): the structure manifest's "combine_methods", the ways two or more
creatures become one (a fusion, a synthesis, an altar).

The list shows each method; the tabs edit the selected one:
- Method: its label, kind (nursery methods compile but only immediate ones run end to end), how the result arrives,
  what happens to the inputs (kept or consumed: removed only once the result is placed), whether eggs may be inputs,
  the input count, and the level, odds and fee expressions (odds / fee empty: none).
- Slots: each input's role (the method's expressions and the effect logic's `input.ROLE` follow a rename) and its
  requirement (the growth `when` language over the input's record).
- Tables: a method's group tables, keyed by a species field's values or the first type; the grid's cells name the
  group a pair gives (empty: none).
- Rules: the ordered result rules (recipe, table with its pick, expression; none matching: refused), each with an
  optional `when`.
- Moves: who picks the result's moves (ordered, random, the player), how many, and the move sources (C9: each
  source's From, the one slot role it reads, and whether the chosen moves are pushed after the result's own).
- Messages: the battle message at each moment (unfit, refused, combined, no room ...).
Below the tabs: a preview of what the method gives (the engine's Python mirror, no random parts) for typed species
and levels or for a test save's boxed creatures. Add / Remove / Rename / Up / Down edit the list (a method the effect
logic or the scripts name is not removed; a rename follows both). Every choice list is the engine's
(core.structure.combination).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from PySide6 import QtCore, QtWidgets

from ....core import inventory
from ....core.document import DocumentError
from ....core.structure import combination as cb_model
from ....core.structure import storage
from ...widgets import button, set_enabled
from ..battle_common import STRUCTURE, BattlePanel, set_check, set_combo, set_spin, set_spin_max

if TYPE_CHECKING:
   from ...panel import PanelHost

## What the page says above the list.
NOTE = ("A combination method makes one creature out of two or more: a script runs it (`combine open NAME`), the "
        "player picks the inputs, each slot's requirement must hold, then the first result rule that matches names "
        "the result (none: refused). Its level, its moves and what the inputs leave it (the `on combine` logic: "
        "inherit ...) follow; consumed inputs go once it is placed.")
## Width of the method list, pixels.
LIST_WIDTH = 180
## What a preview input shows when it is empty.
NO_INPUT = "(none)"
## What the test save chooser shows for typed inputs.
TYPED_INPUTS = "(type species and levels)"
## What a message chooser shows for no message.
NO_MESSAGE = "(none)"
## Preview inputs' level range.
LEVEL_RANGE = (1, 100)
## Most a move limit spin box offers (0: the layout's move slots).
MAX_MOVE_LIMIT = 16
## Slot grid columns: the role, the requirement.
SLOT_ROLE_COLUMN, SLOT_REQUIRES_COLUMN = 0, 1
## Slot grid column count.
SLOT_COLUMNS = 2
## Move source grid columns: used, the limit, all, (C9) the one slot role it reads.
SOURCE_ON_COLUMN, SOURCE_LIMIT_COLUMN, SOURCE_ALL_COLUMN, SOURCE_FROM_COLUMN = 0, 1, 2, 3
## Move source grid column count.
SOURCE_COLUMNS = 4
## The From column's choice for a source reading every input.
ANY_INPUT_TEXT = "every input"
## Height of the grids, pixels.
GRID_HEIGHT = 170


class CombinationPanel(BattlePanel):
   """!The combination methods.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "combination"
   ## See EditorPanel.title.
   title = "Combination"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the list, the tabs, the preview and the buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected method's name, or None.
      self.selected = None
      ## The selected table's name, or None.
      self.table_name = None
      ## The methods.
      self.list = QtWidgets.QListWidget()
      self.list.setMaximumWidth(LIST_WIDTH)
      self.list.currentTextChanged.connect(lambda text: self._picked(text))
      ## The tabs.
      self.tabs = QtWidgets.QTabWidget()
      self.tabs.addTab(self._method_tab(), "Method")
      self.tabs.addTab(self._slots_tab(), "Slots")
      self.tabs.addTab(self._tables_tab(), "Tables")
      self.tabs.addTab(self._rules_tab(), "Rules")
      self.tabs.addTab(self._moves_tab(), "Moves")
      self.tabs.addTab(self._messages_tab(), "Messages")
      preview_box = self._preview_box()
      buttons = QtWidgets.QHBoxLayout()
      buttons.addWidget(button("Add...", lambda: self.add_method(), "Add an immediate method after the selected one"))
      buttons.addWidget(button("Remove", lambda: self.remove_method(),
                               "Remove it (refused while effect logic or a script names it)"))
      buttons.addWidget(button("Rename...", lambda: self.rename_method(),
                               "Rename it; the effect logic and the game's scripts follow"))
      buttons.addWidget(button("Up", lambda: self.move_method(-1)))
      buttons.addWidget(button("Down", lambda: self.move_method(1)))
      buttons.addStretch(1)
      ## Who names the selected method.
      self.users_text = QtWidgets.QLabel()
      self.users_text.setWordWrap(True)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(self.tabs, 1)
      right.addWidget(self.users_text)
      right.addWidget(preview_box)
      body = QtWidgets.QHBoxLayout()
      body.addWidget(self.list)
      body.addLayout(right, 1)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addLayout(body, 1)
      lay.addLayout(buttons)
      lay.addWidget(self.errors)

   # -- building ------------------------------------------------------------------------------------------------------

   def _expr_edit(self, placeholder: str, apply: Callable[[str], object]) -> QtWidgets.QLineEdit:
      """!A line editor of an expression, applied on Return and when the editing ends.
      @param placeholder  what it shows when empty
      @param apply        callable(text)
      @return QLineEdit
      """
      e = QtWidgets.QLineEdit()
      e.setPlaceholderText(placeholder)
      e.editingFinished.connect(lambda: None if self._filling or not e.isModified() else apply(e.text()))
      return e

   def _method_tab(self) -> QtWidgets.QWidget:
      """!The method's own keys.
      @return the tab
      """
      w = QtWidgets.QWidget()
      ## What menus show.
      self.label = QtWidgets.QLineEdit()
      self.label.editingFinished.connect(
         lambda: None if self._filling else self._set(lambda d, n: cb_model.set_label(d, n, self.label.text())))
      ## nursery or immediate.
      self.kind = QtWidgets.QComboBox()
      self.kind.activated.connect(lambda _i: self._set(lambda d, n: cb_model.set_kind(d, n, self.kind.currentText())))
      ## How the result arrives.
      self.delivery = QtWidgets.QComboBox()
      self.delivery.activated.connect(
         lambda _i: self._set(lambda d, n: cb_model.set_delivery(d, n, self.delivery.currentText())))
      ## kept or consumed.
      self.afterwards = QtWidgets.QComboBox()
      self.afterwards.activated.connect(
         lambda _i: self._set(lambda d, n: cb_model.set_afterwards(d, n, self.afterwards.currentText())))
      ## Eggs may be inputs.
      self.eggs = QtWidgets.QCheckBox("Eggs may be inputs")
      self.eggs.clicked.connect(lambda on: self._set(lambda d, n: cb_model.set_allow_eggs(d, n, bool(on))))
      ## Fewest and most inputs.
      self.count_lo, self.count_hi = QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
      for s in (self.count_lo, self.count_hi):
         s.editingFinished.connect(lambda: None if self._filling else self.apply_count())
      count_row = QtWidgets.QHBoxLayout()
      count_row.addWidget(self.count_lo)
      count_row.addWidget(QtWidgets.QLabel("to"))
      count_row.addWidget(self.count_hi)
      count_row.addStretch(1)
      ## The result's level.
      self.level = self._expr_edit("e.g. level_avg, first.level + 1",
                                   lambda t: self._set(lambda d, n: cb_model.set_level(d, n, t)))
      ## The odds (empty: always).
      self.odds = self._expr_edit("(none: always) e.g. 50 if same_species",
                                  lambda t: self._set(lambda d, n: cb_model.set_value(d, n, "odds", t or None)))
      ## The fee (empty: none).
      self.fee = self._expr_edit("(none: free) e.g. result.level * 10",
                                 lambda t: self._set(lambda d, n: cb_model.set_value(d, n, "fee", t or None)))
      form = QtWidgets.QFormLayout(w)
      form.addRow("Label", self.label)
      form.addRow("Kind", self.kind)
      form.addRow("Delivery", self.delivery)
      form.addRow("Inputs afterwards", self.afterwards)
      form.addRow("", self.eggs)
      form.addRow("Inputs", count_row)
      form.addRow("Level", self.level)
      form.addRow("Odds (of 100)", self.odds)
      form.addRow("Fee", self.fee)
      return w

   def _slots_tab(self) -> QtWidgets.QWidget:
      """!The slots' roles and requirements.
      @return the tab
      """
      w = QtWidgets.QWidget()
      ## One row per slot.
      self.slots = QtWidgets.QTableWidget(0, SLOT_COLUMNS)
      self.slots.setHorizontalHeaderLabels(["Role (input.ROLE)", "Requires (empty: any)"])
      self.slots.horizontalHeader().setStretchLastSection(True)
      self.slots.setMinimumHeight(GRID_HEIGHT)
      self.slots.itemChanged.connect(lambda item: self._slot_edited(item))
      lay = QtWidgets.QVBoxLayout(w)
      lay.addWidget(self.slots)
      return w

   def _tables_tab(self) -> QtWidgets.QWidget:
      """!The group tables and their grid.
      @return the tab
      """
      w = QtWidgets.QWidget()
      ## The tables.
      self.table = QtWidgets.QComboBox()
      self.table.activated.connect(lambda _i: self._table_picked())
      ## The table's key.
      self.table_key = QtWidgets.QComboBox()
      self.table_key.activated.connect(lambda _i: self._set_table(key=self.table_key.currentText()))
      ## (a, b) matches (b, a).
      self.symmetric = QtWidgets.QCheckBox("Symmetric")
      self.symmetric.clicked.connect(lambda on: self._set_table(symmetric=bool(on)))
      top = QtWidgets.QHBoxLayout()
      top.addWidget(self.table, 1)
      top.addWidget(QtWidgets.QLabel("key"))
      top.addWidget(self.table_key)
      top.addWidget(self.symmetric)
      top.addWidget(button("Add...", lambda: self.add_table(), "A table keyed by the first type"))
      top.addWidget(button("Remove", lambda: self.remove_table(), "Remove it (refused while a rule names it)"))
      ## The cells: the first input's key value down, the second's across.
      self.grid = QtWidgets.QTableWidget()
      self.grid.setMinimumHeight(GRID_HEIGHT)
      self.grid.itemChanged.connect(lambda item: self._cell_edited(item))
      lay = QtWidgets.QVBoxLayout(w)
      lay.addLayout(top)
      lay.addWidget(self.grid, 1)
      return w

   def _rules_tab(self) -> QtWidgets.QWidget:
      """!The ordered result rules.
      @return the tab
      """
      w = QtWidgets.QWidget()
      ## The rules, in order.
      self.rules = QtWidgets.QListWidget()
      self.rules.currentRowChanged.connect(lambda _r: None if self._filling else self._fill_rule())
      ## The selected rule's `when`.
      self.rule_when = self._expr_edit("(always)", lambda t: self._set_rule(when=t or None))
      ## The selected table rule's pick: which members.
      self.pick_where = self._expr_edit("(any member)", lambda _t: self.apply_pick())
      ## The pick's order.
      self.pick_order = self._expr_edit(f"(the {cb_model.order_index()} order)", lambda _t: self.apply_pick())
      ## The pick's choice.
      self.pick_choose = QtWidgets.QComboBox()
      self.pick_choose.activated.connect(lambda _i: self.apply_pick())
      ## The pick's fallback.
      self.pick_else = QtWidgets.QComboBox()
      self.pick_else.activated.connect(lambda _i: self.apply_pick())
      form = QtWidgets.QFormLayout()
      form.addRow("When", self.rule_when)
      form.addRow("Pick where", self.pick_where)
      form.addRow("Pick order", self.pick_order)
      form.addRow("Pick", self.pick_choose)
      form.addRow("Else", self.pick_else)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Recipe...", lambda: self.add_recipe(), "Inputs (species, FIELD=VALUE, type=TYPE) give"
                                                                    " a species"))
      row.addWidget(button("Table...", lambda: self.add_table_rule(), "A table's group, a member picked"))
      row.addWidget(button("Expression...", lambda: self.add_expression(), "A species index expression"))
      row.addWidget(button("Remove", lambda: self.remove_rule()))
      row.addWidget(button("Up", lambda: self.move_rule(-1)))
      row.addWidget(button("Down", lambda: self.move_rule(1)))
      row.addStretch(1)
      lay = QtWidgets.QVBoxLayout(w)
      lay.addWidget(self.rules, 1)
      lay.addLayout(row)
      lay.addLayout(form)
      return w

   def _moves_tab(self) -> QtWidgets.QWidget:
      """!The move chooser and the sources.
      @return the tab
      """
      w = QtWidgets.QWidget()
      ## Who picks.
      self.chooser = QtWidgets.QComboBox()
      self.chooser.activated.connect(
         lambda _i: self._set(lambda d, n: cb_model.set_moves(d, n, chooser=self.chooser.currentText())))
      ## How many (0: the layout's move slots).
      self.move_limit = QtWidgets.QSpinBox()
      self.move_limit.setRange(0, MAX_MOVE_LIMIT)
      self.move_limit.setSpecialValueText("move slots")
      self.move_limit.editingFinished.connect(
         lambda: None if self._filling else self._set(
            lambda d, n: cb_model.set_moves(d, n, limit=self.move_limit.value())))
      ## The result's own moves fill the slots left.
      self.fill = QtWidgets.QCheckBox("The result's own moves fill the slots left")
      self.fill.clicked.connect(lambda on: self._set(lambda d, n: cb_model.set_moves(d, n, fill=bool(on))))
      ## C9: the chosen moves are learned after the result's own ones, each pushing the first out when full.
      self.push = QtWidgets.QCheckBox("Learn the chosen moves after the result's own (push the first out when full)")
      self.push.clicked.connect(lambda on: self._set(lambda d, n: cb_model.set_moves(d, n, push=bool(on))))
      ## One row per source kind: used, limit, all of them, (C9) the one input it reads.
      self.sources = QtWidgets.QTableWidget(0, SOURCE_COLUMNS)
      self.sources.setHorizontalHeaderLabels(["Used", "Limit (0: none)", "All", "From"])
      self.sources.setMinimumHeight(GRID_HEIGHT)
      self.sources.itemChanged.connect(lambda item: self._source_edited(item))
      form = QtWidgets.QFormLayout()
      form.addRow("Chooser", self.chooser)
      form.addRow("Limit", self.move_limit)
      form.addRow("", self.fill)
      form.addRow("", self.push)
      lay = QtWidgets.QVBoxLayout(w)
      lay.addLayout(form)
      lay.addWidget(QtWidgets.QLabel("Sources, in order (candidates gathered for the chooser)"))
      lay.addWidget(self.sources, 1)
      return w

   def _messages_tab(self) -> QtWidgets.QWidget:
      """!The messages at the moments.
      @return the tab
      """
      w = QtWidgets.QWidget()
      form = QtWidgets.QFormLayout(w)
      ## Moment -> its message chooser.
      self.messages: dict[str, QtWidgets.QComboBox] = {}
      for moment in cb_model.moments():
         c = QtWidgets.QComboBox()
         c.activated.connect(lambda _i, m=moment, c=c: self.apply_message(m, c.currentText()))
         self.messages[moment] = c
         form.addRow(moment, c)
      return w

   def _preview_box(self) -> QtWidgets.QGroupBox:
      """!The preview: inputs and what they give.
      @return the box
      """
      box = QtWidgets.QGroupBox("Preview (the engine's mirror, no random parts)")
      ## Typed inputs or a test save's boxed creatures.
      self.save = QtWidgets.QComboBox()
      self.save.activated.connect(lambda _i: self._fill_preview_inputs())
      ## Per input: species (or boxed creature) and level.
      self.inputs = []
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.save)
      for _k in range(cb_model.limits()["inputs"]):
         c = QtWidgets.QComboBox()
         c.activated.connect(lambda _i: self.run_preview())
         s = QtWidgets.QSpinBox()
         s.setRange(*LEVEL_RANGE)
         s.valueChanged.connect(lambda _v: None if self._filling else self.run_preview())
         row.addWidget(c, 1)
         row.addWidget(s)
         self.inputs.append((c, s))
      ## What they give.
      self.preview_text = QtWidgets.QLabel()
      self.preview_text.setWordWrap(True)
      self.preview_text.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      lay = QtWidgets.QVBoxLayout(box)
      lay.addLayout(row)
      lay.addWidget(self.preview_text)
      return box

   # -- reading -------------------------------------------------------------------------------------------------------

   def names(self) -> list[str]:
      """!The method names in order.
      @return names ([] with nothing open)
      """
      return cb_model.method_names(self.battle_doc())

   def current(self) -> dict[str, Any] | None:
      """!The selected method (live).
      @return the method, or None
      """
      doc = self.battle_doc()
      if doc is None or self.selected not in self.names():
         return None
      return cb_model.method(doc, self.selected)

   def refresh(self) -> None:
      """!Re-reads the methods and shows the selected one.
      @return None
      """
      doc = self.battle_doc()
      names = self.names()
      chosen = self.selected if self.selected in names else (names[0] if names else None)
      self.selected = chosen
      self._filling = True
      try:
         self.list.clear()
         self.list.addItems(names)
         if chosen is not None:
            self.list.setCurrentRow(names.index(chosen))
         self._fill_form()
         self._fill_preview_inputs(run=False)
      finally:
         self._filling = False
      self.run_preview()
      set_enabled(self, doc is not None)
      self.show_errors()

   def _fill_form(self) -> None:
      """!Shows the selected method in the tabs.
      @return None
      """
      doc, m = self.battle_doc(), self.current()
      on = m is not None
      set_enabled(self.tabs, on)   # greyed, read-only; its grid and lists still scroll
      rows = {r["name"]: r for r in cb_model.method_rows(doc)} if doc is not None else {}
      row = rows.get(self.selected)
      named = (row["users"] + cb_model.script_users(doc, row["name"])) if row and doc is not None else []
      self.users_text.setText(("Named by: " + (", ".join(named) or "no effect logic or script")) if row else "")
      if not on or row is None:
         return
      lim = cb_model.limits()
      self.label.setText(row["label"])
      self.label.setMaxLength(lim["label"])
      set_combo(self.kind, cb_model.kinds(), row["kind"])
      set_combo(self.delivery, cb_model.deliveries(), row["delivery"])
      set_combo(self.afterwards, cb_model.afterwards_choices(), row["afterwards"])
      set_check(self.eggs, m.get("allow_eggs", False))
      for s in (self.count_lo, self.count_hi):
         s.setMinimum(lim["min_inputs"])
         set_spin_max(s, lim["inputs"])
      set_spin(self.count_lo, row["min"])
      set_spin(self.count_hi, row["max"])
      level = m.get("level")
      self.level.setText(str(level) if level is not None else "")
      for e, key in ((self.odds, "odds"), (self.fee, "fee")):
         v = m.get(key)
         e.setText(str(v.get("value", "")) if isinstance(v, dict) else "")
      self._fill_slots(m)
      self._fill_tables(m)
      self._fill_rules(m)
      self._fill_moves(m)
      choices = [NO_MESSAGE, *cb_model.message_choices(doc)]
      msgs = m.get("messages") if isinstance(m.get("messages"), dict) else {}
      for moment, c in self.messages.items():
         set_combo(c, choices, msgs.get(moment, NO_MESSAGE))

   def _fill_slots(self, m: dict[str, Any]) -> None:
      """!Fills the slot grid.
      @param m  the method
      @return None
      """
      self.slots.blockSignals(True)
      slots = cb_model.slots_of(m)
      self.slots.setRowCount(len(slots))
      for k, s in enumerate(slots):
         self.slots.setItem(k, SLOT_ROLE_COLUMN, QtWidgets.QTableWidgetItem(str(s.get("role", ""))))
         self.slots.setItem(k, SLOT_REQUIRES_COLUMN, QtWidgets.QTableWidgetItem(str(s.get("requires", ""))))
      self.slots.setVerticalHeaderLabels([f"input {k + 1}" for k in range(len(slots))])
      self.slots.blockSignals(False)

   def _fill_tables(self, m: dict[str, Any]) -> None:
      """!Fills the table chooser and the grid of the chosen table.
      @param m  the method
      @return None
      """
      doc = self.battle_doc()
      tables = cb_model.tables_of(m)
      names = list(tables)
      self.table_name = self.table_name if self.table_name in names else (names[0] if names else None)
      set_combo(self.table, names, self.table_name)
      keys = [cb_model.type_key(), *[f["name"] for f in self._fields() if f.get("values")]]
      t = tables.get(self.table_name) if self.table_name is not None else None
      set_combo(self.table_key, keys, t.get("key") if t else None)
      set_check(self.symmetric, t.get("symmetric", True) if t else False)
      for w in (self.table_key, self.symmetric, self.grid):
         set_enabled(w, t is not None)   # the grid goes read-only and keeps its scroll bars
      self.grid.blockSignals(True)
      self.grid.clear()
      if t is None or doc is None:
         self.grid.setRowCount(0)
         self.grid.setColumnCount(0)
         self.grid.blockSignals(False)
         return
      values = cb_model.key_values(doc, str(t.get("key")))
      given = cb_model.cells(doc, self.selected, self.table_name)
      symmetric = t.get("symmetric", True)
      self.grid.setRowCount(len(values))
      self.grid.setColumnCount(len(values))
      self.grid.setVerticalHeaderLabels(values)
      self.grid.setHorizontalHeaderLabels(values)
      for i, a in enumerate(values):
         for j, b in enumerate(values):
            v = given.get((a, b))
            if v is None and symmetric:
               v = given.get((b, a))
            self.grid.setItem(i, j, QtWidgets.QTableWidgetItem("" if v is None else str(v)))
      self.grid.blockSignals(False)

   def _fill_rules(self, m: dict[str, Any]) -> None:
      """!Fills the rule list.
      @param m  the method
      @return None
      """
      row = self.rules.currentRow()
      self.rules.blockSignals(True)
      self.rules.clear()
      rules = cb_model.rules_of(m)
      self.rules.addItems([f"{k}: {cb_model.rule_text(r)}" for k, r in enumerate(rules)])
      if rules:
         self.rules.setCurrentRow(min(max(row, 0), len(rules) - 1))
      self.rules.blockSignals(False)
      self._fill_rule()

   def _fill_rule(self) -> None:
      """!Shows the selected rule's when and pick.
      @return None
      """
      m, k = self.current(), self.rules.currentRow()
      rules = cb_model.rules_of(m) if m is not None else []
      rule = rules[k] if 0 <= k < len(rules) else None
      self.rule_when.setEnabled(rule is not None)
      self.rule_when.setText(str(rule.get("when", "")) if rule else "")
      is_table = rule is not None and cb_model.rule_kind(rule) == "table"
      p = rule.get("pick") if is_table else None
      p = {"where": p} if isinstance(p, str) else p if isinstance(p, dict) else {}
      for w in (self.pick_where, self.pick_order, self.pick_choose, self.pick_else):
         w.setEnabled(is_table)
      self.pick_where.setText(str(p.get("where", "")))
      self.pick_order.setText(str(p.get("order", "")))
      set_combo(self.pick_choose, cb_model.pick_choices(), p.get("choose", cb_model.pick_choices()[0]))
      set_combo(self.pick_else, cb_model.pick_fallbacks(), p.get("else", cb_model.pick_fallbacks()[0]))

   def _fill_moves(self, m: dict[str, Any]) -> None:
      """!Fills the move chooser and the source grid.
      @param m  the method
      @return None
      """
      mv = m.get("moves") if isinstance(m.get("moves"), dict) else {}
      set_combo(self.chooser, cb_model.choosers(), mv.get("chooser", cb_model.choosers()[0]))
      set_spin(self.move_limit, mv.get("limit", 0))
      set_check(self.fill, mv.get("fill", True))
      set_check(self.push, bool(mv.get("push", False)))
      given = {s.get("kind"): s for s in cb_model.sources_of(m)}
      roles = cb_model.roles_of(m)
      kinds = cb_model.move_sources()
      self.sources.blockSignals(True)
      self.sources.setRowCount(len(kinds))
      self.sources.setVerticalHeaderLabels(kinds)
      for k, kind in enumerate(kinds):
         s = given.get(kind)
         used = QtWidgets.QTableWidgetItem()
         used.setFlags(used.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
         used.setCheckState(QtCore.Qt.CheckState.Checked if s is not None and s.get("on", True)
                            else QtCore.Qt.CheckState.Unchecked)
         every = QtWidgets.QTableWidgetItem()
         every.setFlags(every.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
         every.setCheckState(QtCore.Qt.CheckState.Checked if s is not None and s.get("all")
                             else QtCore.Qt.CheckState.Unchecked)
         self.sources.setItem(k, SOURCE_ON_COLUMN, used)
         self.sources.setItem(k, SOURCE_LIMIT_COLUMN, QtWidgets.QTableWidgetItem(str(s.get("limit", 0)) if s else "0"))
         self.sources.setItem(k, SOURCE_ALL_COLUMN, every)
         # C9: the one slot role the source reads (a combo per row, made once and kept; every input by default)
         role = self.sources.cellWidget(k, SOURCE_FROM_COLUMN)
         if not isinstance(role, QtWidgets.QComboBox):
            role = QtWidgets.QComboBox()
            role.activated.connect(lambda _i, row=k: self._source_edited(self.sources.item(row, SOURCE_ON_COLUMN)))
            self.sources.setCellWidget(k, SOURCE_FROM_COLUMN, role)
         set_combo(role, [ANY_INPUT_TEXT, *roles], (s or {}).get("from") or ANY_INPUT_TEXT)
         role.setEnabled(s is not None)
      self.sources.blockSignals(False)

   def _fields(self) -> list[dict[str, Any]]:
      """!The species fields.
      @return field dicts
      """
      from ....core.structure import species_fields
      doc = self.battle_doc()
      return list(species_fields.fields(doc)) if doc is not None else []

   def _fill_preview_inputs(self, run: bool = True) -> None:
      """!Fills the preview's input choosers: species with a level, or a test save's boxed creatures.
      @param run  True to run the preview afterwards
      @return None
      """
      p, m = self.project(), self.current()
      saves = [TYPED_INPUTS, *[path.stem for path in inventory.testsave_paths(p)]] if p is not None else []
      shown = self.save.currentText()
      set_combo(self.save, saves, shown if shown in saves else (saves[0] if saves else None))
      count = cb_model.count_of(m)[1] if m is not None else 0
      boxed = self._boxed()
      choices = [NO_INPUT, *([self._boxed_text(b) for b in boxed] if boxed is not None
                             else cb_model.species_names(self.battle_doc()) if p is not None else [])]
      for k, (c, s) in enumerate(self.inputs):
         keep = c.currentText()
         default = choices[k + 1] if boxed is not None and k + 1 < len(choices) else NO_INPUT
         set_combo(c, choices, keep if keep in choices and keep != NO_INPUT else default)
         c.setVisible(k < count)
         s.setVisible(k < count and boxed is None)
      if run:
         self.run_preview()

   def _boxed(self) -> list[dict[str, Any]] | None:
      """!The chosen test save's boxed creatures.
      @return their records, or None for typed inputs
      """
      p, name = self.project(), self.save.currentText()
      if p is None or not name or name == TYPED_INPUTS:
         return None
      try:
         return storage.boxed_of(inventory.open_testsave(p, name))
      except (DocumentError, OSError):
         return []

   @staticmethod
   def _boxed_text(b: dict[str, Any]) -> str:
      """!A boxed creature as a choice.
      @param b  its record
      @return "slot N: SPECIES Lv L"
      """
      return f"slot {b.get('slot')}: {b.get('species')} Lv {b.get('level', 1)}"

   def preview_records(self) -> list[dict[str, Any]]:
      """!The preview's inputs.
      @return records ({"species", "level"} or a boxed creature's)
      """
      m = self.current()
      count = cb_model.count_of(m)[1] if m is not None else 0
      boxed = self._boxed()
      by_text = {self._boxed_text(b): b for b in boxed} if boxed is not None else {}
      out = []
      for c, s in self.inputs[:count]:
         text = c.currentText()
         if not text or text == NO_INPUT:
            continue
         out.append(dict(by_text[text]) if text in by_text else {"species": text, "level": s.value()})
      return out

   def run_preview(self) -> str:
      """!Shows what the chosen inputs give.
      @return the text shown
      """
      p, name = self.project(), self.selected
      if p is None or name is None:
         text = "(no method)"
      else:
         records = self.preview_records()
         if not records:
            text = "(choose the inputs)"
         else:
            try:
               text = cb_model.preview_text(cb_model.preview(p, name, records), records)
            except DocumentError as e:   # the battle data does not compile now: the errors line says why
               text = f"(no preview: {e})"
      self.preview_text.setText(text)
      return text

   def _picked(self, text: str) -> None:
      """!Another method was picked.
      @param text  its name
      @return None
      """
      if self._filling or not text:
         return
      self.selected = text
      self.table_name = None
      self._filling = True
      try:
         self._fill_form()
         self._fill_preview_inputs(run=False)
      finally:
         self._filling = False
      self.run_preview()

   # -- editing -------------------------------------------------------------------------------------------------------

   def _edit(self, label: str, fn: Callable[[], object]) -> bool:
      """!One edit; a refused one refreshes the page back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      ok = self.edit(label, fn)
      if not ok:
         self.host.changed()
      return ok

   def _set(self, change: Callable[[Any, str], object], label: str = "Set combination method") -> bool:
      """!Changes the selected method.
      @param change  callable(doc, name)
      @param label   undo label
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      if self._filling or doc is None or name is None:
         return False
      return self._edit(label, lambda: change(doc, name))

   def apply_count(self) -> bool:
      """!States the input count from the spin boxes.
      @return True when it went through
      """
      lo, hi = self.count_lo.value(), max(self.count_lo.value(), self.count_hi.value())
      return self._set(lambda d, n: cb_model.set_count(d, n, lo, hi), "Combination inputs")

   def _slot_edited(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A slot's role or requirement was typed.
      @param item  the cell
      @return None
      """
      if self._filling:
         return
      k, text = item.row(), item.text().strip()
      if item.column() == SLOT_ROLE_COLUMN:
         if text:
            self.set_slot(k, role=text)
         else:
            self.host.changed()
      else:
         self.set_slot(k, requires=text)

   def set_slot(self, k: int, role: str | None = None, requires: str | None = None) -> bool:
      """!Sets a slot's role (followed by the expressions and the logic) or requirement ("" none).
      @param k         slot index
      @param role      its role, or None
      @param requires  its requirement, or None
      @return True when it went through
      """
      return self._set(lambda d, n: cb_model.set_slot(d, n, k, role, requires), "Combination slot")

   def _table_picked(self) -> None:
      """!Another table was chosen.
      @return None
      """
      self.table_name = self.table.currentText() or None
      m = self.current()
      if m is not None:
         self._filling = True
         try:
            self._fill_tables(m)
         finally:
            self._filling = False

   def _set_table(self, **parts: Any) -> bool:
      """!Sets the chosen table's key or symmetry.
      @param parts  key / symmetric
      @return True when it went through
      """
      t = self.table_name
      if t is None:
         return False
      return self._set(lambda d, n: cb_model.set_table(d, n, t, **parts), "Combination table")

   def add_table(self, name: str | None = None) -> bool:
      """!Adds a table keyed by the first type.
      @param name  its name, or None to ask
      @return True when added
      """
      if self.current() is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add table", "Name (lower case):")
         if not ok:
            return False
      if self._set(lambda d, n: cb_model.add_table(d, n, name.strip(), cb_model.type_key()), "Add combination table"):
         self.table_name = name.strip()
         self.host.changed()
         return True
      return False

   def remove_table(self) -> bool:
      """!Removes the chosen table.
      @return True when removed
      """
      t = self.table_name
      if t is None:
         return False
      if self._set(lambda d, n: cb_model.remove_table(d, n, t), "Remove combination table"):
         self.table_name = None
         return True
      return False

   def _cell_edited(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A cell was typed (empty: it goes).
      @param item  the cell
      @return None
      """
      if self._filling or self.table_name is None:
         return
      a = self.grid.verticalHeaderItem(item.row()).text()
      b = self.grid.horizontalHeaderItem(item.column()).text()
      self.set_cell(a, b, item.text().strip() or None)

   def set_cell(self, a: str, b: str, value: str | None) -> bool:
      """!Sets one cell of the chosen table.
      @param a      the first input's key value
      @param b      the second's
      @param value  the group, or None
      @return True when it went through
      """
      t = self.table_name
      if t is None:
         return False
      return self._set(lambda d, n: cb_model.set_cell(d, n, t, a, b, value), "Combination cell")

   def _add_rule(self, rule: dict[str, Any]) -> bool:
      """!Adds a rule after the selected one.
      @param rule  the rule
      @return True when added
      """
      m = self.current()
      k = self.rules.currentRow()
      at = k + 1 if m is not None and 0 <= k < len(cb_model.rules_of(m)) else None
      return self._set(lambda d, n: cb_model.add_rule(d, n, rule, at), "Add combination rule")

   def add_recipe(self, matchers: list[Any] | None = None, result: str | None = None) -> bool:
      """!Adds a recipe rule.
      @param matchers  species names, {FIELD: VALUE} or {"type": TYPE}, or None to ask
      @param result    the species, or None to ask
      @return True when added
      """
      if self.current() is None:
         return False
      if matchers is None:
         text, ok = QtWidgets.QInputDialog.getText(self, "Add recipe", "Inputs (comma separated: species, "
                                                   "FIELD=VALUE or type=TYPE):")
         if not ok:
            return False
         matchers = [{x.split("=", 1)[0].strip(): x.split("=", 1)[1].strip()} if "=" in x else x.strip()
                     for x in text.split(",") if x.strip()]
      if result is None:
         species = cb_model.species_names(self.battle_doc())
         result, ok = QtWidgets.QInputDialog.getItem(self, "Add recipe", "Gives:", species, 0, False)
         if not ok:
            return False
      return self._add_rule({"recipe": matchers, "result": result})

   def add_table_rule(self, table: str | None = None) -> bool:
      """!Adds a table rule (its pick: the first member).
      @param table  the table, or None to ask
      @return True when added
      """
      m = self.current()
      if m is None:
         return False
      if table is None:
         tables = list(cb_model.tables_of(m))
         table, ok = QtWidgets.QInputDialog.getItem(self, "Add table rule", "Table:", tables, 0, False)
         if not ok:
            return False
      return self._add_rule({"table": table})

   def add_expression(self, expr: str | None = None) -> bool:
      """!Adds an expression rule.
      @param expr  the species index expression, or None to ask
      @return True when added
      """
      if self.current() is None:
         return False
      if expr is None:
         expr, ok = QtWidgets.QInputDialog.getText(self, "Add expression rule", "Species (e.g. first.species):")
         if not ok:
            return False
      return self._add_rule({"expression": expr})

   def remove_rule(self) -> bool:
      """!Removes the selected rule.
      @return True when removed
      """
      k = self.rules.currentRow()
      return k >= 0 and self._set(lambda d, n: cb_model.remove_rule(d, n, k), "Remove combination rule")

   def move_rule(self, delta: int) -> bool:
      """!Moves the selected rule.
      @param delta  -1 up, +1 down
      @return True when it went through
      """
      k = self.rules.currentRow()
      if k < 0 or not self._set(lambda d, n: cb_model.move_rule(d, n, k, delta), "Move combination rule"):
         return False
      self.rules.setCurrentRow(k + delta)
      return True

   def _set_rule(self, **parts: Any) -> bool:
      """!Changes the selected rule.
      @param parts  when / pick
      @return True when it went through
      """
      k = self.rules.currentRow()
      return k >= 0 and self._set(lambda d, n: cb_model.set_rule(d, n, k, **parts), "Combination rule")

   def apply_pick(self) -> bool:
      """!States the selected table rule's pick from the editors.
      @return True when it went through
      """
      if self._filling:
         return False
      pick = {"where": self.pick_where.text().strip(), "order": self.pick_order.text().strip(),
              "choose": self.pick_choose.currentText(), "else": self.pick_else.currentText()}
      defaults = {"choose": cb_model.pick_choices()[0], "else": cb_model.pick_fallbacks()[0]}
      pick = {k: v for k, v in pick.items() if v and v != defaults.get(k)}
      return self._set_rule(pick=pick or None)

   def _source_edited(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A source row was changed.
      @param item  the cell
      @return None
      """
      if self._filling:
         return
      k = item.row()
      kind = cb_model.move_sources()[k]
      used = self.sources.item(k, SOURCE_ON_COLUMN).checkState() == QtCore.Qt.CheckState.Checked
      every = self.sources.item(k, SOURCE_ALL_COLUMN).checkState() == QtCore.Qt.CheckState.Checked
      text = self.sources.item(k, SOURCE_LIMIT_COLUMN).text().strip()
      limit = int(text) if text.isdigit() else 0
      combo = self.sources.cellWidget(k, SOURCE_FROM_COLUMN)
      role = combo.currentText() if isinstance(combo, QtWidgets.QComboBox) else ANY_INPUT_TEXT
      self.set_source(kind, used, limit, every, None if role == ANY_INPUT_TEXT else role)

   def set_source(self, kind: str, used: bool, limit: int = 0, every: bool = False, role: str | None = None) -> bool:
      """!Uses a move source (or leaves it out).
      @param kind   one of move_sources()
      @param used   True: a source
      @param limit  its limit (0: none)
      @param every  all its moves
      @param role   C9: the one slot role it reads, or None: every input
      @return True when it went through
      """
      m = self.current()
      present = m is not None and any(s.get("kind") == kind for s in cb_model.sources_of(m))
      if used:
         return self._set(lambda d, n: cb_model.set_source(d, n, kind, True, limit, every, role),
                          "Combination source")
      if present:
         return self._set(lambda d, n: cb_model.remove_source(d, n, kind), "Combination source")
      return False

   def apply_message(self, moment: str, key: str) -> bool:
      """!Sets a moment's message.
      @param moment  one of moments()
      @param key     a message, or NO_MESSAGE
      @return True when it went through
      """
      value = None if key == NO_MESSAGE else key
      return self._set(lambda d, n: cb_model.set_message(d, n, moment, value), "Combination message")

   def add_method(self, name: str | None = None) -> bool:
      """!Adds an immediate method after the selected one.
      @param name  the name, or None to ask
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add combination method", "Name (lower case):")
         if not ok:
            return False
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit("Add combination method", lambda: cb_model.add_method(doc, name, cb_model.DEFAULT_COUNT, at)):
         self.selected = name.strip()
         self.host.changed()
         return True
      return False

   def remove_method(self) -> bool:
      """!Removes the selected method.
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self._edit("Remove combination method", lambda: cb_model.remove_method(doc, name)):
         self.selected = None
         return True
      return False

   def rename_method(self, new: str | None = None) -> bool:
      """!Renames the selected method (the effect logic and the game's scripts follow, one undo step).
      @param new  the new name, or None to ask
      @return True when renamed
      """
      doc, old = self.battle_doc(), self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename combination method", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         return False
      if self._edit("Rename combination method", lambda: cb_model.rename_method(doc, old, new)):
         self.selected = new.strip()
         self.host.changed()
         return True
      return False

   def move_method(self, delta: int) -> bool:
      """!Moves the selected method up or down.
      @param delta  -1 up, +1 down
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      return self._edit("Move combination method", lambda: cb_model.move_method(doc, name, delta))
