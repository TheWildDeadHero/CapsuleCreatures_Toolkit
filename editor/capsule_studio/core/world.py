"""!A world being edited: the world manifest plus its tilesets and maps.

Each file is its own Document (own undo history); the Project opens them on
demand, compiles them with the engine's map compiler (unsaved edits included,
through the compiler's in-memory sources) and saves them together. Nothing
here depends on a user interface.

Large worlds (I2: the imported Emerald world, 539 maps and 76 fixed tilesets)
need the editor to compile only what it shows: compiled_map() and
compiled_tileset() compile one map against the tilesets it draws from, with
each tileset compiled once per change (_tileset_cache), and check_events()
runs the engine's event and object compilers again only when a map's event
data, or the painted state of the cells its events stand on, changed
(_event_fingerprint()). compile() and validate() stay the engine's whole
compile_world(), the one authority before a build.
"""
from __future__ import annotations

import copy
import json
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from . import engine
from .document import Document, DocumentError, group

## World manifest schema.
WORLD_SCHEMA = "capsule.world/1"
## Tileset manifest schema.
TILESET_SCHEMA = "capsule.tileset/2"
## Map manifest schema.
MAP_SCHEMA = "capsule.map/2"
## Where the start position a world without one gets lands on the new map: x, in metatiles.
NEW_START_X = 3
## Where the start position a world without one gets lands on the new map: y, in metatiles.
NEW_START_Y = 3

## A parsed JSON object (a manifest, or a compiler's result).
JsonDict = dict[str, Any]
## An image as the engine's bitmap module holds it: (width, height, RGBA bytes).
Image = tuple[int, int, bytearray]
## A tileset compiled by the engine's map compiler (its tools/map_compiler.Tileset, imported at run time).
CompiledTileset = Any
## A tile layer of a new map: (bg, priority, purpose), as in maps.DEFAULT_LAYERS.
LayerSpec = tuple[int, int, str]
## What a cached compile depends on (revisions, file times), compared as a whole.
CacheKey = tuple[Any, ...]

## Map keys the event and object compilers read (tools/event_compiler.py parse_map(), object_compiler.py
## parse_objects(), map_compiler.event_cell_ok()): a map whose values of these, chunk positions and painted event
## cells are unchanged checks the same (check_events()).
EVENT_KEYS = ("events", "objects", "area", "object_view", "stacked_objects", "unpainted_events")
## Entries of an [x, y] cell.
XY = 2
## One-map compiles kept (the most recently used; I2: a compiled map of a large world's fixed tilesets holds a
## thousand tiles, so browsing 539 maps must not keep them all).
MAP_CACHE_SIZE = 8


class CachedTileset(NamedTuple):
   """!A compiled tileset in Project's cache (I2)."""
   ## What it was compiled from: (path, file key, unsaved images, behaviors, image file times).
   key: CacheKey
   ## The map_compiler.Tileset, or None when it did not compile.
   tileset: Any
   ## The compile error, or None.
   error: str | None
   ## The image files the compile read.
   files: list[Path]


class EventEntry(NamedTuple):
   """!A map's event fingerprint and event view in Project's cache (I2; see Project._event_entry())."""
   ## The document revision or file time they were made for.
   file_key: Any
   ## The fingerprint.
   fingerprint: Any
   ## The event view.
   view: JsonDict


