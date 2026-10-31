"""!Tileset panel parts for the I2 / I3 tileset format: a fixed tileset's placement, palette banks and raw metatile
entries, and the tile animations of any tileset (phase, from_sheet, on_shift; S3: targets at frame offsets). The
TilesetPanel hosts them in tabs under its sheet; every change goes through the panel's edit (one undo step;
renumbered "all" maps join it)."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import tilesets
from ..panes import split_box
from ..widgets import button, set_enabled
from .tileset_targets import TargetsBox

if TYPE_CHECKING:
   from ...core.document import Document
   from .tileset import TilesetPanel

## A parsed JSON object.
JsonDict = dict[str, Any]

## Side of a bank color swatch, pixels.
SWATCH = 18
## Columns of the raw entry table: tile, h flip, v flip, bank.
ENTRY_COLUMNS = ("Tile", "H", "V", "Bank")
## Slot names of a metatile, in entry order.
SLOTS = ("top-left", "top-right", "bottom-left", "bottom-right")
## Largest VRAM tile a raw entry names (10 bits).
ENTRY_TILE_MAX = 0x3FF
## Largest palette bank a raw entry names (4 bits).
ENTRY_BANK_MAX = 15
## Layout stretch of the animation list.
LIST_STRETCH = 1
## Layout stretch of the animation's fields.
FORM_STRETCH = 2
## Spin box value meaning "no phase" (the compiler spreads the map's animations), shown as "auto".
NO_PHASE = -1


class FixedBox(QtWidgets.QWidget):
   """!A fixed tileset's placement (sheet, first VRAM tile, tiles owned, first bank, banks owned), its palette banks
   as swatches (click one to change it) and the chosen metatile's four raw entries. Shows a "Make fixed" button for a
   tileset that is not fixed yet."""

   def __init__(self, panel: TilesetPanel) -> None:
      """!Builds the box.
      @param panel  the owning TilesetPanel
      """
      super().__init__()
      ## The owning panel.
      self.panel = panel
      ## True while the box fills its widgets.
      self._filling = False
      ## The placement's sheet.
      self.sheet = QtWidgets.QComboBox()
      self.sheet.setToolTip("The indexed sheet loaded at the first tile (the tileset's VRAM tiles)")
      ## First VRAM tile.
      self.tile = QtWidgets.QSpinBox()
      ## VRAM tiles owned.
      self.tiles = QtWidgets.QSpinBox()
      ## First palette bank.
      self.palette = QtWidgets.QSpinBox()
      ## Banks owned.
      self.palettes = QtWidgets.QSpinBox()
      for w, tip in ((self.tile, "First VRAM tile the tileset's sheet is loaded at"),
                     (self.tiles, "VRAM tiles the tileset owns (no other tileset of a map may place them)"),
                     (self.palette, "First palette bank the tileset's banks load to"),
                     (self.palettes, "Palette banks the tileset owns")):
         w.setToolTip(tip)
         w.valueChanged.connect(lambda *a: self._place_edited())
      self.sheet.activated.connect(lambda *a: self._place_edited())
      ## "Make fixed" for a tileset without a placement.
      self.make = button("Make fixed placement", lambda: self._make_fixed(),
                         "Turn this (empty) tileset into a fixed-placement one: indexed sheets used as they are, "
                         "raw tilemap entries, its own palette banks")
      ## Adds an indexed sheet.
      self.add_sheet = button("Import indexed sheet...", lambda: self.panel.import_indexed_sheet(),
                              "A palette PNG whose pixels are palette indices 0-15 (copied next to the tileset)")
      form = QtWidgets.QFormLayout()
      form.addRow("Sheet", self.sheet)
      form.addRow("First tile", self.tile)
      form.addRow("Tiles owned", self.tiles)
      form.addRow("First bank", self.palette)
      form.addRow("Banks owned", self.palettes)
      ## The banks' swatches.
      self.banks = QtWidgets.QTableWidget()
      self.banks.setColumnCount(tilesets._mc().BANK_COLORS)
      self.banks.horizontalHeader().setDefaultSectionSize(SWATCH)
      self.banks.verticalHeader().setDefaultSectionSize(SWATCH)
      self.banks.horizontalHeader().setVisible(False)
      self.banks.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.banks.setToolTip("Palette banks (16 colors each, entry 0 included): click a color to change it; the row "
                            "after the last adds a bank")
      self.banks.cellClicked.connect(lambda r, c: self._color_clicked(r, c))
      ## Raw entries of the chosen metatile.
      self.entries = QtWidgets.QTableWidget(len(SLOTS), len(ENTRY_COLUMNS))
      self.entries.setHorizontalHeaderLabels(list(ENTRY_COLUMNS))
      self.entries.setVerticalHeaderLabels(list(SLOTS))
      self.entries.setToolTip("The chosen metatile's tilemap entries: VRAM tile, mirrors and palette bank (any tile "
                              "of any fixed tileset the map loads)")
      ## Per slot: tile spin, h box, v box, bank spin.
      self._entry_widgets = []
      for slot in range(len(SLOTS)):
         t, h, v, b = QtWidgets.QSpinBox(), QtWidgets.QCheckBox(), QtWidgets.QCheckBox(), QtWidgets.QSpinBox()
         t.setRange(0, ENTRY_TILE_MAX)
         b.setRange(0, ENTRY_BANK_MAX)
         for w in (t, b):
            w.valueChanged.connect(lambda *a, s=slot: self._entry_edited(s))
         for w in (h, v):
            w.toggled.connect(lambda *a, s=slot: self._entry_edited(s))
         for col, w in enumerate((t, h, v, b)):
            self.entries.setCellWidget(slot, col, w)
         self._entry_widgets.append((t, h, v, b))
      lay = QtWidgets.QVBoxLayout(self)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.make)
      row.addWidget(self.add_sheet)
      row.addWidget(button("Remove last bank", lambda: self._remove_bank()))
      row.addStretch(1)
      lay.addLayout(row)
      top = QtWidgets.QHBoxLayout()
      top.addLayout(form)
      top.addWidget(self.banks, 1)
      lay.addLayout(top)
      lay.addWidget(QtWidgets.QLabel("Raw entries of the chosen metatile"))
      lay.addWidget(self.entries)
      split_box(lay)   # [RZ] placement and banks over the raw entries

   def fill(self, doc: Document | None) -> None:
      """!Shows a tileset's placement, banks and the chosen metatile's entries.
      @param doc  tileset Document, or None
      @return None
      """
      self._filling = True
      try:
         mc = tilesets._mc()
         pl = tilesets.place_of(doc) if doc is not None else None
         fixed = pl is not None
         self.make.setVisible(doc is not None and not fixed)
         for w in (self.sheet, self.tile, self.tiles, self.palette, self.palettes, self.banks, self.entries):
            set_enabled(w, fixed)   # the tables go read-only and keep their scroll bars
         self.add_sheet.setEnabled(doc is not None and (fixed or not doc.data.get("sheets")))
         self.sheet.clear()
         if doc is not None:
            self.sheet.addItems([s.get("name") for s in doc.data.get("sheets", [])])
         self.tile.setRange(0, mc.MAX_TILES - 1)
         self.tiles.setRange(1, mc.MAX_TILES)
         self.palette.setRange(0, mc.MAX_PALETTES - 1)
         self.palettes.setRange(0, mc.MAX_PALETTES)
         if fixed:
            self.sheet.setCurrentText(str(pl.get("sheet")))
            self.tile.setValue(pl.get("tile", 0))
            self.tiles.setValue(pl.get("tiles", 1))
            self.palette.setValue(pl.get("palette", 0))
            self.palettes.setValue(pl.get("palettes", 0))
         banks = tilesets.bank_colors(doc) if doc is not None else []
         # one row per owned bank (the ones not listed yet are blank: clicking adds them)
         rows = max(len(banks), pl.get("palettes", 0) if fixed else 0)
         self.banks.setRowCount(rows)
         self.banks.setVerticalHeaderLabels([str((pl or {}).get("palette", 0) + r) for r in range(rows)])
         for r in range(rows):
            for c in range(mc.BANK_COLORS):
               item = QtWidgets.QTableWidgetItem()
               if r < len(banks):
                  item.setBackground(QtGui.QColor(banks[r][c]))
                  item.setToolTip(f"bank {(pl or {}).get('palette', 0) + r} entry {c}: {banks[r][c]}")
               self.banks.setItem(r, c, item)
         self._fill_entries(doc)
      finally:
         self._filling = False

   def _fill_entries(self, doc: Document | None) -> None:
      """!The chosen metatile's raw entries.
      @param doc  tileset Document, or None
      @return None
      """
      m = None
      if doc is not None and self.panel.mt_name is not None:
         try:
            m = tilesets.metatile(doc, self.panel.mt_name)
         except ValueError:
            m = None
      entries = m.get("entries") if isinstance(m, dict) else None
      set_enabled(self.entries, isinstance(entries, list))   # read-only, still scrolling
      for slot, (t, h, v, b) in enumerate(self._entry_widgets):
         tile, hf, vf, bank = tilesets.split_entry(entries[slot]) if isinstance(entries, list) else (0, False, False, 0)
         t.setValue(tile)
         h.setChecked(hf)
         v.setChecked(vf)
         b.setValue(bank)

   def _place_edited(self) -> None:
      """!A placement field changed.
      @return None
      """
      doc = self.panel.ts_doc()
      if self._filling or doc is None or not tilesets.is_fixed(doc):
         return
      fields = {"sheet": self.sheet.currentText() or None, "tile": self.tile.value(), "tiles": self.tiles.value(),
                "palette": self.palette.value(), "palettes": self.palettes.value()}
      pl = tilesets.place_of(doc)
      changed = {k: v for k, v in fields.items() if pl.get(k) != v}
      if changed:
         self.panel.edit_tileset("Placement", lambda: tilesets.set_place(doc, **changed))

   def _make_fixed(self) -> None:
      """!Gives the tileset a placement.
      @return None
      """
      doc = self.panel.ts_doc()
      if doc is None:
         self.panel.explain("Make fixed placement", "tileset")
      else:
         first = next((s.get("name") for s in doc.data.get("sheets", [])), None)
         self.panel.edit_tileset("Make fixed", lambda: tilesets.set_place(doc, sheet=first))

   def _color_clicked(self, row: int, column: int) -> None:
      """!Changes one bank color (a color dialog).
      @param row     the tileset's bank
      @param column  the entry
      @return None
      """
      doc = self.panel.ts_doc()
      if doc is None or not tilesets.is_fixed(doc):
         return
      banks = tilesets.bank_colors(doc)
      start = QtGui.QColor(banks[row][column]) if row < len(banks) else QtGui.QColor(tilesets.BLACK)
      c = QtWidgets.QColorDialog.getColor(start, self, f"Bank {row} entry {column}")
      if c.isValid():
         self.set_color(row, column, "#{:02x}{:02x}{:02x}".format(c.red(), c.green(), c.blue()))

   def set_color(self, bank: int, entry: int, color: str) -> None:
      """!Sets one bank color (one undo step).
      @param bank   the tileset's bank
      @param entry  0-15
      @param color  "#rrggbb"
      @return None
      """
      doc = self.panel.ts_doc()
      if doc is not None:
         self.panel.edit_tileset("Bank color", lambda: tilesets.set_bank_color(doc, bank, entry, color))

   def _remove_bank(self) -> None:
      """!Removes the last listed bank.
      @return None
      """
      doc = self.panel.ts_doc()
      if doc is None:
         self.panel.explain("Remove last bank", "tileset")
      else:
         self.panel.edit_tileset("Remove bank", lambda: tilesets.remove_last_bank(doc))

   def _entry_edited(self, slot: int) -> None:
      """!A raw entry's tile, mirror or bank changed.
      @param slot  0-3
      @return None
      """
      doc, name = self.panel.ts_doc(), self.panel.mt_name
      if self._filling or doc is None or name is None:
         return
      t, h, v, b = self._entry_widgets[slot]
      entry = tilesets.make_entry(t.value(), h.isChecked(), v.isChecked(), b.value())
      self.panel.edit_tileset("Set entry", lambda: tilesets.set_entry(doc, name, slot, entry))


class AnimationBox(QtWidgets.QWidget):
   """!A tileset's tile animations: the list, and the chosen one's name, first tile ("tiles" or, fixed, "at"),
   count, frame sheet, period, phase (I2; "auto": spread by the compiler), from_sheet and on_shift (I3)."""

   def __init__(self, panel: TilesetPanel) -> None:
      """!Builds the box.
      @param panel  the owning TilesetPanel
      """
      super().__init__()
      ## The owning panel.
      self.panel = panel
      ## True while the box fills its widgets.
      self._filling = False
      ## The animations.
      self.list = QtWidgets.QListWidget()
      self.list.currentRowChanged.connect(lambda *a: self._chosen())
      ## Name.
      self.name = QtWidgets.QLineEdit()
      ## First tile: "sheet:index" (regular) or a number from the placement's first tile (fixed).
      self.first = QtWidgets.QLineEdit()
      self.first.setToolTip("First replaced tile: \"sheet:index\", or for a fixed tileset its number counted from "
                            "the placement's first tile (\"at\")")
      ## Tiles replaced.
      self.count = QtWidgets.QSpinBox()
      ## The frame sheet.
      self.frames = QtWidgets.QComboBox()
      ## Display frames per animation frame.
      self.period = QtWidgets.QSpinBox()
      ## Frames into the period at map entry (I2), or NO_PHASE.
      self.phase = QtWidgets.QSpinBox()
      self.phase.setSpecialValueText("auto")
      self.phase.setToolTip("Frames into the period when a map is entered (auto: the compiler spreads the map's "
                            "animations over their periods)")
      ## I3: no frame uploaded at entry.
      self.from_sheet = QtWidgets.QCheckBox("Start from the sheet's own tiles")
      self.from_sheet.setToolTip("No frame is uploaded when a map is entered: the tileset's own tiles show until the "
                                 "first frame change (I3 from_sheet)")
      ## I3: what a seamless map shift does.
      self.on_shift = QtWidgets.QComboBox()
      self.on_shift.setToolTip("When the walker steps onto a connected map that runs it too: keep (runs on), reload "
                               "(its tiles are reloaded) or restart (reloaded and started over)")
      mc = tilesets._mc()
      self.count.setRange(1, mc.MAX_ANIMATION_TILES)
      self.period.setRange(1, mc.MAX_ANIMATION_PERIOD)
      self.phase.setRange(NO_PHASE, mc.MAX_ANIMATION_PERIOD - 1)
      self.on_shift.addItems(tilesets.on_shift_words())
      for w in (self.name, self.first):
         w.editingFinished.connect(lambda: self._edited())
      for w in (self.count, self.period, self.phase):
         w.valueChanged.connect(lambda *a: self._edited())
      self.frames.activated.connect(lambda *a: self._edited())
      self.on_shift.activated.connect(lambda *a: self._edited())
      self.from_sheet.toggled.connect(lambda *a: self._edited())
      form = QtWidgets.QFormLayout()
      form.addRow("Name", self.name)
      form.addRow("First tile", self.first)
      form.addRow("Tiles", self.count)
      form.addRow("Frame sheet", self.frames)
      form.addRow("Period", self.period)
      form.addRow("Phase", self.phase)
      form.addRow("", self.from_sheet)
      form.addRow("On a map shift", self.on_shift)
      left = QtWidgets.QVBoxLayout()
      left.addWidget(self.list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add", lambda: self._add()))
      row.addWidget(button("Remove", lambda: self._remove()))
      left.addLayout(row)
      ## [S3] the chosen animation's targets (D-30 section 5).
      self.targets = TargetsBox(self)
      right = QtWidgets.QVBoxLayout()
      right.addLayout(form)
      right.addWidget(self.targets, 1)
      lay = QtWidgets.QHBoxLayout(self)
      lay.addLayout(left, LIST_STRETCH)
      lay.addLayout(right, FORM_STRETCH)
      split_box(lay)   # [RZ] animations | form: the user drags the boundary

   def fill(self, doc: Document | None) -> None:
      """!Shows a tileset's animations.
      @param doc  tileset Document, or None
      @return None
      """
      self._filling = True
      try:
         row = self.list.currentRow()
         self.list.clear()
         items = tilesets.animations(doc) if doc is not None else []
         self.list.addItems([str(an.get("name", f"animation {i}")) for i, an in enumerate(items)])
         self.frames.clear()
         if doc is not None:
            self.frames.addItems([s.get("name") for s in doc.data.get("sheets", [])])
         if items:
            self.list.setCurrentRow(min(max(row, 0), len(items) - 1))
         self._show(doc)
      finally:
         self._filling = False

   def _current(self) -> tuple[Document | None, int, JsonDict | None]:
      """!The chosen animation.
      @return (tileset Document, index, animation dict) — None parts when there is none
      """
      doc = self.panel.ts_doc()
      items = tilesets.animations(doc) if doc is not None else []
      i = self.list.currentRow()
      return doc, i, items[i] if 0 <= i < len(items) else None

   def _show(self, doc: Document | None) -> None:
      """!Shows the chosen animation's fields.
      @param doc  tileset Document, or None
      @return None
      """
      _doc, _i, an = self._current()
      for w in (self.name, self.first, self.count, self.frames, self.period, self.phase, self.from_sheet,
                self.on_shift):
         w.setEnabled(an is not None)
      self.targets.fill()
      if an is None:
         return
      # S3: with targets, the first tile and the phase are each target's
      for w in (self.first, self.phase):
         w.setEnabled(not tilesets.targets(an))
      mc = tilesets._mc()
      fixed = doc is not None and tilesets.is_fixed(doc)
      self.name.setText(str(an.get("name", "")))
      self.first.setText(str(an.get("at", 0)) if fixed else str(an.get("tiles", "")))
      self.count.setValue(an.get("count", 1))
      self.frames.setCurrentText(str(an.get("frames", "")))
      self.period.setValue(an.get("period", mc.DEFAULT_ANIMATION_PERIOD))
      self.phase.setMaximum(self.period.value() - 1)
      self.phase.setValue(an["phase"] if isinstance(an.get("phase"), int) else NO_PHASE)
      self.from_sheet.setChecked(an.get("from_sheet", False) is True)
      self.on_shift.setCurrentText(an.get("on_shift", "keep"))

   def _chosen(self) -> None:
      """!Another animation was picked.
      @return None
      """
      if self._filling:
         return
      self._filling = True
      try:
         self._show(self.panel.ts_doc())
      finally:
         self._filling = False

   def _edited(self) -> None:
      """!A field changed: the chosen animation takes the form's values (one undo step).
      @return None
      """
      doc, i, an = self._current()
      if self._filling or an is None:
         return
      fixed = tilesets.is_fixed(doc)
      fields: dict[str, Any] = {"name": self.name.text().strip() or None, "count": self.count.value(),
                                "frames": self.frames.currentText() or None, "period": self.period.value(),
                                "phase": None if self.phase.value() == NO_PHASE else
                                min(self.phase.value(), self.period.value() - 1),
                                "from_sheet": self.from_sheet.isChecked(), "on_shift": self.on_shift.currentText()}
      text = self.first.text().strip()
      if tilesets.targets(an):   # S3: the targets name the tiles and phases
         fields.pop("phase")
      elif fixed:
         fields["at"] = int(text) if text.isdigit() else an.get("at", 0)
      else:
         fields["tiles"] = text or an.get("tiles")
      if all(an.get(k, _default(k)) == v for k, v in fields.items() if v is not None) and \
            all(k in an or _default(k) is None for k, v in fields.items() if v is None):
         return
      self.panel.edit_tileset("Animation", lambda: tilesets.set_animation(doc, i, **fields))

   def _add(self) -> None:
      """!Adds an animation of the tileset's first sheet.
      @return None
      """
      doc = self.panel.ts_doc()
      if doc is None or not doc.data.get("sheets"):
         self.panel.host.show_status("The tileset needs a sheet first (its frames are another sheet's tiles)")
         return
      sheets = [s.get("name") for s in doc.data["sheets"]]
      name = tilesets.unique_name([a.get("name") for a in tilesets.animations(doc)], "animation")
      first: dict[str, Any] = {} if tilesets.is_fixed(doc) else {"tiles": f"{sheets[0]}:0"}
      self.panel.edit_tileset("Add animation", lambda: tilesets.add_animation(doc, name, sheets[-1], **first))

   def _remove(self) -> None:
      """!Removes the chosen animation.
      @return None
      """
      doc, i, an = self._current()
      if an is None:
         self.panel.explain("Remove animation", "animation")
      else:
         self.panel.edit_tileset("Remove animation", lambda: tilesets.remove_animation(doc, i))


def _default(key: str) -> Any:
   """!The value an animation key has when it is left out (the compiler's defaults).
   @param key  animation key
   @return the default, or None when there is none
   """
   mc = tilesets._mc()
   return {"count": 1, "period": mc.DEFAULT_ANIMATION_PERIOD, "from_sheet": False, "on_shift": "keep",
           "at": 0}.get(key)


## A change of a tileset, run by TilesetPanel.edit_tileset().
Change = Callable[[], object]
