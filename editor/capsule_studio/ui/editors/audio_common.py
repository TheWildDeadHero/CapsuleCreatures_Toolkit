"""![S7] What the audio editor's panels share (engine M4, D-34): the render bar (render through the engine's
audio_render on a worker thread, play the WAV, open or save it), the WAV player, and the drawings: a piano roll
of a song's notes, the player state's channel lanes, a waveform, an envelope curve, a key strip of 128 keys and
the windows of a voice bank.

Playing. The WAV plays through Qt Multimedia (QMediaPlayer + QAudioOutput) when it is installed and an audio
output exists (PySide6-Addons: the toolkit's optional audio group, C14b), never on the offscreen platform the tests
use. Without it, or when the media player reports an error, the editor stays usable: Play hands the WAV to the
system's player and runs the playhead over the song at the real speed, and Open in player / Save WAV as... hand the
file to the system's player or a folder.
"""
from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import audio, audio_render as ar, bench
from .. import background
from ..widgets import button, headless

if TYPE_CHECKING:
   from ...core.audio_song import Note, SongView

## Track colours (piano roll, channel lanes, legends), by track number modulo their count.
TRACK_COLOURS = ((90, 170, 255), (255, 150, 70), (120, 210, 120), (230, 110, 200), (240, 220, 90),
                 (120, 220, 220), (200, 140, 255), (255, 110, 110), (170, 190, 120), (150, 150, 255),
                 (255, 190, 160), (140, 255, 180), (210, 170, 120), (180, 120, 160), (120, 160, 200),
                 (220, 220, 220))
## Colour of other players' tracks in the channel lanes.
OTHER_COLOUR = (150, 150, 150)
## Background, grid and text colours of the drawings.
BACKGROUND, GRID, TEXT = (28, 30, 36), (58, 62, 72), (200, 204, 212)
## Colour of the playhead.
PLAYHEAD = (255, 255, 255)
## Colour of a loop marker.
LOOP_COLOUR = (255, 180, 60)
## Alpha of a muted track's notes.
MUTED_ALPHA = 60
## Full alpha.
OPAQUE = 255
## Piano roll: pixels per tick at zoom 1, the key row height, the margin for key names.
ROLL_TICK_PIXELS, ROLL_KEY_PIXELS, ROLL_MARGIN = 2.0, 5, 34
## Piano roll keys shown at least (around the notes).
ROLL_MIN_KEYS = 24
## Ticks between grid lines (a beat of 24 ticks) and their bar (4 beats).
BEAT_TICKS, BAR_BEATS = 24, 4
## Channel lanes: row height and label width.
LANE_HEIGHT, LANE_LABEL = 16, 52
## Pixels per frame of the channel lanes at zoom 1.
LANE_FRAME_PIXELS = 2.0
## Waveform and envelope views: height.
WAVE_HEIGHT = 150
## Envelope view height.
ENVELOPE_HEIGHT = 120
## Key strip: key width and height, the octave label's height.
KEY_WIDTH, KEY_HEIGHT, KEY_LABEL = 7, 34, 12
## Keys of an octave that are black (C# D# F# G# A#).
BLACK_KEYS = (1, 3, 6, 8, 10)
## Bank view: row height, the pixels per voice at most.
BANK_ROW, BANK_VOICE_PIXELS = 18, 4.0
## Milliseconds between playhead updates.
PLAYHEAD_MS = 30
## Milliseconds per second.
MS_PER_SECOND = 1000
## Milliseconds between looks at a running job's progress text.
PROGRESS_MS = 200
## Characters of the last progress line the render bar shows.
PROGRESS_CHARS = 90
## Range of the render length spin (seconds).
SECONDS_RANGE = (1, 600)
## Zoom factors of the drawings (slider steps: zoom = ZOOM_STEP ** (value / ZOOM_TICKS)).
ZOOM_STEP, ZOOM_TICKS, ZOOM_RANGE = 2.0, 4, (-12, 16)
## The highest 8-bit level (waveforms) and the span of signed levels.
LEVEL_MAX, LEVEL_SPAN = 127, 256
## Whether a WAV can be played here, and why not: (True, an empty text) or (False, the reason).
PlayCheck = tuple[bool, str]
## Halves (centre lines).
HALF = 2
## Pixels between a drawing's left edge and its labels.
LABEL_INSET = 2
## Layout stretch of a view that takes twice its neighbour's room.
WIDE_STRETCH = 2


def document_of(panel: QtWidgets.QWidget) -> audio.AudioDocument | None:
   """!A panel's AudioDocument (its host's; a call, where Doxygen misreads `self.doc` in some uses).
   @param panel  an EditorPanel
   @return AudioDocument, or None
   """
   return getattr(panel.host, "document", None)


