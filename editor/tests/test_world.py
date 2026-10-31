#!/usr/bin/env python3
"""!Tests for capsule_studio.core.world / maps / tilesets / mapview and the
world, map and tileset commands (no Qt needed).

Uses the engine's map sandbox world as the starting point (copied).
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine, field_rules, mapgroups, maps, mapview, tilesets  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402


def sandbox_world() -> Path:
   """!The engine's map sandbox data folder.
   @return Path
   """
   return engine.root() / "apps" / "sandbox_map" / "data"


class WorldTestCase(unittest.TestCase):
   """!Base: a copy of the sandbox world per test.

   @var dir
   The copy's folder (the world's data folder).
   @var project
   The opened Project.
   """

   def setUp(self) -> None:
      """!Copies the world (with the Starter sample its world names, laid out as in the engine:
      apps/sandbox_map and samples/starter) and opens it.
      @return None
      """
      ## Temporary apps folder holding sandbox_map/data (the Starter it names is in ../samples/starter).
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_world_")), ["sandbox_map"])
      self.dir = self.root / "sandbox_map" / "data"
      self.project = Project.open(self.dir / "world.json")

   def tearDown(self) -> None:
      """!Removes the copy.
      @return None
      """
      shutil.rmtree(self.root.parent, ignore_errors=True)


class ProjectTests(WorldTestCase):
   """!Opening, compiling with unsaved edits, adding, renaming, saving."""

   def test_compiles_and_sees_unsaved_edits(self) -> None:
      """!The project compiles; an unsaved paint changes the compiled map.
      @return None
      """
      mp, error = self.project.compiled_map("meadow")
      self.assertIsNone(error)
      mc = engine.tool("map_compiler")
      water = self.project.map("meadow").data["metatiles"].index("outdoor/water")
      self.assertNotEqual(mc.metatile_at(mp, 0, 3, 3), water)
      doc = self.project.map("meadow")
      with doc.edit("Paint"):
         maps.paint(doc, 0, 3, 3, water)
      mp, _ = self.project.compiled_map("meadow")
      self.assertEqual(mc.metatile_at(mp, 0, 3, 3), water)
      self.assertTrue(self.project.dirty)

   def test_errors_come_back_as_messages(self) -> None:
      """!A broken reference is reported, not raised.
      @return None
      """
      doc = self.project.map("cave")
      with doc.edit("Break"):
         doc.data["metatiles"][0] = "cave/nothing"
      self.assertIn("no metatile 'nothing'", self.project.validate())

   def test_add_map_and_tileset_then_save(self) -> None:
      """!New documents are listed in the world and written on save_all().
      @return None
      """
      self.project.add_tileset("extra")
      self.assertIsNone(self.project.validate())   # an empty tileset is fine
      ts = self.project.tileset("extra")
      with ts.edit("Sheet"):
         ts.data["sheets"].append({"name": "s", "palette": ["#ffffff"], "size": [8, 8], "shapes": []})
      self.project.add_map("field", fill="outdoor/grass")
      self.assertIsNone(self.project.validate())
      self.project.save_all()
      again = Project.open(self.dir / "world.json")
      self.assertIn("field", again.map_names())
      self.assertTrue((self.dir / "maps" / "field.json").exists())
      with self.assertRaises(DocumentError):
         again.add_map("field")

   def test_new_world_gets_a_start(self) -> None:
      """!A new world compiles once it has a tileset and a map: the first
      map becomes the start.
      @return None
      """
      p = Project.create(self.dir / "fresh" / "world.json", "fresh")
      ts = p.add_tileset("t")
      with ts.edit("Sheet"):
         ts.data["sheets"].append({"name": "s", "palette": ["#ffffff"], "size": [8, 8], "shapes": []})
         tilesets.add_metatile(ts, "m", [None] * 4)
      p.add_map("first", fill="t/m")
      p.add_map("second", fill="t/m")
      self.assertEqual(p.world.data["start"]["map"], "first")
      self.assertIsNone(p.validate())

   def test_rename_metatile_updates_maps(self) -> None:
      """!Renaming a metatile renames it in every map's dictionary.
      @return None
      """
      changed = self.project.rename_metatile("outdoor", "water", "pond")
      self.assertEqual(changed, ["meadow", "showcase"])
      self.assertIn("outdoor/pond", self.project.map("meadow").data["metatiles"])
      self.assertIsNone(self.project.validate())

   def test_tileset_preview(self) -> None:
      """!A tileset compiles on its own with a preview of every metatile.
      @return None
      """
      ts, preview, error = self.project.compiled_tileset("outdoor")
      self.assertIsNone(error)
      self.assertEqual(len(preview["metatiles"]), len(self.project.tileset("outdoor").data["metatiles"]))
      img = mapview.metatile_image(preview, 0)
      self.assertEqual(img[:2], (16, 16))
      self.assertEqual(img[2][3], 255)


class MapEditTests(WorldTestCase):
   """!Painting operations."""

   def test_cells_pack_like_the_compiler(self) -> None:
      """!The editor's attribute cell layout is the compiler's.
      @return None
      """
      mc = engine.tool("map_compiler")
      self.assertEqual({k: v[:2] for k, v in maps.cell_fields().items()}, {k: v[:2] for k, v in mc.CELL_FIELDS.items()})
      c = maps.make_cell(behavior=3, env=7, collision=2, elevation=9, encounter=True)
      self.assertEqual(maps.unpack(c), {"behavior": 3, "env": 7, "collision": 2, "elevation": 9,
                                        "encounter": True, "slot": 0})
      self.assertEqual(maps.with_fields(c, collision=0, encounter=False) & (3 << 16 | 1 << 22), 0)
      with self.assertRaises(ValueError):
         maps.make_cell(collision=4)
      self.assertEqual(set(maps.PURPOSES), set(mc.LAYER_PURPOSE))

   def test_paint_creates_chunk_and_keeps_attributes(self) -> None:
      """!Painting outside the chunks adds one with default attributes;
      attributes survive repainting; erase clears every layer.
      @return None
      """
      doc = self.project.map("meadow")
      with doc.edit("Paint"):
         maps.paint(doc, 0, 40, 40, 3)
         self.assertEqual(maps.unpack(maps.get(doc.data, 40, 40))["collision"], 0)
         self.assertTrue(maps.set_attributes(doc, 40, 40, collision=1, elevation=5))
         maps.paint(doc, 0, 40, 40, 2)
         maps.paint(doc, 1, 40, 40, 0)
      a = maps.unpack(maps.get(doc.data, 40, 40))
      self.assertEqual((a["collision"], a["elevation"]), (1, 5))
      self.assertEqual((maps.get_tile(doc.data, 0, 40, 40), maps.get_tile(doc.data, 1, 40, 40)), (2, 0))
      self.assertIsNone(maps.get(doc.data, 41, 40))
      self.assertFalse(maps.set_attributes(doc, 41, 40, collision=1))   # unpainted cells stay blocked
      self.assertTrue(maps.has_chunk(doc.data, 41, 40))
      with doc.edit("Clear"):
         maps.paint(doc, 1, 40, 40, None)                      # clearing a layer keeps the cell painted
      self.assertIsNotNone(maps.get(doc.data, 40, 40))
      self.assertIsNone(maps.get_tile(doc.data, 1, 40, 40))
      with doc.edit("Erase"):
         maps.erase(doc, 40, 40)
         self.assertIsNone(maps.get_tile(doc.data, 0, 40, 40))
         self.assertEqual(maps.trim(doc), 1)
      self.assertIsNone(self.project.validate())

   def test_fill_and_rect(self) -> None:
      """!Fill follows equal neighbours on one layer; rect paints the inclusive box.
      @return None
      """
      doc = self.project.map("cave")
      with doc.edit("Rect"):
         n = maps.rect(doc, 0, -8, -8, -5, -6, 2)
      self.assertEqual(n, 12)
      with doc.edit("Fill"):
         filled = maps.fill(doc, 0, -8, -8, 1)
      self.assertGreaterEqual(filled, 12)
      self.assertEqual(maps.get_tile(doc.data, 0, -5, -6), 1)
      with doc.edit("Again"):
         self.assertEqual(maps.fill(doc, 0, -8, -8, 1), 0)    # nothing to change
      with doc.edit("Attributes"):
         changed = maps.rect_attributes(doc, -8, -8, -5, -6, collision=1)
         self.assertEqual(changed, 12)
         spread = maps.fill_attributes(doc, -8, -8, "elevation", 4)
      self.assertGreaterEqual(spread, 12)
      self.assertEqual(maps.unpack(maps.get(doc.data, -5, -6))["elevation"], 4)
      self.assertIsNone(self.project.validate())

   def test_stamps(self) -> None:
      """!Multi-metatile stamps repeat from their anchor, so strokes,
      rectangles and fills line up; None entries leave cells alone.
      @return None
      """
      doc = self.project.map("cave")
      pat = [[0, 1], [2, None]]
      self.assertEqual(maps.pattern_at(pat, 4, 4, 5, 4), 1)
      self.assertEqual(maps.pattern_at(pat, 4, 4, 6, 6), 0)     # repeats every 2 cells
      self.assertEqual(maps.pattern_at(pat, 4, 4, 3, 3), None)  # and backwards
      self.assertEqual(maps.stamp_cells(pat, -8, -8), [(-8, -8), (-7, -8), (-8, -7)])
      with doc.edit("Stamp"):
         before = maps.get_tile(doc.data, 0, -7, -7)
         n = maps.stamp(doc, 0, maps.rect_cells(-8, -8, -7, -7), pat, -8, -8)
      self.assertEqual(n, 3)
      self.assertEqual([maps.get_tile(doc.data, 0, x, y) for x, y in ((-8, -8), (-7, -8), (-8, -7))], [0, 1, 2])
      self.assertEqual(maps.get_tile(doc.data, 0, -7, -7), before)
      with doc.edit("Region"):
         maps.rect(doc, 0, -8, -6, -5, -5, 4)                 # a 4x2 area of one metatile
         n = maps.fill(doc, 0, -8, -6, None, [[3, 1]])
      self.assertEqual(n, 8)
      self.assertEqual([maps.get_tile(doc.data, 0, x, -5) for x in range(-8, -4)], [3, 1, 3, 1])
      names = doc.data["metatiles"]
      with doc.edit("Border"):
         maps.resize_border(doc, 2, 2)
         maps.stamp_border(doc, 0, [(0, 0), (1, 0), (0, 1), (1, 1)], [[names[0], names[1]]], 0, 0)
      self.assertEqual(maps.border_of(doc.data)[2][0], [0, 1, 0, 1])
      self.assertIsNone(self.project.validate())

   def test_layers(self) -> None:
      """!Layers are added on free BGs, changed, removed with what is on them;
      the compiler sees the same layers.
      @return None
      """
      doc = self.project.map("cave")
      self.assertEqual(maps.free_bgs(doc.data), [0, 1, 3])
      with doc.edit("Layer"):
         k = maps.add_layer(doc, 1, purpose="canopy")
         maps.paint(doc, k, -8, -8, maps.dictionary_index(doc, "cave/crystal"))
      self.assertEqual(doc.data["chunks"][0]["layers"][k][0][0], doc.data["metatiles"].index("cave/crystal"))
      self.assertEqual(len(maps.border_of(doc.data)[2]), 2)
      with self.assertRaisesRegex(ValueError, "BG2 already"):
         maps.add_layer(doc, 2)
      with doc.edit("Move"):
         maps.set_layer(doc, k, bg=0, priority=0)
      self.assertEqual(maps.draw_order(doc.data), [0, 1])
      mp, error = self.project.compiled_map("cave")
      self.assertIsNone(error)
      self.assertEqual(mp["layers"], [(2, 2), (0, 0)])
      self.assertEqual(mapview.draw_order(mp), [0, 1])
      with doc.edit("Behind"):
         maps.set_layer(doc, k, priority=3)
      self.assertEqual(maps.draw_order(doc.data), [1, 0])
      with doc.edit("Remove"):
         maps.remove_layer(doc, k)
      self.assertEqual(len(doc.data["chunks"][0]["layers"]), 1)
      self.assertEqual(len(maps.border_of(doc.data)[2]), 1)
      self.assertIsNone(self.project.validate())

   def test_behaviors(self) -> None:
      """!Behaviors are painted through the map's dictionary, which follows
      what is painted (entry 0 stays).
      @return None
      """
      doc = self.project.map("cave")
      names = self.project.behavior_names()
      with doc.edit("Behavior"):
         b = maps.behavior_index(doc, "water", names)
         maps.set_attributes(doc, -8, -8, behavior=b)
      self.assertEqual(maps.behavior_name(doc.data, maps.get(doc.data, -8, -8), names), "water")
      with self.assertRaises(ValueError):
         maps.behavior_index(doc, "lava", names)
      mp, error = self.project.compiled_map("cave")
      self.assertIsNone(error)
      mc = engine.tool("map_compiler")
      self.assertEqual(mc.cell_at(mp, -8, -8) & 0xFF, names.index("water"))   # the world's index at runtime
      with doc.edit("Back"):
         maps.set_attributes(doc, -8, -8, behavior=0)
         self.assertEqual(maps.compact_behaviors(doc), 1)
      self.assertNotIn("water", doc.data["behaviors"])
      self.assertIsNone(self.project.validate())

   def test_border_and_compact(self) -> None:
      """!The border must index the dictionary; compaction renumbers cells.
      @return None
      """
      doc = self.project.map("meadow")
      with doc.edit("Border"):
         maps.set_border(doc, 2, 1, [[0, 1], [None, None]])
         maps.dictionary_index(doc, "outdoor/sign")
         unused = maps.dictionary_index(doc, "cave/floor") if "cave" in maps.tilesets_of(doc.data) else None
      self.assertIsNone(unused)    # meadow draws from outdoor only
      with doc.edit("Unused"):
         doc.data["metatiles"].append("outdoor/stairs_unused")   # nothing uses it
      with self.assertRaises(ValueError):
         maps.set_border(doc, 1, 1, [[999], [None]])
      with self.assertRaises(ValueError):
         maps.set_border(doc, 1, 1, [[0]])                      # one pattern per layer
      with doc.edit("Compact"):
         dropped = maps.compact_dictionary(doc)
      self.assertGreaterEqual(dropped, 1)
      self.assertNotIn("outdoor/stairs_unused", doc.data["metatiles"])
      self.assertIsNone(self.project.validate())

   def test_new_world_saves_into_new_folders(self) -> None:
      """!A new world's first tileset and map go into tilesets/ and maps/,
      which do not exist yet; a world listing files a failed save never
      wrote opens, and the next save writes them.
      @return None
      """
      folder = self.dir / "fresh"
      p = Project.create(folder / "world.json", "fresh")
      p.add_tileset("outdoor")
      p.add_map("route1", tilesets=["outdoor"])
      self.assertIsNone(p.validate())                    # an empty tileset and a blank map compile
      p.save_all()
      self.assertTrue((folder / "tilesets/outdoor.json").is_file())
      self.assertTrue((folder / "maps/route1.json").is_file())
      again = Project.open(folder / "world.json")
      self.assertIsNone(again.validate())
      self.assertFalse(again.dirty)
      # The world lists a map whose file is missing (as after the old failed save).
      (folder / "maps/route1.json").unlink()
      broken = Project.open(folder / "world.json")
      self.assertIsNone(broken.validate())                # compiles before the map is even opened
      self.assertEqual(broken.map("route1").data["metatiles"], [])
      self.assertEqual(len(maps.layers_of(broken.map("route1").data)), 3)
      self.assertTrue(broken.dirty)
      broken.save_all()
      self.assertTrue((folder / "maps/route1.json").is_file())

   def test_blank_map_and_tilesets(self) -> None:
      """!New maps start blank with three tile layers; the map's tilesets
      limit what is painted; the dictionary follows what is painted.
      @return None
      """
      doc = self.project.add_map("blank", tilesets=["cave"])
      self.assertEqual(doc.data["metatiles"], [])
      self.assertEqual(doc.data["chunks"], [])
      self.assertEqual([ly["bg"] for ly in doc.data["layers"]], [3, 2, 1])
      self.assertEqual(maps.border_of(doc.data)[2], [[None], [None], [None]])
      self.assertIsNone(self.project.validate())          # a blank map compiles
      self.assertEqual(maps.tilesets_of(doc.data), ["cave"])
      with self.assertRaisesRegex(ValueError, "not from one of this map's tilesets"):
         with doc.edit("Paint"):
            maps.paint(doc, 0, 0, 0, maps.dictionary_index(doc, "outdoor/grass"))
      with doc.edit("Paint"):
         maps.paint(doc, 0, 0, 0, maps.dictionary_index(doc, "cave/floor"))
         maps.compact_dictionary(doc)
      self.assertEqual(doc.data["metatiles"], ["cave/floor"])
      with self.assertRaisesRegex(ValueError, "still painted"):
         with doc.edit("Tilesets"):
            maps.set_tilesets(doc, ["outdoor"], self.project.tileset_names())
      with doc.edit("Erase"):
         maps.erase(doc, 0, 0)
         maps.compact_dictionary(doc)
      self.assertEqual(doc.data["metatiles"], [])        # nothing painted: nothing listed
      with doc.edit("Tilesets"):
         maps.set_tilesets(doc, ["outdoor", "cave"], self.project.tileset_names())
      self.assertEqual(doc.data["tilesets"], ["outdoor", "cave"])
      self.assertIsNone(self.project.validate())
      # An empty border cell survives compaction.
      with doc.edit("Border"):
         maps.set_border(doc, 2, 1, [[maps.dictionary_index(doc, "outdoor/grass"), None], [None, None],
                                     [None, None]])
         maps.compact_dictionary(doc)
      self.assertEqual(maps.border_of(doc.data)[2][0], [0, None])
      self.assertIsNone(self.project.validate())
      filled = self.project.add_map("filled", fill="cave/floor")
      self.assertEqual(maps.get_tile(filled.data, 0, 7, 7), 0)       # the back layer, BG3
      self.assertIsNone(maps.get_tile(filled.data, 1, 7, 7))
      self.assertIsNone(self.project.validate())

   def test_border_painting(self) -> None:
      """!The border is painted cell by cell per layer, resized and cleared like a map.
      @return None
      """
      doc = self.project.map("meadow")
      with doc.edit("Size"):
         maps.resize_border(doc, 2, 2)
      w, h, pats = maps.border_of(doc.data)
      self.assertEqual((w, h), (2, 2))
      self.assertEqual((pats[0][1], pats[0][3]), (None, None))    # meadow's 1x2 pattern gained an empty column
      with doc.edit("Paint"):
         n = maps.paint_border(doc, 0, [(0, 1), (1, 1)], "outdoor/water")
      self.assertEqual(n, 2)
      names = doc.data["metatiles"]
      self.assertEqual([names[i] for i in maps.border_of(doc.data)[2][0][2:]], ["outdoor/water"] * 2)
      with doc.edit("Clear"):
         maps.paint_border(doc, 0, [(1, 1)], None)
         maps.paint_border(doc, 1, [(0, 0)], None)
      self.assertIsNone(maps.border_of(doc.data)[2][0][3])
      self.assertEqual(maps.border_of(doc.data)[2][1], [None] * 4)
      with doc.edit("Shrink"):
         maps.resize_border(doc, 1, 1)
      self.assertEqual([len(p) for p in doc.data["border"]["layers"]], [1, 1])
      self.assertIsNone(self.project.validate())


class MapGroupTests(WorldTestCase):
   """!The world's map group tree."""

   def test_groups(self) -> None:
      """!Groups nest, hold maps (each in one group), rename, move and go away
      without losing maps; the compiler accepts the result.
      @return None
      """
      w = self.project.world
      with w.edit("Groups"):
         outside = mapgroups.add_group(w, (), "Outside")
         towns = mapgroups.add_group(w, outside, "Towns")
         mapgroups.add_group(w, (), "Caves")
         mapgroups.move_map(w, "meadow", towns)
         mapgroups.move_map(w, "cave", ("Caves",))
      self.assertEqual(mapgroups.group_of(w.data, "meadow"), ("Outside", "Towns"))
      t = mapgroups.tree(w.data, self.project.map_names())
      # groups first, then ungrouped (DS1: the sandbox's hut, the showcase's door warp inside)
      self.assertEqual([n[1] for n in t], ["Outside", "Caves", "showcase", "hut"])
      self.assertEqual(t[0][3][0][3], [("map", "meadow")])
      self.assertIsNone(self.project.validate())
      with self.assertRaisesRegex(ValueError, "already a group"):
         mapgroups.add_group(w, (), "Caves")
      with self.assertRaisesRegex(ValueError, "inside itself"):
         mapgroups.move_group(w, ("Outside",), ("Outside", "Towns"))
      with w.edit("Change"):
         mapgroups.move_map(w, "meadow", ("Caves",), 0)        # one group per map
         self.assertEqual(mapgroups.find(w.data, towns)["maps"], [])
         self.assertEqual(mapgroups.rename_group(w, ("Caves",), "Underground"), ("Underground",))
         mapgroups.move_group(w, ("Underground",), ("Outside",))
         mapgroups.remove_group(w, ("Outside",))                # Towns and Underground move up
      self.assertEqual([g["name"] for g in mapgroups.groups_of(w.data)], ["Towns", "Underground"])
      self.assertEqual(mapgroups.find(w.data, ("Underground",))["maps"], ["meadow", "cave"])
      self.assertIsNone(self.project.validate())
      doc = self.project.add_map("route1", group=("Towns",))
      self.assertEqual(mapgroups.group_of(w.data, "route1"), ("Towns",))
      with self.assertRaises(DocumentError):
         self.project.add_map("route2", group=("Nowhere",))
      self.assertIsNotNone(doc)
      with w.edit("Ungroup"):
         mapgroups.move_map(w, "route1", None)
      self.assertIsNone(mapgroups.group_of(w.data, "route1"))
      self.assertIsNone(self.project.validate())


