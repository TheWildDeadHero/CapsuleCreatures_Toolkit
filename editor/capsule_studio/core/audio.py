"""![S7] A game's audio manifest (capsule.audio/1, engine M4 / D-34): the model the audio editor and
`capsule-studio audio` share.

The engine's tools/audio/format.py is the one authority on the manifest: its schema, its voices and the song
command stream. Every edit made here is checked with it before it becomes an undo step (an edit that adds a
problem is refused and rolled back); validate() reports the whole manifest's problems the way the build's
compiler (tools/audio_compiler.py) would. The converters A6 wrote are used as they are: wav_sample.py (a WAV to
a sample), dpcm.py (decoding a compressed sample for the waveform view) and midi_song.py (a MIDI file to a song).

What it covers:

- the document: AudioDocument, a Document whose data files (sample bytes, song bytes, MIDI sources) imported
  but not yet saved stay in memory until save(), as imported images do; view() gives the manifest with those
  files on disk (a scratch copy) for checks and renders of unsaved edits;
- instrument sets (a window of 128 voices of a bank, or a set with its own voices), voices, keymaps (key
  splits), drum sets and the windows' overlaps in a bank;
- samples: import from a WAV (wav_sample.convert_entry()), their levels for a waveform view;
- songs: MIDI import (midi_song.convert()) with the end-tick report, and songs added in the compiled form or
  the author form (the MIDI file and its options);
- the song table (sound numbers, the player each plays on, names) and the players;
- envelope curves for the instrument editor's preview.

Qt-free; the panels (ui/editors/audio_*.py) and the commands (cli/audio_cmds.py) use it. Songs and their
playback are core.audio_song and core.audio_render.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import shutil
import sys
import tempfile
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from . import engine
from .document import Document, DocumentError

## Manifest schema.
SCHEMA = "capsule.audio/1"
## The engine's audio tools folder (relative to the engine root).
AUDIO_TOOLS = ("tools", "audio")
## The manifest's sections that list keyed entries, as (section, key kind).
SECTIONS = (("samples", "sample"), ("waves", "wave"), ("keymaps", "keymap"), ("voice_banks", "bank"),
            ("instrument_sets", "instruments"), ("songs", "song"), ("clips", "clip"))
## Section name by key kind.
SECTION_OF = {kind: section for section, kind in SECTIONS}
## Voices in an instrument set's window (format.SET_VOICES).
SET_VOICES = 128
## Voices a window can read: keymap bytes and drum keys go up to 255 (the compiler pads every bank so).
WINDOW_READ = 256
## Keys (MIDI notes 0-127).
KEYS = 128
## Highest key.
MAX_KEY = KEYS - 1
## The base key of voices and samples (key 60 plays a sample at its recorded rate).
BASE_KEY = 60
## Keys per octave.
OCTAVE = 12
## Highest byte.
BYTE_MAX = 255
## Highest u16 (a window's offset in its bank).
U16_MAX = 0xFFFF
## Highest signed byte (a PCM8 byte above it is negative).
SIGNED_MAX = 127
## The sample kind of pitch_of()'s one-sample stand-in recording (any of wav_sample's kinds).
PITCH_PROBE_KIND = "u8"
## Users a refusal names at most.
SHOWN_USERS = 4
## A wave's level digits (hex, high nibble first).
HEX_DIGITS = "0123456789ABCDEF"
## Folder (relative to the manifest) new samples' data files go to.
SAMPLE_FOLDER = "samples"
## Folder (relative to the manifest) new songs' data files and MIDI sources go to.
SONG_FOLDER = "songs"
## Data file suffixes: a sample's bytes, a song's compiled command bytes, its text form, a MIDI source.
SAMPLE_SUFFIX, SONG_SUFFIX, ASM_SUFFIX, MIDI_SUFFIX = ".bin", ".seq", ".cseq", ".mid"
## A manifest entry's fields that name a data file.
DATA_FIELDS = ("data", "asm", "midi")
## Prefix of the scratch folder that holds unsaved data files.
SCRATCH_PREFIX = "capsule_audio_"
## Hex digits of the hash that keeps scratch file names apart.
SCRATCH_HASH_DIGITS = 12
## The form a MIDI import adds a song in: its MIDI file and options, or the converted bytes.
SONG_FORMS = ("midi", "compiled")
## Fields of each voice kind, in the editor's order, with their ranges (low, high); "ref:KIND" names a key.
VOICE_FIELDS: dict[str, tuple[tuple[str, Any], ...]] = {
   "none": (),
   "sample": (("sample", "ref:sample"), ("key", (0, MAX_KEY)), ("fixed_rate", "bool"), ("reverse", "bool"),
              ("attack", (0, BYTE_MAX)), ("decay", (0, BYTE_MAX)), ("sustain", (0, BYTE_MAX)),
              ("release", (0, BYTE_MAX)), ("pan_sweep", (0, BYTE_MAX))),
   "square_sweep": (("duty", (0, 3)), ("sweep", (0, BYTE_MAX)), ("length", (0, 63)), ("key", (0, MAX_KEY)),
                    ("even_pitch", "bool"), ("attack", (0, 7)), ("decay", (0, 7)), ("sustain", (0, 15)),
                    ("release", (0, 7))),
   "square": (("duty", (0, 3)), ("length", (0, 63)), ("key", (0, MAX_KEY)), ("even_pitch", "bool"),
              ("attack", (0, 7)), ("decay", (0, 7)), ("sustain", (0, 15)), ("release", (0, 7)),
              ("pan_sweep", (0, BYTE_MAX))),
   "wave": (("wave", "ref:wave"), ("length", (0, 63)), ("key", (0, MAX_KEY)), ("even_pitch", "bool"),
            ("attack", (0, 7)), ("decay", (0, 7)), ("sustain", (0, 15)), ("release", (0, 7)),
            ("pan_sweep", (0, BYTE_MAX))),
   "noise": (("period", (0, 1)), ("length", (0, 63)), ("key", (0, MAX_KEY)), ("even_pitch", "bool"),
             ("attack", (0, 7)), ("decay", (0, 7)), ("sustain", (0, 15)), ("release", (0, 7)),
             ("pan_sweep", (0, BYTE_MAX))),
   "split": (("instruments", "ref:instruments"), ("keymap", "ref:keymap")),
   "drums": (("instruments", "ref:instruments"),),
}
## Prefix of a VOICE_FIELDS range that names a key of the manifest.
REF_PREFIX = "ref:"
## A boolean voice field.
BOOL_FIELD = "bool"
## A new voice of each kind (the editor's "change kind" starts from it; references filled from the manifest).
NEW_VOICES: dict[str, dict[str, Any]] = {
   "none": {"kind": "none"},
   "sample": {"kind": "sample", "sample": None, "key": BASE_KEY, "attack": BYTE_MAX, "decay": 0, "sustain": BYTE_MAX,
              "release": 0},
   "square_sweep": {"kind": "square_sweep", "duty": 2, "sweep": 0, "length": 0, "key": BASE_KEY, "attack": 0,
                    "decay": 0, "sustain": 15, "release": 0},
   "square": {"kind": "square", "duty": 2, "length": 0, "key": BASE_KEY, "attack": 0, "decay": 0, "sustain": 15,
              "release": 0},
   "wave": {"kind": "wave", "wave": None, "length": 0, "key": BASE_KEY, "attack": 0, "decay": 0, "sustain": 15,
            "release": 0},
   "noise": {"kind": "noise", "period": 0, "length": 0, "key": BASE_KEY, "attack": 0, "decay": 0, "sustain": 15,
             "release": 0},
   "split": {"kind": "split", "instruments": None, "keymap": None},
   "drums": {"kind": "drums", "instruments": None},
}
## The reference field a new voice of a kind takes from the manifest, as (field, key kind).
NEW_VOICE_REFS = {"sample": (("sample", "sample"),), "wave": (("wave", "wave"),),
                  "split": (("instruments", "instruments"), ("keymap", "keymap")),
                  "drums": (("instruments", "instruments"),)}
## The sample playback rate unit: a sample's pitch is its rate in Hz x 1024.
PITCH_SCALE = 1024
## A wave's nibbles (32 4-bit levels).
WAVE_NIBBLES = 32
## A new manifest's mixer (the reference hardware's 13,379 Hz, 5 sampled channels, master volume 12, 8-bit DAC).
DEFAULT_MIXER = {"rate": 13379, "channels": 5, "master_volume": 12, "dac_bits": 8, "output": "stereo"}
## A new manifest's players: music (no start check) and one sound effect player (refuses lower priorities).
DEFAULT_PLAYERS = ({"name": "music", "tracks": 10, "start_check": False},
                   {"name": "sfx", "tracks": 3, "start_check": True})
## Track limits (format.MAX_TRACKS per player, format.MAX_ALL_TRACKS for all with the clip players' 4).
MAX_PLAYER_TRACKS, MAX_ALL_TRACKS, CLIP_TRACKS = 16, 40, 4
## Players a table may have (format.MAX_PLAYERS).
MAX_PLAYERS = 8
## Song priority / reverb limits.
MAX_PRIORITY, MAX_REVERB = 255, 127
## Sampled channels a mixer may have (format.MIN_CHANNELS, MAX_CHANNELS) and its highest master volume.
CHANNEL_RANGE, MAX_MASTER_VOLUME = (1, 12), 15

# Envelope preview (the instrument editor's curve).
## Sampled voices' envelope: full level.
ENVELOPE_FULL = 255
## Bits a sampled envelope multiplication drops (level x factor >> 8).
ENVELOPE_SHIFT = 8
## Tone voices' envelope: the goal of a note at full volume (the tone channels' 4-bit level).
TONE_GOAL = 15
## Bits of the tone sustain level arithmetic (goal x sustain + 15 >> 4).
TONE_SUSTAIN_SHIFT = 4
## Frames an envelope preview shows after the release starts at most.
ENVELOPE_TAIL = 240


class AudioError(DocumentError):
   """!An audio edit or import that cannot be done; the message says why."""
   pass


# -- the engine's tools -----------------------------------------------------------------------------------------------

def tool(name: str) -> ModuleType:
   """!One of the engine's audio tools (tools/audio/NAME.py: format, midi_song, wav_sample, dpcm).
   @param name  module name
   @return the module
   @throws engine.EngineNotFound without an engine checkout
   """
   folder = str(engine.root().joinpath(*AUDIO_TOOLS))
   if folder not in sys.path:
      sys.path.insert(0, folder)
   return importlib.import_module(name)


def fmt() -> ModuleType:
   """!The engine's audio format module (tools/audio/format.py).
   @return module
   """
   return tool("format")


def midi() -> ModuleType:
   """!The engine's MIDI converter (tools/audio/midi_song.py).
   @return module
   """
   return tool("midi_song")


def wav() -> ModuleType:
   """!The engine's WAV converter (tools/audio/wav_sample.py).
   @return module
   """
   return tool("wav_sample")


def dpcm() -> ModuleType:
   """!The engine's DPCM codec (tools/audio/dpcm.py).
   @return module
   """
   return tool("dpcm")


def voice_kinds() -> list[str]:
   """!The voice kinds, in the engine's order (format.VOICE_KINDS).
   @return kind names (none without an engine)
   """
   try:
      return list(fmt().VOICE_KINDS)
   except engine.EngineNotFound:
      return []


def tone_kinds() -> list[str]:
   """!The voice kinds the tone channels play (format.TONE_KINDS).
   @return kind names
   """
   try:
      return list(fmt().TONE_KINDS)
   except engine.EngineNotFound:
      return []


def sample_formats() -> list[str]:
   """!The sample formats (format.SAMPLE_FORMATS).
   @return format names
   """
   try:
      return list(fmt().SAMPLE_FORMATS)
   except engine.EngineNotFound:
      return []


def fmt_rates() -> tuple[int, ...]:
   """!The mixing rates the format allows (format.RATES).
   @return rates in Hz
   """
   try:
      return tuple(fmt().RATES)
   except engine.EngineNotFound:
      return (DEFAULT_MIXER["rate"],)


def key_name(key: int) -> str:
   """!A key's name as the song text form writes it (60 = c4).
   @param key  0-127
   @return e.g. "c4", "fs2"
   """
   return fmt().key_name(key)


# -- the document -----------------------------------------------------------------------------------------------------

def empty() -> dict[str, Any]:
   """!A new manifest: the default mixer and players, nothing else.
   @return the manifest JSON
   """
   return {"schema": SCHEMA, "mixer": dict(DEFAULT_MIXER), "players": [dict(p) for p in DEFAULT_PLAYERS],
           "song_table": [], "samples": [], "waves": [], "keymaps": [], "voice_banks": [], "instrument_sets": [],
           "songs": [], "clips": []}


class AudioDocument(Document):
   """!An audio manifest being edited: a Document whose imported data files wait in memory until save().

   @var pending_files
   Imported data files not yet written: path relative to the manifest -> bytes.
   """

   def __init__(self, data: dict[str, Any] | None = None, path: str | Path | None = None,
                schema: str = SCHEMA) -> None:
      """!Wraps manifest data.
      @param data    parsed manifest, or None for a new one (empty())
      @param path    the file, or None until saved
      @param schema  must be SCHEMA
      """
      super().__init__(data if data is not None else empty(), path, schema)
      ## Imported data files not yet written: path relative to the manifest -> bytes.
      self.pending_files = {}
      ## Scratch folder holding the pending files for view() (made on first use, removed with the Document).
      self._scratch = None

   def data_paths(self) -> list[str]:
      """!The data files the manifest names (samples' and songs' data, text forms and MIDI sources).
      @return paths relative to the manifest, in manifest order
      """
      out = []
      manifest = self.data   # a local alias (Doxygen reads some uses of self.x as new members)
      for section in ("samples", "songs"):
         for e in manifest.get(section, []):
            for name in DATA_FIELDS:
               if isinstance(e, dict) and isinstance(e.get(name), str):
                  out.append(e[name])
      return out

   def file_bytes(self, rel: str) -> bytes:
      """!A data file's bytes: the pending import, else the file beside the manifest.
      @param rel  path relative to the manifest
      @return the bytes
      @throws AudioError when the file cannot be read
      """
      pending = self.pending_files   # a local alias ("in self.x": Doxygen reads a new member)
      if rel in pending:
         return pending[rel]
      if self.base_dir is None:
         raise AudioError(f"{rel}: the manifest has not been saved yet")
      try:
         return (self.base_dir / rel).read_bytes()
      except OSError as e:
         raise AudioError(f"{rel}: {e}") from e

   def add_file(self, rel: str, data: bytes) -> None:
      """!Keeps an imported data file until save() (call inside edit()).
      @param rel   path relative to the manifest
      @param data  its bytes
      @return None
      """
      self.pending_files[rel] = bytes(data)

   def unique_file(self, folder: str, stem: str, suffix: str) -> str:
      """!A data file name not used by the manifest, a pending file or a file on disk.
      @param folder  folder relative to the manifest ("samples")
      @param stem    wanted name
      @param suffix  e.g. ".bin"
      @return path relative to the manifest
      """
      used = set(self.data_paths()) | set(self.pending_files)
      n = 0
      while True:
         rel = f"{folder}/{stem}{'' if n == 0 else '_' + str(n)}{suffix}"
         on_disk = self.base_dir is not None and (self.base_dir / rel).exists()
         if rel not in used and not on_disk:
            return rel
         n += 1

   def save(self, path: str | Path | None = None) -> None:
      """!Writes the pending data files the manifest still names, then the manifest.
      @param path  new file path ("save as"), or None for the current one
      @return None
      """
      target = Path(path).resolve() if path is not None else self.path
      if target is None:
         raise DocumentError("no file name; pass a path")
      used = set(self.data_paths())
      pending = self.pending_files   # a local alias (Doxygen reads some uses of self.x as new members)
      for rel, data in list(pending.items()):
         if rel in used:
            out = target.parent / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
      pending.clear()
      super().save(path)

   def scratch(self) -> Path:
      """!The scratch folder of this Document's pending files (removed when the Document goes).
      @return folder
      """
      if self._scratch is None:
         folder = tempfile.mkdtemp(prefix=SCRATCH_PREFIX)
         self._scratch = Path(folder)
         weakref.finalize(self, shutil.rmtree, folder, True)
      return self._scratch

   def view(self) -> tuple[dict[str, Any], Path]:
      """!The manifest as the engine's tools read it, unsaved edits included: pending data files are written to
      the scratch folder and named by absolute path in a copy.
      @return (manifest JSON, its base folder)
      @throws AudioError for a manifest without a file and with relative data paths
      """
      base = self.base_dir or self.scratch()
      pending, manifest = self.pending_files, self.data   # local aliases ("in self.x": Doxygen reads new members)
      if not pending:
         return manifest, base
      out = copy.deepcopy(manifest)
      used = set(self.data_paths())
      names: dict[str, str] = {}
      for rel, data in pending.items():
         if rel not in used:
            continue
         digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:SCRATCH_HASH_DIGITS]
         f = self.scratch() / f"{digest}_{Path(rel).name}"
         if not f.is_file() or f.read_bytes() != data:
            f.write_bytes(data)
         names[rel] = str(f)
      for section in ("samples", "songs"):
         for e in out.get(section, []):
            for name in DATA_FIELDS:
               if isinstance(e, dict) and e.get(name) in names:
                  e[name] = names[e[name]]
      return out, base


def open_audio(path: str | Path) -> AudioDocument:
   """!Opens an audio manifest (saved in its own json layout when it has one, e.g. an importer's).
   @param path  audio.json
   @return AudioDocument
   @throws DocumentError when it cannot be read or is not an audio manifest
   """
   try:
      return AudioDocument.open(path, SCHEMA, keep_layout=True)
   except (OSError, ValueError) as e:
      raise DocumentError(f"cannot read {path}: {e}") from e


def new_audio(path: str | Path | None = None) -> AudioDocument:
   """!A new audio manifest.
   @param path  where it will be saved, or None
   @return AudioDocument
   """
   return AudioDocument(None, path)


# -- checks -----------------------------------------------------------------------------------------------------------

def validate(doc: AudioDocument) -> list[str]:
   """!The manifest's problems, as the engine's format.validate() finds them (unsaved data files included).
   @param doc  AudioDocument
   @return problems (empty: the build's compiler takes it)
   """
   data, base = doc.view()
   return fmt().validate(data, base)


def known_keys(doc: AudioDocument) -> dict[str, set[str]]:
   """!The manifest's keys by kind (format's KINDS).
   @param doc  AudioDocument
   @return kind -> keys
   """
   out: dict[str, set[str]] = {kind: set() for _section, kind in SECTIONS}
   for section, kind in SECTIONS:
      for e in doc.data.get(section, []):
         if isinstance(e, dict) and isinstance(e.get("key"), str):
            out[kind].add(e["key"])
   return out


def keys(doc: AudioDocument, kind: str) -> list[str]:
   """!The keys of one kind, in manifest order.
   @param doc   AudioDocument
   @param kind  "sample", "wave", "keymap", "bank", "instruments", "song" or "clip"
   @return keys
   """
   return [e["key"] for e in doc.data.get(SECTION_OF[kind], []) if isinstance(e, dict) and "key" in e]


def voice_problems(doc: AudioDocument, voice: Any, where: str = "voice") -> list[str]:
   """!A voice's problems (format.check_voice() with the manifest's keys).
   @param doc    AudioDocument
   @param voice  the voice object
   @param where  location for messages
   @return problems
   """
   errors: list[str] = []
   fmt().check_voice(voice, where, known_keys(doc), errors)
   return errors


def checked_edit(doc: AudioDocument, label: str, change: Any, full: bool = True) -> None:
   """!Runs an edit as one undo step and checks the result with format.py: an edit that adds problems is
   refused (the manifest is put back) and AudioError lists them.
   @param doc     AudioDocument
   @param label   undo label
   @param change  callable(data) making the change
   @param full    True: compare format.validate() before and after; False: the caller checked what it changed
   @return None
   @throws AudioError when the edit adds problems
   """
   before = set(problems_of(doc)) if full else set()
   after: list[str] = []
   with doc.edit(label) as data:
      change(data)
      if full:
         after = validate(doc)
         added = [p for p in after if p not in before]
         if added:
            raise AudioError(f"{label}: " + "; ".join(added))
   if full:
      _PROBLEMS[doc] = (doc.revision, after)   # the next edit starts from these (a large manifest checks in a second)


## The latest validate() of each Document: (its revision then, the problems).
_PROBLEMS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def problems_of(doc: AudioDocument) -> list[str]:
   """!validate(), reused while the Document has not changed since.
   @param doc  AudioDocument
   @return problems
   """
   cached = _PROBLEMS.get(doc)
   if cached is not None and cached[0] == doc.revision:
      return cached[1]
   found = validate(doc)
   _PROBLEMS[doc] = (doc.revision, found)
   return found


def entry(doc: AudioDocument, key: str) -> dict[str, Any]:
   """!An entry by key, in the section its kind names.
   @param doc  AudioDocument
   @param key  e.g. "song:town"
   @return the entry (live: change it inside edit())
   @throws AudioError when there is none
   """
   kind = key.split(":", 1)[0]
   section = SECTION_OF.get(kind)
   if section is None:
      raise AudioError(f"{key!r}: an audio key starts with one of {', '.join(SECTION_OF)}:")
   for e in doc.data.get(section, []):
      if isinstance(e, dict) and e.get("key") == key:
         return e
   raise AudioError(f"no {key} in the manifest")


def check_new_key(doc: AudioDocument, key: str, kind: str) -> None:
   """!Checks a key for a new entry.
   @param doc   AudioDocument
   @param key   the key
   @param kind  the kind it must have
   @return None
   @throws AudioError when it is malformed or taken
   """
   if not key.startswith(f"{kind}:") or len(key) == len(kind) + 1:
      raise AudioError(f"{key!r}: the key must look like {kind}:NAME")
   if key in known_keys(doc)[kind]:
      raise AudioError(f"{key} already exists")


def full_key(name: str, kind: str) -> str:
   """!NAME or KIND:NAME as KIND:NAME.
   @param name  the name
   @param kind  the key kind
   @return the key
   """
   return name if name.startswith(f"{kind}:") else f"{kind}:{name}"


def remove_entry(doc: AudioDocument, key: str) -> None:
   """!Removes an entry; refused while something names it.
   @param doc  AudioDocument
   @param key  its key
   @return None
   @throws AudioError when it is used or missing
   """
   e = entry(doc, key)
   users = references(doc, key)
   if users:
      raise AudioError(f"{key} is used by " + ", ".join(users[:SHOWN_USERS]) +
                       (" ..." if len(users) > SHOWN_USERS else ""))
   section = SECTION_OF[key.split(":", 1)[0]]
   checked_edit(doc, f"Remove {key}", lambda data: data[section].remove(e))


def references(doc: AudioDocument, key: str) -> list[str]:
   """!What names a key: voices, sets, songs, clips and the song table.
   @param doc  AudioDocument
   @param key  e.g. "sample:bell"
   @return where it is named
   """
   out = []

   def look(v: Any, where: str) -> None:
      """!One voice.
      @param v      the voice
      @param where  its location
      @return None
      """
      if isinstance(v, dict) and key in (v.get("sample"), v.get("wave"), v.get("instruments"), v.get("keymap")):
         out.append(where)

   for bank in doc.data.get("voice_banks", []):
      for i, v in enumerate(bank.get("voices", [])):
         look(v, f"{bank.get('key')} voice {i}")
   for s in doc.data.get("instrument_sets", []):
      if s.get("bank") == key:
         out.append(s.get("key"))
      for i, v in enumerate(s.get("voices", [])):
         look(v, f"{s.get('key')} voice {i}")
   for s in doc.data.get("songs", []):
      if s.get("instruments") == key:
         out.append(s.get("key"))
   for c in doc.data.get("clips", []):
      look(c.get("voice"), c.get("key"))
      if c.get("reverse_of") == key:
         out.append(c.get("key"))
   for i, e in enumerate(doc.data.get("song_table", [])):
      if isinstance(e, dict) and e.get("song") == key:
         out.append(f"sound {i}")
   return out


# -- instrument sets, banks and voices ---------------------------------------------------------------------------------

@dataclass
class WindowEntry:
   """!One entry of an instrument set's window: the voice a PROGRAM (or a keymap byte, a drum key) reads."""

   ## Its index in the window (0-255).
   index: int
   ## The bank the voice is in (the set's own key for a set with its own voices).
   container: str
   ## Its index in that bank's voices, or -1 past the end (the compiler's padding: a none voice).
   position: int
   ## The voice, or None for padding.
   voice: dict[str, Any] | None


