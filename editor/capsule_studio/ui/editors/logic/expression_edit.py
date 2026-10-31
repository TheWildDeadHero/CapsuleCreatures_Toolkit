"""!Editors of the ruleset expression language (engine E13a), used by the
Formulas page, the pipeline steps and the generation list's derived
expressions (core.expressions reads the language from the engine):

- FormulaEdit: a one-line field (catalog.ExpressionEdit: completes the word
  at the cursor) that colours the expression as it is typed: numbers,
  inputs, species fields (species.NAME), constants, functions, the bit
  operators & | ^ ~ << >> (their own colour: since E13a they bind tighter
  than the comparisons, the tool tip gives every level), other operators,
  and names the place does not know (red, wavy underline; listed in the
  tool tip);
- FormulaDelegate: the same colours in a table's cells, and a FormulaEdit
  as the cell's editor;
- expression_html(): the coloured expression as rich text (labels, cells).

The colours are set on the field's text layout through an input-method
event that commits nothing (QLineEdit has no syntax highlighter), so the
text, the cursor and the undo history stay as typed.
"""
from __future__ import annotations

import html
from collections.abc import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import expressions
from .catalog import ExpressionEdit

## Colours per span kind (readable on light and dark palettes; the effect editor's set where they match).
KIND_COLOURS = {expressions.KIND_NUMBER: "#c87f1a", expressions.KIND_INPUT: "#2b8a9a",
                expressions.KIND_FIELD: "#9a5fd0", expressions.KIND_CONSTANT: "#5f8a1f",
                expressions.KIND_FUNCTION: "#3d7fd6", expressions.KIND_BIT: "#c0507a",
                expressions.KIND_OPERATOR: "#7f8a96", expressions.KIND_UNKNOWN: "#c03030",
                expressions.KIND_INVALID: "#c03030"}
## Span kinds shown in bold.
BOLD_KINDS = (expressions.KIND_BIT,)
## Span kinds underlined as problems.
PROBLEM_KINDS = (expressions.KIND_UNKNOWN, expressions.KIND_INVALID)
## Pixels between a cell's border and its coloured text.
CELL_MARGIN = 3
## Margins around the text: one on each side.
SIDES = 2
## Divisor that centres the text vertically (half the room left).
HALF = 2


def _format(kind: str) -> QtGui.QTextCharFormat:
   """!The text format of a span kind.
   @param kind  core.expressions KIND_* word
   @return QTextCharFormat
   """
   f = QtGui.QTextCharFormat()
   f.setForeground(QtGui.QColor(KIND_COLOURS.get(kind, KIND_COLOURS[expressions.KIND_OPERATOR])))
   if kind in BOLD_KINDS:
      f.setFontWeight(QtGui.QFont.Weight.Bold)
   if kind in PROBLEM_KINDS:
      f.setUnderlineStyle(QtGui.QTextCharFormat.UnderlineStyle.WaveUnderline)
      f.setUnderlineColor(QtGui.QColor(KIND_COLOURS[expressions.KIND_UNKNOWN]))
   return f


def expression_html(text: str, names: expressions.Names | None) -> str:
   """!An expression as coloured rich text.
   @param text   the expression
   @param names  what its place may name, or None (every name is fine)
   @return HTML
   """
   out = []
   pos = 0
   for s in expressions.spans(text, names):
      out.append(html.escape(text[pos:s.start]))
      style = f"color: {KIND_COLOURS.get(s.kind, KIND_COLOURS[expressions.KIND_OPERATOR])};"
      if s.kind in BOLD_KINDS:
         style += " font-weight: bold;"
      if s.kind in PROBLEM_KINDS:
         style += " text-decoration: underline;"
      out.append(f'<span style="{style}">{html.escape(text[s.start:s.end])}</span>')
      pos = s.end
   out.append(html.escape(text[pos:]))
   return "<span style=\"white-space: pre;\">" + "".join(out) + "</span>"


def precedence_tip() -> str:
   """!The tool tip naming the operator levels.
   @return text
   """
   return ("Operators, loosest first: " + expressions.precedence_text() + "\nThe bit operators & | ^ and the "
           "shifts << >> bind tighter than the comparisons (a & MASK == 0 reads as (a & MASK) == 0); a shift "
           f"amount stays within 0-{expressions.shift_max()}.")


