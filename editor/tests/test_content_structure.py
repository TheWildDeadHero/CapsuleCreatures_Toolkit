#!/usr/bin/env python3
"""!Tests of S11 (D-22 A15) without Qt: the core and command line the Content
pages call take their ranges from the compiled structure (levels to
rules.level_max, genes / training / awakening to the record layout's widths;
the CLI's stats, party and damage commands refuse values outside them), new
moves and parties name no closed list, the battle's messages (core.messages
and `battle FILE message ...`: the engine's and the ones the battle declares
itself, engine C4), and the ruleset-removal check that an error inside
structure.json no longer hides.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase).
"""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, engine, messages, pipelines  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import passive_slots, record, stages  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## The Starter's highest level (its rules.level_max).
STARTER_LEVEL_MAX = 50
## The Starter's stat_genes width, bits.
STARTER_GENE_BITS = 4
## Bits of the Starter's stat_training role (G4: its training values, Structure > Growth & training).
STARTER_TRAINING_BITS = 6
## A game message of the Starter that effect logic says (`say dazed`) and a volatile's texts name.
SAID = "dazed"
## A game message of the Starter only a volatile's text names.
TEXT_ONLY = "daze_end"
## A text the engine's encoder refuses for a message (no such placeholder).
BAD_TEXT = "{nowhere} happened"
## A small most of the battle's own messages (the limit test).
FEW = 1


class RangesFromStructureTests(BattleTestCase):
   """!Levels, genes, training and awakening as the data gives them."""

   def test_level_and_rank_max(self) -> None:
      """!level_max() / rank_max() read the rules within the compiler's bounds, else its defaults.
      @return None
      """
      bc = engine.tool("battle_compiler")
      p = self.project
      self.assertEqual(battle.level_max(p.structure), STARTER_LEVEL_MAX)
      self.assertEqual(battle.level_max(None), bc.DEFAULT_LEVEL_MAX)
      self.assertEqual(battle.rank_max(p.battle), p.structure.data["rules"]["rank_max"])
      with p.structure.edit("Odd"):
         p.structure.data["rules"]["level_max"] = bc.MAX_LEVEL_MAX + 1
      self.assertEqual(battle.level_max(p.structure), bc.DEFAULT_LEVEL_MAX)

   def test_stat_inputs(self) -> None:
      """!The Starter's layout holds genes (4 bits) and training values (6 bits, G4); the engine's widths bound every
      input.
      @return None
      """
      p = self.project
      self.assertEqual(record.stat_inputs(p.battle), {"gene": (1 << STARTER_GENE_BITS) - 1,
                                                      "training": (1 << STARTER_TRAINING_BITS) - 1})
      self.assertEqual(list(record.stat_inputs(None)), ["gene"])
      record.check_stat_inputs(p.battle, {"gene": [(1 << STARTER_GENE_BITS) - 1], "training": None})
      with self.assertRaisesRegex(DocumentError, "stat_training width"):
         record.check_stat_inputs(p.battle, {"training": [1 << STARTER_TRAINING_BITS]})
      with self.assertRaisesRegex(DocumentError, "stat_genes width"):
         record.check_stat_inputs(p.battle, {"gene": [1 << STARTER_GENE_BITS]})
      with self.assertRaisesRegex(DocumentError, "stat_awaken"):
         record.check_stat_inputs(p.battle, {"awaken": [record.awaken_max(p.battle) + 1]})

   def test_core_refuses_out_of_range(self) -> None:
      """!stats(), party_add(), learn() and damage_trace() refuse a level above level_max or genes above the width.
      @return None
      """
      p = self.project
      top = STARTER_LEVEL_MAX
      self.assertEqual(len(p.stats("Emberkit", top)), len(battle.stat_keys(p.battle)))
      with self.assertRaisesRegex(DocumentError, "rules.level_max"):
         p.stats("Emberkit", top + 1)
      with self.assertRaisesRegex(DocumentError, "stat_genes"):
         p.stats("Emberkit", top, [1 << STARTER_GENE_BITS] * len(battle.stat_keys(p.battle)))
      with self.assertRaisesRegex(DocumentError, "rules.level_max"):
         with p.battle.edit("Member"):
            battle.party_add(p.battle, "Novice Kit", "Emberkit", top + 1)
      with self.assertRaisesRegex(DocumentError, "stat_genes"):
         with p.battle.edit("Member"):
            battle.party_add(p.battle, "Novice Kit", "Emberkit", top, genes=1 << STARTER_GENE_BITS)
      with self.assertRaisesRegex(DocumentError, "rules.level_max"):
         with p.battle.edit("Learn"):
            battle.learn(p.battle, "Emberkit", top + 1, "Strike")
      with self.assertRaisesRegex(DocumentError, "defender level"):
         pipelines.damage_trace(p, "Emberkit", "Sproutle", "Fireball", top, defender_level=top + 1)

   def test_cli_refuses_out_of_range(self) -> None:
      """!`battle FILE stats` and `party ... add --genes` follow the data; `damage` defaults within level_max.
      @return None
      """
      b = self.dir / "battle.json"
      self.assertEqual(self.run_cli("battle", b, "stats", "Emberkit", STARTER_LEVEL_MAX)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "stats", "Emberkit", STARTER_LEVEL_MAX + 1)[0], 1)
      self.assertEqual(self.run_cli("battle", b, "stats", "Emberkit", 1, "--genes", 1 << STARTER_GENE_BITS)[0], 1)
      self.assertEqual(self.run_cli("battle", b, "stats", "Emberkit", 1, "--awaken", 1)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "party", "Novice Kit", "add", "Emberkit", 2, "--genes",
                                    1 << STARTER_GENE_BITS)[0], 1)
      slot = passive_slots.slot_names(self.project.structure)[-1]
      self.assertEqual(self.run_cli("battle", b, "party", "Novice Kit", "add", "Emberkit", 2, "--genes", 3,
                                    "--passive", slot)[0], 0)
      member = BattleProject.open(b).entry("parties", "Novice Kit")["members"][-1]
      self.assertEqual((member["genes"], member["passive"]), (3, slot))
      with mock.patch.object(pipelines, "DEFAULT_LEVEL", STARTER_LEVEL_MAX + 1):
         self.assertEqual(self.run_cli("battle", b, "damage", "Emberkit", "Sproutle", "Fireball")[0], 0)

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command (its error output dropped).
      @param argv  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out), redirect_stderr(io.StringIO()):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()


