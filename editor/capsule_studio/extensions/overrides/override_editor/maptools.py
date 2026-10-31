"""!The override sets extension's map tools (S3): the Override sets tool (paint the chosen set's cells on a layer,
or take them out), the Override sets overlay and hover text. The logic needs no Qt; only the tool's options widget
does.

The tool and the Override sets panel share what is chosen through SELECTION (the map, the set, the layer, the
metatile painted), so the panel picks what a stroke paints.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from capsule_studio.core import override_sets
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

## Overlay colour of the chosen set's cells and of the other sets' cells (r, g, b, a).
CHOSEN_COLOR, OTHER_COLOR = (230, 60, 200, 140), (150, 90, 220, 90)
## Overlay letter of a set's cell.
LETTER = "O"
## What the panel chose: map, set, layer, metatile ("tileset/name" or None: nothing), erase (bool).
SELECTION: dict[str, Any] = {}
## Tool actions.
ACTIONS = ("paint", "erase")


def choose(map_name: str | None, name: str | None, layer: int = 0, metatile: str | None = None) -> None:
   """!Sets what the tool paints (the panel calls it).
   @param map_name  the map
   @param name      the set, or None
   @param layer     the tile layer
   @param metatile  the metatile painted, or None for nothing
   @return None
   """
   SELECTION.update({"map": map_name, "set": name, "layer": layer, "metatile": metatile})


class OverrideTool(MapTool):
   """!Paints the chosen override set's cells (each a stroke's cell on the chosen layer showing the chosen metatile,
   or nothing), or takes cells out of it.

   @var action
   'paint' or 'erase'.
   """
   id = "overrides"
   label = "Override sets"
   tooltip = ("Drag over cells: they join the override set chosen on the Override sets tab, showing its metatile on "
              "its layer when a script applies the set (or are taken out of the set)")
   stroke = "rect"

   def __init__(self) -> None:
      """!Paints."""
      self.action = ACTIONS[0]

   def apply(self, view: MapView, cells: list[tuple[int, int]]) -> None:
      """!One stroke (one undo step).
      @param view   MapView
      @param cells  [(x, y)]
      @return None
      """
      doc = view.doc
      name = SELECTION.get("set")
      if doc is None or not cells:
         return
      if SELECTION.get("map") != view.map_name or name not in override_sets.set_names(doc):
         view.status("Choose an override set of this map first (Override sets tab)")
         return
      layer = SELECTION.get("layer", 0)
      if self.action == ACTIONS[1]:
         view.edit("Erase override cells", lambda: override_sets.erase(doc, name, cells, layer))
      else:
         view.edit("Paint override cells", lambda: override_sets.paint(doc, name, cells, layer,
                                                                       SELECTION.get("metatile")))

   def options(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
      """!Paint or erase (Qt).
      @param parent  QWidget
      @return QWidget
      """
      from PySide6 import QtWidgets
      w = QtWidgets.QComboBox(parent)
      w.addItems(["Paint the chosen set's cells", "Take cells out of the set"])
      w.setCurrentIndex(ACTIONS.index(self.action))
      w.currentIndexChanged.connect(lambda i: setattr(self, "action", ACTIONS[i]))
      return w


class OverrideOverlay(MapOverlay):
   """!Marks the cells override sets change: O (the chosen set brighter)."""
   ## See MapOverlay.id.
   id = "overrides"
   ## See MapOverlay.title.
   title = "Override sets"

   def prepare(self, view: MapView) -> CellFunction:
      """!Collects the map's set cells once per repaint.
      @param view  MapView
      @return callable(x, y, cell) -> (rgba or None, text or None)
      """
      doc = view.doc
      marks: dict[tuple[int, int], bool] = {}
      chosen = SELECTION.get("set") if SELECTION.get("map") == view.map_name else None
      for s in override_sets.sets(doc) if doc is not None else []:
         for c in s.get("cells", []):
            at = c.get("cell")
            if isinstance(at, list) and len(at) == override_sets.CELL_COORDINATES:
               key = (at[0], at[1])
               marks[key] = marks.get(key, False) or s.get("name") == chosen

      def cell(x: int, y: int, v: int | None) -> CellMark:
         if (x, y) not in marks:
            return None, None
         return (CHOSEN_COLOR if marks[(x, y)] else OTHER_COLOR), LETTER
      return cell


def hover_text(view: MapView, x: int, y: int, cell: int | None) -> str | None:
   """!The override sets changing the hovered cell.
   @param view  MapView
   @param x     column
   @param y     row
   @param cell  attribute cell, or None
   @return text, or None
   """
   doc = view.doc
   if doc is None:
      return None
   out = []
   for s in override_sets.sets(doc):
      for c in s.get("cells", []):
         if c.get("cell") == [x, y]:
            what = "entries" if "entries" in c else str(c.get("metatile"))
            out.append(f"override set {s.get('name')}: layer {c.get('layer', 0)} -> {what}")
   return "; ".join(out) or None
