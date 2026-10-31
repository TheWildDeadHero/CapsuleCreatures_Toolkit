"""!Starts the Studio: every editor in one window, on one game (see
studio_shell.py). The same editors also run by themselves (map-editor,
scene-editor, script-editor, battle-editor, encounter-editor, event-editor,
object-editor, location-editor, project-settings)."""
from __future__ import annotations

import argparse
import sys

from . import profiler  # first: its import time is the start time

from PySide6 import QtCore, QtWidgets

from .studio_shell import PAGES, TITLE, StudioWindow


def main(argv: list[str] | None = None) -> int:
   """!Runs the application.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   p = argparse.ArgumentParser(prog="studio", description=TITLE + ": every editor in one window.",
                               epilog="Qt options take the -name=value form, e.g. -style=fusion.")
   p.add_argument("project", nargs="?", help="a game's reference/project.json to open")
   p.add_argument("--page", choices=[pg.page_id for pg in PAGES], help="page to show first")
   args, qt_args = p.parse_known_args(sys.argv[1:] if argv is None else argv)
   app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1] + qt_args)
   app.setApplicationName(TITLE)
   window = StudioWindow(args.project, args.page)
   if args.page and args.project:
      window.show_page(args.page)
   window.launch()   # the Studio, or the small start window until a project is opened
   QtCore.QTimer.singleShot(0, lambda: setattr(window, "startup_ms", profiler.elapsed_ms()))   # for reports
   return app.exec()


if __name__ == "__main__":
   sys.exit(main())
