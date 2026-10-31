#!/usr/bin/env python3
"""!Tests for text box styles [S2, S4] (no Qt): core.text_boxes (S4: asset kind text_box of engine C10, its
settings from the engine's asset compiler joined with window.h, the engine's limits, the frame's cells as
draw_frame() writes them, the checks, the Font control's fonts, S2's editor-data styles migrated into assets, the
preview typed frame by frame, the box a table fits in), core.text_window (window.cpp's interval and counter typing,
the engine's own counter_typing() expectations) and the `text-box` commands. Uses the neutral game of
text_fixture.py; the message box geometry of the tests is a two-line box over the screen's bottom rows with one cell
of padding at the left (the shape of a handheld game's message box).
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
from capsule_studio.core import engine, text_boxes, text_render, text_tables, text_window  # noqa: E402
from capsule_studio.core.document import Document, DocumentError  # noqa: E402
import text_fixture as fx  # noqa: E402

## The box of the tests: window cells (x, y, width, height) and the frame's left padding.
BOX = (2, 15, 27, 4)
## Its left padding, cells.
PAD_LEFT = 1
## The tests' style key.
KEY = "text_box:MESSAGE"
## The engine's counter typing test (tests/text_window_tests.cpp counter_typing()): the counter, the lead frames, a
## Pause control's frames, the frames run.
DELAY, LEAD, PAUSE, FRAMES = 3, 2, 5, 40
## The glyph the counter tests type ('A').
GLYPH_A = 0x41
## S2's legacy style of the migration test: its name, and a value no setting of the engine takes (font_count).
LEGACY_NAME = "old message"


class BoxCase(unittest.TestCase):
   """!Base: the fixture game with one style."""

   def setUp(self) -> None:
      """!Writes the game and opens its manifest.
      @return None
      """
      ## Temporary folder.
      self.tmp = Path(tempfile.mkdtemp(prefix="capsule_s4_box_"))
      ## The game.
      self.game = fx.make_game(self.tmp)
      ## The manifest.
      self.doc = Document.open(self.game.assets)

   def tearDown(self) -> None:
      """!Removes the folder.
      @return None
      """
      shutil.rmtree(self.tmp, ignore_errors=True)

   def add_box(self) -> dict:
      """!Adds the tests' box as text_box:MESSAGE.
      @return the style
      """
      with self.doc.edit("t"):
         style = text_boxes.add_style(self.doc, KEY, "font:BODY")
         for key, v in zip(("x", "y", "width", "height"), BOX):
            text_boxes.set_value(self.doc, KEY, "window", key, v)
         text_boxes.set_value(self.doc, KEY, "frame", "pad_left", PAD_LEFT)
      return style

   def font(self) -> dict:
      """!The fixture font compiled.
      @return compile_proportional()'s result
      """
      return text_tables.TextContext.for_manifest(self.game.assets).font(self.game.font)


class FieldTests(BoxCase):
   """!The settings follow the engine's asset compiler and header."""

   def test_fields_from_the_compiler(self) -> None:
      """!Every text_box setting of the compiler (TEXT_BOX_WINDOW / TEXT_BOX_FRAME and the words) with its range,
      the optional char_block and arrow, window.h's defaults.
      @return None
      """
      ac = engine.asset_compiler()
      fields = text_boxes.config_fields()
      window = {f.name for f in fields if f.group == "window"}
      self.assertEqual(window, set(ac.TEXT_BOX_WINDOW) | set(ac.TEXT_BOX_WORDS))
      self.assertEqual({f.name for f in fields if f.group == "frame"}, set(ac.TEXT_BOX_FRAME))
      by = {(f.group, f.name): f for f in fields}
      self.assertEqual((by[("window", "x")].low, by[("window", "x")].high), ac.TEXT_BOX_WINDOW["x"])
      self.assertEqual(by[("window", "lines")].default, 1)
      self.assertEqual(by[("window", "typing")].words, tuple(ac.TEXT_BOX_TYPING))
      self.assertEqual(by[("window", "speedup")].default, ac.TEXT_BOX_SPEEDUP[0])
      self.assertTrue(by[("window", "arrow")].optional and by[("window", "char_block")].optional)
      self.assertNotIn(("window", "font_count"), by)   # the fonts table decides it
      lim = text_boxes.limits()
      self.assertEqual(lim.screen, (30, 20))
      self.assertEqual(lim.frame, (3, 9))
      self.assertEqual(lim.banks, 16)


