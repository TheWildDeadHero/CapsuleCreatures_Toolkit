"""!Smoke tests of the record fields pages (the studio side of the record fields):
Structure > Species fields, the Species page's field spins, the Record page's
Stored box and preview tabs, the Progression page's draw order, species
preview and coloured derived field, the Formulas page's coloured cells and
error row, and the pipeline step's expression field. Each opens a copy of a
sample laid out as a game and edits through the widgets (one undo step per
edit). Skipped when PySide6 is missing; uses Qt's offscreen platform; the
Classic record data set's tests are skipped without the reference repo.
CAPSULE_SHOTS=FOLDER saves pictures of the pages there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle, engine, expressions  # noqa: E402
from capsule_studio.core.structure import progression, record, species_fields  # noqa: E402
from sample_data import make_classic_record_game, needs_classic_record  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## Where CAPSULE_SHOTS names the picture folder.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a saved picture.
SHOT_SIZE = (1300, 860)
## The classic record data set's unstored role, a stored custom role without a generation entry, its wide draw, its
## gender role and field, and a species.
UNSTORED, PLAIN_CUSTOM, WIDE_ROLE, FIELD_ROLE, FIELD, SPECIES = ("shiny", "friendship", "seed", "gender",
                                                                 "gender_ratio", "Mothlet")


def save_shot(window: Any, name: str) -> None:
   """!Saves a picture of a window when CAPSULE_SHOTS names a folder.
   @param window  the window
   @param name    file name
   @return None
   """
   folder = os.environ.get(SHOTS_ENV)
   if folder:
      window.resize(*SHOT_SIZE)
      window.grab().save(str(Path(folder) / name))


class SpeciesFieldsPageTests(QtBattleTestCase):
   """!The Species fields page and the Species page's spins on the Starter."""

   def test_fields_page_and_species_spins(self) -> None:
      """!Add a field from the page, rename and change its width by typing, give a species a value through its spin
      (grey while it follows the default), remove the field; each one undo step.
      @return None
      """
      from capsule_studio.ui.editors.structure.species_fields import FIELD_COLUMN
      w, panel = self.window("species_fields")
      p = w.project
      self.assertIs(w.document, p.structure)
      # the Starter's own fields (recruit_rate, the growth's training yields): the new one goes after them
      given = species_fields.field_names(p.structure)
      self.assertEqual(panel.table.rowCount(), len(given))
      self.assertIn(f"{len(given)}/{species_fields.max_fields()}", panel.count.text())
      self.assertEqual(panel.new_width.maximum(), species_fields.max_width())
      panel.selected = given[-1] if given else None
      self.assertTrue(panel.add_field("bulk", 4, 2))
      self.settle()
      self.assertEqual(species_fields.field_names(p.structure), given + ["bulk"])
      self.assertEqual(w.undo_action.text(), "Undo Add species field")
      row = len(given)
      panel.table.item(row, FIELD_COLUMN["name"]).setText("mass")
      self.settle()
      self.assertEqual(species_fields.field_names(p.structure), given + ["mass"])
      panel.table.item(row, FIELD_COLUMN["width"]).setText("40")   # above the engine's widest: refused
      self.settle()
      self.assertEqual(species_fields.fields(p.structure)[row]["width"], 4)
      species = w.show_panel("species")
      self.settle()
      sp = species.names()[0]
      own = dict(battle.entry(p.battle, "species", sp).get("fields", {}))
      self.select(species, sp)
      box = species.field_spins["mass"]
      self.assertEqual((box.value(), box.maximum()), (2, species_fields.top_of(4)))
      self.assertIn("default", box.toolTip())
      box.setValue(9)
      box.editingFinished.emit()
      self.settle()
      self.assertEqual(battle.entry(p.battle, "species", sp)["fields"], {**own, "mass": 9})
      self.assertEqual(w.undo_action.text(), "Undo Set species field")
      save_shot(w, "species_fields_species_page.png")
      panel = w.show_panel("species_fields")
      self.settle()
      panel.selected = "mass"
      self.assertTrue(panel.remove_field())
      self.settle()
      self.assertEqual(battle.entry(p.battle, "species", sp).get("fields", {}), own)
      species = w.show_panel("species")
      self.settle()
      self.assertEqual(list(species.field_spins), given)
      self.close(w)


