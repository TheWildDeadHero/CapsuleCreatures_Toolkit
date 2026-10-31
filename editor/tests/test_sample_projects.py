#!/usr/bin/env python3
"""!Sample projects (D-40 RP): core.samples, `capsule-studio sample ...` and the Studio's Open a sample....

  - Listing: the engine's two release samples (Starter Battle, Map Sandbox), each with one line; find() by id and
    by name; sample.json is checked (schema, id = folder, one-line description, shared folders).
  - Copying: every app file but sample.json, byte for byte apart from the manifests whose paths are pointed at the
    copied shared files (data/starter, with editor.template recorded); the name rules (build_name(), the ROM
    header's title and generic code, editor.sample); refusals (a folder with files, the engine, the Studio).
  - Standing alone: outside_paths() finds nothing in a copy, and finds a path out, an absolute path, an include out
    and a library the engine does not link for every game; the app in place leads out (that is why it is copied).
  - Building: what capsule_game() runs before the C++ build (build settings, assets, battle data, world, scripts)
    passes on each copy, as does `capsule-studio world validate` where the sample has a world.
  - The command line: sample list / copy / check.
  - The Studio (Qt; skipped without PySide6): Studio > Open a sample... and the start window's button; a copy opens
    on its World page (Map Sandbox) or its Battle page (Starter Battle), with its world, scripts and battle data
    open on their pages; a refusal says why.
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine, manifest_io, samples, starter_scene, templates  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402

## The samples the release ships (the engine's release.yml SAMPLE_TARGETS).
RELEASE_SAMPLES = ("sandbox_map", "starter_battle")
## The sample with a world (and scripts).
WORLD_SAMPLE = "sandbox_map"
## The sample without one.
BATTLE_SAMPLE = "starter_battle"
## Where the shared Starter data goes in a copy.
SHARED_TO = "data/starter"
## A name with characters a build name drops.
ODD_NAME = "My World: Two!"
## Times the event loop runs to settle (scheduled refreshes post more events).
SETTLE_ROUNDS = 4
## Exit status of a command that found problems.
PROBLEMS_STATUS = 1


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
   @param name  path below the engine root, e.g. "tools/map_compiler.py"
   @param argv  arguments
   @return the finished process
   """
   return subprocess.run([sys.executable, str(engine.root() / name), *(str(a) for a in argv)], capture_output=True,
                         text=True, check=False)


def write_sample(folder: Path, data: dict) -> Path:
   """!A small app folder with a sample.json, for the manifest checks.
   @param folder  the app folder (its name is the id)
   @param data    the sample manifest
   @return the sample.json path
   """
   (folder / "reference").mkdir(parents=True)
   manifest_io.save(folder / "reference" / "project.json", {"schema": "capsule.project/1", "name": folder.name})
   manifest_io.save(folder / samples.SAMPLE_FILE, data)
   return folder / samples.SAMPLE_FILE


