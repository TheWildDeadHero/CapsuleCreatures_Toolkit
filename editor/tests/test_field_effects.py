#!/usr/bin/env python3
"""!Tests for the timed field effects and the encounter rules in the studio (D-27 sections 1 and 2, engine F1):
core.structure.field_effects (the structure's field_effects, the items starting one), core.structure.encounter_rules
(the lead rule, the encounter pipelines, the logic running the encounter hooks, global rules), the effect logic's
name lists and palette, and the `battle FILE field-effect|encounter ...` and `script save-shapes --check` commands.
No Qt.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase): its Ward effect (steps, refresh, an expiry
message, persists), the Ward Charm starting it for 120 steps, the global ward_rule and Quick Feet's `on encounter`
are read from the sample. The Gen-3 class runs on the reference repo's sample (skipped without it).
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, engine, logic  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import encounter_rules, field_effects  # noqa: E402
from sample_data import gen3_data, needs_gen3  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## The Starter's field effect.
WARD = "ward"
## The Starter's item starting it, and for how many steps.
WARD_ITEM, WARD_STEPS = "Ward Charm", "120"
## The engine's save fixture (a scripts manifest with a save history).
SAVE_FIXTURE = ("scripts.json", "save.cscript", "save_history.json")


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


class FieldEffectTests(BattleTestCase):
   """!The structure's field effects."""

   def test_rows_and_lists(self) -> None:
      """!The sample's effect with its implicit script names and users; the choice lists are the engine's.
      @return None
      """
      bc = engine.tool("battle_compiler")
      doc = self.project.structure
      self.assertEqual(field_effects.units(), list(bc.FIELD_EFFECT_UNITS))
      self.assertEqual(field_effects.stacks(), list(bc.FIELD_EFFECT_STACKS))
      self.assertEqual(field_effects.max_effects(), bc.MAX_FIELD_EFFECTS)
      (row,) = field_effects.effect_rows(doc)
      self.assertEqual((row["name"], row["unit"], row["stack"], row["persists"]), (WARD, "steps", "refresh", True))
      self.assertEqual(row["var"], bc.field_effect_var(WARD))
      self.assertEqual(row["end_script"], bc.field_effect_end_script(WARD))
      self.assertTrue(row["expiry"])
      self.assertEqual(len(row["users"]), 2)   # the global rule and the charm
      self.assertEqual(logic.name_lists(self.project)["field_effects"], [WARD])
      self.assertEqual(field_effects.item_field_effect(self.project, WARD_ITEM), (WARD, WARD_STEPS))

   def test_edit_rename_remove(self) -> None:
      """!Add, set every key (defaults drop the key), rename following the logic, a removal refused while named.
      @return None
      """
      doc = self.project.structure
      with doc.edit("add"):
         field_effects.add_effect(doc, "lure", "minutes")
      with doc.edit("keys"):
         field_effects.set_stack(doc, "lure", "add")
         field_effects.set_expiry(doc, "lure", "The lure is gone.")
         field_effects.set_persists(doc, "lure", False)
         field_effects.set_label(doc, "lure", "Lure")
      rec = field_effects.effects(doc)[-1]
      self.assertEqual(rec, {"name": "lure", "unit": "minutes", "stack": "add", "expiry": "The lure is gone.",
                             "persists": False, "label": "Lure"})
      with doc.edit("defaults"):
         field_effects.set_stack(doc, "lure", field_effects.default_stack())
         field_effects.set_expiry(doc, "lure", "")
         field_effects.set_persists(doc, "lure", True)
         field_effects.set_label(doc, "lure", "")
      self.assertEqual(field_effects.effects(doc)[-1], {"name": "lure", "unit": "minutes"})
      with self.assertRaises(DocumentError):
         with doc.edit("bad"):
            field_effects.set_unit(doc, "lure", "hours")
      with self.assertRaises(DocumentError):
         with doc.edit("bad name"):
            field_effects.add_effect(doc, "Not Lower")
      with doc.edit("rename"):
         places = field_effects.rename_effect(doc, WARD, "glow")
      self.assertEqual(len(places), 2)
      self.assertEqual(field_effects.item_field_effect(self.project, WARD_ITEM), ("glow", WARD_STEPS))
      with self.assertRaises(DocumentError):
         with doc.edit("remove"):
            field_effects.remove_effect(doc, "glow")
      with doc.edit("move"):
         field_effects.move_effect(doc, "lure", -1)
      self.assertEqual(field_effects.effect_names(doc), ["lure", "glow"])
      with doc.edit("remove lure"):
         field_effects.remove_effect(doc, "lure")
      self.assertIsNone(self.project.error_now())

   def test_item_starts_effect(self) -> None:
      """!An item's use_field logic gets the start (the use grows to field); a new amount replaces the old.
      @return None
      """
      p = self.project
      item = next(e["name"] for e in battle.entries(p.battle, "items")
                  if e.get("use", "none") == "none" and e["name"] != WARD_ITEM)
      with p.battle.edit("item"):
         field_effects.set_item_field_effect(p, item, WARD, 30)
      self.assertEqual(field_effects.item_field_effect(p, item), (WARD, "30"))
      self.assertIn(battle.entry(p.battle, "items", item)["use"], ("field", "both"))
      with p.battle.edit("again"):
         field_effects.set_item_field_effect(p, item, WARD, 45)
      self.assertEqual(field_effects.item_field_effect(p, item), (WARD, "45"))
      with self.assertRaises(DocumentError):
         with p.battle.edit("bad"):
            field_effects.set_item_field_effect(p, item, WARD, 0)
      self.assertIsNone(p.error_now())

   def test_palette(self) -> None:
      """!The Field palette group names the battle's effect; encounter primitives are in it.
      @return None
      """
      entries = {label: text for group, label, text in logic.statement_templates(self.project) if group == "Field"}
      self.assertEqual(entries["start field effect"], f"field_effect start {WARD} 100;")
      self.assertIn("encounter_rate", entries["encounter rate"])


