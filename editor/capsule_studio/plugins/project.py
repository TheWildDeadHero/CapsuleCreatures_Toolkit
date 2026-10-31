"""!Finding a world's project manifest and the plugins it lists (D-10 §3).

A game is laid out as the engine's capsule_game() expects: a folder with
reference/project.json (capsule.project/1), whose paths ("maps",
"plugins", ...) are relative to that folder. Only the plugins a project
lists load: "plugins": ["plugins/trainer_moods", ...].
"""
from __future__ import annotations

import json
from pathlib import Path

## Project manifest schema.
SCHEMA = "capsule.project/1"
## Folders above a world searched for the game folder.
SEARCH_DEPTH = 3


def find_project(world_path: str | Path) -> tuple[Path, Path] | tuple[None, None]:
   """!The project manifest whose "maps" is this world.
   @param world_path  world.json
   @return (project.json Path, game folder Path), or (None, None)
   """
   world = Path(world_path).resolve()
   folder = world.parent
   for _ in range(SEARCH_DEPTH + 1):
      candidate = folder / "reference" / "project.json"
      if candidate.is_file():
         try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
         except (OSError, ValueError):
            data = None
         if isinstance(data, dict) and data.get("schema") == SCHEMA and isinstance(data.get("maps"), str) \
                 and (folder / data["maps"]).resolve() == world:
            return candidate, folder
      if folder.parent == folder:
         break
      folder = folder.parent
   return None, None


def plugin_folders(project_path: str | Path, game_folder: str | Path) -> list[Path]:
   """!The plugin folders a project lists.
   @param project_path  project.json
   @param game_folder   its game folder (paths are relative to it)
   @return list of resolved Paths
   @throws ValueError when "plugins" is malformed
   """
   data = json.loads(Path(project_path).read_text(encoding="utf-8"))
   raw = data.get("plugins", [])
   if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
      raise ValueError(f"{project_path}: plugins lists plugin folders (relative to {game_folder})")
   return [(Path(game_folder) / p).resolve() for p in raw]
