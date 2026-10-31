#!/usr/bin/env python3
"""!The I4 text panels of the scene editor [S2] (Qt, offscreen; skipped without PySide6): Text tables (typing
fitted by the engine's rule, wrap / font, the other language, Insert, Add / Rename / Remove), Fonts (glyph grid,
a stroke as one edit, metrics, preview; the tables fitted with the edited font), Text boxes (S4: text_box assets,
settings from the engine, the typed preview, colours, Font control fonts, Apply to table) and Manifest (includes,
tables, the engine's check); the window's
Undo / Redo on a panel's own Document and Save of the tables and fonts it changed. Uses text_fixture.py's game.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))   # the sibling test helpers (V2 finding)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

import text_fixture as fx  # noqa: E402


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class TextPanelTests(unittest.TestCase):
   """!The four panels on the fixture game."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def setUp(self) -> None:
      """!Writes the game and opens the window.
      @return None
      """
      from capsule_studio.ui.editors.fonts import FontPanel
      from capsule_studio.ui.editors.manifest import ManifestPanel
      from capsule_studio.ui.editors.text_boxes import TextBoxPanel
      from capsule_studio.ui.editors.text_tables import TextTablesPanel
      from capsule_studio.ui.shell import EditorWindow
      ## Temporary folder.
      self.tmp = Path(tempfile.mkdtemp(prefix="capsule_qt_i4_"))
      ## The game.
      self.game = fx.make_game(self.tmp)
      ## The window.
      self.w = EditorWindow([TextTablesPanel, FontPanel, TextBoxPanel, ManifestPanel], self.game.assets)
      self.w.show()
      self.settle()
      self.tables, self.fonts, self.boxes, self.manifest = self.w.panels

   def tearDown(self) -> None:
      """!Closes the window without asking and removes the folder.
      @return None
      """
      for d in [self.w.document] + self.w.extra_documents():
         d.dirty = False
      self.w.close()
      shutil.rmtree(self.tmp, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events.
      @return None
      """
      for _ in range(3):
         self.app.processEvents()

   def choose(self, key: str) -> None:
      """!Shows a text of the table panel.
      @param key  its key
      @return None
      """
      p = self.tables
      for i in range(p.list.count()):
         if p.list.item(i).data(QtCore.Qt.ItemDataRole.UserRole) == key:
            p.list.setCurrentRow(i)
      self.settle()
      p._switch_to(key)

   def test_text_tables(self) -> None:
      """!The fit as typed, commit, undo through the window, the other language, wrap, Insert, add / rename / remove,
      save keeping the layout.
      @return None
      """
      p = self.tables
      self.assertEqual(p.table.count(), 2)   # the listed table and its German translation
      self.assertIn("1 lines wider", p.summary.text())
      self.choose("text:Main.Long")
      self.assertIn("wider than the box", p.verdict.text())
      self.assertEqual(p.lines.topLevelItemCount(), 2)
      p.edit.setPlainText("Short line\nshort too")
      self.assertEqual(p.verdict.text(), "Fits the box.")
      p.commit.flush()
      doc = p.table_doc()
      self.assertTrue(doc.dirty)
      self.assertTrue(self.w.unsaved())
      self.assertIs(self.w.active_document(), doc)
      self.w.undo()
      self.assertEqual(doc.data["texts"]["text:Main.Long"]["text"], fx.EN_TEXTS["text:Main.Long"]["text"])
      self.w.redo()
      self.choose("text:Main.Greeting")
      self.assertIn("[de] Hallo", p.others.text())
      p.wrap.setCurrentText("auto")
      self.assertEqual(doc.data["texts"]["text:Main.Greeting"]["wrap"], "auto")
      p.insert_markup("{pause:15}")
      self.assertIn("{pause:15}", p.edit.toPlainText())
      p.commit.flush()
      p.add_text("text:Main.Added")
      p.rename_text("text:Main.Renamed")
      self.assertEqual(p.key, "text:Main.Renamed")
      p.remove_text()
      self.assertNotIn("text:Main.Renamed", doc.data["texts"])
      before = self.game.assets.read_bytes()
      self.assertTrue(self.w.save_file())
      self.assertEqual(self.game.assets.read_bytes(), before)   # the manifest did not change: not rewritten
      text = self.game.en.read_text(encoding="utf-8")
      self.assertIn("short too", text)
      self.assertEqual(text, json.dumps(json.loads(text), indent=1, ensure_ascii=False) + "\n")   # layout kept
      self.assertFalse(self.w.unsaved())

   def test_fonts(self) -> None:
      """!The glyph grid, a stroke as one edit, the width, the preview; the table fitted with the edited font.
      @return None
      """
      p = self.fonts
      self.assertEqual(p.grid.count(), fx.LAST_CODE - fx.FIRST_CODE + 1)
      self.assertIn("Compiles", p.verdict.text())
      self.assertIsNotNone(p.view.image)
      self.assertTrue(p.select_glyph("W"))
      rows = list(p.canvas.rows)
      rows[0] = "3" + rows[0][1:]
      p.stroke_done(rows)
      doc = p.font_doc()
      self.assertEqual(doc.data["glyphs"]["W"]["rows"][0][0], "3")
      self.assertEqual(doc.undo_label(), "Paint glyph")
      p.width_spin.setValue(1)
      p._width_changed()
      self.assertEqual(doc.data["glyphs"]["W"]["width"], 1)
      self.tables._count_table()
      self.assertIn("0 lines wider", self.tables.summary.text())   # W is narrow now: the long line fits
      p.line_height.setValue(fx.LINE_HEIGHT + 1)
      p._metric_changed("line_height", p.line_height)
      self.assertEqual(doc.data["line_height"], fx.LINE_HEIGHT + 1)
      self.assertTrue(self.w.save_file())
      self.assertEqual(json.loads(self.game.font.read_text(encoding="utf-8"))["glyphs"]["W"]["width"], 1)

   def test_text_boxes(self) -> None:
      """!A style (S4: a text_box asset): its fields from the engine, a change, the typed preview at a frame, a
      colour, a Font control font, Apply to table, undo.
      @return None
      """
      from capsule_studio.core import text_boxes
      p = self.boxes
      key = "text_box:MESSAGE"
      self.assertEqual({k for k in p.editors}, {(f.group, f.name) for f in text_boxes.config_fields()})
      p.add_style("MESSAGE")
      self.assertEqual(p.key, key)
      self.assertEqual(text_boxes.find(self.w.document, key)["font"], "font:BODY")
      spin = p.editors[("frame", "pad_left")]
      spin.setValue(2)
      p._changed("frame", "pad_left")
      self.assertEqual(text_boxes.find(self.w.document, key)["frame"]["pad_left"], 2)
      combo = p.editors[("window", "typing")]
      combo.setCurrentText("counter")
      p._changed("window", "typing")
      self.assertEqual(text_boxes.find(self.w.document, key)["window"]["typing"], "counter")
      arrow = p.editors[("window", "arrow")]
      self.assertEqual(arrow.value(), arrow.minimum())   # left out: no arrow
      self.assertEqual(p.view.image.width(), 240)
      self.assertGreater(p.frame.maximum(), 0)   # the sample text typed frame by frame
      p.frame.setValue(1)
      self.assertEqual(p.frame_label.text(), f"1 / {p.frame.maximum()}")
      self.assertTrue(p.set_control_font(3, "font:BODY"))
      self.assertEqual(text_boxes.control_fonts(text_boxes.find(self.w.document, key)), {3: "font:BODY"})
      self.assertTrue(p.set_color(1, (10, 20, 30)))
      self.assertEqual(text_boxes.preview_data(text_boxes.find(self.w.document, key))["colors"][1], "#0a141e")
      self.assertTrue(p.apply_to_table(self.game.en))
      table = self.tables.session().table(self.game.en)
      self.assertEqual(table.data["box"]["width"], text_boxes.fit_box(p.style(), None)["width"])
      self.w.undo()   # the active panel is the first: its table
      self.w.tabs.setCurrentIndex(2)
      self.w.undo()   # the text box panel: the manifest
      self.assertEqual(text_boxes.preview_data(text_boxes.find(self.w.document, key))["colors"][1], "#f8f8f8")

   def test_manifest(self) -> None:
      """!Includes and tables lists, the engine's check.
      @return None
      """
      from capsule_studio.core import manifest_io
      p = self.manifest
      self.assertEqual(p.lists["text_tables"].count(), 1)
      self.assertIn("1 tables listed, 1 translations", p.reached.text())
      fit = p.check()
      self.assertEqual(fit["over"], 1)
      other = self.game.root / "other.json"
      manifest_io.save(other, {"schema": "capsule.assets/1", "id": "other", "assets": []})
      self.assertTrue(p.add_entry("includes", other))
      self.assertEqual(p.lists["includes"].count(), 1)
      p.lists["includes"].setCurrentRow(0)
      self.assertTrue(p.remove_entry("includes"))
      self.assertFalse(p.add_entry("text_tables", other))   # not a table


if __name__ == "__main__":
   unittest.main()
