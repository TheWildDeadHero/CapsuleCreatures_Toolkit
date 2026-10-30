#!/usr/bin/env python3
"""!Every new game has a first scene (D-40 RG): core.templates.new_game() gives each game, whatever its template,
src/game.cpp (from capsule_studio/starter_scene/game.cpp.in, core.starter_scene), the player's sprite in its asset
manifest, and the project manifest's "sources" and "rom" header, so the engine's capsule_game() builds it at once.

  - For every template found: the scene's file, its title, no template mark left, the engine's style check passes;
    "sources" and "rom" (a header title from the name, the generic code); the asset manifest has sprite:PLAYER once.
  - What capsule_game() runs on a game passes: the engine's build settings check, asset, battle and map compilers.
    The C++ build itself needs a toolchain and is the engine's (`./build PRESET --game FOLDER`); not here.
  - Names: build_name() keeps a build target's characters, rom_title() a header's, title_text() what the box and
    a C++ string hold; `capsule-studio new --name` uses them.
  - new_game(..., world=False) writes no scene; add() refuses a game that has src/game.cpp already.
  - The Studio's GBA memory page finds a game's build/<preset> folders (core.gba_memory.build_folders()).
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine, game_world, gba_memory, manifest_io, starter_scene, templates  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402

## The player's sprite key in the game's asset manifest.
PLAYER = "sprite:PLAYER"
## A name with characters no build target, header or C++ string keeps as they are.
ODD_NAME = 'Moss & Stone: "Quest" 2\\'
## What build_name(), rom_title() and title_text() make of it.
ODD_FORMS = ("Moss_Stone_Quest_2", "MOSS STONE Q", "Moss & Stone: Quest 2")
## A preset folder of a game's build (the umbrella's ./build gba-release --game FOLDER).
GBA_PRESET = "gba-release"


def run_cli(*argv: object) -> tuple[int, str]:
   """!Runs the capsule-studio command line.
   @param argv  arguments
   @return (status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      status = cli([str(a) for a in argv])
   return status, out.getvalue() + err.getvalue()


def engine_tool(name: str, *argv: object) -> subprocess.CompletedProcess[str]:
   """!Runs one of the engine's tools as its build does.
   @param name  the tool's path under the engine (e.g. "tools/asset_compiler.py")
   @param argv  arguments
   @return the finished process
   """
   return subprocess.run([sys.executable, str(engine.root() / name), *(str(a) for a in argv)], capture_output=True,
                         text=True, check=False)


class NewGameSceneTests(unittest.TestCase):
   """!new_game() and `capsule-studio new` give every template's game a scene that the engine's build takes."""

   def setUp(self) -> None:
      """!A temporary folder.
      @return None
      """
      ## The temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_new_scene_"))

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def check_scene(self, manifest: Path, shown: str, label: str) -> None:
      """!The game's scene and the manifest entries capsule_game() reads, and the engine's tools on them.
      @param manifest  the game's reference/project.json
      @param shown     the name given to New game (or the folder's)
      @param label     for the messages
      @return None
      """
      game = manifest.parent.parent
      data = manifest_io.load(manifest)
      self.assertEqual(data["name"], starter_scene.build_name(shown), label)
      self.assertEqual(data[starter_scene.SOURCES_KEY], [starter_scene.SOURCE_FILE], label)
      self.assertEqual(data[starter_scene.ROM_KEY], {"title": starter_scene.rom_title(shown),
                                                     "code": starter_scene.ROM_CODE,
                                                     "maker": starter_scene.ROM_MAKER}, label)
      keys = list(data)
      # the header and the sources after the manifest's own keys, before the data files (the world first)
      self.assertEqual(keys[keys.index(starter_scene.EDITOR_KEY) + 1:keys.index(game_world.MAPS_KEY)],
                       [starter_scene.ROM_KEY, starter_scene.SOURCES_KEY], label)

      # The scene: the template with the title in place, in the project's C++ style.
      source = game / starter_scene.SOURCE_FILE
      text = source.read_text(encoding="utf-8")
      self.assertTrue(text.startswith("/// @file"), label)
      self.assertIn(f'text::encode("{starter_scene.title_text(shown)}")', text, label)
      self.assertIsNone(starter_scene.MARK.search(text), label)
      self.assertIn("overworld::start(", text, label)
      self.assertNotIn("\t", text, label)
      done = engine_tool("tools/ci/check_style.py", source)
      self.assertEqual(done.returncode, 0, f"{label}: {done.stdout}{done.stderr}")

      # The player's sprite, once, in the asset manifest the game names.
      assets_path = game / data[starter_scene.ASSETS_KEY]
      assets = manifest_io.load(assets_path)["assets"]
      self.assertEqual([a["key"] for a in assets].count(PLAYER), 1, label)

      # What capsule_game() runs before the C++ build: the build settings, the assets, the battle data, the world.
      out = self.root / "generated" / label
      out.mkdir(parents=True, exist_ok=True)
      runs = [engine_tool("tools/build_settings.py", manifest, "--cmake"),
              engine_tool("tools/asset_compiler.py", assets_path, out / "assets.cpp"),
              engine_tool("tools/battle_compiler.py", game / data[game_world.BATTLE_KEY], out / "battle.cpp",
                          "--ids", out / "battle_ids.h", "--platform", "gba"),
              engine_tool("tools/map_compiler.py", game / data[game_world.MAPS_KEY], out / "world.cpp", "--ids",
                          out / "encounter_ids.h", "--world-ids", out / "world_ids.h")]
      for done in runs:
         self.assertEqual(done.returncode, 0, f"{label}: {done.args[1]}: {done.stdout}{done.stderr}")

   def test_every_template_gets_a_scene(self) -> None:
      """!Each template found: new_game() writes the scene, the sprite and the manifest entries, and the engine's
      tools take them.
      @return None
      """
      found, _problems = templates.discover()
      self.assertGreaterEqual(len(found), 2)   # Blank and the engine's Starter at least
      for t in found:
         with self.subTest(template=t.id):
            self.check_scene(templates.new_game(self.root / t.id, t), t.id, t.id)

   def test_cli_new_with_a_name(self) -> None:
      """!`capsule-studio new GAME --template blank --name NAME`: the name's build, header and title forms.
      @return None
      """
      status, out = run_cli("new", self.root / "cli_game", "--template", "blank", "--name", ODD_NAME)
      self.assertEqual(status, 0, out)
      manifest = self.root / "cli_game" / "reference" / "project.json"
      self.check_scene(manifest, ODD_NAME, "cli")
      data = manifest_io.load(manifest)
      self.assertEqual((data["name"], data["rom"]["title"]), ODD_FORMS[:2])
      self.assertEqual(starter_scene.title_text(ODD_NAME), ODD_FORMS[2])

   def test_names(self) -> None:
      """!build_name(), rom_title() and title_text() on plain, odd and empty names.
      @return None
      """
      self.assertEqual(starter_scene.build_name("MyGame"), "MyGame")
      self.assertEqual(starter_scene.build_name("My Game"), "My_Game")
      self.assertEqual(starter_scene.build_name("2nd try"), "game_2nd_try")
      self.assertEqual(starter_scene.build_name("!!"), starter_scene.DEFAULT_BUILD_NAME)
      self.assertEqual(starter_scene.rom_title("My Game"), "MY GAME")
      self.assertEqual(starter_scene.rom_title("A very long game name"), "A VERY LONG")
      self.assertLessEqual(len(starter_scene.rom_title("x" * 40)), starter_scene.ROM_TITLE_LENGTH)
      self.assertEqual(starter_scene.rom_title("éé"), starter_scene.DEFAULT_ROM_TITLE)
      self.assertEqual(starter_scene.title_text("Café  \"Bar\""), "Caf Bar")
      self.assertEqual(len(starter_scene.title_text("y" * 40)), starter_scene.TITLE_CELLS)
      self.assertEqual(starter_scene.title_text("\t"), starter_scene.DEFAULT_TITLE)
      self.assertEqual(starter_scene.title_text("a@B@c"), "a B c")   # no template mark in the source

   def test_without_a_world_or_twice(self) -> None:
      """!world=False writes no scene (a game as made before D-40 RN); add() refuses a game with the scene's file.
      @return None
      """
      manifest = templates.new_game(self.root / "bare", templates.find("blank"), world=False)
      data = manifest_io.load(manifest)
      self.assertNotIn(starter_scene.SOURCES_KEY, data)
      self.assertNotIn(starter_scene.ROM_KEY, data)
      self.assertFalse((self.root / "bare" / starter_scene.SOURCE_FILE).exists())
      game = self.root / "made"
      templates.new_game(game, templates.find("blank"))
      with self.assertRaises(DocumentError):
         starter_scene.add(game, manifest_io.load(game / "reference" / "project.json"), "made")

   def test_studio_finds_the_game_build(self) -> None:
      """!The GBA memory page lists a game's build/<preset> folder (where `./build PRESET --game` builds it).
      @return None
      """
      game = self.root / "built"
      templates.new_game(game, templates.find("blank"))
      folder = game / gba_memory.GAME_BUILDS / GBA_PRESET
      folder.mkdir(parents=True)
      (folder / gba_memory.CACHE_FILE).write_text(f"{gba_memory.GBAFIX}:FILEPATH=/opt/gbafix\n", encoding="utf-8")
      self.assertEqual(gba_memory.build_folders(game), [folder])


if __name__ == "__main__":
   unittest.main()
