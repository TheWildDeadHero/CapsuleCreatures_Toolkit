"""![S3] The World page's "Doors and draw order" panel (D-30, engine DS1): the world's door bindings by metatile (every
cell showing a metatile animates with a door; a warp's own door, on the Events tab, wins on its cell) and the object
draw order rule (sub-priority from a sprite's bottom edge on screen and its elevation), with a preview of two objects
at rows and elevations of your choice: which one the engine draws in front and their sort keys. Every change is one
undo step on the world Document (the host's run_edit()); the engine's map compiler checks it (core.doors,
core.draw_order)."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import doors, draw_order, engine
from ..panel import EditorPanel
from ..widgets import PixelView, button, set_enabled

if TYPE_CHECKING:
   from ...core.document import Document
   from ...core.world import Project
   from ..panel import PanelHost

## Errors meaning the engine (its compilers) is missing or too old.
ENGINE_ERRORS = (engine.EngineNotFound, ImportError, AttributeError, KeyError)
## Binding table columns.
BINDING_COLUMNS = ("Tileset", "Metatile", "Door")
## The chooser entry of a binding matching any of a map's tilesets (map_compiler ANY_TILESET).
ANY_TILESET = "*"
## Draw order fields edited with a spin box (the powers of two take a combo box).
SPIN_FIELDS = ("bias", "rows", "row_step", "add")
## Draw order fields that are powers of two.
POWER_FIELDS = ("row_pixels", "wrap")
## Elevation bases per row of the base grid.
BASES_PER_ROW = 8
## The preview's screen, pixels (the GBA's 240 x 160).
SCREEN_W, SCREEN_H = 240, 160
## Pixels per cell.
CELL = 16
## The preview sprites' size (an NPC's 16 x 32) and the horizontal distance between them (they overlap).
SPRITE_W, SPRITE_H, SPRITE_GAP = 16, 32, 8
## Left edge of the first preview sprite.
SPRITE_X = 104
## Preview zoom.
PREVIEW_ZOOM = 2
## Preview colours (RGB): the sky / ground grid, sprite A, sprite B, outlines.
GRID_COLOR, A_COLOR, B_COLOR, LINE_COLOR = (88, 168, 56), (64, 104, 224), (232, 144, 48), (32, 32, 32)
## Rows a preview sprite may stand on (its feet's cell row on the screen).
SCREEN_ROWS = SCREEN_H // CELL
## Default preview rows and elevations of sprites A and B.
DEFAULT_A, DEFAULT_B = (6, 3), (5, 3)
## Layout stretch of the bindings column and of the draw order column.
BINDINGS_STRETCH, ORDER_STRETCH = 2, 3


class WorldDoorsPanel(EditorPanel):
   """!Edits the world's door bindings by metatile and its draw order rule."""

   ## See EditorPanel.panel_id.
   panel_id = "doors_draw_order"
   ## See EditorPanel.title.
   title = "Doors and draw order"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## True while the panel fills its widgets.
      self._filling = False

      # -- door bindings
      bind_box = QtWidgets.QGroupBox("Door bindings by metatile")
      bl = QtWidgets.QVBoxLayout(bind_box)
      note = QtWidgets.QLabel("Every cell showing the metatile (on any layer) is the anchor (bottom-left cell) of the "
                              "door. A warp's own door (Events tab) wins on its cell.")
      note.setWordWrap(True)
      bl.addWidget(note)
      ## The bindings.
      self.bindings = QtWidgets.QTableWidget(0, len(BINDING_COLUMNS))
      self.bindings.setHorizontalHeaderLabels(list(BINDING_COLUMNS))
      self.bindings.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.bindings.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.bindings.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.bindings.horizontalHeader().setStretchLastSection(True)
      self.bindings.itemSelectionChanged.connect(lambda: self._binding_picked())
      bl.addWidget(self.bindings, 1)
      ## The form: tileset ("*" any), metatile, door.
      self.tileset = QtWidgets.QComboBox()
      self.tileset.activated.connect(lambda _i: self._fill_metatiles())
      ## The metatile.
      self.metatile = QtWidgets.QComboBox()
      self.metatile.setEditable(True)
      ## The door key.
      self.door = QtWidgets.QComboBox()
      self.door.setEditable(True)
      self.door.setToolTip("A door asset (door:NAME) of the game's asset manifest")
      form = QtWidgets.QFormLayout()
      form.addRow("Tileset", self.tileset)
      form.addRow("Metatile", self.metatile)
      form.addRow("Door", self.door)
      bl.addLayout(form)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add", lambda: self.add_binding(), "Bind the door to every cell showing the metatile"))
      row.addWidget(button("Apply", lambda: self.apply_binding(), "Change the chosen binding to the form's"))
      row.addWidget(button("Remove", lambda: self.remove_binding()))
      bl.addLayout(row)

      # -- draw order
      order_box = QtWidgets.QGroupBox("Object draw order")
      ol = QtWidgets.QVBoxLayout(order_box)
      ## Whether the world states its rule.
      self.state = QtWidgets.QLabel()
      self.state.setWordWrap(True)
      ol.addWidget(self.state)
      rule_form = QtWidgets.QFormLayout()
      ## Spin boxes and power-of-two combos by field.
      self.fields = {}
      ranges = self._ranges()
      tips = {"bias": "Pixels added to the bottom edge first", "rows": "Rows counted from (the row is subtracted)",
              "row_step": "Sub-priority steps per row", "add": "Added last",
              "row_pixels": "Pixels per row (a power of two)",
              "wrap": "Pixels of (edge + bias) kept (a power of two up to 256: a wrapping 8-bit screen row)"}
      for name in SPIN_FIELDS + POWER_FIELDS:
         if name in POWER_FIELDS:
            w = QtWidgets.QComboBox()
            lo, hi = ranges.get(name, (1, 1))
            powers = [1 << k for k in range(hi.bit_length()) if lo <= 1 << k <= hi]
            w.addItems([str(v) for v in powers])
            w.activated.connect(lambda _i, n=name: self._field_changed(n))
         else:
            w = QtWidgets.QSpinBox()
            lo, hi = ranges.get(name, (0, 0))
            w.setRange(lo, hi)
            w.setKeyboardTracking(False)
            w.valueChanged.connect(lambda _v, n=name: self._field_changed(n))
         w.setToolTip(tips.get(name, ""))
         self.fields[name] = w
         rule_form.addRow(name, w)
      ol.addLayout(rule_form)
      ol.addWidget(QtWidgets.QLabel("Base per elevation (added first; higher draws behind)"))
      base_grid = QtWidgets.QGridLayout()
      ## The 16 elevation bases.
      self.bases = []
      lo, hi = ranges.get(draw_order.BASE_KEY, (0, 0))
      for e in range(self._levels()):
         s = QtWidgets.QSpinBox()
         s.setRange(lo, hi)
         s.setKeyboardTracking(False)
         s.setPrefix(f"{e}: ")
         s.valueChanged.connect(lambda v, k=e: self._base_changed(k, v))
         self.bases.append(s)
         base_grid.addWidget(s, e // BASES_PER_ROW, e % BASES_PER_ROW)
      ol.addLayout(base_grid)
      ol.addWidget(button("Reset to the default rule", lambda: self.reset_rule(),
                          "Remove the world's rule: lower on screen in front"))
      ol.addStretch(1)

      # -- preview
      prev_box = QtWidgets.QGroupBox("Preview: two objects")
      pl = QtWidgets.QVBoxLayout(prev_box)
      pick = QtWidgets.QGridLayout()
      ## Rows (the feet's cell row on screen) and elevations of A and B.
      self.at_rows = [QtWidgets.QSpinBox(), QtWidgets.QSpinBox()]
      ## Elevations of A and B.
      self.levels = [QtWidgets.QSpinBox(), QtWidgets.QSpinBox()]
      for k, (name, (r, e)) in enumerate((("A (blue)", DEFAULT_A), ("B (orange)", DEFAULT_B))):
         self.at_rows[k].setRange(0, SCREEN_ROWS - 1)
         self.at_rows[k].setValue(r)
         self.levels[k].setRange(0, self._levels() - 1)
         self.levels[k].setValue(e)
         for w in (self.at_rows[k], self.levels[k]):
            w.valueChanged.connect(lambda _v: self.update_preview())
         # one row per sprite: its name, "row", the row spin, "elevation", the elevation spin
         for col, wdg in enumerate((QtWidgets.QLabel(name), QtWidgets.QLabel("row"), self.at_rows[k],
                                    QtWidgets.QLabel("elevation"), self.levels[k])):
            pick.addWidget(wdg, k, col)
      pl.addLayout(pick)
      ## The picture.
      self.preview = PixelView(PREVIEW_ZOOM)
      pl.addWidget(self.preview, 1)
      ## Which is in front, and why.
      self.verdict = QtWidgets.QLabel()
      self.verdict.setWordWrap(True)
      pl.addWidget(self.verdict)
      ## Compiler messages.
      self.problem = QtWidgets.QLabel()
      self.problem.setWordWrap(True)
      self.problem.setStyleSheet("color: #c03030;")

      right = QtWidgets.QVBoxLayout()
      top = QtWidgets.QHBoxLayout()
      top.addWidget(order_box, 1)
      top.addWidget(prev_box, 1)
      right.addLayout(top, 1)
      right.addWidget(self.problem)
      lay = QtWidgets.QHBoxLayout(self)
      lay.addWidget(bind_box, BINDINGS_STRETCH)
      lay.addLayout(right, ORDER_STRETCH)

   # -- host -------------------------------------------------------------------------------------------

   def world(self) -> Document | None:
      """!The world Document.
      @return Document, or None
      """
      p: Project | None = self.host_project()
      return p.world if p is not None else None

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the world file.
      @return Document, or None
      """
      return self.world()

   @staticmethod
   def _ranges() -> dict[str, tuple[int, int]]:
      """!The rule's field ranges (the engine's), or none without an engine.
      @return {field: (lo, hi)}
      """
      try:
         return draw_order.ranges()
      except ENGINE_ERRORS:
         return {}

   @staticmethod
   def _levels() -> int:
      """!Elevation levels (the engine's).
      @return 16, or 0 without an engine
      """
      try:
         return draw_order.elevations()
      except ENGINE_ERRORS:
         return 0

   def _run(self, label: str, fn: Callable[[Document], object]) -> bool:
      """!One change of the world through the host.
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

   # -- refresh ------------------------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the bindings and the rule.
      @return None
      """
      doc = self.world()
      set_enabled(self, doc is not None)
      if doc is None:
         return
      self._filling = True
      try:
         self._fill_bindings()
         self._fill_rule(doc)
      finally:
         self._filling = False
      self.update_preview()

   def _fill_bindings(self) -> None:
      """!The binding table and the form's choices.
      @return None
      """
      p: Project = self.host_project()
      row = self.bindings.currentRow()
      items = doors.bindings(p.world)
      self.bindings.setRowCount(len(items))
      for i, b in enumerate(items):
         for c, key in enumerate(("tileset", "metatile", "door")):
            self.bindings.setItem(i, c, QtWidgets.QTableWidgetItem(str(b.get(key, ""))))
      t = self.tileset.currentText()
      self.tileset.clear()
      self.tileset.addItems([ANY_TILESET] + p.tileset_names())
      if t:
         self.tileset.setCurrentText(t)
      d = self.door.currentText()
      self.door.clear()
      try:
         self.door.addItems(doors.door_keys(p))
      except ENGINE_ERRORS:
         pass
      self.door.setCurrentText(d)
      self._fill_metatiles()
      if 0 <= row < len(items):
         self.bindings.selectRow(row)

   def _fill_metatiles(self) -> None:
      """!The metatile choices of the chosen tileset (every tileset's for "*").
      @return None
      """
      p: Project = self.host_project()
      if p is None:
         return
      text = self.metatile.currentText()
      names: list[str] = []
      chosen = self.tileset.currentText()
      for t in p.tileset_names() if chosen == ANY_TILESET else [chosen]:
         if t in p.tileset_names():
            names += [n for n in p.metatile_names(t) if n not in names]
      self.metatile.clear()
      self.metatile.addItems(names)
      self.metatile.setCurrentText(text)

   def _fill_rule(self, doc: Document) -> None:
      """!The rule's fields.
      @param doc  world Document
      @return None
      """
      try:
         r = draw_order.rule(doc)
      except ENGINE_ERRORS as e:
         self.state.setText(f"No engine: {e}")
         return
      self.state.setText("The world states its rule." if draw_order.is_set(doc) else
                         "The world states no rule: the engine's default (lower on screen in front).")
      for name, w in self.fields.items():
         if isinstance(w, QtWidgets.QComboBox):
            w.setCurrentText(str(r[name]))
         else:
            w.setValue(r[name])
      for e, s in enumerate(self.bases):
         s.setValue(r[draw_order.BASE_KEY][e])

   def _binding_picked(self) -> None:
      """!A binding row was chosen: the form shows it.
      @return None
      """
      if self._filling is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      i = self.bindings.currentRow()
      items = doors.bindings(self.world()) if self.world() is not None else []
      if not 0 <= i < len(items):
         return
      b = items[i]
      self.tileset.setCurrentText(str(b.get("tileset", ANY_TILESET)))
      self._fill_metatiles()
      self.metatile.setCurrentText(str(b.get("metatile", "")))
      self.door.setCurrentText(str(b.get("door", "")))

   # -- edits ----------------------------------------------------------------------------------------------

   def _form(self) -> tuple[str, str, str]:
      """!The binding form's values.
      @return (tileset, metatile, door)
      """
      return self.tileset.currentText(), self.metatile.currentText().strip(), self.door.currentText().strip()

   def add_binding(self) -> bool:
      """!Adds the form's binding.
      @return True when added
      """
      t, m, d = self._form()
      ok = self._run("Add door binding", lambda doc: doors.add_binding(doc, t, m, d))
      if ok:
         self.refresh()
         self.bindings.selectRow(self.bindings.rowCount() - 1)
      return ok

   def apply_binding(self) -> bool:
      """!The chosen binding takes the form's values.
      @return True when changed
      """
      i = self.bindings.currentRow()
      if i < 0:
         return self.explain("Apply door binding", "door binding")
      t, m, d = self._form()
      return self._run("Door binding", lambda doc: doors.set_binding(doc, i, tileset=t, metatile=m,
                                                                                door=d))

   def remove_binding(self) -> bool:
      """!Removes the chosen binding.
      @return True when removed
      """
      i = self.bindings.currentRow()
      if i < 0:
         return self.explain("Remove door binding", "door binding")
      return self._run("Remove door binding", lambda doc: doors.remove_binding(doc, i))

   def _value(self, name: str) -> int:
      """!A rule field's value in the form.
      @param name  the field
      @return the value
      """
      w = self.fields[name]
      return int(w.currentText()) if isinstance(w, QtWidgets.QComboBox) else w.value()

   def _field_changed(self, name: str) -> None:
      """!A rule field changed.
      @param name  the field
      @return None
      """
      value = self._value(name)
      doc = self.world()
      if doc is not None and draw_order.rule(doc)[name] != value:
         self._run("Draw order", lambda d: draw_order.set_field(d, name, value))
      self.update_preview()

   def _base_changed(self, elevation: int, value: int) -> None:
      """!An elevation's base changed.
      @param elevation  the level
      @param value      its base
      @return None
      """
      doc = self.world()
      if doc is not None and draw_order.rule(doc)[draw_order.BASE_KEY][elevation] != value:
         self._run("Draw order", lambda d: draw_order.set_base(d, elevation, value))
      self.update_preview()

   def reset_rule(self) -> bool:
      """!Removes the world's rule.
      @return True when it went through
      """
      ok = self._run("Draw order", draw_order.reset)
      self.refresh()
      return ok

   # -- preview ----------------------------------------------------------------------------------------------

   def sprites(self) -> list[draw_order.Sprite]:
      """!The preview's two sprites, front first (as the engine sorts them).
      @return [front, back]
      """
      doc = self.world()
      r = draw_order.rule(doc)
      out = []
      for k, name in enumerate(("A", "B")):
         e = self.levels[k].value()
         bottom = (self.at_rows[k].value() + 1) * CELL   # the feet's cell's bottom edge on screen
         out.append(draw_order.Sprite(name, bottom, e, draw_order.level_priority(doc, e)))
      return draw_order.order(r, out)

   def update_preview(self) -> None:
      """!Draws the two objects, the back one first, and says which is in front.
      @return None
      """
      doc = self.world()
      if self._filling or doc is None:
         return
      try:
         ordered = self.sprites()
      except (ValueError, *ENGINE_ERRORS) as e:
         self.problem.setText(str(e))
         return
      self.problem.setText("")
      img = QtGui.QImage(SCREEN_W, SCREEN_H, QtGui.QImage.Format.Format_RGBA8888)
      img.fill(QtGui.QColor(*GRID_COLOR))
      p = QtGui.QPainter(img)
      p.setPen(QtGui.QColor(*LINE_COLOR).lighter())
      for y in range(0, SCREEN_H, CELL):
         p.drawLine(0, y, SCREEN_W, y)
      colors = {"A": A_COLOR, "B": B_COLOR}
      xs = {"A": SPRITE_X, "B": SPRITE_X + SPRITE_GAP}
      for s in reversed(ordered):   # the back one first, the front one over it
         top = s.bottom - SPRITE_H
         p.setPen(QtGui.QColor(*LINE_COLOR))
         p.setBrush(QtGui.QColor(*colors[s.name]))
         p.drawRect(QtCore.QRect(xs[s.name], top, SPRITE_W - 1, SPRITE_H - 1))
         p.drawText(QtCore.QRect(xs[s.name], top, SPRITE_W, SPRITE_H), QtCore.Qt.AlignmentFlag.AlignCenter, s.name)
      p.end()
      self.preview.set_image(img)
      front, back = ordered
      self.verdict.setText(f"{front.name} is in front: sort key {front.key()} (priority {front.priority}, "
                           f"sub-priority {front.sub}) against {back.key()} of {back.name} (priority "
                           f"{back.priority}, sub-priority {back.sub}); lower draws in front, a tie goes to the "
                           "lower edge.")

   def stop(self) -> None:
      """!Nothing pending: edits apply immediately.
      @return None
      """
      pass
