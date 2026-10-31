"""!Starts the script editor (.cscript sources, flags and variables; B-1, B-2, B-4)."""
from __future__ import annotations

import argparse
import sys

from . import profiler  # first: its import time is the start time

from PySide6 import QtCore, QtWidgets

from .script_shell import ScriptWindow


def main(argv: list[str] | None = None) -> int:
   """!Runs the application.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   p = argparse.ArgumentParser(prog="script-editor", description="CapsuleCreatures script editor.",
                               epilog="Qt options take the -name=value form, e.g. -style=fusion.")
   p.add_argument("scripts", nargs="?", help="scripts.json to open")
   args, qt_args = p.parse_known_args(sys.argv[1:] if argv is None else argv)
   app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1] + qt_args)
   app.setApplicationName("CapsuleCreatures Script Editor")
   window = ScriptWindow(args.scripts)
   window.launch()   # the editor, or the small start window until something is opened
   QtCore.QTimer.singleShot(0, lambda: setattr(window, "startup_ms", profiler.elapsed_ms()))   # for reports
   return app.exec()


if __name__ == "__main__":
   sys.exit(main())
