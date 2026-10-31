"""!Resizable panes and scroll bars for every page (D-40 RZ): one mechanism for the Studio and every editor.

Two rules hold on every page, whatever the window's size:

  - **Panels side by side or stacked are split by a splitter**: the user drags the boundary. A list beside a form,
    a tree above an inspector, a canvas beside its property pane: each is a pane of a Splitter (splitter(), or
    split_box() for a box layout built already). Panes never collapse to nothing; each keeps at least
    PANE_MIN_WIDTH x PANE_MIN_HEIGHT, a small named size, not its content's size, so a boundary can always move.
  - **Content that does not fit scrolls**: a pane that is not a view of its own (a list, table, tree, text view or
    canvas scrolls by itself) sits in a fit area (scroll_wrap()): a QScrollArea that follows the pane's size while
    the content fits and shows scroll bars, both ways as needed, when it does not. Every hosted panel sits in one
    as a whole too (fit_panel(), called by the hosts), so no panel makes the window larger than a small screen,
    and nothing is squashed below its usable size or pushed off-screen.

A fit area is part of the page's frame, not its content: FIT_PROPERTY marks it. The scroll bars are never
switched off: a fit area is a QScrollArea page, which widgets.set_enabled() keeps enabled (D-40 RW: no ancestor of
a scroll area is ever disabled).

The tests (editor/tests/test_panes.py) walk every Studio page and every standalone editor and check both rules
with the same definition of a panel this module uses (holds_panel()), so a new page that puts two panels in a
plain box layout, or a panel that forces a large window, fails them.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6 import QtCore, QtGui, QtWidgets

## Smallest width a splitter pane can be dragged to, pixels: room for a short list entry or a field's label.
PANE_MIN_WIDTH = 120
## Smallest height a splitter pane can be dragged to, pixels: about three rows of a list.
PANE_MIN_HEIGHT = 72
## Width of a splitter's handle, pixels: wide enough to grab with the mouse.
HANDLE_WIDTH = 7
## Length of the grip drawn across the middle of a handle, pixels.
GRIP_LENGTH = 28
## Width of the grip's line, pixels.
GRIP_LINE = 1
## Distance between the grip's two lines, pixels.
GRIP_GAP = 2
## Stretch factor of a pane that takes the space a window gains (a form, a canvas, an editor).
WIDE = 1
## Stretch factor of a pane that keeps its size while the window grows (a list, a navigator).
NARROW = 0
## Dynamic property of a fit area (scroll_wrap()): True. Frame, not content: the tests look through it.
FIT_PROPERTY = "capsule_fit"
## Dynamic property of a widget that is a panel without being a view (a picture canvas, widgets.PixelView): True.
PANEL_PROPERTY = "capsule_panel"
## Halves a length (centring the grip).
HALF = 2
## Dynamic property of a splitter handle whose grip its Splitter paints: True.
GRIP_PROPERTY = "capsule_grip"
## Fewest panes a splitter splits (two: one boundary).
MIN_PANES = 2

## Directions of a box layout that lay its items out left to right (or right to left).
_ACROSS = (QtWidgets.QBoxLayout.Direction.LeftToRight, QtWidgets.QBoxLayout.Direction.RightToLeft)
## Widgets that are a panel by themselves: views that scroll and the containers that page or split panels.
_PANEL_TYPES = (QtWidgets.QAbstractScrollArea, QtWidgets.QTabWidget, QtWidgets.QStackedWidget, QtWidgets.QSplitter)
## Widgets that hold a view without being a panel: a combo box's popup list, a header, a spin box's line.
_NOT_PANELS = (QtWidgets.QComboBox, QtWidgets.QHeaderView, QtWidgets.QAbstractSpinBox)


# -- what a panel is -------------------------------------------------------------------------------------------

def is_view(widget: QtWidgets.QWidget) -> bool:
   """!Whether a widget scrolls by itself (a list, table, tree, text view, canvas or scroll page).
   @param widget  QWidget
   @return True for a QAbstractScrollArea that is not part of a field (header, combo popup)
   """
   return isinstance(widget, QtWidgets.QAbstractScrollArea) and not isinstance(widget, _NOT_PANELS)


def holds_panel(widget: QtWidgets.QWidget) -> bool:
   """!Whether a widget is, or holds, a panel: a view, a tab widget, a stack, a splitter or a canvas marked with
   PANEL_PROPERTY (mark_panel()). Fields that hold a view
   of their own (a combo box's popup, a header) do not count, and neither does what is inside them.
   @param widget  QWidget
   @return True when the widget is a panel or contains one
   """
   marked = widget.property(PANEL_PROPERTY)   # None unless mark_panel() set it
   if isinstance(widget, _NOT_PANELS) or marked is False:
      return False
   if isinstance(widget, _PANEL_TYPES) or marked:
      return True
   # Not a child that is a window of its own (a popup, a dialog); the widget itself may have no parent yet (a
   # panel being built), which makes it a window to Qt.
   return any(holds_panel(c) for c in widget.findChildren(
      QtWidgets.QWidget, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly) if not c.isWindow())


def mark_panel(widget: QtWidgets.QWidget, panel: bool = True) -> None:
   """!Makes a widget count as a panel (holds_panel()) though it is no view: a picture or canvas that a page shows
   beside its forms, so split_box() gives it a pane of its own. Or, with panel False, makes a widget that would
   count not count, with what it holds: a strip of tool options in a stack above a canvas belongs to the canvas.
   @param widget  QWidget
   @param panel   True: a panel; False: never a panel
   @return None
   """
   widget.setProperty(PANEL_PROPERTY, panel)


def item_holds_panel(item: QtWidgets.QLayoutItem) -> bool:
   """!Whether a layout item (a widget, or a nested layout) is or holds a panel (holds_panel()).
   @param item  QLayoutItem
   @return True when it does
   """
   if item.widget() is not None:
      return holds_panel(item.widget())
   layout = item.layout()
   if layout is not None:
      return any(item_holds_panel(layout.itemAt(i)) for i in range(layout.count()))
   return False


def is_fit_area(widget: QtWidgets.QWidget) -> bool:
   """!Whether a widget is a fit area (scroll_wrap()): page frame, not content.
   @param widget  QWidget
   @return True for a fit area
   """
   return isinstance(widget, QtWidgets.QScrollArea) and bool(widget.property(FIT_PROPERTY))


# -- scroll bars when content does not fit ---------------------------------------------------------------------

def scroll_wrap(widget: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
   """!A fit area around a widget: the widget follows the area's size while it fits and keeps its minimum size when
   it does not, so scroll bars appear (both ways, as needed) instead of the widget being squashed.
   @param widget  the content
   @return QScrollArea marked with FIT_PROPERTY (no frame: it is not a view of its own)
   """
   area = QtWidgets.QScrollArea()
   area.setProperty(FIT_PROPERTY, True)
   area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
   area.setWidgetResizable(True)   # follows the area, bounded below by the widget's minimum size (hint)
   area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
   area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
   area.setWidget(widget)
   return area


def fit_panel(panel: QtWidgets.QWidget) -> QtWidgets.QScrollArea | None:
   """!Puts everything a hosted panel shows into a fit area inside the panel itself (the panel stays the widget its
   host and tests know): its layout moves to an inner widget, which Qt allows (QWidget::setLayout() takes a layout
   from the widget that had it and reparents the layout's widgets). Hosts call this for every panel they show.
   @param panel  an editor panel, or any page widget, after it built its layout
   @return the fit area (the same one when called again), or None for a widget without a layout
   """
   area = panel.property("capsule_fit_area")
   if isinstance(area, QtWidgets.QScrollArea):
      return area
   layout = panel.layout()
   if layout is None:
      return None
   # A panel holding no view yet may have greyed itself as a whole while it was built (widgets.set_enabled() does
   # that to a widget without views); around a fit area that would lock its scroll bars, so it greys its contents
   # instead (D-40 RW: no ancestor of a scroll area is disabled).
   off = panel.testAttribute(QtCore.Qt.WidgetAttribute.WA_ForceDisabled)
   if off:
      panel.setEnabled(True)
   inner = QtWidgets.QWidget()
   inner.setLayout(layout)   # takes the layout and its widgets from the panel
   area = scroll_wrap(inner)
   outer = QtWidgets.QVBoxLayout(panel)
   outer.setContentsMargins(0, 0, 0, 0)
   outer.addWidget(area)
   panel.setProperty("capsule_fit_area", area)
   if off:
      from .widgets import set_enabled   # here: widgets imports this module
      set_enabled(panel, False)
   return area


# -- resizable panes -------------------------------------------------------------------------------------------

def paint_grip(handle: QtWidgets.QSplitterHandle) -> None:
   """!Paints a splitter handle's grip: two short lines across its middle, so the handle shows where to drag.
   @param handle  QSplitterHandle (called while it paints)
   @return None
   """
   painter = QtGui.QPainter(handle)
   painter.setPen(QtGui.QPen(handle.palette().color(QtGui.QPalette.ColorRole.Mid), GRIP_LINE))
   r = handle.rect()
   mid_x, mid_y = r.width() // HALF, r.height() // HALF
   half = GRIP_LENGTH // HALF
   for offset in (-GRIP_GAP // HALF, GRIP_GAP - GRIP_GAP // HALF):
      if handle.orientation() == QtCore.Qt.Orientation.Horizontal:   # side by side: the handle is upright
         x = mid_x + offset
         painter.drawLine(x, max(0, mid_y - half), x, min(r.height(), mid_y + half))
      else:
         y = mid_y + offset
         painter.drawLine(max(0, mid_x - half), y, min(r.width(), mid_x + half), y)
   painter.end()


class Splitter(QtWidgets.QSplitter):
   """!A QSplitter whose handles show a grip (paint_grip()) and whose panes start at a usable size; set up by
   setup_splitter().

   Qt starts panes at their size hints and takes what is missing from every pane alike, so a fit area (whose own
   minimum is small) could start narrower than its form and show scroll bars in a window that has room. Instead,
   whenever the splitter shows or is resized, until the user drags one of its handles, place() gives each pane its
   share of the space by the stretch factors, as a box layout would, or more when it wants more: its starting size
   (setup_splitter()'s sizes), else its content's minimum (a view: its size hint). Only when the wanted sizes do
   not fit are they scaled down (never below PANE_MIN_WIDTH x PANE_MIN_HEIGHT; the panes scroll). Once the user
   drags a handle, Qt's own rules apply: the boundaries stay where the user put them and a resize goes by the
   stretch factors.
   """

   def __init__(self, orientation: QtCore.Qt.Orientation, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the splitter.
      @param orientation  Qt.Horizontal: side by side; Qt.Vertical: stacked
      @param parent       parent widget
      """
      super().__init__(orientation, parent)
      ## Starting size of each pane along the splitter (None: from its content), or None for all from their content.
      self.starts = None
      ## Whether the user dragged a handle (place() no longer runs).
      self.dragged = False
      self.splitterMoved.connect(lambda _pos, _index: self._user_moved())

   def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
      """!Paints the grip of this splitter's handles (paint_grip()) in place of the style's.
      @param watched  one of its handles (_grip_handles() installs the filter)
      @param event    QEvent
      @return True for a handle's paint event (painted here), False otherwise
      """
      if event.type() == QtCore.QEvent.Type.Paint and isinstance(watched, QtWidgets.QSplitterHandle):
         paint_grip(watched)
         return True
      return False

   def _grip_handles(self) -> None:
      """!Has this splitter paint the grip of each handle it made (once per handle; new panes add handles).
      @return None
      """
      for i in range(self.count()):
         handle = self.handle(i)
         if handle is not None and not handle.property(GRIP_PROPERTY):
            handle.setProperty(GRIP_PROPERTY, True)
            handle.installEventFilter(self)

   def _user_moved(self) -> None:
      """!A handle was dragged (QSplitter.splitterMoved comes from the user only): the panes are the user's now.
      @return None
      """
      self.dragged = True

   def showEvent(self, event: QtGui.QShowEvent) -> None:
      """!Places the panes when the splitter shows (Qt laid it out already: its size is known).
      @param event  QShowEvent
      @return None
      """
      super().showEvent(event)
      self._grip_handles()
      if not self.dragged:
         self.place()

   def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
      """!Places the panes again for the new size until the user drags a handle (a page is often shown at a
      provisional size before its window lays it out); after that Qt's stretch factors share the change.
      @param event  QResizeEvent
      @return None
      """
      super().resizeEvent(event)
      self._grip_handles()
      if not self.dragged and self.isVisible():
         self.place()

   def _wanted(self, i: int) -> int:
      """!The size pane i starts at before the space left is shared: its starting size, else its content's
      minimum (a view's size hint: lists and tables are usable at that size), at least the pane minimum.
      @param i  pane index
      @return pixels along the splitter
      """
      across = self.orientation() == QtCore.Qt.Orientation.Horizontal
      least = PANE_MIN_WIDTH if across else PANE_MIN_HEIGHT
      start = self.starts[i] if self.starts and i < len(self.starts) else None
      if start is not None:
         return max(start, least)
      w = self.widget(i)
      if is_fit_area(w) and w.widget() is not None:
         hint = w.widget().minimumSizeHint()
      else:
         hint = w.sizeHint()
      return max(hint.width() if across else hint.height(), least)

   def place(self) -> None:
      """!Gives each pane its share of the space by the stretch factors (equal shares when none has one), or its
      wanted size (_wanted()) when that is more; scales the wanted sizes down when they do not fit.
      @return None
      """
      count = self.count()
      across = self.orientation() == QtCore.Qt.Orientation.Horizontal
      total = (self.width() if across else self.height()) - self.handleWidth() * max(count - 1, 0)
      if count < MIN_PANES or total <= 0:
         return
      wanted = [self._wanted(i) for i in range(count)]
      need = sum(wanted)
      if need >= total:   # not even the minimums fit: shrink each alike (the panes scroll)
         least = PANE_MIN_WIDTH if across else PANE_MIN_HEIGHT
         self.setSizes([max(least, w * total // need) for w in wanted])
         return
      policy = [self.widget(i).sizePolicy() for i in range(count)]
      weights = [p.horizontalStretch() if across else p.verticalStretch() for p in policy]
      if not any(weights):
         weights = [1] * count
      share = sum(weights)
      # Each pane gets its share of the whole by its stretch factor, or what it wants when that is more; the panes
      # above what they want then give back what is too much, each in proportion to its surplus.
      sizes = [max(w, total * k // share) for w, k in zip(wanted, weights)]
      surplus = [size - w for size, w in zip(sizes, wanted)]
      over, spare = sum(sizes) - total, sum(surplus)
      if over > 0 and spare > 0:
         sizes = [size - over * extra // spare for size, extra in zip(sizes, surplus)]
      sizes[weights.index(max(weights))] += total - sum(sizes)   # the rounding goes to the widest stretch
      self.setSizes(sizes)


def pane(content: QtWidgets.QWidget) -> QtWidgets.QWidget:
   """!A splitter pane for a widget: a view as it is (it scrolls by itself), anything else in a fit area; either
   way at least PANE_MIN_WIDTH x PANE_MIN_HEIGHT, so it can be dragged small but never to nothing.
   @param content  the pane's widget
   @return the widget to add to the splitter (the content itself, or its fit area)
   """
   outer = content if is_view(content) else scroll_wrap(content)
   outer.setMinimumSize(PANE_MIN_WIDTH, PANE_MIN_HEIGHT)
   return outer


def setup_splitter(split: QtWidgets.QSplitter, stretch: Sequence[int] | None = None,
                   sizes: Sequence[int | None] | None = None) -> QtWidgets.QSplitter:
   """!Gives a splitter the panes' rules: every child becomes a pane (pane(): a fit area unless it is a view), no
   pane collapses, the handle is wide enough to grab.
   @param split    QSplitter (a Splitter shows a grip)
   @param stretch  stretch factor of each pane (WIDE / NARROW), or None to keep Qt's
   @param sizes    starting size of each pane along the splitter, pixels (None: from its content, see
                   Splitter.place()), or None for all from their content
   @return the splitter
   """
   split.setChildrenCollapsible(False)
   split.setHandleWidth(HANDLE_WIDTH)
   split.setOpaqueResize(True)
   for i in range(split.count()):
      child = split.widget(i)
      if child.minimumWidth() >= PANE_MIN_WIDTH and child.minimumHeight() >= PANE_MIN_HEIGHT and \
            (is_view(child) or is_fit_area(child)):
         continue   # a pane already
      wrapped = pane(child)   # moving a child into its fit area takes it out of the splitter (Qt's ChildRemoved)
      if wrapped is not child:
         split.insertWidget(i, wrapped)
   for i, factor in enumerate(stretch or ()):
      split.setStretchFactor(i, factor)
   if isinstance(split, Splitter):
      split.starts = list(sizes) if sizes else None   # placed when it first shows (Splitter.place())
   elif sizes:
      across = split.orientation() == QtCore.Qt.Orientation.Horizontal
      hints = [split.widget(i).sizeHint() for i in range(split.count())]
      split.setSizes([(h.width() if across else h.height()) if size is None else size
                      for size, h in zip(sizes, hints)])
   return split


def splitter(orientation: QtCore.Qt.Orientation, panes: Sequence[QtWidgets.QWidget],
             stretch: Sequence[int] | None = None, sizes: Sequence[int | None] | None = None) -> Splitter:
   """!A splitter of panes (setup_splitter()).
   @param orientation  Qt.Horizontal: side by side; Qt.Vertical: stacked
   @param panes        the panes' widgets, in order
   @param stretch      stretch factor of each pane, or None
   @param sizes        starting size of each pane along the splitter, pixels (None: from its content), or None
   @return Splitter
   """
   split = Splitter(orientation)
   for w in panes:
      split.addWidget(w)
   return setup_splitter(split, stretch, sizes)


def _content_of(items: list[tuple[QtWidgets.QLayoutItem, int]], direction: QtWidgets.QBoxLayout.Direction) \
      -> QtWidgets.QWidget:
   """!One pane's content from the layout items split_box() gathered for it.
   @param items      (item, stretch) pairs: a panel and the items that followed it
   @param direction  the box layout's direction (the pane lays its items out the same way)
   @return the widget (the panel's own widget when it is alone)
   """
   first = items[0][0]
   if len(items) == 1 and first.widget() is not None:
      return first.widget()
   if len(items) == 1 and first.layout() is not None:
      layout = first.layout()
      margins = layout.contentsMargins()   # a nested layout's (0 unless set); a widget's own would be the style's
      layout.setParent(None)
      holder = QtWidgets.QWidget()
      holder.setLayout(layout)
      layout.setContentsMargins(margins)
      return holder
   holder = QtWidgets.QWidget()
   box = QtWidgets.QBoxLayout(direction, holder)
   box.setContentsMargins(0, 0, 0, 0)
   for item, factor in items:
      _put_back(box, item, factor)
   return holder


def _put_back(layout: QtWidgets.QBoxLayout, item: QtWidgets.QLayoutItem, factor: int) -> None:
   """!Adds a layout item taken from another box layout.
   @param layout  QBoxLayout
   @param item    a widget item, a nested layout or a spacer
   @param factor  its stretch factor
   @return None
   """
   if item.widget() is not None:
      layout.addWidget(item.widget(), factor, item.alignment())
   elif item.layout() is not None:
      nested = item.layout()
      nested.setParent(None)
      layout.addLayout(nested, factor)
   elif item.spacerItem() is not None:
      layout.addItem(item.spacerItem())
      layout.setStretch(layout.count() - 1, factor)


def split_box(layout: QtWidgets.QBoxLayout, sizes: Sequence[int | None] | None = None,
              every: bool = False) -> Splitter | None:
   """!Turns the panels of a box layout built already into the panes of a splitter, in place: the user drags the
   boundaries between them.

   Each item that holds a panel (item_holds_panel()) starts a pane; the items after it, up to the next panel (or
   the end), join its pane, laid out the same way (a list's buttons, the form under it). Items before the first
   panel stay in the layout, before the splitter (a heading or a tool row over all the panes); a stretch at the
   end is dropped (the panes take that space). With every, each item that is not a spacer starts a pane (a column of
   settings beside two lists, two forms side by side).
   Each pane's stretch factor is its first item's in the layout. The layouts and widgets keep working: a nested
   layout moves into its pane.
   @param layout  a QHBoxLayout (panes side by side) or QVBoxLayout (stacked)
   @param sizes   starting size of each pane along the splitter, pixels (None: from its content), or None
   @param every   True: every item that is not a spacer is a pane
   @return the splitter, or None when the layout holds fewer than two panels (nothing to split)
   """
   count = layout.count()
   if every:
      panels = [i for i in range(count) if layout.itemAt(i).spacerItem() is None]
   else:
      panels = [i for i in range(count) if item_holds_panel(layout.itemAt(i))]
   if len(panels) < MIN_PANES:
      return None
   factors = [layout.stretch(i) for i in range(count)]
   items = [(layout.takeAt(0), factors[i]) for i in range(count)]
   lead = items[:panels[0]]
   end = len(items)
   while end > panels[-1] + 1 and items[end - 1][0].spacerItem() is not None and \
         items[end - 1][0].spacerItem().expandingDirections():
      end -= 1   # a stretch at the end kept the panels together; the splitter's panes take that space now
   bounds = panels + [end]
   direction = layout.direction()
   contents = [_content_of(items[start:end], direction) for start, end in zip(bounds, bounds[1:])]
   orientation = QtCore.Qt.Orientation.Horizontal if direction in _ACROSS else QtCore.Qt.Orientation.Vertical
   split = splitter(orientation, contents, [factors[i] for i in panels], sizes)
   for item, factor in lead:
      _put_back(layout, item, factor)
   layout.addWidget(split, WIDE)
   return split
