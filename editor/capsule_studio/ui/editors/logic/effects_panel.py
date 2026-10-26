"""!Logic > Effects (D-23 §3.3): the effect logic of every owner, stored in
the battle's .ceffect sources, edited through core.logic (which reads and
writes them with the engine's effect compiler).

Layout, left to right:
- the owner tree: Moves, Passives, Items, Statuses, Weathers, Volatiles,
  Side conditions, Field conditions (the owner kinds the engine's battle
  compiler takes today; global owners are not compiled yet), or grouped by source
  file; filters "has logic" (off: every manifest entry, without logic
  greyed) and "uses hook X"; add, remove and give logic to another entry;
- the handlers of the owner, the hook / point picker with what the catalog
  says about the choice, and the budget meter of the selected handler
  (stack, worst-case events, possible draws; core.logic.budgets());
- the editor stack, Block view | Text view, over one AST:
  - Text view: the owner's whole file in the studio's CodeEditor with .ceffect
    colours. A text edit is written (one undo step) after 300 ms without
    typing; when it parses, the blocks follow it; when not, an error banner
    names file:line:col, the editor marks it and the blocks keep the last
    AST that parsed (read only until the text parses again). The list below
    the editor holds every diagnostic; activating one goes to it.
  - Block view (blocks.BlockView): each block operation changes a copy of the
    AST; core.logic.set_owner_ast() formats the owner's block and replaces
    only that span of its file (one undo step).
Undo / Redo act on the selected owner's source (a step that also changed
the battle manifest, such as the first logic of a kind, undoes both).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtGui, QtWidgets

from ....core import logic
from ....core.document import DocumentError
from ...widgets import button
from ..battle_common import BattlePanel
from ..script import CodeEditor
from .blocks import AstChange, BlockView
from .catalog import EffectHighlighter, HookPicker, completion_words

if TYPE_CHECKING:
   from ....core.battle import SourceDocument
   from ....core.document import Document
   from ...panel import PanelHost

## Milliseconds without typing before the text view writes and parses its text.
IDLE_MS = 300
## Owner tree group titles by owner kind.
KIND_TITLES = {"move": "Moves", "passive": "Passives", "item": "Items", "status": "Statuses",
               "weather": "Weathers", "volatile": "Volatiles", "side_condition": "Side conditions",
               "field_condition": "Field conditions", "global": "Global rules"}
## Group-by choices: (text, key).
GROUPINGS = [("By kind", "kind"), ("By source file", "file")]
## The "uses hook" filter's choice for every owner.
ANY_HOOK = "(any hook)"
## File group of entries without logic (grouped by file).
NO_LOGIC_GROUP = "(no logic)"
## Item data role of an owner row: (kind, name, has logic).
OWNER_ROLE = QtCore.Qt.ItemDataRole.UserRole
## Colour of an entry without logic.
NO_LOGIC_COLOUR = "#7f8a96"
## Style of the error banner.
BANNER_STYLE = "background: #d04040; color: white; padding: 4px; border-radius: 3px;"
## Page of the editor stack: blocks.
BLOCK_PAGE = 0
## Page of the editor stack: text.
TEXT_PAGE = 1
## Layout stretches of the three columns (owners, handlers, editor).
COLUMN_STRETCH = (2, 2, 5)
## Text view splitter starting heights (editor, diagnostics), pixels.
TEXT_SPLIT = (520, 120)
## Splitter starting widths of the three columns, pixels.
COLUMN_WIDTHS = (230, 260, 640)


class EffectsPanel(BattlePanel):
   """!The effect logic editor (see the module docstring).

   Attributes are documented where __init__ sets them; the ones below are repeated here because Doxygen's
   Python parser otherwise reports their later uses as undocumented members.

   @var owner
   Selected owner: (kind, name), or None.
   @var handler_index
   Index of the selected handler in the owner's "handlers", or None.
   @var good_ast
   The selected owner's last AST that parsed.
   @var text_rel
   The source the text view shows.
   @var rows
   Owner rows of the last parse.
   @var diags
   Diagnostics shown (every file).
   @var errors
   The panel's message line (BattlePanel's compile result line).
   @var _filling
   True while the panel fills its own widgets.
   @var _handler_rows
   AST handler index of each row of the handler list.
   """

   ## See EditorPanel.panel_id.
   panel_id = "effects"
   ## See EditorPanel.title.
   title = "Effects"

   def __init__(self, host: PanelHost, parent: QtWidgets.QWidget | None = None) -> None:
      """!Builds the panel.
      @param host    PanelHost with a BattleProject as project
      @param parent  parent widget
      """
      super().__init__(host, parent)
      ## Selected owner: (kind, name), or None.
      self.owner: tuple[str, str] | None = None
      ## Index of the selected handler in the owner's "handlers", or None.
      self.handler_index: int | None = None
      ## The selected owner's last AST that parsed (the blocks show it), or None.
      self.good_ast = None
      ## Whether the blocks may edit (the owner's file parses).
      self.editable = False
      ## The source the text view shows (path as the manifest lists it), or None.
      self.text_rel: str | None = None
      ## Owner rows of the last parse: [(kind, name, file, line, handler count)].
      self.rows: list[logic.OwnerRow] = []
      ## Diagnostics shown (every file).
      self.diags: list[logic.Diagnostic] = []
      ## AST handler index of each row of the handler list.
      self._handler_rows: list[int] = []

      # -- owners --
      ## Group by kind or by file.
      self.grouping = QtWidgets.QComboBox()
      self.grouping.addItems([text for text, _key in GROUPINGS])
      self.grouping.currentIndexChanged.connect(lambda _i: self.refresh())
      ## Filter: only owners with logic.
      self.has_logic = QtWidgets.QCheckBox("Has logic")
      self.has_logic.setChecked(True)
      self.has_logic.setToolTip("Off: every entry of the battle data; the ones without logic are grey")
      self.has_logic.toggled.connect(lambda _on: self.refresh())
      ## Filter: only owners with a handler on a hook.
      self.uses_hook = QtWidgets.QComboBox()
      self.uses_hook.setToolTip("Only owners with a handler on this hook, phase or point")
      self.uses_hook.activated.connect(lambda _i: self.refresh())
      ## The owners.
      self.owner_tree = QtWidgets.QTreeWidget()
      self.owner_tree.setHeaderLabels(["Owner", "Handlers"])
      self.owner_tree.currentItemChanged.connect(lambda cur, _prev: self._owner_picked(cur))
      ## Gives the selected entry an empty logic block.
      self.add_button = button("Add logic", lambda: self.add_logic(), "Give the selected entry an empty logic block")
      ## Removes the selected owner's logic.
      self.remove_button = button("Remove logic", lambda: self.remove_logic(), "Remove the selected owner's logic")
      ## Gives the logic to another entry.
      self.rename_button = button("Give to...", lambda: self.rename_logic(),
                                  "Give this logic to another entry of the same kind")
      owners = QtWidgets.QWidget()
      ol = QtWidgets.QVBoxLayout(owners)
      ol.setContentsMargins(0, 0, 0, 0)
      ol.addWidget(self.grouping)
      ol.addWidget(self.has_logic)
      ol.addWidget(self.uses_hook)
      ol.addWidget(self.owner_tree, 1)
      for b in (self.add_button, self.remove_button, self.rename_button):
         ol.addWidget(b)

      # -- handlers --
      ## The owner's handler members.
      self.handler_list = QtWidgets.QListWidget()
      self.handler_list.currentRowChanged.connect(lambda _r: self._handler_picked())
      ## Hook / phase / point picker.
      self.picker = HookPicker()
      self.picker.picked.connect(lambda: self._picker_changed())
      ## `on switch_in per_foe` (once per foe), `on try_switch per_foe` (C5: when a foe switches or runs).
      self.per_foe = QtWidgets.QCheckBox("per_foe (for each foe)")
      self.per_foe.setToolTip("switch_in: also runs once per foe on the field; try_switch: runs when a foe of the "
                              "holder switches out or runs (a foe's trap), not for the holder's own")
      self.per_foe.toggled.connect(lambda on: self._set_per_foe(on))
      ## Adds a handler on the picker's choice.
      self.add_handler_button = button("Add handler", lambda: self.add_handler(),
                                       "Add a handler on the hook, phase or point picked above")
      ## Moves the selected handler to the picker's choice.
      self.set_hook_button = button("Set hook", lambda: self.set_hook(),
                                    "Move the selected handler to the hook, phase or point picked above")
      ## Removes the selected handler.
      self.remove_handler_button = button("Remove", lambda: self.remove_handler(), "Remove the selected handler")
      ## Moves the selected handler up.
      self.handler_up = button("Up", lambda: self.move_handler(-1), "Run it earlier")
      ## Moves it down.
      self.handler_down = button("Down", lambda: self.move_handler(1), "Run it later")
      ## Budget meter: stack.
      self.stack_bar = QtWidgets.QProgressBar()
      self.stack_bar.setFormat("stack %v / %m")
      ## Budget meter: worst-case events.
      self.events_bar = QtWidgets.QProgressBar()
      self.events_bar.setFormat("events %v / %m")
      ## Budget meter: draws, yields, locals.
      self.budget_text = QtWidgets.QLabel()
      self.budget_text.setWordWrap(True)
      handlers = QtWidgets.QWidget()
      hl = QtWidgets.QVBoxLayout(handlers)
      hl.setContentsMargins(0, 0, 0, 0)
      hl.addWidget(QtWidgets.QLabel("Handlers"))
      hl.addWidget(self.handler_list, 1)
      row = QtWidgets.QHBoxLayout()
      for b in (self.handler_up, self.handler_down, self.remove_handler_button):
         row.addWidget(b)
      hl.addLayout(row)
      picker_box = QtWidgets.QGroupBox("Hook / point")
      pl = QtWidgets.QVBoxLayout(picker_box)
      pl.addWidget(self.picker)
      pl.addWidget(self.per_foe)
      row = QtWidgets.QHBoxLayout()
      row.addWidget(self.add_handler_button)
      row.addWidget(self.set_hook_button)
      pl.addLayout(row)
      hl.addWidget(picker_box)
      budget_box = QtWidgets.QGroupBox("Budget of the handler")
      bl = QtWidgets.QVBoxLayout(budget_box)
      bl.addWidget(self.stack_bar)
      bl.addWidget(self.events_bar)
      bl.addWidget(self.budget_text)
      hl.addWidget(budget_box)

      # -- editor stack --
      ## Parse failure banner.
      self.banner = QtWidgets.QLabel()
      self.banner.setWordWrap(True)
      self.banner.setStyleSheet(BANNER_STYLE)
      self.banner.hide()
      ## Goes to the banner's error.
      self.banner_go = button("Go to", lambda: self.go_to_error(), "Show the error in the text")
      self.banner_go.hide()
      ## Block view | Text view.
      self.view_bar = QtWidgets.QTabBar()
      self.view_bar.addTab("Block view")
      self.view_bar.addTab("Text view")
      self.view_bar.currentChanged.connect(lambda i: self._view_changed(i))
      ## The block view.
      self.blocks = BlockView()
      self.blocks.on_edit = lambda label, change: self.apply_ast(label, change)
      self.blocks.range_of = lambda path, text: self._range_of(path, text)
      self.blocks.handler_selected = lambda index: self._block_handler(index)
      ## The text view's editor.
      self.code = CodeEditor(highlighter=EffectHighlighter)
      self.code.setUndoRedoEnabled(False)   # Undo / Redo go to the file's history (the window's actions)
      self.code.installEventFilter(self)
      self.code.textChanged.connect(lambda: self._typed())
      ## Diagnostics of every source.
      self.diag_list = QtWidgets.QListWidget()
      self.diag_list.itemActivated.connect(lambda item: self.go_to_diagnostic(self.diag_list.row(item)))
      self.diag_list.itemDoubleClicked.connect(lambda item: self.go_to_diagnostic(self.diag_list.row(item)))
      text_page = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
      text_page.addWidget(self.code)
      text_page.addWidget(self.diag_list)
      text_page.setStretchFactor(0, 1)
      text_page.setSizes(list(TEXT_SPLIT))
      ## Block | text pages.
      self.stack = QtWidgets.QStackedWidget()
      self.stack.addWidget(self.blocks)
      self.stack.addWidget(text_page)
      ## Writes the typed text after IDLE_MS.
      self.idle = QtCore.QTimer(self)
      self.idle.setSingleShot(True)
      self.idle.setInterval(IDLE_MS)
      self.idle.timeout.connect(lambda: self.commit_text())
      editor = QtWidgets.QWidget()
      el = QtWidgets.QVBoxLayout(editor)
      el.setContentsMargins(0, 0, 0, 0)
      banner_row = QtWidgets.QHBoxLayout()
      banner_row.addWidget(self.banner, 1)
      banner_row.addWidget(self.banner_go)
      el.addLayout(banner_row)
      el.addWidget(self.view_bar)
      el.addWidget(self.stack, 1)
      el.addWidget(self.errors)

      split = QtWidgets.QSplitter()
      for w, stretch in zip((owners, handlers, editor), COLUMN_STRETCH):
         split.addWidget(w)
         split.setStretchFactor(split.count() - 1, stretch)
      split.setSizes(list(COLUMN_WIDTHS))
      lay = QtWidgets.QVBoxLayout(self)
      lay.addWidget(split)

   # -- documents -----------------------------------------------------------------------------------------------------

   def source_doc(self) -> SourceDocument | None:
      """!The source the selected owner (or the text view) is in.
      @return SourceDocument, or None
      """
      p = self.project()
      rel = self.owner_file() or self.text_rel
      if p is None or rel is None or rel not in p.effects:
         return None
      return p.effects[rel]

   def current_document(self) -> Document | None:
      """!Undo / Redo target: the selected owner's source (the battle manifest when there is none).
      @return Document, or None
      """
      return self.source_doc() or self.battle_doc()

   def owner_ref(self) -> str | None:
      """!The selected owner as "kind:name".
      @return text, or None
      """
      return f"{self.owner[0]}{logic.OWNER_SEPARATOR}{self.owner[1]}" if self.owner else None

   def owner_row(self) -> logic.OwnerRow | None:
      """!The selected owner's row (of the last parse).
      @return OwnerRow, or None (no owner, or one without logic)
      """
      return next((r for r in self.rows if self.owner == (r.kind, r.name)), None)

   def owner_file(self) -> str | None:
      """!The selected owner's source.
      @return path as the manifest lists it, or None
      """
      row = self.owner_row()
      return row.file if row is not None else None

   # -- refresh -------------------------------------------------------------------------------------------------------

   def document_replaced(self) -> None:
      """!Another battle data: starts with nothing selected.
      @return None
      """
      self.idle.stop()
      self.owner = None
      self.handler_index = None
      self.good_ast = None
      self.text_rel = None
      self.rows = []
      self.refresh()

   def stop(self) -> None:
      """!Writes text still being typed (the page is left or the files are saved).
      @return None
      """
      if self.idle.isActive():
         self.commit_text()

   def refresh(self) -> None:
      """!Re-reads the owners, the selected owner's logic, the text and the diagnostics.
      @return None
      """
      self._refresh(with_tree=True)

   def _refresh(self, with_tree: bool) -> None:
      """!See refresh().
      @param with_tree  also rebuild the owner tree (False: keep it, the selection only changed)
      @return None
      """
      p = self.project()
      self._filling = True
      try:
         if p is None:
            self.rows = []
            self.owner_tree.clear()
            self.good_ast = None
            self.blocks.show_ast(None, False)
            self._set_code("")
            return
         try:
            self.rows = logic.owners(p)
            broken = False
         except DocumentError:
            broken = True   # the rows of the last parse stay
         if with_tree:
            self._fill_filters(p)
            self._fill_owner_tree(p)
         self._show_owner(p, broken)
      finally:
         self._filling = False

   def _fill_filters(self, p: Any) -> None:
      """!The "uses hook" choices.
      @param p  BattleProject
      @return None
      """
      keep = self.uses_hook.currentText() or ANY_HOOK
      names = [h["name"] for h in logic.hook_catalog()] + [pt["name"] for pt in logic.point_catalog(p)]
      self.uses_hook.blockSignals(True)
      self.uses_hook.clear()
      self.uses_hook.addItems([ANY_HOOK] + list(dict.fromkeys(names)))
      self.uses_hook.setCurrentIndex(max(0, self.uses_hook.findText(keep)))
      self.uses_hook.blockSignals(False)

   def _fill_owner_tree(self, p: Any) -> None:
      """!The owner tree, grouped and filtered (keeps the selection).
      @param p  BattleProject
      @return None
      """
      by_file = GROUPINGS[max(0, self.grouping.currentIndex())][1] == "file"
      hook = self.uses_hook.currentText()
      try:
         members = logic.member_names(p)
      except DocumentError:
         members = {}
      rows = [(r.kind, r.name, r.file, r.handlers) for r in self.rows]
      if hook and hook != ANY_HOOK:
         rows = [r for r in rows if hook in members.get((r[0], r[1]), [])]
      with_logic = {(r.kind, r.name) for r in self.rows}
      if not self.has_logic.isChecked() and (not hook or hook == ANY_HOOK):
         for kind, list_key in logic.kind_lists().items():
            rows += [(kind, name, None, 0) for name in p.names(list_key) if (kind, name) not in with_logic]
      self.owner_tree.blockSignals(True)
      self.owner_tree.clear()
      groups: dict[str, QtWidgets.QTreeWidgetItem] = {}
      order = list(logic.owner_kinds())
      if by_file:
         order = list(p.effects) + [NO_LOGIC_GROUP]
      for key in order:
         title = KIND_TITLES.get(key, key) if not by_file else key
         groups[key] = QtWidgets.QTreeWidgetItem(self.owner_tree, [title])
         groups[key].setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
      selected = None
      for kind, name, file, count in rows:
         key = (file or NO_LOGIC_GROUP) if by_file else kind
         parent = groups.get(key)
         if parent is None:
            continue
         text = name if not by_file else f"{kind} {name}"
         item = QtWidgets.QTreeWidgetItem(parent, [text, str(count) if file else ""])
         item.setData(0, OWNER_ROLE, (kind, name, file is not None))
         if file is None:
            item.setForeground(0, QtGui.QColor(NO_LOGIC_COLOUR))
            item.setToolTip(0, "no logic yet (Add logic)")
         else:
            item.setToolTip(0, file)
         if self.owner == (kind, name):
            selected = item
      for key, item in groups.items():
         item.setText(1, str(item.childCount()))
         item.setHidden(by_file and key == NO_LOGIC_GROUP and item.childCount() == 0)
      self.owner_tree.expandAll()
      self.owner_tree.resizeColumnToContents(0)
      if selected is not None:
         self.owner_tree.setCurrentItem(selected)
      self.owner_tree.blockSignals(False)

   def _show_owner(self, p: Any, broken: bool) -> None:
      """!The selected owner's handlers, blocks, text, diagnostics and budget.
      @param p       BattleProject
      @param broken  whether a source does not parse
      @return None
      """
      row = self.owner_row()
      has_logic = row is not None
      if self.text_rel not in p.effects:
         self.text_rel = next(iter(p.effects), None)
      if row is not None:
         self.text_rel = row.file
      error = logic.source_error(p, self.text_rel) if self.text_rel else None
      if has_logic and error is None:
         try:
            self.good_ast = logic.owner_ast(p, self.owner_ref())
         except DocumentError:
            self.good_ast = None
      elif not has_logic and not broken:
         self.good_ast = None
      self.editable = has_logic and error is None and self.good_ast is not None
      self.add_button.setEnabled(self.owner is not None and not has_logic and not broken)
      self.remove_button.setEnabled(self.editable)
      self.rename_button.setEnabled(self.editable)

      # Words for the blocks (the palette's names come from the structure).
      self.blocks.set_names(logic.name_lists(p), logic.statement_templates(p), completion_words(p))
      self.blocks.show_ast(self.good_ast, self.editable)
      self._fill_handlers(p)

      # Text: the owner's whole file (left alone while typing is pending: the timer writes it).
      if self.text_rel is not None and not self.idle.isActive():
         self._set_code(p.effects[self.text_rel].text)
      self.code.setReadOnly(self.text_rel is None)

      # Banner: the first source that does not parse.
      broken_rel = self.text_rel if error is not None else None
      if error is None and broken:
         for rel in p.effects:
            error = logic.source_error(p, rel)
            if error is not None:
               broken_rel = rel
               break
      if error is not None:
         self.banner.setText(f"Does not parse: {error.text()}. The blocks show the last version that parsed "
                             "(read only until the text parses again).")
      self.banner.setVisible(error is not None)
      self.banner_go.setVisible(error is not None and broken_rel is not None)
      self.diags = logic.diagnostics(p)
      self._show_diagnostics()
      self._show_budget(p)

   def _set_code(self, text: str) -> None:
      """!Sets the text view's text (without counting it as typing); keeps the cursor where it can.
      @param text  the text
      @return None
      """
      if self.code.toPlainText() == text:
         return
      pos = self.code.textCursor().position()
      self.code.blockSignals(True)
      self.code.setPlainText(text)
      self.code.blockSignals(False)
      cur = self.code.textCursor()
      cur.setPosition(min(pos, len(text)))
      self.code.setTextCursor(cur)

   def _show_diagnostics(self) -> None:
      """!The diagnostic list and the text view's marks.
      @return None
      """
      self.diag_list.clear()
      for d in self.diags:
         item = QtWidgets.QListWidgetItem(d.text())
         item.setForeground(QtGui.QColor("#d04040" if d.severity == "error" else "#b08010"))
         self.diag_list.addItem(item)
      marks = [(d.line, d.col, d.severity, d.message) for d in self.diags if d.file == self.text_rel and d.line]
      self.code.set_marks(marks)
      errors = sum(1 for d in self.diags if d.severity == "error")
      warnings = len(self.diags) - errors
      self.errors.setText(f"{errors} error(s), {warnings} warning(s) in the logic" if self.diags else
                          "The logic checks.")

   def _fill_handlers(self, p: Any) -> None:
      """!The handler list and the picker for the owner kind.
      @param p  BattleProject
      @return None
      """
      self.handler_list.blockSignals(True)
      self.handler_list.clear()
      indices: list[int] = []
      for j, h in enumerate((self.good_ast or {}).get("handlers", [])):
         if h.get("stmt") == "comment":
            continue
         self.handler_list.addItem(logic.handler_text(h))
         indices.append(j)
      self._handler_rows = indices
      if self.handler_index not in indices:
         self.handler_index = indices[0] if indices else None
      if self.handler_index is not None:
         self.handler_list.setCurrentRow(indices.index(self.handler_index))
      self.handler_list.blockSignals(False)
      self.picker.fill(p, self.owner[0] if self.owner else None)
      self._sync_picker()
      for w in (self.handler_list, self.add_handler_button, self.set_hook_button, self.remove_handler_button,
                self.handler_up, self.handler_down, self.per_foe):
         w.setEnabled(self.editable)

   def _selected_handler(self) -> dict[str, Any] | None:
      """!The selected handler node (of the shown AST).
      @return node, or None
      """
      handlers = (self.good_ast or {}).get("handlers", [])
      j = self.handler_index
      return handlers[j] if j is not None and 0 <= j < len(handlers) else None

   def _sync_picker(self) -> None:
      """!Shows the selected handler's hook in the picker and its per_foe.
      @return None
      """
      h = self._selected_handler()
      if h is not None:
         member = next((k for k in logic.MEMBER_KEYS if k in h), None)
         if member is not None:
            self.picker.set_choice(member, h[member])
      self.per_foe.blockSignals(True)
      self.per_foe.setChecked(bool(h and h.get("per_foe")))
      choice = self.picker.choice()
      self.per_foe.setEnabled(self.editable and choice is not None and choice[1] in self.picker.per_foe_hooks)
      self.per_foe.blockSignals(False)

   def _show_budget(self, p: Any) -> None:
      """!The budget meter of the selected handler.
      @param p  BattleProject
      @return None
      """
      found = None
      if self.editable and self.handler_index is not None:
         try:
            rows = logic.budgets(p, self.owner_ref())
         except DocumentError:
            rows = None
         if rows is None:
            self.budget_text.setText("Fix the logic's errors to see its budget.")
         else:
            found = next((b for b in rows if b.index == self.handler_index), None)
      elif not self.editable:
         self.budget_text.setText("")
      for bar, what, value, most in ((self.stack_bar, "stack", found.stack if found else 0,
                                      found.stack_limit if found else 1),
                                     (self.events_bar, "events", found.events if found else 0,
                                      found.events_limit if found else 1)):
         bar.setMaximum(most)
         bar.setValue(min(value, most))
         bar.setEnabled(found is not None)
         bar.setFormat(f"{what} %v / %m" if found is not None else f"{what}: -")
      if found is not None:
         h = self._selected_handler() or {}
         hook = next((h[k] for k in ("on", "phase") if k in h), None)
         engine = next((e["draws"] for e in logic.hook_catalog() if e["name"] == hook), "") if hook else ""
         lines = [("may draw random numbers" if found.draws else "draws nothing itself") +
                  (f"; the engine: {engine}" if engine else ""),
                  ("events per step (it may yield)" if found.yields else "events per run (no yield)") +
                  (", asks" if found.asks else ""),
                  f"locals {found.locals} / {found.locals_limit}"]
         self.budget_text.setText("\n".join(lines))

   # -- selection -----------------------------------------------------------------------------------------------------

   def _owner_picked(self, item: QtWidgets.QTreeWidgetItem | None) -> None:
      """!An owner row was selected.
      @param item  the row
      @return None
      """
      if self._filling or item is None:
         return
      data = item.data(0, OWNER_ROLE)
      if not data:
         return
      self.stop()
      self.owner = (data[0], data[1])
      self.handler_index = None
      self.good_ast = None
      # Not the tree: this runs inside its currentItemChanged signal, and clearing the tree there deletes the
      # item Qt is still handling (a crash); picking an owner does not change the tree.
      self._refresh(with_tree=False)
      self.host.selection_changed()
      row = self.owner_row()
      if row is not None:
         self._show_line(row.line)

   def _show_line(self, line: int) -> None:
      """!Puts the text view's cursor on a line and scrolls to it, leaving the focus where it is.
      @param line  1-based line
      @return None
      """
      cur = QtGui.QTextCursor(self.code.document().findBlockByNumber(max(0, line - 1)))
      self.code.setTextCursor(cur)
      self.code.centerCursor()

   def select_owner(self, ref: str) -> bool:
      """!Selects an owner (the Conditions page's "Logic..." button).
      @param ref  "kind:name"
      @return True when the tree shows it
      """
      kind, name = logic.split_owner(ref)
      if kind is None:
         row = next((r for r in self.rows if r.name == name), None)
         kind = row.kind if row is not None else None
      if kind is None:
         return False
      if not any((r.kind, r.name) == (kind, name) for r in self.rows) and self.has_logic.isChecked():
         self.has_logic.setChecked(False)
      it = QtWidgets.QTreeWidgetItemIterator(self.owner_tree)
      while it.value():
         data = it.value().data(0, OWNER_ROLE)
         if data and (data[0], data[1]) == (kind, name):
            self.owner_tree.setCurrentItem(it.value())
            return True
         it += 1
      return False

   def _handler_picked(self) -> None:
      """!A handler row was selected.
      @return None
      """
      if self._filling:
         return
      r = self.handler_list.currentRow()
      rows = self._handler_rows
      if 0 <= r < len(rows):
         self.handler_index = rows[r]
         self.blocks.select_handler(self.handler_index)
         self._sync_picker()
         p = self.project()
         if p is not None:
            self._show_budget(p)

   def _block_handler(self, index: int) -> None:
      """!A row of the block view inside a handler was selected: the handler list follows.
      @param index  handler index
      @return None
      """
      rows = self._handler_rows
      if self._filling or index == self.handler_index or index not in rows:
         return
      self.handler_index = index
      self.handler_list.blockSignals(True)
      self.handler_list.setCurrentRow(rows.index(index))
      self.handler_list.blockSignals(False)
      self._sync_picker()
      p = self.project()
      if p is not None:
         self._show_budget(p)

   def _picker_changed(self) -> None:
      """!The picker's choice changed: per_foe is only for the hooks that take it.
      @return None
      """
      choice = self.picker.choice()
      self.per_foe.setEnabled(self.editable and choice is not None and choice[1] in self.picker.per_foe_hooks)

   def _view_changed(self, index: int) -> None:
      """!The Block view | Text view tab changed.
      @param index  BLOCK_PAGE or TEXT_PAGE
      @return None
      """
      self.stack.setCurrentIndex(index)
      if index == TEXT_PAGE:
         self.code.centerCursor()

   def set_view(self, view: str) -> None:
      """!Shows the block or the text view.
      @param view  "blocks" or "text"
      @return None
      """
      self.view_bar.setCurrentIndex(TEXT_PAGE if view == "text" else BLOCK_PAGE)

   # -- edits ---------------------------------------------------------------------------------------------------------

   def _report(self, label: str, error: Exception) -> None:
      """!Shows why an edit was refused (the status bar and the panel's message line).
      @param label  the edit
      @param error  the exception
      @return None
      """
      self.errors.setText(f"{label}: {error}")
      self.host.show_status(f"{label}: {error}")

   def apply_ast(self, label: str, change: AstChange) -> bool:
      """!Writes a change of the selected owner's AST (one undo step of its file; only its block changes).
      @param label   undo label
      @param change  changes a copy of the AST; may return the path of the statement to select
      @return True when written
      """
      p = self.project()
      if p is None or self.owner is None or not self.editable:
         return False
      self.stop()
      try:
         ast = logic.owner_ast(p, self.owner_ref())
         result = change(ast)
         logic.set_owner_ast(p, self.owner_ref(), ast, label)
      except (DocumentError, ValueError, KeyError, IndexError, TypeError) as e:
         self._report(label, e)
         return False
      if isinstance(result, tuple):
         self.blocks.pending_select = ("stmt", result)
      self.host.changed()
      return True

   def _range_of(self, path: tuple[Any, ...], text: str) -> tuple[int, int] | None:
      """!The analysed range of an expression the block form shows.
      @param path  the slot's path
      @param text  its text
      @return (lo, hi), or None
      """
      p = self.project()
      if p is None or self.owner is None:
         return None
      try:
         return logic.expression_range(p, self.owner_ref(), list(path), text)
      except DocumentError:
         return None

   def _run(self, label: str, fn: Any) -> bool:
      """!Runs a core.logic edit and refreshes.
      @param label  what it is (messages)
      @param fn     callable
      @return True when it went through
      """
      self.stop()
      try:
         fn()
      except (DocumentError, ValueError, KeyError, OSError) as e:
         self._report(label, e)
         return False
      self.host.changed()
      return True

   def add_logic(self) -> bool:
      """!Gives the selected entry (without logic) an empty logic block.
      @return True when added
      """
      p = self.project()
      if p is None or self.owner is None:
         return False
      kind, name = self.owner
      return self._run("Add logic", lambda: logic.add_owner(p, kind, name))

   def remove_logic(self) -> bool:
      """!Removes the selected owner's logic block (the entry stays).
      @return True when removed
      """
      p = self.project()
      if p is None or not self.editable:
         return False
      return self._run("Remove logic", lambda: logic.remove_owner(p, self.owner_ref()))

   def rename_logic(self, new: str | None = None) -> bool:
      """!Gives the selected owner's logic to another entry of its kind.
      @param new  the entry, or None to ask
      @return True when renamed
      """
      p = self.project()
      if p is None or not self.editable:
         return False
      kind, name = self.owner
      if new is None and kind == logic.global_kind():
         # F1: a global rule names no manifest entry: any new name
         new, ok = QtWidgets.QInputDialog.getText(self, "Rename global rule", "New name:", text=name)
         if not ok or not new.strip():
            return False
      if new is None:
         taken = {r.name for r in self.rows if r.kind == kind}
         names = [n for n in p.names(logic.kind_lists()[kind]) if n not in taken]
         if not names:
            self._report("Give to", DocumentError(f"every {kind} has logic already"))
            return False
         new, ok = QtWidgets.QInputDialog.getItem(self, "Give logic to", f"The {kind} that gets {name}'s logic:",
                                                  names, 0, False)
         if not ok:
            return False
      if self._run("Rename logic", lambda: logic.rename_owner(p, self.owner_ref(), new)):
         self.owner = (kind, new)
         return True
      return False

   def _handler_change(self, label: str, change: AstChange) -> bool:
      """!A change of the selected handler (select it again after).
      @param label   undo label
      @param change  AST change
      @return True when written
      """
      return self.apply_ast(label, change)

   def add_handler(self) -> bool:
      """!Adds an empty handler on the picker's hook, phase or point (per_foe when checked).
      @return True when added
      """
      choice = self.picker.choice()
      if choice is None:
         return False
      key, name = choice
      member: dict[str, Any] = {key: name, "body": []}
      if key == "on" and self.per_foe.isChecked() and name in self.picker.per_foe_hooks:
         member["per_foe"] = True

      def change(ast: dict[str, Any]) -> None:
         """!Appends it.
         @param ast  owner AST
         @return None
         """
         ast.setdefault("handlers", []).append(member)
         self.handler_index = len(ast["handlers"]) - 1

      return self._handler_change("Add handler", change)

   def set_hook(self) -> bool:
      """!Moves the selected handler to the picker's hook, phase or point (its body stays).
      @return True when written
      """
      choice = self.picker.choice()
      j = self.handler_index
      if choice is None or j is None:
         return False
      key, name = choice

      def change(ast: dict[str, Any]) -> None:
         """!Changes its member.
         @param ast  owner AST
         @return None
         """
         h = ast["handlers"][j]
         for k in (*logic.MEMBER_KEYS, "per_foe"):
            h.pop(k, None)
         h[key] = name

      return self._handler_change("Set hook", change)

   def _set_per_foe(self, on: bool) -> None:
      """!Sets or clears the selected handler's per_foe.
      @param on  per_foe
      @return None
      """
      j = self.handler_index
      if self._filling or j is None:
         return

      def change(ast: dict[str, Any]) -> None:
         """!Sets it.
         @param ast  owner AST
         @return None
         """
         if on:
            ast["handlers"][j]["per_foe"] = True
         else:
            ast["handlers"][j].pop("per_foe", None)

      self._handler_change("per_foe", change)

   def remove_handler(self) -> bool:
      """!Removes the selected handler.
      @return True when removed
      """
      j = self.handler_index
      if j is None:
         return False
      self.handler_index = None
      return self._handler_change("Remove handler", lambda ast: ast["handlers"].pop(j) and None)

   def move_handler(self, delta: int) -> bool:
      """!Moves the selected handler up or down.
      @param delta  -1 up, +1 down
      @return True when moved
      """
      j = self.handler_index
      handlers = (self.good_ast or {}).get("handlers", [])
      if j is None or not 0 <= j + delta < len(handlers):
         return False

      def change(ast: dict[str, Any]) -> None:
         """!Swaps it with its neighbour.
         @param ast  owner AST
         @return None
         """
         hs = ast["handlers"]
         hs[j], hs[j + delta] = hs[j + delta], hs[j]
         self.handler_index = j + delta

      return self._handler_change("Move handler", change)

   # -- text ----------------------------------------------------------------------------------------------------------

   def _typed(self) -> None:
      """!The text view's text changed: (re)starts the idle timer.
      @return None
      """
      if not self._filling and self.text_rel is not None:
         self.idle.start()

   def commit_text(self) -> bool:
      """!Writes the text view's text to its source (one undo step) and parses it: the blocks follow when it
      parses; otherwise the banner and the marks show the error.
      @return True when the source changed
      """
      self.idle.stop()
      p = self.project()
      rel = self.text_rel
      if p is None or rel is None or rel not in p.effects:
         return False
      text = self.code.toPlainText()
      if text == p.effects[rel].text:
         return False
      try:
         logic.set_source_text(p, rel, text)
      except DocumentError as e:
         self._report("Edit logic text", e)
         return False
      # The owner may have been renamed in the text: then the first owner of that file is shown.
      try:
         rows = logic.owners(p)
      except DocumentError:
         rows = None
      if rows is not None and self.owner is not None and not any((r.kind, r.name) == self.owner for r in rows):
         first = next((r for r in rows if r.file == rel), None)
         self.owner = (first.kind, first.name) if first is not None else None
         self.handler_index = None
      self.refresh()
      self.host.changed()
      return True

   def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
      """!Undo / Redo keys in the text view go to the window's actions (the file's history), after the typed
      text is written.
      @param watched  the editor
      @param event    QEvent
      @return True when the event is taken
      """
      if watched is self.code and event.type() == QtCore.QEvent.Type.ShortcutOverride:
         keys = QtGui.QKeySequence.StandardKey
         if event.matches(keys.Undo) or event.matches(keys.Redo):
            self.stop()
            event.ignore()
            return True
      return super().eventFilter(watched, event)

   def go_to_error(self) -> None:
      """!Shows the banner's syntax error in the text view.
      @return None
      """
      first = next((i for i, d in enumerate(self.diags) if d.code == logic.SYNTAX), None)
      if first is not None:
         self.go_to_diagnostic(first)

   def go_to_diagnostic(self, index: int) -> None:
      """!Shows a diagnostic in the text view (another file: the owner around it is selected).
      @param index  row of the diagnostic list
      @return None
      """
      if not 0 <= index < len(self.diags):
         return
      d = self.diags[index]
      if d.file and d.file != self.text_rel:
         self.stop()
         around = [r for r in self.rows if r.file == d.file and r.line <= max(d.line, 1)]
         if around:
            self.owner = (around[-1].kind, around[-1].name)
            self.handler_index = None
         self.text_rel = d.file
         self.refresh()
         self.host.selection_changed()
      self.set_view("text")
      if d.line:
         self.code.go_to(d.line, max(d.col, 1))