def instrument_sets(doc: AudioDocument) -> list[dict[str, Any]]:
   """!The instrument sets, in manifest order.
   @param doc  AudioDocument
   @return set entries (live)
   """
   return [s for s in doc.data.get("instrument_sets", []) if isinstance(s, dict)]


def bank(doc: AudioDocument, key: str) -> dict[str, Any]:
   """!A voice bank by key.
   @param doc  AudioDocument
   @param key  "bank:NAME"
   @return the bank (live)
   @throws AudioError when there is none
   """
   return entry(doc, key)


def set_voices(doc: AudioDocument, set_key: str) -> tuple[str, list[Any], int]:
   """!Where a set's window reads its voices.
   @param doc      AudioDocument
   @param set_key  "instruments:NAME"
   @return (container key, the container's voice list (live), the window's offset in it)
   @throws AudioError for an unknown set or bank
   """
   s = entry(doc, set_key)
   if "voices" in s:
      return set_key, s["voices"], 0
   b = bank(doc, s.get("bank", ""))
   return b["key"], b.setdefault("voices", []), int(s.get("offset", 0))


def window(doc: AudioDocument, set_key: str, count: int = SET_VOICES) -> list[WindowEntry]:
   """!A set's window: the voices its programs (and keymap bytes, drum keys) read.
   @param doc      AudioDocument
   @param set_key  the set
   @param count    entries (SET_VOICES; WINDOW_READ for what keymaps and drum keys can reach)
   @return one WindowEntry per index
   """
   container, voices, offset = set_voices(doc, set_key)
   out = []
   for i in range(count):
      at = offset + i
      if at < len(voices):
         out.append(WindowEntry(i, container, at, voices[at]))
      else:
         out.append(WindowEntry(i, container, -1, None))
   return out


