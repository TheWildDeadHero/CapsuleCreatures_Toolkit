"""!The Logic > AI page (engine G1, D-26 section 1): the battle's AI profiles (battle.json "ai_profiles") and the
ai_score effect hook a profile's hook rule runs.

Left: the profiles (Add / Copy / Remove / Rename / Up / Down / Default; a rename follows the parties naming it and
the bench scenarios). Right: the selected profile's scoring, switching and item-use rules (G3: an item-use rule
names an item used in battle, picked below its numbers), each list in the order the
engine runs it: pick a rule and Add it, Remove / Up / Down the selected one, and its numbers (each with the
engine's range and default; "default" puts one back) below the list. The parties using the profile, the ai_score
hook's catalog entry (what it binds, its verdicts; pure: the compiler refuses writes, draws and events in it) and,
for data with the former party AI flags, a Migrate button. Every choice list is the engine's (core.ai). The compile
result shows at the bottom.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ....core import ai as ai_model
from ....core.document import DocumentError
from ...panes import split_box
from ...widgets import button, set_enabled
from ..battle_common import CONTENT, BattlePanel

if TYPE_CHECKING:
   from ...panel import PanelHost

## What the page says above the profiles.
NOTE = ("An AI party names a profile (Content > Parties); a party naming none, a party of records and an unowned "
        "one use the default profile. The scoring rules run in order for every usable move and target (only a "
        "noise rule draws); the switching rules run once the best move is known, the first that says so switching "
        "out. A hook rule runs the effect hook ai_score of the move, the user's owners and the target's. The "
        "item-use rules run last: below_hp uses the item on the AI's own battler below a share of its HP, hook "
        "when the item's own ai_score beats the best move by its margin; the party carries the items "
        "(Content > Parties).")
## Rule table columns.
RULE_COLUMNS = ["#", "Rule", "Numbers"]
## Rule table column of the index.
INDEX_COLUMN = 0
## Rule table column of the rule name.
RULE_COLUMN = 1
## Rule table column of the numbers.
NUMBERS_COLUMN = 2
## Title of each rule list's box.
LIST_TITLES = {ai_model.RULES_KEY: "Scoring rules", ai_model.SWITCHING_KEY: "Switching rules",
               ai_model.ITEMS_KEY: "Item-use rules"}
## Text of a number left at the engine's default.
DEFAULT_MARK = " (default)"


class RuleListBox(QtWidgets.QGroupBox):
   """!One rule list of the selected profile: the table, the rule picker and the selected rule's numbers.

   @var numbers
   The selected rule's numbers: name -> (spin, reset button).
   @var _filling
   True while the box fills its own widgets.
   """

   def __init__(self, panel: AiPanel, which: str) -> None:
      """!Builds the table, the buttons and the number form.
      @param panel  the page
      @param which  ai_model.RULES_KEY or SWITCHING_KEY
      """
      super().__init__(LIST_TITLES[which])
      ## The page.
      self.panel = panel
      ## The list it edits.
      self.which = which
      ## The selected rule's index, or None.
      self.selected = None
      self._filling = False
      ## The rules.
      self.table = QtWidgets.QTableWidget(0, len(RULE_COLUMNS))
      self.table.setHorizontalHeaderLabels(RULE_COLUMNS)
      self.table.verticalHeader().setVisible(False)
      self.table.horizontalHeader().setStretchLastSection(True)
      self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.table.itemSelectionChanged.connect(lambda: self._selection_changed())
      ## The rule Add adds.
      self.choice = QtWidgets.QComboBox()
      self.choice.addItems(ai_model.rule_kinds(which))
      ## The selected rule's numbers: name -> (spin, reset button).
      self.numbers: dict[str, tuple[QtWidgets.QSpinBox, QtWidgets.QPushButton]] = {}
      ## The selected item-use rule's item (an item-use list only), or None.
      self.item = None
      ## Their form.
      self.form = QtWidgets.QFormLayout()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.choice)
      row.addWidget(button("Add", lambda: self.add_rule(), "Add the rule after the selected one"))
      row.addWidget(button("Remove", lambda: self.remove_rule()))
      row.addWidget(button("Up", lambda: self.move_rule(-1), "Runs earlier"))
      row.addWidget(button("Down", lambda: self.move_rule(1), "Runs later"))
      row.addStretch(1)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(self.table, 1)
      lay.addLayout(row)
      lay.addLayout(self.form)

   def rows(self) -> list[ai_model.RuleRow]:
      """!The selected profile's rules of this list.
      @return rule_rows() ([] without a profile)
      """
      doc, name = self.panel.battle_doc(), self.panel.selected
      if doc is None or name is None:
         return []
      try:
         return ai_model.rule_rows(doc, name, self.which)
      except DocumentError:
         return []

   def refresh(self) -> None:
      """!Re-reads the rules and the selected one's numbers.
      @return None
      """
      rows = self.rows()
      if self.selected is not None and self.selected >= len(rows):
         self.selected = len(rows) - 1 if rows else None
      self._filling = True
      try:
         self.table.setRowCount(len(rows))
         for r, row in enumerate(rows):
            numbers = ", ".join(f"{k} {v}" + ("" if k in row["stated"] else DEFAULT_MARK)
                                for k, v in row["args"].items() if v is not None)
            if row["item"] is not None:
               numbers = f"{row['item']}; {numbers}" if numbers else row["item"]
            for c, text in ((INDEX_COLUMN, str(row["index"])), (RULE_COLUMN, row["rule"]),
                            (NUMBERS_COLUMN, numbers)):
               self.table.setItem(r, c, QtWidgets.QTableWidgetItem(text))
         self.table.resizeColumnsToContents()
         if self.selected is not None:
            self.table.selectRow(self.selected)
         self._fill_numbers(rows)
      finally:
         self._filling = False

   def _fill_numbers(self, rows: list[ai_model.RuleRow]) -> None:
      """!Shows the selected rule's numbers as spins (the engine's ranges).
      @param rows  the list's rows
      @return None
      """
      while self.form.rowCount():
         self.form.removeRow(0)
      self.numbers = {}
      self.item = None
      if self.selected is None or self.selected >= len(rows):
         return
      row = rows[self.selected]
      if self.which == ai_model.ITEMS_KEY:
         # the item: one the battle uses in battle (core.ai.item_choices())
         self.item = QtWidgets.QComboBox()
         choices = ai_model.item_choices(self.panel.battle_doc())
         self.item.addItems(choices)
         if row["item"] in choices:
            self.item.setCurrentIndex(choices.index(row["item"]))
         self.item.activated.connect(lambda _i: self.set_item(self.item.currentText()))
         self.form.addRow("item", self.item)
      spec = ai_model.rule_args(self.which, row["rule"])
      for name, (lo, hi, default) in spec.items():
         spin = QtWidgets.QSpinBox()
         spin.setRange(lo, hi)
         value = row["args"].get(name)
         spin.setValue(value if value is not None else (default if default is not None else lo))
         spin.setToolTip(f"{lo} to {hi}" + (f"; the engine's default {default}" if default is not None else
                                            "; none stated: not used"))
         spin.editingFinished.connect(lambda n=name, s=spin: self.set_number(n, s.value()))
         reset = button("default", lambda n=name: self.set_number(n, None), "Back to the engine's default")
         reset.setEnabled(name in row["stated"])
         line = QtWidgets.QHBoxLayout()
         line.addWidget(spin)
         line.addWidget(reset)
         line.addStretch(1)
         self.form.addRow(name, line)
         self.numbers[name] = (spin, reset)

   def _selection_changed(self) -> None:
      """!Another rule was picked.
      @return None
      """
      if self._filling:
         return
      picked = self.table.selectionModel().selectedRows()
      self.selected = picked[0].row() if picked else None
      self._filling = True
      try:
         self._fill_numbers(self.rows())
      finally:
         self._filling = False

   def _change(self, label: str, change: Callable[[Any, str], object]) -> bool:
      """!An edit of the selected profile.
      @param label   undo label
      @param change  callable(doc, profile name)
      @return True when it went through
      """
      doc, name = self.panel.battle_doc(), self.panel.selected
      if self._filling or doc is None or name is None:
         return False
      return self.panel.run(label, lambda: change(doc, name))

   def add_rule(self, rule: str | None = None) -> bool:
      """!Adds a rule after the selected one.
      @param rule  the rule, or None for the picker's
      @return True when added
      """
      rule = rule or self.choice.currentText()
      at = self.selected + 1 if self.selected is not None else None
      ok = self._change("Add AI rule", lambda doc, n: ai_model.add_rule(doc, n, rule, self.which, at))
      if ok:
         self.selected = at if at is not None else len(self.rows()) - 1
      return ok

   def remove_rule(self) -> bool:
      """!Removes the selected rule.
      @return True when removed
      """
      index = self.selected
      if index is None:
         return False
      return self._change("Remove AI rule", lambda doc, n: ai_model.remove_rule(doc, n, index, self.which))

   def move_rule(self, delta: int) -> bool:
      """!Moves the selected rule up or down.
      @param delta  -1 up, +1 down
      @return True when it went through
      """
      index = self.selected
      if index is None:
         return False
      ok = self._change("Move AI rule", lambda doc, n: ai_model.move_rule(doc, n, index, delta, self.which))
      if ok and 0 <= index + delta < len(self.rows()):
         self.selected = index + delta
      return ok

   def set_item(self, item: str) -> bool:
      """!Sets the item the selected item-use rule names.
      @param item  an item used in battle
      @return True when it went through
      """
      index = self.selected
      if index is None or not item:
         return False
      return self._change("Set AI rule item", lambda doc, n: ai_model.set_rule_item(doc, n, index, item))

   def set_number(self, arg: str, value: int | None) -> bool:
      """!Sets one of the selected rule's numbers (None: the engine's default).
      @param arg    the number's name
      @param value  its value, or None
      @return True when it went through
      """
      index = self.selected
      if index is None:
         return False
      return self._change("Set AI rule", lambda doc, n: ai_model.set_rule_arg(doc, n, index, arg, value, self.which))


class AiPanel(BattlePanel):
   """!The AI profiles.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the content manifest (battle.json "ai_profiles", the parties' "ai").
   manifest = CONTENT
   ## See EditorPanel.panel_id.
   panel_id = "ai"
   ## See EditorPanel.title.
   title = "AI"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the profile list, the rule boxes and the hook note.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected profile's name, or None.
      self.selected = None
      ## The profiles.
      self.list = QtWidgets.QListWidget()
      self.list.currentTextChanged.connect(lambda text: self._picked(text))
      ## The rule lists of the selected profile.
      self.boxes = {which: RuleListBox(self, which) for which in ai_model.RULE_LISTS}
      ## The parties using the selected profile.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      self.used_by.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## The ai_score hook's catalog entry.
      self.hook = QtWidgets.QLabel()
      self.hook.setWordWrap(True)
      ## Migrates the former party AI flags (shown while a party gives them).
      self.migrate = button("Migrate AI flags", lambda: self.migrate_flags(),
                            "Turn the parties' former AI flags into profiles (tools/battle_ai.py)")
      buttons = QtWidgets.QVBoxLayout()
      for text, fn, tip in (("Add...", lambda: self.add_profile(), "A new profile (the engine's implicit rules)"),
                            ("Copy...", lambda: self.add_profile(like=self.selected), "A copy of this profile"),
                            ("Remove", lambda: self.remove_profile(), "Refused while a party names it"),
                            ("Rename...", lambda: self.rename_profile(), "Parties and bench scenarios follow"),
                            ("Up", lambda: self.move_profile(-1), ""), ("Down", lambda: self.move_profile(1), ""),
                            ("Default", lambda: self.set_default(), "The profile of parties naming none")):
         buttons.addWidget(button(text, fn, tip))
      buttons.addWidget(self.migrate)
      buttons.addStretch(1)
      left = QtWidgets.QHBoxLayout()
      left.addWidget(self.list)
      left.addLayout(buttons)
      right = QtWidgets.QVBoxLayout()
      for box in self.boxes.values():
         right.addWidget(box, 1)
      right.addWidget(self.used_by)
      split_box(right)   # [RZ] the rule lists, stacked: the user drags the boundaries
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      body = QtWidgets.QHBoxLayout()
      body.addLayout(left)
      body.addLayout(right, 1)
      split_box(body)   # [RZ] profiles | rules: the user drags the boundary
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addLayout(body, 1)
      lay.addWidget(self.hook)
      lay.addWidget(self.errors)

   # -- reading -------------------------------------------------------------------------------------------------------

   def names(self) -> list[str]:
      """!The profile names in order.
      @return names ([] with nothing open)
      """
      return ai_model.profile_names(self.battle_doc())

   def refresh(self) -> None:
      """!Re-reads the profiles, the selected one's rules and users and the hook entry.
      @return None
      """
      doc = self.battle_doc()
      names = self.names()
      chosen = self.selected
      chosen = chosen if chosen in names else (names[0] if names else None)
      self.selected = chosen
      default = ai_model.default_name(doc)
      self._filling = True
      try:
         self.list.clear()
         for name in names:
            self.list.addItem(name + (DEFAULT_MARK if name == default else ""))
         if chosen is not None:
            self.list.setCurrentRow(names.index(chosen))
      finally:
         self._filling = False
      self._fill_selected()
      h = ai_model.hook_entry()
      self.hook.setText(f"Hook {h['name']}: {h['binds']}. Verdicts: {', '.join(sorted(h['results'])) or 'none'}; "
                        f"pure: reads, modify and block only.")
      self.migrate.setVisible(doc is not None and bool(ai_model.flag_parties(doc)))
      set_enabled(self, doc is not None)
      self.show_errors()

   def _fill_selected(self) -> None:
      """!Shows the selected profile's rules and users.
      @return None
      """
      doc = self.battle_doc()
      for box in self.boxes.values():
         box.refresh()
      users = ai_model.users(doc, self.selected) if doc is not None and self.selected is not None else []
      self.used_by.setText(f"{self.selected} is used by: {', '.join(users) or 'no party'}"
                           if self.selected is not None else "")

   def _picked(self, text: str) -> None:
      """!Another profile was picked.
      @param text  its list text (the default one has a mark)
      @return None
      """
      if self._filling or not text:
         return
      self.selected = text[:-len(DEFAULT_MARK)] if text.endswith(DEFAULT_MARK) else text
      for box in self.boxes.values():
         box.selected = None
      self._fill_selected()

   def select(self, name: str) -> None:
      """!Selects a profile.
      @param name  its name
      @return None
      """
      names = self.names()
      if name in names:
         self.list.setCurrentRow(names.index(name))

   # -- editing -------------------------------------------------------------------------------------------------------

   def run(self, label: str, fn: Callable[[], object]) -> bool:
      """!One edit; a refused one refreshes the page back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      ok = self.edit(label, fn)
      if not ok:
         self.host.changed()
      return ok

   def add_profile(self, name: str | None = None, like: str | None = None) -> bool:
      """!Adds a profile after the selected one.
      @param name  the name, or None to ask
      @param like  the profile it copies, or None
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add AI profile", "Name:")
         if not ok:
            return False
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self.run("Add AI profile", lambda: ai_model.add_profile(doc, name, like, at)):
         self.selected = name.strip()
         return True
      return False

   def remove_profile(self) -> bool:
      """!Removes the selected profile.
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self.run("Remove AI profile", lambda: ai_model.remove_profile(doc, name)):
         self.selected = None
         return True
      return False

   def rename_profile(self, new: str | None = None) -> bool:
      """!Renames the selected profile (parties and bench scenarios follow, one undo step).
      @param new  the new name, or None to ask
      @return True when renamed
      """
      doc, old = self.battle_doc(), self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename AI profile", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         return False
      if self.run("Rename AI profile", lambda: ai_model.rename_profile(doc, old, new)):
         self.selected = new.strip()
         return True
      return False

   def move_profile(self, delta: int) -> bool:
      """!Moves the selected profile up or down.
      @param delta  -1 up, +1 down
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      return self.run("Move AI profile", lambda: ai_model.move_profile(doc, name, delta))

   def set_default(self) -> bool:
      """!Makes the selected profile the default one.
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      return self.run("Default AI profile", lambda: ai_model.set_default(doc, name))

   def migrate_flags(self) -> bool:
      """!Turns the parties' former AI flags into profiles.
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      return self.run("Migrate AI flags", lambda: ai_model.migrate_flags(doc))
