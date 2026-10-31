"""!The Effects panel's block view (D-23 §3.3): one owner's logic as nested
rows of an indented tree, over the owner's AST.

- A handler member is a top row ("on switch_in per_foe when ..."); its
  statements are rows below it; a block statement (if, chance, repeat, for)
  holds its block's rows, an "else" row holds the else block, and an empty
  block shows an "(empty)" row to drop or insert into.
- Drag a statement row to move it (above, below or onto a row); Up / Down /
  Delete act on the selected row; the palette (Control, Values, Actions,
  Results, Presentation; core.logic.statement_templates()) inserts after the
  selected row, or into the selected block.
- The form below edits the selected row's fields (core.logic.
  statement_fields()): expressions in ExpressionEdit fields with completion
  and the analysed range, names from the battle's lists, subjects, flags and
  modes. The ref picker inserts a read, the function picker a call (odds()
  with 2 to 4 arguments), into the expression field last used.

The view never writes anything itself: each operation is handed to
on_edit(label, change) as a function that changes a copy of the AST, and
the panel writes it (core.logic.set_owner_ast(): the owner's block is
formatted and only that span of its file is replaced, one undo step).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import logic
from ...panes import split_box
from ...widgets import set_enabled
from .catalog import ExpressionEdit, FunctionPicker, RefPicker

## A row's reference: (row kind "handler" | "stmt" | "block", AST path as a tuple).
RowRef = tuple[str, tuple[Any, ...]]
## An AST change: called with a copy of the owner AST, changes it; may return the path to select after.
AstChange = Callable[[dict[str, Any]], object]

## Item data role of a row's RowRef.
REF_ROLE = QtCore.Qt.ItemDataRole.UserRole
## Item data role of a palette row's statement text.
TEMPLATE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
## Text of an empty block's row.
EMPTY_TEXT = "(empty)"
## Row colours by palette group (statements of no group: the palette's default colour).
GROUP_COLOURS = {"Control": "#3d7fd6", "Values": "#9a5fd0", "Results": "#c0507a", "Presentation": "#2f9a52",
                 "comment": "#7f8a96"}
## Statements per palette group, for the row colours (every other primitive is an action).
STATEMENT_GROUPS = {"if": "Control", "chance": "Control", "repeat": "Control", "for": "Control", "call": "Control",
                    "let": "Values", "assign": "Values", "modify": "Results", "immune": "Results",
                    "block": "Results", "stop": "Results", "fail": "Results", "return": "Results",
                    "yield": "Results", "ask": "Results", "text": "Presentation", "say": "Presentation",
                    "announce": "Presentation", "cue": "Presentation", "comment": "comment"}
## Minimum width of the analysed-range label, pixels.
RANGE_LABEL_WIDTH = 140
## Layout stretch of the tree column against the palette column.
TREE_STRETCH = 3
## See TREE_STRETCH.
PALETTE_STRETCH = 1


def drop_target(ref: RowRef, node: Any, position: QtWidgets.QAbstractItemView.DropIndicatorPosition
                ) -> tuple[tuple[Any, ...], int | None] | None:
   """!Where a statement dropped on a row goes.
   @param ref       the row's RowRef
   @param node      the row's AST node (a statement, a handler, a block list)
   @param position  above, below or on the row
   @return (block path, index or None for the end), or None when it cannot go there
   """
   where = QtWidgets.QAbstractItemView.DropIndicatorPosition
   kind, path = ref
   if kind == "handler":
      return (path + ("body",), 0 if position == where.AboveItem else None)
   if kind == "block":
      return (path, 0 if position == where.AboveItem else None)
   if kind != "stmt":
      return None
   if position == where.AboveItem:
      return (path[:-1], path[-1])
   blocks = logic.STATEMENT_BLOCKS.get(node.get("stmt")) if isinstance(node, dict) else None
   if position == where.OnItem and blocks:
      return (path + (blocks[0],), None)
   return (path[:-1], path[-1] + 1)


class BlockTree(QtWidgets.QTreeWidget):
   """!The statement rows; a drop moves a statement through moved(path, block path, index)."""

   ## Emitted on a drop: (statement path, block path, index or None).
   moved = QtCore.Signal(object, object, object)

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the tree.
      @param parent  parent widget
      """
      super().__init__(parent)
      self.setHeaderHidden(True)
      self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
      self.setDropIndicatorShown(True)
      ## Finds a row's AST node (set by BlockView).
      self.node_of: Callable[[RowRef], Any] = lambda _ref: None

   def dropEvent(self, event: QtGui.QDropEvent) -> None:
      """!Turns a drop into moved() (the rows are rebuilt from the AST afterwards, so Qt moves nothing).
      @param event  QDropEvent
      @return None
      """
      source = self.currentItem()
      target = self.itemAt(event.position().toPoint())
      position = self.dropIndicatorPosition()
      event.setDropAction(QtCore.Qt.DropAction.IgnoreAction)
      event.ignore()
      if source is None or target is None or source is target:
         return
      src = source.data(0, REF_ROLE)
      ref = target.data(0, REF_ROLE)
      if not src or src[0] != "stmt" or not ref:
         return
      dest = drop_target(ref, self.node_of(ref), position)
      if dest is not None:
         self.moved.emit(src[1], dest[0], dest[1])


