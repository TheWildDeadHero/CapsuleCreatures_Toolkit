#!/usr/bin/env python3
"""!field options without Qt: text table languages in one manifest (core.asset_tables: the build language and its
fallback checked by the engine's select_language(), missing translations, the fallback's share; core.text_tables
set_language(); the `manifest languages|language|fallback` and `text-table language` commands; the fit report in a
chosen language), coord triggers that run immediately (core.events: the run field, the refusal of a script that may
wait, `events set --run`), the script language's field options words and settings (core.scripts lifetimes() with
session, the vm switches checked by the engine, var_wraps(), `script settings --vm`, core.script_words face / lifetime
words) and door sounds checked against the game's sounds (core.doors.sound_problems()).

Uses copies of the field options fixture (tests/data/field_options: a manifest of en and fr tables, a world with an
immediate trigger, a scripts manifest with the vm switches and session declarations; its tileset comes from
tests/data/doors_overrides) and of the doors and overrides fixture's door (sounds sound:DOOR_OPEN / sound:DOOR_SHUT).
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
from capsule_studio.core import (asset_tables, doors, engine, events, script_words, scripts,  # noqa: E402
                                 text_tables)
from capsule_studio.core.document import Document, DocumentError  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402

## The fixture's map with the triggers, and the index of its immediate one.
PLAIN, IMMEDIATE = "plain", 0
## A script of the fixture that waits (`delay 2`).
WAITING_SCRIPT = "pauses"
## The fixture's languages and the key only English has.
LANGUAGES, ONLY_EN = ["en", "fr"], "text:FIELD_OPTIONS.ONLY_EN"
## The doors and overrides fixture's door and its sounds.
GATE, DOOR_SOUNDS = "door:GATE", ("sound:DOOR_OPEN", "sound:DOOR_SHUT")


class C10Copy(unittest.TestCase):
   """!Base: a copy of the field options and doors and overrides fixtures per test."""

   def setUp(self) -> None:
      """!Copies tests/data/field_options and tests/data/doors_overrides side by side.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_s4_"))
      data = engine.root() / "tests" / "data"
      for name in ("field_options", "doors_overrides"):
         shutil.copytree(data / name, self.root / name)
      ## The field options fixture's folder.
      self.field_options = self.root / "field_options"
      ## Its asset manifest.
      self.assets = self.field_options / "assets.json"
      ## Its scripts manifest.
      self.scripts = self.field_options / "scripts" / "scripts.json"

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


