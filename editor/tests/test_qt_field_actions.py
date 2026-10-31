#!/usr/bin/env python3
"""!Smoke tests of the F2 pages: Structure > Field actions (the list, the form with the engine's requirement checks,
the target and script pickers from the game's world and scripts, a rename following the scripts, the preview), the
World page's Field panel (object kinds, map tags, a map's darkness / tags / escape point, flight points) and the
Encounter rules page's lead preview. Each opens a copy of the map sandbox laid out as one game
(sample_data.make_field_game) and edits through the widgets. Skipped when PySide6 is missing; uses Qt's offscreen
platform. CAPSULE_SHOTS=FOLDER saves a picture of each page there.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core import map_field  # noqa: E402
from capsule_studio.core.structure import field_actions  # noqa: E402
from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402
from sample_data import DATA, make_field_game  # noqa: E402
from test_field_actions import ACTIONS, BUSH, CAVE, DARK, LIGHT_QUERY, SANDBOX_SCRIPTS  # noqa: E402

## Environment variable naming a folder for the pages' pictures.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a picture, pixels.
SHOT_SIZE = (1200, 760)


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class FieldActionPagesTests(unittest.TestCase):
   """!The Field actions page, the World page's Field panel and the lead preview."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies the game.
      @return None
      """
      ## The game folder.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_f2_"))
      ## Its battle.json.
      self.battle_json = make_field_game(self.root)
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(3):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

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

   def battle_window(self, panel_id: str) -> tuple[object, object]:
      """!A battle editor on the copy with the F2 page and the Encounter rules page.
      @param panel_id  the page's panel id
      @return (BattleWindow, the panel)
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.editors.structure.encounter_rules import EncounterRulesPanel
      from capsule_studio.ui.editors.structure.field_actions import FieldActionsPanel
      w = BattleWindow([FieldActionsPanel, EncounterRulesPanel], self.battle_json)
      panel = w.show_panel(panel_id)
      self.settle()
      return w, panel

   def scripts_text(self) -> str:
      """!The sandbox's scripts source.
      @return text
      """
      return self.root.joinpath(DATA, *SANDBOX_SCRIPTS).read_text(encoding="utf-8")

   def test_field_actions_page(self) -> None:
      """!The Starter's actions with the game's choices; a requirement checked, refused and applied; the target and
      script pickers; add, rename (the scripts follow, one undo step), move and remove.
      @return None
      """
      w, panel = self.battle_window("field_actions")
      p = w.project
      self.assertIs(w.document, p.structure)
      self.assertEqual(panel.names(), ACTIONS)
      self.assertEqual(panel.list.count(), len(ACTIONS))
      self.assertEqual(panel.selected, "wade")
      self.assertEqual(panel.target_kind.currentText(), "behavior")
      self.assertEqual(panel.target_name.currentText(), "water")
      self.assertIn("field_wade", [panel.script.itemText(i) for i in range(panel.script.count())])
      self.assertIn("field_action_ask_wade", panel.implicit.text())
      self.assertIn("clear: member 0", panel.preview_text.text())   # the first party: Sproutle knows Vine Lash
      self.shot(w, panel, "studio_field_actions")
      # the requirement: checked (nothing changes), refused, applied
      self.assertIsNotNone(panel.check_requirement("knows.nothing_at_all"))
      self.assertIn("nothing_at_all", panel.check_text.text())
      self.assertFalse(panel.apply_requirement("flag.no_such_flag"))
      self.assertTrue(panel.apply_requirement("knows.tide_slam"))
      self.settle()
      self.assertEqual(field_actions.actions(p.structure)[0]["requires"], "knows.tide_slam")
      self.assertEqual(w.undo_action.text(), "Undo Set field action")
      # the target: the object kinds of the world
      panel.list.setCurrentRow(1)
      self.settle()
      self.assertEqual(panel.selected, "clear")
      self.assertEqual(panel.target_kind.currentText(), "object")
      self.assertEqual([panel.target_name.itemText(i) for i in range(panel.target_name.count())], [BUSH])
      set_kind = panel.target_kind.findText("tag")
      panel.target_kind.setCurrentIndex(set_kind)
      panel.target_kind.activated.emit(set_kind)
      self.settle()
      self.assertEqual(field_actions.actions(p.structure)[1]["target"], {"tag": DARK})
      # add, move, remove
      self.assertTrue(panel.add_action("rest", "field_wade"))
      self.settle()
      self.assertEqual(panel.names(), ["wade", "clear", "rest", "light"])
      self.assertTrue(panel.move_action(1))
      self.settle()
      self.assertEqual(panel.names(), ["wade", "clear", "light", "rest"])
      self.assertTrue(panel.remove_action())
      self.settle()
      # rename: the scripts follow; undo puts them back
      panel.list.setCurrentRow(2)
      self.settle()
      self.assertEqual(panel.selected, "light")
      self.assertTrue(panel.rename_action("glow"))
      self.settle()
      self.assertIn("field_action available glow", self.scripts_text())
      w.undo()
      self.settle()
      self.assertIn(LIGHT_QUERY, self.scripts_text())
      self.assertEqual(panel.names(), ACTIONS)
      self.assertIsNone(p.error_now())

   def test_lead_preview(self) -> None:
      """!The Encounter rules page names who of the chosen party leads.
      @return None
      """
      w, panel = self.battle_window("encounter_rules")
      self.assertTrue(panel.lead_party.count())
      self.assertIn("leads", panel.lead_preview.text())
      self.assertTrue(panel.set_lead("level >= 99"))
      self.settle()
      self.assertEqual(panel.lead_preview.text(), "nobody leads")

   def test_world_field_panel(self) -> None:
      """!Kinds and tags (a rename follows the maps), the cave's darkness / tags / escape point, flight points.
      @return None
      """
      from capsule_studio.ui.editors.map_field import MapFieldPanel
      from capsule_studio.ui.world_shell import WorldWindow
      w = WorldWindow(path=str(self.root / DATA / "world.json"), host_id=STUDIO_HOSTS)
      w.show()
      self.settle()
      panel = next(p for p in w.panels if isinstance(p, MapFieldPanel))
      w.tabs.setCurrentWidget(panel)
      self.settle()
      world = w.project.world
      self.assertEqual(panel.name_lists[map_field.KINDS_KEY].count(), 1)
      cave = panel.map_choice.findText(CAVE)
      panel.map_choice.setCurrentIndex(cave)
      panel.map_choice.activated.emit(cave)
      self.settle()
      self.assertEqual(panel.darkness.value(), 3)
      self.assertEqual(panel.tags.item(0).checkState(), QtCore.Qt.CheckState.Checked)
      self.assertEqual(panel.flights.count(), len(map_field.flight_points(world)))
      # C8: the world's darkness levels (the sandbox's four), the darkness spin up to the darkest
      self.assertEqual(panel.levels.rowCount(), len(map_field.darkness_levels(world)))
      self.assertEqual(panel.darkness.maximum(), map_field.darkest(world))
      self.shot(w, panel, "studio_map_darkness")
      self.assertTrue(panel.add_level())
      self.settle()
      self.assertEqual(panel.levels.rowCount(), map_field.darkest(world))
      self.assertTrue(panel.set_level(map_field.darkest(world), "brightness", 12))
      self.settle()
      self.shot(w, panel, "studio_map_darkness_levels")
      self.assertTrue(panel.remove_level())
      self.settle()
      self.assertTrue(panel.set_darkness(1))
      self.settle()
      self.assertEqual(map_field.map_rules(w.project.map(CAVE), world)[0], 1)
      self.assertFalse(panel.set_darkness(map_field.darkest(world) + 1))
      self.assertTrue(panel.set_escape_point(True))
      self.settle()
      self.assertTrue(map_field.map_rules(w.project.map(CAVE), world)[2])
      panel.tags.item(0).setCheckState(QtCore.Qt.CheckState.Unchecked)
      self.settle()
      self.assertEqual(map_field.map_rules(w.project.map(CAVE), world)[1], [])
      # kinds: add, rename (the maps' objects follow), a removal refused while named
      self.assertTrue(panel.add_name(map_field.KINDS_KEY, "boulder"))
      self.settle()
      panel.name_lists[map_field.KINDS_KEY].setCurrentRow(0)
      self.assertTrue(panel.rename_name(map_field.KINDS_KEY, "shrub"))
      self.settle()
      self.assertEqual(map_field.object_kinds(world), ["shrub", "boulder"])
      self.assertTrue(map_field.kind_users(w.project, "shrub"))
      panel.name_lists[map_field.KINDS_KEY].setCurrentRow(0)
      self.assertFalse(panel.remove_name(map_field.KINDS_KEY))
      # flight points: add on the map shown, move it, remove it
      self.assertTrue(panel.add_flight("pond"))
      self.settle()
      panel.flights.setCurrentRow(panel.flights.count() - 1)
      self.settle()
      self.assertEqual(panel.selected_flight(), "pond")
      self.assertTrue(panel.set_flight("x", 2))
      self.assertTrue(panel.set_flight("label", "Pond"))
      self.settle()
      rec = map_field.flight_points(world)[-1]
      self.assertEqual((rec["map"], rec["x"], rec["label"]), (CAVE, 2, "Pond"))
      self.assertTrue(panel.remove_flight())
      self.settle()
      self.assertIsNone(w.project.validate())

   def test_script_words(self) -> None:
      """!The script editor colours the engine's F1 / F2 statement words.
      @return None
      """
      from capsule_studio.core import engine
      from capsule_studio.ui.editors.script import engine_keywords
      sc = engine.tool("script_compiler")
      words = engine_keywords()
      for word in (sc.FLIGHT_WORD, *sc.FLIGHT_KINDS, sc.DARKNESS_WORD, sc.ESCAPE_WORD, sc.FIELD_ACTION_WORD,
                   *sc.FIELD_ACTION_KINDS, sc.FIELD_EFFECT_WORD):
         self.assertIn(word, words)


if __name__ == "__main__":
   unittest.main()