class StyleTests(BoxCase):
   """!Styles are text_box assets the engine compiles."""

   def test_add_set_remove_and_the_engine_compiles_them(self) -> None:
      """!A style is an asset: the engine's compile_manifest() builds it (its fonts resolved); set_value() keeps the
      compiler's ranges and words; preview data is editor data.
      @return None
      """
      self.add_box()
      self.assertEqual(text_boxes.keys(self.doc), [KEY])
      ac = engine.asset_compiler()
      with self.doc.edit("t"):
         text_boxes.set_value(self.doc, KEY, "window", "typing", "counter")
         text_boxes.set_value(self.doc, KEY, "window", "char_delay", DELAY)
         text_boxes.set_control_font(self.doc, KEY, 1, "font:BODY")
      ac.compile_manifest(self.doc.data, self.doc.base_dir)
      built = ac.compile_manifest.text_boxes
      self.assertEqual(len(built), 1)
      self.assertEqual(built[0]["window"]["typing"], ac.TEXT_BOX_TYPING.index("counter"))
      self.assertEqual(sorted(built[0]["fonts"]), [1])
      self.assertTrue(self.doc.compile_asset(text_boxes.find(self.doc, KEY)).ok)
      for args in (("window", "x", 300), ("window", "nope", 1), ("window", "typing", "fast"),
                   ("preview", "colors", ["red"]), ("", "size", 1)):
         with self.assertRaises(DocumentError):
            with self.doc.edit("t"):
               text_boxes.set_value(self.doc, KEY, *args)
      with self.doc.edit("t"):
         text_boxes.set_value(self.doc, KEY, "window", "arrow", None)   # left out: no arrow
         text_boxes.add_style(self.doc, "COPY", like=KEY)
         text_boxes.set_value(self.doc, "text_box:COPY", "preview", "frame_entries", [6, 7])
         text_boxes.set_value(self.doc, "text_box:COPY", "", "key", "text_box:SECOND")
      self.assertEqual(text_boxes.find(self.doc, "text_box:SECOND")["window"]["width"], BOX[2])
      self.assertEqual(text_boxes.preview_data(text_boxes.find(self.doc, "text_box:SECOND"))["frame_entries"], [6, 7])
      self.assertNotIn("arrow", text_boxes.find(self.doc, KEY)["window"])
      with self.assertRaises(DocumentError):   # one key per asset
         with self.doc.edit("t"):
            text_boxes.add_style(self.doc, KEY)
      with self.doc.edit("t"):
         text_boxes.remove_style(self.doc, "text_box:SECOND")
         text_boxes.remove_style(self.doc, KEY)
      self.assertEqual(text_boxes.styles(self.doc), [])
      self.doc.undo()
      self.assertEqual(len(text_boxes.styles(self.doc)), 2)

   def test_engine_fixture_and_checks(self) -> None:
      """!The engine's C10 fixture style reads back with its settings; a font that is no font asset is refused.
      @return None
      """
      fixture = engine.root() / "tests" / "data" / "c10" / "assets.json"
      doc = Document.open(fixture)
      style = text_boxes.find(doc, "text_box:C10_MESSAGE")
      self.assertEqual(text_boxes.value(style, "window", "typing"), "counter")
      self.assertEqual(text_boxes.value(style, "window", "speedup"), "per_frame")
      self.assertIsNone(text_boxes.value(style, "window", "char_block"))   # the layer's
      self.assertEqual(text_boxes.number(style, "window", "char_block"), engine.asset_compiler().LAYER_CHAR_BLOCK)
      self.assertEqual(text_boxes.control_fonts(style), {3: "font:C10_BOX"})
      self.assertEqual(text_boxes.check(style, None, text_boxes.font_keys(doc)), [])
      bad = dict(style, font="font:NOPE")
      self.assertIn("no font asset", "\n".join(text_boxes.check(bad, None, text_boxes.font_keys(doc))))
      self.assertFalse(doc.compile_asset(bad).ok)

   def test_frame_cells(self) -> None:
      """!The ring one cell outside the window grown by the padding, its parts as window.cpp writes them.
      @return None
      """
      style = self.add_box()
      cells = text_boxes.frame_cells(style)
      x, y, w, h = BOX
      xs = sorted({c[0] for c in cells})
      ys = sorted({c[1] for c in cells})
      self.assertEqual((xs[0], xs[-1], ys[0], ys[-1]), (x - PAD_LEFT - 1, x + w, y - 1, y + h))
      self.assertEqual(cells[(x - PAD_LEFT - 1, y - 1)], 0)   # top-left
      self.assertEqual(cells[(x + w, y + h)], 8)   # bottom-right
      self.assertEqual(cells[(x - PAD_LEFT, y)], 4)   # the padding takes the inside part
      self.assertNotIn((x, y), cells)   # the window's own cells

   def test_checks_and_fit_box(self) -> None:
      """!Too many tiles, a layer that does not exist, lines that do not fit; the table's box.
      @return None
      """
      style = self.add_box()
      font = self.font()
      self.assertEqual(text_boxes.check(style, font, text_boxes.font_keys(self.doc)), [])
      lim = text_boxes.limits()
      # S5: one row more than window::kMaxTiles holds at this width (the engine's limit, 256 since N3), and more
      # lines than that height takes
      height = lim.max_tiles // BOX[2] + 1
      lines = height * lim.tile // font["line_height"] + 2   # the last line starts below the window
      with self.doc.edit("t"):
         text_boxes.set_value(self.doc, KEY, "window", "height", height)
         text_boxes.set_value(self.doc, KEY, "window", "lines", lines)
      style["window"]["bg"] = lim.layers   # past the compiler's range: refused by it too
      problems = "\n".join(text_boxes.check(style, font))
      self.assertIn(f"{BOX[2] * height} cells", problems)
      self.assertIn(f"{lim.max_tiles} tiles (window::kMaxTiles)", problems)
      self.assertIn(f"layer {lim.layers}", problems)
      self.assertIn("bg must be", problems)   # the compiler's message
      self.assertIn(f"{lines} lines", problems)
      self.assertEqual(text_boxes.fit_box(style, "body"), {"font": "body", "width": BOX[2] * lim.tile,
                                                           "lines": lines})

   def test_migrate_editor_data_styles(self) -> None:
      """!S2's editor-data styles become text_box assets the engine compiles; kNoArrow and font_count are left out.
      @return None
      """
      no_arrow = engine.tool("text_encoder").CODE_END
      legacy = {"name": LEGACY_NAME, "font": "font:BODY",
                "window": {"x": 2, "y": 15, "width": 26, "height": 4, "arrow": no_arrow, "font_count": 0},
                "frame": {"pad_left": 1}, "preview": {"frame_entries": [4, 5]}}
      with self.doc.edit("t"):
         self.doc.data["editor"] = {text_boxes.STYLES_KEY: [legacy]}
      self.assertEqual(len(text_boxes.legacy_styles(self.doc)), 1)
      with self.doc.edit("t"):
         done = text_boxes.migrate(self.doc)
      self.assertEqual(done, [(LEGACY_NAME, "text_box:OLD_MESSAGE", ["window.font_count"])])
      self.assertNotIn("editor", self.doc.data)
      style = text_boxes.find(self.doc, "text_box:OLD_MESSAGE")
      self.assertNotIn("arrow", style["window"])
      self.assertEqual(text_boxes.preview_data(style)["frame_entries"], [4, 5])
      engine.asset_compiler().compile_manifest(self.doc.data, self.doc.base_dir)
      self.doc.undo()
      self.assertEqual(len(text_boxes.legacy_styles(self.doc)), 1)

   def test_preview_frames(self) -> None:
      """!The preview at a frame: backdrop, frame lines, the window's background, the text's ink once typed.
      @return None
      """
      style = self.add_box()
      ctx = text_tables.TextContext.for_manifest(self.game.assets)
      font = ctx.font(self.game.font)
      codes = ctx.encode("Hello", "t")
      pens = text_boxes.pens(style)
      x, y, _w, _h = BOX
      ink_at = (x * 8, y * 8 + 1 + fx.SHAPE_TOP)   # H's ink (top 1)
      canvas = text_boxes.preview(style, font, codes, 0, self.doc.base_dir)   # the end (no waits)
      self.assertEqual(canvas.pixel(0, 0), pens.color(0))   # backdrop
      self.assertEqual(canvas.pixel((x - PAD_LEFT - 1) * 8, (y - 1) * 8), pens.color(4))   # the frame's outer line
      self.assertEqual(canvas.pixel(*ink_at), pens.color(pens.ink))
      self.assertEqual(canvas.pixel(x * 8 + 7, y * 8), pens.color(pens.background))
      first = text_boxes.preview(style, font, codes, frame=0, base=self.doc.base_dir)   # after print(): nothing yet
      self.assertEqual(first.pixel(*ink_at), pens.color(pens.background))
      run = text_boxes.typing(style, font, codes)
      self.assertEqual(run.done, len("Hello") + 1)   # interval typing, a glyph a frame, then the end code is read
      self.assertEqual(text_boxes.wait_frames(run), [run.done])


