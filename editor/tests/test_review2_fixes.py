#!/usr/bin/env python3
"""!Regression tests of spot review 2's studio findings (C4): a removal the ruleset still needs is refused even
while another file's error comes first (review2 probes/p_mask.py), a rolled-back grouped edit leaves every
Document's history and unsaved state as they were, removing or moving a passive slot warns that saved records keep
their slot numbers (core and CLI), the pipelines page's default passive follows the engine's
passive_for(), and a malformed reference generators manifest leaves the bench with the engine's
generator (core and CLI). No Qt.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase).
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, bench, document, pipelines, templates  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import passive_slots, stages  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## A move power the battle compiler refuses (an unrelated content error).
BAD_POWER = 99999
## A small undo history for the trimming test.
SHORT_HISTORY = 3
## Passive indices of the first_slot_passive() test.
HIDDEN = 0
FIRST = 1
SECOND = 2
## A malformed capsule.generators/1 manifest.
BAD_GENERATORS = '{"schema": "capsule.generators/1", "generators": [{"nam": 1}]}'


class RulesetKeptTests(BattleTestCase):
   """!check_ruleset_kept() binds the ruleset on its own (review2 N1)."""

   def test_masked_by_other_error(self) -> None:
      """!With a move's power out of range, removing the crit stage the ruleset's crit pipeline needs is still
      refused (p_mask.py); the unrelated error alone is not the ruleset's.
      @return None
      """
      p = self.project
      with p.battle.edit("Break"):
         p.battle.data["moves"][1]["power"] = BAD_POWER
      self.assertIn("power", p.error_now())
      self.assertIsNone(battle.ruleset_problem(p.structure))
      with self.assertRaisesRegex(DocumentError, "still needed by the ruleset: ruleset.json: pipelines.crit"):
         with p.structure.edit("Remove stage"):
            stages.remove_stage(p.structure, "critical")
      self.assertIn("critical", [s.get("name") for s in p.structure.data["stages"]])


class RolledBackGroupTests(BattleTestCase):
   """!A grouped edit that raises leaves the history as it was (review2: document.py redo / trim)."""

   def test_redo_and_dirty_kept(self) -> None:
      """!After an undone rename, a group whose second edit raises keeps both files' redo steps and their unsaved
      state; the rename can still be redone.
      @return None
      """
      p = self.project
      with p.battle.edit("Rename move"):
         battle.rename_entry(p.battle, "moves", "Strike", "Bonk")
      self.assertTrue(p.battle.undo())
      p.save_all()
      redo = (list(p.battle._redo), list(p.structure._redo))
      dirty = (p.battle.dirty, p.structure.dirty)
      with self.assertRaises(DocumentError):
         with document.group("Refused"):
            with p.structure.edit("Stat cap"):
               p.structure.data["rules"]["stat_cap"] -= 1
            with p.battle.edit("Refused"):
               p.battle.data["moves"][0]["power"] = 1
               raise DocumentError("refused")
      self.assertEqual((p.battle._redo, p.structure._redo), redo)
      self.assertEqual((p.battle.dirty, p.structure.dirty), dirty)
      self.assertTrue(p.battle.redo())
      self.assertIn("Bonk", p.names("moves"))
      self.assertIsNone(p.validate())

   def test_trim_waits_for_commit(self) -> None:
      """!A rolled-back group trims nothing (HISTORY_LIMIT applies when the outermost group commits).
      @return None
      """
      doc = document.Document()
      with mock.patch.object(document, "HISTORY_LIMIT", SHORT_HISTORY):
         for k in range(SHORT_HISTORY):
            with doc.edit(f"step {k}"):
               doc.data["id"] = f"v{k}"
         undo = list(doc._undo)
         with self.assertRaises(ValueError):
            with document.group("Refused"):
               with doc.edit("one more"):
                  doc.data["id"] = "more"
               raise ValueError("refused")
         self.assertEqual(doc._undo, undo)
         self.assertEqual(doc.data["id"], f"v{SHORT_HISTORY - 1}")
         with document.group("Kept"):
            with doc.edit("kept"):
               doc.data["id"] = "kept"
         self.assertEqual(len(doc._undo), SHORT_HISTORY)
         self.assertEqual(doc._undo[-1][document.STEP_LABEL], "kept")


class SavedRecordsWarningTests(BattleTestCase):
   """!Removing or moving a passive slot warns about saved records' slot numbers (review2)."""

   def test_warning(self) -> None:
      """!The Starter's record holds a passive_selector: a move or removal warns, naming the slots that change; a
      move past the end warns nothing; the CLI refuses without --force and saves nothing.
      @return None
      """
      p = self.project
      names = passive_slots.slot_names(p.structure)
      with p.structure.edit("Add passive slot"):
         passive_slots.add_slot(p.structure, "veiled", False)
      moved = passive_slots.saved_records_warning(p.structure, "veiled", -1)
      self.assertIn("Saved creature records keep the slot number", moved)
      self.assertIn(repr(names[-1]), moved)
      self.assertIsNone(passive_slots.saved_records_warning(p.structure, "veiled", 1))
      removed = passive_slots.saved_records_warning(p.structure, names[0], None)
      self.assertIn(f"those of {names[0]!r} the passive of {names[1]!r}", removed)
      self.assertIn("first filled rolled slot's passive", removed)
      p.save_all()
      before = (self.dir / "structure.json").read_text(encoding="utf-8")
      err = io.StringIO()
      with redirect_stderr(err), redirect_stdout(io.StringIO()):
         status = cli(["battle", str(self.dir / "battle.json"), "passive-slot", "remove", "veiled"])
      self.assertEqual(status, 1)
      self.assertIn("--force", err.getvalue())
      self.assertEqual((self.dir / "structure.json").read_text(encoding="utf-8"), before)


