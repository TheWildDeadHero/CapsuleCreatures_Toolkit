"""!A designer system on one manifest (D-43 §2): DesignSession.

The session never keeps a diagram of its own. diagram() reads the manifest (cached until the Document changes),
and each edit runs an ops function on a fresh copy and writes the result back inside one Document.edit(), so:
  - each edit is one undo step, with the label the canvas's Undo shows;
  - an edit that fails changes nothing (the Document puts the manifest back);
  - undo, redo and edits from elsewhere (another panel, a grouped step) show at once, since the diagram is read from
    the manifest again.

The canvas and `capsule-studio designer` both call the methods below, which is the command-line parity of D-43 §6.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, TypeVar

from .. import manifest_io
from ..document import Document
from . import checks, layout, ops, registry
from .model import SEVERITY_ERROR, SIDE_OUT, Diagnostic, Diagram, Element, Endpoint, Link, ModelError, Point
from .system import DesignerSystem

## An edit's result type.
Result = TypeVar("Result")
## Most ids an undo label names before it counts them instead.
LABEL_IDS = 3


def _named(ids: Sequence[str], noun: str) -> str:
   """!Elements in an undo label: their ids when there are few, else how many.
   @param ids   the ids
   @param noun  what they are, singular ("element")
   @return text
   """
   if len(ids) <= LABEL_IDS:
      return ", ".join(ids)
   return f"{len(ids)} {noun}s"


class DesignSession:
   """!One manifest, edited through its designer system."""

   def __init__(self, system: DesignerSystem, doc: Document) -> None:
      """!Binds a system to a Document of its schema.
      @param system  the system
      @param doc     the Document
      @throws ModelError when the schemas differ
      """
      if doc.schema != system.schema:
         raise ModelError(f"{system.title} edits {system.schema}, not {doc.schema}")
      ## The system.
      self.system = system
      ## The manifest.
      self.doc = doc
      ## The diagram read at _cache_revision.
      self._cache = None
      ## The Document revision _cache was read at.
      self._cache_revision = None
      ## The problems found at _problems_revision.
      self._problems = None
      ## The Document revision _problems were found at.
      self._problems_revision = None

   # -- files -------------------------------------------------------------------------------------------------------

   @classmethod
   def open(cls, path: str | Path, system_id: str | None = None) -> DesignSession:
      """!Opens a manifest: its system comes from its schema, or is named.
      @param path       the manifest
      @param system_id  the system, or None to find it from the schema
      @return the session
      @throws ModelError when no system edits it; OSError / ValueError when it cannot be read
      """
      data = manifest_io.load(path)
      schema = data.get("schema") if isinstance(data, dict) else None
      system = registry.get(system_id) if system_id else registry.for_schema(str(schema))
      return cls(system, Document(data, path, system.schema))

   @classmethod
   def new(cls, system_id: str, path: str | Path | None = None) -> DesignSession:
      """!A new manifest of a system (not saved until save()).
      @param system_id  the system
      @param path       where it will be saved, or None
      @return the session
      """
      system = registry.get(system_id)
      return cls(system, Document(None, path, system.schema))

   def save(self, path: str | Path | None = None, view: dict[str, Any] | None = None) -> None:
      """!Writes the manifest.
      @param path  a new file ("save as"), or None for its own
      @param view  the canvas's view to keep in the editor block, or None to leave it; the view is no undo step
      @return None
      """
      if view is not None and self.system.annotations:
         diagram = self.diagram().copy()
         if diagram.view != view:
            diagram.view = dict(view)
            # The view rides along with the save: it is not an edit, so it makes no undo step.
            self.system.save(diagram, self.doc.data)
      self.doc.save(path)

   # -- reading -----------------------------------------------------------------------------------------------------

   def diagram(self) -> Diagram:
      """!The manifest's diagram (read again after every change; do not change it: edit through the session).
      @return the diagram
      @throws ModelError when the manifest cannot be shown
      """
      if self._cache is None or self._cache_revision != self.doc.revision:
         self._cache = self.system.load(self.doc.data)
         self._cache_revision = self.doc.revision
      return self._cache

   def diagnostics(self) -> list[Diagnostic]:
      """!Every check's problems (found again only after a change).
      @return problems
      """
      if self._problems is not None and self._problems_revision == self.doc.revision:
         return self._problems
      try:
         diagram = self.diagram()
      except ModelError as e:
         return [Diagnostic(SEVERITY_ERROR, str(e))]
      self._problems = checks.check(self.system, diagram)
      self._problems_revision = self.doc.revision
      return self._problems

   def live_values(self) -> dict[str, str]:
      """!The system's live values on nodes.
      @return element id -> text
      """
      return self.system.live_values(self.diagram())

   # -- editing -----------------------------------------------------------------------------------------------------

   def edit(self, label: str, change: Callable[[Diagram], Result]) -> Result:
      """!Runs a change on a copy of the diagram and writes it back as one undo step.
      @param label   the undo label
      @param change  takes the diagram, changes it in place, and returns anything
      @return what change returned
      @throws ModelError (or what change raises) with nothing changed
      """
      diagram = self.diagram().copy()
      result = change(diagram)
      with self.doc.edit(label) as data:
         self.system.save(diagram, data)
      return result

   def add(self, kind_id: str, pos: Point, properties: dict[str, Any] | None = None,
           element_id: str | None = None, parent: str | None = None) -> Element:
      """!Adds an element from the palette (into the frame it is dropped in, when parent is None and one holds it).
      @param kind_id     the palette kind
      @param pos         its top-left corner
      @param properties  inspector values, or None
      @param element_id  its id, or None for a new one
      @param parent      the frame, or None to find the one it lies in
      @return the element
      """
      title = self.system.kind(kind_id).title

      def change(d: Diagram) -> Element:
         """!The edit.
         @param d  the diagram
         @return the element
         """
         e = ops.add_element(self.system, d, kind_id, pos, properties, element_id, parent)
         if parent is None:
            ops.set_frame(self.system, d, [e.element_id], ops.frame_at(self.system, d, e.element_id))
         if self.system.kind(kind_id).container:
            # A frame dropped over elements takes in those wholly inside it (and in no smaller frame).
            for other in list(d.elements):
               if other != e.element_id and ops.frame_at(self.system, d, other) == e.element_id:
                  ops.set_frame(self.system, d, [other], e.element_id)
         return e

      return self.edit(f"Add {title}", change)

   def add_wired(self, kind_id: str, pos: Point, wire_from: Endpoint, port: str | None = None) -> Element:
      """!Adds a node already wired to a port (Node-RED: a wire dropped in empty space).
      @param kind_id    the palette kind
      @param pos        its top-left corner
      @param wire_from  the port the wire was dragged from (an output feeds the new node's input; an input is fed
                        by its output)
      @param port       the new node's port to wire, or None for its first compatible one
      @return the element
      @throws ModelError when the kind has no fitting port
      """
      title = self.system.kind(kind_id).title

      def change(d: Diagram) -> Element:
         """!The edit.
         @param d  the diagram
         @return the element
         """
         e = ops.add_element(self.system, d, kind_id, pos)
         self._wire_new(d, e, wire_from, port)
         return e

      return self.edit(f"Add {title}", change)

   def _wire_new(self, d: Diagram, e: Element, wire_from: Endpoint, port: str | None) -> None:
      """!Wires a new node to the port a wire was dragged from.
      @param d          the diagram
      @param e          the new node
      @param wire_from  the port
      @param port       the new node's port, or None for the first that fits
      @return None
      @throws ModelError when none fits
      """
      from_spec = checks.port_spec(self.system, d, wire_from)
      if from_spec is None:
         raise ModelError(f"there is no port {wire_from.text()!r}")
      kind = self.system.kind(e.kind)
      forward = from_spec.side == SIDE_OUT
      candidates = kind.inputs() if forward else kind.outputs()
      for spec in candidates:
         if port is not None and spec.name != port:
            continue
         mine = Endpoint(e.element_id, spec.name)
         source, target = (wire_from, mine) if forward else (mine, wire_from)
         if checks.link_problem(self.system, d, source, target) is None:
            ops.connect(self.system, d, source, target)
            return
      raise ModelError(f"{kind.title} has no port that fits {wire_from.text()}")

   def fitting_kinds(self, wire_from: Endpoint) -> list[str]:
      """!The palette kinds a wire dragged from a port could end on (the add-by-typing list, filtered).
      @param wire_from  the port
      @return kind ids
      """
      out = []
      for kind in self.system.node_kinds():
         probe = self.diagram().copy()
         try:
            e = ops.add_element(self.system, probe, kind.kind_id, (0, 0))
            self._wire_new(probe, e, wire_from, None)
         except ModelError:
            continue
         out.append(kind.kind_id)
      return out

   def remove(self, ids: Iterable[str], link_ids: Iterable[str] = ()) -> list[str]:
      """!Removes elements (frames with what they hold, with their links) and links.
      @param ids       element ids
      @param link_ids  link ids
      @return the element ids removed
      """
      ids, link_ids = list(ids), list(link_ids)
      what = _named(ids, "element") if ids else _named(link_ids, "link")
      return self.edit(f"Remove {what}", lambda d: ops.remove(d, ids, link_ids))

   def move(self, ids: Iterable[str], dx: int, dy: int) -> None:
      """!Moves elements by an offset; each lands in the frame it then lies in.
      @param ids  element ids
      @param dx   offset right
      @param dy   offset down
      @return None
      """
      ids = list(ids)

      def change(d: Diagram) -> None:
         """!The edit.
         @param d  the diagram
         @return None
         """
         ops.move(d, ids, dx, dy)
         self._refit_frames(d, ids)

      self.edit(f"Move {_named(ids, 'element')}", change)

   def _refit_frames(self, d: Diagram, ids: Sequence[str]) -> None:
      """!Puts moved elements into the frame they now lie in (or none), as draw.io does on a drop.
      @param d    the diagram
      @param ids  the elements moved (their contents move with them and keep their frame)
      @return None
      """
      moved = set(ids)
      for i in ids:
         e = d.elements[i]
         if e.parent in moved:
            continue   # it moved with its frame
         ops.set_frame(self.system, d, [i], ops.frame_at(self.system, d, i))

   def place(self, element_id: str, pos: Point) -> None:
      """!Moves an element to a position.
      @param element_id  the element
      @param pos         its top-left corner
      @return None
      """
      e = self.diagram().element(element_id)
      self.move([element_id], pos[0] - e.pos[0], pos[1] - e.pos[1])

   def resize(self, element_id: str, size: Point) -> None:
      """!Sets an element's size.
      @param element_id  the element
      @param size        width and height
      @return None
      """
      self.edit(f"Resize {element_id}", lambda d: ops.resize(d, element_id, size))

   def set_properties(self, element_id: str, values: dict[str, Any]) -> None:
      """!Sets inspector values.
      @param element_id  the element
      @param values      field -> value
      @return None
      """
      names = ", ".join(values)
      self.edit(f"Set {names} of {element_id}", lambda d: ops.set_properties(self.system, d, element_id, values))

   def connect(self, source: Endpoint, target: Endpoint, label: str = "") -> Link:
      """!Wires two ports, or connects two elements with a free connector.
      @param source  where it starts
      @param target  where it ends
      @param label   its text
      @return the link
      """
      return self.edit(f"Connect {source.text()} to {target.text()}",
                       lambda d: ops.connect(self.system, d, source, target, label))

   def disconnect(self, link_ids: Iterable[str]) -> None:
      """!Removes links.
      @param link_ids  their ids
      @return None
      """
      link_ids = list(link_ids)
      self.edit(f"Disconnect {_named(link_ids, 'link')}", lambda d: ops.disconnect(d, link_ids))

   def set_label(self, link_id: str, label: str) -> None:
      """!Sets a link's text.
      @param link_id  the link
      @param label    the text
      @return None
      """
      self.edit(f"Label {link_id}", lambda d: ops.set_label(d, link_id, label))

   def set_frame(self, ids: Iterable[str], frame_id: str | None) -> None:
      """!Puts elements into a frame, or takes them out.
      @param ids       element ids
      @param frame_id  the frame, or None
      @return None
      """
      ids = list(ids)
      label = f"Put {_named(ids, 'element')} in {frame_id}" if frame_id else f"Take {_named(ids, 'element')} out"
      self.edit(label, lambda d: ops.set_frame(self.system, d, ids, frame_id))

   def duplicate(self, ids: Sequence[str], offset: Point) -> dict[str, str]:
      """!Copies elements and the wires between them.
      @param ids     element ids
      @param offset  how far the copies sit from the originals
      @return original id -> copy id
      """
      return self.edit(f"Duplicate {_named(list(ids), 'element')}",
                       lambda d: ops.duplicate(self.system, d, ids, offset))

   def paste(self, clip: dict[str, Any], pos: Point) -> dict[str, str]:
      """!Adds copied elements and the links between them (copy() made clip), the first one's corner at pos.
      @param clip  elements and links as Diagram.to_json() writes them
      @param pos   where the copies' top-left corner goes
      @return clip id -> new id
      """
      source = Diagram.from_json(clip)

      def change(d: Diagram) -> dict[str, str]:
         """!The edit.
         @param d  the diagram
         @return clip id -> new id
         """
         if not source.elements:
            return {}
         left = min(e.pos[0] for e in source.elements.values())
         top = min(e.pos[1] for e in source.elements.values())
         new_ids: dict[str, str] = {}
         for e in source.elements.values():
            made = ops.add_element(self.system, d, e.kind, (e.pos[0] - left + pos[0], e.pos[1] - top + pos[1]))
            made.properties = dict(e.properties)
            made.size = e.size
            new_ids[e.element_id] = made.element_id
         for e in source.elements.values():
            if e.parent in new_ids:
               d.elements[new_ids[e.element_id]].parent = new_ids[e.parent]
         for k in source.links.values():
            if k.source.element in new_ids and k.target.element in new_ids:
               ops.connect(self.system, d, Endpoint(new_ids[k.source.element], k.source.port),
                           Endpoint(new_ids[k.target.element], k.target.port), k.label)
         return new_ids

      return self.edit(f"Paste {_named(list(source.elements), 'element')}", change)

   def copy(self, ids: Iterable[str]) -> dict[str, Any]:
      """!What copy puts on the clipboard: elements (frames with what they hold) and the links between them.
      @param ids  element ids
      @return Diagram.to_json() of the copied part
      """
      d = self.diagram()
      chosen = set(ops.with_contents(d, ids))
      part = Diagram({i: e for i, e in d.elements.items() if i in chosen},
                     {k.link_id: k for k in d.links.values()
                      if k.source.element in chosen and k.target.element in chosen})
      return part.copy().to_json()

   def align(self, ids: Sequence[str], edge: str) -> None:
      """!Lines elements up on the first one.
      @param ids   element ids, the anchor first
      @param edge  one of ops.ALIGN_EDGES
      @return None
      """
      self.edit(f"Align {edge}", lambda d: ops.align(self.system, d, ids, edge))

   def distribute(self, ids: Sequence[str], axis: str) -> None:
      """!Spaces elements evenly.
      @param ids   element ids
      @param axis  ops.HORIZONTAL or ops.VERTICAL
      @return None
      """
      self.edit(f"Distribute {axis}ly", lambda d: ops.distribute(self.system, d, ids, axis))

   def same_size(self, ids: Sequence[str], which: str) -> None:
      """!Gives elements the first one's size.
      @param ids    element ids, the anchor first
      @param which  ops.SAME_WIDTH, SAME_HEIGHT or SAME_BOTH
      @return None
      """
      self.edit(f"Same {which}", lambda d: ops.same_size(self.system, d, ids, which))

   def to_front(self, ids: Iterable[str]) -> None:
      """!Draws elements over the others.
      @param ids  element ids
      @return None
      """
      ids = list(ids)
      self.edit("Bring to front", lambda d: ops.to_front(d, ids))

   def to_back(self, ids: Iterable[str]) -> None:
      """!Draws elements under the others.
      @param ids  element ids
      @return None
      """
      ids = list(ids)
      self.edit("Send to back", lambda d: ops.to_back(d, ids))

   def auto_layout(self) -> list[str]:
      """!Lays the system's nodes out in ranks (layout.auto_layout()).
      @return the ids placed
      """
      return self.edit("Tidy up", lambda d: layout.auto_layout(self.system, d))

