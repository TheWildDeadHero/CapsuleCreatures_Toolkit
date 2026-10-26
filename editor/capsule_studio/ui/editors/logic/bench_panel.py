"""!Logic > Bench (D-23 §3.3): battle scenarios (capsule.bench/1, the game's
bench/*.json) run through the engine's compiled bench, with core.bench.

Layout, left to right:
- the scenario list (the game's bench/ folder) with New...;
- the scenario form: name, description, format, seed, field weather,
  parties (each a party of the battle data or its own members, picked
  from the data's names; members' and pokes' resources as "ep 5,
  uses 3/3"), battler pokes (hp, status, volatiles, stages, item,
  resources), scripted choices per turn and answers to effect requests, the
  stop condition and the traces. Every change is one undo step of the
  scenario's Document (Save writes it);
- the run side: the generator (default and the reference repo's
  compat/generators.json: core.bench.generators()), Run, Cancel, "Run on
  save" (a save of the battle data, its sources or the scenario runs it
  again), the progress, an event list (transcript lines with draw markers:
  the random draws made before the line; RNG, VM and battle event rows)
  with type filters and a text filter, "Save as expected" and Check (the
  transcript against the scenario's expected one: pass / fail).

Activating a VM (or effect-made RNG) row opens Logic > Effects on that
owner, in the text view, at the record's source line and column.

The bench builds from the battle data as saved (core.bench.Runner, run in
a thread so the window stays live). Without CMake or a C++ compiler the
page says what is needed; editing, validating and saving still work.
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import bench, logic
from ....core.document import Document, DocumentError
from ...widgets import DEBOUNCE_MS, button, report_failure
from ..battle_common import BattlePanel, set_check, set_combo, set_spin

if TYPE_CHECKING:
   from ....core.battle import BattleProject
   from ...panel import PanelHost

## The generator combo's tooltip.
RNG_TIP = "default: the engine's generator; others: the ones the reference repo declares (compat/generators.json)"
## Combo text: the key is left out (the bench's default).
DEFAULT_TEXT = "(default)"
## Combo text: no weather.
NO_WEATHER = "(none)"
## Largest seed the form's spin box takes (Qt spin boxes are signed 32-bit).
SEED_MAX = 2 ** 31 - 1
## Largest count of a small field (weather turns, stop count): the bench's 16-bit stop limit.
COUNT_MAX = 0xFFFF
## Weather turns the field may start with (an 8-bit counter).
TURNS_MAX = 0xFF
## Event list columns.
EVENT_COLUMNS = ("#", "Turn", "Draws", "Kind", "What happened")
## Event list column of the record index.
INDEX_COLUMN = 0
## Event list column of the draw marker.
DRAWS_COLUMN = 2
## Event list column of the text.
TEXT_COLUMN = 4
## Item data role of an event row: the record's index in the run's output.
RECORD_ROLE = QtCore.Qt.ItemDataRole.UserRole
## Event list type filters: (label, record types).
FILTERS = (("Transcript", ("line",)), ("RNG", ("rng",)), ("VM", ("vm",)), ("Events", ("event",)),
           ("Other", ("request", bench.TRAPPED_KIND, "note", "stop", "error")))
## Filters on before the first run: transcript, RNG and VM rows, and the rest but battle events.
FILTERS_ON = ("Transcript", "RNG", "VM", "Other")
## Background of a transcript line with draws before it (the draw marker).
DRAW_COLOUR = "#f6e39a"
## Text colour by row type.
KIND_COLOURS = {"rng": "#8a6d00", "vm": "#2c5aa0", "event": "#6f7a85", "error": "#c03030", "note": "#b06010",
                "request": "#6a3fa0", "stop": "#2a7a2a", bench.TRAPPED_KIND: "#a03f6a"}
## Style of the toolchain banner.
BANNER_STYLE = "background: #fbe3c0; color: #5a3a00; padding: 6px; border-radius: 3px;"
## Style of a passing check.
PASS_STYLE = "color: #2a7a2a; font-weight: bold;"
## Style of a failing check.
FAIL_STYLE = "color: #c03030; font-weight: bold;"
## Milliseconds a save waits before "Run on save" runs (several files saved together run once).
SAVE_RUN_MS = 250
## Layout stretches of the three columns (scenarios, form, run side).
COLUMN_STRETCH = (0, 1, 1)
## Splitter starting widths of the three columns, pixels.
COLUMN_WIDTHS = (190, 520, 640)
## Headings of the party table.
PARTY_HEADINGS = ("Side", "Controller", "Flags", "Party of the data")
## Headings of the member table.
MEMBER_HEADINGS = ("Species", "Level", "Item", "Trait", "Moves", "HP", "Status", "Resources")
## Headings of the poke table.
POKE_HEADINGS = ("Party", "Member", "HP", "Status", "Status turns", "Confusion", "Item", "Volatiles", "Stages",
                 "Resources")
## Rows a form table shows before it scrolls.
TABLE_ROWS = 4
## Height of one table row, pixels (with the header: the tables' height).
ROW_HEIGHT = 26
## Height of the choices and answers boxes, pixels.
TEXT_BOX_HEIGHT = 70

## Undo labels of add_row() by table.
ADD_LABELS = {"parties": "Add party", "members": "Add member", "pokes": "Add poke"}
## Undo labels of remove_row() by table.
REMOVE_LABELS = {"parties": "Remove party", "members": "Remove member", "pokes": "Remove poke"}

## A function giving the names a table column picks from (None: free text).
ChoicesFn = Callable[[int], Sequence[str] | None]


class NameDelegate(QtWidgets.QStyledItemDelegate):
   """!Edits a table cell with an editable combo box of the battle data's names (for the columns that have
   names; other cells edit as text)."""

   def __init__(self, choices: ChoicesFn, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the delegate.
      @param choices  column -> names, or None for free text
      @param parent   the table
      """
      super().__init__(parent)
      ## Column -> names.
      self.choices = choices

   def createEditor(self, parent: QtWidgets.QWidget, option: QtWidgets.QStyleOptionViewItem,
                    index: QtCore.QModelIndex) -> QtWidgets.QWidget:
      """!A combo box for a name column, else the default editor.
      @param parent  editor parent
      @param option  style option
      @param index   the cell
      @return the editor
      """
      names = self.choices(index.column())
      if names is None:
         return super().createEditor(parent, option, index)
      c = QtWidgets.QComboBox(parent)
      c.setEditable(True)
      c.addItems([""] + list(names))
      return c

   def setEditorData(self, editor: QtWidgets.QWidget, index: QtCore.QModelIndex) -> None:
      """!Shows the cell's text in the editor.
      @param editor  the editor
      @param index   the cell
      @return None
      """
      if isinstance(editor, QtWidgets.QComboBox):
         editor.setCurrentText(str(index.data() or ""))
      else:
         super().setEditorData(editor, index)

   def setModelData(self, editor: QtWidgets.QWidget, model: QtCore.QAbstractItemModel,
                    index: QtCore.QModelIndex) -> None:
      """!Writes the editor's text to the cell.
      @param editor  the editor
      @param model   the table's model
      @param index   the cell
      @return None
      """
      if isinstance(editor, QtWidgets.QComboBox):
         model.setData(index, editor.currentText())
      else:
         super().setModelData(editor, model, index)