def window_voice(doc: AudioDocument, set_key: str, index: int) -> dict[str, Any] | None:
   """!The voice at one index of a set's window.
   @param doc      AudioDocument
   @param set_key  the set
   @param index    0-255
   @return the voice (live), or None past the bank's end
   """
   return window(doc, set_key, index + 1)[index].voice


def sets_reading(doc: AudioDocument, container: str, position: int) -> list[str]:
   """!The sets whose windows (SET_VOICES entries) include a bank voice: editing it changes each of them.
   @param doc        AudioDocument
   @param container  the bank's key (or a set's own key)
   @param position   the voice's index in it
   @return set keys
   """
   out = []
   for s in instrument_sets(doc):
      if s.get("key") == container and "voices" in s:
         out.append(s["key"])
      elif s.get("bank") == container:
         offset = int(s.get("offset", 0))
         if offset <= position < offset + SET_VOICES:
            out.append(s["key"])
   return out


def set_voice(doc: AudioDocument, set_key: str, index: int, voice: dict[str, Any]) -> None:
   """!Replaces the voice at an index of a set's window (the bank's voice: every set reading it sees the
   change); an index just past a set's own voices appends one. Checked with format.check_voice().
   @param doc      AudioDocument
   @param set_key  the set
   @param index    0-127
   @param voice    the new voice
   @return None
   @throws AudioError when the voice has problems or the index is past the end
   """
   if not 0 <= index < SET_VOICES:
      raise AudioError(f"voice {index}: a set's window has {SET_VOICES} entries")
   problems = voice_problems(doc, voice, f"{set_key} voice {index}")
   if problems:
      raise AudioError("; ".join(problems))
   container, voices, offset = set_voices(doc, set_key)
   at = offset + index
   if at > len(voices):
      raise AudioError(f"{set_key} voice {index}: past the end of {container} ({len(voices)} voices); "
                       "add voices first")

   def change(data: dict[str, Any]) -> None:
      """!Writes the voice.
      @param data  the manifest
      @return None
      """
      _c, live, _o = set_voices(doc, set_key)
      if at == len(live):
         live.append(copy.deepcopy(voice))
      else:
         live[at] = copy.deepcopy(voice)
   checked_edit(doc, f"Voice {index} of {set_key}", change, full=False)


