"""!Registers the locations editor with the plugin host."""
from __future__ import annotations

from typing import TYPE_CHECKING

from capsule_studio.plugins import registry
from capsule_studio.core import locations

from . import commands

if TYPE_CHECKING:
   from capsule_studio.core.world import Project
   from capsule_studio.plugins import Diagnostic, MapView
   from capsule_studio.plugins.registry import ExtensionContext
   from capsule_studio.ui.world_shell import WorldWindow

   from .panel import LocationsPanel


def _panel(host: WorldWindow) -> LocationsPanel:
   """!Builds the Locations panel (Qt is imported here, by UI hosts only).
   @param host  PanelHost
   @return LocationsPanel
   """
   from .panel import LocationsPanel
   return LocationsPanel(host)


def _validate(project: Project, map_name: str | None) -> list[Diagnostic]:
   """!Location diagnostics.
   @param project   Project
   @param map_name  one map, or None for the whole world
   @return list of Diagnostic
   """
   return locations.diagnostics(project, map_name)


def _hover(view: MapView, x: int, y: int, cell: int | None) -> str | None:
   """!The hovered map's location (on painted cells).
   @param view  MapView
   @param x     column
   @param y     row
   @param cell  attribute cell, or None
   @return text, or None
   """
   doc = view.doc
   if doc is None or cell is None:
      return None
   key = locations.map_location(doc)
   return f"location {key}" if key else None


def register(ctx: ExtensionContext) -> None:
   """!Adds the panel, hover text, the commands and the validator.
   @param ctx  ExtensionContext
   @return None
   """
   ctx.add_panel("locations", "Locations", _panel, hosts=("location-editor", registry.STUDIO))
   ctx.add_hover_text(_hover)
   ctx.add_validator(_validate)
   commands.register(ctx)
