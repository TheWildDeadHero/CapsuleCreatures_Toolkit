"""!Map panel: paint metatiles on a map's tile layers and attributes
(collision, elevation, behavior, encounter, encounter slot, env) on its
attribute layer.

Extensions (capsule_studio.plugins) add map tools (toolbar buttons after the
built-in ones), overlays (the Overlay chooser) and hover text."""
from __future__ import annotations

import math
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import mapgroups, maps, mapview
from ...plugins import MapView, Registry
from ..panel import EditorPanel
from ..qtimage import to_qimage
from ..widgets import MetatileGrid, button, grid_area
from .maptree import MapTree

if TYPE_CHECKING:
   from ...core.document import Document
   from ...core.world import Project
   from ...plugins import MapTool
   from ..panel import PanelHost
   from .maptree import GroupPath, Node

## A map cell, (x, y) in metatiles.
Cell = tuple[int, int]
## A map rectangle in metatiles: (x0, y0, w, h).
Area = tuple[int, int, int, int]
## A map rectangle in metatiles, corners included: (x0, y0, x1, y1).
Box = tuple[int, int, int, int]
## Metatiles picked together: rows of "tileset/metatile" (None: leave the cell alone).
Stamp = list[list[str | None]]
## What an extension overlay shows on a cell: (RGBA color or None, short text or None).
OverlayCell = tuple[tuple[int, ...] | None, str | None]
## A tileset's metatile pictures: ("tileset/metatile", QImage or None), in tileset order.
Pictures = list[tuple[str, QtGui.QImage | None]]

## Tools, in toolbar order: (id, label, tooltip).
TOOLS = [
   ("paint", "Paint", "Paint the chosen metatile on the current layer, or the chosen attribute on the "
                      "attribute layer (drag for a line of cells)"),
   ("rect", "Rectangle", "Drag a rectangle (metatile or attribute, like Paint)"),
   ("fill", "Fill", "Flood-fill the area that shows the same thing on the current layer"),
   ("clear", "Clear", "Remove the current layer's metatile (the cell stays painted on the other layers)"),
   ("erase", "Erase", "Unpaint cells on every layer: the border shows there and they are always blocked"),
   ("pick", "Pick", "Take the metatile of the current layer, or the attribute, of a cell (right click does this too)"),
]
## Current-layer value meaning the attribute layer (tile layers are their BG numbers).
ATTRIBUTES = "attributes"
## Attribute fields in the attribute chooser: (field, label).
ATTRIBUTE_FIELDS = [("collision", "Collision"), ("elevation", "Elevation"), ("behavior", "Behavior"),
                    ("encounter", "Encounter"), ("slot", "Encounter slot"), ("env", "Environment tag")]
## The attributes set with the value box (its range: the field's highest value, core.maps.cell_fields()).
VALUE_FIELDS = ("collision", "elevation", "slot", "env")
## Map zoom choices, percent (100% = one screen pixel per map pixel).
ZOOM_LEVELS = (50, 100, 150, 200, 300, 400, 600)
## Zoom a map opens at, percent.
DEFAULT_ZOOM = 200
## Collision tint for collision values 1-3 (RGBA).
COLLISION_TINT = QtGui.QColor(255, 40, 40, 110)
## Encounter tint (RGBA).
ENCOUNTER_TINT = QtGui.QColor(40, 220, 80, 110)
## Behavior tints, by the map's behavior dictionary index (entry 0 is not tinted).
BEHAVIOR_TINTS = [QtGui.QColor.fromHsv(h, 200, 230, 110) for h in (60, 140, 200, 20, 250, 100, 170, 230)]

## Zoom levels are percent: 100 is one screen pixel per map pixel.
PERCENT = 100
## Lowest zoom set_zoom() accepts, percent.
MIN_ZOOM = 25
## Smallest cell (screen pixels) that still gets the cell grid (100% zoom).
MIN_GRID_CELL = 16
## Map area shown for a map without painted cells, metatiles (also before the first map).
EMPTY_AREA = (0, 0, 16, 16)
## Map area shown without a map, metatiles.
NO_MAP_AREA = (0, 0, 8, 8)
## Unpainted metatiles shown around a map's painted cells, on each side.
VIEW_MARGIN = 4
## Extra width (height) of the shown area over the painted bounds: the margin on both sides, plus one
## (the bounds are inclusive).
VIEW_MARGIN_SPAN = 9
## Index of the width in an Area, and of the right column in a Box.
AREA_W = 2
## Index of the height in an Area, and of the bottom row in a Box.
AREA_H = 3
## Cells to chunks: a chunk is 1 << CHUNK_SHIFT (maps.CHUNK) cells wide.
CHUNK_SHIFT = 3
## A cell's position inside its chunk: the low CHUNK_SHIFT bits.
CHUNK_MASK = 7
## Bresenham's line works on twice the error term.
ERROR_SCALE = 2
## Half the view, for its middle.
HALF = 2

## Background behind the map (and the border pattern).
CANVAS_BACKGROUND = QtGui.QColor(30, 30, 36)
## Cells whose metatile has no picture (missing, or the tileset does not compile).
MISSING_COLOR = QtGui.QColor(255, 0, 255)
## Shade over the border pattern shown around the map.
BORDER_DIM = QtGui.QColor(0, 0, 0, 120)
## Opacity of the tile layers in front of the painted one ("Fade layers in front").
FADED_OPACITY = 0.35
## Opacity of the stamp previewed under the mouse.
STAMP_PREVIEW_OPACITY = 0.6
## Shade over the cells of the stroke in progress.
STROKE_SHADE = QtGui.QColor(255, 255, 255, 70)
## Lines between cells.
GRID_COLOR = QtGui.QColor(0, 0, 0, 60)
## Lines between chunks.
CHUNK_LINE_COLOR = QtGui.QColor(255, 220, 0, 140)
## Frame of the right-drag pick rectangle.
PICK_AREA_COLOR = QtGui.QColor(80, 200, 255)
## Frame of the hovered cell (or stamp footprint).
HOVER_COLOR = QtGui.QColor(255, 255, 255)
## Width of those frames, pixels.
FRAME_PEN_WIDTH = 2
## Pixels repainted around a changed cell (the hover frame reaches past it).
REPAINT_MARGIN = 2
## Grid lines drawn up to range(first, last + LINE_RANGE_END): the far edge of the last cell too.
LINE_RANGE_END = 2
## Text drawn on cells (attribute values, extension overlays).
CELL_TEXT_COLOR = QtGui.QColor(255, 255, 255)
## Left inset of that text, pixels.
CELL_TEXT_INSET = 2

## Height of the layer list, pixels.
LAYER_LIST_HEIGHT = 110
## The attribute field the value box starts on (its range is the field's highest value, core.maps.cell_fields()).
COLLISION_FIELD = "collision"
## Space above the tilesets line, pixels.
TILESETS_SPACING = 6
## Layout stretch of the map list column.
LIST_STRETCH = 2
## Layout stretch of the map column.
MAP_STRETCH = 7
## Layout stretch of the layers and palette column.
SIDE_STRETCH = 3
## Extension diagnostics listed under the map at most.
DIAGNOSTICS_SHOWN = 6
## Letters of a behavior name shown on the overlay.
BEHAVIOR_SHORT_LETTERS = 4
## Index of the BG number in a "BGn" label.
BG_DIGIT_INDEX = 2
## (w, h) of maps.border_of()'s (w, h, patterns): its first two fields.
BORDER_SIZE_FIELDS = 2
## Screen pixels per border pattern cell.
BORDER_CELL = 32
## Lines between border pattern cells.
BORDER_GRID_COLOR = QtGui.QColor(0, 0, 0, 120)


def line_cells(a: Cell, b: Cell) -> Iterator[Cell]:
   """!Cells on a line between two cells (Bresenham), both ends included.
   @param a  (x, y)
   @param b  (x, y)
   @return generator of (x, y)
   """
   (x, y), (x1, y1) = a, b
   dx, dy = abs(x1 - x), -abs(y1 - y)
   sx, sy = (1 if x1 > x else -1), (1 if y1 > y else -1)
   err = dx + dy
   while True:
      yield x, y
      if (x, y) == (x1, y1):
         return
      e2 = ERROR_SCALE * err
      if e2 >= dy:
         err += dy
         x += sx
      if e2 <= dx:
         err += dx
         y += sy


