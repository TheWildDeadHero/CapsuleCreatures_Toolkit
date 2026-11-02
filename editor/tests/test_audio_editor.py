#!/usr/bin/env python3
"""!audio editor without Qt: the audio manifest model (core.audio: checked edits that format.py refuses,
voices, windows and their overlaps, keymaps, drum sets, waves, samples from WAV files with pending data files,
MIDI import in both forms with the end-tick report, the song table and players, envelope curves), songs
(core.audio_song: notes, tempo map, ends and loops, the mute variant), playback (core.audio_render: the preview
table, the reference model's two-sound preview, and, with CMake and a compiler, renders through the engine's
audio_render: the preview equals the saved table on L2-L4, mutes change it, a note preview, a clip), the
`capsule-studio audio` commands, and the project's "audio" game file.

Content is made by code (tests/audio_fixture.py: simple waveforms, tiny songs and MIDI files).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_fixture as af  # noqa: E402
from capsule_studio.cli.main import main as cli  # noqa: E402
from capsule_studio.core import audio, audio_render as ar, audio_song, project  # noqa: E402
from capsule_studio.core.document import Document, DocumentError  # noqa: E402

## Whether renders can be built here.
CAN_BUILD = not ar.toolchain()
## Why render tests skip.
NO_TOOLCHAIN = "CMake or a C++ compiler is missing: audio_render cannot be built"


def run_cli(*args: str) -> tuple[int, str]:
   """!Runs `capsule-studio` in this process.
   @param args  its arguments
   @return (exit status, stdout + stderr)
   """
   out = io.StringIO()
   with redirect_stdout(out), redirect_stderr(out):
      try:
         status = cli(list(args))
      except SystemExit as e:
         status = int(e.code or 0)
   return status, out.getvalue()


class AudioTestCase(unittest.TestCase):
   """!A fresh tiny game per test; the renderer's cache shared by the class."""

   @classmethod
   def setUpClass(cls) -> None:
      """!The shared cache folder.
      @return None
      """
      cls.cache = Path(tempfile.mkdtemp(prefix="capsule_audio_cache_"))
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
      """!The game.
      @return None
      """
      ## Temporary root.
      self.root = Path(tempfile.mkdtemp(prefix="capsule_s7_"))
      ## The audio manifest.
      self.manifest = af.make_game(self.root)
      ## Its document.
      self.doc = audio.open_audio(self.manifest)

   def tearDown(self) -> None:
      """!Removes the game.
      @return None
      """
      shutil.rmtree(self.root, ignore_errors=True)


