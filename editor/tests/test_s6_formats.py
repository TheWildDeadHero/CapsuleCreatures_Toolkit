#!/usr/bin/env python3
"""!S6 (engine UC / UM, D-33) without Qt: the screen graphics kinds (core.screen_graphics: tiles, tilemaps,
palettes; compiled with the engine, previewed, painted, imported from and exported to indexed PNGs), screen plans
(core.screen_plans: layers, palettes, windows, sheets, sprites, steps and transitions; check() finds video memory
clashes, mode and colour-mode mistakes and sprite limits; render() simulates video memory; fade_frames() steps the
engine's fade; export_cpp() writes a header that compiles), the GBA memory settings and report (core.gba_memory),
the build settings' screen arena, the commands, and the test layout (every module finds its sibling helpers alone).

Uses a copy of the engine's screen sandbox (apps/sandbox_screen: simple shapes).
"""
from __future__ import annotations

import ast
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine, gba_memory, indexed_png, project, screen_graphics as sg  # noqa: E402
from capsule_studio.core import screen_plans as sp  # noqa: E402
from capsule_studio.core.document import Document  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402

## The sandbox's pattern tiles, tilemap and palettes, its sprite sheets.
PATTERN_TILES, PATTERN_MAP = "tiles:SANDBOX_SCREEN_PATTERN", "tilemap:SANDBOX_SCREEN_PATTERN"
BG_PALETTE, OBJ_PALETTE = "palette:SANDBOX_SCREEN_BG", "palette:SANDBOX_SCREEN_OBJ"
ICONS, CURSOR = "tiles:SANDBOX_SCREEN_ICONS", "tiles:SANDBOX_SCREEN_CURSOR"
## A real report line (UM's full ROM, 2026-10-25) and the link's EWRAM failure.
REPORT = ("GBA memory (capsule_game): EWRAM 201300 of 262144 B (60844 B free); IWRAM code + data 19236 of 32768 B, "
          "stack 13276 B (reserve 2048 B)")
OVER = ("GBA memory (capsule_game): EWRAM 365248 of 262144 B (-103104 B free); IWRAM code + data 22200 of 32768 B, "
        "stack 10312 B (reserve 2048 B) - DOES NOT FIT (CAPSULE_GBA_MEMORY_CHECKS is OFF)")
FAILURE = ("/opt/devkitARM/bin/ld: GBA memory: EWRAM (.ewram + .sbss) is over 256 KB; move screen state into the "
           "screen arena (capsule/screen/arena.h) or shrink it")


