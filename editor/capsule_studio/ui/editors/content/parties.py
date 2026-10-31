"""!The Parties panel: reward base, rank, escape, AI flags, the presenters a
party shows, its members and what its intro shows.

Every widget follows the compiled structure (S11, D-22 A15): the AI boxes
are the engine's AI flags, ranks run to rules.rank_max and levels to
rules.level_max, one move box per move slot of the record layout, the passive
slot box lists the structure's passive slots, genes go to the layout's
stat_genes width, and a party takes as many members and presenters as the
layout and the engine hold.

It edits the host's BattleProject (core.battle) through host.run_edit(); the
engine's battle compiler checks the values and its message shows under the
form.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core import ai as ai_model
from ....core import battle, engine
from ....core.document import DocumentError
from ....core.structure import passive_slots, record
from ...panes import split_box
from ...widgets import button, set_enabled
from ..battle_common import (NONE_TEXT, TERM_SLOT, EntryPanel, combo, set_check, set_combo, set_spin,
                             set_spin_max, spin)

if TYPE_CHECKING:
   from ..battle_common import JsonDict, JsonValue

## Height of one row of a party's presenter list, pixels (the list holds the engine's most presenters).
PRESENTER_ROW_HEIGHT = 24
## Height the presenter list's frame adds, pixels.
PRESENTER_LIST_FRAME = 8


def max_reward() -> int:
   """!Highest reward base of a party (PartyData::reward is 16 bits: the compiler's U16_MAX).
   @return the value
   """
   return int(engine.tool("battle_compiler").U16_MAX)


def default_rank() -> int:
   """!Rank of a party that states none (the compiler's DEFAULT_RANK).
   @return the rank
   """
   return int(engine.tool("battle_compiler").DEFAULT_RANK)


class PartiesPanel(EntryPanel):
   """!Parties (the game may call them trainers, teams, ...): reward base,
   rank, escape, AI flags, the presenters shown for them (in order: the first
   enters first), the members, and what the intro shows.

   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "parties"
   ## See EditorPanel.title.
   title = "Parties"
   ## See EntryPanel.kind.
   kind = "parties"
   ## See BattlePanel.title_kind.
   title_kind = "parties"

   def build_form(self, layout: QtWidgets.QVBoxLayout) -> None:
      """!Party fields, presenters, members and the member editor.
      @param layout  QVBoxLayout
      @return None
      """
      ## Reward base (the reward formula's reward_base).
      self.reward = spin(0, max_reward(), lambda v: self.set_field("reward", v))
      ## Rank (the exp formula's foe_rank; up to rules.rank_max once data is open).
      self.rank = spin(0, battle.rank_max(None), lambda v: self.set_field("rank", v))
      ## The player may escape from a battle against the party.
      self.escape = QtWidgets.QCheckBox("the player may escape")
      self.escape.toggled.connect(lambda on: self.set_field("escape", None if on else False, "Set escape"))
      ## The party's AI profile (G1: the data's ai_profiles, Logic > AI; the first entry: none, the default one).
      self.ai = QtWidgets.QComboBox()
      self.ai.activated.connect(lambda i: self.set_field("ai", None if i == 0 else self.ai.currentText(),
                                                         "Set AI profile"))
      ai_row = QtWidgets.QHBoxLayout()
      ai_row.addWidget(self.ai)
      ai_row.addStretch(1)
      form = QtWidgets.QFormLayout()
      form.addRow(self.term_label("reward", False, TERM_SLOT + " (base)"), self.reward)
      form.addRow("Rank", self.rank)
      form.addRow("Escape", self.escape)
      form.addRow("AI", ai_row)
      layout.addLayout(form)

      # Presenters shown for the party.
      layout.addWidget(self.term_label("presenter", True, TERM_SLOT + " (the first enters first)"))
      ## Presenter names the party shows.
      self.shown = QtWidgets.QListWidget()
      self.shown.setMaximumHeight(PRESENTER_ROW_HEIGHT * battle.presenters_max() + PRESENTER_LIST_FRAME)
      layout.addWidget(self.shown)
      ## Presenter to add.
      self.presenter_choice = QtWidgets.QComboBox()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.presenter_choice, 1)
      ## Presenter list buttons: add, remove, up, down.
      self.presenter_buttons = [button("Add", lambda: self.attach_presenter()),
                                button("Remove", lambda: self.detach_presenter()),
                                button("Up", lambda: self.move_presenter(-1), "Enters earlier"),
                                button("Down", lambda: self.move_presenter(1), "Enters later")]
      for b in self.presenter_buttons:
         row.addWidget(b)
      layout.addLayout(row)

      # Members.
      layout.addWidget(QtWidgets.QLabel("Members"))
      ## Party members.
      self.members = QtWidgets.QListWidget()
      self.members.currentRowChanged.connect(lambda *a: self._member_chosen())
      layout.addWidget(self.members, 1)
      row = QtWidgets.QHBoxLayout()
      ## Adds a member.
      self.add_member_button = self.term_text(button("", lambda: self.add_member()), "creature", False,
                                              "Add " + TERM_SLOT)
      row.addWidget(self.add_member_button)
      row.addWidget(button("Remove", lambda: self.remove_member()))
      layout.addLayout(row)
      ## Member species.
      self.m_species = combo(lambda t: self._member_changed("species", t))
      ## Member level.
      self.m_level = spin(1, battle.level_max(None), lambda v: self._member_changed("level", v))   # rules.level_max
      ## Member held item.
      self.m_item = combo(lambda t: self._member_changed("item", None if t == NONE_TEXT else t))
      ## Member passive slot: one of the structure's passive slots (Structure > Passive slots), written by name.
      self.m_passive = combo(lambda t: self._passive_picked(t))
      ## Member genes.
      # (the maximum follows the record layout's stat_genes width once data is open: _fill_member())
      self.m_genes = spin(0, record.gene_max(None), lambda v: self._member_changed("genes", v))
      ## Member trait.
      self.m_trait = combo(lambda t: self._member_changed("trait", None if t == NONE_TEXT else t))
      ## Member moves: one combo per move slot of the record layout (see _ensure_move_combos()).
      self.m_moves = []
      ## Row holding the move combos.
      self.moves_row = QtWidgets.QHBoxLayout()
      self._ensure_move_combos(record.default_move_slots())   # fill_form() follows the open data's layout
      mform = QtWidgets.QFormLayout()
      mform.addRow(self.term_label("species"), self.m_species)
      mform.addRow(self.term_label("level"), self.m_level)
      mform.addRow(self.term_label("item"), self.m_item)
      mform.addRow(self.term_label("passive", False, TERM_SLOT + " slot"), self.m_passive)
      mform.addRow(self.term_label("genes"), self.m_genes)
      mform.addRow(self.term_label("trait"), self.m_trait)
      mform.addRow(self.term_label("move", True, TERM_SLOT + " (none: learnset)"), self.moves_row)
      layout.addLayout(mform)

      # What the intro shows (core.battle.intro()).
      ## The intro, step by step.
      self.intro = QtWidgets.QLabel()
      self.intro.setWordWrap(True)
      self.intro.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      layout.addWidget(self.term_label("format", False, "Intro (first " + TERM_SLOT + ", foe side)"))
      layout.addWidget(self.intro)
      split_box(layout)   # [RZ] presenters over members

   def _ensure_move_combos(self, slots: int) -> None:
      """!Makes one move combo per move slot (the layout's move_slots), adding or removing combos as needed.
      @param slots  move slots
      @return None
      """
      while len(self.m_moves) > slots:
         c = self.m_moves.pop()
         self.moves_row.removeWidget(c)
         c.hide()   # out of sight at once (the deletion waits for the event loop)
         c.deleteLater()
      while len(self.m_moves) < slots:
         c = combo(lambda _t: self._member_changed("moves", self._moves_value()))
         self.moves_row.addWidget(c)
         self.m_moves.append(c)

   def fill_form(self, entry: JsonDict | None) -> None:
      """!Shows a party.
      @param entry  party dict or None
      @return None
      """
      p = self.project()
      on = entry is not None
      e = entry or {}
      set_spin(self.reward, e.get("reward", 0))
      set_spin_max(self.rank, battle.rank_max(p.structure if p is not None else None))
      set_spin(self.rank, e.get("rank", default_rank()))
      set_check(self.escape, e.get("escape", True) is not False)
      doc = p.battle if p is not None else None
      default = ai_model.default_name(doc)
      chosen = e.get("ai") if isinstance(e.get("ai"), str) else None
      set_combo(self.ai, [f"{ai_model.DEFAULT_CHOICE} ({default})"] + ai_model.profile_names(doc),
                chosen if chosen is not None else f"{ai_model.DEFAULT_CHOICE} ({default})")

      # Presenters: the shown list keeps its row; the choice offers the ones not shown yet.
      shown = [n for n in (e.get("presenters") or []) if isinstance(n, str)]
      keep = self.shown.currentRow()
      self.shown.clear()
      self.shown.addItems(shown)
      self.shown.setCurrentRow(min(max(keep, 0), len(shown) - 1) if shown else -1)
      others = [n for n in (p.names("presenters") if p else []) if n not in shown]
      chosen = self.presenter_choice.currentText()
      set_combo(self.presenter_choice, others, chosen if chosen in others else (others[0] if others else None))

      row = self.members.currentRow()
      self.members.blockSignals(True)
      self.members.clear()
      for pm in e.get("members", []):
         self.members.addItem(f"{pm.get('species', '?')}  {self.word('level')} {pm.get('level', '?')}")
      n = self.members.count()
      self.members.setCurrentRow(min(max(row, 0), n - 1) if n else -1)   # keep the row, clamped to the party
      self.members.blockSignals(False)
      for w in [self.reward, self.rank, self.escape, self.shown, self.presenter_choice, self.members,
                self.add_member_button, self.ai] + self.presenter_buttons:
         set_enabled(w, on)   # the lists go read-only and keep their scroll bars
      # A full party (the layout's party_size) takes no more members, nor more presenters than the engine shows.
      self.add_member_button.setEnabled(on and p is not None and n < record.party_size(p.battle))
      self.presenter_buttons[0].setEnabled(on and bool(others) and len(shown) < battle.presenters_max())
      self._fill_member()
      self._fill_intro()

   def _fill_intro(self) -> None:
      """!Shows what the party's intro shows (or why it cannot be shown).
      @return None
      """
      doc = self.battle_doc()
      party = self.selected   # a local name: Doxygen misreads self.x inside battle.intro(...)
      if doc is None or party is None:
         self.intro.setText("")
         return
      try:
         self.intro.setText("\n".join(battle.intro(doc, party)))
      except (DocumentError, KeyError, IndexError, TypeError, ValueError, engine.EngineNotFound) as e:
         self.intro.setText(f"(no intro: {e})")

   # -- presenters --------------------------------------------------------------------------

   def attach_presenter(self) -> None:
      """!Adds the chosen presenter to the party (last: it enters last).
      @return None
      """
      name = self.presenter_choice.currentText()
      if self.selected is None or not name:
         return
      doc = self.battle_doc()
      party = self.selected
      self.edit("Attach " + self.word("presenter"), lambda: battle.presenter_attach(doc, party, name))

   def detach_presenter(self) -> None:
      """!Removes the selected presenter from the party.
      @return None
      """
      item = self.shown.currentItem()
      if self.selected is None or item is None:
         return
      doc = self.battle_doc()
      party = self.selected
      name = item.text()
      self.edit("Detach " + self.word("presenter"), lambda: battle.presenter_detach(doc, party, name))

   def move_presenter(self, delta: int) -> None:
      """!Moves the selected presenter earlier or later in the party's list.
      @param delta  -1 earlier, +1 later
      @return None
      """
      e = self.current()
      i = self.shown.currentRow()
      shown = list((e or {}).get("presenters") or [])
      j = i + delta
      if not (0 <= i < len(shown) and 0 <= j < len(shown)):
         return
      shown[i], shown[j] = shown[j], shown[i]
      self.set_field("presenters", shown, "Reorder " + self.word("presenter", True))
      self.shown.setCurrentRow(j)

   # -- members -----------------------------------------------------------------------------

   def member(self) -> tuple[int, JsonDict | None]:
      """!The selected party member.
      @return (index, dict) or (-1, None)
      """
      e = self.current()
      i = self.members.currentRow()
      members = (e or {}).get("members", [])
      return (i, members[i]) if 0 <= i < len(members) else (-1, None)

   def _member_chosen(self) -> None:
      """!Another party member was picked.
      @return None
      """
      was = self._filling
      self._filling = True
      try:
         self._fill_member()
      finally:
         self._filling = was

   def _fill_member(self) -> None:
      """!Shows the selected member.
      @return None
      """
      p = self.project()
      _, pm = self.member()
      m = pm or {}
      slots = record.move_slots(p.battle) if p is not None else len(self.m_moves)
      self._ensure_move_combos(slots)
      set_combo(self.m_species, p.names("species") if p else [], m.get("species"))
      set_spin_max(self.m_level, battle.level_max(p.structure if p is not None else None))
      set_spin(self.m_level, m.get("level", 1))
      set_combo(self.m_item, [NONE_TEXT] + (p.names("items") if p else []), m.get("item") or NONE_TEXT)
      names = passive_slots.slot_names(p.battle if p is not None else None)
      at = m.get("passive", 0)
      current = names[at] if isinstance(at, int) and not isinstance(at, bool) and 0 <= at < len(names) else at
      set_combo(self.m_passive, names, current)   # a slot the structure lacks still shows (the compiler says so)
      set_spin_max(self.m_genes, record.gene_max(p.battle if p is not None else None))
      set_spin(self.m_genes, m.get("genes", 0))
      set_combo(self.m_trait, [NONE_TEXT] + (p.names("traits") if p else []), m.get("trait") or NONE_TEXT)
      moves = list(m.get("moves") or []) + [None] * slots
      for c, mv in zip(self.m_moves, moves[:slots]):
         set_combo(c, [NONE_TEXT] + (p.names("moves") if p else []), mv or NONE_TEXT)
      for w in [self.m_species, self.m_level, self.m_item, self.m_passive, self.m_genes,
                self.m_trait] + self.m_moves:
         w.setEnabled(pm is not None)

   def _moves_value(self) -> list[str] | None:
      """!The member's moves from the move combos (empty: the learnset's).
      @return list of names, or None
      """
      moves = [c.currentText() for c in self.m_moves if c.currentText() not in (NONE_TEXT, "")]
      return moves or None

   def _member_changed(self, key: str, value: JsonValue) -> None:
      """!One member field changed: only that field is written.
      @param key    field
      @param value  new value (None removes the field)
      @return None
      """
      if self._filling:
         return
      e = self.current()
      i, pm = self.member()
      if e is None or pm is None:
         return
      if (value is None and key not in pm) or (value is not None and pm.get(key) == value):
         return
      members = [dict(x) for x in e.get("members", [])]
      if value is None:
         members[i].pop(key, None)
      else:
         members[i][key] = value
      self.set_field("members", members, "Edit members")

   def _passive_picked(self, name: str) -> None:
      """!A passive slot was picked for the member: written as the slot's name (unless it is the slot it has).
      @param name  slot name
      @return None
      """
      p = self.project()
      _i, pm = self.member()
      if self._filling or p is None or pm is None:
         return
      names = passive_slots.slot_names(p.battle)
      at = pm.get("passive", 0)
      had = names[at] if isinstance(at, int) and not isinstance(at, bool) and 0 <= at < len(names) else at
      if name and name != had:
         self._member_changed("passive", name)

   def add_member(self) -> None:
      """!Adds a member to the party: the first species, at the level of the party's last member (the lowest level
      when it has none, or a level the rules no longer take).
      @return None
      """
      p = self.project()
      if self.selected is None or p is None or not p.names("species"):
         return
      doc, name, sp = self.battle_doc(), self.selected, p.names("species")[0]
      members = (self.current() or {}).get("members") or []
      last = members[-1].get("level") if members and isinstance(members[-1], dict) else None
      ok = isinstance(last, int) and not isinstance(last, bool) and 1 <= last <= battle.level_max(p.structure)
      level = last if ok else 1
      if self.edit("Add member", lambda: battle.party_add(doc, name, sp, level)):
         n = len((self.current() or {}).get("members", []))
         # Select the new member once the host's refresh after the edit has rebuilt the list.
         QtCore.QTimer.singleShot(0, lambda: self.members.setCurrentRow(n - 1))

   def remove_member(self) -> None:
      """!Removes the selected party member.
      @return None
      """
      i, pm = self.member()
      if pm is None:
         return
      doc, name = self.battle_doc(), self.selected
      self.edit("Remove member", lambda: battle.party_remove(doc, name, i))
