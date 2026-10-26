"""!The studio's extension host (D-10).

Plugins extend the tools without forking them. This studio hosts the
**extension** kind (data-specific editing): panels, map tools, map
overlays, hover text, command-line commands and validators, registered
through an ExtensionContext (registry.py). Connectors (compiler-side data,
D-10 §4) are not hosted yet; the loader refuses them with a message.

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
from .registry import API, Diagnostic, MapOverlay, MapTool, Registry  # noqa: F401
from .view import MapView  # noqa: F401