class LanguageTests(C10Copy):
   """!Text tables of several languages in one manifest."""

   def test_languages_and_the_engine_rule(self) -> None:
      """!The manifest's languages, the build language, the engine's refusals, the fallback's share.
      @return None
      """
      doc = Document.open(self.assets)
      self.assertEqual(asset_tables.languages(doc), LANGUAGES)
      self.assertEqual(asset_tables.build_language(doc), "en")
      self.assertIsNone(asset_tables.language_problem(doc))
      self.assertIsNone(asset_tables.language_problem(doc, "fr"))
      self.assertIn("no text table is in language 'de'", asset_tables.language_problem(doc, "de"))
      with self.assertRaises(DocumentError):
         with doc.edit("t"):
            asset_tables.set_language(doc, "fallback_language", "de")   # no table has it
      with doc.edit("t"):
         asset_tables.set_language(doc, "language", None)
      self.assertIn("several languages", asset_tables.language_problem(doc))   # ambiguous
      with doc.edit("t"):
         asset_tables.set_language(doc, "language", "fr")
      self.assertEqual(asset_tables.build_language(doc), "fr")
      docs = {r.path: text_tables.open_table(r.path) for r in asset_tables.tables(doc)}
      self.assertEqual(asset_tables.missing_translations(docs), {"fr": [ONLY_EN]})
      self.assertEqual(asset_tables.fallback_keys(docs, "fr", "en"), [ONLY_EN])
      ctx = text_tables.TextContext.for_manifest(self.assets)
      fit_fr = asset_tables.fit_report(doc, ctx.page, None)   # fr with the en fallback: every key
      fit_en = asset_tables.fit_report(doc, ctx.page, None, "en")
      self.assertEqual(fit_fr["assets"], fit_en["assets"])

   def test_table_language_and_every_language(self) -> None:
      """!A table without a language is in every language: its keys are missing from none.
      @return None
      """
      fr = text_tables.open_table(self.field_options / "text" / "fr.json")
      with fr.edit("t"):
         text_tables.set_language(fr, None)
      self.assertNotIn("language", fr.data)
      with self.assertRaises(DocumentError):
         with fr.edit("t"):
            text_tables.set_language(fr, "no spaces")
      fr.save()
      doc = Document.open(self.assets)
      self.assertEqual(asset_tables.languages(doc), ["en"])
      docs = {r.path: text_tables.open_table(r.path) for r in asset_tables.tables(doc)}
      self.assertEqual(asset_tables.missing_translations(docs), {})

   def test_language_commands(self) -> None:
      """!`manifest languages|language|fallback`, `text-table language`, `manifest check --language`.
      @return None
      """
      status, out = self.run_cli("manifest", "languages", self.assets)
      self.assertEqual(status, 0, out)
      self.assertIn("languages: en, fr", out)
      self.assertIn("fr: 1 keys missing", out)
      self.assertEqual(self.run_cli("manifest", "language", self.assets, "fr")[0], 0)
      self.assertEqual(json.loads(self.assets.read_text(encoding="utf-8"))["language"], "fr")
      self.assertEqual(self.run_cli("manifest", "fallback", self.assets, "-")[0], 0)
      self.assertNotIn("fallback_language", json.loads(self.assets.read_text(encoding="utf-8")))
      status, out = self.run_cli("manifest", "fallback", self.assets, "de")
      self.assertEqual(status, 1, out)
      status, out = self.run_cli("manifest", "languages", self.assets, "--language", "de")
      self.assertEqual(status, 1, out)
      status, out = self.run_cli("manifest", "check", self.assets, "--language", "en")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("text-table", "language", self.field_options / "text" / "fr.json", "-")
      self.assertIn("language -", out)


class TriggerTests(C10Copy):
   """!Coord triggers that run immediately."""

   def test_immediate_trigger(self) -> None:
      """!The fixture's immediate trigger reads back; a waiting script is refused with a way out; the default run is
      not written.
      @return None
      """
      p = Project.open(self.field_options / "world.json")
      self.assertEqual(events.trigger_runs(), ["step", "immediate"])
      doc = p.map(PLAIN)
      e = events.events(doc, "triggers")[IMMEDIATE]
      self.assertEqual(e["run"], "immediate")
      self.assertIn("runs at once", events.describe("triggers", e))
      names = events.names(p)
      self.assertIn(WAITING_SCRIPT, names["waiting"])
      self.assertIsNone(events.immediate_problem(e, names["waiting"]))
      self.assertIsNone(events.check(p))
      with doc.edit("t"):
         events.set_event(doc, "triggers", IMMEDIATE, script=WAITING_SCRIPT)
      self.assertIn("may wait", events.immediate_problem(events.events(doc, "triggers")[IMMEDIATE], names["waiting"]))
      found = [d for d in events.diagnostics(p, PLAIN) if d.level == "error"]
      self.assertTrue(any("run it on step" in d.message for d in found), found)
      self.assertTrue(any("'plain' trigger 0" in d.message and "may wait" in d.message for d in found), found)
      with doc.edit("t"):
         events.set_event(doc, "triggers", IMMEDIATE, run="step")
      self.assertNotIn("run", events.events(doc, "triggers")[IMMEDIATE])
      with self.assertRaises(DocumentError):
         with doc.edit("t"):
            events.set_event(doc, "triggers", IMMEDIATE, run="later")

   def test_run_command(self) -> None:
      """!`events set MAP trigger N --run immediate|step`.
      @return None
      """
      world = self.field_options / "world.json"
      status, out = self.run_cli("events", "set", world, PLAIN, "trigger", "1", "--run", "immediate")
      self.assertEqual(status, 0, out)
      saved = json.loads((self.field_options / "maps" / "plain.json").read_text(encoding="utf-8"))
      self.assertEqual(saved["events"]["triggers"][1]["run"], "immediate")
      status, out = self.run_cli("events", "show", world, "--map", PLAIN)
      self.assertIn("runs at once", out)


