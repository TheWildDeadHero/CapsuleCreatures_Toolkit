"""![S7] Playing audio through the engine (engine M4, D-34): the studio builds the engine's apps/audio_render for
the project's audio table and runs it, headless, through the real audio core.

The build. capsule_audio_render(<target> <manifest>) (engine cmake/parts/audio_hal.cmake) makes an audio_render
program for one manifest. The studio configures the engine once into a cache folder (headless, Release, without the
engine's own tests) with a small CMake file of its own run at the end of the engine's configure
(CMAKE_PROJECT_capsule_engine_INCLUDE + cmake_language(DEFER)), which calls it for three targets:

- TABLE_TARGET: the project's manifest as saved (every sound number and clip of the game's table);
- PREVIEW_TARGET (and PREVIEW_HQ_TARGET, the optional high-quality desktop mix): the preview table, a manifest
  the studio writes before each preview from the editor's current data, unsaved edits included: the songs being
  previewed (with muted tracks silenced, core.audio_song.mute()) as sounds 0, 1, ... on their own players, the
  project's mixer, players, voice banks, instrument sets, keymaps and waves, and only the samples the songs'
  instrument sets can reach (so a preview compiles quickly whatever the size of the game's content).

The cache folder is build/audio-studio in the game folder (the one with reference/project.json above the
manifest), else a folder of the user's cache; CAPSULE_STUDIO_AUDIO_CACHE names another. Only the first build
compiles the audio core (seconds); later ones regenerate the preview table and link.

A render writes (apps/audio_render, format §11): out.wav (signed 16-bit stereo, 13,379 Hz; 4x with HQ),
state.jsonl (the core's Snapshot per frame), tones.txt (tone register writes), segments.bin (the 8-bit mix) and
summary.json (frames, the end frames, the L1-L4 hashes; engine C14a: end_frame is the frame whose ticks ran the
last END, status_end_frame the first frame the player's status shows it ended). RenderResult reads them;
StateTimeline keeps what the player-state view draws.

Two sounds at once (the sound effect tester's priority and channel-stealing preview): C14b: Renderer.priority() runs
them in the C++ core (audio_render --sound 0 --then: sound 1 before blank F, on the preview table;
priority_from_render() reads the state), its WAV the core's output. priority_preview() runs them on the engine's
Python reference model of the core (tests/audio_reference.py) with the same rules, for machines without a toolchain
(its WAV: the sampled channels' 8-bit mix); the studio's tests hold the two to the same outcome.

Building needs CMake and a C++ compiler (core.bench.toolchain() says what is missing); everything else works
without them. No Qt.
"""
from __future__ import annotations

import array
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from . import audio, audio_song, bench, engine

## A progress callback: (phase, text); phases are bench.PHASES' configure / build / log / run / done.
Progress = Callable[[str, str], None]

## The project's table as saved.
TABLE_TARGET = "capsule_studio_audio_table"
## The preview table.
PREVIEW_TARGET = "capsule_studio_audio_preview"
## The preview table with the high-quality desktop mix (CAPSULE_AUDIO_HQ).
PREVIEW_HQ_TARGET = "capsule_studio_audio_preview_hq"
## The studio's CMake file in the cache folder (run at the end of the engine's configure).
HOOK_FILE = "studio_audio.cmake"
## The preview table's folder in the cache folder and its manifest.
PREVIEW_FOLDER, PREVIEW_MANIFEST = "preview", "audio.json"
## Render output folders in the cache folder.
RENDER_FOLDER = "renders"
## The cache folder below a game folder.
GAME_CACHE = ("build", "audio-studio")
## Environment variable naming the cache folder.
CACHE_ENV = "CAPSULE_STUDIO_AUDIO_CACHE"
## The user cache below the home folder (XDG_CACHE_HOME, LOCALAPPDATA first).
USER_CACHE = (".cache", "capsule-studio")
## Environment variables naming the user's cache folder, in order.
USER_CACHE_ENVS = ("XDG_CACHE_HOME", "LOCALAPPDATA")
## Hex digits of the hash naming a user-cache folder per manifest.
CACHE_HASH_DIGITS = 12
## Folders above a manifest searched for the game's reference/project.json.
GAME_SEARCH_DEPTH = 6
## A game's project manifest below its folder.
PROJECT_JSON = ("reference", "project.json")
## CMake's cache file (its presence: configured).
CMAKE_CACHE = "CMakeCache.txt"
## Engine options of the cache build.
CMAKE_OPTIONS = ("-DCAPSULE_PLATFORM=headless", "-DCMAKE_BUILD_TYPE=Release", "-DCAPSULE_ENGINE_TESTS=OFF",
                 "-DCAPSULE_TEST_APPS=OFF")
## The folder capsule_audio_table() writes each target's table into (below the cache folder). The engine's custom
## command does not create it, and only Ninja makes an output's folder itself, so the studio makes it.
GENERATED_FOLDER = "generated"
## The generator used when ninja is on the PATH (else CMake's default).
NINJA = "ninja"
## Variable that runs the hook after project(capsule_engine).
HOOK_VARIABLE = "CMAKE_PROJECT_capsule_engine_INCLUDE"
## Environment variable giving cmake --build its job count.
JOBS_ENV = "CMAKE_BUILD_PARALLEL_LEVEL"
## Seconds a render may take.
RENDER_TIMEOUT = 600
## The render's files.
WAV_FILE, STATE_FILE, TONES_FILE, SEGMENTS_FILE, SUMMARY_FILE = ("out.wav", "state.jsonl", "tones.txt",
                                                                 "segments.bin", "summary.json")
## Frames rendered after a sound ends (to hear its release).
DEFAULT_TAIL = 30
## Seconds a render runs at most by default (a looping song renders this long).
DEFAULT_SECONDS = 30
## Frames per second used to turn seconds into a frame limit.
FRAMES_PER_SECOND = 60
## Ticks a note preview holds its key by default.
DEFAULT_NOTE_TICKS = 60
## Frames the two-sound preview runs by default.
DEFAULT_PRIORITY_FRAMES = 300
## The reference model below the engine root.
REFERENCE_MODEL = ("tests", "audio_reference.py")
## Module name the reference model is loaded as.
REFERENCE_MODULE = "capsule_studio_audio_reference"
## C14b: audio_render --then's separator between the sound number and the blank (THEN_SEPARATOR).
THEN_SEPARATOR = "@"
## WAV header fields: RIFF chunk header, fmt chunk size, PCM tag, bytes per s16 sample, bits.
WAV_HEADER_BYTES, WAV_FMT_BYTES, WAV_PCM, S16_BYTES, S16_BITS = 44, 16, 1, 2, 16
## Stereo.
STEREO = 2
## RIFF and WAVE ids, and the bytes of a u32.
RIFF_ID, WAVE_ID, U32_BYTES = b"RIFF", b"WAVE", 4
## An 8-bit mix byte to a 16-bit sample.
BYTE_TO_S16 = 256
## A byte's sign bit and range (the ring holds signed bytes).
SIGN_BIT, BYTE_RANGE = 0x80, 0x100
## Bytes of a RIFF chunk header (id + size).
CHUNK_HEADER = 8
## Offset of the fmt chunk's fields in a WAV: channels, rate, bits (after the 8-byte RIFF and 4-byte WAVE ids).
WAV_CHANNELS_AT, WAV_RATE_AT, WAV_BITS_AT = 22, 24, 34
## Channel status bits (state.h ChannelState::status): any of these set means the channel sounds.
CHANNEL_ON = 0xC7
## Player status: tracks bits, paused bit.
PLAYER_TRACKS, PLAYER_PAUSED = 0xFFFF, 0x80000000
## C15b: TrackState::flags' bit for a track that exists (engine state.h kTrackExists: it runs; its END clears the bit
## at once, the player's status bits follow at the next tick).
TRACK_EXISTS = 0x80
## The reference model's "no channel" index.
NO_CHANNEL = 0xFF
## Characters of a failed step's output kept in its message.
OUTPUT_TAIL = 4000
## Fields of a tones.txt line (frame, register offset, value) and their number base.
TONE_FIELDS, HEX_BASE = 3, 16
## The first tone channel of the core's channel array (12 sampled slots come first).
TONE_CHANNEL_FIRST = 12


