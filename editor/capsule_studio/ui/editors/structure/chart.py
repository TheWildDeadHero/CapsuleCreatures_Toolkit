"""!The Tiers & Chart panel (D-23 §3.2 "Type chart"): the type chart's tiers,
how they combine, how many types a species has and effects may add, and the
matchup grid drawn from the tiers.

The tiers table edits a tier's name (a rename rewrites every cell and the
default), its kind (scaling, or decisive: zero / ko), its Q8 factor (256 =
x1; the factor and the exponent the exponent mode adds are shown), a
decisive tier's engine message and its shade (the studio's cell colour,
under "editor"). The settings form edits the combine mode, the default tier
(the tier of cells not given), types per species, added types and the
messages said above / below x1. In the grid (rows attack, columns defend) a
click gives the cell the tier picked above it; a right click steps the cell
to the next tier. Every change is one undo step of the battle manifest
(core.structure.chart); the engine's compiler checks the result and its
message shows at the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ....core.structure import chart as chart_model
from ...panes import split_box
from ...widgets import button
from ..battle_common import NONE_TEXT, STRUCTURE, BattlePanel, set_combo

if TYPE_CHECKING:
   from ...panel import PanelHost

## Tiers table columns, in order: (tier_list() key, header).
TIER_COLUMNS = [("name", "Name"), ("kind", "Kind"), ("q8", "Q8"), ("factor", "Factor"), ("exponent", "Exponent"),
                ("message", "Message"), ("shade", "Shade"), ("uses", "Cells"), ("default", "Default")]
## Tiers table column of each key.
TIER_COLUMN = {key: c for c, (key, _header) in enumerate(TIER_COLUMNS)}
## Columns typed as text (the name renames; an empty shade puts the default back).
TIER_TEXT_KEYS = ("name", "q8", "shade")
## Read-only columns.
TIER_READ_ONLY = ("factor", "exponent", "uses", "default")
## Kind choices of the kind combo: scaling or one of the decisive kinds (core.structure.chart.decisive_kinds()).
SCALE_TEXT = chart_model.SCALE
## Default text of the default-tier combo: the chart names none (the first tier at x1).
FIRST_X1_TEXT = "(first x1 tier)"
## Shade of a decisive zero tier (no effect).
ZERO_SHADE = "#c0c0c0"
## Shade of a decisive ko tier.
KO_SHADE = "#f0a0f0"
## Shades of factors above x1, by exponent (1: x2, 2: x4, ...; the last for any larger factor).
ABOVE_SHADES = ["#bfe8bf", "#8fd88f", "#60c060"]
## Shades of factors below x1, by exponent (-1: x0.5, -2: x0.25, ...; the last for any smaller factor).
BELOW_SHADES = ["#f0d0c0", "#e8b0a0", "#d89080"]
## Text colour of the default tier's name in the grid (its cells are left blank).
DEFAULT_COLOR = "#909090"
## Letters of a tier name shown in a grid cell.
CELL_LETTERS = 4
## Letters of a type name shown in a grid column header.
HEADER_LETTERS = 5
## Rows of the settings form (its (label, field) pairs fill it column by column).
FORM_ROWS = 3
## Grid columns of one (label, field) pair.
GRID_COLUMNS_PER_PAIR = 2
## Stretch of the tiers table in the panel's layout (it is as tall as its rows: _fit_tiers()).
TIERS_STRETCH = 0
## Frames above and below the tiers table's rows.
TIERS_FRAMES = 2
## Stretch of the matchup grid.
GRID_STRETCH = 2


def tier_shade(row: chart_model.TierRow | None) -> str | None:
   """!The colour of a tier's cells: its shade, else one from its kind and factor.
   @param row  a tier_list() row, or None (a cell naming no tier)
   @return "#rrggbb", or None for no colour (x1, or unknown)
   """
   if row is None:
      return None
   if row["shade"] is not None:
      return row["shade"]
   if row["kind"] == "zero":
      return ZERO_SHADE
   if row["kind"] == "ko":
      return KO_SHADE
   factor, exp = row["factor"], row["exponent"]
   if factor is None or factor == 1:
      return None
   # Steps away from x1: the exponent when it is one, else one step.
   steps = abs(exp) if exp is not None else 1
   shades = ABOVE_SHADES if factor > 1 else BELOW_SHADES
   return shades[min(steps, len(shades)) - 1]


def tier_cell_text(name: Any, default: str | None) -> str:
   """!A grid cell's text.
   @param name     the cell's tier (or a raw value naming none)
   @param default  the default tier (shown blank)
   @return text
   """
   if name == default:
      return ""
   return str(name)[:CELL_LETTERS]


class TiersChartPanel(BattlePanel):
   """!The tiers table, the chart settings and the matchup grid with its tier picker.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "chart"
   ## See EditorPanel.title.
   title = "Tiers & Chart"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the tables, the form and the buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Name of the selected tier, or None.
      self.selected = None
      ## The tiers, one row each.
      self.tiers = QtWidgets.QTableWidget(0, len(TIER_COLUMNS))
      self.tiers.setHorizontalHeaderLabels([h for _k, h in TIER_COLUMNS])
      self.tiers.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.tiers.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
      self.tiers.verticalHeader().setVisible(False)
      self.tiers.itemChanged.connect(lambda item: self._tier_cell_changed(item))
      self.tiers.itemSelectionChanged.connect(lambda: self._tier_selection_changed())
      ## Kind combos of the tiers table, by row.
      self.kind_combos = []
      ## Message combos of the tiers table, by row.
      self.message_combos = []
      ## How the tiers of a defender's types combine.
      self.combine = QtWidgets.QComboBox()
      self.combine.activated.connect(lambda _i: self.set_option("combine", self.combine.currentText()))
      ## The tier of cells not given.
      self.default = QtWidgets.QComboBox()
      self.default.activated.connect(lambda _i: self._default_picked())
      ## Types a species has.
      self.types_per_species = QtWidgets.QSpinBox()
      self.types_per_species.valueChanged.connect(lambda v: self.set_option("types_per_species", v))
      ## Types effects may add.
      self.added_types = QtWidgets.QSpinBox()
      self.added_types.valueChanged.connect(lambda v: self.set_option("added_types", v))
      ## Message said when the combined factor is above x1.
      self.above = QtWidgets.QComboBox()
      self.above.activated.connect(lambda _i: self._message_picked("above", self.above))
      ## Message said when the combined factor is below x1.
      self.below = QtWidgets.QComboBox()
      self.below.activated.connect(lambda _i: self._message_picked("below", self.below))
      ## The tier a click gives a grid cell.
      self.brush = QtWidgets.QComboBox()
      ## Attacker x defender grid.
      self.grid = QtWidgets.QTableWidget()
      self.grid.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.grid.cellClicked.connect(lambda r, c: self.paint_cell(r, c))
      self.grid.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
      self.grid.customContextMenuRequested.connect(lambda pos: self._grid_right_click(pos))
      self._build_layout()

   def _build_layout(self) -> None:
      """!Lays the widgets out.
      @return None
      """
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("A tier scales (Q8 factor, 256 = x1) or is decisive (zero: no effect; ko). The first "
                              "decisive tier of a defender's types ends the matchup; the scaling ones combine as "
                              "the combine mode says (exponent needs powers of two).")
      note.setWordWrap(True)
      lay.addWidget(note)
      lay.addWidget(self.tiers, TIERS_STRETCH)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add...", lambda: self.add_tier(), "Add a scaling tier at x1 after the selected one"))
      row.addWidget(button("Remove", lambda: self.remove_tier(), "Remove the selected tier (its cells take another)"))
      row.addWidget(button("Rename...", lambda: self.rename_tier(), "Rename the selected tier; the cells follow"))
      row.addWidget(button("Up", lambda: self.move_tier(-1), "Earlier in the list"))
      row.addWidget(button("Down", lambda: self.move_tier(1), "Later in the list"))
      row.addStretch(1)
      lay.addLayout(row)
      form = QtWidgets.QGridLayout()
      pairs = [("Combine", self.combine), ("Default tier", self.default), ("Above x1 says", self.above),
               (self.term_label("type", True, "{} per species"), self.types_per_species),
               (self.term_label("type", True, "Added {}"), self.added_types), ("Below x1 says", self.below)]
      for i, (label, w) in enumerate(pairs):
         r, c = i % FORM_ROWS, (i // FORM_ROWS) * GRID_COLUMNS_PER_PAIR
         form.addWidget(QtWidgets.QLabel(label) if isinstance(label, str) else label, r, c)
         form.addWidget(w, r, c + 1)
      lay.addLayout(form)
      brush_row = QtWidgets.QHBoxLayout()
      brush_row.addWidget(QtWidgets.QLabel("Matchups (rows attack, columns defend). A click sets the tier"))
      brush_row.addWidget(self.brush)
      brush_row.addWidget(QtWidgets.QLabel("; a right click steps to the next tier."))
      brush_row.addStretch(1)
      lay.addLayout(brush_row)
      lay.addWidget(self.grid, GRID_STRETCH)
      lay.addWidget(self.errors)
      split_box(lay)   # [RZ] tiers over the chart

   # -- reading ------------------------------------------------------------------------

   def rows(self) -> list[chart_model.TierRow]:
      """!The tiers as the table shows them.
      @return tier_list() rows ([] with nothing open)
      """
      doc = self.battle_doc()
      return chart_model.tier_list(doc) if doc is not None else []

   def refresh(self) -> None:
      """!Re-reads the tiers, the settings and the grid.
      @return None
      """
      self.update_terms()
      doc = self.battle_doc()
      rows = self.rows()
      names = [r["name"] for r in rows]
      if self.selected not in names:
         self.selected = names[0] if names else None
      self._filling = True
      try:
         self._fill_tiers(rows)
         self._fill_options(doc, names)
         self._fill_grid(doc, rows)
      finally:
         self._filling = False
      for w in (self.tiers, self.grid, self.combine, self.default, self.types_per_species, self.added_types,
                self.above, self.below, self.brush):
         w.setEnabled(doc is not None)
      self.show_errors()

   def _fill_tiers(self, rows: list[chart_model.TierRow]) -> None:
      """!The tiers table.
      @param rows  tier_list() rows
      @return None
      """
      self.tiers.setRowCount(len(rows))
      self.kind_combos, self.message_combos = [], []
      editable = QtCore.Qt.ItemFlag.ItemIsEditable
      kinds = [SCALE_TEXT] + chart_model.decisive_kinds()
      messages = [NONE_TEXT] + chart_model.message_keys(self.battle_doc())
      for r, row in enumerate(rows):
         for key, c in TIER_COLUMN.items():
            if key == "kind":
               self.tiers.setItem(r, c, QtWidgets.QTableWidgetItem(""))
               box = QtWidgets.QComboBox()
               box.addItems(kinds)
               box.setCurrentText(row["kind"])
               box.activated.connect(lambda _i, name=row["name"], b=box: self.set_kind(name, b.currentText()))
               self.tiers.setCellWidget(r, c, box)
               self.kind_combos.append(box)
               continue
            if key == "message":
               self.tiers.setItem(r, c, QtWidgets.QTableWidgetItem(""))
               box = QtWidgets.QComboBox()
               box.addItems(messages)
               box.setCurrentText(row["message"] or NONE_TEXT)
               box.setEnabled(row["kind"] != SCALE_TEXT)
               box.activated.connect(lambda _i, name=row["name"], b=box: self.set_tier(
                  name, "message", None if b.currentText() == NONE_TEXT else b.currentText()))
               self.tiers.setCellWidget(r, c, box)
               self.message_combos.append(box)
               continue
            value = row[key]
            if key == "factor":
               text = f"x{value:g}" if value is not None else ""
            elif key == "default":
               text = "yes" if value else ""
            else:
               text = "" if value is None else str(value)
            item = QtWidgets.QTableWidgetItem(text)
            if key in TIER_READ_ONLY or (key == "q8" and row["kind"] != SCALE_TEXT):
               item.setFlags(item.flags() & ~editable)
            if key == "shade":
               shade = tier_shade(row)
               if shade is not None:
                  item.setBackground(QtGui.QColor(shade))
               if row["shade"] is None:
                  item.setToolTip("The default shade (type #rrggbb to choose one)")
            self.tiers.setItem(r, c, item)
      self.tiers.resizeColumnsToContents()
      self._fit_tiers()
      names = [row["name"] for row in rows]
      if self.selected in names:
         self.tiers.selectRow(names.index(self.selected))

   def _fit_tiers(self) -> None:
      """!Makes the tiers table tall enough for every tier (at most the engine's tier cap, so it never needs
      to scroll; the matchup grid below takes the rest of the height).
      @return None
      """
      t = self.tiers
      rows = sum(t.rowHeight(r) for r in range(t.rowCount()))
      bar = t.horizontalScrollBar().sizeHint().height() if t.horizontalScrollBar().isVisible() else 0
      height = t.horizontalHeader().sizeHint().height() + rows + bar + TIERS_FRAMES * t.frameWidth()
      t.setMinimumHeight(height)
      t.setMaximumHeight(height)

   def _fill_options(self, doc: Any, names: list[str]) -> None:
      """!The settings form and the tier picker.
      @param doc    battle Document, or None
      @param names  tier names
      @return None
      """
      o = chart_model.options(doc) if doc is not None else {}
      set_combo(self.combine, chart_model.combine_modes(), o.get("combine"))
      set_combo(self.default, [FIRST_X1_TEXT] + names, o.get("default") if o.get("default_given") else FIRST_X1_TEXT)
      messages = [NONE_TEXT] + chart_model.message_keys(doc)
      set_combo(self.above, messages, o.get("above") or NONE_TEXT)
      set_combo(self.below, messages, o.get("below") or NONE_TEXT)
      most = chart_model.max_types_per()
      for box, lo, hi, key in ((self.types_per_species, 1, most, "types_per_species"),
                               (self.added_types, 0, most, "added_types")):
         box.blockSignals(True)
         box.setRange(lo, hi)
         value = o.get(key)
         box.setValue(value if isinstance(value, int) else lo)
         box.blockSignals(False)
      keep = self.brush.currentText()
      set_combo(self.brush, names, keep if keep in names else (names[0] if names else None))

   def _fill_grid(self, doc: Any, rows: list[chart_model.TierRow]) -> None:
      """!The matchup grid.
      @param doc   battle Document, or None
      @param rows  tier_list() rows
      @return None
      """
      types = chart_model.type_names(doc) if doc is not None else []
      cells = chart_model.grid(doc) if doc is not None else []
      by_name = {r["name"]: r for r in rows}
      default = chart_model.default_tier(doc) if doc is not None else None
      self.grid.blockSignals(True)
      self.grid.setRowCount(len(types))
      self.grid.setColumnCount(len(types))
      self.grid.setHorizontalHeaderLabels([t[:HEADER_LETTERS] for t in types])
      self.grid.setVerticalHeaderLabels(types)
      for r, (a, line) in enumerate(zip(types, cells)):
         for c, (d, tier) in enumerate(zip(types, line)):
            item = QtWidgets.QTableWidgetItem(tier_cell_text(tier, default))
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            row = by_name.get(tier)
            item.setToolTip(f"{a} attacking {d}: {tier}" + ("" if row is not None else " (no such tier)"))
            shade = tier_shade(row)
            if shade is not None:
               item.setBackground(QtGui.QColor(shade))
            self.grid.setItem(r, c, item)
      self.grid.resizeColumnsToContents()
      self.grid.blockSignals(False)

   # -- editing: tiers -------------------------------------------------------------------

   def _tier_selection_changed(self) -> None:
      """!Another tier row was picked.
      @return None
      """
      if self._filling:
         return
      rows = self.tiers.selectionModel().selectedRows()
      names = [r["name"] for r in self.rows()]
      if rows and rows[0].row() < len(names):
         self.selected = names[rows[0].row()]

   def _tier_cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A tiers table cell was typed in.
      @param item  QTableWidgetItem
      @return None
      """
      if self._filling:
         return
      names = [r["name"] for r in self.rows()]
      key = TIER_COLUMNS[item.column()][0]
      if not 0 <= item.row() < len(names) or key not in TIER_TEXT_KEYS:
         return
      name, text = names[item.row()], item.text().strip()
      if key == "name":
         if text != name:
            self.rename_tier(text, name)
         return
      if key == "q8":
         try:
            value: Any = int(text)
         except ValueError:
            self.host.show_status("Q8 is a whole number (256 = x1).")
            self.host.changed()
            return
      else:
         value = text or None
      self.set_tier(name, key, value)

   def set_tier(self, name: str, key: str, value: Any) -> bool:
      """!Changes one property of a tier (one undo step).
      @param name   tier name
      @param key    one of core.structure.chart.TIER_PROPERTIES
      @param value  the value
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      row = next((r for r in self.rows() if r["name"] == name), None)
      if row is not None and row.get(key if key != "decisive" else "kind") == value:
         return False
      ok = self.edit(f"Tier {key}", lambda: chart_model.set_tier(doc, name, key, value))
      if not ok:
         self.host.changed()
      return ok

   def set_kind(self, name: str, kind: str) -> bool:
      """!Makes a tier scaling or decisive (one undo step).
      @param name  tier name
      @param kind  "scale", "zero" or "ko"
      @return True when the edit went through
      """
      return self.set_tier(name, "decisive", None if kind == SCALE_TEXT else kind)

   def add_tier(self, name: str | None = None, q8: int | None = None, decisive: str | None = None) -> bool:
      """!Adds a tier after the selected one.
      @param name      its name, or None to ask
      @param q8        its Q8 factor (None: x1, unless decisive)
      @param decisive  "zero" or "ko", or None for a scaling tier
      @return True when added
      """
      doc = self.battle_doc()
      if doc is None:
         return False
      if name is None:
         name, ok = QtWidgets.QInputDialog.getText(self, "Add tier", "Name:")
         if not ok or not name.strip():
            return False
      names = [r["name"] for r in self.rows()]
      at = names.index(self.selected) + 1 if self.selected in names else None
      if self.edit("Add tier", lambda: chart_model.add_tier(doc, name, q8, decisive, None, at)):
         self.selected = name.strip()
         return True
      return False

   def remove_tier(self, replace: str | None = None, ask: bool = True) -> bool:
      """!Removes the selected tier; the cells naming it take another tier (asked for when there are any).
      @param replace  the tier they take, or None
      @param ask      ask for it when it is needed and not given
      @return True when removed
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      row = next((r for r in self.rows() if r["name"] == name), None)
      used = row is not None and (row["uses"] or chart_model.options(doc)["default"] == name)
      if used and replace is None and ask:
         others = [r["name"] for r in self.rows() if r["name"] != name]
         replace, ok = QtWidgets.QInputDialog.getItem(self, "Remove tier", f"Cells naming {name} take:", others, 0,
                                                      False)
         if not ok:
            return False
      if self.edit("Remove tier", lambda: chart_model.remove_tier(doc, name, replace if used else None)):
         self.selected = None
         return True
      return False

   def rename_tier(self, new: str | None = None, old: str | None = None) -> bool:
      """!Renames a tier; every cell and the default follow (one undo step).
      @param new  the new name, or None to ask
      @param old  the tier, or None for the selected one
      @return True when renamed
      """
      doc = self.battle_doc()
      old = old or self.selected
      if doc is None or old is None:
         return False
      if new is None:
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename tier", "New name:", text=old)
         if not ok:
            return False
      new = new.strip()
      if not new or new == old:
         self.host.changed()
         return False
      if self.edit("Rename tier", lambda: chart_model.rename_tier(doc, old, new)):
         self.selected = new
         return True
      self.host.changed()
      return False

   def move_tier(self, delta: int) -> bool:
      """!Moves the selected tier up or down.
      @param delta  -1 up, +1 down
      @return True when it moved
      """
      doc, name = self.battle_doc(), self.selected
      if doc is None or name is None:
         return False
      moved = []
      ok = self.edit("Move tier", lambda: moved.append(chart_model.move_tier(doc, name, delta)))
      return ok and moved == [True]

   # -- editing: settings and cells ------------------------------------------------------

   def set_option(self, key: str, value: Any) -> bool:
      """!Changes one chart setting (one undo step).
      @param key    one of core.structure.chart.OPTIONS
      @param value  the value (None: the engine's default)
      @return True when the edit went through
      """
      doc = self.battle_doc()
      if self._filling or doc is None:
         return False
      o = chart_model.options(doc)
      if o.get(key) == value and (key != "default" or o["default_given"] == (value is not None)):
         return False
      ok = self.edit("Chart setting", lambda: chart_model.set_option(doc, key, value))
      if not ok:
         self.host.changed()
      return ok

   def _default_picked(self) -> None:
      """!The default-tier combo changed.
      @return None
      """
      text = self.default.currentText()
      self.set_option("default", None if text == FIRST_X1_TEXT else text)

   def _message_picked(self, key: str, box: QtWidgets.QComboBox) -> None:
      """!An above / below message combo changed.
      @param key  "above" or "below"
      @param box  the combo
      @return None
      """
      text = box.currentText()
      self.set_option(key, None if text == NONE_TEXT else text)

   def _cell_types(self, row: int, col: int) -> tuple[str, str] | None:
      """!The types of a grid cell.
      @param row  attacker row
      @param col  defender column
      @return (attacker, defender), or None outside the grid
      """
      doc = self.battle_doc()
      types = chart_model.type_names(doc) if doc is not None else []
      if not (0 <= row < len(types) and 0 <= col < len(types)):
         return None
      return types[row], types[col]

   def set_cell(self, row: int, col: int, tier: str) -> bool:
      """!Gives a grid cell a tier (one undo step).
      @param row   attacker row
      @param col   defender column
      @param tier  tier name
      @return True when the cell changed
      """
      doc = self.battle_doc()
      cell = self._cell_types(row, col)
      if doc is None or cell is None or chart_model.matchup(doc, *cell) == tier:
         return False
      return self.edit("Type chart", lambda: chart_model.set_matchup(doc, cell[0], cell[1], tier))

   def paint_cell(self, row: int, col: int) -> bool:
      """!Gives a grid cell the picked tier.
      @param row  attacker row
      @param col  defender column
      @return True when the cell changed
      """
      tier = self.brush.currentText()
      return bool(tier) and self.set_cell(row, col, tier)

   def step_cell(self, row: int, col: int, delta: int = 1) -> bool:
      """!Steps a grid cell to the next (or previous) tier.
      @param row    attacker row
      @param col    defender column
      @param delta  +1 next, -1 previous
      @return True when the cell changed
      """
      doc = self.battle_doc()
      cell = self._cell_types(row, col)
      if doc is None or cell is None or not chart_model.tier_names(doc):
         return False
      return self.set_cell(row, col, chart_model.step_tier(doc, cell[0], cell[1], delta))

   def _grid_right_click(self, pos: QtCore.QPoint) -> None:
      """!Steps the right-clicked cell.
      @param pos  QPoint in the grid's viewport
      @return None
      """
      item = self.grid.itemAt(pos)
      if item is not None:
         self.step_cell(item.row(), item.column())
