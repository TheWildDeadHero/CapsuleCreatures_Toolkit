"""!Widgets the battle record forms share (Structure > Conditions, Flags &
Tags, Content > Passives / Items): a checkable name list, a record's texts
table, a manifest point handler table and budget bars.

Each widget only shows values and reports what the user changed through the
callbacks it is given; the panel makes the edit (host.run_edit(), one undo
step) and refreshes it.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import holders
from ...core.structure import conditions as cond_model
from ..widgets import button, set_contents_enabled
from .battle_common import set_combo

## Rows a name list shows before it scrolls.
NAME_ROWS = 4
## Height of one name list row, pixels (its height = rows x this + frame).
NAME_ROW_HEIGHT = 20
## Extra height of a list frame, pixels.
LIST_FRAME = 6
## Texts table columns.
TEXT_COLUMNS = ["Slot", "Kind", "Text or message", "Engine says"]
## Texts table column of the slot.
SLOT_COLUMN = 0
## Texts table column of the kind combo (text or engine message).
TEXT_KIND_COLUMN = 1
## Texts table column of the value.
TEXT_VALUE_COLUMN = 2
## Texts table column of the encoder's verdict.
TEXT_PROBLEM_COLUMN = 3
## Widest the encoder's verdict column gets, pixels (the full text is its tool tip).
PROBLEM_WIDTH = 260
## Kind combo choice: an own text.
TEXT_KIND = "text"
## Kind combo choice: an engine message.
MESSAGE_KIND = "message"
## Rows the texts table shows before it scrolls.
TEXT_ROWS = 5
## Handler table columns.
HANDLER_COLUMNS = ["Point", "Code (after point NAME)"]
## Handler table column of the point combo.
POINT_COLUMN = 0
## Handler table column of the code.
CODE_COLUMN = 1
## Rows the handler table shows before it scrolls.
HANDLER_ROWS = 3
## The effect language's comment mark (a comment runs to the end of its line).
COMMENT_MARK = "#"
## Title of the manifest point handlers box (passives, items, statuses, weathers).
MANIFEST_HANDLERS_TITLE = "Manifest point handlers"
## Title of the box of an owner's .ceffect point members (moves, volatiles, side conditions; E13b).
LOGIC_HANDLERS_TITLE = "Point handlers (effect logic)"
## Note of the manifest point handlers box.
MANIFEST_HANDLERS_NOTE = ("Each runs at a ruleset point (the text after `point NAME` of a .ceffect point member); "
                          "the entry's other logic is on Logic > Effects.")
## Note of the logic point handlers box.
LOGIC_HANDLERS_NOTE = ("Each is a `point NAME` member of the entry's .ceffect logic (written into its logic block; "
                       "a new block when it has none) and runs at a ruleset point whose sources take this kind. "
                       "The entry's other logic is on Logic > Effects.")
## Height of a table row, pixels (tables size to their rows).
TABLE_ROW_HEIGHT = 26
## Extra height of a table (header and frame), pixels.
TABLE_FRAME = 30
## Text colour of a problem.
PROBLEM_COLOR = "#c03030"
## Text colour of "fine".
FINE_COLOR = "#2a7a2a"
## Text of an empty fixed slot.
EMPTY_SLOT_TEXT = ""
## Chunk colour of a budget bar within its limit (light: the bar's text stays readable on it).
BAR_OK = "#a8d8a8"
## Chunk colour of a budget bar over its limit.
BAR_OVER = "#f08080"
## Budget bars per row.
BARS_PER_ROW = 4
## Height of a budget bar, pixels.
BAR_HEIGHT = 18


def table_height(rows: int) -> int:
   """!The height of a table showing a number of rows without scrolling.
   @param rows  rows
   @return pixels
   """
   return TABLE_FRAME + rows * TABLE_ROW_HEIGHT


class NameChecks(QtWidgets.QListWidget):
   """!A short list of names, each with a check box; report(checked names) after a click."""

   def __init__(self, report: Callable[[list[str]], object], parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the list.
      @param report  callable(checked names, in list order)
      @param parent  parent widget
      """
      super().__init__(parent)
      ## Called with the checked names after the user ticks one.
      self.report = report
      ## True while set_names() fills the list.
      self._filling = False
      self.setFixedHeight(NAME_ROWS * NAME_ROW_HEIGHT + LIST_FRAME)
      self.itemChanged.connect(lambda _item: self._changed())

   def set_names(self, names: Sequence[str], checked: Sequence[str]) -> None:
      """!Shows names and ticks some (a checked name the list lacks is added, so odd data still shows).
      @param names    the names
      @param checked  the ticked ones
      @return None
      """
      self._filling = True
      try:
         self.clear()
         for n in list(names) + [c for c in checked if c not in names]:
            item = QtWidgets.QListWidgetItem(n)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked if n in checked else QtCore.Qt.CheckState.Unchecked)
            self.addItem(item)
      finally:
         self._filling = False
      # As tall as its names (one row at least, NAME_ROWS at most: it scrolls beyond).
      self.setFixedHeight(max(1, min(self.count(), NAME_ROWS)) * NAME_ROW_HEIGHT + LIST_FRAME)

   def checked(self) -> list[str]:
      """!The ticked names.
      @return names, in list order
      """
      return [self.item(i).text() for i in range(self.count())
              if self.item(i).checkState() == QtCore.Qt.CheckState.Checked]

   def set_checked(self, name: str, on: bool) -> None:
      """!Ticks or unticks one name as the user would (reports the change).
      @param name  the name
      @param on    ticked
      @return None
      """
      for i in range(self.count()):
         if self.item(i).text() == name:
            self.item(i).setCheckState(QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)

   def _changed(self) -> None:
      """!A box was ticked.
      @return None
      """
      if not self._filling:
         self.report(self.checked())