def colour(rgb: Sequence[int], alpha: int = OPAQUE) -> QtGui.QColor:
   """!A QColor.
   @param rgb    (r, g, b)
   @param alpha  0-255
   @return QColor
   """
   r, g, b = rgb[:len("rgb")]
   return QtGui.QColor(r, g, b, alpha)


def track_colour(track: int, alpha: int = OPAQUE) -> QtGui.QColor:
   """!A track's colour.
   @param track  track number
   @param alpha  0-255
   @return QColor
   """
   return colour(TRACK_COLOURS[track % len(TRACK_COLOURS)], alpha)


def zoom_of(value: int) -> float:
   """!A zoom slider's value as a factor.
   @param value  slider position
   @return factor
   """
   return ZOOM_STEP ** (value / ZOOM_TICKS)


def zoom_slider(changed: Callable[[float], None], value: int = 0) -> QtWidgets.QSlider:
   """!A horizontal zoom slider.
   @param changed  callable(factor)
   @param value    its start position (0 = 1x)
   @return QSlider
   """
   s = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
   s.setRange(*ZOOM_RANGE)
   s.setValue(value)
   s.setToolTip("Zoom")
   s.valueChanged.connect(lambda v: changed(zoom_of(v)))
   return s


# -- playing --------------------------------------------------------------------------------------------------------

def multimedia() -> Any:
   """!Qt Multimedia, when installed.
   @return the QtMultimedia module, or None
   """
   try:
      from PySide6 import QtMultimedia
   except ImportError:
      return None
   return QtMultimedia


def can_play() -> PlayCheck:
   """!Whether a WAV can be played here.
   @return (True, an empty text) or (False, why not)
   """
   if headless():
      return False, "no audio output on the offscreen platform"
   mm = multimedia()
   if mm is None:
      return False, "Qt Multimedia is not installed (PySide6's QtMultimedia module)"
   try:
      if not mm.QMediaDevices.audioOutputs():
         return False, "no audio output device"
   except RuntimeError as e:
      return False, f"no audio output ({e})"
   return True, ""


class WavPlayer(QtCore.QObject):
   """!Plays a WAV through Qt Multimedia when it can, else runs a silent clock; position() is the time either way.
   """

   ## C14b: emitted with Qt Multimedia's error text when it fails while playing (no backend, no device after all, a
   ## file it can't decode); the player is silent from then on, its clock still runs, the owner hands the WAV on.
   failed = QtCore.Signal(str)

   def __init__(self, parent: QtCore.QObject | None = None) -> None:
      """!An idle player.
      @param parent  owner
      """
      super().__init__(parent)
      ## The QMediaPlayer (made at the first play), or None.
      self._media = None
      ## Its QAudioOutput.
      self._output = None
      ## When the silent clock started (time.monotonic()), or None.
      self._started = None
      ## Length of what plays, seconds.
      self.length = 0.0
      ## Whether the last play() has sound.
      self.audible = False

   def play(self, path: Path, length: float) -> None:
      """!Plays a WAV (or starts the silent clock).
      @param path    the file
      @param length  its length, seconds
      @return None
      """
      self.stop()
      self.length = length
      ok, _why = can_play()
      self.audible = ok
      if ok:
         mm = multimedia()
         if self._media is None:
            self._media = mm.QMediaPlayer(self)
            self._output = mm.QAudioOutput(self)
            self._media.setAudioOutput(self._output)
            self._media.errorOccurred.connect(lambda _error, text: self._media_failed(text))
         self._media.setSource(QtCore.QUrl.fromLocalFile(str(path)))
         self._media.play()
      self._started = time.monotonic()

   def stop(self) -> None:
      """!Stops.
      @return None
      """
      if self._media is not None:
         self._media.stop()
      self._started = None

   def _media_failed(self, text: str) -> None:
      """!Qt Multimedia's error while playing: silent from now on (the clock goes on), then failed.
      @param text  its description
      @return None
      """
      if not self.audible:
         return
      self.audible = False
      self.failed.emit(text or "Qt Multimedia could not play the WAV")

   def playing(self) -> bool:
      """!Whether it plays (until its length).
      @return True while it does
      """
      return self._started is not None and self.position() < self.length

   def position(self) -> float:
      """!Seconds since play().
      @return seconds (0 when stopped)
      """
      if self._started is None:
         return 0.0
      if self.audible and self._media is not None and self._media.position() > 0:
         return self._media.position() / MS_PER_SECOND
      return time.monotonic() - self._started


def open_externally(path: Path) -> bool:
   """!Opens a file in the system's program for it.
   @param path  the file
   @return True when handed over
   """
   if headless():
      return False
   return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))


