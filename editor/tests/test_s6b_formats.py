#!/usr/bin/env python3
"""!S6b (engine C13a / C13b / C13c) without Qt: the text window port (core.text_window) held to the engine's own
handheld rules test (tests/text_window_tests.cpp handheld_rules(): glyphs clipped to their width, their glyph_height
rows and the window, 0 pixels in the background; Fill, Clear, SkipTo, ClearTo, MinSpacing; ShiftDown from the text's
start; a Clear typed as a glyph) and line_width(); the bare previews (core.text_render) drawing what the window port
draws; fonts' glyph_height (core.fonts, the compiler keeps it, the cell change clamps it, the commands); the window
tile storage (core.text_window.storage(), text boxes, screen plan windows, their export); the screen plan's exit
(close / close_now / replace / replace_now: the frames, the checks, the export's leave()); the world's cell
interaction rules (core.interactions: edits refused as the map compiler refuses them, problems() equal to the build's
message, rules that never run, the commands).

Uses text_fixture.py's game, a copy of the engine's screen sandbox and of its C13b interaction fixture.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import text_fixture as fx  # noqa: E402
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine, fonts, interactions, text_boxes, text_render, text_window  # noqa: E402
from capsule_studio.core import screen_plans as sp  # noqa: E402
from capsule_studio.core.document import Document, DocumentError  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402
from test_s6_formats import S6Case, list_plan  # noqa: E402

## The engine test font's codes (tests/text_window_tests.cpp kA, kB, kC).
A, B, C = ord("A"), ord("B"), ord("C")
## Its glyphs (8 x 2 cells, 2 bytes a row): A ink 0-2 over shadow, B one ink pixel at 1, C ink 0-5 but 2 wide.
GLYPHS = [bytes((0x15, 0x00, 0x2A, 0x00)), bytes((0x04, 0x00, 0x00, 0x00)), bytes((0x55, 0x05, 0x55, 0x05))]
## Their advances, the cell, the line height and the letter spacing.
WIDTHS, CELL, LINE_HEIGHT, SPACING = [3, 2, 2], (8, 2), 4, 1
## The test window's entries (kInk, kShadow, kBackground) and typing speed.
INK, SHADOW, BACKGROUND, FRAMES_PER_CHAR = 5, 6, 7, 2
## The test window: 2 x 1 cells, two lines.
WINDOW = {"width": 2, "height": 1, "lines": 2, "ink": INK, "shadow": SHADOW, "background": BACKGROUND,
          "frames_per_char": FRAMES_PER_CHAR, "scroll_speed": 0}
## The window's pixels across and down.
WIDTH_PX, HEIGHT_PX = 16, 8
## A wider window for the preview comparisons: 4 x 2 cells, two lines, a margin.
WIDE = dict(WINDOW, width=4, height=2, left=2, top=1)
## The engine fixtures the interaction tests copy (C13b names D-30's tileset).
INTERACTION_FIXTURES = ("c13b", "d30")


def font(glyph_height: int = 0) -> dict:
   """!The engine test's font as compile_proportional() gives it.
   @param glyph_height  0 (kFont) or 1 (kShortFont)
   @return compiled font
   """
   return {"first": A, "count": len(WIDTHS), "cell": CELL, "line_height": LINE_HEIGHT, "letter_spacing": SPACING,
           "glyph_height": glyph_height, "widths": list(WIDTHS), "glyphs": list(GLYPHS)}


def te() -> object:
   """!The engine's text encoder.
   @return module
   """
   return text_render.encoder()


def ctl(name: str, *args: int) -> list[int]:
   """!A control escape's codes.
   @param name  the control (text_encoder.CONTROL_CODES)
   @param args  its argument bytes
   @return codes
   """
   return [te().CODE_CONTROL, te().CONTROL_CODES[name][0], *args]


def end(*codes: int | list[int]) -> list[int]:
   """!Codes and lists of codes joined, with the end code.
   @param codes  codes or lists of them
   @return codes
   """
   out: list[int] = []
   for c in codes:
      out += c if isinstance(c, list) else [c]
   return out + [te().CODE_END]


class TextWindowTests(unittest.TestCase):
   """!core.text_window as the engine's handheld_rules() test sees window.cpp."""

   def setUp(self) -> None:
      """!Opens the test window.
      @return None
      """
      ## The window under test.
      self.w = text_window.Window(WINDOW, font())

   def px(self, x: int, y: int) -> int:
      """!A pixel's palette entry.
      @param x  column
      @param y  row
      @return entry
      """
      return self.w.pixels[y * self.w.width + x]

   def test_glyph_clipping(self) -> None:
      """!C draws two columns; over ink, 0 pixels take the background; the right edge; glyph_height 1.
      @return None
      """
      w = self.w
      w.fill(0, 0, WIDTH_PX, HEIGHT_PX, INK)
      w.print_at(8, 0, end(C))
      self.assertEqual((self.px(8, 0), self.px(9, 0), self.px(10, 0)), (INK, INK, INK))   # 10: the fill, not C's
      w.fill(0, 0, WIDTH_PX, HEIGHT_PX, SHADOW)
      w.print_at(8, 0, end(C))
      self.assertEqual((self.px(9, 0), self.px(10, 0), self.px(9, 1), self.px(9, 2)), (INK, SHADOW, INK, SHADOW))
      w.print_at(0, 0, end(B))
      self.assertEqual((self.px(0, 0), self.px(1, 0), self.px(2, 0)), (BACKGROUND, INK, SHADOW))
      w.fill(0, 0, WIDTH_PX, HEIGHT_PX, SHADOW)
      self.assertEqual(w.print_at(14, 0, end(A)), 14 + WIDTHS[0] + SPACING)
      self.assertEqual(self.px(15, 0), INK)
      w.font = font(1)   # kShortFont: the shadow row is not drawn
      w.print_at(0, 0, end(A))
      self.assertEqual((self.px(0, 0), self.px(0, 1)), (INK, SHADOW))

   def test_controls(self) -> None:
      """!ShiftDown from the start, Clear, SkipTo, ClearTo, MinSpacing, Fill, and line_width() of each.
      @return None
      """
      w, f = self.w, font()
      w.print(end(ctl("shift_down", 4), ctl("shift_down", 4), A), True)
      self.assertEqual((self.px(0, 4), self.px(0, 0)), (INK, BACKGROUND))   # twice 4 is 4, not 8
      w.fill(0, 0, WIDTH_PX, HEIGHT_PX, INK)
      clear = end(A, ctl("clear", 3), B)
      w.print_at(0, 0, clear)
      self.assertEqual((self.px(4, 0), self.px(6, 1), self.px(8, 0), self.px(4, 2)), (BACKGROUND, BACKGROUND, INK,
                                                                                     INK))
      self.assertEqual(text_window.line_width(f, clear), WIDTHS[0] + SPACING + 3 + WIDTHS[1] + SPACING)
      skip = end(ctl("skip_to", 10), B)
      w.print(skip, True)
      self.assertEqual(self.px(11, 0), INK)
      self.assertEqual(text_window.line_width(f, skip), 10 + WIDTHS[1] + SPACING)
      w.fill(0, 0, WIDTH_PX, HEIGHT_PX, INK)
      clear_to = end(A, ctl("clear_to", 10), B)
      w.print_at(0, 0, clear_to)
      self.assertEqual((self.px(4, 0), self.px(9, 1), self.px(11, 0)), (BACKGROUND, BACKGROUND, INK))
      self.assertEqual(text_window.line_width(f, clear_to), 10 + WIDTHS[1] + SPACING)
      least = end(ctl("min_spacing", 6), A, B)
      w.print(least, True)
      self.assertEqual((self.px(7, 0), self.px(5, 0)), (INK, BACKGROUND))
      self.assertEqual(text_window.line_width(f, least), 12)
      w.print(end(A, ctl("fill"), B), True)
      self.assertEqual((self.px(0, 0), self.px(1, 0), self.px(2, 0)), (BACKGROUND, INK, BACKGROUND))

   def test_clear_types_as_a_glyph(self) -> None:
      """!Typed: A, then the Clear, then B, FRAMES_PER_CHAR frames apart.
      @return None
      """
      w = self.w
      w.print(end(A, ctl("clear", 3), B), False)
      for _frame in range(2 * FRAMES_PER_CHAR):
         w.update()
      self.assertEqual(self.px(8, 0), BACKGROUND)
      self.assertTrue(w.busy())
      w.update()
      self.assertEqual(self.px(8, 0), INK)

   def test_storage(self) -> None:
      """!A window's tiles and bytes (TileBuffer<W, H>: kWordsPerTile words a tile); the kMaxTiles clamp.
      @return None
      """
      k = text_window.storage_constants()
      self.assertEqual(k, {"kMaxTiles": 256, "kWordsPerTile": 8})   # read from the engine's window.h
      st = text_window.storage(20, 2)
      self.assertEqual((st.tiles, st.size_bytes, st.fits()), (40, 40 * 32, True))
      self.assertEqual(st.cpp_type(), "capsule::text::window::TileBuffer<20, 2>")
      self.assertFalse(text_window.storage(30, 9).fits())
      big = text_window.Window(dict(WINDOW, width=30, height=9), font())
      self.assertEqual((big.store.height, big.height), (8, 64))   # window::open(): the rows that fit
      self.assertEqual(self.w.store.text(), "2 tiles, 64 bytes (TileBuffer<2, 1>)")


