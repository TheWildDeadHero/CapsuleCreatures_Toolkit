"""![S7] Test content for the audio editor, made by code (engine M4 rule: generated simple waveforms and tiny
songs only): WAV files of a sine, a square or noise, small MIDI files, and a tiny game whose audio manifest
(capsule.audio/1) has two samples, a wave, a bank with a sampled voice, tone voices, a key split and a drum set,
songs in the text form and a song table on a music player and two sound effect players.
"""
from __future__ import annotations

import json
import math
import random
import struct
from pathlib import Path

## Sample rate of the generated WAVs.
RATE = 13379
## Samples of a generated WAV.
LENGTH = 1024
## Peak of a generated 16-bit wave.
PEAK = 20000
## The tiny game's folder layout: its project manifest and its audio manifest (relative to the game folder).
PROJECT = ("reference", "project.json")
AUDIO = "audio/audio.json"
## MIDI ticks per quarter note of the generated files.
DIVISION = 96
## Microseconds per quarter of the generated files' tempo (120 BPM).
TEMPO_US = 500000

## Songs of the tiny game, in the text form (format.py's assembler).
SONGS = {
   # Three tracks: a sampled melody, a square bass, a noise hit; ends.
   "tune": """TRACK
TEMPO 60
PROGRAM 0
VOLUME 100
NOTE 24 c4 v100
WAIT 24
NOTE 24 e4 v100
WAIT 24
NOTE 24 g4 v100
WAIT 24
NOTE 48 c5 v100
WAIT 48
END
TRACK
PROGRAM 1
VOLUME 90
NOTE 48 c2 v100
WAIT 48
NOTE 48 g2 v100
WAIT 48
NOTE 24 c2 v100
WAIT 24
END
TRACK
PROGRAM 3
VOLUME 80
NOTE 6 c4 v80
WAIT 48
NOTE 6 c4 v80
WAIT 48
END
""",
   # A loop on one sampled track.
   "loop": """TRACK
PROGRAM 0
VOLUME 100
@top:
NOTE 12 c4 v100
WAIT 12
NOTE 12 d4 v100
WAIT 12
JUMP @top
""",
   # A low-priority effect: four sampled notes at once (all five channels taken with a fifth on another player).
   "fx_low": """TRACK
PROGRAM 0
VOLUME 100
NOTE 72 c4 v120
WAIT 72
END
TRACK
PROGRAM 0
VOLUME 100
NOTE 72 e4 v120
WAIT 72
END
TRACK
PROGRAM 0
VOLUME 100
NOTE 72 g4 v120
WAIT 72
END
""",
   # A high-priority effect on another player: three sampled notes (steals from fx_low and tune) and a noise hit.
   "fx_high": """TRACK
PRIORITY 10
PROGRAM 0
VOLUME 110
NOTE 48 c5 v120
WAIT 48
END
TRACK
PRIORITY 10
PROGRAM 0
VOLUME 110
NOTE 48 e5 v120
WAIT 48
END
TRACK
PRIORITY 10
PROGRAM 4
VOLUME 110
NOTE 24 g5 v120
WAIT 48
END
""",
   # The key split and the drum set.
   "kit": """TRACK
PROGRAM 5
VOLUME 100
NOTE 12 c3 v100
WAIT 12
NOTE 12 c5 v100
WAIT 12
PROGRAM 6
NOTE 12 c2 v100
WAIT 12
NOTE 12 d2 v100
WAIT 12
END
""",
}


