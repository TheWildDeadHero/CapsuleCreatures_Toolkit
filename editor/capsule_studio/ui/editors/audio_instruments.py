"""![S7] The instrument set editor (engine M4, D-34): instrument sets (a window of 128 voices of a bank, or a set
with its own voices), each window's voices, one voice's fields by kind (sampled, fixed-rate, reverse, square with
sweep and duty, square, wave, noise, key split, drum set) with its envelope's curve, the key splits of a split
voice (a key strip and its runs; select keys and set their entry), the keys of a drum set, and the bank view: the
windows sets read from each bank and where they overlap (a program past a short set reads its neighbour's voice).

Every edit is checked with the engine's format.py (core.audio) before it becomes an undo step; an edit the build
would refuse is refused with its reason. A bank voice belongs to every set whose window covers it: the voice form
names the sets the change reaches.
"""
from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

from ...core import audio, audio_render as ar
from ..panel import EditorPanel, PanelHost
from ..widgets import button
from .audio_common import (WIDE_STRETCH, BankView, EnvelopeView, KeyStrip, RenderBar, document_of, fit_table,
                           problem_text, scroll)

## Window table columns.
WINDOW_COLUMNS = ("Program", "Kind", "Voice", "Also in")
## The window table's column that stretches.
VOICE_COLUMN = 2
## Split table columns.
SPLIT_COLUMNS = ("Keys", "Entry", "Plays")
## Drum table columns.
DRUM_COLUMNS = ("Key", "Name", "Voice")
## Frames the envelope preview holds a note by default, and the spin's range.
DEFAULT_HELD, HELD_RANGE = 30, (1, 600)
## Width of the set list, pixels.
LIST_WIDTH = 220
## Layout stretches: sets, window, voice.
SETS_STRETCH, WINDOW_STRETCH, VOICE_STRETCH = 1, 2, 2
## Tab indices of the voice side.
VOICE_TAB, SPLIT_TAB, DRUM_TAB, BANK_TAB = 0, 1, 2, 3


