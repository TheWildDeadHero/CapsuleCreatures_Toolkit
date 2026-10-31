#!/usr/bin/env python3
"""!Smoke tests of the S1 panels: Parties, Presenters and Terms in the battle
editor, the Code page panel in the project settings window, and the Text
panel's underlining of characters the code page lacks. Each opens a copy of
the engine's Starter sample laid out as a game (tests/sample_data.py), edits
through the widgets, undoes and saves. Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtCore = QtWidgets = None

from capsule_studio.core import battle, engine  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from sample_data import make_game  # noqa: E402
from test_battle import add_cast  # noqa: E402


def cast_game(battle_json: Path) -> None:
   """!Saves test_battle.add_cast()'s presenters into a game copy (Ash and Bly present Duo Ash & Bly, Wen fades in
   and stays for Scholar Wen).
   @param battle_json  the copy's battle.json
   @return None
   """
   p = BattleProject.open(battle_json)
   add_cast(p.battle)
   p.save_all()

## A character the engine's ASCII page lacks.
UNMAPPED = "é"


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtBattleTestCase(unittest.TestCase):
   """!Base: a game copy per test and isolated recent-files settings.

   @var root
   The game folder.
   @var battle_json
   Its battle.json.
   """

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
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_battle_"))
      self.battle_json = make_game(self.root)
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs the host's pending refresh (scheduled after each edit).
      @return None
      """
      for _ in range(3):
         self.app.processEvents()

   def window(self, panel_id: str) -> tuple[object, object]:
      """!The battle editor on the copy, with one tab in front.
      @param panel_id  the tab's panel id
      @return (BattleWindow, the panel)
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      w = BattleWindow(None, self.battle_json)
      panel = w.show_panel(panel_id)
      self.settle()
      return w, panel

   def select(self, panel: object, name: str) -> None:
      """!Picks an entry in an entry panel's list.
      @param panel  EntryPanel
      @param name   entry name
      @return None
      """
      panel.entry_list.setCurrentRow(panel.names().index(name))
      self.settle()
      self.assertEqual(panel.selected, name)

   def saved(self) -> dict:
      """!The battle file as saved.
      @return parsed JSON
      """
      return engine.tool("battle_compiler").view_of(self.battle_json)   # both manifests as one

   def close(self, w: QtWidgets.QMainWindow) -> None:
      """!Closes a window without asking about unsaved changes.
      @param w  the window
      @return None
      """
      w._confirm_discard = lambda: True
      w.close()


class PartiesPanelTests(QtBattleTestCase):
   """!The Parties panel (was Trainers)."""

   def test_parties(self) -> None:
      """!Tab title from terms; presenters reorder, detach, attach; rank, reward, escape; undo; save.
      @return None
      """
      cast_game(self.battle_json)
      w, panel = self.window("parties")
      tabs = w.page_titles()
      self.assertIn("Rivals", tabs)        # the Starter calls parties "Rival"
      self.assertIn("Presenters", tabs)
      self.assertIn("Terms", tabs)
      self.assertFalse(hasattr(panel, "picture"))
      self.select(panel, "Duo Ash & Bly")
      self.assertEqual([panel.shown.item(i).text() for i in range(panel.shown.count())], ["Ash", "Bly"])
      self.assertIn("Ash: Duo Ash & Bly wants to battle!", panel.intro.text())
      self.assertEqual(panel.term_label("passive", False, "{} slot").text(), "Talent slot")

      # Reorder: Bly enters first; undo puts Ash back first.
      panel.shown.setCurrentRow(0)
      panel.move_presenter(1)
      self.settle()
      doc = w.project.battle
      self.assertEqual(battle.entry(doc, "parties", "Duo Ash & Bly")["presenters"], ["Bly", "Ash"])
      w.undo()
      self.settle()
      self.assertEqual(battle.entry(doc, "parties", "Duo Ash & Bly")["presenters"], ["Ash", "Bly"])

      # Detach Bly, attach Wen (the choice offers only presenters not shown yet).
      panel.shown.setCurrentRow(1)
      panel.detach_presenter()
      self.settle()
      offered = [panel.presenter_choice.itemText(i) for i in range(panel.presenter_choice.count())]
      self.assertNotIn("Ash", offered)
      panel.presenter_choice.setCurrentIndex(offered.index("Wen"))
      panel.attach_presenter()
      self.settle()
      self.assertEqual(battle.entry(doc, "parties", "Duo Ash & Bly")["presenters"], ["Ash", "Wen"])

      # Reward, rank, escape.
      panel.reward.setValue(77)
      panel.reward.editingFinished.emit()
      self.settle()
      panel.rank.setValue(0)
      panel.rank.editingFinished.emit()
      self.settle()
      panel.escape.setChecked(False)
      self.settle()
      party = battle.entry(doc, "parties", "Duo Ash & Bly")
      self.assertEqual((party["reward"], party["rank"], party["escape"]), (77, 0, False))
      panel.escape.setChecked(True)          # the default: the key goes
      self.settle()
      self.assertNotIn("escape", battle.entry(doc, "parties", "Duo Ash & Bly"))
      self.assertIsNone(w.project.validate())

      # Members: add one, then remove it.
      n = len(party["members"])
      panel.add_member()
      self.settle()
      self.assertEqual(len(battle.entry(doc, "parties", "Duo Ash & Bly")["members"]), n + 1)
      self.assertTrue(w.save_all())
      saved = next(t for t in self.saved()["parties"] if t["name"] == "Duo Ash & Bly")
      self.assertEqual(saved["presenters"], ["Ash", "Wen"])
      self.assertEqual(saved["reward"], 77)
      self.assertNotIn("picture", json.dumps(self.saved()))
      self.close(w)


class PresentersPanelTests(QtBattleTestCase):
   """!The Presenters panel and its preview."""

   def test_presenters(self) -> None:
      """!Sprite picker from the game's assets, motions, texts with checks, the preview track; undo; save.
      @return None
      """
      w, panel = self.window("presenters")
      doc = w.project.battle
      self.select(panel, "Coach")
      sprites = [panel.sprite.itemText(i) for i in range(panel.sprite.count())]
      self.assertIn("sprite:PRESENTER", sprites)
      self.assertEqual(panel.sprite.currentText(), "sprite:PRESENTER")
      self.assertIn("Shown by: Novice Kit", panel.used_by.text())

      # The preview: the entrance from the right edge to the stand, then held.
      from capsule_studio.ui.editors.content.presenters import HOLD_FRAMES
      self.assertEqual(len(panel.frames), 25 + HOLD_FRAMES)
      self.assertEqual(panel.frames[0][:5], (240, 20, 32, 64, 16))
      self.assertEqual(panel.frames[24][:2], (160, 20))
      panel.preview_cue.setCurrentText("Enter, then exit")
      panel.update_preview()
      self.assertEqual(len(panel.frames), 25 + 17 + 2 * HOLD_FRAMES)
      self.assertEqual(panel.frames[-1][4], 0)   # gone at the end
      panel.play()
      self.assertTrue(panel.timer.isActive())
      panel._tick()
      self.assertEqual(panel.frame_index, 1)
      panel.stop()
      self.assertFalse(panel.timer.isActive())

      # The entrance becomes a fade: the slide's edge goes.
      style = panel.motion["enter"]["style"]
      style.setCurrentText("fade")
      style.activated.emit(style.currentIndex())
      self.settle()
      self.assertEqual(battle.entry(doc, "presenters", "Coach")["enter"], {"style": "fade", "frames": 24})
      self.assertFalse(panel.motion["enter"]["from"].isEnabled())
      self.assertEqual(panel.frames[0][4], 0)    # fading in

      # Texts: an unknown placeholder and an unmapped character are named; {@term} reads as the game's word.
      intro = panel.texts["intro"]
      intro.setText("{trainer} " + UNMAPPED)
      intro.textEdited.emit(intro.text())
      note = panel.text_notes["intro"].text()
      self.assertIn("{trainer}", note)
      self.assertIn(UNMAPPED, note)
      intro.setText("{@party} {party}!")
      intro.textEdited.emit(intro.text())
      self.assertEqual(panel.text_notes["intro"].text(), "Reads: Rival Novice Kit!")
      intro.editingFinished.emit()
      self.settle()
      self.assertEqual(battle.entry(doc, "presenters", "Coach")["intro"], "{@party} {party}!")

      # No sprite: text only; undo brings it back.
      panel.sprite.setCurrentIndex(0)
      panel.sprite.activated.emit(0)
      self.settle()
      self.assertNotIn("sprite", battle.entry(doc, "presenters", "Coach"))
      w.undo()
      self.settle()
      self.assertEqual(battle.entry(doc, "presenters", "Coach")["sprite"], "sprite:PRESENTER")
      self.assertIsNone(w.project.validate())
      self.assertTrue(w.save_all())
      saved = next(p for p in self.saved()["presenters"] if p["name"] == "Coach")
      self.assertEqual((saved["enter"]["style"], saved["intro"]), ("fade", "{@party} {party}!"))
      self.close(w)


class TermsPanelTests(QtBattleTestCase):
   """!The Terms panel."""

   def test_terms(self) -> None:
      """!A word and its plural are typed; labels follow; reset and undo; save.
      @return None
      """
      from capsule_studio.ui.editors.structure.terms import CONCEPT_COLUMN, MANY_COLUMN, ONE_COLUMN
      w, panel = self.window("terms")
      doc = w.project.battle
      rows = {panel.table.item(r, CONCEPT_COLUMN).text(): r for r in range(panel.table.rowCount())}
      self.assertEqual(panel.table.item(rows["party"], ONE_COLUMN).text(), "Rival")
      self.assertEqual(panel.table.item(rows["move"], ONE_COLUMN).text(), "Move")
      r = rows["move"]
      panel.table.item(r, ONE_COLUMN).setText("Skill")
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["terms"]["move"], "Skill")
      self.assertIn("Skills", w.page_titles())
      panel.table.item(r, MANY_COLUMN).setText("Skillz")
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["terms"]["move"], {"one": "Skill", "many": "Skillz"})
      panel.table.item(r, MANY_COLUMN).setText("Skills")   # the derived plural: stored as a plain word again
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["terms"]["move"], "Skill")
      panel.table.selectRow(rows["move"])
      panel.reset_selected()
      self.settle()
      self.assertNotIn("move", battle.structure_doc(doc).data["terms"])
      self.assertIn("Moves", w.page_titles())
      w.undo()
      self.settle()
      self.assertEqual(battle.structure_doc(doc).data["terms"]["move"], "Skill")
      self.assertTrue(w.save_all())
      self.assertEqual(self.saved()["terms"]["move"], "Skill")
      self.close(w)


class CodePagePanelTests(QtBattleTestCase):
   """!The Code page panel of the project settings window."""

   def test_codepage(self) -> None:
      """!Own page, a code set and undone, an unmapped character mapped and aliased; save writes both files.
      @return None
      """
      from capsule_studio.ui.project_shell import ProjectWindow
      data = json.loads(self.battle_json.read_text(encoding="utf-8"))
      data["presenters"][0]["defeat"] = "Très bien… {party}!"
      self.battle_json.write_text(json.dumps(data), encoding="utf-8")
      manifest = self.root / "reference" / "project.json"
      w = ProjectWindow(str(manifest))
      w.launch()
      panel = next(p for p in w.panels if p.panel_id == "codepage")
      w.tabs.setCurrentWidget(panel)
      panel.refresh()
      self.settle()
      self.assertIsNone(panel.page_doc)                      # the engine's page: no file of its own yet
      self.assertFalse(panel.own_button.isHidden())
      self.assertEqual(panel.grid.item(4, 1).text(), "A")    # 0x41
      self.assertFalse(panel.grid.item(4, 1).icon().isNull())
      missing = [panel.missing_list.item(i).data(QtCore.Qt.ItemDataRole.UserRole)
                 for i in range(panel.missing_list.count())]
      self.assertEqual(missing, ["è", "…"])

      panel.own_page()
      self.settle()
      self.assertIsNotNone(panel.page_doc)
      self.assertTrue(w.document.dirty)                      # the project names the page now
      self.assertEqual(w.active_document(), panel.page_doc)

      # Code 0x80 gets è (from the list); undo takes it away, redo gives it back.
      panel.grid.setCurrentCell(8, 0)
      panel.missing_list.setCurrentRow(0)
      panel.map_missing()
      self.settle()
      self.assertEqual(panel.page().chars.get(0x80), "è")
      self.assertEqual(panel.grid.item(8, 0).text(), "è")
      w._undo_redo(True)
      self.assertNotIn(0x80, panel.page().chars)
      w._undo_redo(False)
      self.assertEqual(panel.page().chars.get(0x80), "è")

      # The ellipsis folds onto three dots.
      panel.missing_list.setCurrentRow(0)
      self.assertEqual(panel.selected_missing(), "…")
      with mock.patch.object(QtWidgets.QInputDialog, "getText", return_value=("...", True)):
         panel.alias_missing()
      self.settle()
      self.assertEqual(panel.page_doc.data["aliases"]["…"], "...")
      self.assertEqual(panel.aliases.rowCount(), 1)
      self.assertEqual(panel.missing_list.item(0).data(QtCore.Qt.ItemDataRole.UserRole), None)   # none left

      # Typing a character into a code; unset.
      panel.grid.setCurrentCell(8, 1)
      panel.char_edit.setText("ü")
      panel.set_char()
      self.assertEqual(panel.page().chars.get(0x81), "ü")
      panel.unset_char()
      self.assertNotIn(0x81, panel.page().chars)

      self.assertTrue(w.save())
      page_file = self.root / "data" / "text" / "en.codepage.json"
      saved = json.loads(page_file.read_text(encoding="utf-8"))
      self.assertEqual(saved["map"]["0x80"], "è")
      self.assertEqual(saved["aliases"], {"…": "..."})
      self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["text"]["code_pages"]["en"],
                       "data/text/en.codepage.json")
      self.assertFalse(any(d.dirty for d in w.documents()))
      w.close()


class TextPanelTests(QtBattleTestCase):
   """!The Text panel checks and underlines with the game's code page."""

   def test_unicode_text(self) -> None:
      """!Any Unicode can be typed; characters the page lacks are underlined and named; the text saves.
      @return None
      """
      from capsule_studio.ui.editors.text import TextPanel
      from capsule_studio.ui.shell import EditorWindow
      w = EditorWindow([TextPanel], self.root / "data" / "assets.json")
      panel = w.panels[0]
      self.assertTrue(w.run_edit("New text", lambda: w.document.add_asset(
         {"key": "text:HELLO", "kind": "text", "text": ""})))
      panel.key = "text:HELLO"
      panel.refresh()
      panel.edit.setPlainText("h" + UNMAPPED + "llo")
      panel.commit.flush()
      self.settle()
      self.assertEqual(w.document.find("text:HELLO")["text"], "h" + UNMAPPED + "llo")
      self.assertIn(repr(UNMAPPED), panel.checks.text())
      block = panel.edit.document().firstBlock()
      marks = [(r.start, r.length) for r in block.layout().formats()
               if r.format.underlineStyle() != r.format.UnderlineStyle.NoUnderline]
      self.assertEqual(marks, [(1, 1)])
      w.document.dirty = False
      w.close()


