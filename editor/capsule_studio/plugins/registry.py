"""!What extensions register (D-10 §5), and the context they register through.

An extension module defines register(ctx), called once when the plugin
loads; ctx is an ExtensionContext. Registration points:

  - panels: an EditorPanel (see ui/panel.py) a host shows as a tab. The
    factory is called with the host, so Qt is imported only by hosts that
    show panels (the command line never does). Hosts are named by id:
    "map-editor" (the map editor, MAP_EDITOR), a standalone tool's own id
    (e.g. "encounter-editor") and "studio" (STUDIO, the combined Studio
    window). The Studio's world page shows the panels of both STUDIO_HOSTS,
    so a panel registered for the map editor also shows there.
  - map tools: a MapTool, a button in the map panel's toolbar after the
    built-in tools; its stroke is applied as one document command.
  - map overlays: a MapOverlay drawn over painted cells, picked in the map
    panel's Overlay chooser.
  - hover text: text the map panel adds to the hovered cell's line.
  - commands: `capsule-studio <plugin> <command>` (the studio's own
    extensions may use a short group name, plugin.json "cli").
  - validators: live diagnostics over the project (or one map of it),
    shown by the map panel and by `capsule-studio world validate`.
  - battle templates (plugin API 2, D-23 section 3.5): a template folder
    (template.json, capsule.template/1) the New game / New battle data
    dialog and `capsule-studio template list` offer (core.templates).
  - designer systems (plugin API 3): a system of the manifest designer
    (its node kinds and how a diagram reads and writes a manifest), shown
    by the designer as one of its systems.
  - file formats (plugin API 3): a FileFormat that exports a plugin's
    connector data to a file and imports it back (Plugin data > Import /
    Export, `capsule-studio ext export` / `ext import`).
  - previews (plugin API 3): a Preview that shows a record's connector data
    as text beside the Plugin data inspector (`capsule-studio ext preview`).

A plugin's connector (plugin API 3, the engine's tools/connectors.py)
declares typed data blocks at attach points; the Studio builds the Plugin
data inspector from those declarations and runs the connector's checks
live (core.plugin_data). Plugin API 2 adds battle templates to API 1 and
API 3 adds connectors, designer systems, formats and previews; a plugin
written for an older API loads unchanged (loader: MIN_API to API).

Map tools and overlays receive a view.MapView: the project, the map and
edit(), which runs a change as a document command (undo, redo, dirty
tracking and saving work as for built-in edits). Extensions never write
project files themselves. Everything an extension offers in a panel must
also exist as a command (command-line parity), so it can be scripted and
tested without Qt.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
   from PySide6 import QtWidgets

   from ..core.world import Project
   from ..ui.panel import EditorPanel
   from .manifest import PluginInfo
   from .view import MapView

## Plugin API number this studio implements (plugin.json "api"; 2: battle templates; 3: connectors, designer
## systems, formats and previews).
API = 3
## Oldest plugin API with connectors (plugin.json "connector").
CONNECTOR_API = 3
## Oldest plugin API number this studio still loads (each API adds registration points; none was removed).
MIN_API = 1
## Host id of the map editor (the default host of a panel).
MAP_EDITOR = "map-editor"
## Host id of the combined Studio window.
STUDIO = "studio"
## Host ids whose panels the Studio's world page shows.
STUDIO_HOSTS = (STUDIO, MAP_EDITOR)
## Stroke kinds a map tool can ask for.
STROKES = ("line", "rect", "click")

## A map cell position: (x, y).
CellPosition = tuple[int, int]
## A color with alpha: (r, g, b, a).
Rgba = tuple[int, int, int, int]
## What an overlay draws on one cell: callable(x, y, attribute cell or None) -> (rgba or None, text or None).
OverlayCell = Callable[[int, int, int | None], tuple[Rgba | None, str | None]]
## Hover text: callable(view, x, y, attribute cell or None) -> text or None.
HoverText = Callable[["MapView", int, int, int | None], str | None]
## A validator: callable(project, map name or None) -> Diagnostics (or None for none).
Validator = Callable[["Project", str | None], "Iterable[Diagnostic] | None"]


class RegistrationError(Exception):
   """!An extension registered something invalid; the message names the plugin."""
   pass


class MapTool:
   """!A map panel tool. Subclass and set the class attributes."""

   ## Unique id (plugin-prefixed by the registry: "plugin/id").
   id = "tool"
   ## Button text.
   label = "Tool"
   ## Button tooltip.
   tooltip = ""
   ## How cells are collected before apply(): "line" (drag paints a line of cells), "rect" (drag a rectangle) or
   ## "click" (one cell).
   stroke = "line"

   def apply(self, view: MapView, cells: list[CellPosition]) -> None:
      """!Applies one stroke (call view.edit() to change the map).
      @param view   view.MapView
      @param cells  list of (x, y)
      @return None
      """
      raise NotImplementedError

   def options(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget | None:
      """!Optional settings widget shown while the tool is chosen (Qt; called by UI hosts only).
      @param parent  QWidget
      @return QWidget, or None
      """
      return None


class MapOverlay:
   """!Something drawn over a map's painted cells."""

   ## Unique id (plugin-prefixed by the registry).
   id = "overlay"
   ## Name in the Overlay chooser.
   title = "Overlay"

   def prepare(self, view: MapView) -> OverlayCell:
      """!Called once per repaint; returns the per-cell function.
      @param view  view.MapView
      @return callable(x, y, cell) -> (rgba tuple or None, short text or None)
      """
      raise NotImplementedError


