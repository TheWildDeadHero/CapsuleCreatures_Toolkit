"""!The manifest designer's Qt layer (D-43 §5): one canvas window that every designer system plugs into.

  - items.py      what the canvas draws: elements (nodes with ports, shapes, frames), ports, wires and connectors,
                  and the handles that resize an element or draw a connector from it
  - canvas.py     DesignerScene and DesignerView: the grid, pan and zoom, rubber-band selection, snapping and
                  alignment guides, dragging wires (compatible ports light up), dropping palette kinds
  - palette.py    the searchable palette by category (drag a kind onto the canvas), and the add-by-typing popup
  - inspector.py  the selected element's fields, built from its kind's PropertySpecs; a link's label
  - window.py     DesignerWindow: palette, canvas, inspector and problems around them, the menus and the toolbar

Everything the canvas changes goes through core.designer.session.DesignSession, so each change is one undo step
and the same edits exist on the command line (cli/designer_cmds.py).
"""