class PreviewTests(unittest.TestCase):
   """!core.text_render's bare previews draw what the window port draws."""

   def compare(self, codes: list[int], f: dict | None = None) -> None:
      """!The window port's pixels and draw_lines()' picture of a one-screen text are the same entries.
      @param codes  the text
      @param f      the font (the engine test's by default)
      @return None
      """
      f = f or font()
      w = text_window.Window(WIDE, f)
      w.print(codes, True)
      pens = text_render.Pens(INK, SHADOW, BACKGROUND, [(i, i, i) for i in range(text_render.bank_colors())])
      canvas = text_render.Canvas(w.width, w.height, pens.color(BACKGROUND))
      shown = text_render.screens(codes, WIDE["lines"])
      self.assertEqual(len(shown), 1)
      text_render.draw_lines(canvas, f, shown[0], 0, 0, pens, WIDE["left"], WIDE["top"])
      drawn = [canvas.pixel(x, y)[0] for y in range(w.height) for x in range(w.width)]
      self.assertEqual(drawn, list(w.pixels), [c for c in codes])

   def test_same_as_the_window(self) -> None:
      """!Glyph clipping, glyph_height, colours, every positioning control, Fill with a colour kept, a newline.
      @return None
      """
      for codes in (end(A, B, C), end(A, ctl("clear", 3), B), end(ctl("skip_to", 10), B),
                    end(A, ctl("clear_to", 10), B), end(ctl("min_spacing", 6), A, B, A),
                    end(A, ctl("fill"), B), end(ctl("shift_down", 6), A), end(ctl("shift_right", 5), A),
                    end(ctl("color", 9), A, ctl("fill"), B), end(A, te().CODE_NEWLINE, B, C),
                    end(ctl("highlight", 3), A, ctl("clear", 2), ctl("min_spacing", 5), B, B)):
         self.compare(codes)
      self.compare(end(A, B, te().CODE_NEWLINE, A), font(1))

   def test_line_pixels_and_render(self) -> None:
      """!A line's width follows the controls; render_text() fits ShiftDown and draws glyph_height rows.
      @return None
      """
      f = font()
      line = text_render.screens(end(ctl("skip_to", 10), B), 1)[0][0]
      self.assertEqual(text_render.line_pixels(f, line), 10 + WIDTHS[1] + SPACING)
      w, h, _px = text_render.render_text(f, end(ctl("shift_down", 9), A), text_render.preview_pens())
      self.assertEqual(h, 9 + LINE_HEIGHT)
      self.assertEqual(text_render.glyph_rows(font(1)), 1)
      self.assertEqual(text_render.glyph_rows(font(0)), CELL[1])


