#!/usr/bin/env python3
"""!Tests for capsule_studio.core.structure.conditions (the condition records),
core.structure.flags (move flags and tags), core.structure.categories,
core.holders (passives / items and manifest point handlers) and their
`battle FILE condition|flag|tag|category|holder|handler ...` commands. No Qt.

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
from capsule_studio.core import battle, engine, holders, logic  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import categories, chart, conditions, flags  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402


def source_text(project: BattleProject) -> str:
   """!Every effect source's text, joined.
   @param project  BattleProject
   @return text
   """
   return "\n".join(src.text for src in project.effects.values())


## Records the Starter lacks, for the tests of fields that name move flags (invented, neutral): a status a move
## flag and a type end (thawed_by_move / thawed_by_hit), a chain kept by a flag, the volatile it guards.
FROST = {"name": "Frost", "cure": "1/5", "skip": "1/1", "thawed_by_move": "thaws", "thawed_by_hit": "Fire",
         "immune_types": ["Fire"], "texts": {"inflicted": "{user} froze!", "skip": "{user} is frozen!",
                                             "cured": "{user} thawed!", "already": "{user} is already frozen!"}}
## A chain the guarding flag keeps.
GUARD_CHAIN = {"name": "guard_chain", "chain": {"den": 3, "cap": 8, "kept_by": "guarding"}}
## The volatile a guarding move starts.
GUARD = {"name": "guard", "duration": "turn"}


def add_flag_records(doc: battle.Document) -> None:
   """!Adds FROST, GUARD_CHAIN and GUARD with the flags they name (thaws, guarding, an unused spare) to a Starter
   copy, and the guarding flag to Harden (one undo step).
   @param doc  the battle Document
   @return None
   """
   st = battle.structure_doc(doc).data
   with doc.edit("Flag records"):
      st["move_flags"] = st["move_flags"] + ["thaws", "guarding", "spare"]
      st["statuses"].append(copy.deepcopy(FROST))
      st["volatiles"] += [copy.deepcopy(GUARD_CHAIN), copy.deepcopy(GUARD)]
      battle.entry(doc, "moves", "Harden")["flags"] = ["guarding"]


class ConditionModelTests(BattleTestCase):
   """!The condition records."""

   def test_fields_cover_the_engine(self) -> None:
      """!Every key the engine's compiler takes in a record is a field or edited apart; choice lists are the
      engine's.
      @return None
      """
      bc = engine.tool("battle_compiler")
      cc = engine.tool("battlec.conditions")
      for kind in conditions.kinds():
         covered = set(conditions.fields(kind)) | set(conditions.APART_KEYS)
         self.assertLessEqual(conditions.engine_keys(kind), covered, kind)
         self.assertLessEqual(set(conditions.fields(kind)), conditions.engine_keys(kind), kind)
      self.assertEqual(conditions.durations()[:-1], list(cc.DURATIONS))
      self.assertEqual(conditions.clear_events(), list(cc.CLEARS_ON))
      self.assertEqual(conditions.fixed_slots("status"), list(bc.STATUS_TEXTS))
      self.assertEqual(conditions.list_key("side_condition"), "side_conditions")
      # E9: the battle compiler's re-exports (the same lists as battlec.conditions')
      self.assertEqual(conditions.count_modes(), list(bc.COUNTS))
      self.assertEqual(conditions.text_args("volatile"), sorted(bc.CONDITION_TEXT_ARGS))
      self.assertEqual(conditions.chain_limits(), (bc.MIN_CHAIN_DEN, bc.MAX_CHAIN_CAP, bc.MAX_CHAIN_ODDS))
      self.assertEqual(conditions.default_escalation_cap(), bc.DEFAULT_ESCALATION_CAP)
      self.assertEqual(conditions.template_slots("volatile"), list(bc.VOLATILE_TEXT_SLOTS))
      self.assertEqual(conditions.template_slots("field_condition"), list(bc.CONDITION_TEXT_SLOTS))
      self.assertEqual(conditions.template_slots("status"), [])

   def test_budget(self) -> None:
      """!The Starter's budgets: two volatiles, one with a counter, four statuses in four id bits.
      @return None
      """
      rows = {r.label: r for r in conditions.budget(self.project.battle)}
      self.assertEqual((rows["volatile bits"].used, rows["volatile bits"].most), (2, 32))
      self.assertEqual((rows["volatile counters"].used, rows["volatile counters"].most), (1, 8))
      self.assertEqual((rows["volatile words"].used, rows["volatile words"].most), (0, 4))
      self.assertEqual(rows["status ids"].used, 4)
      self.assertIn("4 id bits", rows["status ids"].note)
      self.assertEqual(rows["side conditions"].most, 16)

   def test_add_set_text_undo(self) -> None:
      """!A side condition with layers, a tag, texts and an engine message compiles; one undo step each.
      @return None
      """
      doc = self.project.battle
      before = copy.deepcopy(doc.data)
      with doc.edit("Tag"):
         flags.add_name(doc, flags.TAGS_KEY, "grounded")
      with doc.edit("Add"):
         self.assertEqual(conditions.add_record(doc, "side_condition", "spikes"), 0)
      with doc.edit("Set"):
         conditions.set_field(doc, "side_condition", "spikes", "layers", 3)
         conditions.set_field(doc, "side_condition", "spikes", "tags", ["grounded"])
         conditions.set_text(doc, "side_condition", "spikes", "start", "Spikes lie around {target}!")
         conditions.set_text(doc, "side_condition", "spikes", "end", {"message": "failed"})
      self.assertEqual(battle.structure_doc(doc).data["side_conditions"],
                       [{"name": "spikes", "layers": 3, "tags": ["grounded"],
                         "texts": {"start": "Spikes lie around {target}!", "end": {"message": "failed"}}}])
      self.assertIsNone(self.project.validate())
      self.assertEqual([s for s, _v in conditions.texts_of(doc, "side_condition", "spikes")], ["start", "end"])
      for bad in ("{status} hi", "{@nothing}"):
         with self.assertRaises(DocumentError):
            conditions.set_text(doc, "side_condition", "spikes", "start", bad)
      with self.assertRaisesRegex(DocumentError, "engine message"):
         conditions.set_text(doc, "side_condition", "spikes", "end", {"message": "no_such"})
      # an optional engine message the data leaves out cannot be named (C1); the pickers do not offer it
      bc = engine.tool("battle_compiler")
      absent = [m for m in bc.OPTIONAL_MESSAGES if m not in doc.data["messages"]]
      self.assertTrue(absent, "the Starter leaves optional messages out")
      self.assertFalse(set(absent) & set(conditions.messages(doc)))
      self.assertFalse(set(absent) & set(chart.message_keys(doc)))
      self.assertEqual(conditions.messages(), [m for m in bc.MESSAGES if m in bc.REQUIRED_MESSAGES])
      with self.assertRaisesRegex(DocumentError, "engine message"):
         conditions.set_text(doc, "side_condition", "spikes", "end", {"message": absent[0]})
      with self.assertRaisesRegex(DocumentError, "engine message"):
         chart.set_option(doc, "above", absent[0])
      with self.assertRaisesRegex(DocumentError, "text slots"):
         conditions.set_text(doc, "status", "Scorch", "start", "x")
      with self.assertRaisesRegex(DocumentError, "already"):
         conditions.add_record(doc, "side_condition", "spikes")
      for _ in range(3):
         doc.undo()
      self.assertEqual(doc.data, before)

   def test_field_values(self) -> None:
      """!Values are stored as the compiler reads them; defaults are left out; bad values are refused.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Fields"):
         conditions.set_field(doc, "volatile", "flinch", "duration", [2, 5])
         conditions.set_field(doc, "volatile", "flinch", "counts", "end_of_turn")
         conditions.set_field(doc, "volatile", "flinch", "clears_on", ["faint"])
         conditions.set_field(doc, "volatile", "dazed", "hud", True)
         conditions.set_field(doc, "status", "Blight", "escalating", 8)
         conditions.set_field(doc, "status", "Shock", "skip", "1/3")
      flinch = conditions.record(doc, "volatile", "flinch")
      self.assertEqual((flinch["duration"], flinch["counts"], flinch["clears_on"]), ([2, 5], "end_of_turn", ["faint"]))
      self.assertTrue(conditions.has_counter(flinch))
      self.assertEqual(conditions.record(doc, "status", "Blight")["escalating"], {"cap": 8})
      self.assertIsNone(self.project.validate())
      with doc.edit("Defaults"):
         conditions.set_field(doc, "volatile", "flinch", "duration", "turn")   # counts goes with the range
         conditions.set_field(doc, "volatile", "flinch", "clears_on", conditions.clear_events())
         conditions.set_field(doc, "volatile", "dazed", "hud", False)
         conditions.set_field(doc, "status", "Blight", "escalating", conditions.default_escalation_cap())
      self.assertNotIn("counts", flinch)
      self.assertNotIn("clears_on", flinch)
      self.assertNotIn("hud", conditions.record(doc, "volatile", "dazed"))
      self.assertIs(conditions.record(doc, "status", "Blight")["escalating"], True)
      add_flag_records(doc)
      self.assertIsNone(self.project.validate())
      bad = [("status", "Scorch", "residual", "9/2"), ("status", "Scorch", "turns", [3, 1]),
             ("status", "Scorch", "immune_types", ["Nothing"]), ("status", "Frost", "thawed_by_move", "nope"),
             ("volatile", "flinch", "counts", "end_of_turn"), ("volatile", "guard_chain", "chain", {"den": 1}),
             ("volatile", "flinch", "tags", ["undeclared"]), ("weather", "Storm", "turns", 300),
             ("status", "Scorch", "name", "x")]
      for kind, name, key, value in bad:
         with self.assertRaises(DocumentError, msg=(kind, key, value)):
            with doc.edit("Bad"):
               conditions.set_field(doc, kind, name, key, value)

   def test_rename_follows_logic_and_remove(self) -> None:
      """!A volatile's rename rewrites its owner block and the moves naming it (one undo step); removal is refused
      while logic names it.
      @return None
      """
      doc = self.project.structure   # its edits change the structure manifest (undo there)
      logic.attach(self.project)
      with doc.edit("Rename"):
         n = conditions.rename_record(doc, "volatile", "dazed", "stunned")
      self.assertGreaterEqual(n, 2)
      text = source_text(self.project)
      for written in ('volatile "stunned" {', "holder.has(stunned)", "vol_on target stunned;"):
         self.assertTrue(written in text, written)
      self.assertFalse("vol_on target dazed" in text)
      self.assertIsNone(self.project.validate())
      doc.undo()
      self.assertIn("dazed", conditions.names(doc, "volatile"))
      self.assertNotIn("stunned", source_text(self.project))
      with self.assertRaisesRegex(DocumentError, "still named by"):
         conditions.remove_record(doc, "volatile", "flinch")   # Shadow Bite's logic starts it
      with doc.edit("Remove"):
         conditions.add_record(doc, "field_condition", "gravity")
         conditions.remove_record(doc, "field_condition", "gravity")
      self.assertEqual(conditions.names(doc, "field_condition"), [])

   def test_bench_uses(self) -> None:
      """!Saved bench scenarios naming a volatile or status are reported.
      @return None
      """
      bench = self.dir / "bench"
      bench.mkdir()
      (bench / "poke.json").write_text(json.dumps({"schema": "capsule.bench/1", "pokes": [
         {"party": 0, "member": 0, "volatiles": ["dazed"], "status": "Scorch"}]}), encoding="utf-8")
      self.assertEqual(conditions.bench_uses(self.project, "volatile", "dazed"), ["bench/poke.json: pokes[0]"])
      self.assertEqual(conditions.bench_uses(self.project, "status", "Scorch"), ["bench/poke.json: pokes[0].status"])
      self.assertEqual(conditions.bench_uses(self.project, "status", "Doze"), [])