def wav_bytes(kind: str = "sine", rate: int = RATE, length: int = LENGTH, loop: tuple[int, int] | None = None,
              key: int | None = None, bits: int = 16) -> bytes:
   """!A mono WAV of a generated wave.
   @param kind    "sine", "square", "saw" or "noise"
   @param rate    sample rate
   @param length  samples
   @param loop    (start, last sample) for a smpl loop, or None
   @param key     the smpl unity key, or None
   @param bits    8 or 16
   @return the file's bytes
   """
   rng = random.Random(7)
   period = 64
   values = []
   for i in range(length):
      if kind == "sine":
         v = math.sin(2 * math.pi * i / period)
      elif kind == "square":
         v = 1.0 if (i // (period // 2)) % 2 == 0 else -1.0
      elif kind == "saw":
         v = (i % period) / (period / 2) - 1.0
      else:
         v = rng.uniform(-1.0, 1.0)
      values.append(v)
   if bits == 8:
      data = bytes(max(0, min(255, int(128 + v * 100))) for v in values)
   else:
      data = b"".join(struct.pack("<h", int(v * PEAK)) for v in values)
   width = bits // 8
   fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * width, width, bits)
   chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
   if len(data) % 2:
      chunks += b"\0"
   if loop is not None or key is not None:
      loops = [(0, 0, loop[0], loop[1], 0, 0)] if loop is not None else []
      body = struct.pack("<IIIIIIIII", 0, 0, 0, key if key is not None else 60, 0, 0, 0, len(loops), 0)
      for lp in loops:
         body += struct.pack("<IIIIII", *lp)
      chunks += b"smpl" + struct.pack("<I", len(body)) + body
   return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def vlq(n: int) -> bytes:
   """!A MIDI variable-length quantity.
   @param n  the value
   @return bytes
   """
   out = [n & 0x7F]
   n >>= 7
   while n:
      out.append(0x80 | (n & 0x7F))
      n >>= 7
   return bytes(reversed(out))


def midi_bytes(tracks: list[list[tuple[int, int, int, int]]] | None = None, tempo_us: int = TEMPO_US,
               loop: bool = False, programs: list[int] | None = None) -> bytes:
   """!A format 1 MIDI file: a tempo track, then one track per note list.
   @param tracks    per track: (start tick, length, key, velocity) notes, channel = track index
   @param tempo_us  microseconds per quarter
   @param loop      True: loop markers "[" at 0 and "]" at the end of the first track
   @param programs  per track a program change at tick 0, or None
   @return the file's bytes
   """
   if tracks is None:
      tracks = [[(0, 96, 60, 100), (96, 96, 64, 100), (192, 96, 67, 100), (288, 192, 72, 100)],
                [(0, 192, 48, 90), (192, 192, 43, 90)]]
   head = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks) + 1, DIVISION)
   meta = b"\x00\xff\x51\x03" + tempo_us.to_bytes(3, "big")
   if loop:
      meta += b"\x00\xff\x06\x01["
   end_tick = max((s + n for t in tracks for s, n, _k, _v in t), default=0)
   if loop:
      meta += vlq(end_tick) + b"\xff\x06\x01]" + b"\x00\xff\x2f\x00"
   else:
      meta += vlq(end_tick) + b"\xff\x2f\x00"
   out = head + b"MTrk" + struct.pack(">I", len(meta)) + meta
   for ch, notes in enumerate(tracks):
      events = []
      for start, length, key, vel in notes:
         events.append((start, 1, bytes([0x90 | ch, key, vel])))
         events.append((start + length, 0, bytes([0x80 | ch, key, 0])))
      events.sort(key=lambda e: (e[0], e[1]))
      body = b""
      if programs is not None:
         body += b"\x00" + bytes([0xC0 | ch, programs[ch]])
      now = 0
      for t, _order, ev in events:
         body += vlq(t - now) + ev
         now = t
      body += b"\x00\xff\x2f\x00"
      out += b"MTrk" + struct.pack(">I", len(body)) + body
   return out


