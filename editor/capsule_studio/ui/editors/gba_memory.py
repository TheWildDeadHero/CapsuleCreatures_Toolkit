"""![S6] The project settings window's GBA memory panel (engine UM, D-33; core.gba_memory).

The screen arena's size is a game's build setting (screen_arena_bytes, on the Build settings tab); the GBA link's
memory checks and its stack reserve are a build folder's (CMake cache settings), so this panel edits them in the
build folder chosen at the top, as cmake-gui would: the next build reads them. A cache value of the arena overrides
every game's setting and is shown (and can be cleared) here.

Below: each GBA program's memory use, as the engine prints it after every link: read from the folder's linked
programs with nm, or from a saved build log (its report lines and any link failure): EWRAM used and free of 256 KB,
IWRAM code and data, the stack left against the reserve, and the screen arena's share of the EWRAM a program uses.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import engine, gba_memory, project
from ..panel import EditorPanel
from ..widgets import button

if TYPE_CHECKING:
   from ..panel import PanelHost

## Errors a build folder or a program can give.
ERRORS = (gba_memory.GbaMemoryError, OSError, ValueError, engine.EngineNotFound)
## QSettings key prefix of the build folder remembered per project.
SETTINGS_KEY = "gba_memory/build_folder/"
## Arrow step of the stack reserve, bytes.
RESERVE_STEP = 256
## The report table's columns.
COLUMNS = ("Program", "EWRAM used", "EWRAM free", "IWRAM code + data", "Stack", "Reserve", "Fits")
## Column of the verdict.
FITS_COLUMN = len(COLUMNS) - 1
## Colours of a program that fits and of one that does not.
FIT_COLORS = {True: "#208040", False: "#c03030"}
## Log file filter.
LOG_FILTER = "Build output (*.log *.txt);;All files (*)"
## Widest a number widget gets, pixels.
VALUE_WIDTH = 140


class GbaMemoryPanel(EditorPanel):
   """!A build folder's GBA memory settings and its programs' memory report."""

   ## See EditorPanel.panel_id.
   panel_id = "gba_memory"
   ## See EditorPanel.title.
   title = "GBA memory"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## True while widgets are being filled.
      self._loading = False
      ## The reports shown.
      self.reports: list[gba_memory.Report] = []
      ## Lines shown under the table (failures, programs not read).
      self._notes: list[str] = []

      ## The build folder.
      self.folder = QtWidgets.QComboBox()
      self.folder.setEditable(True)
      self.folder.setToolTip("A configured build folder (its CMakeCache.txt); GBA folders are listed first")
      self.folder.activated.connect(lambda _i: self.use_folder(self.folder.currentText()))
      self.folder.lineEdit().editingFinished.connect(lambda: self.use_folder(self.folder.currentText()))
      top = QtWidgets.QHBoxLayout()
      top.addWidget(QtWidgets.QLabel("Build folder"))
      top.addWidget(self.folder, 1)
      top.addWidget(button("Browse...", lambda: self.browse()))

      ## The memory checks.
      self.checks = QtWidgets.QCheckBox(f"Fail the link when the program does not fit ({gba_memory.CHECKS})")
      self.checks.setToolTip("Off only to measure a program that does not fit; never for a ROM that runs")
      self.checks.clicked.connect(lambda on: self._set(gba_memory.CHECKS, "ON" if on else "OFF"))
      ## The stack reserve.
      self.reserve = QtWidgets.QSpinBox()
      self.reserve.setRange(gba_memory.MIN_RESERVE, gba_memory.MAX_RESERVE)
      self.reserve.setSingleStep(RESERVE_STEP)
      self.reserve.setSuffix(" B")
      self.reserve.setMaximumWidth(VALUE_WIDTH)
      self.reserve.setKeyboardTracking(False)
      self.reserve.valueChanged.connect(lambda v: self._set(gba_memory.RESERVE, str(v)))
      ## The arena override.
      self.arena_override = QtWidgets.QCheckBox("Override every game's screen arena in this folder")
      self.arena_override.clicked.connect(lambda on: self._arena_toggled(on))
      ## Its bytes.
      self.arena = QtWidgets.QSpinBox()
      bs = project.settings_tool()
      arena_setting = bs.BY_KEY.get("screen_arena_bytes")
      if arena_setting is not None:
         self.arena.setRange(arena_setting.lo, arena_setting.hi)
         self.arena.setSingleStep(getattr(arena_setting, "multiple", 1))
      self.arena.setSuffix(" B")
      self.arena.setMaximumWidth(VALUE_WIDTH)
      self.arena.setKeyboardTracking(False)
      self.arena.valueChanged.connect(lambda v: self._set(gba_memory.ARENA, str(v)) if
                                      self.arena_override.isChecked() else None)
      ## The game's own arena setting.
      self.game_arena = QtWidgets.QLabel()
      self.game_arena.setWordWrap(True)
      settings = QtWidgets.QGroupBox("Link settings (CMake cache of the build folder; read at the next build)")
      form = QtWidgets.QFormLayout(settings)
      form.addRow(self.checks)
      form.addRow(f"Stack reserve ({gba_memory.RESERVE})", self.reserve)
      arena_row = QtWidgets.QHBoxLayout()
      arena_row.addWidget(self.arena_override)
      arena_row.addWidget(self.arena)
      arena_row.addStretch(1)
      form.addRow(arena_row)
      form.addRow(self.game_arena)

      ## The report.
      self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
      self.table.setHorizontalHeaderLabels(list(COLUMNS))
      self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
      head = self.table.horizontalHeader()
      head.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
      head.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
      self.table.currentCellChanged.connect(lambda *_a: self._row_picked())
      ## The chosen program's notes (what does not fit, the arena's share), failures, unread programs.
      self.notes = QtWidgets.QLabel()
      self.notes.setWordWrap(True)
      self.notes.setTextFormat(QtCore.Qt.TextFormat.PlainText)
      report = QtWidgets.QGroupBox("Memory report (as the engine prints it after each GBA link)")
      rl = QtWidgets.QVBoxLayout(report)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Read the folder's programs", lambda: self.read_programs(),
                           "Each linked GBA program of the folder, read with nm (no build needed)"))
      row.addWidget(button("Open build log...", lambda: self.open_log(),
                           "A saved build's output: its report lines and any link failure"))
      row.addStretch(1)
      rl.addLayout(row)
      rl.addWidget(self.table, 1)
      rl.addWidget(self.notes)

      lay = QtWidgets.QVBoxLayout(self)
      lay.addLayout(top)
      lay.addWidget(settings)
      lay.addWidget(report, 1)
      self.refresh()

   def commit(self) -> None:
      """!Nothing waits to be applied (every change is written to the build folder at once); the project window
      calls this before saving or closing.
      @return None
      """

   # -- the folder ------------------------------------------------------------------------------------------------

   def _settings_key(self) -> str:
      """!The QSettings key of the project's remembered build folder.
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
      """!Uses a build folder (remembered for the project).
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
      self.reports.clear()
      self._fill_settings()
      self._fill_report([], [])

   def refresh(self) -> None:
      """!Lists the build folders near the game and shows the chosen one.
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
            except (project.DocumentError, OSError):
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
      self._fill_settings()

   def _fill_settings(self) -> None:
      """!The folder's settings, and the game's arena setting.
      @return None
      """
      folder = self.build_folder()
      self._loading = True
      try:
         try:
            s = gba_memory.settings(folder) if folder is not None else None
            error = None
         except ERRORS as e:
            s, error = None, str(e)
         for w in (self.checks, self.reserve, self.arena_override):
            w.setEnabled(s is not None)
         self.arena.setEnabled(s is not None and s.arena is not None)
         if s is not None:
            self.checks.setChecked(s.checks)
            self.reserve.setValue(s.reserve)
            self.arena_override.setChecked(s.arena is not None)
            if s.arena is not None:
               self.arena.setValue(s.arena)
         game = self._game_arena()
         lines = [f"This game's screen arena: {game} B (screen_arena_bytes, the Build settings tab)."
                  if game is not None else "Open a project to see its screen arena setting."]
         if s is not None and s.arena is not None:
            lines.append(f"The folder's {gba_memory.ARENA} = {s.arena} B overrides it.")
         if s is not None and not s.gba:
            lines.append("This folder does not configure a GBA build: the settings apply to GBA links only.")
         if error:
            lines.append(error)
         self.game_arena.setText(" ".join(lines))
      finally:
         self._loading = False

   def _game_arena(self) -> int | None:
      """!The project's screen arena setting.
      @return bytes, or None without a project (or an engine before UM)
      """
      doc = self.doc
      if doc is None:
         return None
      try:
         row = next((r for r in project.rows(doc) if r.key == "screen_arena_bytes"), None)
      except (project.DocumentError, engine.EngineNotFound):
         return None
      return row.value if row is not None else None

   def _set(self, name: str, value: str) -> bool:
      """!Writes one cache setting of the folder.
      @param name   the cache name
      @param value  its value ("" clears the arena override)
      @return True when written
      """
      folder = self.build_folder()
      if self._loading or folder is None:
         return False
      try:
         gba_memory.set_cache(folder, name, value)
      except ERRORS as e:
         self.host.show_status(str(e))
         self._fill_settings()
         return False
      self.host.show_status(f"{name} = {value or '(default)'} in {folder.name} (read at the next build)")
      self._fill_settings()
      return True

   def _arena_toggled(self, on: bool) -> None:
      """!The arena override on (the game's value to start from) or off (cleared).
      @param on  override
      @return None
      """
      if on:
         start = self._game_arena() or self.arena.value()
         self._loading = True
         self.arena.setValue(start)
         self._loading = False
         self._set(gba_memory.ARENA, str(start))
      else:
         self._set(gba_memory.ARENA, "")

   # -- the report ------------------------------------------------------------------------------------------------

   def read_programs(self) -> bool:
      """!Reads each linked GBA program of the folder with nm.
      @return True when at least one was read
      """
      folder = self.build_folder()
      if folder is None:
         return False
      try:
         reports, errors = gba_memory.folder_reports(folder)
      except ERRORS as e:
         self._fill_report([], [str(e)])
         return False
      if not reports and not errors:
         errors = [f"no linked GBA program (*.elf) in {folder}"]
      self._fill_report(reports, [f"not read: {e}" for e in errors])
      return bool(reports)

   def open_log(self, path: str | None = None) -> bool:
      """!Reads a build's output (asks for the file when none is given).
      @param path  the log, or None to ask
      @return True when it has report lines or failures
      """
      if path is None:
         path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Build log", "", LOG_FILTER)
         if not path:
            return False
      try:
         text = Path(path).read_text(encoding="utf-8", errors="replace")
      except OSError as e:
         self.host.show_status(str(e))
         return False
      reports, failures = gba_memory.parse_log(text)
      notes = [f"link failed: {f}" for f in failures]
      if not reports and not failures:
         notes = [f"{Path(path).name} has no GBA memory report lines"]
      self._fill_report(reports, notes)
      return bool(reports or failures)

   def _fill_report(self, reports: list[gba_memory.Report], notes: list[str]) -> None:
      """!The report table.
      @param reports  the programs' reports
      @param notes    lines shown under it
      @return None
      """
      self.reports[:] = reports   # in place (Doxygen 1.12 reads a second assignment as a new member)
      self._notes[:] = notes
      self.table.setRowCount(len(reports))
      for r, rep in enumerate(reports):
         cells = (rep.name, f"{rep.ewram_used} of {rep.ewram_bytes}", str(rep.ewram_free),
                  f"{rep.iwram_used} of {rep.iwram_bytes}", str(rep.stack), str(rep.reserve),
                  "yes" if rep.fits else "NO")
         for c, text in enumerate(cells):
            item = QtWidgets.QTableWidgetItem(text)
            if c == FITS_COLUMN:
               item.setForeground(QtGui.QColor(FIT_COLORS[rep.fits]))
            self.table.setItem(r, c, item)
      if reports:
         self.table.setCurrentCell(0, 0)
      self._row_picked()

   def _row_picked(self) -> None:
      """!The chosen program's notes.
      @return None
      """
      lines = list(self._notes)
      r = self.table.currentRow()
      if 0 <= r < len(self.reports):
         rep = self.reports[r]
         lines = rep.problems() + lines
         s = None
         folder = self.build_folder()
         try:
            s = gba_memory.settings(folder) if folder is not None else None
         except ERRORS:
            s = None
         arena = s.arena if s is not None and s.arena is not None else self._game_arena()
         if arena:
            lines.append(gba_memory.arena_share(rep, arena))
      self.notes.setText("\n".join(lines))