def set_voice_field(doc: AudioDocument, set_key: str, index: int, name: str, value: Any) -> None:
   """!Changes one field of a window's voice (None removes it).
   @param doc      AudioDocument
   @param set_key  the set
   @param index    0-127
   @param name     the field
   @param value    its new value
   @return None
   @throws AudioError when there is no voice there or the result has problems
   """
   v = window_voice(doc, set_key, index)
   if v is None:
      raise AudioError(f"{set_key} voice {index}: no voice there")
   new = dict(v)
   if value is None:
      new.pop(name, None)
   else:
      new[name] = value
   set_voice(doc, set_key, index, new)


def new_voice(doc: AudioDocument, kind: str, like: dict[str, Any] | None = None) -> dict[str, Any]:
   """!A new voice of a kind, its references filled with the manifest's first keys, the envelope kept from
   another voice where both kinds have one.
   @param doc   AudioDocument
   @param kind  one of voice_kinds()
   @param like  the voice it replaces, or None
   @return the voice
   @throws AudioError for an unknown kind
   """
   if kind not in NEW_VOICES:
      raise AudioError(f"voice kind must be one of {', '.join(voice_kinds())}")
   v = copy.deepcopy(NEW_VOICES[kind])
   have = known_keys(doc)
   for name, ref_kind in NEW_VOICE_REFS.get(kind, ()):
      first = sorted(have[ref_kind])
      v[name] = (like or {}).get(name) if (like or {}).get(name) in have[ref_kind] else (first[0] if first else None)
   if like:
      ranges = dict(VOICE_FIELDS[kind])
      for name, r in ranges.items():
         if name in like and isinstance(r, tuple) and isinstance(like[name], int) and r[0] <= like[name] <= r[1]:
            v[name] = like[name]
   return v


def voice_summary(voice: dict[str, Any] | None) -> str:
   """!One line about a voice, for lists.
   @param voice  the voice, or None (padding past a bank's end)
   @return text
   """
   if voice is None:
      return "(past the bank: none)"
   kind = voice.get("kind", "?")
   env = "/".join(str(voice.get(n, 0)) for n in ("attack", "decay", "sustain", "release"))
   if kind == "none":
      return "none"
   if kind == "sample":
      flags = "".join(f" {f}" for f in ("fixed_rate", "reverse") if voice.get(f))
      return f"sample {voice.get('sample')} key {voice.get('key', BASE_KEY)} ADSR {env}{flags}"
   if kind in ("square_sweep", "square"):
      sweep = f" sweep {voice.get('sweep', 0)}" if kind == "square_sweep" else ""
      return f"{kind} duty {voice.get('duty', 0)}{sweep} key {voice.get('key', BASE_KEY)} ADSR {env}"
   if kind == "wave":
      return f"wave {voice.get('wave')} key {voice.get('key', BASE_KEY)} ADSR {env}"
   if kind == "noise":
      return f"noise period {voice.get('period', 0)} key {voice.get('key', BASE_KEY)} ADSR {env}"
   if kind == "split":
      return f"split {voice.get('instruments')} by {voice.get('keymap')}"
   if kind == "drums":
      return f"drums {voice.get('instruments')}"
   return kind


def add_set(doc: AudioDocument, name: str, bank_key: str | None = None, offset: int = 0) -> str:
   """!A new instrument set: a window of a bank at an offset, or (bank_key None) a set with its own voices.
   @param doc       AudioDocument
   @param name      NAME or instruments:NAME
   @param bank_key  the bank, or None
   @param offset    the window's first voice in the bank
   @return the set's key
   @throws AudioError when the key is taken or the bank unknown
   """
   key = full_key(name, "instruments")
   check_new_key(doc, key, "instruments")
   item: dict[str, Any] = {"key": key, "voices": []} if bank_key is None else {"key": key, "bank": bank_key,
                                                                                "offset": offset}
   checked_edit(doc, f"Add {key}", lambda data: data.setdefault("instrument_sets", []).append(item))
   return key


def add_bank(doc: AudioDocument, name: str) -> str:
   """!A new, empty voice bank.
   @param doc   AudioDocument
   @param name  NAME or bank:NAME
   @return its key
   @throws AudioError when the key is taken
   """
   key = full_key(name, "bank")
   check_new_key(doc, key, "bank")
   checked_edit(doc, f"Add {key}", lambda data: data.setdefault("voice_banks", []).append({"key": key, "voices": []}))
   return key


