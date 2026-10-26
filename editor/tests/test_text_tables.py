#!/usr/bin/env python3
"""!Tests for the I4 text tables [S2] (no Qt): core.text_tables (capsule.texts/1 edits checked by the engine, the
fit check with the engine's rule, control codes), core.asset_tables (includes, text tables, languages, the engine's
fit report), core.manifest_io's kept json layout, and the `text-table` and `manifest` commands. Uses the neutral
game of text_fixture.py.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # the sibling test helpers (V2 finding)
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import asset_tables, engine, manifest_io, text_tables  # noqa: E402
from capsule_studio.core.document import Document, DocumentError  # noqa: E402
import text_fixture as fx  # noqa: E402


class GameCase(unittest.TestCase):
   """!Base: the fixture game in a temporary folder."""

   def setUp(self) -> None:
      """!Writes the game.
      @return None
      """
      ## Temporary folder.
      self.tmp = Path(tempfile.mkdtemp(prefix="capsule_i4_text_"))
      ## The game.
      self.game = fx.make_game(self.tmp)

   def tearDown(self) -> None:
      """!Removes the folder.
      @return None
      """
      shutil.rmtree(self.tmp, ignore_errors=True)

   def context(self) -> text_tables.TextContext:
      """!The game's text settings, found from the asset manifest.
      @return TextContext
      """
      return text_tables.TextContext.for_manifest(self.game.assets)

   def run_cli(self, *args: object) -> tuple[int, str]:
      """!Runs capsule-studio.
      @param args  arguments
      @return (status, output)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         status = cli([str(a) for a in args])
      return status, out.getvalue() + err.getvalue()


class LayoutTests(GameCase):
   """!A table keeps its file's json layout."""

   def test_schemas_are_the_engines(self) -> None:
      """!The studio's schema names are the engine compilers'.
      @return None
      """
      self.assertEqual(text_tables.SCHEMA, engine.asset_compiler().TEXT_TABLE_SCHEMA)
      self.assertEqual(text_tables.wrap_modes(), list(engine.asset_compiler().WRAP_MODES))

   def test_round_trip_is_byte_identical(self) -> None:
      """!Opened and saved without edits: the same bytes; an edit changes only its line.
      @return None
      """
      before = self.game.en.read_bytes()
      doc = text_tables.open_table(self.game.en)
      self.assertEqual(doc.layout, (1, False))
      doc.save()
      self.assertEqual(self.game.en.read_bytes(), before)
      with doc.edit("t"):
         text_tables.set_text(doc, "text:Main.Auto", "Changed.")
      doc.save()
      changed = [a for a, b in zip(before.decode().splitlines(), self.game.en.read_text().splitlines()) if a != b]
      self.assertEqual(len(changed), 1)
      self.assertIn("Changed.", self.game.en.read_text())

   def test_detect(self) -> None:
      """!detect() names Python's layouts and nothing else.
      @return None
      """
      data = {"a": [1, 2], "b": "é"}
      self.assertEqual(manifest_io.detect(json.dumps(data, indent=2) + "\n", data), (2, True))
      self.assertEqual(manifest_io.detect(json.dumps(data, indent=1, ensure_ascii=False) + "\n", data), (1, False))
      self.assertIsNone(manifest_io.detect(manifest_io.dumps(data) + "  \n", data))


class ContextTests(GameCase):
   """!The game's text settings are found from its files."""

   def test_found_from_the_manifest_and_a_table(self) -> None:
      """!The scripts manifest naming the asset manifest gives the placeholders, from a table too.
      @return None
      """
      ctx = self.context()
      self.assertEqual(ctx.scripts, self.game.scripts.resolve())
      self.assertIn("player", ctx.field.codes)
      self.assertEqual(text_tables.owner_manifest(self.game.en), self.game.assets.resolve())
      self.assertEqual(text_tables.TextContext.for_manifest(self.game.en).scripts, self.game.scripts.resolve())
      self.assertIsNone(text_tables.find_codepage(self.game.assets))   # the engine's default page


