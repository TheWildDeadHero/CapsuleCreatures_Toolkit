#!/usr/bin/env python3
"""!Tests for the step effects in the studio (D-27 section 4, engine F3): core.structure.step_effects (the
structure's step_effects: rows, edits, defaults, a rename following the logic and the game's scripts, a refused
removal, the logic running `on steps` in the engine's order, the choices), the effect logic's name lists and palette,
the encounter rules keeping to the encounter hooks, test saves' step counters (checked, shown, exported into the
script banks) and the `battle FILE step-effect ...` / `testsave step` commands. No Qt.

Uses the map sandbox as one game (sample_data.make_field_game: sandbox_map's data with the Starter inside the game):
the Starter's blight (every 4 steps, the survive rule, the message blight_survived) and bond (every 64) effects,
Blight's `on steps` and the global bond_rule, the sandbox's scripts (the effects' implicit counters). The classic class
runs on the reference repo's sample (skipped without it).
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine, inventory, logic  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import encounter_rules, step_effects  # noqa: E402
from sample_data import DATA, classic_data, make_field_game, needs_classic  # noqa: E402

## The Starter's step effects, in order (B2: the grove's check and the egg cycle after the F3 ones).
NAMES = ["blight", "bond", "grove_check", "egg_cycle"]
## Their steps between two runs.
EVERY = {"blight": 4, "bond": 64, "grove_check": 128, "egg_cycle": 256}
## The sandbox's scripts source (relative to the game's data folder).
SANDBOX_SCRIPTS = ("scripts", "sandbox.cscript")
## A script reading the blight's counter (added for the rename test).
COUNTER_SCRIPT = "\nvar seen : u16;\nscript blight_test { var(seen) = var(step_effect_blight); }\n"


def run_cli(*argv: str) -> tuple[int, str]:
   """!Runs the CLI.
   @param argv  arguments
   @return (exit status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      try:
         code = cli(list(argv))
      except SystemExit as e:
         code = int(e.code or 0)
   return code, out.getvalue() + err.getvalue()


class StepGameCase(unittest.TestCase):
   """!Base: a copy of the map sandbox as one game per test.

   @var dir
   The game folder.
   @var battle_json
   Its battle.json (the Starter).
   @var project
   The opened BattleProject.
   """

   def setUp(self) -> None:
      """!Copies the game and opens its battle data.
      @return None
      """
      self.dir = Path(tempfile.mkdtemp(prefix="capsule_f3_"))
      self.battle_json = make_field_game(self.dir)
      self.project = BattleProject.open(self.battle_json)

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.dir, ignore_errors=True)


