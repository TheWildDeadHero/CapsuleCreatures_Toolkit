"""!Starts the manifest designer (D-43): a manifest a designer system edits, shown as a drag-and-drop diagram."""
from __future__ import annotations

import argparse
import sys

from . import profiler  # first: its import time is the start time

from PySide6 import QtCore, QtWidgets

from .designer.window import APP_TITLE, DesignerWindow


def main(argv: list[str] | None = None) -> int:
   """!Runs the application.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   p = argparse.ArgumentParser(prog="manifest-designer", description=f"CapsuleCreatures {APP_TITLE}.",
                               epilog="Qt options take the -name=value form, e.g. -style=fusion.")
   p.add_argument("manifest", nargs="?", help="a manifest to open")
   p.add_argument("--system", help="with a manifest: the designer to open it with; without: start a new one of "
                                   "this designer (capsule-studio designer systems --all lists them)")
   args, qt_args = p.parse_known_args(sys.argv[1:] if argv is None else argv)
   app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1] + qt_args)
   app.setApplicationName(f"CapsuleCreatures {APP_TITLE}")
   window = DesignerWindow(args.manifest, args.system)
   window.launch()   # the designer, or the start page until something is opened
   QtCore.QTimer.singleShot(0, lambda: setattr(window, "startup_ms", profiler.elapsed_ms()))   # for reports
   return app.exec()


if __name__ == "__main__":
   sys.exit(main())
