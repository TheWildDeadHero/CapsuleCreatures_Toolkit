"""!The encounter editor's map tools: the Encounter area brush, the
Encounter tables overlay and hover text. The logic needs no Qt; only the
brush's options widget does (built by UI hosts)."""
from __future__ import annotations

import colorsys
from collections.abc import Callable
from typing import TYPE_CHECKING

from capsule_studio.core import encounters, maps
from capsule_studio.plugins import MapOverlay, MapTool

if TYPE_CHECKING:
   from PySide6 import QtWidgets

   from capsule_studio.plugins import MapView

## A colour (r, g, b, a), each 0-255.
Rgba = tuple[int, int, int, int]
## What an overlay draws on a cell: (colour or None, short text or None).
CellMark = tuple[Rgba | None, str | None]
## An overlay's per-cell function: callable(x, y, attribute cell or None) -> CellMark.
CellFunction = Callable[[int, int, int | None], CellMark]

## Overlay alpha.
ALPHA = 120
## Colour of encounter cells whose slot has no step table.
MISSING = (230, 40, 40, 150)
## Hue step from one slot to the next (1 - 1/golden ratio), so neighbouring slots get far-apart hues.
HUE_STEP = 0.381966
## Saturation of the slot colours.
SATURATION = 0.75
## Brightness (HSV value) of the slot colours.
BRIGHTNESS = 0.95
## Largest colour channel value (colorsys gives 0.0-1.0 channels).
CHANNEL_MAX = 255
## The attribute cell field of the encounter flag (core.maps.cell_fields(): the engine's).
ENCOUNTER_FIELD = "encounter"
## The attribute cell field of the encounter slot.
SLOT_FIELD = "slot"


def slot_color(slot: int) -> Rgba:
   """!A distinct colour per slot.
   @param slot  0-15
   @return (r, g, b, a)
   """
   r, g, b = colorsys.hsv_to_rgb((slot * HUE_STEP) % 1.0, SATURATION, BRIGHTNESS)
   return int(r * CHANNEL_MAX), int(g * CHANNEL_MAX), int(b * CHANNEL_MAX), ALPHA


class EncounterBrush(MapTool):
   """!Paints encounter cells in a slot, or takes encounters off cells.

   @var slot
   Slot painted (0-15).
   @var on
   True paints encounter cells; False clears the encounter flag.
   """
   id = "area"
   label = "Encounters"
   tooltip = ("Paint encounter cells in the chosen slot (each slot rolls its own tables: the "
              "Encounters tab or the encounter editor), or take encounters off; drag for a line, "
              "shift-drag for a rectangle")
   stroke = "line"

   def __init__(self) -> None:
      """!Slot 0, painting encounter cells."""
      self.slot = 0
      self.on = True

   def apply(self, view: MapView, cells: list[tuple[int, int]]) -> None:
      """!Sets the encounter flag and slot of the painted cells of a stroke (one undo step).
      @param view   MapView
      @param cells  list of (x, y)
      @return None
      """
      doc = view.doc
      if doc is None:
         return
      painted = [(x, y) for x, y in cells if maps.is_painted(doc.data, x, y)]
      if not painted:
         view.status("Encounters go on painted cells: paint a metatile there first")
         return

      def run() -> None:
         for x, y in painted:
            if self.on:
               maps.set_attributes(doc, x, y, encounter=True, slot=self.slot)
            else:
               maps.set_attributes(doc, x, y, encounter=False, slot=0)
      view.edit(f"Encounters (slot {self.slot})" if self.on else "No encounters", run)

   def options(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
      """!Slot and on/off chooser, with the slot's tables (Qt).
      @param parent  QWidget
      @return QWidget
      """
      from PySide6 import QtWidgets
      w = QtWidgets.QWidget(parent)
      lay = QtWidgets.QHBoxLayout(w)
      lay.setContentsMargins(0, 0, 0, 0)
      mode = QtWidgets.QComboBox()
      mode.addItems(["Paint encounters in slot", "Take encounters off"])
      mode.setCurrentIndex(0 if self.on else 1)
      slot = QtWidgets.QSpinBox()
      slot.setRange(0, encounters.MAX_SLOTS - 1)
      slot.setValue(self.slot)
      slot.setToolTip("Which of the map's encounter tables these cells use (0-15)")

      def changed() -> None:
         self.on = mode.currentIndex() == 0
         self.slot = slot.value()
         slot.setEnabled(self.on)
      mode.currentIndexChanged.connect(lambda *a: changed())
      slot.valueChanged.connect(lambda *a: changed())
      lay.addWidget(mode)
      lay.addWidget(slot)
      lay.addStretch(1)
      return w


class EncounterOverlay(MapOverlay):
   """!Colours encounter cells by slot (red where the slot has no step table) and shows the slot number."""
   ## See MapOverlay.id.
   id = "slots"
   ## See MapOverlay.title.
   title = "Encounter tables"

   def prepare(self, view: MapView) -> CellFunction:
      """!Looks up which slots have step tables once per repaint.
      @param view  MapView
      @return callable(x, y, cell) -> (rgba or None, text or None)
      """
      steps = set(encounters.step_methods(view.project))
      covered = {s for s, ts in encounters.slot_tables(view.project, view.map_name).items()
                 if any(m in steps for m, _t in ts)}
      fields = maps.cell_fields()
      enc_mask, enc_shift = fields[ENCOUNTER_FIELD]
      slot_mask, slot_shift = fields[SLOT_FIELD]

      def cell(x: int, y: int, v: int | None) -> CellMark:
         # unpack the attribute cell's encounter flag and slot
         if v is None or not (v >> enc_shift) & enc_mask:
            return None, None
         s = (v >> slot_shift) & slot_mask
         return (slot_color(s) if s in covered else MISSING), f"{s:X}"
      return cell


def hover_text(view: MapView, x: int, y: int, cell: int | None) -> str | None:
   """!The hovered encounter cell's slot and tables.
   @param view  MapView
   @param x     column
   @param y     row
   @param cell  attribute cell, or None
   @return text, or None
   """
   fields = maps.cell_fields()
   enc_mask, enc_shift = fields[ENCOUNTER_FIELD]
   slot_mask, slot_shift = fields[SLOT_FIELD]
   if cell is None or not (cell >> enc_shift) & enc_mask:
      return None
   return encounters.describe_slot(view.project, view.map_name, (cell >> slot_shift) & slot_mask)
