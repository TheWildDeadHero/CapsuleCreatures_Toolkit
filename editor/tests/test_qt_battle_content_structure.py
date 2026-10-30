#!/usr/bin/env python3
"""!Smoke tests of S11 (D-22 A15): every Content page widget follows the
compiled structure, on the Starter and on the reference repo's classic game
(the expected counts and ranges are read from each game's data, never
written down): the Species page's type, base, passive and preview boxes, the
Moves page's ranges, flags, targets and bases, the Parties page's AI boxes,
ranks, levels, move slots, genes and passive slots; and the Messages page
(engine C4: the battle's own messages listed, edited, renamed, added and
removed through the widgets, one undo step each). Skipped when PySide6 is
missing; uses Qt's offscreen platform. CAPSULE_SHOTS=FOLDER saves pictures of
the four pages there (starter_*.png, classic_*.png).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import ai as ai_model, battle, engine, messages  # noqa: E402
from capsule_studio.core.structure import chart, passive_slots, record, resources, stages  # noqa: E402
from sample_data import make_classic_game, needs_classic  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## Environment variable naming a folder for the pages' pictures.
SHOTS_ENV = "CAPSULE_SHOTS"
## Size of a picture, pixels.
SHOT_SIZE = (1100, 720)
## The pages pictured, in order.
SHOT_PAGES = ("species", "moves", "parties", "messages")
## A game message of the Starter that effect logic says.
SAID = "dazed"


class ContentChecks:
   """!The checks, on the game the test case's setUp() lays out (mixed into a QtBattleTestCase)."""

   ## Picture name prefix.
   shot_prefix = "starter"

   def shots(self, w: object) -> None:
      """!Saves the four pages' pictures when CAPSULE_SHOTS names a folder.
      @param w  the battle window
      @return None
      """
      folder = os.environ.get(SHOTS_ENV)
      if not folder:
         return
      Path(folder).mkdir(parents=True, exist_ok=True)
      w.resize(*SHOT_SIZE)
      w.show()
      for page in SHOT_PAGES:
         panel = w.show_panel(page)
         self.settle()
         names = getattr(panel, "names", None)
         if names is not None and names() and getattr(panel, "entry_list", None) is not None:
            panel.entry_list.setCurrentRow(0)
            self.settle()
         w.grab().save(str(Path(folder) / f"{self.shot_prefix}_{page}.png"))

   def test_pages_follow_the_data(self) -> None:
      """!Species, Moves and Parties: every count, list and range is the compiled data's or the engine's.
      @return None
      """
      bc = engine.tool("battle_compiler")
      w, species = self.window("species")
      p = w.project
      doc = p.battle
      level_max = battle.level_max(p.structure)
      # Species
      name = next(s["name"] for s in doc.data["species"] if len(s.get("types") or []) <= chart.types_per_species(doc))
      self.select(species, name)
      self.assertEqual(len(species.types), chart.types_per_species(doc))
      self.assertEqual(len(species.base), len(battle.stat_keys(doc)))
      self.assertEqual(len(species.passives), len(passive_slots.slot_names(p.structure)))
      self.assertEqual((species.learn_level.maximum(), species.preview_level.maximum()), (level_max, level_max))
      inputs = record.stat_inputs(doc)
      self.assertEqual({k: s.maximum() for k, s in species.preview_inputs.items()}, inputs)
      self.assertEqual(species.exp_yield.maximum(), bc.U16_MAX)
      self.assertNotIn("(", species.preview.text())   # the preview computes (no error in brackets)
      # Moves
      moves = w.show_panel("moves")
      self.settle()
      self.select(moves, doc.data["moves"][0]["name"])
      self.assertEqual(moves.accuracy.maximum(), bc.PERCENT)
      self.assertEqual((moves.priority.minimum(), moves.priority.maximum()), (-bc.MAX_PRIORITY, bc.MAX_PRIORITY))
      self.assertEqual(moves.crit.maximum(), stages.crit_max(doc))
      self.assertEqual(list(moves.flags), list(p.structure.data.get("move_flags") or []))
      self.assertEqual([moves.target.itemText(i) for i in range(moves.target.count())], list(bc.TARGETS))
      self.assertEqual([moves.category.itemText(i) for i in range(moves.category.count())], p.names("categories"))
      move_resources = [r["name"] for r in resources.resource_rows(doc) if r["scope"] == resources.MOVE]
      self.assertEqual(list(moves.bases), move_resources)
      self.assertTrue(all(b.maximum() == resources.storage_max(resources.MOVE) for b in moves.bases.values()))
      # Parties
      parties = w.show_panel("parties")
      self.settle()
      self.select(parties, doc.data["parties"][0]["name"])
      parties.members.setCurrentRow(0)
      self.settle()
      self.assertEqual([parties.ai.itemText(i) for i in range(1, parties.ai.count())],   # G1: AI profiles
                       ai_model.profile_names(doc))
      self.assertEqual(parties.rank.maximum(), battle.rank_max(p.structure))
      self.assertEqual(parties.m_level.maximum(), level_max)
      self.assertEqual(len(parties.m_moves), record.move_slots(doc))
      self.assertEqual(parties.m_genes.maximum(), record.gene_max(doc))
      self.assertEqual([parties.m_passive.itemText(i) for i in range(parties.m_passive.count())],
                       passive_slots.slot_names(p.structure))
      self.assertEqual(parties.reward.maximum(), bc.U16_MAX)
      # Messages
      page = w.show_panel("messages")
      self.settle()
      rows = messages.rows(doc)
      self.assertEqual(page.table.rowCount(), len(rows))
      self.assertEqual(page.keys, [r["key"] for r in rows])
      self.assertIn(f"of at most {messages.max_game_messages()}", page.budget.text())
      self.shots(w)
      self.close(w)


