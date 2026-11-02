#!/usr/bin/env python3
"""!doors and overrides without Qt: door assets and bindings (core.doors), cell override sets (core.override_sets,
the overrides extension), direction-grid sprites (core.sprite_grid, core.indexed_png), the draw order rule
(core.draw_order), tile animation targets (core.tilesets), the override statement's words (core.script_words), the
importer's handling of persisted sets, and their commands.

Uses the engine's map sandbox (copied with the Starter beside it): its hut door (door:HUT, bound by the metatile
hut_door), the override set garden (persisted by the flag garden_planted), the NPC / GUARD grid sprites (three and
four columns) and the outdoor tileset's flowers animation (four targets).
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import (doors, draw_order, engine, events, indexed_png, override_sets,  # noqa: E402
                                 script_words, sprite_grid, tilesets)
from capsule_studio.core.document import Document  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402
from capsule_studio.plugins import MapView, loader  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402

## The sandbox's hut door, its anchor cell on the showcase and the showcase warp that leads into the hut.
HUT, HUT_CELL, HUT_WARP = "door:HUT", (27, 20), 2
## The sandbox's override set and its flag.
GARDEN, GARDEN_FLAG = "garden", "garden_planted"
## Frame size of the grid sprites made here (an NPC's).
FRAME_W, FRAME_H = 16, 32
## Palette of the grid sheets made here (r, g, b per entry; entry 0 transparent).
PLTE = bytes([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255])


class D30World(unittest.TestCase):
   """!Base: a copy of the sandbox per test."""

   def setUp(self) -> None:
      """!Copies the sandbox world and the battle data it names.
      @return None
      """
      ## Temporary root.
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_doors_overrides_")), ["sandbox_map"])
      ## The copy's data folder.
      self.data = self.root / "sandbox_map" / "data"
      ## The opened world.
      self.project = Project.open(self.data / "world.json")
      ## The asset manifest.
      self.assets = Document.open(self.data / "assets.json")

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


class DoorTests(D30World):
   """!Door assets, their previews and the world's bindings."""

   def test_sandbox_door(self) -> None:
      """!The hut door compiles, is bound by its metatile, and draws on its map cell in the map's colours.
      @return None
      """
      r = doors.compiled(self.assets, HUT)
      self.assertTrue(r.ok, r.error)
      c = r.compiled
      self.assertEqual((c["width"], c["height"], c["frames"], c["frame_tiles"]), (1, 2, 3, 8))
      self.assertEqual(c["load_at"], doors.limits()["map_tiles"] - c["frame_tiles"])   # "end"
      a = self.assets.get(HUT)
      self.assertTrue(doors.is_reverse(a))
      self.assertEqual(doors.steps(a, "close"), list(reversed(doors.steps(a, "open"))))
      self.assertEqual(len(doors.timeline(a, "open")), sum(t for _f, t in doors.steps(a, "open")))
      self.assertEqual(doors.bound_cells(self.project, "showcase", HUT),
                       [(*HUT_CELL, HUT, "metatile outdoor/hut_door")])
      self.assertEqual(doors.find_anchor(self.project, HUT)[:3], ("showcase", *HUT_CELL))
      self.assertIn(HUT, doors.door_keys(self.project))
      closed = doors.render_on_map(self.project, "showcase", *HUT_CELL, c, doors.closed_word())
      opened = doors.render_on_map(self.project, "showcase", *HUT_CELL, c, c["frames"] - 1)
      margin = doors.PREVIEW_MARGIN
      self.assertEqual(closed[:2], ((1 + 2 * margin) * 16, (2 + 2 * margin) * 16))
      self.assertNotEqual(closed[2], opened[2])   # the open frame shows
      alone = doors.render_alone(c, 0)
      self.assertEqual(alone[:2], (16, 32))
      # the frame drawn on the map replaces exactly the door's layers of its cells
      ov = doors.overrides_for(c, 0, *HUT_CELL, 2)
      self.assertEqual(sorted(ov), [(27, 19, 0), (27, 20, 0)])
      self.assertEqual(doors.overrides_for(c, doors.closed_word(), *HUT_CELL, 2), {})

   def test_edit_door(self) -> None:
      """!A new door compiles; size, layers, show, entries, steps and fields are checked by the engine.
      @return None
      """
      doc = self.assets
      with doc.edit("New door"):
         doors.new_door(doc, "door:TEST", 2, 1)
      self.assertTrue(doors.compiled(doc, "door:TEST").ok)
      with doc.edit("Cells"):
         doors.set_cells(doc, "door:TEST", 2, 2)
      a = doc.get("door:TEST")
      # the old bottom row stays the bottom row (the anchor's)
      self.assertEqual(a["entries"][2], [[{"tile": 0}, {"tile": 1}, {"tile": 2}, {"tile": 3}]])
      with doc.edit("Layers"):
         doors.set_layers(doc, "door:TEST", 2)
      self.assertEqual(a["entries"][0][1], [0, 0, 0, 0])
      with doc.edit("Entry"):
         doors.set_entry(doc, "door:TEST", 0, 1, 0, doors.parse_entry("t3 p1 hv"))
      self.assertEqual(a["entries"][0][1][0], {"tile": 3, "palette": 1, "flip": "hv"})
      self.assertEqual(doors.entry_text(a["entries"][0][1][0]), "t3 p1 hv")
      self.assertEqual(doors.parse_entry("0x1004"), 0x1004)
      with self.assertRaises(ValueError):   # the engine refuses a tile past the frame's
         with doc.edit("Entry"):
            doors.set_entry(doc, "door:TEST", 0, 0, 0, {"tile": 99})
      a = doc.get("door:TEST")   # a refused edit puts the manifest back as a copy
      with doc.edit("Steps"):
         doors.set_steps(doc, "door:TEST", "close", [[2, 3], [doors.closed_word(), 2]])
      self.assertFalse(doors.is_reverse(a))
      with doc.edit("Reverse"):
         doors.set_steps(doc, "door:TEST", "close", doors.reverse_word())
      self.assertNotIn("close", a)
      with self.assertRaises(ValueError):   # ticks 1-255
         with doc.edit("Steps"):
            doors.set_steps(doc, "door:TEST", "open", [[0, 0]])
      a = doc.get("door:TEST")
      with doc.edit("Fields"):
         doors.set_fields(doc, "door:TEST", exit="up", sounds={"open": "sound:DOOR", "close": None}, load_at=100)
      self.assertEqual((a["exit"], a["sounds"], a["load_at"]), ("up", {"open": "sound:DOOR"}, 100))
      with doc.edit("Default exit"):
         doors.set_fields(doc, "door:TEST", exit="down", load_at=doors.load_end_word())
      self.assertNotIn("exit", a)
      self.assertNotIn("load_at", a)
      with doc.edit("Override"):
         doors.set_show(doc, "door:TEST", "override")
      self.assertEqual(len(a["frames"]), doors.NEW_FRAMES)
      self.assertTrue(doors.compiled(doc, "door:TEST").ok)
      shown = doors.lines(doc, "door:TEST")
      warned = [line for line in shown if "warning:" in line]   # sound:DOOR is no sound of the sandbox
      self.assertEqual(len(warned), 1, warned)
      self.assertEqual(len(shown) - len(warned), 4 + doors.NEW_FRAMES * 4 * 2)

   def test_sheet_image(self) -> None:
      """!An indexed sheet is copied beside the manifest; its tiles are read as the compiler reads them.
      @return None
      """
      png = self.root / "sheet.png"
      png.write_bytes(indexed_png.encode(16, 96, bytes([1, 2] * (16 * 48)), PLTE))
      doc = self.assets
      with doc.edit("Sheet"):
         rel = doors.set_sheet_image(doc, HUT, png)
      self.assertTrue((self.data / rel).is_file())
      across, tiles = doors.sheet_tiles(doc, doc.get(HUT))
      self.assertEqual((across, len(tiles)), (2, 24))
      c = doors.compiled(doc, HUT).compiled
      self.assertEqual(doors.frame_tiles_of(c, 0)[0][0], [1, 2] * 4)

   def test_bindings(self) -> None:
      """!Bindings by metatile are checked by the engine; a warp's door binds its own cell first.
      @return None
      """
      w = self.project.world
      with w.edit("Binding"):
         i = doors.add_binding(w, "*", "flowers", HUT)
      with self.assertRaises(ValueError):
         with w.edit("Binding"):
            doors.add_binding(w, "outdoor", "flowers", "HUT")   # not a door key
      with w.edit("Binding"):
         doors.set_binding(w, i, metatile="flowers_b")
      self.assertEqual(doors.bindings(w)[i]["metatile"], "flowers_b")
      sc = self.project.map("showcase")
      with sc.edit("Door warp"):
         events.set_event(sc, "warps", HUT_WARP, door=HUT)
      self.assertIn("door door:HUT", events.describe("warps", events.events(sc, "warps")[HUT_WARP]))
      cells = doors.bound_cells(self.project, "showcase", HUT)
      warp_at = events.events(sc, "warps")[HUT_WARP]["at"]
      self.assertEqual(cells[0], (warp_at[0], warp_at[1], HUT, f"warp {HUT_WARP}"))
      with self.assertRaises(Exception):
         with sc.edit("Door warp"):
            events.set_event(sc, "warps", HUT_WARP, door="HUT")
      with w.edit("Binding"):
         doors.remove_binding(w, i)
      self.assertIsNone(self.project.validate())


