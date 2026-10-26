"""![S7] MIDI import (engine M4, D-34): a MIDI file converted with the engine's midi_song.convert() and the options of
one conversion config line (-V volume, -G instrument set, -P priority, -R reverb, -X 48 clocks per beat, -E exact
gate times, -N no compression), shown before anything changes: the report of each track's end tick (or loop), the
frames to the song's end, notes that come before a track's first program change, each track's commands with their
ticks, the notes on a timeline, and a rendered preview through the engine (the converted song on a player with
the manifest's instruments). Import adds it in the author form (the MIDI file beside the manifest and its options;
the build converts it) or the compiled form (the converted command bytes), optionally with a song table entry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6 import QtWidgets

from ...core import audio, audio_render as ar, audio_song
from ..panel import EditorPanel, PanelHost
from ..widgets import button
from .audio_common import PianoRoll, RenderBar, document_of, grid_rows, problem_text, scroll, zoom_slider

## MIDI file dialog filter.
MIDI_FILTER = "MIDI files (*.mid *.midi);;All files (*)"
## The player choice that adds no song table entry.
NO_ENTRY = "(no song table entry)"
## Volume and priority ranges.
VOLUME_RANGE = (0, audio.BYTE_MAX)
## Reverb spin value meaning "none" (leave the mixer's reverb).
REVERB_NONE = -1
## Clocks per beat choices.
CLOCKS = ("24", "48")
## Default master volume (-V) of the form.
DEFAULT_VOLUME = 127
## Grid columns a wide field and a pair span.
GRID_WIDE, GRID_PAIR = 5, 2
## Layout stretch of the report and the listing.
REPORT_STRETCH, LISTING_STRETCH = 1, 2


class MidiPanel(EditorPanel):
   """!MIDI import: options, report, preview, import."""

   ## Identifier.
   panel_id = "audio_midi"
   ## Tab title.
   title = "MIDI import"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel.
      @param host    PanelHost (AudioWindow)
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The converted song (midi_song.Song), or None.
      self.song = None
      ## Its SongView, or None.
      self.view = None
      ## Whether the option widgets are writing the options line.
      self._writing = False
      ## MIDI path.
      self.path = QtWidgets.QLineEdit()
      self.path.setPlaceholderText("a MIDI file (format 0 or 1)")
      ## The song's name.
      self.name = QtWidgets.QLineEdit()
      self.name.setPlaceholderText("song name")
      ## The options line (what the build reads).
      self.options = QtWidgets.QLineEdit()
      self.options.setToolTip("One conversion config line: -V volume, -G instrument set, -P priority, -R reverb, "
                              "-X 48 clocks per beat, -E exact gate times, -N no compression")
      ## Instrument set.
      self.instruments = QtWidgets.QComboBox()
      ## Master volume.
      self.volume = QtWidgets.QSpinBox()
      self.volume.setRange(*VOLUME_RANGE)
      self.volume.setValue(DEFAULT_VOLUME)
      ## Priority.
      self.priority = QtWidgets.QSpinBox()
      self.priority.setRange(0, audio.MAX_PRIORITY)
      ## Reverb.
      self.reverb = QtWidgets.QSpinBox()
      self.reverb.setRange(REVERB_NONE, audio.MAX_REVERB)
      self.reverb.setSpecialValueText("none")
      self.reverb.setValue(REVERB_NONE)
      ## Clocks per beat.
      self.clocks = QtWidgets.QComboBox()
      self.clocks.addItems(CLOCKS)
      ## Exact gate times.
      self.exact = QtWidgets.QCheckBox("Exact gate (-E)")
      ## Compression.
      self.compress = QtWidgets.QCheckBox("Compress (patterns, running status)")
      self.compress.setChecked(True)
      for w in (self.volume, self.priority, self.reverb):
         w.valueChanged.connect(lambda _v: self._write_options())
      for w in (self.instruments, self.clocks):
         w.currentIndexChanged.connect(lambda _i: self._write_options())
      for w in (self.exact, self.compress):
         w.toggled.connect(lambda _on: self._write_options())
      ## Form of the song.
      self.form = QtWidgets.QComboBox()
      self.form.addItems(audio.SONG_FORMS)
      self.form.setToolTip("midi: the MIDI file and its options (the build converts it); compiled: the converted "
                           "bytes")
      ## Player of a new song table entry.
      self.player = QtWidgets.QComboBox()
      ## Name key of the entry.
      self.sound_name = QtWidgets.QLineEdit()
      self.sound_name.setPlaceholderText("optional sound:NAME")
      ## Replace a song of that name.
      self.replace = QtWidgets.QCheckBox("Replace a song of that name")
      label = QtWidgets.QLabel
      grid = grid_rows([
         [label("MIDI"), (self.path, GRID_WIDE), button("Browse...", lambda: self.browse())],
         [label("Name"), self.name, label("Instruments"), self.instruments, label("Volume"), self.volume],
         [label("Priority"), self.priority, label("Reverb"), self.reverb, label("Clocks per beat"), self.clocks],
         [(self.exact, GRID_PAIR), (self.compress, GRID_PAIR)],
         [label("Options"), (self.options, GRID_WIDE)],
         [label("Form"), self.form, label("Add to"), self.player, (self.sound_name, GRID_PAIR)],
         [(self.replace, GRID_PAIR)]])
      actions = QtWidgets.QHBoxLayout()
      actions.addWidget(button("Convert", lambda: self.convert(), "Convert and report (nothing changes)"))
      actions.addWidget(button("Import", lambda: self.import_song(), "Add the song to the manifest"))
      ## Result line.
      self.status = QtWidgets.QLabel("Choose a MIDI file and convert it")
      self.status.setWordWrap(True)
      actions.addWidget(self.status, 1)

      ## The report.
      self.report = QtWidgets.QPlainTextEdit()
      self.report.setReadOnly(True)
      ## Each track's commands with their ticks.
      self.listing = QtWidgets.QPlainTextEdit()
      self.listing.setReadOnly(True)
      ## The notes.
      self.roll = PianoRoll()
      ## Preview render.
      self.bar = RenderBar(lambda: self.preview(), lambda _r: None, tick=self._tick)
      timeline = QtWidgets.QWidget()
      tv = QtWidgets.QVBoxLayout(timeline)
      tv.setContentsMargins(0, 0, 0, 0)
      tv.addWidget(zoom_slider(self.roll.set_zoom))
      ## The roll's scroll area.
      self.roll_area = scroll(self.roll)
      tv.addWidget(self.roll_area, 1)
      ## The views.
      self.views = QtWidgets.QTabWidget()
      self.views.addTab(self.report, "Report")
      self.views.addTab(self.listing, "Commands")
      self.views.addTab(timeline, "Timeline")
      lay = QtWidgets.QVBoxLayout(self)
      lay.addLayout(grid)
      lay.addLayout(actions)
      lay.addWidget(self.bar)
      lay.addWidget(self.views, 1)
      self._write_options()

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

   def refresh(self) -> None:
      """!The instrument sets and players to offer.
      @return None
      """
      self._writing = True
      try:
         keep_set, keep_player = self.instruments.currentText(), self.player.currentText()
         self.instruments.clear()
         self.player.clear()
         self.player.addItem(NO_ENTRY)
         if document_of(self) is not None:
            self.instruments.addItems(audio.keys(document_of(self), "instruments"))
            self.player.addItems([str(p.get("name")) for p in audio.players(document_of(self))])
         if keep_set:
            self.instruments.setCurrentText(keep_set)
         if keep_player:
            self.player.setCurrentText(keep_player)
      finally:
         self._writing = False
      self._write_options()

   # -- options ------------------------------------------------------------------------------------------------------

   def _write_options(self) -> None:
      """!The option widgets write the options line.
      @return None
      """
      writing = self._writing   # a local alias (Doxygen 1.12 reads `if self.x:` as a new member)
      if writing:
         return
      words = [f"-V{self.volume.value():03d}"]
      if self.instruments.currentText():
         words.append(f"-G{self.instruments.currentText().split(':', 1)[1]}")
      words.append(f"-P{self.priority.value()}")
      if self.reverb.value() != REVERB_NONE:
         words.append(f"-R{self.reverb.value()}")
      if self.clocks.currentText() == CLOCKS[1]:
         words.append("-X")
      if self.exact.isChecked():
         words.append("-E")
      if not self.compress.isChecked():
         words.append("-N")
      self.options.setText(" ".join(words))

   def browse(self) -> None:
      """!Picks a MIDI file.
      @return None
      """
      path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import a MIDI file", "", MIDI_FILTER)
      if path:
         self.path.setText(path)
         if not self.name.text():
            self.name.setText(Path(path).stem)

   # -- converting ---------------------------------------------------------------------------------------------------

   def convert(self) -> Any:
      """!Converts the MIDI file and shows the report, the commands and the notes (nothing changes).
      @return midi_song.Song, or None
      """
      path = self.path.text().strip()
      if not path:
         self.status.setText("Choose a MIDI file first")
         return None
      try:
         data = Path(path).read_bytes()
         opts = audio.midi_options(self.options.text())
         song = audio.convert_midi(data, opts, self.name.text().strip() or Path(path).stem)
      except (audio.AudioError, OSError) as e:
         self.status.setText(problem_text(e))
         self.song = self.view = None
         self.report.setPlainText(problem_text(e))
         return None
      self.song = song
      self.view = audio_song.analyse(song.data, song.tracks)
      report = audio.midi_report(song)
      self.report.setPlainText("\n".join(report.lines() + ["", f"options: {audio.options_text(opts)}"]))
      self.listing.setPlainText(audio.midi().listing(song))
      self.roll.set_view(self.view)
      self.roll.fit(self.roll_area.viewport().width())
      self.status.setText(report.lines()[0])
      return song

   def preview(self) -> None:
      """!Renders the converted song (the manifest's instruments, on the chosen player or the first).
      @return None
      """
      doc = document_of(self)
      if doc is None or (self.song is None and self.convert() is None):
         return
      song = self.song
      if song.instruments not in audio.known_keys(doc)["instruments"]:
         self.bar.status.setText(f"{song.instruments} is not in the manifest: choose its instrument set")
         return
      players = [str(p.get("name")) for p in audio.players(doc)]
      player = self.player.currentText() if self.player.currentText() in players else (players[0] if players else "")
      sound = ar.PreviewSound(f"song:{song.name}", player, set(), (bytes(song.data), list(song.tracks)),
                              song.instruments, song.priority)
      try:
         r = self.host.renderer()
         r.prepare([sound])
      except audio.AudioError as e:
         self.bar.status.setText(problem_text(e))
         return
      options = self.bar.options()
      self.bar.start(lambda: r.run_preview([sound], 0, options, self.bar.progress), sound.song)

   def _tick(self, seconds: float) -> None:
      """!The playhead.
      @param seconds  time into the WAV (-1: stopped)
      @return None
      """
      res, v = self.bar.result, self.view
      if seconds < 0 or res is None or v is None:
         self.roll.playhead = -1
      else:
         per = int(res.summary.get("output_samples_per_frame") or res.summary.get("samples_per_frame") or 1)
         frame = int(seconds * int(res.summary.get("rate") or 1) / per) + 1
         song_frame = frame - (audio_song.FIRST_RENDER_FRAME - 1)
         self.roll.playhead = v.tick_at(song_frame) if song_frame >= 1 else -1
      self.roll.update()

   def import_song(self) -> bool:
      """!Adds the song (and the song table entry) to the manifest.
      @return True when added
      """
      doc, path, name = document_of(self), self.path.text().strip(), self.name.text().strip()
      if doc is None or not path or not name:
         self.status.setText("Choose a MIDI file and a name first")
         return False
      player = self.player.currentText()
      player = None if player in ("", NO_ENTRY) else player
      options, form, replace = self.options.text(), self.form.currentText(), self.replace.isChecked()
      sound_name = self.sound_name.text().strip() or None
      key = audio.full_key(name, "song")
      done = {}

      def add() -> None:
         """!The import.
         @return None
         """
         done["result"] = audio.add_midi_song(doc, path, name, options, None, form, player, sound_name, replace)

      if self.host.apply(f"Import {Path(path).name}", add):
         _e, number = done["result"]
         self.status.setText(f"Added {key} ({form} form)" + (f" as sound {number} on {player}" if number is not None
                                                            else ""))
         return True
      return False
