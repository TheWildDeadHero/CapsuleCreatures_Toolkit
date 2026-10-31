#!/usr/bin/env python3
"""!The I2 / I3 world format in the studio's core and command line (no Qt), on a copy of the engine's map test world
(tests/data/maps: the fixed tileset "fixed", the "all" maps fixed_a / fixed_b, the I3 map crowd, behaviors
fence_east and counter_top, vehicle class trek) and small invented additions: a second fixed tileset drawing a tile
the first one places, and an indexed sprite sheet written here.

Covers: "all" dictionaries (resolving, painting, converting, renumbering when the tilesets or their metatile order
change, refusals), fixed tilesets (placement, banks, raw entries, indexed sheets, pictures drawn with the tilesets
maps load together), animations (phase, from_sheet, on_shift), warps (door, arrow, none, dynamic) and unpainted
events, the I3 movements and their settings, object views and stacked objects, behaviors (walls, counter), vehicle
class turn / bump / keep-moving, sprites (mirrored steps, streaming, step tables, indexed frames), the caches of a
large world (one map compiles against its tilesets only; events check again only when what they read changed), the
round trip (open and save without edits) and the commands.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import behaviors, engine, events, field_rules, maps, mapview, objects, sprites  # noqa: E402
from capsule_studio.core import tilesets  # noqa: E402
from capsule_studio.core.document import Document, DocumentError  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402
from sample_data import copy_engine_maps  # noqa: E402

## PNG file signature.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
## PNG color type of a palette image.
PALETTE_COLOR_TYPE = 3
## Bit depth of the test PNGs (one byte per index).
BYTE_DEPTH = 8
## Filter byte of an unfiltered PNG row.
NO_FILTER = b"\x00"
## Colors written into a test PNG's palette (RGB triples; the indices are the data, the colors do not matter).
PNG_COLORS = 16
## A sprite frame side in the tests, pixels.
FRAME = 16
## Frames in the test sprite sheet.
SHEET_FRAMES = 3
## The fixture's fixed tileset owns VRAM tiles 0-7; the test's second one starts after them.
SECOND_TILE = 8
## The second fixed tileset's first palette bank (the fixture's owns 0-1).
SECOND_BANK = 2
## A VRAM tile the fixture's fixed tileset places (its tile 1, flat palette index 1).
FIRST_TILE = 1


def palette_png(width: int, height: int, indices: bytes) -> bytes:
   """!A palette PNG (color type 3, depth 8) of given palette indices.
   @param width    pixels
   @param height   pixels
   @param indices  one byte per pixel, rows top to bottom
   @return the file's bytes
   """
   def chunk(kind: bytes, body: bytes) -> bytes:
      """!One PNG chunk with its CRC."""
      return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
   ihdr = struct.pack(">IIBBBBB", width, height, BYTE_DEPTH, PALETTE_COLOR_TYPE, 0, 0, 0)
   plte = bytes(range(PNG_COLORS * 3))   # any colors: three bytes each
   rows = b"".join(NO_FILTER + indices[y * width:(y + 1) * width] for y in range(height))
   return PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"PLTE", plte) + chunk(b"IDAT", zlib.compress(rows)) + \
      chunk(b"IEND", b"")


def run_cli(*argv: str) -> tuple[int, str]:
   """!Runs the command line, capturing what it prints.
   @param argv  arguments
   @return (status, output)
   """
   out = io.StringIO()
   with contextlib.redirect_stdout(out):
      status = cli(list(argv))
   return status, out.getvalue()


class WorldFormatTests(unittest.TestCase):
   """!Each test works on its own copy of the engine's map test world."""

   def setUp(self) -> None:
      """!Copies the world and opens it.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_i2i3_"))
      ## The copy's world.json.
      self.world = copy_engine_maps(self.root)
      ## The Project.
      self.p = Project.open(self.world)

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)

   def compiles(self) -> None:
      """!Asserts that the whole world compiles with the engine.
      @return None
      """
      self.assertIsNone(self.p.validate())

   # -- "all" dictionaries (I2) --------------------------------------------------------------------

   def test_all_dictionary(self) -> None:
      """!An "all" dictionary resolves to the tilesets' metatiles, paints by name, converts both ways keeping what
      the cells show, and follows the tilesets' and their metatiles' order.
      @return None
      """
      doc = self.p.map("fixed_a")
      self.assertTrue(maps.uses_all(doc.data))
      names = self.p.dictionary("fixed_a")
      self.assertEqual(names, [f"fixed/{n}" for n in self.p.metatile_names("fixed")])
      self.assertEqual(maps.dictionary(doc.data), [])   # without the tilesets' names: nothing to resolve
      self.assertEqual(maps.compact_dictionary(doc), 0)   # "all" holds every metatile
      with doc.edit("Paint"):
         i = maps.dictionary_index(doc, "fixed/glow", self.p.metatile_names)
         maps.paint(doc, 0, 1, 1, i)
      self.assertEqual(doc.data["metatiles"], "all")
      self.assertEqual(i, names.index("fixed/glow"))
      with self.assertRaises(ValueError):
         maps.dictionary_index(doc, "fixed/glow")   # "all" needs the tilesets' names
      with self.assertRaises(ValueError):
         maps.dictionary_index(doc, "test/ground", self.p.metatile_names)   # not one of the map's tilesets
      shown = self.shown(doc)
      with doc.edit("List"):
         maps.set_listed(doc, self.p.metatile_names)
      self.assertIsInstance(doc.data["metatiles"], list)
      self.assertEqual(self.shown(doc), shown)
      self.assertLessEqual(set(doc.data["metatiles"]), set(names))   # the metatiles painted
      with doc.edit("All"):
         maps.set_all(doc, self.p.metatile_names)
      self.assertEqual(doc.data["metatiles"], "all")
      self.assertEqual(self.shown(doc), shown)
      self.compiles()

   def shown(self, doc: Document) -> list[str | None]:
      """!What the map's cells and border show, by metatile name.
      @param doc  map Document
      @return names per cell and border entry
      """
      names = maps.dictionary(doc.data, self.p.metatile_names)
      out = []
      for c in doc.data["chunks"]:
         for g in c["layers"]:
            out += [None if v is None else names[v] for r in g for v in r]
      for pat in doc.data["border"]["layers"]:
         out += [None if v is None else names[v] for v in pat]
      return out

   def second_fixed(self) -> str:
      """!Adds a second fixed tileset after the fixture's: its sheet at VRAM tile 8, its bank 2, a metatile drawing
      the fixture's tile 1 and one of its own; fixed_b then loads both (its "all" cells renumbered).
      @return the tileset's name
      """
      name = "fixed2"
      self.p.add_tileset(name)
      self.p.save_all()
      src = self.world.parent / "tilesets" / "fixed_tiles.png"

      def build(doc: Document) -> None:
         sheet = tilesets.add_indexed_sheet(doc, "tiles", src)
         tilesets.set_place(doc, sheet=sheet, tile=SECOND_TILE, tiles=SECOND_TILE, palette=SECOND_BANK, palettes=1)
         tilesets.set_bank_color(doc, 0, 1, "#ff0000")
         tilesets.add_fixed_metatile(doc, "borrowed", [tilesets.make_entry(FIRST_TILE)] * tilesets.TILES_PER_METATILE)
         tilesets.add_fixed_metatile(doc, "own", [tilesets.make_entry(SECOND_TILE + 1, bank=SECOND_BANK)] *
                                     tilesets.TILES_PER_METATILE)
      self.p.edit_tileset(name, "Build", build)
      doc = self.p.map("fixed_b")
      shown = self.shown(doc)
      with doc.edit("Tilesets"):
         maps.set_tilesets(doc, ["fixed", name], self.p.tileset_names(), self.p.metatile_names)
      self.assertEqual(self.shown(doc), shown)   # the cells were renumbered (here: the same ids, appended after)
      return name

   def test_fixed_tilesets(self) -> None:
      """!A fixed tileset's placement, banks, entries and indexed sheets, its pictures drawn with the tilesets maps
      load with it, and the engine's checks of overlapping placements.
      @return None
      """
      name = self.second_fixed()
      self.compiles()
      doc = self.p.tileset(name)
      self.assertTrue(tilesets.is_fixed(doc))
      self.assertEqual(tilesets.place_of(doc)["tile"], SECOND_TILE)
      self.assertEqual(tilesets.bank_colors(doc)[0][1], "#ff0000")
      self.assertEqual(tilesets.split_entry(tilesets.make_entry(5, True, False, 3)), (5, True, False, 3))
      self.assertEqual(self.p.companions(name), ["fixed", name])
      ts, preview, error = self.p.compiled_tileset(name)
      self.assertIsNone(error)
      # "borrowed" draws the fixture's tile 1 in bank 0: its pixels are that bank's color 1, not blank
      img = mapview.metatile_images(preview, backdrop=False)[0]
      self.assertTrue(any(img[2][3::4]), "the borrowed tile is drawn with the tileset that places it")
      alone = self.p.compiled_tileset(name, [name])[1]
      self.assertFalse(any(mapview.metatile_images(alone, backdrop=False)[0][2][3::4]))   # alone: blank VRAM there
      w, h, _px = mapview.sheet_image(ts, "tiles", SECOND_BANK)
      self.assertEqual((w, h), (ts.sheets["tiles"].w * mapview.TILE, ts.sheets["tiles"].h * mapview.TILE))
      for bad in ({"tile": engine.tool("map_compiler").MAX_TILES}, {"palettes": 0, "palette": 13},
                  {"sheet": "nothing"}, {"colour": 1}):
         with self.assertRaises(ValueError, msg=bad), doc.edit("Bad"):
            tilesets.set_place(doc, **bad)
      # overlapping placements: the engine refuses a map loading both
      with doc.edit("Overlap"):
         tilesets.set_place(doc, tile=0)
      error = self.p.compiled_map("fixed_b")[1]
      self.assertIn("both place VRAM tile", error)
      with self.assertRaises(ValueError), self.p.tileset("test").edit("Not empty"):
         tilesets.set_place(self.p.tileset("test"), sheet="t")   # a tileset of tile references stays one

   def test_metatile_order_follows(self) -> None:
      """!Adding or removing a metatile of a tileset renumbers the "all" maps after it (one undo step with the
      tileset); a removal of a painted metatile is refused.
      @return None
      """
      self.second_fixed()
      doc = self.p.map("fixed_b")
      with doc.edit("Paint own"):
         maps.paint(doc, 0, 0, 0, maps.dictionary_index(doc, "fixed2/own", self.p.metatile_names))
      shown = self.shown(doc)
      self.p.edit_tileset("fixed", "New metatile", lambda t: tilesets.add_fixed_metatile(t, "extra"))
      self.assertEqual(self.shown(doc), shown)   # fixed2's metatiles moved one id up; the cells followed
      self.p.tileset("fixed").undo()
      self.assertEqual(self.shown(doc), shown)
      self.assertNotIn("extra", self.p.metatile_names("fixed"))
      with self.assertRaises(ValueError):
         self.p.edit_tileset("fixed2", "Delete", lambda t: tilesets.remove_metatile(t, "own"))
      self.assertIn("own", self.p.metatile_names("fixed2"))   # refused: nothing changed
      self.compiles()

   def test_animations(self) -> None:
      """!Animations of both tileset kinds: phase (I2), from_sheet and on_shift (I3), within the engine's ranges.
      @return None
      """
      fixed = self.p.tileset("fixed")
      with fixed.edit("Animation"):
         tilesets.set_animation(fixed, 0, phase=3, from_sheet=True, on_shift="restart")
      self.assertEqual(tilesets.animations(fixed)[0]["on_shift"], "restart")
      self.compiles()
      mp, _e = self.p.compiled_map("fixed_a")
      self.assertEqual(mp["anims"][0]["phase"], 3)
      self.assertTrue(mp["anims"][0]["flags"])
      with fixed.edit("Defaults"):
         tilesets.set_animation(fixed, 0, phase=None, from_sheet=False, on_shift="keep")
      self.assertNotIn("from_sheet", tilesets.animations(fixed)[0])   # defaults are left out
      self.assertNotIn("on_shift", tilesets.animations(fixed)[0])
      for bad in ({"phase": 4}, {"on_shift": "spin"}, {"from_sheet": 1}, {"period": 0}, {"tiles": "t:0"}):
         with self.assertRaises(ValueError, msg=bad), fixed.edit("Bad"):
            tilesets.set_animation(fixed, 0, **bad)
      test = self.p.tileset("test")
      with test.edit("Add"):
         i = tilesets.add_animation(test, "pulse", "frames", tiles="t:6", period=8, phase=7)
      self.assertEqual(tilesets.animations(test)[i]["phase"], 7)
      self.assertIn("phase", tilesets.animation_keys(test))
      self.assertEqual(tilesets.on_shift_words(), list(engine.tool("map_compiler").ON_SHIFT))
      self.compiles()

   # -- events and objects (I3) ----------------------------------------------------------------------

   def test_warps(self) -> None:
      """!Door, arrow, landing-only and dynamic warps: set, described, checked by the engine, doors' cells.
      @return None
      """
      doc = self.p.map("crowd")
      self.assertEqual(events.warp_triggers(), list(engine.tool("event_compiler").WARP_TRIGGERS))
      texts = [events.describe("warps", w) for w in events.events(doc, "warps")]
      self.assertIn("door up", texts[0])
      self.assertIn("a landing only", texts[2])
      self.assertIn("the game decides", texts[3])
      self.assertEqual(events.door_cell(events.events(doc, "warps")[0]), (3, 7))
      with doc.edit("None"):
         events.set_event(doc, "warps", 1, trigger="none")
      self.assertNotIn("direction", events.events(doc, "warps")[1])   # a landing takes no direction
      with doc.edit("Door"):
         events.set_event(doc, "warps", 1, trigger="door", direction="up", to=events.dynamic_to())
      self.compiles()
      with self.assertRaises(DocumentError), doc.edit("Bad"):
         events.set_event(doc, "warps", 1, trigger="teleport")
      with doc.edit("Step"):
         events.set_event(doc, "warps", 1, trigger="step")
      self.assertNotIn("trigger", events.events(doc, "warps")[1])
      with doc.edit("Unpainted"):
         events.set_unpainted_events(doc, True)
      self.assertTrue(doc.data["unpainted_events"])
      self.compiles()

   def test_door_diagnostic(self) -> None:
      """!A door opened from a cell the walker cannot stand on is reported.
      @return None
      """
      doc = self.p.map("crowd")
      x, y = events.door_cell(events.events(doc, "warps")[0])
      with doc.edit("Block"):
         maps.set_attributes(doc, x, y, collision=1)
      found = [d.message for d in events.diagnostics(self.p, "crowd")]
      self.assertTrue(any("door warp 0" in m for m in found), found)

   def test_movements(self) -> None:
      """!The I3 movements and their settings (the engine's lists), ranges up to the engine's, settings dropped
      with a movement that does not take them, object views and stacked objects.
      @return None
      """
      self.assertEqual(objects.movements(), [m for m in engine.tool("object_compiler").MOVEMENTS
                                             if m != objects.SCHEDULE])
      doc = self.p.map("crowd")
      i = objects.index_of(doc, "turner")
      with doc.edit("Turn"):
         objects.set_object(doc, i, movement_args={"choices": ["left", "right"], "delays": "short",
                                                   "watch_runner": True})
      self.compiles()
      with doc.edit("Roam"):
         objects.set_object(doc, i, movement="roam", range=[objects.max_range(), 0])
      self.assertEqual(objects.objects(doc)[i]["movement_args"], {"choices": ["left", "right"], "delays": "short"})
      with doc.edit("Static"):
         objects.set_object(doc, i, movement="static")
      self.assertNotIn("movement_args", objects.objects(doc)[i])   # static takes keep_facing only
      for bad in ({"movement_args": {"choices": ["left"]}}, {"movement_args": {"pace": "sprint"}},
                  {"movement_args": {"spin": True}}, {"movement_args": {"legs": ["up"] * 3}},
                  {"range": [objects.max_range() + 1, 0]}):
         with self.assertRaises(DocumentError, msg=bad), doc.edit("Bad"):
            objects.set_object(doc, i, **bad)
      with doc.edit("Mirror"):
         objects.set_object(doc, i, movement="mirror", movement_args={"facing": "left", "keep_to": "swim"})
      with doc.edit("Pace"):
         objects.set_object(doc, objects.index_of(doc, "jogger"), movement_args={"pace": "run"})
      self.compiles()
      with doc.edit("Unknown class"):
         objects.set_object(doc, i, movement_args={"keep_to": "jetpack"})
      self.assertIn("keep_to", self.p.validate())   # the engine checks the class
      self.assertIn("mirror", objects.describe(objects.objects(doc)[i]))

   def test_object_view(self) -> None:
      """!64 objects with a view, 15 without; stacked objects; their diagnostics.
      @return None
      """
      doc = self.p.map("crowd")
      self.assertEqual(objects.object_view(doc), [9, 10, 7, 9])
      self.assertEqual(objects.max_objects(doc), engine.tool("object_compiler").MAX_VIEW_OBJECTS)
      with self.assertRaises(DocumentError), doc.edit("No view"):
         objects.set_object_view(doc, None)   # 31 objects need the view
      for bad in ([0, 0, 0, 0], [1, 2, 3], [engine.tool("map_compiler").MAX_VIEW_CELLS + 1, 0, 0, 0]):
         with self.assertRaises(DocumentError), doc.edit("Bad view"):
            objects.set_object_view(doc, bad)
      with doc.edit("View"):
         objects.set_object_view(doc, [4, 4, 4, 4])
      found = [d.message for d in objects.diagnostics(self.p, "crowd")]
      self.assertTrue(any("shares its cell" in m for m in found), found)
      with doc.edit("Not stacked"):
         objects.set_stacked(doc, False)
      self.assertIn("stands on", self.p.validate())   # the engine refuses objects sharing a cell now
      town = self.p.map("town")
      self.assertEqual(objects.max_objects(town), engine.tool("object_compiler").MAX_OBJECTS)

   # -- world settings ----------------------------------------------------------------------------------

   def test_behaviors_and_modes(self) -> None:
      """!Behaviors' walls and counters (I2 / I3) and the vehicle classes' turn time, bump and keep-moving (I3).
      @return None
      """
      w = self.p.world
      rows = {r["name"]: r for r in behaviors.rows(w)}
      self.assertEqual(rows["fence_east"]["walls"], ["right"])
      self.assertEqual(rows["counter_top"]["kind"], "counter")
      self.assertTrue(rows["counter_top"]["solid"])
      with w.edit("Behaviors"):
         behaviors.add_behavior(w, "fence_corner")
         behaviors.set_walls(w, "fence_corner", ["up", "left", "down"])
         behaviors.set_kind(w, "fence_corner", "ledge", "down")
         behaviors.set_passable(w, "fence_corner", ["foot"])
      row = {r["name"]: r for r in behaviors.rows(w)}["fence_corner"]
      self.assertEqual(row["walls"], ["down", "up", "left"])   # the engine's direction order
      self.assertEqual((row["kind"], row["direction"], row["passable"]), ("ledge", "down", ["foot"]))
      self.compiles()
      with w.edit("Counter"):
         behaviors.set_kind(w, "fence_corner", "counter")
      self.assertNotIn("ledge", w.data["behaviors"][-1])   # the kinds exclude each other
      for bad in (lambda: behaviors.set_walls(w, "fence_corner", ["north"]),
                  lambda: behaviors.set_walls(w, "fence_corner", ["up", "up"]),
                  lambda: behaviors.set_kind(w, "fence_corner", "push"),
                  lambda: behaviors.add_behavior(w, "normal")):
         with self.assertRaises(DocumentError), w.edit("Bad"):
            bad()
      trek = {r["name"]: r for r in field_rules.mode_rows(w)}["trek"]
      self.assertEqual((trek["turn_frames"], trek["bumps"], trek["keeps_moving"]), (8, True, True))
      with w.edit("Turn"):
         field_rules.set_mode(w, "swim", "turn_frames", field_rules.max_turn_frames())
         field_rules.set_mode(w, "swim", "bumps", True)
      self.compiles()
      with self.assertRaises(DocumentError) as caught:   # the engine's check, refused at once
         field_rules.set_mode(w, "swim", "turn_frames", field_rules.max_turn_frames() + 1)
      self.assertIn("turn_frames", str(caught.exception))

   # -- sprites (I3) ----------------------------------------------------------------------------------------

   def test_sprites(self) -> None:
      """!Mirrored steps kept through step edits, streaming, step tables and an indexed sheet's frames.
      @return None
      """
      folder = self.root / "assets"
      folder.mkdir()
      sheet = folder / "walker.png"
      # three 16x16 frames side by side, each flat palette index 1, 2, 3
      w = FRAME * SHEET_FRAMES
      sheet.write_bytes(palette_png(w, FRAME, bytes(1 + x // FRAME for _y in range(FRAME) for x in range(w))))
      doc = Document(path=folder / "assets.json")
      doc.save()
      key = "sprite:WALKER"
      with doc.edit("New"):
         a = sprites.new_sprite(doc, key, FRAME, FRAME)
         a["palette"] = ["#000000", "#ff0000", "#00ff00", "#0000ff"]
         rows = sprites.add_sheet_frames(doc, key, sheet)
      self.assertEqual(rows, list(range(SHEET_FRAMES)))
      self.assertEqual(a["frames"][2], {"image": "frames/walker/walker.png", "frame": 2, "indexed": True})
      self.assertTrue((folder / "frames" / "walker" / "walker.png").exists())
      report = doc.compile_asset(a)
      self.assertTrue(report.ok, report.error)
      _w, _h, px = sprites.frame_pixels(report.compiled, 2)
      self.assertEqual(set(px), {3})   # the sheet's indices, as they are
      with doc.edit("Mirror"):
         sprites.set_flips(doc, key, [1], 1)
      with doc.edit("Duplicate"):
         sprites.duplicate_steps(doc, key, [1])
      self.assertEqual(sprites.flips(a), [0, 1, 1, 0])
      with doc.edit("Move"):
         sprites.move_steps(doc, key, [3], -3)
      self.assertEqual(sprites.flips(a), [0, 0, 1, 1])   # the moved step took its flips along
      with doc.edit("Remove"):
         sprites.remove_steps(doc, key, [1])
      self.assertEqual(sprites.flips(a), [0, 1, 1])
      with doc.edit("Durations"):
         sprites.set_durations(doc, key, [0], 4)
      self.assertEqual(a["animations"][0]["flips"], [0, 1, 1])   # kept by a duration change
      with self.assertRaises(ValueError), doc.edit("Bad flip"):
         sprites.set_flips(doc, key, [0], 4)
      a = doc.get(key)   # a refused edit put back a copy of the manifest
      with doc.edit("Stream"):
         sprites.set_stream(doc, key, True)
         sprites.set_step_table(doc, key, [0, 2, 1, 1])
      self.assertEqual(sprites.tile_budget(a)[0], sprites.tiles_per_frame(a))   # one frame in VRAM
      report = doc.compile_asset(a)
      self.assertTrue(report.ok, report.error)
      self.assertTrue(report.compiled["stream"])
      self.assertEqual(report.compiled["steps"], [0, 2, 1, 1])
      with self.assertRaises(ValueError), doc.edit("Bad table"):
         sprites.set_step_table(doc, key, [0, 1])
      with self.assertRaises(ValueError), doc.edit("Resize"):
         sprites.resize(doc, key, 32, 32)   # indexed frames keep their size
      a = doc.get(key)
      with doc.edit("No table"):
         sprites.set_step_table(doc, key, None)
         sprites.set_stream(doc, key, False)
      self.assertNotIn("steps", a)
      self.assertNotIn("stream", a)

   # -- large worlds (I2): caches ------------------------------------------------------------------------

   def test_caches(self) -> None:
      """!A map compiles against its tilesets only, each once per change; the events check runs again only when
      what the event compilers read changed.
      @return None
      """
      mc = engine.tool("map_compiler")
      calls = {"tileset": 0, "events": 0}
      real_ts, real_ev = mc.compile_tileset, mc.compile_world_events

      def counted_ts(*a: object, **k: object) -> object:
         calls["tileset"] += 1
         return real_ts(*a, **k)

      def counted_ev(*a: object, **k: object) -> object:
         calls["events"] += 1
         return real_ev(*a, **k)
      mc.compile_tileset, mc.compile_world_events = counted_ts, counted_ev
      try:
         mp, error = self.p.compiled_map("fixed_a")
         self.assertIsNone(error)
         self.assertEqual(calls["tileset"], 1)   # fixed only, not test
         self.p.compiled_map("fixed_b")
         self.assertEqual(calls["tileset"], 1)   # the same tileset, unchanged: compiled once
         self.assertIsNone(events.check(self.p))
         self.assertIsNone(events.check(self.p))
         self.assertEqual(calls["events"], 1)
         doc = self.p.map("crowd")
         with doc.edit("Paint away from the events"):
            maps.set_attributes(doc, 0, 0, collision=0)
            maps.paint(doc, 0, 0, 0, 0)
         events.check(self.p)
         self.assertEqual(calls["events"], 1)   # no event cell changed
         x, y = events.events(doc, "warps")[0]["at"]
         with doc.edit("Unpaint an event cell"):
            maps.erase(doc, x, y)
         events.check(self.p)
         self.assertEqual(calls["events"], 2)   # an event's cell changed
         fixed = self.p.tileset("fixed")
         with fixed.edit("Phase"):
            tilesets.set_animation(fixed, 0, phase=2)
         self.p.compiled_map("fixed_a")
         self.assertEqual(calls["tileset"], 2)   # the tileset changed: compiled again
      finally:
         mc.compile_tileset, mc.compile_world_events = real_ts, real_ev

   def test_snapshot(self) -> None:
      """!The background compile works on copies of the unsaved documents.
      @return None
      """
      doc = self.p.map("fixed_a")
      with doc.edit("Bad"):
         doc.data["can_run"] = "sometimes"
      job = self.p.snapshot()
      with doc.edit("Fix"):
         doc.data["can_run"] = True
      result, error = job()
      self.assertIn("can_run", error)   # what the documents held when the snapshot was taken
      self.assertIsNone(self.p.snapshot()()[1])

   # -- round trip ------------------------------------------------------------------------------------------

   def test_round_trip(self) -> None:
      """!Opening every document and saving without edits writes nothing (every file stays byte-identical); a
      forced save of each keeps its JSON (the studio's layout may differ: semantically identical).
      @return None
      """
      files = sorted(p for p in self.world.parent.rglob("*") if p.is_file())
      before = {p: p.read_bytes() for p in files}
      for n in self.p.map_names():
         self.p.map(n)
      for n in self.p.tileset_names():
         self.p.tileset(n)
      self.p.compiled_map("fixed_a")
      events.check(self.p)
      self.p.save_all()
      self.assertEqual({p: p.read_bytes() for p in files}, before)
      for d in self.p.documents():
         d.save()
      for p in files:
         if p.suffix == ".json":
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), json.loads(before[p]), p.name)

   # -- the command line -------------------------------------------------------------------------------------

   def test_commands(self) -> None:
      """!The I2 / I3 commands change what the panels change, compiled before saving.
      @return None
      """
      w = str(self.world)
      status, out = run_cli("map", w, "fixed_a", "dictionary")
      self.assertEqual(status, 0)
      self.assertIn("every metatile", out)
      self.assertEqual(run_cli("map", w, "fixed_a", "dictionary", "list")[0], 0)
      self.assertIsInstance(Project.open(w).map("fixed_a").data["metatiles"], list)
      self.assertEqual(run_cli("map", w, "fixed_a", "dictionary", "all")[0], 0)
      status, out = run_cli("tileset", w, "fixed", "animation-set", "0", "--phase", "2", "--on-shift", "reload")
      self.assertEqual(status, 0, out)
      self.assertIn("phase 2", out)
      status, out = run_cli("tileset", w, "fixed", "animation-set", "0", "--phase", "-")
      self.assertIn("phase auto", out)
      self.assertEqual(run_cli("tileset", w, "fixed", "bank", "1", "2", "#123456")[0], 0)
      status, out = run_cli("tileset", w, "fixed", "entry", "white", "0", "4", "--bank", "1", "--hflip")
      self.assertEqual(status, 0, out)
      self.assertIn("0x1404", out)
      status, out = run_cli("tileset", w, "fixed", "place")
      self.assertIn("tiles 8", out)
      self.assertEqual(run_cli("events", "set", w, "crowd", "warp", "1", "--trigger", "door", "--to", "dynamic")[0],
                       0)
      self.assertEqual(run_cli("events", "unpainted", w, "crowd", "on")[0], 0)
      status, out = run_cli("objects", "set", w, "crowd", "turner", "--movement", "rotate", "--args",
                            '{"clockwise": true}')
      self.assertEqual(status, 0, out)
      status, out = run_cli("objects", "view", w, "crowd", "5", "5", "5", "5")
      self.assertIn("5 left", out)
      self.assertEqual(run_cli("objects", "stacked", w, "crowd", "on")[0], 0)
      status, out = run_cli("behaviors", w, "set", "fence_east", "--walls", "right,down")
      self.assertEqual(status, 0, out)
      self.assertIn("walls down, right", out)
      self.assertEqual(run_cli("modes", w, "set", "swim", "turn_frames", "12")[0], 0)
      p = Project.open(w)
      self.assertEqual(tilesets.animations(p.tileset("fixed"))[0].get("on_shift"), "reload")
      self.assertEqual(events.events(p.map("crowd"), "warps")[1]["to"], "dynamic")
      self.assertEqual(objects.objects(p.map("crowd"))[1]["movement_args"], {"clockwise": True})
      self.assertIsNone(p.validate())
      status, out = run_cli("objects", "set", w, "crowd", "turner", "--args", "{bad")
      self.assertEqual(status, 1)


if __name__ == "__main__":
   unittest.main()
