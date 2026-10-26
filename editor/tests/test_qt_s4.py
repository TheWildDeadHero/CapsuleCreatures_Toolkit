#!/usr/bin/env python3
"""!S4 (engine C10) Qt panels on copies of the engine's C10 and D-30 fixtures: the Events tab's Runs row (an
immediate trigger, a waiting script refused with a message), the text tables panel's Languages box (en and fr side
by side, the missing key, the fallback's text), the Manifest panel's build language and fallback, the script
editor's vm switches and session lifetime, and the Doors tab's sound check. Skipped when PySide6 is missing; uses
Qt's offscreen platform. With CAPSULE_SHOTS=FOLDER it saves pictures of the Events tab and the Languages box.
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

from capsule_studio.core import engine, events  # noqa: E402
from capsule_studio.plugins.registry import STUDIO_HOSTS  # noqa: E402

## Folder of the pictures, or None.
SHOTS = Path(os.environ["CAPSULE_SHOTS"]) if os.environ.get("CAPSULE_SHOTS") else None
## Size of the windows in the pictures.
SHOT_SIZE = (1500, 900)
## The C10 map with the triggers, and its immediate trigger's index.
PLAIN, IMMEDIATE = "plain", 0
## A fixture script that waits.
WAITING_SCRIPT = "pauses"
## The key only the English table has.
ONLY_EN = "text:C10.ONLY_EN"


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtS4Tests(unittest.TestCase):
   """!Drives the S4 panels."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication for the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Copies tests/data/c10 and tests/data/d30.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_s4_"))
      data = engine.root() / "tests" / "data"
      for name in ("c10", "d30"):
         shutil.copytree(data / name, self.root / name)
      ## The C10 fixture's folder.
      self.c10 = self.root / "c10"
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events.
      @return None
      """
      for _ in range(3):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def shot(self, w: QtWidgets.QWidget, name: str) -> None:
      """!Saves a picture of a window when CAPSULE_SHOTS names a folder.
      @param w     the window
      @param name  file stem
      @return None
      """
      if SHOTS is None:
         return
      SHOTS.mkdir(parents=True, exist_ok=True)
      self.settle()
      w.grab().save(str(SHOTS / f"{name}.png"))

   def test_events_runs_row(self) -> None:
      """!The Events tab shows the immediate trigger's run, refuses a waiting script with a message, and sets run.
      @return None
      """
      from capsule_studio.ui.world_shell import WORLD_PANELS, WorldWindow
      w = WorldWindow(WORLD_PANELS, str(self.c10 / "world.json"), STUDIO_HOSTS, "World")
      w.resize(*SHOT_SIZE)
      w.show()
      self.settle()
      mp = next(p for p in w.panels if p.panel_id == "map")
      mp.select_map(PLAIN)
      self.settle()
      ev = next(p for p in w.panels if p.panel_id == "events")
      w.tabs.setCurrentWidget(ev)
      self.settle()
      index = next(i for i in range(ev.tree.topLevelItemCount())
                   if ev.tree.topLevelItem(i).text(0) == f"trigger {IMMEDIATE}")
      ev.tree.setCurrentItem(ev.tree.topLevelItem(index))
      self.settle()
      self.assertEqual(ev.selected()[:2], ("triggers", IMMEDIATE))
      self.assertEqual(ev.run_box.currentText(), "immediate")
      self.assertTrue(ev.run_box.isVisible())
      self.assertFalse(ev.run_problem.isVisible())
      self.shot(w, "event_editor_immediate_trigger")
      ev.script.setCurrentText(WAITING_SCRIPT)
      ev._set(script=WAITING_SCRIPT)
      self.settle()
      ev.tree.setCurrentItem(ev.tree.topLevelItem(index))
      self.settle()
      self.assertIn("may wait", ev.run_problem.text())
      self.assertTrue(ev.run_problem.isVisible())
      self.shot(w, "event_editor_immediate_refused")
      ev.run_box.setCurrentText("step")
      ev.run_box.activated.emit(ev.run_box.currentIndex())
      self.settle()
      self.assertNotIn("run", events.events(w.project.map(PLAIN), "triggers")[IMMEDIATE])
      w._confirm_discard = lambda: True
      w.close()

   def test_languages_and_manifest(self) -> None:
      """!The Languages box puts en and fr side by side, marks the missing key with the fallback's text; the
      Manifest panel sets the build language and refuses an unknown fallback.
      @return None
      """
      from capsule_studio.core import asset_tables
      from capsule_studio.ui.editors.manifest import ManifestPanel
      from capsule_studio.ui.editors.text_tables import FALLBACK_COLOR, TextTablesPanel
      from capsule_studio.ui.shell import EditorWindow
      e = EditorWindow([TextTablesPanel, ManifestPanel], self.c10 / "assets.json")
      e.resize(*SHOT_SIZE)
      e.show()
      self.settle()
      tables, manifest = e.panels
      fr = next(i for i in range(tables.table.count()) if tables.table.itemData(i).endswith("fr.json"))
      tables.table.setCurrentIndex(fr)
      self.settle()
      headers = [tables.grid.horizontalHeaderItem(c).text() for c in range(tables.grid.columnCount())]
      self.assertEqual(headers, ["Key", "en (build)", "fr"])
      en = next(i for i in range(tables.table.count()) if tables.table.itemData(i).endswith("en.json"))
      tables.table.setCurrentIndex(en)
      self.settle()
      keys = [tables.grid.item(r, 0).text() for r in range(tables.grid.rowCount())]
      row = keys.index(ONLY_EN)
      cell = tables.grid.item(row, 2)
      self.assertTrue(cell.text().startswith("(en)"), cell.text())   # fr takes the fallback's text
      self.assertEqual(cell.foreground().color().name(), FALLBACK_COLOR)
      self.assertIn("fr lacks 1 keys (1 from en)", tables.missing.text())
      self.shot(e, "text_tables_two_languages")
      e.tabs.setCurrentWidget(manifest)
      manifest.refresh()
      self.settle()
      boxes = manifest.language_boxes
      self.assertEqual([boxes["language"].itemText(i) for i in range(boxes["language"].count())],
                       ["(not set)", "en", "fr"])
      self.assertTrue(manifest.set_language("language", "fr"))
      self.assertEqual(asset_tables.language_setting(e.document, "language"), "fr")
      self.assertIn("A build takes fr", manifest.language_verdict.text())
      self.assertFalse(manifest.set_language("fallback_language", "de"))
      self.shot(e, "manifest_languages")
      for d in [e.document] + e.extra_documents():
         d.dirty = False
      e.close()

   def test_script_settings(self) -> None:
      """!The script editor shows the manifest's vm switches; one changed back to the engine's own is left out.
      @return None
      """
      from capsule_studio.ui.script_shell import ScriptWindow
      s = ScriptWindow(str(self.c10 / "scripts" / "scripts.json"))
      s.show()
      self.settle()
      self.assertEqual(s.vm_boxes["resume"].currentText(), "next_frame")
      self.assertEqual(s.vm_boxes["vars"].currentText(), "wrap")
      s.vm_boxes["resume"].setCurrentIndex(0)
      s._settings_changed()
      self.assertEqual(s.project.setting("vm"), {"random": "modulo", "vars": "wrap"})
      self.assertIn("session", s.completions("flag f : "))
      s._confirm_discard = lambda: True
      s.close()

   def test_door_sounds(self) -> None:
      """!The Doors tab says the gate's sounds name no sound of the game.
      @return None
      """
      from capsule_studio.ui.shell import EditorWindow
      e = EditorWindow(None, str(self.root / "d30" / "assets.json"))
      e.show()
      self.settle()
      dp = next(p for p in e.panels if p.panel_id == "doors")
      e.tabs.setCurrentWidget(dp)
      dp.key = "door:GATE"
      dp.refresh()
      self.settle()
      self.assertIn("no such sound", dp.sound_check.text())
      e.document.dirty = False
      e.close()


if __name__ == "__main__":
   unittest.main()
