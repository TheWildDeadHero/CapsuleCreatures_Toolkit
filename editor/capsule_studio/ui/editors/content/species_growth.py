"""!The Species page's growth tabs (D-26 section 4, engine G4): the selected
species' transformation rules, forms and training yields, with a preview of
which rule fires.

Transformations: the rules in order (the first that holds wins), each with the
species it becomes, its expression, its triggers (as given, or the ones the
engine works out) and the held item / second creature; the row below edits the
selected rule or adds one (the trigger boxes are the engine's TRIGGERS). The
preview asks the engine's evaluator what a record of the species does on a
trigger: a level, an item, the context values (Structure > Growth & training)
and any other role as ROLE=V (ROLE.STAT=V for a per-stat role).
Forms: each form with its overrides and its rule; the row below edits the
selected one (types and base stats as text, empty: the species' own; a form
without an expression is chosen only by effect logic `form WHO NAME`; the
name "base" adds the rule back to the species' own form).
Yields: one spin per stat the structure's training gives a yield field.
Combine moves (B1): the moves a combination's combine_moves source gives a
result of this species, in order (Add / Remove / Up / Down).
Every widget follows the compiled data (S11); edits go through
core.species_growth, one undo step each.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ....core import battle, species_growth
from ....core.document import DocumentError
from ....core.structure import transformation
from ...widgets import ask, button
from ..battle_common import NONE_TEXT, combo, set_check, set_combo, set_spin, spin

if TYPE_CHECKING:
   from .species import SpeciesPanel

## Rule table headings.
RULE_HEADINGS = ("#", "Becomes", "When", "On (given)", "Looked at on", "Item used up", "Also")
## Form table headings.
FORM_HEADINGS = ("Form", "Name", "Overrides", "When", "On")
## Separator of typed lists (triggers, types, ROLE=V parts are spaces).
LIST_SEPARATOR = ","
## Separator of a typed NAME=VALUE.
ASSIGN = "="
## Separator of a per-stat role's stat (ROLE.STAT=V).
STAT_DOT = "."
## Text colour of a rule that fires in the preview.
FIRES_COLOR = "#2a7a2a"
## Height of the growth tabs' tables, rows shown.
TABLE_ROWS = 4
## Pixels of a table row (the tabs' height follows).
ROW_PIXELS = 26


def _table(headings: tuple[str, ...]) -> QtWidgets.QTableWidget:
   """!A read-only, row-selecting table.
   @param headings  column headings
   @return the table
   """
   t = QtWidgets.QTableWidget(0, len(headings))
   t.setHorizontalHeaderLabels(list(headings))
   t.verticalHeader().setVisible(False)
   t.horizontalHeader().setStretchLastSection(True)
   t.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
   t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
   t.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
   t.setMinimumHeight(ROW_PIXELS * (TABLE_ROWS + 1))
   return t


def _selected_row(table: QtWidgets.QTableWidget) -> int | None:
   """!A table's selected row.
   @param table  the table
   @return its index, or None
   """
   rows = table.selectionModel().selectedRows()
   return rows[0].row() if rows else None


def _assignments(text: str) -> dict[str, Any]:
   """!ROLE=V parts typed in the preview (ROLE.STAT=V: a per-stat role's stat).
   @param text  space separated parts
   @return {role: value or {stat: value}}
   @throws DocumentError for a part that is not NAME=NUMBER
   """
   out: dict[str, Any] = {}
   for part in text.split():
      name, sep, value = part.partition(ASSIGN)
      if not sep or not name or not value.lstrip("-").isdigit():
         raise DocumentError(f"roles: ROLE=NUMBER or ROLE.STAT=NUMBER (got {part!r})")
      role, dot, stat = name.partition(STAT_DOT)
      if dot:
         out.setdefault(role, {})[stat] = int(value)
      else:
         out[name] = int(value)
   return out


class SpeciesGrowthTabs(QtWidgets.QTabWidget):
   """!Transformations, Forms and Yields of the Species page's species."""

   def __init__(self, page: SpeciesPanel) -> None:
      """!Builds the three tabs.
      @param page  the Species page (its project, selection and edits)
      """
      super().__init__()
      ## The Species page.
      self.page = page
      ## True while the tabs fill their own widgets.
      self._filling = False
      self.addTab(self._build_transforms(), "Transformations")
      self.addTab(self._build_forms(), "Forms")
      self.addTab(self._build_yields(), "Yields")
      self.addTab(self._build_combine_moves(), "Combine moves")

   # -- building ------------------------------------------------------------------------------------------------------

   def _trigger_boxes(self, row: QtWidgets.QHBoxLayout) -> dict[str, QtWidgets.QCheckBox]:
      """!One box per trigger of the engine.
      @param row  layout they go into
      @return {trigger: box}
      """
      boxes = {}
      for t in species_growth.triggers():
         box = QtWidgets.QCheckBox(t)
         boxes[t] = box
         row.addWidget(box)
      return boxes

   def _build_transforms(self) -> QtWidgets.QWidget:
      """!The Transformations tab.
      @return the tab
      """
      w = QtWidgets.QWidget()
      ## The species' rules.
      self.rules = _table(RULE_HEADINGS)
      self.rules.itemSelectionChanged.connect(lambda: self._rule_chosen())
      ## The species the edited rule becomes.
      self.into = QtWidgets.QComboBox()
      ## The edited rule's expression.
      self.when = QtWidgets.QLineEdit()
      self.when.setPlaceholderText("e.g. level >= 16, item == fire_stone, time_of_day == night")
      on_row = QtWidgets.QHBoxLayout()
      ## The edited rule's triggers (none ticked: the engine works them out).
      self.on = self._trigger_boxes(on_row)
      on_row.addStretch(1)
      ## The edited rule uses up the held item.
      self.takes_item = QtWidgets.QCheckBox("held item used up")
      ## The edited rule's second creature.
      self.also = QtWidgets.QComboBox()
      edit_row = QtWidgets.QHBoxLayout()
      edit_row.addWidget(QtWidgets.QLabel("Becomes"))
      edit_row.addWidget(self.into)
      edit_row.addWidget(QtWidgets.QLabel("when"))
      edit_row.addWidget(self.when, 1)
      edit_row.addWidget(self.takes_item)
      edit_row.addWidget(QtWidgets.QLabel("also"))
      edit_row.addWidget(self.also)
      buttons = QtWidgets.QHBoxLayout()
      buttons.addWidget(QtWidgets.QLabel("On"))
      buttons.addLayout(on_row, 1)
      buttons.addWidget(button("Add", lambda: self.add_rule(), "Add the rule above as the last one"))
      buttons.addWidget(button("Apply", lambda: self.apply_rule(), "Change the selected rule to the one above"))
      buttons.addWidget(button("Remove", lambda: self.remove_rule(), "Remove the selected rule"))
      buttons.addWidget(button("Up", lambda: self.move_rule(-1), "Looked at earlier"))
      buttons.addWidget(button("Down", lambda: self.move_rule(1), "Looked at later"))
      ## Preview trigger.
      self.trigger = QtWidgets.QComboBox()
      self.trigger.addItems(species_growth.triggers())
      self.trigger.currentIndexChanged.connect(lambda *a: self.update_preview())
      ## Preview item.
      self.item = QtWidgets.QComboBox()
      self.item.currentIndexChanged.connect(lambda *a: self.update_preview())
      ## Preview level.
      self.level = QtWidgets.QSpinBox()
      self.level.setRange(1, battle.level_max(None))
      self.level.valueChanged.connect(lambda *a: self.update_preview())
      ## Preview context value combos ({name: QComboBox or QSpinBox}).
      self.context = {}
      ## Row holding them.
      self.context_row = QtWidgets.QHBoxLayout()
      ## Other preview roles (ROLE=V ...).
      self.roles = QtWidgets.QLineEdit()
      self.roles.setPlaceholderText("other roles: friendship=220 stat_training.attack=4")
      self.roles.editingFinished.connect(lambda: self.update_preview())
      ## Preview result.
      self.result = QtWidgets.QLabel()
      self.result.setWordWrap(True)
      self.result.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      preview = QtWidgets.QHBoxLayout()
      preview.addWidget(QtWidgets.QLabel("Preview: on"))
      preview.addWidget(self.trigger)
      preview.addWidget(QtWidgets.QLabel("item"))
      preview.addWidget(self.item)
      preview.addWidget(QtWidgets.QLabel("level"))
      preview.addWidget(self.level)
      preview.addLayout(self.context_row)
      preview.addWidget(self.roles, 1)
      lay = QtWidgets.QVBoxLayout(w)
      lay.addWidget(self.rules, 1)
      lay.addLayout(edit_row)
      lay.addLayout(buttons)
      lay.addLayout(preview)
      lay.addWidget(self.result)
      return w

   def _build_forms(self) -> QtWidgets.QWidget:
      """!The Forms tab.
      @return the tab
      """
      w = QtWidgets.QWidget()
      ## The species' forms.
      self.forms = _table(FORM_HEADINGS)
      self.forms.itemSelectionChanged.connect(lambda: self._form_chosen())
      ## The edited form's name.
      self.form_name = QtWidgets.QLineEdit()
      ## The edited form's types (comma separated; empty: the species').
      self.form_types = QtWidgets.QLineEdit()
      self.form_types.setPlaceholderText("types (empty: the species')")
      ## The edited form's base stats (comma separated; empty: the species').
      self.form_base = QtWidgets.QLineEdit()
      self.form_base.setPlaceholderText("base stats, one per stat (empty: the species')")
      ## The edited form's front sprite.
      self.form_front = QtWidgets.QLineEdit()
      self.form_front.setPlaceholderText("front sprite (empty: the species')")
      ## The edited form's expression (empty: effect logic only).
      self.form_when = QtWidgets.QLineEdit()
      self.form_when.setPlaceholderText("when (empty: only effect logic `form WHO NAME` chooses it)")
      on_row = QtWidgets.QHBoxLayout()
      ## The edited form's triggers.
      self.form_on = self._trigger_boxes(on_row)
      on_row.addStretch(1)
      grid = QtWidgets.QFormLayout()
      grid.addRow("Name", self.form_name)
      grid.addRow("Types", self.form_types)
      grid.addRow("Base", self.form_base)
      grid.addRow("Front", self.form_front)
      grid.addRow("When", self.form_when)
      grid.addRow("On", on_row)
      buttons = QtWidgets.QHBoxLayout()
      buttons.addWidget(button("Add", lambda: self.add_form(), "Add the form above (name base: the rule back to "
                                                               "the species' own form)"))
      buttons.addWidget(button("Apply", lambda: self.apply_form(), "Change the selected form to the one above"))
      buttons.addWidget(button("Rename", lambda: self.rename_form(), "Rename the selected form (its effect logic "
                                                                     "follows)"))
      buttons.addWidget(button("Remove", lambda: self.remove_form(), "Remove the selected form"))
      buttons.addStretch(1)
      ## Who names the selected form (effect logic).
      self.form_users = QtWidgets.QLabel()
      self.form_users.setWordWrap(True)
      lay = QtWidgets.QVBoxLayout(w)
      lay.addWidget(self.forms, 1)
      lay.addLayout(grid)
      lay.addLayout(buttons)
      lay.addWidget(self.form_users)
      return w

   def _build_yields(self) -> QtWidgets.QWidget:
      """!The Yields tab (its spins follow the training's yield fields: _fill_yields()).
      @return the tab
      """
      w = QtWidgets.QWidget()
      ## Yield spins by stat.
      self.yield_spins = {}
      ## Row holding them.
      self.yield_row = QtWidgets.QHBoxLayout()
      ## Training preview: the receiver's level.
      self.train_level = QtWidgets.QSpinBox()
      self.train_level.setRange(1, battle.level_max(None))
      self.train_level.valueChanged.connect(lambda *a: self.update_training())
      ## Training preview result.
      self.train_result = QtWidgets.QLabel()
      self.train_result.setWordWrap(True)
      note = QtWidgets.QLabel("What defeating this species gives each stat of everyone sharing its experience "
                              "(Structure > Growth & training: the gain formula, the caps, the yield fields).")
      note.setWordWrap(True)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Defeated by a creature of level"))
      row.addWidget(self.train_level)
      row.addWidget(self.train_result, 1)
      lay = QtWidgets.QVBoxLayout(w)
      lay.addWidget(note)
      lay.addLayout(self.yield_row)
      lay.addLayout(row)
      lay.addStretch(1)
      return w

   def _build_combine_moves(self) -> QtWidgets.QWidget:
      """!The Combine moves tab (B1: the moves a combination's combine_moves source gives a result of this species).
      @return the tab
      """
      w = QtWidgets.QWidget()
      ## The species' combine moves, in order.
      self.combine_moves = QtWidgets.QListWidget()
      self.combine_moves.setMaximumHeight(ROW_PIXELS * (TABLE_ROWS + 1))
      ## The move to add.
      self.combine_move = QtWidgets.QComboBox()
      note = QtWidgets.QLabel("Moves a combination may teach a result of this species (Structure > Combination: a "
                              "method's combine_moves source).")
      note.setWordWrap(True)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.combine_move, 1)
      row.addWidget(button("Add", lambda: self.add_combine_move(), "Add the move at the end"))
      row.addWidget(button("Remove", lambda: self.remove_combine_move(), "Remove the selected move"))
      row.addWidget(button("Up", lambda: self.move_combine_move(-1)))
      row.addWidget(button("Down", lambda: self.move_combine_move(1)))
      lay = QtWidgets.QVBoxLayout(w)
      lay.addWidget(note)
      lay.addWidget(self.combine_moves)
      lay.addLayout(row)
      lay.addStretch(1)
      return w

   # -- filling -------------------------------------------------------------------------------------------------------

   def fill(self, name: str | None) -> None:
      """!Shows a species' rules, forms and yields.
      @param name  species name, or None
      @return None
      """
      p = self.page.project()
      doc = p.battle if p is not None else None
      self._filling = True
      try:
         species = p.names("species") if p is not None else []
         for box in (self.into, self.also):
            keep = box.currentText()
            set_combo(box, ([NONE_TEXT] if box is self.also else []) + species, keep or None)
         keep = self.item.currentText()
         set_combo(self.item, [NONE_TEXT] + (p.names("items") if p is not None else []), keep or NONE_TEXT)
         most = battle.level_max(p.structure if p is not None else None)
         for s in (self.level, self.train_level):
            s.setMaximum(most)
         self._fill_contexts(doc)
         self._fill_rules(doc, name)
         self._fill_forms(doc, name)
         self._fill_yields(doc, name)
         self._fill_combine_moves(p, name)
      finally:
         self._filling = False
      self.setEnabled(name is not None)
      self.update_preview()
      self.update_training()

   def _fill_contexts(self, doc: Any) -> None:
      """!(Re)builds the preview's context value widgets (a combo of names, or a spin of a range).
      @param doc  battle Document, or None
      @return None
      """
      rows = transformation.context_rows(doc) if doc is not None else []
      if [r["name"] for r in rows] != list(self.context):
         while self.context_row.count():
            w = self.context_row.takeAt(0).widget()
            if w is not None:
               w.hide()   # out of sight at once (the deletion waits for the event loop)
               w.deleteLater()
         self.context = {}
         for r in rows:
            self.context_row.addWidget(QtWidgets.QLabel(r["name"]))
            if r["values"]:
               box: Any = QtWidgets.QComboBox()
               box.addItems(r["values"])
               box.currentIndexChanged.connect(lambda *a: self.update_preview())
            else:
               box = spin(r["range"][0], r["range"][1], lambda _v: self.update_preview())
            self.context[r["name"]] = box
            self.context_row.addWidget(box)
            if isinstance(box, QtWidgets.QComboBox):
               box.setCurrentIndex(r["default"])
            else:
               set_spin(box, r["default"])

   def _fill_rules(self, doc: Any, name: str | None) -> None:
      """!Shows the rules.
      @param doc   battle Document, or None
      @param name  species name, or None
      @return None
      """
      rows = species_growth.transforms(doc, name) if doc is not None and name is not None else []
      chosen = _selected_row(self.rules)
      self.rules.setRowCount(len(rows))
      for r, row in enumerate(rows):
         texts = (str(row["index"]), row["into"], row["when"], LIST_SEPARATOR.join(row["on"] or []) or "(auto)",
                  LIST_SEPARATOR.join(row["triggers"]), "yes" if row["takes_item"] else "", row["also"] or "")
         for c, text in enumerate(texts):
            self.rules.setItem(r, c, QtWidgets.QTableWidgetItem(text))
      self.rules.resizeColumnsToContents()
      if chosen is not None and chosen < len(rows):
         self.rules.selectRow(chosen)

   def _fill_forms(self, doc: Any, name: str | None) -> None:
      """!Shows the forms.
      @param doc   battle Document, or None
      @param name  species name, or None
      @return None
      """
      rows = species_growth.forms(doc, name) if doc is not None and name is not None else []
      chosen = _selected_row(self.forms)
      self.forms.setRowCount(len(rows))
      for r, row in enumerate(rows):
         texts = (str(row["form"]), row["name"], LIST_SEPARATOR.join(row["overrides"]) or "-",
                  row["when"] or "(effect logic)", LIST_SEPARATOR.join(row["on"] or []) or "(auto)")
         for c, text in enumerate(texts):
            self.forms.setItem(r, c, QtWidgets.QTableWidgetItem(text))
      self.forms.resizeColumnsToContents()
      if chosen is not None and chosen < len(rows):
         self.forms.selectRow(chosen)

   def _fill_yields(self, doc: Any, name: str | None) -> None:
      """!(Re)builds the yield spins (one per stat with a yield field).
      @param doc   battle Document, or None
      @param name  species name, or None
      @return None
      """
      rows = species_growth.yields(doc, name) if doc is not None and name is not None else []
      if [r["stat"] for r in rows] != list(self.yield_spins):
         while self.yield_row.count():
            w = self.yield_row.takeAt(0).widget()
            if w is not None:
               w.hide()   # out of sight at once (the deletion waits for the event loop)
               w.deleteLater()
         self.yield_spins = {}
         for r in rows:
            box = spin(0, r["max"], lambda v, s=r["stat"]: self.set_yield(s, v))
            self.yield_row.addWidget(QtWidgets.QLabel(r["stat"]))
            self.yield_row.addWidget(box)
            self.yield_spins[r["stat"]] = box
         if not rows:
            self.yield_row.addWidget(QtWidgets.QLabel("no yields (Structure > Growth & training)"))
         self.yield_row.addStretch(1)
      for r in rows:
         box = self.yield_spins[r["stat"]]
         box.setMaximum(r["max"])
         set_spin(box, r["value"])
         box.setToolTip(f"species field {r['field']}" + ("" if r["own"] else " (the field's default)"))

   def _fill_combine_moves(self, p: Any, name: str | None) -> None:
      """!Shows the species' combine moves and the moves to add.
      @param p     BattleProject, or None
      @param name  species name, or None
      @return None
      """
      row = self.combine_moves.currentRow()
      self.combine_moves.clear()
      self.combine_moves.addItems(self.combine_move_names())
      if 0 <= row < self.combine_moves.count():
         self.combine_moves.setCurrentRow(row)
      keep = self.combine_move.currentText()
      moves = p.names("moves") if p is not None else []
      set_combo(self.combine_move, moves, keep if keep in moves else (moves[0] if moves else None))

   def combine_move_names(self) -> list[str]:
      """!The selected species' combine moves.
      @return move names
      """
      e = self.page.current()
      given = e.get(battle.COMBINE_MOVES_KEY) if isinstance(e, dict) else None
      return [m for m in given if isinstance(m, str)] if isinstance(given, list) else []

   def _set_combine_moves(self, moves: list[str]) -> None:
      """!States the species' combine moves (none: the key goes).
      @param moves  move names
      @return None
      """
      self.page.set_field(battle.COMBINE_MOVES_KEY, list(moves) or None, "Set combine moves")

   def add_combine_move(self, move: str | None = None) -> None:
      """!Adds a combine move at the end.
      @param move  its name, or None for the chooser's
      @return None
      """
      move = move or self.combine_move.currentText()
      moves = self.combine_move_names()
      if move and move not in moves:
         self._set_combine_moves(moves + [move])

   def remove_combine_move(self) -> None:
      """!Removes the selected combine move.
      @return None
      """
      moves, k = self.combine_move_names(), self.combine_moves.currentRow()
      if 0 <= k < len(moves):
         self._set_combine_moves(moves[:k] + moves[k + 1:])

   def move_combine_move(self, delta: int) -> None:
      """!Moves the selected combine move up or down.
      @param delta  -1 up, +1 down
      @return None
      """
      moves, k = self.combine_move_names(), self.combine_moves.currentRow()
      j = k + delta
      if 0 <= k < len(moves) and 0 <= j < len(moves):
         moves[k], moves[j] = moves[j], moves[k]
         self._set_combine_moves(moves)
         self.combine_moves.setCurrentRow(j)

   def _rule_chosen(self) -> None:
      """!A rule was picked: the edit row shows it.
      @return None
      """
      row = _selected_row(self.rules)
      doc, name = self.page.battle_doc(), self.page.selected
      if self._filling or row is None or doc is None or name is None:
         return
      rules = species_growth.transforms(doc, name)
      if row >= len(rules):
         return
      r = rules[row]
      set_combo(self.into, [self.into.itemText(i) for i in range(self.into.count())], r["into"])
      self.when.setText(r["when"])
      for t, box in self.on.items():
         set_check(box, r["on"] is not None and t in r["on"])
      set_check(self.takes_item, r["takes_item"])
      set_combo(self.also, [self.also.itemText(i) for i in range(self.also.count())], r["also"] or NONE_TEXT)

   def _form_chosen(self) -> None:
      """!A form was picked: the edit rows show it.
      @return None
      """
      row = _selected_row(self.forms)
      doc, name = self.page.battle_doc(), self.page.selected
      if self._filling or row is None or doc is None or name is None:
         return
      rows = species_growth.forms(doc, name)
      if row >= len(rows):
         return
      f = species_growth.form(doc, name, rows[row]["name"])
      self.form_name.setText(rows[row]["name"])
      self.form_types.setText(LIST_SEPARATOR.join(f.get("types", [])))
      self.form_base.setText(LIST_SEPARATOR.join(str(v) for v in f.get("base", [])))
      self.form_front.setText(f.get("front", "") or "")
      self.form_when.setText(f.get(species_growth.WHEN_KEY, "") or "")
      for t, box in self.form_on.items():
         set_check(box, t in (f.get(species_growth.ON_KEY) or []))
      users = species_growth.form_users(doc, rows[row]["name"])
      self.form_users.setText("Effect logic naming it: " + (", ".join(users) if users else "none"))

   # -- previews ------------------------------------------------------------------------------------------------------

   def preview_context(self) -> dict[str, Any]:
      """!The preview's context values.
      @return {name: value name or number}
      """
      return {n: (box.currentText() if isinstance(box, QtWidgets.QComboBox) else box.value())
              for n, box in self.context.items()}

   def update_preview(self) -> None:
      """!Asks the engine which rule fires (core.species_growth.preview()).
      @return None
      """
      doc, name = self.page.battle_doc(), self.page.selected
      if self._filling or doc is None or name is None:
         self.result.setText("")
         return
      item = self.item.currentText()
      try:
         roles = {"level": self.level.value(), **_assignments(self.roles.text())}
         r = species_growth.preview(doc, name, roles, self.trigger.currentText(),
                                    None if item in ("", NONE_TEXT) else item, self.preview_context())
      except DocumentError as e:
         self.result.setText(f"({e})")
         return
      lines = [f"<b style='color:{FIRES_COLOR}'>{name} {r['text']}</b>"]
      for rule in r["rules"]:
         state = "holds" if rule["holds"] else "does not hold"
         heard = "" if rule["listens"] else f" (not looked at on {self.trigger.currentText()})"
         lines.append(f"{rule['owner']}: <code>{rule['when']}</code> {state}{heard}")
      self.result.setText("<br>".join(lines))

   def update_training(self) -> None:
      """!What defeating the species gives (core.species_growth.training_preview()).
      @return None
      """
      doc, name = self.page.battle_doc(), self.page.selected
      if self._filling or doc is None or name is None:
         self.train_result.setText("")
         return
      try:
         r = species_growth.training_preview(doc, name, self.train_level.value())
      except DocumentError as e:
         self.train_result.setText(f"({e})")
         return
      gains = [f"{s} +{g}" for s, g in zip(r["stats"], r["gain"]) if g]
      self.train_result.setText(", ".join(gains) if gains else "nothing")

   # -- editing -------------------------------------------------------------------------------------------------------

   def _edited_rule(self) -> dict[str, Any]:
      """!The rule the edit row shows.
      @return {"into", "when", "on", "takes_item", "also"}
      """
      also = self.also.currentText()
      return {"into": self.into.currentText(), "when": self.when.text().strip(),
              "on": [t for t, box in self.on.items() if box.isChecked()] or None,
              "takes_item": self.takes_item.isChecked(), "also": None if also in ("", NONE_TEXT) else also}

   def add_rule(self) -> bool:
      """!Adds the edit row's rule.
      @return True when added
      """
      doc, name, r = self.page.battle_doc(), self.page.selected, self._edited_rule()
      if doc is None or name is None:
         return False
      return self.page.edit("Add transformation", lambda: species_growth.add_transform(
         doc, name, r["into"], r["when"], r["on"], r["takes_item"], r["also"]))

   def apply_rule(self) -> bool:
      """!Changes the selected rule to the edit row's.
      @return True when it went through
      """
      doc, name, row, r = self.page.battle_doc(), self.page.selected, _selected_row(self.rules), self._edited_rule()
      if doc is None or name is None or row is None:
         return False

      def change() -> None:
         """!Writes every field of the rule.
         @return None
         """
         for field in species_growth.TRANSFORM_FIELDS:
            species_growth.set_transform(doc, name, row, field, r[field])

      return self.page.edit("Set transformation", change)

   def remove_rule(self) -> bool:
      """!Removes the selected rule.
      @return True when removed
      """
      doc, name, row = self.page.battle_doc(), self.page.selected, _selected_row(self.rules)
      if doc is None or name is None or row is None:
         return False
      return self.page.edit("Remove transformation", lambda: species_growth.remove_transform(doc, name, row))

   def move_rule(self, delta: int) -> bool:
      """!Moves the selected rule.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, name, row = self.page.battle_doc(), self.page.selected, _selected_row(self.rules)
      if doc is None or name is None or row is None:
         return False
      moved = []
      ok = self.page.edit("Move transformation",
                          lambda: moved.append(species_growth.move_transform(doc, name, row, delta)))
      if ok and moved == [True]:
         self.rules.selectRow(row + delta)
         return True
      return False

   def _edited_overrides(self) -> dict[str, Any]:
      """!The overrides the form rows give (an empty field: the species' own, None).
      @return {override: value or None}
      @throws DocumentError for base stats that are not numbers
      """
      types = [t.strip() for t in self.form_types.text().split(LIST_SEPARATOR) if t.strip()]
      base_text = [v.strip() for v in self.form_base.text().split(LIST_SEPARATOR) if v.strip()]
      if not all(v.isdigit() for v in base_text):
         raise DocumentError("base: whole numbers, comma separated")
      return {"types": types or None, "base": [int(v) for v in base_text] or None,
              "front": self.form_front.text().strip() or None}

   def add_form(self) -> bool:
      """!Adds the form rows' form.
      @return True when added
      """
      doc, name = self.page.battle_doc(), self.page.selected
      if doc is None or name is None:
         return False
      # a form without an expression has no triggers (the boxes count only with one)
      on = [t for t, box in self.form_on.items() if box.isChecked()] or None if self.form_when.text().strip() else None

      def change() -> None:
         """!Adds the form with its overrides.
         @return None
         """
         given = {k: v for k, v in self._edited_overrides().items() if v is not None}
         species_growth.add_form(doc, name, self.form_name.text(), self.form_when.text() or None, on, given)

      return self.page.edit("Add form", change)

   def _selected_form(self) -> str | None:
      """!The selected form's name.
      @return the name, or None
      """
      row = _selected_row(self.forms)
      item = self.forms.item(row, 1) if row is not None else None
      return item.text() if item is not None else None

   def apply_form(self) -> bool:
      """!Changes the selected form to the form rows' (not its name: Rename).
      @return True when it went through
      """
      doc, name, chosen = self.page.battle_doc(), self.page.selected, self._selected_form()
      if doc is None or name is None or chosen is None:
         return False
      on = [t for t, box in self.form_on.items() if box.isChecked()] or None
      is_base = chosen.lower() == species_growth.base_form()

      def change() -> None:
         """!Writes the overrides and the rule.
         @return None
         """
         if not is_base:
            for key, value in self._edited_overrides().items():
               species_growth.set_form(doc, name, chosen, key, value)
         species_growth.set_form(doc, name, chosen, species_growth.WHEN_KEY, self.form_when.text() or None)
         if self.form_when.text().strip():
            species_growth.set_form(doc, name, chosen, species_growth.ON_KEY, on)

      return self.page.edit("Set form", change)

   def rename_form(self, new: str | None = None) -> bool:
      """!Renames the selected form.
      @param new  the new name, or None for the name row's
      @return True when renamed
      """
      doc, name, chosen = self.page.battle_doc(), self.page.selected, self._selected_form()
      if doc is None or name is None or chosen is None:
         return False
      new = (new or self.form_name.text()).strip()
      return self.page.edit("Rename form", lambda: species_growth.rename_form(doc, name, chosen, new))

   def remove_form(self) -> bool:
      """!Removes the selected form.
      @return True when removed
      """
      doc, name, chosen = self.page.battle_doc(), self.page.selected, self._selected_form()
      if doc is None or name is None or chosen is None:
         return False
      # C6 (review4 finding 13): saved records keep their form numbers (headless: No, as the CLI wants --force)
      warning = species_growth.form_removal_warning(doc, name, chosen)
      b = QtWidgets.QMessageBox.StandardButton
      if warning is not None and ask(self, "Remove form", f"{warning}\n\nRemove it anyway?", b.Yes | b.No, b.No,
                                     b.No) != b.Yes:
         return False
      return self.page.edit("Remove form", lambda: species_growth.remove_form(doc, name, chosen))

   def set_yield(self, stat: str, value: int) -> bool:
      """!Sets the species' yield of a stat.
      @param stat   stat name
      @param value  the yield
      @return True when it went through
      """
      doc, name = self.page.battle_doc(), self.page.selected
      if self._filling or doc is None or name is None:
         return False
      row = next((y for y in species_growth.yields(doc, name) if y["stat"] == stat), None)
      if row is None or row["value"] == value:
         return False
      return self.page.edit("Set yield", lambda: species_growth.set_yield(doc, name, stat, value))
