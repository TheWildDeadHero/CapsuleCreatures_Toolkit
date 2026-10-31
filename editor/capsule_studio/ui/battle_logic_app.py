"""!Starts the battle editor with its Logic pages in front (the battle-logic
launcher); see battle_app.
"""
from __future__ import annotations

import sys

from . import profiler  # noqa: F401  first: its import time is the start time

from .battle_app import main as battle_main


def main(argv: list[str] | None = None) -> int:
   """!Runs the battle editor on its Logic group.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   return battle_main(argv, "logic", "battle-logic")


if __name__ == "__main__":
   sys.exit(main())
