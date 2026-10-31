#!/usr/bin/env python3
"""!Smoke tests of the S5b panels: Structure > Conditions, Flags & Tags and
Categories, Content > Passives / Items, the Tiers table's height and the
battle window's non-modal edit refusals. Each opens a copy of the battle
sandbox laid out as a game, edits through the widgets (one undo step per
edit, renames grouped with their effect source edits), undoes and saves.
Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle, holders  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import categories, conditions, flags  # noqa: E402
from test_qt_battle import QtBattleTestCase, QtWidgets  # noqa: E402
from test_structure_conditions import add_flag_records  # noqa: E402

## The effect source holding the Starter's move logic.
MOVES = "effects/moves.ceffect"
## Window size of the layout check (the tiers table's last row must show).
CHECK_WIDTH = 1400
## See CHECK_WIDTH.
CHECK_HEIGHT = 900


def flag_records_game(battle_json: Path) -> None:
   """!Saves test_structure_conditions.add_flag_records()'s records into a game copy (Frost thawed by the thaws flag,
   guard_chain kept by guarding, guard).
   @param battle_json  the copy's battle.json
   @return None
   """
   p = BattleProject.open(battle_json)
   add_flag_records(p.battle)
   p.save_all()


class ConditionsPanelTests(QtBattleTestCase):
   """!The Conditions page."""

   def test_open_and_budget(self) -> None:
      """!One tab per kind with the sample's records; the budget bars count the engine's storage.
      @return None
      """
      flag_records_game(self.battle_json)
      w, panel = self.window("conditions")
      self.assertIs(w.document, w.project.structure)   # a structure page edits structure.json
      self.assertEqual([panel.tabs.tabText(i) for i in range(panel.tabs.count())],
                       ["Statuses", "Weathers", "Volatiles", "Side conditions", "Field conditions"])
      self.assertEqual(list(panel.kind_tabs), conditions.kinds())   # the engine's LOGIC_KINDS order
      self.assertEqual(panel.tab("volatile").names(), ["flinch", "dazed", "guard_chain", "guard"])
      self.assertEqual(panel.budget.text_of("volatile bits"), "volatile bits 4/32")
      self.assertEqual(panel.budget.text_of("volatile counters"), "volatile counters 2/8")
      tab = panel.show_kind("volatile")
      tab.select("guard_chain")
      self.settle()
      field, parts = tab.inputs["chain"]
      self.assertTrue(parts["check"].isChecked())
      self.assertEqual((parts["den"].value(), parts["cap"].value(), parts["kept_by"].currentText()),
                       (3, 8, "guarding"))
      tab.select("dazed")
      self.settle()
      self.assertEqual(tab.inputs["duration"][1]["combo"].currentText(), conditions.RANGE_DURATION)
      self.assertEqual(tab.texts.slots, ["start", "already", "end"])
      self.assertIn("move Cyclone", tab.used_by.text())
      self.close(w)

   def test_edit_undo_save(self) -> None:
      """!Fields, texts, a new record and a rename (with its logic): one undo step each; saves.
      @return None
      """
      w, panel = self.window("conditions")
      doc = w.project.battle
      weather = panel.show_kind("weather")
      weather.select("Storm")
      self.settle()
      spin = weather.inputs["turns"][1]["spin"]
      spin.setValue(8)
      spin.editingFinished.emit()
      self.settle()
      self.assertEqual(conditions.record(doc, "weather", "Storm")["turns"], 8)
      self.assertEqual(w.undo_action.text(), "Undo Turns")
      weather.texts.table.item(1, 2).setText("The storm keeps raging.")
      self.settle()
      self.assertEqual(conditions.record(doc, "weather", "Storm")["texts"]["continues"], "The storm keeps raging.")
      # A text the encoder refuses is not stored and nothing waits for a click.
      with mock.patch.object(QtWidgets.QMessageBox, "warning") as box:
         weather.texts.table.item(1, 2).setText("{target} is wet")
         self.settle()
      box.assert_not_called()
      self.assertIn("{target}", w.edit_error[1])
      self.assertEqual(conditions.record(doc, "weather", "Storm")["texts"]["continues"], "The storm keeps raging.")
      side = panel.show_kind("side_condition")
      self.assertTrue(side.add_record("spikes"))
      self.settle()
      self.assertEqual(side.selected, "spikes")
      side.inputs["layers"][1]["spin"].setValue(3)
      side.inputs["layers"][1]["spin"].editingFinished.emit()
      side.texts.add_slot("start", "Spikes lie around {target}!")
      self.settle()
      self.assertEqual(conditions.record(doc, "side_condition", "spikes"),
                       {"name": "spikes", "layers": 3, "texts": {"start": "Spikes lie around {target}!"}})
      vol = panel.show_kind("volatile")
      vol.select("dazed")
      self.settle()
      self.assertTrue(vol.rename_record("stunned"))
      self.settle()
      self.assertIn("vol_on target stunned;", w.project.effect_source(MOVES).text)
      w.undo()
      self.settle()
      self.assertIn("vol_on target dazed;", w.project.effect_source(MOVES).text)
      self.assertIn("dazed", vol.names())
      vol.select("flinch")
      self.settle()
      self.assertFalse(vol.remove_record())   # Shadow Bite's logic names it
      self.assertIn("still named by", w.edit_error[1])
      self.assertIsNone(w.project.validate())
      self.assertTrue(w.save_all())
      self.assertEqual(self.saved()["side_conditions"][0]["layers"], 3)
      self.close(w)

   def test_logic_button(self) -> None:
      """!"Logic..." shows the record's owner on the Effects page.
      @return None
      """
      w, panel = self.window("conditions")
      tab = panel.show_kind("volatile")
      tab.select("dazed")
      self.settle()
      self.assertTrue(tab.open_logic())
      self.settle()
      effects = w.active_panel()
      self.assertEqual(effects.panel_id, "effects")
      self.assertEqual(effects.owner, ("volatile", "dazed"))
      self.close(w)


class FlagsCategoriesHoldersTests(QtBattleTestCase):
   """!Flags & Tags, Categories and Passives / Items."""

   def test_flags_and_tags(self) -> None:
      """!Typing a name renames it everywhere; a used name is not removed; tags add.
      @return None
      """
      from capsule_studio.ui.editors.structure.flags import NAME_COLUMN, USES_COLUMN
      flag_records_game(self.battle_json)
      w, panel = self.window("flags")
      doc = w.project.battle
      box = panel.box(flags.FLAGS_KEY)
      names = box.names()
      r = names.index("thaws")
      self.assertEqual(box.table.item(r, USES_COLUMN).text(), "1")
      box.table.item(r, NAME_COLUMN).setText("melts")
      self.settle()
      self.assertEqual(conditions.record(doc, "status", "Frost")["thawed_by_move"], "melts")
      box.selected = "contact"
      self.assertFalse(box.remove_name())
      self.assertIn("contact", flags.names(doc, flags.FLAGS_KEY))
      tags = panel.box(flags.TAGS_KEY)
      self.assertTrue(tags.add_name("grounded"))
      self.settle()
      self.assertEqual(flags.names(doc, flags.TAGS_KEY), ["grounded"])
      self.assertIn("1/16 tags", tags.budget.text())
      w.undo()
      w.undo()
      self.settle()
      self.assertEqual(conditions.record(doc, "status", "Frost")["thawed_by_move"], "thaws")
      self.close(w)

   def test_categories(self) -> None:
      """!Damaging toggles, renames follow the moves, the cap is the engine's.
      @return None
      """
      from capsule_studio.ui.editors.structure.categories import CATEGORY_COLUMN
      w, panel = self.window("categories")
      doc = w.project.battle
      self.assertEqual(panel.table.rowCount(), 3)
      self.assertIn("3/4", panel.budget.text())
      self.assertTrue(panel.add_category("mixed"))
      self.settle()
      self.assertFalse(categories.category_rows(doc)[3]["damaging"])
      panel.row_widgets[3]["damaging"].click()
      self.settle()
      self.assertEqual(categories.category_rows(doc)[3]["offense"], "mp")   # the first stat but the pool stat
      self.assertFalse(panel.add_category("fifth"))   # at most four
      panel.table.item(0, CATEGORY_COLUMN["name"]).setText("body")
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["rules"]["self_hit"]["category"], "body")
      self.assertTrue(all(m.get("category") != "physical" for m in doc.data["moves"]))
      self.assertIsNone(w.project.validate())
      self.close(w)

   def test_hit_categories(self) -> None:
      """!C5: in the move mode the hit types' box turns hit_category_by_type on (a table of every type with the
      compiler's damaging categories, a pick one undo step) and off; the type mode hides it.
      @return None
      """
      from capsule_studio.ui.editors.structure.categories import HIT_COLUMN
      w, panel = self.window("categories")
      doc = w.project.structure
      key = categories.hit_key()
      self.assertFalse(panel.hit_box.isHidden())
      self.assertFalse(panel.hit_box.isChecked())
      self.assertTrue(panel.hit_table.isHidden())
      panel.hit_box.setChecked(True)
      panel._hit_clicked(True)
      self.settle()
      self.assertIn(key, doc.data)
      self.assertFalse(panel.hit_table.isHidden())
      types = [ty["name"] for ty in w.project.battle.data["types"]]
      self.assertEqual([panel.hit_table.item(r, HIT_COLUMN["type"]).text()
                        for r in range(panel.hit_table.rowCount())], types)
      box = panel.hit_boxes["Water"]
      self.assertEqual([box.itemText(i) for i in range(box.count())], ["physical", "elemental"])
      box.setCurrentText("elemental")
      panel._hit_picked("Water")
      self.settle()
      self.assertEqual(doc.data[key]["Water"], "elemental")
      self.assertEqual(w.undo_action.text(), "Undo Hit type category")
      self.assertIsNone(w.project.validate())
      self.assertTrue(panel.set_mode(categories.BY_TYPE))
      self.settle()
      self.assertTrue(panel.hit_box.isHidden())
      self.assertNotIn(key, doc.data)
      self.assertTrue(panel.set_mode(categories.BY_MOVE))
      self.settle()
      self.assertTrue(panel.set_hit(True))
      self.assertTrue(panel.set_hit(False))
      self.settle()
      self.assertNotIn(key, doc.data)
      self.assertTrue(panel.hit_table.isHidden())
      self.close(w)

   def test_category_by_type(self) -> None:
      """!The mode combo switches to category_by_type (E11): the by-type table shows every type with the compiler's
      damaging categories; a pick is one undo step; back to moves; saves.
      @return None
      """
      from capsule_studio.ui.editors.structure.categories import TYPE_COLUMN
      w, panel = self.window("categories")
      doc = w.project.structure
      self.assertEqual([panel.mode_box.itemData(i) for i in range(panel.mode_box.count())],
                       [categories.BY_MOVE, categories.BY_TYPE])
      self.assertTrue(panel.type_table.isHidden())
      panel.mode_box.setCurrentIndex(panel.mode_box.findData(categories.BY_TYPE))
      panel._mode_picked()
      self.settle()
      self.assertEqual(categories.mode(doc), categories.BY_TYPE)
      self.assertFalse(panel.type_table.isHidden())
      types = [t["name"] for t in w.project.battle.data["types"]]
      self.assertEqual([panel.type_table.item(r, TYPE_COLUMN["type"]).text()
                        for r in range(panel.type_table.rowCount())], types)
      box = panel.type_boxes["Water"]
      self.assertEqual([box.itemText(i) for i in range(box.count())], ["physical", "elemental"])
      box.setCurrentText("elemental")
      panel._type_picked("Water")
      self.settle()
      self.assertEqual(doc.data[categories.BY_TYPE_KEY]["Water"], "elemental")
      self.assertEqual(w.undo_action.text(), "Undo Type category")
      self.assertIsNone(w.project.validate())
      self.assertTrue(w.save_all())
      self.assertEqual(self.saved()["category_by_type"]["Water"], "elemental")
      self.assertTrue(panel.set_mode(categories.BY_MOVE))
      self.settle()
      self.assertTrue(panel.type_table.isHidden())
      self.assertNotIn(categories.BY_TYPE_KEY, doc.data)
      self.close(w)

   def test_passives_items(self) -> None:
      """!Announce, a point handler (point and code), the uses and the Logic... button.
      @return None
      """
      w, panel = self.window("passives_items")
      doc = w.project.battle
      tab = panel.tab("items")
      panel.tabs.setCurrentWidget(tab)
      self.select(tab, "Mana Drop")
      self.assertTrue(tab.announce.isChecked())
      tab.announce.click()
      self.settle()
      self.assertIs(doc.data["items"][0]["announce"], False)
      self.assertTrue(tab.handlers.add_handler("damage"))
      self.settle()
      self.assertEqual(holders.handlers(doc, "items", "Mana Drop"), [{"point": "damage", "code": holders.NEW_CODE}])
      tab.handlers.table.item(0, 1).setText("{ modify by 2; }")
      self.settle()
      self.assertEqual(holders.handlers(doc, "items", "Mana Drop")[0]["code"], "{ modify by 2; }")
      self.assertIsNone(w.project.validate())
      self.assertIn("effects/items.ceffect", tab.used_by.text())
      self.assertTrue(tab.open_logic())
      self.settle()
      self.assertEqual(w.active_panel().owner, ("item", "Mana Drop"))
      self.close(w)


class LayoutAndRefusalTests(QtBattleTestCase):
   """!The tiers table at 900 px and refused edits headless."""

   def test_tiers_table_fits(self) -> None:
      """!Every tier row shows without scrolling in a 1400 x 900 window.
      @return None
      """
      w, panel = self.window("chart")
      w.resize(CHECK_WIDTH, CHECK_HEIGHT)
      w.show()
      self.settle()
      t = panel.tiers
      last = t.visualRect(t.model().index(t.rowCount() - 1, 0))
      self.assertLessEqual(last.bottom(), t.viewport().height())
      self.close(w)

   def test_refusal_is_not_modal(self) -> None:
      """!run_edit() keeps the refusal, shows it in the status bar and opens no box headless.
      @return None
      """
      w, _panel = self.window("conditions")

      def refuse() -> None:
         """!An edit the core refuses."""
         raise DocumentError("no such thing")

      with mock.patch.object(QtWidgets.QMessageBox, "warning") as box:
         self.assertFalse(w.run_edit("Try", refuse, w.project.battle))
      box.assert_not_called()
      self.assertEqual(w.edit_error, ("Try", "no such thing"))
      self.assertIn("no such thing", w.statusBar().currentMessage())
      self.assertTrue(w.run_edit("Fine", lambda: None, w.project.battle))
      self.assertIsNone(w.edit_error)
      self.close(w)


if __name__ == "__main__":
   import unittest
   unittest.main()
