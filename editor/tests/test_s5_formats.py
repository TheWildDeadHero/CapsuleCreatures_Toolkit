#!/usr/bin/env python3
"""!S5 (engine N1 / N2 / N3) without Qt: text box styles' art as engine data (core.text_boxes: palette, the frame's
image and palette, the window's arrow image compiled by the engine, typed by core.text_window as window.cpp steps
it; window::kMaxTiles read from the engine), menu styles (core.menu_styles: the settings from the compiler and
menu.h, the edits and their refusals, and the menu run frame by frame against the engine's own ui_tests.cpp
expectations: the repeat counter, a column's delay / wrap / sounds / one action a frame, the every-key order, a
grid, a list against the middle-row model, the arrows' bounce and visibility, print_at() / fill() and the arrow
image's steps), the `text-box` commands for both, a test save's Game section (core.game_block: set / poke / from a
save file / clear, checked, written into the exported image's Game section by the engine's payload and assemble,
`testsave game`), the route steps' help (core.script_words.route_step_help(): engine N2's in_place and speed) and
any JSON shown read-only (core.json_view).

Uses copies of the engine's N3 fixture (tests/data/ui: a font, a two-arrow sprite, text box styles with menus, a
message box with an arrow image) and of the Starter sample (test_battle.BattleTestCase) for the test saves.
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
from capsule_studio.core import (engine, game_block, inventory, json_view, menu_styles, script_words,  # noqa: E402
                                 text_boxes, text_render, text_tables, text_window)
from capsule_studio.core.document import Document, DocumentError  # noqa: E402
from test_battle import BattleTestCase  # noqa: E402

## The fixture's styles.
COLUMN, START, LIST, MESSAGE = "text_box:UI_COLUMN", "text_box:UI_START", "text_box:UI_LIST", "text_box:UI_MESSAGE"
## The fixture's options (codes of A, B and C: the font's glyphs) and the eight the engine's tests show.
A, B, C = [0x41], [0x42], [0x43]
ITEMS = [A, B, C, A, B, C, A, B]
## The engine's ui_tests.cpp constants: the move / open sounds, the repeat's start and interval, the windows'
## background and ink, the menus' row height, top margin and option column, pixels per tile.
MOVE_SOUND, OPEN_SOUND = 5, 7
REPEAT_START, REPEAT_EVERY = 40, 5
BACKGROUND, INK = 1, 2
ROW_HEIGHT, TOP, OPTION_X, TILE = 4, 1, 4, 8
## The repeats the engine's test counts in its window (at 40, 45 and 50 frames after the press).
REPEATS = 3
## Frames of the arrow image's delay in the fixture, and its steps' top rows (the triangle from row 2 of 6).
ARROW_DELAY, ARROW_TOP_ROWS = 8, (2, 1, 0, 1)
## Rows the arrow image test looks through for the ink.
ARROW_LOOK = 4
## Most rows shown the list test tries.
MOST_SHOWN = 4
## Moves of the list test (down then up).
LIST_MOVES = 20
## A test save's game block: its version, size and first bytes.
GAME_VERSION, GAME_SIZE, GAME_BYTES = 3, 40, bytes([1, 2, 3, 0, 5])


def run_cli(*argv: str) -> tuple[int, str]:
   """!Runs the CLI.
   @param argv  arguments
   @return (exit status, stdout + stderr)
   """
   out, err = io.StringIO(), io.StringIO()
   with redirect_stdout(out), redirect_stderr(err):
      try:
         code = cli(list(argv))
      except SystemExit as e:
         code = int(e.code or 0)
   return code, out.getvalue() + err.getvalue()


def keys(pressed: int) -> menu_styles.Keys:
   """!One frame's keys with nothing repeated (ui_tests.cpp press()).
   @param pressed  key bits that went down
   @return Keys
   """
   return menu_styles.Keys(pressed, pressed, pressed)


def bit(*names: str) -> int:
   """!Key bits.
   @param names  key names (A, B, UP, ...)
   @return bits
   """
   return menu_styles.key_bits(list(names))


class UiCase(unittest.TestCase):
   """!Base: a copy of the engine's N3 fixture (tests/data/ui) per test."""

   def setUp(self) -> None:
      """!Copies the fixture and opens its manifest.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_s5_"))
      shutil.copytree(engine.root() / "tests" / "data" / "ui", self.root / "ui")
      ## The fixture's folder.
      self.base = self.root / "ui"
      ## Its manifest.
      self.assets = self.base / "assets.json"
      ## The manifest Document.
      self.doc = Document.open(self.assets)
      ## The fixture font compiled.
      self.font = text_tables.TextContext.for_manifest(self.assets).font(self.base / "ui.font.json")
      ## Sounds played by the menus under test: (what, id).
      self.sounds = []

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def style(self, key: str) -> dict:
      """!A style of the fixture.
      @param key  its key
      @return the style
      """
      return text_boxes.find(self.doc, key)

   def window(self, key: str) -> text_window.Window:
      """!An open window of a style (ui_tests.cpp open_window()).
      @param key  the style
      @return Window
      """
      return text_window.Window(text_boxes.settings(self.style(key), self.base), self.font)

   def menu(self, key: str, options: menu_styles.Options) -> menu_styles.Menu:
      """!A menu of a style opened in its window.
      @param key      the style
      @param options  what it shows
      @return Menu
      """
      return menu_styles.Menu(self.window(key), menu_styles.numbers(self.style(key)), options,
                              lambda what, n: self.sounds.append((what, n)))


class ArtTests(UiCase):
   """!A style's art as engine data, and the engine's limits."""

   def test_styles_compile_with_their_images(self) -> None:
      """!Every fixture style compiles with the manifest's folder (images read) and without it (images left out);
      the arrow image becomes the window's settings; the palettes colour the pens; the frame image is the frame art.
      @return None
      """
      for style in text_boxes.styles(self.doc):
         self.assertEqual(text_boxes.check(style, self.font, text_boxes.font_keys(self.doc), self.base), [],
                          style["key"])
         text_boxes.compile_style(style)   # no folder: compiled without the images
      self.assertEqual(self.doc.compile_asset(self.style(MESSAGE)).error, None)
      message = self.style(MESSAGE)
      k = text_window.header_constants()
      s = text_boxes.settings(message, self.base)
      self.assertEqual((s["arrow_kind"], s["arrow_offsets"], s["arrow_delay"]), (k["kArrowImage"], [0, 1, 2, 1],
                                                                                  ARROW_DELAY))
      self.assertNotIn("arrow_kind", text_boxes.settings(message))   # without the folder: no image
      self.assertEqual(text_boxes.pens(message).color(1), text_render.parse_color(message["palette"][0]))
      column = self.style(COLUMN)
      self.assertEqual(text_boxes.frame_pens(column).color(2), text_render.parse_color(column["frame"]["palette"][1]))
      w, h, px = engine.bitmap().read_png_indices(self.base / column["frame"]["image"])
      art = text_boxes.frame_art(column, self.base)
      self.assertEqual(art[0][0][:TILE], list(px[:TILE]))
      strip = text_boxes.arrow_strip(message, self.base)
      self.assertEqual(strip.height, s["arrow_height"])

   def test_art_edits_and_refusals(self) -> None:
      """!The palette, the frame's image and palette and the arrow image are set, left out and refused as the engine
      would; an arrow image the compiler refuses is an error of check().
      @return None
      """
      with self.doc.edit("t"):
         text_boxes.set_value(self.doc, COLUMN, "", text_boxes.PALETTE_KEY, ["#102030", "#ffffff"])
         text_boxes.set_value(self.doc, COLUMN, "frame", text_boxes.FRAME_PALETTE_KEY, None)
         text_boxes.set_value(self.doc, COLUMN, "window", text_boxes.ARROW_IMAGE_KEY,
                              {"image": "arrow.png", "steps": [0, 1], "delay": 2})
      column = self.style(COLUMN)
      self.assertEqual(column["palette"], ["#102030", "#ffffff"])
      self.assertNotIn("palette", column["frame"])
      self.assertEqual(text_boxes.check(column, None, None, self.base), [])
      most = text_render.bank_colors() - 1
      for group, name, value in (("", "palette", ["#000000"] * (most + 1)), ("", "palette", ["blue"]),
                                 ("frame", "image", "/abs/frame.png"), ("window", "arrow_image", {"pic": "a.png"}),
                                 ("window", "arrow_image", "arrow.png")):
         with self.assertRaises(DocumentError, msg=f"{group}.{name}"):
            with self.doc.edit("t"):
               text_boxes.set_value(self.doc, COLUMN, group, name, value)
      with self.doc.edit("t"):
         text_boxes.set_value(self.doc, COLUMN, "window", text_boxes.ARROW_IMAGE_KEY, {"image": "frame.png"})
      problems = text_boxes.check(self.style(COLUMN), None, None, self.base)
      self.assertTrue(any("8 pixels wide" in p for p in problems), problems)   # the compiler's message

   def test_max_tiles_is_the_engines(self) -> None:
      """!window::kMaxTiles comes from window.h: a window of that many cells passes, one row more is refused.
      @return None
      """
      lim = text_boxes.limits()
      self.assertEqual(lim.max_tiles, text_boxes.constants()["kMaxTiles"])
      width = lim.screen[0]
      with self.doc.edit("t"):
         text_boxes.set_value(self.doc, MESSAGE, "window", "x", 0)
         text_boxes.set_value(self.doc, MESSAGE, "window", "width", width)
         text_boxes.set_value(self.doc, MESSAGE, "window", "height", lim.max_tiles // width)
      self.assertFalse(any("kMaxTiles" in p for p in text_boxes.check(self.style(MESSAGE))))
      with self.doc.edit("t"):
         text_boxes.set_value(self.doc, MESSAGE, "window", "height", lim.max_tiles // width + 1)
      self.assertTrue(any("kMaxTiles" in p for p in text_boxes.check(self.style(MESSAGE))))


class WindowTests(UiCase):
   """!print_at(), fill() and the arrow image's steps (ui_tests.cpp arrow_image())."""

   def test_print_at_and_arrow_image(self) -> None:
      """!print_at() draws over the pixels, fill() clears; a page break's wait steps the image at the pen (shown at
      once, then every delay + 1 frames, through the offsets), erased by the press.
      @return None
      """
      w = self.window(MESSAGE)
      pixel = lambda x, y: w.pixels[y * w.width + x]   # noqa: E731
      w.print_at(0, TOP, A)
      self.assertEqual(pixel(0, TOP), INK)
      w.print_at(TILE, TOP, B)
      self.assertEqual((pixel(0, TOP), pixel(TILE + 1, TOP)), (INK, INK))   # nothing cleared
      w.fill(0, 0, TILE, TILE, BACKGROUND)
      self.assertEqual(pixel(0, TOP), BACKGROUND)
      te = text_render.encoder()
      w.print(A + [te.CODE_PAGE_BREAK] + B)
      w.update()
      w.update()   # the page break: the wait begins
      self.assertTrue(w.waiting())
      pen = w.pen_x

      def top_row() -> int:
         """!The first image row with ink at the pen (-1: none)."""
         return next((y for y in range(ARROW_LOOK) if pixel(pen + 1, TOP + y) == INK), -1)

      w.update()
      self.assertEqual(top_row(), ARROW_TOP_ROWS[0])
      for _ in range(ARROW_DELAY):
         w.update()
      self.assertEqual(top_row(), ARROW_TOP_ROWS[0])
      w.update()   # the ninth frame: the second step
      self.assertEqual(top_row(), ARROW_TOP_ROWS[1])
      for _ in range(ARROW_DELAY + 1):
         w.update()
      self.assertEqual(top_row(), ARROW_TOP_ROWS[2])
      w.update(True)   # the press: the page clears
      self.assertEqual(top_row(), -1)


