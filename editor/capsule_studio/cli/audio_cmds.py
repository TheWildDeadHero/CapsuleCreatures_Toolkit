"""!`capsule-studio audio MANIFEST ...`: a game's audio manifest (capsule.audio/1, the audio / ) from the
command line, every action of the audio editor's panels: songs (their tracks, notes, commands and tempo; rendered
through the engine's audio_render with tracks muted or solo, the player state over time), instrument sets, voices,
envelopes, keymaps (key splits), drum sets and bank windows, waves, samples (WAV import, the levels), MIDI import
(the end-tick report), the song table and players, sounds played on their players, and the priority and channel
stealing of two sounds at once. Every change is checked with the engine's tools/audio/format.py before the
manifest is saved."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from ..core import audio, audio_render as ar, audio_song, bench
from .main import CommandError

## Separator of FIELD=VALUE.
ASSIGN = "="
## The word for "none" (an empty song table slot, a song's reverb left as it is, a removed name).
NONE_WORD = "none"
## The word that removes an optional field.
REMOVE = "-"
## Notes `song --notes` prints per track at most (0: all).
DEFAULT_NOTE_LIMIT = 40
## Levels `sample` prints by default.
DEFAULT_LEVELS = 16
## Frames `envelope` holds the note by default.
DEFAULT_HELD = 30
## Frames `state` prints at most by default.
DEFAULT_STATE_FRAMES = 20
## Build targets by their command-line name.
BUILD_TARGETS = {"preview": ar.PREVIEW_TARGET, "hq": ar.PREVIEW_HQ_TARGET, "table": ar.TABLE_TARGET}
## Answers of yes/no options.
YES_NO = {"yes": True, "no": False, "true": True, "false": False, "on": True, "off": False}
## Height of a waveform picture, pixels, and its colours (background, line, centre).
WAVE_PNG_HEIGHT = 128
## Colours of a waveform picture: background, wave, centre line, loop start (RGBA).
WAVE_COLOURS = ((24, 24, 32, 255), (120, 200, 255, 255), (80, 80, 96, 255), (255, 180, 60, 255))
## Width of a waveform picture, pixels (by default).
WAVE_PNG_WIDTH = 512
## Bytes of an RGBA pixel.
RGBA_BYTES = 4
## Characters of a channel's cell in `state`.
CELL_WIDTH = 8
## Halves (a picture's centre line).
HALF = 2


def register(sub: argparse._SubParsersAction) -> None:
   """!Adds the `audio` command group.
   @param sub  argparse subparsers
   @return None
   """
   p = sub.add_parser("audio", help="a game's audio: songs, instruments, samples, MIDI import, sounds")
   p.add_argument("manifest", help="audio manifest (capsule.audio/1, audio.json)")
   s = p.add_subparsers(dest="audio_command", metavar="ACTION")
   s.required = True

   def add(name: str, help_text: str, run: Any) -> argparse.ArgumentParser:
      """!One action.
      @param name       its name
      @param help_text  its help
      @param run        its function
      @return the parser
      """
      q = s.add_parser(name, help=help_text)
      q.set_defaults(run=run)
      return q

   add("new", "a new manifest with the default mixer and players (the file must not exist)", cmd_new)
   add("check", "the manifest's problems as the engine's format.py finds them (exit 1 when there are any)",
       cmd_check)
   add("info", "mixer, players and what the manifest holds", cmd_info)
   q = add("mixer-set", "a mixer setting: FIELD VALUE (rate, channels, master_volume, dac_bits, output)",
           cmd_mixer_set)
   q.add_argument("field")
   q.add_argument("value")
   # songs
   add("songs", "the songs: key, form, tracks, priority, reverb, instrument set, sound numbers", cmd_songs)
   q = add("song", "one song: its tracks (notes, programs, end or loop), tempo and frames to its end", cmd_song)
   q.add_argument("key")
   q.add_argument("--commands", action="store_true", help="the text form (.cseq disassembly)")
   q.add_argument("--track", type=int, help="this track's commands with their ticks")
   q.add_argument("--notes", action="store_true", help="each track's notes (tick, length, key, velocity)")
   q.add_argument("--limit", type=int, default=DEFAULT_NOTE_LIMIT, help="notes per track at most (0: all)")
   q.add_argument("--tempo", action="store_true", help="the tempo map (TEMPO commands with their frames)")
   q = add("song-set", "a song's header field: FIELD VALUE (instruments, priority, reverb (none: leave it), "
                       "options (MIDI songs; - removes))", cmd_song_set)
   q.add_argument("key")
   q.add_argument("field")
   q.add_argument("value")
   q = add("export-song", "a song's text form to a .cseq file (or its compiled bytes to a .seq file)",
           cmd_export_song)
   q.add_argument("key")
   q.add_argument("out")
   # rendering
   q = add("render", "render a song, a sound number or a clip through the engine's audio_render", cmd_render)
   what = q.add_mutually_exclusive_group(required=True)
   what.add_argument("--song", help="a song key (the editor's current data, on --player or its table player)")
   what.add_argument("--sound", help="a sound number, name key or song key, on its player")
   what.add_argument("--clip", type=int, help="a clip number (the saved table)")
   q.add_argument("--player", help="--song: the player's name")
   q.add_argument("--mute", default="", help="--song: tracks to silence, e.g. 0,2-3")
   q.add_argument("--solo", default="", help="--song: tracks to keep (the others are silenced)")
   q.add_argument("--saved", action="store_true", help="--sound: the whole saved table (TABLE target)")
   _render_options(q)
   _clip_options(q)
   q.add_argument("--out", help="copy the render's files (out.wav, state.jsonl, tones.txt, segments.bin, "
                                "summary.json) to this folder")
   q.add_argument("--state", action="store_true", help="also print which track holds each channel over time")
   q = add("play", "a sound number on its player (render --sound N --saved)", cmd_play)
   q.add_argument("sound")
   _render_options(q)
   q.add_argument("--out", help="copy the render's files to this folder")
   q = add("state", "a render folder's player state over time (state.jsonl)", cmd_state)
   q.add_argument("folder")
   q.add_argument("--frame", type=int, help="this frame's players, tracks and channels")
   q.add_argument("--frames", type=int, default=DEFAULT_STATE_FRAMES, help="frames of the channel overview")
   q.add_argument("--every", type=int, default=1, help="every Nth frame in the overview")
   q = add("build", "build the audio_render program (the first build compiles the engine's audio core)",
           cmd_build)
   q.add_argument("--target", choices=sorted(BUILD_TARGETS), default="preview")
   add("table", "the saved table as the engine compiled it (audio_render --list)", cmd_table)
   q = add("priority", "two sounds started a few frames apart: who gets each channel (the C++ core through "
           "audio_render --then; the reference model without a toolchain or with --model)", cmd_priority)
   q.add_argument("first")
   q.add_argument("second")
   q.add_argument("--delay", type=int, default=1, help="frames between the starts")
   q.add_argument("--frames", type=int, default=ar.DEFAULT_PRIORITY_FRAMES)
   q.add_argument("--every", type=int, default=0, help="print the channel owners every N frames (0: no)")
   q.add_argument("--wav", help="write the mix to this WAV (the core's output; the model: the sampled channels)")
   q.add_argument("--model", action="store_true", help="run the engine's reference model, not the C++ core")
   # instruments
   add("sets", "the instrument sets: their bank and window, or their own voices", cmd_sets)
   q = add("set", "a set's window: the voice each program (0-127) reads", cmd_set)
   q.add_argument("key")
   q.add_argument("--count", type=int, default=audio.SET_VOICES)
   q.add_argument("--all", action="store_true", help="also the entries past the bank's end (padding)")
   q = add("set-add", "a new instrument set: a window of --bank at --offset, or its own voices", cmd_set_add)
   q.add_argument("name")
   q.add_argument("--bank")
   q.add_argument("--offset", type=int, default=0)
   q = add("set-offset", "move a set's window in its bank", cmd_set_offset)
   q.add_argument("key")
   q.add_argument("offset", type=int)
   add("banks", "the voice banks with the windows sets read from them and their overlaps", cmd_banks)
   add("bank-add", "a new, empty voice bank", cmd_bank_add).add_argument("name")
   q = add("voice", "one voice of a set's window (JSON), the sets sharing it", cmd_voice)
   q.add_argument("set")
   q.add_argument("index", type=int)
   q = add("voice-set", "a voice's fields FIELD=VALUE (JSON values; kind=KIND starts a new voice of that kind; "
                        "- removes a field)", cmd_voice_set)
   q.add_argument("set")
   q.add_argument("index", type=int)
   q.add_argument("fields", nargs="+")
   q = add("voice-add", "append a voice to a bank or a set with its own voices: KIND [FIELD=VALUE ...]",
           cmd_voice_add)
   q.add_argument("container")
   q.add_argument("kind", help="a voice kind: " + ", ".join(audio.voice_kinds()))
   q.add_argument("fields", nargs="*")
   q = add("envelope", "a voice's envelope curve (level per frame)", cmd_envelope)
   q.add_argument("set")
   q.add_argument("index", type=int)
   q.add_argument("--held", type=int, default=DEFAULT_HELD, help="frames the note is held")
   add("keymaps", "the keymaps as key splits", cmd_keymaps)
   q = add("keymap-add", "a new keymap (every key on one entry)", cmd_keymap_add)
   q.add_argument("name")
   q.add_argument("--value", type=int, default=0)
   q = add("keymap-set", "a key split: FIRST LAST ENTRY (keys as numbers or names, c4 = 60)", cmd_keymap_set)
   q.add_argument("key")
   q.add_argument("first")
   q.add_argument("last")
   q.add_argument("value", type=int)
   q = add("split", "what a split voice plays per key split", cmd_split)
   q.add_argument("set")
   q.add_argument("index", type=int)
   q = add("drums", "a drum set: the voice each key plays", cmd_drums)
   q.add_argument("set")
   add("waves", "the waves (32 levels each)", cmd_waves)
   q = add("wave-add", "a new wave from 32 hex digits", cmd_wave_add)
   q.add_argument("name")
   q.add_argument("levels")
   # samples
   add("samples", "the samples: format, rate, loop, length", cmd_samples)
   q = add("sample", "one sample's header and levels (DPCM decoded)", cmd_sample)
   q.add_argument("key")
   q.add_argument("--levels", type=int, default=DEFAULT_LEVELS, help="levels to print")
   q.add_argument("--png", help="draw its waveform into this PNG")
   q.add_argument("--width", type=int, default=WAVE_PNG_WIDTH)
   q = add("sample-import", "a WAV as a sample (the engine's wav_sample.py)", cmd_sample_import)
   q.add_argument("wav")
   q.add_argument("name")
   q.add_argument("--dpcm", action="store_true", help="DPCM4 compression")
   q.add_argument("--lookahead", type=int, default=1, help="DPCM search depth 1-8")
   q.add_argument("--no-pad", dest="pad", action="store_false", help="DPCM: stop after the last sample")
   q.add_argument("--loop-start", type=int, help="loop from this sample (turns the loop on)")
   q.add_argument("--length", type=int, help="samples played (the loop end)")
   q.add_argument("--key", help="the key it was recorded at (number or name, default the file's or c4 = 60)")
   q.add_argument("--tune", type=float, help="tuning in cents")
   q.add_argument("--replace", action="store_true", help="replace the sample of that key")
   q = add("sample-set", "a sample's field: FIELD VALUE (pitch, loop, loop_start, length)", cmd_sample_set)
   q.add_argument("key")
   q.add_argument("field")
   q.add_argument("value")
   # MIDI
   q = add("midi-import", "a MIDI file as a song (the engine's midi_song.py), with its end-tick report", cmd_midi)
   q.add_argument("midi")
   q.add_argument("name")
   q.add_argument("--options", default="", help="a conversion config line, given as --options=\"-E -R50 -G_main "
                                                 "-V080\" (with the = sign, as it starts with -)")
   q.add_argument("--instruments", help="the instrument set (over -G)")
   q.add_argument("--priority", type=int)
   q.add_argument("--reverb", help="0-127 or none")
   q.add_argument("--volume", type=int)
   q.add_argument("--form", choices=audio.SONG_FORMS, default="midi",
                  help="midi: the MIDI file and its options (the build converts); compiled: the converted bytes")
   q.add_argument("--player", help="also add a song table entry on this player")
   q.add_argument("--sound-name", help="the entry's name key (sound:NAME)")
   q.add_argument("--replace", action="store_true")
   q.add_argument("--report-only", action="store_true", help="convert and report; change nothing")
   q.add_argument("--listing", action="store_true", help="also print each track's commands with their ticks")
   # the song table and players
   add("sounds", "the song table: number, song, player, name, priority, start check", cmd_sounds)
   q = add("sound-set", "a song table entry", cmd_sound_set)
   q.add_argument("number", type=int)
   q.add_argument("--song", help="a song key or none")
   q.add_argument("--player")
   q.add_argument("--name", help="sound:NAME, or - to remove it")
   q = add("sound-add", "append a song table entry: SONG|none PLAYER", cmd_sound_add)
   q.add_argument("song")
   q.add_argument("player")
   q.add_argument("--name")
   add("sound-remove", "remove the last song table entry", cmd_sound_remove).add_argument("number", type=int)
   add("players", "the players: tracks, start check, the sounds on each", cmd_players)
   q = add("player-set", "a player's name, tracks or start check", cmd_player_set)
   q.add_argument("index", type=int)
   q.add_argument("--name")
   q.add_argument("--tracks", type=int)
   q.add_argument("--start-check", choices=sorted(YES_NO))
   q = add("player-add", "a new player", cmd_player_add)
   q.add_argument("name")
   q.add_argument("tracks", type=int)
   q.add_argument("--start-check", action="store_true")
   q = add("remove", "remove an entry (sample:, wave:, keymap:, bank:, instruments:, song:, clip:) nothing names",
           cmd_remove)
   q.add_argument("key")


def _render_options(q: argparse.ArgumentParser) -> None:
   """!audio_render's length and output options.
   @param q  the action's parser
   @return None
   """
   q.add_argument("--seconds", type=int, default=ar.DEFAULT_SECONDS, help="render at most this long")
   q.add_argument("--tail", type=int, default=ar.DEFAULT_TAIL, help="frames after the end")
   q.add_argument("--mono", action="store_true")
   q.add_argument("--hq", action="store_true", help="the high-quality desktop mix (previews only)")
   q.add_argument("--no-state", dest="state_file", action="store_false", help="no state.jsonl")


def _clip_options(q: argparse.ArgumentParser) -> None:
   """!play_clip()'s parameters.
   @param q  the action's parser
   @return None
   """
   d = ar.ClipOptions()
   for name in ("volume", "pan", "pitch", "hold", "release", "chorus", "priority", "offset"):
      q.add_argument(f"--clip-{name}", dest=f"clip_{name}", type=int, default=getattr(d, name))


# -- helpers -----------------------------------------------------------------------------------------------------------

def _open(args: argparse.Namespace) -> audio.AudioDocument:
   """!Opens the manifest.
   @param args  parsed arguments
   @return AudioDocument
   @throws CommandError when it does not exist
   """
   p = Path(args.manifest)
   if not p.is_file():
      raise CommandError(f"{p} does not exist (capsule-studio audio {p} new makes one)")
   return audio.open_audio(p)


def _save(doc: audio.AudioDocument) -> None:
   """!Saves the manifest (and the data files imported into it) after a checked edit.
   @param doc  AudioDocument
   @return None
   """
   doc.save()
   print(f"saved {doc.path.name}")


def _value(text: str) -> Any:
   """!A command-line value: JSON when it parses (numbers, true/false, null, lists), else the text.
   @param text  the value
   @return the value
   """
   try:
      return json.loads(text)
   except ValueError:
      return text


def _fields(items: list[str]) -> dict[str, Any]:
   """!FIELD=VALUE words.
   @param items  the words
   @return field -> value (REMOVE: None)
   @throws CommandError for a word without "="
   """
   out: dict[str, Any] = {}
   for item in items:
      if ASSIGN not in item:
         raise CommandError(f"{item!r}: fields look like FIELD=VALUE")
      name, text = item.split(ASSIGN, 1)
      out[name] = None if text == REMOVE else _value(text)
   return out


def _tracks(text: str) -> set[int]:
   """!Track numbers like "0,2-3".
   @param text  the list
   @return numbers
   """
   out: set[int] = set()
   for part in text.split(","):
      part = part.strip()
      if "-" in part:
         a, b = part.split("-", 1)
         out.update(range(int(a), int(b) + 1))
      elif part:
         out.add(int(part))
   return out


def _key(text: str) -> int:
   """!A key as a number or a name (c4 = 60).
   @param text  the token
   @return 0-127
   """
   f = audio.fmt()
   try:
      return f.parse_key(text, "key")
   except f.FormatError as e:
      raise CommandError(str(e)) from e


def _options(args: argparse.Namespace) -> ar.RenderOptions:
   """!RenderOptions from the arguments.
   @param args  parsed arguments
   @return RenderOptions
   """
   return ar.RenderOptions(args.seconds, args.tail, args.mono, args.hq, args.state_file)


def _progress(phase: str, text: str) -> None:
   """!Build progress on the terminal (the compiler's lines are left out).
   @param phase  bench phase
   @param text   message
   @return None
   """
   if phase != bench.PHASE_LOG:
      print(f"[{phase}] {text}")


def _renderer(doc: audio.AudioDocument) -> ar.Renderer:
   """!The manifest's renderer.
   @param doc  AudioDocument
   @return Renderer
   """
   return ar.Renderer(doc)


def _copy_out(result: ar.RenderResult, out: str | None) -> None:
   """!Copies a render's files to a folder.
   @param result  RenderResult
   @param out     the folder, or None
   @return None
   """
   if not out:
      return
   folder = Path(out)
   folder.mkdir(parents=True, exist_ok=True)
   for f in result.folder.iterdir():
      if f.is_file():
         shutil.copy2(f, folder / f.name)
   print(f"files in {folder}")


def _run_render(fn: Any) -> ar.RenderResult:
   """!Runs a render, turning the toolchain's and the build's errors into CommandError.
   @param fn  callable() -> RenderResult
   @return the result
   """
   try:
      return fn()
   except bench.ToolchainMissing as e:
      raise CommandError(bench.toolchain_text(e.missing)) from e
   except ar.AudioRenderError as e:
      raise CommandError(str(e)) from e


def _print_state(result: ar.RenderResult, frames: int, every: int) -> None:
   """!Which track holds each channel, frame by frame.
   @param result  RenderResult
   @param frames  rows at most
   @param every   every Nth frame
   @return None
   """
   tl = result.timeline()
   for line in state_lines(tl, frames, every):
      print(line)


def state_lines(tl: ar.StateTimeline, frames: int, every: int) -> list[str]:
   """!A channel overview: per frame, each channel's "player.track key" or ".".
   @param tl      StateTimeline
   @param frames  rows at most
   @param every   every Nth frame
   @return lines
   """
   out = ["frame  " + " ".join(f"ch{c.index:<6d}" for c in tl.frames[0].channels) if tl.frames else "(no frames)"]
   step = max(every, 1)
   for f in range(0, len(tl.frames), step):
      if len(out) > frames:
         break
      cells = []
      for ci in range(tl.channel_count()):
         c = tl.sounding(f, ci)
         if c is None:
            cells.append(".".ljust(CELL_WIDTH))
         else:
            p, t = tl.owners.get(c.track, (-1, -1))
            cells.append(f"{p}.{t}:{audio.key_name(c.key):4s}"[:CELL_WIDTH].ljust(CELL_WIDTH))
      out.append(f"{tl.frames[f].frame:5d}  " + " ".join(cells))
   return out


# -- actions -----------------------------------------------------------------------------------------------------------

def cmd_new(args: argparse.Namespace) -> int:
   """!`audio M new`.
   @param args  parsed arguments
   @return exit status
   """
   p = Path(args.manifest)
   if p.exists():
      raise CommandError(f"{p} exists already")
   audio.new_audio(p).save()
   print(f"wrote {p}")
   return 0


def cmd_check(args: argparse.Namespace) -> int:
   """!`audio M check`.
   @param args  parsed arguments
   @return 1 when there are problems
   """
   problems = audio.validate(_open(args))
   for p in problems:
      print(p)
   print(f"{len(problems)} problems" if problems else "ok")
   return 1 if problems else 0


def cmd_info(args: argparse.Namespace) -> int:
   """!`audio M info`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   m = doc.data.get("mixer", {})
   print("mixer: " + ", ".join(f"{k} {m.get(k, v)}" for k, v in audio.DEFAULT_MIXER.items()))
   for i, p in enumerate(audio.players(doc)):
      print(f"player {i}: {p.get('name')}  {p.get('tracks')} tracks"
            f"{'  start check' if p.get('start_check') else ''}")
   print(f"tracks {audio.track_total(doc)} of {audio.MAX_ALL_TRACKS} (with the clip players' {audio.CLIP_TRACKS})")
   for section, _kind in audio.SECTIONS + (("song_table", "sound"),):
      print(f"{section}: {len(doc.data.get(section, []))}")
   return 0


def cmd_mixer_set(args: argparse.Namespace) -> int:
   """!`audio M mixer-set FIELD VALUE`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   audio.set_mixer(doc, args.field, _value(args.value))
   _save(doc)
   return 0


def cmd_songs(args: argparse.Namespace) -> int:
   """!`audio M songs`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   used: dict[str, list[int]] = {}
   for r in audio.sounds(doc):
      if r.song:
         used.setdefault(r.song, []).append(r.number)
   for e in doc.data.get("songs", []):
      form = next((f for f in audio.DATA_FIELDS if f in e), "?")
      try:
         tracks = len(audio.song_code(doc, e["key"])[1])
      except audio.AudioError as ex:
         tracks = f"error: {ex}"
      nums = ",".join(map(str, used.get(e["key"], []))) or "-"
      print(f"{e['key']}  {form}  tracks {tracks}  priority {e.get('priority', 0)}  reverb {e.get('reverb')}  "
            f"{e.get('instruments')}  sounds {nums}")
   return 0


def cmd_song(args: argparse.Namespace) -> int:
   """!`audio M song KEY`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   sv = audio_song.song_view(doc, args.key)
   if args.commands:
      print(audio_song.disassembly(sv.data, sv.tracks), end="")
      return 0
   if args.track is not None:
      if not 0 <= args.track < len(sv.views):
         raise CommandError(f"track {args.track}: the song has {len(sv.views)}")
      print("\n".join(audio_song.listing(sv, args.track)))
      return 0
   end = sv.end_frame
   print(f"{args.key}: {len(sv.views)} tracks, {len(sv.data)} bytes, {sv.length} ticks, " +
         (f"ends on frame {end} ({audio_song.seconds(end):.2f} s)" if end is not None else "loops"))
   for v in sv.views:
      how = v.error or (f"end tick {v.end_tick}" if v.end_tick is not None else
                        f"loops at tick {v.loop_tick} to @{v.loop_to}" if v.loop_tick is not None else
                        f"runs on past tick {audio_song.WALK_LIMIT}")
      print(f"track {v.index} @{v.start}: {len(v.notes)} notes, programs {v.programs or '-'}, {how}")
      if args.notes:
         shown = v.notes if args.limit == 0 else v.notes[:args.limit]
         for n in shown:
            print(f"   tick {n.tick:6d} +{n.length:<4d} {audio.key_name(n.played):5s} v{n.velocity:<3d}"
                  f"{' held' if n.held else ''}  program {n.program}")
         if len(shown) < len(v.notes):
            print(f"   ... {len(v.notes) - len(shown)} more")
   if args.tempo:
      print("tempo: start 75 (tempo 150, a tick a frame)")
      for c in sv.tempo:
         print(f"   tick {c.tick:6d} frame {sv.frame_of(c.tick):6d} track {c.track}: TEMPO {c.bpm}")
   return 0


def cmd_song_set(args: argparse.Namespace) -> int:
   """!`audio M song-set KEY FIELD VALUE`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   value: Any = _value(args.value)
   if args.field == "reverb" and args.value == NONE_WORD:
      value = None
   if args.field == "options":
      value = None if args.value == REMOVE else args.value
   audio.set_song_field(doc, args.key, args.field, value)
   _save(doc)
   return 0


def cmd_export_song(args: argparse.Namespace) -> int:
   """!`audio M export-song KEY OUT`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   data, tracks = audio.song_code(doc, args.key)
   out = Path(args.out)
   if out.suffix == audio.SONG_SUFFIX:
      out.write_bytes(data)
      print(f"wrote {out} ({len(data)} bytes; tracks {tracks})")
   else:
      out.write_text(audio_song.disassembly(data, tracks), encoding="utf-8")
      print(f"wrote {out}")
   return 0


def cmd_render(args: argparse.Namespace) -> int:
   """!`audio M render`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   r = _renderer(doc)
   o = _options(args)
   if args.song:
      count = len(audio.song_code(doc, args.song)[1])
      muted = audio_song.solo_mutes(count, _tracks(args.solo), _tracks(args.mute))
      res = _run_render(lambda: r.song(args.song, args.player, muted, o, _progress))
   elif args.sound is not None:
      number = audio.find_sound(doc, args.sound)
      res = _run_render(lambda: r.sound(number, o, args.saved, _progress))
   else:
      clip = ar.ClipOptions(args.clip_volume, args.clip_pan, args.clip_pitch, args.clip_hold, args.clip_release,
                            args.clip_chorus, args.clip_priority, args.clip_offset)
      res = _run_render(lambda: r.clip(args.clip, clip, o, _progress))
   print("\n".join(res.lines()))
   print(f"wav: {res.wav_path}")
   if args.state and o.state:
      _print_state(res, DEFAULT_STATE_FRAMES, 1)
   _copy_out(res, args.out)
   return 0


def cmd_play(args: argparse.Namespace) -> int:
   """!`audio M play N`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   number = audio.find_sound(doc, args.sound)
   res = _run_render(lambda: _renderer(doc).sound(number, _options(args), True, _progress))
   print("\n".join(res.lines()))
   print(f"wav: {res.wav_path}")
   _copy_out(res, args.out)
   return 0


def cmd_state(args: argparse.Namespace) -> int:
   """!`audio M state FOLDER`.
   @param args  parsed arguments
   @return exit status
   """
   folder = Path(args.folder)
   try:
      summary = json.loads((folder / ar.SUMMARY_FILE).read_text(encoding="utf-8"))
   except (OSError, ValueError) as e:
      raise CommandError(f"{folder}: not a render folder ({e})") from e
   res = ar.RenderResult(folder, summary, folder.name)
   tl = res.timeline()
   if args.frame is not None:
      if not 1 <= args.frame <= len(tl.frames):
         raise CommandError(f"frame {args.frame}: the render has 1-{len(tl.frames)}")
      fs = tl.frames[args.frame - 1]
      for i, (sound, status, clock, prio) in enumerate(fs.players):
         print(f"player {i}: sound {sound} tracks {status & ar.PLAYER_TRACKS:#06x}"
               f"{' paused' if status & ar.PLAYER_PAUSED else ''} clock {clock} priority {prio}")
      for c in fs.channels:
         if c.status & ar.CHANNEL_ON and c.track:
            p, t = tl.owners.get(c.track, (-1, -1))
            print(f"channel {c.index}: player {p} track {t} key {audio.key_name(c.key)} v{c.velocity} "
                  f"priority {c.priority} envelope {c.env}")
      return 0
   print("\n".join(res.lines()))
   for line in state_lines(tl, args.frames, args.every):
      print(line)
   return 0


def cmd_build(args: argparse.Namespace) -> int:
   """!`audio M build`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   exe = _run_render(lambda: _renderer(doc).build(BUILD_TARGETS[args.target], _progress))
   print(exe)
   return 0


def cmd_table(args: argparse.Namespace) -> int:
   """!`audio M table`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   listing = _run_render(lambda: _renderer(doc).list_table(_progress))
   rows = audio.sounds(doc)
   for s in listing.get("sounds", []):
      n = s["sound"]
      song = rows[n].song if n < len(rows) else "?"
      print(f"sound {n}: player {s['player']} key {s['key']:#010x} ({song})")
   print(f"players {listing.get('players')}, clips {listing.get('clips')}, "
         f"{listing.get('samples_per_frame')} samples per frame")
   return 0


def cmd_priority(args: argparse.Namespace) -> int:
   """!`audio M priority A B`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   a, b = audio.find_sound(doc, args.first), audio.find_sound(doc, args.second)
   try:
      if args.model or ar.toolchain():
         pp = ar.priority_preview(doc, a, b, args.delay, args.frames)
      else:
         pp = _renderer(doc).priority(a, b, args.delay, args.frames)   # in the C++ core
   except (ar.AudioRenderError, bench.BenchError) as e:
      raise CommandError(str(e)) from e
   print(f"(run in {'the C++ core' if pp.render is not None else 'the reference model'})")
   print("\n".join(pp.lines()))
   if args.every:
      print("frame  " + " ".join(f"ch{c:<3d}" for c in pp.channels))
      for f in range(0, len(pp.owners), args.every):
         cells = [f"{'AB'[o[0]]}{o[1]:<4d}" if o is not None else ".    " for o in pp.owners[f]]
         print(f"{f:5d}  " + " ".join(cells))
   if args.wav:
      ar.write_wav(Path(args.wav), pp.rate, pp.samples)
      what = "the core's output" if pp.render is not None else "the sampled channels' mix"
      print(f"wrote {args.wav} ({what})")
   return 0


def cmd_sets(args: argparse.Namespace) -> int:
   """!`audio M sets`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   for s in audio.instrument_sets(doc):
      where = f"own voices ({len(s['voices'])})" if "voices" in s else f"{s.get('bank')} from {s.get('offset', 0)}"
      print(f"{s.get('key')}: {where}")
   return 0


def cmd_set(args: argparse.Namespace) -> int:
   """!`audio M set KEY`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   for w in audio.window(doc, args.key, args.count):
      if w.voice is None and not args.all:
         continue
      shared = audio.sets_reading(doc, w.container, w.position) if w.position >= 0 else []
      also = [k for k in shared if k != args.key]
      print(f"{w.index:3d}: {audio.voice_summary(w.voice)}" + (f"  (also {', '.join(also)})" if also else ""))
   return 0


def cmd_set_add(args: argparse.Namespace) -> int:
   """!`audio M set-add NAME`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   print(audio.add_set(doc, args.name, args.bank, args.offset))
   _save(doc)
   return 0


def cmd_set_offset(args: argparse.Namespace) -> int:
   """!`audio M set-offset KEY N`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   audio.set_window_offset(doc, args.key, args.offset)
   _save(doc)
   return 0


def cmd_banks(args: argparse.Namespace) -> int:
   """!`audio M banks`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   for b in audio.bank_windows(doc):
      print(f"{b.key}: {b.length} voices")
      for key, first, count in b.windows:
         print(f"   {key}: voices {first}-{first + count - 1}")
      for a, c, shared in audio.overlaps(b.windows):
         print(f"   {a} and {c} share {shared} voices")
   return 0


def cmd_bank_add(args: argparse.Namespace) -> int:
   """!`audio M bank-add NAME`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   print(audio.add_bank(doc, args.name))
   _save(doc)
   return 0


def cmd_voice(args: argparse.Namespace) -> int:
   """!`audio M voice SET INDEX`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   w = audio.window(doc, args.set, args.index + 1)[args.index]
   print(json.dumps(w.voice))
   if w.position >= 0:
      print(f"{w.container} voice {w.position}; read by {', '.join(audio.sets_reading(doc, w.container, w.position))}")
   else:
      print(f"past the end of {w.container}: a none voice")
   return 0


def cmd_voice_set(args: argparse.Namespace) -> int:
   """!`audio M voice-set SET INDEX FIELD=VALUE ...`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   fields = _fields(args.fields)
   old = audio.window_voice(doc, args.set, args.index) or {"kind": "none"}
   v = audio.new_voice(doc, fields.pop("kind"), old) if "kind" in fields else dict(old)
   for name, value in fields.items():
      if value is None:
         v.pop(name, None)
      else:
         v[name] = value
   audio.set_voice(doc, args.set, args.index, v)
   print(audio.voice_summary(v))
   _save(doc)
   return 0


def cmd_voice_add(args: argparse.Namespace) -> int:
   """!`audio M voice-add CONTAINER KIND [FIELD=VALUE ...]`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   v = audio.new_voice(doc, args.kind)
   for name, value in _fields(args.fields).items():
      if value is None:
         v.pop(name, None)
      else:
         v[name] = value
   print(f"voice {audio.append_voice(doc, args.container, v)}: {audio.voice_summary(v)}")
   _save(doc)
   return 0


def cmd_envelope(args: argparse.Namespace) -> int:
   """!`audio M envelope SET INDEX`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   v = audio.window_voice(doc, args.set, args.index)
   if v is None or v.get("kind") in ("none", "split", "drums"):
      raise CommandError(f"{args.set} voice {args.index} has no envelope")
   levels, full = audio.envelope_of(v, args.held)
   print(f"{audio.voice_summary(v)}; level per frame (full {full}), note held {args.held} frames:")
   print(" ".join(map(str, levels)))
   return 0


def cmd_keymaps(args: argparse.Namespace) -> int:
   """!`audio M keymaps`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   for k in doc.data.get("keymaps", []):
      runs = audio.keymap_ranges(k.get("entries", []))
      print(f"{k.get('key')}: " + ", ".join(f"{audio.key_name(a)}-{audio.key_name(b)} -> {v}" for a, b, v in runs))
   return 0


def cmd_keymap_add(args: argparse.Namespace) -> int:
   """!`audio M keymap-add NAME`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   print(audio.add_keymap(doc, args.name, args.value))
   _save(doc)
   return 0


def cmd_keymap_set(args: argparse.Namespace) -> int:
   """!`audio M keymap-set KEY FIRST LAST ENTRY`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   audio.set_keymap_range(doc, args.key, _key(args.first), _key(args.last), args.value)
   _save(doc)
   return 0


def cmd_split(args: argparse.Namespace) -> int:
   """!`audio M split SET INDEX`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   v = audio.window_voice(doc, args.set, args.index)
   if v is None or v.get("kind") != "split":
      raise CommandError(f"{args.set} voice {args.index} is not a split voice")
   for first, last, value, target in audio.split_targets(doc, v):
      print(f"{audio.key_name(first)}-{audio.key_name(last)}: entry {value}: {audio.voice_summary(target)}")
   return 0


def cmd_drums(args: argparse.Namespace) -> int:
   """!`audio M drums SET`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   for key, v in audio.drum_map(doc, args.set):
      if v is not None and v.get("kind") != "none":
         print(f"{key:3d} {audio.key_name(key):5s} {audio.voice_summary(v)}")
   return 0


def cmd_waves(args: argparse.Namespace) -> int:
   """!`audio M waves`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   for w in doc.data.get("waves", []):
      print(f"{w.get('key')}: {w.get('data')}")
   return 0


def cmd_wave_add(args: argparse.Namespace) -> int:
   """!`audio M wave-add NAME LEVELS`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   try:
      levels = audio.wave_levels(args.levels)
   except ValueError as e:
      raise CommandError(f"levels are {audio.WAVE_NIBBLES} hex digits: {e}") from e
   print(audio.add_wave(doc, args.name, levels))
   _save(doc)
   return 0


def cmd_samples(args: argparse.Namespace) -> int:
   """!`audio M samples`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   for e in doc.data.get("samples", []):
      rate = int(e.get("pitch", 0)) / audio.PITCH_SCALE
      loop = f"loop from {e.get('loop_start', 0)}" if e.get("loop") else "one-shot"
      print(f"{e.get('key')}: {e.get('format', 'pcm8')} {rate:.1f} Hz, {e.get('length')} samples, {loop}, "
            f"{e.get('data')}")
   return 0


def cmd_sample(args: argparse.Namespace) -> int:
   """!`audio M sample KEY`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   e = audio.entry(doc, args.key)
   print(json.dumps(e))
   levels = audio.sample_levels(doc, args.key)
   print(" ".join(map(str, levels[:args.levels])) + (" ..." if len(levels) > args.levels else ""))
   if args.png:
      wave_png(Path(args.png), levels, args.width, int(e.get("loop_start", 0)) if e.get("loop") else None)
      print(f"wrote {args.png}")
   return 0


def wave_png(path: Path, levels: list[int], width: int, loop: int | None) -> None:
   """!Draws levels (-128..127) as a waveform picture with the engine's PNG writer.
   @param path    the PNG
   @param levels  the levels
   @param width   pixels
   @param loop    the loop start (a marker), or None
   @return None
   """
   from ..core import engine
   back, line, centre, mark = WAVE_COLOURS
   h, w = WAVE_PNG_HEIGHT, max(width, 1)
   px = bytearray(bytes(back) * (w * h))

   def put(x: int, y: int, c: tuple[int, ...]) -> None:
      """!One pixel.
      @param x  column
      @param y  row
      @param c  RGBA
      @return None
      """
      if 0 <= x < w and 0 <= y < h:
         at = (y * w + x) * RGBA_BYTES
         px[at:at + RGBA_BYTES] = bytes(c)

   span = audio.BYTE_MAX + 1
   for x in range(w):
      put(x, h // HALF, centre)
   n = len(levels)
   for x in range(w):
      part = levels[x * n // w:max((x + 1) * n // w, x * n // w + 1)] if n else []
      if not part:
         continue
      top = (audio.SIGNED_MAX - max(part)) * (h - 1) // (span - 1)
      bottom = (audio.SIGNED_MAX - min(part)) * (h - 1) // (span - 1)
      for y in range(top, bottom + 1):
         put(x, y, line)
   if loop is not None and n:
      for y in range(h):
         put(loop * w // n, y, mark)
   engine.bitmap().write_png(path, w, h, px)


def cmd_sample_import(args: argparse.Namespace) -> int:
   """!`audio M sample-import WAV NAME`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   o = audio.WavOptions("dpcm4" if args.dpcm else "pcm8", args.lookahead, args.pad, args.loop_start, args.length,
                        _key(args.key) if args.key else None, args.tune)
   e = audio.import_wav(doc, args.wav, args.name, o, args.replace)
   print(f"{e['key']}: {e['format']}, pitch {e['pitch']}, {e['length']} samples, "
         f"{'loop from ' + str(e['loop_start']) if e['loop'] else 'one-shot'}, {e['data']}")
   _save(doc)
   return 0


def cmd_sample_set(args: argparse.Namespace) -> int:
   """!`audio M sample-set KEY FIELD VALUE`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   audio.set_sample_field(doc, args.key, args.field, _value(args.value))
   _save(doc)
   return 0


def cmd_midi(args: argparse.Namespace) -> int:
   """!`audio M midi-import MIDI NAME`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   fields: dict[str, Any] = {}
   if args.instruments:
      fields["instruments"] = audio.full_key(args.instruments, "instruments")
   for name in ("priority", "volume"):
      if getattr(args, name) is not None:
         fields[name] = getattr(args, name)
   if args.reverb is not None:
      fields["reverb"] = None if args.reverb == NONE_WORD else int(args.reverb)
   try:
      source = Path(args.midi).read_bytes()
   except OSError as e:
      raise CommandError(str(e)) from e
   opts = audio.midi_options(args.options, fields)
   song = audio.convert_midi(source, opts, Path(args.midi).stem)
   print("\n".join(audio.midi_report(song).lines()))
   if args.listing:
      print(audio.midi().listing(song), end="")
   if args.report_only:
      return 0
   e, number = audio.add_midi_song(doc, args.midi, args.name, args.options, fields, args.form, args.player,
                                   args.sound_name, args.replace)
   print(f"{e['key']}: {args.form} form ({e.get('midi') or e.get('data')})" +
         (f", sound {number} on {args.player}" if number is not None else ""))
   _save(doc)
   return 0


def cmd_sounds(args: argparse.Namespace) -> int:
   """!`audio M sounds`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   for r in audio.sounds(doc):
      print(f"{r.number:4d} {str(r.song):24s} {r.player:10s} priority {r.priority:3d}"
            f"{'  start check' if r.start_check else ''}{'  ' + r.name if r.name else ''}")
   return 0


def cmd_sound_set(args: argparse.Namespace) -> int:
   """!`audio M sound-set N`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   song: str | None = ""
   if args.song is not None:
      song = None if args.song == NONE_WORD else audio.full_key(args.song, "song")
   name: str | None = ""
   if args.name is not None:
      name = None if args.name == REMOVE else args.name
   audio.set_sound(doc, args.number, song, args.player, name)
   _save(doc)
   return 0


def cmd_sound_add(args: argparse.Namespace) -> int:
   """!`audio M sound-add SONG PLAYER`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   song = None if args.song == NONE_WORD else audio.full_key(args.song, "song")
   print(f"sound {audio.add_sound(doc, song, args.player, args.name)}")
   _save(doc)
   return 0


def cmd_sound_remove(args: argparse.Namespace) -> int:
   """!`audio M sound-remove N`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   audio.remove_sound(doc, args.number)
   _save(doc)
   return 0


def cmd_players(args: argparse.Namespace) -> int:
   """!`audio M players`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   rows = audio.sounds(doc)
   for i, p in enumerate(audio.players(doc)):
      nums = [r.number for r in rows if r.player_index == i]
      print(f"{i}: {p.get('name')}  {p.get('tracks')} tracks{'  start check' if p.get('start_check') else ''}  "
            f"{len(nums)} sounds")
   return 0


def cmd_player_set(args: argparse.Namespace) -> int:
   """!`audio M player-set INDEX`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   check = YES_NO[args.start_check] if args.start_check is not None else None
   audio.set_player(doc, args.index, args.name, args.tracks, check)
   _save(doc)
   return 0


def cmd_player_add(args: argparse.Namespace) -> int:
   """!`audio M player-add NAME TRACKS`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   print(f"player {audio.add_player(doc, args.name, args.tracks, args.start_check)}")
   _save(doc)
   return 0


def cmd_remove(args: argparse.Namespace) -> int:
   """!`audio M remove KEY`.
   @param args  parsed arguments
   @return exit status
   """
   doc = _open(args)
   audio.remove_entry(doc, args.key)
   _save(doc)
   return 0
