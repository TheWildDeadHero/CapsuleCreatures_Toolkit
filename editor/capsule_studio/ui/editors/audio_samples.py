"""![S7] Samples (engine M4, D-34): the manifest's samples with their header (pitch, loop, loop start, length) edited
with checks, a waveform of the levels playback reads (DPCM samples decoded with the engine's dpcm.decode()), Play
(one note of a sampled voice on the sample, rendered by the engine), and WAV import through the engine's
wav_sample.convert_entry(): PCM8 or DPCM4 (lookahead, padding), loop points, length, base key and tune, with the
converted waveform previewed before it is added. The imported data file is written beside the manifest when it is
saved (core.audio.AudioDocument).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtWidgets

from ...core import audio, audio_render as ar
from ..panel import EditorPanel, PanelHost
from ..widgets import button
from .audio_common import RenderBar, WaveformView, document_of, grid_rows, problem_text

## WAV file dialog filter.
WAV_FILTER = "WAV files (*.wav);;All files (*)"
## Highest pitch the spin offers (u32 values above it are rare: rate x 1024 of 2 MHz).
PITCH_MAX = 0x7FFFFFFF
## Highest sample count the spins offer.
COUNT_MAX = 0x7FFFFFFF
## DPCM lookahead range.
LOOKAHEAD_RANGE = (1, 8)
## Tune range (cents) and its decimals.
TUNE_RANGE, TUNE_DECIMALS = (-1200.0, 1200.0), 1
## Width of the sample list, pixels.
LIST_WIDTH = 220
## Ticks the Play note is held.
PLAY_TICKS = 60
## Grid columns a wide field and a pair span.
GRID_WIDE, GRID_PAIR = 4, 2
## Layout stretch of the list and the sample.
LIST_STRETCH, SAMPLE_STRETCH = 1, 4


class SamplePanel(EditorPanel):
   """!Samples: header, waveform, play, WAV import."""

   ## Identifier.
   panel_id = "audio_samples"
   ## Tab title.
   title = "Samples"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel.
      @param host    PanelHost (AudioWindow)
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Whether the widgets are being filled.
      self._filling = False
      ## The converted sample of the import preview, or None.
      self.converted = None
      ## The sample list.
      self.samples = QtWidgets.QListWidget()
      self.samples.currentItemChanged.connect(lambda _a, _b: self._sample_changed())
      left = QtWidgets.QWidget()
      lv = QtWidgets.QVBoxLayout(left)
      lv.setContentsMargins(0, 0, 0, 0)
      lv.addWidget(QtWidgets.QLabel("Samples"))
      lv.addWidget(self.samples, 1)
      left.setMinimumWidth(LIST_WIDTH)

      ## Header facts.
      self.info = QtWidgets.QLabel()
      self.info.setWordWrap(True)
      ## Pitch (rate in Hz x 1024 at key 60).
      self.pitch = QtWidgets.QSpinBox()
      self.pitch.setRange(0, PITCH_MAX)
      self.pitch.setToolTip("The playback rate in Hz x 1024 at key 60 (the base key)")
      self.pitch.editingFinished.connect(lambda: self._set("pitch", self.pitch.value()))
      ## Loop.
      self.loop = QtWidgets.QCheckBox("Loop")
      self.loop.toggled.connect(lambda on: self._set("loop", on))
      ## Loop start.
      self.loop_start = QtWidgets.QSpinBox()
      self.loop_start.setRange(0, COUNT_MAX)
      self.loop_start.editingFinished.connect(lambda: self._set("loop_start", self.loop_start.value()))
      ## Length (samples played).
      self.length = QtWidgets.QSpinBox()
      self.length.setRange(1, COUNT_MAX)
      self.length.editingFinished.connect(lambda: self._set("length", self.length.value()))
      ## Play key.
      self.play_key = QtWidgets.QSpinBox()
      self.play_key.setRange(0, audio.MAX_KEY)
      self.play_key.setValue(audio.BASE_KEY)
      self.play_key.setToolTip("The key Play plays (60: the sample's own rate)")
      head = QtWidgets.QHBoxLayout()
      for label, w in (("Pitch", self.pitch), ("", self.loop), ("Loop start", self.loop_start),
                       ("Length", self.length), ("Play key", self.play_key)):
         if label:
            head.addWidget(QtWidgets.QLabel(label))
         head.addWidget(w)
      head.addStretch(1)
      ## The waveform.
      self.wave = WaveformView()
      ## The render bar (Play: a note of a sampled voice on this sample).
      self.bar = RenderBar(lambda: self.play(), lambda _r: None)
      self.bar.render_button.setText("Render note")

      # import
      ## WAV path.
      self.wav_path = QtWidgets.QLineEdit()
      self.wav_path.setPlaceholderText("a WAV file (PCM 8/16/24/32-bit or float, mono)")
      ## New sample's name.
      self.name = QtWidgets.QLineEdit()
      self.name.setPlaceholderText("sample name")
      ## Format.
      self.format = QtWidgets.QComboBox()
      self.format.addItems(audio.sample_formats())
      ## DPCM lookahead.
      self.lookahead = QtWidgets.QSpinBox()
      self.lookahead.setRange(*LOOKAHEAD_RANGE)
      ## DPCM pad.
      self.pad = QtWidgets.QCheckBox("Whole DPCM blocks")
      self.pad.setChecked(True)
      ## Loop start override (enabled by its box).
      self.import_loop = QtWidgets.QSpinBox()
      self.import_loop.setRange(0, COUNT_MAX)
      ## Use the loop start override.
      self.use_loop = QtWidgets.QCheckBox("Loop from")
      ## Length override.
      self.import_length = QtWidgets.QSpinBox()
      self.import_length.setRange(1, COUNT_MAX)
      ## Use the length override.
      self.use_length = QtWidgets.QCheckBox("Length")
      ## Base key override.
      self.import_key = QtWidgets.QSpinBox()
      self.import_key.setRange(0, audio.MAX_KEY)
      self.import_key.setValue(audio.BASE_KEY)
      ## Use the base key override.
      self.use_key = QtWidgets.QCheckBox("Base key")
      ## Tune override.
      self.tune = QtWidgets.QDoubleSpinBox()
      self.tune.setRange(*TUNE_RANGE)
      self.tune.setDecimals(TUNE_DECIMALS)
      self.tune.setSuffix(" cents")
      ## Use the tune override.
      self.use_tune = QtWidgets.QCheckBox("Tune")
      ## Replace a sample of that name.
      self.replace = QtWidgets.QCheckBox("Replace a sample of that name")
      ## The converted preview's facts.
      self.import_info = QtWidgets.QLabel("Convert to preview the sample before it is added")
      self.import_info.setWordWrap(True)
      label = QtWidgets.QLabel
      grid = grid_rows([
         [label("WAV"), (self.wav_path, GRID_WIDE), button("Browse...", lambda: self.browse())],
         [label("Name"), self.name, label("Format"), self.format, label("Lookahead"), self.lookahead],
         [(self.pad, GRID_PAIR), (self.replace, GRID_WIDE - 1)],
         [self.use_loop, self.import_loop, label(""), self.use_length, self.import_length],
         [self.use_key, self.import_key, label(""), self.use_tune, self.tune]])
      buttons = QtWidgets.QHBoxLayout()
      buttons.addWidget(button("Convert", lambda: self.convert(), "Convert the WAV and show it (nothing changes)"))
      buttons.addWidget(button("Import", lambda: self.import_wav(), "Add the sample to the manifest"))
      buttons.addWidget(self.import_info, 1)
      box = QtWidgets.QGroupBox("Import a WAV")
      bv = QtWidgets.QVBoxLayout(box)
      bv.addLayout(grid)
      bv.addLayout(buttons)

      right = QtWidgets.QWidget()
      rv = QtWidgets.QVBoxLayout(right)
      rv.setContentsMargins(0, 0, 0, 0)
      rv.addWidget(self.info)
      rv.addLayout(head)
      rv.addWidget(self.wave, 1)
      rv.addWidget(self.bar)
      rv.addWidget(box)
      split = QtWidgets.QSplitter()
      split.addWidget(left)
      split.addWidget(right)
      split.setStretchFactor(0, LIST_STRETCH)
      split.setStretchFactor(1, SAMPLE_STRETCH)
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

   def refresh(self) -> None:
      """!Re-reads the samples (selection kept).
      @return None
      """
      current = self.current_key()
      self.samples.blockSignals(True)
      self.samples.clear()
      if document_of(self) is not None:
         self.samples.addItems(audio.keys(document_of(self), "sample"))
      items = self.samples.findItems(current, QtCore.Qt.MatchFlag.MatchExactly) if current else []
      if items:
         self.samples.setCurrentItem(items[0])
      elif self.samples.count():
         self.samples.setCurrentRow(0)
      self.samples.blockSignals(False)
      self._sample_changed()

   def current_key(self) -> str | None:
      """!The selected sample.
      @return its key, or None
      """
      item = self.samples.currentItem()
      return item.text() if item is not None else None

   def select(self, key: str) -> None:
      """!Selects a sample.
      @param key  its key
      @return None
      """
      items = self.samples.findItems(key, QtCore.Qt.MatchFlag.MatchExactly)
      if items:
         self.samples.setCurrentItem(items[0])

   # -- the sample ---------------------------------------------------------------------------------------------------

   def _sample_changed(self) -> None:
      """!Shows the selected sample.
      @return None
      """
      key, doc = self.current_key(), document_of(self)
      self._filling = True
      try:
         if key is None or doc is None:
            self.info.setText("No sample")
            self.wave.set_levels([])
            return
         e = audio.entry(doc, key)
         self.pitch.setValue(min(int(e.get("pitch", 0)), PITCH_MAX))
         self.loop.setChecked(bool(e.get("loop")))
         self.loop_start.setValue(int(e.get("loop_start", 0)))
         self.length.setValue(max(int(e.get("length", 1)), 1))
         users = audio.references(doc, key)
         rate = int(e.get("pitch", 0)) / audio.PITCH_SCALE
         self.info.setText(f"{key}: {e.get('format', 'pcm8')}, {rate:.1f} Hz at key {audio.BASE_KEY}, "
                           f"{e.get('length')} samples, data {e.get('data')}"
                           f"{' (imported, saved with the manifest)' if e.get('data') in doc.pending_files else ''}"
                           f"; used by {len(users)} voices" +
                           (f" ({', '.join(users[:audio.SHOWN_USERS])}...)" if users else ""))
         try:
            levels = audio.sample_levels(doc, key)
            self.wave.set_levels(levels, loop=int(e.get("loop_start", 0)) if e.get("loop") else None)
         except audio.AudioError as ex:
            self.wave.empty_text = problem_text(ex)
            self.wave.set_levels([])
      finally:
         self._filling = False

   def _set(self, name: str, value: Any) -> None:
      """!A header field edit.
      @param name   the field
      @param value  its value
      @return None
      """
      key = self.current_key()
      doc = document_of(self)
      if self._filling or key is None or doc is None or audio.entry(doc, key).get(name) == value:
         return
      self.host.apply(f"{name} of {key}", lambda: audio.set_sample_field(document_of(self), key, name, value))

   def play(self) -> None:
      """!Renders a note of a sampled voice on the selected sample (at the Play key) and plays it.
      @return None
      """
      key, doc = self.current_key(), document_of(self)
      if key is None or doc is None:
         return
      voice = {"kind": "sample", "sample": key, "key": audio.BASE_KEY, "attack": audio.BYTE_MAX, "decay": 0,
               "sustain": audio.BYTE_MAX, "release": 0}
      try:
         r = self.host.renderer()
         sound, extra = ar.note_sound(doc, voice, self.play_key.value(), PLAY_TICKS)
         r.prepare([sound], [extra])
      except audio.AudioError as e:
         self.bar.status.setText(problem_text(e))
         return
      options = self.bar.options()
      self.bar.start(lambda: r.run_preview([sound], 0, options, self.bar.progress), key)

   # -- import -------------------------------------------------------------------------------------------------------

   def browse(self) -> None:
      """!Picks a WAV.
      @return None
      """
      path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import a WAV", "", WAV_FILTER)
      if path:
         self.wav_path.setText(path)
         if not self.name.text():
            self.name.setText(Path(path).stem)

   def options(self) -> audio.WavOptions:
      """!The conversion options of the form.
      @return WavOptions
      """
      return audio.WavOptions(self.format.currentText(), self.lookahead.value(), self.pad.isChecked(),
                              self.import_loop.value() if self.use_loop.isChecked() else None,
                              self.import_length.value() if self.use_length.isChecked() else None,
                              self.import_key.value() if self.use_key.isChecked() else None,
                              self.tune.value() if self.use_tune.isChecked() else None)

   def convert(self) -> Any:
      """!Converts the WAV and shows the result (nothing changes in the manifest).
      @return wav_sample.Sample, or None
      """
      path = self.wav_path.text().strip()
      if not path:
         self.import_info.setText("Choose a WAV first")
         return None
      try:
         s = audio.convert_wav(path, self.options())
      except (audio.AudioError, OSError) as e:
         me = self   # through another name: Doxygen 1.12 takes members assigned here for undocumented ones
         self.import_info.setText(problem_text(e))
         me.converted = None
         return None
      me = self   # through another name (see above)
      me.converted = s
      if s.format == "dpcm4":
         levels = audio.dpcm().decode(s.data, s.length)
      else:
         levels = [b - (audio.BYTE_MAX + 1) if b > audio.SIGNED_MAX else b for b in s.data[:s.length]]
      self.wave.set_levels(levels, loop=s.loop_start if s.loop else None)
      self.import_info.setText(f"{s.format}, {s.pitch / audio.PITCH_SCALE:.1f} Hz at key {audio.BASE_KEY}, "
                               f"{s.length} samples, {len(s.data)} data bytes, "
                               f"{'loop from ' + str(s.loop_start) if s.loop else 'one-shot'}")
      return s

   def import_wav(self) -> bool:
      """!Adds the WAV to the manifest as a sample.
      @return True when added
      """
      doc, path, name = document_of(self), self.wav_path.text().strip(), self.name.text().strip()
      if doc is None or not path or not name:
         self.import_info.setText("Choose a WAV and a name first")
         return False
      key = audio.full_key(name, "sample")
      options, replace = self.options(), self.replace.isChecked()
      if self.host.apply(f"Import {Path(path).name}", lambda: audio.import_wav(doc, path, name, options, replace)):
         self.select(key)
         self.import_info.setText(f"Added {key} (its data is written when the manifest is saved)")
         return True
      return False
