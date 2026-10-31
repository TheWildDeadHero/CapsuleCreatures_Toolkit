"""!The World page's Behaviors panel (core.behaviors): the world's terrain classes, each solid or not, entered by
every movement mode or by some, doing nothing or sliding / jumping (ledge) / pushing the walker or (I3) being a
counter that A talks across, and (I2) with walls on some sides (one-way fences). The kinds, directions and limits are
the engine's map compiler's; every change is one undo step on the world Document (the host's run_edit())."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6 import QtWidgets

from ...core import behaviors as model
from ...core import engine
from ..panel import EditorPanel
from ..panes import split_box
from ..widgets import button, set_enabled
from .battle_common import FORM_STRETCH, LIST_STRETCH
from .record_widgets import NameChecks

if TYPE_CHECKING:
   from ...core.document import Document
   from ...core.world import Project
   from ..panel import PanelHost


class BehaviorsPanel(EditorPanel):
   """!Edits the world's behaviors."""

   ## See EditorPanel.panel_id.
   panel_id = "behaviors"
   ## See EditorPanel.title.
   title = "Behaviors"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## True while the panel fills its widgets.
      self._filling = False
      ## The chosen behavior's name, or None.
      self.selected = None
      ## The behaviors.
      self.list = QtWidgets.QListWidget()
      self.list.currentRowChanged.connect(lambda row: self._picked(row))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(QtWidgets.QLabel("Behaviors (index: the cells' behavior)"))
      left.addWidget(self.list, 1)
      left.addWidget(button("Add...", lambda: self.add_behavior(), "A new behavior, entered by every mode"))
      ## Solid: nothing enters.
      self.solid = QtWidgets.QCheckBox("solid (nothing enters)")
      self.solid.clicked.connect(lambda on: self._run("Behavior", lambda doc: model.set_solid(doc, self.selected, on)))
      ## What it does to the walker.
      self.kind = QtWidgets.QComboBox()
      self.kind.addItems(model.kinds())
      self.kind.setToolTip("slide: keeps the walker going until blocked; ledge: jumped over moving its direction "
                           "(engine N2: whatever the cell's own collision), a wall otherwise; push: a forced step; "
                           "counter (I3): A facing it talks to the object beyond")
      self.kind.activated.connect(lambda *a: self._kind_chosen())
      ## A ledge's or push's direction.
      self.direction = QtWidgets.QComboBox()
      self.direction.addItems(model.directions())
      self.direction.activated.connect(lambda *a: self._kind_chosen())
      ## I2: wall sides.
      self.walls = {d: QtWidgets.QCheckBox(d) for d in model.directions()}
      walls_row = QtWidgets.QHBoxLayout()
      for d, box in self.walls.items():
         box.setToolTip(f"A step leaving the cell {d}, or entering it from {d}, is blocked")
         box.clicked.connect(lambda *a: self._walls_changed())
         walls_row.addWidget(box)
      ## Every mode that lets it in.
      self.every = QtWidgets.QCheckBox("every movement mode")
      self.every.clicked.connect(lambda on: self._run("Behavior", lambda doc: model.set_passable(
         doc, self.selected, None if on else self.passable.checked())))
      ## The modes that enter it.
      self.passable = NameChecks(lambda names: self._run("Behavior", lambda doc: model.set_passable(
         doc, self.selected, names)))
      ## The engine's verdict (the world's compile, on Validate).
      self.note = QtWidgets.QLabel("Maps name behaviors in their behavior dictionaries; World > Validate compiles "
                                   "the world as the build does.")
      self.note.setWordWrap(True)
      form = QtWidgets.QFormLayout()
      form.addRow("", self.solid)
      form.addRow("Does", self.kind)
      form.addRow("Direction", self.direction)
      form.addRow("Walls (I2)", walls_row)
      form.addRow("Entered by", self.every)
      form.addRow("", self.passable)
      right = QtWidgets.QVBoxLayout()
      right.addLayout(form)
      right.addStretch(1)
      right.addWidget(self.note)
      lay = QtWidgets.QHBoxLayout(self)
      lay.addLayout(left, LIST_STRETCH)
      lay.addLayout(right, FORM_STRETCH)
      split_box(lay)   # [RZ] list | form: the user drags the boundary

   def world(self) -> Document | None:
      """!The world Document.
      @return Document, or None
      """
      p: Project | None = self.host_project()
      return p.world if p is not None else None

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the world file.
      @return Document, or None
      """
      return self.world()

   def rows(self) -> list[dict[str, Any]]:
      """!The behaviors.
      @return core.behaviors.rows() ([] with no world)
      """
      doc = self.world()
      return model.rows(doc) if doc is not None else []

   def refresh(self) -> None:
      """!Re-reads the behaviors.
      @return None
      """
      rows = self.rows()
      names = [r["name"] for r in rows]
      if self.selected not in names:
         self.selected = names[0] if names else None
      self._filling = True
      try:
         self.list.clear()
         self.list.addItems([f"{r['index']} {r['name']}" for r in rows])
         if self.selected in names:
            self.list.setCurrentRow(names.index(self.selected))
      finally:
         self._filling = False
      self._fill_form()
      set_enabled(self, self.world() is not None)

   def _picked(self, row: int) -> None:
      """!Another behavior was picked.
      @param row  list row
      @return None
      """
      if self._filling is True:   # (Doxygen 1.12 reads `self.x:` as a declaration)
         return
      rows = self.rows()
      self.selected = rows[row]["name"] if 0 <= row < len(rows) else None
      self._fill_form()

   def _fill_form(self) -> None:
      """!Shows the chosen behavior.
      @return None
      """
      row = next((r for r in self.rows() if r["name"] == self.selected), None)
      if row is None:
         return
      self._filling = True
      try:
         self.solid.setChecked(row["solid"])
         self.kind.setCurrentText(row["kind"])
         self.direction.setCurrentText(row["direction"] or model.directions()[0])
         self.direction.setEnabled(row["kind"] not in model.UNDIRECTED + (model.NO_KIND,))
         for d, box in self.walls.items():
            box.setChecked(d in row["walls"])
         self.every.setChecked(row["passable"] is None)
         doc = self.world()
         modes = [str(n) for n in engine.tool("map_compiler").vehicle_class_names(doc.data)] if doc else []
         self.passable.set_names(modes, row["passable"] or [])
         set_enabled(self.passable, row["passable"] is not None)   # read-only, still scrolling
      finally:
         self._filling = False

   def _run(self, label: str, fn: Callable[[Document], object]) -> bool:
      """!One change of the world through the host.
      @param label  undo label
      @param fn     callable(world Document)
      @return True when it went through
      """
      doc = self.world()
      if self._filling:
         return False
      if doc is None or self.selected is None:
         return self.explain(label, "behavior")
      ok = self.host.run_edit(label, lambda: fn(doc), doc)
      if not ok:
         self.refresh()
      return ok

   def _kind_chosen(self) -> None:
      """!The kind or its direction changed.
      @return None
      """
      kind, direction = self.kind.currentText(), self.direction.currentText()
      self._run("Behavior", lambda doc: model.set_kind(doc, self.selected, kind, direction))

   def _walls_changed(self) -> None:
      """!A wall box changed.
      @return None
      """
      sides = [d for d, box in self.walls.items() if box.isChecked()]
      self._run("Behavior walls", lambda doc: model.set_walls(doc, self.selected, sides))

   def add_behavior(self, name: str | None = None) -> bool:
      """!Adds a behavior (asks its name when none is given).
      @param name  the name, or None to ask
      @return True when added
      """
      doc = self.world()
      if doc is None:
         return self.explain("Add behavior")
      if name is None:
         text, ok = QtWidgets.QInputDialog.getText(self, "Add behavior", "Name:")
         if not ok or not text.strip():
            return False
         name = text.strip()
      if self.host.run_edit("Add behavior", lambda: model.add_behavior(doc, name), doc):
         self.selected = name
         self.refresh()
         return True
      return False

   def stop(self) -> None:
      """!Nothing pending: edits apply immediately.
      @return None
      """
      pass
