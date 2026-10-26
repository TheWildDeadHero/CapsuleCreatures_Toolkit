#!/usr/bin/env python3
"""!Smoke tests of the G2 pages: Structure > Pockets, Content > Passives / Items (the Items tab's bag box and use
logic, the Shops tab) and Content > Test save (Bag). Each opens a copy of the Starter sample laid out as a game and
edits through the widgets (one undo step per manifest edit). Skipped when PySide6 is missing; uses Qt's offscreen
platform. CAPSULE_SHOTS=FOLDER saves a picture of each page there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle, inventory  # noqa: E402
from capsule_studio.core.structure import pockets  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## Environment variable naming a folder for the pages' pictures.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a picture, pixels.
SHOT_SIZE = (1100, 680)


class InventoryPagesTests(QtBattleTestCase):
   """!The Pockets, Items and Test save pages."""

   def window(self, panel_id: str) -> tuple[object, object]:
      """!A battle editor on the copy hosting the bag's pages (and Logic > Effects, which their Logic... buttons
      open), one in front.
      @param panel_id  the page's panel id
      @return (BattleWindow, the panel)
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.editors.content.holders import PassivesItemsPanel
      from capsule_studio.ui.editors.content.test_save import TestSavePanel
      from capsule_studio.ui.editors.logic.effects_panel import EffectsPanel
      from capsule_studio.ui.editors.structure.pockets import PocketsPanel
      w = BattleWindow([PassivesItemsPanel, TestSavePanel, PocketsPanel, EffectsPanel], self.battle_json)
      panel = w.show_panel(panel_id)
      self.settle()
      return w, panel

   def shot(self, w: object, panel: object, name: str) -> None:
      """!Saves a picture of a page when CAPSULE_SHOTS names a folder.
      @param w      the window
      @param panel  the page
      @param name   file stem
      @return None
      """
      shots = os.environ.get(SHOTS_ENV)
      if not shots:
         return
      Path(shots).mkdir(parents=True, exist_ok=True)
      w.resize(*SHOT_SIZE)
      w.show()
      self.settle()
      panel.grab().save(str(Path(shots) / f"{name}.png"))

   def test_pockets_page(self) -> None:
      """!The sample's pockets with the budget; add, rename by typing (items follow), sort combo, remove.
      @return None
      """
      from capsule_studio.ui.editors.structure.pockets import LABEL_COLUMN, NAME_COLUMN
      w, panel = self.window("pockets")
      p = w.project
      self.assertIs(w.document, p.structure)
      names = pockets.pocket_names(p.structure)
      self.assertEqual(panel.table.rowCount(), len(names))
      self.assertIn("bag slots", panel.budget.text())
      self.shot(w, panel, "pockets")
      panel.selected = names[-1]
      self.assertTrue(panel.add_pocket("spare"))
      self.settle()
      self.assertEqual(pockets.pocket_names(p.structure)[-1], "spare")
      self.assertEqual(w.undo_action.text(), "Undo Add pocket")
      first_items = pockets.users(p.structure, names[0])
      panel.table.item(0, NAME_COLUMN).setText("gear")
      self.settle()
      self.assertEqual(pockets.users(p.structure, "gear"), first_items)
      panel.table.item(0, LABEL_COLUMN).setText("Gear")
      self.settle()
      self.assertEqual(p.structure.data["pockets"][0]["label"], "Gear")
      panel.selected = "gear"
      self.assertTrue(panel.set_field("sort", "index"))
      self.settle()
      self.assertEqual(pockets.rows(p.structure)[0]["sort"], "index")
      self.assertFalse(panel.remove_pocket())   # items name it
      panel.selected = "spare"
      self.assertTrue(panel.remove_pocket())
      self.settle()
      self.assertNotIn("spare", pockets.pocket_names(p.structure))

   def test_items_tab(self) -> None:
      """!The bag box shows the engine's choices and the item's fields; a use change adds a stub handler.
      @return None
      """
      w, panel = self.window("passives_items")
      tab = panel.items
      panel.tabs.setCurrentWidget(tab)
      p = w.project
      usable = next(i["name"] for i in battle.entries(p.battle, "items") if i.get("use") in ("field", "both"))
      self.select(tab, usable)
      self.assertEqual([tab.use.itemText(i) for i in range(tab.use.count())], inventory.uses())
      self.assertEqual(tab.use.currentText(), inventory.fields_of(p.battle, usable)["use"])
      self.assertIn("on use_field", tab.use_text.toPlainText())
      self.shot(w, panel, "items")
      plain = next(i["name"] for i in battle.entries(p.battle, "items")
                   if i.get("use", "none") == "none" and i.get("pocket") is not None)
      self.select(tab, plain)
      self.assertTrue(tab.set_field(inventory.USE_KEY, "field"))
      self.settle()
      self.assertEqual(inventory.fields_of(p.battle, plain)["use"], "field")
      self.assertIn("fail;", tab.use_text.toPlainText())
      self.assertTrue(tab.add_use("use_battle"))
      self.settle()
      self.assertEqual(inventory.fields_of(p.battle, plain)["use"], "both")
      self.assertIsNone(p.error_now())
      # the Shops tab
      shops = panel.shops
      panel.tabs.setCurrentWidget(shops)
      self.assertEqual(shops.shop_list.count(), len(inventory.shop_names(p.battle)))
      self.assertTrue(shops.add_shop("Booth"))
      self.settle()
      self.assertTrue(shops.add_item(usable))
      self.settle()
      self.assertEqual(inventory.shops(p.battle)[-1]["items"], [usable])
      self.shot(w, panel, "shops")

   def test_test_save_page(self) -> None:
      """!A new test save, Put into the shown pocket, Take, Export the engine image.
      @return None
      """
      w, panel = self.window("test_save")
      p = w.project
      self.assertTrue(panel.new_save("page"))
      self.settle()
      pocket = pockets.pocket_names(p.battle)[0]
      panel.show_pocket(pocket)
      items = panel.pocket_items(pocket)
      self.assertTrue(items)
      self.assertTrue(panel.put(items[0], 2))
      self.settle()
      self.assertEqual(inventory.bag_of(panel.save)[pocket], [{"item": items[0], "count": 2}])
      if len(items) > 1:
         self.assertTrue(panel.put(items[1], 1))
         self.settle()
      self.assertIn("fits", panel.problems.text())
      self.shot(w, panel, "bag")
      panel.table.selectRow(0)
      self.assertTrue(panel.take_selected(1))
      self.settle()
      self.assertEqual(inventory.bag_of(panel.save)[pocket][0]["count"], 1)
      out = self.root / "page.sav"
      self.assertTrue(panel.export_save(out))
      self.assertTrue(out.read_bytes().startswith(b"CCSV"))


if __name__ == "__main__":
   import unittest
   unittest.main()
