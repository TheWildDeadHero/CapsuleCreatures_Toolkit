"""!The Presenters panel: who shows a party on screen and speaks for it (D-20 B).

A presenter has a sprite (picked from the game's sprite assets, or none: text
only), an offset from where its party's side stands in the format, an
entrance and an exit (none, slide, fade, a sequence; an exit may also stay),
whether it comes back at the end, and its intro / defeat / victory texts.
Texts may use {party} and {@concept} terms; the panel checks them against the
game's code page as the build will. The preview draws the format's screen
layout and plays the presenter's motion frame by frame, as the engine's
presenter_view plays it (core.battle.presenter_track()).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import battle, codepage, engine, paths
from ....core.document import DocumentError
from ...widgets import button
from ..battle_common import NONE_TEXT, TERM_SLOT, EntryPanel, combo, set_check, set_combo, set_spin, spin

if TYPE_CHECKING:
   from ....core.document import Document
   from ..battle_common import JsonDict

## Shown for {party} in a text preview when no party shows the presenter.
NO_PARTY = "(party)"
## What the preview plays: label -> cues in order.
PREVIEW_CUES = {"Enter": ("enter",), "Exit": ("exit",), "Return": ("return",), "Enter, then exit": ("enter", "exit")}
## Frames the preview holds between two cues and after the last one.
HOLD_FRAMES = 30
## Milliseconds per preview frame (the GBA's 59.73 Hz, near enough).
FRAME_MS = 17
## Screen pixels per preview pixel.
PREVIEW_ZOOM = 2
## Size of a battler's box in the preview, pixels (creature sprites are this size at most).
BATTLER_BOX = 64
## Half the size of a stand's cross in the preview, pixels.
STAND_MARK = 4
## Size drawn for a sprite the game's assets do not have (its real size is unknown).
UNKNOWN_SIZE = (32, 32)
## Preview colours.
PREVIEW_COLORS = {"screen": "#30384a", "battler": "#8090b0", "stand": "#f0d060", "presenter": "#e07050",
                  "text": "#e0e8f0"}
## Where a battler's number is drawn: pixels right of and below its box's top-left corner.
LABEL_OFFSET = (2, 10)
## Margin of the caption from the screen's bottom-left corner, pixels.
CAPTION_MARGIN = 4
## Highest opacity of a QColor.
OPAQUE = 255


def _bc() -> Any:
   """!The engine's battle compiler (its limits and lists: S11, no copies here).
   @return the module
   """
   return engine.tool("battle_compiler")


def offset_range() -> tuple[int, int]:
   """!The offsets a presenter's "at" takes, pixels (PresenterData::dx / dy are int8: the compiler's I8_MIN /
   I8_MAX).
   @return (lowest, highest)
   """
   return int(_bc().I8_MIN), int(_bc().I8_MAX)


def max_frames() -> int:
   """!Highest frames of a motion (a byte: the compiler's U8_MAX).
   @return the value
   """
   return int(_bc().U8_MAX)


def text_keys() -> tuple[str, ...]:
   """!The texts of a presenter (the keys core.codepage checks: the engine's PRESENTER_TEXTS, intro, defeat,
   victory).
   @return keys, in the order the page shows them
   """
   return tuple(codepage.battle_entry_texts()["presenters"])


def text_problems(doc: Document, page: object, text: str) -> list[str]:
   """!What the build would refuse in a presenter text: unknown terms or
   placeholders, characters the game's code page lacks.
   @param doc   battle Document
   @param page  text_encoder.CodePage
   @param text  the text
   @return messages ([] when fine)
   """
   te = engine.tool("text_encoder")
   terms = battle.terms(doc)
   out = []
   try:
      te.expand_terms(text, "text", terms)
   except te.TextError as e:
      out.append(str(e).replace("text: ", "", 1))
   for item in codepage.MARKUP_ITEM.findall(text):
      inner = item[1:-1]
      if not inner.startswith(te.TERM_PREFIX) and inner not in _bc().PRESENTER_TEXT_ARGS:
         out.append(f"{item}: presenter texts take {{party}} and {{@concept}} only")
   bad = codepage.unmapped(page, codepage.plain(text, terms))
   if bad:
      out.append(f"not in the code page {page.id!r}: " + " ".join(repr(c) for c in bad))
   return out


class PresenterPreview(QtWidgets.QWidget):
   """!The battle screen of a format: battler places, the sides' stands and a presenter's sprite."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates an empty preview.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## Screen size (width, height), pixels.
      self.screen = battle.DEFAULT_SCREEN_WIDTH, battle.DEFAULT_SCREEN_HEIGHT
      ## Battler places (centres).
      self.battlers = []
      ## Stands of the sides.
      self.stands = []
      ## The presenter's sprite: (x, y, w, h, weight 0 to blend_max), or None.
      self.sprite = None
      ## Weight of a fully shown sprite.
      self.weight_max = battle.DEFAULT_BLEND_MAX
      ## Caption (frame number, notes).
      self.caption = ""
      self.setFixedSize(self.screen[0] * PREVIEW_ZOOM, self.screen[1] * PREVIEW_ZOOM)

   def set_layout(self, screen: tuple[int, int], battlers: list[tuple[int, int]],
                  stands: list[tuple[int, int]], weight_max: int) -> None:
      """!Shows a format.
      @param screen      (width, height)
      @param battlers    battler place centres
      @param stands      stand of each side
      @param weight_max  weight of a fully shown sprite
      @return None
      """
      self.screen, self.battlers, self.stands, self.weight_max = screen, battlers, stands, weight_max
      self.setFixedSize(screen[0] * PREVIEW_ZOOM, screen[1] * PREVIEW_ZOOM)
      self.update()

   def set_sprite(self, sprite: tuple[int, int, int, int, int] | None, caption: str = "") -> None:
      """!Shows the presenter's sprite at one frame.
      @param sprite   (x, y, w, h, weight), or None
      @param caption  caption text
      @return None
      """
      self.sprite, self.caption = sprite, caption
      self.update()

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the screen.
      @param event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.scale(PREVIEW_ZOOM, PREVIEW_ZOOM)
      p.fillRect(0, 0, self.screen[0], self.screen[1], QtGui.QColor(PREVIEW_COLORS["screen"]))
      half = BATTLER_BOX // battle.HALF
      p.setPen(QtGui.QPen(QtGui.QColor(PREVIEW_COLORS["battler"]), 1, QtCore.Qt.PenStyle.DotLine))
      for i, (x, y) in enumerate(self.battlers):
         p.drawRect(x - half, y - half, BATTLER_BOX, BATTLER_BOX)
         p.drawText(x - half + LABEL_OFFSET[0], y - half + LABEL_OFFSET[1], str(i))
      p.setPen(QtGui.QPen(QtGui.QColor(PREVIEW_COLORS["stand"]), 1))
      for x, y in self.stands:
         p.drawLine(x - STAND_MARK, y, x + STAND_MARK, y)
         p.drawLine(x, y - STAND_MARK, x, y + STAND_MARK)
      if self.sprite is not None:
         x, y, w, h, weight = self.sprite
         color = QtGui.QColor(PREVIEW_COLORS["presenter"])
         # The blend weight as opacity: 0 hidden, weight_max opaque.
         color.setAlpha(OPAQUE * weight // max(1, self.weight_max))
         p.fillRect(x, y, w, h, color)
      p.setPen(QtGui.QColor(PREVIEW_COLORS["text"]))
      p.drawText(CAPTION_MARGIN, self.screen[1] - CAPTION_MARGIN, self.caption)
      p.end()


class PresentersPanel(EntryPanel):
   """!Presenters: sprite, offset, entrance and exit, return, texts, preview.

   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   panel_id = "presenters"
   ## See EditorPanel.title.
   title = "Presenters"
   ## See EntryPanel.kind.
   kind = "presenters"
   ## See BattlePanel.title_kind.
   title_kind = "presenters"

   def build_form(self, layout: QtWidgets.QVBoxLayout) -> None:
      """!Presenter fields and texts on the left, the preview on the right.
      @param layout  QVBoxLayout
      @return None
      """
      columns = QtWidgets.QHBoxLayout()
      left = QtWidgets.QVBoxLayout()
      right = QtWidgets.QVBoxLayout()
      columns.addLayout(left, 1)
      columns.addLayout(right)
      layout.addLayout(columns, 1)
      ## Battle file the sprite list was read for, and the list: (path, {key: size}).
      self._sprites_for = (None, {})
      ## Sprite asset.
      self.sprite = combo(lambda t: self.set_field("sprite", None if t == NONE_TEXT else t))
      ## Offset from the stand, x.
      self.dx = spin(*offset_range(), lambda _v: self._at_changed())
      ## Offset from the stand, y.
      self.dy = spin(*offset_range(), lambda _v: self._at_changed())
      ## Comes back when its party is defeated or wins.
      self.returns = QtWidgets.QCheckBox("comes back when its party is defeated or wins")
      self.returns.toggled.connect(lambda on: self.set_field("returns", True if on else None, "Set returns"))
      at_row = QtWidgets.QHBoxLayout()
      at_row.addWidget(QtWidgets.QLabel("x"))
      at_row.addWidget(self.dx)
      at_row.addWidget(QtWidgets.QLabel("y"))
      at_row.addWidget(self.dy)
      at_row.addStretch(1)
      form = QtWidgets.QFormLayout()
      form.addRow("Sprite", self.sprite)
      form.addRow("Offset from the stand", at_row)
      form.addRow("Return", self.returns)
      left.addLayout(form)
      ## Motion widgets per kind ("enter", "exit"): {"style", "frames", "from", "when", "sequence", "choose"}.
      self.motion = {}
      left.addWidget(self._motion_box("enter", "Entrance"))
      left.addWidget(self._motion_box("exit", "Exit"))

      # Texts.
      ## Text fields by key.
      self.texts = {}
      ## Problems / preview line under each text field, by key.
      self.text_notes = {}
      tform = QtWidgets.QFormLayout()
      for key in text_keys():
         edit = QtWidgets.QLineEdit()
         edit.setPlaceholderText("(none)")
         edit.editingFinished.connect(lambda k=key: self._text_changed(k))
         edit.textEdited.connect(lambda _t, k=key: self._check_text(k))
         note = QtWidgets.QLabel()
         note.setWordWrap(True)
         self.texts[key], self.text_notes[key] = edit, note
         tform.addRow(key.capitalize(), edit)
         tform.addRow("", note)
      texts_label = self.term_label("party", False, "Texts ({party}: the " + TERM_SLOT + "'s name; {@concept}: a term)")
      texts_label.setWordWrap(True)
      left.addWidget(texts_label)
      left.addLayout(tform)
      ## Parties showing the presenter.
      self.used_by = QtWidgets.QLabel()
      self.used_by.setWordWrap(True)
      left.addWidget(self.used_by)
      left.addStretch(1)

      # Preview.
      ## Format the preview shows.
      self.preview_format = QtWidgets.QComboBox()
      self.preview_format.activated.connect(lambda _i: self.update_preview())
      ## Side the presenter's party is on.
      self.preview_side = QtWidgets.QSpinBox()
      self.preview_side.setValue(battle.FOE_SIDE)
      self.preview_side.valueChanged.connect(lambda _v: self.update_preview())
      ## Cues the preview plays.
      self.preview_cue = QtWidgets.QComboBox()
      self.preview_cue.addItems(list(PREVIEW_CUES))
      self.preview_cue.activated.connect(lambda _i: self.update_preview())
      ## The preview.
      self.preview = PresenterPreview()
      ## Frames being played: (x, y, w, h, weight, caption) per frame.
      self.frames = []
      ## Frame shown.
      self.frame_index = 0
      ## Plays the frames.
      self.timer = QtCore.QTimer(self)
      self.timer.setInterval(FRAME_MS)
      self.timer.timeout.connect(lambda: self._tick())
      prow = QtWidgets.QHBoxLayout()
      prow.addWidget(self.term_label("format"))
      prow.addWidget(self.preview_format, 1)
      prow.addWidget(QtWidgets.QLabel("side"))
      prow.addWidget(self.preview_side)
      right.addWidget(QtWidgets.QLabel("Preview (as the engine's presenter_view plays it)"))
      right.addLayout(prow)
      prow = QtWidgets.QHBoxLayout()
      prow.addWidget(self.preview_cue, 1)
      prow.addWidget(button("Play", lambda: self.play()))
      prow.addWidget(button("Stop", lambda: self.stop()))
      right.addLayout(prow)
      right.addWidget(self.preview)
      right.addStretch(1)

   def _motion_box(self, kind: str, title: str) -> QtWidgets.QGroupBox:
      """!The widgets of an entrance or exit.
      @param kind   "enter" or "exit"
      @param title  group title
      @return QGroupBox
      """
      w = {"style": combo(lambda t, k=kind: self._motion_changed(k, "style", t)),
           "frames": spin(1, max_frames(), lambda v, k=kind: self._motion_changed(k, "frames", v)),
           "from": combo(lambda t, k=kind: self._motion_changed(k, "from", t)),
           "sequence": QtWidgets.QLineEdit(),
           "choose": button("Choose...", lambda k=kind: self.choose_sequence(k),
                            "Pick a sequence file (capsule.sequence/1); it is stored relative to the battle data")}
      w["sequence"].editingFinished.connect(lambda k=kind: self._motion_changed(
         k, "sequence", self.motion[k]["sequence"].text().strip() or None))
      w["sequence"].setToolTip("Sequences are JSON files (see the engine's sequence_compiler.py); the "
                               "studio has no sequence editor yet")
      form = QtWidgets.QFormLayout()
      form.addRow("Style", w["style"])
      form.addRow("Frames", w["frames"])
      form.addRow("Slide from" if kind == "enter" else "Slide to", w["from"])
      if kind == "exit":
         w["when"] = combo(lambda t: self._motion_changed("exit", "when", t))
         form.addRow("Leaves", w["when"])
      seq_row = QtWidgets.QHBoxLayout()
      seq_row.addWidget(w["sequence"], 1)
      seq_row.addWidget(w["choose"])
      form.addRow("Sequence", seq_row)
      self.motion[kind] = w
      box = QtWidgets.QGroupBox(title)
      box.setLayout(form)
      return box

   # -- filling ---------------------------------------------------------------------------

   def sprites(self) -> dict[str, tuple[int, int]]:
      """!The game's sprites and their sizes (read once per battle file).
      @return {key: (w, h)}
      """
      doc = self.battle_doc()
      path = doc.path if doc is not None else None
      if self._sprites_for[0] != path:
         self._sprites_for = (path, battle.sprite_sizes(path) if path is not None else {})
      return self._sprites_for[1]

   def document_replaced(self) -> None:
      """!Another battle file: the sprite list is read again.
      @return None
      """
      self._sprites_for = (None, {})
      super().document_replaced()

   def fill_form(self, entry: JsonDict | None) -> None:
      """!Shows a presenter.
      @param entry  presenter dict or None
      @return None
      """
      self.stop()
      on = entry is not None
      e = entry or {}
      set_combo(self.sprite, [NONE_TEXT] + sorted(self.sprites()), e.get("sprite") or NONE_TEXT)
      at = e.get("at") if isinstance(e.get("at"), list) and len(e.get("at")) == _bc().PAIR else [0, 0]
      set_spin(self.dx, at[0])
      set_spin(self.dy, at[1])
      set_check(self.returns, e.get("returns") is True)
      bc = engine.tool("battle_compiler") if self.project() is not None else None
      for kind, w in self.motion.items():
         m = e.get(kind) if isinstance(e.get(kind), dict) else {}
         styles = [] if bc is None else (bc.MOTIONS if kind == "exit" else [s for s in bc.MOTIONS if s != "stay"])
         style = m.get("style", styles[0] if styles else None)
         set_combo(w["style"], styles, style)
         set_spin(w["frames"], m.get("frames", bc.DEFAULT_MOTION_FRAMES if bc else 1))
         set_combo(w["from"], bc.EDGES if bc else [], m.get("from", bc.EDGES[0] if bc else None))
         if "when" in w:
            set_combo(w["when"], bc.EXIT_WHEN if bc else [], m.get("when", bc.EXIT_WHEN[0] if bc else None))
         w["sequence"].setText(m.get("sequence", "") if isinstance(m.get("sequence"), str) else "")
         moving = style is not None and style not in battle.still_motions()
         w["style"].setEnabled(on)
         w["frames"].setEnabled(on and moving and style != "sequence")
         w["from"].setEnabled(on and style == "slide")
         if "when" in w:
            w["when"].setEnabled(on and style != "stay")
         for k in ("sequence", "choose"):
            w[k].setEnabled(on and style == "sequence")
      for key, edit in self.texts.items():
         v = e.get(key)
         if edit.text() != (v or "") or not edit.hasFocus():
            edit.setText(v if isinstance(v, str) else "")
         edit.setEnabled(on)
         self._check_text(key)
      for w in (self.sprite, self.dx, self.dy, self.returns):
         w.setEnabled(on)
      self._fill_used_by()
      self._fill_preview_choices()
      self.update_preview()

   def _fill_used_by(self) -> None:
      """!Which parties show the presenter.
      @return None
      """
      doc = self.battle_doc()
      if doc is None or self.selected is None:
         self.used_by.setText("")
         return
      parties = self.showing_parties()
      word = self.word("party", True)
      self.used_by.setText(f"Shown by: {', '.join(parties)}" if parties else f"No {word.lower()} show it yet "
                           f"(attach it on the {word} tab).")

   def showing_parties(self) -> list[str]:
      """!The parties that show the selected presenter.
      @return party names
      """
      doc = self.battle_doc()
      return [t.get("name") for t in (doc.data.get("parties") or []) if isinstance(t, dict)
              and self.selected in (t.get("presenters") or [])] if doc is not None else []

   def _check_text(self, key: str) -> None:
      """!Checks one text field as it is typed and shows how it reads.
      @param key  "intro", "defeat" or "victory"
      @return None
      """
      doc = self.battle_doc()
      note = self.text_notes[key]
      text = self.texts[key].text()
      if doc is None or not text:
         note.setText("")
         return
      try:
         problems = text_problems(doc, self.code_page(), text)
      except engine.EngineNotFound as e:
         problems = [str(e)]
      if problems:
         note.setText("\n".join(problems))
         note.setStyleSheet("color: #c03030;")
         return
      parties = self.showing_parties()
      try:
         shown = battle.presenter_text(doc, text, parties[0] if parties else NO_PARTY)
      except DocumentError as e:
         shown = str(e)
      note.setText(f"Reads: {shown}")
      note.setStyleSheet("color: #607080;")

   # -- edits -----------------------------------------------------------------------------

   def _at_changed(self) -> None:
      """!The offset changed.
      @return None
      """
      at = [self.dx.value(), self.dy.value()]
      self.set_field("at", None if at == [0, 0] else at, "Set offset")

   def _text_changed(self, key: str) -> None:
      """!A text field was left: its text is written (empty removes it).
      @param key  "intro", "defeat" or "victory"
      @return None
      """
      self.set_field(key, self.texts[key].text() or None, f"Set {key} text")

   def _motion_changed(self, kind: str, key: str, value: object) -> None:
      """!One field of the entrance or exit changed; fields the style does not take are dropped.
      @param kind   "enter" or "exit"
      @param key    "style", "frames", "from", "when" or "sequence"
      @param value  new value (None removes the field)
      @return None
      """
      e = self.current()
      if e is None or self._filling:
         return
      m = dict(e.get(kind)) if isinstance(e.get(kind), dict) else {}
      if value is None:
         m.pop(key, None)
      else:
         m[key] = value
      style = m.get("style")
      if style in battle.still_motions():   # still: no frames, edge or sequence
         for k in ("frames", "from", "sequence"):
            m.pop(k, None)
      if style != "sequence":
         m.pop("sequence", None)
      if style != "slide":
         m.pop("from", None)
      if style == "stay":
         m.pop("when", None)
      self.set_field(kind, m or None, "Set " + ("entrance" if kind == "enter" else "exit"))

   def choose_sequence(self, kind: str) -> None:
      """!Picks a sequence file for the entrance or exit.
      @param kind  "enter" or "exit"
      @return None
      """
      doc = self.battle_doc()
      if doc is None or self.selected is None:
         return
      base = doc.path.parent
      path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Presenter sequence", str(base),
                                                      "Sequences (*.json);;All files (*)")
      if path:
         try:
            rel = paths.relative(path, base)
         except DocumentError as e:   # another drive (Windows)
            QtWidgets.QMessageBox.warning(self, "Presenter sequence", str(e))
            return
         self._motion_changed(kind, "sequence", rel)

   # -- preview ---------------------------------------------------------------------------

   def _fill_preview_choices(self) -> None:
      """!The formats and sides the preview offers.
      @return None
      """
      p = self.project()
      compiled = p.compile()[0] if p is not None else None
      names = compiled["names"]["formats"] if compiled is not None else []
      keep = self.preview_format.currentText()
      set_combo(self.preview_format, names, keep if keep in names else (names[0] if names else None))

   def _format(self, compiled: JsonDict) -> JsonDict | None:
      """!The compiled format the preview shows.
      @param compiled  compile result
      @return the format, or None
      """
      names = compiled["names"]["formats"]
      name = self.preview_format.currentText()
      return compiled["formats"][names.index(name)] if name in names else None

   def update_preview(self) -> None:
      """!Builds the frames for the chosen format, side and cues and shows the first.
      @return None
      """
      self.timer.stop()
      self.frames, self.frame_index = [], 0
      p = self.project()
      compiled, error = p.compile() if p is not None else (None, None)
      fd = self._format(compiled) if compiled is not None else None
      if compiled is None or fd is None or self.selected is None:
         self.preview.set_layout(battle.screen_size(), [], [], battle.blend_max())
         self.preview.set_sprite(None, f"(no preview: {error})" if error else "")
         return
      self.preview_side.blockSignals(True)
      self.preview_side.setRange(0, fd["sides"] - 1)
      self.preview_side.blockSignals(False)
      side = self.preview_side.value()
      battlers = [(fd["x"][i], fd["y"][i]) for i in range(fd["positions"])]
      stands = [(fd["stand_x"][s], fd["stand_y"][s]) for s in range(fd["sides"])]
      self.preview.set_layout(battle.screen_size(), battlers, stands, battle.blend_max())
      sprite = (self.current() or {}).get("sprite")
      known = self.sprites().get(sprite)
      size = known or UNKNOWN_SIZE
      note = "" if known or not sprite else f"  ({sprite} is not in the game's assets: size guessed)"
      cues = PREVIEW_CUES.get(self.preview_cue.currentText(), PREVIEW_CUES["Enter"])
      for cue in cues:
         track = battle.presenter_track(compiled, self.selected, self.preview_format.currentText(), side, cue,
                                        size)
         for frame, x, y, weight in track:
            self.frames.append((x, y, size[0], size[1], weight, f"{cue} {frame}/{track[-1][0]}{note}"))
         # Hold the end state a while (between cues and at the end).
         self.frames += [self.frames[-1]] * HOLD_FRAMES
      self._show_frame()

   def _show_frame(self) -> None:
      """!Draws the current frame.
      @return None
      """
      if not self.frames:
         self.preview.set_sprite(None)
         return
      x, y, w, h, weight, caption = self.frames[min(self.frame_index, len(self.frames) - 1)]
      self.preview.set_sprite((x, y, w, h, weight), caption)

   def play(self) -> None:
      """!Plays the motion from its first frame.
      @return None
      """
      self.update_preview()
      if self.frames:
         self.timer.start()

   def _tick(self) -> None:
      """!Shows the next frame; stops at the last.
      @return None
      """
      self.frame_index += 1
      if self.frame_index >= len(self.frames):
         self.timer.stop()
         return
      self._show_frame()

   def stop(self) -> None:
      """!Stops the preview (another tab, closing).
      @return None
      """
      self.timer.stop()
