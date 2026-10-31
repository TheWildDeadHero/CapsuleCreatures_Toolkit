"""!The Species panel: types, base stats, passives, growth, experience yield,
sprites, the learnset, a stat preview from the engine's formulas and (G4) the
species' Transformations, Forms, Yields and (B1) Combine moves tabs (species_growth.py);
B1: a species field with named values (an egg group) is a combo of its names.
B2: the Eggs row (with the structure's eggs) edits the species' hatch cycles
and egg look fields and shows the steps an egg of it counts from.

Every widget follows the compiled structure (S11, D-22 A15): one type box per
type a species has (the chart's types_per_species), one base spin per stat,
one passive box per passive slot, levels up to rules.level_max, one
preview spin per per-stat input the record layout holds (genes, training,
awakening), each up to its role's width, and one spin per species field of
the structure (E13a, Structure > Species fields: 0 up to the field's
highest value; grey while the species follows the field's default; the
derived expressions read it as species.NAME).

It edits the host's BattleProject (core.battle) through host.run_edit(); the
engine's battle compiler checks the values and its message shows under the
form.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtWidgets

from ....core import battle, engine
from ....core.structure import chart, passive_slots, record, species_fields
from ....core.structure import nursery as nursery_model
from ....core.structure import stats as stat_model
from ...panes import split_box
from ...widgets import button, set_enabled
from ..battle_common import (NONE_TEXT, TERM_SLOT, EntryPanel, combo, set_combo, set_spin, set_spin_max,
                             spin)
from ..structure.turn import mark_default
from .species_growth import SpeciesGrowthTabs

if TYPE_CHECKING:
   from ..battle_common import JsonDict

def engine_default(name: str) -> int:
   """!A default of the engine's battle compiler (DEFAULT_EXP_YIELD, DEFAULT_LEVEL_MAX: E7's neutral defaults; the
   panel shows what the compiler uses for a value the data leaves out).
   @param name  the battle_compiler name
   @return the value
   """
   return int(getattr(engine.tool("battle_compiler"), name))


def max_base_stat() -> int:
   """!Highest base stat (SpeciesData::base is 16 bits: the compiler's U16_MAX).
   @return the value
   """
   return int(engine.tool("battle_compiler").U16_MAX)


def max_exp_yield() -> int:
   """!Highest experience yield (SpeciesData::exp_yield is 16 bits: the compiler's U16_MAX).
   @return the value
   """
   return int(engine.tool("battle_compiler").U16_MAX)


class SpeciesPanel(EntryPanel):
   """!Species: types, base stats, passives, growth, sprites, learnset,
   and a stat preview from the ruleset's formulas."""

   ## See EditorPanel.panel_id.
   panel_id = "species"
   ## See EditorPanel.title.
   title = "Species"
   ## See EntryPanel.kind.
   kind = "species"
   ## See BattlePanel.title_kind.
   title_kind = "species"

   def build_form(self, layout: QtWidgets.QVBoxLayout) -> None:
      """!Creature fields, learnset table and preview.
      @param layout  QVBoxLayout
      @return None
      """
      ## Species the learnset table last showed (another species clears its selection).
      self._learnset_for = None
      ## Type combos, one per type a species has (the chart's types_per_species; _build_types()); all but the
      ## first may be none.
      self.types = []
      ## Row holding the type combos.
      self.type_row = QtWidgets.QHBoxLayout()
      ## Base stat spins, one per stat of the manifest (_build_base()).
      self.base = []
      ## Labels the base spins were built for.
      self._base_labels = None
      ## Row holding the base stat labels and spins.
      self.base_row = QtWidgets.QHBoxLayout()
      ## Passive combos, one per passive slot of the structure (_build_passives()).
      self.passives = []
      ## Slot names the passive combos were built for.
      self._passive_slots = None
      ## Row holding the passive slot labels and combos.
      self.passive_row = QtWidgets.QHBoxLayout()
      ## Species field spins by field name, one per field of the structure (_build_fields()).
      self.field_spins = {}
      ## Field names the spins were built for.
      self._field_names = None
      ## Row holding the field labels and spins (or a note when the structure has none).
      self.field_row = QtWidgets.QHBoxLayout()
      ## B2: the hatch cycles (the eggs' cycles field).
      self.hatch_cycles = spin(0, 0, lambda v: self._egg_field_changed(nursery_model.EGG_FIELD_KEYS[0], v))
      ## B2: the egg look (the eggs' sprite field).
      self.egg_look = spin(0, 0, lambda v: self._egg_field_changed(nursery_model.EGG_FIELD_KEYS[1], v))
      ## B2: the steps an egg of the species counts from, per egg method.
      self.egg_info = QtWidgets.QLabel()
      ## The Eggs row.
      self.egg_row = QtWidgets.QHBoxLayout()
      for text, w in (("hatch cycles", self.hatch_cycles), ("egg look", self.egg_look)):
         self.egg_row.addWidget(QtWidgets.QLabel(text))
         self.egg_row.addWidget(w)
      self.egg_row.addWidget(self.egg_info, 1)
      ## Growth table.
      self.growth = combo(lambda t: self.set_field("growth", t))
      ## Experience yield.
      self.exp_yield = spin(0, max_exp_yield(), lambda v: self.set_field("exp_yield", v))
      ## Front sprite key.
      self.front = QtWidgets.QLineEdit()
      self.front.editingFinished.connect(lambda: self.set_field("front", self.front.text().strip() or None))
      ## Back sprite key.
      self.back = QtWidgets.QLineEdit()
      self.back.editingFinished.connect(lambda: self.set_field("back", self.back.text().strip() or None))
      self._build_types(chart.types_per_species(None))
      self._build_base(self._stat_labels())
      self._build_passives(passive_slots.slot_names(None))
      self._build_fields([])
      form = QtWidgets.QFormLayout()
      form.addRow(self.term_label("type", True), self.type_row)
      form.addRow(self.term_label("stat", True, "Base " + TERM_SLOT), self.base_row)
      form.addRow(self.term_label("passive", True, TERM_SLOT + " (per slot)"), self.passive_row)
      form.addRow("Species fields", self.field_row)
      form.addRow("Eggs", self.egg_row)
      form.addRow(self.term_label("growth"), self.growth)
      form.addRow(self.term_label("exp", False, TERM_SLOT + " yield"), self.exp_yield)
      form.addRow("Front sprite", self.front)
      form.addRow("Back sprite", self.back)
      layout.addLayout(form)
      # Learnset.
      layout.addWidget(QtWidgets.QLabel("Learnset"))
      ## Learnset rows (level, move).
      self.learnset = QtWidgets.QTableWidget(0, battle.LEARNSET_ENTRY_LENGTH)
      self.learnset.setHorizontalHeaderLabels(["Level", "Move"])
      self.learnset.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.learnset.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      layout.addWidget(self.learnset, 1)
      ## New entry level.
      self.learn_level = QtWidgets.QSpinBox()
      self.learn_level.setRange(1, battle.level_max(None))   # rules.level_max once data is open
      ## New entry move.
      self.learn_move = QtWidgets.QComboBox()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.term_label("level"))
      row.addWidget(self.learn_level)
      row.addWidget(self.learn_move, 1)
      row.addWidget(button("Add", lambda: self.add_learn()))
      row.addWidget(button("Remove selected", lambda: self.remove_learn()))
      layout.addLayout(row)
      # C6: the moves `teach` may give it (none listed by any species: any move)
      ## The teachable moves, as text.
      self.teachable = QtWidgets.QLabel()
      self.teachable.setWordWrap(True)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Teachable"))
      row.addWidget(self.teachable, 1)
      row.addWidget(button("Add move", lambda: self.set_teachable(True), "The learn row's move can be taught"))
      row.addWidget(button("Remove move", lambda: self.set_teachable(False), "The learn row's move cannot"))
      layout.addLayout(row)
      # Preview.
      ## Preview level (it starts at the highest: rules.level_max once data is open).
      self.preview_level = QtWidgets.QSpinBox()
      self.preview_level.setRange(1, battle.level_max(None))
      self.preview_level.setValue(self.preview_level.maximum())
      self.preview_level.valueChanged.connect(lambda *a: self.update_preview())
      ## Preview spins of the per-stat inputs the layout holds ({input: QSpinBox}; _build_inputs()).
      self.preview_inputs = {}
      ## Their labels, by input.
      self._input_labels = {}
      ## Row holding the input labels and spins.
      self.input_row = QtWidgets.QHBoxLayout()
      ## Preview result.
      self.preview = QtWidgets.QLabel()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.term_label("stat", True, TERM_SLOT + " at"))
      row.addWidget(self.term_label("level"))
      row.addWidget(self.preview_level)
      row.addLayout(self.input_row)
      row.addWidget(self.preview, 1)
      layout.addLayout(row)
      self._build_inputs(record.stat_inputs(None))
      # G4: the species' transformation rules, forms and training yields (with their previews)
      ## Transformations / Forms / Yields tabs.
      self.growth_tabs = SpeciesGrowthTabs(self)
      layout.addWidget(self.growth_tabs, 1)
      split_box(layout)   # [RZ] form and learnset over the growth tabs

   def _stat_labels(self) -> list[str]:
      """!The battle's stats as the base row labels them: each stat's abbreviation, else its label.
      @return labels in stat order
      """
      p = self.project()
      if p is None:
         return battle.stat_keys()
      return [r["short"] or r["label"] or r["name"] for r in stat_model.stat_list(p.battle)]

   def _build_types(self, count: int) -> None:
      """!(Re)builds the type combos when the number of types a species shows changed.
      @param count  combos (the chart's types_per_species, or more when a species names more)
      @return None
      """
      if count == len(self.types):
         return
      while self.type_row.count():
         w = self.type_row.takeAt(0).widget()
         if w is not None:
            w.hide()   # out of sight at once (the deletion waits for the event loop)
            w.deleteLater()
      self.types = [combo(lambda _t: self._types_changed()) for _ in range(count)]
      for c in self.types:
         self.type_row.addWidget(c)

   def _build_inputs(self, inputs: dict[str, int]) -> None:
      """!(Re)builds the preview's input spins when the layout's per-stat roles changed (one per role it holds,
      up to the role's highest value).
      @param inputs  record.stat_inputs(): {input: highest value}
      @return None
      """
      if list(inputs) != list(self.preview_inputs):
         while self.input_row.count():
            w = self.input_row.takeAt(0).widget()
            if w is not None:
               w.hide()   # out of sight at once (the deletion waits for the event loop)
               w.deleteLater()
         self.preview_inputs = {}
         self._input_labels = {}
         for key in inputs:
            label = QtWidgets.QLabel()
            box = QtWidgets.QSpinBox()
            box.valueChanged.connect(lambda *a: self.update_preview())
            self._input_labels[key] = label
            self.preview_inputs[key] = box
            self.input_row.addWidget(label)
            self.input_row.addWidget(box)
      for key, most in inputs.items():
         self._input_labels[key].setText(self.word(record.STAT_INPUT_TERMS[key]))
         set_spin_max(self.preview_inputs[key], most)

   def _build_base(self, labels: list[str]) -> None:
      """!(Re)builds the base stat spins when the battle's stats changed.
      @param labels  one label per stat
      @return None
      """
      if labels == self._base_labels:
         return
      self._base_labels = list(labels)
      while self.base_row.count():
         w = self.base_row.takeAt(0).widget()
         if w is not None:
            w.hide()   # out of sight at once (the deletion waits for the event loop)
            w.deleteLater()
      self.base = [spin(1, max_base_stat(), lambda _v: self._base_changed()) for _ in labels]
      for label, s in zip(labels, self.base):
         self.base_row.addWidget(QtWidgets.QLabel(label))
         self.base_row.addWidget(s)

   def _build_passives(self, names: list[str]) -> None:
      """!(Re)builds the passive combos when the structure's passive slots changed (one per slot, its name before
      it).
      @param names  slot names, in slot order
      @return None
      """
      if names == self._passive_slots:
         return
      self._passive_slots = list(names)
      while self.passive_row.count():
         w = self.passive_row.takeAt(0).widget()
         if w is not None:
            w.hide()   # out of sight at once (the deletion waits for the event loop)
            w.deleteLater()
      self.passives = [combo(lambda _t: self._passives_changed()) for _ in names]
      for name, c in zip(names, self.passives):
         self.passive_row.addWidget(QtWidgets.QLabel(name))
         c.setToolTip(f"the passive of the slot {name!r} (Structure > Passive slots)")
         self.passive_row.addWidget(c)

   def _build_fields(self, fields: list[JsonDict]) -> None:
      """!(Re)builds the species field editors when the structure's fields changed (one per field, its name before
      it: a spin from 0 up to the field's highest value, or for a field with named values (B1: an egg group) a combo
      of the names).
      @param fields  species_fields.fields(): [{"name", "width", "max", "default", "values", ...}]
      @return None
      """
      names = [(f["name"], tuple(f.get("values") or ())) for f in fields]
      if names != self._field_names:
         self._field_names = names
         while self.field_row.count():
            w = self.field_row.takeAt(0).widget()
            if w is not None:
               w.hide()   # out of sight at once (the deletion waits for the event loop)
               w.deleteLater()
         self.field_spins = {}
         for name, values in names:
            if values:
               box = combo(lambda t, n=name: self._field_changed(n, t))
               box.addItems(list(values))
            else:
               box = spin(0, 0, lambda v, n=name: self._field_changed(n, v))
            self.field_row.addWidget(QtWidgets.QLabel(name))
            self.field_row.addWidget(box)
            self.field_spins[name] = box
         if not names:
            self.field_row.addWidget(QtWidgets.QLabel("none (Structure > Species fields)"))
         self.field_row.addStretch(1)
      for f in fields:
         box = self.field_spins[f["name"]]
         if isinstance(box, QtWidgets.QSpinBox):
            box.setRange(0, f["max"])

   def _field_changed(self, name: str, value: int | str) -> None:
      """!A species field was edited (the field's default drops the species' own value).
      @param name   field name
      @param value  the value (a value name of a field with names)
      @return None
      """
      doc, species = self.battle_doc(), self.selected
      if doc is None or species is None:
         return
      own = next((v for v in species_fields.values_of(doc, species) if v["name"] == name), None)
      if own is not None and own["value"] == value:
         return
      self.edit("Set species field", lambda: species_fields.set_value(doc, species, name, value))

   def _fill_fields(self, entry: JsonDict | None) -> None:
      """!Shows the selected species' field values (grey: the field's default).
      @param entry  species dict or None
      @return None
      """
      p = self.project()
      doc = p.battle if p is not None else None
      self._build_fields(species_fields.fields(doc))
      values = species_fields.values_of(doc, entry["name"]) if doc is not None and entry is not None and \
         isinstance(entry.get("name"), str) else []
      for v in values:
         box = self.field_spins[v["name"]]
         if isinstance(box, QtWidgets.QComboBox):
            shown = v["value"]
            # a number stored for a field with names shows as its name
            if isinstance(shown, int) and 0 <= shown < len(v["values"]):
               shown = v["values"][shown]
            set_combo(box, v["values"], shown)
         else:
            set_spin(box, v["value"])
         mark_default(box, not v["own"])
         box.setToolTip(f"{species_fields.prefix()}{v['name']}: 0-{v['max']}" +
                        ("" if v["own"] else f" (the field's default {v['default']})"))
      for box in self.field_spins.values():
         box.setEnabled(entry is not None)
      self._fill_eggs(entry)

   def _fill_eggs(self, entry: JsonDict | None) -> None:
      """!Shows the selected species' egg values (B2; the row is grey without the structure's eggs).
      @param entry  species dict or None
      @return None
      """
      p = self.project()
      doc = p.battle if p is not None else None
      name = entry.get("name") if entry is not None else None
      row = nursery_model.species_eggs(doc, name) if doc is not None and isinstance(name, str) else None
      self.hatch_cycles.setEnabled(row is not None)
      self.egg_look.setEnabled(row is not None and bool(row["look_field"]))
      if row is None:
         set_spin(self.hatch_cycles, 0)
         set_spin(self.egg_look, 0)
         self.egg_info.setText("no eggs (Structure > Nursery)" if doc is not None and
                               nursery_model.eggs(doc) is None else "")
         return
      set_spin_max(self.hatch_cycles, row["max"])
      set_spin(self.hatch_cycles, row["cycles"])
      set_spin_max(self.egg_look, row["look_max"])
      set_spin(self.egg_look, row["look"])
      steps = ", ".join(f"{m}: {s} steps" for m, s in row["steps"]) or "no method delivers eggs"
      drawn = row["sprite"] or "the game's own egg drawing"
      look = "" if row["look_field"] else f"; every egg shows {drawn}"
      self.egg_info.setText(f"an egg hatches after {steps}{look}")

   def _egg_field_changed(self, key: str, value: int) -> None:
      """!The hatch cycles or the egg look was edited: the species' value of the field the eggs name.
      @param key    nursery_model.EGG_FIELD_KEYS item
      @param value  the value
      @return None
      """
      p = self.project()
      doc = p.battle if p is not None else None
      row = nursery_model.egg_row(doc) if doc is not None else None
      if row is None or not row[key]:
         return
      self._field_changed(row[key], value)

   def _types_changed(self) -> None:
      """!A type combo changed.
      @return None
      """
      shown = [c.currentText() for c in self.types]
      self.set_field("types", shown[:1] + [t for t in shown[1:] if t != NONE_TEXT], "Set types")

   def _base_changed(self) -> None:
      """!A base stat changed.
      @return None
      """
      self.set_field("base", [s.value() for s in self.base], "Set base stats")

   def _passives_changed(self) -> None:
      """!A passive combo changed.
      @return None
      """
      ab = [None if c.currentText() == NONE_TEXT else c.currentText() for c in self.passives]
      while ab and ab[-1] is None:   # trailing empty slots are left out; inner ones stay as null
         ab.pop()
      self.set_field("passives", ab, "Set " + self.word("passive", True))

   def fill_form(self, entry: JsonDict | None) -> None:
      """!Shows a creature.
      @param entry  species dict or None
      @return None
      """
      p = self.project()
      e = entry or {}
      on = entry is not None
      types = p.names("types") if p else []
      ts = list(e.get("types") or [])
      per = chart.types_per_species(p.battle) if p else 1
      # A species with more types than the chart allows still shows them (the compiler reports it), up to the
      # engine's most.
      self._build_types(max(1, min(max(per, len(ts)), chart.max_types_per())))
      set_combo(self.types[0], types, ts[0] if ts else None)
      for i, c in enumerate(self.types[1:], 1):
         set_combo(c, [NONE_TEXT] + types, ts[i] if len(ts) > i else NONE_TEXT)
      # One base value per stat of the manifest: padded with 1s, extra ones dropped.
      self._build_base(self._stat_labels())
      count = len(self.base)
      base = (list(e.get("base") or []) + [1] * count)[:count]
      for s, v in zip(self.base, base):
         set_spin(s, v)
      passives = p.names("passives") if p else []
      self._build_passives(passive_slots.slot_names(p.battle if p is not None else None))
      count = len(self.passives)
      ab = (list(e.get("passives") or []) + [None] * count)[:count]
      for c, a in zip(self.passives, ab):
         set_combo(c, [NONE_TEXT] + passives, a if a is not None else NONE_TEXT)
      self._fill_fields(entry)
      set_combo(self.growth, p.growth_names() if p else [], e.get("growth"))
      set_spin(self.exp_yield, e.get("exp_yield", engine_default("DEFAULT_EXP_YIELD")))
      self.front.setText(e.get("front", "") or "")
      self.back.setText(e.get("back", "") or "")
      if self.selected != self._learnset_for:
         self._learnset_for = self.selected
         self.learnset.clearSelection()
      level_max = battle.level_max(p.structure if p is not None else None)
      for s in (self.learn_level, self.preview_level):
         set_spin_max(s, level_max)
      # The preview's genes, training and awakening: the roles the record layout holds, as high as their widths.
      self._build_inputs(record.stat_inputs(p.battle if p is not None else None))
      rows = e.get("learnset") or []
      self.learnset.setRowCount(len(rows))
      for r, le in enumerate(rows):
         for c, v in enumerate(le[:battle.LEARNSET_ENTRY_LENGTH] if isinstance(le, list) else ["?", "?"]):
            self.learnset.setItem(r, c, QtWidgets.QTableWidgetItem(str(v)))
      keep = self.learn_move.currentText()
      set_combo(self.learn_move, p.names("moves") if p else [], keep or None)
      taught = e.get(battle.TEACHABLE_KEY) if isinstance(e.get(battle.TEACHABLE_KEY), list) else None
      self.teachable.setText(", ".join(taught) if taught else "(none listed: any move while no species lists any)")
      for w in self.types + self.base + self.passives + [self.growth, self.exp_yield, self.front, self.back,
                                                          self.learnset, self.learn_move]:
         set_enabled(w, on)   # the learnset goes read-only and keeps its scroll bars
      self.update_preview()
      self.growth_tabs.fill(e.get("name") if on and isinstance(e.get("name"), str) else None)

   def update_preview(self) -> None:
      """!Recomputes the stat preview (engine formulas).
      @return None
      """
      p = self.project()
      if p is None or self.selected is None:
         self.preview.setText("")
         return
      try:
         labels = self._base_labels or []
         # the same value of each input for every stat; an input the layout does not hold is 0
         values = {k: [box.value()] * len(labels) for k, box in self.preview_inputs.items()}
         st = p.stats(self.selected, self.preview_level.value(), values.get("gene"), values.get("training"),
                      None, values.get("awaken"))
         self.preview.setText("  ".join(f"{k} {v}" for k, v in zip(labels, st)))
      except Exception as e:   # DocumentError, EngineNotFound
         self.preview.setText(f"({e})")

   def add_learn(self) -> None:
      """!Adds the level / move pair below the table.
      @return None
      """
      if self.selected is None or not self.learn_move.currentText():
         return
      doc, name = self.battle_doc(), self.selected
      level, move = self.learn_level.value(), self.learn_move.currentText()
      self.edit("Learn move", lambda: battle.learn(doc, name, level, move))

   def set_teachable(self, on: bool) -> bool:
      """!Adds the learn row's move to the species' teachable moves, or takes it out (C6).
      @param on  add (True) or remove
      @return True when it went through
      """
      if self.selected is None or not self.learn_move.currentText():
         return False
      doc, name, move = self.battle_doc(), self.selected, self.learn_move.currentText()
      return bool(self.edit("Teachable", lambda: battle.set_teachable(doc, name, move, on)))

   def remove_learn(self) -> None:
      """!Removes the selected learnset rows.
      @return None
      """
      e = self.current()
      if e is None:
         return
      rows = sorted({i.row() for i in self.learnset.selectedItems()}, reverse=True)   # last first: indices stay valid
      if not rows:
         return
      ls = [list(x) for x in e.get("learnset", [])]
      for r in rows:
         if 0 <= r < len(ls):
            del ls[r]
      self.set_field("learnset", ls, "Remove learnset rows")