class EncounterRuleTests(BattleTestCase):
   """!The lead rule, the encounter pipelines and the hooks' logic."""

   def test_lead_rule(self) -> None:
      """!No rule by default; one the engine compiles; one it refuses; clearing it.
      @return None
      """
      doc = self.project.structure
      self.assertIsNone(encounter_rules.lead_when(doc))
      self.assertEqual(encounter_rules.describe(doc), encounter_rules.DEFAULT_LEAD_TEXT)
      with doc.edit("lead"):
         encounter_rules.set_lead(doc, "level >= 5")
      self.assertEqual(doc.data["lead"], {"when": "level >= 5"})
      self.assertIsNone(self.project.error_now())
      with self.assertRaises(DocumentError):
         with doc.edit("bad"):
            encounter_rules.set_lead(doc, "no_such_value > 1")
      self.assertEqual(encounter_rules.lead_when(doc), "level >= 5")
      with doc.edit("clear"):
         encounter_rules.clear_lead(doc)
      self.assertNotIn("lead", doc.data)

   def test_handlers_and_globals(self) -> None:
      """!Global rules first, then the lead's passive; a new global rule; global owners on Logic > Effects.
      @return None
      """
      p = self.project
      uses = encounter_rules.encounter_handlers(p)
      self.assertEqual((uses[0].kind, uses[0].name), (logic.global_kind(), "ward_rule"))
      self.assertIn(("passive", "Quick Feet"), [(u.kind, u.name) for u in uses])
      self.assertEqual(set(encounter_rules.encounter_pipelines(p)), set(encounter_rules.PIPELINES))
      # F3: global rules also hold the step effects' steps hook (B1: and the combinations' combine hook); the
      # encounter rules keep to the encounter hooks
      self.assertEqual([h["name"] for h in logic.hook_catalog(logic.global_kind())],
                       encounter_rules.hooks() + ["steps", "combine", "hatch"])
      with p.battle.edit("global"):
         encounter_rules.add_global_rule(p, "lure_rule")
      self.assertIn("lure_rule", [u.name for u in encounter_rules.encounter_handlers(p)])
      self.assertEqual([d for d in logic.diagnostics(p) if d.severity == "error"], [])
      self.assertIsNone(p.error_now())