class TextsTable(QtWidgets.QWidget):
   """!A record's texts: one row per slot (a status's or weather's fixed slots; any slot of the other kinds,
   each an own text or an engine message), with what the engine's text encoder says about it."""

   def __init__(self, set_text: Callable[[str, Any], object], parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the table and its buttons.
      @param set_text  callable(slot, value: text, {"message": KEY} or None to remove)
      @param parent    parent widget
      """
      super().__init__(parent)
      ## Called with (slot, value) for each change.
      self.set_text = set_text
      ## True while the table is filled.
      self._filling = False
      ## The kind shown.
      self.kind = "status"
      ## Slots in row order.
      self.slots = []
      ## The engine messages a slot may name (core.structure.conditions.messages() of the open data).
      self.messages = []
      ## The texts.
      self.table = QtWidgets.QTableWidget(0, len(TEXT_COLUMNS))
      self.table.setHorizontalHeaderLabels(TEXT_COLUMNS)
      self.table.verticalHeader().setVisible(False)
      header = self.table.horizontalHeader()
      header.setSectionResizeMode(TEXT_VALUE_COLUMN, QtWidgets.QHeaderView.ResizeMode.Stretch)
      header.setSectionResizeMode(TEXT_PROBLEM_COLUMN, QtWidgets.QHeaderView.ResizeMode.Interactive)
      self.table.setMinimumHeight(table_height(TEXT_ROWS))
      self.table.itemChanged.connect(lambda item: self._item_changed(item))
      ## Adds a slot (kinds with owner texts).
      self.add_button = button("Add text...", lambda: self.add_slot(), "A text slot: start, already, end, skip "
                                                                      "or a name the record's logic shows")
      ## Removes the selected slot's text.
      self.remove_button = button("Remove text", lambda: self.remove_slot(), "Remove the selected text")
      lay = QtWidgets.QVBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(self.table)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.add_button)
      row.addWidget(self.remove_button)
      row.addStretch(1)
      lay.addLayout(row)

   def show_texts(self, kind: str, texts: list[tuple[str, Any]], problem: Callable[[Any], str | None],
                  messages: list[str] | None = None) -> None:
      """!Shows a record's texts.
      @param kind      condition kind
      @param texts     core.structure.conditions.texts_of() rows
      @param problem   callable(text) -> the encoder's problem or None
      @param messages  the engine messages a slot may name (core.structure.conditions.messages(doc)), or None for
                       the required ones
      @return None
      """
      self._filling = True
      try:
         self.messages = list(messages) if messages is not None else cond_model.messages()
         self.kind = kind
         fixed = bool(cond_model.fixed_slots(kind))
         self.add_button.setVisible(not fixed)
         self.slots = [slot for slot, _v in texts]
         self.table.setRowCount(len(texts))
         editable = QtCore.Qt.ItemFlag.ItemIsEditable
         for r, (slot, value) in enumerate(texts):
            item = QtWidgets.QTableWidgetItem(slot)
            item.setFlags(item.flags() & ~editable)
            self.table.setItem(r, SLOT_COLUMN, item)
            is_message = isinstance(value, dict)
            if fixed:
               self.table.setCellWidget(r, TEXT_KIND_COLUMN, None)
               kind_item = QtWidgets.QTableWidgetItem(TEXT_KIND)
               kind_item.setFlags(kind_item.flags() & ~editable)
               self.table.setItem(r, TEXT_KIND_COLUMN, kind_item)
            else:
               box = QtWidgets.QComboBox()
               box.addItems([TEXT_KIND, MESSAGE_KIND])
               box.setCurrentText(MESSAGE_KIND if is_message else TEXT_KIND)
               box.activated.connect(lambda _i, s=slot, b=box: self._kind_picked(s, b.currentText()))
               self.table.setCellWidget(r, TEXT_KIND_COLUMN, box)
            if is_message:
               self.table.setItem(r, TEXT_VALUE_COLUMN, QtWidgets.QTableWidgetItem(""))
               msg = QtWidgets.QComboBox()
               set_combo(msg, self.messages, value.get(cond_model.MESSAGE_KEY))
               msg.activated.connect(lambda _i, s=slot, b=msg: self.set_text(
                  s, {cond_model.MESSAGE_KEY: b.currentText()}))
               self.table.setCellWidget(r, TEXT_VALUE_COLUMN, msg)
               verdict = "engine message"
            else:
               self.table.setCellWidget(r, TEXT_VALUE_COLUMN, None)
               self.table.setItem(r, TEXT_VALUE_COLUMN,
                                  QtWidgets.QTableWidgetItem(value if isinstance(value, str) else EMPTY_SLOT_TEXT))
               verdict = problem(value) if isinstance(value, str) else ("(none)" if value is None else None)
            note = QtWidgets.QTableWidgetItem(verdict or "fine")
            note.setFlags(note.flags() & ~editable)
            bad = verdict is not None and isinstance(value, str)
            note.setForeground(QtGui.QBrush(QtGui.QColor(PROBLEM_COLOR if bad else FINE_COLOR)))
            note.setToolTip(verdict or "")
            self.table.setItem(r, TEXT_PROBLEM_COLUMN, note)
         for c in (SLOT_COLUMN, TEXT_KIND_COLUMN, TEXT_PROBLEM_COLUMN):
            self.table.resizeColumnToContents(c)
         self.table.setColumnWidth(TEXT_PROBLEM_COLUMN, min(self.table.columnWidth(TEXT_PROBLEM_COLUMN),
                                                            PROBLEM_WIDTH))
      finally:
         self._filling = False

   def _item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A text was typed (an empty one removes the text).
      @param item  the cell
      @return None
      """
      if self._filling or item.column() != TEXT_VALUE_COLUMN or not 0 <= item.row() < len(self.slots):
         return
      text = item.text()
      self.set_text(self.slots[item.row()], text if text.strip() else None)

   def _kind_picked(self, slot: str, kind: str) -> None:
      """!A slot became a text or an engine message.
      @param slot  the slot
      @param kind  TEXT_KIND or MESSAGE_KIND
      @return None
      """
      if kind == MESSAGE_KIND:
         self.set_text(slot, {cond_model.MESSAGE_KEY: (self.messages or cond_model.messages())[0]})
      else:
         self.set_text(slot, "{user}")

   def add_slot(self, slot: str | None = None, text: str = "{user}") -> None:
      """!Adds a text slot.
      @param slot  the slot, or None to ask (the template slots the record lacks are offered first)
      @param text  its first text
      @return None
      """
      if slot is None:
         offered = [s for s in cond_model.template_slots(self.kind) if s not in self.slots]
         slot, ok = QtWidgets.QInputDialog.getItem(self, "Add text", "Slot:", offered, 0, True)
         if not ok:
            return
      if slot.strip():
         self.set_text(slot.strip(), text)

   def remove_slot(self) -> None:
      """!Removes the selected row's text.
      @return None
      """
      r = self.table.currentRow()
      if 0 <= r < len(self.slots):
         self.set_text(self.slots[r], None)


def one_line(code: str) -> str:
   """!Handler code as one table line: its lines joined by spaces (the effect language ignores line breaks), unless
   a `#` comment would then swallow the rest (such code is shown as written).
   @param code  handler code
   @return the text to show and edit
   """
   if COMMENT_MARK in code:
      return code
   return " ".join(line.strip() for line in code.splitlines() if line.strip())


class PointHandlersBox(QtWidgets.QGroupBox):
   """!An entry's point handlers (core.holders): point and code per row, with add / remove / order. The manifest's
   "handlers" of a passive, item, status or weather; E13b: the `.ceffect` point members of a move, volatile or side
   condition (in_logic: core.holders writes them into the owner's logic block)."""

   def __init__(self, edit: Callable[[str, Callable[[], object]], bool], doc_of: Callable[[], Any],
                parent: QtWidgets.QWidget | None = None, in_logic: bool = False) -> None:
      """!Builds the table and its buttons.
      @param edit      callable(undo label, fn) running one battle edit (BattlePanel.edit)
      @param doc_of    callable() -> the battle Document, or None
      @param parent    parent widget
      @param in_logic  the handlers are the owner's .ceffect point members (core.holders.logic_lists())
      """
      super().__init__(LOGIC_HANDLERS_TITLE if in_logic else MANIFEST_HANDLERS_TITLE, parent)
      ## True when the handlers are point members of the owner's logic.
      self.in_logic = in_logic
      ## Runs one edit.
      self.edit = edit
      ## Gives the battle Document.
      self.doc_of = doc_of
      ## True while the table is filled.
      self._filling = False
      ## (manifest list, entry name) shown, or None.
      self.owner = None
      ## The points the owner may handle.
      self.choices = []
      ## Point and code per handler.
      self.table = QtWidgets.QTableWidget(0, len(HANDLER_COLUMNS))
      self.table.setHorizontalHeaderLabels(HANDLER_COLUMNS)
      self.table.verticalHeader().setVisible(False)
      self.table.horizontalHeader().setStretchLastSection(True)
      self.table.setMinimumHeight(table_height(HANDLER_ROWS))
      self.table.itemChanged.connect(lambda item: self._code_changed(item))
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel(LOGIC_HANDLERS_NOTE if in_logic else MANIFEST_HANDLERS_NOTE)
      note.setWordWrap(True)
      lay.addWidget(note)
      lay.addWidget(self.table)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add", lambda: self.add_handler(), "A handler of the first point it may handle, x1"))
      row.addWidget(button("Remove", lambda: self.remove_handler(), "Remove the selected handler"))
      row.addWidget(button("Up", lambda: self.move_handler(-1), "Earlier (handlers of one point run in order)"))
      row.addWidget(button("Down", lambda: self.move_handler(1), "Later"))
      row.addStretch(1)
      lay.addLayout(row)

   def show_handlers(self, owner: tuple[str, str] | None, rows: list[dict[str, Any]], choices: list[str]) -> None:
      """!Shows an entry's handlers.
      @param owner    (manifest list, entry name), or None for nothing
      @param rows     core.holders.handlers() result
      @param choices  core.holders.point_choices()
      @return None
      """
      self._filling = True
      try:
         self.owner = owner
         self.choices = list(choices)
         self.table.setRowCount(len(rows))
         for r, h in enumerate(rows):
            box = QtWidgets.QComboBox()
            set_combo(box, self.choices, h.get("point"))
            box.activated.connect(lambda _i, k=r, b=box: self._point_picked(k, b.currentText()))
            self.table.setCellWidget(r, POINT_COLUMN, box)
            self.table.setItem(r, POINT_COLUMN, QtWidgets.QTableWidgetItem(""))
            code = str(h.get("code", ""))
            cell = QtWidgets.QTableWidgetItem(one_line(code))
            cell.setToolTip(code)
            self.table.setItem(r, CODE_COLUMN, cell)
         self.table.resizeColumnToContents(POINT_COLUMN)
         set_contents_enabled(self, owner is not None)   # the table goes read-only and keeps its scroll bars
      finally:
         self._filling = False

   def _run(self, label: str, fn: Callable[[Any, Any, str, str], object]) -> bool:
      """!One edit of the shown entry's handlers.
      @param label  undo label
      @param fn     callable(core.holders, battle Document, manifest list, entry name)
      @return True when it went through
      """
      doc = self.doc_of()
      if self.owner is None or doc is None:
         return False
      key, name = self.owner
      return self.edit(label, lambda: fn(holders, doc, key, name))

   def add_handler(self, point: str | None = None, code: str | None = None) -> bool:
      """!Adds a handler.
      @param point  its point, or None for the first choice
      @param code   its code, or None for x1
      @return True when added
      """
      point = point if point is not None else (self.choices[0] if self.choices else None)
      if point is None:
         return False
      choices = list(self.choices)
      return self._run("Add point handler", lambda h, d, k, n: h.add_handler(
         d, k, n, point, code if code is not None else h.NEW_CODE, choices))

   def remove_handler(self) -> bool:
      """!Removes the selected handler.
      @return True when removed
      """
      r = self.table.currentRow()
      if r < 0:
         return False
      return self._run("Remove point handler", lambda h, d, k, n: h.remove_handler(d, k, n, r))

   def move_handler(self, delta: int) -> bool:
      """!Moves the selected handler.
      @param delta  -1 up, +1 down
      @return True when the edit ran
      """
      r = self.table.currentRow()
      if r < 0:
         return False
      return self._run("Move point handler", lambda h, d, k, n: h.move_handler(d, k, n, r, delta))

   def set_code(self, row: int, code: str) -> bool:
      """!Changes a handler's code.
      @param row   the handler
      @param code  its code
      @return True when the edit went through
      """
      return self._run("Point handler code", lambda h, d, k, n: h.set_handler(d, k, n, row, None, code))

   def _point_picked(self, row: int, point: str) -> None:
      """!A handler's point was picked.
      @param row    the handler
      @param point  the point
      @return None
      """
      choices = list(self.choices)
      self._run("Point handler point", lambda h, d, k, n: h.set_handler(d, k, n, row, point, None, choices))

   def _code_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A code cell was typed.
      @param item  the cell
      @return None
      """
      if not self._filling and item.column() == CODE_COLUMN:
         self.set_code(item.row(), item.text())


class BudgetBars(QtWidgets.QWidget):
   """!A row of bars, one per budget (used of the engine's most; red when over)."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the empty bar grid.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The bars by label.
      self.bars = {}
      ## Their grid.
      self.grid = QtWidgets.QGridLayout(self)
      self.grid.setContentsMargins(0, 0, 0, 0)

   def show_budget(self, rows: Sequence[Any]) -> None:
      """!Shows budgets.
      @param rows  core.structure.conditions.BudgetRow (label, used, most, note) or the same shape
      @return None
      """
      for i, row in enumerate(rows):
         bar = self.bars.get(row.label)
         if bar is None:
            bar = self.bars[row.label] = QtWidgets.QProgressBar()
            bar.setMaximumHeight(BAR_HEIGHT)
            self.grid.addWidget(bar, i // BARS_PER_ROW, i % BARS_PER_ROW)
         over = row.used > row.most
         bar.setRange(0, max(row.most, 1))
         bar.setValue(min(row.used, row.most))
         bar.setFormat(f"{row.label} {row.used}/{row.most}")
         bar.setToolTip(row.note or row.label)
         bar.setStyleSheet(f"QProgressBar::chunk {{ background: {BAR_OVER if over else BAR_OK}; }}")

   def text_of(self, label: str) -> str:
      """!A bar's text.
      @param label  its budget label
      @return "label used/most", or "" when there is no such bar
      """
      bar = self.bars.get(label)
      return bar.format() if bar is not None else ""
