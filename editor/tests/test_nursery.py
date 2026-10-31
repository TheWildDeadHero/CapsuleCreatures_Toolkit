#!/usr/bin/env python3
"""!Tests for eggs and the nursery in the studio (D-28 sections 2 and 3, engine B2): core.structure.nursery (the
structure's eggs and nursery, the choices, the editing calls, the refusal flags of the systems that use records,
the renames that follow into the sections and the removals refused while they name something), the test saves'
nursery slots, waiting result and boxed eggs (checked and exported into the Nursery section) and the
`battle FILE nursery ...` / `testsave nursery|nursery-result|egg` commands. No Qt.

Uses the map sandbox as one game (sample_data.make_field_game): the Starter's Grove (structure nursery: two slots,
the method grove of kind nursery checked by grove_check, delivering eggs), its eggs (roles egg / hatch_counter, the
species field hatch_cycles, the step effect egg_cycle, the sandbox's hatch_egg script).
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
from capsule_studio.core import battle, engine, inventory  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import (combination, field_expressions, nursery, record,  # noqa: E402
                                           species_fields, step_effects, storage)
from sample_data import make_field_game  # noqa: E402

## The Starter's egg section.
EGGS = {"role": "egg", "counter": "hatch_counter", "cycles_field": "hatch_cycles", "step_effect": "egg_cycle",
        "hatch_script": "hatch_egg"}
## The Starter's nursery method and check.
GROVE, CHECK = "grove", "grove_check"
## Its slots.
SLOTS = 2
## Steps of one egg cycle of the Grove, and Sproutle's hatch cycles (the field's default).
CYCLE, SPROUTLE_CYCLES = 256, 5
## Species the tests use.
SPROUTLE, BREEZLE = "Sproutle", "Breezle"
## A hatch counter the tests give eggs.
STEPS = 600
## Largest counter the Starter's hatch_counter role holds (11 bits).
COUNTER_MAX = 2047
## A test save's name.
SAVE = "grove"
## The egg table's flag of battle setup taking eggs (tools/battlec/nursery.py EGG_FLAG_BATTLE).
BATTLE_FLAG = 1


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


class NurseryCase(unittest.TestCase):
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
      self.dir = Path(tempfile.mkdtemp(prefix="capsule_b2_"))
      self.battle_json = make_field_game(self.dir)
      self.project = BattleProject.open(self.battle_json)

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.dir, ignore_errors=True)

   def compiles(self) -> None:
      """!Asserts the battle data compiles.
      @return None
      """
      compiled, error = self.project.compile()
      self.assertIsNotNone(compiled, error)


class NurseryReadTests(NurseryCase):
   """!Reading the sections and the choices."""

   def test_rows_and_choices(self) -> None:
      """!The Starter's eggs and Grove as the page shows them; the choice lists; a species' egg values.
      @return None
      """
      doc = self.project.structure
      row = nursery.egg_row(doc)
      self.assertEqual({k: row[k] for k in EGGS}, EGGS)
      self.assertEqual(row["name"], nursery.default_name())
      n = nursery.nursery_row(doc)
      self.assertEqual((n["slots"], n["method"], n["check"], n["gain"], n["fee"]), (SLOTS, GROVE, CHECK, False, False))
      self.assertEqual(n["odds_scale"], nursery.default_odds_scale())
      self.assertIn("egg", nursery.role_choices(doc))
      self.assertNotIn("stat_genes", nursery.role_choices(doc))   # an engine role: not a choice
      self.assertIn("hatch_cycles", nursery.field_choices(doc))
      self.assertEqual(nursery.method_choices(doc), [GROVE])
      self.assertEqual(nursery.egg_methods(doc), [(GROVE, CYCLE)])
      self.assertEqual(nursery.counter_max(doc), COUNTER_MAX)
      eggs = nursery.species_eggs(doc, SPROUTLE)
      self.assertEqual((eggs["cycles"], eggs["steps"]), (SPROUTLE_CYCLES, [(GROVE, SPROUTLE_CYCLES * CYCLE)]))
      self.assertEqual(nursery.member_var(), "egg_member")
      self.assertGreaterEqual(nursery.max_slots(), SLOTS)
      systems = {(what, name) for what, name, _on in nursery.refusal_rows(doc)}
      self.assertIn(("battle setup", ""), systems)
      self.assertIn(("combination method", GROVE), systems)
      self.assertTrue(all(not on for _w, _n, on in nursery.refusal_rows(doc)))   # every system refuses eggs
      self.assertTrue(any(line.startswith("nursery: slots 2, method grove") for line in nursery.lines(doc)))


class NurseryEditTests(NurseryCase):
   """!The editing calls, the refusals and the renames that follow."""

   def test_edits_and_flags(self) -> None:
      """!Egg keys, nursery keys and the refusal flags; defaults leave the manifest; bad values are refused.
      @return None
      """
      doc = self.project.structure
      with doc.edit("Eggs"):
         nursery.set_egg(doc, "name", "Seed")
         nursery.set_egg(doc, "sprite_field", "kin")
         nursery.set_nursery(doc, "gain", True)
         nursery.set_nursery(doc, "fee", True)
         nursery.set_nursery(doc, "odds_scale", 1000)
      self.assertEqual(nursery.eggs(doc)["name"], "Seed")
      self.assertEqual(nursery.nursery(doc)["odds_scale"], 1000)
      self.compiles()
      self.assertEqual(nursery.fee_table(doc, 2, 7, 2), 0)   # the Starter's ruleset has no nursery_fee: free
      with doc.edit("Back"):
         nursery.set_egg(doc, "name", nursery.default_name())
         nursery.set_nursery(doc, "odds_scale", nursery.default_odds_scale())
         nursery.set_nursery(doc, "gain", False)
      self.assertNotIn("name", nursery.eggs(doc))
      self.assertNotIn("gain", nursery.nursery(doc))
      for bad in (lambda: nursery.set_egg(doc, "role", "no_role"), lambda: nursery.set_egg(doc, "role", None),
                  lambda: nursery.set_egg(doc, "name", "X" * (nursery.max_name_chars() + 1)),
                  lambda: nursery.set_nursery(doc, "method", "merge_altar"),
                  lambda: nursery.set_nursery(doc, "slots", 1),   # fewer than the Grove's inputs: the engine
                  lambda: nursery.set_egg(doc, "counter", "egg"),   # the same role twice: the engine
                  lambda: nursery.disable_eggs(doc),   # the Grove delivers eggs
                  lambda: nursery.disable_nursery(doc)):   # the Grove is a nursery method: the engine
         with self.assertRaises(DocumentError):
            with doc.edit("bad"):
               bad()
      with doc.edit("Flags"):
         nursery.set_refusal(doc, "rules", "", True)
         nursery.set_refusal(doc, "items", "Orb", True)
         nursery.set_refusal(doc, "field_actions", "wade", True)
         nursery.set_refusal(doc, "combine_methods", "merge_altar", True)
      self.assertTrue(nursery.allowed(doc, "rules"))
      self.assertTrue(battle.entry(self.project.battle, "items", "Orb")["allow_eggs"])
      self.assertTrue(inventory.fields_of(self.project.battle, "Orb")[inventory.EGGS_KEY])
      self.compiles()
      compiled = self.project.compile()[0]
      self.assertEqual(compiled["combine"]["eggs"]["flags"], BATTLE_FLAG)   # rules.allow_eggs; recruit refuses
      with doc.edit("Off"):
         nursery.set_refusal(doc, "items", "Orb", False)
      self.assertNotIn("allow_eggs", battle.entry(self.project.battle, "items", "Orb"))
      with self.assertRaises(DocumentError):
         nursery.set_refusal(doc, "items", "No Such Item", True)

   def test_c9_flags_and_transfer(self) -> None:
      """!C9: the lead rules', transformations' and step effects' egg flags (rows, edits, the compiled bits) and the
      transfer rule for eggs.
      @return None
      """
      doc = self.project.structure
      systems = {(what, name) for what, name, _on in nursery.refusal_rows(doc)}
      self.assertIn(("encounter lead", ""), systems)
      self.assertIn(("step effect", "bond"), systems)
      self.assertEqual(nursery.transfer_eggs(doc), "refuse")
      with doc.edit("Flags"):
         nursery.set_refusal(doc, "lead", "", True)
         nursery.set_refusal(doc, "step_effects", "bond", True)
         nursery.set_transfer_eggs(doc, "hatch")
      self.assertTrue(nursery.allowed(doc, "lead") and nursery.allowed(doc, "step_effects", "bond"))
      self.assertEqual(doc.data["transfer_eggs"], "hatch")
      self.compiles()
      eggs = self.project.compile()[0]["combine"]["eggs"]
      bc = engine.tool("battle_compiler")
      self.assertEqual(eggs["flags"], bc.EGG_FLAG_LEAD | bc.EGG_FLAG_TRANSFER_HATCH)
      self.assertNotEqual(eggs["step_effects"], 0)
      self.assertIn("transferred eggs: hatch", nursery.lines(doc))
      with doc.edit("Back"):
         nursery.set_transfer_eggs(doc, "refuse")
      self.assertNotIn("transfer_eggs", doc.data)
      with self.assertRaises(DocumentError):
         nursery.set_transfer_eggs(doc, "keep")
      b = ["battle", str(self.battle_json)]
      self.project.save_all()
      code, out = run_cli(*b, "nursery", "transfer", "hatch")
      self.assertEqual(code, 0, out)
      code, out = run_cli(*b, "nursery", "allow", "step_effects", "blight", "on")
      self.assertEqual(code, 0, out)
      code, out = run_cli(*b, "nursery", "show")
      self.assertIn("transferred eggs: hatch", out)
      self.assertIn("step effect blight takes eggs", out)

   def test_removals_refused_and_renames_follow(self) -> None:
      """!The roles, the species field, the step effects and the method the sections name are not removed; their
      renames follow into the sections (and the hatch script's).
      @return None
      """
      doc = self.project.structure
      for bad in (lambda: step_effects.remove_effect(doc, "egg_cycle"),
                  lambda: step_effects.remove_effect(doc, CHECK),
                  lambda: record.remove_role(doc, "egg"),
                  lambda: species_fields.remove_field(doc, "hatch_cycles"),
                  lambda: combination.remove_method(doc, GROVE)):
         with self.assertRaises(DocumentError):
            with doc.edit("remove"):
               bad()
      with doc.edit("Rename"):
         places = step_effects.rename_effect(doc, "egg_cycle", "warmth", follow=False)
         record.rename_role(doc, "hatch_counter", "steps_left")
         species_fields.rename_field(doc, "hatch_cycles", "cycles")
         method_places = combination.rename_method(doc, GROVE, "garden", follow=False)
      self.assertIn("structure: eggs.step_effect", places)
      self.assertIn("structure: nursery.method", method_places)
      e, n = nursery.eggs(doc), nursery.nursery(doc)
      self.assertEqual((e["step_effect"], e["counter"], e["cycles_field"], n["method"]),
                       ("warmth", "steps_left", "cycles", "garden"))
      found = field_expressions.follow_script(battle.merged(doc), "hatch_egg", "hatch_seed")
      self.assertIn("eggs.hatch_script", found)
      self.assertEqual(nursery.eggs(doc)["hatch_script"], "hatch_seed")
      self.assertEqual(nursery.uses(doc, "step_effect", CHECK), ["nursery.check"])


class TestSaveTests(NurseryCase):
   """!A test save's nursery, waiting result and boxed eggs."""

   def test_slots_result_eggs_and_export(self) -> None:
      """!Leave / take back, a waiting egg, a boxed egg; checked; the export holds the Nursery section the engine's
      nursery_payload() makes.
      @return None
      """
      p = self.project
      doc = p.battle
      save = inventory.new_testsave(p, SAVE)
      with save.edit("Grove"):
         nursery.put_held(save, doc, 0, BREEZLE, 9, 120)
         nursery.put_held(save, doc, 1, SPROUTLE)
         nursery.set_result(save, doc, SPROUTLE, STEPS)
         storage.put_creature(save, doc, SPROUTLE)
         nursery.set_boxed_hatch(save, doc, 0, STEPS)
      self.assertEqual(inventory.check(save, doc), [])
      self.assertIn(f"nursery slot 0: {BREEZLE} level 9, gained 120", inventory.lines(save, doc))
      self.assertIn(f"nursery result: {SPROUTLE} level 1 (egg, {STEPS} steps)", inventory.lines(save, doc))
      self.assertTrue(any(f"(egg, {STEPS} steps)" in line for line in storage.boxed_lines(save, doc)))
      for bad in (lambda: nursery.put_held(save, doc, SLOTS, BREEZLE),
                  lambda: nursery.put_held(save, doc, 0, "Nobody"),
                  lambda: nursery.set_result(save, doc, SPROUTLE, COUNTER_MAX + 1),
                  lambda: nursery.set_boxed_hatch(save, doc, 1, STEPS),   # an empty slot
                  lambda: nursery.take_held(save, 1 + SLOTS)):
         with self.assertRaises(DocumentError):
            with save.edit("bad"):
               bad()
      # the export: the slots and the waiting egg in the Nursery section, the boxed egg's role and counter set
      compiled = p.compile()[0]
      image = inventory.image_of(save, p)
      sl = engine.tool("save_layout")
      held, result = nursery.image_parts(save, compiled)
      self.assertIn(sl.nursery_payload(compiled, held, result), image)
      egg = nursery.record_bytes(compiled, SPROUTLE, storage.NEW_LEVEL, STEPS)
      self.assertNotEqual(egg, nursery.record_bytes(compiled, SPROUTLE, storage.NEW_LEVEL, None))
      self.assertIn(egg, image)
      with save.edit("Off"):
         nursery.set_boxed_hatch(save, doc, 0, None)
         nursery.take_held(save, 0)
         nursery.set_result(save, doc, None)
      self.assertEqual(nursery.result_of(save), None)
      self.assertEqual([b[nursery.SLOT_KEY] for b in nursery.held_of(save)], [1])
      save.data[nursery.TESTSAVE_NURSERY].append({"slot": SLOTS + 1, "species": "Nobody", "level": 0})
      problems = nursery.check_test(save, doc)
      self.assertTrue(any("slot 3" in x for x in problems) and any("unknown species" in x for x in problems),
                      problems)


class NurseryCliTests(NurseryCase):
   """!The commands."""

   def test_commands(self) -> None:
      """!show, eggs set, set, allow, fee, a refused removal through step-effect; the test save commands.
      @return None
      """
      b = ["battle", str(self.battle_json)]
      code, out = run_cli(*b, "nursery", "show")
      self.assertEqual(code, 0, out)
      self.assertIn("eggs: role egg, counter hatch_counter", out)
      for argv in (("eggs", "set", "name", "Seed"), ("set", "fee", "on"), ("set", "slots", "2"),
                   ("allow", "items", "Orb", "on"), ("allow", "rules", "on")):
         code, out = run_cli(*b, "nursery", *argv)
         self.assertEqual(code, 0, (argv, out))
      code, out = run_cli(*b, "nursery", "fee", "2", "7", "2")
      self.assertEqual((code, out.strip()), (0, "fee 0 (2 levels gained, level 7, 2 held)"))
      code, out = run_cli(*b, "nursery", "show")
      self.assertIn("battle setup takes eggs", out)
      self.assertIn("item Orb takes eggs", out)
      code, out = run_cli(*b, "step-effect", "remove", "egg_cycle")
      self.assertNotEqual(code, 0)
      self.assertIn("eggs.step_effect", out)
      code, out = run_cli(*b, "nursery", "eggs", "off")
      self.assertNotEqual(code, 0)
      self.assertEqual(run_cli(*b, "testsave", "new", SAVE)[0], 0)
      code, out = run_cli(*b, "testsave", "nursery", SAVE, "0", BREEZLE, "--level", "9", "--gained", "120")
      self.assertEqual(code, 0, out)
      code, out = run_cli(*b, "testsave", "nursery-result", SAVE, SPROUTLE, "--hatch", str(STEPS))
      self.assertIn(f"(egg, {STEPS} steps)", out)
      self.assertEqual(run_cli(*b, "testsave", "box", SAVE, "put", SPROUTLE)[0], 0)
      code, out = run_cli(*b, "testsave", "egg", SAVE, "0", str(STEPS))
      self.assertEqual(code, 0, out)
      code, out = run_cli(*b, "testsave", "export", SAVE, str(self.dir / "grove.sav"))
      self.assertEqual(code, 0, out)
      self.assertTrue((self.dir / "grove.sav").is_file())
      code, out = run_cli(*b, "testsave", "nursery", SAVE, "0", "--clear")
      self.assertEqual(code, 0, out)
      self.assertNotIn("nursery slot 0", out)


if __name__ == "__main__":
   unittest.main()
