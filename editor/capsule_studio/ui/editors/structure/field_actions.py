"""!The Field actions page (engine F2, D-27 section 3): the structure manifest's "field_actions", the moves used
outside battle (cross water, clear a bush, light a dark cave, fly).

The list shows each action; the form edits the selected one: its label, its requirement (an expression over a party
member and the game state: the growth `when` language plus knows.MOVE, passive, flag.NAME and var.NAME; the words
to pick from complete as you type and the engine's checks run on Check / Apply, its message below), what it is used
on (a world behavior faced, an object kind faced, a map tag for a menu action, or none: a menu action anywhere; the
names are the game's world's), whether it asks first and its question, and the script it runs (the game's scripts).
Below: the implicit names the script compiler makes for it and who of one of the battle's parties would use each
action (the engine's Python mirror). Add / Remove / Rename / Up / Down edit the list (a rename follows the game's
scripts). Every choice list is the engine's (core.structure.field_actions).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core.structure import field_actions as fa_model
from ....core.structure import nursery as nursery_model
from ...widgets import button, set_enabled
from ..battle_common import STRUCTURE, BattlePanel, set_check, set_combo

if TYPE_CHECKING:
   from ...panel import PanelHost

## What the page says above the list.
NOTE = ("A field action is a move used outside battle. When the walker faces its target (water, a bush) the first "
        "party member its requirement holds for uses it: it asks first if it asks, then runs its script (the "
        "member's party slot in field_action_member). Menu actions (a map tag, or none) are used from the party "
        "menu. Requirements read the member (level, knows.MOVE, passive == passive.NAME, species.FIELD) and the "
        "game state (flag.NAME, var.NAME: a badge, a story step).")
## Width of the list, pixels.
LIST_WIDTH = 200
## Escaped line break of a one-line prompt editor.
LINE_BREAK = "\\n"
## What the requirement's check says when the engine takes it.
CHECK_OK = "The engine takes it."


class FieldActionsPanel(BattlePanel):
   """!The field actions.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "field_actions"
   ## See EditorPanel.title.
   title = "Field actions"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the list, the buttons, the form and the preview.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected action's name, or None.
      self.selected = None
      ## The actions.
      self.list = QtWidgets.QListWidget()
      self.list.setMaximumWidth(LIST_WIDTH)
      self.list.currentTextChanged.connect(lambda text: self._picked(text))
      ## What menus show.
      self.label = QtWidgets.QLineEdit()
      self.label.setMaxLength(fa_model.max_label())
      self.label.editingFinished.connect(
         lambda: None if self._filling else self._set(lambda doc, n: fa_model.set_label(doc, n, self.label.text())))
      ## The requirement (empty: any member).
      self.requires = QtWidgets.QLineEdit()
      self.requires.setPlaceholderText("(none: any member), e.g. knows.tide_slam && flag.badge_1")
      self.requires.returnPressed.connect(lambda: self.apply_requirement())
      ## Completes the requirement's words (the engine's inputs, the game's flags and variables).
      self.completer = QtWidgets.QCompleter([])
      self.completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
      self.completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
      self.requires.setCompleter(self.completer)
      ## The engine's verdict on the requirement.
      self.check_text = QtWidgets.QLabel()
      self.check_text.setWordWrap(True)
      self.check_text.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      req_row = QtWidgets.QHBoxLayout()
      req_row.addWidget(self.requires, 1)
      req_row.addWidget(button("Check", lambda: self.check_requirement(), "The engine's checks; nothing changes"))
      req_row.addWidget(button("Apply", lambda: self.apply_requirement(), "State the requirement"))
      ## Target kind.
      self.target_kind = QtWidgets.QComboBox()
      self.target_kind.activated.connect(lambda _i: self._target_kind_chosen())
      ## Target name (the game's world's names).
      self.target_name = QtWidgets.QComboBox()
      self.target_name.setEditable(True)
      self.target_name.activated.connect(lambda _i: self.apply_target())
      self.target_name.lineEdit().editingFinished.connect(lambda: self.apply_target())
      target_row = QtWidgets.QHBoxLayout()
      target_row.addWidget(self.target_kind)
      target_row.addWidget(self.target_name, 1)
      ## Asks first.
      self.ask = QtWidgets.QCheckBox("Asks first (yes / no), then runs the script")
      self.ask.clicked.connect(lambda on: self._set(lambda doc, n: fa_model.set_ask(doc, n, bool(on))))
      ## B2: whether an egg may use the action (field_actions[].allow_eggs; refused by default).
      self.allow_eggs = QtWidgets.QCheckBox("Eggs may use it")
      self.allow_eggs.clicked.connect(
         lambda on: self._set(lambda doc, n: nursery_model.set_refusal(doc, "field_actions", n, bool(on))))
      ## The question (\\n breaks a line).
      self.prompt = QtWidgets.QLineEdit()
      self.prompt.setMaxLength(fa_model.max_prompt() + fa_model.max_prompt() // len(LINE_BREAK))
      self.prompt.editingFinished.connect(
         lambda: None if self._filling else self._set(
            lambda doc, n: fa_model.set_prompt(doc, n, self.prompt.text().replace(LINE_BREAK, "\n"))))
      ## The script it runs.
      self.script = QtWidgets.QComboBox()
      self.script.setEditable(True)
      self.script.activated.connect(lambda _i: self.apply_script())
      self.script.lineEdit().editingFinished.connect(lambda: self.apply_script())
      ## The implicit script names.
      self.implicit = QtWidgets.QLabel()
      self.implicit.setWordWrap(True)
      self.implicit.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      form = QtWidgets.QFormLayout()
      form.addRow("Label", self.label)
      form.addRow("Requires", req_row)
      form.addRow("", self.check_text)
      form.addRow("Used on", target_row)
      form.addRow("", self.ask)
      form.addRow("", self.allow_eggs)
      form.addRow("Question", self.prompt)
      form.addRow("Runs", self.script)
      form.addRow("Script names", self.implicit)
      # the preview: one of the battle's parties
      preview_box = QtWidgets.QGroupBox("Who uses each action (one of the battle's parties, no game state)")
      ## The party previewed.
      self.party = QtWidgets.QComboBox()
      self.party.activated.connect(lambda _i: self._fill_preview())
      ## Per action: the member that uses it.
      self.preview_text = QtWidgets.QLabel()
      self.preview_text.setWordWrap(True)
      pv = QtWidgets.QVBoxLayout(preview_box)
      pv.addWidget(self.party)
      pv.addWidget(self.preview_text)
      buttons = QtWidgets.QHBoxLayout()
      buttons.addWidget(button("Add...", lambda: self.add_action(), "Add a field action after the selected one"))
      buttons.addWidget(button("Remove", lambda: self.remove_action(), "Remove it"))
      buttons.addWidget(button("Rename...", lambda: self.rename_action(), "Rename it; the game's scripts follow"))
      buttons.addWidget(button("Up", lambda: self.move_action(-1)))
      buttons.addWidget(button("Down", lambda: self.move_action(1)))
      buttons.addStretch(1)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      right = QtWidgets.QVBoxLayout()
      right.addLayout(form)
      right.addWidget(preview_box)
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
      """!The action names in order.
      @return names ([] with nothing open)
      """
      return fa_model.action_names(self.battle_doc())

   def refresh(self) -> None:
      """!Re-reads the actions and shows the selected one.
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
         if doc is not None:
            self.completer.setModel(QtCore.QStringListModel(fa_model.requirement_words(doc), self.completer))
            p = self.project()
            from ....core.structure import encounter_rules
            parties = encounter_rules.party_names(p) if p is not None else []
            shown = self.party.currentText()
            set_combo(self.party, parties, shown if shown in parties else (parties[0] if parties else None))
         self._fill_form()
      finally:
         self._filling = False
      self._fill_preview()
      set_enabled(self, doc is not None)
      self.show_errors()

   def _fill_form(self) -> None:
      """!Shows the selected action in the form.
      @return None
      """
      doc = self.battle_doc()
      rows = {r["name"]: r for r in fa_model.action_rows(doc)} if doc is not None else {}
      row = rows.get(self.selected)
      on = row is not None
      for w in (self.label, self.requires, self.target_kind, self.target_name, self.ask, self.prompt, self.script,
                self.allow_eggs):
         w.setEnabled(on)
      self.label.setText(row["label"] if on else "")
      self.requires.setText(row["requires"] if on else "")
      self.check_text.setText("")
      kind = row["target"] if on else fa_model.MENU_TARGET
      set_combo(self.target_kind, fa_model.target_kinds(), kind)
      self._fill_target_names(kind, row["target_name"] if on else "")
      set_check(self.ask, row["ask"] if on else fa_model.DEFAULT_ASK)
      set_check(self.allow_eggs, on and nursery_model.allowed(doc, "field_actions", self.selected))
      self.prompt.setText(row["prompt"].replace("\n", LINE_BREAK) if on else "")
      self.prompt.setEnabled(on and row["ask"])
      scripts = fa_model.script_names(doc)["script"] if doc is not None else []
      set_combo(self.script, scripts, row["script"] if on else "")
      if on:
         self.script.setCurrentText(row["script"])
      self.implicit.setText((f"member variable {fa_model.member_var()}" +
                             (f", question script {row['ask_script']}" if row["ask_script"] else "")) if on else "")

   def _fill_target_names(self, kind: str, current: str) -> None:
      """!Fills the target name chooser for a kind.
      @param kind     a target kind
      @param current  the name shown
      @return None
      """
      doc = self.battle_doc()
      names = fa_model.target_choices(doc, kind) if doc is not None else []
      set_combo(self.target_name, names, current)
      self.target_name.setCurrentText(current)
      self.target_name.setEnabled(kind != fa_model.MENU_TARGET and self.selected is not None)

   def _fill_preview(self) -> None:
      """!Shows who of the chosen party uses each action.
      @return None
      """
      p = self.project()
      party = self.party.currentText()
      if p is None or not party:
         self.preview_text.setText("(no parties)")
         return
      try:
         records = fa_model.party_records(p, party)
         got = fa_model.preview(p, records)
      except Exception as e:   # the battle data does not compile now: the errors line says why
         self.preview_text.setText(f"(no preview: {e})")
         return
      self.preview_text.setText("\n".join(
         f"{name}: " + (f"member {slot} ({records[slot]['species']})" if slot is not None else "nobody")
         for name, slot in got.items()) or "(no field actions)")

   def _picked(self, text: str) -> None:
      """!Another action was picked.
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
      """!Changes the selected action.
      @param change  callable(doc, name)
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      if self._filling or doc is None or name is None:
         return False
      return self._edit("Set field action", lambda: change(doc, name))

   def check_requirement(self, text: str | None = None) -> str | None:
      """!Runs the engine's checks on the requirement being typed (nothing changes).
      @param text  the expression, or None for the editor's
      @return the engine's message, or None when it takes it
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return None
      error = fa_model.check_requirement(doc, name, self.requires.text() if text is None else text)
      self.check_text.setText(error or CHECK_OK)
      return error

   def apply_requirement(self, text: str | None = None) -> bool:
      """!States the requirement (refused with the engine's message, shown below it).
      @param text  the expression, or None for the editor's
      @return True when it went through
      """
      text = self.requires.text() if text is None else text
      if self.check_requirement(text) is not None:
         return False
      return self._set(lambda doc, n: fa_model.set_requires(doc, n, text))

   def _target_kind_chosen(self) -> None:
      """!A target kind was picked: a menu action applies at once, the others wait for a name.
      @return None
      """
      kind = self.target_kind.currentText()
      self._fill_target_names(kind, "")
      if kind == fa_model.MENU_TARGET:
         self._set(lambda doc, n: fa_model.set_target(doc, n, kind))
      elif self.target_name.count():
         self.target_name.setCurrentIndex(0)
         self.apply_target()

   def apply_target(self) -> bool:
      """!States the target from the choosers.
      @return True when it went through
      """
      kind, name = self.target_kind.currentText(), self.target_name.currentText().strip()
      if self._filling or (kind != fa_model.MENU_TARGET and not name):
         return False
      doc = self.battle_doc()
      row = next((r for r in fa_model.action_rows(doc) if r["name"] == self.selected), None) if doc else None
      if row is not None and (row["target"], row["target_name"]) == (kind, name):
         return False
      return self._set(lambda d, n: fa_model.set_target(d, n, kind, name or None))

   def apply_script(self) -> bool:
      """!States the script from the chooser.
      @return True when it went through
      """
      script = self.script.currentText().strip()
      doc = self.battle_doc()
      row = next((r for r in fa_model.action_rows(doc) if r["name"] == self.selected), None) if doc else None
      if self._filling or not script or (row is not None and row["script"] == script):
         return False
      return self._set(lambda d, n: fa_model.set_script(d, n, script))

   def add_action(self, name: str | None = None, script: str | None = None) -> bool:
      """!Adds an action after the selected one (a menu action anywhere until its target is chosen).
      @param name    the name, or None to ask
      @param script  the script, or None to ask
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add field action", "Name (lower case):")
         if not ok:
            return False
      if script is None:
         scripts = fa_model.script_names(doc)["script"]
         script, ok = QtWidgets.QInputDialog.getItem(self, "Add field action", "Script it runs:", scripts, 0, True)
         if not ok:
            return False
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self._edit("Add field action", lambda: fa_model.add_action(doc, name, script, fa_model.MENU_TARGET, None,
                                                                    at)):
         self.selected = name.strip()
         return True
      return False

   def remove_action(self) -> bool:
      """!Removes the selected action.
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      if self._edit("Remove field action", lambda: fa_model.remove_action(doc, name)):
         self.selected = None
         return True
      return False

   def rename_action(self, new: str | None = None) -> bool:
      """!Renames the selected action (the game's scripts follow, one undo step).
      @param new  the new name, or None to ask
      @return True when renamed
      """
      doc, old = self.battle_doc(), self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename field action", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         return False
      if self._edit("Rename field action", lambda: fa_model.rename_action(doc, old, new)):
         self.selected = new.strip()
         return True
      return False

   def move_action(self, delta: int) -> bool:
      """!Moves the selected action up or down.
      @param delta  -1 up, +1 down
      @return True when it went through
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      return self._edit("Move field action", lambda: fa_model.move_action(doc, name, delta))