class RenderBar(QtWidgets.QWidget):
   """!Render / Play / Stop / Open in player / Save WAV as..., the render length, mono and HQ, and the result.

   The panel gives start(work, label) a callable that renders on a worker thread (core.audio_render: no Document
   access) and gets the RenderResult in its rendered callback on the GUI thread.

   @var result
   The latest RenderResult, or None.
   """

   def __init__(self, render: Callable[[], None], rendered: Callable[[ar.RenderResult], None],
                parent: QtWidgets.QWidget | None = None, tick: Callable[[float], None] | None = None) -> None:
      """!Creates the bar.
      @param render    callable(): the panel's Render button (it calls start())
      @param rendered  callable(RenderResult) on the GUI thread
      @param parent    parent widget
      @param tick      callable(seconds) while playing (the playhead), or None
      """
      super().__init__(parent)
      ## The panel's render action.
      self._render = render
      ## The panel's result callback.
      self._rendered = rendered
      ## The playhead callback.
      self._tick = tick
      ## The latest RenderResult, or None.
      self.result = None
      ## The latest progress text (written on the worker thread).
      self._progress = ""
      ## The player.
      self.player = WavPlayer(self)
      self.player.failed.connect(lambda why: self._play_failed(why))
      ## Seconds spin (render at most).
      self.seconds = QtWidgets.QSpinBox()
      self.seconds.setRange(*SECONDS_RANGE)
      self.seconds.setValue(ar.DEFAULT_SECONDS)
      self.seconds.setSuffix(" s")
      self.seconds.setToolTip("Render at most this long (a looping song renders this long)")
      ## Mono output.
      self.mono = QtWidgets.QCheckBox("Mono")
      ## High-quality desktop mix.
      self.hq = QtWidgets.QCheckBox("HQ")
      self.hq.setToolTip("The optional high-quality desktop mix (4x the samples, 16-bit sums); the GBA and parity "
                         "runs use the normal mix")
      ## Render button.
      self.render_button = button("Render", lambda: self._render(), "Render through the engine's audio_render "
                                                                     "(builds it the first time)")
      ## Play button.
      self.play_button = button("Play", lambda: self.play())
      ## Stop button.
      self.stop_button = button("Stop", lambda: self.stop())
      ## Open in player button.
      self.open_button = button("Open in player", lambda: self.open_wav(), "Open the WAV in the system's player")
      ## Save WAV button.
      self.save_button = button("Save WAV as...", lambda: self.save_wav())
      ## Status text.
      self.status = QtWidgets.QLabel("Not rendered yet")
      self.status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      column = QtWidgets.QVBoxLayout(self)
      column.setContentsMargins(0, 0, 0, 0)
      ## The buttons' row (panels insert their own choices into it).
      self.row = QtWidgets.QHBoxLayout()
      for w in (self.render_button, self.play_button, self.stop_button, self.open_button, self.save_button):
         self.row.addWidget(w)
      ## The length, mono and HQ choices.
      self.choices = QtWidgets.QWidget()
      choices = QtWidgets.QHBoxLayout(self.choices)
      choices.setContentsMargins(0, 0, 0, 0)
      for w in (QtWidgets.QLabel("Length"), self.seconds, self.mono, self.hq):
         choices.addWidget(w)
      self.row.addWidget(self.choices)
      self.row.addStretch(1)
      column.addLayout(self.row)
      column.addWidget(self.status)
      ## Playhead timer.
      self._timer = QtCore.QTimer(self)
      self._timer.setInterval(PLAYHEAD_MS)
      self._timer.timeout.connect(lambda: self._advance())
      ## Progress timer.
      self._progress_timer = QtCore.QTimer(self)
      self._progress_timer.setInterval(PROGRESS_MS)
      self._progress_timer.timeout.connect(lambda: self._show_progress())
      why = can_play()[1]   # an empty text when it can play
      self.play_button.setToolTip(f"Plays the WAV in the system player and runs the playhead: {why}" if why else
                                  "Play the WAV")
      self._update()

   def options(self) -> ar.RenderOptions:
      """!The chosen render options.
      @return RenderOptions
      """
      return ar.RenderOptions(seconds=self.seconds.value(), mono=self.mono.isChecked(), hq=self.hq.isChecked())

   def progress(self, phase: str, text: str) -> None:
      """!Progress from the worker thread (kept for the GUI thread's timer).
      @param phase  bench phase
      @param text   message
      @return None
      """
      self._progress = text if phase != bench.PHASE_LOG else self._progress

   def start(self, work: Callable[[], ar.RenderResult], label: str) -> None:
      """!Runs a render on a worker thread.
      @param work   callable() -> RenderResult (no Qt, no Document)
      @param label  what renders
      @return None
      """
      self.stop()
      missing = ar.toolchain()
      if missing:
         self.status.setText("Cannot build the renderer: " + "; ".join(missing))
         return

      def run() -> Any:
         """!The job.
         @return RenderResult or the exception
         """
         try:
            return work()
         except (audio.AudioError, bench.BenchError, OSError) as e:
            return e

      self.render_button.setEnabled(False)
      self.status.setText(f"Rendering {label}...")
      self._progress = ""
      self._progress_timer.start()
      background.start(self, "render", run, lambda result: self._done(result))

   def set_result(self, result: ar.RenderResult) -> None:
      """!Shows a result made elsewhere (a WAV written by the panel) so Play / Open / Save act on it.
      @param result  RenderResult
      @return None
      """
      self.result = result
      self._update()

   def busy(self) -> bool:
      """!Whether a render runs.
      @return True while one does
      """
      return background.running(self, "render")

   def wait(self, seconds: float) -> bool:
      """!Waits for the running render (tests and scripts), handling events.
      @param seconds  at most
      @return True when it finished
      """
      end = time.monotonic() + seconds
      app = QtWidgets.QApplication.instance()
      while time.monotonic() < end:
         app.processEvents()
         if not self.busy() and not self._progress_timer.isActive():
            return True
         time.sleep(PLAYHEAD_MS / MS_PER_SECOND)
      return False

   def _done(self, result: Any) -> None:
      """!The render finished.
      @param result  RenderResult or an exception
      @return None
      """
      self._progress_timer.stop()
      self.render_button.setEnabled(True)
      if isinstance(result, Exception):
         self.status.setText(f"Render failed: {result}"[:PROGRESS_CHARS * HALF])
         self.status.setToolTip(str(result))
         self._update()
         return
      self.result = result
      self.status.setText(" ".join(result.lines()[:1]))
      self.status.setToolTip("\n".join(result.lines()) + f"\n{result.wav_path}")
      self._update()
      self._rendered(result)

   def _show_progress(self) -> None:
      """!Shows the worker's latest progress line.
      @return None
      """
      if self._progress:
         self.status.setText(self._progress[:PROGRESS_CHARS])

   def _update(self) -> None:
      """!Enables the buttons.
      @return None
      """
      have = self.result is not None and self.result.wav_path.is_file()
      for b in (self.play_button, self.open_button, self.save_button):
         b.setEnabled(have)
      self.stop_button.setEnabled(have)

   def play(self) -> None:
      """!Plays the latest render (or runs the silent playhead).
      @return None
      """
      if self.result is None:
         return
      try:
         length = self.result.wave().seconds
      except ar.AudioRenderError as e:
         self.status.setText(str(e))
         return
      self.player.play(self.result.wav_path, length)
      if not self.player.audible:
         # No sound here: the system's player plays the WAV while the playhead runs.
         opened = open_externally(self.result.wav_path)
         self.status.setText(("Playing in the system's player; " if opened else "Playhead without sound; ") +
                             can_play()[1])
      self._timer.start()

   def stop(self) -> None:
      """!Stops playing.
      @return None
      """
      self.player.stop()
      self._timer.stop()

   def _play_failed(self, why: str) -> None:
      """!Qt Multimedia failed while playing (C14b): the system's player takes the WAV, the playhead runs on.
      @param why  the media player's error
      @return None
      """
      opened = self.result is not None and open_externally(self.result.wav_path)
      self.status.setText(("Playing in the system's player; " if opened else "Playhead without sound; ") + why)

   def _advance(self) -> None:
      """!Moves the playhead.
      @return None
      """
      if not self.player.playing():
         self._timer.stop()
      if self._tick is not None:
         self._tick(self.player.position() if self.player.playing() else -1.0)

   def open_wav(self) -> None:
      """!Hands the WAV to the system's player.
      @return None
      """
      if self.result is not None and not open_externally(self.result.wav_path):
         self.status.setText(f"WAV: {self.result.wav_path}")

   def save_wav(self, path: str | None = None) -> Path | None:
      """!Copies the WAV somewhere.
      @param path  the file, or None to ask
      @return the copy, or None
      """
      if self.result is None:
         return None
      if path is None:
         path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save WAV", "render.wav", "WAV (*.wav)")
         if not path:
            return None
      shutil.copy2(self.result.wav_path, path)
      self.status.setText(f"Saved {Path(path).name}")
      return Path(path)


