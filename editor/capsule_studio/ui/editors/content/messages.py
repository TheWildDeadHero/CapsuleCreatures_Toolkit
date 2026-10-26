"""!The Messages page (Content > Messages; engine C4, S11): the battle's
messages, the engine's and the ones the battle declares itself.

The table lists every message in message id order (core.messages.rows()):
the engine's required ones (always there), its optional ones (said only
where the data names them; one the data leaves out shows greyed with no id)
and the battle's own (any other lower-case key: effect logic says them with
`say KEY`, the chart's tiers and the condition records' texts name them).
Typing a text sets it (checked with the engine's encoder against the game's
code page and terms: the last column says what it would refuse); typing the
key of one of the battle's own renames it, and its uses follow. Add (one of
the battle's own, or an optional engine message), Remove (not a required
one, nor one still named) and Rename are one undo step each. The budget line
counts the battle's own against the most the engine's message ids leave.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import messages as msg_model
from ....core.document import DocumentError
from ...widgets import button
from ..battle_common import BattlePanel, set_combo

if TYPE_CHECKING:
   from ...panel import PanelHost

## Table columns.
COLUMNS = ["Id", "Key", "Kind", "Takes", "Text", "Engine says"]
## Column of the message id.
ID_COLUMN = 0
## Column of the key (typing renames one of the battle's own).
KEY_COLUMN = 1
## Column of the kind.
KIND_COLUMN = 2
## Column of the placeholders a message takes.
ARGS_COLUMN = 3
## Column of the text (typing sets it).
TEXT_COLUMN = 4
## Column of the encoder's verdict.
PROBLEM_COLUMN = 5
## Shown in the id / text column of an optional message the data leaves out.
ABSENT_TEXT = "-"
## Colour of an optional message the data leaves out.
ABSENT_COLOR = "#808080"
## Colour of a text the engine refuses.
PROBLEM_COLOR = "#c03030"
## Colour of the budget line within its limit.
WITHIN_COLOR = "#2a7a2a"
## What the page says above the table.
NOTE = ("The engine says its required messages; an optional one is said only where the data names it (add it "
        "to give its text). A message of the battle's own (a lower-case key) comes after the engine's: effect logic "
        "says it (say KEY), tiers and condition texts name it. Type a text to set it; type a key of the battle's "
        "own to rename it (its uses follow).")


class MessagesPanel(BattlePanel):
   """!The battle's messages.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "messages"
   ## See EditorPanel.title.
   title = "Messages"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the budget line, the table and the buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected message's key, or None.
      self.selected = None
      ## The keys in table order (rows()).
      self.keys = []
      ## The battle's own messages against the most.
      self.budget = QtWidgets.QLabel()
      ## The messages.
      self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
      self.table.setHorizontalHeaderLabels(COLUMNS)
      self.table.verticalHeader().setVisible(False)
      # the text takes the room (the verdict is short or empty)
      self.table.horizontalHeader().setSectionResizeMode(TEXT_COLUMN, QtWidgets.QHeaderView.ResizeMode.Stretch)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      ## The optional engine messages the data leaves out (Add optional takes the chosen one).
      self.optional = QtWidgets.QComboBox()
      ## Buttons that need a selection of a removable / renamable message.
      self.remove_button = button("Remove", lambda: self.remove_message(),
                                  "Remove the selected message (not a required one, nor one still named)")
      ## Renames the selected message of the battle's own.
      self.rename_button = button("Rename...", lambda: self.rename_message(),
                                  "Rename the selected message of the battle's own; its uses follow")
      ## Adds the chosen optional engine message.
      self.optional_button = button("Add optional", lambda: self.add_optional(),
                                    "Give the chosen optional engine message its text")
      ## What names the selected message.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      self.used_by.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add message...", lambda: self.add_message(),
                           "Declare a message of the battle's own (a lower-case key; the next message id)"))
      row.addWidget(self.remove_button)
      row.addWidget(self.rename_button)
      row.addStretch(1)
      row.addWidget(self.optional)
      row.addWidget(self.optional_button)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addWidget(self.budget)
      lay.addWidget(self.table, 1)
      lay.addLayout(row)
      lay.addWidget(self.used_by)
      lay.addWidget(self.errors)

   # -- reading -------------------------------------------------------------------------------------------------------

   def rows(self) -> list[msg_model.MessageRow]:
      """!The messages as the table shows them.
      @return core.messages.rows() ([] with nothing open)
      """
      doc = self.battle_doc()
      return msg_model.rows(doc) if doc is not None else []

   def refresh(self) -> None:
      """!Re-reads the messages, the budget and the optional ones left out.
      @return None
      """
      doc = self.battle_doc()
      rows = self.rows()
      keys = [r["key"] for r in rows]
      self.keys = keys
      chosen = self.selected
      chosen = chosen if chosen in keys else (keys[0] if keys else None)
      self.selected = chosen
      self._filling = True
      try:
         if doc is not None:
            own, most = len(msg_model.game_keys(doc)), msg_model.max_game_messages()
            self.budget.setText(f"{own} of at most {most} messages of the battle's own")
            self.budget.setStyleSheet(f"color: {WITHIN_COLOR if own <= most else PROBLEM_COLOR};")
         else:
            self.budget.setText("")
         self.table.setRowCount(len(rows))
         for r, row in enumerate(rows):
            self._fill_row(doc, r, row)
         self.table.resizeColumnsToContents()
         if chosen in keys:
            self.table.selectRow(keys.index(chosen))
         absent = msg_model.absent_optional(doc) if doc is not None else []
         keep = self.optional.currentText()
         set_combo(self.optional, absent, keep if keep in absent else (absent[0] if absent else None))
         self.optional_button.setEnabled(bool(absent))
         self._fill_selection()
      finally:
         self._filling = False
      self.setEnabled(doc is not None)
      self.show_errors()

   def _fill_row(self, doc: object, r: int, row: msg_model.MessageRow) -> None:
      """!Fills one table row.
      @param doc  the battle Document
      @param r    the row
      @param row  its MessageRow
      @return None
      """
      editable = QtCore.Qt.ItemFlag.ItemIsEditable
      absent = row["text"] is None
      problem = None if absent else msg_model.text_problem(doc, row["key"], row["text"])
      texts = {ID_COLUMN: ABSENT_TEXT if row["id"] is None else str(row["id"]), KEY_COLUMN: row["key"],
               KIND_COLUMN: row["kind"], ARGS_COLUMN: " ".join("{" + a + "}" for a in row["args"]),
               TEXT_COLUMN: ABSENT_TEXT if absent else row["text"], PROBLEM_COLUMN: problem or ""}
      for c, value in texts.items():
         item = QtWidgets.QTableWidgetItem(value)
         # the text of a message the data gives, and the key of one of the battle's own, are typed in place
         typed = (c == TEXT_COLUMN and not absent) or (c == KEY_COLUMN and row["kind"] == msg_model.GAME)
         if not typed:
            item.setFlags(item.flags() & ~editable)
         if absent:
            item.setForeground(QtGui.QColor(ABSENT_COLOR))
         if c == PROBLEM_COLUMN and problem:
            item.setForeground(QtGui.QColor(PROBLEM_COLOR))
            item.setToolTip(problem)
         self.table.setItem(r, c, item)

   def _fill_selection(self) -> None:
      """!Shows what names the selected message and which buttons apply to it.
      @return None
      """
      doc, key = self.battle_doc(), self.selected
      if doc is None or key is None:
         self.used_by.setText("")
         self.remove_button.setEnabled(False)
         self.rename_button.setEnabled(False)
         return
      kind = msg_model.kind_of(key)
      given = key in msg_model.given(doc)
      self.remove_button.setEnabled(given and kind != msg_model.REQUIRED)
      self.rename_button.setEnabled(given and kind == msg_model.GAME)
      try:
         users = msg_model.uses(doc, key)
      except DocumentError as e:
         self.used_by.setText(f"{key}: {e}")
         return
      if kind == msg_model.REQUIRED:
         said = "the engine says it"
      elif kind == msg_model.OPTIONAL:
         said = "the engine says it where the data names it"
      else:
         said = "a message of the battle's own"
      named = ", ".join(users) if users else "nothing in the data or logic"
      self.used_by.setText(f"{key} ({said}) is named by: {named}")

   def _selection_changed(self) -> None:
      """!Another row was picked.
      @return None
      """
      if self._filling:
         return
      rows = self.table.selectionModel().selectedRows()
      if rows and rows[0].row() < len(self.keys):
         self.selected = self.keys[rows[0].row()]
         self._fill_selection()

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A text was typed (sets it) or a key of the battle's own (renames it).
      @param item  the cell
      @return None
      """
      if self._filling or not 0 <= item.row() < len(self.keys):
         return
      key = self.keys[item.row()]
      if item.column() == TEXT_COLUMN:
         self.set_text(key, item.text())
      elif item.column() == KEY_COLUMN and item.text().strip() != key:
         self.rename_message(item.text().strip(), key)

   # -- editing -------------------------------------------------------------------------------------------------------

   def _edit(self, label: str, fn: object) -> bool:
      """!One edit; a refused one refreshes the page back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      ok = self.edit(label, fn)
      if not ok:
         self.host.changed()
      return ok

   def set_text(self, key: str, text: str) -> bool:
      """!Sets a message's text.
      @param key   the message
      @param text  its text
      @return True when it changed
      """
      doc = self.battle_doc()
      if doc is None or msg_model.given(doc).get(key) == text:
         return False
      return self._edit("Set message", lambda: msg_model.set_text(doc, key, text))

   def add_message(self, key: str | None = None, text: str | None = None) -> bool:
      """!Declares a message of the battle's own.
      @param key   its key, or None to ask
      @param text  its text, or None (empty)
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if key is None:
         key, ok = QtWidgets.QInputDialog.getText(self, "Add message", "Key (a lower-case identifier):")
         if not ok:
            return False
      if self._edit("Add message", lambda: msg_model.add(doc, key, text)):
         self.selected = key.strip()
         return True
      return False

   def add_optional(self, key: str | None = None) -> bool:
      """!Gives an optional engine message its text (the template's).
      @param key  the message, or None for the chosen one
      @return True when added
      """
      doc = self.battle_doc()
      key = key or self.optional.currentText()
      if doc is None or not key:
         return False
      if self._edit("Add message", lambda: msg_model.add(doc, key)):
         self.selected = key
         return True
      return False

   def remove_message(self) -> bool:
      """!Removes the selected message.
      @return True when removed
      """
      doc, key = self.battle_doc(), self.selected
      if doc is None or key is None:
         return False
      return self._edit("Remove message", lambda: msg_model.remove(doc, key))

   def rename_message(self, new: str | None = None, old: str | None = None) -> bool:
      """!Renames a message of the battle's own (its uses follow: one undo step).
      @param new  the new key, or None to ask
      @param old  the message, or None for the selected one
      @return True when renamed
      """
      doc = self.battle_doc()
      old = old or self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename message", "New key:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         self.host.changed()
         return False
      if self._edit("Rename message", lambda: msg_model.rename(doc, old, new)):
         self.selected = new.strip()
         return True
      return False