## Jobs still running: kept until they end, so closing a page never destroys a running thread.
_RUNNING: set[QtCore.QThread] = set()
## Whether finish_jobs() runs when the application quits.
_QUIT_HOOKED = False


def keep_alive(job: QtCore.QThread) -> None:
   """!Keeps a job until it ends; when the application quits first, the job is cancelled and waited for.
   @param job  a BenchJob not started yet
   @return None
   """
   global _QUIT_HOOKED
   app = QtCore.QCoreApplication.instance()
   if app is not None and not _QUIT_HOOKED:
      app.aboutToQuit.connect(lambda: finish_jobs())
      _QUIT_HOOKED = True
   _RUNNING.add(job)
   job.finished.connect(lambda: _RUNNING.discard(job))


def finish_jobs() -> None:
   """!Cancels every running job and waits for it (the application quits).
   @return None
   """
   for job in list(_RUNNING):
      job.on_cancel()
      job.wait()
   _RUNNING.clear()


def _no_cancel() -> None:
   """!What a job without a Runner does on cancel: nothing.
   @return None
   """


class BenchJob(QtCore.QThread):
   """!Runs core.bench work (a Runner's build and run) off the window's thread; reports by signals.

   @var result
   What the work returned (a BenchRun), or None.
   @var error
   Why it failed, or None.
   """

   ## (phase, text) progress from the work.
   progress = QtCore.Signal(str, str)

   def __init__(self, work: Callable[[bench.Progress], Any], parent: QtCore.QObject | None = None) -> None:
      """!Creates the job.
      @param work    callable(progress) doing the work
      @param parent  owner
      """
      super().__init__(parent)
      ## The work.
      self.work = work
      ## What the work returned, or None.
      self.result = None
      ## Why it failed (a BenchError), or None.
      self.error: Exception | None = None
      ## Cancels the work (the Runner's cancel()); a callable taking nothing.
      self.on_cancel = _no_cancel

   def run(self) -> None:
      """!Does the work (in the thread).
      @return None
      """
      try:
         self.result = self.work(lambda phase, text: self.progress.emit(phase, text))
      except Exception as e:   # every failure is reported to the panel, never lost in the thread
         self.error = e


