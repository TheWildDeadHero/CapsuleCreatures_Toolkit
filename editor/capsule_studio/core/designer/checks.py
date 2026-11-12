"""!The checks every designer system gets (D-43 §3), then the system's own (DesignerSystem.check()).

  - every element's kind exists, and every link's ends exist;
  - a wire runs from an output port to an input port of compatible data types (DesignerSystem.compatible());
  - an input that takes one link has at most one;
  - a required input is connected;
  - links of the system's data form no cycle, unless the system allows cycles (DesignerSystem.allow_cycles);
  - a frame's elements exist, and frames do not hold themselves.

Annotations (shapes and free connectors) are checked only for existing ends: they carry no data.
"""
from __future__ import annotations

from .model import (SEVERITY_ERROR, SIDE_IN, SIDE_OUT, Diagnostic, Diagram, Endpoint, Link, ModelError, PortSpec)
from .system import DesignerSystem


def port_spec(system: DesignerSystem, diagram: Diagram, endpoint: Endpoint) -> PortSpec | None:
   """!The port an endpoint names.
   @param system    the system
   @param diagram   the diagram
   @param endpoint  the endpoint (port None: no port)
   @return the port, or None when the endpoint names none or it does not exist
   """
   element = diagram.elements.get(endpoint.element)
   if element is None or endpoint.port is None:
      return None
   try:
      return system.kind(element.kind).port(endpoint.port)
   except ModelError:
      return None


class LinkIndex:
   """!The links at each endpoint and between each pair of endpoints, so check() looks each link up once instead
   of scanning every link for every link."""

   def __init__(self, diagram: Diagram) -> None:
      """!Indexes a diagram's links.
      @param diagram  the diagram
      """
      ## Endpoint -> ids of the links ending there.
      self.at = {}
      ## (source, target) -> ids of the links between them.
      self.pairs = {}
      for k in diagram.links.values():
         self.at.setdefault(k.target, []).append(k.link_id)
         self.pairs.setdefault((k.source, k.target), []).append(k.link_id)


def link_problem(system: DesignerSystem, diagram: Diagram, source: Endpoint, target: Endpoint,
                 ignore: str | None = None, index: LinkIndex | None = None) -> str | None:
   """!Why a wire or connector between two endpoints is not allowed (the canvas asks while dragging, ops.connect()
   before connecting).
   @param system   the system
   @param diagram  the diagram
   @param source   where it starts
   @param target   where it ends
   @param ignore   a link to leave out of the count of a port's links (the one being checked), or None
   @param index    the diagram's LinkIndex, or None to scan the links
   @return the reason, or None when it is allowed
   """
   for end in (source, target):
      if end.element not in diagram.elements:
         return f"there is no element {end.element!r}"
   if source.element == target.element:
      return "an element cannot link to itself"
   if source.port is None and target.port is None:
      if not system.annotations:
         return f"{system.title} has no free connectors"
      return None
   if source.port is None or target.port is None:
      return "a wire runs from a port to a port"
   out_port = port_spec(system, diagram, source)
   in_port = port_spec(system, diagram, target)
   if out_port is None or in_port is None:
      missing = source if out_port is None else target
      return f"there is no port {missing.text()!r}"
   if out_port.side != SIDE_OUT or in_port.side != SIDE_IN:
      return "a wire runs from an output to an input"
   if not system.compatible(out_port.data_type, in_port.data_type):
      return f"{out_port.data_type} does not fit {in_port.data_type}"
   if index is not None:
      others = [k for k in index.at.get(target, []) if k != ignore]
      twins = [k for k in index.pairs.get((source, target), []) if k != ignore]
   else:
      others = [k.link_id for k in diagram.links.values() if k.target == target and k.link_id != ignore]
      twins = [k.link_id for k in diagram.links.values()
               if k.source == source and k.target == target and k.link_id != ignore]
   if not in_port.many and others:
      return f"{target.text()} takes one wire"
   if twins:
      return "they are wired already"
   return None


def _cycle(diagram: Diagram, links: list[Link]) -> list[str] | None:
   """!A cycle through the system's links, if there is one.
   @param diagram  the diagram
   @param links    the links that count
   @return the elements around the cycle, or None
   """
   after: dict[str, list[str]] = {e: [] for e in diagram.elements}
   for k in links:
      after.setdefault(k.source.element, []).append(k.target.element)
   # Depth-first search with colours: on the path (grey) or done (black); a grey target closes a cycle.
   grey, black = set(), set()
   for start in after:
      if start in black:
         continue
      path = [start]
      stack = [iter(after[start])]
      grey.add(start)
      while stack:
         nxt = next(stack[-1], None)
         if nxt is None:
            done = path.pop()
            grey.discard(done)
            black.add(done)
            stack.pop()
         elif nxt in grey:
            return path[path.index(nxt):]
         elif nxt not in black:
            grey.add(nxt)
            path.append(nxt)
            stack.append(iter(after.get(nxt, [])))
   return None


def check(system: DesignerSystem, diagram: Diagram) -> list[Diagnostic]:
   """!Every check: the shared ones, then the system's.
   @param system   the system
   @param diagram  the diagram
   @return problems, in a stable order
   """
   out: list[Diagnostic] = []
   kinds = {k.kind_id: k for k in system.kinds()}
   for e in diagram.elements.values():
      if e.kind not in kinds:
         out.append(Diagnostic(SEVERITY_ERROR, f"{e.element_id}: {system.title} has no {e.kind!r}",
                               (e.element_id,)))
      if e.parent is not None:
         frame = diagram.elements.get(e.parent)
         frame_kind = kinds.get(frame.kind) if frame is not None else None
         # A frame inside the element itself would hold it in a loop.
         inside = {f.element_id for f in diagram.descendants(e.element_id)}
         if frame_kind is None or not frame_kind.container or e.parent == e.element_id or e.parent in inside:
            out.append(Diagnostic(SEVERITY_ERROR, f"{e.element_id}: its frame {e.parent!r} cannot hold it",
                                  (e.element_id,)))
   data_links = []
   index = LinkIndex(diagram)
   for k in diagram.links.values():
      problem = link_problem(system, diagram, k.source, k.target, ignore=k.link_id, index=index)
      if problem is not None:
         out.append(Diagnostic(SEVERITY_ERROR, f"{k.source.text()} -> {k.target.text()}: {problem}",
                               tuple(e for e in (k.source.element, k.target.element) if e in diagram.elements),
                               (k.link_id,)))
      if not k.annotation:
         data_links.append(k)
   for e in diagram.elements.values():
      kind = kinds.get(e.kind)
      if kind is None or e.annotation:
         continue
      for port in kind.inputs():
         if port.required and not index.at.get(Endpoint(e.element_id, port.name)):
            out.append(Diagnostic(SEVERITY_ERROR, f"{e.element_id}: {port.label()} needs a wire", (e.element_id,)))
   if not system.allow_cycles:
      loop = _cycle(diagram, data_links)
      if loop is not None:
         out.append(Diagnostic(SEVERITY_ERROR, "the wires form a loop: " + " -> ".join(loop + loop[:1]),
                               tuple(loop)))
   return out + system.check(diagram)


def errors(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
   """!Only the errors.
   @param diagnostics  problems
   @return those with SEVERITY_ERROR
   """
   return [d for d in diagnostics if d.severity == SEVERITY_ERROR]
