#!/usr/bin/env python3
"""!Smoke tests of the S4 panels: Structure > Stats and Logic >
Pipelines & Points of the battle editor. Each opens a copy of the battle
sandbox laid out as a game, edits through the widgets (one undo step per
edit), undoes and saves; the damage calculator must show exactly what
core.pipelines.damage_trace() computes. Skipped when PySide6 is missing;
uses Qt's offscreen platform.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle, pipelines  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.structure import stats  # noqa: E402
from test_qt_battle import QtBattleTestCase, QtCore, QtWidgets  # noqa: E402

## Genes of the calculator's sample line (within the Starter's 4-bit stat_genes).
SAMPLE_GENES = 10
## Training values of the sample line (G4: the Starter's stat_training is 6 bits).
SAMPLE_TRAINING = 30

## Where a refused edit is reported (BattleWindow.run_edit(): no modal box headless).
REFUSAL = "capsule_studio.ui.battle_shell.report_failure"
## Row the steps test drags the first step to (the step lands above it).
DRAG_TO = 3


class StatsPanelTests(QtBattleTestCase):
   """!The Stats page."""

   def cell(self, panel: object, row: int, key: str) -> object:
      """!A stats table item.
      @param panel  StatsPanel
      @param row    table row
      @param key    column key (STAT_COLUMNS)
      @return QTableWidgetItem
      """
      from capsule_studio.ui.editors.structure.stats import STAT_COLUMN
      return panel.table.item(row, STAT_COLUMN[key])

   def test_open(self) -> None:
      """!The stats, their stage flags and the budget of the sample.
      @return None
      """
      from capsule_studio.ui.editors.structure.stats import WITHIN_COLOR
      w, panel = self.window("stats")
      self.assertIs(w.document, w.project.structure)   # a structure page edits structure.json
      names = ["hp", "mp", "ep", "attack", "magic", "defence", "protection", "intelligence", "agility"]
      self.assertEqual(panel.table.rowCount(), len(names))
      self.assertEqual([self.cell(panel, r, "name").text() for r in range(len(names))], names)
      self.assertEqual(self.cell(panel, 0, "pool").checkState(), QtCore.Qt.CheckState.Checked)
      self.assertEqual(self.cell(panel, 0, "stage").checkState(), QtCore.Qt.CheckState.Unchecked)
      self.assertEqual(self.cell(panel, 1, "stage").checkState(), QtCore.Qt.CheckState.Unchecked)   # MP: a pool
      self.assertEqual(self.cell(panel, 8, "order").checkState(), QtCore.Qt.CheckState.Checked)
      self.assertEqual(self.cell(panel, 3, "stage_index").text(), "3")
      self.assertEqual(panel.formula_combos[0].currentText(), "vital")
      self.assertEqual([lb.text() for lb in panel.budget_labels], ["9/10 GBA"])
      self.assertIn(WITHIN_COLOR, panel.budget_labels[0].styleSheet())
      self.close(w)

   def test_edit_undo_save(self) -> None:
      """!Label, flag, formula, rename (transfer pinned), the stage flag: one undo step each; the file saves.
      @return None
      """
      w, panel = self.window("stats")
      doc = w.project.battle
      self.cell(panel, 3, "label").setText("Might")
      self.settle()
      self.assertEqual(stats.stat_entry(doc, "attack")["label"], "Might")
      self.assertEqual(w.undo_action.text(), "Undo Stat label")
      w.undo()
      self.settle()
      self.assertEqual(stats.stat_entry(doc, "attack")["label"], "Attack")
      self.assertEqual(self.cell(panel, 3, "label").text(), "Attack")
      self.cell(panel, 4, "trait").setCheckState(QtCore.Qt.CheckState.Unchecked)
      self.settle()
      self.assertIs(stats.stat_entry(doc, "magic")["trait"], False)
      w.undo()
      self.settle()
      self.assertNotIn("trait", stats.stat_entry(doc, "magic"))
      self.cell(panel, 5, "short").setText("Df")
      self.settle()
      self.assertEqual(stats.stat_list(doc)[5]["short"], "Df")
      # Rename through the name cell: references follow and the old name stays the transfer key.
      self.cell(panel, 3, "name").setText("power")
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["categories"][0]["offense"], "power")
      self.assertEqual(stats.stat_entry(doc, "power")["transfer"], "attack")
      self.assertEqual(self.cell(panel, 3, "transfer").text(), "attack")
      self.assertEqual(panel.selected, "power")
      self.assertIsNone(w.project.validate())
      w.undo()
      self.settle()
      self.assertEqual(stats.stat_names(doc)[3], "attack")
      self.assertNotIn("transfer", stats.stat_entry(doc, "attack"))
      self.assertTrue(panel.rename_stat("might", "attack"))
      self.settle()
      self.assertEqual(stats.stat_entry(doc, "might")["transfer"], "attack")
      # The stage flag takes the stat's stage off "stages" (no logic names magic's stage).
      self.cell(panel, 4, "stage").setCheckState(QtCore.Qt.CheckState.Unchecked)
      self.settle()
      self.assertNotIn("magic", [st.get("stat") for st in battle.structure_doc(doc).data["stages"]])
      self.assertEqual(w.undo_action.text(), "Undo Stat stage")
      self.assertEqual(self.cell(panel, 4, "stage_index").text(), "")
      # The formula combo lists the ruleset's stat formulas.
      box = panel.formula_combos[3]
      self.assertEqual([box.itemText(i) for i in range(box.count())], battle.stat_formulas(w.project.ruleset))
      box.setCurrentText("vital")
      box.activated.emit(box.currentIndex())
      self.settle()
      self.assertEqual(stats.stat_entry(doc, "might")["formula"], "vital")
      w.undo()
      self.settle()
      self.assertIsNone(w.project.validate())
      self.assertTrue(w.save_all())
      saved = self.saved()
      self.assertEqual(saved["stats"][3], {"name": "might", "label": "Attack", "formula": "core",
                                           "transfer": "attack"})
      self.assertEqual(saved["stats"][5]["editor"], {"short": "Df"})
      self.assertNotIn("magic", [st.get("stat") for st in saved["stages"]])
      self.assertIsNone(BattleProject.open(self.battle_json).validate())
      self.close(w)

   def test_add_move_remove(self) -> None:
      """!Add after the selection, move, remove: one undo step each, with every species' base values; the
      pool stat can't be removed.
      @return None
      """
      w, panel = self.window("stats")
      doc = w.project.battle
      before = json.dumps(doc.data, sort_keys=True)
      panel.selected = "defence"
      with mock.patch.object(QtWidgets.QInputDialog, "getText", return_value=("luck", True)):
         self.assertTrue(panel.add_stat())
      self.settle()
      self.assertEqual(stats.stat_names(doc)[6], "luck")
      self.assertEqual(len(doc.data["species"][0]["base"]), 10)
      self.assertEqual(panel.table.rowCount(), 10)
      self.assertEqual([lb.text() for lb in panel.budget_labels], ["10/10 GBA"])
      self.assertEqual(panel.selected, "luck")
      base = [sp["base"][6] for sp in doc.data["species"]]
      self.assertTrue(panel.move_stat(1))
      self.settle()
      self.assertEqual(stats.stat_names(doc)[7], "luck")
      self.assertEqual([sp["base"][7] for sp in doc.data["species"]], base)
      w.undo()
      self.settle()
      self.assertEqual(stats.stat_names(doc)[6], "luck")
      self.assertTrue(panel.remove_stat())
      self.settle()
      self.assertEqual(json.dumps(doc.data, sort_keys=True), before)
      w.undo()
      w.undo()
      self.settle()
      self.assertEqual(json.dumps(doc.data, sort_keys=True), before)
      panel.selected = "hp"
      with mock.patch(REFUSAL) as warned:
         self.assertFalse(panel.remove_stat())
      self.assertTrue(warned.called)
      self.assertEqual(panel.table.rowCount(), 9)
      self.close(w)

   def test_budget_over(self) -> None:
      """!A game for the desktop and the GBA with 14 stats: the GBA budget is red, the desktop's is not.
      @return None
      """
      from capsule_studio.ui.editors.structure.stats import OVER_COLOR, WITHIN_COLOR
      project = self.root / "reference" / "project.json"
      data = json.loads(project.read_text(encoding="utf-8"))
      data["targets"] = ["gba", "desktop"]
      project.write_text(json.dumps(data), encoding="utf-8")
      w, panel = self.window("stats")
      doc = w.project.battle

      def fill() -> None:
         """!Five more stats, allowed by the desktop only."""
         for i in range(5):
            stats.add_stat(doc, f"extra{i}", stage=False, targets=["desktop"])
      self.assertTrue(w.run_edit("Fill", fill, doc))
      self.settle()
      self.assertEqual([lb.text() for lb in panel.budget_labels], ["14/10 GBA", "14/32 DESKTOP"])
      self.assertIn(OVER_COLOR, panel.budget_labels[0].styleSheet())
      self.assertIn(WITHIN_COLOR, panel.budget_labels[1].styleSheet())
      self.assertIn("gba: 14 stats", panel.limit_problems.text())
      with mock.patch(REFUSAL) as warned:
         self.assertFalse(panel.add_stat("one_more"))   # the strictest target is full
      self.assertTrue(warned.called)
      self.close(w)


class PipelinesPanelTests(QtBattleTestCase):
   """!The Pipelines & Points page."""

   def steps(self, w: object, name: str = "damage") -> list:
      """!A pipeline's steps in the ruleset.
      @param w     BattleWindow
      @param name  pipeline
      @return the list
      """
      return w.project.ruleset.data["pipelines"][name]

   def test_steps(self) -> None:
      """!Picker, steps with analysed ranges, editing a step, adding, moving (buttons and drag), removing:
      one ruleset undo step each; the file saves.
      @return None
      """
      w, panel = self.window("pipelines")
      rs = w.project.ruleset
      self.assertIs(w.document, rs)
      self.assertEqual([panel.pipeline.itemText(i) for i in range(panel.pipeline.count())],
                       pipelines.pipeline_names())
      self.assertEqual(panel.step_list.count(), len(self.steps(w)))
      # the sample's own layout: its "let attack" step (ranged) and its "let power = move_power" step
      attack = next(i for i, st in enumerate(self.steps(w)) if st.get("let") == "attack")
      power = next(i for i, st in enumerate(self.steps(w)) if st.get("expr") == "move_power")
      panel.step_list.setCurrentRow(attack)
      self.settle()
      self.assertEqual(panel.step_var.text(), "attack")
      lo, hi = self.steps(w)[attack]["range"]
      self.assertEqual((panel.step_lo.text(), panel.step_hi.text()), (str(lo), str(hi)))
      self.assertIn("before the clamp", panel.step_analysed.text())
      self.assertIn("never engages", panel.step_clamp.text())   # the Starter's stats stay below its STAT_CAP
      a_lo, a_hi = pipelines.pipeline_report(w.project, "damage")[0][attack]["bounds"]
      self.assertIn(f"-> [{a_lo}, {a_hi}]", panel.step_list.item(attack).text())
      # Edit the expression of "let power = move_power".
      panel.step_list.setCurrentRow(power)
      self.settle()
      panel.step_expr.setText("move_power * 2")
      panel.step_expr.editingFinished.emit()
      self.settle()
      self.assertEqual(self.steps(w)[power]["expr"], "move_power * 2")
      p_lo, p_hi = pipelines.pipeline_report(w.project, "damage")[0][power]["bounds"]
      self.assertIn(f"[{p_lo}, {p_hi}]", panel.step_list.item(power).text())
      w.undo()
      self.settle()
      self.assertEqual(self.steps(w)[power]["expr"], "move_power")
      # A clamp: both ends, then none.
      panel.step_lo.setText("1")
      panel.step_hi.setText("90")
      panel.step_hi.editingFinished.emit()
      self.settle()
      self.assertEqual(self.steps(w)[power]["range"], [1, 90])
      panel.step_lo.setText("")
      panel.step_hi.setText("")
      panel.step_hi.editingFinished.emit()
      self.settle()
      self.assertNotIn("range", self.steps(w)[power])
      # Add, move, drag, remove.
      count = len(self.steps(w))
      self.assertTrue(panel.add_step("let"))
      self.settle()
      self.assertEqual(self.steps(w)[power + 1], {"let": "power", "expr": "power"})
      self.assertEqual(panel.selected_step, power + 1)
      self.assertTrue(panel.move_step(-1))
      self.settle()
      self.assertEqual(self.steps(w)[power], {"let": "power", "expr": "power"})
      w.undo()
      self.settle()
      self.assertEqual(self.steps(w)[power + 1], {"let": "power", "expr": "power"})
      first = dict(self.steps(w)[0])
      moved = panel.step_list.model().moveRow(QtCore.QModelIndex(), 0, QtCore.QModelIndex(), DRAG_TO)
      self.assertTrue(moved)
      self.settle()
      self.assertEqual(self.steps(w)[DRAG_TO - 1], first)   # dropped above row DRAG_TO
      self.assertEqual(w.undo_action.text(), "Undo Move step")
      w.undo()
      self.settle()
      self.assertEqual(self.steps(w)[0], first)
      panel.selected_step = power + 1
      self.assertTrue(panel.remove_step())
      self.settle()
      self.assertEqual(len(self.steps(w)), count)
      self.assertTrue(panel.add_step("roll"))
      self.assertTrue(panel.add_step("point"))
      self.settle()
      self.assertEqual(self.steps(w)[panel.selected_step]["point"], pipelines.point_names(rs)[0])
      w.undo()
      w.undo()
      self.settle()
      self.assertEqual(len(self.steps(w)), count)
      self.assertIsNone(w.project.validate())
      # Another pipeline.
      panel.pipeline.setCurrentText("speed")
      self.settle()
      self.assertEqual(panel.step_list.count(), len(self.steps(w, "speed")))
      self.assertTrue(w.save_current())
      saved = json.loads(w.project.ruleset.path.read_text(encoding="utf-8"))
      self.assertNotIn("range", saved["pipelines"]["damage"][power])
      self.assertEqual(saved["pipelines"]["damage"][power]["expr"], "move_power")
      self.close(w)

   def test_points(self) -> None:
      """!The points table: users, holder, sources in order, range; a used point can't be removed.
      @return None
      """
      from capsule_studio.ui.editors.logic.pipelines import (POINT_HI_COLUMN, POINT_NAME_COLUMN,
                                                             POINT_SOURCES_COLUMN, POINT_USERS_COLUMN)
      w, panel = self.window("pipelines")
      rs = w.project.ruleset
      names = [panel.points.item(r, POINT_NAME_COLUMN).text() for r in range(panel.points.rowCount())]
      self.assertEqual(names, pipelines.point_names(rs))
      r = names.index("weather")
      users = pipelines.point_users(rs, "weather", w.project.battle)
      self.assertEqual(panel.points.item(r, POINT_USERS_COLUMN).text(), str(len(users)))
      self.assertGreater(len(users), 0)
      with mock.patch(REFUSAL) as warned:
         self.assertFalse(panel.remove_point("weather"))
      self.assertTrue(warned.called)
      self.assertIn("weather", pipelines.point_names(rs))
      r = names.index("damage")
      panel.points.item(r, POINT_SOURCES_COLUMN).setText("item, status, passive")
      self.settle()
      self.assertEqual(rs.data["points"]["damage"]["sources"], ["item", "status", "passive"])
      w.undo()
      self.settle()
      self.assertEqual(rs.data["points"]["damage"]["sources"], ["status", "passive", "item"])
      panel.points.item(r, POINT_HI_COLUMN).setText("9999")
      self.settle()
      self.assertEqual(rs.data["points"]["damage"]["range"], [0, 9999])
      self.assertTrue(panel.set_point("damage", "holder", "target"))
      self.settle()
      self.assertEqual(panel.holder_combos[r].currentText(), "target")
      with mock.patch.object(QtWidgets.QInputDialog, "getText", return_value=("extra", True)):
         self.assertTrue(panel.add_point())
      self.settle()
      self.assertEqual(panel.points.rowCount(), len(names) + 1)
      panel.points.selectRow(len(names))
      self.assertTrue(panel.remove_point())
      self.settle()
      self.assertEqual(pipelines.point_names(rs), names)
      self.assertTrue(w.save_current())
      saved = json.loads(rs.path.read_text(encoding="utf-8"))
      self.assertEqual(saved["points"]["damage"], {"holder": "target", "sources": ["status", "passive", "item"],
                                                   "range": [0, 9999]})
      self.close(w)

   def test_calculator(self) -> None:
      """!The calculator shows what core.pipelines.damage_trace() computes, step by step; ruleset edits
      show at once.
      @return None
      """
      from capsule_studio.ui.editors.logic.pipelines import TRACE_BEFORE_COLUMN, TRACE_COLUMNS, TRACE_VALUE_COLUMN
      w, panel = self.window("pipelines")
      kw = {"attacker": "Emberkit", "defender": "Sproutle", "move": "Fireball", "level": 5,
            "weather": "Storm", "attacker_trait": "Fierce", "defender_trait": "Sturdy", "passive": "Blaze Heart",
            "genes": SAMPLE_GENES, "training": SAMPLE_TRAINING, "roll": 7, "crit": True}
      for box, text in ((panel.attacker, "Emberkit"), (panel.defender, "Sproutle"), (panel.move, "Fireball"),
                        (panel.weather, "Storm"), (panel.attacker_trait, "Fierce"), (panel.defender_trait, "Sturdy"),
                        (panel.passive, "Blaze Heart")):
         box.setCurrentText(text)
         self.assertEqual(box.currentText(), text)
      panel.level.setValue(5)
      panel.genes.setValue(SAMPLE_GENES)
      panel.training.setValue(SAMPLE_TRAINING)
      panel.roll.setValue(7)
      panel.crit.setChecked(True)
      self.settle()
      want = pipelines.damage_trace(w.project, **kw)
      self.assertEqual(panel.calculator_args(), {**kw, "status": None, "spread": False, "item": None,
                                                 "hp_pct": pipelines.PERCENT, "offense_stage": 0,
                                                 "defense_stage": 0, "defender_level": None,
                                               # S17: no volatiles or side conditions, one battler per side
                                               "attacker_volatiles": [], "defender_volatiles": [],
                                               "attacker_side": [], "defender_side": [],
                                               "defender_active": pipelines.SIDE_ACTIVE})
      self.assertEqual(panel.result.damage, want.damage)
      self.assertEqual(panel.damage.text(), f"Damage {want.damage}")
      self.assertEqual(panel.trace.rowCount(), len(want.trace))
      for r, (_index, _kind, _var, before, value, text) in enumerate(want.trace):
         self.assertEqual(panel.trace.item(r, TRACE_VALUE_COLUMN).text(), str(value))
         self.assertEqual(panel.trace.item(r, TRACE_BEFORE_COLUMN).text(), "" if before is None else str(before))
         self.assertEqual(panel.trace.item(r, len(TRACE_COLUMNS) - 1).text(), text)
      # The same line without a crit and with a spread hit; then a ruleset edit doubles the damage.
      panel.crit.setChecked(False)
      panel.spread.setChecked(True)
      self.settle()
      plain = pipelines.damage_trace(w.project, **{**kw, "crit": False, "spread": True})
      self.assertEqual(panel.result.damage, plain.damage)
      rs = w.project.ruleset
      self.assertTrue(w.run_edit("Double", lambda: pipelines.add_step(
         rs, "damage", pipelines.make_step("let", "damage", "damage * 2", [1, 65535])), rs))
      self.settle()
      self.assertEqual(panel.result.damage, plain.damage * 2)
      # A decisive tier and an unknown choice.
      panel.move.setCurrentText("Arc Bolt")   # Lightning on Earth
      panel.defender.setCurrentText("Clodbun")
      panel.calculate()
      self.assertIn("decisive type tier zero", panel.damage.text())
      self.assertEqual(panel.trace.rowCount(), 0)
      self.close(w)
