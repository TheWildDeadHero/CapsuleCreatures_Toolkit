#!/usr/bin/env python3
"""!Smoke tests of the S6a panels: Structure > Stages and Structure > Tiers &
Chart of the battle editor, and the Types page's grid drawn from the tiers.
Each opens a copy of the Starter sample laid out as a game, edits through
the widgets (one undo step per edit, renames grouped with their effect
source edits), undoes and saves. Skipped when PySide6 is missing; uses Qt's
offscreen platform.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.structure import chart, stages  # noqa: E402
from test_qt_battle import QtBattleTestCase, QtWidgets  # noqa: E402

## Where a refused edit is reported (BattleWindow.run_edit(): no modal box headless).
REFUSAL = "capsule_studio.ui.battle_shell.report_failure"
## The line of Mist Veil's logic that names the evasion stage.
MIST_VEIL_EVASION = "      stage user evasion 1;\n"


def no_evasion_logic(battle_json: Path) -> None:
   """!Drops the one line of the Starter's logic that names the evasion stage (so the stage may go).
   @param battle_json  the game copy's battle.json
   @return None
   """
   moves = battle_json.parent / "effects" / "moves.ceffect"
   moves.write_text(moves.read_text(encoding="utf-8").replace(MIST_VEIL_EVASION, ""), encoding="utf-8")


## Power-of-two factors given to the sample's scaling tiers (x0.5, x2) before the exponent mode.
POWER_OF_TWO_Q8 = {"weak": 128, "strong": 512}
## Percent of x1 (the entries' result column).
PERCENT = 100


def tiered_chart(battle_json: Path) -> None:
   """!Gives the Starter copy's chart a tier of each kind for the chart page's tests (saved): quarter (x0.25) and
   quad (x4) around its weak / normal / strong (made x0.5 / x2: the exponent mode takes powers of two only), a
   decisive ko tier last, in the exponent mode.
   @param battle_json  the game copy's battle.json
   @return None
   """
   p = BattleProject.open(battle_json)
   doc = p.structure
   with doc.edit("Tiers"):
      for name, q8 in POWER_OF_TWO_Q8.items():
         chart.set_tier(doc, name, "q8", q8)
      chart.add_tier(doc, "quarter", 64, index=1)
      chart.add_tier(doc, "quad", 1024)
      chart.add_tier(doc, "ko", decisive="ko")
      chart.set_option(doc, "combine", "exponent")
   p.save_all()


class StagesPanelTests(QtBattleTestCase):
   """!The Stages page."""

   def cell(self, panel: object, row: int, key: str) -> object:
      """!A stages table item.
      @param panel  StagesPanel
      @param row    table row
      @param key    column key (STAGE_COLUMNS)
      @return QTableWidgetItem
      """
      from capsule_studio.ui.editors.structure.stages import STAGE_COLUMN
      return panel.table.item(row, STAGE_COLUMN[key])

   def test_open(self) -> None:
      """!The sample's stages, the budget, and the selected stage's entries with the engine's results.
      @return None
      """
      from capsule_studio.ui.editors.structure.stages import ENTRY_RESULT_COLUMN, ENTRY_VALUE_COLUMN
      w, panel = self.window("stages")
      self.assertIs(w.document, w.project.structure)   # a structure page edits structure.json
      names = ["accuracy", "evasion", "critical", "attack", "magic", "defence", "protection", "intelligence", "agility"]
      self.assertEqual(panel.table.rowCount(), len(names))
      self.assertEqual([self.cell(panel, r, "name").text() for r in range(len(names))], names)
      self.assertEqual(self.cell(panel, 3, "label").text(), "Attack")
      self.assertEqual(panel.row_widgets[3]["stat"].currentText(), "attack")
      self.assertEqual((panel.row_widgets[2]["lo"].value(), panel.row_widgets[2]["hi"].value()), (0, 3))
      self.assertEqual(panel.row_widgets[1]["mode"].currentText(), "none")
      crit_modes = panel.row_widgets[2]["mode"]
      self.assertNotIn("formula", [crit_modes.itemText(i) for i in range(crit_modes.count())])
      self.assertIn("9/12 GBA", panel.budget.text())
      panel.table.selectRow(3)
      self.settle()
      self.assertEqual(panel.selected, "attack")
      table = stages.stat_stage(w.project.battle, "attack")["table"]   # the sample's own
      self.assertEqual(panel.entries.rowCount(), len(table))
      self.assertEqual(panel.entries.item(0, ENTRY_VALUE_COLUMN).text(), f"{table[0][0]}/{table[0][1]}")
      self.assertEqual(panel.entries.item(0, ENTRY_RESULT_COLUMN).text(), str(table[0][0] * PERCENT // table[0][1]))
      last = len(table) - 1
      self.assertEqual(panel.entries.item(last, ENTRY_RESULT_COLUMN).text(),
                       str(table[-1][0] * PERCENT // table[-1][1]))
      self.close(w)

   def test_edit_undo_save(self) -> None:
      """!Label, entry, mode, range, rename (with its logic), add / move / remove: one undo step each; saves.
      @return None
      """
      from capsule_studio.ui.editors.structure.stages import ENTRY_VALUE_COLUMN
      no_evasion_logic(self.battle_json)
      w, panel = self.window("stages")
      doc = w.project.battle
      self.cell(panel, 1, "label").setText("dodging")
      self.settle()
      self.assertEqual(stages.stage_entry(doc, "evasion")["label"], "dodging")
      self.assertEqual(w.undo_action.text(), "Undo Stage label")
      # Typing an entry gives the evasion stage a table.
      panel.table.selectRow(1)
      self.settle()
      stage_one = 1 - stages.stage_entry(doc, "evasion")["range"][0]   # the entry row of stage 1
      panel.entries.item(stage_one, ENTRY_VALUE_COLUMN).setText("4/3")
      self.settle()
      self.assertEqual(stages.stage_entry(doc, "evasion")["table"][stage_one], [4, 3])
      self.assertEqual(w.undo_action.text(), "Undo Stage table")
      box = panel.row_widgets[1]["mode"]
      box.setCurrentText("none")
      box.activated.emit(box.currentIndex())
      self.settle()
      self.assertNotIn("table", stages.stage_entry(doc, "evasion"))
      odds = list(stages.stage_entry(doc, "critical")["table"])   # the sample's own
      hi = panel.row_widgets[2]["hi"]
      hi.setValue(2)
      self.settle()
      self.assertEqual(stages.stage_entry(doc, "critical")["table"], odds[:3])
      w.undo()
      self.settle()
      self.assertEqual(len(stages.stage_entry(doc, "critical")["table"]), 4)
      # A rename follows the effect logic in the same undo step.
      source = w.project.effect_source("effects/moves.ceffect")
      self.cell(panel, 3, "name").setText("might")
      self.settle()
      self.assertIn("stage target might -1;", source.text)
      self.assertEqual(panel.selected, "might")
      w.undo()
      self.settle()
      self.assertIn("stage target attack -1;", source.text)
      self.assertNotIn("name", stages.stat_stage(doc, "attack"))
      # Remove is refused while logic names the stage (no modal box in the test).
      panel.selected = "attack"
      with mock.patch(REFUSAL) as warned:
         self.assertFalse(panel.remove_stage())
      warned.assert_called_once()
      panel.selected = "evasion"
      self.assertTrue(panel.remove_stage())
      self.settle()
      self.assertTrue(panel.add_stage("evasion", name="dodge"))
      self.settle()
      self.assertEqual(stages.stage_names(doc)[1], "dodge")
      self.assertTrue(panel.move_stage(1))
      self.settle()
      self.assertEqual(stages.stage_names(doc)[2], "dodge")
      self.assertIsNone(w.project.validate())
      self.assertTrue(w.save_all())
      saved = self.saved()
      self.assertEqual(saved["stages"][1]["name"], "critical")   # evasion (labelled "dodging") was removed
      self.assertEqual(saved["stages"][2], {"name": "dodge", "kind": "evasion", "range": [-6, 6]})
      self.assertIsNone(BattleProject.open(self.battle_json).validate())
      self.close(w)

   def test_add_asks(self) -> None:
      """!Add asks for the kind and the stat (only stats without a stage are offered).
      @return None
      """
      w, panel = self.window("stages")
      doc = w.project.battle
      with doc.edit("Free magic"):
         stages.remove_stage(doc, "magic")
      self.settle()
      offered = []

      def get_item(_parent: object, _title: str, label: str, items: list, *_args: object) -> tuple[str, bool]:
         """!Answers the dialogs: kind stat, then the first stat offered."""
         offered.append(list(items))
         return (items[0], True) if label == "Stat:" else ("stat", True)

      with mock.patch.object(QtWidgets.QInputDialog, "getItem", side_effect=get_item):
         self.assertTrue(panel.add_stage())
      self.settle()
      self.assertEqual(offered[1], ["mp", "ep", "magic"])   # the stats without a stage (the pools MP and EP)
      self.assertIsNotNone(stages.stat_stage(doc, "mp"))
      self.close(w)


class TiersChartPanelTests(QtBattleTestCase):
   """!The Tiers & Chart page and the Types page's grid."""

   def cell(self, panel: object, row: int, key: str) -> object:
      """!A tiers table item.
      @param panel  TiersChartPanel
      @param row    table row
      @param key    column key (TIER_COLUMNS)
      @return QTableWidgetItem
      """
      from capsule_studio.ui.editors.structure.chart import TIER_COLUMN
      return panel.tiers.item(row, TIER_COLUMN[key])

   def test_open(self) -> None:
      """!The sample's tiers, settings and grid (shaded from the tiers; the default tier blank).
      @return None
      """
      tiered_chart(self.battle_json)
      w, panel = self.window("chart")
      self.assertEqual(panel.tab_title(), "Tiers & Chart")
      self.assertEqual(panel.tiers.rowCount(), 7)
      self.assertEqual(self.cell(panel, 2, "name").text(), "weak")
      self.assertEqual(self.cell(panel, 2, "factor").text(), "x0.5")
      self.assertEqual(self.cell(panel, 2, "exponent").text(), "-1")
      self.assertEqual(self.cell(panel, 3, "default").text(), "yes")
      self.assertEqual(panel.kind_combos[0].currentText(), "zero")
      self.assertEqual(panel.message_combos[0].currentText(), "no_effect")
      self.assertFalse(panel.message_combos[2].isEnabled())
      self.assertEqual(panel.combine.currentText(), "exponent")
      self.assertEqual((panel.types_per_species.value(), panel.added_types.value()), (2, 1))
      self.assertEqual(panel.above.currentText(), "super_effective")
      types = chart.type_names(w.project.battle)
      fire, bio, light = types.index("Fire"), types.index("Bio"), types.index("Light")
      self.assertEqual(panel.grid.item(fire, bio).text(), "stro")
      self.assertEqual(panel.grid.item(fire, light).text(), "")
      self.assertNotEqual(panel.grid.item(fire, bio).background().color().name(), "#000000")
      self.close(w)

   def test_edit_undo_save(self) -> None:
      """!Tier rename (cells follow), kind, q8, shade, settings, painting and stepping cells: one undo step each.
      @return None
      """
      tiered_chart(self.battle_json)
      w, panel = self.window("chart")
      doc = w.project.battle
      types = chart.type_names(doc)
      fire, bio, cosmic = types.index("Fire"), types.index("Bio"), types.index("Cosmic")
      self.cell(panel, 4, "name").setText("double")
      self.settle()
      self.assertEqual(chart.matchup(doc, "Fire", "Bio"), "double")
      self.assertEqual(w.undo_action.text(), "Undo Rename tier")
      self.cell(panel, 6, "shade").setText("#ff8800")
      self.settle()
      self.assertEqual(chart.tier_list(doc)[6]["shade"], "#ff8800")
      box = panel.kind_combos[6]
      box.setCurrentText("scale")
      box.activated.emit(box.currentIndex())
      self.settle()
      self.assertEqual(chart.tier_list(doc)[6]["kind"], "scale")
      w.undo()
      self.settle()
      self.assertEqual(chart.tier_list(doc)[6]["kind"], "ko")
      # A factor the exponent mode can't take: the compiler says so; multiply takes it.
      self.cell(panel, 5, "q8").setText("768")
      self.settle()
      self.assertEqual(chart.tier_entry(doc, "quad")["q8"], 768)
      self.assertIn("power of two", panel.errors.text())
      panel.combine.setCurrentText("multiply")
      panel.combine.activated.emit(panel.combine.currentIndex())
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["chart"]["combine"], "multiply")
      self.assertIn("Compiles", panel.errors.text())
      w.undo()
      w.undo()
      self.settle()
      # Paint a cell with the picked tier, step another.
      panel.brush.setCurrentText("none")
      self.assertTrue(panel.paint_cell(cosmic, bio))
      self.settle()
      self.assertEqual(chart.matchup(doc, "Cosmic", "Bio"), "none")
      self.assertEqual(w.undo_action.text(), "Undo Type chart")
      self.assertTrue(panel.step_cell(fire, bio))
      self.settle()
      self.assertEqual(chart.matchup(doc, "Fire", "Bio"), "quad")
      # 3 + 1 added is over the engine's most: refused (the box says why), the value stays.
      with mock.patch(REFUSAL) as warned:
         panel.types_per_species.setValue(3)
         self.settle()
      warned.assert_called_once()
      self.assertEqual(chart.options(doc)["types_per_species"], 2)
      self.assertEqual(panel.types_per_species.value(), 2)
      panel.added_types.setValue(0)
      self.settle()
      panel.types_per_species.setValue(3)
      self.settle()
      self.assertEqual(chart.options(doc)["types_per_species"], 3)
      self.assertIsNone(w.project.validate())
      # Removing a used tier asks which tier its cells take.
      panel.selected = "none"
      with mock.patch.object(QtWidgets.QInputDialog, "getItem", return_value=("weak", True)):
         self.assertTrue(panel.remove_tier())
      self.settle()
      self.assertEqual(chart.matchup(doc, "Cosmic", "Bio"), "weak")
      self.assertIsNone(w.project.validate())
      self.assertTrue(w.save_all())
      saved = self.saved()["chart"]
      self.assertEqual([t["name"] for t in saved["tiers"]], ["quarter", "weak", "normal", "double", "quad", "ko"])
      self.assertEqual(saved["tiers"][5]["editor"], {"shade": "#ff8800"})
      self.assertEqual(saved["matchups"]["Fire"]["Bio"], "quad")
      self.assertIsNone(BattleProject.open(self.battle_json).validate())
      self.close(w)

   def test_types_page_steps_tiers(self) -> None:
      """!The Types page draws its grid from the tiers and steps cells through them.
      @return None
      """
      tiered_chart(self.battle_json)
      w, panel = self.window("types")
      doc = w.project.battle
      types = chart.type_names(doc)
      fire, bio = types.index("Fire"), types.index("Bio")
      self.assertEqual(panel.chart.item(fire, bio).text(), "stro")
      panel.step_cell(fire, bio, 1)
      self.settle()
      self.assertEqual(chart.matchup(doc, "Fire", "Bio"), "quad")
      panel.step_cell(fire, bio, -1)
      panel.step_cell(fire, bio, -1)
      self.settle()
      self.assertEqual(chart.matchup(doc, "Fire", "Bio"), "normal")
      self.assertNotIn("Bio", battle.structure_doc(doc).data["chart"]["matchups"]["Fire"])
      self.close(w)

   def test_species_types_follow_the_chart(self) -> None:
      """!The Species page builds as many type boxes as the chart's types per species (S11: no fixed count).
      @return None
      """
      w, panel = self.window("species")
      doc = w.project.battle
      self.assertEqual(len(panel.types), chart.types_per_species(doc))   # the Starter's two
      with doc.edit("Three"):
         chart.set_option(doc, "added_types", 0)
         chart.set_option(doc, "types_per_species", 3)
      w.changed()
      self.settle()
      self.assertEqual(len(panel.types), 3)
      self.select(panel, "Starmote")   # Cosmic and Light
      panel.types[2].setCurrentText("Wind")
      panel.types[2].activated.emit(panel.types[2].currentIndex())
      self.settle()
      self.assertEqual(battle.entry(doc, "species", "Starmote")["types"], ["Cosmic", "Light", "Wind"])
      self.assertIsNone(w.project.validate())
      self.close(w)


if __name__ == "__main__":
   import unittest
   unittest.main()
