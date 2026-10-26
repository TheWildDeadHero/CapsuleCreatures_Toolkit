#!/usr/bin/env python3
"""!Smoke tests of review 4's page changes (engine package C6) on a copy of the Starter sample laid out as a game:
Structure > Recruit's refusal boxes, Structure > Flags & Tags' weather-suppress combo, Structure > Growth &
training's gain point, the Species page's teachable row and the Test save page's save shapes box. Skipped when
PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle  # noqa: E402
from capsule_studio.core.structure import flags, recruit, transformation  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402


class Review4PagesTests(QtBattleTestCase):
   """!The pages review 4 changed."""

   def window(self, panel_id: str) -> tuple[object, object]:
      """!A battle editor on the copy with the changed pages.
      @param panel_id  the page's panel id
      @return (BattleWindow, the panel)
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.editors.content.species import SpeciesPanel
      from capsule_studio.ui.editors.content.test_save import TestSavePanel
      from capsule_studio.ui.editors.structure.flags import FlagsTagsPanel
      from capsule_studio.ui.editors.structure.recruit import RecruitPanel
      from capsule_studio.ui.editors.structure.transformation import TransformationPanel
      w = BattleWindow([RecruitPanel, FlagsTagsPanel, TransformationPanel, SpeciesPanel, TestSavePanel],
                       self.battle_json)
      panel = w.show_panel(panel_id)
      self.settle()
      return w, panel

   def test_recruit_refusals(self) -> None:
      """!Ticking a refusal box writes refusal_consumes."""
      w, panel = self.window("recruit")
      panel.consumes["refused"].setChecked(True)
      self.assertTrue(panel.set_refusal_consumes())
      self.settle()
      self.assertEqual(recruit.section(w.project.structure)[recruit.REFUSAL_CONSUMES_KEY], ["refused"])

   def test_weather_suppress_combo(self) -> None:
      """!A tag chosen in the combo becomes the weather-suppressing tag."""
      w, panel = self.window("flags")
      tags = panel.box(flags.TAGS_KEY)
      self.assertTrue(tags.add_name("calm"))
      self.settle()
      tags.suppress.setCurrentText("calm")
      self.assertTrue(tags.set_weather_suppress())
      self.settle()
      self.assertEqual(flags.weather_suppress_tag(w.project.battle), "calm")

   def test_training_point_combo(self) -> None:
      """!The gain point combo lists the ruleset's points."""
      w, panel = self.window("growth_training")
      self.assertGreater(panel.point.count(), 1)
      self.assertTrue(panel.set_training(transformation.POINT_KEY, panel.point.itemText(1)))
      self.settle()
      self.assertEqual(transformation.training(w.project.structure)[transformation.POINT_KEY], panel.point.itemText(1))

   def test_species_teachable(self) -> None:
      """!The learn row's move added to the species' teachable moves."""
      w, panel = self.window("species")
      panel.entry_list.setCurrentRow(0)
      self.settle()
      panel.learn_move.setCurrentIndex(0)
      self.assertTrue(panel.set_teachable(True))
      self.settle()
      self.assertTrue(battle.teachable(w.project.battle, panel.selected))
      self.assertIn(panel.learn_move.currentText(), panel.teachable.text())

   def test_save_shapes_box(self) -> None:
      """!The Test save page says whether the game has script banks."""
      _w, panel = self.window("test_save")
      self.assertTrue(panel.shapes.text())
