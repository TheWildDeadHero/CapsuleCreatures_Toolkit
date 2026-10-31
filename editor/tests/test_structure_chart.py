#!/usr/bin/env python3
"""!Tests for capsule_studio.core.structure.chart (D-22 A6: the type chart's
tiers, combine mode, types per species, matchups) and the `battle FILE tier
...` / `battle FILE chart` commands. No Qt.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase).
"""
from __future__ import annotations

import copy
import io
import json
import math
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, pipelines  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import Document, DocumentError  # noqa: E402
from capsule_studio.core.structure import chart  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## The Starter's tiers in order.
SAMPLE_TIERS = ["none", "weak", "normal", "strong"]
## Q8 factor of x1.
Q8_ONE = 256
## Power-of-two factors for the sample's scaling tiers (x0.5, x2): what the exponent mode takes.
POWER_OF_TWO_Q8 = {"weak": 128, "strong": 512}


def power_of_two_tiers(structure: Document) -> None:
   """!Gives the sample's weak and strong tiers power-of-two factors (one edit), so the exponent mode compiles.
   @param structure  the structure Document
   @return None
   """
   with structure.edit("Powers of two"):
      for name, q8 in POWER_OF_TWO_Q8.items():
         chart.set_tier(structure, name, "q8", q8)


