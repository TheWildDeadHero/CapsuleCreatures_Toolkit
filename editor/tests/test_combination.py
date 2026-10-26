#!/usr/bin/env python3
"""!Tests for the combination methods in the studio (D-28 section 1, engine B1): core.structure.combination (the
structure's combine_methods, the engine's choice lists and limits, the editing calls, the refusals while effect logic
or a script names a method, the renames that follow, the preview on typed and boxed records), the logic catalog's
names and palette, the species fields' named values and the species' combine moves, and the
`battle FILE combine ...` / `species-field values` commands. No Qt.

Uses the map sandbox as one game (sample_data.make_field_game): the Starter's merge_altar method (two slots, level 5
or more, a type table, consumed inputs), its `on combine` rule merge_rule (effects/field.ceffect) and the sandbox's
merge_altar script (`combine open merge_altar`).
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
from capsule_studio.core import battle, engine, inventory, logic, messages  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import combination, species_fields, storage  # noqa: E402
from sample_data import DATA, make_field_game  # noqa: E402

## The Starter's method, its slot roles and its table.
ALTAR, ROLES, ELEMENTS = "merge_altar", ["first", "second"], "elements"
## The sandbox's scripts source (relative to the game's data folder).
SANDBOX_SCRIPTS = ("scripts", "sandbox.cscript")
## The Starter's effect source holding merge_rule.
FIELD_LOGIC = "field.ceffect"
## A pair the altar takes (Wind + Water: the Light group, its first base species) and what it gives.
BREEZLE, TIDEPUP, GLIMMET = "Breezle", "Tidepup", "Glimmet"
## A level the slots take, one they refuse.
FIT_LEVEL, UNFIT_LEVEL = 6, 3
## A species below the slots' level.
SPROUTLE = "Sproutle"
## The altar's messages at its moments.
DONE_MESSAGE = "merge_done"
## A named-values species field the tests add, its names (B2: the Starter's own kin field is the grove's).
GROUP_FIELD, GROUP_VALUES = "clan", ["leaf", "wave", "gust"]
## The Starter's nursery method (B2: the Grove).
GROVE = "grove"
## The fee per result level the tests state (`result.level * 10`).
FEE_PER_LEVEL = 10
## A test save's name.
SAVE = "altar"


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


def record(species: str, level: int) -> dict[str, object]:
   """!A preview input.
   @param species  its species
   @param level    its level
   @return the record
   """
   return {"species": species, "level": level}


class CombinationCase(unittest.TestCase):
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
      self.dir = Path(tempfile.mkdtemp(prefix="capsule_b1_"))
      self.battle_json = make_field_game(self.dir)
      self.project = BattleProject.open(self.battle_json)

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.dir, ignore_errors=True)

   def scripts_text(self) -> str:
      """!The sandbox's scripts source.
      @return text
      """
      return self.dir.joinpath(DATA, *SANDBOX_SCRIPTS).read_text(encoding="utf-8")

   def logic_text(self) -> str:
      """!The Starter's field logic source as the project holds it (unsaved edits included).
      @return text
      """
      return self.project.effect_source(f"effects/{FIELD_LOGIC}").text

   def compiles(self) -> None:
      """!Asserts the battle data compiles.
      @return None
      """
      compiled, error = self.project.compile()
      self.assertIsNotNone(compiled, error)


class CombinationReadTests(CombinationCase):
   """!The lists, the rows and the logic catalog."""

   def test_rows_and_engine_lists(self) -> None:
      """!The Starter's method with the engine's lists and limits; its users; the catalog's names and the palette.
      @return None
      """
      bc = engine.tool("battle_compiler")
      doc = self.project.structure
      self.assertEqual(combination.method_names(doc), [ALTAR, GROVE])
      self.assertEqual(combination.kinds(), list(bc.COMBINE_KINDS))
      self.assertEqual(combination.moments(), list(bc.COMBINE_MOMENTS))
      gba = engine.tool("build_settings").platform_limits("gba")["max_combine_inputs"]
      self.assertEqual(combination.limits("gba")["inputs"], gba)
      self.assertGreaterEqual(combination.limits("desktop")["inputs"], gba)
      row = combination.method_rows(doc)[0]
      self.assertEqual((row["min"], row["max"], row["roles"]), (2, 2, ROLES))
      self.assertEqual(row["afterwards"], "consumed")
      self.assertEqual(row["tables"], [ELEMENTS])
      self.assertTrue(any(FIELD_LOGIC in u for u in row["users"]), row["users"])
      self.assertTrue(combination.script_users(doc, ALTAR))
      shown = "\n".join(combination.show_lines(doc, ALTAR))
      self.assertIn("Water x Earth -> Bio", shown)
      self.assertIn("requires level >= 5", shown)
      lists = logic.name_lists(self.project)
      self.assertEqual(lists["combine_methods"], [ALTAR, GROVE])
      self.assertEqual(lists["combine_slots"], ROLES)
      self.assertIn(combination.HOOK, bc.GLOBAL_HOOKS)
      groups = {g for g, _label, _text in logic.statement_templates(self.project)}
      self.assertIn("Combination", groups)
      self.assertEqual([str(d) for d in logic.diagnostics(self.project)], [])

   def test_preview(self) -> None:
      """!The engine's mirror: a pair the table takes, a slot's requirement refusing, a test save's boxed creatures.
      @return None
      """
      p = self.project
      got = combination.preview(p, ALTAR, [record(BREEZLE, FIT_LEVEL), record(TIDEPUP, FIT_LEVEL)])
      self.assertEqual((got["status"], got["species"], got["level"]), ("ok", GLIMMET, FIT_LEVEL))
      self.assertTrue(got["moves"])
      text = combination.preview_text(got, [record(BREEZLE, FIT_LEVEL), record(TIDEPUP, FIT_LEVEL)])
      self.assertIn(f"-> {GLIMMET}", text)
      refused = combination.preview(p, ALTAR, [record(SPROUTLE, UNFIT_LEVEL), record(TIDEPUP, FIT_LEVEL)])
      self.assertEqual((refused["status"], refused["slot"]), ("unfit", 0))
      self.assertIn("refused: unfit (slot 0)", combination.preview_text(refused, []))
      with self.assertRaises(DocumentError):
         combination.preview(p, "no_such_method", [record(BREEZLE, FIT_LEVEL)])
      save = inventory.new_testsave(p, SAVE)
      with save.edit("Box"):
         storage.put_creature(save, p.structure, BREEZLE, FIT_LEVEL)
         storage.put_creature(save, p.structure, TIDEPUP, FIT_LEVEL)
      save.save()
      boxed = storage.boxed_of(inventory.open_testsave(p, SAVE))
      self.assertEqual(combination.preview(p, ALTAR, boxed)["species"], GLIMMET)
      code, out = run_cli("battle", str(self.battle_json), "combine", "preview", ALTAR, "--save", SAVE, "--slots",
                          ",".join(str(b["slot"]) for b in boxed))
      self.assertEqual(code, 0, out)
      self.assertIn(GLIMMET, out)


class CombinationEditTests(CombinationCase):
   """!Editing, refusals and renames."""

   def test_add_slots_rules_and_tables(self) -> None:
      """!A new method: its count, a slot role renamed (its expression follows), a table keyed by a named-values
      field with a cell, a recipe, a when, a pick, moves, a message; every step compiles.
      @return None
      """
      doc = self.project.structure
      with doc.edit("Add"):
         combination.add_method(doc, "fuse")
      m = combination.method(doc, "fuse")
      self.assertEqual(combination.roles_of(m), ROLES)
      self.assertEqual(combination.rule_kind(combination.rules_of(m)[0]), "expression")
      with doc.edit("Count"):
         combination.set_count(doc, "fuse", 2, 3)
      self.assertEqual(len(combination.roles_of(m)), 3)
      with doc.edit("Role"):
         places = combination.set_slot(doc, "fuse", 0, role="left", requires="level >= 2")
      self.assertTrue(places)
      self.assertIn("left.", combination.rules_of(m)[0]["expression"])
      with self.assertRaises(DocumentError):
         combination.set_slot(doc, "fuse", 1, role="left")
      with doc.edit("Field"):
         species_fields.add_field(doc, GROUP_FIELD, 2)
         species_fields.set_values(doc, GROUP_FIELD, GROUP_VALUES)
         species_fields.set_value(doc, BREEZLE, GROUP_FIELD, GROUP_VALUES[2])
         species_fields.set_value(doc, TIDEPUP, GROUP_FIELD, GROUP_VALUES[1])
      self.assertEqual(combination.key_values(doc, GROUP_FIELD), GROUP_VALUES)
      with doc.edit("Table"):
         combination.add_table(doc, "fuse", "kins", GROUP_FIELD)
         combination.set_cell(doc, "fuse", "kins", GROUP_VALUES[2], GROUP_VALUES[1], GROUP_VALUES[0])
      self.assertEqual(combination.cells(doc, "fuse", "kins"),
                       {(GROUP_VALUES[2], GROUP_VALUES[1]): GROUP_VALUES[0]})
      with doc.edit("Rules"):
         combination.add_rule(doc, "fuse", {"recipe": [BREEZLE, TIDEPUP], "result": GLIMMET}, 0)
         combination.add_rule(doc, "fuse", {"table": "kins"}, 1)
         combination.set_rule(doc, "fuse", 1, when="count == 3", pick={"choose": "random"})
         combination.move_rule(doc, "fuse", 1, -1)
      self.assertEqual([combination.rule_kind(r) for r in combination.rules_of(m)], ["table", "recipe", "expression"])
      with self.assertRaises(DocumentError):
         combination.remove_table(doc, "fuse", "kins")   # a rule names it
      with doc.edit("Moves"):
         combination.set_moves(doc, "fuse", limit=2, chooser="player")
         combination.set_source(doc, "fuse", "known", True, 1)
         combination.set_message(doc, "fuse", "combined", DONE_MESSAGE)
         combination.set_value(doc, "fuse", "fee", f"result.level * {FEE_PER_LEVEL}")
      self.assertEqual(combination.method(doc, "fuse")["messages"], {"combined": DONE_MESSAGE})
      self.compiles()
      got = combination.preview(self.project, "fuse", [record(BREEZLE, FIT_LEVEL), record(TIDEPUP, FIT_LEVEL)])
      # the table rule wants three inputs: the recipe gives the result, at the default level
      self.assertEqual((got["status"], got["rule"], got["species"]), ("ok", 1, GLIMMET))
      self.assertEqual(got["fee"], got["level"] * FEE_PER_LEVEL)
      with self.assertRaises(DocumentError):
         combination.set_message(doc, "fuse", "combined", "no_such_message")
      with self.assertRaises(DocumentError):
         combination.add_method(doc, "fuse")
      with doc.edit("Remove"):
         combination.remove_method(doc, "fuse")
      self.assertEqual(combination.method_names(doc), [ALTAR, GROVE])

   def test_refusal_and_rename_follow(self) -> None:
      """!The altar is not removed while merge_rule and the sandbox script name it; a rename follows both; a slot
      role rename follows `input.ROLE`; renames elsewhere follow into the method (species, message, field value).
      @return None
      """
      doc = self.project.structure
      with self.assertRaises(DocumentError) as e:
         combination.remove_method(doc, ALTAR)
      self.assertIn(FIELD_LOGIC, str(e.exception))
      with doc.edit("Rename"):
         places = combination.rename_method(doc, ALTAR, "altar")
      self.assertTrue(any(p.startswith("scripts:") for p in places), places)
      self.assertIn("combine open altar", self.scripts_text())
      self.assertIn("altar", self.logic_text())
      self.assertEqual(combination.method_names(doc), ["altar", GROVE])
      with doc.edit("Role"):
         combination.set_slot(doc, "altar", 0, role="lead")
      # B2: the Grove's slots are first / second too, so the logic's `input.first` stays (another method names it)
      self.assertIn("input.first", self.logic_text())
      self.compiles()
      # a species rename follows into a recipe
      with doc.edit("Recipe"):
         combination.add_rule(doc, "altar", {"recipe": [BREEZLE, TIDEPUP], "result": GLIMMET}, 0)
      with self.project.battle.edit("Rename species"):
         battle.rename_entry(self.project.battle, "species", GLIMMET, "Glimmo")
      rule = combination.rules_of(combination.method(doc, "altar"))[0]
      self.assertEqual(rule["result"], "Glimmo")
      # a message rename follows into the moments
      with self.project.battle.edit("Rename message"):
         messages.rename(self.project.battle, DONE_MESSAGE, "merge_finished")
      self.assertEqual(combination.method(doc, "altar")["messages"]["combined"], "merge_finished")
      self.compiles()


class SpeciesCombinationTests(CombinationCase):
   """!The species' named field values and combine moves."""

   def test_named_values_and_combine_moves(self) -> None:
      """!A field's value names: a species' value by name, a rename following into a table; the combine moves
      follow a move rename.
      @return None
      """
      doc = self.project.structure
      with doc.edit("Field"):
         species_fields.add_field(doc, GROUP_FIELD, 2)
         species_fields.set_values(doc, GROUP_FIELD, GROUP_VALUES)
         species_fields.set_value(doc, BREEZLE, GROUP_FIELD, GROUP_VALUES[1])
      own = next(v for v in species_fields.values_of(doc, BREEZLE) if v["name"] == GROUP_FIELD)
      self.assertEqual((own["value"], own["values"]), (GROUP_VALUES[1], GROUP_VALUES))
      with doc.edit("Table"):
         combination.add_table(doc, ALTAR, "kins", GROUP_FIELD)
         combination.set_cell(doc, ALTAR, "kins", GROUP_VALUES[1], GROUP_VALUES[1], GROUP_VALUES[0])
      with doc.edit("Rename value"):
         species_fields.rename_value(doc, GROUP_FIELD, GROUP_VALUES[1], "tide")
      self.assertEqual(combination.cells(doc, ALTAR, "kins"), {("tide", "tide"): GROUP_VALUES[0]})
      own = next(v for v in species_fields.values_of(doc, BREEZLE) if v["name"] == GROUP_FIELD)
      self.assertEqual(own["value"], "tide")
      self.compiles()
      entry = battle.entry(self.project.battle, "species", BREEZLE)
      moves = list(entry.get(battle.COMBINE_MOVES_KEY) or [])
      self.assertTrue(moves)
      with self.project.battle.edit("Rename move"):
         battle.rename_entry(self.project.battle, "moves", moves[0], "Renamed Move")
      entry = battle.entry(self.project.battle, "species", BREEZLE)
      self.assertEqual(entry[battle.COMBINE_MOVES_KEY][0], "Renamed Move")


