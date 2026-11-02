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

## The sandbox's ops: 6 aliases, 2 natives.
SANDBOX_ALIASES = 6
## Its natives.
SANDBOX_NATIVES = 2


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