class FontTests(unittest.TestCase):
   """!glyph_height in core.fonts, the engine's compiler and the commands."""

   def setUp(self) -> None:
      """!Writes the fixture game.
      @return None
      """
      ## Temporary folder.
      self.tmp = Path(tempfile.mkdtemp(prefix="capsule_s6b_font_"))
      ## The game.
      self.game = fx.make_game(self.tmp)
      ## The engine's default code page.
      self.page = engine.tool("text_encoder").DEFAULT

   def tearDown(self) -> None:
      """!Removes the folder.
      @return None
      """
      shutil.rmtree(self.tmp, ignore_errors=True)

   def test_glyph_height(self) -> None:
      """!Set, compiled, previewed (rows below it not drawn), refused past the cell, clamped by a smaller cell.
      @return None
      """
      doc = fonts.open_font(self.game.font)
      self.assertEqual((fonts.glyph_height(doc), fonts.drawn_rows(doc)), (0, fx.CELL[1]))
      with doc.edit("Glyph height"):
         fonts.set_metric(doc, fonts.GLYPH_HEIGHT, 3)
      compiled = fonts.compile_font(doc, self.page)
      self.assertEqual(compiled["glyph_height"], 3)
      self.assertEqual(text_boxes._inked_rows(compiled), 3)   # a box needs only the drawn rows
      pens = text_render.preview_pens()
      w, _h, px = text_render.render_text(compiled, end(ord("H")), pens)
      ink = pens.color(pens.ink)

      def at(x: int, y: int) -> tuple[int, ...]:
         """!A pixel's colour.
         @param x  column
         @param y  row
         @return RGB
         """
         o = (y * w + x) * 4
         return tuple(px[o:o + 3])
      column = [at(x, fx.SHAPE_TOP) for x in range(w)]
      self.assertIn(ink, column)                                         # row 1 is drawn
      self.assertNotIn(ink, [at(x, fx.SHAPE_BOTTOM) for x in range(w)])   # row 6 is below the glyph height
      with self.assertRaises(DocumentError), doc.edit("Too high"):
         fonts.set_metric(doc, fonts.GLYPH_HEIGHT, fx.CELL[1] + 1)
      with doc.edit("Cell"):
         fonts.set_cell(doc, fx.CELL[0], 2)
      self.assertEqual(doc.data[fonts.GLYPH_HEIGHT], 2)
      with doc.edit("Whole cell"):
         fonts.set_metric(doc, fonts.GLYPH_HEIGHT, 0)
      self.assertNotIn(fonts.GLYPH_HEIGHT, doc.data)
      self.assertIn(fonts.GLYPH_HEIGHT, fonts.compiler().PROPORTIONAL_KEYS)

   def test_commands(self) -> None:
      """!`font metric FONT glyph_height N` saves it; `font info` shows it.
      @return None
      """
      out = io.StringIO()
      with redirect_stdout(out), redirect_stderr(out):
         self.assertEqual(cli(["font", "metric", str(self.game.font), "glyph_height", "5"]), 0)
         status = cli(["font", "info", str(self.game.font)])
      self.assertEqual(json.loads(self.game.font.read_text(encoding="utf-8"))["glyph_height"], 5)
      self.assertIn("glyph height: 5 (a window draws 5 rows", out.getvalue())
      self.assertEqual(status, 0, out.getvalue())


