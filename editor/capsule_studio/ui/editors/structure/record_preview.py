"""!The preview tabs of the Record page (engine E13a;
core.structure.record_preview):

- DerivedPreviewBox: a record typed in (a species, whose fields species.NAME
  the expressions read, and the stored roles the derived expressions read)
  and every derived generation entry's value for it: what
  battle::record_value() reads (derived_values(): an unstored role, or a
  role the layout leaves out, computed on read) and, for a stored role, what
  battle::rederive() writes;
- TransferPreviewBox: the same kind of record sent by a battle data (this
  one, or another game's battle.json) and imported here (import_rederived():
  the roles the record held keep the sender's values, the derived roles it
  lacked are re-derived, the rest take the receiver's defaults).

Both read the compiled data, unsaved edits included, and change nothing.
Values are typed in decimal or 0x hexadecimal (a 32-bit role exceeds a spin
box); "More roles" takes ROLE=V pairs for roles no expression reads.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ....core.document import DocumentError
from ....core.structure import progression
from ....core.structure import record_preview as model
from ...widgets import button
from ..battle_common import NONE_TEXT, set_combo

if TYPE_CHECKING:
   from ..battle_common import BattlePanel

## Base of a typed value: 0 reads "0x..." as hexadecimal and the rest as decimal.
AUTO_BASE = 0
## Column of the role name in the input table.
ROLE_COLUMN = 0
## Column of the typed value in the input table.
VALUE_COLUMN = 1
## Input table headings.
INPUT_HEADINGS = ["Role", "Value"]
## Derived results headings.
DERIVED_HEADINGS = ["#", "Role", "Read as", "record_value()", "rederive() writes"]
## Transfer results headings.
TRANSFER_HEADINGS = ["Role", "Value", "From"]
## The From cell of a role the record held.
FROM_RECORD = "the record"
## The From cell of a derived role the import re-derived.
FROM_REDERIVED = "re-derived"
## The From cell of a role the receiver's defaults fill.
FROM_DEFAULT = "receiver default"
## Stretch of the results beside the inputs (whose stretch is 1).
RESULTS_STRETCH = 2
## Separator of a ROLE=V pair.
PAIR_SEPARATOR = "="


def _int(text: str) -> int:
   """!A typed number.
   @param text  decimal or 0x hexadecimal
   @return the value
   @throws ValueError when it is not one
   """
   return int(text.strip(), AUTO_BASE)


def _fill_table(table: QtWidgets.QTableWidget, rows: list[list[str]]) -> None:
   """!Fills a read-only results table.
   @param table  QTableWidget
   @param rows   cell texts per row
   @return None
   """
   table.setRowCount(len(rows))
   for r, cells in enumerate(rows):
      for c, text in enumerate(cells):
         item = QtWidgets.QTableWidgetItem(text)
         item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
         table.setItem(r, c, item)
   table.resizeColumnsToContents()


class RecordInputs(QtWidgets.QWidget):
   """!A species and the role values of a preview record."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the widgets.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The record's species.
      self.species = QtWidgets.QComboBox()
      ## Role values (the stored roles the derived expressions read).
      self.table = QtWidgets.QTableWidget(0, len(INPUT_HEADINGS))
      self.table.setHorizontalHeaderLabels(INPUT_HEADINGS)
      self.table.verticalHeader().setVisible(False)
      self.table.horizontalHeader().setStretchLastSection(True)
      ## Further ROLE=V pairs.
      self.more = QtWidgets.QLineEdit()
      self.more.setPlaceholderText("ROLE=V ... (roles no expression reads)")
      ## Roles in the table, in row order.
      self.roles = []
      lay = QtWidgets.QFormLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addRow("Species", self.species)
      lay.addRow(self.table)
      lay.addRow("More roles", self.more)

   def refresh(self, roles: list[str], species: list[str]) -> None:
      """!Shows the roles and the species (typed values of roles still shown are kept).
      @param roles    record_preview.input_roles()
      @param species  species names
      @return None
      """
      keep = self.species.currentText()
      choices = [NONE_TEXT] + species
      set_combo(self.species, choices, keep if keep in choices else (species[0] if species else NONE_TEXT))
      if roles == self.roles:
         return
      typed = {}
      for r, role in enumerate(self.roles):
         item = self.table.item(r, VALUE_COLUMN)
         typed[role] = item.text() if item is not None else "0"
      self.roles = list(roles)
      self.table.setRowCount(len(roles))
      for r, role in enumerate(roles):
         name = QtWidgets.QTableWidgetItem(role)
         name.setFlags(name.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
         self.table.setItem(r, ROLE_COLUMN, name)
         self.table.setItem(r, VALUE_COLUMN, QtWidgets.QTableWidgetItem(typed.get(role, "0")))
      self.table.resizeColumnsToContents()

   def species_name(self) -> str | None:
      """!The record's species.
      @return its name, or None
      """
      text = self.species.currentText()
      return None if not text or text == NONE_TEXT else text

   def set_species(self, name: str | None) -> bool:
      """!Picks the species.
      @param name  species name, or None
      @return True when it is one of the choices
      """
      i = self.species.findText(NONE_TEXT if name is None else name)
      if i >= 0:
         self.species.setCurrentIndex(i)
      return i >= 0

   def set_value(self, role: str, value: int | str) -> bool:
      """!Types a role's value (a role the table does not show goes to "More roles").
      @param role   role name
      @param value  the value
      @return True
      """
      roles = self.roles   # a local name: Doxygen 1.12 misreads membership tests on self.x
      if role in roles:
         self.table.item(roles.index(role), VALUE_COLUMN).setText(str(value))
      else:
         self.more.setText((self.more.text() + f" {role}{PAIR_SEPARATOR}{value}").strip())
      return True

   def values(self) -> dict[str, int]:
      """!The typed role values.
      @return role -> value
      @throws ValueError naming a value that is not a number
      """
      out = {}
      for r, role in enumerate(self.roles):
         item = self.table.item(r, VALUE_COLUMN)
         text = item.text() if item is not None else ""
         try:
            out[role] = _int(text or "0")
         except ValueError:
            raise ValueError(f"{role}: a whole number (decimal or 0x...), got {text!r}") from None
      for pair in self.more.text().split():
         role, sep, text = pair.partition(PAIR_SEPARATOR)
         try:
            if not sep:
               raise ValueError(pair)
            out[role] = _int(text)
         except ValueError:
            raise ValueError(f"more roles look like seed=12345, got {pair!r}") from None
      return out


class DerivedPreviewBox(QtWidgets.QWidget):
   """!A record's derived roles (record_value() / rederive()).

   @var panel
   The Record panel.
   """

   def __init__(self, panel: BattlePanel) -> None:
      """!Builds the box.
      @param panel  the Record panel (project(), battle_doc())
      """
      super().__init__()
      ## The page the box belongs to.
      self.panel = panel
      ## The record typed in.
      self.inputs = RecordInputs()
      ## Every derived entry's values.
      self.results = QtWidgets.QTableWidget(0, len(DERIVED_HEADINGS))
      self.results.setHorizontalHeaderLabels(DERIVED_HEADINGS)
      self.results.verticalHeader().setVisible(False)
      self.results.horizontalHeader().setStretchLastSection(True)
      ## The run's message (an error, or what it shows).
      self.message = QtWidgets.QLabel()
      self.message.setWordWrap(True)
      ## True once run: a refresh runs it again.
      self.ran = False
      lay = QtWidgets.QHBoxLayout(self)
      left = QtWidgets.QVBoxLayout()
      left.addWidget(self.inputs)
      left.addWidget(button("Run", lambda: self.run(), "Every derived role of this record, as the engine reads it"))
      lay.addLayout(left, 1)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(self.results, 1)
      right.addWidget(self.message)
      lay.addLayout(right, RESULTS_STRETCH)

   def refresh(self) -> None:
      """!Re-reads the roles and the species; runs again after a first run.
      @return None
      """
      p = self.panel.project()
      if p is None:
         return
      self.inputs.refresh(model.input_roles(p), progression.species_names(p.battle))
      if self.ran:
         self.run()

   def run(self) -> list[model.DerivedRow] | None:
      """!Computes the derived roles.
      @return the rows, or None (the message says why)
      """
      p = self.panel.project()
      if p is None:
         return None
      self.ran = True
      try:
         rows = model.derived_rows(p, self.inputs.species_name(), self.inputs.values())
      except (DocumentError, ValueError) as e:
         self.message.setText(str(e))
         _fill_table(self.results, [])
         return None
      _fill_table(self.results, [[str(r["index"]), r["role"], r["state"], model.value_text(r["value"]),
                                  model.value_text(r["rederived"])] for r in rows])
      self.message.setText("record_value(): what the engine reads (unstored and not-held roles are computed on "
                           "read); rederive(): what it writes into a stored derived role.")
      return rows


class TransferPreviewBox(QtWidgets.QWidget):
   """!A record transferred in (import_rederived()).

   @var panel
   The Record panel.
   """

   def __init__(self, panel: BattlePanel) -> None:
      """!Builds the box.
      @param panel  the Record panel (project(), battle_doc())
      """
      super().__init__()
      ## The page the box belongs to.
      self.panel = panel
      ## The sending battle.json (empty: this battle data).
      self.sender = QtWidgets.QLineEdit()
      self.sender.setPlaceholderText("this battle data (its own record, canonical form)")
      ## The record typed in.
      self.inputs = RecordInputs()
      ## The imported record.
      self.results = QtWidgets.QTableWidget(0, len(TRANSFER_HEADINGS))
      self.results.setHorizontalHeaderLabels(TRANSFER_HEADINGS)
      self.results.verticalHeader().setVisible(False)
      self.results.horizontalHeader().setStretchLastSection(True)
      ## The import's flags, size, or an error.
      self.message = QtWidgets.QLabel()
      self.message.setWordWrap(True)
      lay = QtWidgets.QHBoxLayout(self)
      left = QtWidgets.QVBoxLayout()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Sent by"))
      row.addWidget(self.sender, 1)
      row.addWidget(button("Browse...", lambda: self.browse(), "Another game's battle.json"))
      left.addLayout(row)
      left.addWidget(self.inputs)
      left.addWidget(button("Import", lambda: self.run(), "Export the record from the sender, import it here"))
      lay.addLayout(left, 1)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(self.results, 1)
      right.addWidget(self.message)
      lay.addLayout(right, RESULTS_STRETCH)

   def refresh(self) -> None:
      """!Re-reads the roles and the species.
      @return None
      """
      p = self.panel.project()
      if p is None:
         return
      self.inputs.refresh(model.input_roles(p), progression.species_names(p.battle))

   def browse(self) -> None:
      """!Picks the sending battle.json.
      @return None
      """
      path, _filter = QtWidgets.QFileDialog.getOpenFileName(self, "Sending battle data", self.sender.text(),
                                                            "Battle data (*.json)")
      if path:
         self.sender.setText(path)

   def run(self) -> dict[str, Any] | None:
      """!Exports the record from the sender and imports it here.
      @return transfer_preview() result, or None (the message says why)
      """
      p = self.panel.project()
      if p is None:
         return None
      try:
         result = model.transfer_preview(p, self.inputs.species_name(), self.inputs.values(),
                                         self.sender.text().strip() or None)
      except (DocumentError, ValueError) as e:
         self.message.setText(str(e))
         _fill_table(self.results, [])
         return None
      rows = []
      for role, value in result["record"].items():
         how = FROM_REDERIVED if role in result["rederived"] else \
            FROM_RECORD if role in result["received"] else FROM_DEFAULT
         rows.append([role, model.value_text(value), how])
      _fill_table(self.results, rows)
      self.message.setText(f"{result['bytes']} transfer bytes; flags: {', '.join(result['flags']) or 'none'}; "
                           f"re-derived: {', '.join(result['rederived']) or 'none'}")
      return result