class MenuTests(UiCase):
   """!Menus run as the engine's ui module runs them (ui_tests.cpp's cases)."""

   def test_fields_follow_the_compiler(self) -> None:
      """!The settings are the compiler's in its order, with menu.h's defaults; edits are checked.
      @return None
      """
      ac = engine.asset_compiler()
      fields = menu_styles.menu_fields()
      self.assertEqual([f.name for f in fields], list(ac.MENU_ORDER))
      by = {f.name: f for f in fields}
      self.assertEqual((by["cancel_keys"].default, by["cursor"].default, by["wrap"].default), (["B"], None, "never"))
      self.assertEqual((by["sound_move"].low, by["sound_move"].high), ac.TEXT_BOX_MENU["sound_move"])
      with self.doc.edit("t"):
         menu_styles.set_value(self.doc, MESSAGE, "wrap", "always")   # a style without a menu gets one
         menu_styles.set_value(self.doc, MESSAGE, "cancel_keys", ["START", "B"])
      self.assertEqual(self.style(MESSAGE)["menu"], {"wrap": "always", "cancel_keys": ["B", "START"]})
      self.assertEqual(text_boxes.check(self.style(MESSAGE), None, None, self.base), [])
      for name, v in (("wrap", "sometimes"), ("option_x", 256), ("cancel_keys", ["Z"]), ("arrow_sprite", "arrows"),
                      ("nothing", 1)):
         with self.assertRaises(DocumentError, msg=name):
            with self.doc.edit("t"):
               menu_styles.set_value(self.doc, MESSAGE, name, v)
      with self.doc.edit("t"):
         menu_styles.set_menu(self.doc, MESSAGE, False)
      self.assertFalse(menu_styles.has_menu(self.style(MESSAGE)))
      n = menu_styles.numbers(self.style(COLUMN))
      c = menu_styles.header_constants()
      self.assertEqual((n["wrap"], n["cancel_keys"]), (c["kWrapAbove"], bit("B")))

   def test_repeat_counter(self) -> None:
      """!The start, the interval, a change of keys starting it again (ui_tests.cpp repeat_counter()).
      @return None
      """
      s = menu_styles.KeyState(REPEAT_START, REPEAT_EVERY)
      down = bit("DOWN")
      k = s.read(down)
      self.assertTrue(k.pressed & down and k.repeated & down)
      frames = [f for f in range(1, REPEAT_START + REPEAT_EVERY * 2 + 1) if s.read(down).repeated & down]
      self.assertEqual(frames, [REPEAT_START + REPEAT_EVERY * i for i in range(REPEATS)])
      k = s.read(down | bit("A"))
      self.assertTrue(k.pressed & bit("A") and not k.pressed & down and k.held & down)
      self.assertFalse(any(s.read(down | bit("A")).repeated & down for _ in range(1, REPEAT_START)))

   def test_column(self) -> None:
      """!The input delay, the wrap rule (above three options), sounds, one action a frame, cancel (column()).
      @return None
      """
      m = self.menu(COLUMN, menu_styles.Options(ITEMS[:4], cursor=1))
      pixel = lambda x, y: m.w.pixels[y * m.w.width + x]   # noqa: E731
      cursor_on = lambda row: pixel(0, TOP + row * ROW_HEIGHT) == INK   # noqa: E731
      self.assertTrue(cursor_on(1) and not cursor_on(0))
      self.assertEqual(pixel(OPTION_X + 1, TOP + ROW_HEIGHT), INK)
      self.sounds.clear()
      self.assertEqual((m.update(keys(bit("DOWN"))), m.cursor), (menu_styles.NOTHING, 1))
      self.assertEqual((m.update(keys(bit("DOWN"))), m.cursor, len(self.sounds)), (menu_styles.NOTHING, 1, 0))
      self.assertEqual((m.update(keys(bit("DOWN"))), m.cursor, len(self.sounds)), (menu_styles.NOTHING, 2, 1))
      self.assertTrue(cursor_on(2) and not cursor_on(1))
      m.update(keys(bit("DOWN")))
      m.update(keys(bit("DOWN")))   # four options: past the last to the first
      self.assertTrue(m.cursor == 0 and cursor_on(0) and not cursor_on(3))
      m.update(keys(bit("UP")))
      self.assertEqual(m.cursor, 3)
      sounds = len(self.sounds)
      self.assertEqual(m.update(keys(bit("A", "DOWN"))), 3)   # Accept before Down
      self.assertEqual((m.cursor, len(self.sounds), self.sounds[-1][1]), (3, sounds + 1, MOVE_SOUND))
      o = menu_styles.Options(ITEMS[:3], cancel=False, delay=0)
      m = self.menu(COLUMN, o)
      self.sounds.clear()
      m.update(keys(bit("UP")))
      self.assertEqual((m.cursor, self.sounds), (0, []))   # three options: no wrap, no sound
      self.assertEqual((m.update(keys(bit("B"))), self.sounds), (menu_styles.NOTHING, []))
      o.cancel = True
      m = self.menu(COLUMN, o)
      self.assertEqual((m.update(keys(bit("B"))), len(self.sounds)), (menu_styles.CANCEL, 1))

   def test_every_key_and_grid(self) -> None:
      """!Up and Accept in one frame move, then pick; Start cancels (every_key()); a grid's moves stay inside it
      (grid()).
      @return None
      """
      m = self.menu(START, menu_styles.Options(ITEMS[:3]))
      self.assertEqual((m.update(keys(bit("UP", "A"))), m.cursor), (2, 2))
      self.sounds.clear()
      m.update(keys(bit("UP", "DOWN")))
      self.assertEqual((m.cursor, len(self.sounds)), (2, 2))
      self.assertEqual(m.update(keys(bit("START"))), menu_styles.CANCEL)
      o = menu_styles.Options(ITEMS[:6], columns=2, option_width=TILE, delay=0)
      m = self.menu(COLUMN, o)
      self.assertEqual(m.rows, 3)
      self.sounds.clear()
      m.update(keys(bit("RIGHT")))
      self.assertEqual((m.cursor, len(self.sounds)), (1, 1))
      self.assertEqual(m.w.pixels[TOP * m.w.width + TILE], INK)   # the cursor in the second column
      m.update(keys(bit("RIGHT")))
      self.assertEqual((m.cursor, len(self.sounds)), (1, 1))
      for _ in range(3):
         m.update(keys(bit("DOWN")))
      self.assertEqual(m.cursor, 5)
      o.items = ITEMS[:5]
      m = self.menu(COLUMN, o)
      m.move_to(3)
      m.update(keys(bit("DOWN")))
      self.assertEqual(m.cursor, 3)

   def test_list_against_the_model(self) -> None:
      """!The middle-row rule against ui_tests.cpp's own model (down to the end and back), the open sound, repeats
      move, a move that changes nothing plays nothing (list()).
      @return None
      """
      for shown in range(1, MOST_SHOWN + 1):
         self.sounds.clear()
         m = self.menu(LIST, menu_styles.Options(ITEMS, shown=shown))
         self.assertEqual(self.sounds, [("open", OPEN_SOUND)])
         scroll, row = 0, 0
         half = shown // 2 + shown % 2
         for i in range(LIST_MOVES):
            down = i < LIST_MOVES // 2
            if down:
               stop = 0 if shown == 1 else half
               if scroll == len(ITEMS) - shown:
                  row = row + 1 if row < shown - 1 else row
               elif row < stop:
                  row += 1
               else:
                  scroll, row = scroll + 1, stop
            else:
               stop = 0 if shown == 1 else shown - half - 1
               if scroll == 0:
                  row = row - 1 if row > 0 else row
               elif row > stop:
                  row -= 1
               else:
                  scroll, row = scroll - 1, stop
            m.update(keys(bit("DOWN" if down else "UP")))
            self.assertEqual((m.scroll, m.cursor), (scroll, scroll + row), f"shown {shown}, move {i}")
      m = self.menu(LIST, menu_styles.Options(ITEMS, shown=MOST_SHOWN))
      m.update(menu_styles.Keys(bit("DOWN"), 0, bit("DOWN")))   # a repeat
      self.assertEqual(m.cursor, 1)
      self.sounds.clear()
      m.update(keys(bit("UP")))
      m.update(keys(bit("UP")))
      self.assertEqual((m.cursor, len(self.sounds)), (0, 1))

   def test_arrows(self) -> None:
      """!The bounce's values (trig.h's table), hidden on the first frame, shown towards where the list can scroll,
      the phases moving at the style's speed (arrows()).
      @return None
      """
      self.assertEqual([menu_styles.bounce(2, p) for p in (0, 64, 192, 21, 22, 234)], [0, 2, -2, 0, 1, -1])
      a = menu_styles.Arrows(menu_styles.numbers(self.style(LIST)))
      self.assertEqual(a.update(0, 4), menu_styles.ArrowState())
      first = a.update(0, 4)
      self.assertEqual((first.up, first.down), (False, True))
      second = a.update(2, 4)
      speed = menu_styles.numbers(self.style(LIST))["arrow_speed"]
      self.assertEqual((second.up, second.down, second.up_dy), (True, True, menu_styles.bounce(2, speed)))
      last = a.update(4, 4)
      self.assertEqual((last.up, last.down, last.down_dy), (True, False, menu_styles.bounce(2, -2 * speed % 256)))

   def test_run_preview_and_script(self) -> None:
      """!run() over a key script holds Down past the repeat's start; the preview settings are checked; the window
      is fitted to the options when the preview says so; preview() draws the screen.
      @return None
      """
      with self.doc.edit("t"):
         menu_styles.set_preview(self.doc, LIST, "repeat", [REPEAT_START, REPEAT_EVERY])
         menu_styles.set_preview(self.doc, LIST, "kind", "list")
         menu_styles.set_preview(self.doc, LIST, "shown", MOST_SHOWN)
      held = REPEAT_START + REPEAT_EVERY + 1   # through the second repeat
      r = menu_styles.run(self.style(LIST), self.font, ITEMS, menu_styles.parse_script(f"down*{held} a"),
                          base=self.base)
      moves = [f for f, t in r.events if "(move)" in t]
      self.assertEqual(moves, [1, REPEAT_START + 1, REPEAT_START + REPEAT_EVERY + 1])
      self.assertEqual(r.answer, (3, held + 2))
      self.assertTrue(r.arrows and r.arrows[-1].up)
      canvas = menu_styles.preview(r, len(r.frames) - 1, self.base)
      lim = text_boxes.limits()
      self.assertEqual((canvas.width, canvas.height), (lim.screen[0] * lim.tile, lim.screen[1] * lim.tile))
      self.assertIn("chose option 3", menu_styles.describe(r))
      for name, v in (("kind", "wheel"), ("script", "jump"), ("repeat", [1]), ("colour", 1)):
         with self.assertRaises(DocumentError, msg=name):
            with self.doc.edit("t"):
               menu_styles.set_preview(self.doc, LIST, name, v)
      self.assertEqual(menu_styles.parse_script("up+a wait 2 b"), [bit("UP", "A"), 0, 0, 0, bit("B"), 0])
      with self.doc.edit("t"):
         menu_styles.set_preview(self.doc, LIST, "fit", True)
      fitted = menu_styles.fitted_style(self.style(LIST), menu_styles.Options(ITEMS[:2]), self.font)
      self.assertEqual(fitted["window"]["height"], 2)   # top 1 + 2 rows of 4 pixels: two cells (line height 4)

   def test_commands(self) -> None:
      """!`text-box menu` shows / sets / clears; `menu-run` and `menu-preview` run it; `text-box set` takes the art.
      @return None
      """
      m = str(self.assets)
      code, out = run_cli("text-box", "menu", m, COLUMN)
      self.assertEqual(code, 0)
      self.assertIn("wrap = above", out)
      self.assertEqual(run_cli("text-box", "menu", m, COLUMN, "set", "wrap", "always")[0], 0)
      self.assertEqual(run_cli("text-box", "menu", m, COLUMN, "set", "cancel_keys", "B,START")[0], 0)
      saved = text_boxes.find(Document.open(self.assets), COLUMN)["menu"]
      self.assertEqual((saved["wrap"], saved["cancel_keys"]), ("always", ["B", "START"]))
      self.assertNotEqual(run_cli("text-box", "menu", m, COLUMN, "set", "wrap", "sometimes")[0], 0)
      code, out = run_cli("text-box", "menu-run", m, COLUMN, "--items", "A|B|C", "--keys", "wait 2 down a")
      self.assertEqual(code, 0)
      self.assertIn("chose option 1", out)
      png = self.root / "menu.png"
      self.assertEqual(run_cli("text-box", "menu-preview", m, LIST, str(png), "--kind", "list", "--shown", "2",
                               "--items", "A|B|C|A", "--keys", "down down")[0], 0)
      self.assertTrue(png.read_bytes().startswith(b"\x89PNG"))
      self.assertEqual(run_cli("text-box", "menu", m, MESSAGE, "on")[0], 0)
      self.assertEqual(run_cli("text-box", "set", m, MESSAGE, "palette", "#000000,#ffffff")[0], 0)
      self.assertEqual(run_cli("text-box", "set", m, MESSAGE, "window.arrow_image",
                               json.dumps({"image": "arrow.png", "steps": [0]}))[0], 0)
      self.assertEqual(run_cli("text-box", "set", m, COLUMN, "frame.image", "-")[0], 0)
      saved = Document.open(self.assets)
      self.assertEqual(text_boxes.find(saved, MESSAGE)["palette"], ["#000000", "#ffffff"])
      self.assertEqual(text_boxes.arrow_image(text_boxes.find(saved, MESSAGE)), {"image": "arrow.png", "steps": [0]})
      self.assertIsNone(text_boxes.frame_image(text_boxes.find(saved, COLUMN)))
      self.assertTrue(menu_styles.has_menu(text_boxes.find(saved, MESSAGE)))


