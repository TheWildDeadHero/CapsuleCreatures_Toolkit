#!/usr/bin/env python3
"""!A game without a world (D-40 RW): a game whose project manifest names no "maps" (made before D-40 RN, when
New game gave no world; here core.templates.new_game(..., world=False) from the Starter template), so its Studio
World page has no world document. New games get a world now (test_new_game_world.py).

  - The World page shows an empty state ("This game has no world yet") with Create a new world and Add an
    existing world..., not the map editor's panels; the standalone map editor shows its own (New world... /
    Open world...).
  - Create a new world (core.game_world.create()) makes an empty data/world.json, names it in the manifest and
    opens it on the World page; New tileset... then asks for the new tileset's name.
  - Add an existing world... adds one through Add world to game... (core.game_world.run()).
  - Every button of the world panels either works (asks something, edits something, toggles) or says in the
    status bar why it did nothing: with no world at all, and with the new empty world (nothing chosen).

Uses Qt's offscreen platform; the Qt tests are skipped when PySide6 is missing. Modal dialogs are replaced by
recorders that answer "cancel", so nothing waits for a click.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core import game_world, manifest_io, project, templates, tilesets  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402

## The template the game without a world is made from (the developer's case).
TEMPLATE = "starter"
## Name the patched name dialog answers New tileset... with.
TILESET_NAME = "plain"
## Times the event loop runs to settle (scheduled refreshes post more events).
SETTLE_ROUNDS = 4
## Buttons the "works or says why" check may leave silent: (panel id, button text) -> why that is right.
SILENT_ALLOWED: dict[tuple[str, str], str] = {}
## The fixture world's maps (Add an existing world...).
SOURCE_MAPS = ["square_field", "square_room"]
## Size of the fixture tileset's sheet, pixels (one 8x8 tile).
SHEET_SIZE = [8, 8]
## Corners of a metatile (2x2 tiles; None: the sheet's empty tile).
METATILE_TILES = 4
## The fixture game's name (its new world's id).
GAME_NAME = "squares_game"


def make_world(path: Path, name: str = "squares") -> Path:
   """!A small world of simple shapes: one tileset with a plain square sheet and one metatile, and SOURCE_MAPS
   filled with it (saved).
   @param path  its world.json
   @param name  world id
   @return path
   """
   world = Project.create(path, name)
   ts = world.add_tileset("plain")
   with ts.edit("Sheet"):
      ts.data["sheets"].append({"name": "s", "palette": ["#ffffff"], "size": SHEET_SIZE, "shapes": []})
      tilesets.add_metatile(ts, "square", [None] * METATILE_TILES)
   for m in SOURCE_MAPS:
      world.add_map(m, fill="plain/square")
   world.save_all()
   return path


def make_game(folder: Path) -> Path:
   """!A game folder with a project manifest naming battle data and no world.
   @param folder  the game folder
   @return its reference/project.json
   """
   manifest_io.save(folder / "data" / "battle.json", {"schema": "capsule.battle/1"})
   manifest = folder / "reference" / "project.json"
   manifest_io.save(manifest, {"schema": project.SCHEMA, "name": GAME_NAME, "battle": "data/battle.json"})
   return manifest


class CoreCreateTests(unittest.TestCase):
   """!core.game_world.create() without any user interface."""

   def setUp(self) -> None:
      """!A game folder with battle data and no world.
      @return None
      """
      ## The temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_no_world_"))
      ## The game folder.
      self.game = self.root / "game"
      ## Its project manifest.
      self.manifest = make_game(self.game)

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_create_names_an_empty_world(self) -> None:
      """!An empty world in data/world.json, pointed at the game's battle data, named in the manifest (the "maps"
      key before the other data file keys).
      @return None
      """
      lines = game_world.create(project.open_project(self.manifest))
      data = manifest_io.load(self.manifest)
      self.assertEqual(data["maps"], game_world.NEW_WORLD_FILE)
      self.assertLess(list(data).index("maps"), list(data).index("battle"))
      self.assertEqual(lines[-1], f"maps: {game_world.NEW_WORLD_FILE}")
      world = Project.open(self.game / game_world.NEW_WORLD_FILE)
      self.assertEqual(world.map_names(), [])
      self.assertEqual(world.tileset_names(), [])
      self.assertEqual(world.world.data["id"], GAME_NAME)
      self.assertTrue(any("battle data" in line for line in lines))

   def test_taken_name_and_existing_world(self) -> None:
      """!A data/world.json that is something else is left alone (data/world_2.json); a game whose world exists
      is refused.
      @return None
      """
      (self.game / "data" / "world.json").write_text("not a world\n")
      game_world.create(project.open_project(self.manifest))
      self.assertEqual(manifest_io.load(self.manifest)["maps"], "data/world_2.json")
      self.assertEqual((self.game / "data" / "world.json").read_text(), "not a world\n")
      with self.assertRaises(DocumentError):
         game_world.create(project.open_project(self.manifest))

   def test_named_but_missing_world_is_made_there(self) -> None:
      """!A manifest naming a world file that is missing gets the new world in that file.
      @return None
      """
      data = manifest_io.load(self.manifest)
      data["maps"] = "world/main.json"
      manifest_io.save(self.manifest, data)
      game_world.create(project.open_project(self.manifest))
      self.assertTrue(Project.open(self.game / "world" / "main.json").map_names() == [])
      self.assertEqual(manifest_io.load(self.manifest)["maps"], "world/main.json")


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class StudioNoWorldTests(unittest.TestCase):
   """!The Studio on a Starter game without a world, and the standalone map editor, with no world."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication; settings in a temporary folder.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
      ## Temporary root.
      cls.root = Path(tempfile.mkdtemp(prefix="capsule_no_world_qt_"))
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(cls.root / "settings"))

   @classmethod
   def tearDownClass(cls) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(cls.root, ignore_errors=True)

   def setUp(self) -> None:
      """!A Starter game made without a world (as New game made them before D-40 RN), opened in the Studio.
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      ## A folder of its own for this test's game.
      self.folder = Path(tempfile.mkdtemp(prefix="game_", dir=self.root))
      ## The game's project manifest.
      self.manifest = templates.new_game(self.folder / "quest", templates.find(TEMPLATE), world=False)
      ## The Studio.
      self.studio = StudioWindow(None)
      self.assertTrue(self.studio.open_game(self.manifest))
      self.settle()
      ## Dialogs the patched dialog functions were asked for.
      self.asked = []

   def tearDown(self) -> None:
      """!Closes the Studio without asking.
      @return None
      """
      for w in self.studio.windows.values():
         w._confirm_discard = lambda: True
      self.studio.close()
      self.studio.deleteLater()
      self.settle()

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(SETTLE_ROUNDS):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def world_page(self) -> QtWidgets.QMainWindow:
      """!Shows the World page.
      @return its WorldWindow
      """
      self.studio.show_page("world")
      self.settle()
      return self.studio.windows["world"]

   # -- modal dialogs answer "cancel" -------------------------------------------------------------------------

   def recorder(self, name: str, answer: object) -> Callable[..., object]:
      """!A stand-in for a modal dialog: records that it was asked, gives the cancel answer.
      @param name    what was asked, for self.asked
      @param answer  what it returns
      @return callable
      """
      def asked(*_args: object, **_kwargs: object) -> object:
         """!Records the call.
         @return the cancel answer
         """
         self.asked.append(name)
         return answer
      return asked

   @contextmanager
   def no_modal_dialogs(self) -> Iterator[None]:
      """!Replaces every modal dialog a panel can open with a recorder that cancels it.
      @return context manager
      """
      w = QtWidgets
      b = w.QMessageBox.StandardButton
      patches = [
         mock.patch.object(w.QInputDialog, "getText", self.recorder("getText", ("", False))),
         mock.patch.object(w.QInputDialog, "getItem", self.recorder("getItem", ("", False))),
         mock.patch.object(w.QInputDialog, "getInt", self.recorder("getInt", (0, False))),
         mock.patch.object(w.QInputDialog, "getMultiLineText", self.recorder("getMultiLineText", ("", False))),
         mock.patch.object(w.QFileDialog, "getOpenFileName", self.recorder("getOpenFileName", ("", ""))),
         mock.patch.object(w.QFileDialog, "getOpenFileNames", self.recorder("getOpenFileNames", ([], ""))),
         mock.patch.object(w.QFileDialog, "getSaveFileName", self.recorder("getSaveFileName", ("", ""))),
         mock.patch.object(w.QFileDialog, "getExistingDirectory", self.recorder("getExistingDirectory", "")),
         mock.patch.object(w.QColorDialog, "getColor", self.recorder("getColor", QtGui.QColor())),
         mock.patch.object(w.QMessageBox, "question", self.recorder("question", b.Cancel)),
         mock.patch.object(w.QMessageBox, "warning", self.recorder("warning", b.Ok)),
         mock.patch.object(w.QMessageBox, "information", self.recorder("information", b.Ok)),
         mock.patch.object(w.QMessageBox, "exec", self.recorder("QMessageBox.exec", int(b.Cancel.value))),
         mock.patch.object(w.QDialog, "exec", self.recorder("QDialog.exec", 0)),
         mock.patch.object(w.QMenu, "exec", self.recorder("QMenu.exec", None)),
      ]
      for p in patches:
         p.start()
      try:
         yield
      finally:
         for p in reversed(patches):
            p.stop()

   # -- the tests ---------------------------------------------------------------------------------------------

   def test_game_without_world_shows_the_empty_state(self) -> None:
      """!The game names no world; its World page shows the empty state with its two buttons and none of the map
      editor's panels.
      @return None
      """
      self.assertNotIn(game_world.MAPS_KEY, manifest_io.load(self.manifest))
      w = self.world_page()
      self.assertIsNone(w.project)
      self.assertIs(w.body.currentWidget(), w.empty)
      self.assertTrue(w.empty.isVisible())
      self.assertFalse(w.tabs.isVisible())
      self.assertEqual(w.empty.heading.text(), "This game has no world yet")
      self.assertEqual(list(w.empty.buttons), ["Create a new world", "Add an existing world..."])
      self.assertTrue(all(b.isEnabled() and b.isVisible() for b in w.empty.buttons.values()))

   def test_create_a_new_world_then_new_tileset(self) -> None:
      """!Create a new world: the game names data/world.json, the World page has that document; New tileset...
      then asks for the tileset's name and adds it.
      @return None
      """
      from capsule_studio.ui.editors.tileset import TilesetPanel
      w = self.world_page()
      w.empty.buttons["Create a new world"].click()
      self.settle()
      self.assertEqual(manifest_io.load(self.manifest)[game_world.MAPS_KEY], game_world.NEW_WORLD_FILE)
      w = self.studio.windows["world"]
      self.assertIsNotNone(w.project)
      self.assertEqual(w.project.world.path, (self.folder / "quest" / game_world.NEW_WORLD_FILE).resolve())
      self.assertIs(w.body.currentWidget(), w.tabs)
      self.assertIn("Create a new world", w.statusBar().currentMessage())
      panel = next(p for p in w.panels if isinstance(p, TilesetPanel))
      w.tabs.setCurrentWidget(panel)
      self.settle()
      new = next(b for b in panel.findChildren(QtWidgets.QPushButton) if b.text() == "New tileset...")
      self.assertTrue(new.isEnabled() and new.isVisible())
      ask = mock.Mock(return_value=(TILESET_NAME, True))
      with mock.patch.object(QtWidgets.QInputDialog, "getText", ask):
         new.click()
         self.settle()
      ask.assert_called_once()
      self.assertIn(TILESET_NAME, w.project.tileset_names())

   def test_add_an_existing_world(self) -> None:
      """!Add an existing world...: Add world to game... imports a world from outside the game into
      data/world.json and opens it.
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      outside = make_world(self.folder / "elsewhere" / "world.json")
      w = self.world_page()
      with mock.patch.object(StudioWindow, "_ask_world_source", lambda _self: outside), \
            mock.patch.object(StudioWindow, "_choose_import", lambda _self, _doc, _add: (list(SOURCE_MAPS), [])):
         w.empty.buttons["Add an existing world..."].click()
         self.settle()
      self.assertEqual(manifest_io.load(self.manifest)[game_world.MAPS_KEY], game_world.NEW_WORLD_FILE)
      w = self.studio.windows["world"]
      self.assertEqual(w.project.map_names(), SOURCE_MAPS)
      self.assertIs(w.body.currentWidget(), w.tabs)

   def revisions(self, w: QtWidgets.QMainWindow) -> list[int]:
      """!Edit counters of the world and the documents it opened (an edit moves one).
      @param w  WorldWindow
      @return list of Document.revision, or [] without a world
      """
      return [d.revision for d in w.project.documents()] if w.project is not None else []

   def click_every_button(self, w: QtWidgets.QMainWindow, label: str) -> tuple[list[str], int]:
      """!Clicks every visible, enabled button of every panel of a world window, with dialogs cancelled.
      @param w      WorldWindow (its panels shown, even without a world)
      @param label  for the messages
      @return (buttons that did nothing and said nothing, buttons clicked)
      """
      silent, clicked = [], 0
      w.body.setCurrentWidget(w.tabs)   # what the developer saw: the panels, with no world behind them
      for panel in list(w.panels):
         w.tabs.setCurrentWidget(panel)
         self.settle()
         buttons = [b for b in panel.findChildren(QtWidgets.QAbstractButton)
                    if isinstance(b, (QtWidgets.QPushButton, QtWidgets.QToolButton)) and b.isVisible()
                    and b.isEnabled() and b.text()]
         for b in buttons:
            try:
               if not (b.isVisible() and b.isEnabled()):
                  continue
               text, checked = b.text(), b.isChecked()
            except RuntimeError:   # a refresh rebuilt it
               continue
            bars = (w.statusBar(), self.studio.statusBar())   # report_failure() writes to the Studio's, headless
            for bar in bars:
               bar.clearMessage()
            self.asked.clear()
            revisions = self.revisions(w)
            with self.no_modal_dialogs():
               b.click()
               self.settle()
            clicked += 1
            try:
               toggled = b.isCheckable() or b.isChecked() != checked   # a tool or a switch: choosing it works
            except RuntimeError:
               toggled = True   # it rebuilt its panel: something happened
            said = any(bar.currentMessage() for bar in bars)
            changed = self.revisions(w) != revisions
            key = (panel.panel_id, text)
            if not (said or self.asked or toggled or changed) and key not in SILENT_ALLOWED:
               silent.append(f"{label} {panel.panel_id}: {text!r}")
      return silent, clicked

   def test_every_button_works_or_says_why(self) -> None:
      """!Every button of every world panel, with no world (the panels shown behind the empty state, as before
      the fix) and with the new empty world (nothing chosen): a dialog, an edit, a toggle or a status message.
      @return None
      """
      w = self.world_page()
      silent, clicked = self.click_every_button(w, "no world:")
      self.assertGreater(clicked, 0)
      self.studio.create_world()
      self.settle()
      w = self.studio.windows["world"]
      more, clicked = self.click_every_button(w, "empty world:")
      self.assertGreater(clicked, 0)
      self.assertFalse(silent + more, "\n".join(silent + more))

   def test_standalone_map_editor_without_a_world(self) -> None:
      """!The map editor's Continue without a world: its empty state offers New world... and Open world...; a
      panel action says why it does nothing.
      @return None
      """
      from capsule_studio.ui.editors.tileset import TilesetPanel
      from capsule_studio.ui.world_shell import NO_WORLD_REASON, WorldWindow
      w = WorldWindow(None, None)
      try:
         w.show_editor()
         self.settle()
         self.assertIs(w.body.currentWidget(), w.empty)
         self.assertEqual(list(w.empty.buttons), ["New world...", "Open world..."])
         panel = next(p for p in w.panels if isinstance(p, TilesetPanel))
         w.statusBar().clearMessage()
         panel.new_tileset()
         self.assertEqual(w.statusBar().currentMessage(), f"New tileset: {NO_WORLD_REASON}")
         with self.no_modal_dialogs():
            w.empty.buttons["Open world..."].click()
         self.assertEqual(self.asked, ["getOpenFileName"])
      finally:
         w.hide()
         w.deleteLater()
         self.settle()

   def test_studio_without_a_game(self) -> None:
      """!The Studio with no game open: its World page offers Open project... and New game....
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      s = StudioWindow(None)
      try:
         s.show_editor()
         s.show_page("world")
         self.settle()
         w = s.windows["world"]
         self.assertIs(w.body.currentWidget(), w.empty)
         self.assertEqual(w.empty.heading.text(), "No game is open")
         self.assertEqual(list(w.empty.buttons), ["Open project...", "New game..."])
      finally:
         s.hide()
         s.deleteLater()
         self.settle()


if __name__ == "__main__":
   unittest.main()
