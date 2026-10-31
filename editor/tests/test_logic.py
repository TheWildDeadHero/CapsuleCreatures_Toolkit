#!/usr/bin/env python3
"""!Tests for capsule_studio.core.logic (the battle's effect logic: sources, owners, AST operations,
catalogs, diagnostics, reference walks, linked undo) and the effect / hooks commands (no Qt needed).

Uses a copy of the engine's Starter sample (test_battle.BattleTestCase).
"""
from __future__ import annotations

import io
import json
import re
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # the sibling test helpers (V2 finding)
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, document, engine, logic, pipelines  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import Document, DocumentError  # noqa: E402
from capsule_studio.core.structure import record, stats  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## The Starter's passive logic.
PASSIVES = "effects/passives.ceffect"
## Its move logic.
MOVES = "effects/moves.ceffect"
## Its status and weather logic.
CONDITIONS = "effects/conditions.ceffect"
## Q8 factor of x1.
Q8_ONE = 256


class LogicTestCase(BattleTestCase):
   """!Helpers over the Starter copy."""

   def source(self, rel: str) -> str:
      """!A source's text now.
      @param rel  its path
      @return text
      """
      return self.project.effect_source(rel).text

   def logic_text(self) -> str:
      """!Every source's text.
      @return text
      """
      return "".join(s.text for s in self.project.effects.values())

   def line_of(self, rel: str, text: str, after: str | None = None) -> int:
      """!The 1-based line of a source that first holds a text (so tests follow the sample's layout instead of
      pinning line numbers).
      @param rel    source path
      @param text   text the line holds
      @param after  look only below the first line holding this text, or None
      @return line number
      """
      lines = self.source(rel).splitlines()
      start = 0 if after is None else next(i for i, line in enumerate(lines) if after in line) + 1
      return next(i for i in range(start, len(lines)) if text in lines[i]) + 1


