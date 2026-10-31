"""!The studio's encounter editor extension (D-12).

  - extension.py: register(ctx), what the extension adds
  - commands.py:  the `capsule-studio encounters ...` command group
  - maptools.py:  the Encounter area brush, the overlay and hover text (no Qt)
  - panel.py:     the Encounters panel (PySide6; imported only by UI hosts)

The editing logic is the studio's core (capsule_studio.core.encounters);
this package is the user-facing part. Modules import each other
relatively (the plugin host loads the package under a private name).
"""
