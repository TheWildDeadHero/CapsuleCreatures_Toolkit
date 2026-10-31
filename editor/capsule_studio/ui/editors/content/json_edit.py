"""!The JSON text editor the Moves panel (effect lists) and the Data panel use:
a text box with an Apply button and a parse error line.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6 import QtGui, QtWidgets

from ...widgets import button, lock_view

if TYPE_CHECKING:
   from ..battle_common import JsonValue

def json_text(value: JsonValue) -> str:
   """!Pretty JSON for text editors.
   @param value  JSON value
   @return text
   """
   return json.dumps(value, indent=1, ensure_ascii=False)


class JsonEdit(QtWidgets.QWidget):
   """!A JSON text editor with an Apply button and a parse error line."""

   def __init__(self, on_apply: Callable[[JsonValue], object], parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the editor.
      @param on_apply  callable(value) called with the parsed JSON
      @param parent    parent widget
      """
      super().__init__(parent)
      ## The text.
      self.text = QtWidgets.QPlainTextEdit()
      self.text.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
      ## Parse errors.
      self.status = QtWidgets.QLabel()
      ## Apply callback.
      self._on_apply = on_apply
      ## Value last shown (unapplied typing survives refreshes that don't change it).
      self._shown = None
      lay = QtWidgets.QVBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(self.text, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.status, 1)
      ## The Apply button (disabled while read only).
      self.apply_button = button("Apply", lambda: self.apply())
      row.addWidget(self.apply_button)
      lay.addLayout(row)
      ## What the read-only state says (None: editable; see set_read_only()).
      self._read_only_note = None

   def set_read_only(self, note: str | None) -> None:
      """!Shows the value read only (no typing, no Apply) with a note saying where it is edited, or makes it
      editable again.
      @param note  the note, or None for editable
      @return None
      """
      self._read_only_note = note
      self.text.setReadOnly(note is not None)
      self.apply_button.setEnabled(note is None)
      self.status.setText(note or "")

   def set_editable(self, on: bool) -> None:
      """!Greys the editor out (the value is not used), or brings it back. Not setEnabled(False): the text keeps
      its scroll bar, so a long value can still be read.
      @param on  True to edit
      @return None
      """
      lock_view(self.text, not on)
      self.apply_button.setEnabled(on and self._read_only_note is None)
      self.status.setEnabled(on)

   def set_value(self, value: JsonValue) -> None:
      """!Shows a value (replacing unapplied typing).
      @param value  JSON value
      @return None
      """
      if self.text.document().isModified() and value == self._shown:
         self.status.setText("Not applied yet.")
         return
      self._shown = value
      self.text.blockSignals(True)
      self.text.setPlainText(json_text(value) if value is not None else "")
      self.text.document().setModified(False)
      self.text.blockSignals(False)
      self.status.setText(self._read_only_note or "")

   def discard(self, value: JsonValue) -> None:
      """!Shows a value even over unapplied typing (another entry was picked).
      @param value  JSON value
      @return None
      """
      self.text.document().setModified(False)
      self.set_value(value)

   def apply(self) -> None:
      """!Parses the text and hands it on (nothing while read only).
      @return None
      """
      if self._read_only_note is not None:
         return
      try:
         value = json.loads(self.text.toPlainText())
      except json.JSONDecodeError as e:
         self.status.setText(f"JSON error, line {e.lineno}: {e.msg}")
         return
      self.status.setText("")
      self.text.document().setModified(False)
      self._on_apply(value)
