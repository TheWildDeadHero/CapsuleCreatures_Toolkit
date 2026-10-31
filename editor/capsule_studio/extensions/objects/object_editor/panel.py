"""!The Objects panel: a map's people, spotters and pickups (B-21, D-17).

Shown on its own as the object editor app, and as a tab of the Studio's
World page after Events and Locations, where it follows the map chosen in
the Map tab. The list shows the map's objects by local ID; the
form under it edits the chosen one (name, cell, level, sprite, facing, movement and range,
speed, frequency, movement options, trigger, script, hide flag, self
switches, spotter sight and the flag that ends it), with the scripts and flags the
scripts manifest offers and the sprites of the game's assets. A custom
movement's move route is typed into a route box, one step per line, checked
with the engine's route compiler as it is typed. The pages box edits the
object's event pages: their conditions (a flag, a variable, self switches)
and the fields each replaces (or "absent"). The Objects map tool
places, moves and removes objects by clicking. Every change goes through the
host's run_edit() on the map's Document, so Undo / Redo, the unsaved mark
and Save work as in the other panels; everything here is also a
`capsule-studio objects` command (commands.py).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6 import QtWidgets

from capsule_studio.core import engine, events, map_field, maps, objects, script_words
from capsule_studio.core.document import DocumentError
from capsule_studio.ui.panel import EditorPanel
from capsule_studio.ui.panes import split_box
from capsule_studio.ui.widgets import button, lock_view, set_enabled, view_locked

from . import maptools
from .movement_args import MovementArgsBox

if TYPE_CHECKING:
   from PySide6 import QtGui

   from capsule_studio.core.document import Document
   from capsule_studio.core.world import Project
   from capsule_studio.ui.world_shell import WorldWindow

## A JSON object (a map object, a page or a route).
JsonDict = dict[str, Any]
## An object or page field's value (None removes the field).
FieldValue = int | str | bool | list[int] | dict[str, bool] | None
## A page condition's value (None removes the condition).
WhenValue = int | str | bool | list[str] | None

## Errors meaning the engine (its compilers) is missing or too old.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError)
## [S5] The route box's tip without the engine's route compiler.
ROUTE_TIP_FALLBACK = "Steps: up / down / left / right [n], wait n, face X, ... (one per line)"
## Page choosers' first entry: the object's own value.
KEEP = "(the object's)"
## Option check box labels.
OPTION_LABELS = {"walk_anim": "walk anim", "step_anim": "step anim", "direction_fix": "fixed facing",
                 "through": "through", "on_top": "on top"}
## Item data role holding an object's local ID (Qt.ItemDataRole.UserRole).
ITEM_KEY_ROLE = 256
## Object list column of the local ID.
ID_COLUMN = 0
## Object list column of the name.
NAME_COLUMN = 1
## Object list column of the cell.
CELL_COLUMN = 2
## Width of the object list's ID column (pixels).
ID_COLUMN_WIDTH = 40
## Width of the object list's Name column (pixels).
NAME_COLUMN_WIDTH = 100
## Width of the object list's Cell column (pixels).
CELL_COLUMN_WIDTH = 60
## Tallest a route box's steps grow (pixels).
ROUTE_TEXT_HEIGHT = 90
## Tallest the page list grows (pixels).
PAGE_LIST_HEIGHT = 90
## Smallest cell coordinate the form takes.
MIN_CELL = -16384
## Largest cell coordinate the form takes.
MAX_CELL = 16383
## The attribute cell field whose highest value is the highest level an object may name (core.maps.cell_fields():
## the engine's; 0 is any level).
ELEVATION_FIELD = "elevation"
## Smallest value a page's variable condition may name (signed 32 bits).
MIN_VALUE = -2**31
## Largest value a page's variable condition may name (signed 32 bits).
MAX_VALUE = 2**31 - 1
## Numbers in a range [x, y].
RANGE_LENGTH = 2
## The object view a map gets when its box is ticked (I3: the reference games' view, cells left, right, up, down).
DEFAULT_VIEW = (9, 10, 7, 9)
## Movement option check boxes per row.
OPTION_COLUMNS = 3
## Stretch of the object list column.
LIST_STRETCH = 3
## Stretch of the form column.
FORM_STRETCH = 2


class RouteBox(QtWidgets.QWidget):
   """!A move route editor: steps one per line, repeat and skip, checked as typed
   (objects.route_error()); Apply hands them to a callback."""

   def __init__(self, on_apply: Callable[[str, bool, bool], object],
                parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the box.
      @param on_apply  callable(text, repeat, skip)
      @param parent    parent widget
      """
      super().__init__(parent)
      ## callable(steps text, repeat, skip) the Apply button calls.
      self.on_apply = on_apply
      ## Flags the steps may name (None: not checked).
      self.flags = None
      ## The steps, one per line.
      self.text = QtWidgets.QPlainTextEdit()
      self.text.setPlaceholderText("one step per line, e.g.\nleft 2\nwait 30\nright 2")
      self.text.setToolTip(route_tip())
      self.text.setMaximumHeight(ROUTE_TEXT_HEIGHT)
      self.text.textChanged.connect(lambda: self.recheck())
      ## Start over at the end.
      self.repeat = QtWidgets.QCheckBox("repeat")
      self.repeat.setChecked(True)
      self.repeat.toggled.connect(lambda _on: self.recheck())
      ## Skip blocked steps.
      self.skip = QtWidgets.QCheckBox("skip blocked")
      self.skip.toggled.connect(lambda _on: self.recheck())
      ## Apply the route.
      self.apply_button = button("Apply route", lambda: self.apply(), "Store the steps (one undo step)")
      ## What the route compiler says.
      self.status = QtWidgets.QLabel()
      self.status.setWordWrap(True)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.repeat)
      row.addWidget(self.skip)
      row.addStretch(1)
      row.addWidget(self.apply_button)
      lay = QtWidgets.QVBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(self.text)
      lay.addLayout(row)
      lay.addWidget(self.status)

   def fill(self, route: JsonDict | None) -> None:
      """!Shows a route.
      @param route  {"steps", "repeat", "skip"}, or None
      @return None
      """
      rt = route if isinstance(route, dict) else {}
      for w in (self.text, self.repeat, self.skip):   # filling is no edit: no recheck per widget
         w.blockSignals(True)
      self.text.setPlainText("\n".join(s for s in rt.get("steps") or [] if isinstance(s, str)))
      self.repeat.setChecked(rt.get("repeat", True) is not False)
      self.skip.setChecked(rt.get("skip", False) is True)
      for w in (self.text, self.repeat, self.skip):
         w.blockSignals(False)
      self.recheck()

   def error(self) -> str | None:
      """!The route compiler's verdict on the typed steps.
      @return message, or None
      """
      try:
         steps = objects.route_steps(self.text.toPlainText())
      except DocumentError as e:
         return str(e)
      return objects.route_error(steps, self.repeat.isChecked(), self.skip.isChecked(), self.flags)

   def recheck(self) -> None:
      """!Shows the verdict.
      @return None
      """
      e = self.error()
      self.status.setText(f"error: {e}" if e else "The steps compile.")

   def apply(self) -> None:
      """!Hands the route to the callback.
      @return None
      """
      self.on_apply(self.text.toPlainText(), self.repeat.isChecked(), self.skip.isChecked())

   def set_editable(self, on: bool) -> None:
      """!Lets the route be edited, or shows it read-only (another movement, or no page chosen). Not
      setEnabled(False): the steps box keeps its scroll bar, so a long route can still be read.
      @param on  True to edit
      @return None
      """
      lock_view(self.text, not on)
      for w in (self.repeat, self.skip, self.apply_button, self.status):
         w.setEnabled(on)

   def editable(self) -> bool:
      """!Whether the route can be edited (set_editable()).
      @return True when it can
      """
      return not view_locked(self.text)


