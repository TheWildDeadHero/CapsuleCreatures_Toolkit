"""!The edits every designer system shares (D-43 §3), on a Diagram in place. They know nothing of manifests or Qt:
core.designer.session runs each one on the diagram read from the manifest and writes the result back as one
Document step, and both the canvas and `capsule-studio designer` call them through the session.

  add_element, remove, move, place, resize, set_properties   elements
  connect, disconnect, set_label                              wires and connectors
  set_frame, frame_at                                         frames (draw.io containers)
  duplicate                                                   copies, with the wires between the copies
  align, distribute, same_size, to_front, to_back             draw.io's arrange tools

Moving a frame moves what it holds; removing a frame removes what it holds (as draw.io does with containers).
Removing an element removes its links.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .checks import link_problem
from .model import Diagram, Element, Endpoint, Link, ModelError, Point
from .system import SHAPE_KINDS, DesignerSystem

## Smallest width or height an element can be resized to (canvas units).
MIN_SIZE = 20
## Halves a length (centres).
HALVES = 2
## Edges align() lines up.
ALIGN_LEFT = "left"
## Horizontal centres.
ALIGN_CENTRE = "centre"
## Right edges.
ALIGN_RIGHT = "right"
## Top edges.
ALIGN_TOP = "top"
## Vertical centres.
ALIGN_MIDDLE = "middle"
## Bottom edges.
ALIGN_BOTTOM = "bottom"
## Every align() edge.
ALIGN_EDGES = (ALIGN_LEFT, ALIGN_CENTRE, ALIGN_RIGHT, ALIGN_TOP, ALIGN_MIDDLE, ALIGN_BOTTOM)
## distribute() along x.
HORIZONTAL = "horizontal"
## distribute() along y.
VERTICAL = "vertical"
## same_size() of widths.
SAME_WIDTH = "width"
## same_size() of heights.
SAME_HEIGHT = "height"
## same_size() of both.
SAME_BOTH = "both"
## Fewest elements distribute() spaces out (the outer two stay where they are).
DISTRIBUTE_MIN = 3
## Fewest elements align() and same_size() line up (the anchor and one more).
ARRANGE_MIN = 2
## How far a rectangle's width (and height) sit after its x (and y): x, y, width, height.
SIZE_INDEX = 2
## Prefix of a free connector's id.
CONNECTOR_PREFIX = "c"
## A rectangle: x, y, width, height.
Rect = tuple[int, int, int, int]

## Ids of the shared shapes (annotations).
SHARED_SHAPES = frozenset(k.kind_id for k in SHAPE_KINDS)


def bounds(system: DesignerSystem, diagram: Diagram, element_id: str) -> Rect:
   """!An element's rectangle.
   @param system      the system (for the kind's size)
   @param diagram     the diagram
   @param element_id  the element
   @return x, y, width, height
   """
   e = diagram.element(element_id)
   w, h = system.element_size(e)
   return (e.pos[0], e.pos[1], w, h)


def snap(value: int, grid: int) -> int:
   """!A coordinate on the grid (the nearest line).
   @param value  the coordinate
   @param grid   the grid's spacing (0: no grid)
   @return the coordinate
   """
   if grid <= 0:
      return value
   return int(round(value / grid)) * grid


def snap_point(pos: Point, grid: int) -> Point:
   """!A point on the grid.
   @param pos   the point
   @param grid  the grid's spacing (0: no grid)
   @return the point
   """
   return (snap(pos[0], grid), snap(pos[1], grid))


def add_element(system: DesignerSystem, diagram: Diagram, kind_id: str, pos: Point,
                properties: dict[str, Any] | None = None, element_id: str | None = None,
                parent: str | None = None) -> Element:
   """!Adds an element from the palette.
   @param system      the system
   @param diagram     the diagram
   @param kind_id     the palette kind
   @param pos         its top-left corner
   @param properties  inspector values on top of the kind's defaults, or None
   @param element_id  its id, or None for a new one
   @param parent      the frame to put it in, or None
   @return the element
   @throws ModelError when the kind, a value, the id or the frame is wrong
   """
   kind = system.kind(kind_id)
   shared = kind_id in SHARED_SHAPES
   if element_id is None:
      element_id = diagram.new_id(kind_id if shared else system.node_prefix)
   elif element_id in diagram.elements or element_id in diagram.links:
      raise ModelError(f"the id {element_id!r} is taken")
   if not element_id or any(c.isspace() for c in element_id) or "." in element_id:
      raise ModelError(f"{element_id!r} cannot be an id (no spaces or dots)")
   values = kind.defaults()
   for name, value in (properties or {}).items():
      spec = kind.property(name)
      if spec is None:
         raise ModelError(f"{kind.title} has no field {name!r}")
      values[name] = spec.coerce(value)
   # The shared shapes are annotations (kept in the editor block); the system's own kinds are its data.
   element = Element(element_id, kind_id, (int(pos[0]), int(pos[1])), (0, 0), values, None, shared)
   diagram.elements[element_id] = element
   if parent is not None:
      set_frame(system, diagram, [element_id], parent)
   return element


def with_contents(diagram: Diagram, ids: Iterable[str]) -> list[str]:
   """!Elements and everything the frames among them hold, each once, in diagram order.
   @param diagram  the diagram
   @param ids      element ids
   @return ids
   """
   wanted = set()
   for i in ids:
      diagram.element(i)
      wanted.add(i)
      wanted.update(e.element_id for e in diagram.descendants(i))
   return [i for i in diagram.elements if i in wanted]


def remove(diagram: Diagram, ids: Iterable[str], link_ids: Iterable[str] = ()) -> list[str]:
   """!Removes elements (with what frames among them hold, and their links) and links.
   @param diagram   the diagram
   @param ids       element ids
   @param link_ids  link ids
   @return the element ids removed
   """
   gone = with_contents(diagram, ids)
   for k in list(link_ids):
      diagram.link(k)
      del diagram.links[k]
   for i in gone:
      for k in diagram.links_of(i):
         del diagram.links[k.link_id]
      del diagram.elements[i]
   return gone


def move(diagram: Diagram, ids: Iterable[str], dx: int, dy: int) -> None:
   """!Moves elements by an offset, frames with what they hold.
   @param diagram  the diagram
   @param ids      element ids
   @param dx       offset right
   @param dy       offset down
   @return None
   """
   for i in with_contents(diagram, ids):
      e = diagram.elements[i]
      e.pos = (e.pos[0] + int(dx), e.pos[1] + int(dy))


def place(diagram: Diagram, element_id: str, pos: Point) -> None:
   """!Moves an element to a position (a frame with what it holds).
   @param diagram     the diagram
   @param element_id  the element
   @param pos         its new top-left corner
   @return None
   """
   e = diagram.element(element_id)
   move(diagram, [element_id], int(pos[0]) - e.pos[0], int(pos[1]) - e.pos[1])


def resize(diagram: Diagram, element_id: str, size: Point) -> None:
   """!Sets an element's size.
   @param diagram     the diagram
   @param element_id  the element
   @param size        width and height (at least MIN_SIZE each)
   @return None
   @throws ModelError when it is too small
   """
   w, h = int(size[0]), int(size[1])
   if w < MIN_SIZE or h < MIN_SIZE:
      raise ModelError(f"an element is at least {MIN_SIZE} x {MIN_SIZE}")
   diagram.element(element_id).size = (w, h)


def set_properties(system: DesignerSystem, diagram: Diagram, element_id: str, values: dict[str, Any]) -> None:
   """!Sets inspector values (each converted by its field).
   @param system      the system
   @param diagram     the diagram
   @param element_id  the element
   @param values      field name -> value
   @return None
   @throws ModelError when a field or value is wrong (nothing is set then)
   """
   e = diagram.element(element_id)
   kind = system.kind(e.kind)
   new = dict(e.properties)
   for name, value in values.items():
      spec = kind.property(name)
      if spec is None:
         raise ModelError(f"{kind.title} has no field {name!r}")
      new[name] = spec.coerce(value)
   e.properties = new


def connect(system: DesignerSystem, diagram: Diagram, source: Endpoint, target: Endpoint, label: str = "",
            link_id: str | None = None) -> Link:
   """!Wires an output to an input, or (no ports) adds a free connector between two elements.
   @param system   the system
   @param diagram  the diagram
   @param source   where it starts
   @param target   where it ends
   @param label    text on it
   @param link_id  its id, or None for a new one
   @return the link
   @throws ModelError when the link is not allowed (checks.link_problem() says why)
   """
   problem = link_problem(system, diagram, source, target)
   if problem is not None:
      raise ModelError(f"cannot link {source.text()} to {target.text()}: {problem}")
   free = source.port is None
   if link_id is None:
      link_id = diagram.new_id(CONNECTOR_PREFIX if free else system.link_prefix)
   elif link_id in diagram.links or link_id in diagram.elements:
      raise ModelError(f"the id {link_id!r} is taken")
   # A free connector is an annotation; so is any link touching one (a note pointing at a node).
   touches_annotation = any(diagram.elements[end.element].annotation for end in (source, target))
   link = Link(link_id, source, target, label, free or touches_annotation)
   diagram.links[link_id] = link
   return link


def disconnect(diagram: Diagram, link_ids: Iterable[str]) -> None:
   """!Removes links.
   @param diagram   the diagram
   @param link_ids  their ids
   @return None
   """
   remove(diagram, (), link_ids)


def set_label(diagram: Diagram, link_id: str, label: str) -> None:
   """!Sets the text on a link.
   @param diagram  the diagram
   @param link_id  the link
   @param label    the text
   @return None
   """
   diagram.link(link_id).label = label


def set_frame(system: DesignerSystem, diagram: Diagram, ids: Iterable[str], frame_id: str | None) -> None:
   """!Puts elements into a frame, or (None) takes them out of theirs.
   @param system    the system
   @param diagram   the diagram
   @param ids       element ids
   @param frame_id  the frame, or None
   @return None
   @throws ModelError when it is not a frame, or would hold itself
   """
   targets = list(ids)
   if frame_id is not None:
      frame = diagram.element(frame_id)
      if not system.kind(frame.kind).container:
         raise ModelError(f"{frame_id} is not a frame")
      for i in targets:
         if i == frame_id or frame_id in {e.element_id for e in diagram.descendants(i)}:
            raise ModelError(f"{frame_id} cannot hold {i}: it is inside it")
   for i in targets:
      diagram.element(i).parent = frame_id


def _inside(inner: Rect, outer: Rect) -> bool:
   """!Whether one rectangle lies wholly inside another.
   @param inner  x, y, w, h
   @param outer  x, y, w, h
   @return True when inside
   """
   ix, iy, iw, ih = inner
   ox, oy, ow, oh = outer
   return ix >= ox and iy >= oy and ix + iw <= ox + ow and iy + ih <= oy + oh


def frame_at(system: DesignerSystem, diagram: Diagram, element_id: str) -> str | None:
   """!The innermost frame an element lies wholly inside (the canvas puts a dropped element there).
   @param system      the system
   @param diagram     the diagram
   @param element_id  the element
   @return the frame's id, or None
   """
   rect = bounds(system, diagram, element_id)
   held = {e.element_id for e in diagram.descendants(element_id)}
   best: tuple[int, str] | None = None
   for e in diagram.elements.values():
      if e.element_id == element_id or e.element_id in held or not system.kind(e.kind).container:
         continue
      outer = bounds(system, diagram, e.element_id)
      if _inside(rect, outer):
         _ox, _oy, ow, oh = outer
         area = ow * oh
         if best is None or area < best[0]:
            best = (area, e.element_id)
   return best[1] if best is not None else None


def duplicate(system: DesignerSystem, diagram: Diagram, ids: Sequence[str], offset: Point) -> dict[str, str]:
   """!Copies elements (with what frames among them hold), and the links between the copies (as Node-RED copies a
   selection's wires).
   @param system   the system
   @param diagram  the diagram
   @param ids      element ids
   @param offset   how far the copies sit from the originals
   @return original id -> copy id
   """
   originals = with_contents(diagram, ids)
   copies: dict[str, str] = {}
   for i in originals:
      e = diagram.elements[i]
      new = add_element(system, diagram, e.kind, (e.pos[0] + offset[0], e.pos[1] + offset[1]), None)
      new.properties = dict(e.properties)
      new.size = e.size
      copies[i] = new.element_id
   for i in originals:
      parent = diagram.elements[i].parent
      diagram.elements[copies[i]].parent = copies.get(parent, parent)
   for k in list(diagram.links.values()):
      if k.source.element in copies and k.target.element in copies:
         connect(system, diagram, Endpoint(copies[k.source.element], k.source.port),
                 Endpoint(copies[k.target.element], k.target.port), k.label)
   return copies


def align(system: DesignerSystem, diagram: Diagram, ids: Sequence[str], edge: str) -> None:
   """!Lines elements up on the first one's edge or centre (draw.io's Align).
   @param system   the system
   @param diagram  the diagram
   @param ids      element ids, the anchor first
   @param edge     one of ALIGN_EDGES
   @return None
   @throws ModelError for another edge
   """
   if edge not in ALIGN_EDGES:
      raise ModelError(f"align to one of {', '.join(ALIGN_EDGES)}, not {edge!r}")
   if len(ids) < ARRANGE_MIN:
      return
   ax, ay, aw, ah = bounds(system, diagram, ids[0])
   for i in ids[1:]:
      x, y, w, h = bounds(system, diagram, i)
      target = {ALIGN_LEFT: (ax, y), ALIGN_RIGHT: (ax + aw - w, y), ALIGN_CENTRE: (ax + (aw - w) // HALVES, y),
                ALIGN_TOP: (x, ay), ALIGN_BOTTOM: (x, ay + ah - h), ALIGN_MIDDLE: (x, ay + (ah - h) // HALVES)}[edge]
      place(diagram, i, target)


def distribute(system: DesignerSystem, diagram: Diagram, ids: Sequence[str], axis: str) -> None:
   """!Spaces elements evenly between the outermost two (draw.io's Distribute): equal gaps between them.
   @param system   the system
   @param diagram  the diagram
   @param ids      element ids (at least DISTRIBUTE_MIN)
   @param axis     HORIZONTAL or VERTICAL
   @return None
   @throws ModelError for another axis
   """
   if axis not in (HORIZONTAL, VERTICAL):
      raise ModelError(f"distribute {HORIZONTAL} or {VERTICAL}, not {axis!r}")
   if len(ids) < DISTRIBUTE_MIN:
      return
   along = 0 if axis == HORIZONTAL else 1
   rects = sorted((bounds(system, diagram, i) for i in ids), key=lambda r: r[along])
   order = sorted(ids, key=lambda i: bounds(system, diagram, i)[along])
   start = rects[0][along]
   end = rects[-1][along] + rects[-1][along + SIZE_INDEX]
   lengths = [r[along + SIZE_INDEX] for r in rects]
   gap = (end - start - sum(lengths)) // (len(rects) - 1)
   cursor = start
   for i, length in zip(order, lengths):
      x, y = diagram.element(i).pos
      place(diagram, i, (cursor, y) if axis == HORIZONTAL else (x, cursor))
      cursor += length + gap


def same_size(system: DesignerSystem, diagram: Diagram, ids: Sequence[str], which: str) -> None:
   """!Gives elements the first one's width, height or both.
   @param system   the system
   @param diagram  the diagram
   @param ids      element ids, the anchor first
   @param which    SAME_WIDTH, SAME_HEIGHT or SAME_BOTH
   @return None
   @throws ModelError for anything else
   """
   if which not in (SAME_WIDTH, SAME_HEIGHT, SAME_BOTH):
      raise ModelError(f"same {SAME_WIDTH}, {SAME_HEIGHT} or {SAME_BOTH}, not {which!r}")
   if len(ids) < ARRANGE_MIN:
      return
   _x, _y, aw, ah = bounds(system, diagram, ids[0])
   for i in ids[1:]:
      _x, _y, w, h = bounds(system, diagram, i)
      resize(diagram, i, (aw if which != SAME_HEIGHT else w, ah if which != SAME_WIDTH else h))


def _reorder(diagram: Diagram, ids: Iterable[str], front: bool) -> None:
   """!Moves elements to the end (front) or the start (back) of the drawing order.
   @param diagram  the diagram
   @param ids      element ids
   @param front    True for the front
   @return None
   """
   chosen = set(with_contents(diagram, ids))
   picked = [(i, e) for i, e in diagram.elements.items() if i in chosen]
   rest = [(i, e) for i, e in diagram.elements.items() if i not in chosen]
   diagram.elements = dict(rest + picked if front else picked + rest)


def to_front(diagram: Diagram, ids: Iterable[str]) -> None:
   """!Draws elements over the others (with what frames among them hold).
   @param diagram  the diagram
   @param ids      element ids
   @return None
   """
   _reorder(diagram, ids, True)


def to_back(diagram: Diagram, ids: Iterable[str]) -> None:
   """!Draws elements under the others.
   @param diagram  the diagram
   @param ids      element ids
   @return None
   """
   _reorder(diagram, ids, False)
