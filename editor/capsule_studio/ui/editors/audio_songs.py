"""![S7] The song player and viewer (engine M4, D-34): a song's tracks with mute and solo for previews, its notes on
a timeline (a piano roll with the playhead), the commands each track runs (the .cseq text form, or one track's
commands with their ticks), the tempo map, and its header (instrument set, priority, reverb) edited with checks.

Render plays the song through the engine's audio_render on the chosen player, from the editor's current data
(unsaved edits included; muted tracks silenced, core.audio_song.mute()); the WAV plays through Qt's audio output
when there is one (else the playhead runs silently and the WAV opens in the system's player). Player state
shows the core's state over the render, frame by frame: which track holds each channel and its envelope; a
click on a frame lists that frame's channels.
"""
from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

from ...core import audio, audio_render as ar, audio_song
from ..panel import EditorPanel, PanelHost
from ..panes import split_box, splitter
from ..widgets import button
from .audio_common import (WIDE_STRETCH, ChannelLanes, PianoRoll, RenderBar, WaveformView, document_of, fit_table,
                           problem_text, scroll, track_colour, zoom_slider)

## Track table columns.
TRACK_COLUMNS = ("Track", "Notes", "Programs", "End", "Mute", "Solo")
## Column indices of the end, mute and solo columns.
TRACK_END_COLUMN, MUTE_COLUMN, SOLO_COLUMN = 3, 4, 5
## Starting height of the track table's pane, pixels (the user drags its boundary).
TRACKS_HEIGHT = 170
## Channel table columns (Player state).
CHANNEL_COLUMNS = ("Channel", "Player", "Track", "Key", "Velocity", "Priority", "Envelope", "Status")
## Tempo table columns.
TEMPO_COLUMNS = ("Tick", "Frame", "Seconds", "Track", "TEMPO")
## The commands view's first choice: the whole text form.
ALL_TRACKS = "All tracks (text form)"
## Reverb spin value meaning "leave the mixer's reverb as it is" (null).
REVERB_LEAVE = -1
## Layout stretch of the song list and the song.
LIST_STRETCH, SONG_STRETCH = 1, 4
## Starting width of the song list, pixels.
LIST_WIDTH = 230
## Waveform buckets per pixel column (the WAV's peaks).
WAVE_BUCKETS = 1200
## Peak of 16-bit samples.
S16_PEAK = 32767


