"""!What the text panels share [S2] (engine I4): the text session of the host's asset manifest and the markup
widgets.

TextSession (one per host, session_of()) knows the manifest's game text settings (core.text_tables.TextContext:
code page, field placeholders), the text tables and fonts it reaches (core.asset_tables), and keeps the table and
font Documents the panels open, so the text table, font and text box panels edit the same Documents (a font edited
in the font panel is fitted at once in the table panel) and the host saves them with the manifest (each panel's
extra_documents()). A new manifest (another path) starts a new session.

MarkupHighlighter colours a text's markup: controls, placeholders, terms and named glyphs it knows, and
underlines braces naming nothing; control_menu() builds the Insert menu of the controls (with their arguments),
the placeholders, the terms and the named glyphs.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtGui, QtWidgets

from ...core import asset_tables, engine, fonts, text_tables
from ...core.document import Document, DocumentError

if TYPE_CHECKING:
   from ..panel import PanelHost

## Attribute of a host holding its TextSession.
SESSION_ATTRIBUTE = "_text_session"
## Colour of a known markup name.
MARKUP_COLOR = "#3d7fd6"
## Colour of a placeholder or term.
PLACEHOLDER_COLOR = "#9a5fd0"
## Underline colour of a markup name nothing knows.
UNKNOWN_COLOR = "#d02020"
## A markup group in a text: `{name}` or `{name:args}`.
MARKUP = re.compile(r"\{([^{}]*)\}")


class TextSession:
   """!The text tables and fonts of one asset manifest, shared by a host's text panels."""

   def __init__(self, manifest: Document) -> None:
      """!Starts a session for a manifest.
      @param manifest  the host's asset manifest Document
      """
      ## The manifest Document.
      self.manifest = manifest
      ## Its path when the session started (a new path starts a new session).
      self.path = manifest.path
      ## Table Documents opened, by path.
      self.tables = {}
      ## Font Documents opened, by path.
      self.fonts = {}
      ## Why the game's text settings could not be read, or None.
      self.problem = None
      ## The game's text settings.
      self.context = self._context()
      if manifest.codepage is None:
         manifest.codepage = self.context.page   # the scene editor checks font assets with the game's page

   def _context(self) -> text_tables.TextContext:
      """!The game's text settings (the engine's default page when they cannot be read).
      @return TextContext
      """
      try:
         return text_tables.TextContext.for_manifest(self.path)
      except (DocumentError, engine.EngineNotFound) as e:
         self.problem = str(e)
         return text_tables.TextContext(engine.tool("text_encoder").DEFAULT)

   def table_refs(self) -> list[asset_tables.TableRef]:
      """!The tables the manifest reaches and their other languages' tables (asset_tables.table_set()).
      @return TableRef list
      """
      return asset_tables.table_set(self.manifest)

   def font_refs(self) -> list[tuple[str, Path]]:
      """!The fonts the manifest reaches.
      @return (label, path) pairs
      """
      return asset_tables.fonts(self.manifest)

   def table(self, path: Path) -> Document:
      """!A table's Document (opened on first use).
      @param path  the table
      @return Document
      """
      path = Path(path).resolve()
      if path not in self.tables:
         self.tables[path] = text_tables.open_table(path)
      return self.tables[path]

   def font(self, path: Path) -> Document:
      """!A font's Document (opened on first use; the context fits texts with its data from then on).
      @param path  the font
      @return Document
      """
      path = Path(path).resolve()
      if path not in self.fonts:
         doc = fonts.open_font(path)
         self.fonts[path] = doc
         self.context.open_fonts[path] = doc
      return self.fonts[path]

   def documents(self) -> list[Document]:
      """!Every table and font Document opened.
      @return Documents
      """
      return list(self.tables.values()) + list(self.fonts.values())


def session_of(host: PanelHost) -> TextSession | None:
   """!The host's text session for its current manifest (a new one when the manifest is another file).
   @param host  the panel host
   @return TextSession, or None while the manifest is unsaved (its paths have no folder)
   """
   doc = getattr(host, "document", None)
   if doc is None or doc.path is None:
      return None
   s = getattr(host, SESSION_ATTRIBUTE, None)
   if s is None or s.manifest is not doc or s.path != doc.path:
      s = TextSession(doc)
      setattr(host, SESSION_ATTRIBUTE, s)
   return s


