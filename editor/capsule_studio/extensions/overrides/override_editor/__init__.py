"""!S3: the studio's cell override sets extension (D-30 section 2, engine DS1): named sets of cell changes scripts
apply and clear (`override apply NAME;` / `override clear NAME;`).

  - extension.py: register(ctx), what the extension adds
  - commands.py:  the `capsule-studio overrides ...` command group
  - maptools.py:  the Override sets map tool, the overlay and hover text (no Qt)
  - panel.py:     the Override sets panel (PySide6; imported only by UI hosts)

The editing logic is the studio's core (capsule_studio.core.override_sets); this package is the user-facing part.
"""