class TypingTests(unittest.TestCase):
   """!core.text_window types as window.cpp does (the engine's own expectations)."""

   def setUp(self) -> None:
      """!A blank font of 4-pixel glyphs and the engine's codes.
      @return None
      """
      ## The engine's text encoder.
      self.te = text_render.encoder()
      ## A font: every printable code 4 pixels wide, 10-pixel lines.
      self.font = {"first": 0x20, "widths": [4] * 0x40, "glyphs": [bytes(16)] * 0x40, "cell": (8, 8),
                   "line_height": 10, "letter_spacing": 0}
      ## The engine test's counter window: per_frame speed-up, lead frames.
      self.counter = {"width": 8, "height": 4, "lines": 2, "typing": 1, "char_delay": DELAY, "speedup": 1,
                      "lead_frames": LEAD}

   def glyph_frames(self, codes: list[int], press_at_4: bool, hold: bool, count: int) -> list[int]:
      """!The update (1-based) on which each glyph appears (the engine test's glyph_frames()).
      @param codes       the text
      @param press_at_4  Accept goes down on update 4
      @param hold        Accept held throughout
      @param count       glyphs looked for
      @return the updates
      """
      w = text_window.Window(self.counter, self.font)
      w.print(codes)
      out = []
      pen, line = w.pen_x, w.line_y
      for f in range(1, FRAMES + 1):
         w.update(press_at_4 and f == 4, hold)
         moved = w.pen_x != pen and w.line_y == line and w.pen_x > pen
         if moved or (w.line_y != line and w.pen_x > 0):
            out.append(f)
         pen, line = w.pen_x, w.line_y
         if len(out) == count:
            break
      return out

   def test_counter_typing(self) -> None:
      """!tests/text_window_tests.cpp counter_typing(): lead 2 then every 4 frames, a pause, a newline, the speed-up.
      @return None
      """
      a, end = GLYPH_A, self.te.CODE_END
      pause = self.te.CONTROL_CODES["pause"][0]
      self.assertEqual(self.glyph_frames([a] * 4 + [end], False, False, 4), [3, 7, 11, 15])
      self.assertEqual(self.glyph_frames([a, self.te.CODE_CONTROL, pause, PAUSE, a, end], False, False, 2), [3, 13])
      self.assertEqual(self.glyph_frames([a, self.te.CODE_NEWLINE, a, end], False, False, 2), [3, 10])
      self.assertEqual(self.glyph_frames([a] * 4 + [end], True, True, 4), [3, 5, 6, 7])   # a press, then held
      self.assertEqual(self.glyph_frames([a] * 4 + [end], False, True, 2), [3, 7])   # held alone: no speed-up

   def test_interval_typing_and_policies(self) -> None:
      """!Interval typing: a glyph every frames_per_char frames, held types the rest at once; a prompt waits for the
      policy's press; none stops at the first wait.
      @return None
      """
      a, end = GLYPH_A, self.te.CODE_END
      interval = {"width": 8, "height": 4, "lines": 2, "frames_per_char": 2}
      run = text_window.run(interval, self.font, [a] * 3 + [end])
      self.assertEqual(run.done, 7)   # updates 1, 3, 5 type, 7 reads the end code (busy() until then)
      held = text_window.run(interval, self.font, [a] * 3 + [end], "hold")
      self.assertEqual(held.done, 1)
      prompt = [a, self.te.CODE_PROMPT, a, end]
      advanced = text_window.run(interval, self.font, prompt, "advance")
      self.assertEqual(advanced.waits, [3])   # A on update 1, the prompt read on update 3
      self.assertEqual(advanced.presses, [3 + text_window.PRESS_AFTER])
      self.assertIsNotNone(advanced.done)
      stopped = text_window.run(interval, self.font, prompt, "none")
      self.assertIsNone(stopped.done)
      with self.assertRaises(ValueError):
         text_window.key_policy("fast")