class ChartModelTests(BattleTestCase):
   """!Reading and editing the chart."""

   def test_tiers_and_options(self) -> None:
      """!The tiers with their kinds, factors, exponents and uses; the settings as the engine resolves them.
      @return None
      """
      doc = self.project.battle
      rows = chart.tier_list(doc)
      self.assertEqual([r["name"] for r in rows], SAMPLE_TIERS)
      weak = rows[1]
      q8 = battle.structure_doc(doc).data["chart"]["tiers"][1]["q8"]   # the sample's own factor
      exponent = math.log2(q8 / Q8_ONE)
      self.assertEqual((weak["kind"], weak["q8"], weak["factor"], weak["exponent"]),
                       ("scale", q8, q8 / Q8_ONE, int(exponent) if exponent.is_integer() else None))
      self.assertEqual((rows[0]["kind"], rows[0]["message"]), ("zero", "no_effect"))
      self.assertTrue(rows[2]["default"])
      cells = battle.structure_doc(doc).data["chart"]["matchups"]
      self.assertEqual(sum(r["uses"] for r in rows), sum(len(r) for r in cells.values()))
      o = chart.options(doc)
      self.assertEqual((o["combine"], o["default"], o["types_per_species"], o["added_types"], o["above"]),
                       ("multiply", "normal", 2, 1, "super_effective"))
      self.assertEqual(chart.matchup(doc, "Fire", "Bio"), "strong")
      self.assertEqual(chart.matchup(doc, "Fire", "Light"), "normal")
      self.assertEqual(chart.types_per_species(doc), 2)

   def test_add_rename_remove(self) -> None:
      """!A rename rewrites the cells and the default; a removal moves the cells to another tier; one undo step
      each.
      @return None
      """
      doc = self.project.structure   # its edits change the structure manifest (undo there)
      before = copy.deepcopy(doc.data)
      with doc.edit("Add"):
         self.assertEqual(chart.add_tier(doc, "triple", 768, index=4), 4)
      self.assertIsNone(self.project.validate())      # the multiply mode takes any factor
      with doc.edit("Combine"):
         chart.set_option(doc, "combine", "exponent")
      self.assertIsNotNone(self.project.validate())   # exponent mode: 768 is no power of two
      with doc.edit("Combine back"):
         chart.set_option(doc, "combine", "multiply")
      with doc.edit("Rename"):
         self.assertEqual(chart.rename_tier(doc, "strong", "double"), 16)
         chart.rename_tier(doc, "normal", "neutral")
      self.assertEqual(battle.structure_doc(doc).data["chart"]["default"], "neutral")
      self.assertEqual(chart.matchup(doc, "Fire", "Bio"), "double")
      with self.assertRaisesRegex(DocumentError, "16 cell"):
         chart.remove_tier(doc, "double")
      with doc.edit("Remove"):
         self.assertEqual(chart.remove_tier(doc, "double", "triple"), 16)
      self.assertEqual(chart.matchup(doc, "Fire", "Bio"), "triple")
      self.assertIsNone(self.project.validate())
      with doc.edit("Default goes"):
         chart.remove_tier(doc, "neutral", "weak")
      self.assertEqual(chart.default_tier(doc), "weak")
      # weak cells are the default now
      self.assertNotIn("weak", json.dumps(battle.structure_doc(doc).data["chart"]["matchups"]))
      while doc.undo():
         pass
      self.assertEqual(doc.data, before)
      for bad in (("normal", None, None), ("", None, None), ("x", 256, "zero"), ("x", 70000, None)):
         with self.assertRaises(DocumentError, msg=str(bad)):
            chart.add_tier(doc, bad[0], bad[1], bad[2])

   def test_set_tier(self) -> None:
      """!Kind, factor, message and shade; the engine's rules on decisive tiers.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Tier"):
         chart.add_tier(battle.structure_doc(doc), "ko", decisive="ko")
         chart.set_tier(doc, "strong", "q8", 1024)
         chart.set_tier(doc, "ko", "decisive", None)
         chart.set_tier(doc, "none", "message", None)
         chart.set_tier(doc, "weak", "shade", "#123456")
      self.assertEqual(chart.tier_entry(doc, "ko"), {"name": "ko", "q8": 256})
      self.assertNotIn("message", chart.tier_entry(doc, "none"))
      self.assertEqual(chart.tier_list(doc)[1]["shade"], "#123456")
      with doc.edit("Shade off"):
         chart.set_tier(doc, "weak", "shade", None)
      self.assertNotIn("editor", chart.tier_entry(doc, "weak"))
      for name, key, value in (("weak", "message", "no_effect"), ("none", "q8", 128), ("weak", "decisive", "x"),
                               ("weak", "shade", "red"), ("none", "message", "nothing"), ("weak", "name", "x")):
         with self.assertRaises(DocumentError, msg=f"{name} {key}"):
            chart.set_tier(doc, name, key, value)

   def test_options_and_types(self) -> None:
      """!Counts within the engine's limits; fewer types per species than a species has is refused.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Three"):
         chart.set_option(doc, "added_types", 0)
         chart.set_option(doc, "types_per_species", 3)
      self.assertIsNone(self.project.validate())
      with doc.edit("A third type"):
         battle.set_field(doc, "species", "Emberkit", "types", ["Fire", "Earth", "Wind"])
      self.assertIsNone(self.project.validate())
      with self.assertRaisesRegex(DocumentError, "Emberkit"):
         chart.set_option(doc, "types_per_species", 2)
      for key, value in (("types_per_species", 0), ("added_types", 1), ("combine", "add"), ("default", "x"),
                         ("above", "nothing"), ("colour", 1)):
         with self.assertRaises(DocumentError, msg=key):
            chart.set_option(doc, key, value)
      with doc.edit("Messages"):
         chart.set_option(doc, "above", None)
         chart.set_option(doc, "below", None)
      self.assertNotIn("messages", battle.structure_doc(doc).data["chart"])

   def test_cells_and_types(self) -> None:
      """!Cells name tiers; a multiplier means its tier; renaming / removing a type follows the matchups.
      @return None
      """
      doc = self.project.battle
      weak_factor = chart.tier_list(doc)[1]["factor"]   # the sample's weak tier, as a multiplier
      with doc.edit("Cells"):
         chart.set_matchup(doc, "Cosmic", "Fire", weak_factor)
         chart.set_matchup(doc, "Cosmic", "Water", 0)
         chart.set_matchup(doc, "Fire", "Bio", "normal")
      matchups = battle.structure_doc(doc).data["chart"]["matchups"]
      self.assertEqual(matchups["Cosmic"]["Fire"], "weak")
      self.assertEqual(matchups["Cosmic"]["Water"], "none")
      self.assertNotIn("Bio", matchups["Fire"])
      self.assertEqual(chart.step_tier(doc, "Cosmic", "Fire", 1), "normal")
      self.assertEqual(chart.step_tier(doc, "Cosmic", "Water", -1), "strong")   # below the first: the last
      with doc.edit("Type"):
         battle.rename_entry(doc, "types", "Cosmic", "Astral")
      self.assertEqual(chart.matchup(doc, "Astral", "Fire"), "weak")
      self.assertEqual(chart.matchup(doc, "Darkness", "Astral"), "weak")
      self.assertIsNone(self.project.validate())
      for bad in (("Astral", "Fire", 3), ("Astral", "Nothing", "weak"), ("Astral", "Fire", "triple")):
         with self.assertRaises(DocumentError, msg=str(bad)):
            chart.set_matchup(doc, *bad)

   def test_damage_follows_the_chart(self) -> None:
      """!The damage trace takes the target's tiers (run_pipeline types=): the Starter's type_scale() gives the
      same damage in the exponent mode (its factors are powers of two); a KO tier deals the target's HP.
      @return None
      """
      doc = self.project.battle
      steps = self.project.ruleset.data["pipelines"]["damage"]
      self.assertIn("type_scale(d)", [s.get("expr") for s in steps])
      power_of_two_tiers(self.project.structure)
      multiplied = pipelines.damage_trace(self.project, "Emberkit", "Sproutle", "Fireball").damage
      with doc.edit("Exponent"):
         chart.set_option(doc, "combine", "exponent")
      self.assertEqual(pipelines.damage_trace(self.project, "Emberkit", "Sproutle", "Fireball").damage, multiplied)
      with doc.edit("KO"):
         chart.add_tier(battle.structure_doc(doc), "ko", decisive="ko")
         chart.set_matchup(doc, "Fire", "Bio", "ko")
      t = pipelines.damage_trace(self.project, "Emberkit", "Sproutle", "Fireball")
      self.assertEqual((t.decisive, t.damage), ("ko", t.defender["hp"]))