class InstrumentPanel(EditorPanel):
   """!Instruments: sets, voices, envelopes, key splits, drum sets and bank windows."""

   ## Identifier.
   panel_id = "audio_instruments"
   ## Tab title.
   title = "Instruments"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel.
      @param host    PanelHost (AudioWindow)
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Whether the widgets are being filled (no edits).
      self._filling = False
      ## The field widgets of the voice form: name -> widget.
      self.fields = {}
      ## The set list.
      self.sets = QtWidgets.QListWidget()
      self.sets.currentItemChanged.connect(lambda _a, _b: self._set_changed())
      ## The window's offset in its bank.
      self.offset = QtWidgets.QSpinBox()
      self.offset.setRange(0, audio.U16_MAX)
      self.offset.setToolTip("The window's first voice in its bank")
      self.offset.editingFinished.connect(lambda: self._offset_changed())
      ## Where the set's voices are.
      self.set_info = QtWidgets.QLabel()
      self.set_info.setWordWrap(True)
      ## New set's name.
      self.new_name = QtWidgets.QLineEdit()
      self.new_name.setPlaceholderText("new name")
      left = QtWidgets.QWidget()
      lv = QtWidgets.QVBoxLayout(left)
      lv.setContentsMargins(0, 0, 0, 0)
      lv.addWidget(QtWidgets.QLabel("Instrument sets"))
      lv.addWidget(self.sets, 1)
      lv.addWidget(self.set_info)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(QtWidgets.QLabel("Window at"))
      row.addWidget(self.offset)
      lv.addLayout(row)
      lv.addWidget(self.new_name)
      lv.addWidget(button("Add set (own voices)", lambda: self.add_set(own=True)))
      lv.addWidget(button("Add window of this bank", lambda: self.add_set(own=False),
                          "A new set reading the selected set's bank from the offset above"))
      lv.addWidget(button("Add bank", lambda: self.add_bank()))
      left.setMinimumWidth(LIST_WIDTH)

      ## The window's voices.
      self.window = QtWidgets.QTableWidget(0, len(WINDOW_COLUMNS))
      self.window.setHorizontalHeaderLabels(WINDOW_COLUMNS)
      self.window.verticalHeader().setVisible(False)
      self.window.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.window.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.window.currentCellChanged.connect(lambda _r, _c, _pr, _pc: self._voice_changed())
      fit_table(self.window, VOICE_COLUMN)
      ## Show the entries past the bank's end.
      self.show_padding = QtWidgets.QCheckBox("Show entries past the bank (none voices)")
      self.show_padding.toggled.connect(lambda _on: self._fill_window())
      ## Kind of a voice to append.
      self.add_kind = QtWidgets.QComboBox()
      self.add_kind.addItems(audio.voice_kinds())
      middle = QtWidgets.QWidget()
      mv = QtWidgets.QVBoxLayout(middle)
      mv.setContentsMargins(0, 0, 0, 0)
      mv.addWidget(self.window, 1)
      mv.addWidget(self.show_padding)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Append voice", lambda: self.append_voice(), "Append a voice of this kind to the set's "
                                                                        "voices or its bank"))
      row.addWidget(self.add_kind)
      mv.addLayout(row)

      # the voice
      ## The voice's kind.
      self.kind = QtWidgets.QComboBox()
      self.kind.addItems(audio.voice_kinds())
      self.kind.activated.connect(lambda _i: self._kind_changed())
      ## Where the voice lives and who shares it.
      self.voice_info = QtWidgets.QLabel()
      self.voice_info.setWordWrap(True)
      ## The form.
      self.form = QtWidgets.QFormLayout()
      self.form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
      ## The envelope preview.
      self.envelope = EnvelopeView()
      ## Frames the preview holds the note.
      self.held = QtWidgets.QSpinBox()
      self.held.setRange(*HELD_RANGE)
      self.held.setValue(DEFAULT_HELD)
      self.held.setSuffix(" frames held")
      self.held.valueChanged.connect(lambda _v: self._show_envelope())
      voice = QtWidgets.QWidget()
      vv = QtWidgets.QVBoxLayout(voice)
      vv.addWidget(self.voice_info)
      kind_row = QtWidgets.QHBoxLayout()
      kind_row.addWidget(QtWidgets.QLabel("Kind"))
      kind_row.addWidget(self.kind, 1)
      vv.addLayout(kind_row)
      form_box = QtWidgets.QWidget()
      form_box.setLayout(self.form)
      vv.addWidget(form_box)
      vv.addWidget(QtWidgets.QLabel("Envelope (level per frame; dashed: the note's end)"))
      vv.addWidget(self.envelope)
      vv.addWidget(self.held)
      ## The key Play note plays.
      self.play_key = QtWidgets.QSpinBox()
      self.play_key.setRange(0, audio.MAX_KEY)
      self.play_key.setValue(audio.BASE_KEY)
      ## Play note: one note of the voice, rendered by the engine.
      self.bar = RenderBar(lambda: self.play_note(), lambda _r: None)
      self.bar.render_button.setText("Play note")
      self.bar.row.insertWidget(1, self.play_key)
      vv.addWidget(self.bar)
      vv.addStretch(1)

      # key split
      ## The keymap's keys.
      self.keys = KeyStrip(lambda a, b: self._keys_picked(a, b))
      ## The split's runs.
      self.split = QtWidgets.QTableWidget(0, len(SPLIT_COLUMNS))
      self.split.setHorizontalHeaderLabels(SPLIT_COLUMNS)
      self.split.verticalHeader().setVisible(False)
      self.split.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.split.currentCellChanged.connect(lambda r, _c, _pr, _pc: self._split_row(r))
      fit_table(self.split)
      ## The selected keys.
      self.key_range = QtWidgets.QLabel("Click a key; shift-click another for a range")
      ## The entry to give them.
      self.entry_value = QtWidgets.QSpinBox()
      self.entry_value.setRange(0, audio.BYTE_MAX)
      split = QtWidgets.QWidget()
      sv = QtWidgets.QVBoxLayout(split)
      ## What the split tab shows.
      self.split_info = QtWidgets.QLabel()
      self.split_info.setWordWrap(True)
      sv.addWidget(self.split_info)
      sv.addWidget(scroll(self.keys))
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.key_range, 1)
      row.addWidget(QtWidgets.QLabel("Entry"))
      row.addWidget(self.entry_value)
      row.addWidget(button("Set keys", lambda: self.set_keys(), "Give the selected keys this entry of the split's "
                                                               "instrument set"))
      sv.addLayout(row)
      sv.addWidget(self.split, 1)

      # drums
      ## The drum set's keys.
      self.drums = QtWidgets.QTableWidget(0, len(DRUM_COLUMNS))
      self.drums.setHorizontalHeaderLabels(DRUM_COLUMNS)
      self.drums.verticalHeader().setVisible(False)
      self.drums.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.drums.cellDoubleClicked.connect(lambda r, _c: self._open_drum(r))
      fit_table(self.drums)
      ## What the drum tab shows.
      self.drum_info = QtWidgets.QLabel()
      self.drum_info.setWordWrap(True)
      drums = QtWidgets.QWidget()
      dv = QtWidgets.QVBoxLayout(drums)
      dv.addWidget(self.drum_info)
      dv.addWidget(self.drums, 1)

      # banks
      ## The bank windows.
      self.banks = BankView()
      ## The overlaps.
      self.overlaps = QtWidgets.QPlainTextEdit()
      self.overlaps.setReadOnly(True)
      banks = QtWidgets.QWidget()
      bv = QtWidgets.QVBoxLayout(banks)
      bv.addWidget(scroll(self.banks, True), WIDE_STRETCH)
      bv.addWidget(self.overlaps, 1)

      ## The voice side's tabs.
      self.side = QtWidgets.QTabWidget()
      self.side.addTab(scroll(voice, True), "Voice")
      self.side.addTab(split, "Key split")
      self.side.addTab(drums, "Drum set")
      self.side.addTab(banks, "Bank windows")
      splitter = QtWidgets.QSplitter()
      splitter.addWidget(left)
      splitter.addWidget(middle)
      splitter.addWidget(self.side)
      for i, s in enumerate((SETS_STRETCH, WINDOW_STRETCH, VOICE_STRETCH)):
         splitter.setStretchFactor(i, s)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(splitter)

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

   def play_note(self) -> None:
      """!Renders one note of the selected voice (held for the envelope preview's frames) and plays it.
      @return None
      """
      v, doc = self.current_voice(), document_of(self)
      if v is None or doc is None or v.get("kind") == "none":
         self.bar.status.setText("Select a voice that plays")
         return
      try:
         r = self.host.renderer()
         sound, extra = ar.note_sound(doc, v, self.play_key.value(), self.held.value())
         r.prepare([sound], [extra])
      except audio.AudioError as e:
         self.bar.status.setText(problem_text(e))
         return
      options = self.bar.options()
      self.bar.start(lambda: r.run_preview([sound], 0, options, self.bar.progress), sound.song)

   def refresh(self) -> None:
      """!Re-reads the sets and the selected voice.
      @return None
      """
      current = self.current_set()
      self.sets.blockSignals(True)
      self.sets.clear()
      if document_of(self) is not None:
         for s in audio.instrument_sets(document_of(self)):
            self.sets.addItem(str(s.get("key")))
      items = self.sets.findItems(current, QtCore.Qt.MatchFlag.MatchExactly) if current else []
      if items:
         self.sets.setCurrentItem(items[0])
      elif self.sets.count():
         self.sets.setCurrentRow(0)
      self.sets.blockSignals(False)
      self._set_changed()

   def current_set(self) -> str | None:
      """!The selected set.
      @return its key, or None
      """
      item = self.sets.currentItem()
      return item.text() if item is not None else None

   def current_index(self) -> int:
      """!The selected program (window index).
      @return 0-127, or -1
      """
      row = self.window.currentRow()
      item = self.window.item(row, 0) if row >= 0 else None
      return int(item.text()) if item is not None else -1

   def select(self, set_key: str, index: int) -> None:
      """!Selects a set and a voice.
      @param set_key  the set
      @param index    the program
      @return None
      """
      items = self.sets.findItems(set_key, QtCore.Qt.MatchFlag.MatchExactly)
      if items:
         self.sets.setCurrentItem(items[0])
      for r in range(self.window.rowCount()):
         if self.window.item(r, 0).text() == str(index):
            self.window.setCurrentCell(r, 0)
            break

   # -- sets ---------------------------------------------------------------------------------------------------------

   def _set_changed(self) -> None:
      """!Shows the selected set.
      @return None
      """
      key, doc = self.current_set(), document_of(self)
      self._filling = True
      try:
         if key is None or doc is None:
            self.set_info.setText("No instrument set")
            self.offset.setEnabled(False)
         else:
            e = audio.entry(doc, key)
            if "voices" in e:
               self.set_info.setText(f"{len(e['voices'])} voices of its own")
               self.offset.setEnabled(False)
               self.offset.setValue(0)
            else:
               b = audio.bank(doc, e.get("bank", ""))
               self.set_info.setText(f"Window of {b['key']} ({len(b.get('voices', []))} voices)")
               self.offset.setEnabled(True)
               self.offset.setValue(int(e.get("offset", 0)))
      except audio.AudioError as ex:
         self.set_info.setText(str(ex))
      finally:
         self._filling = False
      self._fill_window()
      self._fill_banks()

   def _offset_changed(self) -> None:
      """!The window moved.
      @return None
      """
      key = self.current_set()
      if self._filling or key is None or document_of(self) is None:
         return
      if int(audio.entry(document_of(self), key).get("offset", 0)) == self.offset.value():
         return
      value = self.offset.value()
      self.host.apply(f"Window of {key}", lambda: audio.set_window_offset(document_of(self), key, value))

   def add_set(self, own: bool, name: str | None = None) -> None:
      """!A new set: with its own voices, or a window of the selected set's bank.
      @param own   True: its own voices
      @param name  its name, or None for the name field's
      @return None
      """
      doc = document_of(self)
      if doc is None:
         return
      name = name or self.new_name.text().strip()
      if not name:
         self.host.show_status("Type the new set's name first")
         return
      bank_key = None
      if not own:
         cur = self.current_set()
         e = audio.entry(doc, cur) if cur else {}
         bank_key = e.get("bank") or next(iter(audio.keys(doc, "bank")), None)
         if bank_key is None:
            self.host.show_status("There is no bank: add one first")
            return
      offset = self.offset.value() if not own else 0
      key = audio.full_key(name, "instruments")
      if self.host.apply(f"Add {key}", lambda: audio.add_set(doc, name, bank_key, offset)):
         self.new_name.clear()
         self.select(key, 0)

   def add_bank(self, name: str | None = None) -> None:
      """!A new, empty bank.
      @param name  its name, or None for the name field's
      @return None
      """
      doc = document_of(self)
      name = name or self.new_name.text().strip()
      if doc is None or not name:
         self.host.show_status("Type the new bank's name first")
         return
      if self.host.apply(f"Add bank {name}", lambda: audio.add_bank(doc, name)):
         self.new_name.clear()

   # -- the window ---------------------------------------------------------------------------------------------------

   def _fill_window(self) -> None:
      """!The window's voices (selection kept).
      @return None
      """
      key, doc = self.current_set(), document_of(self)
      keep = self.current_index()
      self.window.blockSignals(True)
      rows = []
      if key is not None and doc is not None:
         try:
            rows = [w for w in audio.window(doc, key) if w.voice is not None or self.show_padding.isChecked()]
         except audio.AudioError as e:
            self.set_info.setText(str(e))
      self.window.setRowCount(len(rows))
      for r, w in enumerate(rows):
         shared = [k for k in audio.sets_reading(doc, w.container, w.position) if k != key] if w.position >= 0 else []
         kind = w.voice.get("kind", "?") if w.voice else "-"
         for c, text in enumerate((str(w.index), kind, audio.voice_summary(w.voice), ", ".join(shared))):
            item = QtWidgets.QTableWidgetItem(text)
            item.setToolTip(text)
            self.window.setItem(r, c, item)
      target = next((r for r, w in enumerate(rows) if w.index == keep), 0 if rows else -1)
      if target >= 0:
         self.window.setCurrentCell(target, 0)
      self.window.blockSignals(False)
      self._voice_changed()

   def current_voice(self) -> dict[str, Any] | None:
      """!The selected voice.
      @return the voice (live), or None
      """
      key, i = self.current_set(), self.current_index()
      if key is None or i < 0 or document_of(self) is None:
         return None
      return audio.window_voice(document_of(self), key, i)

   def append_voice(self, kind: str | None = None) -> None:
      """!Appends a voice to the set's voices (or its bank).
      @param kind  its kind, or None for the combo's
      @return None
      """
      key, doc = self.current_set(), document_of(self)
      if key is None or doc is None:
         return
      e = audio.entry(doc, key)
      container = key if "voices" in e else e.get("bank")
      voice = audio.new_voice(doc, kind or self.add_kind.currentText())
      self.host.apply(f"Add voice to {container}", lambda: audio.append_voice(doc, container, voice))

   # -- the voice ----------------------------------------------------------------------------------------------------

   def _voice_changed(self) -> None:
      """!Shows the selected voice's form, envelope, split and drums.
      @return None
      """
      self._filling = True
      try:
         v, key, i = self.current_voice(), self.current_set(), self.current_index()
         while self.form.rowCount():
            self.form.removeRow(0)
         self.fields = {}
         if v is None or key is None:
            self.voice_info.setText("No voice: past the bank's end (a none voice)" if i >= 0 else "No voice selected")
            self.kind.setEnabled(False)
         else:
            w = audio.window(document_of(self), key, i + 1)[i]
            sharing = audio.sets_reading(document_of(self), w.container, w.position)
            self.voice_info.setText(f"Program {i} of {key}: {w.container} voice {w.position}; a change reaches "
                                    f"{', '.join(sharing)}")
            self.kind.setEnabled(True)
            self.kind.setCurrentText(str(v.get("kind")))
            for name, rng in audio.VOICE_FIELDS.get(v.get("kind"), ()):
               self.fields[name] = self._field_widget(name, rng, v)
               self.form.addRow(name.replace("_", " "), self.fields[name])
         self._show_envelope()
         self._show_split()
         self._show_drums()
      finally:
         self._filling = False

   def _field_widget(self, name: str, rng: Any, v: dict[str, Any]) -> QtWidgets.QWidget:
      """!One field's widget, wired to an edit.
      @param name  the field
      @param rng   its range (low, high), "bool" or "ref:KIND"
      @param v     the voice
      @return the widget
      """
      if rng == audio.BOOL_FIELD:
         w = QtWidgets.QCheckBox()
         w.setChecked(bool(v.get(name, False)))
         w.toggled.connect(lambda on, n=name: self.set_field(n, on))
         return w
      if isinstance(rng, str) and rng.startswith(audio.REF_PREFIX):
         w = QtWidgets.QComboBox()
         w.addItems(audio.keys(document_of(self), rng[len(audio.REF_PREFIX):]))
         w.setCurrentText(str(v.get(name) or ""))
         w.activated.connect(lambda _i, n=name, box=w: self.set_field(n, box.currentText()))
         return w
      w = QtWidgets.QSpinBox()
      w.setRange(*rng)
      w.setValue(int(v.get(name, audio.BASE_KEY if name == "key" else 0)))
      if name == "key":
         w.setToolTip("The voice's base key (sampled: the key playing the sample at its rate; drums: the key the "
                      "drum plays at)")
      w.editingFinished.connect(lambda n=name, box=w: self.set_field(n, box.value()))
      return w

   def set_field(self, name: str, value: Any) -> None:
      """!Changes a field of the selected voice (checked).
      @param name   the field
      @param value  its value
      @return None
      """
      v, key, i = self.current_voice(), self.current_set(), self.current_index()
      if self._filling or v is None or key is None or v.get(name) == value:
         return
      self.host.apply(f"{name} of voice {i}", lambda: audio.set_voice_field(document_of(self), key, i, name, value))

   def set_kind(self, kind: str) -> None:
      """!Gives the selected voice another kind (a new voice of it, keeping what fits).
      @param kind  the kind
      @return None
      """
      v, key, i = self.current_voice(), self.current_set(), self.current_index()
      if v is None or key is None or v.get("kind") == kind:
         return
      new = audio.new_voice(document_of(self), kind, v)
      self.host.apply(f"Voice {i} as {kind}", lambda: audio.set_voice(document_of(self), key, i, new))

   def _kind_changed(self) -> None:
      """!The kind combo.
      @return None
      """
      if not self._filling:
         self.set_kind(self.kind.currentText())

   def _show_envelope(self) -> None:
      """!The envelope preview.
      @return None
      """
      v = self.current_voice()
      if v is None or v.get("kind") in ("none", "split", "drums"):
         self.envelope.empty_text = "This voice has no envelope"
         self.envelope.set_curve([], audio.ENVELOPE_FULL, 0)
         return
      levels, full = audio.envelope_of(v, self.held.value())
      self.envelope.set_curve(levels, full, self.held.value())

   # -- key splits -----------------------------------------------------------------------------------------------

   def _show_split(self) -> None:
      """!The split tab: the voice's keymap as runs, the key strip coloured by entry.
      @return None
      """
      v = self.current_voice()
      if v is None or v.get("kind") != "split" or v.get("keymap") not in audio.known_keys(document_of(self))["keymap"]:
         self.split_info.setText("Select a split voice (a key split: a keymap picks a voice of a set per key)")
         self.split.setRowCount(0)
         self.keys.set_values([None] * audio.KEYS)
         return
      km = audio.entry(document_of(self), v["keymap"])
      self.split_info.setText(f"{v['keymap']} picks a voice of {v['instruments']} per key; it plays at the note's "
                              "key")
      runs = audio.split_targets(document_of(self), v)
      self.split.setRowCount(len(runs))
      for r, (first, last, value, target) in enumerate(runs):
         for c, text in enumerate((f"{audio.key_name(first)}-{audio.key_name(last)}", str(value),
                                   audio.voice_summary(target))):
            self.split.setItem(r, c, QtWidgets.QTableWidgetItem(text))
      self.keys.set_values(km["entries"])

   def _keys_picked(self, first: int, last: int) -> None:
      """!Keys selected on the strip.
      @param first  first key
      @param last   last key
      @return None
      """
      self.key_range.setText(f"Keys {audio.key_name(first)}-{audio.key_name(last)} ({first}-{last})")
      v = self.current_voice()
      if v is not None and v.get("kind") == "split":
         self.entry_value.setValue(audio.entry(document_of(self), v["keymap"])["entries"][first])

   def _split_row(self, row: int) -> None:
      """!A run picked in the table selects its keys.
      @param row  the row
      @return None
      """
      v = self.current_voice()
      if row < 0 or v is None or v.get("kind") != "split":
         return
      runs = audio.keymap_ranges(audio.entry(document_of(self), v["keymap"])["entries"])
      if row < len(runs):
         self.keys.selection = (runs[row][0], runs[row][1])
         self.keys.update()
         self._keys_picked(runs[row][0], runs[row][1])

   def set_keys(self, first: int | None = None, last: int | None = None, value: int | None = None) -> None:
      """!Gives keys an entry of the split's set (the selected keys and the entry spin by default).
      @param first  first key
      @param last   last key
      @param value  the entry
      @return None
      """
      v = self.current_voice()
      if v is None or v.get("kind") != "split":
         self.host.show_status("Select a split voice first")
         return
      if first is None or last is None:
         if self.keys.selection is None:
            self.host.show_status("Select keys on the strip first")
            return
         first, last = self.keys.selection
      value = self.entry_value.value() if value is None else value
      keymap = v["keymap"]
      doc = document_of(self)
      self.host.apply(f"Keys of {keymap}", lambda: audio.set_keymap_range(doc, keymap, first, last, value))

   # -- drum sets ------------------------------------------------------------------------------------------------

   def _show_drums(self) -> None:
      """!The drum tab: what each key of the voice's drum set plays.
      @return None
      """
      v = self.current_voice()
      sets = audio.known_keys(document_of(self))["instruments"] if document_of(self) is not None else set()
      if v is None or v.get("kind") != "drums" or v.get("instruments") not in sets:
         self.drum_info.setText("Select a drum set voice (each key plays its own voice of the set, at that voice's "
                                "key and pan)")
         self.drums.setRowCount(0)
         return
      rows = [(k, d) for k, d in audio.drum_map(document_of(self), v["instruments"])
              if d is not None and d.get("kind") != "none"]
      self.drum_info.setText(f"{v['instruments']}: {len(rows)} keys play a voice (double-click one to edit it)")
      self.drums.setRowCount(len(rows))
      for r, (k, d) in enumerate(rows):
         for c, text in enumerate((str(k), audio.key_name(k), audio.voice_summary(d))):
            self.drums.setItem(r, c, QtWidgets.QTableWidgetItem(text))

   def _open_drum(self, row: int) -> None:
      """!Opens a drum key's voice.
      @param row  the row
      @return None
      """
      v = self.current_voice()
      if v is None or v.get("kind") != "drums":
         return
      key = int(self.drums.item(row, 0).text())
      self.show_padding.setChecked(True)
      self.select(v["instruments"], key)
      self.side.setCurrentIndex(VOICE_TAB)

   # -- banks ----------------------------------------------------------------------------------------------------

   def _fill_banks(self) -> None:
      """!The bank view and the overlaps.
      @return None
      """
      if document_of(self) is None:
         self.banks.set_banks([], None)
         self.overlaps.setPlainText("")
         return
      banks = audio.bank_windows(document_of(self))
      self.banks.set_banks(banks, self.current_set())
      lines = []
      for b in banks:
         for a, c, shared in audio.overlaps(b.windows):
            lines.append(f"{b.key}: {a} and {c} share {shared} voices (a program past one set's voices reads the "
                         "other's)")
      self.overlaps.setPlainText("\n".join(lines) or "No windows overlap")
