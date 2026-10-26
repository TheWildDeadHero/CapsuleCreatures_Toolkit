#!/usr/bin/env python3
"""!Smoke test of the objects extension's Qt layer on the Studio's world page: the
Objects tab, the Objects map tool, the Map objects overlay and hover text.
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

from capsule_studio.core import objects  # noqa: E402
from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtObjectTests(unittest.TestCase):
   """!Builds the Studio's world page on a copy of the sandbox world and drives the Objects tab."""

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
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_qt_objects_")), ["sandbox_map"])
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

   def test_objects_tab_and_tool(self) -> None:
      """!The tab lists and edits objects, their pages, options and routes; the tool places one; overlay and
      hover show them.
      @return None
      """
      from capsule_studio.ui.editors.mapedit import MapPanel
      from capsule_studio.ui.world_shell import WorldWindow
      w = WorldWindow(path=str(self.world), host_id=STUDIO_HOSTS)
      w.show()
      self.settle()
      mp = next(p for p in w.panels if isinstance(p, MapPanel))
      ids = [p.panel_id for p in w.panels]
      self.assertLess(ids.index("events"), ids.index("objects"))   # the Objects tab follows Events
      ob = next(p for p in w.panels if p.panel_id == "objects")
      mp.select_map("showcase")
      self.settle()
      w.tabs.setCurrentWidget(ob)
      self.settle()
      self.assertEqual(ob.map_name, "showcase")
      self.assertEqual(ob.tree.topLevelItemCount(), 13)   # F2: the sandbox's bush; DS1: porter and keeper
      # Choose the rival: its fields and page show.
      ob.tree.setCurrentItem(ob.tree.topLevelItem(3))
      self.settle()
      self.assertEqual(ob.name.text(), "rival")
      self.assertEqual(ob.sight.value(), 4)
      self.assertEqual(ob.until.currentText(), "beat_rival")
      self.assertEqual(ob.page_list.count(), 1)
      ob.sight.setValue(6)
      self.settle()
      doc = w.project.map("showcase")
      self.assertEqual(objects.objects(doc)[3]["spotter"]["sight"], 6)
      self.assertEqual(doc.undo_label(), "Change object")
      w.undo()
      self.settle()
      self.assertEqual(objects.objects(doc)[3]["spotter"]["sight"], 4)
      # The page: give it a facing, a self switch condition and its own options.
      ob.page_list.setCurrentRow(0)
      self.settle()
      self.assertEqual(ob.pg_flag.currentText(), "beat_rival")
      ob.pg_facing.setCurrentText("up")
      ob.pg_facing.activated.emit(ob.pg_facing.currentIndex())
      self.settle()
      self.assertEqual(objects.objects(doc)[3]["pages"][0]["facing"], "up")
      ob.pg_self["B"].setChecked(True)
      self.settle()
      self.assertEqual(objects.objects(doc)[3]["pages"][0]["when"], {"flag": "beat_rival", "self": "B"})
      ob.pg_has_options.setChecked(True)
      self.settle()
      ob.pg_options["through"].setChecked(True)
      self.settle()
      self.assertEqual(objects.objects(doc)[3]["pages"][0]["options"], {"through": True})
      # Add a second page, hide the object on it, move it first.
      ob.add_page()
      self.settle()
      self.assertEqual(ob.page_list.count(), 2)
      self.assertEqual(ob._page_row, 1)
      ob.pg_hidden.setChecked(True)
      self.settle()
      self.assertTrue(objects.objects(doc)[3]["pages"][1]["hidden"])
      self.assertFalse(ob.pg_facing.isEnabled())
      ob.move_page(-1)
      self.settle()
      self.assertTrue(objects.objects(doc)[3]["pages"][0]["hidden"])
      ob.remove_page()
      self.settle()
      self.assertEqual(len(objects.objects(doc)[3]["pages"]), 1)
      # Trigger, speed and an option of the object.
      ob.trigger.setCurrentText("player_touch")
      ob.trigger.activated.emit(ob.trigger.currentIndex())
      ob.speed.setValue(4)
      ob.options["on_top"].setChecked(True)
      self.settle()
      o3 = objects.objects(doc)[3]
      self.assertEqual((o3["trigger"], o3["speed"], o3["options"]), ("player_touch", 4, {"on_top": True}))
      # The jogger's route: shown, checked as typed, applied.
      ob.tree.setCurrentItem(ob.tree.topLevelItem(5))
      self.settle()
      self.assertEqual(ob.route.text.toPlainText(), "right 6\ndown 2\nleft 6\nup 2")
      self.assertTrue(ob.route.isEnabled())
      ob.route.text.setPlainText("left 1\nhop")
      self.assertIn("unknown step 'hop'", ob.route.status.text())
      ob.route.text.setPlainText("left 1\nwait 10\nright 1")
      self.assertEqual(ob.route.status.text(), "The steps compile.")
      ob.route.repeat.setChecked(False)
      ob.route.apply()
      self.settle()
      self.assertEqual(objects.objects(doc)[5]["route"], {"steps": ["left 1", "wait 10", "right 1"],
                                                          "repeat": False})
      self.assertEqual(doc.undo_label(), "Set route")
      # Movement and range.
      ob.tree.setCurrentItem(ob.tree.topLevelItem(0))
      self.settle()
      ob.movement.setCurrentText("wander")
      ob.movement.activated.emit(ob.movement.currentIndex())
      self.settle()
      ob.range_x.setValue(3)
      self.settle()
      self.assertEqual(objects.objects(doc)[0]["movement"], "wander")
      self.assertEqual(objects.objects(doc)[0]["range"], [3, 1])
      # The Objects tool places one; the tab shows it chosen; rename it.
      w.tabs.setCurrentWidget(mp)
      self.settle()
      btn = next(b for b in mp._ext_buttons if b.text() == "Objects")
      btn.setChecked(True)
      self.settle()
      tool = mp.extension_tool()
      tool.action = "place"
      mp.apply_tool(mp.tool(), [(6, 9)])
      self.settle()
      self.assertEqual(objects.objects(doc)[13]["at"], [6, 9])   # after the sandbox's bush, porter and keeper (DS1)
      mp.overlay_choice.setCurrentIndex(mp.overlay_choice.findText("Map objects"))
      self.assertIsNotNone(mp.extension_overlay_cell())
      mp.canvas.repaint()
      mp.hovered((6, 9))
      self.assertIn("object 13 npc_1", mp.cell_info.text())
      w.tabs.setCurrentWidget(ob)
      self.settle()
      self.assertEqual(ob.selected()[0], 13)
      ob.name.setText("visitor")
      ob.name.editingFinished.emit()
      self.settle()
      self.assertEqual(objects.objects(doc)[13]["name"], "visitor")
      self.assertIsNone(w.project.validate())
      ob.remove()
      self.settle()
      self.assertEqual(len(objects.objects(doc)), 13)
      self.assertTrue(w.save_all())
      w.close()


if __name__ == "__main__":
   unittest.main()