class FileFormat:
   """!Exchanges a plugin's connector data with a file (plugin API 3). Subclass, set the class attributes and
   override export_data(), import_data() or both. Both work on a core.plugin_data.PluginData: export reads the
   blocks, import returns the changes, which the host applies as one undo step (the command line saves them)."""

   ## Unique id (plugin-prefixed by the registry: "plugin/id").
   id = "format"
   ## Name in menus and lists.
   title = "Format"
   ## File name suffix, with its dot (".csv").
   suffix = ".txt"
   ## The plugin whose blocks it exchanges (default: the plugin that registers it).
   plugin = ""

   def export_data(self, data: Any) -> str:
      """!The file's text.
      @param data  core.plugin_data.PluginData
      @return the text
      """
      raise NotImplementedError

   def import_data(self, data: Any, text: str) -> list[tuple[str, str, Any]]:
      """!The changes a file makes.
      @param data  core.plugin_data.PluginData (to read the blocks there now)
      @param text  the file's text
      @return [(attach point, record name, block or None to remove it)]
      @throws ValueError with a message when the file cannot be read
      """
      raise NotImplementedError

   def can_export(self) -> bool:
      """!Whether it overrides export_data().
      @return True when it can export
      """
      return type(self).export_data is not FileFormat.export_data

   def can_import(self) -> bool:
      """!Whether it overrides import_data().
      @return True when it can import
      """
      return type(self).import_data is not FileFormat.import_data


class Preview:
   """!Shows a record's connector data as text (plugin API 3), beside the Plugin data inspector."""

   ## Unique id (plugin-prefixed by the registry).
   id = "preview"
   ## Its heading.
   title = "Preview"
   ## The plugin whose blocks it shows (default: the plugin that registers it).
   plugin = ""
   ## Attach points it shows (empty: every point of the plugin).
   attach_points: tuple[str, ...] = ()

   def render(self, data: Any, attach: str, name: str, block: Any) -> str:
      """!The preview.
      @param data    core.plugin_data.PluginData
      @param attach  the record's attach point
      @param name    the record's name
      @param block   its block with the defaults filled in (as the inspector shows it)
      @return text (a few lines)
      """
      raise NotImplementedError


@dataclass
class DesignerSystemSpec:
   """!A registered manifest designer system (plugin API 3)."""
   ## Plugin id.
   plugin: str
   ## System id (plugin-prefixed).
   system_id: str
   ## Name in the designer's system list.
   title: str
   ## callable() -> the system (the designer's DesignerSystem; it is imported by the designer, never here).
   factory: Callable[[], Any]


@dataclass
class PanelSpec:
   """!A registered panel."""
   ## Plugin id.
   plugin: str
   ## Panel id (--panel on the command line).
   panel_id: str
   ## Tab title.
   title: str
   ## callable(host) -> EditorPanel.
   factory: Callable[[Any], EditorPanel]
   ## Host ids that show it ("map-editor", ...).
   hosts: tuple[str, ...]
   ## callable(registry) -> whether hosts show it now (None: always).
   shown_if: Callable[[Registry], bool] | None = None


@dataclass
class Command:
   """!A registered command."""
   ## Plugin id.
   plugin: str
   ## Command group (the plugin's cli name).
   group: str
   ## Command name.
   name: str
   ## One-line help.
   help: str
   ## callable(argparse parser) adding arguments.
   setup: Callable[[argparse.ArgumentParser], object]
   ## callable(args) -> exit status or None.
   run: Callable[[argparse.Namespace], int | None]


