"""!Widgets of the script editor: a source editor with line numbers, syntax
colours and diagnostic marks for .cscript files (B-4). The colours are
pluggable: CodeEditor takes a highlighter factory (the effect logic's text
view passes its .ceffect highlighter, ui/editors/logic/catalog.py).

[S2] (engine I4): the keyword colours follow the engine's word lists
(core.script_words: every statement, declaration, trigger kind and kind
word, the I4 statements included); CodeEditor completes words from a
completion source (set_completion_source(): the text before the cursor ->
the words that fit there), by itself after AUTO_PREFIX letters of a word or
on Ctrl+Space."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from PySide6 import QtCore, QtGui, QtWidgets

## A diagnostic shown in the editor: (1-based line, 1-based column, severity, message).
Mark = tuple[int, int, str, str]
## Makes the syntax highlighter of an editor's text document.
HighlighterFactory = Callable[[QtGui.QTextDocument], QtGui.QSyntaxHighlighter]

## Words coloured as keywords.
KEYWORDS = ["flag", "var", "const", "native", "script", "map_scripts", "when", "game", "not", "goto", "call", "of",
            "return", "end", "if", "else", "while", "switch", "case", "default", "set", "clear", "msg", "msgbox",
            "wait_button", "close_msg", "yesno", "choice", "cancel", "delay", "waits", "value", "random",
            "on_load", "on_transition", "on_frame", "move", "face", "hide", "show", "self", "player",
            # D-17: move routes, input, messages, warps, camera and screen effects, timers, encounters, queries
            "route", "wait_moves", "input_number", "wait_key", "msg_pos", "warp", "place", "scroll", "tint",
            "flash", "shake", "timer", "encounters", "pos_x", "pos_y", "facing", "map_index", "steps"]
## The engine script compiler's statement words of the field effects and actions (F1, F2), and of each the words
## after it: (word export, kinds export or None).
ENGINE_WORDS = [("FIELD_EFFECT_WORD", "FIELD_EFFECT_KINDS"), ("FIELD_ACTION_WORD", "FIELD_ACTION_KINDS"),
                ("FLIGHT_WORD", "FLIGHT_KINDS"), ("DARKNESS_WORD", None), ("ESCAPE_WORD", None)]


## [S2] engine_keywords() per engine root, once computed.
_engine_words: dict[object, list[str]] = {}


def engine_keywords() -> list[str]:
   """!The keywords the engine's compilers give beyond KEYWORDS (ENGINE_WORDS; [S2] every word of
   core.script_words.keyword_words(): the I4 statements, their kind words, the trigger kinds; none when the engine
   is not found), so the colours follow the engine's statements.
   @return words
   """
   from ...core import engine, script_words   # local: the widgets load without an engine
   try:
      sc = engine.tool("script_compiler")
      root = engine.root()
   except (engine.EngineNotFound, ImportError, OSError):
      return []
   if _engine_words.get(root) is not None:
      return list(_engine_words[root])   # one engine's words, computed once (every editor tab colours with them)
   words = script_words.keyword_words()
   for word, kinds in ENGINE_WORDS:
      if hasattr(sc, word):
         words.append(str(getattr(sc, word)))
         words += [str(k) for k in getattr(sc, kinds, [])] if kinds is not None else []
   _engine_words[root] = [w for w in dict.fromkeys(words) if w not in KEYWORDS]
   return list(_engine_words[root])


## Words coloured as types and lifetimes.
TYPE_WORDS = ["u8", "u16", "u32", "permanent", "daily", "area", "map", "yes", "no", "true", "false"]
## Colours per token class (readable on light and dark palettes).
COLOURS = {"keyword": "#3d7fd6", "type": "#9a5fd0", "string": "#2f9a52", "number": "#c87f1a",
           "comment": "#7f8a96", "ref": "#c0507a"}
## Length of the block comment markers "/*" and "*/".
COMMENT_MARKER_LENGTH = 2
## Block state of a line that ends outside block comments.
OUTSIDE_COMMENT = 0
## Block state of a line that ends inside a block comment.
INSIDE_COMMENT = 1
## Spaces a tab advances.
TAB_SPACES = 4
## Fewest digits the line-number gutter leaves room for.
GUTTER_MIN_DIGITS = 3
## Gutter width beyond the digits, pixels.
GUTTER_PADDING = 10
## Width of a line's error / warning mark at the gutter's left edge, pixels.
MARK_WIDTH = 4
## Space between the line numbers and the text, pixels.
NUMBER_RIGHT_MARGIN = 4
## [S2] Letters of a word typed before the completion list opens by itself.
AUTO_PREFIX = 2
## [S2] Rows the completion list shows.
COMPLETION_ROWS = 12
## [S2] Gives the words that may follow a text (the source before the cursor).
CompletionSource = Callable[[str], list[str]]


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


class ScriptHighlighter(QtGui.QSyntaxHighlighter):
   """!Syntax colours for .cscript (block comments may span lines)."""

   def __init__(self, document: QtGui.QTextDocument) -> None:
      """!Attaches to a text document.
      @param document  QTextDocument
      """
      super().__init__(document)
      ## (regex, format) for single-line rules, in order.
      self.rules = [
         (re.compile(r"\b(" + "|".join(KEYWORDS + engine_keywords()) + r")\b"),
          _format(COLOURS["keyword"], bold=True)),
         (re.compile(r"\b(" + "|".join(TYPE_WORDS) + r")\b"), _format(COLOURS["type"])),
         (re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*:(\"(?:[^\"\\]|\\.)*\"|[A-Za-z0-9_][A-Za-z0-9_.'-]*)"),
          _format(COLOURS["ref"])),
         (re.compile(r"-?\b(0[xX][0-9A-Fa-f]+|[0-9]+)\b"), _format(COLOURS["number"])),
         (re.compile(r"\"(?:[^\"\\]|\\.)*\""), _format(COLOURS["string"])),
         (re.compile(r"//[^\n]*"), _format(COLOURS["comment"], italic=True)),
      ]
      ## Comment format (also for block comments).
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
      # Block comments: state INSIDE_COMMENT = still inside one at the end of the line.
      self.setCurrentBlockState(OUTSIDE_COMMENT)
      i = 0   # a comment left open by the previous line starts at column 0
      if self.previousBlockState() != INSIDE_COMMENT:
         i = text.find("/*")
      while i >= 0:
         # Look for the end past the "/*" (or from column 0 for a comment carried over).
         end = text.find("*/", i + (0 if i == 0 and self.previousBlockState() == INSIDE_COMMENT
                                    else COMMENT_MARKER_LENGTH))
         if end < 0:
            self.setFormat(i, len(text) - i, self.comment)
            self.setCurrentBlockState(INSIDE_COMMENT)
            return
         self.setFormat(i, end + COMMENT_MARKER_LENGTH - i, self.comment)
         i = text.find("/*", end + COMMENT_MARKER_LENGTH)


class _LineNumbers(QtWidgets.QWidget):
   """!The gutter of a CodeEditor."""

   def __init__(self, editor: CodeEditor) -> None:
      """!Creates the gutter.
      @param editor  its CodeEditor
      """
      super().__init__(editor)
      ## The editor.
      self.editor = editor

   def sizeHint(self) -> QtCore.QSize:
      """!Width for the line numbers.
      @return QSize
      """
      return QtCore.QSize(self.editor.gutter_width(), 0)

   def paintEvent(self, event: QtGui.QPaintEvent) -> None:
      """!Draws the numbers (and error marks).
      @param event  QPaintEvent
      @return None
      """
      self.editor.paint_gutter(event)


class CodeEditor(QtWidgets.QPlainTextEdit):
   """!A plain-text editor for one source file, with line numbers, syntax
   colours and wavy underlines at diagnostics."""

   def __init__(self, parent: QtWidgets.QWidget | None = None, highlighter: HighlighterFactory | None = None) -> None:
      """!Creates the editor.
      @param parent       parent widget
      @param highlighter  makes the syntax colours for the text document, or None for .cscript (ScriptHighlighter)
      """
      super().__init__(parent)
      font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
      self.setFont(font)
      self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
      self.setTabStopDistance(QtGui.QFontMetricsF(font).horizontalAdvance(" ") * TAB_SPACES)
      ## Syntax colours.
      self.highlighter = (highlighter or ScriptHighlighter)(self.document())
      ## Gutter widget.
      self.gutter = _LineNumbers(self)
      ## Diagnostics shown: list of (line, col, severity, message).
      self.marks = []
      ## [S2] The completion source, or None (no completion).
      self.completion_source = None
      ## [S5] What a word under the mouse shows when no diagnostic does: callable(text before it, word) -> text or
      ## None (route steps: core.script_words.word_help()), or None.
      self.word_help = None
      ## [S2] The completion list.
      self.completer = QtWidgets.QCompleter([], self)
      self.completer.setWidget(self)
      self.completer.setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
      self.completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseSensitive)
      self.completer.setMaxVisibleItems(COMPLETION_ROWS)
      self.completer.activated.connect(lambda word: self.insert_completion(word))
      self.blockCountChanged.connect(lambda _n: self._update_margins())
      self.updateRequest.connect(lambda rect, dy: self._scroll_gutter(rect, dy))
      self._update_margins()

   def gutter_width(self) -> int:
      """!Width of the line-number gutter.
      @return pixels
      """
      digits = max(GUTTER_MIN_DIGITS, len(str(self.blockCount())))
      return GUTTER_PADDING + self.fontMetrics().horizontalAdvance("9") * digits

   def _update_margins(self) -> None:
      """!Leaves room for the gutter.
      @return None
      """
      self.setViewportMargins(self.gutter_width(), 0, 0, 0)

   def _scroll_gutter(self, rect: QtCore.QRect, dy: int) -> None:
      """!Keeps the gutter in step with the text.
      @param rect  updated area
      @param dy    vertical scroll
      @return None
      """
      if dy:
         self.gutter.scroll(0, dy)
      else:
         self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

   def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
      """!Resizes the gutter with the editor.
      @param event  QResizeEvent
      @return None
      """
      super().resizeEvent(event)
      cr = self.contentsRect()
      self.gutter.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

   def paint_gutter(self, event: QtGui.QPaintEvent) -> None:
      """!Paints line numbers; lines with an error or warning get a mark.
      @param event  QPaintEvent of the gutter
      @return None
      """
      painter = QtGui.QPainter(self.gutter)
      pal = self.palette()
      painter.fillRect(event.rect(), pal.color(QtGui.QPalette.ColorRole.AlternateBase))
      severity: dict[int, str] = {}   # line -> worst severity (an error wins over a warning)
      marks = self.marks
      for line, _col, sev, _msg in marks:
         if severity.get(line) != "error":
            severity[line] = sev
      block = self.firstVisibleBlock()
      # The first visible line's top, in gutter coordinates (the text's scroll offset applied).
      top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
      h = self.fontMetrics().height()
      while block.isValid() and top <= event.rect().bottom():
         n = block.blockNumber() + 1
         if block.isVisible():
            sev = severity.get(n)
            if sev:
               painter.fillRect(0, top, MARK_WIDTH, h, QtGui.QColor("#d04040" if sev == "error" else "#d0a020"))
            painter.setPen(pal.color(QtGui.QPalette.ColorRole.PlaceholderText))
            painter.drawText(0, top, self.gutter.width() - NUMBER_RIGHT_MARGIN, h, QtCore.Qt.AlignmentFlag.AlignRight,
                             str(n))
         block = block.next()
         top += round(self.blockBoundingRect(block).height()) if block.isValid() else h

   def set_marks(self, marks: Iterable[Mark]) -> None:
      """!Shows diagnostics: a wavy underline from the column to the end of
      the word, and a mark in the gutter.
      @param marks  list of (line, col, severity, message)
      @return None
      """
      self.marks = list(marks)
      selections = []
      for line, col, sev, msg in self.marks:
         block = self.document().findBlockByNumber(max(0, line - 1))
         if not block.isValid():
            continue
         cur = QtGui.QTextCursor(block)
         cur.movePosition(QtGui.QTextCursor.MoveOperation.Right, n=max(0, col - 1))
         cur.movePosition(QtGui.QTextCursor.MoveOperation.EndOfWord, QtGui.QTextCursor.MoveMode.KeepAnchor)
         if not cur.hasSelection():
            cur.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock, QtGui.QTextCursor.MoveMode.KeepAnchor)
         sel = QtWidgets.QTextEdit.ExtraSelection()
         fmt = QtGui.QTextCharFormat()
         fmt.setUnderlineStyle(QtGui.QTextCharFormat.UnderlineStyle.WaveUnderline)
         fmt.setUnderlineColor(QtGui.QColor("#d04040" if sev == "error" else "#d0a020"))
         fmt.setToolTip(msg)
         sel.format = fmt
         sel.cursor = cur
         selections.append(sel)
      self.setExtraSelections(selections)
      self.gutter.update()

   # -- completion [S2] ---------------------------------------------------------------------------------------

   def set_completion_source(self, source: CompletionSource | None) -> None:
      """!Turns completion on with a source of words (or off).
      @param source  the text before the cursor -> the words that fit there, or None
      @return None
      """
      self.completion_source = source

   def _typed_prefix(self) -> str:
      """!The part of a word left of the cursor.
      @return letters, digits and _ (may be empty)
      """
      cur = self.textCursor()
      line = cur.block().text()[:cur.positionInBlock()]
      i = len(line)
      while i > 0 and (line[i - 1].isalnum() or line[i - 1] == "_"):
         i -= 1
      return line[i:]

   def completions(self) -> list[str]:
      """!The words the source offers at the cursor.
      @return words (none without a source)
      """
      if self.completion_source is None:
         return []
      cur = self.textCursor()
      text = self.toPlainText()[:cur.position()]
      try:
         return self.completion_source(text)
      except Exception:   # a source's defect never stops typing
         return []

   def show_completions(self, forced: bool = False) -> bool:
      """!Opens the completion list at the cursor when there is something to offer.
      @param forced  open it even for an empty prefix (Ctrl+Space)
      @return True when it opened
      """
      prefix = self._typed_prefix()
      if not forced and len(prefix) < AUTO_PREFIX:
         self.completer.popup().hide()
         return False
      words = self.completions()
      if not words:
         self.completer.popup().hide()
         return False
      self.completer.setModel(QtCore.QStringListModel(words, self.completer))
      self.completer.setCompletionPrefix(prefix)
      rect = self.cursorRect()
      rect.setWidth(self.completer.popup().sizeHintForColumn(0) +
                    self.completer.popup().verticalScrollBar().sizeHint().width())
      self.completer.complete(rect)
      return True

   def insert_completion(self, word: str) -> None:
      """!Replaces the typed part of a word with a completion.
      @param word  the chosen word
      @return None
      """
      cur = self.textCursor()
      prefix = self._typed_prefix()
      cur.movePosition(QtGui.QTextCursor.MoveOperation.Left, QtGui.QTextCursor.MoveMode.KeepAnchor, len(prefix))
      cur.insertText(word)
      self.setTextCursor(cur)

   def keyPressEvent(self, e: QtGui.QKeyEvent) -> None:
      """!Typing, with the completion list: Enter / Tab take its word, Escape closes it, Ctrl+Space opens it.
      @param e  QKeyEvent
      @return None
      """
      keys = QtCore.Qt.Key
      popup = self.completer.popup()
      if popup.isVisible() and e.key() in (keys.Key_Return, keys.Key_Enter, keys.Key_Tab, keys.Key_Escape,
                                           keys.Key_Backtab):
         e.ignore()   # the completer's popup takes them
         return
      if e.key() == keys.Key_Space and e.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
         self.show_completions(forced=True)
         return
      super().keyPressEvent(e)
      if self.completion_source is not None and e.text() and (e.text().isalnum() or e.text() == "_"):
         self.show_completions()
      elif popup.isVisible():
         popup.hide()

   def go_to(self, line: int, col: int = 1) -> None:
      """!Moves the cursor to a position and shows it.
      @param line  1-based line
      @param col   1-based column
      @return None
      """
      block = self.document().findBlockByNumber(max(0, line - 1))
      cur = QtGui.QTextCursor(block)
      cur.movePosition(QtGui.QTextCursor.MoveOperation.Right, n=max(0, col - 1))
      self.setTextCursor(cur)
      self.centerCursor()
      self.setFocus()

   def event(self, e: QtCore.QEvent) -> bool:
      """!Shows a diagnostic's message as the tooltip over its line ([S5] else the word's help, word_help).
      @param e  QEvent
      @return handled
      """
      if e.type() == QtCore.QEvent.Type.ToolTip:
         # The event's position is the editor's; the text viewport starts after the gutter.
         cur = self.cursorForPosition(e.pos() - QtCore.QPoint(self.gutter_width(), 0))
         line = cur.blockNumber() + 1
         msgs = [m for ln, _c, _s, m in self.marks if ln == line]
         if not msgs and self.word_help is not None:
            # [S5] a route step's help: what it does (engine N2: in_place walks, speed moves the walker too)
            cur.select(QtGui.QTextCursor.SelectionType.WordUnderCursor)
            before = self.toPlainText()[:cur.selectionStart()]
            found = self.word_help(before, cur.selectedText())
            msgs = [found] if found else []
         if msgs:
            QtWidgets.QToolTip.showText(e.globalPos(), "\n".join(msgs), self)
         else:
            QtWidgets.QToolTip.hideText()
         return True
      return super().event(e)
