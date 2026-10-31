#!/usr/bin/env python3
"""!Smoke tests of the G3 pages: Structure > Recruit (the rules, the status bonuses, the messages, the odds preview),
Structure > Storage (the boxes, the budget, the save image), the Items tab's Recruit row, Logic > AI's item-use
rules and the Test save page's Boxes box. Each opens a copy of the Starter sample laid out as a game and edits
through the widgets (one undo step per manifest edit). Skipped when PySide6 is missing; uses Qt's offscreen
platform. CAPSULE_SHOTS=FOLDER saves a picture of each page there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import ai, battle  # noqa: E402
from capsule_studio.core.structure import recruit, storage  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## Environment variable naming a folder for the pages' pictures.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a picture, pixels.
SHOT_SIZE = (1200, 760)


class RecruitPagesTests(QtBattleTestCase):
   """!The Recruit, Storage, Items, AI and Test save pages."""

   def window(self, panel_id: str) -> tuple[object, object]:
      """!A battle editor on the copy hosting the G3 pages (and Logic > Effects for the Logic... buttons).
      @param panel_id  the page's panel id
      @return (BattleWindow, the panel)
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.editors.content.holders import PassivesItemsPanel
      from capsule_studio.ui.editors.content.test_save import TestSavePanel
      from capsule_studio.ui.editors.logic.ai_panel import AiPanel
      from capsule_studio.ui.editors.logic.effects_panel import EffectsPanel
      from capsule_studio.ui.editors.structure.recruit import RecruitPanel
      from capsule_studio.ui.editors.structure.storage import StoragePanel
      w = BattleWindow([RecruitPanel, StoragePanel, PassivesItemsPanel, TestSavePanel, AiPanel, EffectsPanel],
                       self.battle_json)
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

   def test_recruit_page(self) -> None:
      """!The sample's rules and the preview; checks, a status bonus by typing, keep, undo.
      @return None
      """
      from capsule_studio.ui.editors.structure.recruit import BONUS_COLUMN
      w, panel = self.window("recruit")
      p = w.project
      self.assertIs(w.document, p.structure)
      s = recruit.section(p.structure)
      self.assertEqual(panel.checks.value(), s["checks"])
      self.assertEqual(panel.rate.currentText(), s["rate"])
      self.assertEqual(panel.bonus.rowCount(), len(s["status_bonus"]))
      self.assertIn("checks", panel.odds.text())
      self.assertIn("Orb", panel.items.text())
      self.assertFalse(panel.enable_button.isEnabled())
      self.shot(w, panel, "recruit")
      self.assertTrue(panel.set_field("checks", 2))
      self.settle()
      self.assertEqual(p.structure.data["recruit"]["checks"], 2)
      self.assertEqual(w.undo_action.text(), "Undo Recruit checks")
      panel.bonus.item(1, BONUS_COLUMN).setText("40")
      self.settle()
      status = panel.bonus.item(1, 0).text()
      self.assertEqual(recruit.section(p.structure)["status_bonus"][status], 40)
      panel.keep[recruit.keeps()[-1]].setChecked(True)
      self.assertTrue(panel.set_keep())
      self.settle()
      self.assertIn(recruit.keeps()[-1], recruit.section(p.structure)["keep"])
      w.undo_action.trigger()
      self.settle()
      self.assertNotIn(recruit.keeps()[-1], recruit.section(p.structure)["keep"])
      self.assertIsNone(p.error_now())

   def test_storage_page(self) -> None:
      """!The sample's boxes with the budget and the save line; a box renamed by typing, the count, undo.
      @return None
      """
      from capsule_studio.ui.editors.structure.storage import NAME_COLUMN
      w, panel = self.window("storage")
      p = w.project
      self.assertEqual(panel.table.rowCount(), len(storage.box_names(p.structure)))
      self.assertIn("boxes", panel.budget.text())
      self.assertIn("save image", panel.save_line.text())
      self.shot(w, panel, "storage")
      panel.table.item(0, NAME_COLUMN).setText("Home")
      self.settle()
      self.assertEqual(storage.box_names(p.structure)[0], "Home")
      self.assertTrue(panel.set_field(storage.COUNT_KEY, 4))
      self.settle()
      self.assertEqual(len(storage.box_names(p.structure)), 4)
      w.undo_action.trigger()
      self.settle()
      self.assertEqual(len(storage.box_names(p.structure)), storage.section(p.structure)["box_count"])
      self.assertIsNone(p.error_now())

   def test_items_recruit_row(self) -> None:
      """!The Orb shows its bonus; Recruit makes another item recruit (use, target, logic in one step).
      @return None
      """
      w, panel = self.window("passives_items")
      tab = panel.items
      panel.tabs.setCurrentWidget(tab)
      p = w.project
      self.select(tab, "Orb")
      self.assertIn("bonus", tab.recruit_info.text())
      self.shot(w, panel, "items_recruit")
      plain = next(i["name"] for i in battle.entries(p.battle, "items")
                   if i.get("use", "none") == "none" and i.get("pocket") is not None)
      self.select(tab, plain)
      self.assertTrue(tab.set_recruit(12))
      self.settle()
      self.assertEqual(recruit.recruit_bonus(p, plain), "12")
      self.assertIn("recruit holder 12", tab.use_text.toPlainText())
      self.assertIsNone(p.error_now())

   def test_ai_item_rules(self) -> None:
      """!The item-use box shows the Strategist's rule with its item; add one, change its item.
      @return None
      """
      w, panel = self.window("ai")
      p = w.project
      name = next(r["name"] for r in ai.profile_rows(p.battle) if r["items"])
      panel.select(name)
      self.settle()
      box = panel.boxes[ai.ITEMS_KEY]
      self.assertEqual(box.table.rowCount(), len(ai.rule_rows(p.battle, name, ai.ITEMS_KEY)))
      box.table.selectRow(0)
      self.settle()
      self.assertIsNotNone(box.item)
      self.shot(w, panel, "ai_items")
      self.assertTrue(box.add_rule("below_hp"))
      self.settle()
      rows = ai.rule_rows(p.battle, name, ai.ITEMS_KEY)
      last = ai.item_choices(p.battle)[-1]
      box.selected = len(rows) - 1
      self.assertTrue(box.set_item(last))
      self.settle()
      self.assertEqual(ai.rule_rows(p.battle, name, ai.ITEMS_KEY)[-1]["item"], last)

   def test_test_save_boxes(self) -> None:
      """!Box creatures into the current box, change the box, unbox, export.
      @return None
      """
      w, panel = self.window("test_save")
      p = w.project
      self.assertTrue(panel.new_save("boxes"))
      self.settle()
      species = [e["name"] for e in battle.entries(p.battle, "species")]
      self.assertTrue(panel.box_creature(species[0], 12))
      self.settle()
      self.assertTrue(panel.set_current_box(1))
      self.settle()
      self.assertTrue(panel.box_creature(species[1], 8))
      self.settle()
      boxed = storage.boxed_of(panel.save)
      self.assertEqual([b["slot"] for b in boxed], [0, storage.section(p.battle)["box_size"]])
      self.assertEqual(panel.boxed.rowCount(), 2)
      self.shot(w, panel, "test_save_boxes")
      panel.boxed.selectRow(0)
      self.assertTrue(panel.unbox_selected())
      self.settle()
      self.assertEqual(len(storage.boxed_of(panel.save)), 1)
      out = self.root / "boxes.sav"
      self.assertTrue(panel.export_save(out))
      self.assertTrue(out.read_bytes().startswith(b"CCSV"))


if __name__ == "__main__":
   import unittest
   unittest.main()
