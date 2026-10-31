#!/usr/bin/env python3
"""!Tests for capsule_studio.core.codepage, the code page in text checks and
previews, engine.font_glyphs() and `text codepage ...` (no Qt needed).

Each test builds a small game in a temporary folder: reference/project.json
naming data/assets.json, whose texts use characters outside ASCII.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import codepage, engine, manifest_io, preview, texts  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402

## A glyph for é (U+00E9) in the engine's font file format.
E_ACUTE_GLYPH = "U+00E9 ...#. ..#.. .###. #...# ##### #.... .###.\n"


class CodePageTestCase(unittest.TestCase):
   """!Base: a temporary game.

   @var dir
   The game folder.
   @var project_json
   Its reference/project.json.
   @var assets
   Its data/assets.json.
   """

   def setUp(self) -> None:
      """!Writes the game.
      @return None
      """
      # Resolved, as the editor resolves the files it opens (macOS /var is /private/var; Windows short names).
      self.dir = Path(tempfile.mkdtemp(prefix="capsule_codepage_")).resolve()
      self.project_json = self.dir / "reference" / "project.json"
      self.assets = self.dir / "data" / "assets.json"
      manifest_io.save(self.project_json, {"schema": "capsule.project/1", "name": "t",
                                           "rom": {"title": "T", "code": "CTTT", "maker": "00"}, "sources": [],
                                           "assets": "data/assets.json"})
      manifest_io.save(self.assets, {"schema": "capsule.assets/1", "id": "t", "assets": [
         {"key": "text:HELLO", "kind": "text", "text": "Hello"},
         {"key": "text:CAFE", "kind": "text", "text": "Café"},
         {"key": "text:QUOTE", "kind": "text", "text": "It’s é"}]})

   def tearDown(self) -> None:
      """!Removes the game.
      @return None
      """
      shutil.rmtree(self.dir, ignore_errors=True)

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command.
      @param argv  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()

   def give_font(self) -> None:
      """!Gives the game a font: the engine's plus a glyph for é.
      @return None
      """
      extra = self.dir / "data" / "text" / "extra_8x8.txt"
      extra.parent.mkdir(parents=True, exist_ok=True)
      extra.write_text(E_ACUTE_GLYPH, encoding="utf-8")
      # A copy of the engine's font in the game: the temporary folder may be on another drive than the engine
      # (Windows), where no relative path leads to it.
      shutil.copyfile(engine.root() / codepage.DEFAULT_FONT, extra.parent / "default_8x8.txt")
      data = manifest_io.load(self.project_json)
      data["text"]["fonts"] = {"en": ["data/text/default_8x8.txt", "data/text/extra_8x8.txt"]}
      manifest_io.save(self.project_json, data)


class CoreTests(CodePageTestCase):
   """!Projects, pages, missing characters, cells and page edits."""

   def test_project_and_missing(self) -> None:
      """!A file finds its game; the default page lacks é and the curly quote.
      @return None
      """
      self.assertEqual(codepage.find_project(self.assets), self.project_json.resolve())
      self.assertEqual(codepage.find_project(self.dir), self.project_json.resolve())
      self.assertIsNone(codepage.find_project(self.dir.parent))
      project = codepage.open_project(self.assets)
      self.assertIsNone(codepage.language(project))
      self.assertIsNone(codepage.page_path(project))
      self.assertIs(codepage.load(project), codepage.default_page())
      self.assertEqual(codepage.missing(project), {"é": ["assets: text:CAFE", "assets: text:QUOTE"],
                                                   "’": ["assets: text:QUOTE"]})
      with self.assertRaises(DocumentError):
         codepage.open_page(project)
      with self.assertRaises(DocumentError):
         codepage.open_project(self.dir.parent)

   def test_edit_page(self) -> None:
      """!Import, set, alias, unset; invalid pages are refused and roll back.
      @return None
      """
      project = codepage.open_project(self.project_json)
      with project.edit("Import"):
         path = codepage.import_page(project)
      project.save()
      self.assertEqual(path, self.dir / "data" / "text" / "en.codepage.json")
      self.assertEqual(codepage.page_path(project), path.resolve())
      with self.assertRaises(DocumentError):
         codepage.import_page(project)   # already has one
      doc = codepage.open_page(project)
      with doc.edit("Codes"):
         codepage.set_code(doc, 0x80, "é")      # NFC-normalised to é
         codepage.set_alias(doc, "’", "'")
         codepage.unset_code(doc, ord("A"))        # splits the ASCII range around A
      self.assertEqual(doc.data["map"], {"0x80": "é"})
      self.assertEqual([r["first"] for r in doc.data["ranges"]], ["0x20", "0x42"])
      before = json.dumps(doc.data)
      for bad in (lambda: codepage.set_code(doc, 0x81, "é"),     # é is at 0x80 already
                  lambda: codepage.unset_code(doc, ord(" ")),    # the space must stay at 0x20
                  lambda: codepage.unset_code(doc, ord("A")),    # nothing there now
                  lambda: codepage.set_code(doc, 0xFA, "x"),     # reserved code
                  lambda: codepage.set_alias(doc, "x", None)):   # no such alias
         with self.assertRaises(DocumentError):
            with doc.edit("Bad"):
               bad()
      self.assertEqual(json.dumps(doc.data), before)
      doc.save()
      page = codepage.load(project)
      self.assertEqual(codepage.cells(page, "It’s é"), [ord("I"), ord("t"), ord("'"), ord("s"), ord(" "), 0x80])
      self.assertEqual(codepage.unmapped(page, "ABC\né"), ["A"])
      self.assertEqual(codepage.missing(project), {})
      self.assertEqual(codepage.grid(page)[-8][:7], "80   é ")
      self.assertTrue(codepage.font_problems(project))   # the engine's font has no é
      self.give_font()
      project = codepage.open_project(self.project_json)
      self.assertEqual(codepage.font_problems(project), [])
      self.assertIn(0x80, codepage.glyphs(project))

   def test_plain_and_battle_texts(self) -> None:
      """!Markup is left out of a text's characters; a battle project's texts include terms.
      @return None
      """
      self.assertEqual(codepage.plain("{@party} {party} ok", {"party": {"one": "Crew", "many": "Crews"}}),
                       "Crew  ok")
      project = codepage.open_project(engine.root() / "apps" / "starter_battle")   # names ../../samples/starter
      uses = {where: text for where, text, _markup in codepage.texts(project)}
      self.assertEqual(uses["battle: message party_challenge"], "{party} wants to battle!")
      self.assertEqual(uses["battle: term party (one)"], "Rival")
      self.assertIn("battle: presenter Coach intro", uses)
      self.assertEqual(uses["battle: resource mp label"], "MP")   # resource labels are in-game texts (D-25)
      self.assertEqual(codepage.missing(project), {})


class TextAndPreviewTests(CodePageTestCase):
   """!core.texts and core.preview with a page; engine.font_glyphs()."""

   def page_with_e(self) -> tuple[object, dict[int, list[list[int]]]]:
      """!The game's page with é at 0x80, and its font.
      @return (CodePage, glyphs)
      """
      project = codepage.open_project(self.project_json)
      with project.edit("Import"):
         codepage.import_page(project)
      project.save()
      doc = codepage.open_page(project)
      with doc.edit("é"):
         codepage.set_code(doc, 0x80, "é")
      doc.save()
      self.give_font()
      project = codepage.open_project(self.project_json)
      return codepage.load(project), codepage.glyphs(project)

   def test_checks(self) -> None:
      """!Bad characters and line widths follow the page.
      @return None
      """
      self.assertEqual(texts.bad_characters("Café ’"), ["é", "’"])
      page, _glyphs = self.page_with_e()
      self.assertEqual(texts.bad_characters("Café ’", page), ["’"])
      self.assertEqual(texts.check_text("é" * 30, page=page), [])
      self.assertEqual(texts.check_text("é" * 31, page=page), ["line 1 is 31 characters; 30 fit"])
      self.assertTrue(texts.check_text("é")[0].startswith("error: not in the code page 'en'"))

   def test_preview(self) -> None:
      """!A mapped non-ASCII character draws its glyph; without the page it draws '?'.
      @return None
      """
      page, glyphs = self.page_with_e()
      self.assertIn(0x80, glyphs)
      self.assertEqual(engine.font_glyphs()[ord("A")], glyphs[ord("A")])
      ink = preview.expand(preview.STYLE_INK[0])

      def lit(screen: preview.Screen) -> list[tuple[int, int]]:
         """!Ink pixels of the first cell at column 1, row 1.
         @param screen  Screen
         @return list of (x, y)
         """
         return [(x, y) for y in range(8, 16) for x in range(8, 16) if screen.pixel(x, y) == ink]
      shown = lit(preview.text_layer("é", page=page, glyphs=glyphs))
      self.assertEqual(shown, lit(preview.text_layer("é", page=page, glyphs={0x80: glyphs[0x80]})))
      self.assertEqual(lit(preview.text_layer("é")), lit(preview.text_layer("?")))
      self.assertNotEqual(shown, lit(preview.text_layer("?")))
      self.assertEqual(preview.text_codes("é’", page), [0x80, ord("?")])


class CliTests(CodePageTestCase):
   """!`text codepage ...` and the page in `text check`."""

   def test_commands(self) -> None:
      """!show, check, import, set, alias, unset; text check with the game's page.
      @return None
      """
      g = self.project_json
      status, out = self.run_cli("text", "codepage", "check", self.dir)
      self.assertEqual(status, 1)
      self.assertIn("missing 'é' (U+00E9, LATIN SMALL LETTER E WITH ACUTE): assets: text:CAFE", out)
      self.assertEqual(self.run_cli("text", "check", self.assets)[0], 1)
      self.assertEqual(self.run_cli("text", "codepage", "set", g, "0x80", "é")[0], 1)   # no page of its own yet
      self.assertEqual(self.run_cli("text", "codepage", "import", g)[0], 0)
      self.assertEqual(manifest_io.load(g)["text"], {"code_pages": {"en": "data/text/en.codepage.json"},
                                                     "language": "en"})
      self.assertEqual(self.run_cli("text", "codepage", "import", g)[0], 1)
      status, out = self.run_cli("text", "codepage", "set", g, "128", "é")
      self.assertEqual(status, 0)
      self.assertIn("warning: missing glyphs", out)
      self.assertEqual(self.run_cli("text", "codepage", "alias", self.assets, "’", "'")[0], 0)
      status, out = self.run_cli("text", "codepage", "check", g)
      self.assertEqual(status, 1)
      self.assertIn("font: missing glyphs", out)
      self.give_font()
      status, out = self.run_cli("text", "codepage", "check", g)
      self.assertEqual((status, out), (0, "every text fits the code page 'en'\n"))
      self.assertEqual(self.run_cli("text", "check", self.assets)[0], 0)
      status, out = self.run_cli("text", "codepage", "show", g)
      self.assertIn("80   é .", out)
      self.assertIn("alias '’' -> \"'\"", out)
      self.assertEqual(self.run_cli("text", "codepage", "set", g, "0x81", "é")[0], 1)   # é is mapped already
      self.assertEqual(self.run_cli("text", "codepage", "alias", g, "’")[0], 0)
      self.assertEqual(self.run_cli("text", "codepage", "unset", g, "0x80")[0], 0)
      self.assertEqual(self.run_cli("text", "codepage", "unset", g, "0x80")[0], 1)
      self.assertEqual(self.run_cli("text", "codepage", "check", g)[0], 1)
      out_png = self.dir / "p.png"
      self.assertEqual(self.run_cli("text", "preview", self.assets, "text:CAFE", out_png)[0], 0)
      self.assertTrue(out_png.exists())


if __name__ == "__main__":
   unittest.main()
