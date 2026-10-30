"""!Sample projects (D-40 RP): the engine's sample programs, copied into a folder of the user's as a game of their
own.

A sample is an engine app whose folder holds a sample.json (capsule.sample/1) beside its reference/project.json:

    {"schema": "capsule.sample/1", "id": "sandbox_map", "name": "Map Sandbox", "description": "one line",
     "version": 1, "shared": [{"from": "../../samples/starter", "to": "data/starter"}]}

The engine builds the app where it is (its own apps, tests and release downloads), and the app may read data the
engine shares between its programs: "shared" names each such folder (a battle data template, with its
template.json) and where a copy of the sample keeps it. discover() finds the samples of the engine checkout in use
(`apps/*/sample.json`, core.engine.root()).

copy() makes the game, so the copy and the engine's app can never drift apart (there is no second copy to keep in
step):
  1. every file of the app folder, less sample.json, goes to the same relative path in the new folder;
  2. each shared folder's template files go to its "to" folder (core.templates.apply(): editor.template is
     recorded, as for a new game);
  3. every path in the copied JSON manifests that led into a shared folder now leads to its copy (the files keep
     their own layout, core.manifest_io.detect());
  4. the project manifest gets the build-safe name rules of New game (core.starter_scene: "name" is build_name(),
     the ROM header's title rom_title() and its code the generic ROM_CODE) and editor.sample {id, version};
  5. outside_paths() must find nothing: no path of the copy leads out of its folder, and its "libraries" are only
     the engine libraries capsule_game() links for any game (GAME_LIBRARIES).

A copy never goes into the engine or the Studio's own files (protected_folders()). Nothing here depends on a user
interface: the command line (cli/sample_cmds.py) and the Studio's Open a sample... (ui/sample_dialog.py) call it.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import engine, manifest_io, starter_scene, templates
from .document import DocumentError

## A parsed JSON value.
JsonValue = Any
## A parsed JSON object.
JsonDict = dict[str, Any]

## Sample manifest schema.
SCHEMA = "capsule.sample/1"
## A sample's manifest, in the app folder (not copied).
SAMPLE_FILE = "sample.json"
## The engine's folder of apps (each sample is one of them).
ENGINE_APPS = "apps"
## Keys of a sample manifest ("editor" holds notes).
KEYS = ("schema", "id", "name", "description", "version", "shared", "editor")
## Keys of a "shared" entry.
SHARED_KEYS = ("from", "to")
## A sample id: lower-case letters, digits and "_", starting with a letter (the app's folder name).
SAMPLE_ID = re.compile(r"[a-z][a-z0-9_]*")
## Lowest sample version.
FIRST_VERSION = 1

## A game's folder holding its project manifest.
REFERENCE_DIR = templates.REFERENCE_DIR
## A game's project manifest.
PROJECT_FILE = templates.PROJECT_FILE
## A manifest's studio-only object (the compilers strip it).
EDITOR_KEY = templates.EDITOR_KEY
## editor key recording the sample a copy came from: {"id", "version"}.
SAMPLE_KEY = "sample"
## project.json key of the game's build name (the copy's name rules change it).
NAME_KEY = "name"
## project.json key of the GBA ROM header.
ROM_KEY = starter_scene.ROM_KEY
## The ROM header's title key.
ROM_TITLE_KEY = "title"
## The ROM header's game code key.
ROM_CODE_KEY = "code"
## project.json key of the engine libraries a game links (capsule_game(): capsule_<library>).
LIBRARIES_KEY = "libraries"
## The engine libraries capsule_game() links for any game: the engine's CMakeLists.txt defines them for every
## platform with games, outside the engine's own test switches (apps/common: test_kit.h, battle_kit.h).
GAME_LIBRARIES = ("test_kit", "battle_kit")

## Suffix of the files whose paths copy() rewrites and outside_paths() reads.
JSON_SUFFIX = ".json"
## Suffixes of C and C++ files whose quoted include lines outside_paths() reads.
SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".h", ".hpp", ".inc")
## A quoted include line (the file named).
INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)
## Folder names that are never copied (build output, caches, version control).
SKIPPED_FOLDERS = ("build", "__pycache__", ".git")
## Longest JSON text read as a path (map rows and long texts are not paths).
PATH_MAX_CHARS = 260


@dataclass(frozen=True)
class Shared:
   """!A folder the engine shares with a sample, and where a copy keeps it."""

   ## The shared folder's battle data template (its files are what is copied).
   template: templates.Template
   ## Its folder in a copy, relative to the game folder, written with "/".
   to: str


@dataclass(frozen=True)
class Sample:
   """!One sample project: its manifest and its app folder."""

   ## Id (the app's folder name; the CLI's NAME).
   id: str
   ## Shown name.
   name: str
   ## One line on what it shows.
   description: str
   ## Version (recorded in a copy's editor.sample).
   version: int
   ## The app folder (its files are relative to it).
   folder: Path
   ## The folders the engine shares with it.
   shared: tuple[Shared, ...] = ()

   def label(self) -> str:
      """!The sample as lists show it.
      @return e.g. "Map Sandbox (sandbox_map, version 1)"
      """
      return f"{self.name} ({self.id}, version {self.version})"


# -- reading ----------------------------------------------------------------------------------------------------------

def _plain_relative(value: Any) -> bool:
   """!Whether a JSON value is a relative path as manifests write them: "/" between parts, nothing absolute.
   @param value  any JSON value
   @return True for a non-empty relative POSIX path text
   """
   if not isinstance(value, str) or not value or len(value) > PATH_MAX_CHARS:
      return False
   if "\\" in value or "\n" in value or ":" in value:
      return False
   return not PurePosixPath(value).is_absolute()


def _shared(entry: Any, folder: Path, where: str) -> Shared:
   """!Reads one "shared" entry.
   @param entry   the entry as written
   @param folder  the sample's app folder
   @param where   location for messages
   @return Shared
   @throws DocumentError when it is not one
   """
   if not isinstance(entry, dict) or sorted(entry) != sorted(SHARED_KEYS):
      raise DocumentError(f"{where}: a shared entry is {{\"from\": FOLDER, \"to\": FOLDER}}")
   source, to = entry["from"], entry["to"]
   if not _plain_relative(source):
      raise DocumentError(f"{where}: from is a relative folder written with \"/\" (got {source!r})")
   if not _plain_relative(to) or ".." in PurePosixPath(to).parts or to != PurePosixPath(to).as_posix():
      raise DocumentError(f"{where}: to is a plain relative folder inside the copy (got {to!r})")
   if (folder / to).exists():
      raise DocumentError(f"{where}: to {to!r} is taken by the sample's own files")
   template = templates.load((folder / source).resolve(), templates.ENGINE)
   return Shared(template, to)


def load(path: str | Path) -> Sample:
   """!Reads a sample.
   @param path  the app folder or its sample.json
   @return Sample
   @throws DocumentError when the manifest is not a sample, or the folder is not a game
   """
   p = Path(path)
   if p.is_dir():
      p = p / SAMPLE_FILE
   try:
      data = manifest_io.load(p)
   except (OSError, ValueError) as e:
      raise DocumentError(f"cannot read {p}: {e}") from None
   where = str(p)
   if not isinstance(data, dict) or data.get(templates.SCHEMA_KEY) != SCHEMA:
      raise DocumentError(f"{where}: not a sample ({templates.SCHEMA_KEY} {SCHEMA})")
   extra = sorted(set(data) - set(KEYS))
   if extra:
      raise DocumentError(f"{where}: unknown key(s) {', '.join(extra)} (keys: {', '.join(KEYS)})")
   folder = p.parent.resolve()
   sid = data.get("id")
   if not isinstance(sid, str) or not SAMPLE_ID.fullmatch(sid) or sid != folder.name:
      raise DocumentError(f"{where}: id is the app folder's name ({folder.name}), got {sid!r}")
   name = data.get("name")
   if not isinstance(name, str) or not name.strip():
      raise DocumentError(f"{where}: name is a text")
   description = data.get("description", "")
   if not isinstance(description, str) or "\n" in description:
      raise DocumentError(f"{where}: description is one line of text")
   version = data.get("version")
   if not isinstance(version, int) or isinstance(version, bool) or version < FIRST_VERSION:
      raise DocumentError(f"{where}: version is a whole number from {FIRST_VERSION}, got {version!r}")
   if not (folder / REFERENCE_DIR / PROJECT_FILE).is_file():
      raise DocumentError(f"{where}: the sample's folder has no {REFERENCE_DIR}/{PROJECT_FILE}")
   given = data.get("shared", [])
   if not isinstance(given, list):
      raise DocumentError(f"{where}: shared is a list of {{\"from\", \"to\"}} entries")
   shared = tuple(_shared(entry, folder, f"{where}: shared[{i}]") for i, entry in enumerate(given))
   return Sample(sid, name.strip(), description.strip(), version, folder, shared)


def discover() -> tuple[list[Sample], list[str]]:
   """!The samples of the engine checkout in use, by id.
   @return (samples, problems: unreadable manifests, or the engine not found)
   """
   try:
      apps = engine.root() / ENGINE_APPS
   except engine.EngineNotFound as e:
      return [], [str(e)]
   found: list[Sample] = []
   problems: list[str] = []
   for manifest in sorted(apps.glob(f"*/{SAMPLE_FILE}")):
      try:
         found.append(load(manifest))
      except DocumentError as e:
         problems.append(str(e))
   return found, problems


def find(name: str) -> Sample:
   """!A sample by id (or by its name, ignoring case).
   @param name  "sandbox_map", "Map Sandbox", ...
   @return Sample
   @throws DocumentError when there is none
   """
   found, problems = discover()
   for s in found:
      if s.id == name or s.name.lower() == name.lower():
         return s
   trouble = f"; {'; '.join(problems)}" if problems else ""
   raise DocumentError(f"no sample {name!r} (samples: {', '.join(s.id for s in found) or 'none'}){trouble}")


# -- where a copy may go ----------------------------------------------------------------------------------------------

def protected_folders() -> list[Path]:
   """!Folders a copy never goes into: the engine in use and the Studio's own files (its toolkit checkout; in a
   prebuilt bundle, the program's folder and its data folder).
   @return resolved Paths
   """
   out = [engine.STUDIO_ROOT.resolve()]
   try:
      out.append(engine.root())
   except engine.EngineNotFound:
      pass
   if getattr(sys, "frozen", False):
      out.append(Path(sys.executable).resolve().parent)
      bundle_data = getattr(sys, "_MEIPASS", None)
      if bundle_data:
         out.append(Path(bundle_data).resolve())
   return out


def check_destination(folder: str | Path) -> Path:
   """!The folder a copy goes into: new or empty, and outside protected_folders().
   @param folder  the new game's folder
   @return its resolved Path
   @throws DocumentError when it is refused
   """
   dest = Path(folder).expanduser().resolve()
   for guarded in protected_folders():
      if dest == guarded or guarded in dest.parents:
         raise DocumentError(f"{dest} is inside {guarded}, the engine's or the Studio's own files: copy the sample "
                             "into a folder of your own (for example in your home folder)")
   if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
      raise DocumentError(f"{dest} is not an empty folder: a sample is copied into a new folder")
   return dest


# -- copying ----------------------------------------------------------------------------------------------------------

def sample_files(sample: Sample) -> list[str]:
   """!The files of the app folder a copy gets: all of them, less sample.json and SKIPPED_FOLDERS.
   @param sample  Sample
   @return relative paths written with "/", sorted
   """
   out = []
   for path in sorted(sample.folder.rglob("*")):
      rel = path.relative_to(sample.folder)
      if not path.is_file() or any(part in SKIPPED_FOLDERS for part in rel.parts):
         continue
      if rel.as_posix() == SAMPLE_FILE:
         continue
      out.append(rel.as_posix())
   return out


def path_base(game: Path, file: Path) -> Path:
   """!The folder a manifest's paths are relative to: the game folder for its project manifest (as capsule_game()
   reads it), else the manifest's own folder.
   @param game  the game folder
   @param file  a JSON manifest in it
   @return Path
   """
   if file == game / REFERENCE_DIR / PROJECT_FILE:
      return game
   return file.parent


def _map_strings(value: JsonValue, change: Callable[[str], str | None]) -> tuple[JsonValue, int]:
   """!A JSON value with some of its texts replaced (keys stay as they are).
   @param value   the parsed JSON value
   @param change  callable(text) -> the new text, or None to keep it
   @return (the new value, how many texts changed)
   """
   if isinstance(value, dict):
      count = 0
      out = {}
      for key, item in value.items():
         out[key], n = _map_strings(item, change)
         count += n
      return out, count
   if isinstance(value, list):
      count = 0
      items = []
      for item in value:
         new, n = _map_strings(item, change)
         items.append(new)
         count += n
      return items, count
   if isinstance(value, str):
      new = change(value)
      if new is not None and new != value:
         return new, 1
   return value, 0


def _relative_to(target: Path, base: Path) -> str:
   """!A path from a folder to a file, written with "/" (".." where it climbs).
   @param target  the file
   @param base    the folder
   @return relative path
   """
   return Path(os.path.relpath(target, base)).as_posix()


def _rewrite(game: Path, file: Path, moved: dict[Path, Path], sample_folder: Path) -> int:
   """!Points a copied manifest's paths that led into a shared folder at the shared files' copies.
   @param game           the new game folder
   @param file           a copied JSON manifest in it
   @param moved          {shared file in the engine: its copy}
   @param sample_folder  the sample's app folder (where the paths were written)
   @return how many paths changed (the file is saved only then, in its own layout)
   """
   text = file.read_text(encoding="utf-8")
   data = manifest_io.load(file)
   rel = file.relative_to(game)
   origin_base = path_base(sample_folder, sample_folder / rel)
   new_base = path_base(game, file)

   def change(value: str) -> str | None:
      """!The new path of one text, or None when it is not a path into a shared folder."""
      if not _plain_relative(value):
         return None
      target = (origin_base / value).resolve()
      copy = moved.get(target)
      return _relative_to(copy, new_base) if copy is not None else None

   new, count = _map_strings(data, change)
   if count:
      manifest_io.save(file, new, manifest_io.detect(text, data))
   return count


def _rename(project: Path, sample: Sample, shown: str) -> None:
   """!The copy's project manifest with New game's build-safe name rules and the sample it came from.
   @param project  the copy's reference/project.json
   @param sample   Sample
   @param shown    the game's name as given (or the folder's)
   @return None
   """
   text = project.read_text(encoding="utf-8")
   data = manifest_io.load(project)
   layout = manifest_io.detect(text, data)
   data[NAME_KEY] = starter_scene.build_name(shown)
   rom = data.get(ROM_KEY)
   if isinstance(rom, dict):
      # D-40 RG's header rules: the title from the name, the generic code until the developer gives one
      rom[ROM_TITLE_KEY] = starter_scene.rom_title(shown)
      rom[ROM_CODE_KEY] = starter_scene.ROM_CODE
   editor = data.get(EDITOR_KEY) if isinstance(data.get(EDITOR_KEY), dict) else {}
   editor[SAMPLE_KEY] = {"id": sample.id, "version": sample.version}
   data[EDITOR_KEY] = editor
   manifest_io.save(project, data, layout)


def copy(sample: Sample, folder: str | Path, name: str | None = None) -> Path:
   """!Copies a sample into a new folder as a game of its own (the module docstring's steps 1-5).
   @param sample  Sample
   @param folder  the new game's folder (new, or empty; never inside protected_folders())
   @param name    the game's name, or None for the folder's ("name" becomes its build_name())
   @return the copy's project manifest
   @throws DocumentError when the folder is refused or the copy would still lead out of its folder
   """
   game = check_destination(folder)
   written = []
   for rel in sample_files(sample):
      dst = game / rel
      dst.parent.mkdir(parents=True, exist_ok=True)
      shutil.copyfile(sample.folder / rel, dst)
      written.append(dst)
   moved: dict[Path, Path] = {}
   for share in sample.shared:
      copies = templates.apply(share.template, game / share.to)
      for rel, dst in zip(share.template.files(), copies):
         moved[(share.template.folder / rel).resolve()] = dst
   for dst in written:
      if dst.suffix == JSON_SUFFIX:
         _rewrite(game, dst, moved, sample.folder)
   project = game / REFERENCE_DIR / PROJECT_FILE
   _rename(project, sample, name or game.name)
   problems = outside_paths(game)
   if problems:
      raise DocumentError(f"the copy of {sample.id} in {game} still leads out of its folder: {'; '.join(problems)}")
   return project


# -- checking ---------------------------------------------------------------------------------------------------------

def _leaves(base: Path, value: str, game: Path) -> bool:
   """!Whether a relative path, read from a folder, ends outside the game folder.
   @param base   the folder it is relative to
   @param value  the path
   @param game   the game folder (resolved)
   @return True when it leads out
   """
   target = (base / value).resolve()
   return target != game and game not in target.parents


def outside_paths(folder: str | Path) -> list[str]:
   """!What ties a game folder to files outside it: JSON manifest paths that lead out of it (or are absolute and
   exist), quoted include lines that do, and project "libraries" capsule_game() does not link for any game.
   @param folder  a game folder (reference/project.json)
   @return problems ("FILE: PATH leads out of the game folder"); empty when the game stands alone
   """
   game = Path(folder).resolve()
   problems: list[str] = []
   for file in sorted(game.rglob("*")):
      rel = file.relative_to(game)
      if not file.is_file() or any(part in SKIPPED_FOLDERS for part in rel.parts):
         continue
      if file.suffix == JSON_SUFFIX:
         try:
            data = manifest_io.load(file)
         except (OSError, ValueError) as e:
            problems.append(f"{rel.as_posix()}: cannot read it ({e})")
            continue
         base = path_base(game, file)
         found: list[str] = []

         def note(value: str, out: list[str] = found, base: Path = base) -> None:
            """!Notes one text that is a path leading out (absolute ones only when they exist); changes nothing."""
            if value.startswith("/") and len(value) <= PATH_MAX_CHARS and Path(value).exists():
               out.append(value)
            elif _plain_relative(value) and ".." in PurePosixPath(value).parts and _leaves(base, value, game):
               out.append(value)
            return None

         _map_strings(data, note)   # a walk over every text: note() returns None, so nothing is replaced
         problems += [f"{rel.as_posix()}: {value} leads out of the game folder" for value in found]
      elif file.suffix in SOURCE_SUFFIXES:
         text = file.read_text(encoding="utf-8", errors="replace")
         for included in INCLUDE.findall(text):
            if ".." in PurePosixPath(included).parts and _leaves(file.parent, included, game):
               problems.append(f"{rel.as_posix()}: #include \"{included}\" leads out of the game folder")
   project = game / REFERENCE_DIR / PROJECT_FILE
   try:
      data = manifest_io.load(project)
   except (OSError, ValueError):
      problems.append(f"{REFERENCE_DIR}/{PROJECT_FILE}: missing or unreadable")
      return problems
   libraries = data.get(LIBRARIES_KEY, []) if isinstance(data, dict) else []
   for library in libraries if isinstance(libraries, list) else [libraries]:
      if library not in GAME_LIBRARIES:
         problems.append(f"{REFERENCE_DIR}/{PROJECT_FILE}: library {library!r} is not one the engine links for any "
                         f"game ({', '.join(GAME_LIBRARIES)})")
   return problems
