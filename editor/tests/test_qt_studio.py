#!/usr/bin/env python3
"""!Smoke test of the tool split and the Studio's Qt layer: the map editor
shows only its Map and Tileset tabs (keeping the extensions' map tools), each
world tool runs in a window of its own, and the Studio hosts every editor on
one game. Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core import engine, project  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtStudioTests(unittest.TestCase):
   """!Builds the map editor, the standalone world tools and the Studio on a copy of the map sandbox game."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies the map sandbox game and the Starter's game (with the Starter both use, in the engine's layout).
      @return None
      """
      ## Temporary apps folder (the Starter is in ../samples/starter).
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_qt_studio_")),
                                   ["sandbox_map", "starter_battle"], ("data", "reference"))
      ## The game's project manifest.
      self.manifest = self.root / "sandbox_map" / "reference" / "project.json"
      ## Its world.json.
      self.world = self.root / "sandbox_map" / "data" / "world.json"
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root.parent, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(3):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def test_map_editor_keeps_map_and_tileset(self) -> None:
      """!The map editor has no extension tabs, but the extensions' map tools are in its toolbar.
      @return None
      """
      from capsule_studio.ui.world_shell import WorldWindow
      w = WorldWindow(path=str(self.world))
      w.show()
      self.settle()
      self.assertEqual([w.tabs.tabText(i) for i in range(w.tabs.count())],
                       ["Map", "Tileset", "Levels", "Movement modes", "Field", "Behaviors", "Doors and draw order",
                        "Interactions", "Override sets"])   # F2, I2 / I3; S3: D-30 doors, draw order and override
      # sets; S6b: C13b cell interaction rules
      buttons = {b.text() for b in w.panels[0].findChildren(QtWidgets.QToolButton)}
      self.assertTrue({"Encounters", "Events", "Objects"} <= buttons, buttons)
      w.close()

   def test_standalone_world_tools(self) -> None:
      """!Each world tool's window shows only its own panel, on its own map list.
      @return None
      """
      from capsule_studio.ui.world_shell import WorldWindow
      for host, panel in (("event-editor", "events"), ("object-editor", "objects"),
                          ("location-editor", "locations"), ("encounter-editor", "encounters")):
         w = WorldWindow([], str(self.world), host, host)
         w.show()
         self.settle()
         self.assertEqual([p.panel_id for p in w.panels], [panel], host)
         self.assertFalse(w.tabs.tabBar().isVisible())
         self.assertIsNone(w.selected_map())   # no map tab to follow: the panel picks its own map
         self.assertFalse(w.shows_map())
         self.assertTrue(w.panels[0].follow.isHidden(), host)   # so it offers none
         w.close()
      from capsule_studio.ui import event_app, location_app, object_app
      for mod in (event_app, object_app, location_app):
         self.assertTrue(callable(mod.main))

   def test_studio_opens_the_game(self) -> None:
      """!Every file the project names opens on its page; menus and shortcuts follow the page in front.
      @return None
      """
      from capsule_studio.ui.studio_shell import PAGES, StudioWindow
      from capsule_studio.ui.world_shell import WORLD_PANELS
      w = StudioWindow(str(self.manifest))
      self.settle()
      self.assertTrue(w.isVisible())
      # F1: the map sandbox names the Starter's battle data (its lead and Ward charm)
      self.assertEqual(set(w.windows), {"world", "assets", "scripts", "battle", "project"})
      self.assertEqual(w.current_page_id(), "world")
      self.assertIn("sandbox_map - World", w.windowTitle())
      world = w.windows["world"]
      self.assertEqual([world.tabs.tabText(i) for i in range(world.tabs.count())],
                       ["Map", "Tileset", "Levels", "Movement modes", "Field", "Behaviors", "Doors and draw order",
                        "Interactions", "Encounters", "Events", "Locations", "Objects", "Override sets"])   # S3, S6b
      self.assertTrue(world.shows_map())
      for p in world.panels[len(WORLD_PANELS):]:
         self.assertFalse(p.follow.isHidden(), p.panel_id)   # each world tool can follow the Map tab
      files = project.game_files(project.open_project(self.manifest))
      self.assertEqual(world.project.world.path, files["maps"])
      self.assertEqual(w.windows["assets"].document.path, files["assets"])
      self.assertEqual(w.windows["scripts"].project.path, files["scripts"])
      self.assertEqual(w.windows["project"].document.path, self.manifest.resolve())
      self.assertEqual(w.nav.item(0).toolTip(), str(Path("data") / "world.json"))
      # Only the page in front shows: its menus join the Studio menu; only it has shortcuts.
      visible = [i for i in range(w.stack.count()) if w.stack.widget(i).isVisible()]
      self.assertEqual(visible, [0])

      def menus() -> list[str]:
         return [a.text().replace("&", "") for a in w.menuBar().actions()]

      def keyed(pid: str) -> list[QtGui.QAction]:
         return [a for a in w.windows[pid].findChildren(QtGui.QAction) if a.shortcuts()]
      self.assertEqual(menus()[:3], ["Studio", "File", "Edit"])
      self.assertTrue(keyed("world"))
      self.assertEqual([keyed(pid) for pid in ("assets", "scripts", "project")], [[], [], []])
      w.show_page("scripts")
      self.settle()
      self.assertIn("Script", menus())
      self.assertEqual(keyed("world"), [])
      self.assertTrue(keyed("scripts"))
      self.assertIn("Scripts", w.windowTitle())
      # The pages' own Quit is hidden: the Studio quits.
      for win in w.windows.values():
         for a in win.findChildren(QtGui.QAction):
            if a.text().replace("&", "") == "Quit":
               self.assertFalse(a.isVisible())
      # The page list marks unsaved changes.
      pw = w.windows["project"]
      w.show_page("project")
      self.settle()
      self.assertTrue(pw.run_edit("Set", lambda: pw.document.data.setdefault("build", {}).update(
         {"vram_streaming_slots": 32})))
      self.settle()
      self.assertEqual(w.nav.item(PAGES.index(next(p for p in PAGES if p.page_id == "project"))).text(),
                       "Project *")
      # A page that was not opened is built when it is shown.
      w.show_page("battle")
      self.settle()
      self.assertIn("battle", w.windows)
      self.assertEqual(w.current_page_id(), "battle")
      # Closing asks about the unsaved project settings: Cancel keeps the Studio open, Discard closes it.
      b = QtWidgets.QMessageBox.StandardButton
      answers = [b.Cancel, b.Discard]
      shown = []
      original = QtWidgets.QMessageBox.question

      def answer(*_a: object, **_k: object) -> QtWidgets.QMessageBox.StandardButton:
         shown.append(w.current_page_id())   # the page asking is in front while it asks
         return answers.pop(0)
      QtWidgets.QMessageBox.question = staticmethod(answer)
      try:
         self.assertFalse(w.close())
         self.assertEqual(shown, ["project"])
         self.assertEqual(w.current_page_id(), "project")
         self.assertTrue(w.close())
      finally:
         QtWidgets.QMessageBox.question = original
      self.assertEqual(answers, [])

   def test_studio_start_and_pages(self) -> None:
      """!Without a project the start window shows; --page picks the first page.
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow, page_by_id
      w = StudioWindow(None, "scripts")
      w.launch()
      self.settle()
      self.assertTrue(w.start.isVisible())
      self.assertFalse(w.isVisible())
      self.assertEqual(w.current_page_id(), "scripts")
      self.assertEqual(list(w.windows), ["scripts"])
      with self.assertRaises(KeyError):
         page_by_id("nope")
      self.assertTrue(w.open_game(str(self.manifest)))
      self.settle()
      self.assertFalse(w.start.isVisible())
      self.assertTrue(w.isVisible())
      self.assertEqual(w.current_page_id(), "world")
      w.close()


   def copy_game(self, app: str, name: str, broken_world: bool = False) -> Path:
      """!Copies one of the engine's apps as another game.
      @param app           engine app folder name
      @param name          folder of the copy
      @param broken_world  write a world.json the map editor cannot open
      @return its reference/project.json
      """
      apps = engine.root() / "apps"
      shutil.copytree(apps / app / "data", self.root / name / "data")
      shutil.copytree(apps / app / "reference", self.root / name / "reference")
      if broken_world:
         (self.root / name / "data" / "world.json").write_text('{"schema": "capsule.world/1", "maps": 3}',
                                                               encoding="utf-8")
      return self.root / name / "reference" / "project.json"

   def test_studio_second_game_and_failed_opens(self) -> None:
      """!Opening another game resets the pages it does not name and those whose file did not open.
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      warnings = []
      original = QtWidgets.QMessageBox.warning
      QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: warnings.append(a[2] if len(a) > 2 else a))
      try:
         w = StudioWindow(str(self.manifest))
         self.settle()
         self.assertEqual(set(w.windows), {"world", "assets", "scripts", "battle", "project"})
         battle = self.root / "starter_battle" / "reference" / "project.json"   # names assets and battle only
         self.assertTrue(w.open_game(str(battle)))
         self.settle()
         self.assertEqual(set(w.windows), {"assets", "battle", "project"})   # world and scripts reset
         self.assertIn("starter_battle", w.windowTitle())
         self.assertEqual(w.windows["battle"].project.battle.path,
                          (self.root.parent / "samples" / "starter" / "battle.json").resolve())
         self.assertEqual(w.nav.item(0).toolTip(), "nothing open")
         w.show_page("world")   # built again, empty
         self.settle()
         self.assertIsNone(w.windows["world"].project)
         # A world that does not open: its page is reset and the message says so.
         warnings.clear()
         broken = self.copy_game("sandbox_map", "broken", broken_world=True)
         self.assertTrue(w.open_game(str(broken)))
         self.settle()
         self.assertNotIn("world", w.windows)
         self.assertTrue(any("World:" in str(m) and "did not open" in str(m) for m in warnings), warnings)
         # One the tool itself refuses (with its own message): the same.
         warnings.clear()
         unreadable = self.copy_game("sandbox_map", "unreadable")
         (self.root / "unreadable" / "data" / "world.json").write_text("{", encoding="utf-8")
         self.assertTrue(w.open_game(str(unreadable)))
         self.settle()
         self.assertNotIn("world", w.windows)
         self.assertEqual(w.windows["scripts"].project.path,
                          (self.root / "unreadable" / "data" / "scripts" / "scripts.json").resolve())
         self.assertTrue(any("World:" in str(m) and "did not open" in str(m) for m in warnings), warnings)
      finally:
         QtWidgets.QMessageBox.warning = original
      w.close()

   def test_studio_menus_and_project_open(self) -> None:
      """!One Help menu (the Studio's, last); the Project page's Open project... opens a whole game.
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      w = StudioWindow(str(self.manifest))
      self.settle()
      for pid in ("world", "scripts", "project"):
         w.show_page(pid)
         self.settle()
         names = [a.text().replace("&", "") for a in w.menuBar().actions()]
         self.assertEqual(names.count("Help"), 1, names)
         self.assertEqual(names[-1], "Help")
         self.assertEqual(names[0], "Studio")
      asked = []
      w.open_game = lambda path=None: asked.append(path)
      opener = next(a for a in w.windows["project"].findChildren(QtGui.QAction)
                    if a.text().replace("&", "") == "Open project...")
      opener.trigger()
      self.assertEqual(asked, [None])
      w.close()

   def test_recorder_refuses_a_second_profiler(self) -> None:
      """!Record performance does not start while Python's profiler is in use (it stays unchecked).
      @return None
      """
      import cProfile
      from capsule_studio.ui import profiler
      busy = cProfile.Profile()
      try:
         busy.enable()
         second = cProfile.Profile()
         try:
            second.enable()
         except ValueError:
            pass
         else:
            second.disable()
            self.skipTest("this Python allows two profilers at once")
         rec = profiler.Recorder(None, "studio", None)
         self.assertFalse(rec.start())
         self.assertFalse(rec.recording())
      finally:
         busy.disable()

if __name__ == "__main__":
   unittest.main()
