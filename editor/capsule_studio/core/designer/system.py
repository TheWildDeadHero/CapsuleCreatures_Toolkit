"""!What a designer system supplies (D-43 §4), and what every system shares.

A system subclasses DesignerSystem. It names the manifest schema it edits and its palette (element kinds), says
which ports connect, reads its manifest into a Diagram and writes a Diagram back, and adds its own checks; it may
offer live values (shown on each node, as D-18's preview will) and a new, empty manifest.

Every system also gets the shared shapes (SHAPE_KINDS: rectangle, rounded box, ellipse, diamond, note, text and
frame, draw.io style) and free connectors between any two elements. They are annotations: the system's data has no
place for them, so read_annotations() and write_annotations() keep them in the manifest's "editor" block, under
"designer", together with the view. Compilers drop "editor" blocks, so annotations never reach a ROM.

    "editor": {"designer": {
       "shapes": [{"id": "note1", "kind": "note", "pos": [40, 40], "size": [160, 80],
                   "properties": {"text": "Scores add up here"}}],
       "connectors": [{"id": "c1", "from": "note1", "to": "n3", "label": ""}],
       "view": {"zoom": 100, "centre": [300, 200]}}}
"""
from __future__ import annotations

import copy
from typing import Any

from .model import (ANY_TYPE, ROLE_SHAPE, VALUE_COLOUR, VALUE_TEXT, Diagnostic, Diagram, Element, ElementKind,
                    Link, ModelError, PropertySpec)

## The manifest's editor-only block (the Design doc's convention: compilers drop it).
EDITOR_KEY = "editor"
## The designer's part of the editor block.
DESIGNER_KEY = "designer"
## Annotation shapes in the designer block.
SHAPES_KEY = "shapes"
## Free connectors in the designer block.
CONNECTORS_KEY = "connectors"
## The view in the designer block.
VIEW_KEY = "view"

## Direction of auto-layout and of a node's ports: inputs on the left, outputs on the right.
LEFT_TO_RIGHT = "left-to-right"
## Inputs on top, outputs below.
TOP_TO_BOTTOM = "top-to-bottom"

## Drawn shapes (ElementKind.shape).
SHAPE_RECTANGLE = "rectangle"
## A box with rounded corners (also how nodes are drawn).
SHAPE_ROUNDED = "rounded"
## An ellipse.
SHAPE_ELLIPSE = "ellipse"
## A diamond (a decision).
SHAPE_DIAMOND = "diamond"
## A sticky note with a folded corner.
SHAPE_NOTE = "note"
## Text without a border.
SHAPE_TEXT = "text"
## A frame: a titled box that holds other elements and carries them when moved.
SHAPE_FRAME = "frame"
## Every shape.
SHAPES = (SHAPE_RECTANGLE, SHAPE_ROUNDED, SHAPE_ELLIPSE, SHAPE_DIAMOND, SHAPE_NOTE, SHAPE_TEXT, SHAPE_FRAME)

## Palette category of the shared shapes.
SHAPES_CATEGORY = "Shapes"
## Colour of the shared shapes' fill when none is set.
SHAPE_FILL = "#f4f1e8"
## Colour of a note's fill when none is set.
NOTE_FILL = "#fff3b0"
## Colour of a frame's fill when none is set.
FRAME_FILL = "#eef3f8"
## Palette colour of the text shape (it has no fill).
TEXT_SWATCH = "#ffffff"
## Size of a new box shape (canvas units).
SHAPE_SIZE = (160, 80)
## Size of a new text shape.
TEXT_SIZE = (160, 40)
## Size of a new frame.
FRAME_SIZE = (400, 280)


def _shape_fields(fill: str) -> tuple[PropertySpec, ...]:
   """!The inspector fields of a shared shape.
   @param fill  its default fill colour
   @return fields
   """
   return (PropertySpec("text", "Text", VALUE_TEXT, "", help="What the shape says"),
           PropertySpec("fill", "Fill", VALUE_COLOUR, fill, help="Fill colour"))


def _shape(kind_id: str, title: str, shape: str, fill: str, size: tuple[int, int], help_text: str,
           container: bool = False) -> ElementKind:
   """!A shared shape.
   @param kind_id    its id
   @param title      its title
   @param shape      what is drawn (one of SHAPES)
   @param fill       its default fill (also its palette swatch)
   @param size       its size when added
   @param help_text  its palette tooltip
   @param container  whether it holds other elements
   @return the kind
   """
   return ElementKind(kind_id, title, ROLE_SHAPE, SHAPES_CATEGORY, fill, properties=_shape_fields(fill), size=size,
                      help=help_text, shape=shape, container=container)


