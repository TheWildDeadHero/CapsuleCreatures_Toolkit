"""!The Storage page (D-26 section 3, engine G3): the structure manifest's
"storage" section, the storage boxes.

Enable / Disable the boxes; the box count and the slots per box; the names:
one pattern with {n} (the box number) or, once a box is renamed in the
table, every box's own name. The table lists the boxes with their first
slot. The budget line shows the boxes, slots and record bytes against the
engine's most on every target, and the save line the save image with its
Boxes section against the platform's save budget (tools/save_layout.py).
Every change is one undo step (core.structure.storage); the compile result
shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ....core.document import DocumentError
from ....core.structure import stats as stat_model
from ....core.structure import storage as storage_model
from ...widgets import button
from ..battle_common import STRUCTURE, BattlePanel, set_spin, spin

if TYPE_CHECKING:
   from ...panel import PanelHost

## Box table columns.
BOX_COLUMNS = ["#", "Name", "First slot", "Slots"]
## Column of the index.
INDEX_COLUMN = 0
## Column of the name (typing renames).
NAME_COLUMN = 1
## Column of the first slot.
FIRST_COLUMN = 2
## Column of the slots.
SIZE_COLUMN = 3
## Most slots per box the spin offers (the engine's limit on the target decides; the compile says).
SPIN_MAX = 4096
## Text colour of a budget over its limit.
OVER_COLOR = "#c03030"
## Text colour of a budget within its limit.
WITHIN_COLOR = "#2a7a2a"
## What the page says above the boxes.
NOTE = ("A recruit with a full party goes to the storage boxes (the current box first); the script statements "
        "deposit_box, withdraw_box, count_boxed and open_boxes move creatures between the party and the boxes. "
        "Saved games keep every slot: changing the boxes or the record layout makes older saves another game's.")


class StoragePanel(BattlePanel):
   """!The storage boxes.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "storage"
   ## See EditorPanel.title.
   title = "Storage"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the switch row, the numbers, the names, the table and the budget lines.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Whether the section is stated.
      self.state = QtWidgets.QLabel()
      ## Enables the boxes.
      self.enable_button = button("Enable", lambda: self.enable(), "Give the structure storage boxes")
      ## Disables them.
      self.disable_button = button("Disable", lambda: self.disable(), "Take the storage boxes out")
      ## Boxes.
      self.count = spin(1, SPIN_MAX, lambda v: self.set_field(storage_model.COUNT_KEY, v))
      ## Slots per box.
      self.size = spin(1, SPIN_MAX, lambda v: self.set_field(storage_model.SIZE_KEY, v))
      ## The names' pattern (empty while every box has its own name).
      self.pattern = QtWidgets.QLineEdit()
      self.pattern.setToolTip(f"One name for every box, {storage_model.number_placeholder()} the box number")
      self.pattern.editingFinished.connect(lambda: self.set_pattern(self.pattern.text()))
      ## The boxes.
      self.table = QtWidgets.QTableWidget(0, len(BOX_COLUMNS))
      self.table.setHorizontalHeaderLabels(BOX_COLUMNS)
      self.table.verticalHeader().setVisible(False)
      self.table.horizontalHeader().setStretchLastSection(True)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      ## Boxes, slots and bytes against the engine's most.
      self.budget = QtWidgets.QLabel()
      self.budget.setWordWrap(True)
      ## The save image with its boxes.
      self.save_line = QtWidgets.QLabel()
      self.save_line.setWordWrap(True)
      self.save_line.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      top = QtWidgets.QHBoxLayout()
      top.addWidget(self.state, 1)
      top.addWidget(self.enable_button)
      top.addWidget(self.disable_button)
      form = QtWidgets.QFormLayout()
      form.addRow("Boxes", self.count)
      form.addRow("Slots per box", self.size)
      form.addRow("Names", self.pattern)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addLayout(top)
      lay.addLayout(form)
      lay.addWidget(self.budget)
      lay.addWidget(self.table, 1)
      lay.addWidget(self.save_line)
      lay.addWidget(self.errors)

   # -- reading -------------------------------------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the section, the boxes, the budget and the save image.
      @return None
      """
      doc, p = self.structure_doc(), self.project()
      self.setEnabled(doc is not None)
      if doc is None or p is None:
         return
      stated = storage_model.is_stated(doc)
      s = storage_model.section(doc)
      rows = storage_model.rows(doc)
      self._filling = True
      try:
         self.state.setText(f"{len(rows)} storage boxes." if stated else
                            "No storage boxes: a recruit with a full party has no room.")
         self.enable_button.setEnabled(not stated)
         self.disable_button.setEnabled(stated)
         for w in (self.count, self.size, self.pattern, self.table):
            w.setEnabled(stated)
         set_spin(self.count, s[storage_model.COUNT_KEY] or storage_model.NEW_COUNT)
         set_spin(self.size, s[storage_model.SIZE_KEY] or storage_model.NEW_SIZE)
         names = s[storage_model.NAMES_KEY]
         self.pattern.setText(names if isinstance(names, str) else "")
         self.pattern.setPlaceholderText("" if isinstance(names, str) else "every box has its own name")
         self.table.setRowCount(len(rows))
         editable = QtCore.Qt.ItemFlag.ItemIsEditable
         for r, row in enumerate(rows):
            texts = {INDEX_COLUMN: str(row["index"]), NAME_COLUMN: row["name"], FIRST_COLUMN: str(row["first"]),
                     SIZE_COLUMN: str(row["size"])}
            for c, value in texts.items():
               item = QtWidgets.QTableWidgetItem(value)
               if c != NAME_COLUMN:
                  item.setFlags(item.flags() & ~editable)
               self.table.setItem(r, c, item)
         self.table.resizeColumnsToContents()
         try:
            text, over = storage_model.budget(doc, stat_model.project_targets(doc.path))
         except DocumentError as e:
            text, over = str(e), True
         self.budget.setText(text if stated else "")
         self.budget.setStyleSheet(f"color: {OVER_COLOR if over else WITHIN_COLOR}; font-weight: bold;")
         save_text, save_over = storage_model.save_report(p)
         self.save_line.setText(save_text)
         self.save_line.setStyleSheet(f"color: {OVER_COLOR if save_over else WITHIN_COLOR};")
      finally:
         self._filling = False
      self.show_errors()

   # -- editing -------------------------------------------------------------------------------------------------------

   def _edit(self, label: str, fn: Any) -> bool:
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

   def enable(self) -> bool:
      """!Gives the structure storage boxes (the engine's default names).
      @return True when it went through
      """
      doc = self.structure_doc()
      return doc is not None and self._edit("Enable storage", lambda: storage_model.enable(doc))

   def disable(self) -> bool:
      """!Takes the boxes out.
      @return True when it went through
      """
      doc = self.structure_doc()
      return doc is not None and self._edit("Disable storage", lambda: storage_model.disable(doc))

   def set_field(self, field: str, value: int) -> bool:
      """!Sets box_count or box_size.
      @param field  the field
      @param value  the number
      @return True when it went through
      """
      doc = self.structure_doc()
      if doc is None or storage_model.section(doc)[field] == value:
         return False
      return self._edit(f"Storage {field}", lambda: storage_model.set_field(doc, field, value))

   def set_pattern(self, text: str) -> bool:
      """!Names every box by one pattern.
      @param text  the pattern (empty: nothing changes)
      @return True when it went through
      """
      doc = self.structure_doc()
      text = text.strip()
      if doc is None or not text or storage_model.section(doc)[storage_model.NAMES_KEY] == text:
         return False
      return self._edit("Storage names", lambda: storage_model.set_names(doc, text))

   def rename_box(self, index: int, name: str) -> bool:
      """!Names one box.
      @param index  box index
      @param name   its name
      @return True when it went through
      """
      doc = self.structure_doc()
      return doc is not None and self._edit("Rename box", lambda: storage_model.rename_box(doc, index, name))

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A box name was typed.
      @param item  the cell
      @return None
      """
      if self._filling or item.column() != NAME_COLUMN:
         return
      doc = self.structure_doc()
      names = storage_model.box_names(doc) if doc is not None else []
      if 0 <= item.row() < len(names) and item.text().strip() != names[item.row()]:
         self.rename_box(item.row(), item.text())
