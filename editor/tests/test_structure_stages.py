#!/usr/bin/env python3
"""!Tests for capsule_studio.core.structure.stages (D-22 A7: the manifest's
stages list) and the `battle FILE stage ...` / `battle FILE migrate`
commands. No Qt.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase).
"""
from __future__ import annotations

import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, codepage, logic  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import chart, stages  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## The Starter's stage names in index order (MP and EP have no stage).
SAMPLE_STAGES = ["accuracy", "evasion", "critical", "attack", "magic", "defence", "protection", "intelligence",
                 "agility"]
## Its stat stages.
STAT_STAGES = SAMPLE_STAGES[3:]
## Percent of x1 (the preview's third column).
PERCENT = 100
## The line of Mist Veil's logic that names the evasion stage.
MIST_VEIL_EVASION = "      stage user evasion 1;\n"


class StageModelTests(BattleTestCase):
   """!Reading and editing the stages."""

   def test_stage_list(self) -> None:
      """!Defaults resolved as the engine resolves them; names feed the effect logic's stage list.
      @return None
      """
      doc = self.project.battle
      rows = stages.stage_list(doc)
      self.assertEqual([r["name"] for r in rows], SAMPLE_STAGES)
      self.assertEqual(logic.name_lists(self.project)["stages"], SAMPLE_STAGES)
      crit, attack = rows[2], rows[3]
      self.assertEqual((crit["kind"], crit["label"], crit["range"], crit["mode"]), ("crit", "focus", (0, 3), "table"))
      self.assertEqual((attack["kind"], attack["stat"], attack["named"], attack["label"], attack["labelled"]),
                       ("stat", "attack", False, "Attack", False))
      self.assertEqual(rows[1]["mode"], "none")
      self.assertEqual(stages.crit_max(doc), 3)
      self.assertEqual(stages.max_stages(["gba"]), 3 + 10 - 1)

   def test_add_remove_move(self) -> None:
      """!Adding checks the engine's rules; one undo step each; removal is refused while logic names the stage.
      @return None
      """
      doc = self.project.battle
      with self.assertRaisesRegex(DocumentError, "Mist Veil"):
         stages.remove_stage(doc, "evasion")
      moves = self.project.effect_source("effects/moves.ceffect")
      with moves.edit("No evasion"):
         moves.data["text"] = moves.text.replace(MIST_VEIL_EVASION, "")
      before = copy.deepcopy(doc.data)
      with doc.edit("Remove"):
         stages.remove_stage(doc, "evasion")
      with self.assertRaisesRegex(DocumentError, "already a stage of kind accuracy"):
         stages.add_stage(doc, "accuracy")
      with doc.edit("Add"):
         at = stages.add_stage(doc, "evasion", name="dodge", rng=[-3, 3], index=1, label="dodging")
      self.assertEqual(at, 1)
      self.assertEqual(battle.structure_doc(doc).data["stages"][1],
                       {"name": "dodge", "kind": "evasion", "label": "dodging", "range": [-3, 3]})
      self.assertIsNone(self.project.validate())
      with doc.edit("Move"):
         self.assertTrue(stages.move_stage(doc, "dodge", 1))
      self.assertEqual(stages.stage_names(doc)[2], "dodge")
      self.assertFalse(stages.move_stage(doc, "accuracy", -1))
      for bad in ({"kind": "luck"}, {"kind": "stat", "stat": "hp"}, {"kind": "stat", "stat": "attack"},
                  {"kind": "crit"}, {"kind": "evasion", "stat": "attack"}, {"kind": "stat", "stat": "nothing"}):
         with self.assertRaises(DocumentError, msg=str(bad)):
            stages.add_stage(doc, bad["kind"], stat=bad.get("stat"))
      with self.assertRaisesRegex(DocumentError, "Dread Gaze"):
         stages.remove_stage(doc, "attack")
      while doc.undo():
         pass
      self.assertEqual(doc.data, before)

   def test_crit_stage_never(self) -> None:
      """!A new crit stage never hits (odds 0/1 at every value of its range); a ruleset reading the crit odds needs
      one, so it is not removed (S14 F9).
      @return None
      """
      doc = self.project.battle
      with self.assertRaisesRegex(DocumentError, "still needed by the ruleset.*no crit stage"):
         with doc.edit("No crit stage"):   # no logic names it, but the Starter's crit pipeline reads its odds
            stages.remove_stage(doc, "critical")
      self.assertIsNone(self.project.validate())
      fresh = BattleProject.create(self.dir / "fresh" / "battle.json", "fresh")   # the Blank: no stages
      with fresh.battle.edit("Crit"):
         stages.add_stage(fresh.battle, "crit", rng=[0, 2])
      self.assertEqual(stages.stage_entry(fresh.battle, "crit")["table"], ["0/1"] * 3)
      self.assertIsNone(fresh.validate())

   def test_rename_follows_logic(self) -> None:
      """!A rename follows the effect logic in one undo step (of the structure manifest, which it changes); a stat's
      stage named back after the stat goes back to the default.
      @return None
      """
      doc = self.project.structure
      before = copy.deepcopy(doc.data)
      source = self.project.effect_source("effects/moves.ceffect")
      with doc.edit("Rename"):
         n = stages.rename_stage(doc, "attack", "might")
      self.assertEqual(n, 1)   # Dread Gaze's logic
      self.assertEqual(stages.stage_entry(doc, "might"), {**stages.stat_stage(doc, "attack"), "name": "might"})
      self.assertIn("stage target might -1;", source.text)
      self.assertIsNone(self.project.validate())
      with doc.edit("Back"):
         stages.rename_stage(doc, "might", "attack")
      self.assertNotIn("name", stages.stat_stage(doc, "attack"))
      self.assertTrue(doc.undo())
      self.assertTrue(doc.undo())
      self.assertEqual(doc.data, before)
      self.assertIn("stage target attack -1;", source.text)
      with self.assertRaises(DocumentError):
         stages.rename_stage(doc, "attack", "defence")
      with self.assertRaises(DocumentError):
         stages.rename_stage(doc, "attack", "Bad")

   def test_set_range_table_formula(self) -> None:
      """!A range change fits the table; entries, modes and formulas follow the engine's rules.
      @return None
      """
      doc = self.project.battle
      table = stages.stat_stage(doc, "attack")["table"]
      lo = stages.stat_stage(doc, "attack")["range"][0]   # the sample's lowest stage: the table's first entry
      with doc.edit("Range"):
         for name in STAT_STAGES:
            stages.set_stage(doc, name, "range", [-2, 3])
      self.assertEqual(stages.stat_stage(doc, "attack")["table"], table[-2 - lo:3 - lo + 1])
      self.assertIsNone(self.project.validate())
      with doc.edit("Entry"):
         stages.set_entry(doc, "critical", 3, "1/1")
         stages.set_entry(doc, "evasion", 1, [4, 3])
      self.assertEqual(stages.stage_entry(doc, "critical")["table"][3], "1/1")
      evasion_lo = stages.stage_entry(doc, "evasion")["range"][0]
      self.assertEqual(stages.stage_entry(doc, "evasion")["table"][1 - evasion_lo], [4, 3])   # stage 1
      self.assertEqual(stages.stage_entry(doc, "evasion")["table"][0], [1, 1])
      self.assertIsNone(self.project.validate())
      for name, stage, value in (("critical", 4, "1/2"), ("critical", 1, "3/2"), ("attack", 0, "0/2"),
                                 ("attack", 0, "x")):
         with self.assertRaises(DocumentError, msg=f"{name} {stage} {value}"):
            stages.set_entry(doc, name, stage, value)
      with doc.edit("Label"):
         stages.set_stage(doc, "evasion", "label", "dodging")
         stages.set_stage(doc, "accuracy", "label", None)
      self.assertNotIn("label", stages.stage_entry(doc, "accuracy"))
      with self.assertRaisesRegex(DocumentError, "odds"):
         stages.set_mode(doc, "critical", "formula", "damage_base")
      with self.assertRaisesRegex(DocumentError, "not a named formula"):
         stages.set_mode(doc, "attack", "formula", "nothing", stages.formula_choices(self.project))
      with doc.edit("None"):
         stages.set_mode(doc, "evasion", "none")
      self.assertNotIn("table", stages.stage_entry(doc, "evasion"))
      for key, value in (("range", [1, 2]), ("range", [-16, 0]), ("stat", "defence"), ("kind", "stat"),
                         ("table", [[1, 1]])):
         with self.assertRaises(DocumentError, msg=key):
            stages.set_stage(doc, "attack" if key != "table" else "evasion", key, value)

   def test_preview(self) -> None:
      """!The preview is the engine's own evaluation of the compiled stage.
      @return None
      """
      doc = self.project.battle
      attack = stages.stat_stage(doc, "attack")   # the sample's own range and table
      rows = stages.preview(self.project, "attack")
      for row, (num, den), stage in ((rows[0], attack["table"][0], attack["range"][0]),
                                     (rows[-1], attack["table"][-1], attack["range"][1])):
         self.assertEqual(row[:2], (stage, f"x{num / den:.2f} ({num}/{den})"))
         self.assertEqual(row[2], str(num * PERCENT // den))
      crit = stages.stage_entry(doc, "critical")
      self.assertEqual(stages.preview(self.project, "critical")[0][:2], (crit["range"][0], crit["table"][0]))
      evasion = stages.stage_entry(doc, "evasion")
      self.assertEqual(stages.preview(self.project, "evasion")[0], (evasion["range"][0], "x1", "100"))
      with self.assertRaises(DocumentError):
         stages.preview(self.project, "nothing")

   def test_labels_are_texts(self) -> None:
      """!Stage labels are in-game texts the code page checks.
      @return None
      """
      uses = [use[0] for use in codepage._battle_texts(self.project.battle.path)]
      self.assertIn("battle: stage critical label", uses)

   def test_migrate(self) -> None:
      """!Pre-E6a data (rules tables, stage_names, a stat's stage flag; a {attacker: {defender: x}} chart) migrates
      to data the engine compiles.
      @return None
      """
      doc = self.project.battle
      d = self.project.structure.data
      # the pre-E6a engine's fixed ranges: the sample's tables padded at both ends to fill them
      table = old_table(stages.stat_stage(doc, "attack")["table"], stages.old_range("stat"))
      acc = old_table(stages.stage_entry(doc, "accuracy")["table"], stages.old_range("accuracy"))
      crit = stages.stage_entry(doc, "critical")["table"]
      old_chart = {a: {dn: {"weak": 0.5, "strong": 2, "none": 0}[t] for dn, t in row.items()}
                   for a, row in d["chart"]["matchups"].items()}
      with doc.edit("Old"):
         del d["stages"]
         doc.data["stage_names"] = {"accuracy": "accuracy", "evasion": "evasiveness", "critical": "focus"}
         # before E6a the crit odds had five entries (stages 0 to 4)
         d["rules"].update({"stat_stages": table, "accuracy_stages": acc, "crit_odds": crit + crit[-1:]})
         for stat in ("mp", "ep", "magic"):   # pre-E6a: every stat but the pool stat had a stage unless flagged
            next(st for st in d["stats"] if st["name"] == stat)["stage"] = False
         d["chart"] = old_chart
      self.assertIsNotNone(self.project.validate())
      self.assertTrue(stages.needs_migration(battle.merged(doc)) and chart.needs_migration(d))
      with doc.edit("Migrate"):
         self.assertTrue(stages.migrate(doc))
         self.assertTrue(chart.migrate(doc))
      self.assertFalse(stages.migrate(doc))
      self.assertIsNone(self.project.validate())
      self.assertEqual(stages.stage_names(doc), [n for n in SAMPLE_STAGES if n != "magic"])
      self.assertEqual(stages.stage_entry(doc, "evasion")["label"], "evasiveness")
      self.assertEqual(chart.matchup(doc, "Fire", "Bio"), "twice")   # the migrated chart names tiers by factor


def old_table(table: list, old: tuple[int, int]) -> list:
   """!A stage table padded at both ends (its first and last entries repeated) to fill a wider range.
   @param table  the table, lowest stage first
   @param old    the wider range (lo, hi)
   @return the padded table
   """
   pad = (old[1] - old[0] + 1 - len(table)) // 2
   return [table[0]] * pad + list(table) + [table[-1]] * pad


class StageCliTests(BattleTestCase):
   """!The `battle FILE stage ...` commands."""

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
      """!list, add, set, mode, entry, rename, move, preview, remove; refused edits are not saved.
      @return None
      """
      b = self.dir / "battle.json"
      status, out = self.run_cli("battle", b, "stage", "list")
      self.assertEqual(status, 0)
      crit = stages.stage_entry(self.project.battle, "critical")   # the sample's own odds
      self.assertIn(f"2 critical: crit, label 'focus', range {crit['range']}, table {' '.join(crit['table'])}", out)
      self.assertTrue(out.endswith("9/12 stages\n"))
      self.assertEqual(self.run_cli("battle", b, "stage", "remove", "evasion")[0], 1)   # Mist Veil names it
      moves = self.dir / "effects" / "moves.ceffect"
      moves.write_text(moves.read_text(encoding="utf-8").replace(MIST_VEIL_EVASION, ""), encoding="utf-8")
      self.assertEqual(self.run_cli("battle", b, "stage", "remove", "evasion")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stage", "add", "evasion", "--name", "dodge", "--range", -3, 3,
                                    "--at", 1)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stage", "set", "dodge", "label", "Dodge")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stage", "entry", "dodge", 2, "5/3")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stage", "entry", "critical", 0, "1/24")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stage", "rename", "dodge", "evade")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stage", "move", "evade", "down")[0], 0)
      data = battle.merged(BattleProject.open(b).battle)
      self.assertEqual(data["stages"][2], {"name": "evade", "kind": "evasion", "range": [-3, 3], "label": "Dodge",
                                           "table": [[1, 1]] * 5 + [[5, 3], [1, 1]]})
      self.assertEqual(data["stages"][1]["table"][0], "1/24")
      status, out = self.run_cli("battle", b, "stage", "preview", "critical")
      self.assertIn("0 1/24: 4.17 %", out)
      self.assertEqual(self.run_cli("battle", b, "stage", "mode", "evade", "none")[0], 0)
      self.assertNotIn("table", BattleProject.open(b).structure.data["stages"][2])
      # the Starter's ruleset scales each stat by its own stage (stage_scale(offense_stage_id, ...)): a stat stage
      # may have a range of its own (the table follows the range).
      self.assertEqual(self.run_cli("battle", b, "stage", "set", "attack", "range", "[-2, 2]")[0], 0)
      self.assertEqual(BattleProject.open(b).structure.data["stages"][3]["range"], [-2, 2])
      self.assertEqual(self.run_cli("battle", b, "stage", "remove", "attack")[0], 1)
      self.assertEqual(self.run_cli("battle", b, "stat", "stages", "evade", "evading")[0], 0)
      status, out = self.run_cli("battle", b, "stat", "stages")
      self.assertIn("2 evade: evading", out)

   def test_migrate_command(self) -> None:
      """!`battle FILE migrate` turns old data into new and saves it; nothing to do the second time.
      @return None
      """
      b = self.dir / "battle.json"
      st = self.dir / "structure.json"
      data = json.loads(b.read_text(encoding="utf-8"))
      structure = json.loads(st.read_text(encoding="utf-8"))
      data["stage_names"] = {k: k for k in ("accuracy", "evasion", "critical")}   # a retired key: in the content
      structure["rules"]["crit_odds"] = ["0/1"] * 5
      del structure["stages"]
      b.write_text(json.dumps(data), encoding="utf-8")
      st.write_text(json.dumps(structure), encoding="utf-8")
      status, out = self.run_cli("battle", b, "migrate")
      self.assertEqual((status, out.strip()), (0, "migrated: stages"))
      self.assertIsNone(BattleProject.open(b).validate())
      self.assertEqual(self.run_cli("battle", b, "migrate")[1].strip(), "nothing to migrate")


if __name__ == "__main__":
   unittest.main()
