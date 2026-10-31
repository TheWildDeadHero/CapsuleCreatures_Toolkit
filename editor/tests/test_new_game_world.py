#!/usr/bin/env python3
"""!Every new game has a world (D-40 RN): core.templates.new_game() gives each game, whatever its template,
data/world.json with one simple-shape tileset (core.starter_world: ground, path, wall) and the map "start", named
in reference/project.json as "maps" before "battle".

  - For every template found (built in, engine samples, ...): the world, tileset and map files exist, the
    manifest names the world before the battle data, the world points at the game's battle data, the map covers
    the engine's screen, its edge is wall and blocked, the start is on a passable cell.
  - The world builds: Project.validate(), `capsule-studio world validate` and the engine's own world compiler
    (tools/map_compiler.py, run as the engine's build runs it) pass; `capsule-studio new` makes the same world.
  - new_game(..., world=False) makes a game without a world (as before D-40 RN).
  - The Studio's New game opens the World page with the map "start" shown (Qt; skipped without PySide6).
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
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
from capsule_studio.core import (encounters, engine, game_world, manifest_io, maps,  # noqa: E402
                                 starter_world, templates)
from capsule_studio.core.world import Project  # noqa: E402

## Times the event loop runs to settle (scheduled refreshes post more events).
SETTLE_ROUNDS = 4
## The template the Studio test makes its game from.
STUDIO_TEMPLATE = "starter"


def run_cli(*argv: object) -> tuple[int, str]:
   """!Runs the capsule-studio command line.
   @param argv  arguments
   @return (status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      status = cli([str(a) for a in argv])
   return status, out.getvalue() + err.getvalue()


def compile_with_engine(world: Path, out: Path) -> subprocess.CompletedProcess[str]:
   """!Compiles a world with the engine's map compiler, with the outputs the engine's build asks for
   (capsule_game(): world.cpp, its depfile, encounter_ids.h, world_ids.h).
   @param world  world.json
   @param out    folder for the outputs
   @return the finished process
   """
   tool = engine.root() / "tools" / "map_compiler.py"
   out.mkdir(parents=True, exist_ok=True)
   return subprocess.run([sys.executable, str(tool), str(world), str(out / "world.cpp"), "--depfile",
                          str(out / "world.d"), "--ids", str(out / "encounter_ids.h"), "--world-ids",
                          str(out / "world_ids.h")], capture_output=True, text=True, check=False)


class NewGameWorldTests(unittest.TestCase):
   """!new_game() and `capsule-studio new` give every template's game a buildable world."""

   def setUp(self) -> None:
      """!A temporary folder.
      @return None
      """
      ## The temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_new_world_"))

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def check_world(self, manifest: Path, label: str) -> None:
      """!The game's world: linked first, pointed at its battle data, the starter tileset and map, a start on a
      passable cell, walls blocked, and it compiles in the toolkit and in the engine.
      @param manifest  the game's reference/project.json
      @param label     for the messages
      @return None
      """
      game = manifest.parent.parent
      data = manifest_io.load(manifest)
      self.assertEqual(data.get(game_world.MAPS_KEY), game_world.NEW_WORLD_FILE, label)
      keys = list(data)
      self.assertLess(keys.index(game_world.MAPS_KEY), keys.index(game_world.BATTLE_KEY), label)
      world_path = game / data[game_world.MAPS_KEY]
      world = Project.open(world_path)
      self.assertEqual(world.tileset_names(), [starter_world.TILESET], label)
      self.assertEqual(world.map_names(), [starter_world.START_MAP], label)
      self.assertTrue((world.base / "tilesets" / f"{starter_world.TILESET}.json").is_file(), label)
      self.assertTrue((world.base / "maps" / f"{starter_world.START_MAP}.json").is_file(), label)
      self.assertEqual(encounters.battle_path(world), (game / data[game_world.BATTLE_KEY]).resolve(), label)
      self.assertFalse(world.dirty, label)   # everything was saved

      # The tileset: one shape sheet (no image file) and the metatiles.
      ts = world.tileset(starter_world.TILESET).data
      self.assertEqual([s["name"] for s in ts["sheets"]], [starter_world.SHEET], label)
      self.assertNotIn("image", ts["sheets"][0], label)
      self.assertEqual([m["name"] for m in ts["metatiles"]], list(starter_world.METATILES), label)

      # The map: at least the screen, walls blocked on the edge, the start passable on the path.
      mp = world.map(starter_world.START_MAP).data
      x0, y0, x1, y1 = maps.bounds(mp)
      width, height = x1 - x0 + 1, y1 - y0 + 1
      self.assertEqual((x0, y0, width, height), (0, 0) + starter_world.map_size(), label)
      screen = (starter_world.DEFAULT_SCREEN_WIDTH // starter_world.METATILE_PIXELS,
                starter_world.DEFAULT_SCREEN_HEIGHT // starter_world.METATILE_PIXELS)
      self.assertGreaterEqual(width, screen[0], label)
      self.assertGreaterEqual(height, screen[1], label)
      names = maps.dictionary(mp)
      wall = names.index(f"{starter_world.TILESET}/{starter_world.WALL}")
      for x, y in ((0, 0), (x1, y1), (0, y1), (x1, 0), (width // 2, 0)):
         self.assertEqual(maps.get_tile(mp, starter_world.BACK_LAYER, x, y), wall, f"{label} {x},{y}")
         self.assertEqual(maps.unpack(maps.get(mp, x, y))["collision"], starter_world.WALL_COLLISION, label)
      start = world.world.data["start"]
      self.assertEqual(start["map"], starter_world.START_MAP, label)
      cell = maps.unpack(maps.get(mp, start["x"], start["y"]))
      self.assertIsNotNone(cell, label)
      self.assertEqual(cell["collision"], 0, label)
      self.assertEqual(names[maps.get_tile(mp, starter_world.BACK_LAYER, start["x"], start["y"])],
                       f"{starter_world.TILESET}/{starter_world.PATH}", label)

      # It builds: the toolkit's check, the CLI and the engine's own compiler.
      self.assertIsNone(world.validate(), label)
      status, out = run_cli("world", "validate", world_path)
      self.assertEqual(status, 0, f"{label}: {out}")
      done = compile_with_engine(world_path, self.root / "generated" / label)
      self.assertEqual(done.returncode, 0, f"{label}: {done.stdout}{done.stderr}")
      ids = (self.root / "generated" / label / "world_ids.h").read_text(encoding="utf-8")
      self.assertIn(f"MAP_{starter_world.START_MAP.upper()} = 0", ids, label)

   def test_every_template_gets_a_world(self) -> None:
      """!Each template found: new_game() makes the world, the manifest names it first, it builds.
      @return None
      """
      found, _problems = templates.discover()
      self.assertGreaterEqual(len(found), 2)   # Blank and the engine's Starter at least
      for t in found:
         with self.subTest(template=t.id):
            self.check_world(templates.new_game(self.root / t.id, t), t.id)

   def test_cli_new_gets_a_world(self) -> None:
      """!`capsule-studio new GAME --template blank` makes the same world and says so.
      @return None
      """
      status, out = run_cli("new", self.root / "cli_game", "--template", "blank")
      self.assertEqual(status, 0, out)
      self.assertIn(f"with a world ({game_world.NEW_WORLD_FILE}: map {starter_world.START_MAP})", out)
      self.check_world(self.root / "cli_game" / "reference" / "project.json", "cli")

   def test_without_a_world(self) -> None:
      """!new_game(..., world=False): no "maps" and no world files (a game as made before D-40 RN); create() then
      makes an empty world, and fill() refuses a world that has the starter tileset already.
      @return None
      """
      manifest = templates.new_game(self.root / "bare", templates.find("blank"), world=False)
      self.assertNotIn(game_world.MAPS_KEY, manifest_io.load(manifest))
      self.assertFalse((self.root / "bare" / game_world.NEW_WORLD_FILE).exists())
      from capsule_studio.core.document import DocumentError
      from capsule_studio.core.project import open_project
      game_world.create(open_project(manifest))
      world = Project.open(self.root / "bare" / game_world.NEW_WORLD_FILE)
      self.assertEqual(world.map_names(), [])
      starter_world.fill(world)
      with self.assertRaises(DocumentError):
         starter_world.fill(world)

   def test_map_size_follows_the_screen(self) -> None:
      """!The map covers the engine's screen in whole chunks (16 x 16 metatiles on the GBA's 240 x 160).
      @return None
      """
      width, height = starter_world.map_size()
      self.assertEqual((width % maps.CHUNK, height % maps.CHUNK), (0, 0))
      self.assertGreaterEqual(width * starter_world.METATILE_PIXELS, starter_world.DEFAULT_SCREEN_WIDTH)
      self.assertGreaterEqual(height * starter_world.METATILE_PIXELS, starter_world.DEFAULT_SCREEN_HEIGHT)
      self.assertEqual(starter_world.start_position(), (width // starter_world.HALF, height // starter_world.HALF))


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class StudioNewGameWorldTests(unittest.TestCase):
   """!The Studio's New game opens straight into the new game's world with its map shown."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication; settings in a temporary folder.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
      ## Temporary root.
      cls.root = Path(tempfile.mkdtemp(prefix="capsule_new_world_qt_"))
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(cls.root / "settings"))

   @classmethod
   def tearDownClass(cls) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(cls.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(SETTLE_ROUNDS):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def test_new_game_shows_the_world_page_with_the_map(self) -> None:
      """!New game: the World page is in front with its panels (not the empty state), the Map tab shows the map
      "start", and the status bar says so.
      @return None
      """
      from capsule_studio.ui.editors.mapedit import MapPanel
      from capsule_studio.ui.studio_shell import StudioWindow
      studio = StudioWindow(None)
      try:
         self.assertTrue(studio.new_game(STUDIO_TEMPLATE, self.root / "quest"))
         self.settle()
         self.assertEqual(studio.current_page_id(), "world")
         w = studio.windows["world"]
         self.assertIsNotNone(w.project)
         self.assertEqual(w.project.world.path, (self.root / "quest" / game_world.NEW_WORLD_FILE).resolve())
         self.assertIs(w.body.currentWidget(), w.tabs)
         self.assertTrue(w.tabs.isVisible())
         self.assertIsInstance(w.tabs.currentWidget(), MapPanel)
         self.assertEqual(w.selected_map(), starter_world.START_MAP)
         self.assertIn(starter_world.START_MAP, w.statusBar().currentMessage())
         self.assertIn("battle", studio.windows)   # the other pages opened too
      finally:
         for page in studio.windows.values():
            page._confirm_discard = lambda: True
         studio.close()
         studio.deleteLater()
         self.settle()


if __name__ == "__main__":
   unittest.main()
