#!/usr/bin/env python3
"""!The text and script editors on a large imported game (no Qt): skipped unless CAPSULE_IMPORTED_CONTENT
names an importer's output folder for one game (assets-imported/<game>: text/text_assets.json, text/fonts/,
world/scripts/scripts.json). Nothing is written there: the round trip compares each file with what a save would
write, in memory. The times are printed (stderr) and held to generous bounds.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.core import asset_tables, fonts, manifest_io, scripts, text_tables  # noqa: E402
from capsule_studio.core.document import Document  # noqa: E402

## The environment variable naming the content folder.
CONTENT_ENV = "CAPSULE_IMPORTED_CONTENT"
## The content folder, or None.
CONTENT = Path(os.environ[CONTENT_ENV]) if os.environ.get(CONTENT_ENV) else None
## Most seconds one step may take (a generous bound: a slow machine, a debug build of Python).
SLOW_SECONDS = 120


def timed(label: str, start: float) -> float:
   """!Prints how long a step took.
   @param label  the step
   @param start  its perf_counter() start
   @return seconds
   """
   took = time.perf_counter() - start
   print(f"timing: {label}: {took:.2f} s", file=sys.stderr)
   return took


@unittest.skipIf(CONTENT is None, f"set {CONTENT_ENV} to an imported game's folder (assets-imported/<game>)")
class ImportedContentTests(unittest.TestCase):
   """!Open, check and round-trip the content."""

   def test_text_tables_and_fonts(self) -> None:
      """!Every table and font opens and saves byte-identically; the fit agrees with the engine's report.
      @return None
      """
      manifest = CONTENT / "text" / "text_assets.json"
      t = time.perf_counter()
      doc = Document.open(manifest)
      ctx = text_tables.TextContext.for_manifest(manifest)
      refs = asset_tables.table_set(doc)
      tables = [text_tables.open_table(r.path) for r in refs]
      font_docs = [fonts.open_font(p) for _label, p in asset_tables.fonts(doc)]
      self.assertLess(timed(f"open {len(tables)} tables and {len(font_docs)} fonts", t), SLOW_SECONDS)
      self.assertIsNotNone(ctx.field, "the scripts manifest naming the text was not found")
      t = time.perf_counter()
      for d in tables + font_docs:
         self.assertEqual(manifest_io.dumps_layout(d.data, d.layout), d.path.read_text(encoding="utf-8"),
                          f"{d.path.name} would not save byte-identically")
      timed("round trip (in memory)", t)
      t = time.perf_counter()
      fit = [0, 0, 0]
      problems = []
      for d in tables:
         f = text_tables.check_table(ctx, d)
         fit = [fit[0] + f.checked, fit[1] + f.over, fit[2] + f.with_placeholders]
         problems += f.problems
      self.assertLess(timed(f"fit {fit[0]} authored texts", t), SLOW_SECONDS)
      t = time.perf_counter()
      report = asset_tables.fit_report(doc, ctx.page, ctx.field)
      timed("the engine's whole-manifest check", t)
      self.assertEqual(fit, [report["checked"], report["over"], report["with_placeholders"]])
      self.assertEqual([p.key for p in problems if p.error], [])
      for d in font_docs:
         self.assertIsNone(fonts.problem(d, ctx.page), d.path.name)

   def test_scripts(self) -> None:
      """!The scripts compile; the outline has the imported declarations and triggers.
      @return None
      """
      t = time.perf_counter()
      p = scripts.ScriptProject.open(CONTENT / "world" / "scripts" / "scripts.json")
      timed(f"open {len(p.sources)} script sources", t)
      t = time.perf_counter()
      r = p.check()
      self.assertLess(timed("check the scripts", t), SLOW_SECONDS)
      self.assertTrue(r.ok, [d.message for d in r.errors[:5]])
      for kind in ("movement", "mart", "step", "map"):
         self.assertTrue(r.outline.items[kind], kind)
      details = " ".join(i["detail"] for i in r.outline.items["map"])
      self.assertIn("on_warp_into", details)
      self.assertFalse(p.dirty)


if __name__ == "__main__":
   unittest.main()