class ScriptTests(C10Copy):
   """!The script language's field options words and settings."""

   def test_settings_lifetimes_and_wrap(self) -> None:
      """!session lifetime, the vm switches (checked by the engine), which variables wrap.
      @return None
      """
      self.assertIn("session", scripts.lifetimes())
      options = scripts.vm_options()
      self.assertEqual(options["resume"][0], "same_frame")   # the engine's own behaviour first
      self.assertEqual(set(options), {"resume", "random", "vars"})
      p = scripts.ScriptProject.open(self.scripts)
      self.assertEqual(p.setting("vm"), {"resume": "next_frame", "random": "modulo", "vars": "wrap"})
      with self.assertRaises(scripts.ScriptsError):
         p.set_setting("vm", {"resume": "later"})
      p.set_setting("vm", {})
      self.assertIsNone(p.setting("vm"))
      vm = {"vars": "wrap"}
      self.assertTrue(scripts.var_wraps("u16", 0, 0xFFFF, vm))
      self.assertFalse(scripts.var_wraps("u8", 0, 9, vm))   # a narrow range saturates
      self.assertFalse(scripts.var_wraps("u16", 0, 0xFFFF, None))
      self.assertFalse(scripts.var_wraps("u32", 0, 0xFFFF, vm))
      line = scripts.ScriptProject.open(self.scripts).declare("field_options.cscript", "flag", "seen_once", "session")
      self.assertEqual(line, "flag seen_once : session;")

   def test_words_and_commands(self) -> None:
      """!face words and lifetimes in completion; `script settings --vm`; the face template compiles.
      @return None
      """
      self.assertIn("opposite_player", script_words.completions("script s { face selected "))
      self.assertIn("selected", script_words.completions("script s { face sel"))
      self.assertIn("session", script_words.completions("flag f : "))
      self.assertIn("session", script_words.completions("var v : u16 "))
      self.assertIn("opposite_player", script_words.keyword_words())
      status, out = self.run_cli("script", "settings", self.scripts, "--vm", "resume", "same_frame",
                                 "--vm", "random", "scaled")
      self.assertEqual(status, 0, out)
      self.assertEqual(json.loads(self.scripts.read_text(encoding="utf-8"))["vm"], {"vars": "wrap"})
      self.assertIn("vm: vars wrap", out)
      status, out = self.run_cli("script", "settings", self.scripts, "--vm", "vars", "fast")
      self.assertEqual(status, 1, out)
      status, out = self.run_cli("script", "declare", self.scripts, "var", "ticks", "--lifetime", "session",
                                 "--type", "u16")
      self.assertEqual(status, 0, out)


class DoorSoundTests(C10Copy):
   """!Door sounds checked against the game's sounds."""

   def test_door_sounds(self) -> None:
      """!The doors and overrides door's sounds name no sound until the game's scripts declare them; a malformed key is
      said.
      @return None
      """
      doc = Document.open(self.root / "doors_overrides" / "assets.json")
      gate = doc.get(GATE)
      found = doors.sound_problems(doc, gate)
      self.assertEqual(len(found), len(DOOR_SOUNDS), found)
      self.assertTrue(all("no such sound" in p for p in found))
      source = next((self.root / "doors_overrides" / "scripts").glob("*.cscript"))
      names = [s.split(":")[1] for s in DOOR_SOUNDS]
      source.write_text(source.read_text(encoding="utf-8") + "".join(f"\nconst {n} = {i};" for i, n in
                                                                    enumerate(names, 1)) + "\n", encoding="utf-8")
      self.assertEqual(doors.sound_problems(doc, gate), [])
      self.assertIn("is no sound key", doors.sound_problems(doc, dict(gate, sounds={"open": "DOOR_OPEN"}))[0])
      again = Document.open(self.root / "doors_overrides" / "assets.json")
      self.assertFalse(any("no such sound" in line for line in doors.lines(again, GATE)))


if __name__ == "__main__":
   unittest.main()
