"""!The studio bundle's smoke test (D-40 RI): start, open the Starter sample as a new game, show every Studio page,
quit. Runs inside a built bundle (`capsule-studio --bundle-smoke WORK_DIR`, also from the `studio` executable) and,
for a baseline, from the source tree (`python3 bundle_main.py --bundle-smoke WORK_DIR`).

Checks, each recorded in WORK_DIR/smoke.json and printed:
  - engine     the engine the studio uses is the one inside the bundle (unless CAPSULE_ENGINE names another);
  - template   the engine's Starter template is found and makes a new game in WORK_DIR/game;
  - plugins    the studio's own extensions load without errors (the pure-Python rule included);
  - script     an engine tool runs through sys.executable (the bundle stands in for `python script.py`, which
               the battle bench uses);
  - studio     the Studio window opens the new game and builds every page; no Python exception escapes.
Warnings the editors log (a page with nothing to open, for instance) are listed but do not fail the test.
The platform defaults to Qt's offscreen one; a watchdog ends a run that hangs.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path
from types import TracebackType
from typing import Any

## Qt platform used when QT_QPA_PLATFORM is not set (no screen needed).
DEFAULT_PLATFORM = "offscreen"
## Seconds before the watchdog ends a hung run.
WATCHDOG_SECONDS = 240
## Exit status of a run the watchdog ended.
EXIT_HUNG = 3
## Exit status of a failed check.
EXIT_FAILED = 1
## Seconds an engine tool may take to print its help.
SCRIPT_TIMEOUT = 120
## The engine tool run through sys.executable, and its argument.
SCRIPT = ("tools", "bench_scenario.py")
SCRIPT_ARGS = ("--help",)
## The template the new game is made from.
TEMPLATE = "starter"
## Characters of a failed tool's error output kept in the report.
STDERR_TAIL = 2000
## Name of the report file in the work folder.
REPORT_NAME = "smoke.json"
## Indentation of the report's JSON.
REPORT_INDENT = 2

## One check's result: name -> details.
Results = dict[str, Any]


class WarningLog(logging.Handler):
   """!Keeps every warning (and worse) the studio logs during the run."""

   def __init__(self) -> None:
      """!Starts empty."""
      super().__init__(logging.WARNING)
      ## Formatted records.
      self.lines: list[str] = []

   def emit(self, record: logging.LogRecord) -> None:
      """!See logging.Handler.
      @param record  the record
      @return None
      """
      self.lines.append(f"{record.name}: {record.getMessage()}")


def check_engine(results: Results) -> Path:
   """!The engine in use, and whether it is the bundle's own.
   @param results  filled in
   @return the engine root
   """
   from capsule_studio.core import engine

   root = engine.root()
   bundle = getattr(sys, "_MEIPASS", None)
   # The bundle's top: the folder holding _internal/ (Linux, Windows) or the .app's Contents/ (macOS, where the
   # data lives in Resources/ beside Frameworks/).
   top = Path(bundle).resolve().parent if bundle else None
   expected = Path(os.environ[engine.ENV_VAR]).resolve() if os.environ.get(engine.ENV_VAR) else top
   inside = expected is None or expected == root or expected in root.parents
   results["engine"] = {"ok": inside, "root": str(root), "frozen": bundle is not None}
   return root


def check_template(results: Results, work: Path) -> Path:
   """!Makes the new game from the Starter template.
   @param results  filled in
   @param work     the work folder
   @return the new game's project manifest
   """
   from capsule_studio.core import templates

   t = templates.find(TEMPLATE)
   project = templates.new_game(work / "game", t)
   results["template"] = {"ok": project.is_file(), "template": t.label(), "project": str(project)}
   return project


def check_plugins(results: Results) -> None:
   """!Loads the studio's own extensions.
   @param results  filled in
   @return None
   """
   from capsule_studio.plugins import loader

   reg = loader.builtin_registry()
   errors = [str(e) for e in reg.errors]
   results["plugins"] = {"ok": not errors, "errors": errors}


def check_script(results: Results, engine_root: Path) -> None:
   """!Runs an engine tool the way the battle bench does: [sys.executable, script, ...].
   @param results      filled in
   @param engine_root  the engine in use
   @return None
   """
   cmd = [sys.executable, str(engine_root.joinpath(*SCRIPT)), *SCRIPT_ARGS]
   done = subprocess.run(cmd, capture_output=True, text=True, timeout=SCRIPT_TIMEOUT, check=False)
   results["script"] = {"ok": done.returncode == 0 and "usage" in done.stdout.lower(), "command": cmd,
                        "status": done.returncode, "stderr": done.stderr.strip()[-STDERR_TAIL:]}


def check_studio(results: Results, project: Path, exceptions: list[str]) -> None:
   """!Opens the game in the Studio window, builds every page, quits.
   @param results     filled in
   @param project     the project manifest
   @param exceptions  Python exceptions raised inside Qt's event loop so far (appended to by the hook)
   @return None
   """
   from PySide6 import QtCore, QtWidgets

   from capsule_studio.ui.studio_shell import PAGES, StudioWindow

   app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]])
   window = StudioWindow(str(project))
   window.launch()
   shown = []
   for page in PAGES:
      window.show_page(page.page_id)
      app.processEvents()
      shown.append(page.page_id)
   opened = window.project_path is not None and Path(window.project_path).resolve() == project.resolve()
   QtCore.QTimer.singleShot(0, app.quit)
   app.exec()
   window.close()
   loaded = sorted(m for m in sys.modules if m.startswith("PySide6.Qt"))
   results["studio"] = {"ok": opened and not exceptions, "platform": app.platformName(), "pages": shown,
                        "project": str(window.project_path), "exceptions": list(exceptions), "qt_modules": loaded}


def start_watchdog() -> None:
   """!Ends the process if the run hangs (a dialog waiting for a click, a stuck page).
   @return None
   """
   import threading

   def fire() -> None:
      """!Watchdog body.
      @return never
      """
      print(f"bundle smoke: no result after {WATCHDOG_SECONDS} s; stopping", file=sys.stderr, flush=True)
      os._exit(EXIT_HUNG)

   timer = threading.Timer(WATCHDOG_SECONDS, fire)
   timer.daemon = True
   timer.start()


def main(argv: list[str]) -> int:
   """!Runs every check.
   @param argv  [WORK_DIR]
   @return 0 when every check passed
   """
   if len(argv) != 1:
      print("usage: --bundle-smoke WORK_DIR", file=sys.stderr)
      return EXIT_FAILED
   work = Path(argv[0]).resolve()
   work.mkdir(parents=True, exist_ok=True)
   os.environ.setdefault("QT_QPA_PLATFORM", DEFAULT_PLATFORM)
   start_watchdog()
   warnings = WarningLog()
   logging.getLogger().addHandler(warnings)
   exceptions: list[str] = []

   def hook(kind: type[BaseException], value: BaseException, tb: TracebackType | None) -> None:
      """!Records exceptions raised in Qt slots (Qt only prints them).
      @param kind   exception type
      @param value  exception
      @param tb     traceback
      @return None
      """
      exceptions.append("".join(traceback.format_exception(kind, value, tb)))

   sys.excepthook = hook
   results: Results = {}
   try:
      root = check_engine(results)
      project = check_template(results, work)
      check_plugins(results)
      check_script(results, root)
      check_studio(results, project, exceptions)
   except Exception:   # any failure is the test's result, reported below
      results["error"] = {"ok": False, "traceback": traceback.format_exc()}
   results["warnings"] = {"ok": True, "lines": warnings.lines}
   (work / REPORT_NAME).write_text(json.dumps(results, indent=REPORT_INDENT), encoding="utf-8")
   failed = [name for name, r in results.items() if not r.get("ok")]
   for name, r in results.items():
      print(f"bundle smoke: {name}: {'ok' if r.get('ok') else 'FAILED'}")
   print(json.dumps(results, indent=REPORT_INDENT), flush=True)
   return EXIT_FAILED if failed else 0
