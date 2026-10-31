"""!The build settings panel (A-2, A-5): the "build" object of a game's
reference/project.json.

Each setting is a row: a checkbox (unchecked = the engine's default), the
value, and what it does. WAITCNT, the GBA's ROM and SRAM wait states, is
edited by field (wait states per region, prefetch) and also shown as its raw
value. Every change goes through core.project, which checks it with the
engine's tools/build_settings.py, so the panel accepts exactly what the build
accepts; each change is one undo step. Problems and cautions are listed at
the bottom.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ...core import project
from ..panel import EditorPanel
from ..widgets import set_enabled

if TYPE_CHECKING:
   from ..panel import PanelHost

## A setting's value: an int, or the text of a hex field.
SettingValue = int | str

## What one arrow step of a PowerOfTwoSpinBox multiplies (up) or divides (down) the value by.
POWER_STEP_FACTOR = 2
## Grid column of a row's check box.
CHECK_COLUMN = 0
## Grid column of a row's value widget.
VALUE_COLUMN = 1
## Grid column of a row's description (the one that stretches).
TEXT_COLUMN = 2
## Grid columns in all (full-width rows span them).
GRID_COLUMNS = 3
## Grid row of the title.
TITLE_ROW = 0
## Grid row of the hint below the title.
HINT_ROW = 1
## Grid row of the first setting (after the title and the hint).
FIRST_SETTING_ROW = 2
## Widest a value widget gets, pixels.
VALUE_WIDTH = 120

## Labels of the WAITCNT fields.
WAITCNT_LABELS = {
   "sram": "SRAM wait states",
   "ws0_first": "ROM (WS0) first access",
   "ws0_second": "ROM (WS0) sequential access",
   "ws1_first": "WS1 first access",
   "ws1_second": "WS1 sequential access",
   "ws2_first": "WS2 first access",
   "ws2_second": "WS2 sequential access",
   "phi": "PHI terminal output",
   "prefetch": "Prefetch buffer",
}


class PowerOfTwoSpinBox(QtWidgets.QSpinBox):
   """!A spin box whose arrows double and halve the value."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the box.
      @param parent  parent widget
      """
      super().__init__(parent)
      self.setToolTip("A power of two (the arrows double and halve it)")

   def stepBy(self, steps: int) -> None:
      """!Doubles or halves the value per step.
      @param steps  steps (positive: up)
      @return None
      """
      value = self.value()
      for _ in range(abs(steps)):
         value = value * POWER_STEP_FACTOR if steps > 0 else value // POWER_STEP_FACTOR
      self.setValue(max(self.minimum(), min(self.maximum(), value)))


class BuildSettingsPanel(EditorPanel):
   """!Edits a project's build settings."""

   ## Identifier used on the command line and in settings.
   panel_id = "build"
   ## Tab title.
   title = "Build settings"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost (provides document, apply(), show_status())
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## True while refresh() fills the widgets (their signals change nothing then).
      self._loading = False
      ## key -> (QCheckBox, value widget).
      self.rows = {}
      ## WAITCNT field name -> QComboBox.
      self.fields = {}
      ## key -> the value a row had before it was unticked (ticking it again restores it).
      self.remembered = {}
      form = QtWidgets.QGridLayout(self)
      form.setColumnStretch(TEXT_COLUMN, 1)
      title = QtWidgets.QLabel("<b>Runtime build settings</b>")
      hint = QtWidgets.QLabel("Unchecked settings use the engine's default. A CMake cache variable of the same "
                              "name (for example CAPSULE_VRAM_BUDGET_CYCLES) overrides every game's value.")
      hint.setWordWrap(True)
      form.addWidget(title, TITLE_ROW, 0, 1, GRID_COLUMNS)
      form.addWidget(hint, HINT_ROW, 0, 1, GRID_COLUMNS)
      r = FIRST_SETTING_ROW
      bs = project.settings_tool()
      for s in bs.SETTINGS:
         use = QtWidgets.QCheckBox(s.key)
         use.setToolTip(f"Set {s.key} for this game (unchecked: engine default {s.show(s.default)})")
         if s.hex_value:
            value = QtWidgets.QLineEdit()
            value.setMaximumWidth(VALUE_WIDTH)
            value.editingFinished.connect(lambda k=s.key: self._value_edited(k))
         else:
            value = PowerOfTwoSpinBox() if s.power_of_two else QtWidgets.QSpinBox()
            value.setRange(s.lo, s.hi)
            # [S6] UM: a setting whose value is a multiple (screen_arena_bytes: words) steps by it
            value.setSingleStep(max(1, getattr(s, "multiple", 1)))
            value.setMaximumWidth(VALUE_WIDTH)
            # Arrows, the wheel, Enter and leaving the box commit (not every typed digit).
            value.setKeyboardTracking(False)
            value.valueChanged.connect(lambda _v, k=s.key: self._value_edited(k))
         use.toggled.connect(lambda on, k=s.key: self._use_toggled(k, on))
         text = QtWidgets.QLabel(f"{s.text}. Default {s.show(s.default)}.")
         text.setWordWrap(True)
         form.addWidget(use, r, CHECK_COLUMN)
         form.addWidget(value, r, VALUE_COLUMN)
         form.addWidget(text, r, TEXT_COLUMN)
         self.rows[s.key] = (use, value)
         r += 1
      box = QtWidgets.QGroupBox("WAITCNT fields (GBA)")
      grid = QtWidgets.QFormLayout(box)
      for name, _shift, _width, choices in bs.WAITCNT_FIELDS:
         combo = QtWidgets.QComboBox()
         for c in choices:   # numbers are cycle counts; the other choices are shown as they are
            combo.addItem((f"{c} cycle" + ("" if c == 1 else "s")) if isinstance(c, int) else c, c)
         combo.currentIndexChanged.connect(lambda _i, n=name: self._field_changed(n))
         grid.addRow(WAITCNT_LABELS.get(name, name), combo)
         self.fields[name] = combo
      form.addWidget(box, r, 0, 1, GRID_COLUMNS)
      r += 1
      ## Problems and cautions.
      self.problems = QtWidgets.QLabel()
      self.problems.setWordWrap(True)
      self.problems.setTextFormat(QtCore.Qt.TextFormat.PlainText)
      form.addWidget(self.problems, r, 0, 1, GRID_COLUMNS)
      form.setRowStretch(r + 1, 1)
      self.refresh()

   def refresh(self) -> None:
      """!Shows the document's settings.
      @return None
      """
      doc = self.doc
      set_enabled(self, doc is not None)
      if doc is None:
         return
      self._loading = True
      try:
         try:
            shown = project.rows(doc)
         except project.DocumentError as e:
            self.problems.setText(f"error: {e}")
            for use, value in self.rows.values():
               use.setEnabled(False)
               value.setEnabled(False)
            return
         for row in shown:
            use, value = self.rows[row.key]
            use.setEnabled(True)
            use.setChecked(row.given)
            value.setEnabled(row.given)
            use.setStyleSheet("color: #d04040;" if row.error else "")
            use.setToolTip(row.error or f"Set {row.key} for this game (unchecked: engine default "
                                        f"{row.setting.show(row.setting.default)})")
            if isinstance(value, QtWidgets.QLineEdit):
               value.setText(row.shown)
            else:
               value.setValue(row.value)
            if row.key == "gba_waitcnt":
               decoded = project.settings_tool().decode_waitcnt(row.value)
               for name, combo in self.fields.items():
                  combo.setCurrentIndex(combo.findData(decoded[name]))
                  combo.setEnabled(row.given)
         lines = [f"{sev}: {msg}" for sev, msg in project.problems(doc)]
         self.problems.setText("\n".join(lines))
      finally:
         self._loading = False

   def _value(self, key: str) -> SettingValue:
      """!The value a row's widget holds.
      @param key  setting key
      @return int or str
      """
      widget = self.rows[key][1]
      return widget.text().strip() if isinstance(widget, QtWidgets.QLineEdit) else widget.value()

   def _use_toggled(self, key: str, on: bool) -> None:
      """!A row's checkbox: set the shown value, or go back to the default.
      @param key  setting key
      @param on   checked
      @return None
      """
      if self._loading is True:
         return
      doc = self.doc
      if on:
         value = self.remembered.get(key, self._value(key))
         self.host.apply(f"Set {key}", lambda: project.set_setting(doc, key, value))
      else:
         self.remembered[key] = self._value(key)
         self.host.apply(f"Use the default {key}", lambda: project.clear_setting(doc, key))

   def _value_edited(self, key: str) -> None:
      """!A value was edited.
      @param key  setting key
      @return None
      """
      if self._loading is True or not self.rows[key][0].isChecked():
         return
      doc = self.doc
      value = self._value(key)
      current = next(r for r in project.rows(doc) if r.key == key)
      # Unchanged, whether typed as shown (hex) or as the plain number.
      if str(value) in (current.shown, str(current.value)):
         return
      self.host.apply(f"Set {key}", lambda: project.set_setting(doc, key, value))

   def commit(self) -> None:
      """!Applies an edit still in a text box (before saving or closing).
      @return None
      """
      for key, (use, value) in self.rows.items():
         if isinstance(value, QtWidgets.QLineEdit) and value.isModified():
            value.setModified(False)
            self._value_edited(key)

   def _field_changed(self, name: str) -> None:
      """!A WAITCNT field changed.
      @param name  field name
      @return None
      """
      if self._loading is True:
         return
      doc = self.doc
      choice = self.fields[name].currentData()
      self.host.apply(f"Set WAITCNT {name}", lambda: project.set_waitcnt_fields(doc, {name: choice}))