def manifest(folder: Path) -> dict:
   """!Writes the tiny game's audio content into a folder and returns its manifest (not yet written).
   @param folder  the audio folder
   @return the manifest JSON
   """
   (folder / "samples").mkdir(parents=True, exist_ok=True)
   (folder / "songs").mkdir(exist_ok=True)
   sine = bytes(int(round(100 * math.sin(2 * math.pi * i / 32))) & 0xFF for i in range(128)) + b"\0"
   noise_rng = random.Random(3)
   noise = bytes(noise_rng.randrange(256) for _ in range(500)) + b"\0"
   (folder / "samples" / "sine.bin").write_bytes(sine)
   (folder / "samples" / "noise.bin").write_bytes(noise)
   for name, text in SONGS.items():
      (folder / "songs" / f"{name}.cseq").write_text(text, encoding="utf-8")
   voice = {"kind": "sample", "sample": "sample:sine", "key": 60, "attack": 255, "decay": 0, "sustain": 255,
            "release": 200}
   bank = [voice,
           {"kind": "square", "duty": 2, "length": 0, "key": 60, "attack": 0, "decay": 2, "sustain": 10,
            "release": 3},
           {"kind": "wave", "wave": "wave:tri", "length": 0, "key": 60, "attack": 1, "decay": 0, "sustain": 15,
            "release": 2},
           {"kind": "noise", "period": 0, "length": 0, "key": 60, "attack": 0, "decay": 1, "sustain": 0,
            "release": 0},
           {"kind": "sample", "sample": "sample:noise", "key": 72, "attack": 200, "decay": 220, "sustain": 120,
            "release": 150},
           {"kind": "split", "instruments": "instruments:main", "keymap": "keymap:halves"},
           {"kind": "drums", "instruments": "instruments:kit"}]
   bank += [{"kind": "none"}] * (36 - len(bank))
   bank += [{"kind": "noise", "period": 1, "length": 0, "key": 60, "attack": 0, "decay": 1, "sustain": 0,
             "release": 0, "pan_sweep": 200},
            {"kind": "none"},
            {"kind": "square_sweep", "duty": 1, "sweep": 0x23, "length": 0, "key": 72, "attack": 0, "decay": 1,
             "sustain": 0, "release": 0}]
   return {"schema": "capsule.audio/1",
           "mixer": {"rate": 13379, "channels": 5, "master_volume": 12, "dac_bits": 8, "output": "stereo"},
           "players": [{"name": "music", "tracks": 10, "start_check": False},
                       {"name": "sfx", "tracks": 3, "start_check": True},
                       {"name": "sfx2", "tracks": 3, "start_check": True}],
           "song_table": [{"song": "song:tune", "player": "music"}, {"song": "song:loop", "player": "music"},
                          {"song": "song:fx_low", "player": "sfx"}, {"song": "song:fx_high", "player": "sfx2"},
                          {"song": "song:kit", "player": "music"}, {"song": None, "player": "music"},
                          {"song": "song:fx_high", "player": "sfx", "name": "sound:HIGH"}],
           "samples": [{"key": "sample:sine", "format": "pcm8", "pitch": 13379 * 1024, "loop": True,
                        "loop_start": 0, "length": 128, "data": "samples/sine.bin"},
                       {"key": "sample:noise", "format": "pcm8", "pitch": 10512 * 1024, "loop": False,
                        "loop_start": 0, "length": 500, "data": "samples/noise.bin"}],
           "waves": [{"key": "wave:tri", "data": "0123456789ABCDEFFEDCBA9876543210"}],
           "keymaps": [{"key": "keymap:halves", "entries": [0] * 60 + [4] * 68}],
           "voice_banks": [{"key": "bank:main", "voices": bank}],
           "instrument_sets": [{"key": "instruments:main", "bank": "bank:main", "offset": 0},
                               {"key": "instruments:kit", "bank": "bank:main", "offset": 0}],
           "songs": [{"key": f"song:{n}", "instruments": "instruments:main", "priority": 10 if n == "fx_high" else 0,
                      "reverb": None, "asm": f"songs/{n}.cseq"} for n in SONGS],
           "clips": [{"key": "clip:beep", "voice": voice}, {"key": "clip:beep_reverse", "reverse_of": "clip:beep"}]}


def make_game(root: Path, name: str = "tiny") -> Path:
   """!A tiny game folder: reference/project.json naming audio/audio.json, and that manifest's content.
   @param root  where the game folder goes
   @param name  its name
   @return the audio manifest's path
   """
   game = root / name
   (game / "reference").mkdir(parents=True, exist_ok=True)
   (game.joinpath(*PROJECT)).write_text(json.dumps({"schema": "capsule.project/1", "name": name,
                                                     "rom": {"title": "TINY", "code": "CTIN", "maker": "00"},
                                                     "sources": [], "audio": AUDIO}, indent=1), encoding="utf-8")
   path = game / AUDIO
   data = manifest(path.parent)
   path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
   return path
