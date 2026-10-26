"""!The Field effects page (engine F1, D-27 section 2): the structure manifest's "field_effects", the timed effects
an item's use_field logic, a script or game code starts (`field_effect start NAME N;`) and effect logic reads
(`field.effect_active(NAME)`, `field.effect_remaining(NAME)`).

The list shows each effect; the form edits the selected one: its label (what menus show), its unit (the walker's
steps or the game clock's minutes), its stack rule (what starting it while it runs does), the message shown when it
ends and whether a save keeps it; below it the implicit script variable and expiry script the script compiler
makes for it, and the effect logic naming it. Add / Remove / Rename / Up / Down edit the list (a rename follows the
effect logic; a removal is refused while logic names it); every choice list is the engine's
(core.structure.field_effects). The compile result shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core.structure import field_effects as fx_model
from ...widgets import button
from ..battle_common import STRUCTURE, BattlePanel, set_check, set_combo

if TYPE_CHECKING:
   from ...panel import PanelHost

## What the page says above the list.
NOTE = ("A field effect runs for a number of steps or minutes after an item's use_field logic or a script says "
        "`field_effect start NAME N;`. Effect logic reads it (field.effect_active(NAME), e.g. in an encounter "
        "hook); its message shows when it ends. The script compiler keeps what it has left in a permanent script "
        "variable, so the save image holds it (record the save shapes when the list changes: script save-shapes).")
## Width of the list, pixels.
LIST_WIDTH = 220


class FieldEffectsPanel(BattlePanel):
   """!The timed field effects.

   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "field_effects"
   ## See EditorPanel.title.
   title = "Field effects"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the list, the buttons and the form.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected effect's name, or None.
      self.selected = None
      ## The effects.
      self.list = QtWidgets.QListWidget()
      self.list.setMaximumWidth(LIST_WIDTH)
      self.list.currentTextChanged.connect(lambda text: self._picked(text))
      ## What menus show.
      self.label = QtWidgets.QLineEdit()
      self.label.setMaxLength(fx_model.max_label())
      self.label.editingFinished.connect(
         lambda: None if self._filling else self._set(lambda doc, n: fx_model.set_label(doc, n, self.label.text())))
      ## Steps or minutes.
      self.unit = QtWidgets.QComboBox()
      self.unit.activated.connect(
         lambda _i: self._set(lambda doc, n: fx_model.set_unit(doc, n, self.unit.currentText())))
      ## What starting it while it runs does.
      self.stack = QtWidgets.QComboBox()
      self.stack.activated.connect(
         lambda _i: self._set(lambda doc, n: fx_model.set_stack(doc, n, self.stack.currentText())))
      ## The message shown when it ends (empty: none).
      self.expiry = QtWidgets.QLineEdit()
      self.expiry.setMaxLength(fx_model.max_expiry())
      self.expiry.setPlaceholderText("(no message)")
      self.expiry.editingFinished.connect(
         lambda: None if self._filling else self._set(
            lambda doc, n: fx_model.set_expiry(doc, n, self.expiry.text())))
      ## Whether a save keeps it.
      self.persists = QtWidgets.QCheckBox("Survives a save (off: a loaded save starts without it)")
      self.persists.clicked.connect(lambda on: self._set(lambda doc, n: fx_model.set_persists(doc, n, bool(on))))
      ## The implicit script names.
      self.implicit = QtWidgets.QLabel()
      self.implicit.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## What names the selected effect.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      self.used_by.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      form = QtWidgets.QFormLayout()
      form.addRow("Label", self.label)
      form.addRow("Counts", self.unit)
      form.addRow("Started again", self.stack)
      form.addRow("When it ends", self.expiry)
      form.addRow("", self.persists)
      form.addRow("Script names", self.implicit)
      buttons = QtWidgets.QHBoxLayout()
      buttons.addWidget(button("Add...", lambda: self.add_effect(), "Add a field effect after the selected one"))
      buttons.addWidget(button("Remove", lambda: self.remove_effect(), "Remove it (refused while logic names it)"))
      buttons.addWidget(button("Rename...", lambda: self.rename_effect(), "Rename it; effect logic follows"))
      buttons.addWidget(button("Up", lambda: self.move_effect(-1)))
      buttons.addWidget(button("Down", lambda: self.move_effect(1)))
      buttons.addStretch(1)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      right = QtWidgets.QVBoxLayout()
      right.addLayout(form)
      right.addWidget(self.used_by)
      right.addStretch(1)
      body = QtWidgets.QHBoxLayout()
      body.addWidget(self.list)
      body.addLayout(right, 1)
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
      return fx_model.effect_names(self.battle_doc())

   def refresh(self) -> None:
      """!Re-reads the effects and shows the selected one.
      @return None
      """
      doc = self.battle_doc()
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
      finally:
         self._filling = False
      self.setEnabled(doc is not None)
      self.show_errors()

   def _fill_form(self) -> None:
      """!Shows the selected effect in the form.
      @return None
      """
      doc = self.battle_doc()
      rows = {r["name"]: r for r in fx_model.effect_rows(doc)} if doc is not None else {}
      row = rows.get(self.selected)
      on = row is not None
      for w in (self.label, self.unit, self.stack, self.expiry, self.persists):
         w.setEnabled(on)
      self.label.setText(row["label"] if on else "")
      set_combo(self.unit, fx_model.units(), row["unit"] if on else fx_model.units()[0])
      set_combo(self.stack, fx_model.stacks(), row["stack"] if on else fx_model.default_stack())
      self.expiry.setText(row["expiry"] if on else "")
      set_check(self.persists, row["persists"] if on else fx_model.DEFAULT_PERSISTS)
      self.implicit.setText(f"variable {row['var']}" + (f", expiry script {row['end_script']}"
                                                        if row["end_script"] else "") if on else "")
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
      return self._edit("Set field effect", lambda: change(doc, name))

   def add_effect(self, name: str | None = None) -> bool:
      """!Adds an effect after the selected one.
      @param name  the name, or None to ask
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add field effect", "Name (lower case):")
         if not ok:
            return False
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit("Add field effect", lambda: fx_model.add_effect(doc, name, None, at)):
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
      if self._edit("Remove field effect", lambda: fx_model.remove_effect(doc, name)):
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
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename field effect", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         return False
      if self._edit("Rename field effect", lambda: fx_model.rename_effect(doc, old, new)):
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
      return self._edit("Move field effect", lambda: fx_model.move_effect(doc, name, delta))