class ImportTests(WorldTestCase):
   """!Importing maps and tilesets from another world."""

   def test_import_into_new_world(self) -> None:
      """!A map comes with its tilesets, sheet images, behaviors and vehicle
      classes; importing again reuses identical tilesets and renames the map.
      @return None
      """
      p = Project.create(self.dir / "fresh" / "world.json", "fresh")
      report = p.import_from(self.dir / "world.json", maps=["showcase"])
      self.assertIn("map showcase", report[0])
      self.assertEqual(sorted(p.tileset_names()), ["outdoor", "showcase"])
      self.assertEqual(p.world.data["start"]["map"], "showcase")
      self.assertIn("swim", field_rules.mode_names(p.world))   # the water behavior needs it
      swim = p.world.data["vehicle_classes"][field_rules.mode_names(p.world).index("swim")]
      self.assertFalse(swim["can_run"])   # with the source's definition (E8 vehicle class settings)
      self.assertTrue({"water", "ice", "ledge_down", "push_right"} <= set(p.behavior_names()))
      self.assertIsNone(p.validate())
      p.save_all()
      self.assertTrue((self.dir / "fresh/tilesets/sheets/keyed.png").is_file())
      again = Project.open(self.dir / "fresh" / "world.json")
      self.assertIsNone(again.validate())
      report = again.import_from(self.dir / "world.json", maps=["showcase"])
      self.assertEqual(sorted(again.map_names()), ["showcase", "showcase_2"])
      self.assertEqual(sorted(again.tileset_names()), ["outdoor", "showcase"])   # identical: reused
      self.assertTrue(any("reused" in line for line in report))
      # The source's map groups come along.
      src = Project.open(self.dir / "world.json")
      with src.world.edit("Group"):
         mapgroups.add_group(src.world, (), "Demo")
         mapgroups.add_group(src.world, ("Demo",), "Inner")
         mapgroups.move_map(src.world, "cave", ("Demo", "Inner"))
      src.save_all()
      again.import_from(self.dir / "world.json", maps=["cave"])
      self.assertEqual(mapgroups.group_of(again.world.data, "cave"), ("Demo", "Inner"))
      self.assertIsNone(again.validate())

   def test_clashing_tileset_is_renamed(self) -> None:
      """!A different tileset of the same name is imported under a new name
      and the imported map follows it.
      @return None
      """
      p = Project.create(self.dir / "other" / "world.json", "other")
      ts = p.add_tileset("outdoor")
      with ts.edit("Sheet"):
         ts.data["sheets"].append({"name": "s", "palette": ["#ffffff"], "size": [8, 8], "shapes": []})
      p.import_from(self.dir / "world.json", maps=["meadow"])
      self.assertIn("outdoor_2", p.tileset_names())
      names = p.map("meadow").data["metatiles"]
      self.assertTrue(names and all(n.startswith("outdoor_2/") for n in names))
      self.assertEqual(maps.tilesets_of(p.map("meadow").data), ["outdoor_2"])
      self.assertIsNone(p.validate())
      with self.assertRaises(DocumentError):
         self.project.import_from(self.dir / "world.json", maps=["cave"])   # the world already open
      with self.assertRaises(DocumentError):
         p.import_from(self.dir / "world.json", maps=["nowhere"])


