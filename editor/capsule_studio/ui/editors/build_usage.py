"""!D-36 package 3 step 3C: the project settings window's Build usage panel (core.exclusion; the engine's
docs/USAGE.md "Exclusion manifest").

A build folder (chosen at the top, shared with the GBA memory panel's choice) holds what the last build of the game
recorded: its usage report, the build's suggestion of what the game can exclude, the last check of the game's own
manifest and, for a GBA build, the program's symbol listing. The panel shows:

- the engine modules: what uses each, which the game's own code calls (the build did not offer to exclude them), the
  bytes each links on the GBA, and an Excluded box on the excludable ones (offered where the build suggests it);
- the script VM's ops: how often the game's scripts emit each, and an Excluded box on those they do not emit;
- the last build's check, above the tables.

Save writes the game's manifest (the file the project names, or reference/exclude.json, which the project then
names: saved with the project). The next build reads it.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ...core import engine, exclusion, gba_memory, project
from ...core.document import DocumentError
from ..panel import EditorPanel
from ..panes import splitter
from ..widgets import button
from .gba_memory import SETTINGS_KEY

if TYPE_CHECKING:
   from ..panel import PanelHost

## Errors reading a folder or writing the manifest.
ERRORS = (exclusion.ExclusionError, DocumentError, OSError, engine.EngineNotFound)
## The modules table's columns.
MODULE_COLUMNS = ("Module", "Used by", "Game code", "GBA bytes", "Excluded")
## The script ops table's columns.
OP_COLUMNS = ("Script op", "Emitted", "Excluded")
## Column of each table's Excluded box.
MODULE_EXCLUDED, OP_EXCLUDED = len(MODULE_COLUMNS) - 1, len(OP_COLUMNS) - 1
## Colours of the findings by level.
LEVEL_COLORS = {"error": "#c03030", "warning": "#b07000", "note": "#606060"}


class BuildUsagePanel(EditorPanel):
   """!A game's build usage and its exclusion manifest."""

   ## See EditorPanel.panel_id.
   panel_id = "build_usage"
   ## See EditorPanel.title.
   title = "Build usage"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## True while widgets are being filled.
      self._loading = False
      ## What the build folder says about the game, or None.
      self.usage: exclusion.BuildUsage | None = None
      ## The game's manifest as read, or None.
      self.manifest: dict | None = None
      ## The module rows shown.
      self.module_rows: list[exclusion.ModuleRow] = []
      ## The op rows shown.
      self.op_rows: list[exclusion.OpRow] = []

      ## The build folder.
      self.folder = QtWidgets.QComboBox()
      self.folder.setEditable(True)
      self.folder.setToolTip("The build folder that built the game (the GBA memory tab's choice too)")
      self.folder.activated.connect(lambda _i: self.use_folder(self.folder.currentText()))
      self.folder.lineEdit().editingFinished.connect(lambda: self.use_folder(self.folder.currentText()))
      top = QtWidgets.QHBoxLayout()
      top.addWidget(QtWidgets.QLabel("Build folder"))
      top.addWidget(self.folder, 1)
      top.addWidget(button("Browse...", lambda: self.browse()))
      top.addWidget(button("Read", lambda: self.read(), "Read the folder's usage files again (after a build)"))

      ## What was read, and the last build's check.
      self.notes = QtWidgets.QLabel()
      self.notes.setWordWrap(True)
      self.notes.setTextFormat(QtCore.Qt.TextFormat.RichText)

      ## The modules.
      self.modules = self._table(MODULE_COLUMNS)
      ## The script ops.
      self.ops = self._table(OP_COLUMNS)
      boxes = []
      for title, table in (("Engine modules", self.modules), ("Script ops", self.ops)):
         box = QtWidgets.QGroupBox(title)
         QtWidgets.QVBoxLayout(box).addWidget(table)
         boxes.append(box)
      tables = splitter(QtCore.Qt.Orientation.Horizontal, boxes)   # the studio's pane rules (panes.py)

      actions = QtWidgets.QHBoxLayout()
      actions.addWidget(button("Exclude all suggested", lambda: self.take_suggestion(),
                               "Tick every module and op the last build says the game can leave out"))
      actions.addWidget(button("Clear", lambda: self.clear_choices(), "Exclude nothing"))
      actions.addStretch(1)
      actions.addWidget(button("Save", lambda: self.save(),
                               "Write the game's exclusion manifest; the next build checks it and leaves out its "
                               "modules"))

      lay = QtWidgets.QVBoxLayout(self)
      lay.addLayout(top)
      lay.addWidget(self.notes)
      lay.addWidget(tables, 1)
      lay.addLayout(actions)
      self.refresh()

   def _table(self, columns: tuple[str, ...]) -> QtWidgets.QTableWidget:
      """!A read-only table but for its Excluded boxes.
      @param columns  the headings
      @return it
      """
      t = QtWidgets.QTableWidget(0, len(columns))
      t.setHorizontalHeaderLabels(list(columns))
      t.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      t.verticalHeader().setVisible(False)
      head = t.horizontalHeader()
      head.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
      head.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
      return t

   def commit(self) -> None:
      """!Nothing waits to be applied: the manifest is written by Save.
      @return None
      """

   # -- the folder ------------------------------------------------------------------------------------------------

   def _settings_key(self) -> str:
      """!The QSettings key of the project's remembered build folder (the GBA memory panel's).
      @return the key
      """
      doc = self.doc
      return SETTINGS_KEY + (str(doc.path) if doc is not None and doc.path is not None else "none")

   def build_folder(self) -> Path | None:
      """!The chosen build folder.
      @return it, or None
      """
      text = self.folder.currentText().strip()
      return Path(text) if text else None

   def browse(self, path: str | None = None) -> None:
      """!Chooses a build folder (asks when none is given).
      @param path  the folder, or None to ask
      @return None
      """
      if path is None:
         path = QtWidgets.QFileDialog.getExistingDirectory(self, "Build folder", self.folder.currentText())
         if not path:
            return
      self.use_folder(path)

   def use_folder(self, path: str) -> None:
      """!Uses a build folder (remembered for the project) and reads it.
      @param path  the folder
      @return None
      """
      if self._loading:
         return
      QtCore.QSettings().setValue(self._settings_key(), path)
      self._loading = True
      try:
         if self.folder.findText(path) < 0:
            self.folder.addItem(path)
         self.folder.setCurrentText(path)
      finally:
         self._loading = False
      self.read()

   def refresh(self) -> None:
      """!Lists the build folders near the game and reads the chosen one.
      @return None
      """
      doc = self.doc
      self._loading = True
      try:
         keep = self.folder.currentText()
         self.folder.clear()
         found: list[Path] = []
         if doc is not None and doc.path is not None:
            try:
               found = gba_memory.build_folders(project.game_folder(doc))
            except (DocumentError, OSError):
               found = []
         for p in found:
            self.folder.addItem(str(p))
         remembered = QtCore.QSettings().value(self._settings_key(), "")
         choice = keep or (str(remembered) if remembered else "") or (str(found[0]) if found else "")
         if choice and self.folder.findText(choice) < 0:
            self.folder.addItem(choice)
         self.folder.setCurrentText(choice)
      finally:
         self._loading = False
      self.read()

   # -- reading ---------------------------------------------------------------------------------------------------

   def read(self) -> bool:
      """!Reads the folder's usage files and the game's manifest.
      @return True when the folder has the game's report
      """
      self.usage = None
      self.manifest = None
      folder, doc = self.build_folder(), self.doc
      lines: list[str] = []
      try:
         if doc is None or doc.path is None:
            raise exclusion.ExclusionError("open a project to see its build usage")
         self.manifest = exclusion.read_manifest(doc)
         if folder is None:
            raise exclusion.ExclusionError("choose the build folder that built the game")
         self.usage = exclusion.read_build(folder, exclusion.game_name(doc))
      except ERRORS as e:
         lines.append(str(e))
      self._fill(lines)
      return self.usage is not None

   def _fill(self, lines: list[str]) -> None:
      """!The notes and both tables.
      @param lines  messages to show first
      @return None
      """
      usage = self.usage
      if usage is not None:
         path = None
         try:
            path = exclusion.manifest_path(self.doc)
         except exclusion.ExclusionError as e:
            lines.append(str(e))
         lines.append(f"Manifest: {path}" if path is not None else
                      f"The project names no manifest: Save creates {exclusion.DEFAULT_MANIFEST}.")
         if usage.suggestion is None:
            lines.append("The build wrote no suggestion: build the game with an engine that has the exclusion "
                         "manifest.")
         lines.append(f"GBA bytes from {usage.nm_path.name}." if usage.nm_path is not None else
                      "No GBA symbol listing in the folder: no bytes.")
      text = "<br>".join(html.escape(line) for line in lines)
      if usage is not None and usage.findings:
         text += "<br><b>The last build's check:</b>"
         for level, finding in usage.findings:
            text += f"<br><span style='color:{LEVEL_COLORS[level]}'>{level}: {html.escape(finding)}</span>"
      self.notes.setText(text)
      try:
         self.module_rows = exclusion.module_rows(usage, self.manifest) if usage is not None else []
         self.op_rows = exclusion.op_rows(usage, self.manifest) if usage is not None else []
      except exclusion.ExclusionError as e:
         self.module_rows = []
         self.op_rows = []
         self.notes.setText(str(e))
      self._fill_modules()
      self._fill_ops()

   def _box(self, checked: bool, enabled: bool, tip: str) -> QtWidgets.QTableWidgetItem:
      """!An Excluded box.
      @param checked  ticked
      @param enabled  whether it can change
      @param tip      tooltip
      @return the item
      """
      item = QtWidgets.QTableWidgetItem()
      flags = QtCore.Qt.ItemFlag.ItemIsUserCheckable
      if enabled:
         flags |= QtCore.Qt.ItemFlag.ItemIsEnabled
      item.setFlags(flags)
      item.setCheckState(QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)
      item.setToolTip(tip)
      return item

   def _fill_modules(self) -> None:
      """!The modules table.
      @return None
      """
      t = self.modules
      t.setRowCount(len(self.module_rows))
      for r, row in enumerate(self.module_rows):
         cells = (row.name, ", ".join(row.used_by), "yes" if row.game_code else "",
                  "" if row.gba_bytes is None else str(row.gba_bytes))
         for c, text in enumerate(cells):
            t.setItem(r, c, QtWidgets.QTableWidgetItem(text))
         if row.excludable:
            can = row.suggested or row.excluded
            tip = ("the build says the game can leave it out" if row.suggested else
                   "the game's own code calls it" if row.game_code else
                   "used: " + ", ".join(row.used_by) if row.used_by else "the build does not offer it")
            t.setItem(r, MODULE_EXCLUDED, self._box(row.excluded, can, tip))
         else:
            t.setItem(r, MODULE_EXCLUDED, QtWidgets.QTableWidgetItem(""))

   def _fill_ops(self) -> None:
      """!The script ops table.
      @return None
      """
      t = self.ops
      t.setRowCount(len(self.op_rows))
      for r, row in enumerate(self.op_rows):
         t.setItem(r, 0, QtWidgets.QTableWidgetItem(row.name))
         t.setItem(r, 1, QtWidgets.QTableWidgetItem(str(row.emitted) if row.emitted else ""))
         tip = "the game's scripts emit it" if row.emitted else "no script emits it"
         t.setItem(r, OP_EXCLUDED, self._box(row.excluded, row.excluded or row.emitted == 0, tip))

   # -- choosing and saving ---------------------------------------------------------------------------------------

   def chosen(self) -> tuple[list[str], list[str]]:
      """!The ticked modules and ops.
      @return (modules, ops)
      """
      def ticked(table: QtWidgets.QTableWidget, column: int) -> list[str]:
         """!Names of a table's ticked rows.
         @param table   the table
         @param column  its Excluded column
         @return the names
         """
         out = []
         for r in range(table.rowCount()):
            box = table.item(r, column)
            if box is not None and box.checkState() == QtCore.Qt.CheckState.Checked:
               out.append(table.item(r, 0).text())
         return out
      return ticked(self.modules, MODULE_EXCLUDED), ticked(self.ops, OP_EXCLUDED)

   def _tick(self, modules: set[str], ops: set[str]) -> None:
      """!Ticks exactly the named modules and ops (where their box can change).
      @param modules  modules to tick
      @param ops      ops to tick
      @return None
      """
      for table, column, names in ((self.modules, MODULE_EXCLUDED, modules), (self.ops, OP_EXCLUDED, ops)):
         for r in range(table.rowCount()):
            box = table.item(r, column)
            if box is None or not box.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
               continue
            on = table.item(r, 0).text() in names
            box.setCheckState(QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)

   def take_suggestion(self) -> bool:
      """!Ticks what the build suggests.
      @return True when the build wrote a suggestion
      """
      if self.usage is None or self.usage.suggestion is None:
         self.host.show_status("Exclude all suggested: the build folder has no suggestion for this game")
         return False
      self._tick(set(exclusion.names(self.usage.suggestion, exclusion.MODULES)),
                 set(exclusion.names(self.usage.suggestion, exclusion.SCRIPT_OPS)))
      return True

   def clear_choices(self) -> None:
      """!Unticks everything.
      @return None
      """
      self._tick(set(), set())

   def save(self) -> bool:
      """!Writes the game's manifest from the ticked boxes.
      @return True when written
      """
      if self.usage is None:
         self.host.show_status("Save: read a build folder that built the game first")
         return False
      modules, ops = self.chosen()
      try:
         manifest = exclusion.build_manifest(self.usage, modules, ops, self.manifest)
         path, added = exclusion.save(self.doc, manifest)
      except ERRORS as e:
         self.host.show_status(f"Save: {e}")
         return False
      self.manifest = manifest
      self.host.show_status(f"Wrote {path.name}: {len(modules)} modules, {len(ops)} script ops excluded"
                            + ("; the project now names it (save the project)" if added else "")
                            + " - the next build checks it")
      self._fill([])
      return True
