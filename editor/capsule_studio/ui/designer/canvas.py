"""!The manifest designer's canvas (D-43 §5): DesignerScene (what is drawn, and what a drag means) and DesignerView
(the grid, pan and zoom).

The scene shows the session's diagram and rebuilds from it after every change (sync()), so undo, redo and edits
from elsewhere show at once. Drags change only the items while the mouse is down; the release writes the change
through the session as one undo step:
  - moving elements (snapped to the grid, and to other elements' edges and centres along the alignment guides);
    a frame carries what it holds, and an element dropped inside a frame goes into it;
  - drawing a wire from a port: ports it cannot end on fade; ending in empty space asks for a node to add, already
    wired (Node-RED's quick-add);
  - drawing a connector from an element's arrow handle to another element (draw.io);
  - resizing a shape by its corner;
  - dropping a palette kind; double-clicking empty canvas to add one by typing.

The view scrolls with the wheel and its scroll bars (never locked), zooms with Ctrl+wheel, pans with the middle
button or Space+drag, selects with a rubber band, nudges the selection with the arrow keys and deletes it with
Delete.
"""
from __future__ import annotations

import shiboken6
from PySide6 import QtCore, QtGui, QtWidgets

from ...core.designer import checks, layout, ops
from ...core.designer import system as dsystem
from ...core.designer.model import SIDE_IN, SIDE_OUT, Endpoint, ModelError
from ...core.designer.session import DesignSession
from .items import (CONNECTOR_COLOUR, CURVE_REACH, CURVE_SHARE, DIMMED_OPACITY, HALVES, WIRE_WIDTH, ElementItem,
                    LinkItem, PortItem, type_colour)

## Mime type of a palette kind being dragged (its id, UTF-8).
KIND_MIME = "application/x-capsule-designer-kind"
## Z of the grid, under everything.
GRID_Z = -1000000.0
## Z of frames (plus their depth), under everything else.
FRAME_Z = -1000.0
## Z of links: over frames, under elements.
LINK_Z = -100.0
## Z of the first element (each later one is one higher).
ELEMENT_Z = 0.0
## Z of the wire being drawn.
DRAG_Z = 100000.0
## Room around the diagram the scroll bars reach, canvas units.
SCENE_MARGIN = 2000
## How close an edge must come to another's to snap to it, canvas units.
GUIDE_THRESHOLD = 6
## Colour of the alignment guides.
GUIDE_COLOUR = QtGui.QColor("#ff7f0e")
## Colour of the canvas.
CANVAS_COLOUR = QtGui.QColor("#fbfbfb")
## Colour of the grid lines.
GRID_COLOUR = QtGui.QColor("#e8e8e8")
## Fewest screen pixels between grid lines (a finer grid is not drawn).
GRID_MIN_PIXELS = 8
## Zoom step of Ctrl+wheel and Zoom in / out.
ZOOM_STEP = 1.2
## Smallest zoom, percent.
ZOOM_MIN = 10
## Largest zoom, percent.
ZOOM_MAX = 400
## A percentage's whole.
PERCENT = 100
## Room left around the diagram by Zoom to fit, canvas units.
FIT_MARGIN = 40
## Wheel angle of one notch, eighths of a degree (Qt's).
WHEEL_NOTCH = 120


def clip_to_rect(rect: QtCore.QRectF, inside: QtCore.QPointF, outside: QtCore.QPointF) -> QtCore.QPointF:
   """!Where the line from a point inside a rectangle towards another point leaves the rectangle.
   @param rect     the rectangle
   @param inside   a point inside it (its centre)
   @param outside  the other point
   @return the point on the border (inside itself when outside lies inside too)
   """
   dx, dy = outside.x() - inside.x(), outside.y() - inside.y()
   if dx == 0 and dy == 0:
      return inside
   # The smallest positive step to any of the four sides.
   steps = []
   if dx:
      steps += [(rect.left() - inside.x()) / dx, (rect.right() - inside.x()) / dx]
   if dy:
      steps += [(rect.top() - inside.y()) / dy, (rect.bottom() - inside.y()) / dy]
   t = min((s for s in steps if s > 0), default=0.0)
   t = min(t, 1.0)
   return QtCore.QPointF(inside.x() + dx * t, inside.y() + dy * t)


