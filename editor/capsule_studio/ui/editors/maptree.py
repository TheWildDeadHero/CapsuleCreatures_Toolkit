"""!The map editor's map list: the world's map groups as a tree (like
common tile-map editors' map lists), with a filter, drag and drop to reorganise, and a
context menu for groups and new maps."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import mapgroups

if TYPE_CHECKING:
   from .mapedit import MapPanel

## A map group's path: the group names from the top level down (empty: top level / ungrouped).
GroupPath = tuple[str, ...]
## What an item stands for: ("map", name) or ("group", path).
Node = tuple[str, str | GroupPath]
## A node of mapgroups.tree(): ("group", name, path, children) or ("map", name).
TreeNode = tuple[str, str] | tuple[str, str, GroupPath, list["TreeNode"]]
## A world manifest (parsed JSON).
JsonDict = dict[str, Any]

## Item data role holding ("map", name) or ("group", path).
NODE_ROLE = QtCore.Qt.ItemDataRole.UserRole
## Index of a group node's path in a mapgroups.tree() node.
NODE_PATH = 2
## Index of a group node's children in a mapgroups.tree() node.
NODE_CHILDREN = 3


class MapTree(QtWidgets.QTreeWidget):
   """!Groups (folders) and maps; maps no group lists come last. Click a map
   to edit it; drag maps and groups onto a group (or between items) to
   reorganise; right click for New map / New group / Rename / Remove.
   Changes go through the owning panel (one undo step each).
   """

   def __init__(self, panel: MapPanel) -> None:
      """!Creates the tree.
      @param panel  owning MapPanel
      """
      super().__init__()
      ## The owning MapPanel.
      self.panel = panel
      ## Paths of collapsed groups (everything else starts expanded).
      self.collapsed = set()
      ## The filter text (lower case); maps not matching are hidden.
      self.filter = ""
      self.setHeaderHidden(True)
      self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
      self.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
      self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
      self.customContextMenuRequested.connect(lambda pos: self._menu(pos))
      self.itemCollapsed.connect(lambda item: self._expanded(item, False))
      self.itemExpanded.connect(lambda item: self._expanded(item, True))
      self.setToolTip("Maps in their groups. Drag a map or group onto a group to move it there; right click for "
                      "more.")
      ## Folder icon for groups.
      self.group_icon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon)

   def node(self, item: QtWidgets.QTreeWidgetItem | None) -> Node | None:
      """!What an item stands for.
      @param item  QTreeWidgetItem, or None
      @return ("map", name), ("group", path), or None
      """
      return item.data(0, NODE_ROLE) if item is not None else None

   def fill(self, world_data: JsonDict, map_names: list[str], current: str | None) -> None:
      """!Rebuilds the tree.
      @param world_data  world manifest
      @param map_names   the world's map names
      @param current     map to select, or None
      @return None
      """
      self.blockSignals(True)
      try:
         self.clear()
         found = None

         def add(parent: QtWidgets.QTreeWidget | QtWidgets.QTreeWidgetItem, nodes: list[TreeNode]) -> int:
            """!Adds nodes under a parent (recursively for groups).
            @param parent  the tree (top level) or a group item
            @param nodes   mapgroups.tree() nodes
            @return how many maps under them are shown (not filtered out)
            """
            nonlocal found
            shown = 0
            for n in nodes:
               if n[0] == "group":
                  item = QtWidgets.QTreeWidgetItem([n[1]])
                  item.setIcon(0, self.group_icon)
                  item.setData(0, NODE_ROLE, ("group", n[NODE_PATH]))
                  item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsDropEnabled)
                  parent.addChild(item) if isinstance(parent, QtWidgets.QTreeWidgetItem) else \
                      self.addTopLevelItem(item)
                  inner = add(item, n[NODE_CHILDREN])
                  # Filtering hides groups without a matching map and shows every other one open.
                  item.setHidden(bool(self.filter) and inner == 0)
                  item.setExpanded(n[NODE_PATH] not in self.collapsed or bool(self.filter))
                  shown += inner
               else:
                  item = QtWidgets.QTreeWidgetItem([n[1]])
                  item.setData(0, NODE_ROLE, ("map", n[1]))
                  item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsDropEnabled)
                  parent.addChild(item) if isinstance(parent, QtWidgets.QTreeWidgetItem) else \
                      self.addTopLevelItem(item)
                  hidden = bool(self.filter) and self.filter not in n[1].lower()
                  item.setHidden(hidden)
                  shown += 0 if hidden else 1
                  if n[1] == current:
                     found = item
            return shown
         add(self, mapgroups.tree(world_data, map_names))
         if found is not None:
            self.setCurrentItem(found)
      finally:
         self.blockSignals(False)

   def _expanded(self, item: QtWidgets.QTreeWidgetItem, on: bool) -> None:
      """!Remembers collapsed groups across rebuilds.
      @param item  group item
      @param on    expanded
      @return None
      """
      node = self.node(item)
      if node and node[0] == "group" and not self.filter:
         if on:
            self.collapsed.discard(node[1])
         else:
            self.collapsed.add(node[1])

   def group_at(self, item: QtWidgets.QTreeWidgetItem | None) -> GroupPath:
      """!The group an item is in, or is.
      @param item  QTreeWidgetItem, or None
      @return group path (empty: top level / ungrouped)
      """
      node = self.node(item)
      if node is None:
         return ()
      if node[0] == "group":
         return node[1]
      parent = self.node(item.parent()) if item.parent() is not None else None
      return parent[1] if parent else ()

   def _menu(self, pos: QtCore.QPoint) -> None:
      """!Context menu.
      @param pos  viewport position
      @return None
      """
      item = self.itemAt(pos)
      node = self.node(item)
      where = self.group_at(item)
      m = QtWidgets.QMenu(self)
      label = f" in {where[-1]}" if where else ""
      m.addAction(f"New map{label}...").triggered.connect(lambda *a: self.panel.new_map(where))
      m.addAction(f"New group{label}...").triggered.connect(lambda *a: self.panel.new_group(where))
      if node and node[0] == "group":
         m.addSeparator()
         m.addAction("Rename group...").triggered.connect(lambda *a: self.panel.rename_group(node[1]))
         m.addAction("Remove group (keeps its maps)").triggered.connect(lambda *a: self.panel.remove_group(node[1]))
      if node and node[0] == "map" and where:
         m.addSeparator()
         m.addAction("Take out of the group").triggered.connect(
            lambda *a: self.panel.move_node(node, (), None))
      m.exec(self.viewport().mapToGlobal(pos))
      m.deleteLater()

   def dropEvent(self, event: QtGui.QDropEvent) -> None:
      """!Applies a drag as a change to the world's groups (the tree is then rebuilt).
      @param event  QDropEvent
      @return None
      """
      dragged = self.node(self.currentItem())
      target = self.itemAt(event.position().toPoint())
      # Qt must not move the items itself: the panel edits the world, then the tree is rebuilt from it.
      event.setDropAction(QtCore.Qt.DropAction.IgnoreAction)
      event.accept()
      if dragged is None:
         return
      pos = self.dropIndicatorPosition()
      tnode = self.node(target)
      on = QtWidgets.QAbstractItemView.DropIndicatorPosition
      if tnode is None or pos == on.OnViewport:
         parent, index = (), None
      elif pos == on.OnItem and tnode[0] == "group":
         parent, index = tnode[1], None
      else:   # above / below an item: next to it, in its group
         parent = self.group_at(target.parent()) if tnode[0] == "group" else self.group_at(target)
         if tnode[0] == "group":
            parent = tnode[1][:-1]
         # The target's siblings; the index counts only those of the dragged node's kind.
         siblings = [self.node(target.parent().child(i)) if target.parent() is not None
                     else self.node(self.topLevelItem(i))
                     for i in range(target.parent().childCount() if target.parent() is not None
                                    else self.topLevelItemCount())]
         same = [s for s in siblings if s and s[0] == dragged[0] and s != dragged]
         index = same.index(tnode) + (1 if pos == on.BelowItem else 0) if tnode in same else None
      QtCore.QTimer.singleShot(0, lambda: self.panel.move_node(dragged, parent, index))
