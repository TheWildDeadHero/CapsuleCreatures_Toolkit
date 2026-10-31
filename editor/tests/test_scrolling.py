#!/usr/bin/env python3
"""!No scroll bar is ever locked (D-40 RB, RW): every editor window and every Studio page, offscreen, in a window
small enough that the panels' content is taller than the view; with a document open and its first entries chosen,
with a document open and nothing chosen, and with no document open at all.

In every state, every scroll area of a panel (pages, lists, tables, trees, text views) and both of its scroll bars
are enabled: a panel with nothing to show greys its fields with ui/widgets.py set_enabled() /
set_contents_enabled(), and a read-only view is locked (lock_view()), never disabled (Qt disables every child of a
disabled widget, scroll bars too). For each panel shown, every visible scroll area also:
  - has no ScrollBarAlwaysOff policy, unless ALWAYS_OFF_ALLOWED lists the case with its reason;
  - when it overflows: moves with its scroll bar's value and stays there, and moves with the mouse wheel over the
    view and over every value field in it (combo boxes, spin boxes, sliders), which keep their values
    (ui/widgets.py WheelGuard).
The Object editor, where the developer found the lock, is also checked on its own: wheeling over its whole form
scrolls the form and edits nothing.

QTest has no wheel, and Qt passes a wheel event on to the parent widgets only when it comes from the window
system, so wheel() does what QApplication::notify() does with one: it focuses the widget a wheel focuses
(Qt.WheelFocus), then delivers the event bottom-up until a widget accepts it.
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

## A window this small makes the panels' content taller (and wider) than their views (pixels).
SMALL_WINDOW = (640, 340)
## The Studio's window in the same test (its page list takes some width).
SMALL_STUDIO = (800, 400)
## One wheel notch (QWheelEvent angle delta, eighths of a degree).
NOTCH = 120
## Value fields wheeled over per scroll area (enough to cover each kind; the Object editor's form is wheeled whole).
FIELDS_PER_AREA = 8
## Times the event loop runs to settle (scheduled refreshes post more events).
SETTLE_ROUNDS = 4
## Pause before checking that a scroll bar's value stayed where it was put (no timer pins it), milliseconds.
STAY_MS = 30
## Where the wheel goes in a view (pixels from its viewport's top left corner): clear of any frame.
CORNER = (2, 2)
## Scroll areas whose ScrollBarAlwaysOff is allowed: class name -> reason.
ALWAYS_OFF_ALLOWED = {
   "QHeaderView": "a list's or table's header is a scroll area that follows its view; it has no bars of its own",
}
## The map of the map sandbox with objects (the Object editor's check).
OBJECT_MAP = "showcase"
## An object of that map (its row in the Object editor's list).
OBJECT_ROW = 1

if QtWidgets is not None:
   ## Value fields that must leave the wheel to the page while unfocused.
   FIELDS = (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QSlider)


def field_value(field: QtWidgets.QWidget) -> object:
   """!A value field's value, to tell whether a wheel changed it.
   @param field  QComboBox, QAbstractSpinBox or QSlider
   @return its value
   """
   if isinstance(field, QtWidgets.QComboBox):
      return field.currentIndex()
   if isinstance(field, QtWidgets.QSlider):
      return field.value()
   return field.text()


def wheel(over: QtWidgets.QWidget, local: QtCore.QPoint, notches: int = -1) -> QtWidgets.QWidget | None:
   """!Turns the mouse wheel over a point, as the window system's wheel event would (see the module docstring).
   @param over     widget the point is in
   @param local    the point, in its coordinates
   @param notches  wheel notches (negative: down / towards the end)
   @return the widget that took the event, or None
   """
   gpos = over.mapToGlobal(local)
   top = over.window()
   w = top.childAt(top.mapFromGlobal(gpos)) or over
   focus = w
   wheel_focus = QtCore.Qt.FocusPolicy.WheelFocus.value
   while focus is not None:   # QApplicationPrivate::giveFocusAccordingToFocusPolicy()
      if focus.isEnabled() and focus.focusPolicy().value & wheel_focus == wheel_focus:
         focus.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
         break
      if focus.isWindow():
         break
      focus = focus.parentWidget()
   while w is not None:
      event = QtGui.QWheelEvent(QtCore.QPointF(w.mapFromGlobal(gpos)), QtCore.QPointF(gpos), QtCore.QPoint(),
                                QtCore.QPoint(0, notches * NOTCH), QtCore.Qt.MouseButton.NoButton,
                                QtCore.Qt.KeyboardModifier.NoModifier, QtCore.Qt.ScrollPhase.NoScrollPhase, False)
      if QtWidgets.QApplication.sendEvent(w, event) and event.isAccepted():
         return w
      if w.isWindow():
         return None
      w = w.parentWidget()
   return None


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class ScrollingTests(unittest.TestCase):
   """!Opens every editor window and Studio page on copies of the map sandbox, the Starter and a tiny audio game."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication; the games; settings and the renderer cache in a temporary folder.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
      ## Temporary root.
      cls.root = Path(tempfile.mkdtemp(prefix="capsule_scrolling_"))
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
      ## What failed: one line each.
      self.problems = []

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(SETTLE_ROUNDS):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def files(self) -> dict[str, Path]:
      """!The map sandbox's files.
      @return {"maps", "assets", "scripts", "battle"} -> path
      """
      from capsule_studio.core import project
      return project.game_files(project.open_project(self.manifest))

   # -- what is checked ---------------------------------------------------------------------------------------

   def check_enabled(self, label: str, panel: QtWidgets.QWidget) -> None:
      """!Every scroll area of a panel (shown or not) and both its scroll bars are enabled: none is locked.
      @param label  where it is, for the messages
      @param panel  the panel
      @return None
      """
      window = QtWidgets.QWidget.window(panel)   # a panel may have an attribute named "window"
      for area in panel.findChildren(QtWidgets.QAbstractScrollArea):
         if area.window() is not window or isinstance(area, QtWidgets.QHeaderView):
            continue   # a combo box's popup list; a header follows its view
         name = f"{label}: {type(area).__name__} in {type(area.parentWidget()).__name__}"
         if not area.isEnabled():
            self.problems.append(f"{name}: disabled (its scroll bars are dead)")
            continue
         for bar in (area.verticalScrollBar(), area.horizontalScrollBar()):
            if not bar.isEnabled():
               self.problems.append(f"{name}: its {bar.orientation().name} scroll bar is disabled")

   def check_area(self, label: str, panel: QtWidgets.QWidget, area: QtWidgets.QAbstractScrollArea) -> None:
      """!Checks one scroll area (see the module docstring); failures go to self.problems.
      @param label  where it is, for the messages
      @param panel  its panel
      @param area   the scroll area
      @return None
      """
      kind = type(area).__name__
      name = f"{label}: {kind} in {type(area.parentWidget()).__name__}"
      off = QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
      if off in (area.verticalScrollBarPolicy(), area.horizontalScrollBarPolicy()) and \
            kind not in ALWAYS_OFF_ALLOWED:
         self.problems.append(f"{name}: a scroll bar policy is ScrollBarAlwaysOff")
      if isinstance(area, QtWidgets.QHeaderView):
         return   # it follows its view
      if not area.isEnabled():
         return   # check_enabled() reports it
      bar = area.verticalScrollBar()
      if bar.maximum() <= 0:
         return
      middle = max(1, bar.maximum() // 2)
      bar.setValue(middle)
      self.settle()
      QtCore.QThread.msleep(STAY_MS)
      self.settle()
      if bar.value() != min(middle, bar.maximum()):
         self.problems.append(f"{name}: the bar was set to {middle} and is at {bar.value()}")
      bar.setValue(0)
      self.reveal(area)
      corner = QtCore.QPoint(*CORNER)
      top = area.window()
      hit = top.childAt(top.mapFromGlobal(area.viewport().mapToGlobal(corner)))
      if hit is not None and (hit is area.viewport() or area.viewport().isAncestorOf(hit)):
         wheel(area.viewport(), corner)
         self.settle()
         if bar.value() == 0:
            self.problems.append(f"{name}: the wheel does not scroll it")
      self.check_fields(name, area, FIELDS_PER_AREA)

   def reveal(self, widget: QtWidgets.QWidget) -> None:
      """!Scrolls the pages a widget is in so its top left corner shows (a view inside a page may be out of sight).
      @param widget  QWidget
      @return None
      """
      w = widget.parentWidget()
      while w is not None:
         if isinstance(w, QtWidgets.QScrollArea) and w.widget() is not None and w.widget().isAncestorOf(widget):
            w.ensureWidgetVisible(widget, 0, 0)
         w = w.parentWidget()
      self.settle()

   def check_fields(self, name: str, area: QtWidgets.QAbstractScrollArea, most: int) -> int:
      """!Wheels over the unfocused value fields inside a scroll area: the area must scroll and the fields keep their
      values.
      @param name  for the messages
      @param area  the scroll area
      @param most  fields to try at most
      @return fields tried
      """
      bar = area.verticalScrollBar()
      view = area.viewport()
      shown = QtCore.QRect(QtCore.QPoint(0, 0), view.size())
      tried = 0
      for field in view.findChildren(QtWidgets.QWidget):
         if tried >= most:
            break
         try:
            if not isinstance(field, FIELDS) or not field.isVisible() or not field.isEnabled():
               continue
         except RuntimeError:   # a refresh rebuilt the form (after a wheel that edited something)
            continue
         if isinstance(area, QtWidgets.QScrollArea):
            area.ensureWidgetVisible(field, 0, 0)
            self.settle()
         centre = field.mapTo(view, field.rect().center())
         if not shown.contains(centre) or bar.maximum() <= 0:
            continue
         tried += 1
         if field.hasFocus():
            area.setFocus()
         start, before = bar.value(), field_value(field)
         notches = -1 if start < bar.maximum() else 1   # towards the end, or back from it
         wheel(view, centre, notches)
         self.settle()
         if bar.value() == start:
            self.problems.append(f"{name}: the wheel over a {type(field).__name__} does not scroll it")
         if field_value(field) != before:
            self.problems.append(f"{name}: the wheel changed an unfocused {type(field).__name__}")
      return tried

   def check_panel(self, label: str, panel: QtWidgets.QWidget, pick: bool = True) -> None:
      """!Picks the first entry of the panel's lists (so its forms fill), or chooses nothing in them, and checks
      its scroll areas.
      @param label  where it is
      @param panel  the panel
      @param pick   True to pick the first entries, False to leave every list with nothing chosen
      @return None
      """
      self.settle()
      for v in panel.findChildren(QtWidgets.QAbstractItemView):
         model = v.model()
         if not v.isVisible() or model is None or not model.rowCount():
            continue
         if not pick:
            v.setCurrentIndex(QtCore.QModelIndex())
            v.clearSelection()
            self.settle()
         elif v.isEnabled() and not v.currentIndex().isValid():
            v.setCurrentIndex(model.index(0, 0))
            self.settle()
      self.check_enabled(label, panel)   # a disabled panel holding no scroll area locks no scroll bar
      areas = [a for a in panel.findChildren(QtWidgets.QAbstractScrollArea) if a.isVisible()]
      for area in areas:
         self.check_area(label, panel, area)

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

   def show_world_panels(self, window: QtWidgets.QMainWindow) -> None:
      """!A world window without a world shows its empty state (ui/world_shell.py NoWorldPage); its panels are
      shown here anyway, so their scroll bars are checked with no document too.
      @param window  any editor window
      @return None
      """
      body = getattr(window, "body", None)
      if isinstance(body, QtWidgets.QStackedWidget) and getattr(window, "tabs", None) is not None:
         body.setCurrentWidget(window.tabs)
         self.settle()

   def check_window(self, label: str, make: Callable[[], QtWidgets.QMainWindow], pick: bool = True) -> None:
      """!Opens an editor window small and checks every panel in it.
      @param label  its name, for the messages
      @param make   callable returning the window
      @param pick   True to pick the first entries of the lists, False to choose nothing
      @return None
      """
      window = make()
      window.resize(*SMALL_WINDOW)
      window.show()
      self.settle()
      self.show_world_panels(window)
      for p in self.panels(window):
         self.check_panel(f"{label}/{getattr(p, 'panel_id', type(p).__name__)}", p, pick)
      window.hide()   # not close(): nothing is asked about; deleteLater frees it
      window.deleteLater()
      self.settle()

   def editor_windows(self, open_files: bool) -> dict[str, Callable[[], QtWidgets.QMainWindow]]:
      """!The standalone editors: map, object, event, location, encounter, battle, project, assets, scripts, audio.
      @param open_files  True: each on the map sandbox's file (the audio editor on the audio game's); False: each
                         with no document open
      @return {label: callable returning the window}
      """
      from capsule_studio.ui.audio_shell import AudioWindow
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.project_shell import ProjectWindow
      from capsule_studio.ui.script_shell import ScriptWindow
      from capsule_studio.ui.shell import EditorWindow
      from capsule_studio.ui.world_shell import WorldWindow
      f = {key: str(path) for key, path in self.files().items()} if open_files else {}
      manifest = str(self.manifest) if open_files else None
      audio = str(self.audio) if open_files else None
      world = f.get("maps")
      return {
         "map editor": lambda: WorldWindow(None, world),
         "object editor": lambda: WorldWindow([], world, "object-editor", "Object Editor"),
         "event editor": lambda: WorldWindow([], world, "event-editor", "Event Editor"),
         "location editor": lambda: WorldWindow([], world, "location-editor", "Location Editor"),
         "encounter editor": lambda: WorldWindow([], world, "encounter-editor", "Encounter Editor"),
         "battle editor": lambda: BattleWindow(None, f.get("battle")),
         "project editor": lambda: ProjectWindow(manifest),
         "asset editor": lambda: EditorWindow(None, f.get("assets")),
         "script editor": lambda: ScriptWindow(f.get("scripts")),
         "audio editor": lambda: AudioWindow(audio),
      }

   def test_every_editor_window(self) -> None:
      """!The standalone editors, each on its file, with the first entries of their lists chosen.
      @return None
      """
      for label, make in self.editor_windows(True).items():
         self.check_window(label, make)
      self.assertFalse(self.problems, "\n".join(self.problems))   # every problem, one per line

   def test_every_editor_window_nothing_chosen(self) -> None:
      """!The standalone editors, each on its file, with nothing chosen in any list (empty forms).
      @return None
      """
      for label, make in self.editor_windows(True).items():
         self.check_window(label, make, pick=False)
      self.assertFalse(self.problems, "\n".join(self.problems))   # every problem, one per line

   def test_every_editor_window_no_document(self) -> None:
      """!The standalone editors with no document open (Continue without a file): every panel greys its fields
      and keeps every scroll bar.
      @return None
      """
      for label, make in self.editor_windows(False).items():
         self.check_window(f"{label} (no document)", make)
      self.assertFalse(self.problems, "\n".join(self.problems))   # every problem, one per line

   def check_studio(self, manifests: list[Path | None], seen: set[str], pick: bool, note: str) -> None:
      """!Shows every Studio page not seen yet, for each game in turn, and checks each panel on it.
      @param manifests  project manifests to open (None: the Studio with no project)
      @param seen       page ids checked already (updated)
      @param pick       True to pick the first entries of the lists, False to choose nothing
      @param note       added to the labels
      @return None
      """
      from capsule_studio.ui.studio_shell import PAGES, StudioWindow
      for manifest in manifests:
         studio = StudioWindow(str(manifest) if manifest is not None else None)
         studio.resize(*SMALL_STUDIO)
         studio.show()
         self.settle()
         for page in PAGES:
            if page.page_id in seen:
               continue
            studio.show_page(page.page_id)
            self.settle()
            window = studio.windows.get(page.page_id)
            if window is None:
               continue   # this game has no such file
            seen.add(page.page_id)
            self.show_world_panels(window)
            for p in self.panels(window):
               self.check_panel(f"Studio{note} {page.page_id}/{getattr(p, 'panel_id', type(p).__name__)}", p, pick)
         studio.hide()
         studio.deleteLater()
         self.settle()

   def test_every_studio_page(self) -> None:
      """!The Studio's pages on the map sandbox, and its Audio page on the audio game: first entries chosen, then
      nothing chosen.
      @return None
      """
      from capsule_studio.ui.studio_shell import PAGES
      games = [self.manifest, self.audio.parent.parent / "reference" / "project.json"]
      for pick, note in ((True, ""), (False, " (nothing chosen)")):
         seen = set()
         self.check_studio(games, seen, pick, note)
         self.assertEqual(seen, {p.page_id for p in PAGES})
      self.assertFalse(self.problems, "\n".join(self.problems))   # every problem, one per line

   def test_every_studio_page_no_document(self) -> None:
      """!The Studio with no project open: every page is built empty, and every panel keeps its scroll bars.
      @return None
      """
      from capsule_studio.ui.studio_shell import PAGES
      seen = set()
      self.check_studio([None], seen, True, " (no document)")
      self.assertEqual(seen, {p.page_id for p in PAGES})
      self.assertFalse(self.problems, "\n".join(self.problems))   # every problem, one per line

   def test_object_editor_form(self) -> None:
      """!The reported case: the Object editor's form scrolls under the wheel wherever the pointer is, its fields
      keep their values (no edit, no undo step), a focused field still takes the wheel, and a read-only route box
      keeps its scroll bar.
      @return None
      """
      from capsule_studio.ui.widgets import is_enabled
      from capsule_studio.ui.world_shell import WorldWindow
      w = WorldWindow([], str(self.files()["maps"]), "object-editor", "Object Editor")
      w.resize(*SMALL_WINDOW)
      w.show()
      self.settle()
      ob = w.panels[0]
      ob.map_box.setCurrentText(OBJECT_MAP)
      self.settle()
      ob.tree.setCurrentItem(ob.tree.topLevelItem(OBJECT_ROW))
      self.settle()
      form = next(a for a in ob.findChildren(QtWidgets.QScrollArea) if a.isVisible())
      bar = form.verticalScrollBar()
      self.assertGreater(bar.maximum(), 0)   # the form is taller than the view
      fields = [f for f in form.widget().findChildren(QtWidgets.QWidget) if isinstance(f, FIELDS) and f.isVisible()]
      self.assertGreater(self.check_fields("Object editor form", form, len(fields)), 0)
      self.assertFalse(self.problems, "\n".join(self.problems))   # every problem, one per line
      doc = ob.map_doc()
      self.assertFalse(doc.dirty)   # the wheel edited nothing
      # A field the user clicked into still steps with the wheel.
      spin = ob.speed
      form.ensureWidgetVisible(spin, 0, 0)
      self.settle()
      spin.setFocus()
      before, start = spin.value(), bar.value()
      wheel(spin, spin.rect().center(), 1 if spin.value() < spin.maximum() else -1)
      self.settle()
      self.assertNotEqual(spin.value(), before)
      self.assertEqual(bar.value(), start)
      # The route box of a movement that is not custom: read-only, greyed, and it still scrolls.
      route = ob.route
      self.assertFalse(route.editable())
      route.text.setPlainText("\n".join(f"wait {n}" for n in range(FIELDS_PER_AREA * FIELDS_PER_AREA)))
      self.settle()
      text_bar = route.text.verticalScrollBar()
      self.assertTrue(route.text.isEnabled() and text_bar.isEnabled() and text_bar.maximum() > 0)
      self.assertFalse(is_enabled(route.text))
      self.assertTrue(route.text.isReadOnly())
      w.hide()
      w.deleteLater()
      self.settle()

   def test_locked_views(self) -> None:
      """!lock_view() and set_enabled(): a locked text view and table still scroll by bar and wheel; they take no
      focus and no edits; unlocking gives back what they had.
      @return None
      """
      from capsule_studio.ui.widgets import install_wheel_guard, is_enabled, lock_view, set_enabled
      install_wheel_guard()
      page = QtWidgets.QWidget()
      lay = QtWidgets.QVBoxLayout(page)
      text = QtWidgets.QPlainTextEdit("\n".join(str(n) for n in range(NOTCH)))
      table = QtWidgets.QTableWidget(NOTCH, 2)
      for v in (text, table):
         lay.addWidget(v)
      page.resize(*SMALL_WINDOW)
      page.show()
      self.settle()
      policy = text.focusPolicy()
      for v in (text, table):
         set_enabled(v, False)
      self.settle()
      for v in (text, table):
         bar = v.verticalScrollBar()
         self.assertTrue(v.isEnabled() and bar.isEnabled() and not is_enabled(v))
         self.assertFalse(v.viewport().isEnabled())
         self.assertEqual(v.focusPolicy(), QtCore.Qt.FocusPolicy.NoFocus)
         bar.setValue(1)
         self.assertEqual(bar.value(), 1)
         wheel(v.viewport(), QtCore.QPoint(*CORNER))
         self.settle()
         self.assertGreater(bar.value(), 1)
      self.assertTrue(text.isReadOnly())
      lock_view(text, False)
      set_enabled(table, True)
      self.assertFalse(text.isReadOnly())
      self.assertEqual(text.focusPolicy(), policy)
      self.assertTrue(is_enabled(text) and is_enabled(table) and table.viewport().isEnabled())
      page.hide()
      page.deleteLater()
      self.settle()


if __name__ == "__main__":
   unittest.main()
