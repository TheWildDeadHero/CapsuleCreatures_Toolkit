#!/usr/bin/env python3
"""!Qt tests of the studio pages for the engine's G1 (D-26 section 1): the Logic > AI page (profiles, rules, numbers),
the Structure > Delayed hits page, the Parties page's AI profile combo and the Conditions page's bound_to combo.
Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import ai  # noqa: E402
from capsule_studio.core.structure import conditions, delayed_hits  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## The Starter's profiles and a party naming one (samples/starter/battle.json, G1).
STARTER_DEFAULT, STARTER_BATTLER, PARTY = "Basic", "Battler", "Novice Kit"


class AiPageTests(QtBattleTestCase):
   """!The AI page."""

   def test_profiles_and_rules(self) -> None:
      """!The Starter's profiles with the default marked; a rule added, its number set and reset, undone; a profile
      renamed with the parties following; the hook entry shown.
      @return None
      """
      w, panel = self.window("ai")
      doc = w.project.battle
      self.assertIs(w.document, doc)
      self.assertEqual(panel.names(), ai.profile_names(doc))
      panel.select(STARTER_BATTLER)
      self.settle()
      self.assertEqual(panel.selected, STARTER_BATTLER)
      self.assertIn(PARTY, panel.used_by.text())
      self.assertIn("ai_score", panel.hook.text())
      box = panel.boxes[ai.RULES_KEY]
      count = box.table.rowCount()
      self.assertEqual(count, len(ai.rule_rows(doc, STARTER_BATTLER)))
      self.assertTrue(box.add_rule("noise"))
      self.settle()
      self.assertEqual(box.table.rowCount(), count + 1)
      self.assertTrue(box.set_number("max", 8))
      self.settle()
      self.assertEqual(ai.rule_rows(doc, STARTER_BATTLER)[box.selected]["args"]["max"], 8)
      self.assertTrue(box.set_number("max", None))
      self.settle()
      self.assertNotIn("max", ai.rule_rows(doc, STARTER_BATTLER)[box.selected]["stated"])
      for _ in range(3):
         w.undo()
      self.settle()
      self.assertEqual(box.table.rowCount(), count)
      self.assertTrue(panel.rename_profile("Fighter"))
      self.settle()
      self.assertEqual(ai.party_profile(doc, PARTY), "Fighter")
      self.assertFalse(panel.remove_profile())        # a party names it
      self.assertFalse(panel.migrate.isVisible())     # no party gives the former flags
      self.close(w)

   def test_party_combo(self) -> None:
      """!The Parties page's AI combo: the default first (None), then the profiles; picking one sets the party.
      @return None
      """
      w, panel = self.window("parties")
      doc = w.project.battle
      self.select(panel, PARTY)
      combo = panel.ai
      self.assertEqual(combo.currentText(), STARTER_BATTLER)
      self.assertEqual([combo.itemText(i) for i in range(1, combo.count())], ai.profile_names(doc))
      self.assertTrue(combo.itemText(0).startswith(ai.DEFAULT_CHOICE))
      combo.setCurrentIndex(0)
      combo.activated.emit(0)
      self.settle()
      self.assertIsNone(ai.party_profile(doc, PARTY))
      self.close(w)


class DelayedHitsPageTests(QtBattleTestCase):
   """!The Delayed hits page and the Conditions page's bound_to."""

   def test_delayed_hits(self) -> None:
      """!Add a record; the form shows the engine's defaults; accuracy set; undo.
      @return None
      """
      w, panel = self.window("delayed_hits")
      doc = w.project.structure
      self.assertIs(w.document, doc)
      self.assertEqual(panel.names(), [])
      self.assertTrue(panel.add_hit("sight"))
      self.settle()
      self.assertEqual(panel.names(), ["sight"])
      self.assertEqual(list(panel.flags), delayed_hits.flag_names())
      self.assertEqual(panel.accuracy.maximum(), delayed_hits.max_accuracy())
      self.assertEqual(panel.missed.currentText(), delayed_hits.default_miss_message())
      panel.accuracy.setValue(delayed_hits.max_accuracy())
      panel.accuracy.editingFinished.emit()
      self.settle()
      self.assertEqual(delayed_hits.hit_rows(doc)[0]["accuracy"], delayed_hits.max_accuracy())
      w.undo()
      w.undo()
      self.settle()
      self.assertEqual(panel.names(), [])
      self.close(w)

   def test_bound_to(self) -> None:
      """!A volatile's bound_to combo offers none and the engine's choices; picking one sets it.
      @return None
      """
      w, panel = self.window("conditions")
      doc = w.project.structure
      tab = panel.show_kind("volatile")
      name = tab.names()[0]
      tab.select(name)
      self.settle()
      combo = tab.inputs["bound_to"][1]["combo"]
      self.assertEqual([combo.itemText(i) for i in range(1, combo.count())], conditions.bound_choices())
      combo.setCurrentIndex(1)
      combo.activated.emit(1)
      self.settle()
      entry = next(e for e in doc.data["volatiles"] if e["name"] == name)
      self.assertEqual(entry["bound_to"], conditions.bound_choices()[0])
      self.close(w)


if __name__ == "__main__":
   import unittest
   unittest.main()
