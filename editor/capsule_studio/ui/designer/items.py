"""!What the manifest designer's canvas draws (D-43 §5).

  ElementItem      one element: a node (Node-RED style: a coloured title bar, its main setting, its live value,
                   ports with their names) or a shape (rectangle, rounded box, ellipse, diamond, note, text, frame;
                   draw.io style)
  PortItem         a node's port; dragging from it draws a wire
  ConnectorHandle  the small arrow under an element; dragging it to another element draws a free connector
  ResizeHandle     the corner of a shape; dragging it resizes the shape
  LinkItem         a wire (a curve from an output to an input, coloured by data type) or a connector (a straight
                   arrow between two elements), with its label

Items only draw and report what the mouse does: the scene (canvas.py) turns drags into session edits.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.designer import system as dsystem
from ...core.designer.model import ANY_TYPE, ROLE_SHAPE, SIDE_IN, Element, ElementKind, Link, PortSpec

if TYPE_CHECKING:
   from .canvas import DesignerScene

## Height of a node's title bar (canvas units).
TITLE_HEIGHT = 24
## Height of a node's line under the title (its main setting and live value).
INFO_HEIGHT = 16
## Height of one port row.
PORT_ROW = 24
## Radius of a port's circle.
PORT_RADIUS = 6
## Corner radius of nodes and rounded boxes.
CORNER = 8
## Size of a note's folded corner.
NOTE_FOLD = 14
## Height of a frame's title strip.
FRAME_TITLE = 24
## Inner margin of text in an element.
TEXT_MARGIN = 6
## Side of the resize handle.
HANDLE_SIZE = 10
## Radius of the connector handle.
CONNECTOR_RADIUS = 7
## Width of an element's outline, and twice it when selected.
OUTLINE = 1.0
## Width of an outline when selected or showing a problem.
OUTLINE_STRONG = 2.5
## Width of a wire.
WIRE_WIDTH = 2.5
## Length of a connector's arrowhead.
ARROW_LENGTH = 10
## Half the angle of a connector's arrowhead, radians.
ARROW_HALF_ANGLE = math.pi / 7
## How far a wire's curve handles reach out of its ports, at least.
CURVE_REACH = 60
## Share of a wire's horizontal distance its curve handles reach.
CURVE_SHARE = 0.5
## Halves a length.
HALVES = 2
## How much darker an element's outline is than its fill, percent (QColor.darker()).
OUTLINE_DARKER = 160
## How much lighter a node's body is than its title bar, percent (QColor.lighter()).
BODY_LIGHTER = 160
## How much a hovered port grows.
PORT_HOVER_SCALE = 1.5
## How much darker a frame's title strip is than its fill, percent (QColor.darker()).
FRAME_TITLE_DARKER = 115
## Opacity of ports a wire being drawn cannot end on.
DIMMED_OPACITY = 0.25

## Colour of outlines when selected.
SELECTED_COLOUR = QtGui.QColor("#ff7f0e")
## Colour of outlines with a problem.
PROBLEM_COLOUR = QtGui.QColor("#d62728")
## Colour of a node's text.
TEXT_COLOUR = QtGui.QColor("#202020")
## Colour of a live value.
VALUE_COLOUR = QtGui.QColor("#1f5fa8")
## Colour of free connectors.
CONNECTOR_COLOUR = QtGui.QColor("#606060")
## Colours given to data types, in the order the system's ports first use them.
TYPE_COLOURS = ("#4c78a8", "#e45756", "#54a24b", "#b279a2", "#f58518", "#72b7b2", "#9d755d", "#eeca3b")
## Colour of the "any" type.
ANY_COLOUR = "#7f7f7f"

## Data type -> colour, filled by type_colour().
_TYPE_COLOUR_CACHE: dict[tuple[str, str], QtGui.QColor] = {}


def type_colour(system: dsystem.DesignerSystem, data_type: str) -> QtGui.QColor:
   """!The colour of a data type's wires and ports (stable per system).
   @param system     the system
   @param data_type  the type
   @return the colour
   """
   key = (system.system_id, data_type)
   cached = _TYPE_COLOUR_CACHE.get(key)
   if cached is not None:
      return cached
   types: list[str] = []
   for kind in system.node_kinds():
      for port in kind.ports:
         if port.data_type not in types and port.data_type != ANY_TYPE:
            types.append(port.data_type)
   colour = QtGui.QColor(TYPE_COLOURS[types.index(data_type) % len(TYPE_COLOURS)] if data_type in types
                         else ANY_COLOUR)
   _TYPE_COLOUR_CACHE[key] = colour
   return colour


class PortItem(QtWidgets.QGraphicsEllipseItem):
   """!A node's port (a child of its ElementItem); press and drag to draw a wire."""

   def __init__(self, owner: ElementItem, spec: PortSpec, centre: QtCore.QPointF, colour: QtGui.QColor) -> None:
      """!Creates the port.
      @param owner   its element
      @param spec    the port
      @param centre  its centre, in the element's coordinates
      @param colour  its data type's colour
      """
      r = PORT_RADIUS
      super().__init__(-r, -r, r * HALVES, r * HALVES, owner)
      ## The element.
      self.owner = owner
      ## The port.
      self.spec = spec
      self.setPos(centre)
      self.setBrush(QtGui.QBrush(colour))
      self.setPen(QtGui.QPen(colour.darker(OUTLINE_DARKER), OUTLINE))
      self.setAcceptHoverEvents(True)
      self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
      self.setToolTip(f"{spec.label()}: {spec.data_type}" + (" (needs a wire)" if spec.required else ""))

   def endpoint_text(self) -> str:
      """!"element.port".
      @return text
      """
      return f"{self.owner.element_id}.{self.spec.name}"

   def hoverEnterEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
      """!Grows while hovered.
      @param event  the event
      @return None
      """
      self.setScale(PORT_HOVER_SCALE)
      super().hoverEnterEvent(event)

   def hoverLeaveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
      """!Back to its size.
      @param event  the event
      @return None
      """
      self.setScale(1.0)
      super().hoverLeaveEvent(event)

   def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Starts a wire.
      @param event  the event
      @return None
      """
      if event.button() == QtCore.Qt.MouseButton.LeftButton:
         self.owner.designer_scene().start_wire(self)
         event.accept()
         return
      super().mousePressEvent(event)

   def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Drags the wire.
      @param event  the event
      @return None
      """
      self.owner.designer_scene().drag_wire(event.scenePos())

   def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Ends the wire on a port, or in empty space (add a wired node).
      @param event  the event
      @return None
      """
      self.owner.designer_scene().end_wire(event.scenePos(), event.screenPos())


class ConnectorHandle(QtWidgets.QGraphicsEllipseItem):
   """!The arrow under an element's bottom edge (shown while hovered or selected); drag it to another element to draw a
   free connector, as draw.io's hover arrows do."""

   def __init__(self, owner: ElementItem) -> None:
      """!Creates the handle.
      @param owner  its element
      """
      r = CONNECTOR_RADIUS
      super().__init__(-r, -r, r * HALVES, r * HALVES, owner)
      ## The element.
      self.owner = owner
      self.setBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
      self.setPen(QtGui.QPen(CONNECTOR_COLOUR, OUTLINE))
      self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
      self.setToolTip("Drag to another element to connect them")
      self.setVisible(False)

   def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem,
             widget: QtWidgets.QWidget | None = None) -> None:
      """!A circle with an arrow in it.
      @param painter  the painter
      @param option   style options
      @param widget   the widget, or None
      @return None
      """
      super().paint(painter, option, widget)
      r = CONNECTOR_RADIUS / HALVES
      painter.drawLine(QtCore.QPointF(-r, 0), QtCore.QPointF(r, 0))
      painter.drawLine(QtCore.QPointF(0, -r), QtCore.QPointF(r, 0))
      painter.drawLine(QtCore.QPointF(0, r), QtCore.QPointF(r, 0))

   def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Starts a connector.
      @param event  the event
      @return None
      """
      self.owner.designer_scene().start_connector(self.owner)
      event.accept()

   def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Drags it.
      @param event  the event
      @return None
      """
      self.owner.designer_scene().drag_wire(event.scenePos())

   def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Ends it on an element.
      @param event  the event
      @return None
      """
      self.owner.designer_scene().end_wire(event.scenePos(), event.screenPos())


class ResizeHandle(QtWidgets.QGraphicsRectItem):
   """!A shape's bottom-right corner (shown while selected); drag it to resize the shape."""

   def __init__(self, owner: ElementItem) -> None:
      """!Creates the handle.
      @param owner  its element
      """
      super().__init__(0, 0, HANDLE_SIZE, HANDLE_SIZE, owner)
      ## The element.
      self.owner = owner
      ## Where the drag started (scene) and the size then, or None.
      self._start = None
      self.setBrush(QtGui.QBrush(SELECTED_COLOUR))
      self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
      self.setCursor(QtCore.Qt.CursorShape.SizeFDiagCursor)
      self.setToolTip("Drag to resize")
      self.setVisible(False)

   def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Starts resizing.
      @param event  the event
      @return None
      """
      self._start = (event.scenePos(), self.owner.size)
      event.accept()

   def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Resizes the element on the canvas (snapped to the grid).
      @param event  the event
      @return None
      """
      if self._start is None:
         return
      origin, (w, h) = self._start
      delta = event.scenePos() - origin
      scene = self.owner.designer_scene()
      self.owner.set_size(scene.snap_length(w + delta.x()), scene.snap_length(h + delta.y()))

   def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Writes the new size.
      @param event  the event
      @return None
      """
      if self._start is not None:
         self._start = None
         self.owner.designer_scene().resized(self.owner)


class ElementItem(QtWidgets.QGraphicsRectItem):
   """!One element on the canvas."""

   def __init__(self, scene: DesignerScene, element: Element, kind: ElementKind) -> None:
      """!Creates the item (scene.sync() updates it afterwards).
      @param scene    the scene
      @param element  the element
      @param kind     its kind
      """
      super().__init__()
      ## The element's id.
      self.element_id = element.element_id
      ## Its kind.
      self.kind = kind
      ## Its size (canvas units).
      self.size = scene.system.element_size(element)
      ## The element as last synced.
      self.element = element
      ## The line under a node's title.
      self.info = ""
      ## Its live value, or "".
      self.value = ""
      ## Whether a problem names it.
      self.problem = False
      ## Ports by name.
      self.ports = {}
      flags = QtWidgets.QGraphicsItem.GraphicsItemFlag
      self.setFlag(flags.ItemIsMovable, True)
      self.setFlag(flags.ItemIsSelectable, True)
      # The item draws itself (paint()); its rectangle is only its extent, with room for a strong outline.
      self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
      self.setBrush(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
      self._fit_rect()
      self.setAcceptHoverEvents(True)
      self.setToolTip(f"{kind.title} ({element.element_id})" + (f"\n{kind.help}" if kind.help else ""))
      ## The connector handle, or None when the system has no free connectors.
      self.connector = ConnectorHandle(self) if scene.system.annotations else None
      ## The resize handle (shapes only), or None.
      self.resizer = ResizeHandle(self) if kind.role == ROLE_SHAPE else None
      self._build_ports(scene)
      self._place_handles()

   def designer_scene(self) -> DesignerScene:
      """!The scene, typed.
      @return the scene
      """
      return self.scene()

   def _build_ports(self, scene: DesignerScene) -> None:
      """!Creates the port items along the sides.
      @param scene  the scene
      @return None
      """
      for port in self.ports.values():
         port.setParentItem(None)
         scene.removeItem(port)
      self.ports = {}
      vertical = scene.system.direction == dsystem.TOP_TO_BOTTOM
      for side_ports, entering in ((self.kind.inputs(), True), (self.kind.outputs(), False)):
         for n, spec in enumerate(side_ports):
            self.ports[spec.name] = PortItem(self, spec, self.port_position(spec, n, len(side_ports), vertical,
                                                                            entering),
                                             type_colour(scene.system, spec.data_type))

   def port_position(self, spec: PortSpec, index: int, count: int, vertical: bool, entering: bool) -> QtCore.QPointF:
      """!Where a port sits: down the left (inputs) or right (outputs) edge, one row each below the title; along
      the top and bottom edges on a top-to-bottom diagram.
      @param spec      the port
      @param index     its place on its side
      @param count     ports on its side
      @param vertical  whether the diagram runs top to bottom
      @param entering  whether it is an input
      @return its centre
      """
      w, h = self.size
      if vertical:
         x = w * (index + 1) / (count + 1)
         return QtCore.QPointF(x, 0 if entering else h)
      y = TITLE_HEIGHT + INFO_HEIGHT + PORT_ROW * index + PORT_ROW / HALVES
      return QtCore.QPointF(0 if entering else w, min(y, h - PORT_RADIUS))

   def _place_handles(self) -> None:
      """!Puts the handles on the right edge and the bottom-right corner.
      @return None
      """
      w, h = self.size
      if self.connector is not None:
         # Under the middle of the bottom edge: clear of the ports on the sides (and of a top-to-bottom diagram's
         # ports, which sit on the edge itself).
         self.connector.setPos(w / HALVES, h + CONNECTOR_RADIUS * HALVES)
      if self.resizer is not None:
         self.resizer.setPos(w - HANDLE_SIZE / HALVES, h - HANDLE_SIZE / HALVES)

   def set_size(self, w: float, h: float) -> None:
      """!Resizes it on the canvas (the scene writes the size when the drag ends).
      @param w  width
      @param h  height
      @return None
      """
      from ...core.designer.ops import MIN_SIZE
      size = (max(int(w), MIN_SIZE), max(int(h), MIN_SIZE))
      if size == self.size:
         return
      self.size = size
      self._fit_rect()
      self._place_handles()
      self.designer_scene().element_geometry_changed(self)

   def update_from(self, scene: DesignerScene, element: Element, info: str, value: str, problem: bool) -> None:
      """!Takes up a synced element.
      @param scene    the scene
      @param element  the element
      @param info     its main setting
      @param value    its live value, or ""
      @param problem  whether a problem names it
      @return None
      """
      size = scene.system.element_size(element)
      if size != self.size:
         self.size = size
         self._fit_rect()
         self._build_ports(scene)
         self._place_handles()
      self.element = element
      self.info, self.value, self.problem = info, value, problem
      self.setPos(element.pos[0], element.pos[1])
      self.update()

   def port_scene_pos(self, name: str) -> QtCore.QPointF:
      """!Where a port is on the canvas.
      @param name  the port
      @return its centre (the element's centre when it has no such port)
      """
      port = self.ports.get(name)
      if port is None:
         return self.sceneBoundingRect().center()
      return port.scenePos()

   def text(self) -> str:
      """!A shape's text.
      @return text
      """
      return str(self.element.properties.get("text", ""))

   def fill(self) -> QtGui.QColor:
      """!The fill colour: a shape's own, else its kind's colour.
      @return colour
      """
      fill = self.element.properties.get("fill")
      return QtGui.QColor(fill if isinstance(fill, str) and fill else self.kind.colour)

   def _fit_rect(self) -> None:
      """!Sets the item's extent: the element's box, with room for its outline.
      @return None
      """
      w, h = self.size
      pad = OUTLINE_STRONG
      self.setRect(QtCore.QRectF(-pad, -pad, w + pad * HALVES, h + pad * HALVES))

   def box(self) -> QtCore.QRectF:
      """!The element's box on the canvas (without the outline's room).
      @return the rectangle
      """
      return QtCore.QRectF(self.pos(), QtCore.QSizeF(self.size[0], self.size[1]))

   def shape(self) -> QtGui.QPainterPath:
      """!What the mouse hits: the box (a frame only by its title strip and border, so what is inside stays
      clickable).
      @return the path
      """
      w, h = self.size
      path = QtGui.QPainterPath()
      if self.kind.container:
         outer = QtGui.QPainterPath()
         outer.addRect(QtCore.QRectF(0, 0, w, h))
         inner = QtGui.QPainterPath()
         inner.addRect(QtCore.QRectF(TEXT_MARGIN, FRAME_TITLE, w - TEXT_MARGIN * HALVES,
                                     h - FRAME_TITLE - TEXT_MARGIN))
         return outer.subtracted(inner)
      path.addRect(QtCore.QRectF(0, 0, w, h))
      return path

   def _outline(self) -> QtGui.QPen:
      """!The outline pen: selected, a problem, or the fill's darker shade.
      @return the pen
      """
      if self.isSelected():
         return QtGui.QPen(SELECTED_COLOUR, OUTLINE_STRONG)
      if self.problem:
         return QtGui.QPen(PROBLEM_COLOUR, OUTLINE_STRONG)
      return QtGui.QPen(self.fill().darker(OUTLINE_DARKER), OUTLINE)

   def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem,
             widget: QtWidgets.QWidget | None = None) -> None:
      """!Draws a node or a shape.
      @param painter  the painter
      @param option   style options
      @param widget   the widget, or None
      @return None
      """
      painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
      if self.kind.role == ROLE_SHAPE:
         self._paint_shape(painter)
      else:
         self._paint_node(painter)

   def _paint_node(self, painter: QtGui.QPainter) -> None:
      """!A node: title bar in its category's colour, then its setting and live value, then its ports' names.
      @param painter  the painter
      @return None
      """
      w, h = self.size
      rect = QtCore.QRectF(0, 0, w, h)
      colour = QtGui.QColor(self.kind.colour)
      painter.setPen(self._outline())
      painter.setBrush(QtGui.QBrush(colour.lighter(BODY_LIGHTER)))
      painter.drawRoundedRect(rect, CORNER, CORNER)
      title = QtGui.QPainterPath()
      title.addRoundedRect(QtCore.QRectF(0, 0, w, TITLE_HEIGHT + CORNER), CORNER, CORNER)
      clip = QtGui.QPainterPath()
      clip.addRect(QtCore.QRectF(0, 0, w, TITLE_HEIGHT))
      painter.fillPath(title.intersected(clip), QtGui.QBrush(colour))
      painter.setPen(TEXT_COLOUR)
      font = painter.font()
      font.setBold(True)
      painter.setFont(font)
      painter.drawText(QtCore.QRectF(TEXT_MARGIN, 0, w - TEXT_MARGIN * HALVES, TITLE_HEIGHT),
                       QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft, self.kind.title)
      font.setBold(False)
      painter.setFont(font)
      info_rect = QtCore.QRectF(TEXT_MARGIN, TITLE_HEIGHT, w - TEXT_MARGIN * HALVES, INFO_HEIGHT)
      painter.drawText(info_rect, QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
                       self.info)
      if self.value:
         painter.setPen(VALUE_COLOUR)
         painter.drawText(info_rect, QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight,
                          f"= {self.value}")
      painter.setPen(TEXT_COLOUR)
      for port in self.ports.values():
         p = port.pos()
         room = QtCore.QRectF(PORT_RADIUS * HALVES, p.y() - PORT_ROW / HALVES, w / HALVES - PORT_RADIUS * HALVES,
                              PORT_ROW)
         if port.spec.side == SIDE_IN:
            painter.drawText(room, QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft,
                             port.spec.label())
         else:
            room.moveRight(w - PORT_RADIUS * HALVES)
            painter.drawText(room, QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight,
                             port.spec.label())

   def _paint_shape(self, painter: QtGui.QPainter) -> None:
      """!A shape, with its text in the middle (a frame's at the top).
      @param painter  the painter
      @return None
      """
      w, h = self.size
      rect = QtCore.QRectF(0, 0, w, h)
      shape = self.kind.shape
      painter.setPen(self._outline() if shape != dsystem.SHAPE_TEXT or self.isSelected()
                     else QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
      painter.setBrush(QtGui.QBrush(self.fill()) if shape != dsystem.SHAPE_TEXT
                       else QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
      text_rect = rect.adjusted(TEXT_MARGIN, TEXT_MARGIN, -TEXT_MARGIN, -TEXT_MARGIN)
      align = QtCore.Qt.AlignmentFlag.AlignCenter
      if shape == dsystem.SHAPE_ROUNDED:
         painter.drawRoundedRect(rect, CORNER, CORNER)
      elif shape == dsystem.SHAPE_ELLIPSE:
         painter.drawEllipse(rect)
      elif shape == dsystem.SHAPE_DIAMOND:
         painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(w / HALVES, 0), QtCore.QPointF(w, h / HALVES),
                                              QtCore.QPointF(w / HALVES, h), QtCore.QPointF(0, h / HALVES)]))
      elif shape == dsystem.SHAPE_NOTE:
         painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(0, 0), QtCore.QPointF(w - NOTE_FOLD, 0),
                                              QtCore.QPointF(w, NOTE_FOLD), QtCore.QPointF(w, h),
                                              QtCore.QPointF(0, h)]))
         painter.drawLine(QtCore.QPointF(w - NOTE_FOLD, 0), QtCore.QPointF(w - NOTE_FOLD, NOTE_FOLD))
         painter.drawLine(QtCore.QPointF(w - NOTE_FOLD, NOTE_FOLD), QtCore.QPointF(w, NOTE_FOLD))
         align = QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop
      elif shape == dsystem.SHAPE_FRAME:
         painter.drawRoundedRect(rect, CORNER, CORNER)
         painter.fillRect(QtCore.QRectF(0, 0, w, FRAME_TITLE).adjusted(OUTLINE, OUTLINE, -OUTLINE, 0),
                          QtGui.QBrush(self.fill().darker(FRAME_TITLE_DARKER)))
         text_rect = QtCore.QRectF(TEXT_MARGIN, 0, w - TEXT_MARGIN * HALVES, FRAME_TITLE)
         align = QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft
      elif shape != dsystem.SHAPE_TEXT:
         painter.drawRect(rect)
      painter.setPen(TEXT_COLOUR)
      painter.drawText(text_rect, align | QtCore.Qt.TextFlag.TextWordWrap, self.text())

   def hoverEnterEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
      """!Shows the connector handle.
      @param event  the event
      @return None
      """
      self.show_handles(True)
      super().hoverEnterEvent(event)

   def hoverLeaveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
      """!Hides the handles unless selected.
      @param event  the event
      @return None
      """
      self.show_handles(self.isSelected())
      super().hoverLeaveEvent(event)

   def show_handles(self, on: bool) -> None:
      """!Shows or hides the handles.
      @param on  whether they show
      @return None
      """
      if self.connector is not None:
         self.connector.setVisible(on)
      if self.resizer is not None:
         self.resizer.setVisible(on and self.isSelected())

   def mouseDoubleClickEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Opens the element's first field in the inspector.
      @param event  the event
      @return None
      """
      self.designer_scene().edit_requested.emit(self.element_id)
      event.accept()


class LinkItem(QtWidgets.QGraphicsPathItem):
   """!A wire or a connector, with its label on a small plate at its middle."""

   def __init__(self, link: Link, colour: QtGui.QColor) -> None:
      """!Creates the item (scene.route() lays its path).
      @param link    the link
      @param colour  its colour
      """
      super().__init__()
      ## The link's id.
      self.link_id = link.link_id
      ## The link as last synced.
      self.link = link
      ## Its colour.
      self.colour = colour
      ## Whether a problem names it.
      self.problem = False
      ## Arrowhead of a connector, or None.
      self.arrow = None
      ## The label's plate (hidden without a label).
      self.plate = QtWidgets.QGraphicsRectItem(self)
      self.plate.setBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
      ## The label's text.
      self.label_text = QtWidgets.QGraphicsSimpleTextItem(self.plate)
      self.label_text.setBrush(QtGui.QBrush(TEXT_COLOUR))
      self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
      self.setAcceptHoverEvents(True)
      self.set_state(link, False)

   def current_colour(self) -> QtGui.QColor:
      """!Its colour now: selected, a problem, or its own.
      @return the colour
      """
      return SELECTED_COLOUR if self.isSelected() else PROBLEM_COLOUR if self.problem else self.colour

   def set_state(self, link: Link, problem: bool) -> None:
      """!Takes up a synced link.
      @param link     the link
      @param problem  whether a problem names it
      @return None
      """
      self.link, self.problem = link, problem
      self.setToolTip(f"{link.source.text()} -> {link.target.text()}" + (f"\n{link.label}" if link.label else ""))
      pen = QtGui.QPen(self.colour, WIRE_WIDTH)
      if link.annotation:
         pen.setStyle(QtCore.Qt.PenStyle.DashLine)
      pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
      self.setPen(pen)
      self.label_text.setText(link.label)
      self.plate.setVisible(bool(link.label))
      self._place_label()
      self.update()

   def _place_label(self) -> None:
      """!Centres the label's plate on the middle of the path.
      @return None
      """
      text = self.label_text.boundingRect()
      w, h = text.width() + TEXT_MARGIN * HALVES, text.height() + TEXT_MARGIN
      self.plate.setRect(QtCore.QRectF(0, 0, w, h))
      self.plate.setPos(self.middle_point() - QtCore.QPointF(w / HALVES, h / HALVES))
      self.label_text.setPos(TEXT_MARGIN, TEXT_MARGIN / HALVES)

   def middle_point(self) -> QtCore.QPointF:
      """!The middle of the path.
      @return the point
      """
      path = self.path()
      return path.pointAtPercent(CURVE_SHARE) if not path.isEmpty() else QtCore.QPointF()

   def route(self, start: QtCore.QPointF, end: QtCore.QPointF, curved: bool, vertical: bool) -> None:
      """!Lays the path: a curve leaving and entering along the flow (a wire), or a straight arrow (a connector).
      @param start     where it starts
      @param end       where it ends
      @param curved    True for a wire
      @param vertical  whether the flow runs top to bottom
      @return None
      """
      path = QtGui.QPainterPath(start)
      self.arrow = None
      if curved:
         reach = max(CURVE_REACH, abs((end.y() - start.y()) if vertical else (end.x() - start.x())) * CURVE_SHARE)
         if vertical:
            path.cubicTo(start + QtCore.QPointF(0, reach), end - QtCore.QPointF(0, reach), end)
         else:
            path.cubicTo(start + QtCore.QPointF(reach, 0), end - QtCore.QPointF(reach, 0), end)
      else:
         path.lineTo(end)
         angle = math.atan2(end.y() - start.y(), end.x() - start.x())
         left = end - QtCore.QPointF(ARROW_LENGTH * math.cos(angle - ARROW_HALF_ANGLE),
                                     ARROW_LENGTH * math.sin(angle - ARROW_HALF_ANGLE))
         right = end - QtCore.QPointF(ARROW_LENGTH * math.cos(angle + ARROW_HALF_ANGLE),
                                      ARROW_LENGTH * math.sin(angle + ARROW_HALF_ANGLE))
         self.arrow = QtGui.QPolygonF([end, left, right])
      self.setPath(path)
      self._place_label()

   def shape(self) -> QtGui.QPainterPath:
      """!What the mouse hits: a band along the path, and the arrowhead.
      @return the path
      """
      stroker = QtGui.QPainterPathStroker()
      stroker.setWidth(WIRE_WIDTH * HALVES * HALVES)
      band = stroker.createStroke(self.path())
      if self.arrow is not None:
         band.addPolygon(self.arrow)
      return band

   def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem,
             widget: QtWidgets.QWidget | None = None) -> None:
      """!The path in its current colour, and a connector's filled arrowhead.
      @param painter  the painter
      @param option   style options
      @param widget   the widget, or None
      @return None
      """
      painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
      pen = QtGui.QPen(self.pen())
      colour = self.current_colour()
      pen.setColor(colour)
      painter.setPen(pen)
      painter.setBrush(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
      painter.drawPath(self.path())
      if self.arrow is not None:
         painter.setPen(QtGui.QPen(colour, OUTLINE))
         painter.setBrush(QtGui.QBrush(colour))
         painter.drawPolygon(self.arrow)
      if self.plate.pen().color() != colour:
         self.plate.setPen(QtGui.QPen(colour, OUTLINE))

   def mouseDoubleClickEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
      """!Opens the label in the inspector.
      @param event  the event
      @return None
      """
      scene = self.scene()
      if scene is not None:
         scene.edit_requested.emit(self.link_id)
      event.accept()