class AudioRenderError(audio.AudioError):
   """!A build or render failed; the message says why (the compiler's or the program's output)."""
   pass


class Cancelled(AudioRenderError):
   """!The build or render was cancelled."""
   pass


# -- the cache folder --------------------------------------------------------------------------------------------------

def game_folder_of(manifest: Path | None) -> Path | None:
   """!The game folder a manifest belongs to: the nearest folder above it with reference/project.json.
   @param manifest  the manifest's path, or None
   @return the folder, or None
   """
   if manifest is None:
      return None
   p = Path(manifest).resolve().parent
   for _ in range(GAME_SEARCH_DEPTH):
      if p.joinpath(*PROJECT_JSON).is_file():
         return p
      if p.parent == p:
         break
      p = p.parent
   return None


def cache_folder(manifest: Path | None) -> Path:
   """!Where a manifest's renderer is built (see the module notes).
   @param manifest  the manifest's path, or None (unsaved)
   @return folder
   """
   if os.environ.get(CACHE_ENV):
      return Path(os.environ[CACHE_ENV]).expanduser()
   game = game_folder_of(manifest)
   if game is not None:
      return game.joinpath(*GAME_CACHE)
   root = next((Path(os.environ[v]) for v in USER_CACHE_ENVS if os.environ.get(v)), None)
   root = root / USER_CACHE[-1] if root is not None else Path.home().joinpath(*USER_CACHE)
   name = str(Path(manifest).resolve()) if manifest is not None else "unsaved"
   return root / f"audio-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:CACHE_HASH_DIGITS]}"


def hook_text(table: Path | None, preview: Path) -> str:
   """!The studio's CMake file: after the engine's configure, capsule_audio_render() for the three targets.
   @param table    the project's manifest (None: no table target)
   @param preview  the preview manifest
   @return CMake text
   """
   def quoted(p: Path) -> str:
      """!A CMake string of a path.
      @param p  the path
      @return text
      """
      return '"' + p.as_posix().replace('"', '\\"') + '"'

   lines = ["# Written by the studio (core.audio_render): the audio_render programs of its audio editor.",
            "function(capsule_studio_audio_targets)",
            "   if(NOT COMMAND capsule_audio_render)",
            '      message(FATAL_ERROR "the engine has no capsule_audio_render() (M4 audio)")',
            "   endif()"]
   if table is not None:
      lines.append(f"   capsule_audio_render({TABLE_TARGET} {quoted(table)})")
   lines += [f"   capsule_audio_render({PREVIEW_TARGET} {quoted(preview)})",
             f"   capsule_audio_render({PREVIEW_HQ_TARGET} {quoted(preview)} TRUE)",
             "endfunction()",
             "cmake_language(DEFER CALL capsule_studio_audio_targets)", ""]
   return "\n".join(lines)


# -- the preview table -------------------------------------------------------------------------------------------------

@dataclass
class PreviewSound:
   """!One sound of the preview table."""

   ## The song's key, or None for the empty song.
   song: str | None
   ## The player it plays on (a name of the project's players).
   player: str
   ## Track numbers to silence.
   muted: set[int] = field(default_factory=set)
   ## The song's command bytes and track offsets when it is not a manifest song (a converted MIDI file, a note
   ## preview), or None.
   code: tuple[bytes, list[int]] | None = None
   ## The instrument set of a song given by code.
   instruments: str | None = None
   ## The priority of a song given by code.
   priority: int = 0


def reachable_sets(doc: audio.AudioDocument, roots: Sequence[str]) -> list[str]:
   """!The instrument sets songs can reach: theirs and, through split and drum voices, the sets those name.
   @param doc    AudioDocument
   @param roots  the songs' sets
   @return set keys
   """
   known = audio.known_keys(doc)["instruments"]
   seen: list[str] = []
   todo = [r for r in roots if r in known]
   while todo:
      key = todo.pop()
      if key in seen:
         continue
      seen.append(key)
      for w in audio.window(doc, key, audio.WINDOW_READ):
         v = w.voice
         if isinstance(v, dict) and v.get("kind") in ("split", "drums") and v.get("instruments") in known:
            todo.append(v["instruments"])
   return seen


def reachable_samples(doc: audio.AudioDocument, sets: Sequence[str]) -> set[str]:
   """!The samples the voices of some sets' windows name.
   @param doc   AudioDocument
   @param sets  set keys
   @return sample keys
   """
   out: set[str] = set()
   for key in sets:
      for w in audio.window(doc, key, audio.WINDOW_READ):
         if isinstance(w.voice, dict) and w.voice.get("kind") == "sample" and w.voice.get("sample"):
            out.add(w.voice["sample"])
   return out


def preview_manifest(doc: audio.AudioDocument, sounds: Sequence[PreviewSound], folder: Path,
                     extra_sets: Sequence[dict[str, Any]] = ()) -> tuple[dict[str, Any], bool]:
   """!Writes the preview table for some sounds (see the module notes) into a folder.
   @param doc         AudioDocument (its current data, unsaved edits included)
   @param sounds      the sounds, as sound numbers 0, 1, ...
   @param folder      the preview folder (its audio.json and songs/)
   @param extra_sets  instrument sets with their own voices added for the preview (a note preview's), or none
   @return (the manifest, whether its file changed)
   @throws audio.AudioError when a song cannot be loaded or muted
   """
   data, base = doc.view()
   folder.mkdir(parents=True, exist_ok=True)
   songs_dir = folder / audio.SONG_FOLDER
   songs_dir.mkdir(exist_ok=True)
   entries: list[dict[str, Any]] = []
   by_song: dict[tuple[str, tuple[int, ...]], str] = {}
   table = []
   for s in sounds:
      if s.song is None:
         table.append({"song": None, "player": s.player})
         continue
      tag = (s.song, tuple(sorted(s.muted)))
      if tag not in by_song:
         if s.code is not None:
            src = {"instruments": s.instruments, "priority": s.priority, "reverb": None}
            code, tracks = s.code
         else:
            src = audio.entry(doc, s.song)
            code, tracks = audio.song_code(doc, s.song)
         code, tracks = audio_song.mute(code, tracks, s.muted)
         key = f"song:preview_{len(by_song)}"
         rel = f"{audio.SONG_FOLDER}/preview_{len(by_song)}{audio.SONG_SUFFIX}"
         f = folder / rel
         if not f.is_file() or f.read_bytes() != code:
            f.write_bytes(code)
         entries.append({"key": key, "instruments": src.get("instruments"), "priority": src.get("priority", 0),
                         "reverb": src.get("reverb"), "data": rel, "tracks": tracks})
         by_song[tag] = key
      table.append({"song": by_song[tag], "player": s.player})
   extra_keys = {e["key"] for e in extra_sets}
   roots = [e["instruments"] for e in entries if e["instruments"] not in extra_keys]
   kept: set[str] = set()
   for e in extra_sets:
      for v in e.get("voices", []):
         if isinstance(v, dict) and v.get("kind") in ("split", "drums"):
            roots.append(v.get("instruments"))
         elif isinstance(v, dict) and v.get("kind") == "sample" and v.get("sample"):
            kept.add(v["sample"])
   sets = reachable_sets(doc, roots)
   kept |= reachable_samples(doc, sets)

   def prune(voices: list[Any]) -> list[Any]:
      """!Voices with those naming a sample left out replaced by none voices (no song here reaches them).
      @param voices  the voices
      @return the copy
      """
      return [{"kind": "none"} if isinstance(v, dict) and v.get("kind") == "sample" and v.get("sample") not in kept
              else v for v in voices]

   samples = []
   for e in data.get("samples", []):
      if isinstance(e, dict) and e.get("key") in kept:
         item = dict(e)
         if isinstance(item.get("data"), str):
            item["data"] = str((base / item["data"]).resolve())
         samples.append(item)
   sets_out = []
   for e in list(data.get("instrument_sets", [])) + list(extra_sets):
      sets_out.append(dict(e, voices=prune(e["voices"])) if isinstance(e, dict) and "voices" in e else e)
   manifest = {"schema": audio.SCHEMA, "mixer": data.get("mixer", dict(audio.DEFAULT_MIXER)),
               "players": data.get("players", []), "song_table": table, "samples": samples,
               "waves": data.get("waves", []), "keymaps": data.get("keymaps", []),
               "voice_banks": [dict(b, voices=prune(b.get("voices", []))) for b in data.get("voice_banks", [])],
               "instrument_sets": sets_out, "songs": entries, "clips": []}
   text = json.dumps(manifest, indent=1) + "\n"
   out = folder / PREVIEW_MANIFEST
   changed = not out.is_file() or out.read_text(encoding="utf-8") != text
   if changed:
      out.write_text(text, encoding="utf-8")
   return manifest, changed