class TilesetEditTests(WorldTestCase):
   """!Sheets and metatiles."""

   def test_import_sheet_and_metatiles(self) -> None:
      """!A PNG sheet gets metatiles per non-empty block; they compile.
      @return None
      """
      bm = engine.bitmap()
      px = bytearray(32 * 16 * 4)
      for y in range(16):
         for x in range(16):   # left 16x16 block red, right block empty
            px[(y * 32 + x) * 4:(y * 32 + x) * 4 + 4] = bytes((255, 0, 0, 255))
      doc = self.project.tileset("cave")
      with doc.edit("Import"):
         name = tilesets.add_image_sheet(doc, "art", (32, 16, px))
      sheet = tilesets.compile_sheet(self.project, "cave", name)
      with doc.edit("Metatiles"):
         added = tilesets.metatiles_from_sheet(doc, name, sheet)
      self.assertEqual(added, ["art_0_0"])
      self.assertEqual(tilesets.metatile(doc, "art_0_0"),
                       {"name": "art_0_0", "tiles": ["art:0", "art:1", "art:4", "art:5"]})
      self.assertIsNone(self.project.validate())
      self.project.save_all()
      self.assertTrue((self.dir / "tilesets" / "sheets" / "art.png").exists())
      self.assertEqual(bm.read_png(self.dir / "tilesets" / "sheets" / "art.png")[:2], (32, 16))

   def test_metatile_edits(self) -> None:
      """!Tiles and refs (metatiles are graphics only).
      @return None
      """
      doc = self.project.tileset("outdoor")
      with doc.edit("Edit"):
         tilesets.set_tile(doc, "grass", 3, tilesets.ref("terrain", 5, hflip=True))
         added = tilesets.add_metatile(doc, "grass", [None] * 4)
      self.assertEqual(tilesets.metatile(doc, "grass")["tiles"][3], "terrain:5h")
      self.assertEqual(added, "grass_2")
      self.assertEqual(set(tilesets.metatile(doc, added)), {"name", "tiles"})
      self.assertEqual(tilesets.parse("terrain:5hv"), ("terrain", 5, True, True))
      with self.assertRaises(ValueError):
         tilesets.set_tile(doc, "grass", 4, None)
      self.assertIsNone(self.project.validate())


