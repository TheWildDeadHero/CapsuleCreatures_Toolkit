#!/usr/bin/env python3
"""!Smoke test of the locations extension's Qt layer on the Studio's world page (the
Locations tab) and of the Events tab's warp transition chooser (D-17).
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

from capsule_studio.core import events, locations  # noqa: E402
from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtLocationTests(unittest.TestCase):
   """!Builds the Studio's world page on a copy of the sandbox world and drives the Locations tab."""

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
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_qt_locations_")), ["sandbox_map"])
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

   def test_locations_tab(self) -> None:
      """!The tab shows and edits the transition, styles, locations, previews and the map's location;
      the Events tab sets a warp's transition.
      @return None
      """
      from capsule_studio.ui.editors.mapedit import MapPanel
      from capsule_studio.ui.world_shell import WorldWindow
      w = WorldWindow(path=str(self.world), host_id=STUDIO_HOSTS)
      w.show()
      self.settle()
      mp = next(p for p in w.panels if isinstance(p, MapPanel))
      lt = next(p for p in w.panels if p.panel_id == "locations")
      mp.select_map("cave")
      self.settle()
      w.tabs.setCurrentWidget(lt)
      self.settle()
      p = w.project
      self.assertEqual(lt.map_name, "cave")
      self.assertEqual(lt.map_location.currentText(), "cave")
      self.assertEqual(lt.transition.currentText(), "fade")
      self.assertEqual(lt.style_list.count(), 2)
      self.assertEqual(lt.loc_list.count(), 3)
      # The default transition.
      lt.transition.setCurrentText("box")
      lt.transition.activated.emit(lt.transition.currentIndex())
      self.settle()
      self.assertEqual(p.world.data["transition"], "box")
      self.assertEqual(p.world.undo_label(), "Set transition")
      # A style: add it, color it.
      lt.add_style("night")
      self.settle()
      self.assertEqual(lt.chosen_style(), "night")
      lt.style_colors["fill"].setText("#102040")
      lt.style_colors["fill"].editingFinished.emit()
      lt.style_slide.setValue(3)
      self.settle()
      self.assertEqual(locations.styles(p)["night"], {"fill": "#102040", "slide": 3})
      # A location with a preview; the cave map goes into it.
      lt.add_location("lake", "Quiet Lake")
      self.settle()
      self.assertEqual(lt.chosen_location(), "lake")
      lt.loc_banner.setCurrentText("night")
      lt.loc_banner.activated.emit(lt.loc_banner.currentIndex())
      self.settle()
      self.assertEqual(locations.location(p, "lake")["banner"], "night")
      lt.add_sequence("sequences/cave_preview.json")
      self.settle()
      self.assertEqual(lt.seq_list.count(), 1)
      lt.loc_preview.setCurrentText("first")
      lt.loc_preview.activated.emit(lt.loc_preview.currentIndex())
      self.settle()
      self.assertEqual(locations.location(p, "lake")["preview"]["show"], "first")
      lt.seq_list.setCurrentRow(0)
      self.settle()
      lt.seq_when.setText("night")
      lt.seq_when.editingFinished.emit()
      self.settle()
      self.assertEqual(locations.sequences(p, "lake")[0]["when"], ["night"])
      lt.map_location.setCurrentText("lake")
      lt.map_location.activated.emit(lt.map_location.currentIndex())
      self.settle()
      self.assertEqual(locations.map_location(p.map("cave")), "lake")
      self.assertIsNone(p.validate())
      # Renaming the location changes the map too.
      lt.loc_key.setText("pond")
      lt.loc_key.editingFinished.emit()
      self.settle()
      self.assertEqual(locations.map_location(p.map("cave")), "pond")
      self.assertEqual(lt.chosen_location(), "pond")
      # The Events tab: a warp's transition.
      ev = next(x for x in w.panels if x.panel_id == "events")
      mp.select_map("showcase")
      self.settle()
      w.tabs.setCurrentWidget(ev)
      self.settle()
      ev.tree.setCurrentItem(ev.tree.topLevelItem(0))
      self.settle()
      self.assertEqual(ev.transition.currentText(), "mosaic")
      ev.transition.setCurrentIndex(0)
      ev.transition.activated.emit(0)
      self.settle()
      self.assertNotIn("transition", events.events(p.map("showcase"), "warps")[0])
      self.assertIsNone(p.validate())
      self.assertTrue(w.save_all())
      w.close()


if __name__ == "__main__":
   unittest.main()