class ChartCliTests(BattleTestCase):
   """!The `battle FILE tier ...` and `chart` commands."""

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
      """!list, add, set, option, rename, move, remove, chart; refused edits are not saved.
      @return None
      """
      b = self.dir / "battle.json"
      status, out = self.run_cli("battle", b, "tier", "list")
      self.assertEqual(status, 0)
      st = self.project.structure.data["chart"]
      cells = sum(1 for row in st["matchups"].values() for tier in row.values() if tier == "weak")
      self.assertIn(f"1 weak: q8 {st['tiers'][1]['q8']} (x", out)
      self.assertIn(f"; {cells} cell(s)", out)
      self.assertIn("combine multiply, default normal, types per species 2", out)
      self.assertEqual(self.run_cli("battle", b, "tier", "option", "combine", "exponent")[0], 1)   # x0.6: no power
      for name, q8 in POWER_OF_TWO_Q8.items():   # the exponent mode needs powers of two
         self.assertEqual(self.run_cli("battle", b, "tier", "set", name, "q8", q8)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "tier", "option", "combine", "exponent")[0], 0)
      status, out = self.run_cli("battle", b, "tier", "add", "third", "--q8", 85)
      self.assertEqual(status, 1)   # refused: 85 is no power of two, the exponent mode needs one
      self.assertIn("needs a power of two", out)
      self.assertNotIn("third", json.dumps(BattleProject.open(b).structure.data["chart"]))
      self.assertEqual(self.run_cli("battle", b, "tier", "option", "combine", "sequential")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "tier", "add", "third", "--q8", 85, "--at", 1)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "chart", "Fire", "Bio", "third")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "tier", "rename", "third", "feeble")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "tier", "set", "feeble", "shade", "#ff0000")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "tier", "move", "feeble", "up")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "tier", "set", "none", "message", "null")[0], 0)
      data = BattleProject.open(b).structure.data["chart"]
      self.assertEqual(data["tiers"][0], {"name": "feeble", "q8": 85, "editor": {"shade": "#ff0000"}})
      self.assertEqual(data["matchups"]["Fire"]["Bio"], "feeble")
      self.assertEqual(data["combine"], "sequential")
      self.assertEqual(self.run_cli("battle", b, "tier", "remove", "feeble")[0], 1)
      self.assertEqual(self.run_cli("battle", b, "tier", "remove", "feeble", "--to", "strong")[0], 0)
      self.assertEqual(battle.chart_value(BattleProject.open(b).battle, "Fire", "Bio"), "strong")
      self.assertEqual(self.run_cli("battle", b, "tier", "option", "types_per_species", 1)[0], 1)   # Starmote
      self.assertEqual(self.run_cli("battle", b, "tier", "option", "default", "weak")[0], 0)
      self.assertEqual(BattleProject.open(b).structure.data["chart"]["default"], "weak")


if __name__ == "__main__":
   unittest.main()
