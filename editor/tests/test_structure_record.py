#!/usr/bin/env python3
"""!Tests for capsule_studio.core.structure.record (D-23 §3.2 "Record": the
manifest's monster_layout, list and v2 object forms, engine and custom roles,
the budget per target and the layout hash via the engine's compile_layout)
and the `battle FILE role ...` / `battle FILE layout` commands. No Qt.

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
from capsule_studio.core import battle, engine  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import progression, record, stats  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402
from test_structure_stats import STARTER_STATS, write_project  # noqa: E402



def roles_of(doc: object) -> list:
   """!The layout's role list (the object form's "roles", or an older list form itself).
   @param doc  battle Document
   @return the live list
   """
   given = battle.structure_doc(doc).data["monster_layout"]
   return given["roles"] if isinstance(given, dict) else given

class RecordModelTests(BattleTestCase):
   """!Reading the record and the engine's layout."""

   def test_rows_and_engine_layout(self) -> None:
      """!Engine roles keep their registry IDs, custom roles count from 0x80; per-stat roles hold one element
      per stat, move roles one per slot; size and hash are the battle compiler's.
      @return None
      """
      doc = self.project.battle
      rows = record.role_rows(doc)
      by = {r["name"]: r for r in rows}
      lay = engine.tool("battlec.layout")
      self.assertEqual(by["species_key"]["id"], 0)
      self.assertEqual(by["nickname"]["id"], lay.ROLE_NAMES.index("nickname"))
      # the Starter's MP and EP persist in custom roles (D-25); its form is one too (G4), its bond (F3) and its egg
      # role and hatch counter (B2)
      self.assertEqual([r["id"] for r in rows if r["kind"] == record.KIND_CUSTOM],
                       [0x80, 0x81, 0x82, 0x83, 0x84, 0x85])
      self.assertEqual(by["current_mp"]["kind"], record.KIND_CUSTOM)
      self.assertEqual((by["stat_genes"]["count"], by["stat_genes"]["count_rule"]), (len(STARTER_STATS), "stat"))
      self.assertEqual((by["moves"]["count"], by["moves"]["bits"]), (8, 128))
      self.assertTrue(by["stat_genes"]["width_editable"])
      self.assertFalse(by["species_key"]["width_editable"])
      self.assertTrue(by["nickname"]["count_editable"])
      self.assertTrue(by["level"]["required"])
      self.assertEqual(by["stat_genes"]["transfer"], STARTER_STATS)
      self.assertEqual(by["level"]["transfer"], [record.TRANSFER_BY_ID])
      self.assertEqual(by["current_mp"]["transfer"], ["role:current_mp"])   # the record transfer's (E2c) key
      self.assertEqual(by["current_mp"]["transfer_values"], [lay.role_key("current_mp")])
      self.assertEqual(by["stat_genes"]["transfer_values"][0], lay.stat_key("hp"))
      compiled_custom = {c["name"]: c for c in self.project.compile()[0]["layout"]["custom"]}
      self.assertEqual(compiled_custom["current_mp"]["transfer_key"], lay.role_key("current_mp"))
      compiled = self.project.compile()[0]["layout"]
      report = record.layout_report(doc)
      self.assertEqual((report["bytes"], report["hash"]), (compiled["bytes"], compiled["hash"]))
      self.assertEqual(report["budgets"], [("gba", compiled["bytes"], 100)])
      self.assertEqual(report["problems"], [])
      self.assertFalse(report["hash_changed"])
      self.assertEqual(report["saved_hash"], compiled["hash"])
      self.assertEqual((record.party_size(doc), record.move_slots(doc)), (6, 8))
      self.assertTrue(record.party_size_stated(doc))   # E7: a battle states its party size
      self.assertIn("stat_awaken", record.free_engine_roles(doc))
      self.assertNotIn("current_mp", record.engine_roles())
      self.assertIn(f"{compiled['bytes']}/100 B gba", record.layout_lines(doc))

   def test_budget_per_target(self) -> None:
      """!Each target has its own limit; a record over the GBA's is a problem there only.
      @return None
      """
      doc = self.project.battle
      write_project(self.dir, ["gba", "desktop"])
      targets = record.project_targets(doc.path)
      self.assertEqual(targets, ["gba", "desktop"])
      with doc.edit("Big"):
         record.add_custom_role(doc, "ribbons", 8, count=48)
      report = record.layout_report(doc, targets)
      size = report["bytes"]
      self.assertGreater(size, 100)
      self.assertEqual(report["budgets"], [("gba", size, 100), ("desktop", size, 256)])
      self.assertEqual(len(report["problems"]), 1)
      self.assertTrue(report["problems"][0].startswith("gba: "))
      self.assertIsNotNone(self.project.validate("gba"))
      self.assertIsNone(self.project.validate("desktop"))


