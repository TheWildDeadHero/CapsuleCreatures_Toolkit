"""![S8] Affine animation editor (M5, D-38): the commands that scale and rotate a sprite through its matrix, with a
preview that steps them as the engine does (core/anim_affine.py).

Left: the file (a new one starts with the sample: the engine sandbox's spin, pulse and squash; Open..., Save as...,
Export C++...) and its animations (add, rename, remove). Middle: the chosen animation's commands, one row each
(kind, then x scale / y scale / rotation / duration for a frame, the count of a loop, the target of a jump); cells a
kind does not use are greyed. Problems of the file (the export refuses while there are any) are listed below.
Right: the preview (the sprite drawn through each step's matrix, as the hardware draws it), the step bar, and every
step's state (command, frames left, loop count, scales, rotation, matrix). Every edit is one undo step of the file;
the asset editor saves the file with its manifest once it has a name.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import anim_affine as core
from ...core import engine, paths
from ...core.document import Document, DocumentError
from ..panel import EditorPanel
from ..panes import NARROW, WIDE, pane, splitter
from ..qtimage import to_qimage
from ..widgets import PixelView, button
from .anim_common import FrameBar

if TYPE_CHECKING:
   from ..panel import PanelHost

## File dialog filter for animation files.
FILE_FILTER = "Affine animations (*.affine.json *.json);;All files (*)"
## File dialog filter for the C++ export.
HEADER_FILTER = "C++ headers (*.h *.hpp);;All files (*)"
## What file actions may raise.
FILE_ERRORS = (core.AffineError, DocumentError, OSError, ValueError, engine.EngineNotFound)
## A new file's name beside the manifest.
DEFAULT_FILE = "anims" + core.FILE_SUFFIX
## A new animation's name (a number is added while it is taken).
NEW_ANIM = "anim"

## Command table columns: kind, then the four fields.
CMD_COLUMNS = ("Kind", "X scale / count / target", "Y scale", "Rotation", "Duration")
## Command table column of the kind.
KIND_COLUMN = 0
## The fields of each kind, by column (None: unused).
FIELDS = {
   core.OP_FRAME: (None, "x_scale", "y_scale", "rotation", "duration"),
   core.OP_LOOP: (None, "count", None, None, None),
   core.OP_JUMP: (None, "target", None, None, None),
   core.OP_END: (None, None, None, None, None),
}
## Background of a cell its kind does not use.
UNUSED_COLOR = QtGui.QColor(224, 224, 224)

## State table columns.
STATE_COLUMNS = ("Step", "Cmd", "Left", "Loop", "X scale", "Y scale", "Rotation", "pa", "pb", "pc", "pd", "Note")
## Steps the preview runs by default, and at most.
DEFAULT_STEPS = core.DEFAULT_STEPS
## Most steps the preview runs.
MAX_STEPS = 2000
## Zoom of the preview.
PREVIEW_ZOOM = 4
## Width of a hex field (0x0100).
HEX_WIDTH = 6

## Starting widths of the left and right panes, pixels.
LEFT_WIDTH = 200
## Starting width of the right pane, pixels.
RIGHT_WIDTH = 420


class AffineAnimPanel(EditorPanel):
   """!The affine animation editor (see the module doc).

   @var affine
   The animation file's Document (path None until saved).
   @var steps
   The chosen animation's simulated steps (core.Step list).
   """

   ## See EditorPanel.panel_id.
   panel_id = "anim_affine"
   ## See EditorPanel.title.
   title = "Affine anims"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel with a new file (the sample).
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      self.affine: Document | None = None
      self.steps: list[core.Step] = []
      ## True while the panel fills its own widgets.
      self._filling = False

      # left: the file and its animations
      left = QtWidgets.QWidget()
      lv = QtWidgets.QVBoxLayout(left)
      ## The file's name ("new file" while unsaved).
      self.file_label = QtWidgets.QLabel()
      self.file_label.setWordWrap(True)
      lv.addWidget(self.file_label)
      grid = QtWidgets.QGridLayout()
      grid.addWidget(button("New", lambda: self.new_file(), "A new file with the sample animations"), 0, 0)
      grid.addWidget(button("Open...", lambda: self.open_file()), 0, 1)
      grid.addWidget(button("Save as...", lambda: self.save_as(), "Name the file: the editor saves it with the "
                            "manifest from then on"), 1, 0)
      grid.addWidget(button("Export C++...", lambda: self.export(), "af::Cmd arrays and their tables"), 1, 1)
      lv.addLayout(grid)
      ## The animations.
      self.anims = QtWidgets.QListWidget()
      self.anims.currentRowChanged.connect(lambda _r: self._anim_chosen())
      lv.addWidget(self.anims, 1)
      ## The chosen animation's name.
      self.name_edit = QtWidgets.QLineEdit()
      self.name_edit.editingFinished.connect(lambda: self.rename(self.name_edit.text()))
      lv.addWidget(self.name_edit)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Add", lambda: self.add_anim()))
      row.addWidget(button("Remove", lambda: self.remove_anim()))
      lv.addLayout(row)

      # middle: the commands
      middle = QtWidgets.QWidget()
      mv = QtWidgets.QVBoxLayout(middle)
      ## The commands.
      self.cmds = QtWidgets.QTableWidget(0, len(CMD_COLUMNS))
      self.cmds.setHorizontalHeaderLabels(list(CMD_COLUMNS))
      self.cmds.verticalHeader().setVisible(True)
      self.cmds.itemChanged.connect(lambda it: self._cell_edited(it))
      mv.addWidget(self.cmds, 1)
      row = QtWidgets.QHBoxLayout()
      ## The kind Add inserts.
      self.add_kind = QtWidgets.QComboBox()
      self.add_kind.addItems(list(core.OPS))
      row.addWidget(self.add_kind)
      row.addWidget(button("Add", lambda: self.add_cmd(self.add_kind.currentText()), "After the chosen command"))
      row.addWidget(button("Remove", lambda: self.remove_cmd()))
      row.addWidget(button("Up", lambda: self.move_cmd(-1)))
      row.addWidget(button("Down", lambda: self.move_cmd(1)))
      mv.addLayout(row)
      ## The file's problems.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)
      mv.addWidget(self.problems)

      # right: the preview and the steps
      preview = QtWidgets.QWidget()
      pv = QtWidgets.QVBoxLayout(preview)
      ## The sprite drawn through the step's matrix.
      self.view = PixelView(PREVIEW_ZOOM)
      pv.addWidget(self.view, 1)
      opts = QtWidgets.QHBoxLayout()
      ## The preview's shape.
      self.shape = QtWidgets.QComboBox()
      self.shape.addItems(list(core.SHAPES))
      self.shape.currentIndexChanged.connect(lambda _i: self.show_step(self.step_bar.frame()))
      opts.addWidget(self.shape)
      ## Double size (sprites::kAffineDouble).
      self.double = QtWidgets.QCheckBox("Double size")
      self.double.setChecked(True)
      self.double.toggled.connect(lambda _on: self.show_step(self.step_bar.frame()))
      opts.addWidget(self.double)
      ## Steps simulated.
      self.step_count = QtWidgets.QSpinBox()
      self.step_count.setRange(1, MAX_STEPS)
      self.step_count.setValue(DEFAULT_STEPS)
      self.step_count.setPrefix("steps ")
      self.step_count.valueChanged.connect(lambda _v: self.simulate())
      opts.addWidget(self.step_count)
      pv.addLayout(opts)
      ## The step chooser.
      self.step_bar = FrameBar(lambda s: self.show_step(s), 1, DEFAULT_STEPS)
      pv.addWidget(self.step_bar)
      ## Every step's state.
      self.state = QtWidgets.QTableWidget(0, len(STATE_COLUMNS))
      self.state.setHorizontalHeaderLabels(list(STATE_COLUMNS))
      self.state.verticalHeader().setVisible(False)
      self.state.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      self.state.currentCellChanged.connect(lambda r, _c, _pr, _pc: self.step_bar.set_frame(r + 1) if r >= 0 else None)
      right = splitter(QtCore.Qt.Orientation.Vertical, [pane(preview), self.state], [WIDE, WIDE])

      lay = QtWidgets.QVBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(splitter(QtCore.Qt.Orientation.Horizontal, [pane(left), pane(middle), right],
                             [NARROW, WIDE, WIDE], [LEFT_WIDTH, None, RIGHT_WIDTH]))
      try:
         self.new_file(notify=False)
      except FILE_ERRORS as e:
         self.host.show_status(f"Affine animations: {e}")

   # -- documents ---------------------------------------------------------------------------------------------

   def current_document(self) -> Document | None:
      """!Undo / Redo act on the animation file while this panel is in front.
      @return the file's Document
      """
      host = self.host   # a local alias (Doxygen reads the base class's member read here as a new one)
      return self.affine or getattr(host, "document", None)

   def extra_documents(self) -> list[Document]:
      """!The file once it has a name (saved with the manifest).
      @return [file] or []
      """
      return [self.affine] if self.affine is not None and self.affine.path is not None else []

   def stop(self) -> None:
      """!Stops playback.
      @return None
      """
      self.step_bar.stop()

   def set_file(self, doc: Document, notify: bool = True) -> None:
      """!Shows a file.
      @param doc     its Document
      @param notify  tell the host (Undo / Redo follow); False while the host is being built
      @return None
      """
      self.affine = doc
      self.refresh()
      if self.anims.count():
         self.anims.setCurrentRow(0)
      if notify:
         self.host.selection_changed()

   def new_file(self, notify: bool = True) -> bool:
      """!A new, unnamed file with the sample animations.
      @param notify  tell the host (False while it is being built)
      @return True
      """
      self.set_file(Document(core.sample(), None, core.SCHEMA), notify)
      return True

   def open_file(self, path: str | None = None) -> bool:
      """!Opens a file (asks for it when no path is given).
      @param path  NAME.affine.json, or None to ask
      @return True when opened
      """
      if path is None:
         path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Open affine animations", "", FILE_FILTER)
         if not path:
            return False
      try:
         doc = Document.open(path, core.SCHEMA)
      except FILE_ERRORS as e:
         self.host.show_status(f"Open: {e}")
         return False
      self.set_file(doc)
      return True

   def _start_folder(self) -> Path:
      """!Where file dialogs start: beside the file, else beside the manifest, else here.
      @return a folder
      """
      if self.affine is not None and self.affine.path is not None:
         return self.affine.path.parent
      manifest = getattr(self.host, "document", None)
      return manifest.path.parent if manifest is not None and manifest.path is not None else Path.cwd()

   def save_as(self, path: str | None = None) -> bool:
      """!Names the file and saves it (asks where when no path is given).
      @param path  NAME.affine.json, or None to ask
      @return True when saved
      """
      if self.affine is None:
         return False
      if path is None:
         path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save affine animations",
                                                          str(self._start_folder() / DEFAULT_FILE), FILE_FILTER)
         if not path:
            return False
      try:
         self.affine.save(path)
      except FILE_ERRORS as e:
         self.host.show_status(f"Save: {e}")
         return False
      self.host.show_status(f"Saved {Path(path).name}")
      self.refresh()
      self.host.selection_changed()
      return True

   def export(self, path: str | None = None) -> bool:
      """!Writes the C++ (asks where when no path is given); LF line ends, only when the text changes.
      @param path  NAME.h, or None to ask
      @return True when written (or already up to date)
      """
      if self.affine is None:
         return False
      if path is None:
         start = self._start_folder() / "affine_anims.h"
         path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Export affine animations", str(start),
                                                          HEADER_FILTER)
         if not path:
            return False
      out = Path(path)
      source = ""
      if self.affine.path is not None:
         try:
            source = paths.relative(self.affine.path, out.parent)
         except DocumentError:
            source = self.affine.path.name   # another drive: the name only (no absolute path in the output)
      try:
         wrote = core.write_if_changed(out, core.export_cpp(self.affine.data, source))
      except FILE_ERRORS as e:
         self.host.show_status(f"Export: {e}")
         return False
      self.host.show_status(f"Wrote {out.name}" if wrote else f"{out.name} is up to date")
      return True

   # -- filling -----------------------------------------------------------------------------------------------

   def anim_index(self) -> int:
      """!The chosen animation's index.
      @return index, or -1
      """
      return self.anims.currentRow()

   def anim(self) -> dict[str, Any] | None:
      """!The chosen animation.
      @return its data, or None
      """
      i = self.anim_index()
      anims = self.affine.data.get("anims", []) if self.affine is not None else []
      return anims[i] if 0 <= i < len(anims) else None

   def refresh(self) -> None:
      """!Re-reads the file: names, commands, problems, the preview.
      @return None
      """
      if self.affine is None:
         return
      self._filling = True
      try:
         self.file_label.setText(self.affine.path.name if self.affine.path else "New file (not saved yet)")
         row = self.anims.currentRow()
         self.anims.clear()
         for a in self.affine.data.get("anims", []):
            self.anims.addItem(str(a.get("name", "")))
         if self.anims.count():
            self.anims.setCurrentRow(min(max(row, 0), self.anims.count() - 1))
      finally:
         self._filling = False
      found = core.check_data(self.affine.data)
      self.problems.setText("\n".join(found) if found else "No problems: the C++ export is ready.")
      self._fill_cmds()

   def _anim_chosen(self) -> None:
      """!Another animation: its commands and preview.
      @return None
      """
      if not self._filling:
         self._fill_cmds()

   def _fill_cmds(self) -> None:
      """!The chosen animation's commands, then the preview.
      @return None
      """
      a = self.anim()
      self._filling = True
      try:
         self.name_edit.setText(str(a.get("name", "")) if a else "")
         cmds = a.get("cmds", []) if a else []
         row = self.cmds.currentRow()
         self.cmds.setRowCount(len(cmds))
         for r, entry in enumerate(cmds):
            kind = QtWidgets.QComboBox()
            kind.addItems(list(core.OPS))
            kind.setCurrentText(str(entry.get("op")))
            kind.currentTextChanged.connect(lambda op, r=r: self.set_kind(r, op))
            self.cmds.setCellWidget(r, KIND_COLUMN, kind)
            for col, key in enumerate(FIELDS.get(entry.get("op"), FIELDS[core.OP_END])):
               if col == KIND_COLUMN:
                  continue
               it = QtWidgets.QTableWidgetItem(str(entry.get(key, "")) if key else "")
               if key is None:
                  it.setFlags(it.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                  it.setBackground(QtGui.QBrush(UNUSED_COLOR))
               self.cmds.setItem(r, col, it)
         if cmds:
            self.cmds.setCurrentCell(min(max(row, 0), len(cmds) - 1), 1)
      finally:
         self._filling = False
      self.simulate()

   def simulate(self) -> None:
      """!Runs the chosen animation's steps and fills the state table; the preview shows the step chosen.
      @return None
      """
      a = self.anim()
      try:
         self.steps = core.simulate(a.get("cmds", []), self.step_count.value()) if a else []
      except core.AffineError as e:
         self.steps = []
         self.host.show_status(f"Preview: {e}")
      self._filling = True
      try:
         self.state.setRowCount(len(self.steps))
         for r, s in enumerate(self.steps):
            m = s.matrix
            values = (s.step, s.cmd, s.delay, s.loop, f"{s.x_scale:#0{HEX_WIDTH}x}", f"{s.y_scale:#0{HEX_WIDTH}x}",
                      f"{s.rotation:#0{HEX_WIDTH}x}", m.pa, m.pb, m.pc, m.pd,
                      s.problem or ("ended" if s.ended else ""))
            for col, v in enumerate(values):
               self.state.setItem(r, col, QtWidgets.QTableWidgetItem(str(v)))
      finally:
         self._filling = False
      self.step_bar.set_range(1, max(1, len(self.steps)))
      self.show_step(self.step_bar.frame())

   def show_step(self, step: int) -> None:
      """!Draws the sprite through a step's matrix.
      @param step  1-based step
      @return None
      """
      if not 1 <= step <= len(self.steps):
         self.view.set_image(None)
         return
      w, h, rgba = core.render_sprite(self.steps[step - 1].matrix, self.shape.currentText(),
                                      self.double.isChecked())
      self.view.set_image(to_qimage(w, h, rgba))
      if self.state.currentRow() != step - 1:
         self._filling = True
         try:
            self.state.setCurrentCell(step - 1, 0)
         finally:
            self._filling = False

   # -- edits -------------------------------------------------------------------------------------------------

   def _edit(self, label: str, fn: Any) -> bool:
      """!One undo step of the file.
      @param label  undo label
      @param fn     callable(data)
      @return True when it went through
      """
      doc = self.affine
      if doc is None or self._filling:
         return False
      ok = self.host.run_edit(label, lambda: fn(doc.data), document=doc)
      self.host.selection_changed()
      self.refresh()
      return ok

   def add_anim(self, name: str | None = None) -> bool:
      """!Adds an animation (one end command) after the chosen one.
      @param name  its name, or None for a free NEW_ANIM name
      @return True when added
      """
      if self.affine is None:
         return False
      taken = {a.get("name") for a in self.affine.data.get("anims", [])}
      if name is None:
         name, n = NEW_ANIM, 1
         while name in taken:
            n += 1
            name = f"{NEW_ANIM}{n}"
      at = self.anim_index() + 1

      def add(data: dict[str, Any]) -> None:
         if name in taken:
            raise ValueError(f"an animation is called {name!r} already")
         data.setdefault("anims", []).insert(at, {"name": name, "cmds": [core.end()]})

      ok = self._edit("Add affine animation", add)
      if ok:
         self.anims.setCurrentRow(at)
      return ok

   def remove_anim(self) -> bool:
      """!Removes the chosen animation.
      @return True when removed
      """
      i = self.anim_index()
      if i < 0:
         return self.explain("Remove", "animation")
      return self._edit("Remove affine animation", lambda d: d["anims"].pop(i))

   def rename(self, name: str) -> bool:
      """!Renames the chosen animation.
      @param name  the new name (an identifier)
      @return True when renamed
      """
      i, a = self.anim_index(), self.anim()
      name = name.strip()
      if a is None or self._filling or name == a.get("name"):
         return False

      def change(data: dict[str, Any]) -> None:
         if any(o.get("name") == name for o in data["anims"]):
            raise ValueError(f"an animation is called {name!r} already")
         data["anims"][i]["name"] = name

      return self._edit("Rename affine animation", change)

   def add_cmd(self, op: str) -> bool:
      """!Adds a command after the chosen one.
      @param op  its kind (core.OPS)
      @return True when added
      """
      i, a = self.anim_index(), self.anim()
      if a is None:
         return self.explain("Add command", "animation")
      at = self.cmds.currentRow() + 1
      ok = self._edit(f"Add {op}", lambda d: d["anims"][i]["cmds"].insert(at, core.default_entry(op)))
      if ok:
         self.cmds.setCurrentCell(at, 1)
      return ok

   def remove_cmd(self) -> bool:
      """!Removes the chosen command.
      @return True when removed
      """
      i, r = self.anim_index(), self.cmds.currentRow()
      if self.anim() is None or r < 0:
         return self.explain("Remove command", "command")
      return self._edit("Remove command", lambda d: d["anims"][i]["cmds"].pop(r))

   def move_cmd(self, delta: int) -> bool:
      """!Moves the chosen command up (-1) or down (1).
      @param delta  -1 or 1
      @return True when moved
      """
      i, r = self.anim_index(), self.cmds.currentRow()
      a = self.anim()
      if a is None or r < 0:
         return self.explain("Move command", "command")
      to = r + delta
      if not 0 <= to < len(a["cmds"]):
         return False

      def move(data: dict[str, Any]) -> None:
         cmds = data["anims"][i]["cmds"]
         cmds[r], cmds[to] = cmds[to], cmds[r]

      ok = self._edit("Move command", move)
      if ok:
         self.cmds.setCurrentCell(to, 1)
      return ok

   def set_kind(self, row: int, op: str) -> bool:
      """!Changes a command's kind (its fields start at their defaults).
      @param row  the command
      @param op   the kind
      @return True when changed
      """
      i = self.anim_index()
      if self.anim() is None or self._filling:
         return False
      return self._edit(f"Make command {op}", lambda d: d["anims"][i]["cmds"].__setitem__(row, core.default_entry(op)))

   def set_field(self, row: int, key: str, value: int) -> bool:
      """!Sets one field of a command.
      @param row    the command
      @param key    its field ("x_scale", "count", ...)
      @param value  the value
      @return True when set (a value out of range is refused)
      """
      i = self.anim_index()
      if self.anim() is None:
         return False

      def change(data: dict[str, Any]) -> None:
         entry = dict(data["anims"][i]["cmds"][row])
         entry[key] = value
         core.to_cmd(entry)   # refuses a value its field cannot hold
         data["anims"][i]["cmds"][row] = entry

      return self._edit(f"Set {key}", change)

   def _cell_edited(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A field cell changed.
      @param item  the cell
      @return None
      """
      a = self.anim()
      if self._filling or a is None:
         return
      entry = a["cmds"][item.row()]
      key = FIELDS.get(entry.get("op"), FIELDS[core.OP_END])[item.column()]
      if key is None:
         return
      try:
         value = int(item.text(), 0)
      except ValueError:
         self.host.show_status(f"{key}: {item.text()!r} is not a number")
         self.refresh()
         return
      self.set_field(item.row(), key, value)
