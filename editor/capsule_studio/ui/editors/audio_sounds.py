"""![S7] The sound effect tester (engine M4, D-34): the song table (each sound number's song, the player it plays on,
its name key, the song's priority and the player's start check), the players (tracks, start check) and the mixer,
edited with checks; a sound number played on its player (the editor's current data, or the whole saved table as the
game's build compiles it); the clips of the saved table played with their parameters; and two sounds started a few
frames apart: which sound and track holds each channel frame by frame, the channels one took from the other, and
whether the second was refused by its player's start check (C14b: in the C++ core through audio_render --then, its
output to listen to; without a toolchain on the engine's reference model of the core, with the sampled channels' mix).
"""
from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import audio, audio_render as ar
from ..panel import EditorPanel, PanelHost
from ..widgets import button
from .audio_common import (BACKGROUND, GRID, HALF, LABEL_INSET, LANE_HEIGHT, LANE_LABEL, TEXT, WIDE_STRETCH, ZOOM_RANGE,
                           RenderBar, colour, document_of, fit_table, problem_text, scroll, track_colour, zoom_of,
                           zoom_slider)

## Song table columns.
SOUND_COLUMNS = ("Sound", "Song", "Player", "Name", "Priority", "Start check")
## The song table's column that stretches.
SONG_COLUMN = 1
## Tab indices of the panel: the song table, two sounds, clips.
TABLE_TAB, PRIORITY_TAB, CLIPS_TAB = 0, 1, 2
## Player table columns.
PLAYER_COLUMNS = ("Player", "Tracks", "Start check", "Sounds")
## The song choice for an empty slot.
EMPTY_SONG = "(none: the empty song)"
## Pixels per frame of the priority chart at zoom 1.
CHART_FRAME_PIXELS = 3.0
## The two sounds' base colours in the chart (track colours 0 and 1 families: first, second).
SOUND_BASES = (0, 1)
## Colour of a stolen channel's mark.
STEAL_COLOUR = (255, 60, 60)
## QColor.darker()'s factor that keeps a colour as it is.
DARKER_SAME = 100
## Shades of a sound's tracks (darker per track).
SHADE_STEP = 18
## Range of the delay and frame spins.
DELAY_RANGE, FRAMES_RANGE = (0, 600), (1, 3600)
## Ranges of the clip parameter spins: volume, pan, pitch, hold, release, chorus, priority.
CLIP_RANGES = {"volume": (0, audio.SIGNED_MAX), "pan": (-64, 63), "pitch": (-32768, 32767), "hold": (0, 65535),
               "release": (0, audio.BYTE_MAX), "chorus": (0, audio.BYTE_MAX), "priority": (0, audio.BYTE_MAX)}
## Choices of the mixer's output.
OUTPUTS = ("stereo", "mono")


