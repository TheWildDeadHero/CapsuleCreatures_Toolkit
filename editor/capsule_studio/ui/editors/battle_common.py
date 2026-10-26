"""!Shared parts of the battle data panels: a list of named entries of one
kind (with new / copy / rename / delete / move) next to a form the panel
builds, and the compile result below.

Panels change the battle data only through host.run_edit() and the
helpers in core.battle; the host refreshes every panel after an edit. A page
edits one file of the battle data: the content pages battle.json, the
structure pages (BattlePanel.manifest = STRUCTURE) the structure manifest
(structure.json). The two Documents are partners (core.battle), so an edit
may change both as one undo step; Undo acts on the page's file, or on the
other one when the page's last edit changed only that one (the Types page's
chart grid, for one).

Labels name the game's concepts with its own words (core.battle.terms():
"Trainer" where a game calls its parties so): a panel registers a label or
button with term_text() and every refresh rewrites it.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets

from ...core import battle, codepage, engine
from ...core.document import DocumentError
from ..panel import EditorPanel
from ..widgets import ask, button

if TYPE_CHECKING:
   from ...core.battle import BattleProject
   from ...core.document import Document
   from ..panel import PanelHost

## A JSON value of the battle data (parsed JSON: any JSON type).
JsonValue = Any
## A JSON object of the battle data (an entry, a party member, ...).
JsonDict = dict[str, Any]

## Combo text meaning "nothing" (no second type, no ability, ...).
NONE_TEXT = "(none)"
## Layout stretch of an entry panel's list column.
LIST_STRETCH = 2
## Layout stretch of an entry panel's form column.
FORM_STRETCH = 5
## Where a term goes in a term_text() pattern.
TERM_SLOT = "{}"
## A widget that shows text (QLabel, QPushButton, QCheckBox, QGroupBox...): term_text() calls its setText().
TermWidget = QtWidgets.QWidget
## BattlePanel.manifest of a page that edits the battle manifest (the content: battle.json).
CONTENT = "battle"
## BattlePanel.manifest of a page that edits the structure manifest (structure.json).
STRUCTURE = "structure"


def set_combo(combo: QtWidgets.QComboBox, items: Iterable[str], current: object) -> None:
   """!Refills a combo box and selects an item, without emitting signals.
   @param combo    QComboBox
   @param items    list of texts
   @param current  text to select (added when missing, so odd data still shows)
   @return None
   """
   combo.blockSignals(True)
   combo.clear()
   combo.addItems(list(items))
   if current is None:
      combo.setCurrentIndex(-1)   # nothing chosen: show nothing rather than the first item
   else:
      if combo.findText(str(current)) < 0:
         combo.addItem(str(current))
      combo.setCurrentIndex(combo.findText(str(current)))
   combo.blockSignals(False)


def set_spin(spin: QtWidgets.QSpinBox, value: object) -> None:
   """!Sets a spin box without emitting signals.
   @param spin   QSpinBox
   @param value  value (non-integers become the minimum)
   @return None
   """
   spin.blockSignals(True)
   spin.setValue(value if isinstance(value, int) and not isinstance(value, bool) else spin.minimum())
   spin.blockSignals(False)


def set_spin_max(spin: QtWidgets.QSpinBox, most: int) -> None:
   """!Changes a spin box's maximum without emitting signals (a value above it is clamped).
   @param spin  QSpinBox
   @param most  new maximum
   @return None
   """
   if spin.maximum() != most:
      spin.blockSignals(True)
      spin.setMaximum(most)
      spin.blockSignals(False)


def set_check(box: QtWidgets.QCheckBox, on: object) -> None:
   """!Sets a check box without emitting signals.
   @param box  QCheckBox
   @param on   checked
   @return None
   """
   box.blockSignals(True)
   box.setChecked(bool(on))
   box.blockSignals(False)


def spin(lo: int, hi: int, slot: Callable[[int], object]) -> QtWidgets.QSpinBox:
   """!A spin box that reports finished edits.
   @param lo    minimum
   @param hi    maximum
   @param slot  callable(value)
   @return QSpinBox
   """
   s = QtWidgets.QSpinBox()
   s.setRange(lo, hi)
   s.editingFinished.connect(lambda: slot(s.value()))
   return s


def combo(slot: Callable[[str], object]) -> QtWidgets.QComboBox:
   """!A combo box that reports user choices.
   @param slot  callable(text)
   @return QComboBox
   """
   c = QtWidgets.QComboBox()
   c.activated.connect(lambda _i: slot(c.currentText()))
   return c


def default_term(concept: str, many: bool = False) -> str:
   """!The engine's neutral word for a concept (no battle data open).
   @param concept  e.g. "party"
   @param many     the plural
   @return the word, or the concept itself when the engine cannot be found
   """
   try:
      return battle.default_terms()[concept]["many" if many else "one"]
   except (engine.EngineNotFound, KeyError):
      return concept


def game_code_page(path: object) -> Any:
   """!The code page of the game a file belongs to; the engine's default when
   the game has none or its page cannot be read (the build reports that).
   @param path  a file of the game, or None
   @return text_encoder.CodePage
   """
   if path is None:
      return codepage.default_page()
   try:
      return codepage.for_file(path)
   except DocumentError:
      return codepage.default_page()


class BattlePanel(EditorPanel):
   """!Base of the battle panels: project access, edits, the error line, labels in the game's words."""

   ## The kind whose game word (plural) is the tab title, or None to keep ``title``.
   title_kind = None
   ## The file the page edits: CONTENT (battle.json) or STRUCTURE (structure.json).
   manifest = CONTENT

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Creates the panel.
      @param host    PanelHost with a BattleProject as project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## True while the panel fills its own widgets (their signals are ignored).
      self._filling = False
      ## Widgets showing a term: (widget, concept, plural, pattern); see term_text().
      self._term_widgets = []
      ## The manifest Document the page's last edit changed, when it is not the page's own file (or None).
      self._last_changed = None
      ## Compile result.
      self.errors = QtWidgets.QLabel()
      self.errors.setWordWrap(True)
      self.errors.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

   def project(self) -> BattleProject | None:
      """!The host's BattleProject.
      @return BattleProject, or None
      """
      return self.host_project()

   def battle_doc(self) -> Document | None:
      """!The battle manifest Document.
      @return Document, or None
      """
      p = self.project()
      return p.battle if p is not None else None

   def structure_doc(self) -> Document | None:
      """!The structure manifest Document (structure.json).
      @return Document, or None
      """
      p = self.project()
      return p.structure if p is not None else None

   def manifest_doc(self) -> Document | None:
      """!The file this page edits (its manifest: the battle or the structure manifest).
      @return Document, or None
      """
      return self.structure_doc() if self.manifest == STRUCTURE else self.battle_doc()

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the page's file, or the other manifest (or an effect source, S17: a move's or a
      condition's point handlers are its logic's point members) when the page's last edit changed only that one
      and it can still undo it.
      @return Document, or None
      """
      own = self.manifest_doc()
      other = self._last_changed
      p = self.project()
      if other is not None and p is not None and any(other is d for d in self._edited_documents(p)) and \
         other.undo_label() is not None:
         return other
      return own

   @staticmethod
   def _edited_documents(p: Any) -> list[Document]:
      """!The files an edit of a page may change: both manifests and the effect sources.
      @param p  BattleProject
      @return Documents
      """
      sources = p.effects   # local name: Doxygen 1.12 misreads "in self.x"
      return [p.battle, p.structure] + list(sources.values())

   def edit(self, label: str, fn: Callable[[], object]) -> bool:
      """!Runs an edit of the page's file through the host (its partner manifest may change too: one step).
      @param label  undo label
      @param fn     callable
      @return True on success
      """
      doc = self.manifest_doc()
      p = self.project()
      if doc is None or p is None:
         return False
      before = {id(d): d.revision for d in self._edited_documents(p)}
      done = self.host.run_edit(label, fn, doc)
      if done:
         # Undo follows the edit to the other file when only that one changed (a source the edit created counts).
         changed = [d for d in self._edited_documents(p) if before.get(id(d)) != d.revision]
         self._last_changed = changed[0] if len(changed) == 1 and changed[0] is not doc else None
      return done

   def open_logic(self, ref: str) -> bool:
      """!Shows an owner's logic on the Logic > Effects page (the "Logic..." buttons).
      @param ref  "kind:name" (an owner of the effect language)
      @return True when the Effects page shows it
      """
      show = getattr(self.host, "show_panel", None)
      try:
         effects = show("effects") if show is not None else None
      except KeyError:
         effects = None
      if effects is None:
         self.host.show_status(f"{ref}: no Effects page here (open the battle editor's Logic group)")
         return False
      if not effects.select_owner(ref):
         self.host.show_status(f"{ref}: not among the Effects page's owners")
         return False
      return True

   def word(self, concept: str, many: bool = False) -> str:
      """!The game's word for a concept (the engine's default while nothing is open).
      @param concept  e.g. "party"
      @param many     the plural
      @return the word
      """
      doc = self.battle_doc()
      if doc is None:
         return default_term(concept, many)
      return battle.term(doc, concept, many)

   def term_text(self, widget: TermWidget, concept: str, many: bool = False,
                 pattern: str = TERM_SLOT) -> TermWidget:
      """!Makes a widget's text name a concept with the game's word (rewritten at every refresh).
      @param widget   a widget with setText()
      @param concept  e.g. "trait"
      @param many     the plural
      @param pattern  the text, TERM_SLOT where the word goes (e.g. "{} slot")
      @return the widget
      """
      self._term_widgets.append((widget, concept, many, pattern))
      widget.setText(pattern.replace(TERM_SLOT, self.word(concept, many)))
      return widget

   def term_label(self, concept: str, many: bool = False, pattern: str = TERM_SLOT) -> QtWidgets.QLabel:
      """!A label naming a concept with the game's word.
      @param concept  e.g. "trait"
      @param many     the plural
      @param pattern  the text, TERM_SLOT where the word goes
      @return QLabel
      """
      return self.term_text(QtWidgets.QLabel(), concept, many, pattern)

   def update_terms(self) -> None:
      """!Rewrites every term_text() widget with the game's current words.
      @return None
      """
      for widget, concept, many, pattern in self._term_widgets:
         widget.setText(pattern.replace(TERM_SLOT, self.word(concept, many)))

   def tab_title(self) -> str:
      """!The panel's tab title: the game's word for its kind (plural), or its fixed title.
      @return text
      """
      if self.title_kind is None:
         return self.title
      doc = self.battle_doc()
      concept = battle.KIND_CONCEPTS[self.title_kind]
      return battle.kind_label(doc, self.title_kind, True) if doc is not None else default_term(concept, True)

   def kind_word(self, kind: str) -> str:
      """!The game's word for one entry of a kind (dialog titles, undo labels).
      @param kind  one of core.battle.KINDS
      @return e.g. "Trainer"
      """
      return self.word(battle.KIND_CONCEPTS[kind])

   def code_page(self) -> Any:
      """!The game's code page (texts are checked against it).
      @return text_encoder.CodePage
      """
      doc = self.battle_doc()
      return game_code_page(doc.path if doc is not None else None)

   def show_errors(self) -> None:
      """!Shows the compile result for every platform the game builds for.
      @return None
      """
      p = self.project()
      error = p.validate_targets() if p is not None else None
      self.errors.setText(f"Not compiling: {error}" if error else ("Compiles." if p is not None else ""))
      self.errors.setStyleSheet("color: #c03030;" if error else "color: #2a7a2a;")


class EntryPanel(BattlePanel):
   """!A list of one kind's entries plus a form for the selected one.

   Subclasses set ``kind`` and implement build_form(layout) and
   fill_form(entry or None).

   @var errors
   Compile result line.
   @var _filling
   True while the panel fills its own widgets.
   """

   ## Which list of the battle manifest (core.battle.KINDS).
   kind = "types"
   ## True: the form scrolls when it is taller than the page (a long form then keeps its rows apart instead of
   ## squeezing them over each other).
   scroll_form = False

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the list and buttons; the subclass builds its form.
      @param host    PanelHost with a BattleProject as project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Selected entry name, or None.
      self.selected = None
      ## Entry names.
      self.entry_list = QtWidgets.QListWidget()
      self.entry_list.currentRowChanged.connect(lambda *a: self._row_chosen(*a))
      left = QtWidgets.QVBoxLayout()
      left.addWidget(self.term_label(battle.KIND_CONCEPTS[self.kind], False, TERM_SLOT + " list"))
      left.addWidget(self.entry_list, 1)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("New", lambda: self.new_entry()))
      row.addWidget(button("Copy", lambda: self.copy_entry()))
      row.addWidget(button("Rename...", lambda: self.rename_entry()))
      left.addLayout(row)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(button("Delete", lambda: self.delete_entry()))
      tip = ("List order only: the compiler sorts species by key" if self.kind == "species"
             else "Earlier in the list (lower engine index)")
      row.addWidget(button("Up", lambda: self.move_entry(-1), tip))
      row.addWidget(button("Down", lambda: self.move_entry(1),
                           tip.replace("Earlier", "Later").replace("lower", "higher")))
      left.addLayout(row)
      form = QtWidgets.QVBoxLayout()
      self.build_form(form)
      form.addStretch(1)
      form.addWidget(self.errors)
      ## The scroll area around the form (scroll_form), or None.
      self.form_scroll = None
      layout = QtWidgets.QHBoxLayout(self)
      for part, stretch in ((left, LIST_STRETCH), (form, FORM_STRETCH)):
         box = QtWidgets.QWidget()
         box.setLayout(part)
         if part is form and self.scroll_form:
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            scroll.setWidget(box)
            self.form_scroll = box = scroll
         layout.addWidget(box, stretch)

   # -- subclass hooks ---------------------------------------------------------------

   def build_form(self, layout: QtWidgets.QVBoxLayout) -> None:
      """!Adds the form widgets.
      @param layout  QVBoxLayout to add to
      @return None
      """
      pass

   def fill_form(self, entry: JsonDict | None) -> None:
      """!Shows an entry in the form.
      @param entry  dict, or None when nothing is selected
      @return None
      """
      pass

   # -- list ---------------------------------------------------------------------------

   def names(self) -> list[str]:
      """!Entry names of this kind.
      @return list
      """
      p = self.project()
      return p.names(self.kind) if p is not None else []

   def current(self) -> JsonDict | None:
      """!The selected entry.
      @return dict, or None
      """
      p = self.project()
      if p is None or self.selected not in self.names():
         return None
      return p.entry(self.kind, self.selected)

   def refresh(self) -> None:
      """!Re-reads the list, the form and the compile result.
      @return None
      """
      names = self.names()
      if self.selected not in names:
         self.selected = names[0] if names else None
      self.update_terms()
      self._filling = True
      try:
         self.entry_list.clear()
         self.entry_list.addItems(names)
         if self.selected is not None:
            self.entry_list.setCurrentRow(names.index(self.selected))
         self.fill_form(self.current())
      finally:
         self._filling = False
      self.show_errors()

   def _row_chosen(self, row: int) -> None:
      """!Another entry was picked.
      @param row  list row
      @return None
      """
      if self._filling:
         return
      names = self.names()
      self.selected = names[row] if 0 <= row < len(names) else None
      self._filling = True
      try:
         self.fill_form(self.current())
      finally:
         self._filling = False

   def set_field(self, key: str, value: JsonValue, label: str | None = None, keep_null: bool = False) -> None:
      """!Sets a field of the selected entry (None removes it, unless
      @p keep_null).
      @param key        field
      @param value      JSON value or None
      @param label      undo label (default "Set <key>")
      @param keep_null  store None as JSON null
      @return None
      """
      if self._filling or self.selected is None:
         return
      doc, kind, name = self.battle_doc(), self.kind, self.selected
      entry = self.current()
      if entry is not None:
         removing = value is None and not keep_null
         # Nothing to do: removing a field that is not there, or setting the value it has.
         if (removing and key not in entry) or (not removing and key in entry and entry[key] == value):
            return
      self.edit(label or f"Set {key}", lambda: battle.set_field(doc, kind, name, key, value, keep_null))

   def new_entry(self) -> None:
      """!Adds an entry from the kind's template.
      @return None
      """
      word = self.kind_word(self.kind)
      name, ok = QtWidgets.QInputDialog.getText(self, "New " + word, "Name:")
      if ok and name.strip():
         doc, kind = self.battle_doc(), self.kind
         result = []
         if self.edit("New " + word, lambda: result.append(battle.add_entry(doc, kind, name))):
            self.selected = result[0]

   def copy_entry(self) -> None:
      """!Adds a copy of the selected entry.
      @return None
      """
      if self.selected is None:
         return
      doc, kind, src = self.battle_doc(), self.kind, self.selected
      result = []

      def copied() -> None:
         """!Adds the copy under a free name ("NAME 2").
         @return None
         """
         result.append(battle.add_entry(doc, kind, src, src, unique=True))

      if self.edit("Copy " + self.kind_word(kind), copied):
         self.selected = result[0]

   def rename_entry(self) -> None:
      """!Renames the selected entry (references follow).
      @return None
      """
      if self.selected is None:
         return
      new, ok = QtWidgets.QInputDialog.getText(self, "Rename", "New name:", text=self.selected)
      if ok and new.strip() and new.strip() != self.selected:
         b = QtWidgets.QMessageBox.StandardButton
         if self.kind == "species" and ask(
               self, "Rename", "Renaming a species changes its key (species:NAME), so saved creatures "
               "of the old name no longer match it. Rename anyway?", b.Yes | b.No, b.No, b.No) != b.Yes:
            return
         doc, kind, old = self.battle_doc(), self.kind, self.selected
         if self.edit("Rename", lambda: battle.rename_entry(doc, kind, old, new)):
            self.selected = new.strip()

   def delete_entry(self) -> None:
      """!Deletes the selected entry (refused while referenced).
      @return None
      """
      if self.selected is None:
         return
      doc, kind, name = self.battle_doc(), self.kind, self.selected
      if self.edit("Delete " + self.kind_word(kind), lambda: battle.remove_entry(doc, kind, name)):
         self.selected = None

   def move_entry(self, delta: int) -> None:
      """!Moves the selected entry up or down.
      @param delta  -1 or +1
      @return None
      """
      if self.selected is None:
         return
      doc, kind, name = self.battle_doc(), self.kind, self.selected
      self.edit("Move", lambda: battle.move_entry(doc, kind, name, delta))


## Largest width of a planned page's text, pixels (it reads as a paragraph, not one long line).
PLANNED_TEXT_WIDTH = 640


class PlannedPanel(BattlePanel):
   """!A page of the battle navigator whose editor is not built yet: it says
   what the page will edit, which work package builds it and where the data
   is edited until then. It edits nothing (Undo / Redo stay off on it).

   Subclasses set ``panel_id``, ``title``, ``planned``, ``package`` and
   ``until_then``.

   @var errors
   Compile result line (unused here).
   @var _filling
   True while the panel fills its own widgets (unused here).
   """

   ## What the page will edit (one paragraph).
   planned = ""
   ## The work package that builds it (D-23 §5), with its dependencies.
   package = ""
   ## Where the data is edited until then, or "" when nowhere.
   until_then = ""

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the page's text.
      @param host    PanelHost with a BattleProject
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## The page's heading (its title in the game's words).
      self.heading = QtWidgets.QLabel()
      font = self.heading.font()
      font.setBold(True)
      self.heading.setFont(font)
      ## What the page will edit, who builds it, and where to edit meanwhile.
      self.text = QtWidgets.QLabel()
      self.text.setWordWrap(True)
      self.text.setMaximumWidth(PLANNED_TEXT_WIDTH)
      self.text.setTextFormat(QtCore.Qt.TextFormat.PlainText)
      until = self.until_then   # local name: Doxygen 1.12 misreads "if self.x:" here
      parts = [self.planned, f"Not built yet: {self.package}."]
      if until:
         parts.append(f"Until then: {until}")
      self.text.setText("\n\n".join(parts))
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(self.heading)
      lay.addWidget(self.text)
      lay.addStretch(1)
      self.refresh()

   def current_document(self) -> Document | None:
      """!Undo / Redo target: none (the page edits nothing).
      @return None
      """
      return None

   def refresh(self) -> None:
      """!The heading follows the game's words.
      @return None
      """
      self.heading.setText(self.tab_title())
