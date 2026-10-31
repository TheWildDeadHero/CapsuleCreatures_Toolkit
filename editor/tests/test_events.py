#!/usr/bin/env python3
"""!Tests for map events (capsule_studio.core.events) and the studio's events
extension: its commands, map tool, overlay, hover text and validator (no Qt
needed).

Uses the engine's map sandbox world (copied, with the Starter sample its world
names beside it, as in the engine's layout): its showcase, cave and meadow events.
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
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import events  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402
from capsule_studio.plugins import MapView, loader  # noqa: E402
from sample_data import copy_engine_apps  # noqa: E402

if TYPE_CHECKING:
   from capsule_studio.plugins.registry import Registry


class EventWorld(unittest.TestCase):
   """!Base: a copy of the sandbox world per test."""

   def setUp(self) -> None:
      """!Copies the sandbox world and the battle data it names.
      @return None
      """
      ## Temporary root.
      self.root = copy_engine_apps(Path(tempfile.mkdtemp(prefix="capsule_events_")), ["sandbox_map"])
      ## The copy's world.json.
      self.world = self.root / "sandbox_map" / "data" / "world.json"
      ## The opened world.
      self.project = Project.open(self.world)

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

   def reopen(self) -> Project:
      """!Opens the saved world again.
      @return Project
      """
      return Project.open(self.world)


class CoreTests(EventWorld):
   """!core.events on the sandbox world."""

   def test_read(self) -> None:
      """!Events by kind and cell, descriptions, areas, names from the scripts manifest.
      @return None
      """
      doc = self.project.map("showcase")
      # DS1: the hut's door warp and the garden sign came with the hut
      self.assertEqual([k for k, _i, _e in events.all_events(doc)],
                       ["warps", "warps", "warps", "triggers", "signs", "signs", "signs"])
      here = events.events_at(doc, 12, 10)
      self.assertEqual(len(here), 1)
      self.assertEqual(events.describe(*here[0][::2]), "sign: hidden_berry, until found_berry")
      self.assertEqual(events.area(self.project.map("cave"), "cave"), "showcase")
      self.assertEqual(events.area(self.project.map("meadow"), "meadow"), "meadow")
      n = events.names(self.project)
      self.assertIsNone(n["error"])
      self.assertIn("welcome", n["scripts"])
      self.assertEqual(n["vars"]["welcomed"], (0, 1))
      self.assertIsNone(events.check(self.project))

   def test_edit_and_check(self) -> None:
      """!Adding, changing and moving events; the engine's rules decide what is valid.
      @return None
      """
      doc = self.project.map("meadow")
      with doc.edit("Add sign"):
         i = events.add_event(doc, "sign", 3, 2, script="showcase_sign", facing="up")
      self.assertIsNone(events.check(self.project))
      with doc.edit("Change sign"):
         events.set_event(doc, "sign", i, script="nope")
      self.assertIn("unknown script 'nope'", events.check(self.project))
      doc.undo()
      with doc.edit("Change sign"):
         events.set_event(doc, "sign", i, facing=None, elevation=0)
      self.assertNotIn("facing", events.events(doc, "signs")[i])
      with self.assertRaises(DocumentError):
         events.set_event(doc, "sign", i, to="cave")   # not a sign field
      with doc.edit("Move"):
         events.move_event(doc, "sign", i, -50, -50)
      self.assertIn("outside the map's chunks", events.check(self.project))

   def test_remove_renumbers_warps(self) -> None:
      """!Removing a warp renumbers the map's own later warps in one undo step; a warp others land on,
      or one before warps another map lands on, is refused.
      @return None
      """
      p = self.project
      with self.assertRaises(DocumentError) as cm:
         events.remove_event(p, "showcase", "warps", 1)
      self.assertIn("meadow warp 0", str(cm.exception))
      with self.assertRaises(DocumentError) as cm:
         events.remove_event(p, "showcase", "warps", 0)      # cave lands on 0; meadow on the later 1
      sc = p.map("showcase")
      # DS1: showcase warp 2 is the hut's door (hut warp 0 lands on it), so the new warps are 3 to 5
      with self.assertRaises(DocumentError) as cm:
         events.remove_event(p, "showcase", "warps", 2)
      self.assertIn("hut warp 0", str(cm.exception))
      with sc.edit("Add warps"):
         events.add_event(sc, "warps", 1, 9, to="cave", warp=0)        # showcase warp 3
         events.add_event(sc, "warps", 2, 9, to="showcase", warp=4)    # 4: lands on 4 (itself)
         events.add_event(sc, "warps", 3, 9, to="showcase", warp=3)    # 5: lands on 3
      with self.assertRaises(DocumentError):
         events.remove_event(p, "showcase", "warps", 3)                # warp 5 lands on it
      with sc.edit("Retarget"):
         events.set_event(sc, "warps", 5, warp=4)
      events.remove_event(p, "showcase", "warps", 3)
      self.assertEqual([w.get("warp") for w in events.events(sc, "warps")], [0, 0, 0, 3, 3])   # 4 and 5 follow
      sc.undo()
      self.assertEqual([w.get("warp") for w in events.events(sc, "warps")], [0, 0, 0, 0, 4, 4])
      self.assertIsNone(events.check(p))

   def test_dependent_fields_and_game_scripts(self) -> None:
      """!Clearing a press warp's trigger or a trigger's variable drops the field that needs it; the
      game's project.json supplies the scripts manifest when the world names none.
      @return None
      """
      p = self.project
      m = p.map("meadow")
      with m.edit("Step"):
         events.set_event(m, "warps", 0, trigger=None)
      self.assertNotIn("direction", events.events(m, "warps")[0])
      sc = p.map("showcase")
      with sc.edit("Always"):
         events.set_event(sc, "triggers", 0, var=None)
      self.assertNotIn("value", events.events(sc, "triggers")[0])
      game = self.root / "sandbox_map"
      (game / "reference").mkdir()
      (game / "reference" / "project.json").write_text(json.dumps(
         {"schema": "capsule.project/1", "name": "x", "maps": "data/world.json",
          "scripts": "data/scripts/scripts.json"}))
      with p.world.edit("No scripts"):
         events.set_scripts(p, None)
      self.assertIsNone(events.check(p))
      self.assertIn("welcome", events.names(p)["scripts"])

   def test_world_settings(self) -> None:
      """!Scripts manifest and step hooks.
      @return None
      """
      p = self.project
      with p.world.edit("Hook"):
         events.add_hook(p, "step_counter", 4)
      self.assertEqual([h["name"] for h in events.step_hooks(p)], ["pedometer", "step_counter"])
      for bad in (("step_counter", 4), ("timer", 3), ("x y", 4)):
         with self.assertRaises(DocumentError):
            events.add_hook(p, *bad)
      with p.world.edit("Hook"):
         events.remove_hook(p, "step_counter")
      with p.world.edit("Scripts"):
         events.set_scripts(p, None)
      self.assertIn("scripts manifest", events.check(p))
      with p.world.edit("Scripts"):
         events.set_scripts(p, self.root / "sandbox_map" / "data" / "scripts" / "scripts.json")
      self.assertEqual(p.world.data["scripts"], "scripts/scripts.json")
      self.assertIsNone(events.check(p))

   def test_diagnostics(self) -> None:
      """!A trigger on a wall is flagged; compile errors come first.
      @return None
      """
      doc = self.project.map("showcase")
      with doc.edit("Trigger on a wall"):
         events.add_event(doc, "trigger", 3, 3, script="welcome")
      found = events.diagnostics(self.project, "showcase")
      self.assertTrue(any(d.level == "warning" and "collision" in d.message for d in found), found)


class ImportTests(EventWorld):
   """!Importing maps keeps the events that still resolve."""

   def test_import_events(self) -> None:
      """!Warps between imported maps follow; others, and script events without a manifest, are left out.
      @return None
      """
      from capsule_studio.core import importer
      target = Project.create(self.root / "other" / "world.json")
      lines = importer.run(target, self.project, ["showcase", "cave"])
      self.assertTrue(any("events: " in l and "left out" in l for l in lines), lines)
      sc = target.map("showcase")
      self.assertEqual([w["to"] for w in events.events(sc, "warps")], ["cave"])   # the meadow warp is gone
      self.assertEqual(events.events(sc, "triggers"), [])                          # no scripts manifest here
      self.assertEqual(events.area(target.map("cave"), "cave"), "showcase")
      # S3 (DS1): the garden set persists through a flag; without a scripts manifest it is left out
      self.assertTrue(any(l.startswith("override sets: 1 left out") for l in lines), lines)
      self.assertNotIn("override_sets", sc.data)
      self.assertIsNone(target.validate())


class ExtensionTests(EventWorld):
   """!The extension: map tool, overlay, hover text, validator, commands."""

   def registry(self) -> Registry:
      """!The studio's built-in extensions.
      @return Registry
      """
      return loader.builtin_registry()

   def test_tool_overlay_hover(self) -> None:
      """!Place, move and remove with the Events tool; the overlay and hover text show events.
      @return None
      """
      reg = self.registry()
      tool = next(t for t in reg.map_tools() if t.id.endswith("events"))
      view = MapView(self.project, "meadow")
      tool.kind, tool.action = "triggers", "place"
      tool.apply(view, [(4, 4)])
      doc = self.project.map("meadow")
      self.assertEqual(events.events(doc, "triggers")[0]["at"], [4, 4])
      tool.action = "move"
      tool.apply(view, [(5, 4)])
      self.assertEqual(events.events(doc, "triggers")[0]["at"], [5, 4])
      overlay = next(o for o in reg.map_overlays() if o.id.endswith("events"))
      cell = overlay.prepare(view)
      self.assertEqual(cell(5, 4, 0)[1], "T")
      self.assertEqual(cell(0, 0, 0)[1], "W")
      hover = [fn for fn in reg.hover_texts()]
      self.assertTrue(any("trigger 0" in (fn(view, 5, 4, 0) or "") for fn in hover))
      tool.action = "remove"
      tool.apply(view, [(5, 4)])
      self.assertEqual(events.events(doc, "triggers"), [])
      found = reg.validate(self.project, None)
      self.assertFalse(any(d.level == "error" for d in found), found)

   def test_commands(self) -> None:
      """!show, add, set, move, area, hook-add, scripts, check, remove.
      @return None
      """
      w = self.world
      status, out = self.run_cli("events", "show", w, "--map", "showcase")
      self.assertEqual(status, 0, out)
      self.assertIn("sign 1 at 12,10: sign: hidden_berry, until found_berry", out)
      status, out = self.run_cli("events", "add", w, "meadow", "sign", "3", "2", "--script", "showcase_sign")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("events", "set", w, "meadow", "sign", "0", "--facing", "up", "--flag", "found_berry")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("events", "move", w, "meadow", "sign", "0", "4", "2")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("events", "set", w, "meadow", "sign", "0", "--script", "nope")
      self.assertEqual(status, 1)
      self.assertIn("unknown script", out)
      status, out = self.run_cli("events", "set", w, "meadow", "sign", "0", "--to", "cave")
      self.assertEqual(status, 1)
      status, out = self.run_cli("events", "area", w, "meadow", "showcase")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("events", "area", w, "meadow", "-")
      self.assertIn("area meadow", out)
      status, out = self.run_cli("events", "hook-add", w, "step_counter", "4", "--phase", "1")
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("events", "scripts", w)
      self.assertIn("welcome", out)
      status, out = self.run_cli("events", "check", w)
      self.assertEqual(status, 0, out)
      status, out = self.run_cli("events", "remove", w, "meadow", "sign", "0")
      self.assertEqual(status, 0, out)
      p = self.reopen()
      self.assertEqual(events.events(p.map("meadow"), "signs"), [])
      self.assertEqual(events.step_hooks(p)[-1], {"name": "step_counter", "period": 4, "phase": 1})


if __name__ == "__main__":
   unittest.main()
