"""!The Pipelines & Points panel (D-20 F PipelinePanel, D-23 §3.3): the
ruleset's pipelines step by step, its modifier points, and a damage
calculator that shows every step of one hit.

  - Pipelines: pick one of the engine's pipelines (damage, self_hit, speed,
    accuracy, crit, effect_odds); its steps run top to bottom (the order of
    the random draws too). An optional pipeline the ruleset leaves out
    (effect_odds) shows the engine's steps greyed as "engine default (plain
    odds)"; the first edit starts from them, Engine default gives it back.
    Drag a step or use Up / Down to reorder; add let, point and roll steps.
    The selected step's variable, expression (or point, or span; coloured
    and completed: expression_edit.FormulaEdit, with the pipeline's inputs,
    the earlier steps' variables, the constants, functions, helpers and
    named formulas; E13a bit operators) and clamp range are edited below
    the list, with the range the
    engine's interval analysis gives and whether the clamp can engage
    (core.pipelines.pipeline_report()).
  - Points: holder, the sources in the order they run, the range of the
    result and how many pipeline steps and handlers use the point; a used
    point can't be removed.
  - Damage calculator: attacker, defender, move, levels, roll, critical hit,
    spread, weather, status and the other inputs of core.pipelines.
    damage_trace(), with its step-by-step trace (unsaved edits count).

The panel edits the ruleset Document, so Undo / Redo on this page act on
the ruleset; every change is one undo step.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import battle, engine, expressions, pipelines
from ....core.document import DocumentError
from ....core.structure import record
from ....core.structure import turn as turn_model
from ...panes import split_box
from ...widgets import button, set_enabled
from ..battle_common import NONE_TEXT, BattlePanel, set_combo, set_spin, set_spin_max
from .expression_edit import FormulaEdit

if TYPE_CHECKING:
   from ....core.battle import BattleProject
   from ....core.document import Document
   from ...panel import PanelHost

## Item data role of a step row: its index in the pipeline.
STEP_ROLE = QtCore.Qt.ItemDataRole.UserRole
## Points table columns.
POINT_COLUMNS = ["Point", "Holder", "Sources (in order)", "Lowest", "Highest", "Users"]
## Points table column of the name (read only).
POINT_NAME_COLUMN = 0
## Points table column of the holder (a combo).
POINT_HOLDER_COLUMN = 1
## Points table column of the sources.
POINT_SOURCES_COLUMN = 2
## Points table column of the range's lower end.
POINT_LO_COLUMN = 3
## Points table column of the range's upper end.
POINT_HI_COLUMN = 4
## Points table column of the user count (read only).
POINT_USERS_COLUMN = 5
## Separator of a point's sources in the table.
SOURCE_SEPARATOR = ","
## Trace table columns.
TRACE_COLUMNS = ["Step", "Variable", "Before", "Value", "What it does"]
## Trace table column of the value before a point's handlers.
TRACE_BEFORE_COLUMN = 2
## Trace table column of the step's value.
TRACE_VALUE_COLUMN = 3
## Combo text of "the species' first passive".
SPECIES_PASSIVE_TEXT = "(species' first)"
## Highest damage roll index the calculator offers (the engine clamps it below each roll's span).
MAX_ROLL = 255
## Lowest HP percentage the calculator offers.
MIN_HP_PCT = 1
## Variable of a new let step when no step is selected.
NEW_LET_VAR = "v"
## Expression of a new let step when no step is selected.
NEW_LET_EXPR = "0"
## Variable of a new roll step.
NEW_ROLL_VAR = "roll"
## Span of a new roll step (one value: the draw happens, its value is always 0).
NEW_ROLL_SPAN = "1"
## Text colour of a note that the clamp can engage.
CLAMP_COLOR = "#a06000"
## Text colour of a pipeline the engine refuses.
ERROR_COLOR = "#c03030"
## Text colour of an optional pipeline's engine default (its note and its steps).
DEFAULT_COLOR = "#909090"
## Stretch of the step column against the points / calculator column.
STEPS_STRETCH = 2
## Stretch of the points / calculator column.
RIGHT_STRETCH = 3
## Calculator form columns of (label, field) pairs.
CALC_PAIRS_PER_ROW = 3
## Grid columns of one (label, field) pair.
GRID_COLUMNS_PER_PAIR = 2


def _range_value(text: str) -> int | str:
   """!One end of a range as typed: an integer or a constant name.
   @param text  the text
   @return int or str
   """
   text = text.strip()
   try:
      return int(text)
   except ValueError:
      return text


def _range_text(rng: Any) -> tuple[str, str]:
   """!A [lo, hi] range as two texts.
   @param rng  the range, or None
   @return (lo, hi), ("", "") for none
   """
   if isinstance(rng, (list, tuple)) and len(rng) == pipelines.RANGE_LEN:
      return str(rng[0]), str(rng[1])
   return "", ""


class PipelinesPointsPanel(BattlePanel):
   """!Pipeline steps with their analysed ranges, the points table and the damage calculator.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "pipelines"
   ## See EditorPanel.title.
   title = "Pipelines & Points"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the step list, the step editor, the points table and the calculator.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Index of the selected step, or None.
      self.selected_step = None
      ## The analysed rows of the shown pipeline (pipeline_report()), by step index.
      self.report = {}
      ## The last calculator result (core.pipelines.DamageTrace), or None.
      self.result = None
      lay = QtWidgets.QHBoxLayout(self)
      lay.addLayout(self._build_steps(), STEPS_STRETCH)
      ## The calculator and the points, one tab each (the calculator's trace needs the height).
      self.right_tabs = QtWidgets.QTabWidget()
      self.right_tabs.addTab(self._build_calculator(), "Damage calculator")
      ## The points group.
      self.points_box = self._build_points()
      self.right_tabs.addTab(self.points_box, "Points")
      right = QtWidgets.QVBoxLayout()
      right.addWidget(self.right_tabs, 1)
      right.addWidget(self.errors)
      lay.addLayout(right, RIGHT_STRETCH)
      split_box(lay)   # [RZ] steps | calculator and points

   # -- building -------------------------------------------------------------------------

   def _build_steps(self) -> QtWidgets.QVBoxLayout:
      """!The pipeline picker, the step list and the step editor.
      @return the column's layout
      """
      ## Pipeline picker.
      self.pipeline = QtWidgets.QComboBox()
      self.pipeline.currentIndexChanged.connect(lambda *_a: self._pipeline_chosen())
      ## The pipeline's inputs and outputs.
      self.contract = QtWidgets.QLabel()
      self.contract.setWordWrap(True)
      ## The pipeline's steps (drag to reorder).
      self.step_list = QtWidgets.QListWidget()
      self.step_list.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
      self.step_list.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
      self.step_list.currentRowChanged.connect(lambda row: self._step_chosen(row))
      self.step_list.model().rowsMoved.connect(lambda _p, start, _end, _d, row: self._step_dropped(start, row))
      ## "engine default (plain odds)" when the ruleset leaves the shown optional pipeline out, else hidden.
      self.default_state = QtWidgets.QLabel()
      self.default_state.setStyleSheet(f"color: {DEFAULT_COLOR};")
      ## Gives an optional pipeline back to the engine (core.pipelines.reset_pipeline()).
      self.reset_button = button("Engine default", lambda: self.reset_pipeline(),
                                 "Leave this pipeline out of the ruleset: the engine runs its default steps")
      ## Why the pipeline is not analysed (the ruleset compiler's message), or empty.
      self.pipeline_error = QtWidgets.QLabel()
      self.pipeline_error.setWordWrap(True)
      self.pipeline_error.setStyleSheet(f"color: {ERROR_COLOR};")
      col = QtWidgets.QVBoxLayout()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Pipeline"))
      row.addWidget(self.pipeline, 1)
      col.addLayout(row)
      col.addWidget(self.contract)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.default_state, 1)
      row.addWidget(self.reset_button)
      col.addLayout(row)
      col.addWidget(self.step_list, 1)
      col.addWidget(self.pipeline_error)
      row = QtWidgets.QHBoxLayout()
      for kind in pipelines.STEP_KINDS:
         row.addWidget(button(f"Add {kind}", lambda k=kind: self.add_step(k), f"Add a {kind} step after the "
                                                                              "selected one"))
      col.addLayout(row)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Remove", lambda: self.remove_step(), "Remove the selected step"))
      row.addWidget(button("Up", lambda: self.move_step(-1), "Run the selected step earlier"))
      row.addWidget(button("Down", lambda: self.move_step(1), "Run the selected step later"))
      col.addLayout(row)
      col.addWidget(self._build_step_editor())
      return col

   def _build_step_editor(self) -> QtWidgets.QGroupBox:
      """!The selected step's fields and analysis.
      @return the group
      """
      box = QtWidgets.QGroupBox("Step")
      ## The selected step's kind.
      self.step_kind = QtWidgets.QLabel()
      ## The variable it sets (let, roll) or runs the point on (point).
      self.step_var = QtWidgets.QLineEdit()
      self.step_var.editingFinished.connect(lambda: self._var_edited())
      ## The let's expression or the roll's span.
      self.step_expr = FormulaEdit()
      self.step_expr.editingFinished.connect(lambda: self._expr_edited())
      ## The point a point step runs.
      self.step_point = QtWidgets.QComboBox()
      self.step_point.activated.connect(lambda _i: self._set_step_key("point", self.step_point.currentText()))
      ## The let's clamp: lowest (an integer or a constant name; empty with highest: no clamp).
      self.step_lo = QtWidgets.QLineEdit()
      self.step_lo.editingFinished.connect(lambda: self._range_edited())
      ## The let's clamp: highest.
      self.step_hi = QtWidgets.QLineEdit()
      self.step_hi.editingFinished.connect(lambda: self._range_edited())
      ## The step's analysed range.
      self.step_analysed = QtWidgets.QLabel()
      self.step_analysed.setWordWrap(True)
      ## Whether the let's clamp can engage.
      self.step_clamp = QtWidgets.QLabel()
      self.step_clamp.setWordWrap(True)
      ## The expression field's label (Expression / Span / Point).
      self.expr_label = QtWidgets.QLabel("Expression")
      rng = QtWidgets.QHBoxLayout()
      rng.addWidget(self.step_lo)
      rng.addWidget(QtWidgets.QLabel("to"))
      rng.addWidget(self.step_hi)
      expr = QtWidgets.QHBoxLayout()
      expr.addWidget(self.step_expr, 1)
      expr.addWidget(self.step_point, 1)
      form = QtWidgets.QFormLayout(box)
      form.addRow("Kind", self.step_kind)
      form.addRow("Variable", self.step_var)
      form.addRow(self.expr_label, expr)
      ## The range row's label (hidden with the row for point and roll steps).
      self.range_label = QtWidgets.QLabel("Clamp")
      form.addRow(self.range_label, rng)
      form.addRow("Analysed", self.step_analysed)
      form.addRow("", self.step_clamp)
      return box

   def _build_points(self) -> QtWidgets.QWidget:
      """!The points table and its buttons.
      @return the page
      """
      box = QtWidgets.QWidget()
      ## One row per point, in id order.
      self.points = QtWidgets.QTableWidget(0, len(POINT_COLUMNS))
      self.points.setHorizontalHeaderLabels(POINT_COLUMNS)
      self.points.verticalHeader().setVisible(False)
      self.points.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.points.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.points.horizontalHeader().setSectionResizeMode(POINT_SOURCES_COLUMN,
                                                          QtWidgets.QHeaderView.ResizeMode.Stretch)
      self.points.itemChanged.connect(lambda item: self._point_cell_changed(item))
      ## Holder combos of the points table, by row.
      self.holder_combos = []
      lay = QtWidgets.QVBoxLayout(box)
      reserved = "; ".join(f"{n}: {text}" for n, text in pipelines.reserved_points().items())
      note = QtWidgets.QLabel("Sources run in the order listed, then their handlers; the point's range clamps "
                              "its result once at the end. Hover over Users to see what uses a point. Reserved "
                              f"point names (declare one to use it) - {reserved}")
      note.setWordWrap(True)
      lay.addWidget(note)
      lay.addWidget(self.points, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add point...", lambda: self.add_point(), "Add a point (its id is the next one)"))
      row.addWidget(button("Remove point", lambda: self.remove_point(),
                           "Remove the selected point (refused while a step or handler uses it)"))
      row.addStretch(1)
      lay.addLayout(row)
      return box

   def _calc_combo(self) -> QtWidgets.QComboBox:
      """!A calculator combo that recomputes when changed.
      @return QComboBox
      """
      c = QtWidgets.QComboBox()
      c.activated.connect(lambda _i: self.calculate())
      return c

   def _calc_spin(self, lo: int, hi: int, value: int) -> QtWidgets.QSpinBox:
      """!A calculator spin box that recomputes when changed.
      @param lo     minimum
      @param hi     maximum
      @param value  starting value
      @return QSpinBox
      """
      s = QtWidgets.QSpinBox()
      s.setRange(lo, hi)
      s.setValue(value)
      s.valueChanged.connect(lambda _v: self.calculate())
      return s

   def _calc_check(self, text: str) -> QtWidgets.QCheckBox:
      """!A calculator check box that recomputes when changed.
      @param text  label
      @return QCheckBox
      """
      b = QtWidgets.QCheckBox(text)
      b.toggled.connect(lambda _on: self.calculate())
      return b

   def _build_calculator(self) -> QtWidgets.QWidget:
      """!The damage calculator: its inputs, the result and the trace.
      @return the page
      """
      box = QtWidgets.QWidget()
      # The stage spins follow the move's stats' stage ranges at every calculation (_fit_stages()).
      stage_max = engine.tool("battle_compiler").STAGE_LIMIT
      ## Attacking species.
      self.attacker = self._calc_combo()
      ## Defending species.
      self.defender = self._calc_combo()
      ## The move (damaging moves only).
      self.move = self._calc_combo()
      # levels to rules.level_max (_fill_calculator_choices(); S11: no fixed range)
      ## Attacker level.
      self.level = self._calc_spin(1, battle.level_max(None), pipelines.DEFAULT_LEVEL)
      ## Defender level (0: the attacker's).
      self.defender_level = self._calc_spin(0, battle.level_max(None), 0)
      self.defender_level.setSpecialValueText("same")
      ## The damage roll (0 lowest; clamped below each roll's span).
      self.roll = self._calc_spin(0, MAX_ROLL, 0)
      ## Critical hit.
      self.crit = self._calc_check("Critical hit")
      ## Spread hit (several targets).
      self.spread = self._calc_check("Spread")
      ## Weather.
      self.weather = self._calc_combo()
      ## The attacker's status.
      self.status = self._calc_combo()
      ## The attacker's passive.
      self.passive = self._calc_combo()
      ## The attacker's held item.
      self.item = self._calc_combo()
      ## The attacker's trait.
      self.attacker_trait = self._calc_combo()
      ## The defender's trait.
      self.defender_trait = self._calc_combo()
      ## Every stat's gene value of both creatures.
      # (the genes' and training's maximums follow the record layout's widths: _fill_calculator_choices())
      self.genes = self._calc_spin(0, record.gene_max(None), 0)
      ## Every stat's training value of both creatures.
      self.training = self._calc_spin(0, record.training_max(None), 0)
      ## The attacker's HP in percent.
      self.hp_pct = self._calc_spin(MIN_HP_PCT, pipelines.PERCENT, pipelines.PERCENT)
      ## Stage of the attacker's offense stat.
      self.offense_stage = self._calc_spin(-stage_max, stage_max, 0)
      ## Stage of the defender's defense stat.
      self.defense_stage = self._calc_spin(-stage_max, stage_max, 0)
      ## A volatile on the attacker (E13b: its point handlers run).
      self.attacker_volatile = self._calc_combo()
      ## A volatile on the defender.
      self.defender_volatile = self._calc_combo()
      ## A side condition on the attacker's side.
      self.attacker_side = self._calc_combo()
      ## A side condition on the defender's side (e.g. a screen).
      self.defender_side = self._calc_combo()
      ## Battlers active on the defender's side (side(X).active_count; up to the engine's positions).
      self.defender_active = self._calc_spin(1, turn_model.position_limits()[0], pipelines.SIDE_ACTIVE)
      ## The damage dealt (or why there is none).
      self.damage = QtWidgets.QLabel()
      font = self.damage.font()
      font.setBold(True)
      self.damage.setFont(font)
      self.damage.setWordWrap(True)
      ## The pipeline's inputs.
      self.inputs_line = QtWidgets.QLabel()
      self.inputs_line.setWordWrap(True)
      ## The steps run.
      self.trace = QtWidgets.QTableWidget(0, len(TRACE_COLUMNS))
      self.trace.setHorizontalHeaderLabels(TRACE_COLUMNS)
      self.trace.verticalHeader().setVisible(False)
      self.trace.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.trace.horizontalHeader().setStretchLastSection(True)
      genes_label, training_label = self.term_label("genes"), self.term_label("training")
      fields = [(self.term_label("species", False, "Attacker"), self.attacker),
                (self.term_label("species", False, "Defender"), self.defender),
                (self.term_label("move"), self.move),
                (self.term_label("level"), self.level),
                (self.term_label("level", False, "Defender {}"), self.defender_level),
                (QtWidgets.QLabel("Roll"), self.roll),
                (self.term_label("weather"), self.weather),
                (self.term_label("status"), self.status),
                (self.term_label("passive"), self.passive),
                (self.term_label("item"), self.item),
                (self.term_label("trait"), self.attacker_trait),
                (self.term_label("trait", False, "Defender {}"), self.defender_trait),
                (genes_label, self.genes),
                (training_label, self.training),
                (QtWidgets.QLabel("HP %"), self.hp_pct),
                (QtWidgets.QLabel("Offense stage"), self.offense_stage),
                (QtWidgets.QLabel("Defense stage"), self.defense_stage),
                (QtWidgets.QLabel("Attacker volatile"), self.attacker_volatile),
                (QtWidgets.QLabel("Defender volatile"), self.defender_volatile),
                (QtWidgets.QLabel("Attacker side"), self.attacker_side),
                (QtWidgets.QLabel("Defender side"), self.defender_side),
                (QtWidgets.QLabel("Defender side battlers"), self.defender_active)]
      ## The per-stat input spins with their labels ({input: (label, spin)}): hidden when the layout has no role
      ## for the input (the stat formulas then read 0; S17).
      self.stat_input_rows = {"gene": (genes_label, self.genes), "training": (training_label, self.training)}
      grid = QtWidgets.QGridLayout()
      for i, (label, field) in enumerate(fields):
         r, c = divmod(i, CALC_PAIRS_PER_ROW)
         grid.addWidget(label, r, c * GRID_COLUMNS_PER_PAIR)
         grid.addWidget(field, r, c * GRID_COLUMNS_PER_PAIR + 1)
      checks = QtWidgets.QHBoxLayout()
      checks.addWidget(self.crit)
      checks.addWidget(self.spread)
      checks.addStretch(1)
      lay = QtWidgets.QVBoxLayout(box)
      lay.addLayout(grid)
      lay.addLayout(checks)
      lay.addWidget(self.damage)
      lay.addWidget(self.inputs_line)
      lay.addWidget(self.trace, 1)
      return box

   # -- reading --------------------------------------------------------------------------

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the ruleset.
      @return Document, or None
      """
      p = self.project()
      return p.ruleset if p is not None else None

   def ruleset_doc(self) -> Document | None:
      """!The ruleset Document.
      @return Document, or None
      """
      return self.current_document()

   def pipeline_name(self) -> str | None:
      """!The pipeline shown.
      @return name, or None
      """
      return self.pipeline.currentText() or None

   def step_dicts(self) -> list[Any]:
      """!The shown pipeline's steps as the engine runs them (nothing created): the ruleset's, or an optional
      pipeline's default steps (core.pipelines.shown_steps()).
      @return the list ([] when there are none)
      """
      doc, name = self.ruleset_doc(), self.pipeline_name()
      if doc is None or name is None:
         return []
      return pipelines.shown_steps(doc, name)

   def shows_default(self) -> bool:
      """!Whether the shown pipeline is an optional one the ruleset leaves out.
      @return True when the engine's default steps are shown
      """
      doc, name = self.ruleset_doc(), self.pipeline_name()
      return doc is not None and name is not None and pipelines.is_engine_default(doc, name)

   def refresh(self) -> None:
      """!Re-reads the pipeline, the points and the calculator's choices; recomputes.
      @return None
      """
      self.update_terms()
      p = self.project()
      self._filling = True
      try:
         names = pipelines.pipeline_names() if p is not None else []
         if [self.pipeline.itemText(i) for i in range(self.pipeline.count())] != names:
            keep = self.pipeline.currentText()
            set_combo(self.pipeline, names, keep if keep in names else (names[0] if names else None))
         self._fill_steps()
         self._fill_points()
         self._fill_calculator_choices()
      finally:
         self._filling = False
      for w in (self.step_list, self.points):
         set_enabled(w, p is not None)   # read-only lists still scroll
      self.calculate()
      self.show_errors()

   def _fill_steps(self) -> None:
      """!The contract line, the step list (with analysed ranges) and the step editor.
      @return None
      """
      p, name = self.project(), self.pipeline_name()
      steps = self.step_dicts()
      self.report = {}
      error = None
      if p is not None and name is not None:
         rows, error, _own = pipelines.pipeline_report(p, name)
         if len(rows) == len(steps):   # the report is of these steps (it is empty when the ruleset fails)
            self.report = {r["index"]: r for r in rows}
         ins, outs = pipelines.pipeline_inputs(name), pipelines.pipeline_outputs(name)
         self.contract.setText(f"Inputs: {', '.join(ins)}. Sets: {', '.join(outs)} (the first is the result).")
      else:
         self.contract.setText("")
      default = self.shows_default()
      optional = name is not None and name in pipelines.optional_pipelines()
      note = (pipelines.default_note(name) + ": the ruleset leaves it out; an edit starts from these steps"
              if default and name is not None else "")
      self.default_state.setText(note)
      self.default_state.setVisible(default)
      self.reset_button.setVisible(optional)
      self.reset_button.setEnabled(optional and not default)
      self.pipeline_error.setText(f"Not analysed: {error}" if error else "")
      self.pipeline_error.setVisible(bool(error))
      if self.selected_step is not None and not 0 <= self.selected_step < len(steps):
         self.selected_step = len(steps) - 1 if steps else None
      self.step_list.clear()
      for i, s in enumerate(steps):
         try:
            text = pipelines.step_text(s)
         except DocumentError as e:
            text = f"(not a step: {e})"
         row = self.report.get(i)
         if row is not None:
            text += f"   -> [{row['bounds'][0]}, {row['bounds'][1]}]" + ("  clamps" if row["clamp_active"] else "")
         item = QtWidgets.QListWidgetItem(f"{i}  {text}")
         item.setData(STEP_ROLE, i)
         if default:
            item.setForeground(QtGui.QBrush(QtGui.QColor(DEFAULT_COLOR)))   # the engine's steps, not the ruleset's
         self.step_list.addItem(item)
      if self.selected_step is not None:
         self.step_list.setCurrentRow(self.selected_step)
      self._fill_step_editor()

   def _fill_step_editor(self) -> None:
      """!Shows the selected step in the editor.
      @return None
      """
      steps = self.step_dicts()
      i = self.selected_step
      step = steps[i] if i is not None and 0 <= i < len(steps) and isinstance(steps[i], dict) else None
      try:
         kind = pipelines.step_kind(step) if step is not None else None
      except DocumentError:
         kind = None
      doc = self.ruleset_doc()
      self.step_kind.setText(kind or "")
      var_key = {"let": "let", "point": "on", "roll": "roll"}.get(kind)
      self.step_var.setText(str(step.get(var_key, "")) if kind else "")
      self.expr_label.setText({"let": "Expression", "point": "Point", "roll": "Span"}.get(kind, "Expression"))
      name = self.pipeline_name()
      # what the step may name: the inputs and the variables set before it (core.expressions)
      self.step_expr.set_names(expressions.pipeline_names(self.project(), name, i) if name and kind else None)
      self.step_expr.setText(str(step.get("expr" if kind == "let" else "span", "")) if kind in ("let", "roll")
                             else "")
      self.step_expr.setVisible(kind != "point")
      self.step_point.setVisible(kind == "point")
      set_combo(self.step_point, pipelines.point_names(doc) if doc is not None else [],
                step.get("point") if kind == "point" else None)
      lo, hi = _range_text(step.get("range") if kind == "let" else None)
      self.step_lo.setText(lo)
      self.step_hi.setText(hi)
      for w in (self.range_label, self.step_lo, self.step_hi):
         w.setVisible(kind == "let")
      for w in (self.step_var, self.step_expr, self.step_point, self.step_lo, self.step_hi):
         w.setEnabled(kind is not None)
      row = self.report.get(i) if i is not None else None
      if row is None:
         self.step_analysed.setText("" if kind is None else "(the ruleset does not compile: no analysis)")
         self.step_clamp.setText("")
         return
      bounds = f"[{row['bounds'][0]}, {row['bounds'][1]}]"
      if row["analysed"] is not None:
         a = row["analysed"]
         self.step_analysed.setText(f"[{a[0]}, {a[1]}] before the clamp; {row['var']} is {bounds} after it")
      else:
         self.step_analysed.setText(f"{row['var']} is {bounds} after this step")
      if row["range"] is None:
         self.step_clamp.setText("")
      elif row["clamp_active"]:
         self.step_clamp.setText("The clamp can engage: some values are cut to the range.")
         self.step_clamp.setStyleSheet(f"color: {CLAMP_COLOR};")
      else:
         self.step_clamp.setText("The clamp never engages (the value always fits).")
         self.step_clamp.setStyleSheet("")

   def _fill_points(self) -> None:
      """!The points table.
      @return None
      """
      p, doc = self.project(), self.ruleset_doc()
      names = pipelines.point_names(doc) if doc is not None else []
      reserved = pipelines.reserved_points()
      keep = self._selected_point()
      self.points.setRowCount(len(names))
      self.holder_combos = []
      read_only = ~QtCore.Qt.ItemFlag.ItemIsEditable
      for r, name in enumerate(names):
         pt = pipelines.point_entry(doc, name)
         users = pipelines.point_users(doc, name, p.battle)
         lo, hi = _range_text(pt.get("range"))
         sources = pt.get("sources") or []
         cells = [name, "", (SOURCE_SEPARATOR + " ").join(str(s) for s in sources), lo, hi, str(len(users))]
         for c, text in enumerate(cells):
            item = QtWidgets.QTableWidgetItem(text)
            if c in (POINT_NAME_COLUMN, POINT_HOLDER_COLUMN, POINT_USERS_COLUMN):
               item.setFlags(item.flags() & read_only)
            if c == POINT_USERS_COLUMN:
               item.setToolTip("\n".join(users) or "Nothing uses this point")
            if c == POINT_SOURCES_COLUMN:
               item.setToolTip("One of: " + ", ".join(pipelines.point_sources()))
            if c == POINT_NAME_COLUMN and name in reserved:
               item.setToolTip(f"{name}: {reserved[name]}")
            self.points.setItem(r, c, item)
         box = QtWidgets.QComboBox()
         box.addItems(pipelines.holders())
         box.setCurrentText(str(pt.get("holder", pipelines.DEFAULT_HOLDER)))
         box.activated.connect(lambda _i, n=name, b=box: self.set_point(n, "holder", b.currentText()))
         self.points.setCellWidget(r, POINT_HOLDER_COLUMN, box)
         self.holder_combos.append(box)
      self.points.resizeColumnsToContents()
      if keep in names:
         self.points.selectRow(names.index(keep))

   def _fill_calculator_choices(self) -> None:
      """!The calculator's combos from the compiled data (kept when the data does not compile).
      @return None
      """
      p = self.project()
      doc = p.battle if p is not None else None
      set_spin_max(self.genes, record.gene_max(doc))
      set_spin_max(self.training, record.training_max(doc))
      for key, (label, box) in self.stat_input_rows.items():
         held = record.has_stat_input(doc, key)
         label.setVisible(held)
         box.setVisible(held)
         if not held:
            set_spin(box, 0)   # the stat formulas read 0 without the role
      for box in (self.level, self.defender_level):
         set_spin_max(box, battle.level_max(p.structure if p is not None else None))
      compiled = p.compile()[0] if p is not None else None
      if compiled is None:
         return
      bc = engine.tool("battle_compiler")
      names = compiled["names"]
      species = list(names["species"])
      cats = compiled["categories"]
      moves = [m for m, d in zip(names["moves"], compiled["moves"]) if cats[d["category"]]["offense"] != bc.NONE8]

      def fill(box: QtWidgets.QComboBox, items: list[str], default: str | None) -> None:
         """!Refills a combo, keeping its choice when it still exists."""
         keep = box.currentText()
         set_combo(box, items, keep if keep in items else default)

      fill(self.attacker, species, species[0] if species else None)
      fill(self.defender, species, species[1] if len(species) > 1 else (species[0] if species else None))
      fill(self.move, moves, moves[0] if moves else None)
      for box, kind in ((self.weather, "weathers"), (self.status, "statuses"), (self.item, "items"),
                        (self.attacker_trait, "traits"), (self.defender_trait, "traits")):
         fill(box, [NONE_TEXT] + list(names[kind]), NONE_TEXT)
      fill(self.passive, [SPECIES_PASSIVE_TEXT] + list(names["passives"]), SPECIES_PASSIVE_TEXT)
      for box, kind in ((self.attacker_volatile, "volatiles"), (self.defender_volatile, "volatiles"),
                        (self.attacker_side, "side_conditions"), (self.defender_side, "side_conditions")):
         fill(box, [NONE_TEXT] + list(names.get(kind, [])), NONE_TEXT)

   # -- calculator -----------------------------------------------------------------------

   def calculator_args(self) -> dict[str, Any]:
      """!The calculator's inputs as core.pipelines.damage_trace() arguments.
      @return keyword arguments (project excluded)
      """
      def choice(box: QtWidgets.QComboBox, none: str = NONE_TEXT) -> str | None:
         """!A combo's choice, None for "none"."""
         text = box.currentText()
         return None if text in ("", none) else text

      return {"attacker": self.attacker.currentText(), "defender": self.defender.currentText(),
              "move": self.move.currentText(), "level": self.level.value(), "roll": self.roll.value(),
              "crit": self.crit.isChecked(), "weather": choice(self.weather), "status": choice(self.status),
              "spread": self.spread.isChecked(), "attacker_trait": choice(self.attacker_trait),
              "defender_trait": choice(self.defender_trait), "passive": choice(self.passive, SPECIES_PASSIVE_TEXT),
              "item": choice(self.item), "genes": self.genes.value(), "training": self.training.value(),
              "hp_pct": self.hp_pct.value(), "offense_stage": self.offense_stage.value(),
              "defense_stage": self.defense_stage.value(),
              "defender_level": self.defender_level.value() or None,
              "attacker_volatiles": [n for n in (choice(self.attacker_volatile),) if n is not None],
              "defender_volatiles": [n for n in (choice(self.defender_volatile),) if n is not None],
              "attacker_side": [n for n in (choice(self.attacker_side),) if n is not None],
              "defender_side": [n for n in (choice(self.defender_side),) if n is not None],
              "defender_active": self.defender_active.value()}

   def _fit_stages(self, p: BattleProject | None) -> None:
      """!Gives the offense / defense stage spins the ranges of the move's stats' stages (0 only for a stat
      without a stage), without emitting edits.
      @param p  BattleProject, or None
      @return None
      """
      ranges = pipelines.move_stage_ranges(p, self.move.currentText()) if p is not None else None
      if ranges is None:
         return
      for box, (lo, hi) in zip((self.offense_stage, self.defense_stage), ranges):
         box.blockSignals(True)
         box.setRange(lo, hi)
         box.blockSignals(False)

   def calculate(self) -> pipelines.DamageTrace | None:
      """!Runs the damage calculator and shows the trace.
      @return the result, or None when it can't run
      """
      if self._filling:
         return None
      p = self.project()
      self.result = None
      self._fit_stages(p)
      args = self.calculator_args()
      if p is None or not args["attacker"] or not args["move"]:
         self.damage.setText("")
         self.inputs_line.setText("")
         self.trace.setRowCount(0)
         return None
      try:
         t = pipelines.damage_trace(p, **args)
      except (DocumentError, ValueError, KeyError, IndexError, TypeError) as e:   # odd data the compiler took
         self.damage.setText(f"No result: {e}")
         self.inputs_line.setText("")
         self.trace.setRowCount(0)
         return None
      self.result = t
      decisive = t.decisive   # local name: Doxygen 1.12 misreads "if t.x"
      typed = t.hit_type   # local names: Doxygen 1.12 misreads "if t.x"
      own = t.own_type
      self.damage.setText(f"Damage {t.damage}" + (f" (decisive type tier {decisive}: no pipeline runs)"
                                                   if decisive is not None else "")
                          + (f"; hits as {typed} (move_type point; its own type: {own})" if typed != own else ""))
      self.inputs_line.setText("Inputs: " + ", ".join(f"{k} {v}" for k, v in t.inputs.items()))
      steps = t.trace
      self.trace.setRowCount(len(steps))
      for r, (index, _kind, var, before, value, text) in enumerate(steps):
         for c, cell in enumerate((str(index), var, "" if before is None else str(before), str(value), text)):
            item = QtWidgets.QTableWidgetItem(cell)
            if c in (TRACE_BEFORE_COLUMN, TRACE_VALUE_COLUMN):
               item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.trace.setItem(r, c, item)
      self.trace.resizeColumnsToContents()
      return t

   # -- steps ----------------------------------------------------------------------------

   def _pipeline_chosen(self) -> None:
      """!Another pipeline was picked.
      @return None
      """
      if self._filling:
         return
      self.selected_step = 0 if self.step_dicts() else None
      self._filling = True
      try:
         self._fill_steps()
      finally:
         self._filling = False

   def _step_chosen(self, row: int) -> None:
      """!Another step was picked.
      @param row  list row
      @return None
      """
      if self._filling:
         return
      self.selected_step = row if row >= 0 else None
      self._filling = True
      try:
         self._fill_step_editor()
      finally:
         self._filling = False

   def _edit_ruleset(self, label: str, fn: Any) -> bool:
      """!Runs an edit of the ruleset through the host (one undo step); a refused one refreshes the page.
      @param label  undo label
      @param fn     callable
      @return True when the edit went through
      """
      doc = self.ruleset_doc()
      if doc is None:
         return False
      ok = self.host.run_edit(label, fn, doc)
      if not ok:
         self.host.changed()   # the fields show the stored values again
      return ok

   def add_step(self, kind: str) -> bool:
      """!Adds a step after the selected one: a let that keeps the selected step's variable, a point step on
      it (the first point), or a roll.
      @param kind  "let", "point" or "roll"
      @return True when added
      """
      doc, name = self.ruleset_doc(), self.pipeline_name()
      if doc is None or name is None:
         return False
      steps = self.step_dicts()
      i = self.selected_step
      var = None
      if i is not None and 0 <= i < len(steps) and isinstance(steps[i], dict):
         var = steps[i].get("on") if "point" in steps[i] else steps[i].get("let", steps[i].get("roll"))
      if kind == "let":
         step = pipelines.make_step("let", var or NEW_LET_VAR, var or NEW_LET_EXPR)
      elif kind == "point":
         points = pipelines.point_names(doc)
         if not points:
            self.host.show_status("The ruleset has no points: add one first.")
            return False
         step = pipelines.make_step("point", var or NEW_LET_VAR, points[0])
      else:
         step = pipelines.make_step("roll", NEW_ROLL_VAR, NEW_ROLL_SPAN)
      at = len(steps) if i is None else i + 1
      if self._edit_ruleset(f"Add {kind} step", lambda: pipelines.add_step(doc, name, step, at)):
         self.selected_step = at
         return True
      return False

   def reset_pipeline(self) -> bool:
      """!Gives the shown optional pipeline back to the engine (one undo step).
      @return True when the ruleset listed it
      """
      doc, name = self.ruleset_doc(), self.pipeline_name()
      if doc is None or name is None or pipelines.is_engine_default(doc, name):
         return False
      return self._edit_ruleset("Engine default pipeline", lambda: pipelines.reset_pipeline(doc, name))

   def remove_step(self) -> bool:
      """!Removes the selected step.
      @return True when removed
      """
      doc, name, i = self.ruleset_doc(), self.pipeline_name(), self.selected_step
      if doc is None or name is None or i is None:
         return False
      return self._edit_ruleset("Remove step", lambda: pipelines.remove_step(doc, name, i))

   def move_step(self, delta: int, index: int | None = None) -> bool:
      """!Moves a step up or down.
      @param delta  -1 earlier, +1 later (several steps: repeated)
      @param index  the step, or None for the selected one
      @return True when it moved
      """
      doc, name = self.ruleset_doc(), self.pipeline_name()
      i = self.selected_step if index is None else index
      if doc is None or name is None or i is None or delta == 0:
         return False
      step = 1 if delta > 0 else -1
      count = len(self.step_dicts())
      target = max(0, min(count - 1, i + delta))
      if target == i:
         return False

      def fn() -> None:
         """!Moves the step one place at a time (one undo step)."""
         for j in range(i, target, step):
            pipelines.move_step(doc, name, j, step)

      if self._edit_ruleset("Move step", fn):
         self.selected_step = target
         return True
      return False

   def _step_dropped(self, start: int, row: int) -> None:
      """!A step was dragged to another place in the list.
      @param start  its old row
      @param row    the row it was dropped before
      @return None
      """
      if self._filling:
         return
      target = row if row < start else row - 1   # the dragged row no longer counts below its old place
      if not self.move_step(target - start, start):
         self.host.changed()   # show the stored order again

   def _set_step_key(self, key: str, value: Any) -> bool:
      """!Changes one key of the selected step (one undo step).
      @param key    the key
      @param value  the value
      @return True when changed
      """
      if self._filling:
         return False
      doc, name, i = self.ruleset_doc(), self.pipeline_name(), self.selected_step
      steps = self.step_dicts()
      if doc is None or name is None or i is None or not 0 <= i < len(steps):
         return False
      if steps[i].get(key) == value:
         return False
      return self._edit_ruleset(f"Step {key}", lambda: pipelines.set_step(doc, name, i, key, value))

   def _var_edited(self) -> None:
      """!The variable field was edited.
      @return None
      """
      kind = self.step_kind.text()
      key = {"let": "let", "point": "on", "roll": "roll"}.get(kind)
      if key is not None:
         self._set_step_key(key, self.step_var.text().strip())

   def _expr_edited(self) -> None:
      """!The expression (or span) field was edited.
      @return None
      """
      kind = self.step_kind.text()
      if kind in ("let", "roll"):
         self._set_step_key("expr" if kind == "let" else "span", self.step_expr.text().strip())

   def _range_edited(self) -> None:
      """!A clamp field was edited (both empty: no clamp).
      @return None
      """
      if self.step_kind.text() != "let":
         return
      lo, hi = self.step_lo.text().strip(), self.step_hi.text().strip()
      if bool(lo) != bool(hi):
         return   # wait for the other end
      self._set_step_key("range", [_range_value(lo), _range_value(hi)] if lo else None)

   # -- points ---------------------------------------------------------------------------

   def _selected_point(self) -> str | None:
      """!The point of the selected table row.
      @return name, or None
      """
      rows = self.points.selectionModel().selectedRows() if self.points.selectionModel() else []
      item = self.points.item(rows[0].row(), POINT_NAME_COLUMN) if rows else None
      return item.text() if item is not None else None

   def set_point(self, name: str, key: str, value: Any) -> bool:
      """!Changes a point's holder, sources or range (one undo step).
      @param name   point name
      @param key    one of core.pipelines.POINT_KEYS
      @param value  the value
      @return True when changed
      """
      doc = self.ruleset_doc()
      if doc is None or pipelines.point_entry(doc, name).get(key) == value:
         return False
      return self._edit_ruleset(f"Point {key}", lambda: pipelines.set_point(doc, name, key, value))

   def _point_cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A sources or range cell was typed in.
      @param item  QTableWidgetItem
      @return None
      """
      if self._filling:
         return
      name = self.points.item(item.row(), POINT_NAME_COLUMN).text()
      c = item.column()
      if c == POINT_SOURCES_COLUMN:
         sources = [s.strip() for s in item.text().split(SOURCE_SEPARATOR) if s.strip()]
         self.set_point(name, "sources", sources)
      elif c in (POINT_LO_COLUMN, POINT_HI_COLUMN):
         lo = self.points.item(item.row(), POINT_LO_COLUMN).text()
         hi = self.points.item(item.row(), POINT_HI_COLUMN).text()
         if not lo.strip() or not hi.strip():
            self.host.show_status("A point's range needs both ends.")
            self.host.changed()
            return
         self.set_point(name, "range", [_range_value(lo), _range_value(hi)])

   def add_point(self, name: str | None = None) -> bool:
      """!Adds a point.
      @param name  its name, or None to ask
      @return True when added
      """
      doc = self.ruleset_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add point", "Name (lower-case):")
         if not ok or not name.strip():
            return False
      name = name.strip()
      return self._edit_ruleset("Add point", lambda: pipelines.add_point(doc, name))

   def remove_point(self, name: str | None = None) -> bool:
      """!Removes a point nothing uses (refused while a pipeline step or a handler uses it).
      @param name  the point, or None for the selected one
      @return True when removed
      """
      p, doc = self.project(), self.ruleset_doc()
      name = name or self._selected_point()
      if p is None or doc is None or name is None:
         return False
      battle_doc = p.battle
      return self._edit_ruleset("Remove point", lambda: pipelines.remove_point(doc, name, battle_doc))
