"""!Starts the object editor: the Objects panel of the objects extension
(capsule_studio/extensions/objects): people, spotters and pickups with their
pages, triggers and move routes, on its own, in the window the map editor
uses. The map editor keeps the Objects map tool and overlay; the Studio
shows the panel next to the map."""
from __future__ import annotations

import sys

from . import profiler  # noqa: F401  first: its import time is the start time

from . import world_app


def main(argv: list[str] | None = None) -> int:
   """!Runs the application.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   return world_app.main(argv, host_id="object-editor", title="CapsuleCreatures Object Editor", builtin_panels=[])


if __name__ == "__main__":
   sys.exit(main())
