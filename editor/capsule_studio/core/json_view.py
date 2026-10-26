"""!Any JSON file shown read-only [S5]: data files the studio has no editor for, such as an imported game's
importer / tier-3 data (the importer's N1 / N2 / N3 Emerald content: world/scripts/story.json
capsule_import.emerald_story/1, ui/menus.json capsule_import.menus/1, overworld/field.json
capsule_import.emerald_field/1). The studio opens them without errors and changes nothing: open_file() reads one,
says which schema it has and whether a studio editor owns that schema (core.document.EMPTY: the schemas the
studio edits), and children() / summary() walk its values for a tree (long lists in chunks).

Qt-free; the read-only data view (ui/json_view.py) uses it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .document import EMPTY, DocumentError

## Most characters a scalar's summary shows.
SUMMARY_CHARS = 80
## Items of a list or keys of an object shown as one group (a longer one is split into groups of this size).
CHUNK = 200
## The key a JSON file names its schema with.
SCHEMA_KEY = "schema"


@dataclass
class JsonFile:
   """!A JSON file read for the view."""

   ## The file.
   path: Path
   ## Its value.
   data: Any
   ## Its "schema" (None without one).
   schema: str | None
   ## Its size in bytes.
   size: int

   def editable(self) -> bool:
      """!Whether a studio editor owns the file's schema.
      @return True for a schema of core.document.EMPTY
      """
      schema = self.schema   # a local alias (Doxygen 1.12 reads a dataclass field used in a method as a new member)
      return schema in EMPTY

   def banner(self) -> str:
      """!The line the view shows above the tree.
      @return text
      """
      schema = self.schema   # a local alias (see editable())
      what = f"schema {schema}" if schema else "no schema"
      owner = "a studio editor opens it for editing" if self.editable() else \
         "no studio editor: importer / game data, shown read-only"
      return f"{self.path.name} ({self.size} bytes, {what}): read-only here; {owner}"


def open_file(path: str | Path) -> JsonFile:
   """!Reads a JSON file.
   @param path  the file
   @return JsonFile
   @throws DocumentError when it cannot be read or is no JSON
   """
   p = Path(path)
   try:
      raw = p.read_bytes()
      data = json.loads(raw.decode("utf-8"))
   except (OSError, UnicodeDecodeError, ValueError) as e:
      raise DocumentError(f"{p.name}: {e}") from None
   schema = data.get(SCHEMA_KEY) if isinstance(data, dict) else None
   return JsonFile(p.resolve(), data, str(schema) if isinstance(schema, str) else None, len(raw))


def summary(value: Any) -> str:
   """!One line about a value.
   @param value  a JSON value
   @return "{n keys}", "[n items]", or the scalar (cut at SUMMARY_CHARS)
   """
   if isinstance(value, dict):
      return f"{{{len(value)} keys}}"
   if isinstance(value, list):
      return f"[{len(value)} items]"
   text = json.dumps(value, ensure_ascii=False)
   return text if len(text) <= SUMMARY_CHARS else text[:SUMMARY_CHARS - 1] + "…"


def is_container(value: Any) -> bool:
   """!Whether a value has children.
   @param value  a JSON value
   @return True for a non-empty object or list
   """
   return isinstance(value, (dict, list)) and bool(value)


@dataclass
class Chunk:
   """!A group of a long list's items or a big object's keys (CHUNK of them)."""

   ## The container.
   value: Any
   ## The first index (of the items, or of the keys in order).
   start: int
   ## One past the last.
   end: int


def children(value: Any) -> list[tuple[str, Any]]:
   """!A value's children for a tree: (label, child); a container of more than CHUNK children gives Chunks first.
   @param value  a JSON value, or a Chunk
   @return children
   """
   if isinstance(value, Chunk):
      if isinstance(value.value, list):
         return [(f"[{i}]", value.value[i]) for i in range(value.start, value.end)]
      keys = list(value.value)[value.start:value.end]
      return [(str(k), value.value[k]) for k in keys]
   if not isinstance(value, (dict, list)):
      return []
   n = len(value)
   if n > CHUNK:
      return [(f"{'[' if isinstance(value, list) else ''}{s}-{min(s + CHUNK, n) - 1}"
               f"{']' if isinstance(value, list) else ' (keys)'}", Chunk(value, s, min(s + CHUNK, n)))
              for s in range(0, n, CHUNK)]
   if isinstance(value, list):
      return [(f"[{i}]", v) for i, v in enumerate(value)]
   return [(str(k), v) for k, v in value.items()]


def describe(value: Any) -> str:
   """!A tree row's value column.
   @param value  a JSON value or a Chunk
   @return text
   """
   if isinstance(value, Chunk):
      return f"({value.end - value.start} of {len(value.value)})"
   return summary(value)