class MetatileBlockTests(WorldTestCase):
   """!Placing blocks of sheet tiles into metatiles (the metatile maker)."""

   def test_blocks_and_placing(self) -> None:
      """!Blocks read row by row, flipped blocks mirror as a whole, placing
      clips to the 2x2 metatile, flips toggle per tile.
      @return None
      """
      self.assertEqual(tilesets.block("s", 8, 3, 2, 2), [["s:3", "s:4"], ["s:11", "s:12"]])
      self.assertEqual(tilesets.block("s", 8, 3, 2, 1, hflip=True), [["s:4h", "s:3h"]])
      self.assertEqual(tilesets.block("s", 8, 3, 1, 2, vflip=True), [["s:11v"], ["s:3v"]])
      with self.assertRaises(ValueError):
         tilesets.block("s", 8, 0, 3, 1)
      doc = self.project.tileset("outdoor")
      with doc.edit("New"):
         name = tilesets.add_metatile(doc, "made", [None] * 4)
         changed = tilesets.place(doc, name, 0, tilesets.block("terrain", 16, 0, 2, 2))
      self.assertEqual(sorted(changed), [0, 1, 2, 3])
      self.assertEqual(tilesets.metatile(doc, name)["tiles"], ["terrain:0", "terrain:1", "terrain:16", "terrain:17"])
      with doc.edit("Corner"):
         changed = tilesets.place(doc, name, 3, tilesets.block("terrain", 16, 5, 2, 2))   # only the top-left lands
      self.assertEqual(changed, [3])
      self.assertEqual(tilesets.metatile(doc, name)["tiles"][3], "terrain:5")
      with doc.edit("Flip"):
         self.assertTrue(tilesets.toggle_flip(doc, name, 3, "h"))
         tilesets.toggle_flip(doc, name, 3, "v")
         tilesets.place(doc, name, 1, [[None]])
         self.assertFalse(tilesets.toggle_flip(doc, name, 1, "h"))
      self.assertEqual(tilesets.metatile(doc, name)["tiles"], ["terrain:0", None, "terrain:16", "terrain:5hv"])
      self.assertIsNone(self.project.validate())


