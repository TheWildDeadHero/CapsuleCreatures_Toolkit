#!/usr/bin/env python3
"""!Tests for map objects (capsule_studio.core.objects) and the studio's
objects extension: its commands, map tool, overlay, hover text, validator and
the importer (no Qt needed).

Uses the engine's map sandbox world (copied, with the Starter sample its world
names beside it, as in the engine's layout): the showcase's guide, stroller, sentry,
rival, gatekeeper, jogger (a move route), chest (a self switch page),
quaker, lookout and puddle (a touch trigger).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.core import objects  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.plugins import MapView, loader  # noqa: E402
from test_events import EventWorld  # noqa: E402


class CoreTests(EventWorld):
   """!core.objects on the sandbox world."""

   def test_read(self) -> None:
      """!Objects by local ID, cell and name; descriptions; sight lines; the world compiles.
      @return None
      """
      doc = self.project.map("showcase")
      self.assertEqual([o["name"] for o in objects.objects(doc)],
                       ["guide", "stroller", "sentry", "rival", "gatekeeper", "jogger", "chest", "quaker",
                        "lookout", "puddle", "bush", "porter", "keeper"])
      # F2: the bush the clear action removes; DS1: the porter (a 3-column grid) and keeper (4 columns)
      self.assertEqual(objects.object_at(doc, 25, 9)[0], 3)
      self.assertIsNone(objects.object_at(doc, 0, 0))
      self.assertEqual(objects.index_of(doc, "sentry"), 2)
      with self.assertRaises(DocumentError):
         objects.index_of(doc, "nobody")
      rival = objects.objects(doc)[3]
      self.assertIn("spotter, sight 4 until beat_rival", objects.describe(rival))
      self.assertEqual(objects.sight_cells(rival), [(24, 9), (23, 9), (22, 9), (21, 9)])
      self.assertEqual(objects.describe_page(rival["pages"][0]), "when beat_rival: script rival_after")
      self.assertEqual(objects.describe_page(objects.pages(doc, 6)[0]), "when self A: facing up, script chest_empty")
      self.assertIn("wander 2x1", objects.describe(objects.objects(doc)[1]))
      self.assertIn("speed 3; frequency 5; route of 4 step(s)", objects.describe(objects.objects(doc)[5]))
      self.assertIn("options through; trigger player_touch", objects.describe(objects.objects(doc)[9]))
      self.assertIsNone(objects.check(self.project))
      self.assertEqual([d for d in objects.diagnostics(self.project) if d.level == "error"], [])

   def test_edit_and_check(self) -> None:
      """!Add, set (tidying), rename, move, pages, remove; the compiler's errors come through.
      @return None
      """
      doc = self.project.map("meadow")
      with doc.edit("Add"):
         i = objects.add_object(doc, 2, 2)
      o = objects.objects(doc)[i]
      self.assertEqual(o, {"name": "npc_1", "at": [2, 2], "sprite": objects.DEFAULT_SPRITE})
      self.assertIsNone(objects.check(self.project))
      with doc.edit("Set"):
         objects.set_object(doc, i, movement="wander", range=[2, 3], script="stroller_talk", sight=3,
                            until="beat_rival", facing="left")
      self.assertEqual(o["spotter"], {"sight": 3, "until": "beat_rival"})
      self.assertEqual(o["range"], [2, 3])
      with doc.edit("Set"):
         objects.set_object(doc, i, movement="static", sight=0, facing="down")
      self.assertNotIn("range", o)       # static has no range
      self.assertNotIn("spotter", o)     # no sight: no spotter, and no until flag
      self.assertNotIn("movement", o)    # static is the default
      self.assertNotIn("facing", o)
      # I3: a range goes up to the engine's object_compiler.MAX_RANGE (15)
      for bad in ({"movement": "schedule"}, {"range": [objects.max_range() + 1, 0]}, {"sprite": "WALKER"},
                  {"facing": "north"},
                  {"sight": 9}, {"color": 1}, {"sprite": None}):
         with self.assertRaises(DocumentError, msg=bad), doc.edit("Bad"):
            objects.set_object(doc, i, **bad)
      with doc.edit("Rename"):
         objects.rename_object(doc, i, "farmer")
      with self.assertRaises(DocumentError), doc.edit("Rename"):
         objects.rename_object(doc, i, "2bad")
      with doc.edit("Add"):
         j = objects.add_object(doc, 3, 2, "cow")
      with self.assertRaises(DocumentError), doc.edit("Rename"):
         objects.rename_object(doc, j, "farmer")
      with self.assertRaises(DocumentError), doc.edit("Add"):
         objects.add_object(doc, 4, 2, "cow")
      with doc.edit("Move"):
         objects.move_object(doc, j, 5, 2)
      self.assertEqual(objects.objects(doc)[j]["at"], [5, 2])
      # Pages.
      with doc.edit("Page"):
         k = objects.add_page(doc, i, {"flag": "gate_open"}, script="guide_talk")
      with self.assertRaises(DocumentError), doc.edit("Page"):
         objects.add_page(doc, i, {}, script="guide_talk")   # no condition
      with self.assertRaises(DocumentError), doc.edit("Page"):
         objects.add_page(doc, i, {"self": "E"}, hidden=True)
      with doc.edit("Page"):
         objects.set_page(doc, i, k, facing="up", script=None)
      self.assertEqual(objects.pages(doc, i)[k], {"when": {"flag": "gate_open"}, "facing": "up"})
      self.assertIsNone(objects.check(self.project))
      with doc.edit("Page"):
         objects.set_page(doc, i, k, when={"flag": None, "var": "welcomed", "value": 1, "equal": True,
                                           "self": ["B", "A"]})
      self.assertEqual(objects.pages(doc, i)[k]["when"], {"var": "welcomed", "value": 1, "equal": True,
                                                          "self": ["A", "B"]})
      self.assertIsNone(objects.check(self.project))
      with self.assertRaises(DocumentError), doc.edit("Page"):
         objects.set_page(doc, i, k, when={"var": None, "self": None})   # nothing left to wait for
      with doc.edit("Page"):
         j2 = objects.add_page(doc, i, {"self": "A"}, hidden=True)
      with doc.edit("Page"):
         objects.set_page(doc, i, j2, script="guide_talk")   # a field shows the object again
      self.assertNotIn("hidden", objects.pages(doc, i)[j2])
      with doc.edit("Page"):
         objects.set_page(doc, i, j2, hidden=True)            # hidden pages hold nothing else
      self.assertEqual(objects.pages(doc, i)[j2], {"when": {"self": "A"}, "hidden": True})
      with doc.edit("Page"):
         objects.move_page(doc, i, j2, 0)
      self.assertTrue(objects.pages(doc, i)[0]["hidden"])
      with doc.edit("Page"):
         objects.remove_page(doc, i, 0)
      with doc.edit("Page"):
         objects.set_page(doc, i, k, when={"var": None, "flag": "nope"})
      self.assertIn("unknown flag 'nope'", objects.check(self.project))
      errs = [d for d in objects.diagnostics(self.project, "meadow") if d.level == "error"]
      self.assertEqual(len(errs), 1)
      with doc.edit("Page"):
         objects.remove_page(doc, i, k)
      self.assertNotIn("pages", objects.objects(doc)[i])
      # Removing shifts later local IDs.
      with doc.edit("Remove"):
         shifted = objects.remove_object(doc, i)
      self.assertEqual(shifted, ["cow"])
      self.assertEqual(objects.objects(doc)[0]["name"], "cow")
      # Two objects on one cell is the compiler's error.
      with doc.edit("Add"):
         objects.add_object(doc, 5, 2, "calf")
      self.assertIn("stands on 5,2", objects.check(self.project))
      doc.undo()
      self.assertIsNone(objects.check(self.project))

   def test_motion_trigger_route(self) -> None:
      """!Speed, frequency, options, trigger and self switches (defaults left out); move routes on objects
      and pages, checked with the engine's route compiler.
      @return None
      """
      doc = self.project.map("meadow")
      with doc.edit("Add"):
         i = objects.add_object(doc, 2, 2, speed=4, frequency=1, trigger="player_touch", script="stroller_talk",
                                self_switches=True, options={"through": True, "walk_anim": True})
      o = objects.objects(doc)[i]
      self.assertEqual(o["options"], {"through": True})   # walk_anim on is the default
      self.assertEqual((o["speed"], o["frequency"], o["trigger"], o["self_switches"]),
                       (4, 1, "player_touch", True))
      self.assertIsNone(objects.check(self.project))
      with doc.edit("Set"):
         objects.set_object(doc, i, speed=2, frequency=3, trigger="action", self_switches=False)
      for k in ("speed", "frequency", "trigger", "self_switches"):
         self.assertNotIn(k, o)
      with doc.edit("Option"):
         objects.set_option(doc, i, "through", None)
         objects.set_option(doc, i, "walk_anim", False)
      self.assertEqual(o["options"], {"walk_anim": False})
      for bad in ({"speed": 5}, {"frequency": 0}, {"trigger": "touch"}, {"options": {"fly": True}},
                  {"self_switches": "yes"}, {"route": {"steps": ["moonwalk"]}}):
         with self.assertRaises(DocumentError, msg=bad), doc.edit("Bad"):
            objects.set_object(doc, i, **bad)
      with doc.edit("Autorun"):
         objects.set_object(doc, i, trigger="autorun", script=None)
      self.assertIn("autorun objects need a script", objects.check(self.project))
      doc.undo()
      o = objects.objects(doc)[i]   # undo restores a copy
      # Routes: custom movement; text one step per line; repeat and skip.
      with doc.edit("Route"):
         objects.set_route(doc, i, "left 2\n\n# back\nwait 30\nright 2", repeat=False, skip=True)
      self.assertEqual(o["movement"], "custom")
      self.assertEqual(o["route"], {"steps": ["left 2", "wait 30", "right 2"], "repeat": False, "skip": True})
      self.assertIsNone(objects.check(self.project))
      self.assertEqual(objects.route_error(["face up"]), "a repeating route needs a step that takes time "
                                                         "(a move, jump or wait)")
      self.assertIn("unknown flag", objects.route_error(["set nope", "wait 1"], flags=["gate_open"]))
      self.assertIsNone(objects.route_error(["set gate_open", "wait 1"], flags=["gate_open"]))
      with self.assertRaises(DocumentError), doc.edit("Route"):
         objects.set_route(doc, i, ["jump 9 0"])
      o = objects.objects(doc)[i]   # a refused edit restores a copy
      with doc.edit("Route"):
         objects.set_route(doc, i, ["set nope", "wait 1"])
      self.assertIn("unknown flag 'nope'", objects.check(self.project))   # flags are the build's to check
      with doc.edit("Static"):
         objects.set_object(doc, i, movement="static")
      self.assertNotIn("route", o)
      with doc.edit("Custom"):
         objects.set_object(doc, i, movement="custom")
      self.assertEqual(o["route"], objects.DEFAULT_ROUTE)
      with doc.edit("No route"):
         objects.set_route(doc, i, None)
      self.assertNotIn("movement", o)
      # Pages replace motion, options, trigger and the route (its movement becomes custom).
      with doc.edit("Page"):
         k = objects.add_page(doc, i, {"flag": "gate_open"}, speed=1, trigger="action", options={})
      with doc.edit("Page route"):
         objects.set_route(doc, i, ["up", "down"], page=k)
      with doc.edit("Page option"):
         objects.set_option(doc, i, "on_top", True, page=k)
      pg = objects.pages(doc, i)[k]
      self.assertEqual(pg["movement"], "custom")
      self.assertEqual(pg["options"], {"on_top": True})
      self.assertIn("route of 2 step(s)", objects.describe_page(pg))
      self.assertIsNone(objects.check(self.project))
      with doc.edit("Page movement"):
         objects.set_page(doc, i, k, movement="wander")
      self.assertNotIn("route", pg)

   def test_limit(self) -> None:
      """!At most 15 objects per map (I3: without an object view; the engine's object_compiler.MAX_OBJECTS).
      @return None
      """
      doc = self.project.map("meadow")
      with doc.edit("Many"):
         for k in range(objects.max_objects(doc)):
            objects.add_object(doc, k % 8, k // 8)
      with self.assertRaises(DocumentError), doc.edit("One more"):
         objects.add_object(doc, 7, 7)

   def test_diagnostics(self) -> None:
      """!Collision, missing sprites (with the game's assets known) and warps are reported.
      @return None
      """
      game = self.root / "sandbox_map"
      (game / "reference").mkdir()
      (game / "reference" / "project.json").write_text(json.dumps(
         {"schema": "capsule.project/1", "name": "t", "assets": "data/assets.json", "maps": "data/world.json"}))
      p = self.reopen()
      doc = p.map("showcase")
      self.assertIn("sprite:NPC", objects.game_sprites(p))
      with doc.edit("Set"):
         objects.set_object(doc, 0, sprite="sprite:Ghost")
      found = objects.diagnostics(p, "showcase")
      self.assertTrue(any("no sprite:Ghost" in d.message for d in found), found)
      self.assertTrue(any(d.level == "info" and "gatekeeper" in d.message and "warp" in d.message for d in found))
      with doc.edit("Move"):
         objects.move_object(doc, 0, 3, 1)   # a collision cell of the plaza wall
      self.assertTrue(any("collision" in d.message for d in objects.diagnostics(p, "showcase")))
      self.assertTrue(any("still solid" in d.message for d in found))
      gatekeeper = next(i for i, o in enumerate(objects.objects(doc)) if o.get("name") == "gatekeeper")
      with doc.edit("Through"):
         objects.set_option(doc, 0, "through", True)   # walked through: neither solid nor hiding a warp
         objects.set_option(doc, gatekeeper, "through", True)
      through = objects.diagnostics(p, "showcase")
      self.assertTrue(any("no sprite:Ghost" in d.message and "passes through" in d.message for d in through))
      self.assertFalse(any("gatekeeper" in d.message and "warp" in d.message for d in through))

   def test_import(self) -> None:
      """!Objects naming scripts or flags the target lacks are left out.
      @return None
      """
      data = {"objects": [{"name": "a", "at": [0, 0], "sprite": "sprite:X"},
                          {"name": "b", "at": [1, 0], "sprite": "sprite:X", "script": "nope"},
                          {"name": "c", "at": [2, 0], "sprite": "sprite:X", "spotter": {"sight": 2, "until": "f"}},
                          {"name": "d", "at": [3, 0], "sprite": "sprite:X",
                           "overrides": [{"flag": "f", "facing": "up"}, {"flag": "g", "script": "s"}]},
                          {"name": "e", "at": [4, 0], "sprite": "sprite:X", "pages": [{"when": {"var": "v"},
                                                                                       "hidden": True}]},
                          {"name": "r", "at": [5, 0], "sprite": "sprite:X", "movement": "custom",
                           "route": {"steps": ["set g", "wait 1"]}}]}
      known = {"scripts": ["s"], "flags": ["f"], "vars": {}}
      self.assertEqual(objects.import_objects(data, known), 4)
      self.assertEqual([o["name"] for o in data["objects"]], ["a", "c"])
      # Old overrides become pages: the first override that held applied, the last page that holds does.
      o = {"name": "d", "overrides": [{"flag": "f", "facing": "up"}, {"flag": "g", "script": "s"}],
           "pages": [{"when": {"self": "A"}, "hidden": True}]}
      self.assertEqual(objects.pages_from_overrides(o), 2)
      self.assertEqual(o["pages"], [{"when": {"self": "A"}, "hidden": True},
                                    {"when": {"flag": "g"}, "script": "s"},
                                    {"when": {"flag": "f"}, "facing": "up"}])
      self.assertNotIn("overrides", o)
      data = {"objects": [{"name": "d", "at": [3, 0], "sprite": "sprite:X", "overrides": [{"flag": "f"}]},
                          {"name": "a", "at": [0, 0], "sprite": "sprite:X"}]}
      self.assertEqual(objects.import_objects(data, known), 0)
      self.assertEqual(data["objects"][0]["pages"], [{"when": {"flag": "f"}}])
      self.assertEqual(objects.import_objects(data, None), 1)   # no scripts manifest: only plain objects stay
      self.assertEqual([o["name"] for o in data["objects"]], ["a"])


class ExtensionTests(EventWorld):
   """!The extension: map tool, overlay, hover text, validator, commands."""

   def test_tool_overlay_hover(self) -> None:
      """!Place, move and remove with the Objects tool; the overlay and hover text show objects.
      @return None
      """
      reg = loader.builtin_registry()
      self.assertIn("objects", [p.panel_id for p in reg.panels("object-editor")])
      tool = next(t for t in reg.map_tools() if t.id.endswith("objects"))
      view = MapView(self.project, "meadow")
      tool.action = "place"
      tool.apply(view, [(4, 4)])
      doc = self.project.map("meadow")
      self.assertEqual(objects.objects(doc)[0]["at"], [4, 4])
      tool.action = "move"
      tool.apply(view, [(5, 4)])
      self.assertEqual(objects.objects(doc)[0]["at"], [5, 4])
      overlay = next(o for o in reg.map_overlays() if o.id.endswith("objects"))
      cell = overlay.prepare(MapView(self.project, "showcase"))
      self.assertEqual(cell(2, 5, 0)[1], "O>")    # the guide, facing right
      self.assertEqual(cell(25, 9, 0)[1], "S<")   # the spotter ("rival"), facing left
      self.assertIsNotNone(cell(22, 9, 0)[0])     # its sight line
      self.assertIsNone(cell(20, 9, 0)[0])
      hover = list(reg.hover_texts())
      self.assertTrue(any("object 0 npc_1" in (fn(view, 5, 4, 0) or "") for fn in hover))
      tool.action = "remove"
      tool.apply(view, [(5, 4)])
      self.assertEqual(objects.objects(doc), [])
      found = reg.validate(self.project, None)
      self.assertFalse(any(d.level == "error" for d in found), found)

   def test_commands(self) -> None:
      """!show, add, set, move, rename, pages, routes, options, check, remove.
      @return None
      """
      w = self.world
      status, out = self.run_cli("objects", "show", w, "--map", "showcase")
      self.assertEqual(status, 0, out)
      self.assertIn("object 3 rival at 25,9", out)
      self.assertIn("page 0: when beat_rival: script rival_after", out)
      self.assertIn("route: right 6; down 2; left 6; up 2", out)
      status, out = self.run_cli("objects", "add", w, "meadow", "3", "2", "--name", "farmer",
                                 "--sprite", "sprite:NPC", "--movement", "wander", "--range", "2,1")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("objects", "set", w, "meadow", "farmer", "--script", "stroller_talk",
                                 "--sight", "2", "--until", "beat_rival")
      self.assertEqual(status, 0, out)
      self.assertIn("spotter, sight 2", out)
      status, out = self.run_cli("objects", "set", w, "meadow", "0", "--script", "nope")
      self.assertEqual(status, 1)
      self.assertIn("unknown script", out)
      status, out = self.run_cli("objects", "set", w, "meadow", "0", "--range", "9")
      self.assertEqual(status, 1)
      status, out = self.run_cli("objects", "move", w, "meadow", "farmer", "4", "2")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("objects", "rename", w, "meadow", "0", "grower")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("objects", "page-add", w, "meadow", "grower", "--when-flag", "gate_open",
                                 "--movement", "static")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("objects", "page-set", w, "meadow", "grower", "0", "--facing", "up",
                                 "--when-self", "a,c")
      self.assertEqual(status, 0, out)
      self.assertIn("when gate_open, self A+C: movement static, facing up", out)
      status, out = self.run_cli("objects", "page-add", w, "meadow", "grower", "--when-var", "welcomed",
                                 "--when-value", "1", "--when-equal", "on", "--hidden", "on")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("objects", "page-move", w, "meadow", "grower", "1", "0")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("objects", "set", w, "meadow", "grower", "--speed", "3", "--trigger",
                                 "event_touch", "--self-switches", "on")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("objects", "route-set", w, "meadow", "grower", "left 2", "wait 30", "right 2",
                                 "--once")
      self.assertEqual(status, 0, out)
      self.assertIn("route: left 2; wait 30; right 2 (once)", out)
      status, out = self.run_cli("objects", "route-set", w, "meadow", "grower", "fly")
      self.assertEqual(status, 1)
      self.assertIn("unknown step 'fly'", out)
      status, out = self.run_cli("objects", "route-set", w, "meadow", "grower", "up", "down", "--page", "1")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("objects", "option", w, "meadow", "grower", "through", "on")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("objects", "check", w)
      self.assertEqual(status, 0, out)
      p = self.reopen()
      o = objects.objects(p.map("meadow"))[0]
      self.assertEqual(o["name"], "grower")
      self.assertEqual(o["at"], [4, 2])
      self.assertEqual(o["pages"], [{"when": {"var": "welcomed", "value": 1, "equal": True}, "hidden": True},
                                    {"when": {"flag": "gate_open", "self": ["A", "C"]}, "movement": "custom",
                                     "facing": "up", "route": {"steps": ["up", "down"]}}])
      self.assertEqual((o["speed"], o["trigger"], o["self_switches"], o["options"]),
                       (3, "event_touch", True, {"through": True}))
      self.assertEqual(o["route"], {"steps": ["left 2", "wait 30", "right 2"], "repeat": False})
      status, out = self.run_cli("objects", "route-clear", w, "meadow", "grower")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("objects", "page-remove", w, "meadow", "grower", "0")
      self.assertEqual(status, 0, out)
      self.assertNotIn("route", objects.objects(self.reopen().map("meadow"))[0])
      status, out = self.run_cli("objects", "remove", w, "showcase", "guide")
      self.assertEqual(status, 0, out)
      self.assertIn("local IDs 1-12 moved down by one (stroller, sentry, rival, gatekeeper, jogger, chest, "
                    "quaker, lookout, puddle, bush, porter, keeper)", out)   # DS1: porter and keeper


if __name__ == "__main__":
   unittest.main()