class GridItem(QtWidgets.QGraphicsRectItem):
   """!The canvas and its grid, under everything; the mouse passes through it (rubber-band selection starts on it).
   Lines closer than GRID_MIN_PIXELS on screen are skipped, so the grid thins out when zoomed out."""

   def __init__(self, scene: DesignerScene) -> None:
      """!Creates the grid.
      @param scene  the scene (its show_grid decides whether lines are drawn)
      """
      super().__init__()
      ## The scene.
      self.owner = scene
      self.setZValue(GRID_Z)
      self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
      self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
      self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))

   def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem,
             widget: QtWidgets.QWidget | None = None) -> None:
      """!The canvas colour and the grid lines in the exposed part.
      @param painter  the painter
      @param option   style options (exposedRect)
      @param widget   the widget, or None
      @return None
      """
      rect = option.exposedRect
      painter.fillRect(rect, CANVAS_COLOUR)
      if not self.owner.show_grid:
         return
      scale = painter.worldTransform().m11()
      step = layout.GRID
      while step * scale < GRID_MIN_PIXELS:
         step *= HALVES
      painter.setPen(QtGui.QPen(GRID_COLOUR, 0))
      left = int(rect.left()) - int(rect.left()) % step
      top = int(rect.top()) - int(rect.top()) % step
      lines = []
      x = left
      while x < rect.right():
         lines.append(QtCore.QLineF(x, rect.top(), x, rect.bottom()))
         x += step
      y = top
      while y < rect.bottom():
         lines.append(QtCore.QLineF(rect.left(), y, rect.right(), y))
         y += step
      painter.drawLines(lines)