class BoxStorageTests(unittest.TestCase):
   """!A text box style's window storage."""

   def test_style_storage(self) -> None:
      """!The panel's and `text-box show`'s line.
      @return None
      """
      tmp = Path(tempfile.mkdtemp(prefix="capsule_s6b_box_"))
      try:
         game = fx.make_game(tmp)
         doc = Document.open(game.assets)
         with doc.edit("Style"):
            text_boxes.add_style(doc, "text_box:MAIN", "font:BODY")
         doc.save()
         style = text_boxes.find(doc, "text_box:MAIN")
         st = text_boxes.storage(style)
         cells = text_boxes.number(style, "window", "width") * text_boxes.number(style, "window", "height")
         self.assertEqual((st.tiles, st.size_bytes), (cells, cells * 32))
         out = io.StringIO()
         with redirect_stdout(out), redirect_stderr(out):
            cli(["text-box", "show", str(game.assets), "text_box:MAIN"])
         self.assertIn(f"window storage: {st.text()}", out.getvalue())
      finally:
         shutil.rmtree(tmp, ignore_errors=True)


class PlanTests(S6Case):
   """!Screen plans: window buffers and the exit."""

   def test_window_storage(self) -> None:
      """!Each window's buffer, the plan's total, describe(), a window past kMaxTiles refused.
      @return None
      """
      p = list_plan(self.doc)
      self.assertEqual(sp.windows_storage(p.data), (40, 40 * 32))
      self.assertIn("window buffers: 40 tiles, 1280 bytes", sp.describe(p.data))
      with p.edit("Big"):
         sp.add_item(p, "windows", name="big", bg=0, x=0, y=0, w=32, h=9)
      found = [str(x) for x in sp.check(p.data, self.doc)]
      self.assertTrue(any("covers 288 cells; a window has at most 256 tiles" in x for x in found), found)

   def test_exit(self) -> None:
      """!close(): the out fade's 23 calls, leave the frame after (screen_tests.cpp: closed_at + 23), below resumes
      the next; close_now(): leave at the frame's end; the checks; refused words.
      @return None
      """
      p = list_plan(self.doc)
      self.assertEqual(sp.exit_of(p.data), {"call": "close", "next": ""})
      frames = sp.exit_frames(p.data)
      self.assertEqual([f for f, _w in frames], [0, 22, 23, 24])
      self.assertIn("leaves", frames[2][1])
      with p.edit("Exit"):
         sp.set_exit(p, "close_now")
      self.assertEqual([f for f, _w in sp.exit_frames(p.data)], [0, 1])
      found = [str(x) for x in sp.check(p.data, self.doc)]
      self.assertTrue(any("never plays the out fade (23 calls)" in x for x in found), found)
      with p.edit("Out"):
         sp.set_transition(p, "out", "none")
      self.assertEqual([str(x) for x in sp.check(p.data, self.doc)], [])
      with p.edit("Close"):
         sp.set_exit(p, "close")
      self.assertNotIn("exit", p.data)
      self.assertEqual([f for f, _w in sp.exit_frames(p.data)], [0, 1, 2])   # no fade: leave next frame
      with p.edit("Replace"):
         sp.set_exit(p, "replace_now")
      self.assertTrue(any("names no next screen" in str(x) for x in sp.check(p.data, self.doc)))
      with p.edit("Next"):
         sp.set_exit(p, "replace_now", "detail")
      self.assertTrue(any("'detail' is no plan" in str(x) for x in sp.check(p.data, self.doc)))
      sp.create(self.doc, "detail").save()
      self.assertEqual([str(x) for x in sp.check(p.data, self.doc)], [])
      self.assertIn("detail's setup", sp.exit_frames(p.data)[1][1])
      for bad in (("leave",), ("replace", "Not A Name")):
         with self.assertRaises(sp.PlanError), p.edit("Bad"):
            sp.set_exit(p, *bad)

   def test_export(self) -> None:
      """!The header's window buffers and leave() follow the style and compile against the engine (C++20).
      @return None
      """
      p = list_plan(self.doc)
      with p.edit("Exit"):
         sp.set_transition(p, "out", "none")
         sp.set_exit(p, "replace_now", "detail")
      header = self.root / "list_screen.h"
      text = sp.export_cpp(p.data, p.path.name)
      header.write_text(text, encoding="utf-8")
      self.assertIn("using TitleWindowTiles = capsule::text::window::TileBuffer<kTitleWindow.w, kTitleWindow.h>;",
                    text)
      self.assertIn("screen::replace_now(next, arg);", text)
      from importlib import import_module
      sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "toolkit"))
      check_style = import_module("check_style")
      self.assertEqual([str(x) for x in check_style.check_cpp(header, text)], [])
      cxx = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
      if cxx is None:
         self.skipTest("no C++ compiler")
      main = self.root / "use.cpp"
      main.write_text('#include "list_screen.h"\nstatic_assert(list_screen::kWindowTiles == 40);\n'
                      "static_assert(list_screen::kWindowBytes == 1280);\n"
                      "static_assert(sizeof(list_screen::TitleWindowTiles) == list_screen::kWindowBytes);\n"
                      "void use(const capsule::screen::Screen& s) { list_screen::leave(s, 0); }\n", encoding="utf-8")
      r = subprocess.run([cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
                          f"-I{engine.root() / 'include'}", f"-I{self.root}", str(main)],
                         capture_output=True, text=True, check=False)
      self.assertEqual(r.returncode, 0, r.stderr)

   def test_exit_command(self) -> None:
      """!`screen-plan exit PLAN close_now` saves it and lists the frames.
      @return None
      """
      p = list_plan(self.doc)
      status, out = self.run_cli("screen-plan", "exit", p.path, "close_now")
      self.assertEqual(status, 0, out)
      self.assertIn("exit: close_now", out)
      self.assertIn("frame 1:", out)
      self.assertEqual(sp.exit_of(sp.open_plan(p.path).data)["call"], "close_now")
      status, out = self.run_cli("screen-plan", "show", p.path)
      self.assertIn("window 0 title storage: 40 tiles", out)


