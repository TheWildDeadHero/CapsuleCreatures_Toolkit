"""!The Terms panel: the game's words for the battle concepts (D-20 E).

Every concept the engine knows (party, trait, passive, reward, ...) shows its
word and plural. A concept the game leaves to the engine shows the engine's
neutral default, greyed; typing a word makes it the game's. A plural left out
is the word plus "s" (the battle compiler's rule; some concepts never take
one), shown greyed too. Reset puts the selected concepts back to the
defaults. Editors' labels, page titles and `{@concept}` texts use these words.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import battle, engine
from ...widgets import button
from ..battle_common import STRUCTURE, BattlePanel

if TYPE_CHECKING:
   from ...panel import PanelHost

## Table columns: concept, word, plural, where the word comes from.
TERM_COLUMNS = 4
## Column of the concept (read only).
CONCEPT_COLUMN = 0
## Column of the word.
ONE_COLUMN = 1
## Column of the plural.
MANY_COLUMN = 2
## Column saying where the word comes from (read only).
SOURCE_COLUMN = 3
## Text colour of words the game does not give (engine defaults, derived plurals).
DEFAULT_COLOR = "#909090"


class TermsPanel(BattlePanel):
   """!A table of concepts with their singular and plural words.

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## See EditorPanel.panel_id.
   ## The file the page edits: the structure manifest.
   manifest = STRUCTURE
   panel_id = "terms"
   ## See EditorPanel.title.
   title = "Terms"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the table and its buttons.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Concept rows: concept, word, plural, source.
      self.table = QtWidgets.QTableWidget(0, TERM_COLUMNS)
      self.table.setHorizontalHeaderLabels(["Concept", "Word", "Plural", ""])
      self.table.horizontalHeader().setSectionResizeMode(SOURCE_COLUMN, QtWidgets.QHeaderView.ResizeMode.Stretch)
      self.table.verticalHeader().setVisible(False)
      self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
      self.table.itemChanged.connect(lambda item: self._cell_changed(item))
      lay = QtWidgets.QVBoxLayout(self)
      note = QtWidgets.QLabel("The game's words for what the engine calls party, trait, passive, ... Editor labels "
                              "use them, and battle texts write {@concept} or {@concept:many} for them. Greyed "
                              "words are the engine's defaults; a plural left out is derived by the plural rule.")
      note.setWordWrap(True)
      lay.addWidget(note)
      ## The plural rule of a word given without a plural (battle_compiler.PLURAL_RULES).
      self.plural = QtWidgets.QComboBox()
      self.plural.activated.connect(lambda _i: self.set_plural_rule(self.plural.currentText()))
      rule_row = QtWidgets.QHBoxLayout()
      rule_row.addWidget(QtWidgets.QLabel("Plurals left out:"))
      rule_row.addWidget(self.plural)
      rule_row.addStretch(1)
      lay.addLayout(rule_row)
      lay.addWidget(self.table, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Reset to default", lambda: self.reset_selected(),
                           "The selected concepts use the engine's words again"))
      row.addStretch(1)
      lay.addLayout(row)
      lay.addWidget(self.errors)

   def _given(self) -> dict[str, object]:
      """!The manifest's own terms section.
      @return {concept: word or {"one", "many"}} ({} when absent)
      """
      doc = self.structure_doc()
      t = doc.data.get("terms") if doc is not None else None
      return t if isinstance(t, dict) else {}

   def concepts(self) -> list[str]:
      """!Concepts in the table's order (the engine's).
      @return list
      """
      try:
         return list(battle.default_terms())
      except engine.EngineNotFound:
         return []

   def refresh(self) -> None:
      """!Re-reads the words.
      @return None
      """
      doc = self.battle_doc()
      self._filling = True
      try:
         concepts = self.concepts() if doc is not None else []
         shown = battle.terms(doc) if doc is not None else {}
         given = self._given()
         grey = QtGui.QBrush(QtGui.QColor(DEFAULT_COLOR))
         self.table.setRowCount(len(concepts))
         for r, concept in enumerate(concepts):
            g = given.get(concept)
            own_many = isinstance(g, dict) and "many" in g
            source = ("game word" + ("" if own_many else ", plural derived")) if g is not None else "engine default"
            cells = [concept, shown[concept]["one"], shown[concept]["many"], source]
            for c, text in enumerate(cells):
               item = QtWidgets.QTableWidgetItem(text)
               if c in (CONCEPT_COLUMN, SOURCE_COLUMN):
                  item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
               # The engine's words, and plurals the compiler derives, are greyed.
               if (c == ONE_COLUMN and g is None) or (c == MANY_COLUMN and not own_many) or c == SOURCE_COLUMN:
                  item.setForeground(grey)
               self.table.setItem(r, c, item)
         self.table.resizeColumnsToContents()
         self.table.setEnabled(doc is not None)
         rules = battle.plural_rules()
         self.plural.clear()
         self.plural.addItems(rules)
         rule = battle.plural_rule(doc) if doc is not None else None
         self.plural.setCurrentText(rule or (rules[0] if rules else ""))
         self.plural.setEnabled(doc is not None and bool(rules))
      finally:
         self._filling = False
      self.show_errors()

   def _cell_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
      """!A word or plural was typed.
      @param item  QTableWidgetItem
      @return None
      """
      if self._filling or item.column() not in (ONE_COLUMN, MANY_COLUMN):
         return
      doc = self.battle_doc()
      if doc is None:
         return
      concept = self.table.item(item.row(), CONCEPT_COLUMN).text()
      one = self.table.item(item.row(), ONE_COLUMN).text().strip()
      many = self.table.item(item.row(), MANY_COLUMN).text().strip()
      if not one:
         self.host.show_status("A word can't be empty (Reset to default gives the engine's word back).")
         self.refresh()
         return
      g = self._given().get(concept)
      own_many = isinstance(g, dict) and "many" in g
      if item.column() == ONE_COLUMN and not own_many:
         many = None   # a derived plural follows the new word
      elif many == self._derived_plural(concept, one):
         many = None   # the plural the compiler derives anyway: not written
      self.edit("Term " + concept, lambda: battle.set_term(doc, concept, one, many))

   def set_plural_rule(self, rule: str) -> bool:
      """!Sets the plural rule (the first rule, the compiler's default, is not written).
      @param rule  one of battle.plural_rules()
      @return True when it went through
      """
      doc = self.battle_doc()
      if doc is None or self._filling:
         return False
      rules = battle.plural_rules()
      value = None if rules and rule == rules[0] else rule
      if value == battle.plural_rule(doc):
         return False
      return self.edit("Plural rule", lambda: battle.set_plural_rule(doc, value))

   def _derived_plural(self, concept: str, one: str) -> str:
      """!The plural the battle compiler derives from a word (core.battle.derived_plural(): the engine's
      plural_of() by the section's plural rule).
      @param concept  concept
      @param one      the word
      @return the plural
      """
      doc = self.battle_doc()
      return battle.derived_plural(doc, concept, one) if doc is not None else one

   def reset_selected(self) -> None:
      """!Puts the selected concepts back to the engine's words.
      @return None
      """
      doc = self.battle_doc()
      rows = sorted({i.row() for i in self.table.selectedItems()})
      concepts = [self.table.item(r, CONCEPT_COLUMN).text() for r in rows]
      concepts = [c for c in concepts if c in self._given()]
      if doc is None or not concepts:
         return

      def fn() -> None:
         """!Removes the concepts from the terms section."""
         for c in concepts:
            battle.set_term(doc, c, None)
      self.edit("Reset terms", fn)