class ObjectsPanel(EditorPanel):
   """!Edits map objects (core.objects)."""

   ## See EditorPanel.panel_id.
   panel_id = "objects"
   ## See EditorPanel.title.
   title = "Objects"

   def __init__(self, host: WorldWindow, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The map shown, or None.
      self.map_name = None
      ## True while widgets are being filled.
      self._filling = False
      ## Names from the scripts manifest (events.names()).
      self.names = {"scripts": [], "flags": [], "vars": {}, "error": None}
      ## Sprites of the game's assets ('sprite:NAME'), or None when unknown.
      self.sprites = None
      ## Row of the chosen page (kept across refreshes), or -1.
      self._page_row = -1

      # -- map
      ## The map shown.
      self.map_box = QtWidgets.QComboBox()
      self.map_box.currentTextChanged.connect(lambda t: self._map_chosen(t))
      ## Follow the map chosen in the Map tab.
      self.follow = QtWidgets.QCheckBox("Follow the Map tab")
      self.follow.setChecked(True)
      self.follow.toggled.connect(lambda on: on and self._follow())
      self.follow.setVisible(getattr(host, "shows_map", lambda: True)())   # no Map tab: nothing to follow
      top = QtWidgets.QHBoxLayout()
      top.addWidget(QtWidgets.QLabel("Map"))
      top.addWidget(self.map_box, 1)
      top.addWidget(self.follow)
      # I3: the map's object view (objects spawn near the player, up to 64) and stacked objects
      ## The object view is on.
      self.view_on = QtWidgets.QCheckBox("Object view")
      self.view_on.setToolTip("Objects spawn when the player comes this close (cells left, right, up, down) and go "
                              "when both they and their start are outside; a map with a view may list up to "
                              f"{objects._obc().MAX_VIEW_OBJECTS} objects, one without at most "
                              f"{objects._obc().MAX_OBJECTS}")
      self.view_on.clicked.connect(lambda on: self._view_changed())
      ## Its four sides.
      self.view = [QtWidgets.QSpinBox() for _ in objects.VIEW_SIDES]
      for side, w in zip(objects.VIEW_SIDES, self.view):
         w.setRange(0, engine.tool("map_compiler").MAX_VIEW_CELLS)
         w.setToolTip(f"cells {side} of the player")
         w.setKeyboardTracking(False)
         w.valueChanged.connect(lambda _v: self._view_changed())
      ## Objects may share a cell.
      self.stacked = QtWidgets.QCheckBox("Stacked objects")
      self.stacked.setToolTip("Objects may share a cell (data whose flags keep one of them there at a time)")
      self.stacked.clicked.connect(lambda on: self._stacked_changed(on))
      view_row = QtWidgets.QHBoxLayout()
      view_row.addWidget(self.view_on)
      for w in self.view:
         view_row.addWidget(w)
      view_row.addWidget(self.stacked)
      view_row.addStretch(1)

      # -- list
      ## The map's objects.
      self.tree = QtWidgets.QTreeWidget()
      self.tree.setHeaderLabels(["ID", "Name", "Cell", "What"])
      self.tree.setRootIsDecorated(False)
      self.tree.setColumnWidth(ID_COLUMN, ID_COLUMN_WIDTH)
      self.tree.setColumnWidth(NAME_COLUMN, NAME_COLUMN_WIDTH)
      self.tree.setColumnWidth(CELL_COLUMN, CELL_COLUMN_WIDTH)
      self.tree.currentItemChanged.connect(lambda _a, _b: self._object_chosen())
      adds = QtWidgets.QHBoxLayout()
      adds.addWidget(button("Add object", lambda: self.add(),
                            "A new object at the cell in the form (or use the Objects map tool to click one)"))
      adds.addWidget(button("Remove", lambda: self.remove(),
                            "Remove the chosen object (the local IDs after it move down by one)"))

      # -- form
      form_box = QtWidgets.QGroupBox("Chosen object")
      ## The form.
      self.form = QtWidgets.QFormLayout(form_box)
      ## Name (world_ids.h OBJ_<MAP>_<NAME>).
      self.name = QtWidgets.QLineEdit()
      self.name.editingFinished.connect(lambda: self._renamed())
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
      ## Sprite asset reference.
      self.sprite = QtWidgets.QComboBox()
      self.sprite.setEditable(True)
      self.sprite.setToolTip("The sprite asset ('sprite:NAME'); one the game's assets lack is invisible in game")
      self.sprite.activated.connect(lambda _i: self._sprite_chosen())
      self.sprite.lineEdit().editingFinished.connect(lambda: self._sprite_chosen())
      ## Facing.
      self.facing = QtWidgets.QComboBox()
      self.facing.addItems(objects.DIRECTIONS)
      self.facing.activated.connect(lambda _i: self._set(facing=self.facing.currentText()))
      ## Movement type.
      self.movement = QtWidgets.QComboBox()
      self.movement.addItems(objects.movements())
      self.movement.setToolTip("static: stands; look_around: turns now and then; wander: random steps in its "
                               "range box; pace_*: walks to and fro within its range; approach: steps towards "
                               "the player; custom: follows its move route. I3 (the reference games' types): turn, "
                               "roam, rotate, patrol, circuit, mirror (copies the player), in_place, invisible")
      self.movement.activated.connect(lambda _i: self._set(movement=self.movement.currentText()))
      ## I3: the movement's settings.
      self.movement_args = MovementArgsBox(lambda args: self._set(movement_args=args))
      ## Range box, cells each way.
      self.range_x = QtWidgets.QSpinBox()
      ## Range box rows.
      self.range_y = QtWidgets.QSpinBox()
      for w in (self.range_x, self.range_y):
         w.setRange(0, objects.max_range())
         w.setKeyboardTracking(False)
         w.valueChanged.connect(lambda _v: self._range_changed())
      rng = QtWidgets.QHBoxLayout()
      rng.addWidget(self.range_x)
      rng.addWidget(self.range_y)
      ## Talk script ("" = none).
      self.script = QtWidgets.QComboBox()
      self.script.setEditable(True)
      self.script.activated.connect(lambda _i: self._set(script=self.script.currentText().strip() or None))
      self.script.lineEdit().editingFinished.connect(
         lambda: self._set(script=self.script.currentText().strip() or None))
      ## Hide flag ("" = none).
      self.flag = QtWidgets.QComboBox()
      self.flag.setToolTip("The object is hidden while this flag is set (a script sets it: items picked up, "
                           "people who left)")
      self.flag.activated.connect(lambda _i: self._set(flag=self.flag.currentText() or None))
      ## Spotter sight (0 = not a spotter).
      self.sight = QtWidgets.QSpinBox()
      self.sight.setRange(0, objects.MAX_SIGHT)
      self.sight.setSpecialValueText("not a spotter")
      self.sight.setToolTip("A spotter: when it faces the player within this many cells, it walks up and runs "
                            "its script")
      self.sight.setKeyboardTracking(False)
      self.sight.valueChanged.connect(lambda v: self._set(sight=v or None))
      ## Spotter: flag that turns the sight off ("" = none).
      self.until = QtWidgets.QComboBox()
      self.until.setToolTip("Once this flag is set (by its script, say), the spotter no longer spots the player")
      self.until.activated.connect(lambda _i: self._set(until=self.until.currentText() or None))
      ## Speed (1-4; 2 = walking).
      self.speed = QtWidgets.QSpinBox()
      self.speed.setRange(*objects.SPEEDS)
      self.speed.setKeyboardTracking(False)
      self.speed.valueChanged.connect(lambda v: self._set(speed=v))
      ## Frequency (1-5): how often it moves.
      self.frequency = QtWidgets.QSpinBox()
      self.frequency.setRange(*objects.FREQUENCIES)
      self.frequency.setKeyboardTracking(False)
      self.frequency.valueChanged.connect(lambda v: self._set(frequency=v))
      motion = QtWidgets.QHBoxLayout()
      motion.addWidget(self.speed)
      motion.addWidget(QtWidgets.QLabel("frequency"))
      motion.addWidget(self.frequency)
      ## Movement option check boxes {option: QCheckBox}.
      self.options = {}
      ## Their row.
      self.options_row = self._option_boxes(self.options, lambda k, on: self._option(k, on))
      ## The move route (movement custom).
      self.route = RouteBox(lambda text, rep, skip: self._apply_route(text, rep, skip, None))
      ## What starts the script.
      self.trigger = QtWidgets.QComboBox()
      self.trigger.addItems(objects.TRIGGERS)
      self.trigger.setToolTip("action: the player faces it and presses A; player_touch: the player walks into "
                              "it; event_touch: it walks into the player (or the player into it); autorun: runs "
                              "again and again, the player waits; parallel: runs alongside play")
      self.trigger.activated.connect(lambda _i: self._set(trigger=self.trigger.currentText()))
      ## F2: its kind (one of the world's object kinds; field actions target it), "" = none.
      self.kind = QtWidgets.QComboBox()
      self.kind.setToolTip("A kind of the world's object kinds (a bush, a boulder): the battle structure's field "
                           "actions on that kind are offered when the player faces it and it has no script")
      self.kind.activated.connect(lambda _i: self._set(kind=self.kind.currentText() or None))
      ## Self switches A-D even when no page or script needs them.
      self.self_switches = QtWidgets.QCheckBox("give it self switches A-D")
      self.self_switches.setToolTip("Objects whose pages or scripts use self switches get them anyway")
      self.self_switches.toggled.connect(lambda on: self._set(self_switches=on or None))
      ## Rows: (label, widget).
      self.rows = [("Name", self.name), ("Cell (x, y)", cell), ("Level", self.elevation), ("Sprite", self.sprite),
                   ("Facing", self.facing), ("Movement", self.movement), ("Settings", self.movement_args),
                   ("Range (x, y)", rng),
                   ("Speed", motion), ("Options", self.options_row), ("Move route", self.route),
                   ("Script", self.script), ("Trigger", self.trigger), ("Kind", self.kind), ("Hidden while", self.flag),
                   ("Self switches", self.self_switches), ("Spotter sight", self.sight),
                   ("Sight off once", self.until)]
      for label, widget in self.rows:
         self.form.addRow(label, widget)

      # -- pages
      pg_box = QtWidgets.QGroupBox("Pages (the last whose conditions all hold applies)")
      pl = QtWidgets.QVBoxLayout(pg_box)
      ## The chosen object's pages.
      self.page_list = QtWidgets.QListWidget()
      self.page_list.setMaximumHeight(PAGE_LIST_HEIGHT)
      self.page_list.currentRowChanged.connect(lambda _r: self._page_chosen())
      pl.addWidget(self.page_list)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add", lambda: self.add_page(), "A page waiting for a flag (or self switch A)"))
      row.addWidget(button("Remove", lambda: self.remove_page()))
      row.addWidget(button("Up", lambda: self.move_page(-1), "Earlier pages lose to later ones"))
      row.addWidget(button("Down", lambda: self.move_page(1)))
      pl.addLayout(row)
      pf = QtWidgets.QFormLayout()
      ## Page condition: a flag set ("" = none).
      self.pg_flag = QtWidgets.QComboBox()
      self.pg_flag.activated.connect(lambda _i: self._set_when({"flag": self.pg_flag.currentText() or None}))
      ## Page condition: a variable ("" = none).
      self.pg_var = QtWidgets.QComboBox()
      self.pg_var.activated.connect(lambda _i: self._set_when({"var": self.pg_var.currentText() or None}))
      ## Page condition: the variable's value.
      self.pg_value = QtWidgets.QSpinBox()
      self.pg_value.setRange(MIN_VALUE, MAX_VALUE)
      self.pg_value.setKeyboardTracking(False)
      self.pg_value.valueChanged.connect(lambda v: self._set_when({"value": v}))
      ## Page condition: equal (else at least).
      self.pg_equal = QtWidgets.QCheckBox("equal (else at least)")
      self.pg_equal.toggled.connect(lambda on: self._set_when({"equal": on or None}))
      var_row = QtWidgets.QHBoxLayout()
      var_row.addWidget(self.pg_var, 1)
      var_row.addWidget(self.pg_value)
      var_row.addWidget(self.pg_equal)
      ## Page condition: self switches on {letter: QCheckBox}.
      self.pg_self = {}
      self_row = QtWidgets.QHBoxLayout()
      for letter in objects.SELF_SWITCHES:
         box = QtWidgets.QCheckBox(letter)
         box.toggled.connect(lambda _on: self._self_changed())
         self.pg_self[letter] = box
         self_row.addWidget(box)
      self_row.addStretch(1)
      ## Page: the object is absent.
      self.pg_hidden = QtWidgets.QCheckBox("absent while this page applies")
      self.pg_hidden.toggled.connect(lambda on: self._set_page(hidden=on or None))
      ## Page: sprite.
      self.pg_sprite = QtWidgets.QComboBox()
      self.pg_sprite.setEditable(True)
      self.pg_sprite.activated.connect(lambda _i: self._set_page(sprite=self._kept(self.pg_sprite)))
      self.pg_sprite.lineEdit().editingFinished.connect(
         lambda: self._set_page(sprite=self._kept(self.pg_sprite)))
      ## Page: movement.
      self.pg_movement = QtWidgets.QComboBox()
      self.pg_movement.addItems([KEEP] + objects.movements())
      self.pg_movement.activated.connect(lambda _i: self._set_page(movement=self._kept(self.pg_movement)))
      ## Page: facing.
      self.pg_facing = QtWidgets.QComboBox()
      self.pg_facing.addItems([KEEP] + objects.DIRECTIONS)
      self.pg_facing.activated.connect(lambda _i: self._set_page(facing=self._kept(self.pg_facing)))
      ## Page: script.
      self.pg_script = QtWidgets.QComboBox()
      self.pg_script.activated.connect(lambda _i: self._set_page(script=self._kept(self.pg_script)))
      ## Page: trigger.
      self.pg_trigger = QtWidgets.QComboBox()
      self.pg_trigger.addItems([KEEP] + objects.TRIGGERS)
      self.pg_trigger.activated.connect(lambda _i: self._set_page(trigger=self._kept(self.pg_trigger)))
      ## Page: replaces the range.
      self.pg_has_range = QtWidgets.QCheckBox("own range")
      self.pg_has_range.toggled.connect(lambda _on: self._page_range())
      ## Page range x.
      self.pg_range_x = QtWidgets.QSpinBox()
      ## Page range y.
      self.pg_range_y = QtWidgets.QSpinBox()
      for w in (self.pg_range_x, self.pg_range_y):
         w.setRange(0, objects.max_range())
         w.setKeyboardTracking(False)
         w.valueChanged.connect(lambda _v: self._page_range())
      prng = QtWidgets.QHBoxLayout()
      prng.addWidget(self.pg_has_range)
      prng.addWidget(self.pg_range_x)
      prng.addWidget(self.pg_range_y)
      ## Page speed (0: the object's).
      self.pg_speed = QtWidgets.QSpinBox()
      self.pg_speed.setRange(0, objects.SPEEDS[1])
      self.pg_speed.setSpecialValueText(KEEP)
      self.pg_speed.setKeyboardTracking(False)
      self.pg_speed.valueChanged.connect(lambda v: self._set_page(speed=v or None))
      ## Page frequency (0: the object's).
      self.pg_frequency = QtWidgets.QSpinBox()
      self.pg_frequency.setRange(0, objects.FREQUENCIES[1])
      self.pg_frequency.setSpecialValueText(KEEP)
      self.pg_frequency.setKeyboardTracking(False)
      self.pg_frequency.valueChanged.connect(lambda v: self._set_page(frequency=v or None))
      pmotion = QtWidgets.QHBoxLayout()
      pmotion.addWidget(self.pg_speed)
      pmotion.addWidget(QtWidgets.QLabel("frequency"))
      pmotion.addWidget(self.pg_frequency)
      ## Page: has its own options (starting from the defaults).
      self.pg_has_options = QtWidgets.QCheckBox("own options")
      self.pg_has_options.toggled.connect(lambda on: self._set_page(options=self._page_options() if on else None))
      ## Page option check boxes.
      self.pg_options = {}
      pg_opts = QtWidgets.QVBoxLayout()
      pg_opts.addWidget(self.pg_has_options)
      pg_opts.addWidget(self._option_boxes(self.pg_options, lambda _k, _on: self._page_option()))
      ## Page: move route (makes its movement custom).
      self.pg_route = RouteBox(lambda text, rep, skip: self._apply_route(text, rep, skip, self._page_row))
      ## Page: has its own route.
      self.pg_has_route = QtWidgets.QCheckBox("own move route (movement custom)")
      self.pg_has_route.toggled.connect(lambda on: self._page_route_toggled(on))
      pg_route = QtWidgets.QVBoxLayout()
      pg_route.addWidget(self.pg_has_route)
      pg_route.addWidget(self.pg_route)
      pf.addRow("While flag", self.pg_flag)
      pf.addRow("While variable", var_row)
      pf.addRow("While self", self_row)
      pf.addRow("Hidden", self.pg_hidden)
      pf.addRow("Sprite", self.pg_sprite)
      pf.addRow("Movement", self.pg_movement)
      pf.addRow("Range", prng)
      pf.addRow("Speed", pmotion)
      pf.addRow("Options", pg_opts)
      pf.addRow("Route", pg_route)
      pf.addRow("Facing", self.pg_facing)
      pf.addRow("Script", self.pg_script)
      pf.addRow("Trigger", self.pg_trigger)
      pl.addLayout(pf)
      ## Page widgets enabled while a page is chosen (field widgets also while it is not hidden).
      self.page_fields = [self.pg_sprite, self.pg_movement, self.pg_facing, self.pg_script, self.pg_trigger,
                          self.pg_has_range, self.pg_range_x, self.pg_range_y, self.pg_speed, self.pg_frequency,
                          self.pg_has_options, self.pg_has_route, self.pg_route] + list(self.pg_options.values())
      ## Page condition widgets.
      self.page_conditions = [self.pg_flag, self.pg_var, self.pg_value, self.pg_equal, self.pg_hidden] + \
          list(self.pg_self.values())

      ## Problems.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)

      left = QtWidgets.QVBoxLayout()
      left.addLayout(top)
      left.addLayout(view_row)
      left.addWidget(self.tree, 1)
      left.addLayout(adds)
      left.addWidget(self.problems)
      inner = QtWidgets.QWidget()
      right = QtWidgets.QVBoxLayout(inner)
      right.addWidget(form_box)
      right.addWidget(pg_box)
      right.addStretch(1)
      scroll = QtWidgets.QScrollArea()
      scroll.setWidgetResizable(True)
      scroll.setWidget(inner)
      lay = QtWidgets.QHBoxLayout(self)
      lay.addLayout(left, LIST_STRETCH)
      lay.addWidget(scroll, FORM_STRETCH)
      split_box(lay)   # [RZ] objects | form: the user drags the boundary
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
      """!Undo / Redo target: the shown map.
      @return Document, or None
      """
      return self.map_doc()

   def _edit(self, label: str, fn: Callable[[], object]) -> bool:
      """!Runs an edit of the shown map through the host.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      doc = self.map_doc()
      if doc is None:
         return False
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

   def selected(self) -> tuple[int, JsonDict] | None:
      """!The chosen object.
      @return (local ID, object), or None
      """
      return maptools.selected(self.map_doc(), self.map_name)

   def refresh(self) -> None:
      """!Re-reads the world, the map's objects and the chosen one.
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
         self.sprites = objects.game_sprites(p)
         self.map_box.clear()
         self.map_box.addItems(p.map_names())
         if self.map_name:
            self.map_box.setCurrentText(self.map_name)
         self._fill_view()
         self._fill_list()
         self._fill_form()
         self._fill_problems(p)
      finally:
         self._filling = False

   def _fill_view(self) -> None:
      """!The map's object view and stacked objects (I3).
      @return None
      """
      doc = self.map_doc()
      view = objects.object_view(doc) if doc is not None else None
      self.view_on.setChecked(view is not None)
      for k, w in enumerate(self.view):
         w.setValue(view[k] if view is not None and k < len(view) else 0)
         w.setEnabled(view is not None)
      self.stacked.setChecked(doc is not None and doc.data.get("stacked_objects") is True)

   def _view_changed(self) -> None:
      """!The object view box or a side changed (one undo step on the map).
      @return None
      """
      doc = self.map_doc()
      if self._filling or doc is None:
         return
      view = [w.value() for w in self.view] if self.view_on.isChecked() else None
      if view is not None and not any(view):   # a new view: the reference games' (left/right 9 and 10, ...)
         view = [w.value() or DEFAULT_VIEW[k] for k, w in enumerate(self.view)]
      if view == objects.object_view(doc):
         return
      self._run("Object view", lambda: objects.set_object_view(doc, view))

   def _stacked_changed(self, on: bool) -> None:
      """!Whether the map's objects may share a cell (I3).
      @param on  checked
      @return None
      """
      doc = self.map_doc()
      if not self._filling and doc is not None:
         self._run("Stacked objects", lambda: objects.set_stacked(doc, on))

   def _fill_list(self) -> None:
      """!The object list.
      @return None
      """
      self.tree.clear()
      doc = self.map_doc()
      if doc is None:
         return
      chosen = self.selected()
      for i, o in enumerate(objects.objects(doc)):
         if not isinstance(o, dict):
            continue
         at = o.get("at", ["?", "?"])
         item = QtWidgets.QTreeWidgetItem([str(i), str(o.get("name")), f"{at[0]},{at[1]}", objects.describe(o)])
         item.setData(ID_COLUMN, ITEM_KEY_ROLE, i)
         self.tree.addTopLevelItem(item)
         if chosen is not None and chosen[0] == i:
            self.tree.setCurrentItem(item)

   def _show_rows(self, shown: bool) -> None:
      """!Shows or hides the form's rows.
      @param shown  show them
      @return None
      """
      for _label, widget in self.rows:
         lw = self.form.labelForField(widget)
         # the row's widget, or every widget of a row that is a layout
         parts = [widget] if isinstance(widget, QtWidgets.QWidget) else \
             [widget.itemAt(i).widget() for i in range(widget.count())]
         for w in ([lw] if lw else []) + parts:
            if w is not None:
               w.setVisible(shown)

   @staticmethod
   def _combo(box: QtWidgets.QComboBox, items: list[str], current: str, blank: str | None = None) -> None:
      """!Refills a chooser.
      @param box      QComboBox
      @param items    names
      @param current  value to show
      @param blank    first entry ("" or KEEP), or None
      @return None
      """
      box.clear()
      if blank is not None:
         box.addItem(blank)
      box.addItems(items)
      box.setCurrentText(current)

   @staticmethod
   def _option_boxes(store: dict[str, QtWidgets.QCheckBox],
                     changed: Callable[[str, bool], object]) -> QtWidgets.QWidget:
      """!A row of movement option check boxes.
      @param store    dict the boxes go into, {option: QCheckBox}
      @param changed  callable(option, on)
      @return QWidget
      """
      w = QtWidgets.QWidget()
      lay = QtWidgets.QGridLayout(w)
      lay.setContentsMargins(0, 0, 0, 0)
      for n, k in enumerate(objects.OPTIONS):
         box = QtWidgets.QCheckBox(OPTION_LABELS.get(k, k))
         box.setToolTip({"walk_anim": "animates while moving", "step_anim": "animates while standing",
                         "direction_fix": "keeps its facing while moving", "through": "walks through "
                         "everything and is walked through", "on_top": "drawn above everything"}.get(k, k))
         box.toggled.connect(lambda on, k=k: changed(k, on))   # k=k binds this option
         store[k] = box
         lay.addWidget(box, n // OPTION_COLUMNS, n % OPTION_COLUMNS)   # fills the grid row by row
      return w

   def _route_flags(self) -> list[str] | None:
      """!Flags route steps may name (None when the scripts manifest is unknown).
      @return list, or None
      """
      return list(self.names["flags"]) if self.names.get("error") is None else None

   def _fill_form(self) -> None:
      """!The chosen object's fields and pages.
      @return None
      """
      chosen = self.selected()
      self._show_rows(chosen is not None)
      if chosen is None:
         self.page_list.clear()
         self._fill_page()
         return
      _i, o = chosen
      at = o.get("at", [0, 0])
      self.name.setText(str(o.get("name", "")))
      self.x.setValue(at[0])
      self.y.setValue(at[1])
      self.elevation.setValue(o.get("elevation", 0))
      self._combo(self.sprite, sorted(self.sprites or []), o.get("sprite", ""))
      self.facing.setCurrentText(o.get("facing", "down"))
      move = o.get("movement", "static")
      self.movement.setCurrentText(move)
      p = self.project()
      self.movement_args.set_movement(move, [str(n) for n in engine.tool("map_compiler").vehicle_class_names(
         p.world.data)] if p is not None else [])
      self.movement_args.fill(o.get("movement_args"))
      r = o.get("range", [1, 1])
      self.range_x.setValue(r[0] if isinstance(r, list) and len(r) == RANGE_LENGTH else 1)
      self.range_y.setValue(r[1] if isinstance(r, list) and len(r) == RANGE_LENGTH else 1)
      ranged = move in objects.RANGED
      self.range_x.setEnabled(ranged)
      self.range_y.setEnabled(ranged)
      self.speed.setValue(o.get("speed", objects.DEFAULT_SPEED))
      self.frequency.setValue(o.get("frequency", objects.DEFAULT_FREQUENCY))
      opts = o.get("options") if isinstance(o.get("options"), dict) else {}
      for k, box in self.options.items():
         box.setChecked(opts.get(k, objects.OPTIONS[k]) is True)
      self.route.flags = self._route_flags()
      self.route.fill(o.get("route"))
      self.route.set_editable(move == "custom")
      self._combo(self.script, self.names["scripts"], o.get("script", ""), "")
      self.trigger.setCurrentText(o.get("trigger", "action"))
      p = self.project()
      self._combo(self.kind, map_field.object_kinds(p.world) if p is not None else [], o.get("kind", ""), "")
      self._combo(self.flag, self.names["flags"], o.get("flag", ""), "")
      self.self_switches.setChecked(o.get("self_switches") is True)
      t = o.get("spotter") if isinstance(o.get("spotter"), dict) else {}
      self.sight.setValue(t.get("sight", 0))
      self._combo(self.until, self.names["flags"], t.get("until", ""), "")
      self.until.setEnabled(bool(t.get("sight")))
      self.page_list.clear()
      for pg in o.get("pages") or []:
         self.page_list.addItem(objects.describe_page(pg) if isinstance(pg, dict) else "?")
      if 0 <= self._page_row < self.page_list.count():
         self.page_list.setCurrentRow(self._page_row)
      self._fill_page()

   def _fill_page(self) -> None:
      """!The chosen page's conditions and fields.
      @return None
      """
      pg = self._page()
      for w in self.page_conditions + self.page_fields:
         self._set_editable(w, pg is not None)
      pg = pg or {}
      when = pg.get("when") if isinstance(pg.get("when"), dict) else {}
      self._combo(self.pg_flag, self.names["flags"], when.get("flag", ""), "")
      self._combo(self.pg_var, list(self.names["vars"]), when.get("var", ""), "")
      has_var = "var" in when
      self.pg_value.setValue(when.get("value", 1) if isinstance(when.get("value"), int) else 1)
      self.pg_equal.setChecked(when.get("equal") is True)
      self.pg_value.setEnabled(has_var)
      self.pg_equal.setEnabled(has_var)
      letters = when.get("self") or []
      letters = [letters] if isinstance(letters, str) else letters   # one letter may be stored as a string
      for letter, box in self.pg_self.items():
         box.setChecked(letter in letters)
      hidden = pg.get("hidden") is True
      self.pg_hidden.setChecked(hidden)
      self._combo(self.pg_sprite, sorted(self.sprites or []), pg.get("sprite", KEEP), KEEP)
      self.pg_movement.setCurrentText(pg.get("movement", KEEP))
      self.pg_facing.setCurrentText(pg.get("facing", KEEP))
      self._combo(self.pg_script, self.names["scripts"], pg.get("script", KEEP), KEEP)
      self.pg_trigger.setCurrentText(pg.get("trigger", KEEP))
      r = pg.get("range")
      has = isinstance(r, list) and len(r) == RANGE_LENGTH
      self.pg_has_range.setChecked(has)
      self.pg_range_x.setValue(r[0] if has else 1)
      self.pg_range_y.setValue(r[1] if has else 1)
      self.pg_speed.setValue(pg.get("speed", 0) if isinstance(pg.get("speed"), int) else 0)
      self.pg_frequency.setValue(pg.get("frequency", 0) if isinstance(pg.get("frequency"), int) else 0)
      opts = pg.get("options")
      self.pg_has_options.setChecked(isinstance(opts, dict))
      for k, box in self.pg_options.items():
         box.setChecked((opts or {}).get(k, objects.OPTIONS[k]) is True)
         box.setEnabled(isinstance(opts, dict))
      self.pg_has_route.setChecked(isinstance(pg.get("route"), dict))
      self.pg_route.flags = self._route_flags()
      self.pg_route.fill(pg.get("route"))
      self.pg_route.set_editable(isinstance(pg.get("route"), dict))
      if hidden:
         for w in self.page_fields:
            self._set_editable(w, False)

   @staticmethod
   def _set_editable(w: QtWidgets.QWidget, on: bool) -> None:
      """!Enables or disables a page widget; a route box only goes read-only (RouteBox.set_editable()).
      @param w   a widget of page_fields or page_conditions
      @param on  True to enable
      @return None
      """
      if isinstance(w, RouteBox):
         w.set_editable(on)
      else:
         w.setEnabled(on)

   def _fill_problems(self, p: Project) -> None:
      """!The map's object problems.
      @param p  Project
      @return None
      """
      try:
         found = objects.diagnostics(p, self.map_name)
         error = objects.check(p)
      except ENGINE_ERRORS as e:
         self.problems.setText(f"error: {e}")
         return
      lines = [f"{d.level}: {d.message}" for d in found]
      if error and not any(d.level == "error" for d in found):
         lines.insert(0, f"error: {error}")
      self.problems.setText("\n".join(lines) or "No object problems.")

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

   def _object_chosen(self) -> None:
      """!Another object in the list.
      @return None
      """
      if self._filling:
         return
      item = self.tree.currentItem()
      if item is None:
         return
      i = item.data(ID_COLUMN, ITEM_KEY_ROLE)
      o = objects.objects(self.map_doc())[i]
      maptools.select(self.map_name, i, o.get("name"))
      self._page_row = -1
      self._filling = True
      try:
         self._fill_form()
      finally:
         self._filling = False

   def _page(self) -> JsonDict | None:
      """!The chosen page.
      @return its dict, or None
      """
      chosen = self.selected()
      row = self._page_row
      pgs = objects.pages(self.map_doc(), chosen[0]) if chosen is not None else []
      return pgs[row] if 0 <= row < len(pgs) and isinstance(pgs[row], dict) else None

   def _page_chosen(self) -> None:
      """!Another page in the list.
      @return None
      """
      if self._filling:
         return
      self._page_row = self.page_list.currentRow()
      self._filling = True
      try:
         self._fill_page()
      finally:
         self._filling = False

   # -- editing ----------------------------------------------------------------------------------

   def _run(self, label: str, fn: Callable[[], object]) -> bool:
      """!An edit through the host (which shows rule errors); the form is re-read when one is refused.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      try:
         ok = self._edit(label, fn)
      except DocumentError as e:   # hosts without their own error display
         QtWidgets.QMessageBox.warning(self, "Objects", str(e))
         ok = False
      if not ok:
         self.refresh()
      return ok

   def _set(self, **fields: FieldValue) -> None:
      """!Changes fields of the chosen object.
      @param fields  {field: value or None}
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      if self._filling or chosen is None or doc is None:
         return
      i, o = chosen
      t = o.get("spotter") if isinstance(o.get("spotter"), dict) else {}

      def now(k: str) -> Any:
         """!A field's current value.
         @param k  field name
         @return its value, or the default the form shows
         """
         if k in ("sight", "until"):
            return t.get(k)
         default = {"elevation": 0, "facing": "down", "movement": "static", "speed": objects.DEFAULT_SPEED,
                    "frequency": objects.DEFAULT_FREQUENCY, "trigger": "action"}.get(k)
         return o.get(k, default)
      # nothing changes (removing a field that is unset or 0 changes nothing either)
      if all(now(k) == v or (v is None and now(k) in (None, 0)) for k, v in fields.items()):
         return
      self._run("Change object", lambda: objects.set_object(doc, i, **fields))

   def _sprite_chosen(self) -> None:
      """!The sprite reference.
      @return None
      """
      text = self.sprite.currentText().strip()
      if text:
         self._set(sprite=text)

   def _range_changed(self) -> None:
      """!The range spins.
      @return None
      """
      chosen = self.selected()
      if chosen is None or chosen[1].get("movement", "static") not in objects.RANGED:
         return
      self._set(range=[self.range_x.value(), self.range_y.value()])

   def _renamed(self) -> None:
      """!The name field.
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      name = self.name.text().strip()
      if self._filling or chosen is None or doc is None or name == chosen[1].get("name"):
         return
      i = chosen[0]
      if self._run("Rename object", lambda: objects.rename_object(doc, i, name)):
         maptools.select(self.map_name, i, name)

   def _moved(self) -> None:
      """!The cell fields changed.
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      if self._filling or chosen is None or doc is None:
         return
      i, o = chosen
      x, y = self.x.value(), self.y.value()
      if o.get("at") == [x, y]:
         return
      self._run("Move object", lambda: objects.move_object(doc, i, x, y))

   def add(self) -> None:
      """!Adds an object at the form's cell.
      @return None
      """
      doc = self.map_doc()
      if doc is None:
         self.explain("Add object", "map")
         return
      x, y = self.x.value(), self.y.value()
      out: dict[str, int] = {}

      def run() -> None:
         out["i"] = objects.add_object(doc, x, y)
      if self._run("Add object", run):
         maptools.select(self.map_name, out["i"], objects.objects(doc)[out["i"]]["name"])
         self.refresh()

   def remove(self) -> None:
      """!Removes the chosen object.
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      if chosen is None or doc is None:
         self.explain("Remove", "object")
         return
      i = chosen[0]
      out: dict[str, list[str]] = {}

      def run() -> None:
         out["shifted"] = objects.remove_object(doc, i)
      if self._run("Remove object", run):
         maptools.SELECTION.clear()
         if out.get("shifted"):
            self.problems.setText(f"Local IDs after {i} moved down by one ({', '.join(out['shifted'])}); "
                                  "scripts naming them by number must follow.")

   def _option(self, option: str, on: bool) -> None:
      """!An object's movement option check box.
      @param option  key of objects.OPTIONS
      @param on      checked
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      if self._filling or chosen is None or doc is None:
         return
      i, o = chosen
      opts = o.get("options") if isinstance(o.get("options"), dict) else {}
      if opts.get(option, objects.OPTIONS[option]) is on:
         return
      value = None if on is objects.OPTIONS[option] else on   # the default is stored as no value
      self._run("Change option", lambda: objects.set_option(doc, i, option, value))

   def _apply_route(self, text: str, repeat: bool, skip: bool, page: int | None) -> None:
      """!A route box's Apply button.
      @param text    steps, one per line
      @param repeat  start over at the end
      @param skip    skip blocked steps
      @param page    page index, or None for the object
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      if chosen is None or doc is None or (page is not None and self._page() is None):
         return
      i = chosen[0]
      self._run("Set route", lambda: objects.set_route(doc, i, text, repeat, skip, page))

   @staticmethod
   def _kept(box: QtWidgets.QComboBox) -> str | None:
      """!A page chooser's value.
      @param box  QComboBox
      @return its text, or None for KEEP
      """
      text = box.currentText().strip()
      return None if text in (KEEP, "") else text

   def _set_page(self, **fields: FieldValue) -> None:
      """!Changes the chosen page's fields.
      @param fields  {field: value or None}
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      row = self._page_row
      pg = self._page()
      if self._filling or chosen is None or doc is None or pg is None:
         return
      if all(pg.get(k) == v for k, v in fields.items()):
         return
      i = chosen[0]

      def run() -> None:
         """!The change.
         @return None
         """
         objects.set_page(doc, i, row, **fields)
      self._run("Change page", run)

   def _set_when(self, conds: dict[str, WhenValue]) -> None:
      """!Changes the chosen page's conditions (a dict: one of the keys is "self").
      @param conds  {key: value or None}
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      row = self._page_row
      pg = self._page()
      if self._filling or chosen is None or doc is None or pg is None:
         return
      when = pg.get("when") if isinstance(pg.get("when"), dict) else {}
      if all(when.get(k) == v for k, v in conds.items()):
         return
      i = chosen[0]

      def run() -> None:
         """!The change.
         @return None
         """
         objects.set_page(doc, i, row, when=conds)
      self._run("Change page", run)

   def _self_changed(self) -> None:
      """!The page's self switch check boxes.
      @return None
      """
      letters = [k for k, box in self.pg_self.items() if box.isChecked()]
      pg = self._page()
      when = pg.get("when") if pg is not None else None
      now = when.get("self") if isinstance(when, dict) else None
      now = [now] if isinstance(now, str) else (now or [])
      if letters != now:
         self._set_when({"self": letters or None})

   def _page_range(self) -> None:
      """!The page's range check box and spins.
      @return None
      """
      if self._filling is True:
         return
      rng = [self.pg_range_x.value(), self.pg_range_y.value()] if self.pg_has_range.isChecked() else None
      self._set_page(range=rng)

   def _page_options(self) -> dict[str, bool]:
      """!The page's option check boxes as its options (the defaults left out).
      @return {option: bool}
      """
      return {k: box.isChecked() for k, box in self.pg_options.items()
              if box.isChecked() is not objects.OPTIONS[k]}

   def _page_option(self) -> None:
      """!A page option check box.
      @return None
      """
      if self._filling or not self.pg_has_options.isChecked():
         return
      self._set_page(options=self._page_options())

   def _page_route_toggled(self, on: bool) -> None:
      """!The page's own-route check box.
      @param on  checked
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      row = self._page_row
      pg = self._page()
      if self._filling or chosen is None or doc is None or pg is None or isinstance(pg.get("route"), dict) == on:
         return
      i = chosen[0]
      steps = objects.DEFAULT_ROUTE["steps"] if on else None
      self._run("Set route" if on else "Remove route", lambda: objects.set_route(doc, i, steps, page=row))

   def add_page(self) -> None:
      """!Adds a page waiting for the first flag (self switch A when there is none), replacing the script
      (or the facing).
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      if chosen is None or doc is None:
         self.explain("Add page", "object")
         return
      i, o = chosen
      when = {"flag": self.names["flags"][0]} if self.names["flags"] else {"self": "A"}
      fields = {"script": o["script"]} if "script" in o else {"facing": o.get("facing", "down")}
      out: dict[str, int] = {}

      def run() -> None:
         out["j"] = objects.add_page(doc, i, when, **fields)
      if self._run("Add page", run):
         self._page_row = out["j"]

   def remove_page(self) -> None:
      """!Removes the chosen page.
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      row = self._page_row
      if chosen is None or doc is None or self._page() is None:
         self.explain("Remove page", "page")
         return
      i = chosen[0]
      if self._run("Remove page", lambda: objects.remove_page(doc, i, row)):
         self._page_row = -1

   def move_page(self, delta: int) -> None:
      """!Moves the chosen page up or down.
      @param delta  -1 or 1
      @return None
      """
      chosen = self.selected()
      doc = self.map_doc()
      row = self._page_row
      if chosen is None or doc is None or self._page() is None:
         self.explain("Move page", "page")
         return
      to = row + delta
      if not 0 <= to < len(objects.pages(doc, chosen[0])):
         return
      i = chosen[0]
      if self._run("Move page", lambda: objects.move_page(doc, i, row, to)):
         self._page_row = to


def route_tip() -> str:
   """![S5] The route box's tip: the engine's route steps with what they do (core.script_words.route_step_help(): the
   route compiler's table and route.h's; engine N2: in_place walks in place, speed applies to the walker too).
   @return text
   """
   try:
      steps = script_words.route_step_help()
   except ENGINE_ERRORS + (OSError,):
      steps = {}
   if not steps:
      return ROUTE_TIP_FALLBACK
   return "Steps, one per line:\n" + "\n".join(text for text in dict.fromkeys(steps.values()))
