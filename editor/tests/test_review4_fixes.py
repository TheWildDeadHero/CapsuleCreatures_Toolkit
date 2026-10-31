#!/usr/bin/env python3
"""!Review 4's studio findings (engine package C6) on a copy of the Starter sample (no Qt):
  - 3: a test save's export carries the game's script banks and its target platform;
  - 13: removing a form warns (saved records keep form numbers) and the CLI refuses without --force;
  - 14: renaming a form other species share while effect logic names it is refused with a clear message;
  - 15: a species field rename follows training.yields; a custom role rename follows recruit.item_role and the
    transformation's form_role;
  - 24: new context value names that move a value warn;
and the new manifest keys' core and commands: recruit refusal_consumes, species teachable (a move rename follows),
the weather-suppressing tag, the training point, the save shapes of a scripts manifest.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_battle import BattleTestCase  # noqa: E402

from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, engine, inventory, save_shapes, species_growth  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import flags, record, recruit, species_fields, transformation  # noqa: E402

## The engine save fixture's older recorded shapes (its history's first entries, before the build's own; C7).
OLDER_SHAPES = 3
## The Starter's creature with a form.
FORM_SPECIES = "Glimmet"
## Its form.
FORM = "Radiant"


class Review4Tests(BattleTestCase):
   """!The studio's review 4 fixes."""

   def run_cli(self, *args: str) -> tuple[int, str]:
      """!Runs one command on the copy.
      @param args  arguments after `battle FILE`
      @return (exit status, output)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         code = cli(["battle", str(self.dir / "battle.json"), *args])
      return code, out.getvalue() + err.getvalue()

   def test_export_banks_and_platform(self) -> None:
      """!3: the export names the game's first target platform and its script banks (none outside a game)."""
      self.assertEqual(inventory.script_banks(self.project), [])
      self.assertIn(inventory.export_platform(self.project), (None, "gba", "desktop", "headless"))

   def test_form_removal_warns(self) -> None:
      """!13: the last numbered form: its number names no form afterwards; the CLI refuses without --force."""
      warning = species_growth.form_removal_warning(self.project.battle, FORM_SPECIES, FORM)
      self.assertIn("form number", warning)
      code, out = self.run_cli("form", "remove", FORM_SPECIES, FORM)
      self.assertNotEqual(code, 0)
      self.assertIn("--force", out)
      code, out = self.run_cli("form", "remove", FORM_SPECIES, FORM, "--force")
      self.assertIn("warning:", out)

   def test_shared_form_rename_refused(self) -> None:
      """!14: a second species with a Radiant form: the rename cannot follow the logic for one species alone."""
      doc = self.project.battle
      other = next(s["name"] for s in battle.entries(doc, "species") if s["name"] != FORM_SPECIES)
      with doc.edit("Add form"):
         species_growth.add_form(doc, other, FORM)
      with self.assertRaisesRegex(DocumentError, "other species"):
         with doc.edit("Rename form"):
            species_growth.rename_form(doc, FORM_SPECIES, FORM, "Bright")

   def test_renames_follow(self) -> None:
      """!15: a yield field and the form role follow their renames."""
      doc = self.project.structure
      with doc.edit("Rename field"):
         species_fields.rename_field(doc, "yield_hp", "gives_hp")
      self.assertEqual(transformation.training(doc)[transformation.YIELDS_KEY]["hp"], "gives_hp")
      with doc.edit("Rename role"):
         record.rename_role(doc, "form", "shape")
      self.assertEqual(transformation.transformation(doc)[transformation.FORM_ROLE_KEY], "shape")
      with doc.edit("Item role"):
         recruit.set_field(doc, recruit.ITEM_ROLE_KEY, "current_mp")
      with doc.edit("Rename role"):
         record.rename_role(doc, "current_mp", "mana_left")
      self.assertEqual(recruit.section(doc)[recruit.ITEM_ROLE_KEY], "mana_left")

   def test_context_reorder_warning(self) -> None:
      """!24: day and morning swapped: both move; the same names: no warning."""
      doc = self.project.structure
      warning = transformation.context_order_warning(doc, "time_of_day", ["day", "morning", "evening", "night"])
      self.assertIn("'morning' 0 -> 1", warning)
      self.assertIsNone(transformation.context_order_warning(doc, "time_of_day", "morning,day,evening,night"))

   def test_refusal_consumes(self) -> None:
      """!The recruit refusals that use the item up: set, shown, refused for an unknown refusal."""
      doc = self.project.structure
      with doc.edit("Consumes"):
         recruit.set_refusal_consumes(doc, ["refused"])
      self.assertEqual(recruit.section(doc)[recruit.REFUSAL_CONSUMES_KEY], ["refused"])
      with self.assertRaises(DocumentError):
         recruit.set_refusal_consumes(doc, ["owned"])
      code, _out = self.run_cli("recruit", "refusal-consumes", "blocked")
      self.assertEqual(code, 0)
      reopened = battle.BattleProject.open(self.dir / "battle.json")
      self.assertEqual(recruit.section(reopened.structure)[recruit.REFUSAL_CONSUMES_KEY], ["blocked"])

   def test_teachable(self) -> None:
      """!A species' teachable moves; a move rename follows into them."""
      doc = self.project.battle
      species = battle.entries(doc, "species")[0]["name"]
      move = battle.entries(doc, "moves")[0]["name"]
      with doc.edit("Teachable"):
         self.assertTrue(battle.set_teachable(doc, species, move, True))
      self.assertEqual(battle.teachable(doc, species), [move])
      with doc.edit("Rename"):
         battle.rename_entry(doc, "moves", move, "Fresh Move")
      self.assertEqual(battle.teachable(doc, species), ["Fresh Move"])
      code, _out = self.run_cli("teachable", species, "add", move)
      self.assertEqual(code, 0)
      code, out = self.run_cli("teachable", species)
      self.assertEqual(code, 0)
      self.assertIn(move, out)

   def test_weather_suppress_tag(self) -> None:
      """!The weather-suppressing tag: only a tag; a tag rename follows it."""
      doc = self.project.battle
      with doc.edit("Tag"):
         flags.add_name(doc, flags.TAGS_KEY, "calm")
      with doc.edit("Suppress"):
         flags.set_weather_suppress_tag(doc, "calm")
      self.assertEqual(flags.weather_suppress_tag(doc), "calm")
      with self.assertRaises(DocumentError):
         flags.set_weather_suppress_tag(doc, "nothing")
      with doc.edit("Rename tag"):
         flags.rename_name(doc, flags.TAGS_KEY, "calm", "still")
      self.assertEqual(flags.weather_suppress_tag(doc), "still")
      self.assertEqual(self.run_cli("tag", "add", "hush")[0], 0)
      self.assertEqual(self.run_cli("tag", "weather-suppress", "hush")[0], 0)
      code, out = self.run_cli("tag", "weather-suppress")
      self.assertEqual((code, out.strip()), (0, "hush"))

   def test_training_point(self) -> None:
      """!The training point: one of the ruleset's points."""
      doc = self.project.structure
      self.assertIn("power", transformation.training_points(doc))
      with self.assertRaises(DocumentError):
         with doc.edit("Point"):
            transformation.set_training(doc, transformation.POINT_KEY, "nowhere")
      code, _out = self.run_cli("training", "set", "point", "null")
      self.assertEqual(code, 0)