class OverrideSetTests(D30World):
   """!Override sets: names, cells, persistence, scripts, previews, the extension and importing."""

   def test_sandbox_set(self) -> None:
      """!The garden set: its persistence, its script uses, and its cells drawn applied and cleared.
      @return None
      """
      doc = self.project.map("showcase")
      self.assertEqual(override_sets.set_names(doc), [GARDEN])
      self.assertEqual(override_sets.persistence(override_sets.find(doc, GARDEN)),
                       (override_sets.PERSIST_FLAG, GARDEN_FLAG, None))
      self.assertEqual(override_sets.world_names(self.project), {GARDEN: "showcase"})
      self.assertTrue(override_sets.script_uses(self.project, GARDEN))
      self.assertEqual(override_sets.persist_problems(self.project, "showcase"), [])
      applied = override_sets.render(self.project, "showcase", GARDEN, True)
      cleared = override_sets.render(self.project, "showcase", GARDEN, False)
      self.assertEqual(applied[:2], cleared[:2])
      self.assertNotEqual(applied[2], cleared[2])
      self.assertEqual(override_sets.diagnostics(self.project), [])

   def test_edit_sets(self) -> None:
      """!Adding, painting, erasing, persistence, renaming (scripts follow) and removing (refused while used).
      @return None
      """
      p = self.project
      doc = p.map("showcase")
      with doc.edit("Add"):
         override_sets.add_set(p, "showcase", "pond", [10, 10], 0, "outdoor/flowers")
      with self.assertRaises(ValueError):   # names are unique in the world
         with doc.edit("Add"):
            override_sets.add_set(p, "showcase", GARDEN, [10, 10])
      with doc.edit("Paint"):
         self.assertEqual(override_sets.paint(doc, "pond", [[11, 10], [10, 10]], 0, None), 2)
      self.assertEqual(len(override_sets.cells(doc, "pond")), 2)   # 10,10 repainted in place
      self.assertIsNone(override_sets.cells(doc, "pond")[0]["metatile"])
      with doc.edit("Entries"):
         override_sets.paint(doc, "pond", [[12, 10]], 0, entries=[1, 2, 3, 4])
      self.assertIsNone(override_sets.check(p, "showcase"))
      with doc.edit("Erase"):
         self.assertEqual(override_sets.erase(doc, "pond", [[12, 10]], 0), 1)
      with self.assertRaises(ValueError):   # a variable's value is not 0
         with doc.edit("Persist"):
            override_sets.set_persist(doc, "pond", override_sets.PERSIST_VAR, "welcomed", 0)
      with doc.edit("Persist"):
         override_sets.set_persist(doc, "pond", override_sets.PERSIST_VAR, "welcomed", 1)
      self.assertEqual(override_sets.persist_problems(p, "showcase"), [])
      with doc.edit("Persist"):
         override_sets.set_persist(doc, "pond", override_sets.PERSIST_FLAG, "no_such_flag")
      self.assertIn("no_such_flag", override_sets.persist_problems(p, "showcase")[0])
      with doc.edit("Persist"):
         override_sets.set_persist(doc, "pond", override_sets.PERSIST_NONE)
      # outside the map's chunks: the engine refuses it
      with doc.edit("Paint far"):
         override_sets.paint(doc, "pond", [[999, 999]], 0, None)
      self.assertIn("outside the map's chunks", override_sets.check(p, "showcase"))
      doc.undo()
      self.assertIsNone(override_sets.check(p, "showcase"))
      with self.assertRaises(ValueError):   # the scripts name it
         with doc.edit("Remove"):
            override_sets.remove_set(p, "showcase", GARDEN)
      changed = override_sets.rename_set(p, "showcase", GARDEN, "flower_bed")
      self.assertEqual(len(changed), 1)
      text = Path(changed[0]).read_text(encoding="utf-8")
      self.assertIn("override apply flower_bed;", text)
      self.assertNotIn("override apply garden;", text)
      p.save_all()
      self.assertIsNone(p.validate())
      with doc.edit("Remove"):
         override_sets.remove_set(p, "showcase", "pond")
      self.assertEqual(override_sets.set_names(doc), ["flower_bed"])

   def test_import_sets(self) -> None:
      """!Importing keeps sets whose names this world declares, numbers clashing set names, drops the others.
      @return None
      """
      known = {"flags": [GARDEN_FLAG], "vars": {}}
      data = {"override_sets": [{"name": GARDEN, "persist": {"flag": GARDEN_FLAG}, "cells": []},
                                {"name": "other", "persist": {"var": "v", "value": 1}, "cells": []},
                                {"name": "plain", "cells": []}]}
      gone, renamed = override_sets.import_sets(data, known, {GARDEN})
      self.assertEqual(gone, 1)
      self.assertEqual([s["name"] for s in data["override_sets"]], ["garden_2", "plain"])
      self.assertEqual(len(renamed), 1)
      data = {"override_sets": [{"name": GARDEN, "persist": {"flag": GARDEN_FLAG}, "cells": []}]}
      self.assertEqual(override_sets.import_sets(data, None, set()), (1, []))
      self.assertNotIn("override_sets", data)

   def test_extension(self) -> None:
      """!The map tool paints the panel's choice; the overlay and hover text show the cells; the commands work.
      @return None
      """
      reg = loader.builtin_registry()
      tool = next(t for t in reg.map_tools() if t.id.endswith("overrides"))
      maptools = sys.modules[type(tool).__module__]   # the module the plugin host loaded (its SELECTION)
      view = MapView(self.project, "showcase")
      maptools.choose("showcase", GARDEN, 0, "outdoor/flowers_d")
      tool.apply(view, [(31, 23)])
      doc = self.project.map("showcase")
      self.assertEqual(override_sets.cells(doc, GARDEN)[-1], {"cell": [31, 23], "layer": 0,
                                                               "metatile": "outdoor/flowers_d"})
      tool.action = "erase"
      tool.apply(view, [(31, 23)])
      self.assertEqual(len(override_sets.cells(doc, GARDEN)), 3)
      overlay = next(o for o in reg.map_overlays() if o.id.endswith("overrides"))
      cell = overlay.prepare(view)
      self.assertEqual(cell(28, 23, 0), (maptools.CHOSEN_COLOR, maptools.LETTER))
      self.assertEqual(cell(0, 0, 0), (None, None))
      self.assertIn("override set garden", maptools.hover_text(view, 28, 23, None))
      world = self.data / "world.json"
      status, out = self.run_cli("overrides", "list", world)
      self.assertEqual(status, 0, out)
      self.assertIn("garden: 3 cell(s), while flag garden_planted is set", out)
      status, out = self.run_cli("overrides", "add", world, "showcase", "pond", "10,10", "--metatile",
                                 "outdoor/flowers")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("overrides", "paint", world, "showcase", "pond", "0", "11,10", "12,10")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("overrides", "persist", world, "showcase", "pond", "var", "welcomed", "--value", "1")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("overrides", "persist", world, "showcase", "pond", "flag", "nope")
      self.assertEqual(status, 1, out)
      png = self.root / "pond.png"
      status, out = self.run_cli("overrides", "render", world, "showcase", "pond", png, "--cleared")
      self.assertEqual(status, 0, out)
      self.assertTrue(png.is_file())
      status, out = self.run_cli("overrides", "remove", world, "showcase", GARDEN)
      self.assertEqual(status, 1, out)   # the scripts name it
      status, out = self.run_cli("overrides", "uses", world, "showcase", GARDEN)
      self.assertIn("sandbox.cscript", out)
      self.assertIsNone(Project.open(world).validate())


