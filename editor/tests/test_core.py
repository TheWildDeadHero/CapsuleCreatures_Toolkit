#!/usr/bin/env python3
"""!Tests for capsule_studio.core and the command line (no Qt needed).

Run from editor/: python3 -m unittest discover -s tests
Needs an engine checkout (see capsule_studio.core.engine).
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
from capsule_studio.core import engine, imaging, manifest_io, preview, sprites, texts  # noqa: E402
from capsule_studio.core.document import Document, DocumentError  # noqa: E402


def solid(w: int, h: int, rgba: tuple[int, int, int, int]) -> tuple[int, int, bytearray]:
   """!A one-color image.
   @param w     width
   @param h     height
   @param rgba  (r, g, b, a)
   @return (w, h, RGBA)
   """
   return w, h, bytearray(bytes(rgba) * (w * h))


## Opaque red.
RED = (255, 0, 0, 255)
## Opaque blue.
BLUE = (0, 0, 255, 255)


class TempDir(unittest.TestCase):
   """!Base: a fresh temporary directory per test.

   @var dir
   The directory (a Path).
   """

   def setUp(self) -> None:
      """!Creates the directory.
      @return None
      """
      self.dir = Path(tempfile.mkdtemp(prefix="capsule_studio_"))

   def tearDown(self) -> None:
      """!Removes it.
      @return None
      """
      shutil.rmtree(self.dir, ignore_errors=True)


class DocumentTests(TempDir):
   """!Undo, unsaved images, keys, validation."""

   def test_undo_redo_and_failed_edit(self) -> None:
      """!edit() blocks undo as one step; a raising block leaves no trace.
      @return None
      """
      d = Document()
      with d.edit("Add"):
         texts.set_text(d, "text:A", "one")
         texts.set_text(d, "text:B", "two")
      self.assertEqual(d.undo_label(), "Add")
      d.undo()
      self.assertEqual(d.assets(), [])
      d.redo()
      self.assertEqual(len(d.assets()), 2)
      with self.assertRaises(DocumentError):
         with d.edit("Clash"):
            texts.set_text(d, "text:C", "x")
            d.add_asset({"key": "text:a", "kind": "text", "text": "same key after canonicalising"})
      self.assertIsNone(d.find("text:C"))
      self.assertEqual(d.undo_label(), "Add")

   def test_images_written_on_save_only_if_used(self) -> None:
      """!Undone imports leave no files; kept ones are written as PNG.
      @return None
      """
      d = Document(path=self.dir / "a.json")
      with d.edit("New"):
         sprites.new_sprite(d, "sprite:S", 8, 8)
      with d.edit("Import"):
         sprites.add_images(d, "sprite:S", [solid(8, 8, RED)])
      with d.edit("Import"):
         sprites.add_images(d, "sprite:S", [solid(8, 8, BLUE)])
      d.undo()
      d.save()
      files = sorted(p.name for p in (self.dir / "frames" / "s").iterdir())
      self.assertEqual(files, ["s_0.png"])
      again = Document.open(self.dir / "a.json")
      self.assertEqual(again.image("frames/s/s_0.png")[2][:4], bytes(RED))
      problems, reports = again.validate()
      self.assertEqual(problems, [])
      self.assertTrue(reports["sprite:S"].ok)

   def test_rename_updates_lists(self) -> None:
      """!Renaming an asset renames list items naming it.
      @return None
      """
      d = Document()
      with d.edit("x"):
         texts.set_text(d, "text:A", "a")
         d.add_asset({"key": "list:L", "kind": "list", "items": ["text:A"]})
         d.rename_asset("text:A", "text:B")
      self.assertEqual(d.get("list:L")["items"], ["text:B"])

   def test_compact_json(self) -> None:
      """!Short values stay on one line; the file ends with a newline.
      @return None
      """
      out = manifest_io.dumps({"assets": [{"key": "text:A", "kind": "text", "text": "a"}] * 3})
      self.assertIn('{"key": "text:A", "kind": "text", "text": "a"}', out)
      self.assertEqual(json.loads(out)["assets"][0]["key"], "text:A")


class SpriteTests(unittest.TestCase):
   """!Frames, steps, durations, timing."""

   def sprite(self, n: int = 3) -> Document:
      """!A document with an 8x8 sprite of @p n distinct frames.
      @param n  frames
      @return Document
      """
      d = Document()
      with d.edit("s"):
         sprites.new_sprite(d, "sprite:S", 8, 8)
         sprites.add_images(d, "sprite:S", [solid(8, 8, (i * 40, 0, 0, 255)) for i in range(n)], duration=4)
      return d

   def test_period_when_uniform_durations_otherwise(self) -> None:
      """!Equal durations store as period; differing ones as durations.
      @return None
      """
      d = self.sprite()
      anim = d.get("sprite:S")["animations"][0]
      self.assertEqual(anim, {"frames": [0, 1, 2], "period": 4})
      with d.edit("dur"):
         sprites.set_durations(d, "sprite:S", [1], 9)
      self.assertEqual(d.get("sprite:S")["animations"][0], {"frames": [0, 1, 2], "durations": [4, 9, 4]})

   def test_duplicate_move_remove_gc(self) -> None:
      """!Duplicated steps share a frame; removing the last user of a frame drops it.
      @return None
      """
      d = self.sprite()
      with d.edit("e"):
         self.assertEqual(sprites.duplicate_steps(d, "sprite:S", [0]), [1])
         self.assertEqual(sprites.move_steps(d, "sprite:S", [3], -3), [0])
      self.assertEqual([f for f, _ in sprites.steps(d.get("sprite:S"))], [2, 0, 0, 1])
      with d.edit("r"):
         sprites.remove_steps(d, "sprite:S", [0, 3])   # frames 2 and 1 unused now
      a = d.get("sprite:S")
      self.assertEqual(len(a["frames"]), 1)
      self.assertEqual(a["animations"][0]["frames"], [0, 0])

   def test_timeline_matches_engine(self) -> None:
      """!Same timing as asset_tests.cpp checks on the GBA path: 2 then 5 frames, looping.
      @return None
      """
      a = {"frames": [{}, {}], "animations": [{"frames": [0, 1], "durations": [2, 5]}]}
      self.assertEqual(sprites.timeline(a, 0, 2)[:9], [0, 0, 1, 1, 1, 1, 1, 0, 0])
      a["animations"][0]["loop"] = False
      self.assertEqual(len(sprites.timeline(a, 0, 5)), 7)

   def test_budget_and_compiled_pixels(self) -> None:
      """!Tile budget from the engine header; decoded frames match the import.
      @return None
      """
      d = self.sprite(2)
      used, limit = sprites.tile_budget(d.get("sprite:S"))
      self.assertEqual((used, limit), (2, 64))
      r = d.compile_asset(d.get("sprite:S"))
      self.assertTrue(r.ok, r.error)
      _, _, idx = sprites.frame_pixels(r.compiled, 1)
      self.assertEqual(sprites.palette_rgb(r.compiled)[idx[0] - 1], (5, 0, 0))   # 40 >> 3

   def test_too_many_tiles_reported(self) -> None:
      """!Five 32x32 frames exceed a slot's 64 tiles; the engine's message comes through.
      @return None
      """
      d = Document()
      with d.edit("s"):
         sprites.new_sprite(d, "sprite:BIG", 32, 32)
         sprites.add_images(d, "sprite:BIG", [solid(32, 32, RED)] * 5)
      self.assertEqual(sprites.tile_budget(d.get("sprite:BIG"))[0], 80)
      r = d.compile_asset(d.get("sprite:BIG"))
      self.assertFalse(r.ok)
      self.assertIn("80 tiles; a sprite slot holds 64", r.error)

   def test_sizes(self) -> None:
      """!Smallest OBJ size that fits; durations in milliseconds.
      @return None
      """
      self.assertEqual(sprites.smallest_size(20, 20), (32, 32))
      self.assertEqual(sprites.smallest_size(30, 10), (32, 16))
      self.assertEqual(sprites.frames_to_ms(60), 1005)


class ImagingTests(unittest.TestCase):
   """!Fitting and transparency."""

   def test_center_crop_and_pad(self) -> None:
      """!Centring pads with transparency and crops evenly.
      @return None
      """
      w, h, px = imaging.center(solid(2, 2, RED), 4, 4)
      self.assertEqual(px[(1 * 4 + 1) * 4:(1 * 4 + 1) * 4 + 4], bytes(RED))
      self.assertEqual(px[3], 0)
      self.assertEqual(imaging.center(solid(6, 6, RED), 4, 4)[:2], (4, 4))

   def test_scale_keeps_aspect(self) -> None:
      """!A 16x8 image fitted into 8x8 becomes 8x4, centred.
      @return None
      """
      w, h, px = imaging.fit(solid(16, 8, RED), 8, 8, "smooth")
      rows = [any(px[(y * 8 + x) * 4 + 3] for x in range(8)) for y in range(8)]
      self.assertEqual(rows, [False, False, True, True, True, True, False, False])

   def test_corner_key(self) -> None:
      """!The corner color becomes transparent.
      @return None
      """
      img = solid(2, 1, (255, 0, 255, 255))
      img[2][4:8] = bytes(RED)
      _, _, px = imaging.prepare(img, 2, 1, transparency="corner")
      self.assertEqual((px[3], px[7]), (0, 255))


class TextTests(unittest.TestCase):
   """!Texts, credits, previews."""

   def test_credits_round_trip_and_position(self) -> None:
      """!Pages renumber from 1 and stay where the old credits were.
      @return None
      """
      d = Document()
      with d.edit("x"):
         texts.set_text(d, "text:BEFORE", "b")
         texts.set_credits_pages(d, [("A", "1"), ("B", "2\n3")])
         texts.set_text(d, "text:AFTER", "a")
         texts.set_credits_pages(d, [("Z", "9")])
      keys = [a["key"] for a in d.assets()]
      self.assertEqual(keys, ["text:BEFORE", "text:CREDITS HEAD 01", "text:CREDITS NAMES 01", "text:AFTER"])
      self.assertEqual(texts.credits_pages(d), [("Z", "9")])
      src = "HEAD\nName One\nName Two\n\n\nSECOND\n"
      pages = texts.parse_credits_text(src)
      self.assertEqual(pages, [("HEAD", "Name One\nName Two"), ("SECOND", "")])
      self.assertEqual(texts.parse_credits_text(texts.format_credits_text(pages)), pages)

   def test_check_text(self) -> None:
      """!Code page errors and long-line warnings.
      @return None
      """
      self.assertTrue(texts.check_text("café")[0].startswith("error:"))
      self.assertEqual(texts.check_text("x" * 31), ["line 1 is 31 characters; 30 fit"])

   def test_preview_layout(self) -> None:
      """!Credits headings are centred on column 15 in style 1 ink.
      @return None
      """
      s = preview.credits_page("AB", "")
      ink = preview.expand(preview.STYLE_INK[1])
      lit = [x for x in range(240) if s.pixel(x, 14 * 8 + 1) == ink]
      self.assertTrue(lit and 14 * 8 <= min(lit) and max(lit) < 16 * 8)


class CliTests(TempDir):
   """!The command line end to end."""

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command, capturing output.
      @param argv  arguments
      @return (status, stdout)
      """
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()

   def test_import_durations_validate_sheet(self) -> None:
      """!import --create auto, duration, validate and sheet work on files.
      @return None
      """
      bm = engine.bitmap()
      for i in range(2):
         bm.write_png(self.dir / f"f{i}.png", *solid(12, 12, (0, 255 * i, 0, 255)))
      m = self.dir / "assets.json"
      status, _ = self.run_cli("sprite", "import", m, "sprite:X", self.dir / "f0.png", self.dir / "f1.png",
                               "--create", "auto")
      self.assertEqual(status, 0)
      self.assertEqual(self.run_cli("sprite", "duration", m, "sprite:X", 3, "--steps", "1")[0], 0)
      a = manifest_io.load(m)["assets"][0]
      self.assertEqual((a["width"], a["animations"][0]["durations"]), (16, [8, 3]))
      status, out = self.run_cli("validate", m)
      self.assertEqual(status, 0, out)
      self.assertEqual(self.run_cli("sprite", "sheet", m, "sprite:X", self.dir / "s.png")[0], 0)
      self.assertEqual(bm.read_png(self.dir / "s.png")[:2], (32, 16))

   def test_credits_import_rejects_bad_characters(self) -> None:
      """!Credits with characters outside the code page are not saved.
      @return None
      """
      src = self.dir / "c.txt"
      src.write_text("HEAD\nJosé\n", encoding="utf-8")
      status, _ = self.run_cli("credits", "import", self.dir / "a.json", src)
      self.assertEqual(status, 1)
      self.assertFalse((self.dir / "a.json").exists())


if __name__ == "__main__":
   unittest.main()
