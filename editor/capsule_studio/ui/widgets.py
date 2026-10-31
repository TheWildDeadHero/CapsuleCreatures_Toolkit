"""!Small widgets shared by the panels."""
from __future__ import annotations

import logging
from collections.abc import Callable, Hashable, Iterable, Sequence
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import preview
from .panes import mark_panel

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
      mark_panel(self)   # [RZ] a picture beside a form is a pane of its own (panes.split_box())

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

   def minimumSizeHint(self) -> QtCore.QSize:
      """![RZ] The whole image at the current zoom (at least PIXEL_VIEW_MIN_SIZE square): a layout never makes the
      view smaller than its picture, so a pane too small for it scrolls (panes.scroll_wrap()) instead of cutting
      the picture's edges off.
      @return QSize
      """
      return self.sizeHint().expandedTo(QtCore.QSize(PIXEL_VIEW_MIN_SIZE, PIXEL_VIEW_MIN_SIZE))

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


## Value fields that step their value with the mouse wheel (combo boxes, spin boxes, sliders; never a scroll bar).
WHEEL_FIELDS = (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QSlider)
## The wheel guard installed on the application, or None before install_wheel_guard().
_WHEEL_GUARD: WheelGuard | None = None


def scrolling_page(widget: QtWidgets.QWidget) -> QtWidgets.QAbstractScrollArea | None:
   """!The scroll area a widget sits in (its page, a list or a text view), if any.
   @param widget  QWidget
   @return the nearest QAbstractScrollArea above it, or None
   """
   w = widget.parentWidget()
   while w is not None:
      if isinstance(w, QtWidgets.QAbstractScrollArea):
         return w
      w = w.parentWidget()
   return None


class WheelGuard(QtCore.QObject):
   """!Keeps the mouse wheel scrolling the page over value fields (one filter on the whole application).

   Qt gives the wheel to whatever combo box, spin box or slider is under the pointer, even one without the
   keyboard focus: the page stops scrolling there and the field's value changes (an edit, with an undo step)
   instead. Inside a scroll area this filter hands the wheel on to the page unless the field has the focus (the
   user clicked or tabbed into it, so the wheel steps it as before). Fields outside any scroll area keep Qt's
   behaviour; since D-40 RZ every hosted panel sits in a fit area (panes.fit_panel()), so every panel field leaves
   the wheel to its page until it has the focus. Fields also stop taking the focus from the wheel alone
   (Qt.WheelFocus -> Qt.StrongFocus), or the first wheel step over one would focus it and the next would change it.
   """

   def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
      """!Passes an unfocused field's wheel to its page; polishes fields' focus policy.
      @param watched  any object of the application
      @param event    QEvent
      @return True when the wheel goes on to the field's parents (the event is left ignored, so Qt delivers it
              to the widgets under the field, up to the scroll area); False otherwise
      """
      kind = event.type()
      if kind == QtCore.QEvent.Type.Wheel:
         if isinstance(watched, WHEEL_FIELDS) and not watched.hasFocus() and scrolling_page(watched) is not None:
            event.ignore()   # an ignored wheel event travels on to the parent widgets (QApplication::notify)
            return True
      elif kind == QtCore.QEvent.Type.Polish and isinstance(watched, WHEEL_FIELDS):
         unfocus_wheel(watched)
      elif kind == QtCore.QEvent.Type.EnabledChange and not _HoldState.active and \
            isinstance(watched, QtWidgets.QWidget) and watched.property(HELD_PROPERTY) and watched.isEnabled():
         # A part of a container set_contents_enabled() switched off was enabled by its own code (or by an
         # ancestor being enabled): it stays off until the container is on again, as a disabled parent's child
         # would. Its own state is kept for then (see _hold()).
         _hold(watched, False)
      return False


def unfocus_wheel(field: QtWidgets.QWidget) -> None:
   """!Makes a value field take the keyboard focus from clicks and Tab only, not from the wheel.
   @param field  QComboBox, QAbstractSpinBox or QSlider
   @return None
   """
   if field.focusPolicy() == QtCore.Qt.FocusPolicy.WheelFocus:
      field.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)


