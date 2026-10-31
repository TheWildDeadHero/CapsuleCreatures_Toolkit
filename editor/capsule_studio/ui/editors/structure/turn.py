"""!The Formats and Turn pages of the battle navigator (D-23 §3.2 "Formats &
Turn"; core.structure.turn).

Formats: the format list (new, copy, rename, delete, move: references
follow) and a form for the selected one: positions per side, reach, the
rule when a chosen target fainted, the party size limit, each position's
screen place and each side's presenter stand (a table each), with a
preview of the battle screen (content.presenters.PresenterPreview).

Turn: the action brackets (bigger acts first; the move bracket may be each
move's own priority), the speed tie rule, the battle start's send-out and
switch-in orders, the hook dispatch order (drag or Up / Down) and the
end-of-turn phases in order (drag or Up / Down; a battlers phase lists the
dispatch sources it runs, a sides / field phase says for whom). Grey values
are the engine's defaults (the manifest leaves them out); "Engine default"
gives a part back. Every choice list and limit comes from the engine's
compiler; an edit it refuses is refused with its message. Every change is
one undo step on the battle manifest.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ....core import battle
from ....core.structure import nursery as nursery_model
from ....core.structure import turn as model
from ...widgets import button, set_enabled
from ..battle_common import STRUCTURE, BattlePanel, EntryPanel, set_check, set_combo, set_spin
from ..content.presenters import PresenterPreview
from ..record_widgets import NameChecks, table_height

if TYPE_CHECKING:
   from ...panel import PanelHost
   from ..battle_common import JsonDict

## Style of a value the engine gives (the manifest leaves it out).
DEFAULT_STYLE = "color: #808080;"
## Style of a value the manifest gives.
GIVEN_STYLE = ""
## Columns of the places table: position, side, x, y.
PLACE_COLUMNS = ["Position", "Side", "X", "Y"]
## Columns of the stands table: side, x, y.
STAND_COLUMNS = ["Side", "X", "Y"]
## Places / stands table column of x.
PLACE_X = {"layout": 2, "stands": 1}
## Special value text of the party_max spin at its minimum (no limit: the layout's party size).
PARTY_SIZE_TEXT = "party size"
## Stretch of the tables in the formats form.
TABLE_STRETCH = 1


def mark_default(widget: QtWidgets.QWidget, default: bool) -> None:
   """!Greys a widget showing an engine default.
   @param widget   the widget
   @param default  True when the engine gives the value
   @return None
   """
   widget.setStyleSheet(DEFAULT_STYLE if default else GIVEN_STYLE)
   widget.setToolTip("engine default (the manifest leaves it out)" if default else "")


class FormatsPanel(EntryPanel):
   """!The battle formats: list and form.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   @var selected
   Name of the selected format, or None.
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "formats"
   ## See EditorPanel.title.
   title = "Formats"
   ## See EntryPanel.kind.
   kind = "formats"

   def build_form(self, layout: QtWidgets.QVBoxLayout) -> None:
      """!Adds the form widgets.
      @param layout  QVBoxLayout to add to
      @return None
      """
      most, fewest, most_sides = model.position_limits()
      note = QtWidgets.QLabel(f"A format puts {fewest}-{most_sides} sides on the field, at most {most} positions "
                              "in all, numbered side by side. Each position has a screen place; each side's "
                              "presenters stand at its stand (default: its first position).")
      note.setWordWrap(True)
      layout.addWidget(note)
      form = QtWidgets.QFormLayout()
      ## Sides of the format.
      self.side_count = QtWidgets.QSpinBox()
      self.side_count.setRange(fewest, most_sides)
      self.side_count.valueChanged.connect(lambda _v: self._sides_changed())
      ## Positions per side, one spin per possible side.
      self.side_spins = []
      sides_row = QtWidgets.QHBoxLayout()
      sides_row.addWidget(self.side_count)
      sides_row.addWidget(QtWidgets.QLabel("positions per side:"))
      for _s in range(most_sides):
         s = QtWidgets.QSpinBox()
         s.setRange(1, most)
         s.valueChanged.connect(lambda _v: self._sides_changed())
         self.side_spins.append(s)
         sides_row.addWidget(s)
      sides_row.addStretch(1)
      form.addRow("Sides", sides_row)
      ## Reach.
      self.range_box = QtWidgets.QComboBox()
      self.range_box.activated.connect(lambda _i: self.set_format(model.RANGE_KEY, self.range_box.currentText()))
      form.addRow("Range", self.range_box)
      ## Rule when the chosen target fainted.
      self.fainted_box = QtWidgets.QComboBox()
      self.fainted_box.activated.connect(lambda _i: self.set_format(model.FAINTED_KEY,
                                                                    self.fainted_box.currentText()))
      form.addRow("Target fainted", self.fainted_box)
      ## Most creatures a party brings (minimum: the layout's party size).
      self.party_max = QtWidgets.QSpinBox()
      self.party_max.setSpecialValueText(PARTY_SIZE_TEXT)
      self.party_max.editingFinished.connect(lambda: self._party_max_changed())
      form.addRow(self.term_label("party", False, "Most per {}"), self.party_max)
      layout.addLayout(form)
      tables = QtWidgets.QHBoxLayout()
      ## Screen place per position.
      self.places = self._table(PLACE_COLUMNS, model.LAYOUT_KEY)
      ## Stand per side.
      self.stands = self._table(STAND_COLUMNS, model.STANDS_KEY)
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Screen places"))
      left.addWidget(self.places, TABLE_STRETCH)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(QtWidgets.QLabel("Presenter stands"))
      right.addWidget(self.stands, TABLE_STRETCH)
      right.addWidget(button("At first positions", lambda: self.clear_stands(),
                             "Drop the format's own stands: each side stands at its first position"))
      tables.addLayout(left)
      tables.addLayout(right)
      layout.addLayout(tables, TABLE_STRETCH)
      ## The battle screen with the places and stands.
      self.preview = PresenterPreview()
      layout.addWidget(self.preview)

   def _table(self, headers: list[str], what: str) -> QtWidgets.QTableWidget:
      """!A places or stands table.
      @param headers  column headers
      @param what     model.LAYOUT_KEY or model.STANDS_KEY
      @return the table
      """
      t = QtWidgets.QTableWidget(0, len(headers))
      t.setHorizontalHeaderLabels(headers)
      t.verticalHeader().setVisible(False)
      t.setMinimumHeight(table_height(model.position_limits()[0]))   # every position without scrolling
      t.itemChanged.connect(lambda item: self._place_changed(what, item))
      return t

   def row(self) -> dict[str, Any] | None:
      """!The selected format as format_rows() gives it.
      @return the row, or None
      """
      doc = self.battle_doc()
      if doc is None or self.selected is None:
         return None
      return next((r for r in model.format_rows(doc) if r["name"] == self.selected), None)

   def fill_form(self, entry: JsonDict | None) -> None:
      """!Shows the selected format.
      @param entry  dict, or None
      @return None
      """
      row = self.row() if entry is not None else None
      enabled = row is not None
      for w in (self.side_count, self.range_box, self.fainted_box, self.party_max, self.places, self.stands):
         set_enabled(w, enabled)   # the tables go read-only and keep their scroll bars
      if row is None:
         return
      for w in [self.side_count] + self.side_spins:
         w.blockSignals(True)
      try:
         self.side_count.setValue(len(row["sides"]))
         for s, spin in enumerate(self.side_spins):
            spin.setVisible(s < len(row["sides"]))
            spin.setValue(len(row["sides"][s]) if s < len(row["sides"]) else 1)
      finally:
         for w in [self.side_count] + self.side_spins:
            w.blockSignals(False)
      set_combo(self.range_box, model.format_ranges(), row["range"])
      set_combo(self.fainted_box, model.fainted_rules(), row["on_target_fainted"])
      doc = self.battle_doc()
      self.party_max.setRange(0, model.party_size(doc))
      set_spin(self.party_max, row["party_max"] if row["party_max"] is not None else 0)
      side_of = {p: s for s, side in enumerate(row["sides"]) for p in side}
      self._fill_table(self.places, [[str(q), str(side_of.get(q, "?")), str(x), str(y)]
                                     for q, (x, y) in enumerate(row["layout"])], model.LAYOUT_KEY)
      self._fill_table(self.stands, [[str(s), str(x), str(y)] for s, (x, y) in enumerate(row["stands"])],
                       model.STANDS_KEY)
      mark_default(self.stands, not row["own_stands"])
      self.preview.set_layout((battle.DEFAULT_SCREEN_WIDTH, battle.DEFAULT_SCREEN_HEIGHT),
                              [tuple(p) for p in row["layout"]], [tuple(p) for p in row["stands"]],
                              battle.DEFAULT_BLEND_MAX)
      self.preview.set_sprite(None, row["error"] or f"{row['name']}: {row['positions']} positions")

   def _fill_table(self, table: QtWidgets.QTableWidget, rows: list[list[str]], what: str) -> None:
      """!Fills a places or stands table (only x and y are editable).
      @param table  the table
      @param rows   cell texts per row
      @param what   model.LAYOUT_KEY or model.STANDS_KEY
      @return None
      """
      table.blockSignals(True)
      try:
         table.setRowCount(len(rows))
         for r, cells in enumerate(rows):
            for c, text in enumerate(cells):
               item = QtWidgets.QTableWidgetItem(text)
               if c < PLACE_X[what]:
                  item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
               table.setItem(r, c, item)
         table.resizeColumnsToContents()
      finally:
         table.blockSignals(False)

   # -- editing ------------------------------------------------------------------------

   def _run(self, label: str, fn: Any) -> bool:
      """!One edit of the selected format; a refused one refreshes the form back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      if self._filling or self.selected is None:
         return False
      ok = self.edit(label, fn)
      if not ok:
         self.host.changed()
      return ok

   def set_format(self, key: str, value: Any) -> bool:
      """!Sets range, party_max or on_target_fainted of the selected format.
      @param key    model.RANGE_KEY, PARTY_MAX_KEY or FAINTED_KEY
      @param value  the value (None: the default)
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      return self._run(f"Format {key}", lambda: model.set_format_field(doc, name, key, value))

   def _party_max_changed(self) -> None:
      """!The party_max spin was edited (its minimum: no limit).
      @return None
      """
      v = self.party_max.value()
      self.set_format(model.PARTY_MAX_KEY, v if v > 0 else None)

   def _sides_changed(self) -> None:
      """!A side count spin changed.
      @return None
      """
      n = self.side_count.value()
      self.set_sides([s.value() for s in self.side_spins[:n]])

   def set_sides(self, counts: list[int]) -> bool:
      """!Gives the selected format these many positions per side.
      @param counts  positions per side
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      return self._run("Format sides", lambda: model.set_sides(doc, name, counts))

   def _place_changed(self, what: str, item: QtWidgets.QTableWidgetItem) -> None:
      """!An x or y cell was typed.
      @param what  model.LAYOUT_KEY or model.STANDS_KEY
      @param item  the cell
      @return None
      """
      table = self.places if what == model.LAYOUT_KEY else self.stands
      x_col = PLACE_X[what]
      try:
         x, y = int(table.item(item.row(), x_col).text()), int(table.item(item.row(), x_col + 1).text())
      except (ValueError, AttributeError):
         self.host.show_status("Screen coordinates are whole numbers.")
         self.host.changed()
         return
      self.set_place(what, item.row(), x, y)

   def set_place(self, what: str, index: int, x: int, y: int) -> bool:
      """!Moves a position's place or a side's stand.
      @param what   model.LAYOUT_KEY or model.STANDS_KEY
      @param index  position or side
      @param x      screen x
      @param y      screen y
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      return self._run("Format place", lambda: model.set_place(doc, name, what, index, x, y))

   def clear_stands(self) -> bool:
      """!Drops the selected format's own stands.
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      return self._run("Format stands", lambda: model.clear_stands(doc, name))

   def delete_entry(self) -> None:
      """!Deletes the selected format (refused for the last one and while named).
      @return None
      """
      if self.selected is None:
         return
      doc, name = self.battle_doc(), self.selected
      if self.edit("Delete format", lambda: model.remove_format(doc, name)):
         self.selected = None


class TurnPanel(BattlePanel):
   """!The turn structure.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "turn"
   ## See EditorPanel.title.
   title = "Turn"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the page.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      lo, hi = model.bracket_range()
      ## Bracket spins by name.
      self.brackets = {}
      top = QtWidgets.QHBoxLayout()
      group = QtWidgets.QGroupBox("Action brackets (bigger acts first)")
      form = QtWidgets.QFormLayout(group)
      for name in model.bracket_names():
         s = QtWidgets.QSpinBox()
         s.setRange(lo, hi)
         s.editingFinished.connect(lambda n=name, w=s: self.set_bracket(n, w.value()))
         self.brackets[name] = s
         if name == model.MOVE_BRACKET:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(s)
            ## The move bracket is each move's own priority.
            self.move_priority = QtWidgets.QCheckBox("each move's priority")
            self.move_priority.clicked.connect(lambda on: self.set_bracket(
               model.MOVE_BRACKET, model.move_priority() if on else self.brackets[model.MOVE_BRACKET].value()))
            row.addWidget(self.move_priority)
            form.addRow(name, row)
         else:
            form.addRow(name, s)
      form.addRow(button("Engine default", lambda: self.reset(model.BRACKETS_KEY), "The engine's brackets"))
      top.addWidget(group)
      group = QtWidgets.QGroupBox("Order")
      form = QtWidgets.QFormLayout(group)
      ## Choice combos by turn key.
      self.choices = {}
      for key, label, words in ((model.TIE_KEY, "Speed tie", model.tie_rules),
                                (f"{model.SWITCHING_KEY}.send_out", "Send out", model.send_orders),
                                (f"{model.SWITCHING_KEY}.switch_in", "Switch-in hooks", model.switch_in_orders)):
         c = QtWidgets.QComboBox()
         c.activated.connect(lambda _i, k=key, w=c: self.set_choice(k, w.currentText()))
         self.choices[key] = (c, words)
         form.addRow(label, c)
      ## Hook dispatch order (drag to reorder).
      self.order = QtWidgets.QListWidget()
      self.order.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
      self.order.model().rowsMoved.connect(lambda *a: self._order_dragged())
      form.addRow("Effect order", self.order)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Up", lambda: self.move_source(-1), "Earlier in the dispatch order"))
      row.addWidget(button("Down", lambda: self.move_source(1), "Later in the dispatch order"))
      row.addWidget(button("Engine default", lambda: self.reset(model.ORDER_KEY), "The engine's order"))
      form.addRow(row)
      ## B2: whether an egg may be sent into battle (structure rules.allow_eggs; refused by default).
      self.allow_eggs = QtWidgets.QCheckBox("Eggs may battle")
      self.allow_eggs.setToolTip("Battle setup sends no egg in unless this is on (rules.allow_eggs)")
      self.allow_eggs.clicked.connect(lambda on: self.set_allow_eggs(bool(on)))
      form.addRow(self.allow_eggs)
      top.addWidget(group)
      group = QtWidgets.QGroupBox("End of turn, in order")
      lay = QtWidgets.QVBoxLayout(group)
      ## End-of-turn phases (drag to reorder).
      self.phases = QtWidgets.QListWidget()
      self.phases.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
      self.phases.model().rowsMoved.connect(lambda _p, start, _e, _d, row: self._phase_dragged(start, row))
      self.phases.currentRowChanged.connect(lambda _r: self._fill_phase())
      lay.addWidget(self.phases)
      ## What the selected phase runs (core.structure.turn.phase_note(); E13b: the delayed phase).
      self.phase_note = QtWidgets.QLabel()
      self.phase_note.setWordWrap(True)
      lay.addWidget(self.phase_note)
      row = QtWidgets.QHBoxLayout()
      ## Kind of the phase to add.
      self.phase_kind = QtWidgets.QComboBox()
      row.addWidget(self.phase_kind)
      row.addWidget(button("Add", lambda: self.add_phase(self.phase_kind.currentText()), "Add after the selected"))
      row.addWidget(button("Remove", lambda: self.remove_phase(), "Remove the selected phase"))
      row.addWidget(button("Up", lambda: self.move_phase(-1)))
      row.addWidget(button("Down", lambda: self.move_phase(1)))
      lay.addLayout(row)
      ## Uses the effect order (a battlers phase without its own sources).
      self.use_order = QtWidgets.QCheckBox("Sources: the effect order")
      self.use_order.clicked.connect(lambda on: self._use_order_clicked(bool(on)))
      lay.addWidget(self.use_order)
      ## A battlers phase's own sources.
      self.sources = NameChecks(lambda names: self.set_phase_sources(names))
      lay.addWidget(self.sources)
      ## For whom a sides / field phase runs.
      self.each = QtWidgets.QComboBox()
      self.each.activated.connect(lambda _i: self.set_phase_each(self.each.currentText()))
      each_row = QtWidgets.QHBoxLayout()
      each_row.addWidget(QtWidgets.QLabel("Residual for"))
      each_row.addWidget(self.each)
      lay.addLayout(each_row)
      lay.addWidget(button("Engine default", lambda: self.reset(model.END_KEY), "The engine's phases"))
      top.addWidget(group)
      outer = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("The turn: who acts first (brackets, then speed, then the tie rule), the order "
                              "hooks are dispatched in, and what the end of each turn runs. Grey: the engine's "
                              "default (the manifest leaves it out).")
      note.setWordWrap(True)
      outer.addWidget(note)
      outer.addLayout(top, 1)
      outer.addWidget(self.errors)

   # -- reading ------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the turn structure.
      @return None
      """
      doc = self.battle_doc()
      self._filling = True
      try:
         if doc is not None:
            value, defaulted = model.turn_value(doc)
            br = value[model.BRACKETS_KEY]
            for name, s in self.brackets.items():
               v = br.get(name)
               set_spin(s, v if isinstance(v, int) else 0)
               mark_default(s, f"{model.BRACKETS_KEY}.{name}" in defaulted)
            priority = br.get(model.MOVE_BRACKET) == model.move_priority()
            self.move_priority.setChecked(priority)
            self.brackets[model.MOVE_BRACKET].setEnabled(not priority)
            for key, (c, words) in self.choices.items():
               part, _dot, sub = key.partition(".")
               set_combo(c, words(), value[part][sub] if sub else value[part])
               mark_default(c, key in defaulted if not sub else key in defaulted)
            self.order.clear()
            self.order.addItems(value[model.ORDER_KEY])
            set_check(self.allow_eggs, nursery_model.allowed(doc, "rules"))
            mark_default(self.order, model.ORDER_KEY in defaulted)
            current = self.phases.currentRow()
            rows = model.phase_rows(doc)
            self.phases.clear()
            for r in rows:
               extra = ""
               if r["run"] == model.BATTLERS_PHASE:
                  extra = ": " + ", ".join(r["runs"])
               elif r["each"] is not None:
                  extra = f": each {r['each']}"
               self.phases.addItem(f"{r['index']} {r['run']}{extra}")
            mark_default(self.phases, model.END_KEY in defaulted)
            self.phases.setCurrentRow(min(max(current, 0), len(rows) - 1))
            self.phase_kind.clear()
            for k, run in enumerate(model.end_phases()):
               self.phase_kind.addItem(run)
               self.phase_kind.setItemData(k, model.phase_note(run), QtCore.Qt.ItemDataRole.ToolTipRole)
      finally:
         self._filling = False
      self._fill_phase()
      set_enabled(self, doc is not None)
      self.show_errors()

   def set_allow_eggs(self, on: bool) -> bool:
      """!Sets whether eggs may battle (B2: core.structure.nursery.set_refusal()).
      @param on  True: battle setup may send an egg in
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or self._filling:
         return False
      ok = self.edit("Eggs may battle", lambda: nursery_model.set_refusal(doc, "rules", "", on))
      if not ok:
         self.host.changed()
      return ok

   def _fill_phase(self) -> None:
      """!Shows the selected phase's sources or "each".
      @return None
      """
      doc = self.battle_doc()
      rows = model.phase_rows(doc) if doc is not None else []
      i = self.phases.currentRow()
      row = rows[i] if 0 <= i < len(rows) else None
      battlers = row is not None and row["run"] == model.BATTLERS_PHASE
      self.phase_note.setText(f"{row['run']}: {model.phase_note(row['run'])}" if row is not None else "")
      self.use_order.setVisible(battlers)
      self.sources.setVisible(battlers)
      self.each.setEnabled(row is not None and row["each"] is not None)
      if battlers:
         self.use_order.setChecked(row["sources"] is None)
         set_enabled(self.sources, row["sources"] is not None)   # read-only, still scrolling
         order = model.effect_order(doc)
         self.sources.set_names(row["runs"] + [s for s in order if s not in row["runs"]], row["runs"])
      set_combo(self.each, model.phase_each(), row["each"] if row is not None and row["each"] else None)

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

   def set_bracket(self, name: str, value: int | str | None) -> bool:
      """!Sets an action bracket.
      @param name   the bracket
      @param value  a number, the move-priority word, or None
      @return True when it went through
      """
      doc = self.battle_doc()
      return self._run("Turn bracket", lambda: model.set_bracket(doc, name, value))

   def set_choice(self, key: str, value: str | None) -> bool:
      """!Sets the tie rule or a switching order.
      @param key    turn key
      @param value  its word, or None
      @return True when it went through
      """
      doc = self.battle_doc()
      return self._run(f"Turn {key}", lambda: model.set_choice(doc, key, value))

   def selected_source(self) -> str | None:
      """!The selected source of the effect order.
      @return name, or None
      """
      item = self.order.currentItem()
      return item.text() if item is not None else None

   def move_source(self, delta: int, name: str | None = None) -> bool:
      """!Moves a source in the dispatch order.
      @param delta  -1 earlier, +1 later
      @param name   the source, or None for the selected one
      @return True when it went through
      """
      doc, name = self.battle_doc(), name or self.selected_source()
      if name is None:
         return False
      row = self.order.currentRow() + delta
      ok = self._run("Effect order", lambda: model.move_source(doc, name, delta))
      if ok:
         self.order.setCurrentRow(row)
      return ok

   def _order_dragged(self) -> None:
      """!The effect order was dragged: writes the new order.
      @return None
      """
      if self._filling:
         return
      order = [self.order.item(i).text() for i in range(self.order.count())]
      doc = self.battle_doc()
      self._run("Effect order", lambda: model.set_effect_order(doc, order))

   def add_phase(self, run: str) -> bool:
      """!Adds a phase after the selected one.
      @param run  phase kind
      @return True when it went through
      """
      doc = self.battle_doc()
      at = self.phases.currentRow() + 1 if self.phases.currentRow() >= 0 else None
      return self._run("Add phase", lambda: model.add_phase(doc, run, at))

   def remove_phase(self) -> bool:
      """!Removes the selected phase.
      @return True when it went through
      """
      doc, i = self.battle_doc(), self.phases.currentRow()
      return i >= 0 and self._run("Remove phase", lambda: model.remove_phase(doc, i))

   def move_phase(self, delta: int) -> bool:
      """!Moves the selected phase.
      @param delta  -1 earlier, +1 later
      @return True when it went through
      """
      doc, i = self.battle_doc(), self.phases.currentRow()
      ok = i >= 0 and self._run("Move phase", lambda: model.move_phase(doc, i, delta))
      if ok:
         self.phases.setCurrentRow(i + delta)
      return ok

   def _phase_dragged(self, start: int, row: int) -> None:
      """!A phase was dragged.
      @param start  its old row
      @param row    the row it was dropped before
      @return None
      """
      if self._filling:
         return
      to = row - 1 if row > start else row
      doc = self.battle_doc()
      self._run("Move phase", lambda: model.move_phase_to(doc, start, to))

   def _use_order_clicked(self, on: bool) -> None:
      """!"Sources: the effect order" was clicked.
      @param on  ticked
      @return None
      """
      self.set_phase_sources(None if on else self.sources.checked() or model.effect_order(self.battle_doc()))

   def set_phase_sources(self, names: list[str] | None) -> bool:
      """!Sets the selected battlers phase's sources.
      @param names  sources in order, or None for the effect order
      @return True when it went through
      """
      doc, i = self.battle_doc(), self.phases.currentRow()
      return i >= 0 and self._run("Phase sources", lambda: model.set_phase_sources(doc, i, names))

   def set_phase_each(self, each: str | None) -> bool:
      """!Sets for whom the selected sides / field phase runs.
      @param each  word, or None
      @return True when it went through
      """
      doc, i = self.battle_doc(), self.phases.currentRow()
      return i >= 0 and self._run("Phase each", lambda: model.set_phase_each(doc, i, each))

   def reset(self, key: str) -> bool:
      """!Gives a part of the turn back to the engine.
      @param key  model.BRACKETS_KEY, END_KEY, ORDER_KEY, ...
      @return True when it went through
      """
      doc = self.battle_doc()
      return self._run("Engine default", lambda: model.reset(doc, key))
