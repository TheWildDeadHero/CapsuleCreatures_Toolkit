"""!A game's project manifest (reference/project.json, capsule.project/1):
its per-game build settings (A-2, A-5) and the data files it names (the
Studio opens a game through them: game_files()).

The engine's tools/build_settings.py is the one authority on the settings,
their ranges and defaults; this module edits the manifest's "build" object
through a Document (undo, dirty state) and checks every value with it, so
the editor accepts exactly what the build accepts. Qt-free; the project
settings window and `capsule-studio project ...` use it.
"""
from __future__ import annotations

import types
from pathlib import Path
from typing import Any

from . import engine
from .document import Document, DocumentError

## Project manifest schema.
SCHEMA = "capsule.project/1"
## Data files a project manifest may name, as (key, what it is), in the Studio's page order.
GAME_FILES = (("maps", "world (capsule.world/1)"), ("assets", "asset manifest (capsule.assets/1)"),
              ("scripts", "scripts manifest (capsule.scripts/1)"), ("battle", "battle data (capsule.battle/1)"))
## ROM wait states (first access, sequential access) the VRAM queue's cost table assumes (the engine's default WAITCNT).
EXPECTED_ROM_WAIT_STATES = (3, 1)

## One of the engine's tools/build_settings.Setting objects (that module is imported at run time, see settings_tool()).
BuildSetting = Any
## A value a project manifest gives for a setting: an int, or a decimal or 0x string.
RawSetting = int | str


def settings_tool() -> types.ModuleType:
   """!The engine's build settings module.
   @return module
   """
   return engine.tool("build_settings")


def open_project(path: str | Path) -> Document:
   """!Opens a project manifest.
   @param path  reference/project.json
   @return Document
   @throws DocumentError when it is not a project manifest
   """
   try:
      return Document.open(path, SCHEMA)
   except (OSError, ValueError) as e:
      raise DocumentError(f"cannot read {path}: {e}") from e


def game_folder(doc: Document) -> Path:
   """!The game's folder: the one its reference/ folder is in. The paths a
   manifest names are relative to it (as the engine's build reads them).
   @param doc  project Document (opened from a file)
   @return Path
   """
   if doc.path is None:
      raise DocumentError("the project manifest has not been saved yet")
   return doc.path.parent.parent


def game_files(doc: Document) -> dict[str, Path]:
   """!The data files a project manifest names.
   @param doc  project Document
   @return {key: absolute Path} for each GAME_FILES key the manifest gives (the file may be missing)
   @throws DocumentError when a key holds something other than a relative path
   """
   base = game_folder(doc)
   out = {}
   for key, _what in GAME_FILES:
      rel = doc.data.get(key)
      if rel is None:
         continue
      if not isinstance(rel, str) or not rel:
         raise DocumentError(f"{doc.path.name}: {key!r} must be a path relative to the game folder")
      out[key] = (base / rel).resolve()
   return out


class SettingRow:
   """!One setting as an editor shows it."""

   def __init__(self, setting: BuildSetting, value: int, given: bool, error: str | None = None) -> None:
      """!Describes a row.
      @param setting  build_settings.Setting
      @param value    effective int value (the default when the manifest's is invalid)
      @param given    True when the manifest sets it (False: engine default)
      @param error    why the manifest's value is invalid, or None
      """
      ## The engine's description of the setting.
      self.setting = setting
      ## Effective value.
      self.value = value
      ## Whether the manifest sets it.
      self.given = given
      ## Why the manifest's value is invalid (the build fails), or None.
      self.error = error

   @property
   def key(self) -> str:
      """!Key in the "build" object.
      @return str
      """
      return self.setting.key

   @property
   def shown(self) -> str:
      """!Value as written in the manifest.
      @return str
      """
      return self.setting.show(self.value)


def build_values(doc: Document) -> dict[str, int]:
   """!The settings the manifest gives, checked.
   @param doc  project Document
   @return {key: int}
   @throws DocumentError when a value is invalid (the build would fail too)
   """
   bs = settings_tool()
   try:
      return bs.parse(doc.data.get("build"))
   except bs.SettingsError as e:
      raise DocumentError(str(e)) from e


