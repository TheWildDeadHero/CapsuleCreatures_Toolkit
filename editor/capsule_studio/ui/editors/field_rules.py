"""!The World page's Levels and Movement modes panels (engine E8;
core.field_rules): the world's 16 elevation levels and its vehicle classes.

Levels: one row per level (a cell's 4 elevation bits): its name, whom it
meets ("all", "same" or a list of levels by name or number; the "Meets"
column shows the levels the engine resolves), whether a mover arriving on
it takes its level or keeps its own (bridges), and the sprite priority of
a mover on it. Grey rows are the engine's default rule; the first edit
writes the 16 levels into the world. Movement modes: the list (class 0 is
on foot) and a form: walk / run speeds, whether running is allowed, the
first sprite animation of its set and the behaviors it may enter (all, or
the ticked ones); "Enters" shows what the engine resolves from both lists.

Every choice list and limit is the engine's map compiler's; an edit it
refuses is refused with its message. Every change is one undo step on the
world Document (the host's run_edit()); a mode rename or removal the
game's scripts would notice (`vehicle NAME;`) is asked about first.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import field_rules as model
from ..panel import EditorPanel
from ..panes import split_box
from ..widgets import button, headless, set_enabled
from .battle_common import FORM_STRETCH, LIST_STRETCH, set_combo
from .record_widgets import NameChecks

if TYPE_CHECKING:
   from ...core.document import Document
   from ...core.world import Project
   from ..panel import PanelHost

## Level table columns: (key, header).
LEVEL_COLUMNS = [("index", "#"), ("name", "Name"), ("meets", "Meets (as written)"), ("met", "Meets"),
                 ("on_arrive", "On arrive"), ("priority", "Sprite priority")]
## Level table column of each key.
LEVEL_COLUMN = {key: c for c, (key, _h) in enumerate(LEVEL_COLUMNS)}
## Level table columns typed in.
LEVEL_TYPED = ("name", "meets")
## Text colour of the default rule's rows.
DEFAULT_COLOR = "#808080"
## Text colour of the compile result when it fails.
ERROR_COLOR = "#c03030"


def _shown(meets: Any) -> str:
   """!A "meets" value as the table shows it (a word, or the list as JSON).
   @param meets  the value
   @return text
   """
   return meets if isinstance(meets, str) else json.dumps(meets)


def _parsed(text: str) -> Any:
   """!A typed "meets" value: a word, or a list of levels ("1, bridge" or JSON).
   @param text  typed text
   @return the value
   """
   text = text.strip()
   if text in model.meets_words():
      return text
   try:
      value = json.loads(text)
   except json.JSONDecodeError:
      value = [p.strip() for p in text.split(",") if p.strip()]
   if isinstance(value, list):
      return [int(v) if isinstance(v, str) and v.isdigit() else v for v in value]
   return value


class FieldPanel(EditorPanel):
   """!Base of the two panels: the world Document, edits, the compile line."""

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel.
      @param host    the world window
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## True while the panel fills its widgets.
      self._filling = False
      ## The levels' and modes' compile result.
      self.errors = QtWidgets.QLabel()
      self.errors.setWordWrap(True)

   def world(self) -> Document | None:
      """!The world Document.
      @return Document, or None
      """
      p: Project | None = self.host_project()
      return p.world if p is not None else None

   def current_document(self) -> Document | None:
      """!Undo / Redo act on the world.
      @return Document, or None
      """
      return self.world()

   def _run(self, label: str, fn: Callable[[Document], object]) -> bool:
      """!One edit of the world; a refused one refreshes the panel back.
      @param label  undo label
      @param fn     callable(world Document)
      @return True when it went through
      """
      doc = self.world()
      if self._filling:
         return False
      if doc is None:
         return self.explain(label)
      ok = self.host.run_edit(label, lambda: fn(doc), doc)
      if not ok:
         self.refresh()
      return ok

   def show_errors(self) -> None:
      """!The compile result line.
      @return None
      """
      doc = self.world()
      error = model.check(doc) if doc is not None else None
      self.errors.setText(error or "")
      self.errors.setStyleSheet(f"color: {ERROR_COLOR};" if error else "")


class LevelsPanel(FieldPanel):
   """!The 16 elevation levels.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "levels"
   ## See EditorPanel.title.
   title = "Levels"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the table.
      @param host    the world window
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Whether the engine's default rule applies.
      self.state = QtWidgets.QLabel()
      ## The levels.
      self.table = QtWidgets.QTableWidget(0, len(LEVEL_COLUMNS))
      self.table.setHorizontalHeaderLabels([h for _k, h in LEVEL_COLUMNS])
      self.table.verticalHeader().setVisible(False)
      self.table.itemChanged.connect(lambda item: self._typed(item))
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("A cell's elevation is one of 16 levels. Movers on two levels meet when either level "
                              "names the other (\"all\": every level; \"same\": only itself; or a list such as "
                              "1, bridge). Arriving on a \"keep\" level keeps the mover's own level (bridges).")
      note.setWordWrap(True)
      lay.addWidget(note)
      lay.addWidget(self.state)
      lay.addWidget(self.table, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Engine default", lambda: self.reset(), "The engine's default rule (0 meets all, "
                                                                   "15 meets all and keeps, the rest themselves)"))
      row.addStretch(1)
      lay.addLayout(row)
      lay.addWidget(self.errors)

   def refresh(self) -> None:
      """!Re-reads the levels.
      @return None
      """
      doc = self.world()
      rows = model.level_rows(doc) if doc is not None else []
      self._filling = True
      try:
         default = bool(rows) and rows[0]["default"]
         self.state.setText("The engine's default rule (the world has no levels of its own)." if default else
                            "The world's own levels.")
         self.table.setRowCount(len(rows))
         for r, row in enumerate(rows):
            texts = {"index": str(row["index"]), "name": str(row["name"]), "meets": _shown(row["meets"]),
                     "met": ", ".join(str(k) for k in row["met"])}
            for key, c in LEVEL_COLUMN.items():
               if key in ("on_arrive", "priority"):
                  continue
               item = QtWidgets.QTableWidgetItem(texts[key])
               if key not in LEVEL_TYPED:
                  item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
               if default:
                  item.setForeground(QtGui.QColor(DEFAULT_COLOR))
               self.table.setItem(r, c, item)
            arrive = QtWidgets.QComboBox()
            set_combo(arrive, model.arrive_words(), row["on_arrive"])
            arrive.activated.connect(lambda _i, k=r, w=arrive: self.set_level(k, "on_arrive", w.currentText()))
            self.table.setCellWidget(r, LEVEL_COLUMN["on_arrive"], arrive)
            prio = QtWidgets.QSpinBox()
            prio.setRange(0, model.max_priority())
            prio.setValue(row["priority"] if isinstance(row["priority"], int) else 0)
            prio.editingFinished.connect(lambda k=r, w=prio: self.set_level(k, "priority", w.value()))
            self.table.setCellWidget(r, LEVEL_COLUMN["priority"], prio)
         self.table.resizeColumnsToContents()
      finally:
         self._filling = False
      set_enabled(self, doc is not None)
      self.show_errors()

   def _typed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A name or meets cell was typed.
      @param item  the cell
      @return None
      """
      if self._filling:
         return
      if item.column() == LEVEL_COLUMN["name"]:
         self.rename_level(item.row(), item.text())
      elif item.column() == LEVEL_COLUMN["meets"]:
         self.set_level(item.row(), "meets", _parsed(item.text()))

   def set_level(self, index: int, key: str, value: Any) -> bool:
      """!Sets a level field (one undo step).
      @param index  the level
      @param key    meets / on_arrive / priority
      @param value  the value
      @return True when it went through
      """
      return self._run("Level", lambda doc: model.set_level(doc, index, key, value))

   def rename_level(self, index: int, name: str) -> bool:
      """!Renames a level (other levels' meets lists follow).
      @param index  the level
      @param name   new name
      @return True when it went through
      """
      return self._run("Rename level", lambda doc: model.rename_level(doc, index, name))

   def reset(self) -> bool:
      """!Gives the levels back to the engine's rule.
      @return True when it went through
      """
      return self._run("Default levels", model.reset_levels)


class ModesPanel(FieldPanel):
   """!The movement modes (vehicle classes).

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "movement_modes"
   ## See EditorPanel.title.
   title = "Movement modes"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the list and the form.
      @param host    the world window
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The selected mode, or None.
      self.selected = None
      ## The modes.
      self.modes = QtWidgets.QListWidget()
      self.modes.currentRowChanged.connect(lambda r: self._picked(r))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Class 0 is on foot; scripts switch with `vehicle NAME;`."))
      left.addWidget(self.modes, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_mode()))
      row.addWidget(button("Rename...", lambda: self.rename_mode()))
      row.addWidget(button("Remove", lambda: self.remove_mode()))
      left.addLayout(row)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Up", lambda: self.move_mode(-1), "Lower class number (class 0 stays on foot)"))
      row.addWidget(button("Down", lambda: self.move_mode(1), "Higher class number"))
      left.addLayout(row)
      form = QtWidgets.QFormLayout()
      ## Walk and run speed combos.
      self.speed = {}
      for key in ("walk", "run"):
         c = QtWidgets.QComboBox()
         c.activated.connect(lambda _i, k=key, w=c: self.set_mode(k, int(w.currentText())))
         self.speed[key] = c
         form.addRow(f"{key.capitalize()} speed (pixels per frame)", c)
      ## Running allowed.
      self.can_run = QtWidgets.QCheckBox("may run")
      self.can_run.clicked.connect(lambda on: self.set_mode("can_run", None if on else False))
      form.addRow("", self.can_run)
      ## F2: stepping onto a cell only class 0 enters makes the walker class 0 (leaving the water).
      self.dismount = QtWidgets.QCheckBox("steps back onto land on foot (dismount)")
      self.dismount.clicked.connect(lambda on: self.set_mode("dismount", True if on else None))
      form.addRow("", self.dismount)
      ## I3: frames a turn in place takes (0: the field's default).
      self.turn_frames = QtWidgets.QSpinBox()
      self.turn_frames.setRange(0, model.max_turn_frames())
      self.turn_frames.setSpecialValueText("default")
      self.turn_frames.setToolTip("Frames a turn in place takes in this mode (default: the field's own)")
      self.turn_frames.editingFinished.connect(lambda: self.set_mode(model.TURN_FRAMES_KEY,
                                                                     self.turn_frames.value() or None))
      form.addRow("Turn in place (frames)", self.turn_frames)
      ## I3: a blocked step walks in place for a step's time.
      self.bumps = QtWidgets.QCheckBox("bumps into what blocks it (walks in place)")
      self.bumps.clicked.connect(lambda on: self.set_mode(model.BUMPS_KEY, True if on else None))
      form.addRow("", self.bumps)
      ## I3: arriving with another direction held steps on without turning.
      self.keeps_moving = QtWidgets.QCheckBox("keeps moving into another held direction (no turn first)")
      self.keeps_moving.clicked.connect(lambda on: self.set_mode(model.KEEPS_MOVING_KEY, True if on else None))
      form.addRow("", self.keeps_moving)
      step, most = model.animation_step()
      ## First animation of the mode's set.
      self.first_animation = QtWidgets.QSpinBox()
      self.first_animation.setRange(0, most)
      self.first_animation.setSingleStep(step)
      self.first_animation.editingFinished.connect(lambda: self.set_mode("first_animation",
                                                                         self.first_animation.value() or None))
      form.addRow("First animation", self.first_animation)
      ## Enters every behavior that lets it.
      self.every = QtWidgets.QCheckBox("every behavior that lets it in")
      self.every.clicked.connect(lambda on: self.set_mode(model.PASSABLE_KEY, None if on else self.passable.checked()))
      form.addRow("Passable", self.every)
      ## The behaviors it may enter.
      self.passable = NameChecks(lambda names: self.set_mode(model.PASSABLE_KEY, names))
      form.addRow("", self.passable)
      ## What the engine resolves it enters.
      self.enters = QtWidgets.QLabel()
      self.enters.setWordWrap(True)
      form.addRow("Enters", self.enters)
      right = QtWidgets.QVBoxLayout()
      right.addLayout(form)
      right.addStretch(1)
      right.addWidget(self.errors)
      lay = QtWidgets.QHBoxLayout(self)
      lay.addLayout(left, LIST_STRETCH)
      lay.addLayout(right, FORM_STRETCH)
      split_box(lay)   # [RZ] modes | form: the user drags the boundary

   def rows(self) -> list[dict[str, Any]]:
      """!The modes.
      @return mode_rows() ([] with no world)
      """
      doc = self.world()
      return model.mode_rows(doc) if doc is not None else []

   def refresh(self) -> None:
      """!Re-reads the modes.
      @return None
      """
      rows = self.rows()
      names = [r["name"] for r in rows]
      if self.selected not in names:
         self.selected = names[0] if names else None
      self._filling = True
      try:
         self.modes.clear()
         self.modes.addItems([f"{r['index']} {r['name']}" for r in rows])
         if self.selected in names:
            self.modes.setCurrentRow(names.index(self.selected))
      finally:
         self._filling = False
      self._fill_form()
      set_enabled(self, self.world() is not None)
      self.show_errors()

   def _picked(self, row: int) -> None:
      """!Another mode was picked.
      @param row  list row
      @return None
      """
      if self._filling:
         return
      rows = self.rows()
      self.selected = rows[row]["name"] if 0 <= row < len(rows) else None
      self._fill_form()

   def _fill_form(self) -> None:
      """!Shows the selected mode.
      @return None
      """
      row = next((r for r in self.rows() if r["name"] == self.selected), None)
      if row is None:
         return
      self._filling = True
      try:
         for key, c in self.speed.items():
            set_combo(c, [str(s) for s in model.speeds()], str(row[key]))
         self.can_run.setChecked(row["can_run"] is not False)
         self.dismount.setChecked(row["dismount"])
         self.dismount.setEnabled(row["index"] != 0)
         turn = row[model.TURN_FRAMES_KEY]
         self.turn_frames.setValue(turn if isinstance(turn, int) and not isinstance(turn, bool) else 0)
         self.bumps.setChecked(row[model.BUMPS_KEY])
         self.keeps_moving.setChecked(row[model.KEEPS_MOVING_KEY])
         self.first_animation.setValue(row["first_animation"] if isinstance(row["first_animation"], int) else 0)
         self.every.setChecked(row["passable"] is None)
         doc = self.world()
         behaviors = [b.get("name") for b in doc.data.get(model.BEHAVIORS_KEY, []) if isinstance(b, dict)]
         self.passable.set_names([str(b) for b in behaviors], row["passable"] or [])
         set_enabled(self.passable, row["passable"] is not None)   # read-only, still scrolling
         self.enters.setText(", ".join(str(b) for b in row["enters"]) or "nothing")
      finally:
         self._filling = False

   def set_mode(self, key: str, value: Any) -> bool:
      """!Sets a field of the selected mode.
      @param key    walk / run / can_run / first_animation / passable
      @param value  the value (None: the default)
      @return True when it went through
      """
      name = self.selected
      return name is not None and self._run("Mode", lambda doc: model.set_mode(doc, name, key, value))

   def _ask(self, title: str, label: str, text: str = "") -> str | None:
      """!Asks for a name.
      @param title  dialog title
      @param label  prompt
      @param text   starting text
      @return the name, or None when cancelled
      """
      name, ok = QtWidgets.QInputDialog.getText(self, title, label, text=text)
      return name if ok else None

   def _scripts_ok(self, name: str) -> bool:
      """!Asks before a rename / removal the game's scripts would notice (headless: refused).
      @param name  the mode
      @return True to go ahead
      """
      doc = self.world()
      users = model.mode_users(doc, name) if doc is not None else []
      if not users:
         return True
      text = f"The game's scripts name {name!r}:\n" + "\n".join(users) + "\n\nThey are not rewritten. Go ahead?"
      if headless():
         self.host.show_status(text.replace("\n", " "))
         return False
      answer = QtWidgets.QMessageBox.question(self, "Movement mode", text)
      return answer == QtWidgets.QMessageBox.StandardButton.Yes

   def add_mode(self, name: str | None = None) -> bool:
      """!Adds a mode.
      @param name  its name, or None to ask
      @return True when it went through
      """
      name = name if name is not None else self._ask("Add movement mode", "Name:")
      if name is None:
         return False
      ok = self._run("Add mode", lambda doc: model.add_mode(doc, name))
      if ok:
         self.selected = name.strip()
         self.refresh()
      return ok

   def rename_mode(self, new: str | None = None) -> bool:
      """!Renames the selected mode (behaviors and encounter methods follow).
      @param new  the new name, or None to ask
      @return True when it went through
      """
      old = self.selected
      if old is None:
         return self.explain("Rename movement mode", "movement mode")
      new = new if new is not None else self._ask("Rename movement mode", "New name:", old)
      if new is None or not self._scripts_ok(old):
         return False
      ok = self._run("Rename mode", lambda doc: model.rename_mode(doc, old, new))
      if ok:
         self.selected = new.strip()
         self.refresh()
      return ok

   def remove_mode(self) -> bool:
      """!Removes the selected mode.
      @return True when it went through
      """
      name = self.selected
      if name is None:
         return self.explain("Remove movement mode", "movement mode")
      if not self._scripts_ok(name):
         return False
      return self._run("Remove mode", lambda doc: model.remove_mode(doc, name))

   def move_mode(self, delta: int) -> bool:
      """!Moves the selected mode.
      @param delta  -1 up, +1 down
      @return True when it went through
      """
      name = self.selected
      if name is None:
         return self.explain("Move movement mode", "movement mode")
      return self._run("Move mode", lambda doc: model.move_mode(doc, name, delta))
