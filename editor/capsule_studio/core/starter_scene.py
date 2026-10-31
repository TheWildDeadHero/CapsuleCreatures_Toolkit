"""!The scene every new game starts with (D-40 RG), so a new game builds and runs at once: the player on the
world's start map (core.starter_world), walking with the D-pad, and a text box naming the game.

The files come from the toolkit's template folder `capsule_studio/starter_scene/`:
  - `game.cpp.in`: the scene's C++ source; add() writes it to the game's `src/game.cpp` with the game's name for
    `@GAME_TITLE@` (title_text(): printable ASCII that fits the text box);
  - `player.json`: the player's sprite, one capsule.assets/1 asset ("sprite:PLAYER", simple shapes); add() appends it
    to the game's asset manifest, or starts `data/assets.json` with it when the template copied none.

add() also gives the project manifest what the engine's capsule_game() needs to build the game: "sources" (the
scene) and a "rom" header (rom_title(): the game's name in GBA header letters; a generic game code and maker).
build_name() is the game's "name" as a build target name (capsule_NAME). Nothing here depends on a user
interface.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import manifest_io
from .document import DocumentError

## A parsed JSON object.
JsonDict = dict[str, Any]

## Folders between this file and the package (core -> capsule_studio).
PACKAGE_DEPTH = 1
## The toolkit's folder of scene template files.
TEMPLATE_FOLDER = Path(__file__).resolve().parents[PACKAGE_DEPTH] / "starter_scene"
## The scene's source template.
SOURCE_TEMPLATE = "game.cpp.in"
## The player's sprite (one asset record).
PLAYER_TEMPLATE = "player.json"
## Where the scene goes in the game folder (games keep their code in src/, as the engine's apps do).
SOURCE_FILE = "src/game.cpp"
## The mark in the source template that the game's title replaces.
TITLE_MARK = "@GAME_TITLE@"
## Any mark left in a written source (a template mark nothing replaced).
MARK = re.compile(r"@[A-Z_]+@")

## project.json key of the game's sources (relative to the game folder).
SOURCES_KEY = "sources"
## project.json key of the GBA ROM header.
ROM_KEY = "rom"
## project.json key of the asset manifest.
ASSETS_KEY = "assets"
## project.json key of the battle data.
BATTLE_KEY = "battle"
## The asset manifest a game without one gets.
ASSETS_FILE = "data/assets.json"
## Asset manifest schema.
ASSETS_SCHEMA = "capsule.assets/1"
## Suffix of a new asset manifest's id (after the game's build name).
ASSETS_ID_SUFFIX = "_assets"
## An asset record's key field.
ASSET_KEY = "key"
## A manifest's studio-only object (the compilers strip it).
EDITOR_KEY = "editor"

## Characters of a GBA header title (gbafix -t): 12 upper-case letters, digits and spaces.
ROM_TITLE_LENGTH = 12
## Characters a header title keeps; everything else becomes a space.
ROM_TITLE_KEEP = re.compile(r"[^A-Z0-9 ]")
## Title of a game whose name has no such letter.
DEFAULT_ROM_TITLE = "NEW GAME"
## A generic four-letter game code: every new game's, until the developer gives one.
ROM_CODE = "CNEW"
## Two-character maker code (none).
ROM_MAKER = "00"

## Cells inside the welcome box's frame (the scene's box spans the screen's 30 cells).
TITLE_CELLS = 28
## Characters the title keeps: printable ASCII (the engine's default code page), less what a C++ string literal
## escapes and the at sign (template marks are NAME between two at signs).
TITLE_DROP = re.compile(r"[^\x20-\x7e]|[\"\\@]")
## Title of a game whose name has no printable character.
DEFAULT_TITLE = "New game"
## Runs of spaces (one space each).
SPACES = re.compile(r"\s+")

## Characters a build name keeps: letters, digits and "_" (CMake target and save file names).
BUILD_NAME_DROP = re.compile(r"[^A-Za-z0-9_]+")
## Build name of a game whose name has no such character.
DEFAULT_BUILD_NAME = "game"
## Put before a build name that starts with a digit.
BUILD_NAME_PREFIX = "game_"


def build_name(name: str) -> str:
   """!A game name as the engine builds it: capsule_game() makes the target capsule_NAME, so other characters
   become "_" (runs of them one).
   @param name  the name given to New game, or the folder's
   @return letters, digits and "_" ("My Game" -> "My_Game"; "MyGame" stays)
   """
   out = BUILD_NAME_DROP.sub("_", name).strip("_")
   if not out:
      return DEFAULT_BUILD_NAME
   return BUILD_NAME_PREFIX + out if out[0].isdigit() else out


def rom_title(name: str) -> str:
   """!The GBA ROM header's title: the game's name in upper case, other characters as spaces, at most
   ROM_TITLE_LENGTH characters.
   @param name  the game's name
   @return e.g. "MY GAME" (DEFAULT_ROM_TITLE when nothing is left)
   """
   title = SPACES.sub(" ", ROM_TITLE_KEEP.sub(" ", name.upper())).strip()
   return title[:ROM_TITLE_LENGTH].rstrip() or DEFAULT_ROM_TITLE


def title_text(name: str) -> str:
   """!The game's name as the scene's text box shows it: printable ASCII without quotes or backslashes (they would
   end or escape the C++ string) or "@", spaces collapsed, cut to the box's width.
   @param name  the game's name
   @return the text (DEFAULT_TITLE when nothing is left)
   """
   text = SPACES.sub(" ", TITLE_DROP.sub(" ", name)).strip()
   return text[:TITLE_CELLS].rstrip() or DEFAULT_TITLE


def source_text(name: str) -> str:
   """!The scene's C++ source for a game.
   @param name  the game's name
   @return the template with the title in place
   @throws DocumentError when the template cannot be read or keeps a mark
   """
   path = TEMPLATE_FOLDER / SOURCE_TEMPLATE
   try:
      text = path.read_text(encoding="utf-8")
   except OSError as e:
      raise DocumentError(f"cannot read the scene template {path}: {e}") from None
   text = text.replace(TITLE_MARK, title_text(name))
   left = MARK.search(text)
   if left is not None:
      raise DocumentError(f"{path}: {left.group(0)} is not a mark the Studio fills")
   return text


def player_asset() -> JsonDict:
   """!The player's sprite record.
   @return a capsule.assets/1 asset (a fresh copy)
   @throws DocumentError when the template cannot be read
   """
   path = TEMPLATE_FOLDER / PLAYER_TEMPLATE
   try:
      data = manifest_io.load(path)
   except (OSError, ValueError) as e:
      raise DocumentError(f"cannot read the player sprite template {path}: {e}") from None
   if not isinstance(data, dict) or not isinstance(data.get(ASSET_KEY), str):
      raise DocumentError(f"{path}: not an asset record")
   return data


def _add_player(game: Path, project: JsonDict, name: str) -> Path:
   """!Puts the player's sprite in the game's asset manifest (a new data/assets.json when it names none).
   @param game     the game folder
   @param project  the project manifest's data (gets "assets" when it had none)
   @param name     the game's build name (a new manifest's id)
   @return the asset manifest written
   @throws DocumentError when the manifest has the sprite's key already or is not an asset manifest
   """
   player = player_asset()
   rel = project.get(ASSETS_KEY)
   if isinstance(rel, str) and rel:
      path = game / rel
      data = manifest_io.load(path)
      if not isinstance(data, dict) or data.get("schema") != ASSETS_SCHEMA:
         raise DocumentError(f"{path}: not an asset manifest ({ASSETS_SCHEMA})")
   else:
      path = game / ASSETS_FILE
      if path.exists():
         raise DocumentError(f"{path} exists already: a new game starts in a new folder")
      data = {"schema": ASSETS_SCHEMA, "id": name + ASSETS_ID_SUFFIX,
              EDITOR_KEY: {"notes": "The game's art. sprite:PLAYER is the player's sprite in the first scene "
                                    "(src/game.cpp): simple shapes, replace them."},
              "assets": []}
      # before the battle data, in core.project.GAME_FILES order (the world goes in front of both later)
      items = list(project.items())
      at = next((i for i, (key, _value) in enumerate(items) if key == BATTLE_KEY), len(items))
      items.insert(at, (ASSETS_KEY, ASSETS_FILE))
      project.clear()
      project.update(items)
   assets = data.setdefault("assets", [])
   if any(isinstance(a, dict) and a.get(ASSET_KEY) == player[ASSET_KEY] for a in assets):
      raise DocumentError(f"{path} has an asset {player[ASSET_KEY]!r} already")
   assets.append(player)
   path.parent.mkdir(parents=True, exist_ok=True)
   manifest_io.save(path, data)
   return path


def add(game: str | Path, project: JsonDict, name: str) -> list[Path]:
   """!Gives a new game its first scene: src/game.cpp, the player's sprite, and the project manifest's "sources"
   and "rom" (the data is changed in place; the caller saves it).
   @param game     the game folder
   @param project  the project manifest's data
   @param name     the game's name (the title shows it; the header and the build use its forms)
   @return the files written (the scene, the asset manifest)
   @throws DocumentError when the scene's file exists already or the asset manifest cannot take the sprite
   """
   folder = Path(game)
   source = folder / SOURCE_FILE
   if source.exists():
      raise DocumentError(f"{source} exists already: a new game starts in a new folder")
   text = source_text(name)
   assets = _add_player(folder, project, build_name(name))
   source.parent.mkdir(parents=True, exist_ok=True)
   source.write_text(text, encoding="utf-8", newline="\n")
   # The header and the sources go after the manifest's own keys, before the data files (as the engine's apps
   # list them); the manifest is rebuilt in place to keep that order.
   items = [(k, v) for k, v in project.items() if k not in (ROM_KEY, SOURCES_KEY)]
   at = next((i + 1 for i, (key, _value) in enumerate(items) if key == EDITOR_KEY), len(items))
   items[at:at] = [(ROM_KEY, {"title": rom_title(name), "code": ROM_CODE, "maker": ROM_MAKER}),
                   (SOURCES_KEY, [SOURCE_FILE])]
   project.clear()
   project.update(items)
   return [source, assets]