def list_plan(manifest: Document) -> Document:
   """!The sandbox's list screen as a plan: a window layer, a panel layer, the pattern layer, the BG and OBJ
   palettes, a title window, two sheets and a reserve, six icons and a cursor.
   @param manifest  the sandbox's manifest
   @return the plan (saved)
   """
   p = sp.create(manifest, "list")
   with p.edit("Plan"):
      sp.add_item(p, "layers", bg=0, char_block=2, screen_block=31, priority=0)
      sp.add_item(p, "layers", bg=1, char_block=0, screen_block=30, priority=1, shown=False)
      sp.add_item(p, "layers", bg=3, char_block=0, screen_block=29, priority=3, tiles=PATTERN_TILES,
                  tilemap=PATTERN_MAP)
      sp.add_item(p, "palettes", palette=BG_PALETTE, banks=4)
      sp.add_item(p, "palettes", palette=OBJ_PALETTE, target="obj", tag=1)
      sp.add_item(p, "windows", name="title", bg=0, x=1, y=1, w=20, h=2, first_tile=1, palette=3)
      sp.add_item(p, "sheets", tag=1, tiles=ICONS)
      sp.add_item(p, "sheets", tag=2, tiles=CURSOR)
      sp.add_item(p, "sheets", tag=3, reserve=16)
      for i in range(6):
         sp.add_item(p, "sprites", name=f"icon_{i}", sheet=1, palette_tag=1, x=64 + (i % 3) * 56,
                     y=64 + (i // 3) * 48, priority=1, subpriority=2)
      sp.add_item(p, "sprites", name="cursor", sheet=2, palette_tag=1, x=44, y=64, priority=1)
   p.save()
   return p


def pixel(img: tuple[int, int, bytearray], x: int, y: int) -> tuple[int, ...]:
   """!One pixel of an RGBA image.
   @param img  (w, h, RGBA)
   @param x    column
   @param y    row
   @return (r, g, b, a)
   """
   w, _h, px = img
   return tuple(px[(y * w + x) * 4:(y * w + x) * 4 + 4])


class S6Case(unittest.TestCase):
   """!Base: a copy of the screen sandbox per test."""

   def setUp(self) -> None:
      """!Copies the sandbox.
      @return None
      """
      ## Temporary root.
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_s6_")), ["sandbox_screen"])
      ## The copy's data folder.
      self.data = self.root / "sandbox_screen" / "data"
      ## The manifest.
      self.doc = Document.open(self.data / "assets.json")

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root.parent, ignore_errors=True)

   def run_cli(self, *args: object) -> tuple[int, str]:
      """!Runs capsule-studio.
      @param args  arguments
      @return (status, output)
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         status = cli([str(a) for a in args])
      return status, out.getvalue() + err.getvalue()


class GraphicsTests(S6Case):
   """!core.screen_graphics."""

   def test_sandbox_assets(self) -> None:
      """!The sandbox's screen graphics compile and are listed; previews have their sizes.
      @return None
      """
      self.assertTrue(sg.available())
      self.assertEqual(len(sg.graphics(self.doc)), 7)
      self.assertEqual(sg.keys(self.doc, "palette"), [BG_PALETTE, OBJ_PALETTE])
      rec = sg.compiled(self.doc, PATTERN_TILES).compiled
      self.assertEqual((rec["count"], rec["bpp"]), (5, 4))
      self.assertEqual(sg.preview(self.doc, PATTERN_MAP, BG_PALETTE, 0, PATTERN_TILES)[:2], (256, 256))
      self.assertEqual(sg.preview(self.doc, BG_PALETTE)[:2], (16 * sg.SWATCH, 4 * sg.SWATCH))
      # a sheet cut by blocks shows as its canvas was drawn
      self.assertEqual(sg.preview(self.doc, "tiles:SANDBOX_SCREEN_PICTURE", OBJ_PALETTE)[:2], (128, 64))
      self.assertIn("4 banks", "\n".join(sg.lines(self.doc)))

   def test_new_and_edit(self) -> None:
      """!New assets compile; fields, colours, banks, painting and rows are checked by the compiler.
      @return None
      """
      with self.doc.edit("New"):
         sg.new_tiles(self.doc, "BOX", 16, 8)
         sg.new_tilemap(self.doc, "BOX", 4)
         sg.new_palette(self.doc, "BOX", 2)
      self.assertEqual(sg.compiled(self.doc, "tiles:BOX").compiled["count"], 2)
      with self.doc.edit("Shapes"):
         sg.set_shapes(self.doc, "tiles:BOX", [{"shape": "rect", "x": 8, "y": 0, "w": 8, "h": 8, "color": 3}])
      self.assertEqual(sg.decode_tiles(sg.compiled(self.doc, "tiles:BOX").compiled)[1][0][0], 3)
      with self.assertRaises(sg.ScreenGraphicsError), self.doc.edit("Bad"):
         sg.set_fields(self.doc, "tiles:BOX", width=12)   # not whole tiles: the compiler refuses
      with self.doc.edit("Colour"):
         sg.set_color(self.doc, "palette:BOX", 17, "#ff8000")
         sg.set_banks(self.doc, "palette:BOX", 3)
      colors = sg.compiled(self.doc, "palette:BOX").compiled["colors"]
      self.assertEqual((len(colors), sg.hex_of(colors[17])), (48, "#f88000"))
      self.assertEqual(sg.to_bgr555("#ff8000"), colors[17])
      e = sg.parse_entry("t2 p1 hv")
      self.assertEqual(sg.entry_parts(e), (2, 1, True, True))
      self.assertEqual(sg.entry_text(e), "t2 p1 hv")
      with self.doc.edit("Paint"):
         sg.paint(self.doc, "tilemap:BOX", 1, 1, sg.make_entry(1, 1), 3, 1, 1)
         sg.set_rows(self.doc, "tilemap:BOX", 2)
      cells = sg.compiled(self.doc, "tilemap:BOX").compiled["cells"]
      self.assertEqual(cells[33:36], [0x1001, 0x1002, 0x1003])   # a run of tiles, bank 1
      self.assertEqual(len(cells), 64)
      with self.assertRaises(sg.ScreenGraphicsError), self.doc.edit("Off the map"):
         sg.paint(self.doc, "tilemap:BOX", 31, 1, 0, 2, 1)

   def test_import_export(self) -> None:
      """!An indexed PNG round-trips: identical and flipped tiles are shared, a bank per tile, the palette whole
      banks; a data tilemap becomes cells.
      @return None
      """
      # 32 x 8: tile 0 blank, tile 1 a corner in bank 1, tile 2 that corner mirrored, tile 3 the blank again
      w, h = 32, 8
      px = bytearray(w * h)
      for y in range(4):
         for x in range(4):
            px[y * w + 8 + x] = 16 + 2
            px[y * w + 16 + 7 - x] = 16 + 2
      plte = bytes(range(32 * 3))
      png = self.data / "corner.png"
      png.write_bytes(indexed_png.encode(w, h, px, plte))
      with self.doc.edit("Import"):
         added = sg.import_png(self.doc, "CORNER", png)
      self.assertEqual(added, ["tiles:CORNER", "tilemap:CORNER", "palette:CORNER"])
      self.assertTrue((self.data / "screen" / "corner.4bpp").is_file())
      self.assertEqual(sg.compiled(self.doc, "tiles:CORNER").compiled["count"], 2)
      cells = sg.compiled(self.doc, "tilemap:CORNER").compiled["cells"]
      self.assertEqual(cells[:4], [0, 0x1001, 0x1401, 0])   # the mirrored corner shares tile 1, h-flipped
      self.assertEqual(len(cells), 32)                        # a row of a 32-cell layer map
      self.assertEqual(len(sg.compiled(self.doc, "palette:CORNER").compiled["colors"]), 32)
      out = self.data / "back.png"
      sg.export_png(self.doc, "tiles:CORNER", out, "palette:CORNER", 1)
      bw, bh, back = indexed_png.read(out)
      self.assertEqual((bw, bh, back[8 + 0], back[0]), (sg.DEFAULT_SHEET_COLUMNS * 8, 8, 18, 16))
      with self.assertRaises(sg.ScreenGraphicsError):
         sg.cut_image(8, 8, [1, 17] + [0] * 62)   # one tile, two banks
      (self.data / "raw.bin").write_bytes(bytes([1, 0, 2, 0x10]))
      with self.doc.edit("Data map"):
         self.doc.add_asset({"key": "tilemap:RAW", "kind": "tilemap", "data": "raw.bin"})
         sg.to_cells(self.doc, "tilemap:RAW")
      self.assertEqual(self.doc.get("tilemap:RAW")["cells"], [1, 0x1002])

   def test_block_order(self) -> None:
      """!An image wider than one screen block is stored as two blocks side by side.
      @return None
      """
      entries = list(range(40 * 2))
      out = sg.block_order(entries, 40, 2)
      self.assertEqual(len(out), 2 * 32 * 32)
      self.assertEqual(out[0], 0)
      self.assertEqual(out[32 * 32], 32)        # the right block starts with column 32 of row 0
      self.assertEqual(out[32], 40)             # row 1 of the left block
      self.assertEqual(out[32 * 32 + 8], 0)     # past the image: blank


class PlanTests(S6Case):
   """!core.screen_plans."""

   def test_list_plan(self) -> None:
      """!The sandbox's list screen as a plan: no problems, its file found beside the manifest, video memory as
      expected, the picture drawn in priority order.
      @return None
      """
      p = list_plan(self.doc)
      self.assertEqual(sp.plan_files(self.doc), [p.path])
      self.assertEqual(sp.check(p.data, self.doc), [])
      lines = sp.vram_lines(p.data, self.doc)
      self.assertTrue(lines[0].startswith("0x0000-0x009F"), lines)
      self.assertIn("OBJ tiles 20-35  sheet tag 3 (reserved)", lines)
      img = sp.render(p.data, self.doc)
      self.assertEqual(img[:2], (240, 160))
      inside = pixel(img, 8 * 2, 8 * 2)          # in the title window: bank 3's fill index 1
      bank3 = sg.compiled(self.doc, BG_PALETTE).compiled["colors"][3 * 16 + 1]
      self.assertEqual(inside[:3], sg.bgr_to_rgb(bank3))
      cursor = pixel(img, 44, 64)                  # the cursor's centre: an OBJ colour over the pattern
      obj = sg.compiled(self.doc, OBJ_PALETTE).compiled["colors"]
      self.assertIn(cursor[:3], [sg.bgr_to_rgb(c) for c in obj])
      guides = sp.render(p.data, self.doc, guides=True)
      self.assertEqual(pixel(guides, 8, 8), sp.GUIDE_COLOR)   # the window's outline corner

   def test_problems(self) -> None:
      """!A map written over tiles, a layer the mode has not, a colour mode mismatch, a sheet that does not fit, a
      sprite naming no sheet, duplicate names.
      @return None
      """
      p = list_plan(self.doc)
      with p.edit("Clash"):
         sp.set_item(p, "layers", 2, screen_block=0)   # the pattern's map over its own tiles in char block 0
      msgs = [str(x) for x in sp.check(p.data, self.doc)]
      self.assertTrue(any("is written over" in m for m in msgs), msgs)
      with p.edit("Mode"):
         sp.set_item(p, "layers", 2, screen_block=29)
         sp.set_mode(p, 1)                           # mode 1 has no BG3; BG2 would be affine
      msgs = [str(x) for x in sp.check(p.data, self.doc)]
      self.assertTrue(any("mode 1 has no BG3" in m for m in msgs), msgs)
      with p.edit("Colours"):
         sp.set_mode(p, 0)
         sp.set_item(p, "layers", 2, bpp8=True)
         sp.add_item(p, "sheets", tag=4, reserve=1000)
         sp.add_item(p, "sprites", name="cursor", sheet=9, palette_tag=7)
      msgs = [str(x) for x in sp.check(p.data, self.doc)]
      for want in ("takes 8bpp tiles", "do not fit in sprite memory", "no sheet has tag 9", "no OBJ palette has tag 7",
                   "the name 'cursor'"):
         self.assertTrue(any(want in m for m in msgs), (want, msgs))
      self.assertEqual(sp.check(p.data, self.doc)[0].severity, "error")
      with self.assertRaises(sp.PlanError):
         sp.export_cpp(p.data)   # errors refuse the export

   def test_fields(self) -> None:
      """!Fields are checked and converted from command-line text; later templates replace the plan's layer.
      @return None
      """
      p = list_plan(self.doc)
      with self.assertRaises(sp.PlanError), p.edit("Bad"):
         sp.set_item(p, "layers", 0, char_block=4)
      with self.assertRaises(sp.PlanError), p.edit("Bad"):
         sp.set_item(p, "sprites", 0, shape="round")
      with self.assertRaises(sp.PlanError), p.edit("Bad"):
         sp.set_item(p, "layers", 0, tiles="palette:X")
      with p.edit("Later"):
         sp.add_item(p, "layers", bg=3, char_block=1, screen_block=28, priority=3, later="on")
      self.assertEqual(sp.active_layers(p.data)[3]["screen_block"], 29)
      self.assertEqual(sp.active_layers(p.data, later=True)[3]["screen_block"], 28)
      self.assertIn("kLaterBg3", sp.export_cpp(p.data))
      self.assertEqual(sp.cell_index({"bg": 0, "screen_size": 1}, 0, 33, 1), 32 * 32 + 32 + 1)

   def test_fades(self) -> None:
      """!The engine's fade call by call: 0 to 16 in 23 calls with kHandheldFade (BG then OBJ each step, four
      finishing calls); a negative delay steps faster; blend_floor rounds down where blend() truncates.
      @return None
      """
      lists = sp.engine_lists()   # read from the engine's headers, never copied
      self.assertEqual(list(lists["shapes"]), ["square", "wide", "tall"])
      self.assertEqual(lists["steps"]["build_oam"], "BuildOam")
      self.assertEqual(sp.default_steps(), ["tasks", "animate", "build_oam", "copy_tilemaps", "fade"])
      self.assertEqual(sp.obj_size("wide", 2), (32, 16))
      style = sp.fade_style({})
      self.assertEqual(style, sp.handheld())
      self.assertEqual((style["step"], style["finish_calls"], style["rounding"]), (2, 4, "floor"))
      frames = sp.fade_frames(sp.fade_of("to_black"), style)
      self.assertEqual(len(frames), 23)
      self.assertEqual(frames[:4], [(0, 0), (0, 0), (2, 0), (2, 2)])
      self.assertEqual(frames[-1], (16, 16))
      fast = sp.fade_frames(sp.fade_of({"from": 16, "to": 0, "delay": -2}), style)
      self.assertEqual(fast[2], (12, 16))   # step 2 - (-2) = 4 a step
      slow = sp.fade_frames(sp.fade_of({"delay": 1}), dict(style, alternate=False))
      self.assertEqual(slow[:3], [(0, 0), (0, 0), (2, 2)])
      self.assertEqual(sp.fade_frames(sp.fade_of("none"), style), [])
      white = sg.to_bgr555("#f8f8f8")
      self.assertEqual(sp.blend(white, 0, 1, "floor") & sg.CHANNEL_MASK, 29)      # 31 - ceil(31 / 16)
      self.assertEqual(sp.blend(white, 0, 1, "truncate") & sg.CHANNEL_MASK, 30)   # 31 - trunc(31 / 16)
      p = list_plan(self.doc)
      black = sp.render(p.data, self.doc, fade=sp.fade_at(p.data, "open", 22))
      self.assertEqual(pixel(black, 120, 150)[:3], (0, 0, 0))
      with p.edit("Custom"):
         sp.set_transition(p, "in", {"mask": "obj", "from": 16, "to": 0, "color": "#f8f8f8"})
         sp.set_fade_style(p, {"rounding": "truncate"})
      self.assertEqual(sp.fade_at(p.data, "in", 0).mask, sp.MASKS["obj"])
      text = sp.export_cpp(p.data)
      self.assertIn("Rounding::Truncate", text)
      self.assertIn(".mask = 0xFFFF0000u", text)
      with self.assertRaises(sp.PlanError), p.edit("Bad"):
         sp.set_transition(p, "out", {"from": 17})

   def test_export_compiles(self) -> None:
      """!The exported header follows the project style and compiles against the engine's headers (C++20).
      @return None
      """
      p = list_plan(self.doc)
      with p.edit("More"):
         sp.add_item(p, "layers", bg=2, char_block=1, screen_block=27, later=True)
         sp.set_transition(p, "out", {"mask": "bg", "delay": 1, "from": 0, "to": 16, "color": "#f8f8f8"})
      header = self.root / "list_screen.h"
      header.write_text(sp.export_cpp(p.data, p.path.name), encoding="utf-8")
      from importlib import import_module
      sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "toolkit"))
      check_style = import_module("check_style")
      self.assertEqual([str(x) for x in check_style.check_cpp(header, header.read_text(encoding="utf-8"))], [])
      cxx = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
      if cxx is None:
         self.skipTest("no C++ compiler")
      main = self.root / "use.cpp"
      main.write_text('#include "list_screen.h"\nstatic_assert(list_screen::kPlan.count == 3);\n'
                      "static_assert(list_screen::kTitleWindow.w == 20);\n"
                      "static_assert(list_screen::kOut.fade.delay == 1);\n"
                      "int main() { return list_screen::kCursorSprite.x == 44 ? 0 : 1; }\n", encoding="utf-8")
      r = subprocess.run([cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
                          f"-I{engine.root() / 'include'}", f"-I{self.root}", str(main)],
                         capture_output=True, text=True, check=False)
      self.assertEqual(r.returncode, 0, r.stderr)


class MemoryTests(unittest.TestCase):
   """!core.gba_memory and the screen arena build setting."""

   def setUp(self) -> None:
      """!A build folder with a cache.
      @return None
      """
      ## Temporary build folder.
      self.build = Path(tempfile.mkdtemp(prefix="capsule_s6_build_"))
      (self.build / gba_memory.CACHE_FILE).write_text(
         "# This is the CMakeCache file.\n"
         "CMAKE_TOOLCHAIN_FILE:FILEPATH=/engine/cmake/toolchains/gba-devkitarm.cmake\n"
         "CAPSULE_GBA_STACK_RESERVE:STRING=2048\n"
         "CAPSULE_GBA_MEMORY_CHECKS:BOOL=ON\n"
         "CAPSULE_SCREEN_ARENA_BYTES:STRING=\n", encoding="utf-8")

   def tearDown(self) -> None:
      """!Removes the folder.
      @return None
      """
      shutil.rmtree(self.build, ignore_errors=True)

   def test_cache(self) -> None:
      """!The settings read and written as cmake-gui would; the arena override is checked by the engine's rule.
      @return None
      """
      s = gba_memory.settings(self.build)
      self.assertEqual((s.checks, s.reserve, s.arena, s.gba), (True, 2048, None, True))
      gba_memory.set_cache(self.build, gba_memory.CHECKS, "OFF")
      gba_memory.set_cache(self.build, gba_memory.RESERVE, "4096")
      gba_memory.set_cache(self.build, gba_memory.ARENA, "49152")
      s = gba_memory.settings(self.build)
      self.assertEqual((s.checks, s.reserve, s.arena), (False, 4096, 49152))
      text = (self.build / gba_memory.CACHE_FILE).read_text(encoding="utf-8")
      self.assertIn("CAPSULE_GBA_MEMORY_CHECKS:BOOL=OFF\n", text)
      self.assertEqual(text.count("CAPSULE_GBA_STACK_RESERVE"), 1)
      for name, bad in ((gba_memory.ARENA, "1001"), (gba_memory.RESERVE, "99999"), (gba_memory.CHECKS, "maybe")):
         with self.subTest(name=name), self.assertRaises(gba_memory.GbaMemoryError):
            gba_memory.set_cache(self.build, name, bad)
      self.assertIn(self.build, gba_memory.build_folders(self.build))

   def test_report(self) -> None:
      """!Report lines and link failures read from a build's output; the same numbers from nm's listing.
      @return None
      """
      reports, failures = gba_memory.parse_log("\n".join(["[42/42] Linking CXX executable", REPORT, OVER,
                                                         FAILURE]))
      self.assertEqual([r.fits for r in reports], [True, False])
      self.assertEqual(reports[0].ewram_free, 60844)
      self.assertEqual(reports[0].line(), REPORT)
      self.assertIn("103104 B over", reports[1].problems()[0])
      self.assertEqual(len(failures), 1)
      self.assertTrue(failures[0].startswith("GBA memory: EWRAM"))
      nm = "02031254 B __sbss_end__\n03004b30 T __iheap_start\n03007f00 A __sp_usr\n080000c0 T main\n"
      r = gba_memory.report_from_symbols(nm, "game", 2048)
      self.assertEqual((r.ewram_used, r.iwram_used, r.stack), (0x31254, 0x4B30, 0x7F00 - 0x4B30))
      self.assertTrue(r.fits)
      with self.assertRaises(gba_memory.GbaMemoryError):
         gba_memory.report_from_symbols("080000c0 T main\n", "host", 2048)
      self.assertIn("19%", gba_memory.arena_share(reports[0], 39000))
      self.assertIn("links no arena", gba_memory.arena_share(gba_memory.Report("x", 100, 1, 0, 1, 0, 0), 1024))
      elf = self.build / "game.elf"
      elf.write_bytes(gba_memory.ELF_MAGIC + bytes(14) + (gba_memory.EM_ARM).to_bytes(2, "little"))
      self.assertEqual(gba_memory.programs(self.build), [elf])

   def test_cli(self) -> None:
      """!gba-memory show / set / report.
      @return None
      """
      out, err = io.StringIO(), io.StringIO()
      with redirect_stdout(out), redirect_stderr(err):
         self.assertEqual(cli(["gba-memory", str(self.build), "set", "reserve", "3072"]), 0)
         self.assertEqual(cli(["gba-memory", str(self.build), "show"]), 0)
         log = self.build / "build.log"
         log.write_text(OVER + "\n", encoding="utf-8")
         self.assertEqual(cli(["gba-memory", str(self.build), "report", "--log", str(log)]), 1)
      self.assertIn("CAPSULE_GBA_STACK_RESERVE: 3072 B", out.getvalue())
      self.assertIn("DOES NOT FIT", out.getvalue())

   def test_arena_setting(self) -> None:
      """!The engine's screen_arena_bytes is a project build setting (a multiple of 4, 1-192 KB).
      @return None
      """
      doc = Document(None, None, project.SCHEMA)
      rows = {r.key: r for r in project.rows(doc)}
      self.assertIn("screen_arena_bytes", rows)
      with self.assertRaises(project.DocumentError):
         project.set_setting(doc, "screen_arena_bytes", 49153)
      project.set_setting(doc, "screen_arena_bytes", 49152)
      self.assertEqual(doc.data["build"]["screen_arena_bytes"], 49152)


class CommandTests(S6Case):
   """!screen-gfx and screen-plan."""

   def test_gfx_commands(self) -> None:
      """!New, paint, colour, render and export from the command line.
      @return None
      """
      m = self.data / "assets.json"
      self.assertEqual(self.run_cli("screen-gfx", m, "new", "tilemap", "MAP", "--size", "32x2")[0], 0)
      status, out = self.run_cli("screen-gfx", m, "paint", "tilemap:MAP", "0", "1", "t4 p2 v", "--size", "2x1")
      self.assertEqual(status, 0, out)
      self.assertEqual(Document.open(m).get("tilemap:MAP")["cells"][32:34], [0x2804, 0x2804])
      self.assertEqual(self.run_cli("screen-gfx", m, "color", OBJ_PALETTE, "1", "#00ff00")[0], 0)
      status, out = self.run_cli("screen-gfx", m, "set", PATTERN_TILES, "width=12")
      self.assertEqual(status, 1, out)   # refused by the compiler, nothing saved
      out_png = self.data / "map.png"
      self.assertEqual(self.run_cli("screen-gfx", m, "render", PATTERN_MAP, out_png, "--tiles", PATTERN_TILES,
                                    "--palette", BG_PALETTE)[0], 0)
      self.assertEqual(engine.bitmap().read_png(out_png)[:2], (256, 256))
      self.assertEqual(self.run_cli("screen-gfx", m, "export", ICONS, self.data / "icons.png")[0], 0)
      status, out = self.run_cli("screen-gfx", m, "import", "ICONS2", self.data / "icons.png", "--no-map")
      self.assertEqual(status, 0, out)
      self.assertIn("tiles:ICONS2: 16 tiles", out)

   def test_plan_commands(self) -> None:
      """!A plan made, filled, checked, rendered and exported from the command line.
      @return None
      """
      m = self.data / "assets.json"
      status, out = self.run_cli("screen-plan", "new", m, "detail")
      self.assertEqual(status, 0, out)
      plan = self.data / "screens" / "detail.screen.json"
      for args in (("layers", "bg=0", "char_block=2", "screen_block=31"),
                   ("layers", "bg=3", "screen_block=29", "priority=3", f"tiles={PATTERN_TILES}",
                    f"tilemap={PATTERN_MAP}"),
                   ("palettes", f"palette={BG_PALETTE}", "banks=4")):
         status, out = self.run_cli("screen-plan", "add", plan, *args)
         self.assertEqual(status, 0, out)
      self.assertEqual(self.run_cli("screen-plan", "check", plan), (0, "no problems\n"))
      self.assertEqual(self.run_cli("screen-plan", "set", plan, "layers", "1", "screen_block=0")[0], 0)
      status, out = self.run_cli("screen-plan", "check", plan)
      self.assertEqual(status, 1)
      self.assertIn("is written over", out)
      self.assertEqual(self.run_cli("screen-plan", "set", plan, "layers", "1", "screen_block=29")[0], 0)
      self.assertEqual(self.run_cli("screen-plan", "transition", plan, "out", "to_white")[0], 0)
      status, out = self.run_cli("screen-plan", "frames", plan, "open")
      self.assertIn("23 calls", out)
      self.assertEqual(self.run_cli("screen-plan", "render", plan, self.data / "detail.png", "--transition", "out",
                                    "--call", "5")[0], 0)
      self.assertEqual(self.run_cli("screen-plan", "export", plan, self.data / "detail_screen.h")[0], 0)
      self.assertIn("namespace detail_screen", (self.data / "detail_screen.h").read_text(encoding="utf-8"))
      status, out = self.run_cli("screen-plan", "list", m)
      self.assertEqual(out.strip(), "screens/detail.screen.json")
      self.assertIn("first_tile", self.run_cli("screen-plan", "fields", "layers")[1])


class LayoutTests(unittest.TestCase):
   """!The test layout (V2 finding)."""

   def test_sibling_helpers(self) -> None:
      """!Every test module that imports a sibling helper module (sample_data, text_fixture, another test module)
      puts its own folder on sys.path, so it runs alone from any folder.
      @return None
      """
      here = Path(__file__).resolve().parent
      siblings = {p.stem for p in here.glob("*.py")}
      missing = []
      for path in sorted(here.glob("test_*.py")):
         tree = ast.parse(path.read_text(encoding="utf-8"))
         imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
            {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
         if imported & siblings and "resolve().parent))" not in path.read_text(encoding="utf-8"):
            missing.append(path.name)
      self.assertEqual(missing, [])


if __name__ == "__main__":
   unittest.main()
