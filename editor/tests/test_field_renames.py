#!/usr/bin/env python3
"""!C8 (the D-27 review's findings) in the studio: renames and removals elsewhere follow into the field rules of the
battle data and back, and the two new pieces of data the field rules gained. No Qt.

- a move / passive / item rename rewrites `knows.MOVE` / `passive.NAME` / `item.NAME` in the field actions'
  requirements and the lead rules (core.battle.rename_entry(); a removal is refused while they read it);
- a custom role, species field or stat rename follows into them (core.structure.record / species_fields / stats;
  a removal is refused while they read it);
- a script, flag or variable renamed in the game's scripts follows into the field actions' and step effects'
  `script` and `flag.NAME` / `var.NAME` (core.scripts.ScriptProject.rename(): the battle data saved at once);
- a battle message the step effects show is a use (core.messages: the rename follows, the removal is refused);
- the CLI's field-action / field-effect / step-effect renames follow the scripts only once the battle data saved;
- an object kind or map tag renamed in the world follows into the field actions' targets when the world file is
  saved (core.map_field.follow_saved_renames(); the removal is refused while one targets it; the CLI prints them);
- the world's darkness levels (core.map_field: list, add, set, remove the darkest, a map no darker than the
  darkest; CLI `map-field WORLD darkness`) and the lead section's hooks' member (core.structure.encounter_rules:
  set / clear / describe / preview; CLI `encounter hook-lead`).

Uses the map sandbox as one game (sample_data.make_field_game, as tests/test_field_actions.py).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle, engine, map_field, messages, scripts  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import (encounter_rules, field_actions, record, species_fields,  # noqa: E402
                                           stats, step_effects)
from sample_data import DATA  # noqa: E402
from test_field_actions import FieldGameCase, run_cli  # noqa: E402

## The Starter's water move and the wade action reading it.
TIDE_SLAM, WADE = "Tide Slam", "wade"
## The Starter's custom role read by the step effect bond (and here by the field rules).
BOND = "bond"
## The sandbox's scripts manifest (relative to the game's data folder).
SCRIPTS_JSON = ("scripts", "scripts.json")
## A sandbox flag and script the tests make the field rules read.
FLAG, SCRIPT = "beat_rival", "field_wade"
## The Starter's step effect with a message, and that message.
BLIGHT, BLIGHT_MESSAGE = "blight", "blight_survived"


class FieldRenameTests(FieldGameCase):
   """!Renames and removals elsewhere and the field rules."""

   def structure(self) -> dict:
      """!The structure manifest as saved.
      @return parsed JSON
      """
      return json.loads(self.project.structure.path.read_text(encoding="utf-8"))

   def requires(self, name: str) -> str:
      """!A field action's requirement (live).
      @param name  the action
      @return its text
      """
      return next(a for a in field_actions.actions(self.project.battle) if a["name"] == name)["requires"]

   def test_move_passive_item(self) -> None:
      """Finding 2: a move rename rewrites knows.MOVE; a passive and an item rename rewrite passive.NAME / item.NAME;
      removing a move a requirement reads is refused."""
      p = self.project
      passive = battle.entries(p.battle, "passives")[0]["name"]
      item = battle.entries(p.battle, "items")[0]["name"]
      bc = field_actions._bc()
      with p.battle.edit("req"):
         field_actions.set_requires(p.battle, WADE, f"{bc.field_action_move_word(TIDE_SLAM)} && "
                                    f"passive != {bc.field_action_passive_word(passive)}")
         encounter_rules.set_lead(p.battle, f"held_item != item.{item.lower().replace(' ', '_')}")
      with p.battle.edit("rename"):
         n = battle.rename_entry(p.battle, "moves", TIDE_SLAM, "Surge Slam")
      self.assertGreater(n, 0)
      self.assertIn("knows.surge_slam", self.requires(WADE))
      with p.battle.edit("rename"):
         battle.rename_entry(p.battle, "passives", passive, "Renamed Passive")
         battle.rename_entry(p.battle, "items", item, "Renamed Item")
      self.assertIn("passive.renamed_passive", self.requires(WADE))
      self.assertEqual(encounter_rules.lead_when(p.battle), "held_item != item.renamed_item")
      self.assertIsNone(p.error_now())
      with self.assertRaises(DocumentError) as ctx:
         with p.battle.edit("remove"):
            battle.remove_entry(p.battle, "moves", "Surge Slam")
      self.assertIn("field_actions", str(ctx.exception))

   def test_role_field_stat(self) -> None:
      """Finding 3: a custom role, species field and stat rename follow into the lead rules and the requirements;
      removals are refused while they read them."""
      p = self.project
      field = species_fields.field_names(p.battle)[0]
      # a stat no flag pins (pool / order: their removal is refused for that first)
      stat = next(s["name"] for s in stats.stats(p.battle) if not any(s.get(f) for f in stats.ONE_OF_FLAGS))
      with p.battle.edit("rules"):
         encounter_rules.set_lead(p.battle, f"{BOND} >= 0 && level >= 1")
         encounter_rules.set_hook_lead(p.battle, f"species.{field} >= 0")
         field_actions.set_requires(p.battle, WADE, f"knows.tide_slam && {BOND} >= 0 && stat.{stat} >= 0")
      with p.battle.edit("rename role"):
         self.assertTrue(record.rename_role(p.battle, BOND, "kinship"))
      self.assertEqual(encounter_rules.lead_when(p.battle), "kinship >= 0 && level >= 1")
      self.assertIn("kinship >= 0", self.requires(WADE))
      with p.battle.edit("rename field"):
         species_fields.rename_field(p.battle, field, "renamed_field")
      self.assertEqual(encounter_rules.hook_lead_when(p.battle), "species.renamed_field >= 0")
      with p.battle.edit("rename stat"):
         stats.rename_stat(p.battle, stat, "renamed_stat")
      self.assertIn("stat.renamed_stat >= 0", self.requires(WADE))
      self.assertIsNone(p.error_now())
      for remove, what in ((lambda: record.remove_role(p.battle, "kinship"), "lead.when"),
                           (lambda: species_fields.remove_field(p.battle, "renamed_field"), "lead.hook_when"),
                           (lambda: stats.remove_stat(p.battle, "renamed_stat"), "field_actions")):
         with self.subTest(what=what):
            with self.assertRaises(DocumentError) as ctx:
               with p.battle.edit("remove"):
                  remove()
            self.assertIn(what, str(ctx.exception))

   def test_script_flag_var(self) -> None:
      """Finding 4: a script, flag or variable renamed in the game's scripts follows into the battle data (saved),
      and the scripts and battle data compile together."""
      p = self.project
      with p.battle.edit("req"):
         field_actions.set_requires(p.battle, WADE, f"knows.tide_slam && flag.{FLAG} == 0 && var.cells >= 0")
         step_effects.set_script(p.battle, BLIGHT, SCRIPT)
      p.save_all()
      sp = scripts.ScriptProject.open(self.dir.joinpath(DATA, *SCRIPTS_JSON))
      self.assertGreater(sp.rename(SCRIPT, "field_wade2"), 0)
      self.assertEqual(len(sp.followed), 2)   # the action's script and the step effect's
      self.assertGreater(sp.rename(FLAG, "rival_beaten"), 0)
      self.assertGreater(sp.rename("cells", "squares"), 0)
      sp.save()
      reopened = BattleProject.open(self.battle_json)
      wade = next(a for a in field_actions.actions(reopened.battle) if a["name"] == WADE)
      self.assertEqual(wade["script"], "field_wade2")
      self.assertIn("flag.rival_beaten == 0", wade["requires"])
      self.assertIn("var.squares >= 0", wade["requires"])
      blight = next(e for e in step_effects.effects(reopened.battle) if e["name"] == BLIGHT)
      self.assertEqual(blight["script"], "field_wade2")
      # the engine's script compiler on the saved game (it reads the world and the battle data the build reads)
      comp = engine.tool("script_compiler").compile_file(self.dir.joinpath(DATA, *SCRIPTS_JSON))
      self.assertEqual([str(d) for d in comp.errors()], [])
      self.assertIsNone(reopened.error_now())

   def test_step_effect_message(self) -> None:
      """Finding 5: a step effect's message is a use: the rename follows, the removal is refused."""
      p = self.project
      self.assertEqual(messages.uses(p.battle, BLIGHT_MESSAGE), [f"step_effects {BLIGHT}: messages.survived"])
      with p.battle.edit("rename"):
         messages.rename(p.battle, BLIGHT_MESSAGE, "blight_kept")
      blight = next(e for e in step_effects.effects(p.battle) if e["name"] == BLIGHT)
      self.assertEqual(blight["messages"], {"survived": "blight_kept"})
      self.assertIsNone(p.error_now())
      with self.assertRaises(DocumentError):
         with p.battle.edit("remove"):
            messages.remove(p.battle, "blight_kept")

   def test_cli_follows_after_save(self) -> None:
      """Finding 11: a CLI rename whose battle data is not saved (it does not compile) leaves the scripts alone; a
      saved one follows them."""
      bj = str(self.battle_json)
      text = self.scripts_text()
      data = self.structure()
      broken = json.loads(json.dumps(data))
      broken["field_actions"][0]["requires"] = "nope_not_an_input"
      self.project.structure.path.write_text(json.dumps(broken, indent=1), encoding="utf-8")
      code, out = run_cli("battle", bj, "field-action", "rename", "light", "glow")
      self.assertEqual(code, 1, out)
      self.assertEqual(self.scripts_text(), text)   # the cave's `field_action available light` stays
      self.project.structure.path.write_text(json.dumps(data, indent=1), encoding="utf-8")
      code, out = run_cli("battle", bj, "field-action", "rename", "light", "glow")
      self.assertEqual(code, 0, out)
      self.assertIn("field_action available glow", self.scripts_text())

   def test_world_rename(self) -> None:
      """Finding 13 (F2's open item): an object kind / map tag rename in the world follows into the field actions'
      targets when the world is saved (the world and battle data on disk agree before and after); removing one a
      field action targets is refused; the CLI prints what followed."""
      def clear_target() -> dict:
         """!The clear action's target as saved.
         @return it
         """
         return next(a for a in field_actions.actions(BattleProject.open(self.battle_json).battle)
                     if a["name"] == "clear")["target"]

      w = self.world()
      with w.world.edit("rename kind"):
         map_field.rename_name(w, map_field.KINDS_KEY, "bush", "shrub")
      self.assertEqual(clear_target(), {"object": "bush"})   # the world on disk still names bush
      self.assertIsNone(w.validate())
      w.save_all()
      self.assertEqual(w.followed_battle, ["field action clear: bush -> shrub"])
      self.assertEqual(clear_target(), {"object": "shrub"})
      self.assertIsNone(w.validate())
      with w.world.edit("add"):
         map_field.add_name(w, map_field.TAGS_KEY, "lit")
      w.save_all()
      p = BattleProject.open(self.battle_json)
      with p.battle.edit("target"):
         field_actions.set_target(p.battle, "light", "tag", "lit")
      p.save_all()
      w = self.world()
      with self.assertRaises(DocumentError) as ctx:
         with w.world.edit("remove"):
            map_field.remove_name(w, map_field.TAGS_KEY, "lit")
      self.assertIn("field action light", str(ctx.exception))
      code, out = run_cli("map-field", str(self.dir / DATA / "world.json"), "tag", "rename", "lit", "bright")
      self.assertEqual(code, 0, out)
      self.assertIn("battle: field action light", out)
      light = next(a for a in field_actions.actions(BattleProject.open(self.battle_json).battle)
                   if a["name"] == "light")
      self.assertEqual(light["target"], {"tag": "bright"})