class SampleListTests(unittest.TestCase):
   """!discover(), find() and load()."""

   def setUp(self) -> None:
      """!A temporary folder.
      @return None
      """
      ## The temporary folder (resolved: macOS /var is /private/var, Windows has short names).
      self.root = Path(tempfile.mkdtemp(prefix="capsule_samples_")).resolve()

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_the_release_samples_are_listed(self) -> None:
      """!Both release samples, each an engine app with a one-line description and the Starter shared.
      @return None
      """
      found, problems = samples.discover()
      self.assertEqual(problems, [])
      self.assertEqual([s.id for s in found if s.id in RELEASE_SAMPLES], list(RELEASE_SAMPLES))
      for s in found:
         with self.subTest(sample=s.id):
            self.assertEqual(s.folder, engine.root() / samples.ENGINE_APPS / s.id)
            self.assertTrue(s.description)
            self.assertNotIn("\n", s.description)
            self.assertIn(s.id, s.label())
            self.assertEqual([(sh.template.id, sh.to) for sh in s.shared], [("starter", SHARED_TO)])
      self.assertEqual(samples.find("Map Sandbox").id, WORLD_SAMPLE)
      self.assertEqual(samples.find(BATTLE_SAMPLE).name, "Starter Battle")
      with self.assertRaises(DocumentError):
         samples.find("no_such_sample")

   def test_manifest_checks(self) -> None:
      """!A sample.json with a wrong schema, an id that is not its folder, a two-line description, a taken "to"
      folder or a shared folder that is not a template is refused.
      @return None
      """
      # A copy of the Starter beside the app: the temporary folder may be on another drive than the engine
      # (Windows), where no relative path leads to it.
      shutil.copytree(engine.root() / "samples" / "starter", self.root / "shared" / "starter")
      good = {"schema": samples.SCHEMA, "id": "demo", "name": "Demo", "description": "One line.", "version": 1,
              "shared": [{"from": "../shared/starter", "to": "data/starter"}]}
      path = write_sample(self.root / "demo", good)
      self.assertEqual(samples.load(path).shared[0].template.id, "starter")
      bad = [{"schema": "capsule.template/1"}, {"id": "other"}, {"description": "two\nlines"}, {"version": 0},
             {"shared": [{"from": "../nowhere", "to": "data/x"}]},
             {"shared": [{"from": good["shared"][0]["from"], "to": "../out"}]},
             {"shared": [{"from": good["shared"][0]["from"], "to": "reference"}]}, {"extra": True}]
      for change in bad:
         with self.subTest(change=change):
            manifest_io.save(path, {**good, **change})
            with self.assertRaises(DocumentError):
               samples.load(path)


class SampleCopyTests(unittest.TestCase):
   """!copy(): the files, the shared data, the paths, the name rules, the refusals."""

   def setUp(self) -> None:
      """!A temporary folder.
      @return None
      """
      ## The temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_sample_copy_"))

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_copies_stand_alone(self) -> None:
      """!Each sample: its files (sample.json left out; only manifests with paths into the shared folder change),
      the Starter's files in data/starter with editor.template, and nothing leads out of the copy.
      @return None
      """
      for sid in RELEASE_SAMPLES:
         with self.subTest(sample=sid):
            sample = samples.find(sid)
            project = samples.copy(sample, self.root / sid)
            game = project.parent.parent
            self.assertEqual(project, game / "reference" / "project.json")
            self.assertFalse((game / samples.SAMPLE_FILE).exists())
            self.assertEqual(samples.outside_paths(game), [])
            changed = []
            for rel in samples.sample_files(sample):
               if (sample.folder / rel).read_bytes() != (game / rel).read_bytes():
                  changed.append(rel)
            self.assertIn("reference/project.json", changed)
            self.assertTrue(all(rel.endswith(samples.JSON_SUFFIX) for rel in changed), changed)
            share = sample.shared[0].template
            for rel in share.files():
               self.assertTrue((game / SHARED_TO / rel).is_file(), rel)
            self.assertEqual(templates.recorded(game / SHARED_TO / "battle.json"),
                             {"id": share.id, "version": share.version})
            data = manifest_io.load(project)
            self.assertEqual(data["battle"], f"{SHARED_TO}/battle.json")
            self.assertEqual(data["editor"][samples.SAMPLE_KEY], {"id": sid, "version": sample.version})

   def test_world_and_scripts_point_at_the_copy(self) -> None:
      """!The Map Sandbox's world and scripts read the copy's battle data, by paths relative to themselves.
      @return None
      """
      game = samples.copy(samples.find(WORLD_SAMPLE), self.root / "world").parent.parent
      data = manifest_io.load(game / "reference" / "project.json")
      world = manifest_io.load(game / data["maps"])
      scripts = manifest_io.load(game / data["scripts"])
      self.assertEqual(world["battle"], "starter/battle.json")
      self.assertEqual(scripts["battle"], "../starter/battle.json")
      self.assertEqual((game / data["scripts"]).parent.joinpath(scripts["battle"]).resolve(),
                       (game / SHARED_TO / "battle.json").resolve())

   def test_name_rules(self) -> None:
      """!The copy's name is its build name, its ROM header takes the name's title and the generic code; without
      a name, the folder's name.
      @return None
      """
      data = manifest_io.load(samples.copy(samples.find(WORLD_SAMPLE), self.root / "a", ODD_NAME))
      self.assertEqual(data["name"], starter_scene.build_name(ODD_NAME))
      self.assertEqual(data["name"], "My_World_Two")
      self.assertEqual(data["rom"]["title"], starter_scene.rom_title(ODD_NAME))
      self.assertEqual(data["rom"]["code"], starter_scene.ROM_CODE)
      self.assertEqual(data["rom"]["maker"], "00")
      data = manifest_io.load(samples.copy(samples.find(BATTLE_SAMPLE), self.root / "2 fights"))
      self.assertEqual(data["name"], "game_2_fights")
      self.assertEqual(data["libraries"], ["test_kit", "battle_kit"])

   def test_refusals(self) -> None:
      """!A folder with files, the engine and the Studio's own folder are refused, and nothing is written there.
      @return None
      """
      sample = samples.find(BATTLE_SAMPLE)
      taken = self.root / "taken"
      taken.mkdir()
      (taken / "note.txt").write_text("mine", encoding="utf-8")
      with self.assertRaises(DocumentError):
         samples.copy(sample, taken)
      self.assertEqual(sorted(p.name for p in taken.iterdir()), ["note.txt"])
      for guarded in (engine.root() / "rp_sample_copy_test", engine.STUDIO_ROOT / "rp_sample_copy_test"):
         with self.subTest(folder=str(guarded)):
            with self.assertRaises(DocumentError) as caught:
               samples.copy(sample, guarded)
            self.assertIn("own files", str(caught.exception))
            self.assertFalse(guarded.exists())
      self.assertIn(engine.root(), samples.protected_folders())
      with mock.patch.object(sys, "frozen", True, create=True):
         self.assertIn(Path(sys.executable).resolve().parent, samples.protected_folders())


