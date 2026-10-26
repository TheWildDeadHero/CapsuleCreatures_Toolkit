#!/usr/bin/env python3
"""!Tests for locations (capsule_studio.core.locations, D-17), the studio's
locations extension (commands, validator, hover text), warp transitions
(core.events) and importing maps with their locations (no Qt needed).

Uses the engine's map sandbox world (copied, with the Starter sample its world
names beside it): its park, meadow and cave locations, the box and sign banner
styles and the cave's first-visit preview.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.core import events, locations  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402
from capsule_studio.plugins import MapView, loader  # noqa: E402
from test_events import EventWorld  # noqa: E402


class CoreTests(EventWorld):
   """!core.locations on the sandbox world."""

   def test_read(self) -> None:
      """!The world's transition, styles, locations, previews and map locations; the world compiles.
      @return None
      """
      p = self.project
      self.assertEqual(locations.transition(p), "fade")
      self.assertEqual(list(locations.styles(p)), ["box", "sign"])
      self.assertIn("frame banners/sign.png", locations.describe_style(locations.styles(p)["sign"]))
      self.assertIn("plain box", locations.describe_style(locations.styles(p)["box"]))
      self.assertEqual(list(locations.locations(p)), ["park", "meadow", "cave"])
      self.assertEqual(locations.describe(locations.location(p, "cave")),
                       "'Echo Cave'; banner box; preview (first, 1 sequence(s))")
      self.assertEqual(locations.describe_entry(locations.sequences(p, "cave")[0]), "sequences/cave_preview.json")
      self.assertEqual(locations.map_location(p.map("showcase")), "park")
      self.assertEqual(locations.maps_of(p, "cave"), ["cave"])
      with self.assertRaises(DocumentError):
         locations.location(p, "moon")
      self.assertIsNone(locations.check(p))
      self.assertEqual([d for d in locations.diagnostics(p) if d.level != "info"], [])

   def test_edit_and_check(self) -> None:
      """!Transition, styles, locations, previews and map locations; the compiler's errors come through.
      @return None
      """
      p = self.project
      w = p.world
      with w.edit("Transition"):
         locations.set_transition(p, "mosaic")
      self.assertEqual(w.data["transition"], "mosaic")
      with self.assertRaises(DocumentError), w.edit("Transition"):
         locations.set_transition(p, "spin")
      with w.edit("Transition"):
         locations.set_transition(p, None)
      self.assertNotIn("transition", w.data)
      # Styles.
      with w.edit("Style"):
         locations.add_style(p, "night", ink="#FFFFFF", fill="#102040", frames=90)
      self.assertEqual(locations.styles(p)["night"], {"ink": "#ffffff", "fill": "#102040", "frames": 90})
      for bad in ({"ink": "white"}, {"frames": 0}, {"slide": 65}, {"glow": 1}):
         with self.assertRaises(DocumentError, msg=bad), w.edit("Bad"):
            locations.set_style(p, "night", **bad)
      with self.assertRaises(DocumentError), w.edit("Again"):
         locations.add_style(p, "box")
      with w.edit("Frame"):
         locations.set_style(p, "night", frame=self.world.parent / "banners" / "sign.png", ink=None)
      self.assertEqual(locations.styles(p)["night"]["frame"], "banners/sign.png")   # relative to the world
      self.assertNotIn("ink", locations.styles(p)["night"])
      self.assertIsNone(locations.check(p))
      # Locations.
      with w.edit("Location"):
         locations.add_location(p, "lake", "Quiet Lake", "night")
      with self.assertRaises(DocumentError), w.edit("Long"):
         locations.add_location(p, "far", "A" * (locations.MAX_NAME + 1))
      with self.assertRaises(DocumentError), w.edit("Style"):
         locations.set_location(p, "lake", banner="neon")
      with w.edit("Rename style"):
         locations.rename_style(p, "night", "dusk")
      self.assertEqual(locations.location(p, "lake")["banner"], "dusk")
      with self.assertRaises(DocumentError), w.edit("Remove style"):
         locations.remove_style(p, "dusk")   # the lake uses it
      with w.edit("No banner"):
         locations.set_location(p, "lake", name="Still Lake", banner=None)
      self.assertEqual(locations.location(p, "lake"), {"name": "Still Lake"})
      with w.edit("Remove style"):
         locations.remove_style(p, "dusk")
      # Previews: night entries need the world's encounter condition.
      with w.edit("Preview"):
         j = locations.add_sequence(p, "lake", "sequences/cave_preview.json")
         locations.add_sequence(p, "lake", "sequences/cave_preview.json", when=["night"])
         locations.set_preview(p, "lake", "first")
      self.assertEqual(j, 0)
      self.assertEqual(locations.location(p, "lake")["preview"],
                       {"sequences": [{"sequence": "sequences/cave_preview.json"},
                                      {"when": ["night"], "sequence": "sequences/cave_preview.json"}],
                        "show": "first"})
      with self.assertRaises(DocumentError), w.edit("Bad condition"):
         locations.set_sequence(p, "lake", 1, when=["dawn"])
      with w.edit("Preview"):
         locations.set_sequence(p, "lake", 1, when=None)
      self.assertNotIn("when", locations.sequences(p, "lake")[1])
      self.assertIsNone(locations.check(p))
      with w.edit("Missing sequence"):
         locations.set_sequence(p, "lake", 0, sequence="sequences/none.json")
      self.assertIn("cannot read", locations.check(p))
      self.assertTrue(any(d.level == "error" for d in locations.diagnostics(p)))
      with w.edit("Preview"):
         locations.remove_sequence(p, "lake", 0)
         locations.remove_sequence(p, "lake", 0)
      self.assertNotIn("preview", locations.location(p, "lake"))
      self.assertIn("location 'lake' has no maps", [d.message for d in locations.diagnostics(p)])
      # Maps, renames and removals follow into the map files.
      doc = p.map("meadow")
      with doc.edit("Location"):
         locations.set_map_location(p, doc, "lake")
      with self.assertRaises(DocumentError), doc.edit("Location"):
         locations.set_map_location(p, doc, "moon")
      locations.rename_location(p, "lake", "pond")
      self.assertEqual(locations.map_location(doc), "pond")
      self.assertEqual(doc.undo_label(), "Rename location")
      self.assertIsNone(p.validate())
      self.assertEqual(locations.remove_location(p, "pond"), ["meadow"])
      self.assertIsNone(locations.map_location(doc))
      self.assertIn("map meadow: in no location", " ".join(d.message for d in locations.diagnostics(p)))
      self.assertIsNone(p.validate())
      # A map naming a location the world lacks is the compiler's error.
      with doc.edit("Broken"):
         doc.data["location"] = "moon"
      self.assertIn("unknown location 'moon'", locations.check(p))

   def test_warp_transition(self) -> None:
      """!A warp's transition (core.events): set, described, checked, removed.
      @return None
      """
      doc = self.project.map("showcase")
      self.assertIn("transition", events.FIELDS["warps"])
      self.assertEqual(events.events(doc, "warps")[0]["transition"], "mosaic")
      self.assertEqual(events.describe("warp", events.events(doc, "warps")[0]), "warp to cave #0, mosaic")
      with doc.edit("Transition"):
         events.set_event(doc, "warps", 0, transition="box")
      self.assertIsNone(events.check(self.project))
      with self.assertRaises(DocumentError), doc.edit("Bad"):
         events.set_event(doc, "warps", 0, transition="spin")
      with doc.edit("Default"):
         events.set_event(doc, "warps", 0, transition=None)
      self.assertNotIn("transition", events.events(doc, "warps")[0])
      with doc.edit("Add"):
         i = events.add_event(doc, "warp", 3, 3, to="cave", transition="white")
      self.assertEqual(events.events(doc, "warps")[i]["transition"], "white")


class ExtensionTests(EventWorld):
   """!The extension: commands, validator, hover text; the events commands' --transition; the importer."""

   def test_registered(self) -> None:
      """!The Locations tab, hover text and validator are registered.
      @return None
      """
      reg = loader.builtin_registry()
      self.assertIn("locations", [p.panel_id for p in reg.panels("location-editor")])
      view = MapView(self.project, "cave")
      self.assertTrue(any((fn(view, 1, 1, 0) or "") == "location cave" for fn in reg.hover_texts()))
      found = reg.validate(self.project, None)
      self.assertFalse(any(d.level == "error" for d in found), found)

   def test_commands(self) -> None:
      """!show, transition, styles, locations, previews, map, check, rename, remove.
      @return None
      """
      w = self.world
      status, out = self.run_cli("locations", "show", w)
      self.assertEqual(status, 0, out)
      self.assertIn("transition: fade", out)
      self.assertIn("location cave: 'Echo Cave'; banner box; preview (first, 1 sequence(s)); maps: cave", out)
      self.assertIn("  preview 0: sequences/cave_preview.json", out)
      status, out = self.run_cli("locations", "transition", w, "wipe_v")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("locations", "transition", w, "spin")
      self.assertEqual(status, 1)
      status, out = self.run_cli("locations", "style-add", w, "night", "--fill", "#102040", "--slide", "4")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("locations", "style-set", w, "night", "--slide", "-", "--rename", "dusk")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("locations", "add", w, "lake", "--name", "Quiet Lake", "--banner", "dusk")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("locations", "preview-add", w, "lake", "sequences/cave_preview.json",
                                 "--when", "night", "--show", "first")
      self.assertEqual(status, 0, out)
      self.assertIn("lake preview 0: sequences/cave_preview.json when night", out)
      status, out = self.run_cli("locations", "preview-set", w, "lake", "0", "--when", "-")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("locations", "map", w, "meadow", "lake")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("locations", "rename", w, "lake", "pond")
      self.assertEqual(status, 0, out)
      self.assertIn("maps meadow follow", out)
      status, out = self.run_cli("locations", "set", w, "pond", "--name", "Pond", "--banner", "-")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("locations", "check", w)
      self.assertEqual(status, 0, out)
      p = self.reopen()
      self.assertEqual(p.world.data["transition"], "wipe_v")
      self.assertEqual(locations.styles(p)["dusk"], {"fill": "#102040"})
      self.assertEqual(locations.location(p, "pond"), {"name": "Pond", "preview": {
         "sequences": [{"sequence": "sequences/cave_preview.json"}], "show": "first"}})
      self.assertEqual(locations.map_location(p.map("meadow")), "pond")
      status, out = self.run_cli("locations", "preview-remove", w, "pond", "0")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("locations", "style-remove", w, "box")
      self.assertEqual(status, 1)   # park and cave use it
      self.assertIn("is used by park, cave", out)
      status, out = self.run_cli("locations", "remove", w, "pond")
      self.assertEqual(status, 0, out)
      self.assertIn("maps meadow are in none now", out)
      status, out = self.run_cli("locations", "map", w, "showcase", "-")
      self.assertEqual(status, 0, out)
      self.assertIn("showcase: location (none)", out)
      # The events commands take --transition for warps only.
      status, out = self.run_cli("events", "set", w, "showcase", "warp", "1", "--transition", "fade")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("events", "set", w, "showcase", "sign", "0", "--transition", "fade")
      self.assertEqual(status, 1)
      status, out = self.run_cli("events", "set", w, "showcase", "warp", "1", "--transition", "spin")
      self.assertEqual(status, 1)
      self.assertEqual(events.events(self.reopen().map("showcase"), "warps")[1]["transition"], "fade")

   def test_import(self) -> None:
      """!Imported maps bring the locations they name (with their banner styles and the conditions their
      previews wait for), pointing at the source's files; the world's own definitions win.
      @return None
      """
      target = self.root / "target" / "world.json"
      p = Project.create(target)
      p.save_all()
      p = Project.open(target)
      with p.world.edit("Box"):
         locations.add_style(p, "box", fill="#000000")
      src = self.project
      with src.world.edit("Night preview"):
         locations.add_sequence(src, "cave", "sequences/cave_preview.json", when=["night"])
      src.save_all()
      lines = p.import_from(self.world, maps=["cave", "meadow"])
      self.assertTrue(any(ln.startswith("locations cave, meadow (banner styles sign)") for ln in lines), lines)
      self.assertEqual(locations.styles(p)["box"], {"fill": "#000000"})   # the world's own
      self.assertEqual(locations.styles(p)["sign"]["frame"], "../sandbox_map/data/banners/sign.png")
      self.assertEqual(locations.sequences(p, "cave")[0]["sequence"],
                       "../sandbox_map/data/sequences/cave_preview.json")
      self.assertIn("night", p.world.data["encounter_conditions"])
      self.assertEqual(locations.map_location(p.map("cave")), "cave")
      self.assertIsNone(p.validate())
      self.assertEqual(json.loads(json.dumps(locations.location(p, "meadow"))),
                       {"name": "Sunny Meadow", "banner": "sign"})


if __name__ == "__main__":
   unittest.main()
