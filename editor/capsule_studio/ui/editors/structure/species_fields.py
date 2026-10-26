"""!The Species fields page (engine E13a; core.structure.species_fields):
the structure manifest's "species_fields", numeric data columns every
species has, read by the generation list's derived expressions as
species.NAME (a Gen-3 gender from gender_ratio and the seed).

Each row is a field in order: its name (typing renames it; the species'
values and the derived expressions follow), its width in bits (up to the
engine's MAX_SPECIES_FIELD_BITS), the default value of a species that
gives none, its highest value, how many species give their own value and
which derived entries read it. Add / Remove / Up / Down edit the list as
one undo step with the species' values (core.structure.species_fields);
the engine refuses a width or a default a value no longer fits in, and a
removal while an expression reads the field. Each species' values are
edited on the Species page.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ....core.structure import species_fields as model
from ...widgets import button
from ..battle_common import STRUCTURE, BattlePanel

if TYPE_CHECKING:
   from ...panel import PanelHost

## Field table columns, in order: (key, heading).
FIELD_COLUMNS = [("index", "#"), ("name", "Name"), ("width", "Width (bits)"), ("default", "Default"),
                 ("max", "Highest"), ("species", "Species with their own"), ("readers", "Read by")]
## Field table column of each key.
FIELD_COLUMN = {key: c for c, (key, _heading) in enumerate(FIELD_COLUMNS)}
## Columns typed in: rename, set_field() width and default.
EDIT_KEYS = ("name", "width", "default")
## Width of a new field in the form, bits.
NEW_FIELD_WIDTH = 8
## Text colour of a default the field does not state (the engine's 0).
UNSTATED_COLOR = "#909090"
## What the page says above the table.
NOTE = ("Numeric data every species has (Content > Species gives each species' values; a species that gives none "
        "has the default). The generation list's derived expressions read a field as species.NAME. Type a name, "
        "width or default to change it.")


class SpeciesFieldsPanel(BattlePanel):
   """!The species fields.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "species_fields"
   ## See EditorPanel.title.
   title = "Species fields"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the count line, the field table, the add form and the buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected field's name, or None.
      self.selected = None
      ## The rows shown (field_rows()).
      self._rows = []
      ## The fields against the engine's most.
      self.count = QtWidgets.QLabel()
      ## The fields.
      self.table = QtWidgets.QTableWidget(0, len(FIELD_COLUMNS))
      self.table.setHorizontalHeaderLabels([h for _k, h in FIELD_COLUMNS])
      self.table.verticalHeader().setVisible(False)
      self.table.horizontalHeader().setStretchLastSection(True)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      ## New field: name.
      self.new_name = QtWidgets.QLineEdit()
      self.new_name.setPlaceholderText("lower-case name, e.g. gender_ratio")
      ## New field: bits.
      self.new_width = QtWidgets.QSpinBox()
      self.new_width.setRange(1, model.max_width())
      self.new_width.setValue(min(NEW_FIELD_WIDTH, model.max_width()))
      ## New field: default.
      self.new_default = QtWidgets.QSpinBox()
      self.new_width.valueChanged.connect(lambda v: self.new_default.setMaximum(model.top_of(v)))
      self.new_default.setMaximum(model.top_of(self.new_width.value()))
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      form = QtWidgets.QHBoxLayout()
      form.addWidget(QtWidgets.QLabel("Name"))
      form.addWidget(self.new_name, 1)
      form.addWidget(QtWidgets.QLabel("Width"))
      form.addWidget(self.new_width)
      form.addWidget(QtWidgets.QLabel("Default"))
      form.addWidget(self.new_default)
      form.addWidget(button("Add", lambda: self.add_field(), "Add the field after the selected one"))
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Remove", lambda: self.remove_field(),
                           "Remove the selected field and every species' value of it"))
      row.addWidget(button("Up", lambda: self.move_field(-1), "Earlier in the list"))
      row.addWidget(button("Down", lambda: self.move_field(1), "Later in the list"))
      row.addStretch(1)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addWidget(self.count)
      lay.addWidget(self.table, 1)
      lay.addLayout(row)
      lay.addLayout(form)
      lay.addWidget(self.errors)

   # -- reading -------------------------------------------------------------------------------------------------------

   def rows(self) -> list[model.FieldRow]:
      """!The fields as the table shows them.
      @return field_rows() ([] with nothing open)
      """
      doc = self.battle_doc()
      return model.field_rows(doc) if doc is not None else []

   def names(self) -> list[str]:
      """!The field names in order.
      @return names
      """
      return [r["name"] for r in self._rows]

   def refresh(self) -> None:
      """!Re-reads the fields.
      @return None
      """
      doc = self.battle_doc()
      self._rows = self.rows()
      names = self.names()
      # A local name: Doxygen 1.12 misreads membership tests on self.selected.
      chosen = self.selected
      chosen = chosen if chosen in names else (names[0] if names else None)
      self.selected = chosen
      self._filling = True
      try:
         self.count.setText(f"{len(names)}/{model.max_fields()} species fields (the engine's limit); each up to "
                            f"{model.max_width()} bits; read as {model.prefix()}NAME")
         self.table.setRowCount(len(self._rows))
         editable = QtCore.Qt.ItemFlag.ItemIsEditable
         for r, row in enumerate(self._rows):
            for key, c in FIELD_COLUMN.items():
               value = row[key]
               text = ", ".join(value) if isinstance(value, list) else str(value)
               item = QtWidgets.QTableWidgetItem(text)
               if key not in EDIT_KEYS:
                  item.setFlags(item.flags() & ~editable)
               if key == "default" and not row["default_stated"]:
                  item.setForeground(QtGui.QBrush(QtGui.QColor(UNSTATED_COLOR)))
                  item.setToolTip("Not stated: the engine's 0")
               if key == "width":
                  item.setToolTip(f"1-{model.max_width()} bits")
               self.table.setItem(r, c, item)
         self.table.resizeColumnsToContents()
         if chosen in names:
            self.table.selectRow(names.index(chosen))
      finally:
         self._filling = False
      self.setEnabled(doc is not None)
      self.show_errors()

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

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A name, width or default was typed.
      @param item  the cell
      @return None
      """
      names = self.names()
      if self._filling or not 0 <= item.row() < len(names):
         return
      name = names[item.row()]
      key = FIELD_COLUMNS[item.column()][0]
      text = item.text().strip()
      if key == "name":
         if text != name:
            self.rename_field(name, text)
         return
      if key not in EDIT_KEYS:
         return
      if text == "" and key == model.DEFAULT_KEY:
         self.set_field(name, key, None)
         return
      try:
         value = int(text)
      except ValueError:
         self.host.show_status(f"{key}: a whole number")
         self.host.changed()
         return
      self.set_field(name, key, value)

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

   def add_field(self, name: str | None = None, width: int | None = None, default: int | None = None) -> bool:
      """!Adds a field after the selected one.
      @param name     the name, or None for the form's
      @param width    bits, or None for the form's
      @param default  the default, or None for the form's (0: none written)
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      name = (name if name is not None else self.new_name.text()).strip()
      width = width if width is not None else self.new_width.value()
      default = default if default is not None else self.new_default.value()
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit("Add species field", lambda: model.add_field(doc, name, width, default or None, at)):
         self.selected = name
         self.new_name.clear()
         return True
      return False

   def remove_field(self) -> bool:
      """!Removes the selected field (and every species' value of it).
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self._edit("Remove species field", lambda: model.remove_field(doc, name)):
         self.selected = None
         return True
      return False

   def rename_field(self, old: str, new: str) -> bool:
      """!Renames a field (one undo step with the species' values and the derived expressions).
      @param old  current name
      @param new  new name
      @return True when renamed
      """
      doc = self.battle_doc()
      if doc is None or not new or new == old:
         self.host.changed()
         return False
      if self._edit("Rename species field", lambda: model.rename_field(doc, old, new)):
         self.selected = new
         return True
      return False

   def move_field(self, delta: int) -> bool:
      """!Moves the selected field up or down.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      moved = []
      ok = self._edit("Move species field", lambda: moved.append(model.move_field(doc, name, delta)))
      return ok and moved == [True]

   def set_field(self, name: str, key: str, value: int | None) -> bool:
      """!Changes a field's width or default.
      @param name   field name
      @param key    "width" or "default"
      @param value  the value, or None (default: 0)
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      return self._edit("Species field", lambda: model.set_field(doc, name, key, value))
