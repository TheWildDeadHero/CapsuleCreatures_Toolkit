#!/usr/bin/env python3
"""!Tests for proportional fonts [S2] (no Qt): core.fonts (capsule.font/2 edits, the engine's compile check),
core.text_render (text drawn as the engine's text windows draw it, the screens of a text) and the `font` commands.
Uses the neutral game of text_fixture.py.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # the sibling test helpers (V2 finding)
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine, fonts, text_render  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
import text_fixture as fx  # noqa: E402


class FontCase(unittest.TestCase):
   """!Base: the fixture game."""

   def setUp(self) -> None:
      """!Writes the game.
      @return None
      """
      ## Temporary folder.
      self.tmp = Path(tempfile.mkdtemp(prefix="capsule_i4_font_"))
      ## The game.
      self.game = fx.make_game(self.tmp)
      ## The engine's default code page.
      self.page = engine.tool("text_encoder").DEFAULT

   def tearDown(self) -> None:
      """!Removes the folder.
      @return None
      """
      shutil.rmtree(self.tmp, ignore_errors=True)


class FontTests(FontCase):
   """!core.fonts."""

   def test_schema_and_compile(self) -> None:
      """!The schema is the compiler's; the font compiles; glyphs by code; the page's characters all have glyphs.
      @return None
      """
      self.assertEqual(fonts.SCHEMA, fonts.compiler().PROPORTIONAL_SCHEMA)
      doc = fonts.open_font(self.game.font)
      self.assertEqual(doc.layout, (1, False))
      font = fonts.compile_font(doc, self.page)
      self.assertEqual(font["widths"][ord("A") - font["first"]], fx.glyph_width("A"))
      rows = fonts.glyph_rows(doc, self.page)
      self.assertEqual(rows[0].code, fx.FIRST_CODE)
      self.assertEqual(fonts.missing_characters(doc, self.page), [])
      self.assertIsNone(fonts.problem(doc, self.page))

   def test_edits(self) -> None:
      """!Width, pixel, rows, add / remove, metrics, cell; refused values; undo.
      @return None
      """
      doc = fonts.open_font(self.game.font)
      with doc.edit("t"):
         fonts.set_width(doc, "A", 7)
         fonts.set_pixel(doc, "A", 0, 0, 3)
         fonts.set_metric(doc, "letter_spacing", 2)
      self.assertEqual(doc.data["glyphs"]["A"]["width"], 7)
      self.assertEqual(doc.data["glyphs"]["A"]["rows"][0][0], "3")
      with doc.edit("t"):
         fonts.add_glyph(doc, "é")
      self.assertIn("é", fonts.problem(doc, self.page))   # the ASCII page has no é: the compiler says so
      with doc.edit("t"):
         fonts.remove_glyph(doc, "é")
         fonts.set_cell(doc, 12, 6)
      self.assertEqual(fonts.cell(doc), (12, 6))
      self.assertEqual(len(doc.data["glyphs"]["A"]["rows"]), 6)
      self.assertEqual(len(doc.data["glyphs"]["A"]["rows"][0]), 12)
      self.assertIsNone(fonts.problem(doc, self.page))
      for fn in (lambda: fonts.set_width(doc, "A", 999), lambda: fonts.set_pixel(doc, "A", 99, 0, 1),
                 lambda: fonts.set_pixel(doc, "A", 0, 0, 7), lambda: fonts.set_cell(doc, 10, 6),
                 lambda: fonts.set_rows(doc, "A", ["1"]), lambda: fonts.add_glyph(doc, "A"),
                 lambda: fonts.set_metric(doc, "cell", 1)):
         with self.assertRaises(DocumentError):
            with doc.edit("t"):
               fn()
      while doc.undo():
         pass
      self.assertEqual(doc.data, json.loads(self.game.font.read_text(encoding="utf-8")))

   def test_memory_file_reads_unsaved_edits(self) -> None:
      """!The compiler reads the Document's data, not the file.
      @return None
      """
      doc = fonts.open_font(self.game.font)
      with doc.edit("t"):
         fonts.set_width(doc, "B", 1)
      font = fonts.compile_font(doc, self.page)
      self.assertEqual(font["widths"][ord("B") - font["first"]], 1)


class RenderTests(FontCase):
   """!core.text_render."""

   def test_render_and_screens(self) -> None:
      """!A glyph's pixels in the pens' colours; the pen advances by width and spacing; screens split at waits.
      @return None
      """
      te = engine.tool("text_encoder")
      font = fonts.compile_font(fonts.open_font(self.game.font), self.page)
      pens = text_render.Pens(1, 2, 0, [(0, 0, 0), (255, 0, 0), (0, 0, 255)] + [(9, 9, 9)] * 13)
      w, h, _px = text_render.render_text(font, te.encode("AB", "t"), pens)
      self.assertEqual((w, h), (fx.line_width("AB"), fx.LINE_HEIGHT))
      canvas = text_render.Canvas(w, h)
      text_render.draw_lines(canvas, font, [[("g", ord("A")), ("g", ord("B"))]], 0, 0, pens)
      self.assertEqual(canvas.pixel(0, fx.SHAPE_TOP), (255, 0, 0))   # ink
      self.assertEqual(canvas.pixel(fx.glyph_width("A") - 2, fx.SHAPE_TOP), (0, 0, 255))   # the shadow column
      b_left = fx.glyph_width("A") + fx.LETTER_SPACING
      self.assertEqual(canvas.pixel(b_left, fx.SHAPE_TOP), (255, 0, 0))
      codes = te.encode("one\ntwo\nthree{page}four{scroll}five", "t", controls=True)
      shots = text_render.screens(codes, 2)
      flat = [["".join(chr(v) for k, v in line if k == "g") for line in s] for s in shots]
      self.assertEqual(flat, [["one", "two"], ["two", "three"], ["four"], ["four", "five"]])

   def test_colours(self) -> None:
      """!#rrggbb both ways.
      @return None
      """
      self.assertEqual(text_render.parse_color("#10ff00"), (16, 255, 0))
      self.assertEqual(text_render.color_text((16, 255, 0)), "#10ff00")
      with self.assertRaises(ValueError):
         text_render.parse_color("red")


class CommandTests(FontCase):
   """!`font` commands."""

   def run_cli(self, *args: object) -> tuple[int, str]:
      """!Runs capsule-studio.
      @param args  arguments
      @return (status, output)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         status = cli([str(a) for a in args])
      return status, out.getvalue() + err.getvalue()

   def test_font_commands(self) -> None:
      """!info, glyph, width, pixel, metric, add, remove, preview.
      @return None
      """
      f = self.game.font
      status, out = self.run_cli("font", "info", f)
      self.assertEqual(status, 0, out)
      self.assertIn("compiles: yes", out)
      for args in (("width", f, "A", "5"), ("pixel", f, "A", "1", "1", "2"), ("metric", f, "line_height", "10"),
                   ("add", f, "#x"), ("remove", f, "#x")):
         status, out = self.run_cli("font", *args)
         self.assertEqual(status, 0, (args, out))
      status, out = self.run_cli("font", "glyph", f, "A")
      self.assertIn("width 5", out)
      status, out = self.run_cli("font", "preview", f, "Hi there", self.tmp / "p.png", "--scale", "1")
      self.assertEqual(status, 0, out)
      w, _h, _px = engine.bitmap().read_png(self.tmp / "p.png")
      self.assertEqual(w, fx.line_width("Hi there") + 2)   # one pixel of margin each side


if __name__ == "__main__":
   unittest.main()