class FormulaPageTests(QtBattleTestCase):
   """!The Formulas page's coloured cells and the pipeline step's field on the Starter."""

   def test_cells_errors_and_step_field(self) -> None:
      """!The expression column has the formula delegate; a bit-operator formula compiles; a shift by an input up
      to the level marks its row with the engine's message; the pipeline step's field completes the pipeline's
      inputs and colours bit operators.
      @return None
      """
      from capsule_studio.ui.editors.logic.expression_edit import FormulaDelegate, FormulaEdit
      from capsule_studio.ui.editors.logic.formulas import ERROR_TEXT, EXPR_COLUMN, ANALYSED_COLUMN
      w, panel = self.window("rules")
      p = w.project
      self.assertIsInstance(panel.table.itemDelegateForColumn(EXPR_COLUMN), FormulaDelegate)
      slots = p.formula_slots()
      slot = slots[0]
      inputs = [n for n, _r in p.formula_inputs(slot)]
      row = slots.index(slot)
      editor = panel.delegate.createEditor(panel.table.viewport(), None, panel.table.model().index(row, EXPR_COLUMN))
      self.assertIsInstance(editor, FormulaEdit)
      self.assertIn(inputs[0], editor.model.stringList())
      panel.table.item(row, EXPR_COLUMN).setText(f"({inputs[0]} >> 1) | 1")
      self.settle()
      self.assertIsNone(panel.error_slot)
      panel.table.item(row, EXPR_COLUMN).setText(f"{inputs[0]} << {inputs[0]}")
      self.settle()
      self.assertEqual(panel.error_slot, slot)
      self.assertEqual(panel.table.item(row, ANALYSED_COLUMN).text(), ERROR_TEXT)
      self.assertIn("shift", panel.table.item(row, ANALYSED_COLUMN).toolTip())
      save_shot(w, "formulas_shift_error.png")
      w.undo_action.trigger()
      self.settle()
      self.assertIsNone(panel.error_slot)
      pipes = w.show_panel("pipelines")
      self.settle()
      self.assertIsInstance(pipes.step_expr, FormulaEdit)
      name = pipes.pipeline_name()
      self.assertTrue(set(engine.tool("ruleset_compiler").PIPELINES[name]["inputs"])
                      <= set(expressions.completion_words(expressions.pipeline_names(p, name))))
      pipes.step_expr.set_names(expressions.pipeline_names(p, name))
      pipes.step_expr.setText("a ^ b")
      self.assertIn(("^", expressions.KIND_BIT), pipes.step_expr.kinds())
      self.close(w)