class C9CombinationTests(CombinationCase):
   """!The D-28 review's fixes (C9): item words in every combination expression, method-qualified slot roles,
   move sources' `from` and the pushed moves."""

   def test_item_words_follow(self) -> None:
      """!An item named in a rule's when (`item.NAME`) follows the item's rename (one holders() path with the field
      rules) and the item cannot be removed while read.
      @return None
      """
      doc = self.project.structure
      with doc.edit("When"):
         combination.set_rule(doc, GROVE, 0, when="first.held_item != item.focus_lens")
      self.compiles()
      with self.project.battle.edit("Rename item"):
         places = battle.rename_entry(self.project.battle, "items", "Focus Lens", "Keen Lens")
      self.assertTrue(places)
      self.assertEqual(combination.rules_of(combination.method(doc, GROVE))[0]["when"],
                       "first.held_item != item.keen_lens")
      self.compiles()
      with self.assertRaisesRegex(DocumentError, GROVE):
         with self.project.battle.edit("Remove item"):
            battle.remove_entry(self.project.battle, "items", "Keen Lens")

   def test_shared_role_rename(self) -> None:
      """!The Grove and the altar both have `first`: renaming the Grove's follows its own expressions, move sources
      and the logic's `input.grove.first` only (the altar's `input.first` stays); the method's rename follows its
      qualified reads, and a method is not removed while one is read.
      @return None
      """
      doc = self.project.structure
      rel = f"effects/{FIELD_LOGIC}"
      text = self.logic_text() + ('\nglobal "grove_rule" {\n   on combine {\n      if field.combine_method == grove {\n'
                                  '         inherit bond from input.grove.first;\n      }\n   }\n}\n')
      logic.set_source_text(self.project, rel, text)
      self.compiles()
      with doc.edit("Rules"):
         combination.set_source(doc, GROVE, "combine_moves", True, 0, False, "first")
      with doc.edit("Role"):
         places = combination.set_slot(doc, GROVE, 0, role="elder")
      self.assertTrue(any("grove_rule" in p for p in places), places)
      grove = combination.method(doc, GROVE)
      self.assertIn("elder.kin", grove["odds"]["value"])
      self.assertEqual(combination.sources_of(grove)[0]["from"], "elder")
      self.assertEqual(combination.roles_of(combination.method(doc, ALTAR)), ROLES)
      source = self.logic_text()
      self.assertIn("input.grove.elder", source)
      self.assertIn("inherit bond from input.first;", source)   # the altar's: another method names it
      self.compiles()
      with doc.edit("Rename"):
         combination.rename_method(doc, GROVE, "nest")
      self.assertIn("input.nest.elder", self.logic_text())
      self.compiles()
      with doc.edit("Add"):
         combination.add_method(doc, "fuse")
      text = self.logic_text() + ('\nglobal "fuse_rule" {\n   on combine {\n'
                                  '      inherit bond from input.fuse.first;\n   }\n}\n')
      logic.set_source_text(self.project, rel, text)
      self.compiles()
      with self.assertRaisesRegex(DocumentError, "fuse_rule"):
         combination.remove_method(doc, "fuse")

   def test_move_from_and_push(self) -> None:
      """!A source's `from` (one slot role; a role of the method, not with all) and the moves' push compile and show.
      @return None
      """
      doc = self.project.structure
      with doc.edit("Moves"):
         combination.set_source(doc, GROVE, "combine_moves", True, 0, False, "second")
         combination.set_moves(doc, GROVE, push=True)
      self.compiles()
      shown = "\n".join(combination.show_lines(doc, GROVE))
      self.assertIn("combine_moves from second", shown)
      self.assertIn("pushed after its own", shown)
      with self.assertRaises(DocumentError):
         combination.set_source(doc, GROVE, "combine_moves", True, 0, False, "mother")
      with self.assertRaises(DocumentError):
         combination.set_source(doc, GROVE, "combine_moves", True, 0, True, "second")
      with doc.edit("Every input"):
         combination.set_source(doc, GROVE, "combine_moves", True)
         combination.set_moves(doc, GROVE, push=False)
      grove = combination.method(doc, GROVE)
      self.assertNotIn("from", combination.sources_of(grove)[0])
      self.assertNotIn("push", grove["moves"])
      b = ["battle", str(self.battle_json)]
      code, out = run_cli(*b, "combine", "source", GROVE, "combine_moves", "on", "--from", "first")
      self.assertEqual(code, 0, out)
      code, out = run_cli(*b, "combine", "moves", GROVE, "--push", "on")
      self.assertEqual(code, 0, out)
      code, out = run_cli(*b, "combine", "show", GROVE)
      self.assertIn("combine_moves from first", out)
      self.assertIn("pushed after its own", out)
      code, out = run_cli(*b, "combine", "source", GROVE, "known", "on", "--from", "nobody")
      self.assertNotEqual(code, 0)