## The instrument set a note preview adds (its one voice: the voice played).
NOTE_SET = "instruments:studio_note_preview"
## Volume and velocity of a note preview.
NOTE_VOLUME = 127


def note_sound(doc: audio.AudioDocument, voice: dict[str, Any], key: int, held: int,
               player: str | None = None) -> tuple[PreviewSound, dict[str, Any]]:
   """!A preview that plays one note of a voice (the sample and instrument editors' Play): a one-track song
   holding the key for `held` ticks (a tick a frame at the start tempo) on a set holding only that voice.
   @param doc     AudioDocument
   @param voice   the voice
   @param key     the key played
   @param held    ticks the note is held
   @param player  the player (default the first)
   @return (the PreviewSound, the extra set for preview_manifest())
   @throws audio.AudioError when the voice cannot be played
   """
   f = audio.fmt()
   waits = []
   left = max(held, 1)
   longest = f.LENGTHS[-1]
   while left > 0:
      step = max(n for n in f.LENGTHS if n <= min(left, longest))
      waits.append(f"WAIT {step}")
      left -= step
   text = "\n".join(["TRACK", "PROGRAM 0", f"VOLUME {NOTE_VOLUME}", f"NOTE 0 {key} v{NOTE_VOLUME}", *waits,
                     "NOTE_OFF", "END"]) + "\n"
   try:
      song = f.assemble(text, "note preview")
   except f.FormatError as e:
      raise audio.AudioError(str(e)) from e
   ps = audio.players(doc)
   if not ps:
      raise audio.AudioError("the manifest has no players")
   name = player or str(ps[0].get("name"))
   label = f"song:{voice.get('kind')}_note_{audio.key_name(key)}"
   return (PreviewSound(label, name, set(), (bytes(song.data), list(song.tracks)), NOTE_SET),
           {"key": NOTE_SET, "voices": [voice]})


def empty_preview() -> dict[str, Any]:
   """!The preview table before the first preview (configure needs the file).
   @return manifest
   """
   return audio.empty()


# -- results -----------------------------------------------------------------------------------------------------------

@dataclass
class Wave:
   """!A rendered WAV: interleaved signed 16-bit stereo."""

   ## Samples per second.
   rate: int
   ## Channels (2).
   channels: int
   ## Interleaved samples.
   samples: array.array

   @property
   def frames(self) -> int:
      """!Sample frames (one sample per channel).
      @return count
      """
      w = self   # a local alias (Doxygen reads dataclass fields used in a method as new members)
      return len(w.samples) // max(w.channels, 1)

   @property
   def seconds(self) -> float:
      """!Its length.
      @return seconds
      """
      w = self   # a local alias (Doxygen reads dataclass fields used in a method as new members)
      return w.frames / w.rate if w.rate else 0.0

   def peaks(self, buckets: int) -> list[tuple[int, int]]:
      """!Minimum and maximum of each of `buckets` equal parts (both channels), for a waveform strip.
      @param buckets  parts
      @return (min, max) per part
      """
      w = self   # a local alias (Doxygen reads dataclass fields used in a method as new members)
      n = w.frames
      out = []
      if n == 0 or buckets <= 0:
         return out
      s, ch = w.samples, w.channels
      for b in range(buckets):
         lo, hi = b * n // buckets, max((b + 1) * n // buckets, b * n // buckets + 1)
         part = s[lo * ch:hi * ch]
         out.append((min(part), max(part)) if len(part) else (0, 0))
      return out


def read_wav(path: Path) -> Wave:
   """!Reads audio_render's WAV (16-bit PCM).
   @param path  out.wav
   @return Wave
   @throws AudioRenderError when it is not one
   """
   raw = Path(path).read_bytes()
   wave_at = len(RIFF_ID) + U32_BYTES
   if len(raw) < WAV_HEADER_BYTES or raw[:len(RIFF_ID)] != RIFF_ID or raw[wave_at:wave_at + len(WAVE_ID)] != WAVE_ID:
      raise AudioRenderError(f"{path}: not a WAV file")
   channels = int.from_bytes(raw[WAV_CHANNELS_AT:WAV_CHANNELS_AT + S16_BYTES], "little")
   rate = int.from_bytes(raw[WAV_RATE_AT:WAV_RATE_AT + U32_BYTES], "little")
   bits = int.from_bytes(raw[WAV_BITS_AT:WAV_BITS_AT + S16_BYTES], "little")
   if bits != S16_BITS:
      raise AudioRenderError(f"{path}: {bits}-bit samples (16 expected)")
   at = wave_at + len(WAVE_ID)
   data = b""
   while at + CHUNK_HEADER <= len(raw):
      cid, size = raw[at:at + U32_BYTES], int.from_bytes(raw[at + U32_BYTES:at + CHUNK_HEADER], "little")
      if cid == b"data":
         data = raw[at + CHUNK_HEADER:at + CHUNK_HEADER + size]
         break
      at += CHUNK_HEADER + size + (size & 1)
   samples = array.array("h")
   samples.frombytes(data[:len(data) - len(data) % S16_BYTES])
   if sys.byteorder != "little":
      samples.byteswap()
   return Wave(rate, channels, samples)


def write_wav(path: Path, rate: int, samples: array.array) -> None:
   """!Writes interleaved signed 16-bit stereo as a WAV.
   @param path     the file
   @param rate     samples per second
   @param samples  interleaved samples
   @return None
   """
   body = array.array("h", samples)
   if sys.byteorder != "little":
      body.byteswap()
   data = body.tobytes()
   block = STEREO * S16_BYTES

   def u32(v: int) -> bytes:
      """!A little-endian u32.
      @param v  the value
      @return bytes
      """
      return v.to_bytes(U32_BYTES, "little")

   def u16(v: int) -> bytes:
      """!A little-endian u16.
      @param v  the value
      @return bytes
      """
      return v.to_bytes(S16_BYTES, "little")

   head = (RIFF_ID + u32(WAV_HEADER_BYTES - CHUNK_HEADER + len(data)) + WAVE_ID + b"fmt " + u32(WAV_FMT_BYTES) +
           u16(WAV_PCM) + u16(STEREO) + u32(rate) + u32(rate * block) + u16(block) + u16(S16_BITS) + b"data" +
           u32(len(data)))
   Path(path).write_bytes(head + data)


