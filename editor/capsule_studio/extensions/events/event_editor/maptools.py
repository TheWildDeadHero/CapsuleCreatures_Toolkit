"""!The events extension's map tools: the Events tool (place, move or remove
events by clicking), the Map events overlay and hover text. The logic needs
no Qt; only the tool's options widget does.

The tool and the Events panel share the selected event through SELECTION,
so a click can move the event the panel shows, and a placed event is shown
there.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from capsule_studio.core import events
from capsule_studio.core.document import DocumentError
from capsule_studio.plugins import MapOverlay, MapTool

if TYPE_CHECKING:
   from PySide6 import QtWidgets

   from capsule_studio.core.document import Document
   from capsule_studio.plugins import MapView

## A JSON object (an event).
JsonDict = dict[str, Any]
## A colour (r, g, b, a), each 0-255.
Rgba = tuple[int, int, int, int]
## What an overlay draws on a cell: (colour or None, short text or None).
CellMark = tuple[Rgba | None, str | None]
## An overlay's per-cell function: callable(x, y, attribute cell or None) -> CellMark.
CellFunction = Callable[[int, int, int | None], CellMark]

## Overlay colours per kind (r, g, b, a).
COLORS = {"warps": (60, 120, 255, 130), "triggers": (255, 150, 30, 130), "signs": (40, 200, 90, 130)}
## Overlay letters per kind.
LETTERS = {"warps": "W", "triggers": "T", "signs": "S"}
## The selected event, shared with the Events panel: dict(map, kind, index, at), or empty.
## "at" is its cell when chosen: after an undo or a removal elsewhere the index may name
## another event, which is then not taken for it.
SELECTION = {}
## Tool actions.
ACTIONS = ["place", "move", "remove"]
## Numbers in an event's "at" cell ([x, y]).
CELL_COORDINATES = 2


def select(map_name: str, kind: str, index: int, at: list[int] | None = None) -> None:
   """!Selects an event (the panel shows it).
   @param map_name  map
   @param kind      event kind
   @param index     its index
   @param at        its cell [x, y]
   @return None
   """
   SELECTION.clear()
   SELECTION.update({"map": map_name, "kind": kind, "index": index, "at": at})


def selected(doc: Document | None, map_name: str | None) -> tuple[str, int, JsonDict] | None:
   """!The selected event, if it is still the one chosen.
   @param doc       the map's Document
   @param map_name  the map
   @return (kind, index, event), or None
   """
   if doc is None or SELECTION.get("map") != map_name:
      return None
   items = events.events(doc, SELECTION["kind"])
   i = SELECTION["index"]
   # an index out of range, or one now naming an event on another cell, is not the chosen event
   if not 0 <= i < len(items) or (SELECTION.get("at") is not None and items[i].get("at") != SELECTION["at"]):
      return None
   return SELECTION["kind"], i, items[i]


class EventTool(MapTool):
   """!Places a new event of a kind, moves the selected event, or removes the
   events on a cell, by clicking.

   @var kind
   Kind placed ('warps', 'triggers' or 'signs').
   @var action
   'place', 'move' or 'remove'.
   """
   id = "events"
   label = "Events"
   tooltip = ("Click a cell: place a warp, trigger or sign there (then fill it in on the Studio's Events tab or in "
              "the event editor), move the event chosen on the Events tab (or the one placed last) there, or "
              "remove the events on it")
   stroke = "click"

   def __init__(self) -> None:
      """!Places signs."""
      self.kind = "signs"
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
            out["index"] = events.add_event(doc, self.kind, x, y)
         if view.edit(f"Add {events.KINDS[self.kind]}", run):
            select(view.map_name, self.kind, out["index"], [x, y])
            view.status(f"{events.KINDS[self.kind]} added at {x},{y}: fill it in on the Studio's Events tab "
                        "or in the event editor")
      elif self.action == "move":
         chosen = selected(doc, view.map_name)
         if chosen is None:
            view.status("Choose an event of this map first: on the Studio's Events tab, or place one")
            return
         kind, index, _e = chosen
         if view.edit(f"Move {events.KINDS[kind]}", lambda: events.move_event(doc, kind, index, x, y)):
            select(view.map_name, kind, index, [x, y])
      else:
         here = events.events_at(doc, x, y)
         if not here:
            view.status(f"No events at {x},{y}")
            return
         try:
            for kind, index, _e in sorted(here, key=lambda h: -h[1]):   # highest index first
               events.remove_event(view.project, view.map_name, kind, index)
         except DocumentError as e:
            view.status(str(e))
         SELECTION.clear()
         view.edit("Events removed", lambda: None)   # lets the host refresh

   def options(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
      """!Action and kind choosers (Qt).
      @param parent  QWidget
      @return QWidget
      """
      from PySide6 import QtWidgets
      w = QtWidgets.QWidget(parent)
      lay = QtWidgets.QHBoxLayout(w)
      lay.setContentsMargins(0, 0, 0, 0)
      action = QtWidgets.QComboBox()
      action.addItems(["Place a new", "Move the selected event here", "Remove the events here"])
      action.setCurrentIndex(ACTIONS.index(self.action))
      kind = QtWidgets.QComboBox()
      kind.addItems([events.KINDS[k] for k in events.KINDS])
      kind.setCurrentIndex(list(events.KINDS).index(self.kind))

      def changed() -> None:
         self.action = ACTIONS[action.currentIndex()]
         self.kind = list(events.KINDS)[kind.currentIndex()]
         kind.setEnabled(self.action == "place")
      action.currentIndexChanged.connect(lambda *a: changed())
      kind.currentIndexChanged.connect(lambda *a: changed())
      lay.addWidget(action)
      lay.addWidget(kind)
      lay.addStretch(1)
      changed()
      return w


## I3: a warp's letter by what fires it (step and press warps are W; D door, A arrow, L a landing only) and the
## mark of a dynamic destination.
WARP_LETTERS = {"door": "D", "arrow": "A", "none": "L"}
## Added to a warp's letter when the game decides where it lands (I3 "to": "dynamic").
DYNAMIC_MARK = "?"


class EventOverlay(MapOverlay):
   """!Marks cells with events: W warp, T trigger, S sign (several letters when they share a cell); I3: D a door
   warp, A an arrow warp, L a landing only, ? after a warp whose destination the game decides."""
   ## See MapOverlay.id.
   id = "events"
   ## See MapOverlay.title.
   title = "Map events"

   def prepare(self, view: MapView) -> CellFunction:
      """!Collects the map's events once per repaint.
      @param view  MapView
      @return callable(x, y, cell) -> (rgba or None, text or None)
      """
      doc = view.doc
      cells: dict[tuple[int, int], list[tuple[str, str]]] = {}
      dynamic = events.dynamic_to()
      for kind, _i, e in events.all_events(doc) if doc is not None else []:
         at = e.get("at")
         if isinstance(at, list) and len(at) == CELL_COORDINATES:
            letter = LETTERS[kind]
            if kind == "warps":
               letter = WARP_LETTERS.get(e.get("trigger"), letter) + (DYNAMIC_MARK if e.get("to") == dynamic else "")
            cells.setdefault((at[0], at[1]), []).append((kind, letter))

      def cell(x: int, y: int, v: int | None) -> CellMark:
         marks = cells.get((x, y))
         if not marks:
            return None, None
         return COLORS[marks[0][0]], "".join(letter for _k, letter in marks)
      return cell


def hover_text(view: MapView, x: int, y: int, cell: int | None) -> str | None:
   """!The events on the hovered cell.
   @param view  MapView
   @param x     column
   @param y     row
   @param cell  attribute cell, or None
   @return text, or None
   """
   doc = view.doc
   if doc is None:
      return None
   here = events.events_at(doc, x, y)
   if not here:
      return None
   return "; ".join(f"{events.KINDS[k]} {i}: {events.describe(k, e)}" for k, i, e in here)
