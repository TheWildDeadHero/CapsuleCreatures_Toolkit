#!/usr/bin/env python3
"""!Smoke test of the Plugin data panel (plugin API 3) on the Studio's world page: the tab shows for a game with a
connector, the inspector built from the sample connector's schema edits blocks with undo, cells follow the chooser,
the preview and the CSV format work, and the Studio's other pages share their documents.
Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import json
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

from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402
from test_plugin_data import OTHER_PARTY, PARTY, SAMPLE_ID, make_game, read_json  # noqa: E402

## Times pending events are run by settle().
SETTLE_ROUNDS = 3


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtPluginDataTests(unittest.TestCase):
   """!The world page on a copy of the map sandbox listing the sample plugin."""

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
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_plugin_data_"))
      ## The project manifest.
      self.project = make_game(self.root)
      ## The world.
      self.world = self.project.parent.parent / "data" / "world.json"
      ## The battle manifest.
      self.battle = self.root / "samples" / "starter" / "battle.json"
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy and the plugins' private modules.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)
      for name in [n for n in sys.modules if n.startswith(("capsule_connector_", "_capsule_plugin_sample"))]:
         del sys.modules[name]

   def settle(self) -> None:
      """!Runs pending events (scheduled refreshes).
      @return None
      """
      for _ in range(SETTLE_ROUNDS):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def test_plugin_data_tab(self) -> None:
      """!Records, adding a block, fields as undo steps, cells, problems, the preview, export and import.
      @return None
      """
      from capsule_studio.ui.editors.mapedit import MapPanel
      from capsule_studio.ui.world_shell import WorldWindow
      w = WorldWindow(path=str(self.world), host_id=STUDIO_HOSTS)
      w.show()
      self.settle()
      pd = next(p for p in w.panels if p.panel_id == "plugin-data")
      mp = next(p for p in w.panels if isinstance(p, MapPanel))
      w.tabs.setCurrentWidget(pd)
      self.settle()
      self.assertEqual((pd.plugin_box.currentText(), pd.plugin_id()), ("Party moods (sample plugin)", SAMPLE_ID))
      self.assertEqual([pd.point_box.itemText(i) for i in range(pd.point_box.count())], ["party", "map", "cell"])
      self.assertTrue(pd.choose(SAMPLE_ID, "party", PARTY))
      self.assertTrue(pd.add_button.isEnabled())
      self.assertFalse(pd.form_box.isEnabled())
      self.assertEqual(sorted(pd._editors), ["bonus", "mood", "rival"])
      # Add the block, then set fields: each is an undo step on battle.json.
      self.assertTrue(pd.add_block())
      self.settle()
      battle = w.project.document(self.battle, "capsule.battle/1")
      self.assertEqual(battle.data["parties"][0]["ext"], {SAMPLE_ID: {}})
      self.assertIs(pd.current_document(), battle)
      mood = pd._editors["mood"][0]
      mood.setCurrentText("angry")
      mood.activated.emit(mood.currentIndex())
      self.settle()
      bonus = pd._editors["bonus"][0]
      bonus.setValue(6)
      self.settle()
      self.assertEqual(battle.data["parties"][0]["ext"], {SAMPLE_ID: {"mood": "angry", "bonus": 6}})
      self.assertEqual(pd.problems.text(), "No problems")
      self.assertEqual(pd.preview.toPlainText(), f"{PARTY} fights angry.\nThe AI adds 6 to its scores.")
      self.assertTrue(pd.records.currentItem().text().startswith("●"))
      w.undo()
      self.settle()
      self.assertEqual(battle.data["parties"][0]["ext"], {SAMPLE_ID: {"mood": "angry"}})
      # Its own rival: the connector's validate hook, shown under the form.
      rival = pd._editors["rival"][0]
      rival.setCurrentText(PARTY)
      rival.activated.emit(rival.currentIndex())
      self.settle()
      self.assertIn("its own rival", pd.problems.text())
      rival.setCurrentText(OTHER_PARTY)
      rival.activated.emit(rival.currentIndex())
      self.settle()
      self.assertEqual(pd.problems.text(), "No problems")
      # Cells: the chooser follows the Map tab's map; Go shows a cell without a block.
      mp.select_map("cave")
      self.settle()
      pd.point_box.setCurrentText("cell")
      self.settle()
      self.assertEqual(pd.cell_map.currentText(), "cave")
      pd.choose_cell(-3, -4)
      self.assertEqual(pd.record(), "cave@-3,-4")
      self.assertTrue(pd.add_block())
      self.settle()
      self.assertEqual(w.project.map("cave").data["cell_ext"], {SAMPLE_ID: [{"at": [-3, -4], "mood": "calm"}]})
      self.assertEqual([d for d in w.extensions.validate(w.project, "cave") if d.plugin == SAMPLE_ID], [])
      self.assertTrue(pd.remove_block())
      self.settle()
      self.assertNotIn("cell_ext", w.project.map("cave").data)
      # Export and import with the sample's CSV format.
      pd.point_box.setCurrentText("party")
      self.settle()
      sheet = self.root / "moods.csv"
      self.assertEqual(pd.format_box.count(), 1)
      self.assertTrue(pd.export_file(sheet))
      self.assertIn(f"{PARTY},angry,0,{OTHER_PARTY}", sheet.read_text(encoding="utf-8"))
      sheet.write_text(f"party,mood,bonus,rival\n{PARTY},,,\n{OTHER_PARTY},cheerful,2,\n", encoding="utf-8")
      self.assertTrue(pd.import_file(sheet))
      self.settle()
      self.assertNotIn("ext", battle.data["parties"][0])
      self.assertEqual(battle.data["parties"][1]["ext"], {SAMPLE_ID: {"mood": "cheerful", "bonus": 2}})
      self.assertTrue(w.save_all())
      self.assertEqual(read_json(self.battle)["parties"][1]["ext"], {SAMPLE_ID: {"mood": "cheerful", "bonus": 2}})
      w.close()

   def test_hidden_without_connectors(self) -> None:
      """!A game whose plugins have no connector shows no Plugin data tab.
      @return None
      """
      from capsule_studio.ui.world_shell import WorldWindow
      data = read_json(self.project)
      data["plugins"] = []
      self.project.write_text(json.dumps(data), encoding="utf-8")
      w = WorldWindow(path=str(self.world), host_id=STUDIO_HOSTS)
      self.settle()
      self.assertNotIn("plugin-data", [p.panel_id for p in w.panels])
      w.close()


if __name__ == "__main__":
   unittest.main()
