#!/usr/bin/env python3
"""!Tests for script editing (capsule_studio.core.scripts) and the
`capsule-studio script` commands (no Qt needed).

Uses a copy of the engine's script test app data (apps/test_script/data).
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
from capsule_studio.core import engine  # noqa: E402
from capsule_studio.core import scripts  # noqa: E402


class ScriptData(unittest.TestCase):
   """!Base: a copy of the test app's scripts per test."""

   def setUp(self) -> None:
      """!Copies apps/test_script/data.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_scripts_"))
      shutil.copytree(engine.root() / "apps" / "test_script" / "data", self.root / "data")
      ## The copy's scripts.json.
      self.manifest = self.root / "data" / "scripts.json"

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


class CoreTests(ScriptData):
   """!core.scripts on the test app's scripts."""

   def test_open_and_check(self) -> None:
      """!The demo compiles; the outline lists its declarations with places.
      @return None
      """
      p = scripts.ScriptProject.open(self.manifest)
      self.assertEqual(p.sources, ["demo.cscript"])
      self.assertFalse(p.dirty)
      r = p.check()
      self.assertTrue(r.ok, [d.message for d in r.errors])
      self.assertGreater(r.save_bytes, 0)
      self.assertIn("greeting", r.outline.names("script"))
      self.assertIn("met_guide", r.outline.names("flag"))
      visits = r.outline.find("visits")
      self.assertEqual(visits["kind"], "var")
      self.assertEqual(visits["file"], "demo.cscript")
      self.assertIn("0..999", visits["detail"])
      self.assertIn("scripts", r.summary())

   def test_errors_point_at_source(self) -> None:
      """!An error in a buffer is reported with its file and line, without saving.
      @return None
      """
      p = scripts.ScriptProject.open(self.manifest)
      text = p.texts["demo.cscript"] + "\nscript broken {\n    set flag(nope);\n}\n"
      p.set_text("demo.cscript", text)
      self.assertTrue(p.dirty)
      r = p.check()
      self.assertFalse(r.ok)
      e = r.errors[0]
      self.assertEqual(e.file, "demo.cscript")
      self.assertEqual(e.line, text.count("\n") - 1)
      self.assertIn("nope", e.message)
      self.assertNotIn("broken", (self.root / "data" / "demo.cscript").read_text())

   def test_declare_and_save(self) -> None:
      """!Declare appends a line that compiles; save writes it.
      @return None
      """
      p = scripts.ScriptProject.open(self.manifest)
      line = p.declare("demo.cscript", "var", "strides", "daily", "u16", 0, 500)
      self.assertEqual(line, "var strides : u16 daily 0..500;")
      self.assertTrue(p.check().ok)
      with self.assertRaises(scripts.ScriptsError):
         p.declare("demo.cscript", "flag", "strides")
      with self.assertRaises(scripts.ScriptsError):
         p.declare("demo.cscript", "flag", "while")
      p.save()
      self.assertFalse(p.dirty)
      again = scripts.ScriptProject.open(self.manifest)
      self.assertIsNotNone(again.check().outline.find("strides"))

   def test_rename_follows_uses(self) -> None:
      """!Rename changes the declaration and every use, and the result compiles.
      @return None
      """
      p = scripts.ScriptProject.open(self.manifest)
      before = p.texts["demo.cscript"].count("met_guide")
      n = p.rename("met_guide", "guide_met")
      self.assertEqual(n, before)
      self.assertNotIn("met_guide", p.texts["demo.cscript"])
      r = p.check()
      self.assertTrue(r.ok, [d.message for d in r.errors])
      self.assertIn("guide_met", r.outline.names("flag"))
      with self.assertRaises(scripts.ScriptsError):
         p.rename("guide_met", "coins")      # taken
      with self.assertRaises(scripts.ScriptsError):
         p.rename("no_such_name", "x")

   def test_rename_skips_other_meanings(self) -> None:
      """!Rename leaves build variants, map names, native parameters and labels alone.
      @return None
      """
      p = scripts.ScriptProject.open(self.manifest)
      p.set_text("demo.cscript", p.texts["demo.cscript"] + (
         "\nflag other;\nwhen game(other) { flag only_other; }\nnative give(room_talk);\n"
         "script room_talk { other: set flag(other); native give(1); }\n"
         "map_scripts room_talk { on_load -> room_talk; }\n"))
      p.manifest["games"] = ["other", "base"]
      r = p.check()
      self.assertTrue(r.ok, [d.message for d in r.errors])
      self.assertEqual(p.rename("other", "seen_other"), 2)   # declaration and set flag(...)
      text = p.texts["demo.cscript"]
      self.assertIn("when game(other)", text)
      self.assertIn("other: set flag(seen_other);", text)
      self.assertEqual(p.rename("room_talk", "talk_room"), 2)   # script and on_load target
      text = p.texts["demo.cscript"]
      self.assertIn("map_scripts room_talk", text)
      self.assertIn("native give(room_talk)", text)
      r = p.check()
      self.assertTrue(r.ok, [d.message for d in r.errors])

   def test_not_utf8_source(self) -> None:
      """!A source that is not UTF-8 is reported, read-only, and never overwritten.
      @return None
      """
      src = self.root / "data" / "demo.cscript"
      src.write_bytes(b"// caf\xe9\n")
      p = scripts.ScriptProject.open(self.manifest)
      self.assertEqual(p.unreadable, ["demo.cscript"])
      self.assertIn("not UTF-8", p.check().errors[0].message)
      with self.assertRaises(scripts.ScriptsError):
         p.set_text("demo.cscript", "")
      p.save()
      self.assertEqual(src.read_bytes(), b"// caf\xe9\n")

   def test_sources_and_settings(self) -> None:
      """!Adding and removing sources; settings are validated.
      @return None
      """
      p = scripts.ScriptProject.open(self.manifest)
      p.add_source("extra/more.cscript")
      self.assertIn("extra/more.cscript", p.sources)
      self.assertTrue(p.check().ok)
      with self.assertRaises(scripts.ScriptsError):
         p.add_source("extra/more.cscript")
      with self.assertRaises(scripts.ScriptsError):
         p.add_source("notes.txt")
      with self.assertRaises(scripts.ScriptsError):
         p.set_setting("stack_depth", 99)
      p.set_setting("stack_depth", 12)
      p.save()
      self.assertTrue((self.root / "data" / "extra" / "more.cscript").is_file())
      m = json.loads(self.manifest.read_text())
      self.assertEqual(m["stack_depth"], 12)
      self.assertIn("extra/more.cscript", m["sources"])
      p.remove_source("extra/more.cscript")
      p.save()
      self.assertTrue((self.root / "data" / "extra" / "more.cscript").is_file())   # the file stays
      self.assertNotIn("extra/more.cscript", json.loads(self.manifest.read_text())["sources"])

   def test_create(self) -> None:
      """!A new manifest's template compiles.
      @return None
      """
      p = scripts.ScriptProject.create(self.root / "new" / "scripts.json", "town")
      self.assertEqual(p.sources, ["town.cscript"])
      self.assertTrue(p.check().ok)
      with self.assertRaises(scripts.ScriptsError):
         scripts.ScriptProject.create(self.root / "new" / "scripts.json")


