#!/usr/bin/env python3
"""!Tests for the field actions and the map side of F2 in the studio (D-27 section 3, engine F2):
core.structure.field_actions (the structure's field_actions, their choice lists from the game's world and scripts,
the requirement checks, the preview), core.map_field (object kinds, map tags, flight points, map darkness / tags /
escape points), the object kind and the movement mode's dismount, the F1 leftovers (a field effect's rename follows
the .cscript sources, the encounter lead preview) and the `battle FILE field-action ...` and `map-field ...`
commands. No Qt.

Uses the map sandbox as one game (sample_data.make_field_game: sandbox_map's data with the Starter inside the game):
the Starter's wade / clear / light actions, the world's bush kind, dark tag and three flight points, and the scripts
field_wade / field_clear / field_light and the cave's `field_action available light`.
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import document, engine, field_rules, map_field, objects  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import encounter_rules, field_actions, field_effects  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402
from sample_data import DATA, make_field_game  # noqa: E402

## The Starter's field actions, in order.
ACTIONS = ["wade", "clear", "light"]
## The sandbox's scripts source (relative to the game's data folder).
SANDBOX_SCRIPTS = ("scripts", "sandbox.cscript")
## The cave script's query of the light action.
LIGHT_QUERY = "field_action available light"
## The Starter's field effect, and a script naming it (added to the sandbox's scripts for the rename test).
WARD = "ward"
WARD_SCRIPT = "\nscript ward_test { field_effect start ward 5; }\n"
## The Starter party with a member knowing a water move (Tidepup), the field actions' preview party.
WATER_PARTY = "Duo Ash & Bly"
## The world's object kind, map tag and the dark map.
BUSH, DARK, CAVE = "bush", "dark", "cave"


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


class FieldGameCase(unittest.TestCase):
   """!Base: a copy of the map sandbox as one game per test.

   @var dir
   The game folder.
   @var battle_json
   Its battle.json (the Starter).
   @var project
   The opened BattleProject.
   """

   def setUp(self) -> None:
      """!Copies the game and opens its battle data.
      @return None
      """
      self.dir = Path(tempfile.mkdtemp(prefix="capsule_f2_"))
      self.battle_json = make_field_game(self.dir)
      self.project = BattleProject.open(self.battle_json)

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.dir, ignore_errors=True)

   def scripts_text(self) -> str:
      """!The sandbox's scripts source.
      @return text
      """
      return self.dir.joinpath(DATA, *SANDBOX_SCRIPTS).read_text(encoding="utf-8")

   def world(self) -> Project:
      """!The game's world.
      @return Project
      """
      return Project.open(self.dir / DATA / "world.json")


class FieldActionTests(FieldGameCase):
   """!The structure's field actions."""

   def test_rows_and_choices(self) -> None:
      """!The Starter's actions; the choice lists are the engine's and the game's world / scripts.
      @return None
      """
      bc = engine.tool("battle_compiler")
      doc = self.project.structure
      self.assertEqual(field_actions.target_kinds(), list(bc.FIELD_ACTION_TARGETS))
      self.assertEqual(field_actions.max_actions(), bc.MAX_FIELD_ACTIONS)
      self.assertEqual(field_actions.member_var(), bc.FIELD_ACTION_MEMBER_VAR)
      self.assertEqual(field_actions.action_names(doc), ACTIONS)
      self.assertIn("water", field_actions.target_choices(doc, "behavior"))
      self.assertEqual(field_actions.target_choices(doc, "object"), [BUSH])
      self.assertEqual(field_actions.target_choices(doc, "tag"), [DARK])
      self.assertEqual(field_actions.target_choices(doc, field_actions.MENU_TARGET), [])
      names = field_actions.script_names(doc)
      self.assertIn("field_wade", names["script"])
      # the implicit asking wrappers and member variable are no choices
      self.assertNotIn(bc.field_action_ask_script("wade"), names["script"])
      self.assertNotIn(field_actions.member_var(), names["var"])
      words = field_actions.requirement_words(doc)
      self.assertIn(bc.field_action_move_word("Tide Slam"), words)
      self.assertIn(bc.FIELD_ACTION_PASSIVE, words)
      self.assertIn("var.helper", words)
      rows = {r["name"]: r for r in field_actions.action_rows(doc)}
      self.assertEqual(set(rows), set(ACTIONS))
      self.assertTrue(field_actions.lines(doc))

   def test_requirement_checks(self) -> None:
      """!The engine's verdict on requirements: names it does not know and bad syntax are refused, game state and
      moves are words.
      @return None
      """
      doc = self.project.structure
      self.assertIsNone(field_actions.check_requirement(doc, "wade", "knows.tide_slam && var.helper > 0"))
      self.assertIsNone(field_actions.check_requirement(doc, "wade", ""))
      self.assertIsNotNone(field_actions.check_requirement(doc, "wade", "knows.no_such_move"))
      self.assertIsNotNone(field_actions.check_requirement(doc, "wade", "flag.no_such_flag"))
      self.assertIsNotNone(field_actions.check_requirement(doc, "wade", "knows.tide_slam &&"))
      with self.assertRaises(DocumentError):
         with doc.edit("bad"):
            field_actions.set_requires(doc, "wade", "knows.no_such_move")
      self.assertIsNone(self.project.error_now())

   def test_edit(self) -> None:
      """!Add, every key, the target, move and remove; defaults drop their keys.
      @return None
      """
      doc = self.project.structure
      with doc.edit("add"):
         field_actions.add_action(doc, "rest", "field_wade")
      self.assertEqual(field_actions.actions(doc)[-1], {"name": "rest", "script": "field_wade"})
      with doc.edit("keys"):
         field_actions.set_label(doc, "rest", "Rest")
         field_actions.set_requires(doc, "rest", "knows.tide_slam")
         field_actions.set_ask(doc, "rest", False)
         field_actions.set_prompt(doc, "rest", "Rest a while?")
         field_actions.set_target(doc, "rest", "object", BUSH)
      rec = field_actions.actions(doc)[-1]
      self.assertEqual((rec["label"], rec["requires"], rec["ask"], rec["prompt"], rec["target"]),
                       ("Rest", "knows.tide_slam", False, "Rest a while?", {"object": BUSH}))
      with doc.edit("defaults"):
         field_actions.set_label(doc, "rest", "")
         field_actions.set_requires(doc, "rest", "")
         field_actions.set_ask(doc, "rest", field_actions.DEFAULT_ASK)
         field_actions.set_prompt(doc, "rest", "")
         field_actions.set_target(doc, "rest", field_actions.MENU_TARGET)
      self.assertEqual(field_actions.actions(doc)[-1], {"name": "rest", "script": "field_wade"})
      for bad in (lambda: field_actions.add_action(doc, "Not Lower", "field_wade"),
                  lambda: field_actions.add_action(doc, "wade", "field_wade"),
                  lambda: field_actions.set_target(doc, "rest", "planet", "x"),
                  lambda: field_actions.set_prompt(doc, "rest", "x" * (field_actions.max_prompt() + 1))):
         with self.assertRaises(DocumentError):
            with doc.edit("bad"):
               bad()
      with doc.edit("move"):
         field_actions.move_action(doc, "rest", -1)
      self.assertEqual(field_actions.action_names(doc), ["wade", "clear", "rest", "light"])
      with doc.edit("remove"):
         field_actions.remove_action(doc, "rest")
      self.assertEqual(field_actions.action_names(doc), ACTIONS)
      self.assertIsNone(self.project.error_now())

   def test_rename_follows_scripts(self) -> None:
      """!A rename rewrites the scripts' `field_action available`, saved at once; undo puts it back.
      @return None
      """
      doc = self.project.structure
      self.assertIn(LIGHT_QUERY, self.scripts_text())
      with document.group("rename"):
         with doc.edit("rename"):
            places = field_actions.rename_action(doc, "light", "glow")
      self.assertEqual(len(places), 1)
      self.assertIn("field_action available glow", self.scripts_text())
      self.assertNotIn(LIGHT_QUERY, self.scripts_text())
      self.assertTrue(doc.undo())
      self.assertIn(LIGHT_QUERY, self.scripts_text())
      self.assertEqual(field_actions.action_names(doc), ACTIONS)
      self.assertTrue(doc.redo())
      self.assertIn("field_action available glow", self.scripts_text())

   def test_preview(self) -> None:
      """!The preview names a member knowing a move the requirement names, or nobody; a game flag counts.
      @return None
      """
      p = self.project
      party = field_actions.party_records(p, WATER_PARTY)
      got = field_actions.preview(p, party)
      self.assertEqual(list(got), ACTIONS)
      slot = got["wade"]
      self.assertIsNotNone(slot)
      self.assertTrue({"Tide Slam", "Torrent"} & set(party[slot]["moves"]))
      with p.structure.edit("gate"):
         field_actions.set_requires(p.structure, "wade", "var.helper > 0")
      self.assertIsNone(field_actions.preview(p, party)["wade"])
      self.assertEqual(field_actions.preview(p, party, {"var.helper": 1})["wade"], 0)
      with self.assertRaises(DocumentError):
         field_actions.party_records(p, "nobody")

   def test_cli(self) -> None:
      """!`battle FILE field-action ...`.
      @return None
      """
      f = str(self.battle_json)
      code, out = run_cli("battle", f, "field-action", "list")
      self.assertEqual(code, 0)
      for name in ACTIONS:
         self.assertIn(name, out)
      code, out = run_cli("battle", f, "field-action", "choices")
      self.assertEqual(code, 0)
      self.assertIn(f"object: {BUSH}", out)
      self.assertEqual(run_cli("battle", f, "field-action", "check", "wade", "knows.tide_slam")[0], 0)
      self.assertEqual(run_cli("battle", f, "field-action", "check", "wade", "knows.nothing")[0], 1)
      code, out = run_cli("battle", f, "field-action", "preview", WATER_PARTY)
      self.assertEqual(code, 0)
      self.assertIn("wade: member", out)
      self.assertEqual(run_cli("battle", f, "field-action", "add", "rest", "field_wade", "--target", "tag",
                               "--name", DARK)[0], 0)
      self.assertEqual(run_cli("battle", f, "field-action", "set", "rest", "ask", "off")[0], 0)
      self.assertEqual(run_cli("battle", f, "field-action", "move", "rest", "up")[0], 0)
      code, out = run_cli("battle", f, "field-action", "rename", "light", "glow")
      self.assertEqual(code, 0)
      self.assertIn("scripts:", out)
      reopened = BattleProject.open(self.battle_json).structure
      self.assertEqual(field_actions.action_names(reopened), ["wade", "clear", "rest", "glow"])
      self.assertEqual(field_actions.actions(reopened)[2]["ask"], False)
      self.assertEqual(run_cli("battle", f, "field-action", "remove", "rest")[0], 0)