class MarkupHighlighter(QtGui.QSyntaxHighlighter):
   """!Colours a text's markup: known names in colour, unknown ones underlined."""

   def __init__(self, document: QtGui.QTextDocument) -> None:
      """!Attaches to a text document.
      @param document  QTextDocument
      """
      super().__init__(document)
      ## Control names (and named glyphs).
      self.controls = set()
      ## Placeholder names and terms.
      self.placeholders = set()
      ## Format of a control.
      self.control_format = QtGui.QTextCharFormat()
      self.control_format.setForeground(QtGui.QColor(MARKUP_COLOR))
      self.control_format.setFontWeight(QtGui.QFont.Weight.Bold)
      ## Format of a placeholder.
      self.placeholder_format = QtGui.QTextCharFormat()
      self.placeholder_format.setForeground(QtGui.QColor(PLACEHOLDER_COLOR))
      ## Format of an unknown name.
      self.unknown_format = QtGui.QTextCharFormat()
      self.unknown_format.setUnderlineStyle(QtGui.QTextCharFormat.UnderlineStyle.WaveUnderline)
      self.unknown_format.setUnderlineColor(QtGui.QColor(UNKNOWN_COLOR))
      self.unknown_format.setToolTip("the markup names no control, placeholder, term or glyph")

   def set_names(self, context: text_tables.TextContext) -> None:
      """!The names the game's markup knows.
      @param context  the game's text settings
      @return None
      """
      names = text_tables.markup_names(context)
      field = context.field
      places = set(field.codes) | {"@" + t for t in (field.terms or {})} if field is not None else set()
      controls = {n for n in names if n not in places}
      if controls != self.controls or places != self.placeholders:
         self.controls, self.placeholders = controls, places
         self.rehighlight()

   def highlightBlock(self, text: str) -> None:
      """!Colours one line's markup.
      @param text  the line
      @return None
      """
      for m in MARKUP.finditer(text):
         inner = m.group(1)
         base = inner.split(":")[0]   # a control's name before its arguments
         if inner in self.placeholders or base in self.placeholders:
            fmt = self.placeholder_format
         elif base in self.controls or inner in self.controls:
            fmt = self.control_format
         else:
            fmt = self.unknown_format
         self.setFormat(m.start(), m.end() - m.start(), fmt)


def control_menu(parent: QtWidgets.QWidget, context: text_tables.TextContext,
                 insert: Callable[[str], None]) -> QtWidgets.QMenu:
   """!The Insert menu of a text editor: controls (with their argument widths and what they do), placeholders,
   terms, named glyphs.
   @param parent   the menu's parent
   @param context  the game's text settings
   @param insert   called with the markup to insert
   @return QMenu
   """
   menu = QtWidgets.QMenu(parent)
   sub = menu.addMenu("Controls")
   for c in text_tables.controls():
      widths = ", ".join(f"{w} B" for w in c.widths)
      label = f"{c.markup()}    {c.description}" + (f"  ({widths})" if widths else "")
      a = sub.addAction(label)
      a.triggered.connect(lambda _checked=False, m=c.markup(): insert(m))
   field = context.field
   if field is not None and field.codes:
      sub = menu.addMenu("Placeholders")
      for name in field.codes:
         a = sub.addAction("{" + name + "}")
         a.triggered.connect(lambda _checked=False, n=name: insert("{" + n + "}"))
   if field is not None and field.terms:
      sub = menu.addMenu("Terms")
      for concept in field.terms:
         a = sub.addAction("{@" + concept + "}")
         a.triggered.connect(lambda _checked=False, n=concept: insert("{@" + n + "}"))
   named = getattr(context.page, "names", {})
   if named:
      sub = menu.addMenu("Named glyphs")
      prefix = engine.tool("text_encoder").GLYPH_PREFIX
      for name in named:
         a = sub.addAction("{" + prefix + name + "}")
         a.triggered.connect(lambda _checked=False, n=name: insert("{" + prefix + n + "}"))
   return menu