class DesignerScene(QtWidgets.QGraphicsScene):
   """!The diagram of one DesignSession."""

   ## An element or link wants its fields shown (double-click): its id.
   edit_requested = QtCore.Signal(str)
   ## Add a node by typing: screen position, canvas position, and the port a wire was dragged from ("" for none).
   add_requested = QtCore.Signal(QtCore.QPoint, QtCore.QPointF, str)
   ## Something could not be done: why.
   refused = QtCore.Signal(str)
   ## The selection changed, in the order elements were picked: element ids.
   picked = QtCore.Signal(list)

   def __init__(self, session: DesignSession, parent: QtCore.QObject | None = None) -> None:
      """!Creates the scene and shows the diagram.
      @param session  the session
      @param parent   its owner
      """
      super().__init__(parent)
      ## The session.
      self.session = session
      ## The system.
      self.system = session.system
      ## Element items by id.
      self.element_items = {}
      ## Link items by id.
      self.link_items = {}
      ## Whether drags snap to the grid.
      self.snap_to_grid = True
      ## Whether the grid is drawn.
      self.show_grid = True
      ## The alignment guides shown while dragging (line items).
      self.guides = []
      ## The drag of elements under way: element id -> its position when the drag started (the selected ones and
      ## what the frames among them hold), or None.
      self._drag = None
      ## The grid, under everything.
      self.grid = GridItem(self)
      self.addItem(self.grid)
      ## The wire or connector being drawn: (start endpoint, temporary path item), or None.
      self._drawing = None
      ## Element ids in the order they were selected (the first is the anchor of align and same size).
      self.selection_order = []
      ## What the Document calls after each change (kept to unsubscribe it again).
      self._on_change = lambda: self.sync()
      self.selectionChanged.connect(lambda: self._selection_changed())
      session.doc.subscribe(self._on_change)
      self.sync()

   def close(self) -> None:
      """!Stops following the Document.
      @return None
      """
      self.session.doc.unsubscribe(self._on_change)

   # -- showing the diagram -------------------------------------------------------------------------------------------

   def sync(self) -> None:
      """!Shows the session's diagram: items added, updated and removed to match; links routed; problems marked.
      @return None
      """
      try:
         diagram = self.session.diagram()
      except ModelError as e:
         self.refused.emit(f"the manifest cannot be shown: {e}")
         return
      try:
         values = self.session.live_values()
      except (ModelError, KeyError, TypeError, ValueError):
         values = {}
      problems = self.session.diagnostics()
      bad_elements = {e for p in problems for e in p.elements}
      bad_links = {k for p in problems for k in p.links}
      kinds = {k.kind_id: k for k in self.system.kinds()}
      selected = set(self.selection_order)
      self.blockSignals(True)
      for gone in [i for i in self.element_items if i not in diagram.elements or diagram.elements[i].kind
                   not in kinds or self.element_items[i].kind.kind_id != diagram.elements[i].kind]:
         self.removeItem(self.element_items.pop(gone))
      for n, (element_id, element) in enumerate(diagram.elements.items()):
         kind = kinds.get(element.kind)
         if kind is None:
            continue   # an unknown kind is a problem the panel lists, not something to draw
         item = self.element_items.get(element_id)
         if item is None:
            item = ElementItem(self, element, kind)
            self.addItem(item)
            self.element_items[element_id] = item
         item.update_from(self, element, self.system.node_text(element), values.get(element_id, ""),
                          element_id in bad_elements)
         depth = len(self._frames_above(diagram, element_id))
         item.setZValue(FRAME_Z + depth if kind.container else ELEMENT_Z + n)
         item.setSelected(element_id in selected)
      for gone in [k for k in self.link_items if k not in diagram.links]:
         self.removeItem(self.link_items.pop(gone))
      for link_id, link in diagram.links.items():
         item = self.link_items.get(link_id)
         if item is None:
            item = LinkItem(link, self._link_colour(diagram, link))
            item.setZValue(LINK_Z)
            self.addItem(item)
            self.link_items[link_id] = item
         item.colour = self._link_colour(diagram, link)
         item.set_state(link, link_id in bad_links)
         item.setSelected(link_id in selected)
         self.route(item)
      self.selection_order = [i for i in self.selection_order if i in self.element_items or i in self.link_items]
      self.blockSignals(False)
      self._sync_handles()
      self._grow()
      self.update()

   def _frames_above(self, diagram: object, element_id: str) -> list[str]:
      """!The frames that hold an element, innermost first.
      @param diagram     the diagram
      @param element_id  the element
      @return frame ids
      """
      out = []
      parent = diagram.elements[element_id].parent
      while parent is not None and parent in diagram.elements and parent not in out:
         out.append(parent)
         parent = diagram.elements[parent].parent
      return out

   def _link_colour(self, diagram: object, link: object) -> QtGui.QColor:
      """!A wire's data type colour, or the connector colour.
      @param diagram  the diagram
      @param link     the link
      @return the colour
      """
      spec = checks.port_spec(self.system, diagram, link.source)
      return CONNECTOR_COLOUR if spec is None else type_colour(self.system, spec.data_type)

   def _grow(self) -> None:
      """!Lets the scroll bars reach the whole diagram and room around it.
      @return None
      """
      rect = QtCore.QRectF()
      for item in list(self.element_items.values()) + list(self.link_items.values()):
         rect = rect.united(item.sceneBoundingRect())
      if rect.isNull():
         rect = QtCore.QRectF(0, 0, 1, 1)
      self.setSceneRect(rect.adjusted(-SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN))
      self.grid.setRect(self.sceneRect())

   def route(self, item: LinkItem) -> None:
      """!Lays a link between its ends' current positions.
      @param item  the link item
      @return None
      """
      link = item.link
      a = self.element_items.get(link.source.element)
      b = self.element_items.get(link.target.element)
      if a is None or b is None:
         item.setVisible(False)
         return
      item.setVisible(True)
      vertical = self.system.direction == dsystem.TOP_TO_BOTTOM
      if link.source.port is not None and link.target.port is not None:
         item.route(a.port_scene_pos(link.source.port), b.port_scene_pos(link.target.port), True, vertical)
         return
      ra, rb = a.sceneBoundingRect(), b.sceneBoundingRect()
      item.route(clip_to_rect(ra, ra.center(), rb.center()), clip_to_rect(rb, rb.center(), ra.center()), False,
                 vertical)

   def element_geometry_changed(self, item: ElementItem) -> None:
      """!An element was resized on the canvas: its links follow.
      @param item  the element item
      @return None
      """
      self._reroute({item.element_id})

   def _reroute(self, ids: set[str]) -> None:
      """!Lays again the links that touch some elements.
      @param ids  element ids
      @return None
      """
      for link in self.link_items.values():
         if link.link.source.element in ids or link.link.target.element in ids:
            self.route(link)

   # -- snapping ------------------------------------------------------------------------------------------------------

   def snap_length(self, value: float) -> int:
      """!A length on the grid (when snapping).
      @param value  the length
      @return it, snapped
      """
      return ops.snap(int(round(value)), layout.GRID if self.snap_to_grid else 0)

   def snap_drag(self, item: ElementItem, value: QtCore.QPointF,
                 moving: set[str] | None = None) -> QtCore.QPointF:
      """!Where a dragged element goes: on the grid, then onto a close edge or centre of another element (drawing
      the guide).
      @param item    the element dragged
      @param value   where Qt would put it
      @param moving  the elements moving with it (no guides to them), or None
      @return where it goes
      """
      x, y = value.x(), value.y()
      if self.snap_to_grid:
         x, y = float(self.snap_length(x)), float(self.snap_length(y))
      w, h = item.size
      self._clear_guides()
      lines = []
      mine_x = (x, x + w / HALVES, x + w)
      mine_y = (y, y + h / HALVES, y + h)
      best_x = best_y = None
      for other in self.element_items.values():
         if other is item or other.isSelected() or (moving is not None and other.element_id in moving):
            continue
         r = QtCore.QRectF(other.pos(), QtCore.QSizeF(other.size[0], other.size[1]))
         theirs_x = (r.left(), r.center().x(), r.right())
         theirs_y = (r.top(), r.center().y(), r.bottom())
         # The closest pair of edges or centres within GUIDE_THRESHOLD wins, along each axis.
         for mine in mine_x:
            for theirs in theirs_x:
               gap = abs(mine - theirs)
               if gap <= GUIDE_THRESHOLD and (best_x is None or gap < best_x[0]):
                  best_x = (gap, theirs - (mine - x), theirs, r)
         for mine in mine_y:
            for theirs in theirs_y:
               gap = abs(mine - theirs)
               if gap <= GUIDE_THRESHOLD and (best_y is None or gap < best_y[0]):
                  best_y = (gap, theirs - (mine - y), theirs, r)
      if best_x is not None:
         _gap, x, at_x, r = best_x
         lines.append(QtCore.QLineF(at_x, min(r.top(), y), at_x, max(r.bottom(), y + h)))
      if best_y is not None:
         _gap, y, at_y, r = best_y
         lines.append(QtCore.QLineF(min(r.left(), x), at_y, max(r.right(), x + w), at_y))
      pen = QtGui.QPen(GUIDE_COLOUR, 0, QtCore.Qt.PenStyle.DashLine)
      for line in lines:
         guide = QtWidgets.QGraphicsLineItem(line)
         guide.setPen(pen)
         guide.setZValue(DRAG_Z)
         self.addItem(guide)
         self.guides.append(guide)
      return QtCore.QPointF(x, y)

   def _clear_guides(self) -> None:
      """!Removes the alignment guides.
      @return None
      """
      for guide in self.guides:
         self.removeItem(guide)
      self.guides = []

   # -- committing drags ----------------------------------------------------------------------------------------------

   def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Notes where the elements a drag may move start: the selected ones, and what the frames among them hold.
      @param event  the event
      @return None
      """
      super().mousePressEvent(event)
      self._drag = None
      grabber = self.mouseGrabberItem()
      if event.button() != QtCore.Qt.MouseButton.LeftButton or not isinstance(grabber, ElementItem):
         return
      start = {}
      diagram = self.session.diagram()
      for item in self.element_items.values():
         if item.isSelected():
            start[item.element_id] = QtCore.QPointF(item.pos())
            if item.kind.container and item.element_id in diagram.elements:
               for held in diagram.descendants(item.element_id):
                  other = self.element_items.get(held.element_id)
                  if other is not None:
                     start.setdefault(held.element_id, QtCore.QPointF(other.pos()))
      self._drag = (grabber, start)

   def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!While elements are dragged: snaps the one under the mouse (the grid, the guides), moves the rest of the
      selection by the same amount, carries the frames' contents, and keeps the links attached.
      @param event  the event
      @return None
      """
      super().mouseMoveEvent(event)
      if self._drag is None:
         return
      grabber, start = self._drag
      if grabber.element_id not in start:
         return
      snapped = self.snap_drag(grabber, grabber.pos(), set(start))
      delta = snapped - start[grabber.element_id]
      for element_id, origin in start.items():
         item = self.element_items.get(element_id)
         if item is not None:
            item.setPos(origin + delta)
      self._reroute(set(start))

   def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Writes a finished drag of elements as one move.
      @param event  the event
      @return None
      """
      super().mouseReleaseEvent(event)
      self._drag = None
      self._clear_guides()
      self.commit_moves()

   def commit_moves(self) -> None:
      """!Moves the selected elements in the session by how far they were dragged.
      @return None
      """
      try:
         diagram = self.session.diagram()
      except ModelError:
         return
      moved = []
      delta = None
      for item in self.element_items.values():
         if not item.isSelected():
            continue
         element = diagram.elements.get(item.element_id)
         if element is None:
            continue
         dx, dy = int(round(item.pos().x())) - element.pos[0], int(round(item.pos().y())) - element.pos[1]
         if dx or dy:
            moved.append(item.element_id)
            delta = delta or (dx, dy)
      if moved and delta is not None:
         self._run(lambda: self.session.move(moved, delta[0], delta[1]))

   def resized(self, item: ElementItem) -> None:
      """!Writes a finished resize.
      @param item  the element item
      @return None
      """
      self._run(lambda: self.session.resize(item.element_id, item.size))

   def _run(self, change: object) -> object:
      """!Runs a session change; a refusal is reported and the canvas shows the diagram as it is.
      @param change  callable making the change
      @return what it returned, or None when refused
      """
      try:
         return change()
      except ModelError as e:
         self.refused.emit(str(e))
         self.sync()
         return None

   # -- wires and connectors ------------------------------------------------------------------------------------------

   def start_wire(self, port: PortItem) -> None:
      """!Starts drawing a wire from a port; ports it cannot end on fade.
      @param port  the port
      @return None
      """
      start = Endpoint(port.owner.element_id, port.spec.name)
      self._begin_drawing(start, port.scenePos(), type_colour(self.system, port.spec.data_type))
      diagram = self.session.diagram()
      for item in self.element_items.values():
         for other in item.ports.values():
            end = Endpoint(item.element_id, other.spec.name)
            source, target = (start, end) if port.spec.side == SIDE_OUT else (end, start)
            fits = other is port or checks.link_problem(self.system, diagram, source, target) is None
            other.setOpacity(1.0 if fits else DIMMED_OPACITY)

   def start_connector(self, item: ElementItem) -> None:
      """!Starts drawing a free connector from an element.
      @param item  the element item
      @return None
      """
      self._begin_drawing(Endpoint(item.element_id), item.sceneBoundingRect().center(), CONNECTOR_COLOUR)

   def _begin_drawing(self, start: Endpoint, at: QtCore.QPointF, colour: QtGui.QColor) -> None:
      """!Adds the temporary path of a link being drawn.
      @param start   where it starts
      @param at      the canvas point it starts from
      @param colour  its colour
      @return None
      """
      path = QtWidgets.QGraphicsPathItem()
      pen = QtGui.QPen(colour, WIRE_WIDTH, QtCore.Qt.PenStyle.DashLine)
      path.setPen(pen)
      path.setZValue(DRAG_Z)
      self.addItem(path)
      self._drawing = (start, path, at)

   def drag_wire(self, pos: QtCore.QPointF) -> None:
      """!Follows the mouse with the link being drawn.
      @param pos  the mouse, canvas coordinates
      @return None
      """
      if self._drawing is None:
         return
      start, path_item, at = self._drawing
      path = QtGui.QPainterPath(at)
      if start.port is not None:
         reach = max(CURVE_REACH, abs(pos.x() - at.x()) * CURVE_SHARE)
         spec = checks.port_spec(self.system, self.session.diagram(), start)
         sign = -1 if spec is not None and spec.side == SIDE_IN else 1
         path.cubicTo(at + QtCore.QPointF(reach * sign, 0), pos - QtCore.QPointF(reach * sign, 0), pos)
      else:
         path.lineTo(pos)
      path_item.setPath(path)

   def end_wire(self, pos: QtCore.QPointF, screen_pos: QtCore.QPoint) -> None:
      """!Ends the link being drawn: on a port (a wire), on an element (a connector), or in empty space (a wire asks
      for a node to add, already wired).
      @param pos         the mouse, canvas coordinates
      @param screen_pos  the mouse, screen coordinates
      @return None
      """
      if self._drawing is None:
         return
      start, path_item, _at = self._drawing
      self._drawing = None
      self.removeItem(path_item)
      for item in self.element_items.values():
         for port in item.ports.values():
            port.setOpacity(1.0)
      hit = [i for i in self.items(pos) if isinstance(i, (PortItem, ElementItem))]
      port = next((i for i in hit if isinstance(i, PortItem)), None)
      element = next((i for i in hit if isinstance(i, ElementItem)), None)
      if start.port is not None:
         if port is not None:
            end = Endpoint(port.owner.element_id, port.spec.name)
            spec = checks.port_spec(self.system, self.session.diagram(), start)
            source, target = (start, end) if spec is not None and spec.side == SIDE_OUT else (end, start)
            if end != start:
               self._run(lambda: self.session.connect(source, target))
         elif element is None:
            self.add_requested.emit(screen_pos, pos, start.text())
         return
      if element is not None and element.element_id != start.element:
         self._run(lambda: self.session.connect(start, Endpoint(element.element_id)))

   # -- palette drops and adding --------------------------------------------------------------------------------------

   def dragEnterEvent(self, event: QtWidgets.QGraphicsSceneDragDropEvent) -> None:
      """!Accepts a palette kind.
      @param event  the event
      @return None
      """
      if event.mimeData().hasFormat(KIND_MIME):
         event.acceptProposedAction()
      else:
         super().dragEnterEvent(event)

   def dragMoveEvent(self, event: QtWidgets.QGraphicsSceneDragDropEvent) -> None:
      """!Keeps accepting a palette kind.
      @param event  the event
      @return None
      """
      if event.mimeData().hasFormat(KIND_MIME):
         event.acceptProposedAction()
      else:
         super().dragMoveEvent(event)

   def dropEvent(self, event: QtWidgets.QGraphicsSceneDragDropEvent) -> None:
      """!Adds the dropped kind where it was dropped.
      @param event  the event
      @return None
      """
      if not event.mimeData().hasFormat(KIND_MIME):
         super().dropEvent(event)
         return
      kind_id = bytes(event.mimeData().data(KIND_MIME).data()).decode("utf-8")
      event.acceptProposedAction()
      self.add_at(kind_id, event.scenePos())

   def add_at(self, kind_id: str, pos: QtCore.QPointF, wire_from: str = "") -> str | None:
      """!Adds an element at a canvas point (snapped), wired to a port when one is given; selects it.
      @param kind_id    the palette kind
      @param pos        where (its top-left corner)
      @param wire_from  "element.port" a wire was dragged from, or ""
      @return the new element's id, or None when refused
      """
      at = (self.snap_length(pos.x()), self.snap_length(pos.y()))
      if wire_from:
         element = self._run(lambda: self.session.add_wired(kind_id, at, Endpoint.parse(wire_from)))
      else:
         element = self._run(lambda: self.session.add(kind_id, at))
      if element is None:
         return None
      self.select_ids([element.element_id])
      return element.element_id

   def mouseDoubleClickEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!On empty canvas: add an element by typing.
      @param event  the event
      @return None
      """
      if not [i for i in self.items(event.scenePos()) if isinstance(i, (ElementItem, LinkItem, PortItem))]:
         self.add_requested.emit(event.screenPos(), event.scenePos(), "")
         event.accept()
         return
      super().mouseDoubleClickEvent(event)

   # -- selection -----------------------------------------------------------------------------------------------------

   def _selection_changed(self) -> None:
      """!Keeps the selection order (newly selected ids go last).
      @return None
      """
      # A lambda stays connected while Qt destroys the scene (removing its items changes the selection then).
      if not shiboken6.isValid(self):
         return
      now = []
      for item in self.selectedItems():
         if isinstance(item, ElementItem):
            now.append(item.element_id)
         elif isinstance(item, LinkItem):
            now.append(item.link_id)
      self._sync_handles()
      kept = [i for i in self.selection_order if i in now]
      self.selection_order = kept + [i for i in now if i not in kept]
      self.picked.emit(list(self.selection_order))

   def _sync_handles(self) -> None:
      """!Shows each element's handles while it is selected (or hovered).
      @return None
      """
      for item in self.element_items.values():
         item.show_handles(item.isSelected() or item.isUnderMouse())

   def selected_elements(self) -> list[str]:
      """!The selected element ids, the first picked first.
      @return ids
      """
      return [i for i in self.selection_order if i in self.element_items]

   def selected_links(self) -> list[str]:
      """!The selected link ids.
      @return ids
      """
      return [i for i in self.selection_order if i in self.link_items]

   def select_ids(self, ids: list[str]) -> None:
      """!Selects elements and links by id (in that order).
      @param ids  ids
      @return None
      """
      self.blockSignals(True)
      self.clearSelection()
      for i in ids:
         item = self.element_items.get(i) or self.link_items.get(i)
         if item is not None:
            item.setSelected(True)
      self.blockSignals(False)
      self.selection_order = [i for i in ids if i in self.element_items or i in self.link_items]
      self._sync_handles()
      self.picked.emit(list(self.selection_order))

   def delete_selection(self) -> None:
      """!Removes the selected elements and links.
      @return None
      """
      ids, links = self.selected_elements(), self.selected_links()
      if ids or links:
         self.selection_order = []
         self._run(lambda: self.session.remove(ids, links))

   def nudge(self, dx: int, dy: int) -> None:
      """!Moves the selection.
      @param dx  right
      @param dy  down
      @return None
      """
      ids = self.selected_elements()
      if ids:
         self._run(lambda: self.session.move(ids, dx, dy))


