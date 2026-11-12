"""!The studio's extension host (D-10).

Plugins extend the tools without forking them. This studio hosts the
**extension** kind (data-specific editing): panels, map tools, map
overlays, hover text, command-line commands, validators, battle templates,
designer systems, file formats and previews, registered through an
ExtensionContext (registry.py). Connectors (D-10 §4: typed data blocks a
plugin adds to the game's manifests, compiled by the engine's
tools/connectors.py) load through the engine; the Plugin data panel and
`capsule-studio ext` edit their blocks (core.plugin_data).

  - manifest.py: plugin.json (capsule.plugin/1)
  - versions.py: calendar versions, requirements, deprecation
  - purity.py:   the pure-Python rule (folder scan, source scan, import guard)
  - registry.py: registration points, MapTool, MapOverlay, Diagnostic
  - view.py:     MapView, what map tools and overlays work on
  - loader.py:   loading the studio's own extensions and a project's plugins
  - project.py:  finding a world's project.json and its "plugins"

Nothing here imports Qt: hosts with a user interface call panel factories
and tool options themselves.
"""
from .registry import API, Diagnostic, FileFormat, MapOverlay, MapTool, Preview, Registry  # noqa: F401
from .view import MapView  # noqa: F401
