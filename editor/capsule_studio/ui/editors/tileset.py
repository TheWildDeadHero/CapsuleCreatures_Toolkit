"""!Tileset panel: sheets and metatiles (2x2 tiles, graphics only: a map
paints each one on any of its tile layers and paints behavior, collision and
the rest on its attribute layer). I2: fixed-placement tilesets (indexed
sheets shown in one of the tileset's banks, metatiles of raw entries, drawn
with the tilesets maps load together with them) and tile animations of either
kind (tileset_fixed.py)."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import mapview, tilesets
from ..panel import EditorPanel
from ..qtimage import load_rgba, to_qimage
from ..widgets import MetatileGrid, PixelView, button, grid_area
from .tileset_fixed import AnimationBox, FixedBox

if TYPE_CHECKING:
   from ...core.document import Document
   from ...core.tilesets import TileRef
   from ...core.world import Project
   from ..panel import PanelHost

## Parsed JSON: a sheet entry, a drag payload, a compiled preview map.
JsonDict = dict[str, Any]
## A sheet tile, (column, row) in tiles.
TilePos = tuple[int, int]

## File dialog filter for sheet images.
SHEET_FILTER = "Images (*.png *.bmp *.gif *.jpg *.jpeg *.ppm);;All files (*)"
## File dialog filter for indexed sheets (I2: palette PNGs).
INDEXED_FILTER = "Palette PNGs (*.png);;All files (*)"
## Layout stretch of the format tabs (fixed placement, animations) under the sheet.
FORMAT_TABS_STRETCH = 3
## Metatile slot names, in tile order.
SLOT_NAMES = ("top-left", "top-right", "bottom-left", "bottom-right")
## Tiles along a metatile's side (a metatile is 2x2 tiles; a picked block is at most that).
METATILE_SIDE = 2

## Screen pixels per sheet pixel in the sheet view.
SHEET_ZOOM = 3
## Size of the sheet view without a sheet, pixels.
EMPTY_SHEET_SIZE = 64
## Background behind the sheet.
SHEET_BACKGROUND = QtGui.QColor(60, 60, 70)
## Lines between the sheet's tiles.
TILE_GRID_COLOR = QtGui.QColor(0, 0, 0, 70)
## Lines between the sheet's 2x2 tile blocks (metatile size).
BLOCK_GRID_COLOR = QtGui.QColor(255, 220, 0, 160)
## Frame of the picked tiles (and of the maker's marked slots).
PICK_COLOR = QtGui.QColor(255, 255, 255)
## Width of that frame, pixels.
PICK_PEN_WIDTH = 2
## The drag cursor holds the dragged picture this fraction of its size in from the top left (1 / 4).
DRAG_HOTSPOT_DIVISOR = 4


class SheetView(QtWidgets.QWidget):
   """!A tile sheet at a whole-number zoom with a tile grid. Click picks a
   tile; dragging on the sheet picks a block of up to 2x2 tiles; dragging
   out of the sheet carries the picked tiles (drop them on the metatile
   maker or the metatile list).

   @var image
   The sheet QImage, or None.
   """

   def __init__(self, on_select: Callable[[int, int, int], object],
                drag_data: Callable[[], QtCore.QMimeData | None]) -> None:
      """!Creates the view.
      @param on_select  callable(top-left tile number, w, h) when tiles are picked
      @param drag_data  callable() -> QMimeData for the picked tiles, or None
      """
      super().__init__()
      self.image = None
      ## Screen pixels per sheet pixel.
      self.zoom = SHEET_ZOOM
      ## Top-left tile of the picked block, or None.
      self.selected = None
      ## Picked block size in tiles: [w, h], 1-2 each.
      self.size = [1, 1]
      ## Pick callback.
      self._on_select = on_select
      ## Drag payload callback.
      self._drag_data = drag_data
      ## Tile where the press started, (tx, ty), or None.
      self._anchor = None
      ## While picking a color: callable(x, y) given the clicked image pixel, else None.
      self.pick_pixel = None
      self.setToolTip("Click a tile, or drag across up to 2x2 tiles, then drag them out onto the metatile")

   def set_image(self, image: QtGui.QImage | None) -> None:
      """!Shows a sheet.
      @param image  QImage, or None
      @return None
      """
      self.image = image
      w = image.width() * self.zoom if image is not None else EMPTY_SHEET_SIZE
      h = image.height() * self.zoom if image is not None else EMPTY_SHEET_SIZE
      self.setFixedSize(w, h)
      self.update()

   def clear_selection(self) -> None:
      """!Forgets the picked block.
      @return None
      """
      self.selected = None
      self.size = [1, 1]
      self.update()

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the sheet, the grid and the picked block.
      @param event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.fillRect(self.rect(), SHEET_BACKGROUND)
      if self.image is None:
         p.end()
         return
      p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
      p.drawImage(self.rect(), self.image)
      s = mapview.TILE * self.zoom   # screen pixels per tile
      p.setPen(TILE_GRID_COLOR)
      for x in range(0, self.width() + 1, s):
         p.drawLine(x, 0, x, self.height())
      for y in range(0, self.height() + 1, s):
         p.drawLine(0, y, self.width(), y)
      p.setPen(BLOCK_GRID_COLOR)
      for x in range(0, self.width() + 1, METATILE_SIDE * s):
         p.drawLine(x, 0, x, self.height())
      for y in range(0, self.height() + 1, METATILE_SIDE * s):
         p.drawLine(0, y, self.width(), y)
      if self.selected is not None:
         cols = self.image.width() // mapview.TILE
         tx, ty = self.selected % cols, self.selected // cols   # tile number -> column, row
         p.setPen(QtGui.QPen(PICK_COLOR, PICK_PEN_WIDTH))
         p.drawRect(tx * s, ty * s, self.size[0] * s, self.size[1] * s)
      p.end()

   def _tile_at(self, pos: QtCore.QPointF) -> TilePos:
      """!Sheet tile under a position, clamped to the sheet.
      @param pos  QPointF
      @return (tx, ty)
      """
      s = mapview.TILE * self.zoom
      cols, rows = self.image.width() // mapview.TILE, self.image.height() // mapview.TILE
      tx = min(max(int(pos.x()) // s, 0), cols - 1)
      ty = min(max(int(pos.y()) // s, 0), rows - 1)
      return tx, ty

   def _select(self, a: TilePos, b: TilePos) -> None:
      """!Picks the block spanned by two tiles (at most 2x2, growing from @p a).
      @param a  (tx, ty) where the drag started
      @param b  (tx, ty) under the mouse
      @return None
      """
      cols = self.image.width() // mapview.TILE
      # Dragging left or up grows the block from the anchor by at most one tile that way.
      x0 = a[0] if b[0] >= a[0] else max(a[0] - 1, b[0])
      y0 = a[1] if b[1] >= a[1] else max(a[1] - 1, b[1])
      w = min(abs(b[0] - a[0]) + 1, METATILE_SIDE)
      h = min(abs(b[1] - a[1]) + 1, METATILE_SIDE)
      if (self.selected, self.size) == (y0 * cols + x0, [w, h]):
         return
      self.selected = y0 * cols + x0
      self.size = [w, h]
      self.update()
      self._on_select(self.selected, w, h)

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Picks the clicked tile (or the eyedropper's pixel).
      @param event  QMouseEvent
      @return None
      """
      if self.image is None or event.button() != QtCore.Qt.MouseButton.LeftButton:
         return
      if self.pick_pixel is not None:
         self.pick_pixel(int(event.position().x()) // self.zoom, int(event.position().y()) // self.zoom)
         return
      self._anchor = self._tile_at(event.position())
      self._select(self._anchor, self._anchor)

   def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Grows the picked block; leaving the visible sheet starts dragging it.
      @param event  QMouseEvent
      @return None
      """
      if self._anchor is None or self.image is None:
         return
      if not self.visibleRegion().boundingRect().contains(event.position().toPoint()):
         self._anchor = None
         data = self._drag_data()
         if data is not None:
            drag = QtGui.QDrag(self)
            drag.setMimeData(data)
            if data.hasImage():
               pm = QtGui.QPixmap.fromImage(data.imageData())
               drag.setPixmap(pm)
               drag.setHotSpot(QtCore.QPoint(pm.width() // DRAG_HOTSPOT_DIVISOR, pm.height() // DRAG_HOTSPOT_DIVISOR))
            drag.exec(QtCore.Qt.DropAction.CopyAction)
         return
      self._select(self._anchor, self._tile_at(event.position()))

   def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Ends the pick.
      @param event  QMouseEvent
      @return None
      """
      self._anchor = None


## Screen pixels per tile pixel in the metatile maker.
MAKER_ZOOM = 8
## Drag-and-drop format of sheet tiles: JSON {"tileset", "sheet", "index", "w", "h"}.
TILES_MIME = "application/x-capsule-sheet-tiles"
## 1-pixel lines across the maker: left of, between and right of its two tile columns (rows the same).
MAKER_LINES = 3
## Background of the maker.
MAKER_BACKGROUND = QtGui.QColor(30, 30, 36)
## Light squares of the maker's checkerboard (transparent pixels).
CHECKER_LIGHT = QtGui.QColor(200, 200, 205)
## Dark squares of the maker's checkerboard.
CHECKER_DARK = QtGui.QColor(160, 160, 168)
## Tile pixels per checkerboard square in the maker.
CHECKER_PIXELS = 2
## Squares alternate light and dark: every second one is light.
CHECKER_PERIOD = 2
## Shade over a slot a right-drag is about to clear.
CLEARING_SHADE = QtGui.QColor(30, 30, 36, 170)
## The maker's hint text without a metatile.
MAKER_HINT_COLOR = QtGui.QColor(230, 230, 230)

## Size of the transparent color swatch, pixels.
KEY_SWATCH_SIZE = 22
## Screen pixels per pixel of the metatile preview.
METATILE_PREVIEW_ZOOM = 2
## Size of the metatile preview, pixels (a 16x16 metatile at twice its size, and a margin).
METATILE_PREVIEW_SIZE = 36
## Layout stretch of the metatile list in its column.
METATILE_LIST_STRETCH = 2
## Layout stretch of the tileset and sheet lists column.
LISTS_STRETCH = 2
## Layout stretch of the sheet column.
SHEET_STRETCH = 5
## Layout stretch of the metatiles column.
METATILES_STRETCH = 4

## Map entry bit of a tile mirrored left to right (see mapview.draw_tile).
HFLIP_BIT = 0x400
## Map entry bit of a tile mirrored top to bottom.
VFLIP_BIT = 0x800
## Screen pixels per tile pixel in the picture a tile drag carries.
DRAG_ZOOM = 3
## Screen pixels per tile in that picture (TILE pixels at DRAG_ZOOM).
DRAG_TILE_PIXELS = 24


class MetatileCanvas(QtWidgets.QWidget):
   """!The metatile maker: the metatile as a 2x2 map of 8x8 tiles. Left
   click or drag stamps the picked sheet tiles (a picked block lands with
   its top-left tile under the mouse), right click or drag clears, H and V
   mirror the tile under the mouse, and sheet tiles dropped here land the
   same way. With no metatile chosen, painting or dropping starts a new one.
   A drag is one undo step.
   """

   def __init__(self, panel: TilesetPanel) -> None:
      """!Creates the maker.
      @param panel  owning TilesetPanel
      """
      super().__init__()
      ## The owning TilesetPanel.
      self.panel = panel
      ## Slot under the mouse, or None.
      self.hover = None
      ## Slots of the stroke in progress: slot -> True (stamp) or False (clear).
      self.stroke = {}
      ## Slot a dragged sheet block would land on, or None.
      self.drop_slot = None
      side = mapview.METATILE * MAKER_ZOOM + MAKER_LINES
      self.setFixedSize(side, side)
      self.setMouseTracking(True)
      self.setAcceptDrops(True)
      self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
      self.setToolTip("Drag tiles here from the sheet, or click to stamp the picked tiles. Right click clears a "
                      "tile; H / V mirror the tile under the mouse.")

   def slot_at(self, pos: QtCore.QPointF | QtCore.QPoint) -> int | None:
      """!Slot under a position.
      @param pos  QPointF / QPoint
      @return 0-3, or None outside
      """
      s = mapview.TILE * MAKER_ZOOM + 1   # a tile and the line after it
      x, y = int(pos.x()) - 1, int(pos.y()) - 1   # past the outer line
      if not (0 <= x < METATILE_SIDE * s and 0 <= y < METATILE_SIDE * s):
         return None
      return (y // s) * METATILE_SIDE + x // s

   def slot_rect(self, slot: int) -> QtCore.QRect:
      """!Screen rectangle of a slot (1-pixel gaps between tiles, like the map grid).
      @param slot  0-3
      @return QRect
      """
      s = mapview.TILE * MAKER_ZOOM
      # Slot bit 0 is the column, bit 1 the row.
      return QtCore.QRect(1 + (slot & 1) * (s + 1), 1 + (slot >> 1) * (s + 1), s, s)

   def footprint(self, slot: int) -> list[int]:
      """!Slots the picked block covers when placed on @p slot.
      @param slot  0-3
      @return list of slots
      """
      w, h = self.panel.tile_size if self.panel.tile is not None else (1, 1)
      sx, sy = slot & 1, slot >> 1
      # The block's tiles that fall inside the metatile (the rest hang off its right / bottom edge).
      return [(sy + dy) * METATILE_SIDE + sx + dx for dy in range(h) for dx in range(w)
              if sx + dx < METATILE_SIDE and sy + dy < METATILE_SIDE]

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the four tiles over a checkerboard, the hover and the stroke.
      @param event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
      p.fillRect(self.rect(), MAKER_BACKGROUND)
      refs = self.panel.metatile_tiles()
      pictures = self.panel.slot_pictures()
      light, dark = CHECKER_LIGHT, CHECKER_DARK
      c = MAKER_ZOOM * CHECKER_PIXELS   # screen pixels per checkerboard square
      for slot in range(mapview.METATILE_TILES):
         r = self.slot_rect(slot)
         for yy in range(0, r.height(), c):
            for xx in range(0, r.width(), c):
               p.fillRect(r.x() + xx, r.y() + yy, c, c,
                          light if (xx // c + yy // c) % CHECKER_PERIOD == 0 else dark)
         img = pictures[slot] if pictures is not None else None
         if img is not None:
            p.drawImage(r, img)
         if self.stroke.get(slot) is False:
            p.fillRect(r, CLEARING_SHADE)
      marked = set(self.stroke) | (set(self.footprint(self.drop_slot)) if self.drop_slot is not None else set())
      if self.hover is not None and not self.stroke and self.drop_slot is None:
         marked |= set(self.footprint(self.hover))
      p.setPen(QtGui.QPen(PICK_COLOR, PICK_PEN_WIDTH))
      for slot in marked:
         p.drawRect(self.slot_rect(slot).adjusted(1, 1, -1, -1))
      if refs is None and pictures is None:
         p.setPen(MAKER_HINT_COLOR)
         p.drawText(self.rect(), int(QtCore.Qt.AlignmentFlag.AlignCenter | QtCore.Qt.TextFlag.TextWordWrap),
                    "Drop tiles\nfor a new\nmetatile")
      p.end()

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Starts a stamp (left) or clear (right) stroke.
      @param event  QMouseEvent
      @return None
      """
      slot = self.slot_at(event.position())
      if slot is None:
         return
      if event.button() == QtCore.Qt.MouseButton.LeftButton:
         if self.panel.tile is None:
            self.panel.host.show_status("Pick a tile on the sheet first (or drag tiles here from it)")
            return
         self.stroke = {slot: True}
      elif event.button() == QtCore.Qt.MouseButton.RightButton:
         self.stroke = {slot: False}
      self.update()

   def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Extends the stroke and tracks the hovered slot.
      @param event  QMouseEvent
      @return None
      """
      slot = self.slot_at(event.position())
      if slot != self.hover:
         self.hover = slot
         self.update()
      if self.stroke and slot is not None and slot not in self.stroke:
         self.stroke[slot] = next(iter(self.stroke.values()))   # the stroke's kind: stamp or clear
         self.update()

   def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Commits the stroke as one undo step.
      @param event  QMouseEvent
      @return None
      """
      stroke, self.stroke = self.stroke, {}
      if stroke:
         self.panel.paint_slots(sorted(stroke), next(iter(stroke.values())))
      self.update()

   def leaveEvent(self, event: QtCore.QEvent) -> None:
      """!Clears the hover marker.
      @param event  QEvent
      @return None
      """
      self.hover = None
      self.update()

   def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
      """!H / V mirror the tile under the mouse.
      @param event  QKeyEvent
      @return None
      """
      axis = {QtCore.Qt.Key.Key_H: "h", QtCore.Qt.Key.Key_V: "v"}.get(event.key())
      if axis is None or self.hover is None:
         super().keyPressEvent(event)
         return
      self.panel.flip_slot(self.hover, axis)

   def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
      """!Accepts sheet tiles of the shown tileset.
      @param event  QDragEnterEvent
      @return None
      """
      if self.panel.dropped_tiles(event.mimeData()) is not None:
         event.acceptProposedAction()

   def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
      """!Shows where the dragged tiles would land.
      @param event  QDragMoveEvent
      @return None
      """
      slot = self.slot_at(event.position())
      if slot != self.drop_slot:
         self.drop_slot = slot
         self.update()
      if slot is None:
         event.ignore()
      else:
         event.acceptProposedAction()

   def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent) -> None:
      """!Forgets the drop marker.
      @param event  QDragLeaveEvent
      @return None
      """
      self.drop_slot = None
      self.update()

   def dropEvent(self, event: QtGui.QDropEvent) -> None:
      """!Places the dropped tiles.
      @param event  QDropEvent
      @return None
      """
      slot = self.slot_at(event.position())
      self.drop_slot = None
      tiles = self.panel.dropped_tiles(event.mimeData())
      if slot is None or tiles is None:
         return
      event.acceptProposedAction()
      self.panel.drop_block(tiles, slot)
      self.update()


class TilesetPanel(EditorPanel):
   """!Edits the tilesets of the host's Project.

   @var _filling
   True while the panel fills its own widgets (their signals are ignored).
   """

   ## See EditorPanel.panel_id.
   panel_id = "tileset"
   ## See EditorPanel.title.
   title = "Tileset"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Tileset being edited, or None.
      self.ts_name = None
      ## Sheet shown, or None.
      self.sheet_name = None
      ## Metatile being edited, or None.
      self.mt_name = None
      ## Picked sheet tile of the shown tileset (top-left of the picked block): (sheet, index), or None.
      self.tile = None
      ## Picked block size in tiles: [w, h].
      self.tile_size = [1, 1]
      ## Tile pictures: reference -> QImage, for the compiled tileset in _pictures_for.
      self._pictures = {}
      ## The compiled Tileset the pictures were drawn from.
      self._pictures_for = None
      ## I2: the bank they were drawn in.
      self._pictures_bank = None
      self._filling = False
      ## Last compiled (Tileset, preview map) of the shown tileset.
      self._compiled = (None, None)
      ## Tileset / revisions the sheet and metatile lists were filled for.
      self._filled_for = None
      ## A refresh was skipped while the panel was hidden.
      self._stale = False
      ## I2: tile rows of the preview map's raw entries (a fixed tileset's maker pictures), or None.
      self._entry_cache = None

      # -- left: tilesets and sheets
      ## Tilesets of the world.
      self.ts_list = QtWidgets.QListWidget()
      self.ts_list.currentRowChanged.connect(lambda *a: self._tileset_chosen(*a))
      ## Sheets of the tileset.
      self.sheet_list = QtWidgets.QListWidget()
      self.sheet_list.currentRowChanged.connect(lambda *a: self._sheet_chosen(*a))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Tilesets"))
      left.addWidget(self.ts_list, 1)
      left.addWidget(button("New tileset...", lambda: self.new_tileset()))
      left.addWidget(QtWidgets.QLabel("Sheets"))
      left.addWidget(self.sheet_list, 1)
      left.addWidget(button("Import sheet image...", lambda: self.import_sheet(),
                            "A PNG (or BMP, GIF...) of 8x8 tiles; its colors become the palette (up to 15)"))
      left.addWidget(button("Metatiles from sheet blocks", lambda: self.from_blocks(),
                            "One metatile per non-empty 16x16 block of the shown sheet"))

      # -- center: the sheet
      ## Sheet view.
      self.sheet_view = SheetView(lambda t, w, h: self._tile_picked(t, w, h), lambda: self.drag_data())
      scroll = QtWidgets.QScrollArea()
      scroll.setWidget(self.sheet_view)
      ## Picked tile.
      self.tile_info = QtWidgets.QLabel("Pick tiles (click, or drag across up to 2x2), then drag them onto the "
                                        "metatile.")
      self.tile_info.setWordWrap(True)
      ## Mirror the assigned tile horizontally.
      self.hflip = QtWidgets.QCheckBox("Flip H")
      self.hflip.setToolTip("Place the picked tiles mirrored left to right (a 2x2 block mirrors as a whole)")
      ## Mirror the assigned tile vertically.
      self.vflip = QtWidgets.QCheckBox("Flip V")
      self.vflip.setToolTip("Place the picked tiles mirrored top to bottom (a 2x2 block mirrors as a whole)")
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.tile_info, 1)
      row.addWidget(self.hflip)
      row.addWidget(self.vflip)
      ## The shown sheet's transparent color, as a swatch.
      self.key_swatch = QtWidgets.QLabel()
      self.key_swatch.setFixedSize(KEY_SWATCH_SIZE, KEY_SWATCH_SIZE)
      ## Its value, as text.
      self.key_text = QtWidgets.QLabel()
      ## Eyedropper: the next click on the sheet picks the transparent color.
      self.key_pick = QtWidgets.QPushButton("Pick from sheet")
      self.key_pick.setCheckable(True)
      self.key_pick.setToolTip("Click a pixel of the sheet: every pixel of that color becomes transparent")
      self.key_pick.toggled.connect(lambda on: self._picking(on))
      ## Color dialog for the transparent color.
      self.key_choose = button("Choose...", lambda: self.choose_transparent())
      ## Clears the transparent color.
      self.key_clear = button("None", lambda: self.set_transparent(None), "No transparent color")
      key_row = QtWidgets.QHBoxLayout()
      key_row.addWidget(QtWidgets.QLabel("Transparent color:"))
      key_row.addWidget(self.key_swatch)
      key_row.addWidget(self.key_text)
      key_row.addWidget(self.key_pick)
      key_row.addWidget(self.key_choose)
      key_row.addWidget(self.key_clear)
      key_row.addStretch(1)
      ## I2: the bank a fixed tileset's indexed sheet is shown in, and new raw entries take.
      self.sheet_bank = QtWidgets.QSpinBox()
      self.sheet_bank.setRange(0, tilesets._mc().MAX_PALETTES - 1)
      self.sheet_bank.setToolTip("Fixed tileset: the palette bank the sheet is shown in, and the bank of the entries "
                                 "picked tiles make")
      self.sheet_bank.valueChanged.connect(lambda *a: self._sheet_chosen(self.sheet_list.currentRow()))
      ## I2: which tilesets the metatile pictures are drawn with (a fixed tileset's entries name their tiles).
      self.context_label = QtWidgets.QLabel()
      self.context_label.setWordWrap(True)
      bank_row = QtWidgets.QHBoxLayout()
      bank_row.addWidget(QtWidgets.QLabel("Bank:"))
      bank_row.addWidget(self.sheet_bank)
      bank_row.addWidget(self.context_label, 1)
      ## I2 / I3: the fixed placement and the animations.
      self.fixed_box = FixedBox(self)
      ## The tile animations.
      self.anim_box = AnimationBox(self)
      ## Their tabs.
      self.format_tabs = QtWidgets.QTabWidget()
      self.format_tabs.addTab(self.fixed_box, "Fixed placement")
      self.format_tabs.addTab(self.anim_box, "Animations")
      middle = QtWidgets.QVBoxLayout()
      middle.addWidget(scroll, SHEET_STRETCH)
      middle.addLayout(key_row)
      middle.addLayout(bank_row)
      middle.addLayout(row)
      middle.addWidget(self.format_tabs, FORMAT_TABS_STRETCH)

      # -- right: metatiles
      ## Metatiles of the tileset (pictures; the name is the tooltip and mt_label).
      self.mt_grid = MetatileGrid(lambda key: self._metatile_chosen(key))
      ## Name of the chosen metatile.
      self.mt_label = QtWidgets.QLabel()
      ## The metatile maker: a 2x2 map of 8x8 tiles.
      self.maker = MetatileCanvas(self)
      ## The metatile at twice its size.
      self.preview = PixelView(METATILE_PREVIEW_ZOOM)
      self.preview.setFixedSize(METATILE_PREVIEW_SIZE, METATILE_PREVIEW_SIZE)
      self.mt_grid.setAcceptDrops(True)
      self.mt_grid.installEventFilter(self)
      ## Where the attributes went.
      note = QtWidgets.QLabel("Metatiles are graphics only. Behavior, collision, elevation, encounters and "
                              "environment tags are painted on the map's attribute layer (Map tab).")
      note.setWordWrap(True)
      ## Compile result.
      self.errors = QtWidgets.QLabel()
      self.errors.setWordWrap(True)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(QtWidgets.QLabel("Metatiles"))
      right.addWidget(grid_area(self.mt_grid), METATILE_LIST_STRETCH)
      right.addWidget(self.mt_label)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("New", lambda: self.new_metatile()))
      row.addWidget(button("Rename...", lambda: self.rename_metatile()))
      row.addWidget(button("Delete", lambda: self.delete_metatile()))
      right.addLayout(row)
      prow = QtWidgets.QHBoxLayout()
      prow.addWidget(self.maker, 0, QtCore.Qt.AlignmentFlag.AlignTop)
      prow.addWidget(self.preview, 0, QtCore.Qt.AlignmentFlag.AlignTop)
      prow.addStretch(1)
      right.addLayout(prow)
      maker_help = QtWidgets.QLabel("Drag tiles from the sheet onto the metatile (or onto the list above for a new "
                                    "one). Click stamps the picked tiles, right click clears, H / V mirror the "
                                    "tile under the mouse.")
      maker_help.setWordWrap(True)
      right.addWidget(maker_help)
      right.addWidget(note)
      right.addWidget(self.errors)

      layout = QtWidgets.QHBoxLayout(self)
      for part, stretch in ((left, LISTS_STRETCH), (middle, SHEET_STRETCH), (right, METATILES_STRETCH)):
         box = QtWidgets.QWidget()
         box.setLayout(part)
         layout.addWidget(box, stretch)

   # -- documents ---------------------------------------------------------------------

   def project(self) -> Project | None:
      """!The host's project.
      @return Project, or None
      """
      return self.host_project()

   def ts_doc(self) -> Document | None:
      """!The edited tileset's Document.
      @return Document, or None
      """
      p = self.project()
      if p is None or self.ts_name not in (p.tileset_names() if p else []):
         return None
      return p.tileset(self.ts_name)

   def compiled_ts(self) -> Any:
      """![S3] The shown tileset compiled (map_compiler Tileset), as the last fill compiled it.
      @return the Tileset, or None
      """
      return self._compiled[0]

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the edited tileset.
      @return Document, or None
      """
      return self.ts_doc()

   # -- refresh ---------------------------------------------------------------------------

   def document_replaced(self) -> None:
      """!Another world was opened: forget the old one's selection.
      @return None
      """
      self.ts_name = self.sheet_name = self.mt_name = None
      self._clear_tile()
      self._filled_for = None
      self.refresh()

   def showEvent(self, event: QtGui.QShowEvent) -> None:
      """!Catches up on refreshes skipped while hidden.
      @param event  QShowEvent
      @return None
      """
      super().showEvent(event)
      if self._stale:
         self.refresh()

   def _clear_tile(self) -> None:
      """!Forgets the picked sheet tile.
      @return None
      """
      self.tile = None
      self.tile_size = [1, 1]
      self.tile_info.setText("")

   def refresh(self) -> None:
      """!Re-reads the project: lists, sheet, metatile editor. Skipped while
      the panel is hidden (map edits would otherwise recompile the tileset on
      every stroke); showEvent() catches up.
      @return None
      """
      if not self.isVisible():
         self._stale = True
         return
      self._stale = False
      p = self.project()
      self._filling = True
      try:
         names = p.tileset_names() if p is not None else []
         if self.ts_name not in names:
            self.ts_name = names[0] if names else None
         self.ts_list.clear()
         self.ts_list.addItems(names)
         if self.ts_name is not None:
            self.ts_list.setCurrentRow(names.index(self.ts_name))
      finally:
         self._filling = False
      self._fill_tileset()

   def _fill_tileset(self) -> None:
      """!Fills sheets, metatiles and the editor for the current tileset
      (only when the tileset or the world changed since the last fill).
      @return None
      """
      p, doc = self.project(), self.ts_doc()
      key = None if doc is None else (id(p), self.ts_name, doc.revision, p.world.revision)
      if key is not None and key == self._filled_for:
         self._fill_metatile()   # attribute widgets were refilled by refresh()
         return
      self._filled_for = key
      self._filling = True
      try:
         self.sheet_list.clear()
         self.mt_grid.set_sections([])
         self._compiled = (None, None)
         if doc is None:
            self.sheet_view.set_image(None)
            self.errors.setText("")
            self.mt_name = None
            self.sheet_name = None
            self._fill_transparent()
         else:
            self._fill_lists(p, doc)
      finally:
         self._filling = False
      self._fill_metatile()
      self.anim_box.fill(doc)

   def _fill_lists(self, p: Project, doc: Document) -> None:
      """!Compiles the tileset and fills the sheet view and the lists.
      @param p    Project
      @param doc  tileset Document
      @return None
      """
      ts, preview, error = p.compiled_tileset(self.ts_name)
      self._compiled = (ts, preview)
      self._entry_cache = mapview.TileCache(preview) if preview is not None else None
      fixed = tilesets.place_of(doc)
      if fixed is not None:   # I2: shown in the tileset's first bank until another is picked
         self.sheet_bank.setValue(min(max(self.sheet_bank.value(), fixed.get("palette", 0)),
                                      fixed.get("palette", 0) + max(0, fixed.get("palettes", 1) - 1)))
         self.context_label.setText("Pictures drawn with: " + ", ".join(p.companions(self.ts_name)))
      else:
         self.context_label.setText("")
      self.sheet_bank.setEnabled(fixed is not None)
      self.errors.setText(f"Not compiling: {error}" if error else "")
      self.errors.setStyleSheet("color: #c03030;" if error else "")
      sheets = [s.get("name") for s in doc.data.get("sheets", [])]
      if self.sheet_name not in sheets:
         self.sheet_name = sheets[0] if sheets else None
      self.sheet_list.addItems(sheets)
      if self.sheet_name is not None:
         self.sheet_list.setCurrentRow(sheets.index(self.sheet_name))
      image = None
      if ts is not None and self.sheet_name in ts.sheets:
         image = to_qimage(*mapview.sheet_image(ts, self.sheet_name, self.sheet_bank.value()))
      self.sheet_view.set_image(image)
      self._fill_transparent()
      names = [m.get("name") for m in doc.data.get("metatiles", [])]
      if self.mt_name not in names:
         self.mt_name = names[0] if names else None
      items = []
      pictures = mapview.metatile_images(preview, backdrop=False) if preview is not None else []
      for i, n in enumerate(names):
         img = to_qimage(*pictures[i]) if i < len(pictures) else None
         items.append((n, img, n))
      self.mt_grid.set_sections([items])
      self.mt_grid.set_current(self.mt_name)

   def _tile_image(self, ref: TileRef) -> QtGui.QImage | None:
      """!One tile reference as a small QImage, flips applied.
      @param ref  "sheet:index[h][v]" or None
      @return QImage, or None
      """
      ts = self._compiled[0]
      if ref is None or ts is None:
         return None
      sheet, index, h, v = tilesets.parse(ref)
      if sheet not in ts.sheets:
         return None
      s = ts.sheets[sheet]
      img = mapview.blank(mapview.TILE, mapview.TILE)
      mapview.draw_tile(img, 0, 0, s.tile(index, sheet), mapview.sheet_bank_colors(ts, sheet, self.sheet_bank.value()),
                        (HFLIP_BIT if h else 0) | (VFLIP_BIT if v else 0))
      return to_qimage(*img)

   def metatile_tiles(self) -> list[TileRef] | None:
      """!The chosen metatile's four tile references.
      @return list of 4 references (None: transparent), or None without a metatile
      """
      doc = self.ts_doc()
      if doc is None or self.mt_name is None:
         return None
      try:
         m = tilesets.metatile(doc, self.mt_name)
      except ValueError:
         return None
      if "entries" in m:   # I2: raw entries have no tile references (slot_pictures() draws them)
         return None
      return ((m.get("tiles") or []) + [None] * mapview.METATILE_TILES)[:mapview.METATILE_TILES]

   def slot_pictures(self) -> list[QtGui.QImage | None] | None:
      """!The chosen metatile's four tiles as pictures: its tile references, or (I2) its raw entries drawn from the
      preview map (the tilesets maps load with it).
      @return 4 QImages (None: transparent / not drawable), or None without a metatile
      """
      doc = self.ts_doc()
      if doc is None or self.mt_name is None:
         return None
      try:
         m = tilesets.metatile(doc, self.mt_name)
      except ValueError:
         return None
      if "entries" not in m:
         refs = self.metatile_tiles()
         return [self.tile_picture(r) for r in refs] if refs is not None else None
      out = []
      for e in (m.get("entries") or [])[:mapview.METATILE_TILES]:
         if self._entry_cache is None or not isinstance(e, int):
            out.append(None)
            continue
         rows = self._entry_cache.entry_rows(e)
         out.append(to_qimage(mapview.TILE, mapview.TILE, bytearray(b"".join(rows))))
      return out + [None] * (mapview.METATILE_TILES - len(out))

   def tile_picture(self, ref: TileRef) -> QtGui.QImage | None:
      """!A tile reference's picture (cached per compile).
      @param ref  "sheet:index[h][v]" or None
      @return QImage, or None
      """
      if self._pictures_for is not self._compiled[0] or self._pictures_bank != self.sheet_bank.value():
         self._pictures_bank = self.sheet_bank.value()
         self._pictures = {}
         self._pictures_for = self._compiled[0]
      if ref not in self._pictures:
         self._pictures[ref] = self._tile_image(ref)
      return self._pictures[ref]

   def _fill_metatile(self) -> None:
      """!Shows the current metatile in the maker and the preview.
      @return None
      """
      doc = self.ts_doc()
      m = None
      if doc is not None and self.mt_name is not None:
         m = tilesets.metatile(doc, self.mt_name)
      self.mt_label.setText(f"Metatile: {self.mt_name}" if m else "No metatile chosen: drop tiles on the maker "
                            "below, or New")
      self.maker.update()
      self.fixed_box.fill(doc)   # I2: the chosen metatile's raw entries
      if m is None:
         self.preview.set_image(None)
         return
      preview = self._compiled[1]
      names_all = [x.get("name") for x in doc.data.get("metatiles", [])]
      i = names_all.index(self.mt_name)
      if preview is not None and i < len(preview["metatiles"]):
         self.preview.set_image(to_qimage(*mapview.metatile_image(preview, i, backdrop=False)))
      else:
         self.preview.set_image(None)

   def _tileset_chosen(self, row: int) -> None:
      """!Another tileset was picked.
      @param row  list row
      @return None
      """
      if self._filling:
         return
      p = self.project()
      names = p.tileset_names() if p is not None else []
      self.ts_name = names[row] if 0 <= row < len(names) else None
      self.sheet_name = None
      self.mt_name = None
      self._clear_tile()   # a sheet tile belongs to the tileset it was picked in
      QtCore.QTimer.singleShot(0, lambda: self._tileset_shown())

   def _tileset_shown(self) -> None:
      """!Fills the newly picked tileset and updates Undo / Redo for it.
      @return None
      """
      self._fill_tileset()
      self.host.selection_changed()

   def _sheet_chosen(self, row: int) -> None:
      """!Another sheet was picked.
      @param row  list row
      @return None
      """
      if self._filling:
         return
      doc = self.ts_doc()
      sheets = [s.get("name") for s in doc.data.get("sheets", [])] if doc else []
      self.sheet_name = sheets[row] if 0 <= row < len(sheets) else None
      ts = self._compiled[0]
      image = None
      if ts is not None and self.sheet_name in ts.sheets:
         image = to_qimage(*mapview.sheet_image(ts, self.sheet_name, self.sheet_bank.value()))
      self.sheet_view.clear_selection()
      self._clear_tile()
      self.sheet_view.set_image(image)
      self._fill_transparent()
      self._pictures_for = None   # tile pictures follow the shown bank

   # -- transparent color ------------------------------------------------------------------

   def _shown_sheet(self) -> JsonDict | None:
      """!The shown sheet's manifest entry.
      @return dict, or None
      """
      doc = self.ts_doc()
      if doc is None or self.sheet_name is None:
         return None
      return next((s for s in doc.data.get("sheets", []) if s.get("name") == self.sheet_name), None)

   def _fill_transparent(self) -> None:
      """!Shows the sheet's transparent color; the controls work on image sheets only.
      @return None
      """
      s = self._shown_sheet()
      image_sheet = s is not None and "image" in s
      color = s.get("transparent") if image_sheet else None
      self.key_swatch.setStyleSheet(f"background: {color}; border: 1px solid #555;" if color
                                    else "border: 1px dashed #888;")
      if s is None:
         self.key_text.setText("")
      else:
         self.key_text.setText(color or ("none" if image_sheet else "shape sheets use palette entry 0"))
      for w in (self.key_pick, self.key_choose, self.key_clear):
         w.setEnabled(image_sheet)
      if not image_sheet and self.key_pick.isChecked():
         self.key_pick.setChecked(False)

   def _picking(self, on: bool) -> None:
      """!Turns the sheet eyedropper on or off.
      @param on  picking
      @return None
      """
      self.sheet_view.pick_pixel = (lambda x, y: self._picked_pixel(x, y)) if on else None
      self.sheet_view.setCursor(QtCore.Qt.CursorShape.CrossCursor if on else QtCore.Qt.CursorShape.ArrowCursor)
      if on:
         self.host.show_status("Click the color on the sheet that should become transparent")

   def _picked_pixel(self, x: int, y: int) -> None:
      """!The eyedropper clicked a sheet pixel.
      @param x  pixel column
      @param y  pixel row
      @return None
      """
      self.key_pick.setChecked(False)
      doc = self.ts_doc()
      color = tilesets.source_color(doc, self.sheet_name, x, y) if doc is not None else None
      if color is None:
         self.host.show_status("Could not read that pixel of the source image")
         return
      self.set_transparent(color)

   def choose_transparent(self) -> None:
      """!Picks the transparent color in a color dialog.
      @return None
      """
      s = self._shown_sheet()
      start = QtGui.QColor(s.get("transparent", "#ff00ff")) if s else QtGui.QColor("#ff00ff")
      c = QtWidgets.QColorDialog.getColor(start, self, "Transparent color")
      if c.isValid():
         self.set_transparent("#{:02x}{:02x}{:02x}".format(c.red(), c.green(), c.blue()))

   def set_transparent(self, color: str | None) -> None:
      """!Sets the shown sheet's transparent color.
      @param color  "#rrggbb", or None
      @return None
      """
      doc, name = self.ts_doc(), self.sheet_name
      if doc is None or name is None:
         self.explain("Transparent color", "sheet" if doc is not None else "tileset")
         return
      if self._edit("Transparent color", lambda: tilesets.set_transparent(doc, name, color)):
         self.host.show_status(f"Transparent color of {name}: {color or 'none'}")

   def _metatile_chosen(self, name: str) -> None:
      """!Another metatile was picked.
      @param name  metatile name
      @return None
      """
      if self._filling:
         return
      self.mt_name = name
      self._fill_metatile()

   def _tile_picked(self, index: int, w: int = 1, h: int = 1) -> None:
      """!Sheet tiles were picked.
      @param index  top-left tile number
      @param w      block width in tiles
      @param h      block height in tiles
      @return None
      """
      self.tile = (self.sheet_name, index)
      self.tile_size = [w, h]
      size = f" ({w}x{h} tiles)" if (w, h) != (1, 1) else ""
      self.tile_info.setText(f"Picked {self.sheet_name}:{index}{size}: drag it onto the metatile, or click a tile "
                             "there")
      self.maker.update()

   # -- edits -------------------------------------------------------------------------------

   def _edit(self, label: str, fn: Callable[[], object]) -> bool:
      """!Runs an edit on the tileset through the host (edit_tileset()).
      @param label  undo label
      @param fn     callable
      @return True on success
      """
      return self.edit_tileset(label, fn)

   def edit_tileset(self, label: str, fn: Callable[[], object]) -> bool:
      """!Runs a change of the shown tileset through the host as one undo step; I2: the maps with an "all"
      dictionary it reorders are renumbered in the same step (Project.follow_metatile_order()).
      @param label  undo label
      @param fn     callable doing the change
      @return True on success
      """
      p, doc, name = self.project(), self.ts_doc(), self.ts_name
      if doc is None:
         return False

      def run() -> None:
         """!The change, then the "all" maps that follow its metatile order."""
         before = p.metatile_names(name)
         fn()
         followed = p.follow_metatile_order(name, before)
         if followed:
            self.host.show_status(f"Renumbered {len(followed)} map(s) with an \"all\" dictionary")
      return self.host.run_edit(label, run, doc)

   def import_indexed_sheet(self) -> None:
      """!Adds an indexed sheet (I2: a palette PNG used as its indices) to the shown tileset.
      @return None
      """
      doc = self.ts_doc()
      if doc is None:
         self.explain("Import indexed sheet", "tileset")
         return
      path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import indexed sheet", "", INDEXED_FILTER)
      if path:
         self.add_indexed_sheet(path)

   def add_indexed_sheet(self, path: str | Path) -> bool:
      """!Adds an indexed sheet from a file (the dialog-free part of import_indexed_sheet()).
      @param path  palette PNG
      @return True when added
      """
      doc, result = self.ts_doc(), []
      if doc is None:
         return self.explain("Import indexed sheet", "tileset")
      if self._edit("Import indexed sheet", lambda: result.append(tilesets.add_indexed_sheet(doc, Path(path).stem,
                                                                                              path))):
         self.sheet_name = result[0]
         self.host.changed()
         return True
      return False

   def _sheet_width(self, sheet_name: str | None) -> int | None:
      """!A sheet's width in tiles (compiled).
      @param sheet_name  sheet name
      @return tiles, or None when the tileset does not compile
      """
      ts = self._compiled[0]
      return ts.sheets[sheet_name].w if ts is not None and sheet_name in ts.sheets else None

   def picked_block(self) -> list[list[str]] | None:
      """!The picked tiles as they will land, flips applied.
      @return rows of references, or None when nothing is picked
      """
      doc = self.ts_doc()
      if doc is None or self.tile is None or self.tile[0] not in [s.get("name") for s in doc.data.get("sheets", [])]:
         return None
      cols = self._sheet_width(self.tile[0])
      if cols is None:
         return None
      w, h = self.tile_size
      return tilesets.block(self.tile[0], cols, self.tile[1], w, h, self.hflip.isChecked(), self.vflip.isChecked())

   def drag_data(self) -> QtCore.QMimeData | None:
      """!Drag payload for the picked sheet tiles (and a picture of them).
      @return QMimeData, or None
      """
      if self.tile is None or self.ts_name is None:
         return None
      data = QtCore.QMimeData()
      w, h = self.tile_size
      payload = {"tileset": self.ts_name, "sheet": self.tile[0], "index": self.tile[1], "w": w, "h": h}
      data.setData(TILES_MIME, QtCore.QByteArray(json.dumps(payload).encode("utf-8")))
      img = QtGui.QImage(w * mapview.TILE * DRAG_ZOOM, h * mapview.TILE * DRAG_ZOOM, QtGui.QImage.Format.Format_ARGB32)
      img.fill(QtGui.QColor(0, 0, 0, 0))
      cols = self._sheet_width(self.tile[0])
      if cols is not None:
         p = QtGui.QPainter(img)
         for dy, row in enumerate(tilesets.block(self.tile[0], cols, self.tile[1], w, h)):
            for dx, r in enumerate(row):
               pic = self.tile_picture(r)
               if pic is not None:
                  p.drawImage(QtCore.QRect(dx * DRAG_TILE_PIXELS, dy * DRAG_TILE_PIXELS, DRAG_TILE_PIXELS,
                                           DRAG_TILE_PIXELS), pic)
         p.end()
      data.setImageData(img)
      return data

   def dropped_tiles(self, mime: QtCore.QMimeData | None) -> JsonDict | None:
      """!Reads dragged sheet tiles, if they belong to the shown tileset.
      @param mime  QMimeData
      @return the payload dict, or None
      """
      if mime is None or not mime.hasFormat(TILES_MIME):
         return None
      try:
         d = json.loads(bytes(mime.data(TILES_MIME)).decode("utf-8"))
      except ValueError:
         return None
      if not isinstance(d, dict) or d.get("tileset") != self.ts_name or self._sheet_width(d.get("sheet")) is None:
         return None
      return d

   def _place(self, label: str, placements: list[tuple[int, list[list[TileRef]]]]) -> bool:
      """!Places tile blocks into the chosen metatile, or into a new blank
      one when none is chosen (one undo step).
      @param label       undo label
      @param placements  list of (slot, rows of references)
      @return True when edited
      """
      doc = self.ts_doc()
      if doc is None:
         return False
      made = []

      fixed = tilesets.place_of(doc)

      def run() -> None:
         """!Places the blocks, first adding a blank metatile when none is chosen."""
         name = self.mt_name
         if name is None:
            name = tilesets.add_fixed_metatile(doc, "metatile") if fixed is not None else \
               tilesets.add_metatile(doc, "metatile", [None] * mapview.METATILE_TILES)
            made.append(name)
         for slot, rows in placements:
            if fixed is not None:
               self._place_entries(doc, name, slot, rows, fixed)
            else:
               tilesets.place(doc, name, slot, rows)
      ok = self._edit(label if self.mt_name is not None else "New metatile", run)
      if ok and made:
         self.mt_name = made[0]
         self.host.changed()
      return ok

   def _place_entries(self, doc: Document, name: str, slot: int, rows: list[list[TileRef]],
                      place: dict[str, Any]) -> None:
      """!I2: puts picked tiles of a fixed tileset's placement sheet into a metatile as raw entries (VRAM tile =
      the placement's first tile + the sheet tile, the shown bank, the mirrors); None clears to entry 0.
      @param doc    tileset Document
      @param name   metatile name
      @param slot   top-left slot
      @param rows   rows of references, as tilesets.block() gives them
      @param place  the tileset's placement
      @return None
      """
      sx, sy = slot & 1, slot >> 1   # slot bit 0 is the column, bit 1 the row
      for dy, row in enumerate(rows):
         for dx, r in enumerate(row):
            x, y = sx + dx, sy + dy
            if x >= METATILE_SIDE or y >= METATILE_SIDE:
               continue
            if r is None:
               entry = 0
            else:
               sheet, index, h, v = tilesets.parse(r)
               if sheet != place.get("sheet"):
                  raise ValueError(f"raw entries name VRAM tiles: pick tiles of the placement's sheet "
                                   f"({place.get('sheet')}), not {sheet}")
               entry = tilesets.make_entry(place.get("tile", 0) + index, h, v, self.sheet_bank.value())
            tilesets.set_entry(doc, name, y * METATILE_SIDE + x, entry)

   def paint_slots(self, slots: list[int], stamp: bool) -> None:
      """!Stamps the picked tiles on slots (each block lands with its
      top-left tile on the slot), or clears the slots.
      @param slots  slots 0-3, in stroke order
      @param stamp  True to stamp, False to clear
      @return None
      """
      if not stamp:
         if self.mt_name is not None:
            self._place("Clear tile", [(slot, [[None]]) for slot in slots])
         return
      rows = self.picked_block()
      if rows is None:
         self._clear_tile()
         self.host.show_status("Pick a tile on the sheet first.")
         return
      self._place("Set tile", [(slot, rows) for slot in slots])

   def drop_block(self, payload: JsonDict, slot: int) -> bool:
      """!Places dropped sheet tiles with their top-left tile on a slot.
      @param payload  dropped_tiles() result
      @param slot     0-3
      @return True when placed
      """
      cols = self._sheet_width(payload["sheet"])
      try:
         rows = tilesets.block(payload["sheet"], cols, int(payload["index"]), int(payload.get("w", 1)),
                               int(payload.get("h", 1)), self.hflip.isChecked(), self.vflip.isChecked())
      except (ValueError, TypeError):
         return False
      return self._place("Drop tiles", [(slot, rows)])

   def flip_slot(self, slot: int, axis: str) -> None:
      """!Mirrors one tile of the chosen metatile.
      @param slot  0-3
      @param axis  "h" or "v"
      @return None
      """
      doc, name = self.ts_doc(), self.mt_name
      if doc is not None and name is not None and tilesets.is_fixed(doc):   # I2: a raw entry's mirror bit
         m = tilesets.metatile(doc, name)
         if "entries" in m:
            tile, h, v, bank = tilesets.split_entry(m["entries"][slot])
            entry = tilesets.make_entry(tile, h != (axis == "h"), v != (axis == "v"), bank)
            self._edit("Flip tile", lambda: tilesets.set_entry(doc, name, slot, entry))
         return
      refs = self.metatile_tiles()
      if doc is None or name is None or refs is None or refs[slot] is None:
         return
      self._edit("Flip tile", lambda: tilesets.toggle_flip(doc, name, slot, axis))

   def assign(self, slot: int) -> None:
      """!Puts the picked tiles into the metatile with their top-left tile on a slot.
      @param slot  0-3 (top-left, top-right, bottom-left, bottom-right)
      @return None
      """
      self.paint_slots([slot], True)

   def clear_slot(self, slot: int) -> None:
      """!Empties a metatile slot (transparent).
      @param slot  0-3
      @return None
      """
      self.paint_slots([slot], False)

   def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
      """!Sheet tiles dropped on the metatile list make a new metatile.
      @param obj    the metatile grid
      @param event  QEvent
      @return True when the drag event was handled here
      """
      kinds = (QtCore.QEvent.Type.DragEnter, QtCore.QEvent.Type.DragMove, QtCore.QEvent.Type.Drop)
      if obj is not self.mt_grid or event.type() not in kinds:
         return super().eventFilter(obj, event)
      payload = self.dropped_tiles(event.mimeData())
      if payload is None:
         event.ignore()
         return True
      event.acceptProposedAction()
      if event.type() == QtCore.QEvent.Type.Drop:
         keep, self.mt_name = self.mt_name, None   # a new metatile, not the chosen one
         if not self.drop_block(payload, 0):
            self.mt_name = keep
      return True

   def new_tileset(self) -> None:
      """!Adds an empty tileset to the world.
      @return None
      """
      p = self.project()
      if p is None:
         self.explain("New tileset")
         return
      name, ok = QtWidgets.QInputDialog.getText(self, "New tileset", "Name:")
      if not ok or not name.strip():
         return
      try:
         p.add_tileset(name.strip())
      except Exception as e:   # DocumentError
         QtWidgets.QMessageBox.warning(self, "New tileset", str(e))
         return
      self.ts_name = name.strip()
      self.host.changed()

   def import_sheet(self) -> None:
      """!Adds a sheet from an image file.
      @return None
      """
      doc = self.ts_doc()
      if doc is None:
         self.explain("Import sheet image", "tileset")
         return
      path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import sheet", "", SHEET_FILTER)
      if not path:
         return
      try:
         img = load_rgba(path)
      except ValueError as e:
         QtWidgets.QMessageBox.warning(self, "Import sheet", str(e))
         return
      result = []
      if self._edit("Import sheet", lambda: result.append(tilesets.add_image_sheet(doc, Path(path).stem, img))):
         self.sheet_name = result[0]
         self.host.changed()

   def from_blocks(self) -> None:
      """!Adds one metatile per non-empty 16x16 block of the shown sheet.
      @return None
      """
      doc, ts = self.ts_doc(), self._compiled[0]
      if doc is None or ts is None or self.sheet_name not in ts.sheets:
         self.explain("Metatiles from sheet blocks", "sheet" if doc is not None else "tileset")
         return
      if tilesets.is_fixed(doc):
         self.host.show_status("A fixed tileset's metatiles are raw entries: make them in the maker")
         return
      sheet, name = ts.sheets[self.sheet_name], self.sheet_name
      result = []
      if self._edit("Metatiles from sheet", lambda: result.extend(tilesets.metatiles_from_sheet(doc, name, sheet))):
         self.host.show_status(f"{len(result)} metatiles added")

   def new_metatile(self) -> None:
      """!Adds a blank metatile (drag tiles onto it in the maker).
      @return None
      """
      doc = self.ts_doc()
      if doc is None:
         self.explain("New metatile", "tileset")
         return
      result = []
      fixed = tilesets.is_fixed(doc)   # I2: raw entries
      if self._edit("New metatile", lambda: result.append(tilesets.add_fixed_metatile(doc, "metatile") if fixed else
                                                          tilesets.add_metatile(doc, "metatile",
                                                                                [None] * mapview.METATILE_TILES))):
         self.mt_name = result[0]
         self.host.changed()

   def rename_metatile(self) -> None:
      """!Renames the metatile here and in every map using it.
      @return None
      """
      p, name = self.project(), self.mt_name
      if p is None or name is None:
         self.explain("Rename metatile", "metatile")
         return
      new, ok = QtWidgets.QInputDialog.getText(self, "Rename metatile", "Name:", text=name)
      if not ok or not new.strip() or new.strip() == name:
         return
      try:
         changed = p.rename_metatile(self.ts_name, name, new.strip())
      except Exception as e:   # ValueError / DocumentError from the core
         QtWidgets.QMessageBox.warning(self, "Rename metatile", str(e))
         return
      self.mt_name = new.strip()
      self.host.show_status(f"Renamed; maps updated: {', '.join(changed) or 'none'}")
      self.host.changed()

   def delete_metatile(self) -> None:
      """!Removes the metatile (maps still using it then fail to compile).
      @return None
      """
      doc, name = self.ts_doc(), self.mt_name
      if doc is None or name is None:
         self.explain("Delete metatile", "metatile")
      elif self._edit("Delete metatile", lambda: tilesets.remove_metatile(doc, name)):
         self.mt_name = None
         self.host.changed()

   def stop(self) -> None:
      """!Nothing pending: edits apply immediately.
      @return None
      """
      pass