class GridTests(D30World):
   """!Direction-grid sprites: frame-object grids (the sandbox's) and indexed sheet grids (made here)."""

   def test_sandbox_grids(self) -> None:
      """!NPC has three columns (right mirrors left), GUARD four; the walk of each direction; the ROM saved.
      @return None
      """
      npc, guard = self.assets.get("sprite:NPC"), self.assets.get("sprite:GUARD")
      self.assertTrue(sprite_grid.is_grid(npc))
      self.assertTrue(sprite_grid.right_mirrors_left(npc))
      self.assertFalse(sprite_grid.right_mirrors_left(guard))
      r = self.assets.compile_asset(npc)
      self.assertGreater(sprite_grid.saved(r), 0)
      self.assertEqual(sprite_grid.expansion(npc)[:4], [(0, d) for d in sprite_grid.directions()])
      walk = sprite_grid.timeline(r.compiled, sprite_grid.compiled_index(npc, 1, "right"))
      self.assertTrue(all(flip == sprite_grid.FLIP_H for _f, flip in walk))   # right: the left one mirrored
      left = sprite_grid.timeline(r.compiled, sprite_grid.compiled_index(npc, 1, "left"))
      self.assertEqual([f for f, _fl in walk], [f for f, _fl in left])
      cells, error = sprite_grid.cell_frames(self.assets, "sprite:NPC")
      self.assertIsNone(error)
      self.assertEqual(cells["frames"], len(sprite_grid.rows(npc)) * sprite_grid.columns(npc))
      a = sprite_grid.frame_image(cells, sprite_grid.mirrored_from(), False)
      b = sprite_grid.frame_image(cells, sprite_grid.mirrored_from(), True)
      self.assertEqual(a[:2], (FRAME_W, FRAME_H))
      self.assertNotEqual(a[2], b[2])

   def test_frame_object_edits(self) -> None:
      """!Mirror off adds a right column of mirrored shapes; rows and animations follow renames and removals.
      @return None
      """
      doc = self.assets
      key = "sprite:NPC"
      with doc.edit("Mirror"):
         self.assertEqual(sprite_grid.set_right_mirrors_left(doc, key, False), 0)
      self.assertEqual(sprite_grid.columns(doc.get(key)), len(sprite_grid.directions()))
      with doc.edit("Mirror"):
         self.assertEqual(sprite_grid.set_right_mirrors_left(doc, key, True), len(sprite_grid.rows(doc.get(key))))
      with doc.edit("Rows"):
         sprite_grid.add_row(doc, key, "step_b", "step")
         sprite_grid.rename_row(doc, key, "step", "step_a")
      a = doc.get(key)
      self.assertEqual(sprite_grid.rows(a), ["stand", "step_a", "step_b"])
      self.assertEqual(sprite_grid.animations(a)[1]["rows"], ["step_a", "stand"])
      with doc.edit("Anim"):
         i = sprite_grid.add_animation(doc, key, ["step_a", "stand", "step_b", "stand"], durations=[4, 4, 4, 4],
                                       direction="up")
      self.assertEqual(sprite_grid.expansion(doc.get(key))[-1], (i, "up"))
      with doc.edit("Anim"):
         sprite_grid.set_animation(doc, key, i, period=6, direction=None)
      self.assertNotIn("durations", sprite_grid.animations(doc.get(key))[i])
      with self.assertRaises(ValueError):   # animation 0 shows only stand
         with doc.edit("Rows"):
            sprite_grid.remove_row(doc, key, "stand")
      with doc.edit("Rows"):
         sprite_grid.move_row(doc, key, "step_b", -1)
         sprite_grid.remove_row(doc, key, "step_b")
      self.assertEqual(sprite_grid.rows(doc.get(key)), ["stand", "step_a"])
      with doc.edit("New"):
         sprite_grid.new_grid(doc, "sprite:NEW", FRAME_W, FRAME_H)
      self.assertTrue(doc.compile_asset(doc.get("sprite:NEW")).ok)

   def test_sheet_grid(self) -> None:
      """!An indexed sheet grid: toggling the right column and editing rows rewrite its PNG, indices kept.
      @return None
      """
      rows = 3
      cols = sprite_grid.mirrored_columns()
      w, h = FRAME_W * cols, FRAME_H * rows
      # each frame filled with its own index pattern: column c index c + 1, the left column asymmetric
      px = bytearray(w * h)
      for y in range(h):
         for x in range(w):
            c = x // FRAME_W
            px[y * w + x] = (c + 1) if c != sprite_grid.mirrored_from() or x % FRAME_W < FRAME_W // 2 else 0
      (self.data / "frames").mkdir(exist_ok=True)
      (self.data / "frames" / "grid.png").write_bytes(indexed_png.encode(w, h, px, PLTE))
      doc = self.assets
      key = "sprite:SHEET"
      with doc.edit("Add"):
         doc.add_asset({"key": key, "kind": "sprite", "width": FRAME_W, "height": FRAME_H,
                        "palette": ["#ff0000", "#00ff00", "#0000ff"], "layout": sprite_grid.layout_word(),
                        "rows": ["a", "b", "c"], "grid": {"image": "frames/grid.png", "indexed": True},
                        "animations": [{"rows": ["a", "b"], "period": 8}]})
      self.assertTrue(doc.compile_asset(doc.get(key)).ok)
      with doc.edit("Mirror off"):
         sprite_grid.set_right_mirrors_left(doc, key, False)
      a = doc.get(key)
      self.assertEqual(a["columns"], len(sprite_grid.directions()))
      sw, sh, spx = indexed_png.read(self.data / a["grid"]["image"])
      self.assertEqual((sw, sh), (FRAME_W * len(sprite_grid.directions()), h))
      right = [spx[y * sw + FRAME_W * cols:y * sw + FRAME_W * (cols + 1)] for y in range(FRAME_H)]
      left = [spx[y * sw + FRAME_W * sprite_grid.mirrored_from():y * sw + FRAME_W * (sprite_grid.mirrored_from() + 1)]
              for y in range(FRAME_H)]
      self.assertEqual(right, [line[::-1] for line in left])   # the new right column: the left one mirrored
      self.assertEqual(indexed_png.palette_chunks(self.data / a["grid"]["image"])[0], PLTE)
      with doc.edit("Mirror on"):
         self.assertEqual(sprite_grid.set_right_mirrors_left(doc, key, True), 0)
      with doc.edit("Rows"):
         sprite_grid.add_row(doc, key, "d", "a")
         sprite_grid.remove_row(doc, key, "c")
      sw, sh, _px = indexed_png.read(self.data / doc.get(key)["grid"]["image"])
      self.assertEqual((sw, sh), (FRAME_W * cols, FRAME_H * rows))
      self.assertTrue(doc.compile_asset(doc.get(key)).ok)
      self.assertIn("ROM saved", "\n".join(sprite_grid.lines(doc, key)))


