"""![VX] VM extensions view (D-39): a game's VM extension manifests (capsule.vm-ext/1) as the build reads them, with the
engine's checks, the banks' usage and the natives' sizes on the GBA (core/vm_ext.py over the engine's
tools/vm_ext.py).

Left: the manifests (Open manifests..., or the engine sandbox's simple-shape sample), the usage records and the size
listing given with them, and each command table's progress (ops, aliases and their share, natives, natives whose
alias candidate is proven, ops no bank uses). Middle: the ops of the table chosen, filtered by kind and by a name or
reason; a native's GBA bytes and every op's uses are columns. Right: the op chosen (operands, its steps or its
reason, owner, tier, waits, glitch hooks) and the checks' errors and warnings; Copy report puts the natives' list
on the clipboard. Nothing here edits a manifest: they are the game's source files.

D-36 package 2 step D: Script sample opens the engine's field script VM with its natives sample; Open game... finds
the engine's script VM, a game's natives manifest and its scripts usage record under the folders chosen (the
import's content, the build folder). The script VM's generic ops have their own filter; a script native shows
whether the game implements it, its milestone, and its owner's GBA bytes; the natives are summarised by class.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtWidgets

from ...core import engine
from ...core import vm_ext as core
from ..panel import EditorPanel
from ..panes import NARROW, WIDE, pane, split_box, splitter
from ..widgets import button

if TYPE_CHECKING:
   from ..panel import PanelHost

## File dialog filter for manifests and usage records.
JSON_FILTER = "JSON files (*.json);;All files (*)"
## File dialog filter for a size listing.
SIZES_FILTER = "nm listings (*.txt *.nm);;All files (*)"
## What loading may raise.
LOAD_ERRORS = (core.ExtensionError, engine.EngineNotFound, OSError)
## The op list's columns (step D: a script native's implemented flag and milestone; its GBA bytes are its owner's).
COLUMNS = ("Table", "Id", "Name", "Kind", "Owner", "Waits", "Bytes", "GBA bytes", "Uses", "Implemented", "Milestone")
## Marks GBA bytes that are a script native's owner's, not its own.
OWNER_BYTES_MARK = " (owner)"
## Step D: a game's script VM files: the engine's script VM and the game's natives manifest.
GAME_MANIFESTS = 2
## The table filter's entry for every table.
ALL_TABLES = "(every table)"
## A value the view does not have.
NONE_SHOWN = "-"
## Column of the name (the row's op is found by it).
NAME_COLUMN = 2


class VmExtPanel(EditorPanel):
   """!Lists a game's VM extension manifests with their checks, usage and sizes."""

   ## See EditorPanel.panel_id.
   panel_id = "vm_ext"
   ## See EditorPanel.title.
   title = "VM extensions"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The manifests read, or None.
      self.ext = None   # type: core.Extensions | None
      ## The manifests' files.
      self.manifests = []   # type: list[Path]
      ## The usage records.
      self.usage = []   # type: list[Path]
      ## The size listing, or None.
      self.sizes = None   # type: Path | None
      ## The rows the list shows, in its order.
      self.shown = []   # type: list[core.OpRow]

      left = QtWidgets.QWidget()
      lv = QtWidgets.QVBoxLayout(left)
      open_manifests_button = button("Open manifests...", self.open_manifests,
                                     "Read capsule.vm-ext/1 manifests (one game's)")
      lv.addWidget(open_manifests_button)
      open_sample_button = button("Sample", self.open_sample, "The engine sandbox's manifest (simple shapes)")
      lv.addWidget(open_sample_button)
      script_sample_button = button("Script sample", self.open_script_sample,
                                    "The engine's field script VM with its natives sample (simple shapes)")
      lv.addWidget(script_sample_button)
      open_game_button = button("Open game...", self.open_game,
                                "A game's script natives: its import's content folder, then its build folder")
      lv.addWidget(open_game_button)
      add_usage_button = button("Add usage...", self.add_usage, "The banks' usage records (capsule.vm-usage/1)")
      lv.addWidget(add_usage_button)
      add_sizes_button = button("Add GBA sizes...", self.add_sizes, "An nm -S -C listing of a GBA build")
      lv.addWidget(add_sizes_button)
      ## The files given.
      self.files = QtWidgets.QListWidget()
      lv.addWidget(self.files, 1)
      ## Each table's progress.
      self.progress = QtWidgets.QTreeWidget()
      self.progress.setHeaderLabels(["Table", "Ops", "Generic", "Aliases", "Natives", "Proven", "Unused"])
      self.progress.setRootIsDecorated(False)
      lv.addWidget(self.progress, 1)
      ## Step D: the script natives by class.
      self.classes = QtWidgets.QTreeWidget()
      self.classes.setHeaderLabels(["Natives by class", "Natives", "Uses"])
      self.classes.setRootIsDecorated(False)
      lv.addWidget(self.classes, 1)
      split_box(lv)   # the files above the progress: the user drags the boundary

      middle = QtWidgets.QWidget()
      mv = QtWidgets.QVBoxLayout(middle)
      row = QtWidgets.QHBoxLayout()
      ## The table filter.
      self.table_box = QtWidgets.QComboBox()
      self.table_box.activated.connect(lambda _i: self.fill())
      ## The kind filter.
      self.kind_box = QtWidgets.QComboBox()
      self.kind_box.addItems(list(core.FILTERS))
      self.kind_box.activated.connect(lambda _i: self.fill())
      ## The name / reason filter.
      self.search = QtWidgets.QLineEdit()
      self.search.setPlaceholderText("Name or reason")
      self.search.textChanged.connect(lambda _t: self.fill())
      row.addWidget(self.table_box)
      row.addWidget(self.kind_box)
      row.addWidget(self.search, 1)
      mv.addLayout(row)
      ## The ops.
      self.ops = QtWidgets.QTreeWidget()
      self.ops.setHeaderLabels(list(COLUMNS))
      self.ops.setRootIsDecorated(False)
      self.ops.setSortingEnabled(False)
      self.ops.currentItemChanged.connect(lambda _c, _p: self.show_op())
      mv.addWidget(self.ops, 1)

      right = QtWidgets.QWidget()
      rv = QtWidgets.QVBoxLayout(right)
      ## The op chosen.
      self.detail = QtWidgets.QPlainTextEdit()
      self.detail.setReadOnly(True)
      rv.addWidget(self.detail, 1)
      ## The checks' result.
      self.checks = QtWidgets.QPlainTextEdit()
      self.checks.setReadOnly(True)
      rv.addWidget(self.checks, 1)
      copy_report_button = button("Copy report", self.copy_report, "The natives with their reasons, owners and sizes")
      rv.addWidget(copy_report_button)
      split_box(rv)   # the op above the checks (the button stays with the checks' pane)

      layout = QtWidgets.QHBoxLayout(self)
      layout.addWidget(splitter(_horizontal(), [pane(left), pane(middle), pane(right)], [NARROW, WIDE, NARROW]))

   # --- loading ---------------------------------------------------------------------------------------------

   def open_manifests(self) -> None:
      """!Asks for manifests and reads them.
      @return None
      """
      names, _f = QtWidgets.QFileDialog.getOpenFileNames(self, "Open VM extension manifests", "", JSON_FILTER)
      if names:
         self.load([Path(n) for n in names], [], None)

   def open_sample(self) -> None:
      """!Reads the engine sandbox's manifest.
      @return None
      """
      try:
         self.load([core.sandbox_manifest()], [], None)
      except engine.EngineNotFound as e:
         self.host.show_status(f"Sample: {e}")

   def open_script_sample(self) -> None:
      """!Step D: reads the engine's script VM with its natives sample and the sample's usage record.
      @return None
      """
      try:
         manifests, usage = core.script_sample()
      except engine.EngineNotFound as e:
         self.host.show_status(f"Script sample: {e}")
         return
      self.load(manifests, usage, None)

   def open_game(self) -> None:
      """!Step D: asks for a game's import content folder (then, optionally, its build folder) and reads the script
      VM with the game's natives manifest and scripts usage record found there.
      @return None
      """
      content = QtWidgets.QFileDialog.getExistingDirectory(self, "The game's imported content", "")
      if not content:
         return
      build = QtWidgets.QFileDialog.getExistingDirectory(self, "The game's build folder (Cancel: none)", "")
      self.open_game_folders([Path(content)] + ([Path(build)] if build else []))

   def open_game_folders(self, folders: list[Path]) -> bool:
      """!Step D: reads the script VM files found under folders (core.game_files()).
      @param folders  the import's content, the build folder
      @return True when a natives manifest was found and read
      """
      try:
         manifests, usage = core.game_files(folders)
      except engine.EngineNotFound as e:
         self.host.show_status(f"Open game: {e}")
         return False
      if len(manifests) < GAME_MANIFESTS:
         self.host.show_status(f"Open game: no {core.GAME_NATIVES_FILE} under {', '.join(str(f) for f in folders)}")
         return False
      return self.load(manifests, usage, None)

   def add_usage(self) -> None:
      """!Asks for usage records and reads them with the manifests.
      @return None
      """
      names, _f = QtWidgets.QFileDialog.getOpenFileNames(self, "Add usage records", "", JSON_FILTER)
      if names and self.manifests:
         self.load(self.manifests, self.usage + [Path(n) for n in names], self.sizes)
      elif names:
         self.explain("Add usage", "manifest")

   def add_sizes(self) -> None:
      """!Asks for a GBA size listing and reads it with the manifests.
      @return None
      """
      name, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Add GBA sizes", "", SIZES_FILTER)
      if name and self.manifests:
         self.load(self.manifests, self.usage, Path(name))
      elif name:
         self.explain("Add GBA sizes", "manifest")

   def load(self, manifests: list[Path], usage: list[Path], sizes: Path | None) -> bool:
      """!Reads manifests with usage and sizes, and shows them.
      @param manifests  the manifests
      @param usage      usage records
      @param sizes      a size listing, or None
      @return True when they were read
      """
      try:
         ext = core.load(manifests, usage, sizes)
      except LOAD_ERRORS as e:
         self.host.show_status(f"Extensions: {e}")
         return False
      self.ext, self.manifests, self.usage, self.sizes = ext, list(manifests), list(usage), sizes
      self.files.clear()
      self.files.addItems([f"manifest: {p.name}" for p in manifests] + [f"usage: {p.name}" for p in usage] +
                          ([f"sizes: {sizes.name}"] if sizes is not None else []))
      self.table_box.clear()
      self.table_box.addItems([ALL_TABLES] + ext.tables())
      self.progress.clear()
      for s in ext.summary():
         self.progress.addTopLevelItem(QtWidgets.QTreeWidgetItem(
            [s.table, str(s.ops), str(s.generic), f"{s.aliases} ({s.alias_percent}%)", str(s.natives), str(s.proven),
             str(s.unused) if s.unused is not None else NONE_SHOWN]))
      self.classes.clear()
      for label, natives, uses in ext.native_classes():
         self.classes.addTopLevelItem(QtWidgets.QTreeWidgetItem([label, str(natives), str(uses)]))
      lines = [f"error: {e}" for e in ext.errors] + [f"warning: {w}" for w in ext.warnings]
      self.checks.setPlainText("\n".join(lines) if lines else "Checks: no errors, no warnings.")
      self.fill()
      self.host.show_status(f"Extensions: {len(ext.rows)} ops in {len(manifests)} manifests")
      return True

   # --- the list ----------------------------------------------------------------------------------------------

   def fill(self) -> None:
      """!Lists the ops the filters let through.
      @return None
      """
      self.ops.clear()
      self.shown = []
      if self.ext is None:
         return
      table = self.table_box.currentText()
      kinds = core.FILTERS.get(self.kind_box.currentText(), core.FILTERS["All ops"])
      self.shown = self.ext.filtered(None if table in ("", ALL_TABLES) else table, kinds, self.search.text())
      for r in self.shown:
         self.ops.addTopLevelItem(QtWidgets.QTreeWidgetItem(
            [r.table, f"{r.id:#04x}", r.name, r.kind, r.owner, "yes" if r.waits else "",
             str(r.size) if r.size is not None else NONE_SHOWN, _gba_bytes(r),
             str(r.uses) if r.uses is not None else NONE_SHOWN,
             NONE_SHOWN if r.implemented is None else ("yes" if r.implemented else "no"), r.milestone or ""]))
      if self.shown:
         self.ops.setCurrentItem(self.ops.topLevelItem(0))

   def current(self) -> core.OpRow | None:
      """!The op chosen.
      @return its row, or None
      """
      item = self.ops.currentItem()
      if item is None:
         return None
      index = self.ops.indexOfTopLevelItem(item)
      return self.shown[index] if 0 <= index < len(self.shown) else None

   def show_op(self) -> None:
      """!Shows the op chosen.
      @return None
      """
      r = self.current()
      if r is None:
         self.detail.setPlainText("")
         return
      lines = [f"{r.name} ({r.id:#04x}) in {r.table} — {r.kind}, {r.manifest}",
               f"Owner {r.owner or NONE_SHOWN}, tier {r.tier}{', may wait' if r.waits else ''}",
               "Operands: " + (", ".join(r.operands) if r.operands else "none")]
      if r.kind == "native":
         lines += [f"Native: {r.symbol}", f"Reason: {r.reason}"]
         if r.implemented is not None:   # step D: a script native
            lines += [f"Implemented by the game: {'yes' if r.implemented else 'no (its generic stand-in)'}",
                      f"Milestone: {r.milestone or NONE_SHOWN}, class: {core.native_class(r.reason)}",
                      f"Owner's GBA bytes: {r.owner_bytes if r.owner_bytes is not None else NONE_SHOWN}"]
         if r.steps:
            lines += [f"Alias candidate ({r.parity}):"] + [f"   {s}" for s in r.steps]
      else:
         lines += ["Steps:"] + [f"   {s}" for s in r.steps]
      if r.glitch:
         lines.append("Glitch hooks: " + ", ".join(r.glitch))
      self.detail.setPlainText("\n".join(lines))

   def copy_report(self) -> None:
      """!Puts the natives' report on the clipboard.
      @return None
      """
      if self.ext is None:
         self.explain("Copy report", "manifest")
         return
      QtWidgets.QApplication.clipboard().setText(core.report_text(self.ext))
      self.host.show_status("Extensions: the natives' report is on the clipboard")


def _gba_bytes(r: core.OpRow) -> str:
   """!An op's GBA bytes as the list shows them (step D: a script native's are its owner's, marked).
   @param r  the row
   @return the text
   """
   if r.gba_bytes is not None:
      return str(r.gba_bytes)
   return f"{r.owner_bytes}{OWNER_BYTES_MARK}" if r.owner_bytes is not None else NONE_SHOWN


def _horizontal() -> object:
   """!The panes' orientation (left to right).
   @return Qt.Horizontal
   """
   from PySide6 import QtCore   # pylint: disable=import-outside-toplevel
   return QtCore.Qt.Orientation.Horizontal
