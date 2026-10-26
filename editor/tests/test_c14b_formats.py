#!/usr/bin/env python3
"""![C14b] Without Qt: the studio's cover of engine E1's text and script changes and of the M4 fixes. The text window
port (core.text_window) waits in PAUSE_SOUND on WAIT_SE as window.cpp's Pause::Sound does (the control ends the
typed frame, the frame that sees the sound ended still waits: interval and counter typing), hands PLAY_SE / PLAY_BGM
and the music controls to its PreviewSound, and a preview's PLAY_SE can play for chosen frames; the script editor
offers `wait_sound bgm` (the compiler's SOUND_WAITS) and the engine's compiler takes it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capsule_studio.core import script_words, text_window  # noqa: E402
from test_s6b_formats import A, B, WINDOW, ctl, end, font  # noqa: E402

## A sound number split into its control bytes (low first).
SOUND_LO, SOUND_HI = 0x15, 0x01
## The sound number they make.
SOUND = SOUND_HI << text_window.BYTE_BITS | SOUND_LO
## Frames a counter-typed window reads per code (char_delay 0: one code a frame).
COUNTER = dict(WINDOW, typing=text_window.header_constants()["kTypingCounter"], char_delay=0)
## Frames a silent WAIT_SE adds to interval typing (its read takes a typing slot, the frame that sees the sound
## ended types nothing, then the slot's timer).
INTERVAL_WAIT_FRAMES = 3
## Frames a silent WAIT_SE adds to counter typing (its frame, then the frame that sees the sound ended).
COUNTER_WAIT_FRAMES = 2
## Frames a preview's PLAY_SE plays in the tests.
SE_FRAMES = 6


def done(settings: dict, codes: list[int], se_frames: int = 0) -> int:
   """!The frame a text is done typing (no keys pressed: none of these texts waits for one).
   @param settings   the window
   @param codes      the text
   @param se_frames  frames a PLAY_SE plays
   @return the frame
   """
   r = text_window.run(settings, font(), codes, "advance", se_frames=se_frames)
   assert r.done is not None
   return r.done


class SoundPauseTests(unittest.TestCase):
   """!WAIT_SE and the sound controls in the text window port."""

   def test_interval_wait_se(self) -> None:
      """!Interval typing: a silent WAIT_SE costs its frames; a playing effect holds the text until it ends.
      @return None
      """
      plain = done(WINDOW, end(A, B))
      waited = done(WINDOW, end(A, ctl("wait_se"), B))
      self.assertEqual(waited - plain, INTERVAL_WAIT_FRAMES)
      silent = done(WINDOW, end(A, ctl("se", SOUND_LO, SOUND_HI), ctl("wait_se"), B))
      playing = done(WINDOW, end(A, ctl("se", SOUND_LO, SOUND_HI), ctl("wait_se"), B), SE_FRAMES)
      self.assertEqual(silent, waited)
      self.assertEqual(playing - silent, SE_FRAMES - 1)   # waiting() turns false on the effect's last frame

   def test_counter_wait_se(self) -> None:
      """!Counter typing: WAIT_SE ends the frame it is read in; the frame that sees the sound ended still waits.
      @return None
      """
      plain = done(COUNTER, end(A, B))
      waited = done(COUNTER, end(A, ctl("wait_se"), B))
      self.assertEqual(waited - plain, COUNTER_WAIT_FRAMES)
      playing = done(COUNTER, end(A, ctl("se", SOUND_LO, SOUND_HI), ctl("wait_se"), B), SE_FRAMES)
      self.assertEqual(playing - waited, SE_FRAMES - 1)

   def test_sound_wait_is_busy_not_a_button_wait(self) -> None:
      """!While WAIT_SE waits the window is busy, but it does not wait for a button (no arrow, no press needed).
      @return None
      """
      w = text_window.Window(WINDOW, font(), sound=text_window.PreviewSound(SE_FRAMES))
      w.print(end(ctl("se", SOUND_LO, SOUND_HI), ctl("wait_se"), A))
      w.update()
      self.assertEqual(w.pause, text_window.PAUSE_SOUND)
      self.assertTrue(w.busy())
      self.assertFalse(w.waiting())

   def test_sound_controls_reach_the_sound(self) -> None:
      """!PLAY_SE / PLAY_BGM carry their 16-bit numbers (low byte first); the music controls none; by frame.
      @return None
      """
      codes = end(A, ctl("bgm", SOUND_LO, SOUND_HI), ctl("pause_music"), B, ctl("resume_music"),
                  ctl("se", SOUND_LO, SOUND_HI))
      r = text_window.run(WINDOW, font(), codes, "advance")
      self.assertEqual([(name, arg) for _frame, name, arg in r.sounds],
                       [("bgm", SOUND), ("pause_music", 0), ("resume_music", 0), ("se", SOUND)])
      frames = [frame for frame, _name, _arg in r.sounds]
      self.assertEqual(frames, sorted(frames))
      self.assertLess(frames[0], frames[2])   # B types between the pause and the resume


class ScriptWordTests(unittest.TestCase):
   """!E1's `wait_sound bgm;` in the script editor."""

   def test_wait_sound_bgm_is_offered(self) -> None:
      """!The kinds after wait_sound include bgm, and the engine's compiler takes the statement.
      @return None
      """
      self.assertIn("bgm", script_words.statement_kinds()["wait_sound"])
      self.assertIn("bgm", script_words.completions("script x { wait_sound ", {}))
      sc = script_words.compiler()
      source = "script fade { wait_sound bgm; }\n"
      comp = sc.Compiler({"schema": "capsule.scripts/1", "sources": ["t.cscript"]}, ".", {"t.cscript": source}).run()
      self.assertEqual([d.message for d in comp.diags if d.severity == "error"], [])


if __name__ == "__main__":
   unittest.main()
