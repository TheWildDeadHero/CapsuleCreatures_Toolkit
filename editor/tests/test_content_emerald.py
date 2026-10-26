#!/usr/bin/env python3
"""!The studio core on an imported Emerald world (I2: 539 maps, 76 fixed tilesets, "all" dictionaries; I3 content
sets add warps, objects and sprites). Private content, never part of this repository: the tests run when
CAPSULE_CONTENT_EMERALD names an imported content folder (assets-imported/emerald, holding world/world.json) and are
skipped otherwise. The round trip works on a temporary copy, removed afterwards.

Checks: every map compiles one by one against its tilesets (what the map editor shows) without errors, every
tileset's preview draws, the events check passes, and opening every document and saving without edits writes
nothing, while a forced save of each document keeps its JSON (the studio's own layout: semantically identical). The
times are printed.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.core import mapview  # noqa: E402
from capsule_studio.core.document import Document  # noqa: E402
from capsule_studio.core.world import Project  # noqa: E402

## The environment variable naming the content folder.
CONTENT_ENV = "CAPSULE_CONTENT_EMERALD"
## Seconds the one-by-one compile of every map may take at most (a slow machine's margin over the ten it takes).
MAPS_SECONDS = 120


def content_world() -> Path | None:
   """!The content set's world.json.
   @return Path, or None when CAPSULE_CONTENT_EMERALD names none
   """
   folder = os.environ.get(CONTENT_ENV)
   if not folder:
      return None
   world = Path(folder) / "world" / "world.json"
   return world if world.is_file() else None


@unittest.skipIf(content_world() is None, f"{CONTENT_ENV} names no imported content (private; skipped)")
class EmeraldContentTests(unittest.TestCase):
   """!The core on the imported world."""

   def test_every_map(self) -> None:
      """!Every map and tileset compiles and draws; the events check passes.
      @return None
      """
      p = Project.open(content_world())
      t = time.perf_counter()
      errors = [(n, p.compiled_map(n)[1]) for n in p.map_names()]
      errors = [(n, e) for n, e in errors if e]
      maps_time = time.perf_counter() - t
      t = time.perf_counter()
      pictures = 0
      for name in p.tileset_names():
         ts, preview, error = p.compiled_tileset(name)
         self.assertIsNone(error, name)
         pictures += len(mapview.metatile_images(preview, backdrop=False)) if preview else 0
      tiles_time = time.perf_counter() - t
      t = time.perf_counter()
      events_error = p.check_events()
      events_time = time.perf_counter() - t
      print(f"\n{len(p.map_names())} maps in {maps_time:.1f} s, {len(p.tileset_names())} tilesets ({pictures} "
            f"metatile pictures) in {tiles_time:.1f} s, events in {events_time:.1f} s")
      self.assertEqual(errors, [])
      self.assertIsNone(events_error)
      self.assertLess(maps_time, MAPS_SECONDS)

   def test_sprites(self) -> None:
      """!An I3 content set's overworld sprites (streamed, mirrored steps, indexed sheet frames) compile in the scene
      editor's core (skipped for a content set without them).
      @return None
      """
      assets = content_world().parent.parent / "overworld" / "assets.json"
      if not assets.is_file():
         self.skipTest("this content set has no overworld sprites (an I2 one)")
      doc = Document.open(assets)
      problems, reports = doc.validate()
      self.assertEqual(problems, [])
      self.assertEqual([(k, r.error) for k, r in reports.items() if not r.ok], [])
      print(f"\n{len(reports)} imported sprites compile")

   def test_round_trip(self) -> None:
      """!Save without edits writes nothing; a forced save keeps every file's JSON.
      @return None
      """
      src = content_world().parent
      root = Path(tempfile.mkdtemp(prefix="capsule_content_"))
      try:
         copy = root / "world"
         shutil.copytree(src, copy)
         files = sorted(f for f in copy.rglob("*") if f.is_file())
         before = {f: f.read_bytes() for f in files}
         p = Project.open(copy / "world.json")
         for n in p.map_names():
            p.map(n)
         for n in p.tileset_names():
            p.tileset(n)
         p.save_all()
         self.assertEqual({f: f.read_bytes() for f in files}, before)
         for d in p.documents():
            d.save()
         relaid = 0
         for f in files:
            if f.suffix == ".json" and f.read_bytes() != before[f]:
               relaid += 1
               self.assertEqual(json.loads(f.read_text(encoding="utf-8")), json.loads(before[f]), f.name)
         print(f"\nforced save: {relaid} of {len(files)} files written in the studio's layout, the same JSON")
      finally:
         shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
   unittest.main()