def install_wheel_guard() -> WheelGuard | None:
   """!Installs the WheelGuard on the running QApplication once (every panel and start page calls this, so each
   editor window and the Studio has it); fields that exist already get the focus policy now.
   @return the guard, or None without a QApplication
   """
   global _WHEEL_GUARD
   app = QtWidgets.QApplication.instance()
   if app is None:
      return None
   try:
      installed = _WHEEL_GUARD is not None and _WHEEL_GUARD.parent() is app
   except RuntimeError:   # the application that owned the old guard is gone (and the guard with it)
      installed = False
   if not installed:
      _WHEEL_GUARD = WheelGuard(app)   # owned by the application: lives as long as it does
      app.installEventFilter(_WHEEL_GUARD)
      for w in QtWidgets.QApplication.allWidgets():
         if isinstance(w, WHEEL_FIELDS):
            unfocus_wheel(w)
   return _WHEEL_GUARD


## Dynamic property marking a view lock_view() made read-only (True while locked).
LOCKED_PROPERTY = "capsule_view_locked"
## Dynamic property holding a locked view's own focus policy (an int), restored when it is unlocked.
LOCKED_FOCUS_PROPERTY = "capsule_view_focus"
## Dynamic property holding a locked text view's own read-only state, restored when it is unlocked.
LOCKED_READ_ONLY_PROPERTY = "capsule_view_read_only"
## Palette roles a locked view shows in their disabled colours (its text, items and background).
LOCKED_ROLES = (QtGui.QPalette.ColorRole.Text, QtGui.QPalette.ColorRole.WindowText, QtGui.QPalette.ColorRole.Base,
                QtGui.QPalette.ColorRole.AlternateBase, QtGui.QPalette.ColorRole.Highlight,
                QtGui.QPalette.ColorRole.HighlightedText, QtGui.QPalette.ColorRole.ButtonText)


def view_locked(view: QtWidgets.QAbstractScrollArea) -> bool:
   """!Whether lock_view() made a view read-only (what isEnabled() tells for any other widget).
   @param view  QAbstractScrollArea
   @return True while locked
   """
   return bool(view.property(LOCKED_PROPERTY))


def lock_view(view: QtWidgets.QAbstractScrollArea, locked: bool) -> None:
   """!Makes a list, table, tree or text view read-only, or editable again, without disabling it.

   setEnabled(False) on a view disables its scroll bars too: whatever does not fit can then not be read at all.
   A locked view stays enabled, so its scroll bars and the mouse wheel keep working, but its contents (the
   viewport, with any cell widgets in it) and headers are disabled, it takes no keyboard focus, a text view is
   read-only, and its text and items show in the disabled colours as before.
   @param view    QAbstractScrollArea (not a QScrollArea page: set_enabled() handles those)
   @param locked  True to lock, False to unlock
   @return None
   """
   view.setEnabled(True)
   if view.property(HELD_PROPERTY) and not _HoldState.active:
      # Its container is switched off (set_contents_enabled()): the view stays locked; this is its own state for
      # when the container is on again.
      view.setProperty(HELD_VIEW_ON_PROPERTY, not locked)
      return
   if locked == view_locked(view):
      return
   text = isinstance(view, (QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit))
   bars = (view.verticalScrollBar(), view.horizontalScrollBar())
   if locked:
      view.setProperty(LOCKED_FOCUS_PROPERTY, view.focusPolicy().value)
      if text:
         view.setProperty(LOCKED_READ_ONLY_PROPERTY, view.isReadOnly())
         view.setReadOnly(True)
      own = view.palette()
      grey = QtGui.QPalette(own)
      for group in (QtGui.QPalette.ColorGroup.Active, QtGui.QPalette.ColorGroup.Inactive):
         for role in LOCKED_ROLES:
            grey.setColor(group, role, own.color(QtGui.QPalette.ColorGroup.Disabled, role))
      view.setPalette(grey)
      for bar in bars:
         bar.setPalette(own)   # the scroll bars still work, so they keep their normal look
      if view.hasFocus():
         view.clearFocus()
      view.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
   else:
      view.setFocusPolicy(QtCore.Qt.FocusPolicy(int(view.property(LOCKED_FOCUS_PROPERTY))))
      if text:
         view.setReadOnly(bool(view.property(LOCKED_READ_ONLY_PROPERTY)))
      view.setPalette(QtGui.QPalette())   # no toolkit view has its own palette: back to the inherited one
      for bar in bars:
         bar.setPalette(QtGui.QPalette())
   view.viewport().setEnabled(not locked)
   if isinstance(view, QtWidgets.QTableView):
      view.horizontalHeader().setEnabled(not locked)
      view.verticalHeader().setEnabled(not locked)
   elif isinstance(view, QtWidgets.QTreeView):
      view.header().setEnabled(not locked)
   view.setProperty(LOCKED_PROPERTY, locked)


