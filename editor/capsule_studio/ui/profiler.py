"""!Performance recorder: Help > Record performance in the editor windows.

While recording, it notes every time the window stops responding for more
than STALL_MS (the event loop could not run a timer on time), what the user
did just before (the last mouse, key or wheel event and the widget it went
to), and profiles every Python call. Stopping writes a plain-text report to
the toolkit's profiles/ folder: the display setup (platform plugin, screens,
scaling), the stalls, and the functions that took the time.
"""
from __future__ import annotations

import time

## When the program started importing the editor (before PySide6 loads), for the startup time.
STARTED_AT = time.perf_counter()

import cProfile  # noqa: E402
import io  # noqa: E402
import platform  # noqa: E402
import pstats  # noqa: E402
import sys  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

## Milliseconds per second.
MS_PER_SECOND = 1000

## A gap in the event loop longer than this is reported as a stall, milliseconds.
STALL_MS = 50
## Timer period of the stall detector, milliseconds.
TICK_MS = 10
## Stalls kept in the report (the longest).
MAX_STALLS = 60
## Input events worth naming in the report.
INPUT_EVENTS = {
   QtCore.QEvent.Type.MouseButtonPress: "mouse press",
   QtCore.QEvent.Type.MouseButtonRelease: "mouse release",
   QtCore.QEvent.Type.MouseMove: "mouse move",
   QtCore.QEvent.Type.Wheel: "wheel",
   QtCore.QEvent.Type.KeyPress: "key",
}
## Functions listed per profile table in the report.
REPORT_FUNCTIONS = 35
## Folders from this file up to the capsule-studio root (ui, capsule_studio, editor): index in Path.parents.
STUDIO_ROOT_PARENT = 3


def elapsed_ms() -> float:
   """!Milliseconds since the program started.
   @return float
   """
   return (time.perf_counter() - STARTED_AT) * MS_PER_SECOND


def profiles_folder() -> Path:
   """!Where reports go: profiles/ at the capsule-studio root.
   @return Path
   """
   return Path(__file__).resolve().parents[STUDIO_ROOT_PARENT] / "profiles"