class DrawOrderTests(D30World):
   """!The draw order rule and the sub-priority the engine computes."""

   def test_rule(self) -> None:
      """!Defaults, fields left out when default, the engine's checks, the formula and the sort.
      @return None
      """
      w = self.project.world
      self.assertFalse(draw_order.is_set(w))
      r = draw_order.rule(w)
      self.assertEqual(r, draw_order.defaults())
      # lower on screen in front: a larger bottom edge gives a smaller sub-priority
      self.assertLess(draw_order.sub_priority(r, 112, 3), draw_order.sub_priority(r, 96, 3))
      # the engine's formula: base + (rows - ((bottom + bias) & (wrap - 1)) / row_pixels) * row_step + add
      for bottom in (0, 40, 96, 159, 300):
         expect = (r["elevation_base"][3] + (r["rows"] - ((bottom + r["bias"]) & (r["wrap"] - 1)) //
                                             r["row_pixels"]) * r["row_step"] + r["add"]) & draw_order.SUB_MASK
         self.assertEqual(draw_order.sub_priority(r, bottom, 3), expect)
      with w.edit("Rule"):
         draw_order.set_field(w, "row_step", 3)
         draw_order.set_base(w, 4, 50)
      self.assertEqual(w.data["draw_order"], {"row_step": 3, "elevation_base": [0] * 4 + [50] + [0] * 11})
      with self.assertRaises(ValueError):   # a power of two
         with w.edit("Rule"):
            draw_order.set_field(w, "wrap", 100)
      with w.edit("Rule"):
         draw_order.set_field(w, "row_step", draw_order.defaults()["row_step"])
      self.assertEqual(list(w.data["draw_order"]), ["elevation_base"])
      a = draw_order.Sprite("a", 96, 3, 2)
      b = draw_order.Sprite("b", 96, 4, 2)
      self.assertEqual([s.name for s in draw_order.order(draw_order.rule(w), [b, a])], ["a", "b"])   # base 50
      with w.edit("Reset"):
         draw_order.reset(w)
      self.assertFalse(draw_order.is_set(w))
      self.assertIsNone(self.project.validate())
      status, out = self.run_cli("draw-order", self.data / "world.json", "preview", "96:3", "112:3")
      self.assertEqual(status, 0, out)
      self.assertTrue(out.startswith("front: sprite 1"), out)