class TransparentColorTests(WorldTestCase):
   """!Image sheets' transparent color."""

   def test_transparent_color(self) -> None:
      """!Set, picked from the source image, compiled, cleared; shape sheets refuse it.
      @return None
      """
      bm = engine.bitmap()
      px = bytearray()
      for y in range(8):
         for x in range(16):
            px += bytes((255, 0, 255, 255) if x < 8 else (0, 160, 0, 255))
      doc = self.project.tileset("outdoor")
      with doc.edit("Import"):
         name = tilesets.add_image_sheet(doc, "keyed", (16, 8, bytes(px)))
      self.assertEqual(tilesets.source_color(doc, name, 2, 3), "#ff00ff")   # unsaved import: read from memory
      self.assertIsNone(tilesets.source_color(doc, name, 99, 0))
      with doc.edit("Key"):
         tilesets.set_transparent(doc, name, "#FF00FF")
      self.assertEqual(tilesets.sheet(doc, name)["transparent"], "#ff00ff")
      ts, _, error = self.project.compiled_tileset("outdoor")
      self.assertIsNone(error)
      self.assertEqual(ts.palettes[f"outdoor/{name}"][1], 1)                # the key color took no entry
      with self.assertRaises(ValueError):
         tilesets.set_transparent(doc, name, "pink")
      with self.assertRaisesRegex(ValueError, "only image sheets"):
         tilesets.set_transparent(doc, "terrain", "#000000")
      with doc.edit("Clear"):
         tilesets.set_transparent(doc, name, None)
      self.assertNotIn("transparent", tilesets.sheet(doc, name))
      self.project.save_all()
      self.assertEqual(bm.read_png(self.dir / "tilesets" / tilesets.sheet(doc, name)["image"])[0], 16)