def set_enabled(widget: QtWidgets.QWidget, on: bool) -> None:
   """!setEnabled() that never disables a scroll bar: use it for every widget a panel switches off, the panel
   itself included ("no document", "nothing chosen").

   A view (list, table, tree, text view) is locked or unlocked (lock_view()); a QScrollArea page stays enabled
   while its contents are switched; a widget that holds views (a panel, a form, a group box) has its contents
   switched by set_contents_enabled(), so it and every container on the way to a view stay enabled; any other
   widget is enabled or disabled as usual. Qt disables every child of a disabled widget, its scroll bars too, so
   no widget above a scroll area may be disabled.
   @param widget  QWidget
   @param on      True to enable (editable), False to disable (read-only)
   @return None
   """
   if isinstance(widget, QtWidgets.QScrollArea):
      widget.setEnabled(True)
      page = widget.widget()
      if page is not None:
         set_enabled(page, on)
   elif isinstance(widget, QtWidgets.QAbstractScrollArea):
      lock_view(widget, not on)
   elif _holds_view(widget) or widget.property(CONTENTS_OFF_PROPERTY):   # (its parts were held: release them)
      set_contents_enabled(widget, on)
   else:
      widget.setEnabled(on)


def _holds_view(widget: QtWidgets.QWidget) -> bool:
   """!Whether a widget is or contains a scrolling view (not counting the popup lists of combo boxes).
   @param widget  QWidget
   @return True when set_contents_enabled() must look inside it
   """
   if isinstance(widget, QtWidgets.QAbstractScrollArea):
      return True
   if isinstance(widget, WHEEL_FIELDS):
      return False   # a combo box's popup list is its own business
   return any(_holds_view(child) for child in _child_widgets(widget))


def _child_widgets(widget: QtWidgets.QWidget) -> list[QtWidgets.QWidget]:
   """!A widget's direct child widgets, without separate windows (popups, dialogs).
   @param widget  QWidget
   @return list of QWidget
   """
   return [c for c in widget.findChildren(QtWidgets.QWidget, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly)
           if not c.isWindow()]


## Dynamic property of a container set_contents_enabled() switched off (True while its contents are off).
CONTENTS_OFF_PROPERTY = "capsule_contents_off"
## Dynamic property of a part (a view, or a widget that holds none) held off for its container (True while held).
HELD_PROPERTY = "capsule_held_off"
## Dynamic property of a held view: whether its own code wants it editable (restored when it is released).
HELD_VIEW_ON_PROPERTY = "capsule_held_view_on"
## Parts set_contents_enabled() never switches off: moving around is not editing (a tab bar shows another page,
## a splitter handle resizes them).
NAVIGATION = (QtWidgets.QTabBar, QtWidgets.QSplitterHandle)


class _HoldState:
   """!Whether set_contents_enabled() is changing parts right now (so their own code is not)."""

   ## True while set_contents_enabled() switches parts.
   active = False


def _off_above(widget: QtWidgets.QWidget) -> bool:
   """!Whether a container around a widget (up to its window) has its contents switched off.
   @param widget  QWidget
   @return True when set_contents_enabled() switched one of them off
   """
   w = widget.parentWidget()
   while w is not None:
      if w.property(CONTENTS_OFF_PROPERTY):
         return True
      if w.isWindow():
         return False
      w = w.parentWidget()
   return False