class TargetTests(D30World):
   """!Tile animation targets in the sandbox's outdoor tileset."""

   def test_targets(self) -> None:
      """!The flowers' targets, their frames over time, edits checked by the engine, back to one target.
      @return None
      """
      p = self.project
      doc = p.tileset("outdoor")
      names = [an.get("name") for an in tilesets.animations(doc)]
      i = names.index("flowers")
      items = tilesets.targets(tilesets.animations(doc)[i])
      self.assertEqual([t.get("offset", 0) for t in items], [0, 1, 2, 3])
      ts = p.compiled_tilesets(["outdoor"])[0]["outdoor"]
      self.assertGreater(tilesets.target_saved(ts), 0)
      period = tilesets.animations(doc)[i].get("period")
      t0, t1 = tilesets.target_frames(ts, i, 0), tilesets.target_frames(ts, i, period)
      self.assertEqual([(f + 1) % len(t0) for f in t0], t1)
      self.assertEqual(tilesets.target_picture(ts, i, 0, [0] * 15)[:2], (8, 8))
      p.edit_tileset("outdoor", "Offset", lambda d: tilesets.set_target(d, i, 1, offset=3))
      self.assertIsNone(p.validate())
      with self.assertRaises(Exception):   # overlapping targets
         p.edit_tileset("outdoor", "Overlap", lambda d: tilesets.set_target(d, i, 1, tiles=items[0]["tiles"]))
         raise AssertionError(p.validate())
      w = names.index("water")
      p.edit_tileset("outdoor", "Use targets", lambda d: tilesets.use_targets(d, w))
      self.assertEqual(len(tilesets.targets(tilesets.animations(doc)[w])), 1)
      p.edit_tileset("outdoor", "Single", lambda d: tilesets.set_targets(d, w, None))
      self.assertEqual(tilesets.targets(tilesets.animations(doc)[w]), [])
      status, out = self.run_cli("tileset", self.data / "world.json", "outdoor", "targets", i, "--at-frame", "0")
      self.assertEqual(status, 0, out)
      self.assertIn("target 3", out)