class ConditionRecordTests(QtBattleTestCase):
   """!E5 sections (S5f): volatiles, side / field conditions and move flags survive the studio; failed opens
   never wait for a click."""

   def test_sections_round_trip(self) -> None:
      """!Edits elsewhere and a save keep the new sections exactly; the Data page no longer shows the sections
      that have their own pages (S5b).
      @return None
      """
      keys = ("volatiles", "side_conditions", "field_conditions", "move_flags", "rules")
      before = {k: engine.tool("battle_compiler").view_of(self.battle_json).get(k) for k in keys}
      w, panel = self.window("data")
      for own_page in ("volatiles", "side_conditions", "field_conditions", "move_flags", "statuses", "weathers",
                       "categories", "passives", "items"):
         self.assertEqual(panel.what.findText(own_page), -1, own_page)
      panel.what.setCurrentIndex(panel.what.findText("rules"))
      self.settle()
      self.assertFalse(panel.json.text.isReadOnly())
      moves = w.show_panel("moves")
      self.settle()
      first = moves.names()[0]
      self.select(moves, first)
      self.assertTrue(w.run_edit("Power", lambda: battle.set_field(w.project.battle, "moves", first, "power", 45),
                                 w.project.battle))
      self.assertTrue(w.save_all())
      saved = self.saved()
      self.assertEqual({k: saved.get(k) for k in keys}, before)
      self.close(w)

   def test_move_flags_follow_the_manifest(self) -> None:
      """!One box per declared move flag; toggling one keeps flags the manifest lacks.
      @return None
      """
      w, panel = self.window("moves")
      declared = w.project.structure.data["move_flags"]
      self.assertEqual(list(panel.flags), declared)
      self.select(panel, "Harden")
      self.assertFalse(panel.flags["protect"].isChecked())
      self.select(panel, "Strike")
      self.assertTrue(panel.flags["protect"].isChecked())
      strike = w.project.entry("moves", "Strike")
      with w.project.battle.edit("Odd flag"):
         strike["flags"] = ["protect", "custom_flag"]
      panel.refresh()
      panel.flags["contact"].setChecked(True)
      self.settle()
      self.assertEqual(w.project.entry("moves", "Strike")["flags"], ["contact", "protect", "custom_flag"])
      self.close(w)

   def test_open_failure_does_not_wait(self) -> None:
      """!Battle data that does not compile or open is reported in the status bar and open_error (headless: no
      modal box), and the window stays usable.
      @return None
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      broken = self.root / "data" / "broken.json"
      broken.write_text("{", encoding="utf-8")
      w = BattleWindow(None, None)
      with self.assertLogs("capsule_studio", "WARNING") as logged:
         w.open_battle(broken)
      self.assertIn("broken.json", w.open_error)
      self.assertIn("Open battle data", logged.output[0])
      self.assertIsNone(w.project)
      w.open_battle(self.battle_json)
      self.settle()
      self.assertIsNone(w.open_error)
      self.assertIsNotNone(w.project)
      self.close(w)


if __name__ == "__main__":
   unittest.main()