class ModelTests(AudioTestCase):
   """!core.audio."""

   def test_fixture_is_valid(self) -> None:
      """!The generated content passes format.py.
      @return None
      """
      self.assertEqual(audio.validate(self.doc), [])
      self.assertEqual(self.doc.schema, audio.SCHEMA)

   def test_new_manifest(self) -> None:
      """!A new manifest is valid and saves.
      @return None
      """
      doc = audio.new_audio(self.root / "new" / "audio.json")
      self.assertEqual(audio.validate(doc), [])
      doc.save()
      self.assertEqual(audio.validate(audio.open_audio(self.root / "new" / "audio.json")), [])

   def test_refused_edit_rolls_back(self) -> None:
      """!An edit that adds a problem is refused and leaves no undo step.
      @return None
      """
      with self.assertRaises(audio.AudioError):
         audio.set_mixer(self.doc, "channels", 99)
      self.assertEqual(self.doc.data["mixer"]["channels"], 5)
      self.assertIsNone(self.doc.undo_label())
      with self.assertRaises(audio.AudioError):
         audio.set_voice_field(self.doc, "instruments:main", 1, "duty", 7)
      with self.assertRaises(audio.AudioError):
         audio.set_voice_field(self.doc, "instruments:main", 0, "sample", "sample:missing")
      self.assertFalse(self.doc.dirty)

   def test_voice_edit_and_undo(self) -> None:
      """!A voice field edit is one undo step; the sets sharing the voice are named.
      @return None
      """
      audio.set_voice_field(self.doc, "instruments:main", 1, "duty", 3)
      self.assertEqual(audio.window_voice(self.doc, "instruments:kit", 1)["duty"], 3)
      self.assertEqual(audio.sets_reading(self.doc, "bank:main", 1), ["instruments:main", "instruments:kit"])
      self.assertTrue(self.doc.undo())
      self.assertEqual(audio.window_voice(self.doc, "instruments:main", 1)["duty"], 2)

   def test_change_kind(self) -> None:
      """!A new voice of another kind keeps the envelope that fits and fills references.
      @return None
      """
      old = audio.window_voice(self.doc, "instruments:main", 1)
      v = audio.new_voice(self.doc, "wave", old)
      self.assertEqual((v["wave"], v["decay"], v["sustain"]), ("wave:tri", 2, 10))
      audio.set_voice(self.doc, "instruments:main", 1, v)
      self.assertEqual(audio.window_voice(self.doc, "instruments:main", 1)["kind"], "wave")
      s = audio.new_voice(self.doc, "sample", v)
      self.assertEqual(s["sample"], "sample:noise")   # the first key in sorted order
      with self.assertRaises(audio.AudioError):
         audio.new_voice(self.doc, "laser")

   def test_sets_banks_and_windows(self) -> None:
      """!Sets with their own voices, bank windows, offsets, overlaps and padding.
      @return None
      """
      own = audio.add_set(self.doc, "lead")
      i = audio.append_voice(self.doc, own, audio.new_voice(self.doc, "square"))
      self.assertEqual(i, 0)
      self.assertEqual(audio.window_voice(self.doc, own, 0)["kind"], "square")
      self.assertIsNone(audio.window_voice(self.doc, own, 1))
      w = audio.add_set(self.doc, "late", "bank:main", 30)
      self.assertEqual(audio.window_voice(self.doc, w, 6)["kind"], "noise")
      self.assertIsNone(audio.window(self.doc, w)[20].voice)   # past the bank
      audio.set_window_offset(self.doc, w, 0)
      bw = audio.bank_windows(self.doc)[0]
      self.assertEqual(bw.length, 39)
      self.assertIn(("instruments:kit", "instruments:late", audio.SET_VOICES), audio.overlaps(bw.windows))
      with self.assertRaises(audio.AudioError):
         audio.append_voice(self.doc, w, audio.new_voice(self.doc, "square"))   # a window: append to the bank
      b = audio.add_bank(self.doc, "extra")
      audio.append_voice(self.doc, b, {"kind": "none"})
      self.assertEqual(audio.validate(self.doc), [])

   def test_keymaps_and_drums(self) -> None:
      """!Key splits as runs, a range set, what a split plays, a drum set's keys.
      @return None
      """
      self.assertEqual(audio.keymap_ranges(audio.entry(self.doc, "keymap:halves")["entries"]),
                       [(0, 59, 0), (60, 127, 4)])
      audio.set_keymap_range(self.doc, "keymap:halves", 72, 83, 1)
      runs = audio.split_targets(self.doc, audio.window_voice(self.doc, "instruments:main", 5))
      self.assertEqual([(a, b, v) for a, b, v, _t in runs], [(0, 59, 0), (60, 71, 4), (72, 83, 1), (84, 127, 4)])
      self.assertEqual(runs[2][3]["kind"], "square")
      with self.assertRaises(audio.AudioError):
         audio.set_keymap_range(self.doc, "keymap:halves", 10, 5, 0)
      drums = dict(audio.drum_map(self.doc, "instruments:kit"))
      self.assertEqual(drums[36]["kind"], "noise")
      self.assertEqual(drums[38]["kind"], "square_sweep")
      k = audio.add_keymap(self.doc, "flat", 2)
      self.assertEqual(audio.keymap_ranges(audio.entry(self.doc, k)["entries"]), [(0, 127, 2)])

   def test_waves_and_references(self) -> None:
      """!A new wave; references block a removal.
      @return None
      """
      key = audio.add_wave(self.doc, "ramp", list(range(16)) * 2)
      self.assertEqual(audio.wave_levels(audio.entry(self.doc, key)["data"])[:3], [0, 1, 2])
      with self.assertRaises(audio.AudioError):
         audio.add_wave(self.doc, "short", [1, 2])
      with self.assertRaises(audio.AudioError):
         audio.remove_entry(self.doc, "wave:tri")
      audio.remove_entry(self.doc, key)
      self.assertNotIn(key, audio.keys(self.doc, "wave"))

   def test_envelopes(self) -> None:
      """!The sampled envelope's arithmetic and the tone envelope's shape.
      @return None
      """
      env = audio.sample_envelope(20, 200, 128, 180, 30)
      self.assertEqual(env[:3], [20, 40, 60])
      self.assertEqual(max(env), 255)
      self.assertEqual(env[29], 128)
      self.assertEqual(env[30], 128 * 180 >> 8)
      self.assertEqual(env[-1], 0)
      self.assertEqual(audio.sample_envelope(255, 0, 255, 0, 5), [255] * 5 + [0])
      tone = audio.tone_envelope(0, 2, 10, 3, 30)
      self.assertEqual(tone[0], 15)
      self.assertEqual(tone[29], (15 * 10 + 15) >> 4)
      self.assertEqual(tone[-1], 0)
      levels, full = audio.envelope_of(audio.window_voice(self.doc, "instruments:main", 1), 10)
      self.assertEqual(full, audio.TONE_GOAL)

   def test_song_table_and_players(self) -> None:
      """!Sound numbers, names, players (a rename follows into the table), the track budget.
      @return None
      """
      rows = audio.sounds(self.doc)
      self.assertEqual((rows[3].song, rows[3].player, rows[3].priority, rows[3].start_check),
                       ("song:fx_high", "sfx2", 10, True))
      self.assertEqual(audio.find_sound(self.doc, "sound:HIGH"), 6)
      self.assertEqual(audio.find_sound(self.doc, "song:kit"), 4)
      self.assertEqual(audio.find_sound(self.doc, "2"), 2)
      n = audio.add_sound(self.doc, "song:loop", "sfx", "LOOPY")
      self.assertEqual(audio.sounds(self.doc)[n].name, "sound:LOOPY")
      audio.set_sound(self.doc, n, None, name=None)
      self.assertIsNone(audio.sounds(self.doc)[n].song)
      with self.assertRaises(audio.AudioError):
         audio.remove_sound(self.doc, 0)
      audio.remove_sound(self.doc, n)
      audio.set_player(self.doc, 1, name="effects", tracks=4, start_check=False)
      self.assertEqual(audio.sounds(self.doc)[2].player, "effects")
      with self.assertRaises(audio.AudioError):
         audio.set_player(self.doc, 0, tracks=40)
      with self.assertRaises(audio.AudioError):
         audio.add_sound(self.doc, "song:tune", "nobody")
      self.assertEqual(audio.track_total(self.doc), 10 + 4 + 3 + audio.CLIP_TRACKS)


