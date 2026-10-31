"""!Starts the scene editor (all panels, or one with --panel)."""
from __future__ import annotations

import argparse
import sys

from PySide6 import QtWidgets

from .editors import PANELS, by_id
from .shell import EditorWindow


def main(argv: list[str] | None = None) -> int:
   """!Runs the application.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   p = argparse.ArgumentParser(prog="capsule-scene-editor", description="CapsuleCreatures scene editor.",
                               epilog="Qt options take the -name=value form, e.g. -style=fusion.")
   p.add_argument("manifest", nargs="?", help="asset manifest to open")
   p.add_argument("--panel", choices=[c.panel_id for c in PANELS],
                  help="open only this editor (standalone)")
   args, qt_args = p.parse_known_args(sys.argv[1:] if argv is None else argv)
   app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1] + qt_args)
   app.setApplicationName("CapsuleCreatures Scene Editor")
   window = EditorWindow([by_id(args.panel)] if args.panel else None, args.manifest)
   window.show()
   return app.exec()


if __name__ == "__main__":
   sys.exit(main())