class FieldDataTests(FieldGameCase):
   """!The world's darkness levels and the hooks' member (C8 findings 9 and 10)."""

   def test_darkness_levels(self) -> None:
      """The sandbox states the engine's default levels; add / set / remove the darkest; a map no darker than the
      darkest; the CLI lists them."""
      w = self.world()
      levels = map_field.darkness_levels(w.world)
      self.assertEqual([lv["lit"] for lv in levels], [72, 56, 40, 24])
      self.assertFalse(map_field.levels_default(w.world))
      with w.world.edit("add"):
         self.assertEqual(map_field.add_darkness_level(w.world, 16, 16), 5)
      with w.world.edit("set"):
         map_field.set_darkness_level(w.world, 5, "lit", 8)
      self.assertEqual(map_field.darkness_levels(w.world)[-1], {"lit": 8, "brightness": 16})
      with self.assertRaises(DocumentError):
         with w.world.edit("set"):
            map_field.set_darkness_level(w.world, 5, "brightness", map_field.max_brightness() + 1)
      cave = w.map("cave")
      with cave.edit("dark"):
         map_field.set_darkness(cave, w.world, 5)
      with self.assertRaises(DocumentError) as ctx:
         with w.world.edit("remove"):
            map_field.remove_darkness_level(w)
      self.assertIn("cave", str(ctx.exception))
      with cave.edit("dark"):
         map_field.set_darkness(cave, w.world, 3)
      with w.world.edit("remove"):
         map_field.remove_darkness_level(w)
      self.assertEqual(map_field.darkest(w.world), 4)
      with self.assertRaises(DocumentError):
         with cave.edit("dark"):
            map_field.set_darkness(cave, w.world, 5)
      w.save_all()
      code, out = run_cli("map-field", str(self.dir / DATA / "world.json"), "darkness", "list")
      self.assertEqual(code, 0, out)
      self.assertIn("4: lit 24 brightness 16", out)
      code, out = run_cli("map-field", str(self.dir / DATA / "world.json"), "darkness", "add", "12", "16")
      self.assertEqual(code, 0, out)
      self.assertEqual(map_field.darkest(self.world().world), 5)

   def test_hook_lead(self) -> None:
      """The hooks' member: set, described, previewed (a party member whose rule differs), cleared with the lead rule
      kept; the CLI."""
      p = self.project
      with p.battle.edit("hooks"):
         encounter_rules.set_lead(p.battle, "level >= 1")
         encounter_rules.set_hook_lead(p.battle, "1")
      self.assertEqual(encounter_rules.hook_lead_when(p.battle), "1")
      self.assertIn("`1`", encounter_rules.describe_hooks(p.battle))
      party = encounter_rules.party_names(p)[0]
      self.assertEqual(encounter_rules.lead_preview(p, party, hooks=True), 0)
      with p.battle.edit("clear"):
         encounter_rules.clear_hook_lead(p.battle)
      self.assertIsNone(encounter_rules.hook_lead_when(p.battle))
      self.assertEqual(encounter_rules.lead_when(p.battle), "level >= 1")
      with self.assertRaises(DocumentError):
         with p.battle.edit("bad"):
            encounter_rules.set_hook_lead(p.battle, "no_such_input")
      p.save_all()
      code, out = run_cli("battle", str(self.battle_json), "encounter", "hook-lead", "1")
      self.assertEqual(code, 0, out)
      code, out = run_cli("battle", str(self.battle_json), "encounter", "show")
      self.assertIn("hooks' member: the first party member for which `1` holds", out)


if __name__ == "__main__":
   unittest.main()