class InteractionTests(unittest.TestCase):
   """!core.interactions on a copy of the engine's C13b fixture."""

   def setUp(self) -> None:
      """!Copies the fixture.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_s6b_rules_"))
      for name in INTERACTION_FIXTURES:
         shutil.copytree(engine.root() / "tests" / "data" / name, self.root / name)
      ## The world file.
      self.path = self.root / INTERACTION_FIXTURES[0] / "world.json"
      ## The project.
      self.p = Project.open(self.path)

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def run_cli(self, *args: object) -> tuple[int, str]:
      """!Runs capsule-studio.
      @param args  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out), redirect_stderr(out):
         status = cli([str(a) for a in args])
      return status, out.getvalue()

   def build_error(self) -> str:
      """!What the build's map compiler says of the saved world.
      @return its message ("" when it compiles)
      """
      mc = engine.tool("map_compiler")
      try:
         mc.compile_world(self.path, scripts_path=None)
      except mc.ManifestError as e:
         return str(e)
      return ""

   def test_rules_and_edits(self) -> None:
      """!The fixture's rules compile; edits are checked by the compiler; order, conditions, removal.
      @return None
      """
      w = self.p.world
      self.assertEqual(len(interactions.rules(w)), 7)
      self.assertEqual(interactions.problems(self.p), [])
      self.assertEqual(interactions.behavior_names(w)[:3], ["normal", "wall", "pc"])
      self.assertEqual(interactions.vehicle_names(w), ["foot", "swim"])
      for bad in ({"behavior": "nothing"}, {"vehicle": "boat"}, {"facing": "north"}, {"same_level": 1}):
         fields = {"behavior": "pc", "script": "use_pc", **bad}
         with self.assertRaises(ValueError), w.edit("Bad"):
            interactions.add_rule(w, fields.pop("behavior"), fields.pop("script"), **fields)
      with w.edit("Add"):
         at = interactions.add_rule(w, "screen", "watch", 1, facing="down", same_level=False)
      self.assertEqual(at, 1)
      self.assertEqual(interactions.rules(w)[1], {"behavior": "screen", "script": "watch", "facing": "down"})
      with w.edit("Move"):
         self.assertEqual(interactions.move_rule(w, 1, 1), 2)
      self.assertEqual(interactions.rules(w)[2]["facing"], "down")
      with w.edit("Set"):
         interactions.set_rule(w, 2, facing=None, flag="climb")
      self.assertEqual(interactions.rules(w)[2], {"behavior": "screen", "script": "watch", "flag": "climb"})
      with self.assertRaises(ValueError), w.edit("Unknown key"):
         interactions.set_rule(w, 2, colour="red")
      with w.edit("Remove all"):
         for _rule in range(len(interactions.rules(w))):
            interactions.remove_rule(w, 0)
      self.assertNotIn(interactions.RULES_KEY, w.data)

   def test_problems_match_the_build(self) -> None:
      """!An unknown script is the build's own message; a rule an earlier one covers never runs.
      @return None
      """
      w = self.p.world
      with w.edit("Unknown script"):
         interactions.add_rule(w, "pc", "no_such_script")
      self.p.save_all()
      found = interactions.problems(self.p)
      self.assertEqual(len(found), 1)
      self.assertTrue(found[0].startswith("error: "), found)
      self.assertIn("unknown script 'no_such_script'", found[0])
      self.assertIn(found[0][len("error: "):], self.build_error())
      with w.edit("Fix"):
         interactions.set_rule(w, 7, script="use_pc", facing="up")
      found = interactions.problems(self.p)
      self.assertEqual(found, ["warning: rule 7 (pc -> use_pc) never runs: rule 0 is tried first and holds "
                               "whenever it does"])

   def test_commands(self) -> None:
      """!list, add, set, move, remove, check from the command line.
      @return None
      """
      status, out = self.run_cli("interactions", self.path, "list")
      self.assertEqual(status, 0, out)
      self.assertIn("0: facing a 'pc' cell -> use_pc", out)
      status, out = self.run_cli("interactions", self.path, "add", "shelf", "read", "--at", "0", "--facing", "up",
                                 "--same-level", "on")
      self.assertEqual(status, 0, out)
      self.assertIn("0: facing a 'shelf' cell, facing up, same level -> read", out)
      status, out = self.run_cli("interactions", self.path, "set", "0", "--facing", "-")
      self.assertIn("0: facing a 'shelf' cell, same level -> read", out)
      self.assertEqual(self.run_cli("interactions", self.path, "move", "0", "down")[0], 0)
      self.assertEqual(interactions.rules(Project.open(self.path).world)[1]["behavior"], "shelf")
      self.assertEqual(self.run_cli("interactions", self.path, "check"), (0, "the rules compile\n"))
      status, out = self.run_cli("interactions", self.path, "add", "nothing", "read")
      self.assertNotEqual(status, 0)
      self.assertIn("unknown behavior 'nothing'", out)
      self.assertEqual(self.run_cli("interactions", self.path, "remove", "1")[0], 0)
      self.assertEqual(len(interactions.rules(Project.open(self.path).world)), 7)


if __name__ == "__main__":
   unittest.main()
