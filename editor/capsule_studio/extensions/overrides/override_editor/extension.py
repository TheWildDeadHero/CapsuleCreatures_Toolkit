"""!Registers the cell override sets editor with the plugin host (S3)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from capsule_studio.core import override_sets
from capsule_studio.plugins import registry

from . import commands, maptools

if TYPE_CHECKING:
   from capsule_studio.core.world import Project
   from capsule_studio.plugins import Diagnostic
   from capsule_studio.plugins.registry import ExtensionContext
   from capsule_studio.ui.world_shell import WorldWindow

   from .panel import OverrideSetsPanel


def _panel(host: WorldWindow) -> OverrideSetsPanel:
   """!Builds the Override sets panel (Qt is imported here, by UI hosts only).
   @param host  PanelHost
   @return OverrideSetsPanel
   """
   from .panel import OverrideSetsPanel
   return OverrideSetsPanel(host)


def _validate(project: Project, map_name: str | None) -> list[Diagnostic]:
   """!Override set diagnostics.
   @param project   Project
   @param map_name  one map, or None for the whole world
   @return list of Diagnostic
   """
   return override_sets.diagnostics(project, map_name)


def register(ctx: ExtensionContext) -> None:
   """!Adds the panel, the map tool, the overlay, hover text, the commands and the validator.
   @param ctx  ExtensionContext
   @return None
   """
   ctx.add_panel("overrides", "Override sets", _panel, hosts=(registry.MAP_EDITOR, registry.STUDIO))
   ctx.add_map_tool(maptools.OverrideTool())
   ctx.add_map_overlay(maptools.OverrideOverlay())
   ctx.add_hover_text(maptools.hover_text)
   ctx.add_validator(_validate)
   commands.register(ctx)
