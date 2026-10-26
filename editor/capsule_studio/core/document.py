"""!An asset manifest (capsule.assets/1) being edited.

The Document owns the manifest JSON, undo history, and images imported but
not yet saved. It knows nothing about any user interface: editors (Qt panels,
the command line, scripts) change it inside edit() blocks and listen for
changes with subscribe().

Imported frames stay in memory until save(), which writes the ones the
manifest still refers to, so undoing an import leaves no stray files.

Edits of several Documents can be one undo step: every edit() block that
makes a step while a group() is open joins that group (an EditGroup), and
undo() or redo() of any of its Documents reverts or re-applies the whole
group in every member, in lock step [S14]: a member with newer steps on top
of the group's (an edit of that file alone, made later) undoes those first,
each whole (a redo likewise redoes the older steps undone after the group
first), so the files never disagree. A new step clears the redo history of
its Document and, for each group that history held, the redo steps of the
group's other members up to and including that group's; the HISTORY_LIMIT
trim drops whole groups the same way (with every older step of their
members), never a part of one. Inside a group both wait until the outermost
group() block ends without an error (EditGroup.commit()): a group rolled
back leaves each Document's history and unsaved state as they were. A Document whose group_edits is set opens a
group itself for its outermost edit(), so edits of other Documents made
inside its edit() blocks join its step. unsaved_group_files() names the
Documents that must be saved with one so no grouped step is saved in part.

Documents may be partners (two files of one set of data, such as a battle's
content and structure manifests): an edit() of one also opens an edit of
each partner inside the same group, so a block may change both and the
change is one undo step; only a Document that changed gets a step (and is
marked unsaved). An edit() opened inside another one of the same Document
is part of the outer one's step.

[S2] A Document opened with keep_layout=True (text tables, proportional fonts:
files a tool writes in Python's json layout) saves in the file's own layout
(manifest_io.detect()); a Document may carry the game's code page (codepage)
for its font assets' checks.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from . import engine, manifest_io

if TYPE_CHECKING:
   from .imaging import RgbaImage
   from .manifest_io import JsonDict

## Default manifest schema (asset manifests).
SCHEMA = "capsule.assets/1"
## Content of a new, empty document per schema.
EMPTY = {
   "capsule.assets/1": {"schema": "capsule.assets/1", "id": "untitled", "assets": []},
   "capsule.world/1": {"schema": "capsule.world/1", "id": "untitled", "vehicle_classes": ["foot"],
                       "behaviors": [{"name": "normal"}], "tilesets": {}, "maps": {}},
   "capsule.tileset/2": {"schema": "capsule.tileset/2", "id": "untitled", "sheets": [], "metatiles": []},
   # Blank, with the tile layers of core.maps.DEFAULT_LAYERS (BG0 stays free for text windows).
   "capsule.map/2": {"schema": "capsule.map/2", "id": "untitled", "tilesets": [],
                     "layers": [{"bg": 3, "priority": 3, "content": "tilemap", "purpose": "terrain"},
                                {"bg": 2, "priority": 2, "content": "tilemap", "purpose": "terrain"},
                                {"bg": 1, "priority": 1, "content": "tilemap", "purpose": "canopy"}],
                     "metatiles": [], "chunks": [], "border": {"size": [1, 1], "layers": [[None], [None], [None]]}},
   # Battle data and rulesets start from core.battle's templates (NEW_BATTLE, NEW_RULESET).
   "capsule.battle/1": {"schema": "capsule.battle/1", "id": "untitled"},
   "capsule.ruleset/2": {"schema": "capsule.ruleset/2", "formulas": {}},
   # The structure manifest a battle names (D-23 §2, E5s: structure.json, core.battle.NEW_STRUCTURE) and the
   # studio's wrapper of an effect source's text (the .ceffect file itself is plain text: core.battle.SourceDocument).
   "capsule.structure/1": {"schema": "capsule.structure/1"},
   "capsule.effect-source/1": {"schema": "capsule.effect-source/1", "text": ""},
   # A battle bench scenario (core.bench; the engine tool bench_scenario.py validates it).
   "capsule.bench/1": {"schema": "capsule.bench/1", "name": "scenario", "seed": 1, "parties": []},
   # A test save: a bag by pocket (core.inventory, G2; the Test save page and the testsave commands).
   "capsule.testsave/1": {"schema": "capsule.testsave/1", "pockets": {}},
   # A map's encounter tables, or the shared tables (core.encounters).
   "capsule.encounters/1": {"schema": "capsule.encounters/1", "tables": []},
   # A game's reference/project.json (core.project).
   "capsule.project/1": {"schema": "capsule.project/1", "name": "untitled",
                         "rom": {"title": "UNTITLED", "code": "CXXX", "maker": "00"}, "sources": []},
   # A game's code page (core.codepage; the code page panel edits one with undo), as the engine's default
   # page starts: no codes yet.
   "capsule.codepage/1": {"schema": "capsule.codepage/1", "id": "en", "name": "untitled", "ranges": [], "map": {},
                          "aliases": {}},
   # [S2] A text table (engine I4, tools/asset_compiler.py TEXT_TABLE_SCHEMA; core.text_tables) and a proportional
   # font (tools/font_compiler.py PROPORTIONAL_SCHEMA; core.fonts).
   "capsule.texts/1": {"schema": "capsule.texts/1", "language": "en", "texts": {}},
   "capsule.font/2": {"schema": "capsule.font/2", "name": "untitled", "cell": [8, 16], "line_height": 16,
                      "letter_spacing": 0, "glyphs": {}},
   # [S6] A screen plan (engine UC, D-33; the studio's own file: core.screen_plans, exported as C++); its frame
   # steps and transitions default to the engine's (screen_plans.empty() writes them out).
   "capsule.screen-plan/1": {"schema": "capsule.screen-plan/1", "name": "untitled", "assets": "../assets.json",
                             "mode": 0, "layers": [], "palettes": [], "windows": [], "sheets": [], "sprites": []},
}
## Undo steps kept.
HISTORY_LIMIT = 200
## Index of a step's label in an undo / redo entry (label, snapshot, group).
STEP_LABEL = 0
## Index of a step's manifest snapshot in an undo / redo entry.
STEP_DATA = 1
## Index of a step's EditGroup (or None) in an undo / redo entry.
STEP_GROUP = 2


class DocumentError(Exception):
   """!An edit was refused (unknown asset, duplicate key, ...)."""
   pass


class EditGroup:
   """!One undo step across Documents (see group()): the Documents whose edit() blocks made a step while it
   was open, and what to do after it is undone or redone (e.g. forget a file the step created)."""

   def __init__(self, label: str) -> None:
      """!Creates an empty group.
      @param label  what the step is called
      """
      ## What the step is called.
      self.label = label
      ## Documents with a step in this group, in the order of their first one.
      self.members: list[Document] = []
      ## Steps made in it: (Document, its undo entry), in order (rollback() reverts them).
      self.made: list[tuple[Document, tuple]] = []
      ## Callbacks after the group is undone.
      self.undone: list[Callable[[], None]] = []
      ## Callbacks after the group is redone.
      self.redone: list[Callable[[], None]] = []
      ## Callbacks after a part of the group is rolled back: (len(made) when registered, callback).
      self.rolled_back: list[tuple[int, Callable[[], None]]] = []
      ## Each member's unsaved state before its first step in the group (rollback() puts it back).
      self.was_dirty: list[tuple[Document, bool]] = []

   def on_undo(self, callback: Callable[[], None]) -> None:
      """!Calls @p callback() each time the group is undone (after the Documents changed, before listeners hear).
      @param callback  function without arguments
      @return None
      """
      self.undone.append(callback)

   def on_redo(self, callback: Callable[[], None]) -> None:
      """!Calls @p callback() each time the group is redone.
      @param callback  function without arguments
      @return None
      """
      self.redone.append(callback)

   def on_rollback(self, callback: Callable[[], None]) -> None:
      """!Calls @p callback() once if the steps made so far are rolled back (group() reverts the part of the group
      made inside a block that raised): e.g. a project forgets a file the reverted step listed.
      @param callback  function without arguments
      @return None
      """
      self.rolled_back.append((len(self.made), callback))

   def record(self, doc: Document, entry: tuple) -> None:
      """!Notes a step one of the Documents made inside the group.
      @param doc    the Document
      @param entry  its new undo entry
      @return None
      """
      if doc not in self.members:
         self.members.append(doc)
      if not any(d is doc for d, _dirty in self.was_dirty):
         self.was_dirty.append((doc, doc.dirty))
      self.made.append((doc, entry))

   def commit(self) -> None:
      """!Settles the history of every Document with a step in the group (Document._settle(): its redo history
      goes, the history limit trims), once the outermost group() block ends without an error.
      @return None
      """
      settled: list[Document] = []
      for doc, _entry in self.made:
         if not any(d is doc for d in settled):
            settled.append(doc)
            doc._settle()
      self.was_dirty = []

   def rollback(self, mark: int = 0) -> None:
      """!Reverts the steps made since @p mark (newest first), as if they had not happened (no redo step).
      @param mark  len(made) when the part to revert began
      @return None
      """
      reverted = []
      while len(self.made) > mark:
         doc, entry = self.made.pop()
         stack = doc._undo
         if stack and stack[-1] is entry:
            stack.pop()
            doc.data = entry[STEP_DATA]
            if doc not in reverted:
               reverted.append(doc)
      self.members = [d for d in self.members if any(d is m for m, _e in self.made)]
      # A Document left without a step in the group is unsaved again only if it was before its first one.
      for doc in reverted:
         if not any(doc is m for m in self.members):
            doc.dirty = next(dirty for d, dirty in self.was_dirty if d is doc)
            self.was_dirty = [(d, dirty) for d, dirty in self.was_dirty if d is not doc]
      # Callbacks registered after the mark belong to the reverted part (newest first).
      hooks = [cb for at, cb in self.rolled_back if at > mark]
      self.rolled_back = [(at, cb) for at, cb in self.rolled_back if at <= mark]
      for cb in reversed(hooks):
         cb()
      for doc in reverted:
         doc._notify()

   def _holds(self, stack: list[tuple]) -> bool:
      """!Whether an undo or redo stack holds a step of this group.
      @param stack  a Document's _undo or _redo
      @return True when it does
      """
      return any(entry[STEP_GROUP] is self for entry in stack)

   def _step(self, forward: bool) -> bool:
      """!Undoes (or redoes) the group in every member, in lock step: a member whose newest step in that direction
      is another one first undoes (redoes) that one, whole, until the group's is on top.
      @param forward  True to redo
      @return True when a Document changed
      """
      for doc in list(self.members):
         source = doc._redo if forward else doc._undo
         # Newer steps of this member alone (or of other groups) first: the steps are ordered in time, so each one
         # undone here is newer than this group's and the walk ends.
         while source and source[-1][STEP_GROUP] is not self and self._holds(source):
            if not (doc.redo() if forward else doc.undo()):
               break
      changed = []
      members = self.members if forward else list(reversed(self.members))
      for doc in members:
         source, target = (doc._redo, doc._undo) if forward else (doc._undo, doc._redo)
         # A member may hold several steps of the group (one per edit() block): all go.
         while source and source[-1][STEP_GROUP] is self:
            label, snap, _group = source.pop()
            target.append((label, doc.data, self))
            doc.data = snap
            if doc not in changed:
               changed.append(doc)
      if not changed:
         return False
      for cb in list(self.redone if forward else self.undone):
         cb()
      for doc in changed:
         doc.dirty = True
         doc._notify()
      return True

   def undo(self) -> bool:
      """!Undoes the group's steps.
      @return True when something was undone
      """
      return self._step(False)

   def redo(self) -> bool:
      """!Redoes the group's steps.
      @return True when something was redone
      """
      return self._step(True)


## The groups open now, outermost first (an inner group() joins the outermost one).
_OPEN: list[EditGroup] = []


def current_group() -> EditGroup | None:
   """!The group edits join now.
   @return the open EditGroup, or None outside group()
   """
   return _OPEN[0] if _OPEN else None


@contextmanager
def group(label: str) -> Iterator[EditGroup]:
   """!Makes the steps every Document's edit() blocks make inside it one undo step (see EditGroup). A group
   opened inside another one joins it. If the block raises, the steps made inside it are reverted.
   @param label  what the step is called
   @return a context manager giving the EditGroup
   """
   outer = current_group()
   g = outer if outer is not None else EditGroup(label)
   mark = len(g.made)
   if outer is None:
      _OPEN.append(g)
   try:
      yield g
   except BaseException:
      g.rollback(mark)
      raise
   else:
      if outer is None:
         g.commit()   # the steps stand: their Documents' histories settle now (C4)
   finally:
      if outer is None:
         _OPEN.remove(g)


def _drop_through(stack_name: str, groups: list[EditGroup]) -> None:
   """!Drops groups from their members' undo (or redo) stacks, each whole, with every step below the group's in
   those stacks (older undo steps, newer redo steps: they would bring back a part of it), and so on for the groups
   of the steps dropped with them.
   @param stack_name  "_undo" or "_redo"
   @param groups      the groups to drop
   @return None
   """
   pending = list(groups)
   done: list[EditGroup] = []
   while pending:
      g = pending.pop()
      if any(g is d for d in done):
         continue
      done.append(g)
      for member in g.members:
         stack = getattr(member, stack_name)
         last = max((i for i, entry in enumerate(stack) if entry[STEP_GROUP] is g), default=None)
         if last is None:
            continue
         dropped = stack[:last + 1]
         del stack[:last + 1]
         pending += [entry[STEP_GROUP] for entry in dropped if entry[STEP_GROUP] is not None]


def unsaved_group_files(doc: Document) -> list[Document]:
   """!The Documents to save with @p doc so no grouped step is saved in part: @p doc, then every unsaved member of
   a group in its undo or redo history, and theirs in turn (a Document saved already is left out, and so are its
   groups).
   @param doc  the Document to save
   @return Documents, @p doc first
   """
   out = [doc]
   i = 0
   while i < len(out):
      current = out[i]
      i += 1
      for entry in current._undo + current._redo:
         g = entry[STEP_GROUP]
         for member in g.members if g is not None else []:
            if member.dirty and not any(member is d for d in out):
               out.append(member)
   return out


class AssetReport:
   """!Result of compiling one asset with the engine's compiler."""

   def __init__(self, key: str | None, error: str | None = None, compiled: JsonDict | None = None) -> None:
      """!Creates a report.
      @param key       asset key
      @param error     message, or None
      @param compiled  compiler output, or None
      """
      ## Asset key.
      self.key = key
      ## Compiler message, or None when the asset compiles.
      self.error = error
      ## Compiler output for a sprite (tiles, palette, tiles_total, ...), or None.
      self.compiled = compiled

   @property
   def ok(self) -> bool:
      """!True when the asset compiles."""
      return self.error is None


