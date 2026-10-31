#!/usr/bin/env python3
"""!Tests for capsule_studio.core.structure.passive_slots (D-25 decision 6,
engine C1: the structure manifest's passive_slots), what follows them
(species' passives, party members' slots, bench scenario members) and the
`battle FILE passive-slot ...` commands. No Qt.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase): the
slot names and counts are read from the sample's structure.json, so a
re-tuned Starter needs few test edits.
"""
from __future__ import annotations

import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, bench, engine  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import passive_slots, record  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402


class PassiveSlotModelTests(BattleTestCase):
   """!Reading, adding, renaming, moving and removing passive slots."""

   def given(self) -> list[str]:
      """!The slot names the sample states.
      @return names
      """
      return [e["name"] for e in self.project.structure.data["passive_slots"]]

   def species_with(self, i: int) -> list[str]:
      """!The species with a passive in slot i.
      @param i  slot index
      @return names
      """
      return [s["name"] for s in battle.entries(self.project.battle, "species")
              if len(s.get("passives") or []) > i and s["passives"][i] is not None]

   def test_rows_and_budget(self) -> None:
      """!The sample's slots as the engine reads them; the budget names the engine's most and the selector role.
      @return None
      """
      doc = self.project.structure
      names = self.given()
      self.assertTrue(passive_slots.is_stated(doc))
      self.assertEqual(passive_slots.slot_names(doc), names)
      rows = passive_slots.slot_rows(doc)
      self.assertEqual([r["name"] for r in rows], names)
      self.assertEqual(rows[0]["species"], len(self.species_with(0)))
      bc = engine.tool("battle_compiler")
      self.assertEqual(passive_slots.compile_check(doc)[1], None)
      most = passive_slots.max_slots(["gba"])
      self.assertEqual(most, engine.tool("build_settings").platform_limits("gba")["max_passive_slots"])
      self.assertIn(f"{len(names)}/{most} passive slots", passive_slots.budget_text(doc))
      self.assertIsNotNone(passive_slots.selector_max(doc))
      # without the key: the engine's default slots
      with doc.edit("Drop"):
         doc.data.pop("passive_slots")
      self.assertFalse(passive_slots.is_stated(doc))
      self.assertEqual(passive_slots.slot_names(doc), [e["name"] for e in bc.DEFAULT_PASSIVE_SLOTS])
      self.assertIn("the engine's default", "\n".join(passive_slots.lines(doc)))

   def test_add_rename_move_remove_follow(self) -> None:
      """!Species' passives and members' slots follow every edit; each is one undo step of both manifests.
      @return None
      """
      doc, content = self.project.structure, self.project.battle
      names = self.given()
      first = names[0]
      # a member naming the second slot by name, one by number
      with content.edit("Members"):
         members = battle.entries(content, "parties")[0]["members"]
         members[0]["passive"] = names[1]
         members[1]["passive"] = 1
      before_s, before_c = copy.deepcopy(doc.data), copy.deepcopy(content.data)
      sp = self.species_with(1)
      self.assertTrue(sp, "the sample has a species with a second passive")
      second_of = {n: battle.entry(content, "species", n)["passives"][1] for n in sp}
      # add a slot first: the passives after it move one place
      with doc.edit("Add"):
         self.assertEqual(passive_slots.add_slot(doc, "veiled", False, 0), 0)
      self.assertEqual(passive_slots.slot_names(doc), ["veiled"] + names)
      self.assertEqual(doc.data["passive_slots"][0], {"name": "veiled", "rolled": False})
      for n in sp:
         self.assertEqual(battle.entry(content, "species", n)["passives"][2], second_of[n])
      self.assertEqual((members[0]["passive"], members[1]["passive"]), (names[1], 2))
      self.assertIsNone(self.project.error_now())
      doc.undo()
      self.assertEqual((doc.data, content.data), (before_s, before_c))   # one step, both files
      # rename: the member naming it follows
      with doc.edit("Rename"):
         self.assertEqual(passive_slots.rename_slot(doc, names[1], "extra"), 1)
      members = battle.entries(content, "parties")[0]["members"]
      self.assertEqual(members[0]["passive"], "extra")
      # move it up: the species' passives and the numbered member swap with it
      first_of = {n: battle.entry(content, "species", n)["passives"][0] for n in sp}
      with doc.edit("Move"):
         self.assertTrue(passive_slots.move_slot(doc, "extra", -1))
      self.assertEqual(passive_slots.slot_names(doc)[:2], ["extra", first])
      for n in sp:
         self.assertEqual(battle.entry(content, "species", n)["passives"][:2], [second_of[n], first_of[n]])
      self.assertEqual(members[1]["passive"], 0)
      self.assertIsNone(self.project.error_now())
      # remove it: its place goes, the members having it fall back to the first slot
      with doc.edit("Remove"):
         lost = passive_slots.remove_slot(doc, "extra")
      self.assertIn(f"species {sp[0]}", lost)
      self.assertNotIn("passive", members[0])
      self.assertNotIn("passive", members[1])
      for n in sp:
         self.assertEqual(battle.entry(content, "species", n)["passives"][:1], [first_of[n]])
      self.assertIsNone(self.project.error_now())

   def test_refusals(self) -> None:
      """!Bad names, taken names, the engine's most, the last slot, a too-narrow passive_selector role.
      @return None
      """
      doc = self.project.structure
      names = self.given()
      for bad in ("Bad", "two words", "", 3):
         with self.assertRaises(DocumentError), doc.edit("Bad"):
            passive_slots.add_slot(doc, bad)
      with self.assertRaisesRegex(DocumentError, "already"), doc.edit("Taken"):
         passive_slots.add_slot(doc, names[0])
      most = passive_slots.max_slots()
      with doc.edit("Fill"):
         for k in range(most - len(names)):
            passive_slots.add_slot(doc, f"extra{k}")
      with self.assertRaisesRegex(DocumentError, "at most"), doc.edit("Full"):
         passive_slots.add_slot(doc, "one_more")
      with doc.edit("Back"):
         for k in range(most - len(names)):
            passive_slots.remove_slot(doc, f"extra{k}")
      with doc.edit("To one"):
         for n in names[1:]:
            passive_slots.remove_slot(doc, n)
      with self.assertRaisesRegex(DocumentError, "at least one"), doc.edit("Last"):
         passive_slots.remove_slot(doc, names[0])
      # a passive_selector role one bit wide holds slots 0-1: a third slot is refused with the engine's message
      with doc.edit("Narrow"):
         record.set_role(doc, passive_slots.SELECTOR_ROLE, "width", 1)
         passive_slots.add_slot(doc, "second")
      self.assertIsNone(self.project.error_now())
      with self.assertRaisesRegex(DocumentError, "passive_selector"), doc.edit("Third"):
         passive_slots.add_slot(doc, "third")
      self.assertNotIn("third", passive_slots.slot_names(doc))

   def test_rolled(self) -> None:
      """!The rolled flag is written only when it differs from the engine's default.
      @return None
      """
      doc = self.project.structure
      name = self.given()[0]
      with doc.edit("Fixed"):
         passive_slots.set_rolled(doc, name, False)
      self.assertEqual(doc.data["passive_slots"][0], {"name": name, "rolled": False})
      with doc.edit("Rolled"):
         passive_slots.set_rolled(doc, name, True)
      self.assertEqual(doc.data["passive_slots"][0], {"name": name})
      with self.assertRaises(DocumentError), doc.edit("Bad"):
         passive_slots.set_rolled(doc, name, "yes")


