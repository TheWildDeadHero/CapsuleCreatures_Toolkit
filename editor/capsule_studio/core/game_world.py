"""!Adding a world to a game: the project manifest's "maps" key (core.project.GAME_FILES), set from a world file
the user picks.

  - A world inside the game folder is named as it is (a world the game names already is left alone).
  - A world outside it (another game's, or the engine's map sandbox that the Studio download ships) is imported
    first (core.importer: its maps with the tilesets, sheet images and behaviors they need) into the game's own
    world: the one the game names, or a new data/world.json (data/world_2.json, ... when that name holds
    something else).
  - The game's battle data follows: a world that names no battle data, or battle data outside the game folder
    (an imported world names its source's), is pointed at the battle file the game names, so encounters are
    checked against the game's own species.
  - create() makes a new world for a game that has none (data/world.json, or the first free data/world_N.json),
    pointed at the game's battle data, and names it: empty (the Studio's World page offers it while the game has
    no world), or, for a new game (core.templates.new_game(), D-40 RN), with core.starter_world's tileset and
    map, so the game builds from the start.

Nothing is written until everything has worked: run() and create() save the world files with Project.save_all()
(the world file last), then the project manifest with Document.save() (core.manifest_io), never hand-made JSON
text. Nothing here depends on a user interface; the Studio's "Add world to game..." and "Create a new world",
`capsule-studio project add-world` and core.templates.new_game() use it.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, NamedTuple

from . import encounters, engine, importer, project, starter_world
from .document import Document, DocumentError
from .world import WORLD_SCHEMA, Project

## The project manifest key that names the game's world.
MAPS_KEY = "maps"
## The project manifest key that names the game's battle data.
BATTLE_KEY = "battle"
## Where a game's own world is made when it has none, relative to the game folder (beside the templates' data/).
NEW_WORLD_FILE = "data/world.json"
## The engine's map sandbox world, as path parts below the engine root (the sample world the downloads ship).
SANDBOX_WORLD = ("apps", "sandbox_map", "data", "world.json")
## Number the first other name of a new world file gets (world_2.json; the unnumbered name counts as the first).
FIRST_COPY_NUMBER = 2
## Highest number tried for a new world file name before giving up.
LAST_COPY_NUMBER = 99
## World id of a new world when the game has no name.
DEFAULT_WORLD_ID = "world"

## What adding a world does: nothing (the game names it already), name it, or import it first.
Action = Literal["linked", "link", "import"]
## plan(): the game names this world already.
LINKED: Action = "linked"
## plan(): the world is in the game folder; only the project manifest changes.
LINK: Action = "link"
## plan(): the world is outside the game folder; its maps are imported into the game's own world first.
IMPORT: Action = "import"


class AddWorldPlan(NamedTuple):
   """!What adding a world to a game would do (plan())."""

   ## LINKED, LINK or IMPORT.
   action: Action
   ## The world file chosen (resolved).
   source: Path
   ## The world file the game will name (resolved): the source itself, or the world the import goes into.
   target: Path
   ## The project manifest's new "maps" value (relative to the game folder).
   rel: str
   ## The "maps" value it replaces, or None (the game names no world, or the same one).
   replaces: str | None
   ## Whether the import makes a new world file (target does not exist yet).
   creates: bool


def sandbox_world() -> Path | None:
   """!The engine's map sandbox world (in a checkout, or the engine copy a Studio download ships).
   @return its world.json, or None when no engine is found or it has no map sandbox
   """
   try:
      path = engine.root().joinpath(*SANDBOX_WORLD)
   except engine.EngineNotFound:
      return None
   return path if path.is_file() else None


def _opens_as_world(path: Path) -> bool:
   """!Whether a file is a world manifest.
   @param path  file
   @return True when Project.open() reads it
   """
   try:
      Project.open(path)
   except (DocumentError, OSError, ValueError):
      return False
   return True


def _new_world_file(game: Path) -> Path:
   """!The file a game's new world goes into: data/world.json, or the first free data/world_N.json when that
   name holds something that is not a world.
   @param game  the game folder (resolved)
   @return resolved Path (a world.json that exists is a world: the import goes into it)
   @throws DocumentError when every name is taken
   """
   first = game / NEW_WORLD_FILE
   if not first.exists() or _opens_as_world(first):
      return first
   for number in range(FIRST_COPY_NUMBER, LAST_COPY_NUMBER + 1):
      candidate = first.with_name(f"{first.stem}_{number}{first.suffix}")
      if not candidate.exists():
         return candidate
   raise DocumentError(f"no free name for a new world beside {first}")


def plan(doc: Document, source: str | Path) -> AddWorldPlan:
   """!What adding a world to the game would do.
   @param doc     the game's project Document (opened from its reference/project.json)
   @param source  the world file to add
   @return AddWorldPlan
   @throws DocumentError when @p source is not a world, or the manifest's "maps" is not a relative path
   """
   game = project.game_folder(doc).resolve()
   src = Path(source).expanduser().resolve()
   try:
      Project.open(src)
   except (DocumentError, OSError, ValueError) as e:
      raise DocumentError(f"{src}: not a world file ({e})") from e
   current = project.game_files(doc).get(MAPS_KEY)
   current_rel = doc.data.get(MAPS_KEY)
   if src.is_relative_to(game):
      rel = src.relative_to(game).as_posix()
      if current == src:
         return AddWorldPlan(LINKED, src, src, rel, None, False)
      return AddWorldPlan(LINK, src, src, rel, current_rel, False)
   # Outside the game: the import goes into the world the game names (made when it is missing), else a new one.
   if current is not None and current.is_relative_to(game) and (not current.exists() or _opens_as_world(current)):
      target = current
   else:
      target = _new_world_file(game)
   rel = target.relative_to(game).as_posix()
   replaces = current_rel if current_rel is not None and current != target else None
   return AddWorldPlan(IMPORT, src, target, rel, replaces, not target.exists())


def target_world(doc: Document, add: AddWorldPlan) -> Project:
   """!The world a plan's import goes into: opened, or new and unsaved (Project.save_all() writes it).
   @param doc  the game's project Document
   @param add  AddWorldPlan
   @return Project
   """
   if not add.creates:
      return Project.open(add.target)
   world = Document(path=add.target, schema=WORLD_SCHEMA)
   world.data["id"] = doc.data.get("name") or project.game_folder(doc).name or DEFAULT_WORLD_ID
   world.dirty = True
   return Project(world)


def follow_battle(doc: Document, world: Project) -> str | None:
   """!Points a world at the game's battle data when it names none, or names battle data outside the game folder
   (one undo step on the world; unsaved).
   @param doc    the game's project Document
   @param world  the world the game will name
   @return a report line, or None when nothing changed (the game names no battle file, or the world's is the game's)
   """
   battle = project.game_files(doc).get(BATTLE_KEY)
   if battle is None or not battle.is_file():
      return None
   game = project.game_folder(doc).resolve()
   current = encounters.battle_path(world)
   if current is not None and current.is_relative_to(game):
      return None
   rel = Path(os.path.relpath(battle, world.base)).as_posix()
   with world.world.edit("Battle data"):
      encounters.set_battle(world.world, rel)
   return f"battle data: {rel} (the game's)"


def link(doc: Document, rel: str) -> None:
   """!Names the game's world in the project manifest (one undo step; unsaved). A new "maps" key goes before the
   other data file keys, in core.project.GAME_FILES order.
   @param doc  the game's project Document
   @param rel  world file relative to the game folder
   @return None
   """
   if doc.data.get(MAPS_KEY) == rel:
      return
   file_keys = [key for key, _what in project.GAME_FILES]
   with doc.edit("Add world to game") as data:
      if MAPS_KEY in data:
         data[MAPS_KEY] = rel
         return
      # The manifest is rebuilt in place, so the new key lands before the first data file key it has.
      items = list(data.items())
      at = next((i for i, (key, _value) in enumerate(items) if key in file_keys), len(items))
      items.insert(at, (MAPS_KEY, rel))
      data.clear()
      data.update(items)


def _free_world_file(game: Path) -> Path:
   """!The first name a new, empty world can take in a game without replacing a file: data/world.json, else
   data/world_2.json, data/world_3.json, ...
   @param game  the game folder (resolved)
   @return resolved Path that does not exist yet
   @throws DocumentError when every name is taken
   """
   first = game / NEW_WORLD_FILE
   if not first.exists():
      return first
   for number in range(FIRST_COPY_NUMBER, LAST_COPY_NUMBER + 1):
      candidate = first.with_name(f"{first.stem}_{number}{first.suffix}")
      if not candidate.exists():
         return candidate
   raise DocumentError(f"no free name for a new world beside {first}")


def create(doc: Document, starter: bool = False) -> list[str]:
   """!Makes a new world for a game that has none: data/world.json (or the first free data/world_N.json; the file
   the manifest names, when it names one that is missing), pointed at the game's battle data, saved with
   Project.save_all(); then names it in the project manifest and saves that.
   Empty (the Studio's "Create a new world" for a game without one): no tileset and no map yet, so the game
   builds once it has a map. With @p starter (every new game, core.templates.new_game()): core.starter_world's
   tileset and map and a start position on it, so the game builds at once.
   @param doc      the game's project Document (opened from its file; saved here)
   @param starter  True to add the starter tileset and map
   @return report lines (the last one names the world: "maps: data/world.json")
   @throws DocumentError when the game names a world that exists already, or no file name is free
   """
   game = project.game_folder(doc).resolve()
   current = project.game_files(doc).get(MAPS_KEY)
   if current is not None and current.exists():
      raise DocumentError(f"the game has a world already ({doc.data.get(MAPS_KEY)})")
   target = current.resolve() if current is not None and current.resolve().is_relative_to(game) else \
      _free_world_file(game)
   rel = target.relative_to(game).as_posix()
   world_doc = Document(path=target, schema=WORLD_SCHEMA)
   world_doc.data["id"] = doc.data.get("name") or game.name or DEFAULT_WORLD_ID
   world_doc.dirty = True
   world = Project(world_doc)
   if starter:
      lines = [f"new world {rel}"] + starter_world.fill(world)
   else:
      lines = [f"new empty world {rel} (no tileset or map yet)"]
   note = follow_battle(doc, world)
   if note is not None:
      lines.append(note)
   target.parent.mkdir(parents=True, exist_ok=True)
   world.save_all()
   link(doc, rel)
   doc.save()
   lines.append(f"{MAPS_KEY}: {rel}")
   return lines


def run(doc: Document, source: str | Path, maps: Sequence[str] | None = None,
        tilesets: Sequence[str] = ()) -> list[str]:
   """!Adds a world to the game: imports it first when it is outside the game folder, points it at the game's
   battle data, saves the world files, then names it in the project manifest and saves that.
   @param doc       the game's project Document (opened from its file; saved here)
   @param source    the world file to add
   @param maps      the maps to import from a world outside the game, or None for all of them
   @param tilesets  tilesets to import besides the ones the maps draw from
   @return report lines
   @throws DocumentError (importer.ImportRefused) when the import cannot be done; nothing is written then
   """
   add = plan(doc, source)
   if add.action == LINKED:
      return [f"the game names this world already ({add.rel})"]
   lines = []
   world = target_world(doc, add)
   if add.action == IMPORT:
      origin = Project.open(add.source)
      chosen = list(origin.map_names()) if maps is None else list(maps)
      if not chosen and not tilesets:
         raise DocumentError(f"{add.source}: nothing to import (the world has no maps)")
      lines += importer.run(world, origin, chosen, tilesets)
   note = follow_battle(doc, world)
   if note is not None:
      lines.append(note)
   world.save_all()
   link(doc, add.rel)
   doc.save()
   lines.append(f"{MAPS_KEY}: {add.rel}" + (f" (was {add.replaces})" if add.replaces else ""))
   return lines