class MapCanvas(QtWidgets.QWidget):
   """!Draws a map from its document (cells) and the pictures of its
   tilesets' metatiles, with grid, chunk and collision overlays, and turns
   mouse input into tool strokes for MapPanel.

   @var hover
   Cell under the mouse, or None.
   """

   def __init__(self, panel: MapPanel) -> None:
      """!Creates the canvas.
      @param panel  owning MapPanel
      """
      super().__init__()
      ## The owning MapPanel.
      self.panel = panel
      ## Screen pixels per map pixel (0.5 = 50%).
      self.zoom = DEFAULT_ZOOM / PERCENT
      ## Map rectangle shown, metatiles: (x0, y0, w, h).
      self.area = EMPTY_AREA
      self.hover = None
      ## Stroke cells being dragged: {(x, y): True} (line tools only), in stroke order.
      self.stroke = {}
      ## Right-drag pick: (start cell, current cell), or None.
      self.picking = None
      ## Drag start, or None.
      self.anchor = None
      ## Rectangle drag corner opposite the anchor, or None.
      self.corner = None
      ## Last cell added to a line stroke, or None.
      self.last = None
      self.setMouseTracking(True)
      self.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)

   def set_area(self, area: Area) -> None:
      """!Changes the shown rectangle and resizes.
      @param area  (x0, y0, w, h) in metatiles
      @return None
      """
      self.area = area
      self.setFixedSize(area[AREA_W] * self.cell(), area[AREA_H] * self.cell())
      self.update()

   def cell(self) -> int:
      """!Screen pixels per metatile at the current zoom.
      @return pixels (8 at 50%, 16 at 100%, ...)
      """
      return max(1, round(mapview.METATILE * self.zoom))

   def set_zoom(self, percent: int) -> None:
      """!Changes the zoom.
      @param percent  one of ZOOM_LEVELS
      @return None
      """
      self.zoom = max(MIN_ZOOM, int(percent)) / PERCENT
      self.set_area(self.area)

   def cell_at(self, pos: QtCore.QPoint | QtCore.QPointF) -> Cell:
      """!Map cell under a widget position.
      @param pos  QPoint / QPointF
      @return (x, y) in metatiles
      """
      s = self.cell()
      return self.area[0] + math.floor(pos.x()) // s, self.area[1] + math.floor(pos.y()) // s

   def cell_rect(self, cell: Cell) -> QtCore.QRect:
      """!Widget rectangle of a map cell.
      @param cell  (x, y)
      @return QRect
      """
      s = self.cell()
      return QtCore.QRect((cell[0] - self.area[0]) * s, (cell[1] - self.area[1]) * s, s, s)

   def rect_cells(self) -> Box | None:
      """!The dragged rectangle.
      @return (x0, y0, x1, y1) inclusive, or None
      """
      if self.anchor is None or self.corner is None:
         return None
      (ax, ay), (cx, cy) = self.anchor, self.corner
      return min(ax, cx), min(ay, cy), max(ax, cx), max(ay, cy)

   def footprint_rect(self, cell: Cell) -> QtCore.QRect:
      """!Widget rectangle a stamp placed on a cell covers.
      @param cell  (x, y)
      @return QRect
      """
      w, h = self.panel.stamp_size()
      return self.cell_rect(cell).united(self.cell_rect((cell[0] + w - 1, cell[1] + h - 1)))

   def pick_area(self, a: Cell, b: Cell) -> QtCore.QRect:
      """!Widget rectangle of the cells between two corners.
      @param a  (x, y)
      @param b  (x, y)
      @return QRect
      """
      return self.cell_rect((min(a[0], b[0]), min(a[1], b[1]))).united(self.cell_rect((max(a[0], b[0]),
                                                                                       max(a[1], b[1]))))

   def update_cells(self, *cells: Cell | None) -> None:
      """!Repaints only some cells (with the stamp's footprint, for the hover preview).
      @param cells  (x, y) cells, None entries are ignored
      @return None
      """
      for c in cells:
         if c is not None:
            self.update(self.footprint_rect(c).adjusted(-REPAINT_MARGIN, -REPAINT_MARGIN, REPAINT_MARGIN,
                                                        REPAINT_MARGIN))

   def picture(self, names: list[str], index: int | None) -> QtGui.QImage | None:
      """!A dictionary entry's picture.
      @param names  the map's dictionary
      @param index  dictionary index, or None (blank)
      @return QImage, or None (blank or unknown)
      """
      if index is None or not 0 <= index < len(names):
         return None
      return self.panel.images.get(names[index])

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the visible part of the map.
      @param event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
      p.fillRect(self.rect(), CANVAS_BACKGROUND)
      panel = self.panel
      doc = panel.map_doc()
      if doc is None:   # cells still draw (magenta) when the map does not compile
         p.end()
         return
      s = self.cell()
      clip = event.rect()
      x0, y0, w, h = self.area
      # The cells the repainted rectangle touches, in widget cells (add x0, y0 for map cells).
      cx0, cy0 = max(0, clip.left() // s), max(0, clip.top() // s)
      cx1, cy1 = min(w - 1, clip.right() // s), min(h - 1, clip.bottom() // s)
      data = doc.data
      names = panel.names   # the resolved dictionary (I2: an "all" dictionary is every metatile of the tilesets)
      chunks = {tuple(c["at"]): c for c in data.get("chunks", [])}
      bw, bh, pats = maps.border_of(data)
      phase = (data.get("border") or {}).get("phase", [0, 0])
      backdrop = QtGui.QColor(data.get("backdrop", "#000000"))
      layers = maps.layers_of(data)
      shown = [k for k in maps.draw_order(data) if layers[k].get("bg") not in panel.hidden_bgs]
      faded = panel.faded_layers()
      overlay = panel.overlay_field()
      ext_cell = panel.extension_overlay_cell()   # an extension's overlay replaces the attribute one
      missing = MISSING_COLOR
      for cy in range(cy0, cy1 + 1):
         for cx in range(cx0, cx1 + 1):
            mx, my = x0 + cx, y0 + cy
            # The cell's chunk, then the cell inside it (rows first).
            chunk = chunks.get((mx >> CHUNK_SHIFT, my >> CHUNK_SHIFT))
            v = None if chunk is None else chunk["cells"][my & CHUNK_MASK][mx & CHUNK_MASK]
            target = QtCore.QRect(cx * s, cy * s, s, s)
            p.fillRect(target, backdrop)
            if v is None:   # border pattern (empty entries: the backdrop), dimmed
               bi = ((my + phase[1]) % bh) * bw + (mx + phase[0]) % bw   # the pattern repeats, shifted by phase
               for k in shown:
                  img = self.picture(names, pats[k][bi])
                  if img is not None:
                     p.drawImage(target, img)
               p.fillRect(target, BORDER_DIM)
               continue
            grids = chunk.get("layers") or []
            for k in shown:
               i = grids[k][my & CHUNK_MASK][mx & CHUNK_MASK] if k < len(grids) and grids[k] is not None else None
               if i is None:
                  continue
               img = self.picture(names, i)
               if k in faded:
                  p.setOpacity(FADED_OPACITY)
               if img is not None:
                  p.drawImage(target, img)
               else:
                  p.fillRect(target, missing)
               p.setOpacity(1.0)
            if ext_cell is not None:
               try:
                  shown_cell = ext_cell(mx, my, v)
               except Exception as e:   # a broken overlay must not break painting
                  panel.host.show_status(f"overlay: {e}")
                  ext_cell, shown_cell = None, None
               self.draw_extension(p, target, shown_cell)
            elif overlay is not None:
               self.draw_attribute(p, target, v, overlay)
      # Stroke preview.
      shade = STROKE_SHADE
      box = self.rect_cells()
      if box is not None:
         r = QtCore.QRect((box[0] - x0) * s, (box[1] - y0) * s, (box[AREA_W] - box[0] + 1) * s,
                          (box[AREA_H] - box[1] + 1) * s)
         p.fillRect(r.intersected(clip), shade)
      for (mx, my) in panel.stroke_footprint(self.stroke):
         if x0 + cx0 <= mx <= x0 + cx1 and y0 + cy0 <= my <= y0 + cy1:
            p.fillRect(QtCore.QRect((mx - x0) * s, (my - y0) * s, s, s), shade)
      if self.hover is not None and not self.stroke and box is None and self.picking is None:
         stamp = panel.paint_stamp()
         if stamp is not None:   # the stamp's metatiles, see-through, where a click would put them
            p.setOpacity(STAMP_PREVIEW_OPACITY)
            for dy, row in enumerate(stamp):
               for dx, name in enumerate(row):
                  img = panel.images.get(name) if name else None
                  if img is not None:
                     p.drawImage(self.cell_rect((self.hover[0] + dx, self.hover[1] + dy)), img)
            p.setOpacity(1.0)
      if panel.show_grid.isChecked() and self.cell() >= MIN_GRID_CELL:
         p.setPen(GRID_COLOR)
         for cx in range(cx0, cx1 + LINE_RANGE_END):
            p.drawLine(cx * s, cy0 * s, cx * s, (cy1 + 1) * s)
         for cy in range(cy0, cy1 + LINE_RANGE_END):
            p.drawLine(cx0 * s, cy * s, (cx1 + 1) * s, cy * s)
      p.setPen(QtGui.QPen(CHUNK_LINE_COLOR, 1))
      for cx in range(cx0, cx1 + LINE_RANGE_END):
         if (x0 + cx) % maps.CHUNK == 0:   # a chunk's left edge
            p.drawLine(cx * s, cy0 * s, cx * s, (cy1 + 1) * s)
      for cy in range(cy0, cy1 + LINE_RANGE_END):
         if (y0 + cy) % maps.CHUNK == 0:
            p.drawLine(cx0 * s, cy * s, (cx1 + 1) * s, cy * s)
      if self.picking is not None:
         r = self.pick_area(self.picking[0], self.picking[1])
         p.setPen(QtGui.QPen(PICK_AREA_COLOR, FRAME_PEN_WIDTH, QtCore.Qt.PenStyle.DashLine))
         p.drawRect(r.adjusted(1, 1, -1, -1))
      elif self.hover is not None:
         p.setPen(QtGui.QPen(HOVER_COLOR, FRAME_PEN_WIDTH))
         p.drawRect(self.footprint_rect(self.hover) if self.panel.paint_stamp() is not None
                    else self.cell_rect(self.hover))
      p.end()

   def draw_extension(self, p: QtGui.QPainter, target: QtCore.QRect, shown: OverlayCell | None) -> None:
      """!Draws what an extension overlay gives for one cell.
      @param p       QPainter
      @param target  the cell's QRect
      @param shown   (rgba tuple or None, text or None)
      @return None
      """
      color, text = shown if shown else (None, None)
      if color is not None:
         p.fillRect(target, QtGui.QColor(*color))
      if text:
         p.setPen(CELL_TEXT_COLOR)
         p.drawText(target.adjusted(CELL_TEXT_INSET, 0, 0, 0), int(QtCore.Qt.AlignmentFlag.AlignLeft |
                                                               QtCore.Qt.AlignmentFlag.AlignTop), text)

   def draw_attribute(self, p: QtGui.QPainter, target: QtCore.QRect, cell: int, field: str) -> None:
      """!Draws one attribute of a painted cell over it.
      @param p       QPainter
      @param target  the cell's QRect
      @param cell    attribute cell
      @param field   one of maps.cell_fields()
      @return None
      """
      a = maps.unpack(cell)
      value = a[field]
      if field == "collision":
         if value:
            p.fillRect(target, COLLISION_TINT)
         return
      if field == "encounter":
         if value:
            p.fillRect(target, ENCOUNTER_TINT)
         return
      if field == "slot":   # only encounter cells use their slot
         if not a["encounter"]:
            return
         p.fillRect(target, ENCOUNTER_TINT)
      if field == "behavior" and value:
         p.fillRect(target, BEHAVIOR_TINTS[(value - 1) % len(BEHAVIOR_TINTS)])   # tints repeat past the list
      if field == "behavior" and not value:
         return
      if field == "env" and not value:
         return
      p.setPen(CELL_TEXT_COLOR)
      text = self.panel.behavior_short(value) if field == "behavior" else f"{value:X}" if field == "elevation" \
          else str(value)
      p.drawText(target.adjusted(CELL_TEXT_INSET, 0, 0, 0), int(QtCore.Qt.AlignmentFlag.AlignLeft |
                                                            QtCore.Qt.AlignmentFlag.AlignTop), text)

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Starts a stroke, or picks with the right button.
      @param event  QMouseEvent
      @return None
      """
      cell = self.cell_at(event.position())
      if event.button() == QtCore.Qt.MouseButton.RightButton:   # pick; drag to pick a rectangle of metatiles
         self.picking = (cell, cell)
         self.update(self.cell_rect(cell).adjusted(-REPAINT_MARGIN, -REPAINT_MARGIN, REPAINT_MARGIN, REPAINT_MARGIN))
         return
      if event.button() != QtCore.Qt.MouseButton.LeftButton:
         return
      tool = self.panel.tool()
      ext = self.panel.extension_tool()
      if tool in ("fill", "pick") or (ext is not None and ext.stroke == "click"):
         self.panel.apply_tool(tool, [cell])
         return
      shift = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
      if tool == "rect" or (ext is not None and (ext.stroke == "rect" or shift)):
         self.corner = cell
         self.stroke = {}
      else:
         self.corner = None
         self.stroke = {cell: True}
         self.last = cell
      self.anchor = cell
      self.update_cells(cell)

   def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Extends the stroke and tracks the hovered cell.
      @param event  QMouseEvent
      @return None
      """
      cell = self.cell_at(event.position())
      if cell == self.hover:
         return
      old = self.hover
      self.hover = cell
      self.panel.hovered(cell)
      self.update_cells(old, cell)
      if self.picking is not None:
         start, last = self.picking[0], self.picking[1]
         self.picking = (start, cell)
         self.update(self.pick_area(start, last).united(self.pick_area(start, cell)).adjusted(
            -REPAINT_MARGIN, -REPAINT_MARGIN, REPAINT_MARGIN, REPAINT_MARGIN))
         return
      if self.anchor is None:
         return
      if self.corner is not None:   # rectangle: repaint the union of the old and new boxes
         before = self.rect_cells()
         self.corner = cell
         after = self.rect_cells()
         x0, y0 = min(before[0], after[0]), min(before[1], after[1])
         x1, y1 = max(before[AREA_W], after[AREA_W]), max(before[AREA_H], after[AREA_H])
         self.update(self.cell_rect((x0, y0)).united(self.cell_rect((x1, y1))))
         return
      line = list(line_cells(self.last or cell, cell))   # fast drags skip cells: join them
      for c in line:
         self.stroke[c] = True
      self.last = cell
      self.update_cells(*line)

   def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Commits the stroke as one undo step.
      @param event  QMouseEvent
      @return None
      """
      if event.button() == QtCore.Qt.MouseButton.RightButton and self.picking is not None:
         (ax, ay), (bx, by) = self.picking
         self.picking = None
         if (ax, ay) == (bx, by):
            self.panel.pick((ax, ay))
         else:
            self.panel.pick_rect(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
         self.update()
         return
      if event.button() != QtCore.Qt.MouseButton.LeftButton or self.anchor is None:
         return
      box = self.rect_cells()
      if box is not None:
         cells = [(x, y) for y in range(box[1], box[AREA_H] + 1) for x in range(box[0], box[AREA_W] + 1)]
      else:
         cells = list(self.stroke)
      self.anchor = self.corner = self.last = None
      self.stroke = {}
      if cells:
         self.panel.apply_tool(self.panel.tool(), cells)
      self.update()

   def leaveEvent(self, event: QtCore.QEvent) -> None:
      """!Clears the hover marker.
      @param event  QEvent
      @return None
      """
      self.hover = None
      self.update()


class MapPanel(EditorPanel):
   """!Edits the maps of the host's Project.

   @var current_layer
   The layer being painted: a BG number, ATTRIBUTES, or None (the back tile
   layer, chosen on refresh).
   """

   ## See EditorPanel.panel_id.
   panel_id = "map"
   ## See EditorPanel.title.
   title = "Map"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## "tileset/metatile" -> QImage (transparent background) for the map's tilesets.
      self.images = {}
      ## The edited map's dictionary, resolved (I2: an "all" dictionary lists every metatile of its tilesets).
      self.names = []
      ## Per tileset: (tileset revision, world revision) -> its pictures, so painting never recompiles.
      self._tileset_images = {}
      ## Map being edited, or None.
      self.map_name = None
      ## The last edit from this tab changed the world file (Undo goes there first).
      self._world_last = False
      ## The chosen metatile, "tileset/metatile", or None (the top-left one of a multi-metatile stamp).
      self.current_name = None
      ## Several metatiles picked together: rows of "tileset/metatile" (None: leave the cell alone), or None.
      self.stamp = None
      ## True while the panel fills its own widgets.
      self._filling = False
      ## Dictionary / tileset state the images were built for.
      self._built_for = None
      ## Tile and palette use from the last compile, for the summary.
      self._stats = ""
      ## The last compile's error line, or "".
      self._compile_text = ""
      ## Map the canvas area was last set for (scroll compensation).
      self._shown_map = None

      # -- left: the maps, in their groups
      ## Maps of the world, in their groups.
      self.map_list = MapTree(self)
      self.map_list.currentItemChanged.connect(lambda item, _old: self._map_chosen(item))
      ## Filters the map list by name.
      self.map_filter = QtWidgets.QLineEdit()
      self.map_filter.setPlaceholderText("Filter maps")
      self.map_filter.setClearButtonEnabled(True)
      self.map_filter.textChanged.connect(lambda text: self._filter_maps(text))
      ## Every metatile of the map's tilesets.
      self.palette = MetatileGrid(lambda key: self._metatile_chosen(key),
                                  on_block=lambda rows: self._block_chosen(rows))
      self.palette.setToolTip("Click a metatile, or drag (or shift-click) to pick several and paint them together")
      ## The map's tilesets, as text.
      self.tilesets_label = QtWidgets.QLabel()
      self.tilesets_label.setWordWrap(True)
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Maps"))
      left.addWidget(self.map_filter)
      left.addWidget(self.map_list, 1)
      ## The chosen map's size and VRAM use.
      self.summary = QtWidgets.QLabel()
      self.summary.setWordWrap(True)
      left.addWidget(self.summary)
      new_row = QtWidgets.QHBoxLayout()
      new_row.addWidget(button("New map...", lambda: self.new_map(self.map_list.group_at(self.map_list.currentItem())),
                               "A blank map, in the group of the map or group chosen in the list"))
      new_row.addWidget(button("New group...", lambda: self.new_group(self.map_list.group_at(
         self.map_list.currentItem())), "A map group (folder), inside the group chosen in the list"))
      left.addLayout(new_row)

      # -- center: tools and canvas
      ## Tool buttons.
      self.tool_group = QtWidgets.QButtonGroup(self)
      bar = QtWidgets.QHBoxLayout()
      for i, (tid, label, tip) in enumerate(TOOLS):
         b = QtWidgets.QToolButton()
         b.setText(label)
         b.setToolTip(tip)
         b.setCheckable(True)
         b.setChecked(i == 0)
         self.tool_group.addButton(b, i)
         bar.addWidget(b)
      ## Extension tools (plugins.MapTool), after the built-in ones (see _sync_extensions()).
      self._ext_tools = []
      ## Their buttons.
      self._ext_buttons = []
      ## Where extension tool buttons go.
      self._tool_bar = bar
      bar.addStretch(1)
      ## Settings of the chosen extension tool (MapTool.options()).
      self.tool_options = QtWidgets.QStackedWidget()
      self.tool_options.addWidget(QtWidgets.QWidget())
      self.tool_options.setVisible(False)
      ## Options widgets built so far: tool id -> page index.
      self._option_pages = {}
      self.tool_group.idToggled.connect(lambda *a: self._tool_chosen())
      ## Attribute overlay or an extension's (plugins.MapOverlay).
      self.overlay_choice = QtWidgets.QComboBox()
      self.overlay_choice.setToolTip("What is drawn over painted cells: the attribute chosen on the attribute layer, "
                                     "or an extension's overlay")
      self.overlay_choice.currentIndexChanged.connect(lambda *a: self.canvas.update())
      ## Grid overlay toggle.
      self.show_grid = QtWidgets.QCheckBox("Grid")
      self.show_grid.setChecked(True)
      ## Fade the tile layers in front of the current one.
      self.fade_front = QtWidgets.QCheckBox("Fade layers in front")
      self.fade_front.setToolTip("Draw the layers in front of the one being painted see-through")
      ## Map zoom, in percent.
      self.zoom = QtWidgets.QComboBox()
      self.zoom.addItems([f"{z}%" for z in ZOOM_LEVELS])
      self.zoom.setCurrentIndex(ZOOM_LEVELS.index(DEFAULT_ZOOM))
      self.zoom.setToolTip("How large the map is drawn: 100% is one screen pixel per map pixel")
      view_bar = QtWidgets.QHBoxLayout()
      for w in (self.show_grid, self.fade_front):
         view_bar.addWidget(w)
         if isinstance(w, QtWidgets.QCheckBox):
            w.toggled.connect(lambda *a: self.canvas.update())
      view_bar.addWidget(QtWidgets.QLabel("Overlay:"))
      view_bar.addWidget(self.overlay_choice)
      view_bar.addStretch(1)
      ## The map drawing.
      self.canvas = MapCanvas(self)
      self.zoom.currentIndexChanged.connect(lambda i: self._zoom_changed(ZOOM_LEVELS[i]))
      ## Scroll area around the canvas.
      self.scroll = QtWidgets.QScrollArea()
      self.scroll.setWidget(self.canvas)
      self.scroll.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
      ## Status of the hovered cell.
      self.cell_info = QtWidgets.QLabel()
      # Long lines (extension hover text) must not widen the window.
      self.cell_info.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
      middle = QtWidgets.QVBoxLayout()
      middle.addLayout(bar)
      middle.addWidget(self.tool_options)
      middle.addLayout(view_bar)
      middle.addWidget(self.scroll, 1)
      status_row = QtWidgets.QHBoxLayout()
      status_row.addWidget(self.cell_info, 1)
      zoom_label = QtWidgets.QLabel("Zoom:")
      zoom_label.setBuddy(self.zoom)
      status_row.addWidget(zoom_label)
      status_row.addWidget(self.zoom)
      middle.addLayout(status_row)

      # -- right: layers, attributes, map properties
      ## Hidden tile layers, by BG number.
      self.hidden_bgs = set()
      self.current_layer = None
      ## The attribute layer, then the tile layers front to back; the check box shows or hides.
      self.layer_list = QtWidgets.QListWidget()
      self.layer_list.setToolTip("The layer being painted. Unticking a tile layer hides it; unticking "
                                 "Attributes hides the attribute overlay")
      self.layer_list.currentRowChanged.connect(lambda *a: self._layer_chosen(*a))
      self.layer_list.setMaximumHeight(LAYER_LIST_HEIGHT)
      self.layer_list.itemChanged.connect(lambda *a: self._layer_ticked(*a))
      ## Shows the attribute overlay (the Attributes row's tick).
      self.show_attributes = True
      ## The attribute painted and shown.
      self.attr_field = QtWidgets.QComboBox()
      for _f, label in ATTRIBUTE_FIELDS:
         self.attr_field.addItem(label)
      self.attr_field.currentIndexChanged.connect(lambda *a: self._field_chosen())
      ## Value of collision, elevation or env.
      self.attr_value = QtWidgets.QSpinBox()
      self.attr_value.setRange(0, maps.cell_fields()[COLLISION_FIELD][0])
      self.attr_value.setValue(1)
      ## Behavior to paint (world behavior names).
      self.attr_behavior = QtWidgets.QComboBox()
      ## Encounter on or off.
      self.attr_encounter = QtWidgets.QComboBox()
      self.attr_encounter.addItems(["Encounters", "No encounters"])
      attr_page = QtWidgets.QWidget()
      al = QtWidgets.QFormLayout(attr_page)
      al.setContentsMargins(0, 0, 0, 0)
      al.addRow("Attribute", self.attr_field)
      al.addRow("Value", self.attr_value)
      al.addRow("Behavior", self.attr_behavior)
      al.addRow("Encounter", self.attr_encounter)
      ## The edited layer's BG.
      self.layer_bg = QtWidgets.QComboBox()
      self.layer_bg.addItems([f"BG{i}" for i in range(maps.max_layers())])
      self.layer_bg.setToolTip("The GBA background this layer is drawn on (BG0 is shared with text windows)")
      self.layer_bg.activated.connect(lambda *a: self._layer_edited())
      ## The edited layer's draw priority.
      self.layer_priority = QtWidgets.QSpinBox()
      self.layer_priority.setRange(0, maps.max_priority())
      self.layer_priority.setToolTip("Draw priority: 0 is in front; on a tie the lower BG is in front")
      self.layer_priority.valueChanged.connect(lambda *a: self._layer_edited())
      ## The edited layer's purpose (for tools; it draws the same).
      self.layer_purpose = QtWidgets.QComboBox()
      self.layer_purpose.addItems(list(maps.PURPOSES))
      self.layer_purpose.activated.connect(lambda *a: self._layer_edited())
      layer_page = QtWidgets.QWidget()
      ll = QtWidgets.QFormLayout(layer_page)
      ll.setContentsMargins(0, 0, 0, 0)
      ll.addRow("Background", self.layer_bg)
      ll.addRow("Priority", self.layer_priority)
      ll.addRow("Purpose", self.layer_purpose)
      ## Attribute controls or layer properties, by the current layer.
      self.layer_pages = QtWidgets.QStackedWidget()
      self.layer_pages.addWidget(attr_page)
      self.layer_pages.addWidget(layer_page)
      layer_buttons = QtWidgets.QHBoxLayout()
      layer_buttons.addWidget(button("Add layer", lambda: self.add_layer(), "Add a tile layer on a free BG"))
      layer_buttons.addWidget(button("Remove layer", lambda: self.remove_layer(),
                                     "Remove the current tile layer and everything painted on it"))
      ## Compile result for this map.
      self.errors = QtWidgets.QLabel()
      self.errors.setWordWrap(True)
      ## Border width.
      self.border_w = QtWidgets.QSpinBox()
      self.border_w.setRange(1, maps.max_border())
      ## Border height.
      self.border_h = QtWidgets.QSpinBox()
      self.border_h.setRange(1, maps.max_border())
      right = QtWidgets.QVBoxLayout()
      right.addWidget(QtWidgets.QLabel("Layers (front to back)"))
      right.addWidget(self.layer_list)
      right.addLayout(layer_buttons)
      right.addWidget(self.layer_pages)
      ## The border pattern, painted like the map.
      self.border_canvas = BorderCanvas(self)
      self.border_w.valueChanged.connect(lambda *a: self.resize_border())
      self.border_h.valueChanged.connect(lambda *a: self.resize_border())
      border_title = QtWidgets.QLabel("Border (fills the space outside the map; painted on the current layer)")
      border_tip = ("The border has one pattern per tile layer. This shows every shown layer and paints the "
                    "layer selected in Layers above (pick another layer there to paint its pattern); it has no "
                    "attributes and is always blocked.")
      border_title.setToolTip(border_tip)
      self.border_canvas.setToolTip(border_tip)
      right.addWidget(border_title)
      right.addWidget(self.border_canvas, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
      right.addWidget(QtWidgets.QLabel("Pattern size (metatiles)"))
      size_row = QtWidgets.QHBoxLayout()
      size_row.addWidget(self.border_w)
      size_row.addWidget(QtWidgets.QLabel("x"))
      size_row.addWidget(self.border_h)
      right.addLayout(size_row)
      right.addWidget(button("Backdrop color...", lambda: self.pick_backdrop()))
      right.addWidget(button("Remove empty chunks", lambda: self.trim()))
      trow = QtWidgets.QHBoxLayout()
      trow.addWidget(self.tilesets_label, 1)
      trow.addWidget(button("Tilesets...", lambda: self.choose_tilesets(),
                            "Choose the tilesets this map draws from; the palette shows all their metatiles"))
      right.addSpacing(TILESETS_SPACING)
      right.addLayout(trow)
      ## I2: the map's dictionary is every metatile of its tilesets ("metatiles": "all"), not the ones painted.
      self.all_metatiles = QtWidgets.QCheckBox("Dictionary: every metatile of the tilesets")
      self.all_metatiles.setToolTip("On: the map's cells index all metatiles of its tilesets in order (\"metatiles\": "
                                    "\"all\", as imported maps are; up to the engine's limit). Off: the dictionary "
                                    "lists the metatiles painted. Switching renumbers the cells; they show the same.")
      self.all_metatiles.toggled.connect(lambda on: self.set_all_metatiles(on))
      right.addWidget(self.all_metatiles)
      right.addWidget(grid_area(self.palette), 1)
      right.addWidget(self.errors)

      layout = QtWidgets.QHBoxLayout(self)
      for part, stretch in ((left, LIST_STRETCH), (middle, MAP_STRETCH), (right, SIDE_STRETCH)):
         box = QtWidgets.QWidget()
         box.setLayout(part)
         layout.addWidget(box, stretch)
      ## (revisions, map) the extension diagnostics were last found for.
      self._diag_key = None
      ## The extension diagnostics last shown, as text.
      self._diag_text = ""
      self._sync_extensions()
      self._field_chosen()

   # -- documents ---------------------------------------------------------------------

   def project(self) -> Project | None:
      """!The host's project.
      @return Project, or None
      """
      return self.host_project()

   def map_doc(self) -> Document | None:
      """!The edited map's Document.
      @return Document, or None
      """
      p = self.project()
      if p is None or self.map_name is None or self.map_name not in p.map_names():
         return None
      return p.map(self.map_name)

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the edited map, or the world file right after
      a change to it from this tab (map groups, a new map), so Undo takes
      that back first.
      @return Document, or None
      """
      p = self.project()
      if p is not None and self._world_last and (p.world.undo_label() or p.world.redo_label()):
         return p.world
      return self.map_doc()

   def _run_edit(self, label: str, fn: Callable[[], object], doc: Document) -> bool:
      """!Runs an edit through the host, remembering whether it changed the world file (for Undo).
      @param label  undo label
      @param fn     callable doing the change
      @param doc    the Document it changes
      @return True when it went through
      """
      p = self.project()
      self._world_last = p is not None and doc is p.world
      return self.host.run_edit(label, fn, doc)

   def document_replaced(self) -> None:
      """!Another world was opened: forget images built for the old one.
      @return None
      """
      self._diag_key = None
      self._sync_extensions()
      self._built_for = None
      self._shown_map = None
      self.images = {}
      self._tileset_images = {}
      self.map_name = None
      self.current_name = None
      self.hidden_bgs = set()
      self.current_layer = None
      self.refresh()

   def tool(self) -> str:
      """!The chosen tool id.
      @return one of TOOLS' ids
      """
      i = self.tool_group.checkedId()
      if 0 <= i < len(TOOLS):
         return TOOLS[i][0]
      if 0 <= i - len(TOOLS) < len(self._ext_tools):   # extension tool buttons come after the built-in ones
         return self._ext_tools[i - len(TOOLS)].id
      return "paint"

   # -- extensions (D-10) ---------------------------------------------------------------

   def extensions(self) -> Registry:
      """!The host's plugin registry.
      @return plugins.Registry (empty when the host has none)
      """
      reg = getattr(self.host, "extensions", None)
      return reg if reg is not None else Registry()

   def view(self) -> MapView:
      """!The edited map as extensions see it.
      @return plugins.MapView
      """
      run_edit = self._run_edit   # a local name: Doxygen misreads self._run_edit as a variable here
      return MapView(self.project(), self.map_name, run_edit, self.host.show_status)

   def extension_tool(self) -> MapTool | None:
      """!The chosen extension tool.
      @return plugins.MapTool, or None for a built-in tool
      """
      i = self.tool_group.checkedId() - len(TOOLS)
      return self._ext_tools[i] if 0 <= i < len(self._ext_tools) else None

   def extension_overlay_cell(self) -> Callable[[int, int, int | None], OverlayCell | None] | None:
      """!The chosen extension overlay's per-cell function for this repaint.
      @return callable(x, y, cell), or None (the attribute overlay)
      """
      i = self.overlay_choice.currentIndex() - 1   # entry 0 is the attribute overlay
      overlays = self.extensions().map_overlays()
      if not 0 <= i < len(overlays) or self.map_doc() is None:
         return None
      try:
         return overlays[i].prepare(self.view())
      except Exception as e:   # a broken overlay must not break painting
         self.host.show_status(f"overlay {overlays[i].title}: {e}")
         return None

   def _sync_extensions(self) -> None:
      """!Adds the registry's tools and overlays (after another world, with other plugins, was opened).
      @return None
      """
      reg = self.extensions()
      tools = reg.map_tools()
      if [id(t) for t in tools] != [id(t) for t in self._ext_tools]:
         if self.extension_tool() is not None:
            self.tool_group.button(0).setChecked(True)
         for b in self._ext_buttons:
            self.tool_group.removeButton(b)
            self._tool_bar.removeWidget(b)
            b.hide()
            b.deleteLater()
         self._ext_buttons, self._ext_tools = [], list(tools)
         while self.tool_options.count() > 1:
            w = self.tool_options.widget(1)
            self.tool_options.removeWidget(w)
            w.deleteLater()
         self._option_pages = {}
         for k, t in enumerate(tools):
            b = QtWidgets.QToolButton()
            b.setText(t.label)
            b.setToolTip(f"{t.tooltip} (extension {t.id.split('/')[0]})")
            b.setCheckable(True)
            self.tool_group.addButton(b, len(TOOLS) + k)
            self._tool_bar.insertWidget(len(TOOLS) + k, b)
            self._ext_buttons.append(b)
      titles = ["Attributes"] + [o.title for o in reg.map_overlays()]
      if [self.overlay_choice.itemText(i) for i in range(self.overlay_choice.count())] != titles:
         keep = self.overlay_choice.currentText()
         self.overlay_choice.blockSignals(True)
         self.overlay_choice.clear()
         self.overlay_choice.addItems(titles)
         self.overlay_choice.setCurrentIndex(titles.index(keep) if keep in titles else 0)
         self.overlay_choice.blockSignals(False)

   def _tool_chosen(self) -> None:
      """!Shows the chosen extension tool's options (built on first use).
      @return None
      """
      t = self.extension_tool()
      page = 0
      if t is not None:
         if t.id not in self._option_pages:
            try:
               w = t.options(self.tool_options)
            except Exception as e:
               self.host.show_status(f"tool {t.label}: {e}")
               w = None
            self._option_pages[t.id] = self.tool_options.addWidget(w) if w is not None else 0   # 0: no options
         page = self._option_pages[t.id]
      self.tool_options.setCurrentIndex(page)
      self.tool_options.setVisible(page != 0)
      self.canvas.update()

   def _extension_diagnostics(self) -> str:
      """!Validator findings about the edited map (warnings and errors), as text.
      @return text, or ""
      """
      p = self.project()
      # Validate again only after an edit somewhere in the world or on another map.
      key = (tuple((str(d.path), d.revision) for d in p.documents()), self.map_name)
      if key != self._diag_key:
         found = [d for d in self.extensions().validate(p, self.map_name) if d.level in ("error", "warning")
                  and d.map in (None, self.map_name)]
         self._diag_text = "\n".join(f"{d.level.capitalize()}: {d.message}" for d in found[:DIAGNOSTICS_SHOWN]) + \
             (f"\n... and {len(found) - DIAGNOSTICS_SHOWN} more" if len(found) > DIAGNOSTICS_SHOWN else "")
         self._diag_key = key
      return self._diag_text

   # -- refresh -------------------------------------------------------------------------

   def refresh(self) -> None:
      """!Re-reads the project: map list, palette, canvas.
      @return None
      """
      p = self.project()
      self._filling = True
      try:
         names = p.map_names() if p is not None else []
         if self.map_name not in names:
            self.map_name = names[0] if names else None
         if p is None:
            self.map_list.clear()
         else:
            self.map_list.fill(p.world.data, names, self.map_name)
      finally:
         self._filling = False
      self._rebuild()

   def tileset_pictures(self, name: str, context: Sequence[str] | None = None) -> Pictures:
      """!Pictures of every metatile of a tileset (compiled once per tileset change). I2: a fixed tileset's
      metatiles draw from what the tilesets loaded with it place, so they are drawn with the map's tilesets.
      @param name     tileset name
      @param context  the map's tilesets (used for a fixed tileset), or None
      @return [("tileset/metatile", QImage or None)], in tileset order
      """
      p = self.project()
      doc = p.tileset(name)
      fixed = isinstance(doc.data.get("place"), dict)
      ctx = tuple(context) if fixed and context is not None else None
      key = (doc.revision, p.world.revision, ctx, tuple(p.tileset(t).revision for t in ctx or ()))
      hit = self._tileset_images.get((name, ctx))
      if hit is not None and hit[0] == key:
         return hit[1]
      ts, preview, _error = p.compiled_tileset(name, list(ctx) if ctx is not None else None)
      pictures = []
      if ts is not None:
         images = mapview.metatile_images(preview, backdrop=False) if preview is not None else []
         for i, mt in enumerate(ts.metatiles):
            pictures.append((f"{name}/{mt}", to_qimage(*images[i]) if i < len(images) else None))
      else:   # not compiling: names only, drawn as placeholders
         pictures = [(f"{name}/{m.get('name')}", None) for m in doc.data.get("metatiles", [])]
      self._tileset_images[(name, ctx)] = (key, pictures)
      return pictures

   def map_tilesets(self) -> list[str]:
      """!The edited map's tilesets.
      @return list of names
      """
      p, doc = self.project(), self.map_doc()
      if doc is None:
         return []
      return [t for t in maps.tilesets_of(doc.data, p.tileset_names()) if t in p.tileset_names()]

   def _rebuild(self) -> None:
      """!Refreshes the palette from the map's tilesets, the properties and
      the canvas; compiles the map (when its dictionary or the tilesets
      changed) for the error line and the VRAM summary.
      @return None
      """
      p, doc = self.project(), self.map_doc()
      if doc is None:
         self.images = {}
         self.layer_list.clear()
         self.palette.set_sections([])
         self.tilesets_label.setText("")
         self.summary.setText("No map. Use New map...")
         self.canvas.set_area(NO_MAP_AREA)
         self.border_canvas.sync_size()
         return
      names = maps.dictionary(doc.data, p.metatile_names)
      self.names = names
      uses = self.map_tilesets()
      sections = []
      self.images = {}
      for t in uses:
         pictures = self.tileset_pictures(t, uses)
         self.images.update({k: img for k, img in pictures if img is not None})
         sections.append([(k, img, k) for k, img in pictures])
      for n in names:   # painted metatiles always draw, even from a tileset not listed (older maps)
         t = n.split("/", 1)[0]
         if n not in self.images and t in p.tileset_names():
            self.images.update({k: img for k, img in self.tileset_pictures(t) if img is not None})
      self.palette.set_sections(sections)
      keys = self.palette.keys()
      if self.stamp is not None and not all(n in self.images for row in self.stamp for n in row if n is not None):
         self.stamp = None   # a picked metatile is gone (or its tileset was left out)
      if self.current_name not in keys and self.stamp is None:
         self.current_name = keys[0] if keys else None
      if self.stamp is not None:
         self.palette.set_block(self.stamp)
      else:
         self.palette.set_current(self.current_name)
      self.tilesets_label.setText("Tilesets: " + (", ".join(uses) if uses else "none yet"))
      self._filling = True
      try:   # I2: the dictionary is every metatile of the tilesets ("all"), or the metatiles painted
         self.all_metatiles.setChecked(maps.uses_all(doc.data))
      finally:
         self._filling = False
      # Everything the compile result depends on: recompile only when one of these changed.
      key = (self.map_name, tuple(names), tuple((t, p.tileset(t).revision) for t in uses),
             p.world.revision, doc.data.get("backdrop"), repr(doc.data.get("layers")), repr(doc.data.get("behaviors")))
      if key != self._built_for:
         mp, error = p.compiled_map(self.map_name)
         self._compile_text = f"Not compiling: {error}" if error else ""
         self._stats = (f", {len(mp['tiles'])}/{maps.max_tiles()} tiles, {len(mp['palettes'])}/{maps.max_palettes()} "
                        f"palettes, {len(mp['anims'])}/{maps.max_animations()} animations") if mp else ""
         self._built_for = key
      diag = self._extension_diagnostics()
      text = "\n".join(t for t in (self._compile_text, diag) if t)
      self.errors.setText(text)
      self.errors.setStyleSheet("color: #c03030;" if self._compile_text or "Error:" in diag else
                                "color: #b07000;" if diag else "")
      self._filling = True
      try:
         self._fill_layers(doc)
         b = doc.data.get("border", {}).get("size", [1, 1])
         self.border_w.setValue(b[0])
         self.border_h.setValue(b[1])
         self.border_canvas.sync_size()
      finally:
         self._filling = False
      bnd = maps.bounds(doc.data)
      if bnd is None:
         area = EMPTY_AREA
      else:   # the painted bounds and a margin of unpainted cells around them
         area = (bnd[0] - VIEW_MARGIN, bnd[1] - VIEW_MARGIN, bnd[AREA_W] - bnd[0] + VIEW_MARGIN_SPAN,
                 bnd[AREA_H] - bnd[1] + VIEW_MARGIN_SPAN)
      chunks = len(doc.data.get("chunks", []))
      used = "every metatile of its tilesets" if maps.uses_all(doc.data) else "metatiles used"
      self.summary.setText(f"{self.map_name}: {chunks} chunks, {len(maps.layers_of(doc.data))} tile layers, "
                           f"{len(names)} {used} (of {maps.max_metatiles()}){self._stats}")
      old = self.canvas.area
      self.canvas.set_area(area)
      if self._shown_map == self.map_name and (old[0], old[1]) != (area[0], area[1]):
         # A chunk was added left of / above the view: keep the map still under the cursor.
         step = self.canvas.cell()
         h, v = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
         h.setValue(h.value() + (old[0] - area[0]) * step)
         v.setValue(v.value() + (old[1] - area[1]) * step)
      self._shown_map = self.map_name
      self.canvas.update()

   def _zoom_changed(self, percent: int) -> None:
      """!Zooms the map, keeping the middle of the view where it was.
      @param percent  one of ZOOM_LEVELS
      @return None
      """
      h, v = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
      vw, vh = self.scroll.viewport().width(), self.scroll.viewport().height()
      # The view's middle as a fraction of the canvas, which stays the same at the new zoom.
      cx = (h.value() + vw / HALF) / max(1, self.canvas.width())
      cy = (v.value() + vh / HALF) / max(1, self.canvas.height())
      self.canvas.set_zoom(percent)
      h.setValue(round(cx * self.canvas.width() - vw / HALF))
      v.setValue(round(cy * self.canvas.height() - vh / HALF))

   def select_map(self, name: str) -> None:
      """!Shows a map (as if picked in the map list).
      @param name  map name
      @return None
      """
      self.map_name = name
      self.refresh()
      self.host.selection_changed()

   def _filter_maps(self, text: str) -> None:
      """!The map filter changed.
      @param text  filter text
      @return None
      """
      self.map_list.filter = text.strip().lower()
      p = self.project()
      if p is not None:
         self.map_list.fill(p.world.data, p.map_names(), self.map_name)

   def _map_chosen(self, item: QtWidgets.QTreeWidgetItem | None) -> None:
      """!Another item was picked in the map list (groups only open and close).
      @param item  QTreeWidgetItem, or None
      @return None
      """
      node = self.map_list.node(item)
      if self._filling or node is None or node[0] != "map" or node[1] == self.map_name:
         return
      self.map_name = node[1]
      self._world_last = False
      self._built_for = None
      self._rebuild()
      self.host.selection_changed()

   def _metatile_chosen(self, key: str) -> None:
      """!A palette entry was picked.
      @param key  "tileset/metatile"
      @return None
      """
      self.current_name = key
      self.stamp = None
      self.canvas.update()

   def _block_chosen(self, rows: Sequence[Sequence[str | None]]) -> None:
      """!Several palette entries were picked together.
      @param rows  rows of "tileset/metatile" (None past the end of a tileset's entries)
      @return None
      """
      keys = [k for row in rows for k in row if k is not None]
      if not keys:
         return
      self.current_name = keys[0]
      self.stamp = [list(row) for row in rows] if len(keys) > 1 else None
      self.canvas.update()

   def paint_stamp(self) -> Stamp | None:
      """!What Paint puts down on the current tile layer.
      @return rows of "tileset/metatile" (None: leave alone), or None (no metatile, attribute layer, or
              another tool)
      """
      if self.layer_index() is None or self.tool() not in ("paint", "rect", "fill"):
         return None
      if self.stamp is not None:
         return self.stamp
      return [[self.current_name]] if self.current_name is not None else None

   def stamp_size(self) -> tuple[int, int]:
      """!The stamp's size for Paint's preview.
      @return (w, h) in metatiles
      """
      stamp = self.paint_stamp() if self.tool() == "paint" else None
      return (max(len(r) for r in stamp), len(stamp)) if stamp else (1, 1)

   def stroke_footprint(self, stroke: Collection[Cell]) -> list[Cell]:
      """!The cells a Paint stroke covers (each stroke cell gets the whole stamp).
      @param stroke  stroke cells, in order
      @return list of (x, y)
      """
      stamp = self.paint_stamp() if self.tool() == "paint" else None
      if not stroke or stamp is None or (len(stamp), len(stamp[0])) == (1, 1):
         return list(stroke)
      seen = {}   # a dict keeps the cells in stroke order, once each
      for (x, y) in stroke:
         for c in maps.stamp_cells(stamp, x, y):
            seen[c] = True
      return list(seen)

   def hovered(self, cell: Cell) -> None:
      """!Shows the hovered cell's data.
      @param cell  (x, y)
      @return None
      """
      doc = self.map_doc()
      if doc is None:
         return
      x, y = cell
      v = maps.get(doc.data, x, y)
      if v is None:
         self.cell_info.setText(f"{x}, {y}: unpainted (border, blocked)")
         return
      names = self.names
      parts = []
      layers = maps.layers_of(doc.data)
      for k in reversed(maps.draw_order(doc.data)):   # front first, like the layer list
         i = maps.get_tile(doc.data, k, x, y)
         if i is not None:
            parts.append(f"BG{layers[k].get('bg')} {names[i] if i < len(names) else '?'}")
      a = maps.unpack(v)
      beh = maps.behavior_name(doc.data, v, self.project().behavior_names())
      attrs = f"{beh}, collision {a['collision']}, elevation {a['elevation']}" + \
          (f", encounters (slot {a['slot']})" if a["encounter"] else "") + (f", env {a['env']}" if a["env"] else "")
      extra = []
      for h in self.extensions().hover_texts():
         try:
            t = h(self.view(), x, y, v)
         except Exception as e:   # a broken extension must not break hovering
            t = f"({e})"
         if t:
            extra.append(t)
      self.cell_info.setText(f"{x}, {y}: {', '.join(parts) or 'no metatiles'}  |  {attrs}" +
                             "".join(f"  |  {t}" for t in extra))

   # -- layers and attributes -----------------------------------------------------------

   def layer_index(self) -> int | None:
      """!The current tile layer.
      @return layer index, or None on the attribute layer (or without the layer)
      """
      doc = self.map_doc()
      if doc is None or self.current_layer == ATTRIBUTES:
         return None
      for i, ly in enumerate(maps.layers_of(doc.data)):
         if ly.get("bg") == self.current_layer:
            return i
      return None

   def faded_layers(self) -> set[int]:
      """!Tile layers drawn see-through: those in front of the current one,
      when "Fade layers in front" is on.
      @return set of layer indices
      """
      doc, k = self.map_doc(), self.layer_index()
      if doc is None or k is None or not self.fade_front.isChecked():
         return set()
      order = maps.draw_order(doc.data)
      return set(order[order.index(k) + 1:])

   def overlay_field(self) -> str | None:
      """!The attribute drawn over painted cells.
      @return one of maps.cell_fields(), or None when hidden
      """
      if not self.show_attributes:
         return None
      return ATTRIBUTE_FIELDS[max(0, self.attr_field.currentIndex())][0]

   def behavior_short(self, index: int) -> str:
      """!A behavior dictionary entry's short name, for the overlay.
      @param index  the map's behavior index
      @return up to 4 letters
      """
      doc = self.map_doc()
      names = maps.behaviors_of(doc.data, self.project().behavior_names()) if doc is not None else []
      return names[index][:BEHAVIOR_SHORT_LETTERS] if index < len(names) else "?"

   def attribute_value(self) -> tuple[str, str | bool | int | None]:
      """!The attribute value the tools paint.
      @return (field, value): behavior as a world behavior name, encounter as bool, the rest as int
      """
      field = ATTRIBUTE_FIELDS[max(0, self.attr_field.currentIndex())][0]
      if field == "behavior":
         return field, self.attr_behavior.currentText() or None
      if field == "encounter":
         return field, self.attr_encounter.currentIndex() == 0
      return field, self.attr_value.value()

   def _field_chosen(self) -> None:
      """!The attribute chooser changed: show the matching value widget.
      @return None
      """
      field = ATTRIBUTE_FIELDS[max(0, self.attr_field.currentIndex())][0]
      top = maps.cell_fields()[field][0] if field in VALUE_FIELDS else None
      self.attr_value.setEnabled(top is not None)
      if top is not None:
         self.attr_value.setRange(0, top)
      self.attr_behavior.setEnabled(field == "behavior")
      self.attr_encounter.setEnabled(field == "encounter")
      self.canvas.update()

   def _fill_layers(self, doc: Document) -> None:
      """!Fills the layer list and the current layer's controls.
      @param doc  map Document
      @return None
      """
      layers = maps.layers_of(doc.data)
      # None (a new map or a removed layer) or a BG the map does not use: take the back tile layer.
      bgs = [ly.get("bg") for ly in layers]
      back = layers[maps.draw_order(doc.data)[0]].get("bg") if layers else ATTRIBUTES
      keep = self.current_layer == ATTRIBUTES or self.current_layer in bgs
      self.current_layer = self.current_layer if keep else back
      rows = [(ATTRIBUTES, "Attributes (collision, behavior, ...)", self.show_attributes)]
      for k in reversed(maps.draw_order(doc.data)):
         bg = layers[k].get("bg")
         rows.append((bg, maps.layer_label(doc.data, k), bg not in self.hidden_bgs))
      self.layer_list.clear()
      for key, label, shown in rows:
         item = QtWidgets.QListWidgetItem(label)
         item.setData(QtCore.Qt.ItemDataRole.UserRole, key)
         item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
         item.setCheckState(QtCore.Qt.CheckState.Checked if shown else QtCore.Qt.CheckState.Unchecked)
         self.layer_list.addItem(item)
         if key == self.current_layer:
            self.layer_list.setCurrentItem(item)
      k = self.layer_index()
      self.layer_pages.setCurrentIndex(0 if k is None else 1)
      if k is not None:
         ly = layers[k]
         self.layer_bg.setCurrentIndex(ly.get("bg", 0))
         self.layer_priority.setValue(maps.layer_priority(ly))
         purpose = ly.get("purpose", "terrain")
         self.layer_purpose.setCurrentIndex(maps.PURPOSES.index(purpose) if purpose in maps.PURPOSES else 0)
      names = self.project().behavior_names()
      if [self.attr_behavior.itemText(i) for i in range(self.attr_behavior.count())] != names:
         keep = self.attr_behavior.currentText()
         self.attr_behavior.clear()
         self.attr_behavior.addItems(names)
         if keep in names:
            self.attr_behavior.setCurrentIndex(names.index(keep))

   def _layer_chosen(self, row: int) -> None:
      """!Another layer was picked in the list.
      @param row  list row
      @return None
      """
      if self._filling or row < 0:
         return
      self.current_layer = self.layer_list.item(row).data(QtCore.Qt.ItemDataRole.UserRole)
      doc = self.map_doc()
      if doc is not None:
         self._filling = True
         try:
            self._fill_layers(doc)
         finally:
            self._filling = False
      self.canvas.update()
      self.border_canvas.update()

   def _layer_ticked(self, item: QtWidgets.QListWidgetItem) -> None:
      """!A layer's tick changed: show or hide it.
      @param item  QListWidgetItem
      @return None
      """
      if self._filling:
         return
      key = item.data(QtCore.Qt.ItemDataRole.UserRole)
      shown = item.checkState() == QtCore.Qt.CheckState.Checked
      if key == ATTRIBUTES:
         self.show_attributes = shown
      elif shown:
         self.hidden_bgs.discard(key)
      else:
         self.hidden_bgs.add(key)
      self.canvas.update()
      self.border_canvas.update()

   def _layer_edited(self) -> None:
      """!The current tile layer's BG, priority or purpose was changed.
      @return None
      """
      doc, k = self.map_doc(), self.layer_index()
      if self._filling or doc is None or k is None:
         return
      ly = maps.layers_of(doc.data)[k]
      bg, prio = self.layer_bg.currentIndex(), self.layer_priority.value()
      purpose = maps.PURPOSES[max(0, self.layer_purpose.currentIndex())]
      if (bg, prio, purpose) == (ly.get("bg"), maps.layer_priority(ly), ly.get("purpose", "terrain")):
         return
      if bg != ly.get("bg") and bg not in maps.free_bgs(doc.data):
         self.host.show_status(f"BG{bg} already holds another layer of this map")
         self._rebuild()
         return
      if bg != ly.get("bg") and ly.get("bg") in self.hidden_bgs:   # a hidden layer stays hidden on its new BG
         self.hidden_bgs.discard(ly.get("bg"))
         self.hidden_bgs.add(bg)
      self.current_layer = bg
      self._run_edit("Layer", lambda: maps.set_layer(doc, k, bg, prio, purpose), doc)

   def add_layer(self) -> None:
      """!Adds a tile layer on a BG the map does not use (asks which).
      @return None
      """
      doc = self.map_doc()
      if doc is None:
         self.explain("Add layer", "map")
         return
      free = maps.free_bgs(doc.data)
      if not free:
         self.host.show_status("The map already uses all four backgrounds")
         return
      labels = [f"BG{bg}" + (" (shared with text windows)" if bg == 0 else "") for bg in reversed(free)]
      choice, ok = QtWidgets.QInputDialog.getItem(self, "Add layer", "Background for the new layer:", labels, 0,
                                                  False)
      if not ok:
         return
      bg = int(choice[BG_DIGIT_INDEX])
      self.current_layer = bg
      self._run_edit("Add layer", lambda: maps.add_layer(doc, bg), doc)

   def remove_layer(self) -> None:
      """!Removes the current tile layer (after asking when something is painted on it).
      @return None
      """
      doc, k = self.map_doc(), self.layer_index()
      if doc is None:
         self.explain("Remove layer", "map")
         return
      if k is None:
         self.host.show_status("Pick a tile layer (not Attributes) to remove")
         return
      # Anything painted on layer k in any chunk (a chunk may hold fewer layers).
      used = any(v is not None for c in doc.data.get("chunks", []) for g in (c.get("layers") or [])[k:k + 1]
                 for r in g for v in r)
      if used:
         answer = QtWidgets.QMessageBox.question(self, "Remove layer",
                                                 f"Remove {maps.layer_label(doc.data, k)} and the metatiles painted "
                                                 "on it? (Undo brings it back.)")
         if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
      self.current_layer = None
      self._run_edit("Remove layer", lambda: maps.remove_layer(doc, k), doc)

   # -- edits -----------------------------------------------------------------------------

   def apply_tool(self, tool: str, cells: list[Cell]) -> None:
      """!Applies a tool to cells as one undo step: on the current tile layer
      with the chosen metatile, or on the attribute layer with the chosen
      attribute value.
      @param tool   tool id
      @param cells  list of (x, y)
      @return None
      """
      doc = self.map_doc()
      if doc is None:
         return
      if tool == "pick":
         self.pick(cells[0])
         return
      ext = self.extension_tool()
      if ext is not None:
         try:
            ext.apply(self.view(), cells)
         except Exception as e:   # an extension's error becomes a message, not a crash
            self.host.show_status(f"{ext.label}: {e}")
         return
      layer = self.layer_index()
      if tool == "erase":
         def run() -> None:
            """!Unpaints the cells, then drops what nothing uses any more."""
            for (x, y) in cells:
               maps.erase(doc, x, y)
            maps.trim(doc)
            maps.compact_dictionary(doc)
            maps.compact_behaviors(doc)
         self._run_edit("Erase", run, doc)
         return
      if layer is None:
         self.apply_attribute(tool, cells)
         return
      stamp = self.paint_stamp()
      if tool in ("paint", "rect", "fill") and stamp is None:
         self.host.show_status("Pick a metatile in the palette first (Tilesets... chooses what it shows)")
         return
      covered = self.stroke_footprint(cells) if tool == "paint" else cells
      ax, ay = cells[0]
      p = self.project()   # the stamp repeats from the stroke's first cell (a rectangle's top-left)

      def run() -> None:
         """!Clears, fills or stamps the cells on the layer."""
         if tool == "clear":
            for (x, y) in cells:
               maps.paint(doc, layer, x, y, None)
         else:
            pattern = [[None if n is None else maps.dictionary_index(doc, n, p.metatile_names) for n in row]
                       for row in stamp]
            if tool == "fill":
               maps.fill(doc, layer, ax, ay, None, pattern)
            else:
               maps.stamp(doc, layer, covered, pattern, ax, ay)
         maps.compact_dictionary(doc)   # metatiles nothing uses any more leave the dictionary
      labels = {"paint": "Paint", "rect": "Paint rectangle", "fill": "Fill", "clear": "Clear"}
      self._run_edit(labels.get(tool, tool), run, doc)

   def apply_attribute(self, tool: str, cells: list[Cell]) -> None:
      """!Paints the chosen attribute value on painted cells (one undo step).
      @param tool   tool id (Clear does nothing on the attribute layer)
      @param cells  list of (x, y)
      @return None
      """
      doc = self.map_doc()
      field, value = self.attribute_value()
      if tool == "clear":
         self.host.show_status("Clear removes metatiles; on the attribute layer, paint the value you want "
                               "(Erase unpaints cells)")
         return
      if value is None:
         self.host.show_status("The world has no behaviors")
         return
      world_behaviors = self.project().behavior_names()

      def run() -> None:
         """!Sets (or fills) the attribute on the cells."""
         v = maps.behavior_index(doc, value, world_behaviors) if field == "behavior" else value
         for (x, y) in cells:
            if tool == "fill":
               maps.fill_attributes(doc, x, y, field, v)
            else:
               maps.set_attributes(doc, x, y, **{field: v})
         maps.compact_behaviors(doc)
      if not any(maps.is_painted(doc.data, x, y) for (x, y) in cells):
         self.host.show_status("Attributes go on painted cells: paint a metatile there first (unpainted cells "
                               "show the border and are always blocked)")
         return
      self._run_edit(f"Set {field}", run, doc)

   def pick(self, cell: Cell) -> None:
      """!Takes the current layer's metatile of a cell as the chosen one (on
      the attribute layer: the chosen attribute's value).
      @param cell  (x, y)
      @return None
      """
      doc = self.map_doc()
      if doc is None:
         return
      v = maps.get(doc.data, *cell)
      if v is None:
         return
      layer = self.layer_index()
      if layer is not None:
         i = maps.get_tile(doc.data, layer, *cell)
         names = self.names
         if i is not None and i < len(names):
            self.current_name = names[i]
            self.stamp = None
            self.palette.set_current(self.current_name)
         return
      field = ATTRIBUTE_FIELDS[max(0, self.attr_field.currentIndex())][0]
      a = maps.unpack(v)
      if field == "behavior":
         name = maps.behavior_name(doc.data, v, self.project().behavior_names())
         if self.attr_behavior.findText(name) >= 0:
            self.attr_behavior.setCurrentIndex(self.attr_behavior.findText(name))
      elif field == "encounter":
         self.attr_encounter.setCurrentIndex(0 if a["encounter"] else 1)
      else:
         self.attr_value.setValue(a[field])

   def pick_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
      """!Takes the current layer's metatiles of a map rectangle as a
      stamp (cells with nothing on the layer are left alone when painting).
      @param x0  left column
      @param y0  top row
      @param x1  right column (inclusive)
      @param y1  bottom row (inclusive)
      @return None
      """
      doc, layer = self.map_doc(), self.layer_index()
      if doc is None:
         return
      if layer is None:
         self.pick((x0, y0))
         return
      names = self.names
      rows = []
      for y in range(y0, y1 + 1):
         row = []
         for x in range(x0, x1 + 1):
            i = maps.get_tile(doc.data, layer, x, y) if maps.is_painted(doc.data, x, y) else None
            row.append(names[i] if i is not None and i < len(names) else None)
         rows.append(row)
      if all(n is None for row in rows for n in row):
         self.host.show_status("Nothing on this layer there to pick")
         return
      self._block_chosen(rows)
      if self.stamp is not None:
         self.palette.set_block(self.stamp)
         w, h = x1 - x0 + 1, y1 - y0 + 1
         self.host.show_status(f"Picked {w}x{h} metatiles from the map: paint with them")
      else:
         self.palette.set_current(self.current_name)

   def _pick_tilesets(self, title: str, text: str, checked: Collection[str]) -> list[str] | None:
      """!Asks which of the world's tilesets to use.
      @param title    dialog title
      @param text     line above the list
      @param checked  names ticked at first
      @return list of names, or None if cancelled
      """
      p = self.project()
      dlg = QtWidgets.QDialog(self)
      dlg.setWindowTitle(title)
      lst = QtWidgets.QListWidget()
      for t in p.tileset_names():
         item = QtWidgets.QListWidgetItem(t)
         item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
         item.setCheckState(QtCore.Qt.CheckState.Checked if t in checked else QtCore.Qt.CheckState.Unchecked)
         lst.addItem(item)
      buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                           QtWidgets.QDialogButtonBox.StandardButton.Cancel)
      buttons.accepted.connect(lambda *a: dlg.accept())
      buttons.rejected.connect(lambda *a: dlg.reject())
      lay = QtWidgets.QVBoxLayout(dlg)
      lay.addWidget(QtWidgets.QLabel(text))
      lay.addWidget(lst)
      lay.addWidget(buttons)
      accepted = dlg.exec()
      picked = [lst.item(i).text() for i in range(lst.count())
                if lst.item(i).checkState() == QtCore.Qt.CheckState.Checked]
      dlg.deleteLater()
      return picked if accepted else None

   def new_group(self, parent: GroupPath = ()) -> None:
      """!Adds a map group (asks its name).
      @param parent  group to put it in (empty: top level)
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("New group")
         return
      name, ok = QtWidgets.QInputDialog.getText(self, "New group", "Group name:")
      if ok and name.strip():
         self._run_edit("New group", lambda: mapgroups.add_group(p.world, tuple(parent), name.strip()), p.world)

   def rename_group(self, path: GroupPath) -> None:
      """!Renames a map group (asks the new name).
      @param path  group path
      @return None
      """
      p = self.project()
      name, ok = QtWidgets.QInputDialog.getText(self, "Rename group", "Group name:", text=path[-1])
      if not ok or not name.strip() or name.strip() == path[-1]:
         return
      if self._run_edit("Rename group", lambda: mapgroups.rename_group(p.world, path, name.strip()), p.world):
         new = tuple(path[:-1]) + (name.strip(),)
         # Collapsed groups inside the renamed one keep their state under the new path.
         self.map_list.collapsed = {new + c[len(path):] if c[:len(path)] == tuple(path) else c
                                    for c in self.map_list.collapsed}

   def remove_group(self, path: GroupPath) -> None:
      """!Removes a map group; its maps and subgroups move up.
      @param path  group path
      @return None
      """
      p = self.project()
      self._run_edit("Remove group", lambda: mapgroups.remove_group(p.world, path), p.world)

   def move_node(self, node: Node, parent: GroupPath, index: int | None) -> None:
      """!Moves a map or a group in the group tree (from a drag or the menu).
      @param node    ("map", name) or ("group", path)
      @param parent  group path to move it into (empty: top level / ungrouped)
      @param index   position among its new siblings of the same kind, or None for the end
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("Move")
         return
      if node[0] == "map":
         self._run_edit("Move map", lambda: mapgroups.move_map(p.world, node[1], tuple(parent), index), p.world)
      elif tuple(parent) != tuple(node[1][:-1]) or index is not None:   # not dropped back where it is
         self._run_edit("Move group", lambda: mapgroups.move_group(p.world, node[1], tuple(parent), index),
                            p.world)

   def new_map(self, group: GroupPath = ()) -> None:
      """!Adds a blank map drawing from the tilesets chosen.
      @param group  map group to put it in (empty: ungrouped)
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("New map")
         return
      name, ok = QtWidgets.QInputDialog.getText(self, "New map", "Name:")
      if not ok or not name.strip():
         return
      uses = []
      if p.tileset_names():
         uses = self._pick_tilesets("New map", "Tilesets this map draws from:", p.tileset_names()[:1])
         if uses is None:
            return
      try:
         p.add_map(name.strip(), tilesets=uses, group=tuple(group) or None)
         self._world_last = True
      except Exception as e:   # DocumentError, ValueError
         QtWidgets.QMessageBox.warning(self, "New map", str(e))
         return
      self.map_name = name.strip()
      self.host.changed()

   def choose_tilesets(self) -> None:
      """!Chooses the tilesets the map draws from (the palette shows their metatiles).
      @return None
      """
      p, doc = self.project(), self.map_doc()
      if doc is None:
         self.explain("Tilesets", "map")
         return
      if not p.tileset_names():
         self.host.show_status("The world has no tilesets yet (Tileset tab: New tileset...)")
         return
      uses = self._pick_tilesets("Map tilesets", f"Tilesets {self.map_name} draws from:", self.map_tilesets())
      if uses is None:
         return
      names = p.tileset_names()
      self._run_edit("Map tilesets", lambda: maps.set_tilesets(doc, sorted(uses, key=names.index), names,
                                                               p.metatile_names), doc)

   def set_all_metatiles(self, on: bool) -> None:
      """!Makes the map's dictionary every metatile of its tilesets, or the metatiles painted (I2; one undo step).
      @param on  True for "all"
      @return None
      """
      p, doc = self.project(), self.map_doc()
      if self._filling or doc is None or on == maps.uses_all(doc.data):
         return
      change = maps.set_all if on else maps.set_listed
      if not self._run_edit("Dictionary", lambda: change(doc, p.metatile_names), doc):
         self._rebuild()   # refused: the box shows the map's dictionary again

   def border_stamp_cells(self, cells: Iterable[Cell], anchor: Cell) -> dict[Cell, str | None]:
      """!What painting border cells with the stamp puts where.
      @param cells   (x, y) border cells of the drag
      @param anchor  (x, y) where the drag started (the stamp repeats from there)
      @return {(x, y): "tileset/metatile"}, inside the pattern
      """
      doc = self.map_doc()
      stamp = self.stamp if self.stamp is not None else [[self.current_name]]
      if doc is None or self.current_name is None:
         return {}
      w, h, _pats = maps.border_of(doc.data)
      out = {}
      for (x, y) in cells:
         for (cx, cy) in maps.stamp_cells(stamp, x, y):
            if 0 <= cx < w and 0 <= cy < h:
               out[(cx, cy)] = maps.pattern_at(stamp, anchor[0], anchor[1], cx, cy)
      return out

   def paint_border(self, cells: list[Cell], blank: bool, anchor: Cell = (0, 0)) -> None:
      """!Paints border cells of the current tile layer with the chosen
      metatile (or the picked stamp, repeated from @p anchor), or clears
      them (one undo step).
      @param cells   (x, y) border cells
      @param blank   clear them (that layer shows nothing there; still impassable)
      @param anchor  (x, y) the stamp repeats from
      @return None
      """
      doc, layer = self.map_doc(), self.layer_index()
      if doc is None:
         return
      if layer is None:
         self.host.show_status("The border has no attributes (it is always blocked): pick a tile layer to paint it")
         return
      name = None if blank else self.current_name
      if not blank and name is None:
         self.host.show_status("Pick a metatile in the palette first")
         return
      if blank or self.stamp is None:
         self._run_edit("Clear border" if blank else "Paint border",
                            lambda: maps.paint_border(doc, layer, cells, name, self.project().metatile_names), doc)
         return
      placed = self.border_stamp_cells(cells, anchor)
      stamp = self.stamp
      self._run_edit("Paint border", lambda: maps.stamp_border(doc, layer, list(placed), stamp, *anchor,
                                                               metatiles_of=self.project().metatile_names), doc)

   def pick_border(self, x: int, y: int) -> None:
      """!Takes a border cell's metatile on the current layer as the chosen one.
      @param x  border column
      @param y  border row
      @return None
      """
      doc, layer = self.map_doc(), self.layer_index()
      if doc is None or layer is None:
         return
      w, _h, pats = maps.border_of(doc.data)
      i = pats[layer][y * w + x]   # patterns are rows first
      names = self.names
      if i is not None and i < len(names):
         self.current_name = names[i]
         self.stamp = None
         self.palette.set_current(self.current_name)

   def resize_border(self) -> None:
      """!The pattern size spin boxes changed.
      @return None
      """
      doc = self.map_doc()
      if self._filling or doc is None:
         return
      w, h = self.border_w.value(), self.border_h.value()
      if maps.border_of(doc.data)[:BORDER_SIZE_FIELDS] == (w, h):
         return
      self._run_edit("Border size", lambda: maps.resize_border(doc, w, h, self.project().metatile_names), doc)

   def pick_backdrop(self) -> None:
      """!Chooses the color behind every layer.
      @return None
      """
      doc = self.map_doc()
      if doc is None:
         self.explain("Backdrop color", "map")
         return
      old = doc.data.get("backdrop", "#000000")
      c = QtWidgets.QColorDialog.getColor(QtGui.QColor(old), self, "Backdrop")
      if c.isValid():
         value = "#{:02x}{:02x}{:02x}".format(c.red(), c.green(), c.blue())
         self._run_edit("Backdrop", lambda: doc.data.__setitem__("backdrop", value), doc)

   def trim(self) -> None:
      """!Removes chunks without painted cells.
      @return None
      """
      doc = self.map_doc()
      if doc is None:
         self.explain("Remove empty chunks", "map")
      else:
         self._run_edit("Remove empty chunks", lambda: maps.trim(doc), doc)


class BorderCanvas(QtWidgets.QWidget):
   """!The border pattern, painted like the map on the current tile layer
   (every shown layer is drawn): left click or drag uses the current tool
   (Paint and Rectangle paint, Fill fills every cell, Clear and Erase
   clear), right click picks a cell's metatile. A drag is one undo step.

   @var drag
   Cells of the drag in progress.
   """

   def __init__(self, panel: MapPanel) -> None:
      """!Creates the canvas.
      @param panel  owning MapPanel
      """
      super().__init__()
      ## The owning MapPanel.
      self.panel = panel
      self.drag = set()
      ## Where the drag started (a picked stamp repeats from there).
      self.drag_anchor = (0, 0)
      self.setMouseTracking(True)

   def cell_size(self) -> int:
      """!Screen pixels per border cell.
      @return pixels
      """
      return BORDER_CELL

   def pattern(self) -> tuple[int, int, list[list[int | None]]] | None:
      """!The edited map's border.
      @return (w, h, patterns per layer), or None without a map
      """
      doc = self.panel.map_doc()
      return maps.border_of(doc.data) if doc is not None else None

   def sync_size(self) -> None:
      """!Fits the widget to the pattern.
      @return None
      """
      b = self.pattern()
      w, h = (b[0], b[1]) if b else (1, 1)
      s = self.cell_size()
      self.setFixedSize(w * s + 1, h * s + 1)   # and the grid's last line
      self.update()

   def cell_at(self, pos: QtCore.QPointF) -> Cell:
      """!Border cell under a position.
      @param pos  QPointF
      @return (x, y)
      """
      s = self.cell_size()
      return int(pos.x()) // s, int(pos.y()) // s

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the pattern, the drag preview and a grid.
      @param event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
      p.fillRect(self.rect(), CANVAS_BACKGROUND)
      b, doc = self.pattern(), self.panel.map_doc()
      if b is None:
         p.end()
         return
      w, h, pats = b
      names = self.panel.names
      backdrop = QtGui.QColor(doc.data.get("backdrop", "#000000"))
      s = self.cell_size()
      tool = self.panel.tool()
      current = self.panel.layer_index()
      preview = {} if tool in ("erase", "clear") or not self.drag else \
          self.panel.border_stamp_cells(self.drag, self.drag_anchor)
      layers = maps.layers_of(doc.data)
      shown = [k for k in maps.draw_order(doc.data) if layers[k].get("bg") not in self.panel.hidden_bgs
               or k == current]
      for y in range(h):
         for x in range(w):
            r = QtCore.QRect(x * s, y * s, s, s)
            p.fillRect(r, backdrop)
            for k in shown:
               if k == current and preview.get((x, y)) is not None:   # the drag in progress
                  name = preview[(x, y)]
               elif (x, y) in self.drag and k == current:
                  name = None if tool in ("erase", "clear") else self.panel.current_name
               else:
                  i = pats[k][y * w + x]
                  name = names[i] if i is not None and i < len(names) else None
               img = self.panel.images.get(name) if name else None
               if img is not None:
                  p.drawImage(r, img)
      p.setPen(BORDER_GRID_COLOR)
      for x in range(w + 1):
         p.drawLine(x * s, 0, x * s, h * s)
      for y in range(h + 1):
         p.drawLine(0, y * s, w * s, y * s)
      p.end()

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Starts painting, or picks with the right button.
      @param event  QMouseEvent
      @return None
      """
      b = self.pattern()
      if b is None:
         return
      x, y = self.cell_at(event.position())
      if not (0 <= x < b[0] and 0 <= y < b[1]):
         return
      if event.button() == QtCore.Qt.MouseButton.RightButton:
         self.panel.pick_border(x, y)
         return
      if event.button() != QtCore.Qt.MouseButton.LeftButton:
         return
      tool = self.panel.tool()
      if tool == "pick":
         self.panel.pick_border(x, y)
         return
      if tool == "fill":
         self.panel.paint_border([(i, j) for j in range(b[1]) for i in range(b[0])], False)
         return
      if tool not in ("paint", "rect", "erase", "clear"):
         self.panel.host.show_status("The border takes Paint, Fill, Clear and Pick")
         return
      if self.panel.layer_index() is None:
         self.panel.host.show_status("Pick a tile layer to paint the border (it has no attributes: always blocked)")
         return
      self.drag.clear()
      self.drag.add((x, y))
      self.drag_anchor = (x, y)
      self.update()

   def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Extends the drag.
      @param event  QMouseEvent
      @return None
      """
      if not self.drag:
         return
      b = self.pattern()
      x, y = self.cell_at(event.position())
      if b is not None and 0 <= x < b[0] and 0 <= y < b[1] and (x, y) not in self.drag:
         self.drag.add((x, y))
         self.update()

   def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Commits the drag as one undo step.
      @param event  QMouseEvent
      @return None
      """
      if event.button() != QtCore.Qt.MouseButton.LeftButton or not self.drag:
         return
      cells = sorted(self.drag)
      self.drag.clear()
      self.panel.paint_border(cells, self.panel.tool() in ("erase", "clear"), self.drag_anchor)
      self.update()
