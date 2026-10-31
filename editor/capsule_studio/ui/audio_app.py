"""![S7] Starts the audio editor (a game's audio manifest: songs, instruments, samples, MIDI import, sound effects;
engine M4 / D-34). The same window is the Studio's Audio page."""
from __future__ import annotations

import argparse
import sys

from . import profiler  # first: its import time is the start time

from PySide6 import QtCore, QtWidgets

from .audio_shell import TITLE, AudioWindow


def main(argv: list[str] | None = None) -> int:
   """!Runs the application.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   p = argparse.ArgumentParser(prog="audio-editor", description=TITLE + ".",
                               epilog="Qt options take the -name=value form, e.g. -style=fusion.")
   p.add_argument("manifest", nargs="?", help="an audio manifest (audio.json) to open")
   args, qt_args = p.parse_known_args(sys.argv[1:] if argv is None else argv)
   app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1] + qt_args)
   app.setApplicationName(TITLE)
   window = AudioWindow(args.manifest)
   window.launch()   # the editor, or the small start window until something is opened
   QtCore.QTimer.singleShot(0, lambda: setattr(window, "startup_ms", profiler.elapsed_ms()))   # for reports
   return app.exec()


if __name__ == "__main__":
   sys.exit(main())