@dataclass
class Diagnostic:
   """!One validator finding."""
   ## "error", "warning" or "info".
   level: str
   ## What is wrong.
   message: str
   ## Map name it concerns, or None.
   map: str | None = None
   ## (x, y) cell, or None.
   at: CellPosition | None = None
   ## Plugin that reported it (set by the registry).
   plugin: str = field(default="")


class Registry:
   """!Everything loaded plugins registered."""

   def __init__(self) -> None:
      """!Starts empty."""
      ## Loaded plugins: id -> manifest.PluginInfo.
      self.plugins = {}
      ## Load problems: (plugin folder or id, message).
      self.errors = []
      ## Contributions: (kind, plugin id, object).
      self._items = []

   def add(self, kind: str, plugin: str, obj: Any) -> None:
      """!Records a contribution.
      @param kind    "panel", "tool", "overlay", "hover", "command", "validator", "template", "designer", "format",
                     "preview"
      @param plugin  plugin id
      @param obj     the contribution
      @return None
      """
      self._items.append((kind, plugin, obj))

   def _of(self, kind: str) -> list[Any]:
      """!Contributions of a kind, in load order.
      @param kind  kind name
      @return list
      """
      return [o for k, _p, o in self._items if k == kind]

   def panels(self, host_id: str | Iterable[str]) -> list[PanelSpec]:
      """!Panels a host shows.
      @param host_id  e.g. "map-editor", or several ids (a panel registered for any of them)
      @return list of PanelSpec
      """
      ids = {host_id} if isinstance(host_id, str) else set(host_id)
      return [p for p in self._of("panel") if ids & set(p.hosts) and (p.shown_if is None or p.shown_if(self))]

   def map_tools(self) -> list[MapTool]:
      """!Registered map tools.
      @return list of MapTool
      """
      return self._of("tool")

   def map_overlays(self) -> list[MapOverlay]:
      """!Registered overlays.
      @return list of MapOverlay
      """
      return self._of("overlay")

   def hover_texts(self) -> list[HoverText]:
      """!Registered hover text functions.
      @return list of callable(view, x, y, cell) -> str or None
      """
      return self._of("hover")

   def commands(self) -> list[Command]:
      """!Registered commands.
      @return list of Command
      """
      return self._of("command")

   def validate(self, project: Project, map_name: str | None = None) -> list[Diagnostic]:
      """!Runs every validator.
      @param project   core.world.Project
      @param map_name  only findings about this map (and the world as a whole), or None for everything
      @return list of Diagnostic (a validator that raises reports one error)
      """
      out: list[Diagnostic] = []
      items = self._items   # a local alias (Doxygen 1.12 reads the loop's member as a new one)
      for k, pid, fn in items:
         if k != "validator":
            continue
         try:
            found = list(fn(project, map_name) or [])
         except Exception as e:   # a broken validator must not break the editor
            found = [Diagnostic("error", f"validator failed: {e}")]
         for d in found:
            d.plugin = d.plugin or pid   # a validator reporting for other plugins names them (plugin data)
         out.extend(found)
      return out

   def connectors(self) -> list[str]:
      """!Ids of the loaded plugins with a connector (plugin API 3).
      @return ids in load order
      """
      return [pid for pid, info in self.plugins.items() if info.connector is not None]

   def designer_systems(self) -> list[DesignerSystemSpec]:
      """!Registered manifest designer systems.
      @return list in load order
      """
      return self._of("designer")

   def formats(self, plugin_id: str | None = None) -> list[FileFormat]:
      """!Registered file formats.
      @param plugin_id  only those exchanging this plugin's blocks, or None for all
      @return list in load order
      """
      return [f for f in self._of("format") if plugin_id is None or f.plugin == plugin_id]

   def previews(self, plugin_id: str | None = None, attach: str | None = None) -> list[Preview]:
      """!Registered previews.
      @param plugin_id  only those of this plugin's blocks, or None
      @param attach     only those showing this attach point, or None
      @return list in load order
      """
      return [p for p in self._of("preview") if (plugin_id is None or p.plugin == plugin_id)
              and (attach is None or not p.attach_points or attach in p.attach_points)]

   def find(self, kind: str, item_id: str) -> Any:
      """!A registered format or preview by id ("plugin/id", or the id alone when only one plugin uses it).
      @param kind     "format" or "preview"
      @param item_id  its id
      @return the object, or None
      """
      items = self._of(kind)
      exact = [o for o in items if o.id == item_id]
      short = [o for o in items if o.id.split("/", 1)[-1] == item_id]
      found = exact or short
      return found[0] if len(found) == 1 else None

   def battle_templates(self) -> list[tuple[str, Path]]:
      """!Registered battle template folders.
      @return [(plugin id, template folder)] in load order
      """
      return [(pid, path) for k, pid, path in self._items if k == "template"]

   def copy(self) -> Registry:
      """!A registry holding the same plugins and contributions (to add more without changing this one).
      @return Registry
      """
      r = Registry()
      r.plugins = dict(self.plugins)
      r.errors = list(self.errors)
      r._items = list(self._items)
      return r

   def forget(self, plugin_ids: Iterable[str]) -> None:
      """!Drops what some plugins registered (a project with other plugins was opened).
      @param plugin_ids  ids
      @return None
      """
      ids = set(plugin_ids)
      self._items = [i for i in self._items if i[1] not in ids]
      for pid in ids:
         self.plugins.pop(pid, None)


