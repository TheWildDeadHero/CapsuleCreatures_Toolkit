"""!Starts the map editor (map and tileset panels on a world, with the map
tools and overlays extensions add; panels extensions register for the map
editor's host id show as tabs). main() also starts the standalone world tools
(encounter, event, object and location editors) with another host id and no
built-in panels."""
from __future__ import annotations

import argparse
import sys

from . import profiler  # first: its import time is the start time

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ..core.document import DocumentError
from ..plugins import loader
from .world_shell import WORLD_PANELS, WorldWindow

if TYPE_CHECKING:
   from .panel import EditorPanel

## Exit status when the command line or the world can't be used (argparse's own error status).
EXIT_USAGE = 2


def main(argv: list[str] | None = None, host_id: str = "map-editor", title: str = "CapsuleCreatures Map Editor",
         builtin_panels: list[type[EditorPanel]] | None = None) -> int:
   """!Runs the application.
   @param argv            arguments without the program name, or None for sys.argv
   @param host_id         host id (which extension panels it shows; plugins.registry)
   @param title           application title
   @param builtin_panels  built-in panel classes (default WORLD_PANELS)
   @return exit status
   """
   builtin_panels = WORLD_PANELS if builtin_panels is None else builtin_panels
   ext_ids = [s.panel_id for s in loader.builtin_registry().panels(host_id)]
   prog = host_id
   p = argparse.ArgumentParser(prog=prog, description=title + ".",
                               epilog="Qt options take the -name=value form, e.g. -style=fusion.")
   p.add_argument("world", nargs="?", help="world.json to open")
   p.add_argument("--panel", choices=[c.panel_id for c in builtin_panels] + ext_ids, help="open only this editor")
   args, qt_args = p.parse_known_args(sys.argv[1:] if argv is None else argv)
   app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1] + qt_args)
   app.setApplicationName(title)
   try:
      window = WorldWindow(builtin_panels, args.world, host_id, title, [args.panel] if args.panel else None)
   except DocumentError as e:
      print(f"{prog}: error: {e}", file=sys.stderr)
      return EXIT_USAGE
   window.launch()   # the editor, or the small start window until something is opened
   QtCore.QTimer.singleShot(0, lambda: setattr(window, "startup_ms", profiler.elapsed_ms()))   # for reports
   return app.exec()


if __name__ == "__main__":
   sys.exit(main())
