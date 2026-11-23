"""!D-36 package 3 step 3C: a game's build usage and its exclusion manifest (the engine's docs/USAGE.md "Exclusion
manifest"), for the project settings window's Build usage panel and `capsule-studio exclude`.

A build folder holds, for each game it built (the project's "name"):

- `usage/GAME.json`: the usage report (which engine modules and script ops the game's data uses);
- `usage/GAME.exclude.json`: what the build says the game can exclude (capsule.exclude/1: the excludable modules no
  record names and no object of the game's code calls, and the script ops its scripts do not emit);
- `usage/GAME.exclude-check.txt`: the last check of the game's own manifest (errors, warnings, notes);
- for a GBA build, `capsule_GAME.nm`: the program's symbol listing, from which the engine's tools/usage.py tells the
  bytes each module links.

The game's own manifest is the file its project names under "exclude" (reference/exclude.json when the studio
creates it). The engine's tools/usage_exclude.py checks every manifest written here (validate()). Nothing here
imports Qt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from . import engine, project
from .document import Document, DocumentError

## The reports' folder in a build folder.
USAGE_FOLDER = "usage"
## The suggestion's and the findings' suffixes (the engine's cmake/usage.cmake).
SUGGESTION_SUFFIX, FINDINGS_SUFFIX = ".exclude.json", ".exclude-check.txt"
## The GBA program's symbol listing: capsule_GAME.nm (the engine's cmake/nm_listing.cmake).
NM_PREFIX, NM_SUFFIX = "capsule_", ".nm"
## The project key naming the manifest.
EXCLUDE_KEY = "exclude"
## The manifest the studio creates when the project names none (relative to the game folder).
DEFAULT_MANIFEST = "reference/exclude.json"
## The reason of an item chosen in the studio that the build did not suggest.
STUDIO_REASON = "chosen in the studio"
## The manifest's item lists.
MODULES, SCRIPT_OPS = "modules", "script_ops"
## The usage category of the scripts' opcodes.
SCRIPT_OP_CATEGORY = "script.op"
## The findings' line prefixes (tools/usage_exclude.py findings_text()).
ERROR_PREFIX, WARNING_PREFIX, NOTE_PREFIX = "error: ", "warning: ", "note: "
## The manifest's JSON indent (tools/usage_exclude.py).
JSON_INDENT = 1


class ExclusionError(ValueError):
   """!A build folder, report or manifest that cannot be read or written."""


def tools() -> tuple[ModuleType, ModuleType]:
   """!The engine's usage tools.
   @return (tools/usage.py, tools/usage_exclude.py)
   @throws ExclusionError when the engine in use has no exclusion manifest (before D-36 package 3)
   """
   try:
      return engine.tool("usage"), engine.tool("usage_exclude")
   except engine.EngineNotFound as e:
      raise ExclusionError(str(e)) from None
   except ImportError:
      raise ExclusionError(f"the engine at {engine.root()} has no exclusion manifest (tools/usage_exclude.py): "
                           f"update it") from None


@dataclass
class ModuleRow:
   """!One engine module of the Build usage table."""

   ## The module (a folder of the engine's src/).
   name: str
   ## The usage categories that use it (empty: no record names it).
   used_by: list[str]
   ## Whether a game can exclude it (tools/usage_exclude.py EXCLUDABLE_MODULES).
   excludable: bool
   ## Whether the build offers to exclude it (in the suggestion).
   suggested: bool
   ## An excludable module no record names that the build did not offer: the game's own code calls it.
   game_code: bool
   ## Whether the game's manifest excludes it.
   excluded: bool
   ## Bytes it links in the GBA program, or None without a listing.
   gba_bytes: int | None


@dataclass
class OpRow:
   """!One script op of the Build usage table."""

   ## The op.
   name: str
   ## Times the game's scripts emit it.
   emitted: int
   ## Whether the build offers to exclude it.
   suggested: bool
   ## Whether the game's manifest excludes it.
   excluded: bool


@dataclass
class BuildUsage:
   """!What a build folder says about one game."""

   ## The game (the project's name).
   game: str
   ## The usage report.
   report: dict[str, Any]
   ## The build's suggestion (capsule.exclude/1), or None (a build before package 3).
   suggestion: dict[str, Any] | None = None
   ## The last check's findings: (level, text), level "error", "warning" or "note".
   findings: list[tuple[str, str]] = field(default_factory=list)
   ## The link comparison (tools/usage.py compare()) of the GBA listing, or None.
   linked: dict[str, Any] | None = None
   ## The listing read, or None.
   nm_path: Path | None = None


def game_name(doc: Document) -> str:
   """!The game a project builds (its "name": the build's usage/NAME.json).
   @param doc  the project Document
   @return the name
   @throws ExclusionError when the project has none
   """
   name = doc.data.get("name")
   if not isinstance(name, str) or not name:
      raise ExclusionError("the project has no \"name\" (the build names its usage report after it)")
   return name


def parse_findings(text: str) -> list[tuple[str, str]]:
   """!The findings of a check's output.
   @param text  usage/GAME.exclude-check.txt
   @return (level, text) per finding, in order; the summary line is left out
   """
   out = []
   for line in text.splitlines():
      for level, prefix in (("error", ERROR_PREFIX), ("warning", WARNING_PREFIX), ("note", NOTE_PREFIX)):
         if line.startswith(prefix):
            out.append((level, line[len(prefix):]))
   return out


def read_build(build: str | Path, game: str) -> BuildUsage:
   """!Reads what a build folder says about a game.
   @param build  the build folder
   @param game   the game's name
   @return BuildUsage
   @throws ExclusionError when the folder has no report for the game
   """
   usage, usage_exclude = tools()
   folder = Path(build) / USAGE_FOLDER
   report_path = folder / f"{game}.json"
   if not report_path.is_file():
      raise ExclusionError(f"no usage report at {report_path} (build the game: its target capsule_{game}_usage)")
   try:
      out = BuildUsage(game, usage.read_report(report_path))
      suggestion = folder / f"{game}{SUGGESTION_SUFFIX}"
      if suggestion.is_file():
         out.suggestion = usage_exclude.load(suggestion)
      findings = folder / f"{game}{FINDINGS_SUFFIX}"
      if findings.is_file():
         out.findings = parse_findings(findings.read_text(encoding="utf-8", errors="replace"))
      listing = next(Path(build).glob(f"**/{NM_PREFIX}{game}{NM_SUFFIX}"), None)
      if listing is not None:
         out.nm_path = listing
         out.linked = usage.compare(out.report, usage.read_linked(listing.read_text(encoding="utf-8",
                                                                                     errors="replace")))
   except (usage.UsageError, usage_exclude.ExcludeError, OSError) as e:
      raise ExclusionError(str(e)) from None
   return out


def manifest_path(doc: Document) -> Path | None:
   """!The manifest the project names.
   @param doc  the project Document
   @return its path, or None when the project names none
   @throws ExclusionError when "exclude" is not a relative path
   """
   rel = doc.data.get(EXCLUDE_KEY)
   if rel is None:
      return None
   if not isinstance(rel, str) or not rel:
      raise ExclusionError(f"{EXCLUDE_KEY!r} must be a path relative to the game folder")
   return (project.game_folder(doc) / rel).resolve()


def read_manifest(doc: Document) -> dict[str, Any] | None:
   """!The game's own manifest.
   @param doc  the project Document
   @return it, or None when the project names none or the file does not exist yet
   @throws ExclusionError when it does not read or is not a manifest
   """
   path = manifest_path(doc)
   if path is None or not path.is_file():
      return None
   _usage, usage_exclude = tools()
   try:
      return usage_exclude.load(path)
   except usage_exclude.ExcludeError as e:
      raise ExclusionError(str(e)) from None


def names(manifest: dict[str, Any] | None, key: str) -> list[str]:
   """!The names a manifest's list holds.
   @param manifest  the manifest, or None
   @param key       MODULES or SCRIPT_OPS
   @return them
   """
   return [item["name"] for item in (manifest or {}).get(key, [])]


def module_rows(usage: BuildUsage, manifest: dict[str, Any] | None) -> list[ModuleRow]:
   """!The modules table: every module the report lists, by name.
   @param usage     read_build()'s result
   @param manifest  the game's manifest, or None
   @return the rows
   """
   _usage, usage_exclude = tools()
   suggested = set(names(usage.suggestion, MODULES))
   excluded = set(names(manifest, MODULES))
   linked = (usage.linked or {}).get("modules", {})
   rows = []
   for name, entry in sorted(usage.report.get("modules", {}).items()):
      excludable = name in usage_exclude.EXCLUDABLE_MODULES
      used = bool(entry.get("used"))
      rows.append(ModuleRow(name, list(entry.get("by", [])), excludable, name in suggested,
                            excludable and not used and usage.suggestion is not None and name not in suggested,
                            name in excluded,
                            linked[name]["bytes"] if name in linked else (0 if usage.linked is not None else None)))
   return rows


def op_rows(usage: BuildUsage, manifest: dict[str, Any] | None) -> list[OpRow]:
   """!The script ops table: the script VM's ops, in id order.
   @param usage     read_build()'s result
   @param manifest  the game's manifest, or None
   @return the rows
   """
   _usage, usage_exclude = tools()
   emitted = usage.report.get("used", {}).get(SCRIPT_OP_CATEGORY, {})
   suggested = set(names(usage.suggestion, SCRIPT_OPS))
   excluded = set(names(manifest, SCRIPT_OPS))
   return [OpRow(op, int(emitted.get(op, 0)), op in suggested, op in excluded) for op in usage_exclude.script_ops()]


def build_manifest(usage: BuildUsage, modules: list[str], ops: list[str],
                   old: dict[str, Any] | None = None) -> dict[str, Any]:
   """!A manifest of the chosen items, each with its reason: the build's, the old manifest's, else STUDIO_REASON.
   @param usage    read_build()'s result
   @param modules  the modules to exclude
   @param ops      the script ops to exclude
   @param old      the game's manifest before, or None
   @return the manifest
   """
   _usage, usage_exclude = tools()

   def reasons(key: str) -> dict[str, str]:
      """!Known reasons of a list, the build's over the old manifest's.
      @param key  MODULES or SCRIPT_OPS
      @return name -> reason
      """
      known = {i["name"]: i.get("reason", "") for i in (old or {}).get(key, [])}
      known.update({i["name"]: i.get("reason", "") for i in (usage.suggestion or {}).get(key, [])})
      return known

   def items(key: str, chosen: list[str]) -> list[dict[str, str]]:
      """!A list's items, in the order chosen, without repeats.
      @param key     MODULES or SCRIPT_OPS
      @param chosen  the names
      @return the items
      """
      known = reasons(key)
      return [{"name": n, "reason": known.get(n) or STUDIO_REASON} for n in dict.fromkeys(chosen)]

   generated_from = (usage.suggestion or {}).get("generated_from", f"{USAGE_FOLDER}/{usage.game}.json")
   return {"schema": usage_exclude.SCHEMA, "game": usage.game, "generated_from": generated_from,
           MODULES: items(MODULES, modules), SCRIPT_OPS: items(SCRIPT_OPS, ops)}


def save(doc: Document, manifest: dict[str, Any]) -> tuple[Path, bool]:
   """!Writes the game's manifest: the file the project names, or reference/exclude.json, which the project then
   names (one undo step; the project is saved with the project window).
   @param doc       the project Document
   @param manifest  the manifest
   @return (the file written, whether the project's "exclude" was added)
   @throws ExclusionError when the manifest does not validate or the file cannot be written
   """
   _usage, usage_exclude = tools()
   try:
      usage_exclude.validate(manifest)
   except usage_exclude.ExcludeError as e:
      raise ExclusionError(str(e)) from None
   path = manifest_path(doc)
   added = path is None
   if added:
      path = (project.game_folder(doc) / DEFAULT_MANIFEST).resolve()
   try:
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text(json.dumps(manifest, indent=JSON_INDENT, ensure_ascii=False) + "\n", encoding="utf-8",
                      newline="\n")
   except OSError as e:
      raise ExclusionError(f"cannot write {path}: {e}") from None
   if added:
      try:
         with doc.edit("Name the exclusion manifest") as data:
            data[EXCLUDE_KEY] = DEFAULT_MANIFEST
      except DocumentError as e:
         raise ExclusionError(str(e)) from None
   return path, added


def summary(usage: BuildUsage, manifest: dict[str, Any] | None) -> str:
   """!The build usage as text (the command line).
   @param usage     read_build()'s result
   @param manifest  the game's manifest, or None
   @return the lines
   """
   rows = module_rows(usage, manifest)
   ops = op_rows(usage, manifest)
   lines = [f"Build usage of {usage.game}"]
   if usage.suggestion is None:
      lines.append("   (the build wrote no suggestion: build with an engine that has the exclusion manifest)")
   lines.append("Modules (excludable):")
   for r in (r for r in rows if r.excludable):
      state = ("excluded" if r.excluded else "can be excluded" if r.suggested else
               "called by the game's code" if r.game_code else "used by " + ", ".join(r.used_by) if r.used_by else
               "kept")
      size = f", {r.gba_bytes} B on the GBA" if r.gba_bytes else ""
      lines.append(f"   {r.name}: {state}{size}")
   lines.append(f"Script ops: {sum(o.excluded for o in ops)} excluded, "
                f"{sum(o.suggested and not o.excluded for o in ops)} more can be, "
                f"{sum(o.emitted > 0 for o in ops)} used by the scripts")
   if usage.findings:
      lines.append("The last build's check:")
      lines += [f"   {level}: {text}" for level, text in usage.findings]
   return "\n".join(lines) + "\n"