# -- drawings -------------------------------------------------------------------------------------------------------

class PianoRoll(QtWidgets.QWidget):
   """!A song's notes: one row per key, a colour per track, the loop and the playhead; a click picks a tick.

   @var view
   The SongView drawn, or None.
   """

   def __init__(self, picked: Callable[[int], None] | None = None, parent: QtWidgets.QWidget | None = None) -> None:
      """!An empty roll.
      @param picked  callable(tick) on a click, or None
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The SongView drawn, or None.
      self.view = None
      ## Tracks drawn faded (muted in the preview).
      self.muted = set()
      ## Tracks hidden.
      self.hidden = set()
      ## The playhead tick, or -1.
      self.playhead = -1
      ## Horizontal zoom.
      self.zoom = 1.0
      ## The click callback.
      self._picked = picked
      ## Lowest and highest key drawn.
      self._keys = (audio.BASE_KEY - ROLL_MIN_KEYS // HALF, audio.BASE_KEY + ROLL_MIN_KEYS // HALF)
      self.setMinimumHeight(ROLL_MIN_KEYS * ROLL_KEY_PIXELS)

   def set_view(self, view: SongView | None) -> None:
      """!Shows a song.
      @param view  SongView, or None
      @return None
      """
      self.view = view
      keys = [n.played for v in (view.views if view else []) for n in v.notes]
      if keys:
         lo, hi = min(keys), max(keys)
         pad = max(0, ROLL_MIN_KEYS - (hi - lo)) // HALF
         self._keys = (max(0, lo - pad - 1), min(audio.MAX_KEY, hi + pad + 1))
      self._resize()
      self.update()

   def set_zoom(self, zoom: float) -> None:
      """!Horizontal zoom.
      @param zoom  factor
      @return None
      """
      self.zoom = zoom
      self._resize()
      self.update()

   def fit(self, width: int) -> None:
      """!Zooms so the song fills a width (a short song is drawn larger; a long one is drawn down to the slider's
      smallest zoom).
      @param width  pixels
      @return None
      """
      if self.view is None:
         return
      span = (self.view.length + BEAT_TICKS) * ROLL_TICK_PIXELS
      low, high = zoom_of(ZOOM_RANGE[0]), zoom_of(ZOOM_RANGE[1])
      self.set_zoom(min(max((width - ROLL_MARGIN) / max(span, 1.0), low), high))

   def tick_x(self, tick: float) -> float:
      """!A tick's x.
      @param tick  the tick
      @return pixels
      """
      return ROLL_MARGIN + tick * ROLL_TICK_PIXELS * self.zoom

   def key_y(self, key: int) -> int:
      """!A key's row top.
      @param key  the key
      @return pixels
      """
      return (self._keys[1] - key) * ROLL_KEY_PIXELS

   def _resize(self) -> None:
      """!Size for the song at the zoom.
      @return None
      """
      length = self.view.length if self.view is not None else 0
      w = int(self.tick_x(length + BEAT_TICKS)) + 1
      h = (self._keys[1] - self._keys[0] + 1) * ROLL_KEY_PIXELS
      self.setMinimumSize(w, h)
      self.resize(max(w, self.width()), h)

   def notes(self) -> list[Note]:
      """!The notes drawn.
      @return notes of the visible tracks
      """
      if self.view is None:
         return []
      return [n for v in self.view.views if v.index not in self.hidden for n in v.notes]

   def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
      """!Draws the roll.
      @param _event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.fillRect(self.rect(), colour(BACKGROUND))
      lo, hi = self._keys
      p.setPen(colour(GRID))
      for key in range(lo, hi + 1):
         y = self.key_y(key)
         if key % audio.OCTAVE == 0:
            p.drawLine(ROLL_MARGIN, y + ROLL_KEY_PIXELS, self.width(), y + ROLL_KEY_PIXELS)
            p.setPen(colour(TEXT))
            p.drawText(LABEL_INSET, y + ROLL_KEY_PIXELS, audio.key_name(key))
            p.setPen(colour(GRID))
      if self.view is not None:
         for t in range(0, self.view.length + 1, BEAT_TICKS):
            x = int(self.tick_x(t))
            p.setPen(colour(TEXT if t % (BEAT_TICKS * BAR_BEATS) == 0 else GRID))
            p.drawLine(x, 0, x, self.height())
         for n in self.notes():
            alpha = MUTED_ALPHA if n.track in self.muted else OPAQUE
            x0, x1 = self.tick_x(n.tick), self.tick_x(n.tick + max(n.length, 1))
            r = QtCore.QRectF(x0, self.key_y(n.played) + 1, max(x1 - x0 - 1, 1), ROLL_KEY_PIXELS - 1)
            p.fillRect(r, track_colour(n.track, alpha))
         for v in self.view.views:
            if v.loop_tick is not None and v.index not in self.hidden:
               x = int(self.tick_x(v.loop_tick))
               p.setPen(QtGui.QPen(colour(LOOP_COLOUR), 1, QtCore.Qt.PenStyle.DashLine))
               p.drawLine(x, 0, x, self.height())
      if self.playhead >= 0:
         x = int(self.tick_x(self.playhead))
         p.setPen(QtGui.QPen(colour(PLAYHEAD), HALF))
         p.drawLine(x, 0, x, self.height())
      p.end()

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!A click picks a tick.
      @param event  QMouseEvent
      @return None
      """
      tick = int((event.position().x() - ROLL_MARGIN) / (ROLL_TICK_PIXELS * self.zoom))
      if self._picked is not None and tick >= 0:
         self._picked(tick)


class ChannelLanes(QtWidgets.QWidget):
   """!The player state over time: one lane per channel, coloured by the track that holds it (the previewed
   song's player's tracks in their colours, other players grey), the envelope as the bar's height; a click picks a
   frame.

   @var timeline
   The StateTimeline drawn, or None.
   """

   def __init__(self, picked: Callable[[int], None] | None = None, parent: QtWidgets.QWidget | None = None) -> None:
      """!Empty lanes.
      @param picked  callable(frame index) on a click, or None
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The StateTimeline drawn, or None.
      self.timeline = None
      ## The player whose tracks get their colours.
      self.player = 0
      ## The frame index marked, or -1.
      self.marked = -1
      ## Horizontal zoom.
      self.zoom = 1.0
      ## The click callback.
      self._picked = picked

   def set_timeline(self, timeline: ar.StateTimeline | None, player: int) -> None:
      """!Shows a render's state.
      @param timeline  StateTimeline, or None
      @param player    the previewed song's player index
      @return None
      """
      self.timeline = timeline
      self.player = player
      self._resize()
      self.update()

   def set_zoom(self, zoom: float) -> None:
      """!Horizontal zoom.
      @param zoom  factor
      @return None
      """
      self.zoom = zoom
      self._resize()
      self.update()

   def _resize(self) -> None:
      """!Size for the frames at the zoom.
      @return None
      """
      tl = self.timeline
      frames = len(tl.frames) if tl is not None else 0
      chans = tl.channel_count() if tl is not None else 0
      self.setMinimumSize(int(LANE_LABEL + frames * LANE_FRAME_PIXELS * self.zoom) + 1, max(chans, 1) * LANE_HEIGHT)

   def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
      """!Draws the lanes.
      @param _event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.fillRect(self.rect(), colour(BACKGROUND))
      tl = self.timeline
      if tl is None or not tl.frames:
         p.setPen(colour(TEXT))
         p.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "Render to see the player state over time")
         p.end()
         return
      step = LANE_FRAME_PIXELS * self.zoom
      for ci in range(tl.channel_count()):
         y = ci * LANE_HEIGHT
         p.setPen(colour(TEXT))
         p.drawText(LABEL_INSET, y + LANE_HEIGHT - HALF * HALF, f"ch {tl.frames[0].channels[ci].index}")
         p.setPen(colour(GRID))
         p.drawLine(LANE_LABEL, y + LANE_HEIGHT - 1, self.width(), y + LANE_HEIGHT - 1)
         for f in range(len(tl.frames)):
            c = tl.sounding(f, ci)
            if c is None:
               continue
            pi, t = tl.owners.get(c.track, (-1, -1))
            full = audio.TONE_GOAL if c.index >= ar.TONE_CHANNEL_FIRST else audio.ENVELOPE_FULL
            hgt = max(1, (LANE_HEIGHT - HALF) * min(c.env, full) // full)
            col = track_colour(t) if pi == self.player else colour(OTHER_COLOUR)
            p.fillRect(QtCore.QRectF(LANE_LABEL + f * step, y + LANE_HEIGHT - 1 - hgt, max(step, 1.0), hgt), col)
      if self.marked >= 0:
         x = LANE_LABEL + self.marked * step
         p.setPen(QtGui.QPen(colour(PLAYHEAD), HALF))
         p.drawLine(int(x), 0, int(x), self.height())
      p.end()

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!A click picks a frame.
      @param event  QMouseEvent
      @return None
      """
      if self.timeline is None:
         return
      f = int((event.position().x() - LANE_LABEL) / (LANE_FRAME_PIXELS * self.zoom))
      if 0 <= f < len(self.timeline.frames) and self._picked is not None:
         self._picked(f)