@needs_classic_record
class ClassicRecordPageTests(QtBattleTestCase):
   """!The Record and Progression pages on the reference repo's compat/classic/record data set."""

   def setUp(self) -> None:
      """!Copies the record data set as a game.
      @return None
      """
      super().setUp()
      self.battle_json = make_classic_record_game(self.root / "classic")

   def yes(self) -> Any:
      """!Answers the Record page's questions Yes (widgets.ask() says No without a screen).
      @return a context manager
      """
      from PySide6 import QtWidgets
      return mock.patch("capsule_studio.ui.editors.structure.record.ask",
                        return_value=QtWidgets.QMessageBox.StandardButton.Yes)

   def test_record_stored_box_and_previews(self) -> None:
      """!The Stored box: unticked for the unstored role, refused for a role without a derived or constant entry,
      ticking it stores the role (one undo step); the bits and offset cells say computed on read; the derived and
      transfer previews run.
      @return None
      """
      from PySide6 import QtCore
      from capsule_studio.ui.editors.structure.record import ROLE_COLUMN, UNSTORED_TEXT
      w, panel = self.window("record")
      p = w.project
      names = [r["name"] for r in panel._rows]
      shiny, plain = names.index(UNSTORED), names.index(PLAIN_CUSTOM)
      box = panel.table.item(shiny, ROLE_COLUMN["stored"])
      self.assertEqual(box.checkState(), QtCore.Qt.CheckState.Unchecked)
      self.assertEqual(panel.table.item(shiny, ROLE_COLUMN["bits"]).text(), UNSTORED_TEXT)
      self.assertEqual(panel.table.item(shiny, ROLE_COLUMN["offset"]).text(), UNSTORED_TEXT)
      panel.table.item(plain, ROLE_COLUMN["stored"]).setCheckState(QtCore.Qt.CheckState.Unchecked)
      self.settle()
      self.assertEqual(panel.table.item(plain, ROLE_COLUMN["stored"]).checkState(), QtCore.Qt.CheckState.Checked)
      self.assertTrue(all(r["stored"] for r in record.role_rows(p.structure) if r["name"] == PLAIN_CUSTOM))
      panel.derived_box.inputs.set_species(SPECIES)
      panel.derived_box.inputs.set_value(WIDE_ROLE, "0x12345678")
      rows = panel.derived_box.run()
      self.assertIsNotNone(rows, panel.derived_box.message.text())
      self.assertIn(UNSTORED, [r["role"] for r in rows])
      self.assertEqual(panel.derived_box.results.rowCount(), len(rows))
      panel.import_box.inputs.set_species(SPECIES)
      panel.import_box.inputs.set_value(FIELD_ROLE, 2)
      result = panel.import_box.run()
      self.assertIsNotNone(result, panel.import_box.message.text())
      self.assertEqual(result["record"][FIELD_ROLE], 2)
      panel.tabs.setCurrentIndex(2)
      save_shot(w, "record_unstored_role.png")
      with self.yes():
         panel.table.item(shiny, ROLE_COLUMN["stored"]).setCheckState(QtCore.Qt.CheckState.Checked)
         self.settle()
      self.assertTrue(next(r for r in record.role_rows(p.structure) if r["name"] == UNSTORED)["stored"])
      self.assertEqual(w.undo_action.text(), "Undo Role stored")
      w.undo_action.trigger()
      self.settle()
      self.assertFalse(next(r for r in record.role_rows(p.structure) if r["name"] == UNSTORED)["stored"])
      self.close(w)

   def test_progression_order_species_and_colours(self) -> None:
      """!The wide seed's order combo (the engine's orders) and the kind column; the derived field completes the
      species fields and colours the bit operators; picking a species fills its fields for the preview.
      @return None
      """
      from capsule_studio.ui.editors.structure.progression import DEFAULT_ORDER_TEXT, GEN_COLUMNS
      w, panel = self.window("progression")
      p = w.project
      bc = engine.tool("battle_compiler")
      rows = progression.generation_rows(p.structure)
      seed = next(r for r in rows if r["role"] == WIDE_ROLE)
      kind_column = [k for k, _h in GEN_COLUMNS].index("kind")
      self.assertEqual(panel.table.item(seed["index"], kind_column).text(), seed["kind"])
      panel.table.selectRow(seed["index"])
      self.settle()
      self.assertTrue(panel.order.isEnabled())
      self.assertEqual([panel.order.itemText(i) for i in range(panel.order.count())],
                       [DEFAULT_ORDER_TEXT] + list(bc.WIDE_ORDERS))
      self.assertTrue(panel.set_order(bc.DEFAULT_WIDE_ORDER))
      self.settle()
      self.assertEqual(progression.entries_of(p.structure)[seed["index"]]["order"], bc.DEFAULT_WIDE_ORDER)
      self.assertEqual(w.undo_action.text(), "Undo Generation draw order")
      gender = next(r["index"] for r in rows if r["role"] == FIELD_ROLE)
      panel.table.selectRow(gender)
      self.settle()
      self.assertFalse(panel.order.isEnabled())
      self.assertIn(bc.SPECIES_PREFIX + FIELD, panel.expr.model.stringList())
      kinds = dict(panel.expr.kinds())
      self.assertEqual(kinds[bc.SPECIES_PREFIX + FIELD], expressions.KIND_FIELD)
      self.assertEqual(kinds["&"], expressions.KIND_BIT)
      self.assertEqual(panel.expr.unknown(), [])
      self.assertTrue(panel.set_species(SPECIES))
      ratio = battle.entry(p.battle, "species", SPECIES)["fields"][FIELD]
      self.assertEqual(panel.input_values()[bc.SPECIES_PREFIX + FIELD], ratio)
      self.assertTrue(panel.set_input("seed_lo", 0))
      first = panel.run_preview()
      self.assertTrue(panel.set_input("seed_lo", ratio + 1))
      self.assertNotEqual(panel.run_preview(), first)   # below / above the species' ratio
      save_shot(w, "progression_derived_bit_ops.png")
      self.close(w)


if __name__ == "__main__":
   import unittest
   unittest.main()
