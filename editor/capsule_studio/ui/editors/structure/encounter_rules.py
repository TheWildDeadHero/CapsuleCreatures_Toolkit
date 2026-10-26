"""!The Encounter rules page (engine F1, D-27 section 1): the structure manifest's lead rule and what runs when the
walker meets a creature.

The lead box states who leads (the party member whose passive and held item run the `encounter` /
`encounter_made` hooks and whose level the encounter pipelines see): the first member that can battle, or the first
for which an expression over the member's record holds (Apply / Clear; the engine compiles it, a refused one shows
its message; "Preview with" shows who of one of the battle's parties leads). C8: "Hooks' member when" picks another
member whose passive and held item run the hooks (e.g. "1": the first slot even when fainted); the lead stays the
global rules' holder and the level the pipelines see. Below it: whether the ruleset states
the encounter_rate / encounter_level pipelines (Logic > Pipelines edits them) and the logic running the encounter
hooks in run order (global rules first; "Logic..." shows the selected one on Logic > Effects, "Add global rule..."
writes a new one). core.structure.encounter_rules.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtWidgets

from ....core import battle, logic
from ....core.structure import encounter_rules as rules_model
from ...widgets import button
from ..battle_common import STRUCTURE, BattlePanel, set_combo

if TYPE_CHECKING:
   from ...panel import PanelHost

## What the page says at the top.
NOTE = ("When the walker meets a creature, the global rules run their `on encounter` handlers, then the lead's "
        "passive and held item (before the pick: the rate, the level range, a bias, a skip); after the pick "
        "`on encounter_made` may re-roll or block it. The ruleset's encounter_rate and encounter_level pipelines "
        "turn the result into the odds and the level.")
## Columns of the handler table: owner, hook, file.
HANDLER_COLUMNS = ["Owner", "Hook", "Source"]


class EncounterRulesPanel(BattlePanel):
   """!The lead rule, the encounter pipelines and the logic running the encounter hooks.

   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "encounter_rules"
   ## See EditorPanel.title.
   title = "Encounter rules"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the lead box, the pipeline line and the handler table.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      lead_box = QtWidgets.QGroupBox("Lead")
      lead_lay = QtWidgets.QVBoxLayout(lead_box)
      ## Who leads, in words.
      self.lead_text = QtWidgets.QLabel()
      self.lead_text.setWordWrap(True)
      ## The lead rule's expression (empty: the first member that can battle).
      self.when = QtWidgets.QLineEdit()
      self.when.setPlaceholderText("(none: the first member that can battle leads), e.g. level >= 5")
      self.when.returnPressed.connect(lambda: self.set_lead(self.when.text()))
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Leads when"))
      row.addWidget(self.when, 1)
      row.addWidget(button("Apply", lambda: self.set_lead(self.when.text()), "State the lead rule"))
      row.addWidget(button("Clear", lambda: self.clear_lead(), "The first member that can battle leads"))
      # C8: the hooks' member (its passive and held item run the hooks; the lead stays the global rules' holder)
      ## The hooks' member's rule (empty: the lead runs them).
      self.hook_when = QtWidgets.QLineEdit()
      self.hook_when.setPlaceholderText("(none: the lead's passive and held item run the hooks), e.g. 1 for the "
                                        "first slot even when fainted")
      self.hook_when.returnPressed.connect(lambda: self.set_hook_lead(self.hook_when.text()))
      hook_row = QtWidgets.QHBoxLayout()
      hook_row.addWidget(QtWidgets.QLabel("Hooks' member when"))
      hook_row.addWidget(self.hook_when, 1)
      hook_row.addWidget(button("Apply", lambda: self.set_hook_lead(self.hook_when.text()),
                                "State which member's passive and held item run the encounter hooks"))
      hook_row.addWidget(button("Clear", lambda: self.clear_hook_lead(), "The lead runs them"))
      # F2 (an F1 leftover): who of one of the battle's parties would lead (the engine's Python mirror)
      ## The party previewed.
      self.lead_party = QtWidgets.QComboBox()
      self.lead_party.activated.connect(lambda _i: self._fill_lead_preview())
      ## Who of it leads.
      self.lead_preview = QtWidgets.QLabel()
      self.lead_preview.setWordWrap(True)
      preview_row = QtWidgets.QHBoxLayout()
      preview_row.addWidget(QtWidgets.QLabel("Preview with"))
      preview_row.addWidget(self.lead_party)
      preview_row.addWidget(self.lead_preview, 1)
      lead_lay.addWidget(self.lead_text)
      lead_lay.addLayout(row)
      lead_lay.addLayout(hook_row)
      lead_lay.addLayout(preview_row)
      ## The encounter pipelines: stated by the ruleset or the engine's defaults.
      self.pipelines = QtWidgets.QLabel()
      self.pipelines.setWordWrap(True)
      ## The logic running the encounter hooks.
      self.handlers = QtWidgets.QTableWidget(0, len(HANDLER_COLUMNS))
      self.handlers.setHorizontalHeaderLabels(HANDLER_COLUMNS)
      self.handlers.horizontalHeader().setStretchLastSection(True)
      self.handlers.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.handlers.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.handlers.verticalHeader().setVisible(False)
      ## The rows' owner references ("kind:name").
      self.refs: list[str] = []
      buttons = QtWidgets.QHBoxLayout()
      buttons.addWidget(button("Logic...", lambda: self.show_logic(), "Show the selected owner on Logic > Effects"))
      buttons.addWidget(button("Add global rule...", lambda: self.add_global_rule(),
                               "A game rule with an empty `on encounter` handler (runs before the lead's)"))
      buttons.addStretch(1)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addWidget(lead_box)
      lay.addWidget(self.pipelines)
      lay.addWidget(QtWidgets.QLabel("Logic running the encounter hooks, in run order"))
      lay.addWidget(self.handlers, 1)
      lay.addLayout(buttons)
      lay.addWidget(self.errors)

   def refresh(self) -> None:
      """!Re-reads the lead rule, the pipelines and the handlers.
      @return None
      """
      doc, p = self.battle_doc(), self.project()
      self._filling = True
      try:
         self.lead_text.setText(f"Leads: {rules_model.describe(doc)} (its level and the global rules); passive "
                                f"and held item: {rules_model.describe_hooks(doc)}")
         self.when.setText(rules_model.lead_when(doc) or "")
         self.hook_when.setText(rules_model.hook_lead_when(doc) or "")
         stated = rules_model.encounter_pipelines(p) if p is not None else {}
         self.pipelines.setText("Pipelines: " + ", ".join(f"{name} ({'the ruleset' if on else 'engine default'})"
                                                          for name, on in stated.items()))
         try:
            uses = rules_model.encounter_handlers(p) if p is not None else []
         except Exception:   # a source being typed that does not parse: the table shows again when it does
            uses = []
         self.refs = [f"{u.kind}{logic.OWNER_SEPARATOR}{u.name}" for u in uses]
         self.handlers.setRowCount(len(uses))
         for i, u in enumerate(uses):
            for j, text in enumerate((f"{u.kind} {u.name}", f"on {u.hook}", u.file)):
               self.handlers.setItem(i, j, QtWidgets.QTableWidgetItem(text))
         self.handlers.resizeColumnsToContents()
         parties = rules_model.party_names(p) if p is not None else []
         shown = self.lead_party.currentText()
         set_combo(self.lead_party, parties, shown if shown in parties else (parties[0] if parties else None))
      finally:
         self._filling = False
      self._fill_lead_preview()
      self.setEnabled(doc is not None)
      self.show_errors()

   def _fill_lead_preview(self) -> None:
      """!Shows who of the chosen party leads (its members at full hit points).
      @return None
      """
      p, party = self.project(), self.lead_party.currentText()
      if p is None or not party:
         self.lead_preview.setText("(no parties)")
         return
      try:
         slot = rules_model.lead_preview(p, party)
         hooks = rules_model.lead_preview(p, party, hooks=True)
      except Exception as e:   # the battle data does not compile now: the errors line says why
         self.lead_preview.setText(f"(no preview: {e})")
         return
      members = next((q.get("members") or [] for q in battle.entries(p.battle, "parties") if q.get("name") == party),
                     [])
      text = f"member {slot} ({members[slot].get('species')}) leads" if slot is not None else "nobody leads"
      if hooks != slot:   # C8: another member runs the hooks of its passive and held item
         text += (f"; member {hooks} ({members[hooks].get('species')}) runs the hooks" if hooks is not None
                  else "; nobody runs the hooks")
      self.lead_preview.setText(text)

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

   def set_lead(self, when: str) -> bool:
      """!States the lead rule (empty: clears it).
      @param when  an expression over a party member
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or self._filling:
         return False
      if (rules_model.lead_when(doc) or "") == when.strip():
         return False
      return self._edit("Lead rule", lambda: rules_model.set_lead(doc, when))

   def clear_lead(self) -> bool:
      """!Drops the lead rule.
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or rules_model.lead_when(doc) is None:
         return False
      return self._edit("Clear lead rule", lambda: rules_model.clear_lead(doc))

   def set_hook_lead(self, when: str) -> bool:
      """!States the hooks' member's rule (C8; empty: clears it).
      @param when  an expression over a party member
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or self._filling:
         return False
      if (rules_model.hook_lead_when(doc) or "") == when.strip():
         return False
      return self._edit("Hooks' member rule", lambda: rules_model.set_hook_lead(doc, when))

   def clear_hook_lead(self) -> bool:
      """!Drops the hooks' member's rule (C8: the lead runs them).
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or rules_model.hook_lead_when(doc) is None:
         return False
      return self._edit("Clear hooks' member rule", lambda: rules_model.clear_hook_lead(doc))

   def show_logic(self) -> bool:
      """!Shows the selected owner on Logic > Effects.
      @return True when shown
      """
      row = self.handlers.currentRow()
      return self.open_logic(self.refs[row]) if 0 <= row < len(self.refs) else False

   def add_global_rule(self, name: str | None = None) -> bool:
      """!Adds a global rule.
      @param name  its name, or None to ask
      @return True when added
      """
      p = self.project()
      if p is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add global rule", "Name:")
         if not ok:
            return False
      return self._edit("Add global rule", lambda: rules_model.add_global_rule(p, name))