class WaveformView(QtWidgets.QWidget):
   """!Levels (-128..127, or 16-bit samples) as a waveform with optional loop and end markers and a playhead."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!An empty view.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The levels.
      self.levels = []
      ## The largest level magnitude (127 for 8-bit, 32767 for 16-bit).
      self.peak = LEVEL_MAX
      ## Loop start (sample), or None.
      self.loop = None
      ## The end (sample), or None.
      self.end = None
      ## Playhead as a fraction 0-1, or -1.
      self.playhead = -1.0
      ## Text shown when empty.
      self.empty_text = "No sample"
      self.setMinimumHeight(WAVE_HEIGHT)

   def set_levels(self, levels: Sequence[int], peak: int = LEVEL_MAX, loop: int | None = None,
                  end: int | None = None) -> None:
      """!Shows levels.
      @param levels  the values
      @param peak    their largest magnitude
      @param loop    the loop start, or None
      @param end     the end marker, or None
      @return None
      """
      self.levels, self.peak, self.loop, self.end = list(levels), max(peak, 1), loop, end
      self.update()

   def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
      """!Draws the waveform.
      @param _event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.fillRect(self.rect(), colour(BACKGROUND))
      w, h = self.width(), self.height()
      mid = h // HALF
      p.setPen(colour(GRID))
      p.drawLine(0, mid, w, mid)
      n = len(self.levels)
      if n == 0:
         p.setPen(colour(TEXT))
         p.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, self.empty_text)
         p.end()
         return
      p.setPen(track_colour(0))
      for x in range(w):
         part = self.levels[x * n // w:max((x + 1) * n // w, x * n // w + 1)]
         if part:
            y0 = mid - max(part) * (mid - 1) // self.peak
            y1 = mid - min(part) * (mid - 1) // self.peak
            p.drawLine(x, y0, x, y1)
      for at, col in ((self.loop, LOOP_COLOUR), (self.end, TEXT)):
         if at is not None:
            x = at * w // n
            p.setPen(QtGui.QPen(colour(col), 1, QtCore.Qt.PenStyle.DashLine))
            p.drawLine(x, 0, x, h)
      if self.playhead >= 0:
         p.setPen(QtGui.QPen(colour(PLAYHEAD), HALF))
         x = int(self.playhead * w)
         p.drawLine(x, 0, x, h)
      p.end()


class EnvelopeView(QtWidgets.QWidget):
   """!An envelope curve: level per frame, the note's end marked."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!An empty view.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## Levels per frame.
      self.levels = []
      ## The full level.
      self.full = audio.ENVELOPE_FULL
      ## The frame the note ends (release starts).
      self.held = 0
      ## Text when there is no curve.
      self.empty_text = "No envelope"
      self.setMinimumHeight(ENVELOPE_HEIGHT)

   def set_curve(self, levels: Sequence[int], full: int, held: int) -> None:
      """!Shows a curve.
      @param levels  level per frame
      @param full    the full level
      @param held    frames the note is held
      @return None
      """
      self.levels, self.full, self.held = list(levels), max(full, 1), held
      self.update()

   def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
      """!Draws the curve.
      @param _event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.fillRect(self.rect(), colour(BACKGROUND))
      w, h = self.width(), self.height()
      n = len(self.levels)
      if n == 0:
         p.setPen(colour(TEXT))
         p.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, self.empty_text)
         p.end()
         return
      span = max(n, self.held + 1)
      x_held = self.held * (w - 1) // span
      p.setPen(QtGui.QPen(colour(LOOP_COLOUR), 1, QtCore.Qt.PenStyle.DashLine))
      p.drawLine(x_held, 0, x_held, h)
      path = QtGui.QPainterPath()
      for f, v in enumerate(self.levels):
         pt = QtCore.QPointF(f * (w - 1) / span, (h - HALF) - v * (h - HALF * HALF) / self.full)
         if f == 0:
            path.moveTo(pt)
         else:
            path.lineTo(pt)
      p.setPen(QtGui.QPen(track_colour(0), HALF))
      p.drawPath(path)
      p.setPen(colour(TEXT))
      p.drawText(HALF * HALF, h // HALF * HALF - HALF * HALF,
                 f"{n} frames, note held {self.held}, full {self.full}")
      p.end()


