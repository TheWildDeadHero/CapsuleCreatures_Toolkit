"""!The Text page of the battle navigator (Structure > Text): the game's
code page for its language, the characters the game's saved texts use that
the page lacks (core.codepage.missing()), and a button that opens the
project's Code page panel, where the page is edited.

The page edits nothing itself: the code page belongs to the project (its
file is named by reference/project.json), so it is edited with its own undo
history on the Project page (in the Studio) or in the project settings
window (on its own). The host's open_code_page() does that.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ....core import codepage
from ....core.document import DocumentError
from ...widgets import button
from ..battle_common import BattlePanel

if TYPE_CHECKING:
   from ....core.document import Document
   from ...panel import PanelHost

## Most missing characters the page lists by name (the Code page panel lists them all, with where they are used).
MISSING_SHOWN = 40


class CodePageLinkPanel(BattlePanel):
   """!The game's code page at a glance, and the way to the Code page panel.

   @var errors
   Compile result line (unused here).
   @var _filling
   True while the panel fills its own widgets (unused here).
   """

   ## See EditorPanel.panel_id.
   panel_id = "text"
   ## See EditorPanel.title.
   title = "Text"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the summary and the button.
      @param host    PanelHost with a BattleProject (and open_code_page())
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Which game, language and code page.
      self.summary = QtWidgets.QLabel()
      self.summary.setWordWrap(True)
      self.summary.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## The characters the saved texts use that the page lacks.
      self.missing = QtWidgets.QLabel()
      self.missing.setWordWrap(True)
      self.missing.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
      ## Opens the project's Code page panel.
      self.open_button = button("Open the code page", lambda: self.open_code_page())
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(QtWidgets.QLabel("Every text of the game is encoded with its code page: one 8-bit code per "
                                     "character of its language. The page belongs to the project; it is edited "
                                     "in the project's Code page panel."))
      lay.addWidget(self.summary)
      lay.addWidget(self.missing)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.open_button)
      row.addWidget(button("Check again", lambda: self.check()))
      row.addStretch(1)
      lay.addLayout(row)
      lay.addStretch(1)

   def current_document(self) -> Document | None:
      """!Undo / Redo target: none (the code page is the project's).
      @return None
      """
      return None

   def project_manifest(self) -> Document | None:
      """!The project the battle data belongs to.
      @return project Document, or None outside a game (or before battle data is open)
      """
      doc = self.battle_doc()
      if doc is None or doc.path is None or codepage.find_project(doc.path) is None:
         return None
      try:
         return codepage.open_project(doc.path)
      except DocumentError:
         return None

   def refresh(self) -> None:
      """!Checks again only while the page is shown (it reads every saved text of the game).
      @return None
      """
      if self.isVisible():
         self.check()

   def showEvent(self, event: QtCore.QEvent) -> None:
      """!Checks when the page comes to the front.
      @param event  QShowEvent
      @return None
      """
      super().showEvent(event)
      self.check()

   def check(self) -> None:
      """!Reads the project's code page and the characters its saved texts lack.
      @return None
      """
      doc = self.battle_doc()
      project = self.project_manifest()
      self.open_button.setEnabled(project is not None)
      if project is None:
         self.summary.setText("No battle data open." if doc is None else
                              "This battle data is not inside a game (no reference/project.json in its folder or "
                              "above it): its texts use the engine's default code page.")
         self.missing.setText("")
         return
      try:
         lang = codepage.language(project)
         path = codepage.page_path(project)
         lacking = codepage.missing(project)
      except DocumentError as e:
         self.summary.setText(f"The project's code page cannot be read: {e}")
         self.missing.setText("")
         return
      where = path.name if path is not None else "the engine's default page"
      self.summary.setText(f"Game: {project.data.get('name') or project.path.parent.parent.name}. "
                           f"Language: {lang or 'none named (ASCII)'}. Code page: {where}.")
      if not lacking:
         self.missing.setText("Every character the game's saved texts use has a code.")
         self.missing.setStyleSheet("color: #2a7a2a;")
         return
      chars = list(lacking)
      shown = " ".join(chars[:MISSING_SHOWN]) + (" ..." if len(chars) > MISSING_SHOWN else "")
      self.missing.setText(f"{len(chars)} character(s) the game's saved texts use have no code: {shown}")
      self.missing.setStyleSheet("color: #c03030;")

   def open_code_page(self) -> None:
      """!Opens the project's Code page panel (through the host).
      @return None
      """
      opener = getattr(self.host, "open_code_page", None)
      if callable(opener):
         opener()
