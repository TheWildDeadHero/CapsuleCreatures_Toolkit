"""!The Studio's Build and Build and Debug buttons, their Build menu and the Build log (core.game_build).

  - **Build** (Ctrl+B) builds the open game for the target chosen in its drop-down: this computer (the preset
    family of the system the Studio runs on), the Game Boy Advance, the Dreamcast (not on Windows), or every one of
    them; with the release preset unless the drop-down's Debug preset is ticked.
  - **Build and Debug** (F5) builds the debug preset of the target chosen in its own drop-down and starts the
    result: the executable, the ROM in mGBA (No$GBA when mGBA is not found), the disc image in Flycast. Its
    drop-down's Choose emulator... names a program instead of looking for one.
  - **Stop** (Shift+F5) stops the build, or the game it started.

Both first save every page with unsaved changes (a page that fails to save stops the build). The steps are the
same as ./build PRESET --game FOLDER and `capsule-studio build`; their output goes to the Build log at the bottom
of the window, which opens with the build. The choices are remembered per game; the emulators for every game.
"""
from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import game_build
from .widgets import headless, report_failure

## Settings file of the Studio (as widgets.remember_file()).
SETTINGS = ("CapsuleCreatures", "capsule-studio")
## Settings key prefix of a game's choices (followed by the game folder's hash and the choice's name).
CHOICE_KEY = "build/game/"
## Settings key prefix of the emulator chosen for a kind of run (followed by the kind: gba, dreamcast).
EMULATOR_KEY = "build/emulator/"
## The Build drop-down's choice that builds every target.
ALL_TARGETS = "all"
## Title of the buttons, menus and messages.
BUILD = "Build"
BUILD_AND_DEBUG = "Build and Debug"
## Title of the Build log.
LOG_TITLE = "Build log"
## Lines the Build log keeps (older ones are dropped).
LOG_LINES = 20000
## Height the Build log opens with, pixels (drag its edge to change it).
LOG_HEIGHT = 220
## Space around the Build log's row of buttons, pixels.
LOG_MARGIN = 4
## Shortcuts.
BUILD_KEY = "Ctrl+B"
DEBUG_KEY = "F5"
STOP_KEY = "Shift+F5"
## The methods a page saves everything with, tried in order (World/Scripts/Battle, Assets, Project/Audio).
SAVE_METHODS = ("save_all", "save_file", "save")
## Program files for the Choose emulator... dialog.
EMULATOR_FILTER = "Programs (*.exe *.EXE mgba* mGBA* flycast* redream* lxdream*);;All files (*)"
## Windows programs, which run in Wine off Windows (No$GBA).
WINDOWS_PROGRAM = ".exe"


def _settings() -> QtCore.QSettings:
   """!The Studio's settings.
   @return QSettings
   """
   return QtCore.QSettings(*SETTINGS)


def emulator_command(path: str) -> list[str]:
   """!The command of an emulator program the user chose: a Windows program runs in Wine off Windows.
   @param path  the program
   @return the command
   """
   if sys.platform != "win32" and path.lower().endswith(WINDOWS_PROGRAM):
      return ["wine", path]
   return [path]


