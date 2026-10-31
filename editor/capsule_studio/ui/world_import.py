"""!The map editor's Import dialog: pick maps and tilesets of another world;
the tilesets, sheet images and behaviors they need come along (see
core.importer)."""
from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ..core import importer
from ..core.document import DocumentError

if TYPE_CHECKING:
   from ..core.world import Project

## Width of the import dialog when it opens, pixels.
DIALOG_WIDTH = 560
## Height of the import dialog when it opens, pixels.
DIALOG_HEIGHT = 420


class ImportWorldDialog(QtWidgets.QDialog):
   """!Lists another world's maps and tilesets with check boxes and shows
   what importing the ticked ones would bring in.
   """

   def __init__(self, project: Project, source: Project, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the dialog.
      @param project  the open Project (the target)
      @param source   the other world's Project
      @param parent   parent widget
      """
      super().__init__(parent)
      ## The open world.
      self.project = project
      ## The other world.
      self.source = source
      self.setWindowTitle(f"Import from {source.world.path.parent.name}")
      ## The source's maps.
      self.map_list = self._checklist(source.map_names())
      ## The source's tilesets.
      self.tileset_list = self._checklist(source.tileset_names())
      ## What the import would do.
      self.preview = QtWidgets.QLabel()
      self.preview.setWordWrap(True)
      self.preview.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## OK / Cancel.
      self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                                QtWidgets.QDialogButtonBox.StandardButton.Cancel)
      self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Import")
      self.buttons.accepted.connect(lambda *a: self.accept())
      self.buttons.rejected.connect(lambda *a: self.reject())
      lists = QtWidgets.QHBoxLayout()
      for title, lst in (("Maps", self.map_list), ("Tilesets", self.tileset_list)):
         col = QtWidgets.QVBoxLayout()
         col.addWidget(QtWidgets.QLabel(title))
         col.addWidget(lst)
         lists.addLayout(col)
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(QtWidgets.QLabel("Tick what to import. A map brings the tilesets it draws from, their sheet "
                                     "images and the behaviors its cells use."))
      lay.addLayout(lists, 1)
      lay.addWidget(self.preview)
      lay.addWidget(self.buttons)
      self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)
      self.map_list.itemChanged.connect(lambda *a: self.update_preview())
      self.tileset_list.itemChanged.connect(lambda *a: self.update_preview())
      self.update_preview()

   def _checklist(self, names: Iterable[str]) -> QtWidgets.QListWidget:
      """!A list of check boxes.
      @param names  item texts
      @return QListWidget
      """
      lst = QtWidgets.QListWidget()
      for n in names:
         item = QtWidgets.QListWidgetItem(n)
         item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
         item.setCheckState(QtCore.Qt.CheckState.Unchecked)
         lst.addItem(item)
      return lst

   @staticmethod
   def ticked(lst: QtWidgets.QListWidget) -> list[str]:
      """!The ticked items of a list.
      @param lst  QListWidget
      @return list of texts
      """
      return [lst.item(i).text() for i in range(lst.count())
              if lst.item(i).checkState() == QtCore.Qt.CheckState.Checked]

   def choice(self) -> tuple[list[str], list[str]]:
      """!What is ticked.
      @return (map names, tileset names)
      """
      return self.ticked(self.map_list), self.ticked(self.tileset_list)

   def update_preview(self) -> None:
      """!Shows what the import would do (or why it can't).
      @return None
      """
      m, t = self.choice()
      ok = self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
      if not m and not t:
         self.preview.setText("Nothing ticked yet.")
         ok.setEnabled(False)
         return
      try:
         plan = importer.plan(self.project, self.source, m, t)
      except DocumentError as e:
         self.preview.setText(f"Can't import: {e}")
         self.preview.setStyleSheet("color: #c03030;")
         ok.setEnabled(False)
         return
      self.preview.setStyleSheet("")
      lines = []
      for name, (new, reused) in plan["tilesets"].items():
         lines.append(f"tileset {name}: " + ("already here, reused" if reused else
                                              "imported" + (f" as {new}" if new != name else "")))
      for name, new in plan["maps"].items():
         lines.append(f"map {name}: imported" + (f" as {new}" if new != name else ""))
      if plan["behaviors"]:
         lines.append("behaviors added: " + ", ".join(plan["behaviors"]))
      if plan["classes"]:
         lines.append("vehicle classes added: " + ", ".join(plan["classes"]))
      for key, names in plan["names"].items():   # F2: map tags, object kinds
         if names:
            lines.append(f"{key.replace('_', ' ')} added: " + ", ".join(names))
      lines += [n for n in plan["notes"] if "reused" not in n and "imported as" not in n]
      self.preview.setText("\n".join(lines))
      ok.setEnabled(True)
