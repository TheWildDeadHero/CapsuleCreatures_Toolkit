"""!The Passive slots page (D-25 decision 6, engine C1): the structure
manifest's "passive_slots", the slots a species fills with its passives.

Each row is a slot in slot order: its name (typing renames it; the party
members naming it follow), whether the generation list may roll it (an
unrolled slot is one only data or logic gives, such as a hidden passive) and
how many species and party members use it. Add / Remove / Rename / Up / Down
edit the list as one undo step with the species' passives and the members'
slots (core.structure.passive_slots). The budget line shows the slots
against the engine's most on every target and the record's passive_selector
role (it must hold the last slot's number); the compile result shows at the
bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core.document import Document, DocumentError
from ....core.structure import passive_slots as slot_model
from ....core.structure import stats as stat_model
from ...widgets import ask, button
from ..battle_common import STRUCTURE, BattlePanel

if TYPE_CHECKING:
   from ...panel import PanelHost

## Slot table columns.
SLOT_COLUMNS = ["#", "Name", "Rolled", "Species", "Members"]
## Slot table column of the index.
INDEX_COLUMN = 0
## Slot table column of the name (typing renames).
NAME_COLUMN = 1
## Slot table column of the rolled box.
ROLLED_COLUMN = 2
## Slot table column of the species count.
SPECIES_COLUMN = 3
## Slot table column of the member count.
MEMBERS_COLUMN = 4
## Text colour of a budget over its limit.
OVER_COLOR = "#c03030"
## Text colour of a budget within its limit.
WITHIN_COLOR = "#2a7a2a"
## What the page says above the table.
NOTE = ("A species names one passive per slot (Content > Species); a party member names the slot its creature "
        "has (Content > Parties). The generation list's passive_selector entry rolls one of the rolled slots; an "
        "unrolled slot is one only data or logic gives (a hidden passive). Type a name to rename it.")


class PassiveSlotsPanel(BattlePanel):
   """!The passive slots per species.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "passive_slots"
   ## See EditorPanel.title.
   title = "Passive slots"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the budget line, the slot table and the buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected slot's name, or None.
      self.selected = None
      ## The slots against the engine's most and the passive_selector role.
      self.budget = QtWidgets.QLabel()
      self.budget.setWordWrap(True)
      ## The slots.
      self.table = QtWidgets.QTableWidget(0, len(SLOT_COLUMNS))
      self.table.setHorizontalHeaderLabels(SLOT_COLUMNS)
      self.table.verticalHeader().setVisible(False)
      self.table.horizontalHeader().setStretchLastSection(True)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      ## What uses the selected slot.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      self.used_by.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_slot(), "Add a slot after the selected one"))
      row.addWidget(button("Remove", lambda: self.remove_slot(),
                           "Remove the selected slot (species' passives in it go; members fall back to the first)"))
      row.addWidget(button("Rename...", lambda: self.rename_slot(), "Rename it; members naming it follow"))
      row.addWidget(button("Up", lambda: self.move_slot(-1), "Lower number (species' passives follow)"))
      row.addWidget(button("Down", lambda: self.move_slot(1), "Higher number (species' passives follow)"))
      row.addStretch(1)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addWidget(self.budget)
      lay.addWidget(self.table, 1)
      lay.addLayout(row)
      lay.addWidget(self.used_by)
      lay.addWidget(self.errors)

   # -- reading -------------------------------------------------------------------------------------------------------

   def rows(self) -> list[slot_model.SlotRow]:
      """!The slots as the table shows them.
      @return slot_rows() ([] with nothing open)
      """
      doc = self.battle_doc()
      return slot_model.slot_rows(doc) if doc is not None else []

   def names(self) -> list[str]:
      """!The slot names in slot order.
      @return names ([] with nothing open)
      """
      return [r["name"] for r in self.rows()]

   def _budget(self) -> tuple[str, bool]:
      """!The budget line and whether a limit is passed (the engine's most slots, the passive_selector role).
      @return (text, over)
      """
      doc = self.battle_doc()
      if doc is None:
         return "", False
      targets = stat_model.project_targets(doc.path)
      try:
         most = slot_model.max_slots(targets)
         text = slot_model.budget_text(doc, targets)
      except DocumentError as e:
         return str(e), True
      top = slot_model.selector_max(doc)
      count = slot_model.slot_count(doc)
      return text, count > most or (top is not None and count - 1 > top)

   def refresh(self) -> None:
      """!Re-reads the slots, their uses and the budget.
      @return None
      """
      doc = self.battle_doc()
      rows = self.rows()
      names = [r["name"] for r in rows]
      # A local name: Doxygen 1.12 misreads membership tests on self.selected.
      chosen = self.selected
      chosen = chosen if chosen in names else (names[0] if names else None)
      self.selected = chosen
      text, over = self._budget()
      self._filling = True
      try:
         self.budget.setText(text)
         self.budget.setStyleSheet(f"color: {OVER_COLOR if over else WITHIN_COLOR}; font-weight: bold;")
         self.table.setRowCount(len(rows))
         editable = QtCore.Qt.ItemFlag.ItemIsEditable
         checkable = QtCore.Qt.ItemFlag.ItemIsUserCheckable
         for r, row in enumerate(rows):
            texts = {INDEX_COLUMN: str(row["index"]), NAME_COLUMN: row["name"], ROLLED_COLUMN: "",
                     SPECIES_COLUMN: str(row["species"]), MEMBERS_COLUMN: str(row["members"])}
            for c, value in texts.items():
               item = QtWidgets.QTableWidgetItem(value)
               if c != NAME_COLUMN:
                  item.setFlags(item.flags() & ~editable)
               if c == ROLLED_COLUMN:
                  item.setFlags(item.flags() | checkable)
                  item.setCheckState(QtCore.Qt.CheckState.Checked if row["rolled"]
                                     else QtCore.Qt.CheckState.Unchecked)
                  item.setToolTip("the generation list may roll this slot")
               self.table.setItem(r, c, item)
         self.table.resizeColumnsToContents()
         if chosen in names:
            self.table.selectRow(names.index(chosen))
         self._fill_used_by()
      finally:
         self._filling = False
      self.setEnabled(doc is not None)
      self.show_errors()

   def _fill_used_by(self) -> None:
      """!Shows what uses the selected slot.
      @return None
      """
      doc = self.battle_doc()
      if doc is None or self.selected is None:
         self.used_by.setText("")
         return
      users = slot_model.users(doc, self.selected)
      self.used_by.setText(f"{self.selected} is used by: " + (", ".join(users) if users else "nothing"))

   def _selection_changed(self) -> None:
      """!Another row was picked.
      @return None
      """
      if self._filling:
         return
      rows = self.table.selectionModel().selectedRows()
      names = self.names()
      if rows and rows[0].row() < len(names):
         self.selected = names[rows[0].row()]
         self._fill_used_by()

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A name was typed (renames the slot) or the rolled box toggled.
      @param item  the cell
      @return None
      """
      names = self.names()
      if self._filling or not 0 <= item.row() < len(names):
         return
      name = names[item.row()]
      if item.column() == NAME_COLUMN:
         new = item.text().strip()
         if new != name:
            self.rename_slot(new, name)
      elif item.column() == ROLLED_COLUMN:
         self.set_rolled(name, item.checkState() == QtCore.Qt.CheckState.Checked)

   # -- editing -------------------------------------------------------------------------------------------------------

   def confirm_saved_records(self, doc: Document, name: str, delta: int | None) -> bool:
      """!Asks before removing or moving a slot whose number saved creature records keep
      (slot_model.saved_records_warning(), C4).
      @param doc    battle Document
      @param name   slot name
      @param delta  the move's delta, or None for a removal
      @return True to go ahead (nothing changes for saved records, or the user says so; headless No:
              widgets.ask(), as the CLI refuses without --force)
      """
      warning = slot_model.saved_records_warning(doc, name, delta)
      if warning is None:
         return True
      what = "Remove" if delta is None else "Move"
      b = QtWidgets.QMessageBox.StandardButton
      answer = ask(self, f"{what} passive slot", f"{warning}\n\n{what} it anyway?", b.Yes | b.No, b.No, b.No)
      return answer == b.Yes

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

   def add_slot(self, name: str | None = None, rolled: bool = True) -> bool:
      """!Adds a slot after the selected one.
      @param name    the name, or None to ask
      @param rolled  the generation list may roll it
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add passive slot", "Name (a lower-case identifier):")
         if not ok:
            return False
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit("Add passive slot", lambda: slot_model.add_slot(doc, name, rolled, at)):
         self.selected = name.strip()
         return True
      return False

   def remove_slot(self) -> bool:
      """!Removes the selected slot.
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None or not self.confirm_saved_records(doc, name, None):
         return False
      if self._edit("Remove passive slot", lambda: slot_model.remove_slot(doc, name)):
         self.selected = None
         return True
      return False

   def rename_slot(self, new: str | None = None, old: str | None = None) -> bool:
      """!Renames a slot (one undo step with the members naming it).
      @param new  the new name, or None to ask
      @param old  the slot, or None for the selected one
      @return True when renamed
      """
      doc = self.battle_doc()
      old = old or self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename passive slot", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         self.host.changed()
         return False
      if self._edit("Rename passive slot", lambda: slot_model.rename_slot(doc, old, new)):
         self.selected = new.strip()
         return True
      return False

   def move_slot(self, delta: int) -> bool:
      """!Moves the selected slot up or down.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None or not self.confirm_saved_records(doc, name, delta):
         return False
      moved = []
      ok = self._edit("Move passive slot", lambda: moved.append(slot_model.move_slot(doc, name, delta)))
      return ok and moved == [True]

   def set_rolled(self, name: str, rolled: bool) -> bool:
      """!Whether the generation list may roll a slot.
      @param name    slot name
      @param rolled  the value
      @return True when it changed
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      return self._edit("Passive slot rolled", lambda: slot_model.set_rolled(doc, name, rolled))
