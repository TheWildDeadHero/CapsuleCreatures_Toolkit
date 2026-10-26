"""!The script editor window (B-1, B-2, B-4): a game's .cscript sources, checked
live with the engine's compiler.

Layout: the outline on the left (sources, then scripts, flags, variables,
constants, natives and maps of the last check; double-click jumps to the
declaration), the sources as tabs in the middle with the problems list under
them, and on the right the manifest's settings with the Declare and Rename
tools, and a Placeholders tab (the field placeholders and terms,
editors.placeholders). Every edit is checked again after a short pause; the
status bar shows the bank's size or the error count. Undo / Redo work on the
current source, or on the placeholder history while the Placeholders tab is
in front.

[S2] (engine I4): the outline also groups movements, marts and route steps,
and a map's detail shows each trigger entry (on_resume, on_warp_into with
its condition, ...); the editors complete words (core.script_words: what
fits at the cursor, the declared names included); Script > Insert statement
inserts an I4 statement's template; the settings add the object numbering's
start (object_base), unused warnings (warn_unused) and the glitch switches.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import engine, placeholders, script_words, scripts
from ..core.document import DocumentError
from . import profiler
from .editors.placeholders import PlaceholdersPanel
from .editors.script import CodeEditor
from .widgets import STATUS_MS, Debounce, StartPage, button, file_toolbar, remember_file

## File dialog filter.
SCRIPTS_FILTER = "Scripts manifest (scripts.json *.json);;All files (*)"
## Outline groups: (kind, heading).
OUTLINE_GROUPS = [("script", "Scripts"), ("flag", "Flags"), ("var", "Variables"), ("const", "Constants"),
                  ("native", "Natives"), ("map", "Maps"), ("movement", "Movements"), ("mart", "Marts"),
                  ("step", "Route steps")]

## Largest value a QSpinBox holds (a signed 32-bit int).
SPIN_MAX = 2**31 - 1
## Highest value of a new variable's range (the largest u8).
DEFAULT_RANGE_HIGH = 255
## Call depth the VM gives scripts when the manifest sets none.
DEFAULT_STACK_DEPTH = 20
## Deepest call stack the settings offer.
MAX_STACK_DEPTH = 32
## Pause after typing before the sources are checked again, milliseconds.
RECHECK_MS = 400

## Width of the window when it opens, pixels.
WINDOW_WIDTH = 1300
## Height of the window when it opens, pixels.
WINDOW_HEIGHT = 820
## Width of the outline's Name column, pixels.
OUTLINE_NAME_WIDTH = 170
## Width of the problems list's severity column, pixels.
PROBLEM_SEVERITY_WIDTH = 70
## Width of the problems list's Where column, pixels.
PROBLEM_WHERE_WIDTH = 200
## Stretch of the source tabs against the problems list under them (1).
SOURCES_STRETCH = 4
## Stretch of the middle (sources and problems) against the outline and the settings (1 each).
MIDDLE_STRETCH = 4
## Index of the settings pane in the window's splitter (after the outline and the middle).
SIDE_PANE = 2
## [S2] Rows of the glitch switch list before it scrolls.
GLITCH_ROWS = 6


## [S4] What each "vm" switch's value does (the scripts manifest's vm, engine C10): switch -> (label, tip).
VM_TIPS = {"resume": ("After a wait", "same_frame: the instruction after a wait runs in the frame the wait ends; "
                      "next_frame: on the next frame (the reference games' script engines)"),
           "random": ("random(n)", "scaled: (r * n) >> 16; modulo: r % n, drawn even for n = 0 (the reference "
                      "games)"),
           "vars": ("Full-range u8 / u16", "saturate: variables stop at their range's ends; wrap: a u8 0..255 or "
                    "u16 0..65535 overflows as the integer type does (a narrower range still saturates)")}


class DeclareDialog(QtWidgets.QDialog):
   """!Asks for a new flag or variable."""

   def __init__(self, parent: QtWidgets.QWidget | None, sources: Sequence[str], kind: str = "flag",
                vm: dict | None = None) -> None:
      """!Builds the dialog.
      @param parent   parent widget
      @param sources  source paths to choose from
      @param kind     'flag' or 'var' preselected
      @param vm       [S4] the manifest's "vm" setting (whether full-range variables wrap), or None
      """
      super().__init__(parent)
      ## [S4] The manifest's vm switches.
      self.vm = dict(vm or {})
      self.setWindowTitle("Declare a flag or variable")
      form = QtWidgets.QFormLayout(self)
      ## Flag or variable.
      self.kind = QtWidgets.QComboBox()
      self.kind.addItems(["flag", "var"])
      self.kind.setCurrentText(kind)
      ## Name.
      self.name = QtWidgets.QLineEdit()
      ## Source file to add it to.
      self.source = QtWidgets.QComboBox()
      self.source.addItems(sources)
      ## Lifetime bank.
      self.lifetime = QtWidgets.QComboBox()
      self.lifetime.addItems(scripts.lifetimes())   # [S4] the compiler's (C10: session)
      ## Variable type.
      self.type = QtWidgets.QComboBox()
      self.type.addItems(scripts.TYPES)
      ## Range given.
      self.ranged = QtWidgets.QCheckBox("Range")
      ## Lowest value.
      self.lo = QtWidgets.QSpinBox()
      self.lo.setRange(0, SPIN_MAX)
      ## Highest value.
      self.hi = QtWidgets.QSpinBox()
      self.hi.setRange(0, SPIN_MAX)
      self.hi.setValue(DEFAULT_RANGE_HIGH)
      rng = QtWidgets.QHBoxLayout()
      for w in (self.ranged, self.lo, QtWidgets.QLabel(".."), self.hi):
         rng.addWidget(w)
      form.addRow("Kind", self.kind)
      form.addRow("Name", self.name)
      form.addRow("In file", self.source)
      form.addRow("Lifetime", self.lifetime)
      form.addRow("Type", self.type)
      form.addRow("", rng)
      hint = QtWidgets.QLabel("Permanent values are kept; daily ones clear at the day rollover; area ones when "
                              "the player leaves an outdoor area; map ones on every map change; session ones live "
                              "in RAM only (never saved, cleared at a new game).")
      hint.setWordWrap(True)
      form.addRow(hint)
      ## [S4] Whether the variable wraps or saturates (the vm's vars switch, its type and range).
      self.wrap_note = QtWidgets.QLabel()
      self.wrap_note.setWordWrap(True)
      form.addRow(self.wrap_note)
      for w in (self.type, self.lo, self.hi):
         (w.currentTextChanged if isinstance(w, QtWidgets.QComboBox) else w.valueChanged).connect(
            lambda _v: self._wrap_changed())
      self.ranged.toggled.connect(lambda _on: self._wrap_changed())
      bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                      QtWidgets.QDialogButtonBox.StandardButton.Cancel)
      bb.accepted.connect(lambda: self.accept())
      bb.rejected.connect(lambda: self.reject())
      form.addRow(bb)
      self.kind.currentTextChanged.connect(lambda _t: self._kind_changed())
      self._kind_changed()

   def _wrap_changed(self) -> None:
      """![S4] Says whether the variable wraps (scripts.var_wraps()).
      @return None
      """
      t = self.type.currentText()
      top = scripts.WRAPPING_TYPES.get(t)
      lo, hi = (self.lo.value(), self.hi.value()) if self.ranged.isChecked() else (0, top)
      if self.kind.currentText() != "var":
         self.wrap_note.setText("")
      elif top is not None and scripts.var_wraps(t, lo, hi if hi is not None else -1, self.vm):
         self.wrap_note.setText("It wraps: the manifest's vm vars switch is wrap and it has its type's whole range.")
      else:
         self.wrap_note.setText("It saturates at its range's ends" + (
            " (vm vars wrap: only a whole-range u8 / u16 wraps)." if self.vm.get(scripts.VARS_WRAP[0]) ==
            scripts.VARS_WRAP[1] else "."))

   def _kind_changed(self) -> None:
      """!Enables the variable-only fields.
      @return None
      """
      self._wrap_changed()
      is_var = self.kind.currentText() == "var"
      for w in (self.type, self.ranged, self.lo, self.hi):
         w.setEnabled(is_var)


class ScriptWindow(QtWidgets.QMainWindow):
   """!Main window of the script editor."""

   def __init__(self, path: str | Path | None = None) -> None:
      """!Creates the window.
      @param path  scripts.json to open, or None
      """
      super().__init__()
      ## True while _load_settings() fills the fields (their signals change nothing then).
      self._settings_loading = False
      ## The open ScriptProject, or None.
      self.project = None
      ## Last CheckResult, or None.
      self.result = None
      ## Source path -> CodeEditor.
      self.editors = {}
      ## Re-checks after typing pauses.
      self.recheck = Debounce(lambda: self.check(), RECHECK_MS, self)
      self._build_ui()
      self._build_menus()
      ## Start page, shown until a manifest is open.
      self.start = StartPage(
         "CapsuleCreatures Script Editor",
         "Open a game's scripts manifest (scripts.json) or create one to write scripts, flags and variables.",
         [("Open scripts...", lambda: self.open_project()), ("New scripts...", lambda: self.new_project())],
         "script-editor", lambda p: self.open_project(p),
         skip=("Continue without scripts", lambda: self.show_editor()), recent_title="Recent scripts")
      self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
      self._update_title()
      if path:
         self.open_project(path)

   # -- layout ----------------------------------------------------------------------

   def _build_ui(self) -> None:
      """!Outline, tabs, problems and settings.
      @return None
      """
      ## Declarations tree.
      self.outline = QtWidgets.QTreeWidget()
      self.outline.setHeaderLabels(["Name", "Detail"])
      self.outline.setColumnWidth(0, OUTLINE_NAME_WIDTH)
      self.outline.itemActivated.connect(lambda item, _c: self._jump_to_item(item))
      ## Source tabs.
      self.tabs = QtWidgets.QTabWidget()
      self.tabs.currentChanged.connect(lambda _i: self._update_title())
      ## Problems list.
      self.problems = QtWidgets.QTreeWidget()
      self.problems.setHeaderLabels(["", "Where", "Problem"])
      self.problems.setRootIsDecorated(False)
      self.problems.setColumnWidth(0, PROBLEM_SEVERITY_WIDTH)
      self.problems.setColumnWidth(1, PROBLEM_WHERE_WIDTH)
      self.problems.itemActivated.connect(lambda item, _c: self._jump_to_problem(item))
      middle = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
      middle.addWidget(self.tabs)
      middle.addWidget(self.problems)
      middle.setStretchFactor(0, SOURCES_STRETCH)
      middle.setStretchFactor(1, 1)
      # Settings and tools.
      side = QtWidgets.QWidget()
      form = QtWidgets.QFormLayout(side)
      ## Build variant.
      self.game = QtWidgets.QLineEdit()
      self.game.setPlaceholderText("base")
      self.game.setToolTip("The build variant: when game(...) blocks for it are compiled in")
      ## Known variants.
      self.games = QtWidgets.QLineEdit()
      self.games.setPlaceholderText("any")
      self.games.setToolTip("Comma-separated variants; when game(...) may name only these")
      ## VM call depth.
      self.depth = QtWidgets.QSpinBox()
      self.depth.setRange(1, MAX_STACK_DEPTH)
      self.depth.setToolTip("Call depth the VM gives scripts; deeper call chains are build errors (B-1)")
      ## Asset manifest for text: checks.
      self.assets = QtWidgets.QLineEdit()
      self.assets.setPlaceholderText("not checked")
      self.assets.setToolTip("The game's asset manifest, relative to scripts.json: text: references are checked")
      ## World manifest for map checks.
      self.world = QtWidgets.QLineEdit()
      self.world.setPlaceholderText("not checked")
      self.world.setToolTip("The game's world.json, relative to scripts.json: map_scripts names are checked")
      ## [S2] I4: the first local ID of the game's object numbering.
      self.object_base = QtWidgets.QSpinBox()
      self.object_base.setToolTip("Local IDs count from this (an imported game's numbering, I4 object_base)")
      ## [S2] I4: warnings about unused flags and variables.
      self.warn_unused = QtWidgets.QCheckBox("Warn about unused flags and variables")
      ## [S2] I4: the glitch variants' switches (checked: the game's glitch is kept).
      self.glitches = QtWidgets.QListWidget()
      self.glitches.setToolTip("when glitch(\"id\") blocks: checked compiles the glitch, unchecked the fix")
      self.glitches.setMaximumHeight(self.glitches.sizeHintForRow(0) * GLITCH_ROWS + self.glitches.frameWidth()
                                     if self.glitches.count() else self.fontMetrics().height() * GLITCH_ROWS)
      self.glitches.itemChanged.connect(lambda _item: self._settings_changed())
      ## [S4] C10: the vm switches (switch -> its combo; the engine's own behaviour first).
      self.vm_boxes = {}
      for switch, values in scripts.vm_options().items():
         box = QtWidgets.QComboBox()
         box.addItems(values)
         box.setToolTip(VM_TIPS.get(switch, (switch, ""))[1])
         box.activated.connect(lambda _i: self._settings_changed())
         self.vm_boxes[switch] = box
      for w in (self.game, self.games, self.assets, self.world):
         w.editingFinished.connect(lambda: self._settings_changed())
      self.depth.valueChanged.connect(lambda _v: self._settings_changed())
      self.object_base.valueChanged.connect(lambda _v: self._settings_changed())
      self.warn_unused.toggled.connect(lambda _on: self._settings_changed())
      form.addRow(QtWidgets.QLabel("<b>Build settings</b>"))
      form.addRow("Game", self.game)
      form.addRow("Games", self.games)
      form.addRow("Stack depth", self.depth)
      form.addRow("Assets", self.assets)
      form.addRow("World", self.world)
      form.addRow("Object base", self.object_base)
      form.addRow(self.warn_unused)
      form.addRow("Glitches", self.glitches)
      if self.vm_boxes:
         form.addRow(QtWidgets.QLabel("<b>Script VM</b> (how the original game's script engine ran)"))
      for switch, box in self.vm_boxes.items():
         form.addRow(VM_TIPS.get(switch, (switch, ""))[0], box)
      form.addRow(QtWidgets.QLabel("<b>Tools</b>"))
      form.addRow(button("Declare flag or variable...", lambda: self.declare(), "Add a declaration to a source"))
      form.addRow(button("Rename...", lambda: self.rename(), "Rename the selected declaration everywhere"))
      form.addRow(button("Add source...", lambda: self.add_source(), "Add a .cscript file to the manifest"))
      ## Bank summary of the last check.
      self.summary = QtWidgets.QLabel()
      self.summary.setWordWrap(True)
      form.addRow(self.summary)
      ## The manifest's field placeholders and terms (E9).
      self.placeholders = PlaceholdersPanel(self)
      ## Settings | Placeholders.
      self.side_tabs = QtWidgets.QTabWidget()
      self.side_tabs.addTab(side, "Settings")
      self.side_tabs.addTab(self.placeholders, "Placeholders")
      self.side_tabs.currentChanged.connect(lambda _i: self._update_title())
      split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
      split.addWidget(self.outline)
      split.addWidget(middle)
      split.addWidget(self.side_tabs)
      split.setStretchFactor(0, 1)
      split.setStretchFactor(1, MIDDLE_STRETCH)
      split.setStretchFactor(SIDE_PANE, 1)
      self.setCentralWidget(split)

   def _action(self, menu: QtWidgets.QMenu, text: str, slot: Callable[[], object],
               shortcut: QtGui.QKeySequence.StandardKey | str | None = None) -> QtGui.QAction:
      """!Adds a menu action.
      @param menu      QMenu
      @param text      label
      @param slot      callable
      @param shortcut  QKeySequence.StandardKey or str, or None
      @return QAction
      """
      a = QtGui.QAction(text, self)
      if isinstance(shortcut, str):
         a.setShortcut(QtGui.QKeySequence(shortcut))
      elif shortcut is not None:
         a.setShortcuts(shortcut)
      a.triggered.connect(lambda _checked=False: slot())
      menu.addAction(a)
      return a

   def _build_menus(self) -> None:
      """!File, Edit and Script menus and the toolbar.
      @return None
      """
      keys = QtGui.QKeySequence.StandardKey
      m = self.menuBar().addMenu("&File")
      ## New scripts manifest.
      self.new_action = self._action(m, "&New scripts...", lambda: self.new_project(), keys.New)
      ## Open a manifest.
      self.open_action = self._action(m, "&Open scripts...", lambda: self.open_project(), keys.Open)
      ## Add a source file.
      self.add_action = self._action(m, "&Add source...", lambda: self.add_source())
      ## Save the current source.
      self.save_action = self._action(m, "&Save", lambda: self.save_current(), keys.Save)
      ## Save everything.
      self.save_all_action = self._action(m, "Save a&ll", lambda: self.save_all(), keys.SaveAs)
      m.addSeparator()
      self._action(m, "&Quit", lambda: self.close(), keys.Quit)
      m = self.menuBar().addMenu("&Edit")
      ## Undo in the current source.
      self.undo_action = self._action(m, "Undo", lambda: self._editor_call("undo"), keys.Undo)
      ## Redo in the current source.
      self.redo_action = self._action(m, "Redo", lambda: self._editor_call("redo"), keys.Redo)
      m = self.menuBar().addMenu("&Script")
      ## Check now.
      self.check_action = self._action(m, "&Check", lambda: self.check(), "F7")
      self._action(m, "&Declare flag or variable...", lambda: self.declare())
      self._action(m, "&Rename...", lambda: self.rename(), "F2")
      ## [S2] Script > Insert statement: the I4 statements' templates.
      self.insert_menu = m.addMenu("&Insert statement")
      for word in script_words.STATEMENT_TEMPLATES:
         self._action(self.insert_menu, word, lambda w=word: self.insert_statement(w))
      self._action(m, "Complete &word", lambda: self._editor_complete(), "Ctrl+Space")
      ## Actions that need an open manifest.
      self.project_actions = [self.add_action, self.save_all_action, self.check_action]
      ## Help > Record performance.
      self.recorder = profiler.add_menu(self, "script-editor")
      ## Toolbar.
      self.file_bar = file_toolbar(self, [
         ("open", self.open_action, "Open a scripts manifest (scripts.json)", "Open"),
         ("new", self.new_action, "Create a scripts manifest", "New"),
         None,
         ("save", self.save_action, "Save the source in this tab"),
         ("save_all", self.save_all_action, "Save every source and the manifest"),
         None,
         ("undo", self.undo_action, "Undo in this source"),
         ("redo", self.redo_action, "Redo in this source"),
         None,
         ("check", self.check_action, "Check with the engine's compiler now", "Check")])

   # -- window --------------------------------------------------------------------

   def dialog_parent(self) -> QtWidgets.QWidget:
      """!Window dialogs belong to.
      @return QWidget
      """
      return self.start if self.start.isVisible() else self

   def show_editor(self) -> None:
      """!Shows the editor instead of the start window.
      @return None
      """
      self.start.hide()
      self.show()
      if self.project is None:
         self.statusBar().showMessage("No scripts open: File > Open scripts... or New scripts...", STATUS_MS)

   def launch(self) -> None:
      """!Shows the editor when something is open, else the start window.
      @return None
      """
      if self.project is not None:
         self.show()
      else:
         self.start.refresh()
         self.start.show()

   def current_source(self) -> str | None:
      """!The source in the front tab.
      @return relative path, or None
      """
      w = self.tabs.currentWidget()
      for rel, ed in self.editors.items():
         if ed is w:
            return rel
      return None

   def _editor_call(self, name: str) -> None:
      """!Calls undo() / redo() on the front editor, or on the placeholder history while the Placeholders tab is
      in front.
      @param name  method name
      @return None
      """
      if self.project is not None and self.side_tabs.currentWidget() is self.placeholders:
         if getattr(placeholders, name)(self.project):
            self._sync_editors()
            self.placeholders.refresh()
            self.check()
            self._update_title()
         return
      w = self.tabs.currentWidget()
      if isinstance(w, CodeEditor):
         getattr(w, name)()

   def _update_title(self) -> None:
      """!Title, tab marks and enabled actions.
      @return None
      """
      p = self.project
      if p is None:
         self.setWindowTitle("CapsuleCreatures Script Editor")
      else:
         mark = " *" if p.dirty else ""
         self.setWindowTitle(f"{p.path.parent.name}/{p.path.name}{mark} - CapsuleCreatures Script Editor")
         dirty = set(p.dirty_files())
         for i in range(self.tabs.count()):
            rel = self.tabs.widget(i).property("source")
            self.tabs.setTabText(i, Path(rel).name + (" *" if rel in dirty else ""))
      for a in self.project_actions:
         a.setEnabled(p is not None)
      w = self.tabs.currentWidget()
      doc = w.document() if isinstance(w, CodeEditor) else None
      self.undo_action.setEnabled(doc is not None and doc.isUndoAvailable())
      self.redo_action.setEnabled(doc is not None and doc.isRedoAvailable())
      rel = self.current_source()
      self.save_action.setEnabled(p is not None and rel is not None and rel in p.dirty_files())

   # -- project -------------------------------------------------------------------

   def _attach(self, project: scripts.ScriptProject) -> None:
      """!Shows a project.
      @param project  ScriptProject
      @return None
      """
      self.project = project
      self.tabs.clear()
      self.editors = {}
      for rel in project.sources:
         self._add_tab(rel)
      self._load_settings()
      self.start.hide()
      if not self.isVisible():
         self.show()
      remember_file("script-editor", project.path)
      self.check()

   def _add_tab(self, rel: str) -> None:
      """!Adds an editor tab for a source.
      @param rel  source path
      @return None
      """
      ed = CodeEditor()
      ed.setProperty("source", rel)
      ed.setPlainText(self.project.texts.get(rel, ""))
      ed.document().setModified(False)
      if rel in self.project.unreadable:
         ed.setReadOnly(True)
         ed.setPlaceholderText(f"{rel} is not UTF-8 text: convert it to UTF-8 to edit it here")
      ed.set_completion_source(lambda text: self.completions(text))   # [S2]
      ed.word_help = script_words.word_help   # [S5] route steps' help under the mouse
      ed.textChanged.connect(lambda r=rel, e=ed: self._text_changed(r, e))
      ed.document().undoAvailable.connect(lambda _a: self._update_title())
      ed.document().redoAvailable.connect(lambda _a: self._update_title())
      self.editors[rel] = ed
      self.tabs.addTab(ed, Path(rel).name)
      self.tabs.setTabToolTip(self.tabs.count() - 1, rel)

   def _text_changed(self, rel: str, editor: CodeEditor) -> None:
      """!A source buffer changed: keep it and check again soon.
      @param rel     source path
      @param editor  its CodeEditor
      @return None
      """
      if self.project is None:
         return
      self.project.set_text(rel, editor.toPlainText())
      self.recheck.poke()
      self._update_title()

   def _load_settings(self) -> None:
      """!Fills the settings fields from the manifest.
      @return None
      """
      p = self.project
      self._settings_loading = True
      self.game.setText(p.setting("game", "") or "")
      self.games.setText(", ".join(p.setting("games", []) or []))
      self.depth.setValue(p.setting("stack_depth", DEFAULT_STACK_DEPTH))
      self.assets.setText(p.setting("assets", "") or "")
      self.world.setText(p.setting("world", "") or "")
      try:
         self.object_base.setRange(0, getattr(scripts.compiler(), "MAX_OBJECT_BASE", 0))
      except engine.EngineNotFound:
         self.object_base.setRange(0, 0)
      self.object_base.setValue(p.setting("object_base", 0) or 0)
      self.warn_unused.setChecked(p.setting("warn_unused", True) is not False)
      self.glitches.clear()
      for gid, on in (p.setting("glitches") or {}).items():
         item = QtWidgets.QListWidgetItem(gid)
         item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
         item.setCheckState(QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)
         self.glitches.addItem(item)
      vm = p.setting("vm") or {}
      for switch, box in self.vm_boxes.items():   # [S4] a switch left out is the engine's own (the first value)
         box.setCurrentText(str(vm.get(switch, box.itemText(0))))
      self._settings_loading = False

   def _settings_changed(self) -> None:
      """!Writes the settings fields into the manifest and checks again.
      @return None
      """
      p = self.project
      if p is None or self._settings_loading is True:
         return
      games = [g.strip() for g in self.games.text().split(",") if g.strip()]
      wanted = {"game": self.game.text().strip() or None, "games": games or None,
                "stack_depth": self.depth.value(), "assets": self._relative(self.assets.text().strip()),
                "world": self._relative(self.world.text().strip()),
                # [S2] I4: written only when they differ from the compiler's defaults
                "object_base": self.object_base.value() or None,
                "warn_unused": None if self.warn_unused.isChecked() else False}
      # [S4] the vm switches that differ from the engine's own behaviour (none: the key is left out)
      vm = {k: b.currentText() for k, b in self.vm_boxes.items() if b.currentIndex() > 0}
      wanted["vm"] = vm or None
      if p.setting("glitches") is not None:
         wanted["glitches"] = {self.glitches.item(i).text():
                               self.glitches.item(i).checkState() == QtCore.Qt.CheckState.Checked
                               for i in range(self.glitches.count())}
      try:
         for key, value in wanted.items():
            # The default depth is not written into a manifest that leaves it unset.
            default_depth = key == "stack_depth" and value == DEFAULT_STACK_DEPTH and p.setting(key) is None
            # [S2] a written default (object_base 0, warn_unused true) stays as written
            same = (key == "object_base" and (p.setting(key) or 0) == (value or 0)) or \
               (key == "warn_unused" and (p.setting(key) is not False) == (value is None)) or \
               (key == "vm" and _vm_same(p.setting(key), value, self.vm_boxes))
            if p.setting(key) != value and not default_depth and not same:
               p.set_setting(key, value)
      except scripts.ScriptsError as e:
         QtWidgets.QMessageBox.warning(self, "Settings", str(e))
         self._load_settings()
         return
      self.check()
      self._update_title()

   def _relative(self, text: str) -> str | None:
      """!A manifest path setting, relative to scripts.json (P: paths stay relative).
      @param text  typed path, or ''
      @return relative POSIX path, or None when empty
      """
      if not text:
         return None
      p = Path(text)
      if p.is_absolute():
         p = Path(os.path.relpath(p, self.project.path.parent))
      return p.as_posix()

   # -- checking ------------------------------------------------------------------

   def check(self) -> scripts.CheckResult | None:
      """!Compiles the buffers and shows the problems and the outline.
      @return CheckResult, or None without a project
      """
      if self.project is None:
         return None
      try:
         self.result = self.project.check()
      except engine.EngineNotFound as e:
         self.summary.setText(str(e))
         return None
      except Exception as e:   # a compiler defect must not stop the live check
         self.summary.setText(f"The script compiler failed: {type(e).__name__}: {e}")
         self.statusBar().showMessage("The script compiler failed; see the settings panel", STATUS_MS)
         return None
      r = self.result
      self.problems.clear()
      marks = {rel: [] for rel in self.editors}
      for d in r.diagnostics:
         where = d.file or self.project.path.name
         if d.line:
            where += f":{d.line}"
         item = QtWidgets.QTreeWidgetItem([d.severity, where, d.message])
         item.setData(0, QtCore.Qt.ItemDataRole.UserRole, (d.file, d.line, d.col))
         item.setForeground(0, QtGui.QColor("#d04040" if d.severity == "error" else "#b08010"))
         self.problems.addTopLevelItem(item)
         if d.file in marks and d.line:
            marks[d.file].append((d.line, d.col, d.severity, d.message))
      for rel, ed in self.editors.items():
         ed.set_marks(marks.get(rel, []))
      self._fill_outline()
      self.summary.setText(r.summary())
      self.statusBar().showMessage(("Compiles: " if r.ok else "Does not compile: ") + r.summary())
      self.placeholders.refresh()   # use counts and the compiler's verdict
      return r

   def _fill_outline(self) -> None:
      """!Rebuilds the outline from the last check.
      @return None
      """
      # Which groups were open, by heading, so a new check keeps them as they were.
      expanded = {self.outline.topLevelItem(i).text(0): self.outline.topLevelItem(i).isExpanded()
                  for i in range(self.outline.topLevelItemCount())}
      self.outline.clear()
      src = QtWidgets.QTreeWidgetItem(["Sources", str(len(self.project.sources))])
      for rel in self.project.sources:
         child = QtWidgets.QTreeWidgetItem([rel, ""])
         child.setData(0, QtCore.Qt.ItemDataRole.UserRole, (rel, 1))
         src.addChild(child)
      self.outline.addTopLevelItem(src)
      src.setExpanded(expanded.get("Sources", True))
      for kind, heading in OUTLINE_GROUPS:
         items = self.result.outline.items[kind]
         group = QtWidgets.QTreeWidgetItem([heading, str(len(items))])
         for i in items:
            child = QtWidgets.QTreeWidgetItem([i["name"], i["detail"]])
            child.setData(0, QtCore.Qt.ItemDataRole.UserRole, (i["file"], i["line"]))
            child.setData(1, QtCore.Qt.ItemDataRole.UserRole, i["name"])
            child.setToolTip(0, f"{i['file']}:{i['line']}")
            group.addChild(child)
         self.outline.addTopLevelItem(group)
         group.setExpanded(expanded.get(heading, kind in ("script", "flag", "var")))

   def go_to(self, rel: str, line: int, col: int = 1) -> None:
      """!Shows a source at a position.
      @param rel   source path
      @param line  1-based line
      @param col   1-based column
      @return None
      """
      ed = self.editors.get(rel)
      if ed is None:
         return
      self.tabs.setCurrentWidget(ed)
      ed.go_to(line, col)

   def _jump_to_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
      """!Outline double-click.
      @param item  QTreeWidgetItem
      @return None
      """
      data = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
      if data:
         self.go_to(data[0], data[1])

   def _jump_to_problem(self, item: QtWidgets.QTreeWidgetItem) -> None:
      """!Problems double-click.
      @param item  QTreeWidgetItem
      @return None
      """
      f, line, col = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
      if f:
         self.go_to(f, line or 1, col or 1)

   # -- completion and templates [S2] ----------------------------------------------------

   def completions(self, text: str) -> list[str]:
      """!The words that fit at the end of a text (the source before the cursor): core.script_words.completions()
      with the names the last check declared.
      @param text  the source up to the cursor
      @return words
      """
      try:
         return script_words.completions(text, script_words.check_names(self.result))   # S3: + override sets
      except engine.EngineNotFound:
         return []

   def _editor_complete(self) -> None:
      """!Opens the front editor's completion list.
      @return None
      """
      w = self.tabs.currentWidget()
      if isinstance(w, CodeEditor):
         w.show_completions(forced=True)

   def insert_statement(self, word: str) -> None:
      """!Inserts an I4 statement's template at the front editor's cursor (its names are examples to change).
      @param word  a key of core.script_words.STATEMENT_TEMPLATES
      @return None
      """
      w = self.tabs.currentWidget()
      if isinstance(w, CodeEditor) and not w.isReadOnly():
         w.textCursor().insertText(script_words.STATEMENT_TEMPLATES[word])
         w.setFocus()

   # -- editing tools -----------------------------------------------------------

   def _sync_editors(self, only: str | None = None) -> None:
      """!Puts project texts changed by a tool back into their editors
      (as one undoable step each).
      @param only  source to sync, or None for all
      @return None
      """
      for rel, ed in self.editors.items():
         if only is not None and rel != only:
            continue
         text = self.project.texts.get(rel, "")
         if ed.toPlainText() != text:
            cur = QtGui.QTextCursor(ed.document())
            cur.beginEditBlock()
            cur.select(QtGui.QTextCursor.SelectionType.Document)
            cur.insertText(text)
            cur.endEditBlock()

   def placeholder_edit(self, label: str, fn: Callable[[], object]) -> bool:
      """!Runs a placeholder / term edit as one step of the placeholder history (core.placeholders.edit()); the
      editors take renamed texts and the sources are checked again. A refused edit shows in the status bar.
      @param label  undo label
      @param fn     callable
      @return True when it went through
      """
      if self.project is None:
         return False
      try:
         with placeholders.edit(self.project, label):
            fn()
      except (DocumentError, ValueError, TypeError) as e:
         self.statusBar().showMessage(f"{label}: {e}", STATUS_MS)
         return False
      self._sync_editors()
      self.check()
      self._update_title()
      return True

   def declare(self, kind: str = "flag") -> None:
      """!Declare dialog.
      @param kind  'flag' or 'var' preselected
      @return None
      """
      if self.project is None or not self.project.sources:
         return
      d = DeclareDialog(self, self.project.sources, kind, self.project.setting("vm"))
      cur = self.current_source()
      if cur:
         d.source.setCurrentText(cur)
      if d.exec() != QtWidgets.QDialog.DialogCode.Accepted:
         return
      lo = hi = None
      if d.kind.currentText() == "var" and d.ranged.isChecked():
         lo, hi = d.lo.value(), d.hi.value()
      rel = d.source.currentText()
      try:
         line = self.project.declare(rel, d.kind.currentText(), d.name.text().strip(),
                                     d.lifetime.currentText(), d.type.currentText(), lo, hi)
      except scripts.ScriptsError as e:
         QtWidgets.QMessageBox.warning(self, "Declare", str(e))
         return
      self._sync_editors(rel)
      self.statusBar().showMessage(f"{rel}: {line}", STATUS_MS)
      self.check()

   def rename(self) -> None:
      """!Renames the outline's selected declaration (or asks for a name).
      @return None
      """
      if self.project is None:
         return
      item = self.outline.currentItem()
      old = item.data(1, QtCore.Qt.ItemDataRole.UserRole) if item is not None else None
      if not old:
         old, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name to rename:")
         if not ok or not old.strip():
            return
         old = old.strip()
      new, ok = QtWidgets.QInputDialog.getText(self, "Rename", f"New name for {old}:", text=old)
      if not ok or not new.strip() or new.strip() == old:
         return
      try:
         n = self.project.rename(old, new.strip())
      except scripts.ScriptsError as e:
         QtWidgets.QMessageBox.warning(self, "Rename", str(e))
         return
      self._sync_editors()
      self.statusBar().showMessage(f"Renamed {old} to {new.strip()} in {n} place(s)", STATUS_MS)
      self.check()

   def add_source(self) -> None:
      """!Adds a source file (new or existing).
      @return None
      """
      if self.project is None:
         return
      path, _ = QtWidgets.QFileDialog.getSaveFileName(
         self, "Add a source", str(self.project.path.parent / "new.cscript"), "Scripts (*.cscript)",
         options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
      if not path:
         return
      try:
         rel = Path(os.path.relpath(Path(path).resolve(), self.project.path.parent.resolve())).as_posix()
      except ValueError:   # another drive (Windows): a relative path is impossible
         QtWidgets.QMessageBox.warning(self, "Add source", "Sources must be on the same drive as scripts.json.")
         return
      try:
         self.project.add_source(rel)
      except scripts.ScriptsError as e:
         QtWidgets.QMessageBox.warning(self, "Add source", str(e))
         return
      self._add_tab(rel)
      self.tabs.setCurrentWidget(self.editors[rel])
      self.check()
      self._update_title()

   # -- files ---------------------------------------------------------------------

   def _confirm_discard(self) -> bool:
      """!Asks about unsaved changes.
      @return True to go ahead
      """
      if self.project is None or not self.project.dirty:
         return True
      b = QtWidgets.QMessageBox.StandardButton
      answer = QtWidgets.QMessageBox.question(self.dialog_parent(), "Unsaved changes", "Save all changes first?",
                                              b.Save | b.Discard | b.Cancel, b.Save)
      if answer == b.Save:
         return self.save_all()
      return answer == b.Discard

   def new_project(self) -> None:
      """!Creates a scripts manifest in a chosen folder.
      @return None
      """
      if not self._confirm_discard():
         return
      path, _ = QtWidgets.QFileDialog.getSaveFileName(self.dialog_parent(), "New scripts manifest", "scripts.json",
                                                      SCRIPTS_FILTER)
      if not path:
         return
      try:
         self._attach(scripts.ScriptProject.create(path))
      except (scripts.ScriptsError, OSError) as e:
         QtWidgets.QMessageBox.warning(self.dialog_parent(), "New scripts", str(e))

   def open_project(self, path: str | Path | None = None) -> None:
      """!Opens a scripts manifest.
      @param path  scripts.json, or None to ask
      @return None
      """
      if not self._confirm_discard():
         return
      if path is None:
         path, _ = QtWidgets.QFileDialog.getOpenFileName(self.dialog_parent(), "Open scripts", "", SCRIPTS_FILTER)
         if not path:
            return
      try:
         self._attach(scripts.ScriptProject.open(path))
      except (scripts.ScriptsError, OSError) as e:
         QtWidgets.QMessageBox.warning(self.dialog_parent(), "Open scripts", f"{path}: {e}")

   def save_current(self) -> bool:
      """!Saves the source in the front tab.
      @return True when saved
      """
      rel = self.current_source()
      if self.project is None or rel is None:
         return True
      try:
         self.project.save(rel)
      except OSError as e:
         QtWidgets.QMessageBox.warning(self, "Save", str(e))
         return False
      self.statusBar().showMessage(f"Saved {rel}", STATUS_MS)
      self._update_title()
      return True

   def save_all(self) -> bool:
      """!Saves every source and the manifest.
      @return True when saved
      """
      if self.project is None:
         return True
      try:
         self.project.save()
      except OSError as e:
         QtWidgets.QMessageBox.warning(self, "Save", str(e))
         return False
      self.statusBar().showMessage("Saved", STATUS_MS)
      self._update_title()
      return True

   def closeEvent(self, event: QtGui.QCloseEvent) -> None:
      """!Asks about unsaved changes before closing.
      @param event  QCloseEvent
      @return None
      """
      if self._confirm_discard():
         event.accept()
      else:
         event.ignore()


def _vm_same(written: dict | None, wanted: dict | None, boxes: dict[str, QtWidgets.QComboBox]) -> bool:
   """![S4] Whether two vm settings mean the same (a switch written with the engine's own value is left out).
   @param written  the manifest's vm
   @param wanted   the form's
   @param boxes    the switches' combos (their first value is the engine's own)
   @return True when they do
   """
   def meant(vm: dict | None) -> dict:
      """!The switches that differ from the engine's own behaviour."""
      return {k: v for k, v in (vm or {}).items() if k not in boxes or v != boxes[k].itemText(0)}
   return meant(written) == meant(wanted)
