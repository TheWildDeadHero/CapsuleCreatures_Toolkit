#!/usr/bin/env python3
"""!Tests for the bag in the studio (D-26 section 2, engine G2): core.structure.pockets (the structure's pockets),
core.inventory (the items' bag and use fields, their use logic, the shop lists, test saves and their engine save
image) and the `battle FILE pocket|item-field|item-logic|shop|testsave ...` commands. No Qt.

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase): its four pockets (Supplies, Orbs, Charms,
Key), its items and shops are read from the sample, so a re-tuned Starter needs few test edits.
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
from capsule_studio.core import battle, engine, inventory  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import pockets  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402


class PocketTests(BattleTestCase):
   """!The structure's pockets."""

   def test_rows_and_budget(self) -> None:
      """!The sample's pockets as the engine lays them out; the budget names the engine's limits.
      @return None
      """
      doc = self.project.structure
      given = [p["name"] for p in doc.data["pockets"]]
      rows = pockets.rows(doc)
      self.assertEqual([r["name"] for r in rows], given)
      self.assertEqual(rows[1]["first"], rows[0]["capacity"])
      self.assertEqual(pockets.compile_check(doc)[1], None)
      bs = engine.tool("build_settings")
      text, over = pockets.budget(doc, ["gba"])
      self.assertIn(f"/{bs.platform_limits('gba')['max_pockets']} pockets", text)
      self.assertFalse(over)
      self.assertEqual(pockets.sort_rules(), list(engine.tool("battle_compiler").SORT_RULES))

   def test_edits(self) -> None:
      """!Add, rename (items follow), set fields, move, remove (refused while items name it); one undo step each.
      @return None
      """
      doc = self.project.structure
      first = pockets.pocket_names(doc)[0]
      holders = pockets.users(doc, first)
      with doc.edit("Add pocket"):
         pockets.add_pocket(doc, "extra", "Extra", 3)
      self.assertEqual(pockets.pocket_names(doc)[-1], "extra")
      with doc.edit("Rename pocket"):
         self.assertEqual(pockets.rename_pocket(doc, first, "gear"), len(holders))
      self.assertEqual(pockets.users(doc, "gear"), holders)
      with doc.edit("Pocket sort"):
         pockets.set_field(doc, "gear", "sort", "name")
      self.assertEqual(pockets.rows(doc)[0]["sort"], "name")
      with self.assertRaises(DocumentError):
         with doc.edit("Pocket sort"):
            pockets.set_field(doc, "gear", "sort", "price")
      with self.assertRaisesRegex(DocumentError, "move them"):
         with doc.edit("Remove pocket"):
            pockets.remove_pocket(doc, "gear")
      with doc.edit("Move pocket"):
         self.assertTrue(pockets.move_pocket(doc, "extra", -1))
      with doc.edit("Remove pocket"):
         pockets.remove_pocket(doc, "extra")
      doc.undo()
      self.assertIn("extra", pockets.pocket_names(doc))
      with self.assertRaisesRegex(DocumentError, "lower-case"):
         with doc.edit("Add pocket"):
            pockets.add_pocket(doc, "Bad Name")
      # a pocket the engine refuses (a quantity past the engine's most) is refused with its message
      with self.assertRaises(DocumentError):
         with doc.edit("Pocket quantity"):
            pockets.set_field(doc, "gear", "quantity_max", pockets.max_quantity() + 1)


class ItemTests(BattleTestCase):
   """!The items' bag fields, use logic and shops."""

   def usable(self) -> str:
      """!The first item used out of battle.
      @return its name
      """
      return next(i["name"] for i in battle.entries(self.project.battle, "items") if i.get("use") in ("field", "both"))

   def test_fields(self) -> None:
      """!Defaults filled in; a set leaves defaults out; the engine refuses a bad value.
      @return None
      """
      doc = self.project.battle
      name = self.usable()
      f = inventory.fields_of(doc, name)
      self.assertIn(f["use"], inventory.uses())
      self.assertIn(f["pocket"], pockets.pocket_names(doc))
      with doc.edit("Item price"):
         inventory.set_item_field(doc, name, "price", 7)
      self.assertEqual(battle.entry(doc, "items", name)["price"], 7)
      with doc.edit("Item holdable"):
         inventory.set_item_field(doc, name, "holdable", True)   # the default (not a key item): left out
      self.assertNotIn("holdable", battle.entry(doc, "items", name))
      with self.assertRaisesRegex(DocumentError, "no price"):   # a shop sells it
         with doc.edit("Item price"):
            inventory.set_item_field(doc, name, "price", 0)
      with self.assertRaises(DocumentError):
         with doc.edit("Item target"):
            inventory.set_item_field(doc, name, "target", "battler")   # a battle's target, a field use
      with self.assertRaises(DocumentError):
         with doc.edit("Item use"):
            inventory.set_item_field(doc, name, "use", "anywhere")
      self.assertEqual(inventory.targets(), list(engine.tool("battle_compiler").ITEM_TARGETS))

   def test_use_logic(self) -> None:
      """!A use that needs a hook gets a stub handler; Add grows the use; the handlers show as text.
      @return None
      """
      doc = self.project.battle
      plain = next(i["name"] for i in battle.entries(doc, "items") if i.get("use", "none") == "none"
                   and i.get("pocket") is not None)
      with doc.edit("Item use"):
         inventory.set_item_field(doc, plain, "use", "field")
      logic = inventory.use_logic(self.project, plain)
      self.assertIn("fail;", logic["use_field"])
      self.assertIsNone(logic["use_battle"])
      with doc.edit("Add use logic"):
         inventory.add_use_handler(self.project, plain, "use_battle")
      self.assertEqual(inventory.fields_of(doc, plain)["use"], "both")
      self.assertIsNone(self.project.error_now())
      with self.assertRaisesRegex(DocumentError, "already"):
         with doc.edit("Add use logic"):
            inventory.add_use_handler(self.project, plain, "use_battle")

   def test_shops(self) -> None:
      """!Shops: add, put an item, rename an item (the shop follows), refuse an item without a price.
      @return None
      """
      doc = self.project.battle
      given = inventory.shop_names(doc)
      with doc.edit("Add shop"):
         inventory.add_shop(doc, "Test Stall")
      name = self.usable()
      with doc.edit("Shop item"):
         inventory.add_shop_item(doc, "Test Stall", name)
      with doc.edit("Rename item"):
         battle.rename_entry(doc, "items", name, "Renamed Thing")
      self.assertEqual(inventory.shops(doc)[-1]["items"], ["Renamed Thing"])
      key = next(i["name"] for i in battle.entries(doc, "items") if i.get("key"))
      with self.assertRaisesRegex(DocumentError, "no price"):
         with doc.edit("Shop item"):
            inventory.add_shop_item(doc, "Test Stall", key)
      self.assertEqual(inventory.shop_names(doc), given + ["Test Stall"])


