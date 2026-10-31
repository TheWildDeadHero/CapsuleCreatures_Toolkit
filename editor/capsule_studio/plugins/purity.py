"""!The pure-Python rule for plugins (D-10 §2).

A plugin may use only pure-Python code: the standard library, the studio's
API, other plugins and pure-Python packages (py3-none-any wheels). Three
checks enforce it:

  - check_folder(): no native binaries (extension modules, shared
    libraries) and no wheels other than py3-none-any anywhere in the
    plugin's folder;
  - check_sources(): no plugin source imports ctypes or cffi (an import of
    a module already loaded by the studio would not reach the import hook);
  - ImportGuard: while installed, code inside a plugin folder cannot import
    a compiled extension module (other than the standard library's own and
    the studio's PySide6), ctypes or cffi (catches dynamic imports).

Connector code (builds run headless) may import only the standard library
and the studio's core API; check_sources(connector=True) also refuses Qt.
Every error names the plugin and the file.
"""
from __future__ import annotations

import ast
import importlib.machinery
import sys
import sysconfig
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import ModuleType

## Native module and library suffixes refused in plugin folders.
NATIVE_SUFFIXES = tuple(sorted(set(importlib.machinery.EXTENSION_SUFFIXES) |
                               {".so", ".pyd", ".dylib", ".dll", ".a", ".lib", ".o"}))
## Modules that load native code, refused from plugin code.
NATIVE_LOADERS = ("ctypes", "_ctypes", "cffi", "_cffi_backend")
## Modules connector code must not import (headless builds have no Qt).
UI_MODULES = ("PySide6", "shiboken6", "PyQt5", "PyQt6")
## Compiled packages the studio itself provides; extensions draw their UI with them (D-10).
HOST_PACKAGES = ("PySide6", "shiboken6")
## Folders of the standard library (its own compiled modules are allowed).
STDLIB_DIRS = tuple(Path(p).resolve() for p in {sysconfig.get_paths().get("stdlib"),
                                                 sysconfig.get_paths().get("platstdlib")} if p)
## Frames above ImportGuard._caller_plugin() to start from (skipping it and find_spec()).
CALLER_FRAME_DEPTH = 2
## Slice of Path.parts holding the name of a file's folder.
FOLDER_NAME_PARTS = slice(-2, -1)


class PurityError(Exception):
   """!A plugin breaks the pure-Python rule; the message names the plugin and the file."""
   pass


def _is_native(path: Path) -> bool:
   """!Whether a file is a native binary by name.
   @param path  Path
   @return bool
   """
   name = path.name.lower()
   return any(name.endswith(s) for s in NATIVE_SUFFIXES) or ".so." in name


def check_folder(plugin_id: str, folder: str | Path) -> None:
   """!Refuses native binaries and platform wheels in a plugin folder.
   @param plugin_id  for messages
   @param folder     the plugin's folder
   @return None
   """
   folder = Path(folder)
   for f in sorted(folder.rglob("*")):
      if not f.is_file() or "__pycache__" in f.parts:
         continue
      rel = f.relative_to(folder).as_posix()   # messages read the same on every system
      if _is_native(f):
         raise PurityError(f"plugin {plugin_id}: {rel} is a native binary; plugins are pure Python only (D-10)")
      if f.suffix == ".whl" and not f.name.endswith("-py3-none-any.whl"):
         raise PurityError(f"plugin {plugin_id}: {rel} is not a py3-none-any wheel; plugins take pure-Python "
                           "packages only (D-10)")