## The shapes every system's palette offers (annotations, kept in the editor block).
SHAPE_KINDS = (
   _shape("rectangle", "Rectangle", SHAPE_RECTANGLE, SHAPE_FILL, SHAPE_SIZE, "A box with text"),
   _shape("rounded", "Rounded box", SHAPE_ROUNDED, SHAPE_FILL, SHAPE_SIZE, "A box with rounded corners"),
   _shape("ellipse", "Ellipse", SHAPE_ELLIPSE, SHAPE_FILL, SHAPE_SIZE, "An ellipse with text"),
   _shape("diamond", "Diamond", SHAPE_DIAMOND, SHAPE_FILL, SHAPE_SIZE, "A decision"),
   _shape("note", "Note", SHAPE_NOTE, NOTE_FILL, SHAPE_SIZE, "A sticky note"),
   ElementKind("text", "Text", ROLE_SHAPE, SHAPES_CATEGORY, TEXT_SWATCH,
               properties=(PropertySpec("text", "Text", VALUE_TEXT, "Text"),),
               size=TEXT_SIZE, shape=SHAPE_TEXT, help="Text without a border"),
   _shape("frame", "Frame", SHAPE_FRAME, FRAME_FILL, FRAME_SIZE, "A titled frame; what is inside moves with it",
          container=True),
)


class DesignerSystem:
   """!The base of every system. Subclasses set the class attributes and override read() and write()."""

   ## Id (the command line's --system; unique among systems).
   system_id = ""
   ## Shown in the window title and the system list.
   title = ""
   ## The manifest schema it edits ("capsule.aigraph/1", ...).
   schema = ""
   ## What it is for, in a sentence.
   description = ""
   ## LEFT_TO_RIGHT or TOP_TO_BOTTOM.
   direction = LEFT_TO_RIGHT
   ## Whether links may form a cycle.
   allow_cycles = False
   ## Whether the shared shapes and free connectors are offered.
   annotations = True
   ## Prefix of a new node's id.
   node_prefix = "n"
   ## Prefix of a new link's id.
   link_prefix = "w"
   ## Whether it is only for developing the designer (hidden unless asked for).
   dev_only = False

   # -- what a system supplies ------------------------------------------------------------------------------------

   def node_kinds(self) -> tuple[ElementKind, ...]:
      """!The system's own palette (its nodes and boxes); the shared shapes follow them.
      @return kinds
      """
      return ()

   def empty(self) -> dict[str, Any]:
      """!A new, empty manifest.
      @return its JSON
      """
      return {"schema": self.schema}

   def read(self, data: dict[str, Any]) -> Diagram:
      """!The diagram of a manifest (the system's nodes and links; annotations are added by load()).
      @param data  the manifest
      @return the diagram
      @throws ModelError when the manifest cannot be shown
      """
      raise NotImplementedError

   def write(self, diagram: Diagram, data: dict[str, Any]) -> None:
      """!Writes a diagram's nodes and links into the manifest, in place, keeping every key the system does not own
      (annotations are written by save()).
      @param diagram  the diagram
      @param data     the manifest
      @return None
      """
      raise NotImplementedError

   def compatible(self, source_type: str, target_type: str) -> bool:
      """!Whether an output of one data type may feed an input of another.
      @param source_type  the output's PortSpec.data_type
      @param target_type  the input's PortSpec.data_type
      @return True when they connect
      """
      return ANY_TYPE in (source_type, target_type) or source_type == target_type

   def check(self, diagram: Diagram) -> list[Diagnostic]:
      """!The system's own checks (checks.py runs the shared ones first).
      @param diagram  the diagram
      @return problems
      """
      return []

   def live_values(self, diagram: Diagram) -> dict[str, str]:
      """!Values to show on nodes (D-18's preview; Sample flow evaluates its numbers).
      @param diagram  the diagram
      @return element id -> short text (empty: none)
      """
      return {}

   def node_text(self, element: Element) -> str:
      """!The line a node shows under its title (e.g. its main setting).
      @param element  the node
      @return text (empty: none)
      """
      return ""

   # -- what every system shares ----------------------------------------------------------------------------------

   def kinds(self) -> tuple[ElementKind, ...]:
      """!The whole palette: the system's kinds, then the shared shapes when annotations are on.
      @return kinds
      """
      return self.node_kinds() + (SHAPE_KINDS if self.annotations else ())

   def kind(self, kind_id: str) -> ElementKind:
      """!One palette kind.
      @param kind_id  its id
      @return the kind
      @throws ModelError when the system has none
      """
      # The palette never changes, so its index is built once (kind() runs for every element on every redraw).
      index = self.__dict__.get("_kind_index")
      if index is None:
         index = {k.kind_id: k for k in self.kinds()}
         self.__dict__["_kind_index"] = index
      found = index.get(kind_id)
      if found is None:
         raise ModelError(f"{self.title} has no {kind_id!r} (it has " + ", ".join(k.kind_id for k in self.kinds())
                          + ")")
      return found

   def element_size(self, element: Element) -> tuple[int, int]:
      """!An element's size: its own, else its kind's.
      @param element  the element
      @return width and height
      """
      if element.size != (0, 0):
         return element.size
      return self.kind(element.kind).size

   def load(self, data: dict[str, Any]) -> Diagram:
      """!The full diagram of a manifest: read(), then the annotations and the view from the editor block.
      @param data  the manifest
      @return the diagram
      """
      diagram = self.read(data)
      if self.annotations:
         read_annotations(data, diagram)
      return diagram

   def save(self, diagram: Diagram, data: dict[str, Any]) -> None:
      """!Writes the full diagram: write(), then the annotations and the view into the editor block.
      @param diagram  the diagram
      @param data     the manifest (changed in place)
      @return None
      """
      self.write(diagram, data)
      if self.annotations:
         write_annotations(diagram, data)

   def is_node(self, element: Element) -> bool:
      """!Whether an element is one of the system's own (not an annotation).
      @param element  the element
      @return True for the system's nodes and boxes
      """
      return not element.annotation