class StepEffectTests(StepGameCase):
   """!The structure's step effects."""

   def test_rows_and_lists(self) -> None:
      """!The Starter's effects with their counters and users; the choice lists are the engine's.
      @return None
      """
      bc = engine.tool("battle_compiler")
      doc = self.project.structure
      self.assertEqual(step_effects.damage_rules(), list(bc.STEP_EFFECT_DAMAGE_RULES))
      self.assertEqual(step_effects.moments(), list(bc.STEP_EFFECT_MOMENTS))
      self.assertEqual(step_effects.max_effects(), bc.MAX_STEP_EFFECTS)
      self.assertEqual(step_effects.max_every(), bc.STEP_EFFECT_MAX_EVERY)
      blight, bond = step_effects.effect_rows(doc)[:2]
      self.assertEqual([blight["name"], bond["name"]], NAMES[:2])
      self.assertEqual((blight["every"], blight["damage"], blight["messages"]),
                       (4, "survive", {"survived": "blight_survived"}))
      self.assertEqual((bond["every"], bond["damage"], bond["script"]), (64, step_effects.default_damage(), ""))
      self.assertEqual(blight["var"], bc.step_effect_var("blight"))
      self.assertEqual(len(blight["users"]), 1)   # status Blight
      self.assertEqual(len(bond["users"]), 1)     # the global bond_rule
      self.assertEqual(logic.name_lists(self.project)["step_effects"], NAMES)
      self.assertIn("blight_survived", step_effects.message_choices(doc))
      scripts = step_effects.script_choices(doc)
      self.assertIn("field_wade", scripts)
      self.assertFalse(any(s.startswith("field_effect_end_") for s in scripts))   # implicit scripts are no choices
      self.assertIsNone(step_effects.compile_check(doc)[1])

   def test_handlers_and_hooks(self) -> None:
      """!The logic running on steps (the global rule first); the encounter rules keep to the encounter hooks.
      @return None
      """
      uses = step_effects.step_handlers(self.project)
      self.assertEqual([(u.kind, u.name) for u in uses], [(logic.global_kind(), "bond_rule"), ("status", "Blight")])
      self.assertEqual(encounter_rules.hooks(), ["encounter", "encounter_made"])
      self.assertNotIn("bond_rule", [u.name for u in encounter_rules.encounter_handlers(self.project)])
      # the Logic catalog offers the hook to statuses, passives, items and global rules (not to moves)
      for kind in ("status", "passive", "item", logic.global_kind()):
         self.assertIn("steps", [h["name"] for h in logic.hook_catalog(kind)], kind)
      self.assertNotIn("steps", [h["name"] for h in logic.hook_catalog("move")])
      steps = next(h for h in logic.hook_catalog() if h["name"] == "steps")
      self.assertEqual(sorted(steps["owners"]), sorted(["global", "item", "passive", "status"]))
      entries = {label: text for group, label, text in logic.statement_templates(self.project) if group == "Field"}
      self.assertEqual(entries["step effect runs"], "if field.step_effect == blight {}")
      logic.parse_statement(entries["step effect runs"])

   def test_edit_rename_remove(self) -> None:
      """!Add, set every key (defaults drop the key), messages, a script, rename following the logic and the
      game's scripts, a removal refused while named, an unnamed one removed.
      @return None
      """
      doc = self.project.structure
      with doc.edit("add"):
         step_effects.add_effect(doc, "hatch", 3)
      self.assertEqual(step_effects.effect_names(doc), NAMES + ["hatch"])
      with doc.edit("set"):
         step_effects.set_label(doc, "hatch", "Egg")
         step_effects.set_every(doc, "hatch", 5)
         step_effects.set_damage(doc, "hatch", "survive")
         step_effects.set_message(doc, "hatch", "fainted", "blight_survived")
         step_effects.set_message(doc, "hatch", "hurt", "blight_survived")
         step_effects.set_script(doc, "hatch", "field_wade")
      rec = step_effects.effects(doc)[len(NAMES)]
      self.assertEqual(rec, {"name": "hatch", "every": 5, "label": "Egg", "damage": "survive",
                             "messages": {"hurt": "blight_survived", "fainted": "blight_survived"},
                             "script": "field_wade"})
      with doc.edit("defaults"):
         step_effects.set_damage(doc, "hatch", step_effects.default_damage())
         step_effects.set_message(doc, "hatch", "hurt", None)
         step_effects.set_message(doc, "hatch", "fainted", "")
         step_effects.set_script(doc, "hatch", "")
         step_effects.set_label(doc, "hatch", "")
      self.assertEqual(step_effects.effects(doc)[len(NAMES)], {"name": "hatch", "every": 5})
      for bad in (lambda: step_effects.set_every(doc, "hatch", 0),
                  lambda: step_effects.set_every(doc, "hatch", step_effects.max_every() + 1),
                  lambda: step_effects.set_damage(doc, "hatch", "explode"),
                  lambda: step_effects.set_message(doc, "hatch", "later", "blight_survived"),
                  lambda: step_effects.set_message(doc, "hatch", "hurt", "no_such_message"),
                  lambda: step_effects.add_effect(doc, "bond"),
                  lambda: step_effects.add_effect(doc, "Upper")):
         with self.assertRaises(DocumentError):
            with doc.edit("bad"):
               bad()
      with self.assertRaises(DocumentError):
         step_effects.remove_effect(doc, "blight")   # status Blight names it
      with doc.edit("remove"):
         step_effects.remove_effect(doc, "hatch")
      self.assertEqual(step_effects.effect_names(doc), NAMES)
      # a rename: the logic and a script reading the counter follow
      src = self.dir.joinpath(DATA, *SANDBOX_SCRIPTS)
      src.write_text(src.read_text(encoding="utf-8") + COUNTER_SCRIPT, encoding="utf-8")
      with doc.edit("rename"):
         places = step_effects.rename_effect(doc, "blight", "sting")
      self.assertTrue(any(p.startswith("scripts: ") for p in places))
      self.assertIn("var(step_effect_sting)", src.read_text(encoding="utf-8"))
      self.assertIn("field.step_effect == sting", self.project.effect_source("effects/conditions.ceffect").text)
      self.assertIsNone(self.project.error_now())
      with doc.edit("move"):
         step_effects.move_effect(doc, "bond", -1)
      self.assertEqual(step_effects.effect_names(doc), ["bond", "sting", *NAMES[2:]])
      self.assertTrue(step_effects.lines(doc)[0].startswith("bond (Bond): every 64 steps"))