class OutsidePathTests(unittest.TestCase):
   """!outside_paths(): what ties a game folder to files outside it."""

   def setUp(self) -> None:
      """!A copy of the Starter Battle to break.
      @return None
      """
      ## The temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_sample_paths_"))
      ## The copy.
      self.game = samples.copy(samples.find(BATTLE_SAMPLE), self.root / "game").parent.parent

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_each_kind_of_tie_is_found(self) -> None:
      """!A JSON path out, an absolute path that exists, an include line out and a library not every game has.
      @return None
      """
      project = self.game / "reference" / "project.json"
      data = manifest_io.load(project)
      data["assets"] = "../outside/assets.json"
      data["libraries"] = ["test_kit", "engine_tests_only"]
      manifest_io.save(project, data)
      battle = self.game / SHARED_TO / "battle.json"
      content = manifest_io.load(battle)
      content["editor"]["image"] = str(engine.root() / "CMakeLists.txt")
      manifest_io.save(battle, content)
      (self.game / "src" / "extra.h").write_text('#include "../../elsewhere/x.h"\n#include "ok.h"\n',
                                                  encoding="utf-8")
      problems = samples.outside_paths(self.game)
      self.assertEqual(len(problems), 4, problems)
      self.assertTrue(any("../outside/assets.json" in p for p in problems))
      self.assertTrue(any("CMakeLists.txt" in p for p in problems))
      self.assertTrue(any("#include" in p for p in problems))
      self.assertTrue(any("engine_tests_only" in p for p in problems))

   def test_the_app_in_place_leads_out(self) -> None:
      """!The engine's app itself reads the engine's Starter data: that is what copy() brings along.
      @return None
      """
      problems = samples.outside_paths(samples.find(WORLD_SAMPLE).folder)
      self.assertTrue(any("samples/starter/battle.json" in p for p in problems), problems)

   def test_game_libraries_are_the_engines(self) -> None:
      """!Every library a copy may link is a library the engine's CMakeLists.txt defines.
      @return None
      """
      cmake = (engine.root() / "CMakeLists.txt").read_text(encoding="utf-8")
      for library in samples.GAME_LIBRARIES:
         self.assertIn(f"add_library(capsule_{library} ", cmake)


