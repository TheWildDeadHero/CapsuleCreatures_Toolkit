"""!The Step effects page (engine F3, D-27 section 4): the structure manifest's "step_effects", the rules that run on
the party every N steps of the walker through the effect-logic hook `on steps` (statuses, passives, held items and
the game's global rules; `field.step_effect == NAME` tells the effects apart).

The list shows each effect; the form edits the selected one: its label, the steps between two runs, the damage rule
(a member the run took to 0 hit points faints, or survives at 1), the battle message queued at each moment (hurt,
survived, fainted; {user} is the member) and the game script run after a run with an outcome (the game's scripts
are the choices); below it the implicit counter variable the script compiler makes for it and the effect logic
naming it. The table under the form lists the logic running `on steps` in the engine's order (global rules, then a
member's status, passive and held item); "Logic..." shows the selected owner on Logic > Effects. Add / Remove /
Rename / Up / Down edit the list (a rename follows the effect logic and the game's scripts reading the counter; a
removal is refused while logic names it); every choice list is the engine's (core.structure.step_effects). The
compile result shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core import logic
from ....core.structure import step_effects as step_model
from ...panes import split_box
from ...widgets import button, set_enabled
from ..battle_common import STRUCTURE, BattlePanel, set_combo, set_spin

if TYPE_CHECKING:
   from ...panel import PanelHost

## What the page says above the list.
NOTE = ("Every N steps of the walker a step effect runs the `on steps` handlers on each party member: the game's "
        "global rules, then the member's status, passive and held item (`field.step_effect == NAME` tells the "
        "effects apart). The logic is the rule: hit points through the member's resource (holder.resource(hp) -= 1), "
        "a role growing, a counter running down. The damage rule decides a member the run took to 0. The counter is "
        "a permanent script variable, so the save image holds it (record the save shapes when the list changes: "
        "script save-shapes).")
## Starting width of the list, pixels.
LIST_WIDTH = 220
## The combo text of "no message" / "no script".
NONE_TEXT = "(none)"
## Columns of the handler table.
HANDLER_COLUMNS = ["Owner", "Source"]


class StepEffectsPanel(BattlePanel):
   """!The step effects.

   @var errors
   Compile result line.
   @var refs
   The owner refs of the handler table's rows.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "step_effects"
   ## See EditorPanel.title.
   title = "Step effects"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the list, the buttons, the form and the handler table.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected effect's name, or None.
      self.selected = None
      ## The owner refs of the handler table's rows.
      self.refs: list[str] = []
      ## The effects.
      self.list = QtWidgets.QListWidget()
      self.list.currentTextChanged.connect(lambda text: self._picked(text))
      ## What menus show.
      self.label = QtWidgets.QLineEdit()
      self.label.setMaxLength(step_model.max_label())
      self.label.editingFinished.connect(
         lambda: None if self._filling else self._set(lambda doc, n: step_model.set_label(doc, n, self.label.text())))
      ## Steps between two runs.
      self.every = QtWidgets.QSpinBox()
      self.every.setRange(1, step_model.max_every())
      self.every.setSuffix(" steps")
      self.every.editingFinished.connect(
         lambda: None if self._filling else self._set(lambda doc, n: step_model.set_every(doc, n, self.every.value())))
      ## The damage rule.
      self.damage = QtWidgets.QComboBox()
      self.damage.activated.connect(
         lambda _i: self._set(lambda doc, n: step_model.set_damage(doc, n, self.damage.currentText())))
      ## The message combo of each moment.
      self.messages: dict[str, QtWidgets.QComboBox] = {}
      for moment in step_model.moments():
         combo = QtWidgets.QComboBox()
         combo.activated.connect(lambda _i, m=moment: self._set_message(m))
         self.messages[moment] = combo
      ## The game script run after a run with an outcome.
      self.script = QtWidgets.QComboBox()
      self.script.activated.connect(lambda _i: self._set_script())
      ## The implicit counter.
      self.implicit = QtWidgets.QLabel()
      self.implicit.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## What names the selected effect.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      self.used_by.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## The logic running on steps.
      self.handlers = QtWidgets.QTableWidget(0, len(HANDLER_COLUMNS))
      self.handlers.setHorizontalHeaderLabels(HANDLER_COLUMNS)
      self.handlers.horizontalHeader().setStretchLastSection(True)
      self.handlers.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.handlers.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.handlers.verticalHeader().setVisible(False)
      form = QtWidgets.QFormLayout()
      form.addRow("Label", self.label)
      form.addRow("Runs every", self.every)
      form.addRow("At 0 hit points", self.damage)
      for moment, combo in self.messages.items():
         form.addRow(f"Message: {moment}", combo)
      form.addRow("Script after a run", self.script)
      form.addRow("Counter", self.implicit)
      buttons = QtWidgets.QHBoxLayout()
      buttons.addWidget(button("Add...", lambda: self.add_effect(), "Add a step effect after the selected one"))
      buttons.addWidget(button("Remove", lambda: self.remove_effect(), "Remove it (refused while logic names it)"))
      buttons.addWidget(button("Rename...", lambda: self.rename_effect(), "Rename it; effect logic follows"))
      buttons.addWidget(button("Up", lambda: self.move_effect(-1)))
      buttons.addWidget(button("Down", lambda: self.move_effect(1)))
      buttons.addWidget(button("Logic...", lambda: self.show_logic(), "Show the selected owner on Logic > Effects"))
      buttons.addStretch(1)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      right = QtWidgets.QVBoxLayout()
      right.addLayout(form)
      right.addWidget(self.used_by)
      right.addWidget(QtWidgets.QLabel("Logic running on steps, in the engine's order"))
      right.addWidget(self.handlers, 1)
      body = QtWidgets.QHBoxLayout()
      body.addWidget(self.list)
      body.addLayout(right, 1)
      split_box(body, [LIST_WIDTH, None])   # [RZ] list | form: the user drags the boundary
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addLayout(body, 1)
      lay.addLayout(buttons)
      lay.addWidget(self.errors)

   # -- reading -------------------------------------------------------------------------------------------------------

   def names(self) -> list[str]:
      """!The effect names in order.
      @return names ([] with nothing open)
      """
      return step_model.effect_names(self.battle_doc())

   def refresh(self) -> None:
      """!Re-reads the effects, shows the selected one and the logic running the hook.
      @return None
      """
      doc, p = self.battle_doc(), self.project()
      names = self.names()
      chosen = self.selected
      chosen = chosen if chosen in names else (names[0] if names else None)
      self.selected = chosen
      self._filling = True
      try:
         self.list.clear()
         self.list.addItems(names)
         if chosen is not None:
            self.list.setCurrentRow(names.index(chosen))
         self._fill_form()
         try:
            uses = step_model.step_handlers(p) if p is not None else []
         except Exception:   # a source being typed that does not parse: the table shows again when it does
            uses = []
         self.refs = [f"{u.kind}{logic.OWNER_SEPARATOR}{u.name}" for u in uses]
         self.handlers.setRowCount(len(uses))
         for i, u in enumerate(uses):
            for j, text in enumerate((f"{u.kind} {u.name}", u.file)):
               self.handlers.setItem(i, j, QtWidgets.QTableWidgetItem(text))
         self.handlers.resizeColumnsToContents()
      finally:
         self._filling = False
      set_enabled(self, doc is not None)
      self.show_errors()

   def _fill_form(self) -> None:
      """!Shows the selected effect in the form.
      @return None
      """
      doc = self.battle_doc()
      rows = {r["name"]: r for r in step_model.effect_rows(doc)} if doc is not None else {}
      row = rows.get(self.selected)
      on = row is not None
      for w in (self.label, self.every, self.damage, self.script, *self.messages.values()):
         w.setEnabled(on)
      self.label.setText(row["label"] if on else "")
      set_spin(self.every, row["every"] if on else step_model.DEFAULT_EVERY)
      set_combo(self.damage, step_model.damage_rules(), row["damage"] if on else step_model.default_damage())
      choices = [NONE_TEXT] + (step_model.message_choices(doc) if doc is not None else [])
      for moment, combo in self.messages.items():
         set_combo(combo, choices, (row["messages"].get(moment) or NONE_TEXT) if on else NONE_TEXT)
      scripts = [NONE_TEXT] + (step_model.script_choices(doc) if doc is not None else [])
      set_combo(self.script, scripts, (row["script"] or NONE_TEXT) if on else NONE_TEXT)
      member, outcome = step_model.implicit_vars()
      self.implicit.setText(f"variable {row['var']} (0 to {max(row['every'], 1) - 1}); the script reads "
                            f"{member} and {outcome}" if on else "")
      self.used_by.setText(f"{self.selected} is used by: {', '.join(row['users']) or 'nothing'}" if on else "")

   def _picked(self, text: str) -> None:
      """!Another effect was picked.
      @param text  its name
      @return None
      """
      if self._filling or not text:
         return
      self.selected = text
      self._filling = True
      try:
         self._fill_form()
      finally:
         self._filling = False

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

   def _set(self, change: object) -> bool:
      """!Changes the selected effect.
      @param change  callable(doc, name)
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      if self._filling or doc is None or name is None:
         return False
      return self._edit("Set step effect", lambda: change(doc, name))

   def _set_message(self, moment: str) -> bool:
      """!The message combo of a moment changed.
      @param moment  the moment
      @return True when it went through
      """
      text = self.messages[moment].currentText()
      key = None if text == NONE_TEXT else text
      return self._set(lambda doc, n: step_model.set_message(doc, n, moment, key))

   def _set_script(self) -> bool:
      """!The script combo changed.
      @return True when it went through
      """
      text = self.script.currentText()
      return self._set(lambda doc, n: step_model.set_script(doc, n, None if text == NONE_TEXT else text))

   def add_effect(self, name: str | None = None) -> bool:
      """!Adds an effect after the selected one.
      @param name  the name, or None to ask
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add step effect", "Name (lower case):")
         if not ok:
            return False
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit("Add step effect", lambda: step_model.add_effect(doc, name, step_model.DEFAULT_EVERY, at)):
         self.selected = name.strip()
         return True
      return False

   def remove_effect(self) -> bool:
      """!Removes the selected effect.
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self._edit("Remove step effect", lambda: step_model.remove_effect(doc, name)):
         self.selected = None
         return True
      return False

   def rename_effect(self, new: str | None = None) -> bool:
      """!Renames the selected effect (effect logic follows, one undo step).
      @param new  the new name, or None to ask
      @return True when renamed
      """
      doc, old = self.battle_doc(), self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename step effect", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         return False
      if self._edit("Rename step effect", lambda: step_model.rename_effect(doc, old, new)):
         self.selected = new.strip()
         return True
      return False

   def move_effect(self, delta: int) -> bool:
      """!Moves the selected effect up or down.
      @param delta  -1 up, +1 down
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      return self._edit("Move step effect", lambda: step_model.move_effect(doc, name, delta))

   def show_logic(self) -> bool:
      """!Shows the selected handler's owner on Logic > Effects.
      @return True when the Effects page shows it
      """
      row = self.handlers.currentRow()
      return self.open_logic(self.refs[row]) if 0 <= row < len(self.refs) else False
