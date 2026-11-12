"""!The manifest designer's core (D-43; no Qt): a drag-and-drop, UML-style view of a manifest that every system
builds on, inspired by Node-RED (palette, nodes with typed ports, wires) and draw.io (free shapes, frames, notes,
connectors, alignment and layout).

  - model.py     the diagram: elements (nodes and shapes), ports, links, element kinds, property fields,
                 diagnostics
  - system.py    DesignerSystem, what a system supplies: its palette, link rules, how its manifest reads into a
                 diagram and writes back, its checks, live values; the shared shapes and the editor block
  - registry.py  the systems (built-in ones; plugins later), found by id or by manifest schema
  - ops.py       the edits every system shares: add, remove, move, resize, set, connect, disconnect, frames,
                 duplicate, align, distribute, same size
  - checks.py    the checks every system gets: link types, port capacity, required ports, cycles, references
  - layout.py    auto-layout (layered, in the system's direction) and the grid
  - session.py   DesignSession: a system on a Document; every edit is one Document step (undo, unsaved marks,
                 Save all) and the diagram is read back from the manifest
  - sample_flow.py  the dev-only Sample flow system on invented data, which exercises every base feature

The manifest is the only source of truth: a diagram is read from it and written back into it, and positions, notes
and frames that the manifest has no place for go into its "editor" block (under "designer"), which compilers drop.
The canvas (ui/designer) and the command line (cli/designer_cmds.py) both edit through DesignSession.
"""
