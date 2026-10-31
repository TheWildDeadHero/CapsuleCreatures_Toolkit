#!/usr/bin/env python3
"""!Tests for capsule_studio.core.game_world (adding a world to a game), `capsule-studio project add-world` and the
Studio's Add world to game... (offscreen; the Qt part is skipped when PySide6 is missing).

The fixtures are made here from simple shapes: a game folder with its reference/project.json, and a small world
outside it (one tileset of plain squares, two maps filled with them).
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import game_world, manifest_io, project, tilesets  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402

## The fixture world's maps, in the order they are added.
SOURCE_MAPS = ["square_field", "square_room"]
## Size of the fixture tileset's sheet, pixels (one 8x8 tile).
SHEET_SIZE = [8, 8]
## Corners of a metatile (2x2 tiles; None: the sheet's empty tile).
METATILE_TILES = 4


def run_cli(*argv: str) -> tuple[int, str]:
   """!Runs the CLI.
   @param argv  arguments
   @return (status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      status = cli(list(argv))
   return status, out.getvalue() + err.getvalue()


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


def make_game(folder: Path, battle: bool = True) -> Path:
   """!A game folder with a project manifest (and a battle data file when @p battle).
   @param folder  the game folder
   @param battle  whether the game names battle data
   @return its reference/project.json
   """
   data = {"schema": project.SCHEMA, "name": "squares_game"}
   if battle:
      data["battle"] = "data/battle.json"
      manifest_io.save(folder / "data" / "battle.json", {"schema": "capsule.battle/1"})
   manifest = folder / "reference" / "project.json"
   manifest_io.save(manifest, data)
   return manifest


class GameWorldTestCase(unittest.TestCase):
   """!Base: a game and a world outside it, in a temporary folder."""

   def setUp(self) -> None:
      """!Makes the fixtures.
      @return None
      """
      ## The temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_game_world_"))
      ## The game folder.
      self.game = self.root / "game"
      ## Its project manifest.
      self.manifest = make_game(self.game)
      ## A world outside the game.
      self.outside = make_world(self.root / "elsewhere" / "world.json")

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def manifest_data(self) -> dict:
      """!The project manifest as saved.
      @return dict
      """
      return manifest_io.load(self.manifest)


class PlanTests(GameWorldTestCase):
   """!What adding a world would do."""

   def test_outside_world_is_imported_into_a_new_world(self) -> None:
      """!A world outside the game is imported into a new data/world.json.
      @return None
      """
      add = game_world.plan(project.open_project(self.manifest), self.outside)
      self.assertEqual(add.action, game_world.IMPORT)
      self.assertEqual(add.rel, game_world.NEW_WORLD_FILE)
      self.assertTrue(add.creates)
      self.assertIsNone(add.replaces)

   def test_world_inside_the_game_is_named_as_it_is(self) -> None:
      """!A world in the game folder is linked; once named, nothing is left to do.
      @return None
      """
      inside = make_world(self.game / "levels" / "world.json")
      doc = project.open_project(self.manifest)
      add = game_world.plan(doc, inside)
      self.assertEqual((add.action, add.rel, add.creates), (game_world.LINK, "levels/world.json", False))
      game_world.run(doc, inside)
      self.assertEqual(game_world.plan(project.open_project(self.manifest), inside).action, game_world.LINKED)

   def test_taken_world_file_gets_another_name(self) -> None:
      """!When data/world.json holds something else, the new world is data/world_2.json.
      @return None
      """
      manifest_io.save(self.game / "data" / "world.json", {"schema": "capsule.assets/1", "assets": []})
      add = game_world.plan(project.open_project(self.manifest), self.outside)
      self.assertEqual(add.rel, "data/world_2.json")

   def test_not_a_world_is_refused(self) -> None:
      """!A file that is not a world manifest is refused.
      @return None
      """
      with self.assertRaises(DocumentError):
         game_world.plan(project.open_project(self.manifest), self.game / "data" / "battle.json")


class RunTests(GameWorldTestCase):
   """!Adding a world: import, battle data, the project manifest."""

   def test_import_then_link(self) -> None:
      """!Every map comes along, the world follows the game's battle data, the manifest names the world before its
      other data files, and the world compiles.
      @return None
      """
      lines = game_world.run(project.open_project(self.manifest), self.outside)
      self.assertEqual(lines[-1], f"maps: {game_world.NEW_WORLD_FILE}")
      data = self.manifest_data()
      self.assertEqual(list(data), ["schema", "name", "maps", "battle"])
      world = Project.open(self.game / game_world.NEW_WORLD_FILE)
      self.assertEqual(world.map_names(), SOURCE_MAPS)
      self.assertEqual(world.world.data["battle"], "battle.json")
      self.assertEqual(world.world.data["id"], "squares_game")
      self.assertTrue((self.game / "data" / "maps" / "square_room.json").is_file())
      for m in SOURCE_MAPS:   # (validate() would also read the fixture's battle data, which holds no structure)
         self.assertIsNone(world.compiled_map(m)[1])
      self.assertEqual(project.game_files(project.open_project(self.manifest))["maps"],
                       (self.game / game_world.NEW_WORLD_FILE).resolve())

   def test_chosen_maps_only(self) -> None:
      """!With a map list only those maps are imported.
      @return None
      """
      game_world.run(project.open_project(self.manifest), self.outside, [SOURCE_MAPS[1]])
      self.assertEqual(Project.open(self.game / game_world.NEW_WORLD_FILE).map_names(), [SOURCE_MAPS[1]])

   def test_second_import_goes_into_the_game_world(self) -> None:
      """!Once the game names a world, another import adds to it (a clashing map gets a new name).
      @return None
      """
      game_world.run(project.open_project(self.manifest), self.outside, [SOURCE_MAPS[0]])
      add = game_world.plan(project.open_project(self.manifest), self.outside)
      self.assertEqual((add.action, add.creates, add.replaces), (game_world.IMPORT, False, None))
      game_world.run(project.open_project(self.manifest), self.outside, [SOURCE_MAPS[0]])
      names = Project.open(self.game / game_world.NEW_WORLD_FILE).map_names()
      self.assertEqual(names, [SOURCE_MAPS[0], f"{SOURCE_MAPS[0]}_2"])

   def test_another_world_inside_replaces_the_link(self) -> None:
      """!Linking another world of the game replaces "maps" in place and says what it replaced.
      @return None
      """
      first = make_world(self.game / "a" / "world.json", "a")
      second = make_world(self.game / "b" / "world.json", "b")
      game_world.run(project.open_project(self.manifest), first)
      lines = game_world.run(project.open_project(self.manifest), second)
      self.assertEqual(lines[-1], "maps: b/world.json (was a/world.json)")
      self.assertEqual(list(self.manifest_data()), ["schema", "name", "maps", "battle"])

   def test_world_with_game_battle_data_is_kept(self) -> None:
      """!A world inside the game that names battle data in the game keeps it; a game without battle data leaves
      the world alone.
      @return None
      """
      inside = make_world(self.game / "levels" / "world.json")
      world = Project.open(inside)
      with world.world.edit("Battle data"):
         world.world.data["battle"] = "../data/battle.json"
      world.save_all()
      game_world.run(project.open_project(self.manifest), inside)
      self.assertEqual(Project.open(inside).world.data["battle"], "../data/battle.json")
      bare = make_game(self.root / "bare", battle=False)
      game_world.run(project.open_project(bare), self.outside)
      self.assertNotIn("battle", Project.open(self.root / "bare" / game_world.NEW_WORLD_FILE).world.data)

   def test_refused_import_writes_nothing(self) -> None:
      """!An import that cannot be done leaves the manifest as it was and makes no world.
      @return None
      """
      before = self.manifest.read_bytes()
      with self.assertRaises(DocumentError):
         game_world.run(project.open_project(self.manifest), self.outside, ["nowhere"])
      self.assertEqual(self.manifest.read_bytes(), before)
      self.assertFalse((self.game / game_world.NEW_WORLD_FILE).exists())


class CommandTests(GameWorldTestCase):
   """!`capsule-studio project add-world`."""

   def test_import_needs_its_flag(self) -> None:
      """!A world outside the game needs --import; --dry-run changes nothing; with --import it is added.
      @return None
      """
      before = self.manifest.read_bytes()
      status, out = run_cli("project", "add-world", str(self.manifest), str(self.outside))
      self.assertNotEqual(status, 0)
      self.assertIn("--import", out)
      status, out = run_cli("project", "add-world", str(self.manifest), str(self.outside), "--dry-run")
      self.assertEqual(status, 0)
      self.assertIn("would import", out)
      self.assertEqual(self.manifest.read_bytes(), before)
      status, out = run_cli("project", "add-world", str(self.manifest), str(self.outside), "--import",
                            "--map", SOURCE_MAPS[0])
      self.assertEqual(status, 0, out)
      self.assertIn(f"maps: {game_world.NEW_WORLD_FILE}", out)
      self.assertEqual(Project.open(self.game / game_world.NEW_WORLD_FILE).map_names(), [SOURCE_MAPS[0]])
      status, out = run_cli("project", "files", str(self.manifest))
      self.assertEqual(status, 0, out)

   def test_sandbox_option(self) -> None:
      """!--sandbox names the engine's map sandbox world; it and a world file together are refused.
      @return None
      """
      sandbox = game_world.sandbox_world()
      self.assertIsNotNone(sandbox)
      self.assertTrue(sandbox.is_file())
      status, out = run_cli("project", "add-world", str(self.manifest), "--sandbox", "--dry-run")
      self.assertEqual(status, 0, out)
      self.assertIn(str(sandbox), out)
      status, _out = run_cli("project", "add-world", str(self.manifest), str(self.outside), "--sandbox")
      self.assertNotEqual(status, 0)


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtAddWorldTests(unittest.TestCase):
   """!The Studio's Add world to game... on a game without a world."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!A game without battle data (its pages open with nothing to complain about) and a world outside it.
      @return None
      """
      ## The temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_game_world_"))
      ## The game's project manifest.
      self.manifest = make_game(self.root / "game", battle=False)
      ## A world outside the game.
      self.outside = make_world(self.root / "elsewhere" / "world.json")
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_add_world_opens_it_on_the_world_page(self) -> None:
      """!The action is in the Studio menu and the World page's File menu; adding a world imports it, names it in
      the manifest and opens it on the World page.
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      w = StudioWindow(str(self.manifest))
      try:
         self.assertIn(w.add_world_action, w.studio_menu.actions())
         world_page = w.window_of("world")
         files = [a.menu() for a in world_page.menuBar().actions()
                  if a.menu() is not None and a.text().replace("&", "") == "File"]
         self.assertIn(w.add_world_action, files[0].actions())
         self.assertTrue(w.add_world_to_game(self.outside, [SOURCE_MAPS[0]]))
         target = (self.root / "game" / game_world.NEW_WORLD_FILE).resolve()
         self.assertEqual(manifest_io.load(self.manifest)["maps"], game_world.NEW_WORLD_FILE)
         self.assertEqual(w.current_page_id(), "world")
         world_page = w.window_of("world")
         self.assertEqual(world_page.project.world.path, target)
         self.assertEqual(world_page.project.map_names(), [SOURCE_MAPS[0]])
         # Asking again for the same world: nothing to do, the game keeps it.
         self.assertTrue(w.add_world_to_game(target, []))
         self.assertEqual(manifest_io.load(self.manifest)["maps"], game_world.NEW_WORLD_FILE)
      finally:
         w.close()
         w.deleteLater()
         self.app.processEvents()


if __name__ == "__main__":
   unittest.main()