class FieldCliTests(BattleTestCase):
   """!`battle FILE field-effect ...`, `battle FILE encounter ...`."""

   def test_cli(self) -> None:
      """!List, add, set, item, a refused removal, lead set and clear.
      @return None
      """
      b = str(self.dir / "battle.json")
      code, out = run_cli("battle", b, "field-effect", "list")
      self.assertEqual(code, 0)
      self.assertIn(f"{WARD} (", out)
      self.assertEqual(run_cli("battle", b, "field-effect", "add", "lure", "--unit", "minutes")[0], 0)
      self.assertEqual(run_cli("battle", b, "field-effect", "set", "lure", "persists", "off")[0], 0)
      self.assertEqual(run_cli("battle", b, "field-effect", "item", WARD_ITEM, "lure", "15")[0], 0)
      code, out = run_cli("battle", b, "field-effect", "remove", "lure")
      self.assertNotEqual(code, 0)
      self.assertIn("used by", out)
      self.assertEqual(run_cli("battle", b, "encounter", "lead", "level >= 3")[0], 0)
      code, out = run_cli("battle", b, "encounter", "show")
      self.assertIn("level >= 3", out)
      self.assertIn("ward_rule", out)
      self.assertEqual(run_cli("battle", b, "encounter", "lead-clear")[0], 0)
      reopened = battle.BattleProject.open(self.dir / "battle.json")
      self.assertNotIn("lead", reopened.structure.data)
      self.assertFalse(field_effects.effects(reopened.structure)[-1]["persists"])


class SaveShapeCheckTests(unittest.TestCase):
   """!`script save-shapes MANIFEST --check` on a copy of the engine's save fixture."""

   def test_check(self) -> None:
      """!Exit 1 while the history lacks a shape, 0 once --record added them.
      @return None
      """
      src = Path(engine.root()) / "tests/data/save"
      with tempfile.TemporaryDirectory() as tmp:
         folder = Path(tmp)
         for name in SAVE_FIXTURE:
            shutil.copy(src / name, folder / name)
         # keep the history file, without its shapes
         history = json.loads((folder / "save_history.json").read_text(encoding="utf-8"))
         history["shapes"] = []
         (folder / "save_history.json").write_text(json.dumps(history), encoding="utf-8")
         manifest = str(folder / "scripts.json")
         code, out = run_cli("script", "save-shapes", manifest, "--check")
         self.assertEqual(code, 1)
         self.assertIn("not recorded", out)
         self.assertEqual(run_cli("script", "save-shapes", manifest, "--record")[0], 0)
         code, out = run_cli("script", "save-shapes", manifest, "--check")
         self.assertEqual(code, 0)
         self.assertIn("every shape is recorded", out)


@needs_gen3
class Gen3FieldTests(BattleTestCase):
   """!The reference repo's Gen-3 sample: the repel effect, its sprays and the lead abilities."""

   def sample(self) -> Path:
      """!The Gen-3 sample.
      @return its folder
      """
      folder = gen3_data()
      assert folder is not None
      return folder

   def test_repel(self) -> None:
      """!The repel effect refuses while it runs; the three sprays start it; the global rule runs first.
      @return None
      """
      p = self.project
      (row,) = field_effects.effect_rows(p.structure)
      self.assertEqual((row["name"], row["stack"]), ("repel", "refuse"))
      started = {field_effects.item_field_effect(p, n) for n in ("Shoo Spray", "Super Shoo", "Max Shoo")}
      self.assertEqual(started, {("repel", "100"), ("repel", "200"), ("repel", "250")})
      uses = encounter_rules.encounter_handlers(p)
      self.assertEqual(uses[0].kind, logic.global_kind())
      self.assertGreaterEqual(len(uses), 10)


if __name__ == "__main__":
   unittest.main()