class FlagModelTests(BattleTestCase):
   """!Move flags and tags."""

   def test_flag_rename_follows(self) -> None:
      """!A move flag's rename follows moves, a status's thawed_by_move, a chain's kept_by and the logic.
      @return None
      """
      doc = self.project.battle
      logic.attach(self.project)
      counts = flags.use_counts(doc, flags.FLAGS_KEY)
      self.assertGreater(counts["protect"], 0)
      add_flag_records(doc)
      self.assertIsNone(self.project.validate())
      with doc.edit("Rename"):
         flags.rename_name(doc, flags.FLAGS_KEY, "thaws", "melts")
         flags.rename_name(doc, flags.FLAGS_KEY, "guarding", "warding")
      self.assertEqual(conditions.record(doc, "status", "Frost")["thawed_by_move"], "melts")
      self.assertEqual(conditions.record(doc, "volatile", "guard_chain")["chain"]["kept_by"], "warding")
      self.assertIn("melts", flags.names(doc, flags.FLAGS_KEY))
      self.assertIn("warding", battle.entry(doc, "moves", "Harden")["flags"])
      with doc.edit("Rename"):
         flags.rename_name(doc, flags.FLAGS_KEY, "contact", "touch")   # named by passive Static Coat's logic
      self.assertTrue("move.has(touch)" in source_text(self.project))
      self.assertIsNone(self.project.validate())
      doc.undo()
      self.assertFalse("move.has(touch)" in source_text(self.project))
      doc.undo()
      self.assertEqual(conditions.record(doc, "status", "Frost")["thawed_by_move"], "thaws")
      with self.assertRaisesRegex(DocumentError, "still used by"):
         flags.remove_name(doc, flags.FLAGS_KEY, "contact")
      with doc.edit("Remove"):
         flags.remove_name(doc, flags.FLAGS_KEY, "spare")
      with self.assertRaisesRegex(DocumentError, "lower-case identifier"):
         flags.add_name(doc, flags.FLAGS_KEY, "Two words")
      with doc.edit("Move"):
         self.assertTrue(flags.move_name(doc, flags.FLAGS_KEY, "protect", -1))
      self.assertEqual(flags.names(doc, flags.FLAGS_KEY)[0], "protect")
      self.assertIsNone(self.project.validate())

   def test_tags(self) -> None:
      """!A tag's rename follows the records naming it; the list's cap is the engine's.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Tags"):
         flags.add_name(doc, flags.TAGS_KEY, "airborne")
         conditions.set_field(doc, "volatile", "dazed", "tags", ["airborne"])
      self.assertEqual(flags.use_counts(doc, flags.TAGS_KEY), {"airborne": 1})
      with doc.edit("Rename"):
         self.assertEqual(flags.rename_name(doc, flags.TAGS_KEY, "airborne", "flying"), 1)
      self.assertEqual(conditions.record(doc, "volatile", "dazed")["tags"], ["flying"])
      self.assertIsNone(self.project.validate())
      self.assertEqual(flags.max_names(flags.TAGS_KEY), engine.tool("battle_compiler").MAX_TAGS)


class CategoryAndHolderTests(BattleTestCase):
   """!Categories, passives / items and point handlers."""

   def test_categories(self) -> None:
      """!Add (at most the engine's four), damage stats, rename following moves and self_hit, removal rules.
      @return None
      """
      doc = self.project.battle
      logic.attach(self.project)
      with doc.edit("Add"):
         categories.add_category(doc, "mixed", "attack", "protection")
      self.assertIsNone(self.project.validate())
      with self.assertRaisesRegex(DocumentError, "at most 4"):
         categories.add_category(doc, "fifth")
      with self.assertRaisesRegex(DocumentError, "both offense and defense"):
         categories.set_damage(doc, "mixed", "attack", None)
      with self.assertRaisesRegex(DocumentError, "pool stat"):
         categories.set_damage(doc, "mixed", "hp", "defence")
      with doc.edit("Damage"):
         categories.set_damage(doc, "mixed", None, None)
      self.assertFalse(categories.category_rows(doc)[3]["damaging"])
      with doc.edit("Rename"):
         categories.rename_category(doc, "physical", "body")
      self.assertEqual(battle.structure_doc(doc).data["rules"]["self_hit"]["category"], "body")
      self.assertTrue(categories.category_rows(doc)[0]["self_hit"])
      self.assertIsNone(self.project.validate())
      with self.assertRaisesRegex(DocumentError, "still used"):
         categories.remove_category(doc, "elemental")
      with doc.edit("Remove"):
         categories.remove_category(doc, "mixed")
      self.assertEqual(categories.modes(), [categories.BY_MOVE, categories.BY_TYPE])   # E11: category_by_type

   def test_category_by_type(self) -> None:
      """!category_by_type (E11): switching keeps the categories of a type's most common damaging category and
      names status moves' own; a type's category is a damaging one; renames and removals follow the rule; back to
      moves, every move keeps its category; the choices are the compiler's damaging categories.
      @return None
      """
      doc = self.project.structure
      logic.attach(self.project)
      self.assertEqual(categories.mode(doc), categories.BY_MOVE)
      self.assertEqual(categories.damaging_categories(doc), ["physical", "elemental"])
      self.assertEqual(categories.type_rows(doc), [])
      moves = self.project.battle.data["moves"]
      before = {m["name"]: categories.category_of(doc, m) for m in moves}
      with doc.edit("By type"):
         # each Starter type has one physical and one elemental move (and Cosmic two physical ones, with Strike)
         changed = categories.set_mode(doc, categories.BY_TYPE)
      self.assertEqual(categories.mode(doc), categories.BY_TYPE)
      rule = doc.data[categories.BY_TYPE_KEY]
      self.assertEqual(list(rule), [t["name"] for t in self.project.battle.data["types"]])
      self.assertEqual(set(rule.values()), {"physical"})   # ties take the first damaging category
      self.assertEqual(list(doc.data).index(categories.BY_TYPE_KEY), list(doc.data).index("categories") + 1)
      after = {m["name"]: categories.category_of(doc, m) for m in moves}
      self.assertEqual(changed, sum(1 for n in before if before[n] != after[n]))
      self.assertTrue(all("category" not in m for m in moves if after[m["name"]] != "status"))
      self.assertTrue(all(m["category"] == "status" for m in moves if after[m["name"]] == "status"))
      self.assertIsNone(self.project.validate())
      with doc.edit("Fire"):
         categories.set_type_category(doc, "Fire", "elemental")
      self.assertEqual(categories.category_of(doc, battle.entry(self.project.battle, "moves", "Fireball")),
                       "elemental")
      row = next(r for r in categories.type_rows(doc) if r["type"] == "Fire")
      self.assertEqual((row["category"], row["moves"]), ("elemental", 2))
      self.assertIn("types Fire", "\n".join(categories.report(doc)))
      self.assertIsNone(self.project.validate())
      for bad in (lambda: categories.set_type_category(doc, "Fire", "status"),
                  lambda: categories.set_type_category(doc, "Nothing", "physical"),
                  lambda: categories.set_damage(doc, "elemental", None, None),
                  lambda: categories.remove_category(doc, "elemental"),
                  lambda: categories.set_mode(doc, "colour")):
         with self.assertRaises(DocumentError):
            with doc.edit("Refused"):
               bad()
      # renames and removals follow the rule; a new type and a new move fit it
      with doc.edit("Rename"):
         battle.rename_entry(doc, "categories", "elemental", "arcane")
         battle.rename_entry(self.project.battle, "types", "Fire", "Blaze")
      rule = doc.data[categories.BY_TYPE_KEY]
      self.assertEqual(rule["Blaze"], "arcane")
      self.assertEqual(list(rule).index("Blaze"), 0)
      with self.project.battle.edit("New type and move"):
         battle.add_entry(self.project.battle, "types", "Ice")
         battle.add_entry(self.project.battle, "moves", "Chill")
      self.assertEqual(doc.data[categories.BY_TYPE_KEY]["Ice"], "physical")
      self.assertNotIn("category", battle.entry(self.project.battle, "moves", "Chill"))
      self.assertIsNone(self.project.validate())
      with self.project.battle.edit("Type goes"):
         battle.remove_entry(self.project.battle, "moves", "Chill")
         battle.remove_entry(self.project.battle, "types", "Ice")
      self.assertNotIn("Ice", doc.data[categories.BY_TYPE_KEY])
      with doc.edit("By move"):
         categories.set_mode(doc, categories.BY_MOVE)
      self.assertNotIn(categories.BY_TYPE_KEY, doc.data)
      self.assertEqual(categories.category_of(doc, battle.entry(self.project.battle, "moves", "Fireball")), "arcane")
      self.assertIsNone(self.project.validate())

   def test_holders_and_handlers(self) -> None:
      """!Announce flags and manifest point handlers (points the kind may handle; code the parser takes).
      @return None
      """
      doc = self.project.battle
      rows = {r["name"]: r for r in holders.holder_rows(doc, "passives")}
      self.assertFalse(rows["Blaze Heart"]["announce"])
      self.assertTrue(rows["Recharge"]["announce"])
      recharge = [p["name"] for p in doc.data["passives"]].index("Recharge")
      with doc.edit("Announce"):
         holders.set_announce(doc, "passives", "Blaze Heart", True)
         holders.set_announce(doc, "passives", "Recharge", False)
      self.assertNotIn("announce", doc.data["passives"][0])
      self.assertIs(doc.data["passives"][recharge]["announce"], False)
      choices = holders.point_choices(self.project, "passives")
      self.assertIn("power", choices)
      self.assertNotIn("weather", choices)
      with doc.edit("Handler"):
         holders.add_handler(doc, "passives", "Recharge", "power", choices=choices)
         holders.add_handler(doc, "statuses", "Doze", "speed", "{ modify by 0.5; }",
                             holders.point_choices(self.project, "statuses"))
      self.assertEqual(holders.handlers(doc, "passives", "Recharge"), [{"point": "power", "code": holders.NEW_CODE}])
      self.assertIsNone(self.project.validate())
      with self.assertRaises(DocumentError):
         holders.set_handler(doc, "passives", "Recharge", 0, code="{ modify by ; }")
      with self.assertRaisesRegex(DocumentError, "not a point"):
         holders.add_handler(doc, "passives", "Recharge", "weather", choices=choices)
      with doc.edit("Code"):
         holders.set_handler(doc, "passives", "Recharge", 0, code="{ modify by 2; }")
      with doc.edit("Remove"):
         holders.remove_handler(doc, "passives", "Recharge", 0)
      self.assertNotIn("handlers", doc.data["passives"][recharge])


class HitCategoryTests(BattleTestCase):
   """!The hit types' categories (engine C5, structure hit_category_by_type) in the move mode."""

   def test_hit_categories(self) -> None:
      """!On: each type takes its moves' most common damaging category, the key right after "categories"; a type's
      category is a damaging one; renames, removals and new types follow; the type mode drops the table (the engine
      refuses both); off again; the report lists the hit types.
      @return None
      """
      doc = self.project.structure
      logic.attach(self.project)
      bc = engine.tool("battle_compiler")
      self.assertTrue(categories.hit_available())
      self.assertEqual(categories.hit_key(), bc.HIT_CATEGORY_KEY)
      self.assertEqual(categories.hit_rows(doc), [])
      with doc.edit("Hits on"):
         self.assertTrue(categories.set_hit(doc, True))
      key = categories.hit_key()
      table = doc.data[key]
      self.assertEqual(list(table), [t["name"] for t in self.project.battle.data["types"]])
      self.assertEqual(list(doc.data).index(key), list(doc.data).index("categories") + 1)
      self.assertIsNone(self.project.validate())
      categories.check_hit(doc)
      with doc.edit("Fire"):
         categories.set_hit_category(doc, "Fire", "elemental")
      self.assertEqual(doc.data[key]["Fire"], "elemental")
      self.assertIn(f"({key}):", "\n".join(categories.report(doc)))
      for bad in (lambda: categories.set_hit_category(doc, "Fire", "status"),
                  lambda: categories.set_hit_category(doc, "Nothing", "physical"),
                  lambda: categories.set_damage(doc, "elemental", None, None)):
         with self.assertRaises(DocumentError):
            with doc.edit("Refused"):
               bad()
      with doc.edit("Rename"):
         battle.rename_entry(doc, "categories", "elemental", "arcane")
         battle.rename_entry(self.project.battle, "types", "Fire", "Blaze")
      self.assertEqual(doc.data[key]["Blaze"], "arcane")
      with self.project.battle.edit("New type"):
         battle.add_entry(self.project.battle, "types", "Ice")
      self.assertIn("Ice", doc.data[key])
      self.assertIsNone(self.project.validate())
      with self.project.battle.edit("Type goes"):
         battle.remove_entry(self.project.battle, "types", "Ice")
      self.assertNotIn("Ice", doc.data[key])
      with doc.edit("By type"):
         categories.set_mode(doc, categories.BY_TYPE)
      self.assertNotIn(key, doc.data)   # category_by_type gives them
      with self.assertRaises(DocumentError):
         with doc.edit("Both"):
            categories.set_hit(doc, True)
      with doc.edit("By move"):
         categories.set_mode(doc, categories.BY_MOVE)
      with doc.edit("Hits on"):
         categories.set_hit(doc, True)
      with doc.edit("Hits off"):
         self.assertTrue(categories.set_hit(doc, False))
      self.assertNotIn(key, doc.data)
      self.assertIsNone(self.project.validate())


class CommandTests(BattleTestCase):
   """!The `battle FILE condition|flag|tag|category|holder|handler ...` commands."""

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command.
      @param argv  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()

   def saved(self) -> dict:
      """!The battle file as saved.
      @return parsed JSON
      """
      return engine.tool("battle_compiler").view_of(self.dir / "battle.json")   # both manifests as one

   def test_category_hit_commands(self) -> None:
      """!`category hit on|off` and `category hit-type TYPE CATEGORY` (C5) save when they compile.
      @return None
      """
      f = self.dir / "battle.json"
      key = categories.hit_key()
      self.assertEqual(self.run_cli("battle", f, "category", "hit", "on")[0], 0)
      self.assertIn(key, self.saved())
      self.assertEqual(self.run_cli("battle", f, "category", "hit-type", "Fire", "elemental")[0], 0)
      self.assertEqual(self.saved()[key]["Fire"], "elemental")
      status, out = self.run_cli("battle", f, "category", "list")
      self.assertEqual(status, 0)
      self.assertIn("  Fire: elemental", out)
      self.assertEqual(self.run_cli("battle", f, "category", "hit-type", "Fire", "status")[0], 1)
      self.assertEqual(self.run_cli("battle", f, "category", "hit", "off")[0], 0)
      self.assertNotIn(key, self.saved())

   def test_commands(self) -> None:
      """!Edits save when they compile; refused ones save nothing.
      @return None
      """
      f = self.dir / "battle.json"
      status, out = self.run_cli("battle", f, "condition", "budget")
      self.assertEqual(status, 0)
      self.assertIn("volatile bits 2/32", out)
      self.assertEqual(self.run_cli("battle", f, "condition", "side_condition", "add", "spikes")[0], 0)
      self.assertEqual(self.run_cli("battle", f, "condition", "side_condition", "set", "spikes", "layers", "3")[0], 0)
      self.assertEqual(self.run_cli("battle", f, "condition", "side_condition", "text", "spikes", "end",
                                    "--message", "failed")[0], 0)
      self.assertEqual(self.saved()["side_conditions"], [{"name": "spikes", "layers": 3,
                                                          "texts": {"end": {"message": "failed"}}}])
      # A status with turns needs a skip text: the compiler refuses it, nothing is saved.
      status, out = self.run_cli("battle", f, "condition", "status", "set", "Scorch", "turns", "[1, 3]")
      self.assertEqual(status, 1)
      self.assertIn("skip text", out)
      self.assertNotIn("turns", next(s for s in self.saved()["statuses"] if s["name"] == "Scorch"))
      self.assertEqual(self.run_cli("battle", f, "condition", "volatile", "rename", "dazed", "stunned")[0], 0)
      self.assertIn("stunned", [v["name"] for v in self.saved()["volatiles"]])
      self.assertEqual(self.run_cli("battle", f, "flag", "rename", "contact", "touch")[0], 0)
      self.assertIn("touch", next(m for m in self.saved()["moves"] if m["name"] == "Strike")["flags"])
      self.assertIn("move.has(touch)", (self.dir / "effects" / "passives.ceffect").read_text(encoding="utf-8"))
      status, out = self.run_cli("battle", f, "tag", "list")
      self.assertEqual((status, out.strip()), (0, "0/16 tags"))
      self.assertEqual(self.run_cli("battle", f, "category", "add", "mixed", "--offense", "attack", "--defense",
                                    "protection")[0], 0)
      self.assertEqual(self.run_cli("battle", f, "category", "damage", "mixed", "none", "none")[0], 0)
      self.assertEqual(self.saved()["categories"][-1], {"name": "mixed"})
      self.assertEqual(self.run_cli("battle", f, "holder", "items", "announce", "Mana Drop", "off")[0], 0)
      self.assertEqual(self.run_cli("battle", f, "handler", "items", "Mana Drop", "add", "damage")[0], 0)
      status, out = self.run_cli("battle", f, "handler", "items", "Mana Drop", "list")
      self.assertIn("0 point damage", out)
      saved_item = self.saved()["items"][0]
      self.assertEqual((saved_item["announce"], saved_item["handlers"][0]["point"]), (False, "damage"))
      # category_by_type (E11): `category mode` and `category type`
      self.assertEqual(self.run_cli("battle", f, "category", "mode", "type")[0], 0)
      rule = self.saved()["category_by_type"]
      self.assertEqual(len(rule), len(self.saved()["types"]))
      self.assertEqual(self.run_cli("battle", f, "category", "type", "Water", "elemental")[0], 0)
      self.assertEqual(self.saved()["category_by_type"]["Water"], "elemental")
      self.assertEqual(self.run_cli("battle", f, "category", "type", "Water", "mixed")[0], 1)   # not damaging
      status, out = self.run_cli("battle", f, "category", "list")
      self.assertIn("comes from its type (category_by_type)", out)
      self.assertIn("  Water: elemental (2 damaging move(s))", out)
      self.assertEqual(self.run_cli("battle", f, "category", "mode", "move")[0], 0)
      self.assertNotIn("category_by_type", self.saved())


if __name__ == "__main__":
   unittest.main()
