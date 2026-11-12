"""!Plugin data: the connector blocks of a game's plugins (D-10 §4, plugin API 3), for the Plugin data panel and
`capsule-studio ext`.

A plugin's connector declares typed blocks at attach points (the project, the world, maps, cells, layers, battle
entries, assets); the engine's tools/connectors.py reads, checks and compiles them. Everything here goes through
that module (core.engine.tool()), so the Studio offers exactly the fields, records and checks the build has:

  - the schemas: each point's block as plain JSON (ConnectorSpec.describe()), which the panel builds its form from;
  - the records: where a block can go (connectors.targets()), and the blocks there now;
  - edits: a block set or removed as one Document edit (undo, redo, saving as for every other edit), on the
    Document a store hands out: the Studio's open documents (ProjectStore) or files (FileStore, the command line);
  - checks: connectors.run() over the open documents, unsaved changes included, as Diagnostics.

Nothing here imports Qt.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Protocol

from . import engine
from .document import EMPTY, Document, DocumentError, group

if TYPE_CHECKING:
   from ..plugins.registry import Diagnostic, FileFormat
   from .world import Project

## A JSON value.
Json = Any
## A block change: (attach point, record name, block or None to remove it).
Change = tuple[str, str, Json]
## The attach points whose diagnostics name a map: point -> callable(record name) -> map name.
MAP_OF = {"map": lambda name: name, "layer": lambda name: name.split("/", 1)[0],
          "cell": lambda name: name.split("@", 1)[0]}
## Attach points whose diagnostics show on every map (they concern the whole world).
WORLD_POINTS = ("project", "world")
## The schema a store gives a listed file that does not exist yet (only maps can be: the world lists them first).
EMPTY_SCHEMA = "capsule.map/2"


class PluginDataError(Exception):
   """!Plugin data that cannot be read or changed; the message says why."""
   pass


def tool() -> ModuleType:
   """!The engine's tools/connectors.py.
   @return the module
   @throws engine.EngineNotFound when no engine checkout is found
   """
   return engine.tool("connectors")


def load_connector(folder: str | Path) -> Any:
   """!Loads a plugin's connector with the engine (the plugin host's check: the build would refuse it otherwise).
   @param folder  the plugin's folder
   @return the engine's connectors.Plugin, or None when the plugin has no connector
   @throws PluginDataError when the engine refuses it
   """
   c = tool()
   try:
      return c.load_plugin(folder)
   except c.ConnectorError as e:
      raise PluginDataError(str(e)) from None


def attach_points() -> dict[str, str]:
   """!Every attach point and where its blocks live.
   @return {point: where}
   """
   return {name: point.where for name, point in tool().ATTACH_POINTS.items()}


def schema_of(path: Path) -> str:
   """!A manifest file's schema.
   @param path  the file
   @return its "schema"
   @throws PluginDataError when it cannot be read or its schema is not one the Studio edits
   """
   try:
      data = json.loads(path.read_text(encoding="utf-8"))
   except (OSError, ValueError) as e:
      raise PluginDataError(f"{path}: cannot read ({e})") from None
   schema = data.get("schema") if isinstance(data, dict) else None
   if schema not in EMPTY:
      raise PluginDataError(f"{path}: the Studio does not edit {schema!r} files")
   return schema


class Store(Protocol):
   """!Where the Documents of a game's files come from (ProjectStore, FileStore)."""

   def document(self, path: Path) -> Document:
      """!A file's Document.
      @param path  the resolved file
      @return Document
      """

   def opened(self) -> list[Document]:
      """!The Documents opened so far (their data replaces the files in checks).
      @return Documents
      """