class Project:
   """!A world file and the documents it lists."""

   def __init__(self, world: Document) -> None:
      """!Wraps an opened world Document.
      @param world  Document with schema capsule.world/1 and a path
      """
      if world.path is None:
         raise DocumentError("a world needs a file (save it first)")
      ## The world manifest's Document.
      self.world = world
      ## Opened documents: resolved Path -> Document.
      self._docs = {}
      ## Last compile results: key -> (revisions, result or None, error or None).
      self._cache = {}
      ## I2: compiled tilesets: name -> (CacheKey, map_compiler.Tileset or None, error or None, image files read).
      self._tileset_cache: dict[str, CachedTileset] = {}
      ## I2: one-map compiles: map name -> (CacheKey, compile_map() dict or None, error or None).
      self._map_cache = OrderedDict()
      ## I2: per map, its EventEntry (_event_entry()).
      self._fingerprints: dict[str, EventEntry] = {}
      ## I2: the last check_events(): (fingerprint of the world, error or None).
      self._event_check = None
      ## I2: resolved paths of listed files: (kind, relative path) -> Path.
      self._resolved: dict[tuple[str, str], Path] = {}
      ## I2: the last core.events.names(): (CacheKey, names).
      self.names_cache: tuple[CacheKey, Any] | None = None
      ## I2: the last check_encounters() per map list: maps -> (CacheKey, error or None).
      self._encounter_checks: dict[Any, tuple[CacheKey, str | None]] = {}
      ## I2: per map file not opened, (file time, map_head()).
      self._map_heads: dict[Path, tuple[int, JsonDict]] = {}
      ## C8: the battle field actions the last world save made follow ("field action NAME: OLD -> NEW").
      self.followed_battle: list[str] = []

   @classmethod
   def open(cls, path: str | Path) -> Project:
      """!Opens a world file.
      @param path  world.json
      @return Project
      """
      return cls(Document.open(path, WORLD_SCHEMA))

   @classmethod
   def create(cls, path: str | Path, name: str = "world") -> Project:
      """!Starts a new, empty world file (written at once).
      @param path  world.json to create (its folder is the world's folder)
      @param name  world id
      @return Project
      """
      p = Path(path)
      if p.exists():
         raise DocumentError(f"{p} already exists")
      p.parent.mkdir(parents=True, exist_ok=True)
      doc = Document(path=p, schema=WORLD_SCHEMA)
      doc.data["id"] = name
      doc.save()
      return cls(doc)

   @property
   def base(self) -> Path:
      """!The world's folder.
      @return Path
      """
      return self.world.path.parent

   # -- names and documents -----------------------------------------------------

   def tileset_names(self) -> list[str]:
      """!Tilesets the world lists.
      @return list of names
      """
      return list((self.world.data.get("tilesets") or {}).keys())

   def map_names(self) -> list[str]:
      """!Maps the world lists.
      @return list of names
      """
      return list((self.world.data.get("maps") or {}).keys())

   def behavior_names(self) -> list[str]:
      """!Terrain classes of the world, in index order.
      @return list of names
      """
      return [b.get("name", "?") for b in self.world.data.get("behaviors", [])]

   def _path_of(self, kind: str, name: str) -> Path:
      """!File of a listed tileset or map.
      @param kind  "tilesets" or "maps"
      @param name  its name
      @return resolved Path
      """
      rel = (self.world.data.get(kind) or {}).get(name)
      if rel is None:
         raise DocumentError(f"the world has no {kind[:-1]} {name!r}")
      # I2: resolving is a file system walk; a large world asks for its 539 maps' paths often
      key = (kind, rel)
      path = self._resolved.get(key)
      if path is None:
         path = self._resolved[key] = (self.base / rel).resolve()
      return path

   def _doc(self, path: Path, schema: str) -> Document:
      """!Opens (once) a document.
      @param path    resolved Path
      @param schema  expected schema
      @return Document
      """
      docs = self._docs
      if path not in docs:
         if path.exists():
            docs[path] = Document.open(path, schema)
         else:   # listed but never written (an earlier save failed): start it empty, write it next save
            doc = Document(path=path, schema=schema)
            doc.data["id"] = path.stem
            doc.dirty = True
            docs[path] = doc
         if schema == TILESET_SCHEMA:
            # I2: a tileset edit renumbers the "all" maps it reorders (follow_metatile_order()) in the same step
            docs[path].group_edits = True
      return docs[path]

   def map_path(self, name: str) -> Path:
      """!A listed map's file.
      @param name  map name
      @return resolved Path
      """
      return self._path_of("maps", name)

   def metatile_names(self, tileset: str) -> list[str]:
      """!A tileset's metatile names in order (what an "all" dictionary holds of it; I2).
      @param tileset  tileset name
      @return names ([] for a tileset the world does not list)
      """
      if tileset not in self.tileset_names():
         return []
      return [m.get("name") for m in self.tileset(tileset).data.get("metatiles", []) if isinstance(m, dict)]

   def dictionary(self, map_name: str) -> list[str]:
      """!A map's metatile dictionary, resolved (an "all" dictionary is every metatile of its tilesets; I2).
      @param map_name  map name
      @return list of "tileset/metatile"
      """
      from . import maps
      names_of = self.metatile_names   # a local name: Doxygen misreads a bound method passed on as a variable
      return maps.dictionary(self.map(map_name).data, names_of)

   @staticmethod
   def _head_of(data: Any) -> JsonDict:
      """!The light part of a map manifest (see map_head()).
      @param data  parsed map manifest
      @return {"tilesets", "all", "location", "encounters", "override_sets" (S3: the set names)}
      """
      from . import maps
      data = data if isinstance(data, dict) else {}
      raw_sets = data.get("override_sets")
      sets = [s.get("name") for s in raw_sets if isinstance(s, dict)] if isinstance(raw_sets, list) else []
      return {"tilesets": maps.tilesets_of(data), "all": maps.uses_all(data), "location": data.get("location"),
              "encounters": data.get("encounters"), "override_sets": sets}

   def map_head(self, name: str) -> JsonDict:
      """!What world-wide views need of a map without opening it (I2: a large world's 539 map documents are not
      all opened to list their tilesets or locations): its tilesets, whether its dictionary is "all", its location
      and encounter file. An open map's document is read; other files are read once per change of the file.
      @param name  map name
      @return {"tilesets": [names], "all": bool, "location": key or None, "encounters": path or None,
              "override_sets": [S3: names]}
      """
      path = self._path_of("maps", name)
      if path in self._docs:
         return self._head_of(self._docs[path].data)
      try:
         mtime = path.stat().st_mtime_ns
      except OSError:
         return self._head_of({})
      hit = self._map_heads.get(path)
      if hit is None or hit[0] != mtime:
         try:
            data = json.loads(path.read_text(encoding="utf-8"))
         except (OSError, ValueError):
            data = {}
         hit = (mtime, self._head_of(data))
         self._map_heads[path] = hit
      return hit[1]

   def companions(self, tileset: str) -> list[str]:
      """!The tilesets maps load together with a tileset, in their order (I2: a fixed tileset's metatiles may draw
      tiles another one places, so its pictures are drawn with the tilesets the maps load with it): the list
      most maps that use it have, else just the tileset.
      @param tileset  tileset name
      @return tileset names, the tileset included
      """
      counts: dict[tuple[str, ...], int] = {}
      for n in self.map_names():
         uses = self.map_head(n)["tilesets"]
         if tileset in uses:
            key = tuple(t for t in uses if t in self.tileset_names())
            counts[key] = counts.get(key, 0) + 1
      if not counts:
         return [tileset]
      # the most common list, and of those the first in sort order (stable across runs)
      return list(max(sorted(counts), key=lambda k: counts[k]))

   def follow_metatile_order(self, tileset: str, before: Sequence[str]) -> list[str]:
      """!After a tileset's metatiles were added, removed or reordered: renumbers the cells of every map with an
      "all" dictionary that draws from it, so they show the same metatiles (I2; call inside the tileset's edit, so
      the maps' changes join its undo step). Refused when a removed metatile is painted on such a map.
      @param tileset  tileset name
      @param before   its metatile names before the change
      @return names of the maps renumbered
      """
      from . import maps
      after = self.metatile_names(tileset)
      if list(before) == after:
         return []
      changed = []
      names_of = self.metatile_names   # a local name: Doxygen misreads a bound method passed on
      for n in self.map_names():
         head = self.map_head(n)
         if not head["all"] or tileset not in head["tilesets"]:
            continue
         doc = self.map(n)
         with doc.edit("Follow tileset"):
            if maps.follow_metatile_order(doc, tileset, before, after, names_of):
               changed.append(n)
      return changed

   def edit_tileset(self, tileset: str, label: str, change: Callable[[Document], Any]) -> Any:
      """!Runs a change of a tileset as one undo step, with the "all" maps it renumbers (follow_metatile_order()).
      @param tileset  tileset name
      @param label    undo label
      @param change   callable(tileset Document) doing the change
      @return what change() returned
      """
      doc = self.tileset(tileset)
      before = self.metatile_names(tileset)
      with group(label), doc.edit(label):
         out = change(doc)
         self.follow_metatile_order(tileset, before)
      return out

   def tileset(self, name: str) -> Document:
      """!A tileset's Document.
      @param name  tileset name
      @return Document
      """
      return self._doc(self._path_of("tilesets", name), TILESET_SCHEMA)

   def map(self, name: str) -> Document:
      """!A map's Document.
      @param name  map name
      @return Document
      """
      return self._doc(self._path_of("maps", name), MAP_SCHEMA)

   def documents(self) -> list[Document]:
      """!The world and every opened document.
      @return list of Documents
      """
      return [self.world] + list(self._docs.values())

   @property
   def dirty(self) -> bool:
      """!Whether any document has unsaved changes.
      @return True when one has
      """
      return any(d.dirty for d in self.documents())

   def save_all(self) -> None:
      """!Saves every document with changes (images of tileset sheets
      included). The world file goes last, so a failed save never leaves it
      listing a tileset or map file that was not written.
      @return None
      """
      for d in list(self._docs.values()) + [self.world]:
         if d is self.world and (d.dirty or d.pending):
            self._save_world()
         elif d.dirty or d.pending:
            d.save()

   def _save_world(self) -> None:
      """!Saves the world file; C8: the game's battle field actions then follow the object kinds and map tags the
      saved world renamed (core.map_field.follow_saved_renames(): the battle data names what the world on disk
      names, before and after this save).
      @return None
      """
      from . import map_field   # local: core.map_field imports this module's Project for type hints only
      before = map_field.saved_names(self.world)
      self.world.save()
      self.followed_battle[:] = map_field.follow_saved_renames(self, before)

   def save_document(self, doc: Document) -> None:
      """!Saves one document (with its new sheet images), then the world
      file when it has changes too (it lists the document, so a new map or
      tileset is never left out of it).
      @param doc  a Document of this project
      @return None
      """
      if doc is self.world:
         if doc.dirty or doc.pending:
            self._save_world()
         return
      if doc.dirty or doc.pending:
         doc.save()
      if self.world.dirty or self.world.pending:
         self._save_world()

   # -- adding --------------------------------------------------------------------

   def _add(self, kind: str, name: str, rel: str | None, schema: str, data: JsonDict | None,
            also: Callable[[], None] | None = None) -> Document:
      """!Lists a new tileset or map in the world and creates its document.
      @param kind    "tilesets" or "maps"
      @param name    its name
      @param rel     file relative to the world, or None for the default
      @param schema  its schema
      @param data    initial content, or None
      @param also    callable run inside the same world edit, or None
      @return the new Document
      """
      if not name or "/" in name or ":" in name:
         raise DocumentError("names have no '/' or ':'")
      if name in (self.world.data.get(kind) or {}):
         raise DocumentError(f"the world already has a {kind[:-1]} {name!r}")
      rel = rel or f"{kind}/{name}.json"
      path = (self.base / rel).resolve()
      if path in self._docs or path.exists():
         raise DocumentError(f"{rel} already exists")
      with self.world.edit(f"Add {kind[:-1]}"):
         self.world.data.setdefault(kind, {})[name] = rel
         if also is not None:
            also()
      doc = Document(data, path=path, schema=schema)
      doc.data["id"] = name
      doc.dirty = True
      self._docs[path] = doc
      return doc

   def adopt(self, kind: str, name: str, data: JsonDict) -> Document:
      """!Opens a new document for a tileset or map the world already lists
      (an import listed it), holding @p data until it is saved.
      @param kind  "tilesets" or "maps"
      @param name  its name in the world
      @param data  its manifest
      @return the new Document
      """
      path = self._path_of(kind, name)
      if path in self._docs or path.exists():
         raise DocumentError(f"{path.name} already exists")
      doc = Document(data, path=path, schema=TILESET_SCHEMA if kind == "tilesets" else MAP_SCHEMA)
      doc.dirty = True
      self._docs[path] = doc
      return doc

   def adopt_document(self, path: str | Path, schema: str, data: JsonDict) -> Document:
      """!Opens a new, unsaved document of any schema (an encounter file an
      import brings along), written with save_all().
      @param path    resolved file path (must not exist yet)
      @param schema  its schema (one of document.EMPTY)
      @param data    its manifest
      @return the Document
      """
      path = Path(path).resolve()
      if path in self._docs or path.exists():
         raise DocumentError(f"{path.name} already exists")
      doc = Document(data, path=path, schema=schema)
      doc.dirty = True
      self._docs[path] = doc
      return doc

   def import_from(self, source_path: str | Path, maps: Iterable[str] = (), tilesets: Iterable[str] = ()) -> list[str]:
      """!Imports maps and tilesets from another world, with the tilesets,
      sheet images and behaviors they need (see core.importer).
      @param source_path  the other world's world.json
      @param maps         its maps to import
      @param tilesets     its tilesets to import
      @return report lines
      """
      from . import importer
      return importer.run(self, Project.open(source_path), maps, tilesets)

   def add_tileset(self, name: str, rel: str | None = None) -> Document:
      """!Adds an empty tileset (saved with save_all()).
      @param name  tileset name
      @param rel   file relative to the world, default tilesets/NAME.json
      @return Document
      """
      return self._add("tilesets", name, rel, TILESET_SCHEMA, None)

   def add_map(self, name: str, rel: str | None = None, fill: str | None = None, tilesets: Iterable[str] | None = None,
               layers: Iterable[LayerSpec] | None = None, group: Sequence[str] | None = None) -> Document:
      """!Adds a map (saved with save_all()): blank, or with one chunk and
      the border painted with @p fill on its back layer. A world without a
      start position gets one on this map, so it compiles.
      @param name      map name
      @param rel       file relative to the world, default maps/NAME.json
      @param fill      "tileset/metatile" to paint its first chunk and border with, or None for a blank map
      @param tilesets  tilesets the map draws from (default: none, or fill's tileset)
      @param layers    (bg, priority, purpose) per tile layer, default maps.DEFAULT_LAYERS
      @param group     map group path to put it in (see core.mapgroups), or None for ungrouped
      @return Document
      """
      from . import mapgroups
      if group and mapgroups.find(self.world.data, tuple(group)) is None:
         raise DocumentError(f"no map group {'/'.join(group)!r}")
      from . import maps
      tilesets = list(tilesets or [])
      unknown = [t for t in tilesets if t not in self.tileset_names()]
      if unknown:
         raise DocumentError(f"the world has no tileset {unknown[0]!r}")
      if fill is not None and fill.split("/", 1)[0] not in tilesets:
         tilesets.append(fill.split("/", 1)[0])
      layers = tuple(layers) if layers is not None else maps.DEFAULT_LAYERS
      # Each layer needs a BG of its own.
      if len(layers) > maps.max_layers() or len({bg for bg, _p, _u in layers}) != len(layers):
         raise DocumentError("a map has up to four tile layers, each on its own BG")
      data = maps.new_map_data(name, tilesets, layers)
      if fill is not None:
         if not layers:
            raise DocumentError("a filled map needs a tile layer")
         # Metatile 0 (the fill) on the back layer of the border and of one chunk; the other layers stay empty.
         back = maps.draw_order(data)[0]
         data["metatiles"] = [fill]
         data["border"]["layers"][back] = [0]
         grids = [[[0 if k == back else None] * maps.CHUNK for _ in range(maps.CHUNK)] for k in range(len(layers))]
         data["chunks"] = [{"at": [0, 0], "cells": [[0] * maps.CHUNK for _ in range(maps.CHUNK)], "layers": grids}]

      def start() -> None:
         """!Gives the world a start position on the new map when it has none, and files the map in its group."""
         if not isinstance(self.world.data.get("start"), dict):
            self.world.data["start"] = {"map": name, "x": NEW_START_X, "y": NEW_START_Y, "facing": "down"}
         if group:
            mapgroups.move_map(self.world, name, tuple(group))
      return self._add("maps", name, rel, MAP_SCHEMA, data, start)

   def rename_metatile(self, tileset: str, old: str, new: str) -> list[str]:
      """!Renames a metatile in its tileset and in every map using it (one
      undo step per changed document).
      @param tileset  tileset name
      @param old      current metatile name
      @param new      new name
      @return names of the maps that were updated
      """
      from . import maps, tilesets
      doc = self.tileset(tileset)
      with doc.edit("Rename metatile"):
         tilesets.rename_metatile(doc, old, new)
      changed = []
      for name in self.map_names():
         mdoc = self.map(name)
         if f"{tileset}/{old}" in mdoc.data.get("metatiles", []):
            with mdoc.edit("Rename metatile"):
               maps.rename_metatile_refs(mdoc, f"{tileset}/{old}", f"{tileset}/{new}")
            changed.append(name)
      return changed

   # -- compiling -------------------------------------------------------------------

   def _sources(self) -> tuple[dict[Path, JsonDict], dict[Path, Image]]:
      """!Unsaved documents for the compiler.
      @return (sources {Path: data}, images {Path: (w, h, RGBA)})
      """
      # Listed, never written: compile as empty.
      for kind, schema in (("tilesets", TILESET_SCHEMA), ("maps", MAP_SCHEMA)):
         for name in (self.world.data.get(kind) or {}):
            path = self._path_of(kind, name)
            if path not in self._docs and not path.exists():
               self._doc(path, schema)
      sources = {d.path: d.data for d in self.documents() if d.path is not None}
      # Imported sheet images not saved yet, by the file they will be written to.
      images = {}
      for d in self.documents():
         for rel, img in d.pending.items():
            images[(d.path.parent / rel).resolve()] = img
      return sources, images

   def _revisions(self) -> tuple[tuple[str, int], ...]:
      """!Revision of every document, to tell when a cached compile is stale.
      @return tuple
      """
      return tuple((str(d.path), d.revision) for d in self.documents())

   def compile(self, only_maps: Iterable[str] | None = None) -> tuple[JsonDict | None, str | None]:
      """!Compiles the world with the engine's map compiler.
      @param only_maps  map names to compile, or None for all
      @return (result dict or None, error message or None)
      """
      key = tuple(only_maps) if only_maps else None
      revs = self._revisions()
      hit = self._cache.get(key)
      if hit:
         hit_revs, hit_result, hit_error = hit
         if hit_revs == revs:
            return hit_result, hit_error
      sources, images = self._sources()
      try:
         mc = engine.tool("map_compiler")
         result, error = mc.compile_world(self.world.path, None, sources, images, only_maps), None
      except Exception as e:   # the compiler's ManifestErrors, plus asset compiler / key errors
         result, error = None, str(e)
      self._cache[key] = (revs, result, error)
      return result, error

   def _file_key(self, path: Path) -> Any:
      """!What a file's compile depends on: its open Document's revision, else the file's time.
      @param path  resolved Path
      @return a comparable value
      """
      doc = self._docs.get(path)
      if doc is not None:
         return ("doc", id(doc), doc.revision)
      try:
         return ("file", path.stat().st_mtime_ns)
      except OSError:
         return ("missing",)

   @staticmethod
   def _times(paths: Iterable[Path]) -> tuple[Any, ...]:
      """!Modification times of files (image sheets a compile read), missing files included.
      @param paths  files
      @return tuple of times (None for a missing file)
      """
      out = []
      for p in paths:
         try:
            out.append(p.stat().st_mtime_ns)
         except OSError:
            out.append(None)
      return tuple(out)

   def compiled_tilesets(self, names: Iterable[str]) -> tuple[dict[str, CompiledTileset], str | None]:
      """!Tilesets compiled with the engine's map_compiler.compile_tileset(), each once per change of its manifest,
      its unsaved images, its image files or the world's behaviors (I2: a map of a large world compiles against
      the tilesets it draws from only).
      @param names  tileset names (unknown ones are left out)
      @return ({name: Tileset}, the first error or None)
      """
      mc = engine.tool("map_compiler")
      behaviors = tuple(self.behavior_names())
      out, error = {}, None
      for name in names:
         if name not in self.tileset_names():
            continue
         path = self._path_of("tilesets", name)
         doc = self._docs.get(path)
         pending = tuple(sorted(doc.pending)) if doc is not None else ()
         hit = self._tileset_cache.get(name)
         key = (path, self._file_key(path), pending, behaviors)
         # the key without, then with, the image files' times (they are only known after a compile)
         if hit is None or hit.key[:-1] != key or hit.key[-1] != self._times(hit.files):
            deps: list[Path] = []
            sources = {path: doc.data} if doc is not None else None
            images = {(path.parent / rel).resolve(): img for rel, img in doc.pending.items()} if doc else None
            try:
               ts, err = mc.compile_tileset(name, path, {b: i for i, b in enumerate(behaviors)}, deps, sources,
                                            images), None
            except Exception as e:   # the compiler's ManifestErrors, plus bitmap / key errors
               ts, err = None, str(e)
            files = [Path(d) for d in deps if Path(d) != path]
            hit = CachedTileset(key + (self._times(files),), ts, err, files)
            self._tileset_cache[name] = hit
         if hit.tileset is not None:
            out[name] = hit.tileset
         elif error is None:
            error = hit.error
      return out, error

   def _world_rules(self) -> tuple[list[str], int]:
      """!What compile_map() takes from the world: its map tags and its darkest level (map_compiler.map_tags(),
      darkness_levels()).
      @return (tags, darkest level)
      """
      mc = engine.tool("map_compiler")
      w = self.world.data
      return mc.map_tags(w), len(mc.darkness_levels(w))

   def compiled_map(self, name: str) -> tuple[JsonDict | None, str | None]:
      """!One map compiled with the engine's map_compiler.compile_map() against the tilesets it draws from (its
      "tilesets", else those its dictionary names), each compiled once per change (I2; the whole world's checks
      are compile()'s).
      @param name  map name
      @return (compile_map() dict or None, error or None)
      """
      from . import maps
      if name not in self.map_names():
         return None, f"the world has no map {name!r}"
      path = self._path_of("maps", name)
      doc = self.map(name)
      uses = [t for t in maps.tilesets_of(doc.data, self.tileset_names()) if t in self.tileset_names()]
      tilesets, error = self.compiled_tilesets(uses)
      tkeys = tuple(self._tileset_cache[t].key for t in uses if t in self._tileset_cache)
      key = (self._file_key(path), tkeys, self.world.revision)
      hit = self._map_cache.get(name)
      if hit is not None and hit[0] == key:
         self._map_cache.move_to_end(name)
         _key, compiled, compile_error = hit
         return compiled, compile_error
      mc = engine.tool("map_compiler")
      if error is not None:
         result = (None, error)
      else:
         try:
            tags, darkest = self._world_rules()
            result = (mc.compile_map(name, path, tilesets, self.behavior_names() or None, sources={path: doc.data},
                                     tags=tags, darkest=darkest), None)
         except Exception as e:   # the compiler's ManifestErrors, plus asset compiler / key errors
            result = (None, str(e))
      self._map_cache[name] = (key,) + result
      self._map_cache.move_to_end(name)
      while len(self._map_cache) > MAP_CACHE_SIZE:
         self._map_cache.popitem(last=False)
      return result

   def compiled_tileset(self, name: str, context: Sequence[str] | None = None
                        ) -> tuple[CompiledTileset | None, JsonDict | None, str | None]:
      """!A tileset compiled on its own, with a preview map holding every
      metatile (for tileset views and metatile pickers). I2: a fixed tileset's
      metatiles may draw tiles and palette banks other fixed tilesets place, so
      its preview loads them as a map does: @p context, default companions().
      @param name     tileset name
      @param context  the tilesets the preview loads (the tileset included), or None
      @return (Tileset, preview map dict, error) — the first two None on error
      """
      from . import maps
      found, error = self.compiled_tilesets([name])
      ts = found.get(name)
      if ts is None:
         return None, None, error or f"the world has no tileset {name!r}"
      uses = None
      if ts.place is not None:   # fixed: load the tilesets maps load it with (all fixed, as compile_map() wants)
         others, _err = self.compiled_tilesets(context if context is not None else self.companions(name))
         uses = [t for t in (context if context is not None else self.companions(name))
                 if t in others and others[t].place is not None]
         if name not in uses:
            uses.append(name)
         found = {t: others.get(t, ts) for t in uses}
      key = ("tileset", name, tuple(uses or ()), tuple(self._tileset_cache[t].key for t in (uses or [name])),
             self.world.revision)
      hit = self._cache.get(key)
      if hit:
         return hit
      names = [f"{name}/{m}" for m in ts.metatiles]
      preview = None
      try:
         mc = engine.tool("map_compiler")
         if names:   # one layer, one painted chunk: metatile i of the preview is the tileset's metatile i
            fake = (self.base / f".preview-{name}.json").resolve()
            data = {"schema": MAP_SCHEMA, "layers": [{"bg": 0, "priority": 0}], "metatiles": names,
                    "border": {"size": [1, 1], "layers": [[0]]},
                    "chunks": [{"at": [0, 0], "cells": [[0] * maps.CHUNK for _ in range(maps.CHUNK)],
                                "layers": [[[0] * maps.CHUNK for _ in range(maps.CHUNK)]]}]}
            if uses is not None:
               data["tilesets"] = uses
            preview = mc.compile_map(f"{name} preview", fake, found, self.behavior_names() or None, "tileset",
                                     {fake: data})
         out = (ts, preview, None)
      except Exception as e:
         out = (None, None, str(e))
      self._cache[key] = out
      return out

   # -- events (I2: checked again only when what they read changed) -------------------------------

   def _event_fingerprint(self, name: str) -> Any:
      """!What the engine's event and object compilers read of a map: EVENT_KEYS, its chunk positions and which of
      the cells its events and objects stand on are painted (map_compiler.event_cell_ok(), raw_chunk_positions()).
      Cached per document revision (or file time), so painting another cell costs one look at the map.
      @param name  map name
      @return a comparable value
      """
      return self._event_entry(name)[0]

   def _event_view(self, name: str) -> JsonDict:
      """!The part of a map manifest the event and object compilers read (EVENT_KEYS, and the chunks' "at" and
      "cells"; schema and id kept), for compile_world_events(): the tile layers, a large map's most data, are left
      out, so a large world's events check without stripping every map's layers.
      @param name  map name
      @return a manifest dict (shares lists with the document: read only)
      """
      return self._event_entry(name)[1]

   def _event_entry(self, name: str) -> tuple[Any, JsonDict]:
      """!A map's event fingerprint and event view (see _event_fingerprint(), _event_view()), cached per document
      revision or file time.
      @param name  map name
      @return (fingerprint, view)
      """
      from . import maps
      path = self._path_of("maps", name)
      fkey = self._file_key(path)
      hit = self._fingerprints.get(name)
      if hit is not None and hit.file_key == fkey:
         return hit.fingerprint, hit.view
      try:
         data = self._docs[path].data if path in self._docs else json.loads(path.read_text(encoding="utf-8"))
      except (OSError, ValueError):
         data = None
      view: JsonDict = {}
      if not isinstance(data, dict):
         fp: Any = ("unreadable", fkey)
      else:
         view = {k: data[k] for k in ("schema", "id") + EVENT_KEYS if k in data}
         if isinstance(data.get("chunks"), list):
            view["chunks"] = [{k: c[k] for k in ("at", "cells") if k in c} if isinstance(c, dict) else c
                              for c in data["chunks"]]
         cells = []
         ev = data.get("events")
         lists = [v for v in ev.values() if isinstance(v, list)] if isinstance(ev, dict) else []
         objs = data.get("objects")
         for item in [e for lst in lists for e in lst] + (objs if isinstance(objs, list) else []):
            at = item.get("at") if isinstance(item, dict) else None
            if isinstance(at, list) and len(at) == XY and all(isinstance(v, int) for v in at):
               cells.append((at[0], at[1], maps.get(data, at[0], at[1]) is not None))
         chunks = [c.get("at") for c in data.get("chunks", []) or [] if isinstance(c, dict)]
         fp = (json.dumps({k: data.get(k) for k in EVENT_KEYS}, sort_keys=True), json.dumps(chunks),
               tuple(sorted(cells)))
      self._fingerprints[name] = EventEntry(fkey, fp, view)
      return fp, view

   def scripts_times(self, scripts_path: Path | None = None) -> tuple[Any, ...]:
      """!Modification times of the scripts manifest's folder (the manifest and the sources it names relative to
      it): what a cached look at the scripts depends on (I2: a large game's 2,000 scripts compile in a second).
      @param scripts_path  the game's scripts manifest, or None for the world's "scripts"
      @return ((file, time), ...)
      """
      scripts = self.world.data.get("scripts")
      folder = (self.base / scripts).resolve().parent if isinstance(scripts, str) and scripts else None
      if scripts_path is not None:
         folder = Path(scripts_path).resolve().parent
      if folder is None or not folder.is_dir():
         return ()
      return tuple(sorted((str(p), p.stat().st_mtime_ns) for p in folder.rglob("*") if p.is_file()))

   def disk_times(self) -> tuple[Any, ...]:
      """!Modification times of the world file and its maps' files on disk (what a tool reading the files, such as
      the script compiler, depends on).
      @return times (None for a missing file)
      """
      return self._times([self.world.path] + [self._path_of("maps", n) for n in self.map_names()])

   def check_events(self, scripts_path: Path | None = None) -> str | None:
      """!Compiles every map's events and objects with the engine's map_compiler.compile_world_events() (event and
      object compilers), on the open documents; again only when a map's event fingerprint, the world file or the
      scripts manifest's folder changed (I2).
      @param scripts_path  the game's scripts manifest (project.json "scripts"), or None
      @return error message, or None when they compile
      """
      mc = engine.tool("map_compiler")
      key = (self._file_key(self.world.path), str(scripts_path), self.scripts_times(scripts_path),
             tuple(self._event_fingerprint(n) for n in self.map_names()))
      if self._event_check is not None and self._event_check[0] == key:
         return self._event_check[1]
      # the world, and each map's event view (what the event and object compilers read of it)
      sources = {self.world.path: self.world.data}
      sources.update({self._path_of("maps", n): self._event_view(n) for n in self.map_names()})
      try:
         w, _b, _c, _t, map_paths = mc.load_world(self.world.path, sources)
         # [] collects the files read (a depfile), unused here.
         base = self.base
         mc.compile_world_events(w, base, map_paths, [], sources, scripts_path)
         error = None
      except Exception as e:   # the compiler's ManifestErrors, and broken manifests
         error = str(e)
      self._event_check = (key, error)
      return error

   def check_encounters(self, only_maps: Sequence[str] | None = None) -> str | None:
      """!Compiles the encounter tables with the engine's encounter_compiler.compile_encounters() (what
      compile_world() runs for them), on the open documents; again only after a change (I2: without the whole
      world's tilesets and maps).
      @param only_maps  these maps' tables, or None for all
      @return error message, or None when they compile
      """
      # the encounter compiler reads a map's "encounters" only (and the files it names, the shared tables and the
      # battle data): maps are given as that key, and painting a map does not check the tables again
      heads = tuple((n, self.map_head(n)["encounters"]) for n in self.map_names())
      others = tuple((str(d.path), d.revision) for d in self.documents()
                     if d.schema not in (MAP_SCHEMA, TILESET_SCHEMA))
      files = tuple(self._file_key((self._path_of("maps", n).parent / rel).resolve()) for n, rel in heads
                    if isinstance(rel, str))
      battle = self.world.data.get("battle")
      battle_key = self._file_key((self.base / battle).resolve()) if isinstance(battle, str) else None
      key = (heads, others, files, battle_key)
      name = tuple(only_maps) if only_maps is not None else None
      hit = self._encounter_checks.get(name)
      if hit is not None and hit[0] == key:
         return hit[1]
      mc = engine.tool("map_compiler")
      ec = engine.tool("encounter_compiler")
      sources = {d.path: d.data for d in self.documents() if d.path is not None and
                 d.schema not in (MAP_SCHEMA, TILESET_SCHEMA)}
      sources.update({self._path_of("maps", n): {"encounters": rel} if isinstance(rel, str) else {}
                      for n, rel in heads})
      try:
         w, _b, classes, _t, map_paths = mc.load_world(self.world.path, sources)
         ec.compile_encounters(w, self.world.path, classes, map_paths, [], sources, only_maps)
         error = None
      except Exception as e:   # the compiler's ManifestErrors, and broken manifests
         error = str(e)
      self._encounter_checks[name] = (key, error)
      return error

   def snapshot(self) -> Callable[[], tuple[JsonDict | None, str | None]]:
      """!A whole-world compile that can run on another thread while the documents are edited: the open
      documents' data and images are copied now (I2: a large world's compile() takes long; the editor runs it in
      the background and shows the result when it is done).
      @return callable() -> (compile_world() result or None, error or None), as compile()
      """
      sources, images = self._sources()
      # documents with unsaved changes are copied; the others are what their files hold, read by the compile
      sources = {p: copy.deepcopy(data) for p, data in sources.items()
                 if p not in self._docs or self._docs[p].dirty} if sources else {}
      if self.world.dirty:
         sources[self.world.path] = copy.deepcopy(self.world.data)
      else:
         sources.pop(self.world.path, None)
      images = dict(images)
      path = self.world.path

      def run() -> tuple[JsonDict | None, str | None]:
         """!Compiles the copies."""
         try:
            return engine.tool("map_compiler").compile_world(path, None, sources, images, None), None
         except Exception as e:   # the compiler's ManifestErrors, plus asset compiler / key errors
            return None, str(e)
      return run

   def validate(self) -> str | None:
      """!Compiles everything and reports.
      @return error message, or None when the world compiles
      """
      return self.compile()[1]

   def describe(self) -> str:
      """!A short summary for status lines.
      @return text
      """
      return json.dumps({"maps": self.map_names(), "tilesets": self.tileset_names()})