@dataclass
class ChannelFrame:
   """!One channel in one frame (a slice of state.h ChannelState)."""

   ## Channel index (sampled first, then the 4 tone channels).
   index: int
   ## Status bits (0: idle).
   status: int
   ## Voice kind.
   kind: int
   ## Rank of its track (1-based; 0: none).
   track: int
   ## Key played.
   key: int
   ## Velocity.
   velocity: int
   ## Priority.
   priority: int
   ## Envelope level.
   env: int


@dataclass
class FrameState:
   """!What the player-state view shows of one frame."""

   ## Render frame (1-based blank).
   frame: int
   ## Per player: (sound, status, clock, priority).
   players: list[tuple[int, int, int, int]]
   ## Per track rank: (key, velocity, vol, program, offset).
   tracks: list[tuple[int, int, int, int, int]]
   ## Channels.
   channels: list[ChannelFrame]
   ## C15b: per track rank, whether the track exists (TRACK_EXISTS in its flags: it has not run its END).
   running: list[bool] = field(default_factory=list)


class StateTimeline:
   """!The core's state per frame from state.jsonl, kept compact.

   @var frames
   FrameState per render frame, in order.
   @var owners
   Track rank -> (player index, track index in the player) from the first frame.
   """

   def __init__(self, path: Path, limit: int | None = None) -> None:
      """!Reads the file.
      @param path   state.jsonl
      @param limit  frames to read at most, or None
      """
      ## FrameState per render frame, in order.
      self.frames = []
      ## Track rank -> (player index, track index in the player).
      self.owners = {}
      ## Player names are not in the file; the panel names them from the manifest.
      self.player_count = 0
      with Path(path).open(encoding="utf-8") as f:
         for line in f:
            if limit is not None and len(self.frames) >= limit:
               break
            if line.strip():
               self._add(json.loads(line))

   def _add(self, snap: Mapping[str, Any]) -> None:
      """!Keeps one frame.
      @param snap  the Snapshot JSON
      @return None
      """
      if not self.owners:
         self.player_count = int(snap.get("player_count", 0))
         for i, p in enumerate(snap.get("players", [])):
            for t in range(int(p.get("track_count", 0))):
               self.owners[int(p.get("first_track", 0)) + t + 1] = (i, t)
      players = [(p.get("sound", 0), p.get("status", 0), p.get("clock", 0), p.get("priority", 0))
                 for p in snap.get("players", [])]
      tracks = [(t.get("key", 0), t.get("velocity", 0), t.get("vol", 0), t.get("program", 0), t.get("offset", 0))
                for t in snap.get("tracks", [])]
      chans = [ChannelFrame(c.get("index", i), c.get("status", 0), c.get("kind", 0), c.get("track", 0),
                            c.get("key", 0), c.get("velocity", 0), c.get("priority", 0), c.get("env", 0))
               for i, c in enumerate(snap.get("channels", []))]
      running = [bool(int(t.get("flags", 0)) & TRACK_EXISTS) for t in snap.get("tracks", [])]
      self.frames.append(FrameState(int(snap.get("frame", len(self.frames) + 1)), players, tracks, chans, running))

   def tracks_running(self, frame: int, player: int | None = None) -> int:
      """!C15b: the tracks that exist in a frame (TRACK_EXISTS), of one player or of all.
      @param frame   index into frames
      @param player  player index (owners' first element), or None for every player
      @return count
      """
      fs = self.frames[frame]
      return sum(1 for rank, on in enumerate(fs.running, 1)
                 if on and (player is None or self.owners.get(rank, (None, None))[0] == player))

   def channel_count(self) -> int:
      """!Channels in the snapshots.
      @return count
      """
      return len(self.frames[0].channels) if self.frames else 0

   def sounding(self, frame: int, channel: int) -> ChannelFrame | None:
      """!A channel in a frame when it sounds.
      @param frame    index into frames
      @param channel  index into the frame's channels
      @return ChannelFrame, or None when idle
      """
      c = self.frames[frame].channels[channel]
      return c if c.status & CHANNEL_ON and c.track else None


@dataclass
class RenderResult:
   """!One render's files."""

   ## The output folder.
   folder: Path
   ## summary.json (frames, end_frame, status_end_frame, rate, samples_per_frame, l1..l4; with --then the second
   ## sound's then_end_frame / then_status_end_frame).
   summary: dict[str, Any]
   ## What was rendered ("sound 3 (song:town)").
   what: str = ""
   ## C14b: the two sounds' outcome when this render was Renderer.run_priority()'s, else None.
   priority: PriorityPreview | None = None

   @property
   def wav_path(self) -> Path:
      """!out.wav.
      @return path
      """
      r = self   # a local alias (Doxygen reads dataclass fields used in a method as new members)
      return r.folder / WAV_FILE

   @property
   def state_path(self) -> Path:
      """!state.jsonl.
      @return path
      """
      r = self   # a local alias (Doxygen reads dataclass fields used in a method as new members)
      return r.folder / STATE_FILE

   @property
   def frames(self) -> int:
      """!Frames rendered.
      @return count
      """
      return int(self.summary.get("frames", 0))

   @property
   def end_frame(self) -> int:
      """!The render frame whose ticks ran the sound's last END (engine C14a: exactly midi_song.frames_to_end()'s
      frame + the empty first blank; 0: it did not end within the render).
      @return frame
      """
      return int(self.summary.get("end_frame", 0))

   @property
   def status_end_frame(self) -> int:
      """!C14b (engine C14a): the first render frame whose state shows the player ended (the tick after the last
      END: what a game's IsSEPlaying-style wait sees; 0: it did not end).
      @return frame
      """
      return int(self.summary.get("status_end_frame", 0))

   @property
   def then_end_frame(self) -> int:
      """!C15b (engine C14a): with --then, the render frame whose ticks ran the second sound's last END (0: none, or
      it did not end).
      @return frame
      """
      return int(self.summary.get("then_end_frame", 0))

   @property
   def then_status_end_frame(self) -> int:
      """!C15b (engine C14a): with --then, the first render frame whose state shows the second sound's player ended.
      @return frame
      """
      return int(self.summary.get("then_status_end_frame", 0))

   def wave(self) -> Wave:
      """!The WAV.
      @return Wave
      """
      r = self   # a local alias (Doxygen reads some uses of self.x as new members)
      return read_wav(r.wav_path)

   def timeline(self, limit: int | None = None) -> StateTimeline:
      """!The state per frame.
      @param limit  frames at most
      @return StateTimeline
      @throws AudioRenderError when the render wrote no state
      """
      r = self   # a local alias (Doxygen reads some uses of self.x as new members)
      path = r.state_path
      if not path.is_file():
         raise AudioRenderError("this render has no state (rendered with --no-state)")
      return StateTimeline(path, limit)

   def tones(self) -> list[tuple[int, int, int]]:
      """!The tone register writes.
      @return (frame, register offset, value) per write
      """
      out = []
      p = self.folder / TONES_FILE
      if p.is_file():
         for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == TONE_FIELDS:
               frame, reg, value = parts
               out.append((int(frame), int(reg, HEX_BASE), int(value, HEX_BASE)))
      return out

   def lines(self) -> list[str]:
      """!The summary as text.
      @return lines
      """
      s = self.summary
      end = (f"ends on frame {s.get('end_frame')} (status {s.get('status_end_frame')})" if s.get("end_frame")
             else "did not end")
      out = [f"{self.what}: {s.get('frames')} frames, {end}, {s.get('rate')} Hz"]
      if "then_end_frame" in s:   # C15b: the --then sound's end (a two-sound render)
         then = (f"ends on frame {s.get('then_end_frame')} (status {s.get('then_status_end_frame')})"
                 if s.get("then_end_frame") else "did not end")
         out.append(f"second sound: {then}")
      return out + [f"L1 {s.get('l1')}  L2 {s.get('l2')}  L3 {s.get('l3')}  L4 {s.get('l4')}"]


