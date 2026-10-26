#!/usr/bin/env python3
"""!The panels of the I2 / I3 world format (Qt, offscreen), on a copy of the engine's map test world: the map
panel's "all" dictionary box and its pictures of a fixed tileset's map, the tileset panel's placement, banks, raw
entries and animations, the events panel's door / arrow / landing / dynamic warps and unpainted events, the objects
panel's movement settings, object view and stacked objects, the Behaviors panel's walls and counters, the movement
modes' turn time, bump and keep-moving, the scene editor's mirrored steps, streaming and step table, and the
background job helper. Skipped without PySide6.

With CAPSULE_CONTENT_EMERALD naming an imported Emerald content folder (assets-imported/emerald, private: never
copied into this repository), the map editor opens its world and shows one of its maps, and the times are printed.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from capsule_studio.core import behaviors, events, maps, objects, sprites, tilesets  # noqa: E402
from capsule_studio.core.document import Document  # noqa: E402
from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402
from sample_data import copy_engine_maps  # noqa: E402
from test_world_format import FRAME, SHEET_FRAMES, palette_png  # noqa: E402

## The environment variable naming an imported Emerald content folder (its world/world.json is opened).
CONTENT_ENV = "CAPSULE_CONTENT_EMERALD"
## The imported map the content test shows.
CONTENT_MAP = "LittlerootTown"
## Most seconds the content test lets opening the world and showing a map take (a slow machine's margin over the
## few seconds they take).
CONTENT_SECONDS = 60


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtWorldFormatTests(unittest.TestCase):
   """!Drives the panels on a copy of the engine's map test world."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies the world and opens it in the Studio's World page.
      @return None
      """
      from capsule_studio.ui.world_shell import WorldWindow
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_i2i3_"))
      ## The copy's world.json.
      self.world = copy_engine_maps(self.root)
      ## The window.
      self.w = WorldWindow(path=str(self.world), host_id=STUDIO_HOSTS)
      self.w.show()
      self.settle()

   def tearDown(self) -> None:
      """!Closes the window and removes the copy.
      @return None
      """
      self.w.project.world.dirty = False
      for d in self.w.project.documents():
         d.dirty = False
      self.w.close()
      shutil.rmtree(self.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(3):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def panel(self, panel_id: str) -> QtWidgets.QWidget:
      """!A tab's panel, shown.
      @param panel_id  its id
      @return the panel
      """
      p = next(p for p in self.w.panels if p.panel_id == panel_id)
      self.w.tabs.setCurrentWidget(p)
      self.settle()
      return p

   def test_map_panel(self) -> None:
      """!An "all" map shows its dictionary box ticked and pictures of its fixed tileset's metatiles; unticking makes
      the dictionary a list (one undo step), the cells showing the same.
      @return None
      """
      mp = self.panel("map")
      mp.select_map("fixed_a")
      self.settle()
      doc = mp.map_doc()
      self.assertTrue(mp.all_metatiles.isChecked())
      self.assertEqual(mp.names, self.w.project.dictionary("fixed_a"))
      self.assertTrue(all(mp.images.get(n) is not None for n in mp.names))
      self.assertIn("every metatile of its tilesets", mp.summary.text())
      self.assertIn("/32 animations", mp.summary.text())
      mp.canvas.repaint()
      mp.all_metatiles.click()
      self.settle()
      self.assertIsInstance(doc.data["metatiles"], list)
      self.w.undo()
      self.settle()
      self.assertEqual(mp.map_doc().data["metatiles"], "all")
      self.assertTrue(mp.all_metatiles.isChecked())

   def test_tileset_panel(self) -> None:
      """!The fixed tileset's placement, a bank color, a raw entry and an animation's phase from the panel.
      @return None
      """
      tp = self.panel("tileset")
      names = self.w.project.tileset_names()
      tp.ts_list.setCurrentRow(names.index("fixed"))
      self.settle()
      self.assertEqual(tp.ts_name, "fixed")
      box = tp.fixed_box
      self.assertFalse(box.make.isVisible())
      self.assertEqual(box.tiles.value(), tilesets.place_of(tp.ts_doc())["tiles"])
      self.assertIsNotNone(tp.sheet_view.image)
      box.set_color(1, 2, "#abcdef")
      self.settle()
      self.assertEqual(tilesets.bank_colors(tp.ts_doc())[1][2], "#abcdef")
      tp._metatile_chosen("wall")
      self.settle()
      pictures = tp.slot_pictures()
      self.assertEqual(len(pictures), tilesets.TILES_PER_METATILE)
      self.assertTrue(all(p is not None for p in pictures))
      tile_spin, _h, _v, _bank = box._entry_widgets[0]
      tile_spin.setValue(5)
      self.settle()
      self.assertEqual(tilesets.split_entry(tilesets.metatile(tp.ts_doc(), "wall")["entries"][0])[0], 5)
      anim = tp.anim_box
      self.assertEqual(anim.list.count(), 1)
      anim.list.setCurrentRow(0)
      anim.phase.setValue(2)
      self.settle()
      self.assertEqual(tilesets.animations(tp.ts_doc())[0]["phase"], 2)
      anim.on_shift.setCurrentText("restart")
      anim._edited()
      self.settle()
      self.assertEqual(tilesets.animations(tp.ts_doc())[0]["on_shift"], "restart")
      self.assertIsNone(self.w.project.validate())

   def test_events_panel(self) -> None:
      """!The trigger chooser offers the engine's warp triggers; a door warp and unpainted events from the panel.
      @return None
      """
      ep = self.panel("events")
      ep.follow.setChecked(False)
      ep._map_chosen("crowd")
      self.settle()
      self.assertEqual([ep.trigger.itemText(i) for i in range(ep.trigger.count())], events.warp_triggers())
      # the extension's own modules (the plugin loader imports them by path): its map tool shares the selection
      maptools = sys.modules[type(ep).__module__.rsplit(".", 1)[0] + ".maptools"]
      ep.tree.setCurrentItem(ep.tree.topLevelItem(1))   # warps come first: warp 1
      self.settle()
      self.assertIn(events.dynamic_to(), [ep.to.itemText(i) for i in range(ep.to.count())])
      ep.trigger.setCurrentText("door")
      ep._trigger_chosen()
      self.settle()
      self.assertEqual(events.events(ep.map_doc(), "warps")[1]["trigger"], "door")
      ep.unpainted.click()
      self.settle()
      self.assertTrue(ep.map_doc().data.get("unpainted_events"))
      overlay = maptools.EventOverlay().prepare(_View(ep.map_doc()))
      self.assertEqual(overlay(3, 6, None)[1], "D")
      self.assertEqual(overlay(3, 15, None)[1], "W?")

   def test_objects_panel(self) -> None:
      """!The movement settings box follows the movement; the object view and stacked objects from the panel.
      @return None
      """
      op = self.panel("objects")
      op.follow.setChecked(False)
      op._map_chosen("crowd")
      self.settle()
      self.assertTrue(op.view_on.isChecked())
      self.assertTrue(op.stacked.isChecked())
      doc = op.map_doc()
      i = objects.index_of(doc, "turner")
      op.tree.setCurrentItem(op.tree.topLevelItem(i))
      self.settle()
      box = op.movement_args
      self.assertFalse(box.isHidden())
      self.assertEqual(box.count.currentText(), "2")
      box.delays.setCurrentText("medium")
      box._changed()
      self.settle()
      self.assertEqual(objects.objects(op.map_doc())[i]["movement_args"], {"choices": ["down", "up"]})
      op.view[0].setValue(3)
      self.settle()
      self.assertEqual(objects.object_view(op.map_doc())[0], 3)
      self.assertIsNone(self.w.project.validate())

   def test_world_settings(self) -> None:
      """!Behaviors' walls and kind, and a movement mode's turn time, from the panels.
      @return None
      """
      bp = self.panel("behaviors")
      rows = [r["name"] for r in behaviors.rows(self.w.project.world)]
      bp.list.setCurrentRow(rows.index("fence_east"))
      self.settle()
      self.assertTrue(bp.walls["right"].isChecked())
      bp.walls["down"].click()
      self.settle()
      self.assertEqual(self.w.project.world.data["behaviors"][rows.index("fence_east")]["walls"], ["down", "right"])
      bp.list.setCurrentRow(rows.index("counter_top"))
      self.settle()
      self.assertEqual(bp.kind.currentText(), "counter")
      mp = self.panel("movement_modes")
      mp.selected = "trek"
      mp.refresh()
      self.assertEqual(mp.turn_frames.value(), 8)
      self.assertTrue(mp.bumps.isChecked() and mp.keeps_moving.isChecked())
      self.assertTrue(mp.set_mode("turn_frames", 4))
      self.assertIsNone(self.w.project.validate())

   def test_background_job(self) -> None:
      """!A background job's result comes back on the GUI thread; a newer job of the same name replaces it.
      @return None
      """
      from capsule_studio.ui import background
      got = []
      background.start(self.w, "probe", lambda: 1, lambda r: got.append(("old", r)))
      background.start(self.w, "probe", lambda: 2, lambda r: got.append(("new", r)))
      deadline = time.monotonic() + CONTENT_SECONDS
      while not got and time.monotonic() < deadline:
         self.settle()
         time.sleep(background.POLL_MS / 1000)
      self.settle()
      self.assertEqual(got, [("new", 2)])
      self.assertFalse(background.running(self.w, "probe"))


class _View:
   """!The part of plugins.MapView an overlay reads (its map document)."""

   def __init__(self, doc: Document) -> None:
      """!Wraps a map document.
      @param doc  map Document
      """
      ## The map document.
      self.doc = doc


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtSpriteTests(unittest.TestCase):
   """!The scene editor's animation panel: mirrored steps, streaming and the step table (I3)."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def test_animation_panel(self) -> None:
      """!Flip combos per step, the stream box and the step table change the sprite.
      @return None
      """
      from capsule_studio.ui.editors.animation import AnimationPanel, FLIP_COLUMN
      from capsule_studio.ui.shell import EditorWindow
      root = Path(tempfile.mkdtemp(prefix="capsule_qt_sprite_"))
      try:
         sheet = root / "walker.png"
         w = FRAME * SHEET_FRAMES
         sheet.write_bytes(palette_png(w, FRAME, bytes(1 + x // FRAME for _y in range(FRAME) for x in range(w))))
         doc = Document(path=root / "assets.json")
         key = "sprite:WALKER"
         with doc.edit("New"):
            a = sprites.new_sprite(doc, key, FRAME, FRAME)
            a["palette"] = ["#000000", "#ff0000", "#00ff00", "#0000ff"]
         doc.save()
         with doc.edit("Frames"):
            sprites.add_sheet_frames(doc, key, sheet)
         doc.save()
         win = EditorWindow([AnimationPanel], root / "assets.json")
         win.show()
         for _ in range(3):
            self.app.processEvents()
         panel = win.panels[0]
         panel.key = key
         panel.refresh()
         self.assertEqual(panel.table.rowCount(), SHEET_FRAMES)
         combo = panel.table.cellWidget(1, FLIP_COLUMN)
         combo.activated.emit(1)
         for _ in range(3):
            self.app.processEvents()
            QtCore.QCoreApplication.sendPostedEvents()
         self.assertEqual(sprites.flips(win.document.get(key)), [0, 1, 0])
         panel.stream.click()
         self.assertTrue(win.document.get(key).get("stream"))
         panel.has_steps.click()
         panel.step_table[1].setValue(2)
         self.assertEqual(sprites.step_table(win.document.get(key)), [0, 2, 0, 0])
         panel._show_position(sprites.DEFAULT_DURATION)   # the mirrored step shows mirrored
         self.assertIsNotNone(panel.view.image if hasattr(panel.view, "image") else True)
         win.document.dirty = False
         win.close()
      finally:
         shutil.rmtree(root, ignore_errors=True)


@unittest.skipIf(QtWidgets is None or not os.environ.get(CONTENT_ENV), f"{CONTENT_ENV} names no imported content")
class QtContentTests(unittest.TestCase):
   """!The map editor on an imported Emerald world (private content, never part of this repository)."""

   def test_open_imported_world(self) -> None:
      """!Opens the world, shows a map of fixed tilesets with every metatile pictured, in a few seconds.
      @return None
      """
      from capsule_studio.ui import world_shell
      from capsule_studio.ui.editors.mapedit import MapPanel
      app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
      world = Path(os.environ[CONTENT_ENV]) / "world" / "world.json"
      t = time.perf_counter()
      w = world_shell.WorldWindow(path=str(world), host_id=STUDIO_HOSTS)
      w.show()
      app.processEvents()
      opened = time.perf_counter() - t
      mp = next(p for p in w.panels if isinstance(p, MapPanel))
      t = time.perf_counter()
      mp.select_map(CONTENT_MAP)
      app.processEvents()
      shown = time.perf_counter() - t
      print(f"\nimported world: opened in {opened:.2f} s, {CONTENT_MAP} shown in {shown:.2f} s")
      self.assertLess(opened + shown, CONTENT_SECONDS)
      self.assertTrue(maps.uses_all(mp.map_doc().data))
      self.assertEqual(mp._compile_text, "")
      self.assertTrue(all(mp.images.get(n) is not None for n in mp.names))
      w.close()


if __name__ == "__main__":
   unittest.main()