class FieldLeftoverTests(FieldGameCase):
   """!The F1 leftovers: a field effect's rename follows the scripts; the encounter lead preview."""

   def test_effect_rename_follows_scripts(self) -> None:
      """!`field_effect start ward` in a script follows a rename of the effect.
      @return None
      """
      path = self.dir.joinpath(DATA, *SANDBOX_SCRIPTS)
      path.write_text(path.read_text(encoding="utf-8") + WARD_SCRIPT, encoding="utf-8")
      doc = self.project.structure
      with doc.edit("rename"):
         places = field_effects.rename_effect(doc, WARD, "glow")
      self.assertTrue(any(p.startswith("scripts:") for p in places))
      self.assertIn("field_effect start glow 5", self.scripts_text())

   def test_lead_preview(self) -> None:
      """!Each of the battle's parties has a lead (the Starter's rule skips nobody at full hit points).
      @return None
      """
      p = self.project
      names = encounter_rules.party_names(p)
      self.assertIn(WATER_PARTY, names)
      for name in names:
         self.assertIsNotNone(encounter_rules.lead_preview(p, name))
      with self.assertRaises(DocumentError):
         encounter_rules.lead_preview(p, "nobody")


class MapFieldTests(FieldGameCase):
   """!The world's object kinds, map tags and flight points; the maps' darkness, tags and escape points."""

   def test_lists_and_limits(self) -> None:
      """!The engine's limits and the sandbox's names.
      @return None
      """
      mc = engine.tool("map_compiler")
      w = self.world()
      self.assertEqual(map_field.max_darkness(), mc.MAX_DARKNESS)
      self.assertEqual(map_field.darkest(w.world), len(mc.darkness_levels(w.world.data)))   # C8: the world's
      self.assertEqual(map_field.max_flight_points(), mc.MAX_FLIGHT_POINTS)
      self.assertEqual(map_field.object_kinds(w.world), [BUSH])
      self.assertEqual(map_field.map_tags(w.world), [DARK])
      self.assertEqual([f["name"] for f in map_field.flight_points(w.world)], ["park", "meadow", "cave_mouth"])
      self.assertEqual(map_field.map_rules(w.map(CAVE), w.world)[:2], (3, [DARK]))
      self.assertTrue(map_field.lines(w))

   def test_rename_follows_maps(self) -> None:
      """!Renaming a kind or a tag rewrites the maps naming it; a removal is refused while named.
      @return None
      """
      w = self.world()
      self.assertTrue(map_field.kind_users(w, BUSH))
      with w.world.edit("rename kind"):
         followed = map_field.rename_name(w, map_field.KINDS_KEY, BUSH, "shrub")
      self.assertTrue(followed)
      self.assertFalse(map_field.kind_users(w, BUSH))
      self.assertTrue(map_field.kind_users(w, "shrub"))
      with w.world.edit("rename tag"):
         map_field.rename_name(w, map_field.TAGS_KEY, DARK, "gloom")
      self.assertEqual(map_field.map_rules(w.map(CAVE), w.world)[1], ["gloom"])
      with self.assertRaises(DocumentError):
         with w.world.edit("remove"):
            map_field.remove_name(w, map_field.TAGS_KEY, "gloom")
      with w.world.edit("add"):
         map_field.add_name(w, map_field.KINDS_KEY, "boulder")
      with w.world.edit("remove"):
         map_field.remove_name(w, map_field.KINDS_KEY, "boulder")
      self.assertIsNone(w.validate())

   def test_map_rules_and_flights(self) -> None:
      """!Darkness in range, tags from the world, the escape point; flight points added, changed and removed.
      @return None
      """
      w = self.world()
      cave = w.map(CAVE)
      with cave.edit("dark"):
         map_field.set_darkness(cave, w.world, map_field.darkest(w.world))
         map_field.set_escape_point(cave, w.world, True)
      self.assertEqual(map_field.map_rules(cave, w.world), (map_field.darkest(w.world), [DARK], True))
      for bad in (lambda: map_field.set_darkness(cave, w.world, map_field.darkest(w.world) + 1),
                  lambda: map_field.set_tags(cave, w.world, ["nowhere"])):
         with self.assertRaises(DocumentError):
            with cave.edit("bad"):
               bad()
      with cave.edit("off"):
         map_field.set_darkness(cave, w.world, 0)
         map_field.set_tags(cave, w.world, [])
         map_field.set_escape_point(cave, w.world, False)
      self.assertEqual(map_field.map_rules(cave, w.world), (0, [], False))
      for key in (map_field.DARKNESS_KEY, map_field.MAP_TAGS_KEY, map_field.ESCAPE_KEY):
         self.assertNotIn(key, cave.data)
      with w.world.edit("flight"):
         map_field.add_flight_point(w.world, "pond", CAVE, 2, 3, "Pond")
         map_field.set_flight_point(w.world, "pond", "x", 4)
      self.assertEqual(map_field.flight_points(w.world)[-1]["x"], 4)
      with self.assertRaises(DocumentError):
         with w.world.edit("bad"):
            map_field.add_flight_point(w.world, "pond", CAVE, 1, 1)
      with w.world.edit("remove"):
         map_field.remove_flight_point(w.world, "pond")
      self.assertIsNone(w.validate())

   def test_object_kind_and_dismount(self) -> None:
      """!An object's kind is one of the world's; a movement mode's dismount.
      @return None
      """
      w = self.world()
      name = next(n for n in w.map_names() if objects.objects(w.map(n)))
      doc = w.map(name)
      with doc.edit("kind"):
         objects.set_object(doc, 0, kind=BUSH)
      self.assertEqual(objects.objects(doc)[0]["kind"], BUSH)
      self.assertIsNone(w.validate())
      with self.assertRaises(DocumentError):
         with doc.edit("bad"):
            objects.set_object(doc, 0, kind="")
      # class 0 (on foot) has nothing to leave: the first vehicle's
      mode = field_rules.mode_rows(w.world)[1]["name"]
      with w.world.edit("dismount"):
         field_rules.set_mode(w.world, mode, "dismount", True)
      self.assertTrue(next(r for r in field_rules.mode_rows(w.world) if r["name"] == mode)["dismount"])
      foot = field_rules.mode_rows(w.world)[0]["name"]
      with self.assertRaises(DocumentError):
         with w.world.edit("foot"):
            field_rules.set_mode(w.world, foot, "dismount", True)

   def test_cli(self) -> None:
      """!`map-field WORLD ...`.
      @return None
      """
      f = str(self.dir / DATA / "world.json")
      code, out = run_cli("map-field", f, "list")
      self.assertEqual(code, 0)
      self.assertIn(BUSH, out)
      self.assertEqual(run_cli("map-field", f, "map", CAVE, "darkness", "1")[0], 0)
      self.assertNotEqual(run_cli("map-field", f, "map", CAVE, "darkness", "9")[0], 0)
      self.assertEqual(run_cli("map-field", f, "flight", "add", "pond", CAVE, "2", "3", "--label", "Pond")[0], 0)
      self.assertEqual(run_cli("map-field", f, "flight", "set", "pond", "y", "4")[0], 0)
      self.assertEqual(run_cli("map-field", f, "tag", "add", "wet")[0], 0)
      self.assertEqual(run_cli("map-field", f, "map", CAVE, "tags", f"{DARK},wet")[0], 0)
      w = self.world()
      self.assertEqual(map_field.map_rules(w.map(CAVE), w.world)[:2], (1, [DARK, "wet"]))
      self.assertEqual(map_field.flight_points(w.world)[-1]["y"], 4)
      self.assertEqual(run_cli("map-field", f, "flight", "remove", "pond")[0], 0)


if __name__ == "__main__":
   unittest.main()