class FormulaEdit(ExpressionEdit):
   """!A one-line ruleset expression field: completion and colours from core.expressions."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the field.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## What the expression may name (None: no names checked).
      self.names = None
      ## Formats per span kind.
      self.formats = {kind: _format(kind) for kind in KIND_COLOURS}
      self.textChanged.connect(lambda _t: self.highlight())
      self.setToolTip(precedence_tip())

   def set_names(self, names: expressions.Names | None) -> None:
      """!Sets what the expression may name (completion and the unknown-name colour).
      @param names  core.expressions.Names, or None
      @return None
      """
      self.names = names
      self.set_words(expressions.completion_words(names) if names is not None else [])
      self.highlight()

   def unknown(self) -> list[str]:
      """!The names the expression uses that its place does not know.
      @return names
      """
      names = self.names   # a local name: Doxygen 1.12 misreads re-assigned members
      return expressions.unknown_names(self.text(), names) if names is not None else []

   def kinds(self) -> list[tuple[str, str]]:
      """!The expression's pieces and their kinds (what the colours show; tests and the tool tip).
      @return [(text, kind)]
      """
      text = self.text()
      return [(text[s.start:s.end], s.kind) for s in expressions.spans(text, self.names)]

   def highlight(self) -> None:
      """!Colours the text: one input-method event whose formats cover the spans and which commits nothing.
      @return None
      """
      cursor = self.cursorPosition()
      attrs = []
      for s in expressions.spans(self.text(), self.names):
         # input-method attribute positions are relative to the cursor
         attrs.append(QtGui.QInputMethodEvent.Attribute(QtGui.QInputMethodEvent.AttributeType.TextFormat,
                                                        s.start - cursor, s.end - s.start, self.formats[s.kind]))
      QtCore.QCoreApplication.sendEvent(self, QtGui.QInputMethodEvent("", attrs))
      unknown = self.unknown()
      self.setToolTip(precedence_tip() + (f"\nUnknown here: {', '.join(unknown)}" if unknown else ""))

   def keyReleaseEvent(self, event: QtGui.QKeyEvent) -> None:
      """!Re-colours after a cursor move (the formats are placed relative to the cursor).
      @param event  QKeyEvent
      @return None
      """
      super().keyReleaseEvent(event)
      self.highlight()

   def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
      """!Re-colours after a click moved the cursor.
      @param event  QMouseEvent
      @return None
      """
      super().mouseReleaseEvent(event)
      self.highlight()


class FormulaDelegate(QtWidgets.QStyledItemDelegate):
   """!Coloured expression cells, edited in a FormulaEdit."""

   def __init__(self, names_of: Callable[[QtCore.QModelIndex], expressions.Names | None],
                parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the delegate.
      @param names_of  callable(index) -> what the cell's expression may name, or None
      @param parent    parent widget
      """
      super().__init__(parent)
      ## Names per cell.
      self.names_of = names_of

   def createEditor(self, parent: QtWidgets.QWidget, _option: QtWidgets.QStyleOptionViewItem,
                    index: QtCore.QModelIndex) -> QtWidgets.QWidget:
      """!A FormulaEdit for the cell.
      @param parent   the view's viewport
      @param _option  style option
      @param index    the cell
      @return the editor
      """
      edit = FormulaEdit(parent)
      edit.set_names(self.names_of(index))
      return edit

   def setEditorData(self, editor: QtWidgets.QWidget, index: QtCore.QModelIndex) -> None:
      """!Puts the cell's text in the editor.
      @param editor  the FormulaEdit
      @param index   the cell
      @return None
      """
      if isinstance(editor, FormulaEdit):
         editor.setText(str(index.data() or ""))
      else:
         super().setEditorData(editor, index)

   def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem,
             index: QtCore.QModelIndex) -> None:
      """!Draws the cell's background, then the coloured expression.
      @param painter  QPainter
      @param option   style option
      @param index    the cell
      @return None
      """
      opt = QtWidgets.QStyleOptionViewItem(option)
      self.initStyleOption(opt, index)
      text = opt.text
      opt.text = ""
      style = opt.widget.style() if opt.widget is not None else QtWidgets.QApplication.style()
      style.drawControl(QtWidgets.QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
      doc = QtGui.QTextDocument()
      doc.setDefaultFont(opt.font)
      doc.setDocumentMargin(0)
      doc.setHtml(expression_html(text, self.names_of(index)))
      rect = style.subElementRect(QtWidgets.QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
      painter.save()
      painter.setClipRect(rect)
      # vertically centred, CELL_MARGIN from the left edge
      painter.translate(rect.left() + CELL_MARGIN, rect.top() + (rect.height() - doc.size().height()) / HALF)
      doc.drawContents(painter)
      painter.restore()

   def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> QtCore.QSize:
      """!The plain text's size plus the margin (resizeColumnsToContents()).
      @param option  style option
      @param index   the cell
      @return QSize
      """
      size = super().sizeHint(option, index)
      return QtCore.QSize(size.width() + SIDES * CELL_MARGIN, size.height())