@dataclass
class RenderOptions:
   """!audio_render's length and output options."""

   ## Seconds rendered at most (a looping song renders this long).
   seconds: int = DEFAULT_SECONDS
   ## Frames after the end.
   tail: int = DEFAULT_TAIL
   ## Mono output.
   mono: bool = False
   ## The high-quality desktop mix (preview only; never for parity).
   hq: bool = False
   ## Write state.jsonl.
   state: bool = True

   def args(self) -> list[str]:
      """!The command line arguments.
      @return arguments
      """
      o = self   # a local alias (Doxygen reads some uses of self.x as new members)
      out = ["--tail", str(o.tail), "--max-frames", str(max(o.seconds, 1) * FRAMES_PER_SECOND)]
      if o.mono:
         out.append("--mono")
      if not o.state:
         out.append("--no-state")
      return out


@dataclass
class ClipOptions:
   """!play_clip()'s parameters (ClipParams)."""

   ## 0-127.
   volume: int = audio.SIGNED_MAX
   ## -64..63.
   pan: int = 0
   ## key x 256 + fine x 2 - 128 (60 x 256 = the voice's base pitch).
   pitch: int = audio.BASE_KEY * BYTE_TO_S16
   ## Ticks before the release.
   hold: int = 0
   ## Envelope release override.
   release: int = 0
   ## 0: one track; else a detuned second track.
   chorus: int = 0
   ## Priority.
   priority: int = 0
   ## Samples skipped.
   offset: int = 0

   def args(self) -> list[str]:
      """!The command line arguments.
      @return arguments
      """
      c = self   # a local alias (Doxygen reads some uses of self.x as new members)
      return ["--clip-volume", str(c.volume), "--clip-pan", str(c.pan), "--clip-pitch", str(c.pitch),
              "--clip-hold", str(c.hold), "--clip-release", str(c.release), "--clip-chorus", str(c.chorus),
              "--clip-priority", str(c.priority), "--clip-offset", str(c.offset)]


# -- building and running -----------------------------------------------------------------------------------------

def toolchain() -> list[str]:
   """!What building the renderer needs and this machine lacks (core.bench.toolchain()).
   @return missing items
   """
   return bench.toolchain()


def _group_options() -> dict[str, Any]:
   """!Popen options that put a child in its own process group (cancel() kills the group).
   @return keyword arguments
   """
   if os.name == "nt":
      return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
   return {"start_new_session": True}


def _kill(proc: subprocess.Popen) -> None:
   """!Kills a child and its process group.
   @param proc  the child
   @return None
   """
   try:
      if os.name == "nt":
         proc.kill()
      else:
         os.killpg(proc.pid, signal.SIGKILL)
   except (OSError, ProcessLookupError):
      pass


def exe_path(folder: Path, target: str) -> Path:
   """!A target's program in the cache folder (single- and multi-configuration generators).
   @param folder  the cache folder
   @param target  the target
   @return the program's path (it may not exist yet)
   """
   suffix = ".exe" if os.name == "nt" else ""
   for p in (folder / f"{target}{suffix}", folder / "Release" / f"{target}{suffix}"):
      if p.is_file():
         return p
   return folder / f"{target}{suffix}"


