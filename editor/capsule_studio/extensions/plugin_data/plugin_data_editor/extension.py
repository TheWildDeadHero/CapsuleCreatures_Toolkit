"""!Registers the plugin data editor with the plugin host."""
from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

from capsule_studio.core import plugin_data
from capsule_studio.plugins import registry

from . import commands

if TYPE_CHECKING:
   from capsule_studio.core.world import Project
   from capsule_studio.plugins import Diagnostic
   from capsule_studio.plugins.registry import ExtensionContext, Registry
   from capsule_studio.ui.world_shell import WorldWindow

   from .panel import PluginDataPanel

## The plugin data of each open Project (its checks are cached between validations).
_DATA: weakref.WeakKeyDictionary[Project, plugin_data.PluginData | None] = weakref.WeakKeyDictionary()


def _panel(host: WorldWindow) -> PluginDataPanel:
   """!Builds the Plugin data panel (Qt is imported here, by UI hosts only).
   @param host  PanelHost
   @return PluginDataPanel
   """
   from .panel import PluginDataPanel
   return PluginDataPanel(host)


def _shown(reg: Registry) -> bool:
   """!Hosts show the panel while the game has a plugin with a connector.
   @param reg  the host's registry
   @return True when one is loaded
   """
   return bool(reg.connectors())


def data_of(project: Project) -> plugin_data.PluginData | None:
   """!A Project's plugin data (one per Project, so its checks stay cached).
   @param project  core.world.Project
   @return PluginData, or None when the world is not part of a game or lists no plugin with a connector
   """
   if project not in _DATA:
      _DATA[project] = plugin_data.for_project(project)
   return _DATA[project]


def _validate(project: Project, map_name: str | None) -> list[Diagnostic]:
   """!The connectors' checks (nothing when the game has no plugin with a connector).
   @param project   Project
   @param map_name  one map, or None for the whole world
   @return list of Diagnostic
   """
   data = data_of(project)
   if data is None:
      return []
   try:
      if not data.plugins():
         return []
   except plugin_data.PluginDataError:
      pass   # diagnostics() reports it
   return data.diagnostics(map_name)


def register(ctx: ExtensionContext) -> None:
   """!Adds the panel, the validator and the commands.
   @param ctx  ExtensionContext
   @return None
   """
   ctx.add_panel("plugin-data", "Plugin data", _panel, hosts=(registry.MAP_EDITOR, registry.STUDIO), shown_if=_shown)
   ctx.add_validator(_validate)
   commands.register(ctx)