class NewEntryTests(BattleTestCase):
   """!New moves and parties name no closed list."""

   def test_new_move_and_party(self) -> None:
      """!A new move states no flags, target or accuracy (the engine's defaults); a new party takes the first
      party's AI flags; binding_move_plain() takes the engine's accuracy.
      @return None
      """
      p = self.project
      with p.battle.edit("Add"):
         battle.add_entry(p.battle, "moves", "Poke")
         battle.add_entry(p.battle, "parties", "Rival")
      move = battle.entry(p.battle, "moves", "Poke")
      self.assertFalse({"flags", "target", "accuracy"} & set(move))
      first = p.battle.data["parties"][0]
      self.assertEqual(battle.entry(p.battle, "parties", "Rival")["ai"], first["ai"])
      self.assertIsNone(p.validate())
      self.assertEqual(battle.binding_move_plain()["accuracy"], engine.tool("battle_compiler").PERCENT)


class MessagesTests(BattleTestCase):
   """!core.messages and the message commands."""

   def test_rows(self) -> None:
      """!The engine's messages in Msg order, then the battle's own at the ids after them; an optional one the data
      leaves out has no id.
      @return None
      """
      bc = engine.tool("battle_compiler")
      p = self.project
      rows = messages.rows(p.battle)
      own = messages.game_keys(p.battle)
      self.assertIn(SAID, own)
      self.assertEqual([r["key"] for r in rows], list(bc.MESSAGES) + own)
      self.assertEqual([r["id"] for r in rows if r["kind"] == messages.GAME],
                       list(range(len(bc.MESSAGES), len(bc.MESSAGES) + len(own))))
      absent = messages.absent_optional(p.battle)
      self.assertTrue(absent)
      self.assertIsNone(next(r for r in rows if r["key"] == absent[0])["id"])
      self.assertEqual(messages.max_game_messages(), bc.MAX_MESSAGES - len(bc.MESSAGES))
      self.assertEqual(messages.uses(p.battle, TEXT_ONLY), ["volatile 'dazed': text end"])

   def test_edits(self) -> None:
      """!add / set_text / rename (its uses follow) / remove, and what they refuse.
      @return None
      """
      p = self.project
      doc = p.battle
      required = engine.tool("battle_compiler").REQUIRED_MESSAGES[0]
      with doc.edit("Add"):
         messages.add(doc, "taunt", "{user} taunts {target}!")
         messages.add(doc, messages.absent_optional(doc)[0])
      self.assertIsNone(p.validate())
      for bad in ("Taunt", "taunt", required, "no_pp"):
         with self.assertRaises(DocumentError, msg=bad):
            with doc.edit("Bad"):
               messages.add(doc, bad)
      with self.assertRaisesRegex(DocumentError, "placeholder"):
         with doc.edit("Bad text"):
            messages.set_text(doc, "taunt", BAD_TEXT)
      with self.assertRaisesRegex(DocumentError, "always says"):
         with doc.edit("Remove"):
            messages.remove(doc, required)
      with self.assertRaisesRegex(DocumentError, "still used"):
         with doc.edit("Remove"):
            messages.remove(doc, SAID)
      with self.assertRaisesRegex(DocumentError, "engine messages keep"):
         with doc.edit("Rename"):
            messages.rename(doc, required, "other")
      order = list(messages.given(doc))
      with doc.edit("Rename"):
         followed = messages.rename(doc, SAID, "bewildered")
      self.assertEqual([w.split(" line ")[0] for w in followed], ["effects/conditions.ceffect: volatile dazed"])
      self.assertEqual(list(messages.given(doc)), [("bewildered" if k == SAID else k) for k in order])
      self.assertEqual(messages.uses(doc, SAID), [])
      self.assertIsNone(p.validate())
      self.assertTrue(doc.undo())
      self.assertIn(SAID, messages.given(doc))
      with doc.edit("Remove"):
         messages.remove(doc, "taunt")
      self.assertNotIn("taunt", messages.given(doc))
      with mock.patch.object(messages, "max_game_messages", return_value=FEW):
         with self.assertRaisesRegex(DocumentError, "at most"):
            with doc.edit("Full"):
               messages.add(doc, "one_more")

   def test_commands(self) -> None:
      """!message list / show / add / set / rename / remove save only when the data compiles.
      @return None
      """
      b = self.dir / "battle.json"
      status, out = self.run_cli("battle", b, "message", "list")
      self.assertEqual(status, 0)
      self.assertIn(f" game     {SAID}  ", out)
      self.assertIn(f"of at most {messages.max_game_messages()} messages", out)
      status, out = self.run_cli("battle", b, "message", "show", SAID)
      self.assertIn("used by effects/", out)
      self.assertEqual(self.run_cli("battle", b, "message", "add", "taunt", "{user} taunts!")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "message", "set", "taunt", BAD_TEXT)[0], 1)
      self.assertEqual(self.run_cli("battle", b, "message", "rename", SAID, "bewildered")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "message", "remove", "taunt")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "message", "remove", "bewildered")[0], 1)
      p = BattleProject.open(b)
      self.assertIn("bewildered", messages.given(p.battle))
      self.assertNotIn("taunt", messages.given(p.battle))
      self.assertIsNone(p.validate())

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command (its error output dropped).
      @param argv  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out), redirect_stderr(io.StringIO()):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()


