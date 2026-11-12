"""!Sample flow: the manifest designer's dev-only system (D-43 §7, milestone 1), on invented data.

Whole numbers flow from Number nodes through Add, Subtract, Multiply, Compare and Choose into Show nodes, and every
node shows its value live, so it exercises everything a real system uses: a palette by category, typed ports
(number, yes/no), required inputs, one-wire inputs, no loops, inspector fields of each type, a system check, live
values, and the shared notes and frames. It is not engine data and nothing compiles it.

    {"schema": "capsule.sampleflow/1", "id": "sample",
     "nodes": {"n1": {"kind": "number", "pos": [0, 0], "value": 3},
               "n2": {"kind": "number", "pos": [0, 120], "value": 4},
               "n3": {"kind": "add", "pos": [240, 40]},
               "n4": {"kind": "show", "pos": [480, 40], "label": "Total", "editor": {"frame": "frame1"}}},
     "wires": [{"from": "n1.value", "to": "n3.a"}, {"from": "n2.value", "to": "n3.b"},
               {"from": "n3.result", "to": "n4.value", "label": "sum"}],
     "editor": {"designer": {"shapes": [...], "connectors": [...], "view": {...}}}}

Nodes keep their position and their fields inline (as D-18's AI graphs will); a node's frame (a shared shape) is
editor-only, so it goes in the node's own "editor" block. Wires are numbered in file order (w1, w2, ...).
"""
from __future__ import annotations

import copy
from typing import Any

from .model import (SEVERITY_WARNING, SIDE_IN, SIDE_OUT, VALUE_CHOICE, VALUE_INTEGER, VALUE_TEXT, Diagnostic,
                    Diagram, Element, ElementKind, Endpoint, Link, ModelError, PortSpec, PropertySpec, point)
from .system import EDITOR_KEY, DesignerSystem

## The manifest's schema.
SCHEMA = "capsule.sampleflow/1"
## A whole number.
NUMBER = "number"
## Yes or no.
BOOLEAN = "boolean"
## Width of every node.
NODE_WIDTH = 160
## Height of a node's title bar.
HEADER_HEIGHT = 40
## Height each port row adds.
PORT_ROW = 24
## Largest number a Number node holds (the flow is whole numbers in 32 bits).
VALUE_LIMIT = 2 ** 31 - 1
## Compare's tests, as written on the node.
TESTS = ("<", "<=", "=", ">=", ">")
## Key of a node's frame in its editor block.
FRAME_KEY = "frame"
## Prefix of a wire's id (wires are numbered in file order).
WIRE_PREFIX = "w"


def _size(ports: tuple[PortSpec, ...]) -> tuple[int, int]:
   """!A node's size: room for its title and its longer side of ports.
   @param ports  its ports
   @return width and height
   """
   rows = max(sum(1 for p in ports if p.side == SIDE_IN), sum(1 for p in ports if p.side == SIDE_OUT), 1)
   return (NODE_WIDTH, HEADER_HEIGHT + rows * PORT_ROW)


def _kind(kind_id: str, title: str, category: str, colour: str, ports: tuple[PortSpec, ...],
          properties: tuple[PropertySpec, ...] = (), help_text: str = "") -> ElementKind:
   """!A Sample flow node kind.
   @param kind_id     id
   @param title       title
   @param category    palette category
   @param colour      header colour
   @param ports       ports
   @param properties  inspector fields
   @param help_text   palette tooltip
   @return the kind
   """
   return ElementKind(kind_id, title, category=category, colour=colour, ports=ports, properties=properties,
                      size=_size(ports), help=help_text)


def _in(name: str, data_type: str = NUMBER) -> PortSpec:
   """!A required input that takes one wire.
   @param name       its name
   @param data_type  its type
   @return the port
   """
   return PortSpec(name, SIDE_IN, data_type, required=True)


def _out(name: str, data_type: str = NUMBER) -> PortSpec:
   """!An output that feeds any number of wires.
   @param name       its name
   @param data_type  its type
   @return the port
   """
   return PortSpec(name, SIDE_OUT, data_type, many=True)


