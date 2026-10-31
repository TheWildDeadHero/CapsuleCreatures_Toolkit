"""![S7] A song as the song player and viewer shows it (engine M4, D-34): its tracks' notes on a timeline, the
commands each track runs (the .cseq text form, format.disassemble()), the tempo map (ticks to frames, the
sequencer's rule: a frame adds the tempo to a counter and runs a tick per 150 it holds) and the end of each
track. The tracks are walked with midi_song.walk(), the engine's own walker (A6), so ticks and ends are those of
the import report.

mute() makes the preview's variant of a song with some tracks silent (the song player's mute / solo): the
muted tracks run a copy of the song's bytes whose VOLUME commands are 0, so they keep their timing and still
take channels (a mute is heard as on a mixer; channel stealing stays as it is).

Qt-free; the song panel and `capsule-studio audio song` use it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import audio

## The sequencer runs a tick for every 150 the tempo counter holds (tempo 150 = a tick a frame).
TICK_THRESHOLD = 150
## A song's tempo before its first TEMPO command (twice the command's value: 75 x 2).
START_TEMPO = 150
## TEMPO's argument is half the tempo the counter adds.
TEMPO_FACTOR = 2
## Frames per second of the handheld's display (280,896 cycles of 16.78 MHz), for times shown in seconds.
FRAMES_PER_SECOND = 59.7275
## Ticks per beat of the command lengths (96 ticks a whole note).
TICKS_PER_BEAT = 24
## Ticks a walk stops after (a track that never ends and never jumps back: shown as running on).
WALK_LIMIT = 1 << 16
## A song's first sequencer step comes on this render frame (audio_render: init, an empty blank, then the calls).
FIRST_RENDER_FRAME = 2
## Bytes of a u16 argument.
U16_BYTES = 2
## A NOTE's gate extra: its third argument.
EXTRA_ARG = 2
## Byte value where commands start.
COMMAND_FIRST = 0x80
## Highest u16 (song data offsets).
U16_MAX = 0xFFFF
## Argument offsets of jump targets after the command byte: JUMP / CALL, REPEAT (after the count), VAR (after
## operation, address and value).
TARGET_AT = {"JUMP": 1, "CALL": 1, "REPEAT": 2, "VAR": 4}


@dataclass
class Note:
   """!One note a track plays."""

   ## Its track.
   track: int
   ## The tick it starts at.
   tick: int
   ## Ticks it sounds (a held note: until its NOTE_OFF, or the track's end).
   length: int
   ## The key written (before TRANSPOSE).
   key: int
   ## The key it plays at (with the track's TRANSPOSE).
   played: int
   ## Velocity.
   velocity: int
   ## The track's PROGRAM when it starts (-1: none yet, the reset voice).
   program: int
   ## Held until a NOTE_OFF (NOTE 0).
   held: bool
   ## Its command's offset in the song data.
   offset: int


@dataclass
class TrackView:
   """!One track."""

   ## Track number.
   index: int
   ## Its start offset in the song data.
   start: int
   ## Every command it runs (midi_song.Step: tick, offset, command, args), up to its end or loop.
   steps: list[Any] = field(default_factory=list)
   ## Its notes.
   notes: list[Note] = field(default_factory=list)
   ## The tick END runs at, or None (it loops or runs on).
   end_tick: int | None = None
   ## The tick it jumps back at, or None.
   loop_tick: int | None = None
   ## The offset it jumps back to, or None.
   loop_to: int | None = None
   ## PROGRAM numbers it uses, in order of first use.
   programs: list[int] = field(default_factory=list)
   ## A problem walking it, or None.
   error: str | None = None
   ## It neither ends nor jumps back within WALK_LIMIT ticks.
   runs_on: bool = False


@dataclass
class TempoChange:
   """!A TEMPO command."""

   ## The tick it runs at.
   tick: int
   ## Its track.
   track: int
   ## The command's value (beats per minute, as the source wrote it).
   bpm: int


@dataclass
class SongView:
   """!A song for the player and viewer."""

   ## The command bytes.
   data: bytes
   ## Track start offsets.
   tracks: list[int]
   ## Per track.
   views: list[TrackView]
   ## TEMPO commands by tick.
   tempo: list[TempoChange]
   ## Frame (song frame: 1 = the first sequencer step) each tick runs on, for ticks 0..length.
   tick_frames: list[int]

   @property
   def length(self) -> int:
      """!Ticks the viewer shows: the latest end or loop.
      @return ticks
      """
      views = self.views   # a local alias (Doxygen 1.12 reads a dataclass field used in a method as a new member)
      ends = [v.end_tick if v.end_tick is not None else (v.loop_tick or 0) for v in views]
      notes = [n.tick + n.length for v in views for n in v.notes]
      return max(ends + notes + [0])

   @property
   def loops(self) -> bool:
      """!Whether a track jumps back (the song plays until stopped).
      @return True when one does
      """
      views = self.views   # a local alias (Doxygen 1.12 reads a dataclass field used in a method as a new member)
      return any(v.loop_tick is not None or v.runs_on for v in views)

   @property
   def end_frame(self) -> int | None:
      """!The song frame its last END runs on (None when a track loops).
      @return frame
      """
      views, frames = self.views, self.tick_frames   # local aliases (Doxygen reads dataclass fields here as members)
      if not views:
         return 1
      if any(v.end_tick is None for v in views):
         return None
      end = max(v.end_tick or 0 for v in views)
      return frames[end] if end < len(frames) else None

   def frame_of(self, tick: int) -> int:
      """!The song frame a tick runs on.
      @param tick  the tick
      @return frame (the last known one past the map)
      """
      frames = self.tick_frames
      if not frames:
         return 1
      return frames[min(max(tick, 0), len(frames) - 1)]

   def tick_at(self, frame: int) -> int:
      """!The latest tick that ran by a song frame.
      @param frame  the frame
      @return tick (0 before the first)
      """
      frames = self.tick_frames   # a local alias (Doxygen reads a dataclass field used here as a member)
      lo, hi = 0, len(frames)
      while lo < hi:
         mid = (lo + hi) >> 1
         if frames[mid] <= frame:
            lo = mid + 1
         else:
            hi = mid
      return max(lo - 1, 0)


def _walk(data: bytes, start: int) -> Any:
   """!midi_song.walk() of one track.
   @param data   the song data
   @param start  its offset
   @return midi_song.TrackRun
   """
   return audio.midi().walk(data, start, WALK_LIMIT)


def track_view(data: bytes, index: int, start: int) -> TrackView:
   """!Walks one track and collects its notes.
   @param data   the song data
   @param index  its number
   @param start  its offset
   @return TrackView
   """
   m = audio.midi()
   tv = TrackView(index, start)
   try:
      run = _walk(data, start)
   except m.MidiError as e:
      tv.error = str(e)
      return tv
   tv.steps, tv.end_tick, tv.loop_tick, tv.loop_to = run.steps, run.end_tick, run.loop_tick, run.loop_to
   if tv.end_tick is None and tv.loop_tick is None:
      # A REPEAT with count 0 jumps every time: when it jumps back, it is the track's loop.
      for k, s in enumerate(tv.steps):
         if s.command == m.REPEAT and len(s.args) > 1 and s.args[0] == 0 and s.args[1] <= s.offset:
            tv.loop_tick, tv.loop_to, tv.steps = s.tick, s.args[1], tv.steps[:k + 1]
            break
      else:
         tv.runs_on = True
   key, velocity, program, shift = audio.BASE_KEY, 0, -1, 0
   open_notes: list[Note] = []
   last = tv.end_tick if tv.end_tick is not None else (tv.loop_tick if tv.loop_tick is not None else WALK_LIMIT)
   for s in tv.steps:
      c = s.command
      if m.NOTE <= c < m.WAIT:
         if len(s.args) > 0:
            key = s.args[0]
         if len(s.args) > 1:
            velocity = s.args[1]
         extra = s.args[EXTRA_ARG] if len(s.args) > EXTRA_ARG else 0
         ticks = m.LENGTHS[c - m.NOTE]
         n = Note(index, s.tick, ticks + extra, key, key + shift, velocity, program, ticks == 0, s.offset)
         tv.notes.append(n)
         if n.held:
            open_notes.append(n)
      elif c == m.NOTE_OFF:
         if s.args:
            key = s.args[0]
         for n in open_notes:
            if n.key == key:
               n.length = s.tick - n.tick
               open_notes.remove(n)
               break
      elif c == m.PROGRAM and s.args:
         program = s.args[0]
         if program not in tv.programs:
            tv.programs.append(program)
      elif c == m.TRANSPOSE and s.args:
         shift = s.args[0] - (audio.BYTE_MAX + 1) if s.args[0] > audio.SIGNED_MAX else s.args[0]
   for n in open_notes:
      n.length = max(last - n.tick, 1)   # held to the end (or the loop)
   return tv


def tick_frames(tempo: list[TempoChange], length: int) -> list[int]:
   """!The song frame each tick runs on, the sequencer's way (midi_song.frames_to_end()'s rule): each frame adds
   the tempo to a counter and runs a tick per 150; a TEMPO run in a tick counts from the next frame.
   @param tempo   TEMPO commands by tick
   @param length  the last tick
   @return frames for ticks 0..length (shorter when the tempo drops to 0)
   """
   out: list[int] = []
   rate, counter, tick, frame, at = START_TEMPO, 0, 0, 0, 0
   while tick <= length:
      frame += 1
      counter += rate
      while counter >= TICK_THRESHOLD and tick <= length:
         counter -= TICK_THRESHOLD
         while at < len(tempo) and tempo[at].tick <= tick:
            rate = tempo[at].bpm * TEMPO_FACTOR
            at += 1
         out.append(frame)
         tick += 1
      if rate == 0 and counter < TICK_THRESHOLD:
         break
   return out


def analyse(data: bytes, tracks: list[int]) -> SongView:
   """!A song's tracks, notes, tempo map and ends.
   @param data    the command bytes
   @param tracks  track offsets
   @return SongView
   """
   m = audio.midi()
   views = [track_view(data, i, t) for i, t in enumerate(tracks)]
   tempo = sorted((TempoChange(s.tick, v.index, s.args[0]) for v in views for s in v.steps
                   if s.command == m.TEMPO and s.args), key=lambda c: (c.tick, c.track))
   sv = SongView(bytes(data), list(tracks), views, tempo, [])
   sv.tick_frames = tick_frames(tempo, sv.length)
   return sv


def song_view(doc: audio.AudioDocument, key: str) -> SongView:
   """!A manifest song as a SongView.
   @param doc  AudioDocument
   @param key  "song:NAME"
   @return SongView
   @throws audio.AudioError when the song cannot be loaded
   """
   data, tracks = audio.song_code(doc, key)
   return analyse(data, tracks)


def disassembly(data: bytes, tracks: list[int]) -> str:
   """!The song's text form (format.disassemble(): one command per line, TRACK markers, labels).
   @param data    the command bytes
   @param tracks  track offsets
   @return text
   """
   return audio.fmt().disassemble(data, tracks)


def step_text(step: Any) -> str:
   """!One walked command as text.
   @param step  midi_song.Step
   @return e.g. "NOTE 24 60 100", "WAIT 12"
   """
   m = audio.midi()
   c = step.command
   if m.NOTE <= c < m.WAIT:
      name = f"NOTE {m.LENGTHS[c - m.NOTE]}"
   elif m.WAIT <= c < m.END:
      name = f"WAIT {m.LENGTHS[c - m.WAIT]}"
   else:
      name = m.NAMES.get(c, f"0x{c:02X}")
   return f"{name} {' '.join(str(a) for a in step.args)}".rstrip()


def listing(view: SongView, track: int) -> list[str]:
   """!A track's commands with their ticks (what it runs, in order, jumps and calls followed).
   @param view   SongView
   @param track  the track
   @return lines "tick @offset COMMAND args"
   """
   tv = view.views[track]
   lines = [f"{s.tick:7d} @{s.offset:05d} {step_text(s)}" for s in tv.steps]
   if tv.error:
      lines.append(f"error: {tv.error}")
   elif tv.end_tick is not None:
      lines.append(f"{tv.end_tick:7d} end")
   elif tv.loop_tick is not None:
      lines.append(f"{tv.loop_tick:7d} loops to @{tv.loop_to:05d}")
   elif tv.runs_on:
      lines.append(f"{WALK_LIMIT:7d} runs on (no END and no jump back within {WALK_LIMIT} ticks)")
   return lines


def seconds(frames: int) -> float:
   """!Frames as seconds of the handheld's display rate.
   @param frames  frames
   @return seconds
   """
   return frames / FRAMES_PER_SECOND


def mute(data: bytes, tracks: list[int], muted: set[int] | list[int]) -> tuple[bytes, list[int]]:
   """!The song with some tracks silent: the muted tracks start in a copy of the data whose VOLUME commands (and
   VOLUME arguments under running status) are 0 and whose jump targets point into the copy. They keep their
   timing and still take channels.
   @param data    the command bytes
   @param tracks  track offsets
   @param muted   track numbers to silence
   @return (data, track offsets) of the variant (the input when nothing is muted)
   @throws audio.AudioError when the variant would pass the data's u16 offsets
   """
   chosen = {t for t in muted if 0 <= t < len(tracks)}
   if not chosen:
      return bytes(data), list(tracks)
   base = len(data)
   if base + base > U16_MAX + 1:
      raise audio.AudioError(f"the song's {base} bytes are too many to mute a track (the copy passes 64 KiB)")
   f = audio.fmt()
   volume = f.COMMANDS["VOLUME"][0]
   copy = bytearray(data)
   running = None
   for c in f.decode(bytes(data)):
      first = data[c.at]
      if first >= COMMAND_FIRST:
         if f.is_running(first):
            running = first
         cmd = first
         arg = c.at + 1
      else:
         cmd = running
         arg = c.at
      if cmd == volume and arg < base and c.error is None:
         copy[arg] = 0
      name = c.text.split(" ", 1)[0]
      if c.target is not None and name in TARGET_AT and first >= COMMAND_FIRST:
         at = c.at + TARGET_AT[name]
         copy[at:at + U16_BYTES] = (c.target + base).to_bytes(U16_BYTES, "little")
   out = bytes(data) + bytes(copy)
   return out, [t + base if i in chosen else t for i, t in enumerate(tracks)]


def solo_mutes(count: int, solo: set[int] | list[int], muted: set[int] | list[int]) -> set[int]:
   """!The tracks a preview silences: every track but the solo ones when any is solo, plus the muted ones.
   @param count  tracks
   @param solo   solo tracks
   @param muted  muted tracks
   @return track numbers
   """
   out = set(muted)
   if solo:
      out |= {t for t in range(count) if t not in set(solo)}
   return {t for t in out if 0 <= t < count}
