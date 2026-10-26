"""!Small widgets shared by the panels."""
from __future__ import annotations

import logging
from collections.abc import Callable, Hashable, Iterable, Sequence
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import preview

if TYPE_CHECKING:
   from pathlib import Path

## Divisor that halves a length (centring a picture in a widget).
HALF = 2
## How long an editor window's status bar message stays, milliseconds.
STATUS_MS = 6000

## Qt platforms without a screen (the tests' offscreen one): nobody could answer a modal dialog there.
HEADLESS_PLATFORMS = ("offscreen", "minimal")
## Log the studio's windows report failures to (always; a modal box only on a screen).
LOG = logging.getLogger("capsule_studio")

## Default zoom of a PixelView, screen pixels per image pixel.
PIXEL_VIEW_ZOOM = 4
## Smallest PixelView, pixels (width and height).
PIXEL_VIEW_MIN_SIZE = 64
## Size hint of a PixelView without an image, pixels (width and height).
PIXEL_VIEW_EMPTY_SIZE = 128
## Room around a PixelView's image in its size hint, pixels (both sides together).
PIXEL_VIEW_MARGIN = 8


class PixelView(QtWidgets.QWidget):
   """!Shows an image at a whole-number zoom without smoothing, over a
   checkerboard so transparent pixels are visible.

   @var image
   The QImage shown, or None.
   @var zoom
   Pixels per image pixel.
   """

   def __init__(self, zoom: int = PIXEL_VIEW_ZOOM, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the view.
      @param zoom    initial zoom
      @param parent  parent widget
      """
      super().__init__(parent)
      self.image = None
      self.zoom = zoom
      self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
      self.setMinimumSize(PIXEL_VIEW_MIN_SIZE, PIXEL_VIEW_MIN_SIZE)

   def set_image(self, image: QtGui.QImage | None) -> None:
      """!Changes the image.
      @param image  QImage, or None to clear
      @return None
      """
      old = self.image.size() if self.image is not None else None
      self.image = image
      if (image.size() if image is not None else None) != old:
         self.updateGeometry()   # only when the size changes (playback sets a frame every tick)
      self.update()

   def set_zoom(self, zoom: int) -> None:
      """!Changes the zoom.
      @param zoom  1 or more
      @return None
      """
      self.zoom = max(1, int(zoom))
      self.updateGeometry()
      self.update()

   def sizeHint(self) -> QtCore.QSize:
      """!Image size at the current zoom.
      @return QSize
      """
      if self.image is None:
         return QtCore.QSize(PIXEL_VIEW_EMPTY_SIZE, PIXEL_VIEW_EMPTY_SIZE)
      return QtCore.QSize(self.image.width() * self.zoom + PIXEL_VIEW_MARGIN,
                          self.image.height() * self.zoom + PIXEL_VIEW_MARGIN)

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the checkerboard and the image, centred.
      @param event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.fillRect(self.rect(), self.palette().window())
      if self.image is None:
         p.end()
         return
      w, h = self.image.width() * self.zoom, self.image.height() * self.zoom
      target = QtCore.QRect((self.width() - w) // HALF, (self.height() - h) // HALF, w, h)

      # The checkerboard brush starts at the image's corner, so the squares line up with it.
      brush = QtGui.QBrush(checker_pixmap())
      brush.setTransform(QtGui.QTransform.fromTranslate(target.x(), target.y()))
      p.fillRect(target, brush)   # one call, not one per cell
      p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
      p.drawImage(target, self.image)
      p.end()


## Side of the checkerboard tile, pixels (two squares).
CHECKER_TILE = 16
## Side of one checkerboard square, pixels.
CHECKER_SQUARE = 8
## Dark checkerboard squares, 8-bit RGB.
CHECKER_DARK = (110, 110, 110)
## Light checkerboard squares, 8-bit RGB.
CHECKER_LIGHT = (160, 160, 160)

## Checkerboard tile, made on first use (needs a running QApplication).
_checker: QtGui.QPixmap | None = None


def headless() -> bool:
   """!Whether Qt runs without a screen (the offscreen or minimal platform, as the tests do).
   @return True when no one could answer a dialog
   """
   return QtGui.QGuiApplication.instance() is not None and \
      QtGui.QGuiApplication.platformName() in HEADLESS_PLATFORMS


def report_failure(window: QtWidgets.QWidget, title: str, text: str) -> None:
   """!Tells about a failure that needs no answer. It is always logged; on a screen a warning box shows it,
   headless (tests) only the window's status bar (a QMainWindow's) does, so nothing waits for a click.
   @param window  the window it happened in (the box's parent)
   @param title   what failed ("Open battle data")
   @param text    the message
   @return None
   """
   LOG.warning("%s: %s", title, text)
   if not headless():
      QtWidgets.QMessageBox.warning(window, title, text)
      return
   main = window.window()
   if isinstance(main, QtWidgets.QMainWindow):
      main.statusBar().showMessage(f"{title}: {text}", STATUS_MS)


def ask(window: QtWidgets.QWidget, title: str, text: str, buttons: QtWidgets.QMessageBox.StandardButton,
        default: QtWidgets.QMessageBox.StandardButton,
        headless_answer: QtWidgets.QMessageBox.StandardButton) -> QtWidgets.QMessageBox.StandardButton:
   """!Asks a question: a question box on a screen; headless (tests, scripts) nothing waits for a click, the
   answer is @p headless_answer and the question is logged and shown in the window's status bar
   (report_failure()).
   @param window           the window it is asked in (the box's parent)
   @param title            the box's title
   @param text             the question
   @param buttons          the answers offered
   @param default          the answer Enter gives
   @param headless_answer  the answer without a screen (the safe one: keep the data, refuse the change)
   @return the answer
   """
   if headless():
      report_failure(window, title, f"{text} (no screen: {headless_answer.name})")
      return headless_answer
   return QtWidgets.QMessageBox.question(window, title, text, buttons, default)


def checker_pixmap() -> QtGui.QPixmap:
   """!A 16x16 tile of 8-pixel light and dark squares for transparent areas.
   @return QPixmap
   """
   global _checker
   if _checker is None:
      _checker = QtGui.QPixmap(CHECKER_TILE, CHECKER_TILE)
      _checker.fill(QtGui.QColor(*CHECKER_DARK))
      p = QtGui.QPainter(_checker)
      p.fillRect(CHECKER_SQUARE, 0, CHECKER_SQUARE, CHECKER_SQUARE, QtGui.QColor(*CHECKER_LIGHT))
      p.fillRect(0, CHECKER_SQUARE, CHECKER_SQUARE, CHECKER_SQUARE, QtGui.QColor(*CHECKER_LIGHT))
      p.end()
   return _checker


## Entries in a sprite palette, entry 0 (transparent) included.
PALETTE_ENTRIES = 16
## Width of one palette swatch with its gap, pixels.
SWATCH_SIZE = 14
## Space between swatches, pixels.
SWATCH_GAP = 2
## Space above the swatches, pixels.
SWATCH_TOP = 2
## Height of the palette strip, pixels.
PALETTE_STRIP_HEIGHT = 18
## Swatch frames, 8-bit RGB.
SWATCH_FRAME_COLOR = (60, 60, 60)
## The transparent entry's swatch (crossed out), 8-bit RGB.
TRANSPARENT_SWATCH_COLOR = (180, 180, 180)


class PaletteStrip(QtWidgets.QWidget):
   """!Shows a sprite's palette entries as swatches (entry 0, transparent, first).

   @var colors
   5-bit colors of entries 1..n.
   """

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the strip.
      @param parent  parent widget
      """
      super().__init__(parent)
      self.colors = []
      self.setFixedHeight(PALETTE_STRIP_HEIGHT)
      self.setMinimumWidth(PALETTE_ENTRIES * SWATCH_SIZE)

   def set_colors(self, colors: Iterable[tuple[int, int, int]]) -> None:
      """!Changes the colors.
      @param colors  list of (r5, g5, b5), up to 15
      @return None
      """
      self.colors = list(colors)
      self.setToolTip("Palette entries 0 (transparent) to 15, as the GBA shows them")
      self.update()

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the swatches.
      @param event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      size = SWATCH_SIZE
      p.setPen(QtGui.QColor(*SWATCH_FRAME_COLOR))
      for i in range(PALETTE_ENTRIES):
         r = QtCore.QRect(i * size, SWATCH_TOP, size - SWATCH_GAP, size - SWATCH_GAP)
         if i == 0:
            p.fillRect(r, QtGui.QColor(*TRANSPARENT_SWATCH_COLOR))
            p.drawLine(r.topLeft(), r.bottomRight())
         elif i - 1 < len(self.colors):   # entry i is colors[i - 1]: entry 0 has no color
            p.fillRect(r, QtGui.QColor(*preview.expand(self.colors[i - 1])))
         p.drawRect(r)
      p.end()


def button(text: str, slot: Callable[[], object], tip: str | None = None) -> QtWidgets.QPushButton:
   """!A push button wired to a slot.
   @param text  label
   @param slot  callable
   @param tip   tooltip, or None
   @return QPushButton
   """
   b = QtWidgets.QPushButton(text)
   b.clicked.connect(lambda _checked=False: slot())
   if tip:
      b.setToolTip(tip)
   return b


## Default pause before a Debounce calls its function, milliseconds.
DEBOUNCE_MS = 400


class Debounce(QtCore.QObject):
   """!Calls a function once input has paused, so typing becomes one undo step."""

   def __init__(self, fn: Callable[[], object], ms: int = DEBOUNCE_MS, parent: QtCore.QObject | None = None) -> None:
      """!Creates the debouncer.
      @param fn      callable without arguments
      @param ms      pause, milliseconds
      @param parent  owner QObject
      """
      super().__init__(parent)
      ## The function.
      self._fn = fn
      ## Single-shot timer.
      self._timer = QtCore.QTimer(self)
      self._timer.setSingleShot(True)
      self._timer.setInterval(ms)
      self._timer.timeout.connect(fn)

   def poke(self) -> None:
      """!Restarts the wait.
      @return None
      """
      self._timer.start()

   def flush(self) -> None:
      """!Calls the function now if a call is pending.
      @return None
      """
      if self._timer.isActive():
         self._timer.stop()
         self._fn()


## Most recent files a start page lists.
MAX_RECENT = 8


def recent_files(tool: str) -> list[str]:
   """!Files a tool opened recently, newest first (only those that still exist).
   @param tool  tool name (settings group)
   @return list of path strings
   """
   from pathlib import Path
   value = QtCore.QSettings("CapsuleCreatures", "capsule-studio").value(f"{tool}/recent", [])
   if isinstance(value, str):   # QSettings returns a lone entry as a string
      value = [value]
   return [p for p in (value or []) if isinstance(p, str) and Path(p).is_file()][:MAX_RECENT]


def remember_file(tool: str, path: str | Path) -> None:
   """!Puts a file at the top of a tool's recent list.
   @param tool  tool name (settings group)
   @param path  file opened or created
   @return None
   """
   from pathlib import Path
   path = str(Path(path).resolve())
   files = [path] + [p for p in recent_files(tool) if p != path]
   QtCore.QSettings("CapsuleCreatures", "capsule-studio").setValue(f"{tool}/recent", files[:MAX_RECENT])


## Points the start page's title is larger than the normal font.
START_TITLE_EXTRA_POINTS = 6
## Smallest height of the start page's buttons, pixels.
START_BUTTON_HEIGHT = 36
## Tallest the start page's recent list grows, pixels.
START_RECENT_HEIGHT = 150
## Start page margin, left and right, pixels.
START_MARGIN_X = 18
## Start page margin, top and bottom, pixels.
START_MARGIN_Y = 16
## Space above the start page's buttons, pixels.
START_BUTTONS_SPACING = 8
## Space above the start page's recent list, pixels.
START_RECENT_SPACING = 10
## Width of the start page, pixels.
START_PAGE_WIDTH = 460


class StartPage(QtWidgets.QWidget):
   """!The small window an editor opens on when nothing is open yet: what
   to do first, the open / new buttons and the recently opened files. Its
   editor window shows once something is opened (and this one hides).

   @var recent
   List of recent files (double-click or Open selected to open one). It is
   always shown; with nothing opened yet it says so.
   """

   ## Text of the recent list while it is empty.
   EMPTY_TEXT = "Nothing opened yet: files you open or create are listed here"

   def __init__(self, heading: str, text: str, actions: Iterable[tuple[str, Callable[[], object]]], tool: str,
                open_path: Callable[[str], object], parent: QtWidgets.QWidget | None = None,
                skip: tuple[str, Callable[[], object]] | None = None, recent_title: str = "Recent") -> None:
      """!Builds the page.
      @param heading    title line
      @param text       one or two sentences on what to do first
      @param actions    [(button label, callable), ...]
      @param tool       tool name for the recent list (see recent_files())
      @param open_path  callable(path) opening a recent file
      @param parent     parent widget
      @param skip       (button label, callable) opening the editor with nothing open, or None
      @param recent_title  heading of the recent list (e.g. "Recent worlds")
      """
      super().__init__(parent)
      self.setWindowFlag(QtCore.Qt.WindowType.Window, True)
      self.setWindowTitle(heading)
      ## Tool name for the recent list.
      self._tool = tool
      ## Opens a recent file.
      self._open_path = open_path

      title = QtWidgets.QLabel(heading)
      font = title.font()
      font.setPointSize(font.pointSize() + START_TITLE_EXTRA_POINTS)
      font.setBold(True)
      title.setFont(font)
      hint = QtWidgets.QLabel(text)
      hint.setWordWrap(True)
      buttons = QtWidgets.QHBoxLayout()
      for label, slot in actions:
         b = button(label, slot)
         b.setMinimumHeight(START_BUTTON_HEIGHT)
         buttons.addWidget(b)
      buttons.addStretch(1)

      self.recent = QtWidgets.QListWidget()
      self.recent.setMaximumHeight(START_RECENT_HEIGHT)
      self.recent.itemActivated.connect(lambda item: self._open_item(item))
      ## "Open selected" button for the recent list.
      self.open_recent = button("Open selected", lambda: self._open_item(self.recent.currentItem()))
      ## Label above the recent list.
      self.recent_label = QtWidgets.QLabel(recent_title)

      box = QtWidgets.QVBoxLayout(self)
      box.setContentsMargins(START_MARGIN_X, START_MARGIN_Y, START_MARGIN_X, START_MARGIN_Y)
      box.addWidget(title)
      box.addWidget(hint)
      box.addSpacing(START_BUTTONS_SPACING)
      box.addLayout(buttons)
      if skip is not None:
         ## Opens the editor without a file.
         self.skip_button = button(skip[0], skip[1], "Open the editor now; File > Open or New loads something later")
         self.skip_button.setFlat(True)
         box.addWidget(self.skip_button, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
      box.addSpacing(START_RECENT_SPACING)
      box.addWidget(self.recent_label)
      box.addWidget(self.recent)
      box.addWidget(self.open_recent, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
      box.addStretch(1)
      self.setFixedWidth(START_PAGE_WIDTH)
      self.refresh()

   def refresh(self) -> None:
      """!Re-reads the recent list.
      @return None
      """
      from pathlib import Path
      files = recent_files(self._tool)
      self.recent.clear()
      for f in files:   # files share names (world.json): show the folder first
         item = QtWidgets.QListWidgetItem(f"{Path(f).parent.name}    {f}")
         item.setData(QtCore.Qt.ItemDataRole.UserRole, f)
         self.recent.addItem(item)
      if files:
         self.recent.setCurrentRow(0)
      else:   # the list stays, saying why it is empty
         item = QtWidgets.QListWidgetItem(self.EMPTY_TEXT)
         item.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
         self.recent.addItem(item)
      self.open_recent.setEnabled(bool(files))
      self.adjustSize()

   def _open_item(self, item: QtWidgets.QListWidgetItem | None) -> None:
      """!Opens a recent file.
      @param item  QListWidgetItem, or None
      @return None
      """
      path = item.data(QtCore.Qt.ItemDataRole.UserRole) if item is not None else None
      if path:
         self._open_path(path)


## One MetatileGrid item: (key, picture or None, tooltip).
GridItem = tuple[Hashable, QtGui.QImage | None, str]
## Where a MetatileGrid item sits: (section, column, row).
GridPos = tuple[int, int, int]
## Index of the column in a GridPos.
GRID_POS_COLUMN = 1
## Index of the row in a GridPos.
GRID_POS_ROW = 2
## A picked rectangle of MetatileGrid items: rows of keys, None past a section's end.
GridRows = list[list[Hashable | None]]

## Space between MetatileGrid pictures, pixels.
GRID_GAP = 1
## Extra space between MetatileGrid sections, pixels.
GRID_SECTION_GAP = 6
## Default zoom of a MetatileGrid, screen pixels per metatile pixel.
GRID_ZOOM = 2
## Side of a metatile, pixels.
METATILE_PIXELS = 16
## Gaps a single row needs (above and below it).
GRID_ROW_GAPS = 2
## Pictures across in a MetatileGrid's size hint.
GRID_HINT_COLUMNS = 5
## A picture that is missing, 8-bit RGB (magenta stands out).
GRID_MISSING_COLOR = (255, 0, 255)
## Frame of the pick, 8-bit RGB.
GRID_PICK_COLOR = (255, 255, 255)
## Tint over the items of a picked rectangle, 8-bit RGBA.
GRID_BLOCK_TINT = (255, 255, 255, 60)
## Width of the pick's outer frame, pixels.
GRID_PICK_WIDTH = 2
## Inset of the pick's inner frame from the left and top, pixels.
GRID_INNER_INSET = 3
## Inset of the pick's inner frame from the right and bottom, pixels (QRect's right and bottom are inclusive).
GRID_INNER_INSET_FAR = 4


class MetatileGrid(QtWidgets.QWidget):
   """!Metatile pictures in a grid, one pixel apart, no labels (the name is
   the tooltip). Items come in sections (one per tileset); each section
   starts a new row. Click or arrow keys pick; the pick is framed. With
   on_block, dragging (or shift-clicking) picks a rectangle of items inside
   one section, as rows of keys.

   Put it in a QScrollArea with widgetResizable set: its height follows
   its width.

   @var sections
   Items per section: lists of (key, QImage or None, tooltip).
   """

   def __init__(self, on_pick: Callable[[Hashable], object], zoom: int = GRID_ZOOM,
                parent: QtWidgets.QWidget | None = None,
                on_block: Callable[[GridRows], object] | None = None) -> None:
      """!Creates the grid.
      @param on_pick   callable(key) when the user picks an item
      @param zoom      screen pixels per metatile pixel
      @param parent    parent widget
      @param on_block  callable(rows of keys, None past a section's end) when the user picks a rectangle of
                       more than one item, or None for single picks only
      """
      super().__init__(parent)
      ## Called with the picked key.
      self._on_pick = on_pick
      ## Called with a picked rectangle, or None.
      self._on_block = on_block
      ## Keys of the picked rectangle (framed together), or empty.
      self._block = set()
      ## (section, column, row) where a rectangle drag started, or None.
      self._anchor = None
      ## The rectangle picked by the drag so far (rows of keys), or None.
      self._rows = None
      ## Screen pixels per metatile pixel.
      self.zoom = zoom
      self.sections = []
      ## The picked key, or None.
      self._current = None
      self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
      self.setMouseTracking(True)
      policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
      policy.setHeightForWidth(True)
      self.setSizePolicy(policy)

   # -- content -------------------------------------------------------------------

   def set_sections(self, sections: Iterable[Iterable[GridItem]]) -> None:
      """!Replaces the items.
      @param sections  list of lists of (key, QImage or None, tooltip)
      @return None
      """
      self.sections = [list(s) for s in sections]
      self.updateGeometry()
      self.update()

   def keys(self) -> list[Hashable]:
      """!Every key, in order.
      @return list
      """
      return [k for s in self.sections for k, _, _ in s]

   def current(self) -> Hashable | None:
      """!The picked key.
      @return key, or None
      """
      return self._current

   def set_current(self, key: Hashable | None) -> None:
      """!Frames an item (without calling on_pick); forgets a picked rectangle.
      @param key  key, or None
      @return None
      """
      self._current = key
      self._block = set()
      r = self._rect_of(key)
      if r is not None:
         # Inside a QScrollArea the grid's parent is the viewport; the area is the viewport's parent.
         parent = self.parent()
         area = parent.parent() if parent is not None else None
         if isinstance(area, QtWidgets.QScrollArea):
            area.ensureVisible(r.center().x(), r.center().y(), r.width(), r.height())
      self.update()

   # -- layout ----------------------------------------------------------------------

   def cell(self) -> int:
      """!Picture size on screen.
      @return pixels
      """
      return METATILE_PIXELS * self.zoom

   def columns(self, width: int | None = None) -> int:
      """!Pictures per row at a width.
      @param width  pixels (default: the widget's)
      @return count, at least 1
      """
      w = self.width() if width is None else width
      return max(1, (w - GRID_GAP) // (self.cell() + GRID_GAP))

   def _layout(self, width: int | None = None) \
         -> tuple[list[tuple[Hashable, QtGui.QImage | None, str, QtCore.QRect]], int]:
      """!Where every item goes.
      @param width  pixels (default: the widget's)
      @return (list of (key, image, tip, QRect), total height)
      """
      cols = self.columns(width)
      step = self.cell() + GRID_GAP
      out = []
      y = GRID_GAP
      for si, section in enumerate(self.sections):
         if si and section:
            y += GRID_SECTION_GAP
         for i, (key, img, tip) in enumerate(section):
            out.append((key, img, tip, QtCore.QRect(GRID_GAP + (i % cols) * step, y + (i // cols) * step,
                                                    self.cell(), self.cell())))
         if section:
            y += ((len(section) + cols - 1) // cols) * step   # rows the section takes, rounded up
      return out, y

   def hasHeightForWidth(self) -> bool:
      """!The height follows the width.
      @return True
      """
      return True

   def heightForWidth(self, width: int) -> int:
      """!Height needed at a width.
      @param width  pixels
      @return pixels
      """
      return max(self.cell() + GRID_ROW_GAPS * GRID_GAP, self._layout(width)[1])

   def sizeHint(self) -> QtCore.QSize:
      """!About five pictures wide.
      @return QSize
      """
      w = GRID_GAP + GRID_HINT_COLUMNS * (self.cell() + GRID_GAP)
      return QtCore.QSize(w, self.heightForWidth(w))

   def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
      """!Keeps the height in step with the width (inside a scroll area).
      @param event  QResizeEvent
      @return None
      """
      need = self.heightForWidth(event.size().width())
      if self.minimumHeight() != need:
         self.setMinimumHeight(need)
      super().resizeEvent(event)

   def _rect_of(self, key: Hashable | None) -> QtCore.QRect | None:
      """!An item's rectangle.
      @param key  key
      @return QRect, or None
      """
      for k, _, _, r in self._layout()[0]:
         if k == key:
            return r
      return None

   def _grid_pos(self) -> tuple[dict[Hashable, GridPos], dict[GridPos, Hashable]]:
      """!Where every item sits: key -> (section, column, row), and back.
      @return (dict key -> position, dict position -> key)
      """
      cols = self.columns()
      where, back = {}, {}
      for si, section in enumerate(self.sections):
         for i, (key, _img, _tip) in enumerate(section):
            where[key] = (si, i % cols, i // cols)
            back[(si, i % cols, i // cols)] = key
      return where, back

   def _rect_rows(self, a: GridPos, b: GridPos) -> GridRows:
      """!Keys of the rectangle between two grid positions of one section.
      @param a  (section, column, row)
      @param b  (section, column, row) of the same section
      @return rows of keys (None past the section's end)
      """
      back = self._grid_pos()[1]
      c0, c1 = sorted((a[GRID_POS_COLUMN], b[GRID_POS_COLUMN]))
      r0, r1 = sorted((a[GRID_POS_ROW], b[GRID_POS_ROW]))
      return [[back.get((a[0], c, r)) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]

   def set_block(self, rows: Sequence[Sequence[Hashable | None]]) -> None:
      """!Frames a picked rectangle (without calling on_block).
      @param rows  rows of keys (None entries are skipped)
      @return None
      """
      keys = [k for row in rows for k in row if k is not None]
      self._current = keys[0] if keys else None
      self._block = set(keys) if len(keys) > 1 else set()
      self.update()

   def _extend(self, pos: QtCore.QPointF) -> GridRows | None:
      """!Grows the picked rectangle from the anchor to the item under a position.
      @param pos  QPointF
      @return rows of keys, or None when the position is not in the anchor's section
      """
      hit = self._at(pos)
      if hit is None or self._anchor is None:
         return None
      where = self._grid_pos()[0]
      b = where.get(hit[0])
      if b is None or b[0] != self._anchor[0]:
         return None
      rows = self._rect_rows(self._anchor, b)
      keys = [k for row in rows for k in row if k is not None]
      self._block = set(keys) if len(keys) > 1 else set()
      self._rows = rows
      self.update()
      return rows

   def _at(self, pos: QtCore.QPoint | QtCore.QPointF) -> tuple[Hashable, str] | None:
      """!The item under a position.
      @param pos  QPoint / QPointF
      @return (key, tip), or None
      """
      p = QtCore.QPoint(int(pos.x()), int(pos.y()))
      for k, _, tip, r in self._layout()[0]:
         if r.contains(p):
            return k, tip
      return None

   # -- painting and input ------------------------------------------------------------

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the pictures and frames the pick.
      @param event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
      p.fillRect(self.rect(), self.palette().color(QtGui.QPalette.ColorRole.Dark))
      for key, img, _, r in self._layout()[0]:
         if not r.intersects(event.rect()):
            continue
         if img is None:
            p.fillRect(r, QtGui.QColor(*GRID_MISSING_COLOR))
         else:
            p.fillRect(r, QtGui.QColor(0, 0, 0))
            p.drawImage(r, img)
         if key in self._block:
            p.fillRect(r, QtGui.QColor(*GRID_BLOCK_TINT))
            p.setPen(QtGui.QPen(QtGui.QColor(*GRID_PICK_COLOR), GRID_PICK_WIDTH))
            p.drawRect(r.adjusted(1, 1, -1, -1))
         elif key == self._current:
            # A light outer frame and a dark inner one: the pick shows on light and dark pictures.
            p.setPen(QtGui.QPen(QtGui.QColor(*GRID_PICK_COLOR), GRID_PICK_WIDTH))
            p.drawRect(r.adjusted(1, 1, -1, -1))
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1))
            p.drawRect(r.adjusted(GRID_INNER_INSET, GRID_INNER_INSET, -GRID_INNER_INSET_FAR, -GRID_INNER_INSET_FAR))
      p.end()

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Picks the clicked item (shift-click: the rectangle from the current pick).
      @param event  QMouseEvent
      @return None
      """
      hit = self._at(event.position())
      if hit is None or event.button() != QtCore.Qt.MouseButton.LeftButton:
         return
      shift = event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
      where = self._grid_pos()[0]
      if self._on_block is not None and shift and self._current in where:
         # Shift-click: a one-off rectangle from the current pick, without starting a drag.
         self._anchor = where[self._current]
         rows = self._extend(event.position())
         self._anchor = None
         if rows is not None and self._block:
            self._on_block(rows)
         return
      self._pick(hit[0])
      self._rows = None
      self._anchor = where.get(hit[0]) if self._on_block is not None else None

   def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Grows the picked rectangle while the button is down.
      @param event  QMouseEvent
      @return None
      """
      if self._anchor is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
         self._extend(event.position())

   def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Ends a rectangle pick and tells the owner.
      @param event  QMouseEvent
      @return None
      """
      if self._anchor is None:
         return
      self._extend(event.position())
      rows, self._rows, self._anchor = self._rows, None, None
      if rows is not None and self._block:
         self._on_block(rows)

   def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
      """!Arrow keys move the pick.
      @param event  QKeyEvent
      @return None
      """
      keys = self.keys()
      k = QtCore.Qt.Key
      # Left / right step one item; up / down step one row of the grid.
      moves = {k.Key_Left: -1, k.Key_Right: 1, k.Key_Up: -self.columns(), k.Key_Down: self.columns()}
      if event.key() not in moves or not keys:
         super().keyPressEvent(event)
         return
      i = keys.index(self._current) if self._current in keys else 0
      self._pick(keys[max(0, min(len(keys) - 1, i + moves[event.key()]))])

   def event(self, e: QtCore.QEvent) -> bool:
      """!Shows the hovered item's name as a tooltip.
      @param e  QEvent
      @return handled
      """
      if e.type() == QtCore.QEvent.Type.ToolTip:
         hit = self._at(e.pos())
         if hit is not None and hit[1]:
            QtWidgets.QToolTip.showText(e.globalPos(), hit[1], self)
         else:
            QtWidgets.QToolTip.hideText()
            e.ignore()
         return True
      return super().event(e)

   def _pick(self, key: Hashable) -> None:
      """!Picks an item and tells the owner.
      @param key  key
      @return None
      """
      self.set_current(key)
      self._on_pick(key)


def grid_area(grid: MetatileGrid) -> QtWidgets.QScrollArea:
   """!A scroll area holding a MetatileGrid (vertical scrolling only).
   @param grid  MetatileGrid
   @return QScrollArea
   """
   area = QtWidgets.QScrollArea()
   area.setWidget(grid)
   area.setWidgetResizable(True)
   area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
   return area


## One file toolbar entry: (role in TOOLBAR_ICONS, QAction, tooltip[, short button label]).
ToolbarEntry = tuple[str, QtGui.QAction, str] | tuple[str, QtGui.QAction, str, str]

## Standard icons for file toolbar actions, by role (theme icon name, fallback style pixmap).
TOOLBAR_ICONS = {
   "open": ("document-open", "SP_DialogOpenButton"),
   "import": ("document-import", "SP_ArrowDown"),
   "save": ("document-save", "SP_DialogSaveButton"),
   "save_all": ("document-save-all", "SP_DriveFDIcon"),
   "undo": ("edit-undo", "SP_ArrowBack"),
   "redo": ("edit-redo", "SP_ArrowForward"),
   "check": ("dialog-ok-apply", "SP_DialogApplyButton"),
   "new": ("document-new", "SP_FileIcon"),
}
## Fields every toolbar entry has (role, action, tooltip); the optional short button label comes after them.
TOOLBAR_ENTRY_FIELDS = 3


def file_toolbar(window: QtWidgets.QMainWindow, actions: Iterable[ToolbarEntry | None]) -> QtWidgets.QToolBar:
   """!Adds the Save / Save all / Undo / Redo toolbar to an editor window:
   buttons for the same actions as the File and Edit menus (their labels,
   such as "Undo Paint", and enabled state follow the menus').
   @param window   QMainWindow
   @param actions  list of (role in TOOLBAR_ICONS, QAction, tooltip[, short button label]), or None for a
                   separator
   @return the QToolBar
   """
   bar = QtWidgets.QToolBar("File and edit", window)
   bar.setObjectName("file_toolbar")
   bar.setMovable(False)
   bar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
   style = window.style()
   for entry in actions:
      if entry is None:
         bar.addSeparator()
         continue
      role, action, tip = entry[:TOOLBAR_ENTRY_FIELDS]
      if len(entry) > TOOLBAR_ENTRY_FIELDS:
         action.setIconText(entry[TOOLBAR_ENTRY_FIELDS])   # the menu keeps the long label

      # The desktop theme's icon when it has one, else the Qt style's built-in pixmap.
      theme, fallback = TOOLBAR_ICONS[role]
      icon = QtGui.QIcon.fromTheme(theme)
      if icon.isNull():
         icon = style.standardIcon(getattr(QtWidgets.QStyle.StandardPixmap, fallback))
      action.setIcon(icon)
      keys = action.shortcut().toString(QtGui.QKeySequence.SequenceFormat.NativeText)
      action.setToolTip(f"{tip} ({keys})" if keys else tip)
      bar.addAction(action)
   window.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, bar)
   return bar
