#!/usr/bin/env python3
"""![C14b] Qt smoke (offscreen; skipped without PySide6): the WAV player's fallback when Qt Multimedia fails while
playing (the player goes silent, its clock runs on, the render bar hands the WAV to the system's player and says
why), and Play on a machine without Qt Multimedia or an audio output (the offscreen platform) staying silent."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

if QtWidgets is not None:
   from capsule_studio.ui.editors import audio_common  # noqa: E402

## The error text the tests' stand-in media player reports.
MEDIA_ERROR = "no multimedia backend"
## Seconds the stand-in WAV lasts.
LENGTH = 2.0


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtC14bTests(unittest.TestCase):
   """!The audio editor's playing fallbacks."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

   def test_offscreen_cannot_play(self) -> None:
      """!The offscreen platform has no audio output: Play runs the silent clock.
      @return None
      """
      ok, why = audio_common.can_play()
      self.assertFalse(ok)
      self.assertTrue(why)
      p = audio_common.WavPlayer()
      p.play(Path("missing.wav"), LENGTH)
      self.assertFalse(p.audible)
      self.assertTrue(p.playing())
      p.stop()

   def test_media_error_falls_back(self) -> None:
      """!An error from Qt Multimedia while playing: failed(text) once, silent from then on, the clock still runs.
      @return None
      """
      p = audio_common.WavPlayer()
      p.play(Path("missing.wav"), LENGTH)
      p.audible = True   # as if Qt Multimedia had taken the file
      seen: list[str] = []
      p.failed.connect(seen.append)
      p._media_failed(MEDIA_ERROR)
      p._media_failed(MEDIA_ERROR)   # a second report changes nothing
      self.assertEqual(seen, [MEDIA_ERROR])
      self.assertFalse(p.audible)
      self.assertTrue(p.playing())
      p.stop()

   def test_render_bar_reports_the_fallback(self) -> None:
      """!The render bar hands over to the system's player (none offscreen: the playhead runs without sound) and
      shows the media player's error.
      @return None
      """
      bar = audio_common.RenderBar(lambda: None, lambda _result: None)
      bar.player.audible = True
      bar.player._media_failed(MEDIA_ERROR)
      self.assertIn(MEDIA_ERROR, bar.status.text())
      self.assertIn("without sound", bar.status.text())
      bar.deleteLater()


if __name__ == "__main__":
   unittest.main()
