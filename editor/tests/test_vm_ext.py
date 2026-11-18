#!/usr/bin/env python3
"""![VX] The Extensions view's model (core/vm_ext.py, D-39) over the engine's tools/vm_ext.py: the engine sandbox's
manifest (simple shapes), progress per table, filters, usage records, GBA sizes and the report. Skipped without an
engine checkout."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capsule_studio.core import engine  # noqa: E402
from capsule_studio.core import vm_ext as core  # noqa: E402

try:
   engine.root()
   HAVE_ENGINE = True
except engine.EngineNotFound:
   HAVE_ENGINE = False
## Step D: the engine has the script VM's natives sample (an older pinned engine does not).
HAVE_SCRIPT_SAMPLE = HAVE_ENGINE and (engine.root() / core.SCRIPT_SAMPLE).is_file()

## The sandbox's ops: 6 aliases, 2 natives.
SANDBOX_ALIASES = 6
## Its natives.
SANDBOX_NATIVES = 2
## Step D: the engine's script natives sample's natives.
SCRIPT_SAMPLE_NATIVES = 3
## Its wheels package's bytes in the test listing.
WHEELS_BYTES = 0x40


@unittest.skipUnless(HAVE_ENGINE, "no engine checkout (set CAPSULE_ENGINE)")
class ExtensionModelTests(unittest.TestCase):
   """!The sandbox's manifest read through the engine's tool."""

   def test_sample(self) -> None:
      """!Rows, progress and the checks of the sandbox's manifest.
      @return None
      """
      ext = core.load([core.sandbox_manifest()])
      self.assertEqual(ext.tables(), ["battle"])
      (s,) = ext.summary()
      self.assertEqual((s.ops, s.aliases, s.natives, s.proven), (8, SANDBOX_ALIASES, SANDBOX_NATIVES, 0))
      self.assertEqual(s.alias_percent, 75)
      self.assertIsNone(s.unused)
      self.assertEqual((ext.errors, ext.warnings), ([], []))
      goto = next(r for r in ext.rows if r.name == "goto")
      self.assertEqual((goto.kind, goto.size, goto.steps), ("alias", 5, ["jump: target=target"]))
      slide = next(r for r in ext.rows if r.name == "slide")
      self.assertIn("controller", slide.reason)
      self.assertEqual(slide.symbol, "cmd_slide")

   def test_filters(self) -> None:
      """!Kind and text filters.
      @return None
      """
      ext = core.load([core.sandbox_manifest()])
      self.assertEqual(len(ext.filtered(None, core.FILTERS["Natives"])), SANDBOX_NATIVES)
      self.assertEqual(len(ext.filtered("battle", core.FILTERS["Aliases"])), SANDBOX_ALIASES)
      self.assertEqual([r.name for r in ext.filtered(None, core.FILTERS["All ops"], "both")], ["slide_both"])

   def test_usage_and_sizes(self) -> None:
      """!Usage records give uses and the unused count; an nm listing gives the natives' bytes.
      @return None
      """
      with tempfile.TemporaryDirectory() as tmp:
         usage = Path(tmp) / "u.json"
         usage.write_text(json.dumps({"schema": core.USAGE_SCHEMA, "vm": "battle", "bank": "b",
                                      "ops": {"goto": 2, "slide": 4}}), encoding="utf-8")
         sizes = Path(tmp) / "nm.txt"
         sizes.write_text("08000100 00000040 T (anonymous namespace)::cmd_slide(vm::Machine&, void*)\n",
                          encoding="utf-8")
         ext = core.load([core.sandbox_manifest()], [usage], sizes)
      slide = next(r for r in ext.rows if r.name == "slide")
      self.assertEqual((slide.uses, slide.gba_bytes), (4, 64))
      self.assertEqual(next(r for r in ext.rows if r.name == "pause").uses, 0)
      self.assertEqual(ext.summary()[0].unused, 6)
      report = core.report_text(ext)
      self.assertIn("battle: 8 ops, 6 aliases (75%), 2 natives, 6 unused", report)
      self.assertIn("slide\tsandbox\t64 B", report)

   @unittest.skipUnless(HAVE_SCRIPT_SAMPLE, "the engine has no script natives sample (D-36 step D)")
   def test_script_sample(self) -> None:
      """!Step D: the script VM's generic ops and the natives sample: progress, classes, the filters, the report.
      @return None
      """
      manifests, usage = core.script_sample()
      ext = core.load(manifests, usage)
      self.assertEqual(ext.tables(), ["script", "script:native"])
      ops, natives = ext.summary()
      self.assertEqual((ops.generic, ops.natives, ops.aliases), (ops.ops, 0, 0))
      self.assertEqual((natives.natives, natives.unused), (SCRIPT_SAMPLE_NATIVES, 0))
      self.assertEqual(ext.native_classes(), [("Game-specific rules", 1, 2), ("Stand-ins", 1, 1),
                                              ("Not implemented (M6)", 1, 1)])
      self.assertEqual(len(ext.filtered(None, core.FILTERS["Generic ops"])), ops.ops)
      beacon = next(r for r in ext.rows if r.name == "light_beacon")
      self.assertEqual((beacon.implemented, beacon.milestone, beacon.uses), (False, "M6", 1))
      self.assertIn("Stand-ins: 1 natives, 1 uses", core.report_text(ext))

   @unittest.skipUnless(HAVE_SCRIPT_SAMPLE, "the engine has no script natives sample (D-36 step D)")
   def test_script_owner_sizes(self) -> None:
      """!Step D: a script native's GBA bytes are its owner's namespaces' code.
      @return None
      """
      manifests, _usage = core.script_sample()
      with tempfile.TemporaryDirectory() as tmp:
         sizes = Path(tmp) / "nm.txt"
         sizes.write_text("08000000 00000040 T sample::wheels::run(int)\n", encoding="utf-8")
         ext = core.load(manifests, [], sizes)
      wheel = next(r for r in ext.rows if r.name == "spin_wheel")
      self.assertEqual((wheel.gba_bytes, wheel.owner_bytes, wheel.uses), (None, WHEELS_BYTES, 2))

   @unittest.skipUnless(HAVE_SCRIPT_SAMPLE, "the engine has no script natives sample (D-36 step D)")
   def test_game_files(self) -> None:
      """!Step D: a game's natives manifest and usage record are found under its folders.
      @return None
      """
      with tempfile.TemporaryDirectory() as tmp:
         content, build = Path(tmp) / "content" / "world" / "scripts", Path(tmp) / "build" / "game"
         content.mkdir(parents=True)
         build.mkdir(parents=True)
         (content / core.GAME_NATIVES_FILE).write_text("{}", encoding="utf-8")
         (build / core.GAME_USAGE_FILE).write_text("{}", encoding="utf-8")
         manifests, usage = core.game_files([Path(tmp) / "content", Path(tmp) / "build"])
      self.assertEqual([p.name for p in manifests], ["script_vm.json", core.GAME_NATIVES_FILE])
      self.assertEqual([p.name for p in usage], [core.GAME_USAGE_FILE])

   def test_refused(self) -> None:
      """!A manifest the engine refuses is an ExtensionError with its reason.
      @return None
      """
      with tempfile.TemporaryDirectory() as tmp:
         bad = Path(tmp) / "bad.json"
         bad.write_text(json.dumps({"schema": "capsule.vm-ext/1", "vm": "battle", "ops": [
            {"id": 0, "name": "x", "kind": "native", "symbol": "cmd_x", "reason": ""}]}), encoding="utf-8")
         with self.assertRaises(core.ExtensionError) as caught:
            core.load([bad])
      self.assertIn("reason", str(caught.exception))


if __name__ == "__main__":
   unittest.main()
