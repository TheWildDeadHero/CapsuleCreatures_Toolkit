"""!The Pockets page (D-26 section 2, engine G2): the structure manifest's
"pockets", the bag's slices.

Each row is a pocket in order: its name (typing renames it; the items naming
it follow), its label, its capacity (slots: distinct items), its most of one
item per slot, its first slot in the bag and the items naming it. The sort
rule of the selected pocket is the combo below the table (the engine's
SORT_RULES: as items come in, by item index, by display name). Add / Remove /
Up / Down edit the list as one undo step (core.structure.pockets); a pocket
that items name cannot go (give them another pocket on Content > Items). The
budget line shows the pockets and slots against the engine's most on every
target; the compile result shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ....core.document import DocumentError
from ....core.structure import pockets as pocket_model
from ....core.structure import stats as stat_model
from ...widgets import button
from ..battle_common import STRUCTURE, BattlePanel, combo, set_combo

if TYPE_CHECKING:
   from ...panel import PanelHost

## Pocket table columns.
POCKET_COLUMNS = ["#", "Name", "Label", "Slots", "Most of one", "Sort", "First slot", "Items"]
## Column of the index.
INDEX_COLUMN = 0
## Column of the name (typing renames).
NAME_COLUMN = 1
## Column of the label.
LABEL_COLUMN = 2
## Column of the capacity.
CAPACITY_COLUMN = 3
## Column of the quantity maximum.
QUANTITY_COLUMN = 4
## Column of the sort rule.
SORT_COLUMN = 5
## Column of the first slot.
FIRST_COLUMN = 6
## Column of the item count.
ITEMS_COLUMN = 7
## The columns typing edits, with the field they set.
EDIT_COLUMNS = {LABEL_COLUMN: pocket_model.LABEL_KEY, CAPACITY_COLUMN: pocket_model.CAPACITY_KEY,
                QUANTITY_COLUMN: pocket_model.QUANTITY_KEY}
## Text colour of a budget over its limit.
OVER_COLOR = "#c03030"
## Text colour of a budget within its limit.
WITHIN_COLOR = "#2a7a2a"
## What the page says above the table.
NOTE = ("The bag is the pockets one after another: each holds as many distinct items as its slots, up to its most "
        "of one item each. An item names its pocket on Content > Items (an item without one cannot go into the "
        "bag). Saved games keep their bag by slot: changing the pockets makes older saves another game's.")


class PocketsPanel(BattlePanel):
   """!The bag's pockets.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "pockets"
   ## See EditorPanel.title.
   title = "Pockets"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the budget line, the pocket table, the sort combo and the buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected pocket's name, or None.
      self.selected = None
      ## The pockets and slots against the engine's most.
      self.budget = QtWidgets.QLabel()
      self.budget.setWordWrap(True)
      ## The pockets.
      self.table = QtWidgets.QTableWidget(0, len(POCKET_COLUMNS))
      self.table.setHorizontalHeaderLabels(POCKET_COLUMNS)
      self.table.verticalHeader().setVisible(False)
      self.table.horizontalHeader().setStretchLastSection(True)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      ## The selected pocket's sort rule.
      self.sort = combo(lambda text: self.set_field(pocket_model.SORT_KEY, text))
      ## The items naming the selected pocket.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      self.used_by.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_pocket(), "Add a pocket after the selected one"))
      row.addWidget(button("Remove", lambda: self.remove_pocket(), "Remove the selected pocket (no item names it)"))
      row.addWidget(button("Up", lambda: self.move_pocket(-1), "Earlier in the bag"))
      row.addWidget(button("Down", lambda: self.move_pocket(1), "Later in the bag"))
      row.addStretch(1)
      row.addWidget(QtWidgets.QLabel("Sort"))
      row.addWidget(self.sort)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addWidget(self.budget)
      lay.addWidget(self.table, 1)
      lay.addLayout(row)
      lay.addWidget(self.used_by)
      lay.addWidget(self.errors)

   # -- reading -------------------------------------------------------------------------------------------------------

   def rows(self) -> list[pocket_model.PocketRow]:
      """!The pockets as the table shows them.
      @return rows() ([] with nothing open)
      """
      doc = self.battle_doc()
      return pocket_model.rows(doc) if doc is not None else []

   def names(self) -> list[str]:
      """!The pocket names in order.
      @return names
      """
      return [r["name"] for r in self.rows()]

   def refresh(self) -> None:
      """!Re-reads the pockets, their items and the budget.
      @return None
      """
      doc = self.battle_doc()
      rows = self.rows()
      names = [r["name"] for r in rows]
      chosen = self.selected
      chosen = chosen if chosen in names else (names[0] if names else None)
      self.selected = chosen
      self._filling = True
      try:
         if doc is not None:
            try:
               text, over = pocket_model.budget(doc, stat_model.project_targets(doc.path))
            except DocumentError as e:
               text, over = str(e), True
            self.budget.setText(text)
            self.budget.setStyleSheet(f"color: {OVER_COLOR if over else WITHIN_COLOR}; font-weight: bold;")
         self.table.setRowCount(len(rows))
         editable = QtCore.Qt.ItemFlag.ItemIsEditable
         for r, row in enumerate(rows):
            texts = {INDEX_COLUMN: str(row["index"]), NAME_COLUMN: row["name"], LABEL_COLUMN: row["label"],
                     CAPACITY_COLUMN: str(row["capacity"]), QUANTITY_COLUMN: str(row["quantity_max"]),
                     SORT_COLUMN: row["sort"], FIRST_COLUMN: str(row["first"]), ITEMS_COLUMN: str(row["items"])}
            for c, value in texts.items():
               item = QtWidgets.QTableWidgetItem(value)
               if c != NAME_COLUMN and c not in EDIT_COLUMNS:
                  item.setFlags(item.flags() & ~editable)
               self.table.setItem(r, c, item)
         self.table.resizeColumnsToContents()
         if chosen in names:
            self.table.selectRow(names.index(chosen))
         self._fill_selected()
      finally:
         self._filling = False
      self.setEnabled(doc is not None)
      self.show_errors()

   def _fill_selected(self) -> None:
      """!Shows the selected pocket's sort rule and items.
      @return None
      """
      doc = self.battle_doc()
      row = next((r for r in self.rows() if r["name"] == self.selected), None)
      self.sort.setEnabled(row is not None)
      set_combo(self.sort, pocket_model.sort_rules(), row["sort"] if row is not None else None)
      if doc is None or row is None:
         self.used_by.setText("")
         return
      items = pocket_model.users(doc, row["name"])
      self.used_by.setText(f"{row['name']} holds: " + (", ".join(items) if items else "no item"))

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
         self._filling = True
         try:
            self._fill_selected()
         finally:
            self._filling = False

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A name, label or number was typed.
      @param item  the cell
      @return None
      """
      names = self.names()
      if self._filling or not 0 <= item.row() < len(names):
         return
      name = names[item.row()]
      self.selected = name
      if item.column() == NAME_COLUMN:
         new = item.text().strip()
         if new != name:
            self.rename_pocket(new, name)
      elif item.column() in EDIT_COLUMNS:
         self.set_field(EDIT_COLUMNS[item.column()], item.text().strip())

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

   def add_pocket(self, name: str | None = None, label: str | None = None) -> bool:
      """!Adds a pocket after the selected one.
      @param name   the name, or None to ask
      @param label  the label, or None (the name)
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add pocket", "Name (a lower-case identifier):")
         if not ok:
            return False
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit("Add pocket", lambda: pocket_model.add_pocket(doc, name, label, pocket_model.NEW_CAPACITY, at)):
         self.selected = name.strip()
         return True
      return False

   def remove_pocket(self) -> bool:
      """!Removes the selected pocket.
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self._edit("Remove pocket", lambda: pocket_model.remove_pocket(doc, name)):
         self.selected = None
         return True
      return False

   def rename_pocket(self, new: str, old: str | None = None) -> bool:
      """!Renames a pocket (one undo step with the items naming it).
      @param new  the new name
      @param old  the pocket, or None for the selected one
      @return True when renamed
      """
      doc = self.battle_doc()
      old = old or self.selected
      if doc is None or old is None or not new.strip() or new.strip() == old:
         self.host.changed()
         return False
      if self._edit("Rename pocket", lambda: pocket_model.rename_pocket(doc, old, new)):
         self.selected = new.strip()
         return True
      return False

   def move_pocket(self, delta: int) -> bool:
      """!Moves the selected pocket up or down.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      moved = []
      ok = self._edit("Move pocket", lambda: moved.append(pocket_model.move_pocket(doc, name, delta)))
      return ok and moved == [True]

   def set_field(self, field: str, value: Any) -> bool:
      """!Sets one of the selected pocket's fields.
      @param field  label, capacity, quantity_max or sort
      @param value  the value
      @return True when it changed
      """
      doc, name = self.battle_doc(), self.selected
      if self._filling or doc is None or name is None:
         return False
      return self._edit(f"Pocket {field}", lambda: pocket_model.set_field(doc, name, field, value))
