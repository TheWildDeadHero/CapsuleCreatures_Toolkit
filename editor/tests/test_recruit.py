#!/usr/bin/env python3
"""!Tests for recruitment and the storage boxes in the studio (D-26 section 3, engine G3): core.structure.recruit
(the structure's recruit rules, the ruleset's recruit_odds, the items that recruit), core.structure.storage (the
boxes, their budget and the save image, a test save's boxed creatures), core.ai's item-use rules, the renames that
follow, and the `battle FILE recruit|storage|ai rule --items|testsave box ...` commands. No Qt.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase): its recruit section (3 checks, the
recruit_rate field), its 8 boxes of 30 and the Strategist's Tonic rule are read from the sample. The classic class runs
on the reference repo's sample (skipped without it).
"""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import ai, battle, engine, inventory, messages  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import conditions, recruit, species_fields, storage  # noqa: E402
from sample_data import classic_data, needs_classic  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402


def run_cli(*argv: str) -> tuple[int, str]:
   """!Runs the CLI.
   @param argv  arguments
   @return (exit status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      try:
         code = cli(list(argv))
      except SystemExit as e:
         code = int(e.code or 0)
   return code, out.getvalue() + err.getvalue()


class RecruitRulesTests(BattleTestCase):
   """!The structure's recruit section."""

   def test_section_and_lists(self) -> None:
      """!The sample's rules with the defaults filled in; the choice lists are the engine's and the manifests'.
      @return None
      """
      doc = self.project.structure
      bc = engine.tool("battle_compiler")
      self.assertTrue(recruit.is_stated(doc))
      s = recruit.section(doc)
      given = doc.data["recruit"]
      self.assertEqual(s["checks"], given["checks"])
      self.assertEqual(s["rate"], given["rate"])
      self.assertEqual(list(s["status_bonus"]), [bc.RECRUIT_NO_STATUS] + recruit.status_names(doc))
      self.assertEqual(recruit.moments(), list(bc.RECRUIT_MESSAGE_MOMENTS))
      self.assertEqual(recruit.keeps(), list(bc.RECRUIT_KEEPS))
      self.assertEqual(recruit.owned_choices(), list(bc.RECRUIT_OWNED))
      self.assertIn(given["rate"], recruit.rate_choices(doc))
      self.assertTrue(recruit.has_pipeline(self.project))
      self.assertIn("Orb", recruit.recruit_items(self.project))

   def test_edits_and_refusals(self) -> None:
      """!Checks, owned, keep, status bonus, message, break_free: one undo step each; the engine refuses bad ones.
      @return None
      """
      doc = self.project.structure
      with doc.edit("Recruit checks"):
         recruit.set_field(doc, "checks", recruit.max_checks())
      self.assertEqual(doc.data["recruit"]["checks"], recruit.max_checks())
      with self.assertRaises(DocumentError):
         with doc.edit("Recruit checks"):
            recruit.set_field(doc, "checks", recruit.max_checks() + 1)
      with doc.edit("Recruit owned"):
         recruit.set_field(doc, "owned", "allow")
      self.assertEqual(doc.data["recruit"]["owned"], "allow")
      with doc.edit("Recruit owned"):
         recruit.set_field(doc, "owned", recruit.default_owned())
      self.assertNotIn("owned", doc.data["recruit"])
      with doc.edit("Recruit keep"):
         recruit.set_keep(doc, recruit.keeps())
      self.assertNotIn("keep", doc.data["recruit"])
      status = recruit.status_names(doc)[0]
      with doc.edit("Recruit status bonus"):
         recruit.set_status_bonus(doc, status, recruit.max_status_bonus())
      self.assertEqual(recruit.section(doc)["status_bonus"][status], recruit.max_status_bonus())
      with self.assertRaises(DocumentError):
         with doc.edit("Recruit status bonus"):
            recruit.set_status_bonus(doc, status, recruit.max_status_bonus() + 1)
      doc.undo()
      self.assertNotEqual(recruit.section(doc)["status_bonus"][status], recruit.max_status_bonus())
      # a {value} message the section stops naming no longer compiles: the engine's message refuses it
      moment = next(m for m, k in recruit.section(doc)["messages"].items()
                    if k is not None and "{value}" in messages.given(doc)[k])
      with self.assertRaisesRegex(DocumentError, "value"):
         with doc.edit("Recruit message"):
            recruit.set_message(doc, moment, None)
      with self.assertRaisesRegex(DocumentError, "one of"):
         with doc.edit("Recruit message"):
            recruit.set_message(doc, "check", "no_such_message")
      with doc.edit("Recruit break free"):
         recruit.set_break_free(doc, [])
      self.assertNotIn("break_free", doc.data["recruit"])
      self.assertIsNone(self.project.error_now())

   def test_disable_enable_and_pipeline(self) -> None:
      """!Disable takes the section out; enable needs the ruleset's recruit_odds (add_pipeline() writes one).
      @return None
      """
      p = self.project
      # the sample's {value} messages need the section: the engine refuses them without it
      with self.assertRaisesRegex(DocumentError, "value"):
         with p.structure.edit("Disable recruitment"):
            recruit.disable(p.structure)
      for key, text in list(messages.given(p.battle).items()):
         if "{value}" in text:
            with p.battle.edit("Message text"):
               messages.set_text(p.battle, key, text.replace("{value}", "a"))
      with p.structure.edit("Disable recruitment"):
         recruit.disable(p.structure)
      self.assertFalse(recruit.is_stated(p.structure))
      with p.ruleset.edit("Drop pipeline"):
         del p.ruleset.data["pipelines"][recruit.pipeline_name()]
      self.assertIsNone(p.error_now())
      with self.assertRaisesRegex(DocumentError, "recruit_odds"):
         with p.structure.edit("Enable recruitment"):
            recruit.enable(p.structure)
      with p.ruleset.edit("Add recruit_odds"):
         recruit.add_pipeline(p.ruleset)
      with p.structure.edit("Enable recruitment"):
         recruit.enable(p.structure)
      self.assertEqual(p.structure.data["recruit"], {"checks": recruit.NEW_CHECKS})
      self.assertIsNone(p.error_now())
      row = recruit.odds(p, {"recruit_rate": 20, "bonus": 5, "status_bonus": 0})
      self.assertEqual((row["chance"], row["out_of"], row["sure"]), (25, recruit.NEUTRAL_OUT_OF, False))
      self.assertTrue(recruit.odds(p, {"bonus": recruit.NEUTRAL_OUT_OF})["sure"])

   def test_odds_match_the_engine(self) -> None:
      """!The preview is the compiled pipeline run as the engine runs it (the Starter's formula worked by hand).
      @return None
      """
      p = self.project
      constants = p.ruleset.data["constants"]
      species = battle.entries(p.battle, "species")[0]["name"]
      rate = recruit.species_rate(p, species)
      row = recruit.odds(p, {"recruit_rate": rate, "bonus": 5, "target_hp": 10, "target_max_hp": 40})
      missing = (40 - 10) * recruit.PERCENT // 40
      want = min(recruit.PERCENT, rate * (recruit.PERCENT + missing) // constants["RECRUIT_RATE_DIV"] + 5)
      self.assertEqual(row["chance"], want)
      self.assertAlmostEqual(row["all_checks"], (want / recruit.PERCENT) ** row["checks"] * recruit.PERCENT)
      self.assertTrue(recruit.odds(p, {"bonus": constants["RECRUIT_SURE"]})["sure"])
      self.assertIn("checks", recruit.odds_text(row))

   def test_recruit_logic(self) -> None:
      """!An item made to recruit: battle use, battler target, `recruit holder N;` (a new bonus replaces the old).
      @return None
      """
      p = self.project
      item = next(i["name"] for i in battle.entries(p.battle, "items")
                  if i.get("use", "none") == "none" and i.get("pocket") is not None)
      with p.battle.edit("Recruit logic"):
         recruit.set_recruit_logic(p, item, 7)
      f = inventory.fields_of(p.battle, item)
      self.assertIn(f["use"], ("battle", "both"))
      self.assertEqual(f["target"], recruit.BATTLER_TARGET)
      self.assertEqual(recruit.recruit_bonus(p, item), "7")
      with p.battle.edit("Recruit logic"):
         recruit.set_recruit_logic(p, item, 9)
      self.assertEqual(recruit.recruit_bonus(p, item), "9")
      self.assertEqual(inventory.use_logic(p, item)["use_battle"].count("recruit"), 1)
      self.assertIsNone(p.error_now())
      with self.assertRaises(DocumentError):
         with p.battle.edit("Recruit logic"):
            recruit.set_recruit_logic(p, item, recruit.max_bonus() + 1)

   def test_renames_follow(self) -> None:
      """!A status, species field or message rename follows into the section.
      @return None
      """
      doc = self.project.structure
      status = next(k for k in doc.data["recruit"]["status_bonus"] if k != recruit.no_status())
      with doc.edit("Rename status"):
         conditions.rename_record(doc, "status", status, "Snooze")
      self.assertIn("Snooze", doc.data["recruit"]["status_bonus"])
      with doc.edit("Rename field"):
         species_fields.rename_field(doc, doc.data["recruit"]["rate"], "catchiness")
      self.assertEqual(doc.data["recruit"]["rate"], "catchiness")
      key = doc.data["recruit"]["messages"]["check"]
      with self.project.battle.edit("Rename message"):
         messages.rename(self.project.battle, key, "orb_shakes")
      self.assertEqual(doc.data["recruit"]["messages"]["check"], "orb_shakes")
      self.assertIn("recruit: messages.check", messages.uses(self.project.battle, "orb_shakes"))
      self.assertIsNone(self.project.error_now())


class StorageTests(BattleTestCase):
   """!The storage boxes and a test save's boxed creatures."""

   def test_boxes_budget_and_save(self) -> None:
      """!The sample's boxes, the budget against the engine's limits, the save image's Boxes section.
      @return None
      """
      doc = self.project.structure
      given = doc.data["storage"]
      self.assertEqual(storage.slot_count(doc), given["box_count"] * given["box_size"])
      self.assertEqual(storage.box_names(doc)[0], given["names"].replace("{n}", "1"))
      bs = engine.tool("build_settings")
      text, over = storage.budget(doc, ["gba"])
      self.assertIn(f"/{bs.platform_limits('gba')['max_boxes']} boxes", text)
      self.assertFalse(over)
      compiled = self.project.compile()[0]
      want = engine.tool("save_layout").boxes_bytes(compiled)
      self.assertIn(f"boxes {want} B", storage.save_report(self.project)[0])

   def test_edits(self) -> None:
      """!Count, size, a box renamed (the pattern becomes a list that follows the count), limits refused.
      @return None
      """
      doc = self.project.structure
      with doc.edit("Rename box"):
         storage.rename_box(doc, 0, "Home")
      names = doc.data["storage"]["names"]
      self.assertEqual(len(names), doc.data["storage"]["box_count"])
      self.assertEqual(names[0], "Home")
      with doc.edit("Storage box_count"):
         storage.set_field(doc, "box_count", 2)
      self.assertEqual(len(doc.data["storage"]["names"]), 2)
      with doc.edit("Storage names"):
         storage.set_names(doc, storage.default_names())
      self.assertNotIn("names", doc.data["storage"])
      most = storage.limits(["gba"])["max_boxes"]
      with self.assertRaises(DocumentError):
         with doc.edit("Storage box_count"):
            storage.set_field(doc, "box_count", most + 1)
      with doc.edit("Disable storage"):
         storage.disable(doc)
      self.assertFalse(storage.is_stated(doc))
      with doc.edit("Enable storage"):
         storage.enable(doc)
      self.assertEqual(storage.slot_count(doc), storage.NEW_COUNT * storage.NEW_SIZE)
      self.assertIsNone(self.project.error_now())

   def test_test_save_boxes(self) -> None:
      """!Boxed creatures in a test save: the current box first, checks, the image's Boxes section records.
      @return None
      """
      p = self.project
      save = inventory.new_testsave(p, "boxes")
      species = battle.entries(p.battle, "species")[0]["name"]
      size = storage.section(p.battle)["box_size"]
      with save.edit("Box"):
         storage.set_current_box(save, p.battle, 1)
         slot = storage.put_creature(save, p.battle, species, 9)
      self.assertEqual(slot, size)
      with self.assertRaises(DocumentError):
         storage.put_creature(save, p.battle, species, 9, slot)
      with self.assertRaises(DocumentError):
         storage.put_creature(save, p.battle, "Nobody")
      self.assertEqual(inventory.check(save, p.battle), [])
      image = inventory.image_of(save, p)
      compiled = p.compile()[0]
      sl = engine.tool("save_layout")
      rt = engine.tool("record_transfer")
      boxes = sl.boxes_payload(compiled, storage.records_of(save, compiled), 1)
      self.assertIn(boxes, image)
      table = engine.tool("battle_compiler").compile_transfer(compiled["layout"], compiled["stats"], "test")
      record = storage.records_of(save, compiled)[slot]
      self.assertEqual(rt.unpack(table, record)["level"], 9)
      with save.edit("Unbox"):
         storage.remove_creature(save, slot)
      self.assertEqual(storage.boxed_of(save), [])
      save.data["boxes"] = [{"slot": storage.slot_count(p.battle), "species": species, "level": 1}]
      self.assertTrue(any("slot" in problem for problem in inventory.check(save, p.battle)))


class AiItemRuleTests(BattleTestCase):
   """!The AI profiles' item-use rules."""

   def test_rules(self) -> None:
      """!The engine's kinds and numbers; add (an item used in battle), set the item, refusals; renames follow.
      @return None
      """
      doc = self.project.battle
      bc = engine.tool("battle_compiler")
      self.assertEqual(ai.rule_kinds(ai.ITEMS_KEY), list(bc.AI_ITEM_RULES))
      self.assertIn(ai.ITEMS_KEY, ai.RULE_LISTS)
      name = next(r["name"] for r in ai.profile_rows(doc) if r["items"])
      rows = ai.rule_rows(doc, name, ai.ITEMS_KEY)
      self.assertIsNotNone(rows[0]["item"])
      choices = ai.item_choices(doc)
      with doc.edit("Add AI rule"):
         ai.add_rule(doc, name, "below_hp", ai.ITEMS_KEY, args={"percent": 50})
      self.assertEqual(ai.rule_rows(doc, name, ai.ITEMS_KEY)[-1]["item"], choices[0])
      with doc.edit("Set AI rule item"):
         ai.set_rule_item(doc, name, len(rows), choices[-1])
      self.assertEqual(ai.rule_rows(doc, name, ai.ITEMS_KEY)[-1]["item"], choices[-1])
      plain = next(i["name"] for i in battle.entries(doc, "items") if i["name"] not in choices)
      with self.assertRaises(DocumentError):
         with doc.edit("Add AI rule"):
            ai.add_rule(doc, name, "below_hp", ai.ITEMS_KEY, item=plain)
      with self.assertRaises(DocumentError):
         with doc.edit("Add AI rule"):
            ai.add_rule(doc, name, "noise", ai.RULES_KEY, item=choices[0])
      item = rows[0]["item"]
      with doc.edit("Rename item"):
         battle.rename_entry(doc, "items", item, "Big Tonic")
      self.assertEqual(ai.rule_rows(doc, name, ai.ITEMS_KEY)[0]["item"], "Big Tonic")
      carriers = [t for t in battle.entries(doc, "parties") if "Big Tonic" in (t.get("items") or [])]
      self.assertTrue(carriers)
      self.assertIsNone(self.project.error_now())
      self.assertTrue(any("item-use" in line for line in ai.rule_lines(doc, name)))


class RecruitCommandTests(BattleTestCase):
   """!The recruit, storage, ai --items and testsave box commands."""

   def test_commands(self) -> None:
      """!Show, set, odds, storage show / set / rename, an item rule, boxing in a test save and its export.
      @return None
      """
      f = str(self.dir / "battle.json")
      code, out = run_cli("battle", f, "recruit", "show")
      self.assertEqual(code, 0, out)
      self.assertIn("items that recruit: Orb", out)
      self.assertEqual(run_cli("battle", f, "recruit", "set", "checks", "2")[0], 0)
      code, out = run_cli("battle", f, "recruit", "odds", "target_hp=1", "target_max_hp=2", "--species",
                          battle.entries(self.project.battle, "species")[0]["name"])
      self.assertEqual(code, 0, out)
      self.assertIn("2 checks", out)
      code, out = run_cli("battle", f, "storage", "show")
      self.assertEqual(code, 0, out)
      self.assertIn("save image", out)
      self.assertEqual(run_cli("battle", f, "storage", "rename", "0", "Home")[0], 0)
      code, out = run_cli("battle", f, "ai", "rules", "--items")
      self.assertIn("below_hp", out)
      self.assertEqual(run_cli("battle", f, "testsave", "new", "cli")[0], 0)
      species = battle.entries(self.project.battle, "species")[0]["name"]
      code, out = run_cli("battle", f, "testsave", "box", "cli", "put", species, "4")
      self.assertEqual((code, out.strip()), (0, "slot 0"), out)
      code, out = run_cli("battle", f, "testsave", "show", "cli")
      self.assertIn(f"Home slot 0: {species} level 4", out)
      sav = self.dir / "cli.sav"
      self.assertEqual(run_cli("battle", f, "testsave", "export", "cli", str(sav))[0], 0)
      self.assertTrue(sav.read_bytes().startswith(b"CCSV"))
      code, out = run_cli("battle", f, "recruit", "set", "checks", "99")
      self.assertNotEqual(code, 0)


@needs_classic
class ClassicRecruitTests(BattleTestCase):
   """!The reference repo's classic sample: 4 checks and the classic catch formula through the studio's preview."""

   def sample(self) -> Path:
      """!The classic sample.
      @return its folder
      """
      found = classic_data()
      assert found is not None
      return found

   def test_classic_odds(self) -> None:
      """!A catch rate 45 creature at full HP with a Capture Ball: the public classic shake odds.
      @return None
      """
      p = self.project
      self.assertEqual(recruit.section(p.structure)["checks"], 4)
      rc = engine.tool("ruleset_compiler")
      none = recruit.section(p.structure)["status_bonus"][recruit.no_status()]
      row = recruit.odds(p, {"recruit_rate": 45, "bonus": 10, "target_hp": 30, "target_max_hp": 30,
                             "status_bonus": none})
      odds = 45 * 10 // 10 * (30 * 3 - 30 * 2) // (30 * 3) * none // 10
      self.assertEqual(row["chance"], 1048560 // rc.isqrt(rc.isqrt(16711680 // odds)))
      self.assertEqual(storage.slot_count(p.structure), 14 * 30)


if __name__ == "__main__":
   unittest.main()