class BuildLog(QtWidgets.QDockWidget):
   """!The Build log: every step's command and output, with Stop and Clear."""

   def __init__(self, stop: Callable[[], None], parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the log.
      @param stop    called by its Stop button
      @param parent  the Studio window
      """
      super().__init__(LOG_TITLE, parent)
      self.setObjectName("build_log")
      ## The log's text.
      self.text = QtWidgets.QPlainTextEdit()
      self.text.setReadOnly(True)
      self.text.setMaximumBlockCount(LOG_LINES)
      self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
      self.text.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
      ## What runs now.
      self.state = QtWidgets.QLabel("Nothing has been built yet")
      ## Stops the build or the game.
      self.stop_button = QtWidgets.QPushButton("Stop")
      self.stop_button.setEnabled(False)
      self.stop_button.clicked.connect(lambda _c=False: stop())
      clear = QtWidgets.QPushButton("Clear")
      clear.clicked.connect(lambda _c=False: self.text.clear())
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.state, 1)
      row.addWidget(self.stop_button)
      row.addWidget(clear)
      box = QtWidgets.QWidget()
      layout = QtWidgets.QVBoxLayout(box)
      layout.setContentsMargins(0, 0, 0, 0)
      row.setContentsMargins(LOG_MARGIN, LOG_MARGIN, LOG_MARGIN, 0)
      layout.addLayout(row)
      layout.addWidget(self.text)
      self.setWidget(box)

   def add(self, line: str) -> None:
      """!Adds a line (the view follows the end only while it is scrolled to the end).
      @param line  the line
      @return None
      """
      self.text.appendPlainText(line)

   def lines(self) -> list[str]:
      """!The log's lines (tests).
      @return lines
      """
      return self.text.toPlainText().splitlines()


class BuildBar(QtCore.QObject):
   """!The Build toolbar, the Build menu and the Build log of a Studio window, and the build that runs."""

   ## Emitted when a build (and its run, if any) has finished: True when every step succeeded.
   finished = QtCore.Signal(bool)

   def __init__(self, window: QtWidgets.QMainWindow, project_path: Callable[[], Path | None],
                save_pages: Callable[[], bool]) -> None:
      """!Adds the toolbar, the menu and the log to the window.
      @param window        the Studio window
      @param project_path  gives the open game's reference/project.json, or None
      @param save_pages    saves every page with unsaved changes; False when one could not be saved
      """
      super().__init__(window)
      self._window = window
      self._project_path = project_path
      self._save_pages = save_pages
      ## Every target this computer builds.
      self.targets = game_build.targets()
      ## The Build drop-down's choice (a target id or ALL_TARGETS) and preset.
      self.build_choice = self.targets[0].target_id
      self.build_debug = False
      ## The Build and Debug drop-down's choice.
      self.debug_choice = self.targets[0].target_id
      ## Plans still to run, the step queue of the one running, and the one running.
      self._plans: list[game_build.BuildPlan] = []
      self._steps: list[game_build.Step] = []
      self._plan: game_build.BuildPlan | None = None
      ## Targets that failed in this build (for the summary).
      self._failed: list[str] = []
      ## The program running now, or None.
      self.process: QtCore.QProcess | None = None
      ## True while the game (the run step) is what runs.
      self.running_game = False
      ## Unfinished output line of the program running.
      self._partial = ""
      ## The Build log.
      self.log = BuildLog(lambda: self.stop(), window)
      window.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.log)
      self.log.hide()
      ## Whether the log has been given its first height.
      self._log_sized = False
      self._build_actions()

   # -- toolbar and menus -------------------------------------------------------------------------------------------

   def _build_actions(self) -> None:
      """!The two drop-down buttons, Stop, and the Build menu holding the same actions.
      @return None
      """
      w = self._window
      ## Build (the Build button's own action).
      self.build_action = QtGui.QAction(BUILD, w)
      self.build_action.setShortcut(QtGui.QKeySequence(BUILD_KEY))
      self.build_action.triggered.connect(lambda _c=False: self.build())
      ## Build and Debug.
      self.debug_action = QtGui.QAction(BUILD_AND_DEBUG, w)
      self.debug_action.setShortcut(QtGui.QKeySequence(DEBUG_KEY))
      self.debug_action.triggered.connect(lambda _c=False: self.build_and_debug())
      ## Stop.
      self.stop_action = QtGui.QAction("Stop", w)
      self.stop_action.setShortcut(QtGui.QKeySequence(STOP_KEY))
      self.stop_action.setEnabled(False)
      self.stop_action.triggered.connect(lambda _c=False: self.stop())
      ## Show build log.
      self.log_action = self.log.toggleViewAction()
      self.log_action.setText("Show build &log")

      ## The Build button's drop-down: what to build, and the preset.
      self.build_menu = QtWidgets.QMenu(BUILD, w)
      group = QtGui.QActionGroup(self.build_menu)
      ## Target id (or ALL_TARGETS) -> its action in the Build drop-down.
      self.build_choices: dict[str, QtGui.QAction] = {}
      for t in self.targets:
         self.build_choices[t.target_id] = self._choice(self.build_menu, group, t.title, t.target_id, True)
      self.build_choices[ALL_TARGETS] = self._choice(self.build_menu, group, "All targets", ALL_TARGETS, True)
      self.build_menu.addSeparator()
      ## Debug preset instead of release.
      self.debug_preset_action = QtGui.QAction("Debug preset", self.build_menu)
      self.debug_preset_action.setCheckable(True)
      self.debug_preset_action.setToolTip("Build the debug preset (gba-debug, ...) instead of the release preset")
      self.debug_preset_action.toggled.connect(lambda on: self._set_build_debug(on))
      self.build_menu.addAction(self.debug_preset_action)
      self.build_menu.addSeparator()
      self.build_menu.addAction(self.log_action)

      ## The Build and Debug button's drop-down: what to build and start, and the emulators.
      self.debug_menu = QtWidgets.QMenu(BUILD_AND_DEBUG, w)
      group = QtGui.QActionGroup(self.debug_menu)
      ## Target id -> its action in the Build and Debug drop-down.
      self.debug_choices: dict[str, QtGui.QAction] = {}
      for t in self.targets:
         self.debug_choices[t.target_id] = self._choice(self.debug_menu, group, t.title, t.target_id, False)
      self.debug_menu.addSeparator()
      ## Run kind -> Choose emulator... action.
      self.emulator_actions: dict[str, QtGui.QAction] = {}
      for t in self.targets:
         if t.run_kind == game_build.RUN_NATIVE:
            continue
         a = QtGui.QAction(f"Choose {t.title} emulator...", self.debug_menu)
         a.triggered.connect(lambda _c=False, kind=t.run_kind: self.choose_emulator(kind))
         self.debug_menu.addAction(a)
         self.emulator_actions[t.run_kind] = a
      self.debug_menu.addSeparator()
      self.debug_menu.addAction(self.log_action)

      ## The Build toolbar.
      self.toolbar = QtWidgets.QToolBar(BUILD, w)
      self.toolbar.setObjectName("build_toolbar")
      self.toolbar.setMovable(False)
      ## The Build button (click: build; arrow: the drop-down).
      self.build_button = self._menu_button(self.build_action, self.build_menu)
      ## The Build and Debug button.
      self.debug_button = self._menu_button(self.debug_action, self.debug_menu)
      self.toolbar.addWidget(self.build_button)
      self.toolbar.addWidget(self.debug_button)
      self.toolbar.addAction(self.stop_action)
      w.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, self.toolbar)

      ## The window's Build menu (the menu bar's; the Studio places it).
      self.menu = QtWidgets.QMenu("&Build", w)
      self.menu.addAction(self.build_action)
      self.menu.addMenu(self.build_menu).setText("Build &target")
      self.menu.addAction(self.debug_action)
      self.menu.addMenu(self.debug_menu).setText("Build and Debug t&arget")
      self.menu.addAction(self.stop_action)
      self.menu.addSeparator()
      self.menu.addAction(self.log_action)
      self.game_changed()

   def _choice(self, menu: QtWidgets.QMenu, group: QtGui.QActionGroup, title: str, choice: str,
               build: bool) -> QtGui.QAction:
      """!One exclusive choice of a drop-down.
      @param menu    the drop-down
      @param group   its exclusive group
      @param title   shown
      @param choice  target id or ALL_TARGETS
      @param build   True in the Build drop-down, False in Build and Debug's
      @return the action
      """
      a = QtGui.QAction(title, menu)
      a.setCheckable(True)
      a.setData(choice)
      group.addAction(a)
      a.triggered.connect(lambda _c=False, c=choice, b=build: self.choose(c, b))
      menu.addAction(a)
      return a

   def _menu_button(self, action: QtGui.QAction, menu: QtWidgets.QMenu) -> QtWidgets.QToolButton:
      """!A toolbar button that runs an action and drops down a menu.
      @param action  what a click does
      @param menu    the drop-down
      @return the button
      """
      b = QtWidgets.QToolButton()
      b.setDefaultAction(action)
      b.setMenu(menu)
      b.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.MenuButtonPopup)
      b.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
      return b

   # -- choices -----------------------------------------------------------------------------------------------------

   def _game_key(self, name: str) -> str | None:
      """!The settings key of one of the open game's choices.
      @param name  the choice's name
      @return the key, or None with no game open
      """
      path = self._project_path()
      if path is None:
         return None
      digest = hashlib.sha1(str(Path(path).resolve()).encode("utf-8")).hexdigest()
      return f"{CHOICE_KEY}{digest}/{name}"

   def _remember(self, name: str, value: str) -> None:
      """!Remembers one of the open game's choices.
      @param name   the choice's name
      @param value  its value
      @return None
      """
      key = self._game_key(name)
      if key is not None:
         _settings().setValue(key, value)

   def _recall(self, name: str, default: str) -> str:
      """!One of the open game's remembered choices.
      @param name     the choice's name
      @param default  when none is remembered
      @return the value
      """
      key = self._game_key(name)
      value = _settings().value(key, default) if key is not None else default
      return value if isinstance(value, str) else default

   def choose(self, choice: str, build: bool) -> None:
      """!Picks what a button builds.
      @param choice  target id, or ALL_TARGETS (Build only)
      @param build   True for the Build button, False for Build and Debug
      @return None
      """
      ids = {t.target_id for t in self.targets}
      if build and (choice in ids or choice == ALL_TARGETS):
         self.build_choice = choice
         self._remember("build", choice)
      elif not build and choice in ids:
         self.debug_choice = choice
         self._remember("debug", choice)
      self._sync_choices()

   def _set_build_debug(self, on: bool) -> None:
      """!Build's preset: debug or release.
      @param on  True for the debug preset
      @return None
      """
      self.build_debug = on
      self._remember("build_debug", "1" if on else "0")
      self._sync_choices()

   def _title(self, choice: str) -> str:
      """!What a choice is called.
      @param choice  target id or ALL_TARGETS
      @return its title
      """
      if choice == ALL_TARGETS:
         return "All targets"
      return next((t.title for t in self.targets if t.target_id == choice), choice)

   def _sync_choices(self) -> None:
      """!Ticks the choices and names them in the buttons' tooltips.
      @return None
      """
      self.build_choices[self.build_choice].setChecked(True)
      self.debug_choices[self.debug_choice].setChecked(True)
      self.debug_preset_action.blockSignals(True)
      self.debug_preset_action.setChecked(self.build_debug)
      self.debug_preset_action.blockSignals(False)
      preset = "debug" if self.build_debug else "release"
      self.build_action.setToolTip(f"Build the game for {self._title(self.build_choice)} ({preset} preset; "
                                   f"{BUILD_KEY}). The arrow picks what to build.")
      self.debug_action.setToolTip(f"Build the debug preset for {self._title(self.debug_choice)} and start it "
                                   f"({DEBUG_KEY}). The arrow picks what to build and start.")

   def game_changed(self) -> None:
      """!Takes up the open game's remembered choices (the Studio calls it when a game opens).
      @return None
      """
      ids = {t.target_id for t in self.targets}
      first = self.targets[0].target_id
      choice = self._recall("build", first)
      self.build_choice = choice if choice in ids or choice == ALL_TARGETS else first
      choice = self._recall("debug", first)
      self.debug_choice = choice if choice in ids else first
      self.build_debug = self._recall("build_debug", "0") == "1"
      self._sync_choices()
      self._sync_enabled()

   def _sync_enabled(self) -> None:
      """!Build buttons need a game and nothing building; Stop needs something running.
      @return None
      """
      has_game = self._project_path() is not None
      building = self.process is not None and not self.running_game
      self.build_action.setEnabled(has_game and not building)
      self.debug_action.setEnabled(has_game and not building)
      self.stop_action.setEnabled(self.process is not None)
      self.log.stop_button.setEnabled(self.process is not None)

   # -- emulators ---------------------------------------------------------------------------------------------------

   def emulator(self, kind: str) -> list[str] | None:
      """!The emulator chosen for a kind of run.
      @param kind  game_build.RUN_GBA or RUN_DREAMCAST
      @return its command, or None to look for one
      """
      value = _settings().value(EMULATOR_KEY + kind, "")
      return emulator_command(value) if isinstance(value, str) and value else None

   def set_emulator(self, kind: str, path: str | None) -> None:
      """!Names the emulator for a kind of run.
      @param kind  game_build.RUN_GBA or RUN_DREAMCAST
      @param path  the program, or None to look for one again
      @return None
      """
      if path:
         _settings().setValue(EMULATOR_KEY + kind, path)
      else:
         _settings().remove(EMULATOR_KEY + kind)

   def choose_emulator(self, kind: str) -> None:
      """!Asks for the emulator of a kind of run (Cancel keeps it; Look for one clears it).
      @param kind  game_build.RUN_GBA or RUN_DREAMCAST
      @return None
      """
      chosen = self.emulator(kind)
      box = QtWidgets.QMessageBox(self._window)
      box.setWindowTitle("Choose emulator")
      box.setText("Emulator in use: " + (chosen[-1] if chosen else "the first one found on this computer"))
      pick = box.addButton("Choose program...", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
      find = box.addButton("Look for one", QtWidgets.QMessageBox.ButtonRole.ResetRole)
      box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
      box.exec()
      if box.clickedButton() is find:
         self.set_emulator(kind, None)
      elif box.clickedButton() is pick:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self._window, "Choose emulator",
                                                         str(Path(chosen[-1]).parent) if chosen else "",
                                                         EMULATOR_FILTER)
         if path:
            self.set_emulator(kind, path)

   # -- building ----------------------------------------------------------------------------------------------------

   def build(self) -> bool:
      """!Build: the Build drop-down's choice and preset.
      @return True when the build started
      """
      ids = None if self.build_choice == ALL_TARGETS else [self.build_choice]
      return self._start(ids, self.build_debug, False)

   def build_and_debug(self) -> bool:
      """!Build and Debug: the debug preset of the drop-down's choice, then the game.
      @return True when the build started
      """
      return self._start([self.debug_choice], True, True)

   def _start(self, ids: list[str] | None, debug: bool, run: bool) -> bool:
      """!Saves every page, plans the builds and starts the first.
      @param ids    target ids, or None for every target
      @param debug  True for debug presets
      @param run    True to start the result
      @return True when the build started
      """
      path = self._project_path()
      title = BUILD_AND_DEBUG if run else BUILD
      if path is None:
         report_failure(self._window, title, "Open a game first.")
         return False
      if self.process is not None:
         if not self.running_game:
            return False   # a build is running (the buttons are off)
         self.stop()   # the game it started: the new build replaces its files
      if not self._save_pages():
         report_failure(self._window, title, "A page could not be saved, so nothing was built.")
         return False
      try:
         builds = game_build.plans(path, ids, debug, run)
      except (ValueError, KeyError) as e:
         report_failure(self._window, title, str(e))
         return False
      if run:   # an emulator chosen in Build and Debug's drop-down comes before the ones found
         for b in builds:
            command = self.emulator(b.target.run_kind) if b.target.run_kind != game_build.RUN_NATIVE else None
            if command is not None:
               b.run = game_build.run_step(b.target, b.out, b.name, command)
               b.run_problem = ""
      self.show_log()
      self.log.add(f"==== {title}: {builds[0].name} for " + ", ".join(b.target.title for b in builds))
      if all(b.problems for b in builds):
         missing = [f"{b.target.title}: {p}" for b in builds for p in b.problems]
         for b in builds:
            for p in b.problems:
               self.log.add(f"error: {b.target.title}: missing {p}")
         report_failure(self._window, title, "This computer is missing what the build needs:\n\n"
                        + "\n".join(missing))
         self.log.state.setText("Not built: something is missing")
         return False
      self._plans = builds
      self._failed = []
      self._next_plan()
      return True

   def _next_plan(self) -> None:
      """!Starts the next target's build, or finishes.
      @return None
      """
      while self._plans:
         self._plan = self._plans.pop(0)
         if self._plan.problems:
            for p in self._plan.problems:
               self.log.add(f"error: {self._plan.target.title}: missing {p}")
            self._failed.append(self._plan.target.title)
            continue
         self._steps = list(self._plan.steps)
         self._next_step()
         return
      self._plan = None
      self._finish()

   def _next_step(self) -> None:
      """!Starts the plan's next step; after the last, the game (Build and Debug) or the next plan.
      @return None
      """
      plan = self._plan
      assert plan is not None
      if not self._steps:
         output = plan.output()
         self.log.add(f"built {plan.name} for {plan.target.title}: {output if output is not None else plan.out}")
         if plan.run is not None or plan.run_problem:
            self._start_game(plan, output)
            return
         self._next_plan()
         return
      self._launch(self._steps.pop(0), False)

   def _start_game(self, plan: game_build.BuildPlan, output: Path | None) -> None:
      """!Starts the built game (Build and Debug).
      @param plan    the plan just built
      @param output  what it made, or None
      @return None
      """
      problem = plan.run_problem
      if not problem and output is None:
         problem = f"the build made no {game_build.TARGET_PREFIX}{plan.name}{plan.target.output_suffix} to start"
      if problem:
         self.log.add(f"error: {problem}")
         self._failed.append(plan.target.title)
         hint = "" if plan.target.run_kind == game_build.RUN_NATIVE else \
            f"\n\nBuild and Debug's drop-down has Choose {plan.target.title} emulator..."
         report_failure(self._window, BUILD_AND_DEBUG, f"Built, but not started: {problem}.{hint}")
         self._next_plan()
         return
      assert plan.run is not None
      step = game_build.run_step(plan.target, plan.out, plan.name, plan.run.argv[:-1])
      assert step is not None
      self._launch(step, True)

   def _launch(self, step: game_build.Step, game: bool) -> None:
      """!Runs one step's program.
      @param step  the step
      @param game  True for the game (Build and Debug's last step)
      @return None
      """
      self.log.add(f"== {step.title}")
      self.log.add(f"$ {step.shown()}")
      self.log.state.setText(step.title + "...")
      p = QtCore.QProcess(self)
      p.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
      p.setWorkingDirectory(str(step.cwd))
      env = QtCore.QProcessEnvironment.systemEnvironment()
      for k, v in step.env.items():
         env.insert(k, v)
      p.setProcessEnvironment(env)
      p.readyReadStandardOutput.connect(lambda proc=p: self._read(proc))
      p.finished.connect(lambda code, status, proc=p, s=step: self._step_done(proc, s, code, status))
      p.errorOccurred.connect(lambda error, proc=p, s=step: self._step_error(proc, s, error))
      self.process = p
      self.running_game = game
      self._partial = ""
      self._sync_enabled()
      p.start(step.program(), step.argv[1:])

   def _read(self, proc: QtCore.QProcess) -> None:
      """!Adds the program's output to the log, line by line.
      @param proc  the program
      @return None
      """
      text = self._partial + bytes(proc.readAllStandardOutput().data()).decode("utf-8", "replace")
      lines = text.replace("\r\n", "\n").split("\n")
      self._partial = lines.pop()
      for line in lines:
         self.log.add(line)

   def _flush(self, proc: QtCore.QProcess) -> None:
      """!Adds what is left of the program's output.
      @param proc  the program
      @return None
      """
      self._read(proc)
      if self._partial:
         self.log.add(self._partial)
         self._partial = ""

   def _step_done(self, proc: QtCore.QProcess, step: game_build.Step, code: int,
                  status: QtCore.QProcess.ExitStatus) -> None:
      """!A step's program ended: the next step, or the build stops.
      @param proc    the program
      @param step    its step
      @param code    exit code
      @param status  normal exit or crash
      @return None
      """
      if proc is not self.process:
         return   # stopped already
      self._flush(proc)
      self.process = None
      game = self.running_game
      self.running_game = False
      proc.deleteLater()
      ok = status == QtCore.QProcess.ExitStatus.NormalExit and code == 0
      if game:
         self.log.add(f"the game ended (exit status {code})" if status == QtCore.QProcess.ExitStatus.NormalExit
                      else "the game crashed")
         self._next_plan()
         return
      if not ok:
         self._fail(step, f"exit status {code}" if status == QtCore.QProcess.ExitStatus.NormalExit else "crashed")
         return
      self._next_step()

   def _step_error(self, proc: QtCore.QProcess, step: game_build.Step, error: QtCore.QProcess.ProcessError) -> None:
      """!A step's program could not start.
      @param proc   the program
      @param step   its step
      @param error  what went wrong
      @return None
      """
      if proc is not self.process or error != QtCore.QProcess.ProcessError.FailedToStart:
         return   # other errors end in finished()
      self.process = None
      self.running_game = False
      proc.deleteLater()
      self._fail(step, f"cannot start {step.argv[0]}")

   def _fail(self, step: game_build.Step, why: str) -> None:
      """!A step failed: this target stops; the others go on.
      @param step  the step
      @param why   what happened
      @return None
      """
      plan = self._plan
      self.log.add(f"error: {step.title.lower()} failed ({why})")
      if plan is not None:
         self._failed.append(plan.target.title)
      self._steps = []
      self._next_plan()

   def _finish(self) -> None:
      """!Every plan has run: says how it went.
      @return None
      """
      ok = not self._failed
      text = "Done" if ok else "Failed: " + ", ".join(self._failed)
      self.log.add(f"==== {text}")
      self.log.state.setText(text)
      self._sync_enabled()
      show = getattr(self._window, "show_status", None)
      if callable(show):
         show(f"{BUILD}: {text.lower() if ok else text}")
      if not ok and not headless():
         self.show_log()
      self.finished.emit(ok)

   def stop(self) -> None:
      """!Stops what runs: the build (no further steps or targets), or the game.
      @return None
      """
      proc = self.process
      if proc is None:
         return
      game = self.running_game
      self.process = None
      self.running_game = False
      self._plans = []
      self._steps = []
      proc.kill()
      proc.waitForFinished()
      self._flush(proc)
      proc.deleteLater()
      self.log.add("stopped the game" if game else "stopped the build")
      if not game:
         plan = self._plan
         self._failed.append(plan.target.title if plan is not None else BUILD)
      self._plan = None
      self._finish()

   def show_log(self) -> None:
      """!Shows the Build log (LOG_HEIGHT high the first time).
      @return None
      """
      first = not self._log_sized
      self.log.show()
      if first:
         self._window.resizeDocks([self.log], [LOG_HEIGHT], QtCore.Qt.Orientation.Vertical)
         self._log_sized = True

   def busy(self) -> bool:
      """!Whether a build or the game it started runs.
      @return True while something runs
      """
      return self.process is not None