## The palette.
KINDS = (
   _kind("number", "Number", "Inputs", "#a6bbcf", (_out("value"),),
         (PropertySpec("value", "Value", VALUE_INTEGER, 0, minimum=-VALUE_LIMIT, maximum=VALUE_LIMIT),),
         "A whole number"),
   _kind("add", "Add", "Maths", "#e2d96e", (_in("a"), _in("b"), _out("result")), help_text="a + b"),
   _kind("subtract", "Subtract", "Maths", "#e2d96e", (_in("a"), _in("b"), _out("result")), help_text="a - b"),
   _kind("multiply", "Multiply", "Maths", "#e2d96e", (_in("a"), _in("b"), _out("result")), help_text="a x b"),
   _kind("compare", "Compare", "Logic", "#fdd0a2", (_in("a"), _in("b"), _out("result", BOOLEAN)),
         (PropertySpec("test", "Test", VALUE_CHOICE, "<", TESTS),), "Whether a and b pass the test"),
   _kind("choose", "Choose", "Logic", "#fdd0a2", (_in("when", BOOLEAN), _in("yes"), _in("no"), _out("result")),
         help_text="yes when the condition holds, else no"),
   _kind("show", "Show", "Outputs", "#87a980", (_in("value"),),
         (PropertySpec("label", "Label", VALUE_TEXT, "Result"),), "Shows the value that reaches it"),
)
## The fields a node entry holds besides its properties.
ENTRY_KEYS = ("kind", "pos", "size", EDITOR_KEY)