def append_voice(doc: AudioDocument, container: str, voice: dict[str, Any]) -> int:
   """!Appends a voice to a bank or to a set with its own voices.
   @param doc        AudioDocument
   @param container  "bank:NAME" or "instruments:NAME"
   @param voice      the voice
   @return its index in the container
   @throws AudioError when it has problems or the set is a window
   """
   e = entry(doc, container)
   if container.startswith("instruments:") and "voices" not in e:
      raise AudioError(f"{container} is a window of {e.get('bank')}: append to the bank")
   voices = e.get("voices", [])
   if container.startswith("instruments:") and len(voices) >= SET_VOICES:
      raise AudioError(f"{container} has {SET_VOICES} voices already")
   problems = voice_problems(doc, voice, f"{container} voice {len(voices)}")
   if problems:
      raise AudioError("; ".join(problems))
   index = len(voices)
   checked_edit(doc, f"Add voice to {container}", lambda data: entry(doc, container).setdefault(
      "voices", []).append(copy.deepcopy(voice)), full=False)
   return index


def set_window_offset(doc: AudioDocument, set_key: str, offset: int) -> None:
   """!Moves a bank window.
   @param doc      AudioDocument
   @param set_key  the set
   @param offset   its new first voice
   @return None
   @throws AudioError for a set with its own voices or a bad offset
   """
   e = entry(doc, set_key)
   if "bank" not in e:
      raise AudioError(f"{set_key} has its own voices, not a window")
   checked_edit(doc, f"Window of {set_key}", lambda data: e.__setitem__("offset", offset))


@dataclass
class BankWindows:
   """!A bank and the windows sets read from it (the instrument editor's bank view)."""

   ## The bank's key.
   key: str
   ## Its voices.
   length: int
   ## (set key, first voice, voices) per window, by offset.
   windows: list[tuple[str, int, int]] = field(default_factory=list)


def bank_windows(doc: AudioDocument) -> list[BankWindows]:
   """!Every bank with the windows of the sets that read it (overlapping windows share voices: a program past a
   short set reads its neighbour, as the original layout did).
   @param doc  AudioDocument
   @return one BankWindows per bank
   """
   out = []
   for b in doc.data.get("voice_banks", []):
      bw = BankWindows(b.get("key", "?"), len(b.get("voices", [])))
      for s in instrument_sets(doc):
         if s.get("bank") == bw.key:
            bw.windows.append((s["key"], int(s.get("offset", 0)), SET_VOICES))
      bw.windows.sort(key=lambda w: (w[1], w[0]))
      out.append(bw)
   return out


def overlaps(windows: list[tuple[str, int, int]]) -> list[tuple[str, str, int]]:
   """!The pairs of windows that share voices.
   @param windows  (set key, first voice, voices) as BankWindows lists them
   @return (set, set, shared voices) per overlapping pair
   """
   out = []
   for i, (a, a0, an) in enumerate(windows):
      for b, b0, bn in windows[i + 1:]:
         shared = min(a0 + an, b0 + bn) - max(a0, b0)
         if shared > 0:
            out.append((a, b, shared))
   return out


# -- keymaps and drum sets -------------------------------------------------------------------------------------------

def keymap_ranges(entries: list[int]) -> list[tuple[int, int, int]]:
   """!A keymap as key splits: runs of keys that pick the same entry.
   @param entries  128 entries
   @return (first key, last key, entry) per run
   """
   out: list[tuple[int, int, int]] = []
   for k, v in enumerate(entries):
      first, last, value = out[-1] if out else (0, -1, None)
      if out and value == v and last == k - 1:
         out[-1] = (first, k, v)
      else:
         out.append((k, k, v))
   return out


def add_keymap(doc: AudioDocument, name: str, value: int = 0) -> str:
   """!A new keymap with every key on one entry.
   @param doc    AudioDocument
   @param name   NAME or keymap:NAME
   @param value  the entry every key picks
   @return its key
   @throws AudioError when the key is taken
   """
   key = full_key(name, "keymap")
   check_new_key(doc, key, "keymap")
   checked_edit(doc, f"Add {key}", lambda data: data.setdefault("keymaps", []).append(
      {"key": key, "entries": [value] * KEYS}))
   return key


def set_keymap_range(doc: AudioDocument, key: str, first: int, last: int, value: int) -> None:
   """!Sets the entry of a range of keys (a key split).
   @param doc    AudioDocument
   @param key    the keymap
   @param first  first key
   @param last   last key (inclusive)
   @param value  the entry (0-255: an index into the split voice's set)
   @return None
   @throws AudioError for keys or a value out of range
   """
   if not 0 <= first <= last <= MAX_KEY:
      raise AudioError(f"keys {first}-{last}: keys are 0-{MAX_KEY}, first <= last")
   if not 0 <= value <= BYTE_MAX:
      raise AudioError(f"entry {value}: 0-{BYTE_MAX}")
   e = entry(doc, key)

   def change(data: dict[str, Any]) -> None:
      """!Writes the entries.
      @param data  the manifest
      @return None
      """
      for k in range(first, last + 1):
         e["entries"][k] = value
   checked_edit(doc, f"Keys {key_name(first)}-{key_name(last)} of {key}", change)


def split_targets(doc: AudioDocument, voice: dict[str, Any]) -> list[tuple[int, int, int, dict[str, Any] | None]]:
   """!What a split voice plays per key split: the keymap's runs with the voice each entry picks.
   @param doc    AudioDocument
   @param voice  a split voice
   @return (first key, last key, entry, the target set's voice or None) per run
   """
   km = entry(doc, voice["keymap"])
   out = []
   for first, last, value in keymap_ranges(km["entries"]):
      out.append((first, last, value, window(doc, voice["instruments"], value + 1)[value].voice))
   return out


def drum_map(doc: AudioDocument, set_key: str) -> list[tuple[int, dict[str, Any] | None]]:
   """!A drum set's keys: a drums voice plays entry `key` of its set at that entry's own key and pan.
   @param doc      AudioDocument
   @param set_key  the drum set (the drums voice's instruments)
   @return (key, voice or None) for keys 0-127
   """
   return [(w.index, w.voice) for w in window(doc, set_key, KEYS)]


# -- waves ------------------------------------------------------------------------------------------------------------

def wave_levels(text: str) -> list[int]:
   """!A wave's 32 levels (hex nibbles, high nibble first).
   @param text  the 32 hex digits
   @return levels 0-15
   """
   return [HEX_DIGITS.index(c.upper()) for c in text]


def add_wave(doc: AudioDocument, name: str, levels: list[int]) -> str:
   """!A new wave from 32 levels.
   @param doc     AudioDocument
   @param name    NAME or wave:NAME
   @param levels  32 values 0-15
   @return its key
   @throws AudioError for a bad pattern or a taken key
   """
   key = full_key(name, "wave")
   check_new_key(doc, key, "wave")
   if len(levels) != WAVE_NIBBLES or any(not 0 <= v < len(HEX_DIGITS) for v in levels):
      raise AudioError(f"a wave has {WAVE_NIBBLES} levels 0-{len(HEX_DIGITS) - 1}")
   text = "".join(HEX_DIGITS[v] for v in levels)
   checked_edit(doc, f"Add {key}", lambda data: data.setdefault("waves", []).append({"key": key, "data": text}))
   return key


# -- samples ----------------------------------------------------------------------------------------------------------

@dataclass
class WavOptions:
   """!How a WAV becomes a sample (wav_sample.convert_entry()'s author fields)."""

   ## "pcm8" or "dpcm4".
   format: str = "pcm8"
   ## DPCM search depth (1-8).
   lookahead: int = 1
   ## DPCM: whole blocks.
   pad: bool = True
   ## Loop start (turns the loop on), or None for the file's own loop.
   loop_start: int | None = None
   ## Loop end / length (samples played), or None for the file's.
   length: int | None = None
   ## Base key override, or None for the file's (60).
   key: int | None = None
   ## Tuning in cents, or None for the file's.
   tune_cents: float | None = None

   def entry(self, wav_name: str) -> dict[str, Any]:
      """!The author-form entry wav_sample.convert_entry() reads.
      @param wav_name  the WAV file, relative to its folder
      @return the entry
      """
      o = self   # a local alias (Doxygen reads some uses of self.x as new members)
      out: dict[str, Any] = {"wav": wav_name, "format": o.format, "lookahead": o.lookahead, "pad": o.pad}
      for name in ("loop_start", "length", "key", "tune_cents"):
         if getattr(o, name) is not None:
            out[name] = getattr(o, name)
      return out


