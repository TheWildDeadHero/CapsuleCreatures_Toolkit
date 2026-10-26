#!/usr/bin/env python3
"""!Tests for project manifests, their build settings and the data files
they name (capsule_studio.core.project), `capsule-studio project build` and
`capsule-studio project files` (no Qt needed).

Uses a copy of the engine's VRAM test app manifest (apps/test_vram/reference).
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine, project  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402


class ProjectData(unittest.TestCase):
   """!Base: a copy of test_vram's project.json per test."""

   def setUp(self) -> None:
      """!Copies the manifest.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_project_"))
      (self.root / "reference").mkdir()
      ## The copy's project.json.
      self.manifest = self.root / "reference" / "project.json"
      shutil.copy(engine.root() / "apps" / "test_vram" / "reference" / "project.json", self.manifest)

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def run_cli(self, *args: object) -> tuple[int, str]:
      """!Runs capsule-studio.
      @param args  arguments
      @return (status, output)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         status = cli([str(a) for a in args])
      return status, out.getvalue() + err.getvalue()


class CoreTests(ProjectData):
   """!core.project."""

   def test_rows_and_defaults(self) -> None:
      """!Every engine setting is listed; absent keys show the engine default.
      @return None
      """
      doc = project.open_project(self.manifest)
      project.clear_setting(doc, "vram_budget_cycles")
      rows = {r.key: r for r in project.rows(doc)}
      self.assertEqual(list(rows), [s.key for s in project.settings_tool().SETTINGS])
      self.assertFalse(rows["vram_budget_cycles"].given)
      self.assertEqual(rows["vram_budget_cycles"].value, 68 * 1232 - 16384)
      self.assertTrue(rows["gba_waitcnt"].given)
      self.assertEqual(rows["gba_waitcnt"].shown, "0x4014")

   def test_set_check_undo_save(self) -> None:
      """!Values are checked by the engine's rules; each change is one undo step; save writes them.
      @return None
      """
      doc = project.open_project(self.manifest)
      self.assertEqual(project.set_setting(doc, "vram_streaming_slots", "128"), 128)
      with self.assertRaises(DocumentError):
         project.set_setting(doc, "vram_streaming_slots", 100)
      with self.assertRaises(DocumentError):
         project.set_setting(doc, "nope", 1)
      self.assertEqual(project.set_setting(doc, "gba_waitcnt", 0x4317), "0x4317")
      self.assertEqual(doc.undo_label(), "Set gba_waitcnt")
      doc.undo()
      self.assertEqual(doc.data["build"]["gba_waitcnt"], "0x4014")
      doc.save()
      self.assertEqual(json.loads(self.manifest.read_text())["build"]["vram_streaming_slots"], 128)

   def test_waitcnt_fields_and_problems(self) -> None:
      """!Field edits keep the other fields; slower ROM timing gets a caution.
      @return None
      """
      doc = project.open_project(self.manifest)
      self.assertEqual(project.problems(doc), [])
      self.assertEqual(project.set_waitcnt_fields(doc, {"ws0_first": 4}), 0x4010)
      self.assertEqual(project.set_waitcnt_fields(doc, {"prefetch": "off"}), 0x0010)
      msgs = [m for _s, m in project.problems(doc)]
      self.assertTrue(any("4/1" in m for m in msgs) and any("prefetch" in m for m in msgs), msgs)
      with self.assertRaises(DocumentError):
         project.set_waitcnt_fields(doc, {"ws0_first": 5})

   def test_default_removes_empty_build(self) -> None:
      """!Going back to every default removes the "build" object.
      @return None
      """
      doc = project.open_project(self.manifest)
      for s in project.settings_tool().SETTINGS:
         project.clear_setting(doc, s.key)
      self.assertNotIn("build", doc.data)

   def test_bad_manifest_value(self) -> None:
      """!A value the build would reject is reported, not hidden.
      @return None
      """
      data = json.loads(self.manifest.read_text())
      data["build"]["vram_must_land_slots"] = 24
      self.manifest.write_text(json.dumps(data))
      doc = project.open_project(self.manifest)
      self.assertEqual(project.problems(doc)[0][0], "error")
      rows = {r.key: r for r in project.rows(doc)}   # every row still shows
      self.assertIn("power of two", rows["vram_must_land_slots"].error)
      self.assertEqual(rows["vram_budget_cycles"].value, 67392)
      project.set_setting(doc, "vram_must_land_slots", 32)   # fixing it works
      self.assertEqual(project.problems(doc), [])
      doc.data["build"] = [1]
      with self.assertRaises(DocumentError):
         project.set_setting(doc, "vram_must_land_slots", 32)
      with self.assertRaises(DocumentError):
         project.rows(doc)


