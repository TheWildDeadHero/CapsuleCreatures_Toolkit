"""!Reading and writing manifest JSON files.

Files are written in a compact, stable layout: any object or array that fits
on one line stays on one line, the rest is indented. Key order is kept as
loaded, so a saved manifest diffs cleanly against its hand-written original.

[S2] A file written by a tool in Python's own json layout (json.dumps with an
indent, e.g. an importer's text tables and fonts) can keep that layout:
detect() names it (a Layout), save(path, value, layout) writes it again, so an
edit changes only the lines it touches and a file saved unchanged stays byte
for byte the same.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

## Lines longer than this are broken up.
LINE_WIDTH = 110
## Indent per level.
INDENT = "  "

## A parsed JSON value: object, array, string, number, bool or None.
JsonValue = Any
## A parsed JSON object (a manifest, an asset, a chunk...).
JsonDict = dict[str, Any]
## [S2] Python's json layout of a file: (indent, ensure_ascii); None for the compact layout of dumps().
Layout = tuple[int | None, bool] | None
## [S2] Indents detect() tries (json.dumps indent values; None: everything on one line).
DETECTED_INDENTS = (1, 2, 3, 4, None)


def dumps(value: JsonValue, level: int = 0) -> str:
   """!Formats a JSON value in the compact layout.
   @param value  JSON-compatible value
   @param level  current indent level
   @return the text (no trailing newline)
   """
   # Whatever fits on the current line stays on one line.
   flat = json.dumps(value, ensure_ascii=False)
   if not isinstance(value, (dict, list)) or len(flat) + len(INDENT) * level <= LINE_WIDTH:
      return flat
   pad, inner = INDENT * level, INDENT * (level + 1)
   if isinstance(value, dict):
      if not value:
         return "{}"
      items = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {dumps(v, level + 1)}" for k, v in value.items()]
      return "{\n" + ",\n".join(items) + "\n" + pad + "}"
   if not value:
      return "[]"
   return "[\n" + ",\n".join(inner + dumps(v, level + 1) for v in value) + "\n" + pad + "]"


def dumps_layout(value: JsonValue, layout: Layout) -> str:
   """![S2] Formats a JSON value in a file's own layout (detect()), or in the compact layout.
   @param value   JSON-compatible value
   @param layout  the layout, or None for dumps()
   @return the text with its trailing newline
   """
   if layout is None:
      return dumps(value) + "\n"
   indent, ascii_only = layout
   return json.dumps(value, indent=indent, ensure_ascii=ascii_only) + "\n"


def detect(text: str, value: JsonValue) -> Layout:
   """![S2] The json layout a file's text was written in, when it is one of Python's own (an indent of
   DETECTED_INDENTS, ASCII escapes or not, one trailing newline).
   @param text   the file's text
   @param value  its parsed value
   @return the Layout, or None (another layout: saves use the compact one)
   """
   for indent in DETECTED_INDENTS:
      for ascii_only in (False, True):
         if dumps_layout(value, (indent, ascii_only)) == text:
            return indent, ascii_only
   return None


def load(path: str | Path) -> JsonValue:
   """!Reads a manifest file.
   @param path  file path
   @return the parsed JSON
   @throws ValueError (json.JSONDecodeError) on malformed JSON, OSError on I/O errors
   """
   return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: str | Path, value: JsonValue, layout: Layout = None) -> None:
   """!Writes a manifest file in the compact layout (or [S2] a file's own layout), via a temporary file so
   a failed write never leaves half a manifest behind. Missing folders are
   created.
   @param path    file path
   @param value   JSON-compatible value
   @param layout  the file's own layout (detect()), or None for the compact one
   @return None
   """
   path = Path(path)
   path.parent.mkdir(parents=True, exist_ok=True)   # new tilesets/ and maps/ folders
   tmp = path.with_name(path.name + ".tmp")
   tmp.write_text(dumps_layout(value, layout), encoding="utf-8")
   tmp.replace(path)