class CommandTests(BoxCase):
   """!`text-box` commands."""

   def run_cli(self, *args: object) -> tuple[int, str]:
      """!Runs capsule-studio.
      @param args  arguments
      @return (status, output)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         status = cli([str(a) for a in args])
      return status, out.getvalue() + err.getvalue()

   def test_box_commands(self) -> None:
      """!add, set, font, list, show, fields, preview, timeline, migrate, apply, remove.
      @return None
      """
      a = self.game.assets
      self.assertEqual(self.run_cli("text-box", "add", a, "MESSAGE", "--font", "font:BODY")[0], 0)
      for setting, value in (("window.width", "27"), ("frame.pad_left", "1"), ("preview.colors", "#000000,#ffffff"),
                             ("preview.frame_entries", "2,3"), ("window.typing", "counter"),
                             ("window.char_delay", "3"), ("window.speedup", "per_frame"), ("window.arrow", "-")):
         status, out = self.run_cli("text-box", "set", a, KEY, setting, value)
         self.assertEqual(status, 0, (setting, out))
      status, out = self.run_cli("text-box", "font", a, KEY, "7", "font:BODY")
      self.assertEqual(json.loads(out), {"7": "font:BODY"})
      status, out = self.run_cli("text-box", "list", a)
      self.assertIn("27x4 cells", out)
      self.assertIn("typing counter", out)
      status, out = self.run_cli("text-box", "show", a, KEY)
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("text-box", "fields")
      self.assertIn("frame.pad_bottom", out)
      self.assertIn("interval|counter", out)
      status, out = self.run_cli("text-box", "preview", a, KEY, self.tmp / "box.png", "--table", self.game.en,
                                 "text:Main.Greeting", "--scale", "1", "--frame", "10")
      self.assertEqual(status, 0, out)
      self.assertEqual(engine.bitmap().read_png(self.tmp / "box.png")[:2], (240, 160))
      status, out = self.run_cli("text-box", "timeline", a, KEY, "--text", "Hi{prompt}there", "--keys", "hold")
      self.assertEqual(status, 0, out)
      self.assertIn("waits begin at", out)
      status, out = self.run_cli("text-box", "apply", a, KEY, self.game.en)
      self.assertEqual(json.loads(out), {"font": "body", "width": 27 * 8, "lines": 2})
      self.assertEqual(self.run_cli("text-box", "set", a, KEY, "window.x", "999")[0], 1)
      self.assertEqual(self.run_cli("text-box", "migrate", a)[1].strip(), "no editor-data styles")
      self.assertEqual(self.run_cli("text-box", "remove", a, KEY)[0], 0)


if __name__ == "__main__":
   unittest.main()
