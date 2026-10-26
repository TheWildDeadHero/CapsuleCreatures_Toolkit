"""![S3] A map's cell override sets (D-30 section 2, engine DS1: map "override_sets").

A set is a named list of cells, each changing one tile layer of a cell to another metatile of the map's dictionary
(or to nothing: "metatile": null) or to four raw map entries; scripts apply and clear it (`override apply NAME;` /
`override clear NAME;`). A set may persist through a flag ({"flag": F}) or a variable and a non-zero value
({"var": V, "value": N}), so it is applied again whenever the map is entered; without "persist" it lasts until the
map is left. Set names are unique in the world. The engine's map_compiler decides what is valid
(compile_override_sets(): cells inside the map's chunks, layers the map has, metatiles of its dictionary; the flag
and variable names come from the world's scripts manifest when the world compiles).

Functions that change a map take its Document and must run inside doc.edit(), except rename_set() (it may also
rewrite the scripts naming the set, saved at once). Nothing here imports Qt.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import engine

if TYPE_CHECKING:
   from ..plugins import Diagnostic
   from .document import Document
   from .world import Project

## A parsed JSON object (a set, a cell).
JsonDict = dict[str, Any]
## A cell's tile layer: (x, y, layer).
CellLayer = tuple[int, int, int]

## The manifest key of a map's sets.
SETS_KEY = "override_sets"
## How a set without "persist" lasts (map_compiler OVERRIDE_PERSISTS[0], lower case): until the map is left.
PERSIST_NONE = "map"
## A set persisting through a flag.
PERSIST_FLAG = "flag"
## A set persisting through a variable holding a value.
PERSIST_VAR = "var"
## Value a variable-persisted set starts with (0 is refused: clearing the set writes 0).
DEFAULT_VAR_VALUE = 1
## Coordinates in a cell's "cell": [x, y].
CELL_COORDINATES = 2
## An override statement in a script: `override apply|clear NAME` (the name is group NAME_GROUP).
STATEMENT = r"\boverride\s+(apply|clear)\s+({name})\b"
## The STATEMENT group holding the set's name.
NAME_GROUP = 2
## Sides a margin is added on, across or down.
SIDES = 2
## Number a clashing imported set name gets first ("name_2").
FIRST_COPY_NUMBER = 2


def _mc() -> Any:
   """!The engine's map compiler.
   @return module
   """
   return engine.tool("map_compiler")


def persist_kinds() -> list[str]:
   """!How a set may last, in capsule::map::OverridePersist order (map_compiler OVERRIDE_PERSISTS): until the map is
   left, through a flag, through a variable.
   @return "map", "flag", "var"
   """
   return [p.lower() for p in _mc().OVERRIDE_PERSISTS]


def max_sets() -> int:
   """!Most sets a map has (map_compiler MAX_MAP_OVERRIDE_SETS: a 32-bit mask).
   @return the count
   """
   return int(_mc().MAX_MAP_OVERRIDE_SETS)


def value_range() -> tuple[int, int]:
   """!Values a variable-persisted set may hold (map_compiler MIN / MAX_OVERRIDE_VALUE; 0 excluded).
   @return (lowest, highest)
   """
   mc = _mc()
   return int(mc.MIN_OVERRIDE_VALUE), int(mc.MAX_OVERRIDE_VALUE)


def sets(doc: Document) -> list[JsonDict]:
   """!A map's sets.
   @param doc  map Document
   @return the manifest's own list (change it only inside doc.edit())
   """
   s = doc.data.get(SETS_KEY)
   return s if isinstance(s, list) else []


def set_names(doc: Document) -> list[str]:
   """!A map's set names, in order.
   @param doc  map Document
   @return names
   """
   return [str(s.get("name")) for s in sets(doc) if isinstance(s, dict)]


def world_names(project: Project) -> dict[str, str]:
   """!Every set name of the world with the map it is on (map heads: no map is opened).
   @param project  Project
   @return {set name: map name}
   """
   out: dict[str, str] = {}
   for m in project.map_names():
      for n in project.map_head(m).get(SETS_KEY, []):
         out.setdefault(str(n), m)
   return out


def find(doc: Document, name: str) -> JsonDict:
   """!A set by name.
   @param doc   map Document
   @param name  its name
   @return the set (live)
   @throws ValueError when the map has none of that name
   """
   for s in sets(doc):
      if isinstance(s, dict) and s.get("name") == name:
         return s
   raise ValueError(f"the map has no override set {name!r} (sets: {', '.join(set_names(doc)) or 'none'})")


def _check_name(project: Project, name: str, ignore: str | None = None) -> None:
   """!Refuses a name the engine would not take or another set of the world has.
   @param project  Project
   @param name     the name
   @param ignore   a set's own current name (a rename), or None
   @return None
   """
   if not isinstance(name, str) or not name.isidentifier():
      raise ValueError(f"an override set's name is letters, digits and '_' (not starting with a digit): {name!r}")
   owner = world_names(project).get(name)
   if owner is not None and name != ignore:
      raise ValueError(f"map {owner!r} already has an override set {name!r} (names are unique in the world)")


def add_set(project: Project, map_name: str, name: str, cell: Sequence[int], layer: int = 0,
            metatile: str | None = None) -> int:
   """!Adds a set with its first cell (the engine needs one; paint the others after). Call inside the map's edit().
   @param project   Project
   @param map_name  the map
   @param name      a new name (unique in the world)
   @param cell      [x, y] of the first cell
   @param layer     its tile layer
   @param metatile  the "tileset/name" it shows, or None for nothing
   @return the set's index
   """
   doc = project.map(map_name)
   _check_name(project, name)
   if len(sets(doc)) >= max_sets():
      raise ValueError(f"a map has at most {max_sets()} override sets")
   doc.data.setdefault(SETS_KEY, []).append({"name": name, "cells": [_cell(cell, layer, metatile)]})
   return len(sets(doc)) - 1


def _cell(cell: Sequence[int], layer: int, metatile: str | None = None, entries: Sequence[int] | None = None
          ) -> JsonDict:
   """!One cell record of a set.
   @param cell      [x, y]
   @param layer     tile layer
   @param metatile  "tileset/name", or None for nothing (when entries is None)
   @param entries   four raw map entries instead, or None
   @return the record
   """
   if len(cell) != CELL_COORDINATES or any(not isinstance(v, int) or isinstance(v, bool) for v in cell):
      raise ValueError("a cell is [x, y]")
   out: JsonDict = {"cell": [cell[0], cell[1]], "layer": layer}
   if entries is not None:
      mc = _mc()
      if len(entries) != mc.METATILE_TILES or any(not isinstance(v, int) or not 0 <= v <= mc.MAX_ENTRY
                                                  for v in entries):
         raise ValueError(f"entries are {mc.METATILE_TILES} map entries 0-{mc.MAX_ENTRY}")
      out["entries"] = list(entries)
   else:
      out["metatile"] = metatile
   return out


def remove_set(project: Project, map_name: str, name: str, force: bool = False) -> None:
   """!Removes a set (call inside the map's edit()); refused while scripts name it unless forced.
   @param project   Project
   @param map_name  the map
   @param name      the set
   @param force     remove it even when scripts name it (they stop compiling)
   @return None
   """
   doc = project.map(map_name)
   s = find(doc, name)
   used = script_uses(project, name)
   if used and not force:
      where = ", ".join(f"{Path(f).name}:{line}" for f, line in used)
      raise ValueError(f"scripts name override set {name!r} ({where}); change them first")
   sets(doc).remove(s)
   if not sets(doc):
      doc.data.pop(SETS_KEY, None)


def rename_set(project: Project, map_name: str, old: str, new: str, follow: bool = True) -> list[str]:
   """!Renames a set (one undo step of the map); the scripts naming it follow when asked (their .cscript sources
   are rewritten and saved at once, outside the map's undo).
   @param project   Project
   @param map_name  the map
   @param old       its name
   @param new       the new name (unique in the world)
   @param follow    rewrite `override apply|clear OLD` in the world's scripts
   @return the source files rewritten
   """
   doc = project.map(map_name)
   find(doc, old)
   _check_name(project, new, ignore=old)
   if new == old:
      return []
   with doc.edit("Rename override set"):
      find(doc, old)["name"] = new
   if not follow:
      return []
   pattern = re.compile(STATEMENT.format(name=re.escape(old)))
   changed = []
   for path in _script_sources(project):
      text = path.read_text(encoding="utf-8")
      # keeps `override KIND`, replaces the name only
      out = pattern.sub(lambda m: m.group(0)[:m.start(NAME_GROUP) - m.start(0)] + new, text)
      if out != text:
         path.write_text(out, encoding="utf-8")
         changed.append(str(path))
   return changed


def _script_sources(project: Project) -> list[Path]:
   """!The .cscript sources of the world's scripts manifest.
   @param project  Project
   @return paths (none without a manifest)
   """
   from . import events, manifest_io
   path = events.scripts_path(project)
   if path is None:
      return []
   try:
      m = manifest_io.load(path)
   except (OSError, ValueError):
      return []
   sources = m.get("sources", []) if isinstance(m, dict) else []
   return [(path.parent / s).resolve() for s in sources if isinstance(s, str) and (path.parent / s).is_file()]


def script_uses(project: Project, name: str) -> list[tuple[str, int]]:
   """!Where the world's scripts name a set (`override apply|clear NAME`).
   @param project  Project
   @param name     the set
   @return [(source file, line)]
   """
   pattern = re.compile(STATEMENT.format(name=re.escape(name)))
   out = []
   for path in _script_sources(project):
      for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
         if pattern.search(line):
            out.append((str(path), i + 1))
   return out


def persistence(s: JsonDict) -> tuple[str, str | None, int | None]:
   """!How a set lasts.
   @param s  the set
   @return (PERSIST_NONE | PERSIST_FLAG | PERSIST_VAR, flag or variable name or None, the variable's value or None)
   """
   p = s.get("persist")
   if not isinstance(p, dict):
      return PERSIST_NONE, None, None
   if "flag" in p:
      return PERSIST_FLAG, p.get("flag"), None
   return PERSIST_VAR, p.get("var"), p.get("value")


def set_persist(doc: Document, name: str, kind: str, which: str | None = None, value: int | None = None) -> None:
   """!How a set lasts (call inside doc.edit()): until the map is left, through a flag, or through a variable
   holding a non-zero value.
   @param doc    map Document
   @param name   the set
   @param kind   PERSIST_NONE, PERSIST_FLAG or PERSIST_VAR
   @param which  the flag or variable (of the world's scripts manifest)
   @param value  the variable's value (default DEFAULT_VAR_VALUE)
   @return None
   """
   s = find(doc, name)
   if kind not in persist_kinds():
      raise ValueError(f"a set lasts {', '.join(persist_kinds())}")
   if kind == PERSIST_NONE:
      s.pop("persist", None)
      return
   if not isinstance(which, str) or not which:
      raise ValueError(f"a set persisting through a {kind} names it")
   if kind == PERSIST_FLAG:
      s["persist"] = {"flag": which}
      return
   lo, hi = value_range()
   v = DEFAULT_VAR_VALUE if value is None else value
   if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi or v == 0:
      raise ValueError(f"the variable's value is {lo} to {hi}, not 0 (clearing the set writes 0)")
   s["persist"] = {"var": which, "value": v}


def cells(doc: Document, name: str) -> list[JsonDict]:
   """!A set's cells.
   @param doc   map Document
   @param name  the set
   @return the set's own list
   """
   c = find(doc, name).get("cells")
   return c if isinstance(c, list) else []


def _key(c: JsonDict) -> CellLayer | None:
   """!A cell record's (x, y, layer).
   @param c  the record
   @return the key, or None when malformed
   """
   at = c.get("cell") if isinstance(c, dict) else None
   if not isinstance(at, list) or len(at) != CELL_COORDINATES:
      return None
   return at[0], at[1], c.get("layer", 0)


def paint(doc: Document, name: str, at: Iterable[Sequence[int]], layer: int, metatile: str | None = None,
          entries: Sequence[int] | None = None) -> int:
   """!Sets cells of a set on one layer to a metatile of the map's dictionary (None: nothing) or to four raw map
   entries; a cell the set already changes on that layer takes the new value (call inside doc.edit()).
   @param doc       map Document
   @param name      the set
   @param at        cells [x, y]
   @param layer     the tile layer
   @param metatile  "tileset/name", or None for nothing (when entries is None)
   @param entries   four map entries instead, or None
   @return cells painted
   """
   lst = find(doc, name).setdefault("cells", [])
   index = {_key(c): i for i, c in enumerate(lst)}
   n = 0
   for cell in at:
      rec = _cell(cell, layer, metatile, entries)
      k = (rec["cell"][0], rec["cell"][1], layer)
      if k in index:
         lst[index[k]] = rec
      else:
         index[k] = len(lst)
         lst.append(rec)
      n += 1
   return n


def erase(doc: Document, name: str, at: Iterable[Sequence[int]], layer: int) -> int:
   """!Takes cells out of a set on one layer (call inside doc.edit()); a set keeps at least one cell.
   @param doc    map Document
   @param name   the set
   @param at     cells [x, y]
   @param layer  the tile layer
   @return cells taken out
   """
   s = find(doc, name)
   drop = {(c[0], c[1], layer) for c in at}
   kept = [c for c in s.get("cells", []) if _key(c) not in drop]
   gone = len(s.get("cells", [])) - len(kept)
   if not kept and gone:
      raise ValueError("a set keeps at least one cell (remove the set instead)")
   s["cells"] = kept
   return gone


def check(project: Project, map_name: str) -> str | None:
   """!The engine's checks of a map's sets (map_compiler.compile_override_sets() runs in compile_map()).
   @param project   Project
   @param map_name  the map
   @return error, or None
   """
   return project.compiled_map(map_name)[1]


def persist_problems(project: Project, map_name: str) -> list[str]:
   """!Sets persisting through a flag or variable the world's scripts manifest does not declare (the world's
   compile refuses them).
   @param project   Project
   @param map_name  the map
   @return messages
   """
   from . import events
   names = events.names(project)
   out = []
   for s in sets(project.map(map_name)):
      kind, which, _value = persistence(s)
      if kind == PERSIST_NONE:
         continue
      if names["error"] is not None:
         out.append(f"override set {s.get('name')!r} persists through {kind} {which!r}, but {names['error']}")
      elif which not in (names["flags"] if kind == PERSIST_FLAG else names["vars"]):
         out.append(f"override set {s.get('name')!r}: the scripts manifest declares no {kind} {which!r}")
   return out


def diagnostics(project: Project, map_name: str | None = None) -> list[Diagnostic]:
   """!Live findings for the map panel and `world validate`: the engine's errors of the sets and their
   persistence names.
   @param project   Project
   @param map_name  one map, or None for every map that has sets
   @return Diagnostic list
   """
   from ..plugins import Diagnostic
   out = []
   names = [map_name] if map_name else [m for m in project.map_names() if project.map_head(m).get(SETS_KEY)]
   for m in names:
      if not sets(project.map(m)):
         continue
      error = check(project, m)
      if error is not None and "override set" in error:
         out.append(Diagnostic("error", error, m))
      out += [Diagnostic("warning", p, m) for p in persist_problems(project, m)]
   return out


def shown(project: Project, map_name: str, name: str) -> dict[CellLayer, Any]:
   """!What the set's cells show when applied, as mapview.render_map() takes overrides: (x, y, layer) -> a metatile
   id of the compiled map (NO_METATILE: nothing) or a tuple of four map entries.
   @param project   Project
   @param map_name  the map
   @param name      the set
   @return the overrides ({} when the map does not compile)
   """
   compiled, _error = project.compiled_map(map_name)
   if compiled is None:
      return {}
   for s in compiled.get(SETS_KEY, []):
      if s["name"] == name:
         # compile_override_sets(): cells (x, y, layer, entries or None, metatile id)
         return {(x, y, layer): tuple(entries) if entries is not None else metatile
                 for x, y, layer, entries, metatile in s["cells"]}
   return {}


def bounds(doc: Document, name: str, margin: int = 0) -> tuple[int, int, int, int] | None:
   """!The rectangle a set's cells cover.
   @param doc     map Document
   @param name    the set
   @param margin  cells added around it
   @return (x0, y0, w, h), or None without cells
   """
   keys = [k for k in (_key(c) for c in cells(doc, name)) if k is not None]
   if not keys:
      return None
   xs, ys = [k[0] for k in keys], [k[1] for k in keys]
   return (min(xs) - margin, min(ys) - margin, max(xs) - min(xs) + 1 + SIDES * margin,
           max(ys) - min(ys) + 1 + SIDES * margin)


def render(project: Project, map_name: str, name: str, applied: bool = True, margin: int = 1) -> Any:
   """!A picture of a set's cells and their surroundings, applied or cleared.
   @param project   Project
   @param map_name  the map
   @param name      the set
   @param applied   draw the set applied (else the map as it is)
   @param margin    cells drawn around the set
   @return (w, h, RGBA), or None when the map does not compile or the set has no cells
   """
   from . import mapview
   compiled, _error = project.compiled_map(map_name)
   box = bounds(project.map(map_name), name, margin)
   if compiled is None or box is None:
      return None
   return mapview.render_map(compiled, *box, overrides=shown(project, map_name, name) if applied else None)


def lines(project: Project, map_name: str) -> list[str]:
   """!A map's sets as text (`overrides list`).
   @param project   Project
   @param map_name  the map
   @return lines
   """
   out = []
   for s in sets(project.map(map_name)):
      kind, which, value = persistence(s)
      lasts = "until the map is left" if kind == PERSIST_NONE else f"while flag {which} is set" \
         if kind == PERSIST_FLAG else f"while {which} == {value}"
      out.append(f"{map_name}: {s.get('name')}: {len(s.get('cells', []))} cell(s), {lasts}")
      for c in s.get("cells", []):
         what = f"entries {c['entries']}" if "entries" in c else str(c.get("metatile"))
         out.append(f"  {c.get('cell')} layer {c.get('layer', 0)}: {what}")
   return out


def import_sets(data: JsonDict, known: Mapping[str, Any] | None, taken: set[str]) -> tuple[int, list[str]]:
   """!An imported map's sets (core.importer): sets persisting through a flag or variable this world's scripts
   manifest lacks are left out (the world would not compile), a name another set of the world has gets a number.
   @param data   the map manifest (changed in place)
   @param known  this world's names (core.events.names()), or None without a scripts manifest
   @param taken  set names the world has (the kept ones are added)
   @return (sets left out, report lines of renamed sets)
   """
   raw = data.get(SETS_KEY)
   if not isinstance(raw, list):
      return 0, []
   kept, renamed = [], []
   for s in raw:
      if not isinstance(s, dict):
         continue
      kind, which, _value = persistence(s)
      if kind != PERSIST_NONE and (known is None or which not in known[
            "flags" if kind == PERSIST_FLAG else "vars"]):
         continue
      s = copy.deepcopy(s)
      name, n = str(s.get("name")), FIRST_COPY_NUMBER
      while s["name"] in taken:
         s["name"] = f"{name}_{n}"
         n += 1
      if s["name"] != name:
         renamed.append(f"override set {name} is {s['name']} here (another map has {name}); its scripts are not "
                        "imported")
      taken.add(s["name"])
      kept.append(s)
   gone = len([s for s in raw if isinstance(s, dict)]) - len(kept)
   if kept:
      data[SETS_KEY] = kept
   else:
      data.pop(SETS_KEY, None)
   return gone, renamed
