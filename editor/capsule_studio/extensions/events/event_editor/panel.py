"""!The Events panel: a map's warps, triggers and signs, its area root, and
the world's scripts manifest and step hooks (B-3).

Shown on its own as the event editor app, and as a tab of the Studio's World
page, where it follows the map chosen in the Map tab.
The list shows the map's events; the form under it edits the chosen one
(cell, level and the fields of its kind, a warp's transition and doors and overrides door among them,
with the scripts, flags and variables the scripts manifest offers). The Events map tool places, moves
and removes events by clicking. Every change goes through the host's
run_edit() on the Document it changes, so Undo / Redo, the unsaved mark and
Save work as in the other panels; everything here is also a
`capsule-studio events` command (commands.py).
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtWidgets

from capsule_studio.core import doors, engine, events, maps
from capsule_studio.core.document import DocumentError
from capsule_studio.ui.panel import EditorPanel
from capsule_studio.ui.panes import split_box
from capsule_studio.ui.widgets import button, set_enabled

from . import maptools

if TYPE_CHECKING:
   from PySide6 import QtGui

   from capsule_studio.core.document import Document
   from capsule_studio.core.world import Project
   from capsule_studio.ui.world_shell import WorldWindow

## A JSON object (an event).
JsonDict = dict[str, Any]
## An event field's value (None removes the field).
FieldValue = int | str | None

## Errors meaning the engine (its compilers) is missing or too old.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError)
## Transition chooser's first entry: the world's default.
DEFAULT_TRANSITION = "(world default)"
## Item data role holding an event's (kind, index) (Qt.ItemDataRole.UserRole).
ITEM_KEY_ROLE = 256
## Width of the event list's Event column (pixels).
EVENT_COLUMN_WIDTH = 90
## Width of the event list's Cell column (pixels).
CELL_COLUMN_WIDTH = 70
## Smallest cell coordinate the form takes.
MIN_CELL = -16384
## Largest cell coordinate the form takes.
MAX_CELL = 16383
## The attribute cell field whose highest value is the highest level an event may name (core.maps.cell_fields():
## the engine's; 0 is any level).
ELEVATION_FIELD = "elevation"
## Highest warp number a warp may name.
MAX_WARP = 254
## Colour of the refused-run message.
PROBLEM_COLOR = "#c03030"
## Smallest value a trigger's variable may hold (signed 32 bits).
MIN_VALUE = -2**31
## Largest value a trigger's variable may hold (signed 32 bits).
MAX_VALUE = 2**31 - 1
## Tallest the step hook list grows (pixels).
HOOK_LIST_HEIGHT = 110
## Period a new step hook starts with, in steps.
DEFAULT_HOOK_PERIOD = 16
## Longest step hook period, in steps (a power of two).
MAX_HOOK_PERIOD = events.MAX_HOOK_PERIOD
## Stretch of the event list and form column.
EVENTS_STRETCH = 3
## Stretch of the world column.
WORLD_STRETCH = 1


class EventsPanel(EditorPanel):
   """!Edits map events (core.events)."""

   ## See EditorPanel.panel_id.
   panel_id = "events"
   ## See EditorPanel.title.
   title = "Events"

   def __init__(self, host: WorldWindow, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The map shown, or None.
      self.map_name = None
      ## The Document the last edit changed (Undo goes there first).
      self._last_doc = None
      ## True while widgets are being filled.
      self._filling = False
      ## Names from the scripts manifest (events.names()).
      self.names = {"scripts": [], "flags": [], "vars": {}, "error": None}

      # -- map and area
      ## The map shown.
      self.map_box = QtWidgets.QComboBox()
      self.map_box.currentTextChanged.connect(lambda t: self._map_chosen(t))
      ## Follow the map chosen in the Map tab.
      self.follow = QtWidgets.QCheckBox("Follow the Map tab")
      self.follow.setChecked(True)
      self.follow.toggled.connect(lambda on: on and self._follow())
      self.follow.setVisible(getattr(host, "shows_map", lambda: True)())   # no Map tab: nothing to follow
      ## Area root (B-2).
      self.area = QtWidgets.QComboBox()
      self.area.setToolTip("The outdoor map whose area this map is in: leaving the area clears its area flags "
                           "and variables (B-2). Interiors name their town; outdoor maps are their own area.")
      self.area.currentIndexChanged.connect(lambda _i: self._area_chosen())
      ## The map's events and objects may stand on unpainted cells ("unpainted_events").
      self.unpainted = QtWidgets.QCheckBox("Events on unpainted cells")
      self.unpainted.setToolTip("Lets this map's warps, triggers and objects stand on unpainted cells, and warps land "
                                "on them (imported data kept as its source has it; the walker never steps onto such a "
                                "cell by itself)")
      self.unpainted.clicked.connect(lambda on: self._unpainted_toggled(on))
      top = QtWidgets.QHBoxLayout()
      top.addWidget(QtWidgets.QLabel("Map"))
      top.addWidget(self.map_box, 1)
      top.addWidget(self.follow)
      top.addWidget(QtWidgets.QLabel("Area"))
      top.addWidget(self.area, 1)
      top.addWidget(self.unpainted)

      # -- event list
      ## The map's events.
      self.tree = QtWidgets.QTreeWidget()
      self.tree.setHeaderLabels(["Event", "Cell", "What"])
      self.tree.setRootIsDecorated(False)
      self.tree.setColumnWidth(0, EVENT_COLUMN_WIDTH)
      self.tree.setColumnWidth(1, CELL_COLUMN_WIDTH)
      self.tree.currentItemChanged.connect(lambda _a, _b: self._event_chosen())
      adds = QtWidgets.QHBoxLayout()
      for kind in events.KINDS:
         # k=kind binds this kind (a plain closure would see the last one)
         adds.addWidget(button(f"Add {events.KINDS[kind]}", lambda k=kind: self.add(k),
                               f"A new {events.KINDS[kind]} at the cell in the form (or use the Events map "
                               "tool to click one)"))
      adds.addWidget(button("Remove", lambda: self.remove(), "Remove the chosen event (warps after it are "
                                                             "renumbered everywhere)"))

      # -- form
      form_box = QtWidgets.QGroupBox("Chosen event")
      ## The form.
      self.form = QtWidgets.QFormLayout(form_box)
      ## Column.
      self.x = QtWidgets.QSpinBox()
      ## Row.
      self.y = QtWidgets.QSpinBox()
      for w in (self.x, self.y):
         w.setRange(MIN_CELL, MAX_CELL)
         w.setKeyboardTracking(False)
         w.valueChanged.connect(lambda _v: self._moved())
      cell = QtWidgets.QHBoxLayout()
      cell.addWidget(self.x)
      cell.addWidget(self.y)
      ## Level (0 = any).
      self.elevation = QtWidgets.QSpinBox()
      self.elevation.setRange(0, maps.cell_fields()[ELEVATION_FIELD][0])
      self.elevation.setSpecialValueText("any level")
      self.elevation.setKeyboardTracking(False)
      self.elevation.valueChanged.connect(lambda v: self._set(elevation=v))
      ## Warp: destination map (or "dynamic", the game decides when it fires).
      self.to = QtWidgets.QComboBox()
      self.to.setToolTip(f"The map it lands on; {events.dynamic_to()!r}: the game decides when the warp fires (the "
                         "exit of a shared interior back to where the player came from)")
      self.to.activated.connect(lambda _i: self._set(to=self.to.currentText()))
      ## Warp: destination warp number.
      self.warp = QtWidgets.QSpinBox()
      self.warp.setRange(0, MAX_WARP)
      self.warp.setKeyboardTracking(False)
      self.warp.valueChanged.connect(lambda v: self._set(warp=v))
      ## Warp: what fires it (the engine's step, press, arrow, door, none).
      self.trigger = QtWidgets.QComboBox()
      self.trigger.addItems(events.warp_triggers())
      self.trigger.setToolTip("step: arriving on the cell warps; press: pressing the direction while standing "
                              "on it warps; arrow: the same, facing that way already (map-edge arrows); door: "
                              "pressing the direction facing it from the cell before it (the game opens the door); "
                              "none: never fires (a landing other warps name)")
      self.trigger.activated.connect(lambda _i: self._trigger_chosen())
      ## Warp: press direction.
      self.direction = QtWidgets.QComboBox()
      self.direction.addItems(events.DIRECTIONS)
      self.direction.activated.connect(lambda _i: self._set(direction=self.direction.currentText()))
      ## Warp: transition ("" = the world's default).
      self.transition = QtWidgets.QComboBox()
      self.transition.addItems([DEFAULT_TRANSITION] + events.TRANSITIONS)
      self.transition.setToolTip("How the screen changes on this warp; the world's default when not set "
                                 "(the Locations tab sets it)")
      self.transition.activated.connect(lambda _i: self._set(transition=None if self.transition.currentIndex() == 0
                                                             else self.transition.currentText()))
      ## Warp: the door animation it binds to its cell ("" none; an editable list of the game's doors).
      self.door = QtWidgets.QComboBox()
      self.door.setEditable(True)
      self.door.setToolTip("The door animation (an asset door:NAME of the game's asset manifest) this warp's cell "
                           "plays when the warp sequence opens it; it wins over a binding by metatile (World > "
                           "Doors & draw order). Empty: none")
      self.door.activated.connect(lambda _i: self._door_chosen())
      self.door.lineEdit().editingFinished.connect(lambda: self._door_chosen())
      ## Trigger / sign: script.
      self.script = QtWidgets.QComboBox()
      self.script.setEditable(True)
      self.script.activated.connect(lambda _i: self._set(script=self.script.currentText().strip() or None))
      self.script.lineEdit().editingFinished.connect(
         lambda: self._set(script=self.script.currentText().strip() or None))
      ## Trigger: condition variable ("" = always).
      self.var = QtWidgets.QComboBox()
      self.var.activated.connect(lambda _i: self._var_chosen())
      ## Trigger: the variable's value that fires.
      self.value = QtWidgets.QSpinBox()
      self.value.setRange(MIN_VALUE, MAX_VALUE)
      self.value.setKeyboardTracking(False)
      self.value.valueChanged.connect(lambda v: self._set(value=v) if self.var.currentText() else None)
      ## Trigger: how it runs (step: locks the walker; immediate: to its end at once).
      self.run_box = QtWidgets.QComboBox()
      self.run_box.addItems(events.trigger_runs())
      self.run_box.setToolTip("step: the walker stops and the script runs (it may show messages and wait); "
                              "immediate: the script runs to its end at once, the walker keeps walking and the "
                              "cell's next events are still checked (its script may not wait)")
      self.run_box.activated.connect(lambda _i: self._set(run=None if self.run_box.currentText() == events.STEP
                                                         else self.run_box.currentText()))
      ## Why the engine refuses the trigger's run (an immediate trigger whose script may wait), or empty.
      self.run_problem = QtWidgets.QLabel()
      self.run_problem.setWordWrap(True)
      self.run_problem.setStyleSheet(f"color: {PROBLEM_COLOR};")
      ## Sign: the facing it needs.
      self.facing = QtWidgets.QComboBox()
      self.facing.addItems(["any"] + events.DIRECTIONS)
      self.facing.activated.connect(lambda _i: self._set(facing=None if self.facing.currentText() == "any"
                                                         else self.facing.currentText()))
      ## Sign: flag that hides it ("" = none).
      self.flag = QtWidgets.QComboBox()
      self.flag.setToolTip("Once this flag is set the sign is gone (hidden items: the script sets it)")
      self.flag.activated.connect(lambda _i: self._set(flag=self.flag.currentText() or None))
      ## Rows per kind: label -> (widget, kinds shown for).
      self.rows = [("Cell (x, y)", cell, set(events.KINDS)), ("Level", self.elevation, set(events.KINDS)),
                   ("To map", self.to, {"warps"}), ("Its warp", self.warp, {"warps"}),
                   ("Fires on", self.trigger, {"warps"}), ("Direction", self.direction, {"warps"}),
                   ("Transition", self.transition, {"warps"}), ("Door", self.door, {"warps"}),
                   ("Script", self.script, {"triggers", "signs"}), ("While variable", self.var, {"triggers"}),
                   ("Holds", self.value, {"triggers"}), ("Runs", self.run_box, {"triggers"}),
                   ("", self.run_problem, {"triggers"}), ("Read facing", self.facing, {"signs"}),
                   ("Gone once", self.flag, {"signs"})]
      for label, widget, _kinds in self.rows:
         self.form.addRow(label, widget)

      # -- world
      world = QtWidgets.QGroupBox("World")
      wl = QtWidgets.QVBoxLayout(world)
      ## Scripts manifest line.
      self.scripts_label = QtWidgets.QLabel()
      self.scripts_label.setWordWrap(True)
      wl.addWidget(self.scripts_label)
      wl.addWidget(button("Scripts manifest...", lambda: self.choose_scripts(),
                          "The scripts manifest (capsule.scripts/1) events take scripts, flags and variables "
                          "from; the game's project.json must name the same file"))
      wl.addWidget(QtWidgets.QLabel("Step hooks (game code runs every period-th step)"))
      ## Step hooks.
      self.hooks = QtWidgets.QListWidget()
      self.hooks.setMaximumHeight(HOOK_LIST_HEIGHT)
      wl.addWidget(self.hooks)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add", lambda: self.add_hook()))
      row.addWidget(button("Remove", lambda: self.remove_hook(), "Hook IDs after it shift down"))
      wl.addLayout(row)
      wl.addStretch(1)

      ## Problems.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)

      left = QtWidgets.QVBoxLayout()
      left.addLayout(top)
      left.addWidget(self.tree, 1)
      left.addLayout(adds)
      left.addWidget(form_box)
      left.addWidget(self.problems)
      split_box(left)   # [RZ] events over the chosen event's form
      lay = QtWidgets.QHBoxLayout(self)
      lay.addLayout(left, EVENTS_STRETCH)
      lay.addWidget(world, WORLD_STRETCH)
      split_box(lay)   # [RZ] events | world: the user drags the boundary
      self.refresh()

   # -- host ---------------------------------------------------------------------------------

   def project(self) -> Project | None:
      """!The host's world Project.
      @return Project, or None
      """
      return self.host_project()

   def map_doc(self) -> Document | None:
      """!The shown map's Document.
      @return Document, or None
      """
      p = self.project()
      if p is None or self.map_name not in p.map_names():
         return None
      return p.map(self.map_name)

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the document of the last edit from this tab, else the shown map.
      @return Document, or None
      """
      p = self.project()
      if p is None:
         return None
      last = self._last_doc
      if last is not None and last in p.documents() and (last.undo_label() or last.redo_label()):
         return last
      return self.map_doc()

   def _edit(self, label: str, fn: Callable[[], object], doc: Document) -> bool:
      """!Runs an edit through the host.
      @param label  undo label
      @param fn     callable
      @param doc    the Document it changes
      @return True when it went through
      """
      self._last_doc = doc
      return self.host.run_edit(label, fn, doc)

   def _follow(self) -> None:
      """!Switches to the map the host's map panel shows (when following).
      @return None
      """
      sel = getattr(self.host, "selected_map", None)
      name = sel() if callable(sel) and self.follow.isChecked() else None
      if name is not None and name != self.map_name:
         self.map_name = name
         self.refresh()

   def document_replaced(self) -> None:
      """!Another world was opened.
      @return None
      """
      self.map_name = None
      self._last_doc = None
      maptools.SELECTION.clear()
      self.refresh()

   def showEvent(self, event: QtGui.QShowEvent) -> None:
      """!Follows the Map tab's map when shown.
      @param event  QShowEvent
      @return None
      """
      super().showEvent(event)
      self._follow()
      self.refresh()

   # -- refresh -------------------------------------------------------------------------------

   def selected(self) -> tuple[str, int, JsonDict] | None:
      """!The chosen event.
      @return (kind, index, event), or None
      """
      return maptools.selected(self.map_doc(), self.map_name)

   def refresh(self) -> None:
      """!Re-reads the world, the map's events and the chosen one.
      @return None
      """
      p = self.project()
      self._filling = True
      try:
         set_enabled(self, p is not None)
         if p is None:
            return
         if self.map_name not in p.map_names():
            self.map_name = p.map_names()[0] if p.map_names() else None
         try:
            self.names = events.names(p)
         except ENGINE_ERRORS as e:
            self.names = {"scripts": [], "flags": [], "vars": {}, "error": str(e)}
         self._fill_maps(p)
         self._fill_list()
         self._fill_form(p)
         self._fill_world(p)
         self._fill_problems(p)
      finally:
         self._filling = False

   def _fill_maps(self, p: Project) -> None:
      """!Map and area choosers.
      @param p  Project
      @return None
      """
      names = p.map_names()
      self.map_box.clear()
      self.map_box.addItems(names)
      if self.map_name:
         self.map_box.setCurrentText(self.map_name)
      self.area.clear()
      doc = self.map_doc()
      self.unpainted.setChecked(doc is not None and doc.data.get("unpainted_events") is True)
      if doc is None:
         return
      self.area.addItem("its own area", None)
      for n in names:
         if n != self.map_name:
            self.area.addItem(n, n)
      root = events.area(doc, self.map_name)
      # a map that is its own area root shows "its own area" (data None); an unknown root shows it too
      self.area.setCurrentIndex(max(0, self.area.findData(None if root == self.map_name else root)))

   def _fill_list(self) -> None:
      """!The event list.
      @return None
      """
      self.tree.clear()
      doc = self.map_doc()
      if doc is None:
         return
      chosen = self.selected()
      for kind, i, e in events.all_events(doc):
         at = e.get("at", ["?", "?"])
         item = QtWidgets.QTreeWidgetItem([f"{events.KINDS[kind]} {i}", f"{at[0]},{at[1]}",
                                           events.describe(kind, e)])
         item.setData(0, ITEM_KEY_ROLE, (kind, i))
         self.tree.addTopLevelItem(item)
         if chosen is not None and (chosen[0], chosen[1]) == (kind, i):
            self.tree.setCurrentItem(item)

   def _fill_form(self, p: Project) -> None:
      """!The chosen event's fields.
      @param p  Project
      @return None
      """
      chosen = self.selected()
      kind = chosen[0] if chosen else None
      for label, widget, kinds in self.rows:
         shown = kind in kinds
         lw = self.form.labelForField(widget)
         # the row's label and its widget, or every widget of a row that is a layout
         for w in ([lw] if lw else []) + ([widget] if isinstance(widget, QtWidgets.QWidget) else
                                          [widget.itemAt(i).widget() for i in range(widget.count())]):
            if w is not None:
               w.setVisible(shown)
      if chosen is None:
         return
      _kind, _i, e = chosen
      at = e.get("at", [0, 0])
      self.x.setValue(at[0])
      self.y.setValue(at[1])
      self.elevation.setValue(e.get("elevation", 0))
      self.to.clear()
      self.to.addItems(p.map_names() + [events.dynamic_to()])
      self.to.setCurrentText(e.get("to", ""))
      self.warp.setValue(e.get("warp", 0))
      self.trigger.setCurrentText(e.get("trigger", events.STEP))
      self.direction.setCurrentText(e.get("direction", "down"))
      self.direction.setEnabled(e.get("trigger", events.STEP) in events.DIRECTED)
      self.transition.setCurrentText(e.get("transition", DEFAULT_TRANSITION))
      self.door.clear()
      self.door.addItem("")
      try:   # the doors the game's asset manifests and the world's bindings name
         self.door.addItems(doors.door_keys(p))
      except ENGINE_ERRORS:
         pass
      self.door.setCurrentText(e.get("door", ""))
      self.script.clear()
      self.script.addItems(self.names["scripts"])
      self.script.setCurrentText(e.get("script", ""))
      self.var.clear()
      self.var.addItem("")
      self.var.addItems(list(self.names["vars"]))
      self.var.setCurrentText(e.get("var", ""))
      self.value.setEnabled("var" in e)
      self.value.setValue(e.get("value", 0))
      self.run_box.setCurrentText(e.get("run", events.STEP))
      problem = events.immediate_problem(e, self.names.get("waiting", [])) if _kind == "triggers" else None
      self.run_problem.setText(problem or "")
      self.run_problem.setVisible(bool(problem))
      self.facing.setCurrentText(e.get("facing", "any"))
      self.flag.clear()
      self.flag.addItem("")
      self.flag.addItems(self.names["flags"])
      self.flag.setCurrentText(e.get("flag", ""))

   def _fill_world(self, p: Project) -> None:
      """!Scripts manifest and step hooks.
      @param p  Project
      @return None
      """
      rel = p.world.data.get("scripts")
      text = f"Scripts: {rel}" if rel else "Scripts: none (events that run scripts need one)"
      if self.names["error"] and rel:
         text += f"\n{self.names['error']}"
      elif rel:
         text += (f"\n{len(self.names['scripts'])} scripts, {len(self.names['flags'])} flags, "
                  f"{len(self.names['vars'])} variables")
      self.scripts_label.setText(text)
      self.hooks.clear()
      for h in events.step_hooks(p):
         phase = f", phase {h['phase']}" if "phase" in h else ""
         self.hooks.addItem(f"{h.get('name')}: every {h.get('period')} steps{phase}")

   def _fill_problems(self, p: Project) -> None:
      """!The map's event problems.
      @param p  Project
      @return None
      """
      try:
         found = events.diagnostics(p, self.map_name)
      except ENGINE_ERRORS as e:
         self.problems.setText(f"error: {e}")
         return
      self.problems.setText("\n".join(f"{d.level}: {d.message}" for d in found) or "No event problems.")

   # -- choosing ----------------------------------------------------------------------------------

   def _map_chosen(self, name: str) -> None:
      """!Another map in the chooser.
      @param name  map name
      @return None
      """
      if self._filling or not name or name == self.map_name:
         return
      self.follow.setChecked(False)
      self.map_name = name
      maptools.SELECTION.clear()
      self.refresh()

   def _event_chosen(self) -> None:
      """!Another event in the list.
      @return None
      """
      if self._filling:
         return
      item = self.tree.currentItem()
      if item is None:
         return
      kind, i = item.data(0, ITEM_KEY_ROLE)
      e = events.events(self.map_doc(), kind)[i]
      maptools.select(self.map_name, kind, i, e.get("at"))
      self._filling = True
      try:
         self._fill_form(self.project())
      finally:
         self._filling = False

   # -- editing ----------------------------------------------------------------------------------

   def _set(self, **fields: FieldValue) -> None:
      """!Changes fields of the chosen event.
      @param fields  {field: value or None}
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      if self._filling or chosen is None or doc is None:
         return
      kind, i, e = chosen
      fields = {k: v for k, v in fields.items() if k in events.FIELDS[kind]}
      # nothing changes (a missing elevation is 0, any other missing field None)
      if all(e.get(k, None if k != "elevation" else 0) == v for k, v in fields.items()):
         return
      self._edit(f"Change {events.KINDS[kind]}", lambda: events.set_event(doc, kind, i, **fields), doc)

   def _door_chosen(self) -> None:
      """!The warp's door changed ("" removes it).
      @return None
      """
      text = self.door.currentText().strip()
      self._set(door=text or None)

   def _moved(self) -> None:
      """!The cell fields changed.
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      if self._filling or chosen is None or doc is None:
         return
      kind, i, e = chosen
      x, y = self.x.value(), self.y.value()
      if e.get("at") == [x, y]:
         return
      if self._edit(f"Move {events.KINDS[kind]}", lambda: events.move_event(doc, kind, i, x, y), doc):
         maptools.select(self.map_name, kind, i, [x, y])

   def _unpainted_toggled(self, on: bool) -> None:
      """!The map's events may (or may not) stand on unpainted cells.
      @param on  checked
      @return None
      """
      doc = self.map_doc()
      if doc is not None and not self._filling:
         self._edit("Unpainted events", lambda: events.set_unpainted_events(doc, on), doc)

   def _trigger_chosen(self) -> None:
      """!What fires the warp (step, press, arrow, door or none).
      @return None
      """
      trig = self.trigger.currentText()
      if trig in events.DIRECTED:   # press, arrow, door take a direction
         self._set(trigger=trig, direction=self.direction.currentText())
      elif trig == "none":   # a landing only
         self._set(trigger=trig, direction=None)
      else:
         self._set(trigger=None, direction=None)

   def _var_chosen(self) -> None:
      """!The trigger's condition variable.
      @return None
      """
      v = self.var.currentText()
      if v:
         self._set(var=v, value=self.value.value())
      else:
         self._set(var=None, value=None)

   def _area_chosen(self) -> None:
      """!The area root.
      @return None
      """
      doc = self.map_doc()
      if self._filling or doc is None:
         return
      root = self.area.currentData()
      if (root or self.map_name) == events.area(doc, self.map_name):   # None: the map is its own area
         return
      name = self.map_name
      self._edit("Set area", lambda: events.set_area(doc, name, root), doc)

   def add(self, kind: str) -> None:
      """!Adds an event at the form's cell (or 0,0).
      @param kind  event kind
      @return None
      """
      doc = self.map_doc()
      if doc is None:
         self.explain(f"Add {kind}", "map")
         return
      x, y = self.x.value(), self.y.value()
      out: dict[str, int] = {}

      def run() -> None:
         out["i"] = events.add_event(doc, kind, x, y)
      if self._edit(f"Add {events.KINDS[kind]}", run, doc):
         maptools.select(self.map_name, kind, out["i"], [x, y])
         self.refresh()

   def remove(self) -> None:
      """!Removes the chosen event.
      @return None
      """
      chosen = self.selected()
      p = self.project()
      if chosen is None or p is None:
         self.explain("Remove", "event")
         return
      kind, i, _e = chosen
      try:
         events.remove_event(p, self.map_name, kind, i)
      except DocumentError as e:
         QtWidgets.QMessageBox.warning(self, "Events", str(e))
         return
      self._last_doc = self.map_doc()
      maptools.SELECTION.clear()
      self.host.changed()

   def choose_scripts(self) -> None:
      """!Names the world's scripts manifest.
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("Scripts manifest")
         return
      path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Scripts manifest", str(p.base),
                                                      "Scripts manifest (scripts.json *.json);;All files (*)")
      if not path:
         return
      self._edit("Set scripts manifest", lambda: events.set_scripts(p, Path(path)), p.world)

   def add_hook(self) -> None:
      """!Adds a step hook.
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("Add step hook")
         return
      name, ok = QtWidgets.QInputDialog.getText(self, "Step hook", "Name (an identifier, e.g. step_counter):")
      if not ok or not name.strip():
         return
      period, ok = QtWidgets.QInputDialog.getInt(self, "Step hook", "Every how many steps (a power of two)?",
                                                 DEFAULT_HOOK_PERIOD, 1, MAX_HOOK_PERIOD)
      if not ok:
         return
      self._edit("Add step hook", lambda: events.add_hook(p, name.strip(), period), p.world)

   def remove_hook(self) -> None:
      """!Removes the chosen step hook.
      @return None
      """
      p = self.project()
      row = self.hooks.currentRow()
      hooks = events.step_hooks(p) if p is not None else []
      if not 0 <= row < len(hooks):
         self.explain("Remove step hook", "step hook")
         return
      name = hooks[row].get("name")
      self._edit("Remove step hook", lambda: events.remove_hook(p, name), p.world)
