"""!Starts the event editor: the Events panel of the events extension
(capsule_studio/extensions/events): warps, triggers, signs and step hooks,
on its own, in the window the map editor uses. The map editor keeps the
Events map tool and Map events overlay; the Studio shows the panel next to
the map."""
from __future__ import annotations

import sys

from . import profiler  # noqa: F401  first: its import time is the start time

from . import world_app


def main(argv: list[str] | None = None) -> int:
   """!Runs the application.
   @param argv  arguments without the program name, or None for sys.argv
   @return exit status
   """
   return world_app.main(argv, host_id="event-editor", title="CapsuleCreatures Event Editor", builtin_panels=[])


if __name__ == "__main__":
   sys.exit(main())
