#!/usr/bin/env python3
"""!S7 (engine M4, D-34) Qt panels: the audio editor's window (ui/audio_shell.py) on a generated tiny game: Songs
(header edits with undo, mute and solo, the commands and tempo views, a render through the engine with the player
state, the output waveform and the playhead, Play without an audio device), Instruments (a voice field, a kind
change, a refused edit, key splits, a drum key opened, the bank view, the envelope), Samples (a WAV converted,
imported, saved, its header edited), MIDI import (options from the form, the report, an import into the song
table), Sound effects (an entry edited, sounds and players added, the mixer, two sounds at once), the problems list,
and the Studio's Audio page. Skipped when PySide6 is missing; uses Qt's offscreen platform. With CAPSULE_SHOTS
naming a folder, each panel's screenshot is saved there.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
   from PySide6 import QtCore, QtWidgets
except ImportError:   # the headless toolkit (core only)
   QtWidgets = None

import audio_fixture as af  # noqa: E402
from capsule_studio.core import audio, audio_render as ar  # noqa: E402

## Where the screenshots go when CAPSULE_SHOTS names a folder.
SHOTS_ENV = "CAPSULE_SHOTS"
## Whether renders can be built here.
CAN_BUILD = not ar.toolchain()
## Seconds a render may take in a test (the first one builds the renderer).
RENDER_WAIT = 300


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed (run in the toolkit environment)")
class QtS7Tests(unittest.TestCase):
   """!Drives the audio editor."""

   @classmethod
   def setUpClass(cls) -> None:
      """!One QApplication; a renderer cache shared by the tests.
      @return None
      """
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
      cls.cache = Path(tempfile.mkdtemp(prefix="capsule_qt_s7_cache_"))
      cls._old_cache = os.environ.get(ar.CACHE_ENV)
      os.environ[ar.CACHE_ENV] = str(cls.cache)

   @classmethod
   def tearDownClass(cls) -> None:
      """!Removes the cache.
      @return None
      """
      if cls._old_cache is None:
         os.environ.pop(ar.CACHE_ENV, None)
      else:
         os.environ[ar.CACHE_ENV] = cls._old_cache
      shutil.rmtree(cls.cache, ignore_errors=True)

   def setUp(self) -> None:
      """!A tiny game; settings in the temporary folder; the window.
      @return None
      """
      from capsule_studio.ui.audio_shell import AudioWindow
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_qt_s7_"))
      QtCore.QSettings.setPath(QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope,
                               str(self.root / "settings"))
      ## The audio manifest.
      self.manifest = af.make_game(self.root)
      ## The window.
      self.w = AudioWindow(str(self.manifest))
      self.w.resize(1500, 900)
      self.w.show()
      self.settle()

   def tearDown(self) -> None:
      """!Closes the window without asking; removes the game.
      @return None
      """
      if self.w.document is not None:
         self.w.document.dirty = False
      self.w.close()
      self.settle()
      shutil.rmtree(self.root, ignore_errors=True)

   def settle(self) -> None:
      """!Runs pending events.
      @return None
      """
      for _ in range(3):
         self.app.processEvents()
         QtCore.QCoreApplication.sendPostedEvents()

   def shot(self, name: str) -> None:
      """!Saves a screenshot when CAPSULE_SHOTS names a folder.
      @param name  file name
      @return None
      """
      folder = os.environ.get(SHOTS_ENV)
      if folder:
         self.settle()
         self.w.grab().save(str(Path(folder) / name))

   def test_window_and_problems(self) -> None:
      """!The window opens the manifest; the problems list says it is good; a bad manifest lists problems.
      @return None
      """
      self.assertEqual(self.w.check(wait=True), [])
      self.assertIn("No problems", self.w.problem_list.item(0).text())
      self.assertIn("audio.json", self.w.windowTitle())
      bad = self.root / "bad.json"
      data = af.manifest(self.root / "bad_audio")
      data["mixer"]["channels"] = 40
      bad.write_text(__import__("json").dumps(data), encoding="utf-8")
      self.w.open_file(str(bad))
      self.assertTrue(any("channels" in p for p in self.w.check(wait=True)))

   def test_songs_panel(self) -> None:
      """!Header edit and undo; mute and solo; commands and tempo; a render with the player state and Play.
      @return None
      """
      p = self.w.show_panel("audio_songs")
      p.select_song("song:tune")
      self.settle()
      self.assertIn("3 tracks", p.info.text())
      self.assertEqual(p.tracks.rowCount(), 3)
      p.priority.setValue(4)
      p.priority.editingFinished.emit()
      self.assertEqual(audio.entry(self.w.document, "song:tune")["priority"], 4)
      self.w._undo_redo(True)
      self.assertEqual(audio.entry(self.w.document, "song:tune")["priority"], 0)
      p.set_mute(2)
      self.assertEqual(p.silenced(), {2})
      p.set_solo(0)
      self.assertEqual(p.silenced(), {1, 2})
      p.set_solo(0, False)
      self.assertEqual(p.roll.muted, {2})
      self.assertIn("TRACK", p.commands.toPlainText())
      p.command_track.setCurrentIndex(2)
      p._show_commands()
      self.assertIn("PROGRAM 1", p.commands.toPlainText())
      self.assertEqual(p.tempo.rowCount(), 1)
      self.shot("s7_songs.png")
      if not CAN_BUILD:
         return
      p.render()
      self.assertTrue(p.bar.wait(RENDER_WAIT))
      self.assertIsNotNone(p.bar.result, p.bar.status.text())
      self.assertIn("tracks [2] muted", p.bar.status.text())
      self.assertIsNotNone(p.timeline)
      p.show_frame(20)
      self.assertGreater(p.channels.rowCount(), 0)
      self.assertTrue(p.wave.levels)
      p._tick(1.0)
      self.assertGreater(p.roll.playhead, 0)
      p.bar.play()
      self.assertFalse(p.bar.player.audible)   # offscreen: the playhead runs without sound
      self.assertTrue(p.bar.player.playing())
      p.bar.stop()
      saved = p.bar.save_wav(str(self.root / "copy.wav"))
      self.assertEqual(ar.read_wav(saved).rate, 13379)
      p.views.setCurrentIndex(3)
      self.shot("s7_songs_state.png")

   def test_instruments_panel(self) -> None:
      """!A voice field (undo), a kind change, a refused edit, a key split, a drum key, the banks, the envelope.
      @return None
      """
      p = self.w.show_panel("audio_instruments")
      p.select("instruments:main", 1)
      self.settle()
      self.assertEqual(p.current_index(), 1)
      self.assertIn("instruments:kit", p.voice_info.text())
      p.fields["duty"].setValue(3)
      p.fields["duty"].editingFinished.emit()
      self.assertEqual(audio.window_voice(self.w.document, "instruments:main", 1)["duty"], 3)
      self.assertTrue(p.envelope.levels)
      steps = self.w.document.undo_label()
      p.set_field("sustain", 99)   # out of range: refused
      self.assertEqual(self.w.document.undo_label(), steps)
      self.assertIn("sustain", self.w.statusBar().currentMessage())
      p.set_kind("noise")
      self.assertEqual(audio.window_voice(self.w.document, "instruments:main", 1)["kind"], "noise")
      self.w._undo_redo(True)
      self.assertEqual(audio.window_voice(self.w.document, "instruments:main", 1)["kind"], "square")
      self.shot("s7_instruments.png")
      p.select("instruments:main", 5)
      p.side.setCurrentIndex(1)
      self.assertEqual(p.split.rowCount(), 2)
      p.set_keys(60, 71, 1)
      self.assertEqual(audio.entry(self.w.document, "keymap:halves")["entries"][65], 1)
      self.assertEqual(p.split.rowCount(), 3)
      self.shot("s7_instruments_split.png")
      p.select("instruments:main", 6)
      self.assertGreater(p.drums.rowCount(), 0)
      row = next(r for r in range(p.drums.rowCount()) if p.drums.item(r, 0).text() == "36")
      p._open_drum(row)
      self.assertEqual((p.current_set(), p.current_index()), ("instruments:kit", 36))
      self.assertEqual(len(p.banks.banks), 1)
      self.assertIn("share", p.overlaps.toPlainText())
      p.new_name.setText("lead")
      p.add_set(own=True)
      self.assertEqual(p.current_set(), "instruments:lead")
      p.append_voice("square")
      self.assertEqual(audio.window_voice(self.w.document, "instruments:lead", 0)["kind"], "square")
      if CAN_BUILD:
         p.play_note()
         self.assertTrue(p.bar.wait(RENDER_WAIT))
         self.assertIsNotNone(p.bar.result, p.bar.status.text())

   def test_samples_panel(self) -> None:
      """!A WAV converted and imported (saved beside the manifest), a header edit.
      @return None
      """
      wav = self.root / "saw.wav"
      wav.write_bytes(af.wav_bytes("saw", loop=(256, 1023)))
      p = self.w.show_panel("audio_samples")
      p.wav_path.setText(str(wav))
      p.name.setText("saw")
      p.format.setCurrentText("dpcm4")
      s = p.convert()
      self.assertEqual((s.format, s.loop_start), ("dpcm4", 256))
      self.assertTrue(p.wave.levels)
      self.assertTrue(p.import_wav())
      self.assertEqual(p.current_key(), "sample:saw")
      self.assertIn("imported", p.info.text())
      self.shot("s7_samples.png")
      self.assertTrue(self.w.save())
      self.assertTrue((self.manifest.parent / "samples" / "saw.bin").is_file())
      p.loop_start.setValue(300)
      p.loop_start.editingFinished.emit()
      self.assertEqual(audio.entry(self.w.document, "sample:saw")["loop_start"], 300)
      p.wav_path.setText(str(self.root / "missing.wav"))
      self.assertIsNone(p.convert())

   def test_midi_panel(self) -> None:
      """!Options from the form, the report, an import into the song table.
      @return None
      """
      mid = self.root / "tune.mid"
      mid.write_bytes(af.midi_bytes())
      p = self.w.show_panel("audio_midi")
      p.path.setText(str(mid))
      p.name.setText("tune_midi")
      p.instruments.setCurrentText("instruments:main")
      p.exact.setChecked(True)
      self.assertIn("-Gmain", p.options.text())
      self.assertIn("-E", p.options.text())
      self.assertIsNotNone(p.convert())
      self.assertIn("end tick 120", p.report.toPlainText())
      self.assertIn("before the track's first PROGRAM", p.report.toPlainText())
      self.assertIn("track 0", p.listing.toPlainText())
      p.player.setCurrentText("sfx")
      self.assertTrue(p.import_song())
      rows = audio.sounds(self.w.document)
      self.assertEqual((rows[-1].song, rows[-1].player), ("song:tune_midi", "sfx"))
      self.shot("s7_midi.png")

   def test_sounds_panel(self) -> None:
      """!An entry edited, a sound and a player added, the mixer, two sounds at once.
      @return None
      """
      p = self.w.show_panel("audio_sounds")
      p.select_sound(1)
      p.player.setCurrentText("sfx")
      p.apply_sound()
      self.assertEqual(audio.sounds(self.w.document)[1].player, "sfx")
      p.song.setCurrentText("song:kit")
      p.add_sound()
      self.assertEqual(audio.sounds(self.w.document)[-1].song, "song:kit")
      p.remove_last()
      self.assertEqual(len(audio.sounds(self.w.document)), 7)
      p.new_player.setText("extra")
      p.add_player()
      self.assertEqual(audio.players(self.w.document)[-1]["name"], "extra")
      p.players.item(3, 1).setText("2")
      self.assertEqual(audio.players(self.w.document)[3]["tracks"], 2)
      p.master.setValue(9)
      p.master.editingFinished.emit()
      self.assertEqual(self.w.document.data["mixer"]["master_volume"], 9)
      p.pages.setCurrentIndex(1)
      p.first.setValue(2)
      p.second.setValue(3)
      p.delay.setValue(10)
      p.frames.setValue(60)
      result = p.preview_priority()
      if CAN_BUILD:   # C14b: the C++ core renders it on the bar's worker
         self.assertIsNone(result)
         self.assertTrue(p.mix_bar.wait(RENDER_WAIT), p.mix_bar.status.text())
         result = p.priority_result
         self.assertIsNotNone(result, p.mix_bar.status.text())
         self.assertIsNotNone(result.render)
         self.assertIn("the C++ core", p.outcome.toPlainText())
      self.assertEqual(len(result.steals), 1)
      self.assertIn("taken from sound 2", p.outcome.toPlainText())
      self.assertTrue(p.mix_bar.result.wav_path.is_file())
      self.shot("s7_sounds.png")
      if CAN_BUILD:
         p.pages.setCurrentIndex(0)
         p.select_sound(3)
         p.play_sound()
         self.assertTrue(p.bar.wait(RENDER_WAIT))
         self.assertIsNotNone(p.bar.result, p.bar.status.text())

   def test_studio_audio_page(self) -> None:
      """!The Studio opens the project's "audio" manifest on its Audio page.
      @return None
      """
      from capsule_studio.ui.studio_shell import StudioWindow
      s = StudioWindow()
      try:
         self.assertTrue(s.open_game(str(self.root / "tiny" / "reference" / "project.json")))
         w = s.window_of("audio")
         self.assertEqual(w.document.path, self.manifest.resolve())
         s.show_page("audio")
         self.settle()
         self.assertEqual(s.current_page_id(), "audio")
      finally:
         for win in s.windows.values():
            doc = getattr(win, "document", None)
            if doc is not None and hasattr(doc, "dirty"):
               doc.dirty = False
         s.close()


if __name__ == "__main__":
   unittest.main()
