#!/usr/bin/env python3
"""!The I4 editors' windows on a large imported game [S2] (Qt, offscreen): skipped unless CAPSULE_IMPORTED_CONTENT
names an importer's output folder for one game (see test_i4_content.py). Nothing is saved there. Times are printed
(stderr). With CAPSULE_SHOTS=FOLDER the tests save pictures: the script editor on a map's script, the text table
editor with a fit warning (a line typed too long, not saved), the font viewer, the text box style editor
(S4: CAPSULE_TEXT_BOX_STYLE=KEY: the text_box asset shown, else the manifest's first; a new style when it has none).
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # the sibling test helpers (V2 finding)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

from test_i4_content import CONTENT, CONTENT_ENV, SLOW_SECONDS, timed  # noqa: E402

## Folder of the pictures, or None.
SHOTS = Path(os.environ["CAPSULE_SHOTS"]) if os.environ.get("CAPSULE_SHOTS") else None
## S4: the text box style shown (a text_box asset's key), or None (the first).
STYLE_KEY = os.environ.get("CAPSULE_TEXT_BOX_STYLE")
## Size of the windows in the pictures.
SHOT_SIZE = (1500, 900)
## The script shown (a map's source; the first source when the game has no such file).
## The imported map whose script and table are shown (CAPSULE_IMPORTED_MAP; an invented default).
IMPORTED_MAP = os.environ.get("CAPSULE_IMPORTED_MAP", "StarterTown")
SCRIPT_SOURCE = f"maps/{IMPORTED_MAP}.cscript"
## The table shown (the first table when the game has no such file).
TABLE_NAME = f"{IMPORTED_MAP}.json"
## The font shown (the first font otherwise).
FONT_NAME = "normal.font.json"
## Characters typed onto a text's first line to make it wider than its box.
TOO_LONG = " and a few more words than the box holds"


@unittest.skipIf(QtWidgets is None or CONTENT is None, f"needs PySide6 and {CONTENT_ENV}")
class ImportedContentQtTests(unittest.TestCase):
   """!The windows on the content."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def settle(self) -> None:
      """!Runs pending events.
      @return None
      """
      for _ in range(3):
         self.app.processEvents()

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

   def test_script_editor(self) -> None:
      """!The script editor opens and checks the game's scripts.
      @return None
      """
      from capsule_studio.ui.script_shell import ScriptWindow
      t = time.perf_counter()
      w = ScriptWindow(CONTENT / "world" / "scripts" / "scripts.json")
      w.resize(*SHOT_SIZE)
      w.show()
      self.settle()
      self.assertLess(timed("script editor: open and check", t), SLOW_SECONDS)
      self.assertTrue(w.result.ok)
      rel = SCRIPT_SOURCE if SCRIPT_SOURCE in w.editors else w.project.sources[0]
      ed = w.editors[rel]
      w.tabs.setCurrentWidget(ed)
      at = ed.toPlainText().find("lock")
      line = ed.toPlainText().count("\n", 0, max(at, 0)) + 1
      ed.go_to(line)
      for i in range(w.outline.topLevelItemCount()):
         item = w.outline.topLevelItem(i)
         item.setExpanded(item.text(0) in ("Maps", "Route steps"))
      t = time.perf_counter()
      w.check()
      timed("script editor: check again", t)
      self.shot(w, "script_editor_imported")
      self.assertFalse(w.project.dirty)
      w.close()

   def test_text_panels(self) -> None:
      """!The text table editor with a fit warning, the font viewer, the text box style editor.
      @return None
      """
      from capsule_studio.core import text_boxes
      from capsule_studio.ui.shell import EditorWindow
      t = time.perf_counter()
      w = EditorWindow(path=CONTENT / "text" / "text_assets.json")
      w.resize(*SHOT_SIZE)
      w.show()
      self.settle()
      timed("scene editor: open the text manifest", t)
      tables, fonts, boxes = (next(p for p in w.panels if p.panel_id == pid)
                              for pid in ("text_tables", "fonts", "text_boxes"))
      w.tabs.setCurrentWidget(tables)
      t = time.perf_counter()
      tables.refresh()
      timed("text tables: refresh", t)
      paths = [tables.table.itemData(i) for i in range(tables.table.count())]
      chosen = next((i for i, p in enumerate(paths) if Path(p).name == TABLE_NAME), 0)
      tables.table.setCurrentIndex(chosen)
      self.settle()
      text = tables.edit.toPlainText()
      first = text.find("\n")
      tables.edit.setPlainText(text[:first] + TOO_LONG + text[first:] if first >= 0 else text + TOO_LONG)
      self.settle()
      self.assertIn("wider than the box", tables.verdict.text())
      self.shot(w, "text_tables_fit_warning")
      tables.edit.setPlainText(text)   # back as it was: nothing to save
      tables.commit.flush()
      w.tabs.setCurrentWidget(fonts)
      paths = [fonts.font_combo.itemData(i) for i in range(fonts.font_combo.count())]
      fonts.font_combo.setCurrentIndex(next((i for i, p in enumerate(paths) if Path(p).name == FONT_NAME), 0))
      fonts.select_glyph("A")
      fonts.sample.setText("MOM: We're here, honey!")
      self.settle()
      self.assertIn("Compiles", fonts.verdict.text())
      self.shot(w, "font_viewer_normal")
      w.tabs.setCurrentWidget(boxes)
      doc = w.document
      added = not text_boxes.styles(doc)
      if added:   # a game without styles: one for the picture only
         with doc.edit("shot"):
            text_boxes.add_style(doc, "MESSAGE")
      boxes.refresh()
      keys = text_boxes.keys(doc)
      boxes.key = STYLE_KEY if STYLE_KEY in keys else keys[0]
      boxes.refresh()
      paths = [boxes.table_box.itemData(i) for i in range(boxes.table_box.count())]
      boxes.table_box.setCurrentIndex(next((i for i, p in enumerate(paths) if Path(p).name == TABLE_NAME), 0))
      keys = [boxes.text_key.itemText(i) for i in range(boxes.text_key.count())]
      wanted = next((k for k in keys if "OurNewHome" in k), keys[-1])
      boxes.text_key.setCurrentText(wanted)
      t = time.perf_counter()
      boxes._update_preview(True)
      timed("text boxes: type the text", t)
      self.settle()
      self.shot(w, "text_box_style")
      self.assertTrue(boxes.view.image is not None)
      if added:
         doc.undo()   # the style was for the picture only
         self.assertEqual(text_boxes.styles(doc), [])
      doc.dirty = False   # nothing to save (a Document stays marked after an undo)
      w.close()


if __name__ == "__main__":
   unittest.main()
