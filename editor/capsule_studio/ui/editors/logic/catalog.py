"""!Widgets of the Effects panel that show the effect language's catalogs
(D-23 §3.3), all read from core.logic (which reads the engine's effect
compiler):
- EffectHighlighter: .ceffect syntax colours for the studio's CodeEditor
  (ui/editors/script.py), the words from core.logic.words();
- ExpressionEdit: a one-line expression field that completes the word at the
  cursor (context words, reads, functions, the battle's names);
- HookPicker: the hook / move phase / point a handler runs on, with what the
  catalog says about it (context bindings, value, verdicts, draws, may
  yield, per_foe);
- RefPicker: builds a read of a subject's field ("holder.stat(atk)") from the
  compiler's ref tables, with the argument picked from the battle's
  structure (stats and stages, statuses, volatiles, flags, types, roles,
  points);
- FunctionPicker: inserts a call of one of the language's functions
  (core.logic.function_catalog(): signature and help), with the argument
  count for a function that takes several (odds(n, m[, by, on]): 2 to 4,
  the battlers user / target).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import logic

if TYPE_CHECKING:
   from ....core.battle import BattleProject

## Colours per token class (readable on light and dark palettes; the script editor's set).
COLOURS = {"keyword": "#3d7fd6", "primitive": "#2b8a9a", "owner": "#9a5fd0", "hook": "#c0507a",
           "context": "#b8661a", "string": "#2f9a52", "number": "#c87f1a", "comment": "#7f8a96"}
## Characters of the word being completed (a dotted read counts as one word).
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*$")
## Most completions the popup lists.
COMPLETION_ROWS = 12
## Picker group of each subject choice after the battler subjects (core.logic.battler_subjects(), group
## "battler"): (text, ref_catalog() group).
OTHER_SUBJECT_GROUPS = [("move", "move"), ("field", "field"), ("side(holder)", "side"), ("side(other)", "side"),
                        ("(global)", "global")]
## The ref_catalog() group of the battler subjects.
BATTLER_GROUP = "battler"
## Structure lists a ref argument kind reads its names from (core.logic.name_lists() keys).
ARG_LISTS = {"stats": ["stats"], "stages": ["stages"], "types": ["types"], "roles": ["roles"],
             "counters": [logic.COUNTER_LIST], "words": [logic.WORD_LIST], "has": ["volatiles", "tags", "statuses"],
             "move_flags": ["move_flags"], "points": ["points"], "side_conditions": ["side_conditions"],
             "field_conditions": ["field_conditions"], "species_fields": ["species_fields"]}
## Index of the description in a HookPicker choice (member key, name, description).
CHOICE_TEXT = 2
## RefPicker grid columns: subject, field, argument (the preview spans the first two).
SUBJECT_COLUMN = 0
## See SUBJECT_COLUMN.
FIELD_COLUMN = 1
## See SUBJECT_COLUMN.
ARG_COLUMN = 2
## FunctionPicker grid row of the function and its argument count (columns as the RefPicker's).
CHOICE_ROW = 0
## FunctionPicker grid row of the help.
HELP_ROW = 1
## FunctionPicker grid row of the call and its Insert button.
CALL_ROW = 2
## Text of a catalog entry that has no value.
NO_VALUE = "-"


def _format(colour: str, bold: bool = False, italic: bool = False) -> QtGui.QTextCharFormat:
   """!A text format.
   @param colour  hex colour
   @param bold    bold
   @param italic  italic
   @return QTextCharFormat
   """
   f = QtGui.QTextCharFormat()
   f.setForeground(QtGui.QColor(colour))
   if bold:
      f.setFontWeight(QtGui.QFont.Weight.Bold)
   if italic:
      f.setFontItalic(True)
   return f


def _word_rule(words: list[str], fmt: QtGui.QTextCharFormat) -> tuple[re.Pattern[str], QtGui.QTextCharFormat]:
   """!A rule colouring whole words.
   @param words  the words
   @param fmt    their format
   @return (regex, format)
   """
   return re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")\b"), fmt


class EffectHighlighter(QtGui.QSyntaxHighlighter):
   """!Syntax colours for .ceffect: keywords, primitives, owner kinds, hooks, context words, strings, numbers
   and `#` comments (the language has no block comments)."""

   def __init__(self, document: QtGui.QTextDocument) -> None:
      """!Attaches to a text document.
      @param document  QTextDocument
      """
      super().__init__(document)
      w = logic.words()
      ## (regex, format) in order: later rules win where they overlap.
      self.rules = [
         _word_rule(w["context"], _format(COLOURS["context"])),
         _word_rule(w["hooks"], _format(COLOURS["hook"])),
         _word_rule(w["primitives"] + w["functions"], _format(COLOURS["primitive"])),
         _word_rule(w["keywords"] + w["modes"], _format(COLOURS["keyword"], bold=True)),
         _word_rule(w["owners"], _format(COLOURS["owner"], bold=True)),
         (re.compile(r"\b([0-9]+\.[0-9]+|0[xX][0-9A-Fa-f]+|[0-9]+)\b"), _format(COLOURS["number"])),
         (re.compile(r"\"(?:[^\"\\]|\\.)*\""), _format(COLOURS["string"])),
      ]
      ## Comment format.
      self.comment = _format(COLOURS["comment"], italic=True)

   def highlightBlock(self, text: str) -> None:
      """!Colours one line.
      @param text  the line
      @return None
      """
      rules = self.rules
      for rx, fmt in rules:
         for m in rx.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), fmt)
      # A '#' outside a string starts a comment to the end of the line.
      in_string = False
      escaped = False
      for i, c in enumerate(text):
         if in_string:
            escaped = c == "\\" and not escaped
            if c == "\"" and not escaped:
               in_string = False
         elif c == "\"":
            in_string = True
         elif c == "#":
            self.setFormat(i, len(text) - i, self.comment)
            return


def subject_groups() -> list[tuple[str, str]]:
   """!The RefPicker's subject choices: (text, ref_catalog() group), the battler subjects first.
   @return choices
   """
   return [(s, BATTLER_GROUP) for s in logic.battler_subjects()] + OTHER_SUBJECT_GROUPS


def completion_words(project: BattleProject | None) -> list[str]:
   """!What an expression field completes: context words, reads ("holder.hp", "move.type"), functions and
   the battle's names.
   @param project  BattleProject, or None
   @return sorted words without repeats
   """
   w = logic.words()
   out = set(w["context"]) | set(w["functions"]) | {"and", "or", "not", "true", "false"}
   for group, rows in logic.ref_catalog().items():
      if group == "battler":
         out |= {f"{s}.{field}" for s in logic.battler_subjects() for field, _arg, _kind in rows}
      elif group in ("move", "field"):
         out |= {f"{group}.{field}" for field, _arg, _kind in rows}
   if project is not None:
      for names in logic.name_lists(project).values():
         out |= {n for n in names if isinstance(n, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n)}
   return sorted(out)


class ExpressionEdit(QtWidgets.QLineEdit):
   """!An expression field: completes the word before the cursor from completion_words()."""

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the field.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The word list model.
      self.model = QtCore.QStringListModel(self)
      ## The popup completer (the word before the cursor is its prefix).
      self.completer = QtWidgets.QCompleter(self.model, self)
      self.completer.setWidget(self)
      self.completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
      self.completer.setMaxVisibleItems(COMPLETION_ROWS)
      self.completer.activated.connect(lambda text: self.complete_with(text))
      self.textEdited.connect(lambda _t: self._suggest())

   def set_words(self, words: list[str]) -> None:
      """!Sets what the field completes.
      @param words  completion_words()
      @return None
      """
      self.model.setStringList(words)

   def current_word(self) -> str:
      """!The word before the cursor.
      @return it ("" for none)
      """
      m = WORD_RE.search(self.text()[:self.cursorPosition()])
      return m.group() if m else ""

   def _suggest(self) -> None:
      """!Shows the completions of the word before the cursor.
      @return None
      """
      word = self.current_word()
      if not word:
         self.completer.popup().hide()
         return
      self.completer.setCompletionPrefix(word)
      if self.completer.completionCount() > 0:
         self.completer.complete()
      else:
         self.completer.popup().hide()

   def complete_with(self, text: str) -> None:
      """!Replaces the word before the cursor by a completion.
      @param text  the completion
      @return None
      """
      pos = self.cursorPosition()
      word = self.current_word()
      before = self.text()[:pos - len(word)]
      self.setText(before + text + self.text()[pos:])
      self.setCursorPosition(len(before) + len(text))

   def insert_text(self, text: str) -> None:
      """!Inserts text at the cursor (the ref picker's read).
      @param text  the text
      @return None
      """
      self.insert(text)
      self.setFocus()


def describe_hook(entry: dict[str, Any]) -> str:
   """!What the catalog says about a hook or phase, as lines.
   @param entry  a core.logic.hook_catalog() row
   @return text
   """
   value = entry["value"]
   lines = [entry["binds"],
            f"value: {value[0]}..{value[1]}" if value is not None else f"value: {NO_VALUE} (no modify)",
            "verdicts: " + (", ".join(entry["results"]) or NO_VALUE),
            "engine draws: " + (entry["draws"] or "none"),
            "may yield / ask: " + ("yes" if entry["yields"] else "no")]
   if entry["per_foe"]:
      lines.append("per_foe: runs once per foe")
   lines.append("held by: " + ", ".join(entry["owners"]))
   return "\n".join(lines)


def describe_point(entry: dict[str, Any]) -> str:
   """!What the catalog says about a point, as lines.
   @param entry  a core.logic.point_catalog() row
   @return text
   """
   rng = entry["range"]
   return "\n".join([f"point {entry['id']}: modifies the ruleset value, pure code",
                     f"holder: {entry['holder']}", "sources: " + (", ".join(entry["sources"]) or NO_VALUE),
                     f"range: {rng[0]}..{rng[1]}" if rng else f"range: {NO_VALUE}",
                     "draws: none (pure)", "may yield / ask: no"])


class HookPicker(QtWidgets.QWidget):
   """!Picks the hook, move phase or point of a handler for one owner kind, and shows its catalog entry. The
   choice is a member: ("on" | "phase" | "point", name).

   @var choices
   Choices: (member key, name, description).
   @var per_foe_hooks
   Names of the hooks that take per_foe.
   """

   ## Emitted when the user picks another entry.
   picked = QtCore.Signal()

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the picker.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## Hooks, phases and points.
      self.combo = QtWidgets.QComboBox()
      self.combo.setToolTip("The hook, move phase or ruleset point the handler runs on")
      ## The catalog entry of the choice.
      self.info = QtWidgets.QLabel()
      self.info.setWordWrap(True)
      self.info.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## Choices: (member key, name, description).
      self.choices: list[tuple[str, str, str]] = []
      ## Names of the hooks that take per_foe.
      self.per_foe_hooks = set()
      lay = QtWidgets.QVBoxLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(self.combo)
      lay.addWidget(self.info)
      self.combo.currentIndexChanged.connect(lambda _i: self._show())
      self.combo.activated.connect(lambda _i: self.picked.emit())

   def fill(self, project: BattleProject | None, kind: str | None) -> None:
      """!Lists what an owner kind may hold (keeps the choice when it is still there).
      @param project  BattleProject (its ruleset's points), or None
      @param kind     owner kind, or None for nothing
      @return None
      """
      keep = self.choice()
      self.choices = []
      self.per_foe_hooks = set()
      if kind is not None:
         for h in logic.hook_catalog(kind):
            self.choices.append(("phase" if h["phase"] else "on", h["name"], describe_hook(h)))
            if h["per_foe"]:
               self.per_foe_hooks.add(h["name"])
         if project is not None:
            self.choices += [("point", pt["name"], describe_point(pt)) for pt in logic.point_catalog(project)]
      self.combo.blockSignals(True)
      self.combo.clear()
      for key, name, _desc in self.choices:
         self.combo.addItem(name if key == "phase" else f"{key} {name}")
      self.combo.blockSignals(False)
      if keep is not None:
         self.set_choice(*keep)
      self._show()

   def choice(self) -> tuple[str, str] | None:
      """!The member picked.
      @return (member key, name), or None
      """
      i = self.combo.currentIndex()
      return (self.choices[i][0], self.choices[i][1]) if 0 <= i < len(self.choices) else None

   def set_choice(self, key: str, name: str) -> None:
      """!Shows a member (without emitting picked).
      @param key   "on", "phase" or "point"
      @param name  its name
      @return None
      """
      for i, (k, n, _d) in enumerate(self.choices):
         if (k, n) == (key, name):
            self.combo.setCurrentIndex(i)
            return

   def _show(self) -> None:
      """!Shows the catalog entry of the choice.
      @return None
      """
      i = self.combo.currentIndex()
      self.info.setText(self.choices[i][CHOICE_TEXT] if 0 <= i < len(self.choices) else "")


class RefPicker(QtWidgets.QWidget):
   """!Builds a read: a subject, one of its fields (the compiler's ref tables) and, when the field takes one,
   its argument from the battle's structure. Emits picked(text) for "Insert".

   @var lists
   The battle's names by list.
   """

   ## Emitted with the read's text.
   picked = QtCore.Signal(str)

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the picker.
      @param parent  parent widget
      """
      super().__init__(parent)
      ## The compiler's reads by group.
      self.refs = logic.ref_catalog()
      ## The subject choices (subject_groups()).
      self.subjects = subject_groups()
      ## The battle's names by list.
      self.lists = {}
      ## Subject.
      self.subject = QtWidgets.QComboBox()
      self.subject.addItems([text for text, _g in self.subjects])
      ## Field.
      self.field = QtWidgets.QComboBox()
      ## Argument (editable: lists the studio does not know yet, e.g. side conditions).
      self.arg = QtWidgets.QComboBox()
      self.arg.setEditable(True)
      ## The read as text.
      self.preview = QtWidgets.QLabel()
      insert = QtWidgets.QPushButton("Insert read")
      insert.setToolTip("Insert this read into the expression field being edited")
      insert.clicked.connect(lambda: self.picked.emit(self.text()))
      lay = QtWidgets.QGridLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(self.subject, 0, SUBJECT_COLUMN)
      lay.addWidget(self.field, 0, FIELD_COLUMN)
      lay.addWidget(self.arg, 0, ARG_COLUMN)
      lay.addWidget(self.preview, 1, SUBJECT_COLUMN, 1, ARG_COLUMN)
      lay.addWidget(insert, 1, ARG_COLUMN)
      self.subject.currentIndexChanged.connect(lambda _i: self._fill_fields())
      self.field.currentIndexChanged.connect(lambda _i: self._fill_args())
      self.arg.currentTextChanged.connect(lambda _t: self._show())
      self._fill_fields()

   def set_lists(self, lists: dict[str, list[str]]) -> None:
      """!The battle's names (core.logic.name_lists()).
      @param lists  {list key: names}
      @return None
      """
      self.lists = lists
      self._fill_args()

   def _group(self) -> str:
      """!The ref group of the subject chosen.
      @return group key
      """
      return self.subjects[max(0, self.subject.currentIndex())][1]

   def _row(self) -> tuple[str, str | None, str] | None:
      """!The field chosen.
      @return (field, argument kind, value kind), or None
      """
      rows = self.refs.get(self._group(), [])
      i = self.field.currentIndex()
      return rows[i] if 0 <= i < len(rows) else None

   def _fill_fields(self) -> None:
      """!Lists the fields of the subject's group.
      @return None
      """
      self.field.blockSignals(True)
      self.field.clear()
      self.field.addItems([f"{name}  ({kind})" for name, _arg, kind in self.refs.get(self._group(), [])])
      self.field.blockSignals(False)
      self._fill_args()

   def _fill_args(self) -> None:
      """!Lists the argument choices of the field.
      @return None
      """
      row = self._row()
      arg = row[1] if row is not None else None
      names: list[str] = []
      for key in ARG_LISTS.get(arg or "", [arg] if arg else []):
         names += [n for n in self.lists.get(key, []) if n not in names]
      if arg == "index":
         names = ["0", "1"]
      self.arg.blockSignals(True)
      self.arg.clear()
      self.arg.addItems(names)
      self.arg.setEnabled(arg is not None)
      self.arg.blockSignals(False)
      self._show()

   def text(self) -> str:
      """!The read as source text.
      @return e.g. "holder.stat(atk)", "move.type", "turn"
      """
      row = self._row()
      if row is None:
         return ""
      field, arg, _kind = row
      subject = self.subjects[max(0, self.subject.currentIndex())][0]
      head = field if self._group() == "global" else f"{subject}.{field}"
      value = self.arg.currentText().strip()
      if arg is not None:
         return f"{head}({logic.format_id(value)})" if value else f"{head}()"
      return head

   def _show(self) -> None:
      """!Shows the read.
      @return None
      """
      self.preview.setText(self.text())


class FunctionPicker(QtWidgets.QWidget):
   """!Inserts a function call: the function (its signature), its help, and its argument count when it takes a
   range of them (core.logic.function_catalog(), function_text()). Emits picked(text) for "Insert".

   @var functions
   core.logic.function_catalog() rows.
   """

   ## Emitted with the call's text.
   picked = QtCore.Signal(str)

   def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the picker.
      @param parent  parent widget
      """
      super().__init__(parent)
      self.functions = logic.function_catalog()
      ## The function (its signature).
      self.function = QtWidgets.QComboBox()
      self.function.addItems([sig for _n, _lo, _hi, sig, _help in self.functions])
      ## The argument count (enabled for a function that takes a range: odds() takes 2 to 4).
      self.count = QtWidgets.QSpinBox()
      self.count.setToolTip("Arguments: odds(n, m) runs user on target; a third names the battler it is by, a "
                            "fourth the battler it is on")
      ## What the function gives.
      self.help = QtWidgets.QLabel()
      self.help.setWordWrap(True)
      ## The call as text.
      self.preview = QtWidgets.QLabel()
      insert = QtWidgets.QPushButton("Insert call")
      insert.setToolTip("Insert this call into the expression field being edited")
      insert.clicked.connect(lambda: self.picked.emit(self.text()))
      lay = QtWidgets.QGridLayout(self)
      lay.setContentsMargins(0, 0, 0, 0)
      lay.addWidget(self.function, CHOICE_ROW, SUBJECT_COLUMN)
      lay.addWidget(QtWidgets.QLabel("Arguments"), CHOICE_ROW, FIELD_COLUMN)
      lay.addWidget(self.count, CHOICE_ROW, ARG_COLUMN)
      lay.addWidget(self.help, HELP_ROW, SUBJECT_COLUMN, 1, ARG_COLUMN + 1)
      lay.addWidget(self.preview, CALL_ROW, SUBJECT_COLUMN, 1, ARG_COLUMN)
      lay.addWidget(insert, CALL_ROW, ARG_COLUMN)
      self.function.currentIndexChanged.connect(lambda _i: self._fill_count())
      self.count.valueChanged.connect(lambda _v: self._show())
      self._fill_count()

   def select(self, name: str) -> bool:
      """!Shows a function.
      @param name  function name
      @return True when the language has it
      """
      names = [n for n, _lo, _hi, _sig, _help in self.functions]
      if name not in names:
         return False
      self.function.setCurrentIndex(names.index(name))
      return True

   def _row(self) -> tuple[str, int, int, str, str] | None:
      """!The function chosen.
      @return function_catalog() row, or None
      """
      i = self.function.currentIndex()
      return self.functions[i] if 0 <= i < len(self.functions) else None

   def _fill_count(self) -> None:
      """!The argument range and help of the chosen function.
      @return None
      """
      row = self._row()
      _name, lo, hi, sig, text = row if row is not None else ("", 0, 0, "", "")
      self.count.blockSignals(True)
      self.count.setRange(lo, hi)
      self.count.setValue(lo)
      self.count.setEnabled(hi > lo)
      self.count.blockSignals(False)
      self.help.setText(f"{sig}: {text}" if text else sig)
      self._show()

   def text(self) -> str:
      """!The call as source text.
      @return e.g. "odds(1, 2, user)"
      """
      row = self._row()
      return logic.function_text(row[0], self.count.value()) if row is not None else ""

   def _show(self) -> None:
      """!Shows the call.
      @return None
      """
      self.preview.setText(self.text())