class ScriptWordTests(D30World):
   """!The override statement in the script editor's words."""

   def test_override_words(self) -> None:
      """!Kinds and the world's set names complete; the template compiles against the sandbox's world.
      @return None
      """
      self.assertEqual(script_words.statement_kinds()["override"], ["apply", "clear"])
      names = {script_words.OVERRIDE_NAMES: [GARDEN]}
      self.assertEqual(script_words.completions("script x { override ", names), ["apply", "clear"])
      self.assertEqual(script_words.completions("script x { override apply ", names), [GARDEN])
      sc = script_words.compiler()
      manifest = self.data / "scripts" / "scripts.json"
      comp = sc.compile_file(manifest)
      template = script_words.STATEMENT_TEMPLATES["override"].replace(script_words.WORLD_TEMPLATES["override"],
                                                                      GARDEN)
      m = json.loads(manifest.read_text(encoding="utf-8"))
      src = manifest.parent / m["sources"][0]
      text = src.read_text(encoding="utf-8") + f"\nscript doors_template {{\n    {template}\n}}\n"
      src.write_text(text, encoding="utf-8")
      comp = sc.compile_file(manifest)
      self.assertEqual([d.message for d in comp.diags if d.severity == "error"], [])
      from capsule_studio.core import scripts
      result = scripts.ScriptProject.open(manifest).check()
      self.assertIn(GARDEN, script_words.check_names(result)[script_words.OVERRIDE_NAMES])


