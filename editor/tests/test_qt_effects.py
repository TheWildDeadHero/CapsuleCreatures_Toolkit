#!/usr/bin/env python3
"""!Smoke tests of Logic > Effects (S8): the owner tree and its filters, the
handler list with the hook / point picker and the budget meter, the block
view and the text view over one AST (a text edit updates the blocks; text
that does not parse shows a banner and leaves the blocks as they were; a
block edit replaces only the owner's span of its file), undo / redo of
grouped steps and a save round trip. Skipped when PySide6 is missing; uses
Qt's offscreen platform.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import battle, logic  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from test_qt_battle import QtBattleTestCase, QtCore, QtWidgets  # noqa: E402

## The Starter's move logic.
MOVES = "effects/moves.ceffect"
## Its passive logic.
PASSIVES = "effects/passives.ceffect"
## Its condition logic (statuses, weathers, volatiles).
CONDITIONS = "effects/conditions.ceffect"
## A statement of Night Pulse's hit (the line the tests break; the only one of its kind in the file).
ROLL = "stage target intelligence -1;"


class EffectsTestCase(QtBattleTestCase):
   """!Helpers."""

   def effects(self, owner: str | None = "move:Night Pulse") -> tuple[object, object]:
      """!The battle editor on the Effects page, an owner selected.
      @param owner  "kind:name", or None
      @return (BattleWindow, EffectsPanel)
      """
      w, panel = self.window("effects")
      if owner is not None:
         self.assertTrue(panel.select_owner(owner))
         self.settle()
      return w, panel

   def text(self, w: object, rel: str = MOVES) -> str:
      """!A source's text now.
      @param w    BattleWindow
      @param rel  the source
      @return text
      """
      return w.project.effect_source(rel).text

   def block_texts(self, panel: object) -> list[str]:
      """!The block view's row texts.
      @param panel  EffectsPanel
      @return texts in display order
      """
      return [text for _depth, _ref, text in panel.blocks.rows()]

   def assert_only_owner_changed(self, before: str, after: str, start: int, end_from_back: int) -> None:
      """!Checks that a file changed only inside one owner's span.
      @param before         the text before
      @param after          the text after
      @param start          offset of the owner's first character
      @param end_from_back  characters after the owner's closing brace
      @return None
      """
      self.assertNotEqual(before, after)
      self.assertEqual(after[:start], before[:start])
      self.assertEqual(after[len(after) - end_from_back:], before[len(before) - end_from_back:])

   def span(self, w: object, ref: str, rel: str = MOVES) -> tuple[int, int]:
      """!Where an owner's block is in its file.
      @param w    BattleWindow
      @param ref  "kind:name"
      @param rel  its file
      @return (start offset, characters after its end)
      """
      text = self.text(w, rel)
      block = logic.owner_text(w.project, ref)
      start = text.index(block)
      return start, len(text) - start - len(block)


class OwnerTreeTests(EffectsTestCase):
   """!The owner tree, the handlers, the picker and the budget."""

   def test_open(self) -> None:
      """!Groups and counts, selecting an owner, its handler, its blocks, the picker, the budget, Undo target.
      @return None
      """
      w, panel = self.effects(None)
      tree = panel.owner_tree
      self.assertEqual([tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())],
                       ["Moves", "Passives", "Items", "Statuses", "Weathers", "Volatiles", "Side conditions",
                        "Field conditions", "Global rules"])
      self.assertEqual(tree.topLevelItem(3).childCount(), 3)   # Scorch, Shock, Blight (F3: its on steps)
      volatiles = tree.topLevelItem(5)
      self.assertEqual([volatiles.child(i).text(0) for i in range(volatiles.childCount())], ["dazed"])
      self.assertIs(w.document, w.project.effect_source(MOVES))   # nothing selected: the text view's file
      self.assertTrue(panel.select_owner("move:Night Pulse"))
      self.settle()
      self.assertIs(w.document, w.project.effect_source(MOVES))
      self.assertEqual(panel.handler_list.count(), 1)
      self.assertEqual(panel.handler_list.item(0).text(), "hit")
      texts = self.block_texts(panel)
      self.assertEqual(texts[0], "hit")
      self.assertIn("stage target intelligence -1", texts)
      self.assertIn("damage", texts)
      self.assertEqual(panel.picker.choice(), ("phase", "hit"))
      self.assertIn("holder = user", panel.picker.info.text())
      self.assertIn("may yield / ask: yes", panel.picker.info.text())
      self.assertEqual(panel.stack_bar.maximum(), 16)
      self.assertGreater(panel.stack_bar.value(), 0)
      self.assertEqual(panel.events_bar.maximum(), 128)
      self.assertIn("may draw", panel.budget_text.text())
      # A point handler: the catalog's point, no budget beyond the pure code.
      self.assertTrue(panel.select_owner("status:Shock"))
      self.settle()
      self.assertEqual(panel.picker.choice(), ("point", "speed"))
      self.assertIn("pure", panel.picker.info.text())
      self.assertEqual(panel.events_bar.value(), 0)
      # A volatile (E5): its handlers and the condition hooks, try_start included.
      self.assertTrue(panel.select_owner("volatile:dazed"))
      self.settle()
      self.assertEqual(panel.owner, ("volatile", "dazed"))
      self.assertGreater(panel.handler_list.count(), 0)
      self.assertIn("try_start", [h["name"] for h in logic.hook_catalog("volatile")])
      self.assertEqual([d for d in logic.diagnostics(w.project) if d.severity == "error"], [])
      self.close(w)

   def test_condition_owners_without_logic(self) -> None:
      """!"has logic" off lists every volatile record (greyed without logic); logic can be added to one.
      @return None
      """
      w, panel = self.effects(None)
      tree = panel.owner_tree
      panel.has_logic.setChecked(False)
      self.settle()
      volatiles = tree.topLevelItem(5)
      names = [volatiles.child(i).text(0) for i in range(volatiles.childCount())]
      self.assertEqual(sorted(names), sorted(w.project.names("volatiles")))
      flinch = volatiles.child(names.index("flinch"))
      self.assertFalse(flinch.data(0, QtCore.Qt.ItemDataRole.UserRole)[2])
      self.assertTrue(panel.select_owner("volatile:flinch"))
      self.settle()
      self.assertTrue(panel.add_logic())
      self.settle()
      self.assertIn('volatile "flinch" {}', w.project.effect_source(CONDITIONS).text)
      self.close(w)

   def test_filters_and_grouping(self) -> None:
      """!By file; "has logic" off lists entries without logic; "uses hook" keeps the owners using it.
      @return None
      """
      w, panel = self.effects(None)
      tree = panel.owner_tree
      panel.grouping.setCurrentIndex(1)
      self.settle()
      files = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())
               if not tree.topLevelItem(i).isHidden()]
      self.assertEqual(files, list(w.project.effects))
      panel.grouping.setCurrentIndex(0)
      panel.has_logic.setChecked(False)
      self.settle()
      moves = tree.topLevelItem(0)
      names = [moves.child(i).text(0) for i in range(moves.childCount())]
      self.assertIn("Gale Kick", names)   # a damaging move without logic (the standard hit)
      kick = moves.child(names.index("Gale Kick"))
      self.assertFalse(kick.data(0, QtCore.Qt.ItemDataRole.UserRole)[2])
      panel.has_logic.setChecked(True)
      panel.uses_hook.setCurrentIndex(panel.uses_hook.findText("speed"))
      panel.uses_hook.activated.emit(panel.uses_hook.currentIndex())
      self.settle()
      shown = [(tree.topLevelItem(i).text(0), tree.topLevelItem(i).child(j).text(0))
               for i in range(tree.topLevelItemCount()) for j in range(tree.topLevelItem(i).childCount())]
      self.assertIn(("Statuses", "Shock"), shown)
      self.assertNotIn(("Statuses", "Scorch"), shown)
      self.close(w)

   def test_owner_and_handler_edits(self) -> None:
      """!Add logic to an entry, add a handler from the picker (per_foe), set its hook, edit its `when`, remove
      it, give the logic to another entry, remove it: one undo step each.
      @return None
      """
      w, panel = self.effects(None)
      panel.has_logic.setChecked(False)
      self.settle()
      self.assertTrue(panel.select_owner("move:Gale Kick"))
      self.settle()
      self.assertTrue(panel.add_button.isEnabled())
      self.assertTrue(panel.add_logic())
      self.settle()
      self.assertIn('move "Gale Kick" {}', self.text(w))
      self.assertEqual(w.undo_action.text(), "Undo Add logic")
      panel.picker.set_choice("phase", "hit")
      self.assertTrue(panel.add_handler())
      self.settle()
      self.assertEqual(logic.handlers(w.project, "move:Gale Kick")[0].name, "hit")
      self.assertTrue(panel.blocks.insert_template("damage;"))
      self.settle()
      self.assertIn("hit {\n      damage;\n   }", logic.owner_text(w.project, "move:Gale Kick"))
      # A passive: per_foe on switch_in, then its `when` through the block form.
      self.assertTrue(panel.select_owner("passive:Insight"))
      self.settle()
      count = panel.handler_list.count()
      panel.picker.set_choice("on", "switch_in")
      panel._picker_changed()
      self.assertTrue(panel.per_foe.isEnabled())
      panel.per_foe.setChecked(True)   # nothing selected to change yet: the new handler takes it
      panel.picker.set_choice("on", "switch_in")
      self.assertTrue(panel.add_handler())
      self.settle()
      self.assertEqual(panel.handler_list.count(), count + 1)
      row = logic.handlers(w.project, "Insight")[-1]
      self.assertEqual((row.name, row.per_foe), ("switch_in", True))
      panel.blocks.select(("handler", ("handlers", row.index)))
      self.settle()
      when = panel.blocks.field_widget("when")
      when.setText("holder.alive")
      when.editingFinished.emit()
      self.settle()
      self.assertEqual(logic.handlers(w.project, "Insight")[-1].when, "holder.alive")
      self.assertEqual(w.undo_action.text(), "Undo Edit when")
      panel.picker.set_choice("on", "turn_start")
      self.assertTrue(panel.set_hook())
      self.settle()
      self.assertEqual(logic.handlers(w.project, "Insight")[-1].name, "turn_start")
      self.assertTrue(panel.remove_handler())
      self.settle()
      self.assertEqual(len(logic.handlers(w.project, "Insight")), count)
      # Give Gale Kick's logic to an entry without any, then remove it.
      self.assertTrue(panel.select_owner("move:Gale Kick"))
      self.settle()
      free = [n for n in w.project.names("moves") if n not in {r.name for r in logic.owners(w.project, "move")}]
      self.assertTrue(panel.rename_logic(free[0]))
      self.settle()
      self.assertEqual(panel.owner, ("move", free[0]))
      self.assertTrue(panel.remove_logic())
      self.settle()
      self.assertNotIn(free[0], {r.name for r in logic.owners(w.project, "move")})
      self.close(w)


class TextViewTests(EffectsTestCase):
   """!The text view over the same AST."""

   def test_text_edit_updates_blocks(self) -> None:
      """!Typing is written after the idle time (one undo step) and the blocks follow it.
      @return None
      """
      from capsule_studio.ui.editors.logic.effects_panel import IDLE_MS
      w, panel = self.effects()
      panel.set_view("text")
      self.assertIs(panel.stack.currentIndex(), 1)
      self.assertEqual(panel.code.toPlainText(), self.text(w))
      panel.code.setPlainText(self.text(w).replace(ROLL, "stage target intelligence -2;"))
      self.assertTrue(panel.idle.isActive())
      self.assertNotIn("intelligence -2", self.text(w))   # not yet: the user is still typing
      QtCore.QThread.msleep(IDLE_MS + IDLE_MS // 2)
      self.settle()
      self.assertFalse(panel.idle.isActive())
      self.assertIn("stage target intelligence -2;", self.text(w))
      self.assertIn("stage target intelligence -2", self.block_texts(panel))
      self.assertEqual(w.undo_action.text(), "Undo Edit logic text")
      self.assertFalse(panel.banner.isVisible())
      w.undo()
      self.settle()
      self.assertIn(ROLL, panel.code.toPlainText())
      self.assertIn("stage target intelligence -1", self.block_texts(panel))
      self.close(w)

   def test_bad_text(self) -> None:
      """!Text that does not parse: banner with file:line:col, marks, the blocks keep the last AST (read only);
      Go to shows the error; fixing the text brings the blocks back.
      @return None
      """
      w, panel = self.effects()
      w.show()
      panel.set_view("text")
      self.settle()
      good = self.block_texts(panel)
      broken = self.text(w).replace(ROLL, "stage target intelligence -1")
      line = broken[:broken.index("stage target intelligence -1")].count("\n") + 2   # the error is at the next line
      panel.code.setPlainText(broken)
      self.assertTrue(panel.commit_text())
      self.settle()
      self.assertEqual(self.text(w), broken)
      self.assertTrue(panel.banner.isVisible())
      self.assertIn(f"{MOVES}:{line}:", panel.banner.text())
      self.assertEqual(self.block_texts(panel), good)
      self.assertFalse(panel.editable)
      self.assertFalse(panel.blocks.palette.isEnabled())
      self.assertFalse(panel.blocks.insert_template("yield;"))
      self.assertIn(line, [m[0] for m in panel.code.marks])
      self.assertEqual(panel.diag_list.count(), 1)
      panel.code.go_to(1)
      panel.go_to_error()
      self.assertEqual(panel.code.textCursor().blockNumber() + 1, line)
      panel.code.setPlainText(broken.replace("stage target intelligence -1\n", "stage target intelligence -3;\n"))
      self.assertTrue(panel.commit_text())
      self.settle()
      self.assertFalse(panel.banner.isVisible())
      self.assertTrue(panel.editable)
      self.assertIn("stage target intelligence -3", self.block_texts(panel))
      self.close(w)

   def test_go_to_diagnostic_in_another_file(self) -> None:
      """!A diagnostic of another source selects the owner around it and shows that file.
      @return None
      """
      w, panel = self.effects()
      src = w.project.effect_source(PASSIVES)
      with src.edit("Break"):
         src.data["text"] = src.text.replace("immune;", "inflict holder Nothing;", 1)   # an unknown status
      w.changed()
      self.settle()
      index = next(i for i, d in enumerate(panel.diags) if d.file == PASSIVES and d.severity == "error")
      panel.go_to_diagnostic(index)
      self.settle()
      self.assertEqual(panel.text_rel, PASSIVES)
      self.assertEqual(panel.owner_file(), PASSIVES)
      self.assertEqual(panel.code.toPlainText(), src.text)
      self.assertEqual(panel.code.textCursor().blockNumber() + 1, panel.diags[index].line)
      self.close(w)


class BlockViewTests(EffectsTestCase):
   """!Block operations: only the owner's span changes; one undo step each."""

   def test_insert_move_delete(self) -> None:
      """!Insert from the palette, move up / down and by a drop, delete; each replaces only the owner's span.
      @return None
      """
      from capsule_studio.ui.editors.logic.blocks import drop_target
      w, panel = self.effects()
      src = w.project.effect_source(MOVES)
      body = ("handlers", 0, "body")
      # Insert after the damaging `if` (row 0 of the hit body).
      start, tail = self.span(w, "move:Night Pulse")
      before = self.text(w)
      self.assertTrue(panel.blocks.select(("stmt", body + (0,))))
      self.assertTrue(panel.blocks.insert_template("heal holder 1;"))
      self.settle()
      self.assert_only_owner_changed(before, self.text(w), start, tail)
      self.assertEqual(logic.owner_ast(w.project, "Night Pulse")["handlers"][0]["body"][1]["stmt"], "heal")
      self.assertEqual(src.undo_label(), "Insert statement")
      self.assertEqual(panel.blocks.selected_ref(), ("stmt", body + (1,)))   # the new row is selected
      self.assertIn("heal holder 1", self.block_texts(panel))
      # Down, then up again.
      before = self.text(w)
      self.assertTrue(panel.blocks.move_selected(1))
      self.settle()
      self.assert_only_owner_changed(before, self.text(w), start, tail)
      self.assertEqual(panel.blocks.selected_ref(), ("stmt", body + (2,)))
      self.assertTrue(panel.blocks.move_selected(-1))
      self.settle()
      self.assertEqual(self.text(w), before)
      # A drop onto the `if not user.alive` row (after the heal and a yield) puts it into that block.
      where = QtWidgets.QAbstractItemView.DropIndicatorPosition
      if_ref = ("stmt", body + (3,))
      dest = drop_target(if_ref, panel.blocks.node_at(if_ref), where.OnItem)
      self.assertEqual(dest, (body + (3, "then"), None))
      before = self.text(w)
      panel.blocks.tree.moved.emit(body + (1,), dest[0], dest[1])
      self.settle()
      self.assert_only_owner_changed(before, self.text(w), start, tail)
      then = logic.owner_ast(w.project, "Night Pulse")["handlers"][0]["body"][2]["then"]
      self.assertEqual([s["stmt"] for s in then], ["return", "heal"])
      self.assertEqual(drop_target(("stmt", body + (3,)), {}, where.AboveItem), (body, 3))
      self.assertEqual(drop_target(("handler", ("handlers", 0)), {}, where.BelowItem), (body, None))
      # Delete it.
      self.assertTrue(panel.blocks.select(("stmt", body + (2, "then", 1))))
      before = self.text(w)
      self.assertTrue(panel.blocks.delete_selected())
      self.settle()
      self.assert_only_owner_changed(before, self.text(w), start, tail)
      self.assertNotIn("heal holder 1", self.text(w))
      self.close(w)

   def test_form_fields(self) -> None:
      """!The form edits an expression (with its analysed range), a name and a flag of the selected statement.
      @return None
      """
      w, panel = self.effects("move:Night Pulse")
      path = ("handlers", 0, "body", 3, "then", 0)   # stage target intelligence -1
      self.assertTrue(panel.blocks.select(("stmt", path)))
      self.settle()
      delta = panel.blocks.field_widget("delta")
      self.assertEqual(delta.text(), "-1")
      delta.setText("2")
      delta.textEdited.emit("2")
      self.assertEqual(panel.blocks.range_labels["delta"].text(), "range 2..2")
      delta.editingFinished.emit()
      self.settle()
      self.assertIn("stage target intelligence 2;", self.text(w))
      flag = panel.blocks.field_widget("quiet")
      flag.setChecked(True)
      self.settle()
      self.assertIn("stage target intelligence 2 quiet;", self.text(w))
      self.assertEqual(w.undo_action.text(), "Undo Edit quiet")
      who = panel.blocks.field_widget("who")
      who.setCurrentIndex(who.findText("user"))
      who.activated.emit(who.currentIndex())
      self.settle()
      self.assertIn("stage user intelligence 2 quiet;", self.text(w))
      # The ref picker inserts a read into the expression field.
      panel.blocks.select(("stmt", path))
      self.settle()
      delta = panel.blocks.field_widget("delta")
      delta.setText("")
      panel.blocks.last_expression = delta
      panel.blocks.ref_picker.subject.setCurrentIndex(0)
      fields = [panel.blocks.ref_picker.field.itemText(i) for i in range(panel.blocks.ref_picker.field.count())]
      panel.blocks.ref_picker.field.setCurrentIndex(next(i for i, f in enumerate(fields) if f.startswith("stat ")))
      panel.blocks.ref_picker.arg.setCurrentText("attack")
      panel.blocks.ref_picker.picked.emit(panel.blocks.ref_picker.text())
      self.assertEqual(delta.text(), "holder.stat(attack)")
      self.close(w)


