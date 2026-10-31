#!/usr/bin/env python3
"""!Tests for the studio side of the engine's G1 (D-26 section 1), no Qt:

- AI profiles (core.ai, `battle FILE ai ...`): the engine's rule names and numbers, profiles and rules edited
  (refusals with the engine's messages), a rename following the parties and the bench scenarios, the parties'
  profile, the former AI flags migrated (the engine's tools/battle_ai.py), the ai_score hook's catalog entry;
- delayed hits (core.structure.delayed_hits, `battle FILE delayed-hit ...`): records, a rename following the
  effect logic, a removal refused while logic names it;
- bound_to on the Conditions page's volatiles (core.structure.conditions: the engine's BOUND_TO, the budget row);
- the logic editor's `use_move ... unless FLAG` (the kwid signature kind: fields, rename following the flag), the
  name lists (delayed hits, AI profiles) and the palette (delay hit, absorb).

Expected values come from the data or the engine, not written down.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import ai, bench, engine, logic  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import conditions, delayed_hits  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## The Starter's AI profiles (samples/starter/battle.json, G1) and a party naming one.
STARTER_DEFAULT, STARTER_BATTLER, PARTY = "Basic", "Battler", "Novice Kit"


def run_cli(*argv: str) -> tuple[int, str]:
   """!Runs the CLI.
   @param argv  arguments
   @return (exit status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      try:
         status = cli(list(argv))
      except SystemExit as e:
         status = int(e.code or 0)
   return status, out.getvalue() + err.getvalue()


class AiProfileTests(BattleTestCase):
   """!AI profiles on a copy of the Starter."""

   def test_engine_lists(self) -> None:
      """!The rule names, numbers, caps and the hook are the engine's.
      @return None
      """
      bc = engine.tool("battle_compiler")
      self.assertEqual(ai.rule_kinds(), list(bc.AI_RULES))
      self.assertEqual(ai.rule_kinds(ai.SWITCHING_KEY), list(bc.AI_SWITCH_RULES))
      lo, hi, default = ai.rule_args(ai.RULES_KEY, "noise")["max"]
      self.assertEqual((lo, hi, default), bc.AI_RULE_ARGS["noise"]["max"][1:])
      self.assertEqual(ai.max_profiles(), bc.MAX_AI_PROFILES)
      self.assertEqual(ai.max_rules(), bc.MAX_AI_RULES)
      self.assertEqual(ai.implicit_profile(), bc.AI_DEFAULT_PROFILE)
      hook = ai.hook_entry()
      self.assertTrue(hook["pure"])
      self.assertIn("move", hook["owners"])
      with self.assertRaises(DocumentError):
         ai.rule_args(ai.RULES_KEY, "telepathy")

   def test_rows(self) -> None:
      """!Profiles with their users and the default; rules with the engine's defaults filled in.
      @return None
      """
      doc = self.project.battle
      self.assertEqual(ai.default_name(doc), STARTER_DEFAULT)
      rows = {r["name"]: r for r in ai.profile_rows(doc)}
      self.assertTrue(rows[STARTER_DEFAULT]["default"])
      self.assertIn(f"party {PARTY}", rows[STARTER_BATTLER]["parties"])
      rules = ai.rule_rows(doc, STARTER_BATTLER)
      self.assertEqual([r["rule"] for r in rules], ["noise", "damage", "avoid_useless", "status_move"])
      self.assertEqual(rules[1]["args"], {"weight": 4, "ko_bonus": 40})
      self.assertEqual(ai.party_profile(doc, PARTY), STARTER_BATTLER)
      self.assertTrue(ai.lines(doc))
      self.assertTrue(ai.rule_lines(doc, STARTER_BATTLER))

   def test_edit_profiles(self) -> None:
      """!Add (a copy), rename (parties follow), move, default, remove (refused while used and for the last one).
      @return None
      """
      doc = self.project.battle
      with doc.edit("add"):
         ai.add_profile(doc, "Careful", like=STARTER_BATTLER)
      self.assertEqual(ai.rule_rows(doc, "Careful"), ai.rule_rows(doc, STARTER_BATTLER))
      with doc.edit("rename"):
         ai.rename_profile(doc, STARTER_BATTLER, "Fighter")
      self.assertEqual(ai.party_profile(doc, PARTY), "Fighter")
      self.assertIsNone(self.project.error_now())
      with self.assertRaisesRegex(DocumentError, "used by"):
         with doc.edit("remove"):
            ai.remove_profile(doc, "Fighter")
      with doc.edit("party"):
         ai.set_party_profile(doc, PARTY, None)
      self.assertIsNone(ai.party_profile(doc, PARTY))
      with doc.edit("default"):
         ai.set_default(doc, "Careful")
      self.assertEqual(ai.default_name(doc), "Careful")
      names = ai.profile_names(doc)
      with doc.edit("move"):
         ai.move_profile(doc, "Careful", -1)
      self.assertEqual(ai.profile_names(doc).index("Careful"), names.index("Careful") - 1)
      with self.assertRaisesRegex(DocumentError, "already"):
         with doc.edit("dup"):
            ai.add_profile(doc, STARTER_DEFAULT)
      self.assertIsNone(self.project.error_now())

   def test_edit_rules(self) -> None:
      """!Rules: add (the engine's numbers, ranges refused), move, set a number and back to its default, remove; a
      pipeline rule without the ruleset's ai_score pipeline is refused with the engine's message.
      @return None
      """
      doc = self.project.battle
      with doc.edit("add"):
         ai.add_rule(doc, STARTER_BATTLER, "hook")
         ai.add_rule(doc, STARTER_BATTLER, "below", ai.SWITCHING_KEY, args={"score": 10})
      self.assertEqual(ai.rule_rows(doc, STARTER_BATTLER)[-1]["rule"], "hook")
      self.assertEqual(ai.rule_rows(doc, STARTER_BATTLER, ai.SWITCHING_KEY)[0]["args"], {"score": 10})
      with doc.edit("set"):
         ai.set_rule_arg(doc, STARTER_BATTLER, 1, "weight", 6)
      self.assertEqual(ai.rule_rows(doc, STARTER_BATTLER)[1]["args"]["weight"], 6)
      with doc.edit("reset"):
         ai.set_rule_arg(doc, STARTER_BATTLER, 1, "weight", None)
      self.assertNotIn("weight", ai.rule_rows(doc, STARTER_BATTLER)[1]["stated"])
      hi = ai.rule_args(ai.RULES_KEY, "damage")["weight"][1]
      with self.assertRaisesRegex(DocumentError, "weight"):
         with doc.edit("bad"):
            ai.set_rule_arg(doc, STARTER_BATTLER, 1, "weight", hi + 1)
      with self.assertRaisesRegex(DocumentError, "ai_score"):
         with doc.edit("pipeline"):
            ai.add_rule(doc, STARTER_BATTLER, "pipeline")
      with doc.edit("move"):
         ai.move_rule(doc, STARTER_BATTLER, 0, 1)
      self.assertEqual(ai.rule_rows(doc, STARTER_BATTLER)[1]["rule"], "noise")
      with doc.edit("remove"):
         ai.remove_rule(doc, STARTER_BATTLER, 0, ai.SWITCHING_KEY)
      self.assertEqual(ai.rule_rows(doc, STARTER_BATTLER, ai.SWITCHING_KEY), [])
      self.assertIsNone(self.project.error_now())

   def test_bench_follows(self) -> None:
      """!A bench scenario's party "ai" is a name slot; a profile rename rewrites it.
      @return None
      """
      scenario = {"schema": "capsule.bench/1", "seed": 1,
                  "parties": [{"side": 0, "data": PARTY}, {"side": 1, "ai": STARTER_BATTLER,
                                                           "members": [{"species": "Sproutle", "level": 5}]}]}
      slots = [s for s in bench.name_slots(scenario) if s.list_key == ai.NAMES_LIST]
      self.assertEqual([s.name for s in slots], [STARTER_BATTLER])
      self.assertIn(ai.NAMES_LIST, bench.SCENARIO_LISTS)
      self.assertIn(STARTER_BATTLER, logic.name_lists(self.project)[ai.NAMES_LIST])

   def test_migrate(self) -> None:
      """!The former party AI flags become profiles (the engine's tool); data then compiles.
      @return None
      """
      doc = self.project.battle
      with doc.edit("flags"):
         doc.data.pop(ai.PROFILES_KEY)
         for p in doc.data["parties"]:
            p["ai"] = ["damage", "avoid_useless"]
      self.assertTrue(ai.flag_parties(doc))
      with doc.edit("migrate"):
         notes = ai.migrate_flags(doc)
      self.assertTrue(notes)
      self.assertFalse(ai.flag_parties(doc))
      self.assertIsNone(self.project.error_now())

   def test_cli(self) -> None:
      """!`battle FILE ai ...` lists, shows, edits and saves.
      @return None
      """
      path = str(self.dir / "battle.json")
      status, out = run_cli("battle", path, "ai", "list")
      self.assertEqual(status, 0, out)
      self.assertIn(f"{STARTER_DEFAULT} (default)", out)
      status, out = run_cli("battle", path, "ai", "rules", "--switching")
      self.assertEqual(status, 0, out)
      self.assertIn("below", out)
      self.assertEqual(run_cli("battle", path, "ai", "hook")[0], 0)
      status, out = run_cli("battle", path, "ai", "rule", STARTER_BATTLER, "add", "noise", "max=8")
      self.assertEqual(status, 0, out)
      data = json.loads((self.dir / "battle.json").read_text(encoding="utf-8"))
      battler = next(p for p in data[ai.PROFILES_KEY] if p["name"] == STARTER_BATTLER)
      self.assertEqual(battler["rules"][-1], {"rule": "noise", "max": 8})
      status, out = run_cli("battle", path, "ai", "rename", STARTER_BATTLER, "Fighter")
      self.assertEqual(status, 0, out)
      status, out = run_cli("battle", path, "ai", "party", PARTY)
      self.assertEqual((status, out.strip()), (0, "Fighter"))
      status, out = run_cli("battle", path, "ai", "show", "Fighter")
      self.assertIn("noise (max 8)", out)
      self.assertNotEqual(run_cli("battle", path, "ai", "remove", "Fighter")[0], 0)


class DelayedHitTests(BattleTestCase):
   """!Delayed hits on a copy of the Starter (it has none: the tests add them)."""

   def test_edit(self) -> None:
      """!Add, set every field, rename following the logic, removal refused while named, the CLI.
      @return None
      """
      doc = self.project.structure
      self.assertEqual(delayed_hits.at_use_names(), list(engine.tool("battle_compiler").DELAYED_AT_USE))
      with doc.edit("add"):
         delayed_hits.add_hit(doc, "sight")
      row = delayed_hits.hit_rows(doc)[0]
      self.assertEqual(row["at_use"], delayed_hits.at_use_names())
      self.assertEqual(row["miss_message"], delayed_hits.default_miss_message())
      with doc.edit("set"):
         delayed_hits.set_at_use(doc, "sight", ["level", "stats"])
         delayed_hits.set_flag(doc, "sight", "typed", False)
         delayed_hits.set_accuracy(doc, "sight", delayed_hits.max_accuracy())
      row = delayed_hits.hit_rows(doc)[0]
      self.assertEqual(row["at_use"], ["stats", "level"])   # the engine's order
      self.assertFalse(row["flags"]["typed"])
      self.assertEqual(row["accuracy"], delayed_hits.max_accuracy())
      with self.assertRaises(DocumentError):
         with doc.edit("bad"):
            delayed_hits.set_accuracy(doc, "sight", delayed_hits.max_accuracy() + 1)
      # logic naming it: a rename follows, a removal is refused
      rel = "effects/moves.ceffect"
      source = self.project.effect_source(rel)
      text = source.text + '\nmove "Strike" {\n   use {\n      delay_hit target 2 sight;\n   }\n}\n'
      with doc.edit("phase"):
         doc.data["turn"]["end_of_turn"].insert(0, {"run": "delayed"})   # where delayed hits land
      logic.set_source_text(self.project, rel, text)
      self.assertIsNone(self.project.error_now())
      self.assertIn("move Strike", delayed_hits.hit_rows(doc)[0]["users"][0])
      with doc.edit("rename"):
         delayed_hits.rename_hit(doc, "sight", "foresight")
      self.assertIn("delay_hit target 2 foresight;", source.text)
      with self.assertRaisesRegex(DocumentError, "used by"):
         with doc.edit("remove"):
            delayed_hits.remove_hit(doc, "foresight")
      path = str(self.dir / "battle.json")
      status, out = run_cli("battle", path, "delayed-hit", "list")
      self.assertEqual(status, 0, out)
      self.assertIn("no delayed hits", out)   # the CLI reads the files on disk, which the edits above did not save
      self.assertEqual(run_cli("battle", path, "delayed-hit", "add", "late")[0], 0)
      self.assertEqual(run_cli("battle", path, "delayed-hit", "accuracy", "late", "50")[0], 0)
      status, out = run_cli("battle", path, "delayed-hit", "list")
      self.assertIn("late", out)
      self.assertNotEqual(run_cli("battle", path, "delayed-hit", "accuracy", "late", "101")[0], 0)


class ConditionsAndLogicTests(BattleTestCase):
   """!bound_to, the kwid kind, the name lists and the palette."""

   def test_bound_to(self) -> None:
      """!A volatile's bound_to: the engine's choices, refused otherwise, counted in the budget.
      @return None
      """
      doc = self.project.structure
      self.assertEqual(conditions.bound_choices(), list(engine.tool("battle_compiler").BOUND_TO))
      self.assertEqual(conditions.FIELDS["volatile"]["bound_to"], conditions.BOUND)
      names = conditions.names(doc, "volatile")
      if not names:
         with doc.edit("add"):
            conditions.add_record(doc, "volatile", "hold")
         names = conditions.names(doc, "volatile")
      with doc.edit("bound"):
         conditions.set_field(doc, "volatile", names[0], "bound_to", conditions.bound_choices()[0])
      row = next(r for r in conditions.budget(doc) if r.label == "bound volatiles")
      self.assertEqual(row.used, 1)
      with self.assertRaises(DocumentError):
         with doc.edit("bad"):
            conditions.set_field(doc, "volatile", names[0], "bound_to", "nobody")
      self.assertIsNone(self.project.error_now())

   def test_kwid_and_lists(self) -> None:
      """!`use_move ... unless FLAG`: an optional move flag field; delayed hits and AI profiles in the name lists;
      the palette's delay hit (needs a record), use move unless and absorb.
      @return None
      """
      fields = dict(logic.statement_fields({"stmt": "use_move"}))
      self.assertEqual(fields["unless"], f"{logic.KWID_KIND}:move_flags")
      node = {"owner": {"kind": "move", "name": "x"},
              "handlers": [{"phase": "use", "body": [{"stmt": "use_move", "who": "user", "move": 1, "unless": "a"}]}]}
      logic.set_field(node, ("handlers", 0, "body", 0), "unless", fields["unless"], "")
      self.assertNotIn("unless", node["handlers"][0]["body"][0])
      lists = logic.name_lists(self.project)
      self.assertIn("delayed_hits", lists)
      self.assertIn(ai.NAMES_LIST, lists)
      palette = {label: text for _group, label, text in logic.statement_templates(self.project)}
      self.assertEqual(palette["absorb"], "absorb;")
      self.assertIn("unless", palette["use move unless"] or "unless")
      self.assertIsNone(palette["delay hit"])   # the Starter has no delayed hits


if __name__ == "__main__":
   unittest.main()