class Recorder(QtCore.QObject):
   """!Records stalls and a profile until stopped (see the module docstring)."""

   def __init__(self, window: QtWidgets.QMainWindow, tool: str, parent: QtCore.QObject | None = None) -> None:
      """!Creates a stopped recorder.
      @param window  the editor's main window
      @param tool    tool name for the report file (map-editor, ...)
      @param parent  owner QObject
      """
      super().__init__(parent)
      ## The editor window.
      self.window = window
      ## Tool name.
      self.tool = tool
      ## The Python profiler while recording, or None.
      self.profile = None
      ## Stall detector timer.
      self.timer = QtCore.QTimer(self)
      self.timer.setInterval(TICK_MS)
      self.timer.timeout.connect(lambda: self._tick())
      ## Time of the last tick.
      self.last_tick = 0.0
      ## Stalls: (when, milliseconds, what the user did last).
      self.stalls = []
      ## The last input event: (kind, widget class, time).
      self.last_input = None
      ## Input events seen, by kind.
      self.inputs = {}
      ## When recording started.
      self.started = 0.0

   def recording(self) -> bool:
      """!Whether it is recording.
      @return bool
      """
      return self.profile is not None

   def start(self) -> bool:
      """!Starts recording.
      @return True when it started (Python's profiler may already be in use by another recorder)
      """
      profile = cProfile.Profile()
      try:
         profile.enable()
      except ValueError:   # another profiler holds the interpreter's profiling hook
         return False
      self.stalls = []
      self.inputs = {}
      self.last_input = None
      self.started = time.perf_counter()
      self.last_tick = self.started
      QtWidgets.QApplication.instance().installEventFilter(self)
      self.timer.start()
      self.profile = profile
      return True

   def stop(self) -> Path:
      """!Stops recording and writes the report.
      @return Path of the report
      """
      self.profile.disable()
      self.timer.stop()
      QtWidgets.QApplication.instance().removeEventFilter(self)
      text = self.report()
      self.profile = None
      folder = profiles_folder()
      folder.mkdir(parents=True, exist_ok=True)
      path = folder / f"{self.tool}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
      path.write_text(text, encoding="utf-8")
      return path

   def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
      """!Remembers the last input event (stalls are blamed on it).
      @param obj    receiver
      @param event  QEvent
      @return False (events go on as usual)
      """
      kind = INPUT_EVENTS.get(event.type())
      if kind is not None and isinstance(obj, QtWidgets.QWidget):
         self.last_input = (kind, type(obj).__name__, time.perf_counter())
         self.inputs[kind] = self.inputs.get(kind, 0) + 1
      return False

   def _tick(self) -> None:
      """!Detects a stall: the timer ran late.
      @return None
      """
      now = time.perf_counter()
      # How much later than its period the timer ran: the time the event loop was blocked.
      gap = (now - self.last_tick) * MS_PER_SECOND - TICK_MS
      if gap > STALL_MS:
         what = "no input just before"
         if self.last_input is not None:
            kind, widget, at = self.last_input
            # Negative when the input arrived after the last on-time tick, i.e. while the stall went on.
            lead = MS_PER_SECOND * (self.last_tick - at)
            what = f"{kind} on {widget}, " + (f"{lead:.0f} ms before it began" if lead >= 0 else "handled during it")
         self.stalls.append((self.last_tick - self.started, gap, what))
      self.last_tick = now

   def report(self) -> str:
      """!The report text.
      @return str
      """
      app = QtWidgets.QApplication.instance()
      lines = [f"CapsuleCreatures {self.tool} performance report, {datetime.now():%Y-%m-%d %H:%M:%S}",
               f"recorded {time.perf_counter() - self.started:.1f} s; startup to first window "
               f"{getattr(self.window, 'startup_ms', 0):.0f} ms", "",
               "Setup:",
               f"  Python {platform.python_version()} ({sys.executable})",
               f"  Qt {QtCore.qVersion()}, PySide6 {getattr(sys.modules.get('PySide6'), '__version__', '?')}",
               f"  platform plugin: {QtGui.QGuiApplication.platformName()}; style: {app.style().name()}",
               f"  OS: {platform.platform()}"]
      for s in QtGui.QGuiApplication.screens():
         g = s.geometry()
         lines.append(f"  screen {s.name()}: {g.width()}x{g.height()} logical, scale {s.devicePixelRatio():g}, "
                      f"{s.refreshRate():.0f} Hz")
      win = self.window
      lines.append(f"  window: {win.width()}x{win.height()}, scale {win.devicePixelRatioF():g}")
      extra = getattr(win, "profile_notes", None)
      if callable(extra):
         lines += [f"  {x}" for x in extra()]
      lines += ["", "Input events: " + (", ".join(f"{k} {n}" for k, n in sorted(self.inputs.items())) or "none")]
      stalls = sorted(self.stalls, key=lambda s: -s[1])[:MAX_STALLS]
      total = sum(s[1] for s in self.stalls)
      lines += ["", f"Stalls over {STALL_MS} ms: {len(self.stalls)}, {total:.0f} ms in all (longest first):"]
      lines += [f"  at {at:7.2f} s: {ms:6.0f} ms  after {what}" for at, ms, what in stalls] or ["  none"]
      for key, title in (("cumulative", "including the functions they call"), ("tottime", "in the function itself")):
         out = io.StringIO()
         st = pstats.Stats(self.profile, stream=out)
         st.strip_dirs().sort_stats(key).print_stats(REPORT_FUNCTIONS)
         lines += ["", f"Python time by function ({title}):", out.getvalue()]
      return "\n".join(lines) + "\n"


def add_menu(window: QtWidgets.QMainWindow, tool: str) -> Recorder:
   """!Adds Help > Record performance to an editor window.
   @param window  QMainWindow with show_status(text)
   @param tool    tool name for the report file
   @return the Recorder
   """
   rec = Recorder(window, tool, window)
   menu = window.menuBar().addMenu("&Help")
   action = QtGui.QAction("Record performance", window)
   action.setCheckable(True)
   action.setToolTip("Records where the editor spends its time; uncheck to save the report")

   def toggled(on: bool) -> None:
      if on and not rec.recording():
         if not rec.start():
            action.setChecked(False)
            window.show_status("Cannot record: Python's profiler is already in use")
            return
         window.show_status("Recording performance: use the editor, then uncheck Help > Record performance")
      elif not on and rec.recording():
         path = rec.stop()
         window.show_status(f"Performance report saved: {path}")
         QtWidgets.QMessageBox.information(window, "Performance report", f"Saved to\n{path}")
   action.toggled.connect(toggled)
   menu.addAction(action)
   return rec