class OwnerTests(LogicTestCase):
   """!Owners: list, find, text, AST get/set, add, remove, rename, format."""

   def test_list_and_find(self) -> None:
      """!Owners in file order, by kind; references by kind:name or a unique name.
      @return None
      """
      rows = logic.owners(self.project)
      self.assertEqual(rows[0].kind, "move")
      self.assertIn(("passive", "Recharge", PASSIVES), [(r.kind, r.name, r.file) for r in rows])
      passives = logic.owners(self.project, "passive")
      self.assertEqual([r.name for r in passives][:3], ["Blaze Heart", "Thick Hide", "Insight"])
      self.assertEqual(passives[0].line, self.line_of(PASSIVES, 'passive "Blaze Heart"'))
      self.assertEqual(passives[0].handlers, 1)
      with self.assertRaisesRegex(DocumentError, "unknown owner kind"):
         logic.owners(self.project, "volcano")
      self.assertEqual(logic.split_owner("move:Flare Claw"), ("move", "Flare Claw"))
      self.assertEqual(logic.split_owner("Odd:Name"), (None, "Odd:Name"))
      self.assertEqual(logic.owner_file(self.project, "Recharge"), PASSIVES)
      self.assertEqual(logic.owner_file(self.project, "weather:Storm"), CONDITIONS)
      with self.assertRaisesRegex(DocumentError, "no logic"):
         logic.owner_file(self.project, "Gale Kick")   # a damaging move without logic: the standard hit
      self.assertTrue(logic.owner_text(self.project, "Recharge").startswith('passive "Recharge" {\n   announce;'))
      self.assertTrue(logic.owner_text(self.project, "Recharge").endswith("\n}"))
      self.assertEqual(logic.owner_kinds(), ["move", "passive", "item", "status", "weather", "volatile",
                                             "side_condition", "field_condition", "global"])
      # the engine's owner kinds, in its order; F1: then the global kind, which names no manifest list
      self.assertEqual(list(logic.kind_lists()) + [logic.global_kind()], logic.owner_kinds())
      self.assertEqual(logic.split_owner("volatile:dazed"), ("volatile", "dazed"))
      self.assertIn(("volatile", "dazed", CONDITIONS), [(r.kind, r.name, r.file) for r in rows])

   def test_ast_round_trip(self) -> None:
      """!An owner's AST set back unchanged changes nothing; a changed AST rewrites only that block.
      @return None
      """
      before = self.source(PASSIVES)
      ast = logic.owner_ast(self.project, "Recharge")
      self.assertEqual(ast["schema"], logic.AST_SCHEMA)
      self.assertEqual(ast["owner"], {"kind": "passive", "name": "Recharge"})
      logic.set_owner_ast(self.project, "Recharge", ast)
      self.assertEqual(self.source(PASSIVES), before)
      self.assertIsNone(self.project.effect_source(PASSIVES).undo_label())
      # Blaze Heart's block becomes canonical text with a new statement; everything else stays byte for byte
      # (its handler is the second entry: a comment comes first).
      heart = logic.owner_ast(self.project, "Blaze Heart")
      logic.insert_statement(heart, ["handlers", 1, "body"], 0, "return;")
      logic.set_owner_ast(self.project, "Blaze Heart", heart, "Blaze Heart")
      after = self.source(PASSIVES)
      old_block = logic.owner_text(BattleProject.open(self.dir / "battle.json"), "Blaze Heart")
      new_block = logic.owner_text(self.project, "Blaze Heart")
      modify = next(line for line in old_block.splitlines() if "modify by" in line)   # the sample's own factor
      self.assertIn(f"      return;\n{modify}", new_block)
      self.assertEqual(after.replace(new_block, old_block), before)
      self.assertEqual(self.project.effect_source(PASSIVES).undo_label(), "Blaze Heart")
      for bad in ({"owner": {"kind": "move", "name": "Blaze Heart"}, "handlers": []}, {"handlers": []},
                  {"schema": "other", "owner": {}}):
         with self.assertRaises(DocumentError, msg=bad):
            logic.set_owner_ast(self.project, "Blaze Heart", bad)

   def test_text(self) -> None:
      """!An owner's block set as text is kept as written; it must be that owner's block.
      @return None
      """
      text = 'passive "Lightfoot" {\n   on try_hit { immune; }   # written my way\n}'
      logic.set_owner_text(self.project, "Lightfoot", text)
      self.assertEqual(logic.owner_text(self.project, "Lightfoot"), text)
      self.assertIsNone(self.project.validate())
      for bad in ('passive "Insight" {}', 'passive "Lightfoot" {', '# c\npassive "Lightfoot" {}', ""):
         with self.assertRaises(DocumentError, msg=bad):
            logic.set_owner_text(self.project, "Lightfoot", bad)

   def test_add_remove_rename(self) -> None:
      """!Add an empty block (the default file holds its kind), remove it again, give logic to another entry.
      @return None
      """
      before = self.source(MOVES)
      self.assertEqual(logic.add_owner(self.project, "move", "Gale Kick"), MOVES)
      self.assertTrue(self.source(MOVES).endswith('}\n\nmove "Gale Kick" {}\n'))
      self.assertIsNone(self.project.validate())   # an empty damaging move gets `hit { damage; }`
      for kind, name in (("move", "Gale Kick"), ("move", "Nothing"), ("volcano", "Gale Kick")):
         with self.assertRaises(DocumentError, msg=(kind, name)):
            logic.add_owner(self.project, kind, name)
      logic.remove_owner(self.project, "move:Gale Kick")
      self.assertEqual(self.source(MOVES), before)
      # Removing a block in the middle keeps one blank line between its neighbours.
      logic.remove_owner(self.project, "Thick Hide")
      self.assertIn('}\n\npassive "Insight" {', self.source(PASSIVES))
      self.assertNotIn('passive "Thick Hide"', self.source(PASSIVES))
      logic.rename_owner(self.project, "Insight", "Thick Hide")
      self.assertIn('passive "Thick Hide" {', self.source(PASSIVES))
      self.assertIsNone(self.project.validate())
      for new in ("Blaze Heart", "Nobody"):
         with self.assertRaises(DocumentError, msg=new):
            logic.rename_owner(self.project, "passive:Thick Hide", new)
      self.assertEqual(logic.add_owner(self.project, "passive", "Insight", CONDITIONS), CONDITIONS)

   def test_new_source(self) -> None:
      """!With no source listed, a first owner creates effects/<list>.ceffect and lists it.
      @return None
      """
      p = BattleProject.create(self.dir / "fresh" / "battle.json", "fresh")
      with p.battle.edit("Move"):
         battle.add_entry(p.battle, "moves", "Poke")
      self.assertEqual(logic.add_owner(p, "move", "Poke"), "effects/moves.ceffect")
      self.assertEqual(p.battle.data[battle.EFFECTS_KEY], ["effects/moves.ceffect"])
      self.assertEqual(p.effect_source("effects/moves.ceffect").text, 'move "Poke" {}\n')
      self.assertIsNone(p.validate())
      p.save_all()
      again = BattleProject.open(self.dir / "fresh" / "battle.json")
      self.assertEqual([r.name for r in logic.owners(again)], ["Poke"])

   def test_format(self) -> None:
      """!format_sources() reports and rewrites sources that are not canonical (one undo step each).
      @return None
      """
      self.assertEqual(logic.format_sources(self.project), {})
      src = self.project.effect_source(CONDITIONS)
      squashed = re.sub(r"   point speed \{\n      (modify by [0-9.]+;)\n   \}", r"   point speed { \1 }", src.text,
                        count=1)   # Shock's handler (its factor is the sample's) on one line
      self.assertNotEqual(squashed, src.text)
      with src.edit("Squash"):
         src.data["text"] = squashed
      changed = logic.format_sources(self.project)
      self.assertEqual(list(changed), [CONDITIONS])
      self.assertEqual(logic.canonical_text(self.project, CONDITIONS), changed[CONDITIONS])
      logic.format_sources(self.project, write=True)
      self.assertEqual(src.undo_label(), "Format logic")
      self.assertEqual(logic.format_sources(self.project), {})
      with src.edit("Break"):
         src.data["text"] = "status {"
      with self.assertRaises(DocumentError):
         logic.format_sources(self.project)