class UndoSaveTests(EffectsTestCase):
   """!Grouped undo across documents and saving."""

   def test_undo_redo_across_group(self) -> None:
      """!The first logic of a battle lists a new source in the battle manifest: undo from the source's page
      takes both back (and the project forgets the source); redo brings both.
      @return None
      """
      data = json.loads(self.battle_json.read_text(encoding="utf-8"))
      data[battle.EFFECTS_KEY] = []
      self.battle_json.write_text(json.dumps(data), encoding="utf-8")
      w, panel = self.effects(None)
      self.assertIs(w.document, w.project.battle)   # no source at all: the page edits the manifest
      panel.has_logic.setChecked(False)
      self.settle()
      self.assertTrue(panel.select_owner("item:Mana Drop"))
      self.settle()
      self.assertTrue(panel.add_logic())
      self.settle()
      rel = "effects/items.ceffect"
      source = w.project.effect_source(rel)
      self.assertIs(w.document, source)
      self.assertEqual(w.project.battle.data[battle.EFFECTS_KEY], [rel])
      self.assertEqual(w.undo_action.text(), "Undo Add logic")
      w.undo()
      self.settle()
      self.assertEqual(w.project.effects, {})
      self.assertEqual(w.project.battle.data[battle.EFFECTS_KEY], [])
      self.assertIs(w.document, w.project.battle)
      w.redo()
      self.settle()
      self.assertIs(w.project.effect_source(rel), source)
      self.assertIn('item "Mana Drop" {}', source.text)
      self.assertIs(w.document, source)
      self.close(w)

   def test_rename_follows_and_undoes_from_effects(self) -> None:
      """!A rename of an entry follows its logic; Undo on the Effects page (the source) undoes both.
      @return None
      """
      w, panel = self.effects()
      doc = w.project.battle
      self.assertTrue(w.run_edit("Rename", lambda: battle.rename_entry(doc, "moves", "Night Pulse", "Dark Pulse"),
                                 doc))
      self.settle()
      self.assertIn('move "Dark Pulse"', self.text(w))
      self.assertTrue(panel.select_owner("move:Dark Pulse"))
      self.settle()
      self.assertIs(w.document, w.project.effect_source(MOVES))
      self.assertEqual(w.undo_action.text(), "Undo Rename" + logic.FOLLOW_LABEL)
      w.undo()
      self.settle()
      self.assertIn("Night Pulse", w.project.names("moves"))
      self.assertIn('move "Night Pulse"', self.text(w))
      self.assertIsNone(doc.undo_label())
      w.redo()
      self.settle()
      self.assertIn("Dark Pulse", w.project.names("moves"))
      self.close(w)

   def test_save_round_trip(self) -> None:
      """!A block edit and a text edit are saved; the files read back the same.
      @return None
      """
      w, panel = self.effects()
      panel.blocks.select(("stmt", ("handlers", 0, "body", 0)))
      self.assertTrue(panel.blocks.insert_template("yield;"))
      self.settle()
      panel.set_view("text")
      panel.code.setPlainText(self.text(w).replace(ROLL, "stage target intelligence -2;"))
      self.assertTrue(w.save_all())   # the typing still pending is written first
      self.settle()
      saved = (self.battle_json.parent / MOVES).read_text(encoding="utf-8")
      self.assertEqual(saved, self.text(w))
      self.assertIn("stage target intelligence -2;", saved)
      again = BattleProject.open(self.battle_json)
      ast = logic.owner_ast(again, "Night Pulse")
      self.assertEqual(ast["handlers"][0]["body"][1], {"stmt": "yield"})
      self.assertIsNone(again.validate())
      self.close(w)


if __name__ == "__main__":
   import unittest
   unittest.main()