def _imports(tree: ast.Module) -> list[tuple[str, int]]:
   """!Top-level module names a source imports.
   @param tree  ast.Module
   @return list of (name, line)
   """
   out: list[tuple[str, int]] = []
   for node in ast.walk(tree):
      if isinstance(node, ast.Import):
         out.extend((a.name.split(".")[0], node.lineno) for a in node.names)
      elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
         out.append((node.module.split(".")[0], node.lineno))
      # import_module("name") and __import__("name") with a literal name count too.
      elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in (
            "import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant) \
              and isinstance(node.args[0].value, str):
         out.append((node.args[0].value.split(".")[0], node.lineno))
   return out


def check_sources(plugin_id: str, folder: str | Path, connector_files: Iterable[str | Path] = ()) -> None:
   """!Refuses ctypes / cffi in every source, and Qt in connector sources.
   @param plugin_id        for messages
   @param folder           the plugin's folder
   @param connector_files  sources belonging to the connector (Paths)
   @return None
   """
   folder = Path(folder)
   connector = {Path(p).resolve() for p in connector_files}
   for f in sorted(folder.rglob("*.py")):
      if "__pycache__" in f.parts:
         continue
      rel = f.relative_to(folder).as_posix()   # messages read the same on every system
      try:
         tree = ast.parse(f.read_text(encoding="utf-8"), str(f))
      except (SyntaxError, UnicodeDecodeError) as e:
         raise PurityError(f"plugin {plugin_id}: {rel}: {e}") from None
      for name, line in _imports(tree):
         if name in NATIVE_LOADERS:
            raise PurityError(f"plugin {plugin_id}: {rel}:{line} imports {name}; plugins may not load native "
                              "code (D-10)")
         if f.resolve() in connector and name in UI_MODULES:
            raise PurityError(f"plugin {plugin_id}: {rel}:{line} imports {name}; connectors run in headless "
                              "builds and may import only the standard library and the studio's core (D-10)")


class ImportGuard:
   """!A meta-path finder refusing native imports made from plugin code.

   Install it once (install()); add each plugin's folder with watch(). It
   only judges imports whose nearest caller outside the import machinery
   is a file inside a watched folder.
   """

   def __init__(self) -> None:
      """!Starts with no folders."""
      ## Watched folders: resolved Path -> plugin id.
      self.roots = {}

   def watch(self, plugin_id: str, folder: str | Path) -> None:
      """!Guards imports from a plugin's folder.
      @param plugin_id  plugin id
      @param folder     its folder
      @return None
      """
      self.roots[Path(folder).resolve()] = plugin_id

   def _caller_plugin(self) -> tuple[str, Path] | tuple[None, None]:
      """!The plugin whose code is importing, if any.
      @return (plugin id, file) or (None, None)
      """
      f = sys._getframe(CALLER_FRAME_DEPTH)
      # Walk out past the import machinery to the first real caller.
      while f is not None:
         name = f.f_code.co_filename
         if not name.startswith("<frozen") and "importlib" not in Path(name).parts[FOLDER_NAME_PARTS] \
                 and not name.endswith(("importlib/__init__.py", "purity.py")):
            p = Path(name).resolve() if not name.startswith("<") else None
            if p is None:
               return None, None
            for root, pid in self.roots.items():
               if root in p.parents:
                  return pid, p.relative_to(root)
            return None, None
         f = f.f_back
      return None, None

   def find_spec(self, fullname: str, path: Sequence[str] | None = None, target: ModuleType | None = None) -> None:
      """!See importlib.abc.MetaPathFinder.
      @param fullname  module being imported
      @param path      package path
      @param target    module object (reloads)
      @return None (other finders go on), or raises ImportError
      """
      if len(self.roots) == 0:   # nothing watched yet (Doxygen 1.12 misreads "not self.roots")
         return None
      pid, rel = self._caller_plugin()
      if pid is None:
         return None
      top = fullname.split(".")[0]
      if top in NATIVE_LOADERS:
         raise ImportError(f"plugin {pid}: {rel} imports {fullname}; plugins may not load native code (D-10)")
      if top in HOST_PACKAGES:
         return None
      spec = importlib.machinery.PathFinder.find_spec(fullname, path)
      if spec is not None and isinstance(spec.loader, importlib.machinery.ExtensionFileLoader) \
              and not any(d in Path(spec.origin).resolve().parents for d in STDLIB_DIRS):
         raise ImportError(f"plugin {pid}: {rel} imports {fullname}, a compiled extension module ({spec.origin}); "
                           "plugins are pure Python only (D-10)")
      return None


## The guard the loader installs.
GUARD = ImportGuard()


def install() -> None:
   """!Puts GUARD first on sys.meta_path (once).
   @return None
   """
   if GUARD not in sys.meta_path:
      sys.meta_path.insert(0, GUARD)