class SongPanel(EditorPanel):
   """!Songs: the player and viewer."""

   ## Identifier.
   panel_id = "audio_songs"
   ## Tab title.
   title = "Songs"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel.
      @param host    PanelHost (AudioWindow)
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The SongView shown, or None.
      self.view = None
      ## (song key, document revision) the view was made for.
      self._made_for = None
      ## Tracks muted / solo in the preview.
      self.muted = set()
      ## Solo tracks.
      self.solo = set()
      ## Whether the widgets are being filled (no edits).
      self._filling = False
      ## Filter of the song list.
      self.filter = QtWidgets.QLineEdit()
      self.filter.setPlaceholderText("Filter songs")
      self.filter.textChanged.connect(lambda _t: self._fill_list())
      ## The song list.
      self.songs = QtWidgets.QListWidget()
      self.songs.currentItemChanged.connect(lambda _a, _b: self._song_changed())
      left = QtWidgets.QWidget()
      lv = QtWidgets.QVBoxLayout(left)
      lv.setContentsMargins(0, 0, 0, 0)
      lv.addWidget(self.filter)
      lv.addWidget(self.songs, 1)
      lv.addWidget(button("Export text form...", lambda: self.export_song(), "Write the song's .cseq text form"))

      # header
      ## The song's instrument set.
      self.instruments = QtWidgets.QComboBox()
      self.instruments.activated.connect(lambda _i: self._set_field("instruments", self.instruments.currentText()))
      ## Priority.
      self.priority = QtWidgets.QSpinBox()
      self.priority.setRange(0, audio.MAX_PRIORITY)
      self.priority.editingFinished.connect(lambda: self._set_field("priority", self.priority.value()))
      ## Reverb (REVERB_LEAVE: null).
      self.reverb = QtWidgets.QSpinBox()
      self.reverb.setRange(REVERB_LEAVE, audio.MAX_REVERB)
      self.reverb.setSpecialValueText("leave as it is")
      self.reverb.editingFinished.connect(lambda: self._set_field(
         "reverb", None if self.reverb.value() == REVERB_LEAVE else self.reverb.value()))
      ## The player the preview plays on.
      self.player = QtWidgets.QComboBox()
      self.player.setToolTip("The player the preview plays the song on (its track count and order)")
      ## Song facts.
      self.info = QtWidgets.QLabel()
      self.info.setWordWrap(True)
      head = QtWidgets.QHBoxLayout()
      for label, w in (("Instruments", self.instruments), ("Priority", self.priority), ("Reverb", self.reverb),
                       ("Play on", self.player)):
         head.addWidget(QtWidgets.QLabel(label))
         head.addWidget(w)
      head.addStretch(1)

      ## The tracks.
      self.tracks = QtWidgets.QTableWidget(0, len(TRACK_COLUMNS))
      self.tracks.setHorizontalHeaderLabels(TRACK_COLUMNS)
      self.tracks.horizontalHeader().setStretchLastSection(False)
      self.tracks.verticalHeader().setVisible(False)
      self.tracks.itemChanged.connect(lambda item: self._track_item_changed(item))
      fit_table(self.tracks, TRACK_END_COLUMN)

      ## The render bar.
      self.bar = RenderBar(lambda: self.render(), self._rendered, tick=self._tick)

      ## The piano roll.
      self.roll = PianoRoll(lambda tick: self._pick_tick(tick))
      timeline = QtWidgets.QWidget()
      tv = QtWidgets.QVBoxLayout(timeline)
      tv.setContentsMargins(0, 0, 0, 0)
      tv.addWidget(zoom_slider(self.roll.set_zoom))
      ## The roll's scroll area.
      self.roll_area = scroll(self.roll)
      tv.addWidget(self.roll_area, 1)

      ## Which commands the commands view shows.
      self.command_track = QtWidgets.QComboBox()
      self.command_track.activated.connect(lambda _i: self._show_commands())
      ## The commands.
      self.commands = QtWidgets.QPlainTextEdit()
      self.commands.setReadOnly(True)
      self.commands.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
      commands = QtWidgets.QWidget()
      cv = QtWidgets.QVBoxLayout(commands)
      cv.setContentsMargins(0, 0, 0, 0)
      cv.addWidget(self.command_track)
      cv.addWidget(self.commands, 1)

      ## The tempo map.
      self.tempo = QtWidgets.QTableWidget(0, len(TEMPO_COLUMNS))
      self.tempo.setHorizontalHeaderLabels(TEMPO_COLUMNS)
      self.tempo.verticalHeader().setVisible(False)
      self.tempo.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      fit_table(self.tempo)

      ## The player state lanes.
      self.lanes = ChannelLanes(lambda f: self.show_frame(f))
      ## The frame's channels.
      self.channels = QtWidgets.QTableWidget(0, len(CHANNEL_COLUMNS))
      self.channels.setHorizontalHeaderLabels(CHANNEL_COLUMNS)
      self.channels.verticalHeader().setVisible(False)
      self.channels.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      fit_table(self.channels)
      ## The frame shown.
      self.frame_label = QtWidgets.QLabel("Click a frame")
      state = QtWidgets.QWidget()
      sv = QtWidgets.QVBoxLayout(state)
      sv.setContentsMargins(0, 0, 0, 0)
      sv.addWidget(zoom_slider(self.lanes.set_zoom))
      sv.addWidget(scroll(self.lanes), WIDE_STRETCH)
      sv.addWidget(self.frame_label)
      sv.addWidget(self.channels, 1)
      split_box(sv)   # [RZ] lanes over channels
      ## The timeline the render's state.jsonl gave, or None.
      self.timeline = None
      ## The latest render's WAV length, seconds.
      self._wav_seconds = 0.0

      ## The rendered output's waveform.
      self.wave = WaveformView()
      self.wave.empty_text = "Render to see the output"

      ## The views.
      self.views = QtWidgets.QTabWidget()
      self.views.addTab(timeline, "Timeline")
      self.views.addTab(commands, "Commands")
      self.views.addTab(self.tempo, "Tempo")
      self.views.addTab(state, "Player state")
      self.views.addTab(self.wave, "Output")

      right = QtWidgets.QWidget()
      rv = QtWidgets.QVBoxLayout(right)
      rv.setContentsMargins(0, 0, 0, 0)
      rv.addLayout(head)
      rv.addWidget(self.info)
      rv.addWidget(self.tracks)
      rv.addWidget(self.bar)
      rv.addWidget(self.views, 1)
      split_box(rv, [TRACKS_HEIGHT, None])   # [RZ] tracks over the song's views
      # [RZ] list | song: the user drags the boundary (the list starts LIST_WIDTH wide)
      split = splitter(QtCore.Qt.Orientation.Horizontal, [left, right], [LIST_STRETCH, SONG_STRETCH],
                       [LIST_WIDTH, None])
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(split)

   # -- panel contract ---------------------------------------------------------------------------------------------

   def commit(self) -> None:
      """!Nothing waits to be written.
      @return None
      """
      pass

   def stop(self) -> None:
      """!Stops playing.
      @return None
      """
      self.bar.stop()

   def document_replaced(self) -> None:
      """!Another manifest: forget the song and the render.
      @return None
      """
      self.view, self._made_for, self.timeline = None, None, None
      self.muted, self.solo = set(), set()
      self.bar.result = None
      self.refresh()

   def refresh(self) -> None:
      """!Re-reads the songs and the selected song.
      @return None
      """
      self._filling = True
      try:
         self._fill_list()
         doc = document_of(self)
         self.instruments.clear()
         self.player.clear()
         if doc is not None:
            self.instruments.addItems(audio.keys(doc, "instruments"))
            self.player.addItems([str(p.get("name")) for p in audio.players(doc)])
      finally:
         self._filling = False
      self._song_changed()

   def _fill_list(self) -> None:
      """!The song list (selection kept).
      @return None
      """
      current = self.current_key()
      self.songs.blockSignals(True)
      self.songs.clear()
      doc = document_of(self)
      text = self.filter.text().strip().lower()
      if doc is not None:
         for key in audio.keys(doc, "song"):
            if text in key.lower():
               self.songs.addItem(key)
      items = self.songs.findItems(current, QtCore.Qt.MatchFlag.MatchExactly) if current else []
      if items:
         self.songs.setCurrentItem(items[0])
      elif self.songs.count():
         self.songs.setCurrentRow(0)
      self.songs.blockSignals(False)

   def current_key(self) -> str | None:
      """!The selected song.
      @return its key, or None
      """
      item = self.songs.currentItem()
      return item.text() if item is not None else None

   def select_song(self, key: str) -> None:
      """!Selects a song.
      @param key  its key
      @return None
      """
      self.filter.clear()
      items = self.songs.findItems(key, QtCore.Qt.MatchFlag.MatchExactly)
      if items:
         self.songs.setCurrentItem(items[0])

   # -- the song -----------------------------------------------------------------------------------------------------

   def _song_changed(self) -> None:
      """!Shows the selected song.
      @return None
      """
      key, doc = self.current_key(), document_of(self)
      if key is None or doc is None:
         me = self   # through another name: Doxygen 1.12 takes members assigned here for undocumented ones
         me.view = None
         self._show_song(None)
         return
      made_for = (key, doc.revision)
      if made_for != self._made_for:
         if self._made_for is None or self._made_for[0] != key:
            self.muted, self.solo = set(), set()
            self.timeline = None
            self.lanes.set_timeline(None, 0)
         me = self   # through another name: Doxygen 1.12 takes members assigned here for undocumented ones
         try:
            me.view = audio_song.song_view(doc, key)
            error = None
         except audio.AudioError as e:
            me.view, error = None, problem_text(e)
         self._made_for = made_for
         self._show_song(error)

   def _show_song(self, error: str | None) -> None:
      """!Fills the header, tracks and views.
      @param error  why the song cannot be shown, or None
      @return None
      """
      self._filling = True
      try:
         key, doc, v = self.current_key(), document_of(self), self.view
         e = audio.entry(doc, key) if key and doc is not None else {}
         self.instruments.setCurrentText(str(e.get("instruments", "")))
         self.priority.setValue(int(e.get("priority", 0)))
         self.reverb.setValue(REVERB_LEAVE if e.get("reverb") is None else int(e["reverb"]))
         if key and doc is not None:
            try:
               self.player.setCurrentText(ar.song_player(doc, key))
            except audio.AudioError:
               pass
         if v is None:
            self.info.setText(error or "No song")
         else:
            end = v.end_frame
            form = next((f for f in audio.DATA_FIELDS if f in e), "?")
            how = (f"ends on frame {end} ({audio_song.seconds(end):.2f} s)" if end is not None else
                   "loops (plays until stopped)")
            self.info.setText(f"{len(v.views)} tracks, {len(v.data)} bytes ({form} form), {v.length} ticks, {how}; "
                              f"{len(v.tempo)} tempo changes")
         self._fill_tracks()
         self.roll.set_view(v)
         self.roll.fit(self.roll_area.viewport().width())
         self._apply_mutes()
         self.command_track.clear()
         self.command_track.addItem(ALL_TRACKS)
         for t in range(len(v.views) if v else 0):
            self.command_track.addItem(f"Track {t} (commands with ticks)")
         self._show_commands()
         self._fill_tempo()
      finally:
         self._filling = False

   def _fill_tracks(self) -> None:
      """!The track table.
      @return None
      """
      v = self.view
      self.tracks.blockSignals(True)
      self.tracks.setRowCount(len(v.views) if v else 0)
      for row, tv in enumerate(v.views if v else []):
         end = tv.error or (f"end {tv.end_tick}" if tv.end_tick is not None else
                            f"loops at {tv.loop_tick}" if tv.loop_tick is not None else "runs on")
         cells = (f"Track {tv.index}", str(len(tv.notes)), ", ".join(map(str, tv.programs)) or "-", end)
         for col, text in enumerate(cells):
            item = QtWidgets.QTableWidgetItem(text)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            if col == 0:
               item.setForeground(track_colour(tv.index))
            self.tracks.setItem(row, col, item)
         for col, chosen in ((MUTE_COLUMN, self.muted), (SOLO_COLUMN, self.solo)):
            item = QtWidgets.QTableWidgetItem()
            item.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(QtCore.Qt.CheckState.Checked if tv.index in chosen else QtCore.Qt.CheckState.Unchecked)
            self.tracks.setItem(row, col, item)
      self.tracks.blockSignals(False)

   def _track_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A mute or solo box changed.
      @param item  the cell
      @return None
      """
      if item.column() not in (MUTE_COLUMN, SOLO_COLUMN):
         return
      chosen = self.muted if item.column() == MUTE_COLUMN else self.solo
      if item.checkState() == QtCore.Qt.CheckState.Checked:
         chosen.add(item.row())
      else:
         chosen.discard(item.row())
      self._apply_mutes()
      if self.bar.result is not None:
         self.host.show_status("Render again to hear the change")

   def set_mute(self, track: int, muted: bool = True) -> None:
      """!Mutes or unmutes a track (the table's box).
      @param track  the track
      @param muted  True to mute
      @return None
      """
      self.tracks.item(track, MUTE_COLUMN).setCheckState(QtCore.Qt.CheckState.Checked if muted else
                                                         QtCore.Qt.CheckState.Unchecked)

   def set_solo(self, track: int, solo: bool = True) -> None:
      """!Solos a track (the table's box).
      @param track  the track
      @param solo   True to solo
      @return None
      """
      self.tracks.item(track, SOLO_COLUMN).setCheckState(QtCore.Qt.CheckState.Checked if solo else
                                                         QtCore.Qt.CheckState.Unchecked)

   def silenced(self) -> set[int]:
      """!The tracks the preview silences (core.audio_song.solo_mutes()).
      @return track numbers
      """
      count = len(self.view.views) if self.view else 0
      return audio_song.solo_mutes(count, self.solo, self.muted)

   def _apply_mutes(self) -> None:
      """!The roll fades the silenced tracks.
      @return None
      """
      self.roll.muted = self.silenced()
      self.roll.update()

   def _show_commands(self) -> None:
      """!The commands view.
      @return None
      """
      v = self.view
      if v is None:
         self.commands.setPlainText("")
         return
      i = self.command_track.currentIndex()
      if i <= 0:
         self.commands.setPlainText(audio_song.disassembly(v.data, v.tracks))
      else:
         self.commands.setPlainText("\n".join(audio_song.listing(v, i - 1)))

   def _fill_tempo(self) -> None:
      """!The tempo table.
      @return None
      """
      v = self.view
      rows = v.tempo if v else []
      self.tempo.setRowCount(len(rows))
      for r, c in enumerate(rows):
         frame = v.frame_of(c.tick)
         for col, text in enumerate((c.tick, frame, f"{audio_song.seconds(frame):.2f}", c.track, c.bpm)):
            self.tempo.setItem(r, col, QtWidgets.QTableWidgetItem(str(text)))

   def _set_field(self, name: str, value: Any) -> None:
      """!A header field edit.
      @param name   the field
      @param value  its value
      @return None
      """
      key = self.current_key()
      if self._filling or key is None or document_of(self) is None:
         return
      if audio.entry(document_of(self), key).get(name) == value:
         return
      self.host.apply(f"{name} of {key}", lambda: audio.set_song_field(document_of(self), key, name, value))

   def export_song(self, path: str | None = None) -> None:
      """!Writes the song's text form.
      @param path  the file, or None to ask
      @return None
      """
      v, key = self.view, self.current_key()
      if v is None or key is None:
         return
      if path is None:
         path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export text form", key.split(":", 1)[1] +
                                                         audio.ASM_SUFFIX, "Song text (*.cseq)")
         if not path:
            return
      with open(path, "w", encoding="utf-8") as f:
         f.write(audio_song.disassembly(v.data, v.tracks))
      self.host.show_status(f"Wrote {path}")

   # -- rendering --------------------------------------------------------------------------------------------------

   def render(self) -> None:
      """!Renders the song on the chosen player with the silenced tracks (the preview table on a worker thread).
      @return None
      """
      key, doc = self.current_key(), document_of(self)
      if key is None or doc is None:
         return
      try:
         r = self.host.renderer()
         sounds = [ar.PreviewSound(key, self.player.currentText() or ar.song_player(doc, key), self.silenced())]
         r.prepare(sounds)
      except audio.AudioError as e:
         self.bar.status.setText(problem_text(e))
         return
      options = self.bar.options()
      self.bar.start(lambda: r.run_preview(sounds, 0, options, self.bar.progress), key)

   def _rendered(self, result: ar.RenderResult) -> None:
      """!A render finished: the output waveform and the player state.
      @param result  RenderResult
      @return None
      """
      try:
         w = result.wave()
         self._wav_seconds = w.seconds
         self.wave.set_levels([hi if abs(hi) >= abs(lo) else lo for lo, hi in w.peaks(WAVE_BUCKETS)], S16_PEAK)
      except ar.AudioRenderError as e:
         self.wave.empty_text = problem_text(e)
         self.wave.set_levels([])
      me = self   # through another name: Doxygen 1.12 takes members assigned here for undocumented ones
      try:
         me.timeline = result.timeline()
      except ar.AudioRenderError:
         me.timeline = None
      names = [str(p.get("name")) for p in audio.players(document_of(self))] if document_of(self) is not None else []
      player = names.index(self.player.currentText()) if self.player.currentText() in names else 0
      self.lanes.set_timeline(self.timeline, player)

   def _tick(self, seconds: float) -> None:
      """!The playhead while playing (-1: stopped).
      @param seconds  time into the WAV
      @return None
      """
      res, v = self.bar.result, self.view
      if seconds < 0 or res is None or v is None:
         self.roll.playhead = -1
         self.wave.playhead = -1.0
      else:
         per = int(res.summary.get("output_samples_per_frame") or res.summary.get("samples_per_frame") or 1)
         rate = int(res.summary.get("rate") or 1)
         frame = int(seconds * rate / per) + 1
         song_frame = frame - (audio_song.FIRST_RENDER_FRAME - 1)
         self.roll.playhead = v.tick_at(song_frame) if song_frame >= 1 else -1
         total = self._wav_seconds
         self.wave.playhead = seconds / total if total else -1.0
         self.lanes.marked = frame - 1
         self.lanes.update()
      self.roll.update()
      self.wave.update()

   def _pick_tick(self, tick: int) -> None:
      """!A click on the roll: show that tick's frame in the player state.
      @param tick  the tick
      @return None
      """
      if self.view is None:
         return
      self.roll.playhead = tick
      self.roll.update()
      if self.timeline is not None:
         frame = self.view.frame_of(tick) + audio_song.FIRST_RENDER_FRAME - 1
         self.show_frame(min(frame - 1, len(self.timeline.frames) - 1))

   def show_frame(self, index: int) -> None:
      """!Lists one frame's channels.
      @param index  index into the timeline's frames
      @return None
      """
      tl = self.timeline
      if tl is None or not 0 <= index < len(tl.frames):
         return
      self.lanes.marked = index
      self.lanes.update()
      fs = tl.frames[index]
      names = [str(p.get("name")) for p in audio.players(document_of(self))] if document_of(self) is not None else []
      rows = [c for c in fs.channels if c.track]
      # C15b: the tracks still running (the engine's kTrackExists) beside the channels that sound
      self.frame_label.setText(f"Frame {fs.frame}: {sum(1 for c in rows if c.status & ar.CHANNEL_ON)} channels "
                               f"sounding, {tl.tracks_running(index)} tracks running")
      self.channels.setRowCount(len(rows))
      for r, c in enumerate(rows):
         p, t = tl.owners.get(c.track, (-1, -1))
         pname = names[p] if 0 <= p < len(names) else ("clip" if p >= 0 else "?")
         status = "on" if c.status & ar.CHANNEL_ON else "idle"
         for col, text in enumerate((c.index, pname, t, audio.key_name(c.key), c.velocity, c.priority, c.env,
                                     f"{status} ({c.status:#04x})")):
            self.channels.setItem(r, col, QtWidgets.QTableWidgetItem(str(text)))