class KeyStrip(QtWidgets.QWidget):
   """!128 keys, each coloured by a value (a keymap entry, a drum voice's presence); click picks a key,
   shift-click extends the selection to a range."""

   def __init__(self, picked: Callable[[int, int], None] | None = None,
                parent: QtWidgets.QWidget | None = None) -> None:
      """!A strip.
      @param picked  callable(first, last) when the selection changes, or None
      @param parent  parent widget
      """
      super().__init__(parent)
      ## Per key: its value (a colour index), or None for none.
      self.values = [None] * audio.KEYS
      ## The selected range (first, last), or None.
      self.selection = None
      ## The callback.
      self._picked = picked
      self.setMinimumSize(KEY_WIDTH * audio.KEYS + 1, KEY_HEIGHT)
      self.setMaximumHeight(KEY_HEIGHT * HALF)

   def set_values(self, values: Sequence[int | None]) -> None:
      """!Colours the keys.
      @param values  per key a value or None
      @return None
      """
      self.values = list(values)
      self.update()

   def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
      """!Draws the keys.
      @param _event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.fillRect(self.rect(), colour(BACKGROUND))
      h = self.height()
      for k in range(audio.KEYS):
         x = k * KEY_WIDTH
         v = self.values[k] if k < len(self.values) else None
         base = colour(GRID) if v is None else track_colour(v)
         if k % audio.OCTAVE in BLACK_KEYS:
            base = base.darker()
         p.fillRect(x, 0, KEY_WIDTH - 1, h, base)
         if self.selection is not None and self.selection[0] <= k <= self.selection[1]:
            p.setPen(QtGui.QPen(colour(PLAYHEAD), HALF))
            p.drawRect(x, 1, KEY_WIDTH - HALF, h - HALF)
         if k % audio.OCTAVE == 0:
            p.fillRect(x, h - KEY_LABEL, KEY_WIDTH * HALF, KEY_LABEL, colour(BACKGROUND))
            p.setPen(colour(TEXT))
            p.drawText(x + 1, h - HALF, str(k // audio.OCTAVE - 1))
      p.end()

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Click: pick a key; shift-click: a range from the selection's first key.
      @param event  QMouseEvent
      @return None
      """
      k = int(event.position().x()) // KEY_WIDTH
      if not 0 <= k < audio.KEYS:
         return
      if event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier and self.selection is not None:
         a = self.selection[0]
         self.selection = (min(a, k), max(a, k))
      else:
         self.selection = (k, k)
      self.update()
      if self._picked is not None:
         self._picked(*self.selection)


