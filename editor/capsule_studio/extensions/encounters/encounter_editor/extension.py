"""!Registers the encounter editor with the plugin host."""
from __future__ import annotations

from typing import TYPE_CHECKING

from capsule_studio.plugins import registry
from capsule_studio.core import encounters

from . import commands, maptools

if TYPE_CHECKING:
   from capsule_studio.core.world import Project
   from capsule_studio.plugins import Diagnostic
   from capsule_studio.plugins.registry import ExtensionContext
   from capsule_studio.ui.world_shell import WorldWindow

   from .panel import EncounterPanel


def _panel(host: WorldWindow) -> EncounterPanel:
   """!Builds the Encounters panel (Qt is imported here, by UI hosts only).
   @param host  PanelHost
   @return EncounterPanel
   """
   from .panel import EncounterPanel
   return EncounterPanel(host)


def _validate(project: Project, map_name: str | None) -> list[Diagnostic]:
   """!Encounter diagnostics.
   @param project   Project
   @param map_name  one map, or None for the whole world
   @return list of Diagnostic
   """
   return encounters.diagnostics(project, map_name)


def register(ctx: ExtensionContext) -> None:
   """!Adds the panel, the brush, the overlay, hover text, the commands and the validator.
   @param ctx  ExtensionContext
   @return None
   """
   ctx.add_panel("encounters", "Encounters", _panel, hosts=("encounter-editor", registry.STUDIO))
   ctx.add_map_tool(maptools.EncounterBrush())
   ctx.add_map_overlay(maptools.EncounterOverlay())
   ctx.add_hover_text(maptools.hover_text)
   ctx.add_validator(_validate)
   commands.register(ctx)
