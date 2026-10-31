"""![S3] Tileset > Animations: the Targets list of the chosen animation (D-30 section 5, engine DS1).

One animation's frames shown on several tile ranges: each target names its first tile ("sheet:index", or a tile of
the placement in a fixed tileset), a frame offset (the frame it shows while target 0 shows frame 0; 0 to frames -
1) and optionally its own phase (frames into the period at map entry). The frames are stored once; the readout says
what the tileset's targets save. The preview shows every target's tiles together, animating at the GBA's frame rate
(an imported flower field: one animation, many targets at the offsets the original game shows them at). Changes go
through the Tileset panel's edit (one undo step; the engine's map compiler checks offsets, fits and overlaps).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import mapview, sprites, tilesets
from ..qtimage import to_qimage
from ..panes import split_box
from ..widgets import PixelView, button, set_enabled

if TYPE_CHECKING:
   from ...core.document import Document
   from .tileset_fixed import AnimationBox

## Target table columns.
COLUMNS = ("First tile", "Offset", "Phase")
## Column of a target's first tile, its offset and its phase.
FIRST_COLUMN, OFFSET_COLUMN, PHASE_COLUMN = 0, 1, 2
## A phase cell meaning the animation's own phase.
OWN_PHASE = ""
## Preview zoom, pixels between targets and targets per preview row.
PREVIEW_ZOOM, GAP, PER_ROW = 2, 4, 8
## Starting height of the target table's pane, pixels (a few rows show; the user drags its boundary).
TABLE_HEIGHT = 120
## Playback timer interval, milliseconds.
TICK_MS = 16
## A preview target's background (RGBA) and the gap's.
TARGET_BACK, GAP_BACK = (40, 40, 48, 255), (0, 0, 0, 0)


class TargetsBox(QtWidgets.QWidget):
   """!The chosen animation's targets: table, Add / Remove, the targets form toggle, the ROM saved and a preview."""

   def __init__(self, box: AnimationBox) -> None:
      """!Builds the box.
      @param box  the owning AnimationBox
      """
      super().__init__()
      ## The owning AnimationBox.
      self.box = box
      ## True while the box fills its widgets.
      self._filling = False
      ## The table.
      self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
      self.table.setHorizontalHeaderLabels(list(COLUMNS))
      self.table.setToolTip("First tile: \"sheet:index\" (a fixed tileset: a tile of its placement); offset: the "
                            "frame it shows while target 0 shows frame 0; phase: frames into the period at map entry "
                            "(empty: the animation's)")
      self.table.itemChanged.connect(lambda item: self._edited(item))
      ## The targets form on or off.
      self.use = QtWidgets.QCheckBox("Several targets (the frames stored once)")
      self.use.clicked.connect(lambda on: self._use_toggled(on))
      ## ROM saved, frames.
      self.info = QtWidgets.QLabel()
      self.info.setWordWrap(True)
      ## The preview.
      self.view = PixelView(PREVIEW_ZOOM)
      ## Play / pause.
      self.play = QtWidgets.QPushButton("Play")
      self.play.setCheckable(True)
      self.play.toggled.connect(lambda on: self._play_toggled(on))
      ## The display frame shown.
      self.clock_label = QtWidgets.QLabel()
      ## Playback timer.
      self.timer = QtCore.QTimer(self)
      self.timer.setInterval(TICK_MS)
      self.timer.timeout.connect(lambda: self._tick())
      ## Time since playback started.
      self.clock = QtCore.QElapsedTimer()
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.use)
      row.addWidget(button("Add target", lambda: self.add_target(), "Another tile range showing the same frames"))
      row.addWidget(button("Remove target", lambda: self.remove_target()))
      row.addStretch(1)
      play = QtWidgets.QHBoxLayout()
      play.addWidget(self.play)
      play.addWidget(self.clock_label, 1)
      lay = QtWidgets.QVBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(QtWidgets.QLabel("Targets"))
      lay.addLayout(row)
      lay.addWidget(self.table, 1)
      lay.addWidget(self.info)
      lay.addWidget(self.view, 1)
      lay.addLayout(play)
      split_box(lay, [TABLE_HEIGHT, None])   # [RZ] targets over their preview: drag the boundary

   # -- what is shown -----------------------------------------------------------------------------

   def _current(self) -> tuple[Document | None, int, dict[str, Any] | None]:
      """!The chosen animation.
      @return (tileset Document, index, animation) — None parts when there is none
      """
      return self.box._current()

   def _compiled(self) -> Any:
      """!The shown tileset compiled (the Tileset panel's).
      @return map_compiler Tileset, or None
      """
      return self.box.panel.compiled_ts()

   def frames(self) -> int:
      """!The chosen animation's frame count (compiled).
      @return frames, or 1 when it does not compile
      """
      _doc, i, _an = self._current()
      rec = tilesets.compiled_animation(self._compiled(), i) if self._compiled() is not None else None
      return len(rec["frames"]) if rec else 1

   def fill(self) -> None:
      """!Shows the chosen animation's targets.
      @return None
      """
      doc, _i, an = self._current()
      self._filling = True
      try:
         items = tilesets.targets(an) if an is not None else []
         self.use.setChecked(bool(items))
         self.use.setEnabled(an is not None)
         set_enabled(self.table, bool(items))   # read-only, still scrolling
         self.table.setRowCount(len(items))
         ref = tilesets.target_ref_key(doc) if doc is not None else tilesets.TARGET_REF_KEYS[0]
         for k, tg in enumerate(items):
            self.table.setItem(k, FIRST_COLUMN, QtWidgets.QTableWidgetItem(str(tg.get(ref, ""))))
            self.table.setItem(k, OFFSET_COLUMN, QtWidgets.QTableWidgetItem(str(tg.get("offset", 0))))
            phase = tg.get("phase")
            self.table.setItem(k, PHASE_COLUMN, QtWidgets.QTableWidgetItem(OWN_PHASE if phase is None
                                                                           else str(phase)))
         ts = self._compiled()
         saved = tilesets.target_saved(ts) if ts is not None else 0
         n = self.frames()
         self.info.setText(f"{n} frames, offsets 0-{n - 1}; the targets of the tileset save {saved} bytes of ROM"
                           if ts is not None else "The tileset does not compile")
      finally:
         self._filling = False
      self.show_frame(0)

   def show_frame(self, t: int) -> None:
      """!Draws every target's tiles at display frame t (target 0 first, in rows of PER_ROW).
      @param t  display frames since the map was entered
      @return None
      """
      doc, i, an = self._current()
      ts = self._compiled()
      rec = tilesets.compiled_animation(ts, i) if ts is not None else None
      if rec is None or an is None:
         self.view.set_image(None)
         return
      bank = None
      if tilesets.is_fixed(doc):   # the bank the metatiles draw target 0's tiles in, else the Bank spin's
         first = (tilesets.targets(an) or [an])[0].get(tilesets.TARGET_REF_KEYS[1], 0)
         bank = tilesets.bank_of_tile(doc, first) if isinstance(first, int) else None
         bank = self.box.panel.sheet_bank.value() if bank is None else bank
      colors = mapview.sheet_bank_colors(ts, rec_frames_sheet(an), bank)
      pictures = [tilesets.target_picture(ts, i, f, colors) for f in tilesets.target_frames(ts, i, t)]
      pw, ph = pictures[0][0], pictures[0][1]
      across = min(PER_ROW, len(pictures))
      down = (len(pictures) + across - 1) // across
      w, h = across * (pw + GAP) + GAP, down * (ph + GAP) + GAP
      img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGBA8888)
      img.fill(QtGui.QColor(*GAP_BACK))
      p = QtGui.QPainter(img)
      for k, pic in enumerate(pictures):
         x, y = GAP + (k % across) * (pw + GAP), GAP + (k // across) * (ph + GAP)
         p.fillRect(x, y, pw, ph, QtGui.QColor(*TARGET_BACK))
         p.drawImage(x, y, to_qimage(*pic))
      p.end()
      self.view.set_image(img)
      self.clock_label.setText(f"display frame {t}: frames " + " ".join(
         str(f) for f in tilesets.target_frames(ts, i, t)))

   # -- edits ---------------------------------------------------------------------------------------

   def _set(self, label: str, items: list[dict[str, Any]] | None) -> bool:
      """!Stores the targets (None: the one-target form) through the Tileset panel.
      @param label  undo label
      @param items  the targets
      @return True when it went through
      """
      doc, i, _an = self._current()
      if doc is None:
         return False
      ok = self.box.panel.edit_tileset(label, lambda: tilesets.set_targets(doc, i, items))
      self.box.fill(doc)
      return ok

   def _rows(self) -> list[dict[str, Any]] | None:
      """!The table as targets.
      @return the targets, or None when a cell is not valid
      """
      doc, _i, _an = self._current()
      ref = tilesets.target_ref_key(doc)
      out = []
      for k in range(self.table.rowCount()):
         first = self.table.item(k, FIRST_COLUMN).text().strip()
         offset = self.table.item(k, OFFSET_COLUMN).text().strip()
         phase = self.table.item(k, PHASE_COLUMN).text().strip()
         if not offset.isdigit() or (phase and not phase.isdigit()) or not first:
            return None
         if tilesets.is_fixed(doc):
            if not first.isdigit():
               return None
            first = int(first)
         out.append({ref: first, "offset": int(offset), "phase": int(phase) if phase else None})
      return out

   def _edited(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A target cell was typed.
      @param item  the cell
      @return None
      """
      if self._filling is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      rows = self._rows()
      if rows is None:
         self.box.panel.host.show_status("A target's first tile is a tile reference, its offset and phase numbers")
         self.fill()
         return
      self._set("Animation target", rows)

   def _use_toggled(self, on: bool) -> None:
      """!The targets form on or off.
      @param on  several targets
      @return None
      """
      doc, i, an = self._current()
      if an is None:
         return
      if on:
         self.box.panel.edit_tileset("Animation targets", lambda: tilesets.use_targets(doc, i))
         self.box.fill(doc)
      else:
         self._set("Animation targets", None)

   def add_target(self, first: Any = None, offset: int = 0) -> bool:
      """!Adds a target after the last one's tiles (the next free range), at an offset.
      @param first   its first tile, or None (after the last target)
      @param offset  its offset
      @return True when added
      """
      doc, i, an = self._current()
      if an is None:
         return False
      if first is None:
         first = next_range(doc, an)
      ok = self.box.panel.edit_tileset("Add target", lambda: tilesets.add_target(doc, i, first, offset))
      self.box.fill(doc)
      return ok

   def remove_target(self) -> bool:
      """!Removes the chosen target.
      @return True when removed
      """
      doc, i, an = self._current()
      k = self.table.currentRow()
      if an is None or k < 0:
         return False
      ok = self.box.panel.edit_tileset("Remove target", lambda: tilesets.remove_target(doc, i, k))
      self.box.fill(doc)
      return ok

   # -- playback ------------------------------------------------------------------------------------

   def _play_toggled(self, on: bool) -> None:
      """!Starts or stops the preview.
      @param on  playing
      @return None
      """
      self.play.setText("Pause" if on else "Play")
      if on:
         self.clock.start()
         self.timer.start()
      else:
         self.timer.stop()

   def _tick(self) -> None:
      """!Shows the display frame for the elapsed time.
      @return None
      """
      # elapsed milliseconds -> GBA display frames (cycles elapsed / cycles per frame), in whole numbers
      self.show_frame(self.clock.elapsed() * sprites.GBA_CLOCK // (sprites.GBA_FRAME_CYCLES * sprites.MS_PER_SECOND))

   def stop(self) -> None:
      """!Stops playback.
      @return None
      """
      self.play.setChecked(False)


def rec_frames_sheet(an: dict[str, Any]) -> str:
   """!The sheet an animation's frames come from (their colors).
   @param an  the animation
   @return sheet name
   """
   return str(an.get("frames"))


def next_range(doc: Document, an: dict[str, Any]) -> Any:
   """!A first tile for a new target: just after the last target's tiles.
   @param doc  tileset Document
   @param an   the animation
   @return "sheet:index", or a tile of the placement
   """
   ref = tilesets.target_ref_key(doc)
   items = tilesets.targets(an)
   last = items[-1].get(ref) if items else an.get(ref, 0)
   count = an.get("count", 1)
   if tilesets.is_fixed(doc):
      return int(last or 0) + count
   parsed = tilesets.parse(last) if isinstance(last, str) else None
   return tilesets.ref(parsed[0], parsed[1] + count) if parsed else last