class EditTests(GameCase):
   """!Table edits, each checked by the engine's load_text_table()."""

   def test_rows_and_edits(self) -> None:
      """!Rows; text, wrap, font, add, rename, remove; a string entry stays one until it needs keys.
      @return None
      """
      doc = text_tables.open_table(self.game.en)
      self.assertEqual([r.key for r in text_tables.rows(doc)], list(fx.EN_TEXTS))
      auto = text_tables.entry(doc, "text:Main.Auto")
      self.assertEqual(auto.wrap, "auto")
      self.assertFalse(auto.explicit)
      with doc.edit("t"):
         text_tables.set_text(doc, "text:Main.Auto", "New")
      self.assertEqual(doc.data["texts"]["text:Main.Auto"], "New")
      with doc.edit("t"):
         text_tables.set_wrap(doc, "text:Main.Auto", "original")
         text_tables.set_text_font(doc, "text:Main.Auto", "body")
      self.assertEqual(doc.data["texts"]["text:Main.Auto"], {"text": "New", "wrap": "original", "font": "body"})
      with doc.edit("t"):
         text_tables.add_text(doc, "text:Main.Added", "x", "original")
         text_tables.rename_text(doc, "text:Main.Added", "text:Main.Renamed")
      self.assertEqual(list(doc.data["texts"])[-1], "text:Main.Renamed")
      with doc.edit("t"):
         text_tables.remove_text(doc, "text:Main.Renamed")
      self.assertNotIn("text:Main.Renamed", doc.data["texts"])
      self.assertTrue(doc.undo())
      self.assertIn("text:Main.Renamed", doc.data["texts"])

   def test_refused_edits_roll_back(self) -> None:
      """!A wrap mode, a font or a key the engine refuses changes nothing.
      @return None
      """
      doc = text_tables.open_table(self.game.en)
      before = json.dumps(doc.data)
      for fn in (lambda: text_tables.set_wrap(doc, "text:Main.Auto", "sideways"),
                 lambda: text_tables.set_text_font(doc, "text:Main.Auto", "nope"),
                 lambda: text_tables.add_text(doc, "text:Main.Auto", "dup"),
                 lambda: text_tables.add_text(doc, "text:Other", "x", None, ["text:Other"]),
                 lambda: text_tables.set_box(doc, "nope", 10, 2)):
         with self.assertRaises(DocumentError):
            with doc.edit("t"):
               fn()
      self.assertEqual(json.dumps(doc.data), before)


class FitTests(GameCase):
   """!The fit check is the engine's rule."""

   def test_lines_against_the_box(self) -> None:
      """!Widths per authored line; a line wider than the box; a placeholder measured by its term or not at all.
      @return None
      """
      ctx = self.context()
      doc = text_tables.open_table(self.game.en)
      fit = text_tables.check_text(ctx, doc, "text:Main.Long")
      self.assertIsNone(fit.error)
      self.assertEqual([n.width for n in fit.lines], [fx.line_width("Short line"), fx.line_width("W" * 40)])
      self.assertEqual([n.number for n in fit.over], [2])
      self.assertEqual(fit.lines[1].text, "W" * 40)
      greet = text_tables.check_text(ctx, doc, "text:Main.Greeting")
      self.assertTrue(greet.lines[0].unmeasured)   # {player}: a name slot, measured without its text
      self.assertFalse(greet.lines[1].unmeasured)   # {place}: a term, measured by its text
      self.assertEqual(greet.lines[1].width, fx.line_width(f"Welcome to {fx.TOWN}."))
      pause = text_tables.check_text(ctx, doc, "text:Main.Pause")
      self.assertEqual([n.text for n in pause.lines], ["Wait{pause:15} here", "next line"])   # {scroll} breaks
      auto = text_tables.check_text(ctx, doc, "text:Main.Auto")
      self.assertEqual(auto.lines, [])
      self.assertIn(engine.tool("text_encoder").CODE_NEWLINE, auto.codes)   # broken to the box

   def test_errors(self) -> None:
      """!A text that does not encode, a glyph the font lacks.
      @return None
      """
      ctx = self.context()
      doc = text_tables.open_table(self.game.en)
      with doc.edit("t"):
         text_tables.set_text(doc, "text:Main.Long", "{nobody}")
      self.assertIsNotNone(text_tables.check_text(ctx, doc, "text:Main.Long").error)
      font = json.loads(self.game.font.read_text(encoding="utf-8"))
      del font["glyphs"]["W"]
      self.game.font.write_text(json.dumps(font), encoding="utf-8")
      fit = text_tables.check_text(text_tables.TextContext.for_manifest(self.game.assets), doc, "text:Main.Auto")
      self.assertIsNone(fit.error)
      with doc.edit("t"):
         text_tables.set_text(doc, "text:Main.Auto", "Wow")
      fit = text_tables.check_text(text_tables.TextContext.for_manifest(self.game.assets), doc, "text:Main.Auto")
      self.assertIn("has no glyph for W", fit.error)

   def test_agrees_with_the_engine(self) -> None:
      """!The per-text check counts what the engine's compile_manifest() fit report counts.
      @return None
      """
      ctx = self.context()
      f = text_tables.check_table(ctx, text_tables.open_table(self.game.en))
      totals = [f.checked, f.over, f.with_placeholders]
      report = asset_tables.fit_report(Document.open(self.game.assets), ctx.page, ctx.field)
      self.assertEqual(totals, [report["checked"], report["over"], report["with_placeholders"]])
      self.assertEqual(report["over"], 1)