class CliTests(ScriptData):
   """!capsule-studio script ..."""

   def test_check_and_list(self) -> None:
      """!check passes on the demo; list prints declarations.
      @return None
      """
      status, out = self.run_cli("script", "check", self.manifest)
      self.assertEqual(status, 0, out)
      self.assertIn("scripts", out)
      status, out = self.run_cli("script", "list", self.manifest, "--kind", "flag")
      self.assertEqual(status, 0, out)
      self.assertIn("met_guide", out)
      self.assertNotIn("greeting", out)

   def test_check_fails_on_error(self) -> None:
      """!check exits 1 and prints file:line for an error.
      @return None
      """
      src = self.root / "data" / "demo.cscript"
      src.write_text(src.read_text() + "\nscript bad { goto nowhere; }\n")
      status, out = self.run_cli("script", "check", self.manifest)
      self.assertEqual(status, 1)
      self.assertIn("demo.cscript:", out)
      self.assertIn("error", out)

   def test_declare_rename_settings(self) -> None:
      """!declare, rename and settings change the files.
      @return None
      """
      status, out = self.run_cli("script", "declare", self.manifest, "var", "strides", "--range", "0..50")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("script", "rename", self.manifest, "strides", "paces")
      self.assertEqual(status, 0, out)
      text = (self.root / "data" / "demo.cscript").read_text()
      self.assertIn("var paces : u8 permanent 0..50;", text)
      status, out = self.run_cli("script", "settings", self.manifest, "--game", "red")
      self.assertEqual(status, 0, out)
      self.assertIn("game: red", out)
      status, out = self.run_cli("script", "declare", self.manifest, "var", "x", "--range", "bad")
      self.assertNotEqual(status, 0)

   def test_new_and_sources(self) -> None:
      """!new, add-source and remove-source.
      @return None
      """
      m = self.root / "fresh" / "scripts.json"
      status, out = self.run_cli("script", "new", m)
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("script", "add-source", m, "towns/a.cscript")
      self.assertEqual(status, 0, out)
      self.assertTrue((m.parent / "towns" / "a.cscript").is_file())
      status, out = self.run_cli("script", "check", m)
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("script", "remove-source", m, "towns/a.cscript")
      self.assertEqual(status, 0, out)


if __name__ == "__main__":
   unittest.main()
