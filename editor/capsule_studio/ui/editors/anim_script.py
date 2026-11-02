"""![S8] Animation-script viewer and stepper (M5, D-38): a bank's scripts, their commands and a timeline of what
runs on which frame, as the engine's player runs them (core/anim_script.py).

Left: the bank (Open bank..., or the engine sandbox's simple-shape sample) and its scripts. Middle: the frame bar,
the script's commands (the commands run on the frame shown are marked; the next one has an arrow) and the timeline:
one lane each for sprites, visual tasks, sound, background (layers, scroll, colour effects, graphics), control and
the game's own commands; the visuals as bars from the frame they were made to the frame their step finished them.
Click the timeline to show a frame. Right: the player on that frame (mode, frames to wait, arguments, call stack,
counts) and the settings the player leaves to the game: how long each symbol's visuals live, how long a sound keeps
wait_sound waiting, and the frame limit. A change runs the script again at once.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import anim_script as core
from ...core import engine
from ..panel import EditorPanel
from ..panes import NARROW, WIDE, mark_panel, pane, splitter
from ..widgets import button
from .anim_common import FrameBar

if TYPE_CHECKING:
   from ..panel import PanelHost

## File dialog filter for banks.
BANK_FILTER = "Animation banks (*.canim *.canm *.bin);;All files (*)"
## What opening a bank may raise.
OPEN_ERRORS = (core.ScriptError, engine.EngineNotFound, OSError)

## Listing columns: label, address, command, operands, lane.
LISTING_COLUMNS = ("Label", "Address", "Command", "Operands", "Lane")
## Listing column of the label (script names; the arrow at the next command).
LABEL_COLUMN = 0
## Listing column of the address.
ADDRESS_COLUMN = 1
## Listing column of the command.
COMMAND_COLUMN = 2
## Listing column of the operands.
OPERANDS_COLUMN = 3
## Listing column of the lane.
LANE_COLUMN = 4
## Marker of the next command in the label column.
NEXT_MARK = "▶ "
## Background of a listing row run on the frame shown.
RAN_COLOR = QtGui.QColor(255, 236, 160)

## Lifetime columns: symbol, kind, frames, argument, offset.
LIFE_COLUMNS = ("Symbol", "Kind", "Frames", "From argument", "Offset")
## Lifetime column of the symbol.
SYMBOL_COLUMN = 0
## Lifetime column of the kind.
KIND_COLUMN = 1
## Lifetime column of the frames.
FRAMES_COLUMN = 2
## Lifetime column of the argument slot ("" for none).
ARG_COLUMN = 3
## Lifetime column of the offset.
OFFSET_COLUMN = 4
## Kinds whose symbols make visuals (anim_bank KINDS index -> the lifetime table's text).
VISUAL_KINDS = {core.KIND_TEMPLATE: "sprite", core.KIND_TASK: "visual task", core.KIND_SOUND_TASK: "sound task"}
## Largest frame count the settings take.
MAX_SETTING_FRAMES = 10000

## Timeline geometry, pixels: the lane label column, a frame's width, a row's height, the ruler's height.
LABEL_WIDTH = 72
## A frame's width on the timeline, pixels.
FRAME_WIDTH = 6
## A timeline row's height, pixels.
ROW_HEIGHT = 14
## The ruler's height, pixels.
RULER_HEIGHT = 16
## Frames between two ruler numbers.
RULER_STEP = 10
## Lane colours (bars and ticks), by lane.
LANE_COLORS = {
   "sprites": QtGui.QColor(64, 128, 224), "tasks": QtGui.QColor(48, 168, 96), "sound": QtGui.QColor(200, 120, 32),
   "bg": QtGui.QColor(144, 80, 192), "control": QtGui.QColor(110, 110, 110), "game": QtGui.QColor(200, 56, 56),
}
## Colour of the frame cursor.
CURSOR_COLOR = QtGui.QColor(220, 0, 0)
## Colour of a frame with a player error.
ERROR_COLOR = QtGui.QColor(192, 48, 48)
## Halves (centring).
HALF = 2

## Layout stretch of the left, middle and right panes.
LEFT_STRETCH = NARROW
## Layout stretch of the middle pane.
MIDDLE_STRETCH = WIDE
## Layout stretch of the right pane.
RIGHT_STRETCH = NARROW
## Starting widths of the left and right panes, pixels.
LEFT_WIDTH = 200
## Starting width of the right pane, pixels.
RIGHT_WIDTH = 300


class Timeline(QtWidgets.QWidget):
   """!The timeline's canvas (inside a scroll area): lanes by frames, visuals as bars, commands as ticks.

   @var stepper
   The core Stepper shown, or None.
   @var frame
   The frame the cursor is on.
   @var picked
   Called with a frame when the canvas is clicked.
   """

   def __init__(self, picked: Any) -> None:
      """!An empty timeline.
      @param picked  callable(frame)
      """
      super().__init__()
      self.stepper: core.Stepper | None = None
      self.frame = 0
      self.picked = picked
      ## The rows, top to bottom: (lane, row in the lane).
      self._rows = list[tuple[str, int]]()
      ## The row of each visual (its index in the run): (lane, row in the lane).
      self._slots = dict[int, tuple[str, int]]()
      self.setToolTip("Click a frame to show it")

   def set_stepper(self, stepper: core.Stepper | None) -> None:
      """!Shows a run: each lane gets as many rows as its visuals overlap (one at least).
      @param stepper  the run, or None
      @return None
      """
      self.stepper = stepper
      self._rows.clear()
      self._slots.clear()
      for lane in core.LANES:
         ends: list[int] = []   # per row of this lane: the frame its last bar ends
         for i, v in enumerate(stepper.visuals if stepper else []):
            if v.lane != lane:
               continue
            end = v.finished if v.finished is not None else len(stepper.states)
            row = next((r for r, e in enumerate(ends) if e <= v.made), len(ends))
            if row == len(ends):
               ends.append(end)
            else:
               ends[row] = end
            self._slots[i] = (lane, row)
         for r in range(max(1, len(ends))):
            self._rows.append((lane, r))
      self.updateGeometry()
      self.adjustSize()
      self.update()

   def set_frame(self, frame: int) -> None:
      """!Moves the cursor.
      @param frame  the frame
      @return None
      """
      self.frame = frame
      self.update()

   def frames(self) -> int:
      """!Frames shown (frame 0 to the last state).
      @return count
      """
      return len(self.stepper.states) if self.stepper else 1

   def row_y(self, lane: str, row: int) -> int:
      """!Top of a lane's row.
      @param lane  the lane
      @param row   its row
      @return y, pixels
      """
      return RULER_HEIGHT + self._rows.index((lane, row)) * ROW_HEIGHT

   def frame_x(self, frame: int) -> int:
      """!Left edge of a frame's column.
      @param frame  the frame
      @return x, pixels
      """
      return LABEL_WIDTH + frame * FRAME_WIDTH

   def sizeHint(self) -> QtCore.QSize:
      """!Every frame and row.
      @return QSize
      """
      return QtCore.QSize(self.frame_x(self.frames()) + FRAME_WIDTH,
                          RULER_HEIGHT + max(1, len(self._rows)) * ROW_HEIGHT + 1)

   def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Shows the frame under the click.
      @param event  QMouseEvent
      @return None
      """
      x = int(event.position().x()) - LABEL_WIDTH
      if x >= 0 and self.stepper is not None:
         self.picked(min(self.frames() - 1, x // FRAME_WIDTH))

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the ruler, the lanes, the bars, the ticks and the cursor.
      @param event  QPaintEvent
      @return None
      """
      p = QtGui.QPainter(self)
      p.fillRect(self.rect(), self.palette().base())
      text = self.palette().text().color()
      p.setPen(text)
      for f in range(0, self.frames(), RULER_STEP):
         p.drawText(self.frame_x(f), RULER_HEIGHT - HALF, str(f))
      shown: set[str] = set()
      for lane, row in self._rows:
         y = self.row_y(lane, row)
         p.setPen(self.palette().mid().color())
         p.drawLine(0, y, self.width(), y)
         if lane not in shown:
            p.setPen(text)
            p.drawText(QtCore.QRect(0, y, LABEL_WIDTH, ROW_HEIGHT), QtCore.Qt.AlignmentFlag.AlignVCenter, lane)
            shown.add(lane)
      if self.stepper is not None:
         self._paint_run(p)
      p.setPen(CURSOR_COLOR)
      cx = self.frame_x(self.frame) + FRAME_WIDTH // HALF
      p.drawLine(cx, 0, cx, self.height())
      p.end()

   def _paint_run(self, p: QtGui.QPainter) -> None:
      """!The run's bars, ticks and errors.
      @param p  the painter
      @return None
      """
      s = self.stepper
      for i, v in enumerate(s.visuals):
         lane, row = self._slots[i]
         end = v.finished if v.finished is not None else len(s.states)
         r = QtCore.QRect(self.frame_x(v.made), self.row_y(lane, row) + 1, (end - v.made + 1) * FRAME_WIDTH,
                          ROW_HEIGHT - 1)
         p.fillRect(r, LANE_COLORS[lane].lighter())
         p.setPen(LANE_COLORS[lane].darker())
         p.drawRect(r)
         p.drawText(r, QtCore.Qt.AlignmentFlag.AlignVCenter, " " + v.name)
      for e in s.events:
         if (e.lane, 0) not in self._rows or e.lane in ("sprites", "tasks") or e.name == "wait_visual":
            continue   # visuals have their bars; a wait's tick on every frame would hide the others
         y = self.row_y(e.lane, 0)
         p.fillRect(self.frame_x(e.frame) + 1, y + HALF, FRAME_WIDTH - HALF, ROW_HEIGHT - HALF, LANE_COLORS[e.lane])
      for st in s.states:
         if st.error:
            p.fillRect(self.frame_x(st.frame), 0, FRAME_WIDTH, RULER_HEIGHT, ERROR_COLOR)


class AnimScriptPanel(EditorPanel):
   """!The animation-script viewer and stepper (see the module doc).

   @var bank_path
   The bank's file, or None.
   @var bank
   The anim_bank.Bank shown, or None.
   @var commands
   Its commands, in address order.
   @var stepper
   The current run (core.Stepper), or None.
   @var lifetimes
   core.Lifetime by symbol name (the settings).
   """

   ## See EditorPanel.panel_id.
   panel_id = "anim_script"
   ## See EditorPanel.title.
   title = "Anim scripts"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel and shows the engine sandbox's sample when an engine is found.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      self.bank_path: Path | None = None
      self.bank: Any = None
      self.commands: list[Any] = []
      self.stepper: core.Stepper | None = None
      self.lifetimes: dict[str, core.Lifetime] = {}
      ## True while the panel fills its own widgets.
      self._filling = False
      ## The listing's row of each command, by address.
      self._rows = dict[int, int]()

      # left: the bank and its scripts
      left = QtWidgets.QWidget()
      lv = QtWidgets.QVBoxLayout(left)
      ## The bank's file name.
      self.path_label = QtWidgets.QLabel("No bank")
      self.path_label.setWordWrap(True)
      lv.addWidget(self.path_label)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Open bank...", lambda: self.open_bank(), "A .canim text or a bank file"))
      row.addWidget(button("Sample", lambda: self.open_sample(),
                           "The engine sandbox's script (apps/sandbox_anim/data/shapes.canim: simple shapes)"))
      lv.addLayout(row)
      ## The bank's scripts.
      self.scripts = QtWidgets.QListWidget()
      self.scripts.currentRowChanged.connect(lambda r: self._script_chosen(r))
      lv.addWidget(self.scripts, 1)
      ## The bank's problems (the engine reader's check), or the run's error.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)
      lv.addWidget(self.problems)

      # middle: the frame bar, the listing and the timeline
      middle = QtWidgets.QWidget()
      mv = QtWidgets.QVBoxLayout(middle)
      mv.setContentsMargins(0, 0, 0, 0)
      ## The frame chooser.
      self.frame_bar = FrameBar(lambda f: self.show_frame(f))
      mv.addWidget(self.frame_bar)
      ## The script's commands.
      self.listing = QtWidgets.QTableWidget(0, len(LISTING_COLUMNS))
      self.listing.setHorizontalHeaderLabels(list(LISTING_COLUMNS))
      self.listing.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.listing.verticalHeader().setVisible(False)
      self.listing.horizontalHeader().setStretchLastSection(True)
      ## The timeline canvas.
      self.timeline = Timeline(lambda f: self.frame_bar.set_frame(f))
      ## The timeline's scroll area.
      self.timeline_area = QtWidgets.QScrollArea()
      self.timeline_area.setWidget(self.timeline)
      self.timeline_area.setWidgetResizable(False)
      mv.addWidget(splitter(QtCore.Qt.Orientation.Vertical, [self.listing, self.timeline_area], [WIDE, WIDE]), 1)

      # right: the player on the frame shown and the settings
      right = QtWidgets.QWidget()
      rv = QtWidgets.QVBoxLayout(right)
      form = QtWidgets.QFormLayout()
      ## Labels of the player's state, by field.
      self.state_labels: dict[str, QtWidgets.QLabel] = {}
      for key, title in (("mode", "Mode"), ("pc", "Next command"), ("wait", "Frames to wait"),
                         ("counts", "Visuals / sound tasks"), ("args", "Arguments"), ("stack", "Call stack"),
                         ("alive", "Alive"), ("error", "Error")):
         label = QtWidgets.QLabel("-")
         label.setWordWrap(True)
         label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
         self.state_labels[key] = label
         form.addRow(title, label)
      rv.addLayout(form)
      rv.addWidget(QtWidgets.QLabel("How long visuals live (the game's code decides):"))
      ## The lifetimes table.
      self.life_table = QtWidgets.QTableWidget(0, len(LIFE_COLUMNS))
      self.life_table.setHorizontalHeaderLabels(list(LIFE_COLUMNS))
      self.life_table.verticalHeader().setVisible(False)
      self.life_table.itemChanged.connect(lambda it: self._life_edited(it))
      rv.addWidget(self.life_table, 1)
      settings = QtWidgets.QFormLayout()
      ## Frames of a symbol without a row's value.
      self.default_life = self._spin(core.DEFAULT_LIFETIME, 1, "Frames a visual lives when its row says nothing")
      settings.addRow("Default lifetime", self.default_life)
      ## Frames wait_sound waits after each play_se.
      self.sound_busy = self._spin(core.DEFAULT_SOUND_BUSY, 0, "The game's sound_busy hook: frames a sound plays")
      settings.addRow("Sound plays (frames)", self.sound_busy)
      ## The run's frame limit.
      self.max_frames = self._spin(core.DEFAULT_MAX_FRAMES, 1, "Frames run at most")
      settings.addRow("Frame limit", self.max_frames)
      rv.addLayout(settings)

      lay = QtWidgets.QVBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(splitter(QtCore.Qt.Orientation.Horizontal, [pane(left), pane(middle), pane(right)],
                             [LEFT_STRETCH, MIDDLE_STRETCH, RIGHT_STRETCH], [LEFT_WIDTH, None, RIGHT_WIDTH]))
      mark_panel(middle)
      try:
         self.open_sample()
      except OPEN_ERRORS:
         pass   # no engine: the panel waits for a bank

   def _spin(self, value: int, low: int, tip: str) -> QtWidgets.QSpinBox:
      """!A settings field that runs the script again when changed.
      @param value  its value
      @param low    its smallest value
      @param tip    its tooltip
      @return QSpinBox
      """
      s = QtWidgets.QSpinBox()
      s.setRange(low, MAX_SETTING_FRAMES)
      s.setValue(value)
      s.setToolTip(tip)
      s.valueChanged.connect(lambda _v: self.rerun())
      return s

   def stop(self) -> None:
      """!Stops playback.
      @return None
      """
      self.frame_bar.stop()

   # -- the bank ----------------------------------------------------------------------------------------------

   def open_sample(self) -> bool:
      """!Opens the engine sandbox's script with its lifetimes (core.SANDBOX_LIFETIMES).
      @return True when opened
      """
      ok = self.open_bank(str(core.sandbox_bank()))
      if ok:
         self.lifetimes = {k: core.Lifetime(v.frames, v.from_arg, v.offset) for k, v in core.SANDBOX_LIFETIMES.items()}
         self._fill_lifetimes()
         self.rerun()
      return ok

   def open_bank(self, path: str | None = None) -> bool:
      """!Opens a bank (asks for it when no path is given).
      @param path  a .canim text or a bank file, or None to ask
      @return True when opened
      """
      if path is None:
         path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Open animation bank", "", BANK_FILTER)
         if not path:
            return False
      try:
         bank = core.load_bank(path)
         commands = core.listing(bank)
      except OPEN_ERRORS as e:
         self.host.show_status(f"Open bank: {e}")
         return False
      self.bank_path, self.bank, self.commands = Path(path), bank, commands
      self.lifetimes = {}
      self.path_label.setText(self.bank_path.name)
      self.path_label.setToolTip(str(self.bank_path))
      found = core.problems(bank)
      self.problems.setText("\n".join(found) if found else "The engine's check finds no problem.")
      self._fill_listing()
      self._fill_lifetimes()
      self._filling = True
      try:
         self.scripts.clear()
         for name, address in bank.scripts:
            self.scripts.addItem(f"{name or '(unnamed)'}  @{address:#06x}")
      finally:
         self._filling = False
      if bank.scripts:
         self.scripts.setCurrentRow(0)
      self.rerun()
      return True

   def _fill_listing(self) -> None:
      """!The bank's commands, every script's name at its first command.
      @return None
      """
      entries: dict[int, list[str]] = {}
      for name, address in self.bank.scripts:
         entries.setdefault(address, []).append(name)
      self.listing.setRowCount(len(self.commands))
      self._rows.clear()
      for r, c in enumerate(self.commands):
         self._rows[c.address] = r
         lane = core.COMMAND_LANES.get(c.name, "game" if c.op >= core.bank_tool().FIRST_GAME_OPCODE else "control")
         for col, text in ((LABEL_COLUMN, ", ".join(entries.get(c.address, []))),
                           (ADDRESS_COLUMN, f"{c.address:#06x}"), (COMMAND_COLUMN, c.name),
                           (OPERANDS_COLUMN, core.command_text(self.bank, c)), (LANE_COLUMN, lane)):
            self.listing.setItem(r, col, QtWidgets.QTableWidgetItem(text))
      self.listing.resizeColumnsToContents()

   def _fill_lifetimes(self) -> None:
      """!One row per symbol that makes visuals, with its Lifetime (or empty cells).
      @return None
      """
      self._filling = True
      try:
         rows = [(k, n) for k, _i, n in (self.bank.symbols if self.bank else []) if k in VISUAL_KINDS]
         self.life_table.setRowCount(len(rows))
         for r, (kind, name) in enumerate(rows):
            life = self.lifetimes.get(name)
            values = (name, VISUAL_KINDS[kind], str(life.frames) if life and life.from_arg is None else "",
                      str(life.from_arg) if life and life.from_arg is not None else "",
                      str(life.offset) if life and life.offset else "")
            for col, text in enumerate(values):
               it = QtWidgets.QTableWidgetItem(text)
               if col in (SYMBOL_COLUMN, KIND_COLUMN):
                  it.setFlags(it.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
               self.life_table.setItem(r, col, it)
         self.life_table.resizeColumnsToContents()
      finally:
         self._filling = False

   def _life_edited(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A lifetime cell changed: the row's Lifetime is read back (empty: the default) and the script runs again.
      @param item  the cell
      @return None
      """
      if self._filling:
         return
      r = item.row()
      name = self.life_table.item(r, SYMBOL_COLUMN).text()
      try:
         self.set_lifetime(name, *(self._cell_int(r, c) for c in (FRAMES_COLUMN, ARG_COLUMN, OFFSET_COLUMN)))
      except ValueError as e:
         self.host.show_status(f"Lifetime of {name}: {e}")
         self._fill_lifetimes()

   def _cell_int(self, row: int, col: int) -> int | None:
      """!A lifetime cell's number.
      @param row  the row
      @param col  the column
      @return its value, or None when empty
      @throws ValueError when it is not a number
      """
      it = self.life_table.item(row, col)
      text = it.text().strip() if it is not None else ""
      return int(text) if text else None

   def set_lifetime(self, name: str, frames: int | None = None, from_arg: int | None = None,
                    offset: int | None = None) -> None:
      """!Sets how long a symbol's visuals live and runs the script again.
      @param name      the symbol
      @param frames    fixed frames, or None
      @param from_arg  the argument slot with the frames, or None
      @param offset    frames added to the argument's value, or None (0)
      @return None
      @throws ValueError for an argument slot outside 0 to 7
      """
      if from_arg is not None and not 0 <= from_arg < core.MAX_ARGS:
         raise ValueError(f"argument {from_arg} is outside 0 to {core.MAX_ARGS - 1}")
      if frames is None and from_arg is None:
         self.lifetimes.pop(name, None)
      else:
         self.lifetimes[name] = core.Lifetime(frames or core.DEFAULT_LIFETIME, from_arg, offset or 0)
      self._fill_lifetimes()
      self.rerun()

   # -- the run -----------------------------------------------------------------------------------------------

   def _script_chosen(self, row: int) -> None:
      """!Another script: run it.
      @param row  its index
      @return None
      """
      if not self._filling and row >= 0:
         self.rerun()

   def rerun(self) -> None:
      """!Runs the chosen script with the settings and shows its first frame.
      @return None
      """
      if self.bank is None or self._filling:
         return
      script = max(0, self.scripts.currentRow())
      self.stepper = core.run_script(self.bank, script, self.lifetimes,
                                     core.Lifetime(self.default_life.value()), self.sound_busy.value(),
                                     self.max_frames.value())
      self.timeline.set_stepper(self.stepper)
      self.frame_bar.set_range(0, len(self.stepper.states) - 1)
      last = self.stepper.states[-1]
      end = (f"ends on frame {last.frame}" if not last.error else f"stops on frame {last.frame}: {last.error}")
      if self.isVisible():   # not while the host is being built (every editor would show it)
         self.host.show_status(f"{self.bank.scripts[script][0] if self.bank.scripts else 'script'} {end}")
      self.frame_bar.set_frame(0)
      self.show_frame(self.frame_bar.frame())

   def show_frame(self, frame: int) -> None:
      """!Shows the player on a frame: the commands run, the next one, the state.
      @param frame  the frame
      @return None
      """
      if self.stepper is None or not 0 <= frame < len(self.stepper.states):
         return
      st = self.stepper.states[frame]
      self.timeline.set_frame(frame)
      ran = set(st.ran)
      plain = self.listing.palette().base()
      for address, r in self._rows.items():
         label = self.listing.item(r, LABEL_COLUMN)
         text = label.text().removeprefix(NEXT_MARK)
         label.setText(NEXT_MARK + text if st.active and address == st.pc else text)
         for col in range(len(LISTING_COLUMNS)):
            self.listing.item(r, col).setBackground(QtGui.QBrush(RAN_COLOR) if address in ran else plain)
      if st.active and st.pc in self._rows:
         self.listing.scrollToItem(self.listing.item(self._rows[st.pc], 0))
      mode = "stopped" if not st.active else ("wait mode" if st.waiting else "run mode")
      alive = self.stepper.alive_at(frame)
      for key, text in (("mode", mode), ("pc", f"{st.pc:#06x}"), ("wait", str(st.frames_to_wait)),
                        ("counts", f"{st.visual_count} / {st.sound_count}"),
                        ("args", ", ".join(str(a) for a in st.args)),
                        ("stack", ", ".join(f"{a:#06x}" for a in st.stack) or "empty"),
                        ("alive", ", ".join(v.name for v in alive) or "none"), ("error", st.error or "none")):
         self.state_labels[key].setText(text)