class SaveShapeTests(BattleTestCase):
   """!The save shapes of the engine's save fixture (a copy: recording writes its history)."""

   def test_rows_and_record(self) -> None:
      """!The recorded shapes are listed with their remaps; recording a fresh history adds the build's."""
      src = Path(engine.root()) / "tests/data/save"
      with tempfile.TemporaryDirectory() as tmp:
         folder = Path(tmp)
         for name in ("scripts.json", "save.cscript", "save_history.json"):
            shutil.copy(src / name, folder / name)
         # engine C7: the fixture's history records the build's shapes too; keep its older ones only
         history = json.loads((folder / "save_history.json").read_text(encoding="utf-8"))
         history["shapes"] = history["shapes"][:OLDER_SHAPES]
         (folder / "save_history.json").write_text(json.dumps(history), encoding="utf-8")
         rows = save_shapes.rows(folder / "scripts.json")
         self.assertTrue(any(r["bank"] == "flags.permanent" and not r["recorded"] for r in rows))
         self.assertEqual({m["bank"] for m in save_shapes.remaps(folder / "scripts.json")},
                          {"flags.permanent", "vars.permanent", "names"})
         self.assertGreater(save_shapes.record(folder / "scripts.json"), 0)
         self.assertTrue(all(r["recorded"] for r in save_shapes.rows(folder / "scripts.json")))
         out = io.StringIO()
         with redirect_stdout(out):
            self.assertEqual(cli(["script", "save-shapes", str(folder / "scripts.json")]), 0)
         self.assertIn("flags.permanent", out.getvalue())


if __name__ == "__main__":
   import unittest
   unittest.main()