class ExtensionContext:
   """!Passed to an extension's register(ctx).

   @var api
   The plugin API number (registry.API).
   @var plugin
   This plugin's manifest.PluginInfo.
   """

   def __init__(self, registry: Registry, info: PluginInfo, studio_version: str) -> None:
      """!Binds a plugin to the registry.
      @param registry        Registry
      @param info            manifest.PluginInfo
      @param studio_version  the studio's calendar version
      """
      ## The registry the plugin adds to.
      self._r = registry
      self.plugin = info
      self.api = API
      ## The studio's calendar version.
      self.studio_version = studio_version

   def _ident(self, obj: MapTool | MapOverlay | FileFormat | Preview, kind: str) -> None:
      """!Checks and prefixes a contribution id.
      @param obj   MapTool, MapOverlay, FileFormat or Preview
      @param kind  for messages
      @return None
      """
      if not isinstance(getattr(obj, "id", None), str) or not obj.id:
         raise RegistrationError(f"plugin {self.plugin.id}: a {kind} needs an id")
      if "/" not in obj.id:
         obj.id = f"{self.plugin.id}/{obj.id}"

   def add_panel(self, panel_id: str, title: str, factory: Callable[[Any], EditorPanel],
                 hosts: Iterable[str] = (MAP_EDITOR,), shown_if: Callable[[Registry], bool] | None = None) -> None:
      """!Registers a panel.
      @param panel_id  id (unique; used by --panel)
      @param title     tab title
      @param factory   callable(host) -> EditorPanel (import Qt inside it)
      @param hosts     host ids (MAP_EDITOR, a standalone tool's id, STUDIO)
      @param shown_if  callable(registry) -> whether hosts show it (asked whenever a project's plugins load), or
                       None for always
      @return None
      """
      if any(p.panel_id == panel_id for p in self._r._of("panel")):
         raise RegistrationError(f"plugin {self.plugin.id}: panel id {panel_id!r} is taken")
      spec = PanelSpec(self.plugin.id, panel_id, title, factory, tuple(hosts), shown_if)
      self._r.add("panel", self.plugin.id, spec)

   def add_map_tool(self, tool: MapTool) -> None:
      """!Registers a map tool.
      @param tool  MapTool
      @return None
      """
      if not isinstance(tool, MapTool):
         raise RegistrationError(f"plugin {self.plugin.id}: map tools subclass registry.MapTool")
      if tool.stroke not in STROKES:
         raise RegistrationError(f"plugin {self.plugin.id}: stroke must be one of {', '.join(STROKES)}")
      self._ident(tool, "map tool")
      self._r.add("tool", self.plugin.id, tool)

   def add_map_overlay(self, overlay: MapOverlay) -> None:
      """!Registers an overlay.
      @param overlay  MapOverlay
      @return None
      """
      if not isinstance(overlay, MapOverlay):
         raise RegistrationError(f"plugin {self.plugin.id}: overlays subclass registry.MapOverlay")
      self._ident(overlay, "overlay")
      self._r.add("overlay", self.plugin.id, overlay)

   def add_hover_text(self, fn: HoverText) -> None:
      """!Registers hover text.
      @param fn  callable(view, x, y, cell) -> str or None (cell is the attribute cell, or None)
      @return None
      """
      self._r.add("hover", self.plugin.id, fn)

   def add_command(self, name: str, help: str, setup: Callable[[argparse.ArgumentParser], object],
                   run: Callable[[argparse.Namespace], int | None]) -> None:
      """!Registers `capsule-studio <group> <name>`.
      @param name   command name
      @param help   one line
      @param setup  callable(parser) adding arguments
      @param run    callable(args) -> exit status or None
      @return None
      """
      group = self.plugin.cli
      if any(c.group == group and c.name == name for c in self._r.commands()):
         raise RegistrationError(f"plugin {self.plugin.id}: command {group} {name} exists already")
      self._r.add("command", self.plugin.id, Command(self.plugin.id, group, name, help, setup, run))

   def add_battle_template(self, path: str | Path) -> None:
      """!Registers a battle template (plugin API 2): a folder with a template.json (capsule.template/1), read
      by core.templates.load() now, so a bad one is refused when the plugin loads.
      @param path  the folder or its template.json, relative to the plugin's folder (or absolute)
      @return None
      """
      from ..core import templates   # local: the registry stays importable without the core modules' imports
      from ..core.document import DocumentError

      folder = Path(path)
      if not folder.is_absolute():
         folder = Path(self.plugin.folder) / folder
      try:
         found = templates.load(folder, templates.PLUGIN, self.plugin.id)
      except DocumentError as e:
         raise RegistrationError(f"plugin {self.plugin.id}: {e}") from None
      if any(templates.load(other, templates.PLUGIN).id == found.id for _pid, other in self._r.battle_templates()):
         raise RegistrationError(f"plugin {self.plugin.id}: a battle template {found.id!r} is registered already")
      self._r.add("template", self.plugin.id, found.folder)

   def add_validator(self, fn: Validator) -> None:
      """!Registers a validator.
      @param fn  callable(project, map_name) -> iterable of Diagnostic; map_name None means the whole
                 world, otherwise only that map's findings are wanted (the map panel asks per map)
      @return None
      """
      self._r.add("validator", self.plugin.id, fn)

   def _api(self, what: str) -> None:
      """!Refuses a plugin API 3 registration from a plugin written for an older API.
      @param what  what it registers, for the message
      @return None
      """
      if self.plugin.api < CONNECTOR_API:
         raise RegistrationError(f"plugin {self.plugin.id}: {what} need plugin API {CONNECTOR_API} (plugin.json "
                                 f"\"api\" is {self.plugin.api})")

   def add_designer_system(self, system_id: str, title: str, factory: Callable[[], Any]) -> None:
      """!Registers a manifest designer system (plugin API 3).
      @param system_id  id (prefixed with the plugin's id)
      @param title      name in the designer's system list
      @param factory    callable() -> the system (import the designer inside it)
      @return None
      """
      self._api("designer systems")
      full = system_id if "/" in system_id else f"{self.plugin.id}/{system_id}"
      if not system_id or any(d.system_id == full for d in self._r.designer_systems()):
         raise RegistrationError(f"plugin {self.plugin.id}: designer system {full!r} needs a new id")
      self._r.add("designer", self.plugin.id, DesignerSystemSpec(self.plugin.id, full, title, factory))

   def add_format(self, fmt: FileFormat) -> None:
      """!Registers a file format (plugin API 3).
      @param fmt  FileFormat (export_data(), import_data() or both)
      @return None
      """
      self._api("file formats")
      if not isinstance(fmt, FileFormat):
         raise RegistrationError(f"plugin {self.plugin.id}: file formats subclass registry.FileFormat")
      if not (fmt.can_export() or fmt.can_import()):
         raise RegistrationError(f"plugin {self.plugin.id}: format {fmt.id!r} neither exports nor imports")
      if not fmt.suffix.startswith("."):
         raise RegistrationError(f"plugin {self.plugin.id}: format {fmt.id!r}: suffix starts with a dot")
      self._ident(fmt, "file format")
      fmt.plugin = fmt.plugin or self.plugin.id
      self._r.add("format", self.plugin.id, fmt)

   def add_preview(self, preview: Preview) -> None:
      """!Registers a preview (plugin API 3).
      @param preview  Preview
      @return None
      """
      self._api("previews")
      if not isinstance(preview, Preview):
         raise RegistrationError(f"plugin {self.plugin.id}: previews subclass registry.Preview")
      self._ident(preview, "preview")
      preview.plugin = preview.plugin or self.plugin.id
      self._r.add("preview", self.plugin.id, preview)
