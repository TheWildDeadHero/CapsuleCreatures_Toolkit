"""!The manifest designer's inspector (D-43 §5): the selected element's fields, built from its kind's PropertySpecs
(text, whole number, yes / no, choice, colour), with its position and (shapes) size; or a link's ends and label;
or, for several elements, how many and what the Arrange menu does with them. Each finished field is one session edit.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.designer import model
from ...core.designer.model import ModelError, PropertySpec
from ...core.designer.session import DesignSession

## Range of a whole-number field without limits (32 bits).
INT_LIMIT = 2 ** 31 - 1
## Range of the position fields, canvas units.
POS_LIMIT = 1_000_000
## Range of the size fields, canvas units.
SIZE_LIMIT = 100_000


class Inspector(QtWidgets.QWidget):
   """!The fields of what is selected."""

   ## Something could not be set: why.
   refused = QtCore.Signal(str)

   def __init__(self, session: DesignSession, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the (empty) inspector.
      @param session  the session it edits
      @param parent   parent widget
      """
      super().__init__(parent)
      ## The session.
      self.session = session
      ## What is shown: element or link ids.
      self.ids = []
      ## Field name -> its editor widget (the element's fields, then "x", "y", "w", "h"; a link's "label").
      self.editors = {}
      ## The heading.
      self.heading = QtWidgets.QLabel("Nothing selected")
      font = self.heading.font()
      font.setBold(True)
      self.heading.setFont(font)
      self.heading.setWordWrap(True)
      ## The form.
      self.form = QtWidgets.QFormLayout()
      ## A hint under the form.
      self.hint = QtWidgets.QLabel("Select an element to see its fields; drag from the palette to add one.")
      self.hint.setWordWrap(True)
      box = QtWidgets.QVBoxLayout(self)
      box.addWidget(self.heading)
      box.addLayout(self.form)
      box.addWidget(self.hint)
      box.addStretch(1)

   def show_ids(self, ids: list[str]) -> None:
      """!Shows the fields of a selection.
      @param ids  selected element and link ids (the first picked first)
      @return None
      """
      self.ids = list(ids)
      self.refresh()

   def refresh(self) -> None:
      """!Rebuilds the form from the diagram as it is now.
      @return None
      """
      while self.form.rowCount():
         self.form.removeRow(0)
      self.editors = {}
      try:
         diagram = self.session.diagram()
      except ModelError:
         return
      ids = [i for i in self.ids if i in diagram.elements or i in diagram.links]
      if not ids:
         self.heading.setText("Nothing selected")
         self.hint.setText("Select an element to see its fields; drag from the palette to add one.")
         return
      if len(ids) > 1:
         self.heading.setText(f"{len(ids)} selected")
         self.hint.setText("Arrange lines them up on the first one picked. Duplicate copies them with the wires "
                           "between them.")
         return
      self.hint.setText("")
      only = ids[0]
      if only in diagram.links:
         self._show_link(diagram.link(only))
      else:
         self._show_element(diagram.element(only))

   def _show_link(self, link: model.Link) -> None:
      """!A link's ends and label.
      @param link  the link
      @return None
      """
      self.heading.setText("Connector" if link.annotation else "Wire")
      self.form.addRow("From", QtWidgets.QLabel(link.source.text()))
      self.form.addRow("To", QtWidgets.QLabel(link.target.text()))
      edit = QtWidgets.QLineEdit(link.label)
      edit.editingFinished.connect(lambda: self._apply(lambda: self.session.set_label(link.link_id, edit.text())
                                                       if edit.text() != link.label else None))
      self.form.addRow("Label", edit)
      self.editors["label"] = edit

   def _show_element(self, element: model.Element) -> None:
      """!An element's fields, then its position and size.
      @param element  the element
      @return None
      """
      try:
         kind = self.session.system.kind(element.kind)
      except ModelError as e:
         self.heading.setText(element.element_id)
         self.hint.setText(str(e))
         return
      self.heading.setText(f"{kind.title}  ({element.element_id})")
      if kind.help:
         self.hint.setText(kind.help)
      for spec in kind.properties:
         widget = self._field(element, spec)
         self.form.addRow(spec.title, widget)
         self.editors[spec.name] = widget
      x, y = element.pos
      for name, value in (("x", x), ("y", y)):
         spin = self._spin(-POS_LIMIT, POS_LIMIT, value)
         spin.editingFinished.connect(lambda e=element: self._apply(lambda: self._place(e)))
         self.form.addRow(name.upper(), spin)
         self.editors[name] = spin
      if kind.role == model.ROLE_SHAPE:
         w, h = self.session.system.element_size(element)
         for name, value in (("w", w), ("h", h)):
            spin = self._spin(1, SIZE_LIMIT, value)
            spin.editingFinished.connect(lambda e=element: self._apply(lambda: self._resize(e)))
            self.form.addRow("Width" if name == "w" else "Height", spin)
            self.editors[name] = spin
      if element.parent:
         self.form.addRow("In frame", QtWidgets.QLabel(element.parent))

   def _spin(self, low: int, high: int, value: int) -> QtWidgets.QSpinBox:
      """!A whole-number box.
      @param low    smallest
      @param high   largest
      @param value  its value
      @return the box
      """
      spin = QtWidgets.QSpinBox()
      spin.setRange(low, high)
      spin.setValue(value)
      spin.setKeyboardTracking(False)
      return spin

   def _field(self, element: model.Element, spec: PropertySpec) -> QtWidgets.QWidget:
      """!The editor of one field; finishing it sets the field.
      @param element  the element
      @param spec     the field
      @return the widget
      """
      value = element.properties.get(spec.name, spec.default)

      def setter(get: Callable[[], Any]) -> Callable[[], None]:
         """!Sets the field from a widget when its value differs.
         @param get  reads the widget
         @return the slot
         """
         def apply() -> None:
            """!The slot.
            @return None
            """
            new = get()
            current = self.session.diagram().elements.get(element.element_id)
            if current is not None and current.properties.get(spec.name) != new:
               self._apply(lambda: self.session.set_properties(element.element_id, {spec.name: new}))
         return apply

      if spec.value_type == model.VALUE_INTEGER:
         low = spec.minimum if spec.minimum is not None else -INT_LIMIT
         high = spec.maximum if spec.maximum is not None else INT_LIMIT
         spin = self._spin(low, high, int(value or 0))
         spin.editingFinished.connect(setter(spin.value))
         return spin
      if spec.value_type == model.VALUE_BOOLEAN:
         check = QtWidgets.QCheckBox()
         check.setChecked(bool(value))
         check.toggled.connect(lambda _on, apply=setter(check.isChecked): apply())
         return check
      if spec.value_type == model.VALUE_CHOICE:
         combo = QtWidgets.QComboBox()
         combo.addItems(list(spec.choices))
         combo.setCurrentText(str(value))
         combo.activated.connect(lambda _n, apply=setter(combo.currentText): apply())
         return combo
      if spec.value_type == model.VALUE_COLOUR:
         row = QtWidgets.QWidget()
         line = QtWidgets.QLineEdit(str(value or ""))
         line.setPlaceholderText("#rrggbb")
         line.editingFinished.connect(setter(line.text))
         pick = QtWidgets.QToolButton()
         pick.setText("...")
         pick.setToolTip("Pick a colour")

         def choose() -> None:
            """!Picks a colour with the colour dialog.
            @return None
            """
            colour = QtWidgets.QColorDialog.getColor(QtGui.QColor(line.text() or "#ffffff"), self, spec.title)
            if colour.isValid():
               line.setText(colour.name())
               setter(line.text)()

         pick.clicked.connect(lambda _c=False: choose())
         lay = QtWidgets.QHBoxLayout(row)
         lay.setContentsMargins(0, 0, 0, 0)
         lay.addWidget(line, 1)
         lay.addWidget(pick)
         return row
      line = QtWidgets.QLineEdit(str(value or ""))
      line.editingFinished.connect(setter(line.text))
      if spec.help:
         line.setToolTip(spec.help)
      return line

   def _place(self, element: model.Element) -> None:
      """!Moves the element to the X and Y fields.
      @param element  the element as shown
      @return None
      """
      pos = (self.editors["x"].value(), self.editors["y"].value())
      current = self.session.diagram().elements.get(element.element_id)
      if current is not None and current.pos != pos:
         self.session.place(element.element_id, pos)

   def _resize(self, element: model.Element) -> None:
      """!Resizes the element to the Width and Height fields.
      @param element  the element as shown
      @return None
      """
      size = (self.editors["w"].value(), self.editors["h"].value())
      current = self.session.diagram().elements.get(element.element_id)
      if current is not None and self.session.system.element_size(current) != size:
         self.session.resize(element.element_id, size)

   def _apply(self, change: Callable[[], object]) -> None:
      """!Runs a change; a refusal is reported and the form shows the values as they are.
      @param change  the change
      @return None
      """
      try:
         change()
      except ModelError as e:
         self.refused.emit(str(e))
         QtCore.QTimer.singleShot(0, self, lambda: self.refresh())
