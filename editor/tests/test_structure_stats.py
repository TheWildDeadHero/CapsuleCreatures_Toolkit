#!/usr/bin/env python3
"""!Tests for capsule_studio.core.structure.stats (D-20 C: the manifest's
stats and their stages, the platform limits, the project's targets) and the
`battle FILE stat ...` / `battle FILE validate --platform` commands. No Qt.

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
from capsule_studio.core import battle  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import stages, stats  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402


def write_project(folder: Path, targets: object | None) -> Path:
   """!Makes a folder a game: reference/project.json, with targets when given.
   @param folder   the game folder
   @param targets  the "targets" value, or None for none
   @return the project.json
   """
   (folder / "reference").mkdir(parents=True, exist_ok=True)
   data = {"schema": "capsule.project/1", "name": "t", "rom": {"title": "T", "code": "CXXX", "maker": "00"},
           "sources": []}
   if targets is not None:
      data["targets"] = targets
   path = folder / "reference" / "project.json"
   path.write_text(json.dumps(data), encoding="utf-8")
   return path


## The Starter's stats in record order.
STARTER_STATS = ["hp", "mp", "ep", "attack", "magic", "defence", "protection", "intelligence", "agility"]


class StatModelTests(BattleTestCase):
   """!The stats list and the edits that migrate what depends on it."""

   def test_stat_list(self) -> None:
      """!Flags resolved as the engine resolves them; stage indices follow the fixed stages.
      @return None
      """
      rows = stats.stat_list(self.project.battle)
      self.assertEqual([r["name"] for r in rows], STARTER_STATS)
      self.assertEqual(battle.stat_keys(self.project.battle), [r["name"] for r in rows])
      hp, agility = rows[0], rows[-1]
      self.assertEqual((hp["pool"], hp["stage"], hp["trait"], hp["stage_index"]), (True, False, False, None))
      self.assertEqual((agility["order"], agility["stage"], agility["stage_index"]), (True, True, 8))
      # MP and EP (pools of resources, D-25) have no stage and no trait; attack's stage follows the fixed three
      self.assertEqual([(r["stage"], r["trait"]) for r in rows[1:3]], [(False, False), (False, False)])
      self.assertEqual(rows[3]["stage_index"], 3)
      self.assertEqual((hp["label"], hp["short"]), ("HP", None))
      self.assertEqual(rows[3]["transfer"], "attack")
      self.assertEqual(battle.stat_keys(), [st["name"] for st in battle.NEW_STRUCTURE["stats"]])

   def test_add_in_one_undo(self) -> None:
      """!Adding a stat inserts every species' base value; one undo takes it all back.
      @return None
      """
      doc = self.project.battle
      before = copy.deepcopy(doc.data)
      with doc.edit("Add stat"):
         i = stats.add_stat(doc, "luck", "Luck", index=3, base=7)
      self.assertEqual(i, 3)
      self.assertEqual(stats.stat_names(doc)[3], "luck")
      self.assertEqual(stats.stat_entry(doc, "luck")["formula"], "reserve")   # the first non-pool stat's (MP's)
      for sp in doc.data["species"]:
         self.assertEqual(len(sp["base"]), len(STARTER_STATS) + 1)
         self.assertEqual(sp["base"][3], 7)
      self.assertIsNone(self.project.validate())
      self.assertEqual(len(self.project.stats("Emberkit", 5)), len(STARTER_STATS) + 1)
      self.assertTrue(doc.undo())
      self.assertEqual(doc.data, before)
      with self.assertRaises(DocumentError):
         stats.add_stat(doc, "attack")              # taken
      with self.assertRaises(DocumentError):
         stats.add_stat(doc, "Luck")                # not a lower-case identifier
      with self.assertRaises(DocumentError):
         stats.add_stat(doc, "critical")            # its stage would take the crit stage's name
      with self.assertRaises(DocumentError):
         stats.add_stat(doc, "luck", shiny=True)    # unknown flag

   def test_one_of_flags(self) -> None:
      """!A new pool or order stat takes the flag off the others; the only holder can't drop it.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Order"):
         stats.add_stat(doc, "pace", order=True)
      self.assertEqual([r["name"] for r in stats.stat_list(doc) if r["order"]], ["pace"])
      with self.assertRaisesRegex(DocumentError, "order stat"):
         stats.set_stat(doc, "pace", "order", False)
      with doc.edit("Order back"):
         stats.set_stat(doc, "agility", "order", True)
      self.assertEqual([r["name"] for r in stats.stat_list(doc) if r["order"]], ["agility"])
      self.assertIsNone(self.project.validate())

   def test_remove(self) -> None:
      """!Removal takes the base column and trait references; refused for the pool / order stats and stats a
      category or a stage effect names.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Luck"):
         stats.add_stat(doc, "luck")
         battle.entry(doc, "traits", "Even")["up"] = "luck"
      with doc.edit("Remove"):
         stats.remove_stat(doc, "luck")
      self.assertNotIn("up", battle.entry(doc, "traits", "Even"))
      self.assertTrue(all(len(sp["base"]) == len(STARTER_STATS) for sp in doc.data["species"]))
      self.assertIsNone(self.project.validate())
      for name, pattern in (("hp", "pool stat"), ("agility", "order stat"), ("magic", "category elemental"),
                            ("nothing", "no stat")):
         with self.assertRaisesRegex(DocumentError, pattern, msg=name):
            stats.remove_stat(doc, name)
      with self.assertRaisesRegex(DocumentError, "move Dread Gaze"):   # its logic lowers the attack stage
         stats.remove_stat(doc, "attack")

   def test_move(self) -> None:
      """!Moving a stat moves every species' base value with it.
      @return None
      """
      doc = self.project.battle
      base = list(battle.entry(doc, "species", "Emberkit")["base"])
      before = sorted(self.project.stats("Emberkit", 5))
      with doc.edit("Move"):
         self.assertTrue(stats.move_stat(doc, "agility", -1))
      self.assertEqual(stats.stat_names(doc), STARTER_STATS[:7] + ["agility", "intelligence"])
      self.assertEqual(battle.entry(doc, "species", "Emberkit")["base"], base[:7] + [base[8], base[7]])
      self.assertFalse(stats.move_stat(doc, "hp", -1))
      self.assertIsNone(self.project.validate())
      self.assertEqual(sorted(self.project.stats("Emberkit", 5)), before)   # the same values, moved

   def test_rename(self) -> None:
      """!Renaming follows categories, traits and stat_stage effects, in one undo step.
      @return None
      """
      doc = self.project.battle
      before = copy.deepcopy(doc.data)
      with doc.edit("Rename"):
         n = stats.rename_stat(doc, "attack", "power")
      # physical's offense, Fierce up and Mystic down, Dread Gaze's logic (one per owner); G4: Drill Notes' `train`
      # logic and the training's yield key
      self.assertEqual(n, 6)
      logic_text = "".join(s.text for s in self.project.effects.values())
      self.assertNotIn("stage target attack", logic_text)
      self.assertIn("stage target power -1;", logic_text)
      # The old name stays only as the pinned transfer key.
      self.assertEqual(stats.stat_entry(doc, "power")["transfer"], "attack")
      text = json.dumps(battle.merged(doc))
      self.assertEqual(text.count('"attack"'), 1)
      self.assertEqual(battle.structure_doc(doc).data["categories"][0]["offense"], "power")
      self.assertEqual(battle.entry(doc, "traits", "Fierce")["up"], "power")
      self.assertIsNone(self.project.validate())
      self.assertTrue(doc.undo())
      self.assertEqual(doc.data, before)
      # The linked source edits are undone with the manifest's step.
      self.assertIn("stage target attack -1;", self.project.effect_source("effects/moves.ceffect").text)
      self.assertIsNone(self.project.validate())
      self.assertEqual(stats.rename_stat(doc, "attack", "attack"), 0)
      with self.assertRaises(DocumentError):
         stats.rename_stat(doc, "attack", "defence")

   def test_rename_pins_transfer(self) -> None:
      """!A rename keeps the stat's transfer key: the old name is pinned when the stat had none, an own key
      stays, and renaming back to the key drops it again (the default); the data compiles throughout.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Rename"):
         stats.rename_stat(doc, "agility", "pace")
      self.assertEqual(stats.stat_list(doc)[8]["transfer"], "agility")
      self.assertIsNone(self.project.validate())
      compiled, _error = self.project.compile()
      self.assertEqual(compiled["stats"][8]["transfer"], "agility")
      with doc.edit("Again"):
         stats.rename_stat(doc, "pace", "tempo")
      self.assertEqual(stats.stat_entry(doc, "tempo")["transfer"], "agility")   # the first key stays
      with doc.edit("Back"):
         stats.rename_stat(doc, "tempo", "agility")
      self.assertNotIn("transfer", stats.stat_entry(doc, "agility"))
      with doc.edit("Own key"):
         stats.set_stat(doc, "defence", "transfer", "guard")
         stats.rename_stat(doc, "defence", "shell")
      self.assertEqual(stats.stat_entry(doc, "shell")["transfer"], "guard")
      self.assertTrue(doc.undo())
      self.assertEqual(stats.stat_entry(doc, "defence").get("transfer"), None)
      self.assertIsNone(self.project.validate())

   def test_transfer_key_clash(self) -> None:
      """!A new stat named like another stat's pinned transfer key, or a transfer key another stat uses, is
      refused at once (the battle compiler would refuse it later: "a key no other stat uses").
      @return None
      """
      doc = self.project.battle
      with doc.edit("Rename"):
         stats.rename_stat(doc, "agility", "pace")                    # "agility" is pinned as pace's key
      self.assertEqual(stats.transfer_key_holder(doc, "agility"), "pace")
      before = copy.deepcopy(doc.data)
      refused = [
         lambda: stats.add_stat(doc, "agility"),                       # a new stat's key is its name
         lambda: stats.set_stat(doc, "hp", "transfer", "agility"),     # pace's key
         lambda: stats.set_stat(doc, "hp", "transfer", "attack"),      # attack's (its name)
      ]
      for i, fn in enumerate(refused):
         with self.assertRaises(DocumentError, msg=str(i)) as raised:
            with doc.edit("Refused"):
               fn()
         self.assertIn("'pace'" if i < 2 else "'attack'", str(raised.exception))
         self.assertEqual(doc.data, before, i)
      with doc.edit("Rename to the key"):
         stats.rename_stat(doc, "pace", "agility")                    # its own key: allowed (the pin is dropped)
      self.assertIsNone(stats.transfer_key_holder(doc, "agility", "agility"))
      with doc.edit("A renamed stat keeps its key"):
         stats.rename_stat(doc, "defence", "guard")
         stats.rename_stat(doc, "magic", "defence")   # magic pins "magic"; guard keeps "defence"
      self.assertEqual([r["transfer"] for r in stats.stat_list(doc)][4:7], ["magic", "defence", "protection"])

   def test_set(self) -> None:
      """!Labels, formulas, flags, transfer keys and the editor's abbreviation; None puts defaults back.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Set"):
         stats.set_stat(doc, "attack", "label", "Might")
         stats.set_stat(doc, "attack", "short", "Mi")
         stats.set_stat(doc, "attack", "transfer", "strength")
         stats.set_stat(doc, "protection", "trait", False)
      row = stats.stat_list(doc)[3]
      self.assertEqual((row["label"], row["short"], row["transfer"]), ("Might", "Mi", "strength"))
      self.assertEqual(stats.stat_entry(doc, "attack")["editor"], {"short": "Mi"})
      # Fierce lowers protection: protection must keep the trait flag
      self.assertIn("trait flag", self.project.validate())
      with doc.edit("Defaults"):
         stats.set_stat(doc, "attack", "short", None)
         stats.set_stat(doc, "attack", "transfer", None)
         stats.set_stat(doc, "protection", "trait", None)
      self.assertNotIn("editor", stats.stat_entry(doc, "attack"))
      self.assertIsNone(self.project.validate())
      for key, value in (("name", "x"), ("formula", None), ("label", ""), ("stage", "yes")):
         with self.assertRaises(DocumentError, msg=key):
            stats.set_stat(doc, "attack", key, value)
      with self.assertRaisesRegex(DocumentError, "no stat formula 'nowhere'"):   # checked at once (S14 F12)
         with doc.edit("Formula"):
            stats.set_stat(doc, "attack", "formula", "nowhere")
      self.assertIsNone(self.project.validate())

   def test_stage_flag(self) -> None:
      """!A stat has a stage when "stages" lists one (E6a): the flag adds or removes it; a new stat's stage
      copies the table the stat stages share; renaming and removing a stat follow its stage.
      @return None
      """
      doc = self.project.battle
      self.assertNotIn("stage", json.dumps(battle.structure_doc(doc).data["stats"]))
      with doc.edit("Luck"):
         stats.add_stat(doc, "luck")
      luck = stages.stat_stage(doc, "luck")
      self.assertEqual(luck["table"], stages.stat_stage(doc, "attack")["table"])
      self.assertEqual(stages.stage_names(doc)[-1], "luck")
      self.assertIsNone(self.project.validate())
      with doc.edit("Rename"):
         stats.rename_stat(doc, "luck", "fortune")
      self.assertEqual(stages.stat_stage(doc, "fortune")["stat"], "fortune")
      self.assertNotIn("name", stages.stat_stage(doc, "fortune"))
      with doc.edit("No stage"):
         stats.set_stat(doc, "fortune", "stage", False)
      self.assertIsNone(stages.stat_stage(doc, "fortune"))
      self.assertFalse(next(r for r in stats.stat_list(doc) if r["name"] == "fortune")["stage"])
      with doc.edit("Stage again"):
         stats.set_stat(doc, "fortune", "stage", None)   # the default: every stat but the pool stat has one
      self.assertEqual(next(r for r in stats.stat_list(doc) if r["name"] == "fortune")["stage_index"], 9)
      with doc.edit("Remove"):
         stats.remove_stat(doc, "fortune")
      self.assertIsNone(stages.stat_stage(doc, "fortune"))
      self.assertIsNone(self.project.validate())
      with self.assertRaisesRegex(DocumentError, "pool stat"):
         stats.set_stat(doc, "hp", "stage", True)
      with self.assertRaisesRegex(DocumentError, "has a stage"):
         stats.set_stat(doc, "attack", "pool", True)
      # Dread Gaze's logic lowers the attack stage: it can't go.
      with self.assertRaisesRegex(DocumentError, "Dread Gaze"):
         stats.set_stat(doc, "attack", "stage", False)


class LimitTests(BattleTestCase):
   """!The engine's platform limits and the game's targets."""

   def test_engine_limits(self) -> None:
      """!10 stats on the GBA, 32 elsewhere (the engine's build_settings); unknown platforms are refused.
      @return None
      """
      self.assertEqual(stats.max_stats("gba"), 10)
      self.assertEqual(stats.max_stats("desktop"), 32)
      self.assertEqual(stats.max_stats(), 10)
      self.assertEqual(stats.stat_limit(["gba", "desktop"]), 10)
      self.assertIn("gba", stats.platforms())
      with self.assertRaises(DocumentError):
         stats.max_stats("toaster")
      self.assertEqual(stats.stat_budget(self.project.battle, ["gba", "desktop"]), [("gba", 9, 10),
                                                                                    ("desktop", 9, 32)])
      self.assertEqual(stats.stats_report(self.project.battle)[-1], "9/10 gba")

   def test_targets(self) -> None:
      """!A game's targets come from its project.json; none or no game: the GBA.
      @return None
      """
      battle_json = self.dir / "data" / "battle.json"
      self.assertEqual(stats.project_targets(battle_json), ["gba"])
      write_project(self.dir, None)
      self.assertEqual(stats.project_targets(battle_json), ["gba"])
      write_project(self.dir, ["desktop", "gba", "desktop"])
      self.assertEqual(stats.project_targets(battle_json), ["desktop", "gba"])
      for bad in (["toaster"], [], "gba"):
         write_project(self.dir, bad)
         with self.assertRaises(DocumentError, msg=bad):
            stats.project_targets(battle_json)

   def test_full_list(self) -> None:
      """!The list fills up to the strictest target; a desktop-only game takes more, which the GBA build
      refuses.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Fill"):
         stats.add_stat(doc, "extra", stage=False)
      self.assertEqual(len(stats.stat_names(doc)), 10)
      with self.assertRaisesRegex(DocumentError, "at most 10"):
         stats.add_stat(doc, "one_more", stage=False)
      self.assertEqual(stats.limit_problems(doc), [])
      with doc.edit("Desktop"):
         stats.add_stat(doc, "one_more", stage=False, targets=["desktop"])
      self.assertEqual(stats.limit_problems(doc, ["desktop"]), [])
      self.assertEqual(len(stats.limit_problems(doc, ["gba"])), 1)
      self.assertIsNotNone(self.project.validate("gba"))
      self.assertIsNone(self.project.validate("desktop"))


class OddsFlagTests(BattleTestCase):
   """!The odds stat (E9: at most one; the effect_odds pipeline's user_stat / target_stat)."""

   def test_odds_flag(self) -> None:
      """!Setting odds takes it off the others; false is not written; a game may have none; add_stat(odds=) and
      the CLI set it.
      @return None
      """
      doc = self.project.battle
      self.assertEqual([r["name"] for r in stats.stat_list(doc) if r["odds"]], ["intelligence"])   # the Starter's
      with doc.edit("Odds"):
         stats.set_stat(doc, "magic", "odds", True)
      self.assertIs(stats.stat_entry(doc, "magic")["odds"], True)
      self.assertNotIn("odds", stats.stat_entry(doc, "intelligence"))
      with doc.edit("Odds"):
         stats.set_stat(doc, "protection", "odds", True)
      self.assertNotIn("odds", stats.stat_entry(doc, "magic"))
      self.assertEqual([r["name"] for r in stats.stat_list(doc) if r["odds"]], ["protection"])
      self.assertIsNone(self.project.validate())
      with doc.edit("Odds off"):
         stats.set_stat(doc, "protection", "odds", False)   # unlike pool and order, odds may go
      self.assertNotIn("odds", stats.stat_entry(doc, "protection"))
      with doc.edit("Add"):
         stats.add_stat(doc, "wit", odds=True)
      self.assertIs(stats.stat_entry(doc, "wit")["odds"], True)
      self.assertIn("[odds, stage, trait]", "\n".join(stats.stats_report(doc)))
      with doc.edit("Add"):
         stats.remove_stat(doc, "wit")   # the GBA's tenth stat: room for one
         stats.add_stat(doc, "luck", odds=False)
      self.assertNotIn("odds", stats.stat_entry(doc, "luck"))
      with self.assertRaises(DocumentError):
         stats.set_stat(doc, "wit", "odds", "yes")
      self.assertIsNone(self.project.validate())
      b = self.dir / "battle.json"
      out = io.StringIO()
      with redirect_stdout(out):
         self.assertEqual(cli(["battle", str(b), "stat", "set", "agility", "odds", "true"]), 0)
         self.assertEqual(cli(["battle", str(b), "stat", "add", "grit", "--odds"]), 0)
      saved = battle.merged(BattleProject.open(b).battle)["stats"]
      self.assertEqual([st["name"] for st in saved if st.get("odds")], ["grit"])


class StatCliTests(BattleTestCase):
   """!`battle FILE stat ...` and `battle FILE validate --platform`."""

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
      """!list, add, move, rename, set, stages, remove; refused edits are not saved.
      @return None
      """
      b = self.dir / "battle.json"
      status, out = self.run_cli("battle", b, "stat", "list")
      self.assertEqual(status, 0)
      self.assertIn('0 hp: "HP" formula vital [pool]', out)
      self.assertIn('8 agility: "Agility" formula core [order, stage, trait]', out)
      self.assertTrue(out.endswith("9/10 gba\n"))
      self.assertEqual(self.run_cli("battle", b, "stat", "add", "luck", "--label", "Luck", "--at", 1, "--base", 9,
                                    "--no-trait")[0], 0)
      data = battle.merged(BattleProject.open(b).battle)
      self.assertEqual(data["stats"][1], {"name": "luck", "label": "Luck", "formula": "reserve", "trait": False})
      self.assertEqual(data["species"][0]["base"][1], 9)
      self.assertEqual(self.run_cli("battle", b, "stat", "move", "luck", "down")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stat", "move", "hp", "up")[0], 1)
      self.assertEqual(self.run_cli("battle", b, "stat", "rename", "luck", "fortune")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stat", "set", "fortune", "label", "1")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stat", "set", "fortune", "stage", "false")[0], 0)
      data = battle.merged(BattleProject.open(b).battle)
      self.assertEqual((data["stats"][2]["name"], data["stats"][2]["label"]), ("fortune", "1"))
      self.assertNotIn("fortune", [st.get("stat") for st in data["stages"]])
      self.assertEqual(self.run_cli("battle", b, "stat", "set", "fortune", "formula", "nowhere")[0], 1)
      self.assertEqual(BattleProject.open(b).structure.data["stats"][2]["formula"], "reserve")   # not saved
      self.assertEqual(self.run_cli("battle", b, "stat", "stages", "evasion", "dodge")[0], 0)
      status, out = self.run_cli("battle", b, "stat", "stages")
      self.assertIn("1 evasion: dodge", out)
      self.assertEqual(self.run_cli("battle", b, "stat", "remove", "fortune")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stat", "remove", "attack")[0], 1)
      self.assertEqual(battle.stat_keys(BattleProject.open(b).battle), STARTER_STATS)

   def test_validate_targets(self) -> None:
      """!validate checks every target of the game, or the one --platform names.
      @return None
      """
      game = self.dir / "game"
      (game / "data").mkdir(parents=True)
      for f in self.dir.iterdir():
         if f.is_file():
            (game / "data" / f.name).write_bytes(f.read_bytes())
      for folder in ("effects",):   # the effect logic
         (game / "data" / folder).mkdir()
         for f in (self.dir / folder).iterdir():
            (game / "data" / folder / f.name).write_bytes(f.read_bytes())
      b = game / "data" / "battle.json"
      write_project(game, ["gba", "desktop"])
      status, out = self.run_cli("battle", b, "validate")
      self.assertEqual((status, out), (0, "battle data compiles (gba)\nbattle data compiles (desktop)\n"))
      p = BattleProject.open(b)
      with p.battle.edit("Fill"):
         for i in range(5):
            stats.add_stat(p.battle, f"extra{i}", stage=False, targets=["desktop"])
      p.save_all()
      status, out = self.run_cli("battle", b, "validate")
      self.assertEqual(status, 1)
      self.assertIn("gba: ", out)
      self.assertIn("battle data compiles (desktop)", out)
      self.assertEqual(self.run_cli("battle", b, "validate", "--platform", "desktop")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "validate", "--platform", "toaster")[0], 1)
      self.assertEqual(self.run_cli("battle", b, "stat", "add", "again")[0], 1)   # over the GBA's limit


if __name__ == "__main__":
   unittest.main()