class BankView(QtWidgets.QWidget):
   """!The voice banks with the windows sets read from them (overlaps show as bars over the same voices)."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!An empty view.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## core.audio.BankWindows per bank.
      self.banks = []
      ## The set to highlight, or None.
      self.current = None

   def set_banks(self, banks: Sequence[audio.BankWindows], current: str | None) -> None:
      """!Shows banks.
      @param banks    BankWindows
      @param current  the set to highlight
      @return None
      """
      self.banks, self.current = list(banks), current
      rows = sum(len(b.windows) + 1 for b in self.banks)
      self.setMinimumHeight(max(rows, 1) * BANK_ROW + BANK_ROW)
      self.update()

   def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
      """!Draws the banks.
      @param _event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.fillRect(self.rect(), colour(BACKGROUND))
      label = self.width() // (HALF * HALF)
      y = 0
      for b in self.banks:
         span = max([b.length] + [o + n for _k, o, n in b.windows] + [1])
         scale = min(BANK_VOICE_PIXELS, (self.width() - label - HALF) / span)
         p.setPen(colour(TEXT))
         p.drawText(LABEL_INSET, y + BANK_ROW - HALF * HALF, f"{b.key} ({b.length})")
         p.fillRect(QtCore.QRectF(label, y + HALF, b.length * scale, BANK_ROW - HALF * HALF), colour(GRID))
         y += BANK_ROW
         for i, (key, first, count) in enumerate(b.windows):
            p.setPen(colour(TEXT))
            p.drawText(LABEL_INSET, y + BANK_ROW - HALF * HALF, key)
            col = track_colour(i, OPAQUE if key == self.current else MUTED_ALPHA * HALF)
            p.fillRect(QtCore.QRectF(label + first * scale, y + HALF, count * scale, BANK_ROW - HALF * HALF), col)
            y += BANK_ROW
      p.end()