def _hold(part: QtWidgets.QWidget, on: bool) -> None:
   """!Holds one part of a container off, or releases it, keeping the part's own state (Qt's parent-child rule
   without a disabled parent).

   A view is locked (lock_view()); its own state is kept in HELD_VIEW_ON_PROPERTY. Any other part is disabled the
   way a disabled parent disables its child: Qt.WA_ForceDisabled (what its own setEnabled() sets) is cleared again,
   so it still tells the part's own state; WheelGuard holds a part its own code enables meanwhile.
   @param part  a view, or a widget that holds no view
   @param on    False to hold it off, True to release it to its own state
   @return None
   """
   view = isinstance(part, QtWidgets.QAbstractScrollArea) and not isinstance(part, QtWidgets.QScrollArea)
   held = bool(part.property(HELD_PROPERTY))
   if on and held and _off_above(part):
      return   # a container around it is still off (nested ones: the outer one wins, as Qt's rule does)
   was = _HoldState.active
   _HoldState.active = True
   try:
      if not on:
         if view:
            if not held:
               part.setProperty(HELD_VIEW_ON_PROPERTY, not view_locked(part))
            lock_view(part, True)
         elif part.isEnabled():
            part.setEnabled(False)
            part.setAttribute(QtCore.Qt.WidgetAttribute.WA_ForceDisabled, False)   # its own state stays "on"
         part.setProperty(HELD_PROPERTY, True)
      elif held:
         part.setProperty(HELD_PROPERTY, False)
         if view:
            lock_view(part, not bool(part.property(HELD_VIEW_ON_PROPERTY)))
         elif not part.testAttribute(QtCore.Qt.WidgetAttribute.WA_ForceDisabled):
            part.setEnabled(True)   # its own code did not switch it off meanwhile
   finally:
      _HoldState.active = was


def _switch_parts(container: QtWidgets.QWidget, on: bool) -> None:
   """!Holds or releases the parts of a container (see set_contents_enabled()); containers on the way to a view
   are enabled and looked into.
   @param container  QWidget
   @param on         True to release, False to hold
   @return None
   """
   for child in _child_widgets(container):
      if isinstance(child, NAVIGATION):
         continue
      if isinstance(child, QtWidgets.QScrollArea):   # a page: it scrolls; its contents are the parts
         child.setEnabled(True)
         page = child.widget()
         if page is not None and _holds_view(page):
            page.setEnabled(True)
            _switch_parts(page, on)
         elif page is not None:
            _hold(page, on)
      elif isinstance(child, QtWidgets.QAbstractScrollArea) or not _holds_view(child):
         _hold(child, on)
      else:
         child.setEnabled(True)
         _switch_parts(child, on)


def set_contents_enabled(container: QtWidgets.QWidget, on: bool) -> None:
   """!Switches everything in a container (a panel, a form, a group box, a tab widget) off or on again without
   locking a scroll bar: the container and every container on the way to a view stay enabled; the views are
   locked (lock_view()); every other part is disabled, greyed, as under a disabled parent.

   Each part keeps its own state, as Qt's parent-child rule does: a button its code disabled stays disabled when
   the container is on again, and a part its code enables while the container is off stays off until then.
   Call it again after building new parts into a container that is off (refresh() does, in the panels).
   @param container  QWidget
   @param on         True to enable
   @return None
   """
   if on and not container.property(CONTENTS_OFF_PROPERTY):
      container.setEnabled(True)   # never switched off (the usual refresh): nothing of its own is held
      return
   install_wheel_guard()   # its EnabledChange watch keeps held parts off (WheelGuard)
   was = _HoldState.active
   _HoldState.active = True
   try:
      container.setEnabled(True)
      container.setProperty(CONTENTS_OFF_PROPERTY, not on)
      _switch_parts(container, on)
   finally:
      _HoldState.active = was


def is_enabled(widget: QtWidgets.QWidget) -> bool:
   """!Whether set_enabled() last enabled a widget (a locked view, a container whose contents are off and a held
   part count as disabled).
   @param widget  QWidget
   @return True when it can be edited
   """
   if widget.property(CONTENTS_OFF_PROPERTY):
      return False
   if isinstance(widget, QtWidgets.QAbstractScrollArea) and not isinstance(widget, QtWidgets.QScrollArea):
      return widget.isEnabled() and not view_locked(widget)
   return widget.isEnabled()


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
      install_wheel_guard()   # every editor window and the Studio build a start page (see WheelGuard)
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

   def minimumSizeHint(self) -> QtCore.QSize:
      """!One picture wide (a scroll area scrolls sideways below that rather than cut it off).
      @return QSize
      """
      w = GRID_GAP + self.cell() + GRID_GAP
      return QtCore.QSize(w, self.heightForWidth(w))

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
   """!A scroll area holding a MetatileGrid (it scrolls down; sideways only when narrower than one picture).
   @param grid  MetatileGrid
   @return QScrollArea
   """
   area = QtWidgets.QScrollArea()
   area.setWidget(grid)
   area.setWidgetResizable(True)
   # No ScrollBarAlwaysOff: the grid reflows to the width, so a horizontal bar shows only when the view is
   # narrower than one picture (MetatileGrid.minimumSizeHint()), instead of cutting that picture off.
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