class RecordEditTests(BattleTestCase):
   """!Editing roles, party size and move slots."""

   def test_custom_role_in_one_undo(self) -> None:
      """!Adding a custom role changes the hash (old saves won't load) until saved; one undo takes it back.
      @return None
      """
      doc = self.project.structure   # the record is the structure manifest's
      before = copy.deepcopy(doc.data)
      saved = record.layout_report(doc)["hash"]
      with doc.edit("Add custom role"):
         at = record.add_custom_role(doc, "gender", 2, default=1, index=12)
      self.assertEqual(at, 12)
      self.assertEqual(roles_of(doc)[12], {"custom": "gender", "width": 2, "default": 1})
      report = record.layout_report(doc)
      self.assertNotEqual(report["hash"], saved)
      self.assertTrue(report["hash_changed"])
      self.assertEqual(report["saved_hash"], saved)
      self.assertTrue(any("old saves won't load" in line for line in record.layout_lines(doc)))
      self.assertEqual(report["hash"], self.project.compile()[0]["layout"]["hash"])
      gender = next(r for r in record.role_rows(doc) if r["name"] == "gender")
      self.assertEqual(gender["id"], 0x81)   # after current_mp
      self.assertIsNone(self.project.validate())
      self.assertTrue(doc.undo())
      self.assertEqual(doc.data, before)
      with doc.edit("Again"):
         record.add_custom_role(doc, "gender", 2)
      self.project.save_all()
      self.assertFalse(record.layout_report(doc)["hash_changed"])

   def test_refusals(self) -> None:
      """!What the engine's compiler refuses is refused, and the manifest stays as it was.
      @return None
      """
      doc = self.project.battle
      before = copy.deepcopy(doc.data)
      refused = [
         lambda: record.add_custom_role(doc, "Bad Name", 4),
         lambda: record.add_custom_role(doc, "level", 4),             # an engine role's name
         lambda: record.add_custom_role(doc, "current_mp", 8),        # held already
         lambda: record.add_custom_role(doc, "wide", 33),
         lambda: record.add_custom_role(doc, "small", 2, default=4),  # does not fit
         lambda: record.add_custom_role(doc, "many", 1, count=256),
         lambda: record.add_engine_role(doc, "level"),                 # held already
         lambda: record.add_engine_role(doc, "owner_name"),            # retired: a custom role now
         lambda: record.add_engine_role(doc, "nothing"),
         lambda: record.remove_role(doc, "level"),                     # battles need it
         lambda: record.remove_role(doc, "nothing"),
         lambda: record.set_role(doc, "species_key", "width", 16),     # fixed width
         lambda: record.set_role(doc, "level", "width", 9),            # above the engine maximum
         lambda: record.set_role(doc, "moves", "count", 2),            # count from move_slots
         lambda: record.set_role(doc, "stat_genes", "count", 2),       # count from the stats
         lambda: record.set_role(doc, "level", "default", 1),          # engine roles have no default here
         lambda: record.set_role(doc, "current_mp", "width", None),    # a custom role needs a width
         lambda: record.set_role(doc, "level", "colour", 1),
         lambda: record.rename_role(doc, "level", "lvl"),              # engine names are fixed
         lambda: record.rename_role(doc, "current_mp", "current_ep"),  # taken
         lambda: record.set_move_slots(doc, 9),
         lambda: record.set_move_slots(doc, 0),
         lambda: record.set_move_slots(doc, 7),                        # Duo Ash & Bly's Emberkit names eight
         lambda: record.set_party_size(doc, 7),                        # the GBA holds six
         lambda: record.set_party_size(doc, 4),                        # formats' party_max is 6
      ]
      for i, fn in enumerate(refused):
         with self.assertRaises(DocumentError, msg=str(i)):
            with doc.edit("Refused"):
               fn()
         self.assertEqual(doc.data, before, i)
      with doc.edit("Wide default"):
         record.add_custom_role(doc, "met", 8, default=200)
      with self.assertRaises(DocumentError):
         with doc.edit("Narrow"):
            record.set_role(doc, "met", "width", 4)                    # the default would not fit

   def test_engine_role_shapes(self) -> None:
      """!Chosen widths and counts are written as objects and dropped again with null; the data still compiles.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Width"):
         self.assertTrue(record.set_role(doc, "stat_genes", "width", 3))
      self.assertIn({"role": "stat_genes", "width": 3}, roles_of(doc))
      with doc.edit("Count"):
         record.set_role(doc, "nickname", "count", 8)
      self.assertIn({"role": "nickname", "count": 8}, roles_of(doc))
      self.assertIsNone(self.project.validate())
      genes = next(r for r in record.role_rows(doc) if r["name"] == "stat_genes")
      self.assertEqual((genes["width"], genes["bits"]), (3, 3 * len(STARTER_STATS)))
      with doc.edit("Back"):
         record.set_role(doc, "stat_genes", "width", 4)   # the Starter's (the default 5 would exceed its gene input)
         record.set_role(doc, "nickname", "count", None)
      self.assertIn({"role": "stat_genes", "width": 4}, roles_of(doc))
      self.assertIn("nickname", roles_of(doc))   # null drops the object form
      with doc.edit("Add engine role"):
         record.add_engine_role(doc, "stat_awaken", index=11, width=4)
      self.assertEqual(roles_of(doc)[11], {"role": "stat_awaken", "width": 4})
      self.assertIsNone(self.project.validate())

   def test_order_rename_and_retired_names(self) -> None:
      """!Moving a custom role moves its ID; renaming changes the hash; a bare retired name written out with its
      old shape keeps the hash.
      @return None
      """
      doc = self.project.structure   # the record is the structure manifest's
      start = record.layout_report(doc)["hash"]
      with doc.edit("Move"):
         self.assertTrue(record.move_role_to(doc, "current_ep", 0))
      ids = {r["name"]: r["id"] for r in record.role_rows(doc)}
      self.assertEqual((ids["current_ep"], ids["current_mp"]), (0x80, 0x81))
      self.assertFalse(record.move_role(doc, "current_ep", -1))
      self.assertTrue(doc.undo())
      self.assertEqual(record.layout_report(doc)["hash"], start)
      with doc.edit("Rename"):
         self.assertTrue(record.rename_role(doc, "current_mp", "mana"))   # the mp resource follows (D-25)
      self.assertNotEqual(record.layout_report(doc)["hash"], start)
      self.assertIsNone(self.project.validate())
      self.assertTrue(doc.undo())
      # A retired engine name (owner_secret: a custom role since E2c) written bare keeps its old shape and hash.
      with doc.edit("Custom"):
         roles_of(doc).insert(3, {"custom": "owner_secret", "width": 16})
      start = record.layout_report(doc)["hash"]
      with doc.edit("Retired"):
         roles_of(doc)[3] = "owner_secret"
      self.assertTrue(next(r for r in record.role_rows(doc) if r["name"] == "owner_secret")["legacy"])
      self.assertEqual(record.layout_report(doc)["hash"], start)
      with doc.edit("Default"):
         record.set_role(doc, "owner_secret", "default", 7)
      self.assertEqual(roles_of(doc)[3], {"custom": "owner_secret", "width": 16, "default": 7})
      self.assertEqual(record.layout_report(doc)["hash"], start)

   def test_object_form(self) -> None:
      """!The first move slots / party size change converts the list form; members and formats follow the limits;
      undo puts the list back.
      @return None
      """
      doc = self.project.structure   # the record is the structure manifest's
      roles = copy.deepcopy(roles_of(doc))
      with doc.edit("Older data"):   # the list form older battle data used (E7 refuses it)
         battle.structure_doc(doc).data["monster_layout"] = copy.deepcopy(roles)
      self.assertFalse(record.party_size_stated(doc))
      self.assertEqual(record.move_slots(doc), engine.tool("battle_compiler").DEFAULT_MOVE_SLOTS)
      with doc.edit("Slots"):
         self.assertTrue(record.set_move_slots(doc, 8))
      self.assertEqual(battle.structure_doc(doc).data["monster_layout"],
                       {"party_size": 6, "move_slots": 8, "roles": roles})
      self.assertEqual(next(r for r in record.role_rows(doc) if r["name"] == "moves")["count"], 8)
      self.assertIsNone(self.project.validate())
      self.assertFalse(record.set_move_slots(doc, 8))
      write_project(self.dir, ["desktop"])
      with doc.edit("Party"):
         self.assertTrue(record.set_party_size(doc, 8, ["desktop"]))
      self.assertEqual(list(battle.structure_doc(doc).data["monster_layout"]), ["party_size", "move_slots", "roles"])
      self.assertIsNone(self.project.validate("desktop"))
      self.assertEqual(len(record.layout_report(doc, ["gba"])["problems"]), 1)   # the GBA holds six
      for _ in range(2):
         self.assertTrue(doc.undo())
      self.assertEqual(battle.structure_doc(doc).data["monster_layout"], roles)
      self.assertTrue(doc.undo())   # back to the sample's object form
      with doc.edit("Fewer moves"):
         battle.entry(doc, "parties", "Duo Ash & Bly")["members"][2]["moves"] = ["Flare Claw", "Smolder"]
         record.set_move_slots(doc, 2)
      self.assertEqual(record.move_slots(doc), 2)
      self.assertIsNone(self.project.validate())

   def test_stat_count_follows_stats(self) -> None:
      """!A new stat gives per-stat roles one element more (and a new hash).
      @return None
      """
      doc = self.project.battle
      start = record.layout_report(doc)["hash"]
      with doc.edit("Add stat"):
         stats.add_stat(doc, "luck")
      genes = next(r for r in record.role_rows(doc) if r["name"] == "stat_genes")
      self.assertEqual(genes["count"], len(STARTER_STATS) + 1)
      self.assertEqual(genes["transfer"][-1], "luck")
      self.assertNotEqual(record.layout_report(doc)["hash"], start)


class RecordCliTests(BattleTestCase):
   """!`battle FILE role ...` and `battle FILE layout`."""

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
      """!list, add, move, rename, set, remove, layout; refused edits are not saved.
      @return None
      """
      b = self.dir / "battle.json"
      status, out = self.run_cli("battle", b, "role", "list")
      self.assertEqual(status, 0)
      self.assertIn("0 species_key [engine 0x00] 32 bit(s) x 1 (one) = 32 bits required", out)
      self.assertIn(f"transfer {', '.join(STARTER_STATS)}", out)
      self.assertIn("transfer role:current_mp 0x", out)
      self.assertEqual(self.run_cli("battle", b, "role", "add", "gender", "--custom", "--width", 2, "--default", 1,
                                    "--at", 3)[0], 0)
      self.assertEqual(roles_of(BattleProject.open(b).battle)[3],
                       {"custom": "gender", "width": 2, "default": 1})
      self.assertEqual(self.run_cli("battle", b, "role", "add", "gender2", "--custom")[0], 1)   # no --width
      self.assertEqual(self.run_cli("battle", b, "role", "move", "gender", "down")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "role", "move", "gender", 0)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "role", "move", "gender", "sideways")[0], 1)
      self.assertEqual(self.run_cli("battle", b, "role", "rename", "gender", "sex")[0], 0)
      self.assertEqual(self.run_cli("battle", b, "role", "set", "sex", "count", 2)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "role", "set", "sex", "default", "null")[0], 0)
      self.assertEqual(roles_of(BattleProject.open(b).battle)[0], {"custom": "sex", "width": 2,
                                                                               "count": 2})
      self.assertEqual(self.run_cli("battle", b, "role", "set", "level", "width", 9)[0], 1)
      self.assertEqual(self.run_cli("battle", b, "role", "remove", "level")[0], 1)
      self.assertEqual(self.run_cli("battle", b, "role", "add", "stat_awaken", "--width", 4)[0], 0)
      self.assertEqual(self.run_cli("battle", b, "role", "remove", "sex")[0], 0)
      status, out = self.run_cli("battle", b, "layout")
      self.assertEqual(status, 0)
      size = BattleProject.open(b).compile()[0]["layout"]["bytes"]
      self.assertIn(f"{size}/100 B gba", out)
      self.assertNotIn("not stated", out)   # the sample states its party size (E7)
      self.assertEqual(self.run_cli("battle", b, "layout", "--move-slots", 6)[0], 1)   # a member names eight
      status, out = self.run_cli("battle", b, "layout", "--party-size", 6)
      self.assertEqual(status, 0)
      self.assertIn("party size 6, move slots 8", out)
      self.assertEqual(BattleProject.open(b).structure.data["monster_layout"]["move_slots"], 8)
      self.assertEqual(self.run_cli("battle", b, "layout", "--party-size", 7)[0], 1)
      # a custom role that takes the record over the GBA's 100 bytes compiles nowhere: not saved
      self.assertEqual(self.run_cli("battle", b, "role", "add", "ribbons", "--custom", "--width", 8, "--count",
                                    64)[0], 1)
      self.assertNotIn("ribbons", record.role_names(BattleProject.open(b).battle))


## A field script naming record roles: by name (with a parenthesised slot operand) and by custom role ID.
FIELD_SCRIPT = """script check_roles {
    role_get(var(slot), current_mp) -> var(v);
    role_set(0, 0x81, 1);
    role_set(SECOND, level, 0, 1);
}
"""


class GameUseTests(BattleTestCase):
   """!The record against the game it is in: party size, the game's targets, field scripts using roles."""

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command.
      @param argv  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()

   def make_game(self, targets: object | None = None, scripts: bool = True) -> Path:
      """!Copies the battle data into a game (reference/project.json) with a scripts manifest using its roles.
      @param targets  the project's "targets", or None for none
      @param scripts  give the game the scripts manifest (FIELD_SCRIPT, a record placeholder)
      @return the game's battle.json
      """
      game = self.dir / "game"
      data = game / "data"
      for f in BattleProject.open(self.dir / "battle.json").files():
         out = data / f.relative_to(self.dir.resolve())   # files() are resolved
         out.parent.mkdir(parents=True, exist_ok=True)
         out.write_bytes(f.read_bytes())
      project = write_project(game, targets)
      if scripts:
         manifest = json.loads(project.read_text(encoding="utf-8"))
         manifest["scripts"] = "data/scripts/scripts.json"
         project.write_text(json.dumps(manifest), encoding="utf-8")
         (data / "scripts").mkdir()
         (data / "scripts" / "field.cscript").write_text(FIELD_SCRIPT, encoding="utf-8")
         (data / "scripts" / "scripts.json").write_text(json.dumps({
            "schema": "capsule.scripts/1", "sources": ["field.cscript"], "battle": "../battle.json",
            "placeholders": {"pal": {"record": "current_ep", "slot": 0}}}), encoding="utf-8")
      return data / "battle.json"

   def test_party_max_follows_layout(self) -> None:
      """!party_add / party_max take the layout's party_size, not the engine's fixed six.
      @return None
      """
      doc = self.project.battle
      small = 3
      self.assertEqual(battle.party_max(doc), engine.tool("battle_compiler").PARTY_SIZE)
      with doc.edit("Smaller parties"):
         for f in battle.entries(doc, "formats"):
            f["party_max"] = small
         record.set_party_size(doc, small)
      self.assertEqual(battle.party_max(doc), small)
      with doc.edit("Fill"):
         while len(battle.entry(doc, "parties", "Novice Kit")["members"]) < small:
            battle.party_add(doc, "Novice Kit", "Voltmink", 5)
      with self.assertRaises(DocumentError) as raised:
         with doc.edit("One too many"):
            battle.party_add(doc, "Novice Kit", "Voltmink", 5)
      self.assertIn(f"at most {small} members", str(raised.exception))
      self.assertEqual(len(battle.entry(doc, "parties", "Novice Kit")["members"]), small)

   def test_saves_check_every_target(self) -> None:
      """!An edit is saved only when the data compiles for every target of the game; errors name the platform.
      @return None
      """
      b = self.make_game(["gba", "desktop"], scripts=False)
      p = BattleProject.open(b)
      self.assertEqual(p.targets(), ["gba", "desktop"])
      with p.battle.edit("Fill"):
         for i in range(5):   # over the GBA's stat limit, within the desktop's
            stats.add_stat(p.battle, f"extra{i}", stage=False, targets=["desktop"])
      p.save_all()
      p = BattleProject.open(b)
      errors = p.target_errors()
      self.assertEqual(len(errors), 1)
      self.assertTrue(errors[0].startswith("gba: "))
      self.assertTrue(p.validate_targets().startswith("gba: "))
      self.assertIsNone(p.validate_targets(["desktop"]))
      status, out = self.run_cli("battle", b, "stat", "set", "extra0", "label", "Extra")
      self.assertEqual(status, 1)
      self.assertIn("not saved: gba: ", out)
      self.assertNotIn("Extra", (b.parent / "structure.json").read_text(encoding="utf-8"))
      write_project(b.parent.parent, ["desktop"])   # desktop only: the same edit saves
      self.assertEqual(self.run_cli("battle", b, "stat", "set", "extra0", "label", "Extra")[0], 0)
      self.assertIn("Extra", (b.parent / "structure.json").read_text(encoding="utf-8"))

   def test_field_scripts_using_roles(self) -> None:
      """!role_get / role_set statements and record placeholders that use a role are listed; the CLI refuses
      to remove or rename such a role without --force.
      @return None
      """
      self.assertEqual(record.role_users(self.project.battle, "current_mp"), [])   # in no game
      b = self.make_game()
      doc = BattleProject.open(b).battle
      users = record.role_users(doc, "current_mp")
      self.assertEqual(users, ["scripts: field.cscript line 2 (role_get current_mp)"])
      # removing the first custom role moves current_ep's ID (0x81), which the script names by number
      removing = record.role_users(doc, "current_mp", removing=True)
      self.assertEqual(len(removing), 2)
      self.assertIn("line 3 (role_set role ID 0x81", removing[1])
      self.assertEqual(record.role_users(doc, "current_ep"), ["scripts: placeholder {pal} (record current_ep)"])
      self.assertEqual(record.role_users(doc, "level"), ["scripts: field.cscript line 4 (role_set level)"])
      self.assertEqual(record.role_users(doc, "nickname"), [])

      structure = b.parent / "structure.json"
      before = structure.read_text(encoding="utf-8")
      status, out = self.run_cli("battle", b, "role", "remove", "current_mp")
      self.assertEqual(status, 1)
      self.assertEqual(structure.read_text(encoding="utf-8"), before)
      status, out = self.run_cli("battle", b, "role", "rename", "current_ep", "fondness")
      self.assertEqual(status, 1)
      self.assertEqual(structure.read_text(encoding="utf-8"), before)
      status, out = self.run_cli("battle", b, "role", "rename", "current_ep", "fondness", "--force")
      self.assertEqual(status, 0)
      self.assertIn("warning: field scripts use the role 'current_ep'", out)
      self.assertIn("fondness", record.role_names(BattleProject.open(b).battle))
      # a manifest whose scripts read another battle's record does not count
      sj = b.parent / "scripts" / "scripts.json"
      sj.write_text(sj.read_text(encoding="utf-8").replace("../battle.json", "../other.json"), encoding="utf-8")
      self.assertEqual(record.role_users(BattleProject.open(b).battle, "current_mp"), [])


   def test_storing_moves_ids_from_the_stored_position(self) -> None:
      """!C5: storing an unstored custom role again moves the custom IDs from its stored-position ID on (below its
      unstored ID), so the scan for scripts naming custom roles by ID starts there: the script's role ID 0x81 (now
      current_mp's, glint's once stored) is listed; unstoring scans from the role's own ID.
      @return None
      """
      b = self.make_game()
      doc = BattleProject.open(b).battle
      first = next(r["index"] for r in record.role_rows(doc) if r["name"] == "current_mp")
      with doc.edit("Glint"):
         record.add_custom_role(doc, "glint", 1, index=first)
         k = progression.add_entry(doc, "glint", progression.CONSTANT_WAY)
         progression.set_constant(doc, k, 1)
         record.set_stored(doc, "glint", False)
      rows = {r["name"]: r for r in record.role_rows(doc)}
      base = engine.tool("battle_compiler").CUSTOM_ROLE_BASE
      # glint takes the ID after every stored custom role's (current_mp, current_ep and G4's form)
      stored = sum(1 for r in rows.values() if r["kind"] == record.KIND_CUSTOM and r["stored"])
      self.assertEqual((rows["current_mp"]["id"], rows["glint"]["id"]), (base, base + stored))
      self.assertEqual(record.stored_position_id(doc, "glint"), base)
      storing = record.role_users(doc, "glint", removing=True, storing=True)
      self.assertTrue(any("role ID 0x81" in u for u in storing), storing)
      self.assertFalse(any("role ID" in u for u in record.role_users(doc, "glint", removing=True)))
      self.assertIsNone(record.stored_position_id(doc, "level"))


if __name__ == "__main__":
   unittest.main()