class GameBlockTests(BattleTestCase):
   """!A test save's Game section (engine N3)."""

   def test_set_check_export_and_read_back(self) -> None:
      """!The block is set, checked, written into the image's Game section (the engine's game_payload()) next to the
      other sections, read back from a save file, poked and cleared; refusals.
      @return None
      """
      self.assertTrue(game_block.available())
      save = inventory.new_testsave(self.project, "game")
      plain = inventory.image_of(save, self.project)
      with save.edit("t"):
         game_block.set_game(save, GAME_VERSION, GAME_SIZE, GAME_BYTES)
      self.assertEqual(save.data["game"], {"version": GAME_VERSION, "size": GAME_SIZE, "bytes": "0102030005"})
      self.assertEqual(inventory.check(save, self.project.battle), [])
      data = inventory.image_of(save, self.project)
      sl = engine.tool("save_layout")
      _seq, parts = game_block.sections(data)
      block = GAME_BYTES + bytes(GAME_SIZE - len(GAME_BYTES))
      self.assertEqual(parts["game"], sl.game_payload(block, GAME_VERSION))
      self.assertEqual({k: v for k, v in parts.items() if k != "game"}, game_block.sections(plain)[1])
      self.assertEqual(data[:4], sl.MAGIC.to_bytes(4, "little"))
      # a file of two copies: the newer one's block is read
      older = game_block.with_game(plain, save)
      newer_save = inventory.new_testsave(self.project, "newer")
      with newer_save.edit("t"):
         game_block.set_game(newer_save, GAME_VERSION, GAME_SIZE, b"\x09")
      found = game_block.sections(inventory.image_of(newer_save, self.project))
      newer = sl.assemble(found[1], found[0] + 1)
      path = self.dir / "two.sav"
      path.write_bytes(older + bytes(len(older) % game_block.COPY_ALIGN or 0) + newer)
      other = inventory.new_testsave(self.project, "other")
      with other.edit("t"):
         self.assertEqual(game_block.from_image(other, path), GAME_SIZE)
      self.assertEqual(game_block.block_of(other)[:1], b"\x09")
      with other.edit("t"):
         game_block.set_bytes(other, GAME_SIZE - 1, b"\xff")
      self.assertEqual(game_block.block_of(other)[-1:], b"\xff")
      for bad in (lambda: game_block.set_game(other, game_block.MAX_VERSION + 1, GAME_SIZE),
                  lambda: game_block.set_game(other, 1, 0),
                  lambda: game_block.set_game(other, 1, 2, b"abc"),
                  lambda: game_block.set_bytes(other, GAME_SIZE, b"\x01"),
                  lambda: game_block.from_image(other, self.dir / "battle.json")):
         with self.assertRaises(DocumentError):
            with other.edit("t"):
               bad()
      other.data["game"]["bytes"] = "zz"
      self.assertTrue(any(p.startswith("game:") for p in inventory.check(other, self.project.battle)))
      with save.edit("t"):
         game_block.clear_game(save)
      self.assertEqual(inventory.image_of(save, self.project), plain)

   def test_commands(self) -> None:
      """!`testsave game NAME set | poke | show | from-image | clear`, and `testsave show` names the block.
      @return None
      """
      b = ["battle", str(self.dir / "battle.json"), "testsave"]
      self.assertEqual(run_cli(*b, "new", "g")[0], 0)
      code, out = run_cli(*b, "game", "g", "set", str(GAME_VERSION), str(GAME_SIZE), "--hex", "0a0b")
      self.assertEqual(code, 0)
      self.assertIn(f"game block: version {GAME_VERSION}, {GAME_SIZE} bytes", out)
      self.assertEqual(run_cli(*b, "game", "g", "poke", "2", "0c")[0], 0)
      code, out = run_cli(*b, "game", "g", "show")
      self.assertIn("0a 0b 0c", out)
      image = self.dir / "g.sav"
      self.assertEqual(run_cli(*b, "export", "g", str(image))[0], 0)
      self.assertEqual(run_cli(*b, "game", "g", "clear")[0], 0)
      self.assertIn("(no game block)", run_cli(*b, "game", "g", "show")[1])
      self.assertEqual(run_cli(*b, "game", "g", "from-image", str(image))[0], 0)
      self.assertIn("0a 0b 0c", run_cli(*b, "game", "g", "show")[1])
      self.assertNotEqual(run_cli(*b, "game", "g", "set", "1", "1", "--hex", "xyz")[0], 0)


