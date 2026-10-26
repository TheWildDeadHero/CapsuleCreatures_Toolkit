#!/usr/bin/env python3
"""!Smoke tests of the S5c field pages: the World page's Levels and Movement
modes panels (core.field_rules) on a copy of the map sandbox, and the
script editor's Placeholders tab (core.placeholders) on a small scripts
manifest. Edits go through the widgets, one undo step each. Skipped when
PySide6 is missing; uses Qt's offscreen platform.
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

from capsule_studio.core import field_rules  # noqa: E402
from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402
from test_placeholders import MANIFEST, SOURCE  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402

## Highest level number.
TOP_LEVEL = 15


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtFieldTests(unittest.TestCase):
   """!The world's field rules and the scripts' placeholders."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies the sandbox world and writes a scripts manifest.
      @return None
      """
      ## Temporary root.
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_qt_field_")), ["sandbox_map"])
      ## The copy's world.json.
      self.world = self.root / "sandbox_map" / "data" / "world.json"
      scripts = self.root / "scripts"
      scripts.mkdir()
      (scripts / "main.cscript").write_text(SOURCE, encoding="utf-8")
      (scripts / "scripts.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
      ## The scripts manifest.
      self.manifest = scripts / "scripts.json"
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

   def test_levels_and_modes(self) -> None:
      """!Level rename and on-arrive; a mode added, set, renamed; undo; saved.
      @return None
      """
      from capsule_studio.ui.editors.field_rules import LEVEL_COLUMN, LevelsPanel, ModesPanel
      from capsule_studio.ui.world_shell import WorldWindow
      w = WorldWindow(path=str(self.world), host_id=STUDIO_HOSTS)
      w.show()
      self.settle()
      levels = next(p for p in w.panels if isinstance(p, LevelsPanel))
      modes = next(p for p in w.panels if isinstance(p, ModesPanel))
      w.tabs.setCurrentWidget(levels)
      self.settle()
      self.assertEqual(levels.table.rowCount(), TOP_LEVEL + 1)
      levels.table.item(TOP_LEVEL, LEVEL_COLUMN["name"]).setText("overpass")
      self.settle()
      self.assertEqual(w.project.world.data["elevations"][TOP_LEVEL]["name"], "overpass")
      levels.table.item(3, LEVEL_COLUMN["meets"]).setText("overpass, 4")
      self.settle()
      self.assertEqual(w.project.world.data["elevations"][3]["meets"], ["overpass", 4])
      self.assertEqual(levels.table.item(3, LEVEL_COLUMN["met"]).text(), "3, 4, 15")
      self.assertTrue(levels.set_level(2, "on_arrive", "keep"))
      self.settle()
      w.undo()
      self.settle()
      self.assertEqual(w.project.world.data["elevations"][2]["on_arrive"], "take")
      w.tabs.setCurrentWidget(modes)
      self.settle()
      self.assertEqual(modes.modes.count(), 2)
      self.assertTrue(modes.add_mode("bike"))
      self.settle()
      self.assertEqual(modes.selected, "bike")
      self.assertTrue(modes.set_mode("walk", 2))
      self.settle()
      self.assertEqual(modes.speed["walk"].currentText(), "2")
      self.assertFalse(modes.set_mode("first_animation", 1))   # refused: not a multiple of the set size
      self.settle()
      modes.modes.setCurrentRow(1)
      self.settle()
      self.assertTrue(modes.rename_mode("boat"))
      self.settle()
      self.assertEqual(field_rules.mode_names(w.project.world), ["foot", "boat", "bike"])
      self.assertIn("water", modes.enters.text())
      self.assertTrue(w.save_all())
      saved = json.loads(self.world.read_text(encoding="utf-8"))
      self.assertEqual(saved["encounter_methods"][1]["vehicles"], ["boat"])
      self.assertEqual(saved["elevations"][TOP_LEVEL]["name"], "overpass")
      w.close()

   def test_placeholders_tab(self) -> None:
      """!Add, rename (the editor's text follows), undo through Edit > Undo, a term; saved.
      @return None
      """
      from capsule_studio.ui.script_shell import ScriptWindow
      w = ScriptWindow(str(self.manifest))
      w.launch()
      self.settle()
      panel = w.placeholders
      w.side_tabs.setCurrentWidget(panel)
      self.settle()
      self.assertEqual(panel.table.rowCount(), 1)
      self.assertTrue(panel.markup.isChecked())
      self.assertTrue(panel.add_placeholder("money", "var", "coins"))
      self.settle()
      self.assertEqual(panel.table.rowCount(), 2)
      self.assertTrue(panel.rename_placeholder("player", "hero"))
      self.settle()
      self.assertIn("{hero}", w.editors["main.cscript"].toPlainText())
      self.assertFalse(panel.remove_placeholder("hero"))   # still used
      self.assertIn("still used", w.statusBar().currentMessage())
      w.undo_action.trigger()
      self.settle()
      self.assertIn("{player}", w.editors["main.cscript"].toPlainText())
      self.assertTrue(panel.set_term("rival", "Mira", "Miras"))
      self.settle()
      self.assertEqual(panel.terms.item(0, 2).text(), "Miras")
      self.assertTrue(w.save_all())
      saved = json.loads(self.manifest.read_text(encoding="utf-8"))
      self.assertEqual(list(saved["placeholders"]), ["player", "money"])
      self.assertEqual(saved["terms"]["rival"], {"one": "Mira", "many": "Miras"})
      w._confirm_discard = lambda: True
      w.close()


if __name__ == "__main__":
   unittest.main()
