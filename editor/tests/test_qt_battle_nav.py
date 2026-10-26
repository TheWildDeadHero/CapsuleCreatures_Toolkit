#!/usr/bin/env python3
"""!Smoke tests of the battle editor's navigator (S2, D-23 §3.1): the
Content, Structure and Logic groups and every page in them, the
battle-structure and battle-logic entry points, the Text page's way to the
code page, and the Studio's Battle page with the same navigator. Skipped
when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_qt_battle import QtBattleTestCase, QtWidgets  # noqa: E402

## The studio repository (launchers, toolkit, .gitattributes).
REPO = Path(__file__).resolve().parent.parent.parent


class NavigatorTests(QtBattleTestCase):
   """!The navigator of a battle editor window."""

   def test_groups_and_pages(self) -> None:
      """!Three groups in order; every page opens in front with its group; titles follow the game's words;
      planned pages say who builds them and edit nothing.
      @return None
      """
      from capsule_studio.ui.battle_shell import BATTLE_PANELS, NAV_GROUPS, BattleWindow
      from capsule_studio.ui.editors.battle_common import PlannedPanel
      w = BattleWindow(None, self.battle_json)
      w.show()
      self.settle()
      self.assertEqual([w.nav.topLevelItem(i).text(0) for i in range(w.nav.topLevelItemCount())],
                       ["Content", "Structure", "Logic"])
      self.assertEqual([type(p) for p in w.panels], BATTLE_PANELS)
      ids = {gid: [c.panel_id for c in classes] for gid, _title, classes in NAV_GROUPS}
      self.assertEqual(ids["content"], ["species", "moves", "types", "parties", "presenters", "passives_items",
                                        "test_save", "messages", "data"])
      self.assertEqual(ids["structure"], ["record", "stats", "resources", "passive_slots", "species_fields",
                                          "pockets", "recruit", "storage", "stages", "categories", "chart", "flags",
                                          "conditions", "delayed_hits", "formats", "turn", "progression",
                                          "growth_training", "field_effects",
                                          "encounter_rules", "field_actions", "step_effects", "combination", "nursery",
                                          "terms",
                                          "text"])
      self.assertEqual(ids["logic"], ["effects", "rules", "pipelines", "ai", "bench"])
      for gid, panel_ids in ids.items():
         for pid in panel_ids:
            panel = w.show_panel(pid)
            self.settle()
            self.assertIs(w.active_panel(), panel, pid)
            self.assertIs(w.stack.currentWidget(), panel, pid)
            self.assertEqual(w.group_of(panel), gid, pid)
            self.assertTrue(w.group_items[gid].isExpanded(), pid)
            self.assertTrue(panel.isVisible(), pid)
            if isinstance(panel, PlannedPanel):
               self.assertIsNone(w.document, pid)          # Undo / Redo / Save stay off
               self.assertFalse(w.undo_action.isEnabled(), pid)
               self.assertIn("Not built yet: ", panel.text.text(), pid)
               self.assertRegex(panel.text.text(), r"S\d", pid)   # names a work package
      self.assertIs(w.show_panel("rules").current_document(), w.project.ruleset)
      self.settle()
      self.assertIs(w.document, w.project.ruleset)          # the Formulas page edits the ruleset
      self.assertIs(w.show_panel("species").current_document(), w.project.battle)
      titles = w.page_titles()
      self.assertIn("Rivals", titles)                        # the Starter calls parties "Rival"
      passives = w.show_panel("passives_items")
      self.assertEqual(w.page_title(passives), passives.tab_title())
      self.assertIn(" / ", w.page_title(passives))
      self.assertIn("rules", [p.panel_id for p in w.panels if w.group_of(p) == "logic"])
      with self.assertRaises(KeyError):
         w.show_panel("nothing")
      self.close(w)

   def test_formulas_page(self) -> None:
      """!The Formulas page lists the formula slots and the ruleset's stat formulas.
      @return None
      """
      from capsule_studio.ui.editors.logic.formulas import SLOT_COLUMN
      w, panel = self.window("rules")
      slots = [panel.table.item(r, SLOT_COLUMN).text() for r in range(panel.table.rowCount())]
      self.assertIn("damage_base", slots)
      self.assertIn("vital", slots)     # the Starter's stat formulas
      self.assertIn("reserve", slots)
      self.close(w)

   def test_group_preselected(self) -> None:
      """!A window opened on a group shows its first page; the other groups start collapsed.
      @return None
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      for group, first in (("structure", "record"), ("logic", "effects"), ("content", "species")):
         w = BattleWindow(None, self.battle_json, group)
         self.settle()
         self.assertEqual(w.active_panel().panel_id, first, group)
         self.assertEqual({gid for gid, item in w.group_items.items() if item.isExpanded()}, {group})
         self.close(w)
      with self.assertRaises(ValueError):
         BattleWindow(None, None, "nowhere")

   def test_one_panel_alone(self) -> None:
      """!battle-editor --panel hosts one editor without a navigator.
      @return None
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.editors.structure.terms import TermsPanel
      w = BattleWindow([TermsPanel], self.battle_json)
      self.assertIs(w.centralWidget(), w.panels[0])
      self.assertIs(w.active_panel(), w.panels[0])
      self.close(w)

   def test_entry_points(self) -> None:
      """!battle-structure and battle-logic start the battle editor on their group (launchers, toolkit tools,
      line endings).
      @return None
      """
      from capsule_studio.ui import battle_app, battle_logic_app, battle_structure_app
      from capsule_studio.ui.battle_shell import BattleWindow
      made = []

      def make(*args: object) -> BattleWindow:
         """!Builds the window the app asks for, and keeps it.
         @return BattleWindow
         """
         made.append(BattleWindow(*args))
         return made[-1]
      with mock.patch.object(battle_app, "BattleWindow", side_effect=make), \
           mock.patch.object(QtWidgets.QApplication, "exec", return_value=0):
         self.assertEqual(battle_structure_app.main([str(self.battle_json)]), 0)
         self.assertEqual(battle_logic_app.main([str(self.battle_json)]), 0)
         self.assertEqual(battle_app.main([str(self.battle_json)]), 0)
         self.assertEqual(battle_app.main([str(self.battle_json), "--group", "logic"]), 0)
      self.settle()
      self.assertEqual([w.active_panel().panel_id for w in made], ["record", "effects", "species", "effects"])
      for w in made:
         self.close(w)
      sys.path.insert(0, str(REPO / "toolkit"))
      import env
      self.assertEqual(env.TOOLS["battle-structure"][0], "capsule_studio.ui.battle_structure_app")
      self.assertEqual(env.TOOLS["battle-logic"][0], "capsule_studio.ui.battle_logic_app")
      attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
      for tool in ("battle-structure", "battle-logic"):
         self.assertIn(f"run {tool} ", (REPO / tool).read_text(encoding="utf-8"))
         self.assertIn(f"run {tool} ", (REPO / f"{tool}.cmd").read_bytes().decode("utf-8"))
         self.assertIn(b"\r\n", (REPO / f"{tool}.cmd").read_bytes())
         self.assertNotIn(b"\r", (REPO / tool).read_bytes())
         self.assertRegex(attributes, rf"(?m)^{tool}\s+text eol=lf$")

   def test_text_page(self) -> None:
      """!The Text page names the code page and what the texts lack; its button opens the project's Code page
      panel in a project settings window.
      @return None
      """
      w, panel = self.window("text")
      w.show()
      self.settle()
      self.assertIn("Code page:", panel.summary.text())
      self.assertTrue(panel.open_button.isEnabled())
      panel.open_button.click()
      self.settle()
      pw = w._code_page_window
      self.assertIsNotNone(pw)
      self.assertEqual(pw.tabs.currentWidget().panel_id, "codepage")
      self.assertEqual(pw.document.path, (self.root / "reference" / "project.json").resolve())
      panel.open_button.click()
      self.assertIs(w._code_page_window, pw)   # the same window again
      pw.close()
      self.close(w)


class FileIndicatorTests(QtBattleTestCase):
   """!Which file a page edits (E5s: battle.json is the content, structure.json the structure): the navigator's
   file column, the status bar, Undo across both manifests, the Data page's sections and the split offer."""

   def test_files_shown_and_grouped_undo(self) -> None:
      """!Each group names its file (with a mark while it has unsaved changes), the status bar the active page's;
      a rename on a structure page that changes both manifests is one undo step.
      @return None
      """
      from capsule_studio.core import battle
      from capsule_studio.ui.battle_shell import DIRTY_MARK, FILE_COLUMN
      w, panel = self.window("categories")
      p = w.project
      files = {gid: item.text(FILE_COLUMN) for gid, item in w.group_items.items()}
      self.assertEqual(files, {"content": "battle.json", "structure": "structure.json", "logic": "ruleset.json"})
      self.assertEqual(w.file_status.text(), "Editing structure.json")
      self.assertIs(w.document, p.structure)
      self.assertTrue(panel.edit("Rename", lambda: battle.rename_entry(p.structure, "categories", "physical",
                                                                       "body")))
      self.settle()
      self.assertEqual(battle.entry(p.battle, "moves", "Flare Claw")["category"], "body")
      self.assertEqual(w.group_items["content"].text(FILE_COLUMN), "battle.json" + DIRTY_MARK)
      self.assertEqual(w.group_items["structure"].text(FILE_COLUMN), "structure.json" + DIRTY_MARK)
      self.assertEqual(w.file_status.text(), "Editing structure.json" + DIRTY_MARK)
      w.undo()
      self.settle()
      self.assertEqual(battle.entry(p.battle, "moves", "Flare Claw")["category"], "physical")
      self.assertIn("physical", p.names("categories"))
      w.redo()
      self.settle()
      self.assertTrue(w.save_all())
      self.settle()
      self.assertEqual(w.group_items["structure"].text(FILE_COLUMN), "structure.json")
      self.assertEqual(battle.entry(battle.content_doc(p.battle), "moves", "Flare Claw")["category"], "body")
      w.show_panel("species")
      self.settle()
      self.assertEqual(w.file_status.text(), "Editing battle.json")
      self.close(w)

   def test_pages_editing_another_file(self) -> None:
      """!The Data page edits the file of the section it shows; the Types page's chart grid edits the structure
      manifest, and Undo there follows it.
      @return None
      """
      from capsule_studio.core import battle
      from capsule_studio.ui.battle_shell import FILE_COLUMN
      w, panel = self.window("data")
      p = w.project
      panel.what.setCurrentText("rules")
      self.settle()
      self.assertIs(w.document, p.structure)
      self.assertEqual(panel.file_label.text(), "In structure.json")
      self.assertEqual(w.page_items[w.panels.index(panel)].text(FILE_COLUMN), "structure.json")
      panel.what.setCurrentText("traits")   # the messages have their own page (S11)
      self.settle()
      self.assertIs(w.document, p.battle)
      types = w.show_panel("types")
      self.settle()
      self.assertIs(w.document, p.battle)
      self.assertTrue(types.edit("Chart", lambda: battle.set_chart(p.battle, "Fire", "Light", "weak")))
      self.settle()
      self.assertIs(w.document, p.structure)   # only the structure manifest changed: Undo goes there
      w.undo()
      self.settle()
      self.assertEqual(battle.chart_value(p.battle, "Fire", "Light"), "normal")
      self.assertIs(w.document, p.battle)
      self.close(w)

   def test_single_file_data_offers_split(self) -> None:
      """!Single-file battle data (before E5s) does not open: headless the refusal is reported (no question); on a
      screen the window asks, splits it and opens it.
      @return None
      """
      from capsule_studio.core import battle, engine
      from capsule_studio.ui.battle_shell import BattleWindow
      merged = engine.tool("battle_compiler").view_of(self.battle_json)
      merged.pop(battle.STRUCTURE_KEY)
      (self.battle_json.parent / battle.STRUCTURE_FILE).unlink()
      self.battle_json.write_text(json.dumps(merged), encoding="utf-8")
      w = BattleWindow(None, self.battle_json)
      self.assertIsNone(w.project)
      self.assertIn("split", w.open_error)
      b = QtWidgets.QMessageBox.StandardButton
      with mock.patch("capsule_studio.ui.battle_shell.headless", return_value=False), \
           mock.patch.object(QtWidgets.QMessageBox, "question", return_value=b.Yes) as asked:
         w.open_battle(self.battle_json)
      self.assertEqual(asked.call_count, 1)
      self.assertIsNotNone(w.project)
      self.assertEqual(w.project.structure.path, (self.battle_json.parent / battle.STRUCTURE_FILE).resolve())
      self.assertIsNone(w.project.validate())
      self.close(w)


class StudioBattlePageTests(QtBattleTestCase):
   """!The Studio's Battle page."""

   def test_studio_battle_page(self) -> None:
      """!The Battle page has the navigator; its Text page opens the Project page's code page.
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      s = StudioWindow(str(self.root / "reference" / "project.json"), "battle")
      self.settle()
      s.show_page("battle")
      self.settle()
      bw = s.windows["battle"]
      self.assertEqual(s.current_page_id(), "battle")
      self.assertEqual(len(bw.group_items), len(["content", "structure", "logic"]))
      self.assertTrue(bw.nav.isVisibleTo(s))
      text = bw.show_panel("text")
      self.settle()
      text.open_button.click()
      self.settle()
      self.assertEqual(s.current_page_id(), "project")
      self.assertEqual(s.windows["project"].tabs.currentWidget().panel_id, "codepage")
      self.assertIsNone(bw._code_page_window)   # no window of its own in the Studio
      for w in s.windows.values():
         w._confirm_discard = lambda: True
      s._confirm_all = lambda: True
      s.close()
