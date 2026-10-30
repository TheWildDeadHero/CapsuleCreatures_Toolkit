"""!The Recruit page (D-26 section 3, engine G3): the structure manifest's
"recruit" section, the ruleset's recruit_odds and an odds preview.

Top: Enable / Disable (a section needs the ruleset's own recruit_odds: Add
pipeline writes a neutral one), then the rules: the checks, the species
field read as the recruit rate, whether an owned battler may be recruited,
the record role storing the item used, the battle changes the record keeps,
the status bonuses (a table: the "none" row is the bonus without a status
and of every status left at its default), a message per moment and the
"broke free" messages by the checks passed. Every choice list is the
engine's or the manifests' (core.structure.recruit). The preview runs
recruit_odds as the engine does for a species, an HP share, an item that
recruits (its bonus) and a status, and shows the odds of one check and of
all of them. The items that recruit are listed (Content > Items: Recruit).
Every change is one undo step; the compile result shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ....core import battle
from ....core.document import DocumentError
from ....core.structure import nursery as nursery_model
from ....core.structure import recruit as recruit_model
from ...widgets import button, set_enabled
from ..battle_common import STRUCTURE, BattlePanel, combo, set_check, set_combo, set_spin, spin

if TYPE_CHECKING:
   from ...panel import PanelHost

## A combo's entry for nothing (no rate field, no item role, no message).
NONE_CHOICE = "(none)"
## Status bonus table columns.
BONUS_COLUMNS = ["Status", "Bonus"]
## Column of the status.
STATUS_COLUMN = 0
## Column of the bonus (typing sets it; empty: the default).
BONUS_COLUMN = 1
## The preview's HP share spin's top (percent).
PERCENT = 100
## The preview's HP share at start (percent).
PREVIEW_HP = 50
## The preview's levels at start.
PREVIEW_LEVEL = 10
## Separator of the "broke free" list's text.
LIST_SEPARATOR = ","
## What the page says at the top.
NOTE = ("An item recruits with `recruit holder BONUS;` in its use_battle logic (Content > Items: Recruit). The "
        "engine then makes the checks, each a draw against the ruleset's recruit_odds; every check passed and the "
        "creature joins the party, else the storage boxes (Structure > Storage), and the battle ends.")


class RecruitPanel(BattlePanel):
   """!The recruit rules and the odds preview.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   ## See EditorPanel.panel_id.
   panel_id = "recruit"
   ## See EditorPanel.title.
   title = "Recruit"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the switch row, the rules form, the bonus table, the messages and the preview.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Whether the section is stated, and the ruleset's pipeline.
      self.state = QtWidgets.QLabel()
      self.state.setWordWrap(True)
      ## Enables the section.
      self.enable_button = button("Enable", lambda: self.enable(), "Give the structure a recruit section")
      ## Disables it.
      self.disable_button = button("Disable", lambda: self.disable(), "Take the recruit section out")
      ## Writes the neutral recruit_odds.
      self.pipeline_button = button("Add pipeline", lambda: self.add_pipeline(),
                                    "Write a neutral recruit_odds into the ruleset (rate + bonus + status, percent)")
      ## Checks a recruit makes.
      self.checks = spin(1, recruit_model.max_checks(), lambda v: self.set_field(recruit_model.CHECKS_KEY, v))
      ## The species field read as the recruit rate.
      self.rate = combo(lambda text: self.set_field(recruit_model.RATE_KEY, None if text == NONE_CHOICE else text))
      ## Owned battlers.
      self.owned = combo(lambda text: self.set_field(recruit_model.OWNED_KEY, text))
      ## The record role storing the item used.
      self.item_role = combo(lambda text: self.set_field(recruit_model.ITEM_ROLE_KEY,
                                                         None if text == NONE_CHOICE else text))
      ## What a recruited record keeps: name -> box.
      self.keep = {}
      keep_row = QtWidgets.QHBoxLayout()
      for k in recruit_model.keeps():
         box = QtWidgets.QCheckBox(k)
         box.clicked.connect(lambda _on: self.set_keep())
         self.keep[k] = box
         keep_row.addWidget(box)
      keep_row.addStretch(1)
      ## The refusals that still use the item up (C6): name -> box.
      self.consumes = {}
      consumes_row = QtWidgets.QHBoxLayout()
      for k in recruit_model.refusals():
         box = QtWidgets.QCheckBox(k)
         box.clicked.connect(lambda _on: self.set_refusal_consumes())
         self.consumes[k] = box
         consumes_row.addWidget(box)
      consumes_row.addStretch(1)
      ## The status bonuses.
      self.bonus = QtWidgets.QTableWidget(0, len(BONUS_COLUMNS))
      self.bonus.setHorizontalHeaderLabels(BONUS_COLUMNS)
      self.bonus.verticalHeader().setVisible(False)
      self.bonus.horizontalHeader().setStretchLastSection(True)
      self.bonus.itemChanged.connect(lambda item: self._bonus_changed(item))
      ## The message of each moment.
      self.messages = {}
      msg_form = QtWidgets.QFormLayout()
      for m in recruit_model.moments():
         c = combo(lambda text, moment=m: self.set_message(moment, None if text == NONE_CHOICE else text))
         self.messages[m] = c
         msg_form.addRow(m, c)
      ## The "broke free" messages, comma separated.
      self.break_free = QtWidgets.QLineEdit()
      self.break_free.setToolTip("Message keys by the checks passed (the last one for more), comma separated")
      self.break_free.editingFinished.connect(lambda: self.set_break_free(self.break_free.text()))
      msg_form.addRow("broke free", self.break_free)
      rules = QtWidgets.QGroupBox("Rules")
      form = QtWidgets.QFormLayout(rules)
      form.addRow("Checks", self.checks)
      form.addRow("Recruit rate", self.rate)
      form.addRow("Owned battlers", self.owned)
      form.addRow("Item role", self.item_role)
      form.addRow("Keeps", keep_row)
      form.addRow("Refusals use the item up", consumes_row)
      ## B2: whether an egg may be recruited (recruit.allow_eggs; refused by default).
      self.allow_eggs = QtWidgets.QCheckBox("Eggs may be recruited")
      self.allow_eggs.clicked.connect(lambda on: self.set_allow_eggs(bool(on)))
      form.addRow("Eggs", self.allow_eggs)
      bonus_box = QtWidgets.QGroupBox("Status bonuses")
      QtWidgets.QVBoxLayout(bonus_box).addWidget(self.bonus)
      msg_box = QtWidgets.QGroupBox("Messages")
      msg_box.setLayout(msg_form)
      # the preview
      ## Species of the preview.
      self.species = combo(lambda _t: self.update_preview())
      ## HP share of the preview, percent.
      self.hp = spin(1, PERCENT, lambda _v: self.update_preview())
      self.hp.setSuffix(" % HP")
      ## Item of the preview (one that recruits).
      self.item = combo(lambda _t: self.update_preview())
      ## Status of the preview.
      self.status = combo(lambda _t: self.update_preview())
      ## Levels of the preview.
      self.level = spin(1, PERCENT, lambda _v: self.update_preview())
      ## The odds.
      self.odds = QtWidgets.QLabel()
      self.odds.setWordWrap(True)
      self.odds.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      preview = QtWidgets.QGroupBox("Odds preview (recruit_odds)")
      pf = QtWidgets.QFormLayout(preview)
      pf.addRow("Species", self.species)
      pf.addRow("HP", self.hp)
      pf.addRow("Item", self.item)
      pf.addRow("Status", self.status)
      pf.addRow("Levels", self.level)
      pf.addRow(self.odds)
      ## The items whose logic recruits.
      self.items = QtWidgets.QLabel()
      self.items.setWordWrap(True)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      top = QtWidgets.QHBoxLayout()
      top.addWidget(self.state, 1)
      top.addWidget(self.pipeline_button)
      top.addWidget(self.enable_button)
      top.addWidget(self.disable_button)
      left = QtWidgets.QVBoxLayout()
      left.addWidget(rules)
      left.addWidget(bonus_box, 1)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(msg_box)
      right.addWidget(preview)
      right.addStretch(1)
      body = QtWidgets.QHBoxLayout()
      body.addLayout(left, 1)
      body.addLayout(right, 1)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addLayout(top)
      lay.addLayout(body, 1)
      lay.addWidget(self.items)
      lay.addWidget(self.errors)
      self.hp.setValue(PREVIEW_HP)
      self.level.setValue(PREVIEW_LEVEL)

   # -- reading -------------------------------------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the section, the choices, the items that recruit and the preview.
      @return None
      """
      doc, p = self.structure_doc(), self.project()
      set_enabled(self, doc is not None)
      if doc is None or p is None:
         return
      stated = recruit_model.is_stated(doc)
      piped = recruit_model.has_pipeline(p)
      s = recruit_model.section(doc)
      self._filling = True
      try:
         self.state.setText(("Recruitment is on." if stated else "No recruitment: no item can recruit.") +
                            (f" The ruleset lists {recruit_model.pipeline_name()}." if piped else
                             f" The ruleset lists no {recruit_model.pipeline_name()} (Add pipeline)."))
         self.enable_button.setEnabled(not stated and piped)
         self.disable_button.setEnabled(stated)
         self.pipeline_button.setEnabled(not piped)
         for w in (self.checks, self.rate, self.owned, self.item_role, self.bonus, self.break_free,
                   *self.keep.values(), *self.consumes.values(), *self.messages.values()):
            set_enabled(w, stated)   # a view among them goes read-only and keeps its scroll bars
         set_spin(self.checks, s[recruit_model.CHECKS_KEY] or recruit_model.NEW_CHECKS)
         set_combo(self.rate, [NONE_CHOICE] + recruit_model.rate_choices(doc), s[recruit_model.RATE_KEY] or NONE_CHOICE)
         set_combo(self.owned, recruit_model.owned_choices(), s[recruit_model.OWNED_KEY])
         set_combo(self.item_role, [NONE_CHOICE] + recruit_model.role_choices(doc),
                   s[recruit_model.ITEM_ROLE_KEY] or NONE_CHOICE)
         for k, box in self.keep.items():
            set_check(box, k in s[recruit_model.KEEP_KEY])
         self.allow_eggs.setEnabled(stated)
         set_check(self.allow_eggs, nursery_model.allowed(doc, "recruit"))
         for k, box in self.consumes.items():
            set_check(box, k in s[recruit_model.REFUSAL_CONSUMES_KEY])
         bonuses = s[recruit_model.STATUS_BONUS_KEY]
         given = recruit_model.given(doc).get(recruit_model.STATUS_BONUS_KEY) or {}
         self.bonus.setRowCount(len(bonuses))
         editable = QtCore.Qt.ItemFlag.ItemIsEditable
         for r, (status, value) in enumerate(bonuses.items()):
            name = QtWidgets.QTableWidgetItem(status)
            name.setFlags(name.flags() & ~editable)
            self.bonus.setItem(r, STATUS_COLUMN, name)
            cell = QtWidgets.QTableWidgetItem(str(value))
            cell.setToolTip("stated" if status in given else "default (the none row's value)")
            self.bonus.setItem(r, BONUS_COLUMN, cell)
         keys = [NONE_CHOICE] + recruit_model.message_choices(doc)
         for m, c in self.messages.items():
            set_combo(c, keys, s[recruit_model.MESSAGES_KEY].get(m) or NONE_CHOICE)
         self.break_free.setText(f"{LIST_SEPARATOR} ".join(s[recruit_model.BREAK_FREE_KEY]))
         species = [str(e.get("name")) for e in battle.entries(p.battle, "species") if isinstance(e, dict)]
         set_combo(self.species, species, self.species.currentText() or (species[0] if species else None))
         items = recruit_model.recruit_items(p)
         set_combo(self.item, items, self.item.currentText() or (items[0] if items else None))
         set_combo(self.status, list(bonuses), self.status.currentText() or recruit_model.no_status())
         self.items.setText("Items that recruit: " + (", ".join(
            f"{i} (bonus {recruit_model.recruit_bonus(p, i)})" for i in items) or "none (Content > Items: Recruit)"))
      finally:
         self._filling = False
      self.update_preview()
      self.show_errors()

   def set_allow_eggs(self, on: bool) -> bool:
      """!Sets whether eggs may be recruited (B2: core.structure.nursery.set_refusal()).
      @param on  True: an egg may be recruited
      @return True when it went through
      """
      doc = self.structure_doc()
      if doc is None or self._filling:
         return False
      ok = self.edit("Recruit eggs", lambda: nursery_model.set_refusal(doc, "recruit", "", on))
      if not ok:
         self.host.changed()
      return ok

   def preview_inputs(self) -> dict[str, int]:
      """!The preview's recruit_odds inputs.
      @return inputs (the rate read from the species, the bonus from the item's logic)
      @throws DocumentError when the data does not compile
      """
      p, doc = self.project(), self.structure_doc()
      max_hp = PERCENT
      bonus_text = recruit_model.recruit_bonus(p, self.item.currentText()) if self.item.currentText() else None
      s = recruit_model.section(doc)
      return {"target_hp": max(1, self.hp.value()), "target_max_hp": max_hp,
              "recruit_rate": recruit_model.species_rate(p, self.species.currentText()),
              "bonus": int(bonus_text) if bonus_text is not None and bonus_text.isdigit() else 0,
              "status_bonus": int(s[recruit_model.STATUS_BONUS_KEY].get(self.status.currentText(), 0)),
              "target_level": self.level.value(), "user_level": self.level.value()}

   def update_preview(self) -> None:
      """!Runs recruit_odds for the preview's inputs.
      @return None
      """
      if self._filling:
         return
      doc, p = self.structure_doc(), self.project()
      if doc is None or p is None or not recruit_model.is_stated(doc) or not self.species.currentText():
         self.odds.setText("")
         return
      try:
         self.odds.setText(recruit_model.odds_text(recruit_model.odds(p, self.preview_inputs())))
      except DocumentError as e:
         self.odds.setText(str(e))

   # -- editing -------------------------------------------------------------------------------------------------------

   def _edit(self, label: str, fn: Any) -> bool:
      """!One edit; a refused one refreshes the page back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      if self._filling:
         return False
      ok = self.edit(label, fn)
      if not ok:
         self.host.changed()
      return ok

   def enable(self) -> bool:
      """!Gives the structure a recruit section.
      @return True when it went through
      """
      doc = self.structure_doc()
      return doc is not None and self._edit("Enable recruitment", lambda: recruit_model.enable(doc))

   def disable(self) -> bool:
      """!Takes the section out.
      @return True when it went through
      """
      doc = self.structure_doc()
      return doc is not None and self._edit("Disable recruitment", lambda: recruit_model.disable(doc))

   def add_pipeline(self) -> bool:
      """!Writes the neutral recruit_odds into the ruleset (an edit of the ruleset file).
      @return True when it went through
      """
      p = self.project()
      if p is None or self._filling:
         return False
      ok = self.host.run_edit("Add recruit_odds", lambda: recruit_model.add_pipeline(p.ruleset), p.ruleset)
      if not ok:
         self.host.changed()
      return ok

   def set_field(self, field: str, value: Any) -> bool:
      """!Sets checks, rate, owned or item_role.
      @param field  the field
      @param value  the value
      @return True when it went through
      """
      doc = self.structure_doc()
      return doc is not None and self._edit(f"Recruit {field}",
                                            lambda: recruit_model.set_field(doc, field, value))

   def set_keep(self) -> bool:
      """!Sets what a recruited record keeps from the boxes.
      @return True when it went through
      """
      doc = self.structure_doc()
      kept = [k for k, box in self.keep.items() if box.isChecked()]
      return doc is not None and self._edit("Recruit keep", lambda: recruit_model.set_keep(doc, kept))

   def set_refusal_consumes(self) -> bool:
      """!Sets the refusals that use the item up from the boxes (C6).
      @return True when it went through
      """
      doc = self.structure_doc()
      refused = [k for k, box in self.consumes.items() if box.isChecked()]
      return doc is not None and self._edit("Recruit refusal consumes",
                                            lambda: recruit_model.set_refusal_consumes(doc, refused))

   def set_status_bonus(self, status: str, value: int | None) -> bool:
      """!Sets a status's bonus.
      @param status  a status or "none"
      @param value   the bonus, or None (the default)
      @return True when it went through
      """
      doc = self.structure_doc()
      return doc is not None and self._edit("Recruit status bonus",
                                            lambda: recruit_model.set_status_bonus(doc, status, value))

   def _bonus_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A bonus was typed (empty: back to the default).
      @param item  the cell
      @return None
      """
      if self._filling or item.column() != BONUS_COLUMN:
         return
      status = self.bonus.item(item.row(), STATUS_COLUMN).text()
      text = item.text().strip()
      if not text:
         self.set_status_bonus(status, None)
      elif text.isdigit():
         self.set_status_bonus(status, int(text))
      else:
         self.host.changed()

   def set_message(self, moment: str, key: str | None) -> bool:
      """!Sets a moment's message.
      @param moment  the moment
      @param key     a message key, or None
      @return True when it went through
      """
      doc = self.structure_doc()
      return doc is not None and self._edit("Recruit message", lambda: recruit_model.set_message(doc, moment, key))

   def set_break_free(self, text: str) -> bool:
      """!Sets the "broke free" messages from their comma separated keys.
      @param text  the keys
      @return True when it went through
      """
      doc = self.structure_doc()
      keys = [k.strip() for k in text.split(LIST_SEPARATOR) if k.strip()]
      if doc is None or keys == recruit_model.section(doc)[recruit_model.BREAK_FREE_KEY]:
         return False
      return self._edit("Recruit break free", lambda: recruit_model.set_break_free(doc, keys))