class RulesetKeptStructureErrorTests(BattleTestCase):
   """!The ruleset-removal check is not hidden by an error inside structure.json (S11)."""

   def test_masked_by_structure_error(self) -> None:
      """!With a volatile's text in error (structure.json's own), removing the crit stage the ruleset's crit
      pipeline needs is still refused; the volatile's error alone is not the ruleset's.
      @return None
      """
      p = self.project
      volatile = p.structure.data["volatiles"][0]
      slot = next(iter(volatile["texts"]))
      with p.structure.edit("Break"):
         volatile["texts"][slot] = BAD_TEXT
      self.assertTrue(p.error_now().startswith(p.structure.path.name))
      self.assertIsNone(battle.ruleset_problem(p.structure))
      with self.assertRaisesRegex(DocumentError, "still needed by the ruleset: ruleset.json: pipelines.crit"):
         with p.structure.edit("Remove stage"):
            stages.remove_stage(p.structure, "critical")
      self.assertIn("critical", [s.get("name") for s in p.structure.data["stages"]])

   def test_binding_structure(self) -> None:
      """!binding_structure() keeps the condition records' names and what the ruleset binds to.
      @return None
      """
      data = self.project.structure.data
      plain = battle.binding_structure(data)
      for key in battle.BINDING_RECORD_LISTS:
         self.assertEqual([e["name"] for e in plain.get(key, [])], [e["name"] for e in data.get(key, [])])
      for key in ("stats", "stages", "monster_layout", "rules", "categories", "chart"):
         self.assertEqual(plain.get(key), data.get(key), key)
      self.assertFalse(set(battle.BINDING_DROPPED) & set(plain))


if __name__ == "__main__":
   unittest.main()
