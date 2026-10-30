#!/usr/bin/env python3
"""!S3 (D-30, engine DS1) Qt panels on a copy of the sandbox: the scene editor's Doors tab and the Animation tab's
direction-grid view, the World page's Doors and draw order tab, Override sets tab (with its map tool), the Events
tab's door chooser, the Tileset tab's animation targets and the script editor's override completion. Skipped when
PySide6 is missing; uses Qt's offscreen platform.
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

from capsule_studio.core import doors, draw_order, events, override_sets, sprite_grid, tilesets  # noqa: E402
from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402

## The sandbox's hut door and its anchor cell.
HUT, HUT_CELL = "door:HUT", (27, 20)


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtD30Tests(unittest.TestCase):
   """!Drives the D-30 panels."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies the sandbox (with the battle data beside it).
      @return None
      """
      ## Temporary root.
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_qt_d30_")), ["sandbox_map"])
      ## The copy's data folder.
      self.data = self.root / "sandbox_map" / "data"
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root.parent, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events.
      @return None
      """
      for _ in range(3):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def scene(self) -> object:
      """!The scene editor on the sandbox's asset manifest.
      @return EditorWindow
      """
      from capsule_studio.ui.shell import EditorWindow
      e = EditorWindow(None, str(self.data / "assets.json"))
      e.show()
      self.settle()
      return e

   def world(self) -> object:
      """!The Studio's world page on the sandbox.
      @return WorldWindow
      """
      from capsule_studio.ui.world_shell import WORLD_PANELS, WorldWindow
      w = WorldWindow(WORLD_PANELS, str(self.data / "world.json"), STUDIO_HOSTS, "World")
      w.show()
      self.settle()
      return w

   def test_door_panel(self) -> None:
      """!The Doors tab: the hut door previewed on its bound cell, edits through the form and tables, undo.
      @return None
      """
      e = self.scene()
      dp = next(p for p in e.panels if p.panel_id == "doors")
      e.tabs.setCurrentWidget(dp)
      self.settle()
      self.assertEqual(dp.key, HUT)
      self.assertEqual((dp.map_box.currentText(), dp.cell_x.value(), dp.cell_y.value()), ("showcase", *HUT_CELL))
      self.assertIsNotNone(dp.view.image)
      self.assertEqual(dp.entries.rowCount(), 2)
      from capsule_studio.ui.widgets import is_enabled
      self.assertFalse(is_enabled(dp.steps["close"]))   # close: the open reversed (read-only; it still scrolls)
      dp.reverse.setChecked(False)
      dp._reverse_toggled(False)
      self.settle()
      self.assertIn("close", e.document.get(HUT))
      self.assertTrue(is_enabled(dp.steps["close"]))
      dp.steps["open"].item(1, 1).setText("6")
      self.settle()
      self.assertEqual(doors.steps(e.document.get(HUT), "open")[1], [0, 6])
      dp.entries.item(0, 0).setText("t1 p2")
      self.settle()
      self.assertEqual(e.document.get(HUT)["entries"][0][0][0], {"tile": 1, "palette": 2})
      dp.entries.item(0, 1).setText("t99")   # refused by the engine: the table shows the manifest again
      self.settle()
      self.assertEqual(dp.entries.item(0, 1).text(), "t1")
      dp.cells_w.setValue(2)
      self.settle()
      self.assertEqual(doors.cells_of(e.document.get(HUT)), (2, 2))
      e.undo()
      self.settle()
      self.assertEqual(doors.cells_of(e.document.get(HUT)), (1, 2))
      dp.exit.setCurrentText("up")
      dp.exit.activated.emit(dp.exit.currentIndex())
      self.settle()
      self.assertEqual(e.document.get(HUT)["exit"], "up")
      self.assertTrue(dp.new_door("door:NEW"))
      self.assertEqual(dp.key, "door:NEW")
      self.assertTrue(dp.add_step("open"))
      self.assertEqual(len(doors.steps(e.document.get("door:NEW"), "open")), doors.NEW_FRAMES + 2)
      dp.play("open")
      dp._tick()
      dp.stop()
      e._confirm_discard = lambda: True
      e.close()

   def test_grid_view(self) -> None:
      """!The Animation tab shows a grid sprite's grid view: columns, mirroring, rows and animations by rows.
      @return None
      """
      e = self.scene()
      an = next(p for p in e.panels if p.panel_id == "animation")
      e.tabs.setCurrentWidget(an)
      an.key = "sprite:NPC"
      an.refresh()
      self.settle()
      g = an.grid_box
      self.assertIs(an.pages.currentWidget(), g)
      self.assertTrue(g.mirror.isChecked())
      self.assertEqual(g.grid.horizontalHeaderItem(3).text(), "right = left mirrored")
      self.assertIn("ROM saved", g.saved.text())
      self.assertEqual(sorted(g.walks), sorted(sprite_grid.directions()))
      g.mirror.setChecked(False)
      g._mirror_toggled(False)
      self.settle()
      self.assertEqual(sprite_grid.columns(e.document.get("sprite:NPC")), len(sprite_grid.directions()))
      self.assertTrue(g.add_row("step_b"))
      self.assertEqual(sprite_grid.rows(e.document.get("sprite:NPC")), ["stand", "step", "step_b"])
      g.anims.setCurrentRow(1)
      self.settle()
      g.anim_rows.setText("step, stand, step_b, stand")
      g.per_row.setChecked(True)
      g.durations.setText("4, 4, 4, 4")
      g._anim_edited()
      self.settle()
      self.assertEqual(sprite_grid.animations(e.document.get("sprite:NPC"))[1],
                       {"rows": ["step", "stand", "step_b", "stand"], "durations": [4, 4, 4, 4]})
      g._show(5)
      self.assertIsNotNone(g.views["right"].image)
      an.key = "sprite:WALKER"   # a plain sprite: the steps view again
      an.refresh()
      self.settle()
      self.assertIs(an.pages.currentWidget(), an.frames_page)
      self.assertTrue(an.new_grid("sprite:GRID"))
      self.assertTrue(sprite_grid.is_grid(e.document.get("sprite:GRID")))
      e._confirm_discard = lambda: True
      e.close()

   def test_world_doors_and_draw_order(self) -> None:
      """!The Doors and draw order tab: a binding added, the rule changed, the preview's verdict follows.
      @return None
      """
      w = self.world()
      wd = next(p for p in w.panels if p.panel_id == "doors_draw_order")
      w.tabs.setCurrentWidget(wd)
      self.settle()
      self.assertEqual(wd.bindings.rowCount(), 1)
      self.assertEqual(wd.bindings.item(0, 2).text(), HUT)
      wd.tileset.setCurrentText("outdoor")
      wd._fill_metatiles()
      wd.metatile.setCurrentText("flowers")
      wd.door.setCurrentText(HUT)
      self.assertTrue(wd.add_binding())
      self.assertEqual(doors.bindings(w.project.world)[-1], {"tileset": "outdoor", "metatile": "flowers",
                                                              "door": HUT})
      self.assertTrue(wd.remove_binding())
      # A one row lower than B, same elevation: A in front
      wd.at_rows[0].setValue(6)
      wd.at_rows[1].setValue(5)
      self.settle()
      self.assertTrue(wd.verdict.text().startswith("A is in front"))
      self.assertEqual(wd.sprites()[0].name, "A")
      # B's elevation base far below: B in front
      wd.levels[1].setValue(4)
      wd.bases[3].setValue(100)
      self.settle()
      self.assertEqual(draw_order.rule(w.project.world)["elevation_base"][3], 100)
      self.assertTrue(wd.verdict.text().startswith("B is in front"), wd.verdict.text())
      self.assertTrue(wd.reset_rule())
      self.assertFalse(draw_order.is_set(w.project.world))
      w._confirm_discard = lambda: True
      w.close()

   def test_override_sets_tab(self) -> None:
      """!The Override sets tab: the garden set, painting with the map tool, persistence, preview, add / remove.
      @return None
      """
      w = self.world()
      mp = next(p for p in w.panels if p.panel_id == "map")
      mp.select_map("showcase")
      self.settle()
      ov = next(p for p in w.panels if p.panel_id == "overrides")
      w.tabs.setCurrentWidget(ov)
      self.settle()
      self.assertEqual((ov.map_name, ov.chosen), ("showcase", "garden"))
      self.assertEqual(ov.cells.rowCount(), 3)
      self.assertEqual(ov.which.currentText(), "garden_planted")
      self.assertIsNotNone(ov.preview.image)
      ov.metatile.setCurrentText("outdoor/flowers_d")
      ov._paint_choice()
      w.tabs.setCurrentWidget(mp)
      self.settle()
      btn = next(b for b in mp._ext_buttons if b.text() == "Override sets")
      btn.setChecked(True)
      self.settle()
      mp.apply_tool(mp.tool(), [(31, 23)])
      self.settle()
      doc = w.project.map("showcase")
      self.assertEqual(len(override_sets.cells(doc, "garden")), 4)
      mp.overlay_choice.setCurrentIndex(mp.overlay_choice.findText("Override sets"))
      self.assertIsNotNone(mp.extension_overlay_cell())
      mp.hovered((31, 23))
      self.assertIn("override set garden", mp.cell_info.text())
      w.tabs.setCurrentWidget(ov)
      self.settle()
      ov.persist.setCurrentIndex(override_sets.persist_kinds().index(override_sets.PERSIST_NONE))
      ov._persist_changed()
      self.assertNotIn("persist", override_sets.find(doc, "garden"))
      w.undo()
      self.settle()
      self.assertIn("persist", override_sets.find(doc, "garden"))
      self.assertTrue(ov.add_set("pond"))
      self.assertEqual(ov.chosen, "pond")
      self.assertTrue(ov.remove_set())
      ov.chosen = "garden"
      ov.refresh()
      self.assertFalse(ov.remove_set())   # the scripts name it
      self.assertIsNone(w.project.validate())
      w._confirm_discard = lambda: True
      w.close()

   def test_events_door_and_targets(self) -> None:
      """!The Events tab binds a door to a warp; the Tileset tab's targets list edits an offset.
      @return None
      """
      w = self.world()
      mp = next(p for p in w.panels if p.panel_id == "map")
      mp.select_map("showcase")
      self.settle()
      ev = next(p for p in w.panels if p.panel_id == "events")
      w.tabs.setCurrentWidget(ev)
      self.settle()
      ev.tree.setCurrentItem(ev.tree.topLevelItem(2))   # the hut's door warp
      self.settle()
      self.assertEqual(ev.selected()[:2], ("warps", 2))
      self.assertGreaterEqual(ev.door.findText(HUT), 0)
      ev.door.setCurrentText(HUT)
      ev._door_chosen()
      self.settle()
      self.assertEqual(events.events(w.project.map("showcase"), "warps")[2]["door"], HUT)
      ts = next(p for p in w.panels if p.panel_id == "tileset")
      w.tabs.setCurrentWidget(ts)
      self.settle()
      ab = ts.anim_box
      ts.format_tabs.setCurrentWidget(ab)
      names = [ab.list.item(i).text() for i in range(ab.list.count())]
      ab.list.setCurrentRow(names.index("flowers"))
      self.settle()
      tb = ab.targets
      self.assertEqual(tb.table.rowCount(), 4)
      self.assertFalse(ab.first.isEnabled())
      self.assertIn("save", tb.info.text())
      tb.table.item(1, 1).setText("3")
      self.settle()
      doc = w.project.tileset("outdoor")
      self.assertEqual(tilesets.targets(tilesets.animations(doc)[names.index("flowers")])[1]["offset"], 3)
      tb.show_frame(40)
      self.assertIsNotNone(tb.view.image)
      water = names.index("water")
      ab.list.setCurrentRow(water)
      self.settle()
      tb._use_toggled(True)
      self.assertEqual(len(tilesets.targets(tilesets.animations(doc)[water])), 1)
      tb._use_toggled(False)
      self.assertEqual(tilesets.targets(tilesets.animations(doc)[water]), [])
      self.assertIsNone(w.project.validate())
      w._confirm_discard = lambda: True
      w.close()

   def test_script_completion(self) -> None:
      """!The script editor completes `override apply` with the world's sets.
      @return None
      """
      from capsule_studio.ui.script_shell import ScriptWindow
      s = ScriptWindow(str(self.data / "scripts" / "scripts.json"))
      s.show()
      self.settle()
      s.check()
      self.assertIn("garden", s.completions("script x { override apply "))
      self.assertEqual(s.completions("script x { override "), ["apply", "clear"])
      s._confirm_discard = lambda: True
      s.close()


if __name__ == "__main__":
   unittest.main()
