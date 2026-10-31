#!/usr/bin/env python3
"""!Tests of the S5c structure models: formats and the turn structure
(core.structure.turn), the progression rules and the generation list
(core.structure.progression), the record's transfer defaults
(core.structure.record), and their `battle FILE ...` commands. Uses a copy
of the engine's Starter sample; every choice list and limit is the
engine's compiler's.
"""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, engine  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import progression, record, stats, turn  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402


class TurnModelTests(BattleTestCase):
   """!The turn structure."""

   def test_defaults_and_choices(self) -> None:
      """!The merged structure marks what the engine gives; the choices are the compiler's lists.
      @return None
      """
      bc = engine.tool("battle_compiler")
      doc = self.project.battle
      self.assertEqual(turn.sources(), bc.SOURCES)
      self.assertEqual(turn.end_phases(), bc.END_PHASES)
      self.assertEqual(turn.bracket_range(), (bc.BRACKET_MIN, bc.BRACKET_MAX))
      self.assertEqual(turn.move_priority(), bc.DEFAULT_TURN["brackets"]["move"])
      with doc.edit("Drop"):
         battle.structure_doc(doc).data.pop("turn")
      value, defaulted = turn.turn_value(doc)
      self.assertEqual(value, bc.DEFAULT_TURN)
      self.assertIn("brackets.run", defaulted)
      self.assertIn("end_of_turn", defaulted)
      self.assertTrue(all(r["default"] for r in turn.phase_rows(doc)))
      self.assertIn("(default)", turn.turn_lines(doc)[0])

   def test_edits(self) -> None:
      """!Brackets, choices, the effect order and the phases; the compiler refuses what it must.
      @return None
      """
      doc = self.project.structure   # its edits change the structure manifest (undo there)
      with doc.edit("Bracket"):
         turn.set_bracket(doc, "run", 5)
         turn.set_bracket(doc, "move", 3)
      self.assertEqual(battle.structure_doc(doc).data["turn"]["brackets"]["run"], 5)
      self.assertEqual(turn.compile_turn(doc)[0]["brackets"]["move_priority"], 0)
      with self.assertRaises(DocumentError):
         turn.set_bracket(doc, "run", turn.bracket_range()[1] + 1)
      with self.assertRaises(DocumentError):
         turn.set_bracket(doc, "switch", turn.move_priority())   # only the move bracket may be "priority"
      with doc.edit("Tie"):
         turn.set_choice(doc, "tie", "position")
         turn.set_choice(doc, "switching.send_out", None)
      self.assertNotIn("send_out", battle.structure_doc(doc).data["turn"]["switching"])
      with doc.edit("Order"):
         self.assertTrue(turn.move_source(doc, "item", -1))
      self.assertEqual(turn.effect_order(doc)[-2:], ["item", "passive"])
      with self.assertRaises(DocumentError):
         turn.set_effect_order(doc, ["status"])
      # phases: weather must stay exactly once (the compiler's message), a second battlers phase is fine
      with self.assertRaisesRegex(DocumentError, "exactly once"):
         with doc.edit("Remove"):
            turn.remove_phase(doc, 0)
      self.assertEqual(len(turn.phase_rows(doc)), 5)   # the Starter's EP regenerates in a regen phase (D-25)
      with doc.edit("Add"):
         self.assertEqual(turn.add_phase(doc, "battlers", 1), 1)
         turn.set_phase_sources(doc, 1, ["status", "item"])
         turn.set_phase_each(doc, 3, "once")
      rows = turn.phase_rows(doc)
      self.assertEqual(rows[1]["runs"], ["status", "item"])
      self.assertEqual(rows[3]["each"], "once")
      with self.assertRaises(DocumentError):
         turn.set_phase_each(doc, 1, "once")   # a battlers phase has no "each"
      with doc.edit("Drag"):
         self.assertTrue(turn.move_phase_to(doc, 1, 4))
      self.assertEqual([r["run"] for r in turn.phase_rows(doc)],
                       ["weather", "battlers", "sides", "field", "battlers", "regen"])
      self.assertIsNone(self.project.validate())
      with doc.edit("Reset"):
         self.assertTrue(turn.reset(doc, "end_of_turn"))
      self.assertNotIn("end_of_turn", battle.structure_doc(doc).data["turn"])
      doc.undo()
      self.assertIn("end_of_turn", battle.structure_doc(doc).data["turn"])


