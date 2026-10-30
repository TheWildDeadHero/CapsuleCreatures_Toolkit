"""!Smoke tests of the S17 pages (the studio side of the engine's E13b): the
Moves page's point handlers (a move's .ceffect point members), the Conditions
page's side condition handlers, the Effects page's palette with E13b's
statements, the Turn page's delayed phase, the Bench page's owner texts
switch and data level, the damage calculator's conditions and hidden stat
inputs, and the classic cost cell. Each opens a copy of a sample laid out as a
game and edits through the widgets (one undo step per edit). Skipped when
PySide6 is missing; uses Qt's offscreen platform; the classic tests are
skipped without the reference repo. CAPSULE_SHOTS=FOLDER saves pictures of
the pages there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle, bench, engine, holders, logic, pipelines  # noqa: E402
from capsule_studio.core.structure import record, turn  # noqa: E402
from sample_data import classic_data, make_game, needs_classic  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## Where CAPSULE_SHOTS names the picture folder.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a saved picture.
SHOT_SIZE = (1300, 900)
## Classic names: a move with move_type handlers, a move with a power handler, a screen side condition.
SKY_BALL, WHIRL, HARD_WALL = "Sky Ball", "Whirl", "Hard Wall"


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


class StarterPagesTests(QtBattleTestCase):
   """!The Starter: palette, Turn, Bench, calculator."""

   def test_palette(self) -> None:
      """!The block palette lists E13b's statements (from the engine's primitives) and inserts one.
      @return None
      """
      w, panel = self.window("effects")
      owner = next(r for r in logic.owners(w.project) if r.kind == "move")
      self.assertTrue(panel.select_owner(f"move:{owner.name}"))
      self.settle()
      items = {}
      for i in range(panel.blocks.palette.topLevelItemCount()):
         group = panel.blocks.palette.topLevelItem(i)
         for k in range(group.childCount()):
            items[group.child(k).text(0)] = group.child(k)
      for label in ("reset stages", "delay", "reward", "end battle", "stage (silent)"):
         self.assertIn(label, items)
      panel.blocks.palette.scrollToItem(items["end battle"])
      panel.blocks.palette.setCurrentItem(items["reset stages"])
      save_shot(w, "palette_e13b.png")
      self.close(w)

   def test_turn_delayed_phase(self) -> None:
      """!The Turn page offers the delayed phase with its note, adds it (one undo step) and shows what it runs.
      @return None
      """
      w, panel = self.window("turn")
      kinds = [panel.phase_kind.itemText(i) for i in range(panel.phase_kind.count())]
      self.assertEqual(kinds, turn.end_phases())
      at = kinds.index("delayed")
      from PySide6 import QtCore
      self.assertIn("delay", panel.phase_kind.itemData(at, QtCore.Qt.ItemDataRole.ToolTipRole))
      before = len(turn.phase_rows(w.project.structure))
      self.assertTrue(panel.add_phase("delayed"))
      self.settle()
      rows = turn.phase_rows(w.project.structure)
      self.assertEqual(len(rows), before + 1)
      panel.phases.setCurrentRow(next(r["index"] for r in rows if r["run"] == "delayed"))
      self.settle()
      self.assertIn("delayed: ", panel.phase_note.text())
      self.assertIn("at most once", panel.phase_note.text())
      save_shot(w, "turn_delayed_phase.png")
      w.undo()
      self.settle()
      self.assertEqual(len(turn.phase_rows(w.project.structure)), before)
      self.close(w)

   def test_bench_owner_texts(self) -> None:
      """!The Owner texts box writes the scenario's owner_texts (one undo step); a new member gets the data's level.
      @return None
      """
      w, panel = self.window("bench")
      panel.toolchain_check = lambda: []
      self.assertTrue(panel.new_scenario("wild"))
      self.settle()
      doc = panel.scenario_doc()
      self.assertFalse(panel.owner_texts.isChecked())
      panel.owner_texts.click()
      self.settle()
      self.assertIs(doc.data[bench.owner_texts_key()], True)
      save_shot(w, "bench_owner_texts.png")
      self.assertIs(w.document, doc)
      w.undo()
      self.settle()
      self.assertNotIn(bench.owner_texts_key(), doc.data)
      self.assertFalse(panel.owner_texts.isChecked())
      self.assertTrue(panel.add_row("parties"))
      self.settle()
      member = doc.data["parties"][-1]["members"][0]
      self.assertEqual(member["level"], bench.new_member_level(w.project))
      self.close(w)

   def test_calculator_inputs(self) -> None:
      """!The calculator's condition combos list the data's names; a stat input's spin hides without its role.
      @return None
      """
      w, panel = self.window("pipelines")
      p = w.project
      compiled = p.compile()[0]
      self.assertEqual([panel.defender_side.itemText(i) for i in range(1, panel.defender_side.count())],
                       compiled["names"]["side_conditions"])
      label, spin = panel.stat_input_rows["training"]
      self.assertEqual(spin.isHidden(), not record.has_stat_input(p.battle, "training"))
      with mock.patch.object(record, "has_stat_input", lambda _d, key: key != "training"):
         panel._fill_calculator_choices()
      self.assertTrue(spin.isHidden())
      self.assertTrue(label.isHidden())
      self.assertFalse(panel.stat_input_rows["gene"][1].isHidden())
      self.assertEqual(panel.calculator_args()["defender_active"], pipelines.SIDE_ACTIVE)
      self.close(w)


@needs_classic
class ClassicPagesTests(QtBattleTestCase):
   """!E13b's owners on the reference repo's classic template."""

   def setUp(self) -> None:
      """!The classic template as a game.
      @return None
      """
      super().setUp()
      self.battle_json = make_game(self.root / "classic", classic_data())

   def test_move_point_handlers(self) -> None:
      """!The Moves page shows a move's point handlers (its logic's point members), adds one into its logic block
      and Undo on the page takes it back; the hp cost cell of a move without its own cost says it pays nothing.
      @return None
      """
      from capsule_studio.ui.editors.content.moves import FROM_COLUMN, FROM_FREE
      w, panel = self.window("moves")
      self.select(panel, SKY_BALL)
      box = panel.handlers
      rc = engine.tool("ruleset_compiler")
      shown = [box.table.cellWidget(r, 0).currentText() for r in range(box.table.rowCount())]
      self.assertIn(rc.MOVE_TYPE_POINT, shown)
      self.assertEqual(shown, [h["point"] for h in holders.handlers(w.project.battle, "moves", SKY_BALL)])
      self.assertIn(rc.MOVE_TYPE_POINT, box.choices)
      self.assertTrue(box.in_logic)
      hp = next(r for r in range(panel.cost_table.rowCount())
                if panel.cost_table.item(r, 0).text().startswith(w.project.structure.data["resources"][0]["name"]))
      self.assertEqual(panel.cost_table.item(hp, FROM_COLUMN).text(), FROM_FREE)
      save_shot(w, "moves_point_handlers.png")
      self.select(panel, WHIRL)
      before = holders.handlers(w.project.battle, "moves", WHIRL)
      self.assertTrue(panel.handlers.add_handler("power", "{ modify by 3; }"))
      self.settle()
      self.assertEqual(len(holders.handlers(w.project.battle, "moves", WHIRL)), len(before) + 1)
      self.assertEqual(panel.handlers.table.rowCount(), len(before) + 1)
      self.assertIsNot(panel.current_document(), w.project.battle)   # Undo follows the edit into the source
      w.undo()
      self.settle()
      self.assertEqual(holders.handlers(w.project.battle, "moves", WHIRL), before)
      self.close(w)

   def test_side_condition_handlers(self) -> None:
      """!The Conditions page's side condition tab has the point handlers box with the screen handler.
      @return None
      """
      w, panel = self.window("conditions")
      tab = panel.tab("side_condition")
      panel.tabs.setCurrentWidget(tab)
      self.select(tab, HARD_WALL)
      self.assertIsNotNone(tab.handlers)
      self.assertEqual(tab.handlers.table.rowCount(),
                       len(holders.handlers(w.project.structure, "side_conditions", HARD_WALL)))
      self.assertGreater(tab.handlers.table.rowCount(), 0)
      save_shot(w, "conditions_side_handlers.png")
      self.close(w)

   def test_calculator_hit_type(self) -> None:
      """!The calculator says which type the hit has when the move_type point changes it.
      @return None
      """
      w, panel = self.window("pipelines")
      panel.move.setCurrentText(SKY_BALL)
      panel.weather.setCurrentText(w.project.names("weathers")[0])
      t = panel.calculate()
      self.assertIsNotNone(t)
      self.assertNotEqual(t.hit_type, t.own_type)   # the first weather turns the ball's type
      self.assertIn(f"hits as {t.hit_type}", panel.damage.text())
      self.assertEqual(battle.level_max(w.project.structure), panel.level.maximum())
      self.close(w)