class CatalogTests(LogicTestCase):
   """!Handlers, the hook catalog and the points."""

   def test_handlers(self) -> None:
      """!Handler rows: member, name, per_foe, when, statement count, AST index.
      @return None
      """
      rows = logic.handlers(self.project, "Recharge")
      self.assertEqual([(r.index, r.member, r.name, r.per_foe, r.statements) for r in rows],
                       [(0, "on", "residual", False, 1)])
      rows = logic.handlers(self.project, "weather:Storm")
      self.assertEqual([(r.member, r.name, r.when) for r in rows],
                       [("point", "weather", "move.type == Lightning"), ("point", "weather", "move.type == Fire")])
      self.assertEqual(logic.handlers(self.project, "Flare Claw")[0].member, "phase")

   def test_hooks_and_points(self) -> None:
      """!The hook catalog by owner kind, with bindings, values, verdicts, draws and yields; the ruleset's points.
      @return None
      """
      every = {h["name"]: h for h in logic.hook_catalog()}
      self.assertIn("holder = target", every["try_hit"]["binds"])
      self.assertEqual(every["try_hit"]["results"], ["block", "immune"])
      self.assertEqual(every["before_damage"]["value"], [0, 65535])
      self.assertIsNone(every["switch_in"]["value"])
      self.assertTrue(every["switch_in"]["per_foe"])
      self.assertTrue(every["hit"]["yields"] and every["hit"]["phase"])
      self.assertFalse(every["residual"]["yields"])   # not in this engine yet
      self.assertIn("draw", every["order"]["draws"])
      weather = [h["name"] for h in logic.hook_catalog("weather")]
      self.assertIn("field_residual", weather)
      self.assertNotIn("hit", weather)
      self.assertEqual(every["side_residual"]["owners"], ["side_condition"])   # E5: side conditions are owners
      self.assertIn("try_start", [h["name"] for h in logic.hook_catalog("volatile")])
      self.assertEqual(every["try_start"]["results"], ["block", "immune"])
      with self.assertRaises(DocumentError):
         logic.hook_catalog("volcano")
      points = logic.point_catalog(self.project)
      self.assertEqual([p["name"] for p in points], pipelines.point_names(self.project.ruleset))
      self.assertEqual(points[0]["id"], 0)
      self.assertEqual(points[1]["range"], [1, 1023])


class FunctionCatalogTests(LogicTestCase):
   """!The function picker's catalog (S10): odds() with 2 to 4 arguments (E9)."""

   def test_functions(self) -> None:
      """!Every function of the effect compiler with its argument range and help; odds() calls of 2, 3 and 4
      arguments parse and format back; the palette offers `if odds(...)`.
      @return None
      """
      rows = {name: (lo, hi, sig, text) for name, lo, hi, sig, text in logic.function_catalog()}
      self.assertEqual(set(rows), set(engine.tool("effect_compiler").FUNCTIONS))
      self.assertEqual(rows["odds"][:3], (2, 4, "odds(n, m[, by, on])"))
      self.assertIn("effect_odds", rows["odds"][3])
      self.assertEqual(rows["pick"][2], "pick(i, a[, b, ...])")
      self.assertTrue(all(text for _lo, _hi, _sig, text in rows.values()))
      texts = [logic.function_text("odds", n) for n in (2, 3, 4)]
      self.assertEqual(texts, ["odds(1, 2)", "odds(1, 2, user)", "odds(1, 2, user, target)"])
      for text in texts:
         self.assertEqual(logic.format_expression(logic.parse_expression(text)), text)
      self.assertEqual(logic.function_text("odds", 9), "odds(1, 2, user, target)")   # clamped to 4
      self.assertEqual(logic.function_text("odds", 4, ["target", "user"]), "odds(1, 2, target, user)")
      with self.assertRaises(DocumentError):
         logic.function_text("colour", 1)
      templates = {label: text for _group, label, text in logic.statement_templates(self.project)}
      self.assertEqual(templates["odds"], "if odds(1, 2) {}")
      logic.parse_statement(templates["odds"])


class DiagnosticTests(LogicTestCase):
   """!Diagnostics with file, line and column."""

   def test_clean_and_broken(self) -> None:
      """!The Starter's logic is clean; syntax errors, unknown names, unknown owners and duplicates are errors
      at their place.
      @return None
      """
      self.assertEqual(logic.diagnostics(self.project), [])
      moves = self.project.effect_source(MOVES)
      with moves.edit("Unknown stage"):
         moves.data["text"] = moves.text.replace("stage target attack -1;", "stage target luck -1;")
      errors = [d for d in logic.diagnostics(self.project) if d.severity == "error"]
      self.assertEqual([(d.file, d.line) for d in errors], [(MOVES, self.line_of(MOVES, "stage target luck"))])
      self.assertTrue(errors[0].text().startswith(f"{MOVES}:{errors[0].line}:{errors[0].col}: error: "))
      self.assertIn("luck", errors[0].message)
      self.assertIn("luck", self.project.validate())   # unsaved sources reach the compiler
      passives = self.project.effect_source(PASSIVES)
      with passives.edit("Duplicate and unknown"):
         passives.data["text"] = passives.text + '\npassive "Insight" {}\n\npassive "Nobody" {}\n'
      codes = [d.code for d in logic.diagnostics(self.project) if d.severity == "error"]
      self.assertIn(logic.DUPLICATE_OWNER, codes)
      self.assertIn(logic.UNKNOWN_OWNER, codes)
      with passives.edit("Syntax"):
         passives.data["text"] = 'passive "Insight" {\n   on {\n}\n'
      found = [d for d in logic.diagnostics(self.project) if d.file == PASSIVES]
      self.assertEqual([(d.file, d.line, d.col, d.code) for d in found], [(PASSIVES, 2, 7, logic.SYNTAX)])