class FirstSlotPassiveTests(unittest.TestCase):
   """!The pipelines page's default passive follows the engine's passive_for() (review2 N2)."""

   def test_empty_first_slot(self) -> None:
      """!A filled first slot gives its passive; an empty one the first filled rolled slot's, never a hidden one.
      @return None
      """
      none = pipelines._bc().NONE8
      compiled = {"passive_slots": [{"name": "hidden", "rolled": False}, {"name": "first", "rolled": True},
                                    {"name": "second", "rolled": True}]}
      self.assertEqual(pipelines.first_slot_passive(compiled, {"passives": [HIDDEN, none, SECOND]}), HIDDEN)
      compiled["passive_slots"].reverse()
      self.assertEqual(pipelines.first_slot_passive(compiled, {"passives": [none, FIRST, HIDDEN]}), FIRST)
      self.assertEqual(pipelines.first_slot_passive(compiled, {"passives": [none, none, HIDDEN]}), none)


class MalformedGeneratorsTests(BattleTestCase):
   """!A malformed reference compat/generators.json leaves the engine's generator (review2)."""

   def setUp(self) -> None:
      """!The copy, and a reference checkout whose generators manifest is malformed.
      @return None
      """
      super().setUp()
      self.ref = Path(tempfile.mkdtemp(prefix="capsule_badref_"))
      (self.ref / templates.REFERENCE_TEMPLATES).mkdir()
      (self.ref / bench.COMPAT_FOLDER).mkdir()
      (self.ref / bench.COMPAT_FOLDER / bench.tool().GENERATORS_FILE).write_text(BAD_GENERATORS, encoding="utf-8")
      self.env = mock.patch.dict(os.environ, {templates.REFERENCE_ENV: str(self.ref)})
      self.env.start()

   def tearDown(self) -> None:
      """!Removes the copies.
      @return None
      """
      self.env.stop()
      shutil.rmtree(self.ref, ignore_errors=True)
      super().tearDown()

   def test_default_generator(self) -> None:
      """!generators() raises; generators_or_default() gives the engine's generator and the problem;
      generator_source() of the default needs no manifest; the CLI lists the default and prints the error.
      @return None
      """
      with self.assertRaises(bench.BenchError):
         bench.generators(self.project)
      found, problem = bench.generators_or_default(self.project)
      self.assertEqual(list(found), [bench.DEFAULT_RNG])
      self.assertIn("generators[0]", problem)
      self.assertIsNone(bench.generator_source(self.project, bench.DEFAULT_RNG))
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         status = cli(["battle", str(self.dir / "battle.json"), "bench", "generators"])
      self.assertEqual(status, 1)
      self.assertIn(bench.DEFAULT_RNG, out.getvalue())
      self.assertIn("generators[0]", err.getvalue())


if __name__ == "__main__":
   unittest.main()