class TestSaveTests(BattleTestCase):
   """!Test saves and their engine save image."""

   def test_put_check_export(self) -> None:
      """!Put into the item's pocket, refuse past quantity_max, check, export the engine image (save_layout.image()).
      @return None
      """
      doc = self.project.battle
      save = inventory.new_testsave(self.project, "t1")
      item = next(i["name"] for i in battle.entries(doc, "items") if i.get("pocket"))
      pocket = inventory.fields_of(doc, item)["pocket"]
      most = next(r["quantity_max"] for r in pockets.rows(doc) if r["name"] == pocket)
      with save.edit("Put"):
         self.assertEqual(inventory.put(save, doc, item, most), most)
      with self.assertRaisesRegex(DocumentError, "at most"):
         with save.edit("Put"):
            inventory.put(save, doc, item, 1)
      self.assertEqual(inventory.check(save, doc), [])
      data = inventory.image_of(save, self.project)
      sl = engine.tool("save_layout")
      self.assertEqual(data[:4], sl.MAGIC.to_bytes(4, "little"))
      compiled, _e = self.project.compile()
      # C6: the filled bag entries only (at most the build's image), format version 2
      self.assertLessEqual(len(data), sl.image_bytes(sl.sections_of(compiled)))
      self.assertEqual(int.from_bytes(data[4:6], "little"), sl.VERSION)
      save.data["pockets"][pocket].append({"item": "Nothing", "count": 1})
      self.assertTrue(any("unknown item" in p for p in inventory.check(save, doc)))
      with self.assertRaises(DocumentError):
         inventory.image_of(save, self.project)


class CommandTests(BattleTestCase):
   """!The commands."""

   def run_cli(self, *args: str) -> tuple[int, str]:
      """!Runs one command on the copy.
      @param args  arguments after `battle FILE`
      @return (exit status, output)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         code = cli(["battle", str(self.dir / "battle.json"), *args])
      return code, out.getvalue() + err.getvalue()

   def test_commands(self) -> None:
      """!pocket / item-field / item-logic / shop / testsave round trips, saved only when they compile.
      @return None
      """
      code, out = self.run_cli("pocket", "list")
      self.assertEqual(code, 0)
      self.assertIn("bag slots", out)
      self.assertEqual(self.run_cli("pocket", "add", "extra", "--capacity", "2")[0], 0)
      saved = json.loads((self.dir / "structure.json").read_text())
      self.assertEqual(saved["pockets"][-1], {"name": "extra", "capacity": 2})
      self.assertEqual(self.run_cli("pocket", "set", "extra", "sort", "index")[0], 0)
      item = next(i["name"] for i in battle.entries(self.project.battle, "items") if i.get("pocket"))
      code, out = self.run_cli("item-field", item)
      self.assertIn("pocket:", out)
      self.assertEqual(self.run_cli("item-field", item, "pocket", "extra")[0], 0)
      self.assertEqual(self.run_cli("pocket", "remove", "extra")[0], 1)   # an item names it
      self.assertEqual(self.run_cli("pocket", "remove", "extra", "--unpocket")[0], 1)   # a shop sells it now
      code, out = self.run_cli("item-logic", item)
      self.assertEqual(code, 0)
      self.assertEqual(self.run_cli("shop", "add", "Kiosk")[0], 0)
      self.assertIn("Kiosk", self.run_cli("shop", "list")[1])
      self.assertEqual(self.run_cli("testsave", "new", "cli")[0], 0)
      self.assertEqual(self.run_cli("testsave", "put", "cli", item, "1")[0], 0)
      self.assertEqual(self.run_cli("testsave", "check", "cli")[0], 0)
      out_file = self.dir / "cli.sav"
      self.assertEqual(self.run_cli("testsave", "export", "cli", str(out_file))[0], 0)
      self.assertTrue(out_file.read_bytes().startswith(b"CCSV"))
      self.assertIn(item, self.run_cli("testsave", "show", "cli")[1])


if __name__ == "__main__":
   unittest.main()