class EngineC1Tests(LogicTestCase):
   """!What engine package C1 changed in the logic catalog: optional messages, weather hooks, odds() ranges."""

   def test_optional_messages(self) -> None:
      """!An optional engine message the data leaves out is not offered (nor named by the catalog); one the data
      gives is; the compiler takes the catalog as it is.
      @return None
      """
      bc = engine.tool("battle_compiler")
      given = self.project.battle.data["messages"]
      absent = [m for m in bc.OPTIONAL_MESSAGES if m not in given]
      self.assertTrue(absent, "the Starter leaves optional messages out")
      names = logic.name_lists(self.project)["messages"]
      self.assertFalse(set(absent) & set(names))
      self.assertTrue(set(bc.REQUIRED_MESSAGES) <= set(names))
      self.assertNotIn(bc.ABSENT_MESSAGE, names)
      self.assertEqual(logic.diagnostics(self.project), [])
      with self.project.battle.edit("Give one"):
         given[absent[0]] = "{user} said it."
      self.assertIn(absent[0], logic.name_lists(self.project)["messages"])

   def test_weather_hooks(self) -> None:
      """!A weather may hold the condition-own try_start and already hooks (C1's weather lifecycle).
      @return None
      """
      hooks = [h["name"] for h in logic.hook_catalog("weather")]
      for name in ("try_start", "already", "start", "end"):
         self.assertIn(name, hooks)

   def test_odds_range(self) -> None:
      """!An odds() operand that can pass the engine's 1-65535 is reported where it is (the odds-range check).
      @return None
      """
      moves = self.project.effect_source(MOVES)
      with moves.edit("Wide odds"):
         moves.data["text"] = moves.text.replace("stage target attack -1;",
                                                 "if odds(holder.hp * 2, 2) { stage target attack -1; }", 1)
      found = [d for d in logic.diagnostics(self.project) if d.code == "odds-range"]
      self.assertEqual(len(found), 1)
      self.assertEqual(found[0].file, MOVES)
      self.assertIn("65535", found[0].message)


class ConditionRecordTests(LogicTestCase):
   """!E5 condition records and move flags: the names effect code may use are the manifest's (S5f)."""

   def test_names_from_the_manifest(self) -> None:
      """!Volatiles, side / field conditions and move flags come from the manifest (unsaved edits included); the
      catalog gives a counter to the volatiles the battle compiler gives one; logic of a new side condition
      checks clean and the battle compiles with it.
      @return None
      """
      d = battle.merged(self.project.battle)
      lists = logic.name_lists(self.project)
      self.assertEqual(lists["volatiles"], [v["name"] for v in d["volatiles"]])
      self.assertEqual(lists["move_flags"], d["move_flags"])
      self.assertEqual(lists["side_conditions"], [])
      cat = logic.catalog(self.project)
      self.assertIn("dazed", cat.counters)   # a [min, max] duration
      self.assertNotIn("flinch", cat.counters)
      with self.project.battle.edit("Side condition"):   # the structure manifest is its partner: one step
         st = self.project.structure.data
         st["side_conditions"] = [{"name": "Spikes", "layers": 3, "texts": {"start": "Spikes were scattered!"}}]
         st["move_flags"] = st["move_flags"] + ["spiky"]
      self.assertEqual(logic.name_lists(self.project)["side_conditions"], ["Spikes"])
      self.assertIn("spiky", logic.name_lists(self.project)["move_flags"])
      logic.add_owner(self.project, "side_condition", "Spikes", CONDITIONS)
      logic.set_owner_text(self.project, "side_condition:Spikes",
                           'side_condition "Spikes" {\n   on before_accuracy when move.has(spiky) {\n'
                           '      text start;\n   }\n}')
      errors = [d.text() for d in logic.diagnostics(self.project) if d.severity == "error"]
      self.assertEqual(errors, [])
      self.assertIsNone(self.project.validate())
      self.assertEqual([r.name for r in logic.owners(self.project, "side_condition")], ["Spikes"])
      with self.project.battle.edit("Gone"):
         self.project.structure.data["side_conditions"] = []
      codes = [d.code for d in logic.diagnostics(self.project) if d.severity == "error"]
      self.assertIn(logic.UNKNOWN_OWNER, codes)


class AstOperationTests(LogicTestCase):
   """!The block editor's operations on an owner AST."""

   def test_parse_pieces(self) -> None:
      """!Expressions and statements from text; anything else is refused.
      @return None
      """
      self.assertEqual(logic.parse_expression("-3"), -3)
      self.assertEqual(logic.parse_expression("move.type == Fire"),
                       {"op": "==", "args": [{"ref": "move.type"}, {"name": "Fire"}]})
      self.assertEqual(logic.parse_statement("inflict other Scorch quiet;"),
                       {"stmt": "inflict", "who": "other", "status": "Scorch", "quiet": True})
      for bad in ("1 +", "a b", "", "(1"):
         with self.assertRaises(DocumentError, msg=bad):
            logic.parse_expression(bad)
      for bad in ("inflict other;", "return; return;", "x"):
         with self.assertRaises(DocumentError, msg=bad):
            logic.parse_statement(bad)

   def test_edit_operations(self) -> None:
      """!Insert, move, delete a statement and set an expression; the result compiles.
      @return None
      """
      ast = logic.owner_ast(self.project, "Second Wind")
      body = ["handlers", 0, "body"]
      self.assertEqual(logic.node_at(ast, body + [0, "stmt"]), "if")
      self.assertEqual(logic.insert_statement(ast, body, None, "return;"), 1)
      self.assertTrue(logic.move_statement(ast, body + [1], -1))
      self.assertFalse(logic.move_statement(ast, body + [0], -1))
      self.assertEqual(logic.node_at(ast, body + [0]), {"stmt": "return"})
      self.assertEqual(logic.delete_statement(ast, body + [0]), {"stmt": "return"})
      logic.set_expression(ast, body + [0, "cond"], "field.weather == Storm")
      logic.set_expression(ast, ["handlers", 0, "when"], "holder.alive")
      logic.set_expression(ast, body + [0, "cond", "args", 1], {"name": "Storm"})
      logic.set_owner_ast(self.project, "Second Wind", ast)
      text = logic.owner_text(self.project, "Second Wind")
      self.assertIn("on switch_in when holder.alive {", text)
      self.assertIn("if field.weather == Storm {", text)
      self.assertIsNone(self.project.validate())
      logic.set_expression(ast, ["handlers", 0, "when"], None)
      self.assertNotIn("when", ast["handlers"][0])
      for bad in (lambda: logic.node_at(ast, ["handlers", 9]), lambda: logic.delete_statement(ast, body),
                  lambda: logic.insert_statement(ast, ["handlers", 0], 0, {"stmt": "return"}),
                  lambda: logic.insert_statement(ast, body, 0, {"no": "stmt"}),
                  lambda: logic.move_statement(ast, body + [9], 1), lambda: logic.set_expression(ast, [], 1),
                  lambda: logic.set_expression(ast, body + [0, "cond", "args", 5], 1)):
         with self.assertRaises(DocumentError):
            bad()


