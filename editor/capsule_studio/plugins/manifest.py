"""!Plugin manifests (plugin.json, capsule.plugin/1; D-10 §3).

    {
      "schema": "capsule.plugin/1",
      "id": "acme.day_cycle",            reverse-domain style, unique per project
      "version": "2026.10.17.0690",          calendar version (see versions.py)
      "api": 2,                              plugin API number it was written for (1 or 2: templates)
      "requires": {"capsule_studio": ">=2026.10.01.0000", "plugins": ["acme.base"]},
      "extension": {"module": "day_cycle.extension"},
      "connector": {"module": "day_cycle.connector"},
      "pure_python_deps": ["somepkg-1.0-py3-none-any.whl"],
      "title": "Day cycle",                 optional, for lists
      "cli": "cycle"                         built-in extensions only: short command group name
    }

Modules are relative to the plugin folder (which is put on the import path
while the plugin loads). An extension module defines register(ctx) (see
registry.ExtensionContext).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import versions

## Manifest schema.
SCHEMA = "capsule.plugin/1"
## Keys a manifest may have.
KEYS = {"schema", "id", "version", "api", "requires", "extension", "connector", "pure_python_deps", "title", "cli",
        "editor"}
## Plugin ids: dotted lower-case words.
ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")


class ManifestError(Exception):
   """!A plugin.json is malformed; the message names the file."""
   pass


class PluginInfo:
   """!A parsed plugin.json."""

   def __init__(self, folder: str | Path, data: Any, builtin: bool = False) -> None:
      """!Checks a manifest.
      @param folder   the plugin's folder
      @param data     parsed plugin.json
      @param builtin  shipped with the studio (may declare "cli")
      """
      where = f"{Path(folder) / 'plugin.json'}"
      if not isinstance(data, dict):
         raise ManifestError(f"{where}: expected an object")
      unknown = sorted(set(data) - KEYS)
      if unknown:
         raise ManifestError(f"{where}: unknown key(s) {', '.join(unknown)}")
      if data.get("schema") != SCHEMA:
         raise ManifestError(f"{where}: schema must be {SCHEMA!r}")
      pid = data.get("id")
      if not isinstance(pid, str) or not ID_PATTERN.fullmatch(pid):
         raise ManifestError(f"{where}: id must be reverse-domain style (e.g. \"acme.day_cycle\"), got {pid!r}")
      try:
         versions.parse(data.get("version"))
      except versions.VersionError as e:
         raise ManifestError(f"{where}: {e}") from None
      api = data.get("api")
      if not isinstance(api, int) or isinstance(api, bool) or api < 1:
         raise ManifestError(f"{where}: api must be the plugin API number (an integer)")
      req = data.get("requires", {})
      if not isinstance(req, dict) or set(req) - {"capsule_studio", "plugins"}:
         raise ManifestError(f"{where}: requires holds capsule_studio and plugins")
      if "capsule_studio" in req:
         try:
            # Any valid version will do: this only checks that the requirement parses.
            versions.satisfies("2000.01.01.0000", req["capsule_studio"])
         except versions.VersionError as e:
            raise ManifestError(f"{where}: requires.capsule_studio: {e}") from None
      deps = req.get("plugins", [])
      if not isinstance(deps, list) or not all(isinstance(d, str) and ID_PATTERN.fullmatch(d) for d in deps):
         raise ManifestError(f"{where}: requires.plugins lists plugin ids")
      for kind in ("extension", "connector"):
         part = data.get(kind)
         if part is not None and (not isinstance(part, dict) or set(part) != {"module"} or
                                  not isinstance(part["module"], str)):
            raise ManifestError(f"{where}: {kind} is {{\"module\": \"package.module\"}}")
      if data.get("extension") is None and data.get("connector") is None:
         raise ManifestError(f"{where}: a plugin has an extension, a connector, or both")
      wheels = data.get("pure_python_deps", [])
      if not isinstance(wheels, list) or not all(isinstance(w, str) for w in wheels):
         raise ManifestError(f"{where}: pure_python_deps lists wheel file names")
      cli = data.get("cli")
      if cli is not None and (not builtin or not isinstance(cli, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", cli)):
         raise ManifestError(f"{where}: cli (a short command name) is for the studio's own extensions; other "
                             f"plugins' commands run as 'capsule-studio {pid} COMMAND'")
      ## The plugin's folder (resolved).
      self.folder = Path(folder).resolve()
      ## Plugin id.
      self.id = pid
      ## Calendar version.
      self.version = data["version"]
      ## Plugin API number.
      self.api = api
      ## Required studio version range, or None.
      self.requires_studio = req.get("capsule_studio")
      ## Required plugin ids.
      self.requires_plugins = list(deps)
      ## Extension module name, or None.
      self.extension = (data.get("extension") or {}).get("module")
      ## Connector module name, or None.
      self.connector = (data.get("connector") or {}).get("module")
      ## Wheel files it vendors (in its wheels/ folder).
      self.wheels = list(wheels)
      ## Display title.
      self.title = data.get("title") or pid
      ## Command group name on the command line.
      self.cli = cli or pid
      ## Shipped with the studio.
      self.builtin = builtin

   @classmethod
   def read(cls, folder: str | Path, builtin: bool = False) -> PluginInfo:
      """!Reads a plugin folder's plugin.json.
      @param folder   folder
      @param builtin  shipped with the studio
      @return PluginInfo
      """
      path = Path(folder) / "plugin.json"
      try:
         data = json.loads(path.read_text(encoding="utf-8"))
      except OSError as e:
         raise ManifestError(f"{path}: cannot read ({e.strerror})") from None
      except json.JSONDecodeError as e:
         raise ManifestError(f"{path}: {e}") from None
      return cls(folder, data, builtin)
