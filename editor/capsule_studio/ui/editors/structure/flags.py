"""!The Flags & Tags panel (D-23 §3.2 "Flags & Tags"): the battle manifest's
move flags and tags side by side, each with its use counts and budget.

A move flag is a bit of a move's flags (ticked on Content > Moves, tested by
effect code, named by statuses' thawed_by_move and volatiles' chain
kept_by); a tag is a bit an owner gives its holder (condition records'
tags, `.ceffect` `tags [...]`). Typing a name in the table renames it and
every use (moves, records and the effect logic, one undo step); a name in
use cannot be removed. The engine's caps come from its compiler
(MAX_MOVE_FLAGS, MAX_TAGS); the compile result shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core.document import DocumentError
from ....core.structure import flags as flag_model
from ...widgets import button
from ..battle_common import STRUCTURE, BattlePanel

if TYPE_CHECKING:
   from ...panel import PanelHost

## Name table columns.
NAME_COLUMNS = ["#", "Name", "Uses"]
## Name table column of the bit.
BIT_COLUMN = 0
## Name table column of the name (typing renames).
NAME_COLUMN = 1
## Name table column of the use count.
USES_COLUMN = 2
## Group box titles.
GROUP_TITLES = {flag_model.FLAGS_KEY: "Move flags", flag_model.TAGS_KEY: "Tags"}
## The weather-suppress combo's "no tag" entry.
SUPPRESS_NONE = "(none)"
## Text colour of a budget over its limit.
OVER_COLOR = "#c03030"
## Text colour of a budget within its limit.
WITHIN_COLOR = "#2a7a2a"


class NameListBox(QtWidgets.QGroupBox):
   """!One list (move flags or tags): the names in bit order with their uses."""

   def __init__(self, panel: FlagsTagsPanel, which: str) -> None:
      """!Builds the table, the budget and the buttons.
      @param panel  the FlagsTagsPanel
      @param which  core.structure.flags.FLAGS_KEY or TAGS_KEY
      """
      super().__init__(GROUP_TITLES[which])
      ## The panel.
      self.panel = panel
      ## The list edited.
      self.which = which
      ## The selected name, or None.
      self.selected = None
      ## True while the box fills its widgets.
      self._filling = False
      ## Names used against the engine's cap.
      self.budget = QtWidgets.QLabel()
      ## The names.
      self.table = QtWidgets.QTableWidget(0, len(NAME_COLUMNS))
      self.table.setHorizontalHeaderLabels(NAME_COLUMNS)
      self.table.verticalHeader().setVisible(False)
      self.table.horizontalHeader().setStretchLastSection(True)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      ## What uses the selected name.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      self.used_by.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      word = flag_model.SINGULAR[which]
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(self.budget)
      lay.addWidget(self.table, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_name(), f"Add a {word} after the selected one"))
      row.addWidget(button("Remove", lambda: self.remove_name(), f"Remove the selected {word} (nothing may use it)"))
      row.addWidget(button("Rename...", lambda: self.rename_name(), "Rename it; every use follows"))
      row.addWidget(button("Up", lambda: self.move_name(-1), "Lower bit"))
      row.addWidget(button("Down", lambda: self.move_name(1), "Higher bit"))
      row.addStretch(1)
      lay.addLayout(row)
      lay.addWidget(self.used_by)
      ## C6: the tag whose holders keep the weather from acting (tags only), or none.
      self.suppress = QtWidgets.QComboBox()
      self.suppress.setToolTip("While a battler holding this tag is on the field the weather does not act "
                               "(a weather-calming passive)")
      self.suppress.activated.connect(lambda _i: self.set_weather_suppress())
      if which == flag_model.TAGS_KEY:
         suppress_row = QtWidgets.QHBoxLayout()
         suppress_row.addWidget(QtWidgets.QLabel("Weather suppressed by"))
         suppress_row.addWidget(self.suppress, 1)
         lay.addLayout(suppress_row)

   def set_weather_suppress(self) -> bool:
      """!Names the weather-suppressing tag from the combo (C6).
      @return True when it went through
      """
      doc = self.panel.battle_doc()
      if doc is None or self._filling:
         return False
      text = self.suppress.currentText()
      name = None if text == SUPPRESS_NONE else text
      if name == flag_model.weather_suppress_tag(doc):
         return False
      return self._edit("Weather suppress tag", lambda: flag_model.set_weather_suppress_tag(doc, name))

   def names(self) -> list[str]:
      """!The names in bit order.
      @return names ([] with nothing open)
      """
      doc = self.panel.battle_doc()
      return flag_model.names(doc, self.which) if doc is not None else []

   def refresh(self) -> None:
      """!Re-reads the names, their uses and the budget.
      @return None
      """
      doc = self.panel.battle_doc()
      names = self.names()
      counts = self._counts()
      # A local name: Doxygen 1.12 misreads membership tests on self.selected.
      chosen = self.selected
      chosen = chosen if chosen in names else (names[0] if names else None)
      self.selected = chosen
      self._filling = True
      try:
         most = flag_model.max_names(self.which)
         self.budget.setText(f"{len(names)}/{most} {self.which}" if doc is not None else "")
         self.budget.setStyleSheet(f"color: {OVER_COLOR if len(names) > most else WITHIN_COLOR}; "
                                   "font-weight: bold;")
         self.table.setRowCount(len(names))
         editable = QtCore.Qt.ItemFlag.ItemIsEditable
         for r, n in enumerate(names):
            for c, text in ((BIT_COLUMN, str(r)), (NAME_COLUMN, n), (USES_COLUMN, str(counts.get(n, "?")))):
               item = QtWidgets.QTableWidgetItem(text)
               if c != NAME_COLUMN:
                  item.setFlags(item.flags() & ~editable)
               self.table.setItem(r, c, item)
         self.table.resizeColumnToContents(BIT_COLUMN)
         if chosen in names:
            self.table.selectRow(names.index(chosen))
         self._fill_used_by()
         self.suppress.clear()
         self.suppress.addItems([SUPPRESS_NONE] + names)
         current = flag_model.weather_suppress_tag(doc) if doc is not None else None
         self.suppress.setCurrentText(current if current in names else SUPPRESS_NONE)
      finally:
         self._filling = False
      self.setEnabled(doc is not None)

   def _counts(self) -> dict[str, int]:
      """!Each name's use count.
      @return {name: uses} ({} with nothing open or while a source does not parse)
      """
      doc = self.panel.battle_doc()
      if doc is None:
         return {}
      try:
         return flag_model.use_counts(doc, self.which)
      except DocumentError:
         return {}

   def _fill_used_by(self) -> None:
      """!Shows what uses the selected name.
      @return None
      """
      doc = self.panel.battle_doc()
      if doc is None or self.selected is None:
         self.used_by.setText("")
         return
      try:
         users = flag_model.uses(doc, self.which, self.selected)
         self.used_by.setText(f"{self.selected} is used by: " + (", ".join(users) if users else "nothing"))
      except DocumentError as e:
         self.used_by.setText(f"Uses unknown while a source does not parse ({e})")

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
      """!A name was typed: renames it.
      @param item  the cell
      @return None
      """
      names = self.names()
      if self._filling or item.column() != NAME_COLUMN or not 0 <= item.row() < len(names):
         return
      old, new = names[item.row()], item.text().strip()
      if new != old:
         self.rename_name(new, old)

   def _edit(self, label: str, fn: object) -> bool:
      """!One edit; a refused one refreshes the table back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      ok = self.panel.edit(label, fn)
      if not ok:
         self.panel.host.changed()
      return ok

   def add_name(self, name: str | None = None) -> bool:
      """!Adds a name after the selected one.
      @param name  the name, or None to ask
      @return True when added
      """
      doc, which = self.panel.battle_doc(), self.which
      if doc is None:
         return False
      word = flag_model.SINGULAR[which]
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, f"Add {word}", "Name (a lower-case identifier):")
         if not ok:
            return False
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit(f"Add {word}", lambda: flag_model.add_name(doc, which, name, at)):
         self.selected = name.strip()
         return True
      return False

   def remove_name(self) -> bool:
      """!Removes the selected name (refused while used).
      @return True when removed
      """
      doc, which, name = self.panel.battle_doc(), self.which, self.selected
      if doc is None or name is None:
         return False
      if self._edit(f"Remove {flag_model.SINGULAR[which]}", lambda: flag_model.remove_name(doc, which, name)):
         self.selected = None
         return True
      return False

   def rename_name(self, new: str | None = None, old: str | None = None) -> bool:
      """!Renames a name and every use (one undo step).
      @param new  the new name, or None to ask
      @param old  the name, or None for the selected one
      @return True when renamed
      """
      doc, which = self.panel.battle_doc(), self.which
      old = old or self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         self.panel.host.changed()
         return False
      if self._edit(f"Rename {flag_model.SINGULAR[which]}", lambda: flag_model.rename_name(doc, which, old, new)):
         self.selected = new.strip()
         return True
      return False

   def move_name(self, delta: int) -> bool:
      """!Moves the selected name up or down (its bit).
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, which, name = self.panel.battle_doc(), self.which, self.selected
      if doc is None or name is None:
         return False
      moved = []
      ok = self._edit(f"Move {flag_model.SINGULAR[which]}",
                      lambda: moved.append(flag_model.move_name(doc, which, name, delta)))
      return ok and moved == [True]


class FlagsTagsPanel(BattlePanel):
   """!Move flags and tags.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "flags"
   ## See EditorPanel.title.
   title = "Flags & Tags"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the two lists.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The move flags.
      self.flags = NameListBox(self, flag_model.FLAGS_KEY)
      ## The tags.
      self.tags = NameListBox(self, flag_model.TAGS_KEY)
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("A move flag's place is its bit in MoveData::flags; moves tick them on Content > Moves "
                              "and effect code tests them (move.has(contact)). A tag is a bit an owner gives its "
                              "holder (records' tags, `tags [...]` in .ceffect). Type a name to rename it "
                              "everywhere.")
      note.setWordWrap(True)
      lay.addWidget(note)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.flags, 1)
      row.addWidget(self.tags, 1)
      lay.addLayout(row, 1)
      lay.addWidget(self.errors)

   def box(self, which: str) -> NameListBox:
      """!The box of a list.
      @param which  core.structure.flags.FLAGS_KEY or TAGS_KEY
      @return NameListBox
      """
      return self.flags if which == flag_model.FLAGS_KEY else self.tags

   def refresh(self) -> None:
      """!Re-reads both lists.
      @return None
      """
      self.flags.refresh()
      self.tags.refresh()
      self.show_errors()
