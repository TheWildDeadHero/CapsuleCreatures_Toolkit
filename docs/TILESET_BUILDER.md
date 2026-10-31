# Tileset builder (planned)

**Not written yet.** The tileset builder is part of the toolkit (D-37, developer 2026-10-25); this page records
what it is and where its code will go, so the first package starts from it.

## Purpose (D-11)

A tool for artists to build tileset art from parts: they layer core pieces, each coloured by the user, into objects
such as trees and buildings, and the builder writes the result as hardware-legal sheets (4bpp 8×8 tiles and
palettes, within the display limits D-9 and C-02/C-03 set). Metatiles are still made in the map editor's metatile
maker, which reads the object regions from the builder's sheets.

The builder is generic: no franchise terms, usable for any 2D tile game. Art made with it, and the fan resources of
`ProjectHeliodor/resources` (which mix fan-made, official and third-party material), stay outside the toolkit;
test pieces are simple shapes only.

## Planned layout (the toolkit's usual split)

```
editor/capsule_studio/core/tileset_builder.py    pieces, layers, user colours and palettes, objects, sheet export (no UI import)
editor/capsule_studio/cli/tileset_builder_cmds.py the command line (build sheets in pipelines and containers)
editor/capsule_studio/ui/editors/tileset_builder.py  the PySide6 panel, in the Studio and as a standalone tool
tileset-builder, tileset-builder.cmd               launchers, like the other editors (and in the umbrella)
editor/tests/test_tileset_builder*.py              unittest suites on simple-shape pieces
```

It runs in the toolkit environment (`toolkit/env.py`) and uses the engine's bitmap and palette tools, found the way
the toolkit finds the engine. Core + command line + panel + tests ship together, as for every toolkit feature, and
the code map gets one line per file.