class Document:
   """!One manifest file and its editing state."""

   def __init__(self, data: JsonDict | None = None, path: str | Path | None = None, schema: str = SCHEMA) -> None:
      """!Wraps manifest data.
      @param data    parsed manifest, or None for a new empty one
      @param path    file it was loaded from, or None
      @param schema  the schema this document must have (one of EMPTY)
      """
      if schema not in EMPTY:
         raise DocumentError(f"unknown schema {schema!r}")
      ## Schema of the manifest.
      self.schema = schema
      ## The manifest JSON (edit only inside edit()).
      self.data = data if data is not None else copy.deepcopy(EMPTY[schema])
      ## File path, or None until first saved.
      self.path = Path(path).resolve() if path else None
      ## Imported images not yet written: manifest path -> (w, h, RGBA).
      self.pending = {}
      ## Changes since the last save.
      self.dirty = False
      ## Increments on every change; views compare it to know when to refresh.
      self.revision = 0
      ## Undo stack of (label, manifest snapshot, EditGroup or None).
      self._undo = []
      ## Redo stack of (label, manifest snapshot, EditGroup or None).
      self._redo = []
      ## Whether the outermost edit() block opens a group() (edits of other Documents inside it join its step).
      self.group_edits = False
      ## Partner Documents: each edit() block also opens an edit of each one (see the module's notes).
      self.partners: list[Document] = []
      ## How many of this Document's edit() blocks are open (an inner one is part of the outermost one's step).
      self._depth = 0
      ## Change callbacks.
      self._listeners = []
      ## Images read from disk: path -> (mtime, image).
      self._disk_cache = {}
      ## [S2] The file's own json layout save() keeps (manifest_io.detect()), or None for the compact layout.
      self.layout: manifest_io.Layout = None
      ## [S2] The game's code page (text_encoder.CodePage) its font assets are checked with, or None (the engine's).
      self.codepage = None
      if self.data.get("schema") != schema:
         raise DocumentError(f"schema is {self.data.get('schema')!r}, expected {schema!r}")
      if schema == SCHEMA:
         self.data.setdefault("assets", [])

   # -- files -------------------------------------------------------------

   @classmethod
   def open(cls, path: str | Path, schema: str = SCHEMA, keep_layout: bool = False) -> Document:
      """!Loads a manifest file.
      @param path         file path
      @param schema       the schema it must have
      @param keep_layout  [S2] save in the file's own json layout when it has one (manifest_io.detect())
      @return the Document
      """
      if not keep_layout:
         return cls(manifest_io.load(path), path, schema)
      text = Path(path).read_text(encoding="utf-8")
      data = json.loads(text)
      doc = cls(data, path, schema)
      doc.layout = manifest_io.detect(text, data)
      return doc

   @property
   def base_dir(self) -> Path | None:
      """!Directory image paths are relative to, or None while unsaved."""
      return self.path.parent if self.path else None

   def save(self, path: str | Path | None = None) -> None:
      """!Writes the manifest and the imported images it refers to.
      @param path  new file path ("save as"), or None for the current one
      @return None
      """
      if path is not None:
         self.path = Path(path).resolve()
      if self.path is None:
         raise DocumentError("no file name; pass a path")
      used = set(self.image_paths())
      for rel, (w, h, px) in list(self.pending.items()):
         if rel in used:
            out = self.path.parent / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            engine.bitmap().write_png(out, w, h, px)
      self.pending.clear()
      self._disk_cache.clear()
      manifest_io.save(self.path, self.data, self.layout)
      self.dirty = False
      self._notify()

   # -- change tracking -----------------------------------------------------

   def subscribe(self, callback: Callable[[], None]) -> None:
      """!Calls @p callback() after every change, undo and redo.
      @param callback  function without arguments
      @return None
      """
      self._listeners.append(callback)

   def unsubscribe(self, callback: Callable[[], None]) -> None:
      """!Removes a subscribe() callback.
      @param callback  the function
      @return None
      """
      if callback in self._listeners:
         self._listeners.remove(callback)

   def _notify(self) -> None:
      """!Tells listeners something changed.
      @return None
      """
      self.revision += 1
      for cb in list(self._listeners):
         cb()

   @contextmanager
   def edit(self, label: str) -> Iterator[JsonDict]:
      """!Groups changes into one undo step. If the block raises, the
      manifest is put back as it was. Inside group() the step joins the
      group; with group_edits set, the outermost block opens one.
      @param label  what the change is called in Undo/Redo
      """
      if self.group_edits and current_group() is None:
         with group(label), self._edit_all(label) as data:
            yield data
         return
      with self._edit_all(label) as data:
         yield data

   @contextmanager
   def _edit_all(self, label: str) -> Iterator[JsonDict]:
      """!_edit() of this Document and of each partner, nested (inside the group edit() opened, if any).
      @param label  undo label
      """
      with ExitStack() as stack:
         data = stack.enter_context(self._edit(label))
         for partner in self.partners:
            stack.enter_context(partner._edit(label))
         yield data

   @contextmanager
   def _edit(self, label: str) -> Iterator[JsonDict]:
      """!edit() without opening a group.
      @param label  undo label
      """
      before = copy.deepcopy(self.data)
      self._depth += 1
      try:
         yield self.data
      except BaseException:
         self.data = before
         raise
      finally:
         self._depth -= 1
      # An inner block: the outermost one makes the step (two steps would undo to the inner block's start).
      if self._depth or self.data == before:
         return
      g = current_group()
      entry = (label, before, g)
      self._undo.append(entry)
      if g is not None:
         # inside a group the history is settled when the outermost group() commits (EditGroup.commit()): a
         # group rolled back leaves the redo history and the trimmed steps as they were (C4)
         g.record(self, entry)
      else:
         self._settle()
      self.dirty = True
      self._notify()

   def _settle(self) -> None:
      """!After a new step (or a committed group's steps): clears the redo history and keeps the newest
      HISTORY_LIMIT steps, in the other members of the groups concerned too (see the module's notes).
      @return None
      """
      # The redo history is gone, in the other members of its groups too.
      cleared, self._redo = self._redo, []
      _drop_through("_redo", [e[STEP_GROUP] for e in cleared if e[STEP_GROUP] is not None])
      # Keeps the newest HISTORY_LIMIT steps; a group trimmed here goes from all its members, whole.
      trimmed = self._undo[:-HISTORY_LIMIT]
      del self._undo[:-HISTORY_LIMIT]
      _drop_through("_undo", [e[STEP_GROUP] for e in trimmed if e[STEP_GROUP] is not None])

   def undo_label(self) -> str | None:
      """!Label of the step undo() would revert, or None."""
      return self._undo[-1][STEP_LABEL] if self._undo else None

   def redo_label(self) -> str | None:
      """!Label of the step redo() would apply, or None."""
      return self._redo[-1][STEP_LABEL] if self._redo else None

   def undo(self) -> bool:
      """!Reverts the last edit() block (a grouped step: the whole group).
      @return True if something was undone
      """
      if not self._undo:
         return False
      g = self._undo[-1][STEP_GROUP]
      if g is not None:
         return g.undo()
      label, snap, _group = self._undo.pop()
      self._redo.append((label, self.data, None))
      self.data = snap
      self.dirty = True
      self._notify()
      return True

   def redo(self) -> bool:
      """!Re-applies the last undone edit() block (a grouped step: the whole group).
      @return True if something was redone
      """
      if not self._redo:
         return False
      g = self._redo[-1][STEP_GROUP]
      if g is not None:
         return g.redo()
      label, snap, _group = self._redo.pop()
      self._undo.append((label, self.data, None))
      self.data = snap
      self.dirty = True
      self._notify()
      return True

   # -- assets ----------------------------------------------------------------

   def assets(self, kind: str | None = None) -> list[JsonDict]:
      """!Assets in manifest order.
      @param kind  only this kind ("sprite", "text", ...), or None for all
      @return list of asset objects (live; change them only inside edit())
      """
      return [a for a in self.data.get("assets", []) if kind is None or a.get("kind") == kind]

   def find(self, key: str) -> JsonDict | None:
      """!An asset by key (exact text).
      @param key  e.g. "sprite:HERO"
      @return the asset object, or None
      """
      for a in self.data.get("assets", []):
         if a.get("key") == key:
            return a
      return None

   def get(self, key: str) -> JsonDict:
      """!An asset by key, which must exist.
      @param key  asset key
      @return the asset object
      @throws DocumentError when there is none
      """
      a = self.find(key)
      if a is None:
         raise DocumentError(f"no asset {key!r}")
      return a

   def hash_of(self, key: str) -> int:
      """!Asset Key v1 of a key, as the engine computes it.
      @param key  asset key
      @return 32-bit hash
      """
      return engine.tool("sequence_compiler").asset_key(key)

   def check_new_key(self, key: str, ignore: JsonDict | None = None) -> None:
      """!Refuses keys that are malformed or collide (after the engine's
      canonicalisation) with another asset.
      @param key     proposed key
      @param ignore  asset object to leave out of the check (when renaming)
      @throws DocumentError when the key cannot be used
      @return None
      """
      sc = engine.tool("sequence_compiler")
      try:
         h = sc.asset_key(key)
      except sc.ManifestError as e:
         raise DocumentError(str(e)) from None
      for a in self.data.get("assets", []):
         if a is ignore:
            continue
         try:
            if sc.asset_key(a.get("key")) == h:
               raise DocumentError(f"{key!r} is the same key as existing {a.get('key')!r}")
         except sc.ManifestError:
            continue

   def add_asset(self, asset: JsonDict, index: int | None = None) -> JsonDict:
      """!Adds an asset (call inside edit()).
      @param asset  asset object with a new key
      @param index  position, or None for the end
      @return the asset
      """
      self.check_new_key(asset.get("key"))
      if index is None:
         self.data["assets"].append(asset)
      else:
         self.data["assets"].insert(index, asset)
      return asset

   def remove_asset(self, key: str) -> None:
      """!Removes an asset (call inside edit()).
      @param key  asset key
      @return None
      """
      a = self.get(key)
      self.data["assets"].remove(a)

   def rename_asset(self, old: str, new: str) -> None:
      """!Changes an asset's key and every list item naming it (call inside edit()).
      @param old  current key
      @param new  new key (same namespace recommended)
      @return None
      """
      a = self.get(old)
      self.check_new_key(new, ignore=a)
      a["key"] = new
      for lst in self.assets("list"):
         lst["items"] = [new if item == old else item for item in lst.get("items", [])]

   # -- images ------------------------------------------------------------------

   def image_paths(self) -> list[str]:
      """!Every image path the manifest refers to (sprite frames, tileset sheets).
      @return list of manifest paths, in order, without repeats
      """
      out = []
      sources = [f for a in self.assets("sprite") for f in a.get("frames", [])] if self.schema == SCHEMA else []
      if self.schema == SCHEMA:   # [S3] DS1: a direction grid's sheet and a door's sheet
         sources += [a.get("grid") for a in self.assets("sprite")] + [a.get("sheet") for a in self.assets("door")]
         sources += [f for a in self.assets("sprite") if isinstance(a.get("grid"), list)
                     for row in a["grid"] if isinstance(row, list) for f in row]
      if self.schema == "capsule.tileset/2":
         sources = self.data.get("sheets", [])
      for f in sources:
         p = f.get("image") if isinstance(f, dict) else None
         if isinstance(p, str) and p not in out:
            out.append(p)
      return out

   def image(self, rel: str) -> RgbaImage | None:
      """!An image frame: the unsaved import, or the file.
      @param rel  manifest path
      @return (w, h, RGBA), or None when it can't be read
      """
      if rel in self.pending:
         return self.pending[rel]
      if self.base_dir is None:
         return None
      full = self.base_dir / rel
      try:
         mtime = full.stat().st_mtime_ns
      except OSError:
         return None
      # A cached image is reused while the file's modification time is unchanged.
      hit = self._disk_cache.get(rel)
      if hit and hit[0] == mtime:
         return hit[1]
      bm = engine.bitmap()
      try:
         img = bm.read_png(full)
      except bm.BitmapError:
         return None
      self._disk_cache[rel] = (mtime, img)
      return img

   def add_image(self, rel: str, image: RgbaImage) -> None:
      """!Holds an imported image under a manifest path until save().
      @param rel    manifest path (see unique_image_path())
      @param image  (w, h, RGBA)
      @return None
      """
      self.pending[rel] = image

   def unique_image_path(self, folder: str, stem: str) -> str:
      """!A manifest path for a new image that clashes with nothing in use,
      pending or on disk.
      @param folder  folder below the manifest, '/'-separated
      @param stem    file name without extension
      @return "folder/stem.png", with a number added when needed
      """
      safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem.lower()).strip("_") or "frame"
      n = 0
      while True:
         name = f"{folder}/{safe}.png" if n == 0 else f"{folder}/{safe}_{n}.png"
         taken = name in self.pending or name in self.image_paths()
         if not taken and self.base_dir is not None:
            taken = (self.base_dir / name).exists()
         if not taken:
            return name
         n += 1

   # -- validation ----------------------------------------------------------------

   def compile_asset(self, asset: JsonDict) -> AssetReport:
      """!Compiles one asset with the engine's compiler.
      @param asset  asset object
      @return AssetReport
      """
      ac = engine.asset_compiler()
      if asset.get("kind") == "text_box":
         return self._compile_text_box(asset)
      single = {"schema": SCHEMA, "palettes": self.data.get("palettes", {}), "assets": [asset]}
      try:
         page = {"codepage": self.codepage} if self.codepage is not None else {}   # [S2] font assets
         _, _, sprites, _, _ = ac.compile_manifest(single, self.base_dir, None, self.pending, **page)
      except (ac.ManifestError, KeyError, TypeError, ValueError) as e:
         msg = str(e)
         # Drops the compiler's "asset 0 (key):" prefix: the report already names the asset.
         if msg.startswith("asset 0 ("):
            msg = msg[msg.index(")") + 1:].lstrip(" :")
         return AssetReport(asset.get("key"), msg or "invalid")
      # [S3] DS1: a door's compiled record is in compile_manifest.doors
      doors = getattr(ac.compile_manifest, "doors", [])
      # [S6] UC (D-33): a tiles / tilemap / palette asset's record is in compile_manifest.screen by kind
      screen = getattr(ac.compile_manifest, "screen", {}).get(asset.get("kind"), [])
      compiled = sprites[0] if sprites else doors[0] if doors else screen[0] if screen else None
      if compiled is not None and sprites:   # the build checks this with a static_assert; say it here first
         limit = engine.sprite_tiles_per_slot()
         if compiled["tiles_total"] > limit:
            return AssetReport(asset.get("key"), f"frames use {compiled['tiles_total']} tiles; a sprite slot "
                                                 f"holds {limit} (fewer frames, or a smaller size)", compiled)
      return AssetReport(asset.get("key"), None, compiled)

   def _compile_text_box(self, asset: JsonDict) -> AssetReport:
      """!S4 (engine C10): a text box style compiled by the engine (core.text_boxes.compile_style()); its fonts must
      be font assets the manifest reaches (the engine checks them with the whole table).
      @param asset  the text_box asset
      @return AssetReport (compiled: compile_text_box()'s record)
      """
      from . import text_boxes
      try:
         compiled = text_boxes.compile_style(asset, self.base_dir)   # S5: N3's images are relative to the folder
      except DocumentError as e:
         return AssetReport(asset.get("key"), str(e))
      have = text_boxes.font_keys(self)
      named = [asset.get("font")] + list(text_boxes.control_fonts(asset).values())
      missing = [str(k) for k in named if k not in have]
      if missing:
         return AssetReport(asset.get("key"), f"names {', '.join(missing)}: no font asset of this manifest", compiled)
      return AssetReport(asset.get("key"), None, compiled)

   def validate(self) -> tuple[list[str], dict[str | None, AssetReport]]:
      """!Compiles every asset and checks the manifest as a whole.
      @return (list of manifest-level errors, dict key -> AssetReport)
      """
      reports = {a.get("key"): self.compile_asset(a) for a in self.data.get("assets", [])}
      problems = []
      seen = {}
      for a in self.data.get("assets", []):
         try:
            h = self.hash_of(a.get("key"))
         except Exception:
            continue
         if h in seen:
            problems.append(f"{a.get('key')!r} has the same key as {seen[h]!r}")
         seen[h] = a.get("key")
      return problems, reports