def _build(doc: Document) -> dict[str, Any]:
   """!The manifest's "build" object.
   @param doc  project Document
   @return dict ({} when absent)
   @throws DocumentError when it is not an object
   """
   build = doc.data.get("build", {})
   if not isinstance(build, dict):
      raise DocumentError('"build" must be an object; fix project.json by hand')
   return build


def rows(doc: Document) -> list[SettingRow]:
   """!Every setting with its effective value. Never fails on a bad value:
   such a row carries the error (and the default as its value), so editors
   show every row and the bad one can be fixed.
   @param doc  project Document
   @return list of SettingRow, in the engine's order
   @throws DocumentError when "build" is not an object
   """
   bs = settings_tool()
   build = _build(doc)
   out = []
   for s in bs.SETTINGS:
      if s.key not in build:
         out.append(SettingRow(s, s.default, False))
         continue
      try:
         out.append(SettingRow(s, s.parse(build[s.key]), True))
      except bs.SettingsError as e:
         out.append(SettingRow(s, s.default, True, str(e)))
   return out


def problems(doc: Document) -> list[tuple[str, str]]:
   """!What the build would reject, and cautions about values it accepts.
   @param doc  project Document
   @return list of (severity 'error' or 'warning', message)
   """
   bs = settings_tool()
   try:
      values = bs.effective(bs.parse(doc.data.get("build")))
   except bs.SettingsError as e:
      return [("error", str(e))]
   out = []
   w = bs.decode_waitcnt(values["gba_waitcnt"])
   if (w["ws0_first"], w["ws0_second"]) != EXPECTED_ROM_WAIT_STATES:
      out.append(("warning", f"ROM wait states are {w['ws0_first']}/{w['ws0_second']}: the VRAM queue's cost "
                             "table assumes 3/1, so ROM uploads may take longer than it estimates"))
   if w["prefetch"] != "on":
      out.append(("warning", "the prefetch buffer is off: code in ROM runs noticeably slower"))
   return out


def set_setting(doc: Document, key: str, raw: RawSetting) -> RawSetting:
   """!Sets a build setting (one undo step).
   @param doc  project Document
   @param key  setting key
   @param raw  value (int, or a decimal or 0x string)
   @return the stored value
   @throws DocumentError for an unknown key or a bad value
   """
   bs = settings_tool()
   s = bs.BY_KEY.get(key)
   if s is None:
      raise DocumentError(f"unknown build setting {key!r} (known: {', '.join(bs.BY_KEY)})")
   try:
      value = s.parse(raw)
   except bs.SettingsError as e:
      raise DocumentError(str(e)) from e
   stored = s.stored(value)
   # Refuses a "build" that is not an object before touching the manifest.
   _build(doc)
   with doc.edit(f"Set {key}") as data:
      build = data.setdefault("build", {})
      build[key] = stored
   return stored


def clear_setting(doc: Document, key: str) -> None:
   """!Removes a build setting, so the engine's default applies (one undo step).
   @param doc  project Document
   @param key  setting key
   @return None
   """
   bs = settings_tool()
   if key not in bs.BY_KEY:
      raise DocumentError(f"unknown build setting {key!r}")
   build = _build(doc)
   if key not in build:
      return
   with doc.edit(f"Use the default {key}") as data:
      del data["build"][key]
      if not data["build"]:
         del data["build"]


def set_waitcnt_fields(doc: Document, fields: dict[str, Any]) -> int:
   """!Changes some WAITCNT fields, keeping the others (one undo step).
   @param doc     project Document
   @param fields  {field name: choice}, names and choices as in build_settings.WAITCNT_FIELDS
   @return the new value
   @throws DocumentError for an unknown field or choice
   """
   bs = settings_tool()
   current = next(r for r in rows(doc) if r.key == "gba_waitcnt").value
   merged = bs.decode_waitcnt(current)
   merged.update(fields)
   try:
      value = bs.encode_waitcnt(merged)
   except bs.SettingsError as e:
      raise DocumentError(str(e)) from e
   set_setting(doc, "gba_waitcnt", value)
   return value
