#!/usr/bin/env python3
"""!Tests of the Record panel (Structure > Record, S5a): the role table with
greyed engine roles, cell edits and drag order as single undo steps, the
custom role form, party size and move slots (and the Parties page's move
combos following them), the budget bars per target and the layout hash
warning. Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle  # noqa: E402
from capsule_studio.core.structure import record  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402
from test_structure_record import roles_of  # noqa: E402
from test_structure_stats import write_project  # noqa: E402

try:
   from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:   # QtBattleTestCase skips the tests
   QtCore = QtGui = QtWidgets = None

## Where a refused edit is reported (BattleWindow.run_edit(): no modal box headless).
REFUSAL = "capsule_studio.ui.battle_shell.report_failure"


class RecordPanelTests(QtBattleTestCase):
   """!The Record panel."""

   def cell(self, panel: object, role: str, key: str) -> object:
      """!A role table cell.
      @param panel  RecordPanel
      @param role   role name
      @param key    column key
      @return QTableWidgetItem
      """
      from capsule_studio.ui.editors.structure.record import ROLE_COLUMN
      names = [r["name"] for r in panel._rows]
      return panel.table.item(names.index(role), ROLE_COLUMN[key])

   def test_table_budget_and_hash(self) -> None:
      """!Engine roles greyed with fixed IDs; the budget bar per target; the hash warning until saved.
      @return None
      """
      from capsule_studio.ui.editors.structure.record import ENGINE_COLOR
      w, panel = self.window("record")
      self.assertIs(w.document, w.project.structure)   # a structure page edits structure.json
      self.assertEqual(self.cell(panel, "species_key", "id").text(), "0x00")
      self.assertEqual(self.cell(panel, "current_ep", "id").text(), "0x81")   # the Starter's EP pool (D-25)
      self.assertEqual(self.cell(panel, "level", "id").foreground().color().name(), ENGINE_COLOR)
      editable = QtCore.Qt.ItemFlag.ItemIsEditable
      self.assertFalse(self.cell(panel, "species_key", "width").flags() & editable)
      self.assertTrue(self.cell(panel, "stat_genes", "width").flags() & editable)
      self.assertFalse(self.cell(panel, "moves", "count").flags() & editable)
      self.assertTrue(self.cell(panel, "current_ep", "name").flags() & editable)
      self.assertEqual(self.cell(panel, "stat_genes", "count_rule").text(), "stats")
      self.assertTrue(self.cell(panel, "current_ep", "transfer").text().startswith("role:current_ep 0x"))
      self.assertEqual(self.cell(panel, "level", "transfer").text(), record.TRANSFER_BY_ID)
      size = w.project.compile()[0]["layout"]["bytes"]
      self.assertEqual([b.format() for b in panel.budget_bars], [f"{size}/100 B GBA"])
      self.assertFalse(panel.budget_bars[0].property("over"))
      self.assertIn(record.hash_text(w.project.compile()[0]["layout"]["hash"]), panel.hash_label.text())
      self.assertTrue(panel.hash_warning.isHidden())
      self.assertEqual((panel.party_size.maximum(), panel.move_slots.maximum()), (6, 8))

      # a custom role over the GBA's budget: the bar turns red, the hash differs from the saved file's
      panel.c_name.setText("ribbons")
      panel.c_width.setValue(8)
      panel.c_count.setValue(48)
      self.assertTrue(panel.add_custom_from_form())
      self.settle()
      self.assertEqual(panel.selected, "ribbons")
      self.assertTrue(panel.budget_bars[0].property("over"))
      self.assertIn("gba: the record needs", panel.problems.text())
      self.assertFalse(panel.hash_warning.isHidden())
      self.assertIn("old saves won't load", panel.hash_warning.text())
      w.undo()
      self.settle()
      self.assertFalse(panel.budget_bars[0].property("over"))
      self.assertTrue(panel.hash_warning.isHidden())

      # two targets: two bars; the desktop's limit is larger
      write_project(self.root, ["gba", "desktop"])
      w.changed()
      self.settle()
      self.assertEqual([b.format() for b in panel.budget_bars], [f"{size}/100 B GBA", f"{size}/256 B DESKTOP"])
      self.close(w)

   def test_cell_edits_and_form(self) -> None:
      """!A width typed in and a custom role added, renamed and reshaped are one undo step each; a refused edit
      shows the stored values again.
      @return None
      """
      w, panel = self.window("record")
      doc = w.project.battle
      self.cell(panel, "stat_genes", "width").setText("3")
      self.settle()
      self.assertIn({"role": "stat_genes", "width": 3}, roles_of(doc))
      self.assertEqual(self.cell(panel, "stat_genes", "bits").text(), str(3 * len(battle.stat_keys(doc))))
      w.undo()
      self.settle()
      self.assertIn({"role": "stat_genes", "width": 4}, roles_of(doc))   # the Starter's
      with mock.patch(REFUSAL) as warned:
         self.cell(panel, "level", "width").setText("9")
         self.settle()
      warned.assert_called_once()
      self.assertEqual(self.cell(panel, "level", "width").text(), "8")
      panel.selected = "current_mp"
      panel.c_name.setText("gender")
      panel.c_width.setValue(2)
      panel.c_count.setValue(1)
      panel.c_default.setText("1")
      self.assertTrue(panel.add_custom_from_form())
      self.settle()
      names = record.role_names(doc)
      self.assertEqual(names.index("gender"), names.index("current_mp") + 1)
      self.assertEqual(self.cell(panel, "gender", "id").text(), "0x81")
      self.assertTrue(panel.c_apply.isEnabled())
      panel.c_name.setText("sex")
      panel.c_count.setValue(2)
      panel.c_default.setText("0x3")
      self.assertTrue(panel.apply_form())
      self.settle()
      entry = roles_of(doc)[names.index("gender")]
      self.assertEqual(entry, {"custom": "sex", "width": 2, "count": 2, "default": 3})
      w.undo()   # rename + count + default: one step
      self.settle()
      self.assertEqual(roles_of(doc)[names.index("gender")],
                       {"custom": "gender", "width": 2, "default": 1})
      self.cell(panel, "gender", "default").setText("2")
      self.settle()
      self.assertEqual(roles_of(doc)[names.index("gender")]["default"], 2)
      self.cell(panel, "gender", "name").setText("bond")
      self.settle()
      self.assertIn("bond", record.role_names(doc))
      self.assertIsNone(w.project.validate())
      self.close(w)

   def test_drag_order_and_buttons(self) -> None:
      """!Dropping a row on another moves the role there (one undo step); Up / Down; engine roles add and remove;
      required roles stay.
      @return None
      """
      w, panel = self.window("record")
      doc = w.project.battle
      start = record.role_names(doc)
      src = start.index("current_ep")
      panel.table.setCurrentCell(src, 0)
      y = panel.table.visualRect(panel.table.model().index(0, 0)).center().y()
      mime = QtCore.QMimeData()
      event = QtGui.QDropEvent(QtCore.QPointF(panel.table.viewport().width() / 2, y),
                               QtCore.Qt.DropAction.MoveAction, mime, QtCore.Qt.MouseButton.LeftButton,
                               QtCore.Qt.KeyboardModifier.NoModifier)
      panel.table.dropEvent(event)
      self.settle()
      self.assertEqual(record.role_names(doc)[0], "current_ep")
      self.assertEqual(self.cell(panel, "current_ep", "id").text(), "0x80")
      self.assertEqual(panel.selected, "current_ep")
      w.undo()
      self.settle()
      self.assertEqual(record.role_names(doc), start)
      panel.selected = "current_mp"
      self.assertTrue(panel.move_role(-1))
      self.settle()
      self.assertEqual(record.role_names(doc).index("current_mp"), start.index("current_mp") - 1)
      panel.selected = "trait"
      panel.engine_choice.setCurrentText("stat_awaken")
      self.assertTrue(panel.add_engine_role())
      self.settle()
      names = record.role_names(doc)
      self.assertEqual(names.index("stat_awaken"), names.index("trait") + 1)
      self.assertNotIn("stat_awaken", [panel.engine_choice.itemText(i) for i in range(panel.engine_choice.count())])
      self.assertTrue(panel.remove_role())
      self.settle()
      self.assertNotIn("stat_awaken", record.role_names(doc))
      panel.selected = "level"
      with mock.patch(REFUSAL) as warned:
         self.assertFalse(panel.remove_role())
      warned.assert_called_once()
      self.assertIn("level", record.role_names(doc))
      self.close(w)

   def test_move_slots_and_parties(self) -> None:
      """!Move slots and party size are written in the layout's object form; the Parties page shows one move
      combo per slot.
      @return None
      """
      data = json.loads(self.battle_json.read_text(encoding="utf-8"))   # Duo's Emberkit names six moves, not eight
      emberkit = next(t for t in data["parties"] if t["name"] == "Duo Ash & Bly")["members"][2]
      emberkit["moves"] = emberkit["moves"][:6]
      self.battle_json.write_text(json.dumps(data), encoding="utf-8")
      w, panel = self.window("record")
      doc = w.project.battle
      panel.move_slots.setValue(6)
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["monster_layout"]["move_slots"], 6)
      self.assertEqual(self.cell(panel, "moves", "count").text(), "6")
      parties = w.show_panel("parties")
      self.settle()
      self.select(parties, "Duo Ash & Bly")
      parties.members.setCurrentRow(2)
      self.settle()
      self.assertEqual(len(parties.m_moves), 6)
      self.assertEqual([c.currentText() for c in parties.m_moves][:4],
                       ["Flare Claw", "Smolder", "Fireball", "Gale Kick"])
      parties.m_moves[5].setCurrentText("Strike")
      parties.m_moves[5].activated.emit(parties.m_moves[5].currentIndex())   # the user's choice
      self.settle()
      self.assertEqual(doc.data["parties"][2]["members"][2]["moves"][5], "Strike")
      self.assertIsNone(w.project.validate())
      w.undo()
      self.settle()
      w.show_panel("record")
      w.undo()
      self.settle()
      self.assertEqual(record.move_slots(doc), 8)
      # the Starter's object form (E7)
      self.assertEqual(battle.structure_doc(doc).data["monster_layout"]["move_slots"], 8)
      w.show_panel("parties")
      self.settle()
      self.assertEqual(len(parties.m_moves), 8)
      record_panel = w.show_panel("record")
      self.settle()
      with mock.patch(REFUSAL) as warned:
         record_panel.move_slots.setValue(5)   # Duo's Emberkit names six moves
         self.settle()
      warned.assert_called_once()
      self.assertEqual(record_panel.move_slots.value(), 8)
      self.assertEqual(record.move_slots(doc), 8)
      self.close(w)


class GameUsePanelTests(QtBattleTestCase):
   """!The battle window against the game: the status bar follows each compile, the genes and training spins
   follow the layout's widths, and removing or renaming a role field scripts use asks first."""

   def test_status_bar_follows_compile(self) -> None:
      """!The status bar says the data compiles until an edit breaks it, and again after Undo.
      @return None
      """
      from capsule_studio.ui.battle_shell import COMPILES_TEXT
      w, _panel = self.window("record")
      doc = w.project.structure   # the Record page's file
      self.assertEqual(w.compile_status.text(), COMPILES_TEXT)
      self.assertTrue(w.run_edit("Break", lambda: doc.data["growth"].__setitem__("Nonesuch", "n*"), doc))
      self.settle()
      self.assertTrue(w.compile_status.text().startswith("compile error: gba: "), w.compile_status.text())
      self.assertIn("Nonesuch", w.compile_status.toolTip())
      w.undo()
      self.settle()
      self.assertEqual(w.compile_status.text(), COMPILES_TEXT)
      self.close(w)

   def test_genes_and_training_follow_widths(self) -> None:
      """!The Species preview, the Parties member and the damage calculator take genes up to the stat_genes
      width's maximum (the Starter keeps no training: its spin stays at the engine's default).
      @return None
      """
      starter_bits, genes_bits = 4, 3
      w, panel = self.window("record")
      species, parties, calc = (w.show_panel(i) for i in ("species", "parties", "pipelines"))
      self.settle()
      default = (1 << starter_bits) - 1
      self.assertLess(starter_bits, engine_width("stat_genes"))   # the Starter narrows the registry's width
      spins = (species.preview_inputs["gene"], parties.m_genes, calc.genes)
      self.assertEqual([s.maximum() for s in spins], [default] * 3)
      # G4: the Starter's layout holds stat_training (6 bits): the preview's training spin follows its width
      self.assertEqual(species.preview_inputs["training"].maximum(), record.stat_inputs(w.project.battle)["training"])
      w.show_panel("record")
      self.assertTrue(panel.set_role("stat_genes", record.WIDTH_KEY, genes_bits))
      self.settle()
      for page in (species, parties, calc):
         w.show_panel(page)
         self.settle()
      genes_max = (1 << genes_bits) - 1
      self.assertEqual(record.gene_max(w.project.battle), genes_max)
      self.assertEqual([s.maximum() for s in (species.preview_inputs["gene"], parties.m_genes, calc.genes)],
                       [genes_max] * 3)
      self.close(w)

   def test_role_used_by_field_scripts_asks(self) -> None:
      """!Removing or renaming a role a field script uses asks first; No leaves it, Yes goes ahead.
      @return None
      """
      project = self.root / "reference" / "project.json"
      manifest = json.loads(project.read_text(encoding="utf-8"))
      manifest["scripts"] = "data/scripts/scripts.json"
      project.write_text(json.dumps(manifest), encoding="utf-8")
      (self.root / "data" / "scripts").mkdir()
      (self.root / "data" / "scripts" / "field.cscript").write_text(
         "script s {\n    role_set(0, current_mp, 1);\n}\n", encoding="utf-8")
      (self.root / "data" / "scripts" / "scripts.json").write_text(json.dumps({
         "schema": "capsule.scripts/1", "sources": ["field.cscript"],
         "placeholders": {"pal": {"record": "current_ep", "slot": 0}}}), encoding="utf-8")
      w, panel = self.window("record")
      doc = w.project.battle
      buttons = QtWidgets.QMessageBox.StandardButton
      panel.selected = "current_mp"
      with mock.patch.object(QtWidgets.QMessageBox, "question") as asked:   # headless: No, no box (S14 F7)
         self.assertFalse(panel.remove_role())
      asked.assert_not_called()
      # On a screen the question box asks (the page's ask() as widgets.ask() does it there).
      on_screen = mock.patch("capsule_studio.ui.editors.structure.record.ask",
                             side_effect=lambda win, title, text, *_a: QtWidgets.QMessageBox.question(win, title, text))
      on_screen.start()
      self.addCleanup(on_screen.stop)
      with mock.patch.object(QtWidgets.QMessageBox, "question", return_value=buttons.No) as asked:
         self.assertFalse(panel.remove_role())
         self.assertFalse(panel.rename_role("current_ep", "fondness"))
      self.assertEqual(asked.call_count, 2)
      self.assertIn("field.cscript line 2", asked.call_args_list[0].args[2])
      self.assertIn("placeholder {pal}", asked.call_args_list[1].args[2])
      self.assertIn("current_mp", record.role_names(doc))
      self.assertIn("current_ep", record.role_names(doc))
      with mock.patch.object(QtWidgets.QMessageBox, "question", return_value=buttons.Yes):
         self.assertTrue(panel.rename_role("current_ep", "fondness"))   # the ep resource follows
      self.assertIn("fondness", record.role_names(doc))
      self.assertTrue(w.run_edit("Custom", lambda: record.add_custom_role(doc, "secret_code", 16), doc))
      with mock.patch.object(QtWidgets.QMessageBox, "question") as asked:
         self.assertTrue(panel.rename_role("secret_code", "secret"))   # no script uses it: nothing asked
      asked.assert_not_called()
      self.close(w)

   def test_placeholders_removed(self) -> None:
      """!The built pages have no placeholder left behind in the planned modules.
      @return None
      """
      from capsule_studio.ui.editors.logic import planned as logic_planned
      from capsule_studio.ui.editors.structure import planned as structure_planned
      for module, name in ((structure_planned, "RecordPanel"), (structure_planned, "StatsStagesPanel"),
                           (structure_planned, "TypeChartPanel"), (logic_planned, "PipelinesPointsPanel"),
                           (logic_planned, "BenchPanel")):
         self.assertFalse(hasattr(module, name), name)


def engine_width(role: str) -> int:
   """!An engine role's registry width.
   @param role  role name
   @return bits
   """
   from capsule_studio.core import engine
   return engine.tool("battlec.layout").ROLE_SHAPES[role][0]
