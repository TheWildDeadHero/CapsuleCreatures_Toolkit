"""!Registers the map events editor with the plugin host."""
from __future__ import annotations

from typing import TYPE_CHECKING

from capsule_studio.plugins import registry
from capsule_studio.core import events

from . import commands, maptools

if TYPE_CHECKING:
   from capsule_studio.core.world import Project
   from capsule_studio.plugins import Diagnostic
   from capsule_studio.plugins.registry import ExtensionContext
   from capsule_studio.ui.world_shell import WorldWindow

   from .panel import EventsPanel


def _panel(host: WorldWindow) -> EventsPanel:
   """!Builds the Events panel (Qt is imported here, by UI hosts only).
   @param host  PanelHost
   @return EventsPanel
   """
   from .panel import EventsPanel
   return EventsPanel(host)


def _validate(project: Project, map_name: str | None) -> list[Diagnostic]:
   """!Event diagnostics.
   @param project   Project
   @param map_name  one map, or None for the whole world
   @return list of Diagnostic
   """
   return events.diagnostics(project, map_name)


def register(ctx: ExtensionContext) -> None:
   """!Adds the panel, the map tool, the overlay, hover text, the commands and the validator.
   @param ctx  ExtensionContext
   @return None
   """
   ctx.add_panel("events", "Events", _panel, hosts=("event-editor", registry.STUDIO))
   ctx.add_map_tool(maptools.EventTool())
   ctx.add_map_overlay(maptools.EventOverlay())
   ctx.add_hover_text(maptools.hover_text)
   ctx.add_validator(_validate)
   commands.register(ctx)
