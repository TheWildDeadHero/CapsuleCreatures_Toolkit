"""!The manifest designer's systems (D-43 §4): the built-in ones, found by id or by the schema of the manifest they
edit. Registering a system also lets a core.document.Document hold its schema (with the system's empty manifest).

Built-in systems are listed in BUILTIN and imported on first use. Plugin API 3 (a later milestone) will add
systems from plugins through register().
"""
from __future__ import annotations

import importlib

from .. import document
from .model import ModelError
from .system import DesignerSystem

## Built-in systems: module (in this package) and class.
BUILTIN = (("sample_flow", "SampleFlowSystem"),)

## Registered systems by id.
_SYSTEMS: dict[str, DesignerSystem] = {}
## Whether BUILTIN has been imported.
_LOADED = {"builtin": False}


def register(system: DesignerSystem) -> None:
   """!Adds a system.
   @param system  the system (its system_id and schema must be new)
   @return None
   @throws ModelError when its id or schema is taken, or missing
   """
   if not system.system_id or not system.schema:
      raise ModelError(f"{type(system).__name__} needs a system_id and a schema")
   if system.system_id in _SYSTEMS:
      raise ModelError(f"a designer system {system.system_id!r} is registered already")
   if any(s.schema == system.schema for s in _SYSTEMS.values()):
      raise ModelError(f"a designer system for {system.schema} is registered already")
   _SYSTEMS[system.system_id] = system
   document.register_schema(system.schema, system.empty())


def _load_builtin() -> None:
   """!Registers BUILTIN once.
   @return None
   """
   if _LOADED["builtin"]:
      return
   _LOADED["builtin"] = True
   for module_name, class_name in BUILTIN:
      module = importlib.import_module(f"{__package__}.{module_name}")
      register(getattr(module, class_name)())


def systems(include_dev: bool = True) -> list[DesignerSystem]:
   """!Every registered system, by title.
   @param include_dev  whether dev-only systems (Sample flow) are listed
   @return systems
   """
   _load_builtin()
   return sorted((s for s in _SYSTEMS.values() if include_dev or not s.dev_only), key=lambda s: s.title)


def get(system_id: str) -> DesignerSystem:
   """!A system by id.
   @param system_id  its id
   @return the system
   @throws ModelError when there is none
   """
   _load_builtin()
   found = _SYSTEMS.get(system_id)
   if found is None:
      raise ModelError(f"no designer system {system_id!r} (there are " + ", ".join(sorted(_SYSTEMS)) + ")")
   return found


def for_schema(schema: str) -> DesignerSystem:
   """!The system that edits a manifest schema.
   @param schema  e.g. "capsule.sampleflow/1"
   @return the system
   @throws ModelError when none does
   """
   _load_builtin()
   found = next((s for s in _SYSTEMS.values() if s.schema == schema), None)
   if found is None:
      raise ModelError(f"no designer system edits {schema!r} (they edit "
                       + ", ".join(sorted(s.schema for s in _SYSTEMS.values())) + ")")
   return found