class ControlTests(unittest.TestCase):
   """!The control codes, from the engine."""

   def test_controls(self) -> None:
      """!Every generic control and the two markup controls; arguments as encode.h counts them; descriptions from the
      header; markup() writes what the encoder reads.
      @return None
      """
      te = engine.tool("text_encoder")
      cs = text_tables.controls()
      self.assertEqual(len(cs), len(te.CONTROL_CODES) + len(te.CONTROLS))
      header = (engine.root() / "include" / "capsule" / "text" / "encode.h").read_text(encoding="utf-8")
      args = [int(v) for v in re.search(r"kControlArgs\[\] = \{([^}]*)\}", header).group(1).replace("\n", "")
              .split(",")]
      for c in cs:
         if c.name in te.CONTROL_CODES:
            self.assertEqual(sum(c.widths), args[c.code], c.name)
            self.assertTrue(c.description, c.name)
            codes = te.encode(c.markup([1] * len(c.widths)), "t", controls=True)
            self.assertEqual(codes[:2], [te.CODE_CONTROL, c.code])
      self.assertEqual(text_tables.authored_lines("a\nb{page}c{prompt}d{scroll}e"), list("abcde"))


class ManifestTests(GameCase):
   """!Includes and text tables of an asset manifest."""

   def test_lists_languages_and_includes(self) -> None:
      """!The tables with languages (the German table a translation beside the listed one); a missing translation;
      an include adds its tables; a cycle is refused; two languages in one manifest collide in the engine.
      @return None
      """
      doc = Document.open(self.game.assets)
      self.assertEqual([(r.label, r.language) for r in asset_tables.tables(doc)], [("text/en/main.json", "en")])
      refs = asset_tables.table_set(doc)
      self.assertEqual([(r.label, r.language, r.listed) for r in refs],
                       [("text/en/main.json", "en", True), ("text/de/main.json", "de", False)])
      docs = {r.path: text_tables.open_table(r.path) for r in refs}
      self.assertEqual(asset_tables.missing_translations(docs), {"de": ["text:Main.Long", "text:Main.Pause"]})
      top = self.game.root / "top.json"
      manifest_io.save(top, {"schema": "capsule.assets/1", "id": "top", "assets": []})
      tdoc = Document.open(top)
      with tdoc.edit("t"):
         asset_tables.add_entry(tdoc, "includes", self.game.assets)
      self.assertEqual(asset_tables.entries(tdoc, "includes"), ["assets.json"])
      self.assertEqual(len(asset_tables.tables(tdoc)), 1)
      self.assertEqual(asset_tables.fonts(tdoc)[0][0], "font:BODY")
      tdoc.save()
      with self.assertRaises(DocumentError):
         with doc.edit("t"):
            asset_tables.add_entry(doc, "includes", top)   # top includes this one: a cycle
      with self.assertRaises(DocumentError):
         with doc.edit("t"):
            asset_tables.add_entry(doc, "text_tables", top)   # not a table
      with self.assertRaises(DocumentError):   # the engine: a key is one asset of the manifest
         with doc.edit("t"):
            asset_tables.add_entry(doc, "text_tables", self.game.de)
            asset_tables.fit_report(doc, self.context().page, self.context().field)
      with doc.edit("t"):
         asset_tables.add_entry(doc, "text_tables", self.game.de)
         asset_tables.move_entry(doc, "text_tables", "text/de/main.json", -1)
         asset_tables.remove_entry(doc, "text_tables", "text/en/main.json")
      self.assertEqual(asset_tables.entries(doc, "text_tables"), ["text/de/main.json"])