def convert_wav(path: str | Path, options: WavOptions) -> Any:
   """!Converts a WAV file (wav_sample.convert_entry()).
   @param path     the WAV
   @param options  WavOptions
   @return wav_sample.Sample
   @throws AudioError when the file is not a WAV the converter reads
   """
   p = Path(path)
   w = wav()
   if options.format not in sample_formats():
      raise AudioError(f"format must be one of {', '.join(sample_formats())}")
   try:
      return w.convert_entry(options.entry(p.name), p.parent)
   except (w.WavError, ValueError) as e:
      raise AudioError(f"{p.name}: {e}") from e


def import_wav(doc: AudioDocument, path: str | Path, name: str, options: WavOptions,
               replace: bool = False) -> dict[str, Any]:
   """!Imports a WAV as a sample: its data file waits in memory until save().
   @param doc      AudioDocument
   @param path     the WAV
   @param name     NAME or sample:NAME
   @param options  WavOptions
   @param replace  True: an existing sample of that key gets the new data (voices keep naming it)
   @return the manifest entry
   @throws AudioError when the file cannot be converted or the key is taken
   """
   key = full_key(name, "sample")
   old = None
   if replace and key in known_keys(doc)["sample"]:
      old = entry(doc, key)
   else:
      check_new_key(doc, key, "sample")
   sample = convert_wav(path, options)
   stem = key.split(":", 1)[1].replace("/", "_")
   rel = old["data"] if old is not None and isinstance(old.get("data"), str) else \
      doc.unique_file(SAMPLE_FOLDER, stem, SAMPLE_SUFFIX)
   item = sample.entry(key, rel)

   def change(data: dict[str, Any]) -> None:
      """!Adds or replaces the entry and keeps its bytes.
      @param data  the manifest
      @return None
      """
      doc.add_file(rel, sample.data)
      samples = data.setdefault("samples", [])
      if old is not None:
         samples[samples.index(old)] = item
      else:
         samples.append(item)
   checked_edit(doc, f"Import {Path(path).name} as {key}", change)
   return item


def sample_bytes(doc: AudioDocument, key: str) -> bytes:
   """!A sample's data bytes (pending or on disk).
   @param doc  AudioDocument
   @param key  the sample
   @return bytes
   @throws AudioError when it has no readable data
   """
   e = entry(doc, key)
   if not isinstance(e.get("data"), str):
      raise AudioError(f"{key}: no 'data' file")
   return doc.file_bytes(e["data"])


def sample_levels(doc: AudioDocument, key: str, limit: int | None = None) -> list[int]:
   """!A sample's levels as playback reads them (-128..127; DPCM decoded with dpcm.decode()).
   @param doc    AudioDocument
   @param key    the sample
   @param limit  at most this many (None: its length)
   @return levels
   @throws AudioError when the data is short or unreadable
   """
   e = entry(doc, key)
   data = sample_bytes(doc, key)
   count = int(e.get("length", 0)) if limit is None else min(int(e.get("length", 0)), limit)
   if e.get("format") == "dpcm4":
      try:
         return dpcm().decode(data, count)
      except ValueError as ex:
         raise AudioError(f"{key}: {ex}") from ex
   if len(data) < count:
      raise AudioError(f"{key}: {len(data)} bytes for {count} samples")
   sign = BYTE_MAX + 1
   return [b - sign if b > SIGNED_MAX else b for b in data[:count]]


def set_sample_field(doc: AudioDocument, key: str, name: str, value: Any) -> None:
   """!Changes a sample header field (pitch, loop, loop_start, length), checked with format.py.
   @param doc    AudioDocument
   @param key    the sample
   @param name   the field
   @param value  its value
   @return None
   @throws AudioError when the result has problems
   """
   if name not in ("pitch", "loop", "loop_start", "length", "format"):
      raise AudioError(f"{name}: a sample's fields are pitch, loop, loop_start, length, format")
   e = entry(doc, key)
   checked_edit(doc, f"{name} of {key}", lambda data: e.__setitem__(name, value))


def pitch_of(rate: int, key: int = BASE_KEY, tune_cents: float = 0.0) -> int:
   """!A sample's pitch value (rate Hz x 1024 at key 60): wav_sample.convert()'s own formula (C14b, R10 L7: run on a
   one-sample stand-in recording, so the studio never restates it; the key is clamped and the value masked as there).
   @param rate        the recording's rate in Hz
   @param key         the key it was recorded at
   @param tune_cents  tuning
   @return the pitch value
   """
   w = wav()
   one = w.WavInfo(rate=rate, kind=PITCH_PROBE_KIND, values=[0.0], loop_end=1)
   return int(w.convert(one, key=key, tune=float(tune_cents), rate=rate).pitch)


# -- songs and MIDI ---------------------------------------------------------------------------------------------------

def song_code(doc: AudioDocument, key: str) -> tuple[bytes, list[int]]:
   """!A song's command bytes and track offsets, as format.py loads them (data + tracks, the text form, or the
   MIDI source through midi_song).
   @param doc  AudioDocument
   @param key  "song:NAME"
   @return (data, track offsets)
   @throws AudioError when the song cannot be loaded
   """
   entry(doc, key)   # AudioError when there is none
   data, base = doc.view()
   live = next(s for s in data.get("songs", []) if isinstance(s, dict) and s.get("key") == key)
   mini = {"schema": SCHEMA, "songs": [live]}
   errors, aset = fmt().check(mini, base)
   song = aset.songs.get(key)
   if song is None:
      raise AudioError("; ".join(p for p in errors if key in p) or f"{key}: cannot be loaded")
   return bytes(song.data), list(song.tracks)


def midi_options(text: str = "", fields: dict[str, Any] | None = None) -> Any:
   """!MIDI conversion options: one config line's text ("-E -R50 -G_set -V080") and the manifest's author
   fields over it (volume, instruments, priority, reverb, clocks_per_beat, exact_gate, compress).
   @param text    the options text
   @param fields  author fields, or None
   @return midi_song.Options
   @throws AudioError for an unknown option
   """
   m = midi()
   try:
      return m.options_from_entry(dict(fields or {}, options=text))
   except m.MidiError as e:
      raise AudioError(str(e)) from e


def options_text(opts: Any) -> str:
   """!Options as a config line (the inverse of midi_options() for the fields a line can say).
   @param opts  midi_song.Options
   @return text
   """
   words = [f"-V{opts.volume:03d}", f"-G{opts.instruments.split(':', 1)[1]}", f"-P{opts.priority}"]
   if opts.reverb is not None:
      words.append(f"-R{opts.reverb}")
   if opts.factor != 1:
      words.append("-X")
   if opts.exact_gate:
      words.append("-E")
   if not opts.compress:
      words.append("-N")
   return " ".join(words)


def convert_midi(data: bytes, opts: Any, name: str = "song") -> Any:
   """!Converts a MIDI file (midi_song.convert()).
   @param data  the file's bytes
   @param opts  midi_song.Options
   @param name  the song's name when the options give none
   @return midi_song.Song
   @throws AudioError when it cannot be converted
   """
   m = midi()
   try:
      return m.convert(data, opts, name)
   except (m.MidiError, ValueError, IndexError) as e:
      raise AudioError(f"MIDI: {e}") from e


@dataclass
class TrackEnd:
   """!One track of a converted song, for the import report."""

   ## Track number.
   track: int
   ## (MIDI track, channel) it came from, or None.
   source: tuple[int, int] | None
   ## Commands it runs (alone, up to its end or loop).
   steps: int
   ## Notes it plays.
   notes: int
   ## The tick END runs at, or None when it loops.
   end_tick: int | None
   ## The tick it jumps back at, or None.
   loop_tick: int | None
   ## Notes before its first PROGRAM (they play the track's reset voice: a square with envelope 0/0/0/0).
   before_program: int = 0


