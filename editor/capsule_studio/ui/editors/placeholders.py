"""!The Placeholders tab of the script editor (engine E9; core.placeholders):
the scripts manifest's field placeholders and terms.

The placeholder table lists each name the game's field texts may use as
`{name}` with what it is bound to (a name slot of N characters, a declared
variable, a term, or a role of a party record with its slot), the most
cells it prints (from the engine's script compiler) and how many texts use
it. Typing a name renames it (the texts follow); the kind combo and the
value / extra cells change the binding. The terms table gives each concept
its word and plural. "Field texts are markup" says whether braces mean
placeholders (any declared placeholder turns it on). Every change is one
step of the manifest's placeholder history (Edit > Undo while this tab is
in front), checked with the engine's compiler; a refused one shows its
message in the window's status bar.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ...core import placeholders as model
from ..widgets import button

if TYPE_CHECKING:
   from ..script_shell import ScriptWindow

## Placeholder table columns: (key, header).
PLACEHOLDER_COLUMNS = [("name", "Placeholder"), ("kind", "Bound to"), ("value", "Value"), ("extra", "Form / slot"),
                       ("cells", "Prints (cells)"), ("uses", "Uses")]
## Placeholder table column of each key.
PLACEHOLDER_COLUMN = {key: c for c, (key, _h) in enumerate(PLACEHOLDER_COLUMNS)}
## Term table columns: (key, header).
TERM_COLUMNS = [("concept", "Concept"), ("one", "Word"), ("many", "Plural"), ("bindings", "Bound by"),
                ("uses", "Uses")]
## Term table column of each key.
TERM_COLUMN = {key: c for c, (key, _h) in enumerate(TERM_COLUMNS)}
## The binding kind whose value is a number (a name slot's length).
NUMBER_KIND = "name"
## The binding kind with a party slot.
RECORD_KIND = "record"
## The binding kind with a form.
TERM_KIND = "term"


class PlaceholdersPanel(QtWidgets.QWidget):
   """!Placeholders and terms of the open scripts manifest."""

   def __init__(self, window: ScriptWindow) -> None:
      """!Builds the tables.
      @param window  the script editor window
      """
      super().__init__()
      ## The script editor window (its project, placeholder_edit(), editors).
      self.editor = window
      ## True while the panel fills its tables.
      self._filling = False
      ## Field text markup on / off.
      self.markup = QtWidgets.QCheckBox("Field texts are markup ({name}, {prompt}, {@term})")
      self.markup.clicked.connect(lambda on: self.run("Markup", lambda p: model.set_markup(p, bool(on))))
      ## The placeholders.
      self.table = QtWidgets.QTableWidget(0, len(PLACEHOLDER_COLUMNS))
      self.table.setHorizontalHeaderLabels([h for _k, h in PLACEHOLDER_COLUMNS])
      self.table.verticalHeader().setVisible(False)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.itemChanged.connect(lambda item: self._typed(item))
      ## The terms.
      self.terms = QtWidgets.QTableWidget(0, len(TERM_COLUMNS))
      self.terms.setHorizontalHeaderLabels([h for _k, h in TERM_COLUMNS])
      self.terms.verticalHeader().setVisible(False)
      self.terms.itemChanged.connect(lambda item: self._term_typed(item))
      ## The check result of the placeholders.
      self.status = QtWidgets.QLabel()
      self.status.setWordWrap(True)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(self.markup)
      lay.addWidget(self.table, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_placeholder(), "Declare a placeholder (a name slot)"))
      row.addWidget(button("Remove", lambda: self.remove_placeholder(), "Remove the selected one (no text may use it)"))
      row.addWidget(button("Up", lambda: self.move_placeholder(-1)))
      row.addWidget(button("Down", lambda: self.move_placeholder(1)))
      lay.addLayout(row)
      lay.addWidget(QtWidgets.QLabel("Terms (fixed words: {@concept}, term bindings)"))
      lay.addWidget(self.terms, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add term...", lambda: self.add_term()))
      row.addWidget(button("Remove term", lambda: self.remove_term(), "Remove the selected term (nothing may use it)"))
      lay.addLayout(row)
      lay.addWidget(self.status)

   # -- reading ------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the placeholders and terms.
      @return None
      """
      p = self.editor.project
      self.setEnabled(p is not None)
      if p is None:
         return
      self._filling = True
      try:
         self.markup.setChecked(model.declared(p))
         rows = model.rows(p)
         self.table.setRowCount(len(rows))
         editable = QtCore.Qt.ItemFlag.ItemIsEditable
         for r, row in enumerate(rows):
            extra = ", ".join(f"{k} {v}" for k, v in row["extra"].items())
            texts = {"name": row["name"], "value": "" if row["value"] is None else str(row["value"]), "extra": extra,
                     "cells": "" if row["cells"] is None else str(row["cells"]), "uses": str(row["uses"])}
            for key, text in texts.items():
               item = QtWidgets.QTableWidgetItem(text)
               if key in ("cells", "uses"):
                  item.setFlags(item.flags() & ~editable)
               self.table.setItem(r, PLACEHOLDER_COLUMN[key], item)
            kind = QtWidgets.QComboBox()
            kind.addItems(model.kinds())
            kind.setCurrentText(str(row["kind"]))
            kind.activated.connect(lambda _i, n=row["name"], w=kind: self._kind_picked(n, w.currentText()))
            self.table.setCellWidget(r, PLACEHOLDER_COLUMN["kind"], kind)
         self.table.resizeColumnsToContents()
         terms = model.term_rows(p)
         self.terms.setRowCount(len(terms))
         for r, t in enumerate(terms):
            texts = {"concept": t["concept"], "one": t["one"] or "", "many": t["many"] or "",
                     "bindings": ", ".join("{" + n + "}" for n in t["bindings"]), "uses": str(t["uses"])}
            for key, text in texts.items():
               item = QtWidgets.QTableWidgetItem(text)
               if key not in ("one", "many"):
                  item.setFlags(item.flags() & ~editable)
               self.terms.setItem(r, TERM_COLUMN[key], item)
         self.terms.resizeColumnsToContents()
         _field, error = model.compiled(p)
         self.status.setText(error or f"{len(rows)} placeholder(s), {len(terms)} term(s)")
         self.status.setStyleSheet("color: #c03030;" if error else "")
      finally:
         self._filling = False

   def selected(self) -> str | None:
      """!The selected placeholder.
      @return its name, or None
      """
      rows = self.table.selectionModel().selectedRows()
      item = self.table.item(rows[0].row(), PLACEHOLDER_COLUMN["name"]) if rows else None
      return item.text() if item is not None else None

   # -- editing ------------------------------------------------------------------------

   def run(self, label: str, fn: Callable[[Any], object]) -> bool:
      """!One placeholder edit (core.placeholders.edit()); the editors follow renamed texts.
      @param label  undo label
      @param fn     callable(project)
      @return True when it went through
      """
      p = self.editor.project
      if p is None or self._filling:
         return False
      ok = self.editor.placeholder_edit(label, lambda: fn(p))
      self.refresh()
      return ok

   def _extra(self, kind: str, text: str) -> dict[str, Any]:
      """!The extra keys typed in the "Form / slot" cell ("slot 1", "form many", or a bare value).
      @param kind  the binding kind
      @param text  the cell text
      @return {key: value}
      """
      out: dict[str, Any] = {}
      keys = model.extra_keys(kind)
      for part in [x.strip() for x in text.split(",") if x.strip()]:
         words = part.split()
         key, value = (words[0], words[-1]) if len(words) > 1 else (keys[0] if keys else "", words[0])
         out[key] = int(value) if value.isdigit() else value
      return out

   def _binding_of(self, row: int, kind: str | None = None) -> tuple[str, str, Any, dict[str, Any]]:
      """!The binding a table row shows.
      @param row   table row
      @param kind  a kind to use instead of the row's
      @return (name, kind, value, extra)
      """
      name = self.table.item(row, PLACEHOLDER_COLUMN["name"]).data(QtCore.Qt.ItemDataRole.UserRole) or \
         self.table.item(row, PLACEHOLDER_COLUMN["name"]).text()
      kind = kind or self.table.cellWidget(row, PLACEHOLDER_COLUMN["kind"]).currentText()
      text = self.table.item(row, PLACEHOLDER_COLUMN["value"]).text().strip()
      value: Any = int(text) if kind == NUMBER_KIND and text.isdigit() else text
      return name, kind, value, self._extra(kind, self.table.item(row, PLACEHOLDER_COLUMN["extra"]).text())

   def _typed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A placeholder cell was typed: renames it or changes its binding.
      @param item  the cell
      @return None
      """
      if self._filling:
         return
      p = self.editor.project
      names = [r["name"] for r in model.rows(p)] if p is not None else []
      if not 0 <= item.row() < len(names):
         return
      old = names[item.row()]
      if item.column() == PLACEHOLDER_COLUMN["name"]:
         self.rename_placeholder(old, item.text())
         return
      _name, kind, value, extra = self._binding_of(item.row())
      self.set_placeholder(old, kind, value, extra)

   def _kind_picked(self, name: str, kind: str) -> None:
      """!Another kind was picked: the binding starts with the row's value.
      @param name  the placeholder
      @param kind  the kind
      @return None
      """
      p = self.editor.project
      row = [r["name"] for r in model.rows(p)].index(name) if p is not None else -1
      if row < 0:
         return
      _n, _k, value, _extra = self._binding_of(row, kind)
      self.set_placeholder(name, kind, value, {})

   def add_placeholder(self, name: str | None = None, kind: str = NUMBER_KIND, value: Any = None,
                       extra: dict[str, Any] | None = None) -> bool:
      """!Declares a placeholder.
      @param name   its name, or None to ask
      @param kind   binding kind (default: a name slot)
      @param value  its value (default: a name slot of the engine's longest name)
      @param extra  form / slot
      @return True when it went through
      """
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add placeholder", "Name (lower case):")
         if not ok:
            return False
      if value is None:
         value = model.max_name_length()
      return self.run("Add placeholder", lambda p: model.add_placeholder(p, name, kind, value, extra))

   def set_placeholder(self, name: str, kind: str, value: Any, extra: dict[str, Any] | None = None) -> bool:
      """!Changes a binding.
      @param name   the placeholder
      @param kind   binding kind
      @param value  its value
      @param extra  form / slot
      @return True when it went through
      """
      return self.run("Placeholder", lambda p: model.set_placeholder(p, name, kind, value, extra))

   def rename_placeholder(self, old: str, new: str) -> bool:
      """!Renames a placeholder (the texts follow).
      @param old  current name
      @param new  new name
      @return True when it went through
      """
      if new.strip() == old:
         return False
      return self.run("Rename placeholder", lambda p: model.rename_placeholder(p, old, new))

   def remove_placeholder(self, name: str | None = None) -> bool:
      """!Removes a placeholder no text uses.
      @param name  the placeholder, or None for the selected one
      @return True when it went through
      """
      name = name or self.selected()
      return name is not None and self.run("Remove placeholder", lambda p: model.remove_placeholder(p, name))

   def move_placeholder(self, delta: int, name: str | None = None) -> bool:
      """!Moves a placeholder (its index).
      @param delta  -1 up, +1 down
      @param name   the placeholder, or None for the selected one
      @return True when it went through
      """
      name = name or self.selected()
      return name is not None and self.run("Move placeholder", lambda p: model.move_placeholder(p, name, delta))

   def _term_typed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A term's word or plural was typed.
      @param item  the cell
      @return None
      """
      if self._filling:
         return
      r = item.row()
      concept = self.terms.item(r, TERM_COLUMN["concept"]).text()
      one = self.terms.item(r, TERM_COLUMN["one"]).text()
      many = self.terms.item(r, TERM_COLUMN["many"]).text().strip() or None
      self.set_term(concept, one, many)

   def add_term(self, concept: str | None = None, word: str | None = None) -> bool:
      """!Adds a term.
      @param concept  the concept, or None to ask
      @param word     its word, or None to ask
      @return True when it went through
      """
      if concept is None:
         concept, ok = QtWidgets.QInputDialog.getText(self, "Add term", "Concept (lower case):")
         if not ok:
            return False
      if word is None:
         word, ok = QtWidgets.QInputDialog.getText(self, "Add term", f"Word for {concept}:")
         if not ok:
            return False
      return self.set_term(concept, word)

   def set_term(self, concept: str, word: str, plural: str | None = None) -> bool:
      """!Sets a term.
      @param concept  the concept
      @param word     its word
      @param plural   its plural, or None
      @return True when it went through
      """
      return self.run("Term", lambda p: model.set_term(p, concept, word, plural))

   def remove_term(self, concept: str | None = None) -> bool:
      """!Removes a term nothing uses.
      @param concept  the concept, or None for the selected one
      @return True when it went through
      """
      if concept is None:
         rows = self.terms.selectionModel().selectedRows()
         if not rows:
            return False
         concept = self.terms.item(rows[0].row(), TERM_COLUMN["concept"]).text()
      return self.run("Remove term", lambda p: model.remove_term(p, concept))

