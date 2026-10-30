"""!The transfer defaults box of the Record page (E2c, D-23 §3.2 "Record"):
monster_layout.transfer_defaults, what a record transfer (the engine's
capsule/monster/transfer.h) gives a stat the sending game does not have.

One row per stat, one column per per-stat role the layout holds (genes,
training, ...); a cell is that role's value, 0 (the engine's default) when
the layout names none. Typing a value sets that role's value; the "All"
column sets every role at once (the manifest's integer form); clearing a
cell drops it. Every change is one undo step through the panel's edit()
(core.structure.record.set_transfer_default()), refused with the engine's
message when the layout would stop compiling.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ....core.structure import record as model
from ...widgets import set_enabled

if TYPE_CHECKING:
   from ..battle_common import BattlePanel

## Header of the column that sets every per-stat role at once.
ALL_HEADER = "All"
## Text colour of a value the layout does not give (the engine's default).
DEFAULT_COLOR = "#909090"
## Column of the stat name.
STAT_COLUMN = 0
## Columns before the per-role ones: stat, all.
FIXED_COLUMNS = 2


class TransferDefaultsBox(QtWidgets.QGroupBox):
   """!The transfer defaults table.

   @var panel
   The battle panel whose edit() runs the changes.
   """

   def __init__(self, panel: BattlePanel) -> None:
      """!Builds the table.
      @param panel  the Record panel (edit(), battle_doc(), host)
      """
      super().__init__("Transfer defaults (a stat the sending game lacks)")
      ## The panel the box belongs to.
      self.panel = panel
      ## True while the box fills the table.
      self._filling = False
      ## Per-stat roles shown, in column order.
      self.roles = []
      ## The table: stats x (all, per-stat roles).
      self.table = QtWidgets.QTableWidget(0, FIXED_COLUMNS)
      self.table.verticalHeader().setVisible(False)
      self.table.itemChanged.connect(lambda item: self._changed(item))
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("Grey: the engine's 0. Type a value; empty a cell to drop it.")
      note.setWordWrap(True)
      lay.addWidget(note)
      lay.addWidget(self.table)

   def refresh(self) -> None:
      """!Re-reads the defaults.
      @return None
      """
      doc = self.panel.battle_doc()
      rows = model.transfer_defaults(doc) if doc is not None else []
      self.roles = model.per_stat_roles(doc) if doc is not None else []
      self._filling = True
      try:
         self.table.setColumnCount(FIXED_COLUMNS + len(self.roles))
         self.table.setHorizontalHeaderLabels(["Stat", ALL_HEADER] + self.roles)
         self.table.setRowCount(len(rows))
         for r, row in enumerate(rows):
            name = QtWidgets.QTableWidgetItem(row["stat"])
            name.setFlags(name.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, STAT_COLUMN, name)
            values = list(row["values"].values())
            same = row["given"] and row["uniform"] and values
            cells = [str(values[0]) if same else ""] + [str(v) for v in values]
            for c, text in enumerate(cells):
               item = QtWidgets.QTableWidgetItem(text)
               if not row["given"]:
                  item.setForeground(QtGui.QColor(DEFAULT_COLOR))
               self.table.setItem(r, STAT_COLUMN + 1 + c, item)
         self.table.resizeColumnsToContents()
      finally:
         self._filling = False
      set_enabled(self.table, doc is not None)   # read-only, still scrolling

   def _changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A value was typed: sets (or drops) it.
      @param item  the cell
      @return None
      """
      if self._filling or item.column() <= STAT_COLUMN:
         return
      stat = self.table.item(item.row(), STAT_COLUMN).text()
      role = None if item.column() == STAT_COLUMN + 1 else self.roles[item.column() - FIXED_COLUMNS]
      text = item.text().strip()
      if text and not text.isdigit():
         self.panel.host.show_status("Transfer defaults are whole numbers.")
         self.panel.host.changed()
         return
      self.set_default(stat, int(text) if text else None, role)

   def set_default(self, stat: str, value: int | None, role: str | None = None) -> bool:
      """!Sets a stat's transfer default (one undo step).
      @param stat   the stat
      @param value  the value, or None to drop it
      @param role   one per-stat role, or None for all
      @return True when the edit went through
      """
      doc = self.panel.battle_doc()
      if doc is None:
         return False
      ok = self.panel.edit("Transfer default", lambda: model.set_transfer_default(doc, stat, value, role))
      if not ok:
         self.panel.host.changed()
      return ok
