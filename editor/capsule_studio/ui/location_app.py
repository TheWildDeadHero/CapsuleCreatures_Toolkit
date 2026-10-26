"""!Starts the location editor: the Locations panel of the locations extension
(capsule_studio/extensions/locations): locations, banner styles, previews
and the world's warp transition, on its own, in the window the map editor
uses. The Studio shows the panel next to the map."""
from __future__ import annotations

import sys

from . import profiler  # noqa: F401  first: its import time is the start time

from . import world_app


def main(argv: list[str] | None = None) -> int:
   """!Runs the application.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   return world_app.main(argv, host_id="location-editor", title="CapsuleCreatures Location Editor", builtin_panels=[])


if __name__ == "__main__":
   sys.exit(main())
