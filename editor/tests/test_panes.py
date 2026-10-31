#!/usr/bin/env python3
"""!Resizable panels and scroll bars on every page (D-40 RZ): every Studio page and every standalone editor window,
offscreen, on copies of the map sandbox, the Starter and a tiny audio game.

For each window, with each of its panels in front in turn:
  - **fits a small screen**: the window's minimum size hint is at most SMALL_SCREEN (a window can always be made
    that small; nothing forces it larger than a small laptop's screen);
  - **scrolls instead of squashing**: shrunk to SHRUNK, no widget is smaller than the minimum size its layout
    gives it (it would be squashed or cut off), and every scroll area whose content is larger than its view shows
    the scroll bar that direction needs, enabled (never ScrollBarAlwaysOff);
  - **no locked scroll bar**: every scroll area (shown or not) and both its bars are enabled, so no ancestor of one
    is disabled (D-40 RW);
  - **resizable boundaries**: at NORMAL size, every visible splitter keeps its panes (not collapsible) and every
    handle moves its boundary when dragged with the mouse (press, move, release), read back from sizes().
Once per window, the page's frame (everything outside the content scroll pages) is walked: no box layout holds two
panels side by side or stacked (ui/panes.py item_holds_panel(): views, tab widgets, stacks, splitters), so every
boundary between panels is a splitter's. The rule is the same one ui/panes.py split_box() applies, so a new page
that lays two panels out in a plain box layout, or forces a large window, fails here.
Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

import audio_fixture as af  # noqa: E402
from capsule_studio.core import audio_render as ar  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402

## Largest minimum size a window may ask for (pixels): an 800 x 600 screen, the smallest still in use (netbooks,
## small laptops at a large text scale, a window beside another on a 1600-wide screen), minus room for the window's
## title bar and the desktop's panel.
SMALL_SCREEN = (800, 540)
## The size windows are shrunk to for the scroll checks (pixels): smaller than every page's content.
SHRUNK = (640, 400)
## The size the splitter handles are dragged at (pixels): the panes have room to move.
NORMAL = (1280, 800)
## How far a handle is dragged (pixels).
DRAG = 24
## Times the event loop runs to settle (scheduled refreshes post more events).
SETTLE_ROUNDS = 4
## Slack allowed when comparing a widget's size with its minimum (pixels): rounding in nested layouts.
SLACK = 1
## Widgets whose parts are their own business: their children are not checked for squashing.
if QtWidgets is not None:
   OPAQUE = (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QToolBar, QtWidgets.QMenuBar,
             QtWidgets.QStatusBar, QtWidgets.QTabBar, QtWidgets.QAbstractScrollArea, QtWidgets.QSplitterHandle)


def smart_min(w: QtWidgets.QWidget) -> QtCore.QSize:
   """!The minimum size a layout gives a widget (Qt's qSmartMinSize()): its minimumSize() where set, else its
   minimumSizeHint() (its sizeHint() when the policy cannot shrink), nothing when the policy ignores hints.
   @param w  QWidget
   @return QSize
   """
   policy = w.sizePolicy()
   hint, small, explicit = w.sizeHint(), w.minimumSizeHint(), w.minimumSize()
   size = []
   for p, h, s, e in ((policy.horizontalPolicy(), hint.width(), small.width(), explicit.width()),
                      (policy.verticalPolicy(), hint.height(), small.height(), explicit.height())):
      flags = QtWidgets.QSizePolicy.PolicyFlag
      value = p.value if hasattr(p, "value") else int(p)
      if e > 0:
         size.append(e)
      elif value & flags.IgnoreFlag.value:
         size.append(0)
      elif value & flags.ShrinkFlag.value:
         size.append(max(s, 0))
      else:
         size.append(max(h, 0))
   return QtCore.QSize(*size)


def drag(handle: QtWidgets.QSplitterHandle, delta: int) -> None:
   """!Drags a splitter handle with the mouse (press, move, release), as the user would.
   @param handle  QSplitterHandle
   @param delta   pixels along the splitter (positive: right / down)
   @return None
   """
   start = QtCore.QPointF(handle.rect().center())
   horizontal = handle.orientation() == QtCore.Qt.Orientation.Horizontal
   end = start + (QtCore.QPointF(delta, 0) if horizontal else QtCore.QPointF(0, delta))
   left = QtCore.Qt.MouseButton.LeftButton
   none = QtCore.Qt.MouseButton.NoButton
   mods = QtCore.Qt.KeyboardModifier.NoModifier
   for kind, pos, button, buttons in ((QtCore.QEvent.Type.MouseButtonPress, start, left, left),
                                      (QtCore.QEvent.Type.MouseMove, end, none, left),
                                      (QtCore.QEvent.Type.MouseButtonRelease, end, left, none)):
      event = QtGui.QMouseEvent(kind, pos, handle.mapToGlobal(pos), button, buttons, mods)
      QtWidgets.QApplication.sendEvent(handle, event)


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class PanesTests(unittest.TestCase):
   """!Opens every editor window and Studio page and checks their panels' boundaries and scroll bars."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication; the games; settings and the renderer cache in a temporary folder.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
      ## Temporary root.
      cls.root = Path(tempfile.mkdtemp(prefix="capsule_panes_"))
      cls._old_cache = os.environ.get(ar.CACHE_ENV)
      os.environ[ar.CACHE_ENV] = str(cls.root / "cache")
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(cls.root / "settings"))
      apps = copy_engine_apps(cls.root / "apps", ["sandbox_map", "starter_battle"], ("data", "reference"))
      ## The map sandbox's project manifest.
      cls.manifest = apps / "sandbox_map" / "reference" / "project.json"
      ## The tiny audio game's audio manifest.
      cls.audio = af.make_game(cls.root / "games")

   @classmethod
   def tearDownClass(cls) -> None:
      """!Removes the temporary folder.
      @return None
      """
      if cls._old_cache is None:
         os.environ.pop(ar.CACHE_ENV, None)
      else:
         os.environ[ar.CACHE_ENV] = cls._old_cache
      shutil.rmtree(cls.root, ignore_errors=True)

   def setUp(self) -> None:
      """!No problems yet.
      @return None
      """
      ## What failed: one line each (each once).
      self.problems = []

   def problem(self, text: str) -> None:
      """!Records a failure once.
      @param text  what failed
      @return None
      """
      if text not in self.problems:
         self.problems.append(text)

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes, layout requests).
      @return None
      """
      for _ in range(SETTLE_ROUNDS):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   # -- what is checked ---------------------------------------------------------------------------------------

   def check_small_screen(self, label: str, window: QtWidgets.QWidget) -> None:
      """!The window's minimum size hint fits SMALL_SCREEN.
      @param label   where it is, for the messages
      @param window  the top-level window
      @return None
      """
      hint = window.minimumSizeHint()
      if hint.width() > SMALL_SCREEN[0] or hint.height() > SMALL_SCREEN[1]:
         self.problem(f"{label}: the window needs at least {hint.width()}x{hint.height()}, more than a small screen "
                      f"({SMALL_SCREEN[0]}x{SMALL_SCREEN[1]})")

   def check_fit(self, label: str, window: QtWidgets.QWidget) -> None:
      """!Shrunk to SHRUNK: nothing is squashed below its minimum, and every scroll area whose content overflows
      shows that direction's scroll bar, enabled.
      @param label   where it is
      @param window  the top-level window
      @return None
      """
      window.resize(*SHRUNK)
      self.settle()
      self._check_squash(label, window)
      for area in window.findChildren(QtWidgets.QScrollArea):
         if not area.isVisible() or area.widget() is None:
            continue
         # QWidget.size(): a widget may have an attribute of that name
         content, view = QtWidgets.QWidget.size(area.widget()), area.viewport().size()
         name = f"{label}: {type(area).__name__} of {type(area.widget()).__name__}"
         for over, bar, way in ((content.width() > view.width() + SLACK, area.horizontalScrollBar(), "horizontal"),
                                (content.height() > view.height() + SLACK, area.verticalScrollBar(), "vertical")):
            if over and not (bar.isVisible() and bar.isEnabled() and bar.maximum() > 0):
               self.problem(f"{name}: its content does not fit and no {way} scroll bar shows")
      for area in window.findChildren(QtWidgets.QAbstractScrollArea):
         if not area.isVisible() or isinstance(area, QtWidgets.QHeaderView):
            continue
         off = QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
         if off in (area.horizontalScrollBarPolicy(), area.verticalScrollBarPolicy()):
            self.problem(f"{label}: {type(area).__name__} in {type(area.parentWidget()).__name__}: "
                         "a scroll bar is switched off (ScrollBarAlwaysOff)")

   def _check_squash(self, label: str, widget: QtWidgets.QWidget) -> None:
      """!No visible widget under this one is smaller than the minimum its layout gives it.
      @param label   where it is
      @param widget  QWidget (its children are checked)
      @return None
      """
      for child in widget.findChildren(QtWidgets.QWidget,
                                       options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly):
         if child.isWindow() or not child.isVisible():
            continue
         need, size = smart_min(child), QtWidgets.QWidget.size(child)
         if size.width() + SLACK < need.width() or size.height() + SLACK < need.height():
            self.problem(f"{label}: {type(child).__name__} in {type(widget).__name__} is squashed to "
                         f"{size.width()}x{size.height()} (needs {need.width()}x{need.height()})")
            continue   # its own children follow it
         if not isinstance(child, OPAQUE):
            self._check_squash(label, child)

   def check_enabled(self, label: str, window: QtWidgets.QWidget) -> None:
      """!Every scroll area of the window (shown or not) and both its bars are enabled: none of its ancestors is
      disabled, so no scroll bar is locked.
      @param label   where it is
      @param window  the top-level window
      @return None
      """
      for area in window.findChildren(QtWidgets.QAbstractScrollArea):
         if area.window() is not window or isinstance(area, QtWidgets.QHeaderView):
            continue   # a combo box's popup list; a header follows its view
         name = f"{label}: {type(area).__name__} in {type(area.parentWidget()).__name__}"
         if not area.isEnabled():
            w = area
            while w.parentWidget() is not None and not w.parentWidget().isEnabled():
               w = w.parentWidget()
            self.problem(f"{name}: disabled (by {type(w).__name__}); its scroll bars are dead")
            continue
         for bar in (area.verticalScrollBar(), area.horizontalScrollBar()):
            if not bar.isEnabled():
               self.problem(f"{name}: its {bar.orientation().name} scroll bar is disabled")

   def check_splitters(self, label: str, window: QtWidgets.QWidget) -> None:
      """!At NORMAL size every visible splitter's handles move their boundaries when dragged; no pane collapses.
      @param label   where it is
      @param window  the top-level window
      @return None
      """
      from capsule_studio.ui.panes import HANDLE_WIDTH
      window.resize(*NORMAL)
      self.settle()
      for split in window.findChildren(QtWidgets.QSplitter):
         if not split.isVisible() or split.count() < 2:
            continue
         name = f"{label}: QSplitter of {', '.join(type(split.widget(i)).__name__ for i in range(split.count()))}"
         if split.childrenCollapsible():
            self.problem(f"{name}: its panes collapse to nothing when dragged far")
         if split.handleWidth() < HANDLE_WIDTH:
            self.problem(f"{name}: its handle is {split.handleWidth()} pixels wide (at least {HANDLE_WIDTH})")
         for i in range(1, split.count()):
            handle = split.handle(i)
            if not handle.isVisible():
               continue
            before = split.sizes()
            moved = False
            for delta in (DRAG, -DRAG):
               drag(handle, delta)
               self.settle()
               if split.sizes() != before:
                  moved = True
                  break
            if not moved:
               self.problem(f"{name}: dragging handle {i} does not move the boundary (sizes {before})")
            split.setSizes(before)
            self.settle()

   def check_frame(self, label: str, window: QtWidgets.QWidget) -> None:
      """!No box layout of the page's frame (outside its content scroll pages, through the fit areas) holds two
      panels: each boundary between panels is a splitter's.
      @param label   where it is
      @param window  the top-level window
      @return None
      """
      from capsule_studio.ui.panes import is_fit_area, item_holds_panel
      seen: set[int] = set()

      def layouts(layout: QtWidgets.QLayout) -> Iterator[QtWidgets.QLayout]:
         yield layout
         for i in range(layout.count()):
            if layout.itemAt(i).layout() is not None:
               yield from layouts(layout.itemAt(i).layout())

      def walk(widget: QtWidgets.QWidget, path: str) -> None:
         if id(widget) in seen:
            return
         seen.add(id(widget))
         if isinstance(widget, QtWidgets.QScrollArea) and not is_fit_area(widget):
            return   # a content page: its own layout scrolls with it
         if widget.layout() is not None:
            for lay in layouts(widget.layout()):
               if not isinstance(lay, QtWidgets.QBoxLayout):
                  continue
               found = [lay.itemAt(i) for i in range(lay.count()) if item_holds_panel(lay.itemAt(i))]
               if len(found) > 1:
                  kinds = ", ".join(type(it.widget() or it.layout()).__name__ for it in found)
                  self.problem(f"{label}: {path}{type(widget).__name__} lays out panels ({kinds}) in a box layout, "
                               "not a splitter: the boundary cannot be dragged")
         for child in widget.findChildren(QtWidgets.QWidget,
                                          options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly):
            if not child.isWindow() and not isinstance(child, (QtWidgets.QComboBox, QtWidgets.QHeaderView)):
               walk(child, path)

      for panel in getattr(window, "panels", None) or []:
         walk(panel, f"{getattr(panel, 'panel_id', type(panel).__name__)}/")
      central = window.centralWidget() if isinstance(window, QtWidgets.QMainWindow) else window
      if central is not None:
         walk(central, "")

   # -- windows -----------------------------------------------------------------------------------------------

   def panels(self, window: QtWidgets.QMainWindow) -> Iterator[QtWidgets.QWidget]:
      """!Shows each panel of a window in turn.
      @param window  an editor window
      @return iterator of the panel in front
      """
      panels = getattr(window, "panels", None) or [window.centralWidget()]
      for p in panels:
         tabs = getattr(window, "tabs", None)
         if isinstance(tabs, QtWidgets.QTabWidget) and tabs.indexOf(p) >= 0:
            tabs.setCurrentWidget(p)
         elif hasattr(window, "group_of"):   # the battle editor: show_panel() takes the panel
            window.show_panel(p)
         self.settle()
         yield p

   def check_window(self, label: str, window: QtWidgets.QMainWindow, top: QtWidgets.QWidget | None = None) -> None:
      """!Runs every check on a window with each of its panels in front.
      @param label   its name, for the messages
      @param window  an editor window (in the Studio: the page's window)
      @param top     the top-level window it is in (the Studio), or None for the window itself
      @return None
      """
      top = top or window
      self.check_frame(label, window)
      for p in self.panels(window):
         where = f"{label}/{getattr(p, 'panel_id', type(p).__name__)}"
         self.check_small_screen(where, top)
         self.check_fit(where, top)
         self.check_enabled(where, top)
         self.check_splitters(where, top)

   def files(self) -> dict[str, str]:
      """!The map sandbox's files.
      @return {"maps", "assets", "scripts", "battle"} -> path
      """
      from capsule_studio.core import project
      return {k: str(v) for k, v in project.game_files(project.open_project(self.manifest)).items()}

   def editor_windows(self) -> dict[str, Callable[[], QtWidgets.QMainWindow]]:
      """!The standalone editors: map, object, event, location, encounter, battle, project, assets, scripts, audio.
      @return {label: callable returning the window}
      """
      from capsule_studio.ui.audio_shell import AudioWindow
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.project_shell import ProjectWindow
      from capsule_studio.ui.script_shell import ScriptWindow
      from capsule_studio.ui.shell import EditorWindow
      from capsule_studio.ui.world_shell import WorldWindow
      f = self.files()
      return {
         "map editor": lambda: WorldWindow(None, f["maps"]),
         "object editor": lambda: WorldWindow([], f["maps"], "object-editor", "Object Editor"),
         "event editor": lambda: WorldWindow([], f["maps"], "event-editor", "Event Editor"),
         "location editor": lambda: WorldWindow([], f["maps"], "location-editor", "Location Editor"),
         "encounter editor": lambda: WorldWindow([], f["maps"], "encounter-editor", "Encounter Editor"),
         "battle editor": lambda: BattleWindow(None, f["battle"]),
         "project editor": lambda: ProjectWindow(str(self.manifest)),
         "asset editor": lambda: EditorWindow(None, f["assets"]),
         "script editor": lambda: ScriptWindow(f["scripts"]),
         "audio editor": lambda: AudioWindow(str(self.audio)),
      }

   def test_every_editor_window(self) -> None:
      """!The standalone editors, each on its file.
      @return None
      """
      for label, make in self.editor_windows().items():
         window = make()
         window.show()
         self.settle()
         self.check_window(label, window)
         start = getattr(window, "start", None)   # the start page: a window of its own until a file is open
         if isinstance(start, QtWidgets.QWidget):
            self.check_small_screen(f"{label} start page", start)
         window.hide()   # not close(): nothing is asked about; deleteLater frees it
         window.deleteLater()
         self.settle()
      self.assertFalse(self.problems, "\n".join(self.problems))   # every problem, one per line

   def test_every_studio_page(self) -> None:
      """!The Studio's pages on the map sandbox (its Audio page on the audio game), each inside the Studio.
      @return None
      """
      from capsule_studio.ui.studio_shell import PAGES, StudioWindow
      seen = set()
      for manifest in (self.manifest, self.audio.parent.parent / "reference" / "project.json"):
         studio = StudioWindow(str(manifest))
         studio.show()
         self.settle()
         self.check_frame("Studio", studio)
         for page in PAGES:
            if page.page_id in seen:
               continue
            studio.show_page(page.page_id)
            self.settle()
            window = studio.windows.get(page.page_id)
            if window is None:
               continue   # this game has no such file
            seen.add(page.page_id)
            self.check_window(f"Studio {page.page_id}", window, studio)
         studio.hide()
         studio.deleteLater()
         self.settle()
      self.assertEqual(seen, {p.page_id for p in PAGES})
      self.assertFalse(self.problems, "\n".join(self.problems))   # every problem, one per line

   def test_helpers(self) -> None:
      """!ui/panes.py: split_box() splits two panels and leaves the rest around the splitter; panes keep their
      minimum; fit_panel() keeps the panel the host's widget and scrolls its content.
      @return None
      """
      from capsule_studio.ui import panes
      page = QtWidgets.QWidget()
      lay = QtWidgets.QHBoxLayout(page)
      left = QtWidgets.QListWidget()
      right = QtWidgets.QVBoxLayout()
      form = QtWidgets.QFormLayout()
      field = QtWidgets.QLineEdit()
      form.addRow("Name", field)
      right.addLayout(form)
      right.addWidget(QtWidgets.QTableWidget(SETTLE_ROUNDS, SETTLE_ROUNDS))
      lay.addWidget(QtWidgets.QLabel("before"))
      lay.addWidget(left)
      lay.addLayout(right, panes.WIDE)
      split = panes.split_box(lay, [panes.PANE_MIN_WIDTH, None])
      self.assertIsInstance(split, panes.Splitter)
      self.assertEqual(split.count(), 2)
      self.assertIs(split.widget(0), left)   # a view is its own pane
      self.assertTrue(panes.is_fit_area(split.widget(1)))   # a form scrolls in its fit area
      self.assertTrue(split.widget(1).widget().isAncestorOf(field))
      self.assertEqual(lay.count(), 2)   # the label stays before the splitter
      self.assertIsNone(panes.split_box(QtWidgets.QHBoxLayout()))
      area = panes.fit_panel(page)
      self.assertIs(panes.fit_panel(page), area)
      self.assertTrue(area.widget().isAncestorOf(split))
      page.resize(*SHRUNK)
      page.show()
      self.settle()
      self.assertFalse(split.childrenCollapsible())
      self.assertGreaterEqual(left.width(), panes.PANE_MIN_WIDTH)
      drag(split.handle(1), DRAG)
      self.settle()
      self.assertEqual(split.sizes()[0], panes.PANE_MIN_WIDTH + DRAG)
      page.resize(panes.PANE_MIN_WIDTH, panes.PANE_MIN_HEIGHT)   # smaller than both panes: the panel scrolls
      self.settle()
      self.assertTrue(area.horizontalScrollBar().isVisible() and area.horizontalScrollBar().maximum() > 0)
      page.hide()
      page.deleteLater()
      self.settle()


if __name__ == "__main__":
   unittest.main()