class ContentFollowsStructureTests(ContentChecks, QtBattleTestCase):
   """!On the Starter, plus the Messages page's edits and the new party member's level."""

   def test_messages_page_edits(self) -> None:
      """!Typing a text sets it, typing a key of the battle's own renames it (logic follows); add, add optional and
      remove are one undo step each; a used one is not removed.
      @return None
      """
      from capsule_studio.ui.editors.content.messages import KEY_COLUMN, TEXT_COLUMN
      w, page = self.window("messages")
      doc = w.project.battle
      self.assertIs(w.document, doc)
      own = messages.game_keys(doc)
      self.assertTrue(set(own) <= set(page.keys))
      row = page.keys.index(SAID)
      page.table.item(row, TEXT_COLUMN).setText("{user} is all at sea!")
      self.settle()
      self.assertEqual(messages.given(doc)[SAID], "{user} is all at sea!")
      self.assertEqual(w.undo_action.text(), "Undo Set message")
      page.table.item(page.keys.index(SAID), KEY_COLUMN).setText("muddled")
      self.settle()
      self.assertIn("muddled", messages.given(doc))
      self.assertEqual(messages.uses(doc, SAID), [])
      self.assertEqual(w.undo_action.text(), "Undo Rename message")
      self.assertIsNone(w.project.validate())
      self.assertTrue(page.add_message("taunt", "{user} taunts {target}!"))
      self.settle()
      self.assertEqual(page.keys[-1], "taunt")
      self.assertFalse(page.add_message("Taunt"))   # not a lower-case identifier
      absent = messages.absent_optional(doc)
      self.assertTrue(page.add_optional(absent[0]))
      self.settle()
      self.assertIn(absent[0], messages.given(doc))
      page.selected = "muddled"
      self.assertFalse(page.remove_message())   # effect logic says it
      page.selected = "taunt"
      self.assertTrue(page.remove_message())
      self.settle()
      self.assertNotIn("taunt", messages.given(doc))
      self.assertIsNone(w.project.validate())
      self.close(w)

   def test_new_member_level(self) -> None:
      """!A new party member takes the level of the party's last member (within rules.level_max).
      @return None
      """
      w, parties = self.window("parties")
      doc = w.project.battle
      party = doc.data["parties"][0]
      self.select(parties, party["name"])
      last = party["members"][-1]["level"]
      self.assertTrue(parties.add_member_button.isEnabled())
      parties.add_member()
      self.settle()
      self.assertEqual(battle.entry(doc, "parties", party["name"])["members"][-1]["level"], last)
      self.close(w)


@needs_classic
class ClassicContentTests(ContentChecks, QtBattleTestCase):
   """!The same checks on the reference repo's classic game (its own counts and ranges)."""

   ## Picture name prefix.
   shot_prefix = "classic"

   def setUp(self) -> None:
      """!Lays out the classic game instead of the Starter.
      @return None
      """
      super().setUp()
      self.battle_json = make_classic_game(self.root / "classic")