class Renderer:
   """!Builds and runs the audio_render programs of one manifest; cancel() from any thread stops the step that
   runs (the panels run it on a thread).

   @var folder
   The cache folder.
   """

   def __init__(self, doc: audio.AudioDocument, folder: Path | None = None) -> None:
      """!A renderer for a document.
      @param doc     AudioDocument
      @param folder  the cache folder (default cache_folder())
      """
      ## The document.
      self.doc = doc
      ## The cache folder.
      self.folder = Path(folder) if folder is not None else cache_folder(doc.path)
      ## The child process running now, or None.
      self._proc = None
      ## Guards _proc and _cancelled.
      self._lock = threading.Lock()
      ## Whether cancel() was called since the last reset().
      self._cancelled = False

   def cancel(self) -> None:
      """!Stops the build or render running now.
      @return None
      """
      with self._lock:
         self._cancelled = True
         proc = self._proc
      if proc is not None and proc.poll() is None:
         _kill(proc)

   def reset(self) -> None:
      """!Clears a cancel.
      @return None
      """
      with self._lock:
         self._cancelled = False

   def _run(self, cmd: list[str], env: Mapping[str, str] | None = None, timeout: float | None = None,
            progress: Progress | None = None) -> subprocess.CompletedProcess:
      """!Runs a child to its end, its output lines going to progress (phase "log").
      @param cmd       the command
      @param env       its environment, or None
      @param timeout   seconds, or None
      @param progress  callback, or None
      @return its exit status and output
      @throws Cancelled; AudioRenderError when it cannot start or times out
      """
      with self._lock:
         if self._cancelled:
            raise Cancelled("cancelled")
         try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace",
                                    env=dict(env) if env is not None else None, **_group_options())
         except OSError as e:
            raise AudioRenderError(f"cannot start {Path(cmd[0]).name}: {e}") from e
         self._proc = proc
      lines: list[str] = []
      timer = threading.Timer(timeout, lambda: _kill(proc)) if timeout else None
      if timer is not None:
         timer.start()
      try:
         for line in proc.stdout:
            lines.append(line.rstrip("\n"))
            if progress is not None:
               progress(bench.PHASE_LOG, line.rstrip("\n"))
         proc.wait()
      finally:
         if timer is not None:
            timer.cancel()
         proc.stdout.close()
         with self._lock:
            self._proc = None
      if self._cancelled:
         raise Cancelled("cancelled")
      return subprocess.CompletedProcess(cmd, proc.returncode, "\n".join(lines), "")

   def configure(self, progress: Progress | None = None) -> None:
      """!Writes the hook and configures the cache folder when needed (first time, or when the hook changed).
      @param progress  callback, or None
      @return None
      @throws bench.ToolchainMissing without CMake or a compiler; AudioRenderError when configure fails
      """
      missing = toolchain()
      if missing:
         raise bench.ToolchainMissing(missing)
      self.folder.mkdir(parents=True, exist_ok=True)
      preview = self.folder / PREVIEW_FOLDER / PREVIEW_MANIFEST
      if not preview.is_file():
         preview.parent.mkdir(parents=True, exist_ok=True)
         preview.write_text(json.dumps(empty_preview(), indent=1) + "\n", encoding="utf-8")
      table = self.doc.path if self.doc.path is not None and self.doc.path.is_file() else None
      hook = self.folder / HOOK_FILE
      text = hook_text(table, preview)
      changed = not hook.is_file() or hook.read_text(encoding="utf-8") != text
      if changed:
         hook.write_text(text, encoding="utf-8")
      # the table compiler's output folders (engine C14a's capsule_audio_table() makes them as well; kept for an
      # engine before it, whose Makefile builds failed without them)
      for target in (TABLE_TARGET, PREVIEW_TARGET, PREVIEW_HQ_TARGET):
         (self.folder / GENERATED_FOLDER / target).mkdir(parents=True, exist_ok=True)
      if not changed and (self.folder / CMAKE_CACHE).is_file():
         return
      if progress is not None:
         progress(bench.PHASE_CONFIGURE, "configuring the audio renderer (the first build compiles the engine's "
                                         "audio core: a few seconds)")
      cmd = ["cmake", "-S", str(engine.root()), "-B", str(self.folder), *CMAKE_OPTIONS,
             f"-D{HOOK_VARIABLE}={hook.as_posix()}"]
      if not (self.folder / CMAKE_CACHE).is_file() and shutil.which(NINJA):
         cmd += ["-G", "Ninja"]
      done = self._run(cmd, progress=progress)
      if done.returncode != 0:
         raise AudioRenderError("configure failed:\n" + done.stdout[-OUTPUT_TAIL:])

   def build(self, target: str, progress: Progress | None = None, jobs: int | None = None) -> Path:
      """!Builds one target (configuring first when needed).
      @param target    TABLE_TARGET, PREVIEW_TARGET or PREVIEW_HQ_TARGET
      @param progress  callback, or None
      @param jobs      parallel compile jobs (default every core)
      @return the program
      @throws bench.ToolchainMissing; AudioRenderError with the compiler's output; Cancelled
      """
      if target == TABLE_TARGET and (self.doc.path is None or not self.doc.path.is_file()):
         raise AudioRenderError("the whole table renders the manifest as saved: save it first")
      self.configure(progress)
      if progress is not None:
         progress(bench.PHASE_BUILD, f"building {target}")
      env = dict(os.environ)
      env[JOBS_ENV] = str(jobs if jobs is not None else (os.cpu_count() or 1))
      done = self._run(["cmake", "--build", str(self.folder), "--target", target, "--config", "Release"], env=env,
                       progress=progress)
      if done.returncode != 0:
         raise AudioRenderError(f"building {target} failed:\n" + done.stdout[-OUTPUT_TAIL:])
      exe = exe_path(self.folder, target)
      if not exe.is_file():
         raise AudioRenderError(f"the build made no {exe.name}")
      return exe

   def render(self, exe: Path, args: Sequence[str], out: Path, what: str = "",
              progress: Progress | None = None) -> RenderResult:
      """!Runs an audio_render program.
      @param exe       the program
      @param args      its arguments (without --out)
      @param out       the output folder
      @param what      a label for the result
      @param progress  callback, or None
      @return RenderResult
      @throws AudioRenderError when it fails; Cancelled
      """
      out.mkdir(parents=True, exist_ok=True)
      if progress is not None:
         progress(bench.PHASE_RUN, f"rendering {what}")
      done = self._run([str(exe), *args, "--out", str(out), "--quiet"], timeout=RENDER_TIMEOUT)
      if done.returncode != 0:
         raise AudioRenderError(f"audio_render failed ({done.returncode}): {done.stdout.strip()}")
      try:
         summary = json.loads((out / SUMMARY_FILE).read_text(encoding="utf-8"))
      except (OSError, ValueError) as e:
         raise AudioRenderError(f"audio_render wrote no summary: {e}") from e
      if progress is not None:
         progress(bench.PHASE_DONE, "done")
      return RenderResult(out, summary, what)

   def list_table(self, progress: Progress | None = None) -> dict[str, Any]:
      """!The saved table as the engine compiled it (audio_render --list: sound, player, key hash; players; clips).
      @param progress  callback, or None
      @return the parsed listing
      @throws AudioRenderError when it fails
      """
      exe = self.build(TABLE_TARGET, progress)
      done = self._run([str(exe), "--list"])
      if done.returncode != 0:
         raise AudioRenderError(f"audio_render --list failed: {done.stdout.strip()}")
      return json.loads(done.stdout.strip().splitlines()[-1])

   def preview(self, sounds: Sequence[PreviewSound], play: int = 0, options: RenderOptions | None = None,
               progress: Progress | None = None) -> RenderResult:
      """!Renders one sound of a preview table (the editor's current data).
      @param sounds    the preview table's sounds
      @param play      the one to play
      @param options   RenderOptions (default ones)
      @param progress  callback, or None
      @return RenderResult
      """
      self.prepare(sounds)
      return self.run_preview(sounds, play, options, progress)

   def prepare(self, sounds: Sequence[PreviewSound], extra_sets: Sequence[dict[str, Any]] = ()) -> None:
      """!Writes the preview table from the Document (the part of preview() that reads it: a panel calls this on
      the GUI thread, then run_preview() on a worker thread).
      @param sounds      the preview table's sounds
      @param extra_sets  sets added for the preview (note_sound()'s)
      @return None
      """
      preview_manifest(self.doc, sounds, self.folder / PREVIEW_FOLDER, extra_sets)

   def run_preview(self, sounds: Sequence[PreviewSound], play: int = 0, options: RenderOptions | None = None,
                   progress: Progress | None = None) -> RenderResult:
      """!Builds the preview program and renders a sound of the table prepare() wrote (reads no Document data).
      @param sounds    the sounds given to prepare()
      @param play      the one to play
      @param options   RenderOptions
      @param progress  callback, or None
      @return RenderResult
      """
      o = options or RenderOptions()
      exe = self.build(PREVIEW_HQ_TARGET if o.hq else PREVIEW_TARGET, progress)
      s = sounds[play]
      label = f"{s.song or 'the empty song'} on {s.player}" + (f", tracks {sorted(s.muted)} muted" if s.muted
                                                               else "")
      return self.render(exe, ["--sound", str(play), *o.args()], self.output("preview"), label, progress)

   def note(self, voice: dict[str, Any], key: int = audio.BASE_KEY, held: int = DEFAULT_NOTE_TICKS,
            options: RenderOptions | None = None, progress: Progress | None = None) -> RenderResult:
      """!Renders one note of a voice (note_sound()).
      @param voice     the voice
      @param key       the key
      @param held      ticks held
      @param options   RenderOptions
      @param progress  callback, or None
      @return RenderResult
      """
      sound, extra = note_sound(self.doc, voice, key, held)
      self.prepare([sound], [extra])
      return self.run_preview([sound], 0, options, progress)

   def song(self, key: str, player: str | None = None, muted: set[int] | None = None,
            options: RenderOptions | None = None, progress: Progress | None = None) -> RenderResult:
      """!Renders a song of the manifest on a player (the first table entry's, else the first player).
      @param key       "song:NAME"
      @param player    the player's name, or None
      @param muted     tracks to silence
      @param options   RenderOptions
      @param progress  callback, or None
      @return RenderResult
      """
      return self.preview([PreviewSound(key, player or song_player(self.doc, key), set(muted or ()))], 0,
                          options, progress)

   def sound(self, number: int, options: RenderOptions | None = None, saved: bool = False,
             progress: Progress | None = None) -> RenderResult:
      """!Renders a sound number on its player: from the preview table (current data), or from the saved table.
      @param number    the sound number
      @param options   RenderOptions
      @param saved     True: the whole saved table (TABLE_TARGET)
      @param progress  callback, or None
      @return RenderResult
      @throws audio.AudioError for an unknown number
      """
      rows = audio.sounds(self.doc)
      if not 0 <= number < len(rows):
         raise audio.AudioError(f"sound {number}: the table has {len(rows)} entries")
      row = rows[number]
      o = options or RenderOptions()
      if not saved:
         r = self.preview([PreviewSound(row.song, row.player)], 0, o, progress)
         r.what = f"sound {number} ({row.song}) on {row.player}"
         return r
      exe = self.build(TABLE_TARGET, progress)
      return self.render(exe, ["--sound", str(number), *o.args()], self.output("table"),
                         f"sound {number} ({row.song}) on {row.player}, saved table", progress)

   def clip(self, number: int, clip: ClipOptions | None = None, options: RenderOptions | None = None,
            progress: Progress | None = None) -> RenderResult:
      """!Renders a clip of the saved table (play_clip() with its parameters).
      @param number    the clip's index in the manifest's clips
      @param clip      ClipOptions
      @param options   RenderOptions
      @param progress  callback, or None
      @return RenderResult
      """
      clips = self.doc.data.get("clips", [])
      if not 0 <= number < len(clips):
         raise audio.AudioError(f"clip {number}: the manifest has {len(clips)}")
      exe = self.build(TABLE_TARGET, progress)
      c = clip or ClipOptions()
      o = options or RenderOptions()
      return self.render(exe, ["--clip", str(number), *c.args(), *o.args()], self.output("clip"),
                         f"clip {number} ({clips[number].get('key')}), saved table", progress)

   def priority(self, first: int, second: int, delay: int, frames: int = DEFAULT_PRIORITY_FRAMES,
                progress: Progress | None = None) -> PriorityPreview:
      """!C14b: two sound numbers started `delay` frames apart in the C++ core (audio_render --then): who owns each
      channel (priority and channel stealing between them). prepare_priority() then run_priority().
      @param first     the first sound number
      @param second    the second sound number
      @param delay     frames between them
      @param frames    frames to run
      @param progress  callback, or None
      @return PriorityPreview (its render: the RenderResult, out.wav the core's output)
      @throws audio.AudioError for unknown numbers
      """
      sounds, pid = self.prepare_priority(first, second)
      return self.run_priority(sounds, pid, (first, second), delay, frames, progress)

   def prepare_priority(self, first: int, second: int) -> tuple[list[PreviewSound], list[int]]:
      """!C14b: the part of priority() that reads the Document (the GUI thread): the preview table of the two sounds.
      @param first   the first sound number
      @param second  the second sound number
      @return (the preview table's two sounds, their players' indices)
      @throws audio.AudioError for unknown numbers
      """
      sounds, pid = priority_sounds(self.doc, first, second)
      self.prepare(sounds)
      return sounds, pid

   def run_priority(self, sounds: Sequence[PreviewSound], pid: Sequence[int], numbers: tuple[int, int], delay: int,
                    frames: int = DEFAULT_PRIORITY_FRAMES, progress: Progress | None = None) -> PriorityPreview:
      """!C14b: renders prepare_priority()'s table (no Document access): preview sound 0 with frame 1's calls, sound
      1 with frame 1 + delay's (--then: sound 1 before blank F = FIRST_RENDER_FRAME + delay), for `frames` frames
      after the first.
      @param sounds    prepare_priority()'s sounds
      @param pid       their players' indices
      @param numbers   the two sound numbers of the project's table (for the text)
      @param delay     frames between them
      @param frames    frames to run
      @param progress  callback, or None
      @return PriorityPreview
      """
      exe = self.build(PREVIEW_TARGET, progress)
      first_frame = audio_song.FIRST_RENDER_FRAME
      args = ["--sound", "0", "--then", f"1{THEN_SEPARATOR}{first_frame + delay}",
              "--frames", str(frames + first_frame - 1)]
      label = f"sound {numbers[0]} ({sounds[0].song}), then sound {numbers[1]} ({sounds[1].song}) {delay} later"
      r = self.render(exe, args, self.output("priority"), label, progress)
      pp = priority_from_render(numbers, delay, frames, pid, r)
      r.priority = pp
      return pp

   def output(self, name: str) -> Path:
      """!A render output folder in the cache folder.
      @param name  e.g. "preview"
      @return folder
      """
      return self.folder / RENDER_FOLDER / name


