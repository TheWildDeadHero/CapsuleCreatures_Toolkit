"""!The settings box of a movement (I3 "movement_args"): the widgets the chosen movement takes, as the engine's
object_compiler.MOVEMENT_ARGS lists them (turn / roam: choices and delays, watch_runner; rotate: clockwise; circuit:
four legs; mirror: its reference facing and the vehicle class whose terrain it keeps to; in_place: the pace; static:
keep_facing). Every change hands the whole settings object to a callback (None when it holds nothing)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6 import QtWidgets

from capsule_studio.core import objects

## A movement's settings, as the manifest holds them.
Args = dict[str, Any]

## Entries of a choice table or a circuit.
TABLE = 4
## Choices of a two-way table.
TWO = 2
## The choice counts offered (2 or 4 directions).
CHOICE_COUNTS = ("2", "4")
## The flag settings and their box texts.
FLAGS = {"watch_runner": "turns to a running player in its sight", "clockwise": "turns clockwise",
         "keep_facing": "keeps a facing a script gives it"}
## The keep_to entry meaning "none" (any cell it may enter).
ANY_CLASS = ""


class MovementArgsBox(QtWidgets.QWidget):
   """!The settings of one movement; set_movement() shows the widgets it takes, fill() their values."""

   def __init__(self, on_change: Callable[[Args | None], object]) -> None:
      """!Builds every setting's widget (shown as the movement needs them).
      @param on_change  callable(the new settings, or None for none) after the user changed one
      """
      super().__init__()
      ## The callback.
      self._on_change = on_change
      ## True while the box fills its widgets.
      self._filling = False
      ## The movement shown.
      self.movement = "static"
      ## The world's vehicle class names (keep_to).
      self.classes = []
      dirs = objects.DIRECTIONS
      ## How many choices a turn / roam draws from.
      self.count = QtWidgets.QComboBox()
      self.count.addItems(list(CHOICE_COUNTS))
      self.count.setToolTip("A turn draws one of 2 or 4 directions (4 may repeat one to weight it)")
      ## The choice table (or the circuit's legs).
      self.table = [QtWidgets.QComboBox() for _ in range(TABLE)]
      for c in self.table:
         c.addItems(dirs)
      ## The delay table.
      self.delays = QtWidgets.QComboBox()
      self.delays.addItems(objects.delay_words())
      self.delays.setToolTip("medium: 32-128 frames between turns; short: 32-80")
      ## A mirror's reference facing.
      self.facing = QtWidgets.QComboBox()
      self.facing.addItems(dirs)
      self.facing.setToolTip("The player's moves are turned by the angle from the player's facing at spawn to this")
      ## A mirror's vehicle class.
      self.keep_to = QtWidgets.QComboBox()
      self.keep_to.setToolTip("The vehicle class whose terrain the mirror keeps to (none: any cell it may enter)")
      ## An in_place's pace.
      self.pace = QtWidgets.QComboBox()
      self.pace.addItems(objects.pace_words())
      ## The flag settings.
      self.flags = {k: QtWidgets.QCheckBox(text) for k, text in FLAGS.items()}
      for w in [self.count, self.delays, self.facing, self.keep_to, self.pace] + self.table:
         w.activated.connect(lambda *a: self._changed())
      for w in self.flags.values():
         w.clicked.connect(lambda *a: self._changed())
      table_row = QtWidgets.QHBoxLayout()
      for c in self.table:
         table_row.addWidget(c)
      ## The table's label (choices or legs).
      self.table_label = QtWidgets.QLabel("Choices")
      form = QtWidgets.QFormLayout(self)
      form.setContentsMargins(0, 0, 0, 0)
      ## Rows: setting -> (label, widget or layout).
      self._rows: dict[str, tuple[QtWidgets.QLabel | None, Any]] = {}
      for key, label, widget in (("count", "Choose from", self.count), ("table", self.table_label, table_row),
                                 ("delays", "Delays", self.delays), ("facing", "Reference facing", self.facing),
                                 ("keep_to", "Keeps to", self.keep_to), ("pace", "Pace", self.pace)):
         form.addRow(label, widget)
         self._rows[key] = (form.labelForField(widget), widget)
      for key, w in self.flags.items():
         form.addRow("", w)
         self._rows[key] = (None, w)

   def _show(self, key: str, shown: bool) -> None:
      """!Shows or hides one setting's row.
      @param key    row key
      @param shown  visible
      @return None
      """
      label, widget = self._rows[key]
      parts = [widget] if isinstance(widget, QtWidgets.QWidget) else [widget.itemAt(i).widget()
                                                                         for i in range(widget.count())]
      for w in parts + ([label] if label is not None else []):
         w.setVisible(shown)

   def set_movement(self, movement: str, classes: list[str]) -> None:
      """!Shows the settings a movement takes.
      @param movement  movement name
      @param classes   the world's vehicle class names
      @return None
      """
      self.movement = movement
      self.classes = list(classes)
      takes = set(objects.movement_args_of(movement))
      self._show("count", "choices" in takes)
      self._show("table", "choices" in takes or "legs" in takes)
      self.table_label.setText("Legs" if "legs" in takes else "Choices")
      for key in ("delays", "facing", "keep_to", "pace") + tuple(FLAGS):
         self._show(key, key in takes)
      self.setVisible(bool(takes))

   def fill(self, args: Args | None) -> None:
      """!Shows a movement's settings (the engine's defaults for those it leaves out).
      @param args  the "movement_args" object, or None
      @return None
      """
      a = args if isinstance(args, dict) else {}
      self._filling = True
      try:
         table = a.get("legs") if "legs" in objects.movement_args_of(self.movement) else a.get("choices")
         table = table if isinstance(table, list) and table else list(objects.DIRECTIONS)
         self.count.setCurrentText(str(TWO if len(table) == TWO else TABLE))
         for k, c in enumerate(self.table):
            c.setCurrentText(table[k] if k < len(table) else objects.DIRECTIONS[k])
            c.setEnabled(k < TWO or len(table) != TWO or "legs" in objects.movement_args_of(self.movement))
         self.delays.setCurrentText(a.get("delays", objects.delay_words()[0]))
         self.facing.setCurrentText(a.get("facing", "up"))
         self.keep_to.clear()
         self.keep_to.addItems([ANY_CLASS] + self.classes)
         self.keep_to.setCurrentText(a.get("keep_to", ANY_CLASS))
         self.pace.setCurrentText(a.get("pace", "walk"))
         for k, w in self.flags.items():
            w.setChecked(a.get(k) is True)
      finally:
         self._filling = False

   def value(self) -> Args | None:
      """!The settings the widgets show, for the movement shown (defaults left out).
      @return the settings, or None for none
      """
      takes = set(objects.movement_args_of(self.movement))
      out: Args = {}
      if "choices" in takes:
         n = int(self.count.currentText())
         choices = [c.currentText() for c in self.table[:n]]
         if choices != list(objects.DIRECTIONS):   # the engine's default: all four, in order
            out["choices"] = choices
      if "delays" in takes and self.delays.currentText() != objects.delay_words()[0]:
         out["delays"] = self.delays.currentText()
      if "legs" in takes:
         out["legs"] = [c.currentText() for c in self.table]
      if "facing" in takes and self.facing.currentText() != "up":
         out["facing"] = self.facing.currentText()
      if "keep_to" in takes and self.keep_to.currentText() != ANY_CLASS:
         out["keep_to"] = self.keep_to.currentText()
      if "pace" in takes and self.pace.currentText() != "walk":
         out["pace"] = self.pace.currentText()
      for k, w in self.flags.items():
         if k in takes and w.isChecked():
            out[k] = True
      return out or None

   def _changed(self) -> None:
      """!A setting changed: the callback gets the whole object.
      @return None
      """
      if self._filling:
         return
      for k, c in enumerate(self.table):   # a two-way table uses its first two entries only
         c.setEnabled(k < TWO or self.count.currentText() != str(TWO) or
                      "legs" in objects.movement_args_of(self.movement))
      self._on_change(self.value())
