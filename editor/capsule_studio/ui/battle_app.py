"""!Starts the battle editor: content (species, moves, types, parties,
presenters), structure (terms, text, ...) and logic (formulas, ...) pages
in one navigator. battle_structure_app and battle_logic_app start it with
their group in front.
"""
from __future__ import annotations

import argparse
import sys

from . import profiler  # first: its import time is the start time

from PySide6 import QtCore, QtWidgets

from .battle_shell import BATTLE_PANELS, GROUP_IDS, BattleWindow


def main(argv: list[str] | None = None, group: str | None = None, prog: str = "battle-editor") -> int:
   """!Runs the application.
   @param argv   arguments without the program name, or None for sys.argv
   @param group  navigator group in front (--group's default), or None
   @param prog   program name for the help text
   @return exit status
   """
   p = argparse.ArgumentParser(prog=prog, description="CapsuleCreatures battle editor.",
                               epilog="Qt options take the -name=value form, e.g. -style=fusion.")
   p.add_argument("battle", nargs="?", help="battle.json to open")
   p.add_argument("--panel", choices=[c.panel_id for c in BATTLE_PANELS], help="open only this editor")
   p.add_argument("--group", choices=GROUP_IDS, default=group, help="navigator group to show first")
   args, qt_args = p.parse_known_args(sys.argv[1:] if argv is None else argv)
   app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1] + qt_args)
   app.setApplicationName("CapsuleCreatures Battle Editor")
   panels = [c for c in BATTLE_PANELS if c.panel_id == args.panel] if args.panel else None
   window = BattleWindow(panels, args.battle, None if panels else args.group)
   window.launch()   # the editor, or the small start window until something is opened
   QtCore.QTimer.singleShot(0, lambda: setattr(window, "startup_ms", profiler.elapsed_ms()))   # for reports
   return app.exec()


if __name__ == "__main__":
   sys.exit(main())
