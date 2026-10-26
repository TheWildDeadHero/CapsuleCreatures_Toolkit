"""!The Nursery page (engine B2, D-28 sections 2 and 3): the structure manifest's "eggs" and "nursery", and the
egg refusal flags of every system that uses records.

The Eggs box turns eggs on or off and edits the section: the egg role and the hatch counter role (custom roles of one
element), the species field of the hatch cycles, the step effect whose runs are the egg cycles, the hatch script
(the game's scripts; it reads the implicit variable egg_member), what an egg is called, its default sprite and the
species field giving each species' egg look. Below the form: the methods delivering eggs with their steps a cycle
and the largest counter. The Nursery box turns the nursery on or off and edits it: the combination method of kind
nursery it runs, the step effect of its checks, its slots, the odds scale, whether the held records gain experience
per step (the ruleset pipeline nursery_gain) and whether taking one back costs (nursery_fee; the line under it shows
the fee of a few levels). The table lists each system that refuses eggs unless its flag allows them (battle setup,
recruitment, every field action, item and combination method); a click on the check sets the flag. Every choice is
the engine's or the structure's (core.structure.nursery); renames of what the sections name follow into them on
their own pages, and removals are refused while they name it. The compile result shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core.structure import nursery as nursery_model
from ..battle_common import NONE_TEXT, STRUCTURE, BattlePanel, set_check, set_combo, set_spin

if TYPE_CHECKING:
   from ...panel import PanelHost

## What the page says above the boxes.
NOTE = ("An egg is an ordinary record with its egg role set and a hatch counter role holding the steps left; a method "
        "delivering eggs seeds the counter with the species' hatch cycles times its steps a cycle. Each run of the "
        "egg step effect takes its steps off every egg in the party (the `hatch` hook may change that) and an egg at "
        "0 hatches, running the hatch script. The nursery holds records its method (kind nursery) checks on each run "
        "of the check step effect. Every system that uses records refuses eggs unless its flag below allows them.")
## The egg keys holding a name chosen from a list, with their row labels.
EGG_COMBOS = {"role": "Egg role", "counter": "Hatch counter", "cycles_field": "Hatch cycles field",
              "step_effect": "Egg cycle (step effect)", "hatch_script": "Hatch script",
              "sprite_field": "Egg look field"}
## The egg combos that may name nothing.
OPTIONAL_COMBOS = ("hatch_script", "sprite_field")
## Columns of the refusal table.
REFUSAL_COLUMNS = ["System", "Entry", "Takes eggs"]
## Column of the refusal table's check.
CHECK_COLUMN = 2
## The refusal table's system words, back to their manifest keys.
SYSTEM_KEYS = {**{v: k for k, v in nursery_model.SECTION_SYSTEMS.items()},
               **{v: k for k, v in nursery_model.LIST_SYSTEMS.items()}}
## Levels gained the fee line shows.
FEE_LEVELS = (1, 5, 10)
## Largest odds scale the spin offers (the engine's u16).
MAX_SCALE = 0xFFFF


class NurseryPanel(BattlePanel):
   """!Eggs and the nursery.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "nursery"
   ## See EditorPanel.title.
   title = "Nursery"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the Eggs box, the Nursery box and the refusal table.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      # -- eggs
      ## Whether the structure states eggs.
      self.has_eggs = QtWidgets.QCheckBox("The game has eggs")
      self.has_eggs.clicked.connect(lambda on: self.set_eggs_on(bool(on)))
      ## The egg section's name combos by key.
      self.egg_combos: dict[str, QtWidgets.QComboBox] = {}
      for key in EGG_COMBOS:
         box = QtWidgets.QComboBox()
         box.activated.connect(lambda _i, k=key: self._set_egg_combo(k))
         self.egg_combos[key] = box
      ## What an egg is called.
      self.egg_name = QtWidgets.QLineEdit()
      self.egg_name.setMaxLength(nursery_model.max_name_chars())
      self.egg_name.editingFinished.connect(
         lambda: None if self._filling else self.set_egg(nursery_model.NAME_KEY, self.egg_name.text()))
      ## The default egg sprite ("sprite:NAME").
      self.egg_sprite = QtWidgets.QLineEdit()
      self.egg_sprite.setPlaceholderText("sprite:NAME (none: the game draws eggs)")
      self.egg_sprite.editingFinished.connect(
         lambda: None if self._filling else self.set_egg(nursery_model.SPRITE_KEY, self.egg_sprite.text()))
      ## The egg methods and the counter's range.
      self.egg_info = QtWidgets.QLabel()
      self.egg_info.setWordWrap(True)
      self.egg_info.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      egg_box = QtWidgets.QGroupBox("Eggs")
      egg_form = QtWidgets.QFormLayout(egg_box)
      egg_form.addRow(self.has_eggs)
      for key, label in EGG_COMBOS.items():
         egg_form.addRow(label, self.egg_combos[key])
      egg_form.addRow("Egg name", self.egg_name)
      egg_form.addRow("Egg sprite", self.egg_sprite)
      egg_form.addRow(self.egg_info)
      # -- nursery
      ## Whether the structure states a nursery.
      self.has_nursery = QtWidgets.QCheckBox("The game has a nursery")
      self.has_nursery.clicked.connect(lambda on: self.set_nursery_on(bool(on)))
      ## The method it runs.
      self.method = QtWidgets.QComboBox()
      self.method.activated.connect(lambda _i: self.set_nursery(nursery_model.METHOD_KEY, self.method.currentText()))
      ## The step effect of its checks.
      self.check = QtWidgets.QComboBox()
      self.check.activated.connect(lambda _i: self.set_nursery(nursery_model.CHECK_KEY, self.check.currentText()))
      ## Its slots.
      self.slots = QtWidgets.QSpinBox()
      self.slots.setRange(1, nursery_model.max_slots())
      self.slots.editingFinished.connect(
         lambda: None if self._filling else self.set_nursery(nursery_model.SLOTS_KEY, self.slots.value()))
      ## The odds' scale.
      self.scale = QtWidgets.QSpinBox()
      self.scale.setRange(1, MAX_SCALE)
      self.scale.editingFinished.connect(
         lambda: None if self._filling else self.set_nursery(nursery_model.SCALE_KEY, self.scale.value()))
      ## Experience per step.
      self.gain = QtWidgets.QCheckBox("Held records gain experience per step (nursery_gain)")
      self.gain.clicked.connect(lambda on: self.set_nursery(nursery_model.GAIN_KEY, bool(on)))
      ## A fee to take one back.
      self.fee = QtWidgets.QCheckBox("Taking a record back costs (nursery_fee)")
      self.fee.clicked.connect(lambda on: self.set_nursery(nursery_model.FEE_KEY, bool(on)))
      ## The fee of a few levels.
      self.fee_info = QtWidgets.QLabel()
      self.fee_info.setWordWrap(True)
      nursery_box = QtWidgets.QGroupBox("Nursery")
      n_form = QtWidgets.QFormLayout(nursery_box)
      n_form.addRow(self.has_nursery)
      n_form.addRow("Method (kind nursery)", self.method)
      n_form.addRow("Check (step effect)", self.check)
      n_form.addRow("Slots", self.slots)
      n_form.addRow("Odds out of", self.scale)
      n_form.addRow(self.gain)
      n_form.addRow(self.fee)
      n_form.addRow(self.fee_info)
      # -- refusals
      ## The systems' flags.
      self.refusals = QtWidgets.QTableWidget(0, len(REFUSAL_COLUMNS))
      self.refusals.setHorizontalHeaderLabels(REFUSAL_COLUMNS)
      self.refusals.horizontalHeader().setStretchLastSection(True)
      self.refusals.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.refusals.verticalHeader().setVisible(False)
      self.refusals.itemChanged.connect(lambda item: self._refusal_clicked(item))
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      left = QtWidgets.QVBoxLayout()
      left.addWidget(egg_box)
      left.addWidget(nursery_box)
      left.addStretch(1)
      ## C9: what a build without an egg role does with a transferred egg (refuse, or receive it hatched).
      self.transfer = QtWidgets.QComboBox()
      self.transfer.activated.connect(lambda _i: self.set_transfer(self.transfer.currentText()))
      transfer_row = QtWidgets.QFormLayout()
      transfer_row.addRow("Transferred eggs (no egg role)", self.transfer)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(QtWidgets.QLabel("Egg refusals: a system takes eggs only when its flag says so"))
      right.addWidget(self.refusals, 1)
      right.addLayout(transfer_row)
      body = QtWidgets.QHBoxLayout()
      body.addLayout(left, 1)
      body.addLayout(right, 1)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addLayout(body, 1)
      lay.addWidget(self.errors)

   # -- reading -------------------------------------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads both sections and the flags.
      @return None
      """
      doc = self.battle_doc()
      self._filling = True
      try:
         self._fill_eggs(doc)
         self._fill_nursery(doc)
         self._fill_refusals(doc)
         set_combo(self.transfer, nursery_model.transfer_choices(),
                   nursery_model.transfer_eggs(doc) if doc is not None else nursery_model.transfer_choices()[0])
      finally:
         self._filling = False
      self.setEnabled(doc is not None)
      self.show_errors()

   def _fill_eggs(self, doc: object) -> None:
      """!Shows the egg section.
      @param doc  the battle Document, or None
      @return None
      """
      row = nursery_model.egg_row(doc) if doc is not None else None
      on = row is not None
      set_check(self.has_eggs, on)
      for w in (*self.egg_combos.values(), self.egg_name, self.egg_sprite):
         w.setEnabled(on)
      lists = {"role": nursery_model.role_choices, "counter": nursery_model.role_choices,
               "cycles_field": nursery_model.field_choices, "sprite_field": nursery_model.field_choices,
               "step_effect": nursery_model.step_choices, "hatch_script": nursery_model.script_choices}
      for key, box in self.egg_combos.items():
         names = lists[key](doc) if doc is not None else []
         if key in OPTIONAL_COMBOS:
            names = [NONE_TEXT] + names
         current = (row[key] or (NONE_TEXT if key in OPTIONAL_COMBOS else None)) if on else None
         set_combo(box, names, current)
      self.egg_name.setText(row[nursery_model.NAME_KEY] if on else "")
      self.egg_sprite.setText(row[nursery_model.SPRITE_KEY] if on else "")
      if not on:
         self.egg_info.setText("No eggs: no method may deliver eggs.")
         return
      methods = nursery_model.egg_methods(doc)
      self.egg_info.setText(
         "Methods delivering eggs: " + (", ".join(f"{m} ({s} steps a cycle)" for m, s in methods) or "none") +
         f". The counter holds up to {nursery_model.counter_max(doc)} steps; the hatch script reads "
         f"{nursery_model.member_var()} (the egg's party slot).")

   def _fill_nursery(self, doc: object) -> None:
      """!Shows the nursery and its fee line.
      @param doc  the battle Document, or None
      @return None
      """
      row = nursery_model.nursery_row(doc) if doc is not None else None
      on = row is not None
      set_check(self.has_nursery, on)
      for w in (self.method, self.check, self.slots, self.scale, self.gain, self.fee):
         w.setEnabled(on)
      set_combo(self.method, nursery_model.method_choices(doc) if doc is not None else [],
                row[nursery_model.METHOD_KEY] if on else None)
      set_combo(self.check, nursery_model.step_choices(doc) if doc is not None else [],
                row[nursery_model.CHECK_KEY] if on else None)
      set_spin(self.slots, row[nursery_model.SLOTS_KEY] if on else 1)
      set_spin(self.scale, row[nursery_model.SCALE_KEY] if on else nursery_model.default_odds_scale())
      set_check(self.gain, on and row[nursery_model.GAIN_KEY])
      set_check(self.fee, on and row[nursery_model.FEE_KEY])
      if not on or not row[nursery_model.FEE_KEY]:
         self.fee_info.setText("" if not on else "Taking a record back is free.")
         return
      count = max(1, row[nursery_model.SLOTS_KEY] if isinstance(row[nursery_model.SLOTS_KEY], int) else 1)
      fees = [(n, nursery_model.fee_table(doc, n, n + 1, count)) for n in FEE_LEVELS]
      self.fee_info.setText("Fee: " + ", ".join(f"{n} levels gained: {'?' if f is None else f}" for n, f in fees))

   def _fill_refusals(self, doc: object) -> None:
      """!Shows the systems' flags.
      @param doc  the battle Document, or None
      @return None
      """
      rows = nursery_model.refusal_rows(doc) if doc is not None else []
      self.refusals.blockSignals(True)
      self.refusals.setRowCount(len(rows))
      for i, (what, name, on) in enumerate(rows):
         self.refusals.setItem(i, 0, QtWidgets.QTableWidgetItem(what))
         self.refusals.setItem(i, 1, QtWidgets.QTableWidgetItem(name))
         check = QtWidgets.QTableWidgetItem("")
         check.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
         check.setCheckState(QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)
         self.refusals.setItem(i, CHECK_COLUMN, check)
      self.refusals.resizeColumnsToContents()
      self.refusals.blockSignals(False)

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

   def set_eggs_on(self, on: bool) -> bool:
      """!Writes or removes the egg section (new: names suggesting the roles, field and step effect).
      @param on  True: the game has eggs
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or self._filling:
         return False
      if on:
         return self._edit("Eggs", lambda: nursery_model.enable_eggs(doc, *nursery_model.egg_defaults(doc)))
      return self._edit("No eggs", lambda: nursery_model.disable_eggs(doc))

   def set_egg(self, key: str, value: str | None) -> bool:
      """!Sets one key of the egg section.
      @param key    one of nursery_model.EGG_KEYS
      @param value  the value (None or empty: left out)
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or nursery_model.eggs(doc) is None:
         return False
      row = nursery_model.egg_row(doc)
      if row is not None and (row[key] or None) == (value or None):
         return False
      return self._edit(f"Eggs {key}", lambda: nursery_model.set_egg(doc, key, value))

   def _set_egg_combo(self, key: str) -> bool:
      """!An egg combo changed.
      @param key  its key
      @return True when it went through
      """
      text = self.egg_combos[key].currentText()
      return self.set_egg(key, None if text == NONE_TEXT else text)

   def set_nursery_on(self, on: bool) -> bool:
      """!Writes or removes the nursery.
      @param on  True: the game has a nursery
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or self._filling:
         return False
      if on:
         return self._edit("Nursery", lambda: nursery_model.enable_nursery(doc, *nursery_model.nursery_defaults(doc)))
      return self._edit("No nursery", lambda: nursery_model.disable_nursery(doc))

   def set_nursery(self, key: str, value: object) -> bool:
      """!Sets one key of the nursery.
      @param key    one of nursery_model.NURSERY_KEYS
      @param value  the value
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or self._filling or nursery_model.nursery(doc) is None:
         return False
      row = nursery_model.nursery_row(doc)
      if row is not None and row[key] == value:
         return False
      return self._edit(f"Nursery {key}", lambda: nursery_model.set_nursery(doc, key, value))

   def set_transfer(self, rule: str) -> bool:
      """!Sets the transfer rule for eggs (C9).
      @param rule  one of nursery_model.transfer_choices()
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or self._filling or nursery_model.transfer_eggs(doc) == rule:
         return False
      return self._edit("Egg transfer rule", lambda: nursery_model.set_transfer_eggs(doc, rule))

   def set_refusal(self, row: int, on: bool) -> bool:
      """!Sets one system's flag.
      @param row  the table row
      @param on   True: it takes eggs
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      what = self.refusals.item(row, 0).text()
      name = self.refusals.item(row, 1).text()
      return self._edit("Egg refusal", lambda: nursery_model.set_refusal(doc, SYSTEM_KEYS[what], name, on))

   def _refusal_clicked(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A check of the table changed.
      @param item  the cell
      @return None
      """
      if self._filling or item.column() != CHECK_COLUMN:
         return
      self.set_refusal(item.row(), item.checkState() == QtCore.Qt.CheckState.Checked)