class FormatModelTests(BattleTestCase):
   """!The formats."""

   def test_rows_and_edits(self) -> None:
      """!Sides, places, stands and fields; the compiler checks each format; references follow renames.
      @return None
      """
      doc = self.project.battle
      rows = turn.format_rows(doc)
      self.assertEqual([r["name"] for r in rows], ["Single", "Double"])
      self.assertEqual(rows[1]["stands"], [rows[1]["layout"][0], rows[1]["layout"][2]])   # first positions
      self.assertFalse(rows[1]["own_stands"])
      self.assertIsNone(rows[1]["error"])
      with doc.edit("Sides"):
         turn.set_sides(doc, "Single", [1, 2])
      single = turn.format_rows(doc)[0]
      self.assertEqual(single["sides"], [[0], [1, 2]])
      self.assertEqual(len(single["layout"]), 3)
      with doc.edit("Place"):
         turn.set_place(doc, "Single", turn.LAYOUT_KEY, 2, 200, 40)
         turn.set_place(doc, "Single", turn.STANDS_KEY, 1, 190, 30)
      single = turn.format_rows(doc)[0]
      self.assertEqual(single["layout"][2], [200, 40])
      self.assertTrue(single["own_stands"])
      self.assertEqual(single["stands"][1], [190, 30])
      with self.assertRaises(DocumentError):
         turn.set_place(doc, "Single", turn.LAYOUT_KEY, 0, turn.screen_max() + 1, 0)
      with self.assertRaises(DocumentError):
         turn.set_sides(doc, "Single", [1])
      # "adjacent" needs two sides of equal size: the compiler refuses it for 1 | 2
      with self.assertRaisesRegex(DocumentError, "adjacent"):
         with doc.edit("Range"):
            turn.set_format_field(doc, "Single", turn.RANGE_KEY, "adjacent")
      with doc.edit("Fields"):
         turn.set_format_field(doc, "Single", turn.FAINTED_KEY, "fail")
         turn.set_format_field(doc, "Single", turn.PARTY_MAX_KEY, None)
         turn.clear_stands(doc, "Single")
      self.assertNotIn("party_max", battle.structure_doc(doc).data["formats"][0])
      self.assertEqual(turn.format_rows(doc)[0]["on_target_fainted"], "fail")
      with doc.edit("Add"):
         name = turn.add_format(doc, "Wide", "Double", 0)
      self.assertEqual(turn.format_names(doc)[0], name)
      self.assertIsNone(self.project.validate())
      with doc.edit("Remove"):
         turn.remove_format(doc, "Wide")
      self.assertIn("Single:", turn.format_lines(doc)[0])