class CommandTests(D30World):
   """!The door, door-binding and sprite grid commands."""

   def test_door_commands(self) -> None:
      """!door new / cells / layers / entry / steps / set / render; door-binding list / add / cells.
      @return None
      """
      m, world = self.data / "assets.json", self.data / "world.json"
      for args in (("new", "door:CLI", "--cells", "1x2"), ("cells", "door:CLI", "2x2"), ("layers", "door:CLI", "2"),
                   ("entry", "door:CLI", "0", "1", "0", "t1 p2 h"), ("steps", "door:CLI", "close", "closed:2", "2:3"),
                   ("set", "door:CLI", "--exit", "up", "--open-sound", "sound:SE"),
                   ("show-as", "door:CLI", "override")):
         status, out = self.run_cli("door", m, *args)
         self.assertEqual(status, 0, (args, out))
      status, out = self.run_cli("door", m, "steps", "door:CLI", "open", "0:0")
      self.assertEqual(status, 1, out)
      status, out = self.run_cli("door", m, "list")
      self.assertIn("door:CLI: 2x2 cells, override, 2 layer(s)", out)
      png = self.root / "hut.png"
      status, out = self.run_cli("door", m, "render", HUT, png, "--frame", "2", "--world", world, "--map", "showcase")
      self.assertEqual(status, 0, out)
      self.assertEqual(engine.bitmap().read_png(png)[:2], (48, 64))
      status, out = self.run_cli("door-binding", world, "list")
      self.assertIn("outdoor/hut_door -> door:HUT", out)
      self.assertIn("door:CLI", out)   # the asset manifest beside the world
      status, out = self.run_cli("door-binding", world, "add", "*", "flowers", "door:CLI")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("door-binding", world, "cells", "showcase", "--door", HUT)
      self.assertIn("27,20: door:HUT", out)
      status, out = self.run_cli("events", "set", world, "showcase", "warp", HUT_WARP, "--door", HUT)
      self.assertEqual(status, 0, out)

   def test_grid_commands(self) -> None:
      """!sprite grid show / mirror / row / anim-add / anim-set / walk / sheet / new.
      @return None
      """
      m = self.data / "assets.json"
      status, out = self.run_cli("sprite", "grid", m, "sprite:NPC", "show")
      self.assertIn("right (= left mirrored)", out)
      for args in (("mirror", "off"), ("row", "add", "step_b"), ("row", "rename", "step", "step_a"),
                   ("anim-add", "step_a,stand", "--period", "6", "--direction", "up"),
                   ("anim-set", "3", "--durations", "4,4"), ("mirror", "on")):
         status, out = self.run_cli("sprite", "grid", m, "sprite:NPC", *args)
         self.assertEqual(status, 0, (args, out))
      status, out = self.run_cli("sprite", "grid", m, "sprite:NPC", "walk", "1")
      self.assertTrue(out.startswith("down:"), out)
      png = self.root / "npc.png"
      status, out = self.run_cli("sprite", "grid", m, "sprite:NPC", "sheet", png)
      self.assertEqual(engine.bitmap().read_png(png)[:2], (FRAME_W * len(sprite_grid.directions()), FRAME_H * 3))
      status, out = self.run_cli("sprite", "grid", m, "sprite:CLI", "new", "--rows", "stand,walk")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("sprite", "grid", m, "sprite:WALKER", "show")
      self.assertEqual(status, 1, out)   # not a grid


if __name__ == "__main__":
   unittest.main()