class CliTests(ProjectData):
   """!capsule-studio project build."""

   def test_show_and_change(self) -> None:
      """!Shows the settings; --set, --default and --waitcnt change and save them.
      @return None
      """
      status, out = self.run_cli("project", "build", self.manifest)
      self.assertEqual(status, 0, out)
      self.assertIn("vram_must_land_slots = 32", out)
      status, out = self.run_cli("project", "build", self.manifest, "--set", "vram_budget_cycles=60000",
                                 "--default", "vram_streaming_slots", "--waitcnt", "ws0_first=4")
      self.assertEqual(status, 0, out)
      self.assertIn("vram_streaming_slots = 64  (engine default)", out)
      self.assertIn("warning: ROM wait states are 4/1", out)
      build = json.loads(self.manifest.read_text())["build"]
      self.assertEqual(build, {"vram_must_land_slots": 32, "vram_budget_cycles": 60000, "gba_waitcnt": "0x4010"})
      status, out = self.run_cli("project", "build", self.manifest, "--set", "vram_budget_cycles=5")
      self.assertNotEqual(status, 0)
      self.assertIn("outside", out)


class GameFileTests(ProjectData):
   """!The data files a project names (what the Studio opens): core.project.game_files() and `project files`."""

   def write(self, **keys: str | None) -> None:
      """!Sets keys of the copied manifest and creates the files they name.
      @param keys  manifest key -> relative path (None: the key is removed)
      @return None
      """
      data = json.loads(self.manifest.read_text(encoding="utf-8"))
      for k, v in keys.items():
         data.pop(k, None) if v is None else data.__setitem__(k, v)
      self.manifest.write_text(json.dumps(data), encoding="utf-8")

   def test_files_are_relative_to_the_game_folder(self) -> None:
      """!Paths resolve from the folder reference/ is in; keys not given are left out.
      @return None
      """
      self.write(maps="data/world.json", scripts="data/scripts/scripts.json", battle=None, assets="data/assets.json")
      (self.root / "data").mkdir()
      (self.root / "data" / "world.json").write_text("{}", encoding="utf-8")
      doc = project.open_project(self.manifest)
      files = project.game_files(doc)
      self.assertEqual(project.game_folder(doc), self.root.resolve())
      self.assertEqual(files["maps"], (self.root / "data" / "world.json").resolve())
      self.assertEqual(set(files), {"maps", "assets", "scripts"})
      self.assertEqual([k for k, _what in project.GAME_FILES], ["maps", "assets", "scripts", "battle", "audio"])

   def test_bad_path(self) -> None:
      """!A key that is not a relative path is an error.
      @return None
      """
      self.write(maps=12)
      with self.assertRaises(DocumentError):
         project.game_files(project.open_project(self.manifest))

   def test_cli_lists_files(self) -> None:
      """!`project files` lists each key, marks missing files and fails then.
      @return None
      """
      self.write(maps="data/world.json", assets="data/assets.json", scripts=None, battle=None)
      (self.root / "data").mkdir()
      (self.root / "data" / "world.json").write_text("{}", encoding="utf-8")
      status, out = self.run_cli("project", "files", self.manifest)
      self.assertEqual(status, 1, out)
      lines = out.splitlines()
      self.assertTrue(lines[0].startswith("maps: data/world.json") and "(missing)" not in lines[0], out)
      self.assertIn("assets: data/assets.json  (missing)", lines[1])
      self.assertTrue(lines[2].startswith("scripts: (none)"), out)
      (self.root / "data" / "assets.json").write_text("{}", encoding="utf-8")
      self.assertEqual(self.run_cli("project", "files", self.manifest)[0], 0)


if __name__ == "__main__":
   unittest.main()