def grid_rows(rows: Sequence[Sequence[Any]]) -> QtWidgets.QGridLayout:
   """!A grid laid out row by row: each entry a widget, or (widget, columns it spans).
   @param rows  the rows
   @return QGridLayout
   """
   grid = QtWidgets.QGridLayout()
   for r, row in enumerate(rows):
      col = 0
      for entry in row:
         try:
            w, span = entry   # (widget, columns)
         except TypeError:   # a widget alone
            w, span = entry, 1
         grid.addWidget(w, r, col, 1, span)
         col += span
   return grid


def fit_table(table: QtWidgets.QTableWidget, stretch: int = -1) -> None:
   """!Columns sized to their contents, one of them taking the rest of the width.
   @param table    the table
   @param stretch  the column that stretches (-1: the last)
   @return None
   """
   header = table.horizontalHeader()
   last = table.columnCount() - 1
   column = last if stretch < 0 else stretch
   for c in range(table.columnCount()):
      mode = QtWidgets.QHeaderView.ResizeMode.Stretch if c == column else \
         QtWidgets.QHeaderView.ResizeMode.ResizeToContents
      header.setSectionResizeMode(c, mode)


def scroll(widget: QtWidgets.QWidget, resizable: bool = False) -> QtWidgets.QScrollArea:
   """!A widget in a scroll area.
   @param widget     the widget
   @param resizable  whether it follows the area's size
   @return QScrollArea
   """
   area = QtWidgets.QScrollArea()
   area.setWidget(widget)
   area.setWidgetResizable(resizable)
   return area


def problem_text(e: Exception) -> str:
   """!An exception as a message.
   @param e  the exception
   @return text
   """
   return str(e) or type(e).__name__