def song_player(doc: audio.AudioDocument, key: str) -> str:
   """!The player a song plays on: the first song table entry naming it, else the first player.
   @param doc  AudioDocument
   @param key  the song
   @return the player's name
   @throws audio.AudioError when there are no players
   """
   for r in audio.sounds(doc):
      if r.song == key and r.player_index >= 0:
         return r.player
   ps = audio.players(doc)
   if not ps:
      raise audio.AudioError("the manifest has no players")
   return str(ps[0].get("name"))


# -- two sounds at once (C14b: the core; the reference model) ----------------------------------------------------------

def reference_model() -> ModuleType:
   """!The engine's Python model of the audio core (tests/audio_reference.py).
   @return module
   @throws AudioRenderError when the engine has none
   """
   if REFERENCE_MODULE in sys.modules:
      return sys.modules[REFERENCE_MODULE]
   path = engine.root().joinpath(*REFERENCE_MODEL)
   if not path.is_file():
      raise AudioRenderError(f"the engine has no {'/'.join(REFERENCE_MODEL)} (the core's reference model)")
   spec = importlib.util.spec_from_file_location(REFERENCE_MODULE, path)
   module = importlib.util.module_from_spec(spec)
   sys.modules[REFERENCE_MODULE] = module
   spec.loader.exec_module(module)
   return module


@dataclass
class Steal:
   """!A channel one sound's note took from another sound's."""

   ## The frame (song frame of the preview: 0 = the first sound's start).
   frame: int
   ## The channel.
   channel: int
   ## (sound, track) that had it.
   lost: tuple[int, int]
   ## (sound, track) that took it.
   taken: tuple[int, int]
   ## Their priorities (lost, taken).
   priorities: tuple[int, int]


@dataclass
class PriorityPreview:
   """!Two sounds started a few frames apart, on the reference model of the core."""

   ## The two sound numbers of the project's table.
   numbers: tuple[int, int]
   ## The frame the second one was started on.
   delay: int
   ## Per frame, per channel: (preview sound 0 / 1, track) owning it while it sounds, or None.
   owners: list[list[tuple[int, int] | None]]
   ## Per frame: whether each sound's player plays it.
   playing: list[tuple[bool, bool]]
   ## Channels taken from one sound by the other.
   steals: list[Steal]
   ## Whether the second sound was refused (its player's start check and a higher-priority song playing).
   refused: bool
   ## The sampled channels' 8-bit mix as interleaved 16-bit stereo.
   samples: array.array
   ## Its rate.
   rate: int
   ## The core's channel index of each owners column (the sampled channels in use, then the 4 tone channels).
   channels: list[int] = field(default_factory=list)
   ## Both sounds are on one player (the second replaces the first; no stealing between them).
   same_player: bool = False
   ## C14b: the render it came from (Renderer.run_priority(): the C++ core), or None (the reference model).
   render: RenderResult | None = None

   def lines(self) -> list[str]:
      """!The outcome as text.
      @return lines
      """
      p = self   # a local alias (Doxygen reads some uses of self.x as new members)
      a, b = p.numbers
      out = [f"sound {a} at frame 0, sound {b} at frame {p.delay}: " +
             ("refused (its player's start check: a higher-priority song was playing)" if p.refused else "started")]
      if p.same_player and not p.refused:
         out.append(f"both play on one player: sound {b} replaced sound {a} at frame {p.delay}")
      for s in p.steals:
         out.append(f"frame {s.frame}: channel {s.channel} taken from sound {p.numbers[s.lost[0]]} track "
                    f"{s.lost[1]} (priority {s.priorities[0]}) by sound {p.numbers[s.taken[0]]} track "
                    f"{s.taken[1]} (priority {s.priorities[1]})")
      if not p.steals and not p.same_player:
         out.append("no channel was taken from a sounding note")
      return out