class WorldCliTests(WorldTestCase):
   """!The world / map / tileset commands."""

   def run_cli(self, *argv: object) -> tuple[int, str]:
      """!Runs a command.
      @param argv  arguments
      @return (status, output)
      """
      out = io.StringIO()
      with redirect_stdout(out):
         status = cli([str(a) for a in argv])
      return status, out.getvalue()

   def test_commands(self) -> None:
      """!validate, paint, cells, layers, render, tileset render.
      @return None
      """
      w = self.dir / "world.json"
      self.assertEqual(self.run_cli("world", "validate", w)[0], 0)
      self.assertEqual(self.run_cli("map", w, "cave", "paint", "cave/dirt", 0, 0, 2, 1)[0], 0)
      status, out = self.run_cli("map", w, "cave", "cells", 0, 0, 2, 1, "--collision", "1", "--behavior", "ice",
                                 "--encounter", "yes")
      self.assertEqual(status, 0, out)
      doc = Project.open(w).map("cave")
      a = maps.unpack(maps.get(doc.data, 2, 1))
      self.assertEqual((a["collision"], a["encounter"]), (1, True))
      self.assertEqual(maps.behavior_name(doc.data, maps.get(doc.data, 2, 1)), "ice")
      status, _ = self.run_cli("world", "render", w, "cave", self.dir / "cave.png", "--collision")
      self.assertEqual(status, 0)
      self.assertEqual(engine.bitmap().read_png(self.dir / "cave.png")[:2], ((16 + 4) * 16 + 32 * 0, 20 * 16))
      self.assertEqual(self.run_cli("tileset", w, "cave", "render", self.dir / "t.png")[0], 0)
      self.assertEqual(self.run_cli("map", w, "cave", "paint", "cave/missing", 0, 0)[0], 1)
      # Layers.
      self.assertEqual(self.run_cli("map", w, "cave", "layer-add", 1, "--purpose", "canopy")[0], 0)
      self.assertEqual(self.run_cli("map", w, "cave", "paint", "cave/crystal", 0, 0, "--bg", 1)[0], 0)
      status, out = self.run_cli("map", w, "cave", "layers")
      self.assertEqual(out.split("\n")[:2], ["BG2 terrain (priority 2)", "BG1 canopy (priority 1)"])
      self.assertEqual(self.run_cli("map", w, "cave", "paint", "cave/crystal", 0, 0, "--bg", 3)[0], 1)  # no BG3
      self.assertEqual(self.run_cli("map", w, "cave", "layer-set", 1, "--to-bg", 0, "--priority", 0)[0], 0)
      self.assertEqual(self.run_cli("map", w, "cave", "clear", 0, 0, "--bg", 0)[0], 0)
      self.assertEqual(self.run_cli("map", w, "cave", "layer-remove", 0)[0], 0)
      self.assertEqual(len(maps.layers_of(Project.open(w).map("cave").data)), 1)
      # Blank maps and map tilesets.
      self.assertEqual(self.run_cli("map", w, "empty", "new", "--tilesets", "cave", "--layers", "2:1", "0:0:canopy")[0],
                       0)
      self.assertEqual([ly["bg"] for ly in Project.open(w).map("empty").data["layers"]], [2, 0])
      self.assertEqual(self.run_cli("map", w, "empty", "paint", "outdoor/grass", 0, 0)[0], 1)   # not its tileset
      status, out = self.run_cli("map", w, "empty", "tilesets", "outdoor", "cave")
      self.assertEqual(status, 0, out)
      self.assertEqual(self.run_cli("map", w, "empty", "paint", "outdoor/grass", 0, 0)[0], 0)
      self.assertEqual(self.run_cli("map", w, "empty", "border", 2, 1, "outdoor/grass", "blank")[0], 0)
      self.assertEqual(maps.border_of(Project.open(w).map("empty").data)[2], [[0, None], [None, None]])
      # Transparent color of an image sheet.
      png = self.dir / "keyed.png"
      engine.bitmap().write_png(png, 8, 8, bytes((255, 0, 255, 255)) * 64)
      self.assertEqual(self.run_cli("tileset", w, "cave", "import-sheet", png, "--transparent", "#ff00ff")[0], 0)
      self.assertEqual(tilesets.sheet(Project.open(w).tileset("cave"), "keyed")["transparent"], "#ff00ff")
      self.assertEqual(self.run_cli("tileset", w, "cave", "transparent", "keyed", "none")[0], 0)
      self.assertNotIn("transparent", tilesets.sheet(Project.open(w).tileset("cave"), "keyed"))

   def test_group_commands(self) -> None:
      """!world groups / group-add / group-move / group-rename / group-remove, map new --group.
      @return None
      """
      w = self.dir / "world.json"
      for argv in (("world", "group-add", w, "Outside"), ("world", "group-add", w, "Outside/Towns"),
                   ("world", "group-move", w, "meadow", "Outside/Towns"), ("map", w, "route", "new", "--group",
                                                                            "Outside")):
         status, out = self.run_cli(*argv)
         self.assertEqual(status, 0, out)
      status, out = self.run_cli("world", "groups", w)
      self.assertEqual(out.split("\n")[:4], ["Outside/", "  Towns/", "    meadow", "  route"])
      self.assertEqual(self.run_cli("world", "group-move", w, "meadow", "Nowhere")[0], 1)
      self.assertEqual(self.run_cli("world", "group-rename", w, "Outside", "Overworld")[0], 0)
      self.assertEqual(self.run_cli("world", "group-remove", w, "Overworld")[0], 0)
      status, out = self.run_cli("world", "groups", w)
      self.assertEqual(out.split("\n")[:2], ["Towns/", "  meadow"])
      self.assertEqual(self.run_cli("world", "validate", w)[0], 0)

   def test_import_command(self) -> None:
      """!world import, with and without --dry-run.
      @return None
      """
      target = self.dir / "t" / "world.json"
      self.assertEqual(self.run_cli("world", "new", target)[0], 0)
      status, out = self.run_cli("world", "import", target, self.dir / "world.json", "--maps", "cave", "--dry-run")
      self.assertEqual(status, 0, out)
      self.assertIn("map cave: imported as cave", out)
      self.assertEqual(Project.open(target).map_names(), [])
      status, out = self.run_cli("world", "import", target, self.dir / "world.json", "--maps", "cave")
      self.assertEqual(status, 0, out)
      self.assertEqual(Project.open(target).map_names(), ["cave"])
      self.assertEqual(self.run_cli("world", "validate", target)[0], 0)


if __name__ == "__main__":
   unittest.main()