class SampleTests(AudioTestCase):
   """!WAV import."""

   def test_import_pcm_with_loop_and_key(self) -> None:
      """!A 16-bit WAV with a smpl loop becomes a looping PCM8 sample; its file waits until save.
      @return None
      """
      wav = self.root / "sine.wav"
      wav.write_bytes(af.wav_bytes("sine", loop=(64, 1023), key=60))
      e = audio.import_wav(self.doc, wav, "sine2", audio.WavOptions())
      self.assertEqual((e["format"], e["loop"], e["loop_start"], e["length"], e["pitch"]),
                       ("pcm8", True, 64, 1024, af.RATE * audio.PITCH_SCALE))
      self.assertIn(e["data"], self.doc.pending_files)
      self.assertFalse((self.manifest.parent / e["data"]).exists())
      self.assertEqual(audio.validate(self.doc), [])   # checked through the scratch copy
      levels = audio.sample_levels(self.doc, "sample:sine2")
      self.assertEqual(len(levels), 1024)
      self.assertEqual(max(levels), int(af.PEAK / 32768 * 128))
      self.doc.save()
      self.assertTrue((self.manifest.parent / e["data"]).is_file())
      self.assertEqual(audio.validate(audio.open_audio(self.manifest)), [])

   def test_import_dpcm_overrides(self) -> None:
      """!DPCM4 with a length, key and tune; the levels decode with dpcm.decode().
      @return None
      """
      wav = self.root / "noise.wav"
      wav.write_bytes(af.wav_bytes("noise", bits=8, length=777))
      o = audio.WavOptions("dpcm4", 1, True, None, 700, 72, 0.0)
      e = audio.import_wav(self.doc, wav, "hiss", o)
      self.assertEqual((e["format"], e["length"]), ("dpcm4", 700))
      self.assertEqual(e["pitch"], audio.pitch_of(af.RATE, 72))
      data = self.doc.pending_files[e["data"]]
      self.assertEqual(audio.sample_levels(self.doc, "sample:hiss"), audio.dpcm().decode(data, 700))

   def test_pitch_of_is_wav_samples(self) -> None:
      """!A review L7: pitch_of() is wav_sample.convert()'s value: rate x 1024 at key 60, an octave up halves it,
      100 cents raise it a semitone, the key is clamped to 0-127.
      @return None
      """
      rate = 8000
      scale = audio.PITCH_SCALE
      self.assertEqual(audio.pitch_of(rate), rate * scale)
      self.assertEqual(audio.pitch_of(rate, audio.BASE_KEY + audio.OCTAVE), rate * scale // 2)
      semitone = 2.0 ** (1 / audio.OCTAVE)
      self.assertEqual(audio.pitch_of(rate, audio.BASE_KEY, 100.0), int(rate * semitone * scale))
      self.assertEqual(audio.pitch_of(rate, 200), audio.pitch_of(rate, 127))

   def test_undo_import_leaves_no_file(self) -> None:
      """!Undoing an import before saving writes nothing.
      @return None
      """
      wav = self.root / "saw.wav"
      wav.write_bytes(af.wav_bytes("saw"))
      e = audio.import_wav(self.doc, wav, "saw", audio.WavOptions())
      self.doc.undo()
      self.doc.save()
      self.assertFalse((self.manifest.parent / e["data"]).exists())

   def test_replace_and_refusals(self) -> None:
      """!A taken name is refused unless replacing; a non-WAV file is refused.
      @return None
      """
      with self.assertRaises(audio.AudioError):
         audio.set_sample_field(self.doc, "sample:sine", "loop_start", 99999)   # past the looping sample's end
      wav = self.root / "a.wav"
      wav.write_bytes(af.wav_bytes("square"))
      with self.assertRaises(audio.AudioError):
         audio.import_wav(self.doc, wav, "sine", audio.WavOptions())
      e = audio.import_wav(self.doc, wav, "sine", audio.WavOptions(), replace=True)
      self.assertEqual(e["data"], "samples/sine.bin")
      bad = self.root / "bad.wav"
      bad.write_bytes(b"not a wav")
      with self.assertRaises(audio.AudioError):
         audio.import_wav(self.doc, bad, "bad", audio.WavOptions())
      with self.assertRaises(audio.AudioError):
         audio.set_sample_field(self.doc, "sample:sine", "speed", 2)


class MidiTests(AudioTestCase):
   """!MIDI import."""

   def test_report(self) -> None:
      """!End ticks, frames to the end, notes before a program change.
      @return None
      """
      song = audio.convert_midi(af.midi_bytes(), audio.midi_options("-E -V100 -Gmain"))
      r = audio.midi_report(song)
      self.assertEqual([t.end_tick for t in r.tracks], [120, 120])
      self.assertEqual(r.frames_to_end, audio.midi().frames_to_end(audio.midi().run_song(song)))
      self.assertEqual([t.before_program for t in r.tracks], [4, 2])
      self.assertIn("before the track's first PROGRAM", "\n".join(r.lines()))
      looped = audio.convert_midi(af.midi_bytes(loop=True, programs=[0, 1]), audio.midi_options("-Gmain"))
      lr = audio.midi_report(looped)
      self.assertIsNone(lr.frames_to_end)
      self.assertEqual([t.before_program for t in lr.tracks], [0, 0])
      self.assertTrue(all(t.loop_tick is not None for t in lr.tracks))

   def test_import_both_forms(self) -> None:
      """!The author form keeps the MIDI file and its options; the compiled form the bytes; both validate.
      @return None
      """
      mid = self.root / "tune.mid"
      mid.write_bytes(af.midi_bytes(programs=[0, 1]))
      e, n = audio.add_midi_song(self.doc, mid, "tune_a", "-V100 -Gmain -P3", player="music", sound_name="TUNE_A")
      self.assertEqual((e["midi"], e["priority"], n), ("songs/tune_a.mid", 3, 7))
      self.assertIn("-P3", e["options"])
      self.assertEqual(audio.sounds(self.doc)[n].name, "sound:TUNE_A")
      e2, n2 = audio.add_midi_song(self.doc, mid, "tune_b", "-Gmain -R40", form="compiled")
      self.assertEqual((e2["reverb"], n2), (40, None))
      a, b = audio.song_code(self.doc, "song:tune_a"), audio.song_code(self.doc, "song:tune_b")
      self.assertEqual(len(a[1]), 2)
      self.assertEqual(len(b[1]), 2)
      self.assertEqual(audio.validate(self.doc), [])
      self.doc.save()
      self.assertTrue((self.manifest.parent / "songs" / "tune_a.mid").is_file())
      self.assertTrue((self.manifest.parent / "songs" / "tune_b.seq").is_file())
      with self.assertRaises(audio.AudioError):
         audio.add_midi_song(self.doc, mid, "tune_a", "")
      bad = self.root / "bad.mid"
      bad.write_bytes(b"MThd")
      with self.assertRaises(audio.AudioError):
         audio.add_midi_song(self.doc, bad, "bad", "")


class SongTests(AudioTestCase):
   """!core.audio_song."""

   def test_notes_ends_and_tempo(self) -> None:
      """!The tune's notes, ends and tempo map; a loop; the kit's transposed keys.
      @return None
      """
      sv = audio_song.song_view(self.doc, "song:tune")
      self.assertEqual([len(v.notes) for v in sv.views], [4, 3, 2])
      self.assertEqual([v.end_tick for v in sv.views], [120, 120, 96])
      self.assertEqual(sv.views[0].notes[3].length, 48)
      self.assertEqual(sv.tempo[0].bpm, 60)
      # TEMPO 60 = a tempo of 120 a frame: 120 ticks end on frame 151 (the counter's rule)
      self.assertEqual(sv.end_frame, 151)
      self.assertEqual(sv.tick_at(sv.frame_of(60)), 60)
      loop = audio_song.song_view(self.doc, "song:loop")
      self.assertTrue(loop.loops)
      self.assertIsNone(loop.end_frame)
      self.assertEqual(loop.views[0].loop_tick, 24)
      text = audio_song.disassembly(loop.data, loop.tracks)
      self.assertIn("JUMP @l", text)
      self.assertEqual(audio_song.listing(loop, 0)[-1].split()[1:3], ["loops", "to"])

   def test_mute_variant(self) -> None:
      """!A muted track runs a copy with VOLUME 0 (jumps retargeted); the bytes stay a valid song.
      @return None
      """
      data, tracks = audio.song_code(self.doc, "song:loop")
      out, t2 = audio_song.mute(data, tracks, {0})
      self.assertEqual(len(out), 2 * len(data))
      self.assertEqual(t2, [tracks[0] + len(data)])
      self.assertEqual(audio.fmt().check_song(out, t2, "muted"), [])
      walked = audio_song.analyse(out, t2)
      self.assertEqual(walked.views[0].loop_to, tracks[0] + len(data) + (audio_song.song_view(
         self.doc, "song:loop").views[0].loop_to - tracks[0]))
      self.assertTrue(any(s.command == audio.midi().VOLUME and s.args == [0] for s in walked.views[0].steps))
      same, t3 = audio_song.mute(data, tracks, set())
      self.assertEqual((same, t3), (data, tracks))
      self.assertEqual(audio_song.solo_mutes(3, {1}, set()), {0, 2})
      self.assertEqual(audio_song.solo_mutes(3, set(), {2}), {2})


class PreviewTests(AudioTestCase):
   """!The preview table and the two-sound preview."""

   def test_preview_table(self) -> None:
      """!Only the samples the songs reach; voices naming others become none; muted tracks point into the copy.
      @return None
      """
      folder = self.root / "preview"
      m, changed = ar.preview_manifest(self.doc, [ar.PreviewSound("song:tune", "music", {2})], folder)
      self.assertTrue(changed)
      self.assertEqual([s["key"] for s in m["samples"]], ["sample:sine", "sample:noise"])   # split reaches noise
      self.assertEqual(m["song_table"], [{"song": "song:preview_0", "player": "music"}])
      self.assertEqual(audio.fmt().validate(m, folder), [])
      _m2, again = ar.preview_manifest(self.doc, [ar.PreviewSound("song:tune", "music", {2})], folder)
      self.assertFalse(again)
      only = {"kind": "sample", "sample": "sample:sine", "key": 60, "attack": 255, "decay": 0, "sustain": 255,
              "release": 0}
      sound, extra = ar.note_sound(self.doc, only, 64, 100)
      m3, _c = ar.preview_manifest(self.doc, [sound], folder, [extra])
      self.assertIn(ar.NOTE_SET, [s["key"] for s in m3["instrument_sets"]])
      self.assertEqual(audio.fmt().validate(m3, folder), [])

   def test_priority_and_stealing(self) -> None:
      """!The high-priority effect on another player takes a channel from the low one; a lower-priority second
      sound on a start-check player is refused; one player replaces.
      @return None
      """
      p = ar.priority_preview(self.doc, 2, 3, 10, 60, self.root / "pp")
      self.assertFalse(p.refused)
      self.assertEqual([(s.frame, s.lost[0], s.taken[0]) for s in p.steals], [(10, 0, 1)])
      self.assertEqual(p.steals[0].priorities, (0, 20))
      self.assertEqual(len(p.samples), 60 * 224 * 2)
      self.assertIn("taken from sound 2", "\n".join(p.lines()))
      refused = ar.priority_preview(self.doc, 6, 2, 5, 40, self.root / "pp")
      self.assertTrue(refused.refused)
      same = ar.priority_preview(self.doc, 3, 3, 5, 40, self.root / "pp")
      self.assertTrue(same.same_player)
      self.assertIn("replaced", "\n".join(same.lines()))


@unittest.skipUnless(CAN_BUILD, NO_TOOLCHAIN)
class RenderTests(AudioTestCase):
   """!Renders through the engine's audio_render (built once per class in the shared cache)."""

   def test_preview_equals_saved_table(self) -> None:
      """!A preview of a sound renders the same mix (L2), tone writes (L3) and output (L4) as the saved table; a
      mute changes the mix; the state and WAV read back.
      @return None
      """
      r = ar.Renderer(self.doc)
      a = r.sound(0)
      b = r.sound(0, saved=True)
      for level in ("l2", "l3", "l4"):
         self.assertEqual(a.summary[level], b.summary[level], level)
      self.assertEqual(a.end_frame, b.end_frame)
      # The song's END runs on song frame 151 = render frame 152 (audio_render's first blank comes before the
      # call); end_frame is that frame exactly, status_end_frame the later one the player's
      # status shows it ended (the tick after the END)
      song_end = audio_song.song_view(self.doc, "song:tune").end_frame + audio_song.FIRST_RENDER_FRAME - 1
      self.assertEqual(a.end_frame, song_end)
      self.assertGreater(a.status_end_frame, a.end_frame)
      muted = r.song("song:tune", muted={0})
      self.assertNotEqual(muted.summary["l2"], a.summary["l2"])
      w = a.wave()
      self.assertEqual((w.rate, w.channels), (13379, 2))
      self.assertEqual(w.frames, a.frames * 224)
      tl = a.timeline()
      self.assertEqual(len(tl.frames), a.frames)
      self.assertEqual(tl.owners[1], (0, 0))
      busy = [f for f in range(len(tl.frames)) if tl.sounding(f, 0)]
      self.assertTrue(busy)
      # Engine kTrackExists: the song's tracks run until the frame whose ticks ran the last END
      self.assertGreater(tl.tracks_running(a.end_frame - 2), 0)
      self.assertEqual(tl.tracks_running(a.end_frame - 1), 0)
      self.assertTrue(a.tones())
      self.assertEqual(r.list_table()["players"], 3)

   def test_priority_in_the_core(self) -> None:
      """!two sounds at once in the C++ core (audio_render --then) give the reference model's outcome: the
      same owners frame by frame, the same steals and refusals; the mix is the render's output from the first
      sound's frame.
      @return None
      """
      r = ar.Renderer(self.doc)
      for first, second, delay, frames in ((2, 3, 10, 60), (6, 2, 5, 40), (3, 3, 5, 40)):
         core = r.priority(first, second, delay, frames)
         model = ar.priority_preview(self.doc, first, second, delay, frames, self.root / "pp")
         where = (first, second, delay)
         self.assertEqual(core.channels, model.channels, where)
         self.assertEqual(core.owners, model.owners, where)
         self.assertEqual(core.playing, model.playing, where)
         self.assertEqual(core.steals, model.steals, where)
         self.assertEqual((core.refused, core.same_player), (model.refused, model.same_player), where)
         self.assertEqual(len(core.samples), len(model.samples), where)
         self.assertIs(core.render.priority, core)
         # The --then sound's end frames are in the summary and its text
         self.assertIn("then_end_frame", core.render.summary, where)
         self.assertTrue([line for line in core.render.lines() if line.startswith("second sound")], where)

   def test_unsaved_edit_previews(self) -> None:
      """!The preview plays unsaved edits; the saved table does not.
      @return None
      """
      r = ar.Renderer(self.doc)
      before = r.sound(0).summary["l2"]
      audio.set_voice_field(self.doc, "instruments:main", 0, "release", 0)
      self.assertNotEqual(r.sound(0).summary["l2"], before)
      self.assertEqual(r.sound(0, saved=True).summary["l2"], before)

   def test_note_and_clip(self) -> None:
      """!One note of a tone voice; a clip of the saved table; the HQ mix keeps the 8-bit ring.
      @return None
      """
      r = ar.Renderer(self.doc)
      n = r.note(audio.window_voice(self.doc, "instruments:main", 1), 60, 20)
      self.assertGreater(n.end_frame, 20)
      hq = r.note(audio.window_voice(self.doc, "instruments:main", 1), 60, 20, ar.RenderOptions(hq=True))
      self.assertEqual(hq.summary["l2"], n.summary["l2"])
      self.assertEqual(hq.wave().rate, 13379 * 4)
      c = r.clip(0, ar.ClipOptions(hold=10))
      self.assertGreater(c.frames, 0)


class CommandTests(AudioTestCase):
   """!`capsule-studio audio`."""

   def test_read_commands(self) -> None:
      """!check, info, songs, song, sets, set, banks, voice, envelope, keymaps, split, drums, waves, samples,
      sample, sounds, players.
      @return None
      """
      m = str(self.manifest)
      for args, expect in ((("check",), "ok"), (("info",), "player 2: sfx2"), (("songs",), "song:kit  asm"),
                           (("song", "song:tune", "--notes", "--tempo"), "TEMPO 60"),
                           (("song", "song:loop", "--commands"), "JUMP @l"),
                           (("song", "song:tune", "--track", "1"), "PROGRAM 1"),
                           (("sets",), "instruments:kit: bank:main from 0"),
                           (("set", "instruments:main", "--count", "8"), "split instruments:main by keymap:halves"),
                           (("banks",), "share 128 voices"), (("voice", "instruments:main", "1"), '"duty": 2'),
                           (("envelope", "instruments:main", "4", "--held", "5"), "level per frame"),
                           (("keymaps",), "c4-g9 -> 4"), (("split", "instruments:main", "5"), "c-1-b3: entry 0"),
                           (("drums", "instruments:kit"), "c2"), (("waves",), "wave:tri"),
                           (("samples",), "sample:noise: pcm8 10512.0 Hz"),
                           (("sample", "sample:sine", "--levels", "4"), "0 20 38 56"),
                           (("sounds",), "sound:HIGH"), (("players",), "sfx2  3 tracks  start check")):
         status, out = run_cli("audio", m, *args)
         self.assertEqual(status, 0, (args, out))
         self.assertIn(expect, out, args)

   def test_edit_commands(self) -> None:
      """!Edits save the manifest; a refused one exits 1 and changes nothing.
      @return None
      """
      m = str(self.manifest)
      wav, mid = self.root / "s.wav", self.root / "t.mid"
      wav.write_bytes(af.wav_bytes("sine", loop=(0, 511), length=512))
      mid.write_bytes(af.midi_bytes(programs=[0, 1]))
      for args in (("set-add", "lead"), ("voice-add", "instruments:lead", "square", "duty=1"),
                   ("voice-set", "instruments:lead", "0", "kind=noise", "period=1"),
                   ("voice-set", "instruments:main", "1", "release=5"),
                   ("keymap-add", "one"), ("keymap-set", "keymap:one", "c4", "c5", "3"),
                   ("wave-add", "ramp", "00112233445566778899AABBCCDDEEFF"),
                   ("bank-add", "spare"), ("set-add", "late", "--bank", "bank:main", "--offset", "10"),
                   ("set-offset", "instruments:late", "12"),
                   ("sample-import", str(wav), "tone", "--key", "c5"),
                   ("sample-set", "sample:tone", "loop_start", "16"),
                   ("midi-import", str(mid), "imported", "--options=-Gmain", "--player", "sfx",
                    "--sound-name", "IMPORTED"),
                   ("midi-import", str(mid), "imported2", "--form", "compiled", "--reverb", "20",
                    "--instruments", "main"),
                   ("song-set", "song:imported", "priority", "7"), ("song-set", "song:tune", "reverb", "none"),
                   ("sound-add", "song:loop", "music"), ("sound-set", "8", "--song", "none", "--name", "-"),
                   ("sound-remove", "8"), ("player-add", "extra", "2", "--start-check"),
                   ("player-set", "3", "--tracks", "1", "--start-check", "no"),
                   ("mixer-set", "master_volume", "10"), ("remove", "wave:ramp")):
         status, out = run_cli("audio", m, *args)
         self.assertEqual(status, 0, (args, out))
      doc = audio.open_audio(self.manifest)
      self.assertEqual(audio.validate(doc), [])
      self.assertEqual(audio.window_voice(doc, "instruments:lead", 0)["kind"], "noise")
      self.assertEqual(audio.entry(doc, "song:imported")["priority"], 7)
      self.assertEqual(audio.sounds(doc)[7].name, "sound:IMPORTED")
      self.assertEqual(audio.entry(doc, "sample:tone")["loop_start"], 16)
      self.assertEqual(doc.data["mixer"]["master_volume"], 10)
      before = self.manifest.read_text(encoding="utf-8")
      status, out = run_cli("audio", m, "voice-set", "instruments:main", "1", "duty=9")
      self.assertEqual(status, 1)
      self.assertIn("duty", out)
      self.assertEqual(self.manifest.read_text(encoding="utf-8"), before)
      status, out = run_cli("audio", m, "midi-import", str(mid), "x", "--report-only", "--listing")
      self.assertEqual(status, 0)
      self.assertIn("end tick 120", out)
      status, out = run_cli("audio", m, "priority", "2", "3", "--delay", "10", "--frames", "40", "--every", "10",
                            "--wav", str(self.root / "p.wav"))
      self.assertEqual(status, 0, out)
      self.assertIn("taken from sound 2", out)
      self.assertEqual(ar.read_wav(self.root / "p.wav").frames, 40 * 224)
      self.assertIn("(run in the C++ core)" if CAN_BUILD else "(run in the reference model)", out)
      status, out = run_cli("audio", m, "priority", "2", "3", "--delay", "10", "--frames", "40", "--model")
      self.assertEqual(status, 0, out)
      self.assertIn("(run in the reference model)", out)
      self.assertIn("taken from sound 2", out)
      status, out = run_cli("audio", m, "sample", "sample:noise", "--png", str(self.root / "w.png"))
      self.assertEqual(status, 0)
      self.assertTrue((self.root / "w.png").is_file())
      status, out = run_cli("audio", str(self.root / "fresh.json"), "new")
      self.assertEqual(status, 0)
      self.assertEqual(run_cli("audio", str(self.root / "fresh.json"), "check")[0], 0)

   @unittest.skipUnless(CAN_BUILD, NO_TOOLCHAIN)
   def test_render_commands(self) -> None:
      """!render (song with solo, sound by name, saved), play, state, build, table.
      @return None
      """
      m = str(self.manifest)
      out_dir = self.root / "render"
      status, out = run_cli("audio", m, "render", "--song", "song:tune", "--solo", "0", "--out", str(out_dir),
                            "--state")
      self.assertEqual(status, 0, out)
      self.assertIn("tracks [1, 2] muted", out)
      self.assertTrue((out_dir / "out.wav").is_file())
      status, out = run_cli("audio", m, "state", str(out_dir), "--frame", "10")
      self.assertEqual(status, 0, out)
      self.assertIn("channel 0: player 0 track 0", out)
      for args in (("render", "--sound", "sound:HIGH"), ("play", "3"), ("render", "--clip", "1"),
                   ("build", "--target", "table"), ("table",)):
         status, out = run_cli("audio", m, *args)
         self.assertEqual(status, 0, (args, out))


class ProjectTests(unittest.TestCase):
   """!The project's "audio" game file."""

   def test_game_file(self) -> None:
      """!project.json's "audio" is a game file, as capsule_audio_game() reads it.
      @return None
      """
      root = Path(tempfile.mkdtemp(prefix="capsule_audio_project_"))
      try:
         manifest = af.make_game(root)
         doc = project.open_project(root / "tiny" / "reference" / "project.json")
         self.assertEqual(project.game_files(doc)["audio"], manifest.resolve())
         self.assertEqual(ar.game_folder_of(manifest), (root / "tiny").resolve())
         self.assertEqual(ar.cache_folder(manifest) if not os.environ.get(ar.CACHE_ENV) else
                          (root / "tiny").resolve().joinpath(*ar.GAME_CACHE), (root / "tiny").resolve().joinpath(
                             *ar.GAME_CACHE))
         with self.assertRaises(DocumentError):
            Document({"schema": "capsule.audio/1"}, None, "capsule.nothing/1")
      finally:
         shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
   unittest.main()
