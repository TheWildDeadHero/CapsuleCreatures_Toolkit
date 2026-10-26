#!/usr/bin/env python3
"""!Tests for the script language's words [S2] (no Qt): core.script_words (the engine's word lists, the route
steps, the statement templates, completions by context), core.scripts' I4 outline (movements, marts, route steps,
map triggers with conditions) and settings (object_base, warn_unused, glitches), and `script words / list /
settings`. The scripts are a small neutral set written by the tests.
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
from capsule_studio.core import script_words, scripts  # noqa: E402

## The statement words engine I4 (D-29) added (later packages add more: DS1's override; their templates come with
## their studio side).
I4_STATEMENTS = ("lock", "release", "wait_msg", "remove", "visible", "set_template", "door", "weather", "fade",
                 "set_metatile", "respawn", "set_warp", "sound", "wait_sound", "mart", "wait_state")
## A source with the I4 declarations and map triggers.
SOURCE = """// I4 statements, declarations and triggers
var mode : u8 map;
const SIGN = 2;
step hop;
movement walk { up; in_place left 3; face original; step hop 2; }
mart shop { 1, 2, 3 }
script talk {
    lock all;
    msg "Hi" nowait;
    wait_msg;
    route SIGN walk nowait;
    wait_moves last;
    door open 1 2;
    door wait;
    fade to_black speed 2 swap;
    sound se 9;
    wait_sound se;
    mart shop;
    release all;
    call resume loose;
}
script resume { var(mode) = 1; }
script arrive { var(mode) += 1; }
map_scripts town {
    on_resume -> resume;
    on_warp_into var(mode) == 0 -> arrive;
}
"""


class ScriptCase(unittest.TestCase):
   """!Base: the neutral scripts in a temporary folder."""

   def setUp(self) -> None:
      """!Writes the manifest and its source.
      @return None
      """
      ## Temporary folder.
      self.tmp = Path(tempfile.mkdtemp(prefix="capsule_i4_scripts_"))
      (self.tmp / "main.cscript").write_text(SOURCE, encoding="utf-8")
      ## The manifest.
      self.manifest = self.tmp / "scripts.json"
      self.manifest.write_text(json.dumps({"schema": "capsule.scripts/1", "sources": ["main.cscript"],
                                           "stack_depth": 4}), encoding="utf-8")

   def tearDown(self) -> None:
      """!Removes the folder.
      @return None
      """
      shutil.rmtree(self.tmp, ignore_errors=True)

   def run_cli(self, *args: object) -> tuple[int, str]:
      """!Runs capsule-studio.
      @param args  arguments
      @return (status, output)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         status = cli([str(a) for a in args])
      return status, out.getvalue() + err.getvalue()


