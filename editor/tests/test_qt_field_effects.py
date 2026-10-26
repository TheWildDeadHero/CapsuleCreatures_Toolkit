#!/usr/bin/env python3
"""!Smoke tests of the F1 pages: Structure > Field effects (the list, the form, a rename following the logic),
Structure > Encounter rules (the lead rule, the pipelines, the logic running the encounter hooks, a new global rule)
and the Items tab's field effect row. Each opens a copy of the Starter sample laid out as a game and edits through
the widgets (one undo step per manifest edit). Skipped when PySide6 is missing; uses Qt's offscreen platform.
CAPSULE_SHOTS=FOLDER saves a picture of each page there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle, logic  # noqa: E402
from capsule_studio.core.structure import encounter_rules, field_effects  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## Environment variable naming a folder for the pages' pictures.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a picture, pixels.
SHOT_SIZE = (1200, 760)
## The Starter's field effect and the item starting it.
WARD, WARD_ITEM = "ward", "Ward Charm"


class FieldEffectPagesTests(QtBattleTestCase):
   """!The Field effects, Encounter rules and Items pages."""

   def window(self, panel_id: str) -> tuple[object, object]:
      """!A battle editor on the copy hosting the F1 pages (and Logic > Effects for the Logic... button).
      @param panel_id  the page's panel id
      @return (BattleWindow, the panel)
      """
      from capsule_studio.ui.battle_shell import BattleWindow
      from capsule_studio.ui.editors.content.holders import PassivesItemsPanel
      from capsule_studio.ui.editors.logic.effects_panel import EffectsPanel
      from capsule_studio.ui.editors.structure.encounter_rules import EncounterRulesPanel
      from capsule_studio.ui.editors.structure.field_effects import FieldEffectsPanel
      w = BattleWindow([FieldEffectsPanel, EncounterRulesPanel, PassivesItemsPanel, EffectsPanel], self.battle_json)
      panel = w.show_panel(panel_id)
      self.settle()
      return w, panel

   def shot(self, w: object, panel: object, name: str) -> None:
      """!Saves a picture of a page when CAPSULE_SHOTS names a folder.
      @param w      the window
      @param panel  the page
      @param name   file stem
      @return None
      """
      shots = os.environ.get(SHOTS_ENV)
      if not shots:
         return
      Path(shots).mkdir(parents=True, exist_ok=True)
      w.resize(*SHOT_SIZE)
      w.show()
      self.settle()
      panel.grab().save(str(Path(shots) / f"{name}.png"))

   def test_field_effects_page(self) -> None:
      """!The sample's effect in the form; stack and expiry through the widgets; add, rename (logic follows), undo.
      @return None
      """
      w, panel = self.window("field_effects")
      p = w.project
      self.assertIs(w.document, p.structure)
      self.assertEqual(panel.list.count(), 1)
      self.assertEqual(panel.unit.currentText(), "steps")
      self.assertIn("field_effect_ward", panel.implicit.text())
      self.assertIn(WARD_ITEM, panel.used_by.text())
      self.shot(w, panel, "studio_field_effects")
      panel.stack.setCurrentText("add")
      panel.stack.activated.emit(panel.stack.currentIndex())
      self.settle()
      self.assertEqual(field_effects.effects(p.structure)[0]["stack"], "add")
      self.assertEqual(w.undo_action.text(), "Undo Set field effect")
      self.assertTrue(panel.add_effect("lure"))
      self.settle()
      self.assertEqual(field_effects.effect_names(p.structure), [WARD, "lure"])
      panel.selected = WARD
      panel.refresh()
      self.assertTrue(panel.rename_effect("glow"))
      self.settle()
      self.assertEqual(field_effects.item_field_effect(p, WARD_ITEM)[0], "glow")
      self.assertFalse(panel.remove_effect())   # the logic names it
      self.assertIsNone(p.error_now())

   def test_encounter_rules_page(self) -> None:
      """!The default lead, a rule through the line edit, a refused one, the handler table, a global rule.
      @return None
      """
      w, panel = self.window("encounter_rules")
      p = w.project
      self.assertIn(encounter_rules.DEFAULT_LEAD_TEXT, panel.lead_text.text())
      self.assertIn("encounter_rate", panel.pipelines.text())
      self.assertEqual(panel.handlers.item(0, 0).text(), f"{logic.global_kind()} ward_rule")
      self.assertTrue(panel.set_lead("level >= 5"))
      self.settle()
      self.assertEqual(encounter_rules.lead_when(p.structure), "level >= 5")
      self.assertIn("level >= 5", panel.lead_text.text())
      self.shot(w, panel, "studio_encounter_rules_lead")
      self.assertFalse(panel.set_lead("no_such_value > 1"))
      self.settle()
      self.assertEqual(encounter_rules.lead_when(p.structure), "level >= 5")
      rows = panel.handlers.rowCount()
      self.assertTrue(panel.add_global_rule("lure_rule"))
      self.settle()
      self.assertEqual(panel.handlers.rowCount(), rows + 1)
      panel.handlers.selectRow(0)
      self.assertTrue(panel.show_logic())
      # C8: the hooks' member's rule (another member than the lead runs the passive and held item hooks)
      self.assertTrue(panel.set_hook_lead("1"))
      self.settle()
      self.assertEqual(encounter_rules.hook_lead_when(p.structure), "1")
      self.assertEqual(panel.hook_when.text(), "1")
      self.assertIn("`1`", panel.lead_text.text())
      self.shot(w, panel, "studio_encounter_rules_hooks")
      self.assertFalse(panel.set_hook_lead("no_such_value > 1"))
      self.assertTrue(panel.clear_lead())
      self.settle()
      self.assertIsNone(encounter_rules.lead_when(p.structure))
      self.assertEqual(encounter_rules.hook_lead_when(p.structure), "1")   # the hooks' rule stays
      self.assertTrue(panel.clear_hook_lead())
      self.settle()
      self.assertIsNone(encounter_rules.hook_lead_when(p.structure))

   def test_items_row(self) -> None:
      """!The Items tab shows what the charm starts; Start makes another item start the effect (one step).
      @return None
      """
      w, panel = self.window("passives_items")
      tab = panel.items
      panel.tabs.setCurrentWidget(tab)
      p = w.project
      self.select(tab, WARD_ITEM)
      self.assertIn(WARD, tab.field_info.text())
      self.assertEqual(tab.field_effect.currentText(), WARD)
      w.resize(*SHOT_SIZE)
      w.show()
      self.settle()
      # F2 (an F1 leftover): the form scrolls, so the Add buttons sit below the use logic text, not over it
      first_add = next(iter(tab.add_hook.values()))
      self.assertGreaterEqual(first_add.geometry().top(), tab.use_text.geometry().bottom())
      self.assertIsNotNone(tab.form_scroll)
      tab.form_scroll.ensureWidgetVisible(tab.field_info)
      self.shot(w, panel, "studio_items_field_effect")
      other = next(e["name"] for e in battle.entries(p.battle, "items")
                   if e["name"] != WARD_ITEM and e.get("use", "none") == "none" and e.get("pocket") is not None)
      self.select(tab, other)
      self.assertTrue(tab.set_field_effect(WARD, 30))
      self.settle()
      self.assertEqual(field_effects.item_field_effect(p, other), (WARD, "30"))
      self.assertIn(f"field_effect start {WARD} 30", tab.use_text.toPlainText())
      self.assertIsNone(p.error_now())