class ReferenceTests(LogicTestCase):
   """!Names used inside effect code; renames and removals follow them."""

   def test_name_uses(self) -> None:
      """!Uses by list: stats and stages, flags, statuses, types in comparisons; locals are not names.
      @return None
      """
      uses = logic.name_uses(self.project)
      self.assertEqual(logic.per_owner(uses["stages"]["attack"]), [f"{MOVES}: move Dread Gaze"])
      contact = self.line_of(PASSIVES, "move.has(contact)")
      self.assertIn(f"{PASSIVES}: passive Static Coat line {contact}", uses["move_flags"]["contact"])
      self.assertIn("Shock", uses["statuses"])
      self.assertIn("Earth", uses["types"])
      self.assertIn("Storm", uses["weathers"])
      self.assertIn("physical", uses["categories"])
      self.assertIn("weather", uses["points"])
      self.assertIn("ep", uses["resources"])
      self.assertIn("Recharge", uses["passives"])   # the owner block itself
      self.assertNotIn("earth_move", json.dumps(uses))   # a local
      found = logic.references(self.project.battle, ("types",), "Lightning")
      bolt = self.line_of(CONDITIONS, "== Lightning", 'weather "Storm"')   # the comparison, not the comment
      self.assertIn(f"{CONDITIONS}: weather Storm line {bolt}", found)

   def test_rename_and_remove_follow(self) -> None:
      """!Entry, stat and role renames rewrite the logic (only the blocks that change); removals are refused
      while logic uses the entry, its own block included.
      @return None
      """
      doc = self.project.battle
      before = self.source(PASSIVES)
      with doc.edit("Rename"):
         battle.rename_entry(doc, "types", "Earth", "Ground")
      after = self.source(PASSIVES)
      self.assertEqual(after.replace("move.type == Ground", "move.type == Earth"), before)
      with self.assertRaisesRegex(DocumentError, "passive Recharge"):
         with doc.edit("Remove"):
            battle.remove_entry(doc, "passives", "Recharge")
      with self.assertRaisesRegex(DocumentError, "weather Storm"):
         with doc.edit("Remove"):
            battle.remove_entry(doc, "types", "Lightning")
      with self.assertRaisesRegex(DocumentError, "move Dread Gaze"):
         stats.remove_stat(doc, "attack")
      # A role read by logic (a custom one: the engine's roles keep their names): renames follow it, removal is
      # refused.
      with doc.edit("Custom role"):
         self.project.structure.data["monster_layout"]["roles"].append({"custom": "bond_level", "width": 4})
      wind = self.project.effect_source(PASSIVES)
      with wind.edit("Role"):
         wind.data["text"] = wind.text.replace("   on switch_in {\n      if holder.resource(ep)",
                                               "   on switch_in when holder.role(bond_level) > 0 {\n"
                                               "      if holder.resource(ep)")
      self.assertIsNone(self.project.validate())
      with doc.edit("Role rename"):
         self.assertTrue(record.rename_role(doc, "bond_level", "kinship"))
      self.assertIn("holder.role(kinship) > 0", self.source(PASSIVES))   # F3: the Starter has a bond role
      self.assertIsNone(self.project.validate())
      with self.assertRaisesRegex(DocumentError, "Second Wind"):
         with doc.edit("Role remove"):
            record.remove_role(doc, "kinship")

   def test_manifest_point_code(self) -> None:
      """!Manifest point handler code ({"point", "code"}) is walked and renamed too.
      @return None
      """
      doc = self.project.battle
      with doc.edit("Handler"):
         battle.entry(doc, "items", "Vigor Bar")["handlers"] = [
            {"point": "power", "code": "when move.type == Bio { modify by 1.2; }"}]
      self.assertIsNone(self.project.validate())
      self.assertIn("item Vigor Bar (point power handler)", battle.references(doc, "types", "Bio"))
      with doc.edit("Rename"):
         battle.rename_entry(doc, "types", "Bio", "Plant")
      self.assertEqual(battle.entry(doc, "items", "Vigor Bar")["handlers"][0],
                       {"point": "power", "code": "when move.type == Plant {\n   modify by 1.2;\n}"})
      self.assertIn("item Vigor Bar", pipelines.point_users(self.project.ruleset, "power", doc))
      self.assertIsNone(self.project.validate())

   def test_without_project(self) -> None:
      """!A battle Document opened on its own: only the manifest's code is walked.
      @return None
      """
      doc = Document.open(self.dir / "battle.json", battle.BATTLE_SCHEMA)
      self.assertIsNone(logic.project_of(doc))
      self.assertEqual(logic.references(doc, ("types",), "Earth"), [])
      self.assertIs(logic.project_of(self.project.battle), self.project)

   def test_broken_source_refuses_rename(self) -> None:
      """!A source with a syntax error stops a rename (it could not follow the source); nothing changes.
      @return None
      """
      doc = self.project.battle
      src = self.project.effect_source(MOVES)
      with src.edit("Break"):
         src.data["text"] += "move {"
      before = json.dumps(doc.data)
      with self.assertRaises(DocumentError):
         with doc.edit("Rename"):
            battle.rename_entry(doc, "types", "Earth", "Ground")
      self.assertEqual(json.dumps(doc.data), before)


