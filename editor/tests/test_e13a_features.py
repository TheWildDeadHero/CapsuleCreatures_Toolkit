#!/usr/bin/env python3
"""!Tests for the studio side of the engine's E13a (package S16), no Qt:

- core.expressions: the ruleset language's operator levels (bit operators
  above the comparisons), spans, the engine's parse, input names;
- core.structure.species_fields and `battle FILE species-field ...`;
- core.structure.record's stored toggle (unstored custom roles) and
  `battle FILE role stored|preview|import`;
- core.structure.progression's draw order, species fields in derived
  expressions, unstored roles in the generation list;
- core.structure.record_preview (derived_values() / rederive() /
  import_rederived()).

The Starter (neutral) tests run everywhere; the ones on the reference repo's
compat/classic/record data set (an unstored role, species fields, bit operators,
a low-first wide draw) are skipped without the reference repo. Expected values
come from the data or the engine's own mirrors, not written down.
"""
from __future__ import annotations

import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import battle, engine, expressions  # noqa: E402
from capsule_studio.core.battle import BattleProject  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.structure import progression, record, record_preview, species_fields  # noqa: E402
from sample_data import (classic_data, classic_record_data, copy_battle_data, needs_classic,  # noqa: E402
                         needs_classic_record)
from test_battle import BattleTestCase  # noqa: E402

## The classic record data set's unstored role (computed on read).
UNSTORED = "shiny"
## A stored custom role of the data set without a generation entry.
PLAIN_CUSTOM = "friendship"
## The data set's species field the gender expression reads, and its derived role.
FIELD, FIELD_ROLE = "gender_ratio", "gender"
## The data set's wide draw (the seed: two draws, low half first).
WIDE_ROLE = "seed"
## A species of the data set.
SPECIES = "Mothlet"