def read_annotations(data: dict[str, Any], diagram: Diagram) -> None:
   """!Adds the editor block's shapes, connectors and view to a diagram.
   @param data     the manifest
   @param diagram  the diagram (changed in place)
   @return None
   @throws ModelError when the block is malformed
   """
   block = data.get(EDITOR_KEY, {}).get(DESIGNER_KEY, {})
   if not isinstance(block, dict):
      raise ModelError(f"{EDITOR_KEY}.{DESIGNER_KEY} must be an object")
   for raw in block.get(SHAPES_KEY, []):
      element = Element.from_json(raw)
      element.annotation = True
      if element.element_id in diagram.elements:
         raise ModelError(f"shape {element.element_id!r} has the id of another element")
      diagram.elements[element.element_id] = element
   for raw in block.get(CONNECTORS_KEY, []):
      link = Link.from_json(raw)
      link.annotation = True
      if link.link_id in diagram.links:
         raise ModelError(f"connector {link.link_id!r} has the id of another link")
      diagram.links[link.link_id] = link
   diagram.view = dict(block.get(VIEW_KEY, {}))


def write_annotations(diagram: Diagram, data: dict[str, Any]) -> None:
   """!Writes a diagram's shapes, connectors and view into the editor block (the block goes when it is empty).
   @param diagram  the diagram
   @param data     the manifest (changed in place)
   @return None
   """
   shapes = []
   for e in diagram.elements.values():
      if e.annotation:
         raw = e.to_json()
         raw.pop("annotation", None)
         shapes.append(raw)
   connectors = []
   for k in diagram.links.values():
      if k.annotation:
         raw = k.to_json()
         raw.pop("annotation", None)
         connectors.append(raw)
   block: dict[str, Any] = {}
   if shapes:
      block[SHAPES_KEY] = shapes
   if connectors:
      block[CONNECTORS_KEY] = connectors
   if diagram.view:
      block[VIEW_KEY] = copy.deepcopy(diagram.view)
   editor = data.get(EDITOR_KEY)
   if block:
      if not isinstance(editor, dict):
         editor = data[EDITOR_KEY] = {}
      editor[DESIGNER_KEY] = block
   elif isinstance(editor, dict):
      editor.pop(DESIGNER_KEY, None)
      if not editor:
         del data[EDITOR_KEY]
