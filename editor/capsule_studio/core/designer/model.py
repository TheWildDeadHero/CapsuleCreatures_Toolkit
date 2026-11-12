"""!The manifest designer's diagram model (D-43 §3): what a system shows on the canvas, built from its manifest by
the system's adapter and never saved as such.

  Diagram    elements, links and the view
  Element    one box: a node (a palette kind with ports, Node-RED style) or a shape (rectangle, rounded box,
             ellipse, diamond, note, text, frame; draw.io style)
  Link       a wire between two ports, or a connector between two elements (port None)
  ElementKind, PortSpec, PropertySpec   a palette entry, its ports, its inspector fields
  Diagnostic a problem, with the elements and links it is about

Positions and sizes are integer canvas units (diffs stay readable, as D-18 §4.3 asks of the AI graphs). Every
type converts to and from plain JSON (to_json / from_json) for `capsule-studio designer show --json` and tests.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

## Element.role of a node: a palette kind with ports, part of the system's data.
ROLE_NODE = "node"
## Element.role of a shape: a box with text and no ports (a note, a frame, a UML-style box).
ROLE_SHAPE = "shape"

## Port.side of an input (left on a left-to-right diagram).
SIDE_IN = "in"
## Port.side of an output.
SIDE_OUT = "out"

## PortSpec.data_type that connects to every type (a free connector).
ANY_TYPE = "any"

## PropertySpec.value_type of free text.
VALUE_TEXT = "text"
## PropertySpec.value_type of a whole number.
VALUE_INTEGER = "integer"
## PropertySpec.value_type of yes / no.
VALUE_BOOLEAN = "boolean"
## PropertySpec.value_type of one of PropertySpec.choices.
VALUE_CHOICE = "choice"
## PropertySpec.value_type of a colour, as "#rrggbb".
VALUE_COLOUR = "colour"
## Every PropertySpec.value_type.
VALUE_TYPES = (VALUE_TEXT, VALUE_INTEGER, VALUE_BOOLEAN, VALUE_CHOICE, VALUE_COLOUR)

## Diagnostic.severity of a problem that makes the manifest wrong.
SEVERITY_ERROR = "error"
## Diagnostic.severity of something worth a look.
SEVERITY_WARNING = "warning"

## Numbers in a position or a size (x and y, or width and height).
PAIR = 2
## Separator of an element id and a port name in a link endpoint's text form ("n1.out").
PORT_SEPARATOR = "."

## A position or size: two integers.
Point = tuple[int, int]
## JSON values as read from a manifest.
JsonValue = Any


class ModelError(ValueError):
   """!A diagram or a value that does not fit the model."""


@dataclass(frozen=True)
class PropertySpec:
   """!One inspector field of an element kind."""

   ## Key in Element.properties.
   name: str
   ## Shown in the inspector.
   title: str
   ## One of VALUE_TYPES.
   value_type: str = VALUE_TEXT
   ## Value of a new element.
   default: JsonValue = None
   ## Choices of a VALUE_CHOICE field.
   choices: tuple[str, ...] = ()
   ## Smallest VALUE_INTEGER value, or None.
   minimum: int | None = None
   ## Largest VALUE_INTEGER value, or None.
   maximum: int | None = None
   ## Tooltip.
   help: str = ""

   def coerce(self, value: JsonValue) -> JsonValue:
      """!A value for this field, converted from text where that is unambiguous (the command line passes text).
      @param value  the value
      @return the value as this field stores it
      @throws ModelError when it does not fit
      """
      kind = self.value_type
      if kind == VALUE_INTEGER:
         if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ModelError(f"{self.title}: a whole number is needed, not {value!r}")
         try:
            number = int(value)
         except ValueError:
            raise ModelError(f"{self.title}: a whole number is needed, not {value!r}") from None
         low, high = self.minimum, self.maximum
         if (low is not None and number < low) or (high is not None and number > high):
            raise ModelError(f"{self.title}: {number} is outside {low}..{high}")
         return number
      if kind == VALUE_BOOLEAN:
         if isinstance(value, bool):
            return value
         text = str(value).strip().lower()
         if text in ("yes", "true", "on", "1"):
            return True
         if text in ("no", "false", "off", "0"):
            return False
         raise ModelError(f"{self.title}: yes or no is needed, not {value!r}")
      if kind == VALUE_CHOICE:
         if value not in self.choices:
            raise ModelError(f"{self.title}: one of {', '.join(self.choices)} is needed, not {value!r}")
         return value
      if kind == VALUE_COLOUR:
         text = str(value)
         if not is_colour(text):
            raise ModelError(f"{self.title}: a colour like #3c9a4b is needed, not {value!r}")
         return text.lower()
      return "" if value is None else str(value)


## Characters of a "#rrggbb" colour.
COLOUR_LENGTH = len("#rrggbb")
## Digits of a colour.
HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def is_colour(text: str) -> bool:
   """!Whether text is a "#rrggbb" colour.
   @param text  the text
   @return True for a colour
   """
   return len(text) == COLOUR_LENGTH and text.startswith("#") and all(c in HEX_DIGITS for c in text[1:])


@dataclass(frozen=True)
class PortSpec:
   """!One port of a node kind."""

   ## Name, unique among the kind's ports.
   name: str
   ## SIDE_IN or SIDE_OUT.
   side: str
   ## Data type; ports connect when the system's compatible() says the types fit.
   data_type: str = ANY_TYPE
   ## Whether it takes more than one link (outputs usually do; inputs usually take one).
   many: bool = False
   ## Whether an input must be connected (checks.py reports it otherwise).
   required: bool = False
   ## Shown beside the port.
   title: str = ""

   def label(self) -> str:
      """!What the canvas writes beside the port.
      @return the title, or the name
      """
      return self.title or self.name


@dataclass(frozen=True)
class ElementKind:
   """!A palette entry: what one kind of element is."""

   ## Id, unique in its system (stored in the manifest).
   kind_id: str
   ## Shown in the palette and on the element.
   title: str
   ## ROLE_NODE or ROLE_SHAPE.
   role: str = ROLE_NODE
   ## Palette category.
   category: str = ""
   ## Colour of the element's header ("#rrggbb"), as Node-RED colours each category.
   colour: str = "#8fa8c8"
   ## Ports (nodes only).
   ports: tuple[PortSpec, ...] = ()
   ## Inspector fields.
   properties: tuple[PropertySpec, ...] = ()
   ## Size of a new element.
   size: Point = (0, 0)
   ## Palette tooltip.
   help: str = ""
   ## The shape drawn: one of system.SHAPES (shapes; nodes are rounded boxes).
   shape: str = ""
   ## Whether it may hold other elements (a frame).
   container: bool = False

   def port(self, name: str) -> PortSpec | None:
      """!One of the kind's ports.
      @param name  its name
      @return the port, or None
      """
      return next((p for p in self.ports if p.name == name), None)

   def inputs(self) -> list[PortSpec]:
      """!The kind's input ports, in order.
      @return ports
      """
      return [p for p in self.ports if p.side == SIDE_IN]

   def outputs(self) -> list[PortSpec]:
      """!The kind's output ports, in order.
      @return ports
      """
      return [p for p in self.ports if p.side == SIDE_OUT]

   def property(self, name: str) -> PropertySpec | None:
      """!One of the kind's inspector fields.
      @param name  its name
      @return the field, or None
      """
      return next((p for p in self.properties if p.name == name), None)

   def defaults(self) -> dict[str, JsonValue]:
      """!The properties of a new element.
      @return name -> default value
      """
      return {p.name: copy.deepcopy(p.default) for p in self.properties}


@dataclass
class Element:
   """!One box on the canvas."""

   ## Id, unique in the diagram (a system usually takes it from the manifest).
   element_id: str
   ## ElementKind.kind_id.
   kind: str
   ## Top-left corner.
   pos: Point = (0, 0)
   ## Width and height ((0, 0): the kind's size).
   size: Point = (0, 0)
   ## Inspector values, by PropertySpec.name.
   properties: dict[str, JsonValue] = field(default_factory=dict)
   ## The frame holding it, or None.
   parent: str | None = None
   ## Whether it lives only in the editor block (notes, frames, draw.io shapes) rather than in the system's data.
   annotation: bool = False

   def to_json(self) -> dict[str, JsonValue]:
      """!The element as plain JSON.
      @return a dict
      """
      out: dict[str, JsonValue] = {"id": self.element_id, "kind": self.kind, "pos": list(self.pos)}
      if self.size != (0, 0):
         out["size"] = list(self.size)
      if self.properties:
         out["properties"] = copy.deepcopy(self.properties)
      if self.parent is not None:
         out["parent"] = self.parent
      if self.annotation:
         out["annotation"] = True
      return out

   @staticmethod
   def from_json(data: dict[str, JsonValue]) -> Element:
      """!An element from to_json()'s form.
      @param data  the dict
      @return the element
      @throws ModelError when it is malformed
      """
      try:
         return Element(str(data["id"]), str(data["kind"]), point(data.get("pos", (0, 0))),
                        point(data.get("size", (0, 0))), dict(data.get("properties", {})), data.get("parent"),
                        bool(data.get("annotation", False)))
      except (KeyError, TypeError) as e:
         raise ModelError(f"malformed element {data!r}: {e}") from None


@dataclass(frozen=True)
class Endpoint:
   """!One end of a link: an element, and a port of it (None: the element itself, a free connector)."""

   ## Element.element_id.
   element: str
   ## PortSpec.name, or None.
   port: str | None = None

   def text(self) -> str:
      """!The endpoint as "element.port" (or "element").
      @return text
      """
      return self.element if self.port is None else f"{self.element}{PORT_SEPARATOR}{self.port}"

   @staticmethod
   def parse(text: str) -> Endpoint:
      """!An endpoint from text(): the port follows the last separator.
      @param text  "element.port" or "element"
      @return the endpoint
      """
      element, sep, port = text.rpartition(PORT_SEPARATOR)
      return Endpoint(element, port) if sep and element else Endpoint(text)


@dataclass
class Link:
   """!A wire or a connector."""

   ## Id, unique in the diagram.
   link_id: str
   ## Where it starts (an output port, or an element).
   source: Endpoint
   ## Where it ends (an input port, or an element).
   target: Endpoint
   ## Text drawn on it.
   label: str = ""
   ## Whether it lives only in the editor block (a draw.io connector between notes and boxes).
   annotation: bool = False

   def to_json(self) -> dict[str, JsonValue]:
      """!The link as plain JSON.
      @return a dict
      """
      out: dict[str, JsonValue] = {"id": self.link_id, "from": self.source.text(), "to": self.target.text()}
      if self.label:
         out["label"] = self.label
      if self.annotation:
         out["annotation"] = True
      return out

   @staticmethod
   def from_json(data: dict[str, JsonValue]) -> Link:
      """!A link from to_json()'s form.
      @param data  the dict
      @return the link
      @throws ModelError when it is malformed
      """
      try:
         return Link(str(data["id"]), Endpoint.parse(str(data["from"])), Endpoint.parse(str(data["to"])),
                     str(data.get("label", "")), bool(data.get("annotation", False)))
      except (KeyError, TypeError) as e:
         raise ModelError(f"malformed link {data!r}: {e}") from None


@dataclass
class Diagnostic:
   """!A problem a check found."""

   ## SEVERITY_ERROR or SEVERITY_WARNING.
   severity: str
   ## What is wrong, in a sentence.
   message: str
   ## The elements it is about.
   elements: tuple[str, ...] = ()
   ## The links it is about.
   links: tuple[str, ...] = ()

   def to_json(self) -> dict[str, JsonValue]:
      """!The diagnostic as plain JSON.
      @return a dict
      """
      severity, message, elements, links = self.severity, self.message, self.elements, self.links
      return {"severity": severity, "message": message, "elements": list(elements), "links": list(links)}


@dataclass
class Diagram:
   """!Everything the canvas shows of one manifest."""

   ## Elements by id, in drawing order (later ones on top).
   elements: dict[str, Element] = field(default_factory=dict)
   ## Links by id.
   links: dict[str, Link] = field(default_factory=dict)
   ## The view: "zoom" (a percentage) and "centre" ([x, y]), or empty.
   view: dict[str, JsonValue] = field(default_factory=dict)

   def element(self, element_id: str) -> Element:
      """!One element.
      @param element_id  its id
      @return the element
      @throws ModelError when there is none
      """
      found = self.elements.get(element_id)
      if found is None:
         raise ModelError(f"no element {element_id!r}")
      return found

   def link(self, link_id: str) -> Link:
      """!One link.
      @param link_id  its id
      @return the link
      @throws ModelError when there is none
      """
      found = self.links.get(link_id)
      if found is None:
         raise ModelError(f"no link {link_id!r}")
      return found

   def links_of(self, element_id: str) -> list[Link]:
      """!The links that start or end at an element.
      @param element_id  its id
      @return links, in diagram order
      """
      return [k for k in self.links.values() if element_id in (k.source.element, k.target.element)]

   def links_at(self, endpoint: Endpoint) -> list[Link]:
      """!The links that start or end at one port (or element, for a free connector).
      @param endpoint  the endpoint
      @return links, in diagram order
      """
      return [k for k in self.links.values() if endpoint in (k.source, k.target)]

   def children(self, element_id: str) -> list[Element]:
      """!The elements a frame holds directly.
      @param element_id  the frame
      @return elements, in drawing order
      """
      return [e for e in self.elements.values() if e.parent == element_id]

   def descendants(self, element_id: str) -> list[Element]:
      """!The elements a frame holds, at any depth.
      @param element_id  the frame
      @return elements
      """
      out: list[Element] = []
      seen = {element_id}   # frames that hold each other (a malformed manifest) must not loop
      todo = [element_id]
      while todo:
         for child in self.children(todo.pop()):
            if child.element_id in seen:
               continue
            seen.add(child.element_id)
            out.append(child)
            todo.append(child.element_id)
      return out

   def new_id(self, prefix: str) -> str:
      """!An id no element or link has yet: prefix and the smallest free number from 1.
      @param prefix  e.g. "n", "note", "w"
      @return the id
      """
      taken = set(self.elements) | set(self.links)
      number = 1
      while f"{prefix}{number}" in taken:
         number += 1
      return f"{prefix}{number}"

   def copy(self) -> Diagram:
      """!A deep copy.
      @return the copy
      """
      return copy.deepcopy(self)

   def to_json(self) -> dict[str, JsonValue]:
      """!The diagram as plain JSON.
      @return a dict
      """
      view = self.view
      return {"elements": [e.to_json() for e in self.elements.values()],
              "links": [k.to_json() for k in self.links.values()], "view": copy.deepcopy(view)}

   @staticmethod
   def from_json(data: dict[str, JsonValue]) -> Diagram:
      """!A diagram from to_json()'s form.
      @param data  the dict
      @return the diagram
      """
      elements = [Element.from_json(e) for e in data.get("elements", [])]
      links = [Link.from_json(k) for k in data.get("links", [])]
      return Diagram({e.element_id: e for e in elements}, {k.link_id: k for k in links},
                     dict(data.get("view", {})))


def point(value: JsonValue) -> Point:
   """!Two integers from a JSON pair.
   @param value  [x, y]
   @return (x, y)
   @throws ModelError when it is not a pair of integers
   """
   if not isinstance(value, (list, tuple)) or len(value) != PAIR:
      raise ModelError(f"a pair of whole numbers is needed, not {value!r}")
   x, y = value
   if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
      raise ModelError(f"a pair of whole numbers is needed, not {value!r}")
   return (x, y)