class LinkedUndoTests(LogicTestCase):
   """!Source edits made in a manifest edit are part of its undo step."""

   def test_undo_redo(self) -> None:
      """!Undo and redo of the manifest step take the source edits along; an edit that fails rolls them back; a
      source changed since undoes that change first (lock step, S14 F1).
      @return None
      """
      doc = self.project.structure   # weathers are the structure manifest's
      cond = self.project.effect_source(CONDITIONS)
      original = cond.text
      with doc.edit("Rename"):
         battle.rename_entry(doc, "weathers", "Storm", "Squall")
      renamed = cond.text
      self.assertIn('weather "Squall"', renamed)
      self.assertEqual(cond.undo_label(), "Rename" + logic.FOLLOW_LABEL)
      self.assertTrue(doc.undo())
      self.assertEqual(cond.text, original)
      self.assertIsNone(self.project.validate())
      self.assertTrue(doc.redo())
      self.assertEqual(cond.text, renamed)
      self.assertIsNone(self.project.validate())
      # A failing edit puts the sources back too.
      with self.assertRaises(DocumentError):
         with doc.edit("Rename and fail"):
            battle.rename_entry(doc, "weathers", "Squall", "Storm")
            raise DocumentError("stop")
      self.assertEqual(cond.text, renamed)
      self.assertIn("Squall", self.project.names("weathers"))
      # The source changed after the rename: undoing the manifest undoes that change first, then the rename.
      with cond.edit("Own edit"):
         cond.data["text"] = renamed + "\n# a note\n"
      self.assertTrue(doc.undo())
      self.assertEqual(cond.text, original)
      self.assertIsNone(self.project.validate())


class GroupedUndoTests(LogicTestCase):
   """!core.document.group(): edits of several Documents as one undo step (S8)."""

   def test_group_of_two_documents(self) -> None:
      """!Two sources edited in one group: undo and redo from either one take both; a failing group reverts.
      @return None
      """
      moves = self.project.effect_source(MOVES)
      cond = self.project.effect_source(CONDITIONS)
      a, b = moves.text, cond.text
      with document.group("Both"):
         with moves.edit("One"):
            moves.data["text"] = a + "\n# one\n"
         with cond.edit("Two"):
            cond.data["text"] = b + "\n# two\n"
      self.assertEqual((moves.undo_label(), cond.undo_label()), ("One", "Two"))
      self.assertTrue(cond.undo())   # from the second one: both go back
      self.assertEqual((moves.text, cond.text), (a, b))
      self.assertTrue(moves.redo())
      self.assertTrue(moves.text.endswith("# one\n") and cond.text.endswith("# two\n"))
      self.assertTrue(moves.undo())
      self.assertEqual((moves.text, cond.text), (a, b))
      self.assertTrue(moves.redo())
      # A group that raises reverts every step made in it, and leaves no undo step.
      with self.assertRaises(DocumentError):
         with document.group("Fails"):
            with moves.edit("Three"):
               moves.data["text"] = "status {"
            raise DocumentError("stop")
      self.assertTrue(moves.text.endswith("# one\n"))
      self.assertEqual(moves.undo_label(), "One")
      self.assertIsNone(document.current_group())

   def test_manifest_edits_group(self) -> None:
      """!A manifest edit opens a group (attach()): source edits inside join its step, also from the source's side.
      @return None
      """
      doc = self.project.structure   # weathers are the structure manifest's
      cond = self.project.effect_source(CONDITIONS)
      self.assertTrue(doc.group_edits)
      original = cond.text
      with doc.edit("Rename"):
         battle.rename_entry(doc, "weathers", "Storm", "Squall")
      self.assertTrue(cond.undo())   # undoing the source's step undoes the manifest's too
      self.assertEqual(cond.text, original)
      self.assertIn("Storm", self.project.names("weathers"))
      self.assertTrue(doc.redo())
      self.assertIn("Squall", self.project.names("weathers"))
      self.assertIn('weather "Squall"', cond.text)

   def test_new_source_undo(self) -> None:
      """!Undoing the first logic of a kind unlists its new source and drops its SourceDocument; redo brings the
      same one back.
      @return None
      """
      p = BattleProject.create(self.dir / "fresh" / "battle.json", "fresh")
      with p.battle.edit("Move"):
         battle.add_entry(p.battle, "moves", "Poke")
      rel = logic.add_owner(p, "move", "Poke")
      source = p.effect_source(rel)
      self.assertEqual(source.undo_label(), "Add logic")
      self.assertTrue(source.undo())   # one step: the listing and the block
      self.assertNotIn(rel, p.effects)
      self.assertNotIn(battle.EFFECTS_KEY, p.battle.data)
      self.assertEqual(p.names("moves"), ["Poke"])
      self.assertTrue(p.battle.redo())
      self.assertIs(p.effect_source(rel), source)
      self.assertEqual(source.text, 'move "Poke" {}\n')
      self.assertTrue(p.battle.undo())
      self.assertEqual(p.effects, {})
      self.assertIsNone(p.validate())


