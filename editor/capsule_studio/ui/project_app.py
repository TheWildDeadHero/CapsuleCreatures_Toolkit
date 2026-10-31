"""!Starts the project settings window (build settings and code page of a game; A-2, A-5, C-2)."""
from __future__ import annotations

import argparse
import sys

from . import profiler  # first: its import time is the start time

from PySide6 import QtCore, QtWidgets

from .project_shell import ProjectWindow


def main(argv: list[str] | None = None) -> int:
   """!Runs the application.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   p = argparse.ArgumentParser(prog="project-settings", description="CapsuleCreatures project settings.",
                               epilog="Qt options take the -name=value form, e.g. -style=fusion.")
   p.add_argument("project", nargs="?", help="reference/project.json to open")
   args, qt_args = p.parse_known_args(sys.argv[1:] if argv is None else argv)
   app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1] + qt_args)
   app.setApplicationName("CapsuleCreatures Project Settings")
   window = ProjectWindow(args.project)
   window.launch()   # the editor, or the small start window until something is opened
   QtCore.QTimer.singleShot(0, lambda: setattr(window, "startup_ms", profiler.elapsed_ms()))   # for reports
   return app.exec()


if __name__ == "__main__":
   sys.exit(main())
