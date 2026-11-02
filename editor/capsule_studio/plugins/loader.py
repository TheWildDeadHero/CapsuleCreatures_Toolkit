"""!Loading plugins into a Registry (§2-§3).

Loading a plugin checks, in order: its manifest, the plugin API number
(registry.MIN_API to registry.API),
the studio version it requires, the plugins it requires (already loaded),
and the pure-Python rule (purity.py); then imports its extension module
and calls register(ctx). A plugin that fails any step is skipped and the
reason recorded in Registry.errors; nothing it registered stays.

Plugin packages are imported under a private name per plugin, so two
plugins may use the same package name; a plugin's modules import each
other relatively (from . import x).

Connector plugins (manifest and compiler data) need the
compiler-side host, which is not built yet: such plugins are refused with a
message saying so.

The studio's own extensions live in capsule_studio/extensions/NAME/ and
load the same way (builtin_registry()).
"""
from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType

from .. import __calver__
from . import manifest, project, purity, registry

## Folder of the studio's own extensions.
BUILTIN_DIR = Path(__file__).resolve().parent.parent / "extensions"

## The registry of the studio's own extensions (built once).
_BUILTIN: registry.Registry | None = None


class PluginError(Exception):
   """!A plugin could not be loaded; the message says which and why."""
   pass


def builtin_folders() -> list[Path]:
   """!Folders of the studio's own extensions.
   @return sorted list of Paths
   """
   if not BUILTIN_DIR.is_dir():
      return []
   return sorted(p for p in BUILTIN_DIR.iterdir() if (p / "plugin.json").is_file())


def _private_name(pid: str) -> str:
   """!Module prefix a plugin's packages are imported under.
   @param pid  plugin id
   @return name
   """
   return "_capsule_plugin_" + re.sub(r"[^0-9a-zA-Z]", "_", pid)


def _import(info: manifest.PluginInfo, module: str) -> ModuleType:
   """!Imports one of a plugin's modules under its private name.
   @param info    manifest.PluginInfo
   @param module  "package.module" relative to the plugin folder
   @return the module
   """
   top, _, rest = module.partition(".")
   base = _private_name(info.id)
   pkg_name = f"{base}.{top}"
   # An empty namespace package holds the plugin's top-level packages.
   if base not in sys.modules:
      spec = importlib.util.spec_from_loader(base, loader=None, is_package=True)
      root = importlib.util.module_from_spec(spec)
      root.__path__ = []
      sys.modules[base] = root
   if pkg_name not in sys.modules:
      init = info.folder / top / "__init__.py"
      if not init.is_file():
         raise PluginError(f"plugin {info.id}: {top}/__init__.py not found in {info.folder}")
      spec = importlib.util.spec_from_file_location(pkg_name, init, submodule_search_locations=[str(init.parent)])
      mod = importlib.util.module_from_spec(spec)
      sys.modules[pkg_name] = mod
      try:
         spec.loader.exec_module(mod)
      except BaseException:
         del sys.modules[pkg_name]
         raise
   return importlib.import_module(f"{pkg_name}.{rest}") if rest else sys.modules[pkg_name]


def load_plugin(reg: registry.Registry, info: manifest.PluginInfo, studio_version: str = __calver__) -> None:
   """!Loads one plugin.
   @param reg             Registry
   @param info            manifest.PluginInfo
   @param studio_version  calendar version to check "requires" against
   @throws PluginError (nothing it registered is kept)
   @return None
   """
   from . import versions
   if info.id in reg.plugins:
      raise PluginError(f"plugin {info.id}: loaded twice ({reg.plugins[info.id].folder} and {info.folder})")
   if not registry.MIN_API <= info.api <= registry.API:
      raise PluginError(f"plugin {info.id}: written for plugin API {info.api}; this studio has API {registry.API} "
                        f"(it loads plugins written for API {registry.MIN_API} to {registry.API})")
   if info.requires_studio and not versions.satisfies(studio_version, info.requires_studio):
      raise PluginError(f"plugin {info.id}: needs capsule-studio {info.requires_studio}; this is {studio_version}")
   missing = [d for d in info.requires_plugins if d not in reg.plugins]
   if missing:
      raise PluginError(f"plugin {info.id}: needs plugin(s) {', '.join(missing)} (list them first)")
   if info.connector is not None:
      raise PluginError(f"plugin {info.id}: has a connector; connectors (compiler-side data) are not "
                        "supported by this studio yet")
   try:
      purity.check_folder(info.id, info.folder)
      purity.check_sources(info.id, info.folder)
   except purity.PurityError as e:
      raise PluginError(str(e)) from None
   for w in info.wheels:
      wheel = info.folder / "wheels" / w
      if not w.endswith("-py3-none-any.whl") or not wheel.is_file():
         raise PluginError(f"plugin {info.id}: pure_python_deps {w!r} must be a py3-none-any wheel in wheels/")
      # A pure-Python wheel is a zip archive Python imports from directly.
      if str(wheel) not in sys.path:
         sys.path.append(str(wheel))
   purity.install()
   purity.GUARD.watch(info.id, info.folder)
   reg.plugins[info.id] = info
   try:
      mod = _import(info, info.extension)
      fn = getattr(mod, "register", None)
      if not callable(fn):
         raise PluginError(f"plugin {info.id}: {info.extension} has no register(ctx)")
      fn(registry.ExtensionContext(reg, info, studio_version))
   except PluginError:
      reg.forget([info.id])
      raise
   except Exception as e:   # anything a plugin raises while loading
      reg.forget([info.id])
      raise PluginError(f"plugin {info.id}: {type(e).__name__}: {e}") from e


def load_folders(reg: registry.Registry, folders: Iterable[str | Path], builtin: bool = False) -> list[str]:
   """!Loads plugins from folders, recording failures in reg.errors.
   @param reg      Registry
   @param folders  plugin folders, in order
   @param builtin  the studio's own extensions
   @return ids loaded
   """
   loaded: list[str] = []
   for f in folders:
      try:
         info = manifest.PluginInfo.read(f, builtin)
         load_plugin(reg, info)
         loaded.append(info.id)
      except (manifest.ManifestError, PluginError) as e:
         reg.errors.append((str(f), str(e)))
   return loaded


def builtin_registry() -> registry.Registry:
   """!A registry holding the studio's own extensions (loaded once; later
   calls return the same object).
   @return Registry
   """
   global _BUILTIN
   if _BUILTIN is None:
      _BUILTIN = registry.Registry()
      load_folders(_BUILTIN, builtin_folders(), builtin=True)
   return _BUILTIN


def load_project_plugins(reg: registry.Registry, world_path: str | Path,
                         previous: Iterable[str] = ()) -> tuple[list[str], Path | None]:
   """!Loads the plugins of the project a world belongs to, after dropping
   the ones a previously opened project loaded.
   @param reg         Registry
   @param world_path  world.json
   @param previous    ids loaded for the previous world
   @return (ids loaded, project.json Path or None)
   """
   reg.forget(previous)
   path, game = project.find_project(world_path)
   if path is None:
      return [], None
   try:
      folders = project.plugin_folders(path, game)
   except (OSError, ValueError) as e:
      reg.errors.append((str(path), str(e)))
      return [], path
   return load_folders(reg, folders), path