class HelpAndViewTests(unittest.TestCase):
   """!The route steps' help and the read-only JSON view."""

   def test_route_step_help(self) -> None:
      """!in_place and speed say what engine N2 made them do; the help shows only inside a route or movement.
      @return None
      """
      helps = script_words.route_step_help()
      self.assertIn("walk animation", helps["in_place"])
      self.assertIn("walker", helps["speed"])
      self.assertTrue(helps["speed"].startswith("speed n"))   # the route compiler's line first
      self.assertEqual(script_words.word_help("movement m { up; ", "speed"), helps["speed"])
      self.assertIsNone(script_words.word_help("script s { fade to_black ", "speed"))

   def test_json_view(self) -> None:
      """!An importer file opens read-only (no editor owns its schema), long lists come in chunks; an asset
      manifest's schema is the studio's; a file that is no JSON is refused.
      @return None
      """
      root = Path(tempfile.mkdtemp(prefix="capsule_s5_json_"))
      try:
         n = json_view.CHUNK * 2 + 1
         data = {"schema": "capsule_import.menus/1", "multichoice": [{"id": i} for i in range(n)], "max_width": 28}
         path = root / "menus.json"
         path.write_text(json.dumps(data), encoding="utf-8")
         f = json_view.open_file(path)
         self.assertEqual((f.schema, f.editable()), ("capsule_import.menus/1", False))
         self.assertIn("read-only", f.banner())
         top = dict(json_view.children(f.data))
         chunks = json_view.children(top["multichoice"])
         self.assertEqual(len(chunks), 3)
         self.assertEqual(json_view.children(chunks[-1][1]), [(f"[{n - 1}]", {"id": n - 1})])
         self.assertEqual(json_view.summary(top["multichoice"]), f"[{n} items]")
         assets = root / "assets.json"
         assets.write_text(json.dumps({"schema": "capsule.assets/1", "id": "x", "assets": []}), encoding="utf-8")
         self.assertTrue(json_view.open_file(assets).editable())
         bad = root / "bad.json"
         bad.write_text("{", encoding="utf-8")
         with self.assertRaises(DocumentError):
            json_view.open_file(bad)
      finally:
         shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
   unittest.main()