class BenchPanel(BattlePanel):
   """!The battle test bench (see the module docstring).

   Attributes are documented where __init__ sets them; the ones below are repeated here because Doxygen's
   Python parser otherwise reports their later uses as undocumented members.

   @var selected
   The selected scenario file, or None.
   @var last_run
   The latest finished run (core.bench.BenchRun), or None.
   @var job
   The job running now, or None.
   @var documents
   The open scenario Documents by file (the project's).
   @var runner
   The Runner of the current job.
   @var missing
   What the bench's build lacks here (empty: it can build).
   @var _watched
   Documents listened to for "Run on save": [(Document, callback)].
   @var _paths
   The scenario files the list shows, in row order.
   @var _shown
   Event rows shown: record index per row.
   @var errors
   The page's message line (BattlePanel's compile result line).
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "bench"
   ## See EditorPanel.title.
   title = "Bench"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the page.
      @param host    PanelHost with a BattleProject as project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected scenario file, or None.
      self.selected: Path | None = None
      ## The latest finished run, or None.
      self.last_run: bench.BenchRun | None = None
      ## The job running now, or None.
      self.job: BenchJob | None = None
      ## Makes the Runner a run uses (tests give a fake one).
      self.runner_factory = bench.Runner
      ## The Runner of the current job.
      self.runner: Any = None
      ## What the bench's build lacks here (core.bench.toolchain()); checked once, again with "Check again".
      self.toolchain_check = bench.toolchain
      ## What the build lacks (empty: it can build).
      self.missing: list[str] = []
      ## Documents this page listens to for "Run on save": [(Document, callback)].
      self._watched = []
      ## Party row selected in the party table.
      self._party_row = 0
      ## Event rows shown: record index per row.
      self._shown: list[int] = []
      ## The scenario files the list shows, in row order.
      self._paths: list[Path] = []

      # -- scenarios --
      ## The game's scenarios.
      self.scenario_list = QtWidgets.QListWidget()
      self.scenario_list.currentRowChanged.connect(lambda _r: self._scenario_picked())
      left = QtWidgets.QWidget()
      ll = QtWidgets.QVBoxLayout(left)
      ll.setContentsMargins(0, 0, 0, 0)
      ll.addWidget(QtWidgets.QLabel("Scenarios (bench/)"))
      ll.addWidget(self.scenario_list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("New...", lambda: self.new_scenario(), "A scenario from the battle data's parties"))
      row.addWidget(button("Reload", lambda: self.refresh(), "Read the bench folder again"))
      ll.addLayout(row)
      ## Saves the selected scenario.
      self.save_button = button("Save scenario", lambda: self.save_scenario(), "Write the scenario's file")
      ll.addWidget(self.save_button)
      ## Offers to rename the poke keys the bench no longer takes (shown while a scenario writes one).
      self.migrate_button = button("Migrate scenarios", lambda: self.migrate_scenarios(),
                                   "Rename the retired poke keys (status_turns -> status_counter, escalation -> "
                                   "status_aux) in every scenario; Save all writes them")
      self.migrate_button.hide()
      ll.addWidget(self.migrate_button)

      # -- form --
      self._build_form()

      # -- run --
      self._build_run_side()

      split = QtWidgets.QSplitter()
      for w, stretch in zip((left, self.form_area, self.run_side), COLUMN_STRETCH):
         split.addWidget(w)
         split.setStretchFactor(split.count() - 1, stretch)
      split.setSizes(list(COLUMN_WIDTHS))
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(self.banner)
      lay.addWidget(split, 1)
      lay.addWidget(self.errors)
      self.check_toolchain()

   # -- building the page ---------------------------------------------------------------------------------------------

   def _table(self, headings: Sequence[str], choices: ChoicesFn, label: str) -> QtWidgets.QTableWidget:
      """!A form table whose edits commit as one step.
      @param headings  column headings
      @param choices   column -> names to pick from
      @param label     undo label of an edit
      @return QTableWidget
      """
      t = QtWidgets.QTableWidget(0, len(headings))
      t.setHorizontalHeaderLabels(list(headings))
      t.setItemDelegate(NameDelegate(choices, t))
      t.verticalHeader().setVisible(False)
      t.horizontalHeader().setStretchLastSection(True)
      t.setMinimumHeight(ROW_HEIGHT * (TABLE_ROWS + 1))
      t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      t.itemChanged.connect(lambda _item: self.form_changed(label))
      return t

   def _build_form(self) -> None:
      """!The scenario form.
      @return None
      """
      ## The scenario's title (its transcript's first line).
      self.name_edit = QtWidgets.QLineEdit()
      self.name_edit.setPlaceholderText("scenario")
      self.name_edit.editingFinished.connect(lambda: self.form_changed("Scenario name"))
      ## Free text.
      self.description_edit = QtWidgets.QLineEdit()
      self.description_edit.editingFinished.connect(lambda: self.form_changed("Scenario description"))
      ## The battle format.
      self.format_combo = QtWidgets.QComboBox()
      self.format_combo.activated.connect(lambda _i: self.form_changed("Scenario format"))
      ## The battle seed.
      self.seed_spin = QtWidgets.QSpinBox()
      self.seed_spin.setRange(0, SEED_MAX)
      self.seed_spin.editingFinished.connect(lambda: self.form_changed("Scenario seed"))
      ## Running is forbidden.
      self.no_escape = QtWidgets.QCheckBox("No escape")
      self.no_escape.toggled.connect(lambda _on: self.form_changed("No escape"))
      ## The transcript prints the effect logic's texts (scenario "owner_texts", E13b).
      self.owner_texts = QtWidgets.QCheckBox("Owner texts (the effect logic's texts, volatile and side events)")
      self.owner_texts.setToolTip("The transcript shows the texts of the effect logic (text, volatile and side "
                                  "condition events); off: the engine's default transcript")
      self.owner_texts.toggled.connect(lambda _on: self.form_changed("Owner texts"))
      ## Field weather.
      self.weather_combo = QtWidgets.QComboBox()
      self.weather_combo.activated.connect(lambda _i: self.form_changed("Field weather"))
      ## Its turns (0: the bench's default).
      self.weather_turns = QtWidgets.QSpinBox()
      self.weather_turns.setRange(0, TURNS_MAX)
      self.weather_turns.setSpecialValueText(DEFAULT_TEXT)
      self.weather_turns.editingFinished.connect(lambda: self.form_changed("Weather turns"))
      ## The parties.
      self.party_table = self._table(PARTY_HEADINGS, lambda c: self._party_choices(c), "Scenario parties")
      self.party_table.currentCellChanged.connect(lambda r, _c, _pr, _pc: self._party_picked(r))
      ## The selected party's members.
      self.member_table = self._table(MEMBER_HEADINGS, lambda c: self._member_choices(c), "Party members")
      ## Says whose members the member table shows.
      self.member_label = QtWidgets.QLabel()
      ## Battler pokes.
      self.poke_table = self._table(POKE_HEADINGS, lambda c: self._poke_choices(c), "Battler pokes")
      ## Choices per turn.
      self.choices_edit = QtWidgets.QPlainTextEdit()
      self.choices_edit.setPlaceholderText("one turn per line: first | run | move 2 | move Strike @1 | switch 1\n"
                                           "(several on a line, joined by |, are one per field position)")
      self.choices_edit.setFixedHeight(TEXT_BOX_HEIGHT)
      ## Answers to effect requests.
      self.answers_edit = QtWidgets.QPlainTextEdit()
      self.answers_edit.setPlaceholderText("in order: learn_move 0 | switch_target 1 | choice 2")
      self.answers_edit.setFixedHeight(TEXT_BOX_HEIGHT)
      ## Commits typed choices / answers after a pause.
      self.text_timer = QtCore.QTimer(self)
      self.text_timer.setSingleShot(True)
      self.text_timer.setInterval(DEBOUNCE_MS)
      self.text_timer.timeout.connect(lambda: self.form_changed("Choices and answers"))
      for box in (self.choices_edit, self.answers_edit):
         box.textChanged.connect(lambda: self._typed())
      ## Stop condition.
      self.stop_combo = QtWidgets.QComboBox()
      self.stop_combo.addItems(bench.stop_kinds())
      self.stop_combo.activated.connect(lambda _i: self.form_changed("Stop condition"))
      ## Its count.
      self.stop_count = QtWidgets.QSpinBox()
      self.stop_count.setRange(1, COUNT_MAX)
      self.stop_count.editingFinished.connect(lambda: self.form_changed("Stop condition"))
      ## The scenario's own traces.
      self.trace_checks: dict[str, QtWidgets.QCheckBox] = {}
      for t in bench.traces():
         box = QtWidgets.QCheckBox(t)
         box.toggled.connect(lambda _on: self.form_changed("Scenario traces"))
         self.trace_checks[t] = box
      ## Why the form's text does not make a scenario, or a validation problem.
      self.form_error = QtWidgets.QLabel()
      self.form_error.setWordWrap(True)
      self.form_error.setStyleSheet(FAIL_STYLE)

      form = QtWidgets.QWidget()
      fl = QtWidgets.QVBoxLayout(form)
      top = QtWidgets.QFormLayout()
      top.addRow("Name", self.name_edit)
      top.addRow("Description", self.description_edit)
      top.addRow("Format", self.format_combo)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.seed_spin, 1)
      row.addWidget(self.no_escape)
      top.addRow("Seed", row)
      top.addRow("Transcript", self.owner_texts)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.weather_combo, 1)
      row.addWidget(QtWidgets.QLabel("turns"))
      row.addWidget(self.weather_turns)
      top.addRow("Weather", row)
      fl.addLayout(top)
      fl.addWidget(self._heading("Parties (a party of the data, or its own members)"))
      fl.addWidget(self.party_table)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add party", lambda: self.add_row("parties"), "Another party (the foe's side)"))
      row.addWidget(button("Remove party", lambda: self.remove_row("parties")))
      fl.addLayout(row)
      fl.addWidget(self.member_label)
      fl.addWidget(self.member_table)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add member", lambda: self.add_row("members"), "A member of the selected party"))
      row.addWidget(button("Remove member", lambda: self.remove_row("members")))
      fl.addLayout(row)
      fl.addWidget(self._heading("State pokes (battler values right after the start; empty: as it is)"))
      fl.addWidget(self.poke_table)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add poke", lambda: self.add_row("pokes")))
      row.addWidget(button("Remove poke", lambda: self.remove_row("pokes")))
      fl.addLayout(row)
      fl.addWidget(self._heading("Scripted choices (the last line repeats; none: the first usable move)"))
      fl.addWidget(self.choices_edit)
      fl.addWidget(self._heading("Answers to effect requests"))
      fl.addWidget(self.answers_edit)
      bottom = QtWidgets.QFormLayout()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.stop_combo, 1)
      row.addWidget(self.stop_count)
      bottom.addRow("Stop", row)
      row = QtWidgets.QHBoxLayout()
      for box in self.trace_checks.values():
         row.addWidget(box)
      row.addStretch(1)
      bottom.addRow("Traces", row)
      fl.addLayout(bottom)
      fl.addWidget(self.form_error)
      fl.addStretch(1)
      ## The scrolling form.
      self.form_area = QtWidgets.QScrollArea()
      self.form_area.setWidgetResizable(True)
      self.form_area.setWidget(form)

   def _heading(self, text: str) -> QtWidgets.QLabel:
      """!A bold section heading.
      @param text  its text
      @return QLabel
      """
      label = QtWidgets.QLabel(text)
      font = label.font()
      font.setBold(True)
      label.setFont(font)
      return label

   def _build_run_side(self) -> None:
      """!Run controls, the event list and the expected-transcript check.
      @return None
      """
      ## Says what the bench's build needs when it is missing.
      self.banner = QtWidgets.QLabel()
      self.banner.setWordWrap(True)
      self.banner.setStyleSheet(BANNER_STYLE)
      self.banner.hide()
      ## The generator.
      self.rng_combo = QtWidgets.QComboBox()
      self.rng_combo.addItems([bench.DEFAULT_RNG])   # refresh() adds the reference repo's
      self.rng_combo.setToolTip(RNG_TIP)
      ## The reference generators manifest's problem last reported (C4), or None.
      self._generators_problem = None
      ## Builds (incrementally) and runs.
      self.run_button = button("Run", lambda: self.run(), "Build the bench from the saved battle data and run")
      ## Stops the build or the run.
      self.cancel_button = button("Cancel", lambda: self.cancel(), "Stop the build or the run")
      self.cancel_button.setEnabled(False)
      ## Runs again whenever the battle data, its sources or the scenario are saved.
      self.run_on_save = QtWidgets.QCheckBox("Run on save")
      ## Checks the toolchain again (after installing it).
      self.recheck_button = button("Check again", lambda: self.check_toolchain(), "Look for CMake and a compiler")
      self.recheck_button.hide()
      ## Phase and progress text.
      self.progress = QtWidgets.QLabel("Not run yet.")
      self.progress.setWordWrap(True)
      ## Row type filters.
      self.filter_checks: dict[str, QtWidgets.QCheckBox] = {}
      for label, _kinds in FILTERS:
         box = QtWidgets.QCheckBox(label)
         box.setChecked(label in FILTERS_ON)
         box.toggled.connect(lambda _on: self.show_events())
         self.filter_checks[label] = box
      ## Text filter (owner, hook, words).
      self.text_filter = QtWidgets.QLineEdit()
      self.text_filter.setPlaceholderText("filter: owner, hook or text")
      self.text_filter.textChanged.connect(lambda _t: self.show_events())
      ## The run's records.
      self.event_list = QtWidgets.QTreeWidget()
      self.event_list.setHeaderLabels(list(EVENT_COLUMNS))
      self.event_list.setRootIsDecorated(False)
      self.event_list.setUniformRowHeights(True)
      self.event_list.itemActivated.connect(lambda item, _c: self.open_trace(item.data(INDEX_COLUMN, RECORD_ROLE)))
      self.event_list.itemDoubleClicked.connect(
         lambda item, _c: self.open_trace(item.data(INDEX_COLUMN, RECORD_ROLE)))
      ## Saves the last transcript as the scenario's expected one.
      self.expect_button = button("Save as expected", lambda: self.save_expected(),
                                  "Save the scenario and its transcript as a regression test (NAME.expected.txt)")
      ## Runs and compares with the expected transcript.
      self.check_button = button("Check", lambda: self.run(check=True),
                                 "Run and compare the transcript with the expected one")
      ## Pass / fail against the expected transcript.
      self.check_label = QtWidgets.QLabel()
      self.check_label.setWordWrap(True)
      self.check_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

      side = QtWidgets.QWidget()
      sl = QtWidgets.QVBoxLayout(side)
      sl.setContentsMargins(0, 0, 0, 0)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Generator"))
      row.addWidget(self.rng_combo)
      row.addWidget(self.run_button)
      row.addWidget(self.cancel_button)
      row.addWidget(self.run_on_save)
      row.addStretch(1)
      row.addWidget(self.recheck_button)
      sl.addLayout(row)
      sl.addWidget(self.progress)
      row = QtWidgets.QHBoxLayout()
      for box in self.filter_checks.values():
         row.addWidget(box)
      row.addWidget(self.text_filter, 1)
      sl.addLayout(row)
      sl.addWidget(self.event_list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.expect_button)
      row.addWidget(self.check_button)
      row.addStretch(1)
      sl.addLayout(row)
      sl.addWidget(self.check_label)
      ## The run side.
      self.run_side = side

   # -- documents ------------------------------------------------------------------------------------------------------

   @property
   def documents(self) -> dict[Path, Document]:
      """!The open scenario Documents by file: the project's (BattleProject.scenarios [S14]), so the window counts
      them unsaved, Save all writes them and renames rewrite them in the same undo step.
      @return {file: Document} (empty without battle data)
      """
      p = self.project()
      return p.scenarios if p is not None else {}

   def scenario_doc(self) -> Document | None:
      """!The selected scenario's Document (opened once by the project, kept with its undo history).
      @return Document, or None (nothing selected, or the file is not a scenario: see the message line)
      """
      path = self.selected
      p = self.project()
      if path is None or p is None:
         return None
      try:
         doc = p.scenario(path)
      except DocumentError as e:
         self.errors.setText(f"{path.name}: {e}")
         return None
      self._watch_doc(doc)
      return doc

   def current_document(self) -> Document | None:
      """!Undo / Redo / Save target: the selected scenario.
      @return Document, or None
      """
      return self.scenario_doc()

   def document_replaced(self) -> None:
      """!Other battle data: forgets the scenarios and the run, listens to the new data's saves.
      @return None
      """
      self.cancel()
      self.selected = None
      self.last_run = None
      self._watch()
      self.refresh()
      self.show_events()

   def _watch(self) -> None:
      """!Listens to the battle data's Documents (and the open scenarios) for "Run on save".
      @return None
      """
      for doc, cb in self._watched:
         doc.unsubscribe(cb)
      self._watched = []
      p = self.project()
      for doc in (p.documents() if p is not None else []) + list(self.documents.values()):
         self._watch_doc(doc)

   def _watch_doc(self, doc: Document) -> None:
      """!Listens to one more Document's saves (once).
      @param doc  the Document
      @return None
      """
      if any(d is doc for d, _cb in self._watched):
         return
      cb = self._save_listener(doc)
      doc.subscribe(cb)
      self._watched.append((doc, cb))

   def _save_listener(self, doc: Document) -> Callable[[], None]:
      """!A Document listener that notices saves (a change notice with nothing left unsaved).
      @param doc  the Document
      @return callback
      """
      def changed() -> None:
         """!The Document changed or was saved.
         @return None
         """
         if not doc.dirty and self.run_on_save.isChecked():
            QtCore.QTimer.singleShot(SAVE_RUN_MS, lambda: self._run_after_save())
      return changed

   def _run_after_save(self) -> None:
      """!Runs after a save (unless a run is going already).
      @return None
      """
      if self.job is None and self.run_on_save.isChecked():
         self.run()

   def stop(self) -> None:
      """!Commits typed choices (the page is left or files are saved).
      @return None
      """
      if self.text_timer.isActive():
         self.text_timer.stop()
         self.form_changed("Choices and answers")

   # -- refresh --------------------------------------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the scenario list and the selected scenario's form.
      @return None
      """
      p = self.project()
      self._filling = True
      try:
         paths = bench.scenario_paths(p) if p is not None else []
         for path in list(self.documents):
            if path not in paths and path.is_file():
               paths.append(path)   # created by this page, maybe with another schema while typed
         if self.selected not in paths:
            self.selected = paths[0] if paths else None
         self.scenario_list.blockSignals(True)
         self.scenario_list.clear()
         for path in paths:
            doc = self.documents.get(path)
            mark = " *" if doc is not None and doc.dirty else ""
            self.scenario_list.addItem(bench.relative_name(p, path) + mark)
         if self.selected is not None:
            self.scenario_list.setCurrentRow(paths.index(self.selected))
         self.scenario_list.blockSignals(False)
         self._paths = paths
         self.migrate_button.setVisible(p is not None and bool(bench.scenarios_to_migrate(p)))
         self._fill_generators(p)
         self.fill_form()
      finally:
         self._filling = False
      self._update_buttons()

   def _fill_generators(self, p: BattleProject | None) -> None:
      """!Lists the generators the bench can link (default, the reference repo's), keeping the pick; a
      scenario's generator nobody provides is listed too (a run then says what is missing).
      @param p  the BattleProject, or None
      @return None
      """
      current = self.rng_combo.currentText() or bench.DEFAULT_RNG
      found, problem = bench.generators_or_default(p) if p is not None else ({bench.DEFAULT_RNG: None}, None)
      names = list(found)
      if problem is not None:   # a malformed reference generators manifest: the default generator only (C4)
         if problem != self._generators_problem:
            report_failure(self, "Bench generators", f"only the engine's generator: {problem}")
         self.rng_combo.setToolTip(f"Only the engine's generator: {problem}")
      elif self._generators_problem is not None:
         self.rng_combo.setToolTip(RNG_TIP)
      self._generators_problem = problem
      if current not in names:
         names.append(current)
      if [self.rng_combo.itemText(i) for i in range(self.rng_combo.count())] != names:
         self.rng_combo.blockSignals(True)
         self.rng_combo.clear()
         self.rng_combo.addItems(names)
         self.rng_combo.setCurrentText(current)
         self.rng_combo.blockSignals(False)

   def _scenario_picked(self) -> None:
      """!Another scenario was picked.
      @return None
      """
      if self._filling:
         return
      self.stop()
      r = self.scenario_list.currentRow()
      paths = self._paths
      self.selected = paths[r] if 0 <= r < len(paths) else None
      self._party_row = 0
      doc = self.scenario_doc()
      if doc is not None:   # E7: a scenario names the generator its expectations were made with
         rng = bench.scenario_rng(doc.data)
         if self.rng_combo.findText(rng) < 0:
            self.rng_combo.addItem(rng)
         self.rng_combo.setCurrentText(rng)
      self.refresh()
      self.host.selection_changed()

   def _names(self, key: str) -> list[str]:
      """!Names of the battle data for a form choice.
      @param key  a core.logic.name_lists() key, or "parties", "formats", "traits"
      @return names
      """
      p = self.project()
      if p is None:
         return []
      if key in ("parties", "formats", "traits"):
         return p.names(key)
      try:
         return logic.name_lists(p).get(key, [])
      except (DocumentError, KeyError, TypeError, ValueError):
         return []

   def _party_choices(self, column: int) -> Sequence[str] | None:
      """!Names a party table column picks from.
      @param column  column
      @return names, or None for free text
      """
      key = bench.PARTY_COLUMNS[column][0]
      if key == "controller":
         return bench.controllers()
      if key == "data":
         return self._names("parties")
      if key == "flags":
         return bench.party_flags()
      return None

   def _member_choices(self, column: int) -> Sequence[str] | None:
      """!Names a member table column picks from.
      @param column  column
      @return names, or None for free text
      """
      key = bench.MEMBER_COLUMNS[column][0]
      lists = {"species": "species", "item": "items", "trait": "traits", "status": "statuses"}
      return self._names(lists[key]) if key in lists else None

   def _poke_choices(self, column: int) -> Sequence[str] | None:
      """!Names a poke table column picks from.
      @param column  column
      @return names, or None for free text
      """
      key = bench.POKE_COLUMNS[column][0]
      lists = {"status": "statuses", "item": "items"}
      return self._names(lists[key]) if key in lists else None

   def _fill_table(self, table: QtWidgets.QTableWidget, rows: Sequence[Any],
                   columns: Sequence[tuple[str, str]]) -> None:
      """!Fills a form table without emitting edits.
      @param table    the table
      @param rows     scenario objects (non-objects show empty)
      @param columns  core.bench column specs
      @return None
      """
      table.blockSignals(True)
      table.setRowCount(len(rows))
      for r, obj in enumerate(rows):
         texts = bench.cells(obj if isinstance(obj, dict) else {}, columns)
         for c, text in enumerate(texts):
            table.setItem(r, c, QtWidgets.QTableWidgetItem(text))
      table.blockSignals(False)

   def fill_form(self) -> None:
      """!Shows the selected scenario in the form.
      @return None
      """
      doc = self.scenario_doc()
      d = doc.data if doc is not None else {}
      self.form_area.widget().setEnabled(doc is not None)
      self.name_edit.setText(str(d.get("name", "")))
      self.description_edit.setText(str(d.get("description", "")))
      fmt = d.get("format")
      set_combo(self.format_combo, [DEFAULT_TEXT] + self._names("formats"), fmt if fmt is not None else DEFAULT_TEXT)
      set_spin(self.seed_spin, d.get("seed", bench.DEFAULT_SEED))
      set_check(self.no_escape, d.get("no_escape") is True)
      set_check(self.owner_texts, bench.owner_texts(d))
      fld = d.get("field") if isinstance(d.get("field"), dict) else {}
      weather = fld.get("weather")
      set_combo(self.weather_combo, [NO_WEATHER] + self._names("weathers"), weather or NO_WEATHER)
      set_spin(self.weather_turns, fld.get("weather_turns", 0))
      parties = d.get("parties") if isinstance(d.get("parties"), list) else []
      self._fill_table(self.party_table, parties, bench.PARTY_COLUMNS)
      self._party_row = min(self._party_row, max(0, len(parties) - 1))
      if parties:
         self.party_table.blockSignals(True)
         self.party_table.setCurrentCell(self._party_row, 0)
         self.party_table.blockSignals(False)
      self._fill_members(parties)
      pokes = d.get("pokes") if isinstance(d.get("pokes"), list) else []
      self._fill_table(self.poke_table, pokes, bench.POKE_COLUMNS)
      for box, text in ((self.choices_edit, bench.choices_text(d.get("choices") or [])),
                        (self.answers_edit, bench.answers_text(d.get("answers") or []))):
         if box.toPlainText() != text and not self.text_timer.isActive():
            box.blockSignals(True)
            box.setPlainText(text)
            box.blockSignals(False)
      kinds = bench.stop_kinds()
      end = kinds[0]   # the tool's STOP_END
      stop = d.get("stop", end)
      kind, count = (end, 1) if not isinstance(stop, dict) or len(stop) != 1 else next(iter(stop.items()))
      set_combo(self.stop_combo, kinds, kind)
      set_spin(self.stop_count, count)
      self.stop_count.setEnabled(kind != end)
      on = bench.trace_options(d)
      for t, box in self.trace_checks.items():
         set_check(box, t in on)
      self._show_problems(d if doc is not None else None)

   def _fill_members(self, parties: Sequence[Any]) -> None:
      """!The member table: the selected party's own members (a party of the data shows them read only).
      @param parties  the scenario's parties
      @return None
      """
      party = parties[self._party_row] if 0 <= self._party_row < len(parties) else None
      party = party if isinstance(party, dict) else None
      own = party is not None and "data" not in party
      members = party.get("members", []) if own else []
      data_party = party.get("data") if party is not None else None
      if data_party is not None:
         p = self.project()
         try:
            members = p.entry("parties", data_party).get("members", []) if p is not None else []
         except (DocumentError, KeyError):
            members = []
      self._fill_table(self.member_table, members if isinstance(members, list) else [], bench.MEMBER_COLUMNS)
      self.member_table.setEnabled(own)
      if party is None:
         self.member_label.setText("Members: pick a party")
      elif own:
         self.member_label.setText(f"Members of party {self._party_row} (their own records)")
      else:
         self.member_label.setText(f"Members of party {self._party_row}: the data's {data_party!r} (read only; "
                                   "clear \"Party of the data\" to give it its own)")

   def _show_problems(self, data: dict[str, Any] | None) -> None:
      """!The scenario's problems (core.bench.validate(): its shape, its pokes' names) under the form.
      @param data  the scenario, or None
      @return None
      """
      if data is None:
         self.form_error.setText("")
         return
      try:
         problems = bench.validate(data, self.project())
      except Exception as e:   # the engine's tool missing or broken: say so rather than fail the page
         problems = [f"cannot validate: {e}"]
      self.form_error.setText("\n".join(problems))
      self.form_error.setStyleSheet(FAIL_STYLE)

   def _party_picked(self, row: int) -> None:
      """!A party row was selected: the member table follows.
      @param row  its row
      @return None
      """
      if self._filling or row < 0 or row == self._party_row:
         return
      self._party_row = row
      doc = self.scenario_doc()
      parties = doc.data.get("parties", []) if doc is not None else []
      self._filling = True
      try:
         self._fill_members(parties if isinstance(parties, list) else [])
      finally:
         self._filling = False

   def _update_buttons(self) -> None:
      """!Enables what can be done now.
      @return None
      """
      doc = self.scenario_doc()
      running = self.job is not None
      can_run = doc is not None and not self.missing and not running and self.project() is not None
      self.run_button.setEnabled(can_run)
      self.check_button.setEnabled(can_run and doc is not None and bench.expected_path(doc) is not None)
      self.cancel_button.setEnabled(running)
      self.save_button.setEnabled(doc is not None and doc.dirty)
      self.expect_button.setEnabled(doc is not None and self.last_run is not None and self.last_run.ok()
                                    and not running)

   # -- form edits -----------------------------------------------------------------------------------------------------

   def _typed(self) -> None:
      """!Choices or answers typed: commit after a pause.
      @return None
      """
      if not self._filling:
         self.text_timer.start()

   def _table_rows(self, table: QtWidgets.QTableWidget, columns: Sequence[tuple[str, str]],
                   bases: Sequence[Any]) -> list[dict[str, Any]]:
      """!A form table's rows as scenario objects.
      @param table    the table
      @param columns  core.bench column specs
      @param bases    the objects the rows showed (their hidden keys are kept)
      @return objects
      @throws BenchError naming the row and column of a bad cell
      """
      out = []
      for r in range(table.rowCount()):
         texts = [(table.item(r, c).text() if table.item(r, c) is not None else "") for c in range(len(columns))]
         base = bases[r] if r < len(bases) and isinstance(bases[r], dict) else None
         try:
            out.append(bench.from_cells(texts, columns, base))
         except bench.BenchError as e:
            raise bench.BenchError(f"row {r + 1}: {e}") from e
      return out

   def read_form(self) -> dict[str, Any]:
      """!The scenario the form shows (keys the form does not show are kept from the Document).
      @return the scenario
      @throws BenchError when a cell or a text box does not parse
      """
      doc = self.scenario_doc()
      old = doc.data if doc is not None else {}
      d = copy.deepcopy(old)
      d["schema"] = bench.SCHEMA

      def put(key: str, value: Any) -> None:
         """!Sets a key, or leaves it out when the value is None.
         @param key    scenario key
         @param value  value or None
         @return None
         """
         if value is None:
            d.pop(key, None)
         else:
            d[key] = value

      put("name", self.name_edit.text().strip() or None)
      put("description", self.description_edit.text().strip() or None)
      fmt = self.format_combo.currentText()
      put("format", fmt if fmt and fmt != DEFAULT_TEXT else None)
      put("seed", self.seed_spin.value())
      put("no_escape", True if self.no_escape.isChecked() else None)
      put(bench.owner_texts_key(), True if self.owner_texts.isChecked() else None)
      fld = dict(old.get("field")) if isinstance(old.get("field"), dict) else {}
      weather = self.weather_combo.currentText()
      for key, value in (("weather", weather if weather and weather != NO_WEATHER else None),
                         ("weather_turns", self.weather_turns.value() or None)):
         if value is None:
            fld.pop(key, None)
         else:
            fld[key] = value
      put("field", fld or None)
      old_parties = old.get("parties") if isinstance(old.get("parties"), list) else []
      parties = self._table_rows(self.party_table, bench.PARTY_COLUMNS, old_parties)
      row = self._party_row
      for i, party in enumerate(parties):
         if "data" in party:
            party.pop("members", None)
         elif i == row and self.member_table.isEnabled():
            base = party.get("members") if isinstance(party.get("members"), list) else []
            party["members"] = self._table_rows(self.member_table, bench.MEMBER_COLUMNS, base)
         elif "members" not in party:
            party["members"] = self._data_members(old_parties[i] if i < len(old_parties) else None)
      d["parties"] = parties
      old_pokes = old.get("pokes") if isinstance(old.get("pokes"), list) else []
      put("pokes", self._table_rows(self.poke_table, bench.POKE_COLUMNS, old_pokes) or None)
      put("choices", bench.parse_choices(self.choices_edit.toPlainText()) or None)
      put("answers", bench.parse_answers(self.answers_edit.toPlainText()) or None)
      kind = self.stop_combo.currentText()
      put("stop", None if kind == bench.stop_kinds()[0] else {kind: self.stop_count.value()})
      trace = {t: True for t, box in self.trace_checks.items() if box.isChecked()}
      put("trace", trace or None)
      return d

   def _data_members(self, party: Any) -> list[dict[str, Any]]:
      """!The members a party gets when it stops being a party of the data: a copy of that party's members.
      @param party  the party before the change, or None
      @return members (empty when it named none)
      """
      p = self.project()
      name = party.get("data") if isinstance(party, dict) else None
      if p is None or name is None:
         return []
      try:
         members = p.entry("parties", name).get("members", [])
      except (DocumentError, KeyError):
         return []
      return [{k: copy.deepcopy(v) for k, v in m.items() if k in dict(bench.MEMBER_COLUMNS)}
              for m in members if isinstance(m, dict)]

   def form_changed(self, label: str) -> bool:
      """!Writes the form to the scenario (one undo step) when it parses and differs.
      @param label  undo label
      @return True when the scenario changed
      """
      if self._filling:
         return False
      doc = self.scenario_doc()
      if doc is None:
         return False
      try:
         data = self.read_form()
      except bench.BenchError as e:
         self.form_error.setText(str(e))
         return False
      if data == doc.data:
         return False
      changed = self.host.run_edit(label, lambda: bench.set_scenario(doc, data), doc)
      if changed:
         self.host.selection_changed()
      return changed

   def add_row(self, what: str) -> bool:
      """!Adds a party, a member of the selected party or a poke.
      @param what  "parties", "members" or "pokes"
      @return True when added
      """
      doc = self.scenario_doc()
      if doc is None:
         return False
      d = copy.deepcopy(doc.data)
      parties = d.setdefault("parties", [])
      species = self._names("species")
      p = self.project()
      joins = self._party_row if what == "members" else None
      # the level from the data (S17): the party's last member, the data's first party, else rules.level_max
      level = bench.new_member_level(p, d, joins) if p is not None else 1
      member = {"species": species[0] if species else "", "level": level}
      if what == "parties":
         parties.append({"side": bench.FOE_SIDE, "controller": bench.foe_controller(), "members": [member]})
         self._party_row = len(parties) - 1
      elif what == "members":
         party = parties[self._party_row] if 0 <= self._party_row < len(parties) else None
         if not isinstance(party, dict) or "data" in party:
            self.host.show_status("Pick a party with its own members (not a party of the data) first.")
            return False
         party.setdefault("members", []).append(member)
      else:
         d.setdefault("pokes", []).append({"party": 0, "member": 0})
      return self.host.run_edit(ADD_LABELS[what], lambda: bench.set_scenario(doc, d), doc)

   def remove_row(self, what: str) -> bool:
      """!Removes the selected party, member or poke.
      @param what  "parties", "members" or "pokes"
      @return True when removed
      """
      doc = self.scenario_doc()
      if doc is None:
         return False
      d = copy.deepcopy(doc.data)
      table = {"parties": self.party_table, "members": self.member_table, "pokes": self.poke_table}[what]
      r = table.currentRow()
      if what == "members":
         parties = d.get("parties", [])
         party = parties[self._party_row] if 0 <= self._party_row < len(parties) else {}
         rows = party.get("members", []) if isinstance(party, dict) and "data" not in party else []
      else:
         rows = d.get(what, [])
      if not 0 <= r < len(rows):
         return False
      rows.pop(r)
      return self.host.run_edit(REMOVE_LABELS[what], lambda: bench.set_scenario(doc, d), doc)

   def new_scenario(self, name: str | None = None) -> bool:
      """!Makes a scenario from the battle data (the first two parties, or a wild creature) in bench/.
      @param name  file name stem, or None to ask
      @return True when made
      """
      p = self.project()
      if p is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "New scenario", "Name (bench/NAME.json):")
         if not ok or not name.strip():
            return False
      try:
         doc = bench.create(p, name)
      except (DocumentError, OSError) as e:
         report_failure(self, "New scenario", str(e))
         return False
      self._watch_doc(doc)   # core.bench.create() gave it to the project
      self.selected = doc.path
      self.refresh()
      self.host.selection_changed()
      return True

   def migrate_scenarios(self) -> list[str]:
      """!Renames the retired poke keys of every scenario (core.bench.migrate_scenarios(): one undo step; Save all
      writes them).
      @return what was renamed
      """
      p = self.project()
      if p is None:
         return []
      self.stop()
      try:
         done = bench.migrate_scenarios(p)
      except DocumentError as e:
         report_failure(self, "Migrate scenarios", str(e))
         return []
      self.host.show_status(f"Migrated {len(done)} poke key(s); Save all writes them" if done
                            else "No scenario to migrate")
      self.host.changed()
      return done

   def save_scenario(self) -> bool:
      """!Saves the selected scenario.
      @return True when saved
      """
      self.stop()
      doc = self.scenario_doc()
      if doc is None:
         return False
      try:
         doc.save()
      except (DocumentError, OSError) as e:
         report_failure(self, "Save scenario", str(e))
         return False
      self.host.show_status(f"Saved {doc.path.name}")
      self.refresh()
      self.host.selection_changed()
      return True

   # -- running --------------------------------------------------------------------------------------------------------

   def check_toolchain(self) -> list[str]:
      """!Looks for what the bench's build needs; the banner says what is missing.
      @return what is missing
      """
      self.missing = self.toolchain_check()
      self.banner.setText(bench.toolchain_text(self.missing) if self.missing else "")
      self.banner.setVisible(bool(self.missing))
      self.recheck_button.setVisible(bool(self.missing))
      self._update_buttons()
      return self.missing

   def traces(self) -> list[str]:
      """!The traces a run asks for: rng and vm always (the event list filters them), events when shown.
      @return names
      """
      out = ["rng", "vm"]
      if self.filter_checks["Events"].isChecked() or self.trace_checks["events"].isChecked():
         out.append("events")
      return out

   def run(self, check: bool = False) -> bool:
      """!Builds the bench (incrementally) and runs the selected scenario in a thread; the event list and the
      check follow when it ends.
      @param check  also compare with the expected transcript (pass / fail)
      @return True when a run started
      """
      self.stop()
      p = self.project()
      doc = self.scenario_doc()
      if p is None or doc is None or self.job is not None:
         return False
      if self.missing:
         self.progress.setText(bench.toolchain_text(self.missing))
         return False
      if p.dirty:
         self.host.show_status("The bench runs the battle data as saved: save to include the unsaved edits.")
      data = copy.deepcopy(doc.data)
      rng = self.rng_combo.currentText()
      traces = self.traces()
      self.runner = runner = self.runner_factory()

      def work(progress: bench.Progress) -> bench.BenchRun:
         """!The build and the run (in the job's thread).
         @param progress  progress callback
         @return BenchRun
         """
         return runner.build_and_run(p, data, rng, traces, progress)

      # The job has no parent: a page closed while it runs must not destroy a running thread (keep_alive()).
      job = BenchJob(work)
      job.on_cancel = runner.cancel
      keep_alive(job)
      job.progress.connect(lambda phase, text: self._report_progress(phase, text))
      job.finished.connect(lambda: self._job_ended(job, check))
      self.job = job
      self.progress.setText("starting...")
      self.check_label.setText("")
      self._update_buttons()
      job.start()
      return True

   def _report_progress(self, phase: str, text: str) -> None:
      """!Shows a job's progress (the page may be gone).
      @param phase  one of core.bench.PHASES
      @param text   what happens
      @return None
      """
      try:
         self.progress.setText(f"{phase}: {text}")
      except RuntimeError:
         pass   # the page was closed: nothing to show it on

   def _job_ended(self, job: BenchJob, check: bool) -> None:
      """!A job's thread ended (the page may be gone).
      @param job    the job
      @param check  compare with the expected transcript
      @return None
      """
      try:
         self._job_done(job, check)
      except RuntimeError:
         pass   # the page was closed while it ran

   def cancel(self) -> None:
      """!Stops the build or the run.
      @return None
      """
      if self.job is not None and self.runner is not None:
         self.runner.cancel()

   def wait(self, ms: int | None = None) -> bool:
      """!Waits for the running job and handles its end (tests, closing).
      @param ms  most milliseconds to wait, or None for as long as it takes
      @return True when no job is running any more
      """
      job = self.job
      if job is None:
         return True
      done = job.wait(ms) if ms is not None else job.wait()
      if done:
         QtWidgets.QApplication.processEvents()
         if self.job is job:
            self._job_done(job, False)
      return self.job is None

   def _job_done(self, job: BenchJob, check: bool) -> None:
      """!A job ended: shows its run or why it failed.
      @param job    the job
      @param check  compare with the expected transcript
      @return None
      """
      if self.job is not job:
         return
      self.job = None
      error = job.error
      if error is not None:
         if isinstance(error, bench.Cancelled):
            self.progress.setText("Cancelled.")
         elif isinstance(error, bench.ToolchainMissing):
            self.missing = error.missing
            self.check_toolchain()
            self.progress.setText(str(error))
         else:
            self.progress.setText(f"Failed: {error}")
         self._update_buttons()
         return
      self.last_run = job.result
      run = self.last_run
      errors = run.errors()
      self.progress.setText("; ".join(errors) if errors else
                            f"Ran with the {run.rng} generator: {len(run.of('line'))} transcript lines, "
                            f"{len(run.of('rng'))} draws, {len(run.of('vm'))} VM steps.")
      self.show_events()
      self.show_check(always=check)
      self._update_buttons()

   def show_check(self, always: bool = False) -> None:
      """!Pass / fail of the last run against the scenario's expected transcript.
      @param always  say so too when the scenario has none
      @return None
      """
      doc = self.scenario_doc()
      run = self.last_run
      if doc is None or run is None:
         self.check_label.setText("")
         return
      path = bench.expected_path(doc)
      expected = bench.expected_text(doc)
      if path is None:
         self.check_label.setStyleSheet("")
         self.check_label.setText("No expected transcript yet: Save as expected makes one." if always else "")
         return
      if expected is None:
         self.check_label.setStyleSheet(FAIL_STYLE)
         self.check_label.setText(f"The expected transcript {path.name} is missing.")
         return
      problems = bench.expected_problems(expected, run.transcript(), path.name)
      self.check_label.setStyleSheet(PASS_STYLE if not problems else FAIL_STYLE)
      self.check_label.setText(f"PASS: the transcript matches {path.name}" if not problems else
                               "FAIL: " + "\n".join(problems))

   def save_expected(self) -> bool:
      """!Saves the scenario and the last run's transcript as its expected one.
      @return True when saved
      """
      doc = self.scenario_doc()
      run = self.last_run
      if doc is None or run is None or not run.ok():
         return False
      try:
         out = bench.save_expected(doc, run.transcript())
      except (DocumentError, OSError) as e:
         report_failure(self, "Save as expected", str(e))
         return False
      self.host.show_status(f"Saved {doc.path.name} and {out.name}")
      self.host.changed()
      self.show_check()
      return True

   # -- events ---------------------------------------------------------------------------------------------------------

   def shown_kinds(self) -> list[str]:
      """!The record types the filters show.
      @return types
      """
      return [k for label, kinds in FILTERS if self.filter_checks[label].isChecked() for k in kinds]

   def show_events(self) -> None:
      """!Fills the event list from the last run, filtered.
      @return None
      """
      self.event_list.clear()
      self._shown = []
      run = self.last_run
      if run is None:
         return
      words = self.text_filter.text().strip().lower()
      for row in run.events(self.shown_kinds()):
         if words and words not in row.text.lower():
            continue
         marker = str(row.draws) if row.draws else ""
         item = QtWidgets.QTreeWidgetItem([str(row.index), str(row.turn), marker, row.kind, row.text])
         item.setData(INDEX_COLUMN, RECORD_ROLE, row.index)
         if row.draws:
            item.setBackground(DRAWS_COLUMN, QtGui.QColor(DRAW_COLOUR))
            item.setToolTip(DRAWS_COLUMN, f"{row.draws} random draw(s) before this line")
         colour = KIND_COLOURS.get(row.kind)
         if colour is not None:
            item.setForeground(TEXT_COLUMN, QtGui.QColor(colour))
         pos = bench.trace_position(row.record)
         if pos is not None and pos.file:
            item.setToolTip(TEXT_COLUMN, "Activate to open the source line in Logic > Effects")
         elif pos is not None and pos.template:
            item.setToolTip(TEXT_COLUMN, f"Code of the {pos.template} template (no source line): activate to open "
                                         "the owner in Logic > Effects")
         self.event_list.addTopLevelItem(item)
         self._shown.append(row.index)
      for c in range(len(EVENT_COLUMNS) - 1):
         self.event_list.resizeColumnToContents(c)

   def open_trace(self, index: int | None) -> bool:
      """!Opens Logic > Effects on a trace record's owner, in the text view at its source line and column.
      @param index  the record's index in the run's output
      @return True when the Effects page shows it
      """
      run = self.last_run
      if run is None or index is None or not 0 <= index < len(run.records):
         return False
      pos = bench.trace_position(run.records[index])
      if pos is None or not pos.owner:
         return False
      show = getattr(self.host, "show_panel", None)
      if show is None:
         self.host.show_status(f"{pos.owner}: {pos.file}:{pos.line}:{pos.col}")
         return False
      try:
         effects = show("effects")
      except KeyError:
         self.host.show_status(f"{pos.owner}: {pos.file}:{pos.line}:{pos.col} (no Effects page here)")
         return False
      if not effects.select_owner(pos.owner):
         self.host.show_status(f"{pos.owner}: not in the Effects page's owners")
         return False
      p = self.project()
      if p is None or pos.file not in p.effects:
         # Code the compiler generated (a condition template's, E7 "template") has no line in the sources.
         what = f"the {pos.template} template" if pos.template else (pos.file or "generated code")
         self.host.show_status(f"{pos.owner} {pos.hook} pc {pos.pc}: {what} (no source line to show)")
         return False
      if effects.text_rel != pos.file:
         effects.text_rel = pos.file
         effects.refresh()
      effects.set_view("text")
      if pos.line:
         effects.code.go_to(pos.line, max(pos.col, 1))
      return True
