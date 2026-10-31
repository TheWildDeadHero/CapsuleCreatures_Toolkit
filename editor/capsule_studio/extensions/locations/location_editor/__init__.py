"""!The studio's locations extension (D-17): the named places maps belong to,
their name banners and location previews, and the world's default warp
transition.

  - extension.py: register(ctx), what the extension adds
  - commands.py:  the `capsule-studio locations ...` command group
  - panel.py:     the Locations panel (PySide6; imported only by UI hosts)

The editing logic is the studio's core (capsule_studio.core.locations);
this package is the user-facing part. Modules import each other relatively.
"""