class TestSaveCounterTests(StepGameCase):
   """!A test save's step counters."""

   def test_counters(self) -> None:
      """!Set (in range, 0 drops the entry), shown, checked, exported into the script banks.
      @return None
      """
      save = inventory.new_testsave(self.project, "walk")
      doc = self.project.battle
      self.assertEqual(step_effects.counter_rows(save, doc), [(n, 0, EVERY[n]) for n in NAMES])
      with save.edit("count"):
         step_effects.set_counter(save, doc, "blight", 3)
         step_effects.set_counter(save, doc, "bond", 40)
      self.assertEqual(step_effects.counters_of(save), {"blight": 3, "bond": 40})
      for bad in (lambda: step_effects.set_counter(save, doc, "blight", 4),
                  lambda: step_effects.set_counter(save, doc, "blight", -1),
                  lambda: step_effects.set_counter(save, doc, "nothing", 1)):
         with self.assertRaises(DocumentError):
            bad()
      self.assertIn("step blight: 3 of 4 steps", inventory.lines(save, doc))
      self.assertEqual(inventory.check(save, doc), [])
      bc = engine.tool("battle_compiler")
      self.assertEqual(step_effects.counter_values(save), {bc.step_effect_var("blight"): 3,
                                                           bc.step_effect_var("bond"): 40})
      with_counts = inventory.image_of(save, self.project)
      with save.edit("zero"):
         step_effects.set_counter(save, doc, "blight", 0)
         step_effects.set_counter(save, doc, "bond", 0)
      self.assertNotIn("step_counters", save.data)
      plain = inventory.image_of(save, self.project)
      self.assertEqual(len(plain), len(with_counts))
      self.assertNotEqual(plain, with_counts)
      # a counter the battle data no longer has is a problem
      save.data["step_counters"] = {"gone": 1}
      self.assertTrue(any("gone" in p for p in inventory.check(save, doc)))


class CliTests(StepGameCase):
   """!`battle FILE step-effect ...` and `testsave step`."""

   def test_commands(self) -> None:
      """!list / add / set / message / rename / move / handlers / remove; testsave step.
      @return None
      """
      b = str(self.battle_json)
      code, out = run_cli("battle", b, "step-effect", "list")
      self.assertEqual(code, 0, out)
      self.assertIn("blight (Blight): every 4 steps, survive", out)
      for argv in (("add", "hatch", "--every", "3"), ("set", "hatch", "damage", "survive"),
                   ("message", "hatch", "survived", "blight_survived"), ("set", "hatch", "label", "Egg"),
                   ("move", "hatch", "up"), ("rename", "hatch", "egg")):
         code, out = run_cli("battle", b, "step-effect", *argv)
         self.assertEqual(code, 0, (argv, out))
      self.assertEqual(step_effects.effect_names(BattleProject.open(self.battle_json).structure),
                       [*NAMES[:-1], "egg", NAMES[-1]])
      code, out = run_cli("battle", b, "step-effect", "handlers")
      self.assertEqual(code, 0, out)
      self.assertIn("on steps: global bond_rule", out)
      code, out = run_cli("battle", b, "step-effect", "remove", "blight")
      self.assertNotEqual(code, 0)
      code, out = run_cli("battle", b, "step-effect", "remove", "egg")
      self.assertEqual(code, 0, out)
      code, out = run_cli("battle", b, "testsave", "new", "walk")
      self.assertEqual(code, 0, out)
      code, out = run_cli("battle", b, "testsave", "step", "walk", "bond", "12")
      self.assertEqual(code, 0, out)
      self.assertIn("step bond: 12 of 64 steps", out)
      code, out = run_cli("battle", b, "testsave", "step", "walk", "bond", "64")
      self.assertNotEqual(code, 0)


@needs_classic
class ClassicStepTests(unittest.TestCase):
   """!The reference repo's classic sample (read only)."""

   def test_classic(self) -> None:
      """!field_poison every 4 with the faint rule and its message; friendship_walk every 128; their logic.
      @return None
      """
      data = classic_data()
      assert data is not None
      p = BattleProject.open(data / "battle.json")
      rows = {r["name"]: r for r in step_effects.effect_rows(p.structure)}
      self.assertEqual((rows["field_poison"]["every"], rows["field_poison"]["damage"]), (4, "faint"))
      self.assertEqual(rows["field_poison"]["messages"], {"fainted": "field_poison_fainted"})
      self.assertEqual(rows["friendship_walk"]["every"], 128)
      kinds = [(u.kind, u.name) for u in step_effects.step_handlers(p)]
      self.assertEqual(kinds[0], (logic.global_kind(), "friendship_walk"))
      self.assertIn(("status", "Poison"), kinds)
      self.assertIn(("status", "Toxin"), kinds)


if __name__ == "__main__":
   unittest.main()
