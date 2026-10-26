"""!Editor logic without any user interface (no Qt import anywhere below).

Used by the Qt panels, the command line and scripts alike:
  - engine:       finds the engine checkout and its build tools
  - manifest_io:  reads and writes manifest JSON
  - document:     a manifest being edited (undo, unsaved images, validation)
  - imaging:      fitting imported bitmaps to a sprite
  - sprites:      frames, animations, frame durations
  - texts:        text assets and credits pages
  - preview:      screen previews drawn like the engine
"""