class FileStore:
   """!Documents opened from files, for the command line (save() writes the changed ones)."""

   def __init__(self) -> None:
      """!Starts with none open."""
      ## Opened Documents: resolved Path -> Document.
      self._docs = {}

   def document(self, path: Path) -> Document:
      """!A file's Document (opened once).
      @param path  the file
      @return Document
      """
      resolved = Path(path).resolve()
      docs = self._docs
      if resolved not in docs:
         docs[resolved] = Document.open(resolved, schema_of(resolved), keep_layout=True)
      return docs[resolved]

   def opened(self) -> list[Document]:
      """!The Documents opened so far.
      @return Documents
      """
      return list(self._docs.values())

   def save(self) -> list[Path]:
      """!Writes the changed Documents.
      @return the files written
      """
      written = []
      for doc in self._docs.values():
         if doc.dirty:
            doc.save()
            written.append(doc.path)
      return written


class ProjectStore:
   """!The Studio's Documents: the world Project's (world, maps and the game's other manifests), or a Document
   another page of the Studio has open for the same file (shared)."""

   def __init__(self, project: Project, shared: Callable[[Path], Document | None] | None = None) -> None:
      """!Wraps a Project.
      @param project  core.world.Project
      @param shared   callable(path) -> another page's open Document of that file, or None
      """
      ## The world Project.
      self.project = project
      ## The Studio's other pages' documents.
      self.shared = shared
      ## Documents handed out by shared().
      self._shared = {}

   def document(self, path: Path) -> Document:
      """!A file's Document: another page's when it has the file open, else the Project's.
      @param path  the file
      @return Document
      """
      resolved = Path(path).resolve()
      if self.shared is not None and resolved != self.project.world.path:
         doc = self.shared(resolved)
         if doc is not None:
            self._shared[resolved] = doc
            return doc
      return self.project.document(resolved, schema_of(resolved) if resolved.exists() else EMPTY_SCHEMA)

   def opened(self) -> list[Document]:
      """!The Project's documents and the shared ones handed out.
      @return Documents
      """
      return self.project.documents() + [d for d in self._shared.values() if d not in self.project.documents()]