class DesignerView(QtWidgets.QGraphicsView):
   """!The canvas widget: scrolls (never locked), zooms, pans and selects."""

   ## The zoom changed: percent.
   zoomed = QtCore.Signal(int)

   def __init__(self, scene: DesignerScene, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the view.
      @param scene   the scene
      @param parent  parent widget
      """
      super().__init__(scene, parent)
      self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
      self.setDragMode(QtWidgets.QGraphicsView.DragMode.RubberBandDrag)
      self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
      self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
      self.setViewportUpdateMode(QtWidgets.QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
      self.setAcceptDrops(True)
      self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
      ## Where a middle-button pan started, or None.
      self._pan_from = None
      ## Whether Space is held (Space+drag pans).
      self._space = False

   def designer_scene(self) -> DesignerScene:
      """!The scene, typed.
      @return the scene
      """
      return self.scene()

   # -- zoom ----------------------------------------------------------------------------------------------------------

   def zoom_percent(self) -> int:
      """!The zoom.
      @return percent
      """
      return int(round(self.transform().m11() * PERCENT))

   def set_zoom(self, percent: float) -> None:
      """!Sets the zoom (kept between ZOOM_MIN and ZOOM_MAX).
      @param percent  the zoom
      @return None
      """
      percent = max(ZOOM_MIN, min(ZOOM_MAX, percent))
      factor = percent / PERCENT
      self.setTransform(QtGui.QTransform.fromScale(factor, factor))
      self.zoomed.emit(self.zoom_percent())

   def zoom_by(self, factor: float) -> None:
      """!Zooms in (factor above 1) or out.
      @param factor  the factor
      @return None
      """
      self.set_zoom(self.zoom_percent() * factor)

   def fit(self, ids: list[str] | None = None) -> None:
      """!Zooms to show the whole diagram (or some elements), at most 100%.
      @param ids  element ids, or None for everything
      @return None
      """
      scene = self.designer_scene()
      items = [scene.element_items[i] for i in ids or [] if i in scene.element_items] if ids else \
         list(scene.element_items.values())
      if not items:
         return
      rect = items[0].sceneBoundingRect()
      for item in items[1:]:
         rect = rect.united(item.sceneBoundingRect())
      rect = rect.adjusted(-FIT_MARGIN, -FIT_MARGIN, FIT_MARGIN, FIT_MARGIN)
      self.fitInView(rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
      if self.zoom_percent() > PERCENT:
         self.set_zoom(PERCENT)
      self.centerOn(rect.center())
      self.zoomed.emit(self.zoom_percent())

   def view_state(self) -> dict[str, object]:
      """!The zoom and the centre, as the editor block keeps them.
      @return {"zoom": percent, "centre": [x, y]}
      """
      centre = self.mapToScene(self.viewport().rect().center())
      return {"zoom": self.zoom_percent(), "centre": [int(round(centre.x())), int(round(centre.y()))]}

   def apply_view(self, view: dict[str, object]) -> None:
      """!Restores a view_state() (or fits the diagram when there is none).
      @param view  the view
      @return None
      """
      zoom, centre = view.get("zoom"), view.get("centre")
      if not isinstance(zoom, int) or not isinstance(centre, list) or len(centre) != HALVES:
         self.fit()
         return
      self.set_zoom(zoom)
      self.centerOn(QtCore.QPointF(centre[0], centre[1]))

   # -- mouse and keys ------------------------------------------------------------------------------------------------

   def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
      """!Ctrl+wheel zooms; the wheel alone scrolls as usual.
      @param event  the event
      @return None
      """
      if event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
         notches = event.angleDelta().y() / WHEEL_NOTCH
         if notches:
            self.zoom_by(ZOOM_STEP ** notches)
         event.accept()
         return
      super().wheelEvent(event)

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!The middle button (or Space with the left) starts a pan.
      @param event  the event
      @return None
      """
      panning = event.button() == QtCore.Qt.MouseButton.MiddleButton or (
         self._space and event.button() == QtCore.Qt.MouseButton.LeftButton)
      if panning:
         self._pan_from = event.position()
         self.viewport().setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
         event.accept()
         return
      super().mousePressEvent(event)

   def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Pans by moving the scroll bars.
      @param event  the event
      @return None
      """
      if self._pan_from is not None:
         delta = event.position() - self._pan_from
         self._pan_from = event.position()
         self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
         self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
         event.accept()
         return
      super().mouseMoveEvent(event)

   def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Ends a pan.
      @param event  the event
      @return None
      """
      if self._pan_from is not None:
         self._pan_from = None
         self.viewport().unsetCursor()
         event.accept()
         return
      super().mouseReleaseEvent(event)

   def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
      """!Delete removes the selection; arrows nudge it (by the grid; Shift: by one unit); Space starts panning.
      @param event  the event
      @return None
      """
      key = event.key()
      scene = self.designer_scene()
      keys = QtCore.Qt.Key
      if key in (keys.Key_Delete, keys.Key_Backspace):
         scene.delete_selection()
         event.accept()
         return
      steps = {keys.Key_Left: (-1, 0), keys.Key_Right: (1, 0), keys.Key_Up: (0, -1), keys.Key_Down: (0, 1)}
      if key in steps and scene.selected_elements():
         step = 1 if event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier else layout.GRID
         dx, dy = steps[key]
         scene.nudge(dx * step, dy * step)
         event.accept()
         return
      if key == keys.Key_Space and not event.isAutoRepeat():
         self._space = True
         self.viewport().setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
         event.accept()
         return
      super().keyPressEvent(event)

   def keyReleaseEvent(self, event: QtGui.QKeyEvent) -> None:
      """!Releasing Space ends pan mode.
      @param event  the event
      @return None
      """
      if event.key() == QtCore.Qt.Key.Key_Space and not event.isAutoRepeat():
         self._space = False
         self.viewport().unsetCursor()
         event.accept()
         return
      super().keyReleaseEvent(event)
