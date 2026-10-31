"""!The World page's Field panel (engine F2, D-27 section 3; core.map_field): what the field actions and the
overworld's F2 mechanisms read from the world and its maps.

Top: the world's object kinds (what a field action faces: a bush, a boulder; a map object names one in its Kind) and
map tags (what a menu action needs: a dark cave), each a list with Add / Rename / Remove (a rename rewrites the maps
naming it, one undo step, and the game's battle field actions targeting it when the world is saved; a removal is
refused while a map or a field action names it). Middle: one map's darkness (0 lit to the world's darkest level, the
overworld draws a lit box around the walker), its tags (ticked from the world's) and whether it is an escape point
(outdoors: leaving it for a map that is not records where the escape returns to); beside it the world's darkness
levels (C8: each level's lit box half size and brightness, a table with Add level / Remove darkest; the engine's
defaults until edited). Bottom: the world's flight points (the flight menu's places: a label, the map and cell it
lands on, the facing), the list and a form. Every limit and choice list is the engine's map compiler's; an edit it
refuses is refused with its message.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ...core import document, map_field as model
from ..panes import split_box
from ..widgets import button, set_enabled
from .battle_common import set_check, set_combo
from .field_rules import FieldPanel

if TYPE_CHECKING:
   from ...core.document import Document
   from ..panel import PanelHost

## What the panel says at the top.
NOTE = ("Field actions are used on what the walker faces: a behavior (water), or a map object of a kind (a bush). "
        "Menu actions may need the map to carry a tag (a dark cave). A dark map draws a lit box around the walker "
        "(0: lit). Leaving an escape point (outdoors) for a map that is not one records where `escape` returns to. "
        "Flight points are the flight menu's places; `flight record NAME` marks one visited.")
## Height of the map's tag list, pixels (it sits in the map's form).
LIST_HEIGHT = 110
## The name lists: (core key, title, what a name is called).
NAME_LISTS = [(model.KINDS_KEY, "Object kinds", "object kind"), (model.TAGS_KEY, "Map tags", "map tag")]
## C8: the darkness level table's columns (the level, then core.map_field.LEVEL_FIELDS).
LEVEL_COLUMNS = ["Level", "Lit half size (px)", "Brightness (0-16)"]
## The level a new darkest level copies (the last), and what it takes off the lit box, pixels.
NEW_LEVEL_STEP = 8


class MapFieldPanel(FieldPanel):
   """!The world's object kinds, map tags and flight points; a map's darkness, tags and escape point.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "map_field"
   ## See EditorPanel.title.
   title = "Field"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the name lists, the map box and the flight points.
      @param host    the world window
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The name lists by core key.
      self.name_lists: dict[str, QtWidgets.QListWidget] = {}
      names_row = QtWidgets.QHBoxLayout()
      for key, title, what in NAME_LISTS:
         box = QtWidgets.QGroupBox(title)
         lay = QtWidgets.QVBoxLayout(box)
         names = QtWidgets.QListWidget()
         self.name_lists[key] = names
         row = QtWidgets.QHBoxLayout()
         row.addWidget(button("Add...", lambda k=key, w=what: self.add_name(k, None, w)))
         row.addWidget(button("Rename...", lambda k=key, w=what: self.rename_name(k, None, w),
                              "Rename it; the maps follow (the battle field actions on save)"))
         row.addWidget(button("Remove", lambda k=key: self.remove_name(k),
                              "Refused while a map or a field action names it"))
         row.addStretch(1)
         lay.addWidget(names)
         lay.addLayout(row)
         names_row.addWidget(box)
      # one map's darkness, tags and escape point
      map_box = QtWidgets.QGroupBox("Map")
      ## The map shown (the Map tab's, at first).
      self.map_choice = QtWidgets.QComboBox()
      self.map_choice.activated.connect(lambda _i: self.refresh())
      ## How dark the map is.
      self.darkness = QtWidgets.QSpinBox()
      self.darkness.setRange(0, model.max_darkness())
      self.darkness.setSpecialValueText("0 (lit)")
      self.darkness.editingFinished.connect(lambda: self.set_darkness(self.darkness.value()))
      ## The map's tags (ticked).
      self.tags = QtWidgets.QListWidget()
      self.tags.setMaximumHeight(LIST_HEIGHT)
      self.tags.itemChanged.connect(lambda _item: self._tags_ticked())
      ## Whether the map is an escape point.
      self.escape = QtWidgets.QCheckBox("Escape point (outdoors: `escape` returns to where the walker left it)")
      self.escape.clicked.connect(lambda on: self.set_escape_point(bool(on)))
      form = QtWidgets.QFormLayout(map_box)
      form.addRow("Map", self.map_choice)
      form.addRow("Darkness", self.darkness)
      form.addRow("Tags", self.tags)
      form.addRow("", self.escape)
      # C8: the world's darkness levels (what each level looks like)
      levels_box = QtWidgets.QGroupBox("Darkness levels")
      ## The levels: level, lit box half size, brightness.
      self.levels = QtWidgets.QTableWidget(0, len(LEVEL_COLUMNS))
      self.levels.setHorizontalHeaderLabels(LEVEL_COLUMNS)
      self.levels.verticalHeader().setVisible(False)
      self.levels.horizontalHeader().setStretchLastSection(True)
      self.levels.cellChanged.connect(lambda r, c: self._level_edited(r, c))
      ## Says whether the levels are the engine's defaults.
      self.levels_note = QtWidgets.QLabel()
      self.levels_note.setWordWrap(True)
      level_buttons = QtWidgets.QHBoxLayout()
      level_buttons.addWidget(button("Add level", lambda: self.add_level(), "A darker level after the others"))
      level_buttons.addWidget(button("Remove darkest", lambda: self.remove_level(),
                                     "Refused while a map is that dark"))
      level_buttons.addStretch(1)
      levels_lay = QtWidgets.QVBoxLayout(levels_box)
      levels_lay.addWidget(self.levels)
      levels_lay.addWidget(self.levels_note)
      levels_lay.addLayout(level_buttons)
      map_row = QtWidgets.QHBoxLayout()
      map_row.addWidget(map_box, 1)
      map_row.addWidget(levels_box, 1)
      split_box(map_row)   # [RZ] map | darkness levels
      # the flight points
      flight_box = QtWidgets.QGroupBox("Flight points")
      ## The flight points.
      self.flights = QtWidgets.QListWidget()
      self.flights.currentTextChanged.connect(lambda _t: self._fill_flight())
      ## What the flight menu shows.
      self.flight_label = QtWidgets.QLineEdit()
      self.flight_label.setMaxLength(model.max_flight_label())
      self.flight_label.editingFinished.connect(lambda: self.set_flight("label", self.flight_label.text()))
      ## The map it lands on.
      self.flight_map = QtWidgets.QComboBox()
      self.flight_map.activated.connect(lambda _i: self.set_flight("map", self.flight_map.currentText()))
      lo, hi = model.coord_range()
      ## The landing column.
      self.flight_x = QtWidgets.QSpinBox()
      ## The landing row.
      self.flight_y = QtWidgets.QSpinBox()
      for spin, key in ((self.flight_x, "x"), (self.flight_y, "y")):
         spin.setRange(lo, hi)
         spin.editingFinished.connect(lambda s=spin, k=key: self.set_flight(k, s.value()))
      ## The facing on landing.
      self.flight_facing = QtWidgets.QComboBox()
      self.flight_facing.addItems(model.directions())
      self.flight_facing.activated.connect(lambda _i: self.set_flight("facing", self.flight_facing.currentText()))
      cell = QtWidgets.QHBoxLayout()
      cell.addWidget(self.flight_x)
      cell.addWidget(self.flight_y)
      cell.addStretch(1)
      flight_form = QtWidgets.QFormLayout()
      flight_form.addRow("Label", self.flight_label)
      flight_form.addRow("Lands on", self.flight_map)
      flight_form.addRow("Cell (x, y)", cell)
      flight_form.addRow("Facing", self.flight_facing)
      flight_buttons = QtWidgets.QVBoxLayout()
      flight_buttons.addWidget(button("Add...", lambda: self.add_flight(), "A flight point on the map shown above"))
      flight_buttons.addWidget(button("Remove", lambda: self.remove_flight()))
      flight_buttons.addStretch(1)
      flight_lay = QtWidgets.QHBoxLayout(flight_box)
      flight_lay.addWidget(self.flights)
      flight_lay.addLayout(flight_form, 1)
      flight_lay.addLayout(flight_buttons)
      note = QtWidgets.QLabel(NOTE)
      note.setWordWrap(True)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(note)
      lay.addLayout(names_row)
      lay.addLayout(map_row)
      lay.addWidget(flight_box, 1)
      lay.addWidget(self.errors)
      split_box(names_row)   # [RZ] the name lists side by side
      split_box(lay)   # [RZ] names / map and levels / flight points, stacked: the user drags the boundaries

   # -- reading -------------------------------------------------------------------------------------------------------

   def map_doc(self) -> Document | None:
      """!The map shown.
      @return its Document, or None
      """
      p = self.host_project()
      name = self.map_choice.currentText()
      if p is None or not name or name not in p.map_names():
         return None
      return p.map(name)

   def refresh(self) -> None:
      """!Re-reads the world and the map shown.
      @return None
      """
      p, w = self.host_project(), self.world()
      self._filling = True
      try:
         for key, names in self.name_lists.items():
            current = names.currentItem().text() if names.currentItem() is not None else None
            names.clear()
            got = (model.object_kinds(w) if key == model.KINDS_KEY else model.map_tags(w)) if w is not None else []
            names.addItems(got)
            if current in got:
               names.setCurrentRow(got.index(current))
         maps = p.map_names() if p is not None else []
         chosen = self.map_choice.currentText() or self.host.selected_map()
         set_combo(self.map_choice, maps, chosen if chosen in maps else (maps[0] if maps else None))
         self._fill_levels()
         self._fill_map()
         current = self.flights.currentItem().text() if self.flights.currentItem() is not None else None
         flights = [f["name"] for f in model.flight_points(w)] if w is not None else []
         self.flights.clear()
         self.flights.addItems(flights)
         if flights:
            self.flights.setCurrentRow(flights.index(current) if current in flights else 0)
         set_combo(self.flight_map, maps, maps[0] if maps else None)
         self._fill_flight()
      finally:
         self._filling = False
      set_enabled(self, w is not None)
      self.show_errors()

   def _fill_map(self) -> None:
      """!Shows the map's darkness, tags and escape point.
      @return None
      """
      doc, w = self.map_doc(), self.world()
      darkness, tags, escape = model.map_rules(doc, w) if doc is not None and w is not None else (0, [], False)
      was = self._filling
      self._filling = True
      try:
         self.darkness.setValue(darkness)
         self.tags.clear()
         for tag in model.map_tags(w) if w is not None else []:
            item = QtWidgets.QListWidgetItem(tag)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked if tag in tags else QtCore.Qt.CheckState.Unchecked)
            self.tags.addItem(item)
         set_check(self.escape, escape)
         for widget in (self.darkness, self.tags, self.escape):
            set_enabled(widget, doc is not None)   # the tag list goes read-only and keeps its scroll bar
      finally:
         self._filling = was

   def _fill_levels(self) -> None:
      """!Shows the world's darkness levels (C8) and limits the map's darkness to the darkest.
      @return None
      """
      w = self.world()
      levels = model.darkness_levels(w)
      was = self._filling
      self._filling = True
      try:
         self.levels.setRowCount(len(levels))
         for k, lv in enumerate(levels):
            number = QtWidgets.QTableWidgetItem(str(k + 1))
            number.setFlags(number.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.levels.setItem(k, 0, number)
            for col, key in enumerate(model.LEVEL_FIELDS, start=1):
               self.levels.setItem(k, col, QtWidgets.QTableWidgetItem(str(lv[key])))
         self.levels_note.setText("The engine's default levels (the world states none: an edit writes them out)."
                                  if w is not None and model.levels_default(w) else
                                  f"{len(levels)} levels: a map's darkness and `darkness N;` go up to "
                                  f"{len(levels)}; a level is kept across a save until the next map.")
         self.darkness.setRange(0, model.darkest(w))
      finally:
         self._filling = was

   def _level_edited(self, row: int, col: int) -> None:
      """!A level's cell was edited.
      @param row  the row (level - 1)
      @param col  the column (1: lit, 2: brightness)
      @return None
      """
      if self._filling or col == 0:
         return
      item = self.levels.item(row, col)
      text = item.text().strip() if item is not None else ""
      if not text.lstrip("-").isdigit():
         self.refresh()
         return
      self.set_level(row + 1, model.LEVEL_FIELDS[col - 1], int(text))

   def _fill_flight(self) -> None:
      """!Shows the selected flight point.
      @return None
      """
      w = self.world()
      item = self.flights.currentItem()
      rec = next((f for f in model.flight_points(w) if item is not None and f["name"] == item.text()), None) \
         if w is not None else None
      was = self._filling
      self._filling = True
      try:
         for widget in (self.flight_label, self.flight_map, self.flight_x, self.flight_y, self.flight_facing):
            widget.setEnabled(rec is not None)
         if rec is None:
            return
         self.flight_label.setText(rec["label"])
         self.flight_map.setCurrentText(rec["map"])
         self.flight_x.setValue(rec["x"])
         self.flight_y.setValue(rec["y"])
         self.flight_facing.setCurrentText(rec["facing"])
      finally:
         self._filling = was

   # -- editing -------------------------------------------------------------------------------------------------------

   def _map_edit(self, label: str, change: Callable[[Document, Document], None]) -> bool:
      """!One edit of the map shown.
      @param label   undo label
      @param change  callable(map Document, world Document)
      @return True when it went through
      """
      doc, w = self.map_doc(), self.world()
      if doc is None or w is None or self._filling:
         return False
      ok = self.host.run_edit(label, lambda: change(doc, w), doc)
      if not ok:
         self.refresh()
      return ok

   def set_darkness(self, level: int) -> bool:
      """!Sets the map's darkness.
      @param level  0 to the engine's most
      @return True when it went through
      """
      doc, w = self.map_doc(), self.world()
      if doc is not None and w is not None and model.map_rules(doc, w)[0] == level:
         return False
      return self._map_edit("Map darkness", lambda d, wd: model.set_darkness(d, wd, level))

   def set_level(self, level: int, key: str, value: int) -> bool:
      """!Changes a darkness level (C8).
      @param level  1 up
      @param key    lit or brightness
      @param value  the value
      @return True when it went through
      """
      levels = model.darkness_levels(self.world())
      if 1 <= level <= len(levels) and levels[level - 1].get(key) == value:
         return False
      return self._run("Darkness level", lambda wd: model.set_darkness_level(wd, level, key, value))

   def add_level(self) -> bool:
      """!Adds a darker level after the others (the last one's box less NEW_LEVEL_STEP pixels, as dark).
      @return True when added
      """
      levels = model.darkness_levels(self.world())
      last = levels[-1] if levels else {"lit": model.max_lit(), "brightness": model.max_brightness()}
      lit = max(0, int(last["lit"]) - NEW_LEVEL_STEP)
      return self._run("Add darkness level", lambda wd: model.add_darkness_level(wd, lit, int(last["brightness"])))

   def remove_level(self) -> bool:
      """!Removes the darkest level (refused while a map is that dark).
      @return True when removed
      """
      p = self.host_project()
      if p is None:
         return self.explain("Remove darkest")
      return self._run("Remove darkness level", lambda _w: model.remove_darkness_level(p))

   def set_tags(self, tags: list[str]) -> bool:
      """!Sets the map's tags.
      @param tags  names of the world's map tags
      @return True when it went through
      """
      return self._map_edit("Map tags", lambda d, wd: model.set_tags(d, wd, tags))

   def _tags_ticked(self) -> None:
      """!A tag was ticked or unticked.
      @return None
      """
      if self._filling:
         return
      self.set_tags([self.tags.item(i).text() for i in range(self.tags.count())
                     if self.tags.item(i).checkState() == QtCore.Qt.CheckState.Checked])

   def set_escape_point(self, on: bool) -> bool:
      """!Sets whether the map is an escape point.
      @param on  on or off
      @return True when it went through
      """
      return self._map_edit("Escape point", lambda d, wd: model.set_escape_point(d, wd, on))

   def add_name(self, key: str, name: str | None = None, what: str = "name") -> bool:
      """!Adds an object kind or a map tag.
      @param key   model.KINDS_KEY or model.TAGS_KEY
      @param name  the name, or None to ask
      @param what  what the dialog calls it
      @return True when added
      """
      p = self.host_project()
      if p is None:
         return self.explain(f"Add {what}")
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, f"Add {what}", "Name (lower case):")
         if not ok:
            return False
      return self._run(f"Add {what}", lambda _w: model.add_name(p, key, name))

   def rename_name(self, key: str, new: str | None = None, what: str = "name") -> bool:
      """!Renames the selected object kind or map tag; the maps naming it follow (one undo step).
      @param key   model.KINDS_KEY or model.TAGS_KEY
      @param new   the new name, or None to ask
      @param what  what the dialog calls it
      @return True when renamed
      """
      p, item = self.host_project(), self.name_lists[key].currentItem()
      if p is None or item is None:
         return self.explain(f"Rename {what}", what)
      old = item.text()
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, f"Rename {what}", "New name:", text=old)
         if not ok:
            return False
      with document.group(f"Rename {what}"):
         return self._run(f"Rename {what}", lambda _w: model.rename_name(p, key, old, new))

   def remove_name(self, key: str) -> bool:
      """!Removes the selected object kind or map tag (refused while a map names it).
      @param key  model.KINDS_KEY or model.TAGS_KEY
      @return True when removed
      """
      p, item = self.host_project(), self.name_lists[key].currentItem()
      if p is None or item is None:
         return self.explain("Remove name", "name")
      name = item.text()
      return self._run("Remove name", lambda _w: model.remove_name(p, key, name))

   def selected_flight(self) -> str | None:
      """!The selected flight point.
      @return its name, or None
      """
      item = self.flights.currentItem()
      return item.text() if item is not None else None

   def set_flight(self, key: str, value: object) -> bool:
      """!Changes a field of the selected flight point.
      @param key    label, map, x, y or facing
      @param value  the value
      @return True when it went through
      """
      name, w = self.selected_flight(), self.world()
      if name is None or w is None or self._filling:
         return False
      rec = next((f for f in model.flight_points(w) if f["name"] == name), None)
      if rec is not None and rec.get(key) == value:
         return False
      return self._run("Flight point", lambda wd: model.set_flight_point(wd, name, key, value))

   def add_flight(self, name: str | None = None) -> bool:
      """!Adds a flight point on the map shown (its first cell; the form moves it).
      @param name  its name, or None to ask
      @return True when added
      """
      map_name = self.map_choice.currentText()
      if not map_name:
         return self.explain("Add flight point", "map")
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add flight point", "Name (lower case):")
         if not ok:
            return False
      lo = model.coord_range()[0]
      return self._run("Add flight point", lambda wd: model.add_flight_point(wd, name.strip(), map_name, lo, lo))

   def remove_flight(self) -> bool:
      """!Removes the selected flight point.
      @return True when removed
      """
      name = self.selected_flight()
      if name is None:
         return self.explain("Remove flight point", "flight point")
      return self._run("Remove flight point", lambda wd: model.remove_flight_point(wd, name))
