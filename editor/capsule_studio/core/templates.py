"""!Battle data templates (D-23 section 3.5, decision 3; S10): a folder with a
template.json (capsule.template/1) naming the files of each part.

    {"schema": "capsule.template/1", "id": "starter", "name": "Starter", "description": "...", "version": 1,
     "parts": {"structure": ["structure.json"], "logic": ["ruleset.json", "effects/moves.ceffect"],
               "content": ["battle.json", "assets.json"]}}

Templates are found, in this order (an id found twice keeps the first):
  1. the studio's built-in ones, `capsule_studio/templates/*/template.json`
     (Blank: neutral, minimal data that compiles);
  2. the engine's samples, `samples/*/template.json` of the engine checkout
     in use (core.engine.root(); the Starter sample, E9);
  3. the reference repo's `templates/*/template.json` (the rules/ folder of
     the private CapsuleCreatures_PocketProject, D-37), found like the engine:
     CAPSULE_REFERENCE, then ../../CapsuleCreatures_PocketProject-work/rules
     and ../../CapsuleCreatures_PocketProject/rules (this toolkit inside the
     umbrella), then the same two one folder up (a standalone toolkit clone);
  4. plugins: `ctx.add_battle_template(path)` (plugin API 2,
     plugins.registry.Registry.battle_templates()).

Applying a template copies the files of the chosen parts into a folder with
their relative paths (effects/ stays effects/), refusing to overwrite a file,
and records `editor.template {id, version}` in every JSON manifest it copies
(the compilers strip "editor"), so the studio can later compare the game's
data with a newer version of the template (Q7). new_game() makes a game
folder from a template: its data in data/ and a reference/project.json that
names the battle manifest ("battle") and the asset manifest ("assets") it
copied. Nothing here depends on a user interface.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from . import engine, manifest_io
from .document import DocumentError

if TYPE_CHECKING:
   from ..plugins.registry import Registry

## A parsed JSON object.
JsonDict = dict[str, Any]

## Template manifest schema.
SCHEMA = "capsule.template/1"
## A template folder's manifest.
TEMPLATE_FILE = "template.json"
## The parts a template may give, in the order they are copied and listed (the Structure / Logic / Content editors).
PARTS = ("structure", "logic", "content")
## Keys of a template manifest ("editor" is the studio's own notes).
KEYS = ("schema", "id", "name", "description", "version", "editor", "parts")
## A template id: lower-case letters, digits, "-" and "_", starting with a letter.
TEMPLATE_ID = re.compile(r"[a-z][a-z0-9_-]*")
## Lowest template version.
FIRST_VERSION = 1

## Where a template was found (Template.origin), in discovery order.
BUILTIN = "studio"
## An engine sample.
ENGINE = "engine"
## The reference repo.
REFERENCE = "reference"
## A plugin's.
PLUGIN = "plugin"
## How each origin is shown ("Starter (engine sample)").
ORIGIN_TEXT = {BUILTIN: "built in", ENGINE: "engine sample", REFERENCE: "reference repo", PLUGIN: "plugin"}

## Folders between this file and the package (core -> capsule_studio).
PACKAGE_DEPTH = 1
## The studio's built-in templates.
BUILTIN_FOLDER = Path(__file__).resolve().parents[PACKAGE_DEPTH] / "templates"
## The engine checkout's folder of sample games (each with a template.json).
ENGINE_SAMPLES = "samples"
## The reference repo's folder of templates.
REFERENCE_TEMPLATES = "templates"
## Environment variable naming the reference repo checkout.
REFERENCE_ENV = "CAPSULE_REFERENCE"
## The repository holding the reference rules, editable copy first (D-37 section 3).
REFERENCE_REPOS = ("CapsuleCreatures_PocketProject-work", "CapsuleCreatures_PocketProject")
## The reference rules' folder inside that repository.
REFERENCE_RULES = "rules"

## A manifest's studio-only object (the compilers strip it).
EDITOR_KEY = "editor"
## editor key recording the template a file came from: {"id", "version"}.
TEMPLATE_KEY = "template"
## Suffix of the JSON manifests whose editor.template applying records.
JSON_SUFFIX = ".json"
## A JSON manifest's schema key.
SCHEMA_KEY = "schema"

## A new game's folder of battle data (beside reference/).
DATA_FOLDER = "data"
## A game's folder holding its project manifest.
REFERENCE_DIR = "reference"
## A game's project manifest.
PROJECT_FILE = "project.json"
## Project manifest schema (core.project.SCHEMA).
PROJECT_SCHEMA = "capsule.project/1"
## project.json keys new_game() writes for the manifests a template copies, by the manifest's schema.
GAME_FILE_KEYS = {"capsule.battle/1": "battle", "capsule.assets/1": "assets"}


@dataclass(frozen=True)
class Template:
   """!One template: its manifest and where it was found."""

   ## Id (unique among the templates found; the CLI's --template).
   id: str
   ## Shown name.
   name: str
   ## What it gives.
   description: str
   ## Version (a newer version of the same id may be compared with a game's copy).
   version: int
   ## The template's folder (its files are relative to it).
   folder: Path
   ## BUILTIN, ENGINE, REFERENCE or PLUGIN.
   origin: str
   ## Files of each part: {part: (relative path, ...)} in PARTS order.
   parts: dict[str, tuple[str, ...]] = field(default_factory=dict)
   ## The plugin that registered it, or None.
   plugin: str | None = None

   def label(self) -> str:
      """!The template as lists show it.
      @return e.g. "Starter (engine sample, version 1)"
      """
      where = ORIGIN_TEXT.get(self.origin, self.origin)
      if self.plugin:
         where += f" {self.plugin}"
      return f"{self.name} ({where}, version {self.version})"

   def files(self, parts: list[str] | tuple[str, ...] | None = None) -> list[str]:
      """!The files of some parts, in PARTS order.
      @param parts  part names, or None for every part
      @return relative paths
      @throws DocumentError for a part the template does not give
      """
      wanted = list(self.parts) if parts is None else list(parts)
      unknown = [p for p in wanted if p not in self.parts]
      if unknown:
         raise DocumentError(f"template {self.id} has no part {', '.join(unknown)} (parts: {', '.join(self.parts)})")
      return [f for p in PARTS if p in wanted for f in self.parts[p]]


# -- reading ----------------------------------------------------------------------------------------------------------

def _relative(value: Any, where: str) -> str:
   """!A template file path: relative, inside the template folder, written with "/".
   @param value  the path as listed
   @param where  location for messages
   @return the path
   @throws DocumentError when it is not one
   """
   if not isinstance(value, str) or not value or "\\" in value:
      raise DocumentError(f"{where}: a file is a relative path written with \"/\" (got {value!r})")
   pure = PurePosixPath(value)
   if pure.is_absolute() or ".." in pure.parts or value != pure.as_posix():
      raise DocumentError(f"{where}: {value!r} must be a plain relative path inside the template folder")
   return value


def load(path: str | Path, origin: str, plugin: str | None = None) -> Template:
   """!Reads a template.
   @param path    the template folder or its template.json
   @param origin  BUILTIN, ENGINE, REFERENCE or PLUGIN
   @param plugin  the plugin registering it, or None
   @return Template
   @throws DocumentError when the manifest is not a template or names a file that is not there
   """
   p = Path(path)
   if p.is_dir():
      p = p / TEMPLATE_FILE
   try:
      data = manifest_io.load(p)
   except (OSError, ValueError) as e:
      raise DocumentError(f"cannot read {p}: {e}") from None
   where = str(p)
   if not isinstance(data, dict) or data.get(SCHEMA_KEY) != SCHEMA:
      raise DocumentError(f"{where}: not a template ({SCHEMA_KEY} {SCHEMA})")
   extra = sorted(set(data) - set(KEYS))
   if extra:
      raise DocumentError(f"{where}: unknown key(s) {', '.join(extra)} (keys: {', '.join(KEYS)})")
   tid = data.get("id")
   if not isinstance(tid, str) or not TEMPLATE_ID.fullmatch(tid):
      raise DocumentError(f"{where}: id is a lower-case word (letters, digits, - and _), got {tid!r}")
   name = data.get("name")
   if not isinstance(name, str) or not name.strip():
      raise DocumentError(f"{where}: name is a text")
   description = data.get("description", "")
   if not isinstance(description, str):
      raise DocumentError(f"{where}: description is a text")
   version = data.get("version")
   if not isinstance(version, int) or isinstance(version, bool) or version < FIRST_VERSION:
      raise DocumentError(f"{where}: version is a whole number from {FIRST_VERSION}, got {version!r}")
   given = data.get("parts")
   if not isinstance(given, dict) or not given:
      raise DocumentError(f"{where}: parts maps {', '.join(PARTS)} to lists of files")
   unknown = sorted(set(given) - set(PARTS))
   if unknown:
      raise DocumentError(f"{where}: unknown part(s) {', '.join(unknown)} (parts: {', '.join(PARTS)})")
   parts: dict[str, tuple[str, ...]] = {}
   seen: set[str] = set()
   for part in PARTS:
      if part not in given:
         continue
      files = given[part]
      if not isinstance(files, list) or not files:
         raise DocumentError(f"{where}: parts.{part} lists at least one file")
      rels = []
      for f in files:
         rel = _relative(f, f"{where}: parts.{part}")
         if rel in seen:
            raise DocumentError(f"{where}: {rel} is listed twice")
         if not (p.parent / rel).is_file():
            raise DocumentError(f"{where}: parts.{part} names {rel}, which is not in {p.parent}")
         seen.add(rel)
         rels.append(rel)
      parts[part] = tuple(rels)
   return Template(tid, name.strip(), description, version, p.parent.resolve(), origin, parts, plugin)


def _folder_templates(folder: Path, origin: str) -> tuple[list[Template], list[str]]:
   """!The templates of a folder's sub-folders (each with a template.json), by folder name.
   @param folder  e.g. the engine's samples/
   @param origin  where they come from
   @return (templates, problems)
   """
   found, problems = [], []
   if not folder.is_dir():
      return found, problems
   for manifest in sorted(folder.glob(f"*/{TEMPLATE_FILE}")):
      try:
         found.append(load(manifest, origin))
      except DocumentError as e:
         problems.append(str(e))
   return found, problems


def reference_candidates() -> list[Path]:
   """!Folders that may hold the reference repo, in search order (core.engine.candidates()'s pattern).
   @return Paths
   """
   out = []
   if os.environ.get(REFERENCE_ENV):
      out.append(Path(os.environ[REFERENCE_ENV]).expanduser())
   # The toolkit inside the umbrella (workspace/CapsuleCreatures-work/toolkit), then a standalone toolkit clone.
   for workspace in (engine.STUDIO_ROOT.parent.parent, engine.STUDIO_ROOT.parent):
      out += [workspace / repo / REFERENCE_RULES for repo in REFERENCE_REPOS]
   return out


def reference_root() -> Path | None:
   """!The reference repo checkout: the first candidate with a templates/ folder.
   @return Path, or None when there is none (the reference repo is optional)
   """
   return next((c.resolve() for c in reference_candidates() if (c / REFERENCE_TEMPLATES).is_dir()), None)


def plugin_templates(registry: Registry | None) -> tuple[list[Template], list[str]]:
   """!The templates plugins registered (ctx.add_battle_template()).
   @param registry  plugins.Registry, or None
   @return (templates, problems)
   """
   found, problems = [], []
   for plugin, path in (registry.battle_templates() if registry is not None else []):
      try:
         found.append(load(path, PLUGIN, plugin))
      except DocumentError as e:
         problems.append(f"plugin {plugin}: {e}")
   return found, problems


def discover(registry: Registry | None = None) -> tuple[list[Template], list[str]]:
   """!Every template, in discovery order (built in, engine samples, reference repo, plugins); an id found again
   is left out with a problem.
   @param registry  plugins.Registry whose battle templates count, or None
   @return (templates, problems: unreadable manifests and repeated ids)
   """
   groups = [_folder_templates(BUILTIN_FOLDER, BUILTIN)]
   try:
      groups.append(_folder_templates(engine.root() / ENGINE_SAMPLES, ENGINE))
   except engine.EngineNotFound as e:
      groups.append(([], [str(e)]))
   ref = reference_root()
   if ref is not None:
      groups.append(_folder_templates(ref / REFERENCE_TEMPLATES, REFERENCE))
   groups.append(plugin_templates(registry))
   out: list[Template] = []
   problems: list[str] = []
   for found, trouble in groups:
      problems += trouble
      for t in found:
         first = next((o for o in out if o.id == t.id), None)
         if first is not None:
            problems.append(f"template {t.id!r} of {t.folder} is left out: {first.label()} has that id")
            continue
         out.append(t)
   return out, problems


def find(name: str, registry: Registry | None = None) -> Template:
   """!A template by id (or by its name, ignoring case).
   @param name      "starter", "Blank", ...
   @param registry  plugins.Registry, or None
   @return Template
   @throws DocumentError when there is none
   """
   found, _problems = discover(registry)
   for t in found:
      if t.id == name or t.name.lower() == name.lower():
         return t
   raise DocumentError(f"no template {name!r} (templates: {', '.join(t.id for t in found) or 'none'})")


# -- applying ---------------------------------------------------------------------------------------------------------

def plan(template: Template, folder: str | Path, parts: list[str] | None = None) -> list[tuple[Path, Path]]:
   """!What applying a template copies: each file from the template folder to the same relative path in the
   target folder.
   @param template  Template
   @param folder    target folder
   @param parts     part names, or None for every part
   @return [(source, target)]
   @throws DocumentError when a target file exists already (nothing is overwritten)
   """
   target = Path(folder)
   pairs = [(template.folder / rel, target / rel) for rel in template.files(parts)]
   taken = [str(dst) for _src, dst in pairs if dst.exists()]
   if taken:
      raise DocumentError(f"applying {template.id} would overwrite {', '.join(taken)}")
   return pairs


def _record(path: Path, template: Template) -> None:
   """!Writes editor.template {id, version} into a copied JSON manifest (other files are left as they are).
   @param path      the copy
   @param template  Template
   @return None
   """
   if path.suffix != JSON_SUFFIX:
      return
   data = manifest_io.load(path)
   if not isinstance(data, dict) or SCHEMA_KEY not in data:
      return
   ed = data.get(EDITOR_KEY) if isinstance(data.get(EDITOR_KEY), dict) else {}
   ed[TEMPLATE_KEY] = {"id": template.id, "version": template.version}
   data[EDITOR_KEY] = ed
   manifest_io.save(path, data)


def recorded(path: str | Path) -> JsonDict | None:
   """!The template a manifest was copied from.
   @param path  a JSON manifest
   @return {"id", "version"}, or None when it records none
   """
   try:
      data = manifest_io.load(Path(path))
   except (OSError, ValueError):
      return None
   ed = data.get(EDITOR_KEY) if isinstance(data, dict) else None
   rec = ed.get(TEMPLATE_KEY) if isinstance(ed, dict) else None
   return dict(rec) if isinstance(rec, dict) else None


def game_manifests(paths: list[Path]) -> dict[str, Path]:
   """!The copied manifests a project manifest names, by its key (GAME_FILE_KEYS: the battle and asset manifests).
   @param paths  copied files
   @return {"battle" | "assets": Path} (the first of each)
   """
   out: dict[str, Path] = {}
   for p in paths:
      if p.suffix != JSON_SUFFIX:
         continue
      try:
         data = manifest_io.load(p)
      except (OSError, ValueError):
         continue
      key = GAME_FILE_KEYS.get(data.get(SCHEMA_KEY)) if isinstance(data, dict) else None
      if key is not None and key not in out:
         out[key] = p
   return out


def apply(template: Template, folder: str | Path, parts: list[str] | None = None) -> list[Path]:
   """!Copies a template's parts into a folder (relative paths kept; editor.template recorded in the JSON
   manifests).
   @param template  Template
   @param folder    target folder (created when missing)
   @param parts     part names, or None for every part
   @return the files written
   @throws DocumentError when a file would be overwritten
   """
   pairs = plan(template, folder, parts)
   written = []
   for src, dst in pairs:
      dst.parent.mkdir(parents=True, exist_ok=True)
      shutil.copyfile(src, dst)
      _record(dst, template)
      written.append(dst)
   return written


def new_game(folder: str | Path, template: Template, name: str | None = None) -> Path:
   """!A new game folder from a template: the template's files in data/, and reference/project.json naming the
   battle and asset manifests it copied (paths relative to the game folder, as the engine's build reads them).
   @param folder    the game folder (new, or empty)
   @param template  Template
   @param name      the game's name, or None for the folder's name
   @return the project manifest's path
   @throws DocumentError when the folder has files already
   """
   game = Path(folder)
   if game.exists() and (not game.is_dir() or any(game.iterdir())):
      raise DocumentError(f"{game} is not an empty folder: a new game starts in a new folder")
   project = game / REFERENCE_DIR / PROJECT_FILE
   written = apply(template, game / DATA_FOLDER)
   data: JsonDict = {SCHEMA_KEY: PROJECT_SCHEMA, "name": name or game.name,
                     EDITOR_KEY: {TEMPLATE_KEY: {"id": template.id, "version": template.version}}}
   for key, path in game_manifests(written).items():
      data[key] = path.relative_to(game).as_posix()
   project.parent.mkdir(parents=True, exist_ok=True)
   manifest_io.save(project, data)
   return project