def run_cli(*argv: str) -> tuple[int, str]:
   """!Runs the CLI.
   @param argv  arguments
   @return (exit status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      try:
         status = cli(list(argv))
      except SystemExit as e:
         status = int(e.code or 0)
   return status, out.getvalue() + err.getvalue()


class ExpressionLanguageTests(unittest.TestCase):
   """!core.expressions reads the language from the engine."""

   def test_levels_spans_check(self) -> None:
      """!Bit operators bind tighter than the comparisons; spans classify a classic-style expression; the engine's
      parser refuses an unknown name; dotted input names are refused for ruleset inputs.
      @return None
      """
      rc = engine.tool("ruleset_compiler")
      levels = expressions.precedence()
      self.assertEqual(levels[:-1], [list(x) for x in rc.Parser.LEVELS])
      flat = [op for level in levels for op in level]
      for bit in rc.BIT_OPS + rc.SHIFT_OPS:
         self.assertGreater(flat.index(bit), flat.index("=="))
         self.assertGreater(flat.index(bit), flat.index("<"))
      self.assertIn("~", levels[-1])
      self.assertIn("&", expressions.precedence_text())
      names = expressions.Names(["seed_lo", "species.ratio"], ["MASK"], expressions.functions())
      text = "if((seed_lo & MASK) < species.ratio, ~1, other)"
      kinds = {text[s.start:s.end]: s.kind for s in expressions.spans(text, names)}
      self.assertEqual(kinds["if"], expressions.KIND_FUNCTION)
      self.assertEqual(kinds["&"], expressions.KIND_BIT)
      self.assertEqual(kinds["~"], expressions.KIND_BIT)
      self.assertEqual(kinds["<"], expressions.KIND_OPERATOR)
      self.assertEqual(kinds["MASK"], expressions.KIND_CONSTANT)
      self.assertEqual(kinds["species.ratio"], expressions.KIND_FIELD)
      self.assertEqual(kinds["other"], expressions.KIND_UNKNOWN)
      self.assertEqual(expressions.unknown_names(text, names), ["other"])
      self.assertIn("other", expressions.check(text, names) or "")
      self.assertIsNone(expressions.check("seed_lo << 3 | seed_lo >> 1 ^ ~MASK", names))
      self.assertEqual(expressions.spans("a $ b")[1].kind, expressions.KIND_INVALID)
      self.assertIsNone(expressions.input_name_error("gene"))
      self.assertIn("identifier", expressions.input_name_error("species.ratio") or "")


class SpeciesFieldLogicTests(unittest.TestCase):
   """!C5: species fields effect logic reads (the classic sample's Trip Kick: `target.species_field(weight)`)."""

   @needs_classic
   def test_rename_and_remove_follow_logic(self) -> None:
      """!The field's readers list the logic owner; a rename rewrites the logic too (it compiles after, one undo step
      takes it back); a removal is refused while the logic reads it (review3 probe p_rename).
      @return None
      """
      with tempfile.TemporaryDirectory() as tmp:
         folder = Path(tmp)
         copy_battle_data(classic_data() / "battle.json", folder)
         p = BattleProject.open(folder / "battle.json")
         doc = p.structure
         self.assertIsNone(p.error_now())
         names = species_fields.field_names(doc)   # weight, then the sample's other fields (G3 / G4)
         row = next(r for r in species_fields.field_rows(doc) if r["name"] == "weight")
         self.assertIn("effects/moves.ceffect: move Trip Kick", row["readers"])
         with self.assertRaises(DocumentError) as refused:
            with doc.edit("Remove"):
               species_fields.remove_field(doc, "weight")
         self.assertIn("read by effect logic", str(refused.exception))
         with doc.edit("Rename"):
            self.assertGreater(species_fields.rename_field(doc, "weight", "mass"), 0)
         self.assertIsNone(p.error_now())
         source = p.effects["effects/moves.ceffect"].text
         self.assertIn("target.species_field(mass)", source)
         self.assertNotIn("species_field(weight)", source)
         doc.undo()
         self.assertIn("target.species_field(weight)", p.effects["effects/moves.ceffect"].text)
         self.assertEqual(species_fields.field_names(doc), names)


class SpeciesFieldStarterTests(BattleTestCase):
   """!Species fields on the neutral Starter (its own: G3's recruit_rate, G4's training yields; a new one goes after
   them)."""

   def test_add_value_rename_remove(self) -> None:
      """!Add a field, give a species a value (the default is not written), rename (species follow, one undo step of
      both manifests), narrow the width (refused while a value does not fit), remove.
      @return None
      """
      doc, content = self.project.structure, self.project.battle
      given = species_fields.field_names(doc)
      bc = engine.tool("battle_compiler")
      self.assertEqual(species_fields.max_fields(), bc.MAX_SPECIES_FIELDS)
      before_s, before_c = copy.deepcopy(doc.data), copy.deepcopy(content.data)
      with doc.edit("Add"):
         self.assertEqual(species_fields.add_field(doc, "size_class", 4, 3), len(given))
      self.assertEqual(doc.data["species_fields"][-1], {"name": "size_class", "width": 4, "default": 3})
      sp = battle.entries(content, "species")[0]["name"]
      own = dict(battle.entry(content, "species", sp).get("fields", {}))
      with content.edit("Value"):
         self.assertTrue(species_fields.set_value(content, sp, "size_class", 9))
      self.assertEqual(battle.entry(content, "species", sp)["fields"], {**own, "size_class": 9})
      with content.edit("Default"):
         species_fields.set_value(content, sp, "size_class", 3)   # the default: dropped
      self.assertEqual(battle.entry(content, "species", sp).get("fields", {}), own)
      with content.edit("Value"):
         species_fields.set_value(content, sp, "size_class", 9)
      with self.assertRaises(DocumentError):
         with content.edit("Too big"):
            species_fields.set_value(content, sp, "size_class", 16)
      with doc.edit("Rename"):
         self.assertEqual(species_fields.rename_field(doc, "size_class", "bulk"), 1)
      self.assertEqual(battle.entry(content, "species", sp)["fields"], {**own, "bulk": 9})
      self.assertIsNone(self.project.error_now())
      doc.undo()
      self.assertEqual(battle.entry(content, "species", sp)["fields"], {**own, "size_class": 9})   # both files
      with self.assertRaises(DocumentError):
         with doc.edit("Narrow"):
            species_fields.set_field(doc, "size_class", "width", 3)   # 9 needs 4 bits
      with self.assertRaises(DocumentError):
         with doc.edit("Bad"):
            species_fields.add_field(doc, "Bad Name", 4)
      with doc.edit("Remove"):
         self.assertEqual(species_fields.remove_field(doc, "size_class"), [f"species {sp}"])
      self.assertEqual(battle.entry(content, "species", sp).get("fields", {}), own)
      self.assertEqual(species_fields.field_names(doc), given)
      self.assertIsNone(self.project.error_now())
      while doc.undo() or content.undo():
         pass
      self.assertEqual((doc.data, content.data), (before_s, before_c))

   def test_cli(self) -> None:
      """!`species-field add / value / list / rename / set / remove` save when the data compiles.
      @return None
      """
      path = str(self.dir / "battle.json")
      sp = battle.entries(self.project.battle, "species")[0]["name"]
      own = dict(battle.entry(self.project.battle, "species", sp).get("fields", {}))
      self.assertEqual(run_cli("battle", path, "species-field", "add", "bulk", "--width", "3")[0], 0)
      status, out = run_cli("battle", path, "species-field", "value", sp, "bulk", "5")
      self.assertEqual(status, 0, out)
      status, out = run_cli("battle", path, "species-field", "value", sp)
      self.assertIn("bulk 5", out)
      status, out = run_cli("battle", path, "species-field", "list")
      self.assertIn("bulk: 3 bit(s) (0-7)", out)
      self.assertIn(f"/{species_fields.max_fields()} species fields", out)
      status, out = run_cli("battle", path, "species-field", "set", "bulk", "width", "2")
      self.assertNotEqual(status, 0)
      self.assertEqual(run_cli("battle", path, "species-field", "rename", "bulk", "mass")[0], 0)
      saved = json.loads((self.dir / "battle.json").read_text(encoding="utf-8"))
      self.assertEqual(next(s for s in saved["species"] if s["name"] == sp)["fields"], {**own, "mass": 5})
      self.assertEqual(run_cli("battle", path, "species-field", "remove", "mass")[0], 0)
      saved = json.loads((self.dir / "battle.json").read_text(encoding="utf-8"))
      self.assertEqual(next(s for s in saved["species"] if s["name"] == sp).get("fields", {}), own)


class FormulaArgumentTests(BattleTestCase):
   """!A named formula's argument names are identifiers (E13a INPUT_NAME)."""

   def test_dotted_argument_refused(self) -> None:
      """!A dotted argument is refused with the engine's reason; a plain one is fine.
      @return None
      """
      doc = self.project.ruleset
      with self.assertRaises(DocumentError) as e:
         with doc.edit("Args"):
            battle.set_formula(doc, "share", expr="0", args=["species.ratio"])
      self.assertIn("identifier", str(e.exception))
      with doc.edit("Args"):
         battle.set_formula(doc, "share", expr="0", args=["amount"])
      self.assertEqual(doc.data["formulas"]["share"]["args"], ["amount"])


@needs_classic_record
class ClassicRecordTests(BattleTestCase):
   """!The reference repo's compat/classic/record data set: everything E13a added."""

   def sample(self) -> Path:
      """!The reference repo's record data set.
      @return folder
      """
      folder = classic_record_data()
      assert folder is not None
      return folder

   def test_unstored_role_rows_and_toggle(self) -> None:
      """!The unstored role: no bits, out of the transfer, its ID after every stored custom role's; stored again it
      takes bits and the IDs follow the layout's; unstoring a role without a derived or constant entry is refused;
      the generation guard refuses a random entry for an unstored role.
      @return None
      """
      doc = self.project.structure
      compiled = record.compile_record(doc)[0]
      rows = {r["name"]: r for r in record.role_rows(doc)}
      self.assertFalse(rows[UNSTORED]["stored"])
      self.assertEqual(rows[UNSTORED]["bits"], 0)
      self.assertEqual(rows[UNSTORED]["id"], compiled["unstored_ids"][UNSTORED])
      for name, rid in compiled["custom_ids"].items():
         self.assertEqual(rows[name]["id"], rid)
      self.assertEqual(record.transfer_text(rows[UNSTORED]), record.TRANSFER_UNSTORED)
      self.assertIn(UNSTORED, record.layout_report(doc)["unstored"])
      self.assertIn(UNSTORED, progression.role_choices(doc))
      self.assertIsNone(progression.compile_progress(doc)["generation"])
      size = compiled["bytes"]
      held = sum(r["bits"] for r in record.role_rows(doc))
      with doc.edit("Store"):
         self.assertTrue(record.set_stored(doc, UNSTORED, True))
      again = record.compile_record(doc)[0]
      self.assertEqual({r["name"]: r["id"] for r in record.role_rows(doc) if r["kind"] == record.KIND_CUSTOM},
                       again["custom_ids"])
      self.assertEqual(sum(r["bits"] for r in record.role_rows(doc)), held + rows[UNSTORED]["width"])
      self.assertGreaterEqual(again["bytes"], size)
      self.assertNotIn(record.STORED_KEY, next(e for e in doc.data["monster_layout"]["roles"]
                                                if isinstance(e, dict) and e.get("custom") == UNSTORED))
      doc.undo()
      self.assertFalse({r["name"]: r for r in record.role_rows(doc)}[UNSTORED]["stored"])
      with self.assertRaises(DocumentError) as e:
         with doc.edit("Unstore"):
            record.set_stored(doc, PLAIN_CUSTOM, False)
      self.assertIn("exactly one", str(e.exception))
      with self.assertRaises(DocumentError):
         with doc.edit("Engine"):
            record.set_stored(doc, WIDE_ROLE, False)
      k = progression.fillers(doc, UNSTORED)[0]
      with self.assertRaises(DocumentError):
         with doc.edit("Way"):
            progression.set_way(doc, k, progression.RANDOM_WAY)
      self.assertIsNone(self.project.error_now())

   def test_generation_order_and_species_inputs(self) -> None:
      """!The wide seed draws low first (wide_low_first, two draws); the order is set and refused on a range of one
      draw; derived inputs list the species fields; a species' fields feed the preview (record_inputs()); a field
      rename follows the expression; a role rename leaves species.NAME alone.
      @return None
      """
      doc = self.project.structure
      bc = engine.tool("battle_compiler")
      rows = progression.generation_rows(doc)
      seed = next(r for r in rows if r["role"] == WIDE_ROLE)
      self.assertTrue(seed["wide"])
      self.assertEqual(seed["kind"], bc.WIDE_ORDERS[seed["order"]])
      self.assertEqual(seed["draws"], bc.DRAWS_PER_KIND[seed["kind"]])
      self.assertEqual(progression.wide_orders(), list(bc.WIDE_ORDERS))
      with doc.edit("Order"):
         progression.set_order(doc, seed["index"], None)
      self.assertEqual(progression.generation_rows(doc)[seed["index"]]["kind"],
                       bc.WIDE_ORDERS[bc.DEFAULT_WIDE_ORDER])
      doc.undo()
      narrow = next(r for r in rows if r["way"] == progression.RANDOM_WAY and not r["wide"])
      with self.assertRaises(DocumentError):
         with doc.edit("Order"):
            progression.set_order(doc, narrow["index"], progression.wide_orders()[-1])
      inputs = progression.derived_inputs(doc)
      self.assertIn(bc.SPECIES_PREFIX + FIELD, inputs)
      self.assertIn(UNSTORED, [r["role"] for r in rows])
      self.assertFalse([r for r in rows if r["error"]], "every entry compiles on its own")
      values = progression.species_values(doc, SPECIES)
      ratio = battle.entry(self.project.battle, "species", SPECIES).get("fields", {}).get(FIELD)
      self.assertEqual(values[bc.SPECIES_PREFIX + FIELD], ratio)
      gender = next(r["index"] for r in rows if r["role"] == FIELD_ROLE)
      # the engine's mirror on the compiled data agrees with the preview (low byte below / above the ratio)
      compiled = self.project.compile()[0]
      entry = compiled["rules"]["progress"]["generation"][gender]
      for seed_lo in (0, ratio + 1):
         given = {**{n: 0 for n in inputs if n != progression.element_input()}, **values, "seed_lo": seed_lo}
         self.assertEqual(progression.preview(doc, gender, {"seed_lo": seed_lo}, 0, SPECIES),
                          bc.run_derived(entry, given, 0))
      with doc.edit("Rename field"):
         species_fields.rename_field(doc, FIELD, "female_odds")
      self.assertIn(bc.SPECIES_PREFIX + "female_odds", progression.entries_of(doc)[gender]["derived"])
      self.assertIsNone(self.project.error_now())
      doc.undo()
      with self.assertRaises(DocumentError):
         with doc.edit("Remove field"):
            species_fields.remove_field(doc, FIELD)
      readers = species_fields.field_rows(doc)[0]["readers"]
      self.assertTrue(readers)
      # a role named like a field: renaming it leaves species.NAME as it is
      with doc.edit("Rename role"):
         record.rename_role(doc, PLAIN_CUSTOM, FIELD)
      with doc.edit("Rename role back"):
         record.rename_role(doc, FIELD, PLAIN_CUSTOM)
      self.assertIn(bc.SPECIES_PREFIX + FIELD, progression.entries_of(doc)[gender]["derived"])

   def test_record_and_transfer_previews(self) -> None:
      """!derived_rows() is the engine's derived_values() / rederive(); a record from a sender whose layout lacks the
      gender role comes in with gender re-derived (import_rederived()), one that has it keeps the sender's value.
      @return None
      """
      bc = engine.tool("battle_compiler")
      p = self.project
      roles = record_preview.input_roles(p)
      self.assertIn("owner_id", roles)
      self.assertNotIn(UNSTORED, roles)
      values = {"seed": 0x12345678, "owner_id": 1000, "owner_secret": 2000}
      rows = {r["role"]: r for r in record_preview.derived_rows(p, SPECIES, values)}
      compiled = p.compile()[0]
      rec = record_preview.record_of(compiled, SPECIES, values)
      self.assertEqual(rows[UNSTORED]["state"], record_preview.STATE_UNSTORED)
      self.assertEqual(rows[UNSTORED]["value"], bc.derived_values(compiled, rec)[UNSTORED])
      self.assertEqual(rows[FIELD_ROLE]["rederived"], bc.rederive(compiled, rec)[FIELD_ROLE])
      self.assertIsNone(rows[UNSTORED]["rederived"])
      # this data as the sender: the gender it holds is kept
      sent = {**values, FIELD_ROLE: 2}
      same = record_preview.transfer_preview(p, SPECIES, sent)
      self.assertEqual(same["record"][FIELD_ROLE], 2)
      self.assertNotIn(FIELD_ROLE, same["rederived"])
      self.assertNotIn(UNSTORED, same["record"])
      # a sender without the gender role (and its entry): the receiver re-derives it
      sender = Path(tempfile.mkdtemp(prefix="capsule_sender_"))
      self.addCleanup(shutil.rmtree, sender, True)
      copy_battle_data(self.dir / "battle.json", sender)
      other = BattleProject.open(sender / "battle.json")
      sdoc = other.structure
      with sdoc.edit("Drop gender"):
         record.remove_role(sdoc, FIELD_ROLE)
      self.assertIsNone(other.error_now())
      other.save_all()
      got = record_preview.transfer_preview(p, SPECIES, sent, sender / "battle.json")
      self.assertIn(FIELD_ROLE, got["rederived"])
      expected = bc.rederive(compiled, {**got["plain"]}, got["received"])[FIELD_ROLE]
      self.assertEqual(got["record"][FIELD_ROLE], expected)
      self.assertEqual(got["record"][FIELD_ROLE], rows[FIELD_ROLE]["rederived"])

   def test_cli(self) -> None:
      """!`role stored`, `role preview`, `role import`, `generation order` and `generation preview --species`.
      @return None
      """
      path = str(self.dir / "battle.json")
      status, out = run_cli("battle", path, "role", "list")
      self.assertIn("unstored (computed on read)", out)
      status, out = run_cli("battle", path, "role", "stored", PLAIN_CUSTOM, "off")
      self.assertNotEqual(status, 0)
      self.assertIn("exactly one", out)
      self.assertEqual(run_cli("battle", path, "role", "stored", UNSTORED, "on")[0], 0)
      saved = json.loads((self.dir / "structure.json").read_text(encoding="utf-8"))
      entry = next(e for e in saved["monster_layout"]["roles"] if isinstance(e, dict) and e.get("custom") == UNSTORED)
      self.assertNotIn("stored", entry)
      self.assertEqual(run_cli("battle", path, "role", "stored", UNSTORED, "off")[0], 0)
      status, out = run_cli("battle", path, "role", "preview", "--species", SPECIES, "seed=0x12345678")
      self.assertEqual(status, 0, out)
      self.assertIn(f"{UNSTORED} (unstored)", out)
      status, out = run_cli("battle", path, "role", "import", "--species", SPECIES, "seed=0x12345678")
      self.assertEqual(status, 0, out)
      self.assertIn("transfer bytes", out)
      index = str(progression.fillers(self.project.structure, WIDE_ROLE)[0])
      self.assertEqual(run_cli("battle", path, "generation", "order", index, "high_first")[0], 0)
      saved = json.loads((self.dir / "structure.json").read_text(encoding="utf-8"))
      self.assertEqual(saved["generation"][int(index)]["order"], "high_first")
      self.assertNotEqual(run_cli("battle", path, "generation", "order", index, "sideways")[0], 0)
      self.assertEqual(run_cli("battle", path, "generation", "order", index, "null")[0], 0)
      saved = json.loads((self.dir / "structure.json").read_text(encoding="utf-8"))
      self.assertNotIn("order", saved["generation"][int(index)])
      gender = str(progression.fillers(self.project.structure, FIELD_ROLE)[0])
      status, out = run_cli("battle", path, "generation", "preview", gender, "seed_lo=0", "--species", SPECIES)
      self.assertEqual(status, 0, out)
      status, out = run_cli("battle", path, "generation", "show")
      self.assertNotIn("error", out)


if __name__ == "__main__":
   unittest.main()