@dataclass
class MidiReport:
   """!What a MIDI import gives: the tracks' end ticks and the frames to the song's end."""

   ## Per track.
   tracks: list[TrackEnd]
   ## Frames from the start until the last END runs (None: a track loops).
   frames_to_end: int | None
   ## Bytes of command data.
   size: int

   def lines(self) -> list[str]:
      """!The report as text lines.
      @return lines
      """
      r = self   # a local alias (Doxygen reads some uses of self.x as new members)
      out = [f"{len(r.tracks)} tracks, {r.size} bytes, " +
             (f"ends after {r.frames_to_end} frames" if r.frames_to_end is not None else "loops (no end)")]
      for t in r.tracks:
         src = f"MIDI track {t.source[0]} channel {t.source[1]}" if t.source else "-"
         end = f"end tick {t.end_tick}" if t.end_tick is not None else f"loops at tick {t.loop_tick}"
         out.append(f"track {t.track}: {src}: {t.notes} notes, {t.steps} commands, {end}")
         if t.before_program:
            out.append(f"   {t.before_program} notes come before the track's first PROGRAM (a program change): "
                       "they play the track's reset voice, a square with envelope 0/0/0/0 (near silent)")
      return out


def midi_report(song: Any) -> MidiReport:
   """!The end ticks of a converted song's tracks (midi_song.run_song() / frames_to_end()).
   @param song  midi_song.Song
   @return MidiReport
   """
   m = midi()
   runs = m.run_song(song)
   tracks = []
   for n, r in enumerate(runs):
      notes = sum(1 for s in r.steps if m.NOTE <= s.command < m.WAIT)
      first = next((k for k, s in enumerate(r.steps) if s.command == m.PROGRAM), len(r.steps))
      early = sum(1 for s in r.steps[:first] if m.NOTE <= s.command < m.WAIT)
      source = tuple(song.sources[n]) if n < len(song.sources) else None
      tracks.append(TrackEnd(n, source, len(r.steps), notes, r.end_tick, r.loop_tick, early))
   return MidiReport(tracks, m.frames_to_end(runs), len(song.data))


def add_midi_song(doc: AudioDocument, path: str | Path, name: str, options: str = "",
                  fields: dict[str, Any] | None = None, form: str = "midi", player: str | None = None,
                  sound_name: str | None = None, replace: bool = False) -> tuple[dict[str, Any], int | None]:
   """!Adds a song from a MIDI file: in the author form (the MIDI file copied beside the manifest with its options;
   the build converts it) or the compiled form (the converted command bytes); optionally a song table entry.
   @param doc         AudioDocument
   @param path        the MIDI file
   @param name        NAME or song:NAME
   @param options     a config line's options ("-E -R50 -V080")
   @param fields      author fields over the options (instruments, priority, reverb, volume, ...), or None
   @param form        "midi" or "compiled"
   @param player      a player name: also add a song table entry playing it there, or None
   @param sound_name  the entry's optional name key ("sound:NAME"), or None
   @param replace     True: an existing song of that key is replaced
   @return (the song entry, its sound number or None)
   @throws AudioError when it cannot be converted, the key is taken or the result has problems
   """
   if form not in SONG_FORMS:
      raise AudioError(f"form must be one of {', '.join(SONG_FORMS)}")
   key = full_key(name, "song")
   old = None
   if replace and key in known_keys(doc)["song"]:
      old = entry(doc, key)
   else:
      check_new_key(doc, key, "song")
   try:
      source = Path(path).read_bytes()
   except OSError as e:
      raise AudioError(f"{path}: {e}") from e
   opts = midi_options(options, fields)
   song = convert_midi(source, opts, key.split(":", 1)[1])
   stem = key.split(":", 1)[1].replace("/", "_")
   if form == "midi":
      rel = old.get("midi") if old is not None and isinstance(old.get("midi"), str) else \
         doc.unique_file(SONG_FOLDER, stem, MIDI_SUFFIX)
      item: dict[str, Any] = {"key": key, "instruments": opts.instruments, "priority": opts.priority,
                              "reverb": opts.reverb, "midi": rel, "options": options_text(opts)}
      blob = source
   else:
      rel = old.get("data") if old is not None and isinstance(old.get("data"), str) else \
         doc.unique_file(SONG_FOLDER, stem, SONG_SUFFIX)
      item = song.entry(rel, key)
      blob = bytes(song.data)
   if player is not None and player not in [p.get("name") for p in doc.data.get("players", [])]:
      raise AudioError(f"no player {player!r}")
   number = len(doc.data.get("song_table", [])) if player is not None else None

   def change(data: dict[str, Any]) -> None:
      """!Adds or replaces the song (and the table entry), keeping its file.
      @param data  the manifest
      @return None
      """
      doc.add_file(rel, blob)
      songs = data.setdefault("songs", [])
      if old is not None:
         songs[songs.index(old)] = item
      else:
         songs.append(item)
      if player is not None:
         row = {"song": key, "player": player}
         if sound_name:
            row["name"] = full_key(sound_name, "sound")
         data.setdefault("song_table", []).append(row)
   checked_edit(doc, f"Import {Path(path).name} as {key}", change)
   return item, number


def set_song_field(doc: AudioDocument, key: str, name: str, value: Any) -> None:
   """!Changes a song's header field (instruments, priority, reverb; options for a MIDI song), checked.
   @param doc    AudioDocument
   @param key    the song
   @param name   the field
   @param value  its value (None removes options / sets reverb to "leave as it is")
   @return None
   @throws AudioError when the result has problems
   """
   if name not in ("instruments", "priority", "reverb", "options"):
      raise AudioError(f"{name}: a song's header fields are instruments, priority, reverb (options: MIDI songs)")
   e = entry(doc, key)

   def change(data: dict[str, Any]) -> None:
      """!Writes the field.
      @param data  the manifest
      @return None
      """
      if value is None and name == "options":
         e.pop(name, None)
      else:
         e[name] = value
   checked_edit(doc, f"{name} of {key}", change)


# -- the song table and the players ------------------------------------------------------------------------------------

@dataclass
class SoundRow:
   """!One sound number of the song table."""

   ## The sound number.
   number: int
   ## The song's key, or None (an empty slot plays the empty song).
   song: str | None
   ## The player's name.
   player: str
   ## Its index in the player table, or -1 when unknown.
   player_index: int
   ## The optional name key ("sound:NAME"), or None.
   name: str | None
   ## The song's priority (0 for an empty slot).
   priority: int
   ## The player's start check (a lower-priority song is refused while one plays).
   start_check: bool


def players(doc: AudioDocument) -> list[dict[str, Any]]:
   """!The players, in table order (the order they run in; the 2 clip players come last).
   @param doc  AudioDocument
   @return player entries (live)
   """
   return [p for p in doc.data.get("players", []) if isinstance(p, dict)]


def sounds(doc: AudioDocument) -> list[SoundRow]:
   """!The song table.
   @param doc  AudioDocument
   @return one SoundRow per sound number
   """
   names = [p.get("name") for p in players(doc)]
   checks = [bool(p.get("start_check", False)) for p in players(doc)]
   prio = {s.get("key"): int(s.get("priority", 0)) for s in doc.data.get("songs", []) if isinstance(s, dict)}
   out = []
   for i, e in enumerate(doc.data.get("song_table", [])):
      e = e if isinstance(e, dict) else {}
      p = e.get("player")
      pi = names.index(p) if p in names else -1
      out.append(SoundRow(i, e.get("song"), str(p), pi, e.get("name"), prio.get(e.get("song"), 0),
                          checks[pi] if pi >= 0 else False))
   return out


def find_sound(doc: AudioDocument, text: str) -> int:
   """!A sound number from a number, a name key ("sound:NAME") or a song key (the first entry that plays it),
   as audio::find_sound() matches.
   @param doc   AudioDocument
   @param text  "12", "sound:SELECT" or "song:town"
   @return the number
   @throws AudioError when nothing matches
   """
   rows = sounds(doc)
   if text.isdigit():
      n = int(text)
      if n >= len(rows):
         raise AudioError(f"sound {n}: the table has {len(rows)} entries")
      return n
   for r in rows:
      if r.name == text:
         return r.number
   for r in rows:
      if r.song == text:
         return r.number
   raise AudioError(f"no sound {text!r} in the song table")


