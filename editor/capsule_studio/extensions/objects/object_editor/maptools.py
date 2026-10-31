"""!The objects extension's map tools: the Objects tool (place, move or
remove objects by clicking), the Map objects overlay and hover text. The
logic needs no Qt; only the tool's options widget does.

The tool and the Objects panel share the selected object through SELECTION,
so a click can move the object the panel shows, and a placed object is shown
there.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from capsule_studio.core import objects
from capsule_studio.core.document import DocumentError
from capsule_studio.plugins import MapOverlay, MapTool

if TYPE_CHECKING:
   from PySide6 import QtWidgets

   from capsule_studio.core.document import Document
   from capsule_studio.plugins import MapView

## A JSON object (a map object).
JsonDict = dict[str, Any]
## A colour (r, g, b, a), each 0-255.
Rgba = tuple[int, int, int, int]
## What an overlay draws on a cell: (colour or None, short text or None).
CellMark = tuple[Rgba | None, str | None]
## An overlay's per-cell function: callable(x, y, attribute cell or None) -> CellMark.
CellFunction = Callable[[int, int, int | None], CellMark]

## Overlay colours (r, g, b, a): objects, spotters, a spotter's sight line.
COLORS = {"object": (170, 80, 220, 140), "spotter": (230, 40, 40, 150), "sight": (230, 40, 40, 60)}
## Facing marks after the letter.
ARROWS = {"down": "v", "up": "^", "left": "<", "right": ">"}
## The selected object, shared with the Objects panel: dict(map, index, name), or empty.
## "name" is its name when chosen: after an undo or a removal the index may name another
## object, which is then not taken for it.
SELECTION = {}
## Tool actions.
ACTIONS = ["place", "move", "remove"]
## Numbers in an object's "at" cell ([x, y]).
CELL_COORDINATES = objects.XY_ENTRIES


def select(map_name: str, index: int, name: str | None = None) -> None:
   """!Selects an object (the panel shows it).
   @param map_name  map
   @param index     local ID
   @param name      its name
   @return None
   """
   SELECTION.clear()
   SELECTION.update({"map": map_name, "index": index, "name": name})


def selected(doc: Document | None, map_name: str | None) -> tuple[int, JsonDict] | None:
   """!The selected object, if it is still the one chosen.
   @param doc       the map's Document
   @param map_name  the map
   @return (local ID, object), or None
   """
   if doc is None or SELECTION.get("map") != map_name:
      return None
   items = objects.objects(doc)
   i = SELECTION["index"]
   if not 0 <= i < len(items) or not isinstance(items[i], dict):
      return None
   if SELECTION.get("name") is not None and items[i].get("name") != SELECTION["name"]:
      return None
   return i, items[i]


class ObjectTool(MapTool):
   """!Places a new object, moves the selected object, or removes the objects
   on a cell, by clicking.

   @var action
   'place', 'move' or 'remove'.
   """
   id = "objects"
   label = "Objects"
   tooltip = ("Click a cell: place an object there (then fill it in on the Studio's Objects tab or in the "
              "object editor), move the object chosen on the Objects tab (or the one placed last) there, or "
              "remove the objects on it")
   stroke = "click"

   def __init__(self) -> None:
      """!Places objects."""
      self.action = "place"

   def apply(self, view: MapView, cells: list[tuple[int, int]]) -> None:
      """!One click (one undo step).
      @param view   MapView
      @param cells  [(x, y)]
      @return None
      """
      doc = view.doc
      if doc is None or not cells:
         return
      x, y = cells[0]
      if self.action == "place":
         out: dict[str, int] = {}

         def run() -> None:
            out["index"] = objects.add_object(doc, x, y)
         if view.edit("Add object", run):
            select(view.map_name, out["index"], objects.objects(doc)[out["index"]]["name"])
            view.status(f"object added at {x},{y}: fill it in on the Studio's Objects tab or in the object editor")
      elif self.action == "move":
         chosen = selected(doc, view.map_name)
         if chosen is None:
            view.status("Choose an object of this map first: on the Studio's Objects tab, or place one")
            return
         index, o = chosen
         if view.edit("Move object", lambda: objects.move_object(doc, index, x, y)):
            select(view.map_name, index, o.get("name"))
      else:
         here = objects.objects_at(doc, x, y)
         if not here:
            view.status(f"No objects at {x},{y}")
            return
         shifted: list[str] = []

         def run() -> None:
            for index, _o in sorted(here, key=lambda h: -h[0]):   # highest local ID first
               shifted[:] = objects.remove_object(doc, index)
         try:
            if view.edit("Remove object", run) and shifted:
               view.status(f"Local IDs after it moved down ({', '.join(shifted)}); scripts naming them "
                           "by number must follow")
         except DocumentError as e:
            view.status(str(e))
         SELECTION.clear()

   def options(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
      """!Action chooser (Qt).
      @param parent  QWidget
      @return QWidget
      """
      from PySide6 import QtWidgets
      w = QtWidgets.QWidget(parent)
      lay = QtWidgets.QHBoxLayout(w)
      lay.setContentsMargins(0, 0, 0, 0)
      action = QtWidgets.QComboBox()
      action.addItems(["Place a new object", "Move the selected object here", "Remove the objects here"])
      action.setCurrentIndex(ACTIONS.index(self.action))

      def changed() -> None:
         self.action = ACTIONS[action.currentIndex()]
      action.currentIndexChanged.connect(lambda *a: changed())
      lay.addWidget(action)
      lay.addStretch(1)
      return w


class ObjectOverlay(MapOverlay):
   """!Marks objects: O with its facing (S for spotters), and a spotter's sight line."""
   ## See MapOverlay.id.
   id = "objects"
   ## See MapOverlay.title.
   title = "Map objects"

   def prepare(self, view: MapView) -> CellFunction:
      """!Collects the map's objects once per repaint.
      @param view  MapView
      @return callable(x, y, cell) -> (rgba or None, text or None)
      """
      doc = view.doc
      marks: dict[tuple[int, int], list[tuple[str, bool]]] = {}
      sight: set[tuple[int, int]] = set()
      for _i, o in enumerate(objects.objects(doc) if doc is not None else []):
         at = o.get("at") if isinstance(o, dict) else None
         if not (isinstance(at, list) and len(at) == CELL_COORDINATES):
            continue
         spotter = isinstance(o.get("spotter"), dict)
         letter = ("S" if spotter else "O") + ARROWS.get(o.get("facing", "down"), "")
         marks.setdefault((at[0], at[1]), []).append((letter, spotter))
         sight.update(objects.sight_cells(o))

      def cell(x: int, y: int, v: int | None) -> CellMark:
         here = marks.get((x, y))
         if here:
            color = COLORS["spotter"] if any(t for _l, t in here) else COLORS["object"]
            return color, "".join(letter for letter, _t in here)
         if (x, y) in sight:
            return COLORS["sight"], None
         return None, None
      return cell


def hover_text(view: MapView, x: int, y: int, cell: int | None) -> str | None:
   """!The objects on the hovered cell.
   @param view  MapView
   @param x     column
   @param y     row
   @param cell  attribute cell, or None
   @return text, or None
   """
   doc = view.doc
   if doc is None:
      return None
   here = objects.objects_at(doc, x, y)
   if not here:
      return None
   return "; ".join(f"object {i} {o.get('name')}: {objects.describe(o)}" for i, o in here)