class S8CoreTests(LogicTestCase):
   """!What the Effects panel reads: the parse cache, budgets, analysed ranges, the block form's field model,
   the palette, text commits (S8)."""

   def test_parse_cache(self) -> None:
      """!A source is parsed once per revision; callers get their own AST copies.
      @return None
      """
      src = self.project.effect_source(MOVES)
      first = logic._parse_shared(MOVES, src)
      self.assertIs(logic._parse_shared(MOVES, src), first)
      copied = logic._parse(MOVES, src)
      self.assertIsNot(copied.ast, first.ast)
      self.assertEqual(copied.ast, first.ast)
      node = copied.owners[0][0]
      self.assertEqual(copied.positions[id(node)], first.positions[id(first.owners[0][0])])
      logic.add_owner(self.project, "move", "Gale Kick")
      self.assertIsNot(logic._parse_shared(MOVES, src), first)
      self.assertEqual(logic.diagnostics(self.project), logic.diagnostics(self.project))

   def test_budgets(self) -> None:
      """!The compiler's measures of each handler; none while the logic has errors.
      @return None
      """
      rows = logic.budgets(self.project, "Flare Claw")
      self.assertEqual(len(rows), 1)
      b = rows[0]
      self.assertEqual((b.index, b.stack_limit, b.events_limit), (0, 16, 128))
      self.assertGreater(b.stack, 0)
      self.assertGreater(b.events, 0)
      self.assertTrue(b.draws and b.yields)   # odds() draws; the hit yields
      point = logic.budgets(self.project, "status:Scorch")[-1]   # after the record's own handler
      self.assertEqual((point.stack, point.events, point.draws), (0, 0, False))
      logic.set_source_text(self.project, MOVES, self.source(MOVES).replace("damage;", "damage_hp nobody 1;", 1))
      self.assertIsNone(logic.budgets(self.project, "Flare Claw"))

   def test_expression_range(self) -> None:
      """!Ranges with the handler's context: values, comparisons, locals declared before the statement.
      @return None
      """
      # Scorch's handler is its second entry (a comment comes first)
      factor = float(re.search(r"modify by ([0-9.]+);", logic.owner_text(self.project, "Scorch")).group(1))
      q8 = round(factor * Q8_ONE)   # the sample's factor in q8
      self.assertEqual(logic.expression_range(self.project, "Scorch", ["handlers", 1, "body", 0, "value"]), (q8, q8))
      self.assertEqual(logic.expression_range(self.project, "Scorch", ["handlers", 1, "when"]), (0, 1))
      self.assertEqual(logic.expression_range(self.project, "Lightfoot", ["handlers", 0, "body", 0, "value"]),
                       (0, 1))   # let earth_move = a comparison
      path = ["handlers", 0, "body", 1, "cond"]
      self.assertEqual(logic.expression_range(self.project, "Lightfoot", path, "earth_move + 3"), (3, 4))
      self.assertIsNone(logic.expression_range(self.project, "Lightfoot", ["handlers", 0, "body", 5, "value"]))
      self.assertIsNone(logic.expression_range(self.project, "Lightfoot", ["nowhere"]))

   def test_block_helpers(self) -> None:
      """!Moving a statement into another block, the form's fields, the palette, head texts.
      @return None
      """
      ast = logic.owner_ast(self.project, "Flare Claw")
      body = ast["handlers"][0]["body"]
      last = body[-1]
      new = logic.move_statement_to(ast, ["handlers", 0, "body", len(body) - 1], ["handlers", 0, "body", 0, "then"],
                                    0)
      self.assertEqual(new, ["handlers", 0, "body", 0, "then", 0])
      self.assertIs(logic.node_at(ast, new), last)
      # Down the same block: the index counts before the move.
      new = logic.move_statement_to(ast, ["handlers", 0, "body", 0], ["handlers", 0, "body"], 2)
      self.assertEqual(new, ["handlers", 0, "body", 1])
      with self.assertRaises(DocumentError):
         logic.move_statement_to(ast, ["handlers", 0, "body", 1], ["handlers", 0, "body", 1, "then"], 0)
      logic.set_owner_ast(self.project, "Flare Claw", ast)
      s = {"stmt": "damage_hp", "who": "user", "amount": 1}
      fields = logic.statement_fields(s)
      self.assertEqual(fields[:2], [("who", "subj"), ("amount", "expr")])
      self.assertIn(("quiet", "flag"), fields)
      self.assertEqual(logic.statement_fields({"stmt": "switch"})[1], ("mode", "mode:pass,ask,random"))
      logic.set_field(s, [], "amount", "expr", "dealt / 2")
      logic.set_field(s, [], "quiet", "flag", "1")
      self.assertEqual(logic.statement_text(s), "damage_hp user dealt / 2 quiet")
      logic.set_field(s, [], "quiet", "flag", "")
      self.assertEqual(logic.field_text(s, "amount", "expr"), "dealt / 2")
      for bad in (("amount", "expr", ""), ("amount", "expr", "1 +"), ("max", "int", "x")):
         with self.assertRaises(DocumentError, msg=bad):
            logic.set_field(s, [], *bad)
      with self.assertRaises(DocumentError):
         logic.set_field({"stmt": "switch", "who": "holder", "mode": "ask"}, [], "mode", "mode:pass,ask,random", "x")
      templates = logic.statement_templates(self.project)
      self.assertIn("Control", {g for g, _l, _t in templates})
      for _group, label, text in templates:
         if text is not None:
            logic.parse_statement(text)   # every template parses
      self.assertIn(("Actions", "inflict", "inflict target Scorch;"), templates)   # the first status
      self.assertEqual(logic.handler_text({"on": "switch_in", "per_foe": True, "body": []}), "on switch_in per_foe")
      words = logic.words()
      self.assertIn("chance", words["keywords"])
      self.assertIn("inflict", words["primitives"])
      self.assertIn("switch_in", words["hooks"])
      self.assertIn("battler", logic.ref_catalog())

   def test_text_commit(self) -> None:
      """!A whole source's text as written: broken text is kept (diagnostics name file, line and column) and
      the display walks leave it out.
      @return None
      """
      logic.set_source_text(self.project, MOVES, self.source(MOVES).replace("inflict target Scorch quiet;",
                                                                          "inflict target Scorch quiet", 1))
      self.assertEqual(self.project.effect_source(MOVES).undo_label(), "Edit logic text")
      error = logic.source_error(self.project, MOVES)
      self.assertEqual((error.file, error.code), (MOVES, logic.SYNTAX))
      self.assertGreater(error.line, 0)
      self.assertEqual(logic.diagnostics(self.project), [error])
      self.assertIsNone(logic.source_error(self.project, PASSIVES))
      self.assertIn(("statuses", "Scorch"), logic.point_users(self.project.battle))
      with self.assertRaises(DocumentError):
         logic.owners(self.project)