class PluginData:
   """!A game's connector plugins and their blocks."""

   def __init__(self, project_path: str | Path, store: Store) -> None:
      """!Opens a game.
      @param project_path  its reference/project.json
      @param store         where Documents come from (ProjectStore, FileStore)
      """
      ## The project manifest.
      self.project_path = Path(project_path).resolve()
      ## The Documents.
      self.store = store
      ## Loaded connectors (engine connectors.Plugin), or None until plugins().
      self._plugins = None
      ## The last check: (key, result).
      self._checked = None

   # -- the game ----------------------------------------------------------------------------------------------------

   def sources(self) -> dict[Path, Json]:
      """!The open Documents' data, which replaces their files (unsaved changes count).
      @return {path: data}
      """
      return {d.path: d.data for d in self.store.opened() if d.path is not None}

   def game(self) -> Any:
      """!The engine's view of the game, with the open Documents.
      @return connectors.Game
      @throws PluginDataError when the project cannot be read
      """
      c = tool()
      try:
         return c.Game(self.project_path, self.sources())
      except c.ConnectorError as e:
         raise PluginDataError(str(e)) from None

   def reload(self) -> None:
      """!Forgets the loaded plugins and the last check (the project's plugin list changed).
      @return None
      """
      self._plugins = None
      self._checked = None

   def plugins(self) -> list[Any]:
      """!The game's connectors, by id.
      @return connectors.Plugin list
      @throws PluginDataError when one cannot be loaded
      """
      if self._plugins is None:
         c = tool()
         try:
            self._plugins = c.load_plugins(self.game())
         except c.ConnectorError as e:
            raise PluginDataError(str(e)) from None
      return self._plugins

   def plugin(self, plugin_id: str) -> Any:
      """!One connector.
      @param plugin_id  its id
      @return connectors.Plugin
      @throws PluginDataError when the game has no such connector
      """
      for p in self.plugins():
         if p.plugin_id == plugin_id:
            return p
      have = ", ".join(p.plugin_id for p in self.plugins()) or "none"
      raise PluginDataError(f"the game has no plugin {plugin_id!r} with a connector (it has: {have})")

   def points(self, plugin_id: str) -> list[str]:
      """!Where a plugin's blocks go.
      @param plugin_id  the plugin
      @return attach points in declaration order
      """
      return list(self.plugin(plugin_id).spec.attach_points)

   def _schema(self, plugin_id: str, attach: str) -> Any:
      """!A point's block schema.
      @param plugin_id  the plugin
      @param attach     the attach point
      @return connectors.Block
      @throws PluginDataError when the plugin does not attach there
      """
      schema = self.plugin(plugin_id).spec.attach_points.get(attach)
      if schema is None:
         raise PluginDataError(f"{plugin_id} does not attach at {attach} (it attaches at "
                               f"{', '.join(self.points(plugin_id))})")
      return schema

   def schema(self, plugin_id: str, attach: str) -> dict[str, Json]:
      """!A point's block as plain JSON (type, fields, defaults, titles, help, choices, ranges, reference kinds).
      @param plugin_id  the plugin
      @param attach     the attach point
      @return the description
      """
      return self._schema(plugin_id, attach).describe()

   # -- records and blocks ------------------------------------------------------------------------------------------

   def targets(self, attach: str) -> list[Any]:
      """!The records a block can go on at a point (one per map for cells: name a cell with "MAP@x,y").
      @param attach  the attach point
      @return connectors.Target list
      """
      c = tool()
      try:
         return c.targets(self.game(), attach)
      except c.ConnectorError as e:
         raise PluginDataError(str(e)) from None

   def target(self, attach: str, name: str) -> Any:
      """!One record.
      @param attach  the attach point
      @param name    the record ("MAP@x,y" for a cell)
      @return connectors.Target
      """
      c = tool()
      try:
         return c.find_target(self.game(), attach, name)
      except c.ConnectorError as e:
         raise PluginDataError(str(e)) from None

   def names(self, kind: str) -> list[str]:
      """!What a reference field of a kind may name (the inspector's choices).
      @param kind  "species", "move", "item", "party", "presenter", "map" or "asset"
      @return names in the compilers' order
      """
      if kind == "asset":
         return [t.name for t in self.targets("asset")]
      return list(self.game().numbers(kind))

   def _data(self, path: Path) -> Json:
      """!A file's data from its Document.
      @param path  the file
      @return the data
      """
      return self.store.document(path).data

   def get(self, plugin_id: str, attach: str, name: str) -> Json:
      """!A plugin's block on a record, as written.
      @param plugin_id  the plugin
      @param attach     the attach point
      @param name       the record
      @return the block, or None when there is none
      """
      t = self.target(attach, name)
      c = tool()
      try:
         return c.get_block(self._data(t.path), t, plugin_id)
      except c.ConnectorError as e:
         raise PluginDataError(str(e)) from None

   def cells(self, plugin_id: str, map_name: str) -> list[tuple[int, int]]:
      """!The cells of a map with a plugin's block.
      @param plugin_id  the plugin
      @param map_name   the map
      @return [(x, y)]
      """
      for t in self.targets("cell"):
         if t.name == map_name:
            return tool().cells_of(self._data(t.path), plugin_id)
      raise PluginDataError(f"there is no map {map_name!r}")

   def records(self, plugin_id: str, attach: str) -> list[str]:
      """!The records at a point that carry the plugin's block now.
      @param plugin_id  the plugin
      @param attach     the attach point
      @return names
      """
      if attach == "cell":
         return [f"{t.name}@{x},{y}" for t in self.targets("cell")
                 for x, y in tool().cells_of(self._data(t.path), plugin_id)]
      c = tool()
      return [t.name for t in self.targets(attach) if c.get_block(self._data(t.path), t, plugin_id) is not None]

   def new_block(self, plugin_id: str, attach: str) -> dict[str, Json]:
      """!A block for a record without one: only the required fields, each with a starting value where its type has
      one (a choice's first name, an integer's minimum, false, ""); fields with a default stay out, so the file
      holds only what differs from the defaults, and required references stay out (the check then asks for them).
      @param plugin_id  the plugin
      @param attach     the attach point
      @return the block
      """
      out: dict[str, Json] = {}
      for key, f in self.schema(plugin_id, attach).get("fields", {}).items():
         if "default" in f:
            continue
         start = {"choice": (f.get("choices") or [None])[0], "integer": f.get("minimum"), "boolean": False,
                  "text": "", "list": []}.get(f.get("type"))
         if start is not None:
            out[key] = start
      return out

   def complete(self, plugin_id: str, attach: str, block: Json) -> Json:
      """!A block with its defaults filled in (what the hooks see before references resolve).
      @param plugin_id  the plugin
      @param attach     the attach point
      @param block      the block as written
      @return the block
      """
      schema = self._schema(plugin_id, attach)
      return schema.complete(block) if isinstance(block, dict) else block

   def problems(self, plugin_id: str, attach: str, block: Json) -> list[str]:
      """!What is wrong with a block by its schema alone (the inspector's live check).
      @param plugin_id  the plugin
      @param attach     the attach point
      @param block      the block
      @return messages
      """
      return self._schema(plugin_id, attach).check(block, f"{attach} {plugin_id}")

   def set(self, plugin_id: str, attach: str, name: str, block: Json,
           run_edit: Callable[[str, Callable[[], object], Document], bool] | None = None) -> bool:
      """!Sets (or removes) a plugin's block on a record as one Document edit.
      @param plugin_id  the plugin
      @param attach     the attach point
      @param name       the record
      @param block      the block, or None to remove it
      @param run_edit   the host's run_edit(label, fn, document), or None to edit the Document directly
      @return True when it went through
      """
      self._schema(plugin_id, attach)
      t = self.target(attach, name)
      doc = self.store.document(t.path)
      title = self.plugin(plugin_id).title or plugin_id
      label = f"{'Remove' if block is None else 'Set'} {title} on {attach} {name}"
      c = tool()

      def change() -> None:
         """!The edit (a record that moved since it was found is a DocumentError, which hosts report)."""
         try:
            c.set_block(doc.data, t, plugin_id, copy.deepcopy(block))
         except c.ConnectorError as e:
            raise DocumentError(str(e)) from None

      if run_edit is not None:
         return run_edit(label, change, doc)
      with doc.edit(label):
         change()
      return True

   def apply(self, plugin_id: str, changes: Sequence[Change], label: str) -> int:
      """!Several block changes as one undo step (a file import), over any number of files.
      @param plugin_id  the plugin
      @param changes    [(attach point, record name, block or None)]
      @param label      the undo step's label
      @return how many records changed
      """
      c = tool()
      planned = []
      for attach, name, block in changes:
         self._schema(plugin_id, attach)
         planned.append((self.target(attach, name), block))
      changed = 0
      with group(label):
         for t, block in planned:
            doc = self.store.document(t.path)
            before = c.get_block(doc.data, t, plugin_id)
            if before == block:
               continue
            with doc.edit(label):
               c.set_block(doc.data, t, plugin_id, copy.deepcopy(block))
            changed += 1
      return changed

   # -- checks and formats ------------------------------------------------------------------------------------------

   def _key(self) -> tuple[Any, ...]:
      """!What a check depends on: the open Documents' revisions and the files' times.
      @return a key
      """
      docs = tuple((str(d.path), d.revision) for d in self.store.opened())
      files = []
      deps = self._checked[1].deps if self._checked is not None else []
      for p in deps:
         try:
            files.append((str(p), p.stat().st_mtime_ns))
         except OSError:
            files.append((str(p), None))
      return docs, tuple(files)

   def check(self) -> Any:
      """!The build's checks over the open Documents (schemas, references, the validate hooks; nothing emitted).
      Cached until a Document or a file read changes.
      @return connectors.Result
      @throws PluginDataError when the project or a plugin cannot be loaded
      """
      key = self._key()
      if self._checked is not None and self._checked[0] == key:
         return self._checked[1]
      c = tool()
      try:
         result = c.run(self.project_path, self.sources(), emit=False)
      except c.ConnectorError as e:
         raise PluginDataError(str(e)) from None
      # The key names the files the check read, which only the result knows: store it, then key it by them.
      self._checked = (key, result)
      self._checked = (self._key(), result)
      return result

   def diagnostics(self, map_name: str | None = None) -> list[Diagnostic]:
      """!The checks as validator findings.
      @param map_name  only findings about this map (and the project and world as a whole), or None for all
      @return Diagnostics, each naming its plugin
      """
      from ..plugins.registry import Diagnostic   # local: the registry imports this module lazily too
      try:
         problems = self.check().problems
      except PluginDataError as e:
         return [Diagnostic("error", str(e), plugin="connectors")]
      out = []
      for p in problems:
         attach, name = p.record
         on_map = MAP_OF[attach](name) if attach in MAP_OF else None
         at = None
         if attach == "cell":
            at = tool().parse_cell(name)[1]
         if map_name is not None and on_map != map_name and attach not in WORLD_POINTS:
            continue
         out.append(Diagnostic(p.severity, p.message, on_map, at, plugin=p.plugin))
      return out

   def export(self, fmt: FileFormat) -> str:
      """!A plugin's blocks as a format's file.
      @param fmt  registry.FileFormat
      @return the text
      """
      if not fmt.can_export():
         raise PluginDataError(f"format {fmt.id} does not export")
      return fmt.export_data(self)

   def import_changes(self, fmt: FileFormat, text: str) -> list[Change]:
      """!The changes a format's file makes, checked (every block against its schema) before anything changes.
      @param fmt   registry.FileFormat
      @param text  the file's text
      @return [(attach point, record name, block or None)]
      @throws PluginDataError when the file cannot be read or a block does not fit
      """
      if not fmt.can_import():
         raise PluginDataError(f"format {fmt.id} does not import")
      try:
         changes = list(fmt.import_data(self, text))
      except (ValueError, KeyError, TypeError) as e:
         raise PluginDataError(f"format {fmt.id}: {e}") from None
      messages = []
      for attach, name, block in changes:
         self.target(attach, name)
         if block is not None:
            messages += self.problems(fmt.plugin, attach, block)
      if messages:
         raise PluginDataError("; ".join(messages))
      return changes


def for_project(project: Project, shared: Callable[[Path], Document | None] | None = None) -> PluginData | None:
   """!The plugin data of the game a world belongs to.
   @param project  core.world.Project
   @param shared   the Studio's other pages' documents (ProjectStore), or None
   @return PluginData, or None when the world is not part of a game (no reference/project.json lists it)
   """
   from ..plugins import project as plugin_project   # local: plugins imports core lazily too
   path, _game = plugin_project.find_project(project.world.path)
   return PluginData(path, ProjectStore(project, shared)) if path is not None else None


def for_files(project_path: str | Path) -> tuple[PluginData, FileStore]:
   """!The plugin data of a game, on its files (the command line).
   @param project_path  its reference/project.json
   @return (PluginData, the FileStore to save)
   """
   store = FileStore()
   return PluginData(project_path, store), store


def flatten(block: Json, prefix: str = "") -> Iterable[tuple[str, Json]]:
   """!A block's values as (dotted key, value) pairs (formats and the command line show them so).
   @param block   the block
   @param prefix  key prefix
   @return pairs
   """
   if isinstance(block, dict):
      for k, v in block.items():
         yield from flatten(v, f"{prefix}{k}.")
   else:
      yield prefix[:-1], block