def priority_preview(doc: audio.AudioDocument, first: int, second: int, delay: int,
                     frames: int = DEFAULT_PRIORITY_FRAMES, folder: Path | None = None) -> PriorityPreview:
   """!Starts two sound numbers `delay` frames apart on the reference model and records who owns each channel
   (priority and channel stealing between them).
   @param doc     AudioDocument (current data)
   @param first   the first sound number
   @param second  the second sound number
   @param delay   frames between them
   @param frames  frames to run
   @param folder  the preview folder (default: the cache folder's)
   @return PriorityPreview
   @throws audio.AudioError for unknown numbers; AudioRenderError without the model
   """
   rows = audio.sounds(doc)
   for n in (first, second):
      if not 0 <= n < len(rows):
         raise audio.AudioError(f"sound {n}: the table has {len(rows)} entries")
   ref = reference_model()
   where = folder if folder is not None else cache_folder(doc.path) / PREVIEW_FOLDER
   sounds = [PreviewSound(rows[first].song, rows[first].player), PreviewSound(rows[second].song, rows[second].player)]
   preview_manifest(doc, sounds, where)
   try:
      model = ref.Model(ref.Table(where / PREVIEW_MANIFEST))
   except Exception as e:   # the model raises the format's errors for a manifest the build would refuse
      raise AudioRenderError(f"the reference model cannot load the preview: {e}") from e
   events = {0: [[0, "play", 0]]}
   events.setdefault(delay, []).append([delay, "play", 1])
   by_rank: dict[int, tuple[int, int]] = {}
   for pi, p in enumerate(model.players):
      for t in range(p.count):
         by_rank[p.first + t + 1] = (pi, t)
   pid = [audio.players(doc).index(next(p for p in audio.players(doc) if p.get("name") == s.player))
          for s in sounds]
   owners, playing, steals = [], [], []
   samples = array.array("h")
   ids = [i for i in range(len(model.chans)) if i < model.channels or i >= TONE_CHANNEL_FIRST]
   last: list[tuple[int, int] | None] = [None] * len(model.chans)
   last_prio = [0] * len(model.chans)
   refused = False
   for f in range(frames):
      for ev in events.get(f, []):
         model.apply(ev)
      model.vsync()
      model.vblank()
      for p in model.players + model.clip_players:
         p.busy = 0
      model.busy = 0
      model.writes = []
      row: list[tuple[int, int] | None] = []
      for ci in ids:
         c = model.chans[ci]
         holder = None   # the track linked to the channel, sounding or not (a note can end in the frame it took it)
         if c.track:
            pi, t = by_rank.get(c.track, (-1, -1))
            sound = next((k for k in (1, 0) if pid[k] == pi and model.players[pi].sound == k), None)
            holder = (sound, t) if sound is not None else None
         owner = holder if c.status & CHANNEL_ON else None
         if holder is not None and last[ci] is not None and last[ci][0] != holder[0] and pid[0] != pid[1]:
            steals.append(Steal(f, ci, last[ci], holder, (last_prio[ci], c.priority)))
         row.append(owner)
         last[ci] = owner
         last_prio[ci] = c.priority if owner is not None else 0
      owners.append(row)
      playing.append(tuple(bool(model.players[pid[k]].sound == k and model.players[pid[k]].status & PLAYER_TRACKS
                                and not model.players[pid[k]].status & PLAYER_PAUSED) for k in (0, 1)))
      if f == delay + 1 and model.players[pid[1]].sound != 1:
         refused = True
      base = model.segment * model.spf
      for i in range(model.spf):
         for side in (model.right, model.left):
            v = side[base + i]
            samples.append((v - BYTE_RANGE if v & SIGN_BIT else v) * BYTE_TO_S16)
   rate = int(doc.data.get("mixer", {}).get("rate", audio.DEFAULT_MIXER["rate"]))
   return PriorityPreview((first, second), delay, owners, playing, steals, refused, samples, rate, ids,
                          pid[0] == pid[1])


def priority_sounds(doc: audio.AudioDocument, first: int, second: int) -> tuple[list[PreviewSound], list[int]]:
   """!C14b: the preview table's two sounds of a priority preview and their players' indices.
   @param doc     AudioDocument
   @param first   the first sound number
   @param second  the second sound number
   @return (sounds, player indices)
   @throws audio.AudioError for unknown numbers
   """
   rows = audio.sounds(doc)
   for n in (first, second):
      if not 0 <= n < len(rows):
         raise audio.AudioError(f"sound {n}: the table has {len(rows)} entries")
   names = [p.get("name") for p in audio.players(doc)]
   sounds = [PreviewSound(rows[n].song, rows[n].player) for n in (first, second)]
   return sounds, [names.index(s.player) for s in sounds]


def priority_from_render(numbers: tuple[int, int], delay: int, frames: int, pid: Sequence[int],
                         result: RenderResult) -> PriorityPreview:
   """!C14b: a PriorityPreview from audio_render's state (state.jsonl) of Renderer.run_priority(), by
   priority_preview()'s rules: preview frame f is render frame f + FIRST_RENDER_FRAME (the first sound's calls come
   before it); a channel's holder is the track linked to it, its owner the holder while the channel sounds; a steal
   is a channel whose holder changes sound between frames (two players); the second sound is refused when its player
   does not play it the frame after its call. The samples are the core's output (out.wav) from preview frame 0.
   @param numbers  the two sound numbers
   @param delay    frames between them
   @param frames   frames run
   @param pid      the two sounds' players' indices
   @param result   the render
   @return PriorityPreview
   @throws AudioRenderError when the render wrote no state
   """
   tl = result.timeline()
   by_frame = {fs.frame: fs for fs in tl.frames}
   first_frame = audio_song.FIRST_RENDER_FRAME
   start = by_frame.get(first_frame)
   ids = [c.index for c in start.channels] if start is not None else []
   owners: list[list[tuple[int, int] | None]] = []
   playing: list[tuple[bool, bool]] = []
   steals: list[Steal] = []
   last: dict[int, tuple[int, int] | None] = {}
   last_prio: dict[int, int] = {}
   refused = False
   for f in range(frames):
      fs = by_frame.get(f + first_frame)
      if fs is None:
         break
      sounds_on = [p[0] for p in fs.players]
      row: list[tuple[int, int] | None] = []
      chans = {c.index: c for c in fs.channels}
      for ci in ids:
         c = chans.get(ci)
         holder = None   # the track linked to the channel, sounding or not (as priority_preview())
         if c is not None and c.track:
            pi, t = tl.owners.get(c.track, (-1, -1))
            sound = next((k for k in (1, 0) if pid[k] == pi and pi < len(sounds_on) and sounds_on[pi] == k), None)
            holder = (sound, t) if sound is not None else None
         owner = holder if c is not None and c.status & CHANNEL_ON else None
         before = last.get(ci)
         if holder is not None and before is not None and before[0] != holder[0] and pid[0] != pid[1]:
            steals.append(Steal(f, ci, before, holder, (last_prio.get(ci, 0), c.priority)))
         row.append(owner)
         last[ci] = owner
         last_prio[ci] = c.priority if owner is not None else 0
      owners.append(row)
      playing.append(tuple(bool(pid[k] < len(fs.players) and fs.players[pid[k]][0] == k and
                                fs.players[pid[k]][1] & PLAYER_TRACKS and not fs.players[pid[k]][1] & PLAYER_PAUSED)
                           for k in (0, 1)))
      if f == delay + 1 and (pid[1] >= len(sounds_on) or sounds_on[pid[1]] != 1):
         refused = True
   wave = result.wave()
   per_frame = int(result.summary.get("output_samples_per_frame", result.summary.get("samples_per_frame", 0)))
   skip = (first_frame - 1) * per_frame * wave.channels   # render frame 1: the empty first blank
   samples = array.array("h", wave.samples[skip:skip + frames * per_frame * wave.channels])
   return PriorityPreview(numbers, delay, owners, playing, steals, refused, samples, wave.rate, ids,
                          pid[0] == pid[1], result)
