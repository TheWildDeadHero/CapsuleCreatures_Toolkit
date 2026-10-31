"""!The studio's map events extension (B-3): warps, triggers, signs, area
roots and step hooks.

  - extension.py: register(ctx), what the extension adds
  - commands.py:  the `capsule-studio events ...` command group
  - maptools.py:  the Events map tool, the overlay and hover text (no Qt)
  - panel.py:     the Events panel (PySide6; imported only by UI hosts)

The editing logic is the studio's core (capsule_studio.core.events); this
package is the user-facing part. Modules import each other relatively.
"""