class CombinationCliTests(CombinationCase):
   """!The `battle FILE combine ...` and `species-field values` commands."""

   def test_commands(self) -> None:
      """!list / show / preview / add / slot / rule / rename / remove (refused while used) and the field values.
      @return None
      """
      b = ["battle", str(self.battle_json)]
      code, out = run_cli(*b, "combine", "list")
      self.assertEqual(code, 0, out)
      self.assertIn(ALTAR, out)
      code, out = run_cli(*b, "combine", "show", ALTAR)
      self.assertIn("table elements", out)
      code, out = run_cli(*b, "combine", "preview", ALTAR, f"{BREEZLE}:{FIT_LEVEL}", f"{TIDEPUP}:{FIT_LEVEL}")
      self.assertEqual(code, 0, out)
      self.assertIn(f"-> {GLIMMET}", out)
      code, out = run_cli(*b, "combine", "preview", ALTAR, f"{SPROUTLE}:{UNFIT_LEVEL}", f"{TIDEPUP}:{FIT_LEVEL}")
      self.assertIn("refused: unfit", out)
      self.assertEqual(run_cli(*b, "combine", "add", "fuse")[0], 0)
      code, out = run_cli(*b, "combine", "slot", "fuse", "0", "--role", "left")
      self.assertEqual(code, 0, out)
      code, out = run_cli(*b, "combine", "rule", "fuse", "add", "recipe", f"{BREEZLE},{TIDEPUP}", GLIMMET)
      self.assertEqual(code, 0, out)
      code, out = run_cli(*b, "combine", "set", "fuse", "fee", f"result.level * {FEE_PER_LEVEL}")
      self.assertEqual(code, 0, out)
      code, out = run_cli(*b, "combine", "show", "fuse")
      self.assertIn(f"fee result.level * {FEE_PER_LEVEL}", out)
      self.assertIn("slot 0 left", out)
      code, out = run_cli(*b, "combine", "remove", ALTAR)
      self.assertNotEqual(code, 0)
      self.assertIn("is used by", out)
      code, out = run_cli(*b, "combine", "rename", ALTAR, "altar")
      self.assertEqual(code, 0, out)
      self.assertIn("combine open altar", self.scripts_text())
      code, out = run_cli(*b, "combine", "set", "fuse", "kind", "no_such_kind")
      self.assertNotEqual(code, 0)
      self.assertEqual(run_cli(*b, "combine", "remove", "fuse")[0], 0)
      self.assertEqual(run_cli(*b, "species-field", "add", GROUP_FIELD, "--width", "2")[0], 0)
      code, out = run_cli(*b, "species-field", "values", GROUP_FIELD, ",".join(GROUP_VALUES))
      self.assertEqual(code, 0, out)
      code, out = run_cli(*b, "species-field", "values", GROUP_FIELD)
      self.assertIn(", ".join(GROUP_VALUES), out)


if __name__ == "__main__":
   unittest.main()
