#!/usr/bin/env python3
"""!Smoke test of the events extension's Qt layer on the Studio's world page: the
Events tab, the Events map tool, the Map events overlay and hover text.
Skipped when PySide6 is missing; uses Qt's offscreen platform.
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

from capsule_studio.core import events  # noqa: E402
from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtEventTests(unittest.TestCase):
   """!Builds the Studio's world page on a copy of the sandbox world and drives the Events tab."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies the sandbox world (with the battle data beside it).
      @return None
      """
      ## Temporary root.
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_qt_events_")), ["sandbox_map"])
      ## The copy's world.json.
      self.world = self.root / "sandbox_map" / "data" / "world.json"
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root.parent, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(3):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def test_events_tab_and_tool(self) -> None:
      """!The tab lists and edits events; the tool places one; overlay and hover show them; undo works.
      @return None
      """
      from capsule_studio.ui.editors.mapedit import MapPanel
      from capsule_studio.ui.world_shell import WorldWindow
      w = WorldWindow(path=str(self.world), host_id=STUDIO_HOSTS)
      w.show()
      self.settle()
      mp = next(p for p in w.panels if isinstance(p, MapPanel))
      ev = next(p for p in w.panels if p.panel_id == "events")
      mp.select_map("showcase")
      self.settle()
      w.tabs.setCurrentWidget(ev)
      self.settle()
      self.assertEqual(ev.map_name, "showcase")
      self.assertEqual(ev.tree.topLevelItemCount(), 7)   # DS1: the hut's door warp and the garden sign
      self.assertIn("Scripts: scripts/scripts.json", ev.scripts_label.text())
      self.assertEqual(ev.hooks.count(), 1)
      # Choose the hidden berry and give it a facing.
      ev.tree.setCurrentItem(ev.tree.topLevelItem(5))   # 3 warps, the trigger, the first sign, then the berry
      self.settle()
      self.assertEqual(ev.script.currentText(), "hidden_berry")
      self.assertEqual(ev.flag.currentText(), "found_berry")
      ev.facing.setCurrentText("left")
      ev.facing.activated.emit(ev.facing.currentIndex())
      self.settle()
      doc = w.project.map("showcase")
      self.assertEqual(events.events(doc, "signs")[1]["facing"], "left")
      self.assertEqual(doc.undo_label(), "Change sign")
      w.undo()
      self.settle()
      self.assertNotIn("facing", events.events(doc, "signs")[1])
      # The Events tool places a trigger; the tab shows it chosen; fill in its script.
      w.tabs.setCurrentWidget(mp)
      self.settle()
      btn = next(b for b in mp._ext_buttons if b.text() == "Events")
      btn.setChecked(True)
      self.settle()
      tool = mp.extension_tool()
      tool.kind, tool.action = "triggers", "place"
      mp.apply_tool(mp.tool(), [(6, 8)])
      self.settle()
      self.assertEqual(events.events(doc, "triggers")[1]["at"], [6, 8])
      self.assertIn("unknown script", events.check(w.project))   # not filled in yet
      mp.overlay_choice.setCurrentIndex(mp.overlay_choice.findText("Map events"))
      self.assertIsNotNone(mp.extension_overlay_cell())
      mp.canvas.repaint()
      mp.hovered((6, 8))
      self.assertIn("trigger 1", mp.cell_info.text())
      w.tabs.setCurrentWidget(ev)
      self.settle()
      self.assertEqual(ev.selected()[:2], ("triggers", 1))
      ev.script.setCurrentText("welcome")
      ev.script.activated.emit(ev.script.currentIndex())
      ev.var.setCurrentText("welcomed")
      ev.var.activated.emit(ev.var.currentIndex())
      self.settle()
      self.assertEqual(events.events(doc, "triggers")[1], {"at": [6, 8], "script": "welcome", "var": "welcomed",
                                                           "value": 0})
      self.assertIsNone(w.project.validate())
      # Area and removal.
      mp.select_map("cave")
      self.settle()
      ev._follow()
      self.settle()
      self.assertEqual(ev.area.currentData(), "showcase")
      ev.area.setCurrentIndex(0)   # its own area
      self.settle()
      self.assertNotIn("area", w.project.map("cave").data)
      mp.select_map("showcase")
      ev._follow()
      self.settle()
      ev.tree.setCurrentItem(ev.tree.topLevelItem(ev.tree.topLevelItemCount() - 1))
      self.settle()
      ev.remove()
      self.settle()
      self.assertTrue(w.save_all())
      w.close()


if __name__ == "__main__":
   unittest.main()
