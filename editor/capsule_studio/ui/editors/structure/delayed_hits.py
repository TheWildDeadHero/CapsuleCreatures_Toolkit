"""!The Delayed hits page (engine G1, D-26 section 1): the structure manifest's "delayed_hits", the records effect
logic's `delay_hit WHO TURNS NAME;` names.

The list shows each record with the effect logic naming it; the form edits the selected one: what the landing
takes from the snapshot made when the move was used (the engine's DELAYED_AT_USE: the user's stats, stages,
level, types and the target's defending stat), its flags (typed: the hit has the move's type; crit: it may be
critical), the landing's accuracy (0: no check) and the engine message a miss says. Add / Remove / Rename / Up /
Down edit the list (a rename follows the effect logic; a removal is refused while logic names it); every choice
list is the engine's (core.structure.delayed_hits). The compile result shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core.structure import delayed_hits as hit_model
from ...widgets import button, set_enabled
from ..battle_common import STRUCTURE, BattlePanel, set_check, set_combo, set_spin
from ..record_widgets import NameChecks

if TYPE_CHECKING:
   from ...panel import PanelHost

## What the page says above the list.
NOTE = ("A move's `delay_hit WHO TURNS NAME;` keeps a snapshot of its user at the target's position; when it lands "
        "(the end-of-turn phase delayed), the move's land phase `damage;` works the hit out through the damage "
        "pipeline. The record says what the landing takes from the time of use, whether the hit has a type and "
        "may be critical, and its accuracy check when it lands.")
## Width of the list, pixels.
LIST_WIDTH = 220


class DelayedHitsPanel(BattlePanel):
   """!The delayed hits.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "delayed_hits"
   ## See EditorPanel.title.
   title = "Delayed hits"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the list, the buttons and the form.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected record's name, or None.
      self.selected = None
      ## The records.
      self.list = QtWidgets.QListWidget()
      self.list.setMaximumWidth(LIST_WIDTH)
      self.list.currentTextChanged.connect(lambda text: self._picked(text))
      ## What the landing takes from the time of use.
      self.at_use = NameChecks(lambda names: self._set(lambda doc, n: hit_model.set_at_use(doc, n, names)))
      ## The flags (typed, crit), one box each.
      self.flags = {}
      flag_row = QtWidgets.QHBoxLayout()
      for flag in hit_model.flag_names():
         box = QtWidgets.QCheckBox(flag)
         box.clicked.connect(lambda on, f=flag: self._set(lambda doc, n: hit_model.set_flag(doc, n, f, bool(on))))
         self.flags[flag] = box
         flag_row.addWidget(box)
      flag_row.addStretch(1)
      ## The landing's accuracy (0: no check).
      self.accuracy = QtWidgets.QSpinBox()
      self.accuracy.setRange(0, hit_model.max_accuracy())
      self.accuracy.setSpecialValueText("no check")
      self.accuracy.editingFinished.connect(
         lambda: None if self._filling else self._set(
            lambda doc, n: hit_model.set_accuracy(doc, n, self.accuracy.value())))
      ## The message a miss says.
      self.missed = QtWidgets.QComboBox()
      self.missed.activated.connect(
         lambda _i: self._set(lambda doc, n: hit_model.set_miss_message(doc, n, self.missed.currentText())))
      ## What names the selected record.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      self.used_by.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      form = QtWidgets.QFormLayout()
      form.addRow("Taken on use", self.at_use)
      form.addRow("Flags", flag_row)
      form.addRow("Accuracy when it lands", self.accuracy)
      form.addRow("A miss says", self.missed)
      buttons = QtWidgets.QHBoxLayout()
      buttons.addWidget(button("Add...", lambda: self.add_hit(), "Add a delayed hit after the selected one"))
      buttons.addWidget(button("Remove", lambda: self.remove_hit(), "Remove it (refused while logic names it)"))
      buttons.addWidget(button("Rename...", lambda: self.rename_hit(), "Rename it; effect logic follows"))
      buttons.addWidget(button("Up", lambda: self.move_hit(-1)))
      buttons.addWidget(button("Down", lambda: self.move_hit(1)))
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
      """!The record names in order.
      @return names ([] with nothing open)
      """
      return hit_model.hit_names(self.battle_doc())

   def refresh(self) -> None:
      """!Re-reads the records and shows the selected one.
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
      set_enabled(self, doc is not None)
      self.show_errors()

   def _fill_form(self) -> None:
      """!Shows the selected record in the form.
      @return None
      """
      doc = self.battle_doc()
      rows = {r["name"]: r for r in hit_model.hit_rows(doc)} if doc is not None else {}
      row = rows.get(self.selected)
      on = row is not None
      for w in [self.at_use, self.accuracy, self.missed, *self.flags.values()]:
         set_enabled(w, on)   # the name checks go read-only and keep their scroll bar
      self.at_use.set_names(hit_model.at_use_names(), row["at_use"] if on else [])
      for flag, box in self.flags.items():
         set_check(box, row["flags"][flag] if on else hit_model.flag_default(flag))
      set_spin(self.accuracy, row["accuracy"] if on else 0)
      choices = hit_model.message_choices(doc) if doc is not None else []
      set_combo(self.missed, choices, row["miss_message"] if on else hit_model.default_miss_message())
      self.used_by.setText(f"{self.selected} is used by: {', '.join(row['users']) or 'nothing'}" if on else "")

   def _picked(self, text: str) -> None:
      """!Another record was picked.
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
      """!Changes the selected record.
      @param change  callable(doc, name)
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      if self._filling or doc is None or name is None:
         return False
      return self._edit("Set delayed hit", lambda: change(doc, name))

   def add_hit(self, name: str | None = None) -> bool:
      """!Adds a record after the selected one.
      @param name  the name, or None to ask
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add delayed hit", "Name:")
         if not ok:
            return False
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit("Add delayed hit", lambda: hit_model.add_hit(doc, name, at)):
         self.selected = name.strip()
         return True
      return False

   def remove_hit(self) -> bool:
      """!Removes the selected record.
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self._edit("Remove delayed hit", lambda: hit_model.remove_hit(doc, name)):
         self.selected = None
         return True
      return False

   def rename_hit(self, new: str | None = None) -> bool:
      """!Renames the selected record (effect logic follows, one undo step).
      @param new  the new name, or None to ask
      @return True when renamed
      """
      doc, old = self.battle_doc(), self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename delayed hit", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         return False
      if self._edit("Rename delayed hit", lambda: hit_model.rename_hit(doc, old, new)):
         self.selected = new.strip()
         return True
      return False

   def move_hit(self, delta: int) -> bool:
      """!Moves the selected record up or down.
      @param delta  -1 up, +1 down
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      return self._edit("Move delayed hit", lambda: hit_model.move_hit(doc, name, delta))