class SampleBuildTests(unittest.TestCase):
   """!The engine's compilers and the Studio's world check take each copy (no C++ compile: the toolkit's tests
   have no toolchain; the umbrella's check.yml builds a copy as a GBA ROM)."""

   def setUp(self) -> None:
      """!A temporary folder.
      @return None
      """
      ## The temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_sample_build_"))

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_compilers_take_each_copy(self) -> None:
      """!Build settings, assets, battle data (GBA), world and scripts, with the arguments capsule_game() gives.
      @return None
      """
      for sid in RELEASE_SAMPLES:
         with self.subTest(sample=sid):
            project = samples.copy(samples.find(sid), self.root / sid)
            game = project.parent.parent
            data = manifest_io.load(project)
            out = self.root / "generated" / sid
            out.mkdir(parents=True)
            scripts = ["--scripts", game / data["scripts"]] if "scripts" in data else []
            names = ["--debug-names"] if data.get("debug_names") else []
            runs = [engine_tool("tools/build_settings.py", project, "--cmake"),
                    engine_tool("tools/asset_compiler.py", game / data["assets"], out / "assets.cpp", *scripts),
                    engine_tool("tools/battle_compiler.py", game / data["battle"], out / "battle.cpp", "--ids",
                                out / "battle_ids.h", "--platform", "gba", *scripts)]
            if "maps" in data:
               runs.append(engine_tool("tools/map_compiler.py", game / data["maps"], out / "world.cpp", "--ids",
                                       out / "encounter_ids.h", "--world-ids", out / "world_ids.h", *names,
                                       *scripts))
               status, text = run_cli("world", "validate", game / data["maps"])
               self.assertEqual(status, 0, text)
            if "scripts" in data:
               runs.append(engine_tool("tools/script_compiler.py", game / data["scripts"], out / "scripts.cpp",
                                       "--ids", out / "script_ids.h", *names))
            for done in runs:
               self.assertEqual(done.returncode, 0, f"{sid}: {done.args[1]}: {done.stdout}{done.stderr}")


