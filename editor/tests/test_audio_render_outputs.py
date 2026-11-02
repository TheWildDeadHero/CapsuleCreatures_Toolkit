#!/usr/bin/env python3
"""!Without Qt or a toolchain: the studio's cover of the audio fixes' audio_render outputs. The state timeline
reads TrackState::flags' kTrackExists bit (TRACK_EXISTS: the tracks still running per frame, of one player or all),
and a render's summary text names the --then sound's end frames (then_end_frame / then_status_end_frame).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capsule_studio.core import audio_render as ar  # noqa: E402

## A track's flags with the exists bit and a volume change (state.h: 0x80 exists, 0x03 volume change).
RUNNING_FLAGS = ar.TRACK_EXISTS | 0x03
## Flags of a track whose END ran (only the volume change bits left).
ENDED_FLAGS = 0x03
## The second sound's end frames in the --then summary.
THEN_END, THEN_STATUS_END = 30, 31


def snapshot(frame: int, flags: list[int]) -> dict:
   """!One state.jsonl line: two players (tracks 1-2 the first's, track 3 the second's), no channels.
   @param frame  render frame
   @param flags  each track's flags
   @return the Snapshot JSON
   """
   players = [{"sound": 0, "status": 0, "track_count": 2, "first_track": 0},
              {"sound": 1, "status": 0, "track_count": 1, "first_track": 2}]
   return {"frame": frame, "player_count": len(players), "players": players,
           "tracks": [{"flags": f} for f in flags], "channels": []}


class TrackExistsTests(unittest.TestCase):
   """!StateTimeline.tracks_running() from the flags' TRACK_EXISTS bit."""

   def test_running_tracks_by_player(self) -> None:
      """!A track counts while its exists bit is set, not by its other flags; per player through the owners.
      @return None
      """
      self.assertEqual(ar.TRACK_EXISTS, 0x80)
      with tempfile.TemporaryDirectory() as d:
         path = Path(d) / ar.STATE_FILE
         lines = [snapshot(1, [RUNNING_FLAGS, RUNNING_FLAGS, RUNNING_FLAGS]),
                  snapshot(2, [RUNNING_FLAGS, ENDED_FLAGS, RUNNING_FLAGS]),
                  snapshot(3, [ENDED_FLAGS, ENDED_FLAGS, 0])]
         path.write_text("".join(json.dumps(s) + "\n" for s in lines), encoding="utf-8")
         tl = ar.StateTimeline(path)
      self.assertEqual([tl.tracks_running(f) for f in range(len(tl.frames))], [3, 2, 0])
      self.assertEqual(tl.tracks_running(1, player=0), 1)
      self.assertEqual(tl.tracks_running(1, player=1), 1)
      self.assertEqual(tl.frames[1].running, [True, False, True])


class ThenSummaryTests(unittest.TestCase):
   """!RenderResult with audio_render --then's summary fields."""

   def test_then_end_frames(self) -> None:
      """!The second sound's end frames read back and show in the text; a one-sound render has no such line.
      @return None
      """
      base = {"frames": 40, "end_frame": 20, "status_end_frame": 21, "rate": 13379}
      two = ar.RenderResult(Path("."), dict(base, then_end_frame=THEN_END, then_status_end_frame=THEN_STATUS_END),
                            "two sounds")
      self.assertEqual((two.then_end_frame, two.then_status_end_frame), (THEN_END, THEN_STATUS_END))
      self.assertIn(f"second sound: ends on frame {THEN_END} (status {THEN_STATUS_END})", two.lines())
      still = ar.RenderResult(Path("."), dict(base, then_end_frame=0, then_status_end_frame=0), "two sounds")
      self.assertIn("second sound: did not end", still.lines())
      one = ar.RenderResult(Path("."), base, "one sound")
      self.assertEqual(one.then_end_frame, 0)
      self.assertFalse([line for line in one.lines() if line.startswith("second sound")])


if __name__ == "__main__":
   unittest.main()
