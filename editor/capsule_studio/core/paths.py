"""!Paths as manifests and the command line write them, the same on Linux, Windows and macOS (D-40 RX2).

Manifests store relative paths with "/" between parts, whatever system wrote them, and the command line prints the
same text. Three things differ between systems and are handled here once:

- What an absolute path is. A manifest written on one system is read on the others, so is_absolute_text() counts a
  path absolute when any of them would: "/x" (POSIX; on Windows the current drive's root), "C:..." (a drive) and
  "//server/share" (UNC, also written with backslashes). pathlib's own is_absolute() answers only for the running
  system: on Windows it calls "/x" relative, on Linux it calls "C:/x" relative.
- Links and short names. A folder can be reached by two spellings: macOS's temporary folders are /var/..., a link to
  /private/var/...; Windows has 8.3 short names (C:/Users/RUNNER~1). Path.resolve() turns either into the real
  path, so relative() resolves both sides before it compares or climbs; a resolved file against an unresolved folder
  would climb out to the root and back ("../../../var/...").
- Drives. On Windows no relative path leads from one drive to another (os.path.relpath raises ValueError);
  relative() says so in a DocumentError, or gives the absolute path when the caller asks for a label.
"""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

from .document import DocumentError

## A Windows drive at the start of a path text: one letter and a colon ("C:", "c:/x", "C:x"; backslashes too).
DRIVE = re.compile(r"^[A-Za-z]:")
## How a UNC path (//server/share, or the same with backslashes) starts once each backslash is read as "/".
UNC_START = "//"


def is_absolute_text(text: str) -> bool:
   """!Whether a path text, as a manifest or a user gives it, is absolute on any system the toolkit runs on.
   @param text  the path as written ("/" or a backslash between parts)
   @return True for a POSIX absolute path, a Windows drive path (also drive-relative "C:x") or a UNC path
   """
   unified = text.replace("\\", "/")
   return PurePosixPath(unified).is_absolute() or bool(DRIVE.match(unified)) or unified.startswith(UNC_START)


def relative(target: str | Path, base: str | Path, label: bool = False) -> str:
   """!The path from a folder to a file, written with "/" (".." where it climbs), both sides resolved first.
   @param target  the file (absolute, or relative to the working folder)
   @param base    the folder
   @param label   True: a target on another drive gives its absolute path ("/" separators) for a label, instead
                  of an error
   @return the relative path, e.g. "data/assets.json" or "../shared/x.json"
   @throws DocumentError when the target is on another drive than the folder (Windows) and label is False
   """
   real_target = Path(target).resolve()
   real_base = Path(base).resolve()
   try:
      return Path(os.path.relpath(real_target, real_base)).as_posix()
   except ValueError:   # Windows: another drive, so no relative path exists
      if label:
         return real_target.as_posix()
      raise DocumentError(f"{real_target} is on another drive than {real_base}: a manifest path is relative, so "
                          "keep the file on the folder's drive") from None


def inside(path: str | Path, base: str | Path) -> str | None:
   """!A path's place inside a folder, written with "/", both sides resolved first.
   @param path  the file or folder
   @param base  the folder
   @return e.g. "data/world.json" ("." for the folder itself), or None when the path is not inside the folder
   """
   real_path = Path(path).resolve()
   real_base = Path(base).resolve()
   if real_path != real_base and real_base not in real_path.parents:
      return None
   return real_path.relative_to(real_base).as_posix()


def shown(path: str | Path, base: str | Path) -> str:
   """!A path as lists and the command line show it: relative to a folder when it is inside it, else absolute.
   @param path  the file
   @param base  the folder
   @return e.g. "screens/detail.screen.json", or the absolute path ("/" separators) when it is outside
   """
   within = inside(path, base)
   return within if within is not None else Path(path).resolve().as_posix()