class WordTests(unittest.TestCase):
   """!The words come from the engine's compilers."""

   def test_engine_lists(self) -> None:
      """!Every I4 statement word, kind list, trigger kind and route step is offered.
      @return None
      """
      sc = script_words.compiler()
      self.assertTrue(set(sc.I4_WORDS) <= set(script_words.statement_words()))
      kinds = script_words.statement_kinds()
      for word, export in (("door", "DOOR_KINDS"), ("weather", "WEATHER_KINDS"), ("fade", "FADE_KINDS"),
                           ("set_warp", "SET_WARP_KINDS"), ("wait_sound", "SOUND_WAITS"),
                           ("set_template", "TEMPLATE_KINDS"), ("msgbox", "MSGBOX_KINDS")):
         self.assertTrue(set(getattr(sc, export)) <= set(kinds[word]), word)
      self.assertTrue(set(sc.SOUND_KINDS) <= set(kinds["sound"]))
      self.assertTrue(set(sc.MSG_FLAGS) <= set(kinds["msg"]))
      self.assertIn(sc.LOOSE_WORD, kinds["call"])
      self.assertIn(sc.WARP_NOWAIT_WORD, kinds["warp"])
      self.assertTrue(set(sc.TRANSITIONS) <= set(kinds["warp"]))
      self.assertEqual(script_words.trigger_kinds(), list(sc.TRIGGER_KINDS))
      self.assertEqual(script_words.condition_kinds(), list(sc.CONDITION_KINDS))
      for word in (sc.MOVEMENT_WORD, sc.MART_WORD, sc.STEP_WORD):
         self.assertIn(word, script_words.declaration_words())
      steps = script_words.route_steps().steps
      self.assertEqual(set(steps["in_place"]), set(script_words.route_compiler().DIRECTIONS))
      self.assertIn("original", steps["face"])
      self.assertIn("step", steps)
      self.assertEqual(steps["walk_anim"], ["on", "off"])
      words = set(script_words.keyword_words())
      self.assertTrue({"on_warp_into", "set_metatile", "to_black", "loose", "camera"} <= words)

   def test_templates_compile(self) -> None:
      """!Every I4 statement has a template, and each compiles with the engine's compiler.
      @return None
      """
      sc = script_words.compiler()
      self.assertTrue(set(I4_STATEMENTS) <= set(sc.I4_WORDS))
      self.assertTrue(set(I4_STATEMENTS) <= set(script_words.STATEMENT_TEMPLATES))
      # S3: a template naming the world's data (override sets) compiles in test_d30_formats against the sandbox
      body = "\n".join("    " + t for w, t in script_words.STATEMENT_TEMPLATES.items()
                       if w not in script_words.WORLD_TEMPLATES)
      source = script_words.TEMPLATE_DECLARATIONS + "script templates {\n" + body + "\n}\n"
      comp = sc.Compiler({"schema": "capsule.scripts/1", "sources": ["t.cscript"]}, ".", {"t.cscript": source}).run()
      self.assertEqual([d.message for d in comp.diags if d.severity == "error"], [])

   def test_completions(self) -> None:
      """!What fits where: declarations, statements, kinds, objects, route steps, trigger kinds, names.
      @return None
      """
      names = {"script": ["talk", "resume"], "flag": ["seen"], "var": ["mode"], "movement": ["walk"],
               "mart": ["shop"], "step": ["hop"], "map": ["town"], "const": ["SIGN"]}
      c = script_words.completions
      self.assertIn("movement", c("", names))
      self.assertIn("set_metatile", c("script x {\n  set_", names))
      self.assertEqual(c("script x { door ", names)[:5], ["open", "close", "set_open", "set_closed", "wait"])
      self.assertIn("last", c("script x { wait_moves ", names))
      self.assertIn("walk", c("script x { route 1 ", names))
      self.assertIn("in_place", c("movement m { up; in", names))
      self.assertEqual(c("movement m { step ", names), ["hop"])
      self.assertEqual(c("script x { route 1 { face o", names), ["original"])
      self.assertIn("on_warp_into", c("map_scripts town { ", names))
      self.assertIn("var", c("map_scripts town { on_warp_into ", names))
      self.assertEqual(c("map_scripts town { on_resume -> ", names), ["talk", "resume"])
      self.assertEqual(c("script x { call ", names), ["talk", "resume"])
      self.assertEqual(c("script x { call talk ", names), ["loose"])
      self.assertEqual(c('script x { msg "a;b{" no', names), ["nowait"])   # strings are skipped
      self.assertEqual(c("script x { mart ", names), ["shop"])
      self.assertEqual(c("script x { if flag(", names), ["seen"])
      self.assertEqual(c("/* map_scripts { */ ", names)[:1], ["flag"])   # comments are skipped


class OutlineTests(ScriptCase):
   """!core.scripts with the I4 declarations."""

   def test_outline_and_triggers(self) -> None:
      """!Movements, marts, route steps; a map's entries with their conditions.
      @return None
      """
      r = scripts.ScriptProject.open(self.manifest).check()
      self.assertTrue(r.ok, [d.message for d in r.errors])
      o = r.outline
      self.assertEqual(o.names("movement"), ["walk"])
      self.assertEqual(o.items["movement"][0]["detail"], "4 steps")
      self.assertEqual(o.items["mart"][0]["detail"], "3 items")
      self.assertEqual(o.items["step"][0], {"name": "hop", "file": "main.cscript", "line": 4, "detail": "id 0"})
      self.assertEqual(o.items["map"][0]["detail"],
                       "on_resume -> resume, on_warp_into var(mode) == 0 -> arrive")

   def test_settings(self) -> None:
      """!object_base, warn_unused and glitches are checked and saved.
      @return None
      """
      p = scripts.ScriptProject.open(self.manifest)
      top = scripts.compiler().MAX_OBJECT_BASE
      p.set_setting("object_base", top)
      p.set_setting("warn_unused", False)
      p.set_setting("glitches", {"game.fix": True})
      for key, bad in (("object_base", top + 1), ("warn_unused", 1), ("glitches", {"a": 1}), ("nothing", 1)):
         with self.assertRaises(scripts.ScriptsError):
            p.set_setting(key, bad)
      p.save()
      data = json.loads(self.manifest.read_text(encoding="utf-8"))
      self.assertEqual((data["object_base"], data["warn_unused"], data["glitches"]), (top, False, {"game.fix": True}))

   def test_commands(self) -> None:
      """!script list --kind movement, settings with the I4 options, words.
      @return None
      """
      status, out = self.run_cli("script", "list", self.manifest, "--kind", "step")
      self.assertEqual(status, 0, out)
      self.assertIn("hop", out)
      status, out = self.run_cli("script", "settings", self.manifest, "--warn-unused", "off", "--glitch", "g.x", "on")
      self.assertEqual(status, 0, out)
      self.assertIn("warn_unused: False", out)
      self.assertIn("glitches: g.x on", out)
      status, out = self.run_cli("script", "words")
      self.assertIn("map triggers: on_transition", out)
      self.assertIn("in_place[", out)
      status, out = self.run_cli("script", "words", "--at", "movement m { step ", "--manifest", self.manifest)
      self.assertEqual(out.split(), ["hop"])


if __name__ == "__main__":
   unittest.main()
