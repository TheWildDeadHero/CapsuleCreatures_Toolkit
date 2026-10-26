#!/usr/bin/env python3
"""!Tests of core.field_rules (the world's elevation levels and movement
modes, engine E8), their `levels` / `modes` commands and the importer's
level comparison, on a copy of the engine's map sandbox world.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import engine, field_rules, importer  # noqa: E402
from capsule_studio.core.document import DocumentError  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402
from test_world import WorldTestCase  # noqa: E402

## Highest level number (a cell's 4 bits).
TOP_LEVEL = 15


class LevelTests(WorldTestCase):
   """!The 16 levels."""

   def test_rows_and_edits(self) -> None:
      """!Levels as the compiler resolves them; edits checked by it; a rename follows the meets lists.
      @return None
      """
      mc = engine.tool("map_compiler")
      w = self.project.world
      rows = field_rules.level_rows(w)
      self.assertEqual(len(rows), mc.ELEVATIONS)
      self.assertEqual(rows[0]["met"], list(range(mc.ELEVATIONS)))
      self.assertEqual(rows[1]["met"], [1])
      self.assertEqual(rows[TOP_LEVEL]["on_arrive"], "keep")
      self.assertFalse(rows[0]["default"])
      with w.edit("Meets"):
         field_rules.set_level(w, 3, "meets", ["bridge", 4])
      self.assertEqual(field_rules.level_rows(w)[3]["met"], [3, 4, TOP_LEVEL])
      with w.edit("Rename"):
         self.assertEqual(field_rules.rename_level(w, TOP_LEVEL, "overpass"), 1)
      self.assertEqual(w.data["elevations"][3]["meets"], ["overpass", 4])
      with self.assertRaises(DocumentError):
         with w.edit("Priority"):
            field_rules.set_level(w, 4, "priority", field_rules.max_priority() + 1)
      self.assertEqual(w.data["elevations"][4]["priority"], mc.DEFAULT_SPRITE_PRIORITY)
      self.assertIsNone(self.project.validate())
      with w.edit("Reset"):
         self.assertTrue(field_rules.reset_levels(w))
      self.assertTrue(field_rules.level_rows(w)[0]["default"])
      with w.edit("Write out"):
         field_rules.set_level(w, 2, "on_arrive", "keep")   # the default rule is written out first
      self.assertEqual(len(w.data["elevations"]), mc.ELEVATIONS)
      self.assertIsNone(self.project.validate())

   def test_import_compares_levels(self) -> None:
      """!An import notes levels that differ as the engine resolves them.
      @return None
      """
      new = Project.create(self.root / "other" / "world.json", "other")
      plan = importer.plan(new, self.project, ["showcase"], [])
      self.assertTrue(any("elevation levels differ" in n for n in plan["notes"]), plan["notes"])


class ModeTests(WorldTestCase):
   """!The movement modes."""

   def test_rows_and_edits(self) -> None:
      """!Modes with what they enter; renames follow behaviors and encounter methods; class 0 stays.
      @return None
      """
      w = self.project.world
      rows = field_rules.mode_rows(w)
      self.assertEqual([r["name"] for r in rows], ["foot", "swim"])
      self.assertNotIn("water", rows[0]["enters"])
      self.assertIn("water", rows[1]["enters"])
      self.assertFalse(rows[1]["can_run"])
      with w.edit("Add"):
         self.assertEqual(field_rules.add_mode(w, "bike"), 2)
         field_rules.set_mode(w, "bike", "walk", 2)
         field_rules.set_mode(w, "bike", "passable", ["normal", "ice"])
      bike = field_rules.mode_rows(w)[2]
      self.assertEqual((bike["walk"], bike["enters"]), (2, ["normal", "ice"]))
      with self.assertRaises(DocumentError):
         with w.edit("Speed"):
            field_rules.set_mode(w, "bike", "run", 3)   # not a speed the engine allows
      with self.assertRaises(DocumentError):
         with w.edit("Animation"):
            field_rules.set_mode(w, "bike", "first_animation", 1)   # not a multiple of the set size
      with w.edit("Rename"):
         followed = field_rules.rename_mode(w, "swim", "boat")
      self.assertEqual(followed, ["behavior water", "encounter method swim"])
      self.assertIsNone(self.project.validate())
      with self.assertRaises(DocumentError):
         field_rules.remove_mode(w, "foot")
      self.assertFalse(field_rules.move_mode(w, "foot", 1))
      with w.edit("Move"):
         self.assertTrue(field_rules.move_mode(w, "bike", -1))
      self.assertEqual(field_rules.mode_names(w), ["foot", "bike", "boat"])
      with w.edit("Remove"):
         field_rules.remove_mode(w, "bike")
      self.assertEqual(field_rules.mode_names(w), ["foot", "boat"])
      self.assertTrue(any("movement modes" in line for line in field_rules.lines(w)))


class CommandTests(WorldTestCase):
   """!`capsule-studio levels|modes WORLD ...`."""

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
      """!Edits save; a refused one does not.
      @return None
      """
      world = self.dir / "world.json"
      self.assertEqual(self.run_cli("levels", world, "rename", TOP_LEVEL, "overpass")[0], 0)
      self.assertEqual(self.run_cli("levels", world, "set", 3, "meets", '["overpass"]')[0], 0)
      self.assertEqual(self.run_cli("modes", world, "add", "bike")[0], 0)
      self.assertEqual(self.run_cli("modes", world, "set", "bike", "can_run", "false")[0], 0)
      status, out = self.run_cli("modes", world, "rename", "swim", "boat")
      self.assertEqual(status, 0)
      self.assertIn("behavior water", out)
      self.assertEqual(self.run_cli("levels", world, "set", 4, "priority", 9)[0], 1)
      saved = json.loads(world.read_text(encoding="utf-8"))
      self.assertEqual(saved["elevations"][3]["meets"], ["overpass"])
      self.assertEqual(saved["vehicle_classes"][2], {"name": "bike", "can_run": False})
      self.assertEqual(saved["encounter_methods"][1]["vehicles"], ["boat"])
      status, out = self.run_cli("levels", world, "list")
      self.assertIn("15 overpass", out)


if __name__ == "__main__":
   unittest.main()
