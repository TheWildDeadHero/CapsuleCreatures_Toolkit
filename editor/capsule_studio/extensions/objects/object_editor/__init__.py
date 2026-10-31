"""!The studio's map objects extension (B-21, D-17): people, spotters and
pickups, with their movement (move routes included), speed, frequency,
movement options, triggers, scripts, hide flags, self switches, spotter
sight and event pages.

  - extension.py: register(ctx), what the extension adds
  - commands.py:  the `capsule-studio objects ...` command group
  - maptools.py:  the Objects map tool, the overlay and hover text (no Qt)
  - panel.py:     the Objects panel (PySide6; imported only by UI hosts)

The editing logic is the studio's core (capsule_studio.core.objects); this
package is the user-facing part. Modules import each other relatively.
"""