class LogicCliTests(LogicTestCase):
   """!The effect and hooks commands."""

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command.
      @param argv  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()

   def test_read_commands(self) -> None:
      """!list, show, ast, check, format, hooks.
      @return None
      """
      b = self.dir / "battle.json"
      status, out = self.run_cli("battle", b, "effect", "list", "--kind", "weather")
      storm = self.line_of(CONDITIONS, 'weather "Storm"')
      self.assertEqual((status, out), (0, f"weather:Storm  {CONDITIONS}:{storm}  2 handler(s)\n"))
      status, out = self.run_cli("battle", b, "effect", "show", "Recharge")
      self.assertEqual(status, 0)
      self.assertTrue(out.startswith(f"# {PASSIVES}\npassive \"Recharge\" {{\n"))
      self.assertIn("# [0] on residual: 1 statement(s)", out)
      status, out = self.run_cli("battle", b, "effect", "ast", "status:Shock")
      handlers = json.loads(out)["handlers"]
      self.assertEqual(next(h for h in handlers if "point" in h)["point"], "speed")   # after a comment entry
      status, out = self.run_cli("battle", b, "effect", "check")
      self.assertEqual((status, out.strip()), (0, "logic checks: 0 warning(s); battle data compiles"))
      status, out = self.run_cli("battle", b, "effect", "format")
      self.assertEqual(status, 0)
      self.assertIn(f"# file: {CONDITIONS}\n", out)
      status, out = self.run_cli("battle", b, "effect", "format", "--write")
      self.assertEqual((status, out), (0, "every source is canonical\n"))
      status, out = self.run_cli("battle", b, "hooks", "--kind", "move")
      self.assertIn("hit: move phase per target", out)
      self.assertNotIn("point power", out)   # moves have no point handlers
      status, out = self.run_cli("battle", b, "hooks")
      self.assertIn("point weather: id 2, holder user, sources weather", out)
      self.assertEqual(self.run_cli("battle", b, "effect", "show", "Nobody")[0], 1)

   def test_edit_commands(self) -> None:
      """!set, add, rename, remove, format --write; edits that do not compile are not saved.
      @return None
      """
      b = self.dir / "battle.json"
      saved = (self.dir / PASSIVES).read_text(encoding="utf-8")
      foot_before = logic.owner_text(self.project, "Lightfoot")
      text = 'passive "Lightfoot" {\n   on try_hit { immune; }\n}'
      self.assertEqual(self.run_cli("battle", b, "effect", "set", "Lightfoot", "--text", text)[0], 0)
      self.assertIn(text, (self.dir / PASSIVES).read_text(encoding="utf-8"))
      block = self.dir / "block.ceffect"
      block.write_text('passive "Lightfoot" {\n   on try_hit { stage holder luck 1; }\n}\n', encoding="utf-8")
      status, out = self.run_cli("battle", b, "effect", "set", "Lightfoot", "--file", block)
      self.assertEqual(status, 1)
      self.assertIn("not saved", out)
      self.assertIn(text, (self.dir / PASSIVES).read_text(encoding="utf-8"))
      status, out = self.run_cli("battle", b, "effect", "format", "--write")
      self.assertEqual((status, out), (0, f"formatted {PASSIVES}\n"))
      self.assertEqual((self.dir / PASSIVES).read_text(encoding="utf-8"),
                       saved.replace(foot_before, 'passive "Lightfoot" {\n   on try_hit {\n      immune;\n   }\n}'))
      status, out = self.run_cli("battle", b, "effect", "add", "move", "Gale Kick")
      self.assertEqual((status, out), (0, f"added move:Gale Kick to {MOVES}\n"))
      self.assertEqual(self.run_cli("battle", b, "effect", "rename", "move:Gale Kick", "Tide Slam")[0], 0)
      self.assertIn('move "Tide Slam" {}', (self.dir / MOVES).read_text(encoding="utf-8"))
      self.assertEqual(self.run_cli("battle", b, "effect", "remove", "move:Tide Slam")[0], 0)
      self.assertNotIn("Tide Slam", (self.dir / MOVES).read_text(encoding="utf-8"))
      self.assertEqual(self.run_cli("battle", b, "effect", "add", "move", "Nothing")[0], 1)
      # check fails on an error (here: logic of an unknown move, written by hand).
      with (self.dir / MOVES).open("a", encoding="utf-8") as f:
         f.write('\nmove "Nothing" {}\n')
      status, out = self.run_cli("battle", b, "effect", "check")
      self.assertEqual(status, 1)
      self.assertIn(f"{MOVES}:", out)
      self.assertIn("unknown move 'Nothing'", out)


if __name__ == "__main__":
   unittest.main()
