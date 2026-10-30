"""!The Conditions panel (D-22 A3-A5, D-23 §3.2 "Conditions"): the battle
manifest's statuses, volatiles, weathers, side and field conditions as
records, one tab per kind, with the engine's budgets above them.

Each tab lists its records (new / copy / rename / delete / up / down) next
to a form of every field the engine's battle compiler takes for the kind
(core.structure.conditions.FIELDS: durations, counters, words, what clears
a volatile, layers, chains, residual shares, odds, immune types, tags...),
the record's texts (each checked by the engine's text encoder: placeholders,
terms, the code page), a status's or weather's manifest point handlers and
what names the record. "Logic..." shows the record's `.ceffect` owner on the
Logic > Effects page. The budget bars count volatile bits, counters and
words, status ids and side / field conditions against the engine's storage.
Every change is one undo step of the battle manifest (a rename takes the
effect logic with it); the compile result shows at the bottom.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6 import QtWidgets

from ....core import battle, holders
from ....core.document import DocumentError
from ....core.structure import conditions as cond_model
from ...widgets import button, set_enabled
from ..battle_common import (FORM_STRETCH, LIST_STRETCH, NONE_TEXT, STRUCTURE, BattlePanel,
                             set_check, set_combo, set_spin)
from ..record_widgets import BudgetBars, NameChecks, PointHandlersBox, TextsTable

if TYPE_CHECKING:
   from ...panel import PanelHost

## Tab titles of the kinds (statuses and weathers: the game's words when its terms name them).
TAB_TITLES = {"status": "Statuses", "volatile": "Volatiles", "weather": "Weathers", "side_condition": "Side conditions",
              "field_condition": "Field conditions"}
## The core.battle kind (a terms concept) of the kinds whose tab title is the game's word.
TERM_KINDS = {"status": "statuses", "weather": "weathers"}
## Text of a volatile skip that always skips.
ALWAYS_TEXT = "always"
## Short help of each field (tool tips).
FIELD_HELP = {
   "residual": "Share of max HP lost at the end of each turn (e.g. 1/8); empty: none",
   "escalating": "The residual grows by one share each turn, up to the cap",
   "skip": "Odds of losing the turn before a move (n/m); a volatile also takes 'always'",
   "cure": "Odds of being cured before a move (n/m)",
   "turns": "Status: [min, max] turns it lasts (0 0: until cured). Others: the default duration (0: none)",
   "immune_types": "Types it never affects",
   "thawed_by_move": "A move with this flag cures it",
   "thawed_by_hit": "A damaging hit of this type cures it",
   "cured_on_switch": "Switching out cures it",
   "color": "HUD colour index",
   "tags": "Tags it gives its holder (Flags & Tags)",
   "duration": "until_switch, one turn, or [min, max] turns (counted down; it ends at 0)",
   "counts": "Where a [min, max] duration counts down",
   "counter": "A counter slot for its logic (holder.counter(X))",
   "word": "A word slot for its logic (holder.word(X))",
   "clears_on": "Events that end it",
   "passes": "Passed on when the holder switches out to pass its changes on",
   "chain": "Consecutive uses succeed with odds 1 in den^n (n up to cap)",
   "hud": "Start / end events reach the screen",
   "layers": "Most layers it stacks to",
   "bound_to": "Bound to the battler that started it: it ends when that one leaves the field or faints (a hold, a "
               "bind, a link); a passing switch hands it on",
}
## Labels in front of a field's second widgets ([min] to [max]; a chain's den, cap and kept_by; a cap).
PART_LABELS = {"hi": "to", "den": "1 in den^n, den", "cap": "cap", "kept_by": "kept by"}
## Lowest value of a range duration's spins.
RANGE_MIN = 0
## A new range duration's turns.
NEW_RANGE = (1, 1)


def field_label(key: str) -> str:
   """!A field's form label.
   @param key  field key
   @return "Immune types"
   """
   return key.replace("_", " ").capitalize()


class ConditionTab(QtWidgets.QWidget):
   """!One condition kind: its records and the form of the selected one.

   @var _filling
   True while the tab fills its widgets.
   """

   def __init__(self, panel: ConditionsPanel, kind: str) -> None:
      """!Builds the list, the form, the texts and the handler table.
      @param panel  the ConditionsPanel (edits, project access)
      @param kind   one of core.structure.conditions.kinds()
      """
      super().__init__()
      ## The panel.
      self.panel = panel
      ## The condition kind.
      self.kind = kind
      ## The selected record, or None.
      self.selected = None
      ## True while the tab fills its widgets.
      self._filling = False
      ## The form's widgets by field key: (field kind, {part: widget}).
      self.inputs = {}
      ## Record names.
      self.entry_list = QtWidgets.QListWidget()
      self.entry_list.currentRowChanged.connect(lambda r: self._row_chosen(r))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(self.entry_list, 1)
      for row in ((("New...", lambda: self.add_record(), "Add a record"),
                   ("Copy", lambda: self.copy_record(), "Add a copy of the selected record"),
                   ("Rename...", lambda: self.rename_record(), "Rename it; the effect logic follows")),
                  (("Delete", lambda: self.remove_record(), "Remove it (no effect logic may name it)"),
                   ("Up", lambda: self.move_record(-1), "Lower engine index"),
                   ("Down", lambda: self.move_record(1), "Higher engine index"))):
         line = QtWidgets.QHBoxLayout()
         for text, fn, tip in row:
            line.addWidget(button(text, fn, tip))
         left.addLayout(line)
      ## Shows the record's owner on Logic > Effects.
      self.logic_button = button("Logic...", lambda: self.open_logic(), "Show its .ceffect logic on Logic > Effects")
      left.addWidget(self.logic_button)
      form_box = QtWidgets.QWidget()
      form = QtWidgets.QVBoxLayout(form_box)
      ## The fields.
      self.form = QtWidgets.QFormLayout()
      for key, field in cond_model.fields(kind).items():
         self._add_input(key, field)
      form.addLayout(self.form)
      form.addWidget(QtWidgets.QLabel("Texts"))
      ## The record's texts.
      self.texts = TextsTable(lambda slot, value: self.set_text(slot, value))
      form.addWidget(self.texts)
      ## The record's point handlers (None for the kinds without): a status's or weather's manifest handlers, a
      ## volatile's or side condition's .ceffect point members (E13b).
      self.handlers = None
      if kind in cond_model.handler_kinds():
         self.handlers = PointHandlersBox(lambda label, fn: self.panel.edit(label, fn),
                                          lambda: self.panel.battle_doc(),
                                          in_logic=cond_model.list_key(kind) in holders.logic_lists())
         form.addWidget(self.handlers)
      ## What names the record.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      form.addWidget(self.used_by)
      form.addStretch(1)
      scroll = QtWidgets.QScrollArea()
      scroll.setWidgetResizable(True)
      scroll.setWidget(form_box)
      lay = QtWidgets.QHBoxLayout(self)
      box = QtWidgets.QWidget()
      box.setLayout(left)
      lay.addWidget(box, LIST_STRETCH)
      lay.addWidget(scroll, FORM_STRETCH)

   # -- the form -----------------------------------------------------------------------

   def _spin(self, lo: int, hi: int, done: Callable[[], object]) -> QtWidgets.QSpinBox:
      """!A spin box reporting finished edits.
      @param lo    minimum
      @param hi    maximum
      @param done  callable() after an edit
      @return QSpinBox
      """
      s = QtWidgets.QSpinBox()
      s.setRange(lo, hi)
      s.editingFinished.connect(lambda: None if self._filling else done())
      return s

   def _add_input(self, key: str, field: str) -> None:
      """!Adds one field's widgets to the form.
      @param key    field key
      @param field  its field kind (core.structure.conditions)
      @return None
      """
      top = cond_model.byte_max()
      parts: dict[str, Any] = {}
      row = QtWidgets.QHBoxLayout()
      if field == cond_model.BOOL:
         parts["check"] = QtWidgets.QCheckBox()
         parts["check"].clicked.connect(lambda on, k=key: self.set_field(k, bool(on)))
      elif field in (cond_model.BYTE, cond_model.LAYERS):
         lo = 1 if field == cond_model.LAYERS else 0
         parts["spin"] = self._spin(lo, top, lambda k=key: self.set_field(k, self.inputs[k][1]["spin"].value()))
      elif field in (cond_model.SHARE, cond_model.ODDS, cond_model.SKIP):
         parts["edit"] = QtWidgets.QLineEdit()
         parts["edit"].setPlaceholderText(f"{ALWAYS_TEXT} or n/m" if field == cond_model.SKIP else "n/m")
         parts["edit"].editingFinished.connect(lambda k=key: self._text_field(k))
      elif field == cond_model.PAIR:
         most = cond_model.turns_max()
         for part in ("lo", "hi"):
            parts[part] = self._spin(0, most, lambda k=key: self._pair_field(k))
      elif field in (cond_model.TYPES, cond_model.TAGS, cond_model.CLEARS):
         parts["names"] = NameChecks(lambda names, k=key: self.set_field(k, names))
      elif field in (cond_model.TYPE, cond_model.FLAG, cond_model.BOUND):
         parts["combo"] = QtWidgets.QComboBox()
         parts["combo"].activated.connect(lambda _i, k=key: self._combo_field(k))
      elif field == cond_model.ESCALATING:
         parts["check"] = QtWidgets.QCheckBox("on")
         parts["check"].clicked.connect(lambda on, k=key: self.set_field(k, bool(on)))
         parts["cap"] = self._spin(1, top, lambda k=key: self.set_field(k, {cond_model.CAP_KEY:
                                                                           self.inputs[k][1]["cap"].value()}))
      elif field == cond_model.DURATION:
         parts["combo"] = QtWidgets.QComboBox()
         parts["combo"].addItems(cond_model.durations())
         parts["combo"].activated.connect(lambda _i, k=key: self._duration_field(k))
         for part in ("lo", "hi"):
            parts[part] = self._spin(RANGE_MIN, top, lambda k=key: self._duration_field(k))
      elif field == cond_model.COUNTS:
         parts["combo"] = QtWidgets.QComboBox()
         parts["combo"].addItems(cond_model.count_modes())
         parts["combo"].activated.connect(lambda _i, k=key: self.set_field(k, self._combo_text(k)))
      else:   # CHAIN
         min_den, max_cap, _odds = cond_model.chain_limits()
         parts["check"] = QtWidgets.QCheckBox("on")
         parts["check"].clicked.connect(lambda on, k=key: self._chain_field(k, bool(on)))
         parts["den"] = self._spin(min_den, top, lambda k=key: self._chain_field(k, True))
         parts["cap"] = self._spin(1, max_cap, lambda k=key: self._chain_field(k, True))
         parts["kept_by"] = QtWidgets.QComboBox()
         parts["kept_by"].activated.connect(lambda _i, k=key: self._chain_field(k, True))
      for part, w in parts.items():
         if part in PART_LABELS:
            row.addWidget(QtWidgets.QLabel(PART_LABELS[part]))
         row.addWidget(w)
      row.addStretch(1)
      label = QtWidgets.QLabel(field_label(key))
      label.setToolTip(FIELD_HELP.get(key, ""))
      self.form.addRow(label, row)
      self.inputs[key] = (field, parts)

   def _fill_form(self, entry: dict[str, Any] | None) -> None:
      """!Shows a record in the form.
      @param entry  the record, or None
      @return None
      """
      doc = self.panel.battle_doc()
      d = battle.merged(doc) if doc is not None else {}   # types are content, flags and tags structure
      types = [t.get("name") for t in d.get("types", []) if isinstance(t, dict)]
      move_flags = list(d.get("move_flags", []))
      tags = list(d.get("tags", []))
      e = entry or {}
      for key, (field, parts) in self.inputs.items():
         value = e.get(key)
         for w in parts.values():
            set_enabled(w, entry is not None)   # name checks go read-only and keep their scroll bars
         if field == cond_model.BOOL:
            set_check(parts["check"], value)
         elif field in (cond_model.BYTE, cond_model.LAYERS):
            set_spin(parts["spin"], value if value is not None else (1 if field == cond_model.LAYERS else 0))
         elif field in (cond_model.SHARE, cond_model.ODDS, cond_model.SKIP):
            parts["edit"].blockSignals(True)
            parts["edit"].setText(ALWAYS_TEXT if value is True else ("" if value is None else str(value)))
            parts["edit"].blockSignals(False)
         elif field == cond_model.PAIR:
            pair = value if isinstance(value, list) and len(value) == cond_model.PAIR_LEN else [0, 0]
            set_spin(parts["lo"], pair[0])
            set_spin(parts["hi"], pair[1])
         elif field in (cond_model.TYPES, cond_model.TAGS, cond_model.CLEARS):
            names = {cond_model.TYPES: types, cond_model.TAGS: tags, cond_model.CLEARS: cond_model.clear_events()}
            checked = value if isinstance(value, list) else (cond_model.clear_events()
                                                             if field == cond_model.CLEARS else [])
            parts["names"].set_names(names[field], [str(v) for v in checked])
         elif field in (cond_model.TYPE, cond_model.FLAG, cond_model.BOUND):
            # G1: bound_to names whom the volatile is bound to (the engine's BOUND_TO), none: not bound
            choices = types if field == cond_model.TYPE else (move_flags if field == cond_model.FLAG
                                                               else cond_model.bound_choices())
            set_combo(parts["combo"], [NONE_TEXT] + choices, value if value is not None else NONE_TEXT)
         elif field == cond_model.ESCALATING:
            set_check(parts["check"], bool(value))
            cap = value.get(cond_model.CAP_KEY) if isinstance(value, dict) else cond_model.default_escalation_cap()
            set_spin(parts["cap"], cap)
            parts["cap"].setEnabled(bool(value))
         elif field == cond_model.DURATION:
            word, rng = cond_model.duration_of(e)
            set_combo(parts["combo"], cond_model.durations(), word)
            set_spin(parts["lo"], (rng or NEW_RANGE)[0])
            set_spin(parts["hi"], (rng or NEW_RANGE)[1])
            parts["lo"].setEnabled(rng is not None)
            parts["hi"].setEnabled(rng is not None)
         elif field == cond_model.COUNTS:
            set_combo(parts["combo"], cond_model.count_modes(), value or cond_model.DEFAULT_COUNTS)
            parts["combo"].setEnabled(isinstance(e.get("duration"), list))
         else:
            on = isinstance(value, dict)
            chain = value if on else {}
            min_den, _cap, _odds = cond_model.chain_limits()
            set_check(parts["check"], on)
            set_spin(parts["den"], chain.get("den", min_den))
            set_spin(parts["cap"], chain.get("cap", 1))
            set_combo(parts["kept_by"], [NONE_TEXT] + move_flags, chain.get("kept_by") or NONE_TEXT)
            for part in ("den", "cap", "kept_by"):
               parts[part].setEnabled(on)

   def _text_field(self, key: str) -> None:
      """!A share / odds field was typed (empty: none).
      @param key  field key
      @return None
      """
      if self._filling:
         return
      text = self.inputs[key][1]["edit"].text().strip()
      value: Any = None if not text else (True if text == ALWAYS_TEXT and self.inputs[key][0] == cond_model.SKIP
                                          else text)
      self.set_field(key, value)

   def _combo_text(self, key: str) -> str:
      """!A field's combo text.
      @param key  field key
      @return the text
      """
      return self.inputs[key][1]["combo"].currentText()

   def _pair_field(self, key: str) -> None:
      """![min, max] spins changed.
      @param key  field key
      @return None
      """
      parts = self.inputs[key][1]
      self.set_field(key, [parts["lo"].value(), parts["hi"].value()])

   def _combo_field(self, key: str) -> None:
      """!A type / move flag / bound_to combo was picked.
      @param key  field key
      @return None
      """
      text = self.inputs[key][1]["combo"].currentText()
      self.set_field(key, None if text == NONE_TEXT else text)

   def _duration_field(self, key: str) -> None:
      """!The duration combo or its spins changed.
      @param key  field key
      @return None
      """
      parts = self.inputs[key][1]
      word = parts["combo"].currentText()
      self.set_field(key, [parts["lo"].value(), parts["hi"].value()] if word == cond_model.RANGE_DURATION else word)

   def _chain_field(self, key: str, on: bool) -> None:
      """!The chain box or its parts changed.
      @param key  field key
      @param on   the chain is on
      @return None
      """
      parts = self.inputs[key][1]
      if not on:
         self.set_field(key, None)
         return
      kept = parts["kept_by"].currentText()
      chain: dict[str, Any] = {"den": parts["den"].value(), "cap": parts["cap"].value()}
      if kept and kept != NONE_TEXT:
         chain["kept_by"] = kept
      self.set_field(key, chain)

   # -- reading ------------------------------------------------------------------------

   def names(self) -> list[str]:
      """!The kind's record names.
      @return names ([] with nothing open)
      """
      doc = self.panel.battle_doc()
      return cond_model.names(doc, self.kind) if doc is not None else []

   def refresh(self) -> None:
      """!Re-reads the list and the selected record.
      @return None
      """
      names = self.names()
      # A local name: Doxygen 1.12 misreads membership tests on self.selected.
      chosen = self.selected
      chosen = chosen if chosen in names else (names[0] if names else None)
      self.selected = chosen
      self._filling = True
      try:
         self.entry_list.clear()
         self.entry_list.addItems(names)
         if chosen is not None:
            self.entry_list.setCurrentRow(names.index(chosen))
         self._fill_selected()
      finally:
         self._filling = False

   def _fill_selected(self) -> None:
      """!Fills the form, texts, handlers and uses of the selected record.
      @return None
      """
      doc, p = self.panel.battle_doc(), self.panel.project()
      entry = cond_model.record(doc, self.kind, self.selected) if doc is not None and self.selected else None
      self._fill_form(entry)
      self.logic_button.setEnabled(entry is not None)
      if entry is None:
         self.texts.show_texts(self.kind, [], lambda _t: None)
         self.used_by.setText("")
         if self.handlers is not None:
            self.handlers.show_handlers(None, [], [])
         return
      name, kind = self.selected, self.kind
      self.texts.show_texts(kind, cond_model.texts_of(doc, kind, name),
                            lambda text: cond_model.text_problem(doc, kind, text), cond_model.messages(doc))
      if self.handlers is not None:
         key = cond_model.list_key(kind)
         self.handlers.show_handlers((key, name), holders.handlers(doc, key, name),
                                     holders.point_choices(p, key) if p is not None else [])
      try:
         users = cond_model.uses(doc, kind, name)
         text = "Named by: " + (", ".join(users) if users else "nothing (no effect logic yet)")
      except DocumentError as e:
         text = f"Named by: unknown while a source does not parse ({e})"
      bench_uses = cond_model.bench_uses(p, kind, name) if p is not None else []
      if bench_uses:
         text += "\nBench scenarios: " + ", ".join(bench_uses)
      self.used_by.setText(text)

   def _row_chosen(self, row: int) -> None:
      """!Another record was picked.
      @param row  list row
      @return None
      """
      if self._filling:
         return
      names = self.names()
      self.selected = names[row] if 0 <= row < len(names) else None
      self._filling = True
      try:
         self._fill_selected()
      finally:
         self._filling = False

   def select(self, name: str) -> None:
      """!Selects a record.
      @param name  its name
      @return None
      """
      names = self.names()
      if name in names:
         self.entry_list.setCurrentRow(names.index(name))

   # -- editing ------------------------------------------------------------------------

   def _edit(self, label: str, fn: Callable[[], object]) -> bool:
      """!One edit; a refused one refreshes the form back.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      ok = self.panel.edit(label, fn)
      if not ok:
         self.panel.host.changed()
      return ok

   def set_field(self, key: str, value: Any) -> bool:
      """!Changes one field of the selected record (one undo step; None: the default).
      @param key    field key
      @param value  the value
      @return True when the edit went through
      """
      doc, kind, name = self.panel.battle_doc(), self.kind, self.selected
      if self._filling or doc is None or name is None:
         return False
      if cond_model.record(doc, kind, name).get(key) == value:
         return False
      return self._edit(f"{field_label(key)}", lambda: cond_model.set_field(doc, kind, name, key, value))

   def set_text(self, slot: str, value: Any) -> bool:
      """!Sets or removes one text of the selected record.
      @param slot   the slot
      @param value  text, {"message": KEY} or None
      @return True when the edit went through
      """
      doc, kind, name = self.panel.battle_doc(), self.kind, self.selected
      if self._filling or doc is None or name is None:
         return False
      given = cond_model.record(doc, kind, name).get("texts")
      if (given.get(slot) if isinstance(given, dict) else None) == value:
         return False
      return self._edit("Condition text", lambda: cond_model.set_text(doc, kind, name, slot, value))

   def add_record(self, name: str | None = None, copy_of: str | None = None) -> bool:
      """!Adds a record after the selected one.
      @param name     its name, or None to ask
      @param copy_of  a record to copy, or None
      @return True when added
      """
      doc = self.panel.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "New " + self.kind.replace("_", " "), "Name:")
         if not ok:
            return False
      names = self.names()
      at = names.index(self.selected) + 1 if self.selected in names else None
      kind = self.kind
      if self._edit("New " + kind.replace("_", " "), lambda: cond_model.add_record(doc, kind, name, copy_of, at)):
         self.selected = name.strip()
         return True
      return False

   def copy_record(self, name: str | None = None) -> bool:
      """!Adds a copy of the selected record.
      @param name  the copy's name, or None for "NAME copy"
      @return True when added
      """
      if self.selected is None:
         return False
      return self.add_record(name if name is not None else f"{self.selected} copy", self.selected)

   def remove_record(self) -> bool:
      """!Removes the selected record (refused while effect logic names it).
      @return True when removed
      """
      doc, kind, name = self.panel.battle_doc(), self.kind, self.selected
      if doc is None or name is None:
         return False
      if self._edit("Delete " + kind.replace("_", " "), lambda: cond_model.remove_record(doc, kind, name)):
         self.selected = None
         return True
      return False

   def rename_record(self, new: str | None = None) -> bool:
      """!Renames the selected record; the effect logic follows (one undo step).
      @param new  the new name, or None to ask
      @return True when renamed
      """
      doc, kind, old = self.panel.battle_doc(), self.kind, self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename", "New name:", text=old)
         if not ok:
            return False
      if not new.strip() or new.strip() == old:
         return False
      if self._edit("Rename " + kind.replace("_", " "), lambda: cond_model.rename_record(doc, kind, old, new)):
         self.selected = new.strip()
         return True
      return False

   def move_record(self, delta: int) -> bool:
      """!Moves the selected record up or down.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, kind, name = self.panel.battle_doc(), self.kind, self.selected
      if doc is None or name is None:
         return False
      moved = []
      ok = self._edit("Move " + kind.replace("_", " "),
                      lambda: moved.append(cond_model.move_record(doc, kind, name, delta)))
      return ok and moved == [True]

   def open_logic(self) -> bool:
      """!Shows the selected record's owner on Logic > Effects.
      @return True when the Effects page shows it
      """
      if self.selected is None:
         return False
      return self.panel.open_logic(f"{self.kind}:{self.selected}")


class ConditionsPanel(BattlePanel):
   """!The condition budgets and one tab per condition kind.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "conditions"
   ## See EditorPanel.title.
   title = "Conditions"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the budget bars and the tabs.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The engine's condition budgets.
      self.budget = BudgetBars()
      ## One tab per kind.
      self.tabs = QtWidgets.QTabWidget()
      ## The tabs by kind.
      self.kind_tabs = {}
      for kind in cond_model.kinds():
         tab = ConditionTab(self, kind)
         self.kind_tabs[kind] = tab
         self.tabs.addTab(tab, TAB_TITLES[kind])
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("A record keeps what the engine stores; its fields are templates the compiler turns "
                              "into effect code (the record's own logic: Logic...). Texts take the placeholders "
                              "their kind allows and {@term} words.")
      note.setWordWrap(True)
      lay.addWidget(note)
      lay.addWidget(self.budget)
      lay.addWidget(self.tabs, 1)
      lay.addWidget(self.errors)

   def tab(self, kind: str) -> ConditionTab:
      """!A kind's tab.
      @param kind  one of core.structure.conditions.kinds()
      @return the tab
      """
      return self.kind_tabs[kind]

   def show_kind(self, kind: str) -> ConditionTab:
      """!Brings a kind's tab to the front.
      @param kind  one of core.structure.conditions.kinds()
      @return the tab
      """
      tab = self.kind_tabs[kind]
      self.tabs.setCurrentWidget(tab)
      return tab

   def refresh(self) -> None:
      """!Re-reads the budgets and every tab; tab titles follow the game's words.
      @return None
      """
      doc = self.battle_doc()
      self.budget.show_budget(cond_model.budget(doc) if doc is not None else [])
      terms = battle.data_of(doc, "terms").get("terms") if doc is not None else None
      for i, (kind, tab) in enumerate(self.kind_tabs.items()):
         concept = battle.KIND_CONCEPTS.get(TERM_KINDS.get(kind, ""))
         # The game's word only where its terms give one (the engine's default plural of "status" is wrong).
         named = concept is not None and isinstance(terms, dict) and concept in terms
         self.tabs.setTabText(i, self.word(concept, True) if named else TAB_TITLES[kind])
         tab.setEnabled(doc is not None)
         tab.refresh()
      self.show_errors()