class SampleCliTests(unittest.TestCase):
   """!`capsule-studio sample list | copy | check`."""

   def setUp(self) -> None:
      """!A temporary folder.
      @return None
      """
      ## The temporary folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_sample_cli_"))

   def tearDown(self) -> None:
      """!Removes the temporary folder.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def test_list_copy_check(self) -> None:
      """!list names both with their line; copy makes a game that check passes; check fails on the app in place;
      copy refuses the engine.
      @return None
      """
      status, text = run_cli("sample", "list")
      self.assertEqual(status, 0, text)
      for sid in RELEASE_SAMPLES:
         self.assertIn(f"{sid}: {samples.find(sid).name} - ", text)
      status, text = run_cli("sample", "copy", WORLD_SAMPLE, self.root / "mine", "--name", "Mine")
      self.assertEqual(status, 0, text)
      self.assertIn("--game", text)
      self.assertEqual(manifest_io.load(self.root / "mine" / "reference" / "project.json")["name"], "Mine")
      status, text = run_cli("sample", "check", self.root / "mine")
      self.assertEqual(status, 0, text)
      status, text = run_cli("sample", "check", samples.find(WORLD_SAMPLE).folder)
      self.assertEqual(status, PROBLEMS_STATUS, text)
      self.assertIn("leads out of the game folder", text)
      status, text = run_cli("sample", "copy", BATTLE_SAMPLE, engine.root() / "rp_cli_copy_test")
      self.assertNotEqual(status, 0, text)
      self.assertFalse((engine.root() / "rp_cli_copy_test").exists())


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class StudioOpenSampleTests(unittest.TestCase):
   """!The Studio's Open a sample...: menu, start window, the copy opened on its pages."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication; settings in a temporary folder.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
      ## Temporary root.
      cls.root = Path(tempfile.mkdtemp(prefix="capsule_sample_qt_"))
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

   def studio(self) -> object:
      """!A Studio window with no game, closed at the end of the test.
      @return StudioWindow
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      studio = StudioWindow(None)

      def close() -> None:
         """!Closes the Studio without asking."""
         for page in studio.windows.values():
            page._confirm_discard = lambda: True
         studio.close()
         studio.deleteLater()
         self.settle()

      self.addCleanup(close)
      return studio

   def opened(self, studio: object, page_id: str) -> Path | None:
      """!What a page has open.
      @param studio   StudioWindow
      @param page_id  page id
      @return the file, resolved, or None
      """
      from capsule_studio.ui.studio_shell import page_by_id
      w = studio.windows.get(page_id)
      path = page_by_id(page_id).opened(w) if w is not None else None
      return Path(path).resolve() if path is not None else None

   def test_menu_and_start_window(self) -> None:
      """!Studio > Open a sample... and the start window's button, beside New game....
      @return None
      """
      studio = self.studio()
      items = [a.text().replace("&", "") for a in studio.studio_menu.actions()]
      self.assertEqual(items[items.index("New game...") + 1], "Open a sample...")
      labels = [b.text() for b in studio.start.findChildren(QtWidgets.QPushButton)]
      self.assertIn("Open a sample...", labels)
      self.assertEqual(labels.index("Open a sample..."), labels.index("New game...") + 1)

   def test_dialog_lists_the_samples(self) -> None:
      """!Each sample is a row with its name and one line; the description names what is copied along.
      @return None
      """
      from capsule_studio.ui.sample_dialog import SampleDialog
      dialog = SampleDialog()
      self.addCleanup(dialog.deleteLater)
      rows = [dialog.sample_list.item(i).text() for i in range(dialog.sample_list.count())]
      for sid in RELEASE_SAMPLES:
         s = samples.find(sid)
         self.assertIn(f"{s.name}\n{s.description}", rows)
      self.assertTrue(dialog.select(WORLD_SAMPLE))
      self.assertIn(SHARED_TO, dialog.description.text())
      self.assertIsNone(dialog.copy_sample())   # no folder yet
      self.assertTrue(dialog.message.text())

   def test_map_sandbox_opens_on_its_world(self) -> None:
      """!The Map Sandbox's copy: the World page in front with its start map, its scripts and battle data open,
      every file from the copy.
      @return None
      """
      studio = self.studio()
      folder = self.root / "world"
      self.assertTrue(studio.open_sample(WORLD_SAMPLE, folder, "My world"))
      self.settle()
      game = folder.resolve()
      self.assertEqual(studio.project_path.resolve(), game / "reference" / "project.json")
      self.assertEqual(studio.current_page_id(), "world")
      w = studio.windows["world"]
      self.assertIsNotNone(w.project)
      self.assertEqual(self.opened(studio, "world"), game / "data" / "world.json")
      self.assertEqual(w.selected_map(), w.project.world.data["start"]["map"])
      self.assertEqual(self.opened(studio, "scripts"), game / "data" / "scripts" / "scripts.json")
      self.assertEqual(self.opened(studio, "battle"), game / SHARED_TO / "battle.json")
      self.assertIn("--game", w.statusBar().currentMessage())

   def test_starter_battle_opens_on_its_battle_page(self) -> None:
      """!The Starter Battle's copy (no world): the Battle page in front on the copy's battle data.
      @return None
      """
      studio = self.studio()
      folder = self.root / "battles"
      self.assertTrue(studio.open_sample(BATTLE_SAMPLE, folder))
      self.settle()
      self.assertEqual(studio.current_page_id(), "battle")
      self.assertEqual(self.opened(studio, "battle"), folder.resolve() / SHARED_TO / "battle.json")
      self.assertEqual(self.opened(studio, "assets"), folder.resolve() / SHARED_TO / "assets.json")

   def test_refusal_says_why(self) -> None:
      """!A copy into the engine is refused with the reason, and the Studio opens nothing.
      @return None
      """
      studio = self.studio()
      target = engine.root() / "rp_qt_copy_test"
      with mock.patch("capsule_studio.ui.studio_shell.report_failure") as report:
         self.assertFalse(studio.open_sample(BATTLE_SAMPLE, target))
      self.assertIn("own files", report.call_args[0][2])
      self.assertIsNone(studio.project_path)
      self.assertFalse(target.exists())


if __name__ == "__main__":
   unittest.main()
