#!/usr/bin/env python3
"""!Smoke test of the encounter editor's Qt layer: the Studio's world page with
the Encounters tab, the Encounters tool and the Encounter tables overlay,
and the encounter editor app's window. Skipped when PySide6 is missing (the
other tests need no Qt); run it in the toolkit environment, where the
editors' PySide6 is installed. Uses Qt's offscreen platform, so it needs no
display.
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

from capsule_studio.core import encounters as enc  # noqa: E402
from capsule_studio.core import maps  # noqa: E402
from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtEncounterTests(unittest.TestCase):
   """!Builds the windows on a copy of the sandbox world and drives the panels."""

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
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_qt_")), ["sandbox_map"])
      ## The copy's world.json.
      self.world = self.root / "sandbox_map" / "data" / "world.json"

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

   def test_map_editor_with_encounters(self) -> None:
      """!Tab, tool, overlay, hover and diagnostics on the Studio's world page; edits go through Undo.
      @return None
      """
      from capsule_studio.ui.editors.mapedit import MapPanel
      from capsule_studio.ui.world_shell import WorldWindow
      w = WorldWindow(path=str(self.world), host_id=STUDIO_HOSTS)
      w.show()
      self.settle()
      titles = [w.tabs.tabText(i) for i in range(w.tabs.count())]
      # F2: the Field panel; I2 / I3: Behaviors; S3 (D-30): Doors and draw order, Override sets; S6b: Interactions
      self.assertEqual(titles, ["Map", "Tileset", "Levels", "Movement modes", "Field", "Behaviors",
                                "Doors and draw order", "Interactions", "Encounters", "Events", "Locations",
                                "Objects", "Override sets"])
      mp = next(p for p in w.panels if isinstance(p, MapPanel))
      ep = next(p for p in w.panels if p.panel_id == "encounters")
      mp.select_map("showcase")
      self.settle()
      # The Encounters tool paints slot 9 on three grass cells as one undo step.
      tool_ids = [b.text() for b in mp._ext_buttons]
      self.assertEqual(tool_ids, ["Encounters", "Events", "Objects", "Override sets"])   # S3: D-30 override sets
      mp._ext_buttons[0].setChecked(True)
      self.settle()
      self.assertEqual(mp.tool(), "studio.encounters/area")
      self.assertTrue(mp.tool_options.isVisible())
      brush = mp.extension_tool()
      brush.slot, brush.on = 9, True
      cells = enc.slot_cells(w.project.map("showcase").data)[0][:3]
      mp.apply_tool(mp.tool(), cells)
      self.settle()
      doc = w.project.map("showcase")
      self.assertEqual(doc.undo_label(), "Encounters (slot 9)")
      self.assertEqual(maps.unpack(maps.get(doc.data, *cells[0]))["slot"], 9)
      self.assertIn("slot 9", mp.errors.text())   # no table for slot 9 yet
      # Overlay and hover text.
      mp.overlay_choice.setCurrentIndex(mp.overlay_choice.findText("Encounter tables"))
      self.assertIsNotNone(mp.extension_overlay_cell())
      mp.canvas.repaint()
      mp.hovered(cells[0])
      self.assertIn("slot 9: no encounter table", mp.cell_info.text())
      # The Encounters tab follows the map and adds a table for slot 9.
      w.tabs.setCurrentWidget(ep)
      self.settle()
      self.assertEqual(ep.key, "showcase")
      ep.method.setCurrentText("walk")
      ep.add_table()
      self.settle()
      tables = enc.tables(enc.map_doc(w.project, "showcase"))
      self.assertEqual([t["slot"] for t in tables], [0, 1, 9])   # the painted slot without a walk table
      ep.table_list.selectRow(2)
      self.settle()
      ep.label_edit.setText("Painted")
      ep._table_edited()
      ep.add_entry()
      self.settle()
      self.assertEqual(enc.label(enc.tables(enc.map_doc(w.project, "showcase"))[2]), "Painted")
      self.assertEqual(ep.entry_list.rowCount(), 1)
      item = ep.entry_list.item(0, 1)
      item.setText("7-9")
      self.settle()
      self.assertEqual(enc.tables(enc.map_doc(w.project, "showcase"))[2]["entries"][0]["levels"], [7, 9])
      self.assertIsNone(w.project.validate())
      # Undo in the Encounters tab undoes the encounter file's last edit.
      w.undo()
      self.settle()
      self.assertEqual(enc.tables(enc.map_doc(w.project, "showcase"))[2]["entries"][0]["levels"], 5)
      # The shared file and the world settings.
      ep.files.setCurrentRow(0)
      self.settle()
      self.assertEqual(ep.key, "\0shared")
      self.assertTrue(ep.shared_buttons.isVisibleTo(ep))
      ep.preview["night"].setChecked(True)
      self.settle()
      self.assertTrue(w.save_all())
      w.close()

   def test_encounter_editor_app_window(self) -> None:
      """!The encounter editor's window shows only the Encounters panel.
      @return None
      """
      from capsule_studio.ui.world_shell import WorldWindow
      w = WorldWindow([], str(self.world), "encounter-editor", "CapsuleCreatures Encounter Editor")
      w.show()
      self.settle()
      self.assertEqual([p.panel_id for p in w.panels], ["encounters"])
      self.assertFalse(w.tabs.tabBar().isVisible())
      ep = w.panels[0]
      # the showcase's file (DS1: the hut's comes after it)
      ep.files.setCurrentRow(next(i for i in range(ep.files.count()) if "showcase" in ep.files.item(i).text()))
      self.settle()
      self.assertEqual(ep.key, "showcase")
      self.assertGreater(ep.table_list.rowCount(), 0)
      ep.show_on_map()   # no map panel here: a message, no crash
      w.close()


if __name__ == "__main__":
   unittest.main()
