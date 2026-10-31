#!/usr/bin/env python3
"""!Regression tests of the studio review's core findings (S14): grouped undo in lock step across the battle data's
files (F1), history trimming whole groups (F13), the files a save must take along (F3), a category reorder that
keeps every move's category (F5), renames that rewrite saved bench scenarios and scenario name checks (F6, F2),
removals the ruleset still needs (F9), taken names refused (F11), stat formulas checked (F12), the migration of
pre-E6a data (F10) and a failed group forgetting a new source (F15). No Qt.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase).
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, bench, document, logic  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import categories, conditions, resources, stages, stats  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## The Starter's condition logic.
CONDITIONS = "effects/conditions.ceffect"
## A small undo history for the trimming test.
SHORT_HISTORY = 4


class LockStepUndoTests(BattleTestCase):
   """!F1 / F13 / F3 / F15: grouped steps across files."""

   def test_partner_undo_undoes_newer_steps_first(self) -> None:
      """!A move rename (battle + structure), then a structure-only edit: undoing the rename from the battle file
      undoes the newer structure edit first, so both files agree; redo brings the rename back in both.
      @return None
      """
      p = self.project
      with p.battle.edit("Rename move"):
         battle.rename_entry(p.battle, "moves", "Strike", "Bonk")
      with p.structure.edit("Stat cap"):
         p.structure.data["rules"]["stat_cap"] = p.structure.data["rules"]["stat_cap"] - 1
      self.assertTrue(p.battle.undo())
      self.assertIn("Strike", p.names("moves"))
      self.assertEqual(p.structure.data["rules"]["fallback_move"], "Strike")
      self.assertIsNone(p.validate())
      self.assertTrue(p.battle.redo())
      self.assertEqual(p.structure.data["rules"]["fallback_move"], "Bonk")
      self.assertIn("Bonk", p.names("moves"))
      self.assertIsNone(p.validate())

   def test_source_typed_after_rename(self) -> None:
      """!A source edited after a condition rename: undoing the rename undoes that edit first.
      @return None
      """
      p = self.project
      source = p.effect_source(CONDITIONS)
      with p.structure.edit("Rename status"):
         conditions.rename_record(p.structure, "status", "Scorch", "Burnz")
      logic.set_source_text(p, CONDITIONS, source.text + "\n# typed later\n")
      self.assertTrue(p.structure.undo())
      self.assertNotIn("typed later", source.text)
      self.assertIn("Scorch", source.text)
      self.assertIsNone(p.validate())

   def test_new_step_drops_partner_redo(self) -> None:
      """!After undoing a rename, a new step in one file drops the rename's redo from the other one too (a redo
      of half the rename is impossible).
      @return None
      """
      p = self.project
      with p.battle.edit("Rename move"):
         battle.rename_entry(p.battle, "moves", "Strike", "Bonk")
      self.assertTrue(p.battle.undo())
      with p.structure.edit("Stat cap"):
         p.structure.data["rules"]["stat_cap"] = p.structure.data["rules"]["stat_cap"] - 1
      self.assertIsNone(p.battle.redo_label())
      self.assertFalse(p.battle.redo())
      self.assertIsNone(p.validate())

   def test_history_limit_trims_whole_groups(self) -> None:
      """!When the history limit trims a grouped step from one file, the other files lose it too (and their older
      steps), so no undo can bring back a part of it.
      @return None
      """
      p = self.project
      with mock.patch.object(document, "HISTORY_LIMIT", SHORT_HISTORY):
         with p.battle.edit("Rename move"):
            battle.rename_entry(p.battle, "moves", "Strike", "Bonk")
         for i in range(SHORT_HISTORY):
            with p.structure.edit(f"Stat cap {i}"):
               p.structure.data["rules"]["stat_cap"] = p.structure.data["rules"]["stat_cap"] - 1
      self.assertIsNone(p.battle.undo_label())
      while p.structure.undo():
         pass
      self.assertEqual(p.structure.data["rules"]["fallback_move"], "Bonk")
      self.assertIsNone(p.validate())

   def test_unsaved_group_files(self) -> None:
      """!Saving the structure file after a status rename takes the rewritten source along; a file changed alone
      is not taken.
      @return None
      """
      p = self.project
      with p.ruleset.edit("Notes"):
         p.ruleset.data["notes"] = "changed alone"
      with p.structure.edit("Rename status"):
         conditions.rename_record(p.structure, "status", "Scorch", "Burnz")
      files = document.unsaved_group_files(p.structure)
      self.assertIs(files[0], p.structure)
      self.assertIn(p.effect_source(CONDITIONS), files)
      self.assertNotIn(p.ruleset, files)

   def test_new_source_forgotten_on_rollback(self) -> None:
      """!A group that lists a new source and then fails leaves no unlisted source in the project.
      @return None
      """
      p = self.project
      rel = "effects/extra.ceffect"
      with self.assertRaises(DocumentError):
         with document.group("Add logic"):
            logic._new_source(p, rel, "Add logic")
            self.assertIn(rel, p.effects)
            raise DocumentError("later step refused")
      self.assertNotIn(rel, p.effects)
      self.assertNotIn(rel, p.battle.data.get(battle.EFFECTS_KEY, []))


class ReviewModelTests(BattleTestCase):
   """!F5, F6, F9, F10, F11, F12."""

   def scenario(self) -> Path:
      """!Writes a bench scenario naming a party, species, move, status, volatile, stage, resource and format.
      @return the file
      """
      folder = bench.scenario_folder(self.project)
      folder.mkdir(parents=True, exist_ok=True)
      species = self.project.names("species")[0]
      data = {"schema": bench.SCHEMA, "name": "named", "format": "Single", "seed": 1,
              "parties": [{"side": 0, "controller": "human", "data": "Novice Kit"},
                          {"side": 1, "members": [{"species": species, "level": 5, "moves": ["Strike"],
                                                   "resources": {"mp": 3}}]}],
              "pokes": [{"party": 0, "member": 0, "status": "Scorch", "volatiles": ["dazed"],
                         "stages": {"accuracy": 1}}],
              "choices": [{"move": "Strike"}]}
      path = folder / "named.json"
      path.write_text(json.dumps(data), encoding="utf-8")
      return path

   def test_category_reorder_keeps_moves(self) -> None:
      """!A move without a category takes the first; moving the first down writes its category into the move.
      @return None
      """
      doc = self.project.structure
      first = categories.category_rows(doc)[0]["name"]
      with doc.edit("No category"):
         battle.entry(doc, "moves", "Strike").pop("category", None)
      with doc.edit("Move"):
         self.assertTrue(categories.move_category(doc, first, 1))
      self.assertEqual(battle.entry(doc, "moves", "Strike")["category"], first)
      self.assertIsNone(self.project.validate())

   def test_renames_follow_scenarios(self) -> None:
      """!Renames of a party, move, status, volatile, stage and resource rewrite the saved scenario in the same
      undo step; the scenario counts unsaved and Save all writes it; undo puts it back.
      @return None
      """
      p = self.project
      path = self.scenario()
      self.assertEqual(bench.validate(json.loads(path.read_text(encoding="utf-8")), p), [])
      with p.battle.edit("Rename party"):
         battle.rename_entry(p.battle, "parties", "Novice Kit", "Rookie Kit")
      with p.battle.edit("Rename move"):
         battle.rename_entry(p.battle, "moves", "Strike", "Bonk")
      with p.structure.edit("Renames"):
         conditions.rename_record(p.structure, "status", "Scorch", "Burnz")
         conditions.rename_record(p.structure, "volatile", "dazed", "dizzy")
         stages.rename_stage(p.structure, "accuracy", "aim")
         resources.rename_resource(p.structure, "mp", "mana")
      doc = p.scenario(path)
      self.assertTrue(doc.dirty and p.dirty)
      p.save_all()
      data = json.loads(path.read_text(encoding="utf-8"))
      self.assertEqual(data["parties"][0]["data"], "Rookie Kit")
      self.assertEqual(data["parties"][1]["members"][0]["moves"], ["Bonk"])
      self.assertEqual(data["parties"][1]["members"][0]["resources"], {"mana": 3})
      self.assertEqual(data["pokes"][0], {"party": 0, "member": 0, "status": "Burnz", "volatiles": ["dizzy"],
                                          "stages": {"aim": 1}})
      self.assertEqual(data["choices"], [{"move": "Bonk"}])
      self.assertEqual(bench.validate(data, p), [])
      self.assertTrue(p.structure.undo())
      self.assertEqual(doc.data["pokes"][0]["status"], "Scorch")

   def test_validate_reports_unknown_names(self) -> None:
      """!A scenario naming a party and a move the data does not have is reported.
      @return None
      """
      data = json.loads(self.scenario().read_text(encoding="utf-8"))
      data["parties"][0]["data"] = "Nobody"
      data["choices"] = [{"move": "Nope"}]
      problems = bench.validate(data, self.project)
      self.assertIn("parties[0].data: unknown party 'Nobody'", problems)
      self.assertIn("choices[0].move: unknown move 'Nope'", problems)

   def test_stage_the_ruleset_needs(self) -> None:
      """!The crit stage the ruleset's crit pipeline needs is not removed (like effect logic's users).
      @return None
      """
      doc = self.project.structure
      with self.assertRaisesRegex(DocumentError, "still needed by the ruleset"):
         with doc.edit("Remove"):
            stages.remove_stage(doc, "critical")
      self.assertIn("critical", stages.stage_names(doc))
      self.assertIsNone(self.project.validate())

   def test_taken_names_refused(self) -> None:
      """!Adding under a taken name is refused (core and CLI); a copy numbers its name.
      @return None
      """
      doc = self.project.battle
      with self.assertRaisesRegex(DocumentError, "already a type 'Fire'"):
         with doc.edit("Add"):
            battle.add_entry(doc, "types", "Fire")
      with doc.edit("Copy"):
         self.assertEqual(battle.add_entry(doc, "moves", "Strike", "Strike", unique=True), "Strike 2")
      with redirect_stdout(io.StringIO()):
         self.assertNotEqual(cli(["battle", str(self.dir / "battle.json"), "add", "types", "Fire"]), 0)

   def test_stat_formula_checked(self) -> None:
      """!A stat formula the ruleset lacks is refused at edit time (a known one goes through).
      @return None
      """
      doc = self.project.structure
      known = battle.stat_formulas(self.project.ruleset)
      with self.assertRaisesRegex(DocumentError, "no stat formula 'nope'"):
         with doc.edit("Formula"):
            stats.set_stat(doc, "magic", "formula", "nope")
      with doc.edit("Formula"):
         stats.set_stat(doc, "magic", "formula", known[-1])
      with self.assertRaisesRegex(DocumentError, "no stat formula"):
         with doc.edit("Add"):
            stats.add_stat(doc, "luck", formula="nope")

   def test_migrate_all(self) -> None:
      """!Pre-E6a stage names are migrated by migrate_all() (the CLI's migrate and the window's offer).
      @return None
      """
      doc = self.project.battle
      with doc.edit("Old"):
         doc.data[stages.OLD_NAMES_KEY] = {"accuracy": "accuracy"}
      self.assertTrue(stages.needs_any_migration(doc))
      with doc.edit("Migrate"):
         self.assertEqual(stages.migrate_all(doc), ["stages"])
      self.assertFalse(stages.needs_any_migration(doc))
      self.assertIsNone(self.project.validate())


if __name__ == "__main__":
   unittest.main()