class PriorityChart(QtWidgets.QWidget):
   """!Who holds each channel per frame in a two-sound preview: the first sound in one colour, the second in
   another, shaded by track; the second sound's start marked."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!An empty chart.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The core.audio_render.PriorityPreview, or None.
      self.preview = None
      ## Horizontal zoom.
      self.zoom = 1.0

   def set_preview(self, preview: ar.PriorityPreview | None) -> None:
      """!Shows a preview.
      @param preview  PriorityPreview, or None
      @return None
      """
      self.preview = preview
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
      """!Zooms so the frames fill a width.
      @param width  pixels
      @return None
      """
      frames = len(self.preview.owners) if self.preview is not None else 0
      if frames:
         self.set_zoom(max((width - LANE_LABEL) / (frames * CHART_FRAME_PIXELS), zoom_of(ZOOM_RANGE[0])))

   def _resize(self) -> None:
      """!Size for the frames.
      @return None
      """
      p = self.preview
      frames = len(p.owners) if p is not None else 0
      rows = len(p.channels) if p is not None else 1
      self.setMinimumSize(int(LANE_LABEL + frames * CHART_FRAME_PIXELS * self.zoom) + 1, rows * LANE_HEIGHT)

   def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
      """!Draws the chart.
      @param _event  QPaintEvent
      @return None
      """
      painter = QtGui.QPainter(self)
      painter.fillRect(self.rect(), colour(BACKGROUND))
      p = self.preview
      if p is None:
         painter.setPen(colour(TEXT))
         painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "Preview two sounds")
         painter.end()
         return
      step = CHART_FRAME_PIXELS * self.zoom
      for row, ch in enumerate(p.channels):
         y = row * LANE_HEIGHT
         painter.setPen(colour(TEXT))
         painter.drawText(LABEL_INSET, y + LANE_HEIGHT - HALF * HALF, f"ch {ch}")
         painter.setPen(colour(GRID))
         painter.drawLine(LANE_LABEL, y + LANE_HEIGHT - 1, self.width(), y + LANE_HEIGHT - 1)
         for f, owners in enumerate(p.owners):
            o = owners[row]
            if o is None:
               continue
            sound, track = o
            c = track_colour(SOUND_BASES[sound]).darker(DARKER_SAME + SHADE_STEP * track)
            painter.fillRect(QtCore.QRectF(LANE_LABEL + f * step, y + 1, max(step, 1.0), LANE_HEIGHT - HALF), c)
      x = int(LANE_LABEL + p.delay * step)
      painter.setPen(QtGui.QPen(colour(TEXT), HALF, QtCore.Qt.PenStyle.DashLine))
      painter.drawLine(x, 0, x, self.height())
      for s in p.steals:
         painter.setPen(QtGui.QPen(colour(STEAL_COLOUR), HALF))
         row = p.channels.index(s.channel) if s.channel in p.channels else 0
         sx = int(LANE_LABEL + s.frame * step)
         painter.drawRect(sx - HALF, row * LANE_HEIGHT, HALF * HALF, LANE_HEIGHT - 1)
      painter.end()


class SoundPanel(EditorPanel):
   """!Sound effects: song table, players, mixer, play, clips, two sounds at once."""

   ## Identifier.
   panel_id = "audio_sounds"
   ## Tab title.
   title = "Sound effects"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel.
      @param host    PanelHost (AudioWindow)
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Whether the widgets are being filled.
      self._filling = False
      ## The latest two-sound preview, or None.
      self.priority_result = None

      ## The song table.
      self.table = QtWidgets.QTableWidget(0, len(SOUND_COLUMNS))
      self.table.setHorizontalHeaderLabels(SOUND_COLUMNS)
      self.table.verticalHeader().setVisible(False)
      self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.currentCellChanged.connect(lambda _r, _c, _pr, _pc: self._sound_changed())
      self.table.cellDoubleClicked.connect(lambda _r, _c: self.play_sound())
      fit_table(self.table, SONG_COLUMN)
      ## The selected entry's song.
      self.song = QtWidgets.QComboBox()
      ## Its player.
      self.player = QtWidgets.QComboBox()
      ## Its name key.
      self.name = QtWidgets.QLineEdit()
      self.name.setPlaceholderText("optional sound:NAME")
      edit = QtWidgets.QHBoxLayout()
      for label, w in (("Song", self.song), ("Player", self.player), ("Name", self.name)):
         edit.addWidget(QtWidgets.QLabel(label))
         edit.addWidget(w, 1)
      edit.addWidget(button("Apply", lambda: self.apply_sound(), "Write the entry"))
      edit.addWidget(button("Add sound", lambda: self.add_sound(), "Append an entry with this song and player"))
      edit.addWidget(button("Remove last", lambda: self.remove_last()))
      ## Play from the whole saved table.
      self.saved = QtWidgets.QCheckBox("Whole saved table")
      self.saved.setToolTip("Play from the table as saved and as the game's build compiles it (every number), "
                            "instead of the editor's current data")
      ## The render bar.
      self.bar = RenderBar(lambda: self.play_sound(), lambda _r: None)
      self.bar.render_button.setText("Play sound")
      self.bar.row.insertWidget(1, self.saved)
      table_box = QtWidgets.QGroupBox("Song table (double-click a sound to play it on its player)")
      tv = QtWidgets.QVBoxLayout(table_box)
      tv.addWidget(self.table, 1)
      tv.addLayout(edit)
      tv.addWidget(self.bar)

      ## The players.
      self.players = QtWidgets.QTableWidget(0, len(PLAYER_COLUMNS))
      self.players.setHorizontalHeaderLabels(PLAYER_COLUMNS)
      self.players.verticalHeader().setVisible(False)
      self.players.itemChanged.connect(lambda item: self._player_item_changed(item))
      fit_table(self.players, 0)
      ## New player's name.
      self.new_player = QtWidgets.QLineEdit()
      self.new_player.setPlaceholderText("new player")
      ## Mixer rate.
      self.rate = QtWidgets.QComboBox()
      self.rate.addItems([str(r) for r in audio.fmt_rates()])
      self.rate.activated.connect(lambda _i: self._mixer("rate", int(self.rate.currentText())))
      ## Sampled channels.
      self.channels = QtWidgets.QSpinBox()
      self.channels.setRange(*audio.CHANNEL_RANGE)
      self.channels.editingFinished.connect(lambda: self._mixer("channels", self.channels.value()))
      ## Master volume.
      self.master = QtWidgets.QSpinBox()
      self.master.setRange(0, audio.MAX_MASTER_VOLUME)
      self.master.editingFinished.connect(lambda: self._mixer("master_volume", self.master.value()))
      ## Output at start.
      self.output = QtWidgets.QComboBox()
      self.output.addItems(OUTPUTS)
      self.output.activated.connect(lambda _i: self._mixer("output", self.output.currentText()))
      ## Track budget.
      self.tracks_info = QtWidgets.QLabel()
      players_box = QtWidgets.QGroupBox("Players and mixer")
      pv = QtWidgets.QVBoxLayout(players_box)
      pv.addWidget(self.players, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.new_player)
      row.addWidget(button("Add player", lambda: self.add_player()))
      pv.addLayout(row)
      pv.addWidget(self.tracks_info)
      mixer = QtWidgets.QFormLayout()
      mixer.addRow("Rate (Hz)", self.rate)
      mixer.addRow("Sampled channels", self.channels)
      mixer.addRow("Master volume", self.master)
      mixer.addRow("Output at start", self.output)
      pv.addLayout(mixer)

      # clips
      ## The clips.
      self.clips = QtWidgets.QListWidget()
      ## Clip parameters by name.
      self.clip_params = {}
      defaults = ar.ClipOptions()
      clip_form = QtWidgets.QFormLayout()
      for name, rng in CLIP_RANGES.items():
         s = QtWidgets.QSpinBox()
         s.setRange(*rng)
         s.setValue(getattr(defaults, name))
         self.clip_params[name] = s
         clip_form.addRow(name, s)
      ## The clip render bar.
      self.clip_bar = RenderBar(lambda: self.play_clip(), lambda _r: None)
      self.clip_bar.render_button.setText("Play clip")
      clips_box = QtWidgets.QGroupBox("Clips (the saved table)")
      cv = QtWidgets.QHBoxLayout(clips_box)
      cv.addWidget(self.clips, 1)
      cv.addLayout(clip_form)
      clip_column = QtWidgets.QVBoxLayout()
      clip_column.addWidget(clips_box)
      clip_column.addWidget(self.clip_bar)

      # two sounds
      ## The first sound.
      self.first = QtWidgets.QSpinBox()
      ## The second sound.
      self.second = QtWidgets.QSpinBox()
      ## Frames between them.
      self.delay = QtWidgets.QSpinBox()
      self.delay.setRange(*DELAY_RANGE)
      self.delay.setValue(1)
      ## Frames to run.
      self.frames = QtWidgets.QSpinBox()
      self.frames.setRange(*FRAMES_RANGE)
      self.frames.setValue(ar.DEFAULT_PRIORITY_FRAMES)
      ## The outcome.
      self.outcome = QtWidgets.QPlainTextEdit()
      self.outcome.setReadOnly(True)
      ## The chart.
      self.chart = PriorityChart()
      ## The mix's player.
      self.mix_bar = RenderBar(lambda: self.preview_priority(), lambda r: self.show_priority(r.priority))
      self.mix_bar.render_button.setText("Preview")
      self.mix_bar.choices.hide()
      row = QtWidgets.QHBoxLayout()
      for label, w in (("First sound", self.first), ("then", self.second), ("after (frames)", self.delay),
                       ("run (frames)", self.frames)):
         row.addWidget(QtWidgets.QLabel(label))
         row.addWidget(w)
      row.addStretch(1)
      pri_box = QtWidgets.QGroupBox("Priority and channel stealing: two sounds at once (the C++ core; without a "
                                    "toolchain the reference model, its mix the sampled channels only)")
      prv = QtWidgets.QVBoxLayout(pri_box)
      prv.addLayout(row)
      prv.addWidget(self.mix_bar)
      prv.addWidget(zoom_slider(self.chart.set_zoom))
      ## The chart's scroll area.
      self.chart_area = scroll(self.chart)
      prv.addWidget(self.chart_area, WIDE_STRETCH)
      prv.addWidget(self.outcome, 1)

      top = QtWidgets.QSplitter()
      top.addWidget(table_box)
      top.addWidget(players_box)
      top.setStretchFactor(0, HALF)
      top.setStretchFactor(1, 1)
      clip_widget = QtWidgets.QWidget()
      clip_widget.setLayout(clip_column)
      ## The panel's pages.
      self.pages = QtWidgets.QTabWidget()
      self.pages.addTab(top, "Song table and players")
      self.pages.addTab(pri_box, "Two sounds at once")
      self.pages.addTab(clip_widget, "Clips")
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(self.pages)

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
      for b in (self.bar, self.clip_bar, self.mix_bar):
         b.stop()

   def refresh(self) -> None:
      """!Re-reads the table, players, mixer and clips (selection kept).
      @return None
      """
      self._filling = True
      try:
         self._fill_table()
         self._fill_players()
         self._fill_mixer()
         self._fill_clips()
      finally:
         self._filling = False
      self._sound_changed()

   def _fill_table(self) -> None:
      """!The song table.
      @return None
      """
      keep = self.current_number()
      doc = document_of(self)
      rows = audio.sounds(doc) if doc is not None else []
      self.table.blockSignals(True)
      self.table.setRowCount(len(rows))
      for r in rows:
         for c, text in enumerate((r.number, r.song or "(none)", r.player, r.name or "", r.priority,
                                   "yes" if r.start_check else "no")):
            self.table.setItem(r.number, c, QtWidgets.QTableWidgetItem(str(text)))
      if rows:
         self.table.setCurrentCell(keep if 0 <= keep < len(rows) else 0, 0)
      self.table.blockSignals(False)
      last = max(len(rows) - 1, 0)
      for s in (self.first, self.second):
         s.setRange(0, last)
      self.song.clear()
      self.song.addItem(EMPTY_SONG)
      self.player.clear()
      if doc is not None:
         self.song.addItems(audio.keys(doc, "song"))
         self.player.addItems([str(p.get("name")) for p in audio.players(doc)])

   def _fill_players(self) -> None:
      """!The players table.
      @return None
      """
      doc = document_of(self)
      ps = audio.players(doc) if doc is not None else []
      rows = audio.sounds(doc) if doc is not None else []
      self.players.blockSignals(True)
      self.players.setRowCount(len(ps))
      for i, p in enumerate(ps):
         name = QtWidgets.QTableWidgetItem(str(p.get("name")))
         tracks = QtWidgets.QTableWidgetItem(str(p.get("tracks")))
         check = QtWidgets.QTableWidgetItem()
         check.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
         check.setCheckState(QtCore.Qt.CheckState.Checked if p.get("start_check") else QtCore.Qt.CheckState.Unchecked)
         count = QtWidgets.QTableWidgetItem(str(sum(1 for r in rows if r.player_index == i)))
         count.setFlags(count.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
         for c, item in enumerate((name, tracks, check, count)):
            self.players.setItem(i, c, item)
      self.players.blockSignals(False)
      total = audio.track_total(doc) if doc is not None else 0
      self.tracks_info.setText(f"{total} tracks of {audio.MAX_ALL_TRACKS} with the clip players' {audio.CLIP_TRACKS}; "
                               "players run in this order")

   def _fill_mixer(self) -> None:
      """!The mixer settings.
      @return None
      """
      m = (document_of(self).data.get("mixer", {}) if document_of(self) is not None else {})
      self.rate.setCurrentText(str(m.get("rate", audio.DEFAULT_MIXER["rate"])))
      self.channels.setValue(int(m.get("channels", audio.DEFAULT_MIXER["channels"])))
      self.master.setValue(int(m.get("master_volume", audio.DEFAULT_MIXER["master_volume"])))
      self.output.setCurrentText(str(m.get("output", audio.DEFAULT_MIXER["output"])))

   def _fill_clips(self) -> None:
      """!The clips.
      @return None
      """
      keep = self.clips.currentRow()
      self.clips.clear()
      if document_of(self) is not None:
         for i, c in enumerate(document_of(self).data.get("clips", [])):
            how = f"reverse of {c['reverse_of']}" if "reverse_of" in c else audio.voice_summary(c.get("voice"))
            self.clips.addItem(f"{i}: {c.get('key')}  {how}")
      if self.clips.count():
         self.clips.setCurrentRow(keep if 0 <= keep < self.clips.count() else 0)

   def current_number(self) -> int:
      """!The selected sound number.
      @return it, or -1
      """
      return self.table.currentRow()

   def select_sound(self, number: int) -> None:
      """!Selects a sound number.
      @param number  the number
      @return None
      """
      self.table.setCurrentCell(number, 0)

   def _sound_changed(self) -> None:
      """!The entry editor follows the selection.
      @return None
      """
      n, doc = self.current_number(), document_of(self)
      rows = audio.sounds(doc) if doc is not None else []
      if not 0 <= n < len(rows):
         return
      r = rows[n]
      self._filling = True
      try:
         self.song.setCurrentText(r.song or EMPTY_SONG)
         self.player.setCurrentText(r.player)
         self.name.setText(r.name or "")
         self.first.setValue(n)
      finally:
         self._filling = False

   # -- edits --------------------------------------------------------------------------------------------------------

   def _entry_values(self) -> tuple[str | None, str, str | None]:
      """!The entry editor's values.
      @return (song or None, player, name or None)
      """
      song = None if self.song.currentText() == EMPTY_SONG else self.song.currentText()
      return song, self.player.currentText(), self.name.text().strip() or None

   def apply_sound(self) -> None:
      """!Writes the selected entry.
      @return None
      """
      n = self.current_number()
      if n < 0 or document_of(self) is None:
         return
      song, player, name = self._entry_values()
      self.host.apply(f"Sound {n}", lambda: audio.set_sound(document_of(self), n, song, player, name))

   def add_sound(self) -> None:
      """!Appends an entry.
      @return None
      """
      if document_of(self) is None:
         return
      song, player, name = self._entry_values()
      n = len(audio.sounds(document_of(self)))
      if self.host.apply(f"Add sound {n}", lambda: audio.add_sound(document_of(self), song, player, name)):
         self.select_sound(n)

   def remove_last(self) -> None:
      """!Removes the last entry.
      @return None
      """
      if document_of(self) is None or not audio.sounds(document_of(self)):
         return
      n = len(audio.sounds(document_of(self))) - 1
      self.host.apply(f"Remove sound {n}", lambda: audio.remove_sound(document_of(self), n))

   def _player_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A players table edit.
      @param item  the cell
      @return None
      """
      if self._filling or document_of(self) is None:
         return
      i, col = item.row(), item.column()
      kwargs: dict[str, Any] = {}
      if col == 0:
         kwargs["name"] = item.text().strip()
      elif col == 1:
         try:
            kwargs["tracks"] = int(item.text())
         except ValueError:
            self.refresh()
            return
      elif col == HALF:
         kwargs["start_check"] = item.checkState() == QtCore.Qt.CheckState.Checked
      else:
         return
      self.host.apply(f"Player {i}", lambda: audio.set_player(document_of(self), i, **kwargs))

   def add_player(self) -> None:
      """!Appends a player (one track, no start check; edit it in the table).
      @return None
      """
      name = self.new_player.text().strip()
      if document_of(self) is None or not name:
         self.host.show_status("Type the new player's name first")
         return
      if self.host.apply(f"Add player {name}", lambda: audio.add_player(document_of(self), name, 1, False)):
         self.new_player.clear()

   def _mixer(self, name: str, value: Any) -> None:
      """!A mixer edit.
      @param name   the setting
      @param value  its value
      @return None
      """
      if self._filling or document_of(self) is None or document_of(self).data.get("mixer", {}).get(name) == value:
         return
      self.host.apply(f"Mixer {name}", lambda: audio.set_mixer(document_of(self), name, value))

   # -- playing ------------------------------------------------------------------------------------------------------

   def play_sound(self, number: int | None = None) -> None:
      """!Plays a sound number on its player (the current data, or the whole saved table).
      @param number  the number, or None for the selected one
      @return None
      """
      doc = document_of(self)
      n = self.current_number() if number is None else number
      rows = audio.sounds(doc) if doc is not None else []
      if not 0 <= n < len(rows):
         return
      options = self.bar.options()
      try:
         r = self.host.renderer()
         if self.saved.isChecked():
            self.bar.start(lambda: r.sound(n, options, True, self.bar.progress), f"sound {n}")
            return
         sounds = [ar.PreviewSound(rows[n].song, rows[n].player)]
         r.prepare(sounds)
      except audio.AudioError as e:
         self.bar.status.setText(problem_text(e))
         return
      self.bar.start(lambda: r.run_preview(sounds, 0, options, self.bar.progress), f"sound {n}")

   def play_clip(self) -> None:
      """!Plays the selected clip of the saved table with the parameters.
      @return None
      """
      i = self.clips.currentRow()
      if i < 0 or document_of(self) is None:
         return
      clip = ar.ClipOptions(**{name: s.value() for name, s in self.clip_params.items()})
      options = self.clip_bar.options()
      try:
         r = self.host.renderer()
      except audio.AudioError as e:
         self.clip_bar.status.setText(problem_text(e))
         return
      self.clip_bar.start(lambda: r.clip(i, clip, options, self.clip_bar.progress), f"clip {i}")

   def preview_priority(self) -> ar.PriorityPreview | None:
      """!Starts the two sounds and shows who holds each channel: C14b: in the C++ core on the bar's worker
      (audio_render --then; show_priority() when it is done) when the renderer can be built, else at once on the
      engine's reference model of the core.
      @return the reference model's PriorityPreview, or None (the core renders it, or a problem)
      """
      doc = document_of(self)
      if doc is None:
         return None
      first, second, delay, frames = self.first.value(), self.second.value(), self.delay.value(), self.frames.value()
      try:
         r = self.host.renderer()
         if not ar.toolchain():
            sounds, pid = r.prepare_priority(first, second)
            self.mix_bar.start(lambda: r.run_priority(sounds, pid, (first, second), delay, frames,
                                                      self.mix_bar.progress).render, "two sounds")
            return None
         p = ar.priority_preview(doc, first, second, delay, frames, r.folder / ar.PREVIEW_FOLDER)
      except audio.AudioError as e:
         self.outcome.setPlainText(problem_text(e))
         return None
      out = r.output("priority")
      out.mkdir(parents=True, exist_ok=True)
      ar.write_wav(out / ar.WAV_FILE, p.rate, p.samples)
      self.mix_bar.set_result(ar.RenderResult(out, {"frames": len(p.owners), "rate": p.rate}, "two sounds"))
      self.show_priority(p)
      return p

   def show_priority(self, p: ar.PriorityPreview | None) -> None:
      """!Shows a two-sound outcome: the chart, the text, the mix's status.
      @param p  PriorityPreview (None: nothing)
      @return None
      """
      doc = document_of(self)
      if p is None or doc is None:
         return
      self.priority_result = p
      self.chart.set_preview(p)
      self.chart.fit(self.chart_area.viewport().width())
      rows = audio.sounds(doc)
      head = [f"{label}: sound {n} = {rows[n].song} on {rows[n].player} (priority {rows[n].priority})"
              for label, n in (("first", p.numbers[0]), ("second", p.numbers[1])) if n < len(rows)]
      where = "the C++ core" if p.render is not None else "the reference model"
      self.outcome.setPlainText("\n".join(head + [f"(run in {where})", ""] + p.lines()))
      self.mix_bar.status.setText(f"{len(p.steals)} channels taken; the mix is ready to play")