class SampleFlowSystem(DesignerSystem):
   """!Numbers flowing through maths and logic nodes (see the module's notes)."""

   ## Id.
   system_id = "sample-flow"
   ## Title.
   title = "Sample flow"
   ## The manifest schema.
   schema = SCHEMA
   ## What it is for.
   description = "Whole numbers through maths and logic nodes, with live values (for developing the designer)"
   ## Only for developing the designer.
   dev_only = True

   def node_kinds(self) -> tuple[ElementKind, ...]:
      """!The palette.
      @return KINDS
      """
      return KINDS

   def empty(self) -> dict[str, Any]:
      """!A new flow: nothing in it.
      @return the manifest
      """
      return {"schema": SCHEMA, "id": "untitled", "nodes": {}, "wires": []}

   def read(self, data: dict[str, Any]) -> Diagram:
      """!The nodes and wires of a flow.
      @param data  the manifest
      @return the diagram
      @throws ModelError when an entry is malformed
      """
      diagram = Diagram()
      nodes = data.get("nodes", {})
      if not isinstance(nodes, dict):
         raise ModelError("nodes must be an object of node id -> node")
      for node_id, entry in nodes.items():
         if not isinstance(entry, dict) or "kind" not in entry:
            raise ModelError(f"node {node_id!r} needs a kind")
         properties = {k: copy.deepcopy(v) for k, v in entry.items() if k not in ENTRY_KEYS}
         editor = entry.get(EDITOR_KEY, {})
         frame = editor.get(FRAME_KEY) if isinstance(editor, dict) else None
         diagram.elements[node_id] = Element(node_id, str(entry["kind"]), point(entry.get("pos", [0, 0])),
                                             point(entry.get("size", [0, 0])), properties, frame)
      wires = data.get("wires", [])
      if not isinstance(wires, list):
         raise ModelError("wires must be a list")
      for n, wire in enumerate(wires, 1):
         if not isinstance(wire, dict) or "from" not in wire or "to" not in wire:
            raise ModelError(f"wire {n} needs a from and a to")
         link_id = f"{WIRE_PREFIX}{n}"
         diagram.links[link_id] = Link(link_id, Endpoint.parse(str(wire["from"])), Endpoint.parse(str(wire["to"])),
                                       str(wire.get("label", "")))
      return diagram

   def write(self, diagram: Diagram, data: dict[str, Any]) -> None:
      """!Writes the nodes and wires back (unknown keys of a node entry stay).
      @param diagram  the diagram
      @param data     the manifest
      @return None
      """
      old = data.get("nodes", {}) if isinstance(data.get("nodes"), dict) else {}
      nodes: dict[str, Any] = {}
      for e in diagram.elements.values():
         if e.annotation:
            continue
         known = set(self.kind(e.kind).defaults()) if e.kind in {k.kind_id for k in KINDS} else set()
         previous = old.get(e.element_id, {})
         entry = {k: v for k, v in previous.items() if k not in ENTRY_KEYS and k not in known}
         entry.update({"kind": e.kind, "pos": [e.pos[0], e.pos[1]]})
         if e.size != (0, 0):
            entry["size"] = [e.size[0], e.size[1]]
         entry.update(copy.deepcopy(e.properties))
         editor = dict(previous.get(EDITOR_KEY, {})) if isinstance(previous.get(EDITOR_KEY), dict) else {}
         editor.pop(FRAME_KEY, None)
         if e.parent is not None:
            editor[FRAME_KEY] = e.parent
         if editor:
            entry[EDITOR_KEY] = editor
         nodes[e.element_id] = entry
      data["nodes"] = nodes
      wires = []
      for k in diagram.links.values():
         if k.annotation:
            continue
         wire: dict[str, Any] = {"from": k.source.text(), "to": k.target.text()}
         if k.label:
            wire["label"] = k.label
         wires.append(wire)
      data["wires"] = wires

   def compatible(self, source_type: str, target_type: str) -> bool:
      """!Numbers feed numbers and yes/no feeds yes/no (no free "any" ports in a flow).
      @param source_type  the output's type
      @param target_type  the input's type
      @return True when they connect
      """
      return source_type == target_type

   def check(self, diagram: Diagram) -> list[Diagnostic]:
      """!A flow with nodes but no Show shows nothing.
      @param diagram  the diagram
      @return problems
      """
      nodes = [e for e in diagram.elements.values() if not e.annotation]
      if nodes and not any(e.kind == "show" for e in nodes):
         return [Diagnostic(SEVERITY_WARNING, "nothing is shown: add a Show node")]
      return []

   def node_text(self, element: Element) -> str:
      """!A node's main setting (a Number's value shows as its live value already).
      @param element  the node
      @return text
      """
      props = element.properties
      if element.kind == "compare":
         return f"a {props.get('test', '<')} b"
      if element.kind == "show":
         return str(props.get("label", ""))
      return ""

   def evaluate(self, diagram: Diagram) -> dict[str, int | bool]:
      """!Every node's value, in wire order (a node whose inputs are not all known has none).
      @param diagram  the diagram
      @return node id -> value
      """
      feeds: dict[tuple[str, str], str] = {}
      for k in diagram.links.values():
         if not k.annotation and k.target.port is not None:
            feeds[(k.target.element, k.target.port)] = k.source.element
      values: dict[str, int | bool] = {}
      nodes = [e for e in diagram.elements.values() if not e.annotation]
      # Repeat until nothing new is known: a loop (refused by the checks) simply never gets a value.
      changed = True
      while changed:
         changed = False
         for e in nodes:
            if e.element_id in values:
               continue
            value = self._value(e, feeds, values)
            if value is not None:
               values[e.element_id] = value
               changed = True
      return values

   def _value(self, e: Element, feeds: dict[tuple[str, str], str],
              values: dict[str, int | bool]) -> int | bool | None:
      """!One node's value from its inputs' values.
      @param e       the node
      @param feeds   (node, input) -> the node wired into it
      @param values  the values known so far
      @return the value, or None while an input is unknown
      """
      if e.kind == "number":
         return int(e.properties.get("value", 0))
      try:
         kind = self.kind(e.kind)
      except ModelError:
         return None
      inputs = {}
      for port in kind.inputs():
         source = feeds.get((e.element_id, port.name))
         if source is None or source not in values:
            return None
         inputs[port.name] = values[source]
      if e.kind == "add":
         return int(inputs["a"]) + int(inputs["b"])
      if e.kind == "subtract":
         return int(inputs["a"]) - int(inputs["b"])
      if e.kind == "multiply":
         return int(inputs["a"]) * int(inputs["b"])
      if e.kind == "compare":
         a, b = int(inputs["a"]), int(inputs["b"])
         return {"<": a < b, "<=": a <= b, "=": a == b, ">=": a >= b, ">": a > b}[e.properties.get("test", "<")]
      if e.kind == "choose":
         return inputs["yes"] if inputs["when"] else inputs["no"]
      if e.kind == "show":
         return inputs["value"]
      return None

   def live_values(self, diagram: Diagram) -> dict[str, str]:
      """!Each node's value as text ("yes" / "no" for a condition).
      @param diagram  the diagram
      @return node id -> text
      """
      out = {}
      for node_id, value in self.evaluate(diagram).items():
         out[node_id] = ("yes" if value else "no") if isinstance(value, bool) else str(value)
      return out
