"""![S6b] The World page's "Interactions" panel (engine C13b): the world's cell interaction rules, what pressing
Accept while facing a cell does when no object and no sign answers. The rules are tried in the order listed (the
first that holds starts its script), so Up / Down move a rule earlier or later. A rule picks the faced cell's
behavior from the world's behaviors and its script from the world's scripts manifest, and may ask for a facing
direction, a movement mode, a set flag, the faced cell on the player's own level, or to be tried only after the field
actions had nothing to do. Every change is one undo step on the world Document (the host's run_edit()), checked by
the engine's map compiler (core.interactions); below the form, what the build's compiler refuses with the scripts'
names and the rules an earlier one always takes. Generic: nothing here knows what a behavior means."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6 import QtWidgets

from ...core import engine, events, interactions
from ..panel import EditorPanel
from ..panes import split_box
from ..widgets import button, set_enabled

if TYPE_CHECKING:
   from ...core.document import Document
   from ...core.world import Project
   from ..panel import PanelHost

## Errors meaning the engine (its compilers) is missing or too old.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError, KeyError)
## Rule table columns.
COLUMNS = ("Behavior", "Facing", "Mode", "Flag", "Same level", "After actions", "Script")
## The chooser entry of a condition left out.
ANY = "(any)"
## The flag chooser's entry of no flag.
NO_FLAG = "(none)"
## Colours of an error and of warnings under the form.
ERROR_COLOR, WARNING_COLOR = "#c03030", "#b08010"
## Layout stretch of the table column and of the form column.
TABLE_STRETCH, FORM_STRETCH = 3, 2


class InteractionsPanel(EditorPanel):
   """!Edits the world's cell interaction rules."""

   ## See EditorPanel.panel_id.
   panel_id = "interactions"
   ## See EditorPanel.title.
   title = "Interactions"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## True while the panel fills its widgets.
      self._filling = False

      # -- the rules
      note = QtWidgets.QLabel("Facing a cell when no object or sign answers: the first rule that holds runs its "
                              "script. Rules are tried top to bottom.")
      note.setWordWrap(True)
      ## The rules.
      self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
      self.table.setHorizontalHeaderLabels(list(COLUMNS))
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.table.horizontalHeader().setStretchLastSection(True)
      self.table.itemSelectionChanged.connect(lambda: self._rule_picked())
      order = QtWidgets.QHBoxLayout()
      order.addWidget(button("Up", lambda: self.move_rule(-1), "Try the chosen rule earlier"))
      order.addWidget(button("Down", lambda: self.move_rule(1), "Try the chosen rule later"))
      order.addWidget(button("Remove", lambda: self.remove_rule()))
      order.addStretch(1)
      left = QtWidgets.QVBoxLayout()
      left.addWidget(note)
      left.addWidget(self.table, 1)
      left.addLayout(order)

      # -- the form
      ## The faced cell's behavior (the world's behaviors).
      self.behavior = QtWidgets.QComboBox()
      self.behavior.setToolTip("The behavior of the cell the player faces (the World page's Behaviors)")
      ## The script it starts.
      self.script = QtWidgets.QComboBox()
      self.script.setEditable(True)
      self.script.setToolTip("A script of the world's scripts manifest")
      ## The direction the player faces.
      self.facing = QtWidgets.QComboBox()
      ## The movement mode.
      self.vehicle = QtWidgets.QComboBox()
      ## A flag that must be set.
      self.flag = QtWidgets.QComboBox()
      self.flag.setEditable(True)
      self.flag.setToolTip("A flag of the world's scripts manifest that must be set, or none")
      ## The faced level must be the cell's.
      self.same_level = QtWidgets.QCheckBox("the faced cell is on the player's level")
      ## Tried only after the field actions.
      self.after_actions = QtWidgets.QCheckBox("only after the field actions had nothing to do")
      form = QtWidgets.QFormLayout()
      form.addRow("Behavior", self.behavior)
      form.addRow("Script", self.script)
      form.addRow("Facing", self.facing)
      form.addRow("Movement mode", self.vehicle)
      form.addRow("Flag set", self.flag)
      form.addRow("", self.same_level)
      form.addRow("", self.after_actions)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add", lambda: self.add_rule(), "Add the form's rule after the chosen one (or last)"))
      row.addWidget(button("Apply", lambda: self.apply_rule(), "Change the chosen rule to the form's"))
      ## What the build's compiler says.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)
      right = QtWidgets.QVBoxLayout()
      right.addLayout(form)
      right.addLayout(row)
      right.addWidget(self.problems)
      right.addStretch(1)

      lay = QtWidgets.QHBoxLayout(self)
      lay.addLayout(left, TABLE_STRETCH)
      lay.addLayout(right, FORM_STRETCH)
      split_box(lay)   # [RZ] rules | form: the user drags the boundary
      self.refresh()

   # -- host -------------------------------------------------------------------------------------------

   def world(self) -> Document | None:
      """!The world Document.
      @return Document, or None
      """
      p: Project | None = self.host_project()
      return p.world if p is not None else None

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the world file.
      @return Document, or None
      """
      return self.world()

   def _run(self, label: str, fn: Callable[[Document], object]) -> bool:
      """!One change of the world through the host.
      @param label  undo label
      @param fn     callable(world Document)
      @return True when it went through
      """
      doc = self.world()
      if self._filling:
         return False
      if doc is None:
         return self.explain(label)
      ok = self.host.run_edit(label, lambda: fn(doc), doc)
      self.refresh()
      return ok

   # -- refresh ------------------------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the rules, the choices and the compiler's verdict.
      @return None
      """
      doc = self.world()
      set_enabled(self, doc is not None)
      if doc is None:
         return
      self._filling = True
      try:
         self._fill_choices()
         self._fill_table()
      except ENGINE_ERRORS as e:
         self.problems.setText(f"No engine with cell interaction rules (C13b): {e}")
         return
      finally:
         self._filling = False
      self._rule_picked()
      self._show_problems()

   def _fill_choices(self) -> None:
      """!The form's choices: the world's behaviors and movement modes, the scripts' names and flags.
      @return None
      """
      p: Project = self.host_project()
      names = events.names(p)
      for box, items, first in ((self.behavior, interactions.behavior_names(p.world), None),
                                (self.facing, interactions.directions(), ANY),
                                (self.vehicle, interactions.vehicle_names(p.world), ANY),
                                (self.script, list(names.get("scripts", [])), None),
                                (self.flag, list(names.get("flags", [])), NO_FLAG)):
         text = box.currentText()
         box.clear()
         if first is not None:
            box.addItem(first)
         box.addItems(items)
         if text:
            box.setCurrentText(text)

   def _fill_table(self) -> None:
      """!The rule table, keeping the chosen row.
      @return None
      """
      row = self.table.currentRow()
      items = interactions.rules(self.world())
      self.table.setRowCount(len(items))
      for i, r in enumerate(items):
         values = (r.get("behavior"), r.get("facing") or ANY, r.get("vehicle") or ANY, r.get("flag") or NO_FLAG,
                   "yes" if r.get("same_level") else "", "yes" if r.get("after_actions") else "", r.get("script"))
         for c, v in enumerate(values):
            self.table.setItem(i, c, QtWidgets.QTableWidgetItem(str(v)))
      self.table.setVerticalHeaderLabels([str(i) for i in range(len(items))])
      if 0 <= row < len(items):
         self.table.selectRow(row)

   def _show_problems(self) -> None:
      """!What the build's map compiler refuses (with the scripts' names), and rules that never run.
      @return None
      """
      p: Project | None = self.host_project()
      try:
         found = interactions.problems(p) if p is not None else []
      except ENGINE_ERRORS as e:
         found = [f"error: {e}"]
      self.problems.setText("\n".join(found) if found else
                            (f"{len(interactions.rules(p.world))} rule(s); the map compiler takes them." if p else ""))
      bad = any(f.startswith("error") for f in found)
      self.problems.setStyleSheet(f"color: {ERROR_COLOR};" if bad else (f"color: {WARNING_COLOR};" if found else ""))

   def _rule_picked(self) -> None:
      """!A rule row was chosen: the form shows it.
      @return None
      """
      if self._filling is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      i = self.table.currentRow()
      items = interactions.rules(self.world()) if self.world() is not None else []
      if not 0 <= i < len(items):
         return
      r = items[i]
      self.behavior.setCurrentText(str(r.get("behavior", "")))
      self.script.setCurrentText(str(r.get("script", "")))
      self.facing.setCurrentText(str(r.get("facing") or ANY))
      self.vehicle.setCurrentText(str(r.get("vehicle") or ANY))
      self.flag.setCurrentText(str(r.get("flag") or NO_FLAG))
      self.same_level.setChecked(bool(r.get("same_level")))
      self.after_actions.setChecked(bool(r.get("after_actions")))

   # -- edits ----------------------------------------------------------------------------------------------

   def form(self) -> dict[str, Any]:
      """!The form's rule (conditions left as "any" are None).
      @return {behavior, script, facing, vehicle, flag, same_level, after_actions}
      """
      def chosen(box: QtWidgets.QComboBox, none: str) -> str | None:
         """!A chooser's value.
         @param box   the chooser
         @param none  its entry for "any" / "none"
         @return the text, or None
         """
         text = box.currentText().strip()
         return None if not text or text == none else text

      return {"behavior": self.behavior.currentText(), "script": self.script.currentText().strip(),
              "facing": chosen(self.facing, ANY), "vehicle": chosen(self.vehicle, ANY),
              "flag": chosen(self.flag, NO_FLAG), "same_level": self.same_level.isChecked(),
              "after_actions": self.after_actions.isChecked()}

   def add_rule(self) -> bool:
      """!Adds the form's rule after the chosen one (last when none is chosen).
      @return True when added
      """
      f = self.form()
      row = self.table.currentRow()
      at = row + 1 if row >= 0 else None
      done: list[int] = []
      ok = self._run("Add interaction", lambda doc: done.append(interactions.add_rule(
         doc, f.pop("behavior"), f.pop("script"), at, **f)))
      if ok and done:
         self.table.selectRow(done[0])
      return ok

   def apply_rule(self) -> bool:
      """!The chosen rule takes the form's values.
      @return True when changed
      """
      i = self.table.currentRow()
      if i < 0:
         return self.explain("Apply interaction", "interaction rule")
      f = self.form()
      return self._run("Interaction", lambda doc: interactions.set_rule(doc, i, **f))

   def remove_rule(self) -> bool:
      """!Removes the chosen rule.
      @return True when removed
      """
      i = self.table.currentRow()
      if i < 0:
         return self.explain("Remove interaction", "interaction rule")
      return self._run("Remove interaction", lambda doc: interactions.remove_rule(doc, i))

   def move_rule(self, delta: int) -> bool:
      """!Moves the chosen rule earlier (-1) or later (+1).
      @param delta  -1 or +1
      @return True when moved
      """
      i = self.table.currentRow()
      if i < 0:
         return self.explain("Move interaction", "interaction rule")
      to: list[int] = []
      ok = self._run("Move interaction", lambda doc: to.append(interactions.move_rule(doc, i, delta)))
      if ok and to:
         self.table.selectRow(to[0])
      return ok

   def stop(self) -> None:
      """!Nothing pending: edits apply immediately.
      @return None
      """
      pass