def set_sound(doc: AudioDocument, number: int, song: str | None = "", player: str | None = None,
              name: str | None = "") -> None:
   """!Changes a song table entry (arguments left at their defaults stay as they are).
   @param doc     AudioDocument
   @param number  the sound number
   @param song    the song's key, None for an empty slot ("": unchanged)
   @param player  the player's name (None: unchanged)
   @param name    the name key, None to remove it ("": unchanged)
   @return None
   @throws AudioError when the result has problems
   """
   table = doc.data.get("song_table", [])
   if not 0 <= number < len(table):
      raise AudioError(f"sound {number}: the table has {len(table)} entries")

   def change(data: dict[str, Any]) -> None:
      """!Writes the entry.
      @param data  the manifest
      @return None
      """
      e = data["song_table"][number]
      if song != "":
         e["song"] = song
      if player is not None:
         e["player"] = player
      if name is None:
         e.pop("name", None)
      elif name != "":
         e["name"] = full_key(name, "sound")
   checked_edit(doc, f"Sound {number}", change)


def add_sound(doc: AudioDocument, song: str | None, player: str, name: str | None = None) -> int:
   """!Appends a song table entry.
   @param doc     AudioDocument
   @param song    the song's key, or None
   @param player  the player's name
   @param name    an optional name key, or None
   @return its sound number
   @throws AudioError when the result has problems
   """
   row: dict[str, Any] = {"song": song, "player": player}
   if name:
      row["name"] = full_key(name, "sound")
   number = len(doc.data.get("song_table", []))
   checked_edit(doc, f"Add sound {number}", lambda data: data.setdefault("song_table", []).append(row))
   return number


def remove_sound(doc: AudioDocument, number: int) -> None:
   """!Removes the last song table entry (the numbers before it stay as they are; a game names sounds by number).
   @param doc     AudioDocument
   @param number  must be the last number
   @return None
   @throws AudioError for another number
   """
   table = doc.data.get("song_table", [])
   if number != len(table) - 1:
      raise AudioError("only the last sound can be removed (the numbers of the others would change); "
                       "set an entry's song to none to empty it")
   checked_edit(doc, f"Remove sound {number}", lambda data: data["song_table"].pop())


def set_player(doc: AudioDocument, index: int, name: str | None = None, tracks: int | None = None,
               start_check: bool | None = None) -> None:
   """!Changes a player (a rename renames it in the song table too).
   @param doc          AudioDocument
   @param index        its index
   @param name         new name, or None
   @param tracks       its track count, or None
   @param start_check  its start check, or None
   @return None
   @throws AudioError when the result has problems
   """
   ps = players(doc)
   if not 0 <= index < len(ps):
      raise AudioError(f"player {index}: there are {len(ps)}")
   old = ps[index].get("name")
   if name is not None and name != old and name in [p.get("name") for p in ps]:
      raise AudioError(f"a player is called {name!r} already")

   def change(data: dict[str, Any]) -> None:
      """!Writes the player.
      @param data  the manifest
      @return None
      """
      p = data["players"][index]
      if name is not None and name != old:
         p["name"] = name
         for e in data.get("song_table", []):
            if isinstance(e, dict) and e.get("player") == old:
               e["player"] = name
      if tracks is not None:
         p["tracks"] = tracks
      if start_check is not None:
         p["start_check"] = start_check
   checked_edit(doc, f"Player {old}", change)


def add_player(doc: AudioDocument, name: str, tracks: int, start_check: bool) -> int:
   """!Appends a player.
   @param doc          AudioDocument
   @param name         its name
   @param tracks       its tracks (1-16)
   @param start_check  whether it refuses lower-priority songs
   @return its index
   @throws AudioError when the name is taken or the tracks are too many
   """
   if name in [p.get("name") for p in players(doc)]:
      raise AudioError(f"a player is called {name!r} already")
   index = len(players(doc))
   checked_edit(doc, f"Add player {name}", lambda data: data.setdefault("players", []).append(
      {"name": name, "tracks": tracks, "start_check": start_check}))
   return index


def track_total(doc: AudioDocument) -> int:
   """!Tracks of every player with the clip players' (at most MAX_ALL_TRACKS).
   @param doc  AudioDocument
   @return tracks
   """
   return sum(int(p.get("tracks", 0)) for p in players(doc)) + CLIP_TRACKS


def set_mixer(doc: AudioDocument, name: str, value: Any) -> None:
   """!Changes a mixer setting (rate, channels, master_volume, dac_bits, output), checked.
   @param doc    AudioDocument
   @param name   the setting
   @param value  its value
   @return None
   @throws AudioError when the result has problems
   """
   if name not in DEFAULT_MIXER:
      raise AudioError(f"{name}: the mixer's settings are {', '.join(DEFAULT_MIXER)}")
   checked_edit(doc, f"Mixer {name}", lambda data: data.setdefault("mixer", {}).__setitem__(name, value))


# -- envelope curves (the instrument editor's preview) ----------------------------------------------------------------

def sample_envelope(attack: int, decay: int, sustain: int, release: int, held: int,
                    tail: int = ENVELOPE_TAIL) -> list[int]:
   """!A sampled voice's envelope level per frame for a note held `held` frames (the core's arithmetic, without
   the pseudo-echo): attack adds `attack` a frame up to 255; decay multiplies by decay/256 down to the sustain
   level; the release multiplies by release/256 from the frame after the note ends until the level is 0.
   @param attack   0-255
   @param decay    0-255
   @param sustain  0-255
   @param release  0-255
   @param held     frames the note is held
   @param tail     frames shown after the release starts at most
   @return levels 0-255, one per frame
   """
   out = []
   env = min(attack, ENVELOPE_FULL)
   phase = "decay" if attack >= ENVELOPE_FULL else "attack"
   out.append(env)
   for f in range(1, held + tail):
      if f >= held:
         env = (env * release) >> ENVELOPE_SHIFT
         out.append(env)
         if env == 0:
            break
         continue
      if phase == "attack":
         env = min(env + attack, ENVELOPE_FULL)
         phase = "decay" if env >= ENVELOPE_FULL else phase
      elif phase == "decay":
         env = (env * decay) >> ENVELOPE_SHIFT
         if env <= sustain:
            env = sustain
            phase = "sustain"
      out.append(env)
      if env == 0:
         break
   return out


def tone_envelope(attack: int, decay: int, sustain: int, release: int, held: int,
                  tail: int = ENVELOPE_TAIL) -> list[int]:
   """!A tone voice's envelope level per frame for a note at full volume held `held` frames: one level step each
   time a counter of `attack` / `decay` / `release` frames runs out (0: at once), rising to the goal, falling to
   the sustain level (goal x sustain + 15 >> 4), then to 0 after the note. A preview of the shape: the core's tone
   envelope also follows its envelope clock and the channel's volume.
   @param attack   0-7
   @param decay    0-7
   @param sustain  0-15
   @param release  0-7
   @param held     frames the note is held
   @param tail     frames shown after the release starts at most
   @return levels 0-15, one per frame
   """
   goal = TONE_GOAL
   level = (goal * sustain + TONE_GOAL) >> TONE_SUSTAIN_SHIFT
   env = 0 if attack else goal
   phase = "attack" if attack else "decay"
   counter = attack
   if phase == "decay" and decay == 0:
      env, phase = level, "sustain"
   out = [env]
   for f in range(1, held + tail):
      if f >= held:
         if release == 0:
            env = 0
         else:
            counter = counter - 1 if phase == "release" else release - 1
            phase = "release"
            if counter <= 0:
               env, counter = max(env - 1, 0), release
         out.append(env)
         if env == 0:
            break
         continue
      if phase == "attack":
         counter -= 1
         if counter <= 0:
            env += 1
            counter = attack
            if env >= goal:
               env, phase, counter = goal, "decay", decay
               if decay == 0:
                  env, phase = level, "sustain"
      elif phase == "decay":
         counter -= 1
         if counter <= 0:
            env -= 1
            counter = decay
            if env <= level:
               env, phase = level, "sustain"
      out.append(env)
   return out


def envelope_of(voice: dict[str, Any], held: int) -> tuple[list[int], int]:
   """!A voice's envelope curve.
   @param voice  a sample or tone voice
   @param held   frames the note is held
   @return (levels per frame, the full level: 255 sampled, 15 tone)
   """
   args = [int(voice.get(n, 0)) for n in ("attack", "decay", "sustain", "release")]
   if voice.get("kind") in tone_kinds():
      return tone_envelope(*args, held), TONE_GOAL
   return sample_envelope(*args, held), ENVELOPE_FULL
