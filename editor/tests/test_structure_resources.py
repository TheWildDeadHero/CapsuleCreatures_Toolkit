#!/usr/bin/env python3
"""!Tests for capsule_studio.core.structure.resources (the
structure manifest's resources, the moves' costs and bases), what follows
them (stats, record roles, the generation list, effect logic, bench
scenarios) and the `battle FILE resource ...` commands. No Qt.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase):
three battler resources, HP (faint, persisted in current_hp), MP and EP
(persisted in the custom roles current_mp / current_ep; EP regenerates by
the named formula ep_regen); the tests add move resources of their own.
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
from capsule_studio.core import battle, engine, logic  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import progression, record, resources, stats, turn  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## The effect source holding the Starter's passive logic.
PASSIVES = "effects/passives.ceffect"
## Its item logic.
ITEMS = "effects/items.ceffect"


class ResourceModelTests(BattleTestCase):
   """!Reading, adding, changing and removing resources."""

   def add_charge(self) -> None:
      """!Adds a move resource "charge" (each move states its base, field "charge"; one edit).
      @return None
      """
      doc = self.project.structure
      with doc.edit("Move resource"):
         resources.add_resource(doc, "charge", resources.MOVE)

   def test_rows_and_budget(self) -> None:
      """!The Starter's resources as the engine resolves them; the budget counts each scope against the caps.
      @return None
      """
      doc = self.project.battle
      rows = resources.resource_rows(doc)
      self.assertEqual([(r["name"], r["scope"], r["empty"]) for r in rows],
                       [("hp", "battler", "faint"), ("mp", "battler", "none"), ("ep", "battler", "none")])
      self.assertEqual((rows[2]["stat"], rows[2]["persist"], rows[2]["regen"]), ("ep", "current_ep", "ep_regen"))
      # elemental and status moves pay MP, physical ones EP; Strike (the fallback) is free
      self.assertEqual([r["payers"] for r in rows], [0, 18, 9])
      self.assertEqual(resources.budget(doc, ["gba", "desktop"]), [("gba", 3, 4, 0, 2), ("desktop", 3, 8, 0, 4)])
      self.assertEqual(resources.lines(doc)[-2], "3/4 battler, 0/2 move gba")
      self.assertEqual(resources.lines(doc)[-1], f"1/{resources.max_formulas()} resource formulas")   # ep_regen
      self.assertEqual(resources.persist_roles(doc), ["current_hp", "current_mp", "current_ep"])
      self.assertEqual(resources.compile_check(doc)[1], None)
      # a battler pool reaches its stat's highest value (the engine's analysed bounds)
      compiled = self.project.compile()[0]
      mp = next(r for r in compiled["resources"] if r["name"] == "mp")
      self.assertEqual(resources.pool_caps(doc)["mp"], compiled["stats"][mp["stat"]]["bounds"][1])
      self.assertEqual(resources.formula_choices(doc), ["ep_regen"])
      # the roles a pool may be kept in: the record's fitting roles not taken by another pool
      # (the Starter's 8-bit bond role fits too)
      self.assertEqual(resources.role_choices(doc, resources.BATTLER, "ep"),
                       ["current_ep", "hatch_counter", "egg", "bond"])   # the egg roles are free custom roles
      # The growth's form role is the form's; the step effects' bond role is free (no pool keeps it)
      self.assertEqual(resources.role_choices(doc, resources.BATTLER), ["hatch_counter", "egg", "bond"])
      with doc.edit("Custom"):
         record.add_custom_role(doc, "mana_store", 10)
      self.assertEqual(resources.role_choices(doc, resources.BATTLER), ["hatch_counter", "egg", "bond", "mana_store"])

   def test_add_set_regen_and_undo(self) -> None:
      """!A battler resource's regen amount and a custom role to persist in; compiles; undo takes each step back.
      @return None
      """
      doc = self.project.structure
      with doc.edit("Custom"):
         record.add_custom_role(doc, "mana_store", 10)
      before = copy.deepcopy(doc.data)
      with doc.edit("Regen"):
         resources.set_resource(doc, "mp", "regen", 2)
      self.assertEqual(resources.resource_entry(doc, "mp")["regen"], 2)
      self.assertIn("regen", [row["run"] for row in turn.phase_rows(doc)])
      with doc.edit("Persist"):
         resources.set_resource(doc, "mp", "persist", "mana_store")
      self.assertEqual(list(resources.resource_entry(doc, "mp")),
                       ["name", "label", "scope", "stat", "persist", "regen"])
      self.assertIsNone(self.project.validate())
      self.assertNotIn("mana_store", progression.role_choices(doc))   # the engine fills a persisted pool's role
      self.assertTrue(doc.undo())
      self.assertTrue(doc.undo())
      self.assertEqual(doc.data, before)
      for key, value, wanted in (("persist", "moves", "record role"), ("empty", "faint", "pool stat"),
                                 ("regen", "nope", "named formula"), ("max", "ep_regen", "only a move"),
                                 ("stat", "nope", "stat: one of")):
         with self.assertRaisesRegex(DocumentError, wanted):
            with doc.edit("Bad"):
               resources.set_resource(doc, "mp", key, value)
      self.assertEqual(doc.data, before)

   def test_move_costs(self) -> None:
      """!Costs: a move's own costs are shown, a cost is written in resource order, the default (the Starter's
      battler resources: free) drops it again; a resource a move's cost names is not removed; the cost compiles.
      @return None
      """
      doc = self.project.battle
      own = dict(battle.entry(doc, "moves", "Flare Claw")["cost"])   # the sample's own (EP) cost
      self.assertEqual(list(own), ["ep"])
      rows = resources.cost_rows(doc, "Flare Claw")
      self.assertEqual([(r["resource"], r["amount"], r["default"]) for r in rows],
                       [("hp", 0, False), ("mp", 0, False), ("ep", own["ep"], False)])
      with doc.edit("Cost"):
         resources.set_cost(doc, "Flare Claw", "mp", "3")
      self.assertEqual(battle.entry(doc, "moves", "Flare Claw")["cost"], {"mp": 3, "ep": own["ep"]})
      self.assertIsNone(self.project.validate())
      with self.assertRaisesRegex(DocumentError, "move Flare Claw"):
         with doc.edit("Remove"):
            resources.remove_resource(doc, "ep")
      with doc.edit("Free"):
         resources.set_cost(doc, "Flare Claw", "ep", 0)
      self.assertEqual(battle.entry(doc, "moves", "Flare Claw")["cost"], {"mp": 3})
      with doc.edit("Default"):
         resources.set_cost(doc, "Flare Claw", "mp", None)
         resources.set_cost(doc, "Flare Claw", "ep", None)
      self.assertNotIn("cost", battle.entry(doc, "moves", "Flare Claw"))
      self.assertEqual([r["default"] for r in resources.cost_rows(doc, "Flare Claw")], [True, True, True])
      with self.assertRaisesRegex(DocumentError, "whole number"):
         with doc.edit("Bad"):
            resources.set_cost(doc, "Flare Claw", "ep", -1)
      with doc.edit("Again"):
         resources.set_cost(doc, "Flare Claw", "ep", 2)
      self.assertTrue(resources.reset_cost(doc, "Flare Claw"))
      self.assertEqual(resources.cost_of(doc, "Flare Claw"), {})

   def test_cost_rules(self) -> None:
      """!Engine the move costs' rules: the fallback move pays nothing (no cost to edit), a hit point cost stays below
      the most hit points, a regen number lies in REGEN_RANGE, a persist role narrower than its pool is refused with the
      engine's message; the formula count is reported.
      @return None
      """
      doc = self.project.battle
      fallback = resources.fallback_move(doc)
      self.assertIsNotNone(fallback)
      self.assertTrue(all(r["fallback"] and r["amount"] == 0 for r in resources.cost_rows(doc, fallback)))
      with self.assertRaisesRegex(DocumentError, "fallback_move"), doc.edit("Fallback cost"):
         resources.set_cost(doc, fallback, "ep", 1)
      move = next(n for n in self.project.names("moves") if n != fallback)
      top = resources.pool_caps(doc)["hp"]
      with self.assertRaisesRegex(DocumentError, "below the most hp"), doc.edit("HP cost"):
         resources.set_cost(doc, move, "hp", top)
      with doc.edit("HP cost"):
         resources.set_cost(doc, move, "hp", 1)
      self.assertIsNone(self.project.validate())
      st = self.project.structure
      lo, hi = resources.regen_range()
      self.assertEqual((lo, hi), tuple(engine.tool("battle_compiler").REGEN_RANGE))
      with self.assertRaisesRegex(DocumentError, "whole number"), st.edit("Regen"):
         resources.set_resource(st, "mp", "regen", hi + 1)
      # a persist role narrower than the pool's highest value (check_persist_roles(): the whole data's compile)
      with st.edit("Narrow role"):
         record.add_custom_role(st, "tiny_store", 2)
      with self.assertRaisesRegex(DocumentError, "truncate"), st.edit("Persist"):
         resources.set_resource(st, "mp", "persist", "tiny_store")
      self.assertEqual(resources.resource_entry(st, "mp")["persist"], "current_mp")
      self.assertEqual(resources.formula_count(doc), len({r["regen"] for r in resources.resource_rows(doc)
                                                          if isinstance(r["regen"], str)}))

   def test_move_resource_and_caps(self) -> None:
      """!A move resource writes its base into every move (a move without own costs pays its default 1); the GBA's
      cap of two refuses a third; renaming its base field and removing it drop the field again.
      @return None
      """
      self.add_charge()
      doc = self.project.structure
      self.assertTrue(all(m["charge"] == battle.NEW_RESOURCE_BASE for m in battle.entries(doc, "moves")))
      with doc.edit("No own costs"):
         del battle.entry(doc, "moves", "Flare Claw")["cost"]
      self.assertEqual(resources.cost_of(doc, "Flare Claw"), {"charge": 1})
      self.assertIsNone(self.project.validate())
      with doc.edit("Second"):
         resources.add_resource(doc, "more", resources.MOVE)
      with self.assertRaisesRegex(DocumentError, "at most 2 move resources"):
         with doc.edit("Third"):
            resources.add_resource(doc, "extra", resources.MOVE)
      with doc.edit("Base"):
         resources.set_resource(doc, "charge", "base", "charges")
      self.assertTrue(all("charges" in m and "charge" not in m for m in battle.entries(doc, "moves")))
      with doc.edit("Remove"):
         resources.remove_resource(doc, "charge")
      self.assertFalse(any("charges" in m for m in battle.entries(doc, "moves")))
      with self.assertRaisesRegex(DocumentError, "faint resource"):
         with doc.edit("Remove hp"):
            resources.remove_resource(doc, "hp")
      with self.assertRaisesRegex(DocumentError, "faint resource"):
         with doc.edit("Scope"):
            resources.set_scope(doc, "hp", resources.MOVE)

   def test_rename_follows(self) -> None:
      """!A rename of mp follows the costs and the effect logic in one undo step across battle.json, structure.json
      and the sources; bench scenarios naming it are listed, not rewritten; removal is refused while used.
      @return None
      """
      p = self.project
      bench = self.dir / "bench"
      bench.mkdir()
      scenario = {"schema": "capsule.bench/1", "format": "Single",
                  "parties": [{"side": 0, "members": [{"species": "Voltmink", "level": 5,
                                                       "resources": {"mp": 5}}]}]}
      (bench / "mp.json").write_text(json.dumps(scenario), encoding="utf-8")
      self.assertEqual(resources.bench_users(p.structure, "mp"), ["bench bench/mp.json party 0 member 0"])
      sources = (p.effect_source(PASSIVES).text, p.effect_source(ITEMS).text)
      before = (copy.deepcopy(p.battle.data), copy.deepcopy(p.structure.data), sources)
      payers = [m["name"] for m in battle.entries(p.battle, "moves") if "mp" in m.get("cost", {})]
      with p.structure.edit("Rename"):
         n = resources.rename_resource(p.structure, "mp", "mana")
      self.assertEqual(n, len(payers) + 3)   # the costs, Recharge's, Mana Drop's and Mana Tea's logic
      self.assertEqual(resources.resource_entry(p.battle, "mana")["stat"], "mp")   # the stat keeps its name
      self.assertEqual(battle.entry(p.battle, "moves", "Fireball")["cost"], {"mana": 8})
      self.assertIn("restore holder mana 2;", p.effect_source(PASSIVES).text)
      self.assertIn("holder.resource(mana)", p.effect_source(ITEMS).text)
      self.assertIsNone(p.validate())
      self.assertTrue(p.structure.undo())
      self.assertEqual((p.battle.data, p.structure.data,
                        (p.effect_source(PASSIVES).text, p.effect_source(ITEMS).text)), before)
      with self.assertRaisesRegex(DocumentError, "move Fireball"):
         with p.structure.edit("Remove"):
            resources.remove_resource(p.structure, "mp")

   def test_stats_and_roles_follow(self) -> None:
      """!A stat rename follows a battler resource's stat; a stat a resource takes is not removed; a role a
      resource names is not removed, and a custom role's rename follows the resource.
      @return None
      """
      doc = self.project.structure
      with doc.edit("Rename stat"):
         stats.rename_stat(doc, "ep", "energy")
      self.assertEqual(resources.resource_entry(doc, "ep")["stat"], "energy")
      with self.assertRaisesRegex(DocumentError, "resource ep"):
         with doc.edit("Remove stat"):
            stats.remove_stat(doc, "energy")
      with self.assertRaisesRegex(DocumentError, "resource ep persist"):
         with doc.edit("Remove role"):
            record.remove_role(doc, "current_ep")
      with doc.edit("Rename role"):
         record.rename_role(doc, "current_ep", "ep_store")
      self.assertEqual(resources.resource_entry(doc, "ep")["persist"], "ep_store")
      self.assertIsNone(self.project.validate())
      for role in ("current_hp", "current_mp", "ep_store"):   # the engine fills persisted pools' roles
         self.assertNotIn(role, progression.role_choices(doc))

   def test_logic_names(self) -> None:
      """!Effect logic sees the resources: name lists, the catalog's scopes, the palette's restore / raise (raise
      only with a move resource).
      @return None
      """
      p = self.project
      self.assertEqual(logic.name_lists(p)["resources"], ["hp", "mp", "ep"])
      self.assertEqual(logic.catalog(p).entries["resources"], [{"name": n, "scope": "battler"}
                                                               for n in ("hp", "mp", "ep")])
      templates = {label: text for _group, label, text in logic.statement_templates(p)}
      self.assertEqual(templates["restore"], "restore holder hp;")
      self.assertIsNone(templates["raise"])
      self.add_charge()
      templates = {label: text for _group, label, text in logic.statement_templates(p)}
      self.assertEqual(templates["raise"], "raise holder charge 1;")
      self.assertNotIn("no_pp", battle.DEFAULT_MESSAGES)


class ResourceCliTests(BattleTestCase):
   """!The `battle FILE resource ...` commands."""

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs the CLI, capturing stdout.
      @param argv  arguments
      @return (exit status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()

   def test_commands(self) -> None:
      """!List, add, set, cost, base, rename, move and remove save the data when it compiles.
      @return None
      """
      b = self.dir / "battle.json"
      status, out = self.run_cli("battle", b, "resource", "list")
      self.assertEqual(status, 0)
      self.assertIn('2 ep: "EP" battler, stat ep, persist current_ep, regen ep_regen, 9 move(s) pay it', out)
      self.assertIn("3/4 battler, 0/2 move gba", out)
      self.assertEqual(self.run_cli("battle", b, "stat", "add", "luck", "--no-stage")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "resource", "add", "luck", "battler", "--stat", "luck",
                                    "--label", "Luck")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "resource", "set", "luck", "regen", "1")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "resource", "cost", "Fireball", "luck", "4")[0], 0)
      status, out = self.run_cli("battle", b, "resource", "cost", "Fireball")
      self.assertIn("luck (battler): 4", out)
      self.assertEqual(self.run_cli("battle", b, "resource", "add", "charge", "move")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "resource", "base", "Fireball", "charge", "20")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "resource", "rename", "luck", "fortune")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "resource", "move", "fortune", "up")[0], 0)
      saved = json.loads((self.dir / "battle.json").read_text(encoding="utf-8"))
      structure = json.loads((self.dir / battle.STRUCTURE_FILE).read_text(encoding="utf-8"))
      fireball = next(m for m in saved["moves"] if m["name"] == "Fireball")
      self.assertEqual((fireball["charge"], fireball["cost"]), (20, {"mp": 8, "fortune": 4}))
      self.assertEqual([r["name"] for r in structure["resources"]], ["hp", "mp", "fortune", "ep", "charge"])
      self.assertEqual(structure["resources"][2]["regen"], 1)
      self.assertEqual(self.run_cli("battle", b, "resource", "cost", "Fireball", "--reset")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "resource", "remove", "fortune")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "validate")[0], 0)
      with self.assertRaises(SystemExit):   # unknown key
         self.run_cli("battle", b, "resource", "set", "mp", "colour", "1")


if __name__ == "__main__":
   unittest.main()