class BlockView(QtWidgets.QWidget):
   """!One owner's logic as blocks (see the module docstring).

   Attributes are documented where __init__ sets them; the ones below are repeated here because Doxygen's
   Python parser otherwise reports their later uses as undocumented members.

   @var form
   Layout of the selected row's fields.
   @var lists
   The battle's names by list.
   @var words
   What expression fields complete.
   @var pending_select
   Row to select after the next show_ast().
   @var ast
   The owner AST shown.
   @var fields
   Fields of the form: (AST key, kind, widget).
   @var range_labels
   Analysed-range labels of the form's expression fields, by AST key.
   @var last_expression
   The expression field the ref picker inserts into.
   """

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the view.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## Writes an AST change (set by the panel): on_edit(label, change) -> True when written.
      self.on_edit: Callable[[str, AstChange], bool] = lambda _label, _change: False
      ## Analysed range of an expression (set by the panel): range_of(slot path, text) -> (lo, hi) or None.
      self.range_of: Callable[[tuple[Any, ...], str], tuple[int, int] | None] = lambda _path, _text: None
      ## Emitted with the handler index when a handler's row (or a row inside it) is selected.
      self.handler_selected: Callable[[int], None] = lambda _index: None
      ## The owner AST shown.
      self.ast = None
      ## Whether edits are allowed (off while the text does not parse).
      self.editable = True
      ## The battle's names by list.
      self.lists = {}
      ## What expression fields complete.
      self.words: list[str] = []
      ## Row to select after the next show().
      self.pending_select: RowRef | None = None
      ## The expression field the ref picker inserts into.
      self.last_expression: ExpressionEdit | None = None
      ## Fields of the form: (AST key, kind, widget).
      self.fields: list[tuple[str, str, QtWidgets.QWidget]] = []
      ## Analysed-range labels of the form's expression fields, by AST key.
      self.range_labels = {}

      ## Statement rows.
      self.tree = BlockTree()
      self.tree.node_of = lambda ref: self.node_at(ref)
      self.tree.moved.connect(lambda path, block, index: self.move_to(tuple(path), tuple(block), index))
      self.tree.currentItemChanged.connect(lambda _cur, _prev: self._selection_changed())
      ## The statement palette.
      self.palette = QtWidgets.QTreeWidget()
      self.palette.setHeaderLabels(["Insert"])
      self.palette.itemDoubleClicked.connect(lambda item, _col: self.insert_template(item.data(0, TEMPLATE_ROLE)))
      insert = QtWidgets.QPushButton("Insert")
      insert.setToolTip("Insert the palette's statement after the selected row (or into the selected block)")
      insert.clicked.connect(lambda: self._insert_current())
      ## Moves the selected statement up.
      self.up_button = QtWidgets.QPushButton("Up")
      ## Moves it down.
      self.down_button = QtWidgets.QPushButton("Down")
      ## Deletes it.
      self.delete_button = QtWidgets.QPushButton("Delete")
      self.up_button.clicked.connect(lambda: self.move_selected(-1))
      self.down_button.clicked.connect(lambda: self.move_selected(1))
      self.delete_button.clicked.connect(lambda: self.delete_selected())
      ## The selected row's fields.
      self.form_box = QtWidgets.QGroupBox("Selected")
      self.form = QtWidgets.QFormLayout(self.form_box)
      ## Builds reads for expression fields.
      self.ref_picker = RefPicker()
      self.ref_picker.picked.connect(lambda text: self._insert_read(text))
      ref_box = QtWidgets.QGroupBox("Values: read a subject's field")
      QtWidgets.QVBoxLayout(ref_box).addWidget(self.ref_picker)
      ## Builds function calls for expression fields (odds() with 2 to 4 arguments).
      self.function_picker = FunctionPicker()
      self.function_picker.picked.connect(lambda text: self._insert_read(text))
      function_box = QtWidgets.QGroupBox("Values: call a function")
      QtWidgets.QVBoxLayout(function_box).addWidget(self.function_picker)

      rows = QtWidgets.QHBoxLayout()
      for b in (self.up_button, self.down_button, self.delete_button):
         rows.addWidget(b)
      rows.addStretch(1)
      left = QtWidgets.QVBoxLayout()
      left.addWidget(self.tree, 1)
      left.addLayout(rows)
      right = QtWidgets.QVBoxLayout()
      right.addWidget(self.palette, 1)
      right.addWidget(insert)
      top = QtWidgets.QHBoxLayout()
      top.addLayout(left, TREE_STRETCH)
      top.addLayout(right, PALETTE_STRETCH)
      split_box(top)   # [RZ] block tree | palette
      lay = QtWidgets.QVBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addLayout(top, 1)
      lay.addWidget(self.form_box)
      lay.addWidget(ref_box)
      lay.addWidget(function_box)
      ## Widgets that edit (off while not editable).
      self.edit_widgets = [self.palette, insert, self.up_button, self.down_button, self.delete_button,
                           self.form_box, ref_box, function_box]

   # -- names ---------------------------------------------------------------------------------------------------------

   def set_names(self, lists: dict[str, list[str]], templates: list[tuple[str, str, str | None]],
                 words: list[str]) -> None:
      """!The battle's names, the palette and the completion words.
      @param lists      core.logic.name_lists()
      @param templates  core.logic.statement_templates()
      @param words      catalog.completion_words()
      @return None
      """
      self.lists = lists
      self.words = words
      self.ref_picker.set_lists(lists)
      self.palette.clear()
      groups: dict[str, QtWidgets.QTreeWidgetItem] = {}
      for group, label, text in templates:
         if group not in groups:
            groups[group] = QtWidgets.QTreeWidgetItem(self.palette, [group])
            groups[group].setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            colour = GROUP_COLOURS.get(group)
            if colour:
               groups[group].setForeground(0, QtGui.QColor(colour))
         item = QtWidgets.QTreeWidgetItem(groups[group], [label])
         item.setData(0, TEMPLATE_ROLE, text)
         item.setToolTip(0, text or "the battle has no name for it yet")
         if text is None:
            item.setDisabled(True)
      self.palette.expandAll()

   # -- rows ----------------------------------------------------------------------------------------------------------

   def show_ast(self, ast: dict[str, Any] | None, editable: bool) -> None:
      """!Shows an owner (keeps the selected row where it still exists).
      @param ast       owner AST, or None for nothing
      @param editable  whether edits are allowed
      @return None
      """
      keep = self.pending_select or self.selected_ref()
      self.pending_select = None
      self.ast = ast
      self.editable = editable and ast is not None
      self.tree.blockSignals(True)
      self.tree.clear()
      if ast is not None:
         for j, h in enumerate(ast.get("handlers", [])):
            item = QtWidgets.QTreeWidgetItem(self.tree, [logic.handler_text(h)])
            font = item.font(0)
            font.setBold(h.get("stmt") != "comment")
            item.setFont(0, font)
            if h.get("stmt") == "comment":
               item.setForeground(0, QtGui.QColor(GROUP_COLOURS["comment"]))
               item.setData(0, REF_ROLE, ("comment", ("handlers", j)))
               continue
            item.setData(0, REF_ROLE, ("handler", ("handlers", j)))
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            self._add_block(item, ("handlers", j, "body"), h.get("body", []))
      self.tree.expandAll()
      self.tree.blockSignals(False)
      self.tree.setDragEnabled(self.editable)
      for w in self.edit_widgets:
         set_enabled(w, self.editable)   # the palette goes read-only and keeps its scroll bar
      if keep is not None:
         self.select(keep)
      self._selection_changed()

   def _add_block(self, parent: QtWidgets.QTreeWidgetItem, path: tuple[Any, ...], body: list[Any]) -> None:
      """!Adds a block's statement rows.
      @param parent  row they go under
      @param path    the block's path
      @param body    its statements
      @return None
      """
      if not body:
         empty = QtWidgets.QTreeWidgetItem(parent, [EMPTY_TEXT])
         empty.setData(0, REF_ROLE, ("block", path))
         empty.setForeground(0, QtGui.QColor(GROUP_COLOURS["comment"]))
         empty.setFlags(empty.flags() & ~QtCore.Qt.ItemFlag.ItemIsDragEnabled)
         return
      for k, s in enumerate(body):
         self._add_statement(parent, path, k, s)

   def _add_statement(self, parent: QtWidgets.QTreeWidgetItem, path: tuple[Any, ...], index: int,
                      s: dict[str, Any]) -> None:
      """!Adds one statement's row and the rows of its blocks (the main block under it, "else" as a row).
      @param parent  row it goes under
      @param path    its block's path
      @param index   its index in the block
      @param s       the statement
      @return None
      """
      item = QtWidgets.QTreeWidgetItem(parent, [logic.statement_text(s)])
      item.setData(0, REF_ROLE, ("stmt", path + (index,)))
      colour = GROUP_COLOURS.get(STATEMENT_GROUPS.get(s.get("stmt"), ""))
      if colour:
         item.setForeground(0, QtGui.QColor(colour))
      for n, key in enumerate(logic.STATEMENT_BLOCKS.get(s.get("stmt"), ())):
         if n == 0:
            self._add_block(item, path + (index, key), s.get(key, []))
         elif key in s:
            head = QtWidgets.QTreeWidgetItem(item, ["else"])
            head.setData(0, REF_ROLE, ("block", path + (index, key)))
            head.setForeground(0, QtGui.QColor(GROUP_COLOURS["Control"]))
            head.setFlags(head.flags() & ~QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            for m, inner in enumerate(s[key]):
               self._add_statement(head, path + (index, key), m, inner)

   def rows(self) -> list[tuple[int, RowRef, str]]:
      """!Every row, in display order.
      @return [(depth, RowRef, text)]
      """
      out = []

      def walk(item: QtWidgets.QTreeWidgetItem, depth: int) -> None:
         """!Adds a row and the rows below it.
         @param item   the row
         @param depth  its depth
         @return None
         """
         out.append((depth, item.data(0, REF_ROLE), item.text(0)))
         for i in range(item.childCount()):
            walk(item.child(i), depth + 1)

      for i in range(self.tree.topLevelItemCount()):
         walk(self.tree.topLevelItem(i), 0)
      return out

   def item_of(self, ref: RowRef) -> QtWidgets.QTreeWidgetItem | None:
      """!The row of a reference.
      @param ref  RowRef
      @return the row, or None
      """
      it = QtWidgets.QTreeWidgetItemIterator(self.tree)
      while it.value():
         item = it.value()
         got = item.data(0, REF_ROLE)
         if got and (got[0], tuple(got[1])) == (ref[0], tuple(ref[1])):
            return item
         it += 1
      return None

   def select(self, ref: RowRef) -> bool:
      """!Selects a row.
      @param ref  RowRef
      @return True when it exists
      """
      item = self.item_of(ref)
      if item is not None:
         self.tree.setCurrentItem(item)
      return item is not None

   def select_handler(self, index: int) -> None:
      """!Selects a handler's row unless a row inside it is selected already.
      @param index  index in the owner's "handlers"
      @return None
      """
      ref = self.selected_ref()
      if ref is not None and len(ref[1]) > 1 and ref[1][1] == index:
         return
      self.select(("handler", ("handlers", index)))

   def selected_ref(self) -> RowRef | None:
      """!The selected row.
      @return RowRef, or None
      """
      item = self.tree.currentItem()
      ref = item.data(0, REF_ROLE) if item is not None else None
      return (ref[0], tuple(ref[1])) if ref else None

   def node_at(self, ref: RowRef) -> Any:
      """!A row's AST node.
      @param ref  RowRef
      @return the node, or None
      """
      if self.ast is None:
         return None
      try:
         return logic.node_at(self.ast, ref[1])
      except logic.DocumentError:
         return None

   # -- operations ----------------------------------------------------------------------------------------------------

   def insert_target(self) -> tuple[tuple[Any, ...], int | None] | None:
      """!Where the palette inserts: after the selected statement, or at the end of the selected block or
      handler (the first handler when nothing is selected).
      @return (block path, index or None), or None when the owner has no handler
      """
      ref = self.selected_ref()
      if ref is None or ref[0] == "comment":
         handlers = self.ast.get("handlers", []) if self.ast else []
         first = next((j for j, h in enumerate(handlers) if h.get("stmt") != "comment"), None)
         return (("handlers", first, "body"), None) if first is not None else None
      kind, path = ref
      if kind == "stmt":
         return (path[:-1], path[-1] + 1)
      if kind == "block":
         return (path, None)
      return (path + ("body",), None)

   def insert_template(self, text: str | None) -> bool:
      """!Inserts a statement.
      @param text  statement text (a palette template)
      @return True when written
      """
      target = self.insert_target()
      if not text or target is None or not self.editable:
         return False
      block, index = target

      def change(ast: dict[str, Any]) -> tuple[Any, ...]:
         """!Inserts it.
         @param ast  owner AST
         @return the new statement's path
         """
         return block + (logic.insert_statement(ast, block, index, text),)

      return self.on_edit("Insert statement", change)

   def _insert_current(self) -> bool:
      """!Inserts the palette's selected statement.
      @return True when written
      """
      item = self.palette.currentItem()
      return self.insert_template(item.data(0, TEMPLATE_ROLE) if item is not None else None)

   def move_selected(self, delta: int) -> bool:
      """!Moves the selected statement up or down its block.
      @param delta  -1 up, +1 down
      @return True when written
      """
      ref = self.selected_ref()
      if ref is None or ref[0] != "stmt" or not self.editable:
         return False
      path = ref[1]

      def change(ast: dict[str, Any]) -> tuple[Any, ...] | None:
         """!Moves it.
         @param ast  owner AST
         @return its new path
         """
         return path[:-1] + (path[-1] + delta,) if logic.move_statement(ast, path, delta) else None

      return self.on_edit("Move statement", change)

   def move_to(self, path: tuple[Any, ...], block: tuple[Any, ...], index: int | None) -> bool:
      """!Moves a statement into a block (a drop).
      @param path   the statement's path
      @param block  the block's path
      @param index  position, or None for the end
      @return True when written
      """
      if not self.editable:
         return False
      return self.on_edit("Move statement", lambda ast: tuple(logic.move_statement_to(ast, path, block, index)))

   def delete_selected(self) -> bool:
      """!Deletes the selected statement.
      @return True when written
      """
      ref = self.selected_ref()
      if ref is None or ref[0] != "stmt" or not self.editable:
         return False
      path = ref[1]
      return self.on_edit("Delete statement", lambda ast: logic.delete_statement(ast, path) and None)

   # -- the form ------------------------------------------------------------------------------------------------------

   def _selection_changed(self) -> None:
      """!Rebuilds the form for the selected row and tells the panel which handler it is in.
      @return None
      """
      while self.form.rowCount():
         self.form.removeRow(0)
      self.fields = []
      self.range_labels = {}
      self.last_expression = None
      ref = self.selected_ref()
      node = self.node_at(ref) if ref is not None else None
      if ref is not None and len(ref[1]) > 1 and isinstance(ref[1][1], int):
         self.handler_selected(ref[1][1])
      if ref is None or not isinstance(node, dict):
         self.form_box.setTitle("Selected: nothing")
         return
      kind, path = ref
      if kind == "handler":
         self.form_box.setTitle("Handler: " + logic.handler_text(node))
         self._add_field(path, "when", "opt_expr", node)
         return
      if kind != "stmt":
         self.form_box.setTitle("Block")
         return
      self.form_box.setTitle("Statement: " + str(node.get("stmt")))
      for field, fkind in logic.statement_fields(node):
         self._add_field(path, field, fkind, node)

   def _add_field(self, path: tuple[Any, ...], field: str, kind: str, node: dict[str, Any]) -> None:
      """!Adds one field to the form.
      @param path   the node's path
      @param field  AST key
      @param kind   statement_fields() kind ("when" of a handler: opt_expr)
      @param node   the node
      @return None
      """
      text = logic.field_text(node, field, kind)
      head, _, rest = kind.partition(":")
      widget: QtWidgets.QWidget
      if head == "flag":
         box = QtWidgets.QCheckBox()
         box.setChecked(bool(text))
         box.toggled.connect(lambda on: self._commit(path, field, kind, "1" if on else ""))
         widget = box
      elif head in ("expr", "opt_expr", "kw", "exprs"):
         edit = ExpressionEdit()
         edit.set_words(self.words)
         edit.setText(text)
         label = QtWidgets.QLabel()
         label.setMinimumWidth(RANGE_LABEL_WIDTH)
         self.range_labels[field] = label
         edit.textEdited.connect(lambda t: self._show_range(path, field, t))
         edit.editingFinished.connect(lambda: self._commit_if_changed(path, field, kind, edit))
         edit.installEventFilter(self)
         row = QtWidgets.QWidget()
         lay = QtWidgets.QHBoxLayout(row)
         lay.setContentsMargins(0, 0, 0, 0)
         lay.addWidget(edit, 1)
         lay.addWidget(label)
         self._show_range(path, field, text)
         if self.last_expression is None:
            self.last_expression = edit
         widget = row
      else:
         choices = logic.field_choices(kind)
         if head in ("id", "opt_id", logic.KWID_KIND):
            choices = list(self.lists.get(rest, []))   # G1: kwid:LIST (use_move ... unless FLAG) names one too
         elif head in ("subj", "kws", "side"):
            choices = logic.battler_subjects()   # a loop variable or local can be typed in
         combo = QtWidgets.QComboBox()
         combo.setEditable(head not in ("mode", "choice", "sets", "asks"))
         if head in ("opt_id", "kws", logic.KWID_KIND):
            combo.addItem("")
         combo.addItems(choices)
         if combo.findText(text) < 0:
            combo.addItem(text)
         combo.setCurrentIndex(combo.findText(text))
         combo.activated.connect(lambda _i: self._commit(path, field, kind, combo.currentText()))
         if combo.isEditable():
            combo.lineEdit().editingFinished.connect(
               lambda: combo.currentText() != text and self._commit(path, field, kind, combo.currentText()))
         widget = combo
      widget.setEnabled(self.editable)
      self.fields.append((field, kind, widget))
      self.form.addRow(field, widget)

   def field_widget(self, field: str) -> QtWidgets.QWidget | None:
      """!The form's widget of a field (an expression field: its ExpressionEdit).
      @param field  AST key
      @return widget, or None
      """
      for key, _kind, w in self.fields:
         if key == field:
            edit = w.findChild(ExpressionEdit)
            return edit if edit is not None else w
      return None

   def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
      """!Remembers the expression field last focused (the ref picker inserts there).
      @param watched  the field
      @param event    QEvent
      @return False (the event goes on)
      """
      if event.type() == QtCore.QEvent.Type.FocusIn and isinstance(watched, ExpressionEdit):
         self.last_expression = watched
      return False

   def _insert_read(self, text: str) -> None:
      """!Inserts the ref picker's read or the function picker's call into the expression field last used.
      @param text  the read or call
      @return None
      """
      if self.last_expression is not None and text:
         self.last_expression.insert_text(text)

   def _show_range(self, path: tuple[Any, ...], field: str, text: str) -> None:
      """!Shows an expression field's analysed range.
      @param path   the node's path
      @param field  AST key
      @param text   the field's text now
      @return None
      """
      label = self.range_labels.get(field)
      if label is None:
         return
      r = self.range_of(path + (field,), text) if text.strip() else None
      label.setText(f"range {r[0]}..{r[1]}" if r is not None else "range: ?")

   def _commit_if_changed(self, path: tuple[Any, ...], field: str, kind: str, edit: ExpressionEdit) -> None:
      """!Writes an expression field when its text differs from the AST's.
      @param path   the node's path
      @param field  AST key
      @param kind   its kind
      @param edit   the field
      @return None
      """
      node = self.node_at(("stmt", path))
      if isinstance(node, dict) and edit.text().strip() != logic.field_text(node, field, kind):
         self._commit(path, field, kind, edit.text())

   def _commit(self, path: tuple[Any, ...], field: str, kind: str, text: str) -> bool:
      """!Writes one field.
      @param path   the node's path
      @param field  AST key
      @param kind   its kind
      @param text   the new text
      @return True when written
      """
      if not self.editable:
         return False
      ref = self.selected_ref()

      def change(ast: dict[str, Any]) -> object:
         """!Sets it.
         @param ast  owner AST
         @return None (the row stays selected)
         """
         logic.set_field(ast, path, field, kind, text)
         return None

      self.pending_select = ref
      return self.on_edit(f"Edit {field}", change)
