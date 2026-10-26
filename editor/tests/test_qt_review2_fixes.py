#!/usr/bin/env python3
"""!Regression tests of spot review 2's window findings (C4): the bench page with a malformed reference
compat/generators.json opens with the engine's generator and reports the manifest's problem in the status bar.
Skipped when PySide6 is missing; uses Qt's offscreen platform.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import bench, templates  # noqa: E402
from test_qt_battle import QtBattleTestCase  # noqa: E402

## A malformed capsule.generators/1 manifest.
BAD_GENERATORS = '{"schema": "capsule.generators/1", "generators": [{"nam": 1}]}'


class BenchGeneratorsTests(QtBattleTestCase):
   """!The bench page with a malformed reference generators manifest."""

   def test_default_generator_and_report(self) -> None:
      """!The page opens, offers only the default generator and says why in the status bar and the combo's tip.
      @return None
      """
      ref = Path(tempfile.mkdtemp(prefix="capsule_badref_"))
      try:
         (ref / templates.REFERENCE_TEMPLATES).mkdir()
         (ref / bench.COMPAT_FOLDER).mkdir()
         (ref / bench.COMPAT_FOLDER / bench.tool().GENERATORS_FILE).write_text(BAD_GENERATORS, encoding="utf-8")
         with mock.patch.dict(os.environ, {templates.REFERENCE_ENV: str(ref)}):
            w, panel = self.window("bench")
            self.settle()
            items = [panel.rng_combo.itemText(i) for i in range(panel.rng_combo.count())]
            self.assertEqual(items, [bench.DEFAULT_RNG])
            self.assertIn("generators[0]", w.statusBar().currentMessage())
            self.assertIn("Only the engine's generator", panel.rng_combo.toolTip())
            self.close(w)
      finally:
         shutil.rmtree(ref, ignore_errors=True)