class PassiveSlotBenchTests(BattleTestCase):
   """!Saved bench scenarios: members' passive_slot numbers follow; validate() checks them."""

   def test_bench_members_follow(self) -> None:
      """!A move renumbers a scenario's member; one past the last slot is reported.
      @return None
      """
      doc = self.project.structure
      names = passive_slots.slot_names(doc)
      folder = self.dir / bench.SCENARIO_FOLDER
      folder.mkdir()
      species = battle.entries(self.project.battle, "species")[0]["name"]
      scenario = {"schema": bench.SCHEMA, "name": "slots", "seed": bench.DEFAULT_SEED, "parties": [
         {"side": 0, "controller": "human", "members": [{"species": species, "level": 5, "passive_slot": 1}]},
         {"side": 1, "members": [{"species": species, "level": 5}]}]}
      path = folder / "slots.json"
      path.write_text(json.dumps(scenario), encoding="utf-8")
      self.assertEqual(bench.validate(scenario, self.project), [])
      with doc.edit("Move"):
         passive_slots.move_slot(doc, names[1], -1)
      member = self.project.scenario(path).data["parties"][0]["members"][0]
      self.assertEqual(member["passive_slot"], 0)
      doc.undo()
      self.assertEqual(self.project.scenario(path).data["parties"][0]["members"][0]["passive_slot"], 1)
      too_far = copy.deepcopy(scenario)
      too_far["parties"][0]["members"][0]["passive_slot"] = len(names)
      problems = bench.validate(too_far, self.project)
      self.assertEqual(len(problems), 1)
      self.assertIn("passive_slot: 0 to", problems[0])


class PassiveSlotCliTests(BattleTestCase):
   """!`battle FILE passive-slot ...`."""

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command.
      @param argv  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()

   def test_commands(self) -> None:
      """!list, add, rename, move, rolled, remove; refusals exit 1 and save nothing.
      @return None
      """
      b = self.dir / "battle.json"
      names = passive_slots.slot_names(self.project.structure)
      status, out = self.run_cli("battle", b, "passive-slot", "list")
      self.assertEqual(status, 0)
      self.assertIn(f"0 {names[0]}: rolled", out)
      self.assertEqual(self.run_cli("battle", b, "passive-slot", "add", "veiled", "--fixed")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "passive-slot", "rename", "veiled", "secret")[0], 0)
      # saved records keep their slot numbers (C4): move and remove want --force
      err = io.StringIO()
      with redirect_stderr(err):
         self.assertEqual(self.run_cli("battle", b, "passive-slot", "move", "secret", "up")[0], 1)
      self.assertIn("Saved creature records keep the slot number", err.getvalue())
      self.assertEqual(self.run_cli("battle", b, "passive-slot", "move", "secret", "up", "--force")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "passive-slot", "rolled", "secret", "on")[0], 0)
      st = json.loads((self.dir / "structure.json").read_text(encoding="utf-8"))
      self.assertEqual([e["name"] for e in st["passive_slots"]], names[:-1] + ["secret", names[-1]])
      self.assertEqual(self.run_cli("battle", b, "passive-slot", "remove", "secret")[0], 1)
      self.assertEqual(self.run_cli("battle", b, "passive-slot", "remove", "secret", "--force")[0], 0)
      before = (self.dir / "structure.json").read_text(encoding="utf-8")
      self.assertEqual(self.run_cli("battle", b, "passive-slot", "add", "Bad")[0], 1)
      self.assertEqual(self.run_cli("battle", b, "passive-slot", "move", names[0], "up")[0], 1)
      self.assertEqual((self.dir / "structure.json").read_text(encoding="utf-8"), before)


if __name__ == "__main__":
   unittest.main()
