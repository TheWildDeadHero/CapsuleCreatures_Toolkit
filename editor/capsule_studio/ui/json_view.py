"""!The read-only data view [S5]: any JSON file as a tree (core.json_view), for data files the studio has no editor
for (an imported game's importer / tier-3 data such as world/scripts/story.json, ui/menus.json,
overworld/field.json). Nothing is edited or saved.

The Studio menu's "Open data file (read-only)..." opens one; the scene editor's File > Open shows a JSON file of
another schema here instead of refusing it. Children are read when a row is first expanded (a long list shows
groups of core.json_view.CHUNK items), so a big file opens at once.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtWidgets

from ..core import json_view
from ..core.document import DocumentError
from .widgets import report_failure

## File dialog filter.
JSON_FILTER = "JSON (*.json);;All files (*)"
## Columns of the tree.
COLUMNS = ["Key", "Value"]
## The column of a row's value.
VALUE_COLUMN = 1
## A new window's size, pixels.
WINDOW_WIDTH, WINDOW_HEIGHT = 900, 700
## Width of the key column, pixels.
KEY_WIDTH = 320
## The marker child of a row whose children are not read yet.
PENDING = "…"


class JsonView(QtWidgets.QWidget):
   """!A JSON file's banner and tree (read-only)."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the view.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The file shown, or None.
      self.file = None
      ## What the file is.
      self.banner = QtWidgets.QLabel("No file")
      self.banner.setWordWrap(True)
      ## The values.
      self.tree = QtWidgets.QTreeWidget()
      self.tree.setHeaderLabels(COLUMNS)
      self.tree.setColumnWidth(0, KEY_WIDTH)
      self.tree.itemExpanded.connect(lambda item: self._expand(item))
      ## Values of the rows by their item (children read on expansion).
      self._values: dict[int, Any] = {}
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(self.banner)
      lay.addWidget(self.tree, 1)

   def show_file(self, f: json_view.JsonFile) -> None:
      """!Shows a file.
      @param f  core.json_view.JsonFile
      @return None
      """
      self.file = f
      self.banner.setText(f.banner())
      self.tree.clear()
      self._values.clear()
      for label, value in json_view.children(f.data):
         self.tree.addTopLevelItem(self._item(label, value))

   def _item(self, label: str, value: Any) -> QtWidgets.QTreeWidgetItem:
      """!A row (a container gets a marker child until it is expanded).
      @param label  its key
      @param value  its value
      @return the item
      """
      item = QtWidgets.QTreeWidgetItem([label, json_view.describe(value)])
      if isinstance(value, json_view.Chunk) or json_view.is_container(value):
         self._values[id(item)] = value
         item.addChild(QtWidgets.QTreeWidgetItem([PENDING, ""]))
      return item

   def _expand(self, item: QtWidgets.QTreeWidgetItem) -> None:
      """!Reads a row's children the first time it is expanded.
      @param item  the row
      @return None
      """
      value = self._values.pop(id(item), None)
      if value is None:
         return
      item.takeChildren()
      for label, child in json_view.children(value):
         item.addChild(self._item(label, child))

   def rows(self) -> int:
      """!Top-level rows shown.
      @return count
      """
      return self.tree.topLevelItemCount()


class JsonWindow(QtWidgets.QMainWindow):
   """!A window of the read-only data view."""

   def __init__(self, path: str | Path | None = None) -> None:
      """!Creates the window.
      @param path  a JSON file to show, or None
      """
      super().__init__()
      ## The view.
      self.view = JsonView()
      self.setCentralWidget(self.view)
      m = self.menuBar().addMenu("&File")
      a = m.addAction("&Open...")
      a.triggered.connect(lambda _c=False: self.open_file())
      a = m.addAction("&Close")
      a.triggered.connect(lambda _c=False: self.close())
      self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
      self.setWindowTitle("Data view (read-only) - CapsuleCreatures")
      if path is not None:
         self.open_file(path)

   def open_file(self, path: str | Path | None = None) -> bool:
      """!Shows a JSON file.
      @param path  the file, or None to ask
      @return True when it opened
      """
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open data file (read-only)", "", JSON_FILTER)
         if not path:
            return False
      try:
         f = json_view.open_file(path)
      except DocumentError as e:
         report_failure(self, "Open data file", str(e))
         return False
      self.view.show_file(f)
      self.setWindowTitle(f"{f.path.name} (read-only) - CapsuleCreatures Data View")
      return True


## Data view windows kept open (a window without a parent needs a reference).
_OPEN: list[JsonWindow] = []


def show_read_only(path: str | Path | None = None) -> JsonWindow | None:
   """!Opens a data view window on a file (asks for one without a path).
   @param path  the file, or None
   @return the window, or None when nothing opened
   """
   w = JsonWindow()
   if not w.open_file(path):
      w.deleteLater()
      return None
   w.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
   _OPEN.append(w)
   w.destroyed.connect(lambda *_a, win=w: _OPEN.remove(win) if win in _OPEN else None)
   w.show()
   return w


def other_schema(path: str | Path, wanted: str) -> bool:
   """!Whether a file is JSON of another schema than an editor wants (the editor shows it read-only instead).
   @param path    the file
   @param wanted  the editor's schema
   @return True for readable JSON whose schema is not wanted
   """
   try:
      f = json_view.open_file(path)
   except DocumentError:
      return False
   return f.schema != wanted
