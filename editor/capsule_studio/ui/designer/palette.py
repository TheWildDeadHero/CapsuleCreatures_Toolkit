"""!The manifest designer's palette (D-43 §5, from Node-RED): the system's kinds by category, searchable; drag one
onto the canvas, or double-click it to add it in the middle of the view. QuickAdd is the add-by-typing popup the
canvas opens on a double-click in empty space, or when a wire is dropped there (then it lists only the kinds the wire
can end on).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.designer.model import ElementKind
from ...core.designer.system import DesignerSystem
from .canvas import KIND_MIME

## Side of a palette entry's colour swatch, pixels.
SWATCH = 12
## Width of the QuickAdd popup, pixels.
QUICK_WIDTH = 260
## Rows the QuickAdd popup shows before it scrolls.
QUICK_ROWS = 10
## Halves (a frame's two sides).
HALVES = 2
## Role of a palette item's kind id.
KIND_ROLE = QtCore.Qt.ItemDataRole.UserRole


def swatch(colour: str) -> QtGui.QIcon:
   """!A small square of a colour.
   @param colour  "#rrggbb"
   @return the icon
   """
   pixmap = QtGui.QPixmap(SWATCH, SWATCH)
   pixmap.fill(QtGui.QColor(colour))
   return QtGui.QIcon(pixmap)


def matches(kind: ElementKind, text: str) -> bool:
   """!Whether a kind matches a search (its title, id, category or help).
   @param kind  the kind
   @param text  what was typed
   @return True when every word appears
   """
   haystack = " ".join((kind.title, kind.kind_id, kind.category, kind.help)).lower()
   return all(word in haystack for word in text.lower().split())


class PaletteTree(QtWidgets.QTreeWidget):
   """!The palette's tree: categories, then kinds (drag a kind out)."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the tree.
      @param parent  parent widget
      """
      super().__init__(parent)
      self.setHeaderHidden(True)
      self.setDragEnabled(True)
      self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragOnly)
      self.setRootIsDecorated(True)

   def mimeTypes(self) -> list[str]:
      """!What a drag carries.
      @return [KIND_MIME]
      """
      return [KIND_MIME]

   def mimeData(self, items: Sequence[QtWidgets.QTreeWidgetItem]) -> QtCore.QMimeData:
      """!A dragged kind's id.
      @param items  the dragged items
      @return the mime data
      """
      data = QtCore.QMimeData()
      kind_id = next((i.data(0, KIND_ROLE) for i in items if i.data(0, KIND_ROLE)), "")
      data.setData(KIND_MIME, QtCore.QByteArray(str(kind_id).encode("utf-8")))
      return data


class Palette(QtWidgets.QWidget):
   """!The search box and the tree of kinds."""

   ## A kind was double-clicked: its id.
   chosen = QtCore.Signal(str)

   def __init__(self, system: DesignerSystem, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the palette.
      @param system  the system whose kinds it lists
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The system.
      self.system = system
      ## The search box.
      self.search = QtWidgets.QLineEdit()
      self.search.setPlaceholderText("Search")
      self.search.setClearButtonEnabled(True)
      self.search.textChanged.connect(lambda _t: self.refill())
      ## The kinds.
      self.tree = PaletteTree()
      self.tree.itemDoubleClicked.connect(lambda item, _c: self._chosen(item))
      box = QtWidgets.QVBoxLayout(self)
      box.setContentsMargins(0, 0, 0, 0)
      box.addWidget(self.search)
      box.addWidget(self.tree, 1)
      self.refill()

   def refill(self) -> None:
      """!Lists the kinds that match the search, by category.
      @return None
      """
      self.tree.clear()
      text = self.search.text()
      groups: dict[str, QtWidgets.QTreeWidgetItem] = {}
      for kind in self.system.kinds():
         if text and not matches(kind, text):
            continue
         group = groups.get(kind.category)
         if group is None:
            group = QtWidgets.QTreeWidgetItem([kind.category or "Other"])
            group.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(group)
            groups[kind.category] = group
         item = QtWidgets.QTreeWidgetItem([kind.title])
         item.setData(0, KIND_ROLE, kind.kind_id)
         item.setIcon(0, swatch(kind.colour))
         item.setToolTip(0, kind.help or kind.title)
         item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
                       | QtCore.Qt.ItemFlag.ItemIsDragEnabled)
         group.addChild(item)
      self.tree.expandAll()

   def kind_ids(self) -> list[str]:
      """!The kinds listed now (tests).
      @return kind ids
      """
      out = []
      for n in range(self.tree.topLevelItemCount()):
         group = self.tree.topLevelItem(n)
         out += [group.child(m).data(0, KIND_ROLE) for m in range(group.childCount())]
      return out

   def _chosen(self, item: QtWidgets.QTreeWidgetItem) -> None:
      """!A kind was double-clicked.
      @param item  its item
      @return None
      """
      kind_id = item.data(0, KIND_ROLE)
      if kind_id:
         self.chosen.emit(str(kind_id))


class QuickAdd(QtWidgets.QFrame):
   """!The add-by-typing popup: type, then Enter (or double-click) adds the highlighted kind."""

   def __init__(self, kinds: Sequence[ElementKind], on_pick: Callable[[str], object],
                parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the popup.
      @param kinds    the kinds it offers
      @param on_pick  called with the chosen kind id
      @param parent   parent widget
      """
      super().__init__(parent, QtCore.Qt.WindowType.Popup)
      self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
      ## The kinds offered.
      self.kinds = list(kinds)
      ## Called with the chosen kind.
      self._on_pick = on_pick
      ## What is typed.
      self.edit = QtWidgets.QLineEdit()
      self.edit.setPlaceholderText("Type to add")
      self.edit.textChanged.connect(lambda _t: self.refill())
      self.edit.returnPressed.connect(lambda: self.pick())
      self.edit.installEventFilter(self)
      ## The matching kinds.
      self.list = QtWidgets.QListWidget()
      self.list.itemActivated.connect(lambda _i: self.pick())
      box = QtWidgets.QVBoxLayout(self)
      box.addWidget(self.edit)
      box.addWidget(self.list)
      self.setFixedWidth(QUICK_WIDTH)
      self.refill()
      row = self.list.sizeHintForRow(0)
      if row > 0:
         self.list.setMinimumHeight(row * min(QUICK_ROWS, self.list.count()) + self.list.frameWidth() * HALVES)

   def refill(self) -> None:
      """!Lists the kinds that match what is typed.
      @return None
      """
      self.list.clear()
      for kind in self.kinds:
         if self.edit.text() and not matches(kind, self.edit.text()):
            continue
         item = QtWidgets.QListWidgetItem(swatch(kind.colour), f"{kind.title}    {kind.category}")
         item.setData(KIND_ROLE, kind.kind_id)
         self.list.addItem(item)
      if self.list.count():
         self.list.setCurrentRow(0)

   def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
      """!Up and Down in the text box move through the list.
      @param watched  the text box
      @param event    the event
      @return True when handled
      """
      if watched is self.edit and event.type() == QtCore.QEvent.Type.KeyPress:
         step = {QtCore.Qt.Key.Key_Down: 1, QtCore.Qt.Key.Key_Up: -1}.get(event.key())
         if step is not None and self.list.count():
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, self.list.currentRow() + step)))
            return True
      return super().eventFilter(watched, event)

   def pick(self) -> None:
      """!Adds the highlighted kind and closes.
      @return None
      """
      item = self.list.currentItem()
      self.close()
      if item is not None:
         self._on_pick(str(item.data(KIND_ROLE)))

   def popup(self, at: QtCore.QPoint) -> None:
      """!Shows the popup at a screen point, ready for typing.
      @param at  the point
      @return None
      """
      self.move(at)
      self.show()
      self.edit.setFocus()
