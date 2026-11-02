#!/usr/bin/env python3
"""!The screen graphics and plans Qt panels: the scene editor's Screen graphics tab (a tilemap painted by clicking its
preview with a tile picked from the strip, a palette colour set, a PNG imported) and Screen plans tab (a plan made,
its items added and edited through the generated form, a transition played, undo on the plan, saved with the
manifest), the project settings window's GBA memory tab (a build folder's checks and reserve written, a build log's
report read) and the Build settings tab's arena step. Skipped when PySide6 is missing; uses Qt's offscreen platform.
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

from capsule_studio.core import gba_memory, indexed_png, screen_graphics as sg, screen_plans as sp  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402
from test_screen_graphics_plans import (BG_PALETTE, CURSOR, OBJ_PALETTE, OVER, PATTERN_MAP,  # noqa: E402
                                        PATTERN_TILES, REPORT)

## Where the screenshots go when CAPSULE_SHOTS names a folder.
SHOTS_ENV = "CAPSULE_SHOTS"


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtScreenGraphicsPlansTests(unittest.TestCase):
   """!Drives the screen graphics and plans panels."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies the screen sandbox; settings in the copy.
      @return None
      """
      ## Temporary root (resolved, as the editor resolves the files it opens: macOS /var is /private/var, Windows
      # has short names).
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_qt_s6_")).resolve(), ["sandbox_screen"],
                                   ("data", "reference"))
      ## The copy's data folder.
      self.data = self.root / "sandbox_screen" / "data"
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

   def shot(self, w: QtWidgets.QWidget, name: str) -> None:
      """!Saves a screenshot when CAPSULE_SHOTS names a folder.
      @param w     the window
      @param name  file name
      @return None
      """
      folder = os.environ.get(SHOTS_ENV)
      if folder:
         w.grab().save(str(Path(folder) / name))

   def scene(self) -> tuple[object, dict[str, object]]:
      """!The scene editor on the sandbox's manifest.
      @return (EditorWindow, {panel_id: panel})
      """
      from capsule_studio.ui.shell import EditorWindow
      e = EditorWindow(None, str(self.data / "assets.json"))
      e.resize(1500, 860)
      e.show()
      self.settle()
      return e, {p.panel_id: p for p in e.panels}

   def test_graphics_panel(self) -> None:
      """!Paint a tilemap by clicking, pick a tile from the strip, set a colour, import a PNG; undo.
      @return None
      """
      w, panels = self.scene()
      p = panels["screen_graphics"]
      w.tabs.setCurrentWidget(p)
      self.assertEqual(p.list.count(), 7)
      self.assertTrue(p.new_asset("tilemap", "BOX"))
      self.assertEqual(p.key, "tilemap:BOX")
      p.tiles_box.setCurrentIndex(p.tiles_box.findData(PATTERN_TILES))
      p.palette_box.setCurrentIndex(p.palette_box.findData(BG_PALETTE))
      p.update_preview()
      self.assertTrue(p.picker.isVisibleTo(p))
      p._picker_clicked(3 * sg.TILE + 1, 1)           # the strip's fourth tile
      self.assertEqual(p.paint_tile.value(), 3)
      p.paint_bank.setValue(1)
      p.paint_w.setValue(2)
      p._view_clicked(5 * sg.TILE, 2 * sg.TILE)       # cell 5, 2
      cells = w.document.get("tilemap:BOX")["cells"]
      self.assertEqual(cells[2 * 32 + 5:2 * 32 + 7], [0x1003, 0x1003])
      self.shot(w, "screens_graphics_tilemap.png")
      w.undo()
      self.assertEqual(w.document.get("tilemap:BOX")["cells"][2 * 32 + 5], 0)
      p.key = OBJ_PALETTE
      p.refresh()
      self.assertEqual(p.forms.currentIndex(), 2)
      p.swatches.setCurrentCell(0, 4)
      self.assertTrue(p.set_color("#ff0000"))
      self.assertEqual(w.document.get(OBJ_PALETTE)["colors"][4], "#ff0000")
      self.assertFalse(p.set_color("red"))
      w.save_file()
      png = self.data / "two.png"
      px = bytearray(16 * 8)
      px[8 * 0 + 9] = 1
      png.write_bytes(indexed_png.encode(16, 8, px, bytes(16 * 3)))
      self.assertTrue(p.import_png(str(png), "TWO"))
      self.assertIn("palette:TWO", [p.list.item(i).text() for i in range(p.list.count())])
      self.assertTrue(p.delete_asset())
      w.save_file()
      w.close()

   def test_plan_panel(self) -> None:
      """!A plan made in the panel, filled through its form, previewed with a transition, undone, saved.
      @return None
      """
      w, panels = self.scene()
      p = panels["screen_plans"]
      w.tabs.setCurrentWidget(p)
      self.assertIsNone(p.plan)
      self.assertTrue(p.new_plan("menu"))
      self.assertEqual(p.plan.path, (self.data / "screens" / "menu.screen.json").resolve())
      self.assertTrue(p.add_item("layers"))
      self.assertEqual(p.chosen, ("layers", 0))
      self.assertIn("char_block", p.fields)
      p.fields["tiles"].setCurrentIndex(p.fields["tiles"].findData(PATTERN_TILES))
      p.fields["tiles"].activated.emit(p.fields["tiles"].currentIndex())
      self.assertEqual(p.plan.data["layers"][0]["tiles"], PATTERN_TILES)
      self.assertTrue(p.set_field("tilemap", PATTERN_MAP))
      self.assertTrue(p.add_item("palettes", palette=BG_PALETTE, banks=4))
      self.assertTrue(p.add_item("palettes", palette=OBJ_PALETTE, target="obj", tag=1))
      self.assertTrue(p.add_item("sheets", tag=2, tiles=CURSOR))
      self.assertTrue(p.add_item("sprites", name="cursor", sheet=2, palette_tag=1, x=40, y=40))
      self.assertEqual(p.problems.item(0).text(), "ok: plan: no problems")
      self.assertTrue(p.set_field("x", 100))
      self.assertEqual(p.plan.data["sprites"][0]["x"], 100)
      self.assertFalse(p.set_field("size", 9))    # refused by the field's range
      w.undo()                                     # the plan is the panel's document
      self.assertEqual(p.plan.data["sprites"][0]["x"], 40)
      self.assertTrue(p.set_transition("open", '{"mask": "bg", "from": 0, "to": 16, "color": "#f8f8f8"}'))
      p.fade.setCurrentIndex(p.fade.findData("open"))
      p._fade_chosen()
      self.assertEqual(p.slider.maximum(), 22)
      p.slider.setValue(p.slider.maximum())
      self.assertIn("call 23 of 23, BG 16", p.call_text.text())
      p.guides.setChecked(True)
      self.shot(w, "screens_plan_panel.png")
      p.chosen = ("layers", 0)
      p._fill_form()
      self.assertTrue(p.set_field("screen_block", 0))   # the map over the pattern's tiles
      self.assertTrue(any("is written over" in p.problems.item(i).text() for i in range(p.problems.count())))
      self.assertIn("char block 0", p.vram.toPlainText())
      header = self.root / "menu_screen.h"
      self.assertTrue(p.set_field("screen_block", 31))
      self.assertTrue(p.set_field("char_block", 4) is False)   # past the range: refused, nothing exported wrong
      self.assertTrue(p.export(str(header)))
      self.assertIn("namespace menu_screen", header.read_text(encoding="utf-8"))
      self.assertTrue(w.unsaved())
      w.save_file()
      self.assertFalse(p.plan.dirty)
      self.assertEqual(sp.open_plan(p.plan.path).data["sprites"][0]["name"], "cursor")
      w.close()
      again, panels = self.scene()
      self.assertEqual(panels["screen_plans"].plan.path, p.plan.path)   # found beside the manifest
      again.close()

   def test_project_panels(self) -> None:
      """!The GBA memory tab writes a build folder's checks and reserve and reads a log's report; the Build settings
      tab steps the arena by whole words.
      @return None
      """
      from capsule_studio.ui.project_shell import ProjectWindow
      build = self.root / "sandbox_screen" / "build-gba"
      build.mkdir()
      (build / gba_memory.CACHE_FILE).write_text(
         "CMAKE_TOOLCHAIN_FILE:FILEPATH=/e/cmake/toolchains/gba-devkitarm.cmake\n"
         "CAPSULE_GBA_STACK_RESERVE:STRING=2048\nCAPSULE_GBA_MEMORY_CHECKS:BOOL=ON\n", encoding="utf-8")
      w = ProjectWindow(str(self.root / "sandbox_screen" / "reference" / "project.json"))
      w.resize(1000, 700)
      w.show()
      self.settle()
      panels = {p.panel_id: p for p in w.panels}
      mem = panels["gba_memory"]
      self.assertEqual(mem.build_folder(), build)   # found beside the game
      self.assertTrue(mem.checks.isChecked())
      mem.checks.click()
      mem.reserve.setValue(4096)
      s = gba_memory.settings(build)
      self.assertEqual((s.checks, s.reserve), (False, 4096))
      mem.arena_override.click()
      self.assertEqual(gba_memory.settings(build).arena, mem._game_arena())
      log = build / "build.log"
      log.write_text(REPORT + "\n" + OVER + "\n", encoding="utf-8")
      self.assertTrue(mem.open_log(str(log)))
      self.assertEqual(mem.table.rowCount(), 2)
      self.assertEqual(mem.table.item(1, 6).text(), "NO")
      self.assertIn("screen arena", mem.notes.text())
      w.tabs.setCurrentWidget(mem)
      self.shot(w, "screens_gba_memory.png")
      bs = panels["build"]
      use, value = bs.rows["screen_arena_bytes"]
      self.assertEqual(value.singleStep(), 4)
      use.click()
      value.setValue(49152)
      self.assertEqual(w.document.data["build"]["screen_arena_bytes"], 49152)
      self.assertTrue(w.save())
      w.close()


if __name__ == "__main__":
   unittest.main()