class ProgressionModelTests(BattleTestCase):
   """!Learning, experience and the generation list."""

   def test_policies(self) -> None:
      """!Words from the compiler; the defaults show; a refused word is the compiler's.
      @return None
      """
      bc = engine.tool("battle_compiler")
      doc = self.project.battle
      self.assertEqual(progression.choices()["learn.on_full"], bc.LEARN_ON_FULL)
      with doc.edit("Learn"):
         progression.set_policy(doc, "learn.on_full", "request")
         progression.set_policy(doc, "exp_policy.receivers", None)
      value, left = progression.policy(doc, "exp_policy")
      self.assertIn("receivers", left)
      self.assertEqual(value["receivers"], bc.DEFAULT_EXP_POLICY["receivers"])
      for key in progression.required("exp_policy"):   # E7: no engine default (the game states it)
         with self.assertRaises(DocumentError):
            progression.set_policy(doc, f"exp_policy.{key}", None)
      self.assertEqual(battle.structure_doc(doc).data["learn"]["on_full"], "request")
      with self.assertRaises(DocumentError):
         progression.set_policy(doc, "learn.on_full", "forget")
      with doc.edit("Outsider"):
         progression.set_policy(doc, "exp_policy.outsider", "owner_id")   # the sample holds owner_id
      self.assertIsNone(self.project.validate())

   def test_generation(self) -> None:
      """!Rows numbered in draw order; add, edit, move, preview; the roles the engine fills are refused.
      @return None
      """
      bc = engine.tool("battle_compiler")
      doc = self.project.battle
      rows = progression.generation_rows(doc)
      self.assertEqual([r["role"] for r in rows], ["seed", "stat_genes", "trait", "passive_selector"])
      self.assertEqual([(r["first"], r["draws"]) for r in rows], [(1, 2), (3, 9), (12, 1), (13, 1)])   # nine stats
      self.assertTrue(rows[3]["species"])
      self.assertEqual(rows[0]["kind"], "wide")
      self.assertIn("seed_lo", progression.derived_inputs(doc))
      self.assertIn("TRAIT_COUNT", progression.derived_constants(doc))
      with self.assertRaises(DocumentError):
         progression.add_entry(doc, bc.GENERATED_BY_ENGINE[0])
      with doc.edit("Add"):
         i = progression.add_entry(doc, "owner_id", progression.DERIVED_WAY)
         progression.set_derived(doc, i, "seed_lo % 7 + element", [0, 9])
      self.assertEqual(progression.preview(doc, i, {"seed_lo": 20}), 6)
      self.assertEqual(progression.preview(doc, i, {"seed_lo": 20}, element=5), 9)   # clamped to the range
      with self.assertRaises(DocumentError):
         with doc.edit("Bad"):
            progression.set_derived(doc, i, "nothing_here + 1")
      with doc.edit("Way"):
         progression.set_way(doc, i, progression.CONSTANT_WAY)
         progression.set_constant(doc, i, 70)
         progression.move_entry(doc, i, -1)
      self.assertEqual(battle.structure_doc(doc).data["generation"][i - 1], {"role": "owner_id", "constant": 70})
      with doc.edit("Range"):
         progression.set_random(doc, 1, 0, "15")
      self.assertEqual(battle.structure_doc(doc).data["generation"][1]["random_range"], [0, 15])
      with self.assertRaises(DocumentError):
         with doc.edit("Last"):   # the edit puts the manifest back
            progression.set_random(doc, 1, 0, "last")   # "last" is for trait and passive_selector
      self.assertIsNone(self.project.validate())
      with doc.edit("Reset"):
         self.assertTrue(progression.reset_generation(doc))
      self.assertTrue(progression.is_default(doc))

   def test_role_rename_and_removal_follow(self) -> None:
      """!A custom role's rename follows the entries and derived expressions; a removal drops its entries and is
      refused while an expression reads it.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Custom roles"):   # the Starter's record has no free custom role a generation entry may fill
         record.add_custom_role(doc, "fondness", 8)
         record.add_custom_role(doc, "token_code", 16)
      with doc.edit("Add"):
         i = progression.add_entry(doc, "fondness", progression.DERIVED_WAY)
         progression.set_derived(doc, i, "token_code % 100")
         j = progression.add_entry(doc, "token_code", progression.CONSTANT_WAY)
      with doc.edit("Rename"):
         record.rename_role(doc, "token_code", "token")
      self.assertEqual(battle.structure_doc(doc).data["generation"][i]["derived"], "token % 100")
      self.assertEqual(battle.structure_doc(doc).data["generation"][j]["role"], "token")
      self.assertIsNone(self.project.validate())
      with self.assertRaisesRegex(DocumentError, "derived expression"):
         with doc.edit("Remove"):
            record.remove_role(doc, "token")
      with doc.edit("Remove"):
         progression.remove_entry(doc, i)
         record.remove_role(doc, "token")
      self.assertNotIn("token", [e["role"] for e in battle.structure_doc(doc).data["generation"]])
      self.assertIsNone(self.project.validate())


class TransferDefaultTests(BattleTestCase):
   """!monster_layout.transfer_defaults."""

   def test_set_follow_clear(self) -> None:
      """!Whole-stat and per-role values; a stat rename follows; clearing drops empty objects.
      @return None
      """
      doc = self.project.battle
      # the Starter keeps genes and (G4) training values
      self.assertEqual(record.per_stat_roles(doc), ["stat_genes", "stat_training"])
      self.assertFalse(any(r["given"] for r in record.transfer_defaults(doc)))
      with doc.edit("Set"):
         record.set_transfer_default(doc, "hp", 3)
         record.set_transfer_default(doc, "attack", 5, "stat_genes")
      self.assertEqual(battle.structure_doc(doc).data["monster_layout"]["transfer_defaults"],
                       {"hp": 3, "attack": {"stat_genes": 5}})
      self.assertEqual(record.transfer_defaults(doc)[0]["values"], {"stat_genes": 3, "stat_training": 3})
      with self.assertRaises(DocumentError):
         record.set_transfer_default(doc, "hp", record.role_max(doc, "stat_genes") + 1, "stat_genes")
      self.assertIsNone(self.project.validate())
      with doc.edit("Rename stat"):
         stats.rename_stat(doc, "attack", "power")
      self.assertIn("power", battle.structure_doc(doc).data["monster_layout"]["transfer_defaults"])
      with doc.edit("Clear"):
         record.set_transfer_default(doc, "power", None, "stat_genes")
         record.set_transfer_default(doc, "hp", None)
      self.assertNotIn("transfer_defaults", battle.structure_doc(doc).data["monster_layout"])


class CommandTests(BattleTestCase):
   """!The `battle FILE format|turn|learning|exp|generation|transfer ...` commands."""

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
      """!Each group edits, saves and reports.
      @return None
      """
      b = self.dir / "battle.json"
      status, out = self.run_cli("battle", b, "turn", "show")
      self.assertEqual(status, 0)
      self.assertIn("end_of_turn:", out)
      self.assertEqual(self.run_cli("battle", b, "turn", "order", "item", "up")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "turn", "phase", "add", "battlers", "--at", "1")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "turn", "phase", "sources", "1", "status")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "turn", "bracket", "move", "4")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "format", "sides", "Single", "1", "2")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "format", "stand", "Single", "1", "150", "40")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "learning", "set", "on_full", "request")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "generation", "add", "owner_id", "--way", "derived")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "generation", "derived", "4", "seed_lo % 100", "--range", "0",
                                    "99")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "generation", "preview", "4", "seed_lo=250"), (0, "50\n"))
      self.assertEqual(self.run_cli("battle", b, "transfer", "set", "hp", "3")[0], 0)
      saved = engine.tool("battle_compiler").view_of(b)
      self.assertEqual(saved["turn"]["end_of_turn"][1], {"run": "battlers", "sources": ["status"]})
      self.assertEqual(saved["turn"]["brackets"]["move"], 4)
      self.assertEqual(saved["formats"][0]["stands"][1], [150, 40])
      self.assertEqual(saved["learn"]["on_full"], "request")
      self.assertEqual(saved["generation"][4], {"role": "owner_id", "derived": "seed_lo % 100", "range": [0, 99]})
      self.assertEqual(saved["monster_layout"]["transfer_defaults"], {"hp": 3})
      status, out = self.run_cli("battle", b, "generation", "show")
      self.assertIn("draws 1-2", out)
      status, out = self.run_cli("battle", b, "formula")
      self.assertEqual(status, 0)
      # refused edits are not saved
      self.assertEqual(self.run_cli("battle", b, "turn", "phase", "remove", "0")[0], 1)


if __name__ == "__main__":
   unittest.main()