class CommandTests(GameCase):
   """!`text-table` and `manifest` commands."""

   def test_text_table_commands(self) -> None:
      """!list, show, set, wrap, font, add, rename, remove, box, fit, controls.
      @return None
      """
      t = self.game.en
      status, out = self.run_cli("text-table", "list", t)
      self.assertEqual(status, 0, out)
      self.assertIn("text:Main.Long", out)
      status, out = self.run_cli("text-table", "show", t, "text:Main.Long")
      self.assertIn("line 2:", out)
      self.assertIn("OVER", out)
      status, out = self.run_cli("text-table", "fit", t)
      self.assertEqual(status, 1, out)
      self.assertIn("1 lines wider", out)
      self.assertEqual(self.run_cli("text-table", "set", t, "text:Main.Long", "--text", "Short\\nlines")[0], 0)
      status, out = self.run_cli("text-table", "fit", t, "--json")
      self.assertEqual(status, 0, out)
      self.assertEqual(json.loads(out)["over"], 0)
      for args in (("wrap", t, "text:Main.Auto", "original"), ("font", t, "text:Main.Auto", "body"),
                   ("add", t, "text:Main.New", "hi"), ("rename", t, "text:Main.New", "text:Main.Newer"),
                   ("remove", t, "text:Main.Newer"), ("box", t, "--width", "200")):
         status, out = self.run_cli("text-table", *args)
         self.assertEqual(status, 0, (args, out))
      data = json.loads(t.read_text(encoding="utf-8"))
      self.assertEqual(data["box"]["width"], 200)
      self.assertEqual(data["texts"]["text:Main.Auto"]["font"], "body")
      self.assertEqual(manifest_io.detect(t.read_text(encoding="utf-8"), data), (1, False))   # layout kept
      status, out = self.run_cli("text-table", "wrap", t, "text:Main.Auto", "diagonal")
      self.assertEqual(status, 1, out)
      status, out = self.run_cli("text-table", "controls")
      self.assertIn("{pause:0}", out)

   def test_manifest_commands(self) -> None:
      """!tables, includes, check (with its fit report), translations.
      @return None
      """
      a = self.game.assets
      status, out = self.run_cli("manifest", "tables", a)
      self.assertIn("text/en/main.json", out)
      status, out = self.run_cli("manifest", "check", a, "--fit-report", self.tmp / "fit.json")
      self.assertEqual(status, 1, out)   # the long line
      self.assertEqual(json.loads((self.tmp / "fit.json").read_text())["over"], 1)
      status, out = self.run_cli("manifest", "translations", a)
      self.assertEqual(status, 1)
      self.assertIn("de: 2 keys missing", out)
      status, out = self.run_cli("manifest", "tables", a, "add", "text/de/main.json")
      self.assertIn("text/de", out)
      status, out = self.run_cli("manifest", "tables", a, "remove", "text/de/main.json")
      self.assertNotIn("text/de", out)
      status, out = self.run_cli("manifest", "includes", a, "add", "nope.json")
      self.assertEqual(status, 1, out)


if __name__ == "__main__":
   unittest.main()
