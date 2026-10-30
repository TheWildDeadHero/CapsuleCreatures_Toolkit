"""!Menu styles panel [S5] (engine N3: a text box style's "menu", ui::MenuStyle in capsule/ui/menu.h): how a menu
drawn in a style's window looks and behaves, with a live preview that runs the menu frame by frame as the engine's
ui module does (core.menu_styles: keys.cpp's repeat counter, menu.cpp's moves, wrap, delay, sounds and order,
arrows.cpp's bounce).

Left: the manifest's text box styles (those with a menu marked), Give menu / Remove menu. Middle: one editor per
menu setting the engine's compiler takes, in MenuStyle's order with menu.h's comments as tips (numbers in the
compiler's ranges, words as combos, the cancel keys as check boxes, the arrow sprite's asset key). Right: the
preview: the kind of menu (a column, a grid, a scrolling list with its arrows, a yes / no box), its options (one
per line; a line `text:KEY` shows that text of the manifest's tables, e.g. a multichoice's options), the grid's
columns, the list's rows shown, the first cursor, whether cancel answers, the window fitted to the options, the
pad's repeat timing (start / every frames: a game's ui::Repeat), and the keys pressed (a key script: `down`,
`down*40` held 40 frames, `wait 10`; the key buttons add to it). The frame slider and Play show the run; the line
above the picture says what happened (sounds, the answer). The arrows are drawn as stand-ins (triangles), not the
style's arrow sprite.

Every change is one undo step of the manifest (host.run_edit()); the preview's settings are the style's editor data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ...core import menu_styles, text_boxes
from ...core.document import DocumentError
from ..panel import EditorPanel
from ..qtimage import to_qimage
from ..widgets import PixelView, button, set_enabled
from .text_common import session_of

if TYPE_CHECKING:
   from ..panel import PanelHost
   from .text_common import TextSession

## Screen pixels per preview pixel.
PREVIEW_ZOOM = 2
## Milliseconds between preview frames while playing (the GBA's 60 frames a second, rounded).
FRAME_MS = 16
## The mark of a style with a menu in the list.
MENU_MARK = "  (menu)"
## Stretch of the list, the form and the preview.
LIST_STRETCH, FORM_STRETCH, PREVIEW_STRETCH = 1, 2, 3
## Fields per row of the form's grid.
FIELDS_PER_ROW = 2
## Columns per field in the form's grid (label, editor).
FORM_COLUMNS = 2
## Key check boxes per row (cancel keys).
KEYS_PER_ROW = 6
## The key buttons that add to the script: (label, script word).
KEY_BUTTONS = (("Up", "up"), ("Down", "down"), ("Left", "left"), ("Right", "right"), ("A", "a"), ("B", "b"),
               ("Start", "start"))
## Highest repeat / grid / list number the preview's spins offer (a byte).
SPIN_BYTE = 255
## Rows the options box shows.
ITEM_ROWS = 6
## Frames "Hold down" holds Down (a second at 60 frames a second: past the default repeat's start).
HOLD_FRAMES = 60
## Colour of the engine's refusals.
ERROR_COLOR = "#c03030"


class MenuStylePanel(EditorPanel):
   """!Edits the menus of the host's text box styles and previews them."""

   ## See EditorPanel.panel_id.
   panel_id = "menu_styles"
   ## See EditorPanel.title.
   title = "Menu styles"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The style shown (its key), or None.
      self.key = None
      ## True while the panel fills its widgets.
      self._filling = False
      ## The preview's run (core.menu_styles.MenuRun) and what it was run from, or None.
      self._run = None
      ## The styles.
      self.list = QtWidgets.QListWidget()
      self.list.currentItemChanged.connect(lambda item, _old: self._chosen(item))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Text box styles"))
      left.addWidget(self.list, 1)
      left.addWidget(button("Give menu", lambda: self.set_menu(True), "The style gets a menu (every setting at "
                                                                       "its default)"))
      left.addWidget(button("Remove menu", lambda: self.set_menu(False), "The style's menu is taken out"))
      ## Editors by menu setting.
      self.editors = {}
      ## The cancel keys' check boxes by key name.
      self.cancel_boxes = {}
      form = QtWidgets.QVBoxLayout()
      fields = menu_styles.menu_fields()
      if not fields:
         form.addWidget(QtWidgets.QLabel("The engine has no menu styles (they came with engine N3)."))
      box = QtWidgets.QGroupBox("Menu (ui::MenuStyle)")
      grid = QtWidgets.QGridLayout(box)
      row = 0
      placed = 0
      for f in fields:
         if f.kind == "keys":
            continue
         editor = self._editor(f)
         self.editors[f.name] = editor
         r, c = divmod(placed, FIELDS_PER_ROW)
         label = QtWidgets.QLabel(f.name)
         label.setToolTip(editor.toolTip())
         grid.addWidget(label, r, c * FORM_COLUMNS)
         grid.addWidget(editor, r, c * FORM_COLUMNS + 1)
         placed += 1
         row = r + 1
      cancel = next((f for f in fields if f.kind == "keys"), None)
      if cancel is not None:
         keys = QtWidgets.QGroupBox(f"{cancel.name}: {cancel.doc}")
         kgrid = QtWidgets.QGridLayout(keys)
         for i, name in enumerate(cancel.words):
            b = QtWidgets.QCheckBox(name)
            b.clicked.connect(lambda _on: self._cancel_changed())
            self.cancel_boxes[name] = b
            kgrid.addWidget(b, i // KEYS_PER_ROW, i % KEYS_PER_ROW)
         grid.addWidget(keys, row, 0, 1, FIELDS_PER_ROW * FORM_COLUMNS)
      form.addWidget(box)
      ## What the engine refuses or draws wrongly.
      self.checks = QtWidgets.QLabel()
      self.checks.setWordWrap(True)
      form.addWidget(self.checks)
      form.addStretch(1)
      right = self._build_preview()
      layout = QtWidgets.QHBoxLayout(self)
      form_holder = QtWidgets.QWidget()
      form_holder.setLayout(form)
      scroll = QtWidgets.QScrollArea()
      scroll.setWidget(form_holder)
      scroll.setWidgetResizable(True)
      for part, stretch in ((left, LIST_STRETCH), (scroll, FORM_STRETCH), (right, PREVIEW_STRETCH)):
         if isinstance(part, QtWidgets.QLayout):
            holder = QtWidgets.QWidget()
            holder.setLayout(part)
            part = holder
         layout.addWidget(part, stretch)

   def _editor(self, f: menu_styles.MenuField) -> QtWidgets.QWidget:
      """!The editor of one menu setting: a combo for a word, a line for the sprite key, else a spin in the
      compiler's range.
      @param f  the field
      @return the widget
      """
      tip = f"menu.{f.name}: {f.doc}" if f.doc else f"menu.{f.name}"
      if f.kind == "word":
         combo = QtWidgets.QComboBox()
         combo.addItems(f.words)
         combo.setToolTip(tip)
         combo.activated.connect(lambda _i, n=f.name: self._changed(n))
         return combo
      if f.kind == "sprite":
         line = QtWidgets.QLineEdit()
         line.setPlaceholderText("(none: no arrows)")
         line.setToolTip(f"{tip} (a sprite asset: sprite:NAME)")
         line.editingFinished.connect(lambda n=f.name: self._changed(n))
         return line
      spin = QtWidgets.QSpinBox()
      low = f.low - 1 if f.default is None else f.low   # an optional setting's lowest value means left out
      spin.setRange(low, f.high)
      if f.default is None:
         spin.setSpecialValueText("(none)")
      spin.setToolTip(f"{tip} ({f.low}-{f.high})")
      spin.editingFinished.connect(lambda n=f.name: self._changed(n))
      return spin

   def _build_preview(self) -> QtWidgets.QVBoxLayout:
      """!The preview's settings, key buttons, frame slider and picture.
      @return the layout
      """
      ## The kind of menu.
      self.kind = QtWidgets.QComboBox()
      self.kind.addItems(menu_styles.KINDS)
      self.kind.activated.connect(lambda _i: self._preview_set("kind", self.kind.currentText()))
      ## The options, one per line.
      self.items = QtWidgets.QPlainTextEdit()
      self.items.setPlaceholderText("one option per line; text:KEY shows a text of the manifest's tables")
      self.items.setMaximumHeight(self.fontMetrics().height() * ITEM_ROWS)
      self.items.setToolTip("The menu's options (the caller's, ui::Options::items): a line is a text, or text:KEY "
                            "for that text of the manifest's tables")
      ## Applies the options.
      self.items_button = button("Set options", lambda: self.set_items(self.items.toPlainText().splitlines()))
      ## Grid columns.
      self.columns = QtWidgets.QSpinBox()
      self.columns.setRange(1, SPIN_BYTE)
      self.columns.editingFinished.connect(lambda: self._preview_set("columns", self.columns.value()))
      ## List rows shown.
      self.shown = QtWidgets.QSpinBox()
      self.shown.setRange(0, SPIN_BYTE)
      self.shown.editingFinished.connect(lambda: self._preview_set("shown", self.shown.value()))
      ## The first cursor.
      self.cursor = QtWidgets.QSpinBox()
      self.cursor.setRange(0, SPIN_BYTE)
      self.cursor.editingFinished.connect(lambda: self._preview_set("cursor", self.cursor.value()))
      ## Cancel answers.
      self.cancel = QtWidgets.QCheckBox("cancel answers")
      self.cancel.clicked.connect(lambda on: self._preview_set("cancel", on))
      ## The window fitted to the options.
      self.fit = QtWidgets.QCheckBox("fit window")
      self.fit.setToolTip("Size the window to the options (a game sizes a menu box per menu); off: the style's")
      self.fit.clicked.connect(lambda on: self._preview_set("fit", on))
      ## The pad's repeat: frames before the first repeat, between repeats.
      self.repeat = [QtWidgets.QSpinBox(), QtWidgets.QSpinBox()]
      for spin in self.repeat:
         spin.setRange(0, SPIN_BYTE)
         spin.editingFinished.connect(lambda: self._preview_set("repeat", [s.value() for s in self.repeat]))
      self.repeat[0].setToolTip("ui::Repeat::start: frames the same keys are held before the first repeat (0: none)")
      self.repeat[1].setToolTip("ui::Repeat::every: frames between repeats after that")
      ## The key script.
      self.script = QtWidgets.QLineEdit()
      self.script.setToolTip("Keys, one word per press: up, down, left, right, a, b, start, select, l, r; KEY*n holds "
                             "it n frames; wait n waits; KEY+KEY together")
      self.script.editingFinished.connect(lambda: self._preview_set("script", self.script.text()))
      ## The frame shown.
      self.frame = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
      self.frame.valueChanged.connect(lambda _v: self._draw())
      ## The frame's number.
      self.frame_label = QtWidgets.QLabel()
      ## Plays the run.
      self.timer = QtCore.QTimer(self)
      self.timer.setInterval(FRAME_MS)
      self.timer.timeout.connect(lambda: self._tick())
      ## What happened.
      self.summary = QtWidgets.QLabel()
      self.summary.setWordWrap(True)
      ## The picture.
      self.view = PixelView(PREVIEW_ZOOM)
      right = QtWidgets.QVBoxLayout()
      top = QtWidgets.QHBoxLayout()
      top.addWidget(QtWidgets.QLabel("Kind"))
      top.addWidget(self.kind)
      top.addWidget(QtWidgets.QLabel("Columns"))
      top.addWidget(self.columns)
      top.addWidget(QtWidgets.QLabel("Rows shown"))
      top.addWidget(self.shown)
      top.addWidget(QtWidgets.QLabel("Cursor"))
      top.addWidget(self.cursor)
      top.addWidget(self.cancel)
      top.addWidget(self.fit)
      right.addLayout(top)
      irow = QtWidgets.QHBoxLayout()
      irow.addWidget(self.items, 1)
      irow.addWidget(self.items_button)
      right.addLayout(irow)
      krow = QtWidgets.QHBoxLayout()
      krow.addWidget(QtWidgets.QLabel("Repeat (start, every)"))
      for spin in self.repeat:
         krow.addWidget(spin)
      krow.addWidget(QtWidgets.QLabel("Keys"))
      krow.addWidget(self.script, 1)
      right.addLayout(krow)
      brow = QtWidgets.QHBoxLayout()
      for label, word in KEY_BUTTONS:
         brow.addWidget(button(label, lambda w=word: self.add_key(w), f"Press {label} (adds `{word}` to the keys)"))
      brow.addWidget(button("Hold down", lambda: self.add_key(f"down{menu_styles.HOLD_MARK}{HOLD_FRAMES}"),
                            "Hold Down long enough to see the repeat"))
      brow.addWidget(button("Clear", lambda: self._preview_set("script", "")))
      right.addLayout(brow)
      trow = QtWidgets.QHBoxLayout()
      trow.addWidget(QtWidgets.QLabel("Frame"))
      trow.addWidget(self.frame, 1)
      trow.addWidget(self.frame_label)
      trow.addWidget(button("Play", lambda: self.play(), "Run the menu at the GBA's frame rate"))
      trow.addWidget(button("Stop", lambda: self.timer.stop()))
      right.addLayout(trow)
      right.addWidget(self.summary)
      right.addWidget(self.view, 1)
      return right

   # -- filling ---------------------------------------------------------------------------------------------------

   def session(self) -> TextSession | None:
      """!The host's text session.
      @return TextSession, or None
      """
      host = self.host   # a local alias (Doxygen reads `self.x` returned here as a new member)
      return session_of(host)

   def style(self) -> dict[str, Any] | None:
      """!The style shown.
      @return it, or None
      """
      doc, key = self.doc, self.key   # local aliases (see session())
      if key is None:
         return None
      try:
         return text_boxes.find(doc, key)
      except DocumentError:
         return None

   def document_replaced(self) -> None:
      """!Another manifest.
      @return None
      """
      self.key = None
      self.refresh()

   def refresh(self) -> None:
      """!Re-reads the styles and the style shown.
      @return None
      """
      styles = text_boxes.styles(self.doc)
      keys = [str(s.get("key")) for s in styles]
      if self.key not in keys:
         with_menu = [str(s.get("key")) for s in styles if menu_styles.has_menu(s)]
         self.key = (with_menu or keys or [None])[0]
      self._filling = True
      try:
         self.list.clear()
         for s in styles:
            item = QtWidgets.QListWidgetItem(str(s.get("key")) + (MENU_MARK if menu_styles.has_menu(s) else ""))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(s.get("key")))
            self.list.addItem(item)
         if self.key is not None:
            self.list.setCurrentRow(keys.index(self.key))
      finally:
         self._filling = False
      self._fill_style()

   def _fill_style(self) -> None:
      """!Shows the style's menu settings and the preview's.
      @return None
      """
      style = self.style()
      on = style is not None and menu_styles.has_menu(style)
      self._filling = True
      try:
         for name, w in self.editors.items():
            w.setEnabled(on)
            v = menu_styles.value(style, name) if style is not None else None
            if isinstance(w, QtWidgets.QComboBox):
               w.setCurrentText(str(v))
            elif isinstance(w, QtWidgets.QLineEdit):
               w.setText(str(v or ""))
            else:
               w.setValue(w.minimum() if v is None else int(v))
         chosen = menu_styles.value(style, menu_styles.CANCEL_FIELD) if style is not None else []
         for name, b in self.cancel_boxes.items():
            b.setEnabled(on)
            b.setChecked(name in (chosen or []))
         p = menu_styles.preview_data(style) if style is not None else menu_styles.preview_data({})
         self.kind.setCurrentText(str(p.get("kind")))
         self.items.setPlainText("\n".join(str(t) for t in p.get("items", [])))
         self.columns.setValue(int(p.get("columns", 1)))
         self.shown.setValue(int(p.get("shown", 0)))
         self.cursor.setValue(int(p.get("cursor", 0)))
         self.cancel.setChecked(bool(p.get("cancel", True)))
         width = text_boxes.number(style, "window", "width") if style is not None else 0
         height = text_boxes.number(style, "window", "height") if style is not None else 0
         self.fit.setChecked(bool(p.get("fit", width * height <= 1)))
         for spin, v in zip(self.repeat, p.get("repeat", menu_styles.DEFAULT_REPEAT)):
            spin.setValue(int(v))
         self.script.setText(str(p.get("script", "")))
         for w in (self.kind, self.items, self.items_button, self.columns, self.shown, self.cursor, self.cancel,
                   self.fit, self.script, *self.repeat):
            set_enabled(w, on)   # the items box goes read-only and keeps its scroll bar
      finally:
         self._filling = False
      self._update_preview()

   def _compiled_font(self, style: dict[str, Any]) -> dict | None:
      """!The style's font compiled (the session's context: the game's code page).
      @param style  the style
      @return compile_proportional()'s result, or None
      """
      s = self.session()
      key = style.get("font")
      path = dict(s.font_refs()).get(key) if s is not None and key else None
      if path is None:
         return None
      try:
         return s.context.font(path)
      except DocumentError as e:
         self.host.show_status(str(e))
         return None

   def item_codes(self, lines: list[str]) -> list[list[int]]:
      """!The options' codes: a `text:KEY` line is that text of the manifest's tables (the table named after the
      key's first part first), any other line its own text.
      @param lines  the options
      @return codes per option
      @throws DocumentError for a text the code page cannot encode
      """
      s = self.session()
      if s is None:
         return []
      out = []
      refs = s.table_refs()
      for line in lines:
         text = line
         if line.startswith("text:"):
            stem = line[len("text:"):].split(".")[0]
            for ref in sorted(refs, key=lambda r: Path(r.path).stem != stem):
               try:
                  table = s.table(ref.path)
               except DocumentError:
                  continue
               entry = (table.data.get("texts") or {}).get(line)
               if entry is not None:
                  text = entry.get("text", "") if isinstance(entry, dict) else str(entry)
                  break
         out.append(s.context.encode(text, "menu option"))
      return out

   def _update_preview(self) -> None:
      """!Checks the style, runs its menu and draws the frame chosen.
      @return None
      """
      style = self.style()
      if style is None or not menu_styles.has_menu(style):
         self.view.set_image(None)
         self.checks.setText("No style: add one on the Text boxes tab." if style is None else
                             "This style has no menu: Give menu.")
         self.checks.setStyleSheet("")
         self.summary.setText("")
         self._forget_run()
         return
      font = self._compiled_font(style)
      self._show_checks(style, font)
      if font is None:
         self.summary.setText("No preview: the style's font is no font of this manifest.")
         self._forget_run()
         self.view.set_image(None)
         return
      p = menu_styles.preview_data(style)
      lines = list(p.get("items") or [])
      if p.get("kind") == "yes_no" and not lines:
         lines = list(menu_styles.YES_NO_ITEMS)
      stamp = json.dumps(style, sort_keys=True)
      if self._run is None or self._run[0] != stamp:
         try:
            items = self.item_codes(lines)
            run = menu_styles.run(style, font, items, base=self.doc.base_dir)
         except DocumentError as e:
            self.summary.setText(str(e))
            self._forget_run()
            self.view.set_image(None)
            return
         self._run = (stamp, run)
         self._filling = True
         self.frame.setRange(0, len(run.frames) - 1)
         self.frame.setValue(len(run.frames) - 1)
         self._filling = False
      self._show_checks(self._run[1].style, font)   # the window the menu opened in (fitted to its options)
      self.summary.setText(menu_styles.describe(self._run[1]))
      self._draw()

   def _show_checks(self, style: dict[str, Any], font: dict | None) -> None:
      """!What the engine refuses or draws wrongly with the style (its window as the preview opens it).
      @param style  the style, or the preview's copy with the fitted window
      @param font   its compiled font, or None
      @return None
      """
      problems = text_boxes.check(style, font, None, self.doc.base_dir)
      self.checks.setText("\n".join(problems) if problems else "The engine draws this menu as shown.")
      self.checks.setStyleSheet(f"color: {ERROR_COLOR};" if any(p.startswith("error") for p in problems) else "")

   def _forget_run(self) -> None:
      """!The preview's run is out of date (run again on the next update).
      @return None
      """
      self._run = None

   def _draw(self) -> None:
      """!Draws the frame the slider shows.
      @return None
      """
      if self._run is None:
         return
      run = self._run[1]
      n = self.frame.value()
      self.frame_label.setText(f"{n} / {self.frame.maximum()} (cursor {run.cursors[run.frame_at(n)]})")
      canvas = menu_styles.preview(run, n, self.doc.base_dir)
      self.view.set_image(to_qimage(*canvas.image()))

   def play(self) -> None:
      """!Runs the menu from its first frame at the GBA's frame rate.
      @return None
      """
      self.frame.setValue(0)
      self.timer.start()

   def _tick(self) -> None:
      """!One frame of playing.
      @return None
      """
      if self.frame.value() >= self.frame.maximum():
         self.timer.stop()
         return
      self.frame.setValue(self.frame.value() + 1)

   def stop(self) -> None:
      """!Stops playing.
      @return None
      """
      self.timer.stop()

   # -- edits ------------------------------------------------------------------------------------------------------

   def _chosen(self, item: QtWidgets.QListWidgetItem | None) -> None:
      """!Another style.
      @param item  its list item
      @return None
      """
      if self._filling or item is None:
         return
      self.key = item.data(QtCore.Qt.ItemDataRole.UserRole)
      self._forget_run()
      self._fill_style()

   def set_menu(self, on: bool) -> bool:
      """!Gives the style shown a menu or takes it away.
      @param on  give it one
      @return True when it went through
      """
      doc, key = self.doc, self.key
      if key is None:
         return False
      return self.host.run_edit("Menu" if on else "Remove menu", lambda: menu_styles.set_menu(doc, key, on))

   def set_value(self, name: str, v: Any) -> bool:
      """!Changes one menu setting of the style shown.
      @param name  the member
      @param v     its value (None: left out)
      @return True when it went through
      """
      doc, key = self.doc, self.key
      if key is None:
         return False
      return self.host.run_edit(f"menu {name}", lambda: menu_styles.set_value(doc, key, name, v))

   def _changed(self, name: str) -> None:
      """!A setting's editor changed.
      @param name  the member
      @return None
      """
      style = self.style()
      if self._filling or style is None:
         return
      w = self.editors[name]
      if isinstance(w, QtWidgets.QComboBox):
         v: Any = w.currentText()
      elif isinstance(w, QtWidgets.QLineEdit):
         v = w.text().strip() or None
      else:
         f = menu_styles.field_of(name)
         v = None if f is not None and f.default is None and w.value() == w.minimum() else w.value()
      if menu_styles.value(style, name) != v:
         self.set_value(name, v)

   def _cancel_changed(self) -> None:
      """!A cancel key's box changed.
      @return None
      """
      if not self._filling:
         self.set_value(menu_styles.CANCEL_FIELD, [n for n, b in self.cancel_boxes.items() if b.isChecked()])

   def _preview_set(self, name: str, v: Any) -> bool:
      """!Changes one preview setting of the style shown (its editor data).
      @param name  the setting (core.menu_styles.PREVIEW_SETTINGS)
      @param v     its value
      @return True when it went through
      """
      doc, key = self.doc, self.key
      if self._filling or key is None:
         return False
      return self.host.run_edit(f"Menu preview {name}", lambda: menu_styles.set_preview(doc, key, name, v))

   def set_items(self, lines: list[str]) -> bool:
      """!The preview's options.
      @param lines  one option per line (empty lines left out)
      @return True when it went through
      """
      return self._preview_set("items", [t for t in (line.strip() for line in lines) if t])

   def add_key(self, word: str) -> bool:
      """!Adds a key to the preview's script.
      @param word  a script word
      @return True when it went through
      """
      style = self.style()
      if style is None:
         return False
      script = str(menu_styles.preview_data(style).get("script", ""))
      return self._preview_set("script", f"{script} {word}".strip())
